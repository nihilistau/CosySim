"""
Voice Designer — Character voice casting and design registry

Each character gets a ``VoiceDesign`` that describes their vocal identity.
Qwen3-TTS uses these descriptions to generate consistent, characterful speech.

The ``CASTING_OFFICE`` is a registry mapping character IDs to voice designs,
persisted to ``config/voices.yaml``.

Usage::

    from engine.tts.voice_designer import VoiceDesigner, VoiceDesign

    designer = VoiceDesigner()
    designer.cast("luna", VoiceDesign(
        description="A warm, playful female voice with a slight vocal fry...",
        model_size="1.7b",
    ))
    design = designer.get("luna")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_VOICES_FILE = _PROJECT_ROOT / "config" / "voices.yaml"


@dataclass
class VoiceDesign:
    """
    A character's vocal identity for TTS generation.

    Attributes:
        description: Natural-language voice description that triggers
            acoustic features in Qwen3-TTS (pitch, pace, rasp, warmth, etc.).
        model_size: Which Qwen3 model to use — ``"0.6b"`` for simple/fast
            voices (AI, narrator), ``"1.7b"`` for complex emotional voices.
        reference_audio: Optional path to a WAV clip for zero-shot cloning.
        tags: Searchable tags (e.g. ``["female", "young", "playful"]``).
    """
    description: str = "A clear, natural speaking voice."
    model_size: str = "1.7b"
    reference_audio: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> VoiceDesign:
        return cls(
            description=data.get("description", "A clear, natural speaking voice."),
            model_size=data.get("model_size", "1.7b"),
            reference_audio=data.get("reference_audio"),
            tags=data.get("tags", []),
        )


# ── Built-in voice presets ─────────────────────────────────────────────

VOICE_PRESETS: Dict[str, VoiceDesign] = {
    "flirty_female": VoiceDesign(
        description=(
            "A youthful female voice, mid-range pitch, characterized by a warm, "
            "playful cadence. Includes slight vocal fry at the end of sentences "
            "and a breathy, intimate quality. Speaks with a subtle smirk."
        ),
        model_size="1.7b",
        tags=["female", "young", "flirty", "playful"],
    ),
    "confident_male": VoiceDesign(
        description=(
            "A steady, mature male voice with a deep baritone resonance. "
            "The tone is confident and warm, with a natural weight and smooth "
            "delivery. Slight roughness adds character."
        ),
        model_size="1.7b",
        tags=["male", "mature", "confident"],
    ),
    "ai_narrator": VoiceDesign(
        description=(
            "A high-fidelity female voice, perfectly clear and articulate. "
            "The delivery is rhythmic and measured. Includes pristine clarity "
            "and professional broadcast quality."
        ),
        model_size="0.6b",
        tags=["female", "ai", "narrator", "clear"],
    ),
    "whispery_female": VoiceDesign(
        description=(
            "A soft, intimate female whisper-voice. Low volume, breathy, "
            "with close-mic warmth. Speaks slowly and deliberately, as if "
            "sharing a secret. Gentle sighs between phrases."
        ),
        model_size="1.7b",
        tags=["female", "whisper", "intimate", "soft"],
    ),
    "energetic_young": VoiceDesign(
        description=(
            "A youthful, energetic voice with fast-paced speech and a bright, "
            "casual cadence. High energy, slight vocal fry, sharp and clever "
            "pronunciation with enthusiasm."
        ),
        model_size="1.7b",
        tags=["young", "energetic", "fast"],
    ),
    "zero_shot": VoiceDesign(
        description="Zero-shot voice — uses reference audio for cloning.",
        model_size="1.7b",
        tags=["clone", "zero-shot"],
    ),
}


class VoiceDesigner:
    """
    Registry for character voice designs.

    Persists the casting office to ``config/voices.yaml`` so character
    voices remain consistent across sessions.
    """

    def __init__(self, voices_file: Optional[Path] = None):
        self._file = voices_file or _VOICES_FILE
        self._registry: Dict[str, VoiceDesign] = {}
        self._load()

    # ── Public API ─────────────────────────────────────────────────

    def cast(self, character_id: str, design: VoiceDesign) -> None:
        """Assign a voice design to a character and save."""
        self._registry[character_id] = design
        self._save()
        logger.info("Voice cast for %s: %s (%s)", character_id, design.model_size, design.tags)

    def get(self, character_id: str) -> VoiceDesign:
        """Get a character's voice design, or a sensible default."""
        return self._registry.get(character_id, VOICE_PRESETS["flirty_female"])

    def remove(self, character_id: str) -> bool:
        """Remove a character's voice design."""
        if character_id in self._registry:
            del self._registry[character_id]
            self._save()
            return True
        return False

    def list_characters(self) -> List[str]:
        """List all characters with assigned voice designs."""
        return list(self._registry.keys())

    def list_presets(self) -> Dict[str, VoiceDesign]:
        """Return all built-in voice presets."""
        return dict(VOICE_PRESETS)

    def cast_from_preset(self, character_id: str, preset_name: str) -> bool:
        """Assign a built-in preset to a character."""
        if preset_name in VOICE_PRESETS:
            self.cast(character_id, VOICE_PRESETS[preset_name])
            return True
        return False

    def get_all(self) -> Dict[str, VoiceDesign]:
        """Return the full casting office registry."""
        return dict(self._registry)

    # ── Persistence ────────────────────────────────────────────────

    def _load(self) -> None:
        """Load voice designs from YAML file."""
        if not self._file.exists():
            return
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for char_id, design_data in data.items():
                self._registry[char_id] = VoiceDesign.from_dict(design_data)
            logger.info("Loaded %d voice designs from %s", len(self._registry), self._file)
        except Exception as e:
            logger.warning("Failed to load voices: %s", e)

    def _save(self) -> None:
        """Save voice designs to YAML file."""
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            data = {cid: d.to_dict() for cid, d in self._registry.items()}
            with open(self._file, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        except Exception as e:
            logger.warning("Failed to save voices: %s", e)


# ── Module singleton ───────────────────────────────────────────────────

_designer_instance: Optional[VoiceDesigner] = None


def get_voice_designer() -> VoiceDesigner:
    """Return the global VoiceDesigner singleton."""
    global _designer_instance
    if _designer_instance is None:
        _designer_instance = VoiceDesigner()
    return _designer_instance
