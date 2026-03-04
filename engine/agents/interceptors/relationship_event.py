"""Interceptor: RelationshipEventInterceptor.

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

class RelationshipEventInterceptor(InterceptorBase):
    """
    Post-call interceptor that detects relationship-significant events
    in agent replies and applies temporary buffs via the StateCoordinator.

    Buffs stack, expire independently, and reverse cleanly.
    """
    name     = "relationship_event"
    priority = 93

    # Keyword → buff definition: (buff_id_suffix, stat_deltas, duration_secs)
    _INTERACTION_BUFFS: Dict[str, tuple] = {
        # Affectionate
        "cuddle":    ("warmth",   {"affection": 8, "arousal": 3, "trust": 2}, 300),
        "hug":       ("warmth",   {"affection": 5, "trust": 2}, 180),
        "kiss":      ("kiss",     {"affection": 10, "arousal": 8, "trust": 3}, 240),
        "caress":    ("caress",   {"affection": 6, "arousal": 10}, 200),
        "massage":   ("massage",  {"arousal": 12, "affection": 4}, 300),
        # Intimate
        "moan":      ("pleasure", {"arousal": 15, "affection": 5}, 180),
        "orgasm":    ("climax",   {"arousal": 20, "affection": 12, "trust": 5}, 300),
        "thrust":    ("sex_act",  {"arousal": 18, "affection": 3}, 180),
        "lick":      ("oral",     {"arousal": 14, "affection": 4}, 180),
        "suck":      ("oral",     {"arousal": 16, "affection": 3}, 180),
        "penetrat":  ("sex_act",  {"arousal": 20, "affection": 5, "trust": 3}, 240),
        "ride":      ("sex_act",  {"arousal": 18, "affection": 5}, 200),
        "spank":     ("rough",    {"arousal": 12, "affection": -2}, 120),
        # Social
        "compliment":("flattered",{"affection": 4, "trust": 3}, 120),
        "laugh":     ("joy",      {"affection": 3}, 90),
        "flirt":     ("flirty",   {"arousal": 5, "affection": 4}, 120),
        "tease":     ("teased",   {"arousal": 4, "affection": 2}, 90),
        "wink":      ("flirty",   {"arousal": 3, "affection": 2}, 60),
        # Negative
        "argue":     ("tension",  {"affection": -6, "trust": -4, "anger": 10}, 300),
        "insult":    ("hurt",     {"affection": -10, "trust": -8, "anger": 15}, 600),
        "yell":      ("shaken",   {"affection": -5, "trust": -3, "anger": 12}, 240),
        "cry":       ("sympathy", {"affection": 3, "trust": 2}, 180),
        "apologize": ("mending",  {"affection": 4, "trust": 5, "anger": -8}, 300),
    }

    # Don't fire more than once per interaction cycle for the same buff type
    _COOLDOWN_SECS = 10.0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last_fired: Dict[str, float] = {}  # "agent:buff_id" → timestamp

    _KEYWORD_TAGS: Dict[str, str] = {
        "cuddle": "affectionate", "hug": "affectionate", "caress": "affectionate",
        "kiss": "romantic", "flirt": "flirtatious", "wink": "flirtatious",
        "tease": "playful", "laugh": "fun-loving",
        "moan": "passionate", "orgasm": "passionate", "thrust": "daring",
        "compliment": "charming", "apologize": "empathetic",
        "argue": "confrontational", "insult": "hostile", "yell": "aggressive",
        "cry": "vulnerable", "massage": "caring", "ride": "daring",
    }

    @classmethod
    def _keyword_to_tag(cls, keyword: str) -> str:
        """Map an interaction keyword to a behavioral tag."""
        return cls._KEYWORD_TAGS.get(keyword, "")

    def post_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        reply = ctx.get("reply", "")
        if not reply or not agent_id:
            return

        reply_lower = reply.lower()
        now = time.time()
        applied = []

        for keyword, (buff_suffix, deltas, duration) in self._INTERACTION_BUFFS.items():
            if keyword in reply_lower:
                cooldown_key = f"{agent_id}:{buff_suffix}"
                last = self._last_fired.get(cooldown_key, 0)
                if now - last < self._COOLDOWN_SECS:
                    continue

                try:
                    from engine.mcp.state_coordinator import get_coordinator
                    coord = get_coordinator()
                    buff_id = f"rel_{buff_suffix}_{int(now) % 10000}"
                    coord.add_buff(
                        agent_id, buff_id, dict(deltas), duration,
                        source=f"relationship_event:{keyword}",
                    )
                    # Also add behavioral tag based on the keyword category
                    tag = self._keyword_to_tag(keyword)
                    if tag:
                        coord.add_tag(agent_id, tag, strength=0.15)
                    self._last_fired[cooldown_key] = now
                    applied.append(f"{keyword}→{buff_suffix}")
                except Exception as exc:
                    logger.debug("RelationshipEventInterceptor: buff failed: %s", exc)

        if applied:
            logger.info(
                "RelationshipEventInterceptor: %s buffs applied to %s: %s",
                len(applied), agent_id, ", ".join(applied[:5]),
            )
