"""Crew system for CosySim — player crew management, roles, and operations.

The crew is a group of NPCs who have built a strong relationship with the player
and been formally recruited. Crew members have roles, skill contributions, and
loyalty scores. Crews can be deployed on operations (missions) and level up over
time.

Integrates with PlayerProfile for relationship data and PlayerState for credits.

Usage::

    from engine.world.crew import get_crew_manager

    crew = get_crew_manager()
    crew.recruit("lola", role="fixer", notes="Lola finally agreed to join after the casino job")
    state = crew.to_dict()
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from engine.characters.player_profile import get_player_profile as _get_player_profile
except Exception as _exc:  # pragma: no cover
    # v1.54.0 [2026-03-26] — Warn when PlayerProfile is unavailable instead of silent swallow
    logger.warning("[Crew] PlayerProfile unavailable (operation=import): %s", _exc)
    _get_player_profile = None  # type: ignore[assignment]


def get_player_profile():
    """Return the PlayerProfile, resolved lazily to allow patching in tests."""
    if _get_player_profile is not None:
        return _get_player_profile()
    raise ImportError("player_profile not available")


# ──── Crew roles ──────────────────────────────────────────────────────────────

CREW_ROLES = {
    "fixer":    {"label": "Fixer",     "icon": "🤝", "desc": "Connections, contacts, information broker"},
    "hacker":   {"label": "Netrunner", "icon": "💻", "desc": "Cyberspace infiltration, data extraction"},
    "muscle":   {"label": "Muscle",    "icon": "💪", "desc": "Physical protection, intimidation, combat"},
    "medic":    {"label": "Medic",     "icon": "🩺", "desc": "Field medicine, stims, trauma care"},
    "driver":   {"label": "Driver",    "icon": "🚗", "desc": "High-speed extraction, vehicle specialist"},
    "tech":     {"label": "Techie",    "icon": "🔧", "desc": "Hardware, weapons modding, machinery"},
    "lookout":  {"label": "Lookout",   "icon": "👁️", "desc": "Surveillance, early warning, stealth recon"},
    "face":     {"label": "Face",      "icon": "🎭", "desc": "Social engineering, smooth talk, infiltration"},
    "supplier": {"label": "Supplier",  "icon": "📦", "desc": "Black market access, gear procurement"},
    "unknown":  {"label": "Unknown",   "icon": "❓", "desc": "Role not yet determined"},
}

# Crew operation types
OPERATION_TYPES = {
    "recon":     {"label": "Recon",     "min_crew": 1, "skill_weight": {"lookout": 2, "hacker": 1}},
    "heist":     {"label": "Heist",     "min_crew": 3, "skill_weight": {"hacker": 2, "muscle": 1, "driver": 1}},
    "extraction": {"label": "Extraction", "min_crew": 2, "skill_weight": {"driver": 2, "medic": 1, "muscle": 1}},
    "deal":      {"label": "Deal",      "min_crew": 1, "skill_weight": {"fixer": 2, "face": 1}},
    "hit":       {"label": "Hit",       "min_crew": 2, "skill_weight": {"muscle": 2, "lookout": 1}},
    "hack":      {"label": "Hack",      "min_crew": 1, "skill_weight": {"hacker": 3}},
}

# Minimum relationship score to recruit
_MIN_RECRUIT_SCORE = 40.0
# Max active crew size
_MAX_CREW_SIZE = 8


# ──── Data structures ─────────────────────────────────────────────────────────

@dataclass
class CrewMember:
    character_id: str
    role: str = "unknown"
    loyalty: float = 50.0   # 0–100
    xp: int = 0              # experience points
    level: int = 1           # 1–5
    operations: int = 0      # operations completed
    joined_at: float = field(default_factory=time.time)
    notes: List[str] = field(default_factory=list)
    available: bool = True   # False if on a mission or recovering

    @property
    def role_label(self) -> str:
        return CREW_ROLES.get(self.role, CREW_ROLES["unknown"])["label"]

    @property
    def role_icon(self) -> str:
        return CREW_ROLES.get(self.role, CREW_ROLES["unknown"])["icon"]

    def add_xp(self, amount: int) -> bool:
        """Add XP and level up if threshold reached. Returns True if levelled up."""
        self.xp += amount
        threshold = self.level * 100
        if self.xp >= threshold and self.level < 5:
            self.level += 1
            self.xp = 0
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "character_id": self.character_id,
            "role": self.role,
            "role_label": self.role_label,
            "role_icon": self.role_icon,
            "loyalty": self.loyalty,
            "xp": self.xp,
            "level": self.level,
            "operations": self.operations,
            "joined_at": self.joined_at,
            "notes": list(self.notes),
            "available": self.available,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CrewMember":
        return cls(
            character_id=data["character_id"],
            role=data.get("role", "unknown"),
            loyalty=float(data.get("loyalty", 50.0)),
            xp=int(data.get("xp", 0)),
            level=int(data.get("level", 1)),
            operations=int(data.get("operations", 0)),
            joined_at=float(data.get("joined_at", time.time())),
            notes=list(data.get("notes", [])),
            available=bool(data.get("available", True)),
        )


@dataclass
class CrewOperation:
    op_id: str
    op_type: str
    label: str
    assigned_crew: List[str]   # character_ids
    started_at: float
    duration_secs: float       # seconds until complete
    status: str = "active"     # active | complete | failed
    reward_credits: int = 0
    reward_xp: int = 0
    notes: str = ""

    @property
    def complete_at(self) -> float:
        return self.started_at + self.duration_secs

    @property
    def is_complete(self) -> bool:
        return time.time() >= self.complete_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "op_id": self.op_id,
            "op_type": self.op_type,
            "label": self.label,
            "assigned_crew": list(self.assigned_crew),
            "started_at": self.started_at,
            "duration_secs": self.duration_secs,
            "complete_at": self.complete_at,
            "status": self.status,
            "reward_credits": self.reward_credits,
            "reward_xp": self.reward_xp,
            "notes": self.notes,
            "time_remaining": max(0, int(self.complete_at - time.time())),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CrewOperation":
        return cls(
            op_id=data["op_id"],
            op_type=data.get("op_type", "recon"),
            label=data.get("label", "Operation"),
            assigned_crew=list(data.get("assigned_crew", [])),
            started_at=float(data.get("started_at", time.time())),
            duration_secs=float(data.get("duration_secs", 3600)),
            status=data.get("status", "active"),
            reward_credits=int(data.get("reward_credits", 0)),
            reward_xp=int(data.get("reward_xp", 0)),
            notes=data.get("notes", ""),
        )


# ──── CrewManager ─────────────────────────────────────────────────────────────

class CrewManager:
    """Thread-safe crew management singleton.

    Handles recruitment, deployment, operations, and crew state.
    Persists to ``data/crew.json``.
    """

    _SAVE_PATH: Path = Path("data") / "crew.json"
    _instance: Optional["CrewManager"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._members: Dict[str, CrewMember] = {}
        self._operations: List[CrewOperation] = []
        self._crew_name: str = "Unnamed Crew"
        self._crew_rep: int = 0   # crew-wide reputation
        if self._SAVE_PATH.exists():
            try:
                self._load()
            except Exception as exc:
                logger.warning("CrewManager: load failed: %s", exc)

    # ── Recruitment ──────────────────────────────────────────────────────────

    def can_recruit(self, character_id: str) -> tuple[bool, str]:
        """Check if *character_id* can be recruited.

        Args:
            character_id: NPC identifier.

        Returns:
            Tuple of (can_recruit: bool, reason: str).
        """
        if len(self._members) >= _MAX_CREW_SIZE:
            return False, f"Crew is full ({_MAX_CREW_SIZE} max). Cut someone loose first."
        if character_id in self._members:
            return False, f"{character_id} is already in your crew."
        # Check relationship score
        try:
            profile = get_player_profile()
            rel = profile.relationships.get(character_id)
            score = rel.score if rel else 0.0
            if score < _MIN_RECRUIT_SCORE:
                return False, (
                    f"{character_id} doesn't trust you enough (score {score:+.1f}, "
                    f"need {_MIN_RECRUIT_SCORE:+.1f}). Build the relationship first."
                )
        except Exception as e:
            logger.debug("[CrewManager] Relationship check failed (operation=can_recruit): %s", e)
        return True, "OK"

    def recruit(
        self,
        character_id: str,
        role: str = "unknown",
        notes: str = "",
        skip_check: bool = False,
    ) -> tuple[bool, str]:
        """Recruit *character_id* into the crew.

        Args:
            character_id: NPC identifier.
            role: Crew role (see CREW_ROLES).
            notes: Optional recruitment note.
            skip_check: If True, bypass relationship score check only.
                        Capacity and duplicate checks always apply.

        Returns:
            Tuple of (success: bool, message: str).
        """
        # Always check capacity and duplicates
        with self._lock:
            if character_id in self._members:
                return False, f"{character_id} is already in your crew."
            if len(self._members) >= _MAX_CREW_SIZE:
                return False, f"Crew is full ({_MAX_CREW_SIZE} max). Cut someone loose first."

        # Relationship check (skippable)
        if not skip_check:
            try:
                profile = get_player_profile()
                rel = profile.relationships.get(character_id)
                score = rel.score if rel else 0.0
                if score < _MIN_RECRUIT_SCORE:
                    return False, (
                        f"{character_id} doesn't trust you enough (score {score:+.1f}, "
                        f"need {_MIN_RECRUIT_SCORE:+.1f}). Build the relationship first."
                    )
            except Exception as e:
                logger.debug("[CrewManager] Relationship check failed (operation=recruit): %s", e)

        if role not in CREW_ROLES:
            role = "unknown"

        member = CrewMember(
            character_id=character_id,
            role=role,
            notes=[notes] if notes else [],
        )

        with self._lock:
            self._members[character_id] = member

        # Update PlayerProfile relationship type
        try:
            profile = get_player_profile()
            profile.add_crew_member(character_id, crew_tag=f"crew:{role}", notes=notes)
        except Exception as e:
            logger.debug("[CrewManager] PlayerProfile update failed (operation=recruit): %s", e)

        self._save()
        logger.info("CrewManager: %s recruited as %s", character_id, role)
        return True, f"{character_id} joined your crew as {CREW_ROLES[role]['label']}!"

    def dismiss(self, character_id: str, reason: str = "") -> bool:
        """Remove *character_id* from the crew.

        Args:
            character_id: NPC identifier.
            reason: Optional reason for dismissal.

        Returns:
            True if dismissed, False if not found.
        """
        with self._lock:
            if character_id not in self._members:
                return False
            del self._members[character_id]

        # Update relationship type back to friend
        try:
            profile = get_player_profile()
            profile.set_relationship_type(character_id, "friend", notes=f"Left crew: {reason}" if reason else "Left crew")
        except Exception as e:
            logger.debug("[CrewManager] PlayerProfile update failed (operation=dismiss): %s", e)

        self._save()
        logger.info("CrewManager: %s dismissed (%s)", character_id, reason)
        return True

    # ── Loyalty ──────────────────────────────────────────────────────────────

    def adjust_loyalty(self, character_id: str, delta: float, reason: str = "") -> Optional[float]:
        """Adjust a crew member's loyalty score.

        Args:
            character_id: Crew member identifier.
            delta: Amount to adjust (positive = more loyal).
            reason: Optional reason for the change.

        Returns:
            New loyalty score, or None if not found.
        """
        with self._lock:
            member = self._members.get(character_id)
            if not member:
                return None
            member.loyalty = max(0.0, min(100.0, member.loyalty + delta))
            if reason:
                member.notes.append(f"Loyalty {delta:+.0f}: {reason}")
            val = member.loyalty
        self._save()
        return val

    # ── Operations ───────────────────────────────────────────────────────────

    def start_operation(
        self,
        op_type: str,
        assigned_crew: List[str],
        label: str = "",
        duration_secs: float = 3600,
        reward_credits: int = 0,
        reward_xp: int = 25,
    ) -> tuple[bool, str]:
        """Start a crew operation.

        Args:
            op_type: Type from OPERATION_TYPES.
            assigned_crew: List of character_ids to assign.
            label: Human-readable operation label.
            duration_secs: Seconds until completion.
            reward_credits: Credits on success.
            reward_xp: XP per crew member on success.

        Returns:
            Tuple of (success: bool, message: str).
        """
        op_info = OPERATION_TYPES.get(op_type)
        if not op_info:
            return False, f"Unknown operation type '{op_type}'"

        min_crew = op_info["min_crew"]
        if len(assigned_crew) < min_crew:
            return False, f"{op_type} requires at least {min_crew} crew member(s)"

        with self._lock:
            # Verify all assigned are available
            unavailable = [c for c in assigned_crew if not self._members.get(c, CrewMember("")).available]
            if unavailable:
                return False, f"Crew not available: {', '.join(unavailable)}"

            op = CrewOperation(
                op_id=str(uuid.uuid4())[:8],
                op_type=op_type,
                label=label or f"{op_info['label']} Operation",
                assigned_crew=list(assigned_crew),
                started_at=time.time(),
                duration_secs=duration_secs,
                reward_credits=reward_credits,
                reward_xp=reward_xp,
            )
            self._operations.append(op)

            # Mark crew as unavailable
            for cid in assigned_crew:
                if cid in self._members:
                    self._members[cid].available = False

        self._save()
        logger.info("CrewManager: started %s op '%s' with %d crew", op_type, op.label, len(assigned_crew))
        return True, f"Operation '{op.label}' started! {len(assigned_crew)} crew deployed. ETA: {int(duration_secs // 60)} min."

    def check_operations(self) -> List[Dict[str, Any]]:
        """Check all active operations and complete any that are ready.

        Returns:
            List of completed operation result dicts.
        """
        completed = []
        with self._lock:
            for op in list(self._operations):
                if op.status == "active" and op.is_complete:
                    op.status = "complete"
                    result = self._resolve_operation(op)
                    completed.append(result)
        if completed:
            self._save()
        return completed

    def _resolve_operation(self, op: CrewOperation) -> Dict[str, Any]:
        """Resolve a completed operation and apply rewards.

        Args:
            op: The completed CrewOperation.

        Returns:
            Result dict with outcome details.
        """
        # Mark crew available again
        for cid in op.assigned_crew:
            if cid in self._members:
                self._members[cid].available = True
                self._members[cid].operations += 1
                levelled_up = self._members[cid].add_xp(op.reward_xp)
                if levelled_up:
                    logger.info("Crew member %s levelled up to %d!", cid, self._members[cid].level)

        # Apply credit reward
        if op.reward_credits > 0:
            try:
                from engine.world.player_state import get_player_state
                get_player_state().earn_credits(op.reward_credits, reason=f"crew_op:{op.op_type}")
            except Exception as e:
                logger.debug("[CrewManager] Credit reward failed (operation=complete_op): %s", e)

        return {
            "op_id": op.op_id,
            "label": op.label,
            "op_type": op.op_type,
            "status": "complete",
            "credits_earned": op.reward_credits,
            "xp_earned": op.reward_xp,
            "crew": op.assigned_crew,
        }

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_member(self, character_id: str) -> Optional[CrewMember]:
        """Return a crew member by ID, or None."""
        with self._lock:
            return self._members.get(character_id)

    def get_all_members(self) -> List[CrewMember]:
        """Return all crew members."""
        with self._lock:
            return list(self._members.values())

    def get_available(self) -> List[CrewMember]:
        """Return all available (not on operation) crew members."""
        with self._lock:
            return [m for m in self._members.values() if m.available]

    def get_active_operations(self) -> List[CrewOperation]:
        """Return all active (not yet complete) operations."""
        with self._lock:
            return [op for op in self._operations if op.status == "active"]

    def set_crew_name(self, name: str) -> None:
        """Set the crew's display name."""
        with self._lock:
            self._crew_name = name
        self._save()

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a full JSON-safe snapshot."""
        with self._lock:
            members = [m.to_dict() for m in self._members.values()]
            ops = [op.to_dict() for op in self._operations[-10:]]
        return {
            "crew_name": self._crew_name,
            "crew_rep": self._crew_rep,
            "members": members,
            "member_count": len(members),
            "max_size": _MAX_CREW_SIZE,
            "active_operations": [op.to_dict() for op in self.get_active_operations()],
            "recent_operations": ops,
            "roles": CREW_ROLES,
        }

    def to_hud_dict(self) -> List[Dict[str, Any]]:
        """Return compact crew list for HUD display."""
        with self._lock:
            members = list(self._members.values())
        return [
            {
                "id":        m.character_id,
                "role":      m.role,
                "role_icon": m.role_icon,
                "loyalty":   int(m.loyalty),
                "level":     m.level,
                "available": m.available,
            }
            for m in members
        ]

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            self._SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {
                    "crew_name": self._crew_name,
                    "crew_rep": self._crew_rep,
                    "members": {k: v.to_dict() for k, v in self._members.items()},
                    "operations": [op.to_dict() for op in self._operations[-50:]],
                    "_saved_at": time.time(),
                }
            self._SAVE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("CrewManager._save failed: %s", exc)

    def _load(self) -> None:
        data = json.loads(self._SAVE_PATH.read_text(encoding="utf-8"))
        with self._lock:
            self._crew_name = data.get("crew_name", "Unnamed Crew")
            self._crew_rep = int(data.get("crew_rep", 0))
            for cid, mdata in data.get("members", {}).items():
                self._members[cid] = CrewMember.from_dict(mdata)
            for op_data in data.get("operations", []):
                try:
                    self._operations.append(CrewOperation.from_dict(op_data))
                except Exception as e:
                    logger.debug("[CrewManager] Operation load skipped (operation=load): %s", e)
        logger.info("CrewManager loaded: %d members, %d operations", len(self._members), len(self._operations))


# ──── Singleton accessor ──────────────────────────────────────────────────────


def get_crew_manager() -> CrewManager:
    """Return the process-wide CrewManager singleton."""
    if CrewManager._instance is None:
        with CrewManager._class_lock:
            if CrewManager._instance is None:
                CrewManager._instance = CrewManager()
    return CrewManager._instance
