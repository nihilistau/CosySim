"""World Announcer — real-time city event feed for CosySim.

The ``WorldAnnouncer`` subscribes to the EventBus for ``world_event``,
``world.npc_action``, ``world.scene_ambient_shift``, and faction events
fired by :class:`~engine.world.world_sim.WorldSim`. It maintains an
in-memory ring buffer of the last 50 announcements, exposed via
:meth:`WorldAnnouncer.get_feed` and the ``/api/world/events`` REST endpoint.

Stations allow agents or players to mute categories:

- ``"npc"``       — NPC activity events
- ``"faction"``   — Faction shift events
- ``"world"``     — World/ambient events
- ``"hacker"``    — 0xGH0ST messages
- ``"economy"``   — Economy tick events
- ``"all"``       — Master mute switch

Usage::

    from engine.world.world_announcer import get_world_announcer
    feed = get_world_announcer().get_feed(limit=20)
    get_world_announcer().mute_station("npc")
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_RING_BUFFER_MAX: int = 50

# Station → EventBus event types it covers
_STATION_TYPES: Dict[str, List[str]] = {
    "npc":     ["world.npc_action", "npc_activity"],
    "faction": ["neoncity.faction_shift"],
    "world":   ["world.scene_ambient_shift", "world.world_event"],
    "hacker":  ["phone.hacker_message"],
    "economy": ["world.economy_tick"],
}


# ──── Announcement dataclass ─────────────────────────────────────────────────

@dataclass
class Announcement:
    """A single entry in the city-pulse feed."""

    id: str
    title: str
    body: str
    category: str           # one of the station keys above
    scene: str = ""
    actor: str = ""
    intensity: float = 1.0
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to JSON-safe dict."""
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "category": self.category,
            "scene": self.scene,
            "actor": self.actor,
            "intensity": self.intensity,
            "timestamp": self.timestamp,
        }


# ──── WorldAnnouncer ─────────────────────────────────────────────────────────


class WorldAnnouncer:
    """Singleton city-pulse feed.

    Subscribes to the :class:`~engine.events.event_bus.EventBus` on first
    :meth:`start` call.  Thread-safe ring buffer.
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._feed: List[Announcement] = []
        self._muted: Set[str] = set()
        self._subscribed: bool = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Subscribe to EventBus events.  Safe to call multiple times."""
        if self._subscribed:
            return
        try:
            from engine.events.event_bus import get_event_bus
            bus = get_event_bus()
            for station, event_types in _STATION_TYPES.items():
                for evt_type in event_types:
                    bus.subscribe(evt_type, self._on_event)
            self._subscribed = True
            logger.info("WorldAnnouncer subscribed to EventBus.")
        except Exception as exc:
            logger.warning("WorldAnnouncer could not subscribe to EventBus: %s", exc)

    def _on_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Handle an incoming bus event and add it to the feed."""
        try:
            announcement = self._build_announcement(event_type, payload)
            if announcement is None:
                return
            if self._is_muted(announcement.category):
                return
            self._push(announcement)
            self._emit_socket(announcement)
        except Exception as exc:
            logger.debug("WorldAnnouncer: event handling error: %s", exc)

    def _build_announcement(
        self, event_type: str, payload: Dict[str, Any]
    ) -> Optional[Announcement]:
        """Convert raw bus payload into an :class:`Announcement`."""
        import uuid as _uuid

        # Derive category from event type
        category = "world"
        for station, types in _STATION_TYPES.items():
            if event_type in types:
                category = station
                break

        title = payload.get("title") or event_type.replace(".", " ").replace("_", " ").title()
        body = (
            payload.get("description")
            or payload.get("message")
            or payload.get("action")
            or payload.get("desc")
            or ""
        )
        if not body:
            body = title

        return Announcement(
            id=str(_uuid.uuid4())[:8],
            title=title,
            body=body,
            category=category,
            scene=payload.get("scene", ""),
            actor=payload.get("actor") or payload.get("faction", ""),
            intensity=float(payload.get("intensity", 1.0)),
            timestamp=_now_str(),
        )

    def _push(self, announcement: Announcement) -> None:
        """Add announcement to ring buffer (oldest dropped at capacity)."""
        with self._lock:
            self._feed.append(announcement)
            if len(self._feed) > _RING_BUFFER_MAX:
                self._feed.pop(0)

    def _emit_socket(self, announcement: Announcement) -> None:
        """Best-effort Socket.IO broadcast of the new announcement."""
        try:
            from engine.mcp import get_framework
            get_framework().emit("city_pulse", announcement.to_dict())
        except Exception as e:
            logger.debug("[WorldAnnouncer] Socket.IO emit failed (operation=emit_socket): %s", e)

    # ── Public API ───────────────────────────────────────────────────────────

    def announce(
        self,
        title: str,
        body: str,
        category: str = "world",
        scene: str = "",
        actor: str = "",
        intensity: float = 1.0,
    ) -> Announcement:
        """Push a manual announcement into the feed.

        Args:
            title: Short headline.
            body: Detailed announcement text.
            category: One of ``npc|faction|world|hacker|economy``.
            scene: Related scene identifier.
            actor: Character or faction driving the event.
            intensity: 0.0–3.0 importance rating.

        Returns:
            The created :class:`Announcement`.
        """
        import uuid as _uuid

        ann = Announcement(
            id=str(_uuid.uuid4())[:8],
            title=title,
            body=body,
            category=category,
            scene=scene,
            actor=actor,
            intensity=intensity,
            timestamp=_now_str(),
        )
        if not self._is_muted(category):
            self._push(ann)
            self._emit_socket(ann)
        return ann

    def get_feed(self, limit: int = 50, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return recent announcements as a list of dicts, newest first.

        Args:
            limit: Maximum number of entries (default 50).
            category: Optional filter — ``npc|faction|world|hacker|economy``.

        Returns:
            List of announcement dicts, newest first.
        """
        with self._lock:
            snapshot = list(self._feed)
        if category:
            snapshot = [a for a in snapshot if a.category == category]
        return [a.to_dict() for a in reversed(snapshot)][:limit]

    def get_summary(self) -> str:
        """Return a one-paragraph narrative summary of the last 10 events.

        Returns:
            Human-readable summary string.
        """
        feed = self.get_feed(limit=10)
        if not feed:
            return "The city is quiet."
        lines = [f"[{a['category'].upper()}] {a['title']}: {a['body']}" for a in feed]
        return " | ".join(lines[:5])

    def mute_station(self, station: str) -> None:
        """Suppress announcements from *station*.

        Args:
            station: Station name or ``"all"`` to suppress everything.
        """
        with self._lock:
            self._muted.add(station)
        logger.debug("WorldAnnouncer: muted station '%s'", station)

    def unmute_station(self, station: str) -> None:
        """Re-enable announcements from *station*.

        Args:
            station: Station name or ``"all"``.
        """
        with self._lock:
            self._muted.discard(station)
        logger.debug("WorldAnnouncer: unmuted station '%s'", station)

    def get_muted_stations(self) -> List[str]:
        """Return list of currently muted station names."""
        with self._lock:
            return sorted(self._muted)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _is_muted(self, category: str) -> bool:
        with self._lock:
            return "all" in self._muted or category in self._muted


# ──── helpers ────────────────────────────────────────────────────────────────


def _now_str() -> str:
    """Return the current game time string if available, else wall-clock."""
    try:
        from engine.world.world_state import get_world_state
        ws = get_world_state()
        t = ws.get_time()
        return f"Day {t.game_day} {t.game_hour:02d}:00"
    except Exception as e:
        logger.debug("[WorldAnnouncer] Game time unavailable (operation=now_str): %s", e)
        return time.strftime("%H:%M:%S")


# ──── Singleton ───────────────────────────────────────────────────────────────

_ANNOUNCER: Optional[WorldAnnouncer] = None
_ANN_LOCK = threading.Lock()


def get_world_announcer() -> WorldAnnouncer:
    """Return the process-wide :class:`WorldAnnouncer` singleton.

    Starts EventBus subscriptions on first call.

    Returns:
        The singleton :class:`WorldAnnouncer` instance.
    """
    global _ANNOUNCER
    if _ANNOUNCER is None:
        with _ANN_LOCK:
            if _ANNOUNCER is None:
                _ANNOUNCER = WorldAnnouncer()
                _ANNOUNCER.start()
    return _ANNOUNCER


def reset_world_announcer() -> None:
    """Reset the singleton — intended for testing only."""
    global _ANNOUNCER
    with _ANN_LOCK:
        _ANNOUNCER = None
