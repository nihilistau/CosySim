"""
Oracle Error Aggregator — Fingerprint, Group, Count, Surface
=============================================================

Groups similar errors by stripping variable parts (IDs, numbers, paths)
from messages to create stable fingerprints. Counts occurrences, tracks
first/last seen, and detects error rate spikes.

This is the brain behind "hey! problem here!" — it turns 500 individual
log lines into "LMStudio auth failed: 47 times in last 5min, affecting
phone + lounge + tavern, started at 14:32."

Version: v1.49.4 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.4 [2026-03-22] — Initial Oracle error aggregation system

CONNECTS: CosyLog handler (on ERROR+), Oracle dashboard, diagnose.py
CALLED BY: CosyLogHandler.emit(), Oracle API routes
EMITS: error snapshots, rate alerts
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set


# ──── Fingerprinting ─────────────────────────────────────────────────────────

def _fingerprint(error_type: str, module: str, message: str) -> str:
    """Normalize a log message to a stable fingerprint.

    Strips numbers, UUIDs, timestamps, file paths, and hex strings so that
    ``"LMStudio embed HTTP 401 on /v1/embeddings"`` and
    ``"LMStudio embed HTTP 403 on /v1/embeddings"`` collapse to the same bucket.

    Args:
        error_type: Exception class name or empty string.
        module: Logger name (e.g. 'engine.lmstudio.lms_client').
        message: The log message text.

    Returns:
        12-char hex fingerprint.
    """
    pattern = message
    # Strip UUIDs (8-4-4-4-12 and bare hex sequences >= 8 chars)
    pattern = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<UUID>", pattern, flags=re.I)
    pattern = re.sub(r"\b[0-9a-f]{8,}\b", "<HEX>", pattern, flags=re.I)
    # Strip numbers
    pattern = re.sub(r"\b\d+\.?\d*\b", "<N>", pattern)
    # Strip Windows/Unix paths
    pattern = re.sub(r"[A-Z]:\\[^\s,)]+", "<PATH>", pattern)
    pattern = re.sub(r"/[^\s,)]*(?:/[^\s,)]+)+", "<PATH>", pattern)
    # Strip quoted strings (preserve structure)
    pattern = re.sub(r"'[^']{20,}'", "'<STR>'", pattern)
    pattern = re.sub(r'"[^"]{20,}"', '"<STR>"', pattern)

    key = f"{error_type}::{module}::{pattern}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ──── Data structures ────────────────────────────────────────────────────────

@dataclass
class ErrorBucket:
    """A group of similar errors identified by the same fingerprint."""
    fingerprint: str
    error_type: str
    module: str
    message_template: str          # Fingerprinted message pattern
    sample_message: str = ""       # Most recent actual message
    count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    affected_scenes: Set[str] = field(default_factory=set)
    sample_trace_ids: Deque[str] = field(default_factory=lambda: deque(maxlen=5))
    # Rate tracking: timestamps of recent occurrences (last 5 minutes)
    _recent_timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=500))

    def to_dict(self) -> Dict[str, Any]:
        """Export for API responses."""
        now = time.time()
        recent_count = sum(1 for ts in self._recent_timestamps if now - ts < 300)
        return {
            "fingerprint": self.fingerprint,
            "error_type": self.error_type,
            "module": self.module,
            "message_template": self.message_template,
            "sample_message": self.sample_message[:300],
            "count": self.count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "age_seconds": round(now - self.first_seen, 1),
            "affected_scenes": sorted(self.affected_scenes),
            "recent_5min": recent_count,
            "rate_per_min": round(recent_count / 5, 2),
            "trace_ids": list(self.sample_trace_ids),
        }


# ──── ErrorAggregator Singleton ──────────────────────────────────────────────

class ErrorAggregator:
    """Thread-safe error aggregation with fingerprinting and rate detection.

    CONNECTS: CosyLogHandler, Oracle API, diagnose.py
    CALLED BY: CosyLogHandler.emit() on every ERROR+ log event
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: Dict[str, ErrorBucket] = {}
        self._total_count: int = 0
        self._start_time: float = time.time()

    def ingest(
        self,
        message: str,
        module: str = "",
        scene: str = "",
        error_type: str = "",
        trace_id: str = "",
        level: str = "ERROR",
    ) -> str:
        """Ingest an error event — fingerprint, group, count.

        Args:
            message: The log message.
            module: Logger name (e.g. 'engine.mcp.comms_framework').
            scene: Scene ID if available.
            error_type: Exception class name.
            trace_id: Correlation trace ID.
            level: Log level string.

        Returns:
            The fingerprint string for this error.
        """
        fp = _fingerprint(error_type, module, message)
        now = time.time()

        with self._lock:
            self._total_count += 1

            if fp not in self._buckets:
                # Fingerprint the message for the template
                template = message
                template = re.sub(r"\b\d+\.?\d*\b", "<N>", template)
                template = re.sub(r"[0-9a-f]{8,}", "<ID>", template, flags=re.I)

                self._buckets[fp] = ErrorBucket(
                    fingerprint=fp,
                    error_type=error_type,
                    module=module,
                    message_template=template[:200],
                    sample_message=message[:300],
                    count=1,
                    first_seen=now,
                    last_seen=now,
                )
            else:
                bucket = self._buckets[fp]
                bucket.count += 1
                bucket.last_seen = now
                bucket.sample_message = message[:300]

            bucket = self._buckets[fp]
            if scene:
                bucket.affected_scenes.add(scene)
            if trace_id:
                bucket.sample_trace_ids.append(trace_id)
            bucket._recent_timestamps.append(now)

        return fp

    # ──── Query API ──────────────────────────────────────────────────

    def get_top_errors(self, n: int = 20) -> List[Dict[str, Any]]:
        """Return top N errors sorted by count descending."""
        with self._lock:
            sorted_buckets = sorted(
                self._buckets.values(),
                key=lambda b: b.count,
                reverse=True,
            )
            return [b.to_dict() for b in sorted_buckets[:n]]

    def get_error_rate(self, window_seconds: int = 300) -> Dict[str, Any]:
        """Return error rate over the time window.

        Returns:
            Dict with total, rate_per_min, unique_fingerprints, window_seconds.
        """
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            recent_total = sum(
                sum(1 for ts in b._recent_timestamps if ts > cutoff)
                for b in self._buckets.values()
            )
            active_fps = sum(
                1 for b in self._buckets.values()
                if any(ts > cutoff for ts in b._recent_timestamps)
            )
        minutes = window_seconds / 60
        return {
            "total": recent_total,
            "rate_per_min": round(recent_total / max(minutes, 1), 2),
            "unique_fingerprints": active_fps,
            "window_seconds": window_seconds,
        }

    def get_new_errors(self, since_ts: float) -> List[Dict[str, Any]]:
        """Return errors first seen after the given timestamp."""
        with self._lock:
            return [
                b.to_dict() for b in self._buckets.values()
                if b.first_seen > since_ts
            ]

    def snapshot(self) -> Dict[str, Any]:
        """Full aggregator state for dashboard consumption."""
        top = self.get_top_errors(10)
        rate = self.get_error_rate()
        new_1h = self.get_new_errors(time.time() - 3600)
        with self._lock:
            total_unique = len(self._buckets)
            total_count = self._total_count
        return {
            "total_unique": total_unique,
            "total_count": total_count,
            "top_errors": top,
            "error_rate": rate,
            "new_in_last_hour": len(new_1h),
            "uptime_seconds": round(time.time() - self._start_time, 1),
        }

    def clear_old(self, hours: float = 24) -> int:
        """Evict buckets last seen before the cutoff. Returns count evicted."""
        cutoff = time.time() - (hours * 3600)
        with self._lock:
            old_keys = [k for k, b in self._buckets.items() if b.last_seen < cutoff]
            for k in old_keys:
                del self._buckets[k]
            return len(old_keys)


# ──── Singleton ──────────────────────────────────────────────────────────────

_aggregator: Optional[ErrorAggregator] = None
_agg_lock = threading.Lock()


def get_error_aggregator() -> ErrorAggregator:
    """Get or create the singleton ErrorAggregator."""
    global _aggregator
    if _aggregator is None:
        with _agg_lock:
            if _aggregator is None:
                _aggregator = ErrorAggregator()
    return _aggregator
