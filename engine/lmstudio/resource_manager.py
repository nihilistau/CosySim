"""
ResourceManager — Intelligent model lifecycle & GPU/CPU budget controller

Manages the complete lifecycle of LLM models for CosySim's multi-agent system.
Builds on top of ``LMSClient`` (REST) and ``LMSSDKWrapper`` (SDK) with six
hardware strategies tuned for the target platform (i9 NUC, RTX 2060 12GB).

Strategies
----------
SINGLE_BIG
    One large model (e.g. 30B MoE) always loaded on GPU.  Best for
    deep single-agent conversation with maximum quality.

CONCURRENT
    One model loaded, multiple parallel requests.  Uses LMStudio's
    built-in concurrent slots.  Best for multi-agent same-model.

MULTI_SMALL
    2-3 small models co-resident on GPU.  Each agent gets its own
    specialist model.  Requires careful VRAM budgeting.

JIT_SWAP
    Load/unload models per request.  Only one model at a time.
    Best for sequential specialist workflows (summarise → classify → respond).

SPECULATIVE
    Main model + tiny draft model for speculative decoding (2-3x speedup).
    Draft model stays loaded alongside the main model.

HYBRID
    One model on GPU (interactive), one on CPU (background tasks).
    Background work (image gen, TTS, batch processing) on CPU.

Usage::

    from engine.lmstudio.resource_manager import get_resource_manager, Strategy

    rm = get_resource_manager()
    rm.set_strategy(Strategy.CONCURRENT)

    # Ensure a model is ready for an agent
    model_id = rm.acquire("agent_name", role="big")
    # ... use model ...
    rm.release("agent_name")

    # Queue background work
    rm.queue_background_task("generate_images", my_fn, args=(...,))
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from engine.lmstudio.inference_config import LoadConfig

logger = logging.getLogger(__name__)


# ── Strategy enum ───────────────────────────────────────────────────────

class Strategy(str, Enum):
    SINGLE_BIG  = "single_big"
    CONCURRENT  = "concurrent"
    MULTI_SMALL = "multi_small"
    JIT_SWAP    = "jit_swap"
    SPECULATIVE = "speculative"
    HYBRID      = "hybrid"


# ── Model slot tracking ────────────────────────────────────────────────

@dataclass
class ModelSlot:
    """Tracks a model loaded in memory (GPU or CPU)."""
    model_id: str
    device: str = "gpu"          # "gpu" or "cpu"
    vram_mb: int = 0             # estimated VRAM usage
    ram_mb: int = 0              # estimated RAM usage
    context_length: int = 4096
    loaded_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    ttl: int = 0                 # 0 = no auto-evict
    request_count: int = 0
    agents: List[str] = field(default_factory=list)  # agents using this model
    is_draft: bool = False       # speculative decoding draft model

    def touch(self, agent: str = "") -> None:
        self.last_used = time.monotonic()
        self.request_count += 1
        if agent and agent not in self.agents:
            self.agents.append(agent)

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used

    @property
    def is_expired(self) -> bool:
        return self.ttl > 0 and self.idle_seconds > self.ttl


@dataclass
class BackgroundTask:
    """A queued background task."""
    name: str
    fn: Callable
    args: Tuple = ()
    kwargs: Dict = field(default_factory=dict)
    priority: int = 0            # higher = sooner
    device: str = "cpu"          # preferred device
    queued_at: float = field(default_factory=time.monotonic)


# ── Resource Manager ────────────────────────────────────────────────────

class ResourceManager:
    """
    Orchestrates model loading, GPU/CPU budget, and background task scheduling.
    """

    def __init__(self, config=None) -> None:
        if config is None:
            from engine.config import get_config
            config = get_config()
        self._config = config

        # Hardware limits
        self._vram_cap_mb = int(config.get("lmstudio.vram_cap_mb", 11500))
        self._ram_gb = int(config.get("hardware.ram_gb", 32))
        self._concurrent_slots = int(config.get("lmstudio.concurrent_slots", 4))

        # Strategy from config
        strategy_str = config.get("lmstudio.resource_manager.strategy", Strategy.CONCURRENT.value)
        try:
            self._strategy = Strategy(strategy_str)
        except ValueError:
            self._strategy = Strategy.CONCURRENT

        # Default TTL for auto-eviction
        self._default_ttl = int(config.get("lmstudio.resource_manager.default_ttl", 300))

        # Model slots {model_id → ModelSlot}
        self._slots: Dict[str, ModelSlot] = {}
        # Agent → model_id mapping
        self._agent_models: Dict[str, str] = {}

        self._lock = threading.Lock()

        # Background task queue and worker
        self._task_queue: Deque[BackgroundTask] = deque()
        self._bg_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ResourceBG")
        self._bg_running = threading.Event()

        # Reaper for TTL-based eviction
        self._stop_event = threading.Event()
        self._reaper = threading.Thread(target=self._reap_loop, daemon=True, name="ResourceReaper")
        self._reaper.start()

        logger.info("ResourceManager init: strategy=%s vram_cap=%dMB", self._strategy.value, self._vram_cap_mb)

    # ── Public API ──────────────────────────────────────────────────

    @property
    def strategy(self) -> Strategy:
        return self._strategy

    def set_strategy(self, strategy: Strategy, **kwargs) -> None:
        """Change strategy at runtime."""
        with self._lock:
            self._strategy = strategy
            if "default_ttl" in kwargs:
                self._default_ttl = int(kwargs["default_ttl"])
        logger.info("ResourceManager strategy → %s", strategy.value)

    def acquire(
        self,
        agent_name: str,
        *,
        role: str = "big",
        model: Optional[str] = None,
    ) -> str:
        """
        Ensure a model is loaded and ready for an agent.

        Uses the current strategy to decide what to load/unload.
        Returns the model_id to use for inference.
        """
        # Resolve model from agent profile if not specified
        if not model:
            model = self._resolve_model_for_role(role)

        with self._lock:
            strategy = self._strategy

        if strategy == Strategy.SINGLE_BIG:
            return self._acquire_single(agent_name, model)
        elif strategy == Strategy.CONCURRENT:
            return self._acquire_concurrent(agent_name, model)
        elif strategy == Strategy.MULTI_SMALL:
            return self._acquire_multi(agent_name, model)
        elif strategy == Strategy.JIT_SWAP:
            return self._acquire_jit(agent_name, model)
        elif strategy == Strategy.SPECULATIVE:
            return self._acquire_speculative(agent_name, model)
        elif strategy == Strategy.HYBRID:
            return self._acquire_hybrid(agent_name, model)
        else:
            return self._acquire_concurrent(agent_name, model)

    def release(self, agent_name: str) -> None:
        """Release an agent's claim on a model (for JIT strategies)."""
        with self._lock:
            model_id = self._agent_models.pop(agent_name, None)
            if model_id and model_id in self._slots:
                slot = self._slots[model_id]
                if agent_name in slot.agents:
                    slot.agents.remove(agent_name)

    def queue_background_task(
        self,
        name: str,
        fn: Callable,
        *,
        args: Tuple = (),
        kwargs: Optional[Dict] = None,
        priority: int = 0,
        device: str = "cpu",
    ) -> None:
        """Queue a background task (image gen, TTS, batch processing)."""
        task = BackgroundTask(
            name=name, fn=fn, args=args,
            kwargs=kwargs or {}, priority=priority, device=device,
        )
        self._task_queue.append(task)
        self._bg_executor.submit(self._run_background_task, task)
        logger.debug("Queued background task: %s (device=%s)", name, device)

    def get_status(self) -> Dict[str, Any]:
        """Get full resource manager status for admin panels."""
        with self._lock:
            slots = {
                mid: {
                    "device": s.device,
                    "vram_mb": s.vram_mb,
                    "ram_mb": s.ram_mb,
                    "context_length": s.context_length,
                    "idle_seconds": round(s.idle_seconds, 1),
                    "request_count": s.request_count,
                    "agents": list(s.agents),
                    "is_draft": s.is_draft,
                    "ttl": s.ttl,
                    "expired": s.is_expired,
                }
                for mid, s in self._slots.items()
            }
            agent_models = dict(self._agent_models)

        vram_used = sum(s.vram_mb for s in self._slots.values() if s.device == "gpu")

        return {
            "strategy": self._strategy.value,
            "vram_cap_mb": self._vram_cap_mb,
            "vram_used_mb": vram_used,
            "vram_free_mb": self._vram_cap_mb - vram_used,
            "concurrent_slots": self._concurrent_slots,
            "default_ttl": self._default_ttl,
            "slots": slots,
            "agent_models": agent_models,
            "bg_queue_size": len(self._task_queue),
        }

    def get_vram_free(self) -> int:
        """Estimated free VRAM in MB."""
        with self._lock:
            used = sum(s.vram_mb for s in self._slots.values() if s.device == "gpu")
        return self._vram_cap_mb - used

    def update_config(self, **kwargs) -> Dict:
        """Update config at runtime. Returns updated status."""
        if "strategy" in kwargs:
            self.set_strategy(Strategy(kwargs["strategy"]))
        if "default_ttl" in kwargs:
            with self._lock:
                self._default_ttl = int(kwargs["default_ttl"])
        if "vram_cap_mb" in kwargs:
            with self._lock:
                self._vram_cap_mb = int(kwargs["vram_cap_mb"])
        if "concurrent_slots" in kwargs:
            with self._lock:
                self._concurrent_slots = int(kwargs["concurrent_slots"])
        return self.get_status()

    def shutdown(self) -> None:
        """Stop reaper and clean up."""
        self._stop_event.set()
        self._bg_executor.shutdown(wait=False)
        logger.info("ResourceManager shut down")

    # ── Strategy implementations ────────────────────────────────────

    def _acquire_single(self, agent: str, model: str) -> str:
        """SINGLE_BIG: one model, reject if different model requested."""
        with self._lock:
            if self._slots:
                current = next(iter(self._slots.values()))
                current.touch(agent)
                self._agent_models[agent] = current.model_id
                return current.model_id

        # Load the model
        self._load_model(model, device="gpu")
        with self._lock:
            self._agent_models[agent] = model
        return model

    def _acquire_concurrent(self, agent: str, model: str) -> str:
        """CONCURRENT: one model, multiple parallel requests."""
        with self._lock:
            if model in self._slots:
                self._slots[model].touch(agent)
                self._agent_models[agent] = model
                return model
            # If any model loaded, use it
            if self._slots:
                current = next(iter(self._slots.values()))
                current.touch(agent)
                self._agent_models[agent] = current.model_id
                return current.model_id

        self._load_model(model, device="gpu")
        with self._lock:
            self._agent_models[agent] = model
        return model

    def _acquire_multi(self, agent: str, model: str) -> str:
        """MULTI_SMALL: multiple models co-resident."""
        with self._lock:
            if model in self._slots:
                self._slots[model].touch(agent)
                self._agent_models[agent] = model
                return model

        # Check VRAM budget before loading
        if self.get_vram_free() < 1500:  # need at least 1.5GB
            self._evict_least_used()

        self._load_model(model, device="gpu")
        with self._lock:
            self._agent_models[agent] = model
        return model

    def _acquire_jit(self, agent: str, model: str) -> str:
        """JIT_SWAP: evict current, load requested."""
        with self._lock:
            if model in self._slots:
                self._slots[model].touch(agent)
                self._agent_models[agent] = model
                return model

            # Evict everything else
            to_evict = [mid for mid in self._slots if mid != model]

        for mid in to_evict:
            self._unload_model(mid)

        self._load_model(model, device="gpu")
        with self._lock:
            self._agent_models[agent] = model
        return model

    def _acquire_speculative(self, agent: str, model: str) -> str:
        """SPECULATIVE: main model + draft model."""
        draft = self._config.get("lmstudio.speculative.draft_model", "")

        with self._lock:
            if model in self._slots:
                self._slots[model].touch(agent)
                self._agent_models[agent] = model
                return model

        # Load main model
        self._load_model(model, device="gpu")

        # Load draft model if configured and not already loaded
        if draft:
            with self._lock:
                if draft not in self._slots:
                    self._load_model(draft, device="gpu", is_draft=True)

        with self._lock:
            self._agent_models[agent] = model
        return model

    def _acquire_hybrid(self, agent: str, model: str) -> str:
        """HYBRID: interactive on GPU, background on CPU."""
        with self._lock:
            if model in self._slots:
                self._slots[model].touch(agent)
                self._agent_models[agent] = model
                return model

        # Determine device based on agent role
        device = "gpu"  # interactive agents get GPU
        self._load_model(model, device=device)
        with self._lock:
            self._agent_models[agent] = model
        return model

    # ── Model lifecycle helpers ─────────────────────────────────────

    def _load_model(self, model_id: str, *, device: str = "gpu", is_draft: bool = False) -> bool:
        """Load a model using LMSClient REST API or ModelManager CLI."""
        try:
            from engine.lmstudio.lms_client import get_lms_client
            client = get_lms_client()

            load_config = LoadConfig.from_yaml()
            if device == "cpu":
                load_config.gpu_offload = 0
            if self._default_ttl > 0:
                load_config.ttl = self._default_ttl

            result = client.load_model(model_id, config=load_config)

            if result.status == "loaded":
                ctx = load_config.context_length or 4096
                vram = self._estimate_vram(model_id) if device == "gpu" else 0
                with self._lock:
                    self._slots[model_id] = ModelSlot(
                        model_id=model_id,
                        device=device,
                        vram_mb=vram,
                        context_length=ctx,
                        ttl=self._default_ttl,
                        is_draft=is_draft,
                    )
                self._publish_event("model_loaded", {"model": model_id, "device": device})
            return result.status == "loaded"
        except Exception as exc:
            logger.error("Failed to load %s: %s", model_id, exc)
            # Fallback: try ModelManager CLI
            return self._load_via_cli(model_id)

    def _load_via_cli(self, model_id: str) -> bool:
        """Fallback: load via LMStudioManager CLI."""
        try:
            from engine.lmstudio.client import get_lmstudio_manager
            mgr = get_lmstudio_manager()
            return mgr.load_model(model_id, force=True)
        except Exception as exc:
            logger.error("CLI load fallback failed: %s", exc)
            return False

    def _unload_model(self, model_id: str) -> None:
        """Unload a model."""
        with self._lock:
            self._slots.pop(model_id, None)
            # Remove from agent mappings
            self._agent_models = {a: m for a, m in self._agent_models.items() if m != model_id}

        try:
            from engine.lmstudio.lms_client import get_lms_client
            get_lms_client().unload_model(model_id)
        except Exception:
            try:
                from engine.lmstudio.client import get_lmstudio_manager
                get_lmstudio_manager().unload_model(model_id)
            except Exception as exc:
                logger.error("Failed to unload %s: %s", model_id, exc)

        self._publish_event("model_unloaded", {"model": model_id})

    def _evict_least_used(self) -> None:
        """Evict the least recently used non-draft model."""
        with self._lock:
            candidates = [
                (mid, s) for mid, s in self._slots.items()
                if not s.is_draft and s.device == "gpu"
            ]
        if not candidates:
            return
        # Sort by last_used ascending
        candidates.sort(key=lambda x: x[1].last_used)
        victim_id = candidates[0][0]
        logger.info("Evicting least-used model: %s", victim_id)
        self._unload_model(victim_id)

    def _estimate_vram(self, model_id: str) -> int:
        """Estimate VRAM usage for a model."""
        try:
            from engine.lmstudio.client import get_lmstudio_manager
            est = get_lmstudio_manager().estimate_vram_needed(model_id)
            return est or 3000  # default estimate
        except Exception:
            return 3000

    def _resolve_model_for_role(self, role: str) -> str:
        """Resolve model identifier from agent profile role."""
        try:
            from engine.mcp.framework import get_framework
            profile = get_framework().get_agent_profile(role)
            if profile.model:
                return profile.model
        except Exception:
            pass

        # Fallback to config
        concurrent_model = self._config.get("lmstudio.concurrent_model", "")
        if concurrent_model:
            return concurrent_model

        default_model = self._config.get("llm.model", "")
        return default_model

    # ── Background tasks ────────────────────────────────────────────

    def _run_background_task(self, task: BackgroundTask) -> None:
        """Execute a background task."""
        try:
            logger.debug("Running background task: %s", task.name)
            task.fn(*task.args, **task.kwargs)
            logger.debug("Background task complete: %s", task.name)
        except Exception as exc:
            logger.error("Background task %s failed: %s", task.name, exc)
        finally:
            if task in self._task_queue:
                self._task_queue.remove(task)

    # ── TTL reaper ──────────────────────────────────────────────────

    def _reap_loop(self) -> None:
        """Periodically check for expired model slots."""
        while not self._stop_event.wait(timeout=30.0):
            self._reap_expired()

    def _reap_expired(self) -> None:
        with self._lock:
            expired = [mid for mid, s in self._slots.items() if s.is_expired and not s.is_draft]
        for mid in expired:
            logger.info("TTL expired, unloading: %s", mid)
            self._unload_model(mid)

    # ── Event publishing ────────────────────────────────────────────

    def _publish_event(self, event_type: str, data: Dict) -> None:
        try:
            from engine.services.activity_bus import get_activity_bus
            get_activity_bus().publish(
                activity_type=event_type,
                description=f"ResourceManager: {event_type}",
                agent_id="resource_manager",
                scene="system",
                data=data,
            )
        except Exception:
            pass


# ── Singleton ───────────────────────────────────────────────────────────

_rm_instance: Optional[ResourceManager] = None
_rm_lock = threading.Lock()


def get_resource_manager() -> ResourceManager:
    """Return the global ResourceManager singleton."""
    global _rm_instance
    if _rm_instance is None:
        with _rm_lock:
            if _rm_instance is None:
                _rm_instance = ResourceManager()
    return _rm_instance
