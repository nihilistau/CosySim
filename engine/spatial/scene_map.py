"""
SceneMap — manages all locations in a scene and character positions.

Provides ``move_character``, ``get_nearby_characters``, ``can_interact``,
and ``snapshot`` for EventChain logging.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from engine.spatial.location import Location


class SceneMap:
    """Container for all :class:`Location` objects in one scene."""

    def __init__(self):
        self._locations: Dict[str, Location] = {}
        self._char_location: Dict[str, str] = {}  # character_id → location_id

    # ── Location management ─────────────────────────────────────────────
    def add_location(self, loc: Location) -> None:
        self._locations[loc.id] = loc

    def remove_location(self, location_id: str) -> None:
        # Evict occupants first
        loc = self._locations.pop(location_id, None)
        if loc:
            for cid in list(loc._occupants):
                self._char_location.pop(cid, None)
            loc._occupants.clear()

    def get_location(self, location_id: str) -> Optional[Location]:
        return self._locations.get(location_id)

    def get_location_by_name(self, name: str) -> Optional[Location]:
        for loc in self._locations.values():
            if loc.name.lower() == name.lower():
                return loc
        return None

    @property
    def locations(self) -> List[Location]:
        return list(self._locations.values())

    @property
    def location_names(self) -> List[str]:
        return [loc.name for loc in self._locations.values()]

    # ── Character positioning ───────────────────────────────────────────
    def place_character(self, character_id: str, location_id: str) -> bool:
        """Place a character at a location (initial placement, not a move)."""
        loc = self._locations.get(location_id)
        if not loc:
            return False
        if loc.is_full:
            return False
        # Remove from previous location if any
        prev = self._char_location.get(character_id)
        if prev and prev in self._locations:
            self._locations[prev].remove_occupant(character_id)
        loc.add_occupant(character_id)
        self._char_location[character_id] = location_id
        return True

    def move_character(self, character_id: str, to_location_id: str) -> bool:
        """Move a character from their current location to a new one."""
        return self.place_character(character_id, to_location_id)

    def remove_character(self, character_id: str) -> None:
        loc_id = self._char_location.pop(character_id, None)
        if loc_id and loc_id in self._locations:
            self._locations[loc_id].remove_occupant(character_id)

    def get_character_location(self, character_id: str) -> Optional[Location]:
        loc_id = self._char_location.get(character_id)
        return self._locations.get(loc_id) if loc_id else None

    def get_nearby_characters(self, character_id: str) -> List[str]:
        """Return character IDs at the same location (excluding self)."""
        loc = self.get_character_location(character_id)
        if not loc:
            return []
        return [cid for cid in loc.occupants if cid != character_id]

    def can_interact(self, char_a: str, char_b: str) -> bool:
        """Two characters can interact only if they share a location."""
        loc_a = self._char_location.get(char_a)
        loc_b = self._char_location.get(char_b)
        return loc_a is not None and loc_a == loc_b

    # ── Queries ─────────────────────────────────────────────────────────
    def get_occupants(self, location_id: str) -> List[str]:
        loc = self._locations.get(location_id)
        return loc.occupants if loc else []

    def get_empty_locations(self) -> List[Location]:
        return [loc for loc in self._locations.values() if len(loc._occupants) == 0]

    # ── Serialisation ───────────────────────────────────────────────────
    def snapshot(self) -> Dict:
        """Full state dict suitable for EventChain payload."""
        return {
            "locations": {lid: loc.to_dict() for lid, loc in self._locations.items()},
            "character_locations": dict(self._char_location),
        }

    def context_for_character(self, character_id: str, names: Dict[str, str] = None) -> str:
        """Build a full LLM context block describing the map from one character's perspective."""
        loc = self.get_character_location(character_id)
        if not loc:
            return "You are nowhere in particular."
        parts = [loc.context_for_llm(names)]
        # List other locations they could go to
        other_locs = [l for l in self._locations.values() if l.id != loc.id]
        if other_locs:
            options = ", ".join(l.name for l in other_locs)
            parts.append(f"Other places you could go: {options}.")
        return " ".join(parts)
