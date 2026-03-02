"""Player profile skills — expose PlayerProfile to LLM agents."""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill, SkillCategory
from engine.characters.player_profile import get_player_profile

logger = logging.getLogger(__name__)


@skill(
    pack="player_profile",
    description="Get a summary of the player's identity, top NPC relationships, and scene history.",
    category=SkillCategory.SOCIAL,
    tags=["player", "profile", "summary"],
)
def get_player_summary() -> str:
    """Return display_name + top relationships + scene visit history."""
    profile = get_player_profile()
    parts = [
        f"Player: {profile.display_name} (id={profile.player_id})",
        "",
        "── Relationships ──",
        profile.get_relationship_summary(),
        "",
        "── Scene History ──",
        profile.get_scene_summary(),
    ]
    return "\n".join(parts)


@skill(
    pack="player_profile",
    description="Update the player's relationship score with an NPC by a delta value.",
    category=SkillCategory.SOCIAL,
    tags=["player", "relationship", "npc"],
)
def update_npc_relationship(
    character_id: str,
    delta: float,
    reason: str = "",
) -> str:
    """Apply delta to the relationship score for character_id and return the new state."""
    profile = get_player_profile()
    entry = profile.update_relationship(character_id, delta, notes=reason)
    profile.save()
    return (
        f"Relationship with {character_id}: score={entry.score:+.1f}, "
        f"sentiment={entry.sentiment}, interactions={entry.interaction_count}"
    )


@skill(
    pack="player_profile",
    description="Record a significant player decision with optional consequences.",
    category=SkillCategory.NARRATIVE,
    tags=["player", "decision", "narrative"],
)
def record_player_decision(
    scene: str,
    description: str,
    consequences: str = "",
) -> str:
    """Record a decision and return its generated decision_id."""
    profile = get_player_profile()
    consequence_list = [c.strip() for c in consequences.split(",") if c.strip()] if consequences else []
    entry = profile.record_decision(scene, description, consequence_list)
    profile.save()
    return f"Decision recorded: id={entry.decision_id}, scene={scene}"


@skill(
    pack="player_profile",
    description="Get the player's relationship details with a specific NPC character.",
    category=SkillCategory.SOCIAL,
    tags=["player", "relationship", "npc"],
)
def get_relationship_with(character_id: str) -> str:
    """Return score, sentiment, and last interaction time for the given character."""
    profile = get_player_profile()
    if character_id not in profile.relationships:
        return f"No relationship data for {character_id}."
    entry = profile.relationships[character_id]
    last = entry.last_interaction
    last_str = f"{last:.0f}" if last else "never"
    return (
        f"{character_id}: score={entry.score:+.1f}, sentiment={entry.sentiment}, "
        f"interactions={entry.interaction_count}, last_interaction={last_str}"
    )


@skill(
    pack="player_profile",
    description="Get the player's reputation score in a specific scene, or all scenes if none given.",
    category=SkillCategory.SOCIAL,
    tags=["player", "reputation", "scene"],
)
def get_player_reputation(scene: str = "") -> str:
    """Return reputation score(s) for the given scene or all scenes."""
    profile = get_player_profile()
    if not profile.reputation:
        return "No reputation data tracked yet."
    if scene:
        score = profile.reputation.get(scene)
        if score is None:
            return f"No reputation data for scene '{scene}'."
        return f"Reputation in {scene}: {score:+.1f}"
    lines = [
        f"{s}: {v:+.1f}" for s, v in sorted(profile.reputation.items())
    ]
    return "Reputation by scene:\n" + "\n".join(lines)
