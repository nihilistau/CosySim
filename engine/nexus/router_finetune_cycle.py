"""engine/nexus/router_finetune_cycle.py — Router v3 fine-tuning cycle orchestrator.

Coordinates the full pipeline:
  1. Load router_v3.jsonl dataset
  2. Split into train/val sets
  3. Launch fine-tuning via FinetuneOrchestrator
  4. Register the resulting adapter in the model registry

Usage::
    from engine.nexus.router_finetune_cycle import get_router_finetune_cycle
    cycle = get_router_finetune_cycle()
    result = cycle.run()
"""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
_DATASETS_DIR = Path("training/datasets")
_DATASET_V3 = _DATASETS_DIR / "router_v3.jsonl"
_TRAIN_OUT = _DATASETS_DIR / "router_v3_train.jsonl"
_VAL_OUT = _DATASETS_DIR / "router_v3_val.jsonl"

ROUTER_V3_MODEL_KEY = "router_v3"
VAL_SPLIT = 0.1  # 10 % held out for validation


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load a JSONL file into a list of dicts."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _save_jsonl(examples: List[Dict[str, Any]], path: Path) -> None:
    """Save a list of dicts to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")


def _to_alpaca(example: Dict[str, Any]) -> Dict[str, Any]:
    """Convert router_v3 example to Alpaca instruction format."""
    user_text = example["messages"][0]["content"]
    label = example["label"]
    description = example.get("class_description", "")
    return {
        "instruction": (
            "Classify the following user request into exactly one of the 16 "
            "CosySim router categories. Respond with the category name only."
        ),
        "input": user_text,
        "output": label,
        "metadata": {"class_description": description},
    }


# ── RouterFinetuneCycle ───────────────────────────────────────────────────────

class RouterFinetuneCycle:
    """Orchestrates the router_v3 dataset split and fine-tuning launch."""

    _instance: Optional["RouterFinetuneCycle"] = None

    def __init__(self, dataset_path: Optional[Path] = None, seed: int = 42) -> None:
        self._dataset_path = dataset_path or _DATASET_V3
        self._seed = seed

    # ── Public API ────────────────────────────────────────────────────────────

    def prepare_splits(self) -> Dict[str, int]:
        """Split router_v3.jsonl into train/val JSONL files.

        Returns:
            Dict with ``train`` and ``val`` example counts.

        Raises:
            FileNotFoundError: If the source dataset is missing.
        """
        if not self._dataset_path.exists():
            raise FileNotFoundError(
                f"Router v3 dataset not found: {self._dataset_path}. "
                "Run training/datasets/generate_router_v3.py first."
            )

        examples = _load_jsonl(self._dataset_path)
        random.seed(self._seed)
        random.shuffle(examples)

        split_idx = max(1, int(len(examples) * (1 - VAL_SPLIT)))
        train_examples = [_to_alpaca(e) for e in examples[:split_idx]]
        val_examples = [_to_alpaca(e) for e in examples[split_idx:]]

        _save_jsonl(train_examples, _TRAIN_OUT)
        _save_jsonl(val_examples, _VAL_OUT)

        logger.info(
            "router_v3 splits: %d train, %d val → %s, %s",
            len(train_examples), len(val_examples), _TRAIN_OUT, _VAL_OUT,
        )
        return {"train": len(train_examples), "val": len(val_examples)}

    def run(self, dry_run: bool = False) -> Dict[str, Any]:
        """Run the full fine-tuning cycle.

        Args:
            dry_run: If True, prepare splits only — do not launch training.

        Returns:
            Result dict with ``status``, ``train_count``, ``val_count``.
        """
        logger.info("Starting router_v3 fine-tuning cycle (dry_run=%s)", dry_run)

        split_counts = self.prepare_splits()

        if dry_run:
            logger.info("Dry run — skipping training launch.")
            return {"status": "splits_ready", **split_counts}

        try:
            from training.finetune_orchestrator import FinetuneOrchestrator

            orchestrator = FinetuneOrchestrator()
            job = orchestrator.submit(
                model_type=ROUTER_V3_MODEL_KEY,
                dataset_path=str(_TRAIN_OUT),
            )
            logger.info("Fine-tuning job queued: %s", job)
            completed_job = orchestrator.run_next()
            logger.info("Fine-tuning job completed: %s", completed_job)
            return {"status": "training_started", "job": str(job), **split_counts}
        except Exception as exc:
            logger.error("Failed to launch fine-tuning: %s", exc)
            return {"status": "error", "error": str(exc), **split_counts}


# ── Singleton ─────────────────────────────────────────────────────────────────

def get_router_finetune_cycle(
    dataset_path: Optional[Path] = None,
) -> RouterFinetuneCycle:
    """Return the shared RouterFinetuneCycle instance."""
    if RouterFinetuneCycle._instance is None:
        RouterFinetuneCycle._instance = RouterFinetuneCycle(dataset_path=dataset_path)
    return RouterFinetuneCycle._instance


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Router v3 fine-tuning cycle")
    parser.add_argument("--dry-run", action="store_true", help="Prepare splits only, no training")
    parser.add_argument("--dataset", type=str, default=None, help="Override dataset path")
    args = parser.parse_args()

    cycle = RouterFinetuneCycle(
        dataset_path=Path(args.dataset) if args.dataset else None,
    )
    result = cycle.run(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
