"""Skill progression system for CosySim v1.0 "NeonCity 2".

Replaces the flat 0–5 skill levels in PlayerState with a rich use-based
progression system featuring XP, diminishing returns, skill checks with
dice rolls, and unlock gating.

Skills
------
8 skills carried over from PlayerState:
- hacking, combat, stealth, social, tech, driving, medicine, trading

Each skill tracks cumulative XP.  Gaining XP follows a diminishing-returns
curve — early levels come fast, mastery takes sustained effort.

Level Thresholds
~~~~~~~~~~~~~~~~
::

    Level 0: 0 XP      (Untrained)
    Level 1: 100 XP    (Novice)
    Level 2: 300 XP    (Competent)
    Level 3: 600 XP    (Skilled)
    Level 4: 1000 XP   (Expert)
    Level 5: 2000 XP   (Master)

Skill Checks
~~~~~~~~~~~~~
Roll-based system inspired by d20:

    effective = skill_level * 4 + modifier
    roll = random(1, 20)
    success = (roll + effective) >= difficulty

Difficulties: Trivial=5, Easy=8, Medium=12, Hard=16, Very Hard=20, Legendary=25

Player Level
~~~~~~~~~~~~
Global level 1–50 computed from total XP across all skills.

Usage::

    from engine.world.skill_progression import get_skill_manager

    mgr = get_skill_manager()
    mgr.award_xp("hacking", 25, reason="breached firewall")
    result = mgr.skill_check("hacking", difficulty=16)
    if result.success:
        print(f"Hacked! Roll {result.roll} + {result.effective} = {result.total}")
"""
from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ──── Event bus (optional) ────

try:
    from engine.events.event_bus import get_event_bus as _get_event_bus
    _HAS_EVENT_BUS: bool = True
except ImportError:  # pragma: no cover
    _get_event_bus = lambda: None  # type: ignore[assignment]
    _HAS_EVENT_BUS = False

# ──── Constants ────

SKILL_NAMES: List[str] = [
    "hacking",
    "combat",
    "stealth",
    "social",
    "tech",
    "driving",
    "medicine",
    "trading",
]

SKILL_DESCRIPTIONS: Dict[str, str] = {
    "hacking": "Cyberspace infiltration, ICE breaking, data extraction",
    "combat": "Physical combat, weapon proficiency, tactical awareness",
    "stealth": "Sneaking, lockpicking, silent movement, disguise",
    "social": "Persuasion, deception, intimidation, negotiation",
    "tech": "Hardware repair, weapon modding, cyberdeck building",
    "driving": "Vehicle operation, pursuit, evasion, racing",
    "medicine": "Field medicine, stim application, trauma care",
    "trading": "Negotiation, market analysis, deal-making, fencing",
}

SKILL_ICONS: Dict[str, str] = {
    "hacking": "💻",
    "combat": "⚔️",
    "stealth": "🥷",
    "social": "🎭",
    "tech": "🔧",
    "driving": "🚗",
    "medicine": "🩺",
    "trading": "💰",
}

# XP thresholds for levels 0–5
LEVEL_THRESHOLDS: List[int] = [0, 100, 300, 600, 1000, 2000]
MAX_SKILL_LEVEL: int = 5

# Player global level thresholds (1–50)
# Total XP across all skills maps to global level
# Each global level requires progressively more total XP
GLOBAL_LEVEL_XP: List[int] = [
    0,     # Level 1
    50,    # Level 2
    150,   # Level 3
    300,   # Level 4
    500,   # Level 5
    800,   # ...
    1200,
    1700,
    2300,
    3000,  # Level 10
    3800,
    4700,
    5700,
    6800,
    8000,  # Level 15
    9500,
    11200,
    13100,
    15200,
    17500,  # Level 20
    20000,
    22800,
    25900,
    29300,
    33000,  # Level 25
    37000,
    41400,
    46200,
    51400,
    57000,  # Level 30
    63000,
    69500,
    76500,
    84000,
    92000,  # Level 35
    100500,
    109500,
    119000,
    129000,
    140000,  # Level 40
    152000,
    165000,
    179000,
    194000,
    210000,  # Level 45
    228000,
    248000,
    270000,
    295000,
    325000,  # Level 50
]
MAX_GLOBAL_LEVEL: int = 50

# Difficulty tiers
DIFFICULTY_TIERS: Dict[str, int] = {
    "trivial": 5,
    "easy": 8,
    "medium": 12,
    "hard": 16,
    "very_hard": 20,
    "legendary": 25,
    "impossible": 30,
}

# XP multiplier per difficulty (harder tasks reward more)
DIFFICULTY_XP_MULTIPLIER: Dict[str, float] = {
    "trivial": 0.25,
    "easy": 0.5,
    "medium": 1.0,
    "hard": 1.5,
    "very_hard": 2.0,
    "legendary": 3.0,
    "impossible": 5.0,
}

# Diminishing returns curve: XP gain is reduced based on current level
# At level 0, full XP. At level 5, only 20% of base XP.
DIMINISHING_RETURNS: Dict[int, float] = {
    0: 1.0,
    1: 0.85,
    2: 0.65,
    3: 0.45,
    4: 0.30,
    5: 0.20,
}

# Skill unlock requirements (skill → min_level needed for specific actions)
SKILL_UNLOCKS: Dict[str, Dict[str, int]] = {
    "hacking": {
        "basic_scan": 0,
        "breach_ice_1": 1,
        "breach_ice_2": 2,
        "breach_ice_3": 3,
        "data_extraction": 2,
        "backdoor_install": 3,
        "black_ice_counter": 4,
        "zero_day_exploit": 5,
    },
    "combat": {
        "basic_attack": 0,
        "dual_wield": 1,
        "counter_attack": 2,
        "precise_strike": 3,
        "weapon_mastery": 4,
        "lethal_combo": 5,
    },
    "stealth": {
        "sneak": 0,
        "lockpick_basic": 1,
        "disguise": 2,
        "silent_takedown": 3,
        "ghost_mode": 4,
        "phantom": 5,
    },
    "social": {
        "small_talk": 0,
        "persuade": 1,
        "intimidate": 2,
        "deceive": 3,
        "manipulate": 4,
        "mind_game": 5,
    },
    "tech": {
        "basic_repair": 0,
        "weapon_mod": 1,
        "cyberdeck_build": 2,
        "implant_install": 3,
        "prototype_craft": 4,
        "masterwork": 5,
    },
    "driving": {
        "basic_drive": 0,
        "pursuit": 1,
        "evasion": 2,
        "stunt_driving": 3,
        "racing": 4,
        "ace_pilot": 5,
    },
    "medicine": {
        "first_aid": 0,
        "stim_application": 1,
        "trauma_care": 2,
        "surgery": 3,
        "cybernetic_integration": 4,
        "resurrection_protocol": 5,
    },
    "trading": {
        "haggle": 0,
        "fence_goods": 1,
        "market_analysis": 2,
        "black_market_access": 3,
        "cartel_connections": 4,
        "market_manipulation": 5,
    },
}


# ============================================================================
# Data classes
# ============================================================================

@dataclass
class SkillState:
    """State of a single skill."""

    name: str
    xp: int = 0
    level: int = 0
    uses: int = 0
    last_used: float = 0.0
    xp_history: List[Dict[str, Any]] = field(default_factory=list)

    def compute_level(self) -> int:
        """Compute level from current XP.

        Returns:
            Skill level 0–5.
        """
        level = 0
        for i, threshold in enumerate(LEVEL_THRESHOLDS):
            if self.xp >= threshold:
                level = i
        self.level = min(level, MAX_SKILL_LEVEL)
        return self.level

    def xp_to_next_level(self) -> Optional[int]:
        """Calculate XP needed for next level.

        Returns:
            XP remaining, or None if at max level.
        """
        if self.level >= MAX_SKILL_LEVEL:
            return None
        next_threshold = LEVEL_THRESHOLDS[self.level + 1]
        return max(0, next_threshold - self.xp)

    def progress_to_next(self) -> float:
        """Calculate progress percentage toward next level.

        Returns:
            Float 0.0–1.0 representing progress.
        """
        if self.level >= MAX_SKILL_LEVEL:
            return 1.0
        current_threshold = LEVEL_THRESHOLDS[self.level]
        next_threshold = LEVEL_THRESHOLDS[self.level + 1]
        span = next_threshold - current_threshold
        if span <= 0:
            return 1.0
        progress = (self.xp - current_threshold) / span
        return max(0.0, min(1.0, progress))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "xp": self.xp,
            "level": self.level,
            "uses": self.uses,
            "last_used": self.last_used,
            "xp_history": self.xp_history[-15:],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SkillState:
        """Reconstruct from dictionary."""
        state = cls(name=data["name"])
        state.xp = data.get("xp", 0)
        state.uses = data.get("uses", 0)
        state.last_used = data.get("last_used", 0.0)
        state.xp_history = data.get("xp_history", [])
        state.compute_level()
        return state


@dataclass
class SkillCheckResult:
    """Result of a skill check roll."""

    skill: str
    level: int
    roll: int              # Raw d20 roll (1–20)
    effective: int         # skill_level * 4 + modifier
    total: int             # roll + effective
    difficulty: int
    difficulty_name: str
    success: bool
    critical: bool         # Natural 20 or natural 1
    margin: int            # total - difficulty (positive = excess, negative = shortfall)
    xp_awarded: int        # XP gained from the attempt

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "skill": self.skill,
            "level": self.level,
            "roll": self.roll,
            "effective": self.effective,
            "total": self.total,
            "difficulty": self.difficulty,
            "difficulty_name": self.difficulty_name,
            "success": self.success,
            "critical": self.critical,
            "margin": self.margin,
            "xp_awarded": self.xp_awarded,
        }

    def narrative(self) -> str:
        """Generate a narrative description of the check result.

        Returns:
            Human-readable description suitable for game output.
        """
        icon = SKILL_ICONS.get(self.skill, "🎯")
        if self.critical and self.roll == 20:
            return (
                f"{icon} CRITICAL SUCCESS! {self.skill.title()} check "
                f"(rolled nat 20 + {self.effective} = {self.total} vs DC {self.difficulty}). "
                f"Flawless execution! +{self.xp_awarded} XP"
            )
        if self.critical and self.roll == 1:
            return (
                f"{icon} CRITICAL FAILURE! {self.skill.title()} check "
                f"(rolled nat 1 + {self.effective} = {self.total} vs DC {self.difficulty}). "
                f"Complete disaster! +{self.xp_awarded} XP"
            )
        if self.success:
            return (
                f"{icon} SUCCESS: {self.skill.title()} check "
                f"(rolled {self.roll} + {self.effective} = {self.total} vs DC {self.difficulty}, "
                f"margin +{self.margin}). +{self.xp_awarded} XP"
            )
        return (
            f"{icon} FAILED: {self.skill.title()} check "
            f"(rolled {self.roll} + {self.effective} = {self.total} vs DC {self.difficulty}, "
            f"shortfall {abs(self.margin)}). +{self.xp_awarded} XP"
        )


# ============================================================================
# SkillManager — singleton
# ============================================================================

_SAVE_DIR = Path("data")
_SAVE_FILE = "skill_progression.json"


class SkillManager:
    """Central manager for the player's skill progression system.

    Thread-safe singleton.  Manages XP, levels, skill checks, and unlocks.
    Integrates with PlayerState's existing skill system by replacing the
    flat 0–5 level with a rich XP-backed progression.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._skills: Dict[str, SkillState] = {}
        self._total_xp: int = 0
        self._global_level: int = 1
        self._check_history: List[Dict[str, Any]] = []
        self._listeners: List[Callable[[str, int, int], None]] = []
        self._load()
        self._ensure_all_skills()

    def _ensure_all_skills(self) -> None:
        """Ensure all 8 skills exist with at least default state."""
        for skill_name in SKILL_NAMES:
            if skill_name not in self._skills:
                self._skills[skill_name] = SkillState(name=skill_name)
        self._recompute_global()

    # ── XP & Leveling ──

    def award_xp(
        self,
        skill_name: str,
        base_xp: int,
        reason: str = "",
        difficulty: str = "medium",
        neuro_modifier: float = 1.0,
    ) -> Tuple[int, bool]:
        """Award XP to a skill with diminishing returns.

        Args:
            skill_name: Target skill.
            base_xp: Base XP amount before modifiers.
            reason: Description of the XP source.
            difficulty: Difficulty tier for XP multiplier.
            neuro_modifier: Neurochemistry motivation modifier (from BehaviourModifiers).

        Returns:
            Tuple of (actual_xp_awarded, did_level_up).

        Raises:
            ValueError: If skill_name is not valid.
        """
        if skill_name not in SKILL_NAMES:
            raise ValueError(f"Unknown skill '{skill_name}'. Valid: {SKILL_NAMES}")

        with self._lock:
            state = self._skills.setdefault(skill_name, SkillState(name=skill_name))
            old_level = state.level

            diff_mult = DIFFICULTY_XP_MULTIPLIER.get(difficulty, 1.0)
            dim_mult = DIMINISHING_RETURNS.get(state.level, 0.2)
            actual_xp = max(1, int(base_xp * diff_mult * dim_mult * neuro_modifier))

            state.xp += actual_xp
            state.uses += 1
            state.last_used = time.time()
            new_level = state.compute_level()

            state.xp_history.append({
                "xp": actual_xp,
                "reason": reason,
                "difficulty": difficulty,
                "timestamp": time.time(),
            })
            if len(state.xp_history) > 15:
                state.xp_history = state.xp_history[-15:]

            leveled_up = new_level > old_level
            self._total_xp = sum(s.xp for s in self._skills.values())
            self._recompute_global()

        if leveled_up:
            logger.info(
                "LEVEL UP: %s %d → %d (total XP: %d)",
                skill_name, old_level, new_level, state.xp,
            )
            if _HAS_EVENT_BUS:
                bus = _get_event_bus()
                if bus is not None:
                    bus.publish("skill_level_up", {
                        "skill": skill_name,
                        "old_level": old_level,
                        "new_level": new_level,
                        "total_xp": state.xp,
                        "global_level": self._global_level,
                    })
            for listener in self._listeners:
                try:
                    listener(skill_name, old_level, new_level)
                except Exception:
                    logger.exception("Skill listener error")

        self._save()
        return actual_xp, leveled_up

    def _recompute_global(self) -> None:
        """Recompute global player level from total XP."""
        self._total_xp = sum(s.xp for s in self._skills.values())
        level = 1
        for i, threshold in enumerate(GLOBAL_LEVEL_XP):
            if self._total_xp >= threshold:
                level = i + 1
        self._global_level = min(level, MAX_GLOBAL_LEVEL)

    # ── Skill Checks ──

    def skill_check(
        self,
        skill_name: str,
        difficulty: int = 12,
        modifier: int = 0,
        advantage: bool = False,
        disadvantage: bool = False,
        auto_xp: bool = True,
    ) -> SkillCheckResult:
        """Perform a skill check with d20 roll.

        Args:
            skill_name: Skill to check.
            difficulty: DC (difficulty class) to beat.
            modifier: Situational bonus/penalty.
            advantage: Roll twice, take higher.
            disadvantage: Roll twice, take lower.
            auto_xp: Award XP for the attempt.

        Returns:
            SkillCheckResult with all roll details.

        Raises:
            ValueError: If skill_name is not valid.
        """
        if skill_name not in SKILL_NAMES:
            raise ValueError(f"Unknown skill '{skill_name}'. Valid: {SKILL_NAMES}")

        state = self._skills.get(skill_name, SkillState(name=skill_name))

        # Roll
        roll1 = random.randint(1, 20)
        roll2 = random.randint(1, 20)
        if advantage:
            roll = max(roll1, roll2)
        elif disadvantage:
            roll = min(roll1, roll2)
        else:
            roll = roll1

        effective = state.level * 4 + modifier
        total = roll + effective
        success = total >= difficulty
        critical = roll in (1, 20)

        if critical and roll == 20:
            success = True
        elif critical and roll == 1:
            success = False

        margin = total - difficulty
        diff_name = _get_difficulty_name(difficulty)

        xp_awarded = 0
        if auto_xp:
            base_xp = 5 if success else 2
            xp_awarded, _ = self.award_xp(
                skill_name, base_xp,
                reason=f"skill_check DC{difficulty}",
                difficulty=diff_name,
            )

        result = SkillCheckResult(
            skill=skill_name,
            level=state.level,
            roll=roll,
            effective=effective,
            total=total,
            difficulty=difficulty,
            difficulty_name=diff_name,
            success=success,
            critical=critical,
            margin=margin,
            xp_awarded=xp_awarded,
        )

        with self._lock:
            self._check_history.append({
                "result": result.to_dict(),
                "timestamp": time.time(),
            })
            if len(self._check_history) > 50:
                self._check_history = self._check_history[-50:]

        if _HAS_EVENT_BUS:
            bus = _get_event_bus()
            if bus is not None:
                bus.publish("skill_check", result.to_dict())

        return result

    # ── Unlock Gating ──

    def can_use_ability(self, skill_name: str, ability_name: str) -> bool:
        """Check if the player has unlocked a specific ability.

        Args:
            skill_name: Parent skill.
            ability_name: Ability to check.

        Returns:
            True if the player's skill level meets the requirement.
        """
        unlocks = SKILL_UNLOCKS.get(skill_name, {})
        required_level = unlocks.get(ability_name)
        if required_level is None:
            return True
        return self.get_level(skill_name) >= required_level

    def get_unlocked_abilities(self, skill_name: str) -> List[str]:
        """Get all abilities the player has unlocked for a skill.

        Args:
            skill_name: Target skill.

        Returns:
            List of unlocked ability names.
        """
        level = self.get_level(skill_name)
        unlocks = SKILL_UNLOCKS.get(skill_name, {})
        return [name for name, req in unlocks.items() if level >= req]

    def get_locked_abilities(self, skill_name: str) -> List[Tuple[str, int]]:
        """Get abilities the player has NOT yet unlocked.

        Args:
            skill_name: Target skill.

        Returns:
            List of (ability_name, required_level) tuples.
        """
        level = self.get_level(skill_name)
        unlocks = SKILL_UNLOCKS.get(skill_name, {})
        return [(name, req) for name, req in unlocks.items() if level < req]

    # ── Query ──

    def get_level(self, skill_name: str) -> int:
        """Get current level for a skill.

        Args:
            skill_name: Target skill.

        Returns:
            Skill level 0–5.
        """
        state = self._skills.get(skill_name)
        return state.level if state else 0

    def get_xp(self, skill_name: str) -> int:
        """Get current XP for a skill.

        Args:
            skill_name: Target skill.

        Returns:
            Total accumulated XP.
        """
        state = self._skills.get(skill_name)
        return state.xp if state else 0

    def get_global_level(self) -> int:
        """Get the player's global level.

        Returns:
            Global level 1–50.
        """
        return self._global_level

    def get_total_xp(self) -> int:
        """Get total XP across all skills.

        Returns:
            Sum of all skill XP.
        """
        return self._total_xp

    def get_all_skills(self) -> Dict[str, Dict[str, Any]]:
        """Get serialized state for all skills.

        Returns:
            Dict of skill_name → skill state dict.
        """
        with self._lock:
            return {name: state.to_dict() for name, state in self._skills.items()}

    def get_skill_summary(self) -> str:
        """Generate a compact summary for LLM prompt injection.

        Returns:
            Multi-line skill summary string.
        """
        lines = [f"[PLAYER SKILLS — Level {self._global_level}]"]
        for name in SKILL_NAMES:
            state = self._skills.get(name, SkillState(name=name))
            icon = SKILL_ICONS.get(name, "🎯")
            bar = "█" * state.level + "░" * (MAX_SKILL_LEVEL - state.level)
            progress = state.progress_to_next()
            remaining = state.xp_to_next_level()
            if remaining is not None:
                lines.append(
                    f"  {icon} {name}: {bar} Lv{state.level} "
                    f"({state.xp}xp, {progress:.0%} → Lv{state.level + 1})"
                )
            else:
                lines.append(f"  {icon} {name}: {bar} Lv{state.level} (MASTERED)")
        return "\n".join(lines)

    def get_check_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent skill check history.

        Args:
            limit: Maximum number of entries.

        Returns:
            List of recent check results.
        """
        return self._check_history[-limit:]

    # ── Listeners ──

    def add_listener(self, callback: Callable[[str, int, int], None]) -> None:
        """Register callback for level-up events.

        Callback receives (skill_name, old_level, new_level).

        Args:
            callback: Function to call on level up.
        """
        self._listeners.append(callback)

    # ── Persistence ──

    def to_dict(self) -> Dict[str, Any]:
        """Serialize full state."""
        return {
            "skills": {n: s.to_dict() for n, s in self._skills.items()},
            "total_xp": self._total_xp,
            "global_level": self._global_level,
            "check_history": self._check_history[-20:],
        }

    def _save(self) -> None:
        """Persist to JSON file."""
        try:
            _SAVE_DIR.mkdir(parents=True, exist_ok=True)
            path = _SAVE_DIR / _SAVE_FILE
            path.write_text(
                json.dumps(self.to_dict(), indent=2), encoding="utf-8"
            )
        except Exception:
            logger.exception("Failed to save skill progression")

    def _load(self) -> None:
        """Load from JSON file."""
        path = _SAVE_DIR / _SAVE_FILE
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for name, data in raw.get("skills", {}).items():
                self._skills[name] = SkillState.from_dict(data)
            self._check_history = raw.get("check_history", [])
            self._recompute_global()
            logger.info(
                "Loaded skill progression: global level %d, total XP %d",
                self._global_level, self._total_xp,
            )
        except Exception:
            logger.exception("Failed to load skill progression")


def _get_difficulty_name(dc: int) -> str:
    """Map a DC value to the closest difficulty tier name."""
    for name, threshold in sorted(DIFFICULTY_TIERS.items(), key=lambda x: x[1]):
        if dc <= threshold:
            return name
    return "legendary"


# ============================================================================
# Module-level singleton
# ============================================================================

_manager_instance: Optional[SkillManager] = None
_manager_lock = threading.Lock()


def get_skill_manager() -> SkillManager:
    """Get the singleton SkillManager instance.

    Returns:
        The global SkillManager.
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = SkillManager()
    return _manager_instance
