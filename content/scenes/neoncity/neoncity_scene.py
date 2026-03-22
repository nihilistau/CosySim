"""
NeonCity — Living World Hub v1.50 "Three Pillars"
===================================================

The city breathes.  Six factions fight for control.  The night never ends.

Multi-district living city hub wiring together the economy, reputation,
world-simulation, and content engines under the MCP v3.x framework.
Board-game mode (Glitch Storm) at ``/board``.
Cyberspace intrusion network at ``/cyberspace``.

Version: v1.50.0 [2026-03-22]

Change Log:
    v1.50.0 [2026-03-22] — Three Pillars overhaul: exchange_credits handler,
                            district scene_status endpoint, offline scene detection,
                            enhanced _build_city_state with faction standings/territory
    v1.46.0 [2026-03-21] — Rich event feed, board game overhaul,
                            cyberspace intrusion REST API + UI
    v1.45.0 [2026-03-21] — Playable dashboard: mission CRUD, crew ops,
                            shop route, fixed API bugs (dict double-serialise)
    v1.44.0 [2026-03-21] — 3-column dashboard, HUD sidebar panels
    v0.68   [2026-03-20] — Initial living world hub
"""
from __future__ import annotations

import json
import logging
import random
import socket as _socket
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import jsonify, render_template, request
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene
from engine.mcp.framework import get_framework
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
from engine.world.skill_progression import get_skill_manager
from engine.content.content_engine import get_content_engine
from engine.director.scene_director import get_scene_director
from content.shared import register_shared_assets
from content.scenes.neoncity.neoncity_rules import register_neoncity_rules

from engine.world.cyberspace import get_cyberspace_engine

from .neoncity_state import (
    EVENT_POOL,
    PREFAB_TYPES,
    NeonCityGameState,
)

logger = logging.getLogger(__name__)

SCENE_ID = "neoncity"
# v1.49.1 [2026-03-22] — Use port registry instead of hardcoded value
try:
    from engine.port_registry import get_port as _get_port
    DEFAULT_PORT = _get_port("neoncity", 5563)
except Exception:
    DEFAULT_PORT = 5563


# v1.50.0 [2026-03-22] — Port check utility for scene online detection
def _port_check(port: int) -> bool:
    """Quick TCP connect test to see if a port is listening.

    Args:
        port: TCP port number to check.

    Returns:
        True if a service is listening on ``127.0.0.1:port``.
    """
    try:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


# v1.52.0 [2026-03-22] — Consumable effects registry
# CONNECTS: PlayerState, SkillManager
# CALLED BY: api_inventory_use() when action == "use"
_CONSUMABLE_EFFECTS: Dict[str, Dict[str, Any]] = {
    # Drugs / Chems
    "stim_pack":      {"energy": 30, "message": "Stim Pack injected. +30 energy."},
    "health_booster": {"health": 25, "message": "Health Booster applied. +25 health."},
    "focus_chip":     {"message": "Focus Chip activated. Enhanced hacking and tech."},
    "black_lotus":    {"energy": 15, "health": 10, "heat": 5, "message": "Black Lotus consumed. Euphoric rush. +5 heat."},
    # Food
    "synth_ramen":    {"health": 10, "energy": 5, "message": "Synth Ramen consumed. +10 health, +5 energy."},
    "protein_bar":    {"energy": 10, "health": 5, "message": "Protein Bar consumed. +10 energy, +5 health."},
    "corp_ration":    {"health": 8, "energy": 3, "message": "Corp Ration consumed. +8 health."},
}


def _apply_consumable_effect(item_id: str) -> Dict[str, Any]:
    """Apply the effect of a consumable item to PlayerState.

    Args:
        item_id: Inventory item identifier.

    Returns:
        Dict describing what happened (message, stat changes).
    """
    effect = _CONSUMABLE_EFFECTS.get(item_id)
    if not effect:
        return {"message": f"Used {item_id}.", "changes": {}}

    ps = get_player_state()
    changes: Dict[str, int] = {}

    if "health" in effect:
        delta = effect["health"]
        ps.health = min(100, ps.health + delta)
        changes["health"] = delta

    if "energy" in effect:
        delta = effect["energy"]
        ps.energy = min(100, ps.energy + delta)
        changes["energy"] = delta

    if "heat" in effect:
        delta = effect["heat"]
        ps.heat = min(100, ps.heat + delta)
        changes["heat"] = delta

    # Persist the state change
    ps._save()

    logger.info("Consumable effect: %s → %s", item_id, changes)
    return {"message": effect["message"], "changes": changes}


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


# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class NeonCityScene(FlaskScene):
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
        super().__init__(host=host, port=port)

        self.app.config["SECRET_KEY"] = "neoncity_v083_social_layer"

        # v1.51.0 — FlaskScene registers health, hud, announcer, inventory, tts
        self.mount_overlay(self.app, self.socketio)
        self.mount_skills_server(self.app)
        self.register_bench_route(self.app, self.socketio)
        self.register_hack_route(self.app)
        self.register_world_events_route(self.app)
        # v1.45.0 [2026-03-21] — Enable shop buy/sell endpoints
        self.register_shop_route(self.app)

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

        # MCP rules
        register_neoncity_rules()

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

        # v1.50.0 [2026-03-22] — Enhanced faction snapshot with standings & territory
        # CONNECTS: PlayerState.faction_standings, ReputationManager
        ps = get_player_state()
        faction_standings = ps.faction_standings if hasattr(ps, "faction_standings") else {}

        factions: List[Dict[str, Any]] = []
        for name, data in _FACTIONS.items():
            standing_val = faction_standings.get(name, 0)
            if standing_val > 20:
                label = "Ally"
            elif standing_val < -20:
                label = "Enemy"
            else:
                label = "Neutral"
            factions.append({
                "name": name,
                "color": data["color"],
                "power": self._get_faction_power(name),
                "standing": standing_val,
                "label": label,
                "tag": data["tag"],
                "motto": data["motto"],
            })

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

        # v1.50.0 — Include district NPC lists for dynamic frontend updates
        district_data: Dict[str, Any] = {}
        for dkey, dinfo in _DISTRICTS.items():
            district_data[dkey] = {
                **dinfo,
                "npcs": dinfo.get("npcs", []),
            }

        return {
            "districts": district_data,
            "factions": factions,
            "faction_standings": dict(faction_standings),
            "world_time": world_time,
            "active_events": active_events,
            "credits": credits_balance,
            "scene_id": SCENE_ID,
            "version": "1.50",
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

        # v1.50.0 [2026-03-22] — District travel with offline scene detection
        # CONNECTS: CityMap, SCENE_PORTS, _port_check()
        # CALLED BY: NeonCityApp._enterDistrict() via REST
        @self.app.route("/api/district/enter", methods=["POST"])
        def enter_district():
            data = request.json or {}
            district_key = data.get("district", "")
            scene_name = _DISTRICT_TO_SCENE.get(district_key)
            if not scene_name:
                return jsonify({"success": False, "error": f"Unknown district: {district_key}"}), 400

            # Same-scene travel (street_level → NEON CITY)
            if scene_name == "NEON CITY":
                return jsonify({
                    "success": True,
                    "scene": scene_name,
                    "port": DEFAULT_PORT,
                    "url": None,
                    "is_running": True,
                    "same_scene": True,
                    "message": "You are already in Neon City.",
                    "energy_cost": 0,
                    "heat_add": 0,
                    "travel_time": 0,
                })

            try:
                from engine.world.city_map import get_city_map, SCENE_PORTS
                cm = get_city_map()
                result = cm.travel(scene_name)
                port = SCENE_PORTS.get(scene_name, 0)
                # v1.50.0 — Check if the target scene is actually running
                is_running = _port_check(port) if port else False
                return jsonify({
                    "success": result.success,
                    "scene": scene_name,
                    "port": port,
                    "url": f"http://localhost:{port}" if port else None,
                    "is_running": is_running,
                    "same_scene": False,
                    "message": result.message,
                    "energy_cost": result.energy_cost,
                    "heat_add": result.heat_add,
                    "travel_time": result.travel_time,
                })
            except Exception as exc:
                logger.warning("District travel failed: %s", exc)
                return jsonify({"success": False, "error": str(exc)}), 500

        # v1.50.0 [2026-03-22] — District scene online/offline status
        # CONNECTS: _DISTRICT_TO_SCENE, SCENE_PORTS, _port_check()
        # CALLED BY: NeonCityApp._updateDistrictStatuses() via REST
        @self.app.route("/api/district/scene_status")
        def district_scene_status():
            """Return online/offline status for each district's mapped scene."""
            from engine.world.city_map import SCENE_PORTS
            statuses: Dict[str, Dict[str, Any]] = {}
            for district_key, scene_name in _DISTRICT_TO_SCENE.items():
                port = SCENE_PORTS.get(scene_name, 0)
                # NeonCity itself is always "running"
                if scene_name == "NEON CITY":
                    is_running = True
                else:
                    is_running = _port_check(port) if port else False
                statuses[district_key] = {
                    "scene": scene_name,
                    "port": port,
                    "is_running": is_running,
                }
            return jsonify(statuses)

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

        # v1.52.0 [2026-03-22] — Consumable effects system
        # CONNECTS: InventoryManager, PlayerState, SkillManager
        # CALLED BY: NeonCityApp._useItem() via REST
        @self.app.route("/api/inventory/use", methods=["POST"])
        def api_inventory_use():
            """Use, equip, unequip, or sell an inventory item.

            For consumables (drugs/food), applying the item's effect
            to PlayerState before removing it from inventory.
            """
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
                    # v1.52.0 — Apply consumable effects before removing
                    effect = _apply_consumable_effect(item_id)
                    inv.remove_item(item_id, 1)
                    return jsonify({"ok": True, "effect": effect})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        # v1.52.0 [2026-03-22] — NPC Relationship API
        # CONNECTS: ReputationManager, CharacterRegistry
        # CALLED BY: NeonCityApp._loadRelationships() via REST
        @self.app.route("/api/relationships")
        def api_relationships():
            """Return player's relationship standings with all known NPCs and factions."""
            try:
                rep = get_reputation_manager()
                entries = rep.get_all_entries("player")
                result = []
                for entry in entries:
                    result.append({
                        "id": entry.entity_id,
                        "name": getattr(entry, "display_name", entry.entity_id),
                        "standing": entry.standing,
                        "label": entry.label,
                        "tier": entry.tier,
                        "history": [
                            {"delta": h.delta, "reason": h.reason}
                            for h in (entry.history or [])[-5:]
                        ],
                    })
                return jsonify({"ok": True, "relationships": result})
            except Exception as exc:
                logger.debug("Relationships API error: %s", exc)
                return jsonify({"ok": True, "relationships": []})

        # v1.52.0 [2026-03-22] — Dynamic Territory Mission Generation
        # CONNECTS: TerritoryManager, MissionManager, faction state
        # CALLED BY: NeonCityApp via REST (on demand or periodic)
        @self.app.route("/api/missions/generate", methods=["POST"])
        def api_generate_mission():
            """Generate a dynamic mission based on current territory/faction state."""
            try:
                from engine.world.territory import get_territory_manager
                tm = get_territory_manager()
                mm = get_mission_manager()
                ps = get_player_state()

                # Pick a faction conflict zone for the mission
                import random as _rng
                districts = list(tm.get_all_control().items())
                if not districts:
                    return jsonify({"ok": False, "error": "No territory data available."})

                district_name, control = _rng.choice(districts)
                # Find the weakest and strongest faction in this district
                sorted_factions = sorted(control.items(), key=lambda x: x[1], reverse=True)
                dominant = sorted_factions[0][0] if sorted_factions else "Unknown"
                weakest = sorted_factions[-1][0] if len(sorted_factions) > 1 else dominant

                # Generate mission type based on player standing
                player_standing = ps.faction_standings.get(dominant, 0) if hasattr(ps, "faction_standings") else 0
                mission_types = [
                    ("CAPTURE", f"Seize control of {district_name} from {dominant}", "recon"),
                    ("DEFEND", f"Defend {district_name} against {weakest} expansion", "extraction"),
                    ("SABOTAGE", f"Sabotage {dominant}'s operations in {district_name}", "heist"),
                    ("RECON", f"Gather intelligence on {dominant} in {district_name}", "recon"),
                ]
                mtype, desc, category = _rng.choice(mission_types)
                difficulty = _rng.randint(2, 4)
                credits_reward = 500 + difficulty * 300
                xp_reward = 50 + difficulty * 25

                mission_id = f"territory_{district_name.lower().replace(' ', '_')}_{int(time.time()) % 10000}"
                result = mm.create(
                    mission_id=mission_id,
                    title=f"{mtype}: {district_name}",
                    description=desc,
                    mission_type=category,
                    difficulty=difficulty,
                    giver_npc=dominant,
                    location=district_name,
                    objectives=[
                        f"Infiltrate {district_name}",
                        f"Complete {mtype.lower()} objective",
                        f"Extract without detection",
                    ],
                    rewards={
                        "credits": credits_reward,
                        "xp": xp_reward,
                        "reputation": difficulty * 2,
                        "faction_rep": difficulty * 3 if player_standing < 0 else difficulty,
                        "faction": weakest if mtype == "CAPTURE" else dominant,
                    },
                )
                return jsonify({
                    "ok": True,
                    "mission_id": mission_id,
                    "title": f"{mtype}: {district_name}",
                    "message": f"New territory mission available: {mtype} in {district_name}",
                })
            except Exception as exc:
                logger.error("Mission generation failed: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 500

        # v1.52.0 [2026-03-22] — NPC Gift/Favor System
        # CONNECTS: ReputationManager, InventoryManager, PlayerState
        # CALLED BY: NeonCityApp.giftNpc() via REST
        # EMITS: reputation change, inventory removal
        @self.app.route("/api/npc/gift", methods=["POST"])
        def api_npc_gift():
            """Gift an item to an NPC to improve relationship standing.

            Removes the item from inventory and increases standing with
            the NPC by an amount based on item value.
            """
            data = request.get_json(force=True) or {}
            npc_id = data.get("npc_id", "")
            item_id = data.get("item_id", "")

            if not npc_id or not item_id:
                return jsonify({"ok": False, "error": "npc_id and item_id required"}), 400

            try:
                inv = get_inventory()
                ps = get_player_state()
                rep = get_reputation_manager()

                # Check item exists in inventory
                item = inv.get_item(item_id)
                if not item:
                    return jsonify({"ok": False, "error": f"You don't have {item_id}."}), 400

                # Calculate standing boost based on item sell price
                price = getattr(item, "sell_price", 0) or getattr(item, "price", 50) or 50
                standing_boost = max(3, min(20, price // 25))

                # Remove item from inventory
                inv.remove_item(item_id, 1)

                # Increase standing with NPC
                rep.adjust(npc_id, "player", standing_boost, reason=f"gift:{item_id}")
                new_entry = rep.get_entry(npc_id, "player")
                new_standing = new_entry.standing if new_entry else 0
                new_label = new_entry.label if new_entry else "Neutral"

                item_name = getattr(item, "name", item_id)
                logger.info("Gift: %s → %s (+%d standing, now %d/%s)",
                            item_name, npc_id, standing_boost, new_standing, new_label)

                can_recruit = new_standing >= 40
                return jsonify({
                    "ok": True,
                    "npc_id": npc_id,
                    "item": item_name,
                    "standing_boost": standing_boost,
                    "new_standing": new_standing,
                    "new_label": new_label,
                    "can_recruit": can_recruit,
                    "message": (
                        f"Gifted {item_name} to {npc_id}. +{standing_boost} standing "
                        f"(now {new_standing}: {new_label})."
                        + (" Ready to recruit!" if can_recruit else "")
                    ),
                })
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @self.app.route("/api/crew")
        def api_crew():
            """Full crew state — members, operations, roles."""
            try:
                cm = get_crew_manager()
                return jsonify(cm.to_dict())
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
                ok, msg = cm.recruit(char_id, role)
                return jsonify({"ok": ok, "message": msg})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        # v1.45.0 [2026-03-21] — Crew dismiss + start operation routes
        @self.app.route("/api/crew/dismiss", methods=["POST"])
        def api_crew_dismiss():
            """Dismiss a crew member."""
            data = request.get_json(force=True) or {}
            char_id = data.get("character_id", "")
            reason = data.get("reason", "")
            try:
                cm = get_crew_manager()
                ok = cm.dismiss(char_id, reason=reason)
                if ok:
                    return jsonify({"ok": True, "message": f"{char_id} has left the crew."})
                return jsonify({"ok": False, "error": f"{char_id} not found in crew."}), 404
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @self.app.route("/api/crew/start_op", methods=["POST"])
        def api_crew_start_op():
            """Launch a crew operation."""
            data = request.get_json(force=True) or {}
            op_type = data.get("op_type", "")
            crew_ids = data.get("crew_ids", [])
            label = data.get("label", "")
            duration = int(data.get("duration_secs", 3600))
            reward_credits = int(data.get("reward_credits", 500))
            reward_xp = int(data.get("reward_xp", 25))
            try:
                cm = get_crew_manager()
                ok, msg = cm.start_operation(
                    op_type, crew_ids,
                    label=label,
                    duration_secs=duration,
                    reward_credits=reward_credits,
                    reward_xp=reward_xp,
                )
                return jsonify({"ok": ok, "message": msg})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @self.app.route("/api/crew/check_ops", methods=["POST"])
        def api_crew_check_ops():
            """Check and resolve completed crew operations."""
            try:
                cm = get_crew_manager()
                completed = cm.check_operations()
                return jsonify({"ok": True, "completed": completed})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @self.app.route("/api/missions")
        def api_missions():
            """Mission board — available + active missions."""
            try:
                mm = get_mission_manager()
                return jsonify({
                    "available": mm.list_available(),
                    "active": mm.list_active(),
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
                result = mm.accept(mission_id)
                return jsonify({"ok": result["success"], "message": result["message"]})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        # v1.45.0 [2026-03-21] — Mission detail, complete, abandon, objective routes
        @self.app.route("/api/missions/<mission_id>")
        def api_mission_detail(mission_id):
            """Get full mission detail by ID."""
            try:
                mm = get_mission_manager()
                m = mm.get_mission(mission_id)
                if not m:
                    return jsonify({"error": "Mission not found"}), 404
                return jsonify(m.to_dict())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/missions/complete", methods=["POST"])
        def api_missions_complete():
            """Complete an active mission and collect rewards."""
            data = request.get_json(force=True) or {}
            mission_id = data.get("mission_id", "")
            notes = data.get("notes", "")
            try:
                mm = get_mission_manager()
                result = mm.complete(mission_id, notes=notes)
                return jsonify({
                    "ok": result["success"],
                    "message": result["message"],
                    "rewards": result.get("rewards"),
                })
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @self.app.route("/api/missions/abandon", methods=["POST"])
        def api_missions_abandon():
            """Abandon an active mission (-3 rep penalty)."""
            data = request.get_json(force=True) or {}
            mission_id = data.get("mission_id", "")
            try:
                mm = get_mission_manager()
                result = mm.abandon(mission_id)
                return jsonify({"ok": result["success"], "message": result["message"]})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @self.app.route("/api/missions/objective", methods=["POST"])
        def api_missions_objective():
            """Mark a single mission objective as completed."""
            data = request.get_json(force=True) or {}
            mission_id = data.get("mission_id", "")
            objective_id = data.get("objective_id", "")
            try:
                mm = get_mission_manager()
                result = mm.complete_objective(mission_id, objective_id)
                return jsonify({
                    "ok": result["success"],
                    "message": result.get("message", ""),
                    "progress": result.get("progress"),
                })
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        # v1.45.0 [2026-03-21] — Skill progression API
        @self.app.route("/api/skills")
        def api_skills():
            """Full skill progression state (8 skills, XP, levels)."""
            try:
                sm = get_skill_manager()
                return jsonify(sm.to_dict())
            except Exception as exc:
                logger.error("Skills API error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/hud")
        def api_hud():
            """Combined HUD data — player + inventory + crew + missions + skills."""
            try:
                ps = get_player_state()
                inv = get_inventory()
                cm = get_crew_manager()
                mm = get_mission_manager()
                sm = get_skill_manager()
                return jsonify({
                    "player": ps.to_dict(),
                    "inventory": inv.to_hud_dict(),
                    "equipped": inv.get_equipped(),
                    "crew": cm.to_dict(),
                    "missions": {
                        "available": mm.list_available(),
                        "active": mm.list_active(),
                    },
                    "skills": sm.to_dict(),
                    "balance": get_economy_manager().get_balance("player"),
                })
            except Exception as exc:
                logger.error("HUD API error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        # ── v1.46.0 [2026-03-21] — Cyberspace intrusion REST API ────────
        # CONNECTS: CyberspaceEngine, neoncity_cyberspace.html
        # CALLED BY: neoncity-cyberspace.js fetch() calls
        # EMITS: JSON responses for network graph UI

        @self.app.route("/cyberspace")
        def cyberspace_ui():
            return render_template("neoncity_cyberspace.html")

        @self.app.route("/api/cyberspace/networks")
        def cs_list_networks():
            """List available networks with summary info."""
            try:
                cs = get_cyberspace_engine()
                return jsonify({"networks": cs.list_networks()})
            except Exception as exc:
                logger.error("Cyberspace list_networks error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/cyberspace/network/<network_id>")
        def cs_get_network(network_id: str):
            """Full network topology for visualization."""
            try:
                cs = get_cyberspace_engine()
                net = cs.get_network_map(network_id)
                if not net:
                    return jsonify({"error": "Network not found"}), 404
                return jsonify(net)
            except Exception as exc:
                logger.error("Cyberspace get_network error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/cyberspace/generate", methods=["POST"])
        def cs_generate():
            """Generate a network from template."""
            data = request.get_json(force=True) or {}
            nid = data.get("network_id", "")
            diff = int(data.get("difficulty", 1))
            force = data.get("force", False)
            try:
                cs = get_cyberspace_engine()
                result = cs.generate_network(nid, difficulty=diff, force=force)
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/cyberspace/jack_in", methods=["POST"])
        def cs_jack_in():
            """Start an intrusion session."""
            data = request.get_json(force=True) or {}
            nid = data.get("network_id", "")
            programs = data.get("programs")
            try:
                cs = get_cyberspace_engine()
                result = cs.jack_in(nid, programs=programs)
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/cyberspace/move", methods=["POST"])
        def cs_move():
            """Move to an adjacent node."""
            data = request.get_json(force=True) or {}
            sid = data.get("session_id", "")
            target = data.get("target_node", "")
            try:
                cs = get_cyberspace_engine()
                result = cs.move_to(sid, target)
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/cyberspace/scan", methods=["POST"])
        def cs_scan():
            """Scan the current node."""
            data = request.get_json(force=True) or {}
            sid = data.get("session_id", "")
            try:
                cs = get_cyberspace_engine()
                result = cs.scan_node(sid)
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/cyberspace/use_program", methods=["POST"])
        def cs_use_program():
            """Use a loaded program."""
            data = request.get_json(force=True) or {}
            sid = data.get("session_id", "")
            pid = data.get("program_id", "")
            ice_id = data.get("target_ice_id")
            node_id = data.get("target_node_id")
            try:
                cs = get_cyberspace_engine()
                result = cs.use_program(sid, pid,
                                        target_ice_id=ice_id,
                                        target_node_id=node_id)
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/cyberspace/extract", methods=["POST"])
        def cs_extract():
            """Extract data from current node."""
            data = request.get_json(force=True) or {}
            sid = data.get("session_id", "")
            data_id = data.get("data_id")
            try:
                cs = get_cyberspace_engine()
                result = cs.extract_data(sid, data_id=data_id)
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/cyberspace/jack_out", methods=["POST"])
        def cs_jack_out():
            """Disconnect from session."""
            data = request.get_json(force=True) or {}
            sid = data.get("session_id", "")
            try:
                cs = get_cyberspace_engine()
                result = cs.jack_out(sid)
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/cyberspace/session/<session_id>")
        def cs_session(session_id: str):
            """Get current session state."""
            try:
                cs = get_cyberspace_engine()
                result = cs.get_session(session_id)
                if not result:
                    return jsonify({"error": "Session not found"}), 404
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/cyberspace/deck")
        def cs_deck():
            """Get cyberdeck state."""
            try:
                cs = get_cyberspace_engine()
                deck = cs._cyberdeck
                return jsonify({
                    "deck_id": deck.deck_id,
                    "ram_total": deck.ram_total,
                    "ram_used": deck.ram_used,
                    "ram_damage": deck.ram_damage,
                    "ram_available": deck.ram_available,
                    "cpu_speed": deck.cpu_speed,
                    "max_programs": deck.max_programs,
                    "installed_programs": deck.installed_programs,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/cyberspace/stats")
        def cs_stats():
            """Global cyberspace career stats."""
            try:
                cs = get_cyberspace_engine()
                return jsonify(cs.get_stats())
            except Exception as exc:
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

        # v1.46.0 [2026-03-21] — Rich event cards with type, impacts, actor
        @self.socketio.on("get_world_events")
        def on_get_world_events(_data=None):
            """Emit WorldSim digest for neoncity with rich event metadata.

            Each event includes title, event_type, scene, actor, intensity,
            economy/heat/rep impacts, and created_at for the enhanced event
            feed UI (color-coded cards, severity indicators).

            Args:
                _data: Unused.
            """
            events: List[Dict[str, Any]] = []
            try:
                for ev in get_world_sim().get_all_events(limit=20):
                    payload = getattr(ev, "payload", {}) or {}
                    events.append({
                        "id": getattr(ev, "id", ""),
                        "title": getattr(ev, "title", ""),
                        "description": getattr(ev, "description", str(ev)),
                        "event_type": getattr(ev, "event_type", "").value
                            if hasattr(getattr(ev, "event_type", ""), "value")
                            else str(getattr(ev, "event_type", "")),
                        "scene": getattr(ev, "scene", SCENE_ID),
                        "actor": getattr(ev, "actor", ""),
                        "intensity": getattr(ev, "intensity", 1.0),
                        "economy_impact": payload.get("economy_impact", 0),
                        "heat_impact": payload.get("heat_impact", 0),
                        "rep_impact": payload.get("rep_impact", 0),
                        "faction": payload.get("faction", ""),
                        "created_at": getattr(ev, "created_at", ""),
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

        # v1.50.0 [2026-03-22] — Exchange credits (deposit/withdraw)
        # CONNECTS: EconomyManager, PlayerState
        # CALLED BY: NeonCityApp.doExchange() via Socket.IO
        # EMITS: exchange_result, hud_update, error
        @self.socketio.on("exchange_credits")
        def on_exchange_credits(data: Dict[str, Any]):
            """Exchange credits between player wallet and bank.

            Args:
                data: Dict with ``amount`` (int) and ``direction``
                      ('in' = deposit, 'out' = withdraw).
            """
            amount = max(0, int((data or {}).get("amount", 0)))
            direction = (data or {}).get("direction", "in")

            if amount <= 0:
                emit("error", {"message": "Invalid amount."})
                return

            try:
                ps = get_player_state()
                economy = get_economy_manager()
                current_balance = economy.get_balance("player")
                wallet = ps.credits

                if direction == "in":
                    # Deposit: move from wallet to bank
                    if wallet < amount:
                        emit("exchange_result", {
                            "success": False,
                            "error": f"Insufficient wallet funds. Have ₵{wallet}, need ₵{amount}.",
                            "balance": current_balance,
                            "wallet": wallet,
                        })
                        return
                    ps.spend_credits(amount, reason="bank_deposit")
                    economy.transact(amount, TransactionType.EARN, SCENE_ID, "bank_deposit")
                else:
                    # Withdraw: move from bank to wallet
                    if current_balance < amount:
                        emit("exchange_result", {
                            "success": False,
                            "error": f"Insufficient bank balance. Have ₵{current_balance}, need ₵{amount}.",
                            "balance": current_balance,
                            "wallet": wallet,
                        })
                        return
                    economy.transact(-amount, TransactionType.SPEND, SCENE_ID, "bank_withdrawal")
                    ps.earn_credits(amount, reason="bank_withdrawal")

                new_balance = economy.get_balance("player")
                new_wallet = ps.credits
                action = "deposited" if direction == "in" else "withdrew"
                logger.info("Exchange: %s ₵%d (bank=%d, wallet=%d)", action, amount, new_balance, new_wallet)

                emit("exchange_result", {
                    "success": True,
                    "action": action,
                    "amount": amount,
                    "balance": new_balance,
                    "wallet": new_wallet,
                    "message": f"Successfully {action} ₵{amount}.",
                })
                # Also emit hud_update so all panels refresh
                emit("hud_update", {
                    "credits": new_wallet,
                    "bank_balance": new_balance,
                })
            except Exception as exc:
                logger.warning("exchange_credits failed: %s", exc)
                emit("error", {"message": f"Exchange failed: {exc}"})

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
    # v1.51.0 [2026-03-22] — Lifecycle delegated to FlaskScene

    def on_before_serve(self) -> None:
        """Hook: start LivingWorld daemon and crew auto-poller before serving."""
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
                # v1.52.0 — Check for expired missions on each poll tick
                try:
                    mm = get_mission_manager()
                    expired = mm.check_expired()
                    for m in expired:
                        self.socketio.emit("city_event", {
                            "type": "mission_failed",
                            "payload": {
                                "npc_id": "MISSIONS",
                                "description": f"MISSION FAILED: {m['title']} — time expired!",
                            },
                        })
                except Exception:
                    pass
                _time.sleep(60)

        self._crew_poll_running = True
        threading.Thread(
            target=_crew_poll_loop, daemon=True, name="crew-poll",
        ).start()

    # ── Cross-Scene Arrival ─────────────────────────────────────────
    # v1.52.0 [2026-03-22] — Travel log + city welcome on arrival
    # CONNECTS: FlaskScene.on_player_arrival(), city_map.travel()

    def on_player_arrival(self, from_location: str, travel_data: Dict[str, Any]) -> None:
        """Log player arrival in the city chat and broadcast welcome."""
        energy_cost = travel_data.get("energy_cost", 0)
        heat_add = travel_data.get("heat_add", 0)
        costs = []
        if energy_cost:
            costs.append(f"-{energy_cost} EN")
        if heat_add:
            costs.append(f"+{heat_add} HT")
        cost_str = f" ({', '.join(costs)})" if costs else ""

        try:
            self.socketio.emit("city_event", {
                "type": "arrival",
                "payload": {
                    "npc_id": "CITY",
                    "description": f"Arrived from {from_location}.{cost_str} Welcome back to Neon City.",
                },
            })
        except Exception as exc:
            logger.debug("NeonCity arrival broadcast failed: %s", exc)

    def on_shutdown(self) -> None:
        """Hook: stop crew poller, LivingWorld, and unsubscribe events."""
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
