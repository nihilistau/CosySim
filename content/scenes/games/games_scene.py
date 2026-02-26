"""Games Arcade — proper BaseScene wrapper for game modules.

Port 5567.  Flask + SocketIO.

Wraps the existing MysteryGame and TruthOrDareGame modules in a
proper BaseScene with MCPSceneMixin so they participate in the
CosySim lifecycle and are discoverable via MCP skills.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from flask import Flask, jsonify, render_template
from flask_socketio import SocketIO

from engine.scenes.base_scene import BaseScene
from engine.scenes.nexus_mixin import NexusSceneMixin

log = logging.getLogger(__name__)

SCENE_ID = "games"
DEFAULT_PORT = 5567


class GamesScene(BaseScene, NexusSceneMixin):
    """Games Arcade — wraps MysteryGame and TruthOrDareGame in BaseScene."""

    SCENE_METADATA = {
        "name": "games",
        "title": "Games Arcade",
        "port": 5567,
        "type": "game",
        "description": (
            "Mini-game collection: Mystery Investigation (3 cases, 5 clues) "
            "and Truth-or-Dare (dice rolls, scoring). Playable via REST or MCP skills."
        ),
        "genre": "minigames",
        "max_characters": 2,
        "features": [
            "mystery_investigation",
            "truth_or_dare",
            "dice_rolls",
            "scoring",
            "mcp_skills",
        ],
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        super().__init__(scene_name=SCENE_ID, host=host, port=port)

        scene_dir = os.path.dirname(os.path.abspath(__file__))
        self.app = Flask(
            __name__,
            template_folder=os.path.join(scene_dir, "templates"),
            static_folder=os.path.join(scene_dir, "static"),
        )
        self.socketio = SocketIO(self.app, cors_allowed_origins="*",
                                 async_mode="threading")

        # Active game instances (keyed by character_id)
        self.mystery_games: Dict[str, Any] = {}
        self.tod_games: Dict[str, Any] = {}

        self._register_routes()
        self._wire_mcp()

        self.nexus_init("games")

        log.info("GamesScene created on port %d", port)

    def _wire_mcp(self) -> None:
        try:
            from engine.mcp.framework import get_framework
            fw = get_framework()
            self._scene_node = fw.get_scene(SCENE_ID)
            log.info("GamesScene MCP wired")
        except Exception as exc:
            log.warning("MCP wiring skipped: %s", exc)
            self._scene_node = None

    def _register_routes(self) -> None:
        app = self.app

        # Register existing blueprints
        from .mystery_investigation import mystery_bp
        from .truth_or_dare import truth_or_dare_bp
        app.register_blueprint(mystery_bp, url_prefix="/games/mystery")
        app.register_blueprint(truth_or_dare_bp, url_prefix="/games/truth-or-dare")

        @app.route("/")
        def index():
            return render_template("games.html")

        @app.route("/api/health")
        def health():
            return jsonify(self.get_health())

        @app.route("/api/status")
        def status():
            return jsonify({
                "scene": SCENE_ID,
                "mystery_active": len(self.mystery_games),
                "tod_active": len(self.tod_games),
            })

        self.register_health_route(app)
        try:
            self.mount_overlay(app)
            self.mount_skills_server(app)
        except Exception:
            pass

    # -- BaseScene interface --

    def start(self) -> None:
        log.info("Starting GamesScene on %s:%d", self.host, self.port)
        self.socketio.run(self.app, host=self.host, port=self.port,
                          allow_unsafe_werkzeug=True)

    def stop(self) -> None:
        self.nexus_flush()
        log.info("Stopping GamesScene")

    def get_health(self) -> Dict[str, Any]:
        return {
            "scene": SCENE_ID,
            "status": "running",
            "port": self.port,
        }

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name": "games",
            "description": self.SCENE_METADATA["description"],
            "version": "0.50b",
            "author": "CosySim",
            "port": self.port,
            "tags": ["games", "mystery", "truth_or_dare"],
            "skill_packs": ["games"],
            "routes": ["/", "/api/health", "/api/status",
                       "/games/mystery/*", "/games/truth-or-dare/*"],
        }


def create_app(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> GamesScene:
    return GamesScene(host=host, port=port)


if __name__ == "__main__":
    scene = GamesScene(host="0.0.0.0", port=DEFAULT_PORT)
    scene.start()
