"""Canonical control-plane target definitions for launcher-driven services and scenes."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_CONFIG_PATH = PROJECT_ROOT / "config" / "launcher.yaml"


# ──── Canonical launcher target definitions ──────────────────────────────────

SERVICE_DEFS: Dict[str, Dict[str, Any]] = {
    "hub": {
        "type": "flask",
        "cls": "content.scenes.hub.hub_flask.HubScene",
        "label": "CosySim Hub",
        "auto_start": True,
    },
    "nexus_panel": {
        "type": "flask",
        "cls": "content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene",
        "label": "Nexus Control Panel",
        "auto_start": True,
    },
    "dashboard": {
        "type": "streamlit",
        "script": "content/scenes/dashboard/dashboard_v2.py",
        "label": "System Dashboard",
        "auto_start": False,
    },
    "admin": {
        "type": "streamlit",
        "script": "content/scenes/admin/admin_panel.py",
        "label": "Admin Panel",
        "auto_start": False,
    },
    "assets": {
        "type": "streamlit",
        "script": "content/scenes/assets/asset_generator.py",
        "label": "Asset Generator",
        "auto_start": False,
    },
    "creator": {
        "type": "streamlit",
        "script": "content/scenes/hub/scene_creator.py",
        "label": "Scene Creator",
        "auto_start": False,
    },
    "tts": {
        "type": "fastapi",
        "factory": "engine.tts.qwen3_server.create_tts_app",
        "label": "TTS Server",
        "auto_start": False,
    },
    "bridge": {
        "type": "fastapi",
        "factory": "engine.mcp.web_bridge.create_bridge_app",
        "label": "MCP Bridge",
        "auto_start": False,
    },
    "canvas": {
        "type": "node",
        "script": "content/apps/notebook_canvas",
        "label": "Nexus Canvas",
        "auto_start": True,
    },
    "canvas_api": {
        "type": "fastapi",
        "factory": "engine.api.canvas_api.create_app",
        "label": "Canvas API",
        "auto_start": True,
    },
    "nlm_proxy": {
        "type": "flask",
        "cls": "engine.mcp.nlm_live_proxy.NLMProxyServer",
        "label": "NLM Live Proxy",
        "auto_start": False,
    },
    "system_control": {
        "type": "flask",
        "cls": "content.scenes.system_control.system_control_scene.SystemControlScene",
        "label": "System Control Panel",
        "auto_start": True,
    },
}

SCENE_DEFS: Dict[str, Dict[str, Any]] = {
    "phone": {
        "type": "flask",
        "cls": "content.scenes.phone.phone_scene_v2.PhoneSceneV2",
        "label": "SIGNAL",
        "auto_start": True,
    },
    "bedroom": {
        "type": "flask",
        "cls": "content.scenes.bedroom.bedroom_scene.BedroomScene",
        "label": "THE PENTHOUSE",
        "auto_start": True,
    },
    "lounge": {
        "type": "flask",
        "cls": "content.scenes.lounge.lounge_scene.LoungeScene",
        "label": "THE VELVET PIT",
        "auto_start": False,
    },
    "tavern": {
        "type": "flask",
        "cls": "content.scenes.tavern.tavern_scene.TavernScene",
        "label": "THE RUSTY ANCHOR",
        "auto_start": False,
    },
    "casino": {
        "type": "flask",
        "cls": "content.scenes.casino.casino_scene.CasinoScene",
        "label": "CLUB NOIR",
        "auto_start": False,
    },
    "gallery": {
        "type": "flask",
        "cls": "content.scenes.gallery.gallery_scene.GalleryScene",
        "label": "THE OBSCURA",
        "auto_start": False,
    },
    "arena": {
        "type": "flask",
        "cls": "content.scenes.arena.ArenaScene",
        "label": "THE COLOSSEUM",
        "auto_start": False,
    },
    "realm": {
        "type": "flask",
        "cls": "content.scenes.realm.realm_scene.RealmScene",
        "label": "THE SHATTERED THRONE",
        "auto_start": False,
    },
    "neoncity": {
        "type": "flask",
        "cls": "content.scenes.neoncity.neoncity_scene.NeonCityScene",
        "label": "NEON CITY",
        "auto_start": False,
    },
    "coders": {
        "type": "flask",
        "cls": "content.scenes.coders.coders_scene.CodersRoomScene",
        "label": "THE LAB",
        "auto_start": False,
    },
    "heist": {
        "type": "flask",
        "cls": "content.scenes.heist.heist_scene.HeistScene",
        "label": "THE SCORE",
        "auto_start": False,
    },
    "command_center": {
        "type": "flask",
        "cls": "content.scenes.command_center.command_center_scene.CommandCenterScene",
        "label": "Command Center",
        "auto_start": False,
    },
    "games": {
        "type": "flask",
        "cls": "content.scenes.games.games_scene.GamesScene",
        "label": "THE ARCADE",
        "auto_start": False,
    },
    "grid": {
        "type": "flask",
        "cls": "content.scenes.grid.grid_scene.GridScene",
        "label": "THE GRID",
        "auto_start": False,
    },
    "intel_hub": {
        "type": "flask",
        "cls": "content.scenes.intel_hub.intel_hub_scene.IntelHubScene",
        "label": "THE BRIEFING ROOM",
        "auto_start": False,
    },
    "asset_studio": {
        "type": "flask",
        "cls": "content.scenes.asset_studio.asset_studio_scene.AssetStudioScene",
        "label": "ASSET STUDIO",
        "auto_start": False,
    },
}

SERVICE_IDS: Tuple[str, ...] = tuple(SERVICE_DEFS.keys())
SCENE_IDS: Tuple[str, ...] = tuple(SCENE_DEFS.keys())


def _copy_catalogue(entries: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Return a shallow copy of a launcher catalogue definition map."""
    return {target_id: dict(info) for target_id, info in entries.items()}


def _apply_launcher_overrides(
    services: Dict[str, Dict[str, Any]],
    scenes: Dict[str, Dict[str, Any]],
) -> None:
    """Apply launcher.yaml auto-start overrides to generated catalogues."""
    if not LAUNCHER_CONFIG_PATH.exists():
        return

    try:
        import yaml
    except ImportError:
        logger.debug("PyYAML unavailable; skipping launcher override load")
        return

    try:
        with LAUNCHER_CONFIG_PATH.open(encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
    except Exception:
        logger.warning("Failed to read %s", LAUNCHER_CONFIG_PATH, exc_info=True)
        return

    for group_name, catalogue in (("services", services), ("scenes", scenes)):
        for target_id, settings in (config.get(group_name) or {}).items():
            if target_id in catalogue and isinstance(settings, dict) and "auto_start" in settings:
                catalogue[target_id]["auto_start"] = bool(settings["auto_start"])


def get_launcher_catalogue_templates() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Return uncoupled launcher catalogue templates without resolved ports."""
    return {
        "services": _copy_catalogue(SERVICE_DEFS),
        "scenes": _copy_catalogue(SCENE_DEFS),
    }


def get_target_metadata_catalogue() -> Dict[str, Dict[str, Any]]:
    """Return control-plane metadata shared by launcher and port registry."""
    metadata: Dict[str, Dict[str, Any]] = {}
    for group, catalogue in (("service", SERVICE_DEFS), ("scene", SCENE_DEFS)):
        for target_id, info in catalogue.items():
            metadata[target_id] = {
                "id": target_id,
                "group": group,
                "label": info["label"],
                "type": info["type"],
                "auto_start": bool(info.get("auto_start")),
            }
    return metadata


def build_launcher_catalogues(
    port_resolver: Callable[[str], int],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Build launcher-ready catalogues with resolved ports and config overrides."""
    services = _copy_catalogue(SERVICE_DEFS)
    scenes = _copy_catalogue(SCENE_DEFS)

    for catalogue in (services, scenes):
        for target_id, info in catalogue.items():
            info["port"] = int(port_resolver(target_id))

    _apply_launcher_overrides(services, scenes)
    return services, scenes, {**services, **scenes}
