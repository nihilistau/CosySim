"""
Truth or Dare game — CosySim scene module
==========================================
Exposes a Flask Blueprint (``truth_or_dare_bp``) that can be registered on
any existing Flask app.

Game flow
---------
1. ``POST /games/truth-or-dare/start``  – initialise / reset the game for a
   given ``character_id``.
2. The character (via AgentGovernor + GameRulesInterceptor) uses the MCP tools
   ``roll_dice``, ``get_random_topic``, ``set_game_state``, ``update_mood``.
3. ``GET  /games/truth-or-dare/state``  – poll current state.
4. ``POST /games/truth-or-dare/answer`` – submit a truth answer or dare
   completion.
5. ``POST /games/truth-or-dare/end``    – end the game early.

Game state keys (stored in GameState under game_id ``truth_or_dare_<char>``)
-----------------------------------------------------------------------------
- ``active``         bool
- ``scene``          str  "truth_or_dare"
- ``character_id``   str
- ``round``          int
- ``score``          int  (points for completed truths/dares)
- ``last_roll``      int  (1-6)
- ``current_type``   str  "truth" | "dare" | None
- ``current_prompt`` str  the actual question or dare text
- ``rounds_history`` list[dict]
"""

from __future__ import annotations

import random
import time
import logging
from typing import Optional

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# ── content ──────────────────────────────────────────────────────────────────

TRUTH_QUESTIONS = [
    "What is the most embarrassing thing that ever happened to you?",
    "What is your biggest secret?",
    "Have you ever lied to someone you care about? What was it?",
    "What is the strangest dream you have ever had?",
    "What is something you have never told anyone?",
    "If you could change one decision in your life, what would it be?",
    "What are you most afraid of?",
    "What is your most treasured memory?",
    "Have you ever had a crush on someone unexpected?",
    "What do you regret most in life?",
    "What is the bravest thing you have ever done?",
    "What would you do with a million dollars?",
    "Who knows you better than anyone else?",
    "What is your biggest insecurity?",
    "What makes you truly happy?",
]

DARE_PROMPTS = [
    "Sing the chorus of your favourite song right now.",
    "Do your best impression of someone famous.",
    "Dance for 30 seconds without music.",
    "Tell me something nice about the person you dislike most.",
    "Speak in an accent for the next two minutes.",
    "Describe yourself in three words.",
    "Say the alphabet backwards as fast as you can.",
    "Make up a short poem about today.",
    "Pretend you're a robot for the next two turns.",
    "Tell me your most embarrassing story using only sound effects.",
    "Describe your perfect day in 60 seconds.",
    "Give yourself a new nickname and explain why it fits you.",
    "List five things you love about your life right now.",
    "Act out your morning routine without speaking.",
    "Come up with a new catchphrase and use it three times naturally.",
]

# ── Flask Blueprint ───────────────────────────────────────────────────────────

truth_or_dare_bp = Blueprint(
    "truth_or_dare",
    __name__,
    url_prefix="/games/truth-or-dare",
)


def _game_id(character_id: str) -> str:
    return f"truth_or_dare_{character_id}"


def _get_gs():
    from engine.mcp.comms_framework import get_game_state
    return get_game_state()


@truth_or_dare_bp.route("/start", methods=["POST"])
def start():
    """Start (or restart) a Truth-or-Dare game for a character."""
    body = request.get_json(silent=True) or {}
    character_id: str = body.get("character_id", "default")
    gid = _game_id(character_id)
    gs = _get_gs()

    gs.reset(gid)
    gs.set(gid, "active", True)
    gs.set(gid, "scene", "truth_or_dare")
    gs.set(gid, "character_id", character_id)
    gs.set(gid, "round", 0)
    gs.set(gid, "score", 0)
    gs.set(gid, "last_roll", None)
    gs.set(gid, "current_type", None)
    gs.set(gid, "current_prompt", None)
    gs.set(gid, "rounds_history", [])
    gs.set(gid, "started_at", time.time())

    # ── MCP session ──────────────────────────────────────────────────
    try:
        from engine.mcp.game_mcp import get_or_create_session
        session = get_or_create_session(gid, "truth_or_dare", character_id, "bedroom")
        session.log_event("game_start", f"Truth or Dare started for {character_id}", actor="system")
    except Exception as _mcp_exc:
        logger.debug("TOD start: MCP session init skipped: %s", _mcp_exc)

    logger.info("Truth-or-Dare started for character=%s game_id=%s", character_id, gid)
    return jsonify({"status": "started", "game_id": gid, "state": gs.all_games().get(gid, {})})


@truth_or_dare_bp.route("/roll", methods=["POST"])
def roll():
    """Roll the dice and determine truth or dare for this round."""
    body = request.get_json(silent=True) or {}
    character_id: str = body.get("character_id", "default")
    gid = _game_id(character_id)
    gs = _get_gs()

    if not gs.get(gid, "active"):
        return jsonify({"error": "No active game. Call /start first."}), 400

    roll_value = random.randint(1, 6)
    kind = "truth" if roll_value % 2 == 1 else "dare"
    prompt = (
        random.choice(TRUTH_QUESTIONS) if kind == "truth" else random.choice(DARE_PROMPTS)
    )

    gs.set(gid, "last_roll", roll_value)
    gs.set(gid, "current_type", kind)
    gs.set(gid, "current_prompt", prompt)
    gs.increment(gid, "round")

    return jsonify({
        "roll": roll_value,
        "type": kind,
        "prompt": prompt,
        "round": gs.get(gid, "round"),
    })


@truth_or_dare_bp.route("/answer", methods=["POST"])
def answer():
    """Submit a truth answer or dare completion."""
    body = request.get_json(silent=True) or {}
    character_id: str = body.get("character_id", "default")
    completed: bool   = bool(body.get("completed", True))
    response_text: str = body.get("response", "")
    gid = _game_id(character_id)
    gs = _get_gs()

    if not gs.get(gid, "active"):
        return jsonify({"error": "No active game."}), 400

    kind    = gs.get(gid, "current_type") or "truth"
    prompt  = gs.get(gid, "current_prompt") or ""
    round_n = gs.get(gid, "round") or 0

    history: list = gs.get(gid, "rounds_history") or []
    history.append({
        "round":     round_n,
        "type":      kind,
        "prompt":    prompt,
        "completed": completed,
        "response":  response_text,
        "timestamp": time.time(),
    })
    gs.set(gid, "rounds_history", history)

    if completed:
        pts = 2 if kind == "dare" else 1
        gs.increment(gid, "score", pts)

    # clear current prompt
    gs.set(gid, "current_type", None)
    gs.set(gid, "current_prompt", None)

    # ── MCP session event ────────────────────────────────────────────
    try:
        from engine.mcp.game_mcp import get_session
        _s = get_session(gid)
        if _s:
            if kind == "dare":
                _evt = "dare_completed" if completed else "dare_refused"
            else:
                _evt = "truth_answered"
            _s.log_event(
                _evt,
                f"Round {round_n}: {kind} — {'done' if completed else 'skipped'} — {prompt[:60]}",
                {"kind": kind, "prompt": prompt, "completed": completed, "response": response_text},
                actor="player",
            )
    except Exception as _mcp_exc:
        logger.debug("TOD answer: MCP event skipped: %s", _mcp_exc)

    return jsonify({
        "accepted": True,
        "score": gs.get(gid, "score"),
        "rounds_played": round_n,
    })


@truth_or_dare_bp.route("/state", methods=["GET"])
def state():
    character_id = request.args.get("character_id", "default")
    gid = _game_id(character_id)
    gs = _get_gs()
    return jsonify(gs.all_games().get(gid, {}))


@truth_or_dare_bp.route("/end", methods=["POST"])
def end():
    body = request.get_json(silent=True) or {}
    character_id: str = body.get("character_id", "default")
    gid = _game_id(character_id)
    gs = _get_gs()

    final_score = gs.get(gid, "score") or 0
    rounds      = gs.get(gid, "round") or 0
    gs.set(gid, "active", False)
    gs.set(gid, "ended_at", time.time())

    # ── MCP session end ──────────────────────────────────────────────
    try:
        from engine.mcp.game_mcp import get_session
        _s = get_session(gid)
        if _s and _s.get("active"):
            _s.end(won=(final_score >= 5), final_note=f"Game ended score={final_score} rounds={rounds}")
    except Exception as _mcp_exc:
        logger.debug("TOD end: MCP session end skipped: %s", _mcp_exc)

    logger.info(
        "Truth-or-Dare ended for character=%s score=%d rounds=%d",
        character_id, final_score, rounds,
    )
    return jsonify({"status": "ended", "score": final_score, "rounds_played": rounds})


# ── Standalone helper (importable without Flask) ──────────────────────────────

class TruthOrDareGame:
    """
    Programmatic wrapper around the game state — useful for agent integration
    or testing without a running Flask server.
    """

    def __init__(self, character_id: str = "default") -> None:
        self.character_id = character_id
        self.game_id = _game_id(character_id)

    def start(self) -> dict:
        gs = _get_gs()
        gs.reset(self.game_id)
        gs.set(self.game_id, "active", True)
        gs.set(self.game_id, "scene", "truth_or_dare")
        gs.set(self.game_id, "character_id", self.character_id)
        gs.set(self.game_id, "round", 0)
        gs.set(self.game_id, "score", 0)
        gs.set(self.game_id, "started_at", time.time())
        try:
            from engine.mcp.game_mcp import get_or_create_session
            _s = get_or_create_session(self.game_id, "truth_or_dare", self.character_id)
            _s.log_event("game_start", f"TOD game started", actor="system")
        except Exception:
            pass
        return {"started": True, "game_id": self.game_id}

    def roll(self) -> dict:
        gs = _get_gs()
        if not gs.get(self.game_id, "active"):
            raise RuntimeError("Game not active. Call start() first.")
        roll_value = random.randint(1, 6)
        kind   = "truth" if roll_value % 2 == 1 else "dare"
        prompt = (
            random.choice(TRUTH_QUESTIONS) if kind == "truth"
            else random.choice(DARE_PROMPTS)
        )
        gs.set(self.game_id, "last_roll", roll_value)
        gs.set(self.game_id, "current_type", kind)
        gs.set(self.game_id, "current_prompt", prompt)
        gs.increment(self.game_id, "round")
        return {"roll": roll_value, "type": kind, "prompt": prompt}

    def answer(self, completed: bool = True, response: str = "") -> dict:
        gs = _get_gs()
        kind    = gs.get(self.game_id, "current_type") or "truth"
        round_n = gs.get(self.game_id, "round") or 0
        if completed:
            gs.increment(self.game_id, "score", 2 if kind == "dare" else 1)
        gs.set(self.game_id, "current_type", None)
        gs.set(self.game_id, "current_prompt", None)
        try:
            from engine.mcp.game_mcp import get_session
            _s = get_session(self.game_id)
            if _s:
                _evt = ("dare_completed" if completed else "dare_refused") if kind == "dare" else "truth_answered"
                _s.log_event(_evt, f"Round {round_n}: {kind}", actor="player")
        except Exception:
            pass
        return {"score": gs.get(self.game_id, "score"), "round": round_n}

    def end(self) -> dict:
        gs = _get_gs()
        score  = gs.get(self.game_id, "score") or 0
        rounds = gs.get(self.game_id, "round") or 0
        gs.set(self.game_id, "active", False)
        gs.set(self.game_id, "ended_at", time.time())
        try:
            from engine.mcp.game_mcp import get_session
            _s = get_session(self.game_id)
            if _s and _s.get("active"):
                _s.end(won=(score >= 5), final_note=f"Game ended score={score}")
        except Exception:
            pass
        return {"score": score, "rounds": rounds}

    @property
    def state(self) -> dict:
        return _get_gs().all_games().get(self.game_id, {})
