#!/usr/bin/env python3
"""
Training CLI - Dataset & Fine-tuning Pipeline
================================================

Manage training datasets, run fine-tuning, check benchmarks,
and curate data from live traffic.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/training.py status                # Pipeline status + dataset counts
    python apps/training.py bench                  # Run/show benchmarks
    python apps/training.py curate                 # Curate datasets from live data
    python apps/training.py train                  # Start fine-tuning
    python apps/training.py datasets               # List all datasets with line counts
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, ROOT
bootstrap()


def main() -> int:
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help"):
        print("""
  Training - Dataset & Fine-tuning Pipeline v1.57.2
  ===================================================

  Usage: python apps/training.py <command> [args...]

  Commands:
    status              Pipeline status + dataset counts
    datasets            List all datasets with line counts
    bench               Run/show benchmarks
    curate              Curate datasets from live data
    train [--status]    Start fine-tuning (or check status)
""")
        return 0

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "status" or cmd == "train":
        return run(ROOT / "training" / "auto_train.py", ["--status"] if cmd == "status" else rest)

    elif cmd == "bench":
        return _cmd_bench()

    elif cmd == "datasets":
        return _cmd_datasets()

    elif cmd == "curate":
        return run(ROOT / "training" / "auto_train.py", ["--curate"] + rest)

    else:
        print(f"Unknown command: {cmd}")
        return 1


def _cmd_datasets() -> int:
    """List all JSONL datasets with line counts."""
    datasets_dir = ROOT / "training" / "datasets"
    if not datasets_dir.exists():
        print("No datasets directory found.")
        return 1

    files = sorted(datasets_dir.glob("*.jsonl"))
    if not files:
        print("No dataset files found.")
        return 0

    print(f"\n  Training Datasets ({len(files)} files)")
    print(f"  {'-' * 60}")

    total_lines = 0
    for f in files:
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            count = sum(1 for _ in fh)
        total_lines += count
        size_kb = f.stat().st_size / 1024
        print(f"  {count:>6}  {size_kb:>7.1f} KB  {f.name}")

    print(f"  {'-' * 60}")
    print(f"  {total_lines:>6}  total examples")
    print()
    return 0


def _cmd_bench() -> int:
    """Show benchmark results."""
    bench_file = ROOT / "training" / "benchmarks.jsonl"
    if not bench_file.exists():
        print("No benchmarks file found.")
        return 1

    import json
    lines = []
    with open(bench_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    if not lines:
        print("No benchmark results found.")
        return 0

    print(f"\n  Benchmarks ({len(lines)} entries)")
    print(f"  {'-' * 60}")
    for entry in lines[-10:]:  # Last 10
        name = entry.get("name", entry.get("model", "?"))
        score = entry.get("score", entry.get("accuracy", "?"))
        ts = entry.get("timestamp", entry.get("date", ""))[:19]
        print(f"  {ts}  {name:<30} {score}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
