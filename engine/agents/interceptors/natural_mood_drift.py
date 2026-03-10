"""Interceptor: NaturalMoodDriftInterceptor.

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

class NaturalMoodDriftInterceptor(InterceptorBase):
    """
    Pre-call: apply natural stat drift and inject micro-behavioral cues.

    Instead of characters having static moods until an event changes them,
    this interceptor models natural emotional drift:
    - High arousal decays slowly toward baseline
    - Tiredness accumulates with each interaction
    - Happiness regresses toward a personality-specific mean
    - The agent receives a one-line "inner thought" that reflects these shifts

    Runs at priority 5 (before CharacterRegistry at 8) so the drift
    is visible to all downstream interceptors.
    """
    name     = "natural_mood_drift"
    priority = 5
    applicable_scenes = {"penthouse", "phone", "lounge", "gallery", "warzone",
                         "casino", "heist", "realm", "neoncity", "coders"}

    # Per-stat drift rates (delta per call, toward baseline)
    # Kept deliberately slow — emotions should shift gradually, not abruptly
    _DRIFT = {
        "arousal":      -1.0,   # slowly cools (was -2.0)
        "tiredness":     0.5,   # slowly accumulates (was 1.0)
        "happiness":    -0.3,   # mild regression to mean (was -0.5)
        "anger":        -1.5,   # anger fades (was -3.0)
        "fear":         -1.0,   # fear dissipates (was -2.0)
        "drunkenness":  -0.5,   # slowly sobers up (was -1.0)
        "affection":    -0.2,   # affection barely drifts
    }

    _INNER_THOUGHTS = {
        "cooling":    "You feel the intensity fading a little — still present, but settling.",
        "tired":      "A gentle wave of tiredness washes over you.",
        "mellowing":  "Your mood softens slightly, evening out.",
        "sobering":   "The buzz is wearing off, edges sharpening.",
        "calming":    "The tension eases. Your breathing slows.",
    }

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        if not agent_id:
            return

        try:
            from engine.mcp.state_coordinator import get_coordinator
            coord = get_coordinator()
            state = coord.get_full_state(agent_id)
            if not state:
                return

            # Apply drift — only nudge stats that are away from baseline
            drifts_applied = {}
            for stat, rate in self._DRIFT.items():
                val = state.get(stat, 50.0)
                if stat == "tiredness":
                    if val < 90:
                        drifts_applied[stat] = rate
                elif val > 55 or val < 45:  # outside neutral zone
                    drifts_applied[stat] = rate

            if drifts_applied:
                coord.update(agent_id, source="mood_drift", **drifts_applied)

            # Sweep expired buffs (piggyback on drift — runs every call)
            coord.sweep_all_expired_buffs()
            # Decay behavioral tags (very slow — only removes dead tags)
            coord.sweep_all_tags()

            # Pick the most relevant inner thought
            thought = None
            arousal = state.get("arousal", 50)
            tiredness = state.get("tiredness", 30)
            anger = state.get("anger", 0)
            drunkenness = state.get("drunkenness", 0)

            if arousal > 70:
                thought = self._INNER_THOUGHTS["cooling"]
            elif anger > 40:
                thought = self._INNER_THOUGHTS["calming"]
            elif tiredness > 60:
                thought = self._INNER_THOUGHTS["tired"]
            elif drunkenness > 30:
                thought = self._INNER_THOUGHTS["sobering"]
            elif any(v > 60 for k, v in state.items() if k in self._DRIFT and isinstance(v, (int, float))):
                thought = self._INNER_THOUGHTS["mellowing"]

            if thought:
                ctx["system_prompt"] = ctx.get("system_prompt", "") + f"\n\n[Inner feeling: {thought}]"

        except Exception as exc:
            logger.debug("NaturalMoodDriftInterceptor: %s", exc)
