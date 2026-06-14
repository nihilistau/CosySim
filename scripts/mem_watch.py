"""
Memory Watcher — Track process memory growth over time
=======================================================

Snapshots all processes every N seconds and reports which ones are growing.
Run this in a separate terminal while using the system normally.

Usage:
    python scripts/mem_watch.py              # Snapshot every 30s, report after 5 min
    python scripts/mem_watch.py --interval 10 --duration 120   # Every 10s for 2 min
    python scripts/mem_watch.py --interval 60 --duration 600   # Every 60s for 10 min

Version: v1.51.0 [2026-03-24]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-24] — Initial creation for memory leak detection
"""

from __future__ import annotations

import argparse
import psutil
import time
from collections import defaultdict
from typing import Dict, List, Tuple


def snapshot() -> Dict[int, Tuple[str, float, str]]:
    """Capture current process memory state.

    Returns:
        {pid: (name, rss_mb, cmdline_snippet)}
    """
    procs = {}
    for p in psutil.process_iter(["name", "pid", "memory_info", "cmdline"]):
        try:
            info = p.info
            rss_mb = info["memory_info"].rss / 1024 / 1024
            cmd = " ".join(info["cmdline"] or "")[:120]
            procs[info["pid"]] = (info["name"], rss_mb, cmd)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return procs


def main():
    parser = argparse.ArgumentParser(description="Watch for memory leaks")
    parser.add_argument("--interval", type=int, default=30, help="Seconds between snapshots")
    parser.add_argument("--duration", type=int, default=300, help="Total seconds to watch")
    args = parser.parse_args()

    num_snaps = max(2, args.duration // args.interval)

    print(f"Watching memory every {args.interval}s for {args.duration}s ({num_snaps} snapshots)...")
    print()

    # Collect snapshots
    history: List[Tuple[float, Dict[int, Tuple[str, float, str]]]] = []

    for i in range(num_snaps):
        snap = snapshot()
        ts = time.time()
        history.append((ts, snap))

        vm = psutil.virtual_memory()
        total_rss = sum(v[1] for v in snap.values())
        print(f"  [{time.strftime('%H:%M:%S')}] Snap {i+1}/{num_snaps}: "
              f"{vm.percent}% used | {vm.available/1024**3:.1f} GB free | "
              f"{len(snap)} procs | {total_rss/1024:.1f} GB RSS")

        if i < num_snaps - 1:
            time.sleep(args.interval)

    # Analyze growth
    print()
    print("=" * 70)
    print("  MEMORY GROWTH REPORT")
    print("=" * 70)

    first_ts, first_snap = history[0]
    last_ts, last_snap = history[-1]
    elapsed = last_ts - first_ts

    # Track per-PID growth
    growers: List[Tuple[str, int, float, float, float, str]] = []

    for pid, (name, last_mb, cmd) in last_snap.items():
        if pid in first_snap:
            _, first_mb, _ = first_snap[pid]
            growth = last_mb - first_mb
            if growth > 1.0:  # Only report > 1 MB growth
                rate = growth / (elapsed / 60) if elapsed > 0 else 0
                growers.append((name, pid, first_mb, last_mb, rate, cmd))

    # Also track by name (aggregate)
    name_first: Dict[str, float] = defaultdict(float)
    name_last: Dict[str, float] = defaultdict(float)
    name_count: Dict[str, int] = defaultdict(int)
    for pid, (name, mb, _) in first_snap.items():
        name_first[name] += mb
    for pid, (name, mb, _) in last_snap.items():
        name_last[name] += mb
        name_count[name] += 1

    # New processes that appeared
    new_pids = set(last_snap.keys()) - set(first_snap.keys())
    new_mb = sum(last_snap[pid][1] for pid in new_pids)

    # Died processes
    dead_pids = set(first_snap.keys()) - set(last_snap.keys())
    dead_mb = sum(first_snap[pid][1] for pid in dead_pids)

    # Print per-process growers
    if growers:
        growers.sort(key=lambda x: x[4], reverse=True)  # Sort by growth rate
        print(f"\n  Processes with growing memory (>{1} MB over {elapsed:.0f}s):")
        print(f"  {'PROCESS':<25} {'PID':<8} {'START':>8} {'NOW':>8} {'GROWTH':>8} {'RATE':>10}  CMD")
        print(f"  {'-'*95}")
        for name, pid, start, now, rate, cmd in growers[:20]:
            print(f"  {name:<25} {pid:<8} {start:>7.1f}M {now:>7.1f}M {now-start:>+7.1f}M {rate:>8.1f}M/min  {cmd[:40]}")
    else:
        print(f"\n  No individual process grew more than 1 MB over {elapsed:.0f}s.")

    # Print aggregate by name
    agg_growers = []
    for name in name_last:
        growth = name_last[name] - name_first.get(name, 0)
        if growth > 5.0:  # > 5 MB aggregate growth
            agg_growers.append((name, name_count[name], name_first.get(name, 0), name_last[name], growth))

    if agg_growers:
        agg_growers.sort(key=lambda x: x[4], reverse=True)
        print(f"\n  Aggregate growth by process name:")
        print(f"  {'PROCESS':<30} {'COUNT':>5} {'START':>10} {'NOW':>10} {'GROWTH':>10}")
        print(f"  {'-'*70}")
        for name, count, start, now, growth in agg_growers:
            print(f"  {name:<30} {count:>5} {start:>9.0f}M {now:>9.0f}M {growth:>+9.0f}M")

    # New and dead processes
    if new_pids:
        print(f"\n  New processes spawned: {len(new_pids)} ({new_mb:.0f} MB)")
        for pid in sorted(new_pids, key=lambda p: last_snap[p][1], reverse=True)[:10]:
            name, mb, cmd = last_snap[pid]
            print(f"    PID {pid:<6} {name:<25} {mb:>6.1f} MB  {cmd[:60]}")

    if dead_pids:
        print(f"\n  Processes that died: {len(dead_pids)} ({dead_mb:.0f} MB freed)")

    # System summary
    vm_first = history[0][1]
    vm = psutil.virtual_memory()
    print(f"\n  System memory: {vm.percent}% used | {vm.available/1024**3:.1f} GB free")
    print()


if __name__ == "__main__":
    main()
