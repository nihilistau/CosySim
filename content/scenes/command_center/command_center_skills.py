"""
Command Center MCP Skills — Remote scene monitoring and control via tool calls.

Skills:
    cc_scene_list       — List all active scenes with status
    cc_scene_status     — Get detailed status for a specific scene
    cc_scene_feed       — Get recent chat messages from a scene
    cc_character_status — Get detailed character state
    cc_inject_event     — Inject a narrative event into a scene
    cc_system_status    — Get system resource metrics
"""

from engine.skills.skill import skill


def _get_cc_scene():
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("command_center")


@skill(pack="command_center", tags=["monitoring", "scenes"], cooldown=2)
def cc_scene_list() -> str:
    """List all active scenes with their current status, character count, and phase."""
    from engine.scenes.base_scene import get_all_active_scenes

    scenes = get_all_active_scenes()
    if not scenes:
        return "No active scenes."

    cc = _get_cc_scene()
    lines = ["=== Active Scenes ==="]
    for sid, sobj in sorted(scenes.items()):
        if sid == "command_center":
            continue
        if cc:
            try:
                summary = cc._get_scene_summary(sid, sobj)
                phase = summary.get("state", {}).get("phase", "-")
                heat = summary.get("heat", "-")
                chars = summary.get("character_count", 0)
                lines.append(
                    f"  {summary.get('title', sid)} ({sid}) — "
                    f"port:{summary.get('port', '?')} | "
                    f"chars:{chars} | phase:{phase} | heat:{heat}"
                )
                continue
            except Exception:
                pass
        meta = getattr(sobj, "SCENE_METADATA", {})
        lines.append(f"  {meta.get('title', sid)} ({sid}) — port:{getattr(sobj, 'port', '?')}")

    return "\n".join(lines)


@skill(pack="command_center", tags=["monitoring", "scenes"], cooldown=2)
def cc_scene_status(scene_id: str) -> str:
    """Get detailed status for a specific scene including state, characters, and heat."""
    from engine.scenes.base_scene import get_active_scene

    scene = get_active_scene(scene_id)
    if not scene:
        return f"Scene '{scene_id}' is not active."

    cc = _get_cc_scene()
    if not cc:
        return f"Scene '{scene_id}' is active on port {getattr(scene, 'port', '?')}."

    summary = cc._get_scene_summary(scene_id, scene)
    lines = [f"=== {summary.get('title', scene_id)} ==="]
    lines.append(f"Port: {summary.get('port', '?')}")
    lines.append(f"Genre: {summary.get('genre', '?')}")
    lines.append(f"Characters: {', '.join(summary.get('characters', [])) or 'none'}")

    state = summary.get("state", {})
    if state:
        lines.append("State:")
        for k, v in state.items():
            lines.append(f"  {k}: {v}")

    if "heat" in summary:
        lines.append(f"Heat: {summary['heat']}")

    return "\n".join(lines)


@skill(pack="command_center", tags=["monitoring", "chat"], cooldown=3)
def cc_scene_feed(scene_id: str, limit: int = 10) -> str:
    """Get recent chat messages from a scene."""
    cc = _get_cc_scene()
    if not cc:
        return "Command Center not active."

    messages = cc._get_scene_chat_feed(scene_id, limit=limit)
    if not messages:
        return f"No recent messages in {scene_id}."

    lines = [f"=== Recent Chat: {scene_id} ==="]
    for msg in messages:
        speaker = msg.get("speaker", "?")
        text = msg.get("text", "")
        lines.append(f"  [{speaker}] {text}")

    return "\n".join(lines)


@skill(pack="command_center", tags=["monitoring", "characters"], cooldown=2)
def cc_character_status(character_id: str) -> str:
    """Get detailed state for a specific character: mood, energy, stats, relationships."""
    cc = _get_cc_scene()
    if not cc:
        return "Command Center not active."

    details = cc._get_character_details(character_id)
    lines = [f"=== Character: {details.get('name', character_id)} ==="]
    lines.append(f"ID: {character_id}")

    if "mood" in details:
        lines.append(f"Mood: {details['mood']}")
    if "energy" in details:
        lines.append(f"Energy: {details['energy']}")
    if "arousal" in details:
        lines.append(f"Arousal: {details['arousal']}")
    if "inhibition" in details:
        lines.append(f"Inhibition: {details['inhibition']}")

    stats = details.get("stats", {})
    if stats:
        lines.append("Stats:")
        for k, v in stats.items():
            lines.append(f"  {k}: {v}")

    rels = details.get("relationships", [])
    if rels:
        lines.append("Relationships:")
        for r in rels:
            lines.append(f"  → {r['target']}: trust={r.get('trust', 0)}, attraction={r.get('attraction', 0)}")

    return "\n".join(lines)


@skill(pack="command_center", tags=["control", "scenes"], cooldown=5)
def cc_inject_event(scene_id: str, content: str, event_type: str = "narrative") -> str:
    """Inject a narrative event or directive into any active scene.
    
    event_type: 'narrative' (story event), 'directive' (dialog instruction), 'broadcast' (system message)
    """
    from engine.scenes.base_scene import get_active_scene
    from engine.mcp.framework import get_framework

    scene = get_active_scene(scene_id)
    if not scene:
        return f"Scene '{scene_id}' is not active."

    fw = get_framework()
    if event_type == "narrative":
        fw.emit_event(scene_id, "director_injection", {
            "text": content, "source": "command_center_skill"
        })
    elif event_type == "directive":
        try:
            from engine.mcp.dialog_system import get_dialog_system
            ds = get_dialog_system()
            ds.add_directive(scene_id, content, priority=10, ttl=60)
        except Exception as exc:
            return f"Failed to add directive: {exc}"
    elif event_type == "broadcast":
        fw.emit_event(scene_id, "system_broadcast", {
            "text": content, "source": "command_center_skill"
        })
    else:
        return f"Unknown event type: {event_type}. Use 'narrative', 'directive', or 'broadcast'."

    return f"Injected {event_type} into {scene_id}: {content[:80]}"


@skill(pack="command_center", tags=["monitoring", "system"], cooldown=2)
def cc_system_status() -> str:
    """Get current system resource metrics: CPU, RAM, GPU, LMStudio status."""
    try:
        from engine.logging.monitor import get_system_monitor
        mon = get_system_monitor()
        snap = mon.snapshot() if mon else {}
    except Exception:
        snap = {}

    if not snap:
        return "System monitor unavailable."

    cpu = snap.get("cpu_pct", snap.get("cpu", "?"))
    ram = snap.get("ram_pct", "?")
    if isinstance(snap.get("ram"), dict):
        ram = snap["ram"].get("percent", "?")
    gpu_vram = snap.get("gpu_vram_pct", "?")
    if isinstance(snap.get("gpu"), dict):
        gpu_vram = snap["gpu"].get("vram_pct", "?")
    gpu_temp = snap.get("gpu_temp_c", "?")
    if isinstance(snap.get("gpu"), dict):
        gpu_temp = snap["gpu"].get("temp", gpu_temp)

    lines = [
        "=== System Status ===",
        f"CPU: {cpu}%",
        f"RAM: {ram}%",
        f"GPU VRAM: {gpu_vram}%",
        f"GPU Temp: {gpu_temp}°C",
    ]

    # LMStudio status
    try:
        from engine.lmstudio.resource_manager import get_resource_manager
        rm = get_resource_manager()
        if rm:
            lines.append(f"LMStudio: connected")
            loaded = rm.list_loaded_models() if hasattr(rm, "list_loaded_models") else []
            if loaded:
                lines.append(f"Loaded models: {', '.join(str(m) for m in loaded)}")
    except Exception:
        lines.append("LMStudio: unavailable")

    return "\n".join(lines)
