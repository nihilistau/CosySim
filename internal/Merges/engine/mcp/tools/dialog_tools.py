"""
Pure business-logic helpers for dialog / speech MCP tools.

Each function receives its dependencies (dialog system, registries, etc.)
as explicit parameters so the module stays free of global MCP state.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging
from pydantic import BaseModel, Field
from engine.mcp.decorators import mcp_tool, ToolExecutionError

logger = logging.getLogger(__name__)


# ── Domain Models ────────────────────────────────────────────────────


class DialogOptionsResponse(BaseModel):
    options: List[str]
    conversation_heat: int
    scene: str


class DirectiveResponse(BaseModel):
    ok: bool
    character_id: str
    scene: Optional[str] = None
    directive_type: Optional[str] = None
    turns: Optional[int] = None
    behavior: Optional[str] = None
    active: Optional[bool] = None


class ConversationHeatResponse(BaseModel):
    heat: int
    turn: int
    recent_topics: List[str]


# ── get_dialog_options ───────────────────────────────────────────────


@mcp_tool
def get_dialog_options(
    dialog_system: Any,
    character_id: str,
    scene_id: str,
    context_tags: Optional[List[str]] = None,
    stats: Optional[Dict[str, Any]] = None,
    max_options: int = 4,
) -> DialogOptionsResponse:
    """Return situationally appropriate dialog/action options."""
    tags = context_tags or []
    st = stats or {}
    opts = dialog_system.get_options(
        character_id,
        scene_id,
        context_tags=tags,
        stats=st,
        max_options=max_options,
    )
    heat = dialog_system.get_conversation_heat(character_id, scene_id)
    return DialogOptionsResponse(options=opts, conversation_heat=heat, scene=scene_id)


# ── speech_enhance ───────────────────────────────────────────────────


@mcp_tool
def speech_enhance(
    dialog_system: Any,
    character_id: str,
    text: str,
    style: str = "natural",
    scene_id: str = "",
) -> Dict[str, Any]:
    """Enhance *text* in the character's authentic voice."""
    result = dialog_system.enhance_speech(
        character_id, text, style=style, scene=scene_id
    )
    return result


# ── set_response_directive ───────────────────────────────────────────


@mcp_tool
def set_response_directive(
    dialog_system: Any,
    character_id: str,
    scene_id: str,
    directive_type: str,
    value: str,
    turns: int = 1,
    issued_by: str = "director",
) -> DirectiveResponse:
    """Issue a directive controlling the character's next *turns* responses."""
    dialog_system.set_directive(
        character_id,
        scene_id,
        directive_type=directive_type,
        value=value,
        turns=turns,
        issued_by=issued_by,
    )
    return DirectiveResponse(
        ok=True,
        character_id=character_id,
        scene=scene_id,
        directive_type=directive_type,
        turns=turns,
    )


# ── get_active_directive ─────────────────────────────────────────────


@mcp_tool
def get_active_directive(
    dialog_system: Any,
    character_id: str,
    scene_id: str,
) -> Dict[str, Any]:
    """Return the currently active response directive, or ``{active: false}``."""
    directive = dialog_system.get_active_directive(character_id, scene_id)
    return directive or {"active": False}


# ── clear_directive ──────────────────────────────────────────────────


@mcp_tool
def clear_directive(
    dialog_system: Any,
    character_id: str,
    scene_id: str,
) -> DirectiveResponse:
    """Clear any active response directive for a character."""
    dialog_system.clear_directive(character_id, scene_id)
    return DirectiveResponse(ok=True, character_id=character_id, scene=scene_id)


# ── get_conversation_heat ────────────────────────────────────────────


@mcp_tool
def get_conversation_heat(
    dialog_system: Any,
    character_id: str,
    scene_id: str,
) -> ConversationHeatResponse:
    """Return conversation heat (0-100), turn count, and recent topics."""
    heat = dialog_system.get_conversation_heat(character_id, scene_id)
    turn = dialog_system.get_turn(character_id, scene_id)
    topics = dialog_system.get_recent_topics(character_id, scene_id)
    return ConversationHeatResponse(heat=heat, turn=turn, recent_topics=topics)


# ── speak_as ─────────────────────────────────────────────────────────


@mcp_tool
def speak_as(
    dialog_system: Any,
    character_registry: Any,
    character_id: str,
    text: str,
    style: str = "",
    scene_id: str = "",
) -> Dict[str, Any]:
    """Transform plain *text* into the character's authentic voice."""
    from engine.mcp.dialog_system import SpeechStyle

    character_registry.ensure(character_id)

    # Auto-select style based on mood if not specified
    if not style:
        try:
            state = character_registry.get_state(character_id)
            mood_map = {
                "excited": SpeechStyle.PLAYFUL,
                "aroused": SpeechStyle.CHARGED,
                "tender": SpeechStyle.WARM,
                "dominant": SpeechStyle.DOMINANT,
                "sad": SpeechStyle.VULNERABLE,
                "teasing": SpeechStyle.TEASING,
                "confident": SpeechStyle.DIRECT,
                "reflective": SpeechStyle.LITERARY,
                "whisper": SpeechStyle.WHISPER,
            }
            style = (
                mood_map.get(state.mood, SpeechStyle.NATURAL)
                if state
                else SpeechStyle.NATURAL
            )
        except Exception:
            style = SpeechStyle.NATURAL

    result = dialog_system.enhance_speech(
        character_id, text, style=style, scene=scene_id
    )
    result["character_id"] = character_id
    return result


# ── enforce_behavior ─────────────────────────────────────────────────


@mcp_tool
def enforce_behavior(
    dialog_system: Any,
    character_id: str,
    behavior_type: str,
    value: str,
    reason: str = "",
    scene_id: str = "",
    turns: int = 1,
    ssm: Any = None,
) -> DirectiveResponse:
    """Force, block, or shape a character's next response via a directive."""
    dialog_system.set_directive(
        character_id,
        scene_id,
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
                scene_id or "bedroom",
                note,
                entry_type="directive",
                character_id=character_id,
            )
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

    return DirectiveResponse(
        ok=True, character_id=character_id, behavior=behavior_type, turns=turns
    )

class EnhanceResponse(BaseModel):
    original: str
    enhanced: str
    instruction: str

@mcp_tool
def intercept_and_enhance_impl(original_message: str, instruction: str, manager: Any) -> EnhanceResponse:
    from engine.protocols import InferenceRequest

    request = InferenceRequest(
        agent_id="mcp_enhance",
        messages=[
            {
                "role": "system",
                "content": "You are a message editor. Reshape the given message according to "
                "the instruction. Return ONLY the rewritten message, nothing else.",
            },
            {
                "role": "user",
                "content": f"Original:\n{original_message}\n\nInstruction:\n{instruction}",
            },
        ],
        max_output_tokens=300,
        temperature=0.7,
    )

    try:
        response = manager.infer(request)
        return EnhanceResponse(
            original=original_message,
            enhanced=response.text.strip(),
            instruction=instruction
        )
    except Exception as e:
        raise ToolExecutionError(f"Failed to enhance: {e}")
