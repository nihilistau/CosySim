"""Interceptor: MoodSyncInterceptor.

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

class MoodSyncInterceptor(InterceptorBase):
    """
    Post-call: read mood data from ``ctx["parsed"]`` (a ``ParsedResponse``)
    and push back to the CharacterRegistry.

    After syncing mood, evaluates threshold rules in the SceneRulesEngine.
    If any triggered rules have stat thresholds now met, their effects
    auto-fire (stat adjustments, directives, narrative entries, etc.).
    This activates the rules engine as an autonomous behavioral governor.

    If ``ctx["parsed"]`` is not populated (legacy path), falls back to
    ``ContentRouter.parse_full()`` on the raw reply.

    The mood tag is already stripped from ``parsed.content``.
    """
    name     = "mood_sync"
    priority = 92

    def post_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        reply    = ctx.get("reply", "")
        if not reply or not agent_id:
            return

        # Use pre-parsed data if available, otherwise parse now
        parsed = ctx.get("parsed")
        if parsed is None:
            from engine.agents.content_router import ContentRouter
            parsed = ContentRouter.parse_full(reply)
            ctx["parsed"] = parsed

        if not parsed.mood:
            return

        # Update reply with clean text (tags already stripped)
        ctx["reply"] = parsed.content

        intensity = parsed.mood_intensity if parsed.mood_intensity is not None else 0.6

        try:
            from engine.mcp.state_coordinator import get_coordinator
            get_coordinator().update(
                agent_id,
                mood=parsed.mood,
                mood_intensity=intensity,
                scene=ctx.get("scene", ""),
                source="mood_sync_interceptor",
            )
            logger.debug(
                "MoodSyncInterceptor: %s → mood=%s (%.0f%%)",
                agent_id, parsed.mood, intensity * 100,
            )
        except Exception as exc:
            logger.debug("MoodSyncInterceptor: registry update failed: %s", exc)

        # ── Auto-evaluate threshold rules ──────────────────────────
        scene = ctx.get("scene", "")
        if scene:
            self._evaluate_threshold_rules(scene, agent_id, ctx)

        # ── Action-based heat bumping ─────────────────────────────
        # Physical/emotional actions detected in tags auto-bump conversation heat
        self._bump_heat_from_actions(parsed, ctx)

    # Heat bump amounts per action keyword
    _ACTION_HEAT: Dict[str, int] = {
        "kiss": 15, "deep_kiss": 20, "neck_kiss": 18,
        "touch": 10, "caress": 12, "cuddle": 8,
        "flirt": 6, "wink": 4, "tease": 7,
        "dance": 5, "whisper": 6, "embrace": 10,
        "undress": 20, "strip": 18, "intimate": 25,
    }

    def _bump_heat_from_actions(
        self, parsed: Any, ctx: ResponseContext,
    ) -> None:
        """Bump ConversationHeat when action tags indicate physical/emotional escalation."""
        actions = getattr(parsed, "actions", None) or []
        if not actions:
            return
        total_bump = 0
        for action in actions:
            action_lower = action.lower().strip()
            for keyword, bump in self._ACTION_HEAT.items():
                if keyword in action_lower:
                    total_bump += bump
                    break
        if total_bump == 0:
            return
        try:
            from engine.mcp.scene_rules_engine import get_conversation_heat
            heat = get_conversation_heat()
            agent_id = ctx.get("agent_id", "")
            scene = ctx.get("scene", "")
            conv_key = ctx.get("conversation_id") or f"{scene}_{agent_id}"
            heat.bump(conv_key, total_bump)
            logger.debug(
                "MoodSyncInterceptor: action heat bump +%d for %s (actions: %s)",
                total_bump, conv_key, actions,
            )
        except Exception as exc:
            logger.debug("MoodSyncInterceptor: action heat bump failed: %s", exc)

    def _evaluate_threshold_rules(
        self, scene: str, agent_id: str, ctx: ResponseContext,
    ) -> None:
        """
        Check if any triggered rules now have their stat thresholds met.
        If so, auto-fire their effects via the SceneRulesEngine.

        This is the bridge that turns passive rules into active governors —
        whenever mood/stats change, we check if that change crosses a
        threshold that should trigger a rule.
        """
        try:
            from engine.mcp.scene_rules_engine import get_rules_engine
            from engine.mcp.scene_state import get_scene_state_manager
            eng = get_rules_engine()
            ssm = get_scene_state_manager()

            # Gather current stats for this character
            stats_obj = ssm.get_stats(agent_id)
            if isinstance(stats_obj, dict):
                stats = stats_obj
            elif stats_obj and hasattr(stats_obj, "to_dict"):
                stats = stats_obj.to_dict()
            else:
                stats = {}

            # Also include mood/energy from registry for hybrid checks
            try:
                from engine.mcp.character_registry import get_character_registry
                reg = get_character_registry()
                rec = reg.get_character(agent_id)
                if rec and rec.state:
                    stats.setdefault("mood_intensity", rec.state.mood_intensity or 0)
                    stats.setdefault("energy", rec.state.energy or 50)
                    stats.setdefault("inhibition", rec.state.inhibition or 50)
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

            if not stats:
                return

            triggered = eng.evaluate_threshold_rules(scene, agent_id, stats)
            for rule_info in triggered:
                rule_id = rule_info["rule_id"]
                result = eng.apply_rule(
                    scene, rule_id,
                    target_ids=[agent_id],
                    issuer="threshold_auto",
                    ctx=dict(ctx) if ctx else None,
                )
                if result.get("ok"):
                    logger.info(
                        "MoodSyncInterceptor: auto-fired rule '%s' for %s in %s "
                        "(stats: %s)",
                        rule_id, agent_id, scene,
                        {k: v for k, v in stats.items()
                         if isinstance(v, (int, float))},
                    )
        except Exception as exc:
            logger.debug("MoodSyncInterceptor: threshold eval failed: %s", exc)
