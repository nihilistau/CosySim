"""Tests for engine/tts/tts_manager.py — Unified TTS Manager.

Validates multi-backend routing, auto-selection, benchmark tracking,
health checks, fallback behavior, and utility helpers (PCM→WAV, WAV duration).
All external backends (Piper, Orpheus, Qwen3) are fully mocked.
"""
from __future__ import annotations

import io
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from engine.tts.tts_manager import (
    TTSBackend,
    TTSBenchmark,
    TTSManager,
    TTSResult,
    get_tts_manager,
    _tts_manager,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_wav_bytes(
    sample_rate: int = 22050, duration_s: float = 1.0, channels: int = 1
) -> bytes:
    """Build a minimal valid WAV file in memory.

    Args:
        sample_rate: Sample rate in Hz.
        duration_s: Duration in seconds.
        channels: Number of channels.

    Returns:
        WAV file bytes.
    """
    n_frames = int(sample_rate * duration_s)
    pcm = (np.zeros(n_frames, dtype=np.int16)).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


@dataclass
class FakeAudioChunk:
    """Simulates the AudioChunk returned by PiperVoice.synthesize()."""

    audio_float_array: np.ndarray
    sample_rate: int = 22050


def _make_piper_chunks(
    n_chunks: int = 3, chunk_size: int = 4410, sample_rate: int = 22050
) -> List[FakeAudioChunk]:
    """Create a list of fake Piper AudioChunk objects.

    Args:
        n_chunks: Number of chunks to produce.
        chunk_size: Samples per chunk.
        sample_rate: Audio sample rate.

    Returns:
        List of FakeAudioChunk.
    """
    return [
        FakeAudioChunk(
            audio_float_array=np.random.uniform(-1.0, 1.0, chunk_size).astype(
                np.float32
            ),
            sample_rate=sample_rate,
        )
        for _ in range(n_chunks)
    ]


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_config():
    """Return a dict-based mock config that mimics get_config().

    Returns:
        MagicMock with .get() that returns TTS-relevant defaults.
    """
    defaults = {
        "tts.piper.model_path": r"C:\fake\piper\model.onnx",
        "tts.server_url": "http://localhost:8600",
        "tts.engine": "placeholder",
    }
    cfg = MagicMock()
    cfg.get = lambda key, default=None: defaults.get(key, default)
    return cfg


@pytest.fixture
def manager(mock_config):
    """Create a fresh TTSManager with mocked config.

    Args:
        mock_config: Injected mock config fixture.

    Returns:
        TTSManager instance (no backends loaded).
    """
    return TTSManager(config=mock_config)


@pytest.fixture
def piper_voice_mock():
    """Build a mock PiperVoice that produces fake audio chunks.

    Returns:
        MagicMock mimicking PiperVoice interface.
    """
    voice = MagicMock()
    chunks = _make_piper_chunks(n_chunks=3, chunk_size=4410, sample_rate=22050)
    voice.synthesize.return_value = chunks
    voice.config.sample_rate = 22050
    return voice


@pytest.fixture
def manager_with_piper(manager, piper_voice_mock):
    """TTSManager with Piper pre-loaded (no real import).

    Args:
        manager: Base TTSManager.
        piper_voice_mock: Mocked PiperVoice.

    Returns:
        TTSManager with _piper_voice set and _piper_loaded = True.
    """
    manager._piper_voice = piper_voice_mock
    manager._piper_loaded = True
    manager._piper_model_path = r"C:\fake\piper\model.onnx"
    manager._available_backends[TTSBackend.PIPER.value] = True
    return manager


# ═══════════════════════════════════════════════════════════════════════
#  TTSBackend Enum
# ═══════════════════════════════════════════════════════════════════════


class TestTTSBackendEnum:
    """Tests for the TTSBackend enum values."""

    def test_backend_values(self):
        """All four backend identifiers exist."""
        assert TTSBackend.PIPER.value == "piper"
        assert TTSBackend.ORPHEUS.value == "orpheus"
        assert TTSBackend.QWEN3.value == "qwen3"
        assert TTSBackend.AUTO.value == "auto"

    def test_backend_is_str_enum(self):
        """TTSBackend members are also strings."""
        assert isinstance(TTSBackend.PIPER, str)
        assert TTSBackend.PIPER == "piper"


# ═══════════════════════════════════════════════════════════════════════
#  TTSResult Dataclass
# ═══════════════════════════════════════════════════════════════════════


class TestTTSResult:
    """Tests for the TTSResult dataclass."""

    def test_fields_stored(self):
        """All fields are accessible after construction."""
        r = TTSResult(
            audio_bytes=b"\x00",
            sample_rate=22050,
            duration=1.5,
            backend="piper",
            latency_ms=42.0,
            text="hello",
            voice="amy",
            format="wav",
        )
        assert r.audio_bytes == b"\x00"
        assert r.sample_rate == 22050
        assert r.duration == 1.5
        assert r.backend == "piper"
        assert r.latency_ms == 42.0
        assert r.text == "hello"
        assert r.voice == "amy"
        assert r.format == "wav"

    def test_default_voice_and_format(self):
        """Default voice is 'default', format is 'wav'."""
        r = TTSResult(
            audio_bytes=b"", sample_rate=22050, duration=0, backend="piper",
            latency_ms=0, text="",
        )
        assert r.voice == "default"
        assert r.format == "wav"


# ═══════════════════════════════════════════════════════════════════════
#  TTSBenchmark Dataclass
# ═══════════════════════════════════════════════════════════════════════


class TestTTSBenchmark:
    """Tests for benchmark stat tracking."""

    def test_default_values(self):
        """Fresh benchmark starts at zero."""
        b = TTSBenchmark()
        assert b.total_calls == 0
        assert b.total_latency_ms == 0.0
        assert b.failures == 0

    def test_avg_latency_zero_calls(self):
        """Average latency returns 0 when no calls recorded."""
        b = TTSBenchmark()
        assert b.avg_latency_ms == 0.0

    def test_avg_latency_with_calls(self):
        """Average latency computed correctly."""
        b = TTSBenchmark(total_calls=4, total_latency_ms=200.0)
        assert b.avg_latency_ms == 50.0

    def test_avg_rtf_zero_audio(self):
        """RTF returns 0 when no audio generated."""
        b = TTSBenchmark(total_calls=1, total_latency_ms=100.0, total_audio_seconds=0.0)
        assert b.avg_rtf == 0.0

    def test_avg_rtf_computed(self):
        """RTF computes correctly: latency_s / audio_s."""
        b = TTSBenchmark(
            total_calls=1, total_latency_ms=500.0, total_audio_seconds=2.0
        )
        # 0.5s / 2.0s = 0.25
        assert abs(b.avg_rtf - 0.25) < 1e-6


# ═══════════════════════════════════════════════════════════════════════
#  TTSManager Initialization
# ═══════════════════════════════════════════════════════════════════════


class TestTTSManagerInit:
    """Tests for TTSManager construction."""

    def test_initial_state(self, manager):
        """Fresh manager has no loaded backends."""
        assert manager._piper_loaded is False
        assert manager._piper_voice is None
        assert manager._piper_model_path is None

    def test_benchmarks_created_for_each_backend(self, manager):
        """Benchmark entries exist for piper, orpheus, qwen3 (not auto)."""
        assert "piper" in manager._benchmarks
        assert "orpheus" in manager._benchmarks
        assert "qwen3" in manager._benchmarks
        assert "auto" not in manager._benchmarks

    def test_all_backends_initially_unavailable(self, manager):
        """All backends start as unavailable."""
        for name, available in manager._available_backends.items():
            assert available is False, f"{name} should start as unavailable"

    def test_config_stored(self, mock_config):
        """Passed config is stored on the instance."""
        mgr = TTSManager(config=mock_config)
        assert mgr._config is mock_config

    def test_no_config_accepted(self):
        """TTSManager can be created without explicit config."""
        mgr = TTSManager()
        assert mgr._config is None


# ═══════════════════════════════════════════════════════════════════════
#  _get_config
# ═══════════════════════════════════════════════════════════════════════


class TestGetConfig:
    """Tests for config value resolution."""

    def test_returns_from_config_object(self, manager, mock_config):
        """Uses injected config when available."""
        val = manager._get_config("tts.server_url", "fallback")
        assert val == "http://localhost:8600"

    def test_returns_default_on_missing_key(self, manager):
        """Returns default for unknown key."""
        val = manager._get_config("nonexistent.key", "fallback_val")
        assert val == "fallback_val"

    @patch("engine.config.get_config", side_effect=ImportError)
    def test_returns_default_without_config(self, _mock):
        """Falls back to default if no config at all."""
        mgr = TTSManager(config=None)
        val = mgr._get_config("missing", "default_result")
        assert val == "default_result"


# ═══════════════════════════════════════════════════════════════════════
#  Auto Backend Selection
# ═══════════════════════════════════════════════════════════════════════


class TestAutoSelection:
    """Tests for _select_backend auto-routing logic."""

    def test_short_text_selects_piper(self, manager_with_piper):
        """Text under 200 chars routes to Piper."""
        backend = manager_with_piper._select_backend("Short reply.")
        assert backend == "piper"

    def test_exact_boundary_selects_piper(self, manager_with_piper):
        """Text exactly 199 chars routes to Piper."""
        text = "A" * 199
        backend = manager_with_piper._select_backend(text)
        assert backend == "piper"

    def test_boundary_200_chars_skips_piper(self, manager_with_piper):
        """Text at 200 chars does NOT select Piper first."""
        text = "A" * 200
        manager_with_piper._available_backends[TTSBackend.ORPHEUS.value] = True
        backend = manager_with_piper._select_backend(text)
        assert backend == "orpheus"

    def test_long_text_selects_orpheus_when_available(self, manager_with_piper):
        """Long text prefers Orpheus when it is available."""
        manager_with_piper._available_backends[TTSBackend.ORPHEUS.value] = True
        backend = manager_with_piper._select_backend("x" * 300)
        assert backend == "orpheus"

    def test_long_text_falls_back_to_piper(self, manager_with_piper):
        """Long text falls back to Piper when Orpheus unavailable."""
        manager_with_piper._available_backends[TTSBackend.ORPHEUS.value] = False
        backend = manager_with_piper._select_backend("x" * 300)
        assert backend == "piper"

    def test_nothing_available_returns_qwen3(self, manager):
        """When Piper and Orpheus both unavailable, returns Qwen3."""
        with patch.object(manager, "_ensure_piper", return_value=False):
            backend = manager._select_backend("Any text")
            assert backend == "qwen3"

    def test_empty_text_selects_piper(self, manager_with_piper):
        """Empty string (0 chars < 200) routes to Piper."""
        backend = manager_with_piper._select_backend("")
        assert backend == "piper"


# ═══════════════════════════════════════════════════════════════════════
#  Piper Backend
# ═══════════════════════════════════════════════════════════════════════


class TestPiperSynthesis:
    """Tests for Piper TTS synthesis (mocked)."""

    def test_synth_piper_returns_tts_result(self, manager_with_piper):
        """Piper synthesis returns a proper TTSResult."""
        result = manager_with_piper._synth_piper("Hello world")
        assert isinstance(result, TTSResult)
        assert result.backend == "piper"
        assert result.sample_rate == 22050
        assert result.duration > 0
        assert len(result.audio_bytes) > 0
        assert result.text == "Hello world"

    def test_synth_piper_wav_is_valid(self, manager_with_piper):
        """Audio bytes from Piper are a valid WAV file."""
        result = manager_with_piper._synth_piper("Test")
        buf = io.BytesIO(result.audio_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 22050
            assert wf.getnframes() > 0

    def test_synth_piper_voice_param_stored(self, manager_with_piper):
        """Voice parameter is preserved in the result."""
        result = manager_with_piper._synth_piper("Hi", voice="amy")
        assert result.voice == "amy"

    def test_synth_piper_latency_positive(self, manager_with_piper):
        """Latency measurement is a positive number."""
        result = manager_with_piper._synth_piper("Latency check")
        assert result.latency_ms > 0

    def test_synth_piper_empty_audio_raises(self, manager_with_piper):
        """RuntimeError raised when Piper produces no audio chunks."""
        manager_with_piper._piper_voice.synthesize.return_value = []
        with pytest.raises(RuntimeError, match="no audio"):
            manager_with_piper._synth_piper("Silence")

    def test_synth_piper_not_loaded_raises(self, manager):
        """RuntimeError when Piper backend is not available."""
        with patch.object(manager, "_ensure_piper", return_value=False):
            with pytest.raises(RuntimeError, match="not available"):
                manager._synth_piper("Will fail")

    def test_ensure_piper_loads_model(self, manager):
        """_ensure_piper imports and loads PiperVoice on first call."""
        mock_voice = MagicMock()
        mock_voice.config.sample_rate = 22050
        mock_piper_module = MagicMock()
        mock_piper_module.PiperVoice.load.return_value = mock_voice

        with patch.dict("sys.modules", {"piper": mock_piper_module}):
            result = manager._ensure_piper()

        assert result is True
        assert manager._piper_loaded is True
        assert manager._available_backends["piper"] is True

    def test_ensure_piper_skips_reload(self, manager_with_piper):
        """_ensure_piper returns True immediately if already loaded."""
        assert manager_with_piper._ensure_piper() is True

    def test_ensure_piper_handles_import_error(self, manager):
        """_ensure_piper returns False when piper module is missing."""
        with patch("builtins.__import__", side_effect=ImportError("no piper")):
            result = manager._ensure_piper()
        assert result is False
        assert manager._available_backends["piper"] is False


# ═══════════════════════════════════════════════════════════════════════
#  Orpheus Backend
# ═══════════════════════════════════════════════════════════════════════


class TestOrpheusSynthesis:
    """Tests for Orpheus TTS synthesis (mocked)."""

    @patch("engine.tts.tts_manager.Path")
    @patch("engine.tts.orpheus_client.get_orpheus_client")
    def test_synth_orpheus_returns_result(self, mock_get_client, mock_path, manager):
        """Orpheus synthesis returns a valid TTSResult."""
        wav_bytes = _make_wav_bytes(sample_rate=24000, duration_s=1.0)
        mock_client = MagicMock()
        mock_client.generate.return_value = "/fake/output.wav"
        mock_get_client.return_value = mock_client

        mock_path_inst = MagicMock()
        mock_path_inst.exists.return_value = True
        mock_path_inst.read_bytes.return_value = wav_bytes
        mock_path.return_value = mock_path_inst

        result = manager._synth_orpheus("A longer narrative text", voice="tara")

        assert isinstance(result, TTSResult)
        assert result.backend == "orpheus"
        assert result.sample_rate == 24000
        assert result.voice == "tara"
        assert result.duration > 0

    @patch("engine.tts.orpheus_client.get_orpheus_client")
    def test_synth_orpheus_no_output_raises(self, mock_get_client, manager):
        """RuntimeError when Orpheus produces no output file."""
        mock_client = MagicMock()
        mock_client.generate.return_value = None
        mock_get_client.return_value = mock_client

        with pytest.raises(RuntimeError, match="no output"):
            manager._synth_orpheus("Will fail")

    @patch("engine.tts.tts_manager.Path")
    @patch("engine.tts.orpheus_client.get_orpheus_client")
    def test_synth_orpheus_missing_file_raises(
        self, mock_get_client, mock_path, manager
    ):
        """RuntimeError when Orpheus output path doesn't exist on disk."""
        mock_client = MagicMock()
        mock_client.generate.return_value = "/fake/missing.wav"
        mock_get_client.return_value = mock_client

        mock_path_inst = MagicMock()
        mock_path_inst.exists.return_value = False
        mock_path.return_value = mock_path_inst

        with pytest.raises(RuntimeError, match="no output"):
            manager._synth_orpheus("Also fails")

    @patch("engine.tts.tts_manager.Path")
    @patch("engine.tts.orpheus_client.get_orpheus_client")
    def test_synth_orpheus_marks_available(self, mock_get_client, mock_path, manager):
        """Successful Orpheus synthesis marks the backend as available."""
        wav_bytes = _make_wav_bytes(sample_rate=24000)
        mock_client = MagicMock()
        mock_client.generate.return_value = "/fake/output.wav"
        mock_get_client.return_value = mock_client

        mock_path_inst = MagicMock()
        mock_path_inst.exists.return_value = True
        mock_path_inst.read_bytes.return_value = wav_bytes
        mock_path.return_value = mock_path_inst

        manager._synth_orpheus("Mark available")
        assert manager._available_backends["orpheus"] is True


# ═══════════════════════════════════════════════════════════════════════
#  Qwen3 Backend
# ═══════════════════════════════════════════════════════════════════════


class TestQwen3Synthesis:
    """Tests for Qwen3 TTS synthesis (mocked HTTP)."""

    @patch("requests.post")
    def test_synth_qwen3_returns_result(self, mock_post, manager):
        """Qwen3 synthesis returns a valid TTSResult."""
        wav_bytes = _make_wav_bytes(sample_rate=22050, duration_s=0.5)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = wav_bytes
        mock_post.return_value = mock_resp

        result = manager._synth_qwen3("Hello from GPU", voice="default")

        assert isinstance(result, TTSResult)
        assert result.backend == "qwen3"
        assert result.sample_rate == 22050
        assert result.duration > 0
        assert result.text == "Hello from GPU"
        mock_post.assert_called_once()

    @patch("requests.post")
    def test_synth_qwen3_sends_correct_payload(self, mock_post, manager):
        """Request to Qwen3 includes text and voice_design."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = _make_wav_bytes()
        mock_post.return_value = mock_resp

        manager._synth_qwen3("Payload check", voice="warm female")

        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["text"] == "Payload check"
        assert call_kwargs[1]["json"]["voice_design"] == "warm female"

    @patch("requests.post")
    def test_synth_qwen3_http_error_raises(self, mock_post, manager):
        """RuntimeError when Qwen3 returns non-200 status."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="500"):
            manager._synth_qwen3("Server error")

    @patch("requests.post")
    def test_synth_qwen3_uses_configured_url(self, mock_post, manager):
        """Qwen3 reads server URL from config."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = _make_wav_bytes()
        mock_post.return_value = mock_resp

        manager._synth_qwen3("URL check")

        called_url = mock_post.call_args[0][0]
        assert "localhost:8600" in called_url
        assert called_url.endswith("/generate")

    @patch("requests.post")
    def test_synth_qwen3_marks_available(self, mock_post, manager):
        """Successful Qwen3 call marks the backend available."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = _make_wav_bytes()
        mock_post.return_value = mock_resp

        manager._synth_qwen3("Mark available")
        assert manager._available_backends["qwen3"] is True


# ═══════════════════════════════════════════════════════════════════════
#  synthesize() — Public API
# ═══════════════════════════════════════════════════════════════════════


class TestSynthesize:
    """Tests for the main synthesize() public method."""

    def test_synthesize_explicit_piper(self, manager_with_piper):
        """Explicit backend='piper' bypasses auto-selection."""
        result = manager_with_piper.synthesize("Hello", backend="piper")
        assert result.backend == "piper"

    def test_synthesize_auto_short(self, manager_with_piper):
        """Auto mode picks Piper for short text."""
        result = manager_with_piper.synthesize("Hi!", backend="auto")
        assert result.backend == "piper"

    def test_synthesize_unknown_backend_raises(self, manager):
        """ValueError for unknown backend name."""
        with pytest.raises(ValueError, match="Unknown TTS backend"):
            manager.synthesize("Hello", backend="nonexistent")

    def test_synthesize_updates_benchmarks(self, manager_with_piper):
        """Successful synthesis increments benchmark counters."""
        manager_with_piper.synthesize("Benchmark test", backend="piper")

        bench = manager_with_piper._benchmarks["piper"]
        assert bench.total_calls == 1
        assert bench.total_latency_ms > 0
        assert bench.total_audio_seconds > 0
        assert bench.last_latency_ms > 0
        assert bench.last_rtf > 0

    def test_synthesize_multiple_calls_accumulate(self, manager_with_piper):
        """Multiple calls accumulate benchmark stats."""
        manager_with_piper.synthesize("First", backend="piper")
        manager_with_piper.synthesize("Second", backend="piper")

        bench = manager_with_piper._benchmarks["piper"]
        assert bench.total_calls == 2

    def test_synthesize_failure_increments_failures(self, manager_with_piper):
        """Failed synthesis increments failures counter."""
        manager_with_piper._piper_voice.synthesize.side_effect = RuntimeError("boom")
        # Piper fails, fallback also fails since it's the same backend
        with pytest.raises(RuntimeError):
            manager_with_piper.synthesize("Fail", backend="piper")
        assert manager_with_piper._benchmarks["piper"].failures >= 1


# ═══════════════════════════════════════════════════════════════════════
#  Fallback Behavior
# ═══════════════════════════════════════════════════════════════════════


class TestFallback:
    """Tests for backend fallback when the primary fails."""

    def test_orpheus_failure_falls_back_to_piper(self, manager_with_piper):
        """When Orpheus fails, manager falls back to Piper."""
        with patch.object(
            manager_with_piper, "_synth_orpheus", side_effect=RuntimeError("orpheus down")
        ):
            result = manager_with_piper.synthesize("Fallback", backend="orpheus")

        assert result.backend == "piper"
        assert manager_with_piper._benchmarks["orpheus"].failures == 1

    @patch("requests.post")
    def test_qwen3_failure_falls_back_to_piper(self, mock_post, manager_with_piper):
        """When Qwen3 fails, manager falls back to Piper."""
        mock_post.side_effect = RuntimeError("GPU exploded")

        result = manager_with_piper.synthesize("Rescue", backend="qwen3")

        assert result.backend == "piper"
        assert manager_with_piper._benchmarks["qwen3"].failures == 1

    def test_piper_failure_no_fallback_raises(self, manager):
        """When Piper itself fails and nothing else is available, it raises."""
        with patch.object(manager, "_ensure_piper", return_value=False):
            with patch.object(
                manager, "_synth_piper", side_effect=RuntimeError("piper broken")
            ):
                with pytest.raises(RuntimeError):
                    manager.synthesize("No fallback", backend="piper")

    def test_fallback_only_to_piper_not_others(self, manager):
        """Fallback logic only tries Piper, not Orpheus or Qwen3."""
        # Orpheus fails, Piper unavailable → should raise (not try Qwen3)
        with patch.object(manager, "_ensure_piper", return_value=False):
            with patch.object(
                manager, "_synth_orpheus", side_effect=RuntimeError("orpheus down")
            ):
                with pytest.raises(RuntimeError):
                    manager.synthesize("Dead end", backend="orpheus")


# ═══════════════════════════════════════════════════════════════════════
#  Benchmark Reporting
# ═══════════════════════════════════════════════════════════════════════


class TestBenchmarks:
    """Tests for get_benchmarks() reporting."""

    def test_initial_benchmarks_all_zero(self, manager):
        """Fresh manager reports zero stats for all backends."""
        benchmarks = manager.get_benchmarks()
        for name in ("piper", "orpheus", "qwen3"):
            assert benchmarks[name]["total_calls"] == 0
            assert benchmarks[name]["failures"] == 0
            assert benchmarks[name]["avg_latency_ms"] == 0.0

    def test_benchmarks_after_synthesis(self, manager_with_piper):
        """Benchmarks reflect a successful synthesis call."""
        manager_with_piper.synthesize("Bench me", backend="piper")
        bench = manager_with_piper._benchmarks["piper"]
        benchmarks = manager_with_piper.get_benchmarks()

        assert benchmarks["piper"]["total_calls"] == 1
        assert benchmarks["piper"]["total_audio_seconds"] > 0
        # Use raw benchmark values to avoid rounding issues with fast mocks
        assert bench.last_latency_ms > 0
        assert benchmarks["piper"]["available"] is True

    def test_benchmarks_include_availability(self, manager_with_piper):
        """Benchmark report includes availability flags."""
        benchmarks = manager_with_piper.get_benchmarks()
        assert benchmarks["piper"]["available"] is True
        assert benchmarks["orpheus"]["available"] is False
        assert benchmarks["qwen3"]["available"] is False

    def test_benchmarks_keys_complete(self, manager):
        """Each backend entry has all expected keys."""
        benchmarks = manager.get_benchmarks()
        expected_keys = {
            "total_calls", "avg_latency_ms", "avg_rtf",
            "last_latency_ms", "last_rtf", "failures",
            "total_audio_seconds", "available",
        }
        for name in ("piper", "orpheus", "qwen3"):
            assert set(benchmarks[name].keys()) == expected_keys


# ═══════════════════════════════════════════════════════════════════════
#  Health Check
# ═══════════════════════════════════════════════════════════════════════


class TestHealth:
    """Tests for the health() endpoint."""

    @patch("requests.get")
    @patch("engine.tts.orpheus_client.get_orpheus_client")
    def test_health_all_up(self, mock_orpheus, mock_req_get, manager_with_piper):
        """Health returns 'ok' when at least one backend is up."""
        mock_orpheus.return_value.health.return_value = {"status": "ok"}
        mock_resp = MagicMock(status_code=200)
        mock_req_get.return_value = mock_resp

        result = manager_with_piper.health()
        assert result["status"] == "ok"
        assert result["backends"]["piper"] is True

    def test_health_piper_only(self, manager_with_piper):
        """Health 'ok' even when only Piper is available."""
        with patch("engine.tts.orpheus_client.get_orpheus_client", side_effect=Exception):
            with patch("requests.get", side_effect=Exception):
                result = manager_with_piper.health()

        assert result["status"] == "ok"
        assert result["backends"]["piper"] is True
        assert result["backends"]["orpheus"] is False
        assert result["backends"]["qwen3"] is False

    def test_health_all_down(self, manager):
        """Health returns 'degraded' when all backends are down."""
        with patch.object(manager, "_ensure_piper", return_value=False):
            with patch(
                "engine.tts.orpheus_client.get_orpheus_client", side_effect=Exception
            ):
                with patch("requests.get", side_effect=Exception):
                    result = manager.health()

        assert result["status"] == "degraded"

    def test_health_includes_benchmarks(self, manager_with_piper):
        """Health response contains the benchmarks dict."""
        with patch("engine.tts.orpheus_client.get_orpheus_client", side_effect=Exception):
            with patch("requests.get", side_effect=Exception):
                result = manager_with_piper.health()

        assert "benchmarks" in result
        assert "piper" in result["benchmarks"]

    @patch("requests.get")
    @patch("engine.tts.orpheus_client.get_orpheus_client")
    def test_health_orpheus_online(self, mock_orpheus, mock_req_get, manager):
        """Orpheus health checked via client.health()."""
        mock_orpheus.return_value.health.return_value = {"status": "ok"}
        mock_req_get.side_effect = Exception("qwen down")

        with patch.object(manager, "_ensure_piper", return_value=False):
            result = manager.health()

        assert result["backends"]["orpheus"] is True
        assert result["status"] == "ok"

    @patch("requests.get")
    def test_health_qwen3_checked_via_http(self, mock_get, manager):
        """Qwen3 health checked via /health endpoint."""
        mock_get.return_value = MagicMock(status_code=200)

        with patch.object(manager, "_ensure_piper", return_value=False):
            with patch(
                "engine.tts.orpheus_client.get_orpheus_client", side_effect=Exception
            ):
                result = manager.health()

        assert result["backends"]["qwen3"] is True
        called_url = mock_get.call_args[0][0]
        assert called_url.endswith("/health")


# ═══════════════════════════════════════════════════════════════════════
#  list_backends
# ═══════════════════════════════════════════════════════════════════════


class TestListBackends:
    """Tests for list_backends()."""

    def test_returns_three_backends(self, manager_with_piper):
        """Three backend entries are returned."""
        backends = manager_with_piper.list_backends()
        assert len(backends) == 3

    def test_backend_names(self, manager_with_piper):
        """Backend names match enum values."""
        backends = manager_with_piper.list_backends()
        names = [b["name"] for b in backends]
        assert "piper" in names
        assert "orpheus" in names
        assert "qwen3" in names

    def test_piper_shows_available(self, manager_with_piper):
        """Piper shows as available when loaded."""
        backends = manager_with_piper.list_backends()
        piper = next(b for b in backends if b["name"] == "piper")
        assert piper["available"] is True
        assert piper["model"] == r"C:\fake\piper\model.onnx"

    def test_orpheus_shows_unavailable(self, manager_with_piper):
        """Orpheus shows as unavailable when not initialized."""
        backends = manager_with_piper.list_backends()
        orpheus = next(b for b in backends if b["name"] == "orpheus")
        assert orpheus["available"] is False

    def test_each_backend_has_label_and_description(self, manager_with_piper):
        """Each entry has label and description fields."""
        backends = manager_with_piper.list_backends()
        for b in backends:
            assert "label" in b
            assert "description" in b
            assert len(b["description"]) > 10


# ═══════════════════════════════════════════════════════════════════════
#  PCM to WAV Conversion
# ═══════════════════════════════════════════════════════════════════════


class TestPcmToWav:
    """Tests for the _pcm_to_wav static method."""

    def test_produces_valid_wav(self):
        """Generated WAV bytes are parseable by the wave module."""
        pcm = np.zeros(22050, dtype=np.int16).tobytes()
        wav = TTSManager._pcm_to_wav(pcm, sample_rate=22050)

        buf = io.BytesIO(wav)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 22050
            assert wf.getnframes() == 22050

    def test_stereo_wav(self):
        """Stereo PCM produces 2-channel WAV."""
        pcm = np.zeros(44100, dtype=np.int16).tobytes()  # 2 channels × 22050 frames
        wav = TTSManager._pcm_to_wav(pcm, sample_rate=22050, channels=2)

        buf = io.BytesIO(wav)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 2

    def test_different_sample_rates(self):
        """WAV respects the supplied sample rate."""
        for sr in (16000, 22050, 24000, 44100, 48000):
            pcm = np.zeros(sr, dtype=np.int16).tobytes()
            wav = TTSManager._pcm_to_wav(pcm, sample_rate=sr)
            buf = io.BytesIO(wav)
            with wave.open(buf, "rb") as wf:
                assert wf.getframerate() == sr

    def test_empty_pcm_produces_valid_wav(self):
        """Empty PCM data still produces a valid (zero-length) WAV."""
        wav = TTSManager._pcm_to_wav(b"", sample_rate=22050)
        buf = io.BytesIO(wav)
        with wave.open(buf, "rb") as wf:
            assert wf.getnframes() == 0

    def test_wav_starts_with_riff_header(self):
        """WAV bytes begin with 'RIFF' magic bytes."""
        pcm = np.zeros(100, dtype=np.int16).tobytes()
        wav = TTSManager._pcm_to_wav(pcm, sample_rate=22050)
        assert wav[:4] == b"RIFF"


# ═══════════════════════════════════════════════════════════════════════
#  WAV Duration Extraction
# ═══════════════════════════════════════════════════════════════════════


class TestWavDuration:
    """Tests for the _wav_duration static method."""

    def test_known_duration(self):
        """Duration matches the expected value for a known WAV."""
        wav = _make_wav_bytes(sample_rate=22050, duration_s=2.0)
        dur = TTSManager._wav_duration(wav)
        assert abs(dur - 2.0) < 0.01

    def test_short_duration(self):
        """Sub-second WAV duration extracted correctly."""
        wav = _make_wav_bytes(sample_rate=44100, duration_s=0.25)
        dur = TTSManager._wav_duration(wav)
        assert abs(dur - 0.25) < 0.01

    def test_invalid_wav_returns_zero(self):
        """Corrupt/invalid bytes return 0.0 instead of raising."""
        dur = TTSManager._wav_duration(b"not a wav file")
        assert dur == 0.0

    def test_empty_bytes_returns_zero(self):
        """Empty bytes return 0.0."""
        dur = TTSManager._wav_duration(b"")
        assert dur == 0.0

    def test_zero_length_wav_returns_zero(self):
        """WAV with zero frames returns 0.0 duration."""
        wav = _make_wav_bytes(sample_rate=22050, duration_s=0.0)
        dur = TTSManager._wav_duration(wav)
        assert dur == 0.0


# ═══════════════════════════════════════════════════════════════════════
#  Singleton — get_tts_manager
# ═══════════════════════════════════════════════════════════════════════


class TestGetTTSManager:
    """Tests for the module-level singleton factory."""

    def test_returns_tts_manager_instance(self):
        """get_tts_manager() returns a TTSManager."""
        import engine.tts.tts_manager as mod

        mod._tts_manager = None
        try:
            mgr = get_tts_manager()
            assert isinstance(mgr, TTSManager)
        finally:
            mod._tts_manager = None

    def test_singleton_same_instance(self):
        """Repeated calls return the same object."""
        import engine.tts.tts_manager as mod

        mod._tts_manager = None
        try:
            mgr1 = get_tts_manager()
            mgr2 = get_tts_manager()
            assert mgr1 is mgr2
        finally:
            mod._tts_manager = None

    def test_config_passed_on_first_call(self):
        """Config is accepted on the initial singleton creation."""
        import engine.tts.tts_manager as mod

        mod._tts_manager = None
        cfg = MagicMock()
        try:
            mgr = get_tts_manager(config=cfg)
            assert mgr._config is cfg
        finally:
            mod._tts_manager = None

    def test_config_ignored_on_subsequent_calls(self):
        """Config argument is ignored after singleton is created."""
        import engine.tts.tts_manager as mod

        mod._tts_manager = None
        cfg1 = MagicMock()
        cfg2 = MagicMock()
        try:
            mgr1 = get_tts_manager(config=cfg1)
            mgr2 = get_tts_manager(config=cfg2)
            assert mgr2._config is cfg1  # first config wins
        finally:
            mod._tts_manager = None


# ═══════════════════════════════════════════════════════════════════════
#  Integration-style: Full synthesize → benchmark round-trip
# ═══════════════════════════════════════════════════════════════════════


class TestSynthesizeRoundTrip:
    """End-to-end tests combining synthesis + benchmarks + health."""

    def test_piper_synth_then_benchmark_then_health(self, manager_with_piper):
        """Full flow: synthesize → check benchmarks → check health."""
        # Synthesize
        result = manager_with_piper.synthesize("Round trip test", backend="piper")
        assert result.backend == "piper"

        # Benchmarks reflect the call
        benchmarks = manager_with_piper.get_benchmarks()
        assert benchmarks["piper"]["total_calls"] == 1
        assert benchmarks["piper"]["total_audio_seconds"] > 0

        # Health includes updated benchmarks
        with patch("engine.tts.orpheus_client.get_orpheus_client", side_effect=Exception):
            with patch("requests.get", side_effect=Exception):
                health = manager_with_piper.health()
        assert health["status"] == "ok"
        assert health["benchmarks"]["piper"]["total_calls"] == 1

    def test_multiple_backends_tracked_independently(self, manager_with_piper):
        """Calls to different backends update separate benchmark entries."""
        # Piper call
        manager_with_piper.synthesize("Piper call", backend="piper")

        # Simulate orpheus failure → fallback to piper
        # Note: fallback calls _synth_piper directly, not through synthesize,
        # so piper benchmarks are NOT incremented for the fallback call.
        with patch.object(
            manager_with_piper, "_synth_orpheus",
            side_effect=RuntimeError("orpheus down"),
        ):
            manager_with_piper.synthesize("Orpheus attempt", backend="orpheus")

        benchmarks = manager_with_piper.get_benchmarks()
        assert benchmarks["piper"]["total_calls"] == 1  # direct only
        assert benchmarks["orpheus"]["failures"] == 1
