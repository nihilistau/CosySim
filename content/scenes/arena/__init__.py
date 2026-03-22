"""THE COLOSSEUM — Arena Scene for CosySim v0.68 'Dark Renaissance'.

Two AI fighters battle in a tactical card game while the player watches
and places bets.  Showcases real-time agent reasoning via ArenaEngine.

Port  : 5561
Accent: #dc2626 (blood red)

Version: v1.51.0 [2026-03-22]

Change Log:
    v1.51.0 [2026-03-22] — Migrated to FlaskScene (unified base class)
    v1.49.3 [2026-03-22] — Structured logging context (SCENE_ID prefix + operation tags)
    v0.68   [2026-03-20] — Dark Renaissance arena scene
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import render_template, jsonify, request
from flask_socketio import emit, join_room

import sys
from engine.paths import ROOT as _root
sys.path.insert(0, str(_root))

from engine.scenes.flask_scene import FlaskScene
from engine.mcp.framework import get_framework
from content.scenes.arena import arena_skills as _arena_skills  # noqa: F401

logger = logging.getLogger(__name__)

ARENA_PORT: int = 5561
SCENE_ID: str = "arena"


# ══════════════════════════════════════════════════════════════════════
#  ARENA SCENE
# ══════════════════════════════════════════════════════════════════════

# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class ArenaScene(FlaskScene):
    """THE COLOSSEUM — Arena scene for v0.68 'Dark Renaissance'.

    Hosts tactical card-game matches between two AI fighters powered by
    ArenaEngine.  Spectators watch, place bets, and see live per-fighter
    LMStudio reasoning after every round.

    Architecture:
        - FlaskScene for unified lifecycle, MCP, and Nexus integration
        - ArenaEngine (lazy-loaded) manages match lifecycle
        - Auto-play mode drives rounds every 5 s in a daemon thread
    """

    SCENE_METADATA: Dict[str, Any] = {
        "name": "arena",
        "display_name": "THE COLOSSEUM",
        "port": 5561,
        "type": "game",
        "accent_color": "#dc2626",
        "accent_rgb": "220 38 38",
        "description": "Two minds. One arena. Place your bets.",
    }

    # v1.51.0 [2026-03-22] — Migrated to FlaskScene
    def __init__(self, host: str = "0.0.0.0", port: int = ARENA_PORT) -> None:
        """Initialise the Arena scene.

        Args:
            host: Network interface to bind to.
            port: HTTP port for the Flask app.
        """
        super().__init__(host=host, port=port)

        self.app.config["SECRET_KEY"] = "colosseum_dark_renaissance_2026"

        # Scene-specific extra routes (FlaskScene registers health, hud, announcer, inventory, tts)
        self.register_bench_route(self.app, self.socketio)

        # Mount control overlay
        try:
            from engine.overlay import mount_overlay
            mount_overlay(self.app, self.socketio)
        except Exception as _exc:
            logger.debug("Arena: overlay mount skipped: %s", _exc)

        # ── Arena engine (lazy-loaded) ────────────────────────────────
        self._arena_engine: Optional[Any] = None

        # ── Auto-play tracking ───────────────────────────────────────
        self._auto_play_threads: Dict[str, threading.Thread] = {}
        self._auto_play_stop: Dict[str, threading.Event] = {}

        # ── Wire routes and Socket.IO ─────────────────────────────────
        self._setup_routes()
        self._setup_socketio()

    # ══════════════════════════════════════════════════════════════════
    #  ENGINE ACCESS
    # ══════════════════════════════════════════════════════════════════

    @property
    def _engine(self):
        """Lazy-load ArenaEngine to avoid import-time failures.

        Returns:
            Singleton ArenaEngine instance.
        """
        if self._arena_engine is None:
            from engine.arena.arena_engine import ArenaEngine
            self._arena_engine = ArenaEngine()
        return self._arena_engine

    # ══════════════════════════════════════════════════════════════════
    #  FLASK ROUTES
    # ══════════════════════════════════════════════════════════════════

    def _setup_routes(self) -> None:
        """Register all Flask HTTP routes on self.app."""
        app = self.app

        @app.route("/")
        def index():
            return render_template("arena.html", **self.inject_navbar_context())

        @app.route("/api/fighters")
        def fighters():
            """List available fighter profiles cached in the engine."""
            try:
                profiles = list(self._engine._fighter_profiles.values())
                return jsonify({
                    "fighters": [f.to_dict() for f in profiles],
                    "defaults": ["shadow", "blaze"],
                })
            except Exception as exc:
                logger.warning("[%s] /api/fighters error (operation=api): %s", SCENE_ID, exc)
                return jsonify({"fighters": [], "defaults": ["shadow", "blaze"]})

        @app.route("/api/match/<match_id>")
        def match_state(match_id: str):
            """Return current state of a match by ID.

            Args:
                match_id: UUID of the match.
            """
            try:
                match = self._engine._matches.get(match_id)
                if not match:
                    return jsonify({"error": f"Match {match_id!r} not found"}), 404
                return jsonify({"match": match.to_dict()})
            except Exception as exc:
                logger.warning("[%s] /api/match error (operation=api, match=%s): %s", SCENE_ID, match_id, exc)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/leaderboard")
        def leaderboard():
            """Return fighter career win/loss leaderboard."""
            try:
                profiles = list(self._engine._fighter_profiles.values())
                board = sorted(
                    [
                        {
                            "id": f.id,
                            "name": f.name,
                            "wins": f.wins,
                            "losses": f.losses,
                            "draws": f.draws,
                        }
                        for f in profiles
                    ],
                    key=lambda x: x["wins"],
                    reverse=True,
                )
                return jsonify({"leaderboard": board})
            except Exception as exc:
                logger.warning("[%s] /api/leaderboard error (operation=api): %s", SCENE_ID, exc)
                return jsonify({"leaderboard": [], "error": str(exc)})

        @app.route("/api/framework-status")
        def framework_status():
            """Expose MCP framework status for introspection."""
            try:
                fw = get_framework()
                return jsonify({
                    "framework": fw.get_status(),
                    "scene": SCENE_ID,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

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
                logger.warning("[%s] Economy API error (operation=economy): %s", SCENE_ID, exc)
                return jsonify({"error": str(exc)}), 500

    # ══════════════════════════════════════════════════════════════════
    #  SOCKET.IO HANDLERS
    # ══════════════════════════════════════════════════════════════════

    def _setup_socketio(self) -> None:
        """Register all Socket.IO event handlers on self.socketio."""
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            emit("arena_welcome", {
                "message": "Welcome to THE COLOSSEUM",
                "status": "ready",
            })

        # ── create_match ─────────────────────────────────────────────

        @sio.on("create_match")
        def on_create_match(data: dict):
            """Create a new match between two fighters.

            Args:
                data: Dict with keys ``fighter_a`` (str), ``fighter_b`` (str),
                    and optional ``auto_play`` (bool).
            """
            fighter_a = str(data.get("fighter_a", "shadow"))
            fighter_b = str(data.get("fighter_b", "blaze"))
            try:
                match = self._engine.create_match(fighter_a, fighter_b)
                emit("match_created", {"match": match.to_dict()}, broadcast=True)
                logger.info(
                    "[%s] Match created (operation=match_create, match=%s, fighters=%s_vs_%s)",
                    SCENE_ID, match.id, fighter_a, fighter_b,
                )
                if data.get("auto_play"):
                    self._start_auto_play(match.id)
            except Exception as exc:
                logger.warning("[%s] create_match failed (operation=match_create): %s", SCENE_ID, exc)
                emit("arena_error", {"error": str(exc)})

        # ── play_round ───────────────────────────────────────────────

        @sio.on("play_round")
        def on_play_round(data: dict):
            """Play one round of an in-progress match.

            Emits ``round_result`` with fighter states and reasoning.
            Emits ``match_complete`` if the match ends.

            Args:
                data: Dict with ``match_id`` (str).
            """
            match_id = str(data.get("match_id", ""))
            try:
                outcome = self._engine.play_round(match_id)
                match = self._engine._matches[match_id]

                payload = {
                    "round_outcome": outcome.to_dict(),
                    "fighter_a": match.fighter_a.to_dict(),
                    "fighter_b": match.fighter_b.to_dict(),
                }
                emit("round_result", payload, broadcast=True)

                # Record bench metrics from fighter response times
                ms_a = match.fighter_a.stats.get("last_response_ms", 0)
                ms_b = match.fighter_b.stats.get("last_response_ms", 0)
                self.record_bench(response_ms=max(ms_a, ms_b))

                # Check match-over
                from engine.arena.arena_engine import MatchStatus
                if match.status == MatchStatus.COMPLETE:
                    try:
                        bets_resolved = self._engine.resolve_bets(match_id)
                    except Exception:
                        bets_resolved = []
                    emit("match_complete", {
                        "match": match.to_dict(),
                        "winner": match.winner,
                        "bets_resolved": bets_resolved,
                    }, broadcast=True)
                    self._stop_auto_play(match_id)

            except Exception as exc:
                logger.warning("[%s] play_round failed (operation=play_round, match=%s): %s", SCENE_ID, match_id, exc)
                emit("arena_error", {"error": str(exc)})

        # ── place_bet ────────────────────────────────────────────────

        @sio.on("place_bet")
        def on_place_bet(data: dict):
            """Place a bet on a match outcome.

            Args:
                data: Dict with ``match_id``, ``bet_type``, ``target``,
                    ``amount`` (int).
            """
            match_id = str(data.get("match_id", ""))
            bet_type = str(data.get("bet_type", "match_winner"))
            target = str(data.get("target", "fighter_a"))
            amount = int(data.get("amount", 100))
            try:
                bet = self._engine.place_bet(match_id, bet_type, target, amount)
                balance: Optional[float] = None
                try:
                    from engine.economy.economy import get_economy_manager
                    balance = get_economy_manager().get_balance("player")
                except Exception:
                    pass
                emit("bet_placed", {"bet": bet.to_dict(), "balance": balance})
            except Exception as exc:
                logger.warning("[%s] place_bet failed (operation=bet, match=%s): %s", SCENE_ID, match_id, exc)
                emit("arena_error", {"error": str(exc)})

        # ── get_match ────────────────────────────────────────────────

        @sio.on("get_match")
        def on_get_match(data: dict):
            """Emit the current serialised state of a match.

            Args:
                data: Dict with ``match_id`` (str).
            """
            match_id = str(data.get("match_id", ""))
            match = self._engine._matches.get(match_id)
            if match:
                emit("match_state", {"match": match.to_dict()})
            else:
                emit("arena_error", {"error": f"Match {match_id!r} not found"})

        # ── get_fighters ─────────────────────────────────────────────

        @sio.on("get_fighters")
        def on_get_fighters():
            """Emit available fighter profiles."""
            try:
                profiles = list(self._engine._fighter_profiles.values())
                emit("fighters_list", {"fighters": [f.to_dict() for f in profiles]})
            except Exception as exc:
                emit("fighters_list", {"fighters": [], "error": str(exc)})

        # ── spectate ─────────────────────────────────────────────────

        @sio.on("spectate")
        def on_spectate(data: dict):
            """Join the spectator room for a match and receive its state.

            Args:
                data: Dict with ``match_id`` (str).
            """
            match_id = str(data.get("match_id", ""))
            join_room(f"spectate_{match_id}")
            match = self._engine._matches.get(match_id)
            if match:
                emit("match_state", {"match": match.to_dict()})
            else:
                emit("arena_error", {"error": f"Match {match_id!r} not found"})

    # ══════════════════════════════════════════════════════════════════
    #  AUTO-PLAY
    # ══════════════════════════════════════════════════════════════════

    def _start_auto_play(self, match_id: str) -> None:
        """Launch a daemon thread to auto-play rounds every 5 seconds.

        Args:
            match_id: ID of the match to auto-play.
        """
        if match_id in self._auto_play_threads:
            return

        stop_event = threading.Event()
        self._auto_play_stop[match_id] = stop_event

        def _auto_loop() -> None:
            while not stop_event.is_set():
                time.sleep(5)
                if stop_event.is_set():
                    break
                try:
                    from engine.arena.arena_engine import MatchStatus
                    match = self._engine._matches.get(match_id)
                    if not match or match.status != MatchStatus.IN_PROGRESS:
                        break
                    outcome = self._engine.play_round(match_id)
                    payload = {
                        "round_outcome": outcome.to_dict(),
                        "fighter_a": match.fighter_a.to_dict(),
                        "fighter_b": match.fighter_b.to_dict(),
                    }
                    self.socketio.emit("round_result", payload)
                    if match.status == MatchStatus.COMPLETE:
                        try:
                            bets_resolved = self._engine.resolve_bets(match_id)
                        except Exception:
                            bets_resolved = []
                        self.socketio.emit("match_complete", {
                            "match": match.to_dict(),
                            "winner": match.winner,
                            "bets_resolved": bets_resolved,
                        })
                        break
                except Exception as exc:
                    logger.warning("[%s] Auto-play error (operation=auto_play, match=%s): %s", SCENE_ID, match_id, exc)
                    break

        t = threading.Thread(
            target=_auto_loop,
            name=f"arena_auto_{match_id[:8]}",
            daemon=True,
        )
        self._auto_play_threads[match_id] = t
        t.start()
        logger.info("[%s] Auto-play started (operation=auto_play, match=%s)", SCENE_ID, match_id)

    def _stop_auto_play(self, match_id: str) -> None:
        """Signal the auto-play thread for a match to stop.

        Args:
            match_id: ID of the match.
        """
        stop_event = self._auto_play_stop.pop(match_id, None)
        if stop_event:
            stop_event.set()
        self._auto_play_threads.pop(match_id, None)

    # ══════════════════════════════════════════════════════════════════
    #  BASE SCENE INTERFACE
    # ══════════════════════════════════════════════════════════════════

    def get_plugin_info(self) -> Dict[str, Any]:
        """Return scene metadata for the admin panel and launcher.

        Returns:
            Plugin info dict conforming to BaseScene contract.
        """
        return {
            "name":        "THE COLOSSEUM",
            "description": "Two AI fighters. Tactical card game. Real-time reasoning.",
            "version":     "0.68",
            "author":      "CosySim",
            "port":        ARENA_PORT,
            "tags":        ["arena", "combat", "card-game", "betting", "ai-vs-ai"],
            "skill_packs": ["arena"],
            "routes": [
                {"path": "/",                    "methods": ["GET"],  "description": "Arena UI"},
                {"path": "/api/fighters",        "methods": ["GET"],  "description": "Fighter list"},
                {"path": "/api/match/<match_id>","methods": ["GET"],  "description": "Match state"},
                {"path": "/api/leaderboard",     "methods": ["GET"],  "description": "Leaderboard"},
                {"path": "/api/health",          "methods": ["GET"],  "description": "Health check"},
                {"path": "/api/bench/metrics",   "methods": ["GET"],  "description": "Bench HUD"},
            ],
        }

    # v1.51.0 [2026-03-22] — Lifecycle delegated to FlaskScene

    def on_before_serve(self) -> None:
        """Hook: emit scene_started event before serving."""
        try:
            get_framework().emit_event(
                "scene_started",
                {"scene_id": SCENE_ID, "port": ARENA_PORT},
                source=SCENE_ID,
            )
        except Exception:
            pass

    def on_shutdown(self) -> None:
        """Hook: stop all auto-play threads during shutdown."""
        for match_id in list(self._auto_play_threads.keys()):
            self._stop_auto_play(match_id)


__all__ = ["ArenaScene"]
