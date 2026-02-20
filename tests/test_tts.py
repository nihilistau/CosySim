"""
Tests for engine/tts/ — Voice Designer and TTS Server

Tests voice casting, presets, persistence, and TTS server endpoints.
"""
import json
import wave
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from engine.tts.voice_designer import (
    VoiceDesign,
    VoiceDesigner,
    VOICE_PRESETS,
)


# ═══════════════════════════════════════════════════════════════════════
#  VoiceDesign
# ═══════════════════════════════════════════════════════════════════════

class TestVoiceDesign:
    def test_defaults(self):
        d = VoiceDesign()
        assert "clear" in d.description.lower()
        assert d.model_size == "1.7b"
        assert d.reference_audio is None
        assert d.tags == []

    def test_to_dict(self):
        d = VoiceDesign(description="Test voice", model_size="0.6b", tags=["female"])
        data = d.to_dict()
        assert data["description"] == "Test voice"
        assert data["model_size"] == "0.6b"
        assert data["tags"] == ["female"]

    def test_from_dict(self):
        data = {"description": "Deep male", "model_size": "1.7b", "tags": ["male"]}
        d = VoiceDesign.from_dict(data)
        assert d.description == "Deep male"
        assert d.model_size == "1.7b"
        assert d.tags == ["male"]

    def test_from_dict_defaults(self):
        d = VoiceDesign.from_dict({})
        assert d.model_size == "1.7b"
        assert d.reference_audio is None

    def test_roundtrip(self):
        original = VoiceDesign(
            description="A warm voice",
            model_size="0.6b",
            reference_audio="/path/to/ref.wav",
            tags=["warm", "female"],
        )
        restored = VoiceDesign.from_dict(original.to_dict())
        assert restored.description == original.description
        assert restored.model_size == original.model_size
        assert restored.reference_audio == original.reference_audio
        assert restored.tags == original.tags


# ═══════════════════════════════════════════════════════════════════════
#  VoiceDesigner
# ═══════════════════════════════════════════════════════════════════════

class TestVoiceDesigner:
    @pytest.fixture
    def designer(self, tmp_path):
        """Designer with a temp file for persistence."""
        return VoiceDesigner(voices_file=tmp_path / "voices.yaml")

    def test_cast_and_get(self, designer):
        design = VoiceDesign(description="Test voice", model_size="0.6b")
        designer.cast("test_char", design)
        result = designer.get("test_char")
        assert result.description == "Test voice"
        assert result.model_size == "0.6b"

    def test_get_default_when_missing(self, designer):
        result = designer.get("nonexistent")
        assert result is not None
        assert result.model_size in ("0.6b", "1.7b")

    def test_remove(self, designer):
        designer.cast("char_a", VoiceDesign(description="A"))
        assert designer.remove("char_a") is True
        assert designer.remove("char_a") is False

    def test_list_characters(self, designer):
        designer.cast("a", VoiceDesign())
        designer.cast("b", VoiceDesign())
        chars = designer.list_characters()
        assert "a" in chars
        assert "b" in chars

    def test_cast_from_preset(self, designer):
        assert designer.cast_from_preset("luna", "flirty_female") is True
        result = designer.get("luna")
        assert "playful" in result.description.lower() or "vocal fry" in result.description.lower()

    def test_cast_from_invalid_preset(self, designer):
        assert designer.cast_from_preset("luna", "nonexistent") is False

    def test_persistence(self, tmp_path):
        """Voice designs survive save/load cycle."""
        voices_file = tmp_path / "voices.yaml"
        d1 = VoiceDesigner(voices_file=voices_file)
        d1.cast("luna", VoiceDesign(description="Luna voice", tags=["flirty"]))

        d2 = VoiceDesigner(voices_file=voices_file)
        result = d2.get("luna")
        assert result.description == "Luna voice"
        assert "flirty" in result.tags

    def test_get_all(self, designer):
        designer.cast("a", VoiceDesign(description="Voice A"))
        designer.cast("b", VoiceDesign(description="Voice B"))
        all_designs = designer.get_all()
        assert len(all_designs) == 2

    def test_list_presets(self, designer):
        presets = designer.list_presets()
        assert "flirty_female" in presets
        assert "ai_narrator" in presets
        assert "zero_shot" in presets


# ═══════════════════════════════════════════════════════════════════════
#  Voice Presets
# ═══════════════════════════════════════════════════════════════════════

class TestVoicePresets:
    def test_all_presets_have_descriptions(self):
        for name, design in VOICE_PRESETS.items():
            assert len(design.description) > 10, f"Preset {name} has short description"

    def test_all_presets_have_valid_model_size(self):
        for name, design in VOICE_PRESETS.items():
            assert design.model_size in ("0.6b", "1.7b"), f"Preset {name} has invalid model_size"

    def test_preset_count(self):
        assert len(VOICE_PRESETS) >= 5


# ═══════════════════════════════════════════════════════════════════════
#  TTS Server
# ═══════════════════════════════════════════════════════════════════════

class TestTTSServer:
    @pytest.fixture
    def client(self):
        from engine.tts.qwen3_server import create_tts_app
        from fastapi.testclient import TestClient
        app = create_tts_app()
        return TestClient(app)

    def test_status(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine"] == "qwen3-tts"
        assert data["mode"] in ("live", "placeholder")

    def test_voices(self, client):
        resp = client.get("/voices")
        assert resp.status_code == 200
        data = resp.json()
        assert "presets" in data
        assert "flirty_female" in data["presets"]

    def test_generate_short(self, client):
        resp = client.post("/generate", json={
            "text": "Hello, this is a test voice message.",
            "voice_design": "A warm female voice.",
            "max_duration": 30,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["duration"] is not None
        assert data["filename"] is not None
        # Verify WAV file exists
        assert data["download_url"] is not None

    def test_generate_with_character(self, client):
        # First cast a voice
        client.post("/cast", json={
            "character_id": "test_luna",
            "description": "A playful, warm female voice.",
            "model_size": "1.7b",
        })
        # Then generate with that character
        resp = client.post("/generate", json={
            "text": "Hey there!",
            "character_id": "test_luna",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_cast(self, client):
        resp = client.post("/cast", json={
            "character_id": "test_char",
            "description": "A deep male voice.",
            "model_size": "1.7b",
            "tags": ["male", "deep"],
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_download_generated(self, client):
        # Generate first
        resp = client.post("/generate", json={
            "text": "Download test.",
            "max_duration": 10,
        })
        filename = resp.json()["filename"]
        # Download
        resp = client.get(f"/download/{filename}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"

    def test_download_nonexistent(self, client):
        resp = client.get("/download/nonexistent.wav")
        assert resp.status_code == 404

    def test_job_status(self, client):
        # Generate
        resp = client.post("/generate", json={"text": "Job test."})
        job_id = resp.json()["job_id"]
        # Check status
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_job_not_found(self, client):
        resp = client.get("/jobs/nonexistent")
        assert resp.status_code == 404

    def test_generated_wav_is_valid(self, client):
        """Generated placeholder WAV is a valid audio file."""
        resp = client.post("/generate", json={
            "text": "Validate this WAV file please.",
            "max_duration": 10,
        })
        data = resp.json()
        filepath = data["filepath"]
        with wave.open(filepath, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() > 0
            assert wf.getnframes() > 0


# ═══════════════════════════════════════════════════════════════════════
#  Qwen3TTSEngine unit tests
# ═══════════════════════════════════════════════════════════════════════

class TestQwen3TTSEngine:
    def test_engine_starts_unloaded(self):
        from engine.tts.qwen3_server import Qwen3TTSEngine
        engine = Qwen3TTSEngine()
        assert engine.is_loaded is False

    def test_placeholder_mode_generates_wav(self, tmp_path):
        from engine.tts.qwen3_server import Qwen3TTSEngine
        engine = Qwen3TTSEngine()
        filepath, duration = engine._generate_placeholder(
            "Hello world", "A warm voice", 24000, 30
        )
        assert Path(filepath).exists()
        assert duration > 0
        with wave.open(str(filepath), "rb") as wf:
            assert wf.getnchannels() == 1

    def test_load_models_graceful_when_no_models(self, tmp_path):
        from engine.tts.qwen3_server import Qwen3TTSEngine
        engine = Qwen3TTSEngine()
        engine.load_models(model_dir=str(tmp_path))
        assert engine.is_loaded is False

    def test_chunk_text_short(self):
        from engine.tts.qwen3_server import Qwen3TTSEngine
        engine = Qwen3TTSEngine()
        chunks = engine._chunk_text("Short text.")
        assert len(chunks) == 1

    def test_chunk_text_long(self):
        from engine.tts.qwen3_server import Qwen3TTSEngine
        engine = Qwen3TTSEngine()
        long_text = ". ".join(["This is a sentence"] * 100)
        chunks = engine._chunk_text(long_text)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= engine.CHUNK_SIZE + 50  # some tolerance

    def test_select_model_fallback(self):
        from engine.tts.qwen3_server import Qwen3TTSEngine
        engine = Qwen3TTSEngine()
        model, tok = engine._select_model("1.7b")
        assert model is None  # nothing loaded

    def test_generate_falls_to_placeholder(self):
        from engine.tts.qwen3_server import Qwen3TTSEngine
        engine = Qwen3TTSEngine()
        filepath, duration = engine.generate("Test", "Voice", max_duration=10)
        assert Path(filepath).exists()
        assert duration > 0
