"""Faction politics — inter-faction relationships and player standing."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from engine.config import get_config  # noqa: F401 — available for future config use

logger = logging.getLogger(__name__)


@dataclass
class Faction:
    """A named faction with player standing and inter-faction relationships."""

    id: str
    name: str
    scene: str
    description: str = ""
    player_standing: int = 0  # -100 to 100
    relationships: Dict[str, int] = field(default_factory=dict)  # faction_id -> -100..100
    tags: List[str] = field(default_factory=list)


class FactionManager:
    """Manages all factions and their inter-relationships."""

    _instance: Optional["FactionManager"] = None

    def __init__(self) -> None:
        self._factions: Dict[str, Faction] = {}
        logger.info("FactionManager initialised")

    @classmethod
    def get_instance(cls) -> "FactionManager":
        """Return the singleton FactionManager."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, faction: Faction) -> Faction:
        """Register a faction, replacing any existing entry with the same id.

        Args:
            faction: The Faction to register.

        Returns:
            The registered Faction.
        """
        self._factions[faction.id] = faction
        logger.debug("Registered faction %s (scene=%s)", faction.id, faction.scene)
        return faction

    def get(self, faction_id: str) -> Optional[Faction]:
        """Return a faction by id, or None if not found.

        Args:
            faction_id: Faction identifier.

        Returns:
            The Faction or None.
        """
        return self._factions.get(faction_id)

    def get_by_scene(self, scene: str) -> List[Faction]:
        """Return all factions belonging to a scene.

        Args:
            scene: Scene name.

        Returns:
            List of matching Faction objects.
        """
        return [f for f in self._factions.values() if f.scene == scene]

    def modify_standing(
        self, faction_id: str, delta: int, cascade: bool = True
    ) -> Dict[str, int]:
        """Modify player standing with a faction.

        If *cascade* is True, allied factions (positive relationship) receive
        50 % of the delta as a bonus; enemy factions (negative relationship)
        receive -50 % of the delta as a penalty.

        Args:
            faction_id: The faction whose standing changes.
            delta: Signed change in standing (-100..100 clamped).
            cascade: Whether to propagate changes to related factions.

        Returns:
            Dict mapping faction_id -> new player_standing for every faction
            that was modified.
        """
        faction = self._factions.get(faction_id)
        if not faction:
            return {}

        changes: Dict[str, int] = {}
        faction.player_standing = max(-100, min(100, faction.player_standing + delta))
        changes[faction_id] = faction.player_standing

        if cascade:
            for other_id, relationship in faction.relationships.items():
                other = self._factions.get(other_id)
                if not other:
                    continue
                cascade_delta = int(delta * (relationship / 200.0))
                if cascade_delta != 0:
                    other.player_standing = max(
                        -100, min(100, other.player_standing + cascade_delta)
                    )
                    changes[other_id] = other.player_standing

        logger.info(
            "Standing change: %s %+d → %d (cascade: %s)",
            faction_id, delta, faction.player_standing, changes,
        )
        return changes

    def get_scene_politics(self, scene: str) -> Dict[str, Any]:
        """Return a politics summary for all factions in a scene.

        Args:
            scene: Scene name.

        Returns:
            Dict with scene name and list of faction summaries.
        """
        factions = self.get_by_scene(scene)
        return {
            "scene": scene,
            "factions": [
                {
                    "id": f.id,
                    "name": f.name,
                    "player_standing": f.player_standing,
                    "standing_label": _standing_label(f.player_standing),
                    "tags": f.tags,
                }
                for f in factions
            ],
        }

    def reset(self) -> None:
        """Clear all registered factions."""
        self._factions.clear()


# ──── Helpers ────

def _standing_label(score: int) -> str:
    """Map a numeric standing score to a human-readable label.

    Args:
        score: Standing value in range -100..100.

    Returns:
        Label string.
    """
    if score >= 75:
        return "revered"
    if score >= 40:
        return "honored"
    if score >= 10:
        return "friendly"
    if score > -10:
        return "neutral"
    if score > -40:
        return "unfriendly"
    if score > -75:
        return "hostile"
    return "hated"


# ──── Singleton accessor ────

def get_faction_manager() -> FactionManager:
    """Return the singleton FactionManager.

    Returns:
        FactionManager instance.
    """
    return FactionManager.get_instance()
