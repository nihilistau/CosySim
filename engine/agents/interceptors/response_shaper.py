"""Interceptor: ResponseShaperInterceptor.

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

class ResponseShaperInterceptor(InterceptorBase):
    """
    Post-call: trim excessively long replies, strip leaked system
    instructions and LLM token artifacts.
    """
    name     = "response_shaper"
    priority = 80

    # Markers that sometimes leak from system prompts
    _LEAK_MARKERS = [
        "--- Skills", "--- Messages received", "--- Automatic context",
        "--- GAME:", "--- Enhanced memory", "REQUIRED:", "AVAILABLE TOOLS",
        "Stay fully in-character",
    ]

    def post_call(self, ctx: ResponseContext) -> None:
        reply: str = ctx.get("reply", "")
        if not reply:
            return

        # Strip leaked system sections
        for marker in self._LEAK_MARKERS:
            if marker in reply:
                reply = reply[:reply.index(marker)].rstrip()

        # Strip LLM special token artifacts
        from engine.agents.content_router import _RE_TOKEN_ARTIFACTS
        reply = _RE_TOKEN_ARTIFACTS.sub("", reply)

        ctx["reply"] = reply.strip()
