"""Interceptor: SkillAwarenessInterceptor.

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

class SkillAwarenessInterceptor(InterceptorBase):
    """
    Pre-call: inject a "skills available to you" section into the system prompt
    so the model knows what tools it can call and why.

    Required skills get a strong instruction to call them before replying.
    Optional skills get a suggestion.
    """
    name     = "skill_awareness"
    priority = 30

    def pre_call(self, ctx: ResponseContext) -> None:
        manifest = ctx.get("skill_manifest")
        if manifest is None:
            return

        optional_skills  = manifest.optional_skills()
        required_skills  = manifest.required_skills()

        parts: List[str] = []

        if required_skills:
            names = ", ".join(f"`{s.name}`" for s in required_skills)
            descs = "\n".join(
                f"  • {s.name}: {s.description}" for s in required_skills
            )
            parts.append(
                f"REQUIRED: You MUST call the following tools before answering:\n{descs}\n"
                f"Do not reply until you have called: {names}."
            )

        if optional_skills:
            descs = "\n".join(
                f"  • {s.name}: {s.description}" for s in optional_skills
            )
            parts.append(
                f"AVAILABLE TOOLS (use when relevant):\n{descs}"
            )

        if parts:
            ctx["system_prompt"] = ctx.get("system_prompt", "") + (
                "\n\n--- Skills & Tools ---\n" + "\n\n".join(parts) + "\n---"
            )
