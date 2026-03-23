"""Mission system for CosySim v0.82 "THE OPEN WORLD".

Manages player missions across Neon City: accepting jobs, tracking
objectives, rewarding completion, and supporting agent-to-agent handoffs
where NPCs assign work to the player's crew.

Mission types:
    RECON       — gather intelligence on a target
    HEIST       — steal an item or credits from a location
    DEAL        — negotiate a trade or brokerage agreement
    EXTRACTION  — move a person or data from point A to B
    HIT         — neutralise a target (non-lethal takedown by default)

Reward types:
    credits, xp, reputation, items, faction_rep

Usage::

    from engine.world.mission import get_mission_manager

    mgr = get_mission_manager()
    mgr.accept("recon_01")           # accept available mission
    mgr.complete("recon_01", notes)  # complete with agent notes
    mgr.list_available()             # see what's on the board
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Module-level wrapper for patching in tests
def get_player_state():  # noqa: N802
    from engine.world.player_state import get_player_state as _get
    return _get()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MissionType(str, Enum):
    RECON      = "recon"
    HEIST      = "heist"
    DEAL       = "deal"
    EXTRACTION = "extraction"
    HIT        = "hit"


class MissionStatus(str, Enum):
    AVAILABLE  = "available"
    ACTIVE     = "active"
    COMPLETED  = "completed"
    FAILED     = "failed"
    ABANDONED  = "abandoned"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MissionObjective:
    """A single step in a mission."""

    id: str
    description: str
    completed: bool = False
    optional: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "completed": self.completed,
            "optional": self.optional,
        }


@dataclass
class MissionReward:
    """Rewards granted on mission completion."""

    credits: int = 0
    xp: int = 0
    reputation: int = 0
    items: List[str] = field(default_factory=list)
    faction: str = ""
    faction_rep: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "credits": self.credits,
            "xp": self.xp,
            "reputation": self.reputation,
            "items": self.items,
            "faction": self.faction,
            "faction_rep": self.faction_rep,
        }


@dataclass
class Mission:
    """A single mission in the board."""

    id: str
    title: str
    description: str
    mission_type: MissionType
    giver_npc: str                                    # NPC who offered the job
    location: str                                     # Primary scene location
    difficulty: int                                   # 1–5
    time_limit: Optional[int]                         # in-game minutes; None = unlimited
    reward: MissionReward
    objectives: List[MissionObjective] = field(default_factory=list)
    status: MissionStatus = MissionStatus.AVAILABLE
    assigned_crew: List[str] = field(default_factory=list)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    notes: str = ""                                   # agent / player outcome notes

    # ── Computed ──────────────────────────────────────────────────────────

    @property
    def progress(self) -> Dict[str, int]:
        """Return {done, total, pct} objective progress."""
        required = [o for o in self.objectives if not o.optional]
        done = sum(1 for o in required if o.completed)
        total = len(required)
        pct = int(100 * done / total) if total else 100
        return {"done": done, "total": total, "pct": pct}

    @property
    def is_complete(self) -> bool:
        """True when all required objectives are done."""
        return all(o.completed for o in self.objectives if not o.optional)

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "type": self.mission_type.value,
            "giver": self.giver_npc,
            "location": self.location,
            "difficulty": self.difficulty,
            "time_limit_min": self.time_limit,
            "reward": self.reward.to_dict(),
            "objectives": [o.to_dict() for o in self.objectives],
            "status": self.status.value,
            "assigned_crew": self.assigned_crew,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "notes": self.notes,
            "progress": self.progress,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Mission":
        reward = MissionReward(
            credits=data.get("reward", {}).get("credits", 0),
            xp=data.get("reward", {}).get("xp", 0),
            reputation=data.get("reward", {}).get("reputation", 0),
            items=data.get("reward", {}).get("items", []),
            faction=data.get("reward", {}).get("faction", ""),
            faction_rep=data.get("reward", {}).get("faction_rep", 0),
        )
        objectives = [
            MissionObjective(
                id=o["id"],
                description=o["description"],
                completed=o.get("completed", False),
                optional=o.get("optional", False),
            )
            for o in data.get("objectives", [])
        ]
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            mission_type=MissionType(data.get("type", "recon")),
            giver_npc=data.get("giver", ""),
            location=data.get("location", ""),
            difficulty=data.get("difficulty", 1),
            time_limit=data.get("time_limit_min"),
            reward=reward,
            objectives=objectives,
            status=MissionStatus(data.get("status", "available")),
            assigned_crew=data.get("assigned_crew", []),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            notes=data.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# Builtin Mission Templates
# ---------------------------------------------------------------------------

def _build_builtin_missions() -> List[Mission]:
    """Return 15 seed missions spread across all types and districts."""
    defs = [
        # RECON
        {
            "id": "recon_corp_signal",
            "title": "Ghost in the Wire",
            "description": "Viktor thinks OmniCorp is running a ghost project out of SIGNAL. Get in, scan their data terminals, don't get caught.",
            "type": "recon", "giver": "viktor", "location": "SIGNAL", "difficulty": 2, "time_limit": 60,
            "reward": {"credits": 1200, "xp": 80, "reputation": 5, "faction": "Ghost_Net", "faction_rep": 10},
            "objectives": [
                {"id": "scan_terminal_1", "description": "Scan terminal in server room"},
                {"id": "scan_terminal_2", "description": "Scan secondary terminal", "optional": True},
                {"id": "extract_clean", "description": "Leave without triggering alarms"},
            ],
        },
        {
            "id": "recon_penthouse_deal",
            "title": "Eyes on the High Floor",
            "description": "Someone upstairs is brokering tech to SynthSec. Lola wants names and faces.",
            "type": "recon", "giver": "lola", "location": "THE PENTHOUSE", "difficulty": 3, "time_limit": 90,
            "reward": {"credits": 2000, "xp": 120, "reputation": 8, "faction": "BlackMarket", "faction_rep": 5},
            "objectives": [
                {"id": "identify_broker", "description": "Identify the SynthSec broker"},
                {"id": "photograph_handoff", "description": "Capture the exchange", "optional": True},
            ],
        },
        # HEIST
        {
            "id": "heist_lab_prototype",
            "title": "The Clean Lift",
            "description": "NeoTech has a prototype neural chip in THE LAB. Frankie needs it. Do not damage the chip.",
            "type": "heist", "giver": "frankie", "location": "THE LAB", "difficulty": 4, "time_limit": 45,
            "reward": {"credits": 5000, "xp": 200, "reputation": 10, "items": ["void_runner"]},
            "objectives": [
                {"id": "bypass_security", "description": "Bypass lab security (hack or social)"},
                {"id": "locate_chip", "description": "Find the prototype in the lab"},
                {"id": "extract_chip", "description": "Extract the chip undamaged"},
                {"id": "deliver_frankie", "description": "Deliver to Frankie at NEON CITY"},
            ],
        },
        {
            "id": "heist_colosseum_credits",
            "title": "The House Always Loses",
            "description": "The arena bookies are skimming profits. Mira says clean out their safe — make it look like an inside job.",
            "type": "heist", "giver": "mira", "location": "THE COLOSSEUM", "difficulty": 3, "time_limit": None,
            "reward": {"credits": 3500, "xp": 150, "reputation": 5},
            "objectives": [
                {"id": "case_the_arena", "description": "Scout the bookies' office"},
                {"id": "crack_safe", "description": "Crack or hack the safe"},
                {"id": "plant_evidence", "description": "Plant the inside-job evidence", "optional": True},
            ],
        },
        # DEAL
        {
            "id": "deal_rusty_anchor_weapons",
            "title": "Old Debts",
            "description": "Aria's contact owes a debt. Mediate the handoff at THE RUSTY ANCHOR without violence.",
            "type": "deal", "giver": "aria", "location": "THE RUSTY ANCHOR", "difficulty": 2, "time_limit": None,
            "reward": {"credits": 1500, "xp": 60, "faction": "BlackMarket", "faction_rep": 8},
            "objectives": [
                {"id": "meet_contact", "description": "Meet Cara at the bar"},
                {"id": "negotiate_price", "description": "Negotiate a fair price"},
                {"id": "complete_handoff", "description": "Complete the exchange without violence"},
            ],
        },
        {
            "id": "deal_obscura_faction",
            "title": "Fractured Allegiance",
            "description": "Two factions are circling THE OBSCURA. Broker a ceasefire — or pick a side.",
            "type": "deal", "giver": "lola", "location": "THE OBSCURA", "difficulty": 4, "time_limit": None,
            "reward": {"credits": 2500, "xp": 180, "reputation": 15},
            "objectives": [
                {"id": "meet_faction_a", "description": "Meet the Ghost_Net rep"},
                {"id": "meet_faction_b", "description": "Meet the SynthSec rep"},
                {"id": "broker_deal", "description": "Broker the ceasefire or alliance"},
            ],
        },
        # EXTRACTION
        {
            "id": "extraction_grid_data",
            "title": "Data Ghost",
            "description": "Sensitive Nexus backup data is trapped behind a firewall on THE GRID. Extract it before the wipe.",
            "type": "extraction", "giver": "viktor", "location": "THE GRID", "difficulty": 3, "time_limit": 30,
            "reward": {"credits": 2800, "xp": 160, "items": ["netrunner_mk1"]},
            "objectives": [
                {"id": "locate_data_node", "description": "Locate the data node on the grid"},
                {"id": "bypass_firewall", "description": "Bypass the firewall"},
                {"id": "extract_data", "description": "Extract the data package"},
            ],
        },
        {
            "id": "extraction_throne_defector",
            "title": "One Last Ride",
            "description": "A DeepState defector is hiding in THE SHATTERED THRONE. Get them to Command Center alive.",
            "type": "extraction", "giver": "aria", "location": "THE SHATTERED THRONE", "difficulty": 5, "time_limit": 60,
            "reward": {"credits": 8000, "xp": 300, "reputation": 20, "faction": "DeepState", "faction_rep": -15},
            "objectives": [
                {"id": "locate_defector", "description": "Find the defector in The Throne"},
                {"id": "secure_defector", "description": "Secure their trust"},
                {"id": "travel_command", "description": "Deliver to Command Center"},
            ],
        },
        # HIT
        {
            "id": "hit_arcade_fixer",
            "title": "Loose Ends",
            "description": "A fixer at THE ARCADE has been selling crew intel. Mira wants them out of the game — permanently benched, not dead.",
            "type": "hit", "giver": "mira", "location": "THE ARCADE", "difficulty": 2, "time_limit": None,
            "reward": {"credits": 1800, "xp": 100, "reputation": 5},
            "objectives": [
                {"id": "identify_fixer", "description": "Identify the fixer"},
                {"id": "neutralise", "description": "Take them out of the game (non-lethal)"},
                {"id": "confirm_benched", "description": "Confirm with Mira", "optional": True},
            ],
        },
        {
            "id": "hit_velvet_pit_enforcers",
            "title": "House Cleaning",
            "description": "OmniCorp muscle is shaking down THE VELVET PIT. Lola wants them gone before tonight's event.",
            "type": "hit", "giver": "lola", "location": "THE VELVET PIT", "difficulty": 3, "time_limit": 120,
            "reward": {"credits": 2200, "xp": 130, "reputation": 10, "faction": "OmniCorp", "faction_rep": -10},
            "objectives": [
                {"id": "scout_enforcers", "description": "Count and locate the enforcers"},
                {"id": "remove_enforcers", "description": "Remove the enforcers from the venue"},
                {"id": "secure_venue", "description": "Confirm venue secure before the event"},
            ],
        },
        # Mixed extra
        {
            "id": "recon_briefing_room",
            "title": "Need to Know",
            "description": "Someone in THE BRIEFING ROOM has been leaking operation details. Identify the mole.",
            "type": "recon", "giver": "frankie", "location": "THE BRIEFING ROOM", "difficulty": 3, "time_limit": None,
            "reward": {"credits": 1600, "xp": 90, "reputation": 8},
            "objectives": [
                {"id": "attend_briefing", "description": "Attend the scheduled briefing"},
                {"id": "observe_reactions", "description": "Note suspicious behaviour"},
                {"id": "identify_mole", "description": "Identify the leak source"},
            ],
        },
        {
            "id": "heist_score_safe",
            "title": "The Big Score",
            "description": "THE SCORE's underground casino vault hasn't been touched in years. Viktor has the entry code — you have the skills.",
            "type": "heist", "giver": "viktor", "location": "THE SCORE", "difficulty": 5, "time_limit": None,
            "reward": {"credits": 10000, "xp": 400, "reputation": 25, "items": ["specter_3000"]},
            "objectives": [
                {"id": "get_vault_code", "description": "Get the vault access code from Viktor"},
                {"id": "distract_security", "description": "Create a distraction for security"},
                {"id": "enter_vault", "description": "Enter and clear the vault"},
                {"id": "escape_clean", "description": "Escape without triggering shutdown"},
            ],
        },
        {
            "id": "deal_command_center_alliance",
            "title": "Above the Board",
            "description": "Command Center wants a formal alliance with Ghost_Net. Facilitate the introductions.",
            "type": "deal", "giver": "aria", "location": "Command Center", "difficulty": 4, "time_limit": None,
            "reward": {"credits": 3000, "xp": 200, "faction": "Ghost_Net", "faction_rep": 20},
            "objectives": [
                {"id": "arrange_meeting", "description": "Arrange the summit meeting"},
                {"id": "vet_parties", "description": "Vet both parties for traps"},
                {"id": "seal_alliance", "description": "Close the deal"},
            ],
        },
        {
            "id": "extraction_club_noir_runner",
            "title": "Midnight Run",
            "description": "A data runner is stuck at CLUB NOIR with a hot package and no way out. Get them to the drop.",
            "type": "extraction", "giver": "mira", "location": "CLUB NOIR", "difficulty": 2, "time_limit": 45,
            "reward": {"credits": 1200, "xp": 70},
            "objectives": [
                {"id": "find_runner", "description": "Find the runner in Club Noir"},
                {"id": "secure_package", "description": "Secure the data package"},
                {"id": "reach_drop", "description": "Reach the drop at THE GRID"},
            ],
        },
        {
            "id": "hit_colosseum_fixer",
            "title": "Blood Sport",
            "description": "A match fixer is rigging THE COLOSSEUM outcomes. Frankie wants proof and the fixer gone.",
            "type": "hit", "giver": "frankie", "location": "THE COLOSSEUM", "difficulty": 3, "time_limit": None,
            "reward": {"credits": 2400, "xp": 140, "reputation": 12},
            "objectives": [
                {"id": "gather_proof", "description": "Collect evidence of fixing"},
                {"id": "confront_fixer", "description": "Confront the fixer with the evidence"},
                {"id": "report_frankie", "description": "Report outcome to Frankie"},
            ],
        },
    ]

    missions = []
    for d in defs:
        objectives = [
            MissionObjective(
                id=o["id"],
                description=o["description"],
                optional=o.get("optional", False),
            )
            for o in d.get("objectives", [])
        ]
        rw = d.get("reward", {})
        reward = MissionReward(
            credits=rw.get("credits", 0),
            xp=rw.get("xp", 0),
            reputation=rw.get("reputation", 0),
            items=rw.get("items", []),
            faction=rw.get("faction", ""),
            faction_rep=rw.get("faction_rep", 0),
        )
        missions.append(Mission(
            id=d["id"],
            title=d["title"],
            description=d["description"],
            mission_type=MissionType(d["type"]),
            giver_npc=d["giver"],
            location=d["location"],
            difficulty=d["difficulty"],
            time_limit=d.get("time_limit"),
            reward=reward,
            objectives=objectives,
        ))
    return missions


# ---------------------------------------------------------------------------
# MissionManager
# ---------------------------------------------------------------------------

class MissionManager:
    """Singleton mission manager.

    Maintains the mission board, tracks active/completed missions, applies
    rewards on completion, and integrates with PlayerState, CrewManager,
    and EventCascade.
    """

    _SAVE_PATH: Path = Path("data") / "missions.json"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._missions: Dict[str, Mission] = {}
        self._load_or_seed()

    # ── Init ─────────────────────────────────────────────────────────────

    def _load_or_seed(self) -> None:
        """Load persisted missions or seed with builtins."""
        if self._SAVE_PATH.exists():
            try:
                raw = json.loads(self._SAVE_PATH.read_text(encoding="utf-8"))
                for d in raw.get("missions", []):
                    m = Mission.from_dict(d)
                    self._missions[m.id] = m
                logger.info("MissionManager: loaded %d missions from disk", len(self._missions))
                # Ensure all builtin missions are present (add if missing)
                for bm in _build_builtin_missions():
                    if bm.id not in self._missions:
                        self._missions[bm.id] = bm
                return
            except Exception as exc:
                logger.warning("MissionManager: load failed: %s", exc)

        # First-run — seed with builtins
        for m in _build_builtin_missions():
            self._missions[m.id] = m
        self._save()
        logger.info("MissionManager: seeded %d builtin missions", len(self._missions))

    def _save(self) -> None:
        try:
            self._SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {"missions": [m.to_dict() for m in self._missions.values()]}
            self._SAVE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("MissionManager: save failed: %s", exc)

    # ── Queries ───────────────────────────────────────────────────────────

    def get_mission(self, mission_id: str) -> Optional[Mission]:
        """Return a mission by ID."""
        return self._missions.get(mission_id)

    def list_available(
        self,
        location: Optional[str] = None,
        mission_type: Optional[str] = None,
        max_difficulty: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return available missions as dicts.

        Args:
            location: Filter by scene location.
            mission_type: Filter by type (recon/heist/deal/extraction/hit).
            max_difficulty: Only return missions at or below this difficulty.

        Returns:
            List of mission dicts sorted by difficulty.
        """
        with self._lock:
            result = []
            for m in self._missions.values():
                if m.status != MissionStatus.AVAILABLE:
                    continue
                if location and m.location.upper() != location.upper():
                    continue
                if mission_type and m.mission_type.value != mission_type.lower():
                    continue
                if max_difficulty and m.difficulty > max_difficulty:
                    continue
                result.append(m.to_dict())
            return sorted(result, key=lambda x: x["difficulty"])

    def list_active(self) -> List[Dict[str, Any]]:
        """Return all active (accepted) missions."""
        with self._lock:
            return [m.to_dict() for m in self._missions.values()
                    if m.status == MissionStatus.ACTIVE]

    def list_completed(self) -> List[Dict[str, Any]]:
        """Return completed and failed missions."""
        with self._lock:
            return [m.to_dict() for m in self._missions.values()
                    if m.status in (MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.ABANDONED)]

    def get_status(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """Return mission status dict."""
        m = self._missions.get(mission_id)
        return m.to_dict() if m else None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def accept(self, mission_id: str) -> Dict[str, Any]:
        """Accept an available mission.

        Args:
            mission_id: Mission to accept.

        Returns:
            Dict with success flag and message.
        """
        with self._lock:
            m = self._missions.get(mission_id)
            if not m:
                return {"success": False, "message": f"Mission {mission_id} not found."}
            if m.status != MissionStatus.AVAILABLE:
                return {"success": False, "message": f"Mission is {m.status.value}, not available."}
            m.status = MissionStatus.ACTIVE
            m.started_at = time.time()
        self._save()
        self._fire_event("mission_accepted", mission_id, m.title)
        logger.info("Mission accepted: %s", mission_id)
        return {"success": True, "message": f"Mission '{m.title}' accepted. Good luck.", "mission": m.to_dict()}

    def complete_objective(self, mission_id: str, objective_id: str) -> Dict[str, Any]:
        """Mark a single objective as completed.

        Args:
            mission_id: Parent mission ID.
            objective_id: Objective to mark done.

        Returns:
            Dict with success flag and updated progress.
        """
        with self._lock:
            m = self._missions.get(mission_id)
            if not m or m.status != MissionStatus.ACTIVE:
                return {"success": False, "message": "Mission not found or not active."}
            obj = next((o for o in m.objectives if o.id == objective_id), None)
            if not obj:
                return {"success": False, "message": f"Objective {objective_id} not found."}
            obj.completed = True
            progress = m.progress
        self._save()
        return {"success": True, "objective": objective_id, "progress": progress}

    def complete(self, mission_id: str, notes: str = "") -> Dict[str, Any]:
        """Complete a mission and grant rewards.

        Validates all required objectives are done, applies credits/xp/
        reputation/items to PlayerState, adjusts faction standings, then
        fires a ``mission_complete`` event.

        Args:
            mission_id: Mission to complete.
            notes: Optional agent/player outcome notes.

        Returns:
            Dict with success flag, rewards granted, and updated mission.
        """
        with self._lock:
            m = self._missions.get(mission_id)
            if not m:
                return {"success": False, "message": f"Mission {mission_id} not found."}
            if m.status != MissionStatus.ACTIVE:
                return {"success": False, "message": f"Mission not active (status: {m.status.value})."}
            if not m.is_complete:
                missing = [o.description for o in m.objectives if not o.completed and not o.optional]
                return {"success": False, "message": f"Incomplete objectives: {', '.join(missing)}"}
            m.status = MissionStatus.COMPLETED
            m.completed_at = time.time()
            m.notes = notes

        self._apply_rewards(m)
        self._save()
        self._fire_event("mission_complete", mission_id, m.title)
        logger.info("Mission completed: %s", mission_id)
        return {
            "success": True,
            "message": f"Mission '{m.title}' complete. Rewards applied.",
            "rewards": m.reward.to_dict(),
            "mission": m.to_dict(),
        }

    def abandon(self, mission_id: str) -> Dict[str, Any]:
        """Abandon an active mission (minor rep penalty).

        Args:
            mission_id: Mission to abandon.

        Returns:
            Dict with success flag and message.
        """
        with self._lock:
            m = self._missions.get(mission_id)
            if not m or m.status != MissionStatus.ACTIVE:
                return {"success": False, "message": "Mission not found or not active."}
            m.status = MissionStatus.ABANDONED
            m.completed_at = time.time()

        # Minor rep penalty
        try:
            get_player_state().adjust_reputation(-3, reason=f"abandoned:{mission_id}")
        except Exception as e:
            logger.debug("[MissionManager] Rep penalty failed (operation=abandon): %s", e)

        self._save()
        self._fire_event("mission_abandoned", mission_id, m.title)
        return {"success": True, "message": f"Abandoned '{m.title}'. -3 rep."}

    def fail(self, mission_id: str, reason: str = "") -> Dict[str, Any]:
        """Fail an active mission.

        Args:
            mission_id: Mission to fail.
            reason: Optional failure reason.

        Returns:
            Dict with success flag.
        """
        with self._lock:
            m = self._missions.get(mission_id)
            if not m or m.status != MissionStatus.ACTIVE:
                return {"success": False, "message": "Mission not active."}
            m.status = MissionStatus.FAILED
            m.completed_at = time.time()
            m.notes = reason

        # Rep penalty scales with difficulty
        try:
            get_player_state().adjust_reputation(-(m.difficulty * 3), reason=f"failed:{mission_id}")
        except Exception as e:
            logger.debug("[MissionManager] Rep penalty failed (operation=fail): %s", e)

        self._save()
        self._fire_event("mission_failed", mission_id, m.title)
        return {"success": True, "message": f"Mission '{m.title}' failed. {reason}"}

    # v1.52.0 [2026-03-22] — Time-limited mission auto-fail enforcement
    # CONNECTS: MissionStatus.ACTIVE, time_limit, started_at
    # CALLED BY: NeonCity crew poll loop, or any periodic check

    def check_expired(self) -> List[Dict[str, Any]]:
        """Check all active missions for time limit expiry and auto-fail expired ones.

        Returns:
            List of dicts describing missions that were auto-failed.
        """
        failed: List[Dict[str, Any]] = []
        now = time.time()

        with self._lock:
            active = [m for m in self._missions.values()
                       if m.status == MissionStatus.ACTIVE
                       and m.time_limit is not None
                       and m.started_at is not None]

        for m in active:
            # time_limit is in game minutes; 1 real minute = 1 game hour (60 game min)
            # So time_limit game minutes = time_limit real seconds
            elapsed_secs = now - m.started_at
            limit_secs = m.time_limit * 60  # convert game minutes to real seconds
            if elapsed_secs >= limit_secs:
                result = self.fail(m.id, reason=f"Time expired ({m.time_limit} min limit)")
                if result.get("success"):
                    failed.append({
                        "mission_id": m.id,
                        "title": m.title,
                        "time_limit": m.time_limit,
                        "message": result.get("message", ""),
                    })
                    logger.info("Mission auto-failed (expired): %s (%d min limit)",
                                m.title, m.time_limit)

        return failed

    def assign_crew(self, mission_id: str, crew_ids: List[str]) -> Dict[str, Any]:
        """Assign crew members to an active mission.

        Args:
            mission_id: Target mission.
            crew_ids: List of crew member IDs to assign.

        Returns:
            Dict with success flag and updated assigned_crew list.
        """
        with self._lock:
            m = self._missions.get(mission_id)
            if not m or m.status != MissionStatus.ACTIVE:
                return {"success": False, "message": "Mission not found or not active."}
            m.assigned_crew = list(set(m.assigned_crew + crew_ids))

        self._save()
        return {"success": True, "assigned_crew": m.assigned_crew}

    # ── Custom Mission Creation ───────────────────────────────────────────

    def create(
        self,
        title: str,
        description: str,
        mission_type: str,
        giver_npc: str,
        location: str,
        difficulty: int = 2,
        reward_credits: int = 1000,
        reward_xp: int = 50,
        time_limit: Optional[int] = None,
        objectives: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new custom mission and add it to the board.

        Args:
            title: Mission name.
            description: Full mission description.
            mission_type: One of recon/heist/deal/extraction/hit.
            giver_npc: NPC who is offering the mission.
            location: Primary scene location.
            difficulty: 1–5.
            reward_credits: Credits granted on completion.
            reward_xp: XP granted on completion.
            time_limit: Optional in-game time limit in minutes.
            objectives: List of objective descriptions (plain text).

        Returns:
            Dict with success and new mission dict.
        """
        try:
            mt = MissionType(mission_type.lower())
        except ValueError:
            return {"success": False, "message": f"Unknown mission type: {mission_type}"}

        mission_id = f"custom_{uuid.uuid4().hex[:8]}"
        objs = [
            MissionObjective(id=f"obj_{i}", description=o)
            for i, o in enumerate(objectives or ["Complete the mission"])
        ]
        m = Mission(
            id=mission_id,
            title=title,
            description=description,
            mission_type=mt,
            giver_npc=giver_npc,
            location=location,
            difficulty=max(1, min(5, int(difficulty))),
            time_limit=time_limit,
            reward=MissionReward(credits=reward_credits, xp=reward_xp),
            objectives=objs,
        )
        with self._lock:
            self._missions[mission_id] = m
        self._save()
        return {"success": True, "mission_id": mission_id, "mission": m.to_dict()}

    # ── Rewards ───────────────────────────────────────────────────────────

    def _apply_rewards(self, m: Mission) -> None:
        """Apply mission rewards to PlayerState."""
        r = m.reward
        try:
            ps = get_player_state()
            if r.credits:
                ps.earn_credits(r.credits, reason=f"mission:{m.id}")
            if r.xp:
                ps.add_xp(r.xp, reason=f"mission:{m.id}")
            if r.reputation:
                ps.adjust_reputation(r.reputation, reason=f"mission:{m.id}")
            if r.faction and r.faction_rep:
                ps.adjust_faction(r.faction, r.faction_rep)
        except Exception as exc:
            logger.warning("MissionManager: reward apply error: %s", exc)

        # Add item rewards to inventory
        if r.items:
            try:
                from engine.world.inventory import get_inventory
                inv = get_inventory()
                for item_id in r.items:
                    inv.add_item(item_id, auto_equip=False)
            except Exception as exc:
                logger.warning("MissionManager: inventory reward error: %s", exc)

    # ── Events ────────────────────────────────────────────────────────────

    def _fire_event(self, event_type: str, mission_id: str, title: str) -> None:
        try:
            from engine.world.event_cascade import get_event_cascade
            get_event_cascade().fire(event_type, {
                "mission_id": mission_id,
                "title": title,
                "timestamp": time.time(),
            })
        except Exception as exc:
            logger.debug("MissionManager: event fire failed: %s", exc)

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Full board snapshot."""
        with self._lock:
            return {
                "available": [m.to_dict() for m in self._missions.values() if m.status == MissionStatus.AVAILABLE],
                "active": [m.to_dict() for m in self._missions.values() if m.status == MissionStatus.ACTIVE],
                "completed": [m.to_dict() for m in self._missions.values()
                              if m.status in (MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.ABANDONED)],
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_MISSION_MANAGER: Optional[MissionManager] = None
_MANAGER_LOCK = threading.Lock()


def get_mission_manager() -> MissionManager:
    """Return the MissionManager singleton."""
    global _MISSION_MANAGER
    if _MISSION_MANAGER is None:
        with _MANAGER_LOCK:
            if _MISSION_MANAGER is None:
                _MISSION_MANAGER = MissionManager()
    return _MISSION_MANAGER


def reset_mission_manager() -> None:
    """Reset the singleton — for tests only."""
    global _MISSION_MANAGER
    with _MANAGER_LOCK:
        _MISSION_MANAGER = None
