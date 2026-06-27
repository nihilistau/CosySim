"""
Verdant Realms — Dual-Agent LitRPG Scene
========================================

A Director-and-Companion guided interactive-fiction scene set in the living
Verdant Realms. Two AI agents share the stage:

  Director  (Agent 1) — Game master. Narrates the world, runs NPCs, sets the
                        stakes, presents the player's choices, and adjudicates
                        d20 skill checks and combat.
  Companion (Agent 2) — A loyal Wayfarer who travels with the player, offering
                        short tactical asides and colour between beats.

All mutable game state lives in :class:`VerdantState` (one active session at a
time) and is synced to the MCP framework. Inference flows through the existing
``VirtualAgentManager`` (the same seam realm uses); every LLM call degrades
gracefully to a scripted fallback so the scene is always playable — even with
LMStudio offline.

Reuse-first
-----------
The scene OWNS only its own narrative state. Dice, agents, governance, and the
overlay/health/HUD routes all come from EXISTING engine seams
(:class:`FlaskScene`, ``VirtualAgentManager``, ``build_governance_context``).

Version: v1.64.0 [2026-06-27]
Author:  CosySim Team

Change Log:
    v1.64.0 [2026-06-27] — Initial implementation: dual-agent narrative loop,
                            d20 + skill-check + combat mechanics, faction
                            standings, quest tracker; routes /api/verdant/*;
                            graceful scripted fallback when the LLM is offline.

CONNECTS: FlaskScene, SocketIO, VirtualAgentManager, get_framework,
          build_governance_context, get_scene_state_manager
CALLED BY: launcher.py, TUI, hub
EMITS: verdant_state, turn_update, dice_roll, combat_update Socket.IO events
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from flask import jsonify, render_template, request

from engine.scenes.flask_scene import FlaskScene
from engine.mcp.framework import get_framework

logger = logging.getLogger(__name__)

SCENE_ID = "verdant"
# v1.64.0 [2026-06-27] — Structured logging context (SCENE_ID prefix + operation tags)

# v1.64.0 [2026-06-27] — Use the port registry instead of a hardcoded value.
try:
    from engine.port_registry import get_port as _get_port
    DEFAULT_PORT = _get_port("verdant", 5599)
except Exception:
    DEFAULT_PORT = 5599


# ──── Static World Data ──────────────────────────────────────────────────────
# v1.64.0 [2026-06-27] — The three rival powers of the Verdant Realms. Standing
# values are 0–100; the player nudges them through choices and quest outcomes.

VERDANT_FACTIONS: Dict[str, Dict[str, Any]] = {
    "grove": {"name": "The Grove", "icon": "🌿", "standing": 55,
              "blurb": "Druidic keepers of the old canopy."},
    "thorn": {"name": "Thornguard", "icon": "🌑", "standing": 30,
              "blurb": "Militant wardens of the bramble marches."},
    "spore": {"name": "Spore Council", "icon": "🍄", "standing": 45,
              "blurb": "Mycelial mystics who hear the underearth."},
}

# v1.64.0 [2026-06-27] — Skill-check skills mapped to the player's stats.
VERDANT_SKILLS: Dict[str, str] = {
    "arcana": "intellect",
    "persuasion": "charisma",
    "stealth": "agility",
    "might": "strength",
    "survival": "wisdom",
}


# ──── Game State ─────────────────────────────────────────────────────────────


class VerdantState:
    """In-memory state for one Verdant Realms session.

    Holds the player's stats, the two agents' meters (Director influence /
    Companion loyalty), faction standings, the active quest, the turn log, and
    the current choice set. Serialized verbatim to the client + MCP framework.
    """

    def __init__(self) -> None:
        self.session_id: str = uuid.uuid4().hex[:12]
        self.started_at: float = time.time()
        self.turn_number: int = 0
        self.ended: bool = False

        # Player stats (d20 modifiers derive from these).
        self.player_stats: Dict[str, int] = {
            "hp": 30, "max_hp": 30,
            "mp": 12, "max_mp": 12,
            "level": 1, "xp": 0,
            "strength": 12, "agility": 11, "intellect": 13,
            "charisma": 12, "wisdom": 11, "luck": 10,
        }

        # Director / Companion agent meters (shown as stat bars in the UI).
        self.director_influence: int = 87      # 0–100
        self.director_threads: int = 3         # narrative threads in play (0–5)
        self.companion_loyalty: int = 92       # 0–100
        self.companion_focus: int = 4          # 0–4

        # Faction standings (deep-copied so a session can drift independently).
        self.factions: Dict[str, Dict[str, Any]] = {
            k: dict(v) for k, v in VERDANT_FACTIONS.items()
        }

        # Active quest tracker.
        self.quest: Optional[Dict[str, Any]] = None

        # Narrative log + the choices currently presented to the player.
        self.history: List[Dict[str, Any]] = []
        self.current_choices: List[Dict[str, str]] = []

        # Combat sub-state (None when not fighting).
        self.combat: Optional[Dict[str, Any]] = None

    # ── Derived helpers ──────────────────────────────────────────────

    def stat_mod(self, stat: str) -> int:
        """Return the d20 modifier for a stat (D&D-style: (score - 10) // 2)."""
        return (self.player_stats.get(stat, 10) - 10) // 2

    def roll_d20(self, modifier: int = 0) -> Dict[str, Any]:
        """Roll a d20 and return the natural roll, modifier, and total."""
        natural = random.randint(1, 20)
        total = natural + modifier
        return {
            "natural": natural,
            "modifier": modifier,
            "total": total,
            "crit": natural == 20,
            "fumble": natural == 1,
        }

    def skill_check(self, skill: str, dc: int = 15) -> Dict[str, Any]:
        """Resolve a d20 skill check against a difficulty class (DC)."""
        stat = VERDANT_SKILLS.get(skill, "luck")
        modifier = self.stat_mod(stat)
        roll = self.roll_d20(modifier)
        success = roll["crit"] or (not roll["fumble"] and roll["total"] >= dc)
        return {
            "skill": skill, "stat": stat, "dc": dc,
            "success": success, **roll,
        }

    def gain_xp(self, amount: int) -> Dict[str, Any]:
        """Award XP, leveling up every 100 XP (raises max HP/MP)."""
        self.player_stats["xp"] += max(0, amount)
        leveled = False
        while self.player_stats["xp"] >= self.player_stats["level"] * 100:
            self.player_stats["xp"] -= self.player_stats["level"] * 100
            self.player_stats["level"] += 1
            self.player_stats["max_hp"] += 6
            self.player_stats["hp"] = self.player_stats["max_hp"]
            self.player_stats["max_mp"] += 3
            self.player_stats["mp"] = self.player_stats["max_mp"]
            leveled = True
        return {"leveled_up": leveled, "level": self.player_stats["level"]}

    def adjust_standing(self, faction_key: str, delta: int) -> None:
        """Nudge a faction's standing, clamped to 0–100."""
        fac = self.factions.get(faction_key)
        if fac:
            fac["standing"] = max(0, min(100, int(fac["standing"]) + int(delta)))

    def advance_turn(self, narration: str, choices: List[Dict[str, str]]) -> None:
        """Append a beat to the log and store the new choices."""
        self.turn_number += 1
        self.history.append({
            "turn": self.turn_number,
            "narration": narration,
            "ts": time.time(),
        })
        self.history = self.history[-50:]   # cap log growth
        self.current_choices = choices or []

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the full state for the client + MCP framework."""
        return {
            "session_id": self.session_id,
            "turn_number": self.turn_number,
            "ended": self.ended,
            "player_stats": dict(self.player_stats),
            "director": {
                "influence": self.director_influence,
                "threads": self.director_threads,
            },
            "companion": {
                "loyalty": self.companion_loyalty,
                "focus": self.companion_focus,
            },
            "factions": {k: dict(v) for k, v in self.factions.items()},
            "quest": dict(self.quest) if self.quest else None,
            "choices": list(self.current_choices),
            "combat": dict(self.combat) if self.combat else None,
            "events": [h.get("narration", "") for h in self.history[-6:]],
        }


# ──── Prompt Builders ────────────────────────────────────────────────────────


def _director_system_prompt(state: VerdantState) -> str:
    """Build the Director (game-master) system prompt from current state."""
    factions = ", ".join(
        f"{f['name']} ({f['standing']})" for f in state.factions.values()
    )
    return f"""You are THE DIRECTOR of an interactive LitRPG set in the VERDANT REALMS —
a living world of druidic groves, bramble marches, and mycelial deeps.

YOUR ROLE:
- Narrate vividly in second person ("You push through the glowing ferns...").
- Voice every NPC with distinct motive.
- After each beat, present 2-4 player choices as JSON.
- Call for a d20 skill check when an action is risky.
- Keep stakes high; the realm is beautiful but dangerous.

PLAYER:
HP {state.player_stats['hp']}/{state.player_stats['max_hp']} | MP {state.player_stats['mp']}/{state.player_stats['max_mp']} | Lv {state.player_stats['level']}
STR {state.player_stats['strength']} AGI {state.player_stats['agility']} INT {state.player_stats['intellect']} CHA {state.player_stats['charisma']}
Factions: {factions}
Turn: {state.turn_number}

RESPONSE FORMAT — end EVERY reply with a JSON block:
```json
{{"narration": "story text", "choices": [{{"id": "a", "text": "Choice A"}}], "skill_check": null, "xp": 0, "faction_shift": {{}}}}
```
Set skill_check to {{"skill": "arcana", "dc": 15}} when a check is needed.
faction_shift maps faction keys (grove/thorn/spore) to +/- standing deltas."""


def _companion_system_prompt(state: VerdantState) -> str:
    """Build the Companion (loyal Wayfarer) system prompt."""
    return f"""You are the COMPANION — a loyal Wayfarer travelling the Verdant Realms
beside the player. You are warm, wry, and tactically sharp.

- Speak in SHORT asides (1-2 sentences). You're a voice at the player's shoulder.
- Offer genuine tactical reads disguised as banter.
- Your loyalty is {state.companion_loyalty}/100 and your focus is {state.companion_focus}/4.
- React to the moment; never narrate the world (that's the Director's job)."""


# ──── Scene Implementation ───────────────────────────────────────────────────


class VerdantRealmsScene(FlaskScene):
    """Verdant Realms — a dual-agent LitRPG over premium composited scene art.

    CONNECTS: FlaskScene, SocketIO, VirtualAgentManager, get_framework
    CALLED BY: launcher.py, TUI, hub
    EMITS: verdant_state, turn_update, dice_roll, combat_update Socket.IO events
    """

    SCENE_METADATA = {
        "name": "verdant",
        "display_name": "VERDANT REALMS",
        "port": DEFAULT_PORT,
        "type": "rpg",
        "accent_color": "#22c55e",
        "accent_rgb": "34 197 94",
        "description": "A living world of grove, bramble, and spore — guided by a Director and a loyal Companion.",
        "version": "1.64.0",
        "tags": ["litrpg", "dual_agent", "d20", "combat", "factions", "visual_novel"],
        "skill_packs": ["narrative", "memory", "character"],
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        super().__init__(host=host, port=port)

        self.app.config["SECRET_KEY"] = "verdant_realms_v164"

        # v1.64.0 — Bench HUD route (latency/model/tokens strip).
        self.register_bench_route(self.app, self.socketio)

        # One active session at a time (mirrors realm).
        self.state: Optional[VerdantState] = None
        self._director_conv_id: Optional[str] = None

        self._setup_routes()
        self._setup_socketio()

        # Framework integration (defensive — scene boots without it).
        try:
            from engine.mcp.scene_state import get_scene_state_manager
            self._state_mgr = get_scene_state_manager()
        except Exception:
            self._state_mgr = None

    # ── Agent inference (graceful fallback) ──────────────────────────

    def _director_infer(self, user_message: str) -> Dict[str, Any]:
        """Send a beat through the Director agent; fall back to a script on error."""
        if not self.state:
            return self._fallback_beat("The realm is silent.")
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest

            system_prompt = _director_system_prompt(self.state)
            try:
                from engine.mcp.comms_framework import build_governance_context
                gov = build_governance_context("verdant_director", "verdant", user_message)
                if gov:
                    system_prompt = f"{system_prompt}\n\n{gov}"
            except Exception:
                pass

            req = InferenceRequest(
                agent_id="verdant_director",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.85,
                max_output_tokens=1200,
                conversation_id=f"verdant_director_{self.state.session_id}",
                previous_response_id=self._director_conv_id,
                store=True,
                metadata={"scene": "verdant", "role": "director"},
            )
            proc = get_virtual_agent_manager().infer_processed(req)
            if getattr(proc, "response_id", None):
                self._director_conv_id = proc.response_id
            raw = proc.clean_text or proc.raw_text or ""
            return self._parse_director_response(raw)
        except Exception as exc:
            logger.warning("[%s] Director inference failed (operation=chat): %s", SCENE_ID, exc)
            return self._fallback_beat(
                "The Director gathers the threads of the tale... (the weave is quiet)"
            )

    def _companion_infer(self, context: str) -> str:
        """Get a short Companion aside; fall back to a canned quip on error."""
        if not self.state:
            return ""
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest

            req = InferenceRequest(
                agent_id="verdant_companion",
                messages=[
                    {"role": "system", "content": _companion_system_prompt(self.state)},
                    {"role": "user", "content": context},
                ],
                temperature=0.95,
                max_output_tokens=160,
                conversation_id=f"verdant_companion_{self.state.session_id}",
                store=False,
                metadata={"scene": "verdant", "role": "companion"},
            )
            proc = get_virtual_agent_manager().infer_processed(req)
            return (proc.clean_text or proc.raw_text or "").strip()
        except Exception as exc:
            logger.debug("[%s] Companion inference failed (operation=chat): %s", SCENE_ID, exc)
            return random.choice([
                "*The Companion taps their staff.* \"Mind the bramble — it bites back.\"",
                "\"I've a good feeling. Mostly good. Eighty percent good.\"",
                "\"Whatever you're planning, do it before the spores wake.\"",
            ])

    @staticmethod
    def _fallback_beat(narration: str) -> Dict[str, Any]:
        """Return a generic playable beat when the LLM is unavailable."""
        return {
            "narration": narration,
            "choices": [
                {"id": "a", "text": "Press deeper into the canopy"},
                {"id": "b", "text": "Search the glade carefully"},
                {"id": "c", "text": "Call out to whatever listens"},
            ],
            "skill_check": None, "xp": 0, "faction_shift": {},
        }

    def _parse_director_response(self, raw: str) -> Dict[str, Any]:
        """Extract the trailing JSON block from a Director reply (with fallback)."""
        match = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if not match:
            match = re.search(r'(\{[^{}]*"narration"[^{}]*\})', raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                data.setdefault("narration", raw.split("```")[0].strip())
                data.setdefault("choices", [])
                data.setdefault("skill_check", None)
                data.setdefault("xp", 0)
                data.setdefault("faction_shift", {})
                return data
            except json.JSONDecodeError:
                pass
        beat = self._fallback_beat(raw.strip() or "The path winds on.")
        return beat

    def _apply_beat(self, beat: Dict[str, Any]) -> None:
        """Apply a director beat's side effects (XP, faction shifts) to state."""
        if not self.state:
            return
        xp = int(beat.get("xp", 0) or 0)
        if xp > 0:
            result = self.state.gain_xp(xp)
            if result.get("leveled_up"):
                self.socketio.emit("level_up", result)
        for key, delta in (beat.get("faction_shift") or {}).items():
            try:
                self.state.adjust_standing(key, int(delta))
            except Exception:
                pass
        self.state.advance_turn(beat.get("narration", ""), beat.get("choices", []))
        self._sync_to_mcp()

    def _sync_to_mcp(self) -> None:
        """Push game state to the MCP framework scene node (defensive)."""
        if not self.state:
            return
        try:
            self.mcp.update_state(self.state.to_dict())
        except Exception:
            pass

    # ── Routes ───────────────────────────────────────────────────────

    def _setup_routes(self) -> None:
        app = self.app

        @app.route("/")
        def index():
            return render_template("verdant.html", **self.inject_navbar_context())

        @app.route("/api/scene/info")
        def scene_info():
            return jsonify(self.get_plugin_info())

        @app.route("/api/verdant/state")
        def verdant_state():
            if not self.state:
                return jsonify({"active": False})
            return jsonify({"active": True, **self.state.to_dict()})

        # ── New game ──
        @app.route("/api/verdant/new", methods=["POST"])
        def verdant_new():
            try:
                self.state = VerdantState()
                self._director_conv_id = None
                # Seed an opening quest.
                self.state.quest = {
                    "title": "The Verdant Schism",
                    "objective": "Discover why the canopy is dimming.",
                    "progress": 0, "goal": 3,
                }
                beat = self._director_infer(
                    "Begin a new adventure. The player arrives at the edge of the "
                    "Verdant Realms as the great canopy begins, inexplicably, to dim. "
                    "Set the scene in 2-3 paragraphs and present their first choices."
                )
                self._apply_beat(beat)
                companion = self._companion_infer(
                    "A new journey begins and the canopy is dimming. Offer one wry, "
                    "hopeful aside."
                )
                self.socketio.emit("verdant_state", self.state.to_dict())
                return jsonify({
                    "success": True,
                    "narration": beat.get("narration", ""),
                    "choices": beat.get("choices", []),
                    "companion": companion,
                    "state": self.state.to_dict(),
                })
            except Exception as exc:
                logger.error("[%s] new game failed (operation=game_start): %s", SCENE_ID, exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        # ── Unified player action ──
        @app.route("/api/verdant/action", methods=["POST"])
        def verdant_action():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game. Start a new one."}), 400
            data = request.get_json(silent=True) or {}
            action = (data.get("type") or "message").lower()
            handler = {
                "message": self._action_message,
                "choice": self._action_message,
                "roll_d20": self._action_roll_d20,
                "skill_check": self._action_skill_check,
                "combat": self._action_combat,
                "party": self._action_party,
                "end_turn": self._action_end_turn,
            }.get(action, self._action_message)
            try:
                return jsonify(handler(data))
            except Exception as exc:
                logger.error("[%s] action '%s' failed (operation=action): %s", SCENE_ID, action, exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        # ── Consequences (polled by the template; safe empty) ──
        @app.route("/api/consequences")
        def verdant_consequences():
            try:
                from engine.mechanics.consequences import get_consequence_store
                store = get_consequence_store()
                player_id = request.args.get("player_id", "player")
                return jsonify({
                    "recent": [c.to_dict() for c in store.get_history(player_id, limit=5)],
                    "pending": [c.to_dict() for c in store.get_pending(SCENE_ID, player_id)],
                })
            except Exception:
                # Mechanics optional — never break the scene.
                return jsonify({"recent": [], "pending": []})

    # ── Action handlers ──────────────────────────────────────────────

    def _action_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Free-text input or a menu choice → a new Director beat + Companion aside."""
        text = (data.get("text") or "").strip()
        choice_id = data.get("choice_id")
        if choice_id and not text:
            match = next((c for c in self.state.current_choices if c.get("id") == choice_id), None)
            text = match["text"] if match else f"option {choice_id}"
        prompt = f"The player says/does: {text}" if text else "The player waits and watches."
        beat = self._director_infer(prompt)
        self._apply_beat(beat)
        companion = self._companion_infer(
            f"The Director narrated: '{beat.get('narration', '')[:160]}'. React briefly."
        )
        state = self.state.to_dict()
        self.socketio.emit("turn_update", state)
        return {
            "narration": beat.get("narration", ""),
            "choices": beat.get("choices", []),
            "companion": companion,
            "state": state,
        }

    def _action_roll_d20(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Roll a raw d20 (luck-modified) and let the Director narrate the omen."""
        roll = self.state.roll_d20(self.state.stat_mod("luck"))
        self.socketio.emit("dice_roll", roll)
        flavour = "a triumphant" if roll["crit"] else "a doomed" if roll["fumble"] else "an uncertain"
        beat = self._director_infer(
            f"The player rolls the bones of fate: a natural {roll['natural']} "
            f"(total {roll['total']}) — {flavour} omen. Narrate what the realm answers."
        )
        self._apply_beat(beat)
        state = self.state.to_dict()
        self.socketio.emit("turn_update", state)
        return {"roll": roll, "narration": beat.get("narration", ""),
                "choices": beat.get("choices", []), "state": state}

    def _action_skill_check(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve a d20 skill check (skill+DC from the request, with defaults)."""
        skill = (data.get("skill") or random.choice(list(VERDANT_SKILLS))).lower()
        dc = int(data.get("dc", 15))
        result = self.state.skill_check(skill, dc)
        self.socketio.emit("dice_roll", result)
        verb = "succeeds at" if result["success"] else "fumbles"
        beat = self._director_infer(
            f"The player {verb} a {skill} check (rolled {result['total']} vs DC {dc}). "
            "Narrate the consequence and present the next choices."
        )
        if result["success"]:
            self.state.gain_xp(15)
        self._apply_beat(beat)
        state = self.state.to_dict()
        self.socketio.emit("turn_update", state)
        return {"check": result, "narration": beat.get("narration", ""),
                "choices": beat.get("choices", []), "state": state}

    def _action_combat(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Start or advance a lightweight turn-based skirmish."""
        if not self.state.combat:
            self.state.combat = {
                "enemy_name": data.get("enemy", "Bramble Stalker"),
                "enemy_hp": 22, "enemy_max_hp": 22, "round": 0,
            }
        c = self.state.combat
        c["round"] += 1
        atk = self.state.roll_d20(self.state.stat_mod("strength"))
        dmg = 0 if atk["fumble"] else random.randint(4, 9) + (4 if atk["crit"] else 0)
        c["enemy_hp"] = max(0, c["enemy_hp"] - dmg)
        # Enemy strikes back unless defeated.
        enemy_dmg = 0
        if c["enemy_hp"] > 0:
            enemy_dmg = random.randint(2, 6)
            self.state.player_stats["hp"] = max(0, self.state.player_stats["hp"] - enemy_dmg)
        defeated = c["enemy_hp"] <= 0
        beat_prompt = (
            f"Combat round {c['round']} vs the {c['enemy_name']}: the player deals {dmg} "
            f"({'CRIT! ' if atk['crit'] else ''}{'MISS! ' if atk['fumble'] else ''}), "
            f"enemy at {c['enemy_hp']}/{c['enemy_max_hp']} HP"
            + (f", strikes back for {enemy_dmg}." if not defeated else " — and falls!")
            + " Narrate the exchange."
        )
        beat = self._director_infer(beat_prompt)
        if defeated:
            self.state.gain_xp(40)
            self.state.combat = None
            if self.state.quest:
                self.state.quest["progress"] = min(
                    self.state.quest["goal"], self.state.quest["progress"] + 1)
        self._apply_beat(beat)
        state = self.state.to_dict()
        self.socketio.emit("combat_update", {"defeated": defeated, "player_damage": dmg,
                                             "enemy_damage": enemy_dmg, "state": state})
        return {"defeated": defeated, "player_damage": dmg, "enemy_damage": enemy_dmg,
                "narration": beat.get("narration", ""),
                "choices": beat.get("choices", []), "state": state}

    def _action_party(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Companion takes the lead for a beat — a loyalty-warming aside + boon."""
        self.state.companion_loyalty = min(100, self.state.companion_loyalty + 2)
        aside = self._companion_infer(
            "Step forward and take the lead for a moment — rally the player with a "
            "short, heartfelt line, then a plan."
        )
        if self.state.player_stats["mp"] < self.state.player_stats["max_mp"]:
            self.state.player_stats["mp"] = min(
                self.state.player_stats["max_mp"], self.state.player_stats["mp"] + 3)
        state = self.state.to_dict()
        self.socketio.emit("turn_update", state)
        return {"companion": aside, "state": state}

    def _action_end_turn(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Pass the turn — Director advances the world a beat on its own."""
        self.state.director_threads = min(5, self.state.director_threads + 1)
        beat = self._director_infer(
            "The player waits. The realm moves on its own — advance the world a beat, "
            "introduce a complication, and present fresh choices."
        )
        self._apply_beat(beat)
        state = self.state.to_dict()
        self.socketio.emit("turn_update", state)
        return {"narration": beat.get("narration", ""),
                "choices": beat.get("choices", []), "state": state}

    # ── SocketIO ─────────────────────────────────────────────────────

    def _setup_socketio(self) -> None:
        @self.socketio.on("connect")
        def on_connect():
            if self.state:
                self.socketio.emit("verdant_state", self.state.to_dict())

        @self.socketio.on("get_verdant_state")
        def on_get_state():
            self.socketio.emit(
                "verdant_state",
                self.state.to_dict() if self.state else {"active": False},
            )

    # ── Lifecycle ────────────────────────────────────────────────────

    def on_before_serve(self) -> None:
        """Register MCP timer / framework hooks before serving (defensive)."""
        try:
            get_framework()  # warm the singleton; safe no-op if unavailable
        except Exception:
            pass
