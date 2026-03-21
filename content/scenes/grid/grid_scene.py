"""THE GRID — CosySim v0.75 "NEON CITY".

The underground marketplace, travel hub, faction den, and information broker
of Neon City.  Port 5569.

Four zones accessible via tab navigation:

- **MARKET** — buy/sell items with fluctuating prices tied to economy events
- **STATION** — SVG travel map showing all live scene locations
- **DEN** — faction headquarters, allegiance pledging, faction quests
- **BROKER** — Nexus-powered intel trading and 0xGH0ST terminal

All zones react to the living world via Socket.IO and the EventCascade.
"""
from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Any, Dict, List, Optional

from flask import Flask, Response, json, request
from flask_socketio import SocketIO

from engine.scenes.base_scene import BaseScene
from engine.skills.skill import skill
from content.shared import register_shared_assets

logger = logging.getLogger(__name__)

# ──── Catalogue ──────────────────────────────────────────────────────────────

MARKET_CATALOGUE: List[Dict[str, Any]] = [
    # Tech (Mira)
    {"id": "stim_v1",    "name": "Stim-Pack v1",      "vendor": "mira",   "category": "tech",        "base_price": 120,  "stock": 10, "rarity": "common"},
    {"id": "data_chip",  "name": "Data Chip",          "vendor": "mira",   "category": "tech",        "base_price": 250,  "stock": 5,  "rarity": "uncommon"},
    {"id": "jammer",     "name": "Signal Jammer",      "vendor": "mira",   "category": "tech",        "base_price": 600,  "stock": 2,  "rarity": "rare"},
    {"id": "neural_tap", "name": "Neural Tap",         "vendor": "mira",   "category": "tech",        "base_price": 1200, "stock": 1,  "rarity": "legendary"},
    {"id": "dec_key",    "name": "Decrypt Key",        "vendor": "mira",   "category": "tech",        "base_price": 350,  "stock": 3,  "rarity": "uncommon"},
    # Contraband (Viktor)
    {"id": "ghost_id",   "name": "Ghost ID",           "vendor": "viktor", "category": "contraband",  "base_price": 800,  "stock": 4,  "rarity": "rare"},
    {"id": "exp_round",  "name": "Explosive Rounds",   "vendor": "viktor", "category": "contraband",  "base_price": 450,  "stock": 6,  "rarity": "uncommon"},
    {"id": "holo_mask",  "name": "Holo Mask",          "vendor": "viktor", "category": "contraband",  "base_price": 1100, "stock": 2,  "rarity": "rare"},
    {"id": "corp_key",   "name": "Corp Access Card",   "vendor": "viktor", "category": "contraband",  "base_price": 2000, "stock": 1,  "rarity": "legendary"},
    {"id": "wire_tap",   "name": "Wire-Tap Device",    "vendor": "viktor", "category": "contraband",  "base_price": 320,  "stock": 5,  "rarity": "uncommon"},
    # Meds/Stims (Frankie)
    {"id": "nano_heal",  "name": "Nano-Healer",        "vendor": "frankie","category": "meds",        "base_price": 180,  "stock": 8,  "rarity": "common"},
    {"id": "rush_dose",  "name": "Rush Dose",          "vendor": "frankie","category": "meds",        "base_price": 80,   "stock": 15, "rarity": "common"},
    {"id": "trauma_kit", "name": "Trauma Kit",         "vendor": "frankie","category": "meds",        "base_price": 450,  "stock": 3,  "rarity": "uncommon"},
    {"id": "synth_calm", "name": "Synth-Calm",         "vendor": "frankie","category": "meds",        "base_price": 200,  "stock": 6,  "rarity": "common"},
    {"id": "blackout_p", "name": "Blackout Patch",     "vendor": "frankie","category": "meds",        "base_price": 550,  "stock": 2,  "rarity": "rare"},
    # Information
    {"id": "tip_bunker", "name": "Bunker Location Tip","vendor": "broker", "category": "intel",       "base_price": 750,  "stock": 3,  "rarity": "rare"},
    {"id": "tip_route",  "name": "Safe Route Map",     "vendor": "broker", "category": "intel",       "base_price": 300,  "stock": 5,  "rarity": "uncommon"},
]

FACTION_DATA: List[Dict[str, Any]] = [
    {"id": "OmniCorp",    "label": "OmniCorp",    "accent": "#3b82f6",  "archetype": "megacorp"},
    {"id": "NeoTech",     "label": "NeoTech",     "accent": "#8b5cf6",  "archetype": "corp"},
    {"id": "BlackMarket", "label": "BlackMarket", "accent": "#ef4444",  "archetype": "syndicate"},
    {"id": "Ghost_Net",   "label": "Ghost Net",   "accent": "#06b6d4",  "archetype": "hacker"},
    {"id": "SynthSec",    "label": "SynthSec",    "accent": "#f59e0b",  "archetype": "security"},
    {"id": "DeepState",   "label": "DeepState",   "accent": "#a3a3a3",  "archetype": "shadow"},
]

FACTION_QUESTS: List[Dict[str, Any]] = [
    {"faction": "OmniCorp",    "title": "Data Retrieval",     "desc": "Recover a stolen OmniCorp data cache from the black market.", "reward_credits": 1500, "reward_rep": 8},
    {"faction": "NeoTech",     "title": "Prototype Recovery", "desc": "Locate a stolen NeoTech neural prototype before it's sold.", "reward_credits": 1200, "reward_rep": 7},
    {"faction": "BlackMarket", "title": "Moving Day",         "desc": "Help shift a warehouse of hot goods before the sweep.", "reward_credits": 800,  "reward_rep": 5, "heat_cost": 10},
    {"faction": "Ghost_Net",   "title": "Signal Boost",       "desc": "Install a relay node on a corp tower — without being seen.", "reward_credits": 600,  "reward_rep": 6},
    {"faction": "SynthSec",    "title": "Bounty Hunt",        "desc": "Locate and tag a wanted hacker operating in the Grid.", "reward_credits": 1000, "reward_rep": 7, "heat_cost": 5},
    {"faction": "DeepState",   "title": "Dead Drop",          "desc": "Deliver an encrypted drive to a contact. Ask no questions.", "reward_credits": 2000, "reward_rep": 3},
]

# Scene map for THE STATION — all known scene ports
CITY_MAP_NODES: List[Dict[str, Any]] = [
    {"key": "bedroom",  "label": "THE PENTHOUSE",   "port": 5556, "x": 72, "y": 15,  "accent": "#c084fc"},
    {"key": "phone",    "label": "SIGNAL",          "port": 5555, "x": 18, "y": 15,  "accent": "#00e5ff"},
    {"key": "lounge",   "label": "VELVET PIT",      "port": 5557, "x": 50, "y": 30,  "accent": "#f43f5e"},
    {"key": "tavern",   "label": "RUSTY ANCHOR",    "port": 5558, "x": 25, "y": 45,  "accent": "#f97316"},
    {"key": "casino",   "label": "CLUB NOIR",       "port": 5559, "x": 70, "y": 45,  "accent": "#eab308"},
    {"key": "gallery",  "label": "THE OBSCURA",     "port": 5560, "x": 12, "y": 60,  "accent": "#a78bfa"},
    {"key": "arena",    "label": "COLOSSEUM",       "port": 5561, "x": 85, "y": 60,  "accent": "#22c55e"},
    {"key": "realm",    "label": "SHATTERED THRONE","port": 5562, "x": 40, "y": 72,  "accent": "#e879f9"},
    {"key": "neoncity", "label": "NEON CITY",       "port": 5563, "x": 55, "y": 55,  "accent": "#00e5ff"},
    {"key": "coders",   "label": "THE LAB",         "port": 5564, "x": 30, "y": 82,  "accent": "#34d399"},
    {"key": "heist",    "label": "THE SCORE",       "port": 5565, "x": 65, "y": 80,  "accent": "#e11d48"},
    {"key": "games",    "label": "THE ARCADE",      "port": 5567, "x": 45, "y": 88,  "accent": "#fb7185"},
    {"key": "grid",     "label": "THE GRID",        "port": 5569, "x": 50, "y": 50,  "accent": "#00ff88", "is_current": True},
    {"key": "intel",    "label": "THE BRIEFING",    "port": 5580, "x": 80, "y": 25,  "accent": "#38bdf8"},
    {"key": "hub",      "label": "THE LOFT",        "port": 8500, "x": 50, "y": 5,   "accent": "#94a3b8"},
]


# ──── GridState singleton ─────────────────────────────────────────────────────

class _GridState:
    """Runtime state for THE GRID scene — market prices, inventory, quests."""

    def __init__(self) -> None:
        self._prices: Dict[str, float] = {item["id"]: float(item["base_price"]) for item in MARKET_CATALOGUE}
        self._stock: Dict[str, int] = {item["id"]: item["stock"] for item in MARKET_CATALOGUE}
        self._player_inventory: List[Dict[str, Any]] = []
        self._active_quest: Optional[str] = None  # faction id with active quest
        self._quest_complete: Dict[str, bool] = {}
        self._intel_feed: List[Dict[str, Any]] = []
        self._price_trend: Dict[str, str] = {item["id"]: "stable" for item in MARKET_CATALOGUE}

    # ── Market ────────────────────────────────────────────────────────────────

    def get_market_items(self) -> List[Dict[str, Any]]:
        """Return current market catalogue with live prices."""
        items = []
        for item in MARKET_CATALOGUE:
            iid = item["id"]
            items.append({
                **item,
                "price": int(self._prices[iid]),
                "stock": self._stock[iid],
                "trend": self._price_trend[iid],
            })
        return items

    def buy_item(self, item_id: str, quantity: int = 1) -> Dict[str, Any]:
        """Process a purchase. Returns result dict."""
        item = next((i for i in MARKET_CATALOGUE if i["id"] == item_id), None)
        if not item:
            return {"success": False, "error": "Item not found."}
        price = int(self._prices[item_id])
        total = price * quantity
        stock = self._stock[item_id]
        if stock < quantity:
            return {"success": False, "error": f"Insufficient stock ({stock} available)."}
        try:
            from engine.world.player_state import get_player_state
            ps = get_player_state()
            if ps.credits < total:
                return {"success": False, "error": f"Insufficient credits (need ₵{total:,})."}
            ps.spend_credits(total, f"grid_buy:{item_id}")
        except Exception:
            pass  # PlayerState optional
        self._stock[item_id] = max(0, stock - quantity)
        self._player_inventory.append({"item_id": item_id, "name": item["name"], "qty": quantity, "paid": total})
        return {"success": True, "item": item["name"], "quantity": quantity, "paid": total, "remaining_stock": self._stock[item_id]}

    def sell_item(self, item_id: str, quantity: int = 1) -> Dict[str, Any]:
        """Process a sale of player inventory."""
        owned = sum(e["qty"] for e in self._player_inventory if e["item_id"] == item_id)
        if owned < quantity:
            return {"success": False, "error": f"You only own {owned} of that item."}
        item = next((i for i in MARKET_CATALOGUE if i["id"] == item_id), None)
        if not item:
            return {"success": False, "error": "Item not found."}
        sell_price = int(self._prices[item_id] * 0.65)  # 65 % sell-back rate
        total = sell_price * quantity
        try:
            from engine.world.player_state import get_player_state
            get_player_state().earn_credits(total, f"grid_sell:{item_id}")
        except Exception:
            pass
        # Remove from inventory
        remaining = quantity
        new_inv = []
        for e in self._player_inventory:
            if e["item_id"] == item_id and remaining > 0:
                taken = min(e["qty"], remaining)
                remaining -= taken
                if e["qty"] - taken > 0:
                    new_inv.append({**e, "qty": e["qty"] - taken})
            else:
                new_inv.append(e)
        self._player_inventory = new_inv
        self._stock[item_id] = min(self._stock[item_id] + quantity, item["stock"])
        return {"success": True, "item": item["name"], "quantity": quantity, "earned": total}

    def economy_shock(self, event_type: str, economy_impact: int) -> List[Dict[str, Any]]:
        """Apply an economy event to market prices.  Returns list of changed items."""
        changed = []
        for item in MARKET_CATALOGUE:
            iid = item["id"]
            base = float(item["base_price"])
            factor = 1.0
            if event_type in ("market_crash", "corp_tax", "blackout"):
                factor = random.uniform(0.75, 0.95)  # prices drop
                self._price_trend[iid] = "falling"
            elif event_type in ("black_market_sale", "corp_raid"):
                factor = random.uniform(1.05, 1.30)  # prices spike
                self._price_trend[iid] = "rising"
            elif event_type == "festival":
                if item["category"] in ("meds", "tech"):
                    factor = random.uniform(0.85, 0.95)
                    self._price_trend[iid] = "falling"
            else:
                factor = random.uniform(0.95, 1.05)
                self._price_trend[iid] = "stable"
            new_price = max(1, int(base * factor))
            if new_price != int(self._prices[iid]):
                self._prices[iid] = float(new_price)
                changed.append({"id": iid, "price": new_price, "trend": self._price_trend[iid]})
        return changed

    # ── Faction ───────────────────────────────────────────────────────────────

    def pledge_allegiance(self, faction_id: str) -> Dict[str, Any]:
        """Pledge allegiance to a faction."""
        faction = next((f for f in FACTION_DATA if f["id"] == faction_id), None)
        if not faction:
            return {"success": False, "error": "Unknown faction."}
        rivals = {
            "OmniCorp": ["BlackMarket", "Ghost_Net"],
            "BlackMarket": ["OmniCorp", "SynthSec"],
            "Ghost_Net": ["OmniCorp", "DeepState"],
            "SynthSec": ["BlackMarket"],
            "NeoTech": ["Ghost_Net"],
            "DeepState": [],
        }
        rep_gain = 15
        rival_loss = 8
        try:
            from engine.world.player_state import get_player_state
            ps = get_player_state()
            ps.update_faction_standing(faction_id, rep_gain)
            for rival in rivals.get(faction_id, []):
                ps.update_faction_standing(rival, -rival_loss)
        except Exception:
            pass
        return {
            "success": True,
            "faction": faction_id,
            "rep_gained": rep_gain,
            "rivals_lost": rival_loss,
            "message": f"Allegiance pledged to {faction['label']}. Rivals grow hostile.",
        }

    def accept_quest(self, faction_id: str) -> Dict[str, Any]:
        """Accept the faction quest for *faction_id*."""
        quest = next((q for q in FACTION_QUESTS if q["faction"] == faction_id), None)
        if not quest:
            return {"success": False, "error": "No quest available for that faction."}
        if self._quest_complete.get(faction_id):
            return {"success": False, "error": "Quest already completed."}
        self._active_quest = faction_id
        return {"success": True, "quest": quest}

    def complete_quest(self, faction_id: str) -> Dict[str, Any]:
        """Mark the faction quest as complete and award the player."""
        quest = next((q for q in FACTION_QUESTS if q["faction"] == faction_id), None)
        if not quest:
            return {"success": False, "error": "Quest not found."}
        if faction_id != self._active_quest:
            return {"success": False, "error": "No active quest for this faction."}
        self._quest_complete[faction_id] = True
        self._active_quest = None
        try:
            from engine.world.player_state import get_player_state
            ps = get_player_state()
            ps.earn_credits(quest["reward_credits"], f"quest_{faction_id}")
            ps.update_reputation(quest["reward_rep"], f"quest_{faction_id}")
            if quest.get("heat_cost"):
                ps.adjust_heat(quest["heat_cost"])
        except Exception:
            pass
        return {"success": True, "quest": quest, "rewards_applied": True}

    # ── Intel / Broker ────────────────────────────────────────────────────────

    def add_intel(self, entry: Dict[str, Any]) -> None:
        self._intel_feed.insert(0, entry)
        if len(self._intel_feed) > 30:
            self._intel_feed.pop()

    def get_intel_feed(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._intel_feed[:limit]

    def get_player_inventory(self) -> List[Dict[str, Any]]:
        return list(self._player_inventory)


_grid_state_instance: Optional[_GridState] = None


def _get_grid_state() -> _GridState:
    global _grid_state_instance
    if _grid_state_instance is None:
        _grid_state_instance = _GridState()
    return _grid_state_instance


# ──── Scene ───────────────────────────────────────────────────────────────────

class GridScene(BaseScene):
    """THE GRID — underground market, travel hub, faction den, broker.

    Port 5569.  Accent #00ff88.
    """

    SCENE_METADATA = {
        "name": "grid",
        "display_name": "THE GRID",
        "port": 5569,
        "type": "hub",
        "accent_color": "#00ff88",
        "accent_rgb": "0 255 136",
        "description": "The underground backbone of Neon City. Market. Map. Faction den. Intel broker.",
        "characters": ["mira", "viktor", "frankie"],
    }

    def __init__(self, config: Any = None) -> None:
        super().__init__(scene_name="grid", port=self.SCENE_METADATA["port"])
        self.scene_name = "grid"
        self.app: Optional[Flask] = None
        self.socketio: Optional[SocketIO] = None
        self._state = _get_grid_state()
        self._event_sub_id: Optional[str] = None

    # ── BaseScene overrides ───────────────────────────────────────────────────

    def start(self) -> None:
        """Start the Flask app and register all routes."""
        from engine.mcp import get_framework
        from jinja2 import ChoiceLoader, FileSystemLoader
        import os

        self.app = Flask(
            __name__,
            static_folder=os.path.join(os.path.dirname(__file__), "static"),
            template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        )
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode="threading")

        # Shared templates (navbar_v2.html, neon_hud.html, etc.)
        shared_tpl = os.path.join(
            os.path.dirname(__file__), "..", "..", "shared", "templates"
        )
        self.app.jinja_loader = ChoiceLoader([
            FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
            FileSystemLoader(os.path.normpath(shared_tpl)),
        ])

        register_shared_assets(self.app)
        self._register_routes()
        self._wire_event_cascade()
        self.register_health_route(self.app)
        self.register_bench_route(self.app, self.socketio)
        self.register_hud_route(self.app)
        self.register_announcer_route(self.app)
        self.register_inventory_route(self.app)
        self.register_shop_route(self.app)
        self.register_hack_route(self.app)
        self.register_city_route(self.app)
        self.register_mission_route(self.app)

        # Import skills so they register with SKILL_REGISTRY
        import content.scenes.grid.grid_skills  # noqa: F401

        fw = get_framework()
        node = fw.register_scene(self.scene_name)
        node.update_state({"status": "running", "port": self.SCENE_METADATA["port"]})

        logger.info("THE GRID started on port %d", self.SCENE_METADATA["port"])
        self.socketio.run(self.app, host="0.0.0.0", port=self.SCENE_METADATA["port"],
                          allow_unsafe_werkzeug=True)

    def stop(self) -> None:
        """Stop and clean up."""
        try:
            from engine.mcp import get_framework
            fw = get_framework()
            node = fw.register_scene(self.scene_name)
            node.update_state({"status": "stopped"})
        except Exception:
            pass

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name": self.SCENE_METADATA["display_name"],
            "scene_key": self.scene_name,
            "port": self.SCENE_METADATA["port"],
            "type": self.SCENE_METADATA["type"],
            "accent_color": self.SCENE_METADATA["accent_color"],
            "description": self.SCENE_METADATA["description"],
            "status": "running",
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register all HTTP and Socket.IO routes."""
        app = self.app

        @app.route("/")
        def index():
            from flask import render_template
            # v1.49.2 [2026-03-22] — API-first: template is a pure structural
            # shell. All data (market items, factions, player state) loads
            # client-side via JS fetch to /api/* endpoints. No Jinja2 data.
            return render_template("grid.html")

        # ── Market API ────────────────────────────────────────────────────────

        @app.route("/api/market/items")
        def api_market_items():
            return Response(
                json.dumps({"items": self._state.get_market_items(), "inventory": self._state.get_player_inventory()}),
                mimetype="application/json",
            )

        @app.route("/api/market/buy", methods=["POST"])
        def api_market_buy():
            data = request.get_json(silent=True) or {}
            result = self._state.buy_item(data.get("item_id", ""), data.get("quantity", 1))
            if result.get("success") and self.socketio:
                self.socketio.emit("inventory_update", {"inventory": self._state.get_player_inventory()})
            return Response(json.dumps(result, default=str), mimetype="application/json")

        @app.route("/api/market/sell", methods=["POST"])
        def api_market_sell():
            data = request.get_json(silent=True) or {}
            result = self._state.sell_item(data.get("item_id", ""), data.get("quantity", 1))
            if result.get("success") and self.socketio:
                self.socketio.emit("inventory_update", {"inventory": self._state.get_player_inventory()})
            return Response(json.dumps(result, default=str), mimetype="application/json")

        # ── Station / Map API ─────────────────────────────────────────────────

        @app.route("/api/station/map")
        def api_station_map():
            from engine.utils import port_is_open
            nodes = []
            for node in CITY_MAP_NODES:
                online = port_is_open(node["port"], timeout=0.3)
                nodes.append({**node, "online": online})
            return Response(json.dumps({"nodes": nodes}), mimetype="application/json")

        # ── Faction API ───────────────────────────────────────────────────────

        @app.route("/api/faction/standings")
        def api_faction_standings():
            standings = {}
            try:
                from engine.world.player_state import get_player_state
                standings = get_player_state().faction_standings
            except Exception:
                standings = {f["id"]: 50 for f in FACTION_DATA}
            try:
                from engine.world.world_state import get_world_state
                ws_summary = get_world_state().get_world_summary()
                factions_live = ws_summary.get("factions", {})
            except Exception:
                factions_live = {}
            result = []
            for f in FACTION_DATA:
                fid = f["id"]
                power = factions_live.get(fid, {}).get("power", standings.get(fid, 50)) if factions_live else standings.get(fid, 50)
                result.append({**f, "power": power, "player_standing": standings.get(fid, 50)})
            return Response(json.dumps({"factions": result, "quests": FACTION_QUESTS}), mimetype="application/json")

        @app.route("/api/faction/pledge", methods=["POST"])
        def api_faction_pledge():
            data = request.get_json(silent=True) or {}
            result = self._state.pledge_allegiance(data.get("faction_id", ""))
            if result.get("success") and self.socketio:
                self.socketio.emit("faction_update", {"faction_id": data.get("faction_id"), "action": "pledge"})
            return Response(json.dumps(result, default=str), mimetype="application/json")

        @app.route("/api/faction/quest/accept", methods=["POST"])
        def api_faction_quest_accept():
            data = request.get_json(silent=True) or {}
            result = self._state.accept_quest(data.get("faction_id", ""))
            return Response(json.dumps(result, default=str), mimetype="application/json")

        @app.route("/api/faction/quest/complete", methods=["POST"])
        def api_faction_quest_complete():
            data = request.get_json(silent=True) or {}
            result = self._state.complete_quest(data.get("faction_id", ""))
            if result.get("success") and self.socketio:
                self.socketio.emit("quest_complete", result)
            return Response(json.dumps(result, default=str), mimetype="application/json")

        # ── Broker / Intel API ────────────────────────────────────────────────

        @app.route("/api/broker/intel")
        def api_broker_intel():
            feed = self._state.get_intel_feed(20)
            # Augment with recent world events from WorldState
            try:
                from engine.world.world_state import get_world_state
                ws = get_world_state()
                for ev in ws.get_active_events()[:5]:
                    feed.insert(0, {
                        "id": ev.id,
                        "title": ev.name,
                        "desc": ev.description,
                        "type": ev.event_type,
                        "timestamp": ev.started_at,
                        "source": "world_state",
                    })
            except Exception:
                pass
            return Response(json.dumps({"intel": feed}), mimetype="application/json")

        @app.route("/api/broker/sell_info", methods=["POST"])
        def api_broker_sell_info():
            data = request.get_json(silent=True) or {}
            tip = data.get("text", "").strip()
            if not tip:
                return Response(json.dumps({"success": False, "error": "No information provided."}), mimetype="application/json")
            reward = random.randint(50, 300)
            # Store in Nexus
            try:
                from engine.nexus.client import get_nexus_client
                get_nexus_client().add_entry(
                    title=f"grid_intel:{uuid.uuid4()!s:.8}",
                    content=tip,
                    content_type="note",
                    category="street_intel",
                    tags=["grid", "player_tip"],
                )
            except Exception:
                pass
            try:
                from engine.world.player_state import get_player_state
                get_player_state().earn_credits(reward, "sell_intel")
            except Exception:
                pass
            entry = {"id": str(uuid.uuid4()), "title": "Player Intel", "desc": tip[:120], "type": "tip", "timestamp": time.time(), "source": "player"}
            self._state.add_intel(entry)
            if self.socketio:
                self.socketio.emit("intel_update", {"intel": self._state.get_intel_feed()})
            return Response(json.dumps({"success": True, "reward": reward, "message": f"Intel stored. Earned ₵{reward}."}), mimetype="application/json")

        @app.route("/api/broker/ghost_message")
        def api_broker_ghost_message():
            try:
                from engine.nexus.client import get_nexus_client
                results = get_nexus_client().search("ghost_msg", limit=5)
                messages = [r.get("content", "") for r in results if r.get("content")]
            except Exception:
                messages = []
            from engine.world.neon_city_events import GHOST_MESSAGES_RICH
            fallback = [random.choice(GHOST_MESSAGES_RICH)]
            messages = messages or fallback
            return Response(json.dumps({"messages": messages[-5:]}), mimetype="application/json")

        # ── Socket.IO events ──────────────────────────────────────────────────

        @self.socketio.on("connect")
        def on_connect():
            logger.debug("THE GRID: client connected")

        @self.socketio.on("request_prices")
        def on_request_prices():
            self.socketio.emit("price_update", {"items": self._state.get_market_items()})

    def _wire_event_cascade(self) -> None:
        """Subscribe to economy and world events so market prices react."""
        try:
            from engine.events.event_bus import get_event_bus

            def _on_economy_tick(data: Dict[str, Any]) -> None:
                changed = self._state.economy_shock(
                    data.get("event_type", "market_shift"),
                    data.get("economy_impact", 0),
                )
                if changed and self.socketio:
                    self.socketio.emit("price_update", {"changes": changed, "items": self._state.get_market_items()})
                    logger.debug("THE GRID: price update — %d items changed", len(changed))

            def _on_world_event(data: Dict[str, Any]) -> None:
                entry = {
                    "id": data.get("sim_event_id", str(uuid.uuid4())),
                    "title": data.get("title", "City Event"),
                    "desc": data.get("desc", ""),
                    "type": data.get("event_type", "world"),
                    "timestamp": time.time(),
                    "source": "world_sim",
                }
                self._state.add_intel(entry)
                if self.socketio:
                    self.socketio.emit("intel_update", {"intel": self._state.get_intel_feed()})
                    self.socketio.emit("world_event", data)

            bus = get_event_bus()
            bus.subscribe("world.economy_tick", _on_economy_tick, subscriber_id="grid")
            bus.subscribe("world.major_event", _on_world_event, subscriber_id="grid")
            logger.debug("THE GRID: EventBus wired")
        except Exception as exc:
            logger.warning("THE GRID: EventBus wiring failed: %s", exc)
