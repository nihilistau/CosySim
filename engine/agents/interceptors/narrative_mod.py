"""
Narrative Mod Interceptor — injects stage context into agent prompts
=====================================================================

Pre-call: Injects the current narrative stage description and objectives
into the agent's system prompt, guiding the AI to follow the story.

Post-call: (Future) Parse reply for target completion triggers.

Version: v1.51.0 [2026-03-25]
Author:  CosySim Team

CONNECTS: NarrativeModEngine, InterceptorPipeline
CALLED BY: InterceptorPipeline.run_pre(), run_post()
"""
from __future__ import annotations

import logging
from engine.mcp.comms_framework import InterceptorBase, ResponseContext

logger = logging.getLogger(__name__)


class NarrativeModInterceptor(InterceptorBase):
    """Injects active narrative stage context into agent system prompts.

    Priority 15 — runs after identity/scene injection (7-12) but before
    skills (20+), so the agent sees the narrative context when deciding
    which skills to use.
    """

    name = "narrative_mod"
    priority = 15

    def pre_call(self, ctx: ResponseContext) -> None:
        """Inject current stage description + targets into system prompt."""
        try:
            from engine.mcp.narrative_mod import get_narrative_engine

            scene_id = ctx.get("scene", "")
            injection = get_narrative_engine().get_prompt_injection(scene_id)
            if injection:
                ctx["system_prompt"] = ctx.get("system_prompt", "") + f"\n\n{injection}"
        except Exception as exc:
            logger.debug("[NarrativeModInterceptor] pre_call: %s", exc)

    def post_call(self, ctx: ResponseContext) -> None:
        """Check reply for target completion signals (future expansion)."""
        # Future: parse [TARGET_COMPLETE:target_id] tags from reply
        pass
