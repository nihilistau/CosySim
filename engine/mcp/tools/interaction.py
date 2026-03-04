"""MCP tool domain: interaction.

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

# ──── INTERACTION TOOLS ──────────────────────────────────────────────────


@mcp_tool
def perform_interaction(
    interaction_type: str,
    initiator_id: str,
    target_id: str,
    scene_id: str = "bedroom",
    subtype: str = "",
    intensity: int = 0,
) -> str:
    """
    Perform one of the 6 core interaction types between two characters.

    BEDROOM interaction_types:
      cuddle    — physical closeness (subtypes: embrace, spoon, lap_sit, entangled)
      kiss      — kissing (subtypes: soft, neck, deep, trail, urgent)
      caress    — tactile touch (subtypes: hair, back, face, body)
      striptease — undressing performance (subtypes: tease_outer, slow_reveal, dance_strip, interactive_strip)
      intimate  — sexual encounter (subtypes: foreplay, oral, passionate, directed, afterglow)
      deep_talk — intimate conversation (subtypes: pillow_talk, dirty_talk, whisper, confession, fantasy_share)

    PHONE interaction_types:
      flirt_text | sext | voice_call | video_call | send_media | roleplay_text

    intensity: 0=auto-select based on stats, 1-5=force min intimacy level
    subtype: override auto-selection with a specific subtype id

    Returns the interaction result, narrative fragments, stat effects applied,
    and a timed action token if the interaction takes time.
    """
    try:
        it = _itrees()
        initiator_stats = _ssm().get_stats(initiator_id).to_dict()
        result = it.get_interaction_result(
            interaction_type,
            subtype or None,
            initiator_stats=initiator_stats,
            target_stats=_ssm().get_stats(target_id).to_dict() if target_id else None,
            scene=scene_id,
            intensity_override=intensity or None,
        )

        if "error" in result:
            return json.dumps(result, default=str)

        # Apply stat effects to both characters
        for char_id in [initiator_id, target_id]:
            if char_id:
                _ssm().update_stats(char_id, **result["stat_effects"])

        # Log to narrative
        opening = result.get("narrative_opening", "")
        _ssm().add_narrative(
            scene_id,
            opening,
            character_id=initiator_id,
            entry_type="action",
        )

        # Log interaction record
        from engine.mcp.scene_state import InteractionRecord
        record = InteractionRecord(
            interaction_id=json.dumps({"t": result["type"], "s": result["subtype"]})[:32],
            scene_id=scene_id,
            interaction_type=result["type"],
            subtype=result["subtype"],
            initiator_id=initiator_id,
            target_id=target_id,
            description=result["description"],
            duration_secs=result["duration_secs"],
            stat_effects=result["stat_effects"],
        )
        _ssm().log_interaction(scene_id, record)

        # Start timed action if duration > 0
        action_token = None
        if result["duration_secs"] > 0:
            action_token = _ssm().start_timed_action(
                initiator_id,
                action_type=result["type"],
                duration=result["duration_secs"],
                description=result["description"],
                phase_labels=result.get("phases", []),
            )

        # Updated stats
        new_stats = _ssm().get_stats(initiator_id).to_dict()

        return json.dumps({
            "interaction":        result,
            "stat_effects_applied": result["stat_effects"],
            "initiator_new_stats":  new_stats,
            "initiator_emotional_state": _ssm().get_stats(initiator_id).emotional_state_text(),
            "timed_action_token": action_token,
            "narrative_fragment": opening,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def list_available_interactions(character_id: str, scene_id: str = "bedroom") -> str:
    """
    List all interaction types and their accessible subtypes for a character
    based on their current stats.  Use this before calling perform_interaction
    to know what's available without guessing.

    Returns a filtered list — only shows subtypes whose stat requirements are met.
    """
    try:
        it = _itrees()
        stats = _ssm().get_stats(character_id).to_dict()
        available = it.get_available_interactions(stats, scene=scene_id)
        all_types = it.list_interaction_types(scene=scene_id)
        return json.dumps({
            "character_id":  character_id,
            "emotional_state": _ssm().get_stats(character_id).emotional_state_text(),
            "available_now": available,
            "all_types":     all_types,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_interaction_details(
    interaction_type: str,
    subtype: str = "",
    scene_id: str = "bedroom",
) -> str:
    """
    Get detailed information about a specific interaction type/subtype —
    description, phases, sample narrative fragments, stat effects, requirements.

    Call this to understand what an interaction involves before using it,
    or to pick the right fragments for your narration.
    """
    try:
        it = _itrees()
        trees = it.BEDROOM_INTERACTIONS if scene_id == "bedroom" else it.PHONE_INTERACTIONS
        itype = trees.get(interaction_type)
        if not itype:
            return json.dumps({"error": f"Unknown type '{interaction_type}'"})
        if subtype:
            sub = itype.get_subtype(subtype)
            if not sub:
                return json.dumps({"error": f"Unknown subtype '{subtype}'"})
            import dataclasses
            return json.dumps(dataclasses.asdict(sub), indent=2)
        # Return overview of all subtypes
        return json.dumps({
            "type":     itype.id,
            "label":    itype.label,
            "description": itype.description,
            "subtypes": [
                {
                    "id": s.id, "label": s.label,
                    "description": s.description,
                    "intimacy": s.intimacy,
                    "duration": s.duration,
                    "stat_effects": s.stat_effects,
                    "phases": s.phases,
                    "sample_fragments": s.fragments[:3],
                    "requires": s.requires,
                }
                for s in itype.subtypes
            ],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def start_timed_action(
    character_id: str,
    action_type: str,
    duration_secs: float = 30.0,
    description: str = "",
    phases: str = "",
) -> str:
    """
    Start a long-form action that plays out over real time.
    Returns a token you can use to poll progress.

    Use for anything that should feel like it takes time:
    striptease, massage, sex, bath scene, dance, etc.

    phases: comma-separated phase labels e.g. 'beginning,building,peak,afterglow'
    duration_secs: how long the action takes (15-120 typical)
    """
    try:
        phase_list = [p.strip() for p in phases.split(",") if p.strip()] if phases else []
        token = _ssm().start_timed_action(
            character_id, action_type,
            duration=duration_secs,
            description=description,
            phase_labels=phase_list,
        )
        return json.dumps({
            "started": True,
            "token": token,
            "character_id": character_id,
            "action_type": action_type,
            "duration_secs": duration_secs,
            "description": description,
            "message": f"Use poll_timed_action('{token}') to check progress.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def poll_timed_action(token: str) -> str:
    """
    Check the progress of a running timed action.
    Returns phase name, progress (0.0-1.0), elapsed time, and completion status.

    Check this periodically to narrate an unfolding scene.  When complete=true
    the action has finished — emit the afterglow narrative.
    """
    try:
        status = _ssm().poll_timed_action(token)
        if not status:
            return json.dumps({"error": f"No action found with token '{token}'"})
        return json.dumps(status, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def abort_timed_action(token: str) -> str:
    """Stop a timed action early (e.g. interrupted by Director or refused by character)."""
    try:
        ok = _ssm().abort_timed_action(token)
        return json.dumps({"aborted": ok, "token": token})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def list_active_timed_actions(character_id: str = "") -> str:
    """
    List all currently running timed actions.
    Pass character_id to filter to a specific character, or leave blank for all.
    """
    try:
        actions = _ssm().active_timed_actions(character_id=character_id or None)
        return json.dumps({"active_actions": actions, "count": len(actions)}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
