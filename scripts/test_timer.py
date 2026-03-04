"""test_timer.py — time pytest runs, save results, compare across runs.

Usage:
    python scripts/test_timer.py run                  # full suite
    python scripts/test_timer.py run --tag scheduler  # subset by glob/tag
    python scripts/test_timer.py run tests/test_foo.py tests/test_bar.py
    python scripts/test_timer.py compare              # last 2 runs
    python scripts/test_timer.py compare --n 5        # last 5 runs
    python scripts/test_timer.py history              # all saved runs
    python scripts/test_timer.py slowest              # 20 slowest test files
    python scripts/test_timer.py slowest --n 30       # top N slowest
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "logs" / "test_timings"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = RESULTS_DIR / "history.jsonl"

DEFAULT_IGNORE = ["tests/test_agent_loop.py", "tests/live_wire_test.py"]


# ──── Helpers ────

def _parse_pytest_output(output: str) -> Dict[str, Any]:
    """Extract passed/failed/error/skipped counts and per-file times from output."""
    summary: Dict[str, Any] = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "total": 0}

    # Final summary line: "123 passed, 4 failed, 2 skipped in 17.34s"
    m = re.search(
        r"(\d+) passed(?:.*?(\d+) failed)?(?:.*?(\d+) error)?(?:.*?(\d+) skipped)?.*?in ([\d.]+)s",
        output,
    )
    if m:
        summary["passed"]  = int(m.group(1) or 0)
        summary["failed"]  = int(m.group(2) or 0)
        summary["error"]   = int(m.group(3) or 0)
        summary["skipped"] = int(m.group(4) or 0)
        summary["total"]   = summary["passed"] + summary["failed"] + summary["error"]
        summary["pytest_reported_duration"] = float(m.group(5))

    # Per-file durations from --durations output or verbose lines
    # pytest --durations=0 emits: "0.34s call     tests/test_foo.py::test_bar"
    file_times: Dict[str, float] = {}
    for line in output.splitlines():
        dm = re.match(r"\s*([\d.]+)s\s+(?:call|setup|teardown)\s+(tests/[\w/]+\.py)::", line)
        if dm:
            fname = dm.group(2)
            file_times[fname] = file_times.get(fname, 0.0) + float(dm.group(1))
    summary["file_times"] = file_times
    return summary


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


def _save_result(record: Dict[str, Any]) -> None:
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _load_history(n: Optional[int] = None) -> List[Dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    lines = [l for l in HISTORY_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    records = [json.loads(l) for l in lines]
    if n:
        records = records[-n:]
    return records


def _colour(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


# ──── Subcommands ────

def cmd_run(args: argparse.Namespace) -> None:
    """Run pytest, time it, save the result."""
    # Build pytest command
    targets = args.targets or ["tests/"]
    cmd = [sys.executable, "-m", "pytest"] + targets + ["--tb=short", "-q", "--durations=0"]
    for ig in DEFAULT_IGNORE:
        cmd += ["--ignore", ig]
    if args.tag:
        cmd += ["-m", args.tag]

    label = args.label or " ".join(targets)
    print(f"\n⏱  Running: {' '.join(cmd)}\n{'─'*60}")

    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=False, text=True, cwd=str(ROOT))
    # Re-run capturing output just for parsing (fast — pytest already ran)
    result_cap = subprocess.run(
        cmd + ["--co", "-q"],   # collection-only for count
        capture_output=True, text=True, cwd=str(ROOT)
    )
    elapsed = time.perf_counter() - t0

    # Parse output
    # Re-run with captured output for summary parsing
    result2 = subprocess.run(
        [sys.executable, "-m", "pytest"] + targets +
        ["--tb=no", "-q", "--durations=0"] +
        [item for ig in DEFAULT_IGNORE for item in ["--ignore", ig]],
        capture_output=True, text=True, cwd=str(ROOT)
    )
    stats = _parse_pytest_output(result2.stdout + result2.stderr)
    stats["wall_time"] = round(elapsed, 2)

    record: Dict[str, Any] = {
        "ts":       datetime.now().isoformat(timespec="seconds"),
        "label":    label,
        "targets":  targets,
        "tag":      args.tag or "",
        "duration": round(elapsed, 2),
        "passed":   stats.get("passed", 0),
        "failed":   stats.get("failed", 0),
        "error":    stats.get("error", 0),
        "skipped":  stats.get("skipped", 0),
        "total":    stats.get("total", 0),
        "file_times": stats.get("file_times", {}),
        "returncode": result.returncode,
    }
    _save_result(record)

    # Summary
    status = _colour("✅ PASSED", "32") if result.returncode == 0 else _colour("❌ FAILED", "31")
    print(f"\n{'─'*60}")
    print(f"  {status}")
    print(f"  Tests : {record['total']} ({record['passed']} passed, {record['failed']} failed, {record['skipped']} skipped)")
    print(f"  Time  : {_fmt_duration(elapsed)}")
    print(f"  Rate  : {record['total']/elapsed:.1f} tests/s" if elapsed > 0 else "")
    print(f"  Saved : logs/test_timings/history.jsonl")
    print(f"{'─'*60}\n")

    # Compare with previous if exists
    history = _load_history()
    same_label = [r for r in history[:-1] if r.get("label") == label]
    if same_label:
        prev = same_label[-1]
        delta = elapsed - prev["duration"]
        sign = "+" if delta > 0 else ""
        colour = "31" if delta > 5 else ("33" if delta > 0 else "32")
        print(f"  vs last run: {_fmt_duration(prev['duration'])}  →  {_colour(f'{sign}{delta:.1f}s', colour)}\n")


def cmd_compare(args: argparse.Namespace) -> None:
    """Show side-by-side comparison of last N runs."""
    history = _load_history(args.n)
    if len(history) < 2:
        print("Need at least 2 saved runs to compare. Run `test_timer.py run` first.")
        return

    print(f"\n{'─'*70}")
    print(f"  {'#':<3}  {'Label':<30}  {'Tests':>6}  {'Pass':>6}  {'Fail':>5}  {'Time':>8}  {'Rate':>8}")
    print(f"{'─'*70}")

    baseline = history[0]["duration"]
    for i, r in enumerate(history):
        delta = r["duration"] - baseline if i > 0 else 0
        sign = "+" if delta > 0 else ""
        dt_str = f"({sign}{delta:.1f}s)" if i > 0 else "(baseline)"
        fail_col = _colour(str(r['failed']), "31") if r['failed'] else str(r['failed'])
        rate = f"{r['total']/r['duration']:.1f}/s" if r['duration'] > 0 else "—"
        print(
            f"  {i+1:<3}  {r['label'][:30]:<30}  {r['total']:>6}  "
            f"{r['passed']:>6}  {fail_col:>5}  {_fmt_duration(r['duration']):>8}  {rate:>8}  {dt_str}"
        )
    print(f"{'─'*70}\n")

    # Fastest vs slowest
    times = [r["duration"] for r in history]
    print(f"  Fastest: {_fmt_duration(min(times))}  |  Slowest: {_fmt_duration(max(times))}  |  Avg: {_fmt_duration(sum(times)/len(times))}\n")


def cmd_history(args: argparse.Namespace) -> None:
    """Print all saved run records."""
    history = _load_history()
    if not history:
        print("No runs recorded yet.")
        return
    print(f"\n  {len(history)} run(s) in logs/test_timings/history.jsonl\n")
    cmd_compare(argparse.Namespace(n=len(history)))


def cmd_slowest(args: argparse.Namespace) -> None:
    """Aggregate per-file times across all runs, show slowest files."""
    history = _load_history()
    agg: Dict[str, List[float]] = {}
    for r in history:
        for fname, t in r.get("file_times", {}).items():
            agg.setdefault(fname, []).append(t)

    if not agg:
        print("No per-file timing data yet. Run `test_timer.py run` with --durations first.")
        return

    # Average time per file
    avgs = {f: sum(ts) / len(ts) for f, ts in agg.items()}
    ranked = sorted(avgs.items(), key=lambda x: x[1], reverse=True)[: args.n]

    print(f"\n  Top {len(ranked)} slowest test files (avg across {len(history)} run(s)):\n")
    print(f"  {'Avg Time':>10}  {'File'}")
    print(f"  {'─'*10}  {'─'*50}")
    for fname, avg in ranked:
        bar = "█" * min(40, int(avg / max(avgs.values()) * 40))
        print(f"  {_fmt_duration(avg):>10}  {fname}  {bar}")
    print()


# ──── CLI ────

def main() -> None:
    parser = argparse.ArgumentParser(description="CosySim test timer & comparison tool")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="Run tests and record timing")
    p_run.add_argument("targets", nargs="*", help="Test files/dirs (default: tests/)")
    p_run.add_argument("--tag", "-m", help="pytest -m marker filter")
    p_run.add_argument("--label", "-l", help="Label for this run (default: targets)")

    p_cmp = sub.add_parser("compare", help="Compare last N runs side-by-side")
    p_cmp.add_argument("--n", type=int, default=5, help="Number of runs to compare")

    sub.add_parser("history", help="Show all saved runs")

    p_slow = sub.add_parser("slowest", help="Show slowest test files by avg time")
    p_slow.add_argument("--n", type=int, default=20, help="Number of files to show")

    args = parser.parse_args()

    if args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "compare":
        cmd_compare(args)
    elif args.cmd == "history":
        cmd_history(args)
    elif args.cmd == "slowest":
        cmd_slowest(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
