"""Player-to-player messaging — direct messages between connected players.

Provides threaded conversations, read/unread tracking, and message
history with pagination. Integrates with SessionManager for player
identity resolution.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A single player-to-player message.

    Attributes:
        message_id: Unique message identifier.
        sender_id: Player id of the sender.
        receiver_id: Player id of the receiver.
        content: Message text content.
        timestamp: Unix timestamp when sent.
        read: Whether the receiver has read this message.
        thread_id: Conversation thread identifier (sorted sender+receiver pair).
    """
    message_id: str
    sender_id: str
    receiver_id: str
    content: str
    timestamp: float = field(default_factory=time.time)
    read: bool = False
    thread_id: str = ""

    def __post_init__(self) -> None:
        if not self.thread_id:
            self.thread_id = self._make_thread_id(self.sender_id, self.receiver_id)

    @staticmethod
    def _make_thread_id(a: str, b: str) -> str:
        """Create a deterministic thread id from two player ids."""
        return ":".join(sorted([a, b]))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "content": self.content,
            "timestamp": self.timestamp,
            "read": self.read,
            "thread_id": self.thread_id,
        }


class MessageStore:
    """Thread-safe message storage with conversation threading.

    Messages are organized into threads (one thread per unique sender-receiver
    pair). Supports read/unread tracking, pagination, and conversation queries.
    """

    def __init__(self, max_messages_per_thread: int = 500) -> None:
        """Initialize message store.

        Args:
            max_messages_per_thread: Max messages retained per conversation thread.
        """
        self._lock = threading.RLock()
        self._threads: Dict[str, List[Message]] = {}
        self._max_per_thread = max_messages_per_thread
        self._total_sent = 0
        logger.info("MessageStore initialized (cap=%d/thread)", max_messages_per_thread)

    def send(self, sender_id: str, receiver_id: str, content: str) -> Message:
        """Send a message from one player to another.

        Args:
            sender_id: Sending player's id.
            receiver_id: Receiving player's id.
            content: Message text.

        Returns:
            The created Message object.
        """
        msg = Message(
            message_id=str(uuid.uuid4()),
            sender_id=sender_id,
            receiver_id=receiver_id,
            content=content,
        )

        with self._lock:
            thread = self._threads.setdefault(msg.thread_id, [])
            thread.append(msg)
            if len(thread) > self._max_per_thread:
                self._threads[msg.thread_id] = thread[-self._max_per_thread:]
            self._total_sent += 1

        logger.debug("Message %s → %s: %s", sender_id, receiver_id,
                     content[:50])
        return msg

    def get_thread(self, player_a: str, player_b: str,
                   limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Get conversation history between two players.

        Args:
            player_a: First player id.
            player_b: Second player id.
            limit: Max messages to return.
            offset: Number of messages to skip from the end.

        Returns:
            List of message dicts, newest last.
        """
        thread_id = Message._make_thread_id(player_a, player_b)
        with self._lock:
            msgs = self._threads.get(thread_id, [])
            if offset > 0:
                msgs = msgs[:-offset] if offset < len(msgs) else []
            return [m.to_dict() for m in msgs[-limit:]]

    def get_unread(self, player_id: str) -> List[Dict[str, Any]]:
        """Get all unread messages for a player.

        Args:
            player_id: Receiving player.

        Returns:
            List of unread message dicts.
        """
        result: List[Dict[str, Any]] = []
        with self._lock:
            for thread in self._threads.values():
                for msg in thread:
                    if msg.receiver_id == player_id and not msg.read:
                        result.append(msg.to_dict())
        return result

    def unread_count(self, player_id: str) -> int:
        """Count unread messages for a player."""
        count = 0
        with self._lock:
            for thread in self._threads.values():
                for msg in thread:
                    if msg.receiver_id == player_id and not msg.read:
                        count += 1
        return count

    def mark_read(self, player_id: str, thread_partner: Optional[str] = None) -> int:
        """Mark messages as read.

        Args:
            player_id: The receiving player.
            thread_partner: If provided, only mark messages in this conversation.
                           If None, mark all unread messages for this player.

        Returns:
            Number of messages marked as read.
        """
        marked = 0
        with self._lock:
            if thread_partner:
                thread_id = Message._make_thread_id(player_id, thread_partner)
                for msg in self._threads.get(thread_id, []):
                    if msg.receiver_id == player_id and not msg.read:
                        msg.read = True
                        marked += 1
            else:
                for thread in self._threads.values():
                    for msg in thread:
                        if msg.receiver_id == player_id and not msg.read:
                            msg.read = True
                            marked += 1
        return marked

    def get_conversations(self, player_id: str) -> List[Dict[str, Any]]:
        """Get all conversations a player is part of.

        Returns a summary of each conversation with the last message,
        unread count, and partner player id.

        Args:
            player_id: Player to get conversations for.

        Returns:
            List of conversation summary dicts.
        """
        conversations: List[Dict[str, Any]] = []
        with self._lock:
            for thread_id, msgs in self._threads.items():
                parts = thread_id.split(":")
                if player_id not in parts:
                    continue
                partner = parts[0] if parts[1] == player_id else parts[1]
                unread = sum(1 for m in msgs
                            if m.receiver_id == player_id and not m.read)
                last_msg = msgs[-1] if msgs else None
                conversations.append({
                    "thread_id": thread_id,
                    "partner_id": partner,
                    "total_messages": len(msgs),
                    "unread_count": unread,
                    "last_message": last_msg.to_dict() if last_msg else None,
                    "last_activity": last_msg.timestamp if last_msg else 0,
                })

        conversations.sort(key=lambda c: c["last_activity"], reverse=True)
        return conversations

    def delete_thread(self, player_a: str, player_b: str) -> bool:
        """Delete an entire conversation thread.

        Args:
            player_a: First player.
            player_b: Second player.

        Returns:
            True if thread existed and was deleted.
        """
        thread_id = Message._make_thread_id(player_a, player_b)
        with self._lock:
            return self._threads.pop(thread_id, None) is not None

    def get_stats(self) -> Dict[str, Any]:
        """Get message store statistics."""
        with self._lock:
            total_msgs = sum(len(t) for t in self._threads.values())
            return {
                "total_threads": len(self._threads),
                "total_messages": total_msgs,
                "total_sent": self._total_sent,
                "max_per_thread": self._max_per_thread,
            }

    def reset(self) -> None:
        """Clear all messages."""
        with self._lock:
            self._threads.clear()
            self._total_sent = 0
        logger.info("MessageStore reset")


# ──── Singleton ────

_MESSAGE_STORE: Optional[MessageStore] = None
_ms_lock = threading.Lock()


def get_message_store() -> MessageStore:
    """Get or create the global MessageStore singleton."""
    global _MESSAGE_STORE
    if _MESSAGE_STORE is None:
        with _ms_lock:
            if _MESSAGE_STORE is None:
                _MESSAGE_STORE = MessageStore()
    return _MESSAGE_STORE


def reset_message_store() -> None:
    """Reset the global MessageStore singleton."""
    global _MESSAGE_STORE
    with _ms_lock:
        if _MESSAGE_STORE is not None:
            _MESSAGE_STORE.reset()
        _MESSAGE_STORE = None
