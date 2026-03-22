#!/usr/bin/env python3
"""
Oracle — CosySim System Diagnostic CLI
========================================

The All-Seeing Eye. Run from terminal or Claude Code to instantly see
what's healthy, what's broken, and what needs attention.

Usage:
    python scripts/oracle.py              # Full diagnostic report
    python scripts/oracle.py --errors     # Top errors only
    python scripts/oracle.py --health     # Service health only
    python scripts/oracle.py --perf       # Performance benchmarks only
    python scripts/oracle.py --trace ID   # Trace waterfall for a trace_id
    python scripts/oracle.py --logs 20    # Last N error-level log entries

Version: v1.49.4 [2026-03-22]
Author:  CosySim Team
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Oracle — CosySim System Diagnostic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--errors", action="store_true", help="Show top errors only")
    parser.add_argument("--health", action="store_true", help="Show service health only")
    parser.add_argument("--perf", action="store_true", help="Show performance only")
    parser.add_argument("--trace", type=str, help="Show trace waterfall for a trace_id")
    parser.add_argument("--logs", type=int, metavar="N", help="Show last N error-level logs")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show full details")
    args = parser.parse_args()

    from engine.observability.oracle import ensure_initialized, diagnose
    ensure_initialized()

    # Default: full diagnostic
    if not any([args.errors, args.health, args.perf, args.trace, args.logs]):
        diagnose(verbose=args.verbose)
        return

    if args.health:
        _show_health()

    if args.errors:
        _show_errors(args.verbose)

    if args.perf:
        _show_perf()

    if args.trace:
        _show_trace(args.trace)

    if args.logs:
        _show_logs(args.logs)


def _show_health() -> None:
    print("\n-- SERVICE HEALTH --")
    try:
        from engine.logging.monitor import get_system_monitor
        mon = get_system_monitor()
        snapshot = mon.snapshot()
        cpu = snapshot.get("cpu_percent", 0)
        ram = snapshot.get("ram_percent", 0)
        print(f"  CPU: {cpu:.0f}%  |  RAM: {ram:.0f}%")
        services = mon.check_services()
        for name, info in services.items():
            status = "UP" if info.get("up") else "DOWN"
            latency = info.get("latency_ms", 0)
            icon = "[OK]" if info.get("up") else "[!!]"
            print(f"  {icon} {name:20s} {status:4s}  ({latency:.0f}ms)")
    except Exception as exc:
        print(f"  [!] Unavailable: {exc}")


def _show_errors(verbose: bool) -> None:
    print("\n-- TOP ERRORS --")
    try:
        from engine.observability.error_aggregator import get_error_aggregator
        agg = get_error_aggregator()
        top = agg.get_top_errors(20)
        if not top:
            print("  No errors recorded.")
            return
        for err in top:
            mod = err["module"][-30:]
            msg = err["sample_message"][:60]
            print(f"  [{err['count']:4d}x] {mod}: {msg}")
            if verbose:
                print(f"         scenes: {', '.join(err['affected_scenes'][:3])}")
    except Exception as exc:
        print(f"  [!] Unavailable: {exc}")


def _show_perf() -> None:
    print("\n-- PERFORMANCE --")
    try:
        from engine.logging.benchmark import get_benchmarks
        benchmarks = get_benchmarks()
        if not benchmarks:
            print("  No benchmark data.")
            return
        for op, stats in list(benchmarks.items())[:10]:
            print(f"  {op:30s}  avg={stats.get('avg_ms',0):.0f}ms  p95={stats.get('p95_ms',0):.0f}ms  n={stats.get('count',0)}")
    except Exception as exc:
        print(f"  [!] Unavailable: {exc}")


def _show_trace(trace_id: str) -> None:
    print(f"\n-- TRACE: {trace_id} --")
    try:
        from engine.observability.structured_logger import get_structured_logger
        sl = get_structured_logger()
        events = sl.get_trace(trace_id)
        if not events:
            print("  No events found for this trace_id.")
            return
        for evt in events:
            ts = evt.timestamp[:19] if hasattr(evt, "timestamp") else "?"
            level = getattr(evt, "level", "?")
            msg = getattr(evt, "message", "")[:80]
            dur = getattr(evt, "duration_ms", None)
            dur_str = f" ({dur:.0f}ms)" if dur else ""
            print(f"  {ts} [{level:5s}] {msg}{dur_str}")
    except Exception as exc:
        print(f"  [!] Unavailable: {exc}")


def _show_logs(n: int) -> None:
    print(f"\n-- LAST {n} ERROR LOGS --")
    try:
        from engine.observability.structured_logger import get_structured_logger
        sl = get_structured_logger()
        events = sl.query(level="ERROR", limit=n)
        if not events:
            print("  No error logs found.")
            return
        for evt in events:
            ts = evt.timestamp[:19] if hasattr(evt, "timestamp") else "?"
            svc = getattr(evt, "service", "?")
            msg = getattr(evt, "message", "")[:80]
            print(f"  {ts} [{svc:20s}] {msg}")
    except Exception as exc:
        print(f"  [!] Unavailable: {exc}")


if __name__ == "__main__":
    main()
