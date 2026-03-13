"""Tests for engine.observability.unified_monitor — UnifiedMonitor facade.

Verifies lifecycle, delegation, fan-out, health scoring, snapshot aggregation,
and error resilience of the top-level monitoring orchestrator.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

# We patch _getters so that UnifiedMonitor.__init__ receives mock factories
# instead of importing real subsystems.  Every test gets a clean instance.

_SUBSYSTEM_LABELS = [
    "MetricsCollector",
    "MetricsDB",
    "PackTracker",
    "AnomalyDetector",
    "CorrelationEngine",
    "TrendPredictor",
    "AlertRouter",
    "ProcessMonitor",
    "SystemMonitor",
    "ActivityBus",
]


@pytest.fixture()
def mock_subsystems():
    """Create a dict of label → MagicMock instance for every subsystem."""
    return {label: MagicMock(name=label) for label in _SUBSYSTEM_LABELS}


@pytest.fixture()
def mock_getters(mock_subsystems):
    """Patch _getters so each label maps to a factory returning its mock."""
    factories = {label: MagicMock(return_value=mock) for label, mock in mock_subsystems.items()}
    with patch("engine.observability.unified_monitor._getters", factories):
        yield factories


@pytest.fixture()
def _reset_singleton():
    """Reset the module-level singleton before and after each test."""
    with patch("engine.observability.unified_monitor._instance", None):
        yield


@pytest.fixture()
def monitor(mock_getters, _reset_singleton):
    """Construct a fresh UnifiedMonitor with all subsystems mocked."""
    from engine.observability.unified_monitor import UnifiedMonitor

    return UnifiedMonitor(config={"trend_interval": 30.0})


@pytest.fixture()
def subs(monitor, mock_subsystems):
    """Convenience accessor returning the subsystem mocks dict.

    Usage in tests: ``subs["PackTracker"]`` gives the mock that the monitor
    holds as ``monitor._pack_tracker``.
    """
    return mock_subsystems


# ── Construction ────────────────────────────────────────────────────────


def test_construction_acquires_all_subsystems(monitor, subs):
    """UnifiedMonitor stores a reference to every subsystem singleton."""
    assert monitor._metrics_collector is subs["MetricsCollector"]
    assert monitor._metrics_db is subs["MetricsDB"]
    assert monitor._pack_tracker is subs["PackTracker"]
    assert monitor._anomaly_detector is subs["AnomalyDetector"]
    assert monitor._correlation_engine is subs["CorrelationEngine"]
    assert monitor._trend_predictor is subs["TrendPredictor"]
    assert monitor._alert_router is subs["AlertRouter"]
    assert monitor._process_monitor is subs["ProcessMonitor"]
    assert monitor._system_monitor is subs["SystemMonitor"]
    assert monitor._activity_bus is subs["ActivityBus"]


def test_construction_with_no_config(mock_getters, _reset_singleton):
    """UnifiedMonitor uses empty dict when config is None."""
    from engine.observability.unified_monitor import UnifiedMonitor

    mon = UnifiedMonitor(config=None)
    assert mon._config == {}


def test_construction_tolerates_getter_exception(mock_getters, _reset_singleton):
    """A failing getter stores None instead of crashing init."""
    from engine.observability.unified_monitor import UnifiedMonitor

    mock_getters["PackTracker"].side_effect = RuntimeError("boom")
    mon = UnifiedMonitor()
    assert mon._pack_tracker is None


def test_available_subsystems_lists_resolved(monitor, subs):
    """_available_subsystems returns labels whose instances are not None."""
    available = monitor._available_subsystems()
    for label in _SUBSYSTEM_LABELS:
        assert label in available


def test_available_subsystems_excludes_none(mock_getters, _reset_singleton):
    """Missing subsystems are omitted from the available list."""
    from engine.observability.unified_monitor import UnifiedMonitor

    mock_getters["ActivityBus"].return_value = None
    # Patch the factory to return None via side_effect won't work since
    # __init__ checks `_getters.get(label)` for None vs the return value.
    # Instead, remove the key entirely to simulate missing import.
    del mock_getters["ActivityBus"]
    mon = UnifiedMonitor()
    assert "ActivityBus" not in mon._available_subsystems()


# ── Lifecycle: start() ──────────────────────────────────────────────────


def test_start_calls_pack_tracker_start(monitor, subs):
    """start() invokes PackTracker.start()."""
    monitor.start()
    subs["PackTracker"].start.assert_called_once()


def test_start_calls_metrics_collector_start(monitor, subs):
    """start() invokes MetricsCollector.start()."""
    monitor.start()
    subs["MetricsCollector"].start.assert_called_once()


def test_start_calls_trend_predictor_background(monitor, subs):
    """start() invokes TrendPredictor.start_background with config interval."""
    monitor.start()
    subs["TrendPredictor"].start_background.assert_called_once_with(interval=30.0)


def test_start_sets_running_flag(monitor):
    """start() sets _running to True."""
    assert not monitor._running
    monitor.start()
    assert monitor._running


def test_start_is_idempotent(monitor, subs):
    """Calling start() twice only starts subsystems once."""
    monitor.start()
    monitor.start()
    subs["PackTracker"].start.assert_called_once()


def test_start_tolerates_trend_predictor_failure(monitor, subs):
    """start() continues even if TrendPredictor.start_background raises."""
    subs["TrendPredictor"].start_background.side_effect = RuntimeError("fail")
    monitor.start()
    assert monitor._running


def test_start_without_trend_predictor(mock_getters, _reset_singleton):
    """start() works when TrendPredictor is None."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["TrendPredictor"]
    mon = UnifiedMonitor()
    mon.start()
    assert mon._running


# ── Lifecycle: stop() ───────────────────────────────────────────────────


def test_stop_calls_pack_tracker_stop(monitor, subs):
    """stop() invokes PackTracker.stop()."""
    monitor.start()
    monitor.stop()
    subs["PackTracker"].stop.assert_called_once()


def test_stop_calls_metrics_collector_stop(monitor, subs):
    """stop() invokes MetricsCollector.stop()."""
    monitor.start()
    monitor.stop()
    subs["MetricsCollector"].stop.assert_called_once()


def test_stop_persists_trends(monitor, subs):
    """stop() calls TrendPredictor.persist_trends()."""
    monitor.start()
    monitor.stop()
    subs["TrendPredictor"].persist_trends.assert_called_once()


def test_stop_calls_trend_predictor_stop_background(monitor, subs):
    """stop() calls TrendPredictor.stop_background()."""
    monitor.start()
    monitor.stop()
    subs["TrendPredictor"].stop_background.assert_called_once()


def test_stop_clears_running_flag(monitor):
    """stop() sets _running to False."""
    monitor.start()
    monitor.stop()
    assert not monitor._running


def test_stop_is_idempotent(monitor, subs):
    """Calling stop() when not running is a no-op."""
    monitor.stop()
    subs["PackTracker"].stop.assert_not_called()


def test_stop_tolerates_trend_persist_failure(monitor, subs):
    """stop() continues even if persist_trends raises."""
    subs["TrendPredictor"].persist_trends.side_effect = RuntimeError("fail")
    monitor.start()
    monitor.stop()
    assert not monitor._running


def test_stop_tolerates_trend_stop_failure(monitor, subs):
    """stop() continues even if stop_background raises."""
    subs["TrendPredictor"].stop_background.side_effect = RuntimeError("fail")
    monitor.start()
    monitor.stop()
    assert not monitor._running


# ── Lifecycle: restart() & is_running() ─────────────────────────────────


def test_restart_stops_then_starts(monitor, subs):
    """restart() calls stop then start."""
    monitor.start()
    monitor.restart()
    assert monitor._running
    # MetricsCollector.start called twice (initial start + restart start)
    assert subs["MetricsCollector"].start.call_count == 2


def test_is_running_reflects_state(monitor):
    """is_running() returns the current lifecycle state."""
    assert not monitor.is_running()
    monitor.start()
    assert monitor.is_running()
    monitor.stop()
    assert not monitor.is_running()


# ── Fan-Out: _feed_all() ───────────────────────────────────────────────


def test_feed_all_fans_to_anomaly_detector(monitor, subs):
    """_feed_all forwards metric to AnomalyDetector.feed()."""
    subs["AnomalyDetector"].evaluate.return_value = []
    monitor._feed_all("system", "cpu_pct", 42.0)
    subs["AnomalyDetector"].feed.assert_called_once_with("system", "cpu_pct", 42.0)


def test_feed_all_fans_to_correlation_engine(monitor, subs):
    """_feed_all forwards metric to CorrelationEngine.feed()."""
    subs["AnomalyDetector"].evaluate.return_value = []
    monitor._feed_all("system", "cpu_pct", 42.0)
    subs["CorrelationEngine"].feed.assert_called_once_with("system", "cpu_pct", 42.0)


def test_feed_all_fans_to_trend_predictor(monitor, subs):
    """_feed_all forwards metric to TrendPredictor.feed()."""
    subs["AnomalyDetector"].evaluate.return_value = []
    monitor._feed_all("system", "cpu_pct", 42.0)
    subs["TrendPredictor"].feed.assert_called_once_with("system", "cpu_pct", 42.0)


def test_feed_all_routes_anomaly_events(monitor, subs):
    """_feed_all evaluates anomalies and routes them through AlertRouter."""
    event = {"metric": "cpu_pct", "severity": "high"}
    subs["AnomalyDetector"].evaluate.return_value = [event]
    monitor._feed_all("system", "cpu_pct", 95.0)
    subs["AlertRouter"].route_anomaly.assert_called_once_with(event)


def test_feed_all_tolerates_subsystem_feed_error(monitor, subs):
    """_feed_all continues when one subsystem's feed() raises."""
    subs["AnomalyDetector"].feed.side_effect = RuntimeError("boom")
    subs["AnomalyDetector"].evaluate.return_value = []
    monitor._feed_all("system", "cpu_pct", 50.0)
    # Other feeds still called
    subs["CorrelationEngine"].feed.assert_called_once()
    subs["TrendPredictor"].feed.assert_called_once()


def test_feed_all_tolerates_evaluate_error(monitor, subs):
    """_feed_all does not crash if anomaly evaluation raises."""
    subs["AnomalyDetector"].evaluate.side_effect = RuntimeError("fail")
    monitor._feed_all("system", "cpu_pct", 50.0)
    # Should not raise


def test_feed_all_tolerates_route_anomaly_error(monitor, subs):
    """_feed_all does not crash if AlertRouter.route_anomaly raises."""
    subs["AnomalyDetector"].evaluate.return_value = [{"sev": "high"}]
    subs["AlertRouter"].route_anomaly.side_effect = RuntimeError("fail")
    monitor._feed_all("system", "cpu_pct", 50.0)
    # Should not raise


def test_feed_all_skips_none_subsystems(mock_getters, _reset_singleton):
    """_feed_all silently skips subsystems that are None."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["AnomalyDetector"]
    del mock_getters["CorrelationEngine"]
    del mock_getters["TrendPredictor"]
    mon = UnifiedMonitor()
    # Should not raise even with all analytical subsystems missing
    mon._feed_all("sys", "cpu", 10.0)


# ── Fan-Out Wiring ──────────────────────────────────────────────────────


def test_wire_fanout_wraps_alert_engine_feed(monitor, subs):
    """start() wires _feed_all into MetricsCollector.alert_engine.feed."""
    engine = MagicMock()
    original_feed = MagicMock()
    engine.feed = original_feed
    subs["MetricsCollector"].alert_engine = engine
    subs["AnomalyDetector"].evaluate.return_value = []

    monitor.start()

    # The engine.feed has been replaced with augmented version
    engine.feed("node", "metric", 1.0)
    original_feed.assert_called_once_with("node", "metric", 1.0)
    subs["AnomalyDetector"].feed.assert_called_once_with("node", "metric", 1.0)


def test_unwire_fanout_restores_original(monitor, subs):
    """stop() restores original AlertEngine.feed."""
    engine = MagicMock()
    original_feed = MagicMock()
    engine.feed = original_feed
    subs["MetricsCollector"].alert_engine = engine

    monitor.start()
    monitor.stop()

    assert engine.feed is original_feed


def test_wire_fanout_tolerates_missing_alert_engine(monitor, subs):
    """_wire_fanout does not crash if MetricsCollector has no alert_engine."""
    del subs["MetricsCollector"].alert_engine
    monitor.start()
    assert monitor._running


# ── snapshot() ──────────────────────────────────────────────────────────


def test_snapshot_returns_timestamp(monitor):
    """snapshot() includes a 'ts' key with a recent timestamp."""
    before = time.time()
    snap = monitor.snapshot()
    assert snap["ts"] >= before


def test_snapshot_includes_system_data(monitor, subs):
    """snapshot() delegates system data to SystemMonitor.snapshot()."""
    subs["SystemMonitor"].snapshot.return_value = {"cpu_percent": 25.0}
    snap = monitor.snapshot()
    assert snap["system"] == {"cpu_percent": 25.0}


def test_snapshot_includes_packs_from_pack_tracker(monitor, subs):
    """snapshot() calls PackTracker.pack_summary() for pack data."""
    subs["PackTracker"].pack_summary.return_value = {"bedroom": {"calls": 10}}
    snap = monitor.snapshot()
    assert snap["packs"] == {"bedroom": {"calls": 10}}


def test_snapshot_includes_anomalies(monitor, subs):
    """snapshot() delegates anomaly data to AnomalyDetector.snapshot()."""
    subs["AnomalyDetector"].snapshot.return_value = {"count": 3}
    snap = monitor.snapshot()
    assert snap["anomalies"] == {"count": 3}


def test_snapshot_includes_trends(monitor, subs):
    """snapshot() delegates trend data to TrendPredictor.summary()."""
    subs["TrendPredictor"].summary.return_value = {"total": 5}
    snap = monitor.snapshot()
    assert snap["trends"] == {"total": 5}


def test_snapshot_includes_correlations(monitor, subs):
    """snapshot() delegates correlation data to CorrelationEngine.snapshot()."""
    subs["CorrelationEngine"].snapshot.return_value = {"pairs": 2}
    snap = monitor.snapshot()
    assert snap["correlations"] == {"pairs": 2}


def test_snapshot_includes_activity(monitor, subs):
    """snapshot() delegates activity data to ActivityBus.snapshot()."""
    subs["ActivityBus"].snapshot.return_value = {"active": True}
    snap = monitor.snapshot()
    assert snap["activity"] == {"active": True}


def test_snapshot_returns_empty_packs_on_error(monitor, subs):
    """snapshot() returns empty packs dict if PackTracker raises."""
    subs["PackTracker"].pack_summary.side_effect = RuntimeError("fail")
    snap = monitor.snapshot()
    assert snap["packs"] == {}


def test_snapshot_returns_defaults_when_subsystems_none(mock_getters, _reset_singleton):
    """snapshot() returns empty defaults for all absent subsystems."""
    from engine.observability.unified_monitor import UnifiedMonitor

    for label in _SUBSYSTEM_LABELS:
        del mock_getters[label]
    mon = UnifiedMonitor()
    snap = mon.snapshot()
    assert snap["system"] == {}
    assert snap["packs"] == {}
    assert snap["anomalies"] == {}
    assert snap["trends"] == {}
    assert snap["correlations"] == {}
    assert snap["activity"] == {}


# ── health_report() ────────────────────────────────────────────────────


def _setup_healthy_monitor(monitor, subs):
    """Configure mocks so health_report returns a high score."""
    subs["MetricsCollector"].last_system_snapshot = {
        "cpu_pct": 20.0, "ram_pct": 30.0, "gpu_vram_pct": 10.0,
    }
    subs["AnomalyDetector"].anomaly_counts.return_value = {}
    subs["MetricsCollector"].alert_engine.get_status_map.return_value = {}
    subs["TrendPredictor"].degradation_report.return_value = {
        "degrading_count": 0, "volatile_count": 0,
    }
    subs["MetricsCollector"].last_pipeline_summary = {"avg_latency_ms": 50}


def test_health_report_returns_composite_score(monitor, subs):
    """health_report() includes a composite_score key."""
    _setup_healthy_monitor(monitor, subs)
    report = monitor.health_report()
    assert "composite_score" in report
    assert 0 <= report["composite_score"] <= 100


def test_health_report_returns_category_scores(monitor, subs):
    """health_report() includes per-category scores."""
    _setup_healthy_monitor(monitor, subs)
    report = monitor.health_report()
    assert "category_scores" in report
    for cat in ("resources", "stability", "alerts", "trends", "performance"):
        assert cat in report["category_scores"]


def test_health_report_flags_high_cpu(monitor, subs):
    """health_report() creates an issue when CPU exceeds 90%."""
    _setup_healthy_monitor(monitor, subs)
    subs["MetricsCollector"].last_system_snapshot = {
        "cpu_pct": 95.0, "ram_pct": 30.0, "gpu_vram_pct": 10.0,
    }
    report = monitor.health_report()
    details = [i["detail"] for i in report["worst_issues"]]
    assert any("CPU" in d for d in details)


def test_health_report_flags_anomaly_instability(monitor, subs):
    """health_report() flags instability when anomaly count > 5 in 1h."""
    _setup_healthy_monitor(monitor, subs)
    subs["AnomalyDetector"].anomaly_counts.return_value = {
        "system": {"high": 6, "medium": 2}
    }
    report = monitor.health_report()
    assert report["category_scores"]["stability"] < 100


def test_health_report_penalises_red_alerts(monitor, subs):
    """health_report() reduces alert score for red alerts."""
    _setup_healthy_monitor(monitor, subs)
    subs["MetricsCollector"].alert_engine.get_status_map.return_value = {
        "node_a": "red", "node_b": "green",
    }
    report = monitor.health_report()
    assert report["category_scores"]["alerts"] < 100


def test_health_report_high_latency_performance_issue(monitor, subs):
    """health_report() flags performance issue for high latency."""
    _setup_healthy_monitor(monitor, subs)
    subs["MetricsCollector"].last_pipeline_summary = {"avg_latency_ms": 3000}
    report = monitor.health_report()
    assert report["category_scores"]["performance"] <= 20


def test_health_report_includes_timestamp(monitor, subs):
    """health_report() includes a 'ts' key."""
    _setup_healthy_monitor(monitor, subs)
    report = monitor.health_report()
    assert "ts" in report


def test_health_report_issues_sorted_by_severity(monitor, subs):
    """health_report() sorts worst_issues by severity (critical first)."""
    _setup_healthy_monitor(monitor, subs)
    subs["MetricsCollector"].alert_engine.get_status_map.return_value = {
        "a": "red", "b": "yellow",
    }
    subs["MetricsCollector"].last_system_snapshot = {
        "cpu_pct": 95.0, "ram_pct": 30.0, "gpu_vram_pct": 10.0,
    }
    report = monitor.health_report()
    if len(report["worst_issues"]) >= 2:
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        severities = [sev_order.get(i["severity"], 99) for i in report["worst_issues"]]
        assert severities == sorted(severities)


def test_health_report_all_subsystems_none(mock_getters, _reset_singleton):
    """health_report() returns valid structure when all subsystems are None."""
    from engine.observability.unified_monitor import UnifiedMonitor

    for label in _SUBSYSTEM_LABELS:
        del mock_getters[label]
    mon = UnifiedMonitor()
    report = mon.health_report()
    assert "composite_score" in report
    assert "category_scores" in report


# ── PackTracker Delegates ───────────────────────────────────────────────


def test_pack_summary_delegates_to_pack_tracker(monitor, subs):
    """pack_summary() forwards to PackTracker.pack_summary()."""
    subs["PackTracker"].pack_summary.return_value = {"pk": {"count": 5}}
    result = monitor.pack_summary()
    assert result == {"pk": {"count": 5}}
    subs["PackTracker"].pack_summary.assert_called_once()


def test_pack_summary_returns_empty_when_none(mock_getters, _reset_singleton):
    """pack_summary() returns {} when PackTracker is unavailable."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["PackTracker"]
    mon = UnifiedMonitor()
    assert mon.pack_summary() == {}


def test_pack_summary_returns_empty_on_error(monitor, subs):
    """pack_summary() returns {} when PackTracker raises."""
    subs["PackTracker"].pack_summary.side_effect = RuntimeError("fail")
    assert monitor.pack_summary() == {}


def test_top_packs_delegates_to_pack_tracker(monitor, subs):
    """top_packs() forwards to PackTracker.top_packs(n=...)."""
    subs["PackTracker"].top_packs.return_value = [{"pack": "bedroom", "cpu": 5.0}]
    result = monitor.top_packs(n=5)
    assert len(result) == 1
    subs["PackTracker"].top_packs.assert_called_once_with(n=5)


def test_top_packs_returns_empty_list_when_none(mock_getters, _reset_singleton):
    """top_packs() returns [] when PackTracker is unavailable."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["PackTracker"]
    mon = UnifiedMonitor()
    assert mon.top_packs() == []


def test_cross_reference_delegates_to_pack_tracker(monitor, subs):
    """cross_reference() forwards to PackTracker.cross_reference()."""
    subs["PackTracker"].cross_reference.return_value = {"matrix": {}}
    result = monitor.cross_reference()
    assert result == {"matrix": {}}
    subs["PackTracker"].cross_reference.assert_called_once()


def test_cross_reference_returns_empty_when_none(mock_getters, _reset_singleton):
    """cross_reference() returns {} when PackTracker is unavailable."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["PackTracker"]
    mon = UnifiedMonitor()
    assert mon.cross_reference() == {}


# ── AnomalyDetector Delegates ──────────────────────────────────────────


def test_recent_anomalies_delegates_to_anomaly_detector(monitor, subs):
    """recent_anomalies() forwards to AnomalyDetector.recent_anomalies(n=...)."""
    subs["AnomalyDetector"].recent_anomalies.return_value = [{"id": 1}]
    result = monitor.recent_anomalies(n=10)
    assert result == [{"id": 1}]
    subs["AnomalyDetector"].recent_anomalies.assert_called_once_with(n=10)


def test_recent_anomalies_returns_empty_when_none(mock_getters, _reset_singleton):
    """recent_anomalies() returns [] when AnomalyDetector is unavailable."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["AnomalyDetector"]
    mon = UnifiedMonitor()
    assert mon.recent_anomalies() == []


def test_recent_anomalies_returns_empty_on_error(monitor, subs):
    """recent_anomalies() returns [] when AnomalyDetector raises."""
    subs["AnomalyDetector"].recent_anomalies.side_effect = RuntimeError("fail")
    assert monitor.recent_anomalies() == []


def test_anomaly_counts_delegates(monitor, subs):
    """anomaly_counts() forwards to AnomalyDetector.anomaly_counts()."""
    subs["AnomalyDetector"].anomaly_counts.return_value = {"sys": {"high": 2}}
    result = monitor.anomaly_counts()
    assert result == {"sys": {"high": 2}}


# ── TrendPredictor Delegates ───────────────────────────────────────────


def test_all_trends_delegates_to_trend_predictor(monitor, subs):
    """all_trends() forwards to TrendPredictor.all_trends()."""
    subs["TrendPredictor"].all_trends.return_value = [{"metric": "cpu", "slope": 0.1}]
    result = monitor.all_trends()
    assert len(result) == 1
    subs["TrendPredictor"].all_trends.assert_called_once()


def test_all_trends_returns_empty_when_none(mock_getters, _reset_singleton):
    """all_trends() returns [] when TrendPredictor is unavailable."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["TrendPredictor"]
    mon = UnifiedMonitor()
    assert mon.all_trends() == []


def test_all_trends_returns_empty_on_error(monitor, subs):
    """all_trends() returns [] when TrendPredictor raises."""
    subs["TrendPredictor"].all_trends.side_effect = RuntimeError("fail")
    assert monitor.all_trends() == []


def test_capacity_warnings_delegates_to_trend_predictor(monitor, subs):
    """capacity_warnings() forwards to TrendPredictor.capacity_warnings()."""
    subs["TrendPredictor"].capacity_warnings.return_value = [{"metric": "ram_pct"}]
    result = monitor.capacity_warnings(horizon_minutes=120)
    assert len(result) == 1
    subs["TrendPredictor"].capacity_warnings.assert_called_once_with(horizon_minutes=120)


def test_capacity_warnings_returns_empty_when_none(mock_getters, _reset_singleton):
    """capacity_warnings() returns [] when TrendPredictor is unavailable."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["TrendPredictor"]
    mon = UnifiedMonitor()
    assert mon.capacity_warnings() == []


def test_degradation_report_delegates(monitor, subs):
    """degradation_report() forwards to TrendPredictor.degradation_report()."""
    subs["TrendPredictor"].degradation_report.return_value = {"degrading_count": 1}
    result = monitor.degradation_report()
    assert result == {"degrading_count": 1}


# ── CorrelationEngine Delegates ─────────────────────────────────────────


def test_strong_correlations_delegates_to_correlation_engine(monitor, subs):
    """strong_correlations() forwards to CorrelationEngine.correlation_matrix()."""
    subs["CorrelationEngine"].correlation_matrix.return_value = [("cpu", "ram", 0.95)]
    result = monitor.strong_correlations(min_r=0.8)
    assert len(result) == 1
    subs["CorrelationEngine"].correlation_matrix.assert_called_once_with(min_r=0.8)


def test_strong_correlations_returns_empty_when_none(mock_getters, _reset_singleton):
    """strong_correlations() returns [] when CorrelationEngine is unavailable."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["CorrelationEngine"]
    mon = UnifiedMonitor()
    assert mon.strong_correlations() == []


def test_strong_correlations_returns_empty_on_error(monitor, subs):
    """strong_correlations() returns [] when CorrelationEngine raises."""
    subs["CorrelationEngine"].correlation_matrix.side_effect = RuntimeError("fail")
    assert monitor.strong_correlations() == []


def test_discover_correlations_delegates(monitor, subs):
    """discover_correlations() forwards to CorrelationEngine."""
    subs["CorrelationEngine"].discover_correlations.return_value = {"found": 3}
    result = monitor.discover_correlations(min_r=0.6)
    assert result == {"found": 3}


# ── AlertRouter Delegates ──────────────────────────────────────────────


def test_alert_status_delegates_to_alert_engine(monitor, subs):
    """alert_status() reads status_map from MetricsCollector.alert_engine."""
    subs["MetricsCollector"].alert_engine.get_status_map.return_value = {
        "sys": "green", "gpu": "yellow",
    }
    result = monitor.alert_status()
    assert result == {"sys": "green", "gpu": "yellow"}


def test_alert_status_returns_empty_when_no_collector(mock_getters, _reset_singleton):
    """alert_status() returns {} when MetricsCollector is unavailable."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["MetricsCollector"]
    mon = UnifiedMonitor()
    assert mon.alert_status() == {}


def test_alert_status_returns_empty_on_error(monitor, subs):
    """alert_status() returns {} if get_status_map raises."""
    subs["MetricsCollector"].alert_engine.get_status_map.side_effect = RuntimeError("fail")
    assert monitor.alert_status() == {}


def test_recent_alerts_from_alert_router(monitor, subs):
    """recent_alerts() prefers AlertRouter.recent_routed()."""
    subs["AlertRouter"].recent_routed.return_value = [{"alert": "a1"}]
    result = monitor.recent_alerts(n=5)
    assert result == [{"alert": "a1"}]
    subs["AlertRouter"].recent_routed.assert_called_once_with(n=5)


def test_recent_alerts_falls_back_to_metrics_db(monitor, subs):
    """recent_alerts() falls back to MetricsDB when AlertRouter raises."""
    subs["AlertRouter"].recent_routed.side_effect = RuntimeError("fail")
    subs["MetricsDB"].get_recent_alerts.return_value = [{"alert": "db1"}]
    result = monitor.recent_alerts(n=10)
    assert result == [{"alert": "db1"}]


def test_recent_alerts_returns_empty_when_all_fail(monitor, subs):
    """recent_alerts() returns [] when both sources fail."""
    subs["AlertRouter"].recent_routed.side_effect = RuntimeError("fail")
    subs["MetricsDB"].get_recent_alerts.side_effect = RuntimeError("fail")
    assert monitor.recent_alerts() == []


def test_routing_stats_delegates(monitor, subs):
    """routing_stats() forwards to AlertRouter.routing_stats()."""
    subs["AlertRouter"].routing_stats.return_value = {"routed": 10}
    result = monitor.routing_stats()
    assert result == {"routed": 10}


def test_suppress_alert_delegates(monitor, subs):
    """suppress_alert() forwards to AlertRouter.suppress()."""
    monitor.suppress_alert("sys", "cpu_pct", duration=1800.0)
    subs["AlertRouter"].suppress.assert_called_once_with("sys", "cpu_pct", 1800.0)


def test_suppress_alert_tolerates_missing_router(mock_getters, _reset_singleton):
    """suppress_alert() logs a warning when AlertRouter is None."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["AlertRouter"]
    mon = UnifiedMonitor()
    mon.suppress_alert("sys", "cpu", 600.0)  # Should not raise


# ── ActivityBus Delegate ────────────────────────────────────────────────


def test_activity_snapshot_delegates(monitor, subs):
    """activity_snapshot() forwards to ActivityBus.snapshot()."""
    subs["ActivityBus"].snapshot.return_value = {"idle_seconds": 120}
    result = monitor.activity_snapshot()
    assert result == {"idle_seconds": 120}


def test_activity_snapshot_returns_empty_when_none(mock_getters, _reset_singleton):
    """activity_snapshot() returns {} when ActivityBus is unavailable."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["ActivityBus"]
    mon = UnifiedMonitor()
    assert mon.activity_snapshot() == {}


# ── summary() ───────────────────────────────────────────────────────────


def test_summary_includes_running_state(monitor):
    """summary() includes the current running flag."""
    result = monitor.summary()
    assert result["running"] is False


def test_summary_includes_available_subsystems(monitor):
    """summary() includes list of available subsystem labels."""
    result = monitor.summary()
    assert "available_subsystems" in result
    assert len(result["available_subsystems"]) == len(_SUBSYSTEM_LABELS)


def test_summary_includes_metrics_collector_data(monitor, subs):
    """summary() includes metrics_collector section when available."""
    subs["MetricsCollector"].running = True
    subs["MetricsCollector"].last_system_snapshot = {"cpu_pct": 10}
    subs["MetricsCollector"].last_pipeline_summary = {"calls": 100}
    subs["MetricsCollector"].last_process_snapshot = {"pids": 5}
    result = monitor.summary()
    assert "metrics_collector" in result
    assert result["metrics_collector"]["running"] is True


# ── dashboard_data() ───────────────────────────────────────────────────


def test_dashboard_data_includes_current_resources(monitor, subs):
    """dashboard_data() includes current resource values."""
    subs["MetricsCollector"].last_system_snapshot = {
        "cpu_pct": 45.0, "ram_pct": 60.0, "gpu_vram_pct": 30.0, "gpu_temp_c": 55.0,
    }
    subs["AnomalyDetector"].anomaly_counts.return_value = {}
    subs["MetricsCollector"].alert_engine.get_status_map.return_value = {}
    subs["TrendPredictor"].degradation_report.return_value = {"degrading_count": 0, "volatile_count": 0}
    subs["MetricsCollector"].last_pipeline_summary = {"avg_latency_ms": 50}
    subs["TrendPredictor"].all_trends.return_value = []
    subs["PackTracker"].top_packs.return_value = []
    subs["AnomalyDetector"].recent_anomalies.return_value = []
    subs["TrendPredictor"].capacity_warnings.return_value = []
    subs["AlertRouter"].recent_routed.return_value = []
    subs["ActivityBus"].snapshot.return_value = {}

    data = monitor.dashboard_data()
    assert data["current"]["cpu_pct"] == 45.0
    assert "health" in data
    assert "trends" in data
    assert "alerts" in data


# ── _dictify_map() ──────────────────────────────────────────────────────


def test_dictify_map_converts_dataclass_values():
    """_dictify_map calls to_dict() on values that support it."""
    from engine.observability.unified_monitor import UnifiedMonitor

    dc_mock = MagicMock()
    dc_mock.to_dict.return_value = {"a": 1}
    result = UnifiedMonitor._dictify_map({"key": dc_mock})
    assert result == {"key": {"a": 1}}


def test_dictify_map_passes_plain_dicts():
    """_dictify_map passes through values without to_dict unchanged."""
    from engine.observability.unified_monitor import UnifiedMonitor

    result = UnifiedMonitor._dictify_map({"key": {"a": 1}})
    assert result == {"key": {"a": 1}}


def test_dictify_map_returns_non_dict_input():
    """_dictify_map returns non-dict input as-is."""
    from engine.observability.unified_monitor import UnifiedMonitor

    assert UnifiedMonitor._dictify_map([1, 2]) == [1, 2]


# ── _clamp() ────────────────────────────────────────────────────────────


def test_clamp_within_range():
    """_clamp leaves values within [0, 100] unchanged."""
    from engine.observability.unified_monitor import UnifiedMonitor

    assert UnifiedMonitor._clamp(50.0) == 50.0


def test_clamp_lower_bound():
    """_clamp floors negative values to 0."""
    from engine.observability.unified_monitor import UnifiedMonitor

    assert UnifiedMonitor._clamp(-10.0) == 0.0


def test_clamp_upper_bound():
    """_clamp caps values above 100 to 100."""
    from engine.observability.unified_monitor import UnifiedMonitor

    assert UnifiedMonitor._clamp(150.0) == 100.0


# ── Context Manager ────────────────────────────────────────────────────


def test_context_manager_not_supported(monitor):
    """UnifiedMonitor does not implement __enter__/__exit__."""
    with pytest.raises(AttributeError):
        monitor.__enter__()


# ── Singleton ───────────────────────────────────────────────────────────


def test_get_unified_monitor_returns_singleton(mock_getters, _reset_singleton):
    """get_unified_monitor() returns the same instance on repeated calls."""
    from engine.observability.unified_monitor import get_unified_monitor

    with patch("engine.observability.unified_monitor._instance", None):
        m1 = get_unified_monitor()
        # Patch _instance to the value just created so second call returns it
        with patch("engine.observability.unified_monitor._instance", m1):
            m2 = get_unified_monitor()
            assert m1 is m2


# ── _safe_call / _try_call / _try_call_list ─────────────────────────────


def test_safe_call_invokes_method():
    """_safe_call calls the named method on the given object."""
    from engine.observability.unified_monitor import UnifiedMonitor

    obj = MagicMock()
    UnifiedMonitor._safe_call(obj, "start", log="started")
    obj.start.assert_called_once()


def test_safe_call_skips_none():
    """_safe_call does nothing when obj is None."""
    from engine.observability.unified_monitor import UnifiedMonitor

    UnifiedMonitor._safe_call(None, "start")  # Should not raise


def test_safe_call_handles_exception():
    """_safe_call does not propagate exceptions from the called method."""
    from engine.observability.unified_monitor import UnifiedMonitor

    obj = MagicMock()
    obj.start.side_effect = RuntimeError("boom")
    UnifiedMonitor._safe_call(obj, "start")  # Should not raise


def test_try_call_returns_result():
    """_try_call returns the method's return value."""
    from engine.observability.unified_monitor import UnifiedMonitor

    obj = MagicMock()
    obj.snapshot.return_value = {"data": 1}
    assert UnifiedMonitor._try_call(obj, "snapshot", {}) == {"data": 1}


def test_try_call_returns_default_on_none():
    """_try_call returns default when obj is None."""
    from engine.observability.unified_monitor import UnifiedMonitor

    assert UnifiedMonitor._try_call(None, "snapshot", {"empty": True}) == {"empty": True}


def test_try_call_returns_default_on_error():
    """_try_call returns default when method raises."""
    from engine.observability.unified_monitor import UnifiedMonitor

    obj = MagicMock()
    obj.snapshot.side_effect = RuntimeError("fail")
    assert UnifiedMonitor._try_call(obj, "snapshot", {}) == {}


def test_try_call_list_returns_list():
    """_try_call_list returns the method's list result."""
    from engine.observability.unified_monitor import UnifiedMonitor

    obj = MagicMock()
    obj.items.return_value = [1, 2, 3]
    assert UnifiedMonitor._try_call_list(obj, "items") == [1, 2, 3]


def test_try_call_list_returns_empty_on_none():
    """_try_call_list returns [] when obj is None."""
    from engine.observability.unified_monitor import UnifiedMonitor

    assert UnifiedMonitor._try_call_list(None, "items") == []


def test_try_call_list_returns_empty_on_error():
    """_try_call_list returns [] when method raises."""
    from engine.observability.unified_monitor import UnifiedMonitor

    obj = MagicMock()
    obj.items.side_effect = RuntimeError("fail")
    assert UnifiedMonitor._try_call_list(obj, "items") == []


# ── _latest_system_metrics() ───────────────────────────────────────────


def test_latest_system_metrics_from_collector(monitor, subs):
    """_latest_system_metrics prefers MetricsCollector cache."""
    subs["MetricsCollector"].last_system_snapshot = {
        "cpu_pct": 33.0, "ram_pct": 44.0, "gpu_vram_pct": 55.0,
    }
    result = monitor._latest_system_metrics()
    assert result["cpu_pct"] == 33.0


def test_latest_system_metrics_falls_back_to_system_monitor(mock_getters, _reset_singleton):
    """_latest_system_metrics falls back to SystemMonitor when collector fails."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["MetricsCollector"]
    sm = mock_getters["SystemMonitor"].return_value
    sm.snapshot.return_value = {
        "cpu_percent": 50.0,
        "ram": {"percent": 60.0},
        "gpu": {"vram_percent": 70.0, "temperature": 65.0},
    }
    mon = UnifiedMonitor()
    result = mon._latest_system_metrics()
    assert result["cpu_pct"] == 50.0
    assert result["ram_pct"] == 60.0
    assert result["gpu_vram_pct"] == 70.0


def test_latest_system_metrics_returns_zeros_when_all_none(mock_getters, _reset_singleton):
    """_latest_system_metrics returns zero defaults when no subsystem is available."""
    from engine.observability.unified_monitor import UnifiedMonitor

    del mock_getters["MetricsCollector"]
    del mock_getters["SystemMonitor"]
    mon = UnifiedMonitor()
    result = mon._latest_system_metrics()
    assert result == {"cpu_pct": 0.0, "ram_pct": 0.0, "gpu_vram_pct": 0.0, "gpu_temp_c": 0.0}


# ── _wire_anomaly_routing() ────────────────────────────────────────────


def test_wire_anomaly_routing_connects_callback(monitor, subs):
    """_wire_anomaly_routing wires AlertRouter into alert engine callback."""
    engine = MagicMock()
    engine._on_alert = None
    subs["MetricsCollector"].alert_engine = engine

    monitor._wire_anomaly_routing()

    # Callback should now be set
    assert engine._on_alert is not None

    # Invoke the callback and verify routing
    alert = {"node": "sys", "level": "red"}
    engine._on_alert(alert)
    subs["AlertRouter"].route_alert.assert_called_once_with(alert)


def test_wire_anomaly_routing_preserves_original_callback(monitor, subs):
    """_wire_anomaly_routing chains with existing _on_alert callback."""
    engine = MagicMock()
    original_cb = MagicMock()
    engine._on_alert = original_cb
    subs["MetricsCollector"].alert_engine = engine

    monitor._wire_anomaly_routing()

    alert = {"node": "sys", "level": "yellow"}
    engine._on_alert(alert)
    original_cb.assert_called_once_with(alert)
    subs["AlertRouter"].route_alert.assert_called_once_with(alert)
