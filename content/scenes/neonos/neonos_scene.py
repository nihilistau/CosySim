"""
NEON OS — NeonCity Virtual Desktop Shell
=========================================

A desktop-like browser UI that wraps all CosySim scenes as launchable apps
in a single window. Reads target definitions from the control-plane registry,
checks port status for each target, and serves a window-manager desktop shell.

Version: v1.51.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-25] — Full desktop shell with /api/apps, port status checks
    v1.0.0  [2026-03-25] — Initial scaffold via Creation Kit

Usage:
    python launcher.py neonos
    python launcher_game.py neonos
"""
from __future__ import annotations

import logging
import socket
from typing import Any, Dict, List

from flask import jsonify, render_template, request
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene
from engine.port_registry import get_port
from engine.world.player_state import get_player_state
from engine.control_plane_registry import (
    SERVICE_DEFS,
    SCENE_DEFS,
    get_target_metadata_catalogue,
)

logger = logging.getLogger(__name__)

SCENE_ID = "neonos"
DEFAULT_PORT = get_port(SCENE_ID, 5593)


# ──── Helpers ────────────────────────────────────────────────────────────

# v1.51.0 [2026-03-25] — Port status check (non-blocking, 300ms timeout)
def _port_up(port: int) -> bool:
    """Check if a TCP port is listening on localhost.

    Args:
        port: TCP port number to probe.

    Returns:
        True if a service is accepting connections on the port.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


# v1.51.0 [2026-03-25] — Icon mapping for known scene types
# CONNECTS: control_plane_registry target IDs
_ICON_MAP: Dict[str, str] = {
    "phone": "phone",
    "penthouse": "building",
    "lounge": "glass-cheers",
    "tavern": "beer",
    "casino": "dice",
    "gallery": "palette",
    "arena": "swords",
    "realm": "crown",
    "neoncity": "city",
    "coders": "code",
    "heist": "mask",
    "command_center": "terminal",
    "games": "gamepad",
    "grid": "th",
    "lab_break": "flask",
    "oracle": "eye",
    "intel_hub": "radar",
    "hub": "home",
    "nexus_panel": "database",
    "dashboard": "chart-bar",
    "admin": "cog",
    "assets": "image",
    "creator": "magic",
    "tts": "microphone",
    "bridge": "plug",
    "canvas": "book",
    "canvas_api": "server",
    "nlm_proxy": "satellite",
    "system_control": "sliders",
    "asset_studio": "paint-brush",
    "creation_kit": "tools",
    "neonos": "desktop",
}


# ──── Scene Class ────────────────────────────────────────────────────────


class NeonosScene(FlaskScene):
    """NEON OS virtual desktop scene.

    Provides a desktop shell that lists all CosySim scenes/services as
    launchable apps.  Each app opens in a draggable, resizable iframe window.

    CONNECTS: FlaskScene, control_plane_registry, port_registry
    CALLED BY: launcher.py, launcher_game.py, TUI
    EMITS: SocketIO events (scene_state, hud_update), REST API (/api/apps)
    """

    SCENE_METADATA = {
        "name": SCENE_ID,
        "display_name": "NEON OS",
        "port": DEFAULT_PORT,
        "type": "scene",
        "accent_color": "#00e5ff",
        "accent_rgb": "0 229 255",
        "description": "NeonCity Virtual Desktop — all scenes as apps in one window",
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        super().__init__(host=host, port=port)
        self._setup_routes()
        self._setup_socketio()

    # ── Routes ────────────────────────────────────────────────────────

    # v1.51.0 [2026-03-25] — Desktop shell routes + /api/apps endpoint
    def _setup_routes(self) -> None:
        """Register HTTP routes for NEON OS."""

        @self.app.route("/")
        def index():
            return render_template("neonos.html")

        @self.app.route("/api/scene/state")
        def scene_state():
            """Return current scene state snapshot."""
            return jsonify(self._build_state())

        @self.app.route("/api/apps")
        def api_apps():
            """List all CosySim scenes/services as launchable apps.

            Returns:
                JSON array of app descriptors with port, status, display_name,
                accent_color, pillar, and icon fields.

            CONNECTS: control_plane_registry (SERVICE_DEFS, SCENE_DEFS)
            CALLED BY: cosysim-desktop.js NeonDesktop.loadApps()
            """
            apps = self._build_app_list()
            return jsonify({"ok": True, "apps": apps})

    # ── SocketIO Handlers ─────────────────────────────────────────────

    def _setup_socketio(self) -> None:
        """Register Socket.IO event handlers."""

        @self.socketio.on("connect")
        def on_connect():
            logger.info("[neonos] Client connected (operation=connect)")
            emit("scene_state", self._build_state())

        @self.socketio.on("get_state")
        def on_get_state():
            """Client requests full state refresh."""
            emit("scene_state", self._build_state())

        @self.socketio.on("action")
        def on_action(data: Dict[str, Any]):
            """Handle a client action.

            Args:
                data: Dict with ``action`` (str) and optional payload keys.
            """
            action = (data or {}).get("action", "")
            logger.debug("[neonos] Action '%s' (operation=action): %s", action, data)

    # ── App List Builder ─────────────────────────────────────────────

    # v1.51.0 [2026-03-25] — Build app list from control-plane registry
    # CONNECTS: control_plane_registry.SERVICE_DEFS, SCENE_DEFS, port_registry
    def _build_app_list(self) -> List[Dict[str, Any]]:
        """Build a list of all CosySim targets as app descriptors.

        Each descriptor contains the fields needed by the desktop shell
        to render an app icon and open an iframe window.

        Returns:
            List of app dicts sorted by pillar (game first, then service,
            then creation), then alphabetically by ID.
        """
        apps: List[Dict[str, Any]] = []
        all_defs = {**SCENE_DEFS, **SERVICE_DEFS}

        # Pillar sort order: game scenes first, then services, then creation
        pillar_order = {"game": 0, "service": 1, "creation": 2}

        for target_id, info in all_defs.items():
            # Skip self — no point opening NeonOS inside itself
            if target_id == SCENE_ID:
                continue

            # Skip external/non-web targets that can't be iframed
            target_type = info.get("type", "flask")
            if target_type == "external":
                continue

            port = get_port(target_id, 0)
            if port == 0:
                continue

            # Determine display name from metadata
            label = info.get("label", target_id.replace("_", " ").title())

            # Determine accent color — scenes have SCENE_METADATA, fall back to default
            accent = self._get_accent_for_target(target_id)

            pillar = info.get("pillar", "service")

            apps.append({
                "id": target_id,
                "display_name": label,
                "port": port,
                "url": f"http://localhost:{port}/",
                "accent_color": accent,
                "pillar": pillar,
                "type": target_type,
                "icon": _ICON_MAP.get(target_id, "window-maximize"),
                "status": "up" if _port_up(port) else "down",
            })

        # Sort: pillar order, then alphabetical within each pillar
        apps.sort(key=lambda a: (pillar_order.get(a["pillar"], 9), a["display_name"]))
        return apps

    def _get_accent_for_target(self, target_id: str) -> str:
        """Look up the accent color for a target.

        Tries to read SCENE_METADATA from the scene class without importing
        it (too expensive). Falls back to pillar-based defaults.

        Args:
            target_id: The canonical target ID.

        Returns:
            CSS hex color string.
        """
        # Known accent colors for popular scenes
        accent_map: Dict[str, str] = {
            "phone": "#c084fc",
            "penthouse": "#f472b6",
            "lounge": "#f59e0b",
            "tavern": "#a78bfa",
            "casino": "#ef4444",
            "gallery": "#ec4899",
            "arena": "#f97316",
            "realm": "#8b5cf6",
            "neoncity": "#00e5ff",
            "coders": "#22d3ee",
            "heist": "#10b981",
            "command_center": "#6366f1",
            "games": "#facc15",
            "grid": "#06b6d4",
            "lab_break": "#34d399",
            "oracle": "#fbbf24",
            "intel_hub": "#60a5fa",
            "hub": "#3b82f6",
            "nexus_panel": "#14b8a6",
            "dashboard": "#8b5cf6",
            "admin": "#64748b",
            "assets": "#f472b6",
            "creator": "#a78bfa",
            "asset_studio": "#ec4899",
            "creation_kit": "#f59e0b",
            "system_control": "#64748b",
        }
        return accent_map.get(target_id, "#00e5ff")

    # ── State Builder ─────────────────────────────────────────────────

    def _build_state(self) -> Dict[str, Any]:
        """Build a scene state snapshot for the client.

        Returns:
            Dict with scene metadata and player state.
        """
        ps = get_player_state()
        return {
            "scene_id": SCENE_ID,
            "display_name": "NEON OS",
            "player": {
                "credits": ps.credits,
                "health": ps.health,
                "energy": ps.energy,
                "reputation": ps.reputation,
            },
        }

    # ── Lifecycle Hooks ───────────────────────────────────────────────

    def on_before_serve(self) -> None:
        """Scene-specific setup before serving."""
        logger.info(
            "[neonos] NEON OS desktop ready on port %d (operation=init)",
            DEFAULT_PORT,
        )
