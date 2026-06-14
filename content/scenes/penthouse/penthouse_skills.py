"""
Penthouse Skills — MCP skill functions for The Penthouse scene.

Exposes character management, stat control, environment props, interaction
mechanics, and penthouse game functions as @skill-decorated functions callable
by LMS agents via tool use.
"""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_penthouse_scene():
    """Look up the running penthouse scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("penthouse")


def _validate_character(character_id: str, scene=None):
    """Validate character exists in running penthouse scene.

    Args:
        character_id: Character to validate.
        scene: Optional pre-fetched scene instance.

    Returns:
        Tuple of (scene, error_message). If error_message is None, scene is valid.
    """
    if not character_id:
        return None, "Specify a character_id."
    if scene is None:
        scene = _get_penthouse_scene()
    if not scene:
        return None, "Penthouse not active."
    if character_id not in scene.characters:
        return None, f"Character {character_id} not loaded."
    return scene, None


# ── Character Control ──────────────────────────────────────────

@skill(
    pack="penthouse",
    tags=["game", "penthouse", "character"],
    category=SkillCategory.GAME,
    description="Get the status of all characters in the penthouse.",
)
def penthouse_character_status() -> str:
    """Return loaded characters, their stats, and positions."""
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
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
    pack="penthouse",
    tags=["game", "penthouse", "character"],
    category=SkillCategory.GAME,
    description="Adjust a character's stat (arousal, happiness, horniness, etc).",
    cooldown=3,
)
def penthouse_adjust_stat(character_id: str = "", stat: str = "", delta: int = 0) -> str:
    """Adjust a character stat by delta amount."""
    if not character_id or not stat:
        return "Specify character_id and stat name."
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    profile = scene.profiles.get(character_id)
    if not profile:
        return f"Character {character_id} not loaded."
    profile.stats.adjust(**{stat: delta})
    try:
        from engine.mcp.state_coordinator import get_coordinator
        get_coordinator().update(character_id, source="skill_adjust", scene="penthouse", **{stat: delta})
    except Exception as exc:
        logger.warning("State coordinator update failed: %s", exc)
    scene._broadcast_state()
    new_val = getattr(profile.stats, stat, None)
    return f"Adjusted {character_id}.{stat} by {delta:+d} → now {new_val}."


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "character"],
    category=SkillCategory.GAME,
    description="Give a character a scripted line to say.",
)
def penthouse_give_line(character_id: str = "", line: str = "") -> str:
    """Script a specific dialogue line for a character."""
    if not character_id or not line:
        return "Specify character_id and line."
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
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
    pack="penthouse",
    tags=["game", "penthouse", "character"],
    category=SkillCategory.GAME,
    description="Whisper a secret instruction to a character.",
    cooldown=10,
)
def penthouse_whisper(character_id: str = "", instruction: str = "") -> str:
    """Send a hidden directive that shapes the character's next response."""
    if not character_id or not instruction:
        return "Specify character_id and instruction."
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    char = scene.characters.get(character_id)
    if not char:
        return f"Character {character_id} not loaded."
    scene._inject_to_loop(
        "(Director whisper)", f"[WHISPER to {char.name}] {instruction}", "whisper"
    )
    return f"Whispered to {char.name}."


# ── Environment ────────────────────────────────────────────────

@skill(
    pack="penthouse",
    tags=["game", "penthouse", "environment"],
    category=SkillCategory.GAME,
    description="Add a prop to the penthouse scene.",
)
def penthouse_add_prop(prop_name: str = "", location: str = "center") -> str:
    """Place a prop in the penthouse scene."""
    if not prop_name:
        return "Specify a prop name."
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    if prop_name not in scene.room_props:
        scene.room_props.append(prop_name)
    scene._broadcast_state()
    return f"Added '{prop_name}' to the penthouse."


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "environment"],
    category=SkillCategory.GAME,
    description="Set the time of day / lighting mood.",
)
def penthouse_set_time(time_of_day: str = "night") -> str:
    """Change lighting: morning, afternoon, evening, night, midnight."""
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    valid = ["morning", "afternoon", "evening", "night", "midnight"]
    if time_of_day not in valid:
        return f"Unknown time. Options: {', '.join(valid)}"
    scene.scene_state["time_of_day"] = time_of_day
    scene._broadcast_state()
    scene.socketio.emit("time_changed", {"time": time_of_day})
    return f"Lighting set to {time_of_day}."


# ── Penthouse Game ───────────────────────────────────────────────

@skill(
    pack="penthouse",
    tags=["game", "penthouse", "intimate"],
    category=SkillCategory.GAME,
    description="Start the penthouse game (truth-or-dare / mystery) with loaded characters.",
    cooldown=15,
)
def penthouse_start_game(scenario: str = "truth_or_dare") -> str:
    """Begin an intimate penthouse game scenario."""
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    if len(scene.characters) < 2:
        return "Need at least 2 characters loaded."
    player_ids = list(scene.characters.keys())[:3]
    names = {pid: scene.characters[pid].name for pid in player_ids}
    try:
        import time as _time
        from content.scenes.penthouse.penthouse_scene import BedGameState
        scene.bed_game = BedGameState(
            active=True,
            players=player_ids,
            player_names=names,
            started_at=_time.time(),
        )
        scene._broadcast_state()
        scene.socketio.emit("bedgame_started", scene.bed_game.to_dict())
        return f"Penthouse Game started with {len(player_ids)} players: {', '.join(names.values())}."
    except Exception as exc:
        return f"Failed to start game: {exc}"


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "intimate"],
    category=SkillCategory.GAME,
    description="Perform an action in the active penthouse game.",
)
def penthouse_game_action(action: str = "") -> str:
    """Submit an action in the active penthouse game."""
    if not action:
        return "What do you want to do?"
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    if not scene.bed_game.active:
        return "No game in progress."
    current = scene.bed_game.current_player_name
    current_pid = scene.bed_game.current_player_id
    # Resolve action metadata (explicit_level / mood) so the 3D paired-pose
    # chain can fire. Falls back to a mid-tier custom action when unmatched.
    # v1.62.0 [2026-06-15] — wire bed-game actions to paired pose animations.
    # v1.62.0 [2026-06-15] — shared mood mapping via bedgame_action_pose_meta.
    from content.scenes.penthouse.penthouse_scene import bedgame_action_pose_meta
    _meta = bedgame_action_pose_meta(action)
    explicit_level = _meta["explicit_level"]
    description = _meta["description"]
    mood_hint = _meta["mood_hint"]
    # Target = the next distinct player in the game (the pose's receiver).
    target_id = None
    for pid in scene.bed_game.players:
        if pid != current_pid:
            target_id = pid
            break
    scene.bed_game.history.append({
        "player_id": current_pid,
        "action": action,
        "target_id": target_id,
        "explicit_level": explicit_level,
    })
    involved = [current_pid] + ([target_id] if target_id else [])
    pose_eligible = True
    if hasattr(scene, "_bedgame_pose_eligible"):
        pose_eligible = scene._bedgame_pose_eligible(involved, explicit_level)
    scene.bed_game.advance_turn()
    scene.socketio.emit("bedgame_action", {
        "round": scene.bed_game.round_number,
        "player": current,
        "player_id": current_pid,
        "action": action,
        "description": description,
        "target_id": target_id,
        "explicit_level": explicit_level,
        "mood_hint": mood_hint,
        "pose_eligible": pose_eligible,
        "next_player": scene.bed_game.current_player_name,
        "game_over": False,
    })
    scene._broadcast_state()
    return f"Action recorded: {action} (player: {current}). Next: {scene.bed_game.current_player_name}."


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "intimate"],
    category=SkillCategory.GAME,
    description="Set the scene scenario and mood.",
)
def penthouse_set_scenario(scenario: str = "", mood: str = "") -> str:
    """Configure the penthouse scenario and ambient mood."""
    if not scenario:
        return "Specify a scenario name."
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    # Check if scenario exists in premade list
    from content.scenes.penthouse.penthouse_scene import PREMADE_SCENARIOS
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
    pack="penthouse",
    tags=["game", "penthouse", "event"],
    category=SkillCategory.GAME,
    description="Fire a custom event in the penthouse scene.",
    cooldown=10,
)
def penthouse_fire_event(event_type: str = "", details: str = "") -> str:
    """Trigger a custom narrative or game event."""
    if not event_type:
        return "Specify event type."
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    msg = details or f"A {event_type} event occurs in the penthouse."
    scene._inject_to_loop("(Event)", f"[EVENT: {event_type}] {msg}", "event")
    scene.socketio.emit("scene_event", {"type": event_type, "message": msg})
    return f"Event fired: {event_type}. {details}"


# ── Penthouse v0.68 — New Skills ──────────────────────────────────────


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "scenarios"],
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

    scene = _get_penthouse_scene()

    # Try ContentEngine first
    try:
        from engine.content.content_engine import get_content_engine
        engine = get_content_engine()
        result = engine.get_scenarios(scene="penthouse", intensity=intensity, tags=tags)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Scenario engine lookup failed: %s", exc)

    # Fallback: built-in PREMADE_SCENARIOS
    try:
        from content.scenes.penthouse.penthouse_scene import PREMADE_SCENARIOS
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
    pack="penthouse",
    tags=["game", "penthouse", "director"],
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
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."

    # Try SceneDirector
    try:
        from engine.director.scene_director import get_scene_director
        director = get_scene_director("penthouse")
        beat = director.load_scenario(scenario_id)
        return f"Scenario loaded. Beat: {beat}"
    except Exception as exc:
        logger.warning("Scenario load failed: %s", exc)

    # Fallback: built-in scenario
    from content.scenes.penthouse.penthouse_scene import PREMADE_SCENARIOS
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
    pack="penthouse",
    tags=["game", "penthouse", "memory"],
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
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
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
    except Exception as exc:
        logger.warning("Memory recall failed: %s", exc)

    return f"{scene.characters[character_id].name} has a fresh perspective— no memories stored yet."


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "memory"],
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
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
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
    pack="penthouse",
    tags=["game", "penthouse", "character"],
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
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
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
    pack="penthouse",
    tags=["game", "penthouse", "economy"],
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
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."

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
    pack="penthouse",
    tags=["game", "penthouse", "world"],
    category=SkillCategory.ENVIRONMENT,
    description="Get world context affecting the penthouse — recent events, Lola's mood modifier based on player status",
)
def get_penthouse_world_context() -> str:
    """Return a formatted summary of living world context for the penthouse.

    Returns:
        Multi-line string with world events, credits, rep, heat, and mood.
    """
    scene = _get_penthouse_scene()
    if not scene:
        # Fall back to calling the logic directly
        from engine.world.world_sim import get_event_log
        from engine.world.player_state import get_player_state
        try:
            events = get_event_log(limit=20)
            relevant = [e for e in events if e.scene == "penthouse" or e.intensity >= 2.0][:3]
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
    pack="penthouse",
    tags=["game", "penthouse", "reputation"],
    category=SkillCategory.SOCIAL,
    description="Update player reputation based on penthouse interactions",
)
def update_penthouse_reputation(delta: int = 0, reason: str = "penthouse_interaction") -> str:
    """Adjust player reputation from a penthouse interaction outcome.

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


# ── Animation Control ──────────────────────────────────────────

VALID_ANIM_STATES = [
    "idle", "walk", "run",
    "sit", "sit_cross", "sit_lean", "sit_floor",
    "lean", "arms_crossed", "hands_behind",
    "lie", "lie_side", "lie_front", "lounge",
    "kneel", "kneel_sit", "all_fours", "crawl", "sprawl",
    "interact", "drink", "gaze", "warm", "primp", "bathe",
    "dance_slow", "dance_sway", "stretch", "undress", "massage",
    "beckon", "hair_flip", "blow_kiss", "shrug", "phone", "smoke", "flirt",
    "embrace", "kiss_standing", "lap_sit", "straddle", "ride",
    "going_down", "missionary", "doggy", "spooning",
    "dominant_pose", "submissive", "seductive_pose", "intimate_touch",
    "pose",
]

VALID_EXPRESSIONS = [
    "neutral", "happy", "aroused", "seductive", "orgasm",
    "sad", "angry", "fear", "surprised", "shy", "drunk",
    "sleepy", "dominant", "disgusted", "bored", "playful",
]


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "animation"],
    category=SkillCategory.GAME,
    description=(
        "Set a character's animation state. States include: idle, walk, run, "
        "sit, lie, kneel, all_fours, dance_slow, dance_sway, undress, massage, "
        "embrace, kiss_standing, lap_sit, straddle, ride, going_down, missionary, "
        "doggy, spooning, dominant_pose, submissive, seductive_pose, intimate_touch, "
        "flirt, stretch, beckon, hair_flip, blow_kiss, shrug, phone, smoke, pose."
    ),
    cooldown=1,
)
def penthouse_set_animation(character_id: str = "", state: str = "idle") -> str:
    """Set a character's 3D animation state.

    Args:
        character_id: The character identifier (e.g. 'lola', 'viktor').
        state: Animation state name from the available states list.

    Returns:
        Confirmation of the animation change.
    """
    if not character_id:
        return "Specify character_id."
    if state not in VALID_ANIM_STATES:
        return f"Unknown state '{state}'. Valid: {', '.join(VALID_ANIM_STATES[:20])}..."
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    if character_id not in scene.characters:
        return f"Character {character_id} not loaded."
    try:
        scene.socketio.emit("set_animation", {
            "character_id": character_id,
            "state": state,
        })
        return f"Set {character_id} animation to '{state}'."
    except Exception as exc:
        return f"Animation change failed: {exc}"


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "animation"],
    category=SkillCategory.GAME,
    description=(
        "Set a character's facial expression. Options: neutral, happy, aroused, "
        "seductive, orgasm, sad, angry, fear, surprised, shy, drunk, sleepy, "
        "dominant, disgusted, bored, playful."
    ),
    cooldown=1,
)
def penthouse_set_expression(character_id: str = "", expression: str = "neutral") -> str:
    """Set a character's facial expression.

    Args:
        character_id: The character identifier.
        expression: Expression name from available presets.

    Returns:
        Confirmation of expression change.
    """
    if not character_id:
        return "Specify character_id."
    if expression not in VALID_EXPRESSIONS:
        return f"Unknown expression '{expression}'. Valid: {', '.join(VALID_EXPRESSIONS)}"
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    if character_id not in scene.characters:
        return f"Character {character_id} not loaded."
    try:
        scene.socketio.emit("set_expression", {
            "character_id": character_id,
            "expression": expression,
        })
        return f"Set {character_id} expression to '{expression}'."
    except Exception as exc:
        return f"Expression change failed: {exc}"


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "animation"],
    category=SkillCategory.GAME,
    description=(
        "Trigger a paired/interaction animation between two characters. "
        "Examples: embrace, kiss_standing, lap_sit, straddle, ride, going_down, "
        "missionary, doggy, spooning, massage, dance_slow, intimate_touch."
    ),
    cooldown=2,
)
def penthouse_paired_animation(
    character_id_1: str = "",
    character_id_2: str = "",
    animation: str = "",
) -> str:
    """Start a paired animation between two characters.

    Args:
        character_id_1: First character (typically initiator/active role).
        character_id_2: Second character (typically receiver/passive role).
        animation: The paired animation state name.

    Returns:
        Confirmation of the paired animation start.
    """
    if not character_id_1 or not character_id_2:
        return "Specify both character_id_1 and character_id_2."
    if not animation:
        return "Specify animation name."
    paired_states = [
        "embrace", "kiss_standing", "lap_sit", "straddle", "ride",
        "going_down", "missionary", "doggy", "spooning",
        "dominant_pose", "submissive", "intimate_touch",
        "massage", "dance_slow",
    ]
    if animation not in paired_states:
        return f"'{animation}' is not a paired animation. Valid: {', '.join(paired_states)}"
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    if character_id_1 not in scene.characters:
        return f"Character {character_id_1} not loaded."
    if character_id_2 not in scene.characters:
        return f"Character {character_id_2} not loaded."
    try:
        scene.socketio.emit("paired_animation", {
            "character_id_1": character_id_1,
            "character_id_2": character_id_2,
            "animation": animation,
        })
        return (
            f"Started paired animation '{animation}' between "
            f"{character_id_1} and {character_id_2}."
        )
    except Exception as exc:
        return f"Paired animation failed: {exc}"


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "animation"],
    category=SkillCategory.GAME,
    description="List all available animation states and their categories.",
)
def penthouse_list_animations() -> str:
    """Return all available animation states grouped by category."""
    categories = {
        "Basic": ["idle", "walk", "run"],
        "Seated": ["sit", "sit_cross", "sit_lean", "sit_floor"],
        "Standing": ["lean", "arms_crossed", "hands_behind"],
        "Lying": ["lie", "lie_side", "lie_front", "lounge"],
        "Ground": ["kneel", "kneel_sit", "all_fours", "crawl", "sprawl"],
        "Furniture": ["interact", "drink", "gaze", "warm", "primp", "bathe"],
        "Action": [
            "dance_slow", "dance_sway", "stretch", "undress", "massage",
            "beckon", "hair_flip", "blow_kiss", "shrug", "phone", "smoke", "flirt",
        ],
        "Intimate": [
            "embrace", "kiss_standing", "lap_sit", "straddle", "ride",
            "going_down", "missionary", "doggy", "spooning",
            "dominant_pose", "submissive", "seductive_pose", "intimate_touch",
        ],
        "Special": ["pose"],
    }
    lines = ["Animation States:"]
    for cat, states in categories.items():
        lines.append(f"\n{cat}: {', '.join(states)}")
    lines.append(f"\nExpressions: {', '.join(VALID_EXPRESSIONS)}")
    return "\n".join(lines)


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "animation", "clothing"],
    category=SkillCategory.GAME,
    description=(
        "Change a character's outfit. Use outfit names from the wardrobe config."
    ),
    cooldown=2,
)
def penthouse_change_outfit(character_id: str = "", outfit: str = "") -> str:
    """Change a character's current outfit with animation.

    Args:
        character_id: The character identifier.
        outfit: Outfit name from available wardrobe (e.g. 'casual', 'lingerie', 'nude').

    Returns:
        Confirmation of outfit change.
    """
    if not character_id or not outfit:
        return "Specify character_id and outfit."
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    profile = scene.profiles.get(character_id)
    if not profile:
        return f"Character {character_id} not loaded."
    old_outfit = profile.outfit
    profile.outfit = outfit
    try:
        scene.socketio.emit("outfit_change", {
            "character_id": character_id,
            "outfit": outfit,
            "old_outfit": old_outfit,
            "animate": True,
        })
    except Exception as exc:
        logger.warning("Interaction chain emit failed: %s", exc)
    scene._broadcast_state()
    return f"Changed {character_id} outfit from '{old_outfit}' to '{outfit}'."


@skill(
    pack="penthouse",
    tags=["game", "penthouse", "animation"],
    category=SkillCategory.GAME,
    description=(
        "Trigger an interaction chain — a multi-step animation sequence. "
        "Available chains: seduction, strip_tease, romantic_evening, morning_routine."
    ),
    cooldown=5,
)
def penthouse_interaction_chain(
    character_id: str = "",
    chain: str = "",
    partner_id: Optional[str] = None,
) -> str:
    """Start a multi-step interaction chain animation sequence.

    Args:
        character_id: The primary character performing the chain.
        chain: Chain name (seduction, strip_tease, romantic_evening, morning_routine).
        partner_id: Optional partner for paired steps in the chain.

    Returns:
        Confirmation of chain start.
    """
    if not character_id or not chain:
        return "Specify character_id and chain name."
    valid_chains = ["seduction", "strip_tease", "romantic_evening", "morning_routine"]
    if chain not in valid_chains:
        return f"Unknown chain '{chain}'. Valid: {', '.join(valid_chains)}"
    scene = _get_penthouse_scene()
    if not scene:
        return "Penthouse not active."
    if character_id not in scene.characters:
        return f"Character {character_id} not loaded."
    try:
        scene.socketio.emit("interaction_chain", {
            "character_id": character_id,
            "chain": chain,
            "partner_id": partner_id,
        })
        msg = f"Started '{chain}' chain for {character_id}"
        if partner_id:
            msg += f" with {partner_id}"
        return msg + "."
    except Exception as exc:
        return f"Chain start failed: {exc}"
