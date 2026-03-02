"""
npc_backstory_skills.py — NPC backstory retrieval and storage skills

Skill pack: ``character``

Retrieve and persist character background information, used by the portrait
hover panel and any LLM agent that needs character context.
"""
from __future__ import annotations

import logging

from engine.skills.skill import skill

logger = logging.getLogger(__name__)

# Built-in fallback backstories for the five seeded characters
CHARACTER_BACKSTORIES: dict[str, str] = {
    "aria": (
        "Aria is a distributed AI assistant woven into the CosySim fabric. "
        "She has no physical form but exists as whispers in every scene. "
        "Her origins are classified."
    ),
    "lola": (
        "Lola runs THE PENTHOUSE with an iron fist wrapped in silk. "
        "Once a struggling actress, she reinvented herself through connections "
        "most would rather forget. She knows everyone's price."
    ),
    "viktor": (
        "Viktor is a former intelligence operative who now freelances for whoever "
        "pays best. Three countries want him extradited. He speaks six languages "
        "and trusts no one."
    ),
    "frankie": (
        "Frankie grew up on the casino floor, taught to count cards before he "
        "could drive. He's deeply in debt to The House but smiles through it. "
        "His loyalty is rented, not owned."
    ),
    "mira": (
        "Mira disappeared from a tech conglomerate's R&D division taking 40 TB "
        "of proprietary data. She's been in the underground ever since, selling "
        "access and staying one step ahead."
    ),
}


@skill(
    pack="character",
    description="Get an NPC's backstory and background information.",
    category="MEMORY",
    tags=["character", "backstory", "lore", "npc"],
)
def get_npc_backstory(character_id: str) -> str:
    """Retrieve backstory from Nexus cache or built-in defaults.

    Args:
        character_id: Character identifier (e.g. 'lola', 'viktor').

    Returns:
        Backstory string, or a graceful "unknown" message.
    """
    # Try Nexus first
    try:
        from engine.nexus.client import get_nexus_client

        client = get_nexus_client()
        results = client.search(f"character backstory {character_id}")
        if results:
            content = results[0].get("content", "")
            if content:
                return content
    except Exception:
        pass

    # Fall back to built-in
    backstory = CHARACTER_BACKSTORIES.get(character_id.lower())
    if backstory:
        return backstory

    return f"No backstory found for '{character_id}'. Character history is classified or unknown."


@skill(
    pack="character",
    description="Get a brief formatted character profile summary.",
    category="MEMORY",
    tags=["character", "profile", "summary"],
)
def get_character_profile(character_id: str) -> str:
    """Return a brief formatted character profile.

    Args:
        character_id: Character identifier.

    Returns:
        Markdown-formatted string: bold name followed by backstory.
    """
    backstory = get_npc_backstory(character_id)
    return f"**{character_id.title()}**\n{backstory}"


@skill(
    pack="character",
    description="Store or update an NPC backstory in the Nexus knowledge base.",
    category="MEMORY",
    tags=["character", "backstory", "store", "nexus"],
)
def store_npc_backstory(character_id: str, backstory: str) -> str:
    """Persist a character backstory to Nexus.

    Args:
        character_id: Character identifier.
        backstory: Full backstory text to store.

    Returns:
        Confirmation message, or error string on failure.
    """
    try:
        from engine.nexus.client import get_nexus_client

        client = get_nexus_client()
        client.add_entry(
            f"Character backstory: {character_id}",
            backstory,
            content_type="memory",
            category="characters",
        )
        return f"Backstory stored for '{character_id}'."
    except Exception as exc:
        return f"Failed to store backstory: {exc}"
