"""ARGUS HAR Miner — streaming regex-based HAR mining for large files.

Extracts rpcids, API endpoints, build labels, API keys, gRPC methods,
and internal service identifiers from HAR captures and heap timelines.
Designed for files 400MB+ using chunked streaming to avoid memory issues.

Example usage::

    from scripts.argus.har_miner import HARMiner

    miner = HARMiner()
    results = miner.mine_directory(Path("artifacts/argus/har"))
"""
from __future__ import annotations

import json
import logging
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "HARMiner",
    "mine_console_log",
    "mine_har_streaming",
    "mine_heap_strings",
    "cross_reference_yaml",
]

GOLDMINE = Path(r"artifacts\argus\har\users_dump_folder\GoldMine")

# ── Patterns ────────────────────────────────────────────────────────────────
RPCID_PAT = re.compile(r"rpcids=([A-Za-z0-9_]{4,12})")
FREQ_PAT = re.compile(r'"([A-Za-z0-9]{5,8})"')
BATCHEXEC_PAT = re.compile(r"(/_/[A-Za-z]+/data/batchexecute)")
BUILD_LABEL_PAT = re.compile(r"(boq[_\-][A-Za-z0-9._\-]+)")
API_KEY_PAT = re.compile(r"(AIza[A-Za-z0-9_\-]{30,40})")
GA_PAT = re.compile(r"(G-[A-Z0-9]{6,12})")
GRPC_METHOD_PAT = re.compile(r"(/google\.[A-Za-z0-9_.]+/[A-Za-z]+)")
INTERNAL_SERVICE_PAT = re.compile(r'"(google\.internal\.[^"]+)"')


class HARMiner:
    """High-level interface for mining HAR files and directories.

    Wraps the streaming mining functions into a directory-scanning API
    suitable for MCP skill consumption.
    """

    def __init__(self, chunk_size: int = 50 * 1024 * 1024) -> None:
        self.chunk_size = chunk_size

    def mine_directory(
        self, directory: Path, pattern: str = "*.har"
    ) -> Dict[str, Any]:
        """Mine all matching HAR files in a directory.

        Args:
            directory: Directory containing HAR files.
            pattern: Glob pattern for HAR files.

        Returns:
            Combined results with rpcids, api_urls, build_labels, domains,
            and files_scanned count.
        """
        directory = Path(directory)
        if not directory.exists():
            logger.warning("HAR directory does not exist: %s", directory)
            return {
                "rpcids": [],
                "api_urls": [],
                "build_labels": [],
                "domains": [],
                "files_scanned": 0,
            }

        all_rpcids: Set[str] = set()
        all_api_urls: Set[str] = set()
        all_build_labels: Set[str] = set()
        all_domains: Counter = Counter()
        files_scanned = 0

        for har_path in sorted(directory.rglob(pattern)):
            logger.info("Mining %s (%d MB)", har_path.name, har_path.stat().st_size // (1024 * 1024))
            try:
                result = mine_har_streaming(har_path, self.chunk_size)
                all_rpcids.update(result.get("rpcids", []))
                all_api_urls.update(result.get("api_urls", []))
                all_build_labels.update(result.get("build_labels", []))
                for domain, count in result.get("domains", {}).items():
                    all_domains[domain] += count
                files_scanned += 1
            except Exception:
                logger.exception("Failed to mine %s", har_path)

        return {
            "rpcids": sorted(all_rpcids),
            "api_urls": sorted(all_api_urls),
            "build_labels": sorted(all_build_labels),
            "domains": [d for d, _ in all_domains.most_common(50)],
            "files_scanned": files_scanned,
        }


def mine_console_log(path: Path) -> Dict[str, Any]:
    """Parse console log for build labels, analytics IDs, URLs, API keys.

    Args:
        path: Path to the console log file.

    Returns:
        Dict with extracted build_labels, api_keys, analytics_ids,
        google_urls, internal_urls, csp_violations, chrome_extensions.
    """
    content = path.read_text(encoding="utf-8", errors="replace")
    result: Dict[str, Any] = {
        "file": path.name,
        "size_bytes": len(content),
        "build_labels": sorted(set(BUILD_LABEL_PAT.findall(content))),
        "api_keys": sorted(set(API_KEY_PAT.findall(content))),
        "analytics_ids": sorted(set(GA_PAT.findall(content))),
    }

    urls = set(re.findall(r"https?://[^\s'\"\)]+", content))
    google_urls = sorted(u for u in urls if "google" in u.lower())
    internal_urls = sorted(
        u for u in urls
        if any(x in u for x in [
            "internal", "alpha", "beta", "experiment", "proactive",
            "extension", "grpc", "batchexecute", "/_/", "/api/", "notebooklm"
        ])
    )

    csp = re.findall(r"Content Security Policy[^\"]{0,300}", content)

    result["google_urls"] = google_urls[:100]
    result["internal_urls"] = internal_urls[:50]
    result["csp_violations"] = csp[:20]
    result["chrome_extensions"] = sorted(set(re.findall(r"chrome-extension://[^\s'\"\)]+", content)))[:20]

    return result


def mine_har_streaming(path: Path, chunk_size: int = 50 * 1024 * 1024) -> Dict[str, Any]:
    """Stream-parse HAR file for rpcids, endpoints, and metadata using regex on chunks.

    Args:
        path: Path to the HAR file.
        chunk_size: Size of each read chunk in bytes.

    Returns:
        Dict with rpcids, batchexecute_paths, build_labels, api_keys,
        grpc_methods, internal_services, domains, and api_urls.
    """
    rpcids: Set[str] = set()
    batchexecute_paths: Set[str] = set()
    build_labels: Set[str] = set()
    api_keys: Set[str] = set()
    grpc_methods: Set[str] = set()
    internal_services: Set[str] = set()
    domains: Counter = Counter()
    api_urls: Set[str] = set()

    freq_candidates: Counter = Counter()

    file_size = path.stat().st_size
    processed = 0
    overlap = 500

    url_pat = re.compile(r'"url"\s*:\s*"(https?://[^"]+)"')
    rpcid_in_url = re.compile(r"rpcids=([A-Za-z0-9_]{4,12})")
    freq_rpcid = re.compile(r'\[\["([A-Za-z0-9]{5,8})"')

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        prev_tail = ""
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            processed += len(chunk)

            data = prev_tail + chunk
            prev_tail = chunk[-overlap:] if len(chunk) > overlap else chunk

            for m in rpcid_in_url.finditer(data):
                rpcids.add(m.group(1))

            for m in url_pat.finditer(data):
                url = m.group(1)
                try:
                    domain = url.split("/")[2]
                    domains[domain] += 1
                except IndexError:
                    pass

                if any(x in url for x in [
                    "/_/", "/api/", "/v1beta", "/v1alpha", "/internal",
                    "proactiveassist", "batchexecute", "grpc", "/experiment"
                ]):
                    clean = url.split("?")[0]
                    if len(clean) < 300:
                        api_urls.add(clean)

            for m in BUILD_LABEL_PAT.finditer(data):
                build_labels.add(m.group(1))

            for m in API_KEY_PAT.finditer(data):
                api_keys.add(m.group(1))

            for m in BATCHEXEC_PAT.finditer(data):
                batchexecute_paths.add(m.group(1))

            for m in GRPC_METHOD_PAT.finditer(data):
                grpc_methods.add(m.group(1))

            for m in INTERNAL_SERVICE_PAT.finditer(data):
                internal_services.add(m.group(1))

            for m in freq_rpcid.finditer(data):
                freq_candidates[m.group(1)] += 1

            pct = int(processed / file_size * 100)
            if pct % 20 == 0:
                logger.debug("%s: %d%% (%d MB)", path.name, pct, processed // (1024 * 1024))

    return {
        "file": path.name,
        "size_mb": round(file_size / (1024 * 1024), 1),
        "rpcids": sorted(rpcids),
        "rpcid_count": len(rpcids),
        "freq_rpcid_candidates": dict(freq_candidates.most_common(100)),
        "batchexecute_paths": sorted(batchexecute_paths),
        "build_labels": sorted(build_labels),
        "api_keys": sorted(api_keys),
        "grpc_methods": sorted(grpc_methods),
        "internal_services": sorted(internal_services),
        "domains": dict(domains.most_common(50)),
        "api_urls": sorted(api_urls)[:200],
        "api_url_count": len(api_urls),
    }


def mine_heap_strings(path: Path) -> Dict[str, Any]:
    """Extract interesting strings from heap timeline using binary regex.

    Args:
        path: Path to the heap timeline file.

    Returns:
        Dict with rpcids, build_labels, api_keys, internal_services,
        and rpcid_candidates_top50.
    """
    rpcids: Set[str] = set()
    build_labels: Set[str] = set()
    api_keys: Set[str] = set()
    services: Set[str] = set()

    file_size = path.stat().st_size
    chunk_size = 50 * 1024 * 1024
    processed = 0

    rpcid_candidates: Counter = Counter()
    short_alpha = re.compile(r'"([A-Za-z]{5,8})"')

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            processed += len(chunk)

            for m in RPCID_PAT.finditer(chunk):
                rpcids.add(m.group(1))

            for m in BUILD_LABEL_PAT.finditer(chunk):
                build_labels.add(m.group(1))

            for m in API_KEY_PAT.finditer(chunk):
                api_keys.add(m.group(1))

            for m in INTERNAL_SERVICE_PAT.finditer(chunk):
                services.add(m.group(1))

            for m in short_alpha.finditer(chunk):
                s = m.group(1)
                if s[0].isupper() and not s.isupper():
                    rpcid_candidates[s] += 1

            pct = int(processed / file_size * 100)
            if pct % 25 == 0:
                logger.debug("%s: %d%% (%d MB)", path.name, pct, processed // (1024 * 1024))

    return {
        "file": path.name,
        "size_mb": round(file_size / (1024 * 1024), 1),
        "rpcids": sorted(rpcids),
        "build_labels": sorted(build_labels),
        "api_keys": sorted(api_keys),
        "internal_services": sorted(services),
        "rpcid_candidates_top50": dict(rpcid_candidates.most_common(50)),
    }


def cross_reference_yaml(
    all_rpcids: Set[str], yaml_path: str = "config/nlm_rpcids.yaml"
) -> Dict[str, Any]:
    """Compare discovered rpcids against existing YAML registry.

    Args:
        all_rpcids: Set of rpcids discovered from HAR/heap mining.
        yaml_path: Path to the NLM rpcids YAML registry.

    Returns:
        Dict with known_in_yaml, found_in_hars, confirmed, new_discovered,
        new_count, and confirmed_count.
    """
    import yaml
    with open(yaml_path, "r") as f:
        registry = yaml.safe_load(f)

    known_rpcids: Set[str] = set()
    for service_key in ["notebooklm", "gemini", "ai_studio", "colab"]:
        service = registry.get(service_key, {})
        ops = service.get("operations", {})
        for op_name, op_data in ops.items():
            if isinstance(op_data, dict):
                rpcid = op_data.get("rpcid")
                if rpcid:
                    known_rpcids.add(rpcid)
                rpcid_free = op_data.get("rpcid_free")
                rpcid_pro = op_data.get("rpcid_pro")
                if rpcid_free:
                    known_rpcids.add(rpcid_free)
                if rpcid_pro:
                    known_rpcids.add(rpcid_pro)

    new_rpcids = all_rpcids - known_rpcids
    confirmed = all_rpcids & known_rpcids

    return {
        "known_in_yaml": len(known_rpcids),
        "found_in_hars": len(all_rpcids),
        "confirmed": sorted(confirmed),
        "new_discovered": sorted(new_rpcids),
        "new_count": len(new_rpcids),
        "confirmed_count": len(confirmed),
    }


def main() -> None:
    """Mine all goldmine files and output combined report."""
    results: Dict[str, Any] = {}

    log_path = GOLDMINE / "gemini.google.com-1773626526520.log"
    if log_path.exists():
        logger.info("Mining console log...")
        results["console_log"] = mine_console_log(log_path)

    har_files = [
        "dashboard.render.com.har",
        "labs.google.har",
        "opal.google.har",
        "artsandculture.google2-game.com.har",
        "artsandculture.google2.com.har",
        "gemini.google.com-NEWEST.har",
    ]

    results["hars"] = {}
    for har_name in har_files:
        har_path = GOLDMINE / har_name
        if har_path.exists():
            logger.info("Mining %s (%d MB)...", har_name, har_path.stat().st_size // (1024 * 1024))
            results["hars"][har_name] = mine_har_streaming(har_path)

    heap_files = [
        "Heap-experiments-20260316T134743.heaptimeline",
        "Heap-20260316T125812.heaptimeline",
    ]

    results["heaps"] = {}
    for heap_name in heap_files:
        heap_path = GOLDMINE / heap_name
        if heap_path.exists():
            logger.info("Mining %s (%d MB)...", heap_name, heap_path.stat().st_size // (1024 * 1024))
            results["heaps"][heap_name] = mine_heap_strings(heap_path)

    all_rpcids: Set[str] = set()
    for har_data in results.get("hars", {}).values():
        all_rpcids.update(har_data.get("rpcids", []))
        for cand in har_data.get("freq_rpcid_candidates", {}):
            all_rpcids.add(cand)
    for heap_data in results.get("heaps", {}).values():
        all_rpcids.update(heap_data.get("rpcids", []))

    yaml_path = Path("config/nlm_rpcids.yaml")
    if yaml_path.exists() and all_rpcids:
        logger.info("Cross-referencing with nlm_rpcids.yaml...")
        results["cross_reference"] = cross_reference_yaml(all_rpcids, str(yaml_path))

    all_domains: Counter = Counter()
    for har_data in results.get("hars", {}).values():
        for domain, count in har_data.get("domains", {}).items():
            all_domains[domain] += count

    results["combined"] = {
        "total_rpcids_found": len(all_rpcids),
        "all_rpcids": sorted(all_rpcids),
        "top_domains": dict(all_domains.most_common(40)),
    }

    output_path = GOLDMINE / "mining_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("Full results written to %s", output_path)

    print(json.dumps(results.get("combined", {}), indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
