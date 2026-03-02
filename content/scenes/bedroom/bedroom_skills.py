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


# ── Penthouse v0.68 — New Skills ──────────────────────────────────────


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "scenarios"],
    category=SkillCategory.GAME,
    description="Get current scenario options from the content pool.",
)
def get_scenario_options(intensity: int = 2, tags: str = "") -> str:
    """Return available scenarios filtered by intensity level and optional tags.

    Args:
        intensity: Desired intensity level 1-5 (default 2).
        tags: Comma-separated tag filter (e.g. "romantic,slow").

    Returns:
        JSON-serialisable string of scenario objects, or error message.
    """
    import json

    scene = _get_bedroom_scene()

    # Try ContentEngine first
    try:
        from engine.content.content_engine import get_content_engine
        engine = get_content_engine()
        result = engine.get_scenarios(scene="bedroom", intensity=intensity, tags=tags)
        return json.dumps(result, ensure_ascii=False)
    except Exception:
        pass

    # Fallback: built-in PREMADE_SCENARIOS
    try:
        from content.scenes.bedroom.bedroom_scene import PREMADE_SCENARIOS
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        options = []
        for sid, sc in PREMADE_SCENARIOS.items():
            options.append({
                "id": sid,
                "label": sc.get("label", sid),
                "emoji": sc.get("emoji", "🎭"),
                "intensity": intensity,
            })
        return json.dumps(options[:20], ensure_ascii=False)
    except Exception as exc:
        return f"Error loading scenarios: {exc}"


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "director"],
    category=SkillCategory.GAME,
    description="Load a scenario into the scene director.",
)
def load_scenario(scenario_id: str = "") -> str:
    """Activate a scenario and return the opening director beat.

    Args:
        scenario_id: Scenario identifier key (e.g. "romantic_evening").

    Returns:
        Opening beat instruction string, or error message.
    """
    if not scenario_id:
        return "Specify scenario_id."
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."

    # Try SceneDirector
    try:
        from engine.director.scene_director import get_scene_director
        director = get_scene_director("bedroom")
        beat = director.load_scenario(scenario_id)
        return f"Scenario loaded. Beat: {beat}"
    except Exception:
        pass

    # Fallback: built-in scenario
    from content.scenes.bedroom.bedroom_scene import PREMADE_SCENARIOS
    sc = PREMADE_SCENARIOS.get(scenario_id)
    if not sc:
        return f"Unknown scenario: {scenario_id}. Available: {', '.join(PREMADE_SCENARIOS.keys())}"

    scene.active_scenario = scenario_id
    scene.story_beats = list(sc.get("beats", []))
    scene._broadcast_state()
    opening = sc.get("opening", f"Scenario '{sc.get('label', scenario_id)}' begins.")
    scene.socketio.emit("director_beat", {
        "beat": {"type": "opening", "instruction": opening},
        "scenario_id": scenario_id,
    })
    return f"Loaded '{sc.get('label', scenario_id)}'. Opening: {opening[:120]}..."


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "memory"],
    category=SkillCategory.GAME,
    description="Check what the character remembers about the player.",
)
def recall_memories(character_id: str = "") -> str:
    """Retrieve recent memories the character has about the player.

    Args:
        character_id: The character whose memory to query.

    Returns:
        Formatted string of memories, or a fallback message.
    """
    if not character_id:
        return "Specify character_id."
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    if character_id not in scene.characters:
        return f"Character {character_id} not loaded."

    # Try CharacterMemory engine
    try:
        from engine.characters.memory import get_character_memory
        mem = get_character_memory()
        memories = mem.recall(character_id, subject="player", limit=10)
        if not memories:
            return f"{scene.characters[character_id].name} has no memories of the player yet."
        lines = [f"- [{m.get('weight', 0):.1f}] {m.get('description', '')}" for m in memories]
        return f"Memories of {scene.characters[character_id].name}:\n" + "\n".join(lines)
    except Exception:
        pass

    return f"{scene.characters[character_id].name} has a fresh perspective — no memories stored yet."


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "memory"],
    category=SkillCategory.GAME,
    description="Record a memorable moment in character memory.",
    cooldown=5,
)
def remember_moment(
    character_id: str = "",
    description: str = "",
    weight: float = 0.7,
) -> str:
    """Store a memorable moment for a character to recall later.

    Args:
        character_id: The character forming the memory.
        description: Human-readable description of the moment.
        weight: Emotional weight 0.0–1.0 (default 0.7).

    Returns:
        Confirmation string or error message.
    """
    if not character_id or not description:
        return "Specify character_id and description."
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    if character_id not in scene.characters:
        return f"Character {character_id} not loaded."

    char_name = scene.characters[character_id].name
    weight = max(0.0, min(1.0, float(weight)))

    try:
        from engine.characters.memory import get_character_memory
        mem = get_character_memory()
        mem.store(
            character_id=character_id,
            subject="player",
            description=description,
            weight=weight,
        )
        scene.socketio.emit("memory_update", {
            "character_id": character_id,
            "description": description,
            "weight": weight,
        })
        return f"Memory stored for {char_name} (weight={weight:.2f}): {description}"
    except Exception as exc:
        return f"Memory engine unavailable ({exc}). Moment noted locally."


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "character"],
    category=SkillCategory.GAME,
    description="Get current emotion levels for a character.",
)
def get_emotion_levels(character_id: str = "") -> str:
    """Return the full emotion stat vector for a character.

    Args:
        character_id: Character to query.

    Returns:
        Formatted stats string with all 10 emotion dimensions.
    """
    if not character_id:
        return "Specify character_id."
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."
    profile = scene.profiles.get(character_id)
    if not profile:
        return f"Character {character_id} not loaded."

    stats = profile.stats.to_dict()
    char_name = scene.characters[character_id].name if character_id in scene.characters else character_id
    lines = [f"Emotion levels for {char_name}:"]
    for stat, value in sorted(stats.items()):
        bar = "█" * max(0, int(float(value) / 10)) + "░" * max(0, 10 - int(float(value) / 10))
        lines.append(f"  {stat:14s} [{bar}] {float(value):5.1f}")
    lines.append(f"\n  Mood: {profile.stats.describe()}")
    lines.append(f"  Compliance: {round(profile.stats.compliance_score(0), 1)}%")
    return "\n".join(lines)


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "economy"],
    category=SkillCategory.GAME,
    description="Unlock premium content with player credits.",
    cooldown=10,
)
def unlock_premium(content_id: str = "", cost: int = 100) -> str:
    """Spend credits to unlock a premium scenario or content item.

    Args:
        content_id: Identifier of the content to unlock.
        cost: Credit cost (default 100).

    Returns:
        Success confirmation or insufficient-credits message.
    """
    if not content_id:
        return "Specify content_id."
    scene = _get_bedroom_scene()
    if not scene:
        return "Bedroom not active."

    try:
        from engine.economy.economy import get_economy_manager
        economy = get_economy_manager()
        balance = economy.get_balance("player")
        if balance < cost:
            return (
                f"Insufficient credits. Need {cost} ₵, have {balance} ₵. "
                f"Earn more by completing scenarios."
            )
        success = economy.spend("player", cost, reason=f"unlock:{content_id}")
        if success:
            new_balance = economy.get_balance("player")
            scene.socketio.emit("economy_update", {
                "balance": new_balance,
                "currency": "₵",
                "event": "unlock",
                "content_id": content_id,
            })
            scene.socketio.emit("premium_unlocked", {"content_id": content_id})
            return f"Unlocked '{content_id}' for {cost} ₵. New balance: {new_balance} ₵."
        return f"Transaction failed for '{content_id}'."
    except Exception:
        # Economy engine not wired — grant free access in dev
        scene.socketio.emit("premium_unlocked", {"content_id": content_id})
        return f"Unlocked '{content_id}' (economy offline — dev mode)."


# ── Living World Skills ────────────────────────────────────────────────


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "world"],
    category=SkillCategory.ENVIRONMENT,
    description="Get world context affecting the bedroom — recent events, Lola's mood modifier based on player status",
)
def get_bedroom_world_context() -> str:
    """Return a formatted summary of living world context for the bedroom.

    Returns:
        Multi-line string with world events, credits, rep, heat, and mood.
    """
    scene = _get_bedroom_scene()
    if not scene:
        # Fall back to calling the logic directly
        from engine.world.world_sim import get_event_log
        from engine.world.player_state import get_player_state
        try:
            events = get_event_log(limit=20)
            relevant = [e for e in events if e.scene == "bedroom" or e.intensity >= 2.0][:3]
            ctx_lines = [f"• {e.title}: {e.description}" for e in relevant]
            ps = get_player_state()
            state = ps.to_dict()
            credits = state.get("credits", 0)
            rep = state.get("reputation", 50)
            heat = state.get("heat", 0)
        except Exception as exc:
            return f"World context unavailable: {exc}"
        if heat >= 70:
            mood = "tense"
        elif rep >= 70:
            mood = "impressed"
        elif rep <= 30:
            mood = "cold"
        else:
            mood = "neutral"
        lines = [f"Credits: {credits} ₵  Rep: {rep}  Heat: {heat}  Mood: {mood}"]
        lines += ctx_lines or ["No notable events."]
        return "\n".join(lines)

    ctx = scene._get_world_context_for_character()
    lines = [
        f"Credits: {ctx['credits']} ₵  Rep: {ctx['reputation']}  "
        f"Heat: {ctx['heat']}  Mood: {ctx['mood_modifier']}"
    ]
    for item in ctx["world_context"]:
        lines.append(f"• {item}")
    if not ctx["world_context"]:
        lines.append("No notable world events.")
    return "\n".join(lines)


@skill(
    pack="bedroom",
    tags=["game", "bedroom", "reputation"],
    category=SkillCategory.SOCIAL,
    description="Update player reputation based on bedroom interactions",
)
def update_bedroom_reputation(delta: int = 0, reason: str = "bedroom_interaction") -> str:
    """Adjust player reputation from a bedroom interaction outcome.

    Args:
        delta: Amount to change reputation (positive or negative).
        reason: Context label stored in the player state log.

    Returns:
        Confirmation string with new reputation value.
    """
    if delta == 0:
        return "No reputation change (delta=0)."
    try:
        from engine.world.player_state import get_player_state
        ps = get_player_state()
        new_rep = ps.update_reputation(delta, reason)
        direction = "increased" if delta > 0 else "decreased"
        return f"Reputation {direction} by {abs(delta):+d} ({reason}). New reputation: {new_rep}."
    except Exception as exc:
        return f"Reputation update failed: {exc}"
