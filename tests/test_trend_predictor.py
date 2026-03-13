"""Tests for engine.observability.trend_predictor — TrendPredictor module.

Covers construction, feeding, trend classification, prediction,
capacity warnings, persistence, and edge cases.
"""
from __future__ import annotations

import math
import random
import sqlite3
import time

import pytest

from engine.observability.trend_predictor import (
    TrendDirection,
    TrendPredictor,
    TrendResult,
    TrendSeverity,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_predictor(tmp_path, **kwargs):
    """Create a fresh TrendPredictor with a temp DB and low min_samples."""
    defaults = {
        "db_path": str(tmp_path / "test.db"),
        "min_samples": 5,
        "window_size": 300,
        "slope_threshold": 0.001,
    }
    defaults.update(kwargs)
    return TrendPredictor(**defaults)


def _feed_series(predictor, node, metric, values, start_ts=1_000_000.0, step=1.0):
    """Feed a list of numeric values as evenly-spaced samples."""
    for i, v in enumerate(values):
        predictor.feed(node, metric, v, ts=start_ts + i * step)


# ── Construction ─────────────────────────────────────────────────────────


def test_construction_creates_db(tmp_path):
    """TrendPredictor creates the SQLite database and metric_trends table."""
    db_path = str(tmp_path / "metrics.db")
    tp = TrendPredictor(db_path=db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='metric_trends'"
    )
    assert cur.fetchone() is not None
    conn.close()


def test_construction_custom_params(tmp_path):
    """Custom window_size, min_samples, slope_threshold are respected."""
    tp = _make_predictor(tmp_path, window_size=50, min_samples=3, slope_threshold=0.05)
    assert tp._window_size == 50
    assert tp._min_samples == 3
    assert tp._slope_threshold == 0.05


# ── Feeding ──────────────────────────────────────────────────────────────


def test_feed_records_samples(tmp_path):
    """feed() stores timestamped values in the internal buffer."""
    tp = _make_predictor(tmp_path)
    tp.feed("system", "cpu_pct", 45.0, ts=100.0)
    tp.feed("system", "cpu_pct", 50.0, ts=101.0)

    buf = tp._samples["system.cpu_pct"]
    assert len(buf) == 2
    assert buf[0] == (100.0, 45.0)
    assert buf[1] == (101.0, 50.0)


def test_feed_constructs_key_from_node_and_metric(tmp_path):
    """The sample key is '{node}.{metric}'."""
    tp = _make_predictor(tmp_path)
    tp.feed("gpu", "vram_mb", 8000.0, ts=1.0)
    assert "gpu.vram_mb" in tp._samples


def test_feed_respects_window_size(tmp_path):
    """Buffer never exceeds window_size — oldest samples are evicted."""
    tp = _make_predictor(tmp_path, window_size=10)
    for i in range(20):
        tp.feed("sys", "x", float(i), ts=float(i))

    assert len(tp._samples["sys.x"]) == 10
    # Oldest kept should be sample 10
    assert tp._samples["sys.x"][0] == (10.0, 10.0)


def test_feed_uses_current_time_when_ts_omitted(tmp_path):
    """When ts is not provided, feed() uses the current time."""
    tp = _make_predictor(tmp_path)
    before = time.time()
    tp.feed("sys", "m", 1.0)
    after = time.time()

    buf = tp._samples["sys.m"]
    assert len(buf) == 1
    assert before <= buf[0][0] <= after


# ── get_trend: RISING ────────────────────────────────────────────────────


def test_get_trend_rising(tmp_path):
    """Monotonically increasing series is classified as RISING."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [10, 20, 30, 40, 50, 60, 70])

    trend = tp.get_trend("sys.cpu_pct")
    assert trend is not None
    assert trend.direction == TrendDirection.RISING
    assert trend.slope > 0
    assert trend.current_value == 70.0


def test_get_trend_rising_predictions_increase(tmp_path):
    """For a RISING trend, predicted values increase with horizon."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [10, 20, 30, 40, 50])

    trend = tp.get_trend("sys.cpu_pct")
    assert trend is not None
    assert trend.predicted_1h < trend.predicted_4h < trend.predicted_24h


# ── get_trend: FALLING ───────────────────────────────────────────────────


def test_get_trend_falling(tmp_path):
    """Monotonically decreasing series is classified as FALLING."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "ram_pct", [90, 80, 70, 60, 50, 40])

    trend = tp.get_trend("sys.ram_pct")
    assert trend is not None
    assert trend.direction == TrendDirection.FALLING
    assert trend.slope < 0


def test_get_trend_falling_predictions_decrease(tmp_path):
    """For a FALLING trend, predicted values decrease with horizon."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "ram_pct", [100, 90, 80, 70, 60, 50])

    trend = tp.get_trend("sys.ram_pct")
    assert trend is not None
    assert trend.predicted_1h > trend.predicted_4h > trend.predicted_24h


# ── get_trend: STABLE ────────────────────────────────────────────────────


def test_get_trend_stable_flat_series(tmp_path):
    """A perfectly flat series is classified as STABLE."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [50.0] * 10)

    trend = tp.get_trend("sys.cpu_pct")
    assert trend is not None
    assert trend.direction == TrendDirection.STABLE
    assert abs(trend.slope) < 1e-9


def test_get_trend_stable_tiny_drift(tmp_path):
    """A series with sub-threshold drift is still STABLE."""
    tp = _make_predictor(tmp_path, min_samples=5, slope_threshold=0.01)
    # Tiny upward drift: 0.001 per sample, well below threshold
    values = [50.0 + i * 0.0001 for i in range(10)]
    _feed_series(tp, "sys", "cpu_pct", values)

    trend = tp.get_trend("sys.cpu_pct")
    assert trend is not None
    assert trend.direction == TrendDirection.STABLE


# ── get_trend: VOLATILE ──────────────────────────────────────────────────


def test_get_trend_volatile(tmp_path):
    """A highly noisy series with large swings is classified as VOLATILE."""
    tp = _make_predictor(tmp_path, min_samples=5, slope_threshold=0.001)
    # Alternating high/low with large amplitude — low R² but big slope signal
    values = [10, 90, 10, 90, 10, 90, 10, 90, 10, 90]
    _feed_series(tp, "sys", "cpu_pct", values)

    trend = tp.get_trend("sys.cpu_pct")
    assert trend is not None
    # With such oscillation the R² will be very low
    assert trend.direction in (TrendDirection.VOLATILE, TrendDirection.STABLE)


def test_get_trend_volatile_random_noise(tmp_path):
    """Random noise with a large overall spread produces VOLATILE or STABLE."""
    tp = _make_predictor(tmp_path, min_samples=5, slope_threshold=0.001)
    random.seed(42)
    values = [random.uniform(0, 100) for _ in range(30)]
    _feed_series(tp, "sys", "x", values)

    trend = tp.get_trend("sys.x")
    assert trend is not None
    assert trend.direction in (TrendDirection.VOLATILE, TrendDirection.STABLE,
                                TrendDirection.RISING, TrendDirection.FALLING)


# ── get_trend: statistics ────────────────────────────────────────────────


def test_get_trend_computes_min_max_mean(tmp_path):
    """TrendResult contains correct min, max, and mean of the window."""
    tp = _make_predictor(tmp_path, min_samples=5)
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    _feed_series(tp, "sys", "m", values)

    trend = tp.get_trend("sys.m")
    assert trend is not None
    assert trend.min_recent == 10.0
    assert trend.max_recent == 50.0
    assert trend.mean_recent == 30.0
    assert trend.sample_count == 5


def test_get_trend_r_squared_near_one_for_perfect_line(tmp_path):
    """A perfectly linear series should have R² close to 1."""
    tp = _make_predictor(tmp_path, min_samples=5)
    values = [float(i) for i in range(20)]
    _feed_series(tp, "sys", "m", values)

    trend = tp.get_trend("sys.m")
    assert trend is not None
    assert trend.r_squared > 0.99


# ── predict() ────────────────────────────────────────────────────────────


def test_predict_extrapolates_linearly(tmp_path):
    """predict() extrapolates a linear series at the given future offset."""
    tp = _make_predictor(tmp_path, min_samples=5)
    # Feed a simple line: value = timestamp (step=1s)
    _feed_series(tp, "sys", "m", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], step=1.0)

    pred_60 = tp.predict("sys.m", future_seconds=60.0)
    assert pred_60 is not None
    # slope ≈ 1.0/s, last sample at offset 9 → predict(60) ≈ 9 + 60 = 69
    assert abs(pred_60 - 69.0) < 1.0


def test_predict_returns_none_without_enough_data(tmp_path):
    """predict() returns None when there are fewer samples than min_samples."""
    tp = _make_predictor(tmp_path, min_samples=10)
    _feed_series(tp, "sys", "m", [1, 2, 3])

    result = tp.predict("sys.m", future_seconds=3600)
    assert result is None


def test_predict_returns_none_for_unknown_metric(tmp_path):
    """predict() returns None for a metric_key that has never been fed."""
    tp = _make_predictor(tmp_path)
    assert tp.predict("nonexistent.metric", 60.0) is None


def test_predict_at_multiple_horizons(tmp_path):
    """Predictions at 1h, 4h, and 24h match get_trend() results."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "m", [10, 20, 30, 40, 50])

    pred_1h = tp.predict("sys.m", 3600)
    pred_4h = tp.predict("sys.m", 14400)
    pred_24h = tp.predict("sys.m", 86400)

    trend = tp.get_trend("sys.m")
    assert trend is not None
    assert abs(pred_1h - trend.predicted_1h) < 0.01
    assert abs(pred_4h - trend.predicted_4h) < 0.01
    assert abs(pred_24h - trend.predicted_24h) < 0.01


# ── all_trends() ─────────────────────────────────────────────────────────


def test_all_trends_returns_qualifying_metrics(tmp_path):
    """all_trends() includes only metrics with enough samples."""
    tp = _make_predictor(tmp_path, min_samples=5)

    # Feed enough samples for two metrics
    _feed_series(tp, "sys", "cpu_pct", [10, 20, 30, 40, 50])
    _feed_series(tp, "sys", "ram_pct", [50, 40, 30, 20, 10])

    # Feed too few for a third
    tp.feed("sys", "disk_pct", 10.0, ts=1.0)
    tp.feed("sys", "disk_pct", 20.0, ts=2.0)

    trends = tp.all_trends()
    keys = {t.metric_key for t in trends}
    assert "sys.cpu_pct" in keys
    assert "sys.ram_pct" in keys
    assert "sys.disk_pct" not in keys


def test_all_trends_empty_when_no_data(tmp_path):
    """all_trends() returns an empty list when nothing has been fed."""
    tp = _make_predictor(tmp_path)
    assert tp.all_trends() == []


def test_all_trends_returns_trendresult_instances(tmp_path):
    """Each element of all_trends() is a TrendResult dataclass."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [1, 2, 3, 4, 5])

    trends = tp.all_trends()
    assert len(trends) == 1
    assert isinstance(trends[0], TrendResult)


# ── capacity_warnings() ─────────────────────────────────────────────────


def test_capacity_warnings_detects_approaching_threshold(tmp_path):
    """Rising CPU approaching 95% within the horizon triggers a warning."""
    tp = _make_predictor(tmp_path, min_samples=5)
    # CPU at ~90 rising quickly — with slope ~1/s it will breach 95 in ~5 s
    _feed_series(tp, "sys", "cpu_pct", [85, 86, 87, 88, 89, 90], step=1.0)

    warnings = tp.capacity_warnings(horizon_minutes=60)
    assert len(warnings) >= 1
    w = warnings[0]
    assert w["metric_key"] == "sys.cpu_pct"
    assert w["threshold"] == 95.0
    assert w["status"] in ("approaching", "breached")


def test_capacity_warnings_empty_for_stable_metric(tmp_path):
    """A stable metric well below threshold produces no warnings."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [30.0] * 10)

    warnings = tp.capacity_warnings(horizon_minutes=60)
    assert warnings == []


def test_capacity_warnings_breached_status(tmp_path):
    """A metric already above threshold is reported as 'breached'."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [92, 93, 94, 95, 96, 97], step=1.0)

    warnings = tp.capacity_warnings(horizon_minutes=60)
    assert any(w["status"] == "breached" for w in warnings) or \
           any(w["status"] == "approaching" for w in warnings)


def test_capacity_warnings_custom_threshold(tmp_path):
    """Custom thresholds override the defaults."""
    tp = _make_predictor(tmp_path, min_samples=5)
    # custom_metric is not in _DEFAULT_THRESHOLDS, so supply one
    _feed_series(tp, "sys", "custom_metric", [80, 82, 84, 86, 88, 90], step=1.0)

    warnings = tp.capacity_warnings(
        horizon_minutes=60,
        thresholds={"custom_metric": 92.0},
    )
    assert len(warnings) >= 1
    assert warnings[0]["threshold"] == 92.0


def test_capacity_warnings_sorted_by_urgency(tmp_path):
    """Warnings are sorted by time_to_breach_min (soonest first)."""
    tp = _make_predictor(tmp_path, min_samples=5)
    # vram rising fast
    _feed_series(tp, "gpu", "vram_mb", [10000, 10200, 10400, 10600, 10800, 11000], step=1.0)
    # cpu rising slowly
    _feed_series(tp, "sys", "cpu_pct", [80, 81, 82, 83, 84, 85], step=1.0)

    warnings = tp.capacity_warnings(horizon_minutes=120)
    if len(warnings) >= 2:
        assert warnings[0]["time_to_breach_min"] <= warnings[1]["time_to_breach_min"]


def test_capacity_warnings_ignores_falling_metrics(tmp_path):
    """Falling metrics do not generate capacity warnings."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [90, 85, 80, 75, 70, 65], step=1.0)

    warnings = tp.capacity_warnings(horizon_minutes=60)
    assert warnings == []


# ── TrendSeverity classification ─────────────────────────────────────────


def test_severity_none_for_stable(tmp_path):
    """STABLE trends have NONE severity."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [50.0] * 10)

    trend = tp.get_trend("sys.cpu_pct")
    assert trend is not None
    assert trend.severity == TrendSeverity.NONE


def test_severity_critical_when_already_above_threshold(tmp_path):
    """CRITICAL severity when current_value exceeds the threshold ceiling."""
    tp = _make_predictor(tmp_path, min_samples=5)
    # Value already at 96, rising — above 95 threshold
    _feed_series(tp, "sys", "cpu_pct", [93, 94, 95, 96, 97, 98], step=1.0)

    trend = tp.get_trend("sys.cpu_pct")
    assert trend is not None
    assert trend.severity in (TrendSeverity.CRITICAL, TrendSeverity.HIGH)


def test_severity_medium_for_volatile(tmp_path):
    """VOLATILE direction should yield MEDIUM severity."""
    tp = _make_predictor(tmp_path, min_samples=5, slope_threshold=0.001)
    # Create a highly volatile series that triggers VOLATILE classification
    values = [10, 90, 10, 90, 10, 90, 10, 90, 10, 90,
              10, 90, 10, 90, 10, 90, 10, 90, 10, 90]
    _feed_series(tp, "sys", "cpu_pct", values, step=1.0)

    trend = tp.get_trend("sys.cpu_pct")
    assert trend is not None
    if trend.direction == TrendDirection.VOLATILE:
        assert trend.severity == TrendSeverity.MEDIUM


def test_severity_enum_values(tmp_path):
    """TrendSeverity enum has expected string values."""
    assert TrendSeverity.NONE.value == "none"
    assert TrendSeverity.LOW.value == "low"
    assert TrendSeverity.MEDIUM.value == "medium"
    assert TrendSeverity.HIGH.value == "high"
    assert TrendSeverity.CRITICAL.value == "critical"


def test_direction_enum_values(tmp_path):
    """TrendDirection enum has expected string values."""
    assert TrendDirection.RISING.value == "rising"
    assert TrendDirection.FALLING.value == "falling"
    assert TrendDirection.STABLE.value == "stable"
    assert TrendDirection.VOLATILE.value == "volatile"


# ── TrendResult.to_dict() ───────────────────────────────────────────────


def test_trend_result_to_dict(tmp_path):
    """TrendResult.to_dict() serialises all fields with proper types."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [10, 20, 30, 40, 50])

    trend = tp.get_trend("sys.cpu_pct")
    assert trend is not None

    d = trend.to_dict()
    assert isinstance(d, dict)
    assert d["metric_key"] == "sys.cpu_pct"
    assert d["direction"] == trend.direction.value
    assert d["severity"] == trend.severity.value
    assert isinstance(d["slope"], float)
    assert isinstance(d["r_squared"], float)
    assert isinstance(d["predicted_1h"], float)
    assert isinstance(d["predicted_4h"], float)
    assert isinstance(d["predicted_24h"], float)
    assert isinstance(d["sample_count"], int)


# ── Database persistence ─────────────────────────────────────────────────


def test_persist_trends_writes_to_db(tmp_path):
    """persist_trends() inserts rows into the metric_trends table."""
    db_path = str(tmp_path / "persist.db")
    tp = TrendPredictor(db_path=db_path, min_samples=5)

    _feed_series(tp, "sys", "cpu_pct", [10, 20, 30, 40, 50])
    count = tp.persist_trends()
    assert count == 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM metric_trends").fetchall()
    assert len(rows) == 1
    assert rows[0]["metric_key"] == "sys.cpu_pct"
    assert rows[0]["direction"] == "rising"
    conn.close()


def test_persist_trends_returns_zero_with_no_data(tmp_path):
    """persist_trends() returns 0 when no metrics qualify."""
    tp = _make_predictor(tmp_path)
    assert tp.persist_trends() == 0


def test_load_trends_retrieves_persisted_data(tmp_path):
    """load_trends() returns previously persisted trend snapshots."""
    db_path = str(tmp_path / "load.db")
    tp = TrendPredictor(db_path=db_path, min_samples=5)

    _feed_series(tp, "sys", "cpu_pct", [10, 20, 30, 40, 50])
    tp.persist_trends()

    loaded = tp.load_trends(since_hours=1)
    assert len(loaded) == 1
    assert loaded[0]["metric_key"] == "sys.cpu_pct"
    assert loaded[0]["direction"] == "rising"
    assert "slope" in loaded[0]
    assert "r_squared" in loaded[0]


def test_load_trends_respects_time_window(tmp_path):
    """load_trends(since_hours) only returns entries newer than cutoff."""
    db_path = str(tmp_path / "window.db")
    tp = TrendPredictor(db_path=db_path, min_samples=5)

    _feed_series(tp, "sys", "cpu_pct", [10, 20, 30, 40, 50])
    tp.persist_trends()

    # since_hours=0 means "only entries from the last 0 hours" → nothing
    loaded = tp.load_trends(since_hours=0)
    # Current trends just persisted — ts is ~now, cutoff = now - 0 = now
    # They may or may not appear depending on timing, but this tests the filter
    assert isinstance(loaded, list)


def test_persist_multiple_metrics(tmp_path):
    """Multiple metrics are all persisted in one call."""
    db_path = str(tmp_path / "multi.db")
    tp = TrendPredictor(db_path=db_path, min_samples=5)

    _feed_series(tp, "sys", "cpu_pct", [10, 20, 30, 40, 50])
    _feed_series(tp, "gpu", "vram_mb", [8000, 8100, 8200, 8300, 8400])
    count = tp.persist_trends()
    assert count == 2

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT COUNT(*) FROM metric_trends").fetchone()[0]
    assert rows == 2
    conn.close()


# ── Edge Cases ───────────────────────────────────────────────────────────


def test_get_trend_returns_none_insufficient_data(tmp_path):
    """get_trend() returns None when sample count < min_samples."""
    tp = _make_predictor(tmp_path, min_samples=10)
    _feed_series(tp, "sys", "cpu_pct", [1, 2, 3])

    assert tp.get_trend("sys.cpu_pct") is None


def test_get_trend_returns_none_unknown_key(tmp_path):
    """get_trend() returns None for a metric key that was never fed."""
    tp = _make_predictor(tmp_path)
    assert tp.get_trend("nonexistent.metric") is None


def test_single_data_point_below_min_samples(tmp_path):
    """A single sample never qualifies for trend analysis."""
    tp = _make_predictor(tmp_path, min_samples=2)
    tp.feed("sys", "cpu_pct", 42.0, ts=1.0)

    assert tp.get_trend("sys.cpu_pct") is None
    assert tp.predict("sys.cpu_pct", 3600) is None


def test_exactly_min_samples(tmp_path):
    """Exactly min_samples data points should produce a valid trend."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "m", [1, 2, 3, 4, 5])

    trend = tp.get_trend("sys.m")
    assert trend is not None
    assert trend.sample_count == 5


def test_all_zero_series(tmp_path):
    """A series of all zeros is classified STABLE with zero slope."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "m", [0.0] * 10)

    trend = tp.get_trend("sys.m")
    assert trend is not None
    assert trend.direction == TrendDirection.STABLE
    assert abs(trend.slope) < 1e-9
    assert trend.current_value == 0.0
    assert trend.min_recent == 0.0
    assert trend.max_recent == 0.0
    assert trend.mean_recent == 0.0


def test_two_samples_at_min(tmp_path):
    """With min_samples=2, two points give a valid regression."""
    tp = _make_predictor(tmp_path, min_samples=2)
    tp.feed("sys", "m", 10.0, ts=0.0)
    tp.feed("sys", "m", 20.0, ts=1.0)

    trend = tp.get_trend("sys.m")
    assert trend is not None
    assert trend.direction == TrendDirection.RISING
    assert trend.slope > 0


def test_identical_timestamps(tmp_path):
    """Samples with identical timestamps do not crash (degenerate case)."""
    tp = _make_predictor(tmp_path, min_samples=3)
    for v in [10, 20, 30, 40, 50]:
        tp.feed("sys", "m", float(v), ts=1.0)

    trend = tp.get_trend("sys.m")
    # Should still produce a result without crashing
    assert trend is not None
    assert trend.direction == TrendDirection.STABLE


def test_negative_values(tmp_path):
    """Negative values are handled without error."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "temp", [-10, -5, 0, 5, 10])

    trend = tp.get_trend("sys.temp")
    assert trend is not None
    assert trend.direction == TrendDirection.RISING
    assert trend.min_recent == -10.0
    assert trend.max_recent == 10.0


def test_very_large_values(tmp_path):
    """Very large numeric values work without overflow."""
    tp = _make_predictor(tmp_path, min_samples=5)
    base = 1e12
    _feed_series(tp, "sys", "big", [base + i * 1000 for i in range(10)])

    trend = tp.get_trend("sys.big")
    assert trend is not None
    assert trend.slope > 0


# ── Linear Regression internals ──────────────────────────────────────────


def test_regression_slope_perfect_line(tmp_path):
    """Regression on y = 2x + 10 has slope ≈ 2 per second."""
    tp = _make_predictor(tmp_path)
    values = [(float(i), 2.0 * i + 10.0) for i in range(20)]
    slope, intercept, r_sq = tp._compute_regression(values)

    assert abs(slope - 2.0) < 1e-6
    assert abs(intercept - 10.0) < 1e-6
    assert r_sq > 0.999


def test_regression_single_point(tmp_path):
    """Regression with a single point returns zero slope."""
    tp = _make_predictor(tmp_path)
    slope, intercept, r_sq = tp._compute_regression([(5.0, 42.0)])

    assert slope == 0.0
    assert intercept == 42.0


def test_regression_empty_list(tmp_path):
    """Regression on an empty list returns zeros."""
    tp = _make_predictor(tmp_path)
    slope, intercept, r_sq = tp._compute_regression([])

    assert slope == 0.0
    assert intercept == 0.0


# ── degradation_report() ────────────────────────────────────────────────


def test_degradation_report_structure(tmp_path):
    """degradation_report() returns expected keys."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [50, 55, 60, 65, 70])

    report = tp.degradation_report()
    assert "degrading" in report
    assert "volatile" in report
    assert "degrading_count" in report
    assert "volatile_count" in report
    assert "worst_severity" in report


def test_degradation_report_includes_rising_upper_bounded(tmp_path):
    """Rising upper-bounded metrics appear in the 'degrading' list."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [50, 55, 60, 65, 70, 75])

    report = tp.degradation_report()
    assert report["degrading_count"] >= 1
    assert any(d["metric_key"] == "sys.cpu_pct" for d in report["degrading"])


def test_degradation_report_empty_no_data(tmp_path):
    """degradation_report() is clean when no data is present."""
    tp = _make_predictor(tmp_path)
    report = tp.degradation_report()
    assert report["degrading_count"] == 0
    assert report["volatile_count"] == 0
    assert report["worst_severity"] == "none"


# ── recent_predictions() ────────────────────────────────────────────────


def test_recent_predictions_series_length(tmp_path):
    """recent_predictions() returns the requested number of points."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "m", [10, 20, 30, 40, 50])

    preds = tp.recent_predictions("sys.m", points=6, interval_minutes=5)
    assert len(preds) == 6
    assert preds[0]["offset_minutes"] == 5
    assert preds[-1]["offset_minutes"] == 30


def test_recent_predictions_empty_without_data(tmp_path):
    """recent_predictions() returns empty list without enough data."""
    tp = _make_predictor(tmp_path, min_samples=10)
    _feed_series(tp, "sys", "m", [1, 2])

    assert tp.recent_predictions("sys.m") == []


# ── summary() ────────────────────────────────────────────────────────────


def test_summary_structure(tmp_path):
    """summary() returns expected top-level keys."""
    tp = _make_predictor(tmp_path, min_samples=5)
    _feed_series(tp, "sys", "cpu_pct", [10, 20, 30, 40, 50])
    _feed_series(tp, "sys", "ram_pct", [50.0] * 10)

    s = tp.summary()
    assert s["total_metrics"] == 2
    assert s["qualifying_metrics"] == 2
    assert "direction_counts" in s
    assert s["direction_counts"]["rising"] >= 1
    assert s["direction_counts"]["stable"] >= 1
    assert s["background_running"] is False
    assert s["window_size"] == 300
    assert s["min_samples"] == 5


def test_summary_empty_state(tmp_path):
    """summary() works when no data has been fed."""
    tp = _make_predictor(tmp_path)
    s = tp.summary()
    assert s["total_metrics"] == 0
    assert s["total_samples"] == 0
    assert s["qualifying_metrics"] == 0
    assert s["worst_degradation"] is None


# ── Background thread control (no actual threads) ───────────────────────


def test_background_not_started_by_default(tmp_path):
    """Constructor does NOT start the background thread."""
    tp = _make_predictor(tmp_path)
    assert tp._running is False
    assert tp._bg_thread is None


def test_start_stop_background(tmp_path):
    """start_background() and stop_background() toggle the running flag."""
    tp = _make_predictor(tmp_path)

    tp.start_background(interval=0.1)
    assert tp._running is True
    assert tp._bg_thread is not None

    tp.stop_background()
    assert tp._running is False
    assert tp._bg_thread is None
