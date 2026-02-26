"""Games Arcade — AI-powered mini-game scene with GameMaster narration.

Port 5567.  Flask + SocketIO.

Features an AI GameMaster who narrates mysteries, reacts to player choices,
and hosts Truth-or-Dare with personality. Wraps MysteryGame and TruthOrDareGame
in a full BaseScene with Socket.IO events, MCP state, and score persistence.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

from engine.scenes.base_scene import BaseScene
from engine.scenes.nexus_mixin import NexusSceneMixin

log = logging.getLogger(__name__)

SCENE_ID = "games"
DEFAULT_PORT = 5567
GAMEMASTER_ID = "gamemaster"


class GamesScene(BaseScene, NexusSceneMixin):
    """Games Arcade with AI GameMaster, Socket.IO events, and score tracking."""

    SCENE_METADATA = {
        "name": "games",
        "title": "Games Arcade",
        "port": 5567,
        "type": "game",
        "description": (
            "AI-powered mini-game collection: Mystery Investigation with "
            "GameMaster narration and Truth-or-Dare with dice rolls and scoring."
        ),
        "genre": "minigames",
        "max_characters": 2,
        "features": [
            "mystery_investigation",
            "truth_or_dare",
            "ai_gamemaster",
            "score_persistence",
            "socket_io",
            "mcp_skills",
        ],
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        super().__init__(scene_name=SCENE_ID, host=host, port=port)

        scene_dir = os.path.dirname(os.path.abspath(__file__))
        self.app = Flask(
            __name__,
            template_folder=os.path.join(scene_dir, "templates"),
            static_folder=os.path.join(scene_dir, "static"),
        )
        self.socketio = SocketIO(self.app, cors_allowed_origins="*",
                                 async_mode="threading")

        self.mystery_games: Dict[str, Any] = {}
        self.tod_games: Dict[str, Any] = {}
        self._fw: Optional[Any] = None

        self._register_routes()
        self._setup_socketio()
        self._wire_mcp()
        self._register_gamemaster()

        self.nexus_init("games")

        log.info("GamesScene created on port %d", port)

    # ── MCP Integration ──────────────────────────────────────────────

    def _wire_mcp(self) -> None:
        """Wire scene into MCP framework with state node."""
        try:
            from engine.mcp.framework import get_framework
            self._fw = get_framework()
            self._scene_node = self._fw.get_scene(SCENE_ID)
            self._scene_node.update_state({
                "scores": {},
                "games_played": 0,
                "mysteries_solved": 0,
                "tod_rounds": 0,
            })
            log.info("GamesScene MCP wired with state tracking")
        except Exception as exc:
            log.warning("MCP wiring skipped: %s", exc)
            self._scene_node = None

    def _register_gamemaster(self) -> None:
        """Register the AI GameMaster character."""
        try:
            from engine.mcp.character_registry import (
                get_character_registry,
                apply_default_skills,
            )
            reg = get_character_registry()
            if not reg.exists(GAMEMASTER_ID):
                reg.register(
                    GAMEMASTER_ID,
                    name="The GameMaster",
                    age=0,
                    appearance={
                        "description": "A disembodied voice with a theatrical flair",
                        "style": "enigmatic narrator",
                    },
                    personality={
                        "warmth": 0.6,
                        "assertiveness": 0.8,
                        "wit": 0.9,
                        "vulnerability": 0.0,
                        "openness": 0.7,
                        "dominance": 0.7,
                    },
                    backstory=(
                        "The GameMaster is the omniscient narrator of the Games Arcade. "
                        "They have a flair for the dramatic, relish in building suspense, "
                        "and delight in watching players puzzle through mysteries. "
                        "They give hints wrapped in riddles and celebrate victories with gusto."
                    ),
                    voice_style="theatrical, suspenseful, dry wit. Speaks like a dramatic narrator.",
                    scene_roles=[SCENE_ID],
                )
                apply_default_skills(GAMEMASTER_ID)
                log.info("GameMaster character registered")

            if self._fw:
                self._fw.get_character(GAMEMASTER_ID).enter_scene(SCENE_ID)
        except Exception as exc:
            log.warning("GameMaster registration skipped: %s", exc)

    def _get_gamemaster_reply(self, prompt: str) -> str:
        """Get an AI response from the GameMaster character."""
        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            from engine.agents.virtual_agent import InferenceRequest

            mgr = get_virtual_agent_manager()
            system = (
                "You are The GameMaster — the theatrical narrator of the Games Arcade. "
                "You narrate mysteries with suspense, give atmospheric clue descriptions, "
                "react dramatically to accusations, and host Truth-or-Dare with playful energy. "
                "Keep responses to 2-3 sentences. Use [MOOD:emotion] tags. "
                "Be engaging, witty, and slightly mysterious."
            )

            governance = self._get_governance_context(GAMEMASTER_ID)
            if governance:
                system = f"{system}\n\n{governance}"

            req = InferenceRequest(
                agent_id=GAMEMASTER_ID,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                max_output_tokens=150,
                conversation_id=f"games_{GAMEMASTER_ID}",
                store=False,
                metadata={"scene": SCENE_ID, "role": "game_master"},
            )
            proc = mgr.infer_processed(req)
            return (proc.clean_text or "").strip()
        except Exception as exc:
            log.debug("GameMaster AI unavailable: %s", exc)
            return ""

    def _get_governance_context(self, character_id: str) -> str:
        """Build governance context for the character."""
        try:
            from engine.mcp import get_governor
            gov = get_governor()
            return gov.build_governance_context(character_id, SCENE_ID)
        except Exception:
            return ""

    # ── Score Tracking ───────────────────────────────────────────────

    def _update_score(self, player: str, game: str, won: bool, points: int = 0) -> Dict[str, Any]:
        """Update persistent score for a player."""
        scores = {}
        if self._scene_node:
            scores = self._scene_node.get_state().get("scores", {})

        if player not in scores:
            scores[player] = {
                "mystery_wins": 0, "mystery_losses": 0,
                "tod_score": 0, "tod_rounds": 0,
                "total_games": 0,
            }

        scores[player]["total_games"] += 1
        if game == "mystery":
            if won:
                scores[player]["mystery_wins"] += 1
            else:
                scores[player]["mystery_losses"] += 1
        elif game == "tod":
            scores[player]["tod_score"] += points
            scores[player]["tod_rounds"] += 1

        if self._scene_node:
            state = self._scene_node.get_state()
            state["scores"] = scores
            state["games_played"] = state.get("games_played", 0) + 1
            if game == "mystery" and won:
                state["mysteries_solved"] = state.get("mysteries_solved", 0) + 1
            self._scene_node.update_state(state)

        return scores[player]

    # ── Routes ───────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        app = self.app

        from .mystery_investigation import mystery_bp
        from .truth_or_dare import truth_or_dare_bp
        app.register_blueprint(mystery_bp, url_prefix="/games/mystery")
        app.register_blueprint(truth_or_dare_bp, url_prefix="/games/truth-or-dare")

        @app.route("/")
        def index():
            return render_template("games.html")

        @app.route("/api/health")
        def health():
            return jsonify(self.get_health())

        @app.route("/api/status")
        def status():
            scores = {}
            if self._scene_node:
                state = self._scene_node.get_state()
                scores = state.get("scores", {})
            return jsonify({
                "scene": SCENE_ID,
                "mystery_active": len(self.mystery_games),
                "tod_active": len(self.tod_games),
                "scores": scores,
                "games_played": (
                    self._scene_node.get_state().get("games_played", 0)
                    if self._scene_node else 0
                ),
            })

        @app.route("/api/scores")
        def get_scores():
            """Get all player scores."""
            scores = {}
            if self._scene_node:
                scores = self._scene_node.get_state().get("scores", {})
            return jsonify(scores)

        @app.route("/api/chat", methods=["POST"])
        def chat_with_gamemaster():
            """Chat with the AI GameMaster."""
            body = request.get_json(silent=True) or {}
            message = (body.get("message") or "").strip()
            if not message:
                return jsonify({"error": "No message provided"}), 400
            reply = self._get_gamemaster_reply(message) or "The GameMaster ponders silently..."
            return jsonify({"reply": reply, "character": "The GameMaster"})

        @app.route("/api/mystery/narrate", methods=["POST"])
        def narrate_clue():
            """Get GameMaster narration for a clue."""
            body = request.get_json(silent=True) or {}
            clue = body.get("clue", "")
            case_title = body.get("case_title", "the mystery")
            clue_number = body.get("clue_number", 0)
            prompt = (
                f"You're narrating '{case_title}'. The player just found clue #{clue_number}: "
                f'"{clue}". Describe the moment dramatically — what does the player notice? '
                f"Build suspense. Hint at what it might mean without giving away the answer."
            )
            narration = self._get_gamemaster_reply(prompt)
            return jsonify({"narration": narration or clue})

        @app.route("/api/mystery/react", methods=["POST"])
        def react_to_accusation():
            """Get GameMaster reaction to an accusation."""
            body = request.get_json(silent=True) or {}
            correct = body.get("correct", False)
            suspect = body.get("suspect", "unknown")
            real_culprit = body.get("real_culprit", "unknown")
            player = body.get("player", "player")

            if correct:
                prompt = (
                    f'The player accused "{suspect}" — and they are CORRECT! '
                    f"Celebrate their detective skills with dramatic flair. "
                    f"They solved the case!"
                )
                self._update_score(player, "mystery", True)
            else:
                prompt = (
                    f'The player accused "{suspect}" but the real culprit was '
                    f'"{real_culprit}". React with dramatic sympathy. '
                    f"They were so close! What did they miss?"
                )
                self._update_score(player, "mystery", False)

            reaction = self._get_gamemaster_reply(prompt)
            return jsonify({"reaction": reaction or ("Brilliant!" if correct else "Not quite...")})

        self.register_health_route(app)
        try:
            self.mount_overlay(app)
            self.mount_skills_server(app)
        except Exception:
            pass

    # ── Socket.IO Events ─────────────────────────────────────────────

    def _setup_socketio(self) -> None:
        """Wire Socket.IO event handlers for real-time gameplay."""
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            log.debug("Games Arcade client connected")
            scores = {}
            if self._scene_node:
                scores = self._scene_node.get_state().get("scores", {})
            emit("game_update", {
                "type": "connected",
                "scores": scores,
                "games_available": ["mystery", "truth_or_dare"],
            })

        @sio.on("disconnect")
        def on_disconnect():
            log.debug("Games Arcade client disconnected")

        @sio.on("chat_message")
        def on_chat(data: Dict[str, Any]) -> None:
            """Handle chat with GameMaster via Socket.IO."""
            message = (data.get("message") or "").strip()
            if not message:
                return
            reply = self._get_gamemaster_reply(message)
            emit("chat_reply", {
                "character": "The GameMaster",
                "message": reply or "The GameMaster strokes their chin thoughtfully...",
                "timestamp": time.time(),
            })

        @sio.on("mystery_start")
        def on_mystery_start(data: Dict[str, Any]) -> None:
            """Start a mystery game via Socket.IO."""
            from .mystery_investigation import MysteryGame
            player = data.get("player", "player")
            case_index = data.get("case_index")
            game = MysteryGame(character_id=player)
            self.mystery_games[player] = game
            result = game.start(case_index)

            intro_prompt = (
                f"A new mystery begins: '{result['case_title']}'. "
                f"Setting: {result['setting']}. "
                f"Set the scene dramatically. Welcome the detective."
            )
            narration = self._get_gamemaster_reply(intro_prompt)

            emit("mystery_started", {
                "case_title": result["case_title"],
                "setting": result["setting"],
                "narration": narration or f"Welcome to '{result['case_title']}'...",
            })

        @sio.on("mystery_clue")
        def on_mystery_clue(data: Dict[str, Any]) -> None:
            """Request next clue via Socket.IO."""
            player = data.get("player", "player")
            game = self.mystery_games.get(player)
            if not game:
                emit("error", {"message": "No active mystery. Start one first."})
                return

            result = game.next_clue()
            clue = result.get("clue", "")
            clue_num = result.get("clues_found", 0)

            narration = ""
            if clue:
                prompt = (
                    f"The detective found clue #{clue_num}: \"{clue}\". "
                    f"Describe the discovery moment with suspense."
                )
                narration = self._get_gamemaster_reply(prompt)

            emit("clue_revealed", {
                "clue": clue,
                "clue_number": clue_num,
                "total": 5,
                "narration": narration or clue,
                "all_found": clue_num >= 5,
            })

        @sio.on("mystery_accuse")
        def on_mystery_accuse(data: Dict[str, Any]) -> None:
            """Make an accusation via Socket.IO."""
            player = data.get("player", "player")
            suspect = (data.get("suspect") or "").strip()
            game = self.mystery_games.get(player)
            if not game:
                emit("error", {"message": "No active mystery."})
                return

            result = game.accuse(suspect)
            correct = result.get("correct", False)
            self._update_score(player, "mystery", correct)

            if correct:
                prompt = f"CORRECT! The culprit was {result.get('real_culprit')}! Celebrate!"
            else:
                prompt = (
                    f"Wrong! They said '{suspect}' but it was "
                    f"{result.get('real_culprit')}. React with dramatic sympathy."
                )
            reaction = self._get_gamemaster_reply(prompt)

            emit("accusation_result", {
                "correct": correct,
                "suspect": suspect,
                "real_culprit": result.get("real_culprit"),
                "reaction": reaction or ("Case solved!" if correct else "Not quite..."),
            })
            if self._fw:
                self._fw.emit_event("mystery_completed", {
                    "player": player, "correct": correct,
                    "suspect": suspect,
                }, source=SCENE_ID)

        @sio.on("tod_start")
        def on_tod_start(data: Dict[str, Any]) -> None:
            """Start Truth-or-Dare via Socket.IO."""
            from .truth_or_dare import TruthOrDareGame
            player = data.get("player", "player")
            game = TruthOrDareGame(character_id=player)
            self.tod_games[player] = game
            game.start()

            intro = self._get_gamemaster_reply(
                "A new game of Truth or Dare begins! Welcome the player with excitement."
            )
            emit("tod_started", {
                "message": intro or "Truth or Dare begins! Roll the dice!",
            })

        @sio.on("tod_roll")
        def on_tod_roll(data: Dict[str, Any]) -> None:
            """Roll dice in Truth-or-Dare."""
            player = data.get("player", "player")
            game = self.tod_games.get(player)
            if not game:
                emit("error", {"message": "No active Truth-or-Dare game."})
                return
            try:
                result = game.roll()
            except RuntimeError as e:
                emit("error", {"message": str(e)})
                return

            kind = result.get("type", "truth")
            prompt_text = result.get("prompt", "")
            narration = self._get_gamemaster_reply(
                f"The dice show {result.get('roll')}! It's a {kind.upper()}: "
                f'"{prompt_text}". Present this dramatically.'
            )
            emit("tod_prompt", {
                "roll": result.get("roll"),
                "type": kind,
                "prompt": prompt_text,
                "narration": narration or prompt_text,
            })

        @sio.on("tod_answer")
        def on_tod_answer(data: Dict[str, Any]) -> None:
            """Submit answer for Truth-or-Dare."""
            player = data.get("player", "player")
            response = data.get("response", "")
            completed = data.get("completed", True)
            game = self.tod_games.get(player)
            if not game:
                emit("error", {"message": "No active game."})
                return
            result = game.answer(completed=completed, response=response)
            score = result.get("score", 0)
            self._update_score(player, "tod", False, points=score)

            if score >= 5:
                reaction = self._get_gamemaster_reply(
                    f"The player scored {score} points and WINS! Celebrate!"
                )
                emit("tod_complete", {
                    "score": score,
                    "reaction": reaction or f"You win with {score} points!",
                })
            else:
                emit("tod_scored", {
                    "score": score,
                    "completed": completed,
                })

    # ── BaseScene Interface ──────────────────────────────────────────

    def start(self) -> None:
        log.info("Starting GamesScene on %s:%d", self.host, self.port)
        self.socketio.run(self.app, host=self.host, port=self.port,
                          allow_unsafe_werkzeug=True)

    def stop(self) -> None:
        self.nexus_flush()
        log.info("Stopping GamesScene")

    def get_health(self) -> Dict[str, Any]:
        return {
            "scene": SCENE_ID,
            "status": "running",
            "port": self.port,
            "gamemaster": GAMEMASTER_ID,
        }

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name": "games",
            "description": self.SCENE_METADATA["description"],
            "version": "0.56b",
            "author": "CosySim",
            "port": self.port,
            "tags": ["games", "mystery", "truth_or_dare", "ai_gamemaster"],
            "skill_packs": ["games"],
            "routes": [
                "/", "/api/health", "/api/status", "/api/scores",
                "/api/chat", "/api/mystery/narrate", "/api/mystery/react",
                "/games/mystery/*", "/games/truth-or-dare/*",
            ],
        }


def create_app(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> GamesScene:
    """Factory for launcher integration."""
    return GamesScene(host=host, port=port)


if __name__ == "__main__":
    scene = GamesScene(host="0.0.0.0", port=DEFAULT_PORT)
    scene.start()
