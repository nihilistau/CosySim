"""
CorrelationEngine — Cross-reference metrics between processes, packs, services.

Computes Pearson and Spearman correlations between metric time-series pairs,
generates correlation matrices, and discovers automatic correlations across
the entire metric space.

Usage::

    from engine.observability.correlation_engine import get_correlation_engine
    engine = get_correlation_engine()

    # Feed metrics (same interface as AlertEngine/AnomalyDetector)
    engine.feed("system", "cpu_pct", 45.2)
    engine.feed("pipeline", "latency_ms", 230.0)

    # Compute correlation between two metrics
    r = engine.correlate("system.cpu_pct", "pipeline.latency_ms")

    # Discover all strong correlations
    matrix = engine.correlation_matrix(min_r=0.5)

    # Cross-reference two domains
    xref = engine.cross_reference("system", "pipeline")
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional["CorrelationEngine"] = None
_lock = threading.Lock()


def get_correlation_engine() -> "CorrelationEngine":
    """Get or create the singleton CorrelationEngine."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = CorrelationEngine()
    return _instance


# ── Data Models ─────────────────────────────────────────────────────────


@dataclass
class CorrelationResult:
    """Result of a pairwise correlation computation."""
    metric_a: str
    metric_b: str
    pearson_r: float
    spearman_r: float
    sample_count: int
    p_value_approx: float
    lag_seconds: float = 0.0
    strength: str = ""
    direction: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        r = max(abs(self.pearson_r), abs(self.spearman_r))
        if r >= 0.8:
            self.strength = "strong"
        elif r >= 0.5:
            self.strength = "moderate"
        elif r >= 0.3:
            self.strength = "weak"
        else:
            self.strength = "negligible"

        best_r = self.pearson_r if abs(self.pearson_r) >= abs(self.spearman_r) else self.spearman_r
        self.direction = "positive" if best_r >= 0 else "negative"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_a": self.metric_a,
            "metric_b": self.metric_b,
            "pearson_r": round(self.pearson_r, 4),
            "spearman_r": round(self.spearman_r, 4),
            "sample_count": self.sample_count,
            "p_value_approx": round(self.p_value_approx, 6),
            "lag_seconds": round(self.lag_seconds, 1),
            "strength": self.strength,
            "direction": self.direction,
            "ts": self.timestamp,
        }


# ── DB Schema ───────────────────────────────────────────────────────────

_CORRELATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS metric_correlations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    metric_a TEXT NOT NULL,
    metric_b TEXT NOT NULL,
    pearson_r REAL NOT NULL,
    spearman_r REAL NOT NULL,
    sample_count INTEGER NOT NULL,
    p_value_approx REAL DEFAULT 1.0,
    lag_seconds REAL DEFAULT 0.0,
    strength TEXT DEFAULT 'negligible',
    direction TEXT DEFAULT 'positive'
);

CREATE INDEX IF NOT EXISTS idx_mc_ts ON metric_correlations(ts);
CREATE INDEX IF NOT EXISTS idx_mc_metrics ON metric_correlations(metric_a, metric_b, ts);
CREATE INDEX IF NOT EXISTS idx_mc_strength ON metric_correlations(strength, ts);
"""


# ── CorrelationEngine ───────────────────────────────────────────────────


class CorrelationEngine:
    """
    Cross-references metrics between processes, packs, and services
    using Pearson and Spearman correlation coefficients.

    Thread-safe singleton. Shares the metric sample format with
    AlertEngine and AnomalyDetector for easy integration.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        default_window: float = 300.0,
        min_samples: int = 20,
    ):
        self._lock = threading.Lock()
        self._default_window = default_window
        self._min_samples = min_samples

        # Metric sample buffers: "node.metric" → deque of (ts, value)
        self._samples: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))

        # Cached correlation results
        self._cache: Dict[Tuple[str, str], CorrelationResult] = {}
        self._cache_ttl: float = 30.0

        # Correlation history (ring buffer)
        self._history: deque = deque(maxlen=500)

        # DB
        self._db_path = db_path
        self._db_local = threading.local()
        self._init_db()

    def _get_db(self):
        """Thread-local DB connection."""
        import sqlite3
        if not hasattr(self._db_local, "conn") or self._db_local.conn is None:
            if self._db_path:
                path = self._db_path
            else:
                from engine.paths import DATA_DIR
                path = str(DATA_DIR / "metrics.db")
            self._db_local.conn = sqlite3.connect(path, timeout=5)
            self._db_local.conn.row_factory = sqlite3.Row
            self._db_local.conn.execute("PRAGMA journal_mode=WAL")
            self._db_local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._db_local.conn

    def _init_db(self) -> None:
        """Create correlation tables."""
        try:
            conn = self._get_db()
            conn.executescript(_CORRELATION_SCHEMA)
            conn.commit()
        except Exception as exc:
            logger.warning("CorrelationEngine DB init failed: %s", exc)

    # ── Feeding ─────────────────────────────────────────────────────

    def feed(self, node: str, metric: str, value: float) -> None:
        """Feed a metric sample.

        Args:
            node: Metric node (e.g., "system", "pipeline").
            metric: Metric name (e.g., "cpu_pct", "latency_ms").
            value: Metric value.
        """
        key = f"{node}.{metric}"
        self._samples[key].append((time.time(), value))

    # ── Correlation Computation ─────────────────────────────────────

    def correlate(
        self,
        metric_a: str,
        metric_b: str,
        window_s: Optional[float] = None,
    ) -> Optional[CorrelationResult]:
        """Compute Pearson and Spearman correlation between two metrics.

        Args:
            metric_a: First metric key (e.g., "system.cpu_pct").
            metric_b: Second metric key (e.g., "pipeline.latency_ms").
            window_s: Time window in seconds (default: default_window).

        Returns:
            CorrelationResult or None if insufficient data.
        """
        window = window_s or self._default_window
        now = time.time()

        # Check cache
        cache_key = (metric_a, metric_b) if metric_a < metric_b else (metric_b, metric_a)
        cached = self._cache.get(cache_key)
        if cached and now - cached.timestamp < self._cache_ttl:
            return cached

        # Align time-series by nearest timestamp
        a_samples = self._samples.get(metric_a)
        b_samples = self._samples.get(metric_b)

        if not a_samples or not b_samples:
            return None

        cutoff = now - window
        a_vals = [(ts, v) for ts, v in a_samples if ts >= cutoff]
        b_vals = [(ts, v) for ts, v in b_samples if ts >= cutoff]

        if len(a_vals) < self._min_samples or len(b_vals) < self._min_samples:
            return None

        # Align by nearest-timestamp pairing
        paired_a, paired_b = self._align_series(a_vals, b_vals)
        if len(paired_a) < self._min_samples:
            return None

        pearson = self._pearson(paired_a, paired_b)
        spearman = self._spearman(paired_a, paired_b)
        p_value = self._approx_p_value(pearson, len(paired_a))

        result = CorrelationResult(
            metric_a=metric_a,
            metric_b=metric_b,
            pearson_r=pearson,
            spearman_r=spearman,
            sample_count=len(paired_a),
            p_value_approx=p_value,
            timestamp=now,
        )

        self._cache[cache_key] = result
        return result

    def correlation_matrix(
        self,
        min_r: float = 0.3,
        window_s: Optional[float] = None,
        metrics: Optional[List[str]] = None,
    ) -> List[CorrelationResult]:
        """Compute correlations between all metric pairs.

        Args:
            min_r: Minimum |r| to include in results.
            window_s: Time window in seconds.
            metrics: Optional list of specific metrics to compare.

        Returns:
            List of CorrelationResults sorted by |r| descending.
        """
        now = time.time()
        keys = metrics or list(self._samples.keys())

        # Only include metrics with sufficient samples
        window = window_s or self._default_window
        cutoff = now - window
        valid_keys = [
            k for k in keys
            if sum(1 for ts, _ in self._samples.get(k, []) if ts >= cutoff) >= self._min_samples
        ]

        results: List[CorrelationResult] = []
        seen: set = set()

        for i, a in enumerate(valid_keys):
            for b in valid_keys[i + 1:]:
                pair = (a, b) if a < b else (b, a)
                if pair in seen:
                    continue
                seen.add(pair)

                result = self.correlate(a, b, window_s=window)
                if result and max(abs(result.pearson_r), abs(result.spearman_r)) >= min_r:
                    results.append(result)

        results.sort(key=lambda r: max(abs(r.pearson_r), abs(r.spearman_r)), reverse=True)

        # Persist strong correlations
        for r in results:
            if r.strength in ("strong", "moderate"):
                self._persist_correlation(r)
                self._history.append(r)

        return results

    def cross_reference(
        self,
        domain_a: str,
        domain_b: str,
        window_s: Optional[float] = None,
    ) -> List[CorrelationResult]:
        """Find correlations between two metric domains.

        Compares all metrics from domain_a (e.g., "system") against
        all metrics from domain_b (e.g., "pipeline").

        Args:
            domain_a: First domain prefix (e.g., "system").
            domain_b: Second domain prefix (e.g., "pipeline").
            window_s: Time window in seconds.

        Returns:
            List of significant CorrelationResults.
        """
        a_keys = [k for k in self._samples if k.startswith(f"{domain_a}.")]
        b_keys = [k for k in self._samples if k.startswith(f"{domain_b}.")]

        results: List[CorrelationResult] = []
        for a in a_keys:
            for b in b_keys:
                result = self.correlate(a, b, window_s=window_s)
                if result and result.strength in ("strong", "moderate", "weak"):
                    results.append(result)

        results.sort(key=lambda r: max(abs(r.pearson_r), abs(r.spearman_r)), reverse=True)
        return results

    def discover_correlations(
        self,
        min_r: float = 0.5,
        window_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Auto-discover strong correlations across all metrics.

        Args:
            min_r: Minimum |r| threshold.
            window_s: Time window.

        Returns:
            Dict with strong, moderate, and total counts plus correlation list.
        """
        all_corrs = self.correlation_matrix(min_r=min_r, window_s=window_s)

        strong = [c for c in all_corrs if c.strength == "strong"]
        moderate = [c for c in all_corrs if c.strength == "moderate"]

        return {
            "total_pairs_checked": len(self._samples) * (len(self._samples) - 1) // 2,
            "significant_correlations": len(all_corrs),
            "strong": len(strong),
            "moderate": len(moderate),
            "correlations": [c.to_dict() for c in all_corrs],
        }

    # ── Query API ───────────────────────────────────────────────────

    def tracked_metrics(self) -> List[str]:
        """Get all tracked metric keys."""
        return list(self._samples.keys())

    def recent_correlations(self, n: int = 20) -> List[Dict[str, Any]]:
        """Get recent correlation computations.

        Args:
            n: Number of results.

        Returns:
            List of correlation dicts.
        """
        return [c.to_dict() for c in list(self._history)[-n:]]

    def strongest_correlations(
        self,
        hours: float = 24.0,
        n: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get strongest correlations from persistent history.

        Args:
            hours: Lookback window.
            n: Number of results.

        Returns:
            List of correlation dicts.
        """
        cutoff = time.time() - (hours * 3600)
        try:
            conn = self._get_db()
            cur = conn.execute(
                "SELECT * FROM metric_correlations WHERE ts >= ? "
                "ORDER BY ABS(pearson_r) DESC LIMIT ?",
                (cutoff, n),
            )
            return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.debug("Strongest correlations query failed: %s", exc)
            return []

    def snapshot(self) -> Dict[str, Any]:
        """Full correlation engine snapshot.

        Returns:
            Dict with tracked metrics, cache size, and discovery summary.
        """
        return {
            "tracked_metrics": len(self._samples),
            "cache_size": len(self._cache),
            "history_size": len(self._history),
            "metric_keys": list(self._samples.keys()),
        }

    # ── Math Helpers ────────────────────────────────────────────────

    @staticmethod
    def _align_series(
        a: List[Tuple[float, float]],
        b: List[Tuple[float, float]],
        max_gap_s: float = 5.0,
    ) -> Tuple[List[float], List[float]]:
        """Align two time-series by nearest-timestamp pairing.

        For each sample in the shorter series, finds the nearest sample
        in the longer series within max_gap_s seconds.

        Args:
            a: Time-series A as [(ts, value), ...].
            b: Time-series B as [(ts, value), ...].
            max_gap_s: Maximum allowed time gap for pairing.

        Returns:
            Tuple of (paired_a_values, paired_b_values).
        """
        if len(a) > len(b):
            a, b = b, a
            swapped = True
        else:
            swapped = False

        b_idx = 0
        paired_a = []
        paired_b = []

        for ts_a, val_a in a:
            # Advance b_idx to nearest timestamp
            while b_idx < len(b) - 1 and abs(b[b_idx + 1][0] - ts_a) < abs(b[b_idx][0] - ts_a):
                b_idx += 1

            if abs(b[b_idx][0] - ts_a) <= max_gap_s:
                if swapped:
                    paired_a.append(b[b_idx][1])
                    paired_b.append(val_a)
                else:
                    paired_a.append(val_a)
                    paired_b.append(b[b_idx][1])

        return paired_a, paired_b

    @staticmethod
    def _pearson(x: List[float], y: List[float]) -> float:
        """Compute Pearson correlation coefficient.

        Args:
            x: First variable values.
            y: Second variable values.

        Returns:
            Pearson r in [-1, 1].
        """
        n = len(x)
        if n < 2:
            return 0.0

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        sum_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        sum_x2 = sum((xi - mean_x) ** 2 for xi in x)
        sum_y2 = sum((yi - mean_y) ** 2 for yi in y)

        denom = math.sqrt(sum_x2 * sum_y2)
        if denom == 0:
            return 0.0

        return sum_xy / denom

    @staticmethod
    def _spearman(x: List[float], y: List[float]) -> float:
        """Compute Spearman rank correlation coefficient.

        Args:
            x: First variable values.
            y: Second variable values.

        Returns:
            Spearman ρ in [-1, 1].
        """
        n = len(x)
        if n < 2:
            return 0.0

        def rank(vals: List[float]) -> List[float]:
            sorted_vals = sorted(enumerate(vals), key=lambda t: t[1])
            ranks = [0.0] * n
            i = 0
            while i < n:
                j = i
                while j < n - 1 and sorted_vals[j + 1][1] == sorted_vals[j][1]:
                    j += 1
                avg_rank = (i + j) / 2.0 + 1
                for k in range(i, j + 1):
                    ranks[sorted_vals[k][0]] = avg_rank
                i = j + 1
            return ranks

        rx = rank(x)
        ry = rank(y)

        # Pearson on ranks
        return CorrelationEngine._pearson(rx, ry)

    @staticmethod
    def _approx_p_value(r: float, n: int) -> float:
        """Approximate p-value for Pearson correlation using t-distribution.

        Uses a rough approximation suitable for monitoring (not publication).

        Args:
            r: Pearson r value.
            n: Sample count.

        Returns:
            Approximate two-tailed p-value.
        """
        if n <= 2 or abs(r) >= 1.0:
            return 1.0

        t = r * math.sqrt((n - 2) / (1 - r * r))
        # Approximate: p ≈ 2 * exp(-0.717 * t - 0.416 * t^2) for |t| < 6
        abs_t = abs(t)
        if abs_t > 6:
            return 0.0001
        p = 2 * math.exp(-0.717 * abs_t - 0.416 * abs_t * abs_t)
        return min(1.0, max(0.0, p))

    # ── Persistence ─────────────────────────────────────────────────

    def _persist_correlation(self, result: CorrelationResult) -> None:
        """Write correlation result to SQLite."""
        try:
            conn = self._get_db()
            conn.execute(
                "INSERT INTO metric_correlations "
                "(ts, metric_a, metric_b, pearson_r, spearman_r, "
                "sample_count, p_value_approx, lag_seconds, strength, direction) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.timestamp, result.metric_a, result.metric_b,
                    result.pearson_r, result.spearman_r, result.sample_count,
                    result.p_value_approx, result.lag_seconds,
                    result.strength, result.direction,
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.debug("Failed to persist correlation: %s", exc)

    def prune(self, max_age_hours: float = 168.0) -> int:
        """Delete correlation records older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours (default 7 days).

        Returns:
            Number of rows deleted.
        """
        cutoff = time.time() - (max_age_hours * 3600)
        try:
            conn = self._get_db()
            cur = conn.execute("DELETE FROM metric_correlations WHERE ts < ?", (cutoff,))
            conn.commit()
            return cur.rowcount
        except Exception as exc:
            logger.debug("Correlation prune failed: %s", exc)
            return 0
