"""
ConversationManager v2.7 — Client-side conversation state for LMStudio v1 stateful chats

LMStudio's native v1 API supports stateful conversations where the server
maintains KV cache and context via ``previous_response_id``.  Every response
returns a unique ``response_id`` starting with ``resp_``.

ConversationManager solves the three negatives of server-side state:

1. **State loss on unload** — we mirror every message client-side.  When
   the server loses state, we transparently replay the history.
2. **No edit/fork** — to edit history, we keep the canonical copy here,
   modify it, then start a fresh server thread with the altered messages.
3. **Conversation branching** — every ``response_id`` is recorded.  Fork
   at any historical turn and the new branch uses ``previous_response_id``
   from that point, leveraging LMStudio's native branching.
4. **Stateless queries** — ``send_stateless()`` sends ``store: false`` for
   one-off queries that don't affect the conversation.

Architecture::

    ┌───────────────────────────────┐
    │     ConversationManager       │
    │  ┌─────────────────────────┐  │
    │  │ Conversation            │  │
    │  │  messages: List[Dict]   │  │
    │  │  response_id: str       │  │
    │  │  _response_id_history   │  │
    │  │  model: str             │  │
    │  └─────────────────────────┘  │
    └───────────────────────────────┘
              │
              ▼
    ┌───────────────────────────────┐
    │  LMSClient (v1 native only)  │
    │  /api/v1/chat                 │
    │  previous_response_id ────────┤─→ Server KV cache
    │  store: true/false ───────────┤─→ Server state
    └───────────────────────────────┘

Usage::

    from engine.lmstudio.conversation import get_conversation_manager

    mgr = get_conversation_manager()

    # Start a new conversation
    conv = mgr.create("aria_phone", system="You are Aria...")

    # Send a message (returns LMSResponse with response_id)
    resp = conv.send("Hello!")
    resp2 = conv.send("What did I just say?")  # uses previous_response_id

    # Edit history (clears server state, replays modified history)
    conv.edit_message(1, "Actually, goodbye!")

    # Branch at turn 2 (uses recorded response_id for server-side branching)
    branch = conv.branch_at(2, new_id="aria_phone_alt")

    # Stateless one-off query (store: false, no state change)
    summary = conv.send_stateless("Summarise our conversation")
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConversationMessage:
    """A single message in a conversation."""
    role: str  # system, user, assistant, tool
    content: str
    timestamp: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.metadata.get("tool_calls"):
            d["tool_calls"] = self.metadata["tool_calls"]
        if self.role == "tool" and self.metadata.get("tool_call_id"):
            d["tool_call_id"] = self.metadata["tool_call_id"]
        return d


class Conversation:
    """
    A single stateful conversation thread.

    Mirrors server-side state client-side.  Uses ``previous_response_id``
    for efficient server-side context, but can transparently replay if
    the server loses state (model unload, restart, etc.).
    """

    def __init__(
        self,
        conversation_id: str,
        system: str = "",
        model: Optional[str] = None,
        config: Optional[Any] = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.system = system
        self.model = model
        self.config = config  # InferenceConfig

        self.messages: List[ConversationMessage] = []
        self.response_id: Optional[str] = None  # latest server response_id
        self._response_id_history: List[str] = []  # all response_ids for branching
        self._server_synced = False  # True = server has our context
        self._lock = threading.Lock()
        self.created_at = time.time()
        self.last_active = time.time()

        # Add system message if provided
        if system:
            self.messages.append(ConversationMessage(
                role="system", content=system, timestamp=time.time()
            ))

    @property
    def turn_count(self) -> int:
        """Number of user+assistant turns (excluding system)."""
        return sum(1 for m in self.messages if m.role in ("user", "assistant"))

    @property
    def is_synced(self) -> bool:
        """Whether the server has our conversation state."""
        return self._server_synced and self.response_id is not None

    def update_system_if_changed(self, new_system: str) -> bool:
        """Update system prompt only if it actually changed.

        Returns True if the system was updated (and server state invalidated).
        Prevents unnecessary replays when interceptors inject the same context.
        """
        import hashlib
        old_hash = hashlib.md5(self.system.encode()).hexdigest()
        new_hash = hashlib.md5(new_system.encode()).hexdigest()
        if old_hash != new_hash:
            self.system = new_system
            # Update the system message in our message list
            if self.messages and self.messages[0].role == "system":
                self.messages[0] = ConversationMessage(
                    role="system", content=new_system, timestamp=time.time()
                )
            else:
                self.messages.insert(0, ConversationMessage(
                    role="system", content=new_system, timestamp=time.time()
                ))
            self.invalidate()
            return True
        return False

    def send(
        self,
        user_message: str,
        *,
        integrations: Optional[List[Dict]] = None,
        response_format: Optional[Dict] = None,
        previous_response_id_override: Optional[str] = None,
    ) -> Any:
        """
        Send a message in this conversation.

        If the server has our state (``response_id`` valid), sends only the
        new message with ``previous_response_id``.  Otherwise, replays the
        full history.

        Args:
            previous_response_id_override: If provided, branch from this
                response_id instead of the current conversation head. Used
                for mood pivots and conversation repair.

        Returns:
            LMSResponse from the client.
        """
        from engine.lmstudio.lms_client import get_lms_client
        from engine.lmstudio.inference_config import InferenceConfig

        with self._lock:
            # Record user message
            self.messages.append(ConversationMessage(
                role="user", content=user_message, timestamp=time.time()
            ))

            client = get_lms_client()
            cfg = self.config or InferenceConfig()
            if self.model:
                cfg = InferenceConfig.merge(cfg, InferenceConfig(model=self.model))
            if integrations:
                cfg = InferenceConfig.merge(cfg, InferenceConfig(integrations=integrations))
            if response_format:
                cfg = InferenceConfig.merge(cfg, InferenceConfig(response_format=response_format))

            # Determine which response_id to use
            prev_rid = previous_response_id_override or self.response_id

            if (self._server_synced or previous_response_id_override) and prev_rid:
                # Fast path: stateful — send only the new message
                resp = client.chat_stateful(
                    user_message,
                    previous_response_id=prev_rid,
                    config=cfg,
                )
            else:
                # Full replay: send entire history
                resp = client.chat(
                    [m.to_dict() for m in self.messages],
                    config=cfg,
                )

            # Record assistant response
            self.messages.append(ConversationMessage(
                role="assistant",
                content=resp.content,
                timestamp=time.time(),
                metadata={"response_id": resp.response_id},
            ))

            # Update state tracking
            if resp.response_id:
                self.response_id = resp.response_id
                self._response_id_history.append(resp.response_id)
                self._server_synced = True
            self.last_active = time.time()

            return resp

    def add_system_message(self, content: str) -> None:
        """Inject a system/instruction message mid-conversation."""
        with self._lock:
            self.messages.append(ConversationMessage(
                role="system", content=content, timestamp=time.time()
            ))
            self._invalidate_server_state()

    def add_assistant_message(self, content: str) -> None:
        """Inject an assistant message (e.g., for seeding responses)."""
        with self._lock:
            self.messages.append(ConversationMessage(
                role="assistant", content=content, timestamp=time.time()
            ))
            self._invalidate_server_state()

    def edit_message(self, index: int, new_content: str) -> None:
        """
        Edit a message at a specific index.

        Invalidates server-side state — next ``send()`` will replay full history.
        Messages after the edit point are preserved (the model will re-evaluate
        them on the next call).
        """
        with self._lock:
            if 0 <= index < len(self.messages):
                self.messages[index].content = new_content
                self._invalidate_server_state()
            else:
                raise IndexError(f"Message index {index} out of range (0-{len(self.messages)-1})")

    def truncate(self, keep_turns: int) -> None:
        """
        Truncate conversation to keep only the last N user+assistant turns.

        Always preserves system messages at the start.
        """
        with self._lock:
            system_msgs = [m for m in self.messages if m.role == "system"
                           and self.messages.index(m) == 0]
            non_system = [m for m in self.messages if m not in system_msgs]

            # Count from the end
            kept: List[ConversationMessage] = []
            turns_seen = 0
            for msg in reversed(non_system):
                if msg.role in ("user", "assistant"):
                    turns_seen += 1
                if turns_seen <= keep_turns * 2:  # user+assistant pairs
                    kept.insert(0, msg)

            self.messages = system_msgs + kept
            self._invalidate_server_state()

    def fork(
        self,
        at_turn: Optional[int] = None,
        new_id: Optional[str] = None,
        branch_response_id: Optional[str] = None,
    ) -> "Conversation":
        """
        Fork this conversation into a new one.

        Args:
            at_turn: Fork after this many turns (None = copy everything).
            new_id: ID for the new conversation (auto-generated if None).
            branch_response_id: If provided, the new conversation starts with
                this ``response_id`` as its server state — enabling true
                conversation branching via LMStudio's ``previous_response_id``.

        Returns:
            New Conversation with copied messages up to the fork point.
        """
        with self._lock:
            fork_id = new_id or f"{self.conversation_id}_fork_{int(time.time())}"
            new_conv = Conversation(
                conversation_id=fork_id,
                system="",  # We'll copy messages directly
                model=self.model,
                config=copy.deepcopy(self.config),
            )

            if at_turn is None:
                new_conv.messages = [copy.deepcopy(m) for m in self.messages]
            else:
                # Keep system + first N turns
                system_msgs = [m for m in self.messages if m.role == "system"
                               and self.messages.index(m) == 0]
                non_system = [m for m in self.messages if m not in system_msgs]
                turn_count = 0
                kept = list(system_msgs)
                for msg in non_system:
                    if msg.role in ("user", "assistant"):
                        turn_count += 1
                    if turn_count <= at_turn:
                        kept.append(copy.deepcopy(msg))
                    else:
                        break
                new_conv.messages = kept

            # Use branch_response_id for true server-side branching
            if branch_response_id and branch_response_id.startswith("resp_"):
                new_conv.response_id = branch_response_id
                new_conv._server_synced = True
            else:
                new_conv._server_synced = False
                new_conv.response_id = None

            return new_conv

    def invalidate(self) -> None:
        """Force full history replay on next send (e.g., model was unloaded)."""
        with self._lock:
            self._invalidate_server_state()

    def branch_at(self, turn_index: int, new_id: Optional[str] = None) -> "Conversation":
        """
        Branch the conversation at a specific turn using the response_id recorded
        at that point.  This leverages LMStudio's native conversation branching.

        The new conversation can send messages using ``previous_response_id``
        from the branch point, avoiding full history replay.
        """
        with self._lock:
            # Find the response_id at the given turn
            turn_count = 0
            branch_rid: Optional[str] = None
            msg_index = 0
            for i, msg in enumerate(self.messages):
                if msg.role == "assistant":
                    turn_count += 1
                    rid = msg.metadata.get("response_id", "")
                    if turn_count == turn_index and rid:
                        branch_rid = rid
                        msg_index = i
                        break

        return self.fork(
            at_turn=turn_index,
            new_id=new_id,
            branch_response_id=branch_rid,
        )

    def send_stateless(
        self,
        user_message: str,
        *,
        system_override: Optional[str] = None,
    ) -> Any:
        """
        Send a one-off query using this conversation's config but without
        storing it on the server (``store: false``).  Does not modify
        this conversation's state or history.

        Useful for sidebar queries, summaries, or any fire-and-forget LLM call.
        """
        from engine.lmstudio.lms_client import get_lms_client
        from engine.lmstudio.inference_config import InferenceConfig

        client = get_lms_client()
        cfg = self.config or InferenceConfig()
        if self.model:
            cfg = InferenceConfig.merge(cfg, InferenceConfig(model=self.model))

        messages = []
        sys_content = system_override or self.system
        if sys_content:
            messages.append({"role": "system", "content": sys_content})
        messages.append({"role": "user", "content": user_message})

        return client.chat(messages, config=cfg, store=False)

    def get_history(self) -> List[Dict[str, Any]]:
        """Return conversation as a list of message dicts."""
        return [m.to_dict() for m in self.messages]

    def get_summary(self) -> Dict[str, Any]:
        """Return a summary dict for admin/overlay display."""
        return {
            "id": self.conversation_id,
            "turn_count": self.turn_count,
            "model": self.model,
            "synced": self.is_synced,
            "response_id": self.response_id,
            "response_id_count": len(self._response_id_history),
            "created_at": self.created_at,
            "last_active": self.last_active,
            "message_count": len(self.messages),
        }

    def _invalidate_server_state(self) -> None:
        """Mark server state as stale — next send will replay full history."""
        self._server_synced = False
        self.response_id = None


class ConversationManager:
    """
    Manages all active conversations across the system.

    Provides:
    - Create/get/delete conversations
    - Bulk invalidation when a model is unloaded
    - Conversation lookup by ID
    - Stats for overlay/admin
    """

    def __init__(self) -> None:
        self._conversations: Dict[str, Conversation] = {}
        self._lock = threading.Lock()
        self._on_invalidate: List[Callable] = []

    def create(
        self,
        conversation_id: str,
        *,
        system: str = "",
        model: Optional[str] = None,
        config: Optional[Any] = None,
    ) -> Conversation:
        """Create a new conversation (replaces any existing with same ID)."""
        with self._lock:
            conv = Conversation(
                conversation_id=conversation_id,
                system=system,
                model=model,
                config=config,
            )
            self._conversations[conversation_id] = conv
            logger.debug("Conversation created: %s", conversation_id)
            return conv

    def get(self, conversation_id: str) -> Optional[Conversation]:
        """Get a conversation by ID, or None."""
        return self._conversations.get(conversation_id)

    def get_or_create(
        self,
        conversation_id: str,
        *,
        system: str = "",
        model: Optional[str] = None,
        config: Optional[Any] = None,
    ) -> Conversation:
        """Get existing conversation or create a new one."""
        with self._lock:
            if conversation_id in self._conversations:
                return self._conversations[conversation_id]
        return self.create(conversation_id, system=system, model=model, config=config)

    def delete(self, conversation_id: str) -> bool:
        """Delete a conversation."""
        with self._lock:
            if conversation_id in self._conversations:
                del self._conversations[conversation_id]
                logger.debug("Conversation deleted: %s", conversation_id)
                return True
            return False

    def invalidate_all(self, reason: str = "model_unloaded") -> int:
        """
        Invalidate all conversations' server state.

        Called when a model is unloaded/swapped — server-side KV cache is gone.
        Next ``send()`` on any conversation will replay full history.

        Returns:
            Number of conversations invalidated.
        """
        with self._lock:
            count = 0
            for conv in self._conversations.values():
                if conv.is_synced:
                    conv.invalidate()
                    count += 1
            logger.info("Invalidated %d conversations (reason: %s)", count, reason)

            for callback in self._on_invalidate:
                try:
                    callback(reason, count)
                except Exception:
                    pass
            return count

    def invalidate_model(self, model_id: str) -> int:
        """Invalidate conversations using a specific model."""
        with self._lock:
            count = 0
            for conv in self._conversations.values():
                if conv.model == model_id or conv.model is None:
                    conv.invalidate()
                    count += 1
            logger.info("Invalidated %d conversations for model %s", count, model_id)
            return count

    def on_invalidate(self, callback: Callable) -> None:
        """Register a callback for invalidation events."""
        self._on_invalidate.append(callback)

    def list_conversations(self) -> List[Dict[str, Any]]:
        """Return summaries of all active conversations."""
        return [conv.get_summary() for conv in self._conversations.values()]

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate stats for overlay/admin."""
        convs = list(self._conversations.values())
        return {
            "total": len(convs),
            "synced": sum(1 for c in convs if c.is_synced),
            "total_messages": sum(len(c.messages) for c in convs),
            "total_turns": sum(c.turn_count for c in convs),
        }


# ── Singleton ───────────────────────────────────────────────────────────

_manager_instance: Optional[ConversationManager] = None


def get_conversation_manager() -> ConversationManager:
    """Return the global ConversationManager singleton."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ConversationManager()
    return _manager_instance
