"""Tests for engine.observability.anomaly_detector — AnomalyDetector module."""
from __future__ import annotations

import math
import sqlite3
import statistics
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.observability.anomaly_detector import (
    AnomalyDetector,
    AnomalyEvent,
    AnomalyMethod,
    AnomalySeverity,
    MetricConfig,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def detector(tmp_path):
    """Fresh AnomalyDetector with a temp DB and low min_samples for testing."""
    return AnomalyDetector(db_path=str(tmp_path / "test.db"))


@pytest.fixture()
def seeded_detector(tmp_path):
    """AnomalyDetector pre-loaded with 50 samples around mean=100, stdev≈5."""
    det = AnomalyDetector(db_path=str(tmp_path / "seeded.db"))
    det.set_sensitivity("sys.cpu", min_samples=10)
    base_values = [100 + (i % 11 - 5) for i in range(50)]
    now = time.time()
    for i, v in enumerate(base_values):
        det._samples["sys.cpu"].append((now - 60 + i * 0.5, v))
    return det


# ── Construction ────────────────────────────────────────────────────────


def test_construction_with_custom_db_path(tmp_path):
    """AnomalyDetector creates the DB and anomaly_events table at the given path."""
    db_path = str(tmp_path / "custom.db")
    det = AnomalyDetector(db_path=db_path)

    conn = sqlite3.connect(db_path)
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    conn.close()

    assert "anomaly_events" in tables
    assert det._db_path == db_path


def test_construction_default_window(tmp_path):
    """Default window is 300 seconds unless overridden."""
    det = AnomalyDetector(db_path=str(tmp_path / "t.db"))
    assert det._default_window == 300

    det2 = AnomalyDetector(db_path=str(tmp_path / "t2.db"), default_window=600)
    assert det2._default_window == 600


# ── Feeding ─────────────────────────────────────────────────────────────


def test_feed_records_values(detector):
    """feed() appends (ts, value) tuples to the correct metric key."""
    detector.feed("sys", "cpu", 42.0)
    detector.feed("sys", "cpu", 55.0)

    key = "sys.cpu"
    assert key in detector._samples
    assert len(detector._samples[key]) == 2
    assert detector._samples[key][1][1] == 55.0


def test_feed_builds_separate_keys(detector):
    """Different node.metric pairs get separate sample buffers."""
    detector.feed("sys", "cpu", 10.0)
    detector.feed("sys", "mem", 20.0)
    detector.feed("gpu", "temp", 70.0)

    assert len(detector._samples) == 3
    assert len(detector._samples["sys.cpu"]) == 1
    assert len(detector._samples["gpu.temp"]) == 1


# ── Z-Score Detection ──────────────────────────────────────────────────


def test_evaluate_detects_zscore_anomaly(tmp_path):
    """evaluate() returns anomaly when latest value exceeds z-score threshold."""
    det = AnomalyDetector(db_path=str(tmp_path / "z.db"))
    det.set_sensitivity("sys.cpu", min_samples=10, methods=[AnomalyMethod.ZSCORE])

    now = time.time()
    for i in range(40):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0 + (i % 5)))

    # Inject extreme outlier as the latest sample
    det._samples["sys.cpu"].append((now, 200.0))

    events = det.evaluate()
    assert len(events) >= 1
    evt = events[0]
    assert evt.method == AnomalyMethod.ZSCORE
    assert evt.z_score > 3.0
    assert evt.node == "sys"
    assert evt.metric == "cpu"


def test_evaluate_no_anomaly_within_normal_range(tmp_path):
    """evaluate() returns no anomaly when values stay within threshold."""
    det = AnomalyDetector(db_path=str(tmp_path / "norm.db"))
    det.set_sensitivity("sys.cpu", min_samples=5, methods=[AnomalyMethod.ZSCORE])

    now = time.time()
    for i in range(30):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0 + (i % 3)))

    events = det.evaluate()
    assert events == []


# ── IQR Detection ──────────────────────────────────────────────────────


def test_evaluate_detects_iqr_anomaly(tmp_path):
    """evaluate() flags outliers outside Q1-k*IQR / Q3+k*IQR bounds."""
    det = AnomalyDetector(db_path=str(tmp_path / "iqr.db"))
    det.set_sensitivity("sys.mem", min_samples=10, methods=[AnomalyMethod.IQR])

    now = time.time()
    vals = list(range(40, 61))  # 40..60, IQR = 10, Q1=45, Q3=55
    for i, v in enumerate(vals):
        det._samples["sys.mem"].append((now - 1 + i * 0.01, float(v)))

    # Inject extreme outlier well outside upper fence
    det._samples["sys.mem"].append((now, 120.0))

    events = det.evaluate()
    assert len(events) >= 1
    evt = events[0]
    assert evt.method == AnomalyMethod.IQR
    assert evt.iqr_factor > 0


def test_iqr_no_anomaly_within_bounds(tmp_path):
    """Values inside IQR fences produce no anomaly."""
    det = AnomalyDetector(db_path=str(tmp_path / "iqr_ok.db"))
    det.set_sensitivity("sys.mem", min_samples=5, methods=[AnomalyMethod.IQR])

    now = time.time()
    for i in range(30):
        det._samples["sys.mem"].append((now - 1 + i * 0.01, 50.0 + (i % 5)))

    events = det.evaluate()
    assert events == []


# ── MAD Detection ──────────────────────────────────────────────────────


def test_evaluate_detects_mad_anomaly(tmp_path):
    """evaluate() detects anomaly via MAD method for extreme outliers."""
    det = AnomalyDetector(db_path=str(tmp_path / "mad.db"))
    det.set_sensitivity(
        "sys.lat",
        min_samples=10,
        methods=[AnomalyMethod.MAD],
        mad_threshold=3.0,
    )

    now = time.time()
    for i in range(40):
        det._samples["sys.lat"].append((now - 1 + i * 0.01, 100.0 + (i % 7 - 3)))

    det._samples["sys.lat"].append((now, 500.0))

    events = det.evaluate()
    assert len(events) >= 1
    assert events[0].method == AnomalyMethod.MAD
    assert events[0].mad_score > 3.0


def test_mad_no_anomaly_within_threshold(tmp_path):
    """Normal values do not trigger MAD anomalies."""
    det = AnomalyDetector(db_path=str(tmp_path / "mad_ok.db"))
    det.set_sensitivity("sys.lat", min_samples=5, methods=[AnomalyMethod.MAD])

    now = time.time()
    for i in range(30):
        det._samples["sys.lat"].append((now - 1 + i * 0.01, 50.0))

    events = det.evaluate()
    assert events == []


# ── configure_metric (set_sensitivity) ─────────────────────────────────


def test_set_sensitivity_changes_config(detector):
    """set_sensitivity stores custom parameters for a metric key."""
    detector.set_sensitivity(
        "sys.cpu",
        z_threshold=2.0,
        iqr_multiplier=2.5,
        mad_threshold=4.0,
        min_samples=20,
        cooldown_s=30.0,
        enabled=False,
    )

    cfg = detector.get_config("sys.cpu")
    assert cfg.z_threshold == 2.0
    assert cfg.iqr_multiplier == 2.5
    assert cfg.mad_threshold == 4.0
    assert cfg.min_samples == 20
    assert cfg.cooldown_s == 30.0
    assert cfg.enabled is False


def test_set_sensitivity_partial_update(detector):
    """set_sensitivity only overrides provided fields, keeping defaults."""
    detector.set_sensitivity("sys.cpu", z_threshold=2.0)
    cfg = detector.get_config("sys.cpu")

    assert cfg.z_threshold == 2.0
    assert cfg.iqr_multiplier == 1.5  # default
    assert cfg.min_samples == 30      # default


def test_get_config_falls_back_to_default(detector):
    """get_config returns default MetricConfig for unconfigured metrics."""
    cfg = detector.get_config("unknown.metric")
    assert cfg.z_threshold == 3.0
    assert cfg.min_samples == 30


def test_set_sensitivity_changes_methods(detector):
    """set_sensitivity can replace the methods list entirely."""
    detector.set_sensitivity("sys.cpu", methods=[AnomalyMethod.MAD])
    cfg = detector.get_config("sys.cpu")
    assert cfg.methods == [AnomalyMethod.MAD]


# ── Cooldown ───────────────────────────────────────────────────────────


def test_cooldown_prevents_duplicate_anomalies(tmp_path):
    """After reporting an anomaly, the same metric is suppressed for cooldown_s."""
    det = AnomalyDetector(db_path=str(tmp_path / "cd.db"))
    det.set_sensitivity(
        "sys.cpu",
        min_samples=10,
        cooldown_s=120.0,
        methods=[AnomalyMethod.ZSCORE],
    )

    now = time.time()
    for i in range(40):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0 + (i % 3)))
    det._samples["sys.cpu"].append((now, 500.0))

    first = det.evaluate()
    assert len(first) >= 1

    # Second evaluation immediately — should be suppressed by cooldown
    det._samples["sys.cpu"].append((time.time(), 600.0))
    second = det.evaluate()
    assert second == []


def test_cooldown_expires_allows_new_anomaly(tmp_path):
    """After cooldown expires, new anomalies are reported again."""
    det = AnomalyDetector(db_path=str(tmp_path / "cd2.db"))
    det.set_sensitivity(
        "sys.cpu",
        min_samples=10,
        cooldown_s=0.0,  # zero cooldown
        methods=[AnomalyMethod.ZSCORE],
    )

    now = time.time()
    for i in range(40):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0 + (i % 3)))
    det._samples["sys.cpu"].append((now, 500.0))

    first = det.evaluate()
    assert len(first) >= 1

    # With zero cooldown, the next evaluate should also fire
    det._last_anomaly_ts["sys.cpu"] = 0.0  # simulate expiry
    det._samples["sys.cpu"].append((time.time(), 600.0))
    second = det.evaluate()
    assert len(second) >= 1


# ── Severity Classification ───────────────────────────────────────────


def test_severity_from_z_low():
    """Z-score ratio < 1.5 maps to LOW severity."""
    sev = AnomalyDetector._severity_from_z(3.0, 3.0)  # ratio=1.0
    assert sev == AnomalySeverity.LOW


def test_severity_from_z_medium():
    """Z-score ratio >= 1.5 and < 2.0 maps to MEDIUM severity."""
    sev = AnomalyDetector._severity_from_z(4.5, 3.0)  # ratio=1.5
    assert sev == AnomalySeverity.MEDIUM


def test_severity_from_z_high():
    """Z-score ratio >= 2.0 and < 3.0 maps to HIGH severity."""
    sev = AnomalyDetector._severity_from_z(6.0, 3.0)  # ratio=2.0
    assert sev == AnomalySeverity.HIGH


def test_severity_from_z_critical():
    """Z-score ratio >= 3.0 maps to CRITICAL severity."""
    sev = AnomalyDetector._severity_from_z(9.0, 3.0)  # ratio=3.0
    assert sev == AnomalySeverity.CRITICAL


def test_severity_from_iqr_low():
    """IQR factor ratio < 1.5 maps to LOW severity."""
    sev = AnomalyDetector._severity_from_iqr(1.5, 1.5)  # ratio=1.0
    assert sev == AnomalySeverity.LOW


def test_severity_from_iqr_medium():
    """IQR factor ratio >= 1.5 and < 2.5 maps to MEDIUM severity."""
    sev = AnomalyDetector._severity_from_iqr(3.0, 1.5)  # ratio=2.0
    assert sev == AnomalySeverity.MEDIUM


def test_severity_from_iqr_high():
    """IQR factor ratio >= 2.5 and < 4.0 maps to HIGH severity."""
    sev = AnomalyDetector._severity_from_iqr(4.5, 1.5)  # ratio=3.0
    assert sev == AnomalySeverity.HIGH


def test_severity_from_iqr_critical():
    """IQR factor ratio >= 4.0 maps to CRITICAL severity."""
    sev = AnomalyDetector._severity_from_iqr(6.0, 1.5)  # ratio=4.0
    assert sev == AnomalySeverity.CRITICAL


# ── baseline_stats ─────────────────────────────────────────────────────


def test_baseline_stats_returns_correct_values(detector):
    """baseline_stats() computes mean, stdev, median, q1, q3, iqr, and count."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
    now = time.time()
    for v in values:
        detector._samples["sys.cpu"].append((now, v))

    stats = detector.baseline_stats("sys", "cpu")
    assert stats["sample_count"] == 8
    assert stats["mean"] == round(statistics.mean(values), 4)
    assert stats["stdev"] == round(statistics.stdev(values), 4)
    assert stats["median"] == round(statistics.median(values), 4)
    assert stats["min"] == 10.0
    assert stats["max"] == 80.0
    assert stats["iqr"] >= 0


def test_baseline_stats_empty_metric(detector):
    """baseline_stats() returns sample_count=0 for unknown metrics."""
    stats = detector.baseline_stats("nonexistent", "metric")
    assert stats == {"sample_count": 0}


def test_baseline_stats_single_sample(detector):
    """baseline_stats() returns sample_count=0 for fewer than 2 samples."""
    detector._samples["sys.cpu"].append((time.time(), 42.0))
    stats = detector.baseline_stats("sys", "cpu")
    assert stats == {"sample_count": 0}


# ── recent_anomalies ──────────────────────────────────────────────────


def test_recent_anomalies_returns_persisted_events(tmp_path):
    """recent_anomalies() retrieves anomalies from the database."""
    det = AnomalyDetector(db_path=str(tmp_path / "ra.db"))
    det.set_sensitivity(
        "sys.cpu",
        min_samples=10,
        cooldown_s=0.0,
        methods=[AnomalyMethod.ZSCORE],
    )

    now = time.time()
    for i in range(40):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0 + (i % 3)))
    det._samples["sys.cpu"].append((now, 500.0))

    det.evaluate()

    results = det.recent_anomalies(n=10)
    assert len(results) >= 1
    assert results[0]["node"] == "sys"
    assert results[0]["metric"] == "cpu"
    assert results[0]["method"] == "zscore"


def test_recent_anomalies_filtered_by_node(tmp_path):
    """recent_anomalies(node=X) only returns anomalies for that node."""
    det = AnomalyDetector(db_path=str(tmp_path / "rf.db"))

    # Manually persist two anomalies for different nodes
    event_a = AnomalyEvent(
        node="gpu", metric="temp", value=99.0, expected_mean=60.0,
        deviation=39.0, method=AnomalyMethod.ZSCORE,
        severity=AnomalySeverity.HIGH, timestamp=time.time(), z_score=5.0,
    )
    event_b = AnomalyEvent(
        node="sys", metric="cpu", value=99.0, expected_mean=50.0,
        deviation=49.0, method=AnomalyMethod.ZSCORE,
        severity=AnomalySeverity.LOW, timestamp=time.time(), z_score=3.5,
    )
    det._persist_anomaly(event_a)
    det._persist_anomaly(event_b)

    gpu_only = det.recent_anomalies(n=10, node="gpu")
    assert all(r["node"] == "gpu" for r in gpu_only)
    assert len(gpu_only) == 1


def test_recent_anomalies_filtered_by_severity(tmp_path):
    """recent_anomalies(severity=X) only returns matching severity."""
    det = AnomalyDetector(db_path=str(tmp_path / "rs.db"))

    event = AnomalyEvent(
        node="sys", metric="cpu", value=200.0, expected_mean=50.0,
        deviation=150.0, method=AnomalyMethod.ZSCORE,
        severity=AnomalySeverity.CRITICAL, timestamp=time.time(), z_score=10.0,
    )
    det._persist_anomaly(event)

    crit_only = det.recent_anomalies(n=10, severity="critical")
    assert len(crit_only) == 1
    assert crit_only[0]["severity"] == "critical"

    low_only = det.recent_anomalies(n=10, severity="low")
    assert len(low_only) == 0


# ── Database Persistence ──────────────────────────────────────────────


def test_anomaly_persisted_to_database(tmp_path):
    """evaluate() writes anomaly events to the SQLite database."""
    db_path = str(tmp_path / "persist.db")
    det = AnomalyDetector(db_path=db_path)
    det.set_sensitivity(
        "sys.cpu",
        min_samples=10,
        cooldown_s=0.0,
        methods=[AnomalyMethod.ZSCORE],
    )

    now = time.time()
    for i in range(40):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0 + (i % 3)))
    det._samples["sys.cpu"].append((now, 500.0))

    det.evaluate()

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT * FROM anomaly_events").fetchall()
    conn.close()

    assert len(rows) >= 1


def test_persist_anomaly_stores_all_fields(tmp_path):
    """_persist_anomaly writes all AnomalyEvent fields to the database."""
    db_path = str(tmp_path / "fields.db")
    det = AnomalyDetector(db_path=db_path)

    event = AnomalyEvent(
        node="test_node",
        metric="test_metric",
        value=123.456,
        expected_mean=50.0,
        deviation=73.456,
        method=AnomalyMethod.IQR,
        severity=AnomalySeverity.HIGH,
        timestamp=1000000.0,
        z_score=4.5,
        iqr_factor=3.2,
        mad_score=0.0,
        baseline_window=100,
        message="Test anomaly",
    )
    det._persist_anomaly(event)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute("SELECT * FROM anomaly_events LIMIT 1").fetchone())
    conn.close()

    assert row["node"] == "test_node"
    assert row["metric"] == "test_metric"
    assert abs(row["value"] - 123.456) < 0.001
    assert row["method"] == "iqr"
    assert row["severity"] == "high"
    assert row["baseline_window"] == 100
    assert row["message"] == "Test anomaly"


# ── Edge Cases ─────────────────────────────────────────────────────────


def test_insufficient_data_skips_evaluation(tmp_path):
    """evaluate() produces no anomalies when sample count < min_samples."""
    det = AnomalyDetector(db_path=str(tmp_path / "insuf.db"))
    det.set_sensitivity("sys.cpu", min_samples=100)

    now = time.time()
    for i in range(10):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0))

    events = det.evaluate()
    assert events == []


def test_constant_values_zero_stdev_no_zscore_anomaly(tmp_path):
    """Z-score detection returns None when stdev is zero (all identical values)."""
    det = AnomalyDetector(db_path=str(tmp_path / "const.db"))
    det.set_sensitivity(
        "sys.cpu",
        min_samples=5,
        methods=[AnomalyMethod.ZSCORE],
    )

    now = time.time()
    for i in range(30):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0))

    events = det.evaluate()
    assert events == []


def test_constant_values_zero_iqr_no_anomaly(tmp_path):
    """IQR detection returns None when IQR is zero (all identical values)."""
    det = AnomalyDetector(db_path=str(tmp_path / "const_iqr.db"))
    det.set_sensitivity(
        "sys.cpu",
        min_samples=5,
        methods=[AnomalyMethod.IQR],
    )

    now = time.time()
    for i in range(30):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0))

    events = det.evaluate()
    assert events == []


def test_constant_values_zero_mad_no_anomaly(tmp_path):
    """MAD detection returns None when MAD is zero (all identical values)."""
    det = AnomalyDetector(db_path=str(tmp_path / "const_mad.db"))
    det.set_sensitivity(
        "sys.cpu",
        min_samples=5,
        methods=[AnomalyMethod.MAD],
    )

    now = time.time()
    for i in range(30):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0))

    events = det.evaluate()
    assert events == []


def test_nan_feed_does_not_crash_feed(tmp_path):
    """Feeding NaN via feed() stores the value without crashing."""
    det = AnomalyDetector(db_path=str(tmp_path / "nan.db"))
    det.feed("sys", "cpu", float("nan"))

    key = "sys.cpu"
    assert len(det._samples[key]) == 1
    assert math.isnan(det._samples[key][0][1])


def test_nan_in_baseline_raises_on_evaluate(tmp_path):
    """NaN in the sample window causes statistics.stdev to raise.

    This documents real module behavior — NaN is not gracefully handled
    by the stdlib statistics module during evaluate().
    """
    det = AnomalyDetector(db_path=str(tmp_path / "nan2.db"))
    det.set_sensitivity(
        "sys.cpu",
        min_samples=5,
        methods=[AnomalyMethod.ZSCORE],
    )

    now = time.time()
    for i in range(30):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0 + (i % 5)))
    det._samples["sys.cpu"].append((now, float("nan")))

    with pytest.raises((AttributeError, ValueError)):
        det.evaluate()


def test_disabled_metric_skips_evaluation(tmp_path):
    """Disabled metrics are skipped during evaluate()."""
    det = AnomalyDetector(db_path=str(tmp_path / "dis.db"))
    det.set_sensitivity("sys.cpu", enabled=False, min_samples=5)

    now = time.time()
    for i in range(40):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0 + (i % 3)))
    det._samples["sys.cpu"].append((now, 500.0))

    events = det.evaluate()
    assert events == []


# ── Callback ───────────────────────────────────────────────────────────


def test_on_anomaly_callback_fires(tmp_path):
    """on_anomaly callback is invoked when an anomaly is detected."""
    callback = MagicMock()
    det = AnomalyDetector(db_path=str(tmp_path / "cb.db"), on_anomaly=callback)
    det.set_sensitivity(
        "sys.cpu",
        min_samples=10,
        cooldown_s=0.0,
        methods=[AnomalyMethod.ZSCORE],
    )

    now = time.time()
    for i in range(40):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0 + (i % 3)))
    det._samples["sys.cpu"].append((now, 500.0))

    det.evaluate()
    assert callback.call_count >= 1
    event_arg = callback.call_args[0][0]
    assert isinstance(event_arg, AnomalyEvent)


def test_callback_exception_does_not_crash(tmp_path):
    """A failing callback does not prevent evaluate() from completing."""
    def bad_callback(event):
        raise RuntimeError("boom")

    det = AnomalyDetector(db_path=str(tmp_path / "bad_cb.db"), on_anomaly=bad_callback)
    det.set_sensitivity(
        "sys.cpu",
        min_samples=10,
        cooldown_s=0.0,
        methods=[AnomalyMethod.ZSCORE],
    )

    now = time.time()
    for i in range(40):
        det._samples["sys.cpu"].append((now - 1 + i * 0.01, 50.0 + (i % 3)))
    det._samples["sys.cpu"].append((now, 500.0))

    events = det.evaluate()
    assert len(events) >= 1


# ── AnomalyEvent Data Model ──────────────────────────────────────────


def test_anomaly_event_to_dict():
    """AnomalyEvent.to_dict() produces correct serialized representation."""
    evt = AnomalyEvent(
        node="gpu",
        metric="temp",
        value=95.1234,
        expected_mean=60.5678,
        deviation=34.5556,
        method=AnomalyMethod.ZSCORE,
        severity=AnomalySeverity.HIGH,
        timestamp=1700000000.0,
        z_score=5.12345,
        iqr_factor=0.0,
        mad_score=0.0,
        baseline_window=50,
        message="Test",
    )
    d = evt.to_dict()

    assert d["node"] == "gpu"
    assert d["metric"] == "temp"
    assert d["value"] == round(95.1234, 4)
    assert d["method"] == "zscore"
    assert d["severity"] == "high"
    assert d["z_score"] == round(5.12345, 2)
    assert d["ts"] == 1700000000.0
    assert d["baseline_window"] == 50


# ── Snapshot ───────────────────────────────────────────────────────────


def test_snapshot_structure(tmp_path):
    """snapshot() returns dict with expected top-level keys."""
    det = AnomalyDetector(db_path=str(tmp_path / "snap.db"))
    det.feed("sys", "cpu", 42.0)

    snap = det.snapshot()
    assert "tracked_metrics" in snap
    assert "anomalies_1h" in snap
    assert "anomalies_24h" in snap
    assert "counts_by_node" in snap
    assert "recent" in snap
    assert snap["tracked_metrics"] >= 1


# ── Prune ──────────────────────────────────────────────────────────────


def test_prune_removes_old_events(tmp_path):
    """prune() deletes events older than max_age_hours."""
    det = AnomalyDetector(db_path=str(tmp_path / "prune.db"))

    old_event = AnomalyEvent(
        node="sys", metric="cpu", value=200.0, expected_mean=50.0,
        deviation=150.0, method=AnomalyMethod.ZSCORE,
        severity=AnomalySeverity.HIGH,
        timestamp=time.time() - 999999,  # very old
        z_score=8.0,
    )
    new_event = AnomalyEvent(
        node="sys", metric="cpu", value=200.0, expected_mean=50.0,
        deviation=150.0, method=AnomalyMethod.ZSCORE,
        severity=AnomalySeverity.HIGH,
        timestamp=time.time(),
        z_score=8.0,
    )
    det._persist_anomaly(old_event)
    det._persist_anomaly(new_event)

    deleted = det.prune(max_age_hours=1.0)
    assert deleted >= 1

    remaining = det.recent_anomalies(n=100)
    assert len(remaining) == 1


# ── Anomaly Counts ─────────────────────────────────────────────────────


def test_anomaly_counts_groups_by_node_and_severity(tmp_path):
    """anomaly_counts() returns {node: {severity: count}} for the window."""
    det = AnomalyDetector(db_path=str(tmp_path / "counts.db"))

    now = time.time()
    for sev in [AnomalySeverity.LOW, AnomalySeverity.LOW, AnomalySeverity.HIGH]:
        evt = AnomalyEvent(
            node="sys", metric="cpu", value=200.0, expected_mean=50.0,
            deviation=150.0, method=AnomalyMethod.ZSCORE,
            severity=sev, timestamp=now, z_score=5.0,
        )
        det._persist_anomaly(evt)

    counts = det.anomaly_counts(hours=1.0)
    assert counts["sys"]["low"] == 2
    assert counts["sys"]["high"] == 1


# ── MetricConfig Defaults ─────────────────────────────────────────────


def test_metric_config_defaults():
    """MetricConfig default values are sensible."""
    cfg = MetricConfig()
    assert cfg.z_threshold == 3.0
    assert cfg.iqr_multiplier == 1.5
    assert cfg.mad_threshold == 3.5
    assert cfg.min_samples == 30
    assert cfg.enabled is True
    assert cfg.cooldown_s == 60.0
    assert AnomalyMethod.ZSCORE in cfg.methods
    assert AnomalyMethod.IQR in cfg.methods


# ── Window Filtering ──────────────────────────────────────────────────


def test_evaluate_only_considers_window_samples(tmp_path):
    """evaluate() ignores samples outside the default_window."""
    det = AnomalyDetector(db_path=str(tmp_path / "win.db"), default_window=10)
    det.set_sensitivity("sys.cpu", min_samples=5, methods=[AnomalyMethod.ZSCORE])

    now = time.time()
    # Old samples outside window (>10s ago) — large outliers
    for i in range(20):
        det._samples["sys.cpu"].append((now - 100 + i, 500.0))

    # Recent samples within window — normal values
    for i in range(20):
        det._samples["sys.cpu"].append((now - 5 + i * 0.2, 50.0 + (i % 3)))

    events = det.evaluate()
    assert events == []
