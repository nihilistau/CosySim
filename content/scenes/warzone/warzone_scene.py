"""
Global Strike — Modern artillery strategy scene.
=================================================

Port 5561.  Three.js rendered battlefield.  Player vs AI Agent.

Showcases:
- v2.7 streaming (AI commentary via infer_processed)
- MCP framework integration (events, state, skills)
- SharedBoardManager (highscores, message board)
- Three.js real-time rendering with SocketIO
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin

logger = logging.getLogger(__name__)

SCENE_ID = "warzone"
MAX_BUILDINGS = 3

# ── Game data tables ─────────────────────────────────────────────────

WEAPONS = [
    {"level": 1, "name": "Artillery",      "damage": 30,  "accuracy": 70,  "cost": 0,    "power": 0, "intel": 0},
    {"level": 2, "name": "Cruise Missile",  "damage": 50,  "accuracy": 80,  "cost": 300,  "power": 0, "intel": 0},
    {"level": 3, "name": "ICBM",            "damage": 90,  "accuracy": 85,  "cost": 600,  "power": 2, "intel": 0},
    {"level": 4, "name": "Bunker Buster",   "damage": 130, "accuracy": 80,  "cost": 900,  "power": 3, "intel": 0, "bypass": 0.5},
    {"level": 5, "name": "Laser Cannon",    "damage": 100, "accuracy": 100, "cost": 1200, "power": 5, "intel": 0},
    {"level": 6, "name": "Drone Swarm",     "damage": 50,  "accuracy": 75,  "cost": 1500, "power": 4, "intel": 1, "multi": 3},
    {"level": 7, "name": "Orbital Strike",  "damage": 250, "accuracy": 90,  "cost": 2500, "power": 8, "intel": 3},
]

DEFENSES = [
    {"level": 1, "name": "Sandbags",        "reduction": 10, "intercept": 0,  "cost": 0,    "power": 0},
    {"level": 2, "name": "Concrete Wall",   "reduction": 25, "intercept": 0,  "cost": 200,  "power": 0},
    {"level": 3, "name": "Anti-Air",        "reduction": 15, "intercept": 30, "cost": 400,  "power": 1},
    {"level": 4, "name": "Iron Dome",       "reduction": 20, "intercept": 50, "cost": 700,  "power": 3},
    {"level": 5, "name": "Golden Dome",     "reduction": 25, "intercept": 70, "cost": 1200, "power": 5},
    {"level": 6, "name": "Energy Shield",   "reduction": 0,  "intercept": 0,  "cost": 1800, "power": 8, "shield": 120},
]

BUILDINGS = {
    "factory":    {"name": "Factory",      "cost": 200, "hp": 100, "income": {"credits": 75}},
    "powerplant": {"name": "Power Plant",  "cost": 300, "hp": 100, "income": {"power": 2}},
    "intel":      {"name": "Intel Center", "cost": 400, "hp": 100, "income": {"intel": 1}},
}

WEATHER_TABLE = {
    "clear":     {"mod": 0,   "label": "☀️ Clear Skies"},
    "cloudy":    {"mod": -5,  "label": "☁️ Overcast"},
    "storm":     {"mod": -15, "label": "⛈️ Storm"},
    "fog":       {"mod": -20, "label": "🌫️ Dense Fog"},
    "favorable": {"mod": 10,  "label": "🎯 Favorable Winds"},
}

SPECIALS = {
    "spy_satellite":     {"intel": 2, "power": 0, "name": "Spy Satellite",     "desc": "Reveal enemy stats 3 turns"},
    "emp_burst":         {"intel": 0, "power": 3, "name": "EMP Burst",         "desc": "Disable enemy defense 1 turn"},
    "sabotage":          {"intel": 2, "power": 1, "name": "Sabotage",          "desc": "Destroy random enemy building"},
    "shield_overcharge": {"intel": 0, "power": 4, "name": "Shield Overcharge", "desc": "Double defense this turn"},
    "taunt":             {"intel": 1, "power": 0, "name": "Commander Taunt",   "desc": "+10% damage next attack"},
}


# ── Pure game logic ──────────────────────────────────────────────────

class PlayerState:
    """One side's resources, buildings, weapons, defenses, and status effects."""

    def __init__(self, name: str, is_ai: bool = False):
        self.name = name
        self.is_ai = is_ai
        self.base_hp = 500
        self.max_hp = 500
        self.credits = 500
        self.power = 0
        self.intel = 0
        self.weapon_level = 1
        self.defense_level = 1
        self.buildings: List[Dict] = []
        # Status effects
        self.spy_turns = 0
        self.emp_turns = 0
        self.shield_overcharge = False
        self.damage_bonus = 0.0
        self.counterstrike_queued = False

    def income(self, escalation: float = 1.0) -> Dict[str, int]:
        base = {"credits": 100, "power": 0, "intel": 0}
        for b in self.buildings:
            bdata = BUILDINGS.get(b["type"], {})
            for res, amt in bdata.get("income", {}).items():
                base[res] = base.get(res, 0) + amt
        base["credits"] = int(base["credits"] * escalation)
        return base

    def collect_income(self, escalation: float = 1.0) -> Dict[str, int]:
        inc = self.income(escalation)
        self.credits += inc["credits"]
        self.power += inc["power"]
        self.intel += inc["intel"]
        return inc

    def can_afford(self, credits: int = 0, power: int = 0, intel: int = 0) -> bool:
        return self.credits >= credits and self.power >= power and self.intel >= intel

    def spend(self, credits: int = 0, power: int = 0, intel: int = 0):
        self.credits -= credits
        self.power -= power
        self.intel -= intel

    def to_dict(self, hide: bool = False) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "base_hp": self.base_hp, "max_hp": self.max_hp,
            "weapon_level": self.weapon_level,
            "weapon_name": WEAPONS[self.weapon_level - 1]["name"],
            "defense_level": self.defense_level,
            "defense_name": DEFENSES[self.defense_level - 1]["name"],
            "buildings": [
                {"type": b["type"], "name": BUILDINGS[b["type"]]["name"], "hp": b["hp"]}
                for b in self.buildings
            ],
            "building_slots": MAX_BUILDINGS - len(self.buildings),
        }
        if not hide:
            d.update({
                "credits": self.credits, "power": self.power, "intel": self.intel,
                "spy_turns": self.spy_turns, "emp_turns": self.emp_turns,
                "shield_overcharge": self.shield_overcharge,
                "damage_bonus": self.damage_bonus,
            })
        return d


class GameState:
    """Full game state for one session."""

    def __init__(self, game_id: str):
        self.game_id = game_id
        self.turn = 1
        self.phase = "player_turn"
        self.weather = "clear"
        self.player = PlayerState("Commander")
        self.ai = PlayerState("General Ironside", is_ai=True)
        self.log: List[Dict] = []
        self.escalation = 1.0
        self.winner: Optional[str] = None
        self.terrain_seed = random.randint(0, 99999)

    def to_dict(self) -> Dict[str, Any]:
        spy = self.player.spy_turns > 0
        return {
            "game_id": self.game_id, "turn": self.turn,
            "phase": self.phase, "weather": self.weather,
            "weather_label": WEATHER_TABLE[self.weather]["label"],
            "player": self.player.to_dict(),
            "ai": self.ai.to_dict(hide=not spy),
            "log": self.log[-12:], "escalation": self.escalation,
            "winner": self.winner, "terrain_seed": self.terrain_seed,
        }

    def _log(self, msg: str, kind: str = "info"):
        self.log.append({"turn": self.turn, "msg": msg, "type": kind})

    def roll_weather(self):
        self.weather = random.choice(list(WEATHER_TABLE.keys()))
        self._log(f"Weather: {WEATHER_TABLE[self.weather]['label']}", "weather")

    def check_events(self):
        # Supply drop ~15 %
        if random.random() < 0.15:
            target = random.choice([self.player, self.ai])
            if random.random() < 0.6:
                amt = random.randint(150, 250)
                target.credits += amt
                self._log(f"📦 Supply Drop! {target.name} +{amt}💰", "event")
            else:
                amt = random.randint(2, 4)
                target.power += amt
                self._log(f"⚡ Power Surge! {target.name} +{amt}⚡", "event")
        # Arms race every 5 turns
        if self.turn % 5 == 0:
            self.escalation += 0.2
            self._log(f"🔥 Arms Race! Income ×{self.escalation:.1f}", "event")

    # ── Combat ───────────────────────────────────────────────────────

    def resolve_attack(self, attacker: PlayerState, defender: PlayerState,
                       target: str = "base") -> Dict[str, Any]:
        weapon = WEAPONS[attacker.weapon_level - 1]
        defense = DEFENSES[defender.defense_level - 1]
        accuracy = max(10, min(100, weapon["accuracy"] + WEATHER_TABLE[self.weather]["mod"]))
        hits_count = weapon.get("multi", 1)
        total_damage = 0
        hit_details: List[Dict] = []

        for _ in range(hits_count):
            roll = random.randint(1, 100)
            if roll > accuracy:
                hit_details.append({"hit": False, "damage": 0})
                continue
            dmg = weapon["damage"]
            crit = random.random() < 0.15
            if crit:
                dmg = int(dmg * 1.5)
            if attacker.damage_bonus > 0:
                dmg = int(dmg * (1 + attacker.damage_bonus))

            # Defense (skip if EMP active)
            intercepted = False
            if defender.emp_turns <= 0:
                icpt = defense["intercept"] * (2 if defender.shield_overcharge else 1)
                if icpt > 0 and random.randint(1, 100) <= min(95, icpt):
                    intercepted = True
                    hit_details.append({"hit": True, "damage": 0, "intercepted": True, "crit": crit})
                    continue
                reduction = defense["reduction"] * (2 if defender.shield_overcharge else 1)
                shield = defense.get("shield", 0) * (2 if defender.shield_overcharge else 1)
                if shield > 0:
                    dmg = max(0, dmg - shield)
                bypass = weapon.get("bypass", 0)
                dmg = max(0, dmg - int(reduction * (1 - bypass)))

            if target == "building" and defender.buildings:
                bldg = random.choice(defender.buildings)
                bldg["hp"] -= dmg
                if bldg["hp"] <= 0:
                    defender.buildings.remove(bldg)
                    self._log(f"💥 {defender.name}'s {BUILDINGS[bldg['type']]['name']} destroyed!", "combat")
            else:
                defender.base_hp = max(0, defender.base_hp - dmg)

            total_damage += dmg
            hit_details.append({"hit": True, "damage": dmg, "intercepted": False, "crit": crit})

        # Counterstrike chance
        if total_damage > 0 and random.random() < 0.25:
            defender.counterstrike_queued = True
            self._log(f"⚡ {defender.name} readying counterstrike!", "event")

        attacker.damage_bonus = 0
        defender.shield_overcharge = False
        return {"weapon": weapon["name"], "target": target,
                "total_damage": total_damage, "hits": hit_details, "accuracy": accuracy}

    # ── Actions ──────────────────────────────────────────────────────

    def process_action(self, side: str, action: str, **kw) -> Dict[str, Any]:
        ps = self.player if side == "player" else self.ai
        opp = self.ai if side == "player" else self.player

        if action == "attack":
            tgt = kw.get("target", "base")
            result = self.resolve_attack(ps, opp, tgt)
            self._log(f"🎯 {ps.name} fires {result['weapon']}! {result['total_damage']} dmg → {tgt}", "combat")
            if opp.base_hp <= 0:
                self.phase = "game_over"
                self.winner = side
                self._log(f"🏆 {ps.name} wins!", "victory")
            return {"type": "attack", **result}

        if action.startswith("build_"):
            btype = action[6:]
            if btype not in BUILDINGS:
                return {"type": "error", "msg": "Unknown building"}
            if len(ps.buildings) >= MAX_BUILDINGS:
                return {"type": "error", "msg": "No slots"}
            bdata = BUILDINGS[btype]
            if not ps.can_afford(credits=bdata["cost"]):
                return {"type": "error", "msg": "Insufficient credits"}
            ps.spend(credits=bdata["cost"])
            ps.buildings.append({"type": btype, "hp": bdata["hp"]})
            self._log(f"🏗️ {ps.name} built {bdata['name']}", "build")
            return {"type": "build", "building": btype}

        if action == "upgrade_weapon":
            if ps.weapon_level >= len(WEAPONS):
                return {"type": "error", "msg": "Max level"}
            nxt = WEAPONS[ps.weapon_level]
            if not ps.can_afford(credits=nxt["cost"], power=nxt["power"], intel=nxt["intel"]):
                return {"type": "error", "msg": "Insufficient resources"}
            ps.spend(credits=nxt["cost"], power=nxt["power"], intel=nxt["intel"])
            ps.weapon_level += 1
            self._log(f"⬆️ {ps.name} → {nxt['name']}", "upgrade")
            return {"type": "upgrade", "what": "weapon", "level": ps.weapon_level}

        if action == "upgrade_defense":
            if ps.defense_level >= len(DEFENSES):
                return {"type": "error", "msg": "Max level"}
            nxt = DEFENSES[ps.defense_level]
            if not ps.can_afford(credits=nxt["cost"], power=nxt["power"]):
                return {"type": "error", "msg": "Insufficient resources"}
            ps.spend(credits=nxt["cost"], power=nxt["power"])
            ps.defense_level += 1
            self._log(f"🛡️ {ps.name} → {nxt['name']}", "upgrade")
            return {"type": "upgrade", "what": "defense", "level": ps.defense_level}

        if action.startswith("special_"):
            return self._do_special(ps, opp, action[8:])

        return {"type": "error", "msg": f"Unknown: {action}"}

    def _do_special(self, ps: PlayerState, opp: PlayerState, sid: str) -> Dict:
        if sid not in SPECIALS:
            return {"type": "error", "msg": "Unknown special"}
        sp = SPECIALS[sid]
        if not ps.can_afford(intel=sp["intel"], power=sp["power"]):
            return {"type": "error", "msg": "Insufficient resources"}
        ps.spend(intel=sp["intel"], power=sp["power"])

        if sid == "spy_satellite":
            ps.spy_turns = 3
            self._log(f"🛰️ {ps.name}: Spy Satellite active!", "special")
        elif sid == "emp_burst":
            opp.emp_turns = 1
            self._log(f"💫 {ps.name}: EMP! {opp.name}'s defenses offline!", "special")
        elif sid == "sabotage":
            if opp.buildings:
                b = random.choice(opp.buildings)
                opp.buildings.remove(b)
                self._log(f"🕵️ {ps.name} sabotaged {opp.name}'s {BUILDINGS[b['type']]['name']}!", "special")
            else:
                self._log(f"🕵️ Sabotage — no targets", "special")
        elif sid == "shield_overcharge":
            ps.shield_overcharge = True
            self._log(f"🔋 {ps.name}: Shield Overcharge!", "special")
        elif sid == "taunt":
            ps.damage_bonus = 0.10
            self._log(f"📢 {ps.name} taunts! +10% damage next attack", "special")
        return {"type": "special", "special": sid, "name": sp["name"]}

    def advance_turn(self):
        """Tick status effects, collect income, process counterstrikes, roll new weather."""
        for ps in (self.player, self.ai):
            ps.spy_turns = max(0, ps.spy_turns - 1)
            ps.emp_turns = max(0, ps.emp_turns - 1)

        self.turn += 1
        self.roll_weather()
        self.check_events()

        p_inc = self.player.collect_income(self.escalation)
        a_inc = self.ai.collect_income(self.escalation)
        self._log(
            f"💰 Income: +{p_inc['credits']}💰 +{p_inc['power']}⚡ +{p_inc['intel']}🔍",
            "income",
        )

        # Counterstrikes
        for ps in (self.player, self.ai):
            if ps.counterstrike_queued:
                ps.counterstrike_queued = False
                opp = self.ai if ps is self.player else self.player
                r = self.resolve_attack(ps, opp, "base")
                self._log(f"⚡ {ps.name} counterstrike! {r['total_damage']} dmg!", "combat")
                if opp.base_hp <= 0:
                    self.phase = "game_over"
                    self.winner = "player" if ps is self.player else "ai"

        if self.phase != "game_over":
            self.phase = "player_turn"


# ── Scene class ──────────────────────────────────────────────────────

class WarzoneScene(BaseScene, MCPSceneMixin, mcp_scene_id="warzone"):
    def __init__(self):
        super().__init__("warzone", port=5561)
        tpl = str(Path(__file__).parent / "templates")
        self.app = Flask(__name__, template_folder=tpl)
        self.app.config["SECRET_KEY"] = "globalstrike"
        self.socketio = SocketIO(self.app, cors_allowed_origins="*",
                                 async_mode="threading")
        self.games: Dict[str, GameState] = {}
        self._lock = threading.Lock()
        self._fw = None
        try:
            from engine.mcp.framework import get_framework
            self._fw = get_framework()
        except Exception as exc:
            logger.debug("WarzoneScene: framework init failed: %s", exc)
        self._setup_routes()
        self._setup_sio()

    # ── BaseScene interface ──────────────────────────────────────────

    def start(self):
        self.register_health_route(self.app)
        self.mount_overlay(self.app, self.socketio)
        logger.info("Global Strike starting on port %d", self.port)
        self.socketio.run(self.app, host=self.host, port=self.port,
                          allow_unsafe_werkzeug=True)

    def stop(self):
        self._mcp_deregister_scene()

    def get_plugin_info(self):
        return {
            "name": "Global Strike",
            "description": "Modern artillery strategy — Player vs AI Agent",
            "version": "1.0.0", "author": "CosySim",
            "port": self.port,
            "tags": ["game", "strategy", "threejs", "ai"],
            "skill_packs": ["boards"],
            "routes": [
                {"path": "/", "methods": ["GET"], "description": "Game UI"},
                {"path": "/api/highscores", "methods": ["GET"], "description": "Scores"},
            ],
        }

    # ── Routes ───────────────────────────────────────────────────────

    def _setup_routes(self):
        @self.app.route("/")
        def index():
            return render_template("warzone.html")

        @self.app.route("/api/highscores")
        def highscores():
            try:
                from engine.mcp.shared_boards import get_shared_boards
                scores = get_shared_boards().get_highscores("global_strike", 20)
            except Exception:
                scores = []
            return jsonify({"ok": True, "scores": scores})

        @self.app.route("/api/game-data")
        def game_data():
            return jsonify({
                "weapons": WEAPONS, "defenses": DEFENSES,
                "buildings": BUILDINGS, "specials": SPECIALS,
            })

    # ── SocketIO handlers ────────────────────────────────────────────

    def _setup_sio(self):
        sio = self.socketio

        @sio.on("start_game")
        def on_start():
            sid = request.sid
            gid = f"gs_{sid[:8]}_{int(time.time())}"
            game = GameState(gid)
            game.roll_weather()
            with self._lock:
                self.games[sid] = game
            emit("game_state", game.to_dict())
            emit("ai_comment", {"text": "I am General Ironside. Prepare yourself, Commander."})
            if self._fw:
                self._fw.emit_event("game_started",
                                    {"game": "global_strike", "id": gid},
                                    source=SCENE_ID)

        @sio.on("player_action")
        def on_action(data):
            sid = request.sid
            game = self.games.get(sid)
            if not game or game.phase == "game_over":
                return
            if game.phase != "player_turn":
                emit("error", {"msg": "Not your turn"})
                return
            action = data.get("action", "")
            result = game.process_action("player", action,
                                         target=data.get("target", "base"))
            if result.get("type") == "error":
                emit("error", result)
                return
            emit("action_result", {"side": "player", "result": result})
            if game.phase == "game_over":
                self._on_game_over(game, sid)
                emit("game_state", game.to_dict())
                return
            game.phase = "ai_turn"
            emit("game_state", game.to_dict())
            sio.start_background_task(self._ai_turn, sid)

        @sio.on("disconnect")
        def on_dc():
            with self._lock:
                self.games.pop(request.sid, None)

    # ── AI turn ──────────────────────────────────────────────────────

    def _ai_turn(self, sid: str):
        game = self.games.get(sid)
        if not game:
            return
        time.sleep(1.0)
        decision = self._ai_decide(game)
        self.socketio.emit("ai_comment",
                           {"text": decision.get("comment", "...")},
                           room=sid)
        time.sleep(0.5)
        result = game.process_action("ai", decision["action"],
                                     target=decision.get("target", "base"))
        self.socketio.emit("action_result",
                           {"side": "ai", "result": result}, room=sid)
        if game.phase == "game_over":
            self._on_game_over(game, sid)
            self.socketio.emit("game_state", game.to_dict(), room=sid)
            return
        game.advance_turn()
        self.socketio.emit("game_state", game.to_dict(), room=sid)

    def _ai_decide(self, game: GameState) -> Dict[str, Any]:
        """Use LLM (infer_processed) for AI decisions, fallback to rules."""
        ai = game.ai
        player = game.player
        prompt = (
            f"Turn {game.turn}. Weather: {game.weather}.\n"
            f"YOUR stats: HP={ai.base_hp}/{ai.max_hp}, 💰{ai.credits} ⚡{ai.power} 🔍{ai.intel}\n"
            f"YOUR weapon: Lv{ai.weapon_level} {WEAPONS[ai.weapon_level-1]['name']}, "
            f"defense: Lv{ai.defense_level} {DEFENSES[ai.defense_level-1]['name']}\n"
            f"YOUR buildings: {', '.join(b['type'] for b in ai.buildings) or 'none'} "
            f"({MAX_BUILDINGS - len(ai.buildings)} slots free)\n"
            f"ENEMY: HP={player.base_hp}, weapon=Lv{player.weapon_level}, "
            f"defense=Lv{player.defense_level}, {len(player.buildings)} buildings\n\n"
            f"Choose ONE action from: attack, build_factory, build_powerplant, build_intel, "
            f"upgrade_weapon, upgrade_defense, special_emp, special_sabotage, special_spy, "
            f"special_shield_overcharge, special_taunt\n"
            f"Respond with [ACTION:your_choice] optionally [TARGET:base|building] "
            f"then 1-2 sentences of in-character trash-talk or commentary."
        )
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            mgr = get_virtual_agent_manager()
            result = mgr.infer_processed(
                agent_id=f"warzone_ai_{game.game_id}",
                system_prompt=(
                    "You are General Ironside, a cunning AI military commander in Global Strike. "
                    "Be strategic, competitive, and entertaining. Keep responses SHORT."
                ),
                user_prompt=prompt,
                store=False,
            )
            action = "attack"
            target = "base"
            for tag in result.get("action_tags", []):
                t = tag.upper()
                if t.startswith("ACTION:"):
                    action = tag.split(":", 1)[1].strip().lower()
                elif t.startswith("TARGET:"):
                    target = tag.split(":", 1)[1].strip().lower()
            return {"action": action, "target": target,
                    "comment": result.get("text", "...")}
        except Exception as exc:
            logger.debug("AI LLM failed, using fallback: %s", exc)
            return self._ai_fallback(game)

    def _ai_fallback(self, game: GameState) -> Dict[str, Any]:
        """Rule-based fallback AI."""
        ai = game.ai
        # Economy first 3 turns
        if game.turn <= 3 and len(ai.buildings) < 2 and ai.credits >= 200:
            bt = "factory" if not any(b["type"] == "factory" for b in ai.buildings) else "powerplant"
            return {"action": f"build_{bt}", "comment": "Building my war machine..."}
        # Upgrade weapon when affordable
        if ai.weapon_level < len(WEAPONS):
            nxt = WEAPONS[ai.weapon_level]
            if ai.can_afford(credits=nxt["cost"], power=nxt["power"], intel=nxt["intel"]):
                return {"action": "upgrade_weapon",
                        "comment": f"Upgrading to {nxt['name']}!"}
        # Upgrade defense occasionally
        if ai.defense_level < ai.weapon_level and ai.defense_level < len(DEFENSES):
            nxt = DEFENSES[ai.defense_level]
            if ai.can_afford(credits=nxt["cost"], power=nxt["power"]):
                return {"action": "upgrade_defense",
                        "comment": f"Fortifying with {nxt['name']}."}
        # EMP if affordable and enemy has good defense
        if (game.player.defense_level >= 3 and ai.power >= 3
                and "emp_burst" in SPECIALS):
            return {"action": "special_emp", "comment": "Shutting down your defenses!"}
        # Default: attack
        tgt = "building" if game.player.buildings and random.random() < 0.3 else "base"
        return {"action": "attack", "target": tgt, "comment": "Fire!"}

    # ── End game ─────────────────────────────────────────────────────

    def _on_game_over(self, game: GameState, sid: str):
        if game.winner == "player":
            score = game.player.base_hp + game.turn * 10 + game.player.credits
            try:
                from engine.mcp.shared_boards import get_shared_boards
                get_shared_boards().submit_score("global_strike", "Commander", score, {
                    "turns": game.turn, "hp": game.player.base_hp,
                })
                self.socketio.emit("highscore_submitted", {"score": score}, room=sid)
            except Exception:
                pass
        if self._fw:
            self._fw.emit_event("game_over", {
                "game": "global_strike", "winner": game.winner,
                "turns": game.turn,
            }, source=SCENE_ID)


# ── Entry point ──────────────────────────────────────────────────────

def main():
    import sys
    from engine.paths import ROOT
    sys.path.insert(0, str(ROOT))
    scene = WarzoneScene()
    scene.start()


if __name__ == "__main__":
    main()
