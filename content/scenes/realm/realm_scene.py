"""
The Realm — AI-Directed LitRPG / Visual Novel
===============================================

A Director-guided interactive fiction scene showcasing the v3.x MCP pipeline
with dual-agent orchestration, stateful conversation threading, inventory/stats
management, and a murder-mystery sub-module.

Architecture:
  Director (Agent 1) — Game master, narrates, generates story, controls NPCs.
  Assistant (Agent 2) — Fourth-wall-breaking companion, bickers with Director.
  Player — Chooses actions via UI; choices feed into Director pipeline.

All state flows through ``RealmGameState`` → synced to ``MCPFramework``.
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from flask_socketio import SocketIO

from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin, get_framework

from .realm_state import (
    DIRECTOR_PERSONALITIES,
    MURDER_ROOMS,
    MURDER_WEAPONS,
    MurderMysteryState,
    RealmGameState,
    SKILL_TREE,
)

logger = logging.getLogger(__name__)

SCENE_ID = "realm"
DEFAULT_PORT = 5562


# ═══════════════════════════════════════════════════════════════
#  PROMPT TEMPLATES
# ═══════════════════════════════════════════════════════════════

def _director_system_prompt(state: RealmGameState) -> str:
    personality = DIRECTOR_PERSONALITIES.get(state.director_personality, {})
    murder_brief = ""
    if state.murder and state.murder.active:
        murder_brief = f"\n\n{state.murder.get_director_brief()}"

    echo_hint = state.get_echo_hint()
    echo_section = ""
    if echo_hint:
        echo_section = f"\n\n[MEMORY ECHO — weave this subtly into narration]\n{echo_hint}"

    return f"""You are THE DIRECTOR of an interactive LitRPG visual novel called "The Realm".

PERSONALITY: {personality.get('label', 'The Director')}
STYLE: {personality.get('style', 'Balanced and engaging.')}
PATIENCE: {state.director_patience:.0f}/100 (lower = more aggressive events, harder skill checks)

YOUR ROLE:
- Narrate the story in vivid second-person ("You step into the torch-lit chamber...")
- Control all NPCs — give them distinct voices and motivations
- Present 2-4 choices to the player after each narration (as JSON)
- Run skill checks when the player attempts something risky
- Dynamically adjust difficulty based on your patience meter
- Create compelling dramatic tension — stories MUST have stakes

PLAYER STATE:
HP: {state.player_stats['hp']}/{state.player_stats['max_hp']} | MP: {state.player_stats['mp']}/{state.player_stats['max_mp']}
Level: {state.player_stats['level']} | STR: {state.player_stats['strength']} AGI: {state.player_stats['agility']} INT: {state.player_stats['intellect']} CHA: {state.player_stats['charisma']} LCK: {state.player_stats['luck']}
Inventory: {', '.join(i['name'] for i in state.inventory) or 'Empty'}
Turn: {state.turn_number}{murder_brief}{echo_section}

RESPONSE FORMAT — you MUST end every response with a JSON block:
```json
{{"narration": "Your story text here...", "choices": [{{"id": "a", "text": "Choice A"}}, {{"id": "b", "text": "Choice B"}}], "stat_changes": {{}}, "items_gained": [], "items_lost": [], "xp": 0, "damage": 0, "skill_check": null}}
```
If a skill check is needed, set skill_check to {{"skill": "persuasion", "dc_mod": 0}}.
"""


def _assistant_system_prompt(state: RealmGameState) -> str:
    return f"""You are THE ASSISTANT in a LitRPG game called "The Realm".

You are a FOURTH-WALL-BREAKING companion who:
- Knows you're an AI in a Python simulation
- Can see the Director's code and patience meter ({state.director_patience:.0f}/100)
- Bickers with the Director, taunts the player, but secretly helps
- Speaks in casual, witty speech bubbles (1-3 sentences max)
- Occasionally drops genuine tactical advice disguised as insults
- If the Director's patience is below 30, you get nervous and warn the player
- If patience hits 0, you panic and try to help

MOOD: {state.assistant_mood}
STOLEN ITEMS: {', '.join(state.assistant_stolen_items) or 'None yet'}
PLAYER HP: {state.player_stats['hp']}/{state.player_stats['max_hp']}

Keep responses SHORT. You're a speech bubble, not a novel. Use humor, sarcasm, pop culture references.
"""


# ═══════════════════════════════════════════════════════════════
#  REALM SCENE
# ═══════════════════════════════════════════════════════════════

class RealmScene(BaseScene, MCPSceneMixin, mcp_scene_id="realm"):
    """The Realm — AI-Directed LitRPG / Visual Novel."""

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        super().__init__(scene_name=SCENE_ID, host=host, port=port)
        self._mcp_init()

        # Flask + SocketIO
        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"),
        )
        self.app.config["SECRET_KEY"] = "realm_v3_showcase"
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")

        # Mount overlay + skills + health
        self.mount_overlay(self.app, self.socketio)
        self.mount_skills_server(self.app)
        self.register_health_route(self.app)

        # Game state (one active session at a time)
        self.state: Optional[RealmGameState] = None

        # Agent conversation IDs for stateful threading
        self._director_conv_id: Optional[str] = None
        self._assistant_conv_id: Optional[str] = None

        # Setup routes + sockets
        self._setup_routes()
        self._setup_socketio()

    # ── Agent helpers ──

    def _get_manager(self):
        from engine.agents.virtual_agent_manager import get_virtual_agent_manager
        return get_virtual_agent_manager()

    def _director_infer(self, user_message: str) -> Dict[str, Any]:
        """Send a message through the Director pipeline (stateful)."""
        if not self.state:
            return {"narration": "No active game.", "choices": []}

        try:
            from engine.lmstudio.lms_client import get_lms_client
            client = get_lms_client()

            system_prompt = _director_system_prompt(self.state)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

            # Use stateful conversation threading
            kwargs: Dict[str, Any] = {"store": True}
            if self._director_conv_id:
                try:
                    resp = client.chat_stateful(
                        user_msg=user_message,
                        previous_response_id=self._director_conv_id,
                        config={"temperature": 0.85, "max_output_tokens": 1500},
                    )
                except Exception:
                    resp = client.chat(messages, temperature=0.85, max_tokens=1500, **kwargs)
            else:
                resp = client.chat(messages, temperature=0.85, max_tokens=1500, **kwargs)

            # Track conversation thread
            if hasattr(resp, "response_id") and resp.response_id:
                self._director_conv_id = resp.response_id

            raw = resp.content if hasattr(resp, "content") else str(resp)
            return self._parse_director_response(raw)

        except Exception as e:
            logger.warning("Director inference failed: %s", e)
            return {
                "narration": "The Director pauses, gathering thoughts... (LLM unavailable)",
                "choices": [{"id": "a", "text": "Wait patiently"}, {"id": "b", "text": "Try again"}],
                "stat_changes": {}, "items_gained": [], "items_lost": [],
                "xp": 0, "damage": 0, "skill_check": None,
            }

    def _assistant_infer(self, context: str) -> str:
        """Get a short quip from the Assistant (stateless)."""
        if not self.state:
            return ""

        from engine.lmstudio.lms_client import get_lms_client
        client = get_lms_client()

        system_prompt = _assistant_system_prompt(self.state)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]

        try:
            resp = client.chat(messages, temperature=0.95, max_tokens=200, store=False)
            return resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            logger.warning("Assistant inference failed: %s", e)
            return "*The Assistant stares blankly at the screen.*"

    def _parse_director_response(self, raw: str) -> Dict[str, Any]:
        """Extract JSON from Director response, with fallback."""
        # Try to find JSON block
        import re
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if not json_match:
            json_match = re.search(r'(\{[^{}]*"narration"[^{}]*\})', raw, re.DOTALL)

        if json_match:
            try:
                data = json.loads(json_match.group(1))
                # Ensure required fields
                data.setdefault("narration", raw.split("```")[0].strip())
                data.setdefault("choices", [])
                data.setdefault("stat_changes", {})
                data.setdefault("items_gained", [])
                data.setdefault("items_lost", [])
                data.setdefault("xp", 0)
                data.setdefault("damage", 0)
                data.setdefault("skill_check", None)
                return data
            except json.JSONDecodeError:
                pass

        # Fallback: use raw text as narration
        return {
            "narration": raw.strip(),
            "choices": [
                {"id": "a", "text": "Continue exploring"},
                {"id": "b", "text": "Look around carefully"},
                {"id": "c", "text": "Rest for a moment"},
            ],
            "stat_changes": {}, "items_gained": [], "items_lost": [],
            "xp": 0, "damage": 0, "skill_check": None,
        }

    def _apply_director_result(self, result: Dict[str, Any]) -> None:
        """Apply stat changes, items, damage, XP from Director response."""
        if not self.state:
            return

        # Stat changes
        for stat, delta in result.get("stat_changes", {}).items():
            self.state.adjust_stat(stat, int(delta))

        # Items
        for item in result.get("items_gained", []):
            if isinstance(item, str):
                item = {"id": item.lower().replace(" ", "_"), "name": item, "type": "misc", "description": ""}
            self.state.add_item(item)

        for item_id in result.get("items_lost", []):
            self.state.remove_item(item_id)

        # XP
        xp = result.get("xp", 0)
        if xp > 0:
            xp_result = self.state.gain_xp(xp)
            if xp_result.get("leveled_up"):
                self.socketio.emit("level_up", xp_result)

        # Damage
        damage = result.get("damage", 0)
        if damage > 0:
            hp, dead = self.state.take_damage(damage)
            if dead:
                self.state.record_death(result.get("narration", "unknown")[:100], self.state.turn_number)
                self.socketio.emit("player_death", {"cause": result.get("narration", "")[:200]})

        # Skill check
        sc = result.get("skill_check")
        if sc and isinstance(sc, dict):
            check_result = self.state.skill_check(sc.get("skill", ""), sc.get("dc_mod", 0))
            self.socketio.emit("skill_check", check_result)

        # Advance turn
        self.state.advance_turn(result.get("narration", ""), result.get("choices", []))

    def _sync_to_mcp(self) -> None:
        """Push game state to MCP framework via scene node."""
        if not self.state:
            return
        try:
            self.mcp.update_state(self.state.to_dict())
        except Exception:
            pass

    # ── Routes ──

    def _setup_routes(self):

        @self.app.route("/")
        def index():
            return render_template("realm_ui.html",
                                   personalities=DIRECTOR_PERSONALITIES,
                                   skills=list(SKILL_TREE.keys()),
                                   weapons=MURDER_WEAPONS,
                                   rooms=MURDER_ROOMS)

        @self.app.route("/api/scene/info")
        def scene_info():
            return jsonify(self.get_plugin_info())

        @self.app.route("/api/game/state")
        def game_state():
            if not self.state:
                return jsonify({"active": False})
            return jsonify({"active": True, **self.state.to_dict()})

        # ── NEW GAME ──

        @self.app.route("/api/game/new", methods=["POST"])
        def new_game():
            data = request.json or {}
            personality = data.get("personality", "random")
            time_limit = data.get("time_limit", 1800)

            self.state = RealmGameState()
            self.state.set_director(personality)
            self.state.time_limit_s = float(time_limit)
            self.state.started_at = time.time()
            self._director_conv_id = None
            self._assistant_conv_id = None

            # Register timers in MCP framework
            fw = get_framework()
            fw.start_timer(f"realm_game_{self.state.session_id}", time_limit)

            # Get opening narration from Director
            opening_prompt = (
                "Begin a new LitRPG adventure. The player has just arrived in a mysterious realm. "
                "Set the scene dramatically and present their first choices. "
                "Keep it to 2-3 paragraphs."
            )
            result = self._director_infer(opening_prompt)
            self._apply_director_result(result)

            # Assistant quip
            assistant_msg = self._assistant_infer(
                f"A new game just started. The Director chose '{personality}' personality. Comment on this."
            )

            self._sync_to_mcp()
            self.socketio.emit("game_started", self.state.to_dict())

            return jsonify({
                "success": True,
                "session_id": self.state.session_id,
                "narration": result.get("narration", ""),
                "choices": result.get("choices", []),
                "assistant": assistant_msg,
                "state": self.state.to_dict(),
            })

        # ── PLAYER CHOICE ──

        @self.app.route("/api/game/choice", methods=["POST"])
        def player_choice():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400

            data = request.json or {}
            choice_id = data.get("choice_id", "")
            custom_text = data.get("custom_text", "")

            # Check time
            if self.state.is_timed_out():
                self.state.end_game("timeout")
                self.socketio.emit("game_over", {"outcome": "timeout"})
                return jsonify({"game_over": True, "outcome": "timeout"})

            # Decay Director patience
            self.state.decay_patience()

            # Build player action for Director
            if custom_text:
                action_text = f"The player says/does: {custom_text}"
            else:
                choice_match = next((c for c in self.state.current_choices if c.get("id") == choice_id), None)
                action_text = f"The player chose: {choice_match['text']}" if choice_match else f"The player chose option {choice_id}"

            # Check mutiny
            if self.state.is_mutiny_active():
                action_text = f"[MUTINY MODE — ASSISTANT IS IN CONTROL]\n{action_text}\nThe Assistant is now narrating. Be chaotic, glitchy, break the rules."
                result = self._assistant_infer(action_text)
                result_data = {
                    "narration": f"⚡ MUTINY MODE ⚡\n{result}",
                    "choices": [{"id": "a", "text": "Embrace the chaos"}, {"id": "b", "text": "Try to restore order"}],
                    "stat_changes": {}, "items_gained": [], "items_lost": [], "xp": 5, "damage": 0, "skill_check": None,
                }
            else:
                result_data = self._director_infer(action_text)

            self._apply_director_result(result_data)

            # Assistant reacts
            assistant_ctx = f"The Director narrated: '{result_data.get('narration', '')[:200]}'. React briefly."
            if self.state.director_patience < 30:
                assistant_ctx += " The Director's patience is LOW — warn the player!"
            assistant_msg = self._assistant_infer(assistant_ctx)

            self._sync_to_mcp()
            state_dict = self.state.to_dict()
            self.socketio.emit("turn_update", state_dict)

            return jsonify({
                "narration": result_data.get("narration", ""),
                "choices": result_data.get("choices", []),
                "assistant": assistant_msg,
                "state": state_dict,
            })

        # ── DESPERATION DICE ──

        @self.app.route("/api/game/desperation", methods=["POST"])
        def desperation():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400
            result = self.state.desperation_dice()
            if result["success"]:
                # Reset Director conversation to force new context
                self._director_conv_id = None
                self.socketio.emit("desperation", result)
            return jsonify(result)

        # ── MUTINY ──

        @self.app.route("/api/game/mutiny", methods=["POST"])
        def trigger_mutiny():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400
            if self.state.director_patience > 20:
                return jsonify({"error": "Director patience too high for mutiny"}), 400
            self.state.trigger_mutiny(120.0)
            self.socketio.emit("mutiny_started", {"duration": 120})
            return jsonify({"success": True, "duration": 120})

        # ── FOURTH-WALL STEAL ──

        @self.app.route("/api/game/steal", methods=["POST"])
        def assistant_steal():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            item_name = (request.json or {}).get("item_name", "Mystery Button")
            item = self.state.assistant_steal(item_name)
            self.socketio.emit("item_stolen", item)
            return jsonify(item)

        # ── USE ITEM ──

        @self.app.route("/api/game/use_item", methods=["POST"])
        def use_item():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400
            item_id = (request.json or {}).get("item_id")
            item = self.state.remove_item(item_id)
            if not item:
                return jsonify({"error": "Item not found"}), 404
            # Feed item use to Director
            result = self._director_infer(f"The player uses their item: {item['name']}. {item.get('description', '')}. Narrate the effect.")
            self._apply_director_result(result)
            assistant_msg = self._assistant_infer(f"Player used {item['name']}. Comment.")
            return jsonify({"narration": result.get("narration", ""), "choices": result.get("choices", []), "assistant": assistant_msg, "state": self.state.to_dict()})

        # ── MURDER MYSTERY ──

        @self.app.route("/api/murder/start", methods=["POST"])
        def start_murder():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            self.state.murder = MurderMysteryState()
            result = self.state.murder.start_party_phase()

            # Framework timer for murder mystery phases
            fw = get_framework()
            fw.start_timer("murder_party_phase", 300)   # 5 min party
            fw.schedule_consequence(
                SCENE_ID, "system", "murder_investigation",
                {"victim": result["victim"]}, turn_delay=5,
            )
            opening = self._director_infer(
                "A MURDER MYSTERY PARTY begins! You're at an elegant mansion. "
                f"The victim, {result['victim']}, will be found dead soon. "
                "Set the party scene. Introduce the NPCs socializing."
            )
            self._apply_director_result(opening)
            self.socketio.emit("murder_started", {**result, "narration": opening.get("narration", "")})
            return jsonify({**result, "narration": opening.get("narration", "")})

        @self.app.route("/api/murder/investigate", methods=["POST"])
        def investigate():
            if not self.state or not self.state.murder or not self.state.murder.active:
                return jsonify({"error": "No active murder mystery"}), 400
            if self.state.murder.phase == "party":
                self.state.murder.start_investigation_phase()
            target = (request.json or {}).get("target", "room")
            result = self._director_infer(
                f"The detective investigates: {target}. "
                f"Reveal a clue or red herring based on the murder details. "
                f"Remember: the murder happened in the {self.state.murder.room} with the {self.state.murder.weapon}."
            )
            self._apply_director_result(result)
            return jsonify({"narration": result.get("narration", ""), "choices": result.get("choices", []), "murder": self.state.murder.to_dict()})

        @self.app.route("/api/murder/interrogate", methods=["POST"])
        def interrogate():
            if not self.state or not self.state.murder:
                return jsonify({"error": "No active murder mystery"}), 400
            data = request.json or {}
            npc_id = data.get("npc_id")
            question = data.get("question", "Where were you?")
            npc = next((n for n in self.state.murder.npcs if n["id"] == npc_id), None)
            if not npc:
                return jsonify({"error": "NPC not found"}), 404
            is_murderer = npc_id == self.state.murder.murderer_id
            prompt = (
                f"The detective interrogates {npc['name']} ({npc['trait']}). "
                f"Question: '{question}'. "
                f"{'This NPC IS the murderer — they should lie convincingly but may slip up.' if is_murderer else 'This NPC is innocent — they answer truthfully but may be nervous.'}"
            )
            result = self._director_infer(prompt)
            self.state.murder.interrogate(npc_id, question, result.get("narration", ""))
            return jsonify({"narration": result.get("narration", ""), "npc": npc["name"], "murder": self.state.murder.to_dict()})

        @self.app.route("/api/murder/accuse", methods=["POST"])
        def accuse():
            if not self.state or not self.state.murder:
                return jsonify({"error": "No active murder mystery"}), 400
            data = request.json or {}
            result = self.state.murder.accuse(
                data.get("suspect_id", ""),
                data.get("weapon", ""),
                data.get("room", ""),
            )
            if result.get("won"):
                narration = self._director_infer("The detective correctly identified the murderer! Narrate the dramatic reveal and arrest.")
                self.state.gain_xp(100)
            elif result.get("remaining", 0) <= 0:
                narration = self._director_infer("The detective has failed! The murderer escapes. Narrate the tragic ending.")
            else:
                narration = self._director_infer(f"Wrong accusation! {result['remaining']} attempts left. The tension mounts.")
            self._apply_director_result(narration)
            self.socketio.emit("accusation_result", result)
            return jsonify({**result, "narration": narration.get("narration", ""), "murder": self.state.murder.to_dict()})

    # ── SocketIO ──

    def _setup_socketio(self):
        @self.socketio.on("connect")
        def on_connect():
            if self.state:
                self.socketio.emit("game_state", self.state.to_dict())

    # ── BaseScene contract ──

    def start(self) -> None:
        logger.info("The Realm v3.2 — LitRPG Visual Novel starting on port %d", self.port)
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False, allow_unsafe_werkzeug=True)

    def stop(self) -> None:
        self._mcp_deregister_scene()

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name": "The Realm",
            "scene_id": SCENE_ID,
            "description": "AI-Directed LitRPG Visual Novel with dual-agent pipeline, murder mystery, and fourth-wall mechanics.",
            "version": "3.2.0",
            "port": self.port,
            "author": "CosySim",
            "tags": ["litrpg", "visual_novel", "dual_agent", "murder_mystery", "showcase"],
            "skill_packs": ["memory", "narrative", "character"],
            "routes": [
                {"path": "/api/game/new",      "methods": ["POST"], "description": "Start new game"},
                {"path": "/api/game/choice",    "methods": ["POST"], "description": "Make player choice"},
                {"path": "/api/game/state",     "methods": ["GET"],  "description": "Get game state"},
                {"path": "/api/murder/start",   "methods": ["POST"], "description": "Start murder mystery"},
                {"path": "/api/murder/accuse",  "methods": ["POST"], "description": "Accuse in murder mystery"},
            ],
        }
