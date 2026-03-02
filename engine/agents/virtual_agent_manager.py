"""
VirtualAgentManager v3.3 — Centralised agent call server for CosySim.

All VirtualAgent LLM calls are routed through this manager, giving us full
control over:

* **Model routing** — which model handles which agent
* **Concurrency** — multiple agents can share a single loaded model
* **JIT loading** — load a model on demand, unload after TTL
* **Stateful chats** — conversation state via ConversationManager
  (stateful-first: conversations are the primary path, not a fallback)
* **Store / stateless** — ``store=False`` for one-off queries that don't
  pollute the server's conversation state
* **Streaming** — ``infer_stream()`` yields content deltas with typed
  SSE event callbacks (model_load, reasoning, tool_call, etc.)
* **Structured output** — JSON schema enforcement per request
* **Batch inference** — fan-out multiple agent decisions in parallel
* **Logging / observability** — every request/response tracked
* **Three-tier routing** — InferenceRouter dispatches to GPU/CPU/Router
  tiers with priority queue and slot tracking (v3.3)
* **SDK + REST dual channel** — SDK for tool-calling/streaming,
  REST for stateful chats (v3.3)

Architecture::

    VirtualAgent.reply()
         │
         ▼  InferenceRequest
    VirtualAgentManager.infer()
         │
         ├── InferenceRouter (v3.3: priority queue, tier selection)
         │    ├── SDK channel (.respond, .act, .stream)
         │    └── REST channel (/api/v1/chat, stateful)
         ├── ConversationManager (stateful fast-path / replay)
         ├── LMSClient.chat()  (/api/v1/chat — fallback)
         ├── ConcurrentExecutor (parallel requests)
         └── ResourceManager (model lifecycle)
              │
              ▼  InferenceResponse
    VirtualAgent.process_response()

Usage::

    from engine.agents.virtual_agent_manager import get_virtual_agent_manager

    mgr = get_virtual_agent_manager()

    # Register an agent
    agent = mgr.create_agent(character, scene="bedroom")
    reply = agent.reply("Hello!")

    # Batch decisions for multiple agents
    responses = mgr.infer_batch([req1, req2, req3])

    # Streaming with typed events
    for chunk in mgr.infer_stream(request, on_event=my_handler):
        print(chunk, end="")

    # Stats for overlay (now includes router metrics)
    stats = mgr.get_stats()
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from engine.agents.virtual_agent import (
    InferenceRequest,
    InferenceResponse,
    VirtualAgent,
)

logger = logging.getLogger(__name__)


class VirtualAgentManager:
    """
    Centralized inference router and agent lifecycle manager.

    Controls HOW and WHEN LLM calls happen.  Every VirtualAgent delegates
    its LLM calls here; the agent never talks to LMSClient directly.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, VirtualAgent] = {}
        self._lock = threading.Lock()

        # Stats
        self._total_requests = 0
        self._total_tokens_in = 0
        self._total_tokens_out = 0
        self._total_errors = 0
        self._total_latency_ms = 0.0
        # v2.9: granular pipeline metrics
        self._stateless_requests = 0
        self._stateful_requests = 0
        self._repair_attempts = 0
        self._repair_successes = 0
        self._quality_gate_calls = 0
        # v3.3: SDK router integration
        self._router = None           # lazy-init InferenceRouter
        self._router_enabled = False  # controlled by config
        self._router_init_attempted = False
        self._router_lock = threading.Lock()
        # v4.0: VirtualPipeline integration
        self._pipeline = None
        self._pipeline_init_attempted = False
        self._pipeline_lock = threading.Lock()

        # Request hooks — called before/after every inference
        self._pre_hooks: List[Callable] = []
        self._post_hooks: List[Callable] = []

    # ── Router integration ─────────────────────────────────────────

    def get_router(self):
        """Return the InferenceRouter (lazy-init from config).

        Returns None if the router is disabled, not configured, or
        if no backend clients (SDK/REST) are reachable.
        """
        if self._router is not None:
            return self._router
        if self._router_init_attempted:
            return None

        with self._router_lock:
            # Double-check after acquiring lock
            if self._router is not None:
                return self._router
            if self._router_init_attempted:
                return None
            self._router_init_attempted = True

            try:
                from engine.lmstudio.router import InferenceRouter, TierConfig, Tier
                from engine.config import get_config
                cfg = get_config()
                lms_cfg = cfg.get("lmstudio", {})
                router_cfg = lms_cfg.get("router", {})
                models_cfg = lms_cfg.get("models", {})

                if not router_cfg.get("enabled", False):
                    return None

                # Need at least one model key configured
                has_any_model = any(
                    models_cfg.get(t, {}).get("key")
                    for t in ("primary", "utility", "router")
                )
                if not has_any_model:
                    return None

                tiers = {}
                for tier_name, tier_enum in [
                    ("primary", Tier.GPU_PRIMARY),
                    ("utility", Tier.CPU_UTILITY),
                    ("router", Tier.CPU_ROUTER),
                ]:
                    mcfg = models_cfg.get(tier_name, {})
                    tiers[tier_enum] = TierConfig(
                        tier=tier_enum,
                        model_key=mcfg.get("key", ""),
                        max_slots=mcfg.get("slots", 1),
                        device=mcfg.get("device", "cpu"),
                        enabled=mcfg.get("enabled", True) and bool(mcfg.get("key")),
                    )

                self._router = InferenceRouter(
                    tiers=tiers,
                    max_queue_depth=router_cfg.get("max_queue_depth", 20),
                )

                # Wire SDK + REST clients (non-blocking)
                has_backend = False
                try:
                    from engine.lmstudio.sdk_client import get_sdk_client, SDK_AVAILABLE
                    if SDK_AVAILABLE and lms_cfg.get("sdk", {}).get("enabled", False):
                        self._router._sdk_client = get_sdk_client()
                        has_backend = True
                except Exception:
                    logger.debug("Suppressed exception", exc_info=True)
                try:
                    from engine.lmstudio.lms_client import get_lms_client
                    self._router._rest_client = get_lms_client()
                    has_backend = True
                except Exception:
                    logger.debug("Suppressed exception", exc_info=True)

                if not has_backend:
                    self._router = None
                    return None

                self._router.start()
                self._router_enabled = True
                logger.info("InferenceRouter started with %d tiers", len(tiers))
                return self._router

            except Exception as exc:
                logger.debug("Router init failed (will use direct client): %s", exc)
                return None

    def shutdown_router(self):
        """Stop the background router worker."""
        if self._router:
            self._router.stop()
            self._router = None
            self._router_enabled = False

    # ── Pipeline integration (v4.0) ─────────────────────────────────

    def get_pipeline(self):
        """Return the VirtualPipeline (lazy-init from config).

        Returns None if the pipeline is disabled or if init fails.
        The pipeline provides: StreamWatcher, KillSwitch, TokenAheadRouter,
        and MetricsCollector integration on top of the existing streaming.
        """
        if self._pipeline is not None:
            return self._pipeline
        if self._pipeline_init_attempted:
            return None

        with self._pipeline_lock:
            if self._pipeline is not None:
                return self._pipeline
            if self._pipeline_init_attempted:
                return None
            self._pipeline_init_attempted = True

            try:
                from engine.config import get_config
                from engine.pipeline import VirtualPipeline, PipelineConfig

                cfg = get_config()
                pipe_cfg = cfg.get("pipeline", {})
                if not pipe_cfg.get("enabled", False):
                    return None

                config = PipelineConfig.from_dict(pipe_cfg)

                # Optional: metrics callback
                on_metrics = None
                try:
                    from engine.observability.metrics_collector import get_metrics_collector
                    collector = get_metrics_collector()
                    on_metrics = collector.on_pipeline_result
                except Exception:
                    logger.debug("Suppressed exception", exc_info=True)

                # Optional: tool executor for pre-warming
                tool_executor = None
                try:
                    from engine.mcp.skills_server import get_skill_registry
                    registry = get_skill_registry()
                    if registry:
                        tool_executor = lambda name, ctx: registry.invoke(name, **ctx)
                except Exception:
                    logger.debug("Suppressed exception", exc_info=True)

                self._pipeline = VirtualPipeline(
                    vam=self,
                    config=config,
                    tool_executor=tool_executor,
                    on_metrics=on_metrics,
                )
                logger.info("VirtualPipeline initialized (watcher=%s, kill=%s)",
                            config.watcher_enabled, config.kill_switch_enabled)
                return self._pipeline

            except Exception as exc:
                logger.debug("Pipeline init failed (will use standard path): %s", exc)
                return None

    def infer_with_pipeline(
        self,
        request: InferenceRequest,
        *,
        on_delta: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable] = None,
        on_mood: Optional[Callable[[str], None]] = None,
        on_image_request: Optional[Callable[[str], None]] = None,
        on_action: Optional[Callable[[str], None]] = None,
        on_stat_delta: Optional[Callable] = None,
    ):
        """
        Pipeline-enhanced inference: stream + watch + pre-warm + kill switch.

        Falls back to infer_processed() if pipeline is unavailable.
        Returns PipelineResult (superset of ProcessedResponse).
        """
        pipeline = self.get_pipeline()
        if not pipeline:
            # Fallback to standard streaming path
            result = self.infer_processed(
                request,
                on_delta=on_delta,
                on_tool_call=on_tool_call,
                on_mood=on_mood,
                on_image_request=on_image_request,
                on_action=on_action,
                on_stat_delta=on_stat_delta,
            )
            from engine.pipeline.pipeline_result import PipelineResult
            return PipelineResult.from_processed_response(result)

        # Build a stream function that uses our existing infer_stream
        from engine.agents.stream_processor import StreamProcessor

        proc = StreamProcessor(
            on_delta=on_delta,
            on_tool_call=on_tool_call,
            on_mood=on_mood,
            on_image_request=on_image_request,
            on_action=on_action,
            on_stat_delta=on_stat_delta,
        )

        def stream_fn():
            """Yields content deltas from infer_stream."""
            gen = self.infer_stream(request, on_event=proc.on_event)
            try:
                while True:
                    chunk = next(gen)
                    if chunk:
                        yield chunk
            except StopIteration:
                logger.debug("Suppressed exception", exc_info=True)

        result = pipeline.execute(request, stream_fn=stream_fn)

        # Merge StreamProcessor's callbacks-triggered data with pipeline result
        # (tags detected by callbacks are already in proc, pipeline also detects)
        return result

    # ── Agent lifecycle ─────────────────────────────────────────────

    def create_agent(
        self,
        character: Any,
        *,
        db: Any = None,
        config: Any = None,
        scene: Optional[str] = None,
        model: Optional[str] = None,
        skill_packs: Optional[List[str]] = None,
        use_mcp: bool = False,
        mcp_servers: Optional[List[Dict]] = None,
        inference_config: Any = None,
        max_context_memories: int = 5,
    ) -> VirtualAgent:
        """Create a VirtualAgent, register it, and set up its conversation."""
        agent = VirtualAgent(
            character,
            db=db,
            config=config,
            scene=scene,
            model=model,
            skill_packs=skill_packs,
            use_mcp=use_mcp,
            mcp_servers=mcp_servers,
            inference_config=inference_config,
            max_context_memories=max_context_memories,
        )
        self.register(agent)
        return agent

    def register(self, agent: VirtualAgent) -> None:
        """Register a VirtualAgent with this manager."""
        with self._lock:
            agent._manager = self

            # Set up a conversation via ConversationManager
            conv_id = f"{agent.scene or 'global'}_{agent.id}"
            agent.conversation_id = conv_id
            try:
                from engine.lmstudio.conversation import get_conversation_manager
                conv_mgr = get_conversation_manager()
                conv_mgr.get_or_create(
                    conv_id,
                    system=agent._build_system_prompt([]),
                    model=agent.model,
                )
            except Exception as exc:
                logger.debug("ConversationManager setup failed for %s: %s", agent.id, exc)

            self._agents[agent.id] = agent
            logger.info(
                "Registered VirtualAgent: %s (scene=%s, model=%s)",
                agent.name, agent.scene, agent.model,
            )

    def unregister(self, agent_id: str) -> Optional[VirtualAgent]:
        """Remove a VirtualAgent from this manager."""
        with self._lock:
            agent = self._agents.pop(agent_id, None)
            if agent:
                agent._manager = None
                # Clean up conversation
                try:
                    from engine.lmstudio.conversation import get_conversation_manager
                    get_conversation_manager().delete(agent.conversation_id or "")
                except Exception:
                    logger.debug("Suppressed exception", exc_info=True)
                logger.info("Unregistered VirtualAgent: %s", agent.name)
            return agent

    def get_agent(self, agent_id: str) -> Optional[VirtualAgent]:
        """Get a registered agent by ID."""
        return self._agents.get(agent_id)

    def list_agents(self) -> List[Dict[str, Any]]:
        """Return state summaries for all registered agents."""
        return [a.get_state() for a in self._agents.values()]

    # ── Inference routing ───────────────────────────────────────────

    def infer(self, request: InferenceRequest) -> InferenceResponse:
        """
        Route a single inference request to LMStudio and return the response.

        This is the central method — ALL agent LLM calls flow through here.
        """
        self._total_requests += 1

        # Pre-hooks
        for hook in self._pre_hooks:
            try:
                hook(request)
            except Exception as exc:
                logger.debug("Pre-hook error: %s", exc)

        t0 = time.perf_counter()
        try:
            response = self._execute_request(request)
        except Exception as exc:
            self._total_errors += 1
            response = InferenceResponse.from_error(str(exc))
            logger.warning("Inference failed for agent %s: %s", request.agent_id, exc)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        if not response.latency_ms:
            response.latency_ms = elapsed_ms

        # Track stats
        self._total_tokens_in += response.input_tokens
        self._total_tokens_out += response.output_tokens
        self._total_latency_ms += response.latency_ms

        # Publish to MetricsCollector
        try:
            from engine.monitoring.metrics_collector import get_metrics_collector
            _mc = get_metrics_collector()
            if response.ok:
                _mc.record_llm_call(
                    model_profile=request.model or "unknown",
                    latency_ms=response.latency_ms,
                    tokens_prompt=response.input_tokens,
                    tokens_completion=response.output_tokens,
                    success=True,
                )
            else:
                _mc.record_error("lmstudio", "InferenceError")
        except Exception:
            logger.debug("MetricsCollector record failed", exc_info=True)

        # Auto-persist agent state after successful inference
        if response.ok:
            agent = self._agents.get(request.agent_id)
            if agent:
                agent._persist_state()

        # Post-hooks
        for hook in self._post_hooks:
            try:
                hook(request, response)
            except Exception as exc:
                logger.debug("Post-hook error: %s", exc)

        return response

    def infer_batch(
        self,
        requests: List[InferenceRequest],
        *,
        max_workers: Optional[int] = None,
    ) -> List[InferenceResponse]:
        """
        Run multiple inference requests in parallel using ConcurrentExecutor.

        Useful for AgentLoop ticking multiple characters at once.
        """
        if not requests:
            return []

        # Single request — no need for concurrency overhead
        if len(requests) == 1:
            return [self.infer(requests[0])]

        try:
            from engine.lmstudio.concurrency import ConcurrentExecutor
            workers = max_workers or min(len(requests), 4)
            with ConcurrentExecutor(max_workers=workers) as executor:
                futures = []
                for i, req in enumerate(requests):
                    futures.append(executor.submit(
                        req.messages,
                        model=req.model,
                        temperature=req.temperature,
                        max_tokens=req.max_output_tokens,
                        integrations=req.integrations,
                        task_id=i,
                        metadata={"agent_id": req.agent_id},
                    ))
                concurrent_results = executor.gather(futures)

            responses = []
            for cr in concurrent_results:
                if cr.ok:
                    responses.append(InferenceResponse(
                        content=cr.content,
                        model=cr.model,
                        input_tokens=cr.input_tokens,
                        output_tokens=cr.output_tokens,
                        latency_ms=cr.latency_ms,
                    ))
                else:
                    responses.append(InferenceResponse.from_error(cr.error or "unknown"))
            return responses

        except Exception as exc:
            logger.error("Batch inference failed: %s", exc)
            return [InferenceResponse.from_error(str(exc)) for _ in requests]

    # ── Streaming inference ────────────────────────────────────────

    def infer_stream(
        self,
        request: InferenceRequest,
        *,
        on_event: Optional[Callable] = None,
    ):
        """
        Stream a single inference request, yielding content deltas.

        Uses ``LMSClient.chat_stream()`` or ``chat_stream_stateful()``
        depending on whether the agent has an active conversation.

        The optional ``on_event`` callback receives typed ``LMSStreamEvent``
        objects for model_load, reasoning, tool_call progress etc.

        Returns the ``LMSResponse`` (available via generator return / StopIteration.value).
        """
        from engine.lmstudio.lms_client import get_lms_client
        from engine.lmstudio.inference_config import InferenceConfig

        self._total_requests += 1
        t0 = time.perf_counter()
        client = get_lms_client()

        cfg = InferenceConfig(
            model=request.model,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            integrations=request.integrations,
            store=request.store,
        )

        agent = self._agents.get(request.agent_id)
        if agent and agent._inference_config:
            cfg = InferenceConfig.merge(cfg, agent._inference_config)
            if request.store is not None:
                cfg.store = request.store

        event_cb = on_event or request.on_event

        lms_response = None

        # Stateful streaming: use conversation's response_id
        if request.conversation_id and request.store is not False:
            try:
                from engine.lmstudio.conversation import get_conversation_manager
                conv_mgr = get_conversation_manager()
                conv = conv_mgr.get(request.conversation_id)

                if conv and conv.is_synced:
                    # Fast path: server has our context
                    user_msg = request.messages[-1].get("content", "") if request.messages else ""
                    gen = client.chat_stream_stateful(
                        user_msg,
                        previous_response_id=conv.response_id,
                        config=cfg,
                        on_event=event_cb,
                    )
                    lms_response = yield from gen

                    # Update conversation state with new response_id
                    if lms_response and lms_response.response_id:
                        from engine.lmstudio.conversation import ConversationMessage
                        conv.messages.append(ConversationMessage(
                            role="user", content=user_msg, timestamp=time.time()))
                        conv.messages.append(ConversationMessage(
                            role="assistant", content=lms_response.content,
                            timestamp=time.time(),
                            metadata={"response_id": lms_response.response_id}))
                        conv.response_id = lms_response.response_id
                        conv._response_id_history.append(lms_response.response_id)
                        conv._server_synced = True
                        conv.last_active = time.time()

                    return lms_response

            except Exception as exc:
                logger.debug("Stateful stream failed, falling back: %s", exc)

        # Direct streaming (or first call with conversation_id)
        gen = client.chat_stream(
            request.messages, config=cfg, on_event=event_cb,
            store=request.store,
        )
        lms_response = yield from gen

        # If we have a conversation_id, create/update the conversation from the stream result
        if request.conversation_id and request.store is not False and lms_response:
            try:
                from engine.lmstudio.conversation import get_conversation_manager
                conv_mgr = get_conversation_manager()
                conv = conv_mgr.get(request.conversation_id)
                if conv is None:
                    # Extract system prompt from messages
                    system_msg = ""
                    for m in request.messages:
                        if m.get("role") == "system":
                            system_msg = m.get("content", "")
                            break
                    conv = conv_mgr.create(
                        request.conversation_id,
                        system=system_msg,
                        model=request.model,
                        config=cfg,
                    )
                # Record the exchange and response_id
                from engine.lmstudio.conversation import ConversationMessage
                user_msg = ""
                for m in reversed(request.messages):
                    if m.get("role") == "user":
                        user_msg = m.get("content", "")
                        break
                if user_msg:
                    conv.messages.append(ConversationMessage(
                        role="user", content=user_msg, timestamp=time.time()))
                conv.messages.append(ConversationMessage(
                    role="assistant", content=lms_response.content,
                    timestamp=time.time(),
                    metadata={"response_id": lms_response.response_id}))
                if lms_response.response_id:
                    conv.response_id = lms_response.response_id
                    conv._response_id_history.append(lms_response.response_id)
                    conv._server_synced = True
                conv.last_active = time.time()
            except Exception as exc:
                logger.debug("Post-stream conversation update failed: %s", exc)

        return lms_response

    def infer_processed(
        self,
        request: InferenceRequest,
        *,
        on_delta: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable] = None,
        on_mood: Optional[Callable[[str], None]] = None,
        on_image_request: Optional[Callable[[str], None]] = None,
        on_action: Optional[Callable[[str], None]] = None,
        on_stat_delta: Optional[Callable] = None,
    ) -> "ProcessedResponse":
        """
        Stream an inference request and return a rich ProcessedResponse.

        Combines ``infer_stream()`` with ``StreamProcessor`` to provide:
        - Clean text (inline tags stripped)
        - Extracted mood/image/action/stat tags
        - Tool call records
        - Reasoning content
        - Full v1 stats

        Real-time callbacks fire as events arrive during streaming.
        """
        from engine.agents.stream_processor import StreamProcessor

        proc = StreamProcessor(
            on_delta=on_delta,
            on_tool_call=on_tool_call,
            on_mood=on_mood,
            on_image_request=on_image_request,
            on_action=on_action,
            on_stat_delta=on_stat_delta,
        )

        # Stream with the processor as the event handler.
        # Capture the generator's return value (LMSResponse) via StopIteration.
        gen = self.infer_stream(request, on_event=proc.on_event)
        lms_response = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            lms_response = e.value

        result = proc.result()

        # Attach LMSResponse metadata to ProcessedResponse for callers
        if lms_response:
            result.response_id = getattr(lms_response, "response_id", "")
            result.model = getattr(lms_response, "model", "")

        return result

    # ── High-level convenience ──────────────────────────────────────

    def reply(
        self,
        agent_id: str,
        user_message: str,
        *,
        chain_id: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        use_tools: bool = True,
    ) -> str:
        """High-level: build request, infer, process response."""
        agent = self._agents.get(agent_id)
        if not agent:
            logger.warning("Agent %s not registered", agent_id)
            return ""
        return agent.reply(
            user_message,
            chain_id=chain_id,
            history=history,
            use_tools=use_tools,
        )

    def quick_query(
        self, agent_id: str, prompt: str, *, max_tokens: int = 2000,
    ) -> str:
        """High-level: lightweight query for a registered agent."""
        agent = self._agents.get(agent_id)
        if not agent:
            return ""
        return agent.quick_query(prompt, max_tokens=max_tokens)

    # ── Model control ───────────────────────────────────────────────

    def set_model(self, agent_id: str, model: str) -> bool:
        """Change which model an agent uses."""
        agent = self._agents.get(agent_id)
        if not agent:
            return False
        agent.set_model(model)
        # Update conversation model
        try:
            from engine.lmstudio.conversation import get_conversation_manager
            conv = get_conversation_manager().get(agent.conversation_id or "")
            if conv:
                conv.model = model
                conv.invalidate()
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        return True

    def set_all_models(self, model: str) -> int:
        """Set the same model for all agents."""
        count = 0
        for agent_id in list(self._agents.keys()):
            if self.set_model(agent_id, model):
                count += 1
        return count

    def load_model(self, model: str, **kwargs) -> bool:
        """Load a model into LMStudio via LMSClient."""
        try:
            from engine.lmstudio.lms_client import get_lms_client
            client = get_lms_client()
            client.load_model(model, **kwargs)
            return True
        except Exception as exc:
            logger.error("Failed to load model %s: %s", model, exc)
            return False

    def unload_model(self, model: str) -> bool:
        """Unload a model from LMStudio."""
        try:
            from engine.lmstudio.lms_client import get_lms_client
            client = get_lms_client()
            client.unload_model(model)
            return True
        except Exception as exc:
            logger.error("Failed to unload model %s: %s", model, exc)
            return False

    # ── Hooks ───────────────────────────────────────────────────────

    def add_pre_hook(self, fn: Callable[[InferenceRequest], None]) -> None:
        """Add a hook called before every inference request."""
        self._pre_hooks.append(fn)

    def add_post_hook(
        self, fn: Callable[[InferenceRequest, InferenceResponse], None],
    ) -> None:
        """Add a hook called after every inference response."""
        self._post_hooks.append(fn)

    # ── Stats ───────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate stats for overlay/admin."""
        stats = {
            "agents": len(self._agents),
            "total_requests": self._total_requests,
            "total_tokens_in": self._total_tokens_in,
            "total_tokens_out": self._total_tokens_out,
            "total_errors": self._total_errors,
            "avg_latency_ms": (
                self._total_latency_ms / self._total_requests
                if self._total_requests > 0 else 0
            ),
            "stateless_requests": self._stateless_requests,
            "stateful_requests": self._stateful_requests,
            "repair_attempts": self._repair_attempts,
            "repair_successes": self._repair_successes,
            "quality_gate_calls": self._quality_gate_calls,
            "token_savings_pct": (
                round(100 * self._stateful_requests / self._total_requests, 1)
                if self._total_requests > 0 else 0
            ),
            "router_enabled": self._router_enabled,
            "pipeline_enabled": self._pipeline is not None,
        }
        if self._router:
            stats["router"] = self._router.get_metrics()
        if self._pipeline:
            stats["pipeline"] = {
                "watcher_enabled": self._pipeline.config.watcher_enabled,
                "kill_switch_enabled": self._pipeline.config.kill_switch_enabled,
                "pre_warm_enabled": self._pipeline.config.pre_warm_enabled,
            }
        return stats

    # ── Internal: execute a single request ──────────────────────────

    def _execute_request(self, request: InferenceRequest) -> InferenceResponse:
        """
        Execute a single inference request.

        Strategy (v3.3 — router-aware, stateful-first with conversation repair):
        0. If InferenceRouter is active → route stateless/direct calls through it
        1. If store=False → direct LMSClient.chat(store=False), no conversation
        2. If agent has a conversation_id → ConversationManager (stateful)
        3. Fallback → direct LMSClient.chat()
        4. If response is garbage → auto-retry with lower temperature (max 2 retries)
        """
        from engine.lmstudio.lms_client import get_lms_client
        from engine.lmstudio.inference_config import InferenceConfig

        client = get_lms_client()

        # Build InferenceConfig from request
        cfg = InferenceConfig(
            model=request.model,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            integrations=request.integrations,
            store=request.store,
        )

        # Merge with agent-level inference config if available
        agent = self._agents.get(request.agent_id)
        if agent and agent._inference_config:
            cfg = InferenceConfig.merge(cfg, agent._inference_config)
            if request.store is not None:
                cfg.store = request.store

        # Structured output
        if request.structured_schema:
            cfg = InferenceConfig.merge(cfg, InferenceConfig(
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.schema_name or "output",
                        "schema": request.structured_schema,
                    },
                },
            ))

        # v3.1: Attach MCP skills server integration if available
        if cfg.integrations is None:
            try:
                from engine.mcp.skills_server import get_skills_integration
                integration = get_skills_integration()
                if integration:
                    cfg.integrations = [integration]
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

        # ── v3.3: Router dispatch for stateless calls ──
        router = self.get_router()
        if router and request.store is False and not request.conversation_id:
            routed = self._dispatch_via_router(router, request, cfg)
            if routed is not None:
                return routed

        # Stateless one-off: skip conversation entirely
        if request.store is False:
            self._stateless_requests += 1
            resp = client.chat(request.messages, config=cfg, store=False)
            return InferenceResponse.from_lms_response(resp)

        # Stateful path (primary): use ConversationManager
        if request.conversation_id:
            self._stateful_requests += 1
            try:
                response = self._infer_stateful(request, cfg)
                if self._is_garbage_response(response):
                    self._repair_attempts += 1
                    repaired = self._retry_with_repair(request, cfg, attempt=0)
                    if repaired and not self._is_garbage_response(repaired):
                        self._repair_successes += 1
                        return repaired
                return response
            except Exception as exc:
                logger.debug(
                    "Stateful path failed for %s, falling back to direct: %s",
                    request.agent_id, exc,
                )

        # Direct call fallback (optionally via router)
        if router:
            routed = self._dispatch_via_router(router, request, cfg)
            if routed is not None:
                return routed

        resp = client.chat(request.messages, config=cfg)
        response = InferenceResponse.from_lms_response(resp)

        if self._is_garbage_response(response):
            self._repair_attempts += 1
            repaired = self._retry_with_repair(request, cfg, attempt=0)
            if repaired and not self._is_garbage_response(repaired):
                self._repair_successes += 1
                return repaired

        return response

    def _dispatch_via_router(self, router, request, cfg) -> Optional[InferenceResponse]:
        """Try to route a request through the InferenceRouter.

        Returns an InferenceResponse on success, None if the router can't
        handle it (caller falls back to direct client).
        """
        try:
            from engine.lmstudio.router import InferenceRequest as RouterReq, Priority

            priority_map = {
                "realtime": Priority.REALTIME,
                "interactive": Priority.INTERACTIVE,
                "background": Priority.BACKGROUND,
                "batch": Priority.BATCH,
            }
            priority = priority_map.get(
                getattr(request, "priority", None) or "interactive",
                Priority.INTERACTIVE,
            )

            router_req = RouterReq(
                messages=request.messages,
                config=cfg,
                agent_id=request.agent_id,
                priority=priority,
                task_type=getattr(request, "task_type", "chat"),
            )

            future = router.submit(router_req)
            result = future.result(timeout=90)
            return InferenceResponse.from_lms_response(result)

        except Exception as exc:
            logger.debug("Router dispatch failed, falling back to direct: %s", exc)
            return None

    def _is_garbage_response(self, response: InferenceResponse) -> bool:
        """Check if a response is garbage that should be retried."""
        from engine.agents.evaluator import get_text_evaluator
        evaluator = get_text_evaluator()
        return evaluator.is_garbage(response.content or "")

    def _retry_with_repair(
        self, request: InferenceRequest, cfg: Any, attempt: int = 0,
    ) -> Optional[InferenceResponse]:
        """Retry a failed/garbage response with adjusted parameters.

        Uses conversation branching to go back to the last valid state
        and regenerate with lower temperature.
        """
        if attempt >= 2:
            return None

        from engine.lmstudio.lms_client import get_lms_client
        from engine.lmstudio.inference_config import InferenceConfig
        client = get_lms_client()

        # Reduce temperature for retry
        retry_cfg = InferenceConfig.merge(cfg, InferenceConfig(
            temperature=max(0.3, (cfg.temperature or 0.7) - 0.2 * (attempt + 1)),
        ))
        logger.info(
            "Conversation repair attempt %d for %s (temp=%.2f)",
            attempt + 1, request.agent_id, retry_cfg.temperature or 0.7,
        )

        try:
            if request.conversation_id:
                return self._infer_stateful(request, retry_cfg)
            else:
                resp = client.chat(request.messages, config=retry_cfg)
                return InferenceResponse.from_lms_response(resp)
        except Exception as exc:
            logger.debug("Repair attempt %d failed: %s", attempt + 1, exc)
            return None

    def _infer_stateful(
        self, request: InferenceRequest, cfg: Any,
    ) -> InferenceResponse:
        """Use ConversationManager for stateful inference.

        The ConversationManager handles:
        - First call: creates a new server conversation
        - Subsequent: sends only the new user message with previous_response_id
        - Model unload: transparently replays full history
        - System prompt changes: invalidates server state (forces replay)
        """
        from engine.lmstudio.conversation import get_conversation_manager
        from engine.lmstudio.inference_config import InferenceConfig

        conv_mgr = get_conversation_manager()
        conv = conv_mgr.get(request.conversation_id or "")

        # Extract system prompt and user message from request
        system_msg = ""
        user_message = ""
        for m in request.messages:
            if m.get("role") == "system":
                system_msg = m.get("content", "")
        for m in reversed(request.messages):
            if m.get("role") == "user":
                user_message = m.get("content", "")
                break

        if not user_message:
            raise ValueError("No user message in request")

        if conv is None:
            conv = conv_mgr.create(
                request.conversation_id or f"auto_{request.agent_id}",
                system=system_msg,
                model=request.model,
                config=cfg,
            )
        elif system_msg:
            # Use smart diff — only invalidates if system prompt actually changed
            conv.update_system_if_changed(system_msg)

        # Use Conversation.send() which handles stateful/replay automatically
        resp = conv.send(
            user_message,
            integrations=cfg.integrations if hasattr(cfg, "integrations") else None,
            response_format=cfg.response_format if hasattr(cfg, "response_format") else None,
        )
        return InferenceResponse.from_lms_response(resp)

    def infer_quality_gate(
        self,
        request: InferenceRequest,
        *,
        variants: int = 2,
        personality_keywords: Optional[set] = None,
        recent_messages: Optional[list] = None,
    ) -> InferenceResponse:
        """Generate multiple response variants and return the best one.

        Uses store=false for all variants (disposable), then scores each
        with the TextEvaluator and returns the highest-scoring response.

        Args:
            request: The inference request.
            variants: Number of variants to generate (2-4).
            personality_keywords: Keywords for personality scoring.
            recent_messages: Recent messages for variety scoring.
        """
        self._quality_gate_calls += 1
        from engine.agents.evaluator import TextEvaluator
        from engine.lmstudio.inference_config import InferenceConfig

        evaluator = TextEvaluator(personality_keywords=personality_keywords or set())
        variants = max(2, min(4, variants))

        candidates = []
        temps = [0.7, 1.1, 0.9, 0.5][:variants]

        for i, temp in enumerate(temps):
            try:
                cfg = InferenceConfig(
                    model=request.model,
                    temperature=temp,
                    max_output_tokens=request.max_output_tokens,
                    store=False,
                )

                # Force stateless for variant generation
                variant_request = InferenceRequest(
                    agent_id=request.agent_id,
                    messages=request.messages,
                    temperature=temp,
                    max_output_tokens=request.max_output_tokens,
                    store=False,
                    priority=request.priority,
                    metadata={**(request.metadata or {}), "quality_gate_variant": i},
                )

                from engine.lmstudio.lms_client import get_lms_client
                client = get_lms_client()
                resp = client.chat(variant_request.messages, config=cfg)
                inf_resp = InferenceResponse.from_lms_response(resp)

                text = inf_resp.content or ""
                score = evaluator.score_heuristic(
                    text,
                    recent_messages=recent_messages,
                    personality_keywords=personality_keywords,
                )
                candidates.append((inf_resp, score.total))
                logger.debug(
                    "Quality gate variant %d (temp=%.1f): score=%.2f, len=%d",
                    i, temp, score.total, len(text),
                )
            except Exception as exc:
                logger.debug("Quality gate variant %d failed: %s", i, exc)

        if not candidates:
            # Fallback to normal inference
            return self.infer(request)

        # Return highest scoring
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def __repr__(self) -> str:
        return (
            f"<VirtualAgentManager agents={len(self._agents)} "
            f"requests={self._total_requests}>"
        )


# ── Singleton ───────────────────────────────────────────────────────────

_manager_instance: Optional[VirtualAgentManager] = None


def get_virtual_agent_manager() -> VirtualAgentManager:
    """Return the global VirtualAgentManager singleton."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = VirtualAgentManager()
    return _manager_instance
