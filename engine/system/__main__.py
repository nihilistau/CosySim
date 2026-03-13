"""
CLI entry point for the CosySim System Process Monitor.

Usage::

    python -m engine.system                         # One-shot snapshot
    python -m engine.system --watch                 # Continuous monitoring (2s)
    python -m engine.system --watch --interval 5    # Custom interval
    python -m engine.system --git                   # Git operations only
    python -m engine.system --pid 1234              # Process tree for PID
    python -m engine.system --top 10                # Top N consumers
    python -m engine.system --top 10 --by memory    # Sort by memory
    python -m engine.system --track "push" 53472    # Track named operation
    python -m engine.system --untrack "push"        # Stop tracking
    python -m engine.system --stall                 # Check for stalled processes
    python -m engine.system --stall --pids 1234 5678  # Check specific PIDs
    python -m engine.system --lmstudio              # LMStudio processes
    python -m engine.system --python                # Python worker processes
    python -m engine.system --json                  # Output as JSON
    python -m engine.system --record                # Record snapshot to metrics DB
"""
from __future__ import annotations

import argparse
import json
import sys

from engine.system.process_monitor import get_process_monitor, _print_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m engine.system",
        description="CosySim System Process Monitor",
    )
    parser.add_argument("--watch", action="store_true", help="Continuous monitoring")
    parser.add_argument("--interval", type=float, default=2.0, help="Watch interval in seconds")
    parser.add_argument("--git", action="store_true", help="Git operations only")
    parser.add_argument("--pid", type=int, help="Show process tree for PID")
    parser.add_argument("--top", type=int, default=0, help="Show top N consumers")
    parser.add_argument("--by", choices=["cpu_seconds", "cpu_percent", "memory_mb", "memory_percent"],
                        default="cpu_seconds", help="Sort top consumers by")
    parser.add_argument("--track", nargs=2, metavar=("NAME", "PID"), help="Track a named operation")
    parser.add_argument("--track-meta", type=str, help="JSON metadata for --track (e.g. '{\"commits\": 388}')")
    parser.add_argument("--untrack", type=str, metavar="NAME", help="Stop tracking an operation")
    parser.add_argument("--stall", action="store_true", help="Check for stalled processes")
    parser.add_argument("--stall-pids", nargs="+", type=int, metavar="PID", help="PIDs to check for stalls")
    parser.add_argument("--stall-interval", type=float, default=3.0, help="Stall check interval")
    parser.add_argument("--lmstudio", action="store_true", help="Show LMStudio processes")
    parser.add_argument("--python", action="store_true", help="Show Python worker processes")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON")
    parser.add_argument("--record", action="store_true", help="Record snapshot to metrics DB")
    parser.add_argument("--category", type=str, help="Filter by process category")
    parser.add_argument("--max-iter", type=int, default=0, help="Max watch iterations (0=infinite)")

    args = parser.parse_args()
    mon = get_process_monitor()

    # ── Track / Untrack ──────────────────────────────────────────────
    if args.track:
        name, pid_str = args.track
        pid = int(pid_str)
        metadata = {}
        if args.track_meta:
            try:
                metadata = json.loads(args.track_meta)
            except json.JSONDecodeError:
                print(f"Error: invalid JSON metadata: {args.track_meta}", file=sys.stderr)
                return 1
        op = mon.track_operation(name, pid, category="user", metadata=metadata)
        if args.json_output:
            print(json.dumps(op.to_dict(), indent=2))
        else:
            print(f"Tracking operation '{name}' (PID {pid})")
            if metadata:
                print(f"  Metadata: {metadata}")
        return 0

    if args.untrack:
        op = mon.untrack_operation(args.untrack)
        if op:
            if args.json_output:
                print(json.dumps(op.to_dict(), indent=2))
            else:
                print(f"Untracked operation '{args.untrack}' (ran for {op.elapsed_human})")
        else:
            print(f"Operation '{args.untrack}' not found", file=sys.stderr)
            return 1
        return 0

    # ── Process Tree ─────────────────────────────────────────────────
    if args.pid:
        tree = mon.process_tree(args.pid)
        if args.json_output:
            print(json.dumps(tree, indent=2))
        else:
            _print_tree(tree, indent=0)
        return 0

    # ── Top Consumers ────────────────────────────────────────────────
    if args.top > 0:
        top = mon.top_consumers(args.top, sort_by=args.by)
        if args.json_output:
            print(json.dumps([p.to_dict() for p in top], indent=2))
        else:
            print(f"\nTop {args.top} processes by {args.by}:")
            print(f"{'PID':>8}  {'Name':20s}  {'CPU-s':>8}  {'CPU%':>5}  {'Mem MB':>8}  {'Uptime':>8}  Command")
            print("-" * 100)
            for p in top:
                cmd = p.cmdline_str
                if len(cmd) > 40:
                    cmd = cmd[:37] + "..."
                print(f"{p.pid:8d}  {p.name:20s}  {p.cpu_seconds:8.1f}  {p.cpu_percent:5.1f}  "
                      f"{p.memory_mb:8.1f}  {p.uptime_human:>8s}  {cmd}")
        return 0

    # ── Stall Detection ──────────────────────────────────────────────
    if args.stall:
        pids = args.stall_pids
        print(f"Checking for stalls (interval={args.stall_interval}s)...")
        stalls = mon.stall_detection(pids=pids, check_interval=args.stall_interval)
        if args.json_output:
            print(json.dumps([s.to_dict() for s in stalls], indent=2))
        else:
            if not stalls:
                print("No processes to check.")
            else:
                for s in stalls:
                    icon = {"stalled": "🔴", "slow": "🟡", "active": "🟢", "exited": "⚫"}.get(s.verdict, "?")
                    print(f"  {icon} PID {s.pid:8d}  {s.name:20s}  "
                          f"CPU-delta={s.cpu_seconds_delta:.3f}s over {s.check_interval:.1f}s  "
                          f"Mem={s.memory_mb:.1f}MB  verdict={s.verdict}")
        return 0

    # ── LMStudio ─────────────────────────────────────────────────────
    if args.lmstudio:
        procs = mon.lmstudio_processes()
        if args.json_output:
            print(json.dumps([p.to_dict() for p in procs], indent=2))
        else:
            print(f"\nLMStudio Processes ({len(procs)}):")
            for p in procs:
                print(f"  PID {p.pid:8d}  CPU={p.cpu_seconds:.1f}s  Mem={p.memory_mb:.1f}MB  {p.cmdline_str[:60]}")
        return 0

    # ── Python Workers ───────────────────────────────────────────────
    if args.python:
        procs = mon.python_workers()
        if args.json_output:
            print(json.dumps([p.to_dict() for p in procs], indent=2))
        else:
            print(f"\nPython Workers ({len(procs)}):")
            for p in procs:
                cmd = p.cmdline_str
                if len(cmd) > 60:
                    cmd = cmd[:57] + "..."
                print(f"  PID {p.pid:8d}  CPU={p.cpu_seconds:.1f}s  Mem={p.memory_mb:.1f}MB  {cmd}")
        return 0

    # ── Git Operations Only ──────────────────────────────────────────
    if args.git and not args.watch:
        ops = mon.git_operations()
        if args.json_output:
            print(json.dumps([op.to_dict() for op in ops], indent=2))
        else:
            if not ops:
                print("\nNo active git operations.")
            else:
                data = {
                    "timestamp": "",
                    "git_operations": [op.to_dict() for op in ops],
                    "tracked_operations": [t.to_dict() for t in mon.tracked_operations()],
                }
                _print_snapshot(data, git_only=True)
        return 0

    # ── Record to Metrics DB ─────────────────────────────────────────
    if args.record:
        ok = mon.record_to_metrics_db()
        if args.json_output:
            print(json.dumps({"recorded": ok}))
        else:
            print(f"Recorded to metrics DB: {'OK' if ok else 'FAILED'}")
        return 0

    # ── Continuous Watch ─────────────────────────────────────────────
    if args.watch:
        if args.json_output:
            def json_callback(data: dict) -> None:
                print(json.dumps(data))
            mon.watch(
                interval=args.interval,
                callback=json_callback,
                max_iterations=args.max_iter,
                git_only=args.git,
            )
        else:
            mon.watch(
                interval=args.interval,
                max_iterations=args.max_iter,
                git_only=args.git,
            )
        return 0

    # ── Default: One-Shot Snapshot ───────────────────────────────────
    snap = mon.system_snapshot()
    if args.json_output:
        print(json.dumps(snap, indent=2, default=str))
    else:
        _print_snapshot(snap)

    return 0


def _print_tree(node: dict, indent: int = 0) -> None:
    """Pretty-print a process tree."""
    prefix = "  " * indent
    if "error" in node and "pid" not in node:
        print(f"{prefix}{node['error']}")
        return

    pid = node.get("pid", "?")
    name = node.get("name", "?")
    cpu_s = node.get("cpu_seconds", 0)
    mem = node.get("memory_mb", 0)
    uptime = node.get("uptime", "?")
    cmd = node.get("cmdline", "")
    if len(cmd) > 50:
        cmd = cmd[:47] + "..."

    connector = "├── " if indent > 0 else ""
    print(f"{prefix}{connector}PID {pid}  {name}  CPU={cpu_s:.1f}s  Mem={mem:.1f}MB  up={uptime}")
    if cmd and cmd != name:
        print(f"{prefix}{'│   ' if indent > 0 else ''}    cmd: {cmd}")

    tracked = node.get("tracked_operation")
    if tracked:
        print(f"{prefix}{'│   ' if indent > 0 else ''}    ★ tracked: {tracked['name']} ({tracked['status']})")

    children = node.get("children_tree", [])
    for child in children:
        _print_tree(child, indent + 1)


if __name__ == "__main__":
    sys.exit(main())
