"""
relationship_skills.py — Character relationship graph skills.

@skill wrappers around CharacterMemory so LLM agents can read and update
opinion scores between characters during a scene.
"""
from __future__ import annotations

import logging
from typing import Dict

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _fmt_score(score: float) -> str:
    """Return a score + label string, e.g. '0.35 (friendly)'."""
    from engine.agents.character_memory import get_character_memory
    mem = get_character_memory("_util")
    label = mem.score_label(score)
    return f"{score:.2f} ({label})"


@skill(
    pack="relationships",
    description="Get the relationship opinion score from one character toward another (-1=hostile, 0=neutral, 1=trusted)",
    category=SkillCategory.SOCIAL,
    tags=["relationship", "opinion", "social"],
)
def get_relationship_score(character_id: str, other_id: str) -> str:
    """
    Return the current relationship score that *character_id* holds toward *other_id*.

    Args:
        character_id: The character whose opinion we're reading.
        other_id: The target character.

    Returns:
        Human-readable score string.
    """
    try:
        from engine.agents.character_memory import get_character_memory
        mem = get_character_memory(character_id)
        score = mem.get_relationship(other_id)
        return f"{character_id}'s opinion of {other_id}: {_fmt_score(score)}"
    except Exception as exc:
        return f"get_relationship_score failed: {exc}"


@skill(
    pack="relationships",
    description="Update the relationship score between two characters after an interaction",
    category=SkillCategory.SOCIAL,
    tags=["relationship", "opinion", "update", "social"],
)
def update_relationship_score(
    character_id: str,
    other_id: str,
    delta: float,
    reason: str = "",
) -> str:
    """
    Adjust *character_id*'s opinion of *other_id* by *delta*.

    Args:
        character_id: The character whose opinion changes.
        other_id: The target character.
        delta: Change amount, e.g. 0.1 (warmer) or -0.3 (colder).
        reason: Optional human-readable reason.

    Returns:
        Confirmation with old → new score.
    """
    try:
        from engine.agents.character_memory import get_character_memory
        mem = get_character_memory(character_id)
        old = mem.get_relationship(other_id)
        new = mem.update_relationship(other_id, delta, reason=reason)
        suffix = f" ({reason})" if reason else ""
        return (
            f"{character_id}'s opinion of {other_id}: "
            f"{_fmt_score(old)} → {_fmt_score(new)}{suffix}"
        )
    except Exception as exc:
        return f"update_relationship_score failed: {exc}"


@skill(
    pack="relationships",
    description="Get all relationship scores for a character — who they trust, who they dislike",
    category=SkillCategory.SOCIAL,
    tags=["relationship", "opinion", "all", "social"],
)
def get_character_relationships(character_id: str) -> str:
    """
    Return all recorded relationships for *character_id*.

    Args:
        character_id: The character to query.

    Returns:
        Formatted list of relationships, or a 'no relationships' message.
    """
    try:
        from engine.agents.character_memory import get_character_memory
        mem = get_character_memory(character_id)
        rels = mem.get_all_relationships()
        if not rels:
            return f"{character_id} has no recorded relationships yet (everyone is neutral)."
        lines = [f"{character_id}'s relationships:"]
        for other, score in sorted(rels.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {other}: {_fmt_score(score)}")
        return "\n".join(lines)
    except Exception as exc:
        return f"get_character_relationships failed: {exc}"
