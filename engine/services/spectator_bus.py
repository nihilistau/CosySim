"""
Spectator Bus — Real-time broadcast for danmaku/bullet comments
================================================================

Thread-safe singleton that receives agent replies, mood shifts, skill
activations, and system events, then broadcasts them to all subscribed
consumers (SocketIO emitters, overlay UIs, the Oracle dashboard, etc.).

Messages live in a 200-entry ring buffer so late-joining clients can
catch up via ``get_recent()``.

Version: v1.51.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-25] — Initial implementation: SpectatorMessage,
                            SpectatorBus singleton with subscribe/unsubscribe,
                            ring buffer, broadcast callback system

CONNECTS: SpectatorBroadcastInterceptor, Oracle scene, neon_base.html
CALLED BY: Interceptor pipeline (post_call), Oracle SocketIO forwarder
EMITS:     Callback invocations to all registered subscribers
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────
_RING_BUFFER_MAX = 200
_DEFAULT_TTL = 8.0

# ──── Mood → Color Mapping ───────────────────────────────────────────
# Used by the interceptor to pick a display color for danmaku text
MOOD_COLORS: Dict[str, str] = {
    "happy":       "#4ade80",   # green
    "excited":     "#facc15",   # yellow
    "angry":       "#ef4444",   # red
    "sad":         "#60a5fa",   # blue
    "flirty":      "#f472b6",   # pink
    "nervous":     "#a78bfa",   # purple
    "calm":        "#94a3b8",   # slate
    "playful":     "#fb923c",   # orange
    "mysterious":  "#c084fc",   # violet
    "confident":   "#22d3ee",   # cyan
    "embarrassed": "#fda4af",   # rose
    "neutral":     "#e2e8f0",   # light grey
}
DEFAULT_COLOR = "#e2e8f0"


# ──── Data Classes ────────────────────────────────────────────────────

@dataclass
class SpectatorMessage:
    """A single danmaku/bullet-comment message for the spectator overlay.

    Args:
        kind:      Message category — "chat", "action", "system", "mood", "skill".
        text:      Display text (truncated for overlay readability).
        agent_id:  Character/agent that produced this message.
        scene:     Scene where the message originated.
        color:     Hex color for display (derived from mood or category).
        timestamp: Unix timestamp of creation.
        ttl_secs:  How long the message should remain visible on screen.
    """
    kind: str                                          # "chat" | "action" | "system" | "mood" | "skill"
    text: str
    agent_id: str = ""
    scene: str = ""
    color: str = ""
    timestamp: float = field(default_factory=time.time)
    ttl_secs: float = _DEFAULT_TTL
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON transport (SocketIO / REST API)."""
        return {
            "id":        self.msg_id,
            "kind":      self.kind,
            "text":      self.text,
            "agent_id":  self.agent_id,
            "scene":     self.scene,
            "color":     self.color or DEFAULT_COLOR,
            "timestamp": round(self.timestamp, 3),
            "ttl_secs":  self.ttl_secs,
        }


# ──── SpectatorBus ────────────────────────────────────────────────────

class SpectatorBus:
    """Central, thread-safe broadcast hub for danmaku spectator messages.

    Subscribers register a callback via ``subscribe()`` and receive every
    broadcast message as a dict.  A 200-entry ring buffer allows late
    joiners to catch up via ``get_recent()``.

    CONNECTS: SpectatorBroadcastInterceptor (producer), Oracle scene (consumer)
    CALLED BY: get_spectator_bus() singleton accessor
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buffer: List[SpectatorMessage] = []
        self._subscribers: Dict[str, Callable[[Dict[str, Any]], None]] = {}

    # ── Publish ───────────────────────────────────────────────────────

    def broadcast(self, msg: SpectatorMessage) -> None:
        """Broadcast a spectator message to all subscribers and buffer it.

        Args:
            msg: The SpectatorMessage to broadcast.
        """
        msg_dict = msg.to_dict()
        with self._lock:
            self._buffer.append(msg)
            # Trim ring buffer when it exceeds max
            if len(self._buffer) > _RING_BUFFER_MAX:
                self._buffer = self._buffer[-(_RING_BUFFER_MAX // 2):]
            # Snapshot subscribers under lock to avoid mutation during iteration
            subs = list(self._subscribers.values())

        # Fire callbacks outside the lock to avoid deadlocks
        for callback in subs:
            try:
                callback(msg_dict)
            except Exception as exc:
                logger.debug(
                    "[SpectatorBus] Subscriber callback failed (operation=broadcast): %s",
                    exc,
                )

    # ── Subscribe / Unsubscribe ───────────────────────────────────────

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> str:
        """Register a callback to receive all future broadcasts.

        Args:
            callback: Function that accepts a message dict.

        Returns:
            A token string used to unsubscribe later.
        """
        token = str(uuid.uuid4())[:8]
        with self._lock:
            self._subscribers[token] = callback
        logger.debug("[SpectatorBus] Subscriber added (operation=subscribe, token=%s)", token)
        return token

    def unsubscribe(self, token: str) -> bool:
        """Remove a subscriber by its token.

        Args:
            token: The token returned by subscribe().

        Returns:
            True if the subscriber was found and removed.
        """
        with self._lock:
            removed = self._subscribers.pop(token, None) is not None
        if removed:
            logger.debug("[SpectatorBus] Subscriber removed (operation=unsubscribe, token=%s)", token)
        return removed

    # ── Read API ──────────────────────────────────────────────────────

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent messages from the ring buffer.

        Args:
            limit: Maximum number of messages to return (default 50).

        Returns:
            List of message dicts, newest last.
        """
        with self._lock:
            tail = self._buffer[-limit:] if limit < len(self._buffer) else list(self._buffer)
        return [m.to_dict() for m in tail]

    @property
    def subscriber_count(self) -> int:
        """Number of currently registered subscribers."""
        with self._lock:
            return len(self._subscribers)

    @property
    def buffer_size(self) -> int:
        """Number of messages currently in the ring buffer."""
        with self._lock:
            return len(self._buffer)

    def clear(self) -> None:
        """Clear the ring buffer (e.g. on server restart)."""
        with self._lock:
            self._buffer.clear()


# ──── Module-level Singleton ──────────────────────────────────────────

_bus: Optional[SpectatorBus] = None
_bus_lock = threading.Lock()


def get_spectator_bus() -> SpectatorBus:
    """Return the global SpectatorBus singleton (thread-safe lazy init).

    Returns:
        The shared SpectatorBus instance.
    """
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = SpectatorBus()
                logger.info("[SpectatorBus] Initialized (operation=init)")
    return _bus
