import re

with open("engine/mcp/cosysim_server.py", "r", encoding="utf-8") as f:
    content = f.read()

# get_dialog_options
old_gdo = '''@mcp.tool()
def get_dialog_options(
    character_id: str,
    scene_id: str,
    context_tags_json: str = "[]",
    stats_json: str = "{}",
    max_options: int = 4,
) -> str:
    """
    Get situationally appropriate dialog/action options for a character.
    Options are filtered by current stats and context tags.
    Use this before responding to pick the right kind of response.

    Args:
        character_id:      e.g. "aria"
        scene_id:          e.g. "bedroom" or "phone"
        context_tags_json: JSON list of current context tags e.g. '["intimate", "cuddle"]'
        stats_json:        JSON dict of current stats e.g. '{"arousal": 55, "openness": 40}'
        max_options:       Maximum number of options to return
    """
    try:
        from engine.mcp.tools.dialog_tools import get_dialog_options as _impl

        tags = json.loads(context_tags_json) if context_tags_json else []
        stats = json.loads(stats_json) if stats_json else {}
        return _impl(
            get_dialog_system(),
            character_id,
            scene_id,
            context_tags=tags,
            stats=stats,
            max_options=max_options,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})'''

new_gdo = '''@mcp.tool()
def get_dialog_options(
    character_id: str,
    scene_id: str,
    context_tags_json: str = "[]",
    stats_json: str = "{}",
    max_options: int = 4,
) -> str:
    """
    Get situationally appropriate dialog/action options for a character.
    Options are filtered by current stats and context tags.
    Use this before responding to pick the right kind of response.

    Args:
        character_id:      e.g. "aria"
        scene_id:          e.g. "bedroom" or "phone"
        context_tags_json: JSON list of current context tags e.g. '["intimate", "cuddle"]'
        stats_json:        JSON dict of current stats e.g. '{"arousal": 55, "openness": 40}'
        max_options:       Maximum number of options to return
    """
    tags = json.loads(context_tags_json) if context_tags_json else []
    stats = json.loads(stats_json) if stats_json else {}
    return get_dialog_options_impl(
        get_dialog_system(),
        character_id,
        scene_id,
        context_tags=tags,
        stats=stats,
        max_options=max_options,
    )'''

content = content.replace(old_gdo, new_gdo)

# speech_enhance
old_se = '''@mcp.tool()
def speech_enhance(
    character_id: str,
    text: str,
    style: str = "natural",
    scene_id: str = "",
) -> str:
    """
    Enhance or rewrite a piece of speech in the character's authentic voice.
    Returns a rewrite prompt you can use with an LLM, plus a quick heuristic
    version available immediately.

    Valid styles: natural, playful, warm, dominant, vulnerable, teasing,
                  direct, literary, whisper, charged

    Args:
        character_id: e.g. "aria"
        text:         The original text to enhance
        style:        Speech style to apply
        scene_id:     Current scene for context
    """
    try:
        return speech_enhance_impl(
            get_dialog_system(), character_id, text, style=style, scene_id=scene_id
        )
    except Exception as e:
        return json.dumps({"error": str(e)})'''

new_se = '''@mcp.tool()
def speech_enhance(
    character_id: str,
    text: str,
    style: str = "natural",
    scene_id: str = "",
) -> str:
    """
    Enhance or rewrite a piece of speech in the character's authentic voice.
    Returns a rewrite prompt you can use with an LLM, plus a quick heuristic
    version available immediately.

    Valid styles: natural, playful, warm, dominant, vulnerable, teasing,
                  direct, literary, whisper, charged

    Args:
        character_id: e.g. "aria"
        text:         The original text to enhance
        style:        Speech style to apply
        scene_id:     Current scene for context
    """
    return speech_enhance_impl(
        get_dialog_system(), character_id, text, style=style, scene_id=scene_id
    )'''

content = content.replace(old_se, new_se)

# set_response_directive
old_srd = '''@mcp.tool()
def set_response_directive(
    character_id: str,
    scene_id: str,
    directive_type: str,
    value: str,
    turns: int = 1,
    issued_by: str = "director",
) -> str:
    """
    Issue a directive that controls how the character responds for the next N turns.

    Directive types:
      force_response  — override the LLM: use this exact response
      must_include    — the reply MUST naturally include this phrase/fragment
      style_lock      — lock speech to a style: natural/playful/warm/dominant/
                        vulnerable/teasing/direct/literary/whisper/charged
      topic_steer     — steer the conversation toward this topic
      mood_set        — override the character's mood tone
      refuse          — character refuses the next action (in-character)

    Args:
        character_id:   Target character
        scene_id:       Scene context
        directive_type: One of the types above
        value:          The directive value (response text, style name, topic, etc.)
        turns:          How many turns this directive lasts
        issued_by:      Who issued it (for audit)
    """
    try:
        return set_response_directive_impl(
            get_dialog_system(),
            character_id,
            scene_id,
            directive_type=directive_type,
            value=value,
            turns=turns,
            issued_by=issued_by,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})'''

new_srd = '''@mcp.tool()
def set_response_directive(
    character_id: str,
    scene_id: str,
    directive_type: str,
    value: str,
    turns: int = 1,
    issued_by: str = "director",
) -> str:
    """
    Issue a directive that controls how the character responds for the next N turns.

    Directive types:
      force_response  — override the LLM: use this exact response
      must_include    — the reply MUST naturally include this phrase/fragment
      style_lock      — lock speech to a style: natural/playful/warm/dominant/
                        vulnerable/teasing/direct/literary/whisper/charged
      topic_steer     — steer the conversation toward this topic
      mood_set        — override the character's mood tone
      refuse          — character refuses the next action (in-character)

    Args:
        character_id:   Target character
        scene_id:       Scene context
        directive_type: One of the types above
        value:          The directive value (response text, style name, topic, etc.)
        turns:          How many turns this directive lasts
        issued_by:      Who issued it (for audit)
    """
    return set_response_directive_impl(
        get_dialog_system(),
        character_id,
        scene_id,
        directive_type=directive_type,
        value=value,
        turns=turns,
        issued_by=issued_by,
    )'''

content = content.replace(old_srd, new_srd)

# get_active_directive
old_gad = '''@mcp.tool()
def get_active_directive(character_id: str, scene_id: str) -> str:
    """
    Return the currently active response directive for a character in a scene,
    or null if none is set.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "bedroom"
    """
    try:
        return get_active_directive_impl(get_dialog_system(), character_id, scene_id)
    except Exception as e:
        return json.dumps({"error": str(e)})'''

new_gad = '''@mcp.tool()
def get_active_directive(character_id: str, scene_id: str) -> str:
    """
    Return the currently active response directive for a character in a scene,
    or null if none is set.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "bedroom"
    """
    return get_active_directive_impl(get_dialog_system(), character_id, scene_id)'''

content = content.replace(old_gad, new_gad)

# clear_directive
old_cd = '''@mcp.tool()
def clear_directive(character_id: str, scene_id: str) -> str:
    """
    Clear any active response directive for a character.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "bedroom"
    """
    try:
        return clear_directive_impl(get_dialog_system(), character_id, scene_id)
    except Exception as e:
        return json.dumps({"error": str(e)})'''

new_cd = '''@mcp.tool()
def clear_directive(character_id: str, scene_id: str) -> str:
    """
    Clear any active response directive for a character.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "bedroom"
    """
    return clear_directive_impl(get_dialog_system(), character_id, scene_id)'''

content = content.replace(old_cd, new_cd)

# get_conversation_heat
old_gch = '''@mcp.tool()
def get_conversation_heat(character_id: str, scene_id: str) -> str:
    """
    Return the current conversation heat (0-100) for a character in a scene.
    Higher heat = more intense/intimate exchange.  Affects dialog option availability.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "phone"
    """
    try:
        return get_conversation_heat_impl(get_dialog_system(), character_id, scene_id)
    except Exception as e:
        return json.dumps({"error": str(e)})'''

new_gch = '''@mcp.tool()
def get_conversation_heat(character_id: str, scene_id: str) -> str:
    """
    Return the current conversation heat (0-100) for a character in a scene.
    Higher heat = more intense/intimate exchange.  Affects dialog option availability.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "phone"
    """
    return get_conversation_heat_impl(get_dialog_system(), character_id, scene_id)'''

content = content.replace(old_gch, new_gch)

with open("engine/mcp/cosysim_server.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated server script")
