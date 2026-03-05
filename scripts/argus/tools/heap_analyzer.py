"""
ARGUS Heap Analyzer — Parse V8 heapsnapshot files to extract rpcid → function name mappings.

Usage:
    python -m scripts.argus.tools.heap_analyzer --snapshot PATH.heapsnapshot [--rpcids rpc1,rpc2]
    python -m scripts.argus.tools.heap_analyzer --snapshot PATH.heapsnapshot --all-paths
    python -m scripts.argus.tools.heap_analyzer --snapshot PATH.heapsnapshot --service ArtifactService
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Known GAS rpcids from ARGUS config
GAS_RPCIDS = [
    "OOPYjd", "OQOG2e", "AJ6bre", "pEig0e", "ivJzse", "toGAmc",
    "LuHlxe", "UvGaob", "KKLVD", "qqL5ld", "zzomTc", "yFXSbd",
    "NFMk7c", "GXx9jd", "AvwHP",
]

# Expected rpcid pattern: 5-7 char base64url-ish
RPCID_PATTERN = re.compile(r"^[A-Za-z0-9_$]{5,8}$")
# gRPC service path: /ServiceName.MethodName
SERVICE_PATH_PATTERN = re.compile(r"^/([A-Z][a-zA-Z]+)\.([A-Z][a-zA-Z]+)$")


def load_strings(snapshot_path: str) -> list[str]:
    """Load only the strings array from a V8 heapsnapshot."""
    path = Path(snapshot_path)
    logger.info(f"Loading heapsnapshot: {path} ({path.stat().st_size / 1024 / 1024:.1f} MB)")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    strings = data.get("strings", [])
    logger.info(f"Loaded {len(strings):,} strings")
    return strings


def extract_service_paths(strings: list[str]) -> list[tuple[int, str, str, str]]:
    """Extract all gRPC-style service paths from strings.

    Returns:
        List of (index, full_path, service_name, method_name)
    """
    results = []
    for i, s in enumerate(strings):
        m = SERVICE_PATH_PATTERN.match(s)
        if m:
            results.append((i, s, m.group(1), m.group(2)))
    return results


def find_rpcid_mappings(
    strings: list[str],
    rpcids: Optional[list[str]] = None,
    window: int = 500,
) -> dict[str, dict]:
    """Map each rpcid to its nearest gRPC service paths.

    Args:
        strings: All strings from heapsnapshot.
        rpcids: rpcids to search for. Defaults to GAS_RPCIDS.
        window: Search window ±N strings around each rpcid.

    Returns:
        Dict of rpcid -> {index, nearest_path, nearest_dist, candidates}
    """
    if rpcids is None:
        rpcids = GAS_RPCIDS

    service_paths = extract_service_paths(strings)
    results = {}

    for rpcid in rpcids:
        rpcid_idx = next((i for i, s in enumerate(strings) if s == rpcid), None)
        if rpcid_idx is None:
            results[rpcid] = {"found": False, "candidates": []}
            continue

        # Find all service paths within window
        nearby = [
            (abs(sp_idx - rpcid_idx), sp_idx, path, svc, method)
            for sp_idx, path, svc, method in service_paths
            if abs(sp_idx - rpcid_idx) <= window
        ]
        nearby.sort()

        candidates = [
            {"dist": dist, "index": idx, "path": path, "service": svc, "method": method}
            for dist, idx, path, svc, method in nearby[:5]
        ]

        results[rpcid] = {
            "found": True,
            "rpcid_index": rpcid_idx,
            "candidates": candidates,
            "best_match": candidates[0] if candidates else None,
        }

    return results


def build_confirmed_map(mappings: dict[str, dict]) -> dict[str, str]:
    """Build a confirmed rpcid → method_name map from heap analysis.

    Uses distance threshold: dist < 10 = very high confidence, dist < 100 = high confidence.
    """
    confirmed = {}
    for rpcid, info in mappings.items():
        if not info.get("found"):
            continue
        best = info.get("best_match")
        if best and best["dist"] < 100:
            confirmed[rpcid] = best["method"]
    return confirmed


def search_strings_near_rpcid(
    strings: list[str],
    rpcid: str,
    window: int = 50,
    filter_fn=None,
) -> list[tuple[int, int, str]]:
    """Return all strings within ±window of the rpcid string.

    Returns:
        List of (relative_offset, absolute_index, string_value)
    """
    rpcid_idx = next((i for i, s in enumerate(strings) if s == rpcid), None)
    if rpcid_idx is None:
        return []

    results = []
    for i in range(max(0, rpcid_idx - window), min(len(strings), rpcid_idx + window + 1)):
        s = strings[i]
        if filter_fn is None or filter_fn(s):
            results.append((i - rpcid_idx, i, s))
    return results


def find_all_potential_rpcids(strings: list[str]) -> list[tuple[int, str]]:
    """Find all strings matching the rpcid pattern (5-8 char base64url)."""
    return [
        (i, s) for i, s in enumerate(strings)
        if RPCID_PATTERN.match(s) and len(s) >= 5 and s[0].isupper()
    ]


def print_report(mappings: dict[str, dict], service_paths: list) -> None:
    """Print a formatted mapping report."""
    print("\n" + "=" * 70)
    print("ARGUS HEAP ANALYZER — GAS rpcid Mapping Report")
    print("=" * 70)

    found = [(r, m) for r, m in mappings.items() if m.get("found")]
    not_found = [r for r, m in mappings.items() if not m.get("found")]

    print(f"\nFound: {len(found)} / {len(mappings)} rpcids in heap")
    print(f"Not found: {not_found}")

    print("\nrpcid Mappings (sorted by confidence):")
    print(f"{'rpcid':12s} {'idx':7s} {'dist':6s} {'method':35s} {'service'}")
    print("-" * 80)

    # Sort by distance (low dist = high confidence)
    sortable = [(r, m) for r, m in found if m.get("best_match")]
    sortable.sort(key=lambda x: x[1]["best_match"]["dist"])

    for rpcid, info in sortable:
        best = info["best_match"]
        confidence = "HIGH" if best["dist"] < 10 else "MED" if best["dist"] < 200 else "LOW"
        print(f"  {rpcid:10s} {info['rpcid_index']:7d} {best['dist']:6d} {best['method']:35s} {best['service']} [{confidence}]")
        # Show runners-up
        for c in info["candidates"][1:3]:
            if c["dist"] < 500:
                print(f"  {'':10s} {'':7s} {c['dist']:6d} {c['method']:35s} {c['service']}")

    print(f"\nAll gRPC service paths ({len(service_paths)} total):")
    for i, path, svc, method in sorted(service_paths, key=lambda x: x[0]):
        print(f"  [{i:6d}] {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ARGUS Heap Analyzer")
    parser.add_argument("--snapshot", required=True, help="Path to .heapsnapshot file")
    parser.add_argument("--rpcids", help="Comma-separated rpcids to search (default: all GAS)")
    parser.add_argument("--window", type=int, default=500, help="Search window (default: 500)")
    parser.add_argument("--all-paths", action="store_true", help="Show all gRPC service paths")
    parser.add_argument("--service", help="Filter paths to specific service name")
    parser.add_argument("--near", help="Show all strings near a specific rpcid")
    parser.add_argument("--output-json", help="Write JSON mapping to file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    strings = load_strings(args.snapshot)
    service_paths = extract_service_paths(strings)

    if args.service:
        service_paths = [(i, p, s, m) for i, p, s, m in service_paths if s == args.service]

    if args.all_paths:
        print(f"\nAll service paths ({len(service_paths)}):")
        for i, path, svc, method in sorted(service_paths, key=lambda x: x[0]):
            print(f"  [{i:6d}] {path}")
        return

    if args.near:
        nearby = search_strings_near_rpcid(strings, args.near, window=100)
        print(f"\nStrings near '{args.near}':")
        for offset, idx, s in nearby:
            marker = ">>> " if offset == 0 else f"{offset:+4d} "
            print(f"  {marker} [{idx:6d}] {s!r}")
        return

    rpcids = args.rpcids.split(",") if args.rpcids else GAS_RPCIDS
    mappings = find_rpcid_mappings(strings, rpcids, window=args.window)
    print_report(mappings, service_paths)

    confirmed = build_confirmed_map(mappings)
    if confirmed:
        print(f"\nHigh-confidence confirmed mappings ({len(confirmed)}):")
        for rpcid, method in confirmed.items():
            print(f"  {rpcid} -> {method}")

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump({"mappings": mappings, "confirmed": confirmed}, f, indent=2)
        print(f"\nJSON written to {args.output_json}")


if __name__ == "__main__":
    main()
