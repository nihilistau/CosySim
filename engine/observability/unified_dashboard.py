"""
UnifiedDashboard — Single API surface for all monitoring data.

Formats and aggregates data from all monitoring subsystems for
dashboard consumption, with time-range queries and real-time streaming.

Usage::

    from engine.observability.unified_dashboard import get_unified_dashboard
    dashboard = get_unified_dashboard()

    # Full dashboard state
    state = dashboard.full_state()

    # Time-range query
    history = dashboard.system_history(hours=4)

    # Widget-specific data
    gauges = dashboard.gauge_data()
    sparklines = dashboard.sparkline_data(metric="cpu_pct", hours=1)
"""
from __future__ import annotations

import logging
import math
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ──── Lazy subsystem imports ────────────────────────────────────────────

try:
    from engine.observability.metrics_db import get_metrics_db
except ImportError:
    get_metrics_db = None  # type: ignore[assignment]

try:
    from engine.observability.metrics_collector import get_metrics_collector
except ImportError:
    get_metrics_collector = None  # type: ignore[assignment]

try:
    from engine.observability.pack_tracker import get_pack_tracker
except ImportError:
    get_pack_tracker = None  # type: ignore[assignment]

try:
    from engine.observability.anomaly_detector import get_anomaly_detector
except ImportError:
    get_anomaly_detector = None  # type: ignore[assignment]

try:
    from engine.observability.trend_predictor import get_trend_predictor
except ImportError:
    get_trend_predictor = None  # type: ignore[assignment]

try:
    from engine.observability.correlation_engine import get_correlation_engine
except ImportError:
    get_correlation_engine = None  # type: ignore[assignment]

try:
    from engine.observability.alert_router import get_alert_router
except ImportError:
    get_alert_router = None  # type: ignore[assignment]


# ──── Data Classes ──────────────────────────────────────────────────────


@dataclass
class TimeRange:
    """A bounded time window for queries."""

    start: float
    end: float
    label: str


@dataclass
class DashboardWidget:
    """Formatted widget payload ready for UI rendering."""

    widget_id: str
    widget_type: str  # gauge, sparkline, table, counter, status_light, bar_chart
    title: str
    data: Any
    updated_at: float = field(default_factory=time.time)


# ──── Constants ─────────────────────────────────────────────────────────

_DIRECTION_ARROWS: Dict[str, str] = {
    "rising": "↑",
    "falling": "↓",
    "stable": "→",
    "volatile": "↕",
}

_HEALTH_WEIGHTS: Dict[str, float] = {
    "system": 0.30,
    "pipeline": 0.30,
    "packs": 0.20,
    "trends": 0.20,
}


# ──── UnifiedDashboard ──────────────────────────────────────────────────


class UnifiedDashboard:
    """Single query surface for all monitoring data.

    Aggregates subsystem data into formatted, time-range-aware
    payloads suitable for dashboard UIs and agent consumers.
    """

    def __init__(self) -> None:
        self._listeners: List[Callable] = []
        self._lock = threading.Lock()
        logger.info("UnifiedDashboard initialised")

    # ──── Subsystem Accessors ───────────────────────────────────────

    def _db(self) -> Any:
        """Get MetricsDB singleton (or None)."""
        return get_metrics_db() if get_metrics_db else None

    def _collector(self) -> Any:
        """Get MetricsCollector singleton (or None)."""
        return get_metrics_collector() if get_metrics_collector else None

    def _packs(self) -> Any:
        """Get PackTracker singleton (or None)."""
        return get_pack_tracker() if get_pack_tracker else None

    def _anomalies(self) -> Any:
        """Get AnomalyDetector singleton (or None)."""
        return get_anomaly_detector() if get_anomaly_detector else None

    def _trends(self) -> Any:
        """Get TrendPredictor singleton (or None)."""
        return get_trend_predictor() if get_trend_predictor else None

    def _correlations(self) -> Any:
        """Get CorrelationEngine singleton (or None)."""
        return get_correlation_engine() if get_correlation_engine else None

    def _router(self) -> Any:
        """Get AlertRouter singleton (or None)."""
        return get_alert_router() if get_alert_router else None

    # ──── Time Helpers ──────────────────────────────────────────────

    def _time_range(
        self, hours: float = 1.0, end: float | None = None
    ) -> TimeRange:
        """Build a TimeRange for the given window.

        Args:
            hours: Window size in hours.
            end: End epoch (defaults to now).

        Returns:
            TimeRange with start, end, and human label.
        """
        end_ts = end if end is not None else time.time()
        start_ts = end_ts - (hours * 3600)
        if hours < 1:
            label = f"Last {int(hours * 60)}m"
        elif hours == 1.0:
            label = "Last 1h"
        elif hours == int(hours):
            label = f"Last {int(hours)}h"
        else:
            label = f"Last {hours:.1f}h"
        return TimeRange(start=start_ts, end=end_ts, label=label)

    def _period_comparison(
        self, hours: float
    ) -> Tuple[TimeRange, TimeRange]:
        """Return current and previous period of equal length.

        Args:
            hours: Window length in hours.

        Returns:
            Tuple of (current_period, previous_period).
        """
        now = time.time()
        current = self._time_range(hours, end=now)
        previous = TimeRange(
            start=now - (hours * 7200),
            end=now - (hours * 3600),
            label=f"Previous {hours:.0f}h" if hours >= 1 else f"Previous {int(hours * 60)}m",
        )
        return current, previous

    # ──── Dashboard State ───────────────────────────────────────────

    def full_state(self) -> Dict[str, Any]:
        """Everything needed for a full dashboard render.

        Returns:
            Dict with health_score, summary_cards, current_values,
            recent_alerts, top_packs, trends, and anomalies.
        """
        now = time.time()
        health = self.health_score()
        collector = self._collector()

        current_values: Dict[str, Any] = {}
        if collector:
            current_values["system"] = dict(collector.last_system_snapshot)
            current_values["pipeline"] = dict(collector.last_pipeline_summary)

        return {
            "ts": now,
            "health": health,
            "summary_cards": self._summary_cards(health),
            "current_values": current_values,
            "recent_alerts": self.alert_feed(hours=1.0),
            "top_packs": self.pack_leaderboard(n=5),
            "trends": self.trend_overview(),
            "anomalies": self.anomaly_feed(hours=1.0),
            "active_issues": self.active_issues(),
        }

    def _summary_cards(self, health: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build summary cards from health data.

        Args:
            health: Output of health_score().

        Returns:
            List of card dicts for the dashboard header.
        """
        cards: List[Dict[str, Any]] = [
            {
                "id": "health",
                "title": "Health Score",
                "value": health.get("score", 0),
                "unit": "/100",
                "status": health.get("status", "unknown"),
            },
        ]

        breakdown = health.get("breakdown", {})
        for key in ("system", "pipeline", "packs", "trends"):
            sub = breakdown.get(key, {})
            cards.append({
                "id": f"health_{key}",
                "title": f"{key.title()} Health",
                "value": sub.get("score", 0),
                "unit": "/100",
                "status": sub.get("status", "unknown"),
            })

        return cards

    def health_score(self) -> Dict[str, Any]:
        """Composite health score 0-100 with subsystem breakdown.

        Returns:
            Dict with score, status, and per-subsystem breakdown
            for system, pipeline, packs, and trends.
        """
        breakdown: Dict[str, Dict[str, Any]] = {}

        # ── System health (CPU/RAM/GPU) ──
        sys_score = 100.0
        collector = self._collector()
        if collector:
            snap = collector.last_system_snapshot
            cpu = snap.get("cpu_pct", 0.0)
            ram = snap.get("ram_pct", 0.0)
            gpu = snap.get("gpu_vram_pct", 0.0)
            # Penalise proportionally above 70%
            for val in (cpu, ram, gpu):
                if val > 90:
                    sys_score -= 15
                elif val > 80:
                    sys_score -= 8
                elif val > 70:
                    sys_score -= 3
        sys_score = max(0.0, sys_score)
        breakdown["system"] = {
            "score": round(sys_score),
            "status": self._score_status(sys_score),
        }

        # ── Pipeline health (latency/errors) ──
        pipe_score = 100.0
        db = self._db()
        if db:
            try:
                summary = db.get_pipeline_summary(seconds=300)
                avg_lat = summary.get("avg_latency") or 0.0
                total = summary.get("total") or 0
                kills = summary.get("total_kills") or 0
                if avg_lat > 2000:
                    pipe_score -= 30
                elif avg_lat > 1000:
                    pipe_score -= 15
                elif avg_lat > 500:
                    pipe_score -= 5
                if total > 0:
                    kill_rate = kills / total
                    if kill_rate > 0.3:
                        pipe_score -= 30
                    elif kill_rate > 0.1:
                        pipe_score -= 15
                    elif kill_rate > 0.05:
                        pipe_score -= 5
            except Exception as exc:
                logger.debug("Pipeline health check failed: %s", exc)
        pipe_score = max(0.0, pipe_score)
        breakdown["pipeline"] = {
            "score": round(pipe_score),
            "status": self._score_status(pipe_score),
        }

        # ── Pack health (failure rates) ──
        pack_score = 100.0
        packs = self._packs()
        if packs:
            try:
                pack_data = packs.pack_summary(hours=1.0)
                for activity in pack_data.values():
                    total_calls = activity.total_calls
                    if total_calls > 0:
                        err_rate = activity.error_count / total_calls
                        if err_rate > 0.5:
                            pack_score -= 20
                        elif err_rate > 0.2:
                            pack_score -= 10
                        elif err_rate > 0.1:
                            pack_score -= 5
            except Exception as exc:
                logger.debug("Pack health check failed: %s", exc)
        pack_score = max(0.0, pack_score)
        breakdown["packs"] = {
            "score": round(pack_score),
            "status": self._score_status(pack_score),
        }

        # ── Trend health (degradation count) ──
        trend_score = 100.0
        trends = self._trends()
        if trends:
            try:
                critical = trends.critical_trends()
                rising = trends.rising_metrics()
                trend_score -= len(critical) * 20
                trend_score -= len(rising) * 5
            except Exception as exc:
                logger.debug("Trend health check failed: %s", exc)
        trend_score = max(0.0, trend_score)
        breakdown["trends"] = {
            "score": round(trend_score),
            "status": self._score_status(trend_score),
        }

        # ── Weighted composite ──
        composite = sum(
            breakdown[k]["score"] * _HEALTH_WEIGHTS[k]
            for k in _HEALTH_WEIGHTS
        )
        composite = round(min(100.0, max(0.0, composite)))

        return {
            "score": composite,
            "status": self._score_status(composite),
            "breakdown": breakdown,
            "ts": time.time(),
        }

    @staticmethod
    def _score_status(score: float) -> str:
        """Map a numeric score to a status label."""
        if score >= 80:
            return "healthy"
        if score >= 50:
            return "degraded"
        return "critical"

    # ──── System Metrics ────────────────────────────────────────────

    def system_history(self, hours: float = 1.0) -> Dict[str, Any]:
        """Time-series for CPU, RAM, GPU over the requested period.

        Args:
            hours: Window size in hours.

        Returns:
            Dict keyed by metric name, each containing a list of
            ``(timestamp, value)`` tuples, plus range metadata.
        """
        tr = self._time_range(hours)
        db = self._db()
        series: Dict[str, List[Tuple[float, float]]] = {
            "cpu_pct": [],
            "ram_pct": [],
            "gpu_vram_pct": [],
            "gpu_temp_c": [],
        }
        if db:
            try:
                rows = db.get_system_history(seconds=hours * 3600)
                for row in rows:
                    ts = row.get("ts", 0.0)
                    for key in series:
                        val = row.get(key)
                        if val is not None:
                            series[key].append((ts, val))
            except Exception as exc:
                logger.warning("system_history query failed: %s", exc)

        return {
            "range": {"start": tr.start, "end": tr.end, "label": tr.label},
            **series,
        }

    def gauge_data(self) -> List[DashboardWidget]:
        """Current values formatted as gauge widgets.

        Returns:
            List of DashboardWidget with widget_type='gauge' for
            CPU%, RAM%, GPU VRAM%, GPU temp, and LMStudio status.
        """
        collector = self._collector()
        snap = collector.last_system_snapshot if collector else {}
        now = time.time()

        gauges: List[DashboardWidget] = []
        gauge_defs = [
            ("cpu_pct", "CPU Usage", "%", 100),
            ("ram_pct", "RAM Usage", "%", 100),
            ("gpu_vram_pct", "GPU VRAM", "%", 100),
            ("gpu_temp_c", "GPU Temp", "°C", 100),
        ]
        for metric, title, unit, max_val in gauge_defs:
            value = snap.get(metric, 0.0)
            gauges.append(DashboardWidget(
                widget_id=f"gauge_{metric}",
                widget_type="gauge",
                title=title,
                data={
                    "value": round(value, 1),
                    "max": max_val,
                    "unit": unit,
                    "status": self._gauge_status(value, max_val),
                },
                updated_at=now,
            ))

        # Disk usage via process snapshot
        proc_snap = collector.last_process_snapshot if collector else {}
        disk_pct = proc_snap.get("disk_pct", 0.0)
        gauges.append(DashboardWidget(
            widget_id="gauge_disk_pct",
            widget_type="gauge",
            title="Disk Usage",
            data={
                "value": round(disk_pct, 1),
                "max": 100,
                "unit": "%",
                "status": self._gauge_status(disk_pct, 100),
            },
            updated_at=now,
        ))

        return gauges

    @staticmethod
    def _gauge_status(value: float, max_val: float) -> str:
        """Derive RAG status for a gauge value."""
        ratio = value / max_val if max_val else 0
        if ratio >= 0.90:
            return "red"
        if ratio >= 0.75:
            return "yellow"
        return "green"

    def sparkline_data(
        self, metric: str, hours: float = 1.0, points: int = 60
    ) -> DashboardWidget:
        """Downsampled time-series for sparkline rendering.

        Args:
            metric: Column name (e.g. ``cpu_pct``, ``ram_pct``).
            hours: Window size in hours.
            points: Target number of data points.

        Returns:
            DashboardWidget with widget_type='sparkline' and
            downsampled values list.
        """
        tr = self._time_range(hours)
        raw_values: List[Tuple[float, float]] = []
        db = self._db()
        if db:
            try:
                rows = db.get_system_history(seconds=hours * 3600)
                for row in rows:
                    val = row.get(metric)
                    if val is not None:
                        raw_values.append((row["ts"], val))
            except Exception as exc:
                logger.warning("sparkline_data query failed: %s", exc)

        downsampled = self._downsample(raw_values, points)

        current = downsampled[-1][1] if downsampled else 0.0
        min_val = min((v for _, v in downsampled), default=0.0)
        max_val = max((v for _, v in downsampled), default=0.0)

        return DashboardWidget(
            widget_id=f"sparkline_{metric}",
            widget_type="sparkline",
            title=metric.replace("_", " ").title(),
            data={
                "metric": metric,
                "values": [round(v, 2) for _, v in downsampled],
                "timestamps": [t for t, _ in downsampled],
                "current": round(current, 2),
                "min": round(min_val, 2),
                "max": round(max_val, 2),
                "points": len(downsampled),
                "range": {"start": tr.start, "end": tr.end, "label": tr.label},
            },
        )

    @staticmethod
    def _downsample(
        data: List[Tuple[float, float]], target: int
    ) -> List[Tuple[float, float]]:
        """Reduce data points to target count via bucket averaging.

        Args:
            data: List of (timestamp, value) tuples sorted by time.
            target: Desired number of output points.

        Returns:
            Downsampled list of (timestamp, value) tuples.
        """
        if len(data) <= target or target <= 0:
            return list(data)
        bucket_size = len(data) / target
        result: List[Tuple[float, float]] = []
        for i in range(target):
            start_idx = int(i * bucket_size)
            end_idx = int((i + 1) * bucket_size)
            bucket = data[start_idx:end_idx]
            if bucket:
                avg_ts = sum(t for t, _ in bucket) / len(bucket)
                avg_val = sum(v for _, v in bucket) / len(bucket)
                result.append((avg_ts, avg_val))
        return result

    # ──── Pipeline Metrics ──────────────────────────────────────────

    def pipeline_summary(self, hours: float = 1.0) -> Dict[str, Any]:
        """Aggregated pipeline statistics over the requested period.

        Args:
            hours: Window size in hours.

        Returns:
            Dict with avg_latency, p50/p95/p99, throughput, error_rate,
            and token usage stats.
        """
        tr = self._time_range(hours)
        db = self._db()
        result: Dict[str, Any] = {
            "range": {"start": tr.start, "end": tr.end, "label": tr.label},
            "total_requests": 0,
            "avg_latency_ms": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "p99_latency_ms": 0.0,
            "throughput_rpm": 0.0,
            "error_rate": 0.0,
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "avg_tps": 0.0,
        }
        if not db:
            return result

        try:
            with db._cursor() as cur:
                cur.execute(
                    "SELECT latency_ms, tokens_in, tokens_out, tps, kill_fired "
                    "FROM pipeline_metrics WHERE ts > ? AND ts <= ? ORDER BY latency_ms",
                    (tr.start, tr.end),
                )
                rows = cur.fetchall()
        except Exception as exc:
            logger.warning("pipeline_summary query failed: %s", exc)
            return result

        if not rows:
            return result

        latencies = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
        tokens_in = [r["tokens_in"] or 0 for r in rows]
        tokens_out = [r["tokens_out"] or 0 for r in rows]
        tps_vals = [r["tps"] for r in rows if r["tps"] is not None]
        kills = sum(1 for r in rows if r["kill_fired"])
        total = len(rows)
        window_minutes = max((tr.end - tr.start) / 60, 1)

        result["total_requests"] = total
        result["throughput_rpm"] = round(total / window_minutes, 2)
        result["error_rate"] = round(kills / total, 4) if total else 0.0
        result["total_tokens_in"] = sum(tokens_in)
        result["total_tokens_out"] = sum(tokens_out)

        if latencies:
            latencies.sort()
            result["avg_latency_ms"] = round(statistics.mean(latencies), 2)
            result["p50_latency_ms"] = round(self._percentile(latencies, 50), 2)
            result["p95_latency_ms"] = round(self._percentile(latencies, 95), 2)
            result["p99_latency_ms"] = round(self._percentile(latencies, 99), 2)

        if tps_vals:
            result["avg_tps"] = round(statistics.mean(tps_vals), 2)

        return result

    def pipeline_history(self, hours: float = 1.0) -> Dict[str, Any]:
        """Time-series for pipeline latency, tokens, and throughput.

        Args:
            hours: Window size in hours.

        Returns:
            Dict with per-metric time-series lists and range metadata.
        """
        tr = self._time_range(hours)
        series: Dict[str, List[Tuple[float, float]]] = {
            "latency_ms": [],
            "tokens_in": [],
            "tokens_out": [],
            "tps": [],
        }
        db = self._db()
        if db:
            try:
                rows = db.get_pipeline_history(seconds=hours * 3600)
                for row in rows:
                    ts = row.get("ts", 0.0)
                    for key in series:
                        val = row.get(key)
                        if val is not None:
                            series[key].append((ts, val))
            except Exception as exc:
                logger.warning("pipeline_history query failed: %s", exc)

        return {
            "range": {"start": tr.start, "end": tr.end, "label": tr.label},
            **series,
        }

    def model_breakdown(self, hours: float = 1.0) -> List[Dict[str, Any]]:
        """Per-model metrics breakdown over the requested period.

        Args:
            hours: Window size in hours.

        Returns:
            List of dicts with model name, call count, avg latency,
            avg TPS, and token totals.
        """
        tr = self._time_range(hours)
        db = self._db()
        if not db:
            return []

        try:
            with db._cursor() as cur:
                cur.execute(
                    "SELECT model, "
                    "  COUNT(*) as calls, "
                    "  AVG(latency_ms) as avg_latency, "
                    "  AVG(tps) as avg_tps, "
                    "  SUM(tokens_in) as total_tokens_in, "
                    "  SUM(tokens_out) as total_tokens_out, "
                    "  SUM(kill_fired) as kills "
                    "FROM pipeline_metrics "
                    "WHERE ts > ? AND ts <= ? AND model IS NOT NULL "
                    "GROUP BY model ORDER BY calls DESC",
                    (tr.start, tr.end),
                )
                rows = cur.fetchall()
        except Exception as exc:
            logger.warning("model_breakdown query failed: %s", exc)
            return []

        return [
            {
                "model": row["model"],
                "calls": row["calls"],
                "avg_latency_ms": round(row["avg_latency"] or 0, 2),
                "avg_tps": round(row["avg_tps"] or 0, 2),
                "total_tokens_in": row["total_tokens_in"] or 0,
                "total_tokens_out": row["total_tokens_out"] or 0,
                "error_rate": round(
                    (row["kills"] or 0) / row["calls"], 4
                ) if row["calls"] else 0.0,
            }
            for row in rows
        ]

    # ──── Pack Activity ─────────────────────────────────────────────

    def pack_activity(self, hours: float = 1.0) -> Dict[str, Any]:
        """Pack execution statistics over the requested period.

        Args:
            hours: Window size in hours.

        Returns:
            Dict with total executions, CPU time, failure rates,
            top skills, and per-pack summary.
        """
        tr = self._time_range(hours)
        packs = self._packs()
        if not packs:
            return {
                "range": {"start": tr.start, "end": tr.end, "label": tr.label},
                "total_executions": 0,
                "packs": {},
            }

        try:
            summary = packs.pack_summary(hours=hours)
        except Exception as exc:
            logger.warning("pack_activity query failed: %s", exc)
            return {
                "range": {"start": tr.start, "end": tr.end, "label": tr.label},
                "total_executions": 0,
                "packs": {},
            }

        total_exec = 0
        total_cpu = 0.0
        total_errors = 0
        all_skills: Dict[str, int] = {}
        pack_list: Dict[str, Dict[str, Any]] = {}

        for name, activity in summary.items():
            total_exec += activity.total_calls
            total_cpu += activity.total_cpu_seconds
            total_errors += activity.error_count
            for skill, count in activity.skills_used.items():
                all_skills[skill] = all_skills.get(skill, 0) + count
            pack_list[name] = activity.to_dict()

        top_skills = sorted(
            all_skills.items(), key=lambda x: x[1], reverse=True
        )[:10]

        return {
            "range": {"start": tr.start, "end": tr.end, "label": tr.label},
            "total_executions": total_exec,
            "total_cpu_seconds": round(total_cpu, 3),
            "total_errors": total_errors,
            "error_rate": round(total_errors / total_exec, 4) if total_exec else 0.0,
            "top_skills": [{"skill": s, "calls": c} for s, c in top_skills],
            "packs": pack_list,
        }

    def pack_leaderboard(self, n: int = 10) -> List[Dict[str, Any]]:
        """Top packs ranked by various criteria.

        Args:
            n: Number of top packs to return.

        Returns:
            List of dicts with pack name and metrics, sorted by CPU time.
        """
        packs = self._packs()
        if not packs:
            return []
        try:
            return packs.top_packs(n=n, sort_by="cpu")
        except Exception as exc:
            logger.warning("pack_leaderboard query failed: %s", exc)
            return []

    def pack_timeline(
        self, pack: str, hours: float = 1.0
    ) -> List[Dict[str, Any]]:
        """Execution timeline for a single pack.

        Args:
            pack: Pack name to query.
            hours: Window size in hours.

        Returns:
            List of execution dicts with timestamp, skill, duration,
            success, and resource usage.
        """
        db = self._db()
        if not db:
            return []

        tr = self._time_range(hours)
        try:
            with db._cursor() as cur:
                cur.execute(
                    "SELECT ts, skill_name, duration_s, cpu_delta_s, memory_mb, "
                    "       success, error "
                    "FROM pack_executions "
                    "WHERE pack = ? AND ts > ? AND ts <= ? "
                    "ORDER BY ts DESC",
                    (pack, tr.start, tr.end),
                )
                rows = cur.fetchall()
        except Exception as exc:
            logger.warning("pack_timeline query failed: %s", exc)
            return []

        return [
            {
                "ts": row["ts"],
                "skill": row["skill_name"],
                "duration_s": round(row["duration_s"], 4),
                "cpu_seconds": round(row["cpu_delta_s"] or 0, 4),
                "memory_mb": round(row["memory_mb"] or 0, 1),
                "success": bool(row["success"]),
                "error": row["error"] or "",
            }
            for row in rows
        ]

    # ──── Anomalies & Alerts ────────────────────────────────────────

    def anomaly_feed(self, hours: float = 1.0) -> List[Dict[str, Any]]:
        """Recent anomalies with context over the requested period.

        Args:
            hours: Window size in hours.

        Returns:
            List of anomaly dicts sorted by timestamp descending.
        """
        detector = self._anomalies()
        if not detector:
            return []

        try:
            anomalies = detector.recent_anomalies(n=100)
        except Exception as exc:
            logger.warning("anomaly_feed query failed: %s", exc)
            return []

        cutoff = time.time() - (hours * 3600)
        return [
            a for a in anomalies
            if a.get("timestamp", a.get("ts", 0)) >= cutoff
        ]

    def alert_feed(self, hours: float = 1.0) -> List[Dict[str, Any]]:
        """Recent alerts with routing info over the requested period.

        Args:
            hours: Window size in hours.

        Returns:
            List of alert dicts with routing channel information.
        """
        router = self._router()
        if not router:
            # Fall back to raw DB alerts
            db = self._db()
            if not db:
                return []
            try:
                alerts = db.get_recent_alerts(limit=100)
                cutoff = time.time() - (hours * 3600)
                return [a for a in alerts if a.get("ts", 0) >= cutoff]
            except Exception as exc:
                logger.warning("alert_feed DB fallback failed: %s", exc)
                return []

        try:
            routed = router.recent_routed(n=100)
            cutoff = time.time() - (hours * 3600)
            return [a for a in routed if a.get("ts", 0) >= cutoff]
        except Exception as exc:
            logger.warning("alert_feed query failed: %s", exc)
            return []

    def active_issues(self) -> List[Dict[str, Any]]:
        """Currently active (unresolved) issues across all subsystems.

        Returns:
            List of issue dicts combining unacknowledged alerts,
            critical trends, and active anomalies.
        """
        issues: List[Dict[str, Any]] = []

        # Unacknowledged escalation alerts
        router = self._router()
        if router:
            try:
                for esc in router.escalation_check():
                    issues.append({
                        "type": "alert",
                        "severity": esc.get("severity", "unknown"),
                        "node": esc.get("node", ""),
                        "metric": esc.get("metric", ""),
                        "message": esc.get("message", ""),
                        "age_seconds": esc.get("age_seconds", 0),
                        "ts": esc.get("ts", 0),
                    })
            except Exception as exc:
                logger.debug("active_issues alert check failed: %s", exc)

        # Critical trends
        trends = self._trends()
        if trends:
            try:
                for t in trends.critical_trends():
                    td = t.to_dict() if hasattr(t, "to_dict") else {}
                    issues.append({
                        "type": "trend",
                        "severity": "critical",
                        "node": td.get("metric_key", ""),
                        "metric": td.get("metric_key", ""),
                        "message": (
                            f"{td.get('metric_key', '?')} trending "
                            f"{td.get('direction', '?')}, predicted "
                            f"{td.get('predicted_1h', 0):.1f} in 1h"
                        ),
                        "ts": td.get("ts", 0),
                    })
            except Exception as exc:
                logger.debug("active_issues trend check failed: %s", exc)

        # Recent high/critical anomalies (last 15 minutes)
        detector = self._anomalies()
        if detector:
            try:
                cutoff = time.time() - 900
                for a in detector.recent_anomalies(n=50):
                    ts = a.get("timestamp", a.get("ts", 0))
                    sev = a.get("severity", "low")
                    if ts >= cutoff and sev in ("high", "critical", "HIGH", "CRITICAL"):
                        issues.append({
                            "type": "anomaly",
                            "severity": sev.lower(),
                            "node": a.get("node", ""),
                            "metric": a.get("metric", ""),
                            "message": a.get("message", ""),
                            "ts": ts,
                        })
            except Exception as exc:
                logger.debug("active_issues anomaly check failed: %s", exc)

        issues.sort(key=lambda x: x.get("ts", 0), reverse=True)
        return issues

    # ──── Trends & Predictions ──────────────────────────────────────

    def trend_overview(self) -> List[Dict[str, Any]]:
        """All trends with direction arrows and predicted values.

        Returns:
            List of trend dicts with human-readable direction arrows,
            current/predicted values, and severity.
        """
        predictor = self._trends()
        if not predictor:
            return []

        try:
            all_trends = predictor.all_trends()
        except Exception as exc:
            logger.warning("trend_overview query failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for t in all_trends:
            td = t.to_dict() if hasattr(t, "to_dict") else {}
            direction = td.get("direction", "stable")
            arrow = _DIRECTION_ARROWS.get(direction, "?")
            results.append({
                "metric": td.get("metric_key", ""),
                "direction": direction,
                "arrow": arrow,
                "current": round(td.get("current_value", 0), 2),
                "predicted_1h": round(td.get("predicted_1h", 0), 2),
                "predicted_4h": round(td.get("predicted_4h", 0), 2),
                "predicted_24h": round(td.get("predicted_24h", 0), 2),
                "r_squared": round(td.get("r_squared", 0), 3),
                "severity": td.get("severity", "none"),
                "slope": td.get("slope", 0),
            })
        return results

    def capacity_forecast(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Resource capacity projections over the forecast horizon.

        Args:
            hours: Forecast horizon in hours.

        Returns:
            List of dicts with metric, current value, predicted value,
            threshold, and estimated minutes to capacity limit.
        """
        predictor = self._trends()
        if not predictor:
            return []

        try:
            warnings = predictor.capacity_warnings(horizon_minutes=hours * 60)
            return [
                {
                    "metric": w.get("metric", ""),
                    "current": round(w.get("current", 0), 2),
                    "predicted": round(w.get("predicted", 0), 2),
                    "threshold": w.get("threshold", 0),
                    "minutes_to_limit": round(w.get("minutes_to_limit", 0), 1),
                    "hours_to_limit": round(w.get("minutes_to_limit", 0) / 60, 1),
                    "urgency": (
                        "critical" if w.get("minutes_to_limit", 999) < 60
                        else "warning" if w.get("minutes_to_limit", 999) < 240
                        else "info"
                    ),
                }
                for w in warnings
            ]
        except Exception as exc:
            logger.warning("capacity_forecast query failed: %s", exc)
            return []

    # ──── Correlations ──────────────────────────────────────────────

    def correlation_insights(self) -> List[Dict[str, Any]]:
        """Strong correlations formatted as human-readable insights.

        Returns:
            List of insight dicts with natural-language description,
            correlation coefficient, and metric pair.
        """
        engine = self._correlations()
        if not engine:
            return []

        try:
            strong = engine.strongest_correlations(hours=24.0, n=20)
        except Exception as exc:
            logger.warning("correlation_insights query failed: %s", exc)
            return []

        insights: List[Dict[str, Any]] = []
        for c in strong:
            r = c.get("pearson_r", 0)
            a = c.get("metric_a", "?")
            b = c.get("metric_b", "?")
            direction = "positively" if r > 0 else "negatively"
            abs_r = abs(r)

            readable_a = a.replace(".", " → ").replace("_", " ")
            readable_b = b.replace(".", " → ").replace("_", " ")

            if abs_r >= 0.8:
                strength = "strongly"
            elif abs_r >= 0.5:
                strength = "moderately"
            else:
                strength = "weakly"

            insight_text = (
                f"{readable_a} {strength} {direction} correlates "
                f"with {readable_b} (r={r:.2f})"
            )

            insights.append({
                "insight": insight_text,
                "metric_a": a,
                "metric_b": b,
                "pearson_r": round(r, 3),
                "strength": c.get("strength", ""),
                "direction": c.get("direction", ""),
                "sample_count": c.get("sample_count", 0),
            })

        return insights

    # ──── Comparison ────────────────────────────────────────────────

    def comparison(self, hours: float = 1.0) -> Dict[str, Any]:
        """Current period vs previous period with delta percentages.

        Args:
            hours: Window size in hours for each period.

        Returns:
            Dict with current and previous period summaries for
            system and pipeline metrics, plus delta percentages.
        """
        current_range, prev_range = self._period_comparison(hours)
        db = self._db()

        result: Dict[str, Any] = {
            "current_range": {
                "start": current_range.start,
                "end": current_range.end,
                "label": current_range.label,
            },
            "previous_range": {
                "start": prev_range.start,
                "end": prev_range.end,
                "label": prev_range.label,
            },
            "system": {},
            "pipeline": {},
        }

        if not db:
            return result

        # ── System metrics comparison ──
        for metric in ("cpu_pct", "ram_pct", "gpu_vram_pct"):
            cur_avg = self._avg_system_metric(db, metric, current_range)
            prev_avg = self._avg_system_metric(db, metric, prev_range)
            delta = self._delta_pct(cur_avg, prev_avg)
            result["system"][metric] = {
                "current": round(cur_avg, 2),
                "previous": round(prev_avg, 2),
                "delta_pct": delta,
                "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
            }

        # ── Pipeline metrics comparison ──
        cur_pipe = self._pipeline_stats_for_range(db, current_range)
        prev_pipe = self._pipeline_stats_for_range(db, prev_range)

        for key in ("avg_latency_ms", "throughput_rpm", "error_rate", "avg_tps"):
            cur_val = cur_pipe.get(key, 0.0)
            prev_val = prev_pipe.get(key, 0.0)
            delta = self._delta_pct(cur_val, prev_val)
            result["pipeline"][key] = {
                "current": round(cur_val, 2),
                "previous": round(prev_val, 2),
                "delta_pct": delta,
                "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
            }

        return result

    def _avg_system_metric(
        self, db: Any, metric: str, tr: TimeRange
    ) -> float:
        """Compute average of a system metric over a time range.

        Args:
            db: MetricsDB instance.
            metric: Column name.
            tr: TimeRange to query.

        Returns:
            Average value, or 0.0 if no data.
        """
        try:
            with db._cursor() as cur:
                cur.execute(
                    f"SELECT AVG({metric}) as avg_val "
                    "FROM system_metrics WHERE ts > ? AND ts <= ?",
                    (tr.start, tr.end),
                )
                row = cur.fetchone()
                return float(row["avg_val"]) if row and row["avg_val"] is not None else 0.0
        except Exception:
            return 0.0

    def _pipeline_stats_for_range(
        self, db: Any, tr: TimeRange
    ) -> Dict[str, float]:
        """Compute pipeline stats over a specific time range.

        Args:
            db: MetricsDB instance.
            tr: TimeRange to query.

        Returns:
            Dict with avg_latency_ms, throughput_rpm, error_rate, avg_tps.
        """
        try:
            with db._cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) as total, "
                    "  AVG(latency_ms) as avg_lat, "
                    "  AVG(tps) as avg_tps, "
                    "  SUM(kill_fired) as kills "
                    "FROM pipeline_metrics WHERE ts > ? AND ts <= ?",
                    (tr.start, tr.end),
                )
                row = cur.fetchone()
                if not row or not row["total"]:
                    return {}
                total = row["total"]
                window_minutes = max((tr.end - tr.start) / 60, 1)
                return {
                    "avg_latency_ms": float(row["avg_lat"] or 0),
                    "throughput_rpm": total / window_minutes,
                    "error_rate": (row["kills"] or 0) / total if total else 0,
                    "avg_tps": float(row["avg_tps"] or 0),
                }
        except Exception:
            return {}

    @staticmethod
    def _delta_pct(current: float, previous: float) -> float:
        """Compute percentage change between two values.

        Args:
            current: Current period value.
            previous: Previous period value.

        Returns:
            Percentage change rounded to 1 decimal.
            Returns 0.0 if previous is zero.
        """
        if previous == 0:
            return 0.0
        return round(((current - previous) / abs(previous)) * 100, 1)

    @staticmethod
    def _percentile(sorted_data: List[float], pct: int) -> float:
        """Compute percentile from pre-sorted data.

        Args:
            sorted_data: Sorted list of numeric values.
            pct: Percentile (0-100).

        Returns:
            Interpolated percentile value.
        """
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * (pct / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)

    # ──── Event Streaming ───────────────────────────────────────────

    def register_listener(self, callback: Callable) -> None:
        """Register a callback for real-time dashboard events.

        Args:
            callback: Callable receiving (event_type: str, data: dict).
        """
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)
                logger.debug(
                    "Registered dashboard listener (%d total)",
                    len(self._listeners),
                )

    def unregister_listener(self, callback: Callable) -> None:
        """Remove a previously registered listener.

        Args:
            callback: The callback to remove.
        """
        with self._lock:
            try:
                self._listeners.remove(callback)
                logger.debug(
                    "Unregistered dashboard listener (%d remaining)",
                    len(self._listeners),
                )
            except ValueError:
                pass

    def _notify_listeners(self, event_type: str, data: Dict[str, Any]) -> None:
        """Notify all registered listeners of a dashboard event.

        Args:
            event_type: Event category (e.g. 'alert', 'metric', 'anomaly').
            data: Event payload dict.
        """
        with self._lock:
            listeners = list(self._listeners)

        for cb in listeners:
            try:
                cb(event_type, data)
            except Exception as exc:
                logger.warning(
                    "Dashboard listener %s raised: %s", cb, exc
                )


# ──── Singleton ─────────────────────────────────────────────────────────

_instance: Optional[UnifiedDashboard] = None
_lock = threading.Lock()


def get_unified_dashboard(**kwargs: Any) -> UnifiedDashboard:
    """Get or create the singleton UnifiedDashboard.

    Returns:
        The shared UnifiedDashboard instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = UnifiedDashboard(**kwargs)
    return _instance
