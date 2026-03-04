"""Interceptor: PhoneSceneInterceptor.

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

class PhoneSceneInterceptor(InterceptorBase):
    """
    Pre-call: injects conversation heat (arousal, mood) and stat-driven
    behavioural cues into the phone-scene system prompt so agent texting
    feels authentic and evolves with the conversation.

    Also injects a one-line "current vibe" hint if stats are elevated.
    """
    name     = "phone_scene"
    priority = 15
    applicable_scenes = {"phone"}

    # Vibe hints keyed by (arousal_bucket, openness_bucket)
    _VIBE_HINTS: Dict[tuple, str] = {
        ("high", "high")  : "You are intensely engaged — flirty, forward, a little breathless.",
        ("high", "mid")   : "You feel the heat rising but still hold a hint of playful restraint.",
        ("high", "low")   : "You're aroused but guarded — mixed feelings, simmering tension.",
        ("mid",  "high")  : "You're comfortable and warm, happy to lean into wherever this goes.",
        ("mid",  "mid")   : "You're your usual self — curious, a little flirty, easy.",
        ("mid",  "low")   : "You're present but not open to anything too intense right now.",
        ("low",  "high")  : "You're relaxed, maybe a bit bored, easily amused.",
        ("low",  "mid")   : "You're calm and composed, replying at your own pace.",
        ("low",  "low")   : "You feel a bit flat today — short replies, guarded.",
    }

    @staticmethod
    def _bucket(val: float) -> str:
        if val >= 65:
            return "high"
        if val >= 35:
            return "mid"
        return "low"

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        scene_id = ctx.get("scene_id") or ctx.get("room_id") or "phone"

        try:
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()

            snap = ssm.get_stats(agent_id) if agent_id else None
            narrative_entries = ssm.get_narrative_entries(scene_id, limit=6)
            narrative = [e["event"] for e in narrative_entries]

            lines: List[str] = []

            if snap:
                a_bucket = self._bucket(snap.arousal)
                o_bucket = self._bucket(snap.openness)
                vibe = self._VIBE_HINTS.get((a_bucket, o_bucket), "")
                if vibe:
                    lines.append(f"Current vibe: {vibe}")
                lines.append(
                    f"Your stats: arousal={snap.arousal:.0f}, happiness={snap.happiness:.0f}, "
                    f"openness={snap.openness:.0f}, affection={snap.affection:.0f}"
                )

            if narrative:
                narr_block = " | ".join(narrative[-4:])
                lines.append(f"Recent conversation context: {narr_block}")

            # ── conversation heat (pacing & tone gating) ─────────────────
            try:
                from engine.mcp.scene_rules_engine import get_conversation_heat
                heat = get_conversation_heat()
                conv_key = ctx.get("conversation_id") or f"phone_{agent_id}"
                directive = heat.get_directive(conv_key)
                heat_level = heat.get(conv_key) if hasattr(heat, "get") else 0
                if directive:
                    lines.append(f"[CONVERSATION HEAT: {heat_level:.0f}/100] {directive}")
                    if heat_level < 30:
                        lines.append(
                            "Keep texts light and playful. Build connection through "
                            "curiosity and warmth, not intensity."
                        )
                    elif heat_level >= 80:
                        lines.append(
                            "The texting energy is INTENSE. Be bold, direct, and "
                            "passionate. Match the escalation in your messages."
                        )
            except Exception as exc:
                logger.debug("PhoneSceneInterceptor: heat failed: %s", exc)

            # ── MCP available actions ─────────────────────────────────────
            try:
                from engine.mcp.scene_rules_engine import get_rules_engine
                eng = get_rules_engine()
                if agent_id:
                    snap_for_rules = ssm.get_stats(agent_id) if agent_id else None
                    stats_dict = snap_for_rules.__dict__ if snap_for_rules else {}
                    available = eng.get_available_actions("phone", stats_dict)
                    if available:
                        acts = ", ".join(a["id"] for a in available[:6])
                        lines.append(f"MCP-available actions: {acts}")
            except Exception as exc:
                logger.debug("PhoneSceneInterceptor: MCP actions failed: %s", exc)

            if lines:
                injection = "\n\n[PHONE SCENE CONTEXT]\n" + "\n".join(lines) + "\n[/PHONE SCENE CONTEXT]"
                ctx["system_prompt"] = ctx.get("system_prompt", "") + injection

            # store for downstream
            extra = ctx.setdefault("extra", {})
            extra["scene_snapshot"] = {
                "scene_id"         : scene_id,
                "stats"            : snap.__dict__ if snap else {},
                "recent_narrative" : narrative,
            }

        except Exception as exc:
            logger.debug("PhoneSceneInterceptor pre_call failed: %s", exc)
