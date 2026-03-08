"""Interceptor: ActivityLoggerInterceptor.

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

class ActivityLoggerInterceptor(InterceptorBase):
    """
    Post-call: log the completed interaction to the EventChain with
    governance metadata (which interceptors ran, skill manifest name, etc.).
    Also feeds completed interactions into the training DataCollector for
    conversational and tool-dispatch model fine-tuning.
    """
    name     = "activity_logger"
    priority = 90

    def post_call(self, ctx: ResponseContext) -> None:
        chain_id   = ctx.get("chain_id")
        agent_id   = ctx.get("agent_id", "")
        agent_name = ctx.get("agent_name", "?")
        reply      = ctx.get("reply", "")
        if not chain_id or not reply:
            return

        # Log to EventChain
        try:
            from content.simulation.database.events import get_event_chain
            ec = get_event_chain()
            if ec:
                auto_skills = list(ctx.get("auto_results", {}).keys())
                ec.log(
                    "governed_response",
                    actor=agent_name,
                    payload={
                        "scene": ctx.get("scene"),
                        "skills_auto": auto_skills,
                        "game_active": bool(ctx.get("game_state")),
                    },
                    summary=reply[:120],
                    chain_id=chain_id,
                    character_id=agent_id,
                )
        except Exception as exc:
            logger.debug("ActivityLoggerInterceptor EventChain failed: %s", exc)

        # Feed into training DataCollector
        self._collect_training_data(ctx, agent_name, reply)

    def _collect_training_data(
        self, ctx: ResponseContext, agent_name: str, reply: str
    ) -> None:
        """Feed interaction data into the training pipeline."""
        try:
            from training.data_collector import get_data_collector
            collector = get_data_collector()

            user_input = ctx.get("user_input", "")
            system_prompt = ctx.get("system_prompt", "")
            auto_results = ctx.get("auto_results", {})

            # Collect tool dispatch training data for each auto-executed skill
            if auto_results and user_input:
                for skill_name, result in auto_results.items():
                    success = not isinstance(result, Exception)
                    collector.collect_tool_call(
                        user_input=user_input,
                        tool_name=skill_name,
                        params={"agent": agent_name, "scene": ctx.get("scene", "")},
                        success=success,
                    )

            # Collect conversational training data
            if user_input and reply and len(reply) > 20:
                history = ctx.get("history", [])
                if isinstance(history, list):
                    collector.collect_conversation(
                        system_prompt=system_prompt or f"Character: {agent_name}",
                        history=history,
                        response=reply,
                        character_id=ctx.get("agent_id", ""),
                    )
        except Exception as exc:
            logger.debug("ActivityLoggerInterceptor DataCollector failed: %s", exc)
