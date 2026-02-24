"""
Prepare training data from live system metrics.

Reads from MetricsDB training_candidates table, formats into JSONL
compatible with Unsloth/SFTTrainer, and outputs to training/datasets/.

Usage:
    python -m training.prepare_from_live [--dataset tag_extraction] [--min-quality 0.7]
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

TRAINING_DIR = Path(__file__).parent
DATASETS_DIR = TRAINING_DIR / "datasets"


def _get_metrics_db():
    """Lazy import to avoid circular deps at module level."""
    from engine.observability.metrics_db import get_metrics_db
    return get_metrics_db()


def _format_for_gemma(input_text: str, output_text: str) -> dict:
    """Format a single example in Alpaca/ShareGPT style for Unsloth."""
    return {
        "instruction": input_text,
        "output": output_text,
    }


def prepare_dataset(
    dataset_name: Optional[str] = None,
    min_quality: float = 0.7,
    limit: Optional[int] = None,
) -> int:
    """
    Export training candidates from MetricsDB to JSONL files.

    Args:
        dataset_name: Specific dataset to export (None = all datasets).
        min_quality: Minimum quality score threshold.
        limit: Max candidates to export per dataset.

    Returns:
        Total number of examples exported.
    """
    db = _get_metrics_db()
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    total_exported = 0

    if dataset_name:
        datasets = [dataset_name]
    else:
        datasets = [
            "tag_extraction",
            "tool_routing",
            "priority_classify",
            "decision_classify",
            "response_validate",
        ]

    for ds in datasets:
        try:
            candidates = db.get_training_candidates(
                dataset=ds,
                min_quality=min_quality,
                exported=False,
                limit=limit or 10000,
            )
        except Exception as exc:
            log.warning("Failed to fetch candidates for %s: %s", ds, exc)
            candidates = []

        if not candidates:
            log.info("No new candidates for dataset '%s'", ds)
            continue

        # Write to live-capture JSONL (separate from synthetic data)
        output_path = DATASETS_DIR / f"{ds}_live.jsonl"
        written = 0
        with open(output_path, "a", encoding="utf-8") as f:
            for c in candidates:
                inp = c.get("input_text") or c.get("input", "")
                out = c.get("output_text") or c.get("output", "")
                if not inp or not out:
                    continue
                example = _format_for_gemma(inp, out)
                f.write(json.dumps(example, ensure_ascii=False) + "\n")
                written += 1

        # Mark as exported
        ids = [c["id"] for c in candidates if "id" in c]
        if ids:
            try:
                db.mark_exported(ids)
            except Exception as exc:
                log.warning("Failed to mark exported for %s: %s", ds, exc)

        log.info("Exported %d examples for '%s' → %s", written, ds, output_path)
        total_exported += written

    return total_exported


def merge_datasets(dataset_name: str) -> int:
    """
    Merge synthetic (_train.jsonl) and live (_live.jsonl) into combined JSONL.

    Returns total line count.
    """
    parts = [
        DATASETS_DIR / f"{dataset_name}_train.jsonl",
        DATASETS_DIR / f"{dataset_name}_live.jsonl",
    ]

    output = DATASETS_DIR / f"{dataset_name}_combined.jsonl"
    total = 0

    with open(output, "w", encoding="utf-8") as out:
        for part in parts:
            if not part.exists():
                continue
            with open(part, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        out.write(line + "\n")
                        total += 1

    log.info("Merged %d examples for '%s' → %s", total, dataset_name, output)
    return total


def get_dataset_stats() -> dict:
    """Return per-dataset counts for synthetic, live, and combined files."""
    stats = {}
    for ds in ["tag_extraction", "tool_routing", "priority_classify",
                "decision_classify", "response_validate"]:
        entry = {}
        for suffix in ["train", "val", "live", "combined"]:
            path = DATASETS_DIR / f"{ds}_{suffix}.jsonl"
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    entry[suffix] = sum(1 for line in f if line.strip())
            else:
                entry[suffix] = 0
        stats[ds] = entry
    return stats


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Prepare training data from live metrics")
    parser.add_argument("--dataset", type=str, default=None, help="Dataset name (default: all)")
    parser.add_argument("--min-quality", type=float, default=0.7, help="Min quality threshold")
    parser.add_argument("--limit", type=int, default=None, help="Max candidates per dataset")
    parser.add_argument("--merge", action="store_true", help="Merge synthetic + live datasets")
    parser.add_argument("--stats", action="store_true", help="Show dataset statistics")
    args = parser.parse_args()

    if args.stats:
        for name, counts in get_dataset_stats().items():
            print(f"  {name}: {counts}")
    elif args.merge:
        datasets = [args.dataset] if args.dataset else [
            "tag_extraction", "tool_routing", "priority_classify",
            "decision_classify", "response_validate",
        ]
        for ds in datasets:
            merge_datasets(ds)
    else:
        count = prepare_dataset(
            dataset_name=args.dataset,
            min_quality=args.min_quality,
            limit=args.limit,
        )
        print(f"Exported {count} total examples")
