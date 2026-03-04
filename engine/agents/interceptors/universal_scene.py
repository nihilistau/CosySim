"""Interceptor: UniversalSceneInterceptor.

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
from engine.agents.interceptors.cache import SCENES_WITH_DEDICATED_INTERCEPTOR as _SCENES_WITH_DEDICATED_INTERCEPTOR  # noqa: E501

logger = logging.getLogger(__name__)

class UniversalSceneInterceptor(InterceptorBase):
    """
    Catch-all scene interceptor for scenes without a dedicated one
    (Casino, Warzone, Realm, NeonCity, Coders Room, Heist).

    Injects: scene descriptor, character mood/state, scene narrative,
    ConversationHeat pacing, available MCP actions, and player journey
    context.  Runs at priority 16 (just after the dedicated scene
    interceptors at 15) so it doesn't conflict.

    This raises scene-specific interceptor coverage from 4/10 to 10/10.
    """
    name     = "universal_scene"
    priority = 16

    # Thematic descriptors help agents stay in-world
    _SCENE_DESCRIPTORS: Dict[str, str] = {
        "casino": (
            "Setting: The Grand Casino — opulent, high-stakes gambling floor. "
            "Glittering chandeliers, velvet tables, the rush of risk and reward."
        ),
        "warzone": (
            "Setting: Active combat zone. Tactical operations, squad leadership, "
            "survival under fire. Tension is constant, decisions are life-or-death."
        ),
        "realm": (
            "Setting: Fantasy realm — medieval world of magic, quests, and adventure. "
            "Ancient forests, mystical creatures, sword and sorcery."
        ),
        "neon_city": (
            "Setting: Neon City — cyberpunk metropolis. Neon-drenched streets, "
            "corporate intrigue, hackers, augmented reality, rain-slicked alleys."
        ),
        "coders_room": (
            "Setting: The Coder's Room — a tech workspace buzzing with creativity. "
            "Multiple monitors, whiteboards, coffee, collaborative problem-solving."
        ),
        "heist": (
            "Setting: Active heist operation. Precision planning, stealth execution, "
            "split-second decisions. Every move matters, every second counts."
        ),
    }

    def pre_call(self, ctx: ResponseContext) -> None:
        scene = ctx.get("scene", "")
        if not scene or scene in _SCENES_WITH_DEDICATED_INTERCEPTOR:
            return

        agent_id = ctx.get("agent_id", "")
        lines: List[str] = []

        # ── Scene descriptor (thematic context) ───────────────────
        descriptor = self._SCENE_DESCRIPTORS.get(scene)
        if descriptor:
            lines.append(descriptor)

        # ── Character mood/state via Coordinator ──────────────────
        try:
            from engine.mcp.state_coordinator import get_coordinator
            coord = get_coordinator()
            snapshot = coord.get_full_state(agent_id)
            if snapshot:
                mood = snapshot.get("mood", "neutral")
                energy = snapshot.get("energy", 50)
                lines.append(f"Your current mood: {mood} (energy: {energy}%)")
                extra_fields = []
                for k in ("arousal", "inhibition", "trust"):
                    v = snapshot.get(k)
                    if v is not None:
                        extra_fields.append(f"{k}={v}")
                if extra_fields:
                    lines.append(f"State: {', '.join(extra_fields)}")
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        # ── Scene narrative ───────────────────────────────────────
        try:
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()
            narrative = ssm.get_narrative_entries(scene, limit=5)
            if narrative:
                events = [e["event"] for e in narrative]
                lines.append("Recent events: " + " | ".join(events[-3:]))
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        # ── Scene atmosphere ──────────────────────────────────────
        try:
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()
            atm = ssm.get_atmosphere(scene) or {}
            atm_str = " · ".join(str(v) for v in atm.values() if v)
            if atm_str:
                lines.append(f"Atmosphere: {atm_str}")
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        # ── ConversationHeat pacing ───────────────────────────────
        try:
            from engine.mcp.scene_rules_engine import get_conversation_heat
            heat = get_conversation_heat()
            conv_key = ctx.get("conversation_id") or f"{scene}_{agent_id}"
            directive = heat.get_directive(conv_key)
            if directive:
                lines.append(f"[Conversation pacing] {directive}")
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        # ── Available MCP actions ─────────────────────────────────
        try:
            from engine.mcp.scene_rules_engine import get_rules_engine
            eng = get_rules_engine()
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()
            stats = ssm.get_stats(agent_id)
            stats_dict = stats.__dict__ if stats and hasattr(stats, "__dict__") else {}
            actions = eng.get_available_actions(scene, stats_dict)
            if actions:
                action_names = [a["id"] for a in actions[:6]]
                lines.append(f"Available actions: {', '.join(action_names)}")
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        if lines:
            tag = scene.upper().replace("_", " ")
            injection = f"\n\n[{tag} CONTEXT]\n" + "\n".join(lines) + f"\n[/{tag} CONTEXT]"
            ctx["system_prompt"] = ctx.get("system_prompt", "") + injection
