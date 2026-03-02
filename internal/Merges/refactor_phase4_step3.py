import re
import os

with open('engine/mcp/tools/scene_tools.py', 'a', encoding='utf-8') as f:
    f.write("""
# ── Character Scene Stats & Interactions ──────────────────────────────

def _coord():
    from engine.mcp.state_coordinator import get_coordinator
    return get_coordinator()

def _itrees():
    from engine.mcp import interaction_trees as it
    return it

@mcp_tool
def get_character_scene_stats_impl(character_id: str) -> Dict[str, Any]:
    stats = _ssm().get_stats(character_id)
    wardrobe = _ssm().get_wardrobe(character_id)
    return {
        "character_id": character_id,
        "stats": stats.to_dict(),
        "emotional_state": stats.emotional_state_text(),
        "wearing": wardrobe.coverage_description(),
        "is_naked": len(wardrobe.worn_items()) == 0,
    }

@mcp_tool
def update_character_scene_stats_impl(character_id: str, stat_changes: str) -> Dict[str, Any]:
    try:
        changes = json.loads(stat_changes) if isinstance(stat_changes, str) else stat_changes
    except Exception:
        raise ToolExecutionError('stat_changes must be valid JSON: {"stat": delta}')
    
    _coord().update(character_id, source="mcp_tool", **changes)
    stats = _ssm().get_stats(character_id)
    return {
        "updated": True,
        "character_id": character_id,
        "applied_changes": changes,
        "new_stats": stats.to_dict(),
        "emotional_state": stats.emotional_state_text(),
    }

@mcp_tool
def set_character_scene_stat_impl(character_id: str, stat: str, value: float) -> Dict[str, Any]:
    _coord().update(character_id, mode="set", source="mcp_tool", **{stat: value})
    stats = _ssm().get_stats(character_id)
    return {
        "set": True,
        "stat": stat,
        "value": getattr(stats, stat, None),
        "emotional_state": stats.emotional_state_text(),
    }

@mcp_tool
def reset_character_scene_stats_impl(character_id: str) -> Dict[str, Any]:
    stats = _ssm().reset_stats(character_id)
    return {
        "reset": True,
        "character_id": character_id,
        "stats": stats.to_dict(),
    }

@mcp_tool
def perform_interaction_impl(
    interaction_type: str,
    initiator_id: str,
    target_id: str,
    scene_id: str = "bedroom",
    subtype: str = "",
    intensity: int = 0,
) -> Dict[str, Any]:
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
        return result

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

    return {
        "interaction": result,
        "stat_effects_applied": result["stat_effects"],
        "initiator_new_stats": new_stats,
        "initiator_emotional_state": _ssm().get_stats(initiator_id).emotional_state_text(),
        "timed_action_token": action_token,
        "narrative_fragment": opening,
    }

@mcp_tool
def list_available_interactions_impl(character_id: str, scene_id: str = "bedroom") -> Dict[str, Any]:
    it = _itrees()
    stats = _ssm().get_stats(character_id).to_dict()
    available = it.get_available_interactions(stats, scene=scene_id)
    all_types = it.list_interaction_types(scene=scene_id)
    return {
        "character_id": character_id,
        "emotional_state": _ssm().get_stats(character_id).emotional_state_text(),
        "available_now": available,
        "all_types": all_types,
    }

@mcp_tool
def get_interaction_details_impl(
    interaction_type: str,
    subtype: str = "",
    scene_id: str = "bedroom",
) -> Dict[str, Any]:
    it = _itrees()
    trees = it.BEDROOM_INTERACTIONS if scene_id == "bedroom" else it.PHONE_INTERACTIONS
    itype = trees.get(interaction_type)
    if not itype:
        return {"error": f"Unknown type '{interaction_type}'"}
    if subtype:
        sub = itype.get_subtype(subtype)
        if not sub:
            return {"error": f"Unknown subtype '{subtype}'"}
        import dataclasses
        return dataclasses.asdict(sub)
    # Return overview of all subtypes
    return {
        "type": itype.id,
        "label": itype.label,
        "description": itype.description,
        "subtypes": [
            {
                "id": s.id,
                "label": s.label,
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
    }

# ── Timed Actions ─────────────────────────────────────────────────────

@mcp_tool
def start_timed_action_impl(
    character_id: str,
    action_type: str,
    duration_secs: float = 30.0,
    description: str = "",
    phases: str = "",
) -> Dict[str, Any]:
    phase_list = [p.strip() for p in phases.split(",") if p.strip()] if phases else []
    token = _ssm().start_timed_action(
        character_id,
        action_type,
        duration=duration_secs,
        description=description,
        phase_labels=phase_list,
    )
    return {
        "started": True,
        "token": token,
        "character_id": character_id,
        "action_type": action_type,
        "duration_secs": duration_secs,
        "description": description,
        "message": f"Use poll_timed_action('{token}') to check progress.",
    }

@mcp_tool
def poll_timed_action_impl(token: str) -> Dict[str, Any]:
    status = _ssm().poll_timed_action(token)
    if not status:
        return {"error": f"No action found with token '{token}'"}
    return status

@mcp_tool
def abort_timed_action_impl(token: str) -> Dict[str, Any]:
    ok = _ssm().abort_timed_action(token)
    return {"aborted": ok, "token": token}

@mcp_tool
def list_active_timed_actions_impl(character_id: str = "") -> Dict[str, Any]:
    actions = _ssm().active_timed_actions(character_id=character_id or None)
    return {"active_actions": actions, "count": len(actions)}

# ── Consent & Agency ─────────────────────────────────────────────────

@mcp_tool
def check_character_consent_impl(character_id: str, action_type: str) -> Dict[str, Any]:
    stats = _ssm().get_stats(character_id).to_dict()
    openness = float(stats.get("openness", 65))
    arousal = float(stats.get("arousal", 20))
    fear = float(stats.get("fear", 5))
    anger = float(stats.get("anger", 5))
    happiness = float(stats.get("happiness", 60))
    affection = float(stats.get("affection", 50))

    intimacy_map = {
        "cuddle": 20, "kiss": 30, "caress": 35,
   
