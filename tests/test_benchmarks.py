"""
Tests for engine/logging/benchmark.py — Enhanced benchmarking with LLM KPIs.
"""
import time
import pytest

from engine.logging.benchmark import (
    timed,
    get_benchmarks,
    get_operation_timings,
    get_all_operations,
    reset_benchmarks,
    record_llm_kpi,
    get_llm_kpis,
    get_kpi_timeseries,
)


@pytest.fixture(autouse=True)
def clean_benchmarks():
    """Reset all benchmarks before each test."""
    reset_benchmarks()
    yield
    reset_benchmarks()


# ── @timed decorator ─────────────────────────────────────────────────

class TestTimed:
    def test_records_timing(self):
        @timed("test_op")
        def work():
            time.sleep(0.01)
        work()
        stats = get_benchmarks()
        assert "test_op" in stats
        assert stats["test_op"]["count"] == 1
        assert stats["test_op"]["avg_ms"] > 5  # at least 5ms

    def test_no_parens(self):
        @timed
        def my_func():
            pass
        my_func()
        stats = get_benchmarks()
        assert any("my_func" in k for k in stats)

    def test_multiple_calls(self):
        @timed("multi")
        def work():
            pass
        for _ in range(5):
            work()
        stats = get_benchmarks()
        assert stats["multi"]["count"] == 5

    def test_preserves_return_value(self):
        @timed("ret_test")
        def add(a, b):
            return a + b
        assert add(2, 3) == 5

    def test_preserves_exceptions(self):
        @timed("err_test")
        def fail():
            raise ValueError("boom")
        with pytest.raises(ValueError, match="boom"):
            fail()
        # Should still record the timing even on error
        stats = get_benchmarks()
        assert stats["err_test"]["count"] == 1


# ── get_benchmarks ───────────────────────────────────────────────────

class TestGetBenchmarks:
    def test_empty(self):
        assert get_benchmarks() == {}

    def test_stats_fields(self):
        @timed("stat_test")
        def work():
            time.sleep(0.005)
        for _ in range(3):
            work()
        stats = get_benchmarks()["stat_test"]
        assert "count" in stats
        assert "total_ms" in stats
        assert "min_ms" in stats
        assert "max_ms" in stats
        assert "avg_ms" in stats
        assert "p95_ms" in stats
        assert stats["min_ms"] <= stats["avg_ms"] <= stats["max_ms"]


# ── get_operation_timings ────────────────────────────────────────────

class TestGetOperationTimings:
    def test_returns_raw(self):
        @timed("raw_test")
        def work():
            pass
        work()
        work()
        timings = get_operation_timings("raw_test")
        assert len(timings) == 2
        assert all(isinstance(t, float) for t in timings)

    def test_missing_op_returns_empty(self):
        assert get_operation_timings("nonexistent") == []


# ── get_all_operations ───────────────────────────────────────────────

class TestGetAllOperations:
    def test_lists_all(self):
        @timed("op_a")
        def a():
            pass
        @timed("op_b")
        def b():
            pass
        a()
        b()
        ops = get_all_operations()
        assert "op_a" in ops
        assert "op_b" in ops


# ── reset_benchmarks ────────────────────────────────────────────────

class TestResetBenchmarks:
    def test_reset_all(self):
        @timed("reset_test")
        def work():
            pass
        work()
        reset_benchmarks()
        assert get_benchmarks() == {}

    def test_reset_specific(self):
        @timed("keep")
        def keep():
            pass
        @timed("drop")
        def drop():
            pass
        keep()
        drop()
        reset_benchmarks("drop")
        stats = get_benchmarks()
        assert "keep" in stats
        assert "drop" not in stats


# ═══════════════════════════════════════════════════════════════════════
#  LLM KPI tracking
# ═══════════════════════════════════════════════════════════════════════

class TestRecordLLMKpi:
    def test_record_and_get(self):
        record_llm_kpi(
            "llm_chat",
            latency_ms=500,
            tokens_in=50,
            tokens_out=100,
            model="test-model",
        )
        kpis = get_llm_kpis("llm_chat")
        assert kpis["count"] == 1
        assert kpis["total_tokens_in"] == 50
        assert kpis["total_tokens_out"] == 100
        assert kpis["avg_latency_ms"] == 500.0
        assert "test-model" in kpis["models"]

    def test_tokens_per_sec_calculation(self):
        record_llm_kpi("tps_test", latency_ms=1000, tokens_out=50)
        kpis = get_llm_kpis("tps_test")
        assert kpis["avg_tokens_per_sec"] == 50.0

    def test_multiple_records(self):
        record_llm_kpi("multi", latency_ms=200, tokens_in=10, tokens_out=20, model="a")
        record_llm_kpi("multi", latency_ms=400, tokens_in=30, tokens_out=40, model="a")
        kpis = get_llm_kpis("multi")
        assert kpis["count"] == 2
        assert kpis["total_tokens_in"] == 40
        assert kpis["total_tokens_out"] == 60
        assert kpis["avg_latency_ms"] == 300.0

    def test_aggregated_kpis(self):
        record_llm_kpi("op1", latency_ms=100, tokens_out=10, model="a")
        record_llm_kpi("op2", latency_ms=200, tokens_out=20, model="b")
        kpis = get_llm_kpis()  # All operations
        assert kpis["count"] == 2
        assert len(kpis["models"]) == 2

    def test_empty_kpis(self):
        kpis = get_llm_kpis("nothing")
        assert kpis["count"] == 0

    def test_first_token_ms(self):
        record_llm_kpi("ftft", latency_ms=500, first_token_ms=50)
        kpis = get_llm_kpis("ftft")
        assert kpis["avg_first_token_ms"] == 50.0


class TestKpiTimeseries:
    def test_returns_samples(self):
        for i in range(5):
            record_llm_kpi("ts_test", latency_ms=100 * (i + 1), tokens_out=10)
        ts = get_kpi_timeseries("ts_test")
        assert len(ts) == 5
        assert all("latency_ms" in s for s in ts)

    def test_last_n_limit(self):
        for i in range(10):
            record_llm_kpi("limit_test", latency_ms=100)
        ts = get_kpi_timeseries("limit_test", last_n=3)
        assert len(ts) == 3

    def test_ordered_by_timestamp(self):
        for i in range(3):
            record_llm_kpi("order_test", latency_ms=100)
        ts = get_kpi_timeseries("order_test")
        timestamps = [s["timestamp"] for s in ts]
        assert timestamps == sorted(timestamps)

    def test_empty(self):
        ts = get_kpi_timeseries("empty")
        assert ts == []


class TestResetKpis:
    def test_reset_clears_kpis_too(self):
        record_llm_kpi("kpi_reset", latency_ms=100)
        reset_benchmarks("kpi_reset")
        kpis = get_llm_kpis("kpi_reset")
        assert kpis["count"] == 0

    def test_reset_all_clears_kpis(self):
        record_llm_kpi("kpi_all", latency_ms=100)
        reset_benchmarks()
        kpis = get_llm_kpis()
        assert kpis["count"] == 0
