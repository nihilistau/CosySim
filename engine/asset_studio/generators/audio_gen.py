"""Audio Generator — ambient sound and SFX generation (extensible stub).

Currently generates audio using available local tools (pydub, scipy sine
wave SFX, etc.).  Designed for easy extension to full audio generation
pipelines (AudioCraft, Stable Audio, etc.).
"""
from __future__ import annotations

import logging
import math
import struct
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

_OUTPUT_DIR_KEY = "asset_studio.audio_output_dir"
_DEFAULT_OUTPUT_DIR = "data/asset_studio/audio"

# Ambient tone frequencies for each scene (Hz) — used for fallback tones.
_SCENE_TONES: Dict[str, float] = {
    "penthouse":  220.0,   # A3 — low and warm
    "lounge":   261.6,   # C4 — mellow
    "tavern":   329.6,   # E4 — earthy
    "casino":   440.0,   # A4 — bright
    "gallery":  185.0,   # F#3 — eerie
    "arena":    110.0,   # A2 — deep, ominous
    "realm":    174.6,   # F3 — mystical
    "neoncity": 493.9,   # B4 — sharp cyberpunk
    "phone":    392.0,   # G4 — digital
}


class AudioGenerator:
    """Generate ambient audio and SFX.

    Falls back to synthesised sine-wave tones when external audio
    generation tools are unavailable.
    """

    def __init__(self) -> None:
        """Initialise, ensuring output directory exists."""
        cfg = get_config()
        self._output_dir = Path(cfg.get(_OUTPUT_DIR_KEY, _DEFAULT_OUTPUT_DIR))
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        audio_type: str = "ambient",
        description: str = "",
        scene: str = "",
        duration: float = 5.0,
        sample_rate: int = 44100,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate an audio clip.

        Args:
            audio_type: ambient|sfx|music|loop.
            description: Natural-language description of the sound.
            scene: Scene slug for contextual defaults.
            duration: Clip length in seconds.
            sample_rate: Sample rate Hz.

        Returns:
            Dict with ``url``, ``duration``, ``duration_ms``.
        """
        t_start = time.monotonic()

        try:
            audio_bytes = self._synthesize_tone(
                scene=scene,
                duration=duration,
                sample_rate=sample_rate,
                audio_type=audio_type,
            )

            filename = f"audio_{uuid.uuid4().hex[:12]}.wav"
            out_path = self._output_dir / filename
            self._write_wav(out_path, audio_bytes, sample_rate)

            duration_ms = int((time.monotonic() - t_start) * 1000)

            return {
                "url": f"/asset_studio/audio/{filename}",
                "file_path": str(out_path),
                "duration": duration,
                "sample_rate": sample_rate,
                "audio_type": audio_type,
                "cached": False,
                "duration_ms": duration_ms,
                "note": "Synthesised tone — AudioCraft integration planned",
            }
        except Exception as exc:
            logger.warning("Audio generation failed: %s", exc)
            duration_ms = int((time.monotonic() - t_start) * 1000)
            return {
                "url": "",
                "duration": 0.0,
                "audio_type": audio_type,
                "cached": False,
                "duration_ms": duration_ms,
                "error": str(exc),
            }

    def _synthesize_tone(
        self,
        scene: str,
        duration: float,
        sample_rate: int,
        audio_type: str,
    ) -> bytes:
        """Synthesise a simple sine-wave tone for *scene*.

        Applies an amplitude envelope (fade in/out) to avoid clicks.
        """
        freq = _SCENE_TONES.get(scene, 261.6)

        # SFX uses a higher frequency click/pop.
        if audio_type == "sfx":
            freq = freq * 2

        n_samples = int(sample_rate * duration)
        fade_samples = min(int(sample_rate * 0.1), n_samples // 4)

        samples: List[int] = []
        for i in range(n_samples):
            t = i / sample_rate
            amplitude = 0.3 * math.sin(2 * math.pi * freq * t)

            # Fade in.
            if i < fade_samples:
                amplitude *= i / fade_samples
            # Fade out.
            elif i > n_samples - fade_samples:
                amplitude *= (n_samples - i) / fade_samples

            samples.append(int(amplitude * 32767))

        return struct.pack(f"<{len(samples)}h", *samples)

    @staticmethod
    def _write_wav(path: Path, pcm_bytes: bytes, sample_rate: int) -> None:
        """Write raw 16-bit mono PCM to a WAV file."""
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
