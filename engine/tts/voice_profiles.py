"""Per-character TTS voice profiles — maps character traits to TTS parameters."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class VoiceProfile:
    character_id: str
    voice_id: str  # TTS voice identifier
    speed: float = 1.0  # 0.5–2.0
    pitch: float = 1.0  # 0.5–2.0
    style: str = "neutral"  # neutral | warm | cold | dramatic | whisper | commanding
    emotion_modulation: bool = True  # allow emotion tags to modify voice
    metadata: Dict[str, Any] = field(default_factory=dict)


# Default voice profiles for known CosySim characters
DEFAULT_PROFILES: Dict[str, VoiceProfile] = {
    "aria": VoiceProfile(
        character_id="aria",
        voice_id="aria",
        speed=0.95,
        pitch=1.05,
        style="warm",
        metadata={"description": "System assistant — warm, measured, slightly ethereal"},
    ),
    "lola": VoiceProfile(
        character_id="lola",
        voice_id="lola",
        speed=1.05,
        pitch=1.1,
        style="warm",
        metadata={"description": "The Penthouse host — sultry, confident, playful"},
    ),
    "viktor": VoiceProfile(
        character_id="viktor",
        voice_id="viktor",
        speed=0.9,
        pitch=0.9,
        style="cold",
        metadata={"description": "The fixer — measured, precise, Eastern European cadence"},
    ),
    "frankie": VoiceProfile(
        character_id="frankie",
        voice_id="frankie",
        speed=1.1,
        pitch=1.0,
        style="dramatic",
        metadata={"description": "The dealer — fast, nervous energy, street smart"},
    ),
    "mira": VoiceProfile(
        character_id="mira",
        voice_id="mira",
        speed=0.85,
        pitch=1.15,
        style="commanding",
        metadata={"description": "The hacker — intense, focused, slight electronic distortion"},
    ),
}

_EMOTION_MODS: Dict[str, Dict[str, Any]] = {
    "angry":   {"speed": 1.2,  "pitch": 0.9,  "style": "dramatic"},
    "sad":     {"speed": 0.85, "pitch": 0.95, "style": "warm"},
    "excited": {"speed": 1.3,  "pitch": 1.1,  "style": "dramatic"},
    "afraid":  {"speed": 1.15, "pitch": 1.05, "style": "whisper"},
    "loving":  {"speed": 0.9,  "pitch": 1.1,  "style": "warm"},
}


class VoiceProfileManager:
    """Manages voice profiles for all characters. Singleton."""

    _instance: Optional["VoiceProfileManager"] = None

    def __init__(self) -> None:
        self._profiles: Dict[str, VoiceProfile] = dict(DEFAULT_PROFILES)
        logger.info("VoiceProfileManager initialised with %d default profiles", len(self._profiles))

    @classmethod
    def get_instance(cls) -> "VoiceProfileManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get(self, character_id: str) -> VoiceProfile:
        """Get voice profile for character. Falls back to neutral default."""
        return self._profiles.get(
            character_id,
            VoiceProfile(character_id=character_id, voice_id="default"),
        )

    def set(self, profile: VoiceProfile) -> None:
        """Store or replace a voice profile."""
        self._profiles[profile.character_id] = profile
        logger.debug("Voice profile set for %s: %s", profile.character_id, profile.style)

    def list_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Return a lightweight summary of all registered profiles."""
        return {
            cid: {
                "voice_id": p.voice_id,
                "speed": p.speed,
                "pitch": p.pitch,
                "style": p.style,
            }
            for cid, p in self._profiles.items()
        }

    def get_tts_params(self, character_id: str, emotion: Optional[str] = None) -> Dict[str, Any]:
        """Get TTS parameters for a character, optionally modulated by emotion.

        Args:
            character_id: Character identifier.
            emotion: Optional emotion name to modulate voice (angry/sad/excited/afraid/loving).

        Returns:
            Dict with keys: voice, speed, pitch, style.
        """
        profile = self.get(character_id)
        params: Dict[str, Any] = {
            "voice": profile.voice_id,
            "speed": profile.speed,
            "pitch": profile.pitch,
            "style": profile.style,
        }
        if emotion and profile.emotion_modulation:
            mods = _EMOTION_MODS.get(emotion.lower())
            if mods:
                params["speed"] = profile.speed * mods["speed"]
                params["pitch"] = profile.pitch * mods.get("pitch", 1.0)
                params["style"] = mods["style"]
        return params

    def reset(self) -> None:
        """Restore factory default profiles."""
        self._profiles = dict(DEFAULT_PROFILES)


def get_voice_profile_manager() -> VoiceProfileManager:
    """Return the singleton VoiceProfileManager."""
    return VoiceProfileManager.get_instance()
