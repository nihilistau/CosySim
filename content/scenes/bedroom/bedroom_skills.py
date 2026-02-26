"""
Bedroom Skills — MCP skill functions for the Director's Bedroom scene.

Exposes character management, stat control, environment props, interaction
mechanics, and bedroom game functions as @skill-decorated functions callable
by LMS agents via tool use.
"""
from __future__ import annotations

import logging
from typing import Optional

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
    if not scene.characters:
        return "No characters loaded."
    lines = []
    for cid, char in scene.characters.items():
        profile = scene.profiles.get(cid)
        if profile:
            stats = profile.stats.to_dict()
            loc = scene.scene_map.get_character_location(cid)
            loc_name = loc.name if loc else "unknown"
            lines.append(
                f"{char.name} ({cid}): location={loc_name}, "
                f"outfit={profile.outfit}, position={profile.position}, "
                f"feeling={profile.stats.describe()}, "
                f"arousal={stats.get('arousal', 0)}, "
                f"happiness={stats.get('happiness', 0)}, "
                f"compliance={round(profile.stats.compliance_score(0), 1)}%"
            )
    return "\n".join(lines)


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "character"],
    category=SkillCategory.GAME,
    description="Adjust a character's stat (arousal, happiness, horniness, etc).",
    cooldown=3,
)
def bedroom_adjust_stat(character_id: str = "", stat: str = "", delta: int = 0) -> str:
    """Adjust a character stat by delta amount."""
    if not character_id or not stat:
        return "Specify character_id and stat name."
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    profile = scene.profiles.get(character_id)
    if not profile:
        return f"Character {character_id} not loaded."
    profile.stats.adjust(**{stat: delta})
    try:
        from engine.mcp.state_coordinator import get_coordinator
        get_coordinator().update(character_id, source="skill_adjust", scene="bedroom", **{stat: delta})
    except Exception:
        pass
    scene._broadcast_state()
    new_val = getattr(profile.stats, stat, None)
    return f"Adjusted {character_id}.{stat} by {delta:+d} → now {new_val}."


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
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    char = scene.characters.get(character_id)
    if not char:
        return f"Character {character_id} not loaded."
    scene._inject_to_loop(char.name, f"[SCRIPTED LINE] {line}", "director")
    scene.socketio.emit("chat_message", {
        "name": char.name,
        "message": line,
        "character_id": character_id,
    })
    return f"{char.name} says: '{line}'"


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
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    char = scene.characters.get(character_id)
    if not char:
        return f"Character {character_id} not loaded."
    scene._inject_to_loop(
        "(Director whisper)", f"[WHISPER to {char.name}] {instruction}", "whisper"
    )
    return f"Whispered to {char.name}."


# ── Environment ────────────────────────────────────────────────

@skill(
    pack="bedroom",
    tags=["game", "bedroom", "environment"],
    category=SkillCategory.GAME,
    description="Add a prop to the bedroom scene.",
)
def bedroom_add_prop(prop_name: str = "", location: str = "center") -> str:
    """Place a prop in the bedroom scene."""
    if not prop_name:
        return "Specify a prop name."
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    if prop_name not in scene.room_props:
        scene.room_props.append(prop_name)
    scene._broadcast_state()
    return f"Added '{prop_name}' to the bedroom."


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "environment"],
    category=SkillCategory.GAME,
    description="Set the time of day / lighting mood.",
)
def bedroom_set_time(time_of_day: str = "night") -> str:
    """Change lighting: morning, afternoon, evening, night, midnight."""
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    valid = ["morning", "afternoon", "evening", "night", "midnight"]
    if time_of_day not in valid:
        return f"Unknown time. Options: {', '.join(valid)}"
    scene.scene_state["time_of_day"] = time_of_day
    scene._broadcast_state()
    scene.socketio.emit("time_changed", {"time": time_of_day})
    return f"Lighting set to {time_of_day}."


# ── Bedroom Game ───────────────────────────────────────────────

@skill(
    pack="bedroom",
    tags=["game", "bedroom", "intimate"],
    category=SkillCategory.GAME,
    description="Start the bedroom game (truth-or-dare / mystery) with loaded characters.",
    cooldown=15,
)
def bedroom_start_game(scenario: str = "truth_or_dare") -> str:
    """Begin an intimate bedroom game scenario."""
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    if len(scene.characters) < 2:
        return "Need at least 2 characters loaded."
    player_ids = list(scene.characters.keys())[:3]
    names = {pid: scene.characters[pid].name for pid in player_ids}
    try:
        import time as _time
        from content.scenes.bedroom.bedroom_scene import BedGameState
        scene.bed_game = BedGameState(
            active=True,
            players=player_ids,
            player_names=names,
            started_at=_time.time(),
        )
        scene._broadcast_state()
        scene.socketio.emit("bedgame_started", scene.bed_game.to_dict())
        return f"Bedroom game started with {len(player_ids)} players: {', '.join(names.values())}."
    except Exception as exc:
        return f"Failed to start game: {exc}"


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "intimate"],
    category=SkillCategory.GAME,
    description="Perform an action in the active bedroom game.",
)
def bedroom_game_action(action: str = "") -> str:
    """Submit an action in the active bedroom game."""
    if not action:
        return "What do you want to do?"
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    if not scene.bed_game.active:
        return "No game in progress."
    current = scene.bed_game.current_player_name
    scene.bed_game.history.append({
        "player_id": scene.bed_game.current_player_id,
        "action": action,
    })
    scene.bed_game.advance_turn()
    scene._broadcast_state()
    return f"Action recorded: {action} (player: {current}). Next: {scene.bed_game.current_player_name}."


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
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    # Check if scenario exists in premade list
    from content.scenes.bedroom.bedroom_scene import PREMADE_SCENARIOS
    sc = PREMADE_SCENARIOS.get(scenario)
    if sc:
        scene.active_scenario = scenario
        scene.story_beats = list(sc.get("beats", []))
        scene._broadcast_state()
        return f"Scenario '{sc.get('label', scenario)}' activated with {len(scene.story_beats)} beats."
    scene.active_scenario = scenario
    scene._broadcast_state()
    return f"Custom scenario '{scenario}' set."


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
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    msg = details or f"A {event_type} event occurs in the bedroom."
    scene._inject_to_loop("(Event)", f"[EVENT: {event_type}] {msg}", "event")
    scene.socketio.emit("scene_event", {"type": event_type, "message": msg})
    return f"Event fired: {event_type}. {details}"
