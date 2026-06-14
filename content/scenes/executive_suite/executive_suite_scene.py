"""Executive Suite — neon corporate OS desktop scene.
=====================================================

A full-screen neon "operating system" desktop for the executive pillar —
mail, files, and a live in-world AI assistant. This module currently ships a
BOOTABLE PLACEHOLDER shell ("EXECUTIVE SUITE — booting…"); the real OS
desktop (windowing, apps, live comms) is implemented in later v1.62 tasks.

The scene mirrors the canonical FlaskScene template (see
``content/scenes/lab_break/lab_break_scene.py``): FlaskScene base class with
Socket.IO, a one-route placeholder UI, a ``/api/state`` endpoint, and minimal
lifecycle hooks.

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — Initial scaffold (ES-T1): bootable placeholder scene,
                            registered for launcher/TUI/hub + auto-start

CONNECTS: FlaskScene, SocketIO
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

SCENE_ID = "executive_suite"
# v1.62.0 [2026-06-15] — Structured logging context (SCENE_ID prefix + operation tags)


# ──── Scene Implementation ────────────────────────────────────

# v1.62.0 [2026-06-15] — Initial scaffold on FlaskScene base
class ExecutiveSuiteScene(FlaskScene):
    """Executive Suite: a neon corporate OS desktop (placeholder shell).

    The eventual experience is a full windowed desktop — mail, files, and a
    live AI assistant. For now this serves a styled "booting…" placeholder so
    the scene is launchable end-to-end and wired into every catalogue.

    CONNECTS: FlaskScene, SocketIO
    CALLED BY: launcher.py, TUI, hub
    EMITS: state_update Socket.IO event
    """

    SCENE_METADATA = {
        "name": "executive_suite",
        "display_name": "EXECUTIVE SUITE",
        "port": 5596,
        "type": "game",
        "accent_color": "#ffd700",
        "description": "A full neon OS desktop — mail, files, your live AI assistant.",
        "version": "1.62.0",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 host: str = "0.0.0.0") -> None:
        super().__init__(host=host, port=self.SCENE_METADATA["port"])
        self.config = config or {}

        # Scene-specific secret key
        self.app.config["SECRET_KEY"] = "executive-suite-scene"

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
                "executive_suite.html",
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

    # ── State ──────────────────────────────────────────────────────

    def _get_scene_state(self) -> Dict[str, Any]:
        """Return the placeholder scene state."""
        return {
            "scene": SCENE_ID,
            "display_name": self.SCENE_METADATA["display_name"],
            "status": "booting",
            "accent_color": self.SCENE_METADATA["accent_color"],
            "version": self.SCENE_METADATA["version"],
        }

    # ──── FlaskScene Lifecycle Hooks ─────────────────────────────
    # v1.62.0 [2026-06-15] — FlaskScene handles start()/stop(); use hooks

    def on_before_serve(self) -> None:
        """Pre-serve setup (placeholder — nothing to start yet)."""
        logger.info("[%s] Scene booting (operation=lifecycle)", SCENE_ID)

    def on_shutdown(self) -> None:
        """Cleanup on shutdown."""
        logger.info("[%s] Scene stopping (operation=lifecycle)", SCENE_ID)
