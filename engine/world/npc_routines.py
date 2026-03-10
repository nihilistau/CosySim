"""NPC daily routines and location-based schedules for CosySim v1.0.

Each NPC has a **daily routine** — a sequence of (time_of_day, location,
activity) entries that repeat every game day.  The routine system ticks
every game-hour (60 real seconds) and moves NPCs to their scheduled
locations, updating their activity text and availability.

Routine Templates
~~~~~~~~~~~~~~~~~
NPCs are assigned routines based on their **archetype**:

- **bartender** — morning: sleep, afternoon: prep bar, evening/night: tend bar
- **fixer** — morning: intel gathering, afternoon: meetings, evening: back room deals
- **fighter** — morning: training, afternoon: rest, evening: arena fights
- **hacker** — night: grid work, morning: sleep, afternoon: research
- **merchant** — morning: inventory, afternoon/evening: shop counter
- **guard** — rotating 8-hour shifts across locations
- **socialite** — daytime: shopping, evening: clubs, night: private parties
- **crime_boss** — morning: planning, afternoon: territory patrols, night: operations

Routines can be interrupted by world events (faction wars, crackdowns,
festivals) which override the NPC's current activity.

Usage::

    from engine.world.npc_routines import get_routine_manager

    rm = get_routine_manager()
    rm.register_npc("viktor", archetype="bartender", home_district="DOWNTOWN")
    rm.tick("evening")  # moves Viktor to his bar
    loc = rm.get_npc_location("viktor")  # → {"location": "rusty_anchor", ...}

"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Data classes ────


@dataclass
class RoutineEntry:
    """A single entry in an NPC's daily schedule.

    Attributes:
        time_of_day: One of dawn, morning, afternoon, evening, night, late_night.
        location: Scene or district location string.
        activity: Human-readable activity description.
        interruptible: Whether world events can override this slot.
    """
    time_of_day: str
    location: str
    activity: str
    interruptible: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NPCRoutine:
    """A full daily routine for one NPC.

    Attributes:
        character_id: NPC identifier (matches NPCStateRegistry).
        archetype: Template archetype name.
        home_district: NPC's home district.
        schedule: Ordered list of RoutineEntry for each time-of-day.
        current_entry: Index into schedule for current time slot.
        interrupted: Whether the NPC is currently off-routine due to an event.
        interrupt_reason: Description of why the routine is interrupted.
        interrupt_location: Where the NPC is during interruption.
    """
    character_id: str
    archetype: str = "generic"
    home_district: str = "DOWNTOWN"
    schedule: List[RoutineEntry] = field(default_factory=list)
    current_entry: int = 0
    interrupted: bool = False
    interrupt_reason: str = ""
    interrupt_location: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "character_id": self.character_id,
            "archetype": self.archetype,
            "home_district": self.home_district,
            "schedule": [e.to_dict() for e in self.schedule],
            "current_entry": self.current_entry,
            "interrupted": self.interrupted,
            "interrupt_reason": self.interrupt_reason,
        }


# ──── Archetype Schedule Templates ────

# Location tokens are resolved to scene names at registration time
# based on the NPC's home_district.

ARCHETYPE_SCHEDULES: Dict[str, List[Dict[str, str]]] = {
    "bartender": [
        {"time": "dawn", "location": "home", "activity": "sleeping"},
        {"time": "morning", "location": "home", "activity": "sleeping off the night shift"},
        {"time": "afternoon", "location": "bar", "activity": "prepping the bar, restocking supplies"},
        {"time": "evening", "location": "bar", "activity": "serving drinks, chatting with regulars"},
        {"time": "night", "location": "bar", "activity": "tending bar, handling the late crowd"},
        {"time": "late_night", "location": "bar", "activity": "closing up, counting receipts"},
    ],
    "fixer": [
        {"time": "dawn", "location": "home", "activity": "sleeping"},
        {"time": "morning", "location": "streets", "activity": "gathering intel from contacts"},
        {"time": "afternoon", "location": "cafe", "activity": "meeting clients, brokering deals"},
        {"time": "evening", "location": "back_room", "activity": "arranging jobs and smuggling runs"},
        {"time": "night", "location": "underground", "activity": "overseeing covert operations"},
        {"time": "late_night", "location": "home", "activity": "reviewing the night's take"},
    ],
    "fighter": [
        {"time": "dawn", "location": "gym", "activity": "morning training routine"},
        {"time": "morning", "location": "gym", "activity": "sparring practice"},
        {"time": "afternoon", "location": "home", "activity": "resting, reviewing fight footage"},
        {"time": "evening", "location": "arena", "activity": "warming up for tonight's bout"},
        {"time": "night", "location": "arena", "activity": "fighting in the arena"},
        {"time": "late_night", "location": "bar", "activity": "celebrating (or drowning sorrows)"},
    ],
    "hacker": [
        {"time": "dawn", "location": "home", "activity": "sleeping (just went to bed)"},
        {"time": "morning", "location": "home", "activity": "sleeping"},
        {"time": "afternoon", "location": "lab", "activity": "researching vulnerabilities"},
        {"time": "evening", "location": "grid", "activity": "scanning networks, testing exploits"},
        {"time": "night", "location": "grid", "activity": "deep in the net, running intrusions"},
        {"time": "late_night", "location": "grid", "activity": "finishing data extraction runs"},
    ],
    "merchant": [
        {"time": "dawn", "location": "warehouse", "activity": "checking inventory shipments"},
        {"time": "morning", "location": "shop", "activity": "opening the shop, arranging displays"},
        {"time": "afternoon", "location": "shop", "activity": "serving customers, haggling"},
        {"time": "evening", "location": "shop", "activity": "dealing with last-minute buyers"},
        {"time": "night", "location": "home", "activity": "counting the day's profits"},
        {"time": "late_night", "location": "home", "activity": "sleeping"},
    ],
    "guard": [
        {"time": "dawn", "location": "checkpoint", "activity": "starting the morning shift"},
        {"time": "morning", "location": "patrol", "activity": "patrolling the district"},
        {"time": "afternoon", "location": "checkpoint", "activity": "manning the checkpoint"},
        {"time": "evening", "location": "home", "activity": "off-duty, resting"},
        {"time": "night", "location": "patrol", "activity": "night patrol, watching for trouble"},
        {"time": "late_night", "location": "checkpoint", "activity": "late watch, fighting drowsiness"},
    ],
    "socialite": [
        {"time": "dawn", "location": "home", "activity": "sleeping in a luxury apartment"},
        {"time": "morning", "location": "home", "activity": "getting ready, checking social feeds"},
        {"time": "afternoon", "location": "boutique", "activity": "shopping, browsing galleries"},
        {"time": "evening", "location": "club", "activity": "socializing, networking at events"},
        {"time": "night", "location": "club", "activity": "dancing, enjoying the nightlife"},
        {"time": "late_night", "location": "penthouse", "activity": "hosting a private after-party"},
    ],
    "crime_boss": [
        {"time": "dawn", "location": "home", "activity": "sleeping in a secure safehouse"},
        {"time": "morning", "location": "office", "activity": "reviewing reports, planning operations"},
        {"time": "afternoon", "location": "territory", "activity": "inspecting territory, meeting lieutenants"},
        {"time": "evening", "location": "back_room", "activity": "conducting business, receiving tribute"},
        {"time": "night", "location": "underground", "activity": "overseeing nighttime operations"},
        {"time": "late_night", "location": "home", "activity": "reviewing intel, making calls"},
    ],
    "generic": [
        {"time": "dawn", "location": "home", "activity": "sleeping"},
        {"time": "morning", "location": "home", "activity": "waking up, getting ready"},
        {"time": "afternoon", "location": "streets", "activity": "going about daily business"},
        {"time": "evening", "location": "bar", "activity": "relaxing after a long day"},
        {"time": "night", "location": "home", "activity": "settling in for the night"},
        {"time": "late_night", "location": "home", "activity": "sleeping"},
    ],
}

# Map abstract location tokens to scene names by district
LOCATION_MAP: Dict[str, Dict[str, str]] = {
    "DOWNTOWN": {
        "home": "penthouse", "bar": "velvet_pit", "club": "club_noir",
        "streets": "neon_city", "shop": "neon_city", "boutique": "obscura",
        "cafe": "lounge", "back_room": "briefing_room", "underground": "score",
        "gym": "colosseum", "arena": "colosseum", "lab": "lab",
        "grid": "grid", "warehouse": "neon_city", "checkpoint": "neon_city",
        "patrol": "neon_city", "penthouse": "penthouse", "office": "command_center",
        "territory": "neon_city",
    },
    "COMBAT_ZONE": {
        "home": "rusty_anchor", "bar": "rusty_anchor", "club": "rusty_anchor",
        "streets": "neon_city", "shop": "neon_city", "boutique": "neon_city",
        "cafe": "rusty_anchor", "back_room": "rusty_anchor", "underground": "score",
        "gym": "colosseum", "arena": "colosseum", "lab": "lab",
        "grid": "grid", "warehouse": "neon_city", "checkpoint": "neon_city",
        "patrol": "neon_city", "penthouse": "penthouse", "office": "rusty_anchor",
        "territory": "neon_city",
    },
    "HIGHRISE": {
        "home": "penthouse", "bar": "lounge", "club": "club_noir",
        "streets": "neon_city", "shop": "neon_city", "boutique": "obscura",
        "cafe": "lounge", "back_room": "command_center", "underground": "score",
        "gym": "colosseum", "arena": "colosseum", "lab": "lab",
        "grid": "grid", "warehouse": "neon_city", "checkpoint": "command_center",
        "patrol": "neon_city", "penthouse": "penthouse", "office": "command_center",
        "territory": "neon_city",
    },
    "UNDERWORLD": {
        "home": "score", "bar": "rusty_anchor", "club": "velvet_pit",
        "streets": "neon_city", "shop": "neon_city", "boutique": "neon_city",
        "cafe": "rusty_anchor", "back_room": "briefing_room", "underground": "score",
        "gym": "colosseum", "arena": "colosseum", "lab": "lab",
        "grid": "grid", "warehouse": "score", "checkpoint": "neon_city",
        "patrol": "neon_city", "penthouse": "penthouse", "office": "briefing_room",
        "territory": "neon_city",
    },
    "TECH_DISTRICT": {
        "home": "lab", "bar": "lounge", "club": "club_noir",
        "streets": "neon_city", "shop": "arcade", "boutique": "neon_city",
        "cafe": "lounge", "back_room": "grid", "underground": "grid",
        "gym": "colosseum", "arena": "colosseum", "lab": "lab",
        "grid": "grid", "warehouse": "neon_city", "checkpoint": "neon_city",
        "patrol": "neon_city", "penthouse": "penthouse", "office": "lab",
        "territory": "neon_city",
    },
    "OUTSKIRTS": {
        "home": "shattered_throne", "bar": "rusty_anchor", "club": "neon_city",
        "streets": "neon_city", "shop": "neon_city", "boutique": "neon_city",
        "cafe": "neon_city", "back_room": "shattered_throne", "underground": "score",
        "gym": "colosseum", "arena": "colosseum", "lab": "lab",
        "grid": "grid", "warehouse": "neon_city", "checkpoint": "neon_city",
        "patrol": "neon_city", "penthouse": "penthouse", "office": "shattered_throne",
        "territory": "neon_city",
    },
}

# Database NPCs with their archetypes (matches character_registry seeded characters)
DEFAULT_NPC_ARCHETYPES: Dict[str, Dict[str, str]] = {
    "lola": {"archetype": "socialite", "district": "DOWNTOWN"},
    "viktor": {"archetype": "bartender", "district": "COMBAT_ZONE"},
    "aria": {"archetype": "hacker", "district": "TECH_DISTRICT"},
    "frankie": {"archetype": "fixer", "district": "UNDERWORLD"},
    "mira": {"archetype": "merchant", "district": "DOWNTOWN"},
}

TIME_SLOTS = ["dawn", "morning", "afternoon", "evening", "night", "late_night"]


# ──── Routine Manager ────


class RoutineManager:
    """Manages NPC daily routines and location transitions.

    Coordinates with :class:`NPCStateRegistry` to update NPC locations
    and activities as game time progresses.
    """

    def __init__(self) -> None:
        self._routines: Dict[str, NPCRoutine] = {}
        self._lock = threading.RLock()
        self._last_time_slot: str = ""
        logger.info("RoutineManager initialized")

    def register_npc(
        self,
        character_id: str,
        archetype: str = "generic",
        home_district: str = "DOWNTOWN",
    ) -> NPCRoutine:
        """Register an NPC with a routine based on archetype.

        Args:
            character_id: NPC identifier.
            archetype: Template name (bartender, fixer, etc.).
            home_district: District for location resolution.

        Returns:
            The created NPCRoutine.
        """
        template = ARCHETYPE_SCHEDULES.get(archetype, ARCHETYPE_SCHEDULES["generic"])
        loc_map = LOCATION_MAP.get(home_district, LOCATION_MAP["DOWNTOWN"])

        schedule: List[RoutineEntry] = []
        for entry in template:
            raw_loc = entry["location"]
            resolved_loc = loc_map.get(raw_loc, raw_loc)
            schedule.append(RoutineEntry(
                time_of_day=entry["time"],
                location=resolved_loc,
                activity=entry["activity"],
            ))

        routine = NPCRoutine(
            character_id=character_id,
            archetype=archetype,
            home_district=home_district,
            schedule=schedule,
        )

        with self._lock:
            self._routines[character_id] = routine

        logger.debug("Registered routine: %s (%s in %s)",
                      character_id, archetype, home_district)
        return routine

    def register_defaults(self) -> int:
        """Register all default NPCs from DEFAULT_NPC_ARCHETYPES.

        Returns:
            Number of NPCs registered.
        """
        count = 0
        for cid, info in DEFAULT_NPC_ARCHETYPES.items():
            self.register_npc(cid, info["archetype"], info["district"])
            count += 1
        return count

    def tick(self, time_of_day: str) -> Dict[str, Any]:
        """Advance all NPCs to their scheduled activity for this time slot.

        Only transitions NPCs whose routine entry changes from the last
        tick.  Interrupted NPCs stay at their interrupt location unless
        the interrupt has been cleared.

        Args:
            time_of_day: Current time slot (dawn/morning/afternoon/evening/night/late_night).

        Returns:
            Summary of NPC movements this tick.
        """
        if time_of_day not in TIME_SLOTS:
            return {"error": f"Invalid time slot: {time_of_day}"}

        with self._lock:
            if time_of_day == self._last_time_slot:
                return {"transitions": 0, "same_slot": True}

            self._last_time_slot = time_of_day
            transitions: List[Dict[str, Any]] = []

            for cid, routine in self._routines.items():
                if routine.interrupted:
                    continue

                entry = self._find_entry(routine, time_of_day)
                if entry is None:
                    continue

                old_idx = routine.current_entry
                new_idx = routine.schedule.index(entry)
                if old_idx == new_idx:
                    continue

                routine.current_entry = new_idx
                transitions.append({
                    "character_id": cid,
                    "location": entry.location,
                    "activity": entry.activity,
                    "time_of_day": time_of_day,
                })

                self._update_npc_state(cid, entry.location, entry.activity)

        return {
            "transitions": len(transitions),
            "movements": transitions,
            "time_of_day": time_of_day,
        }

    def interrupt_npc(
        self, character_id: str, reason: str, location: str = ""
    ) -> bool:
        """Interrupt an NPC's routine (e.g., due to a world event).

        Args:
            character_id: NPC to interrupt.
            reason: Why the routine is interrupted.
            location: Override location (empty = stay in place).

        Returns:
            True if interrupted, False if NPC not found.
        """
        with self._lock:
            routine = self._routines.get(character_id)
            if not routine:
                return False
            routine.interrupted = True
            routine.interrupt_reason = reason
            if location:
                routine.interrupt_location = location
                self._update_npc_state(character_id, location, reason)
            return True

    def resume_npc(self, character_id: str) -> bool:
        """Resume an NPC's normal routine after interruption.

        Args:
            character_id: NPC to resume.

        Returns:
            True if resumed, False if not found or not interrupted.
        """
        with self._lock:
            routine = self._routines.get(character_id)
            if not routine or not routine.interrupted:
                return False
            routine.interrupted = False
            routine.interrupt_reason = ""
            routine.interrupt_location = ""

            # Snap to current time slot
            if self._last_time_slot:
                entry = self._find_entry(routine, self._last_time_slot)
                if entry:
                    routine.current_entry = routine.schedule.index(entry)
                    self._update_npc_state(
                        character_id, entry.location, entry.activity
                    )
            return True

    def get_npc_location(self, character_id: str) -> Optional[Dict[str, Any]]:
        """Return current location and activity for an NPC.

        Args:
            character_id: NPC identifier.

        Returns:
            Dict with location, activity, interrupted status; or None.
        """
        with self._lock:
            routine = self._routines.get(character_id)
            if not routine:
                return None

            if routine.interrupted:
                return {
                    "character_id": character_id,
                    "location": routine.interrupt_location,
                    "activity": routine.interrupt_reason,
                    "interrupted": True,
                    "archetype": routine.archetype,
                }

            if routine.schedule and 0 <= routine.current_entry < len(routine.schedule):
                entry = routine.schedule[routine.current_entry]
                return {
                    "character_id": character_id,
                    "location": entry.location,
                    "activity": entry.activity,
                    "time_of_day": entry.time_of_day,
                    "interrupted": False,
                    "archetype": routine.archetype,
                }

            return {
                "character_id": character_id,
                "location": "unknown",
                "activity": "idle",
                "interrupted": False,
                "archetype": routine.archetype,
            }

    def get_all_locations(self) -> Dict[str, Dict[str, Any]]:
        """Return locations for all registered NPCs.

        Returns:
            {character_id: location_info} for all NPCs.
        """
        result: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            for cid in self._routines:
                loc = self.get_npc_location(cid)
                if loc:
                    result[cid] = loc
        return result

    def get_npcs_at(self, location: str) -> List[Dict[str, Any]]:
        """Return all NPCs currently at a given location/scene.

        Args:
            location: Scene name or location string.

        Returns:
            List of NPC location dicts at that location.
        """
        all_locs = self.get_all_locations()
        return [info for info in all_locs.values() if info.get("location") == location]

    def get_routine(self, character_id: str) -> Optional[Dict[str, Any]]:
        """Return the full daily schedule for an NPC.

        Args:
            character_id: NPC identifier.

        Returns:
            Routine dict or None.
        """
        with self._lock:
            routine = self._routines.get(character_id)
            return routine.to_dict() if routine else None

    def list_npcs(self) -> List[str]:
        """Return all registered NPC character IDs."""
        with self._lock:
            return list(self._routines.keys())

    def get_stats(self) -> Dict[str, Any]:
        """Return routine system statistics."""
        with self._lock:
            interrupted = sum(1 for r in self._routines.values() if r.interrupted)
            archetypes: Dict[str, int] = {}
            for r in self._routines.values():
                archetypes[r.archetype] = archetypes.get(r.archetype, 0) + 1
            return {
                "total_npcs": len(self._routines),
                "interrupted": interrupted,
                "active": len(self._routines) - interrupted,
                "archetypes": archetypes,
                "last_time_slot": self._last_time_slot,
            }

    def reset(self) -> None:
        """Clear all routines."""
        with self._lock:
            self._routines.clear()
            self._last_time_slot = ""

    # ──── Internal ────

    def _find_entry(
        self, routine: NPCRoutine, time_of_day: str
    ) -> Optional[RoutineEntry]:
        """Find the schedule entry for a given time slot."""
        for entry in routine.schedule:
            if entry.time_of_day == time_of_day:
                return entry
        return None

    def _update_npc_state(
        self, character_id: str, location: str, activity: str
    ) -> None:
        """Push location update to NPCStateRegistry (best-effort)."""
        try:
            from engine.world.npc_state import get_npc_state_registry
            registry = get_npc_state_registry()
            registry.update(character_id, location=location, activity=activity)
        except Exception as exc:
            logger.debug("RoutineManager: NPC state update failed for %s: %s",
                         character_id, exc)


# ──── Singleton ────

_instance: Optional[RoutineManager] = None
_instance_lock = threading.Lock()


def get_routine_manager() -> RoutineManager:
    """Return the singleton RoutineManager."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = RoutineManager()
    return _instance


def reset_routine_manager() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
