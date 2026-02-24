"""
The Midnight Casino — Scene
=============================
A noir-themed underground poker den showcasing the full MCP framework.

Port: 5559

This scene demonstrates every major framework feature:
  • MCPSceneMixin + MCPSceneNode for scene registration
  • MCPFramework event bus (emit_event / on) for decoupled communication
  • MCPFramework lifecycle hooks (framework_ready, scene_tick)
  • Agent profiles (game_master for dealer, small for narrator)
  • MCPGameSession for tracked poker hands with turn history
  • Consequence chains for delayed effects (drunk penalties, luck streaks)
  • MCPTimer for round clock and drink effects
  • SceneStateManager for character stats (chips, confidence, focus, luck)
  • GameState key-value store for poker game tracking
  • DialogSystem ResponseDirective for bluff/tell narration
  • Skill system: new social skills (mood_contagion, relationship_adjust)
  • Cross-scene bridge: can receive phone messages mid-game
  • Random atmospheric events via random_pick
  • State persistence: save_state/load_state across restarts

Characters
----------
• Dealer Jack — the house dealer.  Calm, precise, slightly ominous.
• Hustler Mira — a fellow player.  Charming, unpredictable, reads people.
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

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS

import sys
from engine.paths import ROOT as _root
sys.path.insert(0, str(_root))

from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin, get_framework
from content.scenes.casino.casino_mcp import (
    register_casino_rules,
    SCENE_ID, DEALER_ID, HUSTLER_ID,
    CASINO_DRINKS, RANDOM_EVENTS, TELL_DESCRIPTIONS,
    deal_hand, evaluate_hand_simple, pick_random_event,
)
from content.shared import register_shared_assets
from engine.mcp.scene_state import get_scene_state_manager
from engine.mcp.tag_registry import TagRegistry

logger = logging.getLogger(__name__)

CASINO_PORT = 5559


# ══════════════════════════════════════════════════════════════════════
#  CASINO SCENE
# ══════════════════════════════════════════════════════════════════════

class CasinoScene(BaseScene, MCPSceneMixin, mcp_scene_id=SCENE_ID):
    """
    The Midnight Casino — MCP framework showcase.

    Poker game engine with AI opponents, chip economy, bluffing system,
    and full MCP governance.  Demonstrates all new framework features.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = CASINO_PORT) -> None:
        super().__init__(scene_name=SCENE_ID, host=host, port=port)

        # ── Flask app ────────────────────────────────────────────────
        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"),
        )
        register_shared_assets(self.app)
        self.app.config["SECRET_KEY"] = "midnight_casino_noir_2026"
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", manage_session=False)

        # Mount control overlay
        from engine.overlay import mount_overlay
        mount_overlay(self.app, self.socketio)

        # ── Game state ───────────────────────────────────────────────
        self.player_chips:     int              = 500
        self.player_hand:      List[str]        = []
        self.community_cards:  List[str]        = []
        self.pot:              int              = 0
        self.round_number:     int              = 0
        self.game_active:      bool             = False
        self.current_phase:    str              = "lobby"   # lobby | deal | bet | showdown | result
        self.player_stats:     Dict[str, float] = {
            "confidence": 50.0, "focus": 50.0, "luck": 50.0,
            "charm": 50.0, "recklessness": 20.0,
        }
        self.dealer_hand:      List[str]        = []
        self.mira_hand:        List[str]        = []
        self.mira_chips:       int              = 500
        self.dealer_comment:   str              = ""
        self.mira_comment:     str              = ""
        self.current_tell:     str              = ""
        self.events_log:       List[Dict]       = []
        self.hand_history:     List[Dict]       = []
        self._turn_lock        = threading.Lock()

        # ── Agents (lazy) ────────────────────────────────────────────
        self._dealer_agent = None
        self._mira_agent   = None

        # ── Setup ────────────────────────────────────────────────────
        self._setup_routes()
        self._setup_socketio()
        self._mcp_init()
        register_casino_rules()
        self._seed_casino_registry()
        self._wire_event_bus()

        # Framework integration
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()

    # ══════════════════════════════════════════════════════════════════
    #  FRAMEWORK INTEGRATION
    # ══════════════════════════════════════════════════════════════════

    @property
    def _fw(self):
        return get_framework()

    @property
    def _ssm(self):
        from engine.mcp.scene_state import get_scene_state_manager
        return get_scene_state_manager()

    def _wire_event_bus(self) -> None:
        """Subscribe to framework events."""
        fw = self._fw
        fw.on("scene_tick", self._on_tick)
        fw.on("mood_contagion", self._on_mood_event)
        fw.on("environment_change", self._on_env_change)
        fw.on("story_beat", self._on_story_beat)
        fw.add_lifecycle_hook("state_saved", lambda p: logger.debug("Casino: state saved to %s", p))

    def _on_tick(self, evt) -> None:
        if evt.payload.get("scene_id") == SCENE_ID:
            self._check_timers()

    def _on_mood_event(self, evt) -> None:
        try:
            self.socketio.emit("mood_update", evt.payload)
        except Exception:
            pass

    def _on_env_change(self, evt) -> None:
        if evt.payload.get("scene_id") == SCENE_ID:
            try:
                self.socketio.emit("environment_update", evt.payload)
            except Exception:
                pass

    def _on_story_beat(self, evt) -> None:
        if evt.payload.get("scene_id") == SCENE_ID:
            self.events_log.append({"type": "story_beat", "data": evt.payload})
            try:
                self.socketio.emit("story_beat", evt.payload)
            except Exception:
                pass

    def _check_timers(self) -> None:
        """Check if any casino timers have completed."""
        timer = self._fw.check_timer("casino_round")
        if timer and timer.completed:
            self._fw.cancel_timer("casino_round")
            self._fw.emit_event("casino_round_timeout", {"round": self.round_number}, source=SCENE_ID)

    # ══════════════════════════════════════════════════════════════════
    #  REGISTRY SEEDING
    # ══════════════════════════════════════════════════════════════════

    def _seed_casino_registry(self) -> None:
        """Register Dealer Jack and Hustler Mira in the CharacterRegistry."""
        try:
            from engine.mcp.character_registry import get_character_registry, apply_default_skills
            reg = get_character_registry()

            # Dealer Jack
            reg.register(
                DEALER_ID,
                name="Dealer Jack",
                age=45,
                appearance={
                    "hair": "slicked back, silver-streaked",
                    "eyes": "dark, unreadable",
                    "height": "6'0",
                    "style": "black suit, red pocket square, gold cufflinks",
                },
                personality={
                    "warmth": 0.3, "assertiveness": 0.7, "wit": 0.6,
                    "vulnerability": 0.1, "openness": 0.2, "dominance": 0.8,
                },
                backstory=(
                    "Dealer Jack has been running tables for twenty years. He's seen "
                    "every bluff, every tell, every desperate last-hand bet. He doesn't "
                    "judge. He doesn't comfort. He deals."
                ),
                voice_style="deep, measured, clipped sentences. Slight rasp. Never raises his voice.",
                scene_roles=[SCENE_ID],
            )
            reg.set_state(DEALER_ID, mood="neutral", mood_intensity=0.2, energy=90.0)
            apply_default_skills(DEALER_ID)

            # Hustler Mira
            reg.register(
                HUSTLER_ID,
                name="Mira Chen",
                age=31,
                appearance={
                    "hair": "straight black, cut sharp at the jaw",
                    "eyes": "dark brown, always watching",
                    "height": "5'7",
                    "style": "tailored charcoal blazer, no jewelry, red lipstick",
                },
                personality={
                    "warmth": 0.6, "assertiveness": 0.7, "wit": 0.9,
                    "vulnerability": 0.3, "openness": 0.5, "playfulness": 0.7,
                    "sensuality": 0.5, "empathy": 0.6,
                },
                backstory=(
                    "Mira Chen grew up counting cards in Macau before anyone noticed. "
                    "She plays poker the way she does everything — with calculated charm "
                    "and just enough chaos to keep you guessing."
                ),
                voice_style="quick, playful, slightly mocking. Drops to a conspiratorial whisper for secrets.",
                scene_roles=[SCENE_ID],
            )
            reg.set_state(HUSTLER_ID, mood="amused", mood_intensity=0.6, energy=80.0)
            apply_default_skills(HUSTLER_ID)

            # Enter scene
            for cid in [DEALER_ID, HUSTLER_ID]:
                self._fw.get_character(cid).enter_scene(SCENE_ID)

            logger.info("Casino registry seeded: Dealer Jack + Hustler Mira")
        except Exception as exc:
            logger.warning("_seed_casino_registry failed: %s", exc)

    # ══════════════════════════════════════════════════════════════════
    #  AGENT HELPERS
    # ══════════════════════════════════════════════════════════════════

    def _get_agent_reply(self, character_id: str, prompt: str, role: str = "game_master") -> Dict[str, Any]:
        """Get an LLM reply with rich metadata via infer_processed().

        Returns dict with: text, mood, image_requests, action_tags.
        """
        result = {"text": "", "mood": None, "image_requests": [], "action_tags": []}
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest
            from engine.mcp.framework import get_framework

            profile = get_framework().get_agent_profile(role)
            mgr = get_virtual_agent_manager()

            # Build character-specific system prompt
            try:
                from engine.mcp.character_registry import get_character_registry
                rec = get_character_registry().get_record(character_id)
                if rec:
                    name = rec.profile.name
                    backstory = rec.profile.backstory or ""
                    voice = rec.profile.voice_style or ""
                    system = (
                        f"You are {name}. {backstory}\n"
                        f"Voice style: {voice}\n"
                        f"Stay in character. Keep responses under 3 sentences. "
                        f"You are at a poker table in an underground casino.\n"
                        f"Express mood with [MOOD:emotion]. Use [ACTION:desc] for actions."
                    )
                else:
                    system = "You are a casino character. Keep responses short. Use [MOOD:emotion] tags."
            except Exception:
                system = "You are a casino character. Keep responses short. Use [MOOD:emotion] tags."

            request = InferenceRequest(
                agent_id=character_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=profile.temperature,
                max_output_tokens=profile.max_tokens,
                conversation_id=f"casino_{character_id}",
                store=False,
                metadata={"scene": "casino", "role": role},
            )
            proc = mgr.infer_processed(request)
            result["text"] = (proc.clean_text or "").strip()
            result["mood"] = proc.mood_tags[0] if proc.mood_tags else None
            result["image_requests"] = list(proc.image_requests)
            result["action_tags"] = list(proc.action_tags)

            # Sync mood to framework
            if result["mood"]:
                try:
                    char_node = get_framework().get_character(character_id)
                    if char_node:
                        char_node.update_state({"mood": result["mood"]})
                except Exception:
                    pass

            return result
        except Exception as exc:
            logger.debug("Casino agent reply failed: %s", exc)
            return result

    # ══════════════════════════════════════════════════════════════════
    #  GAME ENGINE
    # ══════════════════════════════════════════════════════════════════

    def _agent_text(self, character_id: str, prompt: str, role: str = "game_master") -> str:
        """Convenience wrapper — returns just the text from _get_agent_reply()."""
        return self._get_agent_reply(character_id, prompt, role).get("text", "")

    def _start_new_hand(self) -> Dict:
        """Deal a new poker hand."""
        self.round_number += 1
        self.game_active = True
        self.current_phase = "deal"
        self.pot = 0

        # Deal hands
        self.player_hand = deal_hand(2)
        self.dealer_hand = deal_hand(2)
        self.mira_hand = deal_hand(2)
        self.community_cards = deal_hand(3)  # flop

        # Ante
        ante = 10
        self.player_chips -= ante
        self.mira_chips -= ante
        self.pot = ante * 2

        # Random tell
        self.current_tell = random.choice(TELL_DESCRIPTIONS)

        # Framework integration
        self._fw.start_timer("casino_round", duration_secs=120, on_complete_note="Round time expired")
        self._fw.emit_event("poker_hand_dealt", {
            "round": self.round_number,
            "pot": self.pot,
            "player_cards": self.player_hand,
        }, source=SCENE_ID)

        # Add narrative
        self._ssm.add_narrative(
            SCENE_ID,
            f"Round {self.round_number} begins. Cards are dealt. The pot is {self.pot} chips.",
            entry_type="game", character_id=DEALER_ID,
        )

        # Get character comments
        self.dealer_comment = self._agent_text(
            DEALER_ID,
            f"You're dealing round {self.round_number}. The pot is {self.pot} chips. "
            f"Announce the deal briefly.",
            role="game_master",
        ) or f"Round {self.round_number}. Cards are out. Ante is {ante}."

        self.mira_comment = self._agent_text(
            HUSTLER_ID,
            f"You've been dealt your cards in round {self.round_number}. "
            f"You have {self.mira_chips} chips. React briefly.",
            role="small",
        ) or "Let's see what we're working with..."

        self.current_phase = "bet"
        return self._get_game_state()

    def _place_bet(self, amount: int) -> Dict:
        """Player places a bet."""
        amount = min(amount, self.player_chips)
        if amount <= 0:
            return {"error": "Invalid bet amount"}

        self.player_chips -= amount
        self.pot += amount

        # Mira's response — based on stats
        mira_action = "call"
        if self.player_stats["recklessness"] > 60:
            mira_action = random.choice(["call", "raise", "fold"])
        elif amount > self.mira_chips // 2:
            mira_action = random.choice(["call", "fold"])

        mira_bet = 0
        if mira_action == "call":
            mira_bet = min(amount, self.mira_chips)
            self.mira_chips -= mira_bet
            self.pot += mira_bet
        elif mira_action == "raise":
            mira_bet = min(amount * 2, self.mira_chips)
            self.mira_chips -= mira_bet
            self.pot += mira_bet

        # Stat adjustments
        self.player_stats["recklessness"] = min(100, self.player_stats["recklessness"] + amount / 50)

        # Consequence chain for large bets
        if amount >= 50:
            self._fw.schedule_consequence(
                scene_id=SCENE_ID,
                character_id=HUSTLER_ID,
                consequence_type="stat_adjust",
                params={"stat": "focus", "delta": -5},
                trigger_after_turns=1,
                description="The weight of the big bet sinks in.",
            )

        self._fw.emit_event("poker_bet_placed", {
            "amount": amount, "pot": self.pot,
            "mira_action": mira_action, "mira_bet": mira_bet,
        }, source=SCENE_ID)

        # Comments
        self.dealer_comment = self._agent_text(
            DEALER_ID,
            f"The player bet {amount} chips. Mira {mira_action}s"
            + (f" with {mira_bet}" if mira_bet else "") + f". Pot is now {self.pot}. Comment briefly.",
            role="small",
        ) or f"Bet noted. Pot stands at {self.pot}."

        if mira_action == "fold":
            self.mira_comment = "I know when to walk away... this time."
        else:
            self.mira_comment = self._agent_text(
                HUSTLER_ID,
                f"You {mira_action} the player's bet of {amount}. "
                f"You have {self.mira_chips} chips left. React.",
                role="small",
            ) or f"I'll {mira_action}."

        self.current_phase = "showdown"
        return self._get_game_state()

    def _bluff(self) -> Dict:
        """Player attempts a bluff."""
        # Bluff success based on stats
        bluff_power = (
            self.player_stats["charm"] * 0.3
            + self.player_stats["confidence"] * 0.3
            + self.player_stats["focus"] * 0.2
            - self.player_stats["recklessness"] * 0.2
        )
        roll = self._fw.random_pick(100)
        success = roll["roll"] < bluff_power

        self.player_stats["confidence"] += 10 if success else -10
        self.player_stats["confidence"] = max(0, min(100, self.player_stats["confidence"]))

        self._fw.emit_event("poker_bluff", {
            "success": success, "bluff_power": bluff_power,
            "roll": roll["roll"],
        }, source=SCENE_ID)

        if success:
            # Mira folds
            self.player_chips += self.pot
            self.pot = 0
            self.current_phase = "result"
            narrative = "Your bluff lands perfectly. Mira folds with a rueful smile."
        else:
            # Mira calls
            narrative = "Mira sees right through you. She calls without hesitation."

        self._ssm.add_narrative(SCENE_ID, narrative, entry_type="game")

        self.mira_comment = self._agent_text(
            HUSTLER_ID,
            f"The player tried to bluff. {'You fell for it and folded.' if success else 'You saw through it and called.'} React.",
            role="small",
        ) or ("Well played..." if success else "Nice try.")

        return self._get_game_state()

    def _showdown(self) -> Dict:
        """Reveal cards and determine winner."""
        self.current_phase = "result"

        # Evaluate hands (player gets community cards)
        player_eval = evaluate_hand_simple(self.player_hand + self.community_cards)
        mira_eval = evaluate_hand_simple(self.mira_hand + self.community_cards)

        # Luck modifier
        luck_bonus = int((self.player_stats["luck"] - 50) / 25)
        player_eval["score"] += luck_bonus

        if player_eval["score"] >= mira_eval["score"]:
            winner = "player"
            self.player_chips += self.pot
            self.player_stats["confidence"] = min(100, self.player_stats["confidence"] + 15)
        else:
            winner = "mira"
            self.mira_chips += self.pot
            self.player_stats["confidence"] = max(0, self.player_stats["confidence"] - 10)

        self.pot = 0

        # Record hand
        hand_record = {
            "round": self.round_number, "winner": winner,
            "player_hand": self.player_hand, "player_eval": player_eval["rank"],
            "mira_hand": self.mira_hand, "mira_eval": mira_eval["rank"],
            "community": self.community_cards,
        }
        self.hand_history.append(hand_record)

        # Framework events
        self._fw.emit_event("poker_showdown", {
            "winner": winner, "player_eval": player_eval, "mira_eval": mira_eval,
            "player_chips": self.player_chips, "mira_chips": self.mira_chips,
        }, source=SCENE_ID)

        # Mood contagion on big wins
        if winner == "player" and player_eval["score"] >= 3:
            try:
                from engine.skills.builtin.social_skills import mood_contagion
                mood_contagion(HUSTLER_ID, "frustration", intensity=0.3, scene_id=SCENE_ID)
            except Exception:
                pass

        # Agent comments
        self.dealer_comment = self._agent_text(
            DEALER_ID,
            f"Showdown: Player has {player_eval['rank']}, Mira has {mira_eval['rank']}. "
            f"{'Player' if winner == 'player' else 'Mira'} wins the pot. Announce the result.",
            role="game_master",
        ) or f"{'Player' if winner == 'player' else 'Mira'} takes the pot."

        self.mira_comment = self._agent_text(
            HUSTLER_ID,
            f"Showdown result: you {'lost' if winner == 'player' else 'won'}. "
            f"Your hand: {mira_eval['rank']}. You have {self.mira_chips} chips. React.",
            role="small",
        ) or ("Next time..." if winner == "player" else "I knew it.")

        # Narrative
        self._ssm.add_narrative(
            SCENE_ID,
            f"Round {self.round_number}: {'Player' if winner == 'player' else 'Mira'} wins with {player_eval['rank'] if winner == 'player' else mira_eval['rank']}.",
            entry_type="game",
        )

        return self._get_game_state()

    def _order_drink(self, drink_id: str) -> Dict:
        """Order a drink from the casino bar."""
        drink = CASINO_DRINKS.get(drink_id)
        if not drink:
            return {"error": "Unknown drink"}

        if self.player_chips < drink["cost"]:
            return {"error": "Not enough chips"}

        self.player_chips -= drink["cost"]
        for stat, delta in drink["stat_effects"].items():
            if stat in self.player_stats:
                self.player_stats[stat] = max(0, min(100, self.player_stats[stat] + delta))

        # Schedule hangover consequence
        if drink["cost"] >= 10:
            self._fw.schedule_consequence(
                scene_id=SCENE_ID,
                character_id="player",
                consequence_type="stat_adjust",
                params={"stat": "focus", "delta": -drink["cost"] // 5},
                trigger_after_turns=3,
                description=f"The {drink['name']} starts to hit...",
            )

        self._fw.emit_event("drink_ordered", {
            "drink": drink["name"], "cost": drink["cost"],
            "effects": drink["stat_effects"],
        }, source=SCENE_ID)

        return {"drink": drink, "player_chips": self.player_chips, "stats": self.player_stats}

    def _trigger_random_event(self) -> Dict:
        """Trigger a random atmospheric event."""
        event = pick_random_event()
        for stat, delta in event.get("stat_effect", {}).items():
            if stat in self.player_stats:
                self.player_stats[stat] = max(0, min(100, self.player_stats[stat] + delta))

        self._fw.emit_event("casino_random_event", event, source=SCENE_ID)
        self._ssm.add_narrative(SCENE_ID, event["text"], entry_type="atmosphere")
        self.events_log.append(event)
        return event

    def _get_game_state(self) -> Dict:
        """Return the full game state for the frontend."""
        return {
            "round": self.round_number,
            "phase": self.current_phase,
            "game_active": self.game_active,
            "player_hand": self.player_hand if self.current_phase != "lobby" else [],
            "community_cards": self.community_cards if self.current_phase not in ("lobby", "deal") else [],
            "mira_hand": self.mira_hand if self.current_phase == "result" else ["🂠", "🂠"],
            "pot": self.pot,
            "player_chips": self.player_chips,
            "mira_chips": self.mira_chips,
            "player_stats": self.player_stats,
            "dealer_comment": self.dealer_comment,
            "mira_comment": self.mira_comment,
            "current_tell": self.current_tell if self.current_phase in ("bet", "showdown") else "",
            "drinks": CASINO_DRINKS,
            "hand_history": self.hand_history[-5:],
            "events": self.events_log[-5:],
        }

    # ══════════════════════════════════════════════════════════════════
    #  FLASK ROUTES
    # ══════════════════════════════════════════════════════════════════

    def _setup_routes(self) -> None:
        app = self.app

        @app.route("/")
        def index():
            return render_template("casino.html")

        @app.route("/api/health")
        def health():
            return jsonify({"status": "ok", "scene": SCENE_ID, "port": self.port})

        @app.route("/api/state")
        def state():
            return jsonify(self._get_game_state())

        @app.route("/api/new-hand", methods=["POST"])
        def new_hand():
            result = self._start_new_hand()
            self.socketio.emit("game_update", result)
            return jsonify(result)

        @app.route("/api/bet", methods=["POST"])
        def bet():
            data = request.get_json(force=True, silent=True) or {}
            amount = int(data.get("amount", 10))
            result = self._place_bet(amount)
            self.socketio.emit("game_update", result)
            return jsonify(result)

        @app.route("/api/bluff", methods=["POST"])
        def bluff():
            result = self._bluff()
            self.socketio.emit("game_update", result)
            return jsonify(result)

        @app.route("/api/showdown", methods=["POST"])
        def showdown():
            result = self._showdown()
            self.socketio.emit("game_update", result)
            return jsonify(result)

        @app.route("/api/fold", methods=["POST"])
        def fold():
            self.mira_chips += self.pot
            self.pot = 0
            self.current_phase = "result"
            self.player_stats["confidence"] = max(0, self.player_stats["confidence"] - 5)
            self.dealer_comment = "Folded. Smart or scared?"
            self.mira_comment = "I'll take those, thanks."
            result = self._get_game_state()
            self.socketio.emit("game_update", result)
            return jsonify(result)

        @app.route("/api/drink", methods=["POST"])
        def drink():
            data = request.get_json(force=True, silent=True) or {}
            result = self._order_drink(data.get("drink_id", ""))
            if "error" not in result:
                self.socketio.emit("game_update", self._get_game_state())
            return jsonify(result)

        @app.route("/api/random-event", methods=["POST"])
        def random_event():
            event = self._trigger_random_event()
            self.socketio.emit("casino_event", event)
            return jsonify(event)

        @app.route("/api/framework-status")
        def framework_status():
            """Expose full framework status — demonstrates framework introspection."""
            fw = self._fw
            return jsonify({
                "framework": fw.get_status(),
                "event_log": fw.get_event_log(limit=20),
                "agent_profiles": fw.list_agent_profiles(),
                "timers": fw.list_timers(),
                "consequences": fw.get_pending_consequences(scene_id=SCENE_ID),
            })

    # ══════════════════════════════════════════════════════════════════
    #  SOCKETIO
    # ══════════════════════════════════════════════════════════════════

    def _setup_socketio(self) -> None:
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            emit("game_update", self._get_game_state())

        @sio.on("chat_message")
        def on_chat(data):
            """Handle a player chat message — routed through MCP governor."""
            msg = data.get("message", "").strip()
            if not msg:
                return
            target = data.get("target", DEALER_ID)
            reply_data = self._get_agent_reply(target, msg, role="game_master")
            emit("chat_reply", {
                "character": target,
                "message": reply_data.get("text") or "...",
                "mood": reply_data.get("mood"),
            })

    # ══════════════════════════════════════════════════════════════════
    #  BASESCENE INTERFACE
    # ══════════════════════════════════════════════════════════════════

    def get_plugin_info(self) -> Dict:
        return {
            "name":        "The Midnight Casino",
            "description": "Noir poker den — Dealer Jack & Hustler Mira. Full MCP showcase.",
            "version":     "1.0.0",
            "port":        CASINO_PORT,
            "tags":        ["casino", "poker", "mcp", "multi-agent", "game"],
            "skill_packs": ["social", "environment", "narrative", "memory", "character"],
        }

    def start(self) -> None:
        logger.info("The Midnight Casino opening on port %d", self.port)
        self._fw.emit_event("scene_started", {"scene_id": SCENE_ID, "port": CASINO_PORT}, source=SCENE_ID)
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False)

    def stop(self) -> None:
        logger.info("The Midnight Casino closing")
        try:
            self._fw.save_state()
        except Exception:
            pass


# ── Standalone entry point ────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scene = CasinoScene()
    scene.start()
