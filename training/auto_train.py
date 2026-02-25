"""
Auto-training loop for continuous model improvement.

Monitors MetricsDB for new training candidates, automatically exports
and triggers fine-tuning when thresholds are met.

Usage:
    python -m training.auto_train               # one-shot check
    python -m training.auto_train --daemon       # run continuously
    python -m training.auto_train --status       # show current state
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger(__name__)

TRAINING_DIR = Path(__file__).parent
DATASETS_DIR = TRAINING_DIR / "datasets"
STATE_FILE = TRAINING_DIR / ".auto_train_state.json"

DEFAULT_THRESHOLDS = {
    "tag_extraction": 100,
    "tool_routing": 50,
    "priority_classify": 50,
    "decision_classify": 50,
    "response_validate": 50,
}

DEFAULT_MIN_QUALITY = 0.8
DEFAULT_CHECK_INTERVAL = 3600  # 1 hour


def _get_metrics_db():
    from engine.observability.metrics_db import get_metrics_db
    return get_metrics_db()


def _load_state() -> dict:
    """Load persisted auto-train state."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_check": 0, "last_train": {}, "history": []}


def _save_state(state: dict):
    """Persist auto-train state."""
    STATE_FILE.write_text(
        json.dumps(state, indent=2, default=str),
        encoding="utf-8",
    )


def check_candidates(
    thresholds: Optional[Dict[str, int]] = None,
    min_quality: float = DEFAULT_MIN_QUALITY,
) -> Dict[str, int]:
    """
    Check how many unexported candidates exist per dataset.

    Returns: {dataset_name: count}
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    db = _get_metrics_db()
    counts = {}

    for dataset in thresholds:
        try:
            candidates = db.get_training_candidates(
                dataset=dataset,
                min_quality=min_quality,
                exported=False,
                limit=1,  # just need the count
            )
            # get_training_candidates might return a list; we need total count
            # Use a count-specific query if available, otherwise use len
            all_candidates = db.get_training_candidates(
                dataset=dataset,
                min_quality=min_quality,
                exported=False,
                limit=100000,
            )
            counts[dataset] = len(all_candidates)
        except Exception as exc:
            log.warning("Failed to check %s: %s", dataset, exc)
            counts[dataset] = 0

    return counts


def check_and_train(
    thresholds: Optional[Dict[str, int]] = None,
    min_quality: float = DEFAULT_MIN_QUALITY,
    dry_run: bool = False,
) -> Dict[str, dict]:
    """
    Check all datasets and train any that exceed their threshold.

    Returns: {dataset: {action, count, result}} for datasets that were trained.
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    state = _load_state()
    results = {}
    counts = check_candidates(thresholds, min_quality)

    for dataset, threshold in thresholds.items():
        count = counts.get(dataset, 0)
        if count < threshold:
            log.info("  %s: %d/%d candidates (below threshold)", dataset, count, threshold)
            continue

        log.info("  %s: %d candidates (>= %d threshold) — training!", dataset, count, threshold)

        if dry_run:
            results[dataset] = {"action": "would_train", "count": count}
            continue

        # Step 1: Export candidates
        try:
            from training.prepare_from_live import prepare_dataset
            exported = prepare_dataset(
                dataset_name=dataset,
                min_quality=min_quality,
            )
            log.info("  Exported %d examples for %s", exported, dataset)
        except Exception as exc:
            log.error("  Export failed for %s: %s", dataset, exc)
            results[dataset] = {"action": "export_failed", "error": str(exc)}
            continue

        # Step 2: Merge with existing synthetic data
        try:
            from training.prepare_from_live import merge_datasets
            merge_datasets(dataset)
        except Exception as exc:
            log.warning("  Merge failed for %s (continuing): %s", dataset, exc)

        # Step 3: Train
        try:
            from training.finetune_local import finetune, check_dependencies
            deps = check_dependencies()
            missing = [k for k, v in deps.items() if not v]
            if missing:
                log.warning("  Training deps missing: %s — skipping actual training", missing)
                results[dataset] = {
                    "action": "exported_only",
                    "count": exported,
                    "missing_deps": missing,
                }
                continue

            train_result = finetune(
                dataset_name=dataset,
                epochs=3,
                export_gguf=True,
            )
            results[dataset] = {
                "action": "trained",
                "count": exported,
                "loss": train_result.get("final_loss"),
                "output": train_result.get("output_dir"),
            }

            # Update state
            state["last_train"][dataset] = {
                "timestamp": time.time(),
                "examples": exported,
                "loss": train_result.get("final_loss"),
            }

        except ImportError as exc:
            log.warning("  Training deps not available: %s", exc)
            results[dataset] = {"action": "exported_only", "count": exported}
        except Exception as exc:
            log.error("  Training failed for %s: %s", dataset, exc)
            results[dataset] = {"action": "train_failed", "count": exported, "error": str(exc)}

    state["last_check"] = time.time()
    if results:
        state["history"].append({
            "timestamp": time.time(),
            "results": {k: v.get("action", "unknown") for k, v in results.items()},
        })
        # Keep last 50 entries
        state["history"] = state["history"][-50:]

    _save_state(state)

    # Log training results to Nexus (best-effort)
    if results:
        _log_training_to_nexus(results)

    return results


def _log_training_to_nexus(results: Dict[str, dict]) -> None:
    """Log training run results to Nexus knowledge store."""
    try:
        import urllib.request
        for dataset, info in results.items():
            data = json.dumps({
                "content": json.dumps({
                    "dataset": dataset,
                    "action": info.get("action", "unknown"),
                    "examples": info.get("count", 0),
                    "loss": info.get("loss"),
                    "output": info.get("output"),
                    "timestamp": time.time(),
                }),
                "content_type": "training_run",
                "tags": ["training", dataset, info.get("action", "unknown")],
                "metadata": {"dataset": dataset, "action": info.get("action")},
                "quality_score": 0.8 if info.get("action") == "trained" else 0.5,
            }).encode()
            req = urllib.request.Request(
                "http://localhost:9400/api/knowledge",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            log.info("Logged training run for %s to Nexus", dataset)
    except Exception as exc:
        log.debug("Nexus logging skipped: %s", exc)


def daemon_loop(
    interval: int = DEFAULT_CHECK_INTERVAL,
    thresholds: Optional[Dict[str, int]] = None,
    min_quality: float = DEFAULT_MIN_QUALITY,
):
    """Run continuous auto-training loop."""
    log.info("Auto-trainer daemon starting (interval=%ds)", interval)
    while True:
        try:
            log.info("Auto-train check at %s", time.strftime("%Y-%m-%d %H:%M:%S"))
            results = check_and_train(thresholds, min_quality)
            if results:
                log.info("Auto-train results: %s", results)
            else:
                log.info("No datasets ready for training")
        except Exception as exc:
            log.error("Auto-train error: %s", exc)

        time.sleep(interval)


def get_status() -> dict:
    """Get current auto-train status."""
    state = _load_state()
    try:
        counts = check_candidates()
    except Exception:
        counts = {}

    return {
        "last_check": state.get("last_check", 0),
        "last_train": state.get("last_train", {}),
        "candidate_counts": counts,
        "thresholds": DEFAULT_THRESHOLDS,
        "recent_history": state.get("history", [])[-5:],
    }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="Auto-training loop")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=DEFAULT_CHECK_INTERVAL, help="Check interval (seconds)")
    parser.add_argument("--dry-run", action="store_true", help="Check without training")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--min-quality", type=float, default=DEFAULT_MIN_QUALITY)
    args = parser.parse_args()

    if args.status:
        status = get_status()
        print(json.dumps(status, indent=2, default=str))
    elif args.daemon:
        daemon_loop(interval=args.interval, min_quality=args.min_quality)
    else:
        results = check_and_train(min_quality=args.min_quality, dry_run=args.dry_run)
        if results:
            for ds, info in results.items():
                print(f"  {ds}: {info}")
        else:
            print("No datasets ready for training")
