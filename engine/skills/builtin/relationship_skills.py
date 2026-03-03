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


# ──── Player-profile relationship type skills ─────────────────────────────────

@skill(
    pack="relationships",
    description="Set the relationship type between the player and an NPC (friend, lover, crew, partner, co_worker, rival, enemy, etc.)",
    category=SkillCategory.SOCIAL,
    tags=["relationship", "type", "player", "social"],
)
def set_player_relationship_type(
    character_id: str,
    rel_type: str,
    notes: str = "",
) -> str:
    """
    Set an explicit relationship type between the player and *character_id*.

    Use this when a story beat changes the relationship dynamic.
    Valid types: stranger, acquaintance, friend, close_friend, lover, partner,
    co_worker, crew, brother, rival, enemy, family.

    Args:
        character_id: NPC identifier.
        rel_type: Relationship type label.
        notes: Optional note about why the relationship changed.

    Returns:
        Confirmation of the new relationship type.
    """
    try:
        from engine.characters.player_profile import get_player_profile, RELATIONSHIP_TYPES
        profile = get_player_profile()
        if rel_type not in RELATIONSHIP_TYPES:
            return f"Unknown relationship type '{rel_type}'. Valid types: {', '.join(RELATIONSHIP_TYPES)}"
        entry = profile.set_relationship_type(character_id, rel_type, notes=notes)
        return f"Relationship with {character_id} is now: {rel_type.upper()} (score {entry.score:+.1f})"
    except Exception as exc:
        return f"set_player_relationship_type failed: {exc}"


@skill(
    pack="relationships",
    description="Recruit an NPC into the player's crew. They must have a high enough relationship score first.",
    category=SkillCategory.SOCIAL,
    tags=["crew", "recruit", "relationship", "player"],
)
def recruit_to_crew(
    character_id: str,
    role: str = "crew",
    notes: str = "",
) -> str:
    """
    Add *character_id* to the player's crew.

    The NPC must have a relationship score of at least 40 to be recruited.
    The role can be anything descriptive: hacker, muscle, fixer, medic, driver, etc.

    Args:
        character_id: NPC identifier.
        role: Role in the crew (e.g. 'hacker', 'muscle', 'fixer').
        notes: Optional recruitment note.

    Returns:
        Confirmation or error if the relationship isn't strong enough.
    """
    try:
        from engine.characters.player_profile import get_player_profile
        profile = get_player_profile()
        existing = profile.relationships.get(character_id)
        score = existing.score if existing else 0.0
        if score < 40:
            return (
                f"Cannot recruit {character_id} — relationship score {score:+.1f} is too low. "
                f"Need at least +40. Spend more time building trust first."
            )
        crew_tag = f"crew:{role}" if role != "crew" else "crew"
        entry = profile.add_crew_member(character_id, crew_tag=crew_tag, notes=notes or f"Recruited as {role}")
        return f"{character_id} joined your crew as {role.upper()}! Score: {entry.score:+.1f}"
    except Exception as exc:
        return f"recruit_to_crew failed: {exc}"


@skill(
    pack="relationships",
    description="List the player's current crew members with their roles and relationship scores",
    category=SkillCategory.SOCIAL,
    tags=["crew", "list", "player", "social"],
)
def list_crew() -> str:
    """
    Return all current crew members with their roles and relationship scores.

    Returns:
        Formatted crew roster or 'no crew' message.
    """
    try:
        from engine.characters.player_profile import get_player_profile
        profile = get_player_profile()
        crew = profile.get_crew()
        if not crew:
            return "You have no crew yet. Build relationships and recruit allies."
        lines = ["YOUR CREW:"]
        for member in sorted(crew, key=lambda r: -r.score):
            tags = [t for t in member.tags if t.startswith("crew:")]
            role = tags[0].replace("crew:", "").upper() if tags else "CREW"
            lines.append(f"  {member.character_id} [{role}] — score {member.score:+.1f} | {member.interaction_count} interactions")
        return "\n".join(lines)
    except Exception as exc:
        return f"list_crew failed: {exc}"


@skill(
    pack="relationships",
    description="Get the player's full relationship summary — all tracked NPCs sorted by closeness",
    category=SkillCategory.SOCIAL,
    tags=["relationship", "player", "summary", "social"],
)
def get_player_relationship_summary() -> str:
    """
    Return all player relationships sorted by absolute score.

    Returns:
        Formatted relationship roster.
    """
    try:
        from engine.characters.player_profile import get_player_profile
        profile = get_player_profile()
        if not profile.relationships:
            return "No relationships tracked yet. Interact with characters to build connections."
        rels = sorted(profile.relationships.values(), key=lambda r: -r.score)
        lines = ["PLAYER RELATIONSHIPS:"]
        for r in rels:
            lines.append(
                f"  {r.character_id}: {r.score:+.1f} [{r.rel_type.upper()}] "
                f"({r.interaction_count} interactions, sentiment: {r.sentiment})"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"get_player_relationship_summary failed: {exc}"
