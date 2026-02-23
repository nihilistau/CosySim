"""
NeonCity — Cyberpunk Strategy Board Game Scene
===============================================

A procedural 2D strategy board game showcasing the v3.x MCP framework with
turn-based gameplay, Glitch Storm shrink mechanic, prefab loot locations,
and AI opponents managed through VirtualAgentManager.
"""
from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from flask_socketio import SocketIO

from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin, get_framework

from .neoncity_state import (
    EVENT_POOL,
    PREFAB_TYPES,
    NeonCityGameState,
)

logger = logging.getLogger(__name__)

SCENE_ID = "neoncity"
DEFAULT_PORT = 5563


class NeonCityScene(BaseScene, MCPSceneMixin, mcp_scene_id="neoncity"):
    """NeonCity — Cyberpunk Strategy Board Game."""

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        super().__init__(scene_name=SCENE_ID, host=host, port=port)
        self._mcp_init()

        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"),
        )
        self.app.config["SECRET_KEY"] = "neoncity_v3"
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")

        self.mount_overlay(self.app, self.socketio)
        self.mount_skills_server(self.app)
        self.register_health_route(self.app)

        self.state: Optional[NeonCityGameState] = None
        self._setup_routes()
        self._setup_socketio()

    def _narrate(self, context: str) -> str:
        """Get a cyberpunk flavor narration from LMS (stateless)."""
        try:
            from engine.lmstudio.lms_client import get_lms_client
            client = get_lms_client()
            messages = [
                {"role": "system", "content": "You are a cyberpunk narrator for a board game called NeonCity. Give short, punchy, neon-drenched descriptions in 1-2 sentences. Use cyberpunk slang."},
                {"role": "user", "content": context},
            ]
            resp = client.chat(messages, temperature=0.9, max_tokens=100, store=False)
            return resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            logger.warning("NeonCity narration failed: %s", e)
            return ""

    def _sync_to_mcp(self) -> None:
        if not self.state:
            return
        try:
            self.mcp.update_state(self.state.to_dict())
        except Exception:
            pass

    def _setup_routes(self):

        @self.app.route("/")
        def index():
            return render_template("neoncity_ui.html", prefabs=PREFAB_TYPES)

        @self.app.route("/api/scene/info")
        def scene_info():
            return jsonify(self.get_plugin_info())

        @self.app.route("/api/game/state")
        def game_state():
            if not self.state:
                return jsonify({"active": False})
            return jsonify({"active": True, **self.state.to_dict()})

        @self.app.route("/api/game/grid")
        def game_grid():
            if not self.state:
                return jsonify({"error": "No game"}), 400
            return jsonify({"grid": self.state.get_grid_dict()})

        # ── NEW GAME ──

        @self.app.route("/api/game/new", methods=["POST"])
        def new_game():
            try:
                data = request.json or {}
                num_ai = data.get("ai_players", 3)
                self.state = NeonCityGameState(num_ai_players=num_ai)
                result = self.state.start_game()

                # Framework timer for Glitch Storm progression
                try:
                    fw = get_framework()
                    fw.start_timer("neoncity_glitch_storm", 600)
                    fw.schedule_consequence(
                        SCENE_ID, "system", "glitch_storm_advance",
                        {"round": 1}, turn_delay=3,
                    )
                except Exception:
                    pass

                narration = self._narrate("A new race begins in NeonCity. Runners spawn at the grid edges. A rogue AI program pulses at the city center.")
                self._sync_to_mcp()
                self.socketio.emit("game_started", self.state.to_dict())
                return jsonify({"success": True, **result, "narration": narration, "state": self.state.to_dict()})
            except Exception as exc:
                logger.error("new_game failed: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        # ── MOVE ──

        @self.app.route("/api/game/move", methods=["POST"])
        def move():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400
            data = request.json or {}
            result = self.state.move_player("player", data.get("x", 0), data.get("y", 0))
            if "error" in result:
                return jsonify(result), 400
            narration = ""
            if result.get("loot"):
                loot = result["loot"]
                narration = self._narrate(f"Runner loots a {loot.get('type', 'cache')}. {json.dumps(loot)}")
            self._sync_to_mcp()
            self.socketio.emit("player_moved", {"player": "player", **result})
            return jsonify({**result, "narration": narration, "state": self.state.to_dict()})

        # ── ATTACK ──

        @self.app.route("/api/game/attack", methods=["POST"])
        def attack():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400
            data = request.json or {}
            result = self.state.attack_player("player", data.get("target_id", ""), data.get("weapon_idx", 0))
            if "error" in result:
                return jsonify(result), 400
            narration = self._narrate(f"Combat: {'Hit for {0} damage'.format(result.get('damage',0)) if result.get('hit') else 'Miss!'}")
            self.socketio.emit("combat", result)
            return jsonify({**result, "narration": narration})

        # ── HACK ──

        @self.app.route("/api/game/hack", methods=["POST"])
        def hack():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400
            result = self.state.hack_target("player")
            if "error" in result:
                return jsonify(result), 400
            if result.get("breached"):
                narration = self._narrate("The firewall shatters. The AI program yields. You've won NeonCity.")
                self.socketio.emit("game_won", {"winner": "player"})
            else:
                narration = self._narrate(f"Hack attempt: {'Success!' if result.get('success') else 'Failed.'} Firewalls remaining: {result.get('firewall_remaining', '?')}")
            return jsonify({**result, "narration": narration})

        # ── END TURN ──

        @self.app.route("/api/game/end_turn", methods=["POST"])
        def end_turn():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400
            try:
                # Process AI turns
                ai_actions = []
                while True:
                    advance = self.state.advance_turn()
                    cp = self.state.get_current_player()
                    if not cp or not cp.is_ai:
                        break
                    actions = self.state.ai_turn(cp.id)
                    ai_actions.append({"player": cp.id, "name": cp.name, "actions": actions})
                    if self.state.ended:
                        break

                # Random event chance (30%)
                event_result = None
                if random.random() < 0.3 and not self.state.ended:
                    event_result = self.state.trigger_event()

                # Tick MCP framework — fire due consequences
                try:
                    fw = get_framework()
                    fw.tick(SCENE_ID)
                except Exception:
                    pass

                self._sync_to_mcp()
                state = self.state.to_dict()
                self.socketio.emit("turn_update", state)

                narration = ""
                if event_result:
                    narration = self._narrate(f"Event: {event_result['event']['label']} — {event_result['event']['description']}")

                return jsonify({
                    "ai_actions": ai_actions,
                    "event": event_result,
                    "narration": narration,
                    "state": state,
                })
            except Exception as exc:
                logger.error("end_turn failed: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

    def _setup_socketio(self):
        @self.socketio.on("connect")
        def on_connect():
            if self.state:
                self.socketio.emit("game_state", self.state.to_dict())

    # ── BaseScene contract ──

    def start(self) -> None:
        logger.info("NeonCity v3.2 — Cyberpunk Board Game starting on port %d", self.port)
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False, allow_unsafe_werkzeug=True)

    def stop(self) -> None:
        self._mcp_deregister_scene()

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name": "NeonCity",
            "scene_id": SCENE_ID,
            "description": "Cyberpunk strategy board game with procedural grid, Glitch Storm, and AI opponents.",
            "version": "3.2.0",
            "port": self.port,
            "author": "CosySim",
            "tags": ["strategy", "cyberpunk", "board_game", "procedural", "showcase"],
            "skill_packs": ["memory", "narrative"],
            "routes": [
                {"path": "/api/game/new",      "methods": ["POST"], "description": "Start new game"},
                {"path": "/api/game/move",     "methods": ["POST"], "description": "Move player"},
                {"path": "/api/game/attack",   "methods": ["POST"], "description": "Attack target"},
                {"path": "/api/game/hack",     "methods": ["POST"], "description": "Hack AI target"},
                {"path": "/api/game/end_turn", "methods": ["POST"], "description": "End turn"},
            ],
        }
