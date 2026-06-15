"""The War Room — faction command center scene.
============================================

Pick a faction. Command crews. Take the city. The War Room is the player's
strategic command center for NEONCITY's emergent metagame — choose an
allegiance, issue crew orders and direct territory operations against the
rival factions that the living world simulates.

C-T1 ships the SCAFFOLD: a bootable placeholder scene serving a neon page and
a stub ``/api/state`` endpoint. The faction-select, crew-command and
territory-operations command center renders against the engine's existing
managers in later v1.63 tasks.

Version: v1.63.0 [2026-06-16]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-16] — Initial scaffold (C-T1): bootable placeholder scene,
                            registered for launcher/TUI/hub + auto-start

CONNECTS: FlaskScene, SocketIO, get_config
CALLED BY: launcher.py, TUI, hub
EMITS: state_update Socket.IO event
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import jsonify, render_template
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene

logger = logging.getLogger(__name__)

SCENE_ID = "war_room"
# v1.63.0 [2026-06-16] — Structured logging context (SCENE_ID prefix + operation tags)


# ──── Scene Implementation ────────────────────────────────────

# v1.63.0 [2026-06-16] — Faction command-center scaffold on FlaskScene base
class WarRoomScene(FlaskScene):
    """The War Room: the player's faction command center.

    Serves the faction command center — pick a faction, command crews and take
    the city. C-T1 ships the bootable scaffold; the live command center renders
    against the engine's emergent managers in later v1.63 tasks.

    CONNECTS: FlaskScene, SocketIO, get_config
    CALLED BY: launcher.py, TUI, hub
    EMITS: state_update Socket.IO event
    """

    SCENE_METADATA = {
        "name": "war_room",
        "display_name": "THE WAR ROOM",
        "port": 5598,
        "type": "game",
        "accent_color": "#ef4444",
        "description": "Pick a faction. Command crews. Take the city.",
        "version": "1.0.0",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 host: str = "0.0.0.0") -> None:
        super().__init__(host=host, port=self.SCENE_METADATA["port"])
        self.config = config or {}

        # Scene-specific secret key
        self.app.config["SECRET_KEY"] = "war-room-scene"

        # Scene-specific route registrations
        self.register_bench_route(self.app, self.socketio)
        self._register_routes()
        self._setup_socketio_handlers()

    # ── Config ─────────────────────────────────────────────────────

    def _cfg(self, key: str, default: Any) -> Any:
        """Return a ``war_room.*`` knob from config with a built-in default.

        Args:
            key: Short key under ``war_room.`` (e.g. ``"contest_delta"``).
            default: Fallback when config is unavailable or the key is unset.

        Returns:
            The configured value, or ``default`` (never raises).
        """
        try:
            from engine.config import get_config  # noqa: PLC0415
            return get_config().get("war_room." + key, default)
        except Exception as exc:  # config optional in minimal builds
            logger.debug("[%s] config lookup failed (operation=cfg, key=%s): %s",
                         SCENE_ID, key, exc)
            return default

    # ── Routes ─────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register all Flask API routes."""
        app = self.app

        @app.route("/")
        def index():
            return render_template(
                "war_room.html",
                scene_data=self._get_scene_state(),
            )

        @app.route("/api/state")
        def get_state():
            return jsonify(self._get_scene_state())

    def _setup_socketio_handlers(self) -> None:
        """Register Socket.IO event handlers."""
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            emit("state_update", self._get_scene_state())

        # v1.63.0 [2026-06-16] — Clients can poll fresh state over the socket
        @sio.on("request_state")
        def on_request_state():
            emit("state_update", self._get_scene_state())

    # ── State ──────────────────────────────────────────────────────

    def _get_scene_state(self) -> Dict[str, Any]:
        """Return the scene state for the template + future command center.

        C-T1 returns a stub (scene identity + live game clock). The faction /
        crew / territory layers populate this in later v1.63 tasks. All lookups
        degrade gracefully — the scaffold must boot even when the world/config
        subsystems are offline.
        """
        state: Dict[str, Any] = {
            "scene": SCENE_ID,
            "display_name": self.SCENE_METADATA["display_name"],
            "status": "booting",
            "accent_color": self.SCENE_METADATA["accent_color"],
            "version": self.SCENE_METADATA["version"],
        }
        state["clock"] = self._read_clock()
        return state

    def _read_clock(self) -> Dict[str, Any]:
        """Return the current in-game clock (falls back to a static label)."""
        try:
            from engine.world.world_state import get_world_state  # noqa: PLC0415
            wt = get_world_state().get_time()
            return {
                "game_hour": wt.game_hour,
                "game_day": wt.game_day,
                "game_day_name": wt.game_day_name,
                "time_of_day": wt.time_of_day,
                "display": wt.to_display(),
            }
        except Exception as exc:  # WorldState optional — never block boot
            logger.debug("[%s] clock unavailable (operation=state): %s", SCENE_ID, exc)
            return {
                "game_hour": 0,
                "game_day": 0,
                "game_day_name": "Mon",
                "time_of_day": "night",
                "display": "",
            }

    # ──── FlaskScene Lifecycle Hooks ─────────────────────────────
    # v1.63.0 [2026-06-16] — FlaskScene handles start()/stop(); use hooks

    def on_before_serve(self) -> None:
        """Subclass hook — scaffold has no world wiring yet (defensive)."""
        logger.info("[%s] command center online (operation=lifecycle)", SCENE_ID)

    def on_shutdown(self) -> None:
        """Subclass hook — scaffold has nothing to clean up yet."""
        logger.info("[%s] Scene stopping (operation=lifecycle)", SCENE_ID)
