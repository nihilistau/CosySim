"""THE TERMINAL — hub skills. v0.68 Dark Renaissance.

System-level skills for querying scene status and world state from the hub.
Registered automatically when the hub package is imported.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from engine.port_registry import ALL_SCENE_TARGETS, build_target_listing
from engine.skills.skill import skill
from engine.utils import port_is_open

logger = logging.getLogger(__name__)


# ── Scene catalogue (built from canonical registry for standalone skill use) ─
_SCENE_PORTS: List[Dict[str, Any]] = [
    {"id": target["id"], "port": target["port"], "label": target["label"]}
    for target in build_target_listing(ALL_SCENE_TARGETS)
]


# ── Skills ───────────────────────────────────────────────────────────


@skill(
    pack="hub",
    description="Get the live online/offline status of all CosySim scenes.",
    category="system",
    tags=["hub", "system", "scenes", "status"],
)
def get_all_scenes_status() -> str:
    """Check each known scene port and return a structured status report.

    Returns:
        JSON string with scene id, label, port, and online status.
        Includes a summary count of online vs total scenes.
    """
    results: List[Dict[str, Any]] = []
    online_count = 0

    for s in _SCENE_PORTS:
        is_online = port_is_open(s["port"])
        if is_online:
            online_count += 1
        results.append({
            "id": s["id"],
            "label": s["label"],
            "port": s["port"],
            "status": "online" if is_online else "offline",
        })

    payload = {
        "summary": f"{online_count}/{len(_SCENE_PORTS)} scenes online",
        "online": online_count,
        "total": len(_SCENE_PORTS),
        "scenes": results,
    }
    return json.dumps(payload, indent=2)


@skill(
    pack="hub",
    description="Get the current CosySim world state: game time, active world events, and NPC availability.",
    category="system",
    tags=["hub", "system", "world", "time", "events"],
)
def get_world_status() -> str:
    """Query the WorldState singleton and return a summary of the living world.

    Returns:
        JSON string with current game time, active events, weather per scene,
        and NPC availability map. Falls back gracefully if WorldState is
        unavailable (e.g. during unit tests).
    """
    try:
        from engine.world.world_state import get_world_state

        ws = get_world_state()
        summary = ws.get_world_summary()

        wt = summary.get("time", {})
        hour = wt.get("hour", 0)
        cycle = "NIGHT CYCLE" if (hour >= 20 or hour < 6) else "DAY CYCLE"
        time_str = f"{cycle} {hour:02d}:{wt.get('minute', 0):02d}"

        active_events = summary.get("active_events", [])
        event_names = [e.get("name", str(e)) for e in active_events[:5]]

        payload = {
            "time": time_str,
            "hour": hour,
            "day": wt.get("day", 0),
            "day_name": wt.get("day_name", ""),
            "cycle": cycle,
            "active_events": event_names,
            "event_count": len(active_events),
            "weather": summary.get("weather", {}),
            "npc_availability": summary.get("npc_availability", {}),
        }
        return json.dumps(payload, indent=2)

    except Exception as exc:
        logger.warning("get_world_status: WorldState unavailable — %s", exc)
        return json.dumps({
            "time": "UNKNOWN",
            "active_events": [],
            "error": str(exc),
        })
