"""Tests for engine.observability.correlation_engine — CorrelationEngine module."""
from __future__ import annotations

import math
import sqlite3
import time
from unittest.mock import patch

import pytest

from engine.observability.correlation_engine import (
    CorrelationEngine,
    CorrelationResult,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_engine(tmp_path, **kwargs):
    """Create a fresh CorrelationEngine backed by a temp database."""
    defaults = {"db_path": str(tmp_path / "test.db"), "min_samples": 5}
    defaults.update(kwargs)
    return CorrelationEngine(**defaults)


def _feed_linear(engine: CorrelationEngine, n: int = 30, *, offset: float = 0.0):
    """Feed two positively-correlated linear series (y = x)."""
    base = time.time()
    for i in range(n):
        ts = base + i
        with patch("time.time", return_value=ts):
            engine.feed("sys", "cpu", float(i) + offset)
            engine.feed("pipe", "latency", float(i) * 2 + offset)


def _feed_inverse(engine: CorrelationEngine, n: int = 30):
    """Feed two negatively-correlated linear series (y = -x)."""
    base = time.time()
    for i in range(n):
        ts = base + i
        with patch("time.time", return_value=ts):
            engine.feed("sys", "cpu", float(i))
            engine.feed("pipe", "latency", float(n - i))


def _feed_constant(engine: CorrelationEngine, n: int = 30):
    """Feed a constant-value series and a varying series."""
    base = time.time()
    for i in range(n):
        ts = base + i
        with patch("time.time", return_value=ts):
            engine.feed("sys", "cpu", 42.0)
            engine.feed("pipe", "latency", float(i))


# ── Construction ────────────────────────────────────────────────────────


def test_construction_with_custom_db_path(tmp_path):
    """Engine creates its DB file and initialises the schema."""
    db_file = tmp_path / "test.db"
    engine = CorrelationEngine(db_path=str(db_file))

    assert db_file.exists()
    conn = sqlite3.connect(str(db_file))
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    assert "metric_correlations" in tables


def test_construction_defaults(tmp_path):
    """Engine uses sensible defaults for window and min_samples."""
    engine = _make_engine(tmp_path)
    assert engine._default_window == 300.0
    assert engine._min_samples == 5


def test_snapshot_empty_engine(tmp_path):
    """Snapshot on a fresh engine returns zeroed counters."""
    engine = _make_engine(tmp_path)
    snap = engine.snapshot()

    assert snap["tracked_metrics"] == 0
    assert snap["cache_size"] == 0
    assert snap["history_size"] == 0
    assert snap["metric_keys"] == []


# ── feed() ──────────────────────────────────────────────────────────────


def test_feed_records_data_points(tmp_path):
    """feed() stores samples keyed by 'node.metric'."""
    engine = _make_engine(tmp_path)
    engine.feed("sys", "cpu", 42.0)
    engine.feed("sys", "cpu", 55.0)

    assert "sys.cpu" in engine._samples
    assert len(engine._samples["sys.cpu"]) == 2
    assert engine._samples["sys.cpu"][-1][1] == 55.0


def test_feed_creates_separate_keys(tmp_path):
    """Different node/metric combos get separate buffers."""
    engine = _make_engine(tmp_path)
    engine.feed("sys", "cpu", 1.0)
    engine.feed("sys", "mem", 2.0)
    engine.feed("pipe", "latency", 3.0)

    assert engine.tracked_metrics() == ["sys.cpu", "sys.mem", "pipe.latency"]


# ── correlate() — positive correlation ──────────────────────────────────


def test_correlate_positive_linear(tmp_path):
    """Perfectly correlated linear series yields Pearson r ≈ 1.0."""
    engine = _make_engine(tmp_path, default_window=600)
    _feed_linear(engine, n=30)

    # Use a future time so all samples are inside the window
    with patch("time.time", return_value=time.time() + 1):
        result = engine.correlate("sys.cpu", "pipe.latency")

    assert result is not None
    assert result.pearson_r == pytest.approx(1.0, abs=0.01)
    assert result.direction == "positive"
    assert result.strength == "strong"
    assert result.sample_count >= 5


def test_correlate_returns_correlation_result_type(tmp_path):
    """correlate() returns a CorrelationResult dataclass."""
    engine = _make_engine(tmp_path, default_window=600)
    _feed_linear(engine, n=30)

    with patch("time.time", return_value=time.time() + 1):
        result = engine.correlate("sys.cpu", "pipe.latency")

    assert isinstance(result, CorrelationResult)
    d = result.to_dict()
    assert "pearson_r" in d
    assert "spearman_r" in d
    assert "strength" in d
    assert "direction" in d


# ── correlate() — negative correlation ──────────────────────────────────


def test_correlate_negative_linear(tmp_path):
    """Inversely correlated series yields Pearson r ≈ -1.0."""
    engine = _make_engine(tmp_path, default_window=600)
    _feed_inverse(engine, n=30)

    with patch("time.time", return_value=time.time() + 1):
        result = engine.correlate("sys.cpu", "pipe.latency")

    assert result is not None
    assert result.pearson_r == pytest.approx(-1.0, abs=0.01)
    assert result.direction == "negative"
    assert result.strength == "strong"


# ── correlate() — Spearman ──────────────────────────────────────────────


def test_correlate_spearman_monotonic(tmp_path):
    """Monotonic non-linear series has Spearman ρ ≈ 1.0."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("a", "x", float(i))
            engine.feed("a", "y", float(i ** 2))  # monotonic, non-linear

    with patch("time.time", return_value=base + 31):
        result = engine.correlate("a.x", "a.y")

    assert result is not None
    assert result.spearman_r == pytest.approx(1.0, abs=0.01)


def test_spearman_handles_tied_ranks(tmp_path):
    """Spearman handles duplicate values (tied ranks) gracefully."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("t", "a", float(i % 5))
            engine.feed("t", "b", float(i))

    with patch("time.time", return_value=base + 31):
        result = engine.correlate("t.a", "t.b")

    # Should still return a result even with many ties
    assert result is not None
    assert -1.0 <= result.spearman_r <= 1.0


# ── correlation_matrix() ───────────────────────────────────────────────


def test_correlation_matrix_multiple_metrics(tmp_path):
    """Matrix returns pairwise results for all fed metrics above min_r."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("a", "m1", float(i))
            engine.feed("a", "m2", float(i) * 2)
            engine.feed("a", "m3", float(i) * -1)

    with patch("time.time", return_value=base + 31):
        results = engine.correlation_matrix(min_r=0.3, window_s=600)

    # Should find correlations between m1-m2 (positive), m1-m3 (negative), m2-m3 (negative)
    assert len(results) >= 2
    pairs = {(r.metric_a, r.metric_b) for r in results}
    # At least m1-m2 pair should be present
    assert any("a.m1" in p and "a.m2" in p for p in pairs)


def test_correlation_matrix_sorted_by_abs_r(tmp_path):
    """Matrix results are sorted by |r| descending."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("a", "m1", float(i))
            engine.feed("a", "m2", float(i) * 2)
            engine.feed("a", "m3", float(i) + (i % 3) * 0.5)

    with patch("time.time", return_value=base + 31):
        results = engine.correlation_matrix(min_r=0.3, window_s=600)

    if len(results) >= 2:
        abs_r = [max(abs(r.pearson_r), abs(r.spearman_r)) for r in results]
        assert abs_r == sorted(abs_r, reverse=True)


def test_correlation_matrix_filters_below_min_r(tmp_path):
    """Matrix excludes pairs with |r| below min_r."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("a", "m1", float(i))
            engine.feed("a", "m2", float(i) * 2)

    with patch("time.time", return_value=base + 31):
        results = engine.correlation_matrix(min_r=0.99, window_s=600)

    # Perfect correlation ≈ 1.0 should still appear at 0.99 threshold
    assert len(results) >= 1
    for r in results:
        assert max(abs(r.pearson_r), abs(r.spearman_r)) >= 0.99


# ── discover_correlations() ────────────────────────────────────────────


def test_discover_correlations_finds_strong(tmp_path):
    """discover_correlations() identifies strong correlations above threshold."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("sys", "cpu", float(i))
            engine.feed("sys", "mem", float(i) * 1.5)

    with patch("time.time", return_value=base + 31):
        discovery = engine.discover_correlations(min_r=0.5, window_s=600)

    assert "total_pairs_checked" in discovery
    assert "significant_correlations" in discovery
    assert "strong" in discovery
    assert "moderate" in discovery
    assert "correlations" in discovery
    assert discovery["significant_correlations"] >= 1
    assert discovery["strong"] >= 1


def test_discover_correlations_returns_dict_format(tmp_path):
    """discover_correlations() returns serialisable dict with expected keys."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("a", "x", float(i))
            engine.feed("b", "y", float(i))

    with patch("time.time", return_value=base + 31):
        discovery = engine.discover_correlations(min_r=0.3, window_s=600)

    for entry in discovery["correlations"]:
        assert "metric_a" in entry
        assert "pearson_r" in entry
        assert "strength" in entry


# ── Time Alignment / max_gap_s ─────────────────────────────────────────


def test_align_series_pairs_close_timestamps():
    """_align_series pairs samples within max_gap_s."""
    a = [(1.0, 10), (2.0, 20), (3.0, 30)]
    b = [(1.1, 11), (2.1, 21), (3.1, 31)]

    paired_a, paired_b = CorrelationEngine._align_series(a, b, max_gap_s=0.5)
    assert len(paired_a) == 3
    assert len(paired_b) == 3


def test_align_series_rejects_distant_timestamps():
    """_align_series drops samples that exceed max_gap_s."""
    a = [(1.0, 10), (10.0, 20), (20.0, 30)]
    b = [(1.5, 11), (50.0, 21), (80.0, 31)]  # only b[0] close to a[0]

    paired_a, paired_b = CorrelationEngine._align_series(a, b, max_gap_s=1.0)
    assert len(paired_a) == 1


def test_align_series_swaps_when_a_longer():
    """_align_series handles case where series A is longer than B."""
    a = [(1.0, 10), (2.0, 20), (3.0, 30), (4.0, 40)]
    b = [(1.0, 11), (3.0, 31)]

    paired_a, paired_b = CorrelationEngine._align_series(a, b, max_gap_s=0.5)
    assert len(paired_a) == len(paired_b)
    assert len(paired_a) == 2


def test_align_series_empty_series():
    """_align_series returns empty lists for empty input."""
    paired_a, paired_b = CorrelationEngine._align_series([], [(1.0, 10)])
    assert paired_a == []
    assert paired_b == []


def test_correlate_respects_time_window(tmp_path):
    """Samples outside the time window are excluded from correlation."""
    engine = _make_engine(tmp_path, default_window=10, min_samples=3)
    base = time.time()

    # Old samples (outside window)
    for i in range(10):
        with patch("time.time", return_value=base - 100 + i):
            engine.feed("a", "x", 999.0)
            engine.feed("a", "y", -999.0)

    # Recent samples (inside window)
    for i in range(10):
        with patch("time.time", return_value=base + i):
            engine.feed("a", "x", float(i))
            engine.feed("a", "y", float(i) * 2)

    with patch("time.time", return_value=base + 10):
        result = engine.correlate("a.x", "a.y", window_s=15)

    assert result is not None
    assert result.pearson_r == pytest.approx(1.0, abs=0.05)


# ── cross_reference() ──────────────────────────────────────────────────


def test_cross_reference_returns_related_metrics(tmp_path):
    """cross_reference() finds correlations between two domains."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("sys", "cpu", float(i))
            engine.feed("pipe", "latency", float(i) * 3)

    with patch("time.time", return_value=base + 31):
        results = engine.cross_reference("sys", "pipe", window_s=600)

    assert len(results) >= 1
    assert results[0].metric_a.startswith("sys.") or results[0].metric_b.startswith("sys.")


def test_cross_reference_empty_for_unrelated_domains(tmp_path):
    """cross_reference() returns empty when domains have no shared metrics."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("sys", "cpu", float(i))

    with patch("time.time", return_value=base + 31):
        results = engine.cross_reference("sys", "nonexistent", window_s=600)

    assert results == []


def test_cross_reference_filters_negligible(tmp_path):
    """cross_reference() excludes negligible-strength correlations."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    import random
    rng = random.Random(42)
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("sys", "cpu", rng.random() * 100)
            engine.feed("pipe", "lat", rng.random() * 100)

    with patch("time.time", return_value=base + 31):
        results = engine.cross_reference("sys", "pipe", window_s=600)

    for r in results:
        assert r.strength != "negligible"


# ── Database persistence ────────────────────────────────────────────────


def test_persist_correlation_writes_to_db(tmp_path):
    """Strong/moderate correlations from matrix are persisted to SQLite."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("db", "read", float(i))
            engine.feed("db", "write", float(i) * 2)

    with patch("time.time", return_value=base + 31):
        engine.correlation_matrix(min_r=0.3, window_s=600)

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    rows = conn.execute("SELECT * FROM metric_correlations").fetchall()
    conn.close()
    assert len(rows) >= 1


def test_strongest_correlations_reads_from_db(tmp_path):
    """strongest_correlations() queries persisted results."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("db", "r", float(i))
            engine.feed("db", "w", float(i) * 2)

    with patch("time.time", return_value=base + 31):
        engine.correlation_matrix(min_r=0.3, window_s=600)

    strongest = engine.strongest_correlations(hours=1, n=10)
    assert len(strongest) >= 1
    assert "pearson_r" in strongest[0]


def test_prune_deletes_old_records(tmp_path):
    """prune() removes correlation records older than max_age_hours."""
    engine = _make_engine(tmp_path, default_window=600)
    db_path = str(tmp_path / "test.db")

    # Insert an old record directly
    conn = sqlite3.connect(db_path)
    old_ts = time.time() - 999999
    conn.execute(
        "INSERT INTO metric_correlations "
        "(ts, metric_a, metric_b, pearson_r, spearman_r, sample_count) "
        "VALUES (?, 'a', 'b', 0.9, 0.9, 30)",
        (old_ts,),
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM metric_correlations").fetchone()[0] == 1
    conn.close()

    deleted = engine.prune(max_age_hours=1.0)
    assert deleted >= 1

    conn = sqlite3.connect(db_path)
    remaining = conn.execute("SELECT COUNT(*) FROM metric_correlations").fetchone()[0]
    conn.close()
    assert remaining == 0


# ── Edge cases ──────────────────────────────────────────────────────────


def test_correlate_returns_none_insufficient_data(tmp_path):
    """correlate() returns None when fewer samples than min_samples."""
    engine = _make_engine(tmp_path, min_samples=20, default_window=600)
    base = time.time()
    for i in range(5):
        with patch("time.time", return_value=base + i):
            engine.feed("a", "x", float(i))
            engine.feed("a", "y", float(i))

    with patch("time.time", return_value=base + 6):
        result = engine.correlate("a.x", "a.y", window_s=600)

    assert result is None


def test_correlate_returns_none_unknown_metric(tmp_path):
    """correlate() returns None for metrics that have never been fed."""
    engine = _make_engine(tmp_path)
    result = engine.correlate("nonexistent.a", "nonexistent.b")
    assert result is None


def test_correlate_constant_series_returns_zero_r(tmp_path):
    """Constant series (zero variance) yields Pearson r = 0.0."""
    engine = _make_engine(tmp_path, default_window=600)
    _feed_constant(engine, n=30)

    with patch("time.time", return_value=time.time() + 1):
        result = engine.correlate("sys.cpu", "pipe.latency")

    assert result is not None
    assert result.pearson_r == 0.0


def test_pearson_single_data_point():
    """Pearson returns 0.0 for fewer than 2 data points."""
    assert CorrelationEngine._pearson([1.0], [2.0]) == 0.0
    assert CorrelationEngine._pearson([], []) == 0.0


def test_spearman_single_data_point():
    """Spearman returns 0.0 for fewer than 2 data points."""
    assert CorrelationEngine._spearman([1.0], [2.0]) == 0.0


def test_approx_p_value_boundary_cases():
    """p-value approximation handles edge cases correctly."""
    assert CorrelationEngine._approx_p_value(0.0, 2) == 1.0  # n <= 2
    assert CorrelationEngine._approx_p_value(1.0, 10) == 1.0  # |r| >= 1
    assert CorrelationEngine._approx_p_value(-1.0, 10) == 1.0

    p = CorrelationEngine._approx_p_value(0.99, 100)
    assert p < 0.01  # highly significant


def test_correlate_caches_result(tmp_path):
    """Repeated correlate() calls use cached result within TTL."""
    engine = _make_engine(tmp_path, default_window=600)
    _feed_linear(engine, n=30)

    now = time.time() + 1
    with patch("time.time", return_value=now):
        r1 = engine.correlate("sys.cpu", "pipe.latency")
        r2 = engine.correlate("sys.cpu", "pipe.latency")

    assert r1 is r2  # same object from cache


def test_correlate_cache_key_is_order_independent(tmp_path):
    """Cache key normalises metric order so (A,B) == (B,A)."""
    engine = _make_engine(tmp_path, default_window=600)
    _feed_linear(engine, n=30)

    now = time.time() + 1
    with patch("time.time", return_value=now):
        r1 = engine.correlate("sys.cpu", "pipe.latency")

    # Clear the direct cache entry and try reversed order
    assert r1 is not None
    with patch("time.time", return_value=now):
        r2 = engine.correlate("pipe.latency", "sys.cpu")

    assert r2 is not None
    assert r1.pearson_r == r2.pearson_r


def test_recent_correlations_returns_history(tmp_path):
    """recent_correlations() returns items from the in-memory history ring."""
    engine = _make_engine(tmp_path, default_window=600)
    base = time.time()
    for i in range(30):
        with patch("time.time", return_value=base + i):
            engine.feed("h", "a", float(i))
            engine.feed("h", "b", float(i) * 2)

    with patch("time.time", return_value=base + 31):
        engine.correlation_matrix(min_r=0.3, window_s=600)

    recent = engine.recent_correlations(n=5)
    assert len(recent) >= 1
    assert "pearson_r" in recent[0]


# ── CorrelationResult dataclass ─────────────────────────────────────────


def test_correlation_result_strength_classification():
    """CorrelationResult.__post_init__ classifies strength correctly."""
    strong = CorrelationResult("a", "b", 0.85, 0.80, 30, 0.001)
    assert strong.strength == "strong"

    moderate = CorrelationResult("a", "b", 0.55, 0.50, 30, 0.01)
    assert moderate.strength == "moderate"

    weak = CorrelationResult("a", "b", 0.35, 0.30, 30, 0.05)
    assert weak.strength == "weak"

    negligible = CorrelationResult("a", "b", 0.1, 0.05, 30, 0.5)
    assert negligible.strength == "negligible"


def test_correlation_result_direction_classification():
    """CorrelationResult.__post_init__ classifies direction correctly."""
    pos = CorrelationResult("a", "b", 0.9, 0.8, 30, 0.001)
    assert pos.direction == "positive"

    neg = CorrelationResult("a", "b", -0.9, -0.8, 30, 0.001)
    assert neg.direction == "negative"


def test_correlation_result_to_dict_keys():
    """to_dict() produces all expected keys with rounded values."""
    cr = CorrelationResult("a.x", "b.y", 0.8765, 0.8234, 50, 0.00123, lag_seconds=1.5)
    d = cr.to_dict()

    assert d["metric_a"] == "a.x"
    assert d["metric_b"] == "b.y"
    assert d["pearson_r"] == 0.8765
    assert d["spearman_r"] == 0.8234
    assert d["sample_count"] == 50
    assert d["lag_seconds"] == 1.5
    assert d["strength"] == "strong"
    assert d["direction"] == "positive"
