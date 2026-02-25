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


# ── helpers ────────────────────────────────────────────────────────────

def _ssm():
    from engine.mcp.scene_state import get_scene_state_manager
    return get_scene_state_manager()


# ── Scene context / atmosphere ─────────────────────────────────────────

def get_scene_context(scene: str = "phone") -> str:
    """Active games, system health, and other scene context."""
    try:
        from engine.mcp.comms_framework import get_game_state as _gs
        from engine.logging.monitor import get_system_monitor
        mon = get_system_monitor()

        active_games: List[Dict[str, Any]] = []
        _gstate = _gs()
        for gid in _gstate.all_games():
            if _gstate.get(gid, "active") and _gstate.get(gid, "scene") == scene:
                active_games.append({"game_id": gid, "state": _gstate.get_all(gid)})

        return json.dumps({
            "scene": scene,
            "active_games": active_games,
            "system": {
                "cpu_pct":          mon.snapshot().get("cpu_percent"),
                "gpu_vram_used_mb": mon.snapshot().get("gpu_vram_used_mb"),
                "loaded_model":     mon.get_loaded_model(),
            },
        }, indent=2, default=str)
    except Exception as e:
        return f"Failed to get scene context: {e}"


def set_scene_atmosphere(
    scene_id: str,
    *,
    lighting: str = "",
    mood: str = "",
    music: str = "",
    temperature: str = "",
    props_present: str = "",
    note: str = "",
) -> str:
    """Set the atmosphere of a scene and log to narrative."""
    ssm = _ssm()
    atm: dict = {}
    if lighting:      atm["lighting"]      = lighting
    if mood:          atm["mood"]          = mood
    if music:         atm["music"]         = music
    if temperature:   atm["temperature"]   = temperature
    if props_present: atm["props_present"] = [p.strip() for p in props_present.split(",")]
    if note:          atm["note"]          = note
    ssm.set_atmosphere(scene_id, **atm)
    if atm:
        desc_parts: List[str] = []
        if lighting: desc_parts.append(f"{lighting} lighting")
        if mood:     desc_parts.append(f"{mood} mood")
        if music:    desc_parts.append(f"{music} playing")
        if note:     desc_parts.append(note)
        ssm.add_narrative(scene_id, "Atmosphere: " + ", ".join(desc_parts) + ".", entry_type="environment")
    return json.dumps({"set": True, "atmosphere": atm, "scene_id": scene_id}, indent=2)


# ── Narrative / continuity ─────────────────────────────────────────────

def add_scene_narrative(
    scene_id: str,
    event: str,
    character_id: str = "",
    entry_type: str = "action",
) -> str:
    """Add an event to the scene's rolling narrative log."""
    _ssm().add_narrative(scene_id, event, character_id=character_id, entry_type=entry_type)
    return json.dumps({"logged": True, "event": event, "scene_id": scene_id})


def get_scene_narrative(scene_id: str, limit: int = 20) -> str:
    """Read the last *limit* entries from the scene narrative log."""
    ssm = _ssm()
    entries = ssm.get_narrative_entries(scene_id, limit=limit)
    text    = ssm.get_narrative(scene_id, limit=limit)
    return json.dumps({
        "scene_id":       scene_id,
        "entry_count":    len(entries),
        "narrative_text": text,
        "entries":        entries,
    }, indent=2)


def get_full_scene_snapshot(scene_id: str, character_ids: str = "") -> str:
    """Complete snapshot: stats, wardrobes, emotions, atmosphere, narrative."""
    char_list = (
        [c.strip() for c in character_ids.split(",") if c.strip()]
        if character_ids else None
    )
    snapshot = _ssm().get_scene_snapshot(scene_id, character_ids=char_list)
    return json.dumps(snapshot, indent=2)


# ── Scene rules engine ─────────────────────────────────────────────────

def get_scene_rules(scene_id: str) -> str:
    """Return the full rules reference for a scene in human-readable form."""
    try:
        from engine.mcp.scene_rules_engine import get_rules_engine
        return get_rules_engine().get_rules_text(scene_id)
    except Exception as exc:
        return f"Error: {exc}"


def get_scene_available_actions(
    scene_id: str,
    character_id: str,
    stats_json: str = "{}",
    scene_state_json: str = "{}",
) -> str:
    """Actions available to *character_id* in *scene_id* right now."""
    try:
        from engine.mcp.scene_rules_engine import get_rules_engine
        stats       = json.loads(stats_json)       if stats_json       else {}
        scene_state = json.loads(scene_state_json) if scene_state_json else {}
        actions = get_rules_engine().get_available_actions(
            scene_id, character_id, stats=stats, scene_state=scene_state,
        )
        return json.dumps({"scene": scene_id, "character": character_id, "actions": actions}, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def apply_scene_rule(
    scene_id: str,
    rule_id: str,
    target_ids_json: str = "[]",
    issuer: str = "director",
) -> str:
    """Apply a named Director rule immediately."""
    try:
        from engine.mcp.scene_rules_engine import get_rules_engine
        targets = json.loads(target_ids_json) if target_ids_json else []
        result = get_rules_engine().apply_rule(
            scene_id, rule_id, target_ids=targets or None, issuer=issuer,
        )
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ── Scene broadcast ────────────────────────────────────────────────────

def scene_broadcast(
    scene_id: str,
    event_type: str,
    payload_json: str = "{}",
    target_characters_json: str = "[]",
) -> str:
    """Push a named event to all characters in a scene."""
    try:
        payload = json.loads(payload_json)   if payload_json   else {}
        targets = json.loads(target_characters_json) if target_characters_json else []

        applied: Dict[str, Any] = {"event_type": event_type, "scene_id": scene_id, "applied": []}

        desc = payload.get("description", f"Scene event: {event_type}")
        try:
            ssm = _ssm()
            ssm.add_narrative(scene_id, desc, entry_type="environment")
            applied["narrative"] = desc
        except Exception:
            pass

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
                        char_id, scene_id,
                        directive_type=directive_info.get("type", "topic_steer"),
                        value=directive_info.get("value", ""),
                        turns=directive_info.get("turns", 1),
                        issued_by="scene_broadcast",
                    )
                applied["directive_issued_to"] = targets
            except Exception as de:
                applied["directive_error"] = str(de)

        return json.dumps(applied, indent=2)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ── Scene rules summary ───────────────────────────────────────────────

def get_scene_rules_summary(scene_id: str, character_id: str = "") -> str:
    """Complete scene rules + actions + character capabilities in one call."""
    try:
        result: Dict[str, Any] = {"scene_id": scene_id, "character_id": character_id}

        # Scene rules and actions
        try:
            from engine.mcp.scene_rules_engine import get_rules_engine
            eng = get_rules_engine()
            result["rules_text"] = eng.get_rules_text(scene_id)
            if character_id:
                result["available_actions"] = eng.get_available_actions(scene_id, character_id)
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
                result["conversation_heat"] = ds.get_conversation_heat(character_id, scene_id)
                result["active_directive"]  = ds.get_active_directive(character_id, scene_id)
                result["recent_topics"]     = ds.get_recent_topics(character_id, scene_id)
            except Exception as de:
                result["dialog_error"] = str(de)

        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── Scene resource (status) ────────────────────────────────────────────

def resource_scene_status(scene_name: str) -> str:
    """Scene health status and connection info."""
    from engine.config import get_config
    config = get_config()
    port = int(config.get(f"scenes.{scene_name}.port", 0))
    if not port:
        known = {"phone": 5555, "bedroom": 5556, "hub": 8500, "admin": 8502}
        port = known.get(scene_name, 0)
    if not port:
        return json.dumps({"scene": scene_name, "status": "unknown", "error": "No port configured"})

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            running = True
    except OSError:
        running = False

    return json.dumps({
        "scene": scene_name,
        "port": port,
        "status": "running" if running else "stopped",
        "url": f"http://localhost:{port}",
    }, indent=2)
