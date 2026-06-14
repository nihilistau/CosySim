"""Interceptor: LoungeSceneInterceptor.

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

class LoungeSceneInterceptor(InterceptorBase):
    """
    Pre-call: enriches Lola's and Viktor's system prompt with the live
    Velvet Lounge MCP state — heat, trust, stage performance, cocktail
    menu, back-room access, and the full set of available MCP actions so
    the LLM knows exactly what is allowed and what is restricted.
    """
    name     = "lounge_scene"
    priority = 15
    applicable_scenes = {"lounge"}

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")

        try:
            from engine.mcp.scene_state   import get_scene_state_manager
            from engine.mcp.scene_rules_engine import get_rules_engine
            from engine.mcp.character_registry import get_character_registry
            from engine.mcp.dialog_system  import get_dialog_system
            from content.scenes.lounge.lounge_mcp import (
                get_all_cocktails, SCENE_ID, LOLA_ID, VIKTOR_ID,
            )

            ssm = get_scene_state_manager()
            eng = get_rules_engine()
            reg = get_character_registry()
            ds  = get_dialog_system()

            # ── Character state ───────────────────────────────────────
            lola_state   = reg.get_state(LOLA_ID)   or {}
            viktor_state = reg.get_state(VIKTOR_ID) or {}
            guest_stats  = ssm.get_stats("guest") if hasattr(ssm, "get_stats") else None
            trust  = int((guest_stats.trust  if guest_stats else 0) or
                         lola_state.get("guest_trust", 10))
            heat   = int(lola_state.get("heat_level", 0))

            # ── Atmosphere ────────────────────────────────────────────
            atm = ssm.get_atmosphere(SCENE_ID) or {}
            atm_line = " · ".join(str(v) for v in atm.values() if v)

            # ── Narrative ─────────────────────────────────────────────
            narrative_entries = ssm.get_narrative_entries(SCENE_ID, limit=5)
            narrative = [e["event"] for e in narrative_entries]

            # ── Active directive ──────────────────────────────────────
            directive = None
            try:
                directive = ds.get_active_directive(agent_id, SCENE_ID)
            except Exception as exc:
                # v1.54.0 [2026-03-26] — Upgrade debug→warning with Oracle context
                logger.warning("[LoungeInterceptor] Directive lookup failed (operation=pre_call): %s", exc)

            # ── Available cocktails this trust level ──────────────────
            cocktails_avail = get_all_cocktails(trust)
            avail_names = ", ".join(
                c["name"] for c in cocktails_avail if not c.get("locked")
            )

            # ── MCP available actions ─────────────────────────────────
            available_actions: List[str] = []
            try:
                stats_dict = guest_stats.__dict__ if guest_stats else {}
                stats_dict["trust"]      = trust
                stats_dict["heat_level"] = heat
                actions = eng.get_available_actions(SCENE_ID, stats_dict)
                available_actions = [a["id"] for a in actions[:8]]
            except Exception as exc:
                # v1.54.0 [2026-03-26] — Upgrade debug→warning with Oracle context
                logger.warning("[LoungeInterceptor] Available actions lookup failed (operation=pre_call): %s", exc)

            # ── Rules summary ─────────────────────────────────────────
            rules_summary = ""
            try:
                rules_summary = eng.get_rules_summary(SCENE_ID)
            except Exception as exc:
                # v1.54.0 [2026-03-26] — Upgrade debug→warning with Oracle context
                logger.warning("[LoungeInterceptor] Rules summary lookup failed (operation=pre_call): %s", exc)

            # ── Cross-agent inbox ─────────────────────────────────────
            cross_note = ""
            try:
                from engine.mcp.framework import get_framework
                fw    = get_framework()
                inbox = fw.get_cross_scene_inbox(agent_id)
                if inbox:
                    msgs = [m.get("message", "") for m in inbox[:2] if m.get("message")]
                    if msgs:
                        cross_note = "Internal message: " + " / ".join(msgs)
            except Exception as exc:
                # v1.54.0 [2026-03-26] — Upgrade debug→warning with Oracle context
                logger.warning("[LoungeInterceptor] Cross-scene inbox failed (operation=pre_call): %s", exc)

            # ── Build injection block ─────────────────────────────────
            lines: List[str] = [
                "Scene: The Velvet Lounge, 1920s underground speakeasy.",
                f"Guest trust level: {trust}/100  |  Heat level: {heat}/100",
            ]

            if atm_line:
                lines.append(f"Atmosphere: {atm_line}")

            if avail_names:
                lines.append(f"Cocktails available at this trust: {avail_names}")

            if available_actions:
                lines.append(f"MCP-available actions: {', '.join(available_actions)}")

            if rules_summary:
                lines.append(f"Active rules: {rules_summary}")

            if directive:
                d_type = getattr(directive, "directive_type", "")
                d_val  = getattr(directive, "value", "")
                if d_type and d_val:
                    lines.append(f"Your current directive [{d_type}]: {d_val}")

            if narrative:
                lines.append("Recent lounge events: " + " | ".join(narrative[-3:]))

            if cross_note:
                lines.append(cross_note)

            if heat >= 65:
                lines.append(
                    "WARNING: heat level is dangerously high. "
                    "Keep things low-key. Do not attract attention."
                )
            elif heat >= 40:
                lines.append("Heat is elevated. Stay measured.")

            # ── ConversationHeat (framework pacing system) ────────
            try:
                from engine.mcp.scene_rules_engine import get_conversation_heat
                conv_heat = get_conversation_heat()
                conv_key = ctx.get("conversation_id") or f"lounge_{agent_id}"
                conv_directive = conv_heat.get_directive(conv_key)
                if conv_directive:
                    lines.append(f"[Conversation pacing] {conv_directive}")
            except Exception as exc:
                # v1.54.0 [2026-03-26] — Upgrade debug→warning with Oracle context
                logger.warning("[LoungeInterceptor] ConversationHeat pacing failed (operation=pre_call): %s", exc)

            injection = "\n\n[LOUNGE MCP CONTEXT]\n" + "\n".join(lines) + "\n[/LOUNGE MCP CONTEXT]"
            ctx["system_prompt"] = ctx.get("system_prompt", "") + injection

            # Stash for downstream interceptors
            extra = ctx.setdefault("extra", {})
            extra["lounge_snapshot"] = {
                "trust": trust, "heat": heat,
                "atmosphere": atm,
                "available_actions": available_actions,
                "directive": {"type": d_type, "value": d_val} if directive else None,
            }

        except Exception as exc:
            logger.debug("LoungeSceneInterceptor pre_call failed: %s", exc)
