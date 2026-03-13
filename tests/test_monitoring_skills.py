"""Tests for engine.skills.builtin.monitoring_skills — 14 MCP monitoring skills.

Verifies each skill calls the correct observability singletons, returns string
results for LLM consumption, and handles errors gracefully without raising.
"""
from __future__ import annotations

import importlib
import sys
import time
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ──── Helpers ──────────────────────────────────────────────────────────


def _make_trend(
    metric_key: str = "cpu.usage",
    direction: str = "rising",
    severity: str = "medium",
    slope: float = 0.05,
    r_squared: float = 0.92,
    current_value: float = 65.0,
    predicted_1h: float = 68.0,
    predicted_4h: float = 77.0,
    predicted_24h: float = 95.0,
) -> SimpleNamespace:
    """Build a fake TrendResult namespace matching the attrs the skills read."""
    return SimpleNamespace(
        metric_key=metric_key,
        direction=SimpleNamespace(value=direction),
        severity=SimpleNamespace(value=severity),
        slope=slope,
        r_squared=r_squared,
        current_value=current_value,
        predicted_1h=predicted_1h,
        predicted_4h=predicted_4h,
        predicted_24h=predicted_24h,
    )


# ──── Snapshot ─────────────────────────────────────────────────────────


@patch("engine.observability.alert_router.get_alert_router")
@patch("engine.observability.trend_predictor.get_trend_predictor")
@patch("engine.observability.pack_tracker.get_pack_tracker")
@patch("engine.observability.anomaly_detector.get_anomaly_detector")
@patch("engine.observability.unified_dashboard.get_unified_dashboard")
def test_monitoring_snapshot_returns_string(
    mock_dash, mock_anom, mock_pack, mock_trend, mock_alert
):
    """Snapshot skill aggregates health, packs, anomalies, trends, alerts."""
    from engine.skills.builtin.monitoring_skills import monitoring_snapshot

    mock_dash.return_value.health_score.return_value = {
        "score": 85, "status": "good", "breakdown": {"cpu": 90, "mem": 80}
    }
    mock_pack.return_value.top_packs.return_value = [
        {"pack": "bedroom", "total_cpu_seconds": 12.3, "total_calls": 55}
    ]
    mock_anom.return_value.recent_anomalies.return_value = []
    mock_trend.return_value.all_trends.return_value = []
    mock_alert.return_value.recent_routed.return_value = []

    result = monitoring_snapshot()

    assert isinstance(result, str)
    assert "MONITORING SNAPSHOT" in result
    assert "85/100" in result
    assert "bedroom" in result


@patch("engine.observability.alert_router.get_alert_router")
@patch("engine.observability.trend_predictor.get_trend_predictor")
@patch("engine.observability.pack_tracker.get_pack_tracker")
@patch("engine.observability.anomaly_detector.get_anomaly_detector")
@patch("engine.observability.unified_dashboard.get_unified_dashboard")
def test_monitoring_snapshot_full_detail(
    mock_dash, mock_anom, mock_pack, mock_trend, mock_alert
):
    """Snapshot with detail='full' requests more items."""
    from engine.skills.builtin.monitoring_skills import monitoring_snapshot

    mock_dash.return_value.health_score.return_value = {"score": 70, "status": "ok"}
    mock_pack.return_value.top_packs.return_value = []
    mock_anom.return_value.recent_anomalies.return_value = []
    mock_trend.return_value.all_trends.return_value = [
        _make_trend("mem.rss", direction="rising", slope=0.1),
    ]
    mock_alert.return_value.recent_routed.return_value = []

    result = monitoring_snapshot(detail="full")

    assert isinstance(result, str)
    # Full detail shows trend slope details
    assert "mem.rss" in result
    mock_pack.return_value.top_packs.assert_called_with(n=10)
    mock_anom.return_value.recent_anomalies.assert_called_with(n=15)


@patch("engine.observability.alert_router.get_alert_router")
@patch("engine.observability.trend_predictor.get_trend_predictor")
@patch("engine.observability.pack_tracker.get_pack_tracker")
@patch("engine.observability.anomaly_detector.get_anomaly_detector")
@patch("engine.observability.unified_dashboard.get_unified_dashboard")
def test_monitoring_snapshot_handles_subsystem_errors(
    mock_dash, mock_anom, mock_pack, mock_trend, mock_alert
):
    """Snapshot catches per-subsystem errors and includes them in output."""
    from engine.skills.builtin.monitoring_skills import monitoring_snapshot

    mock_dash.return_value.health_score.side_effect = RuntimeError("db down")
    mock_pack.return_value.top_packs.side_effect = RuntimeError("tracker crash")
    mock_anom.return_value.recent_anomalies.return_value = []
    mock_trend.return_value.all_trends.return_value = []
    mock_alert.return_value.recent_routed.return_value = []

    result = monitoring_snapshot()

    assert isinstance(result, str)
    assert "unavailable" in result
    assert "db down" in result


# ──── Health ───────────────────────────────────────────────────────────


@patch("engine.observability.unified_dashboard.get_unified_dashboard")
def test_monitoring_health_returns_score(mock_dash):
    """Health skill returns formatted score and subsystem breakdown."""
    from engine.skills.builtin.monitoring_skills import monitoring_health

    mock_dash.return_value.health_score.return_value = {
        "score": 92, "status": "healthy",
        "breakdown": {"resources": 95.0, "pipeline": 88.0},
        "ts": time.time(),
    }

    result = monitoring_health()

    assert isinstance(result, str)
    assert "92/100" in result
    assert "HEALTHY" in result
    assert "Resources" in result
    assert "Pipeline" in result


@patch("engine.observability.unified_dashboard.get_unified_dashboard")
def test_monitoring_health_handles_exception(mock_dash):
    """Health skill returns error string when dashboard is unavailable."""
    from engine.skills.builtin.monitoring_skills import monitoring_health

    mock_dash.return_value.health_score.side_effect = ConnectionError("no db")

    result = monitoring_health()

    assert isinstance(result, str)
    assert "failed" in result.lower()
    assert "no db" in result


# ──── Packs ────────────────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.get_pack_tracker")
def test_monitoring_packs_returns_table(mock_tracker):
    """Packs skill returns leaderboard table with CPU and call stats."""
    from engine.skills.builtin.monitoring_skills import monitoring_packs

    mock_tracker.return_value.top_packs.return_value = [
        {"pack": "bedroom", "total_cpu_seconds": 5.2, "total_calls": 30}
    ]
    mock_tracker.return_value.pack_summary.return_value = {
        "bedroom": {
            "total_calls": 30, "total_cpu_seconds": 5.2,
            "avg_duration_s": 0.17, "error_count": 1, "success_rate": 96.7,
        }
    }

    result = monitoring_packs(hours=12.0, top_n=5)

    assert isinstance(result, str)
    assert "bedroom" in result
    assert "PACK ACTIVITY" in result
    mock_tracker.return_value.top_packs.assert_called_with(n=5)
    mock_tracker.return_value.pack_summary.assert_called_with(hours=12.0)


@patch("engine.observability.pack_tracker.get_pack_tracker")
def test_monitoring_packs_empty(mock_tracker):
    """Packs skill handles no activity gracefully."""
    from engine.skills.builtin.monitoring_skills import monitoring_packs

    mock_tracker.return_value.top_packs.return_value = []
    mock_tracker.return_value.pack_summary.return_value = {}

    result = monitoring_packs()

    assert isinstance(result, str)
    assert "No pack activity" in result


# ──── Pack Detail ──────────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.get_pack_tracker")
def test_monitoring_pack_detail_returns_stats(mock_tracker):
    """Pack detail skill returns per-pack stats and recent executions."""
    from engine.skills.builtin.monitoring_skills import monitoring_pack_detail

    mock_tracker.return_value.pack_summary.return_value = {
        "bedroom": {
            "total_calls": 100, "total_cpu_seconds": 15.0,
            "total_duration_s": 20.0, "avg_duration_s": 0.2,
            "p95_duration_s": 0.5, "p99_duration_s": 0.9,
            "success_rate": 99.0, "error_count": 1,
            "memory_mb_peak": 128.5, "pid_count": 2,
            "categories": ["game", "system"],
            "last_execution": time.time() - 60,
            "skills_used": {"greet": 50, "explore": 50},
        }
    }
    mock_tracker.return_value.pack_processes.return_value = [
        {"pid": 1234, "process_name": "python", "process_category": "runtime",
         "cpu_s": 3.0, "mem_mb": 100.0}
    ]
    mock_tracker.return_value.recent_executions.return_value = [
        {"skill": "greet", "success": True, "duration_s": 0.15, "ts": time.time()}
    ]

    result = monitoring_pack_detail(pack_name="bedroom")

    assert isinstance(result, str)
    assert "PACK: bedroom" in result
    assert "greet" in result
    assert "python" in result


@patch("engine.observability.pack_tracker.get_pack_tracker")
def test_monitoring_pack_detail_not_found(mock_tracker):
    """Pack detail returns informative message when pack has no activity."""
    from engine.skills.builtin.monitoring_skills import monitoring_pack_detail

    mock_tracker.return_value.pack_summary.return_value = {}

    result = monitoring_pack_detail(pack_name="nonexistent")

    assert isinstance(result, str)
    assert "nonexistent" in result
    assert "no recorded activity" in result


@patch("engine.observability.pack_tracker.get_pack_tracker")
def test_monitoring_pack_detail_tolerates_subprocess_errors(mock_tracker):
    """Pack detail catches errors from pack_processes and recent_executions."""
    from engine.skills.builtin.monitoring_skills import monitoring_pack_detail

    mock_tracker.return_value.pack_summary.return_value = {
        "monitoring": {
            "total_calls": 5, "total_cpu_seconds": 1.0,
            "total_duration_s": 2.0, "avg_duration_s": 0.4,
            "p95_duration_s": 0.8, "p99_duration_s": 1.0,
            "success_rate": 100.0, "error_count": 0,
            "memory_mb_peak": 50.0, "pid_count": 1,
            "categories": ["system"],
        }
    }
    mock_tracker.return_value.pack_processes.side_effect = RuntimeError("fail")
    mock_tracker.return_value.recent_executions.side_effect = RuntimeError("fail")

    result = monitoring_pack_detail(pack_name="monitoring")

    # Should not raise — errors are silently caught
    assert isinstance(result, str)
    assert "PACK: monitoring" in result


# ──── Skill Leaderboard ────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.get_pack_tracker")
def test_monitoring_skill_leaderboard_returns_table(mock_tracker):
    """Skill leaderboard returns ranked skills by CPU."""
    from engine.skills.builtin.monitoring_skills import monitoring_skill_leaderboard

    mock_tracker.return_value.skill_leaderboard.return_value = [
        {"skill_name": "greet", "pack": "bedroom", "cnt": 200,
         "total_cpu": 10.5, "avg_dur": 0.05, "err_cnt": 2},
        {"skill_name": "explore", "pack": "bedroom", "cnt": 100,
         "total_cpu": 5.0, "avg_dur": 0.05, "err_cnt": 0},
    ]

    result = monitoring_skill_leaderboard(top_n=10)

    assert isinstance(result, str)
    assert "SKILL LEADERBOARD" in result
    assert "greet" in result
    assert "explore" in result
    mock_tracker.return_value.skill_leaderboard.assert_called_with(top_n=10)


@patch("engine.observability.pack_tracker.get_pack_tracker")
def test_monitoring_skill_leaderboard_empty(mock_tracker):
    """Skill leaderboard handles no data gracefully."""
    from engine.skills.builtin.monitoring_skills import monitoring_skill_leaderboard

    mock_tracker.return_value.skill_leaderboard.return_value = []

    result = monitoring_skill_leaderboard()

    assert isinstance(result, str)
    assert "No skill execution data" in result


# ──── Anomalies ────────────────────────────────────────────────────────


@patch("engine.observability.anomaly_detector.get_anomaly_detector")
def test_monitoring_anomalies_returns_events(mock_detector):
    """Anomalies skill filters by time window and formats a table."""
    from engine.skills.builtin.monitoring_skills import monitoring_anomalies

    now = time.time()
    mock_detector.return_value.recent_anomalies.return_value = [
        {"severity": "high", "node": "system", "metric": "cpu",
         "value": 98.5, "expected_mean": 45.0, "method": "zscore",
         "ts": now - 60, "message": "spike"},
        # Old event outside the window
        {"severity": "low", "node": "gpu", "metric": "temp",
         "value": 70.0, "expected_mean": 55.0, "method": "iqr",
         "ts": now - 50000, "message": "warm"},
    ]

    result = monitoring_anomalies(hours=4.0)

    assert isinstance(result, str)
    assert "ANOMALIES" in result
    assert "HIGH" in result
    # Old event should be filtered out — only 1 event in window
    assert "Total: 1" in result


@patch("engine.observability.anomaly_detector.get_anomaly_detector")
def test_monitoring_anomalies_severity_filter(mock_detector):
    """Anomalies skill passes severity filter to the detector."""
    from engine.skills.builtin.monitoring_skills import monitoring_anomalies

    mock_detector.return_value.recent_anomalies.return_value = []

    result = monitoring_anomalies(severity="critical")

    assert isinstance(result, str)
    assert "CRITICAL" in result
    mock_detector.return_value.recent_anomalies.assert_called_with(
        n=100, severity="critical"
    )


@patch("engine.observability.anomaly_detector.get_anomaly_detector")
def test_monitoring_anomalies_empty_window(mock_detector):
    """Anomalies skill shows clean message when none found."""
    from engine.skills.builtin.monitoring_skills import monitoring_anomalies

    mock_detector.return_value.recent_anomalies.return_value = []

    result = monitoring_anomalies()

    assert isinstance(result, str)
    assert "No anomalies detected" in result


# ──── Trends ───────────────────────────────────────────────────────────


@patch("engine.observability.trend_predictor.get_trend_predictor")
def test_monitoring_trends_returns_grouped_output(mock_predictor):
    """Trends skill groups metrics by direction with predictions."""
    from engine.skills.builtin.monitoring_skills import monitoring_trends

    mock_predictor.return_value.all_trends.return_value = [
        _make_trend("cpu.usage", "rising", slope=0.1),
        _make_trend("mem.free", "falling", slope=-0.05),
        _make_trend("disk.io", "stable", slope=0.001),
    ]

    result = monitoring_trends()

    assert isinstance(result, str)
    assert "METRIC TRENDS" in result
    assert "3 tracked" in result
    assert "RISING" in result
    assert "FALLING" in result
    assert "cpu.usage" in result
    assert "pred 1h=" in result


@patch("engine.observability.trend_predictor.get_trend_predictor")
def test_monitoring_trends_no_data(mock_predictor):
    """Trends skill shows message when insufficient data."""
    from engine.skills.builtin.monitoring_skills import monitoring_trends

    mock_predictor.return_value.all_trends.return_value = []

    result = monitoring_trends()

    assert isinstance(result, str)
    assert "Insufficient data" in result


# ──── Capacity ─────────────────────────────────────────────────────────


@patch("engine.observability.trend_predictor.get_trend_predictor")
def test_monitoring_capacity_with_warnings(mock_predictor):
    """Capacity skill shows breached and approaching resources."""
    from engine.skills.builtin.monitoring_skills import monitoring_capacity

    mock_predictor.return_value.capacity_warnings.return_value = [
        {"metric_key": "disk.usage", "current_value": 95.0,
         "threshold": 90.0, "severity": "critical", "status": "breached"},
        {"metric_key": "mem.usage", "current_value": 78.0,
         "threshold": 85.0, "severity": "warning", "status": "approaching",
         "time_to_breach_min": 120, "predicted_at_horizon": 88.0,
         "slope_per_min": 0.06},
    ]

    result = monitoring_capacity(horizon_hours=12)

    assert isinstance(result, str)
    assert "CAPACITY WARNINGS" in result
    assert "BREACHED" in result
    assert "APPROACHING" in result
    assert "disk.usage" in result
    assert "mem.usage" in result
    mock_predictor.return_value.capacity_warnings.assert_called_with(
        horizon_minutes=720
    )


@patch("engine.observability.trend_predictor.get_trend_predictor")
def test_monitoring_capacity_all_safe(mock_predictor):
    """Capacity skill shows safe message when no warnings."""
    from engine.skills.builtin.monitoring_skills import monitoring_capacity

    mock_predictor.return_value.capacity_warnings.return_value = []

    result = monitoring_capacity()

    assert isinstance(result, str)
    assert "safe operating limits" in result


# ──── Correlations ─────────────────────────────────────────────────────


@patch("engine.observability.correlation_engine.get_correlation_engine")
def test_monitoring_correlations_shows_pairs(mock_engine):
    """Correlations skill shows metric pairs above threshold."""
    from engine.skills.builtin.monitoring_skills import monitoring_correlations

    mock_engine.return_value.strongest_correlations.return_value = [
        {"metric_a": "cpu.usage", "metric_b": "response_time",
         "pearson_r": 0.89, "strength": "strong", "direction": "positive",
         "sample_count": 500},
        {"metric_a": "mem.free", "metric_b": "gc.count",
         "pearson_r": -0.45, "strength": "moderate", "direction": "negative",
         "sample_count": 300},
    ]

    result = monitoring_correlations(min_r=0.7)

    assert isinstance(result, str)
    assert "CORRELATIONS" in result
    # Only the r=0.89 pair passes the threshold
    assert "cpu.usage" in result
    assert "1 significant" in result


@patch("engine.observability.correlation_engine.get_correlation_engine")
def test_monitoring_correlations_none_above_threshold(mock_engine):
    """Correlations skill handles no strong correlations."""
    from engine.skills.builtin.monitoring_skills import monitoring_correlations

    mock_engine.return_value.strongest_correlations.return_value = [
        {"pearson_r": 0.3, "metric_a": "a", "metric_b": "b"},
    ]

    result = monitoring_correlations(min_r=0.9)

    assert isinstance(result, str)
    assert "No correlations" in result
    assert "lowering min_r" in result


# ──── Alerts ───────────────────────────────────────────────────────────


@patch("engine.observability.alert_router.get_alert_router")
def test_monitoring_alerts_returns_feed(mock_router):
    """Alerts skill shows recent alerts with routing info."""
    from engine.skills.builtin.monitoring_skills import monitoring_alerts

    now = time.time()
    mock_router.return_value.recent_routed.return_value = [
        {"level": "warning", "severity": "medium", "node": "gpu",
         "metric": "temp", "message": "GPU hot", "suppressed": False,
         "channels": ["console", "nexus"], "ts": now - 30},
    ]
    mock_router.return_value.routing_stats.return_value = {
        "total": 10, "suppressed": 2, "acknowledged": 3,
    }

    result = monitoring_alerts(hours=1.0)

    assert isinstance(result, str)
    assert "ALERT FEED" in result
    assert "GPU hot" in result
    assert "console" in result
    assert "Total: 10" in result


@patch("engine.observability.alert_router.get_alert_router")
def test_monitoring_alerts_empty(mock_router):
    """Alerts skill handles no alerts in window."""
    from engine.skills.builtin.monitoring_skills import monitoring_alerts

    mock_router.return_value.recent_routed.return_value = []
    mock_router.return_value.routing_stats.return_value = {
        "total": 0, "suppressed": 0, "acknowledged": 0,
    }

    result = monitoring_alerts()

    assert isinstance(result, str)
    assert "No alerts" in result


# ──── Suppress ─────────────────────────────────────────────────────────


@patch("engine.observability.alert_router.get_alert_router")
def test_monitoring_suppress_calls_router(mock_router):
    """Suppress skill calls router.suppress with correct duration."""
    from engine.skills.builtin.monitoring_skills import monitoring_suppress

    result = monitoring_suppress(node="gpu", metric="temp", minutes=60)

    assert isinstance(result, str)
    assert "✓" in result
    assert "gpu.temp" in result
    assert "60m" in result
    mock_router.return_value.suppress.assert_called_once_with(
        "gpu", "temp", duration_seconds=3600.0
    )


@patch("engine.observability.alert_router.get_alert_router")
def test_monitoring_suppress_invalid_duration(mock_router):
    """Suppress skill rejects durations outside 1–1440 range."""
    from engine.skills.builtin.monitoring_skills import monitoring_suppress

    result_low = monitoring_suppress(node="a", metric="b", minutes=0)
    result_high = monitoring_suppress(node="a", metric="b", minutes=2000)

    assert "Invalid duration" in result_low
    assert "Invalid duration" in result_high
    mock_router.return_value.suppress.assert_not_called()


# ──── Dashboard ────────────────────────────────────────────────────────


@patch("engine.observability.unified_dashboard.get_unified_dashboard")
def test_monitoring_dashboard_returns_full_state(mock_dash):
    """Dashboard skill renders all widget sections."""
    from engine.skills.builtin.monitoring_skills import monitoring_dashboard

    mock_dash.return_value.full_state.return_value = {
        "health": {"score": 78, "status": "ok"},
        "summary_cards": {"active_scenes": 2, "total_skills": 45},
        "current_values": {"cpu_usage": 55.0, "memory_mb": 1200.0},
        "top_packs": [{"pack": "bedroom", "total_cpu_seconds": 8.0}],
        "trends": {"degrading_count": 1, "volatile_count": 0, "worst_severity": "low"},
        "anomalies": [
            {"severity": "medium", "node": "sys", "metric": "cpu", "message": "spike"}
        ],
        "recent_alerts": [],
        "active_issues": {"critical": 0, "warning": 1},
    }

    result = monitoring_dashboard()

    assert isinstance(result, str)
    assert "UNIFIED MONITORING DASHBOARD" in result
    assert "78/100" in result
    assert "Active Scenes" in result
    assert "bedroom" in result
    assert "Degrading: 1" in result
    assert "spike" in result


@patch("engine.observability.unified_dashboard.get_unified_dashboard")
def test_monitoring_dashboard_handles_exception(mock_dash):
    """Dashboard skill returns error string when unavailable."""
    from engine.skills.builtin.monitoring_skills import monitoring_dashboard

    mock_dash.return_value.full_state.side_effect = RuntimeError("broken")

    result = monitoring_dashboard()

    assert isinstance(result, str)
    assert "unavailable" in result.lower()
    assert "broken" in result


# ──── Cross-Reference ──────────────────────────────────────────────────


@patch("engine.observability.pack_tracker.get_pack_tracker")
def test_monitoring_cross_reference_returns_map(mock_tracker):
    """Cross-reference skill maps packs to OS processes."""
    from engine.skills.builtin.monitoring_skills import monitoring_cross_reference

    mock_tracker.return_value.cross_reference.return_value = {
        "bedroom": {
            "runtime": {"cpu_seconds": 5.0, "memory_mb_peak": 200.0, "execution_count": 50},
        },
        "monitoring": {
            "system": {"cpu_seconds": 1.0, "memory_mb_peak": 80.0, "execution_count": 10},
        },
    }

    result = monitoring_cross_reference()

    assert isinstance(result, str)
    assert "CROSS-REFERENCE" in result
    assert "bedroom" in result
    assert "monitoring" in result


@patch("engine.observability.pack_tracker.get_pack_tracker")
def test_monitoring_cross_reference_empty(mock_tracker):
    """Cross-reference handles no data."""
    from engine.skills.builtin.monitoring_skills import monitoring_cross_reference

    mock_tracker.return_value.cross_reference.return_value = {}

    result = monitoring_cross_reference()

    assert isinstance(result, str)
    assert "No cross-reference data" in result


@patch("engine.observability.pack_tracker.get_pack_tracker")
def test_monitoring_cross_reference_handles_exception(mock_tracker):
    """Cross-reference returns error string on failure."""
    from engine.skills.builtin.monitoring_skills import monitoring_cross_reference

    mock_tracker.return_value.cross_reference.side_effect = RuntimeError("no data")

    result = monitoring_cross_reference()

    assert isinstance(result, str)
    assert "unavailable" in result.lower()


# ──── Degradation ──────────────────────────────────────────────────────


@patch("engine.observability.trend_predictor.get_trend_predictor")
def test_monitoring_degradation_with_issues(mock_predictor):
    """Degradation skill reports degrading and volatile metrics."""
    from engine.skills.builtin.monitoring_skills import monitoring_degradation

    mock_predictor.return_value.degradation_report.return_value = {
        "degrading": [_make_trend("resp.time", "rising", severity="high", slope=0.2)],
        "volatile": [_make_trend("gc.pause", "volatile", severity="medium", slope=0.05)],
        "degrading_count": 1,
        "volatile_count": 1,
        "worst_severity": "high",
        "ts": time.time(),
    }

    result = monitoring_degradation()

    assert isinstance(result, str)
    assert "DEGRADATION REPORT" in result
    assert "resp.time" in result
    assert "gc.pause" in result
    assert "Degrading: 1" in result
    assert "Volatile: 1" in result


@patch("engine.observability.trend_predictor.get_trend_predictor")
def test_monitoring_degradation_clean(mock_predictor):
    """Degradation skill shows all-clear when nothing is degrading."""
    from engine.skills.builtin.monitoring_skills import monitoring_degradation

    mock_predictor.return_value.degradation_report.return_value = {
        "degrading": [], "volatile": [],
        "worst_severity": "none", "ts": time.time(),
    }

    result = monitoring_degradation()

    assert isinstance(result, str)
    assert "No degradation" in result


@patch("engine.observability.trend_predictor.get_trend_predictor")
def test_monitoring_degradation_handles_exception(mock_predictor):
    """Degradation skill returns error string on failure."""
    from engine.skills.builtin.monitoring_skills import monitoring_degradation

    mock_predictor.return_value.degradation_report.side_effect = RuntimeError("err")

    result = monitoring_degradation()

    assert isinstance(result, str)
    assert "unavailable" in result.lower()


@patch("engine.observability.trend_predictor.get_trend_predictor")
def test_monitoring_degradation_dict_trends(mock_predictor):
    """Degradation skill handles dict-based trend objects (not SimpleNamespace)."""
    from engine.skills.builtin.monitoring_skills import monitoring_degradation

    mock_predictor.return_value.degradation_report.return_value = {
        "degrading": [
            {"metric_key": "latency", "slope": 0.3, "current_value": 500.0,
             "severity": "critical"},
        ],
        "volatile": [],
        "worst_severity": "critical",
        "ts": time.time(),
    }

    result = monitoring_degradation()

    assert isinstance(result, str)
    assert "latency" in result


# ──── All Skills Return Strings ────────────────────────────────────────


@patch("engine.observability.unified_dashboard.get_unified_dashboard")
def test_all_skills_return_str_type(mock_dash):
    """Every monitoring skill returns a str, not dict or None."""
    from engine.skills.builtin.monitoring_skills import (
        monitoring_health,
        monitoring_dashboard,
    )

    mock_dash.return_value.health_score.return_value = {"score": 50, "status": "ok"}
    mock_dash.return_value.full_state.return_value = {"health": {"score": 50, "status": "ok"}}

    assert isinstance(monitoring_health(), str)
    assert isinstance(monitoring_dashboard(), str)


# ──── Lazy Import Verification ─────────────────────────────────────────


def test_no_module_level_singleton_instantiation():
    """Monitoring skills module does NOT instantiate singletons at import time.

    All singletons (get_unified_dashboard, get_pack_tracker, etc.) are imported
    lazily inside function bodies. Importing the module should not trigger them.
    """
    # Remove cached module to force a fresh import
    mod_key = "engine.skills.builtin.monitoring_skills"
    saved = sys.modules.pop(mod_key, None)

    try:
        # Patch the observability singletons to detect if they are called
        with patch("engine.observability.unified_dashboard.get_unified_dashboard") as m_dash, \
             patch("engine.observability.pack_tracker.get_pack_tracker") as m_pack, \
             patch("engine.observability.anomaly_detector.get_anomaly_detector") as m_anom, \
             patch("engine.observability.trend_predictor.get_trend_predictor") as m_trend, \
             patch("engine.observability.alert_router.get_alert_router") as m_alert, \
             patch("engine.observability.correlation_engine.get_correlation_engine") as m_corr:

            importlib.import_module(mod_key)

            m_dash.assert_not_called()
            m_pack.assert_not_called()
            m_anom.assert_not_called()
            m_trend.assert_not_called()
            m_alert.assert_not_called()
            m_corr.assert_not_called()
    finally:
        # Restore original module if it existed
        if saved is not None:
            sys.modules[mod_key] = saved


# ──── Helper Functions ─────────────────────────────────────────────────


def test_helper_ts_formats_utc():
    """_ts helper formats epoch as UTC timestamp string."""
    from engine.skills.builtin.monitoring_skills import _ts

    result = _ts(1000000000)
    assert "2001" in result
    assert "UTC" in result

    result_now = _ts()
    assert "UTC" in result_now


def test_helper_pct_formats_percentage():
    """_pct helper formats a float as a percentage string."""
    from engine.skills.builtin.monitoring_skills import _pct

    assert _pct(99.5) == "99.50%"
    assert _pct(0.0) == "0.00%"


def test_helper_dur_formats_duration():
    """_dur helper formats seconds into human-readable durations."""
    from engine.skills.builtin.monitoring_skills import _dur

    assert _dur(30.0) == "30.0s"
    assert _dur(120.0) == "2.0m"
    assert _dur(7200.0) == "2.0h"


def test_helper_bar_creates_progress_bar():
    """_bar helper creates a visual progress bar string."""
    from engine.skills.builtin.monitoring_skills import _bar

    bar_full = _bar(100.0)
    assert "█" in bar_full
    assert "░" not in bar_full

    bar_empty = _bar(0.0)
    assert "░" in bar_empty
    assert "█" not in bar_empty

    bar_half = _bar(50.0)
    assert "█" in bar_half
    assert "░" in bar_half


def test_helper_tbl_builds_table():
    """_tbl helper builds an aligned table with headers and separator."""
    from engine.skills.builtin.monitoring_skills import _tbl

    rows = [["Alice", "100"], ["Bob", "200"]]
    lines = _tbl(["Name", "Score"], rows)

    assert len(lines) >= 4  # header + separator + 2 rows
    assert "Name" in lines[0]
    assert "─" in lines[1]
    assert "Alice" in lines[2]
