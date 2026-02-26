"""Unified TTS Manager — multi-backend text-to-speech routing.

Routes synthesis requests through the best available backend based on
latency requirements, text length, and backend health.

Backends (priority order for real-time):
    1. Piper — CPU-only ONNX, ~60ms/s, perfect for short assistant replies
    2. Orpheus — LMStudio-backed, high quality, 24 voices + emotion tags
    3. Qwen3 — GPU-based, escalation mode (0.6B→1.7B)

Usage::

    from engine.tts.tts_manager import get_tts_manager
    mgr = get_tts_manager()
    audio = mgr.synthesize("Hello!", backend="auto")
    # audio = {"pcm": bytes, "sample_rate": int, "duration": float}
"""
from __future__ import annotations

import io
import logging
import struct
import time
import wave
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class TTSBackend(str, Enum):
    """Available TTS backend engines."""

    PIPER = "piper"
    ORPHEUS = "orpheus"
    ORPHEUS_NATIVE = "orpheus_native"
    QWEN3 = "qwen3"
    AUTO = "auto"


@dataclass
class TTSResult:
    """Result from a TTS synthesis operation."""

    audio_bytes: bytes
    sample_rate: int
    duration: float
    backend: str
    latency_ms: float
    text: str
    voice: str = "default"
    format: str = "wav"


@dataclass
class TTSBenchmark:
    """Running benchmark stats for a backend."""

    total_calls: int = 0
    total_latency_ms: float = 0.0
    total_audio_seconds: float = 0.0
    failures: int = 0
    last_latency_ms: float = 0.0
    last_rtf: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        """Average latency across all calls."""
        return self.total_latency_ms / max(self.total_calls, 1)

    @property
    def avg_rtf(self) -> float:
        """Average real-time factor (lower = faster than real-time)."""
        if self.total_audio_seconds < 0.01:
            return 0.0
        return (self.total_latency_ms / 1000.0) / self.total_audio_seconds


class TTSManager:
    """Unified TTS manager that routes between backends.

    Automatically selects the best backend based on text length,
    latency requirements, and backend health. Tracks performance
    benchmarks for continuous improvement.

    Args:
        config: Optional config override for testing.
    """

    def __init__(self, config: Optional[Any] = None) -> None:
        self._config = config
        self._piper_voice: Optional[Any] = None
        self._piper_loaded = False
        self._piper_model_path: Optional[str] = None
        self._benchmarks: Dict[str, TTSBenchmark] = {
            b.value: TTSBenchmark() for b in TTSBackend if b != TTSBackend.AUTO
        }
        self._available_backends: Dict[str, bool] = {
            TTSBackend.PIPER.value: False,
            TTSBackend.ORPHEUS.value: False,
            TTSBackend.ORPHEUS_NATIVE.value: False,
            TTSBackend.QWEN3.value: False,
        }
        # Config-driven enabled state (runtime-mutable)
        self._enabled_backends: Dict[str, bool] = {
            TTSBackend.PIPER.value: self._get_config("tts.backends.piper.enabled", True),
            TTSBackend.ORPHEUS.value: self._get_config("tts.backends.orpheus.enabled", True),
            TTSBackend.ORPHEUS_NATIVE.value: self._get_config("tts.backends.orpheus_native.enabled", True),
            TTSBackend.QWEN3.value: self._get_config("tts.backends.qwen3.enabled", True),
        }
        self._default_backend: str = self._get_config("tts.default_backend", "auto")
        logger.info("TTSManager initialized (default=%s, enabled=%s)",
                     self._default_backend, self._enabled_backends)

    # ── Configuration ───────────────────────────────────────────────────

    def _get_config(self, key: str, default: Any = None) -> Any:
        """Get a config value with dot-path notation."""
        if self._config and hasattr(self._config, "get"):
            return self._config.get(key, default)
        try:
            from engine.config import get_config
            return get_config().get(key, default)
        except Exception:
            return default

    # ── Runtime Enable/Disable ──────────────────────────────────────────

    def set_backend_enabled(self, backend: str, enabled: bool) -> None:
        """Enable or disable a backend at runtime.

        Args:
            backend: Backend name ("piper", "orpheus", "qwen3").
            enabled: Whether to enable this backend.
        """
        if backend not in self._enabled_backends:
            raise ValueError(f"Unknown backend: {backend}")
        self._enabled_backends[backend] = enabled
        logger.info("TTS backend '%s' %s", backend, "enabled" if enabled else "disabled")

    def set_default_backend(self, backend: str) -> None:
        """Set the default backend for synthesis.

        Args:
            backend: Backend name or "auto".
        """
        valid = {b.value for b in TTSBackend}
        if backend not in valid:
            raise ValueError(f"Unknown backend: {backend}. Valid: {valid}")
        self._default_backend = backend
        logger.info("TTS default backend set to '%s'", backend)

    def get_tts_config(self) -> Dict[str, Any]:
        """Get the current TTS configuration state.

        Returns:
            Dict with default_backend, enabled states, availability, benchmarks.
        """
        return {
            "default_backend": self._default_backend,
            "backends": {
                name: {
                    "enabled": self._enabled_backends.get(name, False),
                    "available": self._available_backends.get(name, False),
                    "benchmarks": {
                        "total_calls": bench.total_calls,
                        "avg_latency_ms": round(bench.avg_latency_ms, 1),
                        "avg_rtf": round(bench.avg_rtf, 4),
                        "failures": bench.failures,
                    },
                }
                for name, bench in self._benchmarks.items()
            },
        }

    def update_tts_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Apply runtime config updates.

        Args:
            updates: Dict with optional keys: default_backend, backends.{name}.enabled

        Returns:
            Updated config state.
        """
        if "default_backend" in updates:
            self.set_default_backend(updates["default_backend"])
        backends_cfg = updates.get("backends", {})
        for name, cfg in backends_cfg.items():
            if isinstance(cfg, dict) and "enabled" in cfg:
                self.set_backend_enabled(name, bool(cfg["enabled"]))
            elif isinstance(cfg, bool):
                self.set_backend_enabled(name, cfg)
        return self.get_tts_config()

    def is_backend_enabled(self, backend: str) -> bool:
        """Check if a backend is both enabled and available.

        Args:
            backend: Backend name.

        Returns:
            True if enabled in config.
        """
        return self._enabled_backends.get(backend, False)

    # ── Piper Backend ───────────────────────────────────────────────────

    def _ensure_piper(self) -> bool:
        """Load Piper model if not already loaded.

        Returns:
            True if Piper is ready and enabled.
        """
        if not self._enabled_backends.get(TTSBackend.PIPER.value, True):
            return False
        if self._piper_loaded:
            return True
        try:
            from piper import PiperVoice

            model_path = self._get_config(
                "tts.backends.piper.model_path",
                self._get_config(
                    "tts.piper.model_path",
                    r"C:\Files\Models\tts\piper\en_US-amy-medium.onnx",
                ),
            )
            t0 = time.perf_counter()
            self._piper_voice = PiperVoice.load(model_path)
            elapsed = (time.perf_counter() - t0) * 1000
            self._piper_loaded = True
            self._piper_model_path = model_path
            self._available_backends[TTSBackend.PIPER.value] = True
            logger.info("Piper loaded in %.0fms: %s", elapsed, model_path)
            return True
        except Exception as exc:
            logger.warning("Piper unavailable: %s", exc)
            self._available_backends[TTSBackend.PIPER.value] = False
            return False

    def _synth_piper(self, text: str, voice: str = "default") -> TTSResult:
        """Synthesize with Piper (fast, CPU).

        Args:
            text: Text to synthesize.
            voice: Voice identifier (ignored for now — uses loaded model).

        Returns:
            TTSResult with WAV audio.
        """
        if not self._ensure_piper():
            raise RuntimeError("Piper backend not available")

        t0 = time.perf_counter()
        all_audio: List[np.ndarray] = []
        for chunk in self._piper_voice.synthesize(text):
            all_audio.append(chunk.audio_float_array)

        if not all_audio:
            raise RuntimeError("Piper produced no audio")

        audio = np.concatenate(all_audio)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        sr = self._piper_voice.config.sample_rate
        duration = len(audio) / sr

        # Convert to WAV bytes
        pcm = (audio * 32767).astype(np.int16).tobytes()
        wav_bytes = self._pcm_to_wav(pcm, sr)

        return TTSResult(
            audio_bytes=wav_bytes,
            sample_rate=sr,
            duration=duration,
            backend=TTSBackend.PIPER.value,
            latency_ms=elapsed_ms,
            text=text,
            voice=voice,
        )

    # ── Orpheus Backend ─────────────────────────────────────────────────

    def _synth_orpheus(self, text: str, voice: str = "tara") -> TTSResult:
        """Synthesize with Orpheus (high quality, remote).

        Args:
            text: Text to synthesize.
            voice: Orpheus voice name (tara, leo, leah, etc.).

        Returns:
            TTSResult with WAV audio.
        """
        from engine.tts.orpheus_client import get_orpheus_client

        t0 = time.perf_counter()
        client = get_orpheus_client()
        path = client.generate(text, voice=voice)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        if not path or not Path(path).exists():
            raise RuntimeError("Orpheus produced no output file")

        wav_bytes = Path(path).read_bytes()
        duration = self._wav_duration(wav_bytes)
        sr = 24000  # Orpheus default

        self._available_backends[TTSBackend.ORPHEUS.value] = True
        return TTSResult(
            audio_bytes=wav_bytes,
            sample_rate=sr,
            duration=duration,
            backend=TTSBackend.ORPHEUS.value,
            latency_ms=elapsed_ms,
            text=text,
            voice=voice,
        )

    # ── Orpheus Native Backend ──────────────────────────────────────────

    def _synth_orpheus_native(self, text: str, voice: str = "tara") -> TTSResult:
        """Synthesize with native Orpheus (direct GGUF, no LMStudio).

        Args:
            text: Text to synthesize.
            voice: Orpheus voice name.

        Returns:
            TTSResult with WAV audio.
        """
        from engine.tts.orpheus_native import get_orpheus_native

        engine = get_orpheus_native(
            model_dir=self._get_config(
                "tts.backends.orpheus_native.model_dir",
                self._get_config("tts.backends.orpheus.model_dir",
                                 r"D:\Files\Models\Orpheous"),
            ),
        )
        quant = self._get_config("tts.backends.orpheus_native.default_quant", None)
        if quant is None:
            quant = engine.auto_select_quant(text)

        result = engine.synthesize(text, voice=voice, quant=quant)
        self._available_backends[TTSBackend.ORPHEUS_NATIVE.value] = True
        return TTSResult(
            audio_bytes=result.wav_bytes,
            sample_rate=result.sample_rate,
            duration=result.duration,
            backend=TTSBackend.ORPHEUS_NATIVE.value,
            latency_ms=result.latency_ms,
            text=text,
            voice=voice,
        )

    # ── Qwen3 Backend ───────────────────────────────────────────────────

    def _synth_qwen3(self, text: str, voice: str = "default") -> TTSResult:
        """Synthesize with Qwen3 TTS server (GPU).

        Args:
            text: Text to synthesize.
            voice: Voice design description.

        Returns:
            TTSResult with WAV audio.
        """
        import requests

        server_url = self._get_config("tts.server_url", "http://localhost:8600")
        t0 = time.perf_counter()
        resp = requests.post(
            f"{server_url}/generate",
            json={"text": text, "voice_design": voice},
            timeout=30,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        if resp.status_code != 200:
            raise RuntimeError(f"Qwen3 TTS error: {resp.status_code}")

        wav_bytes = resp.content
        duration = self._wav_duration(wav_bytes)

        self._available_backends[TTSBackend.QWEN3.value] = True
        return TTSResult(
            audio_bytes=wav_bytes,
            sample_rate=22050,
            duration=duration,
            backend=TTSBackend.QWEN3.value,
            latency_ms=elapsed_ms,
            text=text,
            voice=voice,
        )

    # ── Auto Selection ──────────────────────────────────────────────────

    def _select_backend(self, text: str) -> str:
        """Choose the best backend based on text, availability, and enabled state.

        Strategy:
            - Short text (<200 chars) → Piper (fastest)
            - Long text (>200 chars) → Orpheus Native or Orpheus API
            - Fallback → whatever is available and enabled

        Args:
            text: Text to synthesize.

        Returns:
            Backend name string.
        """
        char_count = len(text)

        # Try Piper for short text (real-time assistant replies)
        if (
            char_count < 200
            and self._enabled_backends.get(TTSBackend.PIPER.value)
            and self._ensure_piper()
        ):
            return TTSBackend.PIPER.value

        # Try native Orpheus (preferred — no LMStudio dependency)
        if self._enabled_backends.get(TTSBackend.ORPHEUS_NATIVE.value):
            return TTSBackend.ORPHEUS_NATIVE.value

        # Try Orpheus API (LMStudio-backed)
        if (
            self._enabled_backends.get(TTSBackend.ORPHEUS.value)
            and self._available_backends.get(TTSBackend.ORPHEUS.value)
        ):
            return TTSBackend.ORPHEUS.value

        # Fallback to Piper if enabled and available
        if self._enabled_backends.get(TTSBackend.PIPER.value) and self._ensure_piper():
            return TTSBackend.PIPER.value

        # Qwen3 as last resort
        if self._enabled_backends.get(TTSBackend.QWEN3.value):
            return TTSBackend.QWEN3.value

        # Nothing enabled — try anything
        if self._ensure_piper():
            return TTSBackend.PIPER.value
        return TTSBackend.QWEN3.value

    # ── Public API ──────────────────────────────────────────────────────

    def synthesize(
        self,
        text: str,
        backend: str = "auto",
        voice: str = "default",
    ) -> TTSResult:
        """Synthesize text to speech.

        Args:
            text: Text to speak.
            backend: Backend to use ("auto", "piper", "orpheus", "qwen3").
            voice: Voice identifier (backend-specific).

        Returns:
            TTSResult with audio bytes, timing, and metadata.

        Raises:
            RuntimeError: If no backend can synthesize.
        """
        if backend == "auto":
            backend = self._select_backend(text)

        dispatch = {
            TTSBackend.PIPER.value: self._synth_piper,
            TTSBackend.ORPHEUS.value: self._synth_orpheus,
            TTSBackend.ORPHEUS_NATIVE.value: self._synth_orpheus_native,
            TTSBackend.QWEN3.value: self._synth_qwen3,
        }

        synth_fn = dispatch.get(backend)
        if not synth_fn:
            raise ValueError(f"Unknown TTS backend: {backend}")

        try:
            result = synth_fn(text, voice)
            bench = self._benchmarks[backend]
            bench.total_calls += 1
            bench.total_latency_ms += result.latency_ms
            bench.total_audio_seconds += result.duration
            bench.last_latency_ms = result.latency_ms
            bench.last_rtf = (
                result.latency_ms / 1000.0 / max(result.duration, 0.001)
            )
            logger.info(
                "TTS [%s] %.0fms → %.1fs audio (RTF: %.3f)",
                backend,
                result.latency_ms,
                result.duration,
                bench.last_rtf,
            )
            return result
        except Exception as exc:
            self._benchmarks[backend].failures += 1
            logger.warning("TTS [%s] failed: %s", backend, exc)
            # Fallback to next backend if auto
            if backend != TTSBackend.PIPER.value and self._ensure_piper():
                logger.info("TTS falling back to Piper")
                return self._synth_piper(text, voice)
            raise

    def get_benchmarks(self) -> Dict[str, Dict[str, Any]]:
        """Get performance benchmarks for all backends.

        Returns:
            Dict of backend_name → benchmark stats.
        """
        result: Dict[str, Dict[str, Any]] = {}
        for name, bench in self._benchmarks.items():
            result[name] = {
                "total_calls": bench.total_calls,
                "avg_latency_ms": round(bench.avg_latency_ms, 1),
                "avg_rtf": round(bench.avg_rtf, 4),
                "last_latency_ms": round(bench.last_latency_ms, 1),
                "last_rtf": round(bench.last_rtf, 4),
                "failures": bench.failures,
                "total_audio_seconds": round(bench.total_audio_seconds, 1),
                "available": self._available_backends.get(name, False),
            }
        return result

    def list_backends(self) -> List[Dict[str, Any]]:
        """List all backends with their availability status.

        Returns:
            List of backend info dicts.
        """
        backends = [
            {
                "name": TTSBackend.PIPER.value,
                "label": "Piper (Fast)",
                "available": self._ensure_piper(),
                "enabled": self._enabled_backends.get(TTSBackend.PIPER.value, False),
                "description": "CPU-only ONNX, ~60ms/s, best for real-time",
                "model": self._piper_model_path or "not loaded",
            },
            {
                "name": TTSBackend.ORPHEUS.value,
                "label": "Orpheus API (LMStudio)",
                "available": self._available_backends.get(TTSBackend.ORPHEUS.value, False),
                "enabled": self._enabled_backends.get(TTSBackend.ORPHEUS.value, False),
                "description": "LMStudio-backed, 24 voices, emotion tags",
                "model": "orpheus-3b (via LMStudio)",
            },
            {
                "name": TTSBackend.ORPHEUS_NATIVE.value,
                "label": "Orpheus Native (GGUF)",
                "available": self._available_backends.get(TTSBackend.ORPHEUS_NATIVE.value, False),
                "enabled": self._enabled_backends.get(TTSBackend.ORPHEUS_NATIVE.value, False),
                "description": "Direct GGUF inference, multi-quant, no LMStudio",
                "model": "orpheus-3b GGUF",
            },
            {
                "name": TTSBackend.QWEN3.value,
                "label": "Qwen3 (GPU)",
                "available": self._available_backends.get(TTSBackend.QWEN3.value, False),
                "enabled": self._enabled_backends.get(TTSBackend.QWEN3.value, False),
                "description": "GPU-based, 0.6B/1.7B escalation mode",
                "model": "qwen3-tts",
            },
        ]
        return backends

    def health(self) -> Dict[str, Any]:
        """Check health of all TTS backends.

        Returns:
            Dict with overall status and per-backend health.
        """
        piper_ok = self._ensure_piper()

        orpheus_ok = False
        try:
            from engine.tts.orpheus_client import get_orpheus_client
            orpheus_ok = get_orpheus_client().health().get("status") == "ok"
            self._available_backends[TTSBackend.ORPHEUS.value] = orpheus_ok
        except Exception:
            self._available_backends[TTSBackend.ORPHEUS.value] = False

        orpheus_native_ok = False
        try:
            from engine.tts.orpheus_native import get_orpheus_native
            engine = get_orpheus_native()
            orpheus_native_ok = len(engine.list_models()) > 0
            self._available_backends[TTSBackend.ORPHEUS_NATIVE.value] = orpheus_native_ok
        except Exception:
            self._available_backends[TTSBackend.ORPHEUS_NATIVE.value] = False

        qwen3_ok = False
        try:
            import requests
            url = self._get_config("tts.server_url", "http://localhost:8600")
            r = requests.get(f"{url}/health", timeout=3)
            qwen3_ok = r.status_code == 200
            self._available_backends[TTSBackend.QWEN3.value] = qwen3_ok
        except Exception:
            self._available_backends[TTSBackend.QWEN3.value] = False

        any_ok = piper_ok or orpheus_ok or orpheus_native_ok or qwen3_ok
        return {
            "status": "ok" if any_ok else "degraded",
            "backends": {
                TTSBackend.PIPER.value: piper_ok,
                TTSBackend.ORPHEUS.value: orpheus_ok,
                TTSBackend.ORPHEUS_NATIVE.value: orpheus_native_ok,
                TTSBackend.QWEN3.value: qwen3_ok,
            },
            "benchmarks": self.get_benchmarks(),
        }

    # ── Utilities ───────────────────────────────────────────────────────

    @staticmethod
    def _pcm_to_wav(pcm: bytes, sample_rate: int, channels: int = 1, sample_width: int = 2) -> bytes:
        """Convert raw PCM to WAV bytes.

        Args:
            pcm: Raw PCM audio data.
            sample_rate: Sample rate in Hz.
            channels: Number of audio channels.
            sample_width: Bytes per sample.

        Returns:
            WAV file as bytes.
        """
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()

    @staticmethod
    def _wav_duration(wav_bytes: bytes) -> float:
        """Extract duration from WAV bytes.

        Args:
            wav_bytes: WAV file bytes.

        Returns:
            Duration in seconds.
        """
        try:
            buf = io.BytesIO(wav_bytes)
            with wave.open(buf, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / max(rate, 1)
        except Exception:
            return 0.0


# ── Module-level singleton ──────────────────────────────────────────────

_tts_manager: Optional[TTSManager] = None


def get_tts_manager(config: Optional[Any] = None) -> TTSManager:
    """Get the singleton TTSManager instance.

    Args:
        config: Optional config override (used on first call only).

    Returns:
        The global TTSManager instance.
    """
    global _tts_manager
    if _tts_manager is None:
        _tts_manager = TTSManager(config=config)
    return _tts_manager
