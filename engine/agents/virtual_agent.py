"""
VirtualAgent — Decoupled agent identity that routes LLM calls through VirtualAgentManager.

VirtualAgent separates the *concept* of an agent (identity, state, conversation
history, prompt building) from the *execution* of LLM inference.  It satisfies
the ``IAgent`` protocol so it's a drop-in replacement for ``CharacterAgent``
anywhere in the system, but all LLM calls go through the centralised
``VirtualAgentManager`` which controls model routing, concurrency, JIT loading,
and resource strategy.

Architecture::

    Scene / AgentLoop
         │
         ▼
    VirtualAgent  ──(InferenceRequest)──▶  VirtualAgentManager
         │                                       │
         │                                  ┌────┴────┐
         │                                  │LMSClient│  ConversationManager
         │                                  └────┬────┘  ConcurrentExecutor
         ◀──(InferenceResponse)──────────────────┘

Usage::

    from engine.agents.virtual_agent import VirtualAgent
    from engine.agents.virtual_agent_manager import get_virtual_agent_manager

    mgr = get_virtual_agent_manager()
    agent = mgr.create_agent(character, scene="bedroom")
    reply = agent.reply("Hey, what are you up to?")
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from engine.agents.protocols import AgentCapability

logger = logging.getLogger(__name__)


# ── Request / Response ──────────────────────────────────────────────────

@dataclass
class InferenceRequest:
    """An LLM inference request produced by a VirtualAgent."""
    agent_id: str
    messages: List[Dict[str, str]]
    model: Optional[str] = None
    conversation_id: Optional[str] = None
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    use_mcp: bool = False
    integrations: Optional[List[Dict]] = None
    structured_schema: Optional[Dict] = None
    schema_name: Optional[str] = None
    previous_response_id: Optional[str] = None
    # v2.7: store/stateless control
    store: Optional[bool] = None          # None=server default (True), False=stateless
    stream: bool = False                  # Request streaming response
    on_event: Optional[Any] = None        # Callback for streaming events
    priority: int = 5  # 0=highest, 9=lowest
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class InferenceResponse:
    """An LLM response returned to a VirtualAgent."""
    content: str = ""
    reasoning_content: str = ""
    model: str = ""
    response_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: float = 0.0
    tool_calls: List[Dict] = field(default_factory=list)
    error: Optional[str] = None
    # v2.7: native v1 stats
    server_tps: float = 0.0
    time_to_first_token_s: float = 0.0
    model_load_time_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def is_stateful(self) -> bool:
        """Whether the server stored this response for continuations."""
        return bool(self.response_id and self.response_id.startswith("resp_"))

    @property
    def tokens_per_second(self) -> float:
        if self.server_tps > 0:
            return self.server_tps
        if self.latency_ms > 0 and self.output_tokens > 0:
            return self.output_tokens / (self.latency_ms / 1000.0)
        return 0.0

    @classmethod
    def from_lms_response(cls, resp: Any) -> "InferenceResponse":
        """Create from an LMSResponse."""
        return cls(
            content=getattr(resp, "content", "") or "",
            reasoning_content=getattr(resp, "reasoning_content", "") or "",
            model=getattr(resp, "model", ""),
            response_id=getattr(resp, "response_id", ""),
            input_tokens=getattr(resp, "input_tokens", 0),
            output_tokens=getattr(resp, "output_tokens", 0),
            reasoning_tokens=getattr(resp, "reasoning_tokens", 0),
            latency_ms=getattr(resp, "latency_ms", 0.0),
            tool_calls=getattr(resp, "tool_calls", []) or [],
            server_tps=getattr(resp, "server_tps", 0.0),
            time_to_first_token_s=getattr(resp, "time_to_first_token_s", 0.0),
            model_load_time_s=getattr(resp, "model_load_time_s", 0.0),
        )

    @classmethod
    def from_error(cls, error: str) -> "InferenceResponse":
        return cls(error=error)


# ── VirtualAgent ────────────────────────────────────────────────────────

class VirtualAgent:
    """
    Decoupled agent: manages identity, state, prompt building, conversation
    history.  Routes all LLM calls through VirtualAgentManager.

    Satisfies the ``IAgent`` protocol (reply, quick_query, cancel).
    """

    def __init__(
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
    ) -> None:
        self.character = character
        self.db = db
        self.scene = scene
        self.model = model
        self.skill_packs = skill_packs or []
        self.use_mcp = use_mcp
        self.mcp_servers = mcp_servers or []
        self._inference_config = inference_config
        self.max_context_memories = max_context_memories

        if config is None:
            from engine.config import get_config
            config = get_config()
        self.config = config

        if not self.use_mcp:
            self.use_mcp = bool(config.get("lmstudio.mcp_enabled", False))

        # Capabilities
        self.capabilities: Set[AgentCapability] = {
            AgentCapability.TEXT, AgentCapability.MEMORY,
        }
        if self.skill_packs:
            self.capabilities.add(AgentCapability.TOOLS)
        if self.use_mcp:
            self.capabilities.add(AgentCapability.GOVERNED)

        # Local state mirror — mood, energy, arousal, custom keys
        self._state: Dict[str, Any] = {
            "mood": getattr(character, "mood", "neutral"),
            "energy": getattr(character, "energy", 1.0),
            "arousal": getattr(character, "arousal", 0.0),
        }

        # Conversation ID (set by manager when registered)
        self.conversation_id: Optional[str] = None

        # Cancellation
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()

        # RAG memory (lazy)
        self._rag: Any = None

        # Manager reference (set by VirtualAgentManager.register)
        self._manager: Any = None

        # Callbacks
        self._on_response: Optional[Callable] = None

        # MCP registration (best-effort)
        try:
            from engine.mcp.character_registry import get_character_registry
            get_character_registry().ensure(
                character.id, display_name=character.name,
            )
            if scene:
                from engine.mcp.framework import get_framework
                get_framework().get_character(character.id).enter_scene(scene)
        except Exception:
            pass

        # Restore persisted state if available
        self.load_state()

    @property
    def id(self) -> str:
        return self.character.id

    @property
    def name(self) -> str:
        return self.character.name

    # ── IAgent protocol ─────────────────────────────────────────────

    def reply(
        self,
        user_message: str,
        *,
        chain_id: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        use_tools: bool = True,
        governance_context: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Generate a reply by routing through VirtualAgentManager.

        Parameters
        ----------
        governance_context : str, optional
            Supplementary system-prompt text injected by the interceptor
            pipeline (scene state, game rules, skills, etc.).  Appended
            after the agent's own system prompt.
        """
        self._cancel_event.clear()
        mgr = self._get_manager()

        # Build the inference request
        request = self.build_request(
            user_message,
            history=history,
            use_tools=use_tools,
            chain_id=chain_id,
            governance_context=governance_context,
        )

        # Route through manager
        response = mgr.infer(request)

        # Process the response (update state, log events, etc.)
        reply_text = self.process_response(response, chain_id=chain_id)
        return reply_text

    def quick_query(self, prompt: str, *, max_tokens: int = 2000) -> str:
        """Lightweight single-shot — no tools, no RAG, no events.

        Uses ``store=False`` so the query doesn't pollute the server's
        conversation state or return a response_id.
        """
        mgr = self._get_manager()
        system = self._build_system_prompt([])
        request = InferenceRequest(
            agent_id=self.id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            temperature=0.9,
            max_output_tokens=max_tokens,
            store=False,
            priority=3,
            metadata={"type": "quick_query"},
        )
        response = mgr.infer(request)
        return (response.content or response.reasoning_content or "").strip()

    def cancel(self) -> None:
        """Cancel the currently active inference request."""
        self._cancel_event.set()

    # ── Request building ────────────────────────────────────────────

    def build_request(
        self,
        user_message: str,
        *,
        history: Optional[List[Dict]] = None,
        use_tools: bool = True,
        chain_id: Optional[str] = None,
        governance_context: Optional[str] = None,
    ) -> InferenceRequest:
        """Build an InferenceRequest from a user message."""
        # RAG memories
        memories = self._search_memories(user_message)

        # System prompt (base from character + memories)
        system_prompt = self._build_system_prompt(memories)

        # Append governance context (interceptor pipeline injections)
        if governance_context:
            system_prompt = system_prompt + "\n\n" + governance_context

        # Build messages
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        for turn in (history or []):
            messages.append({
                "role": turn.get("role", "user"),
                "content": turn.get("content", ""),
            })
        messages.append({"role": "user", "content": user_message})

        # MCP integrations
        integrations: Optional[List[Dict]] = None
        if use_tools and self.use_mcp:
            integrations = list(self.mcp_servers) if self.mcp_servers else []
            mcp_url = self.config.get("lmstudio.cosysim_mcp_url", "")
            if mcp_url:
                integrations.append({
                    "type": "ephemeral_mcp",
                    "server_url": mcp_url,
                })
            if not integrations:
                integrations = None

        return InferenceRequest(
            agent_id=self.id,
            messages=messages,
            model=self.model,
            conversation_id=self.conversation_id,
            use_mcp=use_tools and self.use_mcp,
            integrations=integrations,
            priority=5,
            metadata={
                "chain_id": chain_id,
                "scene": self.scene,
                "character_name": self.name,
                "memory_count": len(memories),
            },
        )

    # ── Response processing ─────────────────────────────────────────

    def process_response(
        self,
        response: InferenceResponse,
        *,
        chain_id: Optional[str] = None,
    ) -> str:
        """Process an InferenceResponse: update state, log events, return text."""
        if response.error:
            logger.warning("Agent %s got error: %s", self.name, response.error)
            self._log_event("llm_error", chain_id, {"error": response.error})
            return ""

        reply_text = response.content or response.reasoning_content or ""

        # Track response_id for conversation branching
        if response.response_id:
            self._state["last_response_id"] = response.response_id

        # Log to EventChain
        self._log_event("llm_response", chain_id, {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "reasoning_tokens": response.reasoning_tokens,
            "latency_ms": response.latency_ms,
            "model": response.model,
            "response_id": response.response_id,
            "tps": round(response.tokens_per_second, 1),
            "preview": reply_text[:120],
        })

        # Update MCP state
        if reply_text and not self._cancel_event.is_set():
            try:
                from engine.mcp.character_registry import get_character_registry
                get_character_registry().set_state(self.character.id, {
                    "mood": self._state.get("mood", "neutral"),
                    "last_reply": reply_text[:200],
                    "scene": self.scene or "unknown",
                })
            except Exception:
                pass

            # ActivityBus
            try:
                from engine.services.activity_bus import get_activity_bus
                get_activity_bus().publish(
                    activity_type="character_reply",
                    description=f"{self.name}: {reply_text[:120]}",
                    agent_id=self.id,
                    scene=self.scene or "unknown",
                    data={
                        "reply_preview": reply_text[:300],
                        "model": response.model,
                        "tokens": response.output_tokens,
                    },
                )
            except Exception:
                pass

        if self._on_response:
            try:
                self._on_response(self, response, reply_text)
            except Exception:
                pass

        return reply_text

    # ── State management ────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        """Return current agent state snapshot."""
        return {
            "agent_id": self.id,
            "name": self.name,
            "scene": self.scene,
            "model": self.model,
            "conversation_id": self.conversation_id,
            "capabilities": [c.value for c in self.capabilities],
            **self._state,
        }

    def update_state(self, **kwargs: Any) -> None:
        """Update agent state fields and auto-persist."""
        self._state.update(kwargs)
        # Sync back to character object where possible
        for key in ("mood", "energy", "arousal"):
            if key in kwargs and hasattr(self.character, key):
                setattr(self.character, key, kwargs[key])
        self._persist_state()

    def save_state(self) -> bool:
        """Explicitly persist current state to the database."""
        return self._persist_state()

    def load_state(self) -> bool:
        """Load persisted state from the database, merging into _state."""
        try:
            import sqlite3
            db_path = self._get_state_db_path()
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT state_json FROM agent_state WHERE agent_id = ?",
                (self.id,),
            ).fetchone()
            conn.close()
            if row:
                import json
                stored = json.loads(row["state_json"])
                self._state.update(stored)
                # Sync back to character
                for key in ("mood", "energy", "arousal"):
                    if key in stored and hasattr(self.character, key):
                        setattr(self.character, key, stored[key])
                logger.debug("Loaded state for agent %s", self.name)
                return True
        except Exception as exc:
            logger.debug("load_state failed for %s: %s", self.id, exc)
        return False

    def _persist_state(self) -> bool:
        """Write current _state to SQLite (best-effort)."""
        try:
            import json
            import sqlite3
            db_path = self._get_state_db_path()
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_state (
                    agent_id TEXT PRIMARY KEY,
                    scene TEXT,
                    model TEXT,
                    state_json TEXT,
                    updated_at REAL
                )
            """)
            conn.execute("""
                INSERT OR REPLACE INTO agent_state
                (agent_id, scene, model, state_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (self.id, self.scene, self.model, json.dumps(self._state), time.time()))
            conn.commit()
            conn.close()
            return True
        except Exception as exc:
            logger.debug("_persist_state failed for %s: %s", self.id, exc)
            return False

    @staticmethod
    def _get_state_db_path():
        """Return the path to the agent state database."""
        from pathlib import Path
        data_dir = Path(__file__).parent.parent.parent / "data"
        data_dir.mkdir(exist_ok=True)
        return data_dir / "agent_state.db"

    def set_model(self, model: str) -> None:
        """Change the model this agent uses."""
        self.model = model

    # ── Prompt building ─────────────────────────────────────────────

    def _build_system_prompt(self, memories: List[str]) -> str:
        """Build the full system prompt for the character."""
        char = self.character
        name = char.name

        # MCP brief
        mcp_brief = ""
        try:
            if self.scene:
                from engine.mcp.framework import get_framework
                fw_char = get_framework().get_character(char.id)
                mcp_brief = fw_char.brief()
        except Exception:
            pass

        warmth = getattr(char, "warmth", 0.5)
        formality = getattr(char, "formality", 0.5)
        humor = getattr(char, "humor", 0.5)
        flirt = getattr(char, "flirtiness", 0.5)
        intel = getattr(char, "intelligence", 0.5)
        creativity = getattr(char, "creativity", 0.5)
        mood = self._state.get("mood", getattr(char, "mood", "relaxed"))

        def _level(val: float) -> str:
            if val >= 0.8: return "very high"
            if val >= 0.6: return "high"
            if val >= 0.4: return "moderate"
            if val >= 0.2: return "low"
            return "very low"

        parts = [
            f"You are {name}.",
            f"Personality: warmth={_level(warmth)}, humor={_level(humor)}, "
            f"flirtiness={_level(flirt)}, formality={_level(formality)}, "
            f"creativity={_level(creativity)}, intelligence={_level(intel)}.",
            f"Current mood: {mood}.",
        ]

        desc = getattr(char, "description", "") or ""
        if desc:
            parts.append(f"About you: {desc}")

        backstory = getattr(char, "backstory", "") or ""
        if backstory:
            parts.append(f"Backstory: {backstory}")

        custom = self.config.get("llm.custom_context", "").strip()
        if custom:
            parts.append(custom)

        if memories:
            parts.append("\nRelevant memories:")
            for mem in memories[:self.max_context_memories]:
                parts.append(f"- {mem}")

        parts.append(
            "\nRespond naturally in-character. Keep replies concise unless detail is asked for."
        )

        if mcp_brief:
            parts.append(f"\n[MCP Context]\n{mcp_brief}")

        return "\n".join(parts)

    def _search_memories(self, query: str) -> List[str]:
        """Query RAG for relevant memories."""
        if self._rag is None:
            try:
                from content.simulation.database.rag import RAGMemory
                self._rag = RAGMemory()
            except Exception:
                return []
        try:
            results = self._rag.search(
                query,
                n_results=self.max_context_memories,
                character_id=self.character.id,
            )
            texts = []
            for r in (results or []):
                if isinstance(r, dict):
                    texts.append(r.get("content", str(r)))
                else:
                    texts.append(str(r))
            return texts
        except Exception:
            return []

    # ── Event logging ───────────────────────────────────────────────

    def _log_event(
        self, event_type: str, chain_id: Optional[str], payload: Dict,
    ) -> None:
        """Log to EventChain (best-effort)."""
        if not chain_id:
            return
        try:
            from content.simulation.database.events import get_event_chain
            ec = get_event_chain()
            if ec:
                ec.log(
                    event_type,
                    actor=self.name,
                    payload=payload,
                    summary=payload.get("preview", str(payload)[:120]),
                    chain_id=chain_id,
                    character_id=self.id,
                )
        except Exception:
            pass

    # ── Internal ────────────────────────────────────────────────────

    def _get_manager(self):
        """Get the VirtualAgentManager."""
        if self._manager is not None:
            return self._manager
        from engine.agents.virtual_agent_manager import get_virtual_agent_manager
        return get_virtual_agent_manager()

    def __repr__(self) -> str:
        return (
            f"<VirtualAgent {self.name!r} scene={self.scene!r} "
            f"model={self.model!r} conv={self.conversation_id!r}>"
        )
