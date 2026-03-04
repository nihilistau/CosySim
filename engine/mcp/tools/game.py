"""MCP tool domain: game.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── GAME TOOLS ─────────────────────────────────────────────────────────


@mcp_tool
def roll_dice(sides: int = 6, count: int = 1) -> str:
    """
    Roll one or more dice and return the results.
    Useful for game mechanics, random outcomes, or adding unpredictability.
    Example: roll_dice(100) gives a d100 result for truth-or-dare.
    Odd results = Truth, Even results = Dare (for truth-or-dare game).
    """
    try:
        from engine.mcp.tools.utility_tools import roll_dice_logic as _impl
        return _impl(sides, count)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_random_topic(category: str = "general") -> str:
    """
    Get a randomly selected topic or prompt for conversation or games.
    Categories: 'truth_questions', 'dare_ideas', 'mystery_clues',
    'conversation_starters', 'relationship_questions', 'general'.
    Use this to get fresh ideas for games, topics, or challenges.
    """
    try:
        from engine.mcp.tools.utility_tools import get_random_topic_logic as _impl
        return _impl(category)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_game_state(game_id: str, key: Optional[str] = None) -> str:
    """
    Read the current state of a game by its ID.
    If key is provided, returns only that value.
    If key is None, returns the entire game state dict.
    Common game IDs: 'truth_or_dare', 'mystery'.
    """
    try:
        from engine.mcp.tools.game_tools import get_game_state as _impl
        return _impl(game_id, key=key)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def set_game_state(game_id: str, key: str, value: str) -> str:
    """
    Write a value to the game state.
    Use this to record scores, round counts, discovered clues, game outcomes, etc.
    Value is stored as a string — use JSON encoding for complex types.
    Example: set_game_state('truth_or_dare', 'round', '3')
    """
    try:
        from engine.mcp.tools.game_tools import set_game_state as _impl
        return _impl(game_id, key, value)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def start_game(game_id: str, scene: str = "phone", config_json: Optional[str] = None) -> str:
    """
    Start a new game session.
    game_id options: 'truth_or_dare', 'mystery'
    This resets existing game state and marks the game as active.
    The game rules will automatically be injected into your system context.
    """
    try:
        from engine.mcp.tools.game_tools import start_game as _impl
        return _impl(game_id, scene, config_json)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def end_game(game_id: str) -> str:
    """
    End a game and record the final result.
    Returns a summary of the final game state including score.
    """
    try:
        from engine.mcp.tools.game_tools import end_game as _impl
        return _impl(game_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def launch_game(
    character_id: str,
    game_type:    str,
    case_index:   int = -1,
) -> str:
    """
    Start an MCP-tracked Truth-or-Dare or Mystery game session for a character.

    Creates an MCPGameSession with full history, stat sync, and ActivityBus
    integration.  Any previous session for this character+game_type is reset.

    Parameters
    ----------
    character_id : The character / player starting the game.
    game_type    : "truth_or_dare"  or  "mystery".
    case_index   : Mystery only — 0-based index of the case to play (-1 = random).

    Returns
    -------
    JSON with the new session summary including game_id and initial state.
    """
    try:
        from engine.mcp.tools.game_tools import launch_game as _impl
        return _impl(character_id, game_type, case_index)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_active_game(character_id: str) -> str:
    """
    Return the active MCP game session summary and recent history for a character.

    Checks the MCPGameSession registry first; falls back to legacy GameState if
    no MCP session is found.

    Returns
    -------
    JSON: {"active": false} if no session, or full session summary + 10-turn history.
    """
    try:
        from engine.mcp.tools.game_tools import get_active_game as _impl
        return _impl(character_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def game_action(
    character_id: str,
    action:       str,
    data_json:    str = "{}",
) -> str:
    """
    Perform a game action for a character's active MCP game session.

    Truth or Dare actions
    ---------------------
    roll         — Roll for truth or dare; receive the prompt.
    answer       — Resolve the current prompt.
                   data_json: {"completed": true}  for completing a dare.
                   Truths are always resolved as answered.

    Mystery actions
    ---------------
    next_clue    — Reveal the next clue on the board.
    accuse       — Name the culprit and resolve the case.
                   data_json: {"suspect": "Full Name"}

    Parameters
    ----------
    character_id : The acting character.
    action       : One of roll | answer | next_clue | accuse.
    data_json    : JSON-encoded extra parameters (see above).

    Returns
    -------
    JSON result dict with outcome details.
    """
    try:
        from engine.mcp.tools.game_tools import game_action as _impl
        return _impl(character_id, action, data_json)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def game_history(character_id: str, limit: int = 20) -> str:
    """
    Retrieve the full turn-by-turn MCP game history for a character's active session.

    Each entry includes: turn number, event_type, description, actor,
    data payload, and timestamp.

    Parameters
    ----------
    character_id : The character to look up.
    limit        : Maximum number of history entries to return (default 20).

    Returns
    -------
    JSON with game_id, game_type, current turn, and history list.
    """
    try:
        from engine.mcp.tools.game_tools import game_history as _impl
        return _impl(character_id, limit)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def random_pick(
    n:            int,
    options_json: str            = "[]",
    weights_json: str            = "[]",
    seed:         Optional[int]  = None,
) -> str:
    """
    **RANDOM CHOICE SKILL** — Roll a random number between 1 and n,
    or pick from a list of options.

    The system interprets the result for you: exceptional / strong /
    moderate / weak / poor — use this to determine how successful,
    intense, or interesting something is.

    Examples:
      random_pick(10)                                   → roll 1-10
      random_pick(3, '["resist", "comply", "flirt"]')  → pick one option
      random_pick(6, weights_json='[1,1,2,2,3,3]')     → weighted d6

    Use this to:
    - Determine if a seduction attempt works (roll high = success)
    - Pick what mood a character wakes up in
    - Add unpredictability to any decision point
    - Decide the outcome of a risky action

    Args:
        n:            Max value (or number of options)
        options_json: JSON list of strings to pick from (overrides n)
        weights_json: JSON list of floats — bias the distribution
        seed:         Integer seed for reproducible results (omit for random)
    """
    try:
        from engine.mcp.tools.utility_tools import random_pick_logic as _impl
        return _impl(n, options_json=options_json, weights_json=weights_json, seed=seed)
    except Exception as e:
        return json.dumps({"error": str(e)})
