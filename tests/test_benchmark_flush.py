"""Tests for benchmark → MetaMetrics flush integration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engine.logging.benchmark import (
    flush_to_meta_metrics,
    get_benchmarks,
    get_llm_kpis,
    record_llm_kpi,
    reset_benchmarks,
    timed,
)


def _seed_benchmarks() -> None:
    """Populate the in-memory stores with sample data."""
    reset_benchmarks()

    @timed("test_op_a")
    def _op_a():
        pass

    @timed("test_op_b")
    def _op_b():
        pass

    for _ in range(5):
        _op_a()
    for _ in range(3):
        _op_b()

    record_llm_kpi(
        "llm_gen",
        latency_ms=120.0,
        tokens_in=50,
        tokens_out=100,
        model="qwen-7b",
        first_token_ms=25.0,
    )
    record_llm_kpi(
        "llm_gen",
        latency_ms=80.0,
        tokens_in=30,
        tokens_out=60,
        model="qwen-7b",
        first_token_ms=20.0,
    )


# ── Flush Unit Tests ──────────────────────────────────────────────────────────


def test_flush_returns_all_metric_keys():
    """flush_to_meta_metrics returns the 10 expected benchmark.* metric keys."""
    _seed_benchmarks()
    try:
        with patch("engine.logging.benchmark.get_meta_metrics") as mock_mm:
            mock_mm.return_value = MagicMock()
            result = flush_to_meta_metrics(clear=False)
    except Exception:
        # get_meta_metrics import is lazy inside function — patch at module if needed
        with patch(
            "engine.nexus.meta_metrics.get_meta_metrics",
            return_value=MagicMock(),
        ):
            result = flush_to_meta_metrics(clear=False)

    expected_keys = {
        "benchmark.ops.count",
        "benchmark.ops.types",
        "benchmark.ops.total_ms",
        "benchmark.ops.avg_ms",
        "benchmark.ops.p95_ms",
        "benchmark.llm.count",
        "benchmark.llm.total_tokens",
        "benchmark.llm.avg_latency_ms",
        "benchmark.llm.tokens_per_sec",
        "benchmark.llm.first_token_ms",
    }
    assert set(result.keys()) == expected_keys
    reset_benchmarks()


def test_flush_ops_count_correct():
    """flush reports correct aggregate ops count."""
    _seed_benchmarks()
    with patch(
        "engine.nexus.meta_metrics.get_meta_metrics",
        return_value=MagicMock(),
    ):
        result = flush_to_meta_metrics(clear=False)

    assert result["benchmark.ops.count"] == 8.0  # 5 + 3
    assert result["benchmark.ops.types"] == 2.0   # test_op_a, test_op_b
    reset_benchmarks()


def test_flush_llm_count_correct():
    """flush reports correct LLM call count."""
    _seed_benchmarks()
    with patch(
        "engine.nexus.meta_metrics.get_meta_metrics",
        return_value=MagicMock(),
    ):
        result = flush_to_meta_metrics(clear=False)

    assert result["benchmark.llm.count"] == 2.0
    # Total tokens: (50+100) + (30+60) = 240
    assert result["benchmark.llm.total_tokens"] == 240.0
    reset_benchmarks()


def test_flush_with_clear_resets_stores():
    """clear=True empties both stores after flush."""
    _seed_benchmarks()
    with patch(
        "engine.nexus.meta_metrics.get_meta_metrics",
        return_value=MagicMock(),
    ):
        flush_to_meta_metrics(clear=True)

    assert get_benchmarks() == {}
    kpis = get_llm_kpis()
    assert kpis.get("count", 0) == 0


def test_flush_without_clear_preserves_stores():
    """clear=False keeps data in stores."""
    _seed_benchmarks()
    with patch(
        "engine.nexus.meta_metrics.get_meta_metrics",
        return_value=MagicMock(),
    ):
        flush_to_meta_metrics(clear=False)

    assert get_benchmarks() != {}
    kpis = get_llm_kpis()
    assert kpis.get("count", 0) == 2
    reset_benchmarks()


def test_flush_empty_stores():
    """flush on empty stores returns all-zero metrics."""
    reset_benchmarks()
    with patch(
        "engine.nexus.meta_metrics.get_meta_metrics",
        return_value=MagicMock(),
    ):
        result = flush_to_meta_metrics(clear=False)

    assert result["benchmark.ops.count"] == 0.0
    assert result["benchmark.llm.count"] == 0.0
    assert result["benchmark.ops.avg_ms"] == 0.0


def test_flush_calls_record_batch():
    """flush calls MetaMetrics.record_batch with correct number of metrics."""
    _seed_benchmarks()
    mock_mm = MagicMock()
    with patch(
        "engine.nexus.meta_metrics.get_meta_metrics",
        return_value=mock_mm,
    ):
        flush_to_meta_metrics(clear=True)

    mock_mm.record_batch.assert_called_once()
    batch_arg = mock_mm.record_batch.call_args[0][0]
    assert len(batch_arg) == 10


def test_flush_graceful_on_meta_metrics_failure():
    """flush does not raise when MetaMetrics import or call fails."""
    _seed_benchmarks()
    with patch(
        "engine.nexus.meta_metrics.get_meta_metrics",
        side_effect=RuntimeError("DB locked"),
    ):
        result = flush_to_meta_metrics(clear=False)

    # Should still return computed metrics dict even if persistence failed
    assert "benchmark.ops.count" in result
    reset_benchmarks()


# ── MetaMetrics BENCHMARK_METRICS Integration ─────────────────────────────────


def test_benchmark_metrics_registered():
    """BENCHMARK_METRICS list exists in meta_metrics module."""
    from engine.nexus.meta_metrics import BENCHMARK_METRICS, ALL_METRIC_NAMES

    assert len(BENCHMARK_METRICS) == 10
    for metric in BENCHMARK_METRICS:
        assert metric in ALL_METRIC_NAMES


def test_collect_benchmark_metrics_method_exists():
    """MetaMetrics has collect_benchmark_metrics method."""
    from engine.nexus.meta_metrics import MetaMetrics

    assert hasattr(MetaMetrics, "collect_benchmark_metrics")


def test_dashboard_includes_benchmark_section(tmp_path):
    """Dashboard includes Benchmark section in its output."""
    from engine.nexus.meta_metrics import MetaMetrics

    mm = MetaMetrics(db_path=str(tmp_path / "test_mm.db"))
    dashboard = mm.dashboard()

    assert "Benchmark" in dashboard
