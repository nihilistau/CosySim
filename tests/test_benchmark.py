"""Tests for engine.lmstudio.benchmark — InferenceBenchmark."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from engine.lmstudio.benchmark import (
    BENCHMARK_PROMPTS,
    BenchmarkResult,
    BenchmarkSummary,
    InferenceBenchmark,
)


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_config():
    """MagicMock config with .get() support."""
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda k, d=None: {
        "lmstudio.host": "localhost",
        "lmstudio.port": 1234,
        "nexus.url": "http://localhost:8700/api",
    }.get(k, d))
    return cfg


@pytest.fixture
def benchmark(mock_config):
    """InferenceBenchmark instance with mocked config."""
    return InferenceBenchmark(mock_config)


# ── BENCHMARK_PROMPTS ───────────────────────────────────────────────────

def test_prompt_bank_has_all_categories():
    """All expected prompt categories exist."""
    expected = {"short", "medium", "long", "code", "roleplay", "routing"}
    assert expected.issubset(set(BENCHMARK_PROMPTS.keys()))


def test_prompt_bank_entries_are_non_empty():
    """Each category has a non-empty prompt string."""
    for category, prompt in BENCHMARK_PROMPTS.items():
        assert isinstance(prompt, str), f"{category} is not a string"
        assert len(prompt) > 0, f"{category} is empty"


# ── BenchmarkResult ────────────────────────────────────────────────────

def test_benchmark_result_fields():
    """BenchmarkResult stores all expected fields."""
    result = BenchmarkResult(
        model="test-model",
        prompt_type="short",
        temperature=0.7,
        max_tokens=256,
        context_length=8192,
        n_parallel=1,
        total_latency_ms=500.0,
        time_to_first_token_ms=120.0,
        tokens_per_second=25.0,
        completion_tokens=50,
        success=True,
    )
    assert result.model == "test-model"
    assert result.total_latency_ms == 500.0
    assert result.tokens_per_second == 25.0
    assert result.success is True


def test_benchmark_result_failure():
    """BenchmarkResult records failures."""
    result = BenchmarkResult(
        model="fail-model",
        prompt_type="short",
        temperature=0.7,
        max_tokens=256,
        context_length=8192,
        n_parallel=1,
        success=False,
        error="timeout",
    )
    assert result.success is False
    assert result.error == "timeout"


# ── BenchmarkSummary ───────────────────────────────────────────────────

def test_benchmark_summary_stats():
    """BenchmarkSummary computes statistics from results."""
    results = [
        BenchmarkResult("m", "s", 0.7, 256, 8192, 1,
                         total_latency_ms=100, tokens_per_second=20.0),
        BenchmarkResult("m", "s", 0.7, 256, 8192, 1,
                         total_latency_ms=200, tokens_per_second=30.0),
        BenchmarkResult("m", "s", 0.7, 256, 8192, 1,
                         total_latency_ms=300, tokens_per_second=10.0),
    ]
    summary = BenchmarkSummary(model="m", config_label="test", runs=3, results=results)

    assert summary.success_rate == 1.0
    assert summary.tps_stats["mean"] == pytest.approx(20.0, abs=0.1)


def test_benchmark_summary_with_failures():
    """BenchmarkSummary handles mixed success/failure."""
    results = [
        BenchmarkResult("m", "s", 0.7, 256, 8192, 1,
                         tokens_per_second=20.0, success=True),
        BenchmarkResult("m", "s", 0.7, 256, 8192, 1,
                         success=False, error="err"),
    ]
    summary = BenchmarkSummary(model="m", config_label="test", runs=2, results=results)
    assert len(summary.successful) < summary.runs


def test_benchmark_summary_to_markdown():
    """BenchmarkSummary renders markdown."""
    results = [
        BenchmarkResult("m", "s", 0.7, 256, 8192, 1, tokens_per_second=20.0),
    ]
    summary = BenchmarkSummary(model="m", config_label="test", runs=1, results=results)
    md = summary.to_markdown()
    assert "m" in md


# ── InferenceBenchmark ──────────────────────────────────────────────────

@patch("engine.lmstudio.benchmark.requests.post")
def test_run_quick_success(mock_post, benchmark):
    """run_quick returns summary on successful LMStudio responses."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.iter_lines.return_value = [
        b"data: " + json.dumps({"choices": [{"delta": {"content": "hello"}}]}).encode(),
        b"data: " + json.dumps({"choices": [{"delta": {"content": " world"}}]}).encode(),
        b"data: [DONE]",
    ]
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_post.return_value = mock_response

    summary = benchmark.run_quick(model="test-model", runs=2, prompt_type="short")

    assert summary.model == "test-model"
    assert summary.runs == 2
    assert mock_post.call_count == 2


@patch("engine.lmstudio.benchmark.requests.post")
def test_run_quick_handles_errors(mock_post, benchmark):
    """run_quick handles request failures gracefully."""
    mock_post.side_effect = Exception("connection refused")

    summary = benchmark.run_quick(model="fail-model", runs=3, prompt_type="short")

    assert summary.runs == 3
    assert len(summary.successful) == 0
    assert summary.success_rate == 0.0


@patch("engine.lmstudio.benchmark.requests.post")
def test_run_matrix_iterates_prompt_types(mock_post, benchmark):
    """run_matrix tests multiple prompt types."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.iter_lines.return_value = [
        b"data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]}).encode(),
        b"data: [DONE]",
    ]
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_post.return_value = mock_response

    results = benchmark.run_matrix(
        model="test-model",
        prompt_types=["short", "code"],
        temperatures=[0.5],
        runs_per_config=1,
    )

    assert len(results) >= 2


@patch("engine.lmstudio.benchmark.requests.post")
def test_store_results_sends_to_nexus(mock_post, benchmark):
    """store_results sends markdown to Nexus API."""
    results = [
        BenchmarkResult("m", "s", 0.7, 256, 8192, 1, tokens_per_second=20.0),
    ]
    summary = BenchmarkSummary(model="m", config_label="test", runs=1, results=results)

    nexus_response = MagicMock()
    nexus_response.ok = True
    nexus_response.json.return_value = {"id": "test-123"}
    mock_post.return_value = nexus_response

    entry_id = benchmark.store_results(summary)

    assert entry_id == "test-123"
