"""Tests for engine.observability.unified_dashboard."""

import math
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.observability.unified_dashboard import (
    DashboardWidget,
    TimeRange,
    UnifiedDashboard,
)


# ──── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the singleton between tests."""
    import engine.observability.unified_dashboard as mod
    mod._instance = None
    yield
    mod._instance = None


@pytest.fixture
def dashboard():
    """Return a fresh UnifiedDashboard with all subsystems mocked to None."""
    d = UnifiedDashboard()
    return d


@pytest.fixture
def mock_db():
    """MetricsDB mock with cursor context manager."""
    db = MagicMock()
    cursor = MagicMock()
    db._cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    db._cursor.return_value.__exit__ = MagicMock(return_value=False)
    return db, cursor


# ──── Dataclass Tests ───────────────────────────────────────────────────


class TestTimeRange:
    def test_fields(self):
        """TimeRange stores start, end, label."""
        tr = TimeRange(start=100.0, end=200.0, label="Last 1h")
        assert tr.start == 100.0
        assert tr.end == 200.0
        assert tr.label == "Last 1h"


class TestDashboardWidget:
    def test_fields(self):
        """DashboardWidget stores widget_id, widget_type, title, data."""
        w = DashboardWidget(
            widget_id="gauge_cpu",
            widget_type="gauge",
            title="CPU Usage",
            data={"value": 42.0},
        )
        assert w.widget_id == "gauge_cpu"
        assert w.widget_type == "gauge"
        assert w.title == "CPU Usage"
        assert w.data["value"] == 42.0
        assert isinstance(w.updated_at, float)

    def test_updated_at_defaults_to_now(self):
        """updated_at field defaults to current time."""
        before = time.time()
        w = DashboardWidget(
            widget_id="x", widget_type="y", title="z", data={}
        )
        after = time.time()
        assert before <= w.updated_at <= after


# ──── Time Helpers ──────────────────────────────────────────────────────


class TestTimeHelpers:
    def test_time_range_one_hour(self, dashboard):
        """Default 1h range."""
        now = time.time()
        tr = dashboard._time_range(1.0, end=now)
        assert tr.label == "Last 1h"
        assert abs(tr.end - now) < 1
        assert abs((tr.end - tr.start) - 3600) < 1

    def test_time_range_minutes(self, dashboard):
        """Sub-hour range shows minutes."""
        tr = dashboard._time_range(0.5)
        assert tr.label == "Last 30m"

    def test_time_range_multi_hour(self, dashboard):
        """Multi-hour integer range."""
        tr = dashboard._time_range(4.0)
        assert tr.label == "Last 4h"

    def test_time_range_fractional_hour(self, dashboard):
        """Fractional hour shows decimal."""
        tr = dashboard._time_range(1.5)
        assert tr.label == "Last 1.5h"

    def test_period_comparison(self, dashboard):
        """Previous period is immediately before current."""
        now = time.time()
        with patch("time.time", return_value=now):
            current, previous = dashboard._period_comparison(1.0)

        assert abs(current.end - now) < 1
        assert abs(current.start - (now - 3600)) < 1
        assert abs(previous.end - (now - 3600)) < 1
        assert abs(previous.start - (now - 7200)) < 1


# ──── Score Status ──────────────────────────────────────────────────────


class TestScoreStatus:
    def test_healthy(self):
        assert UnifiedDashboard._score_status(80) == "healthy"
        assert UnifiedDashboard._score_status(100) == "healthy"

    def test_degraded(self):
        assert UnifiedDashboard._score_status(50) == "degraded"
        assert UnifiedDashboard._score_status(79) == "degraded"

    def test_critical(self):
        assert UnifiedDashboard._score_status(0) == "critical"
        assert UnifiedDashboard._score_status(49) == "critical"


# ──── Gauge Status ──────────────────────────────────────────────────────


class TestGaugeStatus:
    def test_green(self):
        assert UnifiedDashboard._gauge_status(50, 100) == "green"

    def test_yellow(self):
        assert UnifiedDashboard._gauge_status(80, 100) == "yellow"

    def test_red(self):
        assert UnifiedDashboard._gauge_status(95, 100) == "red"

    def test_zero_max(self):
        """Zero max should not divide by zero."""
        assert UnifiedDashboard._gauge_status(0, 0) == "green"


# ──── Downsample ────────────────────────────────────────────────────────


class TestDownsample:
    def test_returns_all_when_under_target(self):
        data = [(1.0, 10.0), (2.0, 20.0)]
        result = UnifiedDashboard._downsample(data, 5)
        assert len(result) == 2

    def test_downsamples_to_target(self):
        data = [(float(i), float(i * 10)) for i in range(100)]
        result = UnifiedDashboard._downsample(data, 10)
        assert len(result) == 10

    def test_empty_input(self):
        assert UnifiedDashboard._downsample([], 10) == []

    def test_zero_target(self):
        data = [(1.0, 10.0)]
        assert UnifiedDashboard._downsample(data, 0) == [(1.0, 10.0)]


# ──── Percentile ────────────────────────────────────────────────────────


class TestPercentile:
    def test_p50_odd_count(self):
        data = [10.0, 20.0, 30.0]
        assert UnifiedDashboard._percentile(data, 50) == 20.0

    def test_p99_single(self):
        assert UnifiedDashboard._percentile([42.0], 99) == 42.0

    def test_empty(self):
        assert UnifiedDashboard._percentile([], 50) == 0.0

    def test_p95_many(self):
        data = list(range(1, 101))
        p95 = UnifiedDashboard._percentile(data, 95)
        assert 94 <= p95 <= 96


# ──── Delta Percentage ──────────────────────────────────────────────────


class TestDeltaPct:
    def test_increase(self):
        assert UnifiedDashboard._delta_pct(150, 100) == 50.0

    def test_decrease(self):
        assert UnifiedDashboard._delta_pct(50, 100) == -50.0

    def test_no_change(self):
        assert UnifiedDashboard._delta_pct(100, 100) == 0.0

    def test_previous_zero(self):
        assert UnifiedDashboard._delta_pct(100, 0) == 0.0


# ──── Health Score (with mocked subsystems) ─────────────────────────────


class TestHealthScore:
    def test_perfect_health_no_subsystems(self, dashboard):
        """All subsystems None → all scores default to 100."""
        health = dashboard.health_score()
        assert health["score"] == 100
        assert health["status"] == "healthy"
        assert "breakdown" in health
        for key in ("system", "pipeline", "packs", "trends"):
            assert health["breakdown"][key]["score"] == 100

    def test_degraded_system_cpu(self, dashboard):
        """High CPU degrades system score."""
        collector = MagicMock()
        collector.last_system_snapshot = {
            "cpu_pct": 92.0,
            "ram_pct": 50.0,
            "gpu_vram_pct": 50.0,
        }
        with patch.object(dashboard, "_collector", return_value=collector):
            health = dashboard.health_score()
        assert health["breakdown"]["system"]["score"] < 100

    def test_pipeline_high_latency(self, dashboard, mock_db):
        """High pipeline latency degrades pipeline score."""
        db, _ = mock_db
        db.get_pipeline_summary.return_value = {
            "avg_latency": 2500.0,
            "total": 10,
            "total_kills": 0,
        }
        with patch.object(dashboard, "_db", return_value=db):
            health = dashboard.health_score()
        assert health["breakdown"]["pipeline"]["score"] == 70

    def test_pipeline_high_kill_rate(self, dashboard, mock_db):
        """High kill rate degrades pipeline score."""
        db, _ = mock_db
        db.get_pipeline_summary.return_value = {
            "avg_latency": 100.0,
            "total": 10,
            "total_kills": 5,
        }
        with patch.object(dashboard, "_db", return_value=db):
            health = dashboard.health_score()
        assert health["breakdown"]["pipeline"]["score"] < 100


# ──── System History ────────────────────────────────────────────────────


class TestSystemHistory:
    def test_no_db(self, dashboard):
        """Returns empty series when DB is None."""
        result = dashboard.system_history(hours=1.0)
        assert "range" in result
        assert result["cpu_pct"] == []
        assert result["ram_pct"] == []

    def test_with_data(self, dashboard):
        """Populates series from DB rows."""
        db = MagicMock()
        db.get_system_history.return_value = [
            {"ts": 100.0, "cpu_pct": 55.0, "ram_pct": 40.0, "gpu_vram_pct": 30.0, "gpu_temp_c": 60.0},
            {"ts": 200.0, "cpu_pct": 65.0, "ram_pct": 45.0, "gpu_vram_pct": 35.0, "gpu_temp_c": 62.0},
        ]
        with patch.object(dashboard, "_db", return_value=db):
            result = dashboard.system_history(hours=1.0)
        assert len(result["cpu_pct"]) == 2
        assert result["cpu_pct"][0] == (100.0, 55.0)


# ──── Gauge Data ────────────────────────────────────────────────────────


class TestGaugeData:
    def test_returns_gauges_with_no_collector(self, dashboard):
        """Returns gauge widgets even when collector is None."""
        gauges = dashboard.gauge_data()
        assert len(gauges) == 5
        assert all(g.widget_type == "gauge" for g in gauges)

    def test_gauge_values_from_collector(self, dashboard):
        """Gauge values come from the collector snapshot."""
        collector = MagicMock()
        collector.last_system_snapshot = {
            "cpu_pct": 75.5,
            "ram_pct": 60.0,
            "gpu_vram_pct": 80.0,
            "gpu_temp_c": 72.0,
        }
        collector.last_process_snapshot = {"disk_pct": 45.0}
        with patch.object(dashboard, "_collector", return_value=collector):
            gauges = dashboard.gauge_data()
        cpu_gauge = next(g for g in gauges if g.widget_id == "gauge_cpu_pct")
        assert cpu_gauge.data["value"] == 75.5
        disk_gauge = next(g for g in gauges if g.widget_id == "gauge_disk_pct")
        assert disk_gauge.data["value"] == 45.0


# ──── Sparkline Data ────────────────────────────────────────────────────


class TestSparklineData:
    def test_no_db(self, dashboard):
        """Returns empty sparkline with no data."""
        widget = dashboard.sparkline_data("cpu_pct", hours=1.0, points=10)
        assert widget.widget_type == "sparkline"
        assert widget.data["values"] == []

    def test_with_data(self, dashboard):
        """Populates sparkline from DB rows."""
        db = MagicMock()
        db.get_system_history.return_value = [
            {"ts": float(i), "cpu_pct": float(i * 10)}
            for i in range(20)
        ]
        with patch.object(dashboard, "_db", return_value=db):
            widget = dashboard.sparkline_data("cpu_pct", hours=1.0, points=5)
        assert len(widget.data["values"]) == 5
        assert widget.data["current"] > 0


# ──── Pipeline Summary ──────────────────────────────────────────────────


class TestPipelineSummary:
    def test_no_db(self, dashboard):
        """Returns zero defaults when DB is None."""
        result = dashboard.pipeline_summary(hours=1.0)
        assert result["total_requests"] == 0
        assert result["avg_latency_ms"] == 0.0

    def test_with_rows(self, dashboard, mock_db):
        """Calculates stats from pipeline_metrics rows."""
        db, cursor = mock_db
        cursor.fetchall.return_value = [
            {"latency_ms": 100.0, "tokens_in": 10, "tokens_out": 50, "tps": 20.0, "kill_fired": 0},
            {"latency_ms": 200.0, "tokens_in": 15, "tokens_out": 60, "tps": 25.0, "kill_fired": 0},
            {"latency_ms": 300.0, "tokens_in": 20, "tokens_out": 70, "tps": 30.0, "kill_fired": 1},
        ]
        with patch.object(dashboard, "_db", return_value=db):
            result = dashboard.pipeline_summary(hours=1.0)
        assert result["total_requests"] == 3
        assert result["avg_latency_ms"] == 200.0
        assert result["total_tokens_in"] == 45
        assert result["total_tokens_out"] == 180
        assert result["error_rate"] == round(1 / 3, 4)


# ──── Pipeline History ──────────────────────────────────────────────────


class TestPipelineHistory:
    def test_no_db(self, dashboard):
        """Returns empty series when DB is None."""
        result = dashboard.pipeline_history(hours=1.0)
        assert result["latency_ms"] == []

    def test_with_data(self, dashboard):
        """Populates series from DB rows."""
        db = MagicMock()
        db.get_pipeline_history.return_value = [
            {"ts": 1.0, "latency_ms": 100.0, "tokens_in": 10, "tokens_out": 50, "tps": 20.0},
        ]
        with patch.object(dashboard, "_db", return_value=db):
            result = dashboard.pipeline_history(hours=1.0)
        assert len(result["latency_ms"]) == 1


# ──── Model Breakdown ──────────────────────────────────────────────────


class TestModelBreakdown:
    def test_no_db(self, dashboard):
        """Returns empty list when DB is None."""
        assert dashboard.model_breakdown() == []

    def test_with_rows(self, dashboard, mock_db):
        """Correctly formats per-model breakdown."""
        db, cursor = mock_db
        cursor.fetchall.return_value = [
            {
                "model": "qwen3-8b",
                "calls": 10,
                "avg_latency": 250.0,
                "avg_tps": 22.5,
                "total_tokens_in": 500,
                "total_tokens_out": 1200,
                "kills": 1,
            },
        ]
        with patch.object(dashboard, "_db", return_value=db):
            result = dashboard.model_breakdown(hours=1.0)
        assert len(result) == 1
        assert result[0]["model"] == "qwen3-8b"
        assert result[0]["calls"] == 10
        assert result[0]["error_rate"] == 0.1


# ──── Pack Activity ─────────────────────────────────────────────────────


class TestPackActivity:
    def test_no_packs(self, dashboard):
        """Returns empty result when PackTracker is None."""
        result = dashboard.pack_activity(hours=1.0)
        assert result["total_executions"] == 0

    def test_with_packs(self, dashboard):
        """Aggregates pack summary data."""
        packs = MagicMock()
        activity = MagicMock()
        activity.total_calls = 50
        activity.total_cpu_seconds = 12.5
        activity.error_count = 3
        activity.skills_used = {"skill_a": 30, "skill_b": 20}
        activity.to_dict.return_value = {"name": "bedroom"}
        packs.pack_summary.return_value = {"bedroom": activity}

        with patch.object(dashboard, "_packs", return_value=packs):
            result = dashboard.pack_activity(hours=1.0)
        assert result["total_executions"] == 50
        assert result["total_errors"] == 3
        assert len(result["top_skills"]) == 2


# ──── Pack Leaderboard ──────────────────────────────────────────────────


class TestPackLeaderboard:
    def test_no_packs(self, dashboard):
        assert dashboard.pack_leaderboard() == []

    def test_delegates_to_tracker(self, dashboard):
        packs = MagicMock()
        packs.top_packs.return_value = [{"name": "bedroom", "cpu": 5.0}]
        with patch.object(dashboard, "_packs", return_value=packs):
            result = dashboard.pack_leaderboard(n=5)
        assert len(result) == 1
        packs.top_packs.assert_called_once_with(n=5, sort_by="cpu")


# ──── Pack Timeline ─────────────────────────────────────────────────────


class TestPackTimeline:
    def test_no_db(self, dashboard):
        """Returns empty list when DB is None."""
        assert dashboard.pack_timeline("bedroom") == []

    def test_with_data(self, dashboard, mock_db):
        """Formats pack execution rows correctly."""
        db, cursor = mock_db
        cursor.fetchall.return_value = [
            {
                "ts": 1000.0,
                "skill_name": "greet",
                "duration_s": 0.1234,
                "cpu_delta_s": 0.05,
                "memory_mb": 128.7,
                "success": 1,
                "error": "",
            },
        ]
        with patch.object(dashboard, "_db", return_value=db):
            result = dashboard.pack_timeline("bedroom", hours=1.0)
        assert len(result) == 1
        assert result[0]["skill"] == "greet"
        assert result[0]["success"] is True
        assert result[0]["duration_s"] == 0.1234


# ──── Anomaly Feed ──────────────────────────────────────────────────────


class TestAnomalyFeed:
    def test_no_detector(self, dashboard):
        assert dashboard.anomaly_feed(hours=1.0) == []

    def test_filters_by_time(self, dashboard):
        """Only anomalies within the time window are returned."""
        detector = MagicMock()
        now = time.time()
        detector.recent_anomalies.return_value = [
            {"timestamp": now - 100, "severity": "high"},
            {"timestamp": now - 7200, "severity": "high"},  # too old
        ]
        with patch.object(dashboard, "_anomalies", return_value=detector):
            result = dashboard.anomaly_feed(hours=1.0)
        assert len(result) == 1


# ──── Alert Feed ────────────────────────────────────────────────────────


class TestAlertFeed:
    def test_no_router_no_db(self, dashboard):
        assert dashboard.alert_feed(hours=1.0) == []

    def test_uses_router(self, dashboard):
        """Uses alert router when available."""
        router = MagicMock()
        now = time.time()
        router.recent_routed.return_value = [
            {"ts": now - 60, "message": "alert1"},
        ]
        with patch.object(dashboard, "_router", return_value=router):
            result = dashboard.alert_feed(hours=1.0)
        assert len(result) == 1

    def test_falls_back_to_db(self, dashboard):
        """Falls back to DB alerts when router is None."""
        db = MagicMock()
        now = time.time()
        db.get_recent_alerts.return_value = [
            {"ts": now - 60, "message": "db_alert"},
        ]
        with patch.object(dashboard, "_router", return_value=None), \
             patch.object(dashboard, "_db", return_value=db):
            result = dashboard.alert_feed(hours=1.0)
        assert len(result) == 1


# ──── Active Issues ─────────────────────────────────────────────────────


class TestActiveIssues:
    def test_empty_with_no_subsystems(self, dashboard):
        assert dashboard.active_issues() == []

    def test_combines_multiple_sources(self, dashboard):
        """Aggregates issues from router, trends, and anomalies."""
        now = time.time()
        router = MagicMock()
        router.escalation_check.return_value = [
            {"severity": "critical", "node": "gpu", "ts": now},
        ]
        trends = MagicMock()
        trend_obj = MagicMock()
        trend_obj.to_dict.return_value = {
            "metric_key": "gpu_vram_pct",
            "direction": "rising",
            "predicted_1h": 98.0,
            "ts": now,
        }
        trends.critical_trends.return_value = [trend_obj]
        detector = MagicMock()
        detector.recent_anomalies.return_value = [
            {"timestamp": now - 10, "severity": "critical", "node": "cpu", "metric": "cpu_pct", "message": "spike"},
        ]

        with patch.object(dashboard, "_router", return_value=router), \
             patch.object(dashboard, "_trends", return_value=trends), \
             patch.object(dashboard, "_anomalies", return_value=detector):
            issues = dashboard.active_issues()
        assert len(issues) == 3
        types = {i["type"] for i in issues}
        assert types == {"alert", "trend", "anomaly"}


# ──── Trend Overview ────────────────────────────────────────────────────


class TestTrendOverview:
    def test_no_predictor(self, dashboard):
        assert dashboard.trend_overview() == []

    def test_formats_trends(self, dashboard):
        """Formats trend results with arrows."""
        predictor = MagicMock()
        trend = MagicMock()
        trend.to_dict.return_value = {
            "metric_key": "cpu_pct",
            "direction": "rising",
            "current_value": 65.0,
            "predicted_1h": 75.0,
            "predicted_4h": 85.0,
            "predicted_24h": 95.0,
            "r_squared": 0.92,
            "severity": "warning",
            "slope": 2.5,
        }
        predictor.all_trends.return_value = [trend]

        with patch.object(dashboard, "_trends", return_value=predictor):
            result = dashboard.trend_overview()
        assert len(result) == 1
        assert result[0]["arrow"] == "↑"
        assert result[0]["predicted_1h"] == 75.0


# ──── Capacity Forecast ────────────────────────────────────────────────


class TestCapacityForecast:
    def test_no_predictor(self, dashboard):
        assert dashboard.capacity_forecast() == []

    def test_urgency_levels(self, dashboard):
        """Urgency classification based on minutes_to_limit."""
        predictor = MagicMock()
        predictor.capacity_warnings.return_value = [
            {"metric": "gpu_vram", "current": 85, "predicted": 100, "threshold": 95, "minutes_to_limit": 30},
            {"metric": "ram", "current": 70, "predicted": 90, "threshold": 95, "minutes_to_limit": 180},
            {"metric": "disk", "current": 50, "predicted": 70, "threshold": 95, "minutes_to_limit": 300},
        ]
        with patch.object(dashboard, "_trends", return_value=predictor):
            result = dashboard.capacity_forecast(hours=24)
        assert result[0]["urgency"] == "critical"
        assert result[1]["urgency"] == "warning"
        assert result[2]["urgency"] == "info"


# ──── Correlation Insights ──────────────────────────────────────────────


class TestCorrelationInsights:
    def test_no_engine(self, dashboard):
        assert dashboard.correlation_insights() == []

    def test_generates_insights(self, dashboard):
        """Generates human-readable correlation insights."""
        engine = MagicMock()
        engine.strongest_correlations.return_value = [
            {
                "metric_a": "cpu_pct",
                "metric_b": "latency_ms",
                "pearson_r": 0.85,
                "strength": "strong",
                "direction": "positive",
                "sample_count": 100,
            },
        ]
        with patch.object(dashboard, "_correlations", return_value=engine):
            result = dashboard.correlation_insights()
        assert len(result) == 1
        assert "strongly" in result[0]["insight"]
        assert "positively" in result[0]["insight"]
        assert result[0]["pearson_r"] == 0.85


# ──── Comparison ────────────────────────────────────────────────────────


class TestComparison:
    def test_no_db(self, dashboard):
        """Returns zero-value structure when DB is None."""
        result = dashboard.comparison(hours=1.0)
        assert "current_range" in result
        assert "previous_range" in result
        # System metrics still present with zero values (helper returns 0.0)
        for metric in ("cpu_pct", "ram_pct", "gpu_vram_pct"):
            assert result["system"][metric]["current"] == 0.0
            assert result["system"][metric]["direction"] == "flat"

    def test_with_data(self, dashboard, mock_db):
        """Computes deltas between current and previous period."""
        db, cursor = mock_db

        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            row = MagicMock()
            if call_count[0] <= 3:
                # system metric AVG queries (3 metrics × 2 periods = 6)
                row.__getitem__ = lambda s, k: 50.0 if k == "avg_val" else None
            else:
                # pipeline stats queries
                row.__getitem__ = lambda s, k: {
                    "total": 10,
                    "avg_lat": 200.0,
                    "avg_tps": 25.0,
                    "kills": 1,
                }[k]
            return row

        cursor.fetchone.side_effect = side_effect

        with patch.object(dashboard, "_db", return_value=db):
            result = dashboard.comparison(hours=1.0)
        assert "system" in result
        assert "pipeline" in result


# ──── Event Streaming ───────────────────────────────────────────────────


class TestEventStreaming:
    def test_register_and_notify(self, dashboard):
        """Registered listener receives events."""
        events = []
        dashboard.register_listener(lambda t, d: events.append((t, d)))
        dashboard._notify_listeners("alert", {"msg": "test"})
        assert len(events) == 1
        assert events[0] == ("alert", {"msg": "test"})

    def test_unregister(self, dashboard):
        """Unregistered listener does not receive events."""
        events = []
        cb = lambda t, d: events.append((t, d))
        dashboard.register_listener(cb)
        dashboard.unregister_listener(cb)
        dashboard._notify_listeners("alert", {"msg": "test"})
        assert len(events) == 0

    def test_duplicate_register(self, dashboard):
        """Registering same callback twice does not duplicate."""
        events = []
        cb = lambda t, d: events.append((t, d))
        dashboard.register_listener(cb)
        dashboard.register_listener(cb)
        dashboard._notify_listeners("alert", {"msg": "test"})
        assert len(events) == 1

    def test_listener_exception_does_not_crash(self, dashboard):
        """Exception in listener does not propagate."""
        def bad_listener(t, d):
            raise RuntimeError("boom")
        dashboard.register_listener(bad_listener)
        dashboard._notify_listeners("alert", {"msg": "test"})

    def test_unregister_nonexistent(self, dashboard):
        """Unregistering unknown listener is a no-op."""
        dashboard.unregister_listener(lambda t, d: None)


# ──── Singleton ─────────────────────────────────────────────────────────


class TestSingleton:
    def test_returns_same_instance(self):
        """get_unified_dashboard returns the same instance."""
        from engine.observability.unified_dashboard import get_unified_dashboard
        a = get_unified_dashboard()
        b = get_unified_dashboard()
        assert a is b

    def test_is_unified_dashboard(self):
        from engine.observability.unified_dashboard import get_unified_dashboard
        d = get_unified_dashboard()
        assert isinstance(d, UnifiedDashboard)


# ──── Full State Integration ────────────────────────────────────────────


class TestFullState:
    def test_full_state_no_subsystems(self, dashboard):
        """full_state() works with all subsystems returning None."""
        state = dashboard.full_state()
        assert "health" in state
        assert "summary_cards" in state
        assert "recent_alerts" in state
        assert "top_packs" in state
        assert "trends" in state
        assert "anomalies" in state
        assert "active_issues" in state
        assert state["health"]["score"] == 100

    def test_summary_cards_include_all_categories(self, dashboard):
        """Summary cards include health + system + pipeline + packs + trends."""
        state = dashboard.full_state()
        card_ids = {c["id"] for c in state["summary_cards"]}
        assert "health" in card_ids
        assert "health_system" in card_ids
        assert "health_pipeline" in card_ids
        assert "health_packs" in card_ids
        assert "health_trends" in card_ids
