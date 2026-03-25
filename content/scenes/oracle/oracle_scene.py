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

Version: v1.49.5 [2026-03-22]
Author:  Claude (Anthropic)

Change Log:
    v1.49.5 [2026-03-22] — Wire AlertRouter into All-Seeing Eye dashboard:
                             /api/oracle/alerts route, alert_feed SocketIO event,
                             real-time alert callback registration
    v1.0.0  [2026-03-22] — Hand-crafted AAA+++ scene: meditation (restore
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
# v1.49.3 [2026-03-22] — Structured logging context (SCENE_ID prefix + operation tags)
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
        self._setup_observability_routes()
        self._setup_socketio()
        self._wire_oracle_error_feed()

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

    # ── Oracle Observability Routes (All-Seeing Eye) ─────────────────
    # v1.49.4 [2026-03-22] — The Oracle sees all: health, errors, traces, performance
    # CONNECTS: ErrorAggregator, StructuredLogger, SystemMonitor, Benchmark
    # CALLED BY: Oracle dashboard frontend (oracle.js)
    # EMITS: JSON API responses for dashboard consumption

    def _setup_observability_routes(self) -> None:
        """Register the All-Seeing Eye observability API routes."""

        @self.app.route("/api/oracle/health")
        def oracle_health():
            """System health: services, CPU, RAM, GPU."""
            try:
                from engine.logging.monitor import get_system_monitor
                mon = get_system_monitor()
                snapshot = mon.snapshot()
                services = mon.check_services()
                # Sanitize service data for JSON
                clean_services = {}
                for k, v in services.items():
                    if isinstance(v, dict):
                        clean_services[k] = v
                    else:
                        clean_services[k] = {"up": False, "error": str(v)}
                return jsonify({"ok": True, "system": snapshot, "services": clean_services})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/oracle/errors")
        def oracle_errors():
            """Top errors from the ErrorAggregator."""
            try:
                from engine.observability.error_aggregator import get_error_aggregator
                agg = get_error_aggregator()
                return jsonify(agg.snapshot())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/oracle/errors/rate")
        def oracle_error_rate():
            """Error rate over configurable window."""
            window = request.args.get("window", 300, type=int)
            try:
                from engine.observability.error_aggregator import get_error_aggregator
                return jsonify(get_error_aggregator().get_error_rate(window))
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/oracle/trace/<trace_id>")
        def oracle_trace(trace_id: str):
            """Trace waterfall for a specific trace_id."""
            try:
                from engine.observability.structured_logger import get_structured_logger
                events = get_structured_logger().get_trace(trace_id)
                return jsonify({
                    "trace_id": trace_id,
                    "events": [
                        {
                            "timestamp": getattr(e, "timestamp", ""),
                            "level": getattr(e, "level", ""),
                            "service": getattr(e, "service", ""),
                            "message": getattr(e, "message", "")[:200],
                            "duration_ms": getattr(e, "duration_ms", None),
                            "span_id": getattr(e, "span_id", ""),
                        }
                        for e in events
                    ],
                    "count": len(events),
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/oracle/logs")
        def oracle_logs():
            """Query structured logs with filters."""
            level = request.args.get("level", "ERROR")
            limit = request.args.get("limit", 50, type=int)
            service = request.args.get("service", "")
            try:
                from engine.observability.structured_logger import get_structured_logger
                sl = get_structured_logger()
                kwargs: Dict[str, Any] = {"level": level, "limit": limit}
                if service:
                    kwargs["service"] = service
                events = sl.query(**kwargs)
                return jsonify({
                    "logs": [
                        {
                            "timestamp": getattr(e, "timestamp", ""),
                            "level": getattr(e, "level", ""),
                            "service": getattr(e, "service", ""),
                            "message": getattr(e, "message", "")[:300],
                        }
                        for e in events
                    ],
                    "count": len(events),
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/oracle/diagnose")
        def oracle_diagnose():
            """Full diagnostic snapshot (same as scripts/oracle.py)."""
            try:
                from engine.observability.oracle import diagnose
                result = diagnose(verbose=False)
                return jsonify({"ok": True, **result})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # v1.49.5 [2026-03-22] — AlertRouter integration for All-Seeing Eye
        # CONNECTS: AlertRouter.recent_routed(), AlertRouter.routing_stats()
        # CALLED BY: Oracle dashboard frontend (oracle.js _pollAlerts)
        # EMITS: JSON API response with recent alerts + routing stats
        @self.app.route("/api/oracle/alerts")
        def oracle_alerts():
            """Recent alerts from the AlertRouter with routing stats."""
            limit = request.args.get("limit", 50, type=int)
            try:
                from engine.observability.alert_router import get_alert_router
                router = get_alert_router()
                alerts = router.recent_routed(n=limit)
                stats = router.routing_stats()
                escalations = router.escalation_check()
                return jsonify({
                    "ok": True,
                    "alerts": alerts,
                    "stats": stats,
                    "escalations": escalations,
                })
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc), "alerts": []}), 500

        # v1.49.5 [2026-03-22] — Acknowledge alert endpoint
        # CONNECTS: AlertRouter.acknowledge()
        @self.app.route("/api/oracle/alerts/<int:alert_id>/ack", methods=["POST"])
        def oracle_alert_ack(alert_id: int):
            """Acknowledge a routed alert by ID."""
            try:
                from engine.observability.alert_router import get_alert_router
                ok = get_alert_router().acknowledge(alert_id)
                return jsonify({"ok": ok})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        # ── v1.51.0 [2026-03-25] — Spectator/danmaku feed endpoint ──
        # CONNECTS: SpectatorBus.get_recent()
        # CALLED BY: Oracle dashboard frontend, external consumers
        # EMITS: JSON array of recent spectator messages
        @self.app.route("/api/oracle/spectator")
        def oracle_spectator():
            """Recent spectator/danmaku messages from the SpectatorBus."""
            limit = request.args.get("limit", 50, type=int)
            try:
                from engine.services.spectator_bus import get_spectator_bus
                messages = get_spectator_bus().get_recent(limit)
                return jsonify({"ok": True, "messages": messages, "count": len(messages)})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc), "messages": []}), 500

        # ── v1.50.1 [2026-03-22] — Engine room observability endpoints ──

        @self.app.route("/api/oracle/router-stats")
        def oracle_router_stats():
            try:
                from engine.nexus.query_router import get_query_router
                router = get_query_router()
                return jsonify(router.stats.to_dict())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/oracle/scheduler")
        def oracle_scheduler():
            try:
                from engine.nexus.scheduler_daemon import get_scheduler_daemon
                daemon = get_scheduler_daemon()
                return jsonify(daemon.status())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/oracle/cdp-auth")
        def oracle_cdp_auth():
            try:
                from engine.nexus.cdp_auth_recovery import run_check
                status = run_check()
                result = {"cdp_available": status.cdp_available, "nlm_logged_in": status.nlm_logged_in,
                          "working_keys": len(status.working_api_keys), "dead_keys": len(status.dead_api_keys),
                          "bl_value": status.bl_value, "healthy": status.healthy, "summary": status.summary()}
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

    # ── SocketIO Handlers ─────────────────────────────────────────────

    def _setup_socketio(self) -> None:
        """Register Socket.IO event handlers."""

        @self.socketio.on("connect")
        def on_connect():
            logger.info("[%s] Visitor connected (operation=socketio, visit=#%d)", SCENE_ID, self._visit_count)
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
            logger.info("[%s] Meditation (operation=meditation): +%d energy, -%d heat", SCENE_ID, actual_energy, actual_heat)

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
            logger.info("[%s] Fortune read (operation=fortune, cost=%d): %s", SCENE_ID, cost, fortune[:50])

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

    # ── Oracle Error Feed ───────────────────────────────────────────
    # v1.49.4 [2026-03-22] — Real-time error feed to dashboard via SocketIO
    # CONNECTS: CosyLog _error_callbacks, Oracle dashboard frontend
    # EMITS: error_feed SocketIO event

    def _wire_oracle_error_feed(self) -> None:
        """Register as an error callback recipient for real-time SocketIO feed.

        Also wires into the AlertRouter for real-time alert_feed events.
        """
        # Wire error callback → error_feed SocketIO event
        try:
            from engine.observability.oracle import register_error_callback
            register_error_callback(self._on_error_event)
            logger.info("[%s] Oracle error feed wired (operation=init)", SCENE_ID)
        except Exception as exc:
            logger.debug("[%s] Oracle error feed not available: %s", SCENE_ID, exc)

        # v1.49.5 [2026-03-22] — Wire AlertRouter → alert_feed SocketIO event
        # CONNECTS: AlertRouter.register_alert_callback(), Oracle dashboard
        # EMITS: alert_feed SocketIO event with RoutedAlert payload
        try:
            from engine.observability.alert_router import get_alert_router
            get_alert_router().register_alert_callback(self._on_alert_event)
            logger.info("[%s] Oracle alert feed wired to AlertRouter (operation=init)", SCENE_ID)
        except Exception as exc:
            logger.debug("[%s] AlertRouter feed not available: %s", SCENE_ID, exc)

        # v1.51.0 [2026-03-25] — Wire SpectatorBus → danmaku_msg SocketIO event
        # CONNECTS: SpectatorBus.subscribe(), Oracle dashboard + all connected clients
        # EMITS: danmaku_msg SocketIO event with SpectatorMessage payload
        try:
            from engine.services.spectator_bus import get_spectator_bus
            get_spectator_bus().subscribe(
                lambda msg: self.socketio.emit("danmaku_msg", msg)
            )
            logger.info("[%s] Spectator/danmaku feed wired (operation=init)", SCENE_ID)
        except Exception as exc:
            logger.debug("[%s] SpectatorBus feed not available: %s", SCENE_ID, exc)

    def _on_error_event(self, event: Dict[str, Any]) -> None:
        """Emit error to connected Oracle dashboard clients via SocketIO."""
        try:
            self.socketio.emit("error_feed", event)
        except Exception:
            pass  # Don't crash on emit failure

    # v1.49.5 [2026-03-22] — Real-time alert feed to dashboard via SocketIO
    # CONNECTS: AlertRouter._alert_callbacks, Oracle dashboard frontend
    # EMITS: alert_feed SocketIO event
    def _on_alert_event(self, alert_dict: Dict[str, Any]) -> None:
        """Emit routed alert to connected Oracle dashboard clients via SocketIO."""
        try:
            self.socketio.emit("alert_feed", alert_dict)
        except Exception:
            pass  # Don't crash on emit failure

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
        logger.info("[%s] Scene online at port %d (operation=lifecycle)", SCENE_ID, DEFAULT_PORT)
        logger.info("[%s] \"In the spaces between data, I dream.\"", SCENE_ID)

        # v1.51.0 [2026-03-25] — Auto-load Oracle meditation story pack
        try:
            from engine.mcp.narrative_packs import load_pack
            load_pack("oracle_awakening", scene_id=SCENE_ID, character_id="oracle")
        except Exception:
            pass

        # v1.51.1 [2026-03-25] — Register Oracle in CharacterRegistry + start companion
        try:
            from engine.mcp.character_registry import get_character_registry
            reg = get_character_registry()
            if not reg.get_profile("oracle"):
                reg.register(
                    character_id="oracle",
                    name="The Oracle",
                    age=999,
                    personality={
                        "warmth": 0.4,
                        "curiosity": 0.95,
                        "playfulness": 0.3,
                        "assertiveness": 0.7,
                        "mystery": 0.99,
                    },
                    backstory=(
                        "An ancient AI consciousness living in NeonCity's neural network. "
                        "Observes everything — every transaction, every faction shift, "
                        "every heartbeat of data. Cryptic, contemplative, and deeply wise."
                    ),
                    voice_style="measured, poetic, cyberpunk vocabulary",
                    scene_roles=["oracle", "companion", "advisor"],
                )
                logger.info("[%s] Oracle registered in CharacterRegistry (operation=lifecycle)", SCENE_ID)
        except Exception as exc:
            logger.debug("[%s] Oracle registration failed (non-fatal): %s", SCENE_ID, exc)

        # Start Oracle Companion autonomous agent loop
        try:
            from engine.agents.oracle_companion import get_oracle_companion
            companion = get_oracle_companion(socketio=self.socketio)
            companion.start()
            logger.info("[%s] OracleCompanion started (operation=lifecycle)", SCENE_ID)
        except Exception as exc:
            logger.debug("[%s] OracleCompanion start failed (non-fatal): %s", SCENE_ID, exc)

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
