"""
Heist game logic — state, phases, crew, and vault mechanics.

The heist progresses through 4 phases:
  PLANNING  → crew discusses strategy, assigns roles
  APPROACH  → crew moves to target, overcomes obstacles
  EXECUTION → the break-in itself, skill checks, complications
  ESCAPE    → getaway with the loot (or not)

Each crew member has a specialty that determines what actions they can
perform effectively.  The game tracks suspicion (0–100), crew morale,
loot gathered, and complications encountered.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class Phase(str, Enum):
    PLANNING = "planning"
    APPROACH = "approach"
    EXECUTION = "execution"
    ESCAPE = "escape"
    COMPLETE = "complete"
    FAILED = "failed"


class Specialty(str, Enum):
    HACKER = "hacker"
    MUSCLE = "muscle"
    TALKER = "talker"
    DRIVER = "driver"
    WILDCARD = "wildcard"


# Skill checks: specialty → action → base success chance
SKILL_TABLE = {
    Specialty.HACKER: {
        "disable_alarm": 0.90, "crack_safe": 0.85, "loop_cameras": 0.90,
        "hack_door": 0.80, "jam_comms": 0.75, "distract": 0.40,
        "fight": 0.25, "drive": 0.35, "persuade": 0.30,
    },
    Specialty.MUSCLE: {
        "fight": 0.90, "breach_door": 0.85, "intimidate": 0.80,
        "carry_loot": 0.95, "distract": 0.50, "disable_alarm": 0.20,
        "crack_safe": 0.15, "persuade": 0.40, "drive": 0.50,
    },
    Specialty.TALKER: {
        "persuade": 0.90, "distract": 0.85, "bribe": 0.80,
        "impersonate": 0.75, "negotiate": 0.90, "fight": 0.20,
        "crack_safe": 0.15, "disable_alarm": 0.20, "drive": 0.40,
    },
    Specialty.DRIVER: {
        "drive": 0.95, "scout": 0.80, "getaway": 0.90,
        "distract": 0.60, "fight": 0.50, "persuade": 0.35,
        "crack_safe": 0.15, "disable_alarm": 0.30, "breach_door": 0.40,
    },
    Specialty.WILDCARD: {
        "improvise": 0.75, "distract": 0.70, "fight": 0.55,
        "persuade": 0.55, "drive": 0.55, "crack_safe": 0.45,
        "disable_alarm": 0.50, "scout": 0.60, "hack_door": 0.40,
    },
}

# Complication templates per phase
COMPLICATIONS = {
    Phase.PLANNING: [
        "A crew member has a personal grudge against the target.",
        "Intel was wrong — the vault has been upgraded.",
        "An undercover cop is asking questions nearby.",
        "The target changed their routine.",
    ],
    Phase.APPROACH: [
        "A patrol spotted you. Quick — hide or bluff!",
        "The entrance is blocked by construction.",
        "Security cameras have thermal imaging.",
        "A civilian is lingering near the entry point.",
        "It starts raining — visibility drops but so does guard alertness.",
    ],
    Phase.EXECUTION: [
        "The safe has a secondary biometric lock!",
        "A silent alarm was triggered. Clock is ticking.",
        "The vault contains decoy items. Which is real?",
        "A guard is on an unexpected break inside the vault room.",
        "Power fluctuation — cameras might reboot any second.",
        "You hear sirens in the distance. Coincidence or response?",
    ],
    Phase.ESCAPE: [
        "Police roadblock ahead!",
        "The getaway car won't start.",
        "Spike strips on the backup route.",
        "A helicopter is circling overhead.",
        "The crew is arguing about splitting the loot.",
    ],
}

# Venue templates
VENUES = {
    "diamond_exchange": {
        "name": "The Diamond Exchange",
        "difficulty": "medium",
        "base_suspicion": 15,
        "loot_value": 500_000,
        "guards": 4,
        "obstacles": ["laser_grid", "biometric_door", "vault_combination"],
    },
    "art_museum": {
        "name": "National Art Museum",
        "difficulty": "hard",
        "base_suspicion": 25,
        "loot_value": 2_000_000,
        "guards": 8,
        "obstacles": ["pressure_plates", "motion_sensors", "guard_rotation", "glass_case"],
    },
    "tech_lab": {
        "name": "Nexus Tech Labs",
        "difficulty": "easy",
        "base_suspicion": 10,
        "loot_value": 200_000,
        "guards": 2,
        "obstacles": ["keycard_door", "server_room_lock"],
    },
    "casino_vault": {
        "name": "The Golden Serpent Casino",
        "difficulty": "extreme",
        "base_suspicion": 30,
        "loot_value": 5_000_000,
        "guards": 12,
        "obstacles": ["cage_walk", "vault_door", "laser_hallway", "counting_room", "panic_room"],
    },
}


@dataclass
class CrewMember:
    """A member of the heist crew."""
    char_id: str
    name: str
    specialty: Specialty
    health: int = 100
    morale: int = 75
    arrested: bool = False
    injured: bool = False
    skill_uses: int = 0

    def success_chance(self, action: str) -> float:
        """Get success probability for an action based on specialty."""
        table = SKILL_TABLE.get(self.specialty, {})
        base = table.get(action, 0.35)
        # Morale modifier: ±15%
        morale_mod = (self.morale - 50) / 333.0
        # Injury penalty
        injury_mod = -0.20 if self.injured else 0.0
        return max(0.05, min(0.98, base + morale_mod + injury_mod))


@dataclass
class HeistState:
    """Full state of an active heist."""
    heist_id: str = ""
    venue_key: str = "diamond_exchange"
    phase: Phase = Phase.PLANNING
    turn: int = 0

    crew: Dict[str, CrewMember] = field(default_factory=dict)

    # Meters
    suspicion: int = 15          # 0–100; ≥100 = busted
    loot_collected: int = 0      # dollar value
    loot_target: int = 500_000
    time_pressure: int = 0       # increases each turn during execution
    obstacles_cleared: List[str] = field(default_factory=list)
    obstacles_remaining: List[str] = field(default_factory=list)

    # History
    events: List[Dict[str, Any]] = field(default_factory=list)
    complications: List[str] = field(default_factory=list)

    # Timestamps
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0

    @classmethod
    def new_heist(cls, venue_key: str = "diamond_exchange", heist_id: str = "") -> "HeistState":
        venue = VENUES.get(venue_key, VENUES["diamond_exchange"])
        return cls(
            heist_id=heist_id or f"heist_{int(time.time())}",
            venue_key=venue_key,
            suspicion=venue["base_suspicion"],
            loot_target=venue["loot_value"],
            obstacles_remaining=list(venue["obstacles"]),
        )

    def add_crew(self, char_id: str, name: str, specialty: str) -> CrewMember:
        spec = Specialty(specialty) if specialty in [s.value for s in Specialty] else Specialty.WILDCARD
        member = CrewMember(char_id=char_id, name=name, specialty=spec)
        self.crew[char_id] = member
        return member

    def advance_phase(self) -> Phase:
        """Move to the next phase."""
        order = [Phase.PLANNING, Phase.APPROACH, Phase.EXECUTION, Phase.ESCAPE, Phase.COMPLETE]
        idx = order.index(self.phase) if self.phase in order else 0
        if idx < len(order) - 1:
            self.phase = order[idx + 1]
            self._add_event("phase_change", f"Phase advanced to {self.phase.value}")
        return self.phase

    def perform_action(self, char_id: str, action: str, **kwargs) -> Dict[str, Any]:
        """Resolve a crew member's action with skill check."""
        member = self.crew.get(char_id)
        if not member or member.arrested:
            return {"success": False, "message": "Crew member unavailable."}

        chance = member.success_chance(action)
        roll = random.random()
        success = roll < chance
        member.skill_uses += 1

        # Suspicion change
        susp_delta = random.randint(-2, 3) if success else random.randint(5, 15)
        self.suspicion = max(0, min(100, self.suspicion + susp_delta))

        result = {
            "success": success,
            "action": action,
            "character": member.name,
            "roll": round(roll, 3),
            "needed": round(chance, 3),
            "suspicion_delta": susp_delta,
            "suspicion": self.suspicion,
        }

        if success:
            result["message"] = f"{member.name} successfully performed {action}!"
            member.morale = min(100, member.morale + 5)
            # Clear obstacle if applicable
            if action in ("disable_alarm", "crack_safe", "hack_door", "breach_door"):
                cleared = self._try_clear_obstacle(action)
                if cleared:
                    result["obstacle_cleared"] = cleared
        else:
            result["message"] = f"{member.name} failed at {action}!"
            member.morale = max(0, member.morale - 8)
            # Chance of injury on combat failure
            if action in ("fight", "breach_door") and random.random() < 0.3:
                member.injured = True
                result["injury"] = True

        self._add_event(action, result["message"], data=result)
        self.turn += 1

        # Time pressure increases during execution
        if self.phase in (Phase.EXECUTION, Phase.ESCAPE):
            self.time_pressure += random.randint(3, 8)

        return result

    def maybe_complication(self) -> Optional[str]:
        """Roll for a random complication (30% chance per turn)."""
        if random.random() > 0.30:
            return None
        pool = COMPLICATIONS.get(self.phase, [])
        if not pool:
            return None
        comp = random.choice(pool)
        self.complications.append(comp)
        self._add_event("complication", comp)
        return comp

    def collect_loot(self, amount: int) -> int:
        """Add loot to the haul."""
        self.loot_collected += amount
        self._add_event("loot", f"Collected ${amount:,} in loot")
        return self.loot_collected

    def check_bust(self) -> bool:
        """Check if the crew is busted (suspicion ≥ 100)."""
        if self.suspicion >= 100:
            self.phase = Phase.FAILED
            self.ended_at = time.time()
            self._add_event("bust", "BUSTED! Suspicion maxed out!")
            return True
        return False

    def check_victory(self) -> bool:
        """Check if heist succeeded (all obstacles cleared + escaped)."""
        if self.phase == Phase.ESCAPE and not self.obstacles_remaining:
            self.phase = Phase.COMPLETE
            self.ended_at = time.time()
            self._add_event("victory", f"Heist complete! Loot: ${self.loot_collected:,}")
            return True
        return False

    def _try_clear_obstacle(self, action: str) -> Optional[str]:
        """Try to clear the next obstacle matching the action."""
        action_map = {
            "disable_alarm": ["laser_grid", "motion_sensors"],
            "crack_safe": ["vault_combination", "server_room_lock", "vault_door"],
            "hack_door": ["keycard_door", "biometric_door", "counting_room"],
            "breach_door": ["keycard_door", "glass_case", "panic_room"],
        }
        clearable = action_map.get(action, [])
        for obs in clearable:
            if obs in self.obstacles_remaining:
                self.obstacles_remaining.remove(obs)
                self.obstacles_cleared.append(obs)
                return obs
        return None

    def _add_event(self, event_type: str, message: str, data: Optional[Dict] = None):
        self.events.append({
            "type": event_type,
            "message": message,
            "turn": self.turn,
            "phase": self.phase.value,
            "timestamp": time.time(),
            "data": data,
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "heist_id": self.heist_id,
            "venue": VENUES.get(self.venue_key, {}),
            "venue_key": self.venue_key,
            "phase": self.phase.value,
            "turn": self.turn,
            "crew": {k: asdict(v) for k, v in self.crew.items()},
            "suspicion": self.suspicion,
            "loot_collected": self.loot_collected,
            "loot_target": self.loot_target,
            "time_pressure": self.time_pressure,
            "obstacles_cleared": self.obstacles_cleared,
            "obstacles_remaining": self.obstacles_remaining,
            "events": self.events[-20:],  # last 20
            "complications": self.complications,
            "is_active": self.phase not in (Phase.COMPLETE, Phase.FAILED),
        }

    def crew_summary(self) -> str:
        """Text summary for LLM context injection."""
        lines = []
        for m in self.crew.values():
            status = "arrested" if m.arrested else ("injured" if m.injured else "ok")
            lines.append(
                f"  {m.name} ({m.specialty.value}) — "
                f"health:{m.health} morale:{m.morale} status:{status}"
            )
        return "\n".join(lines) or "No crew assigned."

    def situation_summary(self) -> str:
        """Full situation text for LLM prompts."""
        venue = VENUES.get(self.venue_key, {})
        return (
            f"HEIST: {venue.get('name', self.venue_key)}\n"
            f"Phase: {self.phase.value} | Turn: {self.turn}\n"
            f"Suspicion: {self.suspicion}/100 | Time pressure: {self.time_pressure}\n"
            f"Loot: ${self.loot_collected:,} / ${self.loot_target:,}\n"
            f"Obstacles remaining: {', '.join(self.obstacles_remaining) or 'none'}\n"
            f"Obstacles cleared: {', '.join(self.obstacles_cleared) or 'none'}\n"
            f"Crew:\n{self.crew_summary()}"
        )
