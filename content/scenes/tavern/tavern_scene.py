"""THE RUSTY ANCHOR — v0.68 'Dark Renaissance' gritty dockside tavern scene.

Port 5558.  Flask + SocketIO.

A showcase scene demonstrating *every* major MCP framework feature:

    ✅  FlaskScene base class          — unified lifecycle
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

Version: v1.51.0 [2026-03-22]

Change Log:
    v1.51.0 [2026-03-22] — Migrated to FlaskScene (unified base class)
    v1.49.3 [2026-03-22] — Structured logging context (SCENE_ID prefix + operation tags)
    v0.68   [2026-03-20] — Dark Renaissance gritty dockside tavern
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from flask import jsonify, render_template, request

from engine.scenes.flask_scene import FlaskScene

try:
    from engine.world.world_state import get_world_state
    from engine.events.event_bus import get_event_bus, EventBus
    _WORLD_AVAILABLE = True
except ImportError:
    _WORLD_AVAILABLE = False

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

SCENE_ID = "tavern"
# v1.49.1 [2026-03-22] — Use port registry instead of hardcoded value
try:
    from engine.port_registry import get_port as _get_port
    DEFAULT_PORT = _get_port("tavern", 5558)
except Exception:
    DEFAULT_PORT = 5558


# ---------------------------------------------------------------------------
#  Scene class
# ---------------------------------------------------------------------------

# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class TavernScene(FlaskScene):
    """The Dragon's Flagon — a fantasy tavern.

    Inherits FlaskScene for unified lifecycle, MCP, and Nexus integration.
    """

    SCENE_METADATA = {
        "name": "tavern",
        "display_name": "THE RUSTY ANCHOR",
        "port": 5558,
        "type": "adventure",
        "accent_color": "#92400e",
        "accent_rgb": "146 64 14",
        "description": "Cheap ale. Cheaper lies. The best quests start here.",
        "genre": "dark_adventure",
        "max_characters": 6,
        "features": [
            "multi_npc",
            "reputation_system",
            "quest_board",
            "dice_gambling",
            "atmosphere_heat",
            "rumor_system",
            "investigation_board",
            "economy_integration",
            "time_cycle",
            "consequence_chains",
            "mcp_showcase",
        ],
    }

    # ------------------------------------------------------------------
    #  Init
    # ------------------------------------------------------------------

    # v1.51.0 [2026-03-22] — Migrated to FlaskScene
    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        super().__init__(host=host, port=port)

        # Lazy imports to avoid circular deps at module level
        from .tavern_state import TavernState

        self.tavern_state = TavernState()

        self._register_routes()
        self._register_socketio()

        # MCP wiring (scene-specific lifecycle hooks beyond FlaskScene._connect_mcp)
        self._wire_mcp()

        # ── World State ──────────────────────────────────────────────
        self._world_state = None
        self._event_bus_ref = None
        if _WORLD_AVAILABLE:
            self._world_state = get_world_state()
            self._event_bus_ref = get_event_bus()

        logger.info("[%s] Scene created on port %d", SCENE_ID, port)

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

            logger.info("[%s] MCP wired (operation=mcp_wire)", SCENE_ID)
        except Exception as exc:
            logger.warning("[%s] MCP wiring failed (operation=mcp_wire): %s", SCENE_ID, exc)
            self._fw = None
            self._scene_node = None

    def _sync_mcp_state(self) -> None:
        """Push current tavern state into the MCP scene node."""
        if self._scene_node:
            self._scene_node.update_state(self.tavern_state.to_snapshot())

    def _on_framework_ready(self, **_kw: Any) -> None:
        logger.info("[%s] MCP framework ready — scene active (operation=lifecycle)", SCENE_ID)

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
            except Exception as exc:
                # v1.49.1 [2026-03-22] — Surface tick failures
                logger.warning("[%s] MCP tick failed (operation=tick): %s", SCENE_ID, exc)

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
                logger.debug("Ticker error: %s", exc)

    def _stop_ticker(self) -> None:
        self._ticker_running = False

    # ------------------------------------------------------------------
    #  Flask routes
    # ------------------------------------------------------------------

    def _register_routes(self) -> None:
        app = self.app

        @app.route("/")
        def index():
            return render_template(
                "tavern.html",
                **self.inject_navbar_context(),
            )

        @app.route("/api/health")
        def health():
            try:
                return jsonify(self.get_health())
            except Exception:
                logger.exception("[%s] Health check failed (operation=health)", SCENE_ID)
                return jsonify({"status": "error", "scene": "tavern", "reason": "health check raised"}), 500

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

        @app.route("/api/economy")
        def api_economy():
            """Return current economy state for this scene."""
            try:
                from engine.economy.economy import get_economy_manager
                em = get_economy_manager()
                player_id = request.args.get("player_id", "player")
                return jsonify({
                    "scene": SCENE_ID,
                    "balance": em.get_balance(player_id),
                    "debt": em.check_debt(player_id),
                    "recent_transactions": [t.to_dict() for t in em.get_history(player_id, limit=10)],
                })
            except Exception as exc:
                logger.error("[%s] Economy API error (operation=economy): %s", SCENE_ID, exc)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/consequences")
        def api_consequences():
            """Return recent and pending consequences for this scene."""
            try:
                from engine.mechanics.consequences import get_consequence_store
                store = get_consequence_store()
                player_id = request.args.get("player_id", "player")
                return jsonify({
                    "recent": [c.to_dict() for c in store.get_history(player_id, limit=5)],
                    "pending": [c.to_dict() for c in store.get_pending(SCENE_ID, player_id)],
                })
            except Exception as exc:
                logger.error("[%s] Consequences API error (operation=consequences): %s", SCENE_ID, exc)
                return jsonify({"error": str(exc)}), 500

        # v1.51.0 — FlaskScene registers health, hud, announcer, inventory, tts
        # Scene-specific extra routes
        self.register_shop_route(app)

        # Bench metrics
        try:
            self.register_bench_route(app, self.socketio)
        except Exception as exc:
            logger.debug("Bench route: %s", exc)

        # Overlay + skills server
        try:
            self.mount_overlay(app)
            self.mount_skills_server(app)
        except Exception as exc:
            logger.debug("Overlay/skills mount: %s", exc)

    # ------------------------------------------------------------------
    #  SocketIO
    # ------------------------------------------------------------------

    def _register_socketio(self) -> None:
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            sio.emit("state_update", self.tavern_state.to_snapshot())

        @sio.on("get_tavern_state")
        def on_get_tavern_state(_data=None):
            snap = self.tavern_state.to_snapshot()
            sio.emit("tavern_state", {
                "time_of_day": snap.get("time_of_day", "evening"),
                "atmosphere": snap.get("atmosphere", "quiet"),
                "heat": snap.get("heat", 0),
                "available_quests": [
                    q for q in snap.get("quests", {}).values()
                    if q.get("status") == "available"
                ],
                "gold": snap.get("gold", 0),
                "turn": snap.get("turn", 0),
            })

        @sio.on("get_quest_board")
        def on_get_quest_board(_data=None):
            try:
                from engine.content.content_engine import get_content_engine
                ce = get_content_engine()
                items = ce.get_by_scene("tavern", content_type="quest", limit=8)
                quests = [
                    {"id": it.id, "title": it.title, "content": it.content,
                     "tags": it.tags, "intensity": it.intensity}
                    for it in items
                ]
            except Exception:
                quests = []
            if not quests:
                snap = self.tavern_state.to_snapshot()
                quests = [
                    {"id": qid, "title": q.get("title", qid),
                     "reward": q.get("reward_gold", 0), "status": q.get("status")}
                    for qid, q in snap.get("quests", {}).items()
                    if q.get("status") == "available"
                ]
            sio.emit("quest_board", {"quests": quests})

        @sio.on("accept_quest")
        def on_accept_quest(data):
            quest_id = (data or {}).get("quest_id", "")
            if not quest_id:
                sio.emit("error", {"message": "quest_id required"})
                return
            q = self.tavern_state.accept_quest(quest_id)
            self._sync_mcp_state()
            if q:
                try:
                    from engine.events.event_bus import get_event_bus
                    get_event_bus().publish(
                        "tavern.quest_accepted",
                        {"quest_id": quest_id, "title": q.title},
                    )
                except Exception as e:
                    logger.debug("[TavernScene] Silent exception suppressed (operation=best_effort): %s", e)
                sio.emit("quest_started", {
                    "quest_id": quest_id,
                    "title": q.title,
                    "objective": q.objective,
                    "reward_gold": q.reward_gold,
                })
            else:
                sio.emit("error", {"message": f"Quest '{quest_id}' not available."})

        @sio.on("roll_dice")
        def on_roll_dice(data):
            import random
            d = data or {}
            sides = max(2, min(int(d.get("sides", 20)), 100))
            reason = d.get("reason", "skill check")
            rolls = [random.randint(1, sides) for _ in range(3)]
            total = sum(rolls)
            sio.emit("dice_result", {
                "sides": sides,
                "rolls": rolls,
                "total": total,
                "reason": reason,
                "critical": total == sides * 3,
                "fumble": total == 3,
            })
            self._emit("event", {
                "type": "dice_roll",
                "text": f"Dice roll ({reason}): [{chr(44).join(str(r) for r in rolls)}] = {total}",
            })

        @sio.on("order_drink")
        def on_order_drink(data):
            drink = (data or {}).get("drink", "ale")
            try:
                from engine.economy.economy import get_economy_manager, TransactionType
                from .tavern_state import DRINKS_MENU
                item = next((d for d in DRINKS_MENU if d.id == drink), None)
                if item:
                    get_economy_manager().transact(
                        entity_id="player",
                        amount=-item.price,
                        transaction_type=TransactionType.SPEND,
                        description=f"Ordered {item.name} at The Rusty Anchor",
                    )
            except Exception as e:
                logger.debug("[TavernScene] Silent exception suppressed (operation=best_effort): %s", e)
            from .tavern_skills import buy_drink_and_rumor
            result = buy_drink_and_rumor(drink_name=drink)
            self._sync_mcp_state()
            sio.emit("drink_result", {"drink": drink, "result": result})

        @sio.on("investigate_rumor")
        def on_investigate_rumor(data):
            rumor_id = (data or {}).get("rumor_id", "")
            try:
                from engine.mechanics.investigation import get_investigation_board
                board = get_investigation_board("tavern_rumors", scene="tavern")
                board.add_clue(
                    clue_id=rumor_id or f"rumor_{len(board.get_clues())}",
                    title="Tavern Rumor",
                    description=f"Rumor heard at The Rusty Anchor: {rumor_id}",
                    source="barkeep",
                    tags=["rumor", "tavern"],
                )
                sio.emit("rumor_investigated", {
                    "rumor_id": rumor_id,
                    "clues": len(board.get_clues()),
                })
            except Exception as exc:
                logger.debug("Investigate rumor error: %s", exc)
                sio.emit("rumor_investigated", {"rumor_id": rumor_id, "clues": 0})

        # v1.49.1 [2026-03-22] — Removed legacy NOOP "action" handler
        # (new actions use dedicated events above)

    def _emit(self, event: str, data: dict) -> None:
        """Push event to all connected WebSocket clients."""
        try:
            self.socketio.emit(event, data)
        except Exception as e:
            logger.debug("[TavernScene] Silent exception suppressed (operation=best_effort): %s", e)

    # ------------------------------------------------------------------
    #  BaseScene interface
    # ------------------------------------------------------------------

    # v1.51.0 [2026-03-22] — Lifecycle delegated to FlaskScene

    def on_before_serve(self) -> None:
        """Hook: subscribe to world events before the server starts."""
        if _WORLD_AVAILABLE and self._event_bus_ref:
            self._event_bus_ref.subscribe("world.tick", self._on_world_tick)
            self._event_bus_ref.subscribe("world.time_change", self._on_time_change)

        # v1.51.1 [2026-03-25] — Auto-load tavern intrigue story pack
        try:
            from engine.mcp.narrative_packs import load_pack
            load_pack("tavern_intrigue", scene_id="tavern", character_id="bartender")
        except Exception:
            pass

    def on_shutdown(self) -> None:
        """Hook: unsubscribe from world events during shutdown."""
        if hasattr(self, "_event_bus_ref") and self._event_bus_ref:
            try:
                self._event_bus_ref.unsubscribe("world.tick", self._on_world_tick)
                self._event_bus_ref.unsubscribe("world.time_change", self._on_time_change)
            except Exception as e:
                logger.debug("[TavernScene] Silent exception suppressed (operation=best_effort): %s", e)

    # ── World State handlers ──────────────────────────────────────────
    def _on_world_tick(self, event: dict) -> None:
        """React to world simulation tick."""
        if hasattr(self, "socketio") and self.socketio:
            try:
                time_data = self._world_state.get_time()
                self.socketio.emit("world_tick", {
                    "hour": getattr(time_data, "hour", 0),
                    "day": getattr(time_data, "day", 1),
                    "weather": str(getattr(time_data, "weather", "clear")),
                })
            except Exception as e:
                logger.debug("[TavernScene] Silent exception suppressed (operation=best_effort): %s", e)

    def _on_time_change(self, event: dict) -> None:
        """Last call at 02:00 — refresh quest board at dawn (06:00)."""
        hour = event.get("hour", 0)
        if hour == 6 and hasattr(self, "socketio") and self.socketio:
            self.socketio.emit("quest_refresh", {"reason": "dawn"})

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
            "display_name": "THE RUSTY ANCHOR",
            "description": self.SCENE_METADATA["description"],
            "version": "0.68",
            "author": "CosySim",
            "port": self.port,
            "tags": ["adventure", "dockside", "tavern", "dark_renaissance", "mcp_showcase"],
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
