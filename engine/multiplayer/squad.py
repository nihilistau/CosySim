"""
Squad System — Group players for shared objectives (co-op heists)
==================================================================

A Squad groups 2-4 players into a shared instance for cooperative play.
Used primarily by the Heist scene for co-op missions, but generic enough
for any multi-player objective (raids, territory captures, group quests).

Usage:
    from engine.multiplayer.squad import get_squad_manager

    mgr = get_squad_manager()
    squad = mgr.create_squad("player_1", "Knack")
    mgr.join_squad(squad.squad_id, "player_2", "Viktor")
    mgr.set_role(squad.squad_id, "player_1", "hacker")
    mgr.set_role(squad.squad_id, "player_2", "muscle")
    mgr.set_ready(squad.squad_id, "player_1", True)
    mgr.set_ready(squad.squad_id, "player_2", True)

    if mgr.is_all_ready(squad.squad_id):
        heist_id = mgr.start_heist(squad.squad_id)

Version: v1.52.0 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.52.0 [2026-03-26] — Initial: Squad, SquadMember, SquadManager

CONNECTS: SessionManager (engine.multiplayer.session_manager),
          HeistState (content.scenes.heist.heist_game),
          Leaderboards (engine.multiplayer.leaderboards)
CALLED BY: heist_scene.py SocketIO handlers, heist_planning_skills
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


# ──── Enums ──────────────────────────────────────────────────────────────

class SquadStatus(str, Enum):
    FORMING = "forming"
    READY = "ready"
    IN_HEIST = "in_heist"
    COMPLETED = "completed"
    DISBANDED = "disbanded"


# Valid player roles in a heist squad
VALID_ROLES = {"hacker", "muscle", "talker", "driver", "demo", "recon"}


# ──── Data Models ────────────────────────────────────────────────────────

@dataclass
class SquadMember:
    """A player in a squad."""

    player_id: str
    display_name: str
    role: str = ""
    ready: bool = False
    joined_at: float = field(default_factory=time.time)

    # Runtime stats (populated during/after heist)
    obstacles_cleared: int = 0
    crew_arguments: int = 0
    loot_share: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "player_id": self.player_id,
            "display_name": self.display_name,
            "role": self.role,
            "ready": self.ready,
            "joined_at": self.joined_at,
            "obstacles_cleared": self.obstacles_cleared,
            "crew_arguments": self.crew_arguments,
            "loot_share": self.loot_share,
        }


@dataclass
class Squad:
    """A group of players working toward a shared objective."""

    squad_id: str
    leader_id: str
    members: Dict[str, SquadMember] = field(default_factory=dict)
    status: SquadStatus = SquadStatus.FORMING
    scene: str = "heist"
    heist_id: str = ""
    max_members: int = 4
    created_at: float = field(default_factory=time.time)
    total_loot: int = 0

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def is_full(self) -> bool:
        return self.member_count >= self.max_members

    @property
    def all_ready(self) -> bool:
        return (
            self.member_count >= 2
            and all(m.ready for m in self.members.values())
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "squad_id": self.squad_id,
            "leader_id": self.leader_id,
            "members": {k: v.to_dict() for k, v in self.members.items()},
            "status": self.status.value,
            "scene": self.scene,
            "heist_id": self.heist_id,
            "max_members": self.max_members,
            "member_count": self.member_count,
            "all_ready": self.all_ready,
            "created_at": self.created_at,
            "total_loot": self.total_loot,
        }


# ──── Squad Manager ──────────────────────────────────────────────────────

class SquadManager:
    """Thread-safe manager for squad lifecycle.

    Follows the SessionManager pattern: dict-based storage with lock,
    singleton access via get_squad_manager().
    """

    def __init__(self) -> None:
        self._squads: Dict[str, Squad] = {}
        self._player_squad: Dict[str, str] = {}  # player_id → squad_id
        self._lock = threading.Lock()

    # ── Creation ─────────────────────────────────────────────────────

    def create_squad(
        self,
        leader_id: str,
        display_name: str,
        scene: str = "heist",
        max_members: int = 4,
    ) -> Squad:
        """Create a new squad with the leader as first member.

        Args:
            leader_id: Player ID of the squad leader.
            display_name: Leader's display name.
            scene: Target scene for the squad activity.
            max_members: Maximum squad size (2-4).

        Returns:
            The created Squad.
        """
        with self._lock:
            # Check if player is already in a squad
            if leader_id in self._player_squad:
                existing = self._squads.get(self._player_squad[leader_id])
                if existing and existing.status in (SquadStatus.FORMING, SquadStatus.READY, SquadStatus.IN_HEIST):
                    raise ValueError(f"Player {leader_id} is already in squad {existing.squad_id}")

            squad_id = f"squad_{uuid.uuid4().hex[:8]}"
            leader = SquadMember(player_id=leader_id, display_name=display_name)

            squad = Squad(
                squad_id=squad_id,
                leader_id=leader_id,
                members={leader_id: leader},
                scene=scene,
                max_members=max(2, min(4, max_members)),
            )

            self._squads[squad_id] = squad
            self._player_squad[leader_id] = squad_id

            logger.info(
                "[SquadManager] Squad created (operation=create_squad, "
                "squad=%s, leader=%s, scene=%s)", squad_id, leader_id, scene,
            )
            return squad

    # ── Membership ───────────────────────────────────────────────────

    def join_squad(
        self,
        squad_id: str,
        player_id: str,
        display_name: str,
    ) -> bool:
        """Add a player to a squad.

        Returns:
            True if joined successfully.
        """
        with self._lock:
            squad = self._squads.get(squad_id)
            if not squad:
                raise ValueError(f"Squad {squad_id} not found")
            if squad.status != SquadStatus.FORMING:
                raise ValueError(f"Squad is {squad.status.value}, not accepting members")
            if squad.is_full:
                raise ValueError(f"Squad is full ({squad.max_members} members)")
            if player_id in squad.members:
                return True  # Already a member
            if player_id in self._player_squad:
                raise ValueError(f"Player already in another squad")

            squad.members[player_id] = SquadMember(
                player_id=player_id,
                display_name=display_name,
            )
            self._player_squad[player_id] = squad_id

            logger.info(
                "[SquadManager] Player joined (operation=join_squad, "
                "squad=%s, player=%s, count=%d)", squad_id, player_id, squad.member_count,
            )
            return True

    def leave_squad(self, squad_id: str, player_id: str) -> bool:
        """Remove a player from a squad.

        If the leader leaves, the squad is disbanded.
        """
        with self._lock:
            squad = self._squads.get(squad_id)
            if not squad or player_id not in squad.members:
                return False

            if squad.status == SquadStatus.IN_HEIST:
                raise ValueError("Cannot leave during an active heist")

            del squad.members[player_id]
            self._player_squad.pop(player_id, None)

            # If leader left or squad is empty, disband
            if player_id == squad.leader_id or not squad.members:
                self._disband_internal(squad)
                return True

            logger.info(
                "[SquadManager] Player left (operation=leave_squad, "
                "squad=%s, player=%s, remaining=%d)",
                squad_id, player_id, squad.member_count,
            )
            return True

    # ── Roles + Ready ────────────────────────────────────────────────

    def set_role(self, squad_id: str, player_id: str, role: str) -> bool:
        """Set a player's role in the squad."""
        with self._lock:
            squad = self._squads.get(squad_id)
            if not squad or player_id not in squad.members:
                return False
            if role and role not in VALID_ROLES:
                raise ValueError(f"Invalid role '{role}'. Valid: {VALID_ROLES}")

            squad.members[player_id].role = role
            return True

    def set_ready(self, squad_id: str, player_id: str, ready: bool = True) -> bool:
        """Toggle a player's ready state."""
        with self._lock:
            squad = self._squads.get(squad_id)
            if not squad or player_id not in squad.members:
                return False

            squad.members[player_id].ready = ready

            # Auto-advance status when all ready
            if squad.all_ready and squad.status == SquadStatus.FORMING:
                squad.status = SquadStatus.READY

            return True

    def is_all_ready(self, squad_id: str) -> bool:
        """Check if all members are ready."""
        squad = self._squads.get(squad_id)
        return squad.all_ready if squad else False

    # ── Heist Lifecycle ──────────────────────────────────────────────

    def start_heist(self, squad_id: str) -> Optional[str]:
        """Start a heist for the squad. All members must be ready.

        Returns:
            The heist_id if started, None if not ready.
        """
        with self._lock:
            squad = self._squads.get(squad_id)
            if not squad:
                return None
            if not squad.all_ready:
                return None

            heist_id = f"heist_{uuid.uuid4().hex[:8]}"
            squad.heist_id = heist_id
            squad.status = SquadStatus.IN_HEIST

            logger.info(
                "[SquadManager] Heist started (operation=start_heist, "
                "squad=%s, heist=%s, members=%d)",
                squad_id, heist_id, squad.member_count,
            )
            return heist_id

    def complete_heist(
        self,
        squad_id: str,
        total_loot: int = 0,
        success: bool = True,
    ) -> Dict[str, int]:
        """Complete a heist and split loot among members.

        Returns:
            Dict of player_id → loot_share.
        """
        with self._lock:
            squad = self._squads.get(squad_id)
            if not squad:
                return {}

            squad.total_loot = total_loot
            squad.status = SquadStatus.COMPLETED

            # Split loot: equal base + bonus for obstacles cleared - penalty for arguments
            shares: Dict[str, int] = {}
            if squad.members and total_loot > 0:
                base = total_loot // len(squad.members)
                for pid, member in squad.members.items():
                    bonus = int(base * 0.1 * member.obstacles_cleared)
                    penalty = int(base * 0.05 * member.crew_arguments)
                    share = max(0, base + bonus - penalty)
                    member.loot_share = share
                    shares[pid] = share

            # Clean up player→squad mappings
            for pid in squad.members:
                self._player_squad.pop(pid, None)

            logger.info(
                "[SquadManager] Heist completed (operation=complete_heist, "
                "squad=%s, loot=%d, success=%s, shares=%s)",
                squad_id, total_loot, success, shares,
            )
            return shares

    # ── Disband ──────────────────────────────────────────────────────

    def disband(self, squad_id: str) -> bool:
        """Disband a squad (leader action)."""
        with self._lock:
            squad = self._squads.get(squad_id)
            if not squad:
                return False
            if squad.status == SquadStatus.IN_HEIST:
                raise ValueError("Cannot disband during an active heist")
            self._disband_internal(squad)
            return True

    def _disband_internal(self, squad: Squad) -> None:
        """Internal disband (must hold lock)."""
        squad.status = SquadStatus.DISBANDED
        for pid in squad.members:
            self._player_squad.pop(pid, None)
        logger.info("[SquadManager] Squad disbanded (operation=disband, squad=%s)", squad.squad_id)

    # ── Queries ──────────────────────────────────────────────────────

    def get_squad(self, squad_id: str) -> Optional[Squad]:
        """Get a squad by ID."""
        return self._squads.get(squad_id)

    def get_player_squad(self, player_id: str) -> Optional[Squad]:
        """Get the squad a player is currently in."""
        squad_id = self._player_squad.get(player_id)
        return self._squads.get(squad_id) if squad_id else None

    def list_open_squads(self) -> List[Dict[str, Any]]:
        """List squads in FORMING status (joinable)."""
        return [
            s.to_dict()
            for s in self._squads.values()
            if s.status == SquadStatus.FORMING and not s.is_full
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get squad system statistics."""
        active = [s for s in self._squads.values() if s.status in (SquadStatus.FORMING, SquadStatus.READY, SquadStatus.IN_HEIST)]
        return {
            "total_squads": len(self._squads),
            "active_squads": len(active),
            "players_in_squads": len(self._player_squad),
        }


# ──── Singleton ──────────────────────────────────────────────────────────

_manager: Optional[SquadManager] = None
_manager_lock = threading.Lock()


def get_squad_manager() -> SquadManager:
    """Get or create the SquadManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SquadManager()
    return _manager
