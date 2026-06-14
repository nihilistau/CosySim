"""Executive Suite — neon corporate OS desktop scene.
=====================================================

A full-screen neon "operating system" desktop for the executive pillar — a
windowed NeonOS shell (animated skyline + office bezel, left app dock,
draggable windows, bottom taskbar) that later hosts mail, files, notes,
music, code, terminal and a live in-world AI assistant.

This module ships the OS SHELL (ES-T2): the backend that serves the desktop
template and a minimal ``/api/state`` endpoint feeding the system tray
(game clock from :class:`WorldState`, plus config-driven heat / network /
battery readouts). Individual apps register themselves client-side via the
``window.ES`` app-registry API and add their own backend routes in later
v1.62 tasks.

The scene mirrors the canonical FlaskScene template (see
``content/scenes/lab_break/lab_break_scene.py``): FlaskScene base class with
Socket.IO, a one-route full-screen desktop UI, a ``/api/state`` endpoint,
and minimal lifecycle hooks.

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — OS desktop shell (ES-T2): window manager + dock +
                            taskbar + skyline; /api/state returns live clock +
                            tray readouts (replaces ES-T1 placeholder)
    v1.62.0 [2026-06-15] — Initial scaffold (ES-T1): bootable placeholder scene,
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

SCENE_ID = "executive_suite"
# v1.62.0 [2026-06-15] — Structured logging context (SCENE_ID prefix + operation tags)


# ──── Scene Implementation ────────────────────────────────────

# v1.62.0 [2026-06-15] — OS desktop shell on FlaskScene base
class ExecutiveSuiteScene(FlaskScene):
    """Executive Suite: a neon corporate OS desktop (the NeonOS shell).

    Serves a full-screen windowed desktop — animated skyline, office bezel,
    left app dock, draggable windows and a bottom taskbar. The shell defines
    the ``window.ES`` app-registry API; mail / files / notes / music / code /
    terminal / assistant apps register against it in later v1.62 tasks.

    CONNECTS: FlaskScene, SocketIO, WorldState, get_config
    CALLED BY: launcher.py, TUI, hub
    EMITS: state_update Socket.IO event
    """

    SCENE_METADATA = {
        "name": "executive_suite",
        "display_name": "EXECUTIVE SUITE",
        "port": 5596,
        "type": "game",
        "accent_color": "#06b6d4",
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

        # v1.62.0 [2026-06-15] — Clients can poll fresh state over the socket
        @sio.on("request_state")
        def on_request_state():
            emit("state_update", self._get_scene_state())

    # ── State ──────────────────────────────────────────────────────

    def _get_scene_state(self) -> Dict[str, Any]:
        """Return the desktop shell state for the template + tray.

        Pulls the live game clock from :class:`WorldState` when available and
        the system-tray readouts (heat / network / battery) from config so
        nothing is hardcoded. All lookups degrade gracefully — the shell must
        boot even when the world/config subsystems are offline.
        """
        state: Dict[str, Any] = {
            "scene": SCENE_ID,
            "display_name": self.SCENE_METADATA["display_name"],
            "status": "online",
            "accent_color": self.SCENE_METADATA["accent_color"],
            "version": self.SCENE_METADATA["version"],
        }
        state["clock"] = self._read_clock()
        state["tray"] = self._read_tray()
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

    def _read_tray(self) -> Dict[str, Any]:
        """Return system-tray readouts from config (no hardcoded values)."""
        try:
            from engine.config import get_config  # noqa: PLC0415
            cfg = get_config()
        except Exception:  # config optional — fall back to defaults below
            cfg = None

        def _cfg(key: str, default: Any) -> Any:
            if cfg is None:
                return default
            try:
                return cfg.get(key, default)
            except Exception:
                return default

        return {
            "heat": _cfg("executive_suite.tray.heat", 14),
            "battery": _cfg("executive_suite.tray.battery", 87),
            "network": _cfg("executive_suite.tray.network", "nexus"),
            "volume": _cfg("executive_suite.tray.volume", 60),
        }

    # ──── FlaskScene Lifecycle Hooks ─────────────────────────────
    # v1.62.0 [2026-06-15] — FlaskScene handles start()/stop(); use hooks

    def on_before_serve(self) -> None:
        """Pre-serve setup (shell has no background services of its own)."""
        logger.info("[%s] OS shell online (operation=lifecycle)", SCENE_ID)

    def on_shutdown(self) -> None:
        """Cleanup on shutdown."""
        logger.info("[%s] Scene stopping (operation=lifecycle)", SCENE_ID)
