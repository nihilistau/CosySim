"""
TrendPredictor — Forecast resource usage and detect degradation.

Uses linear regression on recent metric windows to predict future values,
detect upward/downward trends, and generate capacity planning alerts.

Usage::

    from engine.observability.trend_predictor import get_trend_predictor
    predictor = get_trend_predictor()

    # Feed metrics (same interface as other subsystems)
    predictor.feed("system", "cpu_pct", 45.2)
    predictor.feed("gpu", "vram_mb", 8900)

    # Get trend for a metric
    trend = predictor.get_trend("system.cpu_pct")
    # → {"slope": 0.5, "direction": "rising", "predicted_1h": 75.0, ...}

    # Get all active trends
    all_trends = predictor.all_trends()

    # Check capacity warnings
    warnings = predictor.capacity_warnings(horizon_minutes=60)
"""
from __future__ import annotations

import logging
import math
import sqlite3
import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional["TrendPredictor"] = None
_lock = threading.Lock()


def get_trend_predictor(**kwargs: Any) -> TrendPredictor:
    """Get or create the singleton TrendPredictor.

    Args:
        **kwargs: Forwarded to ``TrendPredictor.__init__`` on first call.

    Returns:
        The singleton TrendPredictor instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = TrendPredictor(**kwargs)
    return _instance


# ── Data Models ─────────────────────────────────────────────────────────


class TrendDirection(Enum):
    """Direction classification for a metric trend."""
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"
    VOLATILE = "volatile"


class TrendSeverity(Enum):
    """Severity of a detected trend — how urgently it needs attention."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TrendResult:
    """Full trend analysis result for a single metric.

    Attributes:
        metric_key: Node-dot-metric identifier (e.g. ``system.cpu_pct``).
        slope: Rate of change in units per second.
        direction: Classified direction (rising, falling, stable, volatile).
        r_squared: Goodness-of-fit of the linear model (0–1).
        predicted_1h: Predicted value one hour from now.
        predicted_4h: Predicted value four hours from now.
        predicted_24h: Predicted value twenty-four hours from now.
        current_value: Most recent observed value.
        min_recent: Minimum value in the analysis window.
        max_recent: Maximum value in the analysis window.
        mean_recent: Mean value in the analysis window.
        sample_count: Number of samples used for the regression.
        severity: Classified severity of the trend.
        ts: Timestamp of the analysis.
    """
    metric_key: str
    slope: float
    direction: TrendDirection
    r_squared: float
    predicted_1h: float
    predicted_4h: float
    predicted_24h: float
    current_value: float
    min_recent: float
    max_recent: float
    mean_recent: float
    sample_count: int
    severity: TrendSeverity
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for JSON / API responses."""
        return {
            "metric_key": self.metric_key,
            "slope": round(self.slope, 8),
            "direction": self.direction.value,
            "r_squared": round(self.r_squared, 4),
            "predicted_1h": round(self.predicted_1h, 2),
            "predicted_4h": round(self.predicted_4h, 2),
            "predicted_24h": round(self.predicted_24h, 2),
            "current_value": round(self.current_value, 2),
            "min_recent": round(self.min_recent, 2),
            "max_recent": round(self.max_recent, 2),
            "mean_recent": round(self.mean_recent, 2),
            "sample_count": self.sample_count,
            "severity": self.severity.value,
            "ts": self.ts,
        }


# ── DB Schema ───────────────────────────────────────────────────────────

_TREND_SCHEMA = """
CREATE TABLE IF NOT EXISTS metric_trends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_key TEXT NOT NULL,
    slope REAL NOT NULL,
    direction TEXT NOT NULL,
    r_squared REAL NOT NULL,
    predicted_1h REAL,
    predicted_4h REAL,
    predicted_24h REAL,
    current_value REAL,
    severity TEXT NOT NULL,
    ts REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mt_key_ts ON metric_trends(metric_key, ts);
CREATE INDEX IF NOT EXISTS idx_mt_severity ON metric_trends(severity, ts);
"""

# ── Default capacity thresholds ─────────────────────────────────────────

_DEFAULT_THRESHOLDS: Dict[str, float] = {
    "cpu_pct": 95.0,
    "ram_pct": 95.0,
    "vram_mb": 11500.0,
    "disk_pct": 95.0,
    "latency_ms": 5000.0,
}

# Metric patterns that indicate higher-is-worse (used for severity)
_UPPER_BOUNDED = {"cpu_pct", "ram_pct", "vram_mb", "disk_pct", "gpu_pct",
                  "latency_ms", "queue_depth", "error_count", "vram_pct",
                  "gpu_temp_c"}


# ── TrendPredictor ──────────────────────────────────────────────────────


class TrendPredictor:
    """Forecasts resource usage and detects degradation trends.

    Maintains per-metric sample buffers, computes linear regression on the
    recent window, classifies trend direction and severity, and generates
    capacity planning warnings.

    Thread-safe.  Shares ``data/metrics.db`` with the rest of the
    observability stack.
    """

    def __init__(
        self,
        db_path: str = "data/metrics.db",
        window_size: int = 300,
        min_samples: int = 10,
        slope_threshold: float = 0.001,
    ) -> None:
        """Initialise the trend predictor.

        Args:
            db_path: Path to the shared SQLite metrics database.
            window_size: Maximum samples kept per metric (ring buffer).
            min_samples: Minimum samples required before computing a trend.
            slope_threshold: Absolute slope below this is classified as stable.
        """
        self._lock = threading.Lock()
        self._db_path = db_path
        self._window_size = window_size
        self._min_samples = min_samples
        self._slope_threshold = slope_threshold

        # Per-metric sample buffers: "node.metric" → deque of (ts, value)
        self._samples: Dict[str, Deque[Tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=self._window_size)
        )

        # Background thread control
        self._running = False
        self._bg_thread: Optional[threading.Thread] = None

        # Thread-local DB connections
        self._db_local = threading.local()
        self._init_db()

        logger.info(
            "TrendPredictor initialised (window=%d, min_samples=%d, threshold=%.4f)",
            window_size, min_samples, slope_threshold,
        )

    # ── DB helpers ──────────────────────────────────────────────────

    def _get_db(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection."""
        if not hasattr(self._db_local, "conn") or self._db_local.conn is None:
            import pathlib
            pathlib.Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db_local.conn = sqlite3.connect(self._db_path, timeout=5)
            self._db_local.conn.row_factory = sqlite3.Row
            self._db_local.conn.execute("PRAGMA journal_mode=WAL")
            self._db_local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._db_local.conn

    def _init_db(self) -> None:
        """Create the metric_trends table if it does not exist."""
        try:
            conn = self._get_db()
            conn.executescript(_TREND_SCHEMA)
            conn.commit()
        except Exception as exc:
            logger.warning("TrendPredictor DB init failed: %s", exc)

    # ── Feeding ─────────────────────────────────────────────────────

    def feed(self, node: str, metric: str, value: float, ts: Optional[float] = None) -> None:
        """Add a metric sample.

        Args:
            node: Metric source node (e.g. ``"system"``, ``"gpu"``).
            metric: Metric name (e.g. ``"cpu_pct"``, ``"vram_mb"``).
            value: Observed numeric value.
            ts: Optional explicit timestamp; defaults to ``time.time()``.
        """
        key = f"{node}.{metric}"
        sample_ts = ts if ts is not None else time.time()
        with self._lock:
            self._samples[key].append((sample_ts, value))

    # ── Linear Regression ───────────────────────────────────────────

    def _compute_regression(
        self, values: List[Tuple[float, float]]
    ) -> Tuple[float, float, float]:
        """Ordinary least-squares linear regression.

        Args:
            values: Sequence of ``(timestamp, value)`` pairs.

        Returns:
            Tuple of ``(slope, intercept, r_squared)``.
        """
        n = len(values)
        if n < 2:
            return 0.0, values[0][1] if values else 0.0, 0.0

        # Use time offsets relative to first sample to avoid float precision issues
        t0 = values[0][0]
        xs = [t - t0 for t, _ in values]
        ys = [v for _, v in values]

        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        sum_x2 = sum(x * x for x in xs)

        denom = n * sum_x2 - sum_x * sum_x
        if abs(denom) < 1e-15:
            return 0.0, sum_y / n, 0.0

        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n

        # R² (coefficient of determination)
        y_mean = sum_y / n
        ss_tot = sum((y - y_mean) ** 2 for y in ys)
        if ss_tot < 1e-15:
            r_squared = 1.0 if abs(slope) < 1e-15 else 0.0
        else:
            ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
            r_squared = max(0.0, 1.0 - ss_res / ss_tot)

        # Adjust intercept back to absolute time reference
        intercept_abs = slope * (-t0) + intercept + slope * t0
        # Actually: predicted(t) = slope*(t - t0) + intercept
        # At absolute time T: value = slope*(T - t0) + intercept
        # We return intercept relative to t0 for prediction use

        return slope, intercept, r_squared

    # ── Classification ──────────────────────────────────────────────

    def _classify_direction(
        self, slope: float, r_squared: float, threshold: float
    ) -> TrendDirection:
        """Classify the trend direction.

        Args:
            slope: Regression slope (units/second).
            r_squared: Goodness of fit.
            threshold: Minimum absolute slope to be non-stable.

        Returns:
            The classified ``TrendDirection``.
        """
        if r_squared < 0.1:
            # Very poor fit — data is noisy / volatile
            if abs(slope) > threshold * 10:
                return TrendDirection.VOLATILE
            return TrendDirection.STABLE

        if abs(slope) < threshold:
            return TrendDirection.STABLE

        return TrendDirection.RISING if slope > 0 else TrendDirection.FALLING

    def _classify_severity(
        self,
        slope: float,
        direction: TrendDirection,
        current_value: float,
        metric_key: str,
    ) -> TrendSeverity:
        """Classify severity based on rate of change and proximity to danger.

        Args:
            slope: Regression slope (units/second).
            direction: Already-classified direction.
            current_value: Most recent observed value.
            metric_key: The ``node.metric`` key, used to look up thresholds.

        Returns:
            The classified ``TrendSeverity``.
        """
        if direction == TrendDirection.STABLE:
            return TrendSeverity.NONE

        # Extract metric name from key for threshold lookup
        metric_name = metric_key.split(".", 1)[1] if "." in metric_key else metric_key
        threshold = _DEFAULT_THRESHOLDS.get(metric_name)

        is_upper_bounded = metric_name in _UPPER_BOUNDED

        if direction == TrendDirection.VOLATILE:
            return TrendSeverity.MEDIUM

        if direction == TrendDirection.RISING and is_upper_bounded and threshold:
            # Rising toward a ceiling — how close and how fast?
            headroom = threshold - current_value
            if headroom <= 0:
                return TrendSeverity.CRITICAL

            # Time to breach at current rate (seconds)
            if slope > 0:
                time_to_breach = headroom / slope
                if time_to_breach < 900:       # <15 min
                    return TrendSeverity.CRITICAL
                if time_to_breach < 3600:      # <1 h
                    return TrendSeverity.HIGH
                if time_to_breach < 14400:     # <4 h
                    return TrendSeverity.MEDIUM
                return TrendSeverity.LOW

        if direction == TrendDirection.FALLING and not is_upper_bounded and threshold:
            # Falling below a floor for metrics where lower is worse
            return TrendSeverity.MEDIUM

        # Generic slope-magnitude heuristic
        abs_slope_per_min = abs(slope) * 60.0
        if abs_slope_per_min > 5.0:
            return TrendSeverity.HIGH
        if abs_slope_per_min > 1.0:
            return TrendSeverity.MEDIUM
        if abs_slope_per_min > 0.1:
            return TrendSeverity.LOW
        return TrendSeverity.NONE

    # ── Trend Computation ───────────────────────────────────────────

    def get_trend(self, metric_key: str) -> Optional[TrendResult]:
        """Compute the current trend for a single metric.

        Args:
            metric_key: Fully qualified key in ``node.metric`` format.

        Returns:
            A ``TrendResult`` if enough samples exist, else ``None``.
        """
        with self._lock:
            buf = self._samples.get(metric_key)
            if not buf or len(buf) < self._min_samples:
                return None
            values = list(buf)

        slope, intercept, r_sq = self._compute_regression(values)
        direction = self._classify_direction(slope, r_sq, self._slope_threshold)

        # Extract statistics from the window
        raw_vals = [v for _, v in values]
        current = raw_vals[-1]
        min_val = min(raw_vals)
        max_val = max(raw_vals)
        mean_val = statistics.mean(raw_vals)

        # Predictions: value = slope * (future_t - t0) + intercept
        t0 = values[0][0]
        now = values[-1][0]
        offset = now - t0

        pred_1h = slope * (offset + 3600) + intercept
        pred_4h = slope * (offset + 14400) + intercept
        pred_24h = slope * (offset + 86400) + intercept

        severity = self._classify_severity(slope, direction, current, metric_key)

        return TrendResult(
            metric_key=metric_key,
            slope=slope,
            direction=direction,
            r_squared=r_sq,
            predicted_1h=pred_1h,
            predicted_4h=pred_4h,
            predicted_24h=pred_24h,
            current_value=current,
            min_recent=min_val,
            max_recent=max_val,
            mean_recent=mean_val,
            sample_count=len(values),
            severity=severity,
        )

    def all_trends(self) -> List[TrendResult]:
        """Compute trends for all metrics with enough samples.

        Returns:
            List of ``TrendResult`` objects, one per qualifying metric.
        """
        with self._lock:
            keys = [
                k for k, buf in self._samples.items()
                if len(buf) >= self._min_samples
            ]

        results: List[TrendResult] = []
        for key in keys:
            trend = self.get_trend(key)
            if trend is not None:
                results.append(trend)
        return results

    # ── Capacity Warnings ───────────────────────────────────────────

    def capacity_warnings(
        self,
        horizon_minutes: int = 60,
        thresholds: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """Check if any metric will breach a threshold within the horizon.

        Args:
            horizon_minutes: How far into the future to project.
            thresholds: Metric-name → ceiling mapping.  Defaults to
                ``_DEFAULT_THRESHOLDS``.

        Returns:
            List of warning dicts for metrics projected to breach.
        """
        effective = dict(_DEFAULT_THRESHOLDS)
        if thresholds:
            effective.update(thresholds)

        horizon_s = horizon_minutes * 60.0
        warnings: List[Dict[str, Any]] = []
        trends = self.all_trends()

        for trend in trends:
            metric_name = (
                trend.metric_key.split(".", 1)[1]
                if "." in trend.metric_key
                else trend.metric_key
            )
            ceiling = effective.get(metric_name)
            if ceiling is None:
                continue

            # Only warn for rising metrics approaching the ceiling
            if trend.direction != TrendDirection.RISING or trend.slope <= 0:
                continue

            headroom = ceiling - trend.current_value
            if headroom <= 0:
                # Already breached
                warnings.append({
                    "metric_key": trend.metric_key,
                    "current_value": round(trend.current_value, 2),
                    "threshold": ceiling,
                    "status": "breached",
                    "time_to_breach_min": 0,
                    "predicted_at_horizon": round(
                        trend.current_value + trend.slope * horizon_s, 2
                    ),
                    "severity": TrendSeverity.CRITICAL.value,
                    "slope_per_min": round(trend.slope * 60, 4),
                })
                continue

            ttb_seconds = headroom / trend.slope
            ttb_minutes = ttb_seconds / 60.0

            if ttb_minutes <= horizon_minutes:
                sev = TrendSeverity.CRITICAL if ttb_minutes < 15 else (
                    TrendSeverity.HIGH if ttb_minutes < 30 else TrendSeverity.MEDIUM
                )
                warnings.append({
                    "metric_key": trend.metric_key,
                    "current_value": round(trend.current_value, 2),
                    "threshold": ceiling,
                    "status": "approaching",
                    "time_to_breach_min": round(ttb_minutes, 1),
                    "predicted_at_horizon": round(
                        trend.current_value + trend.slope * horizon_s, 2
                    ),
                    "severity": sev.value,
                    "slope_per_min": round(trend.slope * 60, 4),
                })

        # Sort by urgency — soonest breach first
        warnings.sort(key=lambda w: w["time_to_breach_min"])
        return warnings

    # ── Degradation Report ──────────────────────────────────────────

    def degradation_report(self) -> Dict[str, Any]:
        """Summary of all degrading metrics with severity classification.

        Returns:
            Dict with ``degrading`` list, ``volatile`` list, and ``summary``.
        """
        trends = self.all_trends()
        degrading: List[Dict[str, Any]] = []
        volatile_list: List[Dict[str, Any]] = []

        for trend in trends:
            if trend.direction == TrendDirection.RISING:
                metric_name = (
                    trend.metric_key.split(".", 1)[1]
                    if "." in trend.metric_key
                    else trend.metric_key
                )
                if metric_name in _UPPER_BOUNDED:
                    degrading.append(trend.to_dict())
            elif trend.direction == TrendDirection.VOLATILE:
                volatile_list.append(trend.to_dict())

        # Sort by severity ordinal then slope magnitude
        severity_order = {
            TrendSeverity.CRITICAL.value: 0,
            TrendSeverity.HIGH.value: 1,
            TrendSeverity.MEDIUM.value: 2,
            TrendSeverity.LOW.value: 3,
            TrendSeverity.NONE.value: 4,
        }
        degrading.sort(key=lambda d: (severity_order.get(d["severity"], 9), -abs(d["slope"])))

        return {
            "degrading": degrading,
            "volatile": volatile_list,
            "degrading_count": len(degrading),
            "volatile_count": len(volatile_list),
            "worst_severity": degrading[0]["severity"] if degrading else TrendSeverity.NONE.value,
            "ts": time.time(),
        }

    # ── Single-Point Prediction ─────────────────────────────────────

    def predict(self, metric_key: str, future_seconds: float) -> Optional[float]:
        """Predict a single value at a future time.

        Args:
            metric_key: Fully qualified ``node.metric`` key.
            future_seconds: How many seconds into the future to predict.

        Returns:
            The predicted value, or ``None`` if not enough data.
        """
        with self._lock:
            buf = self._samples.get(metric_key)
            if not buf or len(buf) < self._min_samples:
                return None
            values = list(buf)

        slope, intercept, _ = self._compute_regression(values)
        t0 = values[0][0]
        now = values[-1][0]
        offset = now - t0
        return slope * (offset + future_seconds) + intercept

    # ── Prediction Series ───────────────────────────────────────────

    def recent_predictions(
        self,
        metric_key: str,
        points: int = 12,
        interval_minutes: int = 5,
    ) -> List[Dict[str, Any]]:
        """Generate a series of future predictions at regular intervals.

        Args:
            metric_key: Fully qualified ``node.metric`` key.
            points: Number of future data points to produce.
            interval_minutes: Minutes between each predicted point.

        Returns:
            List of dicts with ``ts``, ``offset_minutes``, and ``predicted_value``.
        """
        with self._lock:
            buf = self._samples.get(metric_key)
            if not buf or len(buf) < self._min_samples:
                return []
            values = list(buf)

        slope, intercept, _ = self._compute_regression(values)
        t0 = values[0][0]
        now = values[-1][0]
        offset = now - t0

        series: List[Dict[str, Any]] = []
        for i in range(1, points + 1):
            future_s = i * interval_minutes * 60.0
            pred = slope * (offset + future_s) + intercept
            series.append({
                "ts": now + future_s,
                "offset_minutes": i * interval_minutes,
                "predicted_value": round(pred, 4),
            })
        return series

    # ── Persistence ─────────────────────────────────────────────────

    def persist_trends(self) -> int:
        """Save current trends to the SQLite database.

        Returns:
            Number of trends persisted.
        """
        trends = self.all_trends()
        if not trends:
            return 0

        conn = self._get_db()
        count = 0
        try:
            for trend in trends:
                conn.execute(
                    """
                    INSERT INTO metric_trends
                        (metric_key, slope, direction, r_squared,
                         predicted_1h, predicted_4h, predicted_24h,
                         current_value, severity, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trend.metric_key,
                        trend.slope,
                        trend.direction.value,
                        trend.r_squared,
                        trend.predicted_1h,
                        trend.predicted_4h,
                        trend.predicted_24h,
                        trend.current_value,
                        trend.severity.value,
                        trend.ts,
                    ),
                )
                count += 1
            conn.commit()
            logger.debug("Persisted %d trends to DB", count)
        except Exception as exc:
            logger.warning("Failed to persist trends: %s", exc)
            try:
                conn.rollback()
            except Exception:
                pass
        return count

    def load_trends(self, since_hours: float = 24) -> List[Dict[str, Any]]:
        """Load historical trend snapshots from the database.

        Args:
            since_hours: How far back to look (in hours).

        Returns:
            List of trend dicts ordered by timestamp descending.
        """
        cutoff = time.time() - since_hours * 3600
        conn = self._get_db()
        try:
            cur = conn.execute(
                """
                SELECT metric_key, slope, direction, r_squared,
                       predicted_1h, predicted_4h, predicted_24h,
                       current_value, severity, ts
                FROM metric_trends
                WHERE ts >= ?
                ORDER BY ts DESC
                """,
                (cutoff,),
            )
            rows = cur.fetchall()
            return [
                {
                    "metric_key": r["metric_key"],
                    "slope": r["slope"],
                    "direction": r["direction"],
                    "r_squared": r["r_squared"],
                    "predicted_1h": r["predicted_1h"],
                    "predicted_4h": r["predicted_4h"],
                    "predicted_24h": r["predicted_24h"],
                    "current_value": r["current_value"],
                    "severity": r["severity"],
                    "ts": r["ts"],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("Failed to load trends: %s", exc)
            return []

    # ── Background Thread ───────────────────────────────────────────

    def start_background(self, interval: float = 60.0) -> None:
        """Start a daemon thread that periodically computes and persists trends.

        Args:
            interval: Seconds between background computation cycles.
        """
        if self._running:
            logger.debug("TrendPredictor background thread already running")
            return
        self._running = True
        self._bg_interval = interval
        self._bg_thread = threading.Thread(
            target=self._bg_loop, daemon=True, name="TrendPredictor-bg"
        )
        self._bg_thread.start()
        logger.info("TrendPredictor background started (interval=%.1fs)", interval)

    def stop_background(self) -> None:
        """Stop the background computation thread."""
        self._running = False
        if self._bg_thread is not None:
            self._bg_thread.join(timeout=5.0)
            self._bg_thread = None
        logger.info("TrendPredictor background stopped")

    def _bg_loop(self) -> None:
        """Background loop: compute trends, persist, log warnings."""
        while self._running:
            try:
                trends = self.all_trends()
                if trends:
                    self.persist_trends()

                warnings = self.capacity_warnings()
                for w in warnings:
                    logger.warning(
                        "Capacity warning: %s at %.1f (threshold %.1f, breach in %.1f min)",
                        w["metric_key"],
                        w["current_value"],
                        w["threshold"],
                        w["time_to_breach_min"],
                    )
            except Exception as exc:
                logger.error("TrendPredictor background error: %s", exc)

            # Sleep in small increments for responsive shutdown
            slept = 0.0
            interval = getattr(self, "_bg_interval", 60.0)
            while slept < interval and self._running:
                time.sleep(min(1.0, interval - slept))
                slept += 1.0

    # ── Summary ─────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Overall summary of trend tracking state.

        Returns:
            Dict with counts of tracked metrics, direction breakdown,
            worst degradation info, and background thread status.
        """
        with self._lock:
            total_metrics = len(self._samples)
            total_samples = sum(len(buf) for buf in self._samples.values())
            qualifying = sum(
                1 for buf in self._samples.values()
                if len(buf) >= self._min_samples
            )

        trends = self.all_trends()

        rising = sum(1 for t in trends if t.direction == TrendDirection.RISING)
        falling = sum(1 for t in trends if t.direction == TrendDirection.FALLING)
        stable = sum(1 for t in trends if t.direction == TrendDirection.STABLE)
        volatile = sum(1 for t in trends if t.direction == TrendDirection.VOLATILE)

        # Find worst degradation
        worst: Optional[Dict[str, Any]] = None
        severity_rank = {
            TrendSeverity.CRITICAL: 4,
            TrendSeverity.HIGH: 3,
            TrendSeverity.MEDIUM: 2,
            TrendSeverity.LOW: 1,
            TrendSeverity.NONE: 0,
        }
        for trend in trends:
            rank = severity_rank.get(trend.severity, 0)
            if rank > 0 and (worst is None or rank > worst["_rank"]):
                worst = {
                    "metric_key": trend.metric_key,
                    "severity": trend.severity.value,
                    "slope_per_min": round(trend.slope * 60, 6),
                    "direction": trend.direction.value,
                    "current_value": round(trend.current_value, 2),
                    "_rank": rank,
                }

        if worst:
            worst.pop("_rank", None)

        return {
            "total_metrics": total_metrics,
            "total_samples": total_samples,
            "qualifying_metrics": qualifying,
            "direction_counts": {
                "rising": rising,
                "falling": falling,
                "stable": stable,
                "volatile": volatile,
            },
            "worst_degradation": worst,
            "background_running": self._running,
            "window_size": self._window_size,
            "min_samples": self._min_samples,
            "ts": time.time(),
        }
