"""
Lounge Skills — MCP skill functions for the Jazz Lounge scene.

Exposes cocktail ordering, song requests, conversation mechanics,
and social interactions as @skill-decorated functions callable by
LMS agents via tool use.
"""
from __future__ import annotations

import logging
import random

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_lounge_scene():
    """Look up the running Lounge scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("lounge")


# ── Social & Atmosphere ────────────────────────────────────────

@skill(
    pack="lounge",
    tags=["game", "lounge", "social"],
    category=SkillCategory.SOCIAL,
    description="Get the current lounge atmosphere and character moods.",
)
def lounge_status() -> str:
    """Return lounge atmosphere, current song, and character states."""
    scene = _get_lounge_scene()
    if not scene:
        return "Lounge not active."
    state = getattr(scene, "_scene_state", {})
    if callable(getattr(state, "to_dict", None)):
        state = state.to_dict()
    song = state.get("current_song", "ambient jazz")
    mood = state.get("atmosphere", "relaxed")
    return f"Atmosphere: {mood} | Now playing: {song}"


@skill(
    pack="lounge",
    tags=["game", "lounge", "social"],
    category=SkillCategory.SOCIAL,
    description="Order a cocktail from the lounge bar.",
    cooldown=10,
)
def lounge_order_drink(drink_name: str = "old fashioned") -> str:
    """Order a drink. Each cocktail has mood and stat effects."""
    try:
        from content.scenes.lounge.lounge_mcp import COCKTAILS
    except ImportError:
        return "Bar menu unavailable."
    drink = COCKTAILS.get(drink_name.lower())
    if not drink:
        available = ", ".join(list(COCKTAILS.keys())[:8])
        return f"Unknown drink. Try: {available}"
    effects = drink.get("effects", {})
    effect_str = ", ".join(f"{k}: {v:+d}" for k, v in effects.items()) if effects else "smooth"
    return f"Ordered {drink.get('name', drink_name)}. Effects: {effect_str}."


@skill(
    pack="lounge",
    tags=["game", "lounge", "social"],
    category=SkillCategory.SOCIAL,
    description="Request a song for the lounge playlist.",
)
def lounge_request_song(song_name: str = "") -> str:
    """Request a song. The DJ will consider your taste."""
    if not song_name:
        return "What song would you like to hear?"
    return f"Song request: '{song_name}' added to the playlist."


@skill(
    pack="lounge",
    tags=["game", "lounge", "social"],
    category=SkillCategory.SOCIAL,
    description="Share a secret or start a deep conversation.",
    cooldown=30,
)
def lounge_share_secret(target: str = "", topic: str = "life") -> str:
    """Share something personal. Builds intimacy and trust."""
    if not target:
        return "Who do you want to open up to?"
    return f"You lean in and share something about {topic} with {target}..."


@skill(
    pack="lounge",
    tags=["game", "lounge", "social"],
    category=SkillCategory.SOCIAL,
    description="Use Dream Whisper — enter a character's dreamspace.",
    cooldown=60,
)
def lounge_dream_whisper(target: str = "lola") -> str:
    """Whisper into the dream of another character. Intimate and surreal."""
    return f"You close your eyes and whisper into {target}'s dreamscape..."


@skill(
    pack="lounge",
    tags=["game", "lounge", "social"],
    category=SkillCategory.SOCIAL,
    description="Use Mirror Soul — reflect someone's inner state back to them.",
    cooldown=45,
)
def lounge_mirror_soul(target: str = "") -> str:
    """Mirror back what you sense in another character's emotions."""
    if not target:
        return "Whose soul would you like to mirror?"
    return f"You reach out empathically to {target}, reflecting their inner world..."
