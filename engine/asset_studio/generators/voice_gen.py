"""Voice Generator — TTS synthesis with voice design support.

Wraps the TTSManager to generate voice clips for any text input.
Supports voice design editing (description-based Qwen3 voices) and
saves output WAV files into the asset studio output directory.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

_OUTPUT_DIR_KEY = "asset_studio.voice_output_dir"
_DEFAULT_OUTPUT_DIR = "data/asset_studio/voice"


class VoiceGenerator:
    """Generate voice clips via TTS manager.

    Falls back gracefully when TTS backends are unavailable.
    """

    def __init__(self) -> None:
        """Initialise, ensuring output directory exists."""
        cfg = get_config()
        self._output_dir = Path(cfg.get(_OUTPUT_DIR_KEY, _DEFAULT_OUTPUT_DIR))
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        text: str,
        voice: str = "default",
        backend: str = "auto",
        character_id: str = "",
        scene: str = "",
        description: str = "",
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        """Synthesise speech for *text*.

        Args:
            text: Text to synthesise.
            voice: Voice name or character ID.
            backend: TTS backend (auto|piper|orpheus|qwen3).
            character_id: If given, looks up character's voice design.
            scene: Scene context (metadata only).
            description: Custom voice description (Qwen3 style).

        Returns:
            Dict with ``url``, ``duration``, ``backend``, ``cached``,
            ``duration_ms``, ``text``.
        """
        if not text.strip():
            return {"error": "Empty text", "url": ""}

        t_start = time.monotonic()
        output_filename = f"voice_{uuid.uuid4().hex[:12]}.wav"
        output_path = self._output_dir / output_filename

        try:
            from engine.tts.tts_manager import get_tts_manager  # noqa: PLC0415
            from engine.tts.voice_designer import VoiceDesigner  # noqa: PLC0415

            mgr = get_tts_manager()

            # Resolve voice: if character_id given, look up their design.
            effective_voice = voice
            effective_backend = backend

            if character_id and not description:
                try:
                    designer = VoiceDesigner()
                    design = designer.get(character_id)
                    if design:
                        description = design.description
                        effective_backend = "qwen3"
                except Exception as e:
                    logger.debug("[VoiceGen] Voice designer lookup failed for %s (operation=generate): %s", character_id, e)

            result = mgr.synthesize(
                text=text,
                backend=effective_backend,
                voice=effective_voice,
                description=description if description else None,
            )

            # Write WAV file.
            if result.audio_bytes:
                output_path.write_bytes(result.audio_bytes)

            duration_ms = int((time.monotonic() - t_start) * 1000)
            relative_url = f"/asset_studio/voice/{output_filename}"

            return {
                "url": relative_url,
                "file_path": str(output_path),
                "duration": result.duration,
                "backend": result.backend,
                "sample_rate": result.sample_rate,
                "cached": False,
                "duration_ms": duration_ms,
                "text": text,
                "voice": effective_voice,
                "character_id": character_id,
                "scene": scene,
            }

        except Exception as exc:
            logger.warning("Voice generation failed: %s", exc)
            duration_ms = int((time.monotonic() - t_start) * 1000)
            return {
                "url": "",
                "duration": 0.0,
                "backend": backend,
                "cached": False,
                "duration_ms": duration_ms,
                "text": text,
                "error": str(exc),
            }

    def list_voices(self) -> Dict[str, Any]:
        """Return available voices grouped by backend.

        Returns:
            Dict with ``piper``, ``orpheus``, ``qwen3`` keys listing voices.
        """
        voices: Dict[str, Any] = {"piper": [], "orpheus": [], "qwen3": []}
        try:
            from engine.tts.voice_profiles import VOICE_PROFILES  # noqa: PLC0415
            for k, v in VOICE_PROFILES.items():
                backend = v.get("backend", "piper")
                voices.setdefault(backend, []).append({"id": k, **v})
        except Exception as e:
            logger.debug("[VoiceGen] Failed to load voice profiles (operation=list_voices): %s", e)

        try:
            from engine.tts.voice_designer import VoiceDesigner  # noqa: PLC0415
            designer = VoiceDesigner()
            for char_id, design in designer.list_all().items():
                voices["qwen3"].append({
                    "id": char_id,
                    "description": design.description,
                    "model_size": design.model_size,
                })
        except Exception as e:
            logger.debug("[VoiceGen] Failed to load voice designs (operation=list_voices): %s", e)

        return voices

    def save_voice_design(self, character_id: str, description: str, model_size: str = "1.7b") -> bool:
        """Save a voice design for a character.

        Args:
            character_id: Character identifier.
            description: Voice description for Qwen3.
            model_size: Qwen3 model size (0.6b|1.7b).

        Returns:
            ``True`` on success.
        """
        try:
            from engine.tts.voice_designer import VoiceDesigner, VoiceDesign  # noqa: PLC0415
            designer = VoiceDesigner()
            designer.cast(character_id, VoiceDesign(
                description=description,
                model_size=model_size,
            ))
            return True
        except Exception as exc:
            logger.warning("Failed to save voice design: %s", exc)
            return False
