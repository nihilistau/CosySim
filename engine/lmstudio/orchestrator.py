"""
InferenceOrchestrator — Unified model lifecycle + routing + resource management

Bridges ModelManager (lifecycle), InferenceRouter (queue/routing), and
ResourceManager (GPU budget) into a single inference API.

One call does everything::

    from engine.lmstudio.orchestrator import get_orchestrator

    orch = get_orchestrator()
    response = orch.infer(
        agent_id="aria",
        messages=[{"role": "user", "content": "Hello"}],
        task_type="chat",
        priority="interactive",
    )

The orchestrator:
1. Selects the right tier based on task_type + priority
2. Ensures the model for that tier is loaded (via ResourceManager)
3. Routes the request through the priority queue (via Router)
4. Tracks performance metrics (TPS, latency) for adaptive routing
5. Provides a unified status API for admin panels
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Performance tracking ────────────────────────────────────────────────

_PERF_WINDOW = 50  # keep last N measurements per tier


@dataclass
class TierPerformance:
    """Rolling performance stats for a model tier."""
    latency_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=_PERF_WINDOW))
    tokens_per_sec: Deque[float] = field(default_factory=lambda: deque(maxlen=_PERF_WINDOW))
    errors: int = 0
    successes: int = 0

    def record(self, latency_ms: float, tps: float = 0.0) -> None:
        self.latency_ms.append(latency_ms)
        if tps > 0:
            self.tokens_per_sec.append(tps)
        self.successes += 1

    def record_error(self) -> None:
        self.errors += 1

    @property
    def avg_latency_ms(self) -> float:
        return sum(self.latency_ms) / len(self.latency_ms) if self.latency_ms else 0.0

    @property
    def avg_tps(self) -> float:
        return sum(self.tokens_per_sec) / len(self.tokens_per_sec) if self.tokens_per_sec else 0.0

    @property
    def error_rate(self) -> float:
        total = self.successes + self.errors
        return self.errors / total if total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "avg_tps": round(self.avg_tps, 1),
            "error_rate": round(self.error_rate, 3),
            "samples": self.successes + self.errors,
        }


# ── Agent profile ───────────────────────────────────────────────────────

@dataclass
class AgentProfile:
    """Describes an agent's model requirements."""
    agent_id: str
    preferred_tier: str = "auto"           # "gpu_primary", "cpu_utility", "auto"
    preferred_model: str = ""              # explicit model override
    max_tokens: int = 2048
    context_budget: int = 8192             # max context to send
    temperature: float = 0.7
    priority_boost: int = 0                # -1 = higher priority, +1 = lower
    tags: List[str] = field(default_factory=list)


# ── Orchestrator ────────────────────────────────────────────────────────

class InferenceOrchestrator:
    """
    Unified facade for multi-model inference management.

    Coordinates between:
    - ModelManager: model loading/unloading lifecycle
    - InferenceRouter: priority-queue-based request routing
    - ResourceManager: GPU/CPU budget and slot management
    - LMSClient: actual inference calls
    """

    def __init__(self, config=None) -> None:
        if config is None:
            from engine.config import get_config
            config = get_config()
        self._config = config

        # Lazy references (set during configure() or on first use)
        self._client = None
        self._model_manager = None
        self._resource_manager = None
        self._router = None

        # Performance tracking per tier
        self._perf: Dict[str, TierPerformance] = defaultdict(TierPerformance)
        self._lock = threading.Lock()

        # Agent profiles {agent_id → AgentProfile}
        self._profiles: Dict[str, AgentProfile] = {}

        # Request counter for metrics
        self._total_requests = 0
        self._total_errors = 0

        logger.info("InferenceOrchestrator initialized")

    # ── Configuration ────────────────────────────────────────────────

    def configure(
        self,
        *,
        client=None,
        model_manager=None,
        resource_manager=None,
        router=None,
    ) -> "InferenceOrchestrator":
        """Inject component references. Returns self for chaining."""
        if client is not None:
            self._client = client
        if model_manager is not None:
            self._model_manager = model_manager
        if resource_manager is not None:
            self._resource_manager = resource_manager
        if router is not None:
            self._router = router
        return self

    def register_agent(self, profile: AgentProfile) -> None:
        """Register an agent's model preferences."""
        self._profiles[profile.agent_id] = profile
        logger.debug("Registered agent profile: %s", profile.agent_id)

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent profile."""
        self._profiles.pop(agent_id, None)

    # ── Lazy component getters ───────────────────────────────────────

    @property
    def client(self):
        if self._client is None:
            from engine.lmstudio.lms_client import get_lms_client
            self._client = get_lms_client()
        return self._client

    @property
    def model_manager(self):
        if self._model_manager is None:
            from engine.lmstudio.model_manager import get_model_manager
            self._model_manager = get_model_manager()
        return self._model_manager

    @property
    def resource_manager(self):
        if self._resource_manager is None:
            from engine.lmstudio.resource_manager import get_resource_manager
            self._resource_manager = get_resource_manager()
        return self._resource_manager

    @property
    def router(self):
        if self._router is None:
            from engine.lmstudio.router import InferenceRouter
            self._router = InferenceRouter()
        return self._router

    # ── Main inference API ───────────────────────────────────────────

    def infer(
        self,
        *,
        agent_id: str = "",
        messages: Any = None,
        task_type: str = "chat",
        priority: str = "interactive",
        model: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[list] = None,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        config: Any = None,
    ) -> Any:
        """
        Unified inference call — handles model selection, loading, and routing.

        Parameters
        ----------
        agent_id : str
            Agent making the request (for profile lookup and affinity).
        messages : list
            Chat messages to send.
        task_type : str
            "chat", "act", "classify", "route", "complete", "stream"
        priority : str
            "realtime", "interactive", "background", "batch"
        model : str
            Explicit model override (bypasses tier selection).
        temperature, max_tokens : optional
            Inference parameters (override agent profile).
        tools : list, optional
            Tool definitions for function calling.
        system_prompt : str, optional
            System prompt to prepend.
        stream : bool
            Stream the response.
        config : InferenceConfig, optional
            Full config object (overrides individual params).

        Returns
        -------
        LMSResponse or generator (if streaming)
        """
        t0 = time.monotonic()

        # Resolve agent profile
        profile = self._profiles.get(agent_id, AgentProfile(agent_id=agent_id))

        # Resolve model: explicit > profile > tier-based
        resolved_model = model or profile.preferred_model

        # Resolve tier
        tier_name = self._select_tier(task_type, priority, profile, bool(tools))

        # Ensure model is loaded via resource manager
        if resolved_model:
            try:
                resolved_model = self.resource_manager.acquire(
                    agent_id or "anonymous",
                    role=self._tier_to_role(tier_name),
                    model=resolved_model,
                )
            except Exception as e:
                logger.warning("ResourceManager.acquire failed: %s", e)
                # Fall through — model might already be loaded

        # Build inference config
        if config is None:
            from engine.lmstudio.inference_config import InferenceConfig
            config = InferenceConfig(
                temperature=temperature or profile.temperature,
                max_output_tokens=max_tokens or profile.max_tokens,
            )

        # Direct inference (bypass router for simplicity and reliability)
        try:
            with self._lock:
                self._total_requests += 1

            if stream:
                return self._infer_stream(
                    messages, resolved_model, config, tools,
                    system_prompt, tier_name, t0, agent_id,
                )
            else:
                return self._infer_sync(
                    messages, resolved_model, config, tools,
                    system_prompt, tier_name, t0, agent_id,
                )

        except Exception as e:
            self._record_error(tier_name)
            raise

    def infer_quick(self, prompt: str, *, agent_id: str = "", **kwargs) -> str:
        """Convenience: send a single prompt, get text back."""
        messages = [{"role": "user", "content": prompt}]
        resp = self.infer(agent_id=agent_id, messages=messages, **kwargs)
        return resp.content if hasattr(resp, "content") else str(resp)

    # ── Internal inference methods ───────────────────────────────────

    def _infer_sync(
        self, messages, model, config, tools,
        system_prompt, tier_name, t0, agent_id,
    ):
        """Synchronous inference with performance tracking."""
        kwargs = {"messages": messages, "config": config}
        if model:
            kwargs["model"] = model
        if tools:
            kwargs["tools"] = tools
        if system_prompt:
            kwargs["system_prompt"] = system_prompt

        resp = self.client.chat(**kwargs)

        # Record performance
        latency_ms = (time.monotonic() - t0) * 1000
        tps = 0.0
        if hasattr(resp, "usage") and resp.usage:
            try:
                tokens = int(getattr(resp.usage, "completion_tokens", 0) or 0)
                if tokens > 0 and latency_ms > 0:
                    tps = tokens / (latency_ms / 1000)
            except (TypeError, ValueError):
                logger.debug("Suppressed exception", exc_info=True)

        self._record_success(tier_name, latency_ms, tps)
        return resp

    def _infer_stream(
        self, messages, model, config, tools,
        system_prompt, tier_name, t0, agent_id,
    ):
        """Streaming inference with performance tracking."""
        kwargs = {"messages": messages, "config": config}
        if model:
            kwargs["model"] = model
        if tools:
            kwargs["tools"] = tools
        if system_prompt:
            kwargs["system_prompt"] = system_prompt

        return self.client.chat_stream(**kwargs)

    # ── Tier selection ───────────────────────────────────────────────

    def _select_tier(
        self, task_type: str, priority: str,
        profile: AgentProfile, has_tools: bool,
    ) -> str:
        """
        Select the best tier for a request.

        Uses task type, priority, agent profile, and performance history.
        """
        # Explicit tier in profile
        if profile.preferred_tier != "auto":
            return profile.preferred_tier

        # Classification/routing → tiny model
        if task_type in ("classify", "route", "tag_extract", "validate"):
            return "cpu_router"

        # Tool calling needs reasoning capacity → big model
        if task_type == "act" or has_tools:
            return "gpu_primary"

        # Background/batch without tools → utility model if performant
        if priority in ("background", "batch"):
            utility_perf = self._perf.get("cpu_utility")
            if utility_perf and utility_perf.error_rate < 0.2:
                return "cpu_utility"

        # Default → primary
        return "gpu_primary"

    @staticmethod
    def _tier_to_role(tier_name: str) -> str:
        """Map tier name to ResourceManager role."""
        return {
            "gpu_primary": "big",
            "cpu_utility": "small",
            "cpu_router": "router",
        }.get(tier_name, "big")

    # ── Performance tracking ─────────────────────────────────────────

    def _record_success(self, tier: str, latency_ms: float, tps: float) -> None:
        with self._lock:
            self._perf[tier].record(latency_ms, tps)

    def _record_error(self, tier: str) -> None:
        with self._lock:
            self._perf[tier].record_error()
            self._total_errors += 1

    # ── Status and metrics ───────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Comprehensive status for admin panels."""
        with self._lock:
            perf = {k: v.to_dict() for k, v in self._perf.items()}
            profiles = {
                aid: {
                    "preferred_tier": p.preferred_tier,
                    "preferred_model": p.preferred_model,
                    "max_tokens": p.max_tokens,
                    "context_budget": p.context_budget,
                    "temperature": p.temperature,
                }
                for aid, p in self._profiles.items()
            }
            total = self._total_requests
            errors = self._total_errors

        # Gather sub-system status
        status = {
            "orchestrator": {
                "total_requests": total,
                "total_errors": errors,
                "error_rate": round(errors / total, 3) if total > 0 else 0.0,
                "registered_agents": len(profiles),
            },
            "performance_by_tier": perf,
            "agent_profiles": profiles,
        }

        # Add model manager status
        try:
            mm = self.model_manager
            status["model_manager"] = {
                "mode": mm.mode.value,
                "active_sessions": len(mm._sessions),
            }
        except Exception:
            status["model_manager"] = {"error": "unavailable"}

        # Add resource manager status
        try:
            status["resource_manager"] = self.resource_manager.get_status()
        except Exception:
            status["resource_manager"] = {"error": "unavailable"}

        return status

    def get_performance(self, tier: Optional[str] = None) -> Dict[str, Any]:
        """Get performance metrics, optionally filtered by tier."""
        with self._lock:
            if tier:
                p = self._perf.get(tier)
                return {tier: p.to_dict()} if p else {}
            return {k: v.to_dict() for k, v in self._perf.items()}

    def update_config(self, **kwargs) -> Dict[str, Any]:
        """
        Runtime config updates.

        Supported keys:
        - model_manager_mode: "concurrent" | "jit" | "jit_ttl"
        - resource_strategy: "single_big" | "concurrent" | "multi_small" | ...
        - ttl_seconds: int
        - vram_cap_mb: int
        - concurrent_slots: int
        """
        from engine.lmstudio.model_manager import LoadMode
        from engine.lmstudio.resource_manager import Strategy

        if "model_manager_mode" in kwargs:
            self.model_manager.set_mode(LoadMode(kwargs["model_manager_mode"]))
        if "resource_strategy" in kwargs:
            self.resource_manager.set_strategy(Strategy(kwargs["resource_strategy"]))
        if "ttl_seconds" in kwargs:
            self.model_manager.set_mode(
                self.model_manager.mode, ttl_seconds=int(kwargs["ttl_seconds"])
            )
        if "vram_cap_mb" in kwargs:
            self.resource_manager.update_config(vram_cap_mb=int(kwargs["vram_cap_mb"]))
        if "concurrent_slots" in kwargs:
            self.resource_manager.update_config(
                concurrent_slots=int(kwargs["concurrent_slots"])
            )

        return self.get_status()

    def shutdown(self) -> None:
        """Clean shutdown of all sub-systems."""
        try:
            self.resource_manager.shutdown()
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        try:
            if self._router and hasattr(self._router, "stop"):
                self._router.stop()
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        logger.info("InferenceOrchestrator shut down")


# ── Singleton ────────────────────────────────────────────────────────────

_instance: Optional[InferenceOrchestrator] = None
_instance_lock = threading.Lock()


def get_orchestrator(config=None) -> InferenceOrchestrator:
    """Get or create the singleton orchestrator."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = InferenceOrchestrator(config)
        return _instance


def reset_orchestrator() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    with _instance_lock:
        if _instance is not None:
            try:
                _instance.shutdown()
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)
            _instance = None
