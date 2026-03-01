"""
NeonCity — Living World Hub v0.68 "Dark Renaissance"
====================================================

The city breathes.  Six factions fight for control.  The night never ends.

Multi-district living city hub wiring together the economy, reputation,
world-simulation, and content engines under the MCP v3.x framework.
Board-game mode (Glitch Storm) is preserved at ``/board``.
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
from flask_socketio import SocketIO, emit

from engine.scenes.base_scene import BaseScene
from engine.scenes.nexus_mixin import NexusSceneMixin
from engine.mcp.framework import MCPSceneMixin, get_framework
from engine.mcp.scene_state import get_scene_state_manager
from engine.mcp.tag_registry import TagRegistry, TagDef
from engine.events.event_bus import get_event_bus, EventTypes
from engine.economy.economy import get_economy_manager, TransactionType
from engine.characters.reputation import get_reputation_manager
from engine.mechanics.consequences import get_consequence_store
from engine.world.world_state import get_world_state
from engine.world.world_sim import get_world_sim
from engine.content.content_engine import get_content_engine
from engine.director.scene_director import get_scene_director
from content.shared import register_shared_assets
from content.scenes.neoncity.neoncity_rules import register_neoncity_rules

from .neoncity_state import (
    EVENT_POOL,
    PREFAB_TYPES,
    NeonCityGameState,
)

logger = logging.getLogger(__name__)

SCENE_ID = "neoncity"
DEFAULT_PORT = 5563

# ---------------------------------------------------------------------------
# Module-level metadata (also set as class attribute for MCP discovery)
# ---------------------------------------------------------------------------

SCENE_METADATA: Dict[str, Any] = {
    "name": "neoncity",
    "display_name": "NEON CITY",
    "port": DEFAULT_PORT,
    "type": "world_hub",
    "accent_color": "#06b6d4",
    "accent_rgb": "6 182 212",
    "description": "The city breathes. Six factions fight for control. The night never ends.",
}

# ---------------------------------------------------------------------------
# City faction catalogue
# ---------------------------------------------------------------------------

_FACTIONS: Dict[str, Dict[str, Any]] = {
    "OmniCorp": {
        "engine_id": "CORPORATE",
        "color": "#3b82f6",
        "base_power": 78,
        "tag": "corp",
        "motto": "Control through compliance.",
    },
    "NeoTech": {
        "engine_id": "ARENA_GUILD",
        "color": "#8b5cf6",
        "base_power": 52,
        "tag": "tech",
        "motto": "The future is a product.",
    },
    "BlackMarket": {
        "engine_id": "UNDERGROUND",
        "color": "#f97316",
        "base_power": 22,
        "tag": "black",
        "motto": "Everything has a price.",
    },
    "Ghost_Net": {
        "engine_id": "HACKER",
        "color": "#22c55e",
        "base_power": 81,
        "tag": "ghost",
        "motto": "Data is the new oxygen.",
    },
    "SynthSec": {
        "engine_id": "SYNDICATE",
        "color": "#ec4899",
        "base_power": 43,
        "tag": "synth",
        "motto": "We keep the peace — at a cost.",
    },
    "DeepState": {
        "engine_id": "STREET",
        "color": "#06b6d4",
        "base_power": 70,
        "tag": "deep",
        "motto": "The shadows run deeper than you know.",
    },
}

# ---------------------------------------------------------------------------
# District catalogue
# ---------------------------------------------------------------------------

_DISTRICTS: Dict[str, Dict[str, Any]] = {
    "black_market": {
        "name": "BLACK MARKET",
        "icon": "🔫",
        "border_color": "#f97316",
        "controlling_faction": "BlackMarket",
        "activity_level": "busy",
        "description": "Buy/sell contraband, hire fixers, trade in the shadows.",
        "npcs": ["FIXER", "ARMORER", "INFO_BROKER"],
    },
    "corporate_tower": {
        "name": "CORPORATE TOWER",
        "icon": "🏢",
        "border_color": "#3b82f6",
        "controlling_faction": "OmniCorp",
        "activity_level": "quiet",
        "description": "Faction HQ, corporate espionage, and reputation quests.",
        "npcs": ["EXEC", "SEC_AGENT", "CORP_LIAISON"],
    },
    "underground_club": {
        "name": "UNDERGROUND CLUB",
        "icon": "🎵",
        "border_color": "#ec4899",
        "controlling_faction": "SynthSec",
        "activity_level": "busy",
        "description": "Connects to Lounge. Live performances, dark deals.",
        "npcs": ["BARTENDER", "DANCER", "CONTACT"],
    },
    "hacker_den": {
        "name": "HACKER DEN",
        "icon": "💻",
        "border_color": "#22c55e",
        "controlling_faction": "Ghost_Net",
        "activity_level": "dangerous",
        "description": "0xGH0ST base. Connects to Admin/phone.",
        "npcs": ["0xGH0ST", "NETRUNNER", "SYSOP"],
    },
    "street_level": {
        "name": "STREET LEVEL",
        "icon": "🌆",
        "border_color": "#facc15",
        "controlling_faction": "DeepState",
        "activity_level": "dangerous",
        "description": "NPCs, rumors, and world events unfold here.",
        "npcs": ["STREET_KID", "GANGER", "INFORMANT"],
    },
}

_TICKER_TEMPLATES: List[str] = [
    "[OMNICORP] Market share up {pct}% in lower districts",
    "[GHOST_NET] Security breach at SynthSec tower. Data released.",
    "[ALERT] Unrest detected in sector {sector}",
    "[NEOTECH] Patent granted on neural-link mk{v}",
    "[BLACKMARKET] Rare cybernetics shipment arriving at dock {dock}",
    "[SYNTHSEC] Curfew extended in zones {z1}–{z2}",
    "[DEEPSTATE] Shadow council convenes at midnight",
    "[BROADCAST] {faction} influence grows in the outer ring",
]


class NeonCityScene(BaseScene, MCPSceneMixin, NexusSceneMixin, mcp_scene_id="neoncity"):
    """NeonCity — Living World Hub v0.68 'Dark Renaissance'.

    Multi-district city scene wiring together economy, reputation,
    world-simulation, and content engines under the MCP v3.x framework.
    """

    SCENE_METADATA = SCENE_METADATA  # expose module-level dict on the class too

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        """Initialise NeonCity and wire all engine subsystems.

        Args:
            host: Bind address for the Flask/SocketIO server.
            port: TCP port for the server.
        """
        super().__init__(scene_name=SCENE_ID, host=host, port=port)
        self._mcp_init()

        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"),
        )
        self.app.config["SECRET_KEY"] = "neoncity_v068_dark_renaissance"
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        register_shared_assets(self.app)

        # BaseScene standard route mounts
        self.mount_overlay(self.app, self.socketio)
        self.mount_skills_server(self.app)
        self.register_health_route(self.app)
        self.register_bench_route(self.app, self.socketio)
        self.register_tts_route(self.app)

        # Board-game state (legacy)
        self.state: Optional[NeonCityGameState] = None

        # MCP framework helpers
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()
        self._tag_registry.register(TagDef(
            name="HACK",
            pattern=r"\[HACK:([^\]]+)\]",
            handler=None,
            strip_from_output=True,
            pre_warm_intent="neoncity_hack",
        ))

        # EventBus subscription tracking
        self._event_bus = get_event_bus()
        self._bus_subs: List[str] = []

        # MCP rules + Nexus
        register_neoncity_rules()
        self.nexus_init("neoncity")

        # Wire everything up
        self._setup_routes()
        self._setup_socketio()
        self._setup_event_bus()

    # ------------------------------------------------------------------
    # Private — city state helpers
    # ------------------------------------------------------------------

    def _get_faction_power(self, faction_name: str) -> int:
        """Compute current faction power blended with player reputation.

        Args:
            faction_name: Key in ``_FACTIONS``.

        Returns:
            Integer power value 0–100.
        """
        base = _FACTIONS.get(faction_name, {}).get("base_power", 50)
        try:
            rep_mgr = get_reputation_manager()
            engine_id = _FACTIONS[faction_name]["engine_id"]
            entry = rep_mgr.get_entry(engine_id, "player")
            delta = int(entry.standing / 10)
            return max(0, min(100, base + delta))
        except Exception:
            return base

    def _build_city_state(self) -> Dict[str, Any]:
        """Assemble a full city state snapshot.

        Returns:
            Dict containing districts, factions, world time, active events,
            and the player's credit balance.
        """
        # World time
        world_time: Dict[str, Any] = {"display": "NIGHT CYCLE", "time_of_day": "night"}
        try:
            wt = get_world_state().get_time()
            world_time = {
                "hour": wt.game_hour,
                "day": wt.game_day,
                "day_name": wt.game_day_name,
                "time_of_day": wt.time_of_day,
                "display": f"DAY {wt.game_day} — {wt.game_hour:02d}:00 [{wt.time_of_day.upper()}]",
            }
        except Exception as exc:
            logger.debug("WorldState unavailable: %s", exc)

        # Faction power snapshot
        factions: List[Dict[str, Any]] = [
            {
                "name": name,
                "color": data["color"],
                "power": self._get_faction_power(name),
                "tag": data["tag"],
                "motto": data["motto"],
            }
            for name, data in _FACTIONS.items()
        ]

        # Active world events
        active_events: List[Dict[str, Any]] = []
        try:
            for ev in get_world_state().get_active_events(scene=SCENE_ID):
                active_events.append({
                    "id": getattr(ev, "id", ""),
                    "label": getattr(ev, "label", str(ev)),
                    "description": getattr(ev, "description", ""),
                })
        except Exception as exc:
            logger.debug("WorldState events unavailable: %s", exc)

        # Economy balance
        credits_balance = 0
        try:
            credits_balance = get_economy_manager().get_balance("player")
        except Exception:
            pass

        return {
            "districts": _DISTRICTS,
            "factions": factions,
            "world_time": world_time,
            "active_events": active_events,
            "credits": credits_balance,
            "scene_id": SCENE_ID,
            "version": "0.68",
        }

    def _build_ticker_items(self) -> List[str]:
        """Generate live ticker items blending WorldSim events with templates.

        Returns:
            List of ticker strings for the scrolling display.
        """
        items: List[str] = []
        try:
            for ev in get_world_sim().get_all_events(limit=6):
                desc = getattr(ev, "description", str(ev))
                scene = getattr(ev, "scene", "CITY")
                items.append(f"[{scene.upper()}] {desc}")
        except Exception:
            pass

        for tmpl in random.sample(_TICKER_TEMPLATES, min(4, len(_TICKER_TEMPLATES))):
            items.append(tmpl.format(
                pct=random.randint(5, 20),
                sector=random.randint(1, 12),
                v=random.randint(2, 5),
                dock=random.randint(1, 8),
                z1=random.randint(1, 5),
                z2=random.randint(6, 10),
                faction=random.choice(list(_FACTIONS.keys())),
            ))
        return items

    def _sync_to_mcp(self) -> None:
        """Push current city state snapshot to MCPFramework."""
        try:
            self.mcp.update_state(self._build_city_state())
        except Exception:
            pass
        try:
            self._state_mgr.add_narrative(SCENE_ID, "NeonCity hub state synced.")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Private — narration
    # ------------------------------------------------------------------

    def _narrate(self, context: str) -> str:
        """Return a short cyberpunk narration string from LMS.

        Args:
            context: Description of what happened in the city.

        Returns:
            Narration string, or empty string on failure.
        """
        try:
            from engine.lmstudio.lms_client import get_lms_client
            from engine.mcp.comms_framework import build_governance_context
            client = get_lms_client()
            system = (
                "You are a cyberpunk narrator for NeonCity — a living, breathing city hub. "
                "Give short, punchy, neon-drenched descriptions in 1-2 sentences. "
                "Use cyberpunk slang. Reference factions, corps, and the underground."
            )
            gov_ctx = build_governance_context("neoncity_narrator", "neoncity", context)
            if gov_ctx:
                system = f"{system}\n\n{gov_ctx}"
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": context},
            ]
            resp = client.chat(messages, temperature=0.9, max_tokens=80, store=False)
            return resp.content if hasattr(resp, "content") else str(resp)
        except Exception as exc:
            logger.debug("NeonCity narration failed: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # Private — HTTP routes
    # ------------------------------------------------------------------

    def _setup_routes(self) -> None:
        """Register all Flask HTTP routes."""

        @self.app.route("/")
        def index():
            return render_template("neoncity.html")

        # Legacy board-game UI
        @self.app.route("/board")
        def board():
            return render_template("neoncity_ui.html", prefabs=PREFAB_TYPES)

        @self.app.route("/api/scene/info")
        def scene_info():
            return jsonify(self.get_plugin_info())

        @self.app.route("/api/city/state")
        def city_state_http():
            return jsonify(self._build_city_state())

        @self.app.route("/api/city/ticker")
        def city_ticker():
            return jsonify({"items": self._build_ticker_items()})

        @self.app.route("/api/city/factions")
        def city_factions():
            return jsonify({
                name: {**data, "power": self._get_faction_power(name)}
                for name, data in _FACTIONS.items()
            })

        # ── Board game routes (legacy) ──────────────────────────────────

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

        @self.app.route("/api/game/new", methods=["POST"])
        def new_game():
            try:
                data = request.json or {}
                num_ai = data.get("ai_players", 3)
                self.state = NeonCityGameState(num_ai_players=num_ai)
                result = self.state.start_game()
                try:
                    fw = get_framework()
                    fw.start_timer("neoncity_glitch_storm", 600)
                    fw.schedule_consequence(
                        SCENE_ID, "system", "glitch_storm_advance",
                        {"round": 1}, turn_delay=3,
                    )
                except Exception:
                    pass
                narration = self._narrate(
                    "A new race begins in NeonCity. Runners spawn at the grid edges."
                )
                self._sync_to_mcp()
                self.socketio.emit("game_started", self.state.to_dict())
                return jsonify({
                    "success": True, **result,
                    "narration": narration,
                    "state": self.state.to_dict(),
                })
            except Exception as exc:
                logger.error("new_game failed: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

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
                narration = self._narrate(
                    f"Runner loots a {result['loot'].get('type', 'cache')}."
                )
            self._sync_to_mcp()
            self.socketio.emit("player_moved", {"player": "player", **result})
            return jsonify({**result, "narration": narration, "state": self.state.to_dict()})

        @self.app.route("/api/game/attack", methods=["POST"])
        def attack():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400
            data = request.json or {}
            result = self.state.attack_player(
                "player", data.get("target_id", ""), data.get("weapon_idx", 0)
            )
            if "error" in result:
                return jsonify(result), 400
            narration = self._narrate(
                f"Combat: {'Hit for ' + str(result.get('damage', 0)) + ' damage' if result.get('hit') else 'Miss!'}"
            )
            self.socketio.emit("combat", result)
            return jsonify({**result, "narration": narration})

        @self.app.route("/api/game/hack", methods=["POST"])
        def hack():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400
            result = self.state.hack_target("player")
            if "error" in result:
                return jsonify(result), 400
            if result.get("breached"):
                narration = self._narrate(
                    "The firewall shatters. The AI program yields. You've won NeonCity."
                )
                self.socketio.emit("game_won", {"winner": "player"})
            else:
                narration = self._narrate(
                    f"Hack attempt: {'Success!' if result.get('success') else 'Failed.'} "
                    f"Firewalls remaining: {result.get('firewall_remaining', '?')}"
                )
            return jsonify({**result, "narration": narration})

        @self.app.route("/api/game/end_turn", methods=["POST"])
        def end_turn():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400
            try:
                ai_actions = []
                while True:
                    self.state.advance_turn()
                    cp = self.state.get_current_player()
                    if not cp or not cp.is_ai:
                        break
                    actions = self.state.ai_turn(cp.id)
                    ai_actions.append({"player": cp.id, "name": cp.name, "actions": actions})
                    if self.state.ended:
                        break
                event_result = None
                if random.random() < 0.3 and not self.state.ended:
                    event_result = self.state.trigger_event()
                try:
                    get_framework().tick(SCENE_ID)
                except Exception:
                    pass
                self._sync_to_mcp()
                state_dict = self.state.to_dict()
                self.socketio.emit("turn_update", state_dict)
                narration = ""
                if event_result:
                    ev = event_result.get("event", {})
                    narration = self._narrate(
                        f"Event: {ev.get('label', '?')} — {ev.get('description', '')}"
                    )
                return jsonify({
                    "ai_actions": ai_actions,
                    "event": event_result,
                    "narration": narration,
                    "state": state_dict,
                })
            except Exception as exc:
                logger.error("end_turn failed: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

    # ------------------------------------------------------------------
    # Private — Socket.IO handlers
    # ------------------------------------------------------------------

    def _setup_socketio(self) -> None:
        """Register all Socket.IO event handlers."""

        @self.socketio.on("connect")
        def on_connect():
            """Send initial city state on client connect."""
            try:
                self.socketio.emit("city_state", self._build_city_state())
                self.socketio.emit("ticker_update", {"items": self._build_ticker_items()})
            except Exception as exc:
                logger.warning("on_connect emission failed: %s", exc)

        @self.socketio.on("get_city_state")
        def on_get_city_state(_data=None):
            """Emit full city state: districts, factions, world time, events.

            Args:
                _data: Unused; accepted for protocol compatibility.
            """
            emit("city_state", self._build_city_state())

        @self.socketio.on("visit_district")
        def on_visit_district(data: Dict[str, Any]):
            """Emit district detail + NPCs present.

            Args:
                data: Dict with ``district`` key (str district key).
            """
            district_key = (data or {}).get("district", "")
            district = _DISTRICTS.get(district_key)
            if not district:
                emit("error", {"message": f"Unknown district: {district_key}"})
                return
            faction_name = district.get("controlling_faction", "")
            emit("district_info", {
                "district_key": district_key,
                "district": district,
                "faction_power": self._get_faction_power(faction_name),
                "faction_color": _FACTIONS.get(faction_name, {}).get("color", "#06b6d4"),
                "ticker": self._build_ticker_items()[:3],
            })

        @self.socketio.on("get_world_events")
        def on_get_world_events(_data=None):
            """Emit WorldSim digest for neoncity.

            Args:
                _data: Unused.
            """
            events: List[Dict[str, Any]] = []
            try:
                for ev in get_world_sim().get_digest(SCENE_ID):
                    events.append({
                        "id": getattr(ev, "id", ""),
                        "description": getattr(ev, "description", str(ev)),
                        "scene": getattr(ev, "scene", SCENE_ID),
                        "timestamp": str(getattr(ev, "timestamp", "")),
                    })
            except Exception as exc:
                logger.debug("WorldSim digest failed: %s", exc)
            emit("world_events", {"events": events, "scene": SCENE_ID})

        @self.socketio.on("get_faction_status")
        def on_get_faction_status(_data=None):
            """Emit all 6 faction standings with reputation context.

            Args:
                _data: Unused.
            """
            try:
                standings = get_reputation_manager().get_faction_standings("player")
            except Exception:
                standings = {}
            factions_out: List[Dict[str, Any]] = []
            for name, data in _FACTIONS.items():
                rep_entry = standings.get(data["engine_id"])
                factions_out.append({
                    "name": name,
                    "engine_id": data["engine_id"],
                    "color": data["color"],
                    "power": self._get_faction_power(name),
                    "standing": rep_entry.standing if rep_entry else 0,
                    "label": rep_entry.label if rep_entry else "Neutral",
                    "motto": data["motto"],
                })
            emit("faction_status", {"factions": factions_out})

        @self.socketio.on("buy_info")
        def on_buy_info(data: Dict[str, Any]):
            """Deduct credits and return ContentEngine lore for a topic.

            Args:
                data: Dict with ``topic`` (str) and ``cost`` (int) keys.
            """
            topic = (data or {}).get("topic", "city")
            cost = max(0, int((data or {}).get("cost", 50)))
            new_balance = 0
            try:
                economy = get_economy_manager()
                balance = economy.get_balance("player")
                if balance < cost:
                    emit("intel_result", {
                        "error": f"Insufficient credits. Need {cost}¢, have {balance}¢.",
                        "balance": balance,
                    })
                    return
                economy.transact(-cost, TransactionType.SPEND, SCENE_ID, f"intel: {topic}")
                new_balance = economy.get_balance("player")
            except Exception as exc:
                logger.warning("Economy transaction failed in buy_info: %s", exc)

            lore_text = ""
            try:
                item = get_content_engine().get_lore(topic, scene=SCENE_ID)
                if item:
                    lore_text = item.body if hasattr(item, "body") else str(item)
            except Exception as exc:
                logger.debug("ContentEngine lore failed: %s", exc)

            emit("intel_result", {
                "topic": topic,
                "cost": cost,
                "lore": lore_text or f"[BROKER] No active intel on '{topic}'. City keeps its secrets.",
                "balance": new_balance,
            })

    # ------------------------------------------------------------------
    # Private — EventBus subscriptions
    # ------------------------------------------------------------------

    def _setup_event_bus(self) -> None:
        """Subscribe to relevant cross-scene EventBus events."""

        def _on_world_event(event: Dict[str, Any]) -> None:
            """Forward major world events to all connected clients."""
            try:
                self.socketio.emit("world_major_event", {
                    "type": event.get("event_type", ""),
                    "payload": event.get("payload", {}),
                    "scene": event.get("scene", ""),
                })
            except Exception as exc:
                logger.debug("world_major_event emit failed: %s", exc)

        def _on_faction_shift(event: Dict[str, Any]) -> None:
            """Forward faction shift events to all connected clients."""
            try:
                self.socketio.emit("faction_update", {
                    "type": "faction_shift",
                    "payload": event.get("payload", {}),
                })
            except Exception as exc:
                logger.debug("faction_update emit failed: %s", exc)

        def _on_npc_action(event: Dict[str, Any]) -> None:
            """Forward NeonCity NPC action events to all connected clients."""
            if event.get("payload", {}).get("scene") != SCENE_ID:
                return
            try:
                self.socketio.emit("city_event", {
                    "type": "npc_action",
                    "payload": event.get("payload", {}),
                })
            except Exception as exc:
                logger.debug("city_event emit failed: %s", exc)

        try:
            bus = self._event_bus
            self._bus_subs.extend([
                bus.subscribe(EventTypes.WORLD_EVENT, _on_world_event, "neoncity_scene"),
                bus.subscribe(EventTypes.NEONCITY_FACTION_SHIFT, _on_faction_shift, "neoncity_scene"),
                bus.subscribe(EventTypes.NEONCITY_WORLD_EVENT, _on_npc_action, "neoncity_scene"),
            ])
            logger.info("NeonCity EventBus: %d subscriptions active.", len(self._bus_subs))
        except Exception as exc:
            logger.warning("EventBus subscription failed: %s", exc)

    # ------------------------------------------------------------------
    # BaseScene contract
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the NeonCity Flask/SocketIO server."""
        logger.info(
            'NeonCity v0.68 "Dark Renaissance" — Living World Hub starting on port %d',
            self.port,
        )
        self.socketio.run(
            self.app, host=self.host, port=self.port,
            debug=False, allow_unsafe_werkzeug=True,
        )

    def stop(self) -> None:
        """Tear down the scene and release all resources."""
        for sub_id in self._bus_subs:
            try:
                self._event_bus.unsubscribe(sub_id)
            except Exception:
                pass
        self.nexus_flush()
        self._mcp_deregister_scene()

    def get_plugin_info(self) -> Dict[str, Any]:
        """Return scene plugin metadata for the MCP registry.

        Returns:
            Dict with scene metadata, version, available routes, and skill packs.
        """
        return {
            "name": "NEON CITY",
            "display_name": "NEON CITY",
            "scene_id": SCENE_ID,
            "description": "The city breathes. Six factions fight for control. The night never ends.",
            "version": "0.68",
            "port": self.port,
            "type": "world_hub",
            "accent_color": "#06b6d4",
            "author": "CosySim",
            "tags": ["world_hub", "cyberpunk", "factions", "living_world", "economy"],
            "skill_packs": ["neoncity", "memory", "narrative"],
            "districts": list(_DISTRICTS.keys()),
            "factions": list(_FACTIONS.keys()),
            "routes": [
                {"path": "/",                 "methods": ["GET"],  "description": "Living World Hub UI"},
                {"path": "/board",            "methods": ["GET"],  "description": "Board game UI (legacy)"},
                {"path": "/api/city/state",   "methods": ["GET"],  "description": "Full city state"},
                {"path": "/api/city/ticker",  "methods": ["GET"],  "description": "World ticker items"},
                {"path": "/api/city/factions","methods": ["GET"],  "description": "Faction standings"},
                {"path": "/api/game/new",     "methods": ["POST"], "description": "Start board game"},
                {"path": "/api/game/move",    "methods": ["POST"], "description": "Move player"},
                {"path": "/api/game/attack",  "methods": ["POST"], "description": "Attack target"},
                {"path": "/api/game/hack",    "methods": ["POST"], "description": "Hack AI target"},
                {"path": "/api/game/end_turn","methods": ["POST"], "description": "End turn"},
            ],
        }
