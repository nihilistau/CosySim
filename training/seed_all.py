"""seed_all.py — Bootstrap all training datasets from existing sources.

Runs all dataset generators to create baseline training data before live runtime
data has been collected. Safe to re-run — appends to existing datasets.

Usage:
    python -m training.seed_all
    python -m training.seed_all --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ──── Seed Targets ────

_RESULTS: Dict[str, Any] = {}


def _seed_coder(dry_run: bool = False) -> int:
    """Seed coder dataset from CosySim codebase + Nexus Q&A.

    Returns:
        Number of examples generated.
    """
    try:
        from training.coder_pipeline import get_coder_pipeline
        if dry_run:
            logger.info("[coder] DRY RUN — would call refresh_dataset()")
            return 0
        pipeline = get_coder_pipeline()
        count = pipeline.refresh_dataset()
        logger.info("[coder] Generated %d examples", count)
        return count
    except Exception as exc:
        logger.error("[coder] Failed: %s", exc)
        return 0


def _seed_tool_dispatch(dry_run: bool = False) -> int:
    """Seed tool_dispatch dataset from skill registry.

    Returns:
        Number of examples generated.
    """
    try:
        from training.datasets.generate_tool_dispatch import generate_from_registry, save_dataset
        if dry_run:
            logger.info("[tool_dispatch] DRY RUN — would call generate_from_registry()")
            return 0
        examples = generate_from_registry(limit=1000)
        out_path = Path("training/datasets/tool_dispatch_train.jsonl")
        save_dataset(examples, output_path=out_path)
        logger.info("[tool_dispatch] Generated %d examples → %s", len(examples), out_path)
        return len(examples)
    except Exception as exc:
        logger.error("[tool_dispatch] Failed: %s", exc)
        return 0


def _seed_conversational(dry_run: bool = False) -> int:
    """Seed conversational dataset from character profiles + dialog history.

    Returns:
        Number of examples generated.
    """
    try:
        from training.datasets.generate_conversation import (
            extract_from_event_chain,
            extract_from_nexus,
            save_dataset as save_conv_dataset,
        )
        if dry_run:
            logger.info("[conversational] DRY RUN — would extract conversations")
            return 0
        examples = []
        examples.extend(extract_from_event_chain(limit=2000))
        examples.extend(extract_from_nexus(limit=500))
        out_path = Path("training/datasets/conversational_train.jsonl")
        save_conv_dataset(examples, output_path=out_path)
        logger.info("[conversational] Generated %d examples → %s", len(examples), out_path)
        return len(examples)
    except Exception as exc:
        logger.error("[conversational] Failed: %s", exc)
        return 0


def _seed_grammar_scanner(dry_run: bool = False) -> int:
    """Seed grammar_scanner dataset from micro-dataset templates.

    Returns:
        Number of examples generated.
    """
    try:
        from training.micro_datasets import MicroDatasetManager
        if dry_run:
            logger.info("[grammar_scanner] DRY RUN — would build micro-dataset templates")
            return 0
        builder = MicroDatasetManager()
        stats = builder.build("grammar_scanner", count=500)
        count = stats.train_count if hasattr(stats, "train_count") else (stats.get("train_count", 0) if isinstance(stats, dict) else 0)
        logger.info("[grammar_scanner] Generated %d training examples", count)
        return count
    except Exception as exc:
        logger.error("[grammar_scanner] Failed: %s", exc)
        return 0


def _seed_router(dry_run: bool = False) -> int:
    """Seed router dataset from RouterDataCollector export.

    Returns:
        Number of examples generated.
    """
    try:
        from engine.lmstudio.router_data import get_router_data_collector
        if dry_run:
            logger.info("[router] DRY RUN — would export router data")
            return 0
        collector = get_router_data_collector()
        out_path = str(Path("training/datasets/router_train.jsonl"))
        count = collector.export_jsonl(out_path)
        logger.info("[router] Exported %d examples → %s", count, out_path)
        return count
    except Exception as exc:
        logger.error("[router] Failed: %s", exc)
        return 0


# ──── Main ────

_SEEDS = [
    ("coder",          _seed_coder),
    ("tool_dispatch",  _seed_tool_dispatch),
    ("conversational", _seed_conversational),
    ("grammar_scanner", _seed_grammar_scanner),
    ("router",         _seed_router),
]


def seed_all(dry_run: bool = False) -> Dict[str, int]:
    """Run all dataset seed functions.

    Args:
        dry_run: If True, log what would happen without writing files.

    Returns:
        Dict mapping model_type to example count.
    """
    results: Dict[str, int] = {}
    total_start = time.time()
    logger.info("═══ CosySim Training Dataset Seed (%s) ═══", "DRY RUN" if dry_run else "LIVE")

    for name, fn in _SEEDS:
        t0 = time.time()
        count = fn(dry_run=dry_run)
        elapsed = time.time() - t0
        results[name] = count
        logger.info("  %-20s %5d examples  (%.1fs)", name, count, elapsed)

    total = sum(results.values())
    elapsed_total = time.time() - total_start
    logger.info("═══ Total: %d examples across %d model types (%.1fs) ═══", total, len(results), elapsed_total)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed all CosySim training datasets")
    parser.add_argument("--dry-run", action="store_true", help="Log without writing")
    args = parser.parse_args()
    results = seed_all(dry_run=args.dry_run)
    sys.exit(0 if sum(results.values()) > 0 or args.dry_run else 1)
