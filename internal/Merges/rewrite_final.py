import re

with open("engine/mcp/cosysim_server.py", "r", encoding="utf-8") as f:
    content = f.read()

# schedule_consequence
old_sc = '''@mcp.tool()
def schedule_consequence(
    scene_id: str,
    character_id: str,
    consequence_type: str,
    params_json: str = "{}",
    trigger_after_turns: int = 1,
    description: str = "",
    created_by: str = "system",
) -> str:
    """
    **CONSEQUENCE CHAINS** — Schedule a delayed effect to fire after N turns.

    Use this to create build-up, anticipation, or delayed reactions.
    The consequence stays pending until the target character takes their
    ``trigger_after_turns``-th turn, then it fires automatically.

    Consequence types:
      stat_change      — Adjust stats (params: {"arousal": 10})
      mood_shift       — Change mood (params: {"mood": "aroused", "intensity": 0.8})
      state_set        — Set arbitrary state flag (params: {"field": "has_drink", "value": true})
      directive_clear  — Clear any active response directive
      scene_event      — Trigger an ambient event (params: {"event_id": "phone_ring"})

    Examples:
      schedule_consequence("bedroom", "user_char", "stat_change",
                          '{"arousal": 15}', 2,
                          "The kiss lingers — arousal builds.")

      schedule_consequence("bedroom", "aria", "state_set",
                          '{"field": "mood", "value": "vulnerable"}', 3,
                          "The confession settles in. She feels exposed.")

    Args:
        scene_id:            Scene where the consequence fires
        character_id:        The affected character
        consequence_type:    Effect type (see above)
        params_json:         JSON dict of parameters for the effect
        trigger_after_turns: How many turns until it fires (1 = next turn)
        description:         Narrative text logged when it fires
        created_by:          Who scheduled this (for audit)
    """
    try:

        params = _json.loads(params_json) if params_json else {}
        cseq = get_framework().schedule_consequence(
            scene_id=scene_id,
            character_id=character_id,
            consequence_type=consequence_type,
            params=params,
            trigger_after_turns=trigger_after_turns,
            description=description,
            created_by=created_by,
        )
        return json.dumps(
            {
                "ok": True,
                "consequence_id": cseq.id,
                "fires_in_turns": trigger_after_turns,
            }
        )

    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})'''

new_sc = '''@mcp.tool()
def schedule_consequence(
    scene_id: str,
    character_id: str,
    consequence_type: str,
    params_json: str = "{}",
    trigger_after_turns: int = 1,
    description: str = "",
    created_by: str = "system",
) -> str:
    """
    **CONSEQUENCE CHAINS** — Schedule a delayed effect to fire after N turns.

    Use this to create build-up, anticipation, or delayed reactions.
    The consequence stays pending until the target character takes their
    ``trigger_after_turns``-th turn, then it fires automatically.

    Consequence types:
      stat_change      — Adjust stats (params: {"arousal": 10})
      mood_shift       — Change mood (params: {"mood": "aroused", "intensity": 0.8})
      state_set        — Set arbitrary state flag (params: {"field": "has_drink", "value": true})
      directive_clear  — Clear any active response directive
      scene_event      — Trigger an ambient event (params: {"event_id": "phone_ring"})

    Examples:
      schedule_consequence("bedroom", "user_char", "stat_change",
                          '{"arousal": 15}', 2,
                          "The kiss lingers — arousal builds.")

      schedule_consequence("bedroom", "aria", "state_set",
                          '{"field": "mood", "value": "vulnerable"}', 3,
                          "The confession settles in. She feels exposed.")

    Args:
        scene_id:            Scene where the consequence fires
        character_id:        The affected character
        consequence_type:    Effect type (see above)
        params_json:         JSON dict of parameters for the effect
        trigger_after_turns: How many turns until it fires (1 = next turn)
        description:         Narrative text logged when it fires
        created_by:          Who scheduled this (for audit)
    """
    from engine.mcp.tools.interaction_tools import schedule_consequence_impl
    return schedule_consequence_impl(
        scene_id,
        character_id,
        consequence_type,
        params_json,
        trigger_after_turns,
        description,
        created_by,
        get_framework()
    )'''
content = content.replace(old_sc, new_sc)

# cancel_consequence
old_cc = '''@mcp.tool()
def cancel_consequence(consequence_id: str) -> str:
    """
    **CONSEQUENCE CHAINS** — Cancel a scheduled consequence before it fires.

    Args:
        consequence_id: The ID returned by schedule_consequence
    """
    try:

        ok = get_framework().cancel_consequence(consequence_id)
        return json.dumps({"ok": ok, "consequence_id": consequence_id})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})'''

new_cc = '''@mcp.tool()
def cancel_consequence(consequence_id: str) -> str:
    """
    **CONSEQUENCE CHAINS** — Cancel a scheduled consequence before it fires.

    Args:
        consequence_id: The ID returned by schedule_consequence
    """
    from engine.mcp.tools.interaction_tools import cancel_consequence_impl
    return cancel_consequence_impl(consequence_id, get_framework())'''
content = content.replace(old_cc, new_cc)

# get_pending_consequences
old_gp = '''@mcp.tool()
def get_pending_consequences(scene_id: str = "", character_id: str = "") -> str:
    """
    **CONSEQUENCE CHAINS** — List all scheduled consequences that haven't fired yet.

    Use this to see what's coming and plan your response.
    A thoughtful agent references pending consequences in their narration.

    Args:
        scene_id:     Filter by scene (optional)
        character_id: Filter by character (optional)
    """
    try:

        pending = get_framework().get_pending_consequences(
            scene_id=scene_id, character_id=character_id
        )
        return json.dumps({"pending": pending, "count": len(pending)}, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})'''

new_gp = '''@mcp.tool()
def get_pending_consequences(scene_id: str = "", character_id: str = "") -> str:
    """
    **CONSEQUENCE CHAINS** — List all scheduled consequences that haven't fired yet.

    Use this to see what's coming and plan your response.
    A thoughtful agent references pending consequences in their narration.

    Args:
        scene_id:     Filter by scene (optional)
        character_id: Filter by character (optional)
    """
    from engine.mcp.tools.interaction_tools import get_pending_consequences_impl
    return get_pending_consequences_impl(scene_id, character_id, get_framework())'''
content = content.replace(old_gp, new_gp)

# mood_whisper
old_mw = '''@mcp.tool()
def mood_whisper(
    from_character_id: str,
    to_character_id: str,
    whisper_content: str,
    duration_turns: int = 2,
    scene_id: str = "",
) -> str:
    """
    **PSYCHOLOGICAL TOOL** — Plant an emotion, sensation, or thought directly into another character's mind.

    This acts as a "phantom directive". The target will feel or think
    *whisper_content* without necessarily knowing why or where it came from.
    They must incorporate it into their next responses.

    Use this to:
    • Nudge someone's emotional state subtly across the scene
    • Leave an impression that lingers beyond a single reply
    • Create tension, longing, or warmth from a distance

    The whisper fires as a ``mood_set`` ResponseDirective on the target.

    Args:
        from_character_id: The character doing the whispering (e.g. "lola")
        to_character_id:   The character receiving it   (e.g. "user_char")
        whisper_content:   What is being planted — a feeling, an image,
                           a thought. E.g. "a sudden, inexplicable warmth" or
                           "the faint ghost of perfume and low piano"
        duration_turns:    How many of the target's turns the influence lasts (1–5)
        scene_id:          Scene context (optional, defaults to target's current scene)
    """
    try:

        duration_turns = max(1, min(5, duration_turns))
        fw = get_framework()
        ds = get_dialog_system()
        ssm = get_scene_state_manager()

        # Get target's current scene if not provided
        target_scene = scene_id
        if not target_scene:
            try:
                target_scene = fw.get_character(to_character_id).current_scene or "phone"
            except Exception:
                target_scene = "phone"

        # Apply a mood_set directive with the whisper content
        directive_val = f"[MOOD WHISPER from {from_character_id}]: {whisper_content}"

        ds.set_directive(
            character_id=to_character_id,
            scene_id=target_scene,
            directive_type="mood_set",
            value=directive_val,
            turns=duration_turns,
            issued_by=from_character_id,
        )

        # Log it to narrative so the context knows it happened
        ssm.add_narrative(
            target_scene,
            f"[{from_character_id} planted a mood whisper in {to_character_id}'s mind.]",
            entry_type="system",
            character_id=to_character_id,
        )

        return json.dumps(
            {
                "ok": True,
                "from_character_id": from_character_id,
                "to_character_id": to_character_id,
                "duration_turns": duration_turns,
                "note": "Whisper planted. They will feel it for the next few turns.",
            },
            indent=2,
        )

    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})'''

new_mw = '''@mcp.tool()
def mood_whisper(
    from_character_id: str,
    to_character_id: str,
    whisper_content: str,
    duration_turns: int = 2,
    scene_id: str = "",
) -> str:
    """
    **PSYCHOLOGICAL TOOL** — Plant an emotion, sensation, or thought directly into another character's mind.

    This acts as a "phantom directive". The target will feel or think
    *whisper_content* without necessarily knowing why or where it came from.
    They must incorporate it into their next responses.

    Use this to:
    • Nudge someone's emotional state subtly across the scene
    • Leave an impression that lingers beyond a single reply
    • Create tension, longing, or warmth from a distance

    The whisper fires as a ``mood_set`` ResponseDirective on the target.

    Args:
        from_character_id: The character doing the whispering (e.g. "lola")
        to_character_id:   The character receiving it   (e.g. "user_char")
        whisper_content:   What is being planted — a feeling, an image,
                           a thought. E.g. "a sudden, inexplicable warmth" or
                           "the faint ghost of perfume and low piano"
        duration_turns:    How many of the target's turns the influence lasts (1–5)
        scene_id:          Scene context (optional, defaults to target's current scene)
    """
    from engine.mcp.tools.interaction_tools import mood_whisper_impl
    return mood_whisper_impl(
        from_character_id,
        to_character_id,
        whisper_content,
        duration_turns,
        get_framework(),
        get_dialog_system(),
        get_scene_state_manager(),
        scene_id=scene_id
    )'''
content = content.replace(old_mw, new_mw)

# mirror_soul
old_ms = '''@mcp.tool()
def mirror_soul(
    character_id: str,
    target_id: str,
    duration_turns: int = 3,
    scene_id: str = "bedroom",
) -> str:
    """
    **PSYCHOLOGICAL TOOL** — Deeply attune to another character's current state.

    Mirror Soul checks the target character's current mood and temporarily
    forces *your* character into a complementary/attuned voice style via a
    ResponseDirective. It also provides a significant bump to mutual affection
    and openness.

    The mirror effect auto-clears after the set turns via a scheduled consequence.

    Use this to:
    • Create a moment of deep, uncanny connection
    • Shift an awkward conversation into something real
    • Recover a scene that has gone flat
    • Make someone feel completely seen

    Args:
        character_id:  The character activating Mirror Soul (you)
        target_id:     Who you are mirroring   (e.g. "user_char", "aria")
        duration_turns: How long the attunement holds     (1–6)
        scene_id:       Current scene
    """
    try:

        duration_turns = max(1, min(6, duration_turns))
        reg = get_character_registry()
        ds = get_dialog_system()
        ssm = get_scene_state_manager()
        fw = get_framework()

        # Get target mood
        target_state = reg.get_state(target_id)
        target_mood = target_state.mood if target_state else "neutral"

        # Determine complementary style
        mood_to_style = {
            "vulnerable": "warm",
            "sad": "warm",
            "angry": "calm",
            "aroused": "charged",
            "playful": "teasing",
            "nervous": "dominant",
            "dominant": "submissive",
            "submissive": "dominant",
            "excited": "playful",
        }
        chosen_style = mood_to_style.get(target_mood, "natural")

        # Apply style lock directive to self
        ds.set_directive(
            character_id=character_id,
            scene_id=scene_id,
            directive_type="style_lock",
            value=chosen_style,
            turns=duration_turns,
            issued_by="mirror_soul",
        )

        # Apply stat bumps
        ssm.update_stats(character_id, openness=15, affection=10)
        ssm.update_stats(target_id, openness=15, affection=10)

        # Add narrative
        ssm.add_narrative(
            scene_id,
            f"[MIRROR SOUL]: {character_id} attuned to {target_id}'s {target_mood} mood, adopting {chosen_style} style.",
            entry_type="system",
            character_id=character_id,
        )

        # Schedule clear
        fw.schedule_consequence(
            scene_id=scene_id,
            character_id=character_id,
            consequence_type="directive_clear",
            params={},
            trigger_after_turns=duration_turns,
            description=f"The Mirror Soul attunement fades. {character_id} returns to baseline.",
            created_by="mirror_soul",
        )

        return json.dumps(
            {
                "ok": True,
                "character_id": character_id,
                "target_id": target_id,
                "chosen_style": chosen_style,
                "lasts_turns": duration_turns,
                "narrative": (
                    f"Something shifts. {character_id} doesn't change, exactly — "
                    f"they just become the version of themselves {target_id} most needs right now. "
                    f"Style: {chosen_style.upper()}. Duration: {duration_turns} turns."
                ),
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})'''

new_ms = '''@mcp.tool()
def mirror_soul(
    character_id: str,
    target_id: str,
    duration_turns: int = 3,
    scene_id: str = "bedroom",
) -> str:
    """
    **PSYCHOLOGICAL TOOL** — Deeply attune to another character's current state.

    Mirror Soul checks the target character's current mood and temporarily
    forces *your* character into a complementary/attuned voice style via a
    ResponseDirective. It also provides a significant bump to mutual affection
    and openness.

    The mirror effect auto-clears after the set turns via a scheduled consequence.

    Use this to:
    • Create a moment of deep, uncanny connection
    • Shift an awkward conversation into something real
    • Recover a scene that has gone flat
    • Make someone feel completely seen

    Args:
        character_id:  The character activating Mirror Soul (you)
        target_id:     Who you are mirroring   (e.g. "user_char", "aria")
        duration_turns: How long the attunement holds     (1–6)
        scene_id:       Current scene
    """
    from engine.mcp.tools.interaction_tools import mirror_soul_impl
    return mirror_soul_impl(
        character_id,
        target_id,
        duration_turns,
        scene_id,
        get_character_registry(),
        get_dialog_system(),
        get_scene_state_manager(),
        get_framework()
    )'''
content = content.replace(old_ms, new_ms)

# serve_lounge_drink
old_sl = '''@mcp.tool()
def serve_lounge_drink(
    drink_id: str,
    bartender_id: str = "viktor",
    scene_id: str = "lounge",
) -> str:
    """
    Viktor serves a cocktail to the guest.

    Applies drink stat effects as a consequence chain (fires next turn),
    triggers Lola reaction if the drink is noteworthy, and handles the
    Viktor-joins-guest ritual for bourbon.

    Returns: narrative description of the serve.
    """
    try:
        from content.scenes.lounge.lounge_mcp import (
            get_cocktail,
            SCENE_ID as LOUNGE_SCENE,
            LOLA_ID,
            VIKTOR_ID,
        )

        drink = get_cocktail(drink_id)
        if not drink:
            return json.dumps(
                {"error": f"Drink '{drink_id}' not found on the menu."}, indent=2
            )

        fw = get_framework()
        ssm = get_scene_state_manager()
        router = get_router()

        # Build serve text
        desc = f"[{bartender_id.title()} serves {drink['name']}]"
        if drink.get("presentation"):
            desc += f" {drink['presentation']}"

        # 1. Apply effects as a delayed consequence
        if drink.get("effects"):
            fw.schedule_consequence(
                scene_id=LOUNGE_SCENE,
                character_id="user_char",  # Hardcoded for single player right now
                consequence_type="stat_change",
                params=drink["effects"],
                trigger_after_turns=1,
                description=f"The {drink['name']} takes effect.",
                created_by="serve_lounge_drink",
            )

        # 2. Add to scene narrative
        ssm.add_narrative(
            LOUNGE_SCENE,
            desc,
            entry_type="system",
            character_id=bartender_id,
        )

        # 3. Special handling for Bourbon (Viktor joins)
        if drink_id == "neat_bourbon":
            ssm.set_scene_state(LOUNGE_SCENE, "viktor_drinking", True)
            desc += (
                " He pours a measure for himself, leaning against the counter."
            )

        # 4. Notify Lola if the drink has a high heat modifier
        effects = drink.get("effects", {})
        if effects.get("arousal", 0) > 0 or drink_id in ["siren_song", "velvet_rose"]:
            router.send(
                LOLA_ID,
                f"Viktor just served the guest a {drink['name']}. It's a bold choice.",
                sender_id="system",
            )

        return json.dumps({"ok": True, "drink": drink["name"], "narrative": desc}, indent=2)

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})'''

new_sl = '''@mcp.tool()
def serve_lounge_drink(
    drink_id: str,
    bartender_id: str = "viktor",
    scene_id: str = "lounge",
) -> str:
    """
    Viktor serves a cocktail to the guest.

    Applies drink stat effects as a consequence chain (fires next turn),
    triggers Lola reaction if the drink is noteworthy, and handles the
    Viktor-joins-guest ritual for bourbon.

    Returns: narrative description of the serve.
    """
    from engine.mcp.tools.lounge_tools import serve_lounge_drink_impl
    return serve_lounge_drink_impl(
        drink_id,
        bartender_id,
        get_framework(),
        get_scene_state_manager(),
        get_router(),
        scene_id=scene_id
    )'''
content = content.replace(old_sl, new_sl)

with open("engine/mcp/cosysim_server.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Replaced final tool blocks")
