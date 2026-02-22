"""
MessagesApp v2.7 — Agent-integrated messaging for the phone scene.

Each DM thread maps to a ConversationManager conversation, giving us:
- Stateful chat (only the new message sent to LMStudio, not full history)
- Response_id tracking for conversation branching
- Rich messages: text, images (via generate_image tool), voice
- Typing indicators via streaming events
- Character-initiated messages (outbound from agent without user prompt)

Usage::

    app = MessagesApp(db=db, character_id="aria")
    app.ensure_thread("user")

    # User sends a message → agent replies
    result = app.send("Hey, what are you up to?")
    print(result.reply_text)          # Agent's text response
    print(result.image_url)           # Image if agent sent one
    print(result.mood)                # Detected mood tag

    # Get conversation history
    history = app.get_history(limit=20)
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MessageEntry:
    """A single message in a thread."""
    id: str = ""
    role: str = ""             # "user" | "assistant" | "system"
    content: str = ""
    timestamp: str = ""
    read: bool = False
    # Rich content
    image_url: str = ""        # Path to generated image
    voice_url: str = ""        # Path to voice message
    mood: str = ""             # Detected mood from response
    actions: List[str] = field(default_factory=list)
    # Metadata
    response_id: str = ""      # LMStudio response_id for branching
    tool_calls: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "read": self.read,
        }
        if self.image_url:
            d["image_url"] = self.image_url
        if self.voice_url:
            d["voice_url"] = self.voice_url
        if self.mood:
            d["mood"] = self.mood
        if self.actions:
            d["actions"] = self.actions
        if self.response_id:
            d["response_id"] = self.response_id
        return d


@dataclass
class SendResult:
    """Result from sending a message (user → agent reply)."""
    user_message: MessageEntry
    reply: MessageEntry
    reply_text: str = ""
    image_url: str = ""
    mood: str = ""
    response_id: str = ""
    latency_ms: float = 0.0


class MessagesApp:
    """
    Agent-integrated messaging — each thread backed by ConversationManager.

    Parameters
    ----------
    db : Database handle for persistent storage.
    character_id : The character this app instance is for.
    rag : Optional RAG instance for memory search.
    governor : Optional AgentGovernor for governed replies.
    agent_manager : Optional VirtualAgentManager (resolved lazily if None).
    """

    def __init__(
        self,
        db,
        character_id: str,
        rag=None,
        governor=None,
        agent_manager=None,
    ) -> None:
        self.db = db
        self.character_id = character_id
        self.rag = rag
        self._governor = governor
        self._agent_manager = agent_manager
        # Thread tracking: contact_id → conversation_id
        self._threads: Dict[str, str] = {}
        self._current_thread: Optional[str] = None

    # ── Thread management ───────────────────────────────────────────

    def ensure_thread(self, contact_id: str = "user") -> str:
        """
        Get or create a conversation thread for a contact.
        Returns the conversation_id.
        """
        if contact_id in self._threads:
            return self._threads[contact_id]

        conv_id = f"phone_{self.character_id}_{contact_id}"
        self._threads[contact_id] = conv_id
        self._current_thread = contact_id

        # Create ConversationManager conversation if needed
        try:
            from engine.lmstudio.conversation import get_conversation_manager
            cm = get_conversation_manager()
            if cm.get(conv_id) is None:
                cm.create(conv_id, system="", model=None)
        except Exception as exc:
            logger.debug("ConversationManager thread create: %s", exc)

        return conv_id

    def switch_thread(self, contact_id: str) -> str:
        """Switch active thread."""
        self._current_thread = contact_id
        return self.ensure_thread(contact_id)

    @property
    def active_conversation_id(self) -> Optional[str]:
        if self._current_thread:
            return self._threads.get(self._current_thread)
        return None

    # ── Send / receive ──────────────────────────────────────────────

    def send(
        self,
        content: str,
        *,
        contact_id: str = "user",
        use_governor: bool = True,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> SendResult:
        """
        Send a user message and get the agent's reply.

        Routes through AgentGovernor if available (interceptor pipeline
        for personality, rules, mood injection). Falls back to
        VirtualAgentManager direct call.

        Args:
            content:      User message text.
            contact_id:   Thread contact (default: "user").
            use_governor: Whether to use the governor pipeline.
            on_delta:     Optional streaming callback for UI.

        Returns:
            SendResult with user message, agent reply, and metadata.
        """
        t0 = time.perf_counter()
        conv_id = self.ensure_thread(contact_id)

        # Record user message
        user_msg = MessageEntry(
            id=str(uuid.uuid4()),
            role="user",
            content=content,
            timestamp=datetime.now().isoformat(),
            read=True,
        )
        self._persist_message(conv_id, user_msg)

        # Get agent reply
        reply_text = ""
        response_id = ""
        mood = ""
        image_url = ""
        tool_calls = []

        try:
            if use_governor and self._governor:
                # Governor path: full interceptor pipeline
                reply_text = self._governor.reply(
                    content,
                    chain_id=conv_id,
                )
                # Extract metadata from governor's last context if available
                # (governor populates ctx["mood_tags"] etc. in v2.7)
            else:
                # Direct manager path with streaming
                reply_text, mood, image_url, response_id, tool_calls = (
                    self._send_via_manager(content, conv_id, on_delta=on_delta)
                )
        except Exception as exc:
            logger.error("MessagesApp send failed: %s", exc)
            reply_text = ""

        # Record agent reply
        reply_msg = MessageEntry(
            id=str(uuid.uuid4()),
            role="assistant",
            content=reply_text,
            timestamp=datetime.now().isoformat(),
            read=False,
            image_url=image_url,
            mood=mood,
            response_id=response_id,
            tool_calls=tool_calls,
        )
        self._persist_message(conv_id, reply_msg)

        latency = (time.perf_counter() - t0) * 1000
        return SendResult(
            user_message=user_msg,
            reply=reply_msg,
            reply_text=reply_text,
            image_url=image_url,
            mood=mood,
            response_id=response_id,
            latency_ms=latency,
        )

    def _send_via_manager(
        self,
        content: str,
        conv_id: str,
        *,
        on_delta=None,
    ):
        """Send via VirtualAgentManager with stream processing."""
        from engine.agents.virtual_agent_manager import get_virtual_agent_manager
        from engine.agents.virtual_agent import InferenceRequest
        mgr = self._agent_manager or get_virtual_agent_manager()

        request = InferenceRequest(
            agent_id=self.character_id,
            messages=[{"role": "user", "content": content}],
            conversation_id=conv_id,
            stream=True,
            priority=5,
            metadata={"type": "message", "scene": "phone"},
        )

        result = mgr.infer_processed(request, on_delta=on_delta)
        return (
            result.clean_text,
            result.primary_mood,
            "",  # image_url from tool calls handled below
            result.response_id,
            [{"name": tc.name, "output": tc.output} for tc in result.tool_calls],
        )

    def receive_unsolicited(
        self,
        prompt_hint: str = "",
        *,
        contact_id: str = "user",
    ) -> Optional[MessageEntry]:
        """
        Character initiates a message without user prompt.

        Uses store=False one-shot query to generate the message,
        then stores it in the thread.

        Args:
            prompt_hint: Context hint for what the character might say.
            contact_id:  Thread contact.

        Returns:
            The generated MessageEntry, or None on failure.
        """
        conv_id = self.ensure_thread(contact_id)

        try:
            from engine.agents.scene_agent import get_scene_agent
            agent = get_scene_agent()
            task = (
                f"You are {self.character_id}. Write a short casual text message "
                f"to send unprompted. {prompt_hint or 'Be natural and in-character.'}"
                f"\nReply with ONLY the message text."
            )
            text = agent.run(task, max_tokens=200)
            if not text:
                return None

            msg = MessageEntry(
                id=str(uuid.uuid4()),
                role="assistant",
                content=text,
                timestamp=datetime.now().isoformat(),
                read=False,
            )
            self._persist_message(conv_id, msg)
            return msg

        except Exception as exc:
            logger.error("Unsolicited message failed: %s", exc)
            return None

    # ── History ─────────────────────────────────────────────────────

    def get_history(
        self,
        contact_id: str = "user",
        limit: int = 50,
    ) -> List[Dict]:
        """Get recent messages for a thread."""
        conv_id = self._threads.get(contact_id)
        if not conv_id:
            return []
        try:
            conv = self.db.get_conversation(conv_id)
            if conv and conv.get("messages"):
                return conv["messages"][-limit:]
        except Exception:
            pass
        return []

    def get_unread_count(self, contact_id: str = "user") -> int:
        """Count unread messages in a thread."""
        history = self.get_history(contact_id)
        return sum(
            1 for msg in history
            if msg.get("role") == "assistant" and not msg.get("read", False)
        )

    def mark_read(self, message_id: str, contact_id: str = "user") -> bool:
        """Mark a specific message as read."""
        conv_id = self._threads.get(contact_id)
        if not conv_id:
            return False
        try:
            conv = self.db.get_conversation(conv_id)
            if conv:
                for msg in conv.get("messages", []):
                    if msg.get("id") == message_id:
                        msg["read"] = True
                self.db.update_conversation(conv_id, conv["messages"])
                return True
        except Exception:
            pass
        return False

    def mark_all_read(self, contact_id: str = "user") -> int:
        """Mark all messages as read. Returns count marked."""
        conv_id = self._threads.get(contact_id)
        if not conv_id:
            return 0
        try:
            conv = self.db.get_conversation(conv_id)
            if not conv:
                return 0
            count = 0
            for msg in conv.get("messages", []):
                if not msg.get("read", False):
                    msg["read"] = True
                    count += 1
            if count:
                self.db.update_conversation(conv_id, conv["messages"])
            return count
        except Exception:
            return 0

    # ── Persistence ─────────────────────────────────────────────────

    def _persist_message(self, conv_id: str, msg: MessageEntry) -> None:
        """Persist a message to the database."""
        try:
            conv = self.db.get_conversation(conv_id)
            if conv:
                messages = conv.get("messages", [])
                messages.append(msg.to_dict())
                self.db.update_conversation(conv_id, messages)
            else:
                self.db.create_conversation(
                    self.character_id,
                    conv_id,
                    messages=[msg.to_dict()],
                )
        except Exception as exc:
            logger.debug("Message persist failed: %s", exc)

        # Log interaction
        try:
            self.db.log_interaction(
                "text_message",
                self.character_id,
                msg.content,
                chain_id=conv_id,
                metadata={
                    "sender": msg.role,
                    "mood": msg.mood,
                    "has_image": bool(msg.image_url),
                },
            )
        except Exception:
            pass
