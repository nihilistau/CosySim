"""
Pure business-logic functions for scene-related MCP tools.

Each function mirrors the corresponding ``@mcp.tool()`` or
``@mcp.resource()`` in ``cosysim_server.py`` but accepts its
dependencies as explicit parameters so the module stays free of
MCP/FastMCP imports.
"""

from __future__ import annotations

import json
import socket
from typing import Any, Dict, List, Optional
import logging
from pydantic import BaseModel, Field
from engine.mcp.decorators import mcp_tool, ToolExecutionError

logger = logging.getLogger(__name__)


# ── Domain Models ────────────────────────────────────────────────────


class ActiveGame(BaseModel):
    game_id: str
    state: Dict[str, Any]


class SystemMonitorDict(BaseModel):
    cpu_pct: Optional[float]
    gpu_vram_used_mb: Optional[float]
    loaded_model: str


class SceneContextResponse(BaseModel):
    scene: str
    active_games: List[ActiveGame]
    system: SystemMonitorDict


class AtmosphereResponse(BaseModel):
    set: bool
    atmosphere: Dict[str, Any]
    scene_id: str


class SceneNarrativeResponse(BaseModel):
    scene_id: str
    entry_count: int
    narrative_text: str
    entries: List[Dict[str, Any]]


class SceneActionsResponse(BaseModel):
    scene: str
    character: str
    actions: Any


class ResourceSceneStatusResponse(BaseModel):
    scene: str
    status: str
    error: Optional[str] = None
    port: Optional[int] = None
    url: Optional[str] = None


# ── helpers ────────────────────────────────────────────────────────────


def _ssm():
    from engine.mcp.scene_state import get_scene_state_manager

    return get_scene_state_manager()


# ── Scene context / atmosphere ─────────────────────────────────────────


@mcp_tool
def get_scene_context(scene: str = "phone") -> SceneContextResponse:
    """Active games, system health, and other scene context."""
    from engine.mcp.comms_framework import get_game_state as _gs
    from engine.logging.monitor import get_system_monitor

    mon = get_system_monitor()

    active_games: List[ActiveGame] = []
    _gstate = _gs()
    for gid in _gstate.all_games():
        if _gstate.get(gid, "active") and _gstate.get(gid, "scene") == scene:
            active_games.append(ActiveGame(game_id=gid, state=_gstate.get_all(gid)))

    system_info = SystemMonitorDict(
        cpu_pct=mon.snapshot().get("cpu_percent"),
        gpu_vram_used_mb=mon.snapshot().get("gpu_vram_used_mb"),
        loaded_model=mon.get_loaded_model() or "none",
    )

    return SceneContextResponse(
        scene=scene, active_games=active_games, system=system_info
    )


@mcp_tool
def set_scene_atmosphere(
    scene_id: str,
    *,
    lighting: str = "",
    mood: str = "",
    music: str = "",
    temperature: str = "",
    props_present: str = "",
    note: str = "",
) -> AtmosphereResponse:
    """Set the atmosphere of a scene and log to narrative."""
    ssm = _ssm()
    atm: dict = {}
    if lighting:
        atm["lighting"] = lighting
    if mood:
        atm["mood"] = mood
    if music:
        atm["music"] = music
    if temperature:
        atm["temperature"] = temperature
    if props_present:
        atm["props_present"] = [p.strip() for p in props_present.split(",")]
    if note:
        atm["note"] = note
    ssm.set_atmosphere(scene_id, **atm)
    if atm:
        desc_parts: List[str] = []
        if lighting:
            desc_parts.append(f"{lighting} lighting")
        if mood:
            desc_parts.append(f"{mood} mood")
        if music:
            desc_parts.append(f"{music} playing")
        if note:
            desc_parts.append(note)
        ssm.add_narrative(
            scene_id,
            "Atmosphere: " + ", ".join(desc_parts) + ".",
            entry_type="environment",
        )
    return AtmosphereResponse(set=True, atmosphere=atm, scene_id=scene_id)


# ── Narrative / continuity ─────────────────────────────────────────────


@mcp_tool
def add_scene_narrative(
    scene_id: str,
    event: str,
    character_id: str = "",
    entry_type: str = "action",
) -> Dict[str, Any]:
    """Add an event to the scene's rolling narrative log."""
    _ssm().add_narrative(
        scene_id, event, character_id=character_id, entry_type=entry_type
    )
    return {"logged": True, "event": event, "scene_id": scene_id}


@mcp_tool
def get_scene_narrative(scene_id: str, limit: int = 20) -> SceneNarrativeResponse:
    """Read the last *limit* entries from the scene narrative log."""
    ssm = _ssm()
    entries = ssm.get_narrative_entries(scene_id, limit=limit)
    text = ssm.get_narrative(scene_id, limit=limit)
    return SceneNarrativeResponse(
        scene_id=scene_id,
        entry_count=len(entries),
        narrative_text=text,
        entries=entries,
    )


@mcp_tool
def get_full_scene_snapshot(scene_id: str, character_ids: str = "") -> Dict[str, Any]:
    """Complete snapshot: stats, wardrobes, emotions, atmosphere, narrative."""
    char_list = (
        [c.strip() for c in character_ids.split(",") if c.strip()]
        if character_ids
        else None
    )
    snapshot = _ssm().get_scene_snapshot(scene_id, character_ids=char_list)
    return snapshot


# ── Scene rules engine ─────────────────────────────────────────────────


@mcp_tool
def get_scene_rules(scene_id: str) -> str:
    """Return the full rules reference for a scene in human-readable form."""
    from engine.mcp.scene_rules_engine import get_rules_engine

    return get_rules_engine().get_rules_text(scene_id)


@mcp_tool
def get_scene_available_actions(
    scene_id: str,
    character_id: str,
    stats_json: str = "{}",
    scene_state_json: str = "{}",
) -> SceneActionsResponse:
    """Actions available to *character_id* in *scene_id* right now."""
    from engine.mcp.scene_rules_engine import get_rules_engine

    stats = json.loads(stats_json) if stats_json else {}
    scene_state = json.loads(scene_state_json) if scene_state_json else {}
    actions = get_rules_engine().get_available_actions(
        scene_id,
        character_id,
        stats=stats,
        scene_state=scene_state,
    )
    return SceneActionsResponse(scene=scene_id, character=character_id, actions=actions)


@mcp_tool
def apply_scene_rule(
    scene_id: str,
    rule_id: str,
    target_ids_json: str = "[]",
    issuer: str = "director",
) -> Dict[str, Any]:
    """Apply a named Director rule immediately."""
    from engine.mcp.scene_rules_engine import get_rules_engine

    targets = json.loads(target_ids_json) if target_ids_json else []
    result = get_rules_engine().apply_rule(
        scene_id,
        rule_id,
        target_ids=targets or None,
        issuer=issuer,
    )
    return result


# ── Scene broadcast ────────────────────────────────────────────────────


@mcp_tool
def scene_broadcast(
    scene_id: str,
    event_type: str,
    payload_json: str = "{}",
    target_characters_json: str = "[]",
) -> Dict[str, Any]:
    """Push a named event to all characters in a scene."""
    payload = json.loads(payload_json) if payload_json else {}
    targets = json.loads(target_characters_json) if target_characters_json else []

    applied: Dict[str, Any] = {
        "event_type": event_type,
        "scene_id": scene_id,
        "applied": [],
    }

    desc = payload.get("description", f"Scene event: {event_type}")
    try:
        ssm = _ssm()
        ssm.add_narrative(scene_id, desc, entry_type="environment")
        applied["narrative"] = desc
    except Exception:
        logger.debug("Suppressed exception", exc_info=True)

    stat_effects: Dict[str, Dict] = payload.get("stat_effects", {})
    for char_id, effects in stat_effects.items():
        if targets and char_id not in targets:
            continue
        try:
            ssm = _ssm()
            ssm.update_stats(char_id, **effects)
            applied["applied"].append({"char": char_id, "stats": effects})
        except Exception as se:
            applied["applied"].append({"char": char_id, "error": str(se)})

    directive_info = payload.get("directive")
    if directive_info and targets:
        try:
            from engine.mcp.dialog_system import get_dialog_system

            ds = get_dialog_system()
            for char_id in targets:
                ds.set_directive(
                    char_id,
                    scene_id,
                    directive_type=directive_info.get("type", "topic_steer"),
                    value=directive_info.get("value", ""),
                    turns=directive_info.get("turns", 1),
                    issued_by="scene_broadcast",
                )
            applied["directive_issued_to"] = targets
        except Exception as de:
            applied["directive_error"] = str(de)

    return applied


# ── Scene rules summary ───────────────────────────────────────────────


@mcp_tool
def get_scene_rules_summary(scene_id: str, character_id: str = "") -> Dict[str, Any]:
    """Complete scene rules + actions + character capabilities in one call."""
    result: Dict[str, Any] = {"scene_id": scene_id, "character_id": character_id}

    # Scene rules and actions
    try:
        from engine.mcp.scene_rules_engine import get_rules_engine

        eng = get_rules_engine()
        result["rules_text"] = eng.get_rules_text(scene_id)
        if character_id:
            result["available_actions"] = eng.get_available_actions(
                scene_id, character_id
            )
    except Exception as re:
        result["rules_error"] = str(re)

    # Character skills
    if character_id:
        try:
            from engine.mcp.character_registry import get_character_registry

            reg = get_character_registry()
            reg.ensure(character_id)
            skills = reg.get_skills(character_id)
            result["character_skills"] = [
                {"id": s.skill_id, "label": s.label, "trigger": s.trigger}
                for s in skills
            ]
            result["character_summary"] = reg.get_character_summary(character_id)
        except Exception as ce:
            result["character_error"] = str(ce)

    # Conversation heat + directive
    if character_id:
        try:
            from engine.mcp.dialog_system import get_dialog_system

            ds = get_dialog_system()
            result["conversation_heat"] = ds.get_conversation_heat(
                character_id, scene_id
            )
            result["active_directive"] = ds.get_active_directive(character_id, scene_id)
            result["recent_topics"] = ds.get_recent_topics(character_id, scene_id)
        except Exception as de:
            result["dialog_error"] = str(de)

    return result


# ── Scene resource (status) ────────────────────────────────────────────


@mcp_tool
def resource_scene_status(scene_name: str) -> ResourceSceneStatusResponse:
    """Scene health status and connection info."""
    from engine.config import get_config

    config = get_config()
    port = int(config.get(f"scenes.{scene_name}.port", 0))
    if not port:
        known = {"phone": 5555, "bedroom": 5556, "hub": 8500, "admin": 8502}
        port = known.get(scene_name, 0)
    if not port:
        return ResourceSceneStatusResponse(
            scene=scene_name, status="unknown", error="No port configured"
        )

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            running = True
    except OSError:
        running = False

    return ResourceSceneStatusResponse(
        scene=scene_name,
        port=port,
        status="running" if running else "stopped",
        url=f"http://localhost:{port}",
    )

class ResolveSceneEventResponse(BaseModel):
    scene_id: str
    event: str
    effects: Dict[str, int]

@mcp_tool
def resolve_random_scene_event_impl(scene_id: str, ssm: Any) -> ResolveSceneEventResponse:
    """Generate a random scene event to keep things fresh."""
    import random
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
        ssm.add_narrative(
            scene_id,
            f"[SCENE EVENT]: {evt['event']}",
            entry_type="system",
        )
    except Exception:
        pass

    return ResolveSceneEventResponse(
        scene_id=scene_id,
        event=evt["event"],
        effects=evt["effects"]
    )

class GetMySkillsResponse(BaseModel):
    scene: str
    auto_skills: List[Dict[str, str]]
    optional_skills: List[Dict[str, str]]
    required_skills: List[Dict[str, str]]

@mcp_tool
def get_my_skills_impl(scene: str, manifest_getter: Any) -> GetMySkillsResponse:
    manifest = manifest_getter.get(scene)
    return GetMySkillsResponse(
        scene=scene,
        auto_skills=[{"name": s.name, "description": s.description} for s in manifest.auto_skills()],
        optional_skills=[{"name": s.name, "description": s.description} for s in manifest.optional_skills()],
        required_skills=[{"name": s.name, "description": s.description} for s in manifest.required_skills()],
    )

class AllToolsResponse(BaseModel):
    scene_id: str
    tools: List[str]

@mcp_tool
def get_all_tools_for_scene_impl(scene_id: str) -> AllToolsResponse:
    # Just a static mapping for now, mirroring the original logic
    bedroom_tools = [
        "wardrobe_get", "wardrobe_init", "wardrobe_remove_item",
        "wardrobe_remove_outermost", "wardrobe_add_item", "wardrobe_redress",
        "get_character_scene_stats", "update_character_scene_stats",
        "set_character_scene_stat", "reset_character_scene_stats",
        "perform_interaction", "list_available_interactions",
        "get_interaction_details", "start_timed_action", "poll_timed_action",
        "abort_timed_action", "list_active_timed_actions", "add_scene_narrative",
        "get_scene_narrative", "get_full_scene_snapshot", "set_scene_atmosphere",
        "check_character_consent", "get_character_agency_summary",
    ]
    if scene_id == "bedroom":
        return AllToolsResponse(scene_id=scene_id, tools=bedroom_tools)
    return AllToolsResponse(scene_id=scene_id, tools=[])
