"""Interceptor: GallerySceneInterceptor.

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

class GallerySceneInterceptor(InterceptorBase):
    """
    Pre-call: enriches the gallery curator agent's prompt with artwork context,
    exhibition state, ConversationHeat pacing, and Coordinator mood data.

    The gallery scene uses infer_processed() with streaming callbacks rather
    than the governor path. This interceptor provides the same framework
    context that governor-wrapped scenes get automatically.
    """
    name     = "gallery_scene"
    priority = 15
    applicable_scenes = {"gallery"}

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        if not agent_id:
            return

        lines: List[str] = []

        try:
            # ── Character mood/state ──────────────────────────────
            from engine.mcp.state_coordinator import get_coordinator
            coord = get_coordinator()
            snapshot = coord.get_full_state(agent_id)
            if snapshot:
                mood = snapshot.get("mood", "neutral")
                energy = snapshot.get("energy", 50)
                lines.append(f"Your current mood: {mood} (energy: {energy}%)")
        except Exception as exc:
            # v1.54.0 [2026-03-26] — Upgrade debug→warning with Oracle context
            logger.warning("[GalleryInterceptor] Context enrichment failed (operation=pre_call): %s", exc)

        try:
            # ── Scene narrative ────────────────────────────────────
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()
            narrative = ssm.get_narrative_entries("gallery", limit=5)
            if narrative:
                events = [e["event"] for e in narrative]
                lines.append("Recent gallery events: " + " | ".join(events[-3:]))
        except Exception as exc:
            # v1.54.0 [2026-03-26] — Upgrade debug→warning with Oracle context
            logger.warning("[GalleryInterceptor] Context enrichment failed (operation=pre_call): %s", exc)

        try:
            # ── ConversationHeat pacing ────────────────────────────
            from engine.mcp.scene_rules_engine import get_conversation_heat
            heat = get_conversation_heat()
            conv_key = ctx.get("conversation_id") or f"gallery_{agent_id}"
            directive = heat.get_directive(conv_key)
            if directive:
                lines.append(f"[Conversation pacing] {directive}")
        except Exception as exc:
            # v1.54.0 [2026-03-26] — Upgrade debug→warning with Oracle context
            logger.warning("[GalleryInterceptor] Context enrichment failed (operation=pre_call): %s", exc)

        if lines:
            injection = "\n\n[GALLERY CONTEXT]\n" + "\n".join(lines) + "\n[/GALLERY CONTEXT]"
            ctx["system_prompt"] = ctx.get("system_prompt", "") + injection
