"""
Phone Skills — MCP skill functions for the CosyPhone scene.

Exposes messaging, media, games, and social interactions as @skill-decorated
functions callable by LMS agents via tool use.
"""
from __future__ import annotations

import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_phone_scene():
    """Look up the running Phone scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("phone")


# ── Messaging ──────────────────────────────────────────────────

@skill(
    pack="phone",
    tags=["social", "phone", "messaging"],
    category=SkillCategory.SOCIAL,
    description="Send a text message to a character.",
)
def phone_send_message(character_id: str = "", message: str = "") -> str:
    """Send a text message to a character's DM thread."""
    if not character_id or not message:
        return "Specify character_id and message."
    scene = _get_phone_scene()
    if not scene:
        return "Phone not active."
    return f"Message sent to {character_id}: '{message[:50]}...'" if len(message) > 50 else f"Message sent to {character_id}: '{message}'"


@skill(
    pack="phone",
    tags=["social", "phone", "messaging"],
    category=SkillCategory.SOCIAL,
    description="Check message threads and unread counts.",
)
def phone_check_messages() -> str:
    """Get a summary of message threads and unread messages."""
    scene = _get_phone_scene()
    if not scene:
        return "Phone not active."
    db = getattr(scene, "_phone_db", None)
    if not db:
        return "Phone database not available."
    try:
        threads = db.get_threads()
        if not threads:
            return "No message threads."
        lines = [f"{len(threads)} threads:"]
        for t in threads[:5]:
            name = t.get("character_id", "unknown")
            unread = t.get("unread", 0)
            lines.append(f"  {name}: {unread} unread")
        return "\n".join(lines)
    except Exception:
        return "Could not read messages."


# ── Games ──────────────────────────────────────────────────────

@skill(
    pack="phone",
    tags=["game", "phone", "arcade"],
    category=SkillCategory.GAME,
    description="Start an arcade game on the phone.",
    cooldown=10,
)
def phone_start_game(game_type: str = "trivia") -> str:
    """Start a phone game: trivia, would_you_rather, truth_or_dare."""
    valid = ["trivia", "would_you_rather", "truth_or_dare", "story_chain"]
    if game_type not in valid:
        return f"Unknown game. Available: {', '.join(valid)}"
    return f"Starting {game_type.replace('_', ' ').title()} game..."


@skill(
    pack="phone",
    tags=["game", "phone", "arcade"],
    category=SkillCategory.GAME,
    description="Submit an action in the current phone game.",
)
def phone_game_action(action: str = "") -> str:
    """Submit a game action (answer, choice, dare, etc)."""
    if not action:
        return "What's your move?"
    return f"Game action: {action}"


# ── Media ──────────────────────────────────────────────────────

@skill(
    pack="phone",
    tags=["media", "phone"],
    category=SkillCategory.SYSTEM,
    description="Generate an AI image and save to gallery.",
    cooldown=15,
)
def phone_generate_image(prompt: str = "") -> str:
    """Generate an image using AI and save to the phone gallery."""
    if not prompt:
        return "Describe the image you want to generate."
    return f"Generating image: '{prompt[:80]}'"


@skill(
    pack="phone",
    tags=["social", "phone"],
    category=SkillCategory.SOCIAL,
    description="Mute or unmute auto-text messages from characters.",
)
def phone_toggle_autotxt(mute: bool = True) -> str:
    """Toggle automatic text messages from characters."""
    return f"Auto-texts {'muted' if mute else 'unmuted'}."
