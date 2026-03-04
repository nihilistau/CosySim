"""Interceptor: AutoResultInjector.

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

class AutoResultInjector(InterceptorBase):
    """
    Pre-call: take results from auto-triggered skills (already stored in
    ``ctx['auto_results']``) and append them as a structured context block
    in the system prompt.
    """
    name     = "auto_results"
    priority = 20

    def pre_call(self, ctx: ResponseContext) -> None:
        auto_results: Dict[str, Any] = ctx.get("auto_results", {})
        if not auto_results:
            return
        lines = []
        for skill_name, result in auto_results.items():
            snippet = str(result)[:300]
            lines.append(f"[{skill_name}] {snippet}")
        block = "\n".join(lines)
        ctx["system_prompt"] = ctx.get("system_prompt", "") + (
            f"\n\n--- Automatic context (from skills) ---\n{block}\n---"
        )
