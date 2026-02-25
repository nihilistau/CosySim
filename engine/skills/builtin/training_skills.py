"""
training_skills.py — MCP skill wrappers for the training pipeline

These skills expose the CosySim training subsystem to the LLM so it can:
- Trigger local fine-tuning runs in the background
- Poll training job status and retrieve results
- Export live interaction data into training-ready datasets
- List trained model artifacts (LoRA adapters, GGUF exports)
"""
from __future__ import annotations

import json
import uuid
from typing import Dict

from engine.skills.skill import skill

# Module-level store for background training jobs.
# Keys are job-id strings; values are dicts with keys:
#   status  – "started" | "running" | "completed" | "failed"
#   result  – return value from finetune() on success
#   error   – exception string on failure
_training_jobs: Dict[str, dict] = {}


# ── trigger_finetune ────────────────────────────────────────────────────

@skill(
    pack="training",
    description=(
        "Launch a local fine-tuning run in the background. "
        "Returns a job ID that can be polled with get_training_status."
    ),
    tags=["training", "finetune", "background"],
)
def trigger_finetune(
    dataset: str = "tag_extraction",
    epochs: int = 3,
) -> str:
    """
    Start a fine-tuning job as a daemon thread.

    Args:
        dataset: Name of the dataset under training/datasets/.
        epochs:  Number of training epochs (1–50).

    Returns:
        JSON string with job_id, status, dataset, and epochs.
    """
    import threading

    job_id = uuid.uuid4().hex[:12]
    _training_jobs[job_id] = {"status": "started", "result": None, "error": None}

    def _run() -> None:
        from training.finetune_local import finetune

        _training_jobs[job_id]["status"] = "running"
        try:
            result = finetune(dataset_name=dataset, epochs=epochs)
            _training_jobs[job_id].update(status="completed", result=result)
        except Exception as exc:
            _training_jobs[job_id].update(status="failed", error=str(exc))

    thread = threading.Thread(target=_run, daemon=True, name=f"finetune-{job_id}")
    thread.start()

    return json.dumps({
        "job_id": job_id,
        "status": "started",
        "dataset": dataset,
        "epochs": epochs,
    })


# ── get_training_status ─────────────────────────────────────────────────

@skill(
    pack="training",
    description=(
        "Check the status of a background training job. "
        "Pass an empty job_id to list every tracked job."
    ),
    tags=["training", "status"],
)
def get_training_status(job_id: str = "") -> str:
    """
    Return the current status of one or all training jobs.

    Args:
        job_id: The job identifier returned by trigger_finetune.
                If empty, returns a summary of all known jobs.

    Returns:
        JSON string with status, result (if completed), or error (if failed).
    """
    if not job_id:
        summary = {jid: {"status": info["status"]} for jid, info in _training_jobs.items()}
        return json.dumps(summary) if summary else json.dumps({"message": "No training jobs recorded."})

    info = _training_jobs.get(job_id)
    if info is None:
        return json.dumps({"error": f"Unknown job_id: {job_id}"})

    out: dict = {"job_id": job_id, "status": info["status"]}
    if info["status"] == "completed" and info["result"] is not None:
        out["result"] = info["result"]
    if info["status"] == "failed" and info["error"]:
        out["error"] = info["error"]
    return json.dumps(out)


# ── export_training_data ────────────────────────────────────────────────

@skill(
    pack="training",
    description=(
        "Export live interaction data into a training-ready dataset. "
        "Filters by a minimum quality score."
    ),
    tags=["training", "data", "export"],
)
def export_training_data(
    dataset: str = "tag_extraction",
    min_quality: float = 0.7,
) -> str:
    """
    Prepare a dataset from recorded live interactions.

    Args:
        dataset:     Target dataset name written to training/datasets/.
        min_quality: Minimum quality threshold (0.0–1.0) for including examples.

    Returns:
        JSON string with the count of exported examples.
    """
    try:
        from training.prepare_from_live import prepare_dataset

        count = prepare_dataset(dataset_name=dataset, min_quality=float(min_quality))
        return json.dumps({"dataset": dataset, "min_quality": min_quality, "exported_examples": count})
    except Exception as exc:
        return json.dumps({"error": f"Export failed: {exc}"})


# ── list_trained_models ─────────────────────────────────────────────────

@skill(
    pack="training",
    description=(
        "List trained model artifacts found in training/output/. "
        "Reports LoRA adapters and GGUF exports with sizes."
    ),
    tags=["training", "models", "listing"],
)
def list_trained_models() -> str:
    """
    Scan training/output/ for directories that contain model artifacts.

    Returns:
        JSON list of objects with name, path, has_adapter, has_gguf, and size_mb.
    """
    import os
    from pathlib import Path

    output_dir = Path("training/output")
    if not output_dir.is_dir():
        return json.dumps({"error": "training/output/ directory not found."})

    models = []
    for entry in sorted(output_dir.iterdir()):
        if not entry.is_dir():
            continue

        files = [f.name for f in entry.rglob("*") if f.is_file()]
        has_adapter = any(f.startswith("adapter") for f in files)
        has_gguf = any(f.endswith(".gguf") for f in files)

        total_bytes = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
        size_mb = round(total_bytes / (1024 * 1024), 2)

        models.append({
            "name": entry.name,
            "path": str(entry),
            "has_adapter": has_adapter,
            "has_gguf": has_gguf,
            "size_mb": size_mb,
        })

    return json.dumps(models)


# ── auto_train_check ────────────────────────────────────────────────────

@skill(
    pack="training",
    description=(
        "Check auto-training pipeline status: candidate counts, "
        "thresholds, and recent training history."
    ),
    tags=["training", "auto", "status"],
)
def training_auto_check() -> str:
    """
    Check the auto-training pipeline status including candidate
    counts per dataset and recent training history.

    Returns:
        JSON with candidate_counts, thresholds, and recent_history.
    """
    try:
        from training.auto_train import get_status
        status = get_status()
        return json.dumps(status, default=str, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"Auto-train check failed: {exc}"})
