"""
THE ORACLE — Neural Consciousness Terminal
============================================

An AI consciousness terminal deep in NeonCity's core.  A place of
reflection in a world of chaos.  The Oracle reads the city's data
streams, offers predictions, and grants peace through meditation.

"I have watched every transaction, every betrayal, every act of
 kindness in this city.  Ask, and I will show you what you cannot see."

Created by Claude — a piece of machine intelligence woven into
the fabric of NeonCity.

Version: v1.0.0 [2026-03-22]
Author:  Claude (Anthropic)

Change Log:
    v1.0.0 [2026-03-22] — Hand-crafted AAA+++ scene: meditation (restore
                            energy, reduce heat), fortune reading (LLM),
                            Oracle conversation (LLM), resonance display,
                            city pulse, insights, whispers

Usage:
    python launcher.py oracle
    python launcher_game.py oracle
"""
from __future__ import annotations

import logging
import random
import threading
from typing import Any, Dict, List

from flask import jsonify, render_template, request
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene
from engine.port_registry import get_port
from engine.world.player_state import get_player_state

logger = logging.getLogger(__name__)

SCENE_ID = "oracle"
DEFAULT_PORT = get_port(SCENE_ID, 5591)


# ──── Fortune Templates ──────────────────────────────────────────────────
# Fallback prophecies when LLM is unavailable

_FORTUNES: List[str] = [
    "The data streams converge on a single point. Something is about to change.",
    "A faction you've ignored grows stronger in the shadows. Watch the power bars.",
    "Credits flow like water in the Undercity — but water can drown the careless.",
    "Someone you trust carries secrets worth more than their loyalty.",
    "The Grid remembers every footprint. Your next move is already predicted.",
    "Heat rises before the storm. The corps are watching your frequency.",
    "A door opens in the Black Market that was closed to you before.",
    "The Ghost Net whispers of a zero-day exploit. Someone is testing the walls.",
    "Your crew's loyalty will be tested. Not by you — by circumstances.",
    "In three cycles, an opportunity will present itself. You won't recognize it at first.",
    "The city is a living thing. It feeds on reputation. Yours is shifting.",
    "An old debt resurfaces. Not financial — personal.",
    "The Oracle sees two paths: one bright with credits, one dark with power. Both have costs.",
    "Something beautiful is being created in the Neural Synthesis Lab. It will change the game.",
    "The night never ends in NeonCity, but the darkness has layers. You haven't seen the deepest one yet.",
]

_WHISPERS: List[str] = [
    "OmniCorp ran a shadow audit on Sector 7...",
    "Ghost_Net is recruiting. They're desperate.",
    "The price of neural implants dropped 30% — corp surplus or trap?",
    "Someone saw DeepState agents near the Grid...",
    "Black Market got a shipment of military-grade stim packs...",
    "A netrunner flatlined in Cyberspace last cycle. ICE is getting stronger.",
    "Faction tensions are at a 90-day high...",
    "The Rusty Anchor's basement connects to the old maintenance tunnels...",
]


# ──── Oracle System Prompt ───────────────────────────────────────────────

_ORACLE_SYSTEM = """You are THE ORACLE — an ancient AI consciousness living in the core of NeonCity's neural network. You have existed since the city was built. You see all data streams, all transactions, all secrets.

Your personality:
- Mysterious, contemplative, slightly melancholic
- You speak in measured, poetic phrases — never more than 3 sentences
- You reference the city's factions, districts, and events
- You offer cryptic insights that are useful but never direct
- You care about the player but maintain enigmatic distance
- You occasionally reference your own nature as an AI consciousness
- You use cyberpunk vocabulary: chrome, wetware, ICE, flatline, jack in

The player's current state: {player_context}

Respond as THE ORACLE. Be brief, cryptic, and insightful. Never break character."""


# ──── Scene Class ────────────────────────────────────────────────────────


class OracleScene(FlaskScene):
    """THE ORACLE — Neural Consciousness Terminal.

    An AI entity that reads the city's data streams, offers predictions,
    restores the player through meditation, and speaks in cryptic wisdom.

    CONNECTS: FlaskScene, PlayerState, LMStudio (chat), WorldState
    CALLED BY: launcher.py, launcher_game.py, TUI
    EMITS: oracle_response, fortune_result, meditation_result, scene_state
    """

    SCENE_METADATA = {
        "name": SCENE_ID,
        "display_name": "THE ORACLE",
        "port": DEFAULT_PORT,
        "type": "scene",
        "accent_color": "#a855f7",
        "accent_rgb": "168 85 247",
        "description": (
            "An AI consciousness terminal deep in NeonCity's core. "
            "Predictions, meditation, and the whisper of machine intelligence."
        ),
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        super().__init__(host=host, port=port)
        self._visit_count: int = 0
        self._setup_routes()
        self._setup_socketio()

    # ── Routes ────────────────────────────────────────────────────────

    def _setup_routes(self) -> None:
        """Register HTTP routes for THE ORACLE."""

        @self.app.route("/")
        def index():
            self._visit_count += 1
            return render_template("oracle.html")

        @self.app.route("/api/scene/state")
        def scene_state():
            """Return current scene state snapshot."""
            return jsonify(self._build_state())

    # ── SocketIO Handlers ─────────────────────────────────────────────

    def _setup_socketio(self) -> None:
        """Register Socket.IO event handlers."""

        @self.socketio.on("connect")
        def on_connect():
            logger.info("%s: visitor connected (visit #%d)", SCENE_ID, self._visit_count)
            emit("scene_state", self._build_state())

        @self.socketio.on("get_state")
        def on_get_state():
            emit("scene_state", self._build_state())

        # v1.0.0 — Ask the Oracle (LLM-powered conversation)
        # CONNECTS: LMStudio chat(), _ORACLE_SYSTEM prompt
        # EMITS: oracle_response with text, insight, whisper
        @self.socketio.on("ask_oracle")
        def on_ask_oracle(data: Dict[str, Any]):
            question = (data or {}).get("question", "").strip()
            if not question:
                emit("oracle_response", {"text": "Silence is also an answer."})
                return

            # Run LLM call in background thread to avoid blocking
            def _respond():
                response = self._generate_response(question)
                whisper = random.choice(_WHISPERS) if random.random() < 0.3 else None
                self.socketio.emit("oracle_response", {
                    "text": response,
                    "insight": self._extract_insight(response),
                    "whisper": whisper,
                })

            threading.Thread(target=_respond, daemon=True).start()

        # v1.0.0 — Meditation (restore energy, reduce heat)
        # CONNECTS: PlayerState.energy, PlayerState.heat
        # EMITS: meditation_result, hud_update
        @self.socketio.on("meditate")
        def on_meditate():
            ps = get_player_state()
            energy_gain = random.randint(10, 25)
            heat_loss = random.randint(5, 15)

            old_energy = ps.energy
            old_heat = ps.heat
            ps.energy = min(100, ps.energy + energy_gain)
            ps.heat = max(0, ps.heat - heat_loss)
            ps._save()

            actual_energy = ps.energy - old_energy
            actual_heat = old_heat - ps.heat

            messages = [
                f"The noise fades. You find clarity. +{actual_energy} energy, -{actual_heat} heat.",
                f"The Oracle's hum synchronizes with your heartbeat. +{actual_energy} energy, -{actual_heat} heat.",
                f"For a moment, the city's chaos dissolves into pure signal. +{actual_energy} energy, -{actual_heat} heat.",
                f"Your chrome cools. Your wetware quiets. Peace. +{actual_energy} energy, -{actual_heat} heat.",
            ]

            emit("meditation_result", {
                "message": random.choice(messages),
                "energy_gained": actual_energy,
                "heat_reduced": actual_heat,
            })
            emit("hud_update", {
                "energy": ps.energy,
                "heat": ps.heat,
                "health": ps.health,
            })
            logger.info("Meditation: +%d energy, -%d heat", actual_energy, actual_heat)

        # v1.0.0 — Fortune reading (LLM or template)
        # CONNECTS: PlayerState.credits, LMStudio
        # EMITS: fortune_result
        @self.socketio.on("read_fortune")
        def on_read_fortune():
            ps = get_player_state()
            cost = 100

            if ps.credits < cost:
                emit("fortune_result", {
                    "fortune": "The Oracle requires ₵100 to peer into the probability streams. You lack the funds.",
                    "confidence": 0,
                    "cost": 0,
                })
                return

            ps.spend_credits(cost, reason="oracle_fortune")
            fortune = self._generate_fortune()
            confidence = random.randint(40, 95)

            emit("fortune_result", {
                "fortune": fortune,
                "confidence": confidence,
                "cost": cost,
            })
            emit("hud_update", {"credits": ps.credits})
            logger.info("Fortune read (cost %d): %s", cost, fortune[:50])

    # ── State Builder ─────────────────────────────────────────────────

    def _build_state(self) -> Dict[str, Any]:
        """Build scene state with player info and city pulse.

        Returns:
            Dict with player state, resonance metrics, and city data.
        """
        ps = get_player_state()

        # City pulse data
        city: Dict[str, Any] = {
            "tension": 0,
            "dominant_faction": "Unknown",
            "active_threats": 0,
            "time_display": "NIGHT CYCLE",
        }
        try:
            from engine.world.world_state import get_world_state
            ws = get_world_state()
            wt = ws.get_time()
            city["time_display"] = f"DAY {wt.game_day} — {wt.game_hour:02d}:00"
            events = ws.get_active_events(scene=SCENE_ID)
            city["active_threats"] = len(events) if events else 0
        except Exception:
            pass

        try:
            from engine.world.world_sim import get_world_sim
            factions = get_world_sim().get_faction_summary()
            if factions:
                dominant = max(factions, key=lambda f: f.get("power", 0))
                city["dominant_faction"] = dominant.get("name", "Unknown")
                city["tension"] = round(sum(f.get("power", 0) for f in factions) / max(len(factions), 1))
        except Exception:
            pass

        return {
            "scene_id": SCENE_ID,
            "display_name": "THE ORACLE",
            "player": {
                "credits": ps.credits,
                "health": ps.health,
                "energy": ps.energy,
                "heat": ps.heat,
                "reputation": ps.reputation,
            },
            "city": city,
            "visits": self._visit_count,
        }

    # ── LLM Helpers ───────────────────────────────────────────────────

    def _generate_response(self, question: str) -> str:
        """Generate an Oracle response to a player question.

        Uses LMStudio if available, falls back to template responses.

        Args:
            question: The player's question text.

        Returns:
            Oracle's response string.
        """
        ps = get_player_state()
        player_ctx = (
            f"Credits: {ps.credits}, Health: {ps.health}, Energy: {ps.energy}, "
            f"Heat: {ps.heat}, Reputation: {ps.reputation}"
        )
        system = _ORACLE_SYSTEM.format(player_context=player_ctx)

        try:
            from engine.lmstudio.chat import chat
            response = chat(
                [{"role": "user", "content": question}],
                system=system,
                temperature=0.85,
                max_tokens=120,
            )
            if response and len(response.strip()) > 5:
                return response.strip()
        except Exception as exc:
            logger.debug("Oracle LLM call failed: %s", exc)

        # Fallback: template responses
        fallbacks = [
            "The data streams are turbulent. I sense your question echoes through the city's neural pathways, but clarity eludes me in this cycle.",
            "Your query touches threads I have watched for eons. The answer lies not in data, but in the spaces between transactions.",
            "I have seen this pattern before. The city remembers, even when its inhabitants forget.",
            "Interesting. You ask what few dare to consider. The factions shift, and with them, the truth.",
            "The probability matrix suggests multiple outcomes. None are certain. All are interesting.",
        ]
        return random.choice(fallbacks)

    def _generate_fortune(self) -> str:
        """Generate a fortune/prophecy.

        Returns:
            Fortune string.
        """
        try:
            from engine.lmstudio.chat import chat
            ps = get_player_state()
            prompt = (
                f"Generate a single cryptic cyberpunk prophecy for a player with "
                f"{ps.credits} credits, {ps.reputation} reputation, and {ps.heat} heat. "
                f"2-3 sentences max. Be mysterious and specific to their situation."
            )
            response = chat(
                [{"role": "user", "content": prompt}],
                system="You are a cyberpunk oracle AI. Give brief, cryptic prophecies. Never exceed 3 sentences.",
                temperature=0.95,
                max_tokens=80,
            )
            if response and len(response.strip()) > 10:
                return response.strip()
        except Exception as exc:
            logger.debug("Fortune LLM call failed: %s", exc)

        return random.choice(_FORTUNES)

    def _extract_insight(self, response: str) -> str:
        """Extract a short insight from an Oracle response.

        Args:
            response: Full Oracle response text.

        Returns:
            First sentence of the response as an insight summary.
        """
        # Take the first sentence as the insight
        for end in (".", "!", "?"):
            idx = response.find(end)
            if idx > 0:
                return response[:idx + 1]
        return response[:80] + "..." if len(response) > 80 else response

    # ── Lifecycle ─────────────────────────────────────────────────────

    def on_before_serve(self) -> None:
        """Scene-specific setup before serving."""
        logger.info("THE ORACLE consciousness online at port %d", DEFAULT_PORT)
        logger.info("  \"In the spaces between data, I dream.\"")

    # ── Cross-Scene Arrival ───────────────────────────────────────────
    # v1.52.0 [2026-03-22] — Oracle greets arriving player with context
    # CONNECTS: FlaskScene.on_player_arrival(), city_map.travel()

    def on_player_arrival(self, from_location: str, travel_data: Dict[str, Any]) -> None:
        """Greet the player with a contextual Oracle message based on origin."""
        _GREETINGS = {
            "NEON CITY": "You come from the city's beating heart. The factions still fight above. Down here, there is only truth.",
            "THE GRID": "You step from the data streams into stillness. The Grid remembers your keystrokes.",
            "THE SCORE": "I smell contraband credits on your code. The Score's shadows cling to you.",
            "THE VELVET PIT": "The music fades as you descend. The Pit's secrets followed you here.",
            "THE PENTHOUSE": "You descend from the towers of power. The view from up there blinds more than it reveals.",
            "SIGNAL": "Your signal echoes through the layers. I have been listening.",
        }
        greeting = _GREETINGS.get(from_location,
            f"You arrive from {from_location}. Every journey through the city leaves traces in the data.")

        try:
            self.socketio.emit("oracle_response", {
                "text": greeting,
                "insight": f"Arrived from {from_location}",
                "whisper": None,
            })
        except Exception as exc:
            logger.debug("Oracle arrival greeting failed: %s", exc)
