"""Interceptor: AmbientEventInterceptor.

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

class AmbientEventInterceptor(InterceptorBase):
    """
    Pre-call: with a configurable probability, injects a random ambient
    micro-event into the system prompt.  This makes scenes feel alive —
    NPCs do things, environments change, small things happen between
    player actions.

    Events are scene-aware: a casino might have "a slot machine pays out
    nearby", while a warzone might have "distant gunfire echoes".

    The interceptor tracks recently used events per scene to avoid
    repetition within a configurable window.
    """
    name     = "ambient_events"
    priority = 17

    # Probability of injecting an ambient event per call (0.0–1.0)
    EVENT_CHANCE = 0.25

    # Per-scene ambient event pools
    _SCENE_EVENTS: Dict[str, List[str]] = {
        "bedroom": [
            "A soft notification chimes on the nightstand phone.",
            "Moonlight shifts through the curtains, casting new shadows.",
            "Music from a neighbor's apartment drifts faintly through the wall.",
            "The scent of the candle changes subtly as it burns lower.",
            "A car passes outside, headlights briefly sweeping across the ceiling.",
        ],
        "phone": [
            "A new trending topic appears in the social feed.",
            "The battery indicator drops a percentage.",
            "A push notification from an unrelated app appears briefly.",
            "The screen brightness auto-adjusts to the ambient light.",
        ],
        "lounge": [
            "A jazz record crackles as it switches to a new track.",
            "Someone at a distant table laughs quietly.",
            "The bartender polishes a glass with practiced ease.",
            "Cigarette smoke curls through the amber light.",
            "A new patron slips through the velvet curtain.",
        ],
        "gallery": [
            "A spotlight flickers briefly on a nearby painting.",
            "Another visitor pauses at an adjacent exhibit, murmuring appreciation.",
            "The gallery's ambient music transitions to a new piece.",
            "Footsteps echo from the adjacent wing.",
        ],
        "casino": [
            "A slot machine nearby erupts in flashing lights and coins.",
            "The roulette wheel in the corner spins with a satisfying hum.",
            "A dealer at the next table shuffles cards with a crisp snap.",
            "Someone at the bar orders champagne with a confident wave.",
            "The pit boss strolls past, eyes scanning the floor.",
        ],
        "warzone": [
            "Distant artillery rumbles like thunder on the horizon.",
            "A radio crackles with a garbled transmission from another squad.",
            "Wind carries the acrid smell of smoke across the position.",
            "A stray dog trots through the rubble, pausing to sniff.",
            "Overhead, a drone buzzes faintly before disappearing from sight.",
        ],
        "realm": [
            "A bird of prey circles high above the treeline.",
            "The wind carries a faint melody from a distant village.",
            "Leaves rustle as something small scurries through the underbrush.",
            "Storm clouds gather on the far horizon.",
            "A merchant's cart creaks along a nearby path.",
        ],
        "neon_city": [
            "A holographic billboard flickers and changes to a new ad.",
            "A delivery drone whirs past at street level.",
            "Neon puddles ripple as someone splashes through them.",
            "A street vendor calls out, hawking synthetic food.",
            "The hum of the city's power grid surges momentarily.",
        ],
        "coders_room": [
            "A compile notification pings on a nearby monitor.",
            "The server rack fans spin up briefly then settle.",
            "Someone's mechanical keyboard clacks rhythmically in the background.",
            "A coffee machine gurgles to life in the corner.",
        ],
        "heist": [
            "A security camera rotates to a new angle.",
            "Footsteps echo in the corridor — a guard on patrol.",
            "The building's ventilation system hums steadily.",
            "A radio transmission crackles from the security office.",
            "An elevator dings on a floor above.",
        ],
    }

    # Generic fallback events for unknown scenes
    _GENERIC_EVENTS = [
        "The ambient lighting shifts subtly.",
        "A faint sound carries from somewhere nearby.",
        "The atmosphere seems to change imperceptibly.",
        "Time passes quietly for a moment.",
    ]

    def __init__(self) -> None:
        self._recent: Dict[str, List[str]] = {}  # scene -> recent events
        self._recent_limit = 3
        import random
        self._rng = random

    def pre_call(self, ctx: ResponseContext) -> None:
        if self._rng.random() > self.EVENT_CHANCE:
            return

        scene = ctx.get("scene", "")
        if not scene:
            return

        pool = self._SCENE_EVENTS.get(scene, self._GENERIC_EVENTS)
        recent = self._recent.get(scene, [])
        available = [e for e in pool if e not in recent]
        if not available:
            self._recent[scene] = []
            available = pool

        if not available:
            return

        event = self._rng.choice(available)
        recent.append(event)
        if len(recent) > self._recent_limit:
            recent.pop(0)
        self._recent[scene] = recent

        ctx["system_prompt"] = ctx.get("system_prompt", "") + (
            f"\n\n[AMBIENT] {event} [/AMBIENT]"
        )
