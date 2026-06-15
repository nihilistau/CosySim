"""
Oracle Error Aggregator — Fingerprint, Group, Count, Surface
=============================================================

Groups similar errors by stripping variable parts (IDs, numbers, paths)
from messages to create stable fingerprints. Counts occurrences, tracks
first/last seen, and detects error rate spikes.

This is the brain behind "hey! problem here!" — it turns 500 individual
log lines into "LMStudio auth failed: 47 times in last 5min, affecting
phone + lounge + tavern, started at 14:32."

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Hardening: bounded bucket store (LRU size cap so a
                            flood of unique fingerprints can't grow memory
                            without bound), throttled error-rate alert hook
                            (fires once when rate exceeds a configurable
                            threshold, then re-arms after cooldown), all caps
                            configurable via get_config() with safe defaults.
    v1.49.4 [2026-03-22] — Initial Oracle error aggregation system

CONNECTS: CosyLog handler (on ERROR+), Oracle dashboard, diagnose.py, get_config
CALLED BY: CosyLogHandler.emit(), Oracle API routes
EMITS: error snapshots, rate alerts (via registered alert hooks)
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# v1.60.0 [2026-06-13] — Tunable defaults; overridable via get_config().
#   observability.error_aggregator.max_buckets       — LRU size cap on buckets
#   observability.error_aggregator.alert_threshold   — errors/window to alert
#   observability.error_aggregator.alert_window_sec  — rate window (seconds)
#   observability.error_aggregator.alert_cooldown_sec— re-arm cooldown after alert
_DEFAULT_MAX_BUCKETS = 2000
_DEFAULT_ALERT_THRESHOLD = 100
_DEFAULT_ALERT_WINDOW_SEC = 300
_DEFAULT_ALERT_COOLDOWN_SEC = 300


def _cfg(path: str, default: Any) -> Any:
    """Read a config value, tolerating a missing/unloadable config layer.

    Args:
        path: Dot-notation config path.
        default: Fallback when config is unavailable or the key is unset.

    Returns:
        The configured value or ``default``.
    """
    try:
        from engine.config import get_config

        val = get_config().get(path, default)
        return default if val is None else val
    except Exception:
        # Config not available (e.g. early import, hermetic test) — use default.
        return default


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

    def __init__(
        self,
        max_buckets: Optional[int] = None,
        alert_threshold: Optional[int] = None,
        alert_window_sec: Optional[int] = None,
        alert_cooldown_sec: Optional[float] = None,
    ) -> None:
        """Construct the aggregator.

        Args:
            max_buckets: Hard cap on retained fingerprint buckets (LRU eviction
                of the least-recently-seen bucket past this). Defaults to config
                ``observability.error_aggregator.max_buckets`` or 2000.
            alert_threshold: Error count within ``alert_window_sec`` that trips a
                high-visibility alert. Defaults to config or 100.
            alert_window_sec: Sliding window (seconds) for the rate alert.
            alert_cooldown_sec: Minimum spacing between alerts (throttle), so a
                sustained flood fires once, not on every ingest.
        """
        self._lock = threading.Lock()
        # v1.60.0 — OrderedDict gives O(1) LRU: move_to_end on touch, popitem(last=False)
        # to evict the least-recently-seen bucket once the size cap is exceeded.
        self._buckets: "OrderedDict[str, ErrorBucket]" = OrderedDict()
        self._total_count: int = 0
        self._evicted_count: int = 0
        self._start_time: float = time.time()

        # ── Bounded growth (audit fix: flood of unique fingerprints) ──
        self._max_buckets: int = int(
            max_buckets if max_buckets is not None
            else _cfg("observability.error_aggregator.max_buckets", _DEFAULT_MAX_BUCKETS)
        )

        # ── Error-rate alerting (audit fix: no rate alerting) ──
        self._alert_threshold: int = int(
            alert_threshold if alert_threshold is not None
            else _cfg("observability.error_aggregator.alert_threshold", _DEFAULT_ALERT_THRESHOLD)
        )
        self._alert_window_sec: int = int(
            alert_window_sec if alert_window_sec is not None
            else _cfg("observability.error_aggregator.alert_window_sec", _DEFAULT_ALERT_WINDOW_SEC)
        )
        self._alert_cooldown_sec: float = float(
            alert_cooldown_sec if alert_cooldown_sec is not None
            else _cfg("observability.error_aggregator.alert_cooldown_sec", _DEFAULT_ALERT_COOLDOWN_SEC)
        )
        self._alert_hooks: List[Callable[[Dict[str, Any]], None]] = []
        self._last_alert_ts: float = 0.0
        self._alert_count: int = 0

    # ──── Alert hook registration ────────────────────────────────────
    # CONNECTS: oracle._OracleHandler (default high-visibility logging hook)
    # CALLED BY: ensure_initialized(), Oracle dashboard, tests
    # EMITS: throttled alert dicts to every registered hook

    def register_alert_hook(self, fn: Callable[[Dict[str, Any]], None]) -> None:
        """Register a hook fired (throttled) when the error rate is exceeded.

        The hook receives a dict: ``rate``, ``threshold``, ``window_seconds``,
        ``unique_fingerprints``, ``top_errors``, ``timestamp``, ``alert_count``.

        Args:
            fn: Callable invoked on each (throttled) rate-exceeded event.
        """
        with self._lock:
            if fn not in self._alert_hooks:
                self._alert_hooks.append(fn)

    def unregister_alert_hook(self, fn: Callable[[Dict[str, Any]], None]) -> None:
        """Remove a previously registered alert hook."""
        with self._lock:
            if fn in self._alert_hooks:
                self._alert_hooks.remove(fn)

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
        fire_alert_payload: Optional[Dict[str, Any]] = None

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

            # v1.60.0 — LRU touch: mark this fingerprint most-recently-seen so
            # eviction always drops the stalest bucket, never a hot one.
            self._buckets.move_to_end(fp, last=True)

            # v1.60.0 — Bounded growth: evict least-recently-seen buckets when
            # the unique-fingerprint count blows past the cap. This is the audit
            # fix for unbounded memory under high-cardinality error storms.
            while len(self._buckets) > self._max_buckets:
                self._buckets.popitem(last=False)
                self._evicted_count += 1

            # v1.60.0 — Evaluate the rate alert while holding the lock (cheap),
            # but DISPATCH hooks outside the lock to stay non-blocking.
            fire_alert_payload = self._maybe_build_alert_locked(now)

        if fire_alert_payload is not None:
            self._dispatch_alert(fire_alert_payload)

        return fp

    # ──── Rate alerting (internal) ───────────────────────────────────

    def _maybe_build_alert_locked(self, now: float) -> Optional[Dict[str, Any]]:
        """Return an alert payload if the rate is tripped and re-armed.

        MUST be called while holding ``self._lock``. Does not dispatch — the
        caller dispatches outside the lock so a slow hook can't stall ingest.

        Args:
            now: Current epoch time.

        Returns:
            Alert payload dict, or ``None`` if not tripping / still cooling down.
        """
        if self._alert_threshold <= 0:
            return None
        # Throttle: stay quiet until the cooldown since the last alert elapses.
        if (now - self._last_alert_ts) < self._alert_cooldown_sec:
            return None

        cutoff = now - self._alert_window_sec
        recent_total = 0
        active_fps = 0
        for b in self._buckets.values():
            hits = sum(1 for ts in b._recent_timestamps if ts > cutoff)
            if hits:
                active_fps += 1
                recent_total += hits

        if recent_total < self._alert_threshold:
            return None

        self._last_alert_ts = now
        self._alert_count += 1
        minutes = max(self._alert_window_sec / 60, 1)
        top = sorted(self._buckets.values(), key=lambda b: b.count, reverse=True)[:5]
        return {
            "rate": recent_total,
            "rate_per_min": round(recent_total / minutes, 2),
            "threshold": self._alert_threshold,
            "window_seconds": self._alert_window_sec,
            "unique_fingerprints": active_fps,
            "alert_count": self._alert_count,
            "timestamp": now,
            "top_errors": [
                {
                    "fingerprint": b.fingerprint,
                    "module": b.module,
                    "count": b.count,
                    "sample_message": b.sample_message[:200],
                }
                for b in top
            ],
        }

    def _dispatch_alert(self, payload: Dict[str, Any]) -> None:
        """Fire every registered alert hook; never let a hook crash ingest.

        Args:
            payload: The alert payload from :meth:`_maybe_build_alert_locked`.
        """
        with self._lock:
            hooks = list(self._alert_hooks)
        for hook in hooks:
            try:
                hook(payload)
            except Exception as exc:
                # v1.60.0 — Surface (don't swallow) a misbehaving alert hook.
                logger.debug(
                    "[ErrorAggregator] Alert hook raised (operation=alert_dispatch): %s",
                    exc,
                )

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
            evicted = self._evicted_count
            max_buckets = self._max_buckets
            alert_count = self._alert_count
            alert_threshold = self._alert_threshold
        return {
            "total_unique": total_unique,
            "total_count": total_count,
            "top_errors": top,
            "error_rate": rate,
            "new_in_last_hour": len(new_1h),
            "uptime_seconds": round(time.time() - self._start_time, 1),
            # v1.60.0 — Hardening telemetry: bucket pressure + alert activity.
            "buckets_evicted": evicted,
            "max_buckets": max_buckets,
            "alerts_fired": alert_count,
            "alert_threshold": alert_threshold,
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
