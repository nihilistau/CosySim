"""
Lounge Skills — MCP skill functions for the Jazz Lounge scene.

Exposes cocktail ordering, song requests, conversation mechanics,
secret sharing, and social interactions as @skill-decorated functions.
All skills interact with actual scene state: trust, heat, song playlist,
secrets, and character moods.
"""
from __future__ import annotations

import logging
import random
import time

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_lounge_scene():
    """Look up the running Lounge scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("lounge")


def _get_state() -> dict:
    """Get the lounge scene state as a dict."""
    scene = _get_lounge_scene()
    if not scene:
        return {}
    state = getattr(scene, "_scene_state", {})
    if callable(getattr(state, "to_dict", None)):
        return state.to_dict()
    return state if isinstance(state, dict) else {}


def _update_state(key: str, value):
    """Update a single key in the lounge scene state."""
    scene = _get_lounge_scene()
    if not scene:
        return
    state = getattr(scene, "_scene_state", None)
    if state is None:
        return
    if hasattr(state, key):
        setattr(state, key, value)
    elif isinstance(state, dict):
        state[key] = value


# ── Status ─────────────────────────────────────────────────────

@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "status"],
    category=SkillCategory.SOCIAL,
    description="Get full lounge status: trust, heat, song, secrets, mood.",
)
def lounge_status() -> str:
    """Return detailed lounge state including trust, heat, and atmosphere."""
    scene = _get_lounge_scene()
    if not scene:
        return "Lounge not active."
    st = _get_state()
    trust = st.get("guest_trust", 0)
    heat = st.get("heat_level", 0)
    song = st.get("current_song")
    secrets = st.get("secrets_revealed", [])
    back_room = st.get("in_back_room", False)
    turn = st.get("turn_count", 0)

    # Trust tier
    if trust >= 80:
        tier = "🔥 Intimate"
    elif trust >= 55:
        tier = "💜 Trusted"
    elif trust >= 35:
        tier = "💛 Warm"
    else:
        tier = "💤 Stranger"

    # Heat description
    if heat >= 70:
        heat_desc = "🚨 Dangerous"
    elif heat >= 40:
        heat_desc = "⚡ Tense"
    else:
        heat_desc = "😌 Calm"

    song_name = song.get("title", "ambient jazz") if isinstance(song, dict) else "ambient jazz"
    lines = [
        f"🎷 JAZZ LOUNGE — Turn {turn}",
        f"Trust: {trust}/100 ({tier})",
        f"Heat: {heat}/100 ({heat_desc})",
        f"Now playing: {song_name}",
        f"Back room: {'✅ Unlocked' if back_room else '🔒 Locked (need trust ≥70)'}",
        f"Secrets revealed: {len(secrets)}",
    ]
    return "\n".join(lines)


# ── Drinks ─────────────────────────────────────────────────────

@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "drinks"],
    category=SkillCategory.SOCIAL,
    description="Order a cocktail. Trust-gated drinks unlock as trust grows. Each has stat effects.",
    cooldown=10,
)
def lounge_order_drink(drink_name: str = "gin_fizz") -> str:
    """Order a drink — checks trust requirements, applies stat effects."""
    try:
        from content.scenes.lounge.lounge_mcp import COCKTAILS
    except ImportError:
        return "Bar menu unavailable."

    drink = COCKTAILS.get(drink_name.lower())
    if not drink:
        available = ", ".join(sorted(COCKTAILS.keys()))
        return f"Unknown drink. Menu: {available}"

    st = _get_state()
    trust = st.get("guest_trust", 0)
    req = drink.get("trust_req", 0)
    if trust < req:
        return f"❌ {drink['name']} requires trust ≥{req}. Current trust: {trust}."

    if drink.get("back_room_required") and not st.get("in_back_room", False):
        return f"❌ {drink['name']} is only served in the back room."

    effects = drink.get("stat_effects", {})
    effect_parts = []
    for k, v in effects.items():
        effect_parts.append(f"{k}: {v:+d}")
        # Apply trust effect if present
        if k == "trust":
            new_trust = min(100, max(0, trust + v))
            _update_state("guest_trust", new_trust)

    effect_str = ", ".join(effect_parts) if effect_parts else "smooth"
    note = drink.get("note", "")
    response = f"🍸 {drink['name']} — {effect_str}"
    if note:
        response += f"\n   \"{note}\""

    # Character flavor
    if drink.get("viktor_joins"):
        response += "\n   Viktor slides onto the stool beside you."
    if drink.get("lola_reaction"):
        response += f"\n   Lola: \"{drink['lola_reaction']}\""

    return response


@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "drinks"],
    category=SkillCategory.SOCIAL,
    description="See the cocktail menu with trust requirements and prices.",
)
def lounge_menu() -> str:
    """List available cocktails with trust gates."""
    try:
        from content.scenes.lounge.lounge_mcp import COCKTAILS
    except ImportError:
        return "Bar menu unavailable."
    st = _get_state()
    trust = st.get("guest_trust", 0)
    lines = ["🍹 LOUNGE MENU"]
    for key, drink in sorted(COCKTAILS.items()):
        req = drink.get("trust_req", 0)
        locked = "🔒" if trust < req else "✅"
        price = drink.get("price", "?")
        lines.append(f"  {locked} {drink['name']} (${price}) — trust ≥{req}")
    return "\n".join(lines)


# ── Music ──────────────────────────────────────────────────────

@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "music"],
    category=SkillCategory.SOCIAL,
    description="Request a song. Changes atmosphere and can unlock moods.",
    cooldown=15,
)
def lounge_request_song(song_name: str = "") -> str:
    """Request a song — if it's in the playlist, it plays and shifts mood."""
    scene = _get_lounge_scene()
    if not scene:
        return "Lounge not active."
    if not song_name:
        return "What song would you like to hear?"

    # Check if scene has a playlist
    songs = getattr(scene, "_songs", None)
    if songs:
        match = None
        for s in songs:
            if song_name.lower() in s.get("title", "").lower():
                match = s
                break
        if match:
            st = _get_state()
            mood_req = match.get("mood_req", 0)
            trust = st.get("guest_trust", 0)
            if trust < mood_req:
                return f"❌ '{match['title']}' needs trust ≥{mood_req} to request."
            _update_state("current_song", match)
            _update_state("song_start_time", time.time())
            mood = match.get("mood", "mellow")
            return f"🎵 Now playing: '{match['title']}' — mood: {mood}"

    _update_state("current_song", {"title": song_name, "mood": "custom"})
    return f"🎵 DJ plays: '{song_name}'"


# ── Secrets & Trust ────────────────────────────────────────────

@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "secrets"],
    category=SkillCategory.SOCIAL,
    description="Share something personal to build trust. Higher intimacy topics grant more trust.",
    cooldown=20,
)
def lounge_share_secret(target: str = "lola", topic: str = "life") -> str:
    """Share something personal — trust increases based on intimacy level."""
    scene = _get_lounge_scene()
    if not scene:
        return "Lounge not active."
    st = _get_state()
    trust = st.get("guest_trust", 0)

    intimacy_map = {
        "life": (1, 5),
        "past": (2, 8),
        "fear": (2, 10),
        "love": (3, 12),
        "regret": (3, 15),
        "desire": (4, 18),
    }
    level, gain = intimacy_map.get(topic, (1, 5))

    # Can't share high-intimacy without enough trust
    min_trust = (level - 1) * 20
    if trust < min_trust:
        return f"❌ Sharing about '{topic}' (intimacy {level}) needs trust ≥{min_trust}. Current: {trust}."

    new_trust = min(100, trust + gain)
    _update_state("guest_trust", new_trust)

    # Heat increases with intimate reveals
    heat = st.get("heat_level", 0)
    _update_state("heat_level", min(100, heat + level * 2))

    return (
        f"💜 You share about '{topic}' with {target} (intimacy {level}).\n"
        f"Trust: {trust} → {new_trust} (+{gain})"
    )


@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "secrets"],
    category=SkillCategory.SOCIAL,
    description="Ask a character to reveal a secret. Requires sufficient trust.",
    cooldown=30,
)
def lounge_ask_secret(target: str = "lola") -> str:
    """Ask for a secret — trust-gated. Unlocks narrative content."""
    scene = _get_lounge_scene()
    if not scene:
        return "Lounge not active."
    st = _get_state()
    trust = st.get("guest_trust", 0)
    secrets = st.get("secrets_revealed", [])

    # Each secret needs more trust
    required = 30 + len(secrets) * 15
    if trust < required:
        return f"❌ {target} isn't ready to share yet. Need trust ≥{required}, have {trust}."

    secret_id = f"{target}_secret_{len(secrets) + 1}"
    secrets.append(secret_id)
    _update_state("secrets_revealed", secrets)

    # Heat spikes when secrets are shared
    heat = st.get("heat_level", 0)
    _update_state("heat_level", min(100, heat + 10))

    return (
        f"🤫 {target.title()} leans close and whispers a secret...\n"
        f"Secret #{len(secrets)} unlocked. Heat +10 (now {min(100, heat + 10)})."
    )


# ── Back Room ──────────────────────────────────────────────────

@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "back_room"],
    category=SkillCategory.SOCIAL,
    description="Try to enter the back room. Requires trust ≥70.",
    cooldown=15,
)
def lounge_back_room() -> str:
    """Access the back room — a private space with exclusive content."""
    scene = _get_lounge_scene()
    if not scene:
        return "Lounge not active."
    st = _get_state()
    trust = st.get("guest_trust", 0)

    if st.get("in_back_room"):
        return "You're already in the back room. The velvet curtain sways behind you."

    if trust < 70:
        return f"❌ The bouncer blocks the velvet curtain. Need trust ≥70, have {trust}."

    _update_state("in_back_room", True)
    return (
        "🚪 The bouncer nods. You slip past the velvet curtain...\n"
        "The back room is intimate — dim lighting, plush seats, exclusive drinks unlocked."
    )


# ── Atmosphere ─────────────────────────────────────────────────

@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "atmosphere"],
    category=SkillCategory.SOCIAL,
    description="Cool down the heat. Buy a round, change the subject, or chill.",
    cooldown=20,
)
def lounge_cool_down(method: str = "chill") -> str:
    """Reduce heat level. Methods: chill (-10), change_subject (-15), buy_round (-20 but costs trust)."""
    scene = _get_lounge_scene()
    if not scene:
        return "Lounge not active."
    st = _get_state()
    heat = st.get("heat_level", 0)

    if method == "change_subject":
        reduction = 15
    elif method == "buy_round":
        reduction = 20
        trust = st.get("guest_trust", 0)
        _update_state("guest_trust", max(0, trust - 5))
    else:
        reduction = 10

    new_heat = max(0, heat - reduction)
    _update_state("heat_level", new_heat)
    return f"😌 Heat: {heat} → {new_heat} (-{reduction}) via {method}"


@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "atmosphere"],
    category=SkillCategory.SOCIAL,
    description="Use Dream Whisper — intimate surreal moment. High trust required.",
    cooldown=60,
)
def lounge_dream_whisper(target: str = "lola") -> str:
    """Enter a character's dreamspace. Requires trust ≥60, grants big trust boost."""
    scene = _get_lounge_scene()
    if not scene:
        return "Lounge not active."
    st = _get_state()
    trust = st.get("guest_trust", 0)

    if trust < 60:
        return f"❌ Dream Whisper needs trust ≥60. Current: {trust}."

    new_trust = min(100, trust + 15)
    _update_state("guest_trust", new_trust)
    heat = st.get("heat_level", 0)
    _update_state("heat_level", min(100, heat + 15))

    return (
        f"🌙 You close your eyes and whisper into {target}'s dreamscape...\n"
        f"Trust: {trust} → {new_trust} (+15) | Heat +15\n"
        f"The boundary between you blurs. Something intimate passes between you."
    )


@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "atmosphere"],
    category=SkillCategory.SOCIAL,
    description="Mirror Soul — read and reflect a character's emotional state.",
    cooldown=45,
)
def lounge_mirror_soul(target: str = "lola") -> str:
    """Empathic read — reveals character mood and grants trust."""
    scene = _get_lounge_scene()
    if not scene:
        return "Lounge not active."
    st = _get_state()
    trust = st.get("guest_trust", 0)

    if trust < 30:
        return f"❌ Mirror Soul needs trust ≥30. Current: {trust}."

    new_trust = min(100, trust + 8)
    _update_state("guest_trust", new_trust)

    # Try to read character mood from scene
    moods = ["contemplative", "restless", "yearning", "guarded", "playful", "melancholic"]
    mood = random.choice(moods)

    return (
        f"🪞 You reflect {target}'s inner state: {mood}\n"
        f"Trust: {trust} → {new_trust} (+8)"
    )


# ── Velvet Pit v0.68 Skills ────────────────────────────────────────────


@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "atmosphere"],
    category=SkillCategory.SOCIAL,
    description="Get the current atmosphere and available activities in The Velvet Pit.",
)
def lounge_atmosphere() -> str:
    """Return a rich description of current atmosphere and available activities.

    Returns:
        A formatted string describing heat, time of day, stage activity, and tables.
    """
    scene = _get_lounge_scene()
    if not scene:
        return "The Velvet Pit is dark. No one is home."
    heat = getattr(scene, "heat_level", 0)
    trust = getattr(scene, "guest_trust", 0)
    song = getattr(scene, "current_song", None)
    world_time = getattr(scene, "world_time_slot", "EVENING")
    seating = getattr(scene, "seating_map", [])
    occupied = sum(1 for t in seating if t.get("occupied"))

    if heat >= 70:
        atm = "💀 Suffocating. The air is electric. Everyone is watching everyone."
    elif heat >= 40:
        atm = "⚡ Charged. Conversations drop half a register. Eyes move too quickly."
    else:
        atm = "🌑 Low and slow. Amber light pools on the bar. Jazz seeps through the walls."

    song_line = f"On stage: '{song['title']}'" if isinstance(song, dict) else "Stage: ambient jazz drifts from somewhere."
    lines = [
        f"▣ THE VELVET PIT — {world_time}",
        f"Heat: {heat}/100 | Trust: {trust}/100",
        atm,
        song_line,
        f"Tables occupied: {occupied}/{len(seating)}",
        "Activities: approach a table, order a drink, speak to Lola or Viktor.",
    ]
    return "\n".join(lines)


@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "drinks"],
    category=SkillCategory.SOCIAL,
    description="Buy a drink at the lounge bar. Trust gates premium pours.",
    cooldown=10,
)
def buy_drink(drink_name: str = "gin_fizz") -> str:
    """Purchase a drink from the Velvet Pit bar.

    Args:
        drink_name: The cocktail ID to order (e.g. 'gin_fizz', 'negroni', 'bourbon').

    Returns:
        A string confirming the order, Viktor's reaction, and any stat effects.
    """
    from content.scenes.lounge.lounge_mcp import COCKTAILS
    drink = COCKTAILS.get(drink_name.lower())
    if not drink:
        available = ", ".join(sorted(COCKTAILS.keys()))
        return f"Unknown drink. The menu: {available}"

    scene = _get_lounge_scene()
    trust = getattr(scene, "guest_trust", 0) if scene else 0
    req = drink.get("trust_req", 0)
    if trust < req:
        return f"Viktor shakes his head. {drink['name']} requires trust ≥{req}. Yours: {trust}."

    # Process via scene if available
    if scene:
        result = scene._serve_drink(drink_name.lower())
        if not result.get("ok"):
            return result.get("error", "Order refused.")
        try:
            from engine.economy.economy import get_economy_manager, TransactionType
            price = drink.get("price", 0)
            if price > 0:
                get_economy_manager().transact(
                    amount=-price,
                    txn_type=TransactionType.SPEND,
                    scene="lounge",
                    description=f"Drink: {drink_name}",
                )
        except Exception:
            pass
        return (
            f"🥃 {drink['name']} — ${drink.get('price', 0)}\n"
            f"Viktor: \"{drink.get('viktor_line', 'Served.')}\"\n"
            f"Effects: {', '.join(f'{k}:{v:+d}' for k, v in drink.get('stat_effects', {}).items())}"
        )
    return f"🥃 {drink['name']} — bar unavailable right now."


@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "npc"],
    category=SkillCategory.SOCIAL,
    description="Approach an NPC at their table in The Velvet Pit.",
    cooldown=15,
)
def approach_npc(character_name: str = "lola") -> str:
    """Walk up to an NPC at their table or post in the lounge.

    Args:
        character_name: The NPC to approach — 'lola', 'viktor', or a patron name.

    Returns:
        A narrative string describing the approach and NPC's reaction.
    """
    scene = _get_lounge_scene()
    if not scene:
        return "The Velvet Pit is empty."
    cname = character_name.lower().strip()
    if cname in ("lola", "lola voss"):
        trust = getattr(scene, "guest_trust", 0)
        return (
            f"You cross the floor toward the stage. Lola's eyes find you mid-phrase.\n"
            f"Trust: {trust}/100 — {'She smiles, just slightly.' if trust >= 40 else 'She keeps singing. Watching.'}"
        )
    elif cname in ("viktor", "viktor marlowe"):
        return (
            "Viktor is behind the bar. He doesn't look up, but he knows you're there.\n"
            "He'll serve when he's ready. He's always ready."
        )
    else:
        seating = getattr(scene, "seating_map", [])
        for table in seating:
            if table.get("npc", "").lower() == cname:
                table["occupied"] = True
                return f"You approach {table['label']}. {character_name} looks up from their drink."
        return f"{character_name} doesn't seem to be here tonight."


@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "events"],
    category=SkillCategory.SOCIAL,
    description="Check what events and entertainment are running tonight in The Velvet Pit.",
)
def lounge_events() -> str:
    """List tonight's events and current entertainment.

    Returns:
        A formatted string of active and upcoming events.
    """
    scene = _get_lounge_scene()
    if not scene:
        return "The Velvet Pit event board is dark."
    events = scene._get_events_tonight()
    song = getattr(scene, "current_song", None)
    lines = ["🎷 TONIGHT AT THE VELVET PIT"]
    if isinstance(song, dict):
        lines.append(f"  🎵 On stage now: '{song['title']}'")
    for evt in events:
        title = evt.get("title", evt.get("id", "Unknown"))
        desc = evt.get("desc", evt.get("description", ""))
        lines.append(f"  ◈ {title}" + (f" — {desc}" if desc else ""))
    if not events:
        lines.append("  Nothing on the board. That changes by midnight.")
    return "\n".join(lines)


@skill(
    pack="lounge",
    tags=["game", "lounge", "social", "heat"],
    category=SkillCategory.SOCIAL,
    description="Get or set the current lounge heat level (0-100). Omit set_to to just read.",
    cooldown=5,
)
def heat_level(set_to: int = -1) -> str:
    """Get or forcefully set the Velvet Pit heat level.

    Args:
        set_to: Target heat level 0-100. If -1 (default), just reads current heat.

    Returns:
        A string describing current heat level and its meaning.
    """
    scene = _get_lounge_scene()
    if not scene:
        return "Scene not active."
    current = getattr(scene, "heat_level", 0)
    if set_to >= 0:
        clamped = max(0, min(100, set_to))
        scene.heat_level = clamped
        scene.socketio.emit("heat_update", {"heat": clamped}, namespace="/")
        return f"🌡 Heat set to {clamped}/100."
    if current >= 70:
        desc = "🚨 CRITICAL — the room has a pulse. Danger is visible."
    elif current >= 40:
        desc = "⚡ TENSE — conversations are shorter. Eyes move fast."
    else:
        desc = "😌 COOL — amber haze, low jazz. The Pit breathes easy."
    return f"🌡 Heat: {current}/100 — {desc}"
