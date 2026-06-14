"""
ARGUS Generic Heap Snapshot Analyzer
======================================

Analyzes V8 heap snapshots from any web application to extract API-relevant
strings: URLs, method names, API keys, configuration objects, and RPC IDs.

Version: v1.50.0 [2026-03-25]
Author:  CosySim Team

CONNECTS: data_types
CALLED BY: CLI (analyze.py)
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Set

from scripts.argus.analyzers.data_types import HeapAnalysisReport, HeapDiffReport

logger = logging.getLogger(__name__)

# ──── Extraction Patterns ────────────────────────────────────────────────────

_URL_PATTERN = re.compile(r"https?://[a-zA-Z0-9._/\-?&=%:@+~#]+", re.I)
_API_ENDPOINT_PATTERN = re.compile(
    r"https?://[^/]+/(api|v[0-9]+|graphql|\$rpc|_/[^/]+/data)/", re.I
)
_METHOD_NAME_PATTERN = re.compile(
    r"^(Create|Get|List|Update|Delete|Search|Fetch|Stream|Generate|Send|"
    r"Execute|Upload|Download|Export|Import|Validate|Verify|Check|"
    r"Start|Stop|Enable|Disable|Set|Reset|Clear|Flush|Sync|"
    r"Add|Remove|Move|Copy|Clone|Fork|Merge|Patch|Put)[A-Z][a-zA-Z0-9]+$"
)
_SERVICE_PATH_PATTERN = re.compile(
    r"[/.]([A-Z][a-zA-Z]+Service)[/.]([A-Z][a-zA-Z]+)$"
)
_RPCID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]{3,8}$")  # e.g., "ub2Bae", "wXbhsf"
_API_KEY_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"pk_(live|test)_[a-zA-Z0-9]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
]


def _redact(value: str) -> str:
    if len(value) <= 16:
        return value[:4] + "..." + value[-2:] if len(value) > 6 else "***"
    return value[:8] + "..." + value[-4:]


# ──── Heap Snapshot Parser ───────────────────────────────────────────────────


def _extract_strings_from_heap(path: Path) -> List[str]:
    """Extract all string values from a V8 heap snapshot.

    V8 heap snapshots are JSON with a "strings" array containing all
    interned strings. This function extracts that array efficiently.

    Args:
        path: Path to .heapsnapshot file.

    Returns:
        List of strings from the heap.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data.get("strings", [])
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("[ARGUS] Failed to parse heap snapshot: %s", exc)
        return []


# ──── Generic Heap Analyzer ──────────────────────────────────────────────────


class GenericHeapAnalyzer:
    """Analyze V8 heap snapshots from any web application.

    Extracts URLs, API endpoints, method names, RPC ID candidates,
    service paths, configuration objects, and API keys.
    """

    def analyze_file(self, path: Path) -> HeapAnalysisReport:
        """Analyze a single heap snapshot file.

        Args:
            path: Path to .heapsnapshot file.

        Returns:
            HeapAnalysisReport with all extracted data.
        """
        start = time.time()
        file_size_mb = path.stat().st_size / (1024 * 1024)

        strings = _extract_strings_from_heap(path)

        report = HeapAnalysisReport(
            file_path=str(path),
            file_size_mb=file_size_mb,
            total_strings=len(strings),
        )

        urls: Set[str] = set()
        api_endpoints: Set[str] = set()
        method_names: Set[str] = set()
        rpcid_candidates: Set[str] = set()
        service_paths: Set[str] = set()
        api_keys: Set[str] = set()
        config_objects: List[Dict] = []

        for s in strings:
            if not isinstance(s, str) or len(s) < 3:
                continue

            # URLs
            for m in _URL_PATTERN.finditer(s):
                url = m.group(0)
                urls.add(url)
                if _API_ENDPOINT_PATTERN.search(url):
                    api_endpoints.add(url)

            # Method names (CamelCase CRUD-style)
            if _METHOD_NAME_PATTERN.match(s):
                method_names.add(s)

            # Service/Method paths
            sm = _SERVICE_PATH_PATTERN.search(s)
            if sm:
                service_paths.add(f"{sm.group(1)}.{sm.group(2)}")

            # RPC ID candidates (short alphanumeric strings)
            if _RPCID_PATTERN.match(s) and not s.isdigit() and not s.isupper():
                rpcid_candidates.add(s)

            # API keys
            for pattern in _API_KEY_PATTERNS:
                if pattern.search(s):
                    api_keys.add(_redact(s))

            # JSON config objects
            if s.startswith("{") and len(s) > 20:
                try:
                    obj = json.loads(s)
                    if isinstance(obj, dict) and len(obj) >= 3:
                        config_objects.append(obj)
                except (json.JSONDecodeError, ValueError):
                    pass

        report.urls = sorted(urls)
        report.api_endpoints = sorted(api_endpoints)
        report.method_names = sorted(method_names)
        report.rpcid_candidates = sorted(rpcid_candidates)
        report.service_paths = sorted(service_paths)
        report.config_objects = config_objects[:50]  # Cap to prevent huge reports
        report.api_keys = sorted(api_keys)
        report.analysis_duration_ms = (time.time() - start) * 1000

        return report

    def diff_files(self, before: Path, after: Path) -> HeapDiffReport:
        """Diff two heap snapshots to find new API-relevant strings.

        Args:
            before: Path to "before" heap snapshot.
            after: Path to "after" heap snapshot.

        Returns:
            HeapDiffReport with new discoveries.
        """
        start = time.time()

        report_before = self.analyze_file(before)
        report_after = self.analyze_file(after)

        return HeapDiffReport(
            before_path=str(before),
            after_path=str(after),
            new_urls=sorted(set(report_after.urls) - set(report_before.urls)),
            new_api_endpoints=sorted(set(report_after.api_endpoints) - set(report_before.api_endpoints)),
            new_method_names=sorted(set(report_after.method_names) - set(report_before.method_names)),
            new_rpcid_candidates=sorted(set(report_after.rpcid_candidates) - set(report_before.rpcid_candidates)),
            new_config_objects=[
                o for o in report_after.config_objects
                if o not in report_before.config_objects
            ],
            removed_count=(
                len(set(report_before.urls) - set(report_after.urls))
                + len(set(report_before.method_names) - set(report_after.method_names))
            ),
            analysis_duration_ms=(time.time() - start) * 1000,
        )
