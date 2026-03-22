"""THE COLOSSEUM — Arena Scene for CosySim v0.68 'Dark Renaissance'.

Two AI fighters battle in a tactical card game while the player watches
and places bets.  Showcases real-time agent reasoning via ArenaEngine.

Port  : 5561
Accent: #dc2626 (blood red)

Version: v1.51.1 [2026-03-22]

Change Log:
    v1.51.1 [2026-03-22] — Named fighter roster (8 fighters) + tournament bracket system
    v1.51.0 [2026-03-22] — Migrated to FlaskScene (unified base class)
    v1.49.3 [2026-03-22] — Structured logging context (SCENE_ID prefix + operation tags)
    v0.68   [2026-03-20] — Dark Renaissance arena scene
"""
from __future__ import annotations

import copy
import json
import logging
import random
import threading
import time
import uuid
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
#  NAMED FIGHTER ROSTER
# ══════════════════════════════════════════════════════════════════════

# v1.51.1 [2026-03-22] — Named fighter roster with unique styles and deck biases
ARENA_FIGHTERS: Dict[str, Dict[str, Any]] = {
    "shadow": {
        "name": "Shadow", "title": "The Silent Blade", "style": "assassin", "hp": 90,
        "backstory": "Nobody has ever seen Shadow's face. They move like smoke.",
        "deck_bias": {"attack": 40, "special": 30, "steal": 20, "defend": 10},
    },
    "blaze": {
        "name": "Blaze", "title": "The Inferno", "style": "berserker", "hp": 120,
        "backstory": "Once set an entire district on fire to win a bet. The bet was 50 credits.",
        "deck_bias": {"attack": 50, "defend": 30, "special": 15, "steal": 5},
    },
    "iron_maiden": {
        "name": "Iron Maiden", "title": "The Unbreakable", "style": "tank", "hp": 150,
        "backstory": "Former SynthSec riot shield operator. Has never been knocked down.",
        "deck_bias": {"defend": 45, "attack": 30, "special": 20, "steal": 5},
    },
    "viper": {
        "name": "Viper", "title": "The Venomous", "style": "trickster", "hp": 80,
        "backstory": "Wins by making opponents defeat themselves. Has a collection of their tears.",
        "deck_bias": {"steal": 35, "special": 30, "attack": 25, "defend": 10},
    },
    "titan": {
        "name": "Titan", "title": "The Mountain", "style": "heavy", "hp": 180,
        "backstory": "Genetically enhanced. Takes hits like they're compliments. Slow but devastating.",
        "deck_bias": {"defend": 40, "attack": 40, "special": 15, "steal": 5},
    },
    "phoenix": {
        "name": "Phoenix", "title": "The Undying", "style": "comeback", "hp": 100,
        "backstory": "Lost 47 fights in a row, then won 48 straight. Lives for the impossible.",
        "deck_bias": {"special": 40, "defend": 25, "attack": 25, "steal": 10},
    },
    "ghost_hand": {
        "name": "Ghost Hand", "title": "The Pickpocket", "style": "technical", "hp": 95,
        "backstory": "Can steal the fillings from your teeth mid-fight. Literally.",
        "deck_bias": {"special": 35, "steal": 30, "attack": 20, "defend": 15},
    },
    "crimson": {
        "name": "Crimson", "title": "The Balanced", "style": "all_rounder", "hp": 110,
        "backstory": "No flashy style, no weakness. The fighter other fighters fear most.",
        "deck_bias": {"attack": 30, "defend": 25, "special": 25, "steal": 20},
    },
}


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

        # v1.51.1 [2026-03-22] — Tournament bracket system
        self._tournament_state: Dict[str, Any] = {
            "active": False,
            "bracket": [],
            "round": 0,
            "champion": None,
            "tournament_id": None,
            "match_log": [],
        }
        self._tournament_thread: Optional[threading.Thread] = None
        self._tournament_stop: Optional[threading.Event] = None

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

        # ── Tournament Bracket Routes ──────────────────────────────────
        # v1.51.1 [2026-03-22] — Tournament bracket system
        # CONNECTS: ARENA_FIGHTERS, ArenaEngine, tournament_update SocketIO
        # CALLED BY: Frontend tournament UI
        # EMITS: tournament_update SocketIO event

        @app.route("/api/fighters/roster")
        def fighters_roster():
            """Return the named fighter roster with backstories and deck biases."""
            return jsonify({"roster": ARENA_FIGHTERS})

        @app.route("/api/tournament/create", methods=["POST"])
        def tournament_create():
            """Create a new 8-fighter tournament bracket.

            Accepts optional JSON body:
                fighters: List[str] — fighter IDs to include (defaults to all 8).

            Shuffles entrants and pairs them for round 1 (quarterfinals).
            """
            if self._tournament_state["active"]:
                return jsonify({"error": "Tournament already active"}), 400

            data = request.get_json(silent=True) or {}
            fighter_ids = data.get("fighters", list(ARENA_FIGHTERS.keys()))

            # Validate all fighter IDs exist
            invalid = [f for f in fighter_ids if f not in ARENA_FIGHTERS]
            if invalid:
                return jsonify({"error": f"Unknown fighters: {invalid}"}), 400
            if len(fighter_ids) < 4:
                return jsonify({"error": "Need at least 4 fighters for a tournament"}), 400

            # Pad to even power of 2 if needed (prefer 8, allow 4)
            if len(fighter_ids) > 8:
                fighter_ids = fighter_ids[:8]

            # Shuffle entrants for random seeding
            entrants = list(fighter_ids)
            random.shuffle(entrants)

            # Build bracket: list of rounds, each round is a list of matchups
            # Round 1 pairs: (0,1), (2,3), (4,5), (6,7) etc.
            round_1_matchups = []
            for i in range(0, len(entrants), 2):
                if i + 1 < len(entrants):
                    round_1_matchups.append({
                        "match_id": uuid.uuid4().hex[:8],
                        "fighter_a": entrants[i],
                        "fighter_b": entrants[i + 1],
                        "winner": None,
                        "played": False,
                    })
                else:
                    # Odd fighter gets a bye
                    round_1_matchups.append({
                        "match_id": uuid.uuid4().hex[:8],
                        "fighter_a": entrants[i],
                        "fighter_b": None,
                        "winner": entrants[i],
                        "played": True,
                    })

            tournament_id = uuid.uuid4().hex[:8]
            self._tournament_state = {
                "active": True,
                "tournament_id": tournament_id,
                "bracket": [round_1_matchups],
                "round": 1,
                "champion": None,
                "match_log": [],
                "entrants": entrants,
            }

            logger.info(
                "[%s] Tournament created (operation=tournament_create, id=%s, fighters=%d)",
                SCENE_ID, tournament_id, len(entrants),
            )

            return jsonify({
                "success": True,
                "tournament_id": tournament_id,
                "round": 1,
                "bracket": self._tournament_state["bracket"],
                "entrants": [
                    {"id": fid, **ARENA_FIGHTERS[fid]}
                    for fid in entrants if fid in ARENA_FIGHTERS
                ],
            })

        @app.route("/api/tournament/state")
        def tournament_state():
            """Return current tournament bracket state."""
            if not self._tournament_state["active"] and not self._tournament_state["champion"]:
                return jsonify({"active": False, "message": "No tournament in progress"})

            # Enrich bracket with fighter details
            enriched_bracket = []
            for rnd in self._tournament_state["bracket"]:
                enriched_round = []
                for match in rnd:
                    enriched_match = dict(match)
                    if match["fighter_a"] and match["fighter_a"] in ARENA_FIGHTERS:
                        enriched_match["fighter_a_info"] = ARENA_FIGHTERS[match["fighter_a"]]
                    if match["fighter_b"] and match["fighter_b"] in ARENA_FIGHTERS:
                        enriched_match["fighter_b_info"] = ARENA_FIGHTERS[match["fighter_b"]]
                    if match["winner"] and match["winner"] in ARENA_FIGHTERS:
                        enriched_match["winner_info"] = ARENA_FIGHTERS[match["winner"]]
                    enriched_round.append(enriched_match)
                enriched_bracket.append(enriched_round)

            champion_info = None
            if self._tournament_state["champion"] and self._tournament_state["champion"] in ARENA_FIGHTERS:
                champion_info = ARENA_FIGHTERS[self._tournament_state["champion"]]

            return jsonify({
                "active": self._tournament_state["active"],
                "tournament_id": self._tournament_state.get("tournament_id"),
                "round": self._tournament_state["round"],
                "bracket": enriched_bracket,
                "champion": self._tournament_state["champion"],
                "champion_info": champion_info,
                "match_log": self._tournament_state["match_log"],
            })

        @app.route("/api/tournament/reset", methods=["POST"])
        def tournament_reset():
            """Reset the tournament, stopping any auto-play."""
            self._stop_tournament()
            self._tournament_state = {
                "active": False,
                "bracket": [],
                "round": 0,
                "champion": None,
                "tournament_id": None,
                "match_log": [],
            }
            logger.info("[%s] Tournament reset (operation=tournament_reset)", SCENE_ID)
            return jsonify({"success": True, "message": "Tournament reset"})

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

        # ── start_tournament ───────────────────────────────────────────
        # v1.51.1 [2026-03-22] — Tournament auto-play via SocketIO
        # CONNECTS: ARENA_FIGHTERS, _tournament_state, _simulate_tournament_match
        # CALLED BY: Frontend tournament start button
        # EMITS: tournament_update SocketIO event after each match

        @sio.on("start_tournament")
        def on_start_tournament(data: dict = None):
            """Begin auto-playing the tournament bracket (one match every 30s).

            If no tournament exists, creates one with all 8 fighters first.
            Emits ``tournament_update`` after each match resolves.

            Args:
                data: Optional dict with ``match_delay`` (int, seconds between matches).
            """
            data = data or {}
            match_delay = int(data.get("match_delay", 30))

            # Auto-create tournament if none is active
            if not self._tournament_state["active"]:
                entrants = list(ARENA_FIGHTERS.keys())
                random.shuffle(entrants)
                round_1_matchups = []
                for i in range(0, len(entrants), 2):
                    if i + 1 < len(entrants):
                        round_1_matchups.append({
                            "match_id": uuid.uuid4().hex[:8],
                            "fighter_a": entrants[i],
                            "fighter_b": entrants[i + 1],
                            "winner": None,
                            "played": False,
                        })
                tournament_id = uuid.uuid4().hex[:8]
                self._tournament_state = {
                    "active": True,
                    "tournament_id": tournament_id,
                    "bracket": [round_1_matchups],
                    "round": 1,
                    "champion": None,
                    "match_log": [],
                    "entrants": entrants,
                }

            self._start_tournament_auto_play(match_delay)
            emit("tournament_update", {
                "event": "tournament_started",
                "tournament_id": self._tournament_state.get("tournament_id"),
                "round": self._tournament_state["round"],
                "bracket": self._tournament_state["bracket"],
                "match_delay": match_delay,
            }, broadcast=True)

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
    #  TOURNAMENT BRACKET SYSTEM
    # ══════════════════════════════════════════════════════════════════

    # v1.51.1 [2026-03-22] — Tournament bracket: 8-fighter single-elimination
    # CONNECTS: ARENA_FIGHTERS, _tournament_state
    # CALLED BY: start_tournament SocketIO handler, /api/tournament/create
    # EMITS: tournament_update SocketIO event

    def _simulate_tournament_match(self, fighter_a_id: str, fighter_b_id: str) -> str:
        """Simulate a single tournament match between two named fighters.

        Uses deck bias weights to probabilistically determine the winner.
        Higher attack bias = more damage; higher defend bias = more mitigation.

        Args:
            fighter_a_id: ID of the first fighter in ARENA_FIGHTERS.
            fighter_b_id: ID of the second fighter in ARENA_FIGHTERS.

        Returns:
            The ID of the winning fighter.
        """
        fa = ARENA_FIGHTERS.get(fighter_a_id, {})
        fb = ARENA_FIGHTERS.get(fighter_b_id, {})

        hp_a = fa.get("hp", 100)
        hp_b = fb.get("hp", 100)
        bias_a = fa.get("deck_bias", {"attack": 25, "defend": 25, "special": 25, "steal": 25})
        bias_b = fb.get("deck_bias", {"attack": 25, "defend": 25, "special": 25, "steal": 25})

        # Simulate rounds until one fighter drops to 0 HP (max 20 rounds safety)
        for _ in range(20):
            # Fighter A's turn — draw from weighted deck
            a_action = random.choices(
                ["attack", "defend", "special", "steal"],
                weights=[bias_a.get("attack", 25), bias_a.get("defend", 25),
                         bias_a.get("special", 25), bias_a.get("steal", 25)],
                k=1,
            )[0]

            # Fighter B's turn
            b_action = random.choices(
                ["attack", "defend", "special", "steal"],
                weights=[bias_b.get("attack", 25), bias_b.get("defend", 25),
                         bias_b.get("special", 25), bias_b.get("steal", 25)],
                k=1,
            )[0]

            # Resolve A's action against B
            if a_action == "attack":
                dmg = random.randint(8, 18)
                if b_action == "defend":
                    dmg = max(1, dmg // 2)  # Halved by defense
                hp_b -= dmg
            elif a_action == "special":
                dmg = random.randint(12, 25)
                if b_action == "defend":
                    dmg = max(2, int(dmg * 0.6))  # Partially blocked
                hp_b -= dmg
            elif a_action == "steal":
                # Steal heals A slightly and damages B lightly
                steal_val = random.randint(3, 8)
                hp_b -= steal_val
                hp_a = min(fa.get("hp", 100), hp_a + steal_val)
            # defend = no damage dealt

            if hp_b <= 0:
                return fighter_a_id

            # Resolve B's action against A
            if b_action == "attack":
                dmg = random.randint(8, 18)
                if a_action == "defend":
                    dmg = max(1, dmg // 2)
                hp_a -= dmg
            elif b_action == "special":
                dmg = random.randint(12, 25)
                if a_action == "defend":
                    dmg = max(2, int(dmg * 0.6))
                hp_a -= dmg
            elif b_action == "steal":
                steal_val = random.randint(3, 8)
                hp_a -= steal_val
                hp_b = min(fb.get("hp", 100), hp_b + steal_val)

            if hp_a <= 0:
                return fighter_b_id

        # Tiebreaker: whoever has more HP remaining wins
        return fighter_a_id if hp_a >= hp_b else fighter_b_id

    def _advance_tournament_round(self) -> bool:
        """Play all unplayed matches in the current round and create the next round.

        Returns:
            True if the tournament is complete (champion crowned), False otherwise.
        """
        state = self._tournament_state
        if not state["active"]:
            return True

        current_round = state["bracket"][-1]

        # Play all unplayed matches in current round
        for match in current_round:
            if match["played"]:
                continue

            # Bye handling (one fighter is None)
            if match["fighter_b"] is None:
                match["winner"] = match["fighter_a"]
                match["played"] = True
                continue
            if match["fighter_a"] is None:
                match["winner"] = match["fighter_b"]
                match["played"] = True
                continue

            # Simulate the match
            winner = self._simulate_tournament_match(match["fighter_a"], match["fighter_b"])
            match["winner"] = winner
            match["played"] = True

            loser = match["fighter_b"] if winner == match["fighter_a"] else match["fighter_a"]
            winner_info = ARENA_FIGHTERS.get(winner, {})
            loser_info = ARENA_FIGHTERS.get(loser, {})

            state["match_log"].append({
                "round": state["round"],
                "winner": winner,
                "winner_name": winner_info.get("name", winner),
                "loser": loser,
                "loser_name": loser_info.get("name", loser),
                "match_id": match["match_id"],
            })

            logger.info(
                "[%s] Tournament match (operation=tournament_match, round=%d): %s defeated %s",
                SCENE_ID, state["round"],
                winner_info.get("name", winner),
                loser_info.get("name", loser),
            )

        # Collect winners from this round
        winners = [m["winner"] for m in current_round if m["winner"]]

        # If only 1 winner remains, crown champion
        if len(winners) <= 1:
            state["champion"] = winners[0] if winners else None
            state["active"] = False
            logger.info(
                "[%s] Tournament champion crowned (operation=tournament_complete): %s",
                SCENE_ID, ARENA_FIGHTERS.get(state["champion"], {}).get("name", state["champion"]),
            )
            return True

        # Build next round
        next_round_matchups = []
        for i in range(0, len(winners), 2):
            if i + 1 < len(winners):
                next_round_matchups.append({
                    "match_id": uuid.uuid4().hex[:8],
                    "fighter_a": winners[i],
                    "fighter_b": winners[i + 1],
                    "winner": None,
                    "played": False,
                })
            else:
                # Odd winner gets a bye to next round
                next_round_matchups.append({
                    "match_id": uuid.uuid4().hex[:8],
                    "fighter_a": winners[i],
                    "fighter_b": None,
                    "winner": winners[i],
                    "played": True,
                })

        state["bracket"].append(next_round_matchups)
        state["round"] += 1
        return False

    def _start_tournament_auto_play(self, match_delay: int = 30) -> None:
        """Launch a daemon thread to auto-play the tournament bracket.

        One match resolves every ``match_delay`` seconds. Emits ``tournament_update``
        after each match and ``tournament_complete`` when the champion is crowned.

        Args:
            match_delay: Seconds between each tournament match.
        """
        if self._tournament_thread and self._tournament_thread.is_alive():
            return

        stop_event = threading.Event()
        self._tournament_stop = stop_event

        def _tournament_loop() -> None:
            while not stop_event.is_set():
                state = self._tournament_state
                if not state["active"]:
                    break

                current_round = state["bracket"][-1]
                unplayed = [m for m in current_round if not m["played"]]

                if not unplayed:
                    # All matches in current round played — advance
                    complete = self._advance_tournament_round()
                    if complete:
                        champion_info = None
                        if state["champion"] and state["champion"] in ARENA_FIGHTERS:
                            champion_info = ARENA_FIGHTERS[state["champion"]]
                        self.socketio.emit("tournament_update", {
                            "event": "tournament_complete",
                            "champion": state["champion"],
                            "champion_info": champion_info,
                            "bracket": state["bracket"],
                            "match_log": state["match_log"],
                        })
                        break
                    continue

                # Play the next unplayed match
                match = unplayed[0]

                # Skip byes
                if match["fighter_b"] is None:
                    match["winner"] = match["fighter_a"]
                    match["played"] = True
                    continue

                # Simulate the match
                winner = self._simulate_tournament_match(match["fighter_a"], match["fighter_b"])
                match["winner"] = winner
                match["played"] = True

                loser = match["fighter_b"] if winner == match["fighter_a"] else match["fighter_a"]
                winner_info = ARENA_FIGHTERS.get(winner, {})
                loser_info = ARENA_FIGHTERS.get(loser, {})

                state["match_log"].append({
                    "round": state["round"],
                    "winner": winner,
                    "winner_name": winner_info.get("name", winner),
                    "loser": loser,
                    "loser_name": loser_info.get("name", loser),
                    "match_id": match["match_id"],
                })

                # Emit update for this match
                self.socketio.emit("tournament_update", {
                    "event": "match_result",
                    "round": state["round"],
                    "match": match,
                    "winner": winner,
                    "winner_info": winner_info,
                    "loser": loser,
                    "loser_info": loser_info,
                    "bracket": state["bracket"],
                    "remaining_matches": len(unplayed) - 1,
                })

                logger.info(
                    "[%s] Tournament auto-play (operation=tournament_auto, round=%d): "
                    "%s defeated %s",
                    SCENE_ID, state["round"],
                    winner_info.get("name", winner),
                    loser_info.get("name", loser),
                )

                # Wait before next match
                stop_event.wait(match_delay)

        self._tournament_thread = threading.Thread(
            target=_tournament_loop,
            name="arena_tournament",
            daemon=True,
        )
        self._tournament_thread.start()
        logger.info(
            "[%s] Tournament auto-play started (operation=tournament_start, delay=%ds)",
            SCENE_ID, match_delay,
        )

    def _stop_tournament(self) -> None:
        """Signal the tournament auto-play thread to stop."""
        if self._tournament_stop:
            self._tournament_stop.set()
        self._tournament_thread = None
        self._tournament_stop = None

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
                {"path": "/",                        "methods": ["GET"],  "description": "Arena UI"},
                {"path": "/api/fighters",            "methods": ["GET"],  "description": "Fighter list"},
                {"path": "/api/fighters/roster",     "methods": ["GET"],  "description": "Named fighter roster"},
                {"path": "/api/match/<match_id>",    "methods": ["GET"],  "description": "Match state"},
                {"path": "/api/leaderboard",         "methods": ["GET"],  "description": "Leaderboard"},
                {"path": "/api/tournament/create",   "methods": ["POST"], "description": "Create tournament"},
                {"path": "/api/tournament/state",    "methods": ["GET"],  "description": "Tournament state"},
                {"path": "/api/tournament/reset",    "methods": ["POST"], "description": "Reset tournament"},
                {"path": "/api/health",              "methods": ["GET"],  "description": "Health check"},
                {"path": "/api/bench/metrics",       "methods": ["GET"],  "description": "Bench HUD"},
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
        """Hook: stop all auto-play and tournament threads during shutdown."""
        for match_id in list(self._auto_play_threads.keys()):
            self._stop_auto_play(match_id)
        self._stop_tournament()


__all__ = ["ArenaScene", "ARENA_FIGHTERS"]
