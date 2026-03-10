"""Session management for multiplayer — per-player state isolation.

Provides PlayerSession, SessionManager, and PlayerSessionState.
Each connected player gets a session with isolated inventory, credits,
stats, and location tracking, while sharing the global world state
(market, factions, weather, NPCs).
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Data Structures ────


class PlayerStatus(str, Enum):
    """Online status for a player."""
    ONLINE = "online"
    AWAY = "away"
    BUSY = "busy"
    OFFLINE = "offline"


@dataclass
class PlayerSession:
    """Represents a connected player session.

    Attributes:
        session_id: Unique session identifier.
        player_id: Persistent player identifier (survives reconnects).
        display_name: Player-visible name.
        status: Current online status.
        connected_scene: Scene the player is currently viewing.
        socket_sid: Socket.IO session id for targeted emits.
        created_at: Unix timestamp of session creation.
        last_heartbeat: Unix timestamp of last activity.
    """
    session_id: str
    player_id: str
    display_name: str
    status: PlayerStatus = PlayerStatus.ONLINE
    connected_scene: Optional[str] = None
    socket_sid: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "session_id": self.session_id,
            "player_id": self.player_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "connected_scene": self.connected_scene,
            "socket_sid": self.socket_sid,
            "created_at": self.created_at,
            "last_heartbeat": self.last_heartbeat,
            "uptime_seconds": round(time.time() - self.created_at, 1),
        }


@dataclass
class PlayerSessionState:
    """Per-session player state — isolated from other players.

    Each player session tracks its own credits, reputation, inventory,
    skills, and stats independently. The shared world (market, factions,
    weather, NPCs) remains global.

    Attributes:
        player_id: Owning player.
        credits: Player credit balance.
        reputation: Player reputation score.
        heat: Wanted level (0-100).
        health: Player health (0-100).
        inventory: List of item dicts.
        skills: Skill name → XP mapping.
        faction_standings: Faction name → standing (-100 to 100).
        stats: Arbitrary stat counters (kills, heists_completed, etc.).
        active_location: Current district/scene.
    """
    player_id: str
    credits: int = 1000
    reputation: int = 0
    heat: int = 0
    health: int = 100
    inventory: List[Dict[str, Any]] = field(default_factory=list)
    skills: Dict[str, float] = field(default_factory=dict)
    faction_standings: Dict[str, float] = field(default_factory=lambda: {
        "OmniCorp": 0.0, "NeoTech": 0.0, "BlackMarket": 0.0,
        "Ghost_Net": 0.0, "SynthSec": 0.0, "DeepState": 0.0,
    })
    stats: Dict[str, int] = field(default_factory=lambda: {
        "kills": 0, "heists_completed": 0, "hacks_completed": 0,
        "items_bought": 0, "items_sold": 0, "messages_sent": 0,
        "scenes_visited": 0, "total_earned": 0, "total_spent": 0,
    })
    active_location: Optional[str] = None

    def earn_credits(self, amount: int, reason: str = "") -> int:
        """Add credits. Returns new balance."""
        self.credits += amount
        self.stats["total_earned"] = self.stats.get("total_earned", 0) + amount
        logger.debug("Player %s earned %d credits (%s)", self.player_id, amount, reason)
        return self.credits

    def spend_credits(self, amount: int, reason: str = "") -> bool:
        """Deduct credits if sufficient. Returns success."""
        if self.credits < amount:
            return False
        self.credits -= amount
        self.stats["total_spent"] = self.stats.get("total_spent", 0) + amount
        logger.debug("Player %s spent %d credits (%s)", self.player_id, amount, reason)
        return True

    def add_item(self, item: Dict[str, Any]) -> None:
        """Add an item to inventory."""
        self.inventory.append(item)

    def remove_item(self, item_id: str) -> bool:
        """Remove an item by id. Returns success."""
        for i, item in enumerate(self.inventory):
            if item.get("id") == item_id:
                self.inventory.pop(i)
                return True
        return False

    def adjust_reputation(self, delta: int, reason: str = "") -> int:
        """Adjust reputation. Returns new value."""
        self.reputation += delta
        return self.reputation

    def adjust_heat(self, delta: int) -> int:
        """Adjust heat (wanted level). Clamped 0-100."""
        self.heat = max(0, min(100, self.heat + delta))
        return self.heat

    def increment_stat(self, stat: str, amount: int = 1) -> int:
        """Increment a stat counter. Returns new value."""
        self.stats[stat] = self.stats.get(stat, 0) + amount
        return self.stats[stat]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "player_id": self.player_id,
            "credits": self.credits,
            "reputation": self.reputation,
            "heat": self.heat,
            "health": self.health,
            "inventory_count": len(self.inventory),
            "inventory": self.inventory,
            "skills": dict(self.skills),
            "faction_standings": dict(self.faction_standings),
            "stats": dict(self.stats),
            "active_location": self.active_location,
        }


# ──── Session Manager ────


class SessionManager:
    """Manages player sessions with thread-safe isolation.

    Each player connection creates a session with its own state.
    Sessions auto-expire after a configurable heartbeat timeout.
    The global world state (market, factions, etc.) remains shared.
    """

    def __init__(self, heartbeat_timeout: float = 120.0) -> None:
        """Initialize session manager.

        Args:
            heartbeat_timeout: Seconds of inactivity before auto-disconnect.
        """
        self._lock = threading.RLock()
        self._sessions: Dict[str, PlayerSession] = {}
        self._states: Dict[str, PlayerSessionState] = {}
        self._player_sessions: Dict[str, str] = {}  # player_id → session_id
        self._heartbeat_timeout = heartbeat_timeout
        logger.info("SessionManager initialized (timeout=%ss)", heartbeat_timeout)

    def create_session(
        self,
        player_id: str,
        display_name: str,
        socket_sid: Optional[str] = None,
    ) -> PlayerSession:
        """Create a new player session.

        If the player already has an active session, it is destroyed first
        (single-session-per-player policy).

        Args:
            player_id: Persistent player identifier.
            display_name: Display name for the player.
            socket_sid: Optional Socket.IO session id.

        Returns:
            The newly created PlayerSession.
        """
        with self._lock:
            if player_id in self._player_sessions:
                old_sid = self._player_sessions[player_id]
                logger.info("Player %s reconnecting — destroying old session %s",
                            player_id, old_sid)
                self._destroy_session_unlocked(old_sid)

            session_id = str(uuid.uuid4())
            session = PlayerSession(
                session_id=session_id,
                player_id=player_id,
                display_name=display_name,
                socket_sid=socket_sid,
            )
            state = PlayerSessionState(player_id=player_id)

            self._sessions[session_id] = session
            self._states[session_id] = state
            self._player_sessions[player_id] = session_id

            logger.info("Session created: %s for player %s (%s)",
                        session_id[:8], player_id, display_name)
            return session

    def destroy_session(self, session_id: str) -> bool:
        """Destroy a session and clean up.

        Args:
            session_id: Session to destroy.

        Returns:
            True if session existed and was destroyed.
        """
        with self._lock:
            return self._destroy_session_unlocked(session_id)

    def _destroy_session_unlocked(self, session_id: str) -> bool:
        """Internal destroy without acquiring lock."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return False
        self._states.pop(session_id, None)
        self._player_sessions.pop(session.player_id, None)
        logger.info("Session destroyed: %s (player %s)",
                    session_id[:8], session.player_id)
        return True

    def get_session(self, session_id: str) -> Optional[PlayerSession]:
        """Get session by session_id."""
        with self._lock:
            return self._sessions.get(session_id)

    def get_session_by_player(self, player_id: str) -> Optional[PlayerSession]:
        """Get session by player_id."""
        with self._lock:
            sid = self._player_sessions.get(player_id)
            if sid:
                return self._sessions.get(sid)
            return None

    def get_state(self, session_id: str) -> Optional[PlayerSessionState]:
        """Get player state for a session."""
        with self._lock:
            return self._states.get(session_id)

    def get_state_by_player(self, player_id: str) -> Optional[PlayerSessionState]:
        """Get player state by player_id."""
        with self._lock:
            sid = self._player_sessions.get(player_id)
            if sid:
                return self._states.get(sid)
            return None

    def heartbeat(self, session_id: str) -> bool:
        """Update heartbeat timestamp. Returns False if session not found."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            session.last_heartbeat = time.time()
            return True

    def set_scene(self, session_id: str, scene_name: str) -> bool:
        """Update the scene a player is currently in.

        Args:
            session_id: Player session.
            scene_name: Scene name to move to.

        Returns:
            True if session found and updated.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            state = self._states.get(session_id)
            if not session:
                return False
            old_scene = session.connected_scene
            session.connected_scene = scene_name
            if state:
                state.active_location = scene_name
                state.increment_stat("scenes_visited")
            logger.debug("Player %s moved: %s → %s",
                        session.player_id, old_scene, scene_name)
            return True

    def set_status(self, session_id: str, status: PlayerStatus) -> bool:
        """Update player online status."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            session.status = status
            return True

    def cleanup_stale(self) -> List[str]:
        """Remove sessions that haven't sent a heartbeat within timeout.

        Returns:
            List of destroyed session_ids.
        """
        now = time.time()
        stale: List[str] = []
        with self._lock:
            for sid, session in list(self._sessions.items()):
                if now - session.last_heartbeat > self._heartbeat_timeout:
                    stale.append(sid)
            for sid in stale:
                self._destroy_session_unlocked(sid)
        if stale:
            logger.info("Cleaned up %d stale sessions", len(stale))
        return stale

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all active sessions."""
        with self._lock:
            return [s.to_dict() for s in self._sessions.values()]

    def list_online_players(self) -> List[Dict[str, Any]]:
        """List players with ONLINE or AWAY status."""
        with self._lock:
            return [
                s.to_dict() for s in self._sessions.values()
                if s.status in (PlayerStatus.ONLINE, PlayerStatus.AWAY)
            ]

    def get_players_in_scene(self, scene_name: str) -> List[Dict[str, Any]]:
        """Get all players currently in a specific scene."""
        with self._lock:
            return [
                s.to_dict() for s in self._sessions.values()
                if s.connected_scene == scene_name
                and s.status != PlayerStatus.OFFLINE
            ]

    @property
    def session_count(self) -> int:
        """Number of active sessions."""
        with self._lock:
            return len(self._sessions)

    def get_stats(self) -> Dict[str, Any]:
        """Get session manager statistics."""
        with self._lock:
            by_status = {}
            for s in self._sessions.values():
                by_status[s.status.value] = by_status.get(s.status.value, 0) + 1
            by_scene: Dict[str, int] = {}
            for s in self._sessions.values():
                if s.connected_scene:
                    by_scene[s.connected_scene] = by_scene.get(s.connected_scene, 0) + 1
            return {
                "total_sessions": len(self._sessions),
                "by_status": by_status,
                "by_scene": by_scene,
                "heartbeat_timeout": self._heartbeat_timeout,
            }

    def reset(self) -> None:
        """Clear all sessions."""
        with self._lock:
            self._sessions.clear()
            self._states.clear()
            self._player_sessions.clear()
            logger.info("SessionManager reset")


# ──── Singleton ────

_SESSION_MANAGER: Optional[SessionManager] = None
_sm_lock = threading.Lock()


def get_session_manager() -> SessionManager:
    """Get or create the global SessionManager singleton."""
    global _SESSION_MANAGER
    if _SESSION_MANAGER is None:
        with _sm_lock:
            if _SESSION_MANAGER is None:
                _SESSION_MANAGER = SessionManager()
    return _SESSION_MANAGER


def reset_session_manager() -> None:
    """Reset the global SessionManager singleton."""
    global _SESSION_MANAGER
    with _sm_lock:
        if _SESSION_MANAGER is not None:
            _SESSION_MANAGER.reset()
        _SESSION_MANAGER = None
