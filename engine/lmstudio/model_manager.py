"""
ModelManager — Three-mode LMStudio model lifecycle controller

Three loading strategies for different use-cases:

CONCURRENT
    One model stays loaded permanently.  All agent requests are sent to it
    in parallel — LMStudio handles up to lmstudio.concurrent_slots requests
    simultaneously.  Best for a single capable model (e.g. Qwen-32B or a
    specialist router) that is always in VRAM.

JIT  (Just-In-Time, evict-on-next-load)
    Each named model is loaded when first requested.  When a *different*
    model is requested, the current one is unloaded first.  Only one model
    lives in VRAM at a time.  Great for large models that don't fit
    together, or for sequential specialist calls (summarise → classify →
    respond) that don't overlap in time.

JIT_TTL  (Just-In-Time with Time-To-Live)
    Models are loaded on first request and stay warm until they have been
    idle for ``ttl_seconds``.  Multiple small models can coexist if they
    all arrive within the TTL window — the framework tries to fit them in
    VRAM budget.  The background reaper thread unloads models that time out.
    Good for small specialists that get called sporadically.

Usage::

    from engine.lmstudio.model_manager import get_model_manager, LoadMode

    mgr = get_model_manager()
    mgr.set_mode(LoadMode.JIT_TTL, ttl_seconds=300)

    # Ensure a model is loaded before calling it
    model_id = mgr.ensure_loaded("lmstudio-community/Qwen2.5-7B-Instruct-GGUF")
    reply = client.chat(messages, model=model_id)

    # After you are done with a JIT model (optional manual evict):
    mgr.release("lmstudio-community/Qwen2.5-7B-Instruct-GGUF")
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Load strategy enum ─────────────────────────────────────────────────

class LoadMode(str, Enum):
    CONCURRENT = "concurrent"   # one model, N parallel slots
    JIT        = "jit"          # load on demand, evict on next load
    JIT_TTL    = "jit_ttl"      # load on demand, evict after idle timeout


# ── Model session tracking ─────────────────────────────────────────────

@dataclass
class ModelSession:
    """Runtime record for one loaded model."""
    model_key:    str
    loaded_at:    float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)
    request_count: int  = 0
    gpu_fraction:  float = 0.9
    context_length: int  = 4096
    ttl_seconds:   int   = 300   # 0 = never expire

    def touch(self) -> None:
        self.last_used_at = time.monotonic()
        self.request_count += 1

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used_at

    @property
    def is_expired(self) -> bool:
        return self.ttl_seconds > 0 and self.idle_seconds > self.ttl_seconds

    def __repr__(self) -> str:
        return (
            f"<ModelSession {self.model_key!r} "
            f"reqs={self.request_count} idle={self.idle_seconds:.0f}s>"
        )


# ── Core manager ───────────────────────────────────────────────────────

class ModelManager:
    """
    Controls which LMStudio models are loaded and when.

    Parameters
    ----------
    config : ConfigManager, optional
    cli_manager : LMStudioManager, optional
        The CLI-based lifecycle manager (load/unload/estimate).
    """

    _REAPER_INTERVAL = 30.0   # seconds between TTL reaper ticks

    def __init__(self, config=None, cli_manager=None) -> None:
        if config is None:
            from engine.config import get_config
            config = get_config()
        self.config = config

        if cli_manager is None:
            from engine.lmstudio.client import get_lmstudio_manager
            cli_manager = get_lmstudio_manager()
        self._cli = cli_manager

        # Mode from config, overrideable at runtime
        mode_str = config.get("lmstudio.load_mode", LoadMode.CONCURRENT.value)
        self._mode = LoadMode(mode_str)
        self._default_ttl     = int(config.get("lmstudio.jit_ttl_seconds", 300))
        self._default_gpu     = float(config.get("lmstudio.default_load_opts.gpu", 0.9))
        self._default_ctx     = int(config.get("lmstudio.default_load_opts.context_length", 4096))
        self._concurrent_model = config.get("lmstudio.concurrent_model", "")

        # Active sessions  {model_key → ModelSession}
        self._sessions: Dict[str, ModelSession] = {}
        self._lock = threading.Lock()

        # Background reaper (for JIT_TTL)
        self._reaper_thread: Optional[threading.Thread] = None
        self._stop_reaper = threading.Event()

        # Start reaper if mode is JIT_TTL
        if self._mode == LoadMode.JIT_TTL:
            self._start_reaper()

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def mode(self) -> LoadMode:
        return self._mode

    def set_mode(
        self,
        mode: LoadMode,
        *,
        ttl_seconds: Optional[int] = None,
        concurrent_model: Optional[str] = None,
    ) -> None:
        """
        Switch loading strategy at runtime.

        Args:
            mode: New ``LoadMode``.
            ttl_seconds: Override TTL for JIT_TTL mode.
            concurrent_model: Pin a specific model for CONCURRENT mode.
        """
        with self._lock:
            self._mode = mode
            if ttl_seconds is not None:
                self._default_ttl = ttl_seconds
            if concurrent_model is not None:
                self._concurrent_model = concurrent_model
        logger.info("ModelManager mode → %s (ttl=%ds)", mode.value, self._default_ttl)

        # Start/stop reaper as needed
        if mode == LoadMode.JIT_TTL:
            self._start_reaper()
        else:
            self._stop_reaper.set()

    def ensure_loaded(
        self,
        model_key: str,
        *,
        gpu: Optional[float] = None,
        context_length: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """
        Ensure *model_key* is loaded according to the current mode.

        Returns the model_key string to pass directly to
        ``LMStudioClient.chat(model=...)``.

        In CONCURRENT mode the ``concurrent_model`` config value is
        returned and always assumed to be loaded (load it via the CLI
        or LMStudio UI once, then leave it).

        In JIT mode the current model is evicted and *model_key* is loaded.

        In JIT_TTL mode *model_key* is loaded if not already present and
        its TTL is refreshed on each call.
        """
        gpu = gpu or self._default_gpu
        ctx = context_length or self._default_ctx
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl

        with self._lock:
            mode = self._mode

        if mode == LoadMode.CONCURRENT:
            return self._ensure_concurrent(model_key)
        elif mode == LoadMode.JIT:
            return self._ensure_jit(model_key, gpu=gpu, ctx=ctx)
        else:  # JIT_TTL
            return self._ensure_jit_ttl(model_key, gpu=gpu, ctx=ctx, ttl=ttl)

    def release(self, model_key: str) -> None:
        """
        Manually release (unload) a model.

        In CONCURRENT mode this is a no-op — the permanent model is managed
        by the operator, not the code.
        """
        with self._lock:
            if self._mode == LoadMode.CONCURRENT:
                return
            if model_key in self._sessions:
                del self._sessions[model_key]
        self._cli_unload(model_key)

    def list_sessions(self) -> List[ModelSession]:
        """Return a snapshot of all active ModelSessions."""
        with self._lock:
            return list(self._sessions.values())

    def status(self) -> Dict:
        """Return a status dict suitable for the admin panel."""
        sessions = self.list_sessions()
        loaded_via_lms = self._cli.list_loaded_models()
        return {
            "mode": self._mode.value,
            "default_ttl": self._default_ttl,
            "concurrent_model": self._concurrent_model,
            "tracked_sessions": [
                {
                    "model_key": s.model_key,
                    "loaded_at": s.loaded_at,
                    "idle_seconds": round(s.idle_seconds, 1),
                    "request_count": s.request_count,
                    "ttl_seconds": s.ttl_seconds,
                    "expired": s.is_expired,
                }
                for s in sessions
            ],
            "lmstudio_loaded": loaded_via_lms,
        }

    # ── Mode implementations ────────────────────────────────────────────

    def _ensure_concurrent(self, model_key: str) -> str:
        """CONCURRENT: return configured model (assumed always loaded)."""
        target = self._concurrent_model or model_key
        with self._lock:
            if target not in self._sessions:
                # Register a session just for tracking
                self._sessions[target] = ModelSession(
                    model_key=target,
                    ttl_seconds=0,  # never expire
                )
            self._sessions[target].touch()
        return target

    def _ensure_jit(self, model_key: str, *, gpu: float, ctx: int) -> str:
        """JIT: evict current model, load requested one."""
        with self._lock:
            current_keys = list(self._sessions.keys())

        # Evict anything that isn't what we want
        for key in current_keys:
            if key != model_key:
                logger.info("JIT: evicting %r to load %r", key, model_key)
                with self._lock:
                    self._sessions.pop(key, None)
                self._cli_unload(key)

        # Load new model if not already tracked
        with self._lock:
            if model_key not in self._sessions:
                loaded = self._cli_load(model_key, gpu=gpu, ctx=ctx, ttl=0)
                if loaded:
                    self._sessions[model_key] = ModelSession(
                        model_key=model_key,
                        gpu_fraction=gpu,
                        context_length=ctx,
                        ttl_seconds=0,
                    )
                else:
                    logger.warning("JIT load of %r failed; will try anyway", model_key)
                    self._sessions[model_key] = ModelSession(model_key=model_key)
            self._sessions[model_key].touch()

        return model_key

    def _ensure_jit_ttl(self, model_key: str, *, gpu: float, ctx: int, ttl: int) -> str:
        """JIT_TTL: load on first use, keep warm, expire on idle timeout."""
        with self._lock:
            if model_key in self._sessions:
                self._sessions[model_key].touch()
                return model_key

        # Model not in session — check if it's actually loaded via CLI
        loaded_models = self._cli.list_loaded_models()
        already_loaded = any(
            m.get("model_key", m.get("id", "")) == model_key
            for m in loaded_models
        )
        if not already_loaded:
            logger.info("JIT_TTL: loading %r (ttl=%ds)", model_key, ttl)
            self._cli_load(model_key, gpu=gpu, ctx=ctx, ttl=ttl)

        with self._lock:
            session = ModelSession(
                model_key=model_key,
                gpu_fraction=gpu,
                context_length=ctx,
                ttl_seconds=ttl,
            )
            session.touch()
            self._sessions[model_key] = session

        return model_key

    # ── CLI helpers ─────────────────────────────────────────────────────

    def _cli_load(self, model_key: str, *, gpu: float, ctx: int, ttl: int) -> bool:
        try:
            result = self._cli.load_model(
                model_key,
                gpu=gpu,
                context_length=ctx,
                ttl=ttl,
                force=True,  # skip VRAM guard — manager owns that decision
            )
            if result:
                # MCP: publish to ActivityBus
                try:
                    from engine.services.activity_bus import get_activity_bus
                    get_activity_bus().publish(
                        activity_type="model_loaded",
                        description=f"Model loaded: {model_key}",
                        agent_id="model_manager",
                        scene=None,
                        data={"model_key": model_key, "gpu": gpu, "ctx": ctx, "ttl": ttl},
                    )
                except Exception:
                    logger.debug("Suppressed exception", exc_info=True)
            return result
        except Exception as exc:
            logger.error("CLI load failed for %r: %s", model_key, exc)
            return False

    def _cli_unload(self, model_key: str) -> None:
        try:
            self._cli.unload_model(model_key)
            # MCP: publish to ActivityBus
            try:
                from engine.services.activity_bus import get_activity_bus
                get_activity_bus().publish(
                    activity_type="model_unloaded",
                    description=f"Model unloaded: {model_key}",
                    agent_id="model_manager",
                    scene=None,
                    data={"model_key": model_key},
                )
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)
        except Exception as exc:
            logger.warning("CLI unload failed for %r: %s", model_key, exc)

    # ── TTL reaper ──────────────────────────────────────────────────────

    def _start_reaper(self) -> None:
        self._stop_reaper.clear()
        if self._reaper_thread and self._reaper_thread.is_alive():
            return
        self._reaper_thread = threading.Thread(
            target=self._reap_loop, daemon=True, name="ModelReaper"
        )
        self._reaper_thread.start()
        logger.debug("ModelReaper started (interval=%.0fs)", self._REAPER_INTERVAL)

    def _reap_loop(self) -> None:
        while not self._stop_reaper.wait(timeout=self._REAPER_INTERVAL):
            self._reap_expired()

    def _reap_expired(self) -> None:
        with self._lock:
            expired = [
                key for key, sess in self._sessions.items()
                if sess.is_expired
            ]
        for key in expired:
            logger.info(
                "JIT_TTL: unloading %r — idle for %.0fs (ttl=%ds)",
                key,
                self._sessions.get(key, ModelSession(key)).idle_seconds,
                self._default_ttl,
            )
            with self._lock:
                self._sessions.pop(key, None)
            self._cli_unload(key)

    def shutdown(self) -> None:
        """Stop the reaper and release all JIT-managed sessions."""
        self._stop_reaper.set()
        if self._mode != LoadMode.CONCURRENT:
            for key in list(self._sessions.keys()):
                self._cli_unload(key)
        with self._lock:
            self._sessions.clear()
        logger.info("ModelManager shut down")

    # ── Agent sizing ────────────────────────────────────────────────────

    def ensure_for_agent(self, agent_role: str = "big", **kwargs) -> str:
        """
        Ensure the correct model is loaded for an agent role.

        Uses MCPFramework agent profiles to determine model, context_length,
        and other parameters.  Falls back to the default loaded model.

        Returns the model_key to use for LLM calls.
        """
        try:
            from engine.mcp.framework import get_framework
            profile = get_framework().get_agent_profile(agent_role)
            model = profile.model or self._concurrent_model or ""
            if not model:
                # Auto-detect from loaded models
                loaded = self._cli.list_loaded_models()
                if loaded:
                    model = loaded[0].get("model_key", loaded[0].get("id", ""))
            if model:
                return self.ensure_loaded(
                    model,
                    context_length=kwargs.get("context_length", profile.context_length),
                    gpu=kwargs.get("gpu", self._default_gpu),
                    ttl_seconds=kwargs.get("ttl_seconds"),
                )
        except Exception as exc:
            logger.debug("ensure_for_agent(%s) fallback: %s", agent_role, exc)
        return self._concurrent_model or ""

    def get_agent_config(self, agent_role: str = "big") -> Dict:
        """
        Return the full LLM config for an agent role.

        Combines AgentProfile settings with ModelManager state.
        """
        try:
            from engine.mcp.framework import get_framework
            profile = get_framework().get_agent_profile(agent_role)
        except Exception:
            profile = None

        return {
            "role": agent_role,
            "model": (profile.model if profile else "") or self._concurrent_model,
            "context_length": profile.context_length if profile else self._default_ctx,
            "max_tokens": profile.max_tokens if profile else 2000,
            "temperature": profile.temperature if profile else 0.7,
            "top_p": profile.top_p if profile else 0.9,
            "load_mode": self._mode.value,
            "gpu_fraction": self._default_gpu,
            "vram_cap_mb": self.config.get("lmstudio.vram_cap_mb", 11500),
        }

    def get_full_config(self) -> Dict:
        """Return the complete ModelManager configuration for admin panels."""
        return {
            "mode": self._mode.value,
            "default_ttl": self._default_ttl,
            "default_gpu": self._default_gpu,
            "default_context_length": self._default_ctx,
            "concurrent_model": self._concurrent_model,
            "concurrent_slots": int(self.config.get("lmstudio.concurrent_slots", 4)),
            "vram_cap_mb": int(self.config.get("lmstudio.vram_cap_mb", 11500)),
            "hardware": {
                "gpu_name": self.config.get("hardware.gpu_name", "Unknown"),
                "gpu_vram_mb": int(self.config.get("hardware.gpu_vram_mb", 0)),
                "ram_gb": int(self.config.get("hardware.ram_gb", 0)),
            },
            "mcp_enabled": bool(self.config.get("lmstudio.mcp_enabled", True)),
            "api_version": self.config.get("lmstudio.api_version", "v1"),
            "sessions": self.status(),
        }

    def update_config(self, **kwargs) -> Dict:
        """
        Update ModelManager config at runtime.

        Supported keys: mode, ttl_seconds, concurrent_model, gpu, context_length.
        Returns the updated config dict.
        """
        if "mode" in kwargs:
            new_mode = LoadMode(kwargs["mode"])
            self.set_mode(new_mode, ttl_seconds=kwargs.get("ttl_seconds"))
        if "concurrent_model" in kwargs:
            with self._lock:
                self._concurrent_model = kwargs["concurrent_model"]
        if "gpu" in kwargs:
            with self._lock:
                self._default_gpu = float(kwargs["gpu"])
        if "context_length" in kwargs:
            with self._lock:
                self._default_ctx = int(kwargs["context_length"])
        if "ttl_seconds" in kwargs and "mode" not in kwargs:
            with self._lock:
                self._default_ttl = int(kwargs["ttl_seconds"])

        logger.info("ModelManager config updated: %s", kwargs)
        return self.get_full_config()


# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional[ModelManager] = None
_instance_lock = threading.Lock()


def get_model_manager() -> ModelManager:
    """Return the global ModelManager singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ModelManager()
    return _instance
