"""
ConversationManager — Client-side conversation state for LMStudio v1 stateful chats

LMStudio's native v1 API supports stateful conversations where the server
maintains KV cache and context via ``previous_response_id``.  This works
beautifully — until the model is unloaded (VRAM eviction, TTL, manual swap).

ConversationManager solves the three negatives of server-side state:

1. **State loss on unload** — we mirror every message client-side.  When
   the server loses state, we transparently replay the history.
2. **No edit/fork** — to edit history, we keep the canonical copy here,
   modify it, then start a fresh server thread with the altered messages.
3. **Single source of truth** — the governor, scenes, and overlay all
   read/write through this manager, so conversation state is consistent.

Architecture::

    ┌───────────────────────────────┐
    │     ConversationManager       │
    │  ┌─────────────────────────┐  │
    │  │ Conversation            │  │
    │  │  messages: List[Dict]   │  │
    │  │  response_id: str       │  │
    │  │  model: str             │  │
    │  └─────────────────────────┘  │
    │  ┌─────────────────────────┐  │
    │  │ Conversation ...        │  │
    │  └─────────────────────────┘  │
    └───────────────────────────────┘
              │
              ▼
    ┌───────────────────────────────┐
    │  LMSClient (v1 native only)  │
    │  /api/v1/chat                 │
    │  previous_response_id ────────┤─→ Server KV cache
    └───────────────────────────────┘

Usage::

    from engine.lmstudio.conversation import get_conversation_manager

    mgr = get_conversation_manager()

    # Start a new conversation
    conv = mgr.create("aria_phone", system="You are Aria...")

    # Send a message (returns LMSResponse)
    resp = conv.send("Hello!")
    resp2 = conv.send("What did I just say?")  # uses previous_response_id

    # Edit history (clears server state, replays modified history)
    conv.edit_message(1, "Actually, goodbye!")
    resp3 = conv.send("Continue from here")

    # Fork a conversation at a specific point
    forked = conv.fork(at_turn=2, new_id="aria_phone_alt")
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

    def send(
        self,
        user_message: str,
        *,
        integrations: Optional[List[Dict]] = None,
        response_format: Optional[Dict] = None,
    ) -> Any:
        """
        Send a message in this conversation.

        If the server has our state (``response_id`` valid), sends only the
        new message with ``previous_response_id``.  Otherwise, replays the
        full history.

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

            if self._server_synced and self.response_id:
                # Fast path: stateful — send only the new message
                resp = client.chat_stateful(
                    user_message,
                    previous_response_id=self.response_id,
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

    def fork(self, at_turn: Optional[int] = None, new_id: Optional[str] = None) -> "Conversation":
        """
        Fork this conversation into a new one.

        Args:
            at_turn: Fork after this many turns (None = copy everything).
            new_id: ID for the new conversation (auto-generated if None).

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

            # Fork always starts with no server state
            new_conv._server_synced = False
            new_conv.response_id = None
            return new_conv

    def invalidate(self) -> None:
        """Force full history replay on next send (e.g., model was unloaded)."""
        with self._lock:
            self._invalidate_server_state()

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
