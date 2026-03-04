"""Interceptor: ConversationRecapInterceptor.

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

class ConversationRecapInterceptor(InterceptorBase):
    """
    Tracks recent conversation turns per agent and injects a brief recap
    into the system prompt so agents maintain short-term conversational
    memory.  This prevents the "goldfish effect" where agents forget
    what was just discussed when context windows are large or prompts
    are rebuilt each turn.

    The recap is lightweight (last 4 exchanges max) and fades old entries
    automatically.  Runs at priority 6 (after NaturalMoodDrift at 5,
    before CharacterRegistry at 8) so downstream interceptors see it.
    """
    name     = "conversation_recap"
    priority = 6

    MAX_TURNS = 4      # recent exchanges to keep
    MAX_MSG_LEN = 120  # truncate long messages in recap

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._history: Dict[str, List[Dict[str, str]]] = {}  # conv_key → [{role, text}]

    def _conv_key(self, ctx: ResponseContext) -> str:
        return ctx.get("conversation_id") or f"{ctx.get('scene', 'default')}_{ctx.get('agent_id', 'anon')}"

    def _truncate(self, text: str) -> str:
        if len(text) <= self.MAX_MSG_LEN:
            return text
        return text[:self.MAX_MSG_LEN - 3] + "..."

    def pre_call(self, ctx: ResponseContext) -> None:
        key = self._conv_key(ctx)
        user_msg = ctx.get("user_message") or ctx.get("message", "")

        with self._lock:
            history = self._history.setdefault(key, [])
            # Record the incoming user message
            if user_msg:
                history.append({"role": "user", "text": self._truncate(str(user_msg))})
                # Trim to keep window manageable
                if len(history) > self.MAX_TURNS * 2:
                    self._history[key] = history[-(self.MAX_TURNS * 2):]
                    history = self._history[key]

        if len(history) < 2:
            return  # Not enough history for a recap

        # Build recap from recent exchanges
        recap_lines = []
        for entry in history[-(self.MAX_TURNS * 2):]:
            role = "Player" if entry["role"] == "user" else "You"
            recap_lines.append(f"  {role}: {entry['text']}")

        if recap_lines:
            recap = (
                "\n\n[CONVERSATION RECAP — recent exchanges]\n"
                + "\n".join(recap_lines)
                + "\n[/CONVERSATION RECAP]"
            )
            ctx["system_prompt"] = ctx.get("system_prompt", "") + recap

    def post_call(self, ctx: ResponseContext) -> None:
        """Record the agent's reply for next turn's recap."""
        key = self._conv_key(ctx)
        reply = ctx.get("response") or ctx.get("reply", "")
        if not reply:
            return

        with self._lock:
            history = self._history.setdefault(key, [])
            history.append({"role": "agent", "text": self._truncate(str(reply))})
            if len(history) > self.MAX_TURNS * 2:
                self._history[key] = history[-(self.MAX_TURNS * 2):]
