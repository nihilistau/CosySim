"""
tts_profile_skills.py — Per-character TTS voice profile skills

Skill pack: ``tts``

These skills let agents query and configure per-character voice profiles,
including emotion-aware parameter modulation.
"""
from __future__ import annotations

import json

from engine.skills.skill import skill


@skill(
    pack="tts",
    description="Get TTS voice parameters for a character, optionally modulated by emotion.",
    category="COMMUNICATION",
    tags=["tts", "voice", "profile", "character"],
)
def get_character_voice(character_id: str, emotion: str = "") -> str:
    """Return the TTS parameters for *character_id* as a JSON string.

    Args:
        character_id: Character identifier (e.g. 'lola', 'viktor').
        emotion: Optional emotion modifier (angry/sad/excited/afraid/loving).

    Returns:
        JSON string with keys: voice, speed, pitch, style.
    """
    try:
        from engine.tts.voice_profiles import get_voice_profile_manager

        mgr = get_voice_profile_manager()
        params = mgr.get_tts_params(character_id, emotion or None)
        return json.dumps(params)
    except Exception as exc:
        return f"Failed to get voice profile: {exc}"


@skill(
    pack="tts",
    description="Set a custom TTS voice profile for a character.",
    category="COMMUNICATION",
    tags=["tts", "voice", "profile", "cast"],
)
def set_character_voice(
    character_id: str,
    voice_id: str,
    speed: float = 1.0,
    pitch: float = 1.0,
    style: str = "neutral",
) -> str:
    """Save a custom voice profile for a character.

    Args:
        character_id: Character identifier.
        voice_id: TTS voice name.
        speed: Playback speed (0.5–2.0).
        pitch: Voice pitch (0.5–2.0).
        style: Voice style (neutral/warm/cold/dramatic/whisper/commanding).

    Returns:
        Confirmation message.
    """
    try:
        from engine.tts.voice_profiles import VoiceProfile, get_voice_profile_manager

        profile = VoiceProfile(
            character_id=character_id,
            voice_id=voice_id,
            speed=speed,
            pitch=pitch,
            style=style,
        )
        get_voice_profile_manager().set(profile)
        return f"Voice profile set for '{character_id}': voice={voice_id}, speed={speed}, pitch={pitch}, style={style}"
    except Exception as exc:
        return f"Failed to set voice profile: {exc}"


@skill(
    pack="tts",
    description="List all registered character voice profiles.",
    category="COMMUNICATION",
    tags=["tts", "voice", "profile", "list"],
)
def list_voice_profiles() -> str:
    """Return all registered voice profiles as a JSON string.

    Returns:
        JSON object mapping character_id → {voice_id, speed, pitch, style}.
    """
    try:
        from engine.tts.voice_profiles import get_voice_profile_manager

        profiles = get_voice_profile_manager().list_profiles()
        return json.dumps(profiles, indent=2)
    except Exception as exc:
        return f"Failed to list voice profiles: {exc}"
