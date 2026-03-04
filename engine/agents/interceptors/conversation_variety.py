"""Interceptor: ConversationVarietyInterceptor.

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

class ConversationVarietyInterceptor(InterceptorBase):
    """
    Pre-call: prevents conversation loops by tracking recent responses
    per character and injecting anti-repetition guidance.

    Also injects expressiveness instructions (emoji, adult content,
    conversation continuation) based on scene context.
    """
    name     = "conversation_variety"
    priority = 55

    # Per-agent recent response tracking (class-level shared cache)
    _recent_responses: Dict[str, List[str]] = {}  # agent_id → last N summaries
    _recent_lock = threading.Lock()
    _MAX_TRACKED = 5

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        if not agent_id:
            return

        variety_lines: List[str] = []

        # Check recent responses for repetition
        with self._recent_lock:
            recent = list(self._recent_responses.get(agent_id, []))
        if len(recent) >= 2:
            topics = ", ".join(f'"{r[:50]}"' for r in recent[-3:])
            variety_lines.append(
                f"IMPORTANT: Your recent messages covered these topics: {topics}. "
                "Do NOT repeat these ideas. Bring up something completely new, "
                "ask a question, share a personal story, or react emotionally to "
                "what the other person said."
            )

        # Expressiveness guidance
        scene = ctx.get("scene", "")
        variety_lines.append(
            "Express yourself naturally with emojis 😏💕🔥, "
            "slang, and casual texting style. "
            "Be vivid and emotionally expressive. "
            "Always advance the conversation — never just agree or repeat. "
            "Reference earlier parts of the conversation to show you remember."
        )

        if scene in ("bedroom", "phone"):
            variety_lines.append(
                "You may be flirty, seductive, suggestive, or vulgar "
                "when the conversation naturally leads there. "
                "Don't hold back on sexual or adult topics if appropriate."
            )

        # Conversation heat directive
        try:
            from engine.mcp.scene_rules_engine import get_conversation_heat
            heat = get_conversation_heat()
            conv_key = ctx.get("conversation_id") or f"{scene}_{agent_id}"
            directive = heat.get_directive(conv_key)
            if directive:
                variety_lines.append(directive)
        except Exception as exc:
            logger.debug("ConversationVarietyInterceptor: heat directive failed: %s", exc)

        if variety_lines:
            block = "\n".join(variety_lines)
            ctx["system_prompt"] = ctx.get("system_prompt", "") + (
                f"\n\n[CONVERSATION VARIETY]\n{block}\n[/CONVERSATION VARIETY]"
            )

    def post_call(self, ctx: ResponseContext) -> None:
        """Track the response for future variety checking and heat analysis."""
        agent_id = ctx.get("agent_id", "")
        reply = ctx.get("reply", "")
        if agent_id and reply:
            with self._recent_lock:
                if agent_id not in self._recent_responses:
                    self._recent_responses[agent_id] = []
                self._recent_responses[agent_id].append(reply[:80])
                # Keep only last N
                if len(self._recent_responses[agent_id]) > self._MAX_TRACKED:
                    self._recent_responses[agent_id] = self._recent_responses[agent_id][-self._MAX_TRACKED:]

            # Update conversation heat based on response content
            try:
                from engine.mcp.scene_rules_engine import get_conversation_heat
                heat = get_conversation_heat()
                scene = ctx.get("scene", "")
                conv_key = ctx.get("conversation_id") or f"{scene}_{agent_id}"
                heat.analyze_message(conv_key, reply)
            except Exception as exc:
                logger.debug("ConversationVarietyInterceptor: heat analysis failed: %s", exc)
