"""Tests for engine.observability.metric_dimensions — DimensionStore and helpers.

Covers: helpers, init, record, record_batch, query raw/aggregated,
tag operations, get_summary, prune, export, and edge cases.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time

import pytest

from engine.observability.metric_dimensions import (
    AggregationResult,
    DimensionalMetric,
    DimensionStore,
    TagCardinality,
    _percentile,
    _stddev,
    get_dimension_store,
)


# ──── Helpers ────────────────────────────────────────────────────────────────


def _fresh_store(tmp_path, name: str = "test.db") -> DimensionStore:
    """Create an isolated DimensionStore pointing at a temp database."""
    return DimensionStore(str(tmp_path / name))


# ──── _percentile edge cases ────────────────────────────────────────────────


class TestPercentile:
    """Tests for the _percentile helper."""

    def test_single_element(self):
        """Single-element list always returns that element."""
        assert _percentile([42.0], 0) == 42.0
        assert _percentile([42.0], 50) == 42.0
        assert _percentile([42.0], 100) == 42.0

    def test_two_elements_median(self):
        """Median of two elements is the average."""
        result = _percentile([1.0, 3.0], 50)
        assert result == pytest.approx(2.0)

    def test_p0_returns_min(self):
        """p0 returns the minimum value."""
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert _percentile(vals, 0) == pytest.approx(10.0)

    def test_p100_returns_max(self):
        """p100 returns the maximum value."""
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert _percentile(vals, 100) == pytest.approx(50.0)

    def test_interpolation(self):
        """p25 of [0, 10, 20, 30] is interpolated correctly."""
        vals = [0.0, 10.0, 20.0, 30.0]
        result = _percentile(vals, 25)
        # rank = 0.25 * 3 = 0.75 → lower=0, upper=1, frac=0.75
        expected = 0.0 + 0.75 * (10.0 - 0.0)
        assert result == pytest.approx(expected)


# ──── _stddev ────────────────────────────────────────────────────────────────


class TestStddev:
    """Tests for the _stddev helper."""

    def test_single_value_returns_zero(self):
        """Single-element list has zero stddev."""
        assert _stddev([5.0], 5.0) == 0.0

    def test_empty_returns_zero(self):
        """Empty list has zero stddev."""
        assert _stddev([], 0.0) == 0.0

    def test_known_stddev(self):
        """Population stddev of [2, 4, 4, 4, 5, 5, 7, 9] is 2.0."""
        vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        mean = sum(vals) / len(vals)
        result = _stddev(vals, mean)
        assert result == pytest.approx(2.0)

    def test_identical_values(self):
        """All-same values have zero stddev."""
        vals = [3.0, 3.0, 3.0, 3.0]
        assert _stddev(vals, 3.0) == pytest.approx(0.0)


# ──── DimensionStore init ────────────────────────────────────────────────────


class TestDimensionStoreInit:
    """Tests for DimensionStore construction."""

    def test_creates_database_file(self, tmp_path):
        """Init creates the SQLite database on disk."""
        db_path = tmp_path / "init_test.db"
        DimensionStore(str(db_path))
        assert db_path.exists()

    def test_tables_exist(self, tmp_path):
        """Init creates dimensional_metrics and metric_tags tables."""
        db_path = tmp_path / "tables_test.db"
        DimensionStore(str(db_path))
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cur.fetchall()}
        conn.close()
        assert "dimensional_metrics" in tables
        assert "metric_tags" in tables

    def test_fresh_state_no_metrics(self, tmp_path):
        """A fresh store has no metrics."""
        store = _fresh_store(tmp_path)
        names = store.get_metric_names()
        assert names == []


# ──── record ─────────────────────────────────────────────────────────────────


class TestRecord:
    """Tests for DimensionStore.record()."""

    def test_basic_record(self, tmp_path):
        """Recording a metric returns a positive integer id."""
        store = _fresh_store(tmp_path)
        mid = store.record("latency_ms", 42.0)
        assert isinstance(mid, int)
        assert mid > 0

    def test_record_with_tags(self, tmp_path):
        """Tags are stored and retrievable."""
        store = _fresh_store(tmp_path)
        tags = {"agent": "alice", "scene": "bedroom"}
        mid = store.record("latency_ms", 55.0, tags=tags)
        rows = store.query("latency_ms", filters={"agent": "alice"})
        assert len(rows) == 1
        assert rows[0].tags["agent"] == "alice"
        assert rows[0].tags["scene"] == "bedroom"

    def test_record_without_tags(self, tmp_path):
        """Recording without tags succeeds and stores empty dict."""
        store = _fresh_store(tmp_path)
        mid = store.record("cpu_pct", 75.5)
        rows = store.query("cpu_pct")
        assert len(rows) == 1
        assert rows[0].tags == {}

    def test_record_returns_incrementing_ids(self, tmp_path):
        """Successive records return increasing ids."""
        store = _fresh_store(tmp_path)
        id1 = store.record("m", 1.0)
        id2 = store.record("m", 2.0)
        id3 = store.record("m", 3.0)
        assert id1 < id2 < id3

    def test_record_increments_count(self, tmp_path):
        """Each record increases the metric count."""
        store = _fresh_store(tmp_path)
        store.record("m", 1.0)
        store.record("m", 2.0)
        rows = store.query("m")
        assert len(rows) == 2

    def test_timestamp_defaults_to_now(self, tmp_path):
        """Timestamp defaults close to current time when not specified."""
        store = _fresh_store(tmp_path)
        before = time.time()
        store.record("m", 1.0)
        after = time.time()
        rows = store.query("m")
        assert before <= rows[0].timestamp <= after


# ──── record_batch ───────────────────────────────────────────────────────────


class TestRecordBatch:
    """Tests for DimensionStore.record_batch()."""

    def test_basic_batch(self, tmp_path):
        """Batch insert stores all metrics."""
        store = _fresh_store(tmp_path)
        metrics = [
            DimensionalMetric("m1", 10.0),
            DimensionalMetric("m1", 20.0),
            DimensionalMetric("m2", 30.0),
        ]
        ids = store.record_batch(metrics)
        assert len(ids) == 3

    def test_empty_batch(self, tmp_path):
        """Empty batch returns empty list without error."""
        store = _fresh_store(tmp_path)
        ids = store.record_batch([])
        assert ids == []

    def test_batch_returns_correct_ids(self, tmp_path):
        """Returned ids are unique and ordered."""
        store = _fresh_store(tmp_path)
        metrics = [DimensionalMetric("m", float(i)) for i in range(5)]
        ids = store.record_batch(metrics)
        assert len(ids) == 5
        assert len(set(ids)) == 5
        assert ids == sorted(ids)

    def test_batch_tags_propagated(self, tmp_path):
        """Tags on batch items are stored correctly."""
        store = _fresh_store(tmp_path)
        metrics = [
            DimensionalMetric("m", 1.0, tags={"env": "prod"}),
            DimensionalMetric("m", 2.0, tags={"env": "dev"}),
        ]
        store.record_batch(metrics)
        prod_rows = store.query("m", filters={"env": "prod"})
        dev_rows = store.query("m", filters={"env": "dev"})
        assert len(prod_rows) == 1
        assert len(dev_rows) == 1
        assert prod_rows[0].value == 1.0
        assert dev_rows[0].value == 2.0


# ──── query raw ──────────────────────────────────────────────────────────────


class TestQueryRaw:
    """Tests for DimensionStore.query() in raw mode."""

    def test_query_by_name(self, tmp_path):
        """Query returns only metrics matching the name."""
        store = _fresh_store(tmp_path)
        store.record("alpha", 1.0)
        store.record("beta", 2.0)
        store.record("alpha", 3.0)
        rows = store.query("alpha")
        assert len(rows) == 2
        assert all(r.name == "alpha" for r in rows)

    def test_query_with_filters(self, tmp_path):
        """Tag filters restrict results."""
        store = _fresh_store(tmp_path)
        store.record("m", 1.0, tags={"color": "red"})
        store.record("m", 2.0, tags={"color": "blue"})
        store.record("m", 3.0, tags={"color": "red"})
        rows = store.query("m", filters={"color": "blue"})
        assert len(rows) == 1
        assert rows[0].value == 2.0

    def test_query_with_window(self, tmp_path):
        """Window restricts to recent metrics only."""
        store = _fresh_store(tmp_path)
        old_ts = time.time() - 3600
        store.record("m", 1.0, timestamp=old_ts)
        store.record("m", 2.0)  # current
        rows = store.query("m", window_seconds=600)
        assert len(rows) == 1
        assert rows[0].value == 2.0

    def test_query_no_results(self, tmp_path):
        """Query for non-existent metric returns empty list."""
        store = _fresh_store(tmp_path)
        rows = store.query("nonexistent")
        assert rows == []

    def test_query_limit(self, tmp_path):
        """Limit caps the number of returned rows."""
        store = _fresh_store(tmp_path)
        for i in range(10):
            store.record("m", float(i))
        rows = store.query("m", limit=3)
        assert len(rows) == 3

    def test_query_multiple_tag_filters(self, tmp_path):
        """Multiple tag filters are AND-ed together."""
        store = _fresh_store(tmp_path)
        store.record("m", 1.0, tags={"env": "prod", "region": "us"})
        store.record("m", 2.0, tags={"env": "prod", "region": "eu"})
        store.record("m", 3.0, tags={"env": "dev", "region": "us"})
        rows = store.query("m", filters={"env": "prod", "region": "us"})
        assert len(rows) == 1
        assert rows[0].value == 1.0


# ──── query aggregated ───────────────────────────────────────────────────────


class TestQueryAggregated:
    """Tests for DimensionStore.query() with group_by aggregation."""

    def _seed(self, store: DimensionStore) -> None:
        """Seed a store with known data for aggregation tests."""
        for val, agent in [(10.0, "alice"), (20.0, "alice"), (30.0, "bob"), (40.0, "bob")]:
            store.record("latency", val, tags={"agent": agent, "scene": "bedroom"})

    def test_group_by_single(self, tmp_path):
        """Grouping by one tag key returns correct groups."""
        store = _fresh_store(tmp_path)
        self._seed(store)
        results = store.query("latency", group_by=["agent"])
        assert len(results) == 2
        keys = {tuple(r.group_key.items()) for r in results}
        assert (("agent", "alice"),) in keys
        assert (("agent", "bob"),) in keys

    def test_group_by_multi(self, tmp_path):
        """Grouping by multiple tag keys produces combined groups."""
        store = _fresh_store(tmp_path)
        store.record("m", 1.0, tags={"a": "x", "b": "1"})
        store.record("m", 2.0, tags={"a": "x", "b": "2"})
        store.record("m", 3.0, tags={"a": "y", "b": "1"})
        results = store.query("m", group_by=["a", "b"])
        assert len(results) == 3

    def test_group_by_with_filters(self, tmp_path):
        """Filters are applied before grouping."""
        store = _fresh_store(tmp_path)
        self._seed(store)
        results = store.query("latency", filters={"agent": "alice"}, group_by=["agent"])
        assert len(results) == 1
        assert results[0].group_key["agent"] == "alice"
        assert results[0].count == 2

    def test_mean_min_max_correct(self, tmp_path):
        """Aggregation computes correct mean, min, and max."""
        store = _fresh_store(tmp_path)
        self._seed(store)
        results = store.query("latency", group_by=["agent"])
        alice = [r for r in results if r.group_key["agent"] == "alice"][0]
        assert alice.mean == pytest.approx(15.0)
        assert alice.min_val == pytest.approx(10.0)
        assert alice.max_val == pytest.approx(20.0)

    def test_stddev_correct(self, tmp_path):
        """Aggregation stddev matches expected population stddev."""
        store = _fresh_store(tmp_path)
        self._seed(store)
        results = store.query("latency", group_by=["agent"])
        alice = [r for r in results if r.group_key["agent"] == "alice"][0]
        expected_sd = math.sqrt(((10 - 15) ** 2 + (20 - 15) ** 2) / 2)
        assert alice.stddev == pytest.approx(expected_sd)

    def test_percentiles_correct(self, tmp_path):
        """Aggregation p50 is the median."""
        store = _fresh_store(tmp_path)
        store.record("m", 10.0, tags={"g": "a"})
        store.record("m", 20.0, tags={"g": "a"})
        store.record("m", 30.0, tags={"g": "a"})
        results = store.query("m", group_by=["g"])
        assert len(results) == 1
        assert results[0].p50 == pytest.approx(20.0)

    def test_empty_group(self, tmp_path):
        """Grouping with no matching data returns empty list."""
        store = _fresh_store(tmp_path)
        results = store.query("nonexistent", group_by=["tag"])
        assert results == []

    def test_window_filter_aggregated(self, tmp_path):
        """Window filter works with aggregated queries."""
        store = _fresh_store(tmp_path)
        old_ts = time.time() - 7200
        store.record("m", 100.0, tags={"g": "a"}, timestamp=old_ts)
        store.record("m", 5.0, tags={"g": "a"})
        results = store.query("m", group_by=["g"], window_seconds=600)
        assert len(results) == 1
        assert results[0].mean == pytest.approx(5.0)


# ──── tag operations ─────────────────────────────────────────────────────────


class TestTagOperations:
    """Tests for tag introspection methods."""

    def test_get_tag_cardinality_all(self, tmp_path):
        """get_tag_cardinality without name returns all tag keys."""
        store = _fresh_store(tmp_path)
        store.record("m1", 1.0, tags={"env": "prod", "region": "us"})
        store.record("m2", 2.0, tags={"env": "dev"})
        cards = store.get_tag_cardinality()
        keys = {c.key for c in cards}
        assert "env" in keys
        assert "region" in keys

    def test_cardinality_filtered_by_metric(self, tmp_path):
        """get_tag_cardinality with name restricts to that metric's tags."""
        store = _fresh_store(tmp_path)
        store.record("m1", 1.0, tags={"env": "prod"})
        store.record("m2", 2.0, tags={"region": "us"})
        cards = store.get_tag_cardinality(name="m1")
        keys = {c.key for c in cards}
        assert "env" in keys
        assert "region" not in keys

    def test_get_tag_values(self, tmp_path):
        """get_tag_values returns sorted unique values for a key."""
        store = _fresh_store(tmp_path)
        store.record("m", 1.0, tags={"color": "red"})
        store.record("m", 2.0, tags={"color": "blue"})
        store.record("m", 3.0, tags={"color": "red"})
        vals = store.get_tag_values("color")
        assert vals == ["blue", "red"]

    def test_tag_values_filtered_by_name(self, tmp_path):
        """get_tag_values with name restricts to that metric."""
        store = _fresh_store(tmp_path)
        store.record("m1", 1.0, tags={"env": "prod"})
        store.record("m2", 2.0, tags={"env": "dev"})
        vals = store.get_tag_values("env", name="m1")
        assert vals == ["prod"]

    def test_get_metric_names(self, tmp_path):
        """get_metric_names returns sorted unique metric names."""
        store = _fresh_store(tmp_path)
        store.record("zeta", 1.0)
        store.record("alpha", 2.0)
        store.record("zeta", 3.0)
        names = store.get_metric_names()
        assert names == ["alpha", "zeta"]

    def test_sample_values_populated(self, tmp_path):
        """Cardinality results include sample_values."""
        store = _fresh_store(tmp_path)
        for i in range(5):
            store.record("m", float(i), tags={"idx": str(i)})
        cards = store.get_tag_cardinality()
        idx_card = [c for c in cards if c.key == "idx"][0]
        assert idx_card.unique_values == 5
        assert len(idx_card.sample_values) == 5


# ──── get_summary ────────────────────────────────────────────────────────────


class TestGetSummary:
    """Tests for DimensionStore.get_summary()."""

    def test_basic_summary(self, tmp_path):
        """Summary contains expected keys."""
        store = _fresh_store(tmp_path)
        for v in [10.0, 20.0, 30.0]:
            store.record("m", v)
        summary = store.get_summary("m")
        assert "count" in summary
        assert "mean" in summary
        assert "p50" in summary

    def test_summary_with_window(self, tmp_path):
        """Summary window restricts to recent data."""
        store = _fresh_store(tmp_path)
        old_ts = time.time() - 7200
        store.record("m", 100.0, timestamp=old_ts)
        store.record("m", 5.0)
        summary = store.get_summary("m", window_seconds=600)
        assert summary["count"] == 1
        assert summary["mean"] == pytest.approx(5.0)

    def test_summary_empty(self, tmp_path):
        """Summary of non-existent metric returns empty dict."""
        store = _fresh_store(tmp_path)
        summary = store.get_summary("nothing")
        assert summary == {}

    def test_summary_count_correct(self, tmp_path):
        """Summary count matches the number of recorded values."""
        store = _fresh_store(tmp_path)
        for i in range(7):
            store.record("m", float(i))
        summary = store.get_summary("m")
        assert summary["count"] == 7

    def test_summary_percentiles_correct(self, tmp_path):
        """Summary percentiles are computed from the full dataset."""
        store = _fresh_store(tmp_path)
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            store.record("m", v)
        summary = store.get_summary("m")
        assert summary["p50"] == pytest.approx(3.0)
        assert summary["min"] == pytest.approx(1.0)
        assert summary["max"] == pytest.approx(5.0)


# ──── prune ──────────────────────────────────────────────────────────────────


class TestPrune:
    """Tests for DimensionStore.prune()."""

    def test_prune_old_metrics(self, tmp_path):
        """Prune removes metrics older than the threshold."""
        store = _fresh_store(tmp_path)
        old_ts = time.time() - 7200
        store.record("m", 1.0, timestamp=old_ts)
        store.record("m", 2.0)
        deleted = store.prune(3600)
        assert deleted >= 1
        rows = store.query("m")
        assert len(rows) == 1
        assert rows[0].value == 2.0

    def test_prune_nothing(self, tmp_path):
        """Prune with large window deletes nothing."""
        store = _fresh_store(tmp_path)
        store.record("m", 1.0)
        deleted = store.prune(999999)
        assert deleted == 0

    def test_prune_count_correct(self, tmp_path):
        """Prune returns correct count of deleted rows."""
        store = _fresh_store(tmp_path)
        old_ts = time.time() - 7200
        for i in range(5):
            store.record("m", float(i), timestamp=old_ts)
        store.record("m", 99.0)
        deleted = store.prune(3600)
        assert deleted == 5

    def test_prune_cleans_tags(self, tmp_path):
        """Prune removes orphaned tag rows."""
        store = _fresh_store(tmp_path)
        old_ts = time.time() - 7200
        store.record("m", 1.0, tags={"env": "old"}, timestamp=old_ts)
        store.record("m", 2.0, tags={"env": "new"})
        store.prune(3600)
        vals = store.get_tag_values("env")
        assert "old" not in vals
        assert "new" in vals


# ──── export ─────────────────────────────────────────────────────────────────


class TestExport:
    """Tests for DimensionStore.export_for_analysis()."""

    def test_basic_export(self, tmp_path):
        """Export returns flat dicts with expected keys."""
        store = _fresh_store(tmp_path)
        store.record("m", 42.0, tags={"env": "prod"})
        rows = store.export_for_analysis("m")
        assert len(rows) == 1
        assert rows[0]["name"] == "m"
        assert rows[0]["value"] == 42.0
        assert rows[0]["tag_env"] == "prod"

    def test_export_with_filters(self, tmp_path):
        """Export respects tag filters."""
        store = _fresh_store(tmp_path)
        store.record("m", 1.0, tags={"env": "prod"})
        store.record("m", 2.0, tags={"env": "dev"})
        rows = store.export_for_analysis("m", filters={"env": "dev"})
        assert len(rows) == 1
        assert rows[0]["value"] == 2.0

    def test_export_tag_prefix_keys(self, tmp_path):
        """Exported tag keys are prefixed with 'tag_'."""
        store = _fresh_store(tmp_path)
        store.record("m", 1.0, tags={"region": "us", "tier": "free"})
        rows = store.export_for_analysis("m")
        assert "tag_region" in rows[0]
        assert "tag_tier" in rows[0]
        assert "region" not in rows[0]  # raw key should not appear


# ──── edge cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge-case and robustness tests."""

    def test_special_chars_in_tags(self, tmp_path):
        """Tags with special characters are stored and queried correctly."""
        store = _fresh_store(tmp_path)
        tags = {"path": "/scenes/bedroom/main.py", "label": "it's \"quoted\""}
        store.record("m", 1.0, tags=tags)
        rows = store.query("m", filters={"path": "/scenes/bedroom/main.py"})
        assert len(rows) == 1
        assert rows[0].tags["label"] == "it's \"quoted\""

    def test_empty_tags_dict(self, tmp_path):
        """Empty tags dict is handled identically to no tags."""
        store = _fresh_store(tmp_path)
        mid = store.record("m", 1.0, tags={})
        rows = store.query("m")
        assert len(rows) == 1
        assert rows[0].tags == {}

    def test_very_large_values(self, tmp_path):
        """Very large float values are stored without loss."""
        store = _fresh_store(tmp_path)
        big = 1e18
        store.record("m", big)
        rows = store.query("m")
        assert rows[0].value == pytest.approx(big)

    def test_concurrent_access(self, tmp_path):
        """Multiple threads can record concurrently without error."""
        store = _fresh_store(tmp_path)
        errors = []

        def writer(thread_id: int) -> None:
            try:
                for i in range(20):
                    store.record("m", float(i), tags={"tid": str(thread_id)})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        rows = store.query("m", limit=10000)
        assert len(rows) == 80  # 4 threads × 20 records

    def test_singleton_pattern(self, tmp_path):
        """get_dimension_store returns the same instance on repeated calls."""
        # NOTE: This test validates the function signature exists and returns
        # a DimensionStore. It does not reset the global singleton to avoid
        # side-effects on other tests.
        store = get_dimension_store()
        assert isinstance(store, DimensionStore)
        store2 = get_dimension_store()
        assert store is store2
