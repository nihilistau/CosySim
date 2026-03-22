"""
Control Plane Registry
======================

Canonical control-plane target definitions for all launcher-driven services
and scenes in CosySim.  This module is the single source of truth for what
targets exist, their types, labels, pillars, and auto-start preferences.

The launcher, TUI, Hub, and port registry all derive their catalogues from
the ``SERVICE_DEFS`` and ``SCENE_DEFS`` dictionaries defined here.  Runtime
overrides from ``config/launcher.yaml`` are applied via
``_apply_launcher_overrides()``.

Version: v1.42.1 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.42.1 [2026-03-21] â€” Added module header, section dividers, version stamps
    v1.42.0 [2026-03-21] â€” Three-pillar architecture, managed Nexus KMS
    v1.41.0 [2026-03-20] â€” ARGUS deep polish, extended rpcids
    v1.40.0 [2026-03-19] â€” Health check aggregator, service discovery registry
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_CONFIG_PATH = PROJECT_ROOT / "config" / "launcher.yaml"


# â”€â”€â”€â”€ Service Definitions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Launcher-managed services: infrastructure, dashboards, APIs, proxies.
# Each entry defines type, class/script path, display label, auto-start flag,
# and pillar membership (service | game | creation).

# v1.42.1 [2026-03-21] â€” 14 service targets across 3 pillars
SERVICE_DEFS: Dict[str, Dict[str, Any]] = {
    "nexus_kms": {
        "type": "external",
        "label": "Nexus KMS",
        "auto_start": True,
        "pillar": "service",
        "cwd": "C:/Files/Nexus",
        "cmd": ["python", "-m", "nexus", "api"],
        "start_priority": 0,  # must start before everything else
    },
    "hub": {
        "type": "flask",
        "cls": "content.scenes.hub.hub_flask.HubScene",
        "label": "CosySim Hub",
        "auto_start": True,
        "pillar": "service",
    },
    "nexus_panel": {
        "type": "flask",
        "cls": "content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene",
        "label": "Nexus Control Panel",
        "auto_start": True,
        "pillar": "service",
    },
    "dashboard": {
        "type": "streamlit",
        "script": "content/scenes/dashboard/dashboard_v2.py",
        "label": "System Dashboard",
        "auto_start": False,
        "pillar": "service",
    },
    "admin": {
        "type": "streamlit",
        "script": "content/scenes/admin/admin_panel.py",
        "label": "Admin Panel",
        "auto_start": False,
        "pillar": "service",
    },
    "assets": {
        "type": "streamlit",
        "script": "content/scenes/assets/asset_generator.py",
        "label": "Asset Generator",
        "auto_start": False,
        "pillar": "creation",
    },
    "creator": {
        "type": "streamlit",
        "script": "content/scenes/hub/scene_creator.py",
        "label": "Scene Creator",
        "auto_start": False,
        "pillar": "creation",
    },
    "tts": {
        "type": "fastapi",
        "factory": "engine.tts.qwen3_server.create_tts_app",
        "label": "TTS Server",
        "auto_start": False,
        "pillar": "service",
    },
    "bridge": {
        "type": "fastapi",
        "factory": "engine.mcp.web_bridge.create_bridge_app",
        "label": "MCP Bridge",
        "auto_start": True,
        "pillar": "service",
    },
    "canvas": {
        "type": "node",
        "script": "content/apps/notebook_canvas",
        "label": "Nexus Canvas",
        "auto_start": True,
        "pillar": "creation",
    },
    "canvas_api": {
        "type": "fastapi",
        "factory": "engine.api.canvas_api.create_app",
        "label": "Canvas API",
        "auto_start": True,
        "pillar": "creation",
    },
    "nlm_proxy": {
        "type": "flask",
        "cls": "engine.mcp.nlm_live_proxy.NLMProxyServer",
        "label": "NLM Live Proxy",
        "auto_start": True,
        "pillar": "service",
    },
    "system_control": {
        "type": "flask",
        "cls": "content.scenes.system_control.system_control_scene.SystemControlScene",
        "label": "System Control Panel",
        "auto_start": True,
        "pillar": "service",
    },
}

# â”€â”€â”€â”€ Scene Definitions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Interactive game scenes and content scenes.  Each scene is a Flask app with
# Socket.IO, served on its own port (resolved by port_registry at runtime).

# v1.42.1 [2026-03-21] â€” 17 scene targets (15 game, 1 service, 1 creation)
SCENE_DEFS: Dict[str, Dict[str, Any]] = {
    "phone": {
        "type": "flask",
        "cls": "content.scenes.phone.phone_scene_v2.PhoneSceneV2",
        "label": "SIGNAL",
        "auto_start": True,
        "pillar": "game",
    },
    "penthouse": {
        "type": "flask",
        "cls": "content.scenes.penthouse.penthouse_scene.PenthouseScene",
        "label": "THE PENTHOUSE",
        "auto_start": True,
        "pillar": "game",
    },
    "lounge": {
        "type": "flask",
        "cls": "content.scenes.lounge.lounge_scene.LoungeScene",
        "label": "THE VELVET PIT",
        "auto_start": False,
        "pillar": "game",
    },
    "tavern": {
        "type": "flask",
        "cls": "content.scenes.tavern.tavern_scene.TavernScene",
        "label": "THE RUSTY ANCHOR",
        "auto_start": False,
        "pillar": "game",
    },
    "casino": {
        "type": "flask",
        "cls": "content.scenes.casino.casino_scene.CasinoScene",
        "label": "CLUB NOIR",
        "auto_start": False,
        "pillar": "game",
    },
    "gallery": {
        "type": "flask",
        "cls": "content.scenes.gallery.gallery_scene.GalleryScene",
        "label": "THE OBSCURA",
        "auto_start": False,
        "pillar": "game",
    },
    "arena": {
        "type": "flask",
        "cls": "content.scenes.arena.ArenaScene",
        "label": "THE COLOSSEUM",
        "auto_start": False,
        "pillar": "game",
    },
    "realm": {
        "type": "flask",
        "cls": "content.scenes.realm.realm_scene.RealmScene",
        "label": "THE SHATTERED THRONE",
        "auto_start": False,
        "pillar": "game",
    },
    "neoncity": {
        "type": "flask",
        "cls": "content.scenes.neoncity.neoncity_scene.NeonCityScene",
        "label": "NEON CITY",
        "auto_start": True,
        "pillar": "game",
    },
    "coders": {
        "type": "flask",
        "cls": "content.scenes.coders.coders_scene.CodersRoomScene",
        "label": "THE LAB",
        "auto_start": False,
        "pillar": "game",
    },
    "heist": {
        "type": "flask",
        "cls": "content.scenes.heist.heist_scene.HeistScene",
        "label": "THE SCORE",
        "auto_start": False,
        "pillar": "game",
    },
    "command_center": {
        "type": "flask",
        "cls": "content.scenes.command_center.command_center_scene.CommandCenterScene",
        "label": "Command Center",
        "auto_start": False,
        "pillar": "service",
    },
    "games": {
        "type": "flask",
        "cls": "content.scenes.games.games_scene.GamesScene",
        "label": "THE ARCADE",
        "auto_start": False,
        "pillar": "game",
    },
    "grid": {
        "type": "flask",
        "cls": "content.scenes.grid.grid_scene.GridScene",
        "label": "THE GRID",
        "auto_start": False,
        "pillar": "game",
    },
    "intel_hub": {
        "type": "flask",
        "cls": "content.scenes.intel_hub.intel_hub_scene.IntelHubScene",
        "label": "THE BRIEFING ROOM",
        "auto_start": True,
        "pillar": "service",
    },
    "asset_studio": {
        "type": "flask",
        "cls": "content.scenes.asset_studio.asset_studio_scene.AssetStudioScene",
        "label": "ASSET STUDIO",
        "auto_start": False,
        "pillar": "creation",
    },
    # v1.47.0 [2026-03-21] â€” Creation Kit visual scene editor
    "creation_kit": {
        "type": "flask",
        "cls": "content.scenes.creation_kit.creation_kit_scene.CreationKitScene",
        "label": "CREATION KIT",
        "auto_start": False,
        "pillar": "creation",
    },
    "lab_break": {
        "type": "flask",
        "cls": "content.scenes.lab_break.lab_break_scene.LabBreakScene",
        "label": "LAB BREAK",
        "auto_start": False,
        "pillar": "game",
    },
    # v1.52.0 — Auto-registered by Creation Kit
    "oracle": {
        "type": "flask",
        "cls": "content.scenes.oracle.oracle_scene.OracleScene",
        "label": "THE ORACLE",
        "auto_start": False,
        "pillar": "game",
    },
}

# ──── Derived ID Tuples ──────────────────────────────────────────────────────

SERVICE_IDS: Tuple[str, ...] = tuple(SERVICE_DEFS.keys())
SCENE_IDS: Tuple[str, ...] = tuple(SCENE_DEFS.keys())


# â”€â”€â”€â”€ Catalogue Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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
                "pillar": info.get("pillar", "service"),
            }
    return metadata


# â”€â”€â”€â”€ Pillar Grouping â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def get_targets_by_pillar(pillar: str) -> Dict[str, Dict[str, Any]]:
    """Return all SERVICE_DEFS + SCENE_DEFS entries matching *pillar*."""
    result: Dict[str, Dict[str, Any]] = {}
    for catalogue in (SERVICE_DEFS, SCENE_DEFS):
        for target_id, info in catalogue.items():
            if info.get("pillar") == pillar:
                result[target_id] = info
    return result


# v1.42.1 [2026-03-21] â€” Pre-computed pillar membership for fast lookup
PILLAR_IDS: Dict[str, Tuple[str, ...]] = {
    "game": tuple(
        tid for tid, info in {**SERVICE_DEFS, **SCENE_DEFS}.items()
        if info.get("pillar") == "game"
    ),
    "service": tuple(
        tid for tid, info in {**SERVICE_DEFS, **SCENE_DEFS}.items()
        if info.get("pillar") == "service"
    ),
    "creation": tuple(
        tid for tid, info in {**SERVICE_DEFS, **SCENE_DEFS}.items()
        if info.get("pillar") == "creation"
    ),
}


# â”€â”€â”€â”€ Launcher Catalogue Builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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


# â”€â”€â”€â”€ Dynamic scene discovery â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def scan_scene_directories() -> Dict[str, Any]:
    """Scan ``content/scenes/`` for directories that look like scenes.

    A directory qualifies as a scene candidate when it contains an
    ``__init__.py`` file and is not prefixed with ``_`` (archives/internal).
    The results are compared against ``SCENE_DEFS`` so callers can see which
    directories are registered and which are potentially new/unregistered.

    Returns:
        Dict with ``registered``, ``unregistered``, ``archived``, and
        ``total_dirs`` keys.
    """
    scenes_root = PROJECT_ROOT / "content" / "scenes"
    if not scenes_root.is_dir():
        return {"error": "content/scenes directory not found", "registered": [], "unregistered": [], "archived": []}

    registered: list[str] = []
    unregistered: list[str] = []
    archived: list[str] = []

    for child in sorted(scenes_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name

        # Skip hidden/dunder directories
        if name.startswith("__"):
            continue

        # Archived directories (prefixed with _)
        if name.startswith("_"):
            archived.append(name)
            continue

        # Must have __init__.py to be a scene candidate
        if not (child / "__init__.py").exists():
            continue

        if name in SCENE_DEFS:
            registered.append(name)
        else:
            unregistered.append(name)

    return {
        "registered": registered,
        "unregistered": unregistered,
        "archived": archived,
        "total_dirs": len(registered) + len(unregistered) + len(archived),
        "registered_count": len(registered),
        "unregistered_count": len(unregistered),
    }
