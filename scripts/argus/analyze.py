#!/usr/bin/env python3
"""
ARGUS Generic API Discovery CLI
=================================

Analyze any HAR file or V8 heap snapshot to discover API endpoints,
authentication schemes, protocol types, tokens, and more.

Usage:
    python -m scripts.argus.analyze har path/to/file.har
    python -m scripts.argus.analyze har path/to/file.har --json
    python -m scripts.argus.analyze heap path/to/snapshot.heapsnapshot
    python -m scripts.argus.analyze dir path/to/har_folder/
    python -m scripts.argus.analyze compare file1.har file2.har
    python -m scripts.argus.analyze heap-diff before.heap after.heap

Version: v1.50.0 [2026-03-25]
Author:  CosySim Team
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARGUS — Generic API Discovery Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # har
    har_p = sub.add_parser("har", help="Analyze a single HAR file")
    har_p.add_argument("path", type=Path)
    har_p.add_argument("--json", action="store_true", help="Output as JSON")
    har_p.add_argument("--report", action="store_true", help="Generate Markdown intelligence report")

    # heap
    heap_p = sub.add_parser("heap", help="Analyze a heap snapshot")
    heap_p.add_argument("path", type=Path)
    heap_p.add_argument("--json", action="store_true")

    # dir
    dir_p = sub.add_parser("dir", help="Batch analyze all HARs in a directory")
    dir_p.add_argument("path", type=Path)
    dir_p.add_argument("--pattern", default="*.har")
    dir_p.add_argument("--json", action="store_true")

    # deep — automated full workflow
    deep_p = sub.add_parser("deep", help="Full automated deep analysis (HAR + heap + probing)")
    deep_p.add_argument("path", type=Path, help="Directory containing HAR and heap files")

    # compare
    cmp_p = sub.add_parser("compare", help="Diff two HAR files")
    cmp_p.add_argument("file_a", type=Path)
    cmp_p.add_argument("file_b", type=Path)

    # heap-diff
    hd_p = sub.add_parser("heap-diff", help="Diff two heap snapshots")
    hd_p.add_argument("before", type=Path)
    hd_p.add_argument("after", type=Path)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "deep":
        _deep_analyze(args.path)
    elif args.command == "har":
        _analyze_har(args.path, args.json, getattr(args, 'report', False))
    elif args.command == "heap":
        _analyze_heap(args.path, args.json)
    elif args.command == "dir":
        _analyze_dir(args.path, args.pattern, args.json)
    elif args.command == "compare":
        _compare_hars(args.file_a, args.file_b)
    elif args.command == "heap-diff":
        _diff_heaps(args.before, args.after)


# ──── Deep Analysis ───────────────────────────────────────────────────────────

def _deep_analyze(path: Path) -> None:
    from scripts.argus.analyzers.deep_analyzer import DeepAnalyzer
    if not path.is_dir():
        print(f"Not a directory: {path}")
        return
    analyzer = DeepAnalyzer()
    analyzer.analyze(str(path))


# ──── HAR Analysis ───────────────────────────────────────────────────────────

def _analyze_har(path: Path, as_json: bool, as_report: bool = False) -> None:
    from scripts.argus.analyzers.har_analyzer import HARAnalyzer

    if not path.exists():
        print(f"File not found: {path}")
        return

    analyzer = HARAnalyzer()
    report = analyzer.analyze_file(path)

    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
        return

    if as_report:
        _generate_report(path, report)
        return

    print()
    print("=" * 60)
    print("  ARGUS HAR Analysis")
    print("=" * 60)
    print(f"  File:     {path.name} ({report.file_size_mb:.1f} MB)")
    print(f"  Entries:  {report.total_entries:,}")
    print(f"  Duration: {report.analysis_duration_ms:.0f} ms")

    # Protocols
    print()
    print("-- Protocols --")
    for proto, count in report.protocol_breakdown.items():
        pct = count / max(report.total_entries, 1) * 100
        print(f"  {proto:20s} {count:6,} ({pct:.1f}%)")

    # Services
    if report.service_groups:
        print()
        print("-- Services (by domain) --")
        for sg in report.service_groups[:10]:
            auth = sg.auth_schemes[0].scheme_type if sg.auth_schemes else "none"
            print(f"  {sg.domain:35s} {len(sg.endpoints):4d} endpoints   {auth}")

    # Auth
    if report.auth_schemes:
        print()
        print("-- Auth Schemes --")
        for a in report.auth_schemes[:5]:
            print(f"  {a.scheme_type:20s} {a.frequency:6,} requests   ({a.header_name})")

    # Top endpoints
    if report.unique_endpoints:
        print()
        print("-- Top Endpoints --")
        for ep in report.unique_endpoints[:10]:
            print(f"  {ep.method:6s} {ep.base_path[:50]:50s} {ep.frequency:5d} calls")

    # GraphQL
    if report.graphql_operations:
        print()
        print("-- GraphQL Operations --")
        for gql in report.graphql_operations[:8]:
            name = gql.operation_name or "anonymous"
            print(f"  {gql.operation_type:12s} {name:30s} {gql.frequency:5d} calls")

    # Rate limits
    if report.rate_limits:
        print()
        print("-- Rate Limits --")
        for rl in report.rate_limits:
            print(f"  429 responses: {rl.status_429_count} (on {rl.endpoint[:50]})")

    # Tokens
    if report.tokens_found:
        print()
        print("-- Tokens Found (REDACTED) --")
        for t in report.tokens_found[:5]:
            print(f"  {t.token_type:10s} {t.redacted_value:30s} ({t.frequency} uses)")

    if report.errors:
        print()
        print(f"  [!] {report.errors} entry processing errors")

    print()
    print("=" * 60)
    print()


# ──── Heap Analysis ──────────────────────────────────────────────────────────

def _analyze_heap(path: Path, as_json: bool) -> None:
    from scripts.argus.analyzers.heap_analyzer import GenericHeapAnalyzer

    if not path.exists():
        print(f"File not found: {path}")
        return

    analyzer = GenericHeapAnalyzer()
    report = analyzer.analyze_file(path)

    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
        return

    print()
    print("=" * 60)
    print("  ARGUS Heap Snapshot Analysis")
    print("=" * 60)
    print(f"  File:      {path.name} ({report.file_size_mb:.1f} MB)")
    print(f"  Strings:   {report.total_strings:,}")
    print(f"  Duration:  {report.analysis_duration_ms:.0f} ms")
    print()
    print(f"  URLs:              {len(report.urls):,}")
    print(f"  API endpoints:     {len(report.api_endpoints):,}")
    print(f"  Method names:      {len(report.method_names):,}")
    print(f"  RPC ID candidates: {len(report.rpcid_candidates):,}")
    print(f"  Service paths:     {len(report.service_paths):,}")
    print(f"  Config objects:    {len(report.config_objects):,}")
    print(f"  API keys:          {len(report.api_keys):,}")

    if report.api_endpoints:
        print()
        print("-- API Endpoints (top 10) --")
        for ep in report.api_endpoints[:10]:
            print(f"  {ep[:80]}")

    if report.method_names:
        print()
        print("-- Method Names (top 10) --")
        for m in report.method_names[:10]:
            print(f"  {m}")

    if report.service_paths:
        print()
        print("-- Service Paths --")
        for sp in report.service_paths[:10]:
            print(f"  {sp}")

    print()
    print("=" * 60)
    print()


# ──── Directory Batch ────────────────────────────────────────────────────────

def _analyze_dir(dir_path: Path, pattern: str, as_json: bool) -> None:
    from scripts.argus.analyzers.har_analyzer import HARAnalyzer

    if not dir_path.is_dir():
        print(f"Not a directory: {dir_path}")
        return

    analyzer = HARAnalyzer()
    reports = analyzer.analyze_directory(dir_path, pattern)

    if as_json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
        return

    print(f"\nAnalyzed {len(reports)} HAR files in {dir_path}")
    for r in reports:
        print(f"  {Path(r.file_path).name}: {r.total_entries} entries, "
              f"{len(r.unique_endpoints)} endpoints, "
              f"{len(r.service_groups)} services")


# ──── Compare ────────────────────────────────────────────────────────────────

def _compare_hars(file_a: Path, file_b: Path) -> None:
    from scripts.argus.analyzers.har_analyzer import HARAnalyzer

    analyzer = HARAnalyzer()
    report_a = analyzer.analyze_file(file_a)
    report_b = analyzer.analyze_file(file_b)
    diff = analyzer.compare(report_a, report_b)

    print(f"\n=== HAR Comparison ===")
    print(f"  A: {file_a.name} ({report_a.total_entries} entries)")
    print(f"  B: {file_b.name} ({report_b.total_entries} entries)")
    print(f"  New endpoints:     {diff['new_count']}")
    print(f"  Removed endpoints: {diff['removed_count']}")
    print(f"  Shared endpoints:  {diff['shared_count']}")

    if diff["new_endpoints"]:
        print("\n  New in B:")
        for ep in diff["new_endpoints"][:15]:
            print(f"    + {ep}")

    if diff["removed_endpoints"]:
        print("\n  Removed from A:")
        for ep in diff["removed_endpoints"][:15]:
            print(f"    - {ep}")


# ──── Heap Diff ──────────────────────────────────────────────────────────────

def _diff_heaps(before: Path, after: Path) -> None:
    from scripts.argus.analyzers.heap_analyzer import GenericHeapAnalyzer

    analyzer = GenericHeapAnalyzer()
    diff = analyzer.diff_files(before, after)

    print(f"\n=== Heap Snapshot Diff ===")
    print(f"  Before: {before.name}")
    print(f"  After:  {after.name}")
    print(f"  New URLs:          {len(diff.new_urls)}")
    print(f"  New API endpoints: {len(diff.new_api_endpoints)}")
    print(f"  New methods:       {len(diff.new_method_names)}")
    print(f"  New RPC IDs:       {len(diff.new_rpcid_candidates)}")
    print(f"  Removed:           {diff.removed_count}")

    if diff.new_api_endpoints:
        print("\n  New API endpoints:")
        for ep in diff.new_api_endpoints[:10]:
            print(f"    + {ep[:80]}")

    if diff.new_method_names:
        print("\n  New methods:")
        for m in diff.new_method_names[:10]:
            print(f"    + {m}")


# ──── Report Generator ────────────────────────────────────────────────────

def _generate_report(path: Path, report) -> None:
    """Generate a Markdown intelligence report from a HAR analysis."""
    import time as _time

    target = report.service_groups[0].domain if report.service_groups else "unknown"
    service = report.service_groups[0].service_name if report.service_groups else "unknown"
    date = _time.strftime("%Y-%m-%d")
    report_name = f"{service}_analysis_{date}.md"
    report_path = _ROOT / "data" / "argus" / "reports" / report_name

    lines = [
        f"# ARGUS Intelligence Report: {service.title()}",
        f"",
        f"> Generated: {date} | Source: {path.name}",
        f"> Target: {target}",
        f"> Classification: Passive traffic analysis",
        f"",
        f"---",
        f"",
        f"## Summary",
        f"",
        f"- **File:** {path.name} ({report.file_size_mb:.1f} MB)",
        f"- **Entries:** {report.total_entries:,}",
        f"- **Unique endpoints:** {len(report.unique_endpoints)}",
        f"- **Services discovered:** {len(report.service_groups)}",
        f"- **Auth schemes:** {len(report.auth_schemes)}",
        f"- **Analysis time:** {report.analysis_duration_ms:.0f} ms",
        f"",
        f"---",
        f"",
        f"## Protocol Breakdown",
        f"",
        f"| Protocol | Count | Percentage |",
        f"|----------|-------|------------|",
    ]

    for proto, count in report.protocol_breakdown.items():
        pct = count / max(report.total_entries, 1) * 100
        lines.append(f"| {proto} | {count} | {pct:.1f}% |")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## Services Discovered",
        f"",
        f"| Domain | Endpoints | Protocols | Auth |",
        f"|--------|-----------|-----------|------|",
    ])

    for sg in report.service_groups[:15]:
        protos = ", ".join(p.value for p in sg.protocols)
        auth = sg.auth_schemes[0].scheme_type if sg.auth_schemes else "none"
        lines.append(f"| {sg.domain} | {len(sg.endpoints)} | {protos} | {auth} |")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## API Endpoints",
        f"",
        f"| Method | Path | Frequency | Protocol |",
        f"|--------|------|-----------|----------|",
    ])

    for ep in report.unique_endpoints[:30]:
        lines.append(f"| {ep.method} | `{ep.base_path[:60]}` | {ep.frequency} | {ep.protocol.value} |")

    if report.auth_schemes:
        lines.extend([
            f"",
            f"---",
            f"",
            f"## Authentication Schemes",
            f"",
            f"| Type | Header | Frequency | Pattern |",
            f"|------|--------|-----------|---------|",
        ])
        for a in report.auth_schemes:
            lines.append(f"| {a.scheme_type} | {a.header_name} | {a.frequency} | `{a.example_pattern}` |")

    if report.tokens_found:
        lines.extend([
            f"",
            f"---",
            f"",
            f"## Tokens Found (REDACTED)",
            f"",
            f"| Type | Location | Key | Value |",
            f"|------|----------|-----|-------|",
        ])
        for t in report.tokens_found[:10]:
            lines.append(f"| {t.token_type} | {t.location} | {t.key_name} | `{t.redacted_value}` |")

    if report.graphql_operations:
        lines.extend([
            f"",
            f"---",
            f"",
            f"## GraphQL Operations",
            f"",
            f"| Type | Name | Frequency |",
            f"|------|------|-----------|",
        ])
        for g in report.graphql_operations:
            lines.append(f"| {g.operation_type} | {g.operation_name or 'anonymous'} | {g.frequency} |")

    if report.rate_limits:
        lines.extend([
            f"",
            f"---",
            f"",
            f"## Rate Limits Detected",
            f"",
        ])
        for rl in report.rate_limits:
            lines.append(f"- **{rl.endpoint}**: {rl.status_429_count} x 429")

    if report.websocket_urls:
        lines.extend([
            f"",
            f"---",
            f"",
            f"## WebSocket Endpoints",
            f"",
        ])
        for ws in report.websocket_urls:
            lines.append(f"- `{ws[:100]}`")

    lines.extend([
        f"",
        f"---",
        f"",
        f"*Report generated by ARGUS Generic API Discovery Engine v1.50.0*",
    ])

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report saved: {report_path}")
    print(f"  {len(report.unique_endpoints)} endpoints, {len(report.service_groups)} services, "
          f"{len(report.auth_schemes)} auth schemes")


if __name__ == "__main__":
    main()
