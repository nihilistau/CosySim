"""
CharacterAgent — LMStudio-backed conversational agent with full CosySim context

The ``CharacterAgent`` is the primary interface between a character and the LLM.
It wires together:

* **Character persona** — system prompt built from name, traits, backstory, mood
* **RAG memory** — top-k memories from ChromaDB injected into the system prompt
* **Skills** — optional tool packs passed to ``llm.act()``
* **EventChain** — every LLM request/response/tool-call logged in the DB
* **Cancellation** — thread-safe ``cancel()`` that calls ``prediction_stream.cancel()``

Usage::

    from engine.agents import CharacterAgent
    from content.simulation.database.db import Database
    from content.simulation.character_system.character import Character

    db   = Database()
    char = Character.load("char-uuid", db=db)

    agent = CharacterAgent(char, db=db)
    reply = agent.reply("Hey, what are you up to?")
    print(reply)

Skill packs are opt-in — pass ``skill_packs=["comfyui", "memory"]`` to the
constructor to equip the agent with image generation and memory search tools.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

try:
    from engine.logging import timed
except ImportError:
    def timed(name):
        def decorator(fn):
            return fn
        return decorator

logger = logging.getLogger(__name__)


class CharacterAgent:
    """
    Conversational agent that wraps a ``Character`` object with LMStudio SDK calls.

    Parameters
    ----------
    character : Character
        The character whose persona drives the system prompt.
    db : Database
        Database instance for RAG queries and event logging.
    config : ConfigManager, optional
        Config override.  Uses global config if None.
    skill_packs : list[str], optional
        Names of skill packs to equip (e.g. ``["comfyui", "memory"]``).
        Empty list (default) = text-only LLM with no tools.
    model : str, optional
        LMStudio model key to use.  Defaults to the currently loaded model.
    max_context_memories : int
        Number of RAG memories to inject into the prompt (default 5).
    """

    def __init__(
        self,
        character,
        *,
        db=None,
        config=None,
        skill_packs: Optional[List[str]] = None,
        model:       Optional[str]       = None,
        max_context_memories: int        = 5,
        use_mcp:     bool                = False,
        mcp_servers: Optional[List[Dict]] = None,
    ) -> None:
        self.character            = character
        self.db                   = db
        self.skill_packs          = skill_packs or []
        self.model                = model
        self.max_context_memories = max_context_memories
        self.use_mcp              = use_mcp
        self.mcp_servers          = mcp_servers or []

        if config is None:
            from engine.config import get_config
            config = get_config()
        self.config = config

        # Enable MCP if configured globally
        if not self.use_mcp:
            self.use_mcp = bool(config.get("lmstudio.mcp_enabled", False))

        # Cancellation support
        self._cancel_event: threading.Event          = threading.Event()
        self._stream:       Any                      = None   # active prediction stream
        self._lock:         threading.Lock           = threading.Lock()

        # RAG memory (lazy init)
        self._rag                                    = None

    # ──────────────────────────────────────────────────── public API ──

    def reply(
        self,
        user_message: str,
        *,
        chain_id:    Optional[str] = None,
        history:     Optional[List[Dict]] = None,
        use_tools:   bool          = True,
    ) -> str:
        """
        Generate a character reply to ``user_message``.

        Steps:
          1. Query RAG for relevant memories.
          2. Build character system prompt.
          3. Log ``llm_request`` event.
          4. Call ``llm.act(chat, tools)`` (with tools) or ``llm.respond(chat)``
             (text only).
          5. Log ``llm_response`` or ``llm_cancelled`` event.
          6. Return reply text.

        Args:
            user_message: The user's message text.
            chain_id:     Existing EventChain ID to append to (creates new if None).
            history:      Optional prior turns ``[{"role": ..., "content": ...}]``.
            use_tools:    Whether to include skill tools.  Set False for
                          lightweight text-only completions.

        Returns:
            Reply text string (empty string on cancellation or error).
        """
        self._cancel_event.clear()

        # ── 1. EventChain setup ──────────────────────────────────────
        ec = self._get_event_chain()
        if chain_id is None and ec:
            try:
                chain_id = ec.start_chain(
                    scene_id=f"agent_{self.character.name.lower().replace(' ', '_')}",
                    character_id=self.character.id,
                    summary=f"User: {user_message[:80]}",
                )
            except Exception:
                logger.debug("EventChain start_chain failed", exc_info=True)
                chain_id = None
        memories: List[str] = []
        try:
            memories = self._search_memories(user_message)
            if ec and chain_id and memories:
                ec.log(
                    "rag_result",
                    actor="rag",
                    payload={"count": len(memories)},
                    summary=f"Retrieved {len(memories)} memories",
                    chain_id=chain_id,
                    character_id=self.character.id,
                )
        except Exception as exc:
            logger.debug("RAG query failed: %s", exc)

        # ── 3. Build chat ────────────────────────────────────────────
        system_prompt = self._build_system_prompt(memories)
        try:
            import lmstudio as lms
            chat = lms.Chat(system_prompt)
        except ImportError as exc:
            logger.error("lmstudio package not installed: %s", exc)
            return ""

        # Inject prior history
        for turn in (history or []):
            role    = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                chat.add_user_message(content)
            elif role == "assistant":
                chat.add_assistant_response(content)

        chat.add_user_message(user_message)

        # ── 4. Log request event ─────────────────────────────────────
        if ec and chain_id:
            try:
                ec.log(
                    "llm_request",
                    actor=self.character.name,
                    payload={"model": self.model, "use_tools": use_tools},
                    summary=f"Requesting LLM reply (tools={use_tools})",
                    chain_id=chain_id,
                    character_id=self.character.id,
                )
            except Exception:
                logger.debug("EventChain log llm_request failed", exc_info=True)

        # ── 5. LLM call ──────────────────────────────────────────────
        reply_text = ""
        try:
            if self.use_mcp:
                # REST API path with MCP integrations
                reply_text = self._reply_via_rest(
                    system_prompt, user_message, history, chain_id=chain_id
                )
            else:
                # SDK path (original)
                llm_handle = self._get_llm()
                if use_tools and self.skill_packs:
                    tools = self._get_tools()
                    reply_text = self._act(llm_handle, chat, tools, chain_id=chain_id)
                else:
                    reply_text = self._complete(llm_handle, chat)

        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            if ec and chain_id:
                try:
                    ec.log_error(str(exc), chain_id=chain_id, character_id=self.character.id)
                except Exception:
                    logger.debug("EventChain log_error failed", exc_info=True)
            return ""

        # ── 6. Log response / cancellation ───────────────────────────
        if ec and chain_id:
            try:
                if self._cancel_event.is_set():
                    ec.log(
                        "llm_cancelled",
                        actor=self.character.name,
                        summary="LLM response cancelled by user",
                        chain_id=chain_id,
                        character_id=self.character.id,
                    )
                else:
                    ec.log(
                        "llm_response",
                        actor=self.character.name,
                        summary=reply_text[:120],
                        chain_id=chain_id,
                        character_id=self.character.id,
                    )
            except Exception:
                logger.debug("EventChain log response failed", exc_info=True)

        return reply_text

    def cancel(self) -> None:
        """
        Cancel the currently active LLM prediction.

        Sets the cancel event and calls ``prediction_stream.cancel()`` if
        a live stream is present.  Safe to call from any thread.
        """
        self._cancel_event.set()
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.cancel()
                except Exception:
                    logger.debug("Stream cancel failed", exc_info=True)

    # ─────────────────────────────────────────────────── internals ──

    def _get_llm(self):
        """Return an lmstudio LLM handle for this agent's model."""
        import lmstudio as lms
        if self.model:
            return lms.llm(self.model)
        return lms.llm()

    @timed("llm.complete")
    def _complete(self, llm_handle, chat) -> str:
        """Simple text completion (no tools)."""
        stream = llm_handle.respond(chat)
        with self._lock:
            self._stream = stream
        chunks = []
        for chunk in stream:
            if self._cancel_event.is_set():
                break
            text = chunk if isinstance(chunk, str) else getattr(chunk, "text", str(chunk))
            chunks.append(text)
        with self._lock:
            self._stream = None
        return "".join(chunks).strip()

    @timed("llm.act")
    def _act(self, llm_handle, chat, tools: List, *, chain_id: Optional[str]) -> str:
        """Agentic loop completion with skill tools."""
        from engine.skills.chain_context import set_chain_context, clear_chain_context
        ec = self._get_event_chain()

        # Set thread-local chain context so skills can log events
        set_chain_context(
            chain_id=chain_id,
            scene_id=getattr(self, "scene_id", "unknown"),
            character_id=self.character.id,
        )

        def on_tool_call(tool_name: str, args: Dict, result: Any) -> None:
            """Callback: log each tool invocation to EventChain."""
            if ec and chain_id:
                try:
                    ec.log(
                        "tool_call",
                        actor=self.character.name,
                        payload={"tool": tool_name, "args": args},
                        summary=f"→ {tool_name}({args})",
                        chain_id=chain_id,
                        character_id=self.character.id,
                    )
                    ec.log(
                        "tool_result",
                        actor=tool_name,
                        payload={"result": str(result)[:500]},
                        summary=str(result)[:120],
                        chain_id=chain_id,
                        character_id=self.character.id,
                    )
                except Exception:
                    logger.debug("EventChain tool log failed", exc_info=True)

        # lmstudio.llm.act() is synchronous — it handles the loop internally.
        # The callback signature depends on the SDK version; we try the common form.
        result_text = ""
        try:
            prediction = llm_handle.act(
                chat,
                tools,
                on_tool_called=on_tool_call,
            )
            with self._lock:
                self._stream = prediction
            result_text = str(prediction).strip()
        except TypeError:
            # Older SDK may not support on_tool_called kwarg
            prediction  = llm_handle.act(chat, tools)
            with self._lock:
                self._stream = prediction
            result_text = str(prediction).strip()
        finally:
            clear_chain_context()
            with self._lock:
                self._stream = None
        return result_text

    @timed("llm.rest_mcp")
    def _reply_via_rest(
        self,
        system_prompt: str,
        user_message: str,
        history: Optional[List[Dict]],
        *,
        chain_id: Optional[str],
    ) -> str:
        """
        Reply using the REST v2 client with MCP integrations.

        Falls back to SDK path on connection failure.
        """
        from engine.lmstudio.client_v2 import get_lmstudio_client, MCP

        ec = self._get_event_chain()
        client = get_lmstudio_client()

        # Build messages array
        messages = [{"role": "system", "content": system_prompt}]
        for turn in (history or []):
            messages.append({
                "role": turn.get("role", "user"),
                "content": turn.get("content", ""),
            })
        messages.append({"role": "user", "content": user_message})

        # Build integrations list
        integrations = list(self.mcp_servers) if self.mcp_servers else []
        # Auto-add CosySim MCP server if configured
        cosysim_mcp_url = self.config.get("lmstudio.cosysim_mcp_url", "")
        if cosysim_mcp_url:
            integrations.append(MCP.ephemeral(cosysim_mcp_url))

        try:
            resp = client.chat(
                messages,
                model=self.model,
                integrations=integrations if integrations else None,
            )

            # Log token stats
            if ec and chain_id:
                try:
                    ec.log(
                        "mcp_tool_call" if integrations else "llm_response",
                        actor=self.character.name,
                        payload={
                            "input_tokens": resp.input_tokens,
                            "output_tokens": resp.output_tokens,
                            "latency_ms": resp.latency_ms,
                            "tokens_per_sec": resp.tokens_per_second,
                            "model": resp.model,
                            "mcp_servers": len(integrations),
                        },
                        summary=resp.content[:120],
                        chain_id=chain_id,
                        character_id=self.character.id,
                    )
                except Exception:
                    logger.debug("EventChain MCP log failed", exc_info=True)

            return resp.content

        except ConnectionError:
            logger.warning("REST client failed, falling back to SDK")
            llm_handle = self._get_llm()
            import lmstudio as lms
            chat = lms.Chat(system_prompt)
            for turn in (history or []):
                if turn.get("role") == "user":
                    chat.add_user_message(turn.get("content", ""))
                elif turn.get("role") == "assistant":
                    chat.add_assistant_response(turn.get("content", ""))
            chat.add_user_message(user_message)
            return self._complete(llm_handle, chat)

    def _build_system_prompt(self, memories: List[str]) -> str:
        """Build the full system prompt for the character."""
        char = self.character
        name = char.name

        # Trait description
        warmth     = getattr(char, "warmth",      0.5)
        formality  = getattr(char, "formality",   0.5)
        humor      = getattr(char, "humor",       0.5)
        flirt      = getattr(char, "flirtiness",  0.5)
        intel      = getattr(char, "intelligence",0.5)
        creativity = getattr(char, "creativity",  0.5)
        mood       = getattr(char, "mood",        "relaxed")

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

        # Backstory / description
        desc = getattr(char, "description", "") or ""
        if desc:
            parts.append(f"About you: {desc}")

        backstory = getattr(char, "backstory", "") or ""
        if backstory:
            parts.append(f"Backstory: {backstory}")

        # Custom LLM context injection from settings
        custom = self.config.get("llm.custom_context", "").strip()
        if custom:
            parts.append(custom)

        # RAG memories
        if memories:
            parts.append("\nRelevant memories:")
            for mem in memories[:self.max_context_memories]:
                parts.append(f"- {mem}")

        parts.append(
            "\nRespond naturally in-character. Keep replies concise unless detail is asked for."
        )
        return "\n".join(parts)

    def _search_memories(self, query: str) -> List[str]:
        """Query RAG for memories relevant to *query*."""
        if self._rag is None:
            try:
                from content.simulation.database.rag import RAGMemory
                self._rag = RAGMemory()
            except Exception:
                logger.debug("RAG init failed, memories disabled", exc_info=True)
                return []
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

    def _get_tools(self) -> List:
        """Retrieve skill callables for all configured packs."""
        from engine.skills import get_pack_tools
        tools = []
        for pack in self.skill_packs:
            tools.extend(get_pack_tools(pack))
        return tools

    def _get_event_chain(self):
        """Return the global EventChain instance, or None on import error."""
        try:
            from content.simulation.database.events import get_event_chain
            return get_event_chain()
        except Exception:
            logger.debug("EventChain unavailable")
            return None
