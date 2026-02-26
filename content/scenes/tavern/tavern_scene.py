"""The Dragon's Flagon — Fantasy tavern scene.

Port 5558.  Flask + SocketIO.

A showcase scene demonstrating *every* major MCP framework feature:

    ✅  BaseScene + MCPSceneMixin      — proper lifecycle
    ✅  MCPSceneNode                   — state, rules, events
    ✅  SceneStateManager              — persistent character stats
    ✅  DialogSystem / ResponseDirective — forced NPC lines
    ✅  MCPTimer                       — bard songs, stranger arrival
    ✅  EventChain / emit_event        — quest events, brawl triggers
    ✅  Consequence chains             — delayed stat effects
    ✅  Tag registry                   — [MOOD:], [ACTION:], [STAT:]
    ✅  @skill pack                    — 11 agent-callable skills
    ✅  Reputation system              — gates NPC features
    ✅  Quest board                    — accept / progress / complete
    ✅  Dice gambling                  — gold economy
    ✅  Atmosphere / heat meter        — quiet → lively → rowdy → brawl
    ✅  Time-of-day cycle              — morning → midnight
    ✅  NPC profiles                   — 4 NPCs with personalities
    ✅  Rumour system                  — unlocks quests
    ✅  Web UI                         — Flask + SocketIO + HTML

Created as a reference implementation for new scene developers.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

from engine.scenes.base_scene import BaseScene
from engine.scenes.nexus_mixin import NexusSceneMixin
from content.shared import register_shared_assets

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

SCENE_ID = "tavern"
DEFAULT_PORT = 5558


# ---------------------------------------------------------------------------
#  Scene class
# ---------------------------------------------------------------------------

class TavernScene(BaseScene, NexusSceneMixin):
    """The Dragon's Flagon — a fantasy tavern.

    Inherits BaseScene for lifecycle management and uses MCPSceneMixin
    (applied via __init_subclass__ if available, or manual wiring).
    """

    SCENE_METADATA = {
        "title": "The Dragon's Flagon",
        "description": (
            "A fantasy tavern with 4 NPCs, quest board, dice gambling, "
            "reputation system, and dynamic atmosphere.  MCP framework "
            "showcase scene."
        ),
        "genre": "fantasy_social",
        "max_characters": 4,
        "features": [
            "multi_npc",
            "reputation_system",
            "quest_board",
            "dice_gambling",
            "atmosphere_heat",
            "rumor_system",
            "bard_music",
            "merchant_trade",
            "time_cycle",
            "consequence_chains",
            "mcp_showcase",
        ],
    }

    # ------------------------------------------------------------------
    #  Init
    # ------------------------------------------------------------------

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        super().__init__(scene_name=SCENE_ID, host=host, port=port)

        # Lazy imports to avoid circular deps at module level
        from .tavern_state import TavernState

        self.tavern_state = TavernState()

        # Flask app
        self.app = Flask(
            __name__,
            template_folder=os.path.join(os.path.dirname(__file__), "templates"),
            static_folder=os.path.join(os.path.dirname(__file__), "static"),
        )
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode="threading")
        register_shared_assets(self.app)

        self._register_routes()
        self._register_socketio()

        # MCP wiring
        self._wire_mcp()

        # Background ticker
        self._ticker_running = False
        self._ticker_thread: Optional[threading.Thread] = None

        self.nexus_init("tavern")

        log.info("TavernScene created on port %d", port)

    # ------------------------------------------------------------------
    #  MCP integration
    # ------------------------------------------------------------------

    def _wire_mcp(self) -> None:
        """Wire into the MCP framework — scene node, lifecycle hooks."""
        try:
            from engine.mcp.framework import get_framework

            fw = get_framework()
            self._fw = fw
            self._scene_node = fw.get_scene(SCENE_ID)

            # Update scene node state from our tavern state
            self._sync_mcp_state()

            # Lifecycle hooks
            fw.add_lifecycle_hook("framework_ready", self._on_framework_ready)
            fw.add_lifecycle_hook("scene_tick", self._on_scene_tick)

            log.info("TavernScene MCP wired")
        except Exception as exc:
            log.warning("MCP wiring failed (non-fatal): %s", exc)
            self._fw = None
            self._scene_node = None

    def _sync_mcp_state(self) -> None:
        """Push current tavern state into the MCP scene node."""
        if self._scene_node:
            self._scene_node.update_state(self.tavern_state.to_snapshot())

    def _on_framework_ready(self, **_kw: Any) -> None:
        log.info("MCP framework ready — tavern scene active")

    def _on_scene_tick(self, scene_id: str = "", **_kw: Any) -> None:
        if scene_id == SCENE_ID:
            self._tick()

    def _tick(self) -> None:
        """Advance one game tick — decay heat, check timers, fire consequences."""
        state = self.tavern_state
        state.adjust_heat(-1)  # Natural cool-down
        state.turn += 1

        # Maybe stranger appears
        if state.maybe_stranger_appears():
            self._emit("event", {"type": "stranger_arrives",
                                 "text": "A hooded stranger slips through the door..."})

        # Sync state to MCP
        self._sync_mcp_state()

        # Fire due consequences
        if self._fw:
            try:
                fired = self._fw.tick(SCENE_ID)
                for c in fired:
                    self._emit("consequence", c)
            except Exception:
                pass

    # ------------------------------------------------------------------
    #  Background ticker
    # ------------------------------------------------------------------

    def _start_ticker(self) -> None:
        if self._ticker_running:
            return
        self._ticker_running = True
        self._ticker_thread = threading.Thread(target=self._ticker_loop, daemon=True)
        self._ticker_thread.start()

    def _ticker_loop(self) -> None:
        while self._ticker_running:
            time.sleep(30)  # Tick every 30s
            try:
                self._tick()
            except Exception as exc:
                log.debug("Ticker error: %s", exc)

    def _stop_ticker(self) -> None:
        self._ticker_running = False

    # ------------------------------------------------------------------
    #  Flask routes
    # ------------------------------------------------------------------

    def _register_routes(self) -> None:
        app = self.app

        @app.route("/")
        def index():
            return render_template("tavern_ui.html")

        @app.route("/api/health")
        def health():
            return jsonify(self.get_health())

        @app.route("/api/status")
        def status():
            return jsonify(self.tavern_state.to_snapshot())

        @app.route("/api/drink", methods=["POST"])
        def order_drink():
            data = request.json or {}
            drink_id = data.get("drink_id", "ale")
            from .tavern_skills import tavern_order_drink
            result = tavern_order_drink(drink_id=drink_id)
            self._sync_mcp_state()
            self._emit("drink", {"drink": drink_id, "result": result})
            return jsonify({"result": result, "state": self.tavern_state.to_snapshot()})

        @app.route("/api/quest", methods=["POST"])
        def quest_action():
            data = request.json or {}
            action = data.get("action", "list")
            quest_id = data.get("quest_id", "")
            from .tavern_skills import tavern_quest_board
            result = tavern_quest_board(action=action, quest_id=quest_id)
            self._sync_mcp_state()
            return jsonify({"result": result, "state": self.tavern_state.to_snapshot()})

        @app.route("/api/dice", methods=["POST"])
        def dice_action():
            data = request.json or {}
            action = data.get("action", "start")
            bet = data.get("bet", 5)
            from .tavern_skills import tavern_dice
            result = tavern_dice(action=action, bet=bet)
            self._sync_mcp_state()
            self._emit("dice", {"action": action, "result": result})
            return jsonify({"result": result, "state": self.tavern_state.to_snapshot()})

        @app.route("/api/trade", methods=["POST"])
        def trade_action():
            data = request.json or {}
            action = data.get("action", "browse")
            item_id = data.get("item_id", "")
            from .tavern_skills import tavern_trade
            result = tavern_trade(action=action, item_id=item_id)
            self._sync_mcp_state()
            return jsonify({"result": result, "state": self.tavern_state.to_snapshot()})

        @app.route("/api/rumor", methods=["POST"])
        def hear_rumor():
            from .tavern_skills import tavern_hear_rumor
            result = tavern_hear_rumor()
            self._sync_mcp_state()
            return jsonify({"result": result, "state": self.tavern_state.to_snapshot()})

        @app.route("/api/influence", methods=["POST"])
        def influence():
            data = request.json or {}
            action = data.get("action", "toast")
            from .tavern_skills import tavern_influence
            result = tavern_influence(action=action)
            self._sync_mcp_state()
            self._emit("atmosphere", {
                "action": action, "heat": self.tavern_state.heat,
                "atmosphere": self.tavern_state.atmosphere.value,
            })
            return jsonify({"result": result, "state": self.tavern_state.to_snapshot()})

        @app.route("/api/song", methods=["POST"])
        def request_song():
            data = request.json or {}
            mood = data.get("mood", "merry")
            from .tavern_skills import tavern_request_song
            result = tavern_request_song(mood=mood)
            self._sync_mcp_state()
            return jsonify({"result": result, "state": self.tavern_state.to_snapshot()})

        @app.route("/api/time", methods=["POST"])
        def advance_time():
            from .tavern_skills import tavern_advance_time
            result = tavern_advance_time()
            self._sync_mcp_state()
            self._emit("time_change", {
                "time": self.tavern_state.time_of_day.value,
                "turn": self.tavern_state.turn,
            })
            return jsonify({"result": result, "state": self.tavern_state.to_snapshot()})

        @app.route("/api/reputation/<npc_id>")
        def check_rep(npc_id: str):
            from .tavern_skills import tavern_check_reputation
            result = tavern_check_reputation(npc_id=npc_id)
            return jsonify({"result": result})

        @app.route("/api/narrative")
        def get_narrative():
            limit = request.args.get("limit", 20, type=int)
            entries = self.tavern_state.narrative[-limit:]
            return jsonify({"narrative": entries})

        # Health route for service discovery
        self.register_health_route(app)

        # Overlay + skills server
        try:
            self.mount_overlay(app)
            self.mount_skills_server(app)
        except Exception as exc:
            log.debug("Overlay/skills mount: %s", exc)

    # ------------------------------------------------------------------
    #  SocketIO
    # ------------------------------------------------------------------

    def _register_socketio(self) -> None:
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            sio.emit("state_update", self.tavern_state.to_snapshot())

        @sio.on("action")
        def on_action(data):
            action_type = data.get("type", "")
            log.debug("SocketIO action: %s", action_type)
            # Actions handled via REST API; SocketIO is for push updates

    def _emit(self, event: str, data: dict) -> None:
        """Push event to all connected WebSocket clients."""
        try:
            self.socketio.emit(event, data)
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  BaseScene interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        log.info("Starting TavernScene on %s:%d", self.host, self.port)
        self._start_ticker()
        self.socketio.run(self.app, host=self.host, port=self.port,
                          allow_unsafe_werkzeug=True)

    def stop(self) -> None:
        self.nexus_flush()
        log.info("Stopping TavernScene")
        self._stop_ticker()

    def get_health(self) -> Dict[str, Any]:
        return {
            "scene": SCENE_ID,
            "status": "running",
            "port": self.port,
            "turn": self.tavern_state.turn,
            "atmosphere": self.tavern_state.atmosphere.value,
            "npcs": len(self.tavern_state.npcs_present),
        }

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name": "tavern",
            "description": self.SCENE_METADATA["description"],
            "version": "0.50b",
            "author": "CosySim",
            "port": self.port,
            "tags": ["fantasy", "social", "tavern", "mcp_showcase"],
            "skill_packs": ["tavern"],
            "routes": [
                "/", "/api/health", "/api/status", "/api/drink",
                "/api/quest", "/api/dice", "/api/trade", "/api/rumor",
                "/api/influence", "/api/song", "/api/time",
                "/api/reputation/<npc_id>", "/api/narrative",
            ],
        }


# ---------------------------------------------------------------------------
#  Factory
# ---------------------------------------------------------------------------

def create_app(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> TavernScene:
    """Create and return a TavernScene instance."""
    return TavernScene(host=host, port=port)


if __name__ == "__main__":
    scene = TavernScene(host="0.0.0.0", port=DEFAULT_PORT)
    scene.start()
