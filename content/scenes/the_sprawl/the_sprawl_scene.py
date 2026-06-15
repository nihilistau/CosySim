"""The Sprawl — the living city map scene.
============================================

A real-time map of NEONCITY: watch the city move, walk its streets and change
its fate. Territory contests, NPC movement and the player's avatar render on a
live map fed by the engine's :class:`LivingWorld` simulation.

This module ships the SCAFFOLD (B-T1): a bootable placeholder scene that serves
a neon "THE SPRAWL — booting…" page (loading its own css/js + a live Socket.IO
connection) and a stub ``/api/state`` endpoint. The live map, territory layer
and avatar movement land in later v1.63 tasks.

The scene mirrors the canonical FlaskScene template (see
``content/scenes/executive_suite/executive_suite_scene.py``): FlaskScene base
class with Socket.IO, a one-route full-screen UI, a ``/api/state`` endpoint and
minimal lifecycle hooks.

Version: v1.63.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-15] — Initial scaffold (B-T1): bootable placeholder scene,
                            registered for launcher/TUI/hub + auto-start

CONNECTS: FlaskScene, SocketIO, WorldState, get_config
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

SCENE_ID = "the_sprawl"
# v1.63.0 [2026-06-15] — Structured logging context (SCENE_ID prefix + operation tags)


# ──── Scene Implementation ────────────────────────────────────

# v1.63.0 [2026-06-15] — Living-city map scaffold on FlaskScene base
class TheSprawlScene(FlaskScene):
    """The Sprawl: a live map of NEONCITY (the living city).

    Serves a full-screen neon city map — territory, NPCs and the player's
    avatar. B-T1 ships the bootable scaffold; the live map renders against the
    engine :class:`LivingWorld` simulation in later v1.63 tasks.

    CONNECTS: FlaskScene, SocketIO, WorldState, get_config
    CALLED BY: launcher.py, TUI, hub
    EMITS: state_update Socket.IO event
    """

    SCENE_METADATA = {
        "name": "the_sprawl",
        "display_name": "THE SPRAWL",
        "port": 5597,
        "type": "game",
        "accent_color": "#39ff14",
        "description": "The living city — watch it move, walk its streets, change its fate.",
        "version": "1.0.0",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 host: str = "0.0.0.0") -> None:
        super().__init__(host=host, port=self.SCENE_METADATA["port"])
        self.config = config or {}

        # Scene-specific secret key
        self.app.config["SECRET_KEY"] = "the-sprawl-scene"

        # Scene-specific route registrations
        self.register_bench_route(self.app, self.socketio)
        self._register_routes()
        self._setup_socketio_handlers()

    # ── Routes ─────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register all Flask API routes."""
        app = self.app

        @app.route("/")
        def index():
            return render_template(
                "the_sprawl.html",
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

        # v1.63.0 [2026-06-15] — Clients can poll fresh state over the socket
        @sio.on("request_state")
        def on_request_state():
            emit("state_update", self._get_scene_state())

    # ── State ──────────────────────────────────────────────────────

    def _get_scene_state(self) -> Dict[str, Any]:
        """Return the scene state for the template + future live map.

        B-T1 returns a stub (scene identity + live game clock). The live
        territory / NPC / avatar layers populate this in later v1.63 tasks.
        All lookups degrade gracefully — the scaffold must boot even when the
        world/config subsystems are offline.
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
    # v1.63.0 [2026-06-15] — FlaskScene handles start()/stop(); use hooks

    def on_before_serve(self) -> None:
        """Pre-serve setup (scaffold has no background services of its own)."""
        logger.info("[%s] living-city scaffold online (operation=lifecycle)", SCENE_ID)

    def on_shutdown(self) -> None:
        """Cleanup on shutdown."""
        logger.info("[%s] Scene stopping (operation=lifecycle)", SCENE_ID)
