"""ARGUS heap diffing — V8 heap snapshot capture and analysis via CDP.

Captures two heap snapshots (before/after an action) and diffs them to
find new string literals, object types, and function names — which often
reveal new API endpoints, rpcids, and method names.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from scripts.argus.cdp_bridge import CDPSession
from scripts.argus.config import HEAP_DIR

logger = logging.getLogger(__name__)

# Patterns that indicate API-relevant strings
_RPCID_RE_LEN = (4, 8)          # rpcids are 4–8 alphanumeric chars
_METHOD_PREFIXES = (
    "Create", "Get", "List", "Update", "Delete", "Generate", "Stream",
    "Send", "Fetch", "Download", "Upload", "Import", "Export",
    "Process", "Annotate", "Deploy", "Undeploy", "Clone", "Sync",
    "Start", "Stop", "Cancel", "Query", "Search", "Check", "Upsert",
)


@dataclass
class HeapSnapshot:
    """A parsed V8 heap snapshot."""

    raw: str
    timestamp: float = field(default_factory=time.time)
    strings: Set[str] = field(default_factory=set)
    node_types: Set[str] = field(default_factory=set)
    label: str = ""

    def __post_init__(self) -> None:
        if self.raw:
            self._parse()

    def _parse(self) -> None:
        """Extract strings and node type names from the heap JSON."""
        try:
            data = json.loads(self.raw)
        except json.JSONDecodeError as exc:
            logger.warning("HeapSnapshot parse error: %s", exc)
            return

        # strings array contains all string values in the heap
        for s in data.get("strings", []):
            if isinstance(s, str) and len(s) >= 3:
                self.strings.add(s)

        # node_types tells us what kinds of objects are in the heap
        for nt in data.get("snapshot", {}).get("meta", {}).get("node_types", []):
            if isinstance(nt, list):
                for t in nt:
                    if isinstance(t, str):
                        self.node_types.add(t)
            elif isinstance(nt, str):
                self.node_types.add(nt)


@dataclass
class HeapDiff:
    """Result of diffing two heap snapshots."""

    new_strings: Set[str] = field(default_factory=set)
    removed_strings: Set[str] = field(default_factory=set)
    new_rpcids: List[str] = field(default_factory=list)
    new_methods: List[str] = field(default_factory=list)
    new_endpoints: List[str] = field(default_factory=list)
    new_service_names: List[str] = field(default_factory=list)
    all_api_strings: List[str] = field(default_factory=list)
    before_label: str = ""
    after_label: str = ""
    duration_ms: float = 0.0

    @property
    def has_findings(self) -> bool:
        return bool(
            self.new_rpcids or self.new_methods or
            self.new_endpoints or self.new_service_names
        )

    def summary(self) -> str:
        lines = [
            f"HeapDiff [{self.before_label} → {self.after_label}]",
            f"  New strings:       {len(self.new_strings)}",
            f"  New rpcids:        {self.new_rpcids}",
            f"  New methods:       {self.new_methods[:10]}",
            f"  New endpoints:     {self.new_endpoints[:5]}",
            f"  New services:      {self.new_service_names}",
        ]
        return "\n".join(lines)


class HeapDiffer:
    """Capture and diff V8 heap snapshots via CDP to discover new API shapes."""

    def __init__(self, known_rpcids: Optional[Set[str]] = None) -> None:
        self._known_rpcids = known_rpcids or set()

    # ──── Capture ────

    async def capture(self, session: CDPSession, label: str = "") -> HeapSnapshot:
        """Take a heap snapshot from the given CDP session.

        Args:
            session: An active CDPSession with HeapProfiler enabled.
            label:   Human-readable label (e.g. "before_chat", "after_chat").

        Returns:
            A parsed HeapSnapshot.
        """
        await session.enable_heap_profiler()
        logger.info("HeapDiffer: capturing snapshot '%s'...", label)
        t0 = time.time()
        raw = await session.take_heap_snapshot()
        elapsed = (time.time() - t0) * 1000
        logger.info("HeapDiffer: snapshot '%s' captured in %.0f ms (%d chars)",
                    label, elapsed, len(raw))

        snap = HeapSnapshot(raw=raw, label=label)

        # Optionally save to disk
        if label:
            path = HEAP_DIR / f"{label}_{int(time.time())}.json"
            path.write_text(raw, encoding="utf-8")
            logger.debug("Heap snapshot saved: %s", path)

        return snap

    # ──── Diff ────

    def diff(self, before: HeapSnapshot, after: HeapSnapshot) -> HeapDiff:
        """Compute the diff between two heap snapshots.

        Returns a HeapDiff highlighting new strings that look like API artifacts.
        """
        t0 = time.time()
        new_strings = after.strings - before.strings
        removed_strings = before.strings - after.strings

        result = HeapDiff(
            new_strings=new_strings,
            removed_strings=removed_strings,
            before_label=before.label,
            after_label=after.label,
        )

        for s in new_strings:
            self._classify_string(s, result)

        result.duration_ms = (time.time() - t0) * 1000
        logger.info("HeapDiff: %d new strings → %d rpcids, %d methods, %d endpoints",
                    len(new_strings), len(result.new_rpcids),
                    len(result.new_methods), len(result.new_endpoints))
        return result

    # ──── String classification ────

    def _classify_string(self, s: str, result: HeapDiff) -> None:
        """Classify a new heap string and add it to the appropriate diff bucket."""
        # rpcid: 4–8 alphanumeric chars, mix of upper+lower
        if (
            _RPCID_RE_LEN[0] <= len(s) <= _RPCID_RE_LEN[1]
            and s.isalnum()
            and any(c.isupper() for c in s)
            and any(c.islower() for c in s)
            and s not in self._known_rpcids
        ):
            result.new_rpcids.append(s)

        # API method names
        if any(s.startswith(p) for p in _METHOD_PREFIXES) and len(s) > 6:
            # Filter out common non-API strings
            if not any(x in s for x in (" ", ".", "-", "/", "<", ">")):
                result.new_methods.append(s)

        # Endpoints / URLs
        if s.startswith("https://") or s.startswith("http://"):
            if any(d in s for d in (
                "google.com", "googleapis.com", "clients6.google.com", "gstatic.com"
            )):
                result.new_endpoints.append(s)

        # Google internal service namespaces
        if s.startswith("google.internal.") or s.startswith("google.ai."):
            result.new_service_names.append(s)

        # General API strings worth noting
        if any(kw in s for kw in ("rpcid", "f.req", "batchexecute", "wrb.fr",
                                   "SAPISIDHASH", "$rpc", "grpc-status")):
            result.all_api_strings.append(s)

    # ──── Convenience: capture + diff in one call ────

    async def capture_and_diff(
        self,
        session: CDPSession,
        before: HeapSnapshot,
        label: str = "after",
    ) -> Tuple[HeapSnapshot, HeapDiff]:
        """Capture a new snapshot and diff against `before`. Returns (after, diff)."""
        after = await self.capture(session, label=label)
        diff = self.diff(before, after)
        return after, diff

    # ──── Load from file ────

    @staticmethod
    def load_from_file(path: Path, label: str = "") -> HeapSnapshot:
        """Load a previously saved heap snapshot from disk."""
        raw = path.read_text(encoding="utf-8")
        return HeapSnapshot(raw=raw, label=label or path.stem)


# ──── Module-level singleton ────
_differ: Optional[HeapDiffer] = None


def get_differ(known_rpcids: Optional[Set[str]] = None) -> HeapDiffer:
    global _differ
    if _differ is None:
        from scripts.argus.config import NLM_RPCIDS, GEMINI_RPCIDS
        all_known = set(NLM_RPCIDS) | set(GEMINI_RPCIDS)
        if known_rpcids:
            all_known |= known_rpcids
        _differ = HeapDiffer(known_rpcids=all_known)
    return _differ
