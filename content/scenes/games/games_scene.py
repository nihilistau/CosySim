"""THE ARCADE — v0.68 Dark Renaissance. Violet-themed arcade with investigation
board, 3D dice, adult Truth-or-Dare, and AI GameMaster narration.

Port 5567.  Flask + SocketIO.

Features an AI GameMaster who narrates mysteries, reacts to player choices,
and hosts Truth-or-Dare with personality. Wraps MysteryGame and TruthOrDareGame
in a full FlaskScene with Socket.IO events, MCP state, score persistence,
investigation board integration, and a Nexus-backed leaderboard.

Version: v1.51.0 [2026-03-22]

Change Log:
    v1.51.0 [2026-03-22] — Migrated to FlaskScene (unified base class)
    v0.68   [2026-03-20] — Dark Renaissance arcade scene
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from flask import jsonify, render_template, request
from flask_socketio import emit

from engine.scenes.flask_scene import FlaskScene

# v1.49.3 [2026-03-22] — Structured logging context (SCENE_ID prefix + operation tags)
# v1.49.2 [2026-03-22] — Removed duplicate 'log' variable (CLAUDE.md standard: use 'logger')
SCENE_ID = "games"
# v1.49.1 [2026-03-22] — Use port registry instead of hardcoded value
try:
    from engine.port_registry import get_port as _get_port
    DEFAULT_PORT = _get_port("games", 5567)
except Exception:
    DEFAULT_PORT = 5567
GAMEMASTER_ID = "gamemaster"

# Games available in THE ARCADE
ARCADE_GAMES = ["mystery", "dice_challenge", "truth_or_dare", "trivia", "word_game"]


# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class GamesScene(FlaskScene):
    """THE ARCADE — violet-themed game hub with AI GameMaster, Socket.IO events,
    investigation board, 3D dice, adult Truth-or-Dare, and Nexus leaderboard."""

    SCENE_METADATA = {
        "name": "games",
        "display_name": "THE ARCADE",
        "port": 5567,
        "type": "games",
        "accent_color": "#8b5cf6",
        "accent_rgb": "139 92 246",
        "description": "Insert coin. Lose yourself. The high score is never enough.",
    }

    # v1.51.0 [2026-03-22] — Migrated to FlaskScene
    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        super().__init__(host=host, port=port)

        self.mystery_games: Dict[str, Any] = {}
        self.tod_games: Dict[str, Any] = {}
        self._fw: Optional[Any] = None
        self._active_game: Dict[str, str] = {}   # player → active game type
        self._trivia_state: Dict[str, Any] = {}  # player → trivia state

        self._register_routes()
        self._setup_socketio()
        self._wire_mcp()
        self._register_gamemaster()

        # Wire bench route (TTS already registered by FlaskScene)
        self.register_bench_route(self.app, self.socketio)

        logger.info("[%s] Scene created on port %d", SCENE_ID, port)

    # ── MCP Integration ──────────────────────────────────────────────

    def _wire_mcp(self) -> None:
        """Wire scene into MCP framework with state node."""
        try:
            from engine.mcp.framework import get_framework
            self._fw = get_framework()
            self._scene_node = self._fw.get_scene(SCENE_ID)
            self._scene_node.update_state({
                "scores": {},
                "leaderboard": [],
                "games_played": 0,
                "mysteries_solved": 0,
                "tod_rounds": 0,
                "active_game": None,
            })
            logger.info("[%s] MCP wired (operation=mcp_wire)", SCENE_ID)
        except Exception as exc:
            logger.warning("[%s] MCP wiring skipped (operation=mcp_wire): %s", SCENE_ID, exc)
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
                logger.info("[%s] GameMaster character registered (operation=seed)", SCENE_ID)

            if self._fw:
                self._fw.get_character(GAMEMASTER_ID).enter_scene(SCENE_ID)
        except Exception as exc:
            logger.warning("[%s] GameMaster registration skipped (operation=seed): %s", SCENE_ID, exc)

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
            logger.debug("GameMaster AI unavailable: %s", exc)
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
        """Update persistent score for a player and refresh leaderboard."""
        scores = {}
        if self._scene_node:
            scores = self._scene_node.get_state().get("scores", {})

        if player not in scores:
            scores[player] = {
                "mystery_wins": 0, "mystery_losses": 0,
                "tod_score": 0, "tod_rounds": 0,
                "dice_wins": 0, "total_games": 0,
                "total_points": 0,
            }

        scores[player]["total_games"] += 1
        if game == "mystery":
            if won:
                scores[player]["mystery_wins"] += 1
                scores[player]["total_points"] += 10
            else:
                scores[player]["mystery_losses"] += 1
        elif game == "tod":
            scores[player]["tod_score"] += points
            scores[player]["tod_rounds"] += 1
            scores[player]["total_points"] += points
        elif game == "dice":
            if won:
                scores[player]["dice_wins"] += 1
                scores[player]["total_points"] += points

        if self._scene_node:
            state = self._scene_node.get_state()
            state["scores"] = scores
            state["games_played"] = state.get("games_played", 0) + 1
            if game == "mystery" and won:
                state["mysteries_solved"] = state.get("mysteries_solved", 0) + 1
            # Rebuild leaderboard (top-10 by total_points)
            lb: List[Dict[str, Any]] = [
                {"player": p, "points": v.get("total_points", 0),
                 "games": v.get("total_games", 0)}
                for p, v in scores.items()
            ]
            lb.sort(key=lambda x: x["points"], reverse=True)
            state["leaderboard"] = lb[:10]
            self._scene_node.update_state(state)

        return scores[player]

    def _get_leaderboard(self) -> List[Dict[str, Any]]:
        """Return current top-10 leaderboard from MCP state."""
        if self._scene_node:
            return self._scene_node.get_state().get("leaderboard", [])
        return []

    # ── Routes ───────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        app = self.app

        from .mystery_investigation import mystery_bp
        from .truth_or_dare import truth_or_dare_bp
        app.register_blueprint(mystery_bp, url_prefix="/games/mystery")
        app.register_blueprint(truth_or_dare_bp, url_prefix="/games/truth-or-dare")

        @app.route("/")
        def index():
            return render_template("games.html", **self.inject_navbar_context())

        @app.route("/api/health")
        def health():
            try:
                return jsonify(self.get_health())
            except Exception:
                logger.exception("[%s] Health check failed (operation=health)", SCENE_ID)
                return jsonify({"status": "error", "scene": "games", "reason": "health check raised"}), 500

        @app.route("/api/status")
        def status():
            scores = {}
            state = {}
            if self._scene_node:
                state = self._scene_node.get_state()
                scores = state.get("scores", {})
            return jsonify({
                "scene": SCENE_ID,
                "display_name": self.SCENE_METADATA["display_name"],
                "active_game": state.get("active_game"),
                "mystery_active": len(self.mystery_games),
                "tod_active": len(self.tod_games),
                "scores": scores,
                "games_played": state.get("games_played", 0),
                "games_available": ARCADE_GAMES,
            })

        @app.route("/api/scores")
        def get_scores():
            """Get all player scores."""
            scores = {}
            if self._scene_node:
                scores = self._scene_node.get_state().get("scores", {})
            return jsonify(scores)

        @app.route("/api/leaderboard")
        def get_leaderboard():
            """Get THE ARCADE leaderboard (top-10 by points)."""
            return jsonify({
                "leaderboard": self._get_leaderboard(),
                "scene": SCENE_ID,
            })

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

        # v1.51.0 — FlaskScene registers health, hud, announcer, inventory, tts
        try:
            self.mount_overlay(app)
            self.mount_skills_server(app)
        except Exception:
            pass

    # ── Socket.IO Events ─────────────────────────────────────────────

    def _setup_socketio(self) -> None:
        """Wire Socket.IO event handlers for THE ARCADE real-time gameplay."""
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            logger.debug("THE ARCADE client connected")
            scores = {}
            state = {}
            if self._scene_node:
                state = self._scene_node.get_state()
                scores = state.get("scores", {})
            emit("game_update", {
                "type": "connected",
                "display_name": self.SCENE_METADATA["display_name"],
                "accent": self.SCENE_METADATA["accent_color"],
                "scores": scores,
                "games_available": ARCADE_GAMES,
                "leaderboard": self._get_leaderboard(),
            })

        @sio.on("disconnect")
        def on_disconnect():
            logger.debug("THE ARCADE client disconnected")

        # ── New v0.68 handlers ────────────────────────────────────────

        @sio.on("get_games_state")
        def on_get_games_state(data: Dict[str, Any] = None) -> None:
            """Emit current arcade state: active game, scores, leaderboard."""
            data = data or {}
            player = data.get("player", "player")
            state = {}
            if self._scene_node:
                state = self._scene_node.get_state()
            emit("games_state", {
                "active_game": self._active_game.get(player),
                "games_available": ARCADE_GAMES,
                "scores": state.get("scores", {}).get(player, {}),
                "leaderboard": self._get_leaderboard(),
                "games_played": state.get("games_played", 0),
            })

        @sio.on("start_game")
        def on_start_game(data: Dict[str, Any]) -> None:
            """Begin a specific mini-game for a player."""
            player = data.get("player", "player")
            game = (data.get("game") or "").lower().strip()
            if game not in ARCADE_GAMES:
                emit("error", {"message": f"Unknown game '{game}'. Available: {ARCADE_GAMES}"})
                return
            self._active_game[player] = game
            if self._scene_node:
                s = self._scene_node.get_state()
                s["active_game"] = game
                self._scene_node.update_state(s)

            intro = self._get_gamemaster_reply(
                f"Welcome to THE ARCADE! A new game of {game.replace('_', ' ').title()} begins. "
                f"Introduce it with dark, violet-noir flair."
            )
            emit("game_started", {
                "game": game,
                "message": intro or f"Welcome to {game.replace('_', ' ').title()}!",
                "player": player,
            })

        @sio.on("submit_answer")
        def on_submit_answer(data: Dict[str, Any]) -> None:
            """Generic answer submission — routes to active game logic."""
            player = data.get("player", "player")
            answer = (data.get("answer") or "").strip()
            active = self._active_game.get(player)
            if active == "mystery":
                # Treat answer as accusation
                game = self.mystery_games.get(player)
                if not game:
                    emit("error", {"message": "No active mystery game."})
                    return
                result = game.accuse(answer)
                correct = result.get("correct", False)
                self._update_score(player, "mystery", correct)
                reaction = self._get_gamemaster_reply(
                    f"{'Correct!' if correct else 'Wrong!'} They said '{answer}', "
                    f"real culprit was {result.get('real_culprit')}."
                )
                emit("accusation_result", {
                    "correct": correct,
                    "suspect": answer,
                    "real_culprit": result.get("real_culprit"),
                    "reaction": reaction or ("Case solved!" if correct else "Not quite..."),
                    "player": player,
                })
            elif active == "truth_or_dare":
                # Route to ToD answer handler
                game = self.tod_games.get(player)
                if not game:
                    emit("error", {"message": "No active Truth-or-Dare game."})
                    return
                result = game.answer(completed=True, response=answer)
                score = result.get("score", 0)
                self._update_score(player, "tod", False, points=score)
                if score >= 5:
                    reaction = self._get_gamemaster_reply(
                        f"The player scored {score} and WINS Truth or Dare! Celebrate!"
                    )
                    emit("tod_complete", {
                        "score": score,
                        "reaction": reaction or f"You win with {score} points!",
                    })
                else:
                    emit("tod_scored", {"score": score, "completed": True})
            else:
                emit("error", {"message": f"No active game handling answers (active: {active})."})

        @sio.on("roll_dice")
        def on_roll_dice(data: Dict[str, Any]) -> None:
            """Roll an N-sided die (defaults to d6). Returns roll result with animation cue."""
            sides = int(data.get("sides", 6))
            player = data.get("player", "player")
            sides = max(2, min(sides, 100))  # clamp to sane range
            roll = random.randint(1, sides)
            narrative = self._get_gamemaster_reply(
                f"The dice tumble across the violet-lit table and show {roll} on a d{sides}. "
                f"React dramatically — build tension!"
            )
            self._update_score(player, "dice", roll == sides, points=roll)
            emit("dice_result", {
                "roll": roll,
                "sides": sides,
                "is_max": roll == sides,
                "narration": narrative or f"Rolled {roll}!",
                "player": player,
            })

        @sio.on("get_leaderboard")
        def on_get_leaderboard(data: Dict[str, Any] = None) -> None:
            """Emit current Nexus-backed leaderboard."""
            emit("leaderboard_update", {
                "leaderboard": self._get_leaderboard(),
                "scene": SCENE_ID,
            })

        # ── Legacy handlers (Mystery + ToD) ──────────────────────────

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
            self._active_game[player] = "mystery"
            result = game.start(case_index)

            intro_prompt = (
                f"A new mystery begins in THE ARCADE: '{result['case_title']}'. "
                f"Setting: {result['setting']}. "
                f"Set the scene with dark, violet-neon atmosphere. Welcome the detective."
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
                    f"Clue #{clue_num} in THE ARCADE mystery: \"{clue}\". "
                    f"Describe it with noir suspense under violet neon."
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
                prompt = f"CORRECT in THE ARCADE! The culprit was {result.get('real_culprit')}! Celebrate with violet flair!"
            else:
                prompt = (
                    f"Wrong in THE ARCADE! They said '{suspect}' but it was "
                    f"{result.get('real_culprit')}. React with theatrical sympathy."
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
            self._active_game[player] = "truth_or_dare"
            game.start()

            intro = self._get_gamemaster_reply(
                "A new game of Truth or Dare begins in THE ARCADE. "
                "Welcome the player with violet-tinged excitement and a hint of danger."
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
            intensity = result.get("intensity", 1)
            narration = self._get_gamemaster_reply(
                f"The dice show {result.get('roll')}! It's a {kind.upper()} "
                f"(intensity {intensity}): \"{prompt_text}\". Present with dark arcade energy."
            )
            emit("tod_prompt", {
                "roll": result.get("roll"),
                "type": kind,
                "prompt": prompt_text,
                "intensity": intensity,
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
                    f"The player scored {score} points and WINS in THE ARCADE! Celebrate!"
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

    # v1.51.0 [2026-03-22] — start/stop delegated to FlaskScene

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
            "display_name": self.SCENE_METADATA["display_name"],
            "description": self.SCENE_METADATA["description"],
            "version": "0.68",
            "author": "CosySim",
            "port": self.port,
            "accent_color": self.SCENE_METADATA["accent_color"],
            "tags": ["games", "arcade", "mystery", "truth_or_dare", "dice", "ai_gamemaster"],
            "skill_packs": ["games"],
            "routes": [
                "/", "/api/health", "/api/status", "/api/scores",
                "/api/leaderboard", "/api/chat",
                "/api/mystery/narrate", "/api/mystery/react",
                "/games/mystery/*", "/games/truth-or-dare/*",
            ],
        }


def create_app(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> GamesScene:
    """Factory for launcher integration."""
    return GamesScene(host=host, port=port)


if __name__ == "__main__":
    scene = GamesScene(host="0.0.0.0", port=DEFAULT_PORT)
    scene.start()
