"""Interceptor: TTSStyleInterceptor.

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

class TTSStyleInterceptor(InterceptorBase):
    """
    Post-call: attach TTS rendering metadata to ``ctx["tts_meta"]``.

    The metadata is a dict with keys:
    * ``emotion``    — primary emotion label for CosyVoice instruction mode
    * ``speed``      — float multiplier (1.0 = normal)
    * ``style_lock`` — style tag from ``DialogDirectiveInterceptor`` (if any)
    * ``voice_id``   — character voice id from CharacterRegistry (if configured)

    Scene UIs can read ``ctx["tts_meta"]`` after the governor call to drive
    voice synthesis.  Does NOT modify the reply text.
    """
    name     = "tts_style"
    priority = 85

    # Maps mood keyword → CosyVoice-compatible emotion label
    _MOOD_EMOTION: Dict[str, str] = {
        "happy":    "happy",
        "excited":  "happy",
        "sad":      "sad",
        "angry":    "angry",
        "fearful":  "fearful",
        "surprised":"surprised",
        "disgust":  "disgusted",
        "tender":   "tender",
        "romantic": "tender",
        "flirty":   "happy",
        "mischievous": "happy",
        "tired":    "sad",
        "calm":     "neutral",
        "neutral":  "neutral",
    }

    def post_call(self, ctx: ResponseContext) -> None:
        reply     = ctx.get("reply", "")
        agent_id  = ctx.get("agent_id", "")
        scene     = ctx.get("scene", "")
        if not reply:
            return

        # ── Determine emotion from character registry mood ────────────
        emotion = "neutral"
        speed   = 1.0
        voice_id = ""
        try:
            from engine.mcp.character_registry import get_character_registry
            reg     = get_character_registry()
            summary = reg.get_character_summary(agent_id)
            if summary:
                mood      = str(summary.get("mood") or "neutral").lower()
                emotion   = self._MOOD_EMOTION.get(mood, "neutral")
                intensity = float(summary.get("mood_intensity", 0.5))
                # Higher intensity → slightly faster delivery
                speed    = 1.0 + (intensity - 0.5) * 0.2
                voice_id = summary.get("voice_id", "") or ""

            # Fallback: if registry has no voice_id, try voices.yaml by agent_id
            if not voice_id and agent_id:
                try:
                    from engine.config import get_config
                    voices_cfg = get_config().get("voices", {})
                    if isinstance(voices_cfg, dict) and agent_id in voices_cfg:
                        voice_id = agent_id
                except Exception as exc:
                    logger.debug("TTSStyleInterceptor: voice config lookup failed: %s", exc)
        except Exception as exc:
            logger.debug("TTSStyleInterceptor: registry lookup failed: %s", exc)

        # ── Inherit style_lock from DialogDirectiveInterceptor ────────
        style_lock = ctx.get("active_style_lock", "")

        # ── Heuristic: scan reply text for emotion cues ───────────────
        reply_lower = reply.lower()
        for keyword, emo in self._MOOD_EMOTION.items():
            if keyword in reply_lower:
                emotion = emo
                break

        ctx["tts_meta"] = {
            "emotion":    emotion,
            "speed":      round(speed, 2),
            "style_lock": style_lock,
            "voice_id":   voice_id,
            "scene":      scene,
        }
