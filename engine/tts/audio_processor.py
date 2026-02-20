"""
Audio Post-Processor — trim, normalize, fade, stitch

Runs on CPU (i9) while GPU handles TTS generation.
Provides clinical audio cleanup: silence trimming, volume normalization,
and fade in/out to eliminate pops between stitched clips.
"""
from __future__ import annotations

import io
import logging
import struct
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Optional deps — degrade gracefully
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

try:
    import librosa
    import soundfile as sf
    _HAS_LIBROSA = True
except ImportError:
    _HAS_LIBROSA = False


class AudioProcessor:
    """Post-process TTS audio on CPU."""

    def __init__(
        self,
        trim_db: float = 20.0,
        fade_ms: float = 50.0,
        target_sr: int = 24000,
    ):
        self.trim_db = trim_db
        self.fade_ms = fade_ms
        self.target_sr = target_sr

    def process_bytes(self, audio_bytes: bytes, sr: int = 24000) -> bytes:
        """Full pipeline: trim → normalize → fade. Returns WAV bytes."""
        if not _HAS_LIBROSA:
            return self._process_basic(audio_bytes, sr)

        y, sr = librosa.load(io.BytesIO(audio_bytes), sr=sr)

        # 1. Trim silence
        y_trimmed, _ = librosa.effects.trim(y, top_db=self.trim_db)

        # 2. Normalize
        y_norm = librosa.util.normalize(y_trimmed)

        # 3. Fade in/out
        fade_len = int(self.fade_ms / 1000.0 * sr)
        if len(y_norm) > fade_len * 2:
            fade_in = np.linspace(0, 1, fade_len)
            fade_out = np.linspace(1, 0, fade_len)
            y_norm[:fade_len] *= fade_in
            y_norm[-fade_len:] *= fade_out

        buf = io.BytesIO()
        sf.write(buf, y_norm, sr, format='WAV')
        return buf.getvalue()

    def process_file(self, filepath: Path, output: Optional[Path] = None) -> Path:
        """Process a WAV file in-place or to a new file."""
        output = output or filepath
        with open(filepath, 'rb') as f:
            raw = f.read()
        processed = self.process_bytes(raw, self.target_sr)
        with open(output, 'wb') as f:
            f.write(processed)
        return output

    def stitch_files(self, filepaths: list[Path], output: Path, gap_ms: float = 100) -> Path:
        """Concatenate multiple WAV files with a gap between them."""
        if not _HAS_NUMPY:
            return self._stitch_basic(filepaths, output)

        all_audio = []
        gap_samples = int(gap_ms / 1000.0 * self.target_sr)
        silence = np.zeros(gap_samples, dtype=np.float32)

        for fp in filepaths:
            try:
                if _HAS_LIBROSA:
                    y, _ = librosa.load(str(fp), sr=self.target_sr)
                else:
                    y = self._read_wav_numpy(fp)
                all_audio.append(y)
                all_audio.append(silence)
            except Exception as e:
                logger.warning("Skipping file %s: %s", fp, e)
                continue

        if not all_audio:
            return output

        combined = np.concatenate(all_audio)
        # Normalize combined
        peak = np.abs(combined).max()
        if peak > 0:
            combined = combined / peak * 0.95

        audio_int16 = (combined * 32767).astype(np.int16)
        with wave.open(str(output), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.target_sr)
            wf.writeframes(audio_int16.tobytes())

        logger.info("Stitched %d files → %s (%.1fs)", len(filepaths), output.name,
                     len(combined) / self.target_sr)
        return output

    # ── Fallbacks for when librosa isn't installed ──

    def _process_basic(self, audio_bytes: bytes, sr: int) -> bytes:
        """Basic normalization without librosa."""
        if not _HAS_NUMPY:
            return audio_bytes
        try:
            with wave.open(io.BytesIO(audio_bytes), 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                sr = wf.getframerate()
            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
            peak = np.abs(samples).max()
            if peak > 0:
                samples = samples / peak * 0.95
            # Simple fade
            fade_len = int(self.fade_ms / 1000.0 * sr)
            if len(samples) > fade_len * 2:
                samples[:fade_len] *= np.linspace(0, 1, fade_len)
                samples[-fade_len:] *= np.linspace(1, 0, fade_len)
            buf = io.BytesIO()
            audio_int16 = (samples * 32767).astype(np.int16)
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(audio_int16.tobytes())
            return buf.getvalue()
        except Exception:
            return audio_bytes

    def _read_wav_numpy(self, filepath: Path) -> np.ndarray:
        """Read WAV to numpy without librosa."""
        with wave.open(str(filepath), 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
        return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0

    def _stitch_basic(self, filepaths: list[Path], output: Path) -> Path:
        """Stitch without numpy — raw concatenation."""
        all_frames = b""
        sr = self.target_sr
        for fp in filepaths:
            try:
                with wave.open(str(fp), 'rb') as wf:
                    sr = wf.getframerate()
                    all_frames += wf.readframes(wf.getnframes())
                    # Add gap
                    gap = int(0.1 * sr) * 2  # 100ms of silence (16-bit mono)
                    all_frames += b'\x00' * gap
            except Exception as e:
                logger.warning("Failed to read audio file %s: %s", fp, e)
                continue

        if not all_frames:
            raise ValueError("No valid audio files to stitch")

        with wave.open(str(output), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(all_frames)
        return output
