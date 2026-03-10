"""
Pure business-logic helpers for dialog / speech MCP tools.

Each function receives its dependencies (dialog system, registries, etc.)
as explicit parameters so the module stays free of global MCP state.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


# ── get_dialog_options ───────────────────────────────────────────────

def get_dialog_options(
    dialog_system: Any,
    character_id: str,
    scene_id: str,
    context_tags: Optional[List[str]] = None,
    stats: Optional[Dict[str, Any]] = None,
    max_options: int = 4,
) -> str:
    """Return situationally appropriate dialog/action options."""
    try:
        tags = context_tags or []
        st = stats or {}
        opts = dialog_system.get_options(
            character_id, scene_id,
            context_tags=tags, stats=st, max_options=max_options,
        )
        heat = dialog_system.get_conversation_heat(character_id, scene_id)
        return json.dumps({"options": opts, "conversation_heat": heat, "scene": scene_id}, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── speech_enhance ───────────────────────────────────────────────────

def speech_enhance(
    dialog_system: Any,
    character_id: str,
    text: str,
    style: str = "natural",
    scene_id: str = "",
) -> str:
    """Enhance *text* in the character's authentic voice."""
    try:
        result = dialog_system.enhance_speech(character_id, text, style=style, scene=scene_id)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── set_response_directive ───────────────────────────────────────────

def set_response_directive(
    dialog_system: Any,
    character_id: str,
    scene_id: str,
    directive_type: str,
    value: str,
    turns: int = 1,
    issued_by: str = "director",
) -> str:
    """Issue a directive controlling the character's next *turns* responses."""
    try:
        dialog_system.set_directive(
            character_id, scene_id,
            directive_type=directive_type,
            value=value,
            turns=turns,
            issued_by=issued_by,
        )
        return json.dumps({
            "ok": True, "character_id": character_id, "scene": scene_id,
            "directive_type": directive_type, "turns": turns,
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ── get_active_directive ─────────────────────────────────────────────

def get_active_directive(
    dialog_system: Any,
    character_id: str,
    scene_id: str,
) -> str:
    """Return the currently active response directive, or ``{active: false}``."""
    try:
        directive = dialog_system.get_active_directive(character_id, scene_id)
        return json.dumps(directive or {"active": False})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── clear_directive ──────────────────────────────────────────────────

def clear_directive(
    dialog_system: Any,
    character_id: str,
    scene_id: str,
) -> str:
    """Clear any active response directive for a character."""
    try:
        dialog_system.clear_directive(character_id, scene_id)
        return json.dumps({"ok": True, "character_id": character_id, "scene": scene_id})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ── get_conversation_heat ────────────────────────────────────────────

def get_conversation_heat(
    dialog_system: Any,
    character_id: str,
    scene_id: str,
) -> str:
    """Return conversation heat (0-100), turn count, and recent topics."""
    try:
        heat = dialog_system.get_conversation_heat(character_id, scene_id)
        turn = dialog_system.get_turn(character_id, scene_id)
        topics = dialog_system.get_recent_topics(character_id, scene_id)
        return json.dumps({"heat": heat, "turn": turn, "recent_topics": topics})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── speak_as ─────────────────────────────────────────────────────────

def speak_as(
    dialog_system: Any,
    character_registry: Any,
    character_id: str,
    text: str,
    style: str = "",
    scene_id: str = "",
) -> str:
    """Transform plain *text* into the character's authentic voice."""
    try:
        from engine.mcp.dialog_system import SpeechStyle

        character_registry.ensure(character_id)

        # Auto-select style based on mood if not specified
        if not style:
            try:
                state = character_registry.get_state(character_id)
                mood_map = {
                    "excited":    SpeechStyle.PLAYFUL,
                    "aroused":    SpeechStyle.CHARGED,
                    "tender":     SpeechStyle.WARM,
                    "dominant":   SpeechStyle.DOMINANT,
                    "sad":        SpeechStyle.VULNERABLE,
                    "teasing":    SpeechStyle.TEASING,
                    "confident":  SpeechStyle.DIRECT,
                    "reflective": SpeechStyle.LITERARY,
                    "whisper":    SpeechStyle.WHISPER,
                }
                style = mood_map.get(state.mood, SpeechStyle.NATURAL) if state else SpeechStyle.NATURAL
            except Exception:
                style = SpeechStyle.NATURAL

        result = dialog_system.enhance_speech(character_id, text, style=style, scene=scene_id)
        result["character_id"] = character_id
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── enforce_behavior ─────────────────────────────────────────────────

def enforce_behavior(
    dialog_system: Any,
    character_id: str,
    behavior_type: str,
    value: str,
    reason: str = "",
    scene_id: str = "",
    turns: int = 1,
    ssm: Any = None,
) -> str:
    """Force, block, or shape a character's next response via a directive."""
    try:
        dialog_system.set_directive(
            character_id, scene_id,
            directive_type=behavior_type,
            value=value,
            turns=turns,
            issued_by=f"enforce_behavior:{reason or 'unspecified'}",
        )
        # Audit to scene narrative
        if ssm is not None:
            try:
                note = f"[Director enforced {behavior_type} on {character_id}]"
                if reason:
                    note += f" Reason: {reason}"
                ssm.add_narrative(
                    scene_id or "penthouse", note,
                    entry_type="directive", character_id=character_id,
                )
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)
        return json.dumps({"ok": True, "character_id": character_id, "behavior": behavior_type, "turns": turns})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})
