"""Interceptor: RelationshipContextInterceptor.

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

class RelationshipContextInterceptor(InterceptorBase):
    """
    Pre-call interceptor that adds a one-line relationship note to the
    agent's system prompt, e.g.:
      "Your relationship with player: 0.65 (friendly). Act accordingly."

    Priority 9 — runs after CharacterRegistryInterceptor (8) so the
    character identity is already present.
    """
    name     = "relationship_context"
    priority = 9

    def pre_call(self, ctx: Dict[str, Any]) -> None:
        agent_id = ctx.get("agent_id", "")
        # Determine the "other" character — prefer explicit field, fall back to "player"
        other_id = ctx.get("interlocutor_id", "") or ctx.get("user_id", "") or "player"
        if not agent_id or not other_id:
            return
        try:
            from engine.agents.character_memory import get_character_memory
            mem   = get_character_memory(agent_id)
            score = mem.get_relationship(other_id)
            label = mem.score_label(score)
            note  = (
                f"\nYour relationship with {other_id}: {score:.2f} ({label}). "
                "Act accordingly."
            )
            ctx["system_prompt"] = ctx.get("system_prompt", "") + note
        except Exception as exc:
            logger.debug("RelationshipContextInterceptor: %s", exc)
