"""Native Orpheus TTS engine — direct GGUF inference via llama-cpp-python.

Bypasses LMStudio entirely, loading Orpheus GGUF models directly with
llama.cpp Python bindings. Supports multiple quant levels simultaneously
for adaptive quality/speed trade-offs:

- Q2_K (~1.5GB) — fast, lower quality, good for short UI feedback
- Q4_K_M (~2.3GB) — balanced quality/speed for most speech
- Q8_0 (~3.5GB) — highest quality for narrative/emotional speech

Each quant can run on GPU (n_gpu_layers=-1) or CPU (n_gpu_layers=0).

Usage::

    from engine.tts.orpheus_native import OrpheusNative, get_orpheus_native
    engine = get_orpheus_native()
    wav_bytes = engine.synthesize("Hello world!", voice="tara")
"""
from __future__ import annotations

import io
import logging
import os
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
    import torch
    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover — absent in lean CI / Python 3.13 venvs
    np = None  # type: ignore[assignment]
    torch = None  # type: ignore[assignment]
    _TORCH_AVAILABLE = False

# SNAC codec constants
SNAC_SAMPLE_RATE = 24000
START_OF_SPEECH = 128257
END_OF_SPEECH = 128258
START_OF_HUMAN = 128259
END_OF_HUMAN = 128260
START_OF_AI = 128261
END_OF_AI = 128262
AUDIO_TOKEN_OFFSET = 128266
CODEBOOK_SIZE = 4096

# Default voice
DEFAULT_VOICE = "tara"
AVAILABLE_VOICES = [
    "tara", "leo", "leah", "jess", "mia",
    "zac", "dan", "emma", "will", "nova",
]


@dataclass
class OrpheusModel:
    """A loaded Orpheus GGUF model instance."""

    path: str
    quant: str
    llm: Any = None
    on_gpu: bool = False
    load_time_ms: float = 0.0


@dataclass
class SynthResult:
    """Result from native Orpheus synthesis."""

    wav_bytes: bytes
    sample_rate: int = SNAC_SAMPLE_RATE
    duration: float = 0.0
    latency_ms: float = 0.0
    tokens_generated: int = 0
    tokens_per_sec: float = 0.0
    quant: str = ""
    voice: str = DEFAULT_VOICE


class OrpheusNative:
    """Native Orpheus TTS using llama-cpp-python for GGUF inference.

    Loads models directly without LMStudio. Supports multiple quants
    simultaneously for adaptive quality routing.

    Args:
        model_dir: Directory containing Orpheus GGUF files.
        default_quant: Default quantization to use.
        gpu_layers: Number of GPU layers (-1 for all, 0 for CPU).
        context_size: Context window size.
    """

    def __init__(
        self,
        model_dir: str = r"D:\Files\Models\Orpheous",
        default_quant: str = "q4_k_m",
        gpu_layers: int = -1,
        context_size: int = 8192,
    ) -> None:
        if not _TORCH_AVAILABLE:
            raise RuntimeError(
                "OrpheusNative requires torch and numpy. "
                "Install them with: pip install torch numpy"
            )
        self._model_dir = Path(model_dir)
        self._default_quant = default_quant.lower()
        self._gpu_layers = gpu_layers
        self._context_size = context_size
        self._models: Dict[str, OrpheusModel] = {}
        self._snac_model: Optional[Any] = None
        self._snac_device: str = "cpu"

        # Discover available GGUF files
        self._available_models = self._discover_models()
        logger.info(
            "OrpheusNative initialized: %d models found in %s",
            len(self._available_models),
            self._model_dir,
        )

    def _discover_models(self) -> Dict[str, str]:
        """Scan model directory for GGUF files and classify by quant.

        Returns:
            Dict mapping quant label to file path.
        """
        models: Dict[str, str] = {}
        if not self._model_dir.exists():
            logger.warning("Orpheus model dir not found: %s", self._model_dir)
            return models

        for gguf in self._model_dir.rglob("*.gguf"):
            name = gguf.stem.lower()
            size_mb = gguf.stat().st_size / (1024 * 1024)

            # Classify by filename or size
            if "q2_k" in name:
                quant = "q2_k"
            elif "q4_k_m" in name:
                quant = "q4_k_m"
            elif "q6_k" in name:
                quant = "q6_k"
            elif "q8_0" in name or "q8" in name:
                quant = "q8_0"
            elif size_mb < 1700:
                quant = "q2_k"
            elif size_mb < 2500:
                quant = "q4_k_m"
            else:
                quant = "q8_0"

            if quant not in models:
                models[quant] = str(gguf)
                logger.info(
                    "Orpheus model: %s (%s, %.0fMB)",
                    quant, gguf.name, size_mb,
                )

        return models

    def _ensure_snac(self) -> None:
        """Load SNAC codec model for audio decoding."""
        if self._snac_model is not None:
            return

        from snac import SNAC

        self._snac_device = "cuda" if torch.cuda.is_available() else "cpu"
        self._snac_model = SNAC.from_pretrained("hubertsiuzdak/snac_24khz").eval()
        self._snac_model = self._snac_model.to(self._snac_device)
        logger.info("SNAC codec loaded on %s", self._snac_device)

    def _load_model(self, quant: str, gpu_layers: Optional[int] = None) -> OrpheusModel:
        """Load a specific GGUF model.

        Args:
            quant: Quantization level (q2_k, q4_k_m, q8_0).
            gpu_layers: Override GPU layers (-1=all GPU, 0=CPU).

        Returns:
            Loaded OrpheusModel instance.
        """
        if quant in self._models:
            return self._models[quant]

        if quant not in self._available_models:
            raise ValueError(
                f"No {quant} model found. Available: {list(self._available_models)}"
            )

        # Fix CUDA_PATH — strip trailing \bin and prefer v12.4 for compatibility
        cuda_path = os.environ.get("CUDA_PATH", "")
        if cuda_path.endswith("\\bin"):
            os.environ["CUDA_PATH"] = cuda_path.rsplit("\\bin", 1)[0]
        cuda_12_4 = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4"
        if os.path.isdir(cuda_12_4) and "v13" in cuda_path:
            os.environ["CUDA_PATH"] = cuda_12_4

        from llama_cpp import Llama

        model_path = self._available_models[quant]
        layers = gpu_layers if gpu_layers is not None else self._gpu_layers
        on_gpu = layers != 0

        logger.info(
            "Loading Orpheus %s: %s (gpu_layers=%d)",
            quant, Path(model_path).name, layers,
        )

        t0 = time.perf_counter()
        llm = Llama(
            model_path=model_path,
            n_gpu_layers=layers,
            n_ctx=self._context_size,
            seed=-1,
            flash_attn=on_gpu,
            verbose=False,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        model = OrpheusModel(
            path=model_path,
            quant=quant,
            llm=llm,
            on_gpu=on_gpu,
            load_time_ms=elapsed_ms,
        )
        self._models[quant] = model
        logger.info(
            "Orpheus %s loaded in %.0fms (%s)",
            quant, elapsed_ms, "GPU" if on_gpu else "CPU",
        )
        return model

    def _format_prompt(self, text: str, voice: str) -> str:
        """Format text into Orpheus prompt format.

        Args:
            text: Input text to speak.
            voice: Voice name.

        Returns:
            Formatted prompt string.
        """
        return f"<|audio|>{voice}: {text}<|eot_id|>"

    def _generate_tokens(
        self,
        model: OrpheusModel,
        text: str,
        voice: str = DEFAULT_VOICE,
        temperature: float = 0.6,
        top_p: float = 0.9,
        repeat_penalty: float = 1.1,
        max_tokens: int = 8192,
    ) -> Tuple[List[int], float, int]:
        """Generate audio tokens from text.

        Args:
            model: Loaded OrpheusModel.
            text: Text to synthesize.
            voice: Voice name.
            temperature: Sampling temperature.
            top_p: Nucleus sampling threshold.
            repeat_penalty: Repetition penalty.
            max_tokens: Maximum tokens to generate.

        Returns:
            Tuple of (audio_codes, elapsed_seconds, token_count).
        """
        prompt = self._format_prompt(text, voice)
        input_tokens = model.llm.tokenize(prompt.encode(), add_bos=True, special=True)

        t0 = time.perf_counter()
        audio_tokens: List[int] = []
        token_count = 0

        for token in model.llm.generate(
            tokens=input_tokens,
            top_k=40,
            top_p=top_p,
            temp=temperature,
            repeat_penalty=repeat_penalty,
        ):
            token_count += 1

            if token == END_OF_SPEECH or token_count >= max_tokens:
                break

            if token >= AUDIO_TOKEN_OFFSET:
                audio_tokens.append(token)

        elapsed = time.perf_counter() - t0
        return audio_tokens, elapsed, token_count

    def _decode_audio(self, codes: List[int]) -> np.ndarray:
        """Decode SNAC audio tokens to PCM waveform.

        Args:
            codes: Raw audio token codes from the LLM.

        Returns:
            Float32 numpy array of audio samples at 24kHz.
        """
        self._ensure_snac()

        # Strip offset and organize into codec layers
        codes = [c - AUDIO_TOKEN_OFFSET for c in codes]
        # Ensure divisible by 7 (7 tokens per audio frame)
        codes = codes[: len(codes) // 7 * 7]

        if len(codes) == 0:
            return np.zeros(SNAC_SAMPLE_RATE, dtype=np.float32)

        layer_0: List[int] = []
        layer_1: List[int] = []
        layer_2: List[int] = []

        for i in range(len(codes) // 7):
            base = 7 * i
            layer_0.append(codes[base])
            layer_1.append(codes[base + 1] - CODEBOOK_SIZE)
            layer_2.append(codes[base + 2] - 2 * CODEBOOK_SIZE)
            layer_2.append(codes[base + 3] - 3 * CODEBOOK_SIZE)
            layer_1.append(codes[base + 4] - 4 * CODEBOOK_SIZE)
            layer_2.append(codes[base + 5] - 5 * CODEBOOK_SIZE)
            layer_2.append(codes[base + 6] - 6 * CODEBOOK_SIZE)

        codec_layers = [
            torch.tensor([layer_0], dtype=torch.long, device=self._snac_device),
            torch.tensor([layer_1], dtype=torch.long, device=self._snac_device),
            torch.tensor([layer_2], dtype=torch.long, device=self._snac_device),
        ]

        with torch.inference_mode():
            audio = self._snac_model.decode(codec_layers)

        return audio.float().squeeze().cpu().numpy()

    def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        quant: Optional[str] = None,
        gpu_layers: Optional[int] = None,
        temperature: float = 0.6,
    ) -> SynthResult:
        """Synthesize text to speech using native GGUF inference.

        Args:
            text: Text to speak.
            voice: Voice name (tara, leo, leah, etc.).
            quant: Quantization level (q2_k, q4_k_m, q8_0). None=default.
            gpu_layers: Override GPU layers. None=use default.
            temperature: Sampling temperature.

        Returns:
            SynthResult with WAV bytes and metrics.
        """
        quant = (quant or self._default_quant).lower()
        if voice not in AVAILABLE_VOICES:
            voice = DEFAULT_VOICE

        t0 = time.perf_counter()

        model = self._load_model(quant, gpu_layers)
        audio_tokens, gen_time, token_count = self._generate_tokens(
            model, text, voice, temperature=temperature,
        )

        if not audio_tokens:
            logger.warning("No audio tokens generated for: %s", text[:50])
            # Return silence
            silence = np.zeros(SNAC_SAMPLE_RATE, dtype=np.float32)
            wav_bytes = self._to_wav(silence)
            return SynthResult(
                wav_bytes=wav_bytes, duration=1.0,
                latency_ms=(time.perf_counter() - t0) * 1000,
                quant=quant, voice=voice,
            )

        audio = self._decode_audio(audio_tokens)
        total_ms = (time.perf_counter() - t0) * 1000
        duration = len(audio) / SNAC_SAMPLE_RATE
        tps = token_count / gen_time if gen_time > 0 else 0

        wav_bytes = self._to_wav(audio)

        logger.info(
            "Orpheus native [%s] %.0fms → %.1fs audio (%.1f tok/s, %d tokens)",
            quant, total_ms, duration, tps, token_count,
        )

        return SynthResult(
            wav_bytes=wav_bytes,
            duration=duration,
            latency_ms=total_ms,
            tokens_generated=token_count,
            tokens_per_sec=tps,
            quant=quant,
            voice=voice,
        )

    def auto_select_quant(self, text: str) -> str:
        """Select best quant based on text length and available models.

        Strategy:
            - <50 chars → Q2_K (fastest, fine for short utterances)
            - 50-300 chars → Q4_K_M (balanced)
            - >300 chars → Q4_K_M or Q8_0 (quality matters for long text)

        Args:
            text: Input text.

        Returns:
            Quant label string.
        """
        char_count = len(text)
        if char_count < 50 and "q2_k" in self._available_models:
            return "q2_k"
        if "q4_k_m" in self._available_models:
            return "q4_k_m"
        if "q8_0" in self._available_models:
            return "q8_0"
        if "q2_k" in self._available_models:
            return "q2_k"
        raise RuntimeError("No Orpheus GGUF models available")

    def benchmark(
        self,
        quant: Optional[str] = None,
        gpu_layers: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run a benchmark on a specific quant level.

        Args:
            quant: Quantization to benchmark. None=all available.
            gpu_layers: Override GPU layers.

        Returns:
            Benchmark results dict.
        """
        test_texts = [
            ("tiny", "Hello there."),
            ("short", "The weather is beautiful today, perfect for a walk."),
            ("medium", "In the grand tapestry of human civilization, few inventions "
             "have been as transformative as the printing press. Before Gutenberg, "
             "knowledge was locked away in hand-copied manuscripts."),
            ("long", "The ancient library stood at the crossroads of two great "
             "civilizations. Its halls echoed with whispered conversations between "
             "scholars who had traveled thousands of miles to consult its vast "
             "collection of scrolls and codices. Among them was a young woman "
             "who carried with her a single question."),
        ]

        quants = [quant] if quant else list(self._available_models.keys())
        results: Dict[str, Any] = {}

        for q in quants:
            q_results: List[Dict[str, Any]] = []
            logger.info("Benchmarking Orpheus %s...", q)

            for label, text in test_texts:
                try:
                    result = self.synthesize(text, quant=q, gpu_layers=gpu_layers)
                    rtf = (result.latency_ms / 1000) / max(result.duration, 0.001)
                    entry = {
                        "label": label,
                        "words": len(text.split()),
                        "latency_s": round(result.latency_ms / 1000, 1),
                        "audio_s": round(result.duration, 1),
                        "rtf": round(rtf, 2),
                        "tokens": result.tokens_generated,
                        "tok_per_sec": round(result.tokens_per_sec, 1),
                    }
                    q_results.append(entry)
                except Exception as exc:
                    q_results.append({"label": label, "error": str(exc)})
                    logger.error("Benchmark %s/%s failed: %s", q, label, exc)

            results[q] = q_results

        return results

    def list_models(self) -> List[Dict[str, Any]]:
        """List all available and loaded models.

        Returns:
            List of model info dicts.
        """
        result: List[Dict[str, Any]] = []
        for quant, path in self._available_models.items():
            loaded = quant in self._models
            info: Dict[str, Any] = {
                "quant": quant,
                "path": path,
                "size_mb": round(Path(path).stat().st_size / (1024 * 1024)),
                "loaded": loaded,
            }
            if loaded:
                m = self._models[quant]
                info["on_gpu"] = m.on_gpu
                info["load_time_ms"] = round(m.load_time_ms)
            result.append(info)
        return result

    def unload_model(self, quant: str) -> bool:
        """Unload a specific model to free memory.

        Args:
            quant: Quantization level to unload.

        Returns:
            True if model was unloaded.
        """
        if quant not in self._models:
            return False
        model = self._models.pop(quant)
        if hasattr(model.llm, "close"):
            model.llm.close()
        if hasattr(model.llm, "_sampler") and model.llm._sampler:
            model.llm._sampler.close()
        logger.info("Unloaded Orpheus %s", quant)
        return True

    def unload_all(self) -> None:
        """Unload all models and free memory."""
        for quant in list(self._models.keys()):
            self.unload_model(quant)
        self._snac_model = None
        torch.cuda.empty_cache() if torch.cuda.is_available() else None

    @staticmethod
    def _to_wav(audio: np.ndarray, sample_rate: int = SNAC_SAMPLE_RATE) -> bytes:
        """Convert float32 audio to WAV bytes.

        Args:
            audio: Float32 audio samples.
            sample_rate: Sample rate in Hz.

        Returns:
            WAV file bytes.
        """
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()


# ── Module-level singleton ──────────────────────────────────────────────

_orpheus_native: Optional[OrpheusNative] = None


def get_orpheus_native(**kwargs: Any) -> OrpheusNative:
    """Get the singleton OrpheusNative instance.

    Args:
        **kwargs: Passed to OrpheusNative constructor on first call.

    Returns:
        The global OrpheusNative instance.
    """
    global _orpheus_native
    if _orpheus_native is None:
        _orpheus_native = OrpheusNative(**kwargs)
    return _orpheus_native
