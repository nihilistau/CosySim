"""Fine-tune Orchestrator — manages Unsloth QLoRA fine-tuning jobs for all micro-models.

Supports Qwen 270M, Qwen 1.7B, and Llama 3 3B. Handles job queue, progress tracking,
checkpoint management, and auto-merge of LoRA adapters on completion.

Usage::
    from training.finetune_orchestrator import get_finetune_orchestrator
    orch = get_finetune_orchestrator()
    job = orch.submit("qa_evaluator", base_model="Qwen/Qwen2.5-0.5B-Instruct")
    orch.run_next()
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JOBS_PATH = Path("training/jobs.jsonl")
_MODELS_DIR = Path("training/models")
_DATASETS_DIR = Path("training/datasets")

# Python executable used for training subprocesses.
# Set COSYSIM_TRAIN_PYTHON env var to override (e.g. conda base python with unsloth).
# Example: $env:COSYSIM_TRAIN_PYTHON = "C:\Users\Knack\anaconda3\python.exe"
_DEFAULT_TRAIN_PYTHON: str = os.environ.get("COSYSIM_TRAIN_PYTHON") or sys.executable


# ──── Enums / Models ──────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


BASE_MODEL_ALIASES: Dict[str, str] = {
    "qwen-270m": "Qwen/Qwen2.5-0.5B-Instruct",
    "qwen-1.7b": "Qwen/Qwen2.5-1.5B-Instruct",
    "llama-3b": "meta-llama/Llama-3.2-3B-Instruct",
    "qwen-7b": "Qwen/Qwen2.5-7B-Instruct",
}

RECOMMENDED_MODELS: Dict[str, str] = {
    "qa_evaluator": "qwen-270m",
    "conversation_analyzer": "qwen-270m",
    "syntax_fixer": "qwen-1.7b",
    "router_v2": "qwen-270m",
    "router_v3": "qwen-270m",
    "knowledge_synthesizer": "qwen-1.7b",
}


@dataclass
class FinetuneJob:
    """A single fine-tuning job."""
    job_id: str
    model_type: str
    base_model: str
    dataset_path: str
    output_dir: str
    status: str = JobStatus.PENDING
    progress: float = 0.0
    current_step: int = 0
    total_steps: int = 0
    loss: Optional[float] = None
    best_loss: Optional[float] = None
    checkpoint_path: Optional[str] = None
    merged_path: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    metrics: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FinetuneJob":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def is_terminal(self) -> bool:
        return self.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)


@dataclass
class FinetuneConfig:
    """Hyperparameter config for a fine-tuning run."""
    max_seq_length: int = 512
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    num_epochs: int = 3
    batch_size: int = 4
    gradient_accumulation: int = 4
    learning_rate: float = 2e-4
    warmup_steps: int = 5
    save_steps: int = 50
    eval_steps: int = 50
    max_steps: int = -1  # -1 = full epochs
    load_in_4bit: bool = True
    use_gradient_checkpointing: bool = True
    output_format: str = "alpaca"  # alpaca | sharegpt

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ──── Orchestrator ─────────────────────────────────────────────────────────────

class FinetuneOrchestrator:
    """Manages the full lifecycle of Unsloth QLoRA fine-tuning jobs."""

    def __init__(self) -> None:
        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        _DATASETS_DIR.mkdir(parents=True, exist_ok=True)
        _JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, FinetuneJob] = {}
        self._load_jobs()

    # ── Public API ────────────────────────────────────────────────────────────

    def submit(
        self,
        model_type: str,
        base_model: Optional[str] = None,
        config: Optional[FinetuneConfig] = None,
        dataset_path: Optional[str] = None,
    ) -> FinetuneJob:
        """Submit a new fine-tuning job.

        Args:
            model_type: One of the 5 micro-model types.
            base_model: HuggingFace model ID or alias. Defaults to recommended.
            config: Hyperparameter config. Defaults to recommended for model size.
            dataset_path: Path to JSONL training file. Defaults to auto-detect.

        Returns:
            FinetuneJob with status=PENDING.
        """
        # Resolve base model
        if base_model is None:
            alias = RECOMMENDED_MODELS.get(model_type, "qwen-270m")
            base_model = BASE_MODEL_ALIASES.get(alias, alias)
        elif base_model in BASE_MODEL_ALIASES:
            base_model = BASE_MODEL_ALIASES[base_model]

        # Resolve dataset
        if dataset_path is None:
            dataset_path = str(_DATASETS_DIR / f"{model_type}_train.jsonl")
        if not Path(dataset_path).exists():
            raise FileNotFoundError(f"Training dataset not found: {dataset_path}")

        # Resolve config
        if config is None:
            config = self._default_config(base_model)

        job_id = str(uuid.uuid4())[:8]
        output_dir = str(_MODELS_DIR / f"{model_type}_{job_id}")
        job = FinetuneJob(
            job_id=job_id,
            model_type=model_type,
            base_model=base_model,
            dataset_path=dataset_path,
            output_dir=output_dir,
            config=config.to_dict(),
        )
        self._jobs[job_id] = job
        self._persist_job(job)
        logger.info("Submitted finetune job %s: %s → %s", job_id, model_type, base_model)
        return job

    def run_next(self) -> Optional[FinetuneJob]:
        """Run the next pending job synchronously.

        Returns:
            Completed FinetuneJob, or None if queue is empty.
        """
        pending = [j for j in self._jobs.values() if j.status == JobStatus.PENDING]
        if not pending:
            logger.info("No pending finetune jobs.")
            return None
        job = sorted(pending, key=lambda j: j.created_at)[0]
        return self._run_job(job)

    def run_job(self, job_id: str) -> FinetuneJob:
        """Run a specific job by ID.

        Args:
            job_id: Job ID to run.

        Returns:
            Completed FinetuneJob.
        """
        if job_id not in self._jobs:
            raise KeyError(f"Job {job_id} not found")
        return self._run_job(self._jobs[job_id])

    def cancel_job(self, job_id: str) -> None:
        """Cancel a pending or running job."""
        if job_id not in self._jobs:
            raise KeyError(f"Job {job_id} not found")
        job = self._jobs[job_id]
        if not job.is_terminal():
            job.status = JobStatus.CANCELLED
            self._persist_job(job)
            logger.info("Cancelled job %s", job_id)

    def list_jobs(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all jobs, optionally filtered by status."""
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return [j.to_dict() for j in sorted(jobs, key=lambda j: j.created_at, reverse=True)]

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job details by ID."""
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def queue_status(self) -> Dict[str, Any]:
        """Return counts by status."""
        counts: Dict[str, int] = {s.value: 0 for s in JobStatus}
        for j in self._jobs.values():
            counts[j.status] = counts.get(j.status, 0) + 1
        return {"jobs": counts, "total": len(self._jobs)}

    # ── Training Script Generation ────────────────────────────────────────────

    def generate_training_script(self, job: FinetuneJob) -> str:
        """Generate a standalone Python training script for the job.

        Args:
            job: The job to generate a script for.

        Returns:
            Python script as a string.
        """
        cfg = FinetuneConfig(**job.config) if job.config else FinetuneConfig()
        # Normalise paths to forward slashes so the generated script is cross-platform
        dataset_path = str(Path(job.dataset_path).resolve()).replace("\\", "/")
        output_dir   = str(Path(job.output_dir).resolve()).replace("\\", "/")
        return f'''"""Auto-generated fine-tuning script for job {job.job_id}: {job.model_type}."""
import json
from pathlib import Path
from datasets import Dataset

# ── Unsloth fast model loading ────────────────────────────────────────────────
from unsloth import FastLanguageModel
import torch

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="{job.base_model}",
    max_seq_length={cfg.max_seq_length},
    load_in_4bit={cfg.load_in_4bit},
    dtype=None,
)

model = FastLanguageModel.get_peft_model(
    model,
    r={cfg.lora_r},
    lora_alpha={cfg.lora_alpha},
    lora_dropout={cfg.lora_dropout},
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing={cfg.use_gradient_checkpointing},
)

# ── Dataset loading ───────────────────────────────────────────────────────────
def load_dataset_from_jsonl(path: str) -> Dataset:
    examples = []
    with open(path) as f:
        for line in f:
            if line.strip():
                examples.append(json.loads(line))
    return Dataset.from_list(examples)

def format_alpaca(example):
    text = f"### Instruction:\\n{{example.get(\'instruction\', \'\')}}\\n\\n### Input:\\n{{example.get(\'input\', \'\')}}\\n\\n### Response:\\n{{example.get(\'output\', '')}}"
    return {{"text": text}}

raw_dataset = load_dataset_from_jsonl("{dataset_path}")
dataset = raw_dataset.map(format_alpaca)

# ── Training ──────────────────────────────────────────────────────────────────
from trl import SFTTrainer
from transformers import TrainingArguments

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length={cfg.max_seq_length},
    args=TrainingArguments(
        output_dir="{output_dir}",
        num_train_epochs={cfg.num_epochs},
        per_device_train_batch_size={cfg.batch_size},
        gradient_accumulation_steps={cfg.gradient_accumulation},
        learning_rate={cfg.learning_rate},
        warmup_steps={cfg.warmup_steps},
        save_steps={cfg.save_steps},
        eval_strategy="no",
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=1,
        report_to="none",
    ),
)
trainer.train()

# ── Save adapter ──────────────────────────────────────────────────────────────
adapter_path = "{output_dir}/adapter"
model.save_pretrained(adapter_path)
tokenizer.save_pretrained(adapter_path)
print(f"Adapter saved to: {{adapter_path}}")

# ── Merge ──────────────────────────────────────────────────────────────────────
merged_path = "{output_dir}/merged"
model.save_pretrained_merged(merged_path, tokenizer, save_method="merged_16bit")
print(f"Merged model saved to: {{merged_path}}")
'''

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _run_job(self, job: FinetuneJob) -> FinetuneJob:
        """Execute a fine-tuning job."""
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        logger.info("Starting finetune job %s (%s)", job.job_id, job.model_type)

        script_path = Path(job.output_dir)
        script_path.mkdir(parents=True, exist_ok=True)
        script_file = script_path / "train.py"
        script = self.generate_training_script(job)
        script_file.write_text(script, encoding="utf-8")

        try:
            train_python = _DEFAULT_TRAIN_PYTHON
            try:
                from engine.config import get_config
                cfg_py = get_config().get("training.python_executable", "")
                if cfg_py:
                    train_python = cfg_py
            except Exception:
                pass

            process = subprocess.Popen(
                [train_python, str(script_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(Path(".").resolve()),
            )

            log_path = script_path / "train.log"
            step_pattern = import_re_for_step()

            with open(log_path, "w", encoding="utf-8") as log_f:
                for line in process.stdout:
                    log_f.write(line)
                    log_f.flush()
                    # Parse step progress
                    m = step_pattern.search(line)
                    if m:
                        try:
                            job.current_step = int(m.group(1))
                            total = int(m.group(2))
                            job.total_steps = total
                            job.progress = job.current_step / max(total, 1)
                        except (ValueError, IndexError):
                            pass
                    # Parse loss
                    if "'loss'" in line or '"loss"' in line:
                        try:
                            import re
                            lm = re.search(r"['\"]loss['\"]:\s*([\d.]+)", line)
                            if lm:
                                loss = float(lm.group(1))
                                job.loss = loss
                                if job.best_loss is None or loss < job.best_loss:
                                    job.best_loss = loss
                        except (ValueError, AttributeError):
                            pass
                    self._persist_job(job)

            process.wait()
            if process.returncode == 0:
                merged_path = Path(job.output_dir) / "merged"
                job.merged_path = str(merged_path) if merged_path.exists() else None
                job.checkpoint_path = str(Path(job.output_dir) / "adapter")
                job.status = JobStatus.DONE
                job.progress = 1.0
                logger.info("Job %s completed. Merged: %s", job.job_id, job.merged_path)
                self._notify_registry(job)
            else:
                job.status = JobStatus.FAILED
                job.error = f"Training process exited with code {process.returncode}"
                logger.error("Job %s failed: %s", job.job_id, job.error)

        except FileNotFoundError:
            # unsloth not installed — mark as needing unsloth
            job.status = JobStatus.FAILED
            job.error = "unsloth not installed. Run: pip install unsloth"
            logger.warning("Job %s: unsloth not available", job.job_id)
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            logger.error("Job %s error: %s", job.job_id, exc)

        job.completed_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        return job

    def _default_config(self, base_model: str) -> FinetuneConfig:
        """Return sensible defaults based on model size."""
        if "0.5B" in base_model or "270M" in base_model or "0.6B" in base_model:
            return FinetuneConfig(lora_r=8, batch_size=8, num_epochs=3, max_seq_length=512)
        elif "1.5B" in base_model or "1.7B" in base_model:
            return FinetuneConfig(lora_r=16, batch_size=4, num_epochs=3, max_seq_length=1024)
        else:
            return FinetuneConfig(lora_r=32, batch_size=2, num_epochs=2, max_seq_length=2048)

    def _notify_registry(self, job: FinetuneJob) -> None:
        """Notify ModelRegistry of a completed job."""
        try:
            from training.model_registry import get_model_registry
            registry = get_model_registry()
            registry.register_from_job(job)
        except Exception as exc:
            logger.debug("Registry notification skipped: %s", exc)

    def _load_jobs(self) -> None:
        """Load job history from disk."""
        if not _JOBS_PATH.exists():
            return
        for line in _JOBS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    d = json.loads(line)
                    job = FinetuneJob.from_dict(d)
                    self._jobs[job.job_id] = job
                except Exception as exc:
                    logger.debug("Job load error: %s", exc)

    def _persist_job(self, job: FinetuneJob) -> None:
        """Persist all jobs to disk (full rewrite — jobs file stays manageable)."""
        try:
            with open(_JOBS_PATH, "w", encoding="utf-8") as f:
                for j in self._jobs.values():
                    f.write(json.dumps(j.to_dict()) + "\n")
        except Exception as exc:
            logger.debug("Job persist error: %s", exc)


def import_re_for_step():
    """Import re and return step pattern."""
    import re
    return re.compile(r"(\d+)/(\d+)")


# ──── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[FinetuneOrchestrator] = None


def get_finetune_orchestrator() -> FinetuneOrchestrator:
    """Return the shared FinetuneOrchestrator singleton."""
    global _instance
    if _instance is None:
        _instance = FinetuneOrchestrator()
    return _instance
