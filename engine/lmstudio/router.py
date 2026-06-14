"""
InferenceRouter — Three-tier priority queue with slot-aware scheduling

Routes LLM requests to the optimal model tier and communication channel
based on priority, task type, and slot availability.

Architecture::

    submit(request) ──► Priority Queue ──► Tier Selection ──► Channel
                         (heapq)           T1/T2/T3           SDK / REST

Tiers:
    T1 (GPU Primary)   — Character dialogue, .act() tool calling, narration
    T2 (CPU Utility)   — Auto-texts, decisions, JSON-only outputs
    T3 (CPU Router)    — Tag extraction, routing, classification, spec decode draft

Priority levels:
    REALTIME(0)    — Scene agent responding to player (immediate)
    INTERACTIVE(1) — Phone chat, game UI responses
    BACKGROUND(2)  — Autonomous text generation, periodic checks
    BATCH(3)       — Image prompts, analytics, non-urgent

Thread-safe.  All public methods are safe to call from multiple threads.

Version: v1.57.0 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.57.0 [2026-03-26] — Enhanced Nexus-aware routing: agent hit-rate analysis
                             from QueryRouter stats for smarter model selection
    v1.56.0 [2026-03-26] — Nexus-aware routing hint for small model selection
    v1.49.0 [2026-03-22] — Initial three-tier priority queue router
"""
from __future__ import annotations

import enum
import heapq
import logging
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Enums ────────────────────────────────────────────────────────────

class Priority(enum.IntEnum):
    """Request priority levels (lower = higher priority)."""
    REALTIME    = 0
    INTERACTIVE = 1
    BACKGROUND  = 2
    BATCH       = 3


class Tier(enum.Enum):
    """Model tiers for routing."""
    GPU_PRIMARY  = "gpu_primary"   # T1: big model on GPU
    CPU_UTILITY  = "cpu_utility"   # T2: small model on CPU
    CPU_ROUTER   = "cpu_router"    # T3: tiny router model (Gemma 270M)


class Channel(enum.Enum):
    """Communication channel to LMStudio."""
    SDK  = "sdk"    # WebSocket via lmstudio SDK
    REST = "rest"   # HTTP via LMSClient


# ── Request / Result containers ──────────────────────────────────────

@dataclass
class InferenceRequest:
    """A queued inference request."""
    # Routing metadata
    priority: Priority = Priority.INTERACTIVE
    tier: Optional[Tier] = None          # None = auto-select
    channel: Optional[Channel] = None    # None = auto-select
    agent_id: str = ""                   # for slot affinity tracking
    scene: str = ""                      # for priority inference
    task_type: str = "chat"              # "chat", "act", "complete", "classify", "stream"

    # Payload
    messages: Any = None                 # List[Dict] or str
    tools: Optional[list] = None         # for .act() calls
    model_key: Optional[str] = None      # explicit model override
    config: Any = None                   # InferenceConfig
    system_prompt: Optional[str] = None
    stream: bool = False

    # Callbacks
    on_fragment: Optional[Callable] = None
    on_first_token: Optional[Callable] = None

    # Internal
    _created_at: float = field(default_factory=time.time)
    _sequence: int = 0  # tie-breaker for same-priority items


@dataclass
class RouterMetrics:
    """Live metrics for the router."""
    total_submitted: int = 0
    total_completed: int = 0
    total_errors: int = 0
    total_cancelled: int = 0
    # Per-tier counts
    tier_counts: Dict[str, int] = field(default_factory=dict)
    # Per-priority counts
    priority_counts: Dict[str, int] = field(default_factory=dict)
    # Queue depths
    queue_depth: int = 0
    # Timing
    avg_wait_ms: float = 0.0
    avg_latency_ms: float = 0.0
    # Slot utilization
    slots_busy: Dict[str, int] = field(default_factory=dict)
    slots_total: Dict[str, int] = field(default_factory=dict)


# ── Tier configuration ───────────────────────────────────────────────

@dataclass
class TierConfig:
    """Configuration for a model tier."""
    tier: Tier
    model_key: str = ""
    max_slots: int = 1
    device: str = "gpu"               # "gpu" or "cpu"
    channel: Channel = Channel.SDK    # preferred channel
    enabled: bool = True
    # Slot tracking
    _busy_slots: int = 0


# ── The Router ───────────────────────────────────────────────────────

class InferenceRouter:
    """
    Three-tier priority queue with intelligent routing.

    Parameters
    ----------
    tiers : dict[Tier, TierConfig], optional
        Custom tier configurations.  If None, uses defaults.
    max_queue_depth : int
        Maximum queued requests before rejecting.
    preempt_on_priority : bool
        If True, higher-priority requests can preempt lower ones.
    """

    def __init__(
        self,
        tiers: Optional[Dict[Tier, TierConfig]] = None,
        max_queue_depth: int = 50,
        preempt_on_priority: bool = False,
    ) -> None:
        # Tier configs
        self._tiers: Dict[Tier, TierConfig] = tiers or {
            Tier.GPU_PRIMARY: TierConfig(
                tier=Tier.GPU_PRIMARY,
                model_key="",
                max_slots=2,
                device="gpu",
                channel=Channel.SDK,
            ),
            Tier.CPU_UTILITY: TierConfig(
                tier=Tier.CPU_UTILITY,
                model_key="",
                max_slots=1,
                device="cpu",
                channel=Channel.SDK,
            ),
            Tier.CPU_ROUTER: TierConfig(
                tier=Tier.CPU_ROUTER,
                model_key="",
                max_slots=1,
                device="cpu",
                channel=Channel.SDK,
            ),
        }

        self._max_queue_depth = max_queue_depth
        self._preempt = preempt_on_priority

        # Priority queue: (priority, sequence, request, future)
        self._queue: List[Tuple[int, int, InferenceRequest, Future]] = []
        self._lock = threading.Lock()
        self._sequence = 0

        # Metrics
        self._metrics = RouterMetrics()
        self._wait_times: List[float] = []
        self._latency_times: List[float] = []

        # Slot tracking: agent_id → tier (for affinity), bounded LRU
        self._agent_affinity: Dict[str, Tier] = {}
        _MAX_AFFINITY = 256  # evict oldest when exceeded

        # Worker thread
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._work_available = threading.Event()

        # SDK and REST client references (set via configure())
        self._sdk_client = None
        self._rest_client = None

    # ─────────────────────────────── configuration ──

    def configure(
        self,
        *,
        sdk_client=None,
        rest_client=None,
        tier_configs: Optional[Dict[str, Dict]] = None,
    ) -> None:
        """
        Set up client references and optionally update tier configs.

        Called during application startup after clients are initialized.
        """
        if sdk_client is not None:
            self._sdk_client = sdk_client
        if rest_client is not None:
            self._rest_client = rest_client

        if tier_configs:
            for tier_name, cfg in tier_configs.items():
                tier = Tier(tier_name)
                if tier in self._tiers:
                    tc = self._tiers[tier]
                    tc.model_key = cfg.get("model_key", tc.model_key)
                    tc.max_slots = cfg.get("max_slots", tc.max_slots)
                    tc.device = cfg.get("device", tc.device)
                    tc.enabled = cfg.get("enabled", tc.enabled)

    # ─────────────────────────────── agent slot binding ──

    def bind_agent(self, agent_id: str, tier: Tier) -> None:
        """Pin an agent to a specific tier (e.g. for KV cache warmth)."""
        self._agent_affinity[agent_id] = tier

    def unbind_agent(self, agent_id: str) -> None:
        """Remove agent affinity — let the router decide freely."""
        self._agent_affinity.pop(agent_id, None)

    def get_agent_bindings(self) -> Dict[str, str]:
        """Return current agent → tier bindings."""
        return {aid: t.value for aid, t in self._agent_affinity.items()}

    # ─────────────────────────────── lifecycle ──

    def start(self) -> None:
        """Start the router worker thread."""
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="InferenceRouter-Worker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("InferenceRouter started")

    def stop(self) -> None:
        """Stop the router and cancel pending requests."""
        self._running = False
        self._work_available.set()  # wake up worker
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        # Cancel all pending
        with self._lock:
            for _, _, req, future in self._queue:
                if not future.done():
                    future.cancel()
                    self._metrics.total_cancelled += 1
            self._queue.clear()
        logger.info("InferenceRouter stopped")

    # ─────────────────────────────── submit ──

    def submit(self, request: InferenceRequest) -> Future:
        """
        Submit an inference request to the router.

        Returns a Future that will contain the LMSResponse when complete.
        Raises RuntimeError if the queue is full.
        """
        with self._lock:
            if len(self._queue) >= self._max_queue_depth:
                future = Future()
                future.set_exception(RuntimeError(
                    f"Router queue full ({self._max_queue_depth} pending)"
                ))
                return future

            self._sequence += 1
            request._sequence = self._sequence

            future: Future = Future()
            heapq.heappush(
                self._queue,
                (request.priority.value, self._sequence, request, future),
            )

            self._metrics.total_submitted += 1
            self._metrics.queue_depth = len(self._queue)
            p_name = request.priority.name
            self._metrics.priority_counts[p_name] = \
                self._metrics.priority_counts.get(p_name, 0) + 1

        self._work_available.set()
        return future

    def submit_sync(self, request: InferenceRequest, timeout: float = 60.0) -> Any:
        """Submit and block until result is available."""
        future = self.submit(request)
        return future.result(timeout=timeout)

    # ─────────────────────────────── Nexus-aware routing ──

    # v1.57.0 [2026-03-26] — Enhanced Nexus-aware routing with agent hit-rate analysis
    # CONNECTS: select_tier(), Nexus QueryRouter stats, knowledge confidence
    # CALLED BY: select_tier() as a pre-check before ML/rule routing
    def _nexus_routing_hint(self, request: InferenceRequest) -> Optional[str]:
        """Use Nexus query patterns to optimize model selection.

        Checks two signals:
        1. Short factual questions (< 50 chars with '?') → small model
        2. Agent-level Nexus hit rate — if an agent gets 70%+ cache hits
           from Nexus (after 10+ queries), it asks simple questions that
           a smaller CPU model can handle.

        Args:
            request: The inference request to evaluate.

        Returns:
            ``"small"`` if a lightweight model would suffice, else ``None``.
        """
        messages = getattr(request, "messages", None) or []
        if not isinstance(messages, list):
            return None
        # Find the last user message
        user_msg = ""
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                user_msg = m.get("content", "")
                break
        if not user_msg:
            return None

        # Short factual questions → small model
        if len(user_msg) < 50 and "?" in user_msg:
            return "small"

        # v1.57.0 [2026-03-26] — Check if Nexus-first inference is catching
        # most queries for this agent.  High hit rate means simple questions
        # that a smaller model can handle just as well.
        agent_id = request.agent_id
        if agent_id:
            try:
                from engine.nexus.query_router import get_query_router
                stats = get_query_router().stats
                agent_hits = stats.agent_hits.get(agent_id, 0)
                agent_queries = stats.agent_queries.get(agent_id, 0)
                if agent_queries > 10 and agent_hits / max(1, agent_queries) > 0.7:
                    # This agent gets 70%+ cache hits — simple questions, use small model
                    return "small"
            except Exception:
                pass

        return None

    # ─────────────────────────────── routing logic ──

    def select_tier(self, request: InferenceRequest) -> Tier:
        """
        Select the best tier for a request.

        Rules:
        1. Explicit tier in request → use it
        2. Agent affinity (warm KV cache) → prefer same tier
        3. RouterV3 ML prediction → use if available (with rule fallback)
        4. Rule-based fallback: task_type classify/route → T3, act/tools → T1,
           BACKGROUND without tools → T2, else T1
        """
        if request.tier is not None:
            return request.tier

        # Agent affinity: prefer the tier where this agent already has a warm cache
        if request.agent_id and request.agent_id in self._agent_affinity:
            affinity_tier = self._agent_affinity[request.agent_id]
            if self.has_available_slot(affinity_tier):
                return affinity_tier

        # v1.56.0 — Nexus-aware routing hint: short factual queries → small model
        hint = self._nexus_routing_hint(request)
        if hint == "small" and not request.tools:
            # Prefer CPU utility for simple questions (saves GPU for dialogue)
            if self._tiers.get(Tier.CPU_UTILITY, TierConfig(Tier.CPU_UTILITY)).enabled:
                if self.has_available_slot(Tier.CPU_UTILITY):
                    return Tier.CPU_UTILITY

        # RouterV3 ML-based prediction
        try:
            from engine.lmstudio.router_v3_client import get_router_v3_client
            v3 = get_router_v3_client()
            has_tools = bool(request.tools)
            has_sys = bool(request.system_prompt)
            tier_name = v3.predict_tier(
                request.task_type,
                request.priority.name.lower(),
                has_tools=has_tools,
                has_system_prompt=has_sys,
            )
            tier = Tier(tier_name)
            # Validate selected tier is enabled and has slots
            if self._tiers.get(tier, TierConfig(tier)).enabled:
                return tier
        except Exception:
            logger.debug("Tier selection lookup failed, falling through to rules", exc_info=True)

        task = request.task_type

        # Router tasks → T3
        if task in ("classify", "route", "validate", "tag_extract"):
            if self._tiers.get(Tier.CPU_ROUTER, TierConfig(Tier.CPU_ROUTER)).enabled:
                return Tier.CPU_ROUTER

        # Tool calling → T1 (needs reasoning capacity)
        if task == "act" or request.tools:
            return Tier.GPU_PRIMARY

        # Background work without tools → T2 if available
        if request.priority >= Priority.BACKGROUND:
            if self._tiers.get(Tier.CPU_UTILITY, TierConfig(Tier.CPU_UTILITY)).enabled:
                return Tier.CPU_UTILITY

        return Tier.GPU_PRIMARY

    def select_channel(self, request: InferenceRequest, tier: Tier) -> Channel:
        """
        Select SDK or REST channel.

        Rules:
        1. Explicit channel in request → use it
        2. .act() calls → SDK only (REST doesn't support .act())
        3. Stateful chat (has previous_response_id) → REST only
        4. Otherwise → tier's preferred channel
        """
        if request.channel is not None:
            return request.channel

        # .act() is SDK-only
        if request.task_type == "act" or request.tools:
            return Channel.SDK

        # Stateful chats need REST (previous_response_id)
        if request.config and hasattr(request.config, "previous_response_id"):
            if request.config.previous_response_id:
                return Channel.REST

        # Use tier's preferred channel
        tier_config = self._tiers.get(tier)
        if tier_config:
            return tier_config.channel

        return Channel.SDK if self._sdk_client else Channel.REST

    def has_available_slot(self, tier: Tier) -> bool:
        """Check if the tier has a free slot."""
        tc = self._tiers.get(tier)
        if not tc or not tc.enabled:
            return False
        return tc._busy_slots < tc.max_slots

    # ─────────────────────────────── execution ──

    def _execute_request(
        self,
        request: InferenceRequest,
        tier: Tier,
        channel: Channel,
    ) -> Any:
        """Execute a single request on the selected tier and channel."""
        tier_config = self._tiers.get(tier)
        model_key = request.model_key or (tier_config.model_key if tier_config else None)

        t0 = time.time()

        try:
            if channel == Channel.SDK:
                return self._execute_via_sdk(request, model_key)
            else:
                return self._execute_via_rest(request, model_key)
        finally:
            latency = (time.time() - t0) * 1000
            self._latency_times.append(latency)
            if len(self._latency_times) > 100:
                self._latency_times = self._latency_times[-100:]
            self._metrics.avg_latency_ms = (
                sum(self._latency_times) / len(self._latency_times)
                if self._latency_times else 0.0
            )
            # Record agent affinity for KV cache warmth (bounded)
            if request.agent_id:
                self._agent_affinity[request.agent_id] = tier
                if len(self._agent_affinity) > self._MAX_AFFINITY:
                    # Evict oldest entry (first key in insertion-order dict)
                    oldest = next(iter(self._agent_affinity))
                    del self._agent_affinity[oldest]

    def _execute_via_sdk(self, request: InferenceRequest, model_key: Optional[str]) -> Any:
        """Execute via the SDK client."""
        if not self._sdk_client:
            raise RuntimeError("SDK client not configured")

        if request.task_type == "act" and request.tools:
            return self._sdk_client.act(
                request.messages,
                request.tools,
                model_key=model_key,
                config=request.config,
                on_fragment=request.on_fragment,
            )
        elif request.stream:
            # For streaming, collect all events and return final response
            events = list(self._sdk_client.respond_stream(
                request.messages,
                model_key=model_key,
                config=request.config,
            ))
            # Find the content from delta events
            content = "".join(
                e.content for e in events
                if hasattr(e, "event_type") and e.event_type == "message.delta" and e.content
            )
            from .lms_client import LMSResponse
            return LMSResponse(content=content, model=model_key or "")
        elif request.task_type == "complete":
            return self._sdk_client.complete(
                request.messages if isinstance(request.messages, str) else "",
                model_key=model_key,
                config=request.config,
            )
        else:
            return self._sdk_client.respond(
                request.messages,
                model_key=model_key,
                config=request.config,
                on_first_token=request.on_first_token,
                on_fragment=request.on_fragment,
            )

    def _execute_via_rest(self, request: InferenceRequest, model_key: Optional[str]) -> Any:
        """Execute via the REST client."""
        if not self._rest_client:
            raise RuntimeError("REST client not configured")

        # Build messages list
        messages = request.messages
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        if request.stream:
            return self._rest_client.chat_stream(
                messages=messages,
                model=model_key,
                config=request.config,
            )
        else:
            return self._rest_client.chat(
                messages=messages,
                model=model_key,
                config=request.config,
            )

    # ─────────────────────────────── worker loop ──

    def _worker_loop(self) -> None:
        """Background thread that processes the priority queue."""
        while self._running:
            self._work_available.wait(timeout=1.0)
            self._work_available.clear()

            while self._running:
                # Peek at the highest-priority request
                with self._lock:
                    if not self._queue:
                        break

                    _, _, request, future = self._queue[0]

                    if future.cancelled():
                        heapq.heappop(self._queue)
                        self._metrics.total_cancelled += 1
                        continue

                    # Select tier and check slot
                    tier = self.select_tier(request)
                    if not self.has_available_slot(tier):
                        # No slot — can we use a fallback tier?
                        fallback = self._find_fallback_tier(tier, request)
                        if fallback and self.has_available_slot(fallback):
                            tier = fallback
                        else:
                            break  # Wait for a slot to free up

                    # Pop and execute
                    heapq.heappop(self._queue)
                    self._metrics.queue_depth = len(self._queue)

                    # Mark slot busy
                    tier_config = self._tiers.get(tier)
                    if tier_config:
                        tier_config._busy_slots += 1
                        tier_name = tier.value
                        self._metrics.slots_busy[tier_name] = tier_config._busy_slots
                        self._metrics.slots_total[tier_name] = tier_config.max_slots

                # Execute outside the lock
                wait_ms = (time.time() - request._created_at) * 1000
                self._wait_times.append(wait_ms)
                if len(self._wait_times) > 100:
                    self._wait_times = self._wait_times[-100:]
                self._metrics.avg_wait_ms = (
                    sum(self._wait_times) / len(self._wait_times)
                    if self._wait_times else 0.0
                )

                channel = self.select_channel(request, tier)
                tier_name = tier.value
                self._metrics.tier_counts[tier_name] = \
                    self._metrics.tier_counts.get(tier_name, 0) + 1

                try:
                    result = self._execute_request(request, tier, channel)
                    future.set_result(result)
                    self._metrics.total_completed += 1
                except Exception as exc:
                    logger.error("Router execution error: %s", exc)
                    future.set_exception(exc)
                    self._metrics.total_errors += 1
                finally:
                    # Free slot
                    if tier_config:
                        tier_config._busy_slots = max(0, tier_config._busy_slots - 1)
                        self._metrics.slots_busy[tier_name] = tier_config._busy_slots

    def _find_fallback_tier(self, primary: Tier, request: InferenceRequest) -> Optional[Tier]:
        """Find an alternative tier if the primary is full."""
        # T1 full → try T2 (if task doesn't need tools)
        if primary == Tier.GPU_PRIMARY and not request.tools:
            if self._tiers.get(Tier.CPU_UTILITY, TierConfig(Tier.CPU_UTILITY)).enabled:
                return Tier.CPU_UTILITY
        # T2 full → try T1
        if primary == Tier.CPU_UTILITY:
            return Tier.GPU_PRIMARY
        return None

    # ─────────────────────────────── metrics ──

    def get_metrics(self) -> Dict[str, Any]:
        """Return current router metrics as a dict."""
        m = self._metrics
        return {
            "total_submitted": m.total_submitted,
            "total_completed": m.total_completed,
            "total_errors": m.total_errors,
            "total_cancelled": m.total_cancelled,
            "queue_depth": m.queue_depth,
            "avg_wait_ms": round(m.avg_wait_ms, 1),
            "avg_latency_ms": round(m.avg_latency_ms, 1),
            "tier_counts": dict(m.tier_counts),
            "priority_counts": dict(m.priority_counts),
            "slots": {
                tier_name: {
                    "busy": m.slots_busy.get(tier_name, 0),
                    "total": m.slots_total.get(tier_name, 0),
                }
                for tier_name in [t.value for t in Tier]
            },
        }


# ── Convenience constructors ─────────────────────────────────────────

def create_router_from_config(config=None) -> InferenceRouter:
    """
    Create an InferenceRouter from CosySim config.

    Reads ``lmstudio.router.*`` and ``lmstudio.models.*`` from config.
    """
    if config is None:
        from engine.config import get_config
        config = get_config()

    max_queue = int(config.get("lmstudio.router.max_queue_depth", 50))
    preempt = bool(config.get("lmstudio.router.preempt_on_priority", False))

    # Build tier configs from lmstudio.models.*
    models_cfg = config.get("lmstudio.models") or {}
    tiers = {}

    primary_cfg = models_cfg.get("primary") or {}
    tiers[Tier.GPU_PRIMARY] = TierConfig(
        tier=Tier.GPU_PRIMARY,
        model_key=primary_cfg.get("key", ""),
        max_slots=int(primary_cfg.get("slots", 2)),
        device=primary_cfg.get("device", "gpu"),
        channel=Channel.SDK,
        enabled=True,
    )

    utility_cfg = models_cfg.get("utility") or {}
    tiers[Tier.CPU_UTILITY] = TierConfig(
        tier=Tier.CPU_UTILITY,
        model_key=utility_cfg.get("key", ""),
        max_slots=int(utility_cfg.get("slots", 1)),
        device=utility_cfg.get("device", "cpu"),
        channel=Channel.SDK,
        enabled=bool(utility_cfg.get("key", "")),
    )

    router_cfg = models_cfg.get("router") or {}
    tiers[Tier.CPU_ROUTER] = TierConfig(
        tier=Tier.CPU_ROUTER,
        model_key=router_cfg.get("key", ""),
        max_slots=int(router_cfg.get("slots", 1)),
        device=router_cfg.get("device", "cpu"),
        channel=Channel.SDK,
        enabled=bool(router_cfg.get("key", "")),
    )

    return InferenceRouter(
        tiers=tiers,
        max_queue_depth=max_queue,
        preempt_on_priority=preempt,
    )


# ── Singleton ────────────────────────────────────────────────────────

_router: Optional[InferenceRouter] = None
_router_lock = threading.Lock()


def get_router() -> InferenceRouter:
    """Return the global InferenceRouter singleton."""
    global _router
    if _router is not None:
        return _router

    with _router_lock:
        if _router is not None:
            return _router
        _router = InferenceRouter()
        return _router
