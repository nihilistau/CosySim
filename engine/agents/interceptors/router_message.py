"""Interceptor: RouterMessageInjector.

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

class RouterMessageInjector(InterceptorBase):
    """
    Pre-call: drain any pending agent-router inbox messages and
    inject them into the user message context so the character
    sees them as additional context to react to.
    """
    name     = "router_messages"
    priority = 10

    def pre_call(self, ctx: ResponseContext) -> None:
        from engine.mcp.comms_framework import get_router
        agent_id = ctx.get("agent_id", "")
        if not agent_id:
            return
        router = get_router()
        pending = router.drain(agent_id)

        # Cross-scene messages via MCPFramework
        try:
            from engine.mcp.framework import get_framework
            cross = get_framework().get_cross_scene_inbox(agent_id)
            if cross:
                for cm in cross:
                    pending.append({
                        "sender":  f"{cm['from']}@{cm['from_scene']}",
                        "message": f"[{cm['type'].upper()}] {cm['message']}",
                    })
        except Exception as exc:
            logger.debug("RouterMessageInjector: cross-scene inbox error: %s", exc)

        # ── Player journey context (always inject, not just with messages) ──
        try:
            prev = get_framework().get_previous_scene()
            if prev:
                current = ctx.get("scene", "")
                if prev != current:
                    ctx["system_prompt"] = ctx.get("system_prompt", "") + (
                        f"\n(The player just came from the {prev} scene.)"
                    )
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        if not pending:
            return
        lines = [f"[incoming from {m['sender']}]: {m['message']}" for m in pending]
        extra = "\n".join(lines)
        ctx["system_prompt"] = ctx.get("system_prompt", "") + (
            f"\n\n--- Messages received from other agents ---\n{extra}\n---"
        )

        logger.debug("RouterMessageInjector: injected %d message(s) for %s", len(pending), agent_id)
