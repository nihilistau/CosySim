"""Interceptor: PersonalityGuardInterceptor.

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

class PersonalityGuardInterceptor(InterceptorBase):
    """
    Pre-call: append in-character reminders based on the character's
    personality traits and the interaction policy's required tone.
    """
    name     = "personality_guard"
    priority = 50

    def pre_call(self, ctx: ResponseContext) -> None:
        policy: Any = ctx.get("policy")
        if policy is None:
            return

        reminders: List[str] = []

        if policy.enforce_in_character:
            reminders.append("Stay fully in-character at all times.")

        if policy.required_tone:
            reminders.append(f"Your tone should be: {policy.required_tone}.")

        if policy.forbidden_topics:
            topics = ", ".join(policy.forbidden_topics)
            reminders.append(f"Never discuss: {topics}.")

        if policy.append_to_system:
            reminders.append(policy.append_to_system)

        if reminders:
            ctx["system_prompt"] = ctx.get("system_prompt", "") + (
                "\n\n" + "  ".join(reminders)
            )
