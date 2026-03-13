"""
AnomalyDetector — Statistical anomaly detection beyond simple thresholds.

Implements z-score, IQR (interquartile range), and MAD (median absolute
deviation) detectors on metric time-series data.  Integrates with AlertEngine
to fire anomaly-triggered alerts.

Usage::

    from engine.observability.anomaly_detector import get_anomaly_detector
    detector = get_anomaly_detector()

    # Feed samples (same interface as AlertEngine.feed)
    detector.feed("system", "cpu_pct", 45.2)

    # Evaluate all metrics for anomalies
    anomalies = detector.evaluate()

    # Get anomaly history
    detector.recent_anomalies(n=20)

    # Configure sensitivity per metric
    detector.set_sensitivity("system.cpu_pct", z_threshold=2.5)
"""
from __future__ import annotations

import logging
import math
import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional["AnomalyDetector"] = None
_lock = threading.Lock()


def get_anomaly_detector() -> "AnomalyDetector":
    """Get or create the singleton AnomalyDetector."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AnomalyDetector()
    return _instance


# ── Data Models ─────────────────────────────────────────────────────────


class AnomalyMethod(Enum):
    """Detection method used to flag an anomaly."""
    ZSCORE = "zscore"
    IQR = "iqr"
    MAD = "mad"


class AnomalySeverity(Enum):
    """Severity levels for detected anomalies."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AnomalyEvent:
    """A detected anomaly on a specific metric."""
    node: str
    metric: str
    value: float
    expected_mean: float
    deviation: float
    method: AnomalyMethod
    severity: AnomalySeverity
    timestamp: float
    z_score: float = 0.0
    iqr_factor: float = 0.0
    mad_score: float = 0.0
    baseline_window: int = 0
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node": self.node,
            "metric": self.metric,
            "value": round(self.value, 4),
            "expected_mean": round(self.expected_mean, 4),
            "deviation": round(self.deviation, 4),
            "method": self.method.value,
            "severity": self.severity.value,
            "z_score": round(self.z_score, 2),
            "iqr_factor": round(self.iqr_factor, 2),
            "mad_score": round(self.mad_score, 2),
            "baseline_window": self.baseline_window,
            "message": self.message,
            "ts": self.timestamp,
        }


@dataclass
class MetricConfig:
    """Per-metric anomaly detection configuration."""
    z_threshold: float = 3.0
    iqr_multiplier: float = 1.5
    mad_threshold: float = 3.5
    min_samples: int = 30
    methods: List[AnomalyMethod] = field(
        default_factory=lambda: [AnomalyMethod.ZSCORE, AnomalyMethod.IQR]
    )
    enabled: bool = True
    cooldown_s: float = 60.0


# ── DB Schema ───────────────────────────────────────────────────────────

_ANOMALY_SCHEMA = """
CREATE TABLE IF NOT EXISTS anomaly_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    node TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    expected_mean REAL DEFAULT 0.0,
    deviation REAL DEFAULT 0.0,
    method TEXT NOT NULL,
    severity TEXT NOT NULL,
    z_score REAL DEFAULT 0.0,
    iqr_factor REAL DEFAULT 0.0,
    mad_score REAL DEFAULT 0.0,
    baseline_window INTEGER DEFAULT 0,
    message TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_ae_ts ON anomaly_events(ts);
CREATE INDEX IF NOT EXISTS idx_ae_node ON anomaly_events(node, metric, ts);
CREATE INDEX IF NOT EXISTS idx_ae_severity ON anomaly_events(severity, ts);
"""


# ── AnomalyDetector ────────────────────────────────────────────────────


class AnomalyDetector:
    """
    Statistical anomaly detection engine.

    Maintains rolling metric buffers and detects anomalies using multiple
    methods (z-score, IQR, MAD). Fires callbacks and persists events to DB.

    Thread-safe singleton.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        default_window: int = 300,
        on_anomaly: Optional[Callable[[AnomalyEvent], None]] = None,
    ):
        self._lock = threading.Lock()
        self._on_anomaly = on_anomaly

        # Metric sample buffers: "node.metric" → deque of (ts, value)
        self._samples: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))

        # Per-metric configuration overrides
        self._configs: Dict[str, MetricConfig] = {}
        self._default_config = MetricConfig()
        self._default_window = default_window

        # Anomaly history (in-memory ring buffer)
        self._anomalies: deque = deque(maxlen=1000)

        # Cooldown tracking: "node.metric" → last anomaly ts
        self._last_anomaly_ts: Dict[str, float] = {}

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
        """Create anomaly tables."""
        try:
            conn = self._get_db()
            conn.executescript(_ANOMALY_SCHEMA)
            conn.commit()
        except Exception as exc:
            logger.warning("AnomalyDetector DB init failed: %s", exc)

    # ── Configuration ───────────────────────────────────────────────

    def set_sensitivity(
        self,
        metric_key: str,
        z_threshold: Optional[float] = None,
        iqr_multiplier: Optional[float] = None,
        mad_threshold: Optional[float] = None,
        min_samples: Optional[int] = None,
        methods: Optional[List[AnomalyMethod]] = None,
        enabled: Optional[bool] = None,
        cooldown_s: Optional[float] = None,
    ) -> None:
        """Set sensitivity parameters for a specific metric.

        Args:
            metric_key: "node.metric" key (e.g., "system.cpu_pct").
            z_threshold: Z-score threshold for anomaly detection.
            iqr_multiplier: IQR multiplier (1.5 = standard, 3.0 = extreme).
            mad_threshold: MAD score threshold.
            min_samples: Minimum samples before detection activates.
            methods: List of detection methods to use.
            enabled: Whether detection is enabled for this metric.
            cooldown_s: Cooldown seconds between anomaly reports.
        """
        cfg = self._configs.get(metric_key, MetricConfig())
        if z_threshold is not None:
            cfg.z_threshold = z_threshold
        if iqr_multiplier is not None:
            cfg.iqr_multiplier = iqr_multiplier
        if mad_threshold is not None:
            cfg.mad_threshold = mad_threshold
        if min_samples is not None:
            cfg.min_samples = min_samples
        if methods is not None:
            cfg.methods = methods
        if enabled is not None:
            cfg.enabled = enabled
        if cooldown_s is not None:
            cfg.cooldown_s = cooldown_s
        self._configs[metric_key] = cfg

    def get_config(self, metric_key: str) -> MetricConfig:
        """Get configuration for a metric, falling back to defaults."""
        return self._configs.get(metric_key, self._default_config)

    # ── Feeding ─────────────────────────────────────────────────────

    def feed(self, node: str, metric: str, value: float) -> None:
        """Feed a metric sample for anomaly analysis.

        Same interface as AlertEngine.feed() for easy integration.

        Args:
            node: Metric node (e.g., "system", "gpu_primary", "pipeline").
            metric: Metric name (e.g., "cpu_pct", "latency_ms").
            value: Metric value.
        """
        key = f"{node}.{metric}"
        self._samples[key].append((time.time(), value))

    # ── Detection ───────────────────────────────────────────────────

    def evaluate(self) -> List[AnomalyEvent]:
        """Evaluate all metrics for anomalies.

        Returns:
            List of newly detected AnomalyEvent objects.
        """
        events: List[AnomalyEvent] = []
        now = time.time()

        for key, samples in list(self._samples.items()):
            cfg = self.get_config(key)
            if not cfg.enabled:
                continue

            # Check cooldown
            last_ts = self._last_anomaly_ts.get(key, 0.0)
            if now - last_ts < cfg.cooldown_s:
                continue

            # Extract recent values
            values = [v for ts, v in samples if ts >= now - self._default_window]
            if len(values) < cfg.min_samples:
                continue

            node, metric = key.split(".", 1) if "." in key else (key, key)
            latest = values[-1]

            # Run configured detection methods
            for method in cfg.methods:
                anomaly = self._detect(node, metric, latest, values, method, cfg, now)
                if anomaly:
                    events.append(anomaly)
                    self._last_anomaly_ts[key] = now
                    self._anomalies.append(anomaly)
                    self._persist_anomaly(anomaly)

                    if self._on_anomaly:
                        try:
                            self._on_anomaly(anomaly)
                        except Exception:
                            logger.debug("Anomaly callback error", exc_info=True)
                    break

        return events

    def _detect(
        self,
        node: str,
        metric: str,
        value: float,
        values: List[float],
        method: AnomalyMethod,
        cfg: MetricConfig,
        now: float,
    ) -> Optional[AnomalyEvent]:
        """Run a single detection method."""
        if method == AnomalyMethod.ZSCORE:
            return self._detect_zscore(node, metric, value, values, cfg, now)
        elif method == AnomalyMethod.IQR:
            return self._detect_iqr(node, metric, value, values, cfg, now)
        elif method == AnomalyMethod.MAD:
            return self._detect_mad(node, metric, value, values, cfg, now)
        return None

    def _detect_zscore(
        self,
        node: str,
        metric: str,
        value: float,
        values: List[float],
        cfg: MetricConfig,
        now: float,
    ) -> Optional[AnomalyEvent]:
        """Z-score based anomaly detection.

        Flags values that deviate more than z_threshold standard deviations
        from the rolling mean.
        """
        if len(values) < 2:
            return None

        mean = statistics.mean(values)
        stdev = statistics.stdev(values)
        if stdev == 0:
            return None

        z = abs(value - mean) / stdev
        if z < cfg.z_threshold:
            return None

        severity = self._severity_from_z(z, cfg.z_threshold)
        return AnomalyEvent(
            node=node,
            metric=metric,
            value=value,
            expected_mean=mean,
            deviation=value - mean,
            method=AnomalyMethod.ZSCORE,
            severity=severity,
            timestamp=now,
            z_score=z,
            baseline_window=len(values),
            message=(
                f"Z-score anomaly: {node}.{metric}={value:.2f} "
                f"(z={z:.1f}, mean={mean:.2f}, σ={stdev:.2f})"
            ),
        )

    def _detect_iqr(
        self,
        node: str,
        metric: str,
        value: float,
        values: List[float],
        cfg: MetricConfig,
        now: float,
    ) -> Optional[AnomalyEvent]:
        """IQR (interquartile range) based anomaly detection.

        Flags values outside Q1 - k*IQR or Q3 + k*IQR.
        """
        if len(values) < 4:
            return None

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[n // 4]
        q3 = sorted_vals[(3 * n) // 4]
        iqr = q3 - q1
        if iqr == 0:
            return None

        lower = q1 - cfg.iqr_multiplier * iqr
        upper = q3 + cfg.iqr_multiplier * iqr

        if lower <= value <= upper:
            return None

        factor = max(abs(value - lower), abs(value - upper)) / iqr
        mean = statistics.mean(values)
        severity = self._severity_from_iqr(factor, cfg.iqr_multiplier)

        return AnomalyEvent(
            node=node,
            metric=metric,
            value=value,
            expected_mean=mean,
            deviation=value - mean,
            method=AnomalyMethod.IQR,
            severity=severity,
            timestamp=now,
            iqr_factor=factor,
            baseline_window=len(values),
            message=(
                f"IQR anomaly: {node}.{metric}={value:.2f} "
                f"(factor={factor:.1f}, range=[{lower:.2f}, {upper:.2f}])"
            ),
        )

    def _detect_mad(
        self,
        node: str,
        metric: str,
        value: float,
        values: List[float],
        cfg: MetricConfig,
        now: float,
    ) -> Optional[AnomalyEvent]:
        """MAD (median absolute deviation) based anomaly detection.

        More robust than z-score against outliers in the baseline.
        """
        if len(values) < 5:
            return None

        median = statistics.median(values)
        abs_devs = [abs(v - median) for v in values]
        mad = statistics.median(abs_devs)

        if mad == 0:
            return None

        # Modified z-score using MAD
        modified_z = 0.6745 * (value - median) / mad
        abs_z = abs(modified_z)

        if abs_z < cfg.mad_threshold:
            return None

        severity = self._severity_from_z(abs_z, cfg.mad_threshold)
        return AnomalyEvent(
            node=node,
            metric=metric,
            value=value,
            expected_mean=median,
            deviation=value - median,
            method=AnomalyMethod.MAD,
            severity=severity,
            timestamp=now,
            mad_score=abs_z,
            baseline_window=len(values),
            message=(
                f"MAD anomaly: {node}.{metric}={value:.2f} "
                f"(mad_z={abs_z:.1f}, median={median:.2f}, MAD={mad:.2f})"
            ),
        )

    # ── Severity Classification ─────────────────────────────────────

    @staticmethod
    def _severity_from_z(z: float, threshold: float) -> AnomalySeverity:
        """Map z-score deviation to severity level."""
        ratio = z / max(threshold, 0.001)
        if ratio >= 3.0:
            return AnomalySeverity.CRITICAL
        elif ratio >= 2.0:
            return AnomalySeverity.HIGH
        elif ratio >= 1.5:
            return AnomalySeverity.MEDIUM
        return AnomalySeverity.LOW

    @staticmethod
    def _severity_from_iqr(factor: float, multiplier: float) -> AnomalySeverity:
        """Map IQR factor to severity level."""
        ratio = factor / max(multiplier, 0.001)
        if ratio >= 4.0:
            return AnomalySeverity.CRITICAL
        elif ratio >= 2.5:
            return AnomalySeverity.HIGH
        elif ratio >= 1.5:
            return AnomalySeverity.MEDIUM
        return AnomalySeverity.LOW

    # ── Query API ───────────────────────────────────────────────────

    def recent_anomalies(
        self,
        n: int = 50,
        node: str = "",
        severity: str = "",
    ) -> List[Dict[str, Any]]:
        """Get recent anomaly events.

        Args:
            n: Maximum events to return.
            node: Optional node filter.
            severity: Optional severity filter.

        Returns:
            List of anomaly event dicts.
        """
        try:
            conn = self._get_db()
            conditions = ["1=1"]
            params: List[Any] = []

            if node:
                conditions.append("node = ?")
                params.append(node)
            if severity:
                conditions.append("severity = ?")
                params.append(severity)

            where = " AND ".join(conditions)
            params.append(n)

            cur = conn.execute(
                f"SELECT * FROM anomaly_events WHERE {where} "
                f"ORDER BY ts DESC LIMIT ?",
                params,
            )
            return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.debug("Anomaly query failed: %s", exc)
            return []

    def anomaly_counts(self, hours: float = 24.0) -> Dict[str, Dict[str, int]]:
        """Get anomaly counts grouped by node and severity.

        Args:
            hours: Lookback window in hours.

        Returns:
            Dict: {node: {severity: count}}.
        """
        cutoff = time.time() - (hours * 3600)
        counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        try:
            conn = self._get_db()
            cur = conn.execute(
                "SELECT node, severity, COUNT(*) as cnt "
                "FROM anomaly_events WHERE ts >= ? "
                "GROUP BY node, severity",
                (cutoff,),
            )
            for row in cur.fetchall():
                counts[row["node"]][row["severity"]] = row["cnt"]
        except Exception as exc:
            logger.debug("Anomaly counts failed: %s", exc)

        return dict(counts)

    def baseline_stats(self, node: str, metric: str) -> Dict[str, float]:
        """Get current baseline statistics for a metric.

        Args:
            node: Metric node.
            metric: Metric name.

        Returns:
            Dict with mean, stdev, median, mad, q1, q3, iqr, sample_count.
        """
        key = f"{node}.{metric}"
        samples = self._samples.get(key)
        if not samples or len(samples) < 2:
            return {"sample_count": 0}

        values = [v for _, v in samples]
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[n // 4]
        q3 = sorted_vals[(3 * n) // 4]
        median = statistics.median(values)
        abs_devs = [abs(v - median) for v in values]
        mad = statistics.median(abs_devs) if abs_devs else 0.0

        return {
            "sample_count": n,
            "mean": round(statistics.mean(values), 4),
            "stdev": round(statistics.stdev(values), 4),
            "median": round(median, 4),
            "mad": round(mad, 4),
            "q1": round(q1, 4),
            "q3": round(q3, 4),
            "iqr": round(q3 - q1, 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }

    def snapshot(self) -> Dict[str, Any]:
        """Full anomaly detector snapshot.

        Returns:
            Dict with status, counts, tracked metrics, and recent anomalies.
        """
        tracked = list(self._samples.keys())
        counts = self.anomaly_counts(hours=1.0)
        total_1h = sum(
            sum(sev.values()) for sev in counts.values()
        )

        return {
            "tracked_metrics": len(tracked),
            "anomalies_1h": total_1h,
            "anomalies_24h": sum(
                sum(sev.values()) for sev in self.anomaly_counts(hours=24.0).values()
            ),
            "counts_by_node": dict(counts),
            "recent": [a.to_dict() for a in list(self._anomalies)[-10:]],
        }

    # ── Persistence ─────────────────────────────────────────────────

    def _persist_anomaly(self, event: AnomalyEvent) -> None:
        """Write anomaly event to SQLite."""
        try:
            conn = self._get_db()
            conn.execute(
                "INSERT INTO anomaly_events "
                "(ts, node, metric, value, expected_mean, deviation, method, "
                "severity, z_score, iqr_factor, mad_score, baseline_window, message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.timestamp, event.node, event.metric, event.value,
                    event.expected_mean, event.deviation, event.method.value,
                    event.severity.value, event.z_score, event.iqr_factor,
                    event.mad_score, event.baseline_window, event.message,
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.debug("Failed to persist anomaly: %s", exc)

    def prune(self, max_age_hours: float = 168.0) -> int:
        """Delete anomaly events older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours (default 7 days).

        Returns:
            Number of rows deleted.
        """
        cutoff = time.time() - (max_age_hours * 3600)
        try:
            conn = self._get_db()
            cur = conn.execute("DELETE FROM anomaly_events WHERE ts < ?", (cutoff,))
            conn.commit()
            return cur.rowcount
        except Exception as exc:
            logger.debug("Anomaly prune failed: %s", exc)
            return 0
