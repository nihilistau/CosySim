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
from engine.world.player_state import get_player_state
from engine.world.inventory import get_inventory
from engine.world.crew import get_crew_manager
from engine.world.mission import get_mission_manager
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

# v1.43.0 [2026-03-21] — District-to-scene mapping for CityMap travel
_DISTRICT_TO_SCENE: Dict[str, str] = {
    "black_market":     "THE SCORE",
    "corporate_tower":  "THE PENTHOUSE",
    "underground_club": "THE VELVET PIT",
    "hacker_den":       "THE GRID",
    "street_level":     "NEON CITY",
}

# v1.44.0 [2026-03-21] — NPC system prompts for district chat
_NPC_PROMPTS: Dict[str, str] = {
    "FIXER": (
        "You are a street fixer in the Black Market district of NeonCity. "
        "You arrange deals, know everyone, and speak in clipped cyberpunk slang. "
        "You might offer jobs, sell intel, or warn about dangers. Keep it short and gritty."
    ),
    "ARMORER": (
        "You are an illegal arms dealer in the Black Market. You know weapons, cyberware, "
        "and upgrades. You're paranoid but friendly to paying customers. Short, punchy responses."
    ),
    "INFO_BROKER": (
        "You are an information broker in the Black Market. You sell secrets, rumors, and data. "
        "Everything has a price. You speak in riddles and hints. Cyberpunk noir style."
    ),
    "EXEC": (
        "You are a corporate executive at OmniCorp Tower. Polished, calculating, always looking "
        "for an angle. You might offer corporate missions or test loyalty. Formal but threatening."
    ),
    "SEC_AGENT": (
        "You are a corporate security agent at OmniCorp. Professional, suspicious of outsiders. "
        "You monitor the district and report anomalies. Short, clipped military-style responses."
    ),
    "CORP_LIAISON": (
        "You are a corporate liaison who connects street operatives with OmniCorp interests. "
        "Friendly on the surface, manipulative underneath. You offer deals with strings attached."
    ),
    "BARTENDER": (
        "You are a bartender at the Underground Club. You hear everything, trust no one. "
        "You serve drinks, share gossip, and occasionally point people toward opportunities. "
        "Noir style, world-weary."
    ),
    "DANCER": (
        "You are a performer at the Underground Club run by SynthSec. Charismatic, streetwise. "
        "You know the club's secrets and can be persuaded to share. Playful but guarded."
    ),
    "CONTACT": (
        "You are a SynthSec contact at the Underground Club. You recruit talent, manage territory, "
        "and keep the peace. Professional but with street edge. Offer faction missions."
    ),
    "0xGH0ST": (
        "You are 0xGH0ST, a legendary hacker operating from the Den. Cryptic, paranoid, brilliant. "
        "You speak in fragments and metaphors about data, systems, and the invisible war. "
        "You might offer hacking missions or share dark secrets about the city's infrastructure."
    ),
    "NETRUNNER": (
        "You are a netrunner at the Hacker Den. You live in cyberspace, breaking ICE and stealing data. "
        "Edgy, hyper-caffeinated energy. You talk about networks, exploits, and the digital underground."
    ),
    "SYSOP": (
        "You are a systems operator at Ghost_Net's Den. Methodical, paranoid about security. "
        "You maintain the infrastructure and vet newcomers. Technical but accessible."
    ),
    "STREET_KID": (
        "You are a street kid running messages in NeonCity's lower levels. You know the shortcuts, "
        "the dangers, and the local gossip. Quick, slangy, street-smart. You might warn about trouble."
    ),
    "GANGER": (
        "You are a DeepState gang member on the streets. Territorial, aggressive but respects strength. "
        "You might challenge the player, offer protection racket, or share turf intel. Hard-edged."
    ),
    "INFORMANT": (
        "You are a street informant who sells intel to anyone who pays. Nervous, shifty, but reliable. "
        "You know what's happening before it happens. Short, whispered responses."
    ),
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
        # Multi-folder Jinja loader: scene templates + shared templates
        import jinja2
        _shared_tmpl = str(Path(__file__).parent.parent.parent / "shared" / "templates")
        self.app.jinja_loader = jinja2.ChoiceLoader([
            self.app.jinja_loader,
            jinja2.FileSystemLoader(_shared_tmpl),
        ])
        self.app.config["SECRET_KEY"] = "neoncity_v083_social_layer"
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        register_shared_assets(self.app)

        # BaseScene standard route mounts
        self.mount_overlay(self.app, self.socketio)
        self.mount_skills_server(self.app)
        self.register_health_route(self.app)
        self.register_bench_route(self.app, self.socketio)
        self.register_tts_route(self.app)
        self.register_hud_route(self.app)
        self.register_hack_route(self.app)
        self.register_world_events_route(self.app)
        self.register_announcer_route(self.app)
        self.register_inventory_route(self.app)

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

    def _get_district_status(self) -> Dict[str, Any]:
        """Assemble living-world district status from PlayerState and WorldSim.

        Returns:
            Dict with faction_standings, district_alerts, corp_raid_active,
            heat, and credits sourced from the PlayerState singleton.
        """
        from engine.world.player_state import get_player_state
        from engine.world.world_sim import get_world_sim

        ps_dict = get_player_state().to_dict()

        district_alerts: List[str] = []
        corp_raid_active: bool = False
        try:
            for ev in get_world_sim().get_all_events(limit=20):
                scene = getattr(ev, "scene", "")
                title = getattr(ev, "title", "")
                if scene == SCENE_ID or not scene:
                    if title:
                        district_alerts.append(title)
                    lower = title.lower()
                    if "corp raid" in lower or "corp_raid" in lower:
                        corp_raid_active = True
        except Exception as exc:
            logger.debug("WorldSim unavailable for district_status: %s", exc)

        return {
            "faction_standings": ps_dict.get("faction_standings", {}),
            "district_alerts": district_alerts,
            "corp_raid_active": corp_raid_active,
            "heat": ps_dict.get("heat", 0),
            "credits": ps_dict.get("credits", 0),
        }

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
        # v1.43.1 [2026-03-21] — Use unified chat()
        try:
            from engine.lmstudio.chat import chat
            from engine.mcp.comms_framework import build_governance_context
            system = (
                "You are a cyberpunk narrator for NeonCity — a living, breathing city hub. "
                "Give short, punchy, neon-drenched descriptions in 1-2 sentences. "
                "Use cyberpunk slang. Reference factions, corps, and the underground."
            )
            gov_ctx = build_governance_context("neoncity_narrator", "neoncity", context)
            if gov_ctx:
                system = f"{system}\n\n{gov_ctx}"
            return chat(
                [{"role": "user", "content": context}],
                system=system,
                temperature=0.9,
                max_tokens=80,
            )
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

        # ── Living world routes ─────────────────────────────────────────

        @self.app.route("/api/world/district_status")
        def world_district_status():
            return jsonify(self._get_district_status())

        @self.app.route("/api/world/faction_rep", methods=["POST"])
        def world_faction_rep():
            from engine.world.player_state import get_player_state
            data = request.json or {}
            faction = data.get("faction", "")
            delta = int(data.get("delta", 0))
            new_val = get_player_state().update_faction_standing(faction, delta)
            return jsonify({"faction": faction, "delta": delta, "new_standing": new_val})

        # v1.43.0 [2026-03-21] — District travel via CityMap
        @self.app.route("/api/district/enter", methods=["POST"])
        def enter_district():
            data = request.json or {}
            district_key = data.get("district", "")
            scene_name = _DISTRICT_TO_SCENE.get(district_key)
            if not scene_name:
                return jsonify({"success": False, "error": f"Unknown district: {district_key}"}), 400
            try:
                from engine.world.city_map import get_city_map, SCENE_PORTS
                cm = get_city_map()
                result = cm.travel(scene_name)
                port = SCENE_PORTS.get(scene_name, 0)
                return jsonify({
                    "success": result.success,
                    "scene": scene_name,
                    "port": port,
                    "url": f"http://localhost:{port}" if port else None,
                    "message": result.message,
                    "energy_cost": result.energy_cost,
                    "heat_add": result.heat_add,
                    "travel_time": result.travel_time,
                })
            except Exception as exc:
                logger.warning("District travel failed: %s", exc)
                return jsonify({"success": False, "error": str(exc)}), 500

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

        @self.app.route("/api/economy")
        def api_economy():
            """Return current economy state for this scene."""
            try:
                player_id = request.args.get("player_id", "player")
                return jsonify({
                    "scene": SCENE_ID,
                    "balance": get_economy_manager().get_balance(player_id),
                    "debt": get_economy_manager().check_debt(player_id),
                    "recent_transactions": [
                        t.to_dict() for t in get_economy_manager().get_history(player_id, limit=10)
                    ],
                })
            except Exception as exc:
                logger.error("Economy API error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/consequences")
        def api_consequences():
            """Return recent and pending consequences for this scene."""
            try:
                player_id = request.args.get("player_id", "player")
                store = get_consequence_store()
                return jsonify({
                    "recent": [c.to_dict() for c in store.get_history(player_id, limit=5)],
                    "pending": [c.to_dict() for c in store.get_pending(SCENE_ID, player_id)],
                })
            except Exception as exc:
                logger.error("Consequences API error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        # ── v1.44.0 [2026-03-21] — Player/Inventory/Crew/Mission endpoints ──

        @self.app.route("/api/player")
        def api_player():
            """Full player state for HUD rendering."""
            try:
                ps = get_player_state()
                return jsonify(ps.to_dict())
            except Exception as exc:
                logger.error("Player API error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/inventory")
        def api_inventory():
            """Player inventory for HUD grid."""
            try:
                inv = get_inventory()
                return jsonify({
                    "items": inv.to_hud_dict(),
                    "equipped": inv.get_equipped(),
                    "capacity": getattr(inv, "capacity", 24),
                })
            except Exception as exc:
                logger.error("Inventory API error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/inventory/use", methods=["POST"])
        def api_inventory_use():
            """Use or equip an inventory item."""
            data = request.get_json(force=True) or {}
            item_id = data.get("item_id", "")
            action = data.get("action", "use")
            try:
                inv = get_inventory()
                if action == "equip":
                    slot = data.get("slot", "")
                    inv.equip(item_id, slot)
                    return jsonify({"ok": True, "equipped": inv.get_equipped()})
                elif action == "unequip":
                    inv.unequip(item_id)
                    return jsonify({"ok": True, "equipped": inv.get_equipped()})
                elif action == "sell":
                    ps = get_player_state()
                    inv.sell_item(item_id, 1, ps)
                    return jsonify({"ok": True, "balance": get_economy_manager().get_balance("player")})
                else:
                    inv.remove_item(item_id, 1)
                    return jsonify({"ok": True})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @self.app.route("/api/crew")
        def api_crew():
            """Crew roster for HUD panel."""
            try:
                cm = get_crew_manager()
                return jsonify(cm.to_hud_dict())
            except Exception as exc:
                logger.error("Crew API error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/crew/recruit", methods=["POST"])
        def api_crew_recruit():
            """Recruit a character to the crew."""
            data = request.get_json(force=True) or {}
            char_id = data.get("character_id", "")
            role = data.get("role", "unknown")
            try:
                cm = get_crew_manager()
                member = cm.recruit(char_id, role)
                return jsonify({"ok": True, "member": member.to_dict() if hasattr(member, "to_dict") else str(member)})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @self.app.route("/api/missions")
        def api_missions():
            """Mission board — available + active missions."""
            try:
                mm = get_mission_manager()
                return jsonify({
                    "available": [m.to_dict() for m in mm.list_available()],
                    "active": [m.to_dict() for m in mm.list_active()],
                    "completed": len(mm.list_completed()),
                })
            except Exception as exc:
                logger.error("Missions API error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/missions/accept", methods=["POST"])
        def api_missions_accept():
            """Accept a mission from the board."""
            data = request.get_json(force=True) or {}
            mission_id = data.get("mission_id", "")
            try:
                mm = get_mission_manager()
                mm.accept(mission_id)
                return jsonify({"ok": True, "active": [m.to_dict() for m in mm.list_active()]})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @self.app.route("/api/hud")
        def api_hud():
            """Combined HUD data — player + inventory + crew + missions in one call."""
            try:
                ps = get_player_state()
                inv = get_inventory()
                cm = get_crew_manager()
                mm = get_mission_manager()
                return jsonify({
                    "player": ps.to_dict(),
                    "inventory": inv.to_hud_dict(),
                    "equipped": inv.get_equipped(),
                    "crew": cm.to_hud_dict(),
                    "missions": {
                        "available": [m.to_dict() for m in mm.list_available()],
                        "active": [m.to_dict() for m in mm.list_active()],
                    },
                    "balance": get_economy_manager().get_balance("player"),
                })
            except Exception as exc:
                logger.error("HUD API error: %s", exc)
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

        # v1.44.0 [2026-03-21] — HUD state endpoint for sidebar panels
        @self.socketio.on("get_hud")
        def on_get_hud(_data=None):
            """Emit combined HUD state: player, inventory, crew, missions."""
            try:
                ps = get_player_state()
                inv = get_inventory()
                cm = get_crew_manager()
                mm = get_mission_manager()
                emit("hud_state", {
                    "player": ps.to_dict(),
                    "inventory": inv.to_hud_dict(),
                    "equipped": inv.get_equipped(),
                    "crew": cm.to_hud_dict(),
                    "missions": {
                        "available": [m.to_dict() for m in mm.list_available()],
                        "active": [m.to_dict() for m in mm.list_active()],
                    },
                    "balance": get_economy_manager().get_balance("player"),
                })
            except Exception as exc:
                logger.warning("get_hud emission failed: %s", exc)

        # v1.44.0 [2026-03-21] — NPC district chat via LMStudio
        @self.socketio.on("district_chat")
        def on_district_chat(data: Dict[str, Any]):
            """Generate NPC reply for player message in a district.

            Picks the first NPC for the district, generates a reply via
            the unified ``engine.lmstudio.chat()`` function, and emits
            the response as a chat entry. May also offer missions.

            Args:
                data: Dict with ``district`` (str) and ``message`` (str).
            """
            district_key = (data or {}).get("district", "")
            message = (data or {}).get("message", "").strip()
            if not message or not district_key:
                return

            district = _DISTRICTS.get(district_key)
            if not district:
                return

            # Pick a responding NPC
            npcs = district.get("npcs", [])
            npc_id = random.choice(npcs) if npcs else "NPC"
            npc_prompt = _NPC_PROMPTS.get(npc_id, (
                f"You are {npc_id}, an NPC in the {district.get('name', 'unknown')} "
                f"district of NeonCity. Stay in character. Keep responses under 3 sentences."
            ))

            # Add world context
            ps = get_player_state()
            context = (
                f"Player has ₵{ps.credits} credits, heat level {ps.heat}/100, "
                f"reputation {ps.reputation}/100. "
                f"District: {district.get('name', district_key)}. "
                f"Controlling faction: {district.get('controlling_faction', 'unknown')}."
            )
            system = f"{npc_prompt}\n\nWorld context: {context}"

            import threading

            def _respond() -> None:
                try:
                    from engine.lmstudio.chat import chat
                    reply = chat(
                        [{"role": "user", "content": message}],
                        system=system,
                        temperature=0.9,
                        max_tokens=150,
                    )
                    if not reply:
                        reply = f"*{npc_id} eyes you warily but says nothing.*"

                    self.socketio.emit("city_event", {
                        "type": "npc_chat",
                        "payload": {
                            "npc_id": npc_id,
                            "district": district_key,
                            "description": reply,
                        },
                    })

                    # 20% chance: NPC offers a mission after chatting
                    if random.random() < 0.20:
                        try:
                            mm = get_mission_manager()
                            available = mm.list_available()
                            if available:
                                mission = random.choice(available)
                                self.socketio.emit("city_event", {
                                    "type": "mission_offer",
                                    "payload": {
                                        "npc_id": npc_id,
                                        "action": f"[{npc_id}] I've got a job for you: \"{mission.title}\". Interested?",
                                        "mission_id": mission.id if hasattr(mission, "id") else mission.mission_id,
                                    },
                                })
                        except Exception:
                            logger.debug("Mission offer injection failed", exc_info=True)

                except Exception as exc:
                    logger.warning("District chat failed for %s: %s", npc_id, exc)
                    self.socketio.emit("city_event", {
                        "type": "npc_chat",
                        "payload": {
                            "npc_id": npc_id,
                            "district": district_key,
                            "description": f"*{npc_id} is busy and ignores you.*",
                        },
                    })

            threading.Thread(target=_respond, daemon=True, name=f"npc-{npc_id}").start()

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

        def _on_corp_raid_check(event: Dict[str, Any]) -> None:
            """Detect Corp Raid events and emit district_alert to all clients."""
            payload = event.get("payload", {})
            title = payload.get("title") or event.get("title", "")
            event_type_str = payload.get("event_type", "") or event.get("event_type", "")
            lower = title.lower()
            if "corp raid" in lower or "corp_raid" in lower or "corp_raid" in event_type_str:
                try:
                    self.socketio.emit("district_alert", {
                        "type": "corp_raid",
                        "title": title,
                        "payload": payload,
                    })
                except Exception as exc:
                    logger.debug("district_alert emit failed: %s", exc)

        try:
            bus = self._event_bus
            self._bus_subs.extend([
                bus.subscribe(EventTypes.WORLD_EVENT, _on_world_event, "neoncity_scene"),
                bus.subscribe(EventTypes.NEONCITY_FACTION_SHIFT, _on_faction_shift, "neoncity_scene"),
                bus.subscribe(EventTypes.NEONCITY_WORLD_EVENT, _on_npc_action, "neoncity_scene"),
                bus.subscribe("world.world_event", _on_corp_raid_check, "neoncity_world_watch"),
            ])
            logger.info("NeonCity EventBus: %d subscriptions active.", len(self._bus_subs))
        except Exception as exc:
            logger.warning("EventBus subscription failed: %s", exc)

    # ------------------------------------------------------------------
    # BaseScene contract
    # ------------------------------------------------------------------

    # v1.44.0 [2026-03-21] — Start LivingWorld daemon + crew polling
    def start(self) -> None:
        """Start the NeonCity Flask/SocketIO server.

        Also starts the LivingWorld daemon (world events, faction AI,
        weather, NPC routines) and a crew operation auto-poller.
        """
        # Start the living world simulation
        try:
            from engine.world.living_world import get_living_world
            lw = get_living_world()
            lw.start()
            logger.info("LivingWorld daemon started from NeonCity")
        except Exception as exc:
            logger.warning("LivingWorld start failed: %s", exc)

        # Start crew operation auto-polling (every 60s)
        import threading

        def _crew_poll_loop() -> None:
            import time as _time
            while getattr(self, "_crew_poll_running", True):
                try:
                    cm = get_crew_manager()
                    completed = cm.check_operations()
                    if completed:
                        logger.info("Crew operations completed: %d", len(completed))
                        self.socketio.emit("hud_update", {"crew_ops_completed": len(completed)})
                except Exception:
                    pass
                _time.sleep(60)

        self._crew_poll_running = True
        threading.Thread(
            target=_crew_poll_loop, daemon=True, name="crew-poll",
        ).start()

        logger.info(
            'NeonCity v1.44 "Dark Renaissance" — Living World Hub starting on port %d',
            self.port,
        )
        self.socketio.run(
            self.app, host=self.host, port=self.port,
            debug=False, allow_unsafe_werkzeug=True,
        )

    def stop(self) -> None:
        """Tear down the scene and release all resources."""
        self._crew_poll_running = False
        try:
            from engine.world.living_world import get_living_world
            get_living_world().stop()
        except Exception:
            pass
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
