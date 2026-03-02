"""
Tests for engine/tts/voice_profiles.py — VoiceProfileManager and TTS profile skills.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Stub torch and other heavy ML deps before importing engine.tts.*
for _mod in ("torch", "torchaudio", "transformers", "numpy", "soundfile"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import json
import pytest
from unittest.mock import patch

from engine.tts.voice_profiles import (
    VoiceProfile,
    VoiceProfileManager,
    DEFAULT_PROFILES,
    get_voice_profile_manager,
)


# ═══════════════════════════════════════════════════════════════════════
#  VoiceProfile dataclass
# ═══════════════════════════════════════════════════════════════════════

class TestVoiceProfile:
    def test_defaults(self):
        p = VoiceProfile(character_id="x", voice_id="default")
        assert p.speed == 1.0
        assert p.pitch == 1.0
        assert p.style == "neutral"
        assert p.emotion_modulation is True
        assert p.metadata == {}

    def test_custom_values(self):
        p = VoiceProfile(character_id="lola", voice_id="lola", speed=1.1, pitch=1.1, style="warm")
        assert p.speed == 1.1
        assert p.pitch == 1.1
        assert p.style == "warm"


# ═══════════════════════════════════════════════════════════════════════
#  Default profiles
# ═══════════════════════════════════════════════════════════════════════

class TestDefaultProfiles:
    def test_five_default_profiles(self):
        assert len(DEFAULT_PROFILES) == 5

    def test_all_seeded_characters_present(self):
        for char in ("aria", "lola", "viktor", "frankie", "mira"):
            assert char in DEFAULT_PROFILES

    def test_aria_style_warm(self):
        assert DEFAULT_PROFILES["aria"].style == "warm"

    def test_viktor_style_cold(self):
        assert DEFAULT_PROFILES["viktor"].style == "cold"

    def test_mira_style_commanding(self):
        assert DEFAULT_PROFILES["mira"].style == "commanding"

    def test_frankie_style_dramatic(self):
        assert DEFAULT_PROFILES["frankie"].style == "dramatic"

    def test_lola_style_warm(self):
        assert DEFAULT_PROFILES["lola"].style == "warm"


# ═══════════════════════════════════════════════════════════════════════
#  VoiceProfileManager
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def mgr():
    """Fresh VoiceProfileManager (not singleton) for isolation."""
    m = VoiceProfileManager.__new__(VoiceProfileManager)
    m._profiles = dict(DEFAULT_PROFILES)
    return m


class TestVoiceProfileManagerInit:
    def test_initialises_with_five_profiles(self, mgr):
        assert len(mgr._profiles) == 5

    def test_get_instance_returns_same_object(self):
        a = VoiceProfileManager.get_instance()
        b = VoiceProfileManager.get_instance()
        assert a is b

    def test_get_voice_profile_manager_helper(self):
        assert isinstance(get_voice_profile_manager(), VoiceProfileManager)


class TestVoiceProfileManagerGet:
    def test_get_known_character(self, mgr):
        p = mgr.get("lola")
        assert p.character_id == "lola"
        assert p.voice_id == "lola"

    def test_get_viktor(self, mgr):
        p = mgr.get("viktor")
        assert p.style == "cold"

    def test_get_unknown_returns_neutral_default(self, mgr):
        p = mgr.get("ghost")
        assert p.character_id == "ghost"
        assert p.voice_id == "default"
        assert p.style == "neutral"
        assert p.speed == 1.0
        assert p.pitch == 1.0

    def test_get_unknown_does_not_pollute_registry(self, mgr):
        mgr.get("nobody")
        assert "nobody" not in mgr._profiles


class TestVoiceProfileManagerSet:
    def test_set_stores_profile(self, mgr):
        p = VoiceProfile(character_id="new_char", voice_id="v1", speed=1.2, style="cold")
        mgr.set(p)
        assert mgr.get("new_char").voice_id == "v1"

    def test_set_overwrites_existing(self, mgr):
        p = VoiceProfile(character_id="aria", voice_id="aria_v2", style="dramatic")
        mgr.set(p)
        assert mgr.get("aria").style == "dramatic"


class TestVoiceProfileManagerListProfiles:
    def test_list_profiles_returns_dict(self, mgr):
        result = mgr.list_profiles()
        assert isinstance(result, dict)
        assert "aria" in result

    def test_list_profiles_contains_required_keys(self, mgr):
        for cid, info in mgr.list_profiles().items():
            for key in ("voice_id", "speed", "pitch", "style"):
                assert key in info, f"Missing '{key}' for {cid}"

    def test_list_profiles_count(self, mgr):
        assert len(mgr.list_profiles()) == 5


class TestVoiceProfileManagerGetTtsParams:
    def test_returns_required_keys(self, mgr):
        params = mgr.get_tts_params("lola")
        for key in ("voice", "speed", "pitch", "style"):
            assert key in params

    def test_correct_values_for_lola(self, mgr):
        params = mgr.get_tts_params("lola")
        assert params["voice"] == "lola"
        assert params["style"] == "warm"

    def test_no_emotion_returns_base_params(self, mgr):
        params = mgr.get_tts_params("viktor")
        assert params["style"] == "cold"

    def test_angry_emotion_increases_speed(self, mgr):
        base = mgr.get_tts_params("lola")
        angry = mgr.get_tts_params("lola", emotion="angry")
        assert angry["speed"] > base["speed"]
        assert angry["style"] == "dramatic"

    def test_sad_emotion_decreases_speed(self, mgr):
        base = mgr.get_tts_params("lola")
        sad = mgr.get_tts_params("lola", emotion="sad")
        assert sad["speed"] < base["speed"]

    def test_excited_emotion_style_dramatic(self, mgr):
        params = mgr.get_tts_params("aria", emotion="excited")
        assert params["style"] == "dramatic"

    def test_afraid_emotion_style_whisper(self, mgr):
        params = mgr.get_tts_params("aria", emotion="afraid")
        assert params["style"] == "whisper"

    def test_loving_emotion_style_warm(self, mgr):
        params = mgr.get_tts_params("aria", emotion="loving")
        assert params["style"] == "warm"

    def test_unknown_emotion_uses_base_style(self, mgr):
        params = mgr.get_tts_params("viktor", emotion="confused")
        assert params["style"] == "cold"  # unchanged

    def test_emotion_case_insensitive(self, mgr):
        params = mgr.get_tts_params("lola", emotion="ANGRY")
        assert params["style"] == "dramatic"


class TestVoiceProfileManagerReset:
    def test_reset_restores_defaults(self, mgr):
        mgr.set(VoiceProfile(character_id="aria", voice_id="modified", style="cold"))
        mgr.reset()
        assert mgr.get("aria").style == "warm"

    def test_reset_removes_custom_profiles(self, mgr):
        mgr.set(VoiceProfile(character_id="custom_char", voice_id="x"))
        mgr.reset()
        assert "custom_char" not in mgr._profiles


# ═══════════════════════════════════════════════════════════════════════
#  TTS Profile Skills
# ═══════════════════════════════════════════════════════════════════════

class TestTtsProfileSkills:
    def test_get_character_voice_returns_string(self):
        from engine.skills.builtin.tts_profile_skills import get_character_voice
        result = get_character_voice("lola")
        assert isinstance(result, str)

    def test_get_character_voice_is_valid_json(self):
        from engine.skills.builtin.tts_profile_skills import get_character_voice
        result = get_character_voice("lola")
        data = json.loads(result)
        assert "voice" in data

    def test_get_character_voice_with_emotion(self):
        from engine.skills.builtin.tts_profile_skills import get_character_voice
        result = get_character_voice("lola", emotion="angry")
        data = json.loads(result)
        assert data["style"] == "dramatic"

    def test_set_character_voice_returns_string(self):
        from engine.skills.builtin.tts_profile_skills import set_character_voice
        result = set_character_voice("test_npc", "test_voice", 1.1, 0.9, "cold")
        assert isinstance(result, str)
        assert "test_npc" in result

    def test_set_then_get_voice_profile(self):
        from engine.skills.builtin.tts_profile_skills import set_character_voice, get_character_voice
        set_character_voice("temp_npc", "special_voice", 1.3, 1.0, "warm")
        result = get_character_voice("temp_npc")
        data = json.loads(result)
        assert data["voice"] == "special_voice"

    def test_list_voice_profiles_returns_string(self):
        from engine.skills.builtin.tts_profile_skills import list_voice_profiles
        result = list_voice_profiles()
        assert isinstance(result, str)

    def test_list_voice_profiles_contains_known_characters(self):
        from engine.skills.builtin.tts_profile_skills import list_voice_profiles
        result = list_voice_profiles()
        data = json.loads(result)
        assert "aria" in data
        assert "viktor" in data
