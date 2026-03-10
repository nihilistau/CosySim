"""Player presence tracking — who is where, online/away/busy.

Wraps SessionManager to provide scene-level occupancy queries,
status broadcasting, and automatic cleanup of disconnected players.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from engine.multiplayer.session_manager import (
    PlayerStatus,
    get_session_manager,
)

logger = logging.getLogger(__name__)


@dataclass
class PresenceEvent:
    """Record of a presence change.

    Attributes:
        player_id: Who changed.
        event_type: join_scene, leave_scene, status_change, connect, disconnect.
        scene: Relevant scene (if applicable).
        old_value: Previous state.
        new_value: New state.
        timestamp: When it happened.
    """
    player_id: str
    event_type: str
    scene: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "player_id": self.player_id,
            "event_type": self.event_type,
            "scene": self.scene,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "timestamp": self.timestamp,
        }


class PresenceTracker:
    """Tracks player presence across scenes.

    Integrates with SessionManager but adds:
    - Scene transition tracking (join/leave events)
    - Presence event history for UI updates
    - Scene occupancy queries optimized for frequent polling
    - Auto-cleanup via heartbeat timeout
    """

    def __init__(self, max_history: int = 200) -> None:
        """Initialize presence tracker.

        Args:
            max_history: Maximum presence events to retain.
        """
        self._lock = threading.RLock()
        self._history: List[PresenceEvent] = []
        self._max_history = max_history
        logger.info("PresenceTracker initialized (history_cap=%d)", max_history)

    def player_connected(self, player_id: str, display_name: str,
                         socket_sid: Optional[str] = None) -> Dict[str, Any]:
        """Register a new player connection.

        Creates a session and records a connect event.

        Args:
            player_id: Persistent player identifier.
            display_name: Display name.
            socket_sid: Optional Socket.IO session id.

        Returns:
            Session info dict.
        """
        sm = get_session_manager()
        session = sm.create_session(player_id, display_name, socket_sid)
        self._record(PresenceEvent(
            player_id=player_id,
            event_type="connect",
            new_value="online",
        ))
        logger.info("Player connected: %s (%s)", player_id, display_name)
        return session.to_dict()

    def player_disconnected(self, session_id: str) -> bool:
        """Handle player disconnect.

        Args:
            session_id: Session to disconnect.

        Returns:
            True if session was found and removed.
        """
        sm = get_session_manager()
        session = sm.get_session(session_id)
        if not session:
            return False

        self._record(PresenceEvent(
            player_id=session.player_id,
            event_type="disconnect",
            scene=session.connected_scene,
            old_value="online",
            new_value="offline",
        ))

        if session.connected_scene:
            self._record(PresenceEvent(
                player_id=session.player_id,
                event_type="leave_scene",
                scene=session.connected_scene,
            ))

        sm.destroy_session(session_id)
        logger.info("Player disconnected: %s", session.player_id)
        return True

    def player_joined_scene(self, session_id: str, scene_name: str) -> bool:
        """Record a player entering a scene.

        Args:
            session_id: Player session.
            scene_name: Scene they entered.

        Returns:
            True if session found and updated.
        """
        sm = get_session_manager()
        session = sm.get_session(session_id)
        if not session:
            return False

        old_scene = session.connected_scene

        if old_scene and old_scene != scene_name:
            self._record(PresenceEvent(
                player_id=session.player_id,
                event_type="leave_scene",
                scene=old_scene,
            ))

        sm.set_scene(session_id, scene_name)

        self._record(PresenceEvent(
            player_id=session.player_id,
            event_type="join_scene",
            scene=scene_name,
            old_value=old_scene,
            new_value=scene_name,
        ))

        logger.debug("Player %s joined scene %s", session.player_id, scene_name)
        return True

    def player_left_scene(self, session_id: str) -> bool:
        """Record a player leaving their current scene.

        Args:
            session_id: Player session.

        Returns:
            True if session found and scene was cleared.
        """
        sm = get_session_manager()
        session = sm.get_session(session_id)
        if not session or not session.connected_scene:
            return False

        old_scene = session.connected_scene
        self._record(PresenceEvent(
            player_id=session.player_id,
            event_type="leave_scene",
            scene=old_scene,
        ))

        sm.set_scene(session_id, "")
        return True

    def set_status(self, session_id: str, status: str) -> bool:
        """Change player status (online/away/busy).

        Args:
            session_id: Player session.
            status: New status string.

        Returns:
            True if session found and status updated.
        """
        try:
            new_status = PlayerStatus(status)
        except ValueError:
            logger.warning("Invalid status: %s", status)
            return False

        sm = get_session_manager()
        session = sm.get_session(session_id)
        if not session:
            return False

        old_status = session.status.value
        sm.set_status(session_id, new_status)

        self._record(PresenceEvent(
            player_id=session.player_id,
            event_type="status_change",
            scene=session.connected_scene,
            old_value=old_status,
            new_value=status,
        ))

        return True

    def get_scene_occupancy(self, scene_name: str) -> List[Dict[str, Any]]:
        """Get all players currently in a specific scene.

        Args:
            scene_name: Scene to query.

        Returns:
            List of player info dicts.
        """
        sm = get_session_manager()
        return sm.get_players_in_scene(scene_name)

    def get_player_scene(self, player_id: str) -> Optional[str]:
        """Get which scene a player is currently in.

        Args:
            player_id: Player to look up.

        Returns:
            Scene name or None.
        """
        sm = get_session_manager()
        session = sm.get_session_by_player(player_id)
        if session:
            return session.connected_scene
        return None

    def get_all_presence(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get scene → players mapping for all occupied scenes."""
        sm = get_session_manager()
        sessions = sm.list_sessions()
        by_scene: Dict[str, List[Dict[str, Any]]] = {}
        for s in sessions:
            scene = s.get("connected_scene")
            if scene:
                by_scene.setdefault(scene, []).append(s)
        return by_scene

    def get_online_count(self) -> int:
        """Count of currently online players."""
        sm = get_session_manager()
        return len(sm.list_online_players())

    def cleanup_stale(self) -> List[str]:
        """Remove stale sessions and record disconnect events.

        Returns:
            List of cleaned up session_ids.
        """
        sm = get_session_manager()
        stale_sessions = []
        with self._lock:
            now = time.time()
            for s_dict in sm.list_sessions():
                if now - s_dict["last_heartbeat"] > sm._heartbeat_timeout:
                    stale_sessions.append(s_dict)

        removed = []
        for s_dict in stale_sessions:
            sid = s_dict["session_id"]
            self._record(PresenceEvent(
                player_id=s_dict["player_id"],
                event_type="disconnect",
                scene=s_dict.get("connected_scene"),
                old_value=s_dict.get("status"),
                new_value="offline",
            ))
            sm.destroy_session(sid)
            removed.append(sid)

        return removed

    def get_recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent presence events.

        Args:
            limit: Max events to return.

        Returns:
            List of event dicts, newest first.
        """
        with self._lock:
            return [e.to_dict() for e in reversed(self._history[-limit:])]

    def get_stats(self) -> Dict[str, Any]:
        """Get presence tracker statistics."""
        sm = get_session_manager()
        all_presence = self.get_all_presence()
        return {
            "online_players": self.get_online_count(),
            "total_sessions": sm.session_count,
            "occupied_scenes": len(all_presence),
            "scene_occupancy": {s: len(p) for s, p in all_presence.items()},
            "recent_events": len(self._history),
        }

    def _record(self, event: PresenceEvent) -> None:
        """Record a presence event to history."""
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

    def reset(self) -> None:
        """Clear all presence data."""
        with self._lock:
            self._history.clear()
        get_session_manager().reset()
        logger.info("PresenceTracker reset")


# ──── Singleton ────

_PRESENCE: Optional[PresenceTracker] = None
_p_lock = threading.Lock()


def get_presence_tracker() -> PresenceTracker:
    """Get or create the global PresenceTracker singleton."""
    global _PRESENCE
    if _PRESENCE is None:
        with _p_lock:
            if _PRESENCE is None:
                _PRESENCE = PresenceTracker()
    return _PRESENCE


def reset_presence_tracker() -> None:
    """Reset the global PresenceTracker singleton."""
    global _PRESENCE
    with _p_lock:
        if _PRESENCE is not None:
            _PRESENCE.reset()
        _PRESENCE = None
