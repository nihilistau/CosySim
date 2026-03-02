"""
character_memory.py — Character relationship graph for CosySim.

Stores per-character opinion scores toward other characters as a simple
-1.0 (hostile) → 0.0 (neutral) → +1.0 (trusted) float.

Storage: in-memory dict, optionally mirrored to Nexus for audit trail.

Usage::

    from engine.agents.character_memory import CharacterMemory

    mem = CharacterMemory("lola")
    mem.set_relationship("player", 0.5, reason="helped me")
    score = mem.get_relationship("player")       # 0.5
    score = mem.update_relationship("player", -0.2, reason="lied")  # 0.3
    all_rels = mem.get_all_relationships()       # {"player": 0.3}
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── Module-level registry so one CharacterMemory per character_id ───────
_REGISTRY: Dict[str, "CharacterMemory"] = {}


def get_character_memory(character_id: str) -> "CharacterMemory":
    """Return the singleton CharacterMemory for *character_id*."""
    if character_id not in _REGISTRY:
        _REGISTRY[character_id] = CharacterMemory(character_id)
    return _REGISTRY[character_id]


class CharacterMemory:
    """
    Lightweight opinion-score store for one character.

    Relationship scores are floats in the range [-1.0, 1.0]:
      -1.0  → deeply hostile
       0.0  → neutral (default)
      +1.0  → completely trusted

    Parameters
    ----------
    character_id:
        The owning character's ID (e.g. ``"lola"``).
    """

    def __init__(self, character_id: str) -> None:
        self.character_id = character_id
        # {other_character_id: score}
        self._relationships: Dict[str, float] = {}

    # ── core relationship API ────────────────────────────────────────────

    def set_relationship(
        self,
        other_character_id: str,
        score: float,
        reason: str = "",
    ) -> None:
        """
        Store an opinion score toward *other_character_id*.

        Args:
            other_character_id: Target character's ID.
            score: Opinion score clamped to [-1.0, 1.0].
            reason: Human-readable context (used for Nexus audit).
        """
        clamped = max(-1.0, min(1.0, float(score)))
        self._relationships[other_character_id] = clamped
        logger.debug(
            "CharacterMemory[%s] set relationship → %s = %.2f (%s)",
            self.character_id, other_character_id, clamped, reason,
        )
        self._nexus_log(other_character_id, clamped, reason, action="set")

    def get_relationship(self, other_character_id: str) -> float:
        """
        Return the opinion score toward *other_character_id*.

        Returns 0.0 (neutral) when no relationship has been recorded.

        Args:
            other_character_id: Target character's ID.

        Returns:
            Score in [-1.0, 1.0].
        """
        return self._relationships.get(other_character_id, 0.0)

    def update_relationship(
        self,
        other_character_id: str,
        delta: float,
        reason: str = "",
    ) -> float:
        """
        Adjust the opinion score by *delta* (clamped to [-1.0, 1.0]).

        Args:
            other_character_id: Target character's ID.
            delta: Amount to add (positive or negative).
            reason: Human-readable context.

        Returns:
            New score in [-1.0, 1.0].
        """
        current = self._relationships.get(other_character_id, 0.0)
        new_score = max(-1.0, min(1.0, current + float(delta)))
        self._relationships[other_character_id] = new_score
        logger.debug(
            "CharacterMemory[%s] update relationship → %s: %.2f%+.2f = %.2f (%s)",
            self.character_id, other_character_id, current, delta, new_score, reason,
        )
        self._nexus_log(other_character_id, new_score, reason, action="update")
        return new_score

    def get_all_relationships(self) -> Dict[str, float]:
        """
        Return all recorded relationships as a ``{character_id: score}`` dict.

        Returns:
            Shallow copy of the internal relationships mapping.
        """
        return dict(self._relationships)

    # ── helpers ─────────────────────────────────────────────────────────

    def score_label(self, score: float) -> str:
        """Convert a numeric score to a human-readable label."""
        if score >= 0.7:
            return "trusted"
        if score >= 0.3:
            return "friendly"
        if score >= -0.2:
            return "neutral"
        if score >= -0.6:
            return "wary"
        return "hostile"

    def _nexus_log(
        self,
        other_id: str,
        score: float,
        reason: str,
        action: str,
    ) -> None:
        """Best-effort audit log to Nexus (fire-and-forget, never raises)."""
        try:
            from engine.nexus.client import get_nexus_client
            nx = get_nexus_client()
            if not nx.is_available():
                return
            label = self.score_label(score)
            title = f"relationship_event:{self.character_id}→{other_id}"
            content = (
                f"action={action} score={score:.2f} ({label})"
                + (f" reason={reason}" if reason else "")
            )
            nx.add_entry(
                title=title,
                content=content,
                content_type="memory",
                category="relationships",
                tags=["relationship_event"],
            )
        except Exception:
            logger.debug("CharacterMemory._nexus_log suppressed", exc_info=True)

    def __repr__(self) -> str:
        return (
            f"<CharacterMemory character={self.character_id!r} "
            f"relationships={len(self._relationships)}>"
        )
