"""Training preparation and validation utilities.

Provides:
  - Multi-task combined dataset generation
  - Dataset quality validation / pre-flight checks
  - Nexus-curated data integration
  - Training run configuration builder

Usage::

    python -m training.prepare_training --validate          # validate all datasets
    python -m training.prepare_training --combine           # create multi-task dataset
    python -m training.prepare_training --augment-nexus     # add Nexus Q&A data
    python -m training.prepare_training --preflight         # full pre-flight check
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DATASET_DIR = Path("training/datasets")
CUSTOM_DIR = DATASET_DIR / "custom"

TASK_PREFIXES = {
    "tag_extraction": "Extract tags from this response",
    "tool_routing": "Classify the following intent and return the appropriate tool call",
    "priority_classify": "Classify this request's priority tier and routing",
    "decision_classify": "Decide the next action for this character state",
    "response_validate": "Validate whether the LLM response matches the expected format",
}

EXPECTED_DATASETS = list(TASK_PREFIXES.keys())


# ── Data Structures ──────────────────────────────────────────────

@dataclass
class DatasetReport:
    """Quality report for a single dataset."""

    name: str
    train_count: int = 0
    val_count: int = 0
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    avg_input_len: float = 0.0
    avg_output_len: float = 0.0
    unique_instructions: int = 0

    @property
    def is_valid(self) -> bool:
        return len(self.issues) == 0

    def summary(self) -> str:
        status = "✅" if self.is_valid else "❌"
        lines = [
            f"{status} {self.name}: {self.train_count} train / {self.val_count} val",
            f"   Avg input: {self.avg_input_len:.0f} chars, Avg output: {self.avg_output_len:.0f} chars",
            f"   Unique instructions: {self.unique_instructions}",
        ]
        for issue in self.issues:
            lines.append(f"   ❌ {issue}")
        for warning in self.warnings:
            lines.append(f"   ⚠️ {warning}")
        return "\n".join(lines)


@dataclass
class PreflightReport:
    """Full pre-flight check report."""

    datasets: List[DatasetReport] = field(default_factory=list)
    total_examples: int = 0
    ready_for_training: bool = False

    def summary(self) -> str:
        lines = ["═" * 60, "TRAINING PRE-FLIGHT REPORT", "═" * 60, ""]
        for ds in self.datasets:
            lines.append(ds.summary())
            lines.append("")
        lines.append(f"Total examples: {self.total_examples}")
        lines.append(f"Ready: {'✅ YES' if self.ready_for_training else '❌ NO'}")
        return "\n".join(lines)


# ── Validation ───────────────────────────────────────────────────

def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load a JSONL file into a list of dicts."""
    if not path.exists():
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("Line %d in %s: invalid JSON: %s", i, path.name, e)
    return items


def validate_dataset(name: str, dataset_dir: Path = DATASET_DIR) -> DatasetReport:
    """Validate a single dataset for quality issues."""
    report = DatasetReport(name=name)

    train_path = dataset_dir / f"{name}_train.jsonl"
    val_path = dataset_dir / f"{name}_val.jsonl"

    # Check existence
    if not train_path.exists():
        report.issues.append(f"Missing train file: {train_path}")
        return report
    if not val_path.exists():
        report.warnings.append(f"Missing val file: {val_path}")

    train_data = _load_jsonl(train_path)
    val_data = _load_jsonl(val_path)
    report.train_count = len(train_data)
    report.val_count = len(val_data)

    # Check minimum counts
    if report.train_count < 50:
        report.issues.append(f"Too few training examples: {report.train_count} (min 50)")
    if report.val_count < 10:
        report.warnings.append(f"Few validation examples: {report.val_count} (recommend 10+)")

    # Check required fields
    all_data = train_data + val_data
    required_fields = {"instruction", "input", "output"}
    for i, item in enumerate(all_data):
        missing = required_fields - set(item.keys())
        if missing:
            report.issues.append(f"Example {i}: missing fields {missing}")
            if len(report.issues) > 10:
                report.issues.append("...truncated (too many field errors)")
                break

    # Compute stats
    if all_data:
        input_lens = [len(item.get("input", "")) for item in all_data]
        output_lens = [len(item.get("output", "")) for item in all_data]
        report.avg_input_len = sum(input_lens) / len(input_lens)
        report.avg_output_len = sum(output_lens) / len(output_lens)

        instructions = set(item.get("instruction", "") for item in all_data)
        report.unique_instructions = len(instructions)

    # Check for duplicates
    seen = set()
    dupes = 0
    for item in train_data:
        key = (item.get("input", ""), item.get("output", ""))
        if key in seen:
            dupes += 1
        seen.add(key)
    if dupes > 0:
        pct = 100 * dupes / len(train_data)
        if pct > 10:
            report.issues.append(f"High duplicate rate: {dupes}/{len(train_data)} ({pct:.1f}%)")
        else:
            report.warnings.append(f"Some duplicates: {dupes}/{len(train_data)} ({pct:.1f}%)")

    # Check empty outputs
    empty = sum(1 for item in all_data if not item.get("output", "").strip())
    if empty > 0:
        report.issues.append(f"Empty outputs: {empty}")

    return report


def validate_all(dataset_dir: Path = DATASET_DIR) -> PreflightReport:
    """Validate all expected datasets."""
    report = PreflightReport()

    for name in EXPECTED_DATASETS:
        ds_report = validate_dataset(name, dataset_dir)
        report.datasets.append(ds_report)
        report.total_examples += ds_report.train_count + ds_report.val_count

    report.ready_for_training = all(ds.is_valid for ds in report.datasets)
    return report


# ── Multi-Task Combined Dataset ─────────────────────────────────

def create_combined_dataset(
    dataset_dir: Path = DATASET_DIR,
    output_prefix: str = "combined_multitask",
    shuffle: bool = True,
    seed: int = 42,
) -> Dict[str, int]:
    """Merge all task datasets into a single multi-task training set.

    Each example gets a task prefix prepended to distinguish tasks,
    enabling the model to learn task routing alongside execution.

    Args:
        dataset_dir: Directory containing per-task JSONL files.
        output_prefix: Filename prefix for output files.
        shuffle: Whether to shuffle the combined dataset.
        seed: Random seed for reproducibility.

    Returns:
        Dict with train/val counts per task and totals.
    """
    random.seed(seed)
    combined_train: List[Dict[str, Any]] = []
    combined_val: List[Dict[str, Any]] = []
    stats: Dict[str, int] = {}

    for task_name in EXPECTED_DATASETS:
        train_path = dataset_dir / f"{task_name}_train.jsonl"
        val_path = dataset_dir / f"{task_name}_val.jsonl"

        if not train_path.exists():
            logger.warning("Skipping %s — no train file", task_name)
            continue

        train_data = _load_jsonl(train_path)
        val_data = _load_jsonl(val_path) if val_path.exists() else []

        # Tag each example with its task for multi-task learning
        for item in train_data + val_data:
            item["_task"] = task_name

        combined_train.extend(train_data)
        combined_val.extend(val_data)
        stats[task_name] = len(train_data) + len(val_data)

    # Also include any custom datasets (instruction format only)
    custom_dir = dataset_dir / "custom"
    if custom_dir.exists():
        for jsonl in custom_dir.glob("*_train.jsonl"):
            task_name = jsonl.stem.replace("_train", "")
            train_data = _load_jsonl(jsonl)
            val_path = custom_dir / f"{task_name}_val.jsonl"
            val_data = _load_jsonl(val_path) if val_path.exists() else []
            # Filter to instruction-format only (skip chat_ml entries)
            required = {"instruction", "input", "output"}
            train_data = [d for d in train_data if required.issubset(d.keys())]
            val_data = [d for d in val_data if required.issubset(d.keys())]
            if not train_data:
                logger.info("Skipping custom/%s — no instruction-format examples", task_name)
                continue
            for item in train_data + val_data:
                item["_task"] = f"custom_{task_name}"
            combined_train.extend(train_data)
            combined_val.extend(val_data)
            stats[f"custom_{task_name}"] = len(train_data) + len(val_data)

    if shuffle:
        random.shuffle(combined_train)
        random.shuffle(combined_val)

    # Write combined files
    train_out = dataset_dir / f"{output_prefix}_train.jsonl"
    val_out = dataset_dir / f"{output_prefix}_val.jsonl"
    _write_jsonl(combined_train, train_out)
    _write_jsonl(combined_val, val_out)

    stats["_total_train"] = len(combined_train)
    stats["_total_val"] = len(combined_val)
    stats["_total"] = len(combined_train) + len(combined_val)
    return stats


def _write_jsonl(items: List[Dict[str, Any]], path: Path) -> None:
    """Write list of dicts as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ── Nexus Augmentation ───────────────────────────────────────────

def augment_from_nexus(
    nexus_url: str = "http://localhost:8700",
    output_dir: Path = CUSTOM_DIR,
    fmt: str = "instruction",
) -> Dict[str, int]:
    """Pull Q&A and knowledge entries from Nexus, format as training data.

    Uses the DatasetCurator to export Nexus knowledge as training examples
    in the same format as the synthetic datasets.

    Args:
        nexus_url: Nexus API base URL.
        output_dir: Where to write the augmented JSONL files.
        fmt: Output format (instruction, chat_ml, sharegpt, raw).

    Returns:
        Dict with counts.
    """
    try:
        from engine.nexus.dataset_curator import DatasetCurator
    except ImportError:
        logger.error("DatasetCurator not available — skipping Nexus augmentation")
        return {"error": "DatasetCurator not importable"}

    curator = DatasetCurator(nexus_url=nexus_url)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: Dict[str, int] = {}

    # Export Q&A pairs as training data
    qa_path = str(output_dir / "nexus_qa_train.jsonl")
    try:
        qa_stats = curator.export_qa_dataset(qa_path, fmt=fmt)
        results["qa_exported"] = qa_stats.exported
        logger.info("Exported %d Q&A examples from Nexus", qa_stats.exported)
    except Exception as e:
        logger.warning("Failed to export Q&A from Nexus: %s", e)
        results["qa_error"] = str(e)

    # Export knowledge entries
    entry_path = str(output_dir / "nexus_entries_train.jsonl")
    try:
        entry_stats = curator.export_instruction_dataset(entry_path, fmt=fmt)
        results["entries_exported"] = entry_stats.exported
        logger.info("Exported %d entry examples from Nexus", entry_stats.exported)
    except Exception as e:
        logger.warning("Failed to export entries from Nexus: %s", e)
        results["entries_error"] = str(e)

    return results


# ── Training Config Builder ──────────────────────────────────────

def build_training_config(
    dataset_name: str = "combined_multitask",
    epochs: int = 3,
    batch_size: int = 4,
    learning_rate: float = 2e-4,
    lora_r: int = 16,
    lora_alpha: int = 16,
    max_seq_length: int = 2048,
) -> Dict[str, Any]:
    """Build a training configuration dict for the Colab notebook.

    Returns:
        Config dict that can be serialized to JSON for notebook consumption.
    """
    dataset_dir = DATASET_DIR
    train_path = dataset_dir / f"{dataset_name}_train.jsonl"
    val_path = dataset_dir / f"{dataset_name}_val.jsonl"

    train_count = len(_load_jsonl(train_path)) if train_path.exists() else 0
    val_count = len(_load_jsonl(val_path)) if val_path.exists() else 0

    return {
        "dataset_name": dataset_name,
        "train_examples": train_count,
        "val_examples": val_count,
        "model": "google/gemma-3-270m-it",
        "hyperparameters": {
            "epochs": epochs,
            "batch_size": batch_size,
            "gradient_accumulation_steps": 4,
            "learning_rate": learning_rate,
            "lr_scheduler": "cosine",
            "warmup_ratio": 0.1,
            "weight_decay": 0.01,
            "max_seq_length": max_seq_length,
        },
        "lora": {
            "r": lora_r,
            "alpha": lora_alpha,
            "dropout": 0,
            "target_modules": [
                "q_proj", "k_proj", "v_proj", "o_proj",
                "gate_proj", "up_proj", "down_proj",
            ],
        },
        "output": {
            "gguf_q4": True,
            "gguf_q8": True,
            "lora_adapter": True,
        },
    }


# ── CLI ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Training preparation utilities")
    parser.add_argument("--validate", action="store_true", help="Validate all datasets")
    parser.add_argument("--combine", action="store_true", help="Create multi-task combined dataset")
    parser.add_argument("--augment-nexus", action="store_true", help="Augment with Nexus data")
    parser.add_argument("--preflight", action="store_true", help="Full pre-flight check (validate + combine)")
    parser.add_argument("--config", action="store_true", help="Print training config JSON")
    parser.add_argument("--dataset-dir", default="training/datasets", help="Dataset directory")
    parser.add_argument("--nexus-url", default="http://localhost:8700", help="Nexus API URL")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    dataset_dir = Path(args.dataset_dir)

    if args.preflight or args.validate:
        report = validate_all(dataset_dir)
        print(report.summary())
        if not report.ready_for_training:
            sys.exit(1)

    if args.augment_nexus:
        print("\n📥 Augmenting from Nexus...")
        results = augment_from_nexus(nexus_url=args.nexus_url, output_dir=dataset_dir / "custom")
        for k, v in results.items():
            print(f"  {k}: {v}")

    if args.preflight or args.combine:
        print("\n📦 Creating combined multi-task dataset...")
        stats = create_combined_dataset(dataset_dir)
        for k, v in stats.items():
            print(f"  {k}: {v}")

    if args.config:
        config = build_training_config()
        print(json.dumps(config, indent=2))

    if not any([args.validate, args.combine, args.augment_nexus, args.preflight, args.config]):
        parser.print_help()


if __name__ == "__main__":
    main()
