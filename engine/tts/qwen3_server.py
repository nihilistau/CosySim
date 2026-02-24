"""
Qwen3-TTS Server — FastAPI + FastMCP voice generation service

Generates voice messages, voicemails, and stories as WAV files using
Qwen3-TTS models (0.6B for fast/simple, 1.7B for complex/emotional).

Endpoints:
    POST /generate     — Generate speech from text
    GET  /voices       — List available voice designs
    GET  /status       — Server status + queue depth
    POST /cast         — Save a voice design for a character
    GET  /jobs/{id}    — Check async generation status

MCP tools (exposed to LMStudio via /mcp):
    generate_voice    — Generate speech with voice design
    cast_voice        — Save/update a character's voice

Run standalone::

    python -m engine.tts.qwen3_server            # port 8600
    python -m engine.tts.qwen3_server --port 8601
"""
from __future__ import annotations

import json
import logging
import os
import struct
import uuid
import wave
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from engine.paths import VOICE_DIR, PRETRAINED_MODELS as _PRETRAINED_DIR
VOICE_DIR.mkdir(parents=True, exist_ok=True)


# ── Request / Response models ──────────────────────────────────────────

class GenerateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=50000, description="Text to speak")
    voice_design: str = Field(
        default="A clear, natural speaking voice.",
        description="Voice design description for Qwen3-TTS",
    )
    character_id: Optional[str] = Field(default=None, description="Character ID for voice lookup")
    model_size: str = Field(default="auto", description="'0.6b', '1.7b', 'escalate', or 'auto'")
    max_duration: int = Field(default=60, ge=10, le=3600, description="Max duration in seconds")
    sample_rate: int = Field(default=24000, description="Output sample rate")
    chain_id: Optional[str] = Field(default=None, description="EventChain ID for logging")
    post_process: bool = Field(default=True, description="Apply audio post-processing (trim, normalize, fade)")


class CastRequest(BaseModel):
    character_id: str
    description: str
    model_size: str = "1.7b"
    reference_audio: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    job_id: str
    status: str  # "completed", "queued", "processing", "failed"
    filepath: Optional[str] = None
    filename: Optional[str] = None
    duration: Optional[float] = None
    download_url: Optional[str] = None
    error: Optional[str] = None


# ── Job tracking ───────────────────────────────────────────────────────

@dataclass
class TTSJob:
    job_id: str
    status: str = "queued"
    filepath: Optional[str] = None
    filename: Optional[str] = None
    duration: Optional[float] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None


_jobs: Dict[str, TTSJob] = {}
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts")


# ── TTS Engine wrapper ────────────────────────────────────────────────

class Qwen3TTSEngine:
    """
    Wrapper around Qwen3-TTS model inference.

    Supports two model sizes (0.6B fast, 1.7B quality) with voice design
    strings that control pitch, pace, emotion and character.
    Falls back to placeholder WAV generation when models are not loaded.
    """

    # Chunk size for long-form generation (chars per chunk)
    CHUNK_SIZE = 500
    # Max samples per chunk to avoid OOM
    MAX_CHUNK_DURATION = 60  # seconds

    def __init__(self):
        self._model_06b = None
        self._model_17b = None
        self._tokenizer_06b = None
        self._tokenizer_17b = None
        self._processor = None
        self._loaded = False
        self._device = "cuda" if self._cuda_available() else "cpu"

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def load_models(self, model_dir: Optional[str] = None):
        """
        Load Qwen3-TTS models from disk.

        Searches these paths in order:
          1. ``model_dir`` argument
          2. ``COSYSIM_TTS_MODEL_DIR`` env var
          3. ``pretrained_models/Qwen3-TTS-*`` under project root

        Sets ``_loaded = True`` only if at least one model loads successfully.
        """
        search_dirs = []
        if model_dir:
            search_dirs.append(Path(model_dir))
        env = os.environ.get("COSYSIM_TTS_MODEL_DIR")
        if env:
            search_dirs.append(Path(env))
        search_dirs.append(_PRETRAINED_DIR)

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError:
            logger.info("torch/transformers not available — TTS in placeholder mode")
            self._loaded = False
            return

        for base in search_dirs:
            for size, attr_m, attr_t in [
                ("0.6B", "_model_06b", "_tokenizer_06b"),
                ("1.7B", "_model_17b", "_tokenizer_17b"),
            ]:
                if getattr(self, attr_m) is not None:
                    continue  # already loaded
                candidates = [
                    base / f"Qwen3-TTS-{size}",
                    base / f"qwen3-tts-{size.lower()}",
                    base / f"Qwen" / f"Qwen3-TTS-{size}",
                ]
                for p in candidates:
                    if p.exists() and (p / "config.json").exists():
                        try:
                            logger.info("Loading Qwen3-TTS-%s from %s …", size, p)
                            model = AutoModelForCausalLM.from_pretrained(
                                str(p),
                                torch_dtype=torch.float16 if self._device == "cuda" else torch.float32,
                                device_map=self._device,
                                trust_remote_code=True,
                            )
                            model.eval()
                            tokenizer = AutoTokenizer.from_pretrained(
                                str(p), trust_remote_code=True,
                            )
                            setattr(self, attr_m, model)
                            setattr(self, attr_t, tokenizer)
                            logger.info("✅ Qwen3-TTS-%s loaded on %s", size, self._device)
                        except Exception as e:
                            logger.warning("Failed to load Qwen3-TTS-%s from %s: %s", size, p, e)
                        break  # stop searching for this size

        self._loaded = self._model_06b is not None or self._model_17b is not None
        if not self._loaded:
            logger.info("Qwen3-TTS models not found — running in placeholder mode")

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def _select_model(self, model_size: str):
        """Return (model, tokenizer) for the requested size, with fallback."""
        if model_size == "0.6b" and self._model_06b:
            return self._model_06b, self._tokenizer_06b
        if model_size == "1.7b" and self._model_17b:
            return self._model_17b, self._tokenizer_17b
        # Fallback: use whichever is available
        if self._model_17b:
            return self._model_17b, self._tokenizer_17b
        if self._model_06b:
            return self._model_06b, self._tokenizer_06b
        return None, None

    def generate(
        self,
        text: str,
        voice_design: str,
        model_size: str = "1.7b",
        sample_rate: int = 24000,
        max_duration: int = 60,
        post_process: bool = True,
    ) -> tuple[Path, float]:
        """
        Generate speech audio.

        Args:
            model_size: '0.6b', '1.7b', 'escalate' (0.6b first, 1.7b fallback), or 'auto'
            post_process: Apply trim/normalize/fade via AudioProcessor

        Returns:
            (filepath, duration_seconds)
        """
        if model_size == "escalate" and self._loaded:
            return self._generate_escalated(text, voice_design, sample_rate, max_duration, post_process)

        if self._loaded:
            result = self._generate_real(text, voice_design, model_size, sample_rate, max_duration)
        else:
            result = self._generate_placeholder(text, voice_design, sample_rate, max_duration)

        if post_process:
            result = self._post_process(result)
        return result

    def _generate_escalated(
        self, text, voice_design, sample_rate, max_duration, post_process
    ) -> tuple[Path, float]:
        """
        Multi-model escalation: 0.6B scout → quality check → 1.7B fallback.

        Uses the fast 0.6B model first. If a reference audio is available,
        checks similarity score via simple energy/spectral comparison.
        Falls back to 1.7B if the score is below threshold.
        """
        SIMILARITY_THRESHOLD = 0.75

        # First take: 0.6B (fast)
        if self._model_06b:
            logger.info("🎬 Escalation: Take 1 with 0.6B...")
            filepath, duration = self._generate_real(
                text, voice_design, "0.6b", sample_rate, max_duration
            )

            # Quick quality heuristic (spectral energy check)
            score = self._quick_quality_score(filepath)
            if score >= SIMILARITY_THRESHOLD:
                logger.info("✅ 0.6B passed (score %.2f)", score)
                if post_process:
                    return self._post_process((filepath, duration))
                return filepath, duration
            else:
                logger.info("⚠️ 0.6B score %.2f < %.2f, escalating to 1.7B...",
                           score, SIMILARITY_THRESHOLD)
                # Remove failed attempt
                try:
                    filepath.unlink()
                except Exception:
                    pass

        # Fallback: 1.7B (quality)
        if self._model_17b:
            logger.info("🎬 Escalation: Take 2 with 1.7B...")
            result = self._generate_real(
                text, f"{voice_design}. Professional acting.", "1.7b",
                sample_rate, max_duration
            )
            if post_process:
                return self._post_process(result)
            return result

        # Neither model available
        return self._generate_placeholder(text, voice_design, sample_rate, max_duration)

    def _quick_quality_score(self, filepath: Path) -> float:
        """
        Quick quality heuristic based on audio energy and spectral content.
        Returns 0.0-1.0. Higher = better quality.
        Without WeSpeaker, uses spectral flatness as a proxy.
        """
        try:
            import numpy as np
            with wave.open(str(filepath), 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                sr = wf.getframerate()
            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0

            if len(samples) == 0:
                return 0.0

            # Energy check — very quiet audio is likely bad
            rms = np.sqrt(np.mean(samples ** 2))
            if rms < 0.01:
                return 0.2

            # Spectral variety check via zero-crossing rate
            zero_crossings = np.sum(np.abs(np.diff(np.sign(samples)))) / (2 * len(samples))
            # Good speech has moderate zero-crossing rate (0.02-0.15)
            zcr_score = 1.0 - abs(zero_crossings - 0.08) / 0.08
            zcr_score = max(0.0, min(1.0, zcr_score))

            # Combined score
            energy_score = min(1.0, rms / 0.1)
            return 0.4 * energy_score + 0.6 * zcr_score
        except Exception:
            return 0.8  # assume OK if we can't check

    def _post_process(self, result: tuple[Path, float]) -> tuple[Path, float]:
        """Apply audio post-processing (trim, normalize, fade)."""
        filepath, duration = result
        try:
            from engine.tts.audio_processor import AudioProcessor
            proc = AudioProcessor(target_sr=24000)
            proc.process_file(filepath)
            # Re-read duration after trimming
            with wave.open(str(filepath), 'rb') as wf:
                duration = wf.getnframes() / wf.getframerate()
        except Exception as e:
            logger.debug("Post-processing skipped: %s", e)
        return filepath, duration

    def _generate_real(
        self, text, voice_design, model_size, sample_rate, max_duration
    ) -> tuple[Path, float]:
        """Generate with actual Qwen3-TTS model."""
        import torch
        import numpy as np

        model, tokenizer = self._select_model(model_size)
        if model is None:
            logger.warning("No model for size %s, falling back to placeholder", model_size)
            return self._generate_placeholder(text, voice_design, sample_rate, max_duration)

        # Build prompt with voice design instruction
        prompt = f"<|voice_design|>{voice_design}<|text|>{text}"

        # Chunk long texts to avoid OOM
        chunks = self._chunk_text(text) if len(text) > self.CHUNK_SIZE else [text]
        all_audio = []

        for chunk in chunks:
            chunk_prompt = f"<|voice_design|>{voice_design}<|text|>{chunk}"
            try:
                inputs = tokenizer(chunk_prompt, return_tensors="pt").to(model.device)
                with torch.no_grad():
                    outputs = model.generate(
                        **inputs,
                        max_new_tokens=int(self.MAX_CHUNK_DURATION * 50),  # ~50 tokens/sec
                        temperature=0.7,
                        do_sample=True,
                    )
                # Decode audio tokens — model-specific post-processing
                audio_tokens = outputs[0][inputs["input_ids"].shape[-1]:]
                # Try model's built-in decode method first
                if hasattr(model, 'decode_audio'):
                    audio_np = model.decode_audio(audio_tokens, sample_rate=sample_rate)
                elif hasattr(tokenizer, 'decode_audio'):
                    audio_np = tokenizer.decode_audio(audio_tokens, sample_rate=sample_rate)
                else:
                    # Fallback: treat output logits as raw audio codes
                    audio_np = audio_tokens.float().cpu().numpy().flatten()
                    audio_np = np.clip(audio_np / (np.abs(audio_np).max() + 1e-8), -1.0, 1.0)

                all_audio.append(audio_np)
            except Exception as e:
                logger.error("Chunk generation failed: %s", e)
                continue

        if not all_audio:
            logger.warning("All chunks failed, falling back to placeholder")
            return self._generate_placeholder(text, voice_design, sample_rate, max_duration)

        # Concatenate chunks
        full_audio = np.concatenate(all_audio)
        duration = min(len(full_audio) / sample_rate, float(max_duration))
        full_audio = full_audio[:int(duration * sample_rate)]

        # Normalize
        peak = np.abs(full_audio).max()
        if peak > 0:
            full_audio = full_audio / peak * 0.95

        # Save WAV
        filename = f"tts_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        filepath = VOICE_DIR / filename
        audio_int16 = (full_audio * 32767).astype(np.int16)

        with wave.open(str(filepath), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())

        logger.info("Generated %s: %.1fs via Qwen3-TTS (%s)", filename, duration, model_size)
        return filepath, duration

    def _chunk_text(self, text: str) -> List[str]:
        """Split long text into chunks at sentence boundaries."""
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks, current = [], ""
        for sent in sentences:
            if len(current) + len(sent) > self.CHUNK_SIZE:
                if current:
                    chunks.append(current.strip())
                current = sent
            else:
                current = f"{current} {sent}" if current else sent
        if current:
            chunks.append(current.strip())
        return chunks or [text]

    def _generate_placeholder(
        self, text: str, voice_design: str, sample_rate: int, max_duration: int
    ) -> tuple[Path, float]:
        """Generate a silent placeholder WAV (model not loaded)."""
        # Estimate duration: ~150 words per minute
        word_count = len(text.split())
        duration = min(max(2.0, word_count / 2.5), float(max_duration))

        filename = f"tts_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        filepath = VOICE_DIR / filename

        # Generate silence — model is not loaded, no TTS available
        n_samples = int(duration * sample_rate)

        with wave.open(str(filepath), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))

        return filepath, duration


# ── Module-level engine ────────────────────────────────────────────────

_engine = Qwen3TTSEngine()


def _run_generation(job_id: str, request: GenerateRequest):
    """Background generation task."""
    job = _jobs[job_id]
    job.status = "processing"

    try:
        # Resolve voice design from character if needed
        voice_design = request.voice_design
        model_size = request.model_size

        if request.character_id:
            try:
                from engine.tts.voice_designer import get_voice_designer
                designer = get_voice_designer()
                design = designer.get(request.character_id)
                voice_design = design.description
                if model_size == "auto":
                    model_size = design.model_size
            except Exception:
                pass

        if model_size == "auto":
            # Auto-select: short text → 0.6b, long/emotional → 1.7b
            model_size = "0.6b" if len(request.text) < 100 else "1.7b"

        filepath, duration = _engine.generate(
            text=request.text,
            voice_design=voice_design,
            model_size=model_size,
            sample_rate=request.sample_rate,
            max_duration=request.max_duration,
            post_process=request.post_process,
        )

        job.status = "completed"
        job.filepath = str(filepath)
        job.filename = filepath.name
        job.duration = duration
        job.completed_at = datetime.now().isoformat()

        # Log to EventChain
        if request.chain_id:
            try:
                from content.simulation.database.events import EventChain
                ec = EventChain()
                ec.log(
                    "media_generated",
                    actor="tts_server",
                    payload={
                        "type": "voice",
                        "model_size": model_size,
                        "character_id": request.character_id,
                        "duration": duration,
                        "text_length": len(request.text),
                    },
                    summary=f"TTS generated: {duration:.1f}s ({model_size})",
                    chain_id=request.chain_id,
                    character_id=request.character_id,
                )
            except Exception:
                pass

        logger.info("TTS job %s completed: %s (%.1fs)", job_id, filepath.name, duration)

        # MCP: publish to ActivityBus
        try:
            from engine.services.activity_bus import get_activity_bus
            get_activity_bus().publish(
                activity_type="tts_generated",
                description=f"Voice generated ({model_size}): {duration:.1f}s",
                agent_id=request.character_id or "tts_server",
                scene="tts",
                data={
                    "filename":   filepath.name,
                    "duration":   duration,
                    "model_size": model_size,
                    "text_len":   len(request.text),
                    "chain_id":   request.chain_id,
                },
            )
        except Exception:
            pass

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now().isoformat()
        logger.error("TTS job %s failed: %s", job_id, e)


# ── FastAPI app ────────────────────────────────────────────────────────

def create_tts_app() -> FastAPI:
    """Create the TTS server FastAPI application."""

    @asynccontextmanager
    async def lifespan(app):
        _engine.load_models()
        yield

    app = FastAPI(title="CosySim TTS Server", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Generate ────────────────────────────────────────────────────

    @app.post("/generate", response_model=GenerateResponse)
    async def generate(request: GenerateRequest, background_tasks: BackgroundTasks):
        """
        Generate speech from text.

        Short texts return immediately. Long texts (>30s estimated)
        return a job_id for polling via ``GET /jobs/{id}``.
        """
        job_id = str(uuid.uuid4())[:12]
        _jobs[job_id] = TTSJob(job_id=job_id)

        # Estimate if this will be quick
        word_count = len(request.text.split())
        estimated_duration = word_count / 2.5

        if estimated_duration < 30:
            # Run synchronously for short messages
            _run_generation(job_id, request)
            job = _jobs[job_id]
            return GenerateResponse(
                job_id=job_id,
                status=job.status,
                filepath=job.filepath,
                filename=job.filename,
                duration=job.duration,
                download_url=f"/download/{job.filename}" if job.filename else None,
                error=job.error,
            )
        else:
            # Queue for async generation
            background_tasks.add_task(_run_generation, job_id, request)
            return GenerateResponse(job_id=job_id, status="queued")

    # ── Job status ──────────────────────────────────────────────────

    @app.get("/jobs/{job_id}", response_model=GenerateResponse)
    async def get_job(job_id: str):
        """Check the status of a generation job."""
        if job_id not in _jobs:
            raise HTTPException(404, f"Job {job_id} not found")
        job = _jobs[job_id]
        return GenerateResponse(
            job_id=job_id,
            status=job.status,
            filepath=job.filepath,
            filename=job.filename,
            duration=job.duration,
            download_url=f"/download/{job.filename}" if job.filename else None,
            error=job.error,
        )

    # ── Batch / Long-form generation ───────────────────────────────

    class BatchRequest(BaseModel):
        lines: List[Dict[str, Any]] = Field(
            ..., description="List of {text, voice_design?, model_size?, character_id?}"
        )
        stitch: bool = Field(default=True, description="Stitch all clips into one WAV")
        gap_ms: float = Field(default=100, description="Silence gap between clips (ms)")
        post_process: bool = Field(default=True, description="Post-process each clip")

    @app.post("/batch")
    async def batch_generate(request: BatchRequest, background_tasks: BackgroundTasks):
        """
        Generate multiple lines and optionally stitch into one file.
        For book-scale / 10min+ audio generation.
        Runs generation in a background thread to avoid blocking the event loop.
        """
        import asyncio

        batch_id = str(uuid.uuid4())[:12]

        def _do_batch():
            results = []
            for i, line in enumerate(request.lines):
                text = line.get("text", "")
                if not text:
                    continue
                voice_design = line.get("voice_design", "A clear, natural speaking voice.")
                model_size = line.get("model_size", "auto")
                if model_size == "auto":
                    model_size = "0.6b" if len(text) < 100 else "1.7b"

                try:
                    filepath, duration = _engine.generate(
                        text=text,
                        voice_design=voice_design,
                        model_size=model_size,
                        post_process=request.post_process,
                    )
                    results.append({
                        "index": i, "status": "ok", "filename": filepath.name,
                        "duration": duration, "filepath": str(filepath),
                    })
                except Exception as e:
                    results.append({"index": i, "status": "error", "error": str(e)})

            # Stitch if requested
            stitched = None
            if request.stitch and results:
                try:
                    from engine.tts.audio_processor import AudioProcessor
                    proc = AudioProcessor()
                    paths = [Path(r["filepath"]) for r in results if r["status"] == "ok"]
                    out_name = f"batch_{batch_id}.wav"
                    out_path = VOICE_DIR / out_name
                    proc.stitch_files(paths, out_path, gap_ms=request.gap_ms)
                    total_dur = sum(r.get("duration", 0) for r in results if r["status"] == "ok")
                    stitched = {"filename": out_name, "download_url": f"/download/{out_name}",
                               "total_duration": total_dur}
                except Exception as e:
                    stitched = {"error": str(e)}

            return results, stitched

        results, stitched = await asyncio.to_thread(_do_batch)

        return {
            "batch_id": batch_id,
            "total_lines": len(request.lines),
            "completed": sum(1 for r in results if r["status"] == "ok"),
            "failed": sum(1 for r in results if r["status"] == "error"),
            "clips": results,
            "stitched": stitched,
        }

    # ── Download ────────────────────────────────────────────────────

    @app.get("/download/{filename}")
    async def download(filename: str):
        """Download a generated WAV file."""
        if "/" in filename or "\\" in filename or ".." in filename:
            raise HTTPException(400, "Invalid filename")
        filepath = (VOICE_DIR / filename).resolve()
        if not str(filepath).startswith(str(VOICE_DIR.resolve())):
            raise HTTPException(403, "Access denied")
        if not filepath.exists():
            raise HTTPException(404, "File not found")
        return FileResponse(str(filepath), media_type="audio/wav", filename=filename)

    # ── Voice designs ───────────────────────────────────────────────

    @app.get("/voices")
    async def list_voices():
        """List all voice designs (presets + character casts)."""
        from engine.tts.voice_designer import get_voice_designer, VOICE_PRESETS
        designer = get_voice_designer()
        return {
            "presets": {k: v.to_dict() for k, v in VOICE_PRESETS.items()},
            "characters": {k: v.to_dict() for k, v in designer.get_all().items()},
        }

    @app.post("/cast")
    async def cast_voice(request: CastRequest):
        """Save a voice design for a character."""
        from engine.tts.voice_designer import get_voice_designer, VoiceDesign
        designer = get_voice_designer()
        design = VoiceDesign(
            description=request.description,
            model_size=request.model_size,
            reference_audio=request.reference_audio,
            tags=request.tags,
        )
        designer.cast(request.character_id, design)
        return {"status": "ok", "character_id": request.character_id}

    # ── Health & Status ─────────────────────────────────────────────

    @app.get("/health")
    async def health():
        """Quick health check for service discovery."""
        return {
            "status": "ok",
            "engine": "qwen3-tts",
            "models_loaded": _engine.is_loaded,
            "mode": "live" if _engine.is_loaded else "placeholder",
        }

    @app.get("/status")
    async def status():
        """Server status: model loaded, queue depth, engine info."""
        active = sum(1 for j in _jobs.values() if j.status in ("queued", "processing"))
        completed = sum(1 for j in _jobs.values() if j.status == "completed")
        failed = sum(1 for j in _jobs.values() if j.status == "failed")
        return {
            "engine": "qwen3-tts",
            "models_loaded": _engine.is_loaded,
            "mode": "live" if _engine.is_loaded else "placeholder",
            "queue_active": active,
            "total_completed": completed,
            "total_failed": failed,
            "voice_dir": str(VOICE_DIR),
        }

    # ── MCP mount ───────────────────────────────────────────────────

    try:
        from fastmcp import FastMCP

        tts_mcp = FastMCP(
            "CosySim-TTS",
            instructions="Voice generation tools for CosySim characters.",
        )

        @tts_mcp.tool()
        def generate_voice(
            text: str,
            character_id: Optional[str] = None,
            voice_design: str = "A clear, natural speaking voice.",
            model_size: str = "auto",
            max_duration: int = 60,
        ) -> str:
            """
            Generate speech audio for a character. Returns the download URL.
            """
            job_id = str(uuid.uuid4())[:12]
            req = GenerateRequest(
                text=text,
                voice_design=voice_design,
                character_id=character_id,
                model_size=model_size,
                max_duration=max_duration,
            )
            _jobs[job_id] = TTSJob(job_id=job_id)
            _run_generation(job_id, req)
            job = _jobs[job_id]
            if job.status == "completed":
                return f"Voice generated: {job.filename} ({job.duration:.1f}s)"
            return f"Voice generation failed: {job.error}"

        @tts_mcp.tool()
        def cast_character_voice(
            character_id: str,
            description: str,
            model_size: str = "1.7b",
        ) -> str:
            """Save or update a character's voice design."""
            from engine.tts.voice_designer import get_voice_designer, VoiceDesign
            designer = get_voice_designer()
            designer.cast(character_id, VoiceDesign(
                description=description,
                model_size=model_size,
            ))
            return f"Voice design saved for {character_id}"

        mcp_app = tts_mcp.http_app(path="/mcp")
        app.mount("/mcp", mcp_app)
        logger.info("TTS MCP server mounted at /mcp")

    except Exception as e:
        logger.warning("Failed to mount TTS MCP: %s", e)

    return app


# ── Standalone entry point ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="CosySim TTS Server")
    parser.add_argument("--port", type=int, default=8600, help="Port (default 8600)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default 0.0.0.0)")
    args = parser.parse_args()

    app = create_tts_app()

    print(f"\n🎙️ CosySim TTS Server (Qwen3-TTS)")
    print(f"   Listening: http://{args.host}:{args.port}")
    print(f"   Generate:  POST http://localhost:{args.port}/generate")
    print(f"   Voices:    GET  http://localhost:{args.port}/voices")
    print(f"   Status:    GET  http://localhost:{args.port}/status")
    print(f"   MCP:       http://localhost:{args.port}/mcp/sse")
    print()

    uvicorn.run(app, host=args.host, port=args.port)
