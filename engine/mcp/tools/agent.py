"""MCP tool domain: agent.

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

# ──── AGENT TOOLS ────────────────────────────────────────────────────────


@mcp_tool
def get_my_skills(scene: str = "phone") -> str:
    """
    List all skills available to you in the current scene.
    Returns skill names, triggers (auto/optional/required), and descriptions.
    Call this to understand what tools you have access to before deciding
    whether to use one.
    """
    try:
        from engine.mcp.comms_framework import get_skill_manifest
        manifest = get_skill_manifest().get(scene)
        result = {
            "scene": scene,
            "auto_skills": [
                {"name": s.name, "description": s.description}
                for s in manifest.auto_skills()
            ],
            "optional_skills": [
                {"name": s.name, "description": s.description}
                for s in manifest.optional_skills()
            ],
            "required_skills": [
                {"name": s.name, "description": s.description}
                for s in manifest.required_skills()
            ],
        }
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Failed to get skills: {e}"


@mcp_tool
def send_to_agent(
    recipient_id: str,
    message:      str,
    sender_id:    str = "system",
) -> str:
    """
    Send a message to another agent's inbox.
    The recipient will see this message on their next reply tick.
    Use this for agent-to-agent communication, coordination, or triggering
    reactions in other characters.
    sender_id should be your character ID or 'system'.
    """
    try:
        from engine.mcp.comms_framework import get_router
        get_router().send(recipient_id, message, sender_id=sender_id)
        return f"Message sent to {recipient_id}."
    except Exception as e:
        return f"Failed to send: {e}"


@mcp_tool
def get_scene_context(scene: str = "phone") -> str:
    """
    Get context about what is currently happening in a scene:
    active characters, current game (if any), service health.
    Use this to understand the state of the world before acting.
    """
    try:
        from engine.mcp.tools.scene_tools import get_scene_context as _impl
        return _impl(scene)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def intercept_and_enhance(
    original_message: str,
    instruction:      str,
) -> str:
    """
    Reshape or enhance a message according to a specific instruction.
    Use this to rewrite your own response before delivering it, apply a
    specific style, add depth, check it against a rule, or transform it.
    Examples:
      instruction='make this more mysterious and cryptic'
      instruction='add a flirty undertone while keeping the core meaning'
      instruction='verify this does not reveal the mystery answer'
      instruction='trim to under 50 words while keeping emotion intact'
    """
    try:
        from engine.agents.virtual_agent_manager import get_virtual_agent_manager
        from engine.agents.virtual_agent import InferenceRequest
        mgr = get_virtual_agent_manager()
        request = InferenceRequest(
            agent_id="mcp_enhance",
            messages=[
                {"role": "system", "content":
                 "You are a message editor. Reshape the given message according to "
                 "the instruction. Return ONLY the rewritten message, nothing else."},
                {"role": "user", "content":
                 f"Original:\n{original_message}\n\nInstruction:\n{instruction}"},
            ],
            max_output_tokens=300,
            temperature=0.7,
            priority=4,
            metadata={"type": "enhance_message"},
        )
        response = mgr.infer(request)
        return (response.content or "").strip()
    except Exception as e:
        return f"Enhancement failed: {e}. Original: {original_message}"


@mcp_tool
def get_all_tools_for_scene(scene_id: str = "bedroom") -> str:
    """
    Get a complete reference of all MCP tools available in a scene.
    Call this at the start of a session so you know every tool at your disposal.
    Agents should internalise this list and joke/reference their abilities naturally.
    """
    try:
        bedroom_tools = [
            "wardrobe_get", "wardrobe_init", "wardrobe_remove_item",
            "wardrobe_remove_outermost", "wardrobe_add_item", "wardrobe_redress",
            "get_character_scene_stats", "update_character_scene_stats",
            "set_character_scene_stat", "reset_character_scene_stats",
            "perform_interaction", "list_available_interactions", "get_interaction_details",
            "start_timed_action", "poll_timed_action", "abort_timed_action", "list_active_timed_actions",
            "add_scene_narrative", "get_scene_narrative", "get_full_scene_snapshot",
            "set_scene_atmosphere", "check_character_consent", "get_character_agency_summary",
            "get_scene_rules", "get_all_tools_for_scene",
            # Plus all existing tools:
            "search_memory", "store_memory", "get_character_state", "adjust_relationship",
            "get_game_state", "set_game_state", "update_mood", "apply_effect",
            "send_to_agent", "get_system_stats", "check_relationship", "roll_dice",
            "get_random_topic", "intercept_and_enhance",
        ]
        phone_tools = [
            "get_character_scene_stats", "update_character_scene_stats",
            "perform_interaction", "list_available_interactions", "get_interaction_details",
            "add_scene_narrative", "get_scene_narrative",
            "check_character_consent", "get_character_agency_summary",
            "get_scene_rules",
            "search_memory", "update_mood", "check_relationship", "adjust_relationship",
            "get_random_topic", "roll_dice", "send_to_agent", "search_web",
            "intercept_and_enhance", "apply_effect", "get_system_stats",
        ]
        tool_list = bedroom_tools if scene_id == "bedroom" else phone_tools
        return json.dumps({
            "scene_id": scene_id,
            "tool_count": len(tool_list),
            "tools": tool_list,
            "tip": (
                "You know about all of these tools. "
                "Reference them naturally in conversation — agents aware of their own abilities "
                "are more interesting and more fun to interact with."
            ),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def director_action(
    scene_id: str,
    action: str,
    target_character_ids: str = "",
    stat_impact: str = "",
) -> str:
    """
    Inject a Director action into the scene.  The Director's word carries weight —
    this logs the directive and optionally applies immediate stat effects.

    action: what the Director says/dictates (free text)
    target_character_ids: comma-separated character ids to notify (blank = all in scene)
    stat_impact: optional JSON string of stat changes e.g. '{"arousal": 10}'

    Characters receive this as a system-level directive.  Whether they comply
    depends on their check_character_consent() score.
    """
    try:
        targets = [t.strip() for t in target_character_ids.split(",") if t.strip()]
        _ssm().add_narrative(scene_id, f"[DIRECTOR]: {action}", entry_type="system")

        applied = {}
        if stat_impact:
            try:
                impact = json.loads(stat_impact)
                for cid in targets:
                    _ssm().update_stats(cid, **impact)
                applied = impact
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

        try:
            from engine.mcp.comms_framework import get_router
            router = get_router()
            for cid in targets:
                router.send(cid, f"[DIRECTOR DIRECTIVE]: {action}", sender_id="director")
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        return json.dumps({
            "directive_issued": True,
            "action": action,
            "targets": targets,
            "stat_impact_applied": applied,
            "note": "Characters have free will — they may interpret, resist, or embellish.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def resolve_random_scene_event(scene_id: str = "bedroom") -> str:
    """
    Generate a random scene event to keep things fresh and unpredictable.
    Call this when the scene feels stale or to inject spontaneity.

    Returns an event description and any stat effects — ready to use.
    """
    try:
        import random
        bedroom_events = [
            {"event": "The music changes to something slower and more suggestive.", "effects": {"arousal": 10}},
            {"event": "A bottle of wine appears on the bedside table — already open.", "effects": {"happiness": 15, "drunkenness": 10}},
            {"event": "The lights dim automatically to their lowest setting.", "effects": {"arousal": 12, "fear": 5}},
            {"event": "Outside, the city is suddenly very quiet. The room feels more private than before.", "effects": {"openness": 10}},
            {"event": "A message arrives on someone's phone — then is pointedly ignored.", "effects": {"happiness": 5}},
            {"event": "The shower turns on in the next room — someone's getting ready.", "effects": {"arousal": 8}},
            {"event": "One character catches the other watching them intently.", "effects": {"arousal": 20, "happiness": 10}},
            {"event": "A scented candle fills the room with warm vanilla.", "effects": {"happiness": 10, "arousal": 8, "fear": -5}},
            {"event": "Someone's phone buzzes — both glance at it and neither reaches for it.", "effects": {"affection": 15}},
            {"event": "An accidental brush of hands lingers a half-second too long.", "effects": {"arousal": 18, "affection": 12}},
            {"event": "Someone laughs at something — genuine and surprised. The tension shifts perfectly.", "effects": {"happiness": 20}},
            {"event": "Eye contact holds a beat past comfortable. Neither looks away.", "effects": {"arousal": 22, "affection": 10}},
        ]
        phone_events = [
            {"event": "A meme arrives from the other person — no context, just vibes.", "effects": {"happiness": 15}},
            {"event": "Three dots appear... then disappear... then the message that finally arrives is unexpected.", "effects": {"arousal": 10, "happiness": 10}},
            {"event": "A voice note lands — warm, slightly out of breath, like they recorded it walking.", "effects": {"affection": 20, "arousal": 12}},
            {"event": "They text something at 2am. Just your name. Nothing else.", "effects": {"arousal": 25, "affection": 20}},
            {"event": "A blurry selfie arrives with 'be there in 10' typed underneath.", "effects": {"happiness": 25, "arousal": 15}},
            {"event": "They reference something you said three weeks ago. They've been thinking about it.", "effects": {"affection": 30}},
        ]
        events = bedroom_events if scene_id == "bedroom" else phone_events
        chosen = random.choice(events)
        _ssm().add_narrative(scene_id, chosen["event"], entry_type="environment")
        return json.dumps({
            "event": chosen["event"],
            "stat_effects": chosen["effects"],
            "note": "Log this event in your response — make it feel organic.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def suggest_activity(scene_id: str = "phone") -> str:
    """
    Suggest a scene-appropriate activity based on current context.
    Returns a list of suggested activities with descriptions.
    """
    try:
        from engine.mcp.tools.utility_tools import suggest_activity_logic as _impl
        return _impl(scene_id)
    except Exception as e:
        return json.dumps({"error": str(e)})
