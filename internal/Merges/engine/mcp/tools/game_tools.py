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
from pydantic import BaseModel

from engine.mcp.decorators import mcp_tool


class GameStateResponse(BaseModel):
    state: Dict[str, Any]


class GameUpdateResponse(BaseModel):
    status: str


class GameStartResponse(BaseModel):
    status: str


class GameEndResponse(BaseModel):
    game_id: str
    summary: str
    final_state: Dict[str, Any]


# ── Simple game state (comms_framework GameState) ──────────────────────


@mcp_tool
def get_game_state(game_id: str, *, key: Optional[str] = None) -> GameStateResponse:
    """Read game state for *game_id*; optionally a single *key*."""
    from engine.mcp.comms_framework import get_game_state as _gs

    gs = _gs()
    if key:
        val = gs.get(game_id, key)
        return GameStateResponse(state={game_id: {key: val}})
    return GameStateResponse(state={game_id: gs.get_all(game_id)})


@mcp_tool
def set_game_state(game_id: str, key: str, value: str) -> GameUpdateResponse:
    """Write a single *key*/*value* pair into the game state."""
    from engine.mcp.comms_framework import get_game_state as _gs

    _gs().set(game_id, key, value)
    return GameUpdateResponse(status=f"Game state updated: {game_id}.{key} = {value!r}")


@mcp_tool
def start_game(
    game_id: str,
    scene: str = "phone",
    config_json: Optional[str] = None,
) -> GameStartResponse:
    """Reset and start a new game session."""
    from engine.mcp.comms_framework import get_game_state as _gs

    gs = _gs()
    gs.reset(game_id)
    config = json.loads(config_json) if config_json else {}
    gs.set(game_id, "active", True)
    gs.set(game_id, "scene", scene)
    gs.set(game_id, "started_at", str(time.time()))
    gs.set(game_id, "round", 0)
    gs.set(game_id, "score", 0)
    for k, v in config.items():
        gs.set(game_id, k, v)
    return GameStartResponse(status=f"Game '{game_id}' started in scene '{scene}'.")


@mcp_tool
def end_game(game_id: str) -> GameEndResponse:
    """End a game and return a final-state summary."""
    from engine.mcp.comms_framework import get_game_state as _gs

    gs = _gs()
    state = gs.get_all(game_id)
    gs.set(game_id, "active", False)
    gs.set(game_id, "ended_at", str(time.time()))
    return GameEndResponse(
        game_id=game_id,
        summary="Game ended.",
        final_state=state,
    )


# ── MCP-tracked game tools (MCPGameSession) ────────────────────────────


@mcp_tool
def launch_game(
    character_id: str,
    game_type: str,
    case_index: int = -1,
) -> Any:
    """Start an MCP-tracked game session for a character."""
    from content.scenes.bedroom.bedroom_game_skill import launch_game as _lg

    return _lg(character_id, game_type, case_index)


@mcp_tool
def get_active_game(character_id: str) -> Any:
    """Return the active MCP game session summary for *character_id*."""
    from content.scenes.bedroom.bedroom_game_skill import get_active_game as _gag

    return _gag(character_id)


@mcp_tool
def game_action(
    character_id: str,
    action: str,
    data_json: str = "{}",
) -> Any:
    """Perform a game action for a character's active session."""
    from content.scenes.bedroom.bedroom_game_skill import game_action as _ga

    return _ga(character_id, action, data_json)


@mcp_tool
def game_history(character_id: str, limit: int = 20) -> Any:
    """Retrieve turn-by-turn MCP game history for a character."""
    from content.scenes.bedroom.bedroom_game_skill import game_history as _gh

    return _gh(character_id, limit)
