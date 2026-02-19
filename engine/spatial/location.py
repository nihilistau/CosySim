"""
Location — a named place inside a scene that characters can occupy.

Each location has a capacity, available interactions, and properties
(privacy, comfort, lighting) that influence agent behaviour.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class Location:
    """A discrete place within a scene (e.g. 'bed', 'bar', 'balcony')."""

    id: str = ""
    name: str = ""
    description: str = ""
    interactions: List[str] = field(default_factory=list)
    capacity: int = 4
    properties: Dict = field(default_factory=dict)

    # Runtime state
    _occupants: Set[str] = field(default_factory=set, repr=False)

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())

    # ── Occupancy ───────────────────────────────────────────────────────
    @property
    def occupants(self) -> List[str]:
        return list(self._occupants)

    @property
    def is_full(self) -> bool:
        return len(self._occupants) >= self.capacity

    def add_occupant(self, character_id: str) -> bool:
        """Add a character. Returns False if at capacity."""
        if self.is_full:
            return False
        self._occupants.add(character_id)
        return True

    def remove_occupant(self, character_id: str) -> bool:
        self._occupants.discard(character_id)
        return True

    def has_occupant(self, character_id: str) -> bool:
        return character_id in self._occupants

    # ── Properties shortcuts ────────────────────────────────────────────
    @property
    def privacy(self) -> float:
        """0.0 (public) – 1.0 (private)."""
        return float(self.properties.get("privacy", 0.5))

    @property
    def comfort(self) -> float:
        return float(self.properties.get("comfort", 0.5))

    @property
    def spiciness(self) -> int:
        """0–5 scale: how intimate interactions can get here."""
        return int(self.properties.get("spiciness", 1))

    # ── Serialisation ───────────────────────────────────────────────────
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "interactions": self.interactions,
            "capacity": self.capacity,
            "properties": self.properties,
            "occupants": self.occupants,
        }

    def context_for_llm(self, other_names: Optional[Dict[str, str]] = None) -> str:
        """Build a short context string an LLM can read.

        Args:
            other_names: ``{character_id: display_name}`` for occupants.
        """
        others = []
        if other_names:
            for cid in self._occupants:
                if cid in other_names:
                    others.append(other_names[cid])
        people = ", ".join(others) if others else "no one else"
        acts = ", ".join(self.interactions) if self.interactions else "nothing special"
        return (
            f"You are at the {self.name}. {self.description} "
            f"People here: {people}. You can: {acts}."
        )
