import re

with open("engine/mcp/cosysim_server.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace speak_as
old_sa = '''@mcp.tool()
def speak_as(
    character_id: str,
    text: str,
    style: str = "",
    scene_id: str = "",
) -> str:
    """
    **SPEECH SKILL** — Transform plain text into a character's authentic voice.

    This is the full speech pipeline:
    1. Looks up the character's registered voice_style and current mood
    2. Determines the best speech style (or uses the one you specify)
    3. Applies quick heuristic enhancement
    4. Returns both the enhanced version AND a full LLM rewrite prompt

    Use the ``rewrite_prompt`` field to have an LLM produce the definitive version
    in the character's voice.  Use ``quick_version`` when you need something now.

    Args:
        character_id: The speaking character
        text:         The raw text to enhance
        style:        Force a style (or leave blank to auto-select)
        scene_id:     Current scene for context
    """
    try:
        return speak_as_impl(
            get_dialog_system(),
            get_character_registry(),
            character_id,
            text,
            style=style,
            scene_id=scene_id,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})'''

new_sa = '''@mcp.tool()
def speak_as(
    character_id: str,
    text: str,
    style: str = "",
    scene_id: str = "",
) -> str:
    """
    **SPEECH SKILL** — Transform plain text into a character's authentic voice.

    This is the full speech pipeline:
    1. Looks up the character's registered voice_style and current mood
    2. Determines the best speech style (or uses the one you specify)
    3. Applies quick heuristic enhancement
    4. Returns both the enhanced version AND a full LLM rewrite prompt

    Use the ``rewrite_prompt`` field to have an LLM produce the definitive version
    in the character's voice.  Use ``quick_version`` when you need something now.

    Args:
        character_id: The speaking character
        text:         The raw text to enhance
        style:        Force a style (or leave blank to auto-select)
        scene_id:     Current scene for context
    """
    return speak_as_impl(
        get_dialog_system(),
        get_character_registry(),
        character_id,
        text,
        style=style,
        scene_id=scene_id,
    )'''
content = content.replace(old_sa, new_sa)

# Replace enforce_behavior
old_eb = '''@mcp.tool()
def enforce_behavior(
    character_id: str,
    behavior_type: str,
    value: str,
    reason: str = "",
    scene_id: str = "",
    turns: int = 1,
) -> str:
    """
    **DIRECTOR SKILL** — Force, block, or shape a character's next response.

    Use this when a character is drifting off-brief, ignoring a rule, or
    when you need to forcefully steer a scene.

    Behavior types:
      force_response  — override the LLM: use this exact response
      refuse          — force the character to refuse the last action (in-character)
      style_lock      — lock to a style: charged/dominant/vulnerable/whisper/etc.
      must_include    — the reply MUST naturally contain ``value``
      topic_steer     — steer to a topic
      mood_set        — override the character's emotional tone

    This also updates the scene narrative with a record of what was enforced.

    Args:
        character_id: Target character
        behavior_type: One of the types above
        value:         The value for the behavior (response/style/topic/mood)
        reason:        Why this was enforced (for audit log)
        scene_id:      Scene context
        turns:         How many turns the enforcement lasts
    """
    try:
        return enforce_behavior_impl(
            get_dialog_system(),
            character_id,
            behavior_type,
            value,
            reason=reason,
            scene_id=scene_id,
            turns=turns,
            ssm=get_scene_state_manager(),
        )
    except Exception as e:
        return json.dumps({"error": str(e)})'''

new_eb = '''@mcp.tool()
def enforce_behavior(
    character_id: str,
    behavior_type: str,
    value: str,
    reason: str = "",
    scene_id: str = "",
    turns: int = 1,
) -> str:
    """
    **DIRECTOR SKILL** — Force, block, or shape a character's next response.

    Use this when a character is drifting off-brief, ignoring a rule, or
    when you need to forcefully steer a scene.

    Behavior types:
      force_response  — override the LLM: use this exact response
      refuse          — force the character to refuse the last action (in-character)
      style_lock      — lock to a style: charged/dominant/vulnerable/whisper/etc.
      must_include    — the reply MUST naturally contain ``value``
      topic_steer     — steer to a topic
      mood_set        — override the character's emotional tone

    This also updates the scene narrative with a record of what was enforced.

    Args:
        character_id: Target character
        behavior_type: One of the types above
        value:         The value for the behavior (response/style/topic/mood)
        reason:        Why this was enforced (for audit log)
        scene_id:      Scene context
        turns:         How many turns the enforcement lasts
    """
    return enforce_behavior_impl(
        get_dialog_system(),
        character_id,
        behavior_type,
        value,
        reason=reason,
        scene_id=scene_id,
        turns=turns,
        ssm=get_scene_state_manager(),
    )'''
content = content.replace(old_eb, new_eb)

# Replace character_remove_restriction
old_cr = '''@mcp.tool()
def character_remove_restriction(character_id: str, restriction: str) -> str:
    """
    Remove a named restriction from a character.

    Args:
        character_id: e.g. "aria"
        restriction:  Name of the restriction to remove
    """
    try:
        from engine.mcp.tools.character_tools import (
    get_character_scene_stats_impl,
    update_character_scene_stats_impl,
    set_character_scene_stat_impl,
    reset_character_scene_stats_impl,
    check_character_consent_impl,
    get_character_agency_summary_impl,
)

from engine.mcp.tools.character_tools import character_remove_restriction_impl
        return character_remove_restriction_impl(character_id, restriction)
    except Exception as e:
        return json.dumps({"error": str(e)})'''

new_cr = '''@mcp.tool()
def character_remove_restriction(character_id: str, restriction: str) -> str:
    """
    Remove a named restriction from a character.

    Args:
        character_id: e.g. "aria"
        restriction:  Name of the restriction to remove
    """
    return character_remove_restriction_impl(character_id, restriction)'''
content = content.replace(old_cr, new_cr)

# Replace resolve_random_scene_event
old_rre = '''@mcp.tool()
def resolve_random_scene_event(scene_id: str = "bedroom") -> str:
    """
    Generate a random scene event to keep things fresh and unpredictable.
    Call this when the scene feels stale or to inject spontaneity.

    Returns an event description and any stat effects — ready to use.
    """
    try:

        bedroom_events = [
            {
                "event": "The music changes to something slower and more suggestive.",
                "effects": {"arousal": 10},
            },
            {
                "event": "Someone laughs in the next room, breaking the silence.",
                "effects": {"inhibition": 5},
            },
            {
                "event": "A sudden rush of warmth hits the room.",
                "effects": {"openness": 5, "arousal": 5},
            },
            {
                "event": "A text message notification buzzes loudly nearby.",
                "effects": {"inhibition": 10},
            },
            {
                "event": "Eye contact holds for a second too long.",
                "effects": {"affection": 10, "arousal": 5},
            },
        ]

        if scene_id == "bedroom":
            evt = random.choice(bedroom_events)
        else:
            evt = {
                "event": "A cool breeze passes through, shifting the atmosphere.",
                "effects": {"openness": 5},
            }

        try:
            get_scene_state_manager().add_narrative(
                scene_id,
                f"[SCENE EVENT]: {evt['event']}",
                entry_type="system",
            )
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        return json.dumps(
            {"scene_id": scene_id, "event": evt["event"], "effects": evt["effects"]},
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})'''

new_rre = '''@mcp.tool()
def resolve_random_scene_event(scene_id: str = "bedroom") -> str:
    """
    Generate a random scene event to keep things fresh and unpredictable.
    Call this when the scene feels stale or to inject spontaneity.

    Returns an event description and any stat effects — ready to use.
    """
    from engine.mcp.tools.scene_tools import resolve_random_scene_event_impl
    return resolve_random_scene_event_impl(scene_id, get_scene_state_manager())'''
content = content.replace(old_rre, new_rre)

with open("engine/mcp/cosysim_server.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated more try/catch blocks")
