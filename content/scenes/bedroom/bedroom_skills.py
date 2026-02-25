"""
Bedroom Skills — MCP skill functions for the Director's Bedroom scene.

Exposes character management, stat control, environment props, interaction
mechanics, and bedroom game functions as @skill-decorated functions callable
by LMS agents via tool use.
"""
from __future__ import annotations

import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_bedroom_scene():
    """Look up the running Bedroom scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("bedroom")


# ── Character Control ──────────────────────────────────────────

@skill(
    pack="bedroom",
    tags=["game", "bedroom", "character"],
    category=SkillCategory.GAME,
    description="Get the status of all characters in the bedroom.",
)
def bedroom_character_status() -> str:
    """Return loaded characters, their stats, and positions."""
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    chars = getattr(scene, "_loaded_characters", {})
    if not chars:
        return "No characters loaded."
    lines = []
    for cid, data in chars.items():
        stats = data.get("stats", {})
        pos = data.get("position", "standing")
        lines.append(f"{cid}: pos={pos}, mood={stats.get('mood', '?')}, energy={stats.get('energy', '?')}")
    return "\n".join(lines)


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "character"],
    category=SkillCategory.GAME,
    description="Adjust a character's stat (excitement, compliance, arousal, etc).",
    cooldown=3,
)
def bedroom_adjust_stat(character_id: str = "", stat: str = "", delta: int = 0) -> str:
    """Adjust a character stat by delta amount."""
    if not character_id or not stat:
        return "Specify character_id and stat name."
    return f"Adjusted {character_id}.{stat} by {delta:+d}."


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "character"],
    category=SkillCategory.GAME,
    description="Give a character a scripted line to say.",
)
def bedroom_give_line(character_id: str = "", line: str = "") -> str:
    """Script a specific dialogue line for a character."""
    if not character_id or not line:
        return "Specify character_id and line."
    return f"{character_id} says: '{line}'"


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "character"],
    category=SkillCategory.GAME,
    description="Whisper a secret instruction to a character.",
    cooldown=10,
)
def bedroom_whisper(character_id: str = "", instruction: str = "") -> str:
    """Send a hidden directive that shapes the character's next response."""
    if not character_id or not instruction:
        return "Specify character_id and instruction."
    return f"Whispered to {character_id}."


# ── Environment ────────────────────────────────────────────────

@skill(
    pack="bedroom",
    tags=["game", "bedroom", "environment"],
    category=SkillCategory.GAME,
    description="Add a prop or piece of furniture to the bedroom.",
)
def bedroom_add_prop(prop_name: str = "", location: str = "center") -> str:
    """Place a prop in the bedroom scene."""
    if not prop_name:
        return "Specify a prop name."
    return f"Added '{prop_name}' at {location}."


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "environment"],
    category=SkillCategory.GAME,
    description="Set the time of day / lighting mood.",
)
def bedroom_set_time(time_of_day: str = "night") -> str:
    """Change lighting: morning, afternoon, evening, night, midnight."""
    valid = ["morning", "afternoon", "evening", "night", "midnight"]
    if time_of_day not in valid:
        return f"Unknown time. Options: {', '.join(valid)}"
    return f"Lighting set to {time_of_day}."


# ── Bedroom Game ───────────────────────────────────────────────

@skill(
    pack="bedroom",
    tags=["game", "bedroom", "intimate"],
    category=SkillCategory.GAME,
    description="Start the bedroom game with loaded characters.",
    cooldown=15,
)
def bedroom_start_game(scenario: str = "default") -> str:
    """Begin an intimate bedroom game scenario."""
    return f"Bedroom game started: scenario '{scenario}'."


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "intimate"],
    category=SkillCategory.GAME,
    description="Perform an action in the bedroom game.",
)
def bedroom_game_action(action: str = "") -> str:
    """Submit an action in the active bedroom game."""
    if not action:
        return "What do you want to do?"
    return f"Bedroom action: {action}"


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "intimate"],
    category=SkillCategory.GAME,
    description="Set the scene scenario and mood.",
)
def bedroom_set_scenario(scenario: str = "", mood: str = "") -> str:
    """Configure the bedroom scenario and ambient mood."""
    if not scenario:
        return "Specify a scenario name."
    msg = f"Scenario set to '{scenario}'."
    if mood:
        msg += f" Mood: {mood}."
    return msg


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "event"],
    category=SkillCategory.GAME,
    description="Fire a custom event in the bedroom scene.",
    cooldown=10,
)
def bedroom_fire_event(event_type: str = "", details: str = "") -> str:
    """Trigger a custom narrative or game event."""
    if not event_type:
        return "Specify event type."
    return f"Event fired: {event_type}. {details}"
