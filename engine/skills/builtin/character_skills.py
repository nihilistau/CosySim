"""
character_skills.py — Character state and relationship management skills

These skills let the LLM read and adjust the active character's emotional
state, personality traits, and relationship level as part of a conversation.
"""
from __future__ import annotations

from engine.skills.skill import skill


@skill(
    pack="character",
    description=(
        "Get the current emotional and relational state of the active character, "
        "including mood, energy, relationship level, and personality traits."
    ),
    tags=["character", "state"],
)
def get_character_state(character_id: str) -> str:
    """
    Return a formatted summary of the character's current state.

    Args:
        character_id: The character's database ID.

    Returns:
        Formatted state string, or error message.
    """
    try:
        from content.simulation.database.db import Database
        from content.simulation.character_system.character import Character

        db   = Database()
        char = Character.load(character_id, db=db)
        if not char:
            return f"Character {character_id!r} not found."

        state = char.to_dict()
        lines = [
            f"Name: {state.get('name', '?')}",
            f"Mood: {state.get('mood', '?')} | Energy: {state.get('energy', '?')}",
            f"Relationship: {state.get('relationship_level', '?')}",
            f"Arousal: {state.get('arousal', '?')}",
            "",
            "Personality traits:",
            f"  Warmth:       {state.get('warmth', 0.5):.2f}",
            f"  Formality:    {state.get('formality', 0.5):.2f}",
            f"  Humor:        {state.get('humor', 0.5):.2f}",
            f"  Flirtiness:   {state.get('flirtiness', 0.5):.2f}",
            f"  Intelligence: {state.get('intelligence', 0.5):.2f}",
            f"  Creativity:   {state.get('creativity', 0.5):.2f}",
        ]
        return "\n".join(lines)

    except Exception as exc:
        return f"Failed to get character state: {exc}"


@skill(
    pack="character",
    description=(
        "Adjust a personality trait of the character by a delta amount. "
        "Valid traits: warmth, formality, humor, flirtiness, intelligence, creativity."
    ),
    tags=["character", "traits"],
)
def adjust_trait(
    character_id: str,
    trait: str,
    delta: float,
) -> str:
    """
    Adjust one of the character's personality traits by a delta value.

    The new trait value is clamped to [0.0, 1.0].  Positive deltas increase
    the trait, negative deltas decrease it.

    Args:
        character_id: The character's database ID.
        trait:        Trait name: warmth, formality, humor, flirtiness, intelligence, creativity.
        delta:        Amount to add (e.g. 0.1 to increase, -0.05 to decrease).

    Returns:
        Confirmation with old and new value, or error message.
    """
    try:
        from content.simulation.database.db import Database
        from content.simulation.character_system.character import Character

        db   = Database()
        char = Character.load(character_id, db=db)
        if not char:
            return f"Character {character_id!r} not found."

        old_val = getattr(char, trait, None)
        if old_val is None:
            valid = "warmth, formality, humor, flirtiness, intelligence, creativity"
            return f"Unknown trait {trait!r}.  Valid traits: {valid}"

        char.adjust_trait(trait, delta)
        char.save()
        new_val = getattr(char, trait, old_val + delta)
        return f"Trait {trait!r}: {old_val:.2f} → {new_val:.2f}"

    except Exception as exc:
        return f"Failed to adjust trait: {exc}"


@skill(
    pack="character",
    description=(
        "Set the character's mood.  Mood affects the tone of their responses."
    ),
    tags=["character", "mood"],
)
def set_mood(character_id: str, mood: str) -> str:
    """
    Set the character's current mood.

    Args:
        character_id: The character's database ID.
        mood:         Mood string, e.g. "happy", "sad", "excited", "nervous".

    Returns:
        Confirmation string or error message.
    """
    try:
        from content.simulation.database.db import Database
        from content.simulation.character_system.character import Character

        db   = Database()
        char = Character.load(character_id, db=db)
        if not char:
            return f"Character {character_id!r} not found."

        char.set_mood(mood)
        char.save()
        return f"Mood set to {mood!r}."

    except Exception as exc:
        return f"Failed to set mood: {exc}"


@skill(
    pack="character",
    description=(
        "Adjust the character's relationship level with the user. "
        "Positive delta increases closeness, negative delta decreases it."
    ),
    tags=["character", "relationship"],
)
def adjust_relationship(
    character_id: str,
    delta: float,
    reason: str = "",
) -> str:
    """
    Adjust the relationship level between the character and the user.

    Args:
        character_id: The character's database ID.
        delta:        Change in relationship level (−1.0 to +1.0 range).
        reason:       Optional human-readable reason (for logging).

    Returns:
        Confirmation with old and new level, or error message.
    """
    try:
        from content.simulation.database.db import Database
        from content.simulation.character_system.character import Character

        db   = Database()
        char = Character.load(character_id, db=db)
        if not char:
            return f"Character {character_id!r} not found."

        old_level = char.relationship_level
        char.adjust_relationship(delta)
        char.save()
        new_level = char.relationship_level
        suffix    = f" (reason: {reason})" if reason else ""
        return f"Relationship: {old_level:.2f} → {new_level:.2f}{suffix}"

    except Exception as exc:
        return f"Failed to adjust relationship: {exc}"
