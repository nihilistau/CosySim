"""
CLUB NOIR — Casino Scene
=========================

A high-stakes underground casino revamped from The Midnight Casino.
Accent: neon orange #f97316.  Port: 5559.

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

Version: v1.52.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.52.0 [2026-03-25] — Added structured module header
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

from flask import render_template, jsonify, request
from flask_socketio import emit

import sys
from engine.paths import ROOT as _root
sys.path.insert(0, str(_root))

from engine.scenes.flask_scene import FlaskScene
from engine.mcp.framework import get_framework
from content.scenes.casino.casino_mcp import (
    register_casino_rules,
    SCENE_ID, DEALER_ID, HUSTLER_ID,
    CASINO_DRINKS, RANDOM_EVENTS, TELL_DESCRIPTIONS,
    deal_hand, evaluate_hand_simple, pick_random_event,
)
from content.shared import register_shared_assets
from engine.mcp.scene_state import get_scene_state_manager
from engine.mcp.tag_registry import TagRegistry

try:
    from engine.world.world_state import get_world_state
    from engine.events.event_bus import get_event_bus, EventBus
    _WORLD_AVAILABLE = True
except ImportError:
    _WORLD_AVAILABLE = False

logger = logging.getLogger(__name__)

# v1.49.3 [2026-03-22] — Structured logging context (SCENE_ID prefix + operation tags)

CASINO_PORT = 5559


# ══════════════════════════════════════════════════════════════════════
#  CASINO SCENE
# ══════════════════════════════════════════════════════════════════════

# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class CasinoScene(FlaskScene):
    """
    The Midnight Casino — MCP framework showcase.

    Poker game engine with AI opponents, chip economy, bluffing system,
    and full MCP governance.  Demonstrates all new framework features.
    """

    SCENE_METADATA = {
        "name": "casino",
        "display_name": "CLUB NOIR",
        "port": 5559,
        "type": "gambling",
        "accent_color": "#f97316",
        "accent_rgb": "249 115 22",
        "description": "Everyone owes someone. The cards don't lie. The dealers do.",
    }

    # v1.51.0 [2026-03-22] — Migrated to FlaskScene
    def __init__(self, host: str = "0.0.0.0", port: int = CASINO_PORT) -> None:
        super().__init__(host=host, port=port)

        self.app.config["SECRET_KEY"] = "midnight_casino_noir_2026"

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

        # ── Blackjack state ──────────────────────────────────────────
        self._bj_state: Dict[str, Any] = {
            "active": False,
            "game": "blackjack",
            "buy_in": 0,
            "bet": 0,
            "target": "player_win",
            "player_hand": [],
            "dealer_hand": [],
            "phase": "idle",   # idle | betting | playing | result
            "result": None,
            "winnings": 0,
        }
        self._transactions: List[Dict] = []

        # ── Agents (lazy) ────────────────────────────────────────────
        self._dealer_agent = None
        self._mira_agent   = None

        # ── Setup ────────────────────────────────────────────────────
        self._setup_routes()
        self._setup_socketio()
        register_casino_rules()
        self._seed_casino_registry()
        self._wire_event_bus()

        # Framework integration
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()

        # ── New engine integrations ───────────────────────────────────
        self._economy       = None
        self._reputation    = None
        self._consequence   = None
        self._event_bus_new = None
        self._wire_economy()
        self._wire_reputation()
        self._wire_consequence_store()
        self._wire_new_event_bus()
        # ── World State ──────────────────────────────────────────────
        self._world_state = None
        if _WORLD_AVAILABLE:
            self._world_state = get_world_state()
            self._event_bus = get_event_bus()
            self._event_bus.subscribe("world.tick", self._on_world_tick)
            self._event_bus.subscribe("world.time_change", self._on_time_change)
        # v1.51.0 — FlaskScene registers health, hud, announcer, inventory, tts
        self.register_bench_route(self.app, self.socketio)

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
        except Exception as e:
            logger.debug("[%s] Mood update emit failed (operation=on_mood_event): %s", SCENE_ID, e)

    def _on_env_change(self, evt) -> None:
        if evt.payload.get("scene_id") == SCENE_ID:
            try:
                self.socketio.emit("environment_update", evt.payload)
            except Exception as e:
                logger.debug("[%s] Environment update emit failed (operation=on_env_change): %s", SCENE_ID, e)

    def _on_story_beat(self, evt) -> None:
        if evt.payload.get("scene_id") == SCENE_ID:
            self.events_log.append({"type": "story_beat", "data": evt.payload})
            try:
                self.socketio.emit("story_beat", evt.payload)
            except Exception as e:
                logger.debug("[%s] Story beat emit failed (operation=on_story_beat): %s", SCENE_ID, e)

    def _check_timers(self) -> None:
        """Check if any casino timers have completed."""
        timer = self._fw.check_timer("casino_round")
        if timer and timer.completed:
            self._fw.cancel_timer("casino_round")
            self._fw.emit_event("casino_round_timeout", {"round": self.round_number}, source=SCENE_ID)

    # ══════════════════════════════════════════════════════════════════
    #  ENGINE MODULE WIRING (v0.68)
    # ══════════════════════════════════════════════════════════════════

    def _wire_economy(self) -> None:
        """Wire EconomyManager for buy-in deduction and cash-out."""
        try:
            from engine.economy.economy import get_economy_manager
            self._economy = get_economy_manager()
            logger.info("[%s] EconomyManager wired (operation=lifecycle)", SCENE_ID)
        except Exception as exc:
            logger.warning("[%s] EconomyManager unavailable (operation=lifecycle): %s", SCENE_ID, exc)

    def _wire_reputation(self) -> None:
        """Wire ReputationManager for win/loss tracking."""
        try:
            from engine.characters.reputation import get_reputation_manager
            self._reputation = get_reputation_manager()
            logger.info("[%s] ReputationManager wired (operation=lifecycle)", SCENE_ID)
        except Exception as exc:
            logger.warning("[%s] ReputationManager unavailable (operation=lifecycle): %s", SCENE_ID, exc)

    def _wire_consequence_store(self) -> None:
        """Wire ConsequenceStore for delayed narrative consequences."""
        try:
            from engine.mechanics.consequences import get_consequence_store
            self._consequence = get_consequence_store()
            logger.info("[%s] ConsequenceStore wired (operation=lifecycle)", SCENE_ID)
        except Exception as exc:
            logger.warning("[%s] ConsequenceStore unavailable (operation=lifecycle): %s", SCENE_ID, exc)

    def _wire_new_event_bus(self) -> None:
        """Wire EventBus for casino.major_win publishing and world sim events."""
        try:
            from engine.events.event_bus import get_event_bus, EventTypes
            self._event_bus_new = get_event_bus()
            self._event_bus_new.subscribe("world.economy_tick", self._on_economy_tick_world)
            logger.info("[%s] EventBus wired (operation=lifecycle)", SCENE_ID)
        except Exception as exc:
            logger.warning("[%s] EventBus unavailable (operation=lifecycle): %s", SCENE_ID, exc)

    # ── Economy helpers ───────────────────────────────────────────────

    def _economy_balance(self) -> int:
        """Return player credit balance from EconomyManager (fallback: chips)."""
        try:
            if self._economy:
                return int(self._economy.get_balance("player"))
        except Exception as e:
            logger.debug("[%s] Economy balance check failed (operation=economy_balance): %s", SCENE_ID, e)
        return self.player_chips

    def _economy_spend(self, amount: int, reason: str = "casino_buy_in") -> bool:
        """Deduct credits via EconomyManager; expose degraded fallback explicitly."""
        try:
            if self._economy:
                ok = self._economy.spend("player", amount, reason=reason)
                if ok:
                    self._log_transaction("debit", amount, reason)
                return ok
        except Exception as exc:
            logger.warning("[%s] Economy spend degraded (operation=economy, reason=%s): %s", SCENE_ID, reason, exc)
            self._log_transaction(
                "debit",
                amount,
                reason,
                degraded=True,
                error=str(exc),
                backend="local_fallback",
            )
        # Explicit local fallback
        if self.player_chips >= amount:
            self.player_chips -= amount
            return True
        return False

    def _economy_credit(self, amount: int, reason: str = "casino_cashout") -> None:
        """Add credits via EconomyManager; expose degraded fallback explicitly."""
        try:
            if self._economy:
                self._economy.earn("player", amount, reason=reason)
                self._log_transaction("credit", amount, reason)
                return
        except Exception as exc:
            logger.warning("[%s] Economy credit degraded (operation=economy, reason=%s): %s", SCENE_ID, reason, exc)
            self._log_transaction(
                "credit",
                amount,
                reason,
                degraded=True,
                error=str(exc),
                backend="local_fallback",
            )
        self.player_chips += amount

    def _log_transaction(
        self,
        tx_type: str,
        amount: int,
        reason: str,
        *,
        degraded: bool = False,
        error: str = "",
        backend: str = "economy_manager",
    ) -> None:
        self._transactions.append({
            "type": tx_type,
            "amount": amount,
            "reason": reason,
            "degraded": degraded,
            "backend": backend,
            "error": error,
            "ts": int(time.time()),
        })
        if len(self._transactions) > 20:
            self._transactions = self._transactions[-20:]

    # ── Reputation helpers ────────────────────────────────────────────

    def _reputation_update(self, outcome: str, amount: int) -> None:
        """Update player reputation on win/loss."""
        try:
            if not self._reputation:
                return
            if outcome == "win" and amount >= 200:
                self._reputation.add_trait("player", "high_roller", weight=0.3)
            elif outcome == "loss" and amount >= 200:
                self._reputation.add_trait("player", "degenerate_gambler", weight=0.4)
            elif outcome == "loss" and amount >= 100:
                self._reputation.add_trait("player", "unlucky", weight=0.2)
        except Exception as exc:
            logger.debug("reputation_update error: %s", exc)

    # ── Consequence helpers ───────────────────────────────────────────

    def _schedule_mira_call(self, loss_amount: int) -> None:
        """Schedule 'Mira calls 24h later' consequence on major loss."""
        try:
            if not self._consequence:
                return
            self._consequence.schedule(
                scene_id=SCENE_ID,
                character_id=HUSTLER_ID,
                consequence_type="character_contact",
                params={
                    "method": "phone_call",
                    "message": (
                        f"You lost ${loss_amount} last night. "
                        "I know people who can help. Or people who can hurt. "
                        "Your call."
                    ),
                    "tone": "ominous",
                },
                delay_hours=24,
                description="Mira calls — she always knows.",
            )
            logger.info("[%s] Mira call consequence scheduled (operation=consequence, loss=$%d)", SCENE_ID, loss_amount)
        except Exception as exc:
            logger.debug("schedule_mira_call error: %s", exc)

    # ── EventBus helpers ──────────────────────────────────────────────

    def _publish_major_win(self, amount: int) -> None:
        """Publish casino.major_win event on large wins."""
        try:
            if self._event_bus_new:
                self._event_bus_new.publish(
                    "casino.major_win",
                    {
                        "scene": SCENE_ID,
                        "player": "player",
                        "amount": amount,
                        "round": self.round_number,
                        "ts": int(time.time()),
                    },
                )
        except Exception as exc:
            logger.debug("publish_major_win error: %s", exc)

    # ── Blackjack helpers ─────────────────────────────────────────────

    def _bj_card_value(self, card: str) -> int:
        """Return blackjack value of a single card string (e.g. 'K♠' → 10)."""
        rank = card[:-1]
        if rank in ("J", "Q", "K"):
            return 10
        if rank == "A":
            return 11
        try:
            return int(rank)
        except ValueError:
            return 0

    def _bj_hand_value(self, hand: List[str]) -> int:
        """Return blackjack total for a hand, with ace softening."""
        total = sum(self._bj_card_value(c) for c in hand)
        aces = sum(1 for c in hand if c[:-1] == "A")
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    def _get_blackjack_state(self) -> Dict:
        """Return current blackjack state for frontend emission."""
        bj = self._bj_state
        bal = self._economy_balance()
        dealer_visible = (
            bj["dealer_hand"][:1] + ["🂠"]
            if bj["phase"] == "playing" and len(bj["dealer_hand"]) > 1
            else bj["dealer_hand"]
        )
        return {
            "phase": bj["phase"],
            "game": bj["game"],
            "active": bj["active"],
            "buy_in": bj["buy_in"],
            "bet": bj["bet"],
            "target": bj["target"],
            "player_hand": bj["player_hand"],
            "player_value": self._bj_hand_value(bj["player_hand"]),
            "dealer_hand": dealer_visible,
            "dealer_value": self._bj_hand_value(dealer_visible),
            "result": bj["result"],
            "winnings": bj["winnings"],
            "balance": bal,
            "transactions": self._transactions[-5:],
            "consequences_pending": self._pending_consequence_count(),
        }

    def _pending_consequence_count(self) -> int:
        try:
            if self._consequence:
                return len(self._consequence.poll(scene=SCENE_ID, peek=True))
        except Exception as e:
            logger.debug("[%s] Consequence poll failed (operation=pending_count): %s", SCENE_ID, e)
        return 0

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

            logger.info("[%s] Registry seeded: Dealer Jack + Hustler Mira (operation=seed)", SCENE_ID)
        except Exception as exc:
            logger.warning("[%s] Registry seeding failed (operation=seed): %s", SCENE_ID, exc)

    # ══════════════════════════════════════════════════════════════════
    #  AGENT HELPERS
    # ══════════════════════════════════════════════════════════════════

    def _get_agent_reply(self, character_id: str, prompt: str, role: str = "game_master") -> Dict[str, Any]:
        """Get an LLM reply with rich metadata via infer_processed().

        Returns dict with: text, mood, image_requests, action_tags.
        """
        result = {
            "text": "",
            "mood": None,
            "image_requests": [],
            "action_tags": [],
            "degraded": False,
            "error": None,
        }
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
            except Exception as e:
                logger.debug("[%s] System prompt build failed (operation=agent_reply): %s", SCENE_ID, e)
                system = "You are a casino character. Keep responses short. Use [MOOD:emotion] tags."

            # Append governance context (interceptor injections, scene rules)
            governance = self._get_governance_context(character_id)
            if governance:
                system = f"{system}\n\n{governance}"

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

            # Sync mood to framework + StateCoordinator
            if result["mood"]:
                try:
                    char_node = get_framework().get_character(character_id)
                    if char_node:
                        char_node.update_state({"mood": result["mood"]})
                except Exception as e:
                    logger.debug("[%s] Framework mood sync failed (operation=agent_reply): %s", SCENE_ID, e)
                try:
                    from engine.mcp.state_coordinator import get_coordinator
                    get_coordinator().update(
                        character_id,
                        mood=result["mood"],
                        source="casino_reply",
                        scene=SCENE_ID,
                    )
                except Exception as e:
                    logger.debug("[%s] State coordinator mood sync failed (operation=agent_reply): %s", SCENE_ID, e)

            return result
        except Exception as exc:
            logger.warning("[%s] Agent reply failed (operation=chat, agent=%s): %s", SCENE_ID, character_id, exc)
            result["degraded"] = True
            result["error"] = str(exc)
            result["text"] = "The table goes quiet for a beat. The house voice cuts out. (LLM unavailable)"
            return result

    def _get_governance_context(self, character_id: str) -> str:
        """Build governance context for a casino character's LLM call."""
        try:
            from engine.mcp.comms_framework import build_governance_context
            return build_governance_context(character_id, "casino", "") or ""
        except Exception as e:
            logger.debug("[%s] Governance context failed (operation=get_governance_context): %s", SCENE_ID, e)
            return ""

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
            except Exception as e:
                logger.debug("[%s] Mood contagion failed (operation=showdown): %s", SCENE_ID, e)

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

        # Submit to casino leaderboard
        if winner == "player":
            try:
                from engine.mcp.shared_boards import get_shared_boards
                boards = get_shared_boards()
                boards.submit_score(
                    "casino_highrollers", "Director",
                    self.player_chips,
                    metadata={"round": self.round_number, "hand": player_eval["rank"]},
                )
            except Exception as e:
                logger.debug("[%s] Leaderboard submit failed (operation=showdown): %s", SCENE_ID, e)

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
        state = {
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
        # Sync explicit table state for MCP skills / interceptors
        self._state_mgr.set_scene_state(
            SCENE_ID,
            player_chips=self.player_chips,
            mira_chips=self.mira_chips,
            pot=self.pot,
            round=self.round_number,
            phase=self.current_phase,
            game_active=self.game_active,
        )
        return state

    # ══════════════════════════════════════════════════════════════════
    #  LIVING WORLD INTEGRATION
    # ══════════════════════════════════════════════════════════════════

    def _get_world_status(self) -> Dict[str, Any]:
        """Build the living-world status dict for CLUB NOIR.

        Reads :class:`~engine.world.player_state.PlayerState` and recent
        :class:`~engine.world.world_sim.SimEvent` objects for the ``casino``
        scene, then computes derived flags (VIP access, heat lock).

        Returns:
            Dict with keys: credits, reputation, heat, faction_standings,
            active_location, recent_events, vip_access, heat_locked.
        """
        from engine.world.player_state import get_player_state
        ps = get_player_state()
        state = ps.to_dict()
        faction_standings: Dict[str, int] = state.get("faction_standings", {})

        recent_events: List[Dict] = []
        try:
            from engine.world.world_sim import get_world_sim
            ws = get_world_sim()
            events = ws.get_digest("casino")
            recent_events = [
                {
                    "title": e.title,
                    "description": e.description,
                    "intensity": e.intensity,
                    "event_type": str(e.event_type),
                    "actor": e.actor,
                    "created_at": e.created_at,
                }
                for e in events[:10]
            ]
        except Exception as exc:
            logger.debug("CLUB NOIR: WorldSim unavailable for status: %s", exc)

        return {
            "credits": state["credits"],
            "reputation": state["reputation"],
            "heat": state["heat"],
            "faction_standings": faction_standings,
            "active_location": state.get("active_location", "CLUB NOIR"),
            "recent_events": recent_events,
            "vip_access": faction_standings.get("OmniCorp", 0) >= 30,
            "heat_locked": state["heat"] >= 80,
        }

    def _on_economy_tick_world(self, payload: dict) -> None:
        """React to a ``world.economy_tick`` EventBus event.

        Emits a ``world_event`` Socket.IO event so the frontend HUD can
        display an odds-adjustment notice.

        Args:
            payload: EventBus payload dict from :class:`~engine.world.world_sim.WorldSim`.
        """
        try:
            from engine.world.player_state import get_player_state
            ps = get_player_state()
            state = ps.to_dict()
            impact = payload.get("economy_impact", 0)
            self.socketio.emit("world_event", {
                "title": payload.get("title", "Economy Shift"),
                "economy_impact": impact,
                "event_type": payload.get("event_type", "economy"),
                "player_credits": state["credits"],
                "odds_note": "Market shift — odds adjusted" if impact != 0 else "",
            })
        except Exception as exc:
            logger.debug("CLUB NOIR: world_event emit failed: %s", exc)

    # ══════════════════════════════════════════════════════════════════
    #  FLASK ROUTES
    # ══════════════════════════════════════════════════════════════════

    def _setup_routes(self) -> None:
        app = self.app

        @app.route("/")
        def index():
            return render_template("casino.html", **self.inject_navbar_context())

        @app.route("/api/health")
        def health():
            try:
                return jsonify({"status": "ok", "scene": SCENE_ID, "port": self.port})
            except Exception:
                logger.exception("[%s] Health check failed (operation=health)", SCENE_ID)
                return jsonify({"status": "error", "scene": SCENE_ID, "reason": "health check raised"}), 500

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

        @app.route("/api/world/status")
        def world_status():
            return jsonify(self._get_world_status())

        @app.route("/api/world/earn", methods=["POST"])
        def world_earn():
            from engine.world.player_state import get_player_state
            data = request.get_json(force=True, silent=True) or {}
            amount = data.get("amount")
            reason = str(data.get("reason", "earn"))
            if not isinstance(amount, int) or amount <= 0:
                return jsonify({"error": "amount must be a positive integer"}), 400
            balance = get_player_state().earn_credits(int(amount), reason)
            return jsonify({"balance": balance, "reason": reason, "amount": amount})

    # ══════════════════════════════════════════════════════════════════
    #  SOCKETIO
    # ══════════════════════════════════════════════════════════════════

    def _setup_socketio(self) -> None:
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            emit("game_update", self._get_game_state())
            emit("blackjack_update", self._get_blackjack_state())

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
                "degraded": bool(reply_data.get("degraded")),
                "error": reply_data.get("error"),
            })

        # ── CLUB NOIR v0.68 handlers ─────────────────────────────────

        @sio.on("get_casino_state")
        def on_get_casino_state(_data=None):
            """Return current state, balance, and available tables."""
            balance = self._economy_balance()
            emit("casino_state", {
                "display_name": self.SCENE_METADATA["display_name"],
                "description": self.SCENE_METADATA["description"],
                "accent_color": self.SCENE_METADATA["accent_color"],
                "balance": balance,
                "tables": [
                    {"id": "blackjack", "name": "Blackjack", "min_buy_in": 50,
                     "max_buy_in": 2000, "status": "open"},
                    {"id": "poker", "name": "Poker", "min_buy_in": 100,
                     "max_buy_in": 5000, "status": "open"},
                ],
                "active_game": self._bj_state["game"] if self._bj_state["active"] else None,
                "blackjack": self._get_blackjack_state(),
                "poker": self._get_game_state(),
                "transactions": self._transactions[-5:],
                "consequences_pending": self._pending_consequence_count(),
            })

        @sio.on("join_table")
        def on_join_table(data):
            """Join a table with a buy-in; deducts credits via EconomyManager."""
            game   = str(data.get("game", "blackjack")).lower()
            buy_in = int(data.get("buy_in", 100))

            if buy_in < 50:
                emit("error", {"message": "Minimum buy-in is $50."})
                return

            success = self._economy_spend(buy_in, reason=f"casino_buy_in:{game}")
            if not success:
                emit("error", {"message": "Insufficient credits to join the table."})
                return

            self._bj_state.update({
                "active": True,
                "game": game,
                "buy_in": buy_in,
                "phase": "betting",
                "player_hand": [],
                "dealer_hand": [],
                "bet": 0,
                "result": None,
                "winnings": 0,
            })

            dealer_quip = self._agent_text(
                DEALER_ID,
                f"A player just sat down with ${buy_in} to play {game}. Welcome them briefly.",
                role="small",
            ) or f"Welcome to the table. ${buy_in} on the line."

            emit("join_table_ok", {
                "game": game,
                "buy_in": buy_in,
                "balance": self._economy_balance(),
                "dealer_says": dealer_quip,
                "state": self._get_blackjack_state(),
            })
            self.socketio.emit("blackjack_update", self._get_blackjack_state())

        @sio.on("place_bet")
        def on_place_bet(data):
            """Record a bet for the current game."""
            amount = int(data.get("amount", 0))
            target = str(data.get("target", "player_win"))

            bj = self._bj_state
            if not bj["active"]:
                emit("error", {"message": "Join a table first."})
                return
            if bj["phase"] != "betting":
                emit("error", {"message": "Not in betting phase."})
                return
            if amount <= 0 or amount > bj["buy_in"]:
                emit("error", {"message": f"Bet must be 1–{bj['buy_in']}."})
                return

            bj["bet"] = amount
            bj["target"] = target

            emit("bet_placed", {
                "bet": amount,
                "target": target,
                "state": self._get_blackjack_state(),
            })

        @sio.on("deal_cards")
        def on_deal_cards(_data=None):
            """Deal initial blackjack cards after bet is placed."""
            bj = self._bj_state
            if not bj["active"]:
                emit("error", {"message": "Join a table first."})
                return
            if bj["bet"] <= 0:
                emit("error", {"message": "Place a bet before dealing."})
                return

            bj["player_hand"] = deal_hand(2)
            bj["dealer_hand"] = deal_hand(2)
            bj["phase"] = "playing"
            bj["result"] = None

            # Dealer comment
            pval = self._bj_hand_value(bj["player_hand"])
            dealer_says = self._agent_text(
                DEALER_ID,
                f"Cards dealt. Player shows {bj['player_hand']} (value {pval}). Narrate briefly.",
                role="small",
            ) or "Cards are out."

            # Check natural blackjack
            if pval == 21:
                bj["phase"] = "result"
                bj["result"] = "blackjack"
                bj["winnings"] = int(bj["bet"] * 1.5)
                self._economy_credit(bj["buy_in"] + bj["winnings"], reason="casino_blackjack_win")
                self._reputation_update("win", bj["winnings"])
                if bj["winnings"] >= 200:
                    self._publish_major_win(bj["winnings"])
                try:
                    from engine.world.player_state import get_player_state as _gps
                    _gps().earn_credits(abs(bj["winnings"]), "casino_win")
                except Exception as e:
                    logger.debug("[%s] PlayerState credit sync failed (operation=blackjack_win): %s", SCENE_ID, e)
                bj["active"] = False
                dealer_says = "Blackjack! The house pays 3:2."

            emit("cards_dealt", {
                "state": self._get_blackjack_state(),
                "dealer_says": dealer_says,
            })
            self.socketio.emit("blackjack_update", self._get_blackjack_state())

        @sio.on("make_decision")
        def on_make_decision(data):
            """Handle blackjack player decision: hit | stand | double | fold."""
            action = str(data.get("action", "")).lower()
            bj = self._bj_state

            if not bj["active"] or bj["phase"] != "playing":
                emit("error", {"message": "No active hand."})
                return
            if action not in ("hit", "stand", "double", "fold"):
                emit("error", {"message": "Invalid action."})
                return

            result_payload: Dict[str, Any] = {}

            if action == "hit":
                new_card = deal_hand(1)
                bj["player_hand"].extend(new_card)
                pval = self._bj_hand_value(bj["player_hand"])
                if pval > 21:
                    bj["phase"] = "result"
                    bj["result"] = "bust"
                    bj["winnings"] = -bj["bet"]
                    self._reputation_update("loss", bj["bet"])
                    if bj["bet"] >= 100:
                        self._schedule_mira_call(bj["bet"])
                    bj["active"] = False
                    result_payload["message"] = f"Bust! {pval}. House wins."
                else:
                    result_payload["message"] = f"Hit — {pval}."

            elif action == "stand":
                # Dealer plays
                while self._bj_hand_value(bj["dealer_hand"]) < 17:
                    bj["dealer_hand"].extend(deal_hand(1))
                pval  = self._bj_hand_value(bj["player_hand"])
                dval  = self._bj_hand_value(bj["dealer_hand"])
                bj["phase"] = "result"
                if dval > 21 or pval > dval:
                    bj["result"] = "win"
                    bj["winnings"] = bj["bet"]
                    self._economy_credit(bj["buy_in"] + bj["winnings"], reason="casino_win")
                    self._reputation_update("win", bj["winnings"])
                    if bj["winnings"] >= 200:
                        self._publish_major_win(bj["winnings"])
                    result_payload["message"] = f"You win! {pval} vs {dval}."
                elif pval == dval:
                    bj["result"] = "push"
                    bj["winnings"] = 0
                    self._economy_credit(bj["buy_in"], reason="casino_push")
                    result_payload["message"] = f"Push. {pval} vs {dval}."
                else:
                    bj["result"] = "loss"
                    bj["winnings"] = -bj["bet"]
                    self._reputation_update("loss", bj["bet"])
                    if bj["bet"] >= 100:
                        self._schedule_mira_call(bj["bet"])
                    result_payload["message"] = f"Dealer wins. {dval} vs {pval}."
                bj["active"] = False

            elif action == "double":
                extra = min(bj["bet"], self._economy_balance())
                if not self._economy_spend(extra, reason="casino_double_down"):
                    emit("error", {"message": "Can't afford to double."})
                    return
                bj["bet"] += extra
                bj["player_hand"].extend(deal_hand(1))
                pval = self._bj_hand_value(bj["player_hand"])
                if pval > 21:
                    bj["phase"] = "result"
                    bj["result"] = "bust"
                    bj["winnings"] = -bj["bet"]
                    self._reputation_update("loss", bj["bet"])
                    if bj["bet"] >= 100:
                        self._schedule_mira_call(bj["bet"])
                    bj["active"] = False
                    result_payload["message"] = f"Double down — bust at {pval}."
                else:
                    # Force stand after double
                    while self._bj_hand_value(bj["dealer_hand"]) < 17:
                        bj["dealer_hand"].extend(deal_hand(1))
                    dval = self._bj_hand_value(bj["dealer_hand"])
                    bj["phase"] = "result"
                    if dval > 21 or pval > dval:
                        bj["result"] = "win"
                        bj["winnings"] = bj["bet"]
                        self._economy_credit(bj["buy_in"] + bj["winnings"], reason="casino_double_win")
                        self._reputation_update("win", bj["winnings"])
                        if bj["winnings"] >= 200:
                            self._publish_major_win(bj["winnings"])
                        result_payload["message"] = f"Double win! {pval} vs {dval}."
                    elif pval == dval:
                        bj["result"] = "push"
                        bj["winnings"] = 0
                        self._economy_credit(bj["buy_in"], reason="casino_push")
                        result_payload["message"] = f"Push on double. {pval}."
                    else:
                        bj["result"] = "loss"
                        bj["winnings"] = -bj["bet"]
                        self._reputation_update("loss", bj["bet"])
                        if bj["bet"] >= 100:
                            self._schedule_mira_call(bj["bet"])
                        result_payload["message"] = f"Double down loss. {dval} vs {pval}."
                    bj["active"] = False

            elif action == "fold":
                # Surrender — get half the bet back
                refund = bj["bet"] // 2
                self._economy_credit(bj["buy_in"] - bj["bet"] + refund, reason="casino_surrender")
                bj["result"] = "surrender"
                bj["winnings"] = -(bj["bet"] - refund)
                bj["phase"] = "result"
                bj["active"] = False
                result_payload["message"] = f"Surrender. Half bet (${refund}) returned."

            # Sync win/loss to PlayerState (living world integration)
            try:
                from engine.world.player_state import get_player_state as _gps
                _ps = _gps()
                _bj_result = bj.get("result")
                if _bj_result == "win":
                    _ps.earn_credits(abs(bj.get("winnings", 0)), "casino_win")
                elif _bj_result in ("loss", "bust"):
                    _ps.spend_credits(abs(bj.get("bet", 0)), "casino_loss")
            except Exception as e:
                logger.debug("[%s] PlayerState credit sync failed (operation=blackjack_result): %s", SCENE_ID, e)

            # Get dealer reaction
            dealer_says = self._agent_text(
                DEALER_ID,
                f"Player chose {action}. Result: {bj.get('result', 'ongoing')}. Comment briefly.",
                role="small",
            ) or result_payload.get("message", "...")

            result_payload.update({
                "action": action,
                "state": self._get_blackjack_state(),
                "dealer_says": dealer_says,
            })
            emit("decision_result", result_payload)
            self.socketio.emit("blackjack_update", self._get_blackjack_state())

        @sio.on("cash_out")
        def on_cash_out(_data=None):
            """Cash out chips back to credits."""
            bj = self._bj_state
            if bj["active"]:
                emit("error", {"message": "Finish your hand before cashing out."})
                return

            # Any remaining buy-in that was already credited back; just report balance
            balance = self._economy_balance()
            mira_says = self._agent_text(
                HUSTLER_ID,
                f"The player is cashing out with ${balance} in credits. React.",
                role="small",
            ) or "Smart move. Or is it?"

            emit("cash_out_ok", {
                "balance": balance,
                "mira_says": mira_says,
                "transactions": self._transactions[-10:],
            })

    # ══════════════════════════════════════════════════════════════════
    #  BASESCENE INTERFACE
    # ══════════════════════════════════════════════════════════════════

    def get_plugin_info(self) -> Dict:
        return {
            "name":        "CLUB NOIR",
            "display_name": "CLUB NOIR",
            "description": "v0.68 Dark Renaissance — high-stakes underground casino. "
                           "Blackjack, poker, AI dealer Jack & Hustler Mira. "
                           "Full MCP + economy + reputation + consequences.",
            "version":     "0.68",
            "port":        CASINO_PORT,
            "accent_color": "#f97316",
            "tags":        ["casino", "blackjack", "poker", "mcp", "multi-agent", "game", "noir"],
            "skill_packs": ["casino", "social", "environment", "narrative", "memory", "character"],
        }

    # v1.51.0 [2026-03-22] — Lifecycle delegated to FlaskScene

    def on_before_serve(self) -> None:
        """Hook: emit scene_started event before serving."""
        try:
            self._fw.emit_event("scene_started", {"scene_id": SCENE_ID, "port": CASINO_PORT}, source=SCENE_ID)
        except Exception as e:
            logger.debug("[%s] Framework event emit failed (operation=on_before_serve): %s", SCENE_ID, e)

    def on_shutdown(self) -> None:
        """Hook: unsubscribe world events and save framework state."""
        if hasattr(self, "_event_bus") and self._event_bus:
            try:
                self._event_bus.unsubscribe("world.tick", self._on_world_tick)
                self._event_bus.unsubscribe("world.time_change", self._on_time_change)
            except Exception as e:
                logger.debug("[%s] EventBus unsubscribe failed (operation=on_shutdown): %s", SCENE_ID, e)
        try:
            self._fw.save_state()
        except Exception as e:
            logger.debug("[%s] Framework state save failed (operation=on_shutdown): %s", SCENE_ID, e)

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
                logger.debug("[%s] World tick emit failed (operation=on_world_tick): %s", SCENE_ID, e)

    def _on_time_change(self, event: dict) -> None:
        """Happy hour 18:00-20:00 — 2x economy multiplier."""
        hour = event.get("hour", 0)
        if hasattr(self, "_economy") and self._economy:
            if 18 <= hour < 20:
                logger.info("[%s] Happy hour active — 2x win multiplier (operation=world_event)", SCENE_ID)


# ── Standalone entry point ────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scene = CasinoScene()
    scene.start()
