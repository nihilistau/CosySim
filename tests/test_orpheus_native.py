"""Tests for engine.tts.orpheus_native — native GGUF Orpheus TTS engine."""
from __future__ import annotations

import io
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from engine.tts.orpheus_native import (
    AUDIO_TOKEN_OFFSET,
    AVAILABLE_VOICES,
    CODEBOOK_SIZE,
    DEFAULT_VOICE,
    END_OF_SPEECH,
    OrpheusModel,
    OrpheusNative,
    SNAC_SAMPLE_RATE,
    SynthResult,
    get_orpheus_native,
)


# ═══════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def engine(tmp_path):
    """Create an OrpheusNative with empty model dir."""
    return OrpheusNative(model_dir=str(tmp_path))


@pytest.fixture
def engine_with_models(tmp_path):
    """Create engine with fake GGUF files for discovery."""
    q2_dir = tmp_path / "q2"
    q2_dir.mkdir()
    q2_file = q2_dir / "orpheus-q2_k.gguf"
    q2_file.write_bytes(b"\x00" * 1024)

    q4_dir = tmp_path / "q4"
    q4_dir.mkdir()
    q4_file = q4_dir / "orpheus-q4_k_m.gguf"
    q4_file.write_bytes(b"\x00" * 2048)

    return OrpheusNative(model_dir=str(tmp_path))


# ═══════════════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════════════


class TestConstants:
    """Verify module-level constants."""

    def test_snac_sample_rate(self):
        assert SNAC_SAMPLE_RATE == 24000

    def test_default_voice(self):
        assert DEFAULT_VOICE == "tara"

    def test_available_voices(self):
        assert "tara" in AVAILABLE_VOICES
        assert "leo" in AVAILABLE_VOICES
        assert len(AVAILABLE_VOICES) >= 5

    def test_audio_token_offset(self):
        assert AUDIO_TOKEN_OFFSET == 128266

    def test_end_of_speech(self):
        assert END_OF_SPEECH == 128258


# ═══════════════════════════════════════════════════════════════════════
#  SynthResult Dataclass
# ═══════════════════════════════════════════════════════════════════════


class TestSynthResult:
    """Tests for SynthResult dataclass."""

    def test_defaults(self):
        result = SynthResult(wav_bytes=b"fake")
        assert result.sample_rate == SNAC_SAMPLE_RATE
        assert result.duration == 0.0
        assert result.latency_ms == 0.0
        assert result.tokens_generated == 0
        assert result.voice == DEFAULT_VOICE

    def test_custom_values(self):
        result = SynthResult(
            wav_bytes=b"data", duration=2.5, latency_ms=500,
            tokens_generated=100, tokens_per_sec=50.0, quant="q4_k_m",
            voice="leo",
        )
        assert result.duration == 2.5
        assert result.quant == "q4_k_m"
        assert result.voice == "leo"


# ═══════════════════════════════════════════════════════════════════════
#  Model Discovery
# ═══════════════════════════════════════════════════════════════════════


class TestModelDiscovery:
    """Tests for _discover_models."""

    def test_empty_dir(self, engine):
        """No GGUF files found in empty dir."""
        assert len(engine._available_models) == 0

    def test_finds_q2(self, engine_with_models):
        """Discovers Q2_K model."""
        assert "q2_k" in engine_with_models._available_models

    def test_finds_q4(self, engine_with_models):
        """Discovers Q4_K_M model."""
        assert "q4_k_m" in engine_with_models._available_models

    def test_nonexistent_dir(self, tmp_path):
        """Handles nonexistent model dir gracefully."""
        engine = OrpheusNative(model_dir=str(tmp_path / "nope"))
        assert len(engine._available_models) == 0


# ═══════════════════════════════════════════════════════════════════════
#  Format Prompt
# ═══════════════════════════════════════════════════════════════════════


class TestFormatPrompt:
    """Tests for _format_prompt."""

    def test_default_voice(self, engine):
        result = engine._format_prompt("Hello", "tara")
        assert result == "<|audio|>tara: Hello<|eot_id|>"

    def test_custom_voice(self, engine):
        result = engine._format_prompt("Test", "leo")
        assert result == "<|audio|>leo: Test<|eot_id|>"


# ═══════════════════════════════════════════════════════════════════════
#  Audio Decoding
# ═══════════════════════════════════════════════════════════════════════


class TestDecodeAudio:
    """Tests for _decode_audio."""

    def test_empty_codes_returns_silence(self, engine):
        """Empty token list returns 1s of silence."""
        mock_snac = MagicMock()
        engine._snac_model = mock_snac
        engine._snac_device = "cpu"

        audio = engine._decode_audio([])
        assert isinstance(audio, np.ndarray)
        assert len(audio) == SNAC_SAMPLE_RATE  # 1s silence

    def test_codes_not_divisible_by_7_truncated(self, engine):
        """Codes truncated to nearest multiple of 7."""
        mock_snac = MagicMock()
        fake_audio = MagicMock()
        fake_audio.float.return_value.squeeze.return_value.cpu.return_value.numpy.return_value = np.zeros(100)
        mock_snac.decode.return_value = fake_audio
        engine._snac_model = mock_snac
        engine._snac_device = "cpu"

        # 10 codes — should truncate to 7
        codes = [AUDIO_TOKEN_OFFSET + i for i in range(10)]
        audio = engine._decode_audio(codes)
        assert isinstance(audio, np.ndarray)


# ═══════════════════════════════════════════════════════════════════════
#  WAV Conversion
# ═══════════════════════════════════════════════════════════════════════


class TestToWav:
    """Tests for _to_wav static method."""

    def test_produces_valid_wav(self):
        """Output is valid WAV file bytes."""
        audio = np.random.randn(24000).astype(np.float32) * 0.5
        wav_bytes = OrpheusNative._to_wav(audio)
        assert wav_bytes[:4] == b"RIFF"
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getframerate() == SNAC_SAMPLE_RATE
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2

    def test_clamps_audio(self):
        """Audio values outside [-1, 1] are clamped."""
        audio = np.array([2.0, -3.0, 0.5], dtype=np.float32)
        wav_bytes = OrpheusNative._to_wav(audio)
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(3)
            samples = np.frombuffer(frames, dtype=np.int16)
            assert samples[0] == 32767  # clamped to 1.0
            assert samples[1] == -32767  # clamped to -1.0


# ═══════════════════════════════════════════════════════════════════════
#  Model Loading
# ═══════════════════════════════════════════════════════════════════════


class TestModelLoading:
    """Tests for _load_model."""

    def test_load_unknown_quant_raises(self, engine):
        """Loading a quant not in available models raises ValueError."""
        with pytest.raises(ValueError, match="No q8_0 model found"):
            engine._load_model("q8_0")

    def test_cached_model_returned(self, engine):
        """Already-loaded model is returned without re-loading."""
        mock_model = OrpheusModel(path="/fake", quant="q2_k", llm=MagicMock())
        engine._models["q2_k"] = mock_model
        result = engine._load_model("q2_k")
        assert result is mock_model


# ═══════════════════════════════════════════════════════════════════════
#  Auto Quant Selection
# ═══════════════════════════════════════════════════════════════════════


class TestAutoSelectQuant:
    """Tests for auto_select_quant."""

    def test_short_text_selects_q2(self, engine):
        """Short text (<50 chars) prefers Q2_K."""
        engine._available_models = {"q2_k": "/fake", "q4_k_m": "/fake2"}
        assert engine.auto_select_quant("Hi") == "q2_k"

    def test_medium_text_selects_q4(self, engine):
        """Medium text prefers Q4_K_M."""
        engine._available_models = {"q2_k": "/fake", "q4_k_m": "/fake2"}
        assert engine.auto_select_quant("x" * 100) == "q4_k_m"

    def test_only_q2_available(self, engine):
        """Falls back to Q2_K if nothing else available."""
        engine._available_models = {"q2_k": "/fake"}
        assert engine.auto_select_quant("x" * 100) == "q2_k"

    def test_no_models_raises(self, engine):
        """No models available raises RuntimeError."""
        engine._available_models = {}
        with pytest.raises(RuntimeError, match="No Orpheus"):
            engine.auto_select_quant("test")


# ═══════════════════════════════════════════════════════════════════════
#  List Models
# ═══════════════════════════════════════════════════════════════════════


class TestListModels:
    """Tests for list_models."""

    def test_empty_when_no_models(self, engine):
        assert engine.list_models() == []

    def test_lists_discovered_models(self, engine_with_models):
        models = engine_with_models.list_models()
        quants = [m["quant"] for m in models]
        assert "q2_k" in quants
        assert "q4_k_m" in quants

    def test_loaded_flag(self, engine):
        """Loaded models are flagged."""
        engine._available_models = {"q2_k": "/fake.gguf"}
        engine._models["q2_k"] = OrpheusModel(
            path="/fake.gguf", quant="q2_k", llm=MagicMock(), on_gpu=False,
        )
        # list_models calls stat on the path — mock it
        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 1024 * 1024 * 100
            models = engine.list_models()
        assert models[0]["loaded"] is True


# ═══════════════════════════════════════════════════════════════════════
#  Unload
# ═══════════════════════════════════════════════════════════════════════


class TestUnload:
    """Tests for unload_model and unload_all."""

    def test_unload_unknown_returns_false(self, engine):
        assert engine.unload_model("q8_0") is False

    def test_unload_loaded_returns_true(self, engine):
        mock_llm = MagicMock()
        engine._models["q2_k"] = OrpheusModel(
            path="/fake", quant="q2_k", llm=mock_llm,
        )
        assert engine.unload_model("q2_k") is True
        assert "q2_k" not in engine._models

    def test_unload_all_clears_everything(self, engine):
        engine._models["q2_k"] = OrpheusModel(path="/f", quant="q2_k", llm=MagicMock())
        engine._models["q4_k_m"] = OrpheusModel(path="/f", quant="q4_k_m", llm=MagicMock())
        engine._snac_model = MagicMock()
        engine.unload_all()
        assert len(engine._models) == 0
        assert engine._snac_model is None


# ═══════════════════════════════════════════════════════════════════════
#  Synthesize (mocked)
# ═══════════════════════════════════════════════════════════════════════


class TestSynthesize:
    """Tests for synthesize with mocked LLM and SNAC."""

    def test_invalid_voice_defaults_to_tara(self, engine):
        """Unknown voice name falls back to default."""
        engine._available_models = {"q2_k": "/fake.gguf"}
        mock_llm = MagicMock()
        mock_llm.tokenize.return_value = [1, 2, 3]
        mock_llm.generate.return_value = iter([END_OF_SPEECH])
        engine._models["q2_k"] = OrpheusModel(path="/f", quant="q2_k", llm=mock_llm)

        mock_snac = MagicMock()
        engine._snac_model = mock_snac
        engine._snac_device = "cpu"

        result = engine.synthesize("Hi", voice="invalid_voice_xyz", quant="q2_k")
        assert result.voice == "tara"

    def test_no_audio_tokens_returns_silence(self, engine):
        """When LLM produces no audio tokens, returns silence."""
        engine._available_models = {"q2_k": "/fake.gguf"}
        mock_llm = MagicMock()
        mock_llm.tokenize.return_value = [1, 2, 3]
        mock_llm.generate.return_value = iter([END_OF_SPEECH])
        engine._models["q2_k"] = OrpheusModel(path="/f", quant="q2_k", llm=mock_llm)

        engine._snac_model = MagicMock()
        engine._snac_device = "cpu"

        result = engine.synthesize("Hello", quant="q2_k")
        assert result.duration == 1.0  # 1s silence
        assert result.wav_bytes[:4] == b"RIFF"


# ═══════════════════════════════════════════════════════════════════════
#  Singleton
# ═══════════════════════════════════════════════════════════════════════


class TestSingleton:
    """Tests for get_orpheus_native singleton."""

    def test_returns_same_instance(self):
        """Calling twice returns the same object."""
        import engine.tts.orpheus_native as mod
        mod._orpheus_native = None
        with patch.object(OrpheusNative, "__init__", return_value=None):
            a = get_orpheus_native()
            b = get_orpheus_native()
            assert a is b
            mod._orpheus_native = None  # cleanup


# ═══════════════════════════════════════════════════════════════════════
#  Benchmark Method
# ═══════════════════════════════════════════════════════════════════════


class TestBenchmark:
    """Tests for the benchmark method."""

    def test_benchmark_with_no_models(self, engine):
        """Benchmark with no models returns empty results."""
        result = engine.benchmark()
        assert result == {}

    def test_benchmark_captures_errors(self, engine):
        """Benchmark captures synthesis errors."""
        engine._available_models = {"q2_k": "/fake.gguf"}
        with patch.object(engine, "synthesize", side_effect=RuntimeError("fail")):
            result = engine.benchmark(quant="q2_k")
        assert "q2_k" in result
        assert all("error" in r for r in result["q2_k"])
