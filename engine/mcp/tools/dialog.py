"""MCP tool domain: dialog.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── DIALOG TOOLS ───────────────────────────────────────────────────────


@mcp_tool
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
        scene_id:          e.g. "penthouse" or "phone"
        context_tags_json: JSON list of current context tags e.g. '["intimate", "cuddle"]'
        stats_json:        JSON dict of current stats e.g. '{"arousal": 55, "openness": 40}'
        max_options:       Maximum number of options to return
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        from engine.mcp.tools.dialog_tools import get_dialog_options as _impl
        tags  = json.loads(context_tags_json) if context_tags_json else []
        stats = json.loads(stats_json)        if stats_json        else {}
        return _impl(get_dialog_system(), character_id, scene_id,
                     context_tags=tags, stats=stats, max_options=max_options)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
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
        from engine.mcp.dialog_system import get_dialog_system
        from engine.mcp.tools.dialog_tools import speech_enhance as _impl
        return _impl(get_dialog_system(), character_id, text, style=style, scene_id=scene_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
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
        from engine.mcp.dialog_system import get_dialog_system
        from engine.mcp.tools.dialog_tools import set_response_directive as _impl
        return _impl(get_dialog_system(), character_id, scene_id,
                     directive_type=directive_type, value=value, turns=turns,
                     issued_by=issued_by)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_active_directive(character_id: str, scene_id: str) -> str:
    """
    Return the currently active response directive for a character in a scene,
    or null if none is set.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "penthouse"
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        from engine.mcp.tools.dialog_tools import get_active_directive as _impl
        return _impl(get_dialog_system(), character_id, scene_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def clear_directive(character_id: str, scene_id: str) -> str:
    """
    Clear any active response directive for a character.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "penthouse"
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        from engine.mcp.tools.dialog_tools import clear_directive as _impl
        return _impl(get_dialog_system(), character_id, scene_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_conversation_heat(character_id: str, scene_id: str) -> str:
    """
    Return the current conversation heat (0-100) for a character in a scene.
    Higher heat = more intense/intimate exchange.  Affects dialog option availability.

    Args:
        character_id: e.g. "aria"
        scene_id:     e.g. "phone"
    """
    try:
        from engine.mcp.dialog_system import get_dialog_system
        from engine.mcp.tools.dialog_tools import get_conversation_heat as _impl
        return _impl(get_dialog_system(), character_id, scene_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def start_timer(
    timer_name:       str,
    duration_secs:    float,
    on_complete_note: str   = "",
) -> str:
    """
    **TIMER SKILL** — Start a named countdown timer.

    Timers are turn-passive: they count real-world seconds but are only
    checked when you call ``check_timer()``.  Use them for:
    - "Her blush takes 30 seconds to fade" → start_timer("blush_fade", 30)
    - "The massage lasts 3 minutes" → start_timer("massage", 180, "Massage complete — she's relaxed and warm")
    - Cooldowns, tension windows, delayed reveals

    Multiple timers can run simultaneously under different names.

    Args:
        timer_name:       Unique name you will use to check this timer
        duration_secs:    How long the timer runs in real seconds
        on_complete_note: Text returned when the timer finishes (use it in your response)
    """
    try:
        from engine.mcp.tools.utility_tools import start_timer_logic as _impl
        return _impl(timer_name, duration_secs, on_complete_note=on_complete_note)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def check_timer(timer_name: str) -> str:
    """
    **TIMER SKILL** — Check the state of a running timer.

    Returns remaining time, progress percentage, and whether it has completed.
    When completed, the ``on_complete_note`` field tells you what should happen.

    Call this every turn for any timer that is still running.
    Use the progress to describe physical/emotional state mid-timer.

    Args:
        timer_name: The name you gave when starting the timer
    """
    try:
        from engine.mcp.tools.utility_tools import check_timer_logic as _impl
        return _impl(timer_name)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def cancel_timer(timer_name: str) -> str:
    """
    **TIMER SKILL** — Cancel a running timer before it completes.

    Args:
        timer_name: The timer to cancel
    """
    try:
        from engine.mcp.tools.utility_tools import cancel_timer_logic as _impl
        return _impl(timer_name)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_conversation_heat_level(conversation_id: str) -> str:
    """
    Get the current heat level (0-100) for a conversation.
    Heat increases with flirty/intimate content and decays over time.
    Returns JSON with the heat level and current directive.
    """
    try:
        from engine.mcp.scene_rules_engine import get_conversation_heat
        heat = get_conversation_heat()
        level = heat.get(conversation_id)
        directive = heat.get_directive(conversation_id)
        return json.dumps({
            "conversation_id": conversation_id,
            "heat": round(level, 1),
            "directive": directive or "normal",
            "thresholds": {"warm": 30, "hot": 60, "intense": 80},
        })
    except Exception as e:
        return json.dumps({"error": str(e)})
