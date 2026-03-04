"""Interceptor: GameInterceptor.

Split from engine/agents/interceptors.py by scripts/hindsight/split_interceptors.py.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from engine.mcp.comms_framework import (
    InterceptorBase,
    ResponseContext,
    TRIGGER_OPTIONAL,
    TRIGGER_REQUIRED,
)

logger = logging.getLogger(__name__)

class GameInterceptor(InterceptorBase):
    """
    Unified game interceptor (v3.1 — merges GameSessionInterceptor + GameRulesInterceptor).

    Priority 35.

    Pre-call
    --------
    1. Checks for active ``MCPGameSession`` → injects session state + history
    2. Checks for active game rules → injects rules + current state

    Post-call
    ---------
    Reads ``ctx["parsed"].game_events`` to detect events and fire
    MCPGameSession log entries.
    """
    name     = "game"
    priority = 35

    GAME_RULES: Dict[str, str] = {
        "truth_or_dare": (
            "You are playing Truth or Dare! Rules:\n"
            "1. On each turn, roll the dice (call `roll_dice`). "
            "Odd = Truth, Even = Dare.\n"
            "2. Give the user a truth question OR a dare based on your roll.\n"
            "3. If they complete it, call `set_game_state` to record the result "
            "and increment the score.\n"
            "4. Keep track of the round with `get_game_state`.\n"
            "5. After 10 rounds, tally the score and declare a winner.\n"
            "Make it playful, escalate intensity gradually."
        ),
        "mystery": (
            "You are running a mystery investigation game! Rules:\n"
            "1. The player is investigating a mystery — guide them with clues.\n"
            "2. Use `search_memory` to find relevant clues from past sessions.\n"
            "3. Use `get_random_topic` to generate new clue ideas.\n"
            "4. When the player discovers a clue, call `set_game_state` to record it.\n"
            "5. Check `get_game_state` to know what clues they've found so far.\n"
            "6. The player wins by finding all 5 clues and naming the culprit.\n"
            "Build suspense, be cryptic, reward deduction."
        ),
    }

    def pre_call(self, ctx: ResponseContext) -> None:
        # Part 1: MCP game session context
        try:
            from engine.mcp.game_mcp import GameSessionInterceptor as _GSI
            _GSI().pre_call(ctx)
        except Exception as exc:
            logger.debug("GameInterceptor session pre_call: %s", exc)

        # Part 2: Game rules injection
        try:
            from engine.mcp.comms_framework import get_game_state
            gs = get_game_state()
            scene = ctx.get("scene", "")

            game_id = None
            for gid in gs.all_games():
                if gs.get(gid, "scene") == scene and gs.get(gid, "active"):
                    game_id = gid
                    break

            if game_id is None:
                return

            rules = self.GAME_RULES.get(game_id, "")
            state = gs.get_all(game_id)
            ctx["game_state"] = state

            ctx["system_prompt"] = ctx.get("system_prompt", "") + (
                f"\n\n--- GAME: {game_id.upper()} ---\n"
                f"{rules}\n"
                f"Current state: {json.dumps(state, indent=2)}\n---"
            )
        except Exception as exc:
            logger.debug("GameInterceptor rules pre_call: %s", exc)

    def post_call(self, ctx: ResponseContext) -> None:
        try:
            from engine.mcp.game_mcp import GameSessionInterceptor as _GSI
            _GSI().post_call(ctx)
        except Exception as exc:
            logger.debug("GameInterceptor post_call: %s", exc)
