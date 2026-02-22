"""
VirtualAgentManager v2.7 — Centralised agent call server for CosySim.

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
* **Logging / observability** — every request/response tracked

Architecture::

    VirtualAgent.reply()
         │
         ▼  InferenceRequest
    VirtualAgentManager.infer()
         │
         ├── ConversationManager (stateful fast-path / replay)
         ├── LMSClient.chat()  (/api/v1/chat)
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

    # Stats for overlay
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

        # Request hooks — called before/after every inference
        self._pre_hooks: List[Callable] = []
        self._post_hooks: List[Callable] = []

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
                    pass
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

        # Stateful streaming: use conversation's response_id
        if request.conversation_id and request.store is not False:
            try:
                from engine.lmstudio.conversation import get_conversation_manager
                conv = get_conversation_manager().get(request.conversation_id)
                if conv and conv.is_synced:
                    gen = client.chat_stream_stateful(
                        request.messages[-1].get("content", "") if request.messages else "",
                        previous_response_id=conv.response_id,
                        config=cfg,
                        on_event=event_cb,
                    )
                    yield from gen
                    return
            except Exception as exc:
                logger.debug("Stateful stream failed, falling back: %s", exc)

        # Direct streaming
        gen = client.chat_stream(
            request.messages, config=cfg, on_event=event_cb,
            store=request.store,
        )
        yield from gen

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
            pass
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
        return {
            "agents": len(self._agents),
            "total_requests": self._total_requests,
            "total_tokens_in": self._total_tokens_in,
            "total_tokens_out": self._total_tokens_out,
            "total_errors": self._total_errors,
            "avg_latency_ms": (
                self._total_latency_ms / self._total_requests
                if self._total_requests > 0 else 0
            ),
        }

    # ── Internal: execute a single request ──────────────────────────

    def _execute_request(self, request: InferenceRequest) -> InferenceResponse:
        """
        Execute a single inference request.

        Strategy (v2.7 — stateful-first):
        1. If store=False → direct LMSClient.chat(store=False), no conversation
        2. If agent has a conversation_id → ConversationManager (stateful)
        3. Fallback → direct LMSClient.chat()
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
            # Re-apply request-level store override (merge might clobber)
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

        # Stateless one-off: skip conversation entirely
        if request.store is False:
            resp = client.chat(request.messages, config=cfg, store=False)
            return InferenceResponse.from_lms_response(resp)

        # Stateful path (primary): use ConversationManager
        if request.conversation_id:
            try:
                return self._infer_stateful(request, cfg)
            except Exception as exc:
                logger.debug(
                    "Stateful path failed for %s, falling back to direct: %s",
                    request.agent_id, exc,
                )

        # Direct call fallback
        resp = client.chat(request.messages, config=cfg)
        return InferenceResponse.from_lms_response(resp)

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
        elif system_msg and conv.system != system_msg:
            # System prompt changed (interceptors updated it) — update and
            # invalidate server state so next send replays with new prompt
            conv.system = system_msg
            if conv.messages and conv.messages[0].role == "system":
                conv.messages[0].content = system_msg
            conv.invalidate()

        # Use Conversation.send() which handles stateful/replay automatically
        resp = conv.send(
            user_message,
            integrations=cfg.integrations if hasattr(cfg, "integrations") else None,
            response_format=cfg.response_format if hasattr(cfg, "response_format") else None,
        )
        return InferenceResponse.from_lms_response(resp)

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
