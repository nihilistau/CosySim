"""
Assistant Platform — Training Dashboard API
=============================================

Wraps the existing training pipeline (auto_train, finetune_orchestrator,
model_registry) into REST endpoints for the dashboard UI.

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Initial training dashboard routes
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

training_bp = Blueprint("training", __name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


# ──── Training Status ────────────────────────────────────────────────

@training_bp.route("/status", methods=["GET"])
def training_status():
    """Get auto-train daemon status and dataset counts."""
    result = {"daemon": "unknown", "datasets": {}, "last_run": None}

    # Check auto-train state file
    state_file = PROJECT_ROOT / ".auto_train_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            result["daemon"] = "active"
            result["last_run"] = state.get("last_run")
            result["check_interval_hours"] = state.get("check_interval_hours", 1)
        except Exception:
            result["daemon"] = "error"
    else:
        result["daemon"] = "not_started"

    # Count dataset files
    datasets_dir = PROJECT_ROOT / "training" / "datasets"
    if datasets_dir.exists():
        for f in datasets_dir.glob("*.jsonl"):
            try:
                lines = sum(1 for _ in open(f, encoding="utf-8", errors="replace"))
                result["datasets"][f.stem] = {"file": f.name, "examples": lines}
            except Exception:
                result["datasets"][f.stem] = {"file": f.name, "examples": 0}

    # Collected datasets
    collected_dir = datasets_dir / "collected"
    if collected_dir.exists():
        for f in collected_dir.glob("*_live.jsonl"):
            try:
                lines = sum(1 for _ in open(f, encoding="utf-8", errors="replace"))
                result["datasets"][f.stem] = {"file": f.name, "examples": lines, "type": "live"}
            except Exception:
                pass

    return jsonify(result)


# ──── Model Registry ─────────────────────────────────────────────────

@training_bp.route("/models", methods=["GET"])
def training_models():
    """Get the model registry — all trained/registered model versions."""
    registry_path = PROJECT_ROOT / "training" / "model_registry.json"
    if not registry_path.exists():
        return jsonify({"models": [], "error": "registry not found"})

    try:
        registry = json.loads(registry_path.read_text())
        return jsonify(registry)
    except Exception as e:
        return jsonify({"models": [], "error": str(e)})


# ──── Benchmarks ─────────────────────────────────────────────────────

@training_bp.route("/benchmarks", methods=["GET"])
def training_benchmarks():
    """Get latest benchmark results."""
    benchmarks_path = PROJECT_ROOT / "training" / "benchmarks.jsonl"
    if not benchmarks_path.exists():
        return jsonify({"benchmarks": []})

    results = []
    try:
        for line in open(benchmarks_path, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass

    # Return last 20 results
    return jsonify({"benchmarks": results[-20:]})


# ──── Training Jobs ──────────────────────────────────────────────────

@training_bp.route("/jobs", methods=["GET"])
def training_jobs():
    """List recent training jobs from auto_train state."""
    state_file = PROJECT_ROOT / ".auto_train_state.json"
    if not state_file.exists():
        return jsonify({"jobs": []})

    try:
        state = json.loads(state_file.read_text())
        jobs = state.get("job_history", [])
        return jsonify({"jobs": jobs[-20:]})
    except Exception as e:
        return jsonify({"jobs": [], "error": str(e)})


# ──── Dataset Details ────────────────────────────────────────────────

@training_bp.route("/datasets", methods=["GET"])
def training_datasets():
    """Get detailed dataset info with quality metrics."""
    datasets_dir = PROJECT_ROOT / "training" / "datasets"
    result = {"datasets": []}

    if not datasets_dir.exists():
        return jsonify(result)

    for f in sorted(datasets_dir.glob("*.jsonl")):
        try:
            lines = sum(1 for _ in open(f, encoding="utf-8", errors="replace"))
            size_kb = f.stat().st_size / 1024
            result["datasets"].append({
                "name": f.stem,
                "file": f.name,
                "examples": lines,
                "size_kb": round(size_kb, 1),
                "type": "train",
            })
        except Exception:
            pass

    # Live/collected datasets
    collected = datasets_dir / "collected"
    if collected.exists():
        for f in sorted(collected.glob("*.jsonl")):
            try:
                lines = sum(1 for _ in open(f, encoding="utf-8", errors="replace"))
                size_kb = f.stat().st_size / 1024
                result["datasets"].append({
                    "name": f.stem,
                    "file": f.name,
                    "examples": lines,
                    "size_kb": round(size_kb, 1),
                    "type": "live",
                })
            except Exception:
                pass

    return jsonify(result)
