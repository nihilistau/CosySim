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

from flask import jsonify, render_template, request
from flask_socketio import SocketIO

from engine.scenes.flask_scene import FlaskScene
from engine.mcp.framework import get_framework

from .realm_state import (
    DIRECTOR_PERSONALITIES,
    EQUIPMENT_SLOTS,
    ITEM_CATALOG,
    MURDER_ROOMS,
    MURDER_WEAPONS,
    MurderMysteryState,
    REALM_LOCATIONS,
    RealmGameState,
    SKILL_TREE,
)
from content.shared import register_shared_assets
from engine.mcp.scene_state import get_scene_state_manager
from engine.mcp.tag_registry import TagRegistry
from content.scenes.realm.realm_rules import register_realm_rules

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

    loc = REALM_LOCATIONS.get(state.current_location, {})
    location_section = f"\nLOCATION: {loc.get('name', state.current_location)} — {loc.get('description', '')}"
    connections = loc.get("connections", [])
    if connections:
        conn_names = [REALM_LOCATIONS.get(c, {}).get("name", c) for c in connections]
        location_section += f"\nConnected to: {', '.join(conn_names)}"

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
Level: {state.player_stats['level']} | Gold: {state.player_stats.get('gold', 0)}
STR: {state.player_stats['strength']} AGI: {state.player_stats['agility']} INT: {state.player_stats['intellect']} CHA: {state.player_stats['charisma']} LCK: {state.player_stats['luck']}
Inventory: {', '.join(i['name'] for i in state.inventory) or 'Empty'}
Turn: {state.turn_number}{location_section}{murder_brief}{echo_section}

COMBAT ACTIONS: attack (d20+STR vs defense), defend (halve damage), flee (d20+AGI vs DC12), use_item

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

# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class RealmScene(FlaskScene):
    """The Realm — AI-Directed LitRPG / Visual Novel."""

    SCENE_METADATA = {
        "name": "realm",
        "display_name": "THE SHATTERED THRONE",
        "port": 5562,
        "type": "rpg",
        "accent_color": "#059669",
        "accent_rgb": "5 150 105",
        "description": "The throne is broken. The king is dead. Power is yours to take — or lose.",
        # Legacy fields retained for compatibility
        "genre": "dark_fantasy_rpg",
        "max_characters": 4,
        "features": [
            "dark_story_arcs", "magic_system", "sanity_mechanic",
            "combat", "quests", "murder_mystery", "dual_agent",
        ],
    }

    # v1.51.0 [2026-03-22] — Migrated to FlaskScene
    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        super().__init__(host=host, port=port)

        self.app.config["SECRET_KEY"] = "realm_shattered_throne_v068"

        # v1.51.0 — FlaskScene registers health, hud, announcer, inventory, tts
        self.mount_overlay(self.app, self.socketio)
        self.mount_skills_server(self.app)
        self.register_bench_route(self.app, self.socketio)

        # Game state (one active session at a time)
        self.state: Optional[RealmGameState] = None

        # Agent conversation IDs for stateful threading
        self._director_conv_id: Optional[str] = None
        self._assistant_conv_id: Optional[str] = None

        # Setup routes + sockets
        self._setup_routes()
        self._setup_socketio()

        # Framework integration
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()

        # MCP rules
        register_realm_rules()

        # v1.51.0 — FlaskScene handles Nexus connection

    # ── Agent helpers──

    def _get_manager(self):
        from engine.agents.virtual_agent_manager import get_virtual_agent_manager
        return get_virtual_agent_manager()

    def _director_infer(self, user_message: str) -> Dict[str, Any]:
        """Send a message through the Director pipeline via VirtualAgentManager with governance."""
        if not self.state:
            return {"narration": "No active game.", "choices": []}

        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            from engine.mcp.comms_framework import build_governance_context

            mgr = get_virtual_agent_manager()

            system_prompt = _director_system_prompt(self.state)
            gov_ctx = build_governance_context("realm_director", "realm", user_message)
            if gov_ctx:
                system_prompt = f"{system_prompt}\n\n{gov_ctx}"

            req = InferenceRequest(
                agent_id="realm_director",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.85,
                max_output_tokens=1500,
                conversation_id=f"realm_director_{self.state.session_id}",
                previous_response_id=self._director_conv_id,
                store=True,
                metadata={"scene": "realm", "role": "director"},
            )
            proc = mgr.infer_processed(req)

            # Track conversation thread
            if proc.response_id:
                self._director_conv_id = proc.response_id

            raw = proc.clean_text or proc.raw_text or ""
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
        """Get a short quip from the Assistant via VirtualAgentManager with governance."""
        if not self.state:
            return ""

        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            from engine.mcp.comms_framework import build_governance_context

            mgr = get_virtual_agent_manager()

            system_prompt = _assistant_system_prompt(self.state)
            gov_ctx = build_governance_context("realm_assistant", "realm", context)
            if gov_ctx:
                system_prompt = f"{system_prompt}\n\n{gov_ctx}"

            req = InferenceRequest(
                agent_id="realm_assistant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": context},
                ],
                temperature=0.95,
                max_output_tokens=200,
                conversation_id=f"realm_assistant_{self.state.session_id}",
                store=False,
                metadata={"scene": "realm", "role": "assistant"},
            )
            proc = mgr.infer_processed(req)
            return (proc.clean_text or proc.raw_text or "").strip()
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

        # Sync significant changes to Coordinator for cross-system visibility
        stat_changes = result.get("stat_changes", {})
        if stat_changes:
            try:
                from engine.mcp.state_coordinator import get_coordinator
                coord = get_coordinator()
                mapped = {}
                if "hp" in stat_changes:
                    mapped["energy"] = stat_changes["hp"]
                coord.update("realm_player", source="realm_director", scene="realm", **mapped)
            except Exception:
                pass
            try:
                self._state_mgr.add_narrative("realm", f"Stats changed: {stat_changes}")
            except Exception:
                pass

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
            try:
                from engine.mcp.state_coordinator import get_coordinator
                get_coordinator().update(
                    "realm_player", source="realm_xp", scene="realm",
                    xp=xp, level=self.state.player_stats.get("level", 1),
                )
            except Exception:
                pass

        # Damage
        damage = result.get("damage", 0)
        if damage > 0:
            hp, dead = self.state.take_damage(damage)
            if dead:
                self.state.record_death(result.get("narration", "unknown")[:100], self.state.turn_number)
                self.socketio.emit("player_death", {"cause": result.get("narration", "")[:200]})
            try:
                from engine.mcp.state_coordinator import get_coordinator
                get_coordinator().update(
                    "realm_player", source="realm_combat", scene="realm",
                    energy=-(damage), hp=self.state.player_stats.get("hp", 0),
                )
            except Exception:
                pass

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
            return render_template(
                "realm.html",
                personalities=DIRECTOR_PERSONALITIES,
                skills=list(SKILL_TREE.keys()),
                weapons=MURDER_WEAPONS,
                rooms=MURDER_ROOMS,
                **self.inject_navbar_context(),
            )

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
            try:
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
                try:
                    fw = get_framework()
                    fw.start_timer(f"realm_game_{self.state.session_id}", time_limit)
                except Exception:
                    pass

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
            except Exception as exc:
                logger.error("new_game failed: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

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
            try:
                self.state.murder = MurderMysteryState()
                result = self.state.murder.start_party_phase()

                # Framework timer for murder mystery phases
                try:
                    fw = get_framework()
                    fw.start_timer("murder_party_phase", 300)   # 5 min party
                    fw.schedule_consequence(
                        SCENE_ID, "system", "murder_investigation",
                        {"victim": result["victim"]}, turn_delay=5,
                    )
                except Exception:
                    pass

                opening = self._director_infer(
                    "A MURDER MYSTERY PARTY begins! You're at an elegant mansion. "
                    f"The victim, {result['victim']}, will be found dead soon. "
                    "Set the party scene. Introduce the NPCs socializing."
                )
                self._apply_director_result(opening)
                self.socketio.emit("murder_started", {**result, "narration": opening.get("narration", "")})
                return jsonify({**result, "narration": opening.get("narration", "")})
            except Exception as exc:
                logger.error("start_murder failed: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

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

        # ── Combat Routes ──

        @self.app.route("/api/combat/start", methods=["POST"])
        def combat_start():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            data = request.get_json(silent=True) or {}
            enemy_key = data.get("enemy")
            result = self.state.start_combat(enemy_key)
            if "error" in result:
                return jsonify(result), 400
            # Director narrates the encounter start
            narration = self._director_infer(
                f"A {result['enemy_name']} appears! It has {result['enemy_hp']} HP. "
                "Narrate the dramatic encounter beginning. Give the player combat choices: attack, flee, or use an item."
            )
            self._apply_director_result(narration)
            self.socketio.emit("combat_started", result)
            return jsonify({**result, "narration": narration.get("narration", "")})

        @self.app.route("/api/combat/attack", methods=["POST"])
        def combat_attack():
            if not self.state or not self.state.combat:
                return jsonify({"error": "Not in combat"}), 400
            result = self.state.combat_attack()
            if result.get("defeated"):
                narration = self._director_infer(
                    f"The player defeated the {self.state.combat.enemy_name if self.state.combat else 'enemy'}! "
                    f"{'CRITICAL HIT! ' if result.get('crit') else ''}"
                    f"They dealt {result['player_damage']} damage. "
                    f"XP gained: {result.get('xp_gained', 0)}. "
                    f"{'Loot found: ' + result['loot']['name'] + '!' if result.get('loot') else 'No loot this time.'} "
                    "Narrate the victory and suggest what to do next."
                )
            else:
                narration = self._director_infer(
                    f"Combat turn: Player {'MISSED!' if result.get('miss') else 'dealt ' + str(result.get('player_damage', 0)) + ' damage'}. "
                    f"Enemy has {result['enemy_hp']} HP remaining. "
                    f"Enemy strikes back for {result['enemy_damage']} damage. "
                    f"Player HP: {result['player_hp']}. "
                    "Narrate the exchange and present combat choices."
                )
            self._apply_director_result(narration)
            event = "combat_victory" if result.get("defeated") else "combat_turn"
            self.socketio.emit(event, result)
            return jsonify({**result, "narration": narration.get("narration", "")})

        @self.app.route("/api/combat/flee", methods=["POST"])
        def combat_flee():
            if not self.state or not self.state.combat:
                return jsonify({"error": "Not in combat"}), 400
            result = self.state.combat_flee()
            if result.get("fled"):
                narration = self._director_infer("The player successfully fled from combat! Narrate their escape.")
            else:
                narration = self._director_infer(
                    f"The player tried to flee but failed! The enemy struck them for {result.get('enemy_damage', 0)} damage. "
                    f"Player HP: {result.get('player_hp', '?')}. Continue the combat."
                )
            self._apply_director_result(narration)
            self.socketio.emit("combat_flee", result)
            return jsonify({**result, "narration": narration.get("narration", "")})

        @self.app.route("/api/combat/defend", methods=["POST"])
        def combat_defend():
            if not self.state or not self.state.combat:
                return jsonify({"error": "Not in combat"}), 400
            result = self.state.combat_defend()
            if "error" in result:
                return jsonify(result), 400
            narration = self._director_infer(
                f"The player raises their guard and braces for impact! "
                f"The {result.get('enemy_name', 'enemy')} strikes but the blow is softened — "
                f"only {result.get('enemy_damage', 0)} damage gets through. "
                f"Player HP: {result.get('player_hp', '?')}. "
                "Narrate the defensive stance and present combat choices."
            )
            self._apply_director_result(narration)
            self.socketio.emit("combat_defend", result)
            return jsonify({**result, "narration": narration.get("narration", "")})

        @self.app.route("/api/combat/use_item", methods=["POST"])
        def combat_use_item():
            if not self.state or not self.state.combat:
                return jsonify({"error": "Not in combat"}), 400
            data = request.get_json(silent=True) or {}
            item_id = data.get("item_id")
            if not item_id:
                return jsonify({"error": "item_id required"}), 400
            result = self.state.combat_use_item(item_id)
            if "error" in result:
                return jsonify(result), 400
            parts = [f"The player uses {result.get('item_name', 'an item')} mid-combat!"]
            if result.get("healed"):
                parts.append(f"Healed {result['healed']} HP.")
            if result.get("restored_mp"):
                parts.append(f"Restored {result['restored_mp']} MP.")
            if result.get("item_damage"):
                parts.append(f"Dealt {result['item_damage']} damage to the enemy!")
            if result.get("enemy_damage", 0) > 0:
                parts.append(f"Enemy strikes back for {result['enemy_damage']} damage.")
            parts.append(f"Player HP: {result.get('player_hp', '?')} | Enemy HP: {result.get('enemy_hp', '?')}.")
            if result.get("defeated"):
                parts.append("The enemy is defeated!")
            narration = self._director_infer(" ".join(parts) + " Narrate the action.")
            self._apply_director_result(narration)
            event = "combat_victory" if result.get("defeated") else "combat_item_used"
            self.socketio.emit(event, result)
            # Sync item usage to coordinator
            try:
                from engine.mcp.state_coordinator import get_coordinator
                get_coordinator().update(
                    "realm_player", source="realm_combat_item", scene="realm",
                    hp=self.state.player_stats.get("hp", 0),
                )
            except Exception:
                pass
            return jsonify({**result, "narration": narration.get("narration", "")})

        # ── Location Routes ──

        @self.app.route("/api/location/current")
        def location_current():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            return jsonify(self.state.get_location_info())

        @self.app.route("/api/location/move", methods=["POST"])
        def location_move():
            if not self.state or self.state.ended:
                return jsonify({"error": "No active game"}), 400
            data = request.get_json(silent=True) or {}
            destination = data.get("destination")
            if not destination:
                return jsonify({"error": "destination required"}), 400
            result = self.state.move_to_location(destination)
            if "error" in result:
                return jsonify(result), 400
            # Director narrates the journey
            encounter_text = ""
            if result.get("encounter"):
                enc = result["encounter"]
                encounter_text = (
                    f" A {enc.get('enemy_name', 'creature')} blocks the path! "
                    f"Enemy HP: {enc.get('enemy_hp', '?')}/{enc.get('enemy_max_hp', '?')}. "
                    "Present combat choices: attack, defend, flee, or use item."
                )
            narration = self._director_infer(
                f"The player travels from {result['from_name']} to {result['to_name']}. "
                f"{result['description']}{encounter_text} "
                "Narrate the journey and arrival."
            )
            self._apply_director_result(narration)
            self.socketio.emit("location_changed", result)
            # Sync location to coordinator
            try:
                from engine.mcp.state_coordinator import get_coordinator
                get_coordinator().update(
                    "realm_player", source="realm_location", scene="realm",
                    location=result["to_name"],
                )
            except Exception:
                pass
            return jsonify({**result, "narration": narration.get("narration", ""), "state": self.state.to_dict()})

        # ── Quest Routes ──

        @self.app.route("/api/quests")
        def quest_list():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            return jsonify({
                "available": self.state.get_available_quests(),
                "active": self.state.active_quests,
                "completed": self.state.completed_quests,
            })

        @self.app.route("/api/quests/accept", methods=["POST"])
        def quest_accept():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            data = request.get_json(silent=True) or {}
            quest_key = data.get("quest")
            if not quest_key:
                return jsonify({"error": "quest key required"}), 400
            result = self.state.accept_quest(quest_key)
            if "error" in result:
                return jsonify(result), 400
            quest = result["quest"]
            narration = self._director_infer(
                f"The player accepts the quest: '{quest['title']}' — {quest['description']}. "
                "Narrate the quest-giver and set the scene."
            )
            self._apply_director_result(narration)
            self.socketio.emit("quest_accepted", quest)
            return jsonify({**result, "narration": narration.get("narration", "")})

        # ── Equipment Routes ──

        @self.app.route("/api/equipment")
        def equipment_get():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            return jsonify({
                "equipment": self.state.get_equipment(),
                "total_stats": self.state.get_total_stats(),
            })

        @self.app.route("/api/equipment/equip", methods=["POST"])
        def equipment_equip():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            data = request.get_json(silent=True) or {}
            item_id = data.get("item_id")
            if not item_id:
                return jsonify({"error": "item_id required"}), 400
            result = self.state.equip_item(item_id)
            if "error" in result:
                return jsonify(result), 400
            self.socketio.emit("equipment_changed", self.state.get_equipment())
            return jsonify(result)

        @self.app.route("/api/equipment/unequip", methods=["POST"])
        def equipment_unequip():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            data = request.get_json(silent=True) or {}
            slot = data.get("slot")
            if not slot:
                return jsonify({"error": "slot required"}), 400
            result = self.state.unequip_slot(slot)
            if "error" in result:
                return jsonify(result), 400
            self.socketio.emit("equipment_changed", self.state.get_equipment())
            return jsonify(result)

        @self.app.route("/api/inventory")
        def inventory_list():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            return jsonify({"inventory": list(self.state.inventory), "gold": self.state.gold})

        # ── Shop / Economy Routes ──

        @self.app.route("/api/shop/catalog")
        def shop_catalog():
            return jsonify({"catalog": {k: {**v, "id": k} for k, v in ITEM_CATALOG.items()}})

        @self.app.route("/api/shop/buy", methods=["POST"])
        def shop_buy():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            data = request.get_json(silent=True) or {}
            item_key = data.get("item_id")
            if not item_key:
                return jsonify({"error": "item_id required"}), 400
            result = self.state.buy_item(item_key)
            if "error" in result:
                return jsonify(result), 400
            self.socketio.emit("gold_changed", {"gold": self.state.gold})
            return jsonify(result)

        @self.app.route("/api/shop/sell", methods=["POST"])
        def shop_sell():
            if not self.state:
                return jsonify({"error": "No active game"}), 400
            data = request.get_json(silent=True) or {}
            item_id = data.get("item_id")
            if not item_id:
                return jsonify({"error": "item_id required"}), 400
            result = self.state.sell_item(item_id)
            if "error" in result:
                return jsonify(result), 400
            self.socketio.emit("gold_changed", {"gold": self.state.gold})
            return jsonify(result)

        @self.app.route("/api/economy")
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
                logger.error("Economy API error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/consequences")
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
                logger.error("Consequences API error: %s", exc)
                return jsonify({"error": str(exc)}), 500

    # ── SocketIO ──

    def _setup_socketio(self):
        @self.socketio.on("connect")
        def on_connect():
            if self.state:
                self.socketio.emit("game_state", self.state.to_dict())

        @self.socketio.on("get_realm_state")
        def on_get_realm_state():
            """Emit full state: arc, player_stats, active_quest, world_events."""
            if not self.state:
                self.socketio.emit("realm_state", {"active": False})
                return
            self.socketio.emit("realm_state", {
                "active": True,
                "arc": getattr(self.state, "active_arc", None),
                "player_stats": self.state.player_stats,
                "active_quest": self.state.active_quests[0] if self.state.active_quests else None,
                "world_events": list(self.state.history[-5:]) if hasattr(self.state, "history") else [],
                "sanity": getattr(self.state, "sanity", 100),
                **self.state.to_dict(),
            })

        @self.socketio.on("get_story_arcs")
        def on_get_story_arcs():
            """Emit available dark story arcs from ContentEngine."""
            self.socketio.emit("story_arcs", {"arcs": self._get_story_arcs()})

        @self.socketio.on("start_arc")
        def on_start_arc(data: Dict):
            """Begin a dark story arc by arc_id."""
            if not self.state:
                self.socketio.emit("arc_error", {"error": "No active game."})
                return
            arc_id = (data or {}).get("arc_id", "")
            arc = self._STORY_ARCS.get(arc_id)
            if not arc:
                self.socketio.emit("arc_error", {"error": f"Unknown arc '{arc_id}'."})
                return
            self.state.active_arc = arc_id  # type: ignore[attr-defined]
            prompt = (
                f"The player starts the dark arc: '{arc['title']}'. "
                f"Arc description: {arc['description']}. "
                "Open this arc dramatically in 2-3 paragraphs. Dark tone, high stakes."
            )
            result = self._director_infer(prompt)
            self._apply_director_result(result)
            self._sync_to_mcp()
            self.socketio.emit("arc_started", {
                "arc": arc,
                "narration": result.get("narration", ""),
                "choices": result.get("choices", []),
                "state": self.state.to_dict(),
            })

        @self.socketio.on("player_choice")
        def on_player_choice(data: Dict):
            """Narrative branching point via Socket.IO."""
            if not self.state or self.state.ended:
                self.socketio.emit("choice_error", {"error": "No active game."})
                return
            choice_id = (data or {}).get("choice_id", "")
            self.state.decay_patience()
            choice_match = next(
                (c for c in self.state.current_choices if c.get("id") == choice_id), None
            )
            action_text = (
                f"The player chose: {choice_match['text']}" if choice_match
                else f"Player chose option {choice_id}"
            )
            result = self._director_infer(action_text)
            self._apply_director_result(result)
            self._sync_to_mcp()
            self.socketio.emit("choice_result", {
                "narration": result.get("narration", ""),
                "choices": result.get("choices", []),
                "state": self.state.to_dict(),
            })

        @self.socketio.on("cast_spell")
        def on_cast_spell(data: Dict):
            """Magic system — costs MP, narrated by Director."""
            if not self.state or self.state.ended:
                self.socketio.emit("spell_error", {"error": "No active game."})
                return
            spell = (data or {}).get("spell", "").strip()
            if not spell:
                self.socketio.emit("spell_error", {"error": "No spell specified."})
                return
            mp_cost = max(5, len(spell) // 3)
            current_mp = self.state.player_stats.get("mp", 0)
            if current_mp < mp_cost:
                self.socketio.emit("spell_error", {
                    "error": f"Not enough MP. Need {mp_cost}, have {current_mp}.",
                })
                return
            self.state.adjust_stat("mp", -mp_cost)
            forbidden_keywords = {"void", "soul", "death", "blood", "forbidden", "ancient", "eldritch"}
            if any(kw in spell.lower() for kw in forbidden_keywords):
                sanity = getattr(self.state, "sanity", 100)
                self.state.sanity = max(0, sanity - 10)  # type: ignore[attr-defined]
            result = self._director_infer(
                f"The player casts the spell: '{spell}' (cost {mp_cost} MP). "
                "Describe the dramatic magical effect with dark fantasy flair."
            )
            self._apply_director_result(result)
            self._sync_to_mcp()
            self.socketio.emit("spell_cast", {
                "spell": spell,
                "mp_cost": mp_cost,
                "mp_remaining": self.state.player_stats.get("mp", 0),
                "sanity": getattr(self.state, "sanity", 100),
                "narration": result.get("narration", ""),
                "choices": result.get("choices", []),
                "state": self.state.to_dict(),
            })

        @self.socketio.on("inventory_action")
        def on_inventory_action(data: Dict):
            """Inventory management via Socket.IO."""
            if not self.state:
                self.socketio.emit("inventory_error", {"error": "No active game."})
                return
            action = (data or {}).get("action", "")
            item_id = (data or {}).get("item_id", "")
            if action == "use":
                result = self.state.combat_use_item(item_id) if self.state.combat else {"error": "Not in combat"}
                self.socketio.emit("inventory_result", {"action": "use", "result": result})
            elif action == "drop":
                removed = self.state.remove_item(item_id)
                self.socketio.emit("inventory_result", {
                    "action": "drop",
                    "item": removed,
                    "inventory": list(self.state.inventory),
                })
            elif action == "inspect":
                item = next((i for i in self.state.inventory if i.get("id") == item_id), None)
                self.socketio.emit("inventory_result", {"action": "inspect", "item": item})
            else:
                self.socketio.emit("inventory_error", {
                    "error": f"Unknown action '{action}'. Valid: use, drop, inspect.",
                })

    # ── Dark Story Arcs ──────────────────────────────────────────

    _STORY_ARCS = {
        "corruption": {
            "id": "corruption",
            "title": "The Corruptor's Bargain",
            "icon": "☠️",
            "description": "A dark entity offers you impossible power — at the cost of your soul.",
            "intensity": 2,
            "tags": ["dark", "moral_choice", "power"],
        },
        "forbidden_magic": {
            "id": "forbidden_magic",
            "title": "Forbidden Tome",
            "icon": "📖",
            "description": "A cursed grimoire promises omniscience. Every spell costs sanity.",
            "intensity": 2,
            "tags": ["magic", "sanity", "horror"],
        },
        "betrayal": {
            "id": "betrayal",
            "title": "The Knife in the Dark",
            "icon": "🗡️",
            "description": "Your closest ally is the realm's most dangerous traitor.",
            "intensity": 2,
            "tags": ["political", "trust", "revenge"],
        },
        "lovecraftian": {
            "id": "lovecraftian",
            "title": "What Stirs Beneath",
            "icon": "🦑",
            "description": "Something ancient and unspeakable stirs beneath the shattered throne.",
            "intensity": 3,
            "tags": ["cosmic_horror", "sanity", "eldritch"],
        },
        "political_intrigue": {
            "id": "political_intrigue",
            "title": "Game of Shards",
            "icon": "👑",
            "description": "Four factions war for the throne's fragments. Every alliance is a lie.",
            "intensity": 1,
            "tags": ["political", "strategy", "intrigue"],
        },
    }

    def _get_story_arcs(self) -> List[Dict[str, Any]]:
        """Return dark story arcs, enriched from ContentEngine if available."""
        arcs = list(self._STORY_ARCS.values())
        try:
            from engine.content.content_engine import get_content_engine
            engine = get_content_engine()
            ce_arcs = engine.get_content("realm", "arc", count=5, intensity_max=3)
            for arc in ce_arcs:
                if arc.id not in self._STORY_ARCS:
                    arcs.append({
                        "id": arc.id,
                        "title": arc.title,
                        "icon": "🌑",
                        "description": arc.content[:120],
                        "intensity": arc.intensity,
                        "tags": arc.tags,
                    })
        except Exception:
            pass
        return arcs

    # ── SocketIO ──

    # v1.51.0 [2026-03-22] — start/stop delegated to FlaskScene

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name": "THE SHATTERED THRONE",
            "scene_id": SCENE_ID,
            "description": "Dark Renaissance RPG — dark story arcs, magic system, sanity mechanics, dual-agent pipeline.",
            "version": "0.68",
            "port": self.port,
            "author": "CosySim",
            "accent_color": "#059669",
            "tags": [
                "dark_fantasy", "litrpg", "visual_novel", "dual_agent",
                "combat", "quests", "murder_mystery", "magic", "sanity",
            ],
            "skill_packs": ["realm", "memory", "narrative", "character"],
            "story_arcs": list(self._STORY_ARCS.keys()),
            "routes": [
                {"path": "/api/game/new",        "methods": ["POST"], "description": "Start new game"},
                {"path": "/api/game/choice",      "methods": ["POST"], "description": "Make player choice"},
                {"path": "/api/game/state",       "methods": ["GET"],  "description": "Get game state"},
                {"path": "/api/combat/start",     "methods": ["POST"], "description": "Start combat encounter"},
                {"path": "/api/combat/attack",    "methods": ["POST"], "description": "Attack in combat"},
                {"path": "/api/combat/defend",    "methods": ["POST"], "description": "Defend in combat"},
                {"path": "/api/combat/flee",      "methods": ["POST"], "description": "Flee from combat"},
                {"path": "/api/combat/use_item",  "methods": ["POST"], "description": "Use item in combat"},
                {"path": "/api/location/current", "methods": ["GET"],  "description": "Get current location"},
                {"path": "/api/location/move",    "methods": ["POST"], "description": "Move to connected location"},
                {"path": "/api/quests",           "methods": ["GET"],  "description": "List quests"},
                {"path": "/api/quests/accept",    "methods": ["POST"], "description": "Accept a quest"},
                {"path": "/api/murder/start",     "methods": ["POST"], "description": "Start murder mystery"},
                {"path": "/api/murder/accuse",    "methods": ["POST"], "description": "Accuse in murder mystery"},
                {"path": "/api/equipment",        "methods": ["GET"],  "description": "Get equipment"},
                {"path": "/api/equipment/equip",  "methods": ["POST"], "description": "Equip an item"},
                {"path": "/api/equipment/unequip","methods": ["POST"], "description": "Unequip a slot"},
                {"path": "/api/inventory",        "methods": ["GET"],  "description": "Get inventory"},
                {"path": "/api/shop/catalog",     "methods": ["GET"],  "description": "Shop catalog"},
                {"path": "/api/shop/buy",         "methods": ["POST"], "description": "Buy item"},
                {"path": "/api/shop/sell",        "methods": ["POST"], "description": "Sell item"},
            ],
        }
