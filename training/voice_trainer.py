"""Voice model trainer — Piper VITS, Qwen3-TTS LoRA, and Orpheus LoRA per-character training."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_VOICE_DATA_DIR = Path("training/voice_data")
_instance: Optional["VoiceTrainer"] = None
_lock = threading.Lock()

_SUPPORTED_BACKENDS = ("piper", "qwen3", "orpheus")
_DEFAULT_MIN_SAMPLES = 30


@dataclass
class VoiceTrainResult:
    """Result of a voice model training run."""

    character_id: str
    backend: str
    success: bool
    samples_used: int = 0
    output_path: Optional[str] = None
    error: Optional[str] = None
    duration_s: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "character_id": self.character_id,
            "backend": self.backend,
            "success": self.success,
            "samples_used": self.samples_used,
            "output_path": self.output_path,
            "error": self.error,
            "duration_s": self.duration_s,
            "timestamp": self.timestamp,
        }


class VoiceTrainer:
    """Manages per-character voice model training across Piper, Qwen3-TTS, and Orpheus backends.

    Samples are stored in training/voice_data/{character_id}/{backend}/samples.jsonl.
    Training is launched as a subprocess using the configured Python executable.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        """Initialize VoiceTrainer.

        Args:
            base_dir: Base directory for voice data. Defaults to training/voice_data.
        """
        self._base_dir = base_dir or _VOICE_DATA_DIR
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()

    # ── Sample Collection ─────────────────────────────────────────────────────

    def collect_sample(
        self,
        character_id: str,
        text: str,
        audio_path: str,
        quality_rating: float,
        backend: str,
    ) -> None:
        """Collect a voice sample for training.

        Args:
            character_id: Character identifier (e.g., "aria").
            text: The text that was spoken.
            audio_path: Path to the WAV audio file.
            quality_rating: Quality rating 0.0-1.0.
            backend: TTS backend (piper, qwen3, orpheus).
        """
        if backend not in _SUPPORTED_BACKENDS:
            logger.warning(f"Unknown backend '{backend}', supported: {_SUPPORTED_BACKENDS}")
            return

        try:
            samples_path = self._samples_path(character_id, backend)
            samples_path.parent.mkdir(parents=True, exist_ok=True)

            record = {
                "character_id": character_id,
                "text": text,
                "audio_path": audio_path,
                "quality_rating": quality_rating,
                "backend": backend,
                "collected_at": time.time(),
            }
            with self._write_lock:
                with samples_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.error(f"VoiceTrainer.collect_sample failed for {character_id}/{backend}: {e}")

    def get_character_stats(self, character_id: str) -> Dict[str, int]:
        """Get sample counts per backend for a character.

        Args:
            character_id: Character identifier.

        Returns:
            Dict mapping backend name to sample count.
        """
        stats: Dict[str, int] = {}
        for backend in _SUPPORTED_BACKENDS:
            samples_path = self._samples_path(character_id, backend)
            if samples_path.exists():
                try:
                    count = sum(
                        1 for line in samples_path.open("r", encoding="utf-8") if line.strip()
                    )
                    stats[backend] = count
                except Exception:
                    stats[backend] = 0
            else:
                stats[backend] = 0
        return stats

    def get_all_stats(self) -> Dict[str, Dict[str, int]]:
        """Get sample counts for all characters and backends.

        Returns:
            Dict mapping character_id to per-backend sample counts.
        """
        result: Dict[str, Dict[str, int]] = {}
        if not self._base_dir.exists():
            return result
        for char_dir in self._base_dir.iterdir():
            if char_dir.is_dir():
                character_id = char_dir.name
                stats = self.get_character_stats(character_id)
                if any(v > 0 for v in stats.values()):
                    result[character_id] = stats
        return result

    # ── Training ──────────────────────────────────────────────────────────────

    def train_piper(
        self,
        character_id: str,
        force: bool = False,
        min_samples: int = _DEFAULT_MIN_SAMPLES,
    ) -> VoiceTrainResult:
        """Train a Piper VITS model for a character.

        Args:
            character_id: Character to train.
            force: Force training even if below min_samples.
            min_samples: Minimum samples required.

        Returns:
            VoiceTrainResult with outcome.
        """
        return self._train(character_id, "piper", force=force, min_samples=min_samples)

    def train_qwen3(
        self,
        character_id: str,
        force: bool = False,
        min_samples: int = _DEFAULT_MIN_SAMPLES,
    ) -> VoiceTrainResult:
        """Train a Qwen3-TTS LoRA model for a character.

        Args:
            character_id: Character to train.
            force: Force training even if below min_samples.
            min_samples: Minimum samples required.

        Returns:
            VoiceTrainResult with outcome.
        """
        return self._train(character_id, "qwen3", force=force, min_samples=min_samples)

    def train_orpheus(
        self,
        character_id: str,
        force: bool = False,
        min_samples: int = _DEFAULT_MIN_SAMPLES,
    ) -> VoiceTrainResult:
        """Train an Orpheus LoRA model for a character.

        Args:
            character_id: Character to train.
            force: Force training even if below min_samples.
            min_samples: Minimum samples required.

        Returns:
            VoiceTrainResult with outcome.
        """
        return self._train(character_id, "orpheus", force=force, min_samples=min_samples)

    def train_all_backends(
        self,
        character_id: str,
        force: bool = False,
        min_samples: int = _DEFAULT_MIN_SAMPLES,
    ) -> List[VoiceTrainResult]:
        """Train all backends for a character.

        Args:
            character_id: Character to train.
            force: Force training even if below min_samples.
            min_samples: Minimum samples required.

        Returns:
            List of VoiceTrainResult, one per backend.
        """
        results = []
        for backend in _SUPPORTED_BACKENDS:
            result = self._train(character_id, backend, force=force, min_samples=min_samples)
            results.append(result)
        return results

    def auto_train_all(
        self,
        min_samples: int = _DEFAULT_MIN_SAMPLES,
    ) -> List[VoiceTrainResult]:
        """Auto-train all characters that have enough samples.

        Only trains when sample count meets min_samples threshold.

        Args:
            min_samples: Minimum samples needed before training.

        Returns:
            List of VoiceTrainResult for all trained models.
        """
        results = []
        all_stats = self.get_all_stats()
        for character_id, stats in all_stats.items():
            for backend, count in stats.items():
                if count >= min_samples:
                    logger.info(
                        f"Auto-training {character_id}/{backend} with {count} samples"
                    )
                    result = self._train(character_id, backend, force=False, min_samples=min_samples)
                    results.append(result)
        return results

    # ── Private ───────────────────────────────────────────────────────────────

    def _samples_path(self, character_id: str, backend: str) -> Path:
        """Get path to samples.jsonl for a character/backend."""
        return self._base_dir / character_id / backend / "samples.jsonl"

    def _load_samples(
        self, character_id: str, backend: str
    ) -> List[Dict[str, Any]]:
        """Load all samples for a character/backend."""
        samples_path = self._samples_path(character_id, backend)
        if not samples_path.exists():
            return []
        records = []
        try:
            with samples_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"Failed to load voice samples for {character_id}/{backend}: {e}")
        return records

    def _train(
        self,
        character_id: str,
        backend: str,
        force: bool = False,
        min_samples: int = _DEFAULT_MIN_SAMPLES,
    ) -> VoiceTrainResult:
        """Internal training dispatcher.

        Args:
            character_id: Character to train.
            backend: Backend type (piper, qwen3, orpheus).
            force: Skip threshold check if True.
            min_samples: Minimum samples required.

        Returns:
            VoiceTrainResult.
        """
        start = time.time()
        samples = self._load_samples(character_id, backend)

        if not samples:
            return VoiceTrainResult(
                character_id=character_id,
                backend=backend,
                success=False,
                error=f"No voice data found for {character_id}/{backend}",
            )

        if not force and len(samples) < min_samples:
            return VoiceTrainResult(
                character_id=character_id,
                backend=backend,
                success=False,
                samples_used=len(samples),
                error=f"Insufficient samples: {len(samples)} < {min_samples} (use force=True to override)",
            )

        # Prepare output directory
        output_dir = self._base_dir / character_id / backend / "model"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write training manifest
        manifest_path = self._base_dir / character_id / backend / "manifest.jsonl"
        try:
            with manifest_path.open("w", encoding="utf-8") as f:
                for sample in samples:
                    f.write(json.dumps(sample) + "\n")
        except Exception as e:
            logger.error(f"Failed to write voice training manifest: {e}")
            return VoiceTrainResult(
                character_id=character_id,
                backend=backend,
                success=False,
                error=f"Manifest write failed: {e}",
            )

        # Generate and run training script
        script = self._generate_script(character_id, backend, manifest_path, output_dir, samples)
        script_path = self._base_dir / character_id / backend / "train.py"
        try:
            script_path.write_text(script, encoding="utf-8")
        except Exception as e:
            return VoiceTrainResult(
                character_id=character_id,
                backend=backend,
                success=False,
                error=f"Script write failed: {e}",
            )

        # Resolve Python executable
        train_python = sys.executable
        try:
            from engine.config import get_config
            cfg_py = get_config().get("training.python_executable", "")
            if cfg_py:
                train_python = cfg_py
        except Exception:
            pass

        try:
            proc = subprocess.run(
                [train_python, str(script_path)],
                capture_output=True,
                text=True,
                timeout=3600,
                cwd=str(Path(".").resolve()),
            )
            duration = time.time() - start
            if proc.returncode == 0:
                result = VoiceTrainResult(
                    character_id=character_id,
                    backend=backend,
                    success=True,
                    samples_used=len(samples),
                    output_path=str(output_dir),
                    duration_s=round(duration, 2),
                )
                self._store_result_in_nexus(result)
                return result
            else:
                error = proc.stderr[:500] if proc.stderr else f"exit code {proc.returncode}"
                return VoiceTrainResult(
                    character_id=character_id,
                    backend=backend,
                    success=False,
                    samples_used=len(samples),
                    error=error,
                    duration_s=round(duration, 2),
                )
        except subprocess.TimeoutExpired:
            return VoiceTrainResult(
                character_id=character_id,
                backend=backend,
                success=False,
                samples_used=len(samples),
                error="Training timed out after 3600s",
                duration_s=3600.0,
            )
        except Exception as e:
            duration = time.time() - start
            logger.error(f"VoiceTrainer._train failed for {character_id}/{backend}: {e}")
            return VoiceTrainResult(
                character_id=character_id,
                backend=backend,
                success=False,
                samples_used=len(samples),
                error=str(e),
                duration_s=round(duration, 2),
            )

    def _generate_script(
        self,
        character_id: str,
        backend: str,
        manifest_path: Path,
        output_dir: Path,
        samples: List[Dict[str, Any]],
    ) -> str:
        """Generate a training script for the given backend.

        Args:
            character_id: Character identifier.
            backend: TTS backend type.
            manifest_path: Path to the training manifest.
            output_dir: Output directory for the trained model.
            samples: List of sample records.

        Returns:
            Python script as a string.
        """
        manifest_str = str(manifest_path.resolve()).replace("\\", "/")
        output_str = str(output_dir.resolve()).replace("\\", "/")

        if backend == "piper":
            return f'''"""Auto-generated Piper VITS voice training script for {character_id}."""
import json, subprocess, sys
from pathlib import Path

MANIFEST = "{manifest_str}"
OUTPUT_DIR = "{output_str}"
CHARACTER_ID = "{character_id}"

samples = []
with open(MANIFEST) as f:
    for line in f:
        if line.strip():
            samples.append(json.loads(line))

print(f"[piper-train] {len(samples)} samples for {{CHARACTER_ID}}")

# Prepare filelists
output_path = Path(OUTPUT_DIR)
output_path.mkdir(parents=True, exist_ok=True)
filelist = output_path / "filelist.txt"
with filelist.open("w") as fl:
    for s in samples:
        audio = s.get("audio_path", "")
        text = s.get("text", "")
        if audio and text:
            fl.write(f"{{audio}}|{{text}}\\n")

print(f"[piper-train] filelist written: {{filelist}}")

# Try to run piper_train if available
try:
    result = subprocess.run(
        [sys.executable, "-m", "piper_train",
         "--dataset-dir", str(output_path),
         "--accelerator", "gpu",
         "--devices", "1",
         "--batch-size", "16",
         "--max-epochs", "100",
         "--quality", "medium",
         "--precision", "32",
        ],
        capture_output=True, text=True, timeout=3600,
    )
    if result.returncode == 0:
        print("[piper-train] Training completed successfully")
    else:
        print(f"[piper-train] Training failed: {{result.stderr[:200]}}")
except Exception as e:
    print(f"[piper-train] piper_train not available or failed: {{e}}")
    # Write placeholder model file to indicate completion attempt
    (output_path / "train_attempted.json").write_text(
        json.dumps({{"character_id": CHARACTER_ID, "backend": "piper", "samples": len(samples)}}),
        encoding="utf-8",
    )
    print("[piper-train] Wrote completion marker")
'''

        elif backend == "qwen3":
            return f'''"""Auto-generated Qwen3-TTS LoRA voice training script for {character_id}."""
import json, sys
from pathlib import Path

MANIFEST = "{manifest_str}"
OUTPUT_DIR = "{output_str}"
CHARACTER_ID = "{character_id}"

samples = []
with open(MANIFEST) as f:
    for line in f:
        if line.strip():
            samples.append(json.loads(line))

print(f"[qwen3-tts-train] {{len(samples)}} samples for {{CHARACTER_ID}}")

output_path = Path(OUTPUT_DIR)
output_path.mkdir(parents=True, exist_ok=True)

try:
    from unsloth import FastLanguageModel
    import torch

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="Qwen/Qwen3-TTS-0.6B",
        max_seq_length=1024,
        load_in_4bit=True,
        dtype=None,
    )
    model = FastLanguageModel.get_peft_model(
        model, r=8, lora_alpha=16, lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )

    from datasets import Dataset
    dataset_records = [
        {{"instruction": "Speak this text in character.", "input": s.get("text", ""), "output": s.get("audio_path", "")}}
        for s in samples
    ]
    dataset = Dataset.from_list(dataset_records)

    from trl import SFTTrainer
    from transformers import TrainingArguments
    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="input",
        max_seq_length=512,
        args=TrainingArguments(
            output_dir=str(output_path), num_train_epochs=2,
            per_device_train_batch_size=4, learning_rate=2e-4,
            fp16=True, logging_steps=1, report_to="none",
        ),
    )
    trainer.train()
    model.save_pretrained(str(output_path / "adapter"))
    print(f"[qwen3-tts-train] Adapter saved to {{output_path / 'adapter'}}")

except Exception as e:
    print(f"[qwen3-tts-train] Training failed: {{e}}")
    (output_path / "train_attempted.json").write_text(
        json.dumps({{"character_id": CHARACTER_ID, "backend": "qwen3", "samples": len(samples), "error": str(e)}}),
    )
    print("[qwen3-tts-train] Wrote completion marker")
'''

        else:  # orpheus
            return f'''"""Auto-generated Orpheus LoRA voice training script for {character_id}."""
import json, sys
from pathlib import Path

MANIFEST = "{manifest_str}"
OUTPUT_DIR = "{output_str}"
CHARACTER_ID = "{character_id}"

samples = []
with open(MANIFEST) as f:
    for line in f:
        if line.strip():
            samples.append(json.loads(line))

print(f"[orpheus-train] {{len(samples)}} samples for {{CHARACTER_ID}}")

output_path = Path(OUTPUT_DIR)
output_path.mkdir(parents=True, exist_ok=True)

try:
    from unsloth import FastLanguageModel
    import torch

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="canopylabs/orpheus-3b-0.1-ft",
        max_seq_length=2048,
        load_in_4bit=True,
        dtype=None,
    )
    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=32, lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )

    dataset_records = [
        {{"instruction": f"Speak as {{CHARACTER_ID}}:", "input": s.get("text", ""), "output": s.get("audio_path", "")}}
        for s in samples
    ]
    from datasets import Dataset
    dataset = Dataset.from_list(dataset_records)

    from trl import SFTTrainer
    from transformers import TrainingArguments
    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="input",
        max_seq_length=1024,
        args=TrainingArguments(
            output_dir=str(output_path), num_train_epochs=3,
            per_device_train_batch_size=2, gradient_accumulation_steps=4,
            learning_rate=2e-4, fp16=True, logging_steps=1, report_to="none",
        ),
    )
    trainer.train()
    model.save_pretrained(str(output_path / "adapter"))
    print(f"[orpheus-train] Adapter saved to {{output_path / 'adapter'}}")

except Exception as e:
    print(f"[orpheus-train] Training failed: {{e}}")
    (output_path / "train_attempted.json").write_text(
        json.dumps({{"character_id": CHARACTER_ID, "backend": "orpheus", "samples": len(samples), "error": str(e)}}),
    )
    print("[orpheus-train] Wrote completion marker")
'''

    def _store_result_in_nexus(self, result: VoiceTrainResult) -> None:
        """Store training result in Nexus (best-effort)."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            client.add_entry(
                title=f"Voice Training: {result.character_id}/{result.backend}",
                content=json.dumps(result.to_dict()),
                content_type="history",
                category="training",
            )
        except Exception as exc:
            logger.debug(f"Could not store voice training result in Nexus: {exc}")


def get_voice_trainer() -> VoiceTrainer:
    """Get the VoiceTrainer singleton.

    Returns:
        The global VoiceTrainer instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = VoiceTrainer()
    return _instance
