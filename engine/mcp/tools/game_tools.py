"""
Pure business-logic functions for game-related MCP tools.

Each function mirrors the corresponding ``@mcp.tool()`` in
``cosysim_server.py`` but accepts its dependencies as explicit
parameters so the module stays free of MCP/FastMCP imports.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional


# ── Simple game state (comms_framework GameState) ──────────────────────

def get_game_state(game_id: str, *, key: Optional[str] = None) -> str:
    """Read game state for *game_id*; optionally a single *key*."""
    try:
        from engine.mcp.comms_framework import get_game_state as _gs
        gs = _gs()
        if key:
            val = gs.get(game_id, key)
            return json.dumps({game_id: {key: val}})
        return json.dumps({game_id: gs.get_all(game_id)}, indent=2, default=str)
    except Exception as e:
        return f"Failed to get game state: {e}"


def set_game_state(game_id: str, key: str, value: str) -> str:
    """Write a single *key*/*value* pair into the game state."""
    try:
        from engine.mcp.comms_framework import get_game_state as _gs
        _gs().set(game_id, key, value)
        return f"Game state updated: {game_id}.{key} = {value!r}"
    except Exception as e:
        return f"Failed to set game state: {e}"


def start_game(
    game_id: str,
    scene: str = "phone",
    config_json: Optional[str] = None,
) -> str:
    """Reset and start a new game session."""
    try:
        from engine.mcp.comms_framework import get_game_state as _gs
        gs = _gs()
        gs.reset(game_id)
        config = json.loads(config_json) if config_json else {}
        gs.set(game_id, "active",     True)
        gs.set(game_id, "scene",      scene)
        gs.set(game_id, "started_at", str(time.time()))
        gs.set(game_id, "round",      0)
        gs.set(game_id, "score",      0)
        for k, v in config.items():
            gs.set(game_id, k, v)
        return f"Game '{game_id}' started in scene '{scene}'."
    except Exception as e:
        return f"Failed to start game: {e}"


def end_game(game_id: str) -> str:
    """End a game and return a final-state summary."""
    try:
        from engine.mcp.comms_framework import get_game_state as _gs
        gs = _gs()
        state = gs.get_all(game_id)
        gs.set(game_id, "active",   False)
        gs.set(game_id, "ended_at", str(time.time()))
        return json.dumps({
            "game_id": game_id,
            "summary": "Game ended.",
            "final_state": state,
        }, indent=2, default=str)
    except Exception as e:
        return f"Failed to end game: {e}"


# ── MCP-tracked game tools (MCPGameSession) ────────────────────────────

def launch_game(
    character_id: str,
    game_type: str,
    case_index: int = -1,
) -> str:
    """Start an MCP-tracked game session for a character."""
    try:
        from content.scenes.bedroom.bedroom_game_skill import launch_game as _lg
        return _lg(character_id, game_type, case_index)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_active_game(character_id: str) -> str:
    """Return the active MCP game session summary for *character_id*."""
    try:
        from content.scenes.bedroom.bedroom_game_skill import get_active_game as _gag
        return _gag(character_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


def game_action(
    character_id: str,
    action: str,
    data_json: str = "{}",
) -> str:
    """Perform a game action for a character's active session."""
    try:
        from content.scenes.bedroom.bedroom_game_skill import game_action as _ga
        return _ga(character_id, action, data_json)
    except Exception as e:
        return json.dumps({"error": str(e)})


def game_history(character_id: str, limit: int = 20) -> str:
    """Retrieve turn-by-turn MCP game history for a character."""
    try:
        from content.scenes.bedroom.bedroom_game_skill import game_history as _gh
        return _gh(character_id, limit)
    except Exception as e:
        return json.dumps({"error": str(e)})
