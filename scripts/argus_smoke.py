#!/usr/bin/env python3
"""
ARGUS Smoke Harness
===================

Regression check that drives every ARGUS analysis surface against a directory of
capture files (V8 heap snapshots + HAR) and reports PASS/FAIL per surface. Use it
to confirm the ARGUS reconnaissance toolkit still works after refactors.

Surfaces exercised:
    1. Heap CLI path     — GenericHeapAnalyzer.analyze_file() on every .heapsnapshot
    2. HAR CLI path      — HARAnalyzer.analyze_file() + Markdown report generation
    3. Heap diff         — GenericHeapAnalyzer.diff_files() across consecutive snapshots
    4. Deep analyzer     — DeepAnalyzer.analyze() on the captures directory
    5. Toolkit pipeline  — toolkit.auto_analyze() (mine_heap + deep parse + extractors + JWTs)

Each surface runs inside its own guard so one failure never masks the rest. Exit
code is non-zero if any surface fails.

Version: v1.63.1 [2026-06-17]
Author:  CosySim Team

Change Log:
    v1.63.1 [2026-06-17] — Initial: end-to-end ARGUS smoke harness over a captures dir

Usage:
    .venv/Scripts/python.exe scripts/argus_smoke.py
    .venv/Scripts/python.exe scripts/argus_smoke.py --captures path/to/dir
    .venv/Scripts/python.exe scripts/argus_smoke.py --quick   # skip 5x V8 deep parses

CONNECTS: GenericHeapAnalyzer, HARAnalyzer, DeepAnalyzer, toolkit.auto_analyze
CALLED BY: developers / CI as an ARGUS regression check
EMITS: PASS/FAIL summary table to stdout; Markdown + JSON reports under data|artifacts/argus
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ──── Repo root on path ──────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.argus.analyze import _generate_report  # reuse the CLI's Markdown writer
from scripts.argus.analyzers.deep_analyzer import DeepAnalyzer
from scripts.argus.analyzers.har_analyzer import HARAnalyzer
from scripts.argus.analyzers.heap_analyzer import GenericHeapAnalyzer
from scripts.argus import toolkit

logger = logging.getLogger("argus_smoke")

DEFAULT_CAPTURES = _ROOT / "artifacts" / "argus" / "captures"


# ──── Result tracking ────────────────────────────────────────────────────────

@dataclass
class SurfaceResult:
    """Outcome of exercising a single ARGUS surface."""

    name: str
    passed: bool = False
    duration_s: float = 0.0
    detail: str = ""
    error: str = ""
    notes: List[str] = field(default_factory=list)


def _run_surface(name: str, fn: Callable[[], SurfaceResult]) -> SurfaceResult:
    """Run one surface guarded so a crash becomes a FAIL, not an abort."""
    print(f"\n{'=' * 70}\n  {name}\n{'=' * 70}")
    start = time.time()
    try:
        result = fn()
    except Exception as exc:  # pragma: no cover - we want every failure captured
        result = SurfaceResult(name=name, passed=False, error=f"{type(exc).__name__}: {exc}")
        result.notes.append(traceback.format_exc().strip().splitlines()[-1])
        logger.error("[argus_smoke] %s failed (operation=smoke): %s", name, exc)
        traceback.print_exc()
    result.name = name
    result.duration_s = time.time() - start
    status = "PASS" if result.passed else "FAIL"
    print(f"\n  [{status}] {name} ({result.duration_s:.1f}s) — {result.detail or result.error}")
    return result


# ──── Surface 1: Heap CLI path ───────────────────────────────────────────────

def _surface_heap(heaps: List[Path]) -> SurfaceResult:
    res = SurfaceResult(name="Heap analysis")
    analyzer = GenericHeapAnalyzer()
    ok = 0
    for p in heaps:
        report = analyzer.analyze_file(p)
        line = (
            f"  {p.name:38s} strings={report.total_strings:>7,} "
            f"urls={len(report.urls):>4} api={len(report.api_endpoints):>4} "
            f"methods={len(report.method_names):>4} rpcid={len(report.rpcid_candidates):>4} "
            f"keys={len(report.api_keys):>3}"
        )
        print(line)
        if report.total_strings > 0:
            ok += 1
        else:
            res.notes.append(f"{p.name}: 0 strings extracted")
    res.passed = ok == len(heaps) and len(heaps) > 0
    res.detail = f"{ok}/{len(heaps)} heaps yielded strings"
    return res


# ──── Surface 2: HAR CLI path + report ───────────────────────────────────────

def _surface_har(har: Optional[Path]) -> SurfaceResult:
    res = SurfaceResult(name="HAR analysis + report")
    if har is None:
        res.passed = False
        res.error = "no .har file found in captures dir"
        return res

    analyzer = HARAnalyzer()
    report = analyzer.analyze_file(har)
    print(
        f"  {har.name}: entries={report.total_entries:,} "
        f"endpoints={len(report.unique_endpoints)} services={len(report.service_groups)} "
        f"auth={len(report.auth_schemes)} tokens={len(report.tokens_found)} "
        f"graphql={len(report.graphql_operations)} ws={len(report.websocket_urls)}"
    )
    for proto, count in list(report.protocol_breakdown.items())[:8]:
        print(f"    proto {proto:18s} {count}")

    # Reuse the CLI's Markdown report writer to confirm reports still serialize.
    report_path_before = set((_ROOT / "data" / "argus" / "reports").glob("*.md")) if (
        _ROOT / "data" / "argus" / "reports"
    ).exists() else set()
    _generate_report(har, report)
    report_dir = _ROOT / "data" / "argus" / "reports"
    new_reports = (set(report_dir.glob("*.md")) - report_path_before) if report_dir.exists() else set()

    res.passed = report.total_entries > 0
    res.detail = (
        f"{report.total_entries:,} entries, {len(report.unique_endpoints)} endpoints, "
        f"{len(report.service_groups)} services; "
        f"report {'written' if new_reports else 'serialized (no new file)'}"
    )
    if new_reports:
        res.notes.append(f"report: {sorted(p.name for p in new_reports)[0]}")
    return res


# ──── Surface 3: Heap diff across the time series ─────────────────────────────

def _surface_heap_diff(heaps: List[Path]) -> SurfaceResult:
    res = SurfaceResult(name="Heap diff")
    if len(heaps) < 2:
        res.passed = False
        res.error = "need >= 2 heaps to diff"
        return res

    analyzer = GenericHeapAnalyzer()
    pairs = list(zip(heaps, heaps[1:]))
    ok = 0
    for before, after in pairs:
        diff = analyzer.diff_files(before, after)
        print(
            f"  {before.name[-18:]} -> {after.name[-18:]}  "
            f"+urls={len(diff.new_urls):>3} +api={len(diff.new_api_endpoints):>3} "
            f"+methods={len(diff.new_method_names):>3} +rpcid={len(diff.new_rpcid_candidates):>3} "
            f"removed={diff.removed_count}"
        )
        ok += 1
    res.passed = ok == len(pairs)
    res.detail = f"diffed {ok} consecutive pairs"
    return res


# ──── Surface 4: Deep analyzer ───────────────────────────────────────────────

def _surface_deep(captures: Path) -> SurfaceResult:
    res = SurfaceResult(name="Deep analyzer")
    analyzer = DeepAnalyzer()
    report = analyzer.analyze(str(captures))
    print(
        f"  target={report.target or '?'} har_files={report.har_files} heap_files={report.heap_files} "
        f"entries={report.total_entries:,} endpoints={report.unique_endpoints} "
        f"services={report.services_discovered} jwts={len(report.jwts)} "
        f"firebase={'yes' if report.firebase_api_key else 'no'}"
    )
    res.passed = report.har_files > 0 and report.heap_files > 0
    res.detail = (
        f"{report.har_files} HAR + {report.heap_files} heaps analyzed, "
        f"{report.unique_endpoints} endpoints, {len(report.jwts)} JWTs"
    )
    return res


# ──── Surface 5: Toolkit master pipeline ─────────────────────────────────────

def _surface_auto(captures: Path, expected_heaps: int, expected_hars: int) -> SurfaceResult:
    res = SurfaceResult(name="Toolkit auto_analyze")
    results = toolkit.auto_analyze(str(captures))

    heaps = results.get("heaps_processed", 0)
    hars = results.get("hars_processed", 0)
    print(f"  heaps_processed={heaps} hars_processed={hars}")

    for name, finding in results.get("findings", {}).items():
        if "regex" in finding:  # heap finding
            regex = finding.get("regex", {})
            deep = finding.get("deep", {})
            agents = finding.get("agents", {})
            print(
                f"  {name[-22:]:22s} regex_findings={regex.get('findings', 0):>4} "
                f"regex_cats={regex.get('categories', 0):>2} "
                f"deep_files={deep.get('total_files', 0):>2} "
                f"agent_events={agents.get('total_events', 0):>3} "
                f"cot={finding.get('chain_of_thought', 0):>3} "
                f"schemas={finding.get('app_schemas', 0):>3} "
                f"proto={finding.get('protobuf_definitions', 0):>3} "
                f"jwts={finding.get('jwts', 0):>2}"
            )
        else:  # har finding
            print(f"  {name[-22:]:22s} refresh_token={'yes' if finding.get('refresh_token_found') else 'no'}")

    res.passed = heaps == expected_heaps and hars == expected_hars
    res.detail = (
        f"{heaps}/{expected_heaps} heaps + {hars}/{expected_hars} HARs processed; "
        f"report={results.get('report', 'n/a')}"
    )
    if not res.passed:
        res.notes.append(f"expected {expected_heaps} heaps / {expected_hars} HARs")
    return res


# ──── Driver ─────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="ARGUS smoke harness — exercise every analysis surface")
    parser.add_argument("--captures", type=Path, default=DEFAULT_CAPTURES,
                        help="Directory of capture files (default: artifacts/argus/captures)")
    parser.add_argument("--quick", action="store_true",
                        help="Skip the deep analyzer + auto_analyze (no 5x V8 deep parses)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    captures: Path = args.captures
    if not captures.is_dir():
        print(f"[FATAL] captures dir not found: {captures}")
        return 2

    heaps = sorted(captures.glob("*.heapsnapshot"))
    hars = sorted(captures.glob("*.har"))
    har = hars[0] if hars else None

    print("\n" + "#" * 70)
    print(f"#  ARGUS SMOKE HARNESS  —  {captures}")
    print(f"#  {len(heaps)} heap snapshot(s), {len(hars)} HAR file(s)  |  mode={'quick' if args.quick else 'full'}")
    print("#" * 70)

    results: List[SurfaceResult] = []
    results.append(_run_surface("Heap analysis", lambda: _surface_heap(heaps)))
    results.append(_run_surface("HAR analysis + report", lambda: _surface_har(har)))
    results.append(_run_surface("Heap diff", lambda: _surface_heap_diff(heaps)))

    if not args.quick:
        results.append(_run_surface("Deep analyzer", lambda: _surface_deep(captures)))
        results.append(_run_surface(
            "Toolkit auto_analyze",
            lambda: _surface_auto(captures, len(heaps), len(hars)),
        ))
    else:
        print("\n[skip] Deep analyzer + auto_analyze skipped (--quick)")

    # ──── Summary ────────────────────────────────────────────────────────────
    print("\n" + "#" * 70)
    print("#  SUMMARY")
    print("#" * 70)
    passed = 0
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.name:24s} {r.duration_s:6.1f}s  {r.detail or r.error}")
        for note in r.notes:
            print(f"           - {note}")
        passed += int(r.passed)

    print(f"\n  {passed}/{len(results)} surfaces passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
