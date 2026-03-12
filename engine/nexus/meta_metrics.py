"""
MetaMetrics — System-level metrics tracking for CosySim's autonomous pipeline.

Tracks and trends ALL system metrics over time: knowledge growth, cache hit
rates, LLM calls, task completion, agent errors, NLM usage, test pass rates,
inference speed.  Stores everything in SQLite for trend analysis and alerting.

Thread-safe singleton — call ``get_meta_metrics()`` from anywhere.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from engine.paths import DATA_DIR

logger = logging.getLogger(__name__)

_DEFAULT_PATH = DATA_DIR / "meta_metrics.db"

# ── Data Models ─────────────────────────────────────────────────────────

_START_TIME = time.monotonic()


@dataclass
class MetricPoint:
    """A single metric observation."""

    name: str
    value: float
    timestamp: datetime
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class MetricAlert:
    """An alert fired when a metric deviates from its baseline."""

    metric_name: str
    alert_type: str  # "regression", "threshold", "trend"
    message: str
    current_value: float
    baseline_value: float
    threshold_pct: float
    timestamp: datetime


# ── Schema ──────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL,
    value     REAL    NOT NULL,
    ts        REAL    NOT NULL,
    tags_json TEXT    DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_metrics_name_ts ON metrics(name, ts);

CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name     TEXT    NOT NULL,
    alert_type      TEXT    NOT NULL,
    message         TEXT    NOT NULL,
    current_value   REAL    NOT NULL,
    baseline_value  REAL    NOT NULL,
    threshold_pct   REAL    NOT NULL,
    ts              REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);

CREATE TABLE IF NOT EXISTS baselines (
    name  TEXT PRIMARY KEY,
    value REAL NOT NULL,
    ts    REAL NOT NULL
);
"""

# ── Singleton ───────────────────────────────────────────────────────────

_metrics: Optional[MetaMetrics] = None
_lock = threading.Lock()


def get_meta_metrics(db_path: Optional[Path] = None) -> MetaMetrics:
    """Get or create the singleton MetaMetrics instance."""
    global _metrics
    if _metrics is None:
        with _lock:
            if _metrics is None:
                _metrics = MetaMetrics(db_path)
    return _metrics


# ── Metric Categories ───────────────────────────────────────────────────

KNOWLEDGE_METRICS = [
    "nexus.entries.total",
    "nexus.entries.added",
    "nexus.qa.total",
    "nexus.qa.cache_hits",
    "nexus.quality.average",
]

INFERENCE_METRICS = [
    "llm.calls.total",
    "llm.tokens.input",
    "llm.tokens.output",
    "llm.cache.hit_rate",
    "llm.latency.avg_ms",
]

TASK_METRICS = [
    "tasks.created",
    "tasks.completed",
    "tasks.failed",
    "tasks.agent_error_rate",
]

TEST_METRICS = [
    "tests.total",
    "tests.passed",
    "tests.failed",
    "tests.duration_s",
]

SYSTEM_METRICS = [
    "system.vram_used_mb",
    "system.uptime_s",
    "nlm.notebooks.active",
    "nlm.research.sessions",
]

NEWS_METRICS = [
    "news.fetch.total",
    "news.fetch.fresh",
    "news.fetch.latency_ms",
    "news.fetch.sources_success",
    "news.fetch.sources_failure",
    "news.fetch.sources_skipped",
    "news.dedup.filtered",
    "news.dedup.ratio",
    "news.store.success",
    "news.store.failed",
    "news.distill.latency_ms",
    "news.distill.qa_pairs",
    "news.cycle.duration_s",
]

ALL_METRIC_NAMES = (
    KNOWLEDGE_METRICS
    + INFERENCE_METRICS
    + TASK_METRICS
    + TEST_METRICS
    + SYSTEM_METRICS
    + NEWS_METRICS
)


# ── MetaMetrics ─────────────────────────────────────────────────────────

class MetaMetrics:
    """Comprehensive system-level metrics tracking with trend analysis."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialize SQLite storage and create tables.

        Args:
            db_path: Path to the SQLite database. Defaults to
                     ``data/meta_metrics.db``.
        """
        self._path = Path(db_path) if db_path else _DEFAULT_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    # ── Connection helpers ──────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._path), timeout=5)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """Yield a cursor inside a commit/rollback transaction."""
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    # ── Core API ────────────────────────────────────────────────────

    def record(
        self,
        name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record a single metric point.

        Args:
            name: Dot-notation metric name (e.g. ``nexus.entries.total``).
            value: Numeric metric value.
            tags: Optional key-value tags for this observation.
        """
        tags_json = json.dumps(tags or {})
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO metrics (name, value, ts, tags_json) "
                "VALUES (?, ?, ?, ?)",
                (name, value, time.time(), tags_json),
            )

    def record_batch(self, metrics: List[Tuple[str, float]]) -> int:
        """Record multiple metrics at once.

        Args:
            metrics: List of ``(name, value)`` tuples.

        Returns:
            Number of metrics recorded.
        """
        now = time.time()
        rows = [(name, value, now, "{}") for name, value in metrics]
        with self._cursor() as cur:
            cur.executemany(
                "INSERT INTO metrics (name, value, ts, tags_json) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def get(self, name: str, hours: int = 24) -> List[MetricPoint]:
        """Get metric history for the last *hours*.

        Args:
            name: Metric name to query.
            hours: Look-back window in hours.

        Returns:
            List of MetricPoint instances ordered by time ascending.
        """
        cutoff = time.time() - (hours * 3600)
        with self._cursor() as cur:
            cur.execute(
                "SELECT name, value, ts, tags_json "
                "FROM metrics WHERE name = ? AND ts > ? ORDER BY ts",
                (name, cutoff),
            )
            results: List[MetricPoint] = []
            for row in cur.fetchall():
                results.append(
                    MetricPoint(
                        name=row["name"],
                        value=row["value"],
                        timestamp=datetime.fromtimestamp(
                            row["ts"], tz=timezone.utc
                        ),
                        tags=json.loads(row["tags_json"]),
                    )
                )
            return results

    # ── Trend & comparison ──────────────────────────────────────────

    def trend(self, name: str, days: int = 7) -> Dict[str, Any]:
        """Calculate trend statistics for a metric.

        Args:
            name: Metric name.
            days: Number of days to analyse.

        Returns:
            Dict with keys: direction, rate_of_change, min, max, avg,
            first, last, count.
        """
        cutoff = time.time() - (days * 86400)
        with self._cursor() as cur:
            cur.execute(
                "SELECT value, ts FROM metrics "
                "WHERE name = ? AND ts > ? ORDER BY ts",
                (name, cutoff),
            )
            rows = cur.fetchall()

        if not rows:
            return {
                "direction": "stable",
                "rate_of_change": 0.0,
                "min": 0.0,
                "max": 0.0,
                "avg": 0.0,
                "first": 0.0,
                "last": 0.0,
                "count": 0,
            }

        values = [r["value"] for r in rows]
        first_val = values[0]
        last_val = values[-1]
        avg_val = sum(values) / len(values)
        min_val = min(values)
        max_val = max(values)

        if first_val != 0:
            rate = (last_val - first_val) / abs(first_val)
        else:
            rate = 0.0 if last_val == 0 else 1.0

        if last_val > first_val:
            direction = "up"
        elif last_val < first_val:
            direction = "down"
        else:
            direction = "stable"

        return {
            "direction": direction,
            "rate_of_change": round(rate, 4),
            "min": min_val,
            "max": max_val,
            "avg": round(avg_val, 4),
            "first": first_val,
            "last": last_val,
            "count": len(values),
        }

    def compare(
        self,
        name: str,
        current_hours: int = 24,
        baseline_hours: int = 168,
    ) -> Dict[str, Any]:
        """Compare recent period vs baseline period.

        Args:
            name: Metric name.
            current_hours: Duration of the recent window (hours).
            baseline_hours: Duration of the baseline window (hours).

        Returns:
            Dict with current_avg, baseline_avg, change_pct, improved.
        """
        now = time.time()
        current_cutoff = now - (current_hours * 3600)
        baseline_start = now - (baseline_hours * 3600)

        with self._cursor() as cur:
            cur.execute(
                "SELECT AVG(value) as avg_val FROM metrics "
                "WHERE name = ? AND ts > ?",
                (name, current_cutoff),
            )
            current_row = cur.fetchone()
            current_avg = current_row["avg_val"] if current_row["avg_val"] is not None else 0.0

            cur.execute(
                "SELECT AVG(value) as avg_val FROM metrics "
                "WHERE name = ? AND ts > ? AND ts <= ?",
                (name, baseline_start, current_cutoff),
            )
            baseline_row = cur.fetchone()
            baseline_avg = baseline_row["avg_val"] if baseline_row["avg_val"] is not None else 0.0

        if baseline_avg != 0:
            change_pct = ((current_avg - baseline_avg) / abs(baseline_avg)) * 100
        else:
            change_pct = 0.0 if current_avg == 0 else 100.0

        higher_is_better = name in {
            "nexus.entries.total",
            "nexus.qa.total",
            "nexus.qa.cache_hits",
            "nexus.quality.average",
            "llm.cache.hit_rate",
            "tasks.completed",
            "tests.total",
            "tests.passed",
        }
        if higher_is_better:
            improved = change_pct > 0
        else:
            improved = change_pct < 0

        return {
            "current_avg": round(current_avg, 4),
            "baseline_avg": round(baseline_avg, 4),
            "change_pct": round(change_pct, 2),
            "improved": improved,
        }

    # ── Baselines & regressions ─────────────────────────────────────

    def set_baseline(self, name: str, value: float) -> None:
        """Set a baseline value for a metric.

        Args:
            name: Metric name.
            value: Baseline value to store.
        """
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO baselines (name, value, ts) "
                "VALUES (?, ?, ?)",
                (name, value, time.time()),
            )

    def auto_baseline(self, name: str, days: int = 7) -> float:
        """Auto-set baseline from the average of the last *days*.

        Args:
            name: Metric name.
            days: Number of days to average over.

        Returns:
            The computed baseline value.
        """
        cutoff = time.time() - (days * 86400)
        with self._cursor() as cur:
            cur.execute(
                "SELECT AVG(value) as avg_val FROM metrics "
                "WHERE name = ? AND ts > ?",
                (name, cutoff),
            )
            row = cur.fetchone()
            avg_val = row["avg_val"] if row["avg_val"] is not None else 0.0

        self.set_baseline(name, avg_val)
        return avg_val

    def check_regressions(
        self, threshold_pct: float = 10.0
    ) -> List[MetricAlert]:
        """Check all base-lined metrics for regressions.

        A regression is detected when the latest recorded value deviates
        from its baseline by more than *threshold_pct* percent in the
        "wrong" direction.

        Args:
            threshold_pct: Percentage deviation that triggers an alert.

        Returns:
            List of MetricAlert instances for any regressions found.
        """
        alerts: List[MetricAlert] = []
        with self._cursor() as cur:
            cur.execute("SELECT name, value FROM baselines")
            baselines = {row["name"]: row["value"] for row in cur.fetchall()}

        if not baselines:
            return alerts

        higher_is_better = {
            "nexus.entries.total",
            "nexus.qa.total",
            "nexus.qa.cache_hits",
            "nexus.quality.average",
            "llm.cache.hit_rate",
            "tasks.completed",
            "tests.total",
            "tests.passed",
        }

        for metric_name, baseline_val in baselines.items():
            with self._cursor() as cur:
                cur.execute(
                    "SELECT value FROM metrics WHERE name = ? "
                    "ORDER BY ts DESC LIMIT 1",
                    (metric_name,),
                )
                row = cur.fetchone()
            if row is None:
                continue

            current_val = row["value"]
            if baseline_val == 0:
                continue

            change_pct = ((current_val - baseline_val) / abs(baseline_val)) * 100

            is_regression = False
            if metric_name in higher_is_better:
                is_regression = change_pct < -threshold_pct
            else:
                is_regression = change_pct > threshold_pct

            if is_regression:
                alert = MetricAlert(
                    metric_name=metric_name,
                    alert_type="regression",
                    message=(
                        "%s regressed %.1f%% (baseline: %.2f, current: %.2f)"
                        % (metric_name, abs(change_pct), baseline_val, current_val)
                    ),
                    current_value=current_val,
                    baseline_value=baseline_val,
                    threshold_pct=threshold_pct,
                    timestamp=datetime.now(tz=timezone.utc),
                )
                alerts.append(alert)
                self._store_alert(alert)

        return alerts

    def _store_alert(self, alert: MetricAlert) -> None:
        """Persist an alert to the alerts table."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO alerts "
                "(metric_name, alert_type, message, current_value, "
                "baseline_value, threshold_pct, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    alert.metric_name,
                    alert.alert_type,
                    alert.message,
                    alert.current_value,
                    alert.baseline_value,
                    alert.threshold_pct,
                    alert.timestamp.timestamp(),
                ),
            )

    # ── Snapshot & dashboard ────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """Take a full system snapshot — latest value for each metric.

        Returns:
            Dict mapping metric names to their most recent values.
        """
        with self._cursor() as cur:
            cur.execute(
                "SELECT name, value, ts FROM metrics "
                "WHERE id IN ("
                "  SELECT MAX(id) FROM metrics GROUP BY name"
                ") ORDER BY name"
            )
            result: Dict[str, Any] = {}
            for row in cur.fetchall():
                result[row["name"]] = {
                    "value": row["value"],
                    "timestamp": datetime.fromtimestamp(
                        row["ts"], tz=timezone.utc
                    ).isoformat(),
                }
            return result

    def dashboard(self, hours: int = 24) -> str:
        """Generate a markdown dashboard with all metrics and trends.

        Args:
            hours: Look-back window for trend calculation.

        Returns:
            Markdown-formatted dashboard string.
        """
        now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"# System Dashboard — {now_str}", ""]

        sections = [
            ("Knowledge", KNOWLEDGE_METRICS),
            ("Inference", INFERENCE_METRICS),
            ("Tasks", TASK_METRICS),
            ("Tests", TEST_METRICS),
            ("System", SYSTEM_METRICS),
        ]

        for section_name, metric_names in sections:
            lines.append(f"## {section_name}")
            lines.append(
                "| Metric | Current | %dh Trend | 7d Trend |" % hours
            )
            lines.append("|--------|---------|-----------|----------|")

            for name in metric_names:
                current = self._latest_value(name)
                short_trend = self.trend(name, days=int(max(hours / 24, 1)))
                long_trend = self.trend(name, days=7)
                short_arrow = self._trend_arrow(short_trend)
                long_arrow = self._trend_arrow(long_trend)

                if name.endswith("hit_rate"):
                    current_str = "%.1f%%" % (current * 100)
                elif name.endswith("_ms") or name.endswith("_s"):
                    current_str = "%.1f" % current
                else:
                    current_str = "%g" % current

                short_label = name.split(".")[-1]
                lines.append(
                    "| %s | %s | %s | %s |"
                    % (name, current_str, short_arrow, long_arrow)
                )

            lines.append("")

        # Alerts section
        alerts = self.check_regressions()
        if alerts:
            lines.append("## Alerts")
            for a in alerts:
                lines.append("- ⚠️ %s" % a.message)
            lines.append("")
        else:
            lines.append("## Alerts")
            lines.append("- ✅ No regressions detected")
            lines.append("")

        return "\n".join(lines)

    def _latest_value(self, name: str) -> float:
        """Return the most recent value for a metric, or 0."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT value FROM metrics WHERE name = ? "
                "ORDER BY ts DESC LIMIT 1",
                (name,),
            )
            row = cur.fetchone()
            return row["value"] if row else 0.0

    @staticmethod
    def _trend_arrow(trend_data: Dict[str, Any]) -> str:
        """Format a trend dict as a short arrow string."""
        direction = trend_data.get("direction", "stable")
        rate = trend_data.get("rate_of_change", 0.0)
        last = trend_data.get("last", 0.0)
        first = trend_data.get("first", 0.0)
        delta = last - first

        if direction == "up":
            return "+%g ↑" % delta
        elif direction == "down":
            return "%g ↓" % delta
        return "— stable"

    # ── Collection helpers ──────────────────────────────────────────

    def collect_system_metrics(self) -> Dict[str, float]:
        """Collect current system metrics (VRAM, uptime).

        Uses ``nvidia-smi`` for GPU memory; gracefully returns 0 on
        failure.

        Returns:
            Dict of system metric names to values.
        """
        result: Dict[str, float] = {}

        # Uptime
        result["system.uptime_s"] = round(time.monotonic() - _START_TIME, 1)

        # GPU VRAM
        vram = 0.0
        try:
            proc = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                vram = float(proc.stdout.strip().split("\n")[0])
        except Exception:
            logger.debug("nvidia-smi unavailable — VRAM metric set to 0")
        result["system.vram_used_mb"] = vram

        # NLM placeholders — zero unless external collectors update them
        result["nlm.notebooks.active"] = 0.0
        result["nlm.research.sessions"] = 0.0

        return result

    def collect_nexus_metrics(self) -> Dict[str, float]:
        """Collect Nexus knowledge metrics via the Nexus client.

        Gracefully returns zeros if Nexus is unreachable.

        Returns:
            Dict of Nexus metric names to values.
        """
        result: Dict[str, float] = {
            "nexus.entries.total": 0.0,
            "nexus.entries.added": 0.0,
            "nexus.qa.total": 0.0,
            "nexus.qa.cache_hits": 0.0,
            "nexus.quality.average": 0.0,
        }

        try:
            from engine.nexus.client import get_nexus_client

            client = get_nexus_client()
            status = client.status()
            if isinstance(status, dict):
                result["nexus.entries.total"] = float(
                    status.get("total_entries", 0)
                )
                result["nexus.qa.total"] = float(
                    status.get("total_qa", 0)
                )
                result["nexus.qa.cache_hits"] = float(
                    status.get("cache_hits", 0)
                )
                result["nexus.quality.average"] = float(
                    status.get("avg_quality", 0.0)
                )
        except Exception:
            logger.debug("Nexus unreachable — knowledge metrics set to 0")

        return result

    def collect_all(self) -> Dict[str, float]:
        """Collect and record ALL metric categories.

        Returns:
            Dict mapping every collected metric name to its value.
        """
        all_metrics: Dict[str, float] = {}
        all_metrics.update(self.collect_system_metrics())
        all_metrics.update(self.collect_nexus_metrics())

        batch = [(name, value) for name, value in all_metrics.items()]
        if batch:
            self.record_batch(batch)
            logger.info(
                "Collected and recorded %d metrics", len(batch)
            )

        return all_metrics

    # ── Stats ───────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return database statistics.

        Returns:
            Dict with total_points, unique_metrics, date_range (first/last
            ISO timestamps), and total_alerts.
        """
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM metrics")
            total_points = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(DISTINCT name) as cnt FROM metrics")
            unique_metrics = cur.fetchone()["cnt"]

            cur.execute(
                "SELECT MIN(ts) as first_ts, MAX(ts) as last_ts FROM metrics"
            )
            row = cur.fetchone()
            first_ts = row["first_ts"]
            last_ts = row["last_ts"]

            cur.execute("SELECT COUNT(*) as cnt FROM alerts")
            total_alerts = cur.fetchone()["cnt"]

        date_range: Dict[str, Optional[str]] = {
            "first": None,
            "last": None,
        }
        if first_ts is not None:
            date_range["first"] = datetime.fromtimestamp(
                first_ts, tz=timezone.utc
            ).isoformat()
        if last_ts is not None:
            date_range["last"] = datetime.fromtimestamp(
                last_ts, tz=timezone.utc
            ).isoformat()

        return {
            "total_points": total_points,
            "unique_metrics": unique_metrics,
            "date_range": date_range,
            "total_alerts": total_alerts,
        }
