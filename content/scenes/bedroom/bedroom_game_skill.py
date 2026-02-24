"""
Bedroom Game Skills
===================

MCP-backed game skill functions exposed to bedroom agents and the admin MCP
tool surface.  Imported by ``engine/mcp/cosysim_server.py`` and registered
as FastMCP tools (``launch_game``, ``get_active_game``, ``game_action``,
``game_history``).

Each function is also callable directly from bedroom Flask routes and test
helpers without requiring the MCP server to be running.

Game types
----------
``truth_or_dare``
    Classic Truth or Dare.  Actions: ``roll``, ``answer``.

``mystery``
    Mystery Investigation (3 built-in cases).  Actions: ``next_clue``,
    ``accuse``.

Usage example
-------------
>>> from content.scenes.bedroom.bedroom_game_skill import launch_game, game_action
>>> result = launch_game("char:001", "truth_or_dare")
>>> result = game_action("char:001", "roll")
>>> result = game_action("char:001", "answer", '{"completed": true}')
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
def _session_id_for(character_id: str, game_type: str) -> str:
    """Deterministic session ID (same char + type → same bucket)."""
    safe = character_id.replace(":", "_").replace("/", "_")
    return f"{game_type}_{safe}"


# ══════════════════════════════════════════════════════════════════════
#   launch_game
# ══════════════════════════════════════════════════════════════════════

def launch_game(
    character_id: str,
    game_type:    str,
    case_index:   int = -1,
    *,
    scene_id:     str = "bedroom",
) -> str:
    """
    Start a Truth-or-Dare or Mystery game session, fully MCP-tracked.

    Parameters
    ----------
    character_id : str  Character / agent starting the game.
    game_type    : str  ``"truth_or_dare"`` or ``"mystery"``.
    case_index   : int  Mystery only — 0-based case index.  -1 = random.
    scene_id     : str  Parent scene (default ``"bedroom"``).

    Returns
    -------
    JSON string with the new session summary.
    """
    game_type = game_type.lower().strip()
    if game_type not in ("truth_or_dare", "mystery"):
        return json.dumps({"error": f"Unknown game_type '{game_type}'. Use truth_or_dare or mystery."})

    from engine.mcp.game_mcp import get_or_create_session
    from engine.mcp.comms_framework import get_game_state

    game_id = _session_id_for(character_id, game_type)
    gs      = get_game_state()

    # Reset any prior state so this is a clean session
    try:
        gs.reset(game_id)
    except Exception:
        pass

    session = get_or_create_session(game_id, game_type, character_id, scene_id)

    # Type-specific initialisation
    if game_type == "truth_or_dare":
        gs.set(game_id, "round",           0)
        gs.set(game_id, "dare_count",      0)
        gs.set(game_id, "truth_count",     0)
        gs.set(game_id, "skip_count",      0)
        gs.set(game_id, "current_type",    None)
        gs.set(game_id, "current_prompt",  None)
        session.log_event(
            "game_start",
            f"Truth or Dare started for {character_id}",
            {"scene": scene_id},
            actor="system",
        )

    elif game_type == "mystery":
        # Import mystery data to pick a case
        try:
            from content.scenes.games.mystery_investigation import MysteryGame
            mg = MysteryGame()
            total_cases = len(mg.cases)
            if case_index < 0 or case_index >= total_cases:
                import random
                case_index = random.randint(0, total_cases - 1)
            case = mg.cases[case_index]
            gs.set(game_id, "case_index",   case_index)
            gs.set(game_id, "case_title",   case.get("title", f"Case {case_index}"))
            gs.set(game_id, "clues_total",  len(case.get("clues", [])))
            gs.set(game_id, "clues_found",  0)
            gs.set(game_id, "accusation",   None)
        except Exception as exc:
            gs.set(game_id, "case_index",  case_index)
            gs.set(game_id, "case_title",  f"Case #{case_index}")
            gs.set(game_id, "clues_total", 5)
            gs.set(game_id, "clues_found", 0)
            logger.warning("launch_game: mystery init: %s", exc)

        session.log_event(
            "game_start",
            f"Mystery investigation '{gs.get(game_id, 'case_title')}' started for {character_id}",
            {"scene": scene_id, "case_index": case_index},
            actor="system",
        )

    summary = session.summary()
    logger.info("launch_game: %s type=%s char=%s", game_id, game_type, character_id)
    return json.dumps({"ok": True, "session": summary}, default=str)


# ══════════════════════════════════════════════════════════════════════
#   get_active_game
# ══════════════════════════════════════════════════════════════════════

def get_active_game(character_id: str) -> str:
    """
    Return the active game session summary + recent history for a character.

    Returns
    -------
    JSON string: ``{"active": false}`` if none, or full session summary.
    """
    from engine.mcp.game_mcp import get_active_session

    session = get_active_session(character_id)
    if session is None:
        # Fallback: check raw GameState
        from engine.mcp.comms_framework import get_game_state
        gs   = get_game_state()
        for gid in gs.all_games():
            if gs.get(gid, "active") and gs.get(gid, "character_id") == character_id:
                summary = gs.get_all(gid)
                return json.dumps({"active": True, "source": "legacy", "state": summary})
        return json.dumps({"active": False})

    summary  = session.summary()
    history  = session.get_history(10)
    return json.dumps({"active": True, "session": summary, "history": history}, default=str)


# ══════════════════════════════════════════════════════════════════════
#   game_action
# ══════════════════════════════════════════════════════════════════════

def game_action(
    character_id: str,
    action:       str,
    data_json:    str = "{}",
) -> str:
    """
    Perform a game action for a character's active game session.

    Truth or Dare actions
    ---------------------
    ``roll``    — Roll for truth or dare; returns the prompt.
    ``answer``  — Resolve the current prompt.  Expects ``{"completed": true}``
                  in *data_json* for a dare; truths are always "answered".

    Mystery actions
    ---------------
    ``next_clue`` — Advance to the next clue on the board.
    ``accuse``    — Make an accusation.  Expects ``{"suspect": "Name"}``
                    in *data_json*.

    Parameters
    ----------
    character_id : str  The acting character.
    action       : str  One of ``roll``, ``answer``, ``next_clue``, ``accuse``.
    data_json    : str  JSON-encoded extra parameters.

    Returns
    -------
    JSON result string.
    """
    action = action.lower().strip()

    try:
        data: Dict = json.loads(data_json) if data_json else {}
    except json.JSONDecodeError:
        return json.dumps({"error": f"Invalid data_json: {data_json!r}"})

    from engine.mcp.game_mcp import get_active_session
    session = get_active_session(character_id)
    if session is None:
        return json.dumps({"error": "No active game session found. Use launch_game first."})

    game_type = session.session_type

    # ── Truth or Dare ─────────────────────────────────────────────────
    if game_type == "truth_or_dare":
        if action == "roll":
            return _tod_roll(session, character_id)
        elif action == "answer":
            completed = bool(data.get("completed", True))
            return _tod_answer(session, character_id, completed=completed)
        else:
            return json.dumps({"error": f"Unknown TOD action '{action}'. Use: roll, answer"})

    # ── Mystery ───────────────────────────────────────────────────────
    elif game_type == "mystery":
        if action == "next_clue":
            return _mystery_next_clue(session, character_id)
        elif action == "accuse":
            suspect = data.get("suspect", "")
            return _mystery_accuse(session, character_id, suspect)
        else:
            return json.dumps({"error": f"Unknown mystery action '{action}'. Use: next_clue, accuse"})

    return json.dumps({"error": f"Unsupported game type '{game_type}'"})


# ── TOD helper actions ────────────────────────────────────────────────

def _tod_roll(session, character_id: str) -> str:
    """Roll for truth or dare and return the prompt."""
    import random
    from engine.mcp.comms_framework import get_game_state

    TRUTHS = [
        # ── Mild (warmup) ───────────────────────────────────────
        "What's the dirtiest fantasy you've ever had about someone in this room?",
        "Describe the best orgasm you've ever had — in detail.",
        "What's the kinkiest thing you've actually done? Don't spare the details.",
        "Have you ever been caught having sex? What happened?",
        "What part of your body is the most sensitive during sex?",
        "What's your go-to move when you want to make someone cum fast?",
        # ── Medium (escalation) ─────────────────────────────────
        "Describe exactly what you'd do to the person on your left right now.",
        "What's your biggest sexual regret — the thing you wish you'd said yes to?",
        "Have you ever faked an orgasm? Describe what you were really feeling.",
        "What do you sound like when you cum? Show us.",
        "Describe the filthiest sext you've ever sent — word for word.",
        "What position makes you cum hardest and why?",
        "Describe in graphic detail what you want done to you tonight.",
        "What's the most people you've been with at once? Describe it.",
        # ── Hot (no holds barred) ───────────────────────────────
        "Tell us your most depraved sexual fantasy — the one you've never told anyone.",
        "If you could do anything to anyone in this room right now with zero consequences, what would it be?",
        "Describe — in pornographic detail — the last time you masturbated.",
        "What words make you the wettest/hardest? Say them out loud.",
        "Rank everyone in this room by who you'd fuck first, and say exactly what you'd do to each.",
        "Confess the most taboo sexual thought you've ever had.",
        "Describe your ideal threesome — who does what to whom.",
    ]
    DARES = [
        # ── Mild (warmup) ───────────────────────────────────────
        "Remove one piece of clothing — slowly, like a strip tease.",
        "Give someone in this room a lap dance for 30 seconds.",
        "Kiss the person across from you — with tongue.",
        "Whisper the dirtiest thing you can think of into someone's ear.",
        "Let someone run their hands over your body for 10 seconds.",
        # ── Medium (escalation) ─────────────────────────────────
        "Take off everything below the waist and stay that way for the rest of the game.",
        "Sit on someone's lap facing them and grind for 30 seconds.",
        "Demonstrate your best oral technique — on a finger.",
        "Let someone spank you 5 times. Count each one out loud.",
        "Touch yourself for 15 seconds while everyone watches.",
        "Suck someone's finger like you mean it.",
        "Let someone undress you completely.",
        "Give someone a hickey wherever they choose.",
        "Lick whipped cream off someone's body.",
        # ── Hot (no holds barred) ───────────────────────────────
        "Go down on the person of your choice for 30 seconds.",
        "Let someone use a toy on you until your next turn.",
        "Perform a sexual act of the group's choice.",
        "Masturbate in front of everyone until you finish or your next turn.",
        "Let two people do whatever they want to you for 60 seconds.",
        "Recreate your favourite porn scene with someone willing.",
        "Edge someone until they beg — then stop.",
    ]

    gs      = get_game_state()
    gid     = session.game_id
    kind    = random.choice(["truth", "dare"])
    prompt  = random.choice(TRUTHS if kind == "truth" else DARES)
    round_n = session.increment("round")

    gs.set(gid, "current_type",   kind)
    gs.set(gid, "current_prompt", prompt)

    session.log_event(
        "rolled",
        f"Round {round_n}: rolled {kind} — '{prompt[:60]}'",
        {"kind": kind, "prompt": prompt},
        actor="system",
    )

    return json.dumps({
        "ok":     True,
        "round":  round_n,
        "kind":   kind,
        "prompt": prompt,
    })


def _tod_answer(session, character_id: str, *, completed: bool = True) -> str:
    """Resolve the current truth/dare prompt."""
    from engine.mcp.comms_framework import get_game_state
    gs  = get_game_state()
    gid = session.game_id

    kind   = session.get("current_type")
    prompt = session.get("current_prompt")
    if not kind or not prompt:
        return json.dumps({"error": "No active prompt — call roll first."})

    if kind == "dare":
        event_type = "dare_completed" if completed else "dare_refused"
        gs.increment(gid, "dare_count")
        if completed:
            gs.increment(gid, "score", 2)
    else:
        event_type = "truth_answered"
        gs.increment(gid, "truth_count")
        gs.increment(gid, "score", 1)

    round_n = session.get("round", 0)
    session.log_event(
        event_type,
        f"Round {round_n}: {kind} — {'completed' if completed else 'skipped'}",
        {"kind": kind, "prompt": prompt, "completed": completed},
        actor="player",
    )

    gs.set(gid, "current_type",   None)
    gs.set(gid, "current_prompt", None)

    return json.dumps({
        "ok":         True,
        "event_type": event_type,
        "score":      gs.get(gid, "score", 0),
        "message":    f"{'Dare completed!' if completed else 'Dare skipped.'}"
                      if kind == "dare" else "Truth answered.",
    })


# ── Mystery helper actions ────────────────────────────────────────────

def _mystery_next_clue(session, character_id: str) -> str:
    """Reveal the next clue."""
    import random
    from engine.mcp.comms_framework import get_game_state
    gs  = get_game_state()
    gid = session.game_id

    clues_found = session.get("clues_found", 0)
    clues_total = session.get("clues_total", 5)

    if clues_found >= clues_total:
        return json.dumps({"ok": False, "message": "All clues already revealed. Time to accuse!"})

    # Try to fetch real case clues
    clue_text   = ""
    is_red_herring = False
    try:
        from content.scenes.games.mystery_investigation import MysteryGame
        mg   = MysteryGame()
        cidx = session.get("case_index", 0)
        case = mg.cases[int(cidx)] if int(cidx) < len(mg.cases) else mg.cases[0]
        clues_list = case.get("clues", [])
        if clues_found < len(clues_list):
            clue = clues_list[clues_found]
            if isinstance(clue, dict):
                clue_text      = clue.get("text", str(clue))
                is_red_herring = clue.get("red_herring", False)
            else:
                clue_text = str(clue)
    except Exception:
        clue_text = f"A mysterious clue #{clues_found + 1} pointing to an unknown suspect."

    event_type = "red_herring" if is_red_herring else "clue_found"
    gs.set(gid, "clues_found", clues_found + 1)
    gs.increment(gid, "score", 1)

    session.log_event(
        event_type,
        f"Clue {clues_found + 1}: {clue_text[:80]}",
        {"clue": clue_text, "number": clues_found + 1, "red_herring": is_red_herring},
        actor="system",
    )

    return json.dumps({
        "ok":           True,
        "clue_number":  clues_found + 1,
        "clue":         clue_text,
        "red_herring":  is_red_herring,
        "clues_found":  clues_found + 1,
        "clues_total":  clues_total,
    })


def _mystery_accuse(session, character_id: str, suspect: str) -> str:
    """Make an accusation and resolve the case."""
    from engine.mcp.comms_framework import get_game_state
    gs  = get_game_state()
    gid = session.game_id

    if not suspect:
        return json.dumps({"error": "Provide a suspect name in data_json: {\"suspect\": \"Name\"}"})

    correct_suspect = ""
    verdict         = False
    try:
        from content.scenes.games.mystery_investigation import MysteryGame
        mg   = MysteryGame()
        cidx = int(session.get("case_index", 0))
        case = mg.cases[cidx] if cidx < len(mg.cases) else mg.cases[0]
        correct_suspect = case.get("culprit", "Unknown")
        verdict = suspect.strip().lower() == correct_suspect.strip().lower()
    except Exception as exc:
        logger.warning("_mystery_accuse: culprit lookup failed: %s", exc)
        verdict = False

    gs.set(gid, "accusation", suspect)
    event_type = "culprit_named" if verdict else "wrong_accusation"

    session.log_event(
        event_type,
        f"Accused '{suspect}' — {'CORRECT' if verdict else f'WRONG (was {correct_suspect})'}",
        {"suspect": suspect, "correct": correct_suspect, "verdict": verdict},
        actor="player",
    )

    if verdict:
        session.end(won=True, final_note=f"Mystery solved! {character_id} correctly accused {suspect}.")
    else:
        gs.increment(gid, "score", -2)  # penalty

    return json.dumps({
        "ok":              True,
        "suspect":         suspect,
        "correct_suspect": correct_suspect,
        "verdict":         verdict,
        "message":         f"{'Correct! Case closed.' if verdict else f'Wrong! The culprit was {correct_suspect}.'}"
    })


# ══════════════════════════════════════════════════════════════════════
#   game_history
# ══════════════════════════════════════════════════════════════════════

def game_history(character_id: str, limit: int = 20) -> str:
    """
    Return the turn-by-turn MCP game history for a character's active session.

    Parameters
    ----------
    character_id : str  The character to look up.
    limit        : int  Max entries to return (default 20).

    Returns
    -------
    JSON string with list of history entries, or ``{"error": ...}``.
    """
    from engine.mcp.game_mcp import get_active_session
    session = get_active_session(character_id)
    if session is None:
        return json.dumps({"error": "No active game session found.", "history": []})

    history = session.get_history(limit)
    return json.dumps({
        "game_id":   session.game_id,
        "game_type": session.session_type,
        "turn":      session._turn,
        "history":   history,
    }, default=str)
