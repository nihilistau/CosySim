"""Territory control system for CosySim v1.0 "NeonCity 2".

Models faction control over NeonCity's 16 districts, crew headquarters,
territory missions, and faction warfare.

Each of the 6 factions controls a percentage of each district (summing
to ~100%).  Control shifts through missions, world events, crew
operations, and player actions.  Economic bonuses flow from controlled
territory — controlling a tech district boosts hacking income, etc.

Crew HQ
~~~~~~~
Players can establish a headquarters in any district, choosing from
5 room types that provide specific bonuses:

- **Barracks** — crew capacity +2
- **Armory** — combat skill checks +1
- **Lab** — hacking/tech skill checks +1
- **Vault** — passive credit income
- **Comms** — intel range, faction rep gains +20%

Territory Missions
~~~~~~~~~~~~~~~~~~
Special missions that shift district control:
- Capture: take control points from a rival faction
- Defend: protect your faction's control from attack
- Sabotage: reduce a faction's control without gaining it
- Recon: reveal hidden faction operations

Faction War
~~~~~~~~~~~
Triggered when control shifts exceed 10% in a single tick.
Affects reputation, spawns combat events, and can cascade across
adjacent districts.

Usage::

    from engine.world.territory import get_territory_manager

    mgr = get_territory_manager()
    status = mgr.get_district_control("DOWNTOWN")
    mgr.shift_control("DOWNTOWN", "Ghost_Net", +5.0, reason="completed mission")
    hq = mgr.establish_hq("TECH_DISTRICT", crew_id="alpha_squad")
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ──── Event bus (optional) ────

try:
    from engine.events.event_bus import get_event_bus as _get_event_bus
    _HAS_EVENT_BUS: bool = True
except ImportError:  # pragma: no cover
    _get_event_bus = lambda: None  # type: ignore[assignment]
    _HAS_EVENT_BUS = False

# ──── Constants ────

FACTION_NAMES: List[str] = [
    "OmniCorp",
    "NeoTech",
    "BlackMarket",
    "Ghost_Net",
    "SynthSec",
    "DeepState",
]

DISTRICT_NAMES: List[str] = [
    "DOWNTOWN",
    "COMBAT_ZONE",
    "HIGHRISE",
    "UNDERWORLD",
    "TECH_DISTRICT",
    "OUTSKIRTS",
]

# Which scenes are in each district
DISTRICT_SCENES: Dict[str, List[str]] = {
    "DOWNTOWN": ["velvet_pit", "club_noir", "obscura"],
    "COMBAT_ZONE": ["colosseum", "rusty_anchor"],
    "HIGHRISE": ["penthouse", "command_center"],
    "UNDERWORLD": ["score", "briefing_room"],
    "TECH_DISTRICT": ["lab", "grid", "arcade", "signal"],
    "OUTSKIRTS": ["shattered_throne", "neon_city", "asset_studio"],
}

# Default faction control percentages per district (must sum to ~100)
DEFAULT_CONTROL: Dict[str, Dict[str, float]] = {
    "DOWNTOWN": {
        "OmniCorp": 35.0,
        "NeoTech": 10.0,
        "BlackMarket": 25.0,
        "Ghost_Net": 5.0,
        "SynthSec": 15.0,
        "DeepState": 10.0,
    },
    "COMBAT_ZONE": {
        "OmniCorp": 10.0,
        "NeoTech": 5.0,
        "BlackMarket": 30.0,
        "Ghost_Net": 10.0,
        "SynthSec": 35.0,
        "DeepState": 10.0,
    },
    "HIGHRISE": {
        "OmniCorp": 40.0,
        "NeoTech": 25.0,
        "BlackMarket": 5.0,
        "Ghost_Net": 5.0,
        "SynthSec": 10.0,
        "DeepState": 15.0,
    },
    "UNDERWORLD": {
        "OmniCorp": 5.0,
        "NeoTech": 5.0,
        "BlackMarket": 35.0,
        "Ghost_Net": 20.0,
        "SynthSec": 10.0,
        "DeepState": 25.0,
    },
    "TECH_DISTRICT": {
        "OmniCorp": 20.0,
        "NeoTech": 35.0,
        "BlackMarket": 5.0,
        "Ghost_Net": 25.0,
        "SynthSec": 5.0,
        "DeepState": 10.0,
    },
    "OUTSKIRTS": {
        "OmniCorp": 15.0,
        "NeoTech": 10.0,
        "BlackMarket": 20.0,
        "Ghost_Net": 15.0,
        "SynthSec": 20.0,
        "DeepState": 20.0,
    },
}

# District economic specializations
DISTRICT_SPECIALIZATIONS: Dict[str, Dict[str, Any]] = {
    "DOWNTOWN": {
        "type": "entertainment",
        "bonus_skill": "social",
        "credit_multiplier": 1.2,
        "description": "Entertainment and nightlife hub — social skill bonuses",
    },
    "COMBAT_ZONE": {
        "type": "combat",
        "bonus_skill": "combat",
        "credit_multiplier": 1.0,
        "description": "Lawless fighting pits — combat skill bonuses",
    },
    "HIGHRISE": {
        "type": "corporate",
        "bonus_skill": "trading",
        "credit_multiplier": 1.5,
        "description": "Corporate towers — trading and credit bonuses",
    },
    "UNDERWORLD": {
        "type": "criminal",
        "bonus_skill": "stealth",
        "credit_multiplier": 1.3,
        "description": "Black market operations — stealth and fencing bonuses",
    },
    "TECH_DISTRICT": {
        "type": "technology",
        "bonus_skill": "hacking",
        "credit_multiplier": 1.1,
        "description": "Hacker enclaves and labs — hacking and tech bonuses",
    },
    "OUTSKIRTS": {
        "type": "frontier",
        "bonus_skill": "driving",
        "credit_multiplier": 0.8,
        "description": "Sprawl fringes — driving and exploration",
    },
}

# Faction personality traits (affects AI behaviour in faction wars)
FACTION_TRAITS: Dict[str, Dict[str, Any]] = {
    "OmniCorp": {
        "aggression": 0.6,
        "expansion_rate": 0.7,
        "diplomacy": 0.4,
        "preferred_districts": ["HIGHRISE", "DOWNTOWN"],
        "hostile_to": ["Ghost_Net", "BlackMarket"],
        "allied_with": ["NeoTech"],
        "description": "Megacorporation — controls through money and influence",
    },
    "NeoTech": {
        "aggression": 0.4,
        "expansion_rate": 0.5,
        "diplomacy": 0.7,
        "preferred_districts": ["TECH_DISTRICT", "HIGHRISE"],
        "hostile_to": ["SynthSec"],
        "allied_with": ["OmniCorp"],
        "description": "Tech innovators — controls through patents and infrastructure",
    },
    "BlackMarket": {
        "aggression": 0.7,
        "expansion_rate": 0.6,
        "diplomacy": 0.3,
        "preferred_districts": ["UNDERWORLD", "COMBAT_ZONE"],
        "hostile_to": ["OmniCorp", "SynthSec"],
        "allied_with": ["DeepState"],
        "description": "Criminal syndicate — controls through fear and black money",
    },
    "Ghost_Net": {
        "aggression": 0.3,
        "expansion_rate": 0.4,
        "diplomacy": 0.5,
        "preferred_districts": ["TECH_DISTRICT", "OUTSKIRTS"],
        "hostile_to": ["OmniCorp", "DeepState"],
        "allied_with": [],
        "description": "Hacktivist collective — controls through information",
    },
    "SynthSec": {
        "aggression": 0.8,
        "expansion_rate": 0.8,
        "diplomacy": 0.2,
        "preferred_districts": ["COMBAT_ZONE", "OUTSKIRTS"],
        "hostile_to": ["NeoTech", "BlackMarket"],
        "allied_with": [],
        "description": "Private military — controls through brute force",
    },
    "DeepState": {
        "aggression": 0.5,
        "expansion_rate": 0.5,
        "diplomacy": 0.6,
        "preferred_districts": ["UNDERWORLD", "HIGHRISE"],
        "hostile_to": ["Ghost_Net"],
        "allied_with": ["BlackMarket"],
        "description": "Shadow government — controls through manipulation",
    },
}

# HQ room types with bonuses
HQ_ROOM_TYPES: Dict[str, Dict[str, Any]] = {
    "barracks": {
        "description": "Crew quarters — increases max crew size by 2",
        "bonus": {"crew_capacity": 2},
        "cost": 2000,
        "max_level": 3,
    },
    "armory": {
        "description": "Weapons storage — combat skill checks +1 per level",
        "bonus": {"combat_modifier": 1},
        "cost": 3000,
        "max_level": 3,
    },
    "lab": {
        "description": "Tech workshop — hacking/tech skill checks +1 per level",
        "bonus": {"hacking_modifier": 1, "tech_modifier": 1},
        "cost": 3500,
        "max_level": 3,
    },
    "vault": {
        "description": "Secure vault — passive credit income per game tick",
        "bonus": {"passive_credits": 50},
        "cost": 5000,
        "max_level": 3,
    },
    "comms": {
        "description": "Communications array — faction rep gains +20% per level",
        "bonus": {"rep_multiplier": 0.2},
        "cost": 4000,
        "max_level": 3,
    },
}

# War threshold — control shift > this triggers faction war event
WAR_THRESHOLD: float = 10.0

# Control shift bounds per operation
CONTROL_SHIFT_RANGE: Tuple[float, float] = (1.0, 8.0)


# ============================================================================
# Data classes
# ============================================================================

@dataclass
class HQRoom:
    """A room in the crew's headquarters."""

    room_type: str
    level: int = 1
    built_at: float = field(default_factory=time.time)

    def get_bonus(self) -> Dict[str, float]:
        """Get the current bonus for this room at its level."""
        base = HQ_ROOM_TYPES.get(self.room_type, {}).get("bonus", {})
        return {k: v * self.level for k, v in base.items()}

    def upgrade_cost(self) -> Optional[int]:
        """Get cost to upgrade to next level, or None if maxed."""
        max_level = HQ_ROOM_TYPES.get(self.room_type, {}).get("max_level", 3)
        if self.level >= max_level:
            return None
        base_cost = HQ_ROOM_TYPES.get(self.room_type, {}).get("cost", 1000)
        return int(base_cost * (self.level + 1) * 0.8)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize."""
        return {
            "room_type": self.room_type,
            "level": self.level,
            "built_at": self.built_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> HQRoom:
        """Deserialize."""
        return cls(
            room_type=data["room_type"],
            level=data.get("level", 1),
            built_at=data.get("built_at", time.time()),
        )


@dataclass
class CrewHQ:
    """A crew's headquarters in a district."""

    crew_id: str
    district: str
    rooms: Dict[str, HQRoom] = field(default_factory=dict)
    established_at: float = field(default_factory=time.time)
    reputation_local: float = 0.0

    def get_all_bonuses(self) -> Dict[str, float]:
        """Aggregate all room bonuses."""
        total: Dict[str, float] = {}
        for room in self.rooms.values():
            for k, v in room.get_bonus().items():
                total[k] = total.get(k, 0.0) + v
        return total

    def add_room(self, room_type: str) -> bool:
        """Add a room to the HQ if not already present.

        Args:
            room_type: Type of room to build.

        Returns:
            True if built, False if already exists or invalid type.
        """
        if room_type not in HQ_ROOM_TYPES:
            return False
        if room_type in self.rooms:
            return False
        self.rooms[room_type] = HQRoom(room_type=room_type)
        return True

    def upgrade_room(self, room_type: str) -> bool:
        """Upgrade an existing room.

        Args:
            room_type: Room to upgrade.

        Returns:
            True if upgraded, False if not found or maxed.
        """
        room = self.rooms.get(room_type)
        if not room:
            return False
        max_level = HQ_ROOM_TYPES.get(room_type, {}).get("max_level", 3)
        if room.level >= max_level:
            return False
        room.level += 1
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize."""
        return {
            "crew_id": self.crew_id,
            "district": self.district,
            "rooms": {k: v.to_dict() for k, v in self.rooms.items()},
            "established_at": self.established_at,
            "reputation_local": round(self.reputation_local, 2),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CrewHQ:
        """Deserialize."""
        hq = cls(
            crew_id=data["crew_id"],
            district=data["district"],
            established_at=data.get("established_at", time.time()),
            reputation_local=data.get("reputation_local", 0.0),
        )
        for k, v in data.get("rooms", {}).items():
            hq.rooms[k] = HQRoom.from_dict(v)
        return hq


@dataclass
class TerritoryEvent:
    """Record of a territory control shift."""

    district: str
    faction: str
    delta: float
    reason: str
    timestamp: float = field(default_factory=time.time)
    triggered_war: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize."""
        return {
            "district": self.district,
            "faction": self.faction,
            "delta": round(self.delta, 2),
            "reason": self.reason,
            "timestamp": self.timestamp,
            "triggered_war": self.triggered_war,
        }


# ============================================================================
# TerritoryManager — singleton
# ============================================================================

_SAVE_DIR = Path("data")
_SAVE_FILE = "territory.json"
_MAX_EVENT_HISTORY = 100


class TerritoryManager:
    """Central manager for faction territory control.

    Thread-safe singleton.  Manages district control percentages, crew HQs,
    territory events, and faction war triggers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._control: Dict[str, Dict[str, float]] = {}
        self._hqs: Dict[str, CrewHQ] = {}
        self._event_history: List[TerritoryEvent] = []
        self._listeners: List[Callable[[TerritoryEvent], None]] = []
        self._load()
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        """Ensure all districts have control data."""
        for district in DISTRICT_NAMES:
            if district not in self._control:
                self._control[district] = dict(
                    DEFAULT_CONTROL.get(district, {f: 100.0 / len(FACTION_NAMES) for f in FACTION_NAMES})
                )
        self._normalize_all()

    def _normalize_all(self) -> None:
        """Ensure control percentages sum to 100% per district."""
        for district in self._control:
            self._normalize_district(district)

    def _normalize_district(self, district: str) -> None:
        """Normalize a single district's control to sum to 100%."""
        ctrl = self._control.get(district, {})
        total = sum(ctrl.values())
        if total <= 0:
            for f in FACTION_NAMES:
                ctrl[f] = 100.0 / len(FACTION_NAMES)
        elif abs(total - 100.0) > 0.01:
            factor = 100.0 / total
            for f in ctrl:
                ctrl[f] = max(0.0, ctrl[f] * factor)

    # ── Control Operations ──

    def get_district_control(self, district: str) -> Dict[str, float]:
        """Get faction control percentages for a district.

        Args:
            district: District name.

        Returns:
            Dict of faction → control percentage.
        """
        with self._lock:
            return dict(self._control.get(district, {}))

    def get_dominant_faction(self, district: str) -> Tuple[str, float]:
        """Get the faction with the most control in a district.

        Args:
            district: District name.

        Returns:
            (faction_name, control_percentage).
        """
        ctrl = self.get_district_control(district)
        if not ctrl:
            return ("none", 0.0)
        dominant = max(ctrl.items(), key=lambda x: x[1])
        return dominant

    def shift_control(
        self,
        district: str,
        faction: str,
        delta: float,
        reason: str = "",
        source_faction: Optional[str] = None,
    ) -> TerritoryEvent:
        """Shift faction control in a district.

        Control is taken proportionally from other factions (or a specific
        source faction).  Triggers war events if delta > WAR_THRESHOLD.

        Args:
            district: Target district.
            faction: Faction gaining (positive) or losing (negative) control.
            delta: Control percentage change.
            reason: Description of the cause.
            source_faction: If specified, take control only from this faction.

        Returns:
            TerritoryEvent recording the shift.
        """
        if district not in self._control:
            self._control[district] = dict(
                DEFAULT_CONTROL.get(district, {f: 100.0 / len(FACTION_NAMES) for f in FACTION_NAMES})
            )

        with self._lock:
            ctrl = self._control[district]

            # Clamp delta to prevent going below 0 or above 100
            current = ctrl.get(faction, 0.0)
            effective_delta = max(-current, min(100.0 - current, delta))

            if abs(effective_delta) < 0.01:
                return TerritoryEvent(
                    district=district, faction=faction,
                    delta=0.0, reason=reason,
                )

            ctrl[faction] = current + effective_delta

            # Redistribute lost/gained control among other factions
            other_factions = [f for f in FACTION_NAMES if f != faction]
            if source_faction and source_faction in other_factions:
                src_current = ctrl.get(source_faction, 0.0)
                taken = min(src_current, abs(effective_delta))
                ctrl[source_faction] = src_current - taken
                remaining = abs(effective_delta) - taken
                if remaining > 0.01 and other_factions:
                    share = remaining / len([f for f in other_factions if f != source_faction])
                    for f in other_factions:
                        if f != source_faction:
                            ctrl[f] = max(0.0, ctrl.get(f, 0.0) - share)
            elif other_factions:
                share = effective_delta / len(other_factions)
                for f in other_factions:
                    ctrl[f] = max(0.0, ctrl.get(f, 0.0) - share)

            self._normalize_district(district)

            triggered_war = abs(effective_delta) >= WAR_THRESHOLD
            event = TerritoryEvent(
                district=district,
                faction=faction,
                delta=round(effective_delta, 2),
                reason=reason,
                triggered_war=triggered_war,
            )
            self._event_history.append(event)
            if len(self._event_history) > _MAX_EVENT_HISTORY:
                self._event_history = self._event_history[-_MAX_EVENT_HISTORY:]

        # Fire events
        if _HAS_EVENT_BUS:
            bus = _get_event_bus()
            if bus is not None:
                bus.publish("territory_shift", event.to_dict())
                if triggered_war:
                    bus.publish("faction_war", {
                        "district": district,
                        "aggressor": faction,
                        "delta": effective_delta,
                        "reason": reason,
                        "control": dict(self._control[district]),
                    })

        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                logger.exception("Territory listener error")

        self._save()
        logger.info(
            "Territory shift: %s %+.1f%% in %s (%s)%s",
            faction, effective_delta, district, reason,
            " — WAR TRIGGERED!" if triggered_war else "",
        )
        return event

    def simulate_faction_tick(self) -> List[TerritoryEvent]:
        """Simulate one tick of autonomous faction activity.

        Each faction attempts to expand in its preferred districts,
        influenced by aggression traits and current control levels.

        Returns:
            List of territory events that occurred.
        """
        events: List[TerritoryEvent] = []
        for faction in FACTION_NAMES:
            traits = FACTION_TRAITS.get(faction, {})
            aggression = traits.get("aggression", 0.5)
            expansion_rate = traits.get("expansion_rate", 0.5)
            preferred = traits.get("preferred_districts", [])
            hostile_to = traits.get("hostile_to", [])

            if random.random() > aggression:
                continue

            target_district = random.choice(preferred) if preferred else random.choice(DISTRICT_NAMES)
            ctrl = self.get_district_control(target_district)
            current = ctrl.get(faction, 0.0)

            if current >= 60.0:
                continue

            delta = random.uniform(0.5, 2.0) * expansion_rate

            source = None
            if hostile_to:
                candidates = [f for f in hostile_to if ctrl.get(f, 0.0) > 5.0]
                if candidates:
                    source = random.choice(candidates)

            event = self.shift_control(
                target_district, faction, delta,
                reason=f"faction_expansion",
                source_faction=source,
            )
            if abs(event.delta) > 0.01:
                events.append(event)

        return events

    # ── HQ Operations ──

    def establish_hq(self, district: str, crew_id: str) -> CrewHQ:
        """Establish a crew HQ in a district.

        Args:
            district: District to set up in.
            crew_id: Crew identifier.

        Returns:
            The new or existing CrewHQ.
        """
        with self._lock:
            if crew_id in self._hqs:
                return self._hqs[crew_id]
            hq = CrewHQ(crew_id=crew_id, district=district)
            self._hqs[crew_id] = hq
        self._save()
        logger.info("Established HQ for %s in %s", crew_id, district)

        if _HAS_EVENT_BUS:
            bus = _get_event_bus()
            if bus is not None:
                bus.publish("hq_established", {
                    "crew_id": crew_id,
                    "district": district,
                })

        return hq

    def get_hq(self, crew_id: str) -> Optional[CrewHQ]:
        """Get a crew's HQ.

        Args:
            crew_id: Crew identifier.

        Returns:
            CrewHQ or None.
        """
        with self._lock:
            return self._hqs.get(crew_id)

    def build_room(self, crew_id: str, room_type: str) -> bool:
        """Build a room in a crew's HQ.

        Args:
            crew_id: Crew identifier.
            room_type: Type of room to build.

        Returns:
            True if built successfully.
        """
        with self._lock:
            hq = self._hqs.get(crew_id)
            if not hq:
                return False
            result = hq.add_room(room_type)
        if result:
            self._save()
        return result

    def upgrade_room(self, crew_id: str, room_type: str) -> bool:
        """Upgrade a room in a crew's HQ.

        Args:
            crew_id: Crew identifier.
            room_type: Room to upgrade.

        Returns:
            True if upgraded successfully.
        """
        with self._lock:
            hq = self._hqs.get(crew_id)
            if not hq:
                return False
            result = hq.upgrade_room(room_type)
        if result:
            self._save()
        return result

    def relocate_hq(self, crew_id: str, new_district: str) -> bool:
        """Move a crew's HQ to a new district (loses all rooms).

        Args:
            crew_id: Crew identifier.
            new_district: Target district.

        Returns:
            True if relocated.
        """
        with self._lock:
            hq = self._hqs.get(crew_id)
            if not hq:
                return False
            if new_district not in DISTRICT_NAMES:
                return False
            hq.district = new_district
            hq.rooms.clear()
            hq.established_at = time.time()
            hq.reputation_local = 0.0
        self._save()
        logger.info("Relocated HQ for %s to %s", crew_id, new_district)
        return True

    # ── Query ──

    def get_all_control(self) -> Dict[str, Dict[str, float]]:
        """Get control map for all districts."""
        with self._lock:
            return {d: dict(c) for d, c in self._control.items()}

    def get_faction_total_control(self, faction: str) -> float:
        """Get a faction's total control across all districts.

        Args:
            faction: Faction name.

        Returns:
            Sum of control percentages (0–600 theoretical max).
        """
        total = 0.0
        with self._lock:
            for ctrl in self._control.values():
                total += ctrl.get(faction, 0.0)
        return round(total, 2)

    def get_faction_ranking(self) -> List[Tuple[str, float]]:
        """Rank all factions by total control.

        Returns:
            List of (faction, total_control) sorted descending.
        """
        rankings = [(f, self.get_faction_total_control(f)) for f in FACTION_NAMES]
        rankings.sort(key=lambda x: x[1], reverse=True)
        return rankings

    def get_district_specialization(self, district: str) -> Dict[str, Any]:
        """Get economic specialization data for a district.

        Args:
            district: District name.

        Returns:
            Specialization dict with type, bonus_skill, credit_multiplier.
        """
        return DISTRICT_SPECIALIZATIONS.get(district, {})

    def get_event_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent territory events.

        Args:
            limit: Max events to return.

        Returns:
            List of event dicts.
        """
        return [e.to_dict() for e in self._event_history[-limit:]]

    def get_wars_active(self) -> List[Dict[str, Any]]:
        """Get recent faction war events (last 10 ticks).

        Returns:
            List of war event dicts.
        """
        cutoff = time.time() - 600  # Last 10 minutes
        return [
            e.to_dict() for e in self._event_history
            if e.triggered_war and e.timestamp > cutoff
        ]

    def get_territory_summary(self) -> str:
        """Generate territory status for LLM prompt injection.

        Returns:
            Multi-line territory summary.
        """
        lines = ["[TERRITORY CONTROL]"]
        for district in DISTRICT_NAMES:
            ctrl = self.get_district_control(district)
            dominant, pct = self.get_dominant_faction(district)
            spec = DISTRICT_SPECIALIZATIONS.get(district, {})
            lines.append(
                f"  {district}: {dominant} ({pct:.0f}%) "
                f"[{spec.get('type', 'unknown')}]"
            )

        rankings = self.get_faction_ranking()
        lines.append("Faction Power Ranking:")
        for i, (faction, total) in enumerate(rankings, 1):
            lines.append(f"  {i}. {faction}: {total:.0f}% total control")

        wars = self.get_wars_active()
        if wars:
            lines.append(f"⚠️ Active faction wars: {len(wars)}")

        return "\n".join(lines)

    # ── Listeners ──

    def add_listener(self, callback: Callable[[TerritoryEvent], None]) -> None:
        """Register callback for territory events.

        Args:
            callback: Function receiving TerritoryEvent.
        """
        self._listeners.append(callback)

    # ── Persistence ──

    def to_dict(self) -> Dict[str, Any]:
        """Serialize full state."""
        return {
            "control": {
                d: {f: round(v, 2) for f, v in c.items()}
                for d, c in self._control.items()
            },
            "hqs": {k: v.to_dict() for k, v in self._hqs.items()},
            "event_history": [e.to_dict() for e in self._event_history[-50:]],
        }

    def _save(self) -> None:
        """Persist to JSON."""
        try:
            _SAVE_DIR.mkdir(parents=True, exist_ok=True)
            path = _SAVE_DIR / _SAVE_FILE
            path.write_text(
                json.dumps(self.to_dict(), indent=2), encoding="utf-8"
            )
        except Exception:
            logger.exception("Failed to save territory state")

    def _load(self) -> None:
        """Load from JSON."""
        path = _SAVE_DIR / _SAVE_FILE
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._control = raw.get("control", {})
            for k, v in raw.get("hqs", {}).items():
                self._hqs[k] = CrewHQ.from_dict(v)
            for ev in raw.get("event_history", []):
                self._event_history.append(TerritoryEvent(
                    district=ev["district"],
                    faction=ev["faction"],
                    delta=ev["delta"],
                    reason=ev.get("reason", ""),
                    timestamp=ev.get("timestamp", time.time()),
                    triggered_war=ev.get("triggered_war", False),
                ))
            logger.info("Loaded territory state for %d districts", len(self._control))
        except Exception:
            logger.exception("Failed to load territory state")


# ============================================================================
# Module-level singleton
# ============================================================================

_manager_instance: Optional[TerritoryManager] = None
_manager_lock = threading.Lock()


def get_territory_manager() -> TerritoryManager:
    """Get the singleton TerritoryManager instance.

    Returns:
        The global TerritoryManager.
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = TerritoryManager()
    return _manager_instance
