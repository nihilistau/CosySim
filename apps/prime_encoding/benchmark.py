#!/usr/bin/env python3
"""
Benchmark — Full PE comparison across all tasks and sequence lengths.
======================================================================

Runs the complete experimental matrix: 5 PE schemes x 4 tasks x 4 seq lengths
= 80 training runs. Each run trains a tiny transformer for 2000 steps and
reports accuracy.

Version: v0.1.0 [2026-03-27]
Author:  CosySim Research

Usage:
    python apps/prime_encoding/benchmark.py                  # Full benchmark
    python apps/prime_encoding/benchmark.py --quick           # Reduced (500 steps)
    python apps/prime_encoding/benchmark.py --task copy       # Single task
    python apps/prime_encoding/benchmark.py --pe zeta         # Single PE
    python apps/prime_encoding/benchmark.py --lengths 64,128  # Custom lengths
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "apps"))
sys.path.insert(0, str(ROOT))

from prime_encoding.tasks import TASK_LENGTHS
from prime_encoding.train import TrainResult, get_device, train_and_evaluate


# ──── PE Configurations ─────────────────────────────────────────────────────

PE_CONFIGS = [
    ("sinusoidal", {}),
    ("prime",      {"alpha": 0.5}),
    ("prime",      {"alpha": 1.0}),
    ("zeta",       {}),
    ("hybrid",     {"prime_ratio": 0.5}),
]

PE_LABELS = [
    "sinusoidal",
    "prime(a=0.5)",
    "prime(a=1.0)",
    "zeta",
    "hybrid",
]


def run_benchmark(
    tasks: List[str] | None = None,
    pe_indices: List[int] | None = None,
    lengths_override: Dict[str, List[int]] | None = None,
    train_steps: int = 2000,
    quiet: bool = False,
) -> List[TrainResult]:
    """Run the full benchmark matrix.

    Args:
        tasks: Which tasks to run (None = all 4).
        pe_indices: Which PE configs to test (None = all 5).
        lengths_override: Override sequence lengths per task.
        train_steps: Training steps per run.
        quiet: Suppress per-step output.

    Returns:
        List of TrainResult from all runs.
    """
    device = get_device()
    print(f"\n  Phase 2 Benchmark — Device: {device}")
    print(f"  {'=' * 60}\n")

    task_list = tasks or list(TASK_LENGTHS.keys())
    pe_list = pe_indices or list(range(len(PE_CONFIGS)))

    total_runs = len(task_list) * len(pe_list) * 4  # approx
    run_count = 0
    results: List[TrainResult] = []
    t0 = time.time()

    for task_name in task_list:
        task_lengths = (lengths_override or {}).get(task_name, TASK_LENGTHS[task_name])

        for length in task_lengths:
            print(f"\n  --- Task: {task_name} | Length: {length} ---")

            for pi in pe_list:
                pe_type, pe_kwargs = PE_CONFIGS[pi]
                label = PE_LABELS[pi]
                run_count += 1

                print(f"\n  [{run_count}] {label} (len={length}):")

                result = train_and_evaluate(
                    pe_type=pe_type,
                    task_name=task_name,
                    seq_len=length,
                    train_steps=train_steps,
                    device=device,
                    pe_kwargs=pe_kwargs,
                    quiet=quiet,
                )
                # Override pe_type with our label
                result.pe_type = label
                results.append(result)

                print(f"    => acc={result.best_accuracy:.4f} "
                      f"loss={result.final_loss:.4f} "
                      f"time={result.train_time_secs:.0f}s")

    total_time = time.time() - t0
    print(f"\n  Total: {run_count} runs in {total_time:.0f}s\n")
    return results


def print_results_table(results: List[TrainResult]) -> None:
    """Print a formatted results table grouped by task."""
    tasks = sorted(set(r.task_name for r in results))

    for task in tasks:
        task_results = [r for r in results if r.task_name == task]
        lengths = sorted(set(r.seq_len for r in task_results))
        pe_types = sorted(set(r.pe_type for r in task_results),
                          key=lambda x: PE_LABELS.index(x) if x in PE_LABELS else 99)

        print(f"\n  Task: {task.upper()}")
        header = f"  {'PE Type':<20}"
        for l in lengths:
            header += f"  len={l:<5}"
        print(header)
        print(f"  {'-' * (20 + 9 * len(lengths))}")

        for pe in pe_types:
            row = f"  {pe:<20}"
            for l in lengths:
                match = [r for r in task_results if r.pe_type == pe and r.seq_len == l]
                if match:
                    row += f"  {match[0].best_accuracy:>6.3f}"
                else:
                    row += f"  {'---':>6}"
            print(row)

    # Overall winners
    print(f"\n  {'=' * 50}")
    print(f"  WINNERS BY TASK")
    print(f"  {'=' * 50}")
    for task in tasks:
        task_results = [r for r in results if r.task_name == task]
        if task_results:
            best = max(task_results, key=lambda r: r.best_accuracy)
            print(f"  {task:<15} {best.pe_type:<20} acc={best.best_accuracy:.4f} (len={best.seq_len})")

    # Overall best PE
    pe_scores: Dict[str, List[float]] = {}
    for r in results:
        pe_scores.setdefault(r.pe_type, []).append(r.best_accuracy)

    print(f"\n  AVERAGE ACCURACY ACROSS ALL TASKS")
    print(f"  {'-' * 40}")
    for pe in sorted(pe_scores, key=lambda k: -sum(pe_scores[k]) / len(pe_scores[k])):
        avg = sum(pe_scores[pe]) / len(pe_scores[pe])
        print(f"  {pe:<20} {avg:.4f}")
    print()


def save_results(results: List[TrainResult], path: str) -> None:
    """Save results to JSON."""
    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "device": str(get_device()),
        "runs": [r.to_dict() for r in results],
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Results saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="Phase 2 Benchmark — PE Comparison")
    parser.add_argument("--quick", action="store_true", help="Quick mode (500 steps)")
    parser.add_argument("--task", type=str, help="Single task to run")
    parser.add_argument("--pe", type=str, help="Single PE type to test")
    parser.add_argument("--lengths", type=str, help="Comma-separated lengths (e.g. 64,128)")
    parser.add_argument("--steps", type=int, default=2000, help="Training steps per run")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-step output")
    args = parser.parse_args()

    steps = 500 if args.quick else args.steps
    tasks = [args.task] if args.task else None

    pe_indices = None
    if args.pe:
        matches = [i for i, l in enumerate(PE_LABELS) if args.pe.lower() in l.lower()]
        if matches:
            pe_indices = matches
        else:
            print(f"Unknown PE: {args.pe}. Available: {PE_LABELS}")
            return 1

    lengths_override = None
    if args.lengths:
        lens = [int(x) for x in args.lengths.split(",")]
        lengths_override = {t: lens for t in TASK_LENGTHS}

    results = run_benchmark(
        tasks=tasks,
        pe_indices=pe_indices,
        lengths_override=lengths_override,
        train_steps=steps,
        quiet=args.quiet,
    )

    print_results_table(results)

    out_path = ROOT / "apps" / "prime_encoding" / "results" / "phase2" / "benchmark.json"
    save_results(results, str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
