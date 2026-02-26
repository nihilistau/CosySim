"""Tests for engine.lmstudio.auto_tuner — AutoTuner."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.lmstudio.auto_tuner import (
    AutoTuner,
    TASK_TYPE_CONFIGS,
    TuningConfig,
    TuningResult,
)
from engine.lmstudio.benchmark import BenchmarkResult, BenchmarkSummary


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_config():
    """MagicMock config with .get() support."""
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda k, d=None: {
        "lmstudio.host": "localhost",
        "lmstudio.port": 1234,
        "lmstudio.models.primary": "qwen3-8b",
        "lmstudio.models.cpu_utility": "qwen3-4b-thinking",
        "nexus.url": "http://localhost:8700/api",
    }.get(k, d))
    return cfg


@pytest.fixture
def tuner(mock_config):
    """AutoTuner with mocked config."""
    return AutoTuner(mock_config)


def _make_summary(tps: float = 20.0, latency: float = 200.0) -> BenchmarkSummary:
    """Helper to create a BenchmarkSummary with given stats."""
    return BenchmarkSummary(
        model="test",
        config_label="test",
        runs=5,
        results=[
            BenchmarkResult("test", "short", 0.7, 256, 8192, 1,
                             total_latency_ms=latency, tokens_per_second=tps)
            for _ in range(5)
        ],
    )


# ── TuningConfig ────────────────────────────────────────────────────────

def test_tuning_config_to_dict():
    """TuningConfig serializes to dict."""
    cfg = TuningConfig(temperature=0.7, max_tokens=512, label="test")
    d = cfg.to_dict()
    assert d["temperature"] == 0.7
    assert d["max_tokens"] == 512
    assert d["label"] == "test"


def test_tuning_config_defaults():
    """TuningConfig has sensible defaults."""
    cfg = TuningConfig()
    assert cfg.temperature == 0.7
    assert cfg.max_tokens == 256
    assert cfg.n_parallel == 1
    assert cfg.gpu_offload == 1.0


# ── TASK_TYPE_CONFIGS ───────────────────────────────────────────────────

def test_task_type_configs_has_all_types():
    """All expected task types have configs."""
    expected = {"roleplay", "code", "routing", "chat", "narration"}
    assert expected.issubset(set(TASK_TYPE_CONFIGS.keys()))


def test_task_type_configs_have_labels():
    """Every config in every task type has a label."""
    for task_type, configs in TASK_TYPE_CONFIGS.items():
        for cfg in configs:
            assert cfg.label, f"Missing label in {task_type}"


# ── TuningResult ────────────────────────────────────────────────────────

def test_tuning_result_to_markdown():
    """TuningResult renders markdown with results table."""
    result = TuningResult(
        model="qwen3-8b",
        task_type="chat",
        configs_tested=2,
        best_tps=25.0,
        best_latency=150.0,
        best_config=TuningConfig(label="best"),
        all_results=[
            {"label": "a", "tps": 25.0, "latency": 150.0, "success_rate": 1.0},
            {"label": "b", "tps": 15.0, "latency": 300.0, "success_rate": 0.8},
        ],
    )
    md = result.to_markdown()
    assert "qwen3-8b" in md
    assert "Best Config" in md
    assert "All Results" in md


def test_tuning_result_empty():
    """TuningResult renders without errors even when empty."""
    result = TuningResult(model="test", task_type="chat")
    md = result.to_markdown()
    assert "test" in md
    assert "Configs tested: 0" in md


# ── AutoTuner.find_optimal ──────────────────────────────────────────────

def test_find_optimal_selects_best_config(tuner):
    """find_optimal returns config with highest TPS."""
    summaries = [
        _make_summary(tps=10.0),
        _make_summary(tps=30.0),
        _make_summary(tps=20.0),
    ]
    call_count = 0

    def mock_run_quick(*args, **kwargs):
        nonlocal call_count
        result = summaries[min(call_count, len(summaries) - 1)]
        call_count += 1
        return result

    tuner._benchmark.run_quick = mock_run_quick

    result = tuner.find_optimal("test-model", task_type="routing")

    assert result.model == "test-model"
    assert result.best_tps == 30.0
    assert result.configs_tested == len(TASK_TYPE_CONFIGS["routing"])


def test_find_optimal_with_custom_configs(tuner):
    """find_optimal uses custom configs when provided."""
    tuner._benchmark.run_quick = MagicMock(return_value=_make_summary(tps=15.0))

    custom = [TuningConfig(temperature=0.5, label="custom")]
    result = tuner.find_optimal("test", custom_configs=custom)

    assert result.configs_tested == 1
    assert tuner._benchmark.run_quick.call_count == 1


# ── AutoTuner.test_hypothesis ───────────────────────────────────────────

def test_hypothesis_unknown(tuner):
    """Unknown hypothesis returns error dict."""
    result = tuner.test_hypothesis("nonexistent")
    assert "error" in result


def test_hypothesis_speculative(tuner):
    """Speculative hypothesis returns not_implemented status."""
    result = tuner.test_hypothesis("speculative")
    assert result["status"] == "not_implemented"


def test_hypothesis_cpu_overflow(tuner):
    """CPU overflow hypothesis compares GPU vs CPU models."""
    tuner._benchmark.run_quick = MagicMock(return_value=_make_summary(tps=20.0))

    result = tuner.test_hypothesis("cpu_overflow")

    assert result["hypothesis"] == "cpu_overflow"
    assert "gpu_tps" in result
    assert "cpu_tps" in result
    assert "verdict" in result
    assert tuner._benchmark.run_quick.call_count == 2


def test_hypothesis_context_reduction(tuner):
    """Context reduction hypothesis compares short vs long prompts."""
    call_count = 0

    def varying_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_summary(tps=30.0 if call_count == 1 else 15.0)

    tuner._benchmark.run_quick = varying_run

    result = tuner.test_hypothesis("context_reduction")

    assert result["hypothesis"] == "context_reduction"
    assert result["speedup_factor"] == 2.0


# ── AutoTuner.store_results ────────────────────────────────────────────

@patch("engine.lmstudio.auto_tuner.requests.post")
def test_store_results_sends_to_nexus(mock_post, tuner):
    """store_results sends tuning results to Nexus."""
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {"id": "tune-123"}
    mock_post.return_value = mock_response

    result = TuningResult(model="test", task_type="chat", best_tps=25.0)
    entry_id = tuner.store_results(result)

    assert entry_id == "tune-123"
    mock_post.assert_called_once()


@patch("engine.lmstudio.auto_tuner.requests.post")
def test_store_results_handles_nexus_failure(mock_post, tuner):
    """store_results returns None when Nexus is unavailable."""
    mock_post.side_effect = Exception("connection refused")

    result = TuningResult(model="test", task_type="chat")
    entry_id = tuner.store_results(result)

    assert entry_id is None
