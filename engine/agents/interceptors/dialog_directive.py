"""Interceptor: DialogDirectiveInterceptor.

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

class DialogDirectiveInterceptor(InterceptorBase):
    """
    Runs between CharacterRegistryInterceptor and scene interceptors (priority 12).

    pre_call
    --------
    - Injects ``must_include`` fragments and ``style_lock`` style instructions
      into the system prompt so the model naturally incorporates them.
    - Records any active style_lock in ctx so ResponseShaperInterceptor can
      reference it.

    post_call
    ---------
    - Checks if a ``must_include`` directive is active; if the fragment is
      missing from the final reply it is appended gracefully.
    - Ticks the DialogSystem conversation state (increments turn counter,
      decrements directive turns).
    """
    name     = "dialog_directive"
    priority = 12

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        scene    = ctx.get("scene", "")
        if not agent_id:
            return

        try:
            from engine.mcp.dialog_system import get_dialog_system
            ds = get_dialog_system()
            directive = ds.get_active_directive(agent_id, scene)
            if not directive:
                return

            dtype = directive.get("directive_type", "")
            value = directive.get("value", "")

            if dtype == "must_include" and value:
                ctx.setdefault("dialog_must_include", []).append(value)
                ctx["system_prompt"] = (
                    ctx.get("system_prompt", "") +
                    f"\n\n[DIRECTIVE] Your response MUST naturally include or reference: \"{value}\". "
                    f"Work it in organically — do not quote it verbatim."
                )

            elif dtype == "style_lock" and value:
                from engine.mcp.dialog_system import SpeechStyle, _STYLE_INSTRUCTIONS
                instr = _STYLE_INSTRUCTIONS.get(value, "")
                if instr:
                    ctx["system_prompt"] = (
                        ctx.get("system_prompt", "") +
                        f"\n\n[STYLE LOCK] Respond in this style for this turn: {value.upper()} — {instr}"
                    )
                ctx["active_style_lock"] = value

            elif dtype == "topic_steer" and value:
                ctx["system_prompt"] = (
                    ctx.get("system_prompt", "") +
                    f"\n\n[DIRECTIVE] Steer the conversation toward this topic: {value}"
                )

            elif dtype == "mood_set" and value:
                ctx["system_prompt"] = (
                    ctx.get("system_prompt", "") +
                    f"\n\n[DIRECTIVE] Your mood and tone for this turn: {value}"
                )

        except Exception as exc:
            logger.debug("DialogDirectiveInterceptor pre_call failed: %s", exc)

    def post_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        scene    = ctx.get("scene", "")
        if not agent_id:
            return

        # ── Enforce must_include fragments ───────────────────────────
        must_list = ctx.get("dialog_must_include", [])
        reply     = ctx.get("reply", "")
        if must_list and reply:
            for fragment in must_list:
                if fragment.lower() not in reply.lower():
                    # Append gracefully
                    ctx["reply"] = reply.rstrip() + f"  ({fragment})"
                    reply = ctx["reply"]

        # ── Tick conversation state + framework consequence chains ────────
        try:
            from engine.mcp.dialog_system import get_dialog_system
            ds = get_dialog_system()
            ds.tick(agent_id, scene)
        except Exception as exc:
            logger.debug("DialogDirectiveInterceptor post_call tick failed: %s", exc)

        try:
            from engine.mcp.framework import get_framework
            fired = get_framework().tick(scene)
            if fired:
                for item in fired:
                    logger.debug(
                        "DialogDirectiveInterceptor: consequence fired: %s",
                        item.get("consequence_id")
                    )
                ctx.setdefault("fired_consequences", []).extend(fired)
        except Exception as exc:
            logger.debug("DialogDirectiveInterceptor framework tick failed: %s", exc)
