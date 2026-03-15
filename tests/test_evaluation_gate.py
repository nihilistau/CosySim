"""Tests for training.evaluation_gate — gate policies, benchmarks, persistence."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from training.evaluation_gate import (
    DEFAULT_BENCHMARK_PROMPTS,
    BenchmarkResult,
    BenchmarkSpec,
    EvaluationGate,
    GatePolicy,
    GateResult,
    get_evaluation_gate,
)


# ──── Helpers ────────────────────────────────────────────────────────


def make_benchmark(
    model_id: str = "test-model",
    model_type: str = "general",
    accuracy: float = 0.8,
    latency: float = 1.0,
    consistency: float = 0.9,
    error_rate: float = 0.0,
) -> BenchmarkResult:
    """Build a BenchmarkResult with controllable scores."""
    return BenchmarkResult(
        model_id=model_id,
        model_type=model_type,
        timestamp=time.time(),
        scores={
            "accuracy": accuracy,
            "latency": latency,
            "consistency": consistency,
        },
        raw_results=[],
        latency_stats={
            "mean": latency,
            "p50": latency,
            "p95": latency * 1.2,
            "p99": latency * 1.5,
            "min": latency * 0.8,
            "max": latency * 1.5,
            "stdev": 0.05,
        },
        consistency_score=consistency,
        total_tokens=100,
        total_time_s=5.0,
        error_rate=error_rate,
    )


def make_gate(tmp_path: Path) -> EvaluationGate:
    """Create an isolated EvaluationGate backed by a temp database."""
    return EvaluationGate(db_path=tmp_path / "test_gate.db")


# ──── BenchmarkResult ────────────────────────────────────────────────


class TestBenchmarkResult:
    """Tests for BenchmarkResult dataclass and its overall_score property."""

    def test_overall_score_calculation(self) -> None:
        """Weighted overall score calculated correctly."""
        bench = make_benchmark(accuracy=0.8, latency=2.0, consistency=0.9, error_rate=0.1)
        # accuracy   → 0.8 * 0.40 = 0.32
        # latency    → (1 - 2.0/10) = 0.8 * 0.20 = 0.16
        # consistency → 0.9 * 0.25 = 0.225
        # error_rate → (1 - 0.1) = 0.9 * 0.15 = 0.135
        # total weight = 1.0, sum = 0.84
        expected = round((0.32 + 0.16 + 0.225 + 0.135) / 1.0, 4)
        assert bench.overall_score == expected

    def test_overall_score_zero_weights(self) -> None:
        """Overall score handles missing metrics gracefully."""
        bench = BenchmarkResult(
            model_id="empty",
            model_type="general",
            timestamp=time.time(),
            scores={},
            raw_results=[],
            latency_stats={},
            consistency_score=0.0,
            total_tokens=0,
            total_time_s=0.0,
            error_rate=0.0,
        )
        # latency uses .get("mean", 5.0) → 5.0 → value = 0.5
        # consistency = 0.0
        # error_rate → 1.0 - 0.0 = 1.0
        # accuracy missing → skipped
        # total weight = 0.20 + 0.25 + 0.15 = 0.60
        # weighted_sum = 0.5*0.20 + 0.0*0.25 + 1.0*0.15 = 0.1 + 0.0 + 0.15 = 0.25
        expected = round(0.25 / 0.60, 4)
        assert bench.overall_score == expected

    def test_overall_score_low_latency_is_good(self) -> None:
        """Low latency contributes positively to overall score."""
        fast = make_benchmark(latency=0.5)
        slow = make_benchmark(latency=5.0)
        assert fast.overall_score > slow.overall_score

    def test_benchmark_result_to_dict(self) -> None:
        """to_dict includes overall_score and all expected keys."""
        bench = make_benchmark()
        d = bench.to_dict()
        assert "overall_score" in d
        assert d["model_id"] == "test-model"
        assert d["model_type"] == "general"
        assert isinstance(d["scores"], dict)
        assert isinstance(d["latency_stats"], dict)
        assert isinstance(d["consistency_score"], float)
        assert isinstance(d["error_rate"], float)

    def test_benchmark_result_high_error_rate(self) -> None:
        """High error rate reduces overall score."""
        good = make_benchmark(error_rate=0.0)
        bad = make_benchmark(error_rate=0.9)
        assert good.overall_score > bad.overall_score


# ──── GateResult ─────────────────────────────────────────────────────


class TestGateResult:
    """Tests for GateResult dataclass and its to_dict serialisation."""

    def test_gate_result_to_dict(self) -> None:
        """to_dict includes all fields with proper rounding."""
        before = make_benchmark(accuracy=0.7)
        after = make_benchmark(accuracy=0.9)
        gr = GateResult(
            passed=True,
            policy="no_regression",
            model_id="v2",
            model_type="general",
            scores_before=before.scores,
            scores_after=after.scores,
            delta={"accuracy": 0.200001, "latency": -0.100001},
            delta_pct={"accuracy": 28.571, "latency": -10.001},
            recommendation="promote",
            reason="All metrics pass",
            timestamp=time.time(),
            benchmark_before=before,
            benchmark_after=after,
        )
        d = gr.to_dict()
        assert d["passed"] is True
        assert d["policy"] == "no_regression"
        assert d["delta"]["accuracy"] == 0.2
        assert d["delta"]["latency"] == -0.1
        assert d["delta_pct"]["accuracy"] == 28.57
        assert "benchmark_before" in d
        assert "benchmark_after" in d
        assert d["benchmark_before"]["model_id"] == "test-model"

    def test_gate_result_without_benchmarks(self) -> None:
        """to_dict handles None benchmark_before/after."""
        gr = GateResult(
            passed=False,
            policy="must_improve",
            model_id="v3",
            model_type="router",
            scores_before={},
            scores_after={},
            delta={},
            delta_pct={},
            recommendation="reject",
            reason="No benchmarks",
            timestamp=time.time(),
            benchmark_before=None,
            benchmark_after=None,
        )
        d = gr.to_dict()
        assert d["benchmark_before"] is None
        assert d["benchmark_after"] is None


# ──── Static Helpers ─────────────────────────────────────────────────


class TestStaticHelpers:
    """Tests for EvaluationGate static/class helper methods."""

    def test_compute_latency_stats_normal(self) -> None:
        """Latency stats computed correctly for normal data."""
        latencies = [1.0, 2.0, 3.0, 4.0, 5.0]
        stats = EvaluationGate._compute_latency_stats(latencies)
        assert stats["mean"] == 3.0
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0
        assert stats["p50"] == 3.0
        assert stats["stdev"] > 0

    def test_compute_latency_stats_empty(self) -> None:
        """Empty latencies return zeroes."""
        stats = EvaluationGate._compute_latency_stats([])
        assert stats["mean"] == 0.0
        assert stats["p50"] == 0.0
        assert stats["p95"] == 0.0
        assert stats["p99"] == 0.0
        assert stats["min"] == 0.0
        assert stats["max"] == 0.0
        assert stats["stdev"] == 0.0

    def test_compute_consistency_identical(self) -> None:
        """Identical outputs score 1.0."""
        outputs = [["hello world", "hello world", "hello world"]]
        score = EvaluationGate._compute_consistency(outputs)
        assert score == 1.0

    def test_compute_consistency_different(self) -> None:
        """Different outputs score < 1.0."""
        outputs = [
            ["apples are red fruits", "bananas are yellow fruits", "grapes are purple"]
        ]
        score = EvaluationGate._compute_consistency(outputs)
        assert 0.0 < score < 1.0

    def test_parse_judge_score_simple(self) -> None:
        """Parse '8' from judge output."""
        assert EvaluationGate._parse_judge_score("8") == 8

    def test_parse_judge_score_with_text(self) -> None:
        """Parse '7' from 'Score: 7 out of 10'."""
        # Note: "7/10" keeps "/" in the middle after strip, so use spaces
        assert EvaluationGate._parse_judge_score("Score: 7 out of 10") == 7


# ──── Policy Evaluators ──────────────────────────────────────────────


class TestNoRegressionPolicy:
    """Tests for the NO_REGRESSION gate policy."""

    def test_no_regression_pass(self, tmp_path: Path) -> None:
        """Model within threshold passes."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(accuracy=0.8, latency=1.0, consistency=0.9)
        candidate = make_benchmark(accuracy=0.78, latency=1.02, consistency=0.88)
        passed, rec, reason = gate._evaluate_no_regression(baseline, candidate, 0.95)
        assert passed is True
        assert rec == "promote"

    def test_no_regression_fail(self, tmp_path: Path) -> None:
        """Model below threshold fails."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(accuracy=0.8, latency=1.0, consistency=0.9)
        candidate = make_benchmark(accuracy=0.5, latency=1.0, consistency=0.9)
        passed, rec, reason = gate._evaluate_no_regression(baseline, candidate, 0.95)
        assert passed is False
        assert "Regression" in reason

    def test_no_regression_latency_regression(self, tmp_path: Path) -> None:
        """Latency regression detected (higher latency is worse)."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(accuracy=0.8, latency=1.0, consistency=0.9)
        # Latency ceiling = old / threshold = 1.0 / 0.95 ≈ 1.053
        candidate = make_benchmark(accuracy=0.8, latency=2.0, consistency=0.9)
        passed, rec, reason = gate._evaluate_no_regression(baseline, candidate, 0.95)
        assert passed is False
        assert "latency" in reason.lower()


class TestMustImprovePolicy:
    """Tests for the MUST_IMPROVE gate policy."""

    def test_must_improve_pass(self, tmp_path: Path) -> None:
        """Required metric improved passes."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(accuracy=0.7)
        candidate = make_benchmark(accuracy=0.85)
        passed, rec, reason = gate._evaluate_must_improve(baseline, candidate, "accuracy")
        assert passed is True
        assert rec == "promote"
        assert "improved" in reason.lower()

    def test_must_improve_unchanged(self, tmp_path: Path) -> None:
        """Unchanged metric → review recommendation."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(accuracy=0.8)
        candidate = make_benchmark(accuracy=0.8)
        passed, rec, reason = gate._evaluate_must_improve(baseline, candidate, "accuracy")
        assert passed is False
        assert rec == "review"
        assert "unchanged" in reason.lower()

    def test_must_improve_regressed(self, tmp_path: Path) -> None:
        """Regressed metric → reject."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(accuracy=0.9)
        candidate = make_benchmark(accuracy=0.7)
        passed, rec, reason = gate._evaluate_must_improve(baseline, candidate, "accuracy")
        assert passed is False
        assert rec == "reject"
        assert "regressed" in reason.lower()


class TestParetoPolicy:
    """Tests for the PARETO_DOMINANT gate policy."""

    def test_pareto_non_dominated(self, tmp_path: Path) -> None:
        """Candidate better on at least one metric passes."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(accuracy=0.8, latency=1.0, consistency=0.9)
        candidate = make_benchmark(accuracy=0.85, latency=1.0, consistency=0.9)
        passed, rec, reason = gate._evaluate_pareto(baseline, candidate)
        assert passed is True

    def test_pareto_dominated(self, tmp_path: Path) -> None:
        """Candidate worse on all metrics fails."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(accuracy=0.9, latency=0.5, consistency=0.95)
        # Worse accuracy, worse (higher) latency, worse consistency
        candidate = make_benchmark(accuracy=0.7, latency=2.0, consistency=0.6)
        passed, rec, reason = gate._evaluate_pareto(baseline, candidate)
        assert passed is False
        assert rec == "reject"
        assert "dominated" in reason.lower()


# ──── EvaluationGate API ─────────────────────────────────────────────


class TestEvaluationGateAPI:
    """Tests for the EvaluationGate public API methods."""

    def test_gate_init_creates_db(self, tmp_path: Path) -> None:
        """Gate creates SQLite database on init."""
        db_path = tmp_path / "sub" / "gate.db"
        gate = EvaluationGate(db_path=db_path)
        assert db_path.exists()

    def test_run_gate_no_baseline(self, tmp_path: Path) -> None:
        """run_gate works when no baseline exists (creates empty baseline)."""
        gate = make_gate(tmp_path)
        candidate = make_benchmark(model_id="model-v1", accuracy=0.8)

        with patch.object(gate, "get_baseline", return_value=None), \
             patch.object(gate, "run_benchmark", return_value=candidate), \
             patch.object(gate, "_log_to_nexus"), \
             patch.object(gate, "_record_impact"), \
             patch.object(gate, "_update_registry_score"):
            result = gate.run_gate("model-v1", "general")

        assert result.passed is True
        assert result.policy == "no_regression"
        # Empty baseline has zeroes, so any non-zero candidate passes
        assert result.scores_before == {"accuracy": 0.0, "latency": 0.0, "consistency": 0.0}

    def test_run_gate_custom_policy(self, tmp_path: Path) -> None:
        """CUSTOM policy uses provided function."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(model_id="base", accuracy=0.7)
        candidate = make_benchmark(model_id="new", accuracy=0.9)

        custom_fn = MagicMock(return_value=(True, "promote", "Custom OK"))

        with patch.object(gate, "get_baseline", return_value=baseline), \
             patch.object(gate, "run_benchmark", return_value=candidate), \
             patch.object(gate, "_log_to_nexus"), \
             patch.object(gate, "_record_impact"), \
             patch.object(gate, "_update_registry_score"):
            result = gate.run_gate(
                "new", "general",
                policy=GatePolicy.CUSTOM,
                custom_fn=custom_fn,
            )

        assert result.passed is True
        assert result.recommendation == "promote"
        assert result.reason == "Custom OK"
        custom_fn.assert_called_once()

    def test_get_gate_history_empty(self, tmp_path: Path) -> None:
        """Empty DB returns empty list."""
        gate = make_gate(tmp_path)
        history = gate.get_gate_history("general")
        assert history == []

    def test_get_gate_history_with_data(self, tmp_path: Path) -> None:
        """After run_gate, history contains the result."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(model_id="base")
        candidate = make_benchmark(model_id="candidate")

        with patch.object(gate, "get_baseline", return_value=baseline), \
             patch.object(gate, "run_benchmark", return_value=candidate), \
             patch.object(gate, "_log_to_nexus"), \
             patch.object(gate, "_record_impact"), \
             patch.object(gate, "_update_registry_score"):
            gate.run_gate("candidate", "general")

        history = gate.get_gate_history("general")
        assert len(history) == 1
        assert history[0]["model_id"] == "candidate"
        assert history[0]["model_type"] == "general"
        assert history[0]["policy"] == "no_regression"

    def test_get_benchmark_history(self, tmp_path: Path) -> None:
        """After storing a benchmark, history contains the result."""
        gate = make_gate(tmp_path)
        bench = make_benchmark(model_id="bench-model")
        gate._store_benchmark(bench)

        history = gate.get_benchmark_history("general")
        assert len(history) == 1
        assert history[0]["model_id"] == "bench-model"
        assert history[0]["overall_score"] == bench.overall_score

    def test_get_default_prompts_known(self) -> None:
        """Known model_type returns specific prompts."""
        gate = EvaluationGate.__new__(EvaluationGate)
        prompts = gate.get_default_prompts("router")
        assert len(prompts) == 5
        assert all("Route" in p for p in prompts)
        # Verify we get a copy, not the original list
        prompts.append("extra")
        assert len(gate.get_default_prompts("router")) == 5

    def test_get_default_prompts_unknown(self) -> None:
        """Unknown model_type falls back to general."""
        gate = EvaluationGate.__new__(EvaluationGate)
        prompts = gate.get_default_prompts("nonexistent_type_xyz")
        assert prompts == DEFAULT_BENCHMARK_PROMPTS["general"]


# ──── Singleton ──────────────────────────────────────────────────────


class TestSingleton:
    """Tests for the get_evaluation_gate singleton factory."""

    def test_singleton_returns_same_instance(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_evaluation_gate returns same instance on repeated calls."""
        monkeypatch.setattr("training.evaluation_gate._gate_instance", None)
        db = tmp_path / "singleton.db"
        first = get_evaluation_gate(db)
        second = get_evaluation_gate(db)
        assert first is second
        # Clean up singleton so other tests aren't affected
        monkeypatch.setattr("training.evaluation_gate._gate_instance", None)

    def test_failed_benchmark_error_rate(self) -> None:
        """_failed_benchmark has error_rate=1.0 and zero accuracy."""
        bench = EvaluationGate._failed_benchmark("bad-model", "router", "connection refused")
        assert bench.error_rate == 1.0
        assert bench.scores["accuracy"] == 0.0
        assert bench.model_id == "bad-model"
        assert bench.model_type == "router"
        assert bench.raw_results[0]["error"] == "connection refused"


# ──── Integration-like Tests ─────────────────────────────────────────


class TestPersistence:
    """Tests that verify SQLite persistence of results."""

    def test_store_gate_result(self, tmp_path: Path) -> None:
        """Gate result persisted to SQLite."""
        gate = make_gate(tmp_path)
        gr = GateResult(
            passed=True,
            policy="no_regression",
            model_id="m1",
            model_type="general",
            scores_before={"accuracy": 0.7},
            scores_after={"accuracy": 0.8},
            delta={"accuracy": 0.1},
            delta_pct={"accuracy": 14.29},
            recommendation="promote",
            reason="All good",
            timestamp=time.time(),
        )
        gate._store_gate_result(gr)
        history = gate.get_gate_history("general")
        assert len(history) == 1
        assert history[0]["passed"] is True
        assert history[0]["recommendation"] == "promote"

    def test_store_benchmark(self, tmp_path: Path) -> None:
        """Benchmark result persisted to SQLite."""
        gate = make_gate(tmp_path)
        bench = make_benchmark(model_id="bm1", model_type="router")
        gate._store_benchmark(bench)

        history = gate.get_benchmark_history("router")
        assert len(history) == 1
        assert history[0]["model_id"] == "bm1"
        assert history[0]["scores"]["accuracy"] == 0.8

    def test_gate_result_persisted_after_run(self, tmp_path: Path) -> None:
        """Full run_gate persists both gate and benchmark results."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(model_id="base", accuracy=0.7)
        candidate = make_benchmark(model_id="candidate", accuracy=0.85)

        with patch.object(gate, "get_baseline", return_value=baseline), \
             patch.object(gate, "run_benchmark", return_value=candidate), \
             patch.object(gate, "_log_to_nexus"), \
             patch.object(gate, "_record_impact"), \
             patch.object(gate, "_update_registry_score"):
            result = gate.run_gate("candidate", "general")

        assert result.passed is True
        gate_history = gate.get_gate_history("general")
        assert len(gate_history) == 1
        assert gate_history[0]["model_id"] == "candidate"
        assert gate_history[0]["passed"] is True

    def test_custom_policy_must_return_tuple(self, tmp_path: Path) -> None:
        """CUSTOM policy without custom_fn raises ValueError."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark()
        candidate = make_benchmark()

        with patch.object(gate, "get_baseline", return_value=baseline), \
             patch.object(gate, "run_benchmark", return_value=candidate), \
             patch.object(gate, "_log_to_nexus"), \
             patch.object(gate, "_record_impact"), \
             patch.object(gate, "_update_registry_score"):
            with pytest.raises(ValueError, match="custom_fn"):
                gate.run_gate(
                    "model-x", "general",
                    policy=GatePolicy.CUSTOM,
                    custom_fn=None,
                )


# ──── Edge Cases ─────────────────────────────────────────────────────


class TestEdgeCases:
    """Additional edge-case and boundary tests."""

    def test_make_empty_baseline_zeroes(self) -> None:
        """_make_empty_baseline returns all-zero scores."""
        bench = EvaluationGate._make_empty_baseline("router")
        assert bench.model_id == "__no_baseline__"
        assert bench.scores["accuracy"] == 0.0
        assert bench.scores["latency"] == 0.0
        assert bench.scores["consistency"] == 0.0
        assert bench.error_rate == 0.0
        assert bench.timestamp == 0.0

    def test_parse_judge_score_out_of_range(self) -> None:
        """Score outside 0-10 returns 0."""
        assert EvaluationGate._parse_judge_score("15") == 0
        assert EvaluationGate._parse_judge_score("-3") == 0

    def test_parse_judge_score_no_number(self) -> None:
        """Non-numeric text returns 0."""
        assert EvaluationGate._parse_judge_score("excellent work") == 0

    def test_parse_judge_score_float_text(self) -> None:
        """Float like '8.5' is parsed to int 8."""
        assert EvaluationGate._parse_judge_score("8.5") == 8

    def test_compute_consistency_empty_list(self) -> None:
        """Empty outputs list returns 0.0."""
        assert EvaluationGate._compute_consistency([]) == 0.0

    def test_compute_consistency_all_empty_strings(self) -> None:
        """All-empty outputs for a prompt return 0.0 consistency."""
        score = EvaluationGate._compute_consistency([["", "", ""]])
        assert score == 0.0

    def test_compute_consistency_single_output(self) -> None:
        """Single non-empty output is trivially consistent (1.0)."""
        score = EvaluationGate._compute_consistency([["hello"]])
        assert score == 1.0

    def test_latency_stats_single_value(self) -> None:
        """Single latency value: stdev=0, all percentiles equal."""
        stats = EvaluationGate._compute_latency_stats([2.5])
        assert stats["mean"] == 2.5
        assert stats["p50"] == 2.5
        assert stats["min"] == 2.5
        assert stats["max"] == 2.5
        assert stats["stdev"] == 0.0

    def test_must_improve_latency_lower_is_better(self, tmp_path: Path) -> None:
        """MUST_IMPROVE on latency: lower value counts as improvement."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(latency=3.0)
        candidate = make_benchmark(latency=1.5)
        passed, rec, reason = gate._evaluate_must_improve(baseline, candidate, "latency")
        assert passed is True
        assert "improved" in reason.lower()

    def test_pareto_trade_off(self, tmp_path: Path) -> None:
        """Pareto trade-off: better on one, worse on another → pass with review."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(accuracy=0.8, latency=1.0, consistency=0.9)
        candidate = make_benchmark(accuracy=0.9, latency=2.0, consistency=0.9)
        passed, rec, reason = gate._evaluate_pareto(baseline, candidate)
        assert passed is True
        assert rec == "review"
        assert "trade-off" in reason.lower()

    def test_benchmark_history_no_filter(self, tmp_path: Path) -> None:
        """get_benchmark_history without model_type returns all types."""
        gate = make_gate(tmp_path)
        gate._store_benchmark(make_benchmark(model_id="a", model_type="router"))
        gate._store_benchmark(make_benchmark(model_id="b", model_type="general"))

        history = gate.get_benchmark_history(model_type=None)
        assert len(history) == 2

    def test_gate_history_no_filter(self, tmp_path: Path) -> None:
        """get_gate_history without model_type returns all types."""
        gate = make_gate(tmp_path)
        gr1 = GateResult(
            passed=True, policy="no_regression", model_id="m1",
            model_type="router", scores_before={}, scores_after={},
            delta={}, delta_pct={}, recommendation="promote",
            reason="ok", timestamp=time.time(),
        )
        gr2 = GateResult(
            passed=False, policy="must_improve", model_id="m2",
            model_type="general", scores_before={}, scores_after={},
            delta={}, delta_pct={}, recommendation="reject",
            reason="bad", timestamp=time.time(),
        )
        gate._store_gate_result(gr1)
        gate._store_gate_result(gr2)

        history = gate.get_gate_history(model_type=None)
        assert len(history) == 2

    def test_run_gate_must_improve_policy(self, tmp_path: Path) -> None:
        """run_gate with MUST_IMPROVE policy correctly delegates."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(model_id="base", accuracy=0.6)
        candidate = make_benchmark(model_id="new", accuracy=0.85)

        with patch.object(gate, "get_baseline", return_value=baseline), \
             patch.object(gate, "run_benchmark", return_value=candidate), \
             patch.object(gate, "_log_to_nexus"), \
             patch.object(gate, "_record_impact"), \
             patch.object(gate, "_update_registry_score"):
            result = gate.run_gate(
                "new", "general",
                policy=GatePolicy.MUST_IMPROVE,
                required_metric="accuracy",
            )

        assert result.passed is True
        assert result.policy == "must_improve"
        assert result.delta["accuracy"] > 0

    def test_run_gate_pareto_policy(self, tmp_path: Path) -> None:
        """run_gate with PARETO_DOMINANT policy correctly delegates."""
        gate = make_gate(tmp_path)
        baseline = make_benchmark(model_id="base", accuracy=0.8)
        candidate = make_benchmark(model_id="new", accuracy=0.85)

        with patch.object(gate, "get_baseline", return_value=baseline), \
             patch.object(gate, "run_benchmark", return_value=candidate), \
             patch.object(gate, "_log_to_nexus"), \
             patch.object(gate, "_record_impact"), \
             patch.object(gate, "_update_registry_score"):
            result = gate.run_gate(
                "new", "general",
                policy=GatePolicy.PARETO_DOMINANT,
            )

        assert result.passed is True
        assert result.policy == "pareto_dominant"

    def test_default_prompts_all_types_have_five(self) -> None:
        """Every entry in DEFAULT_BENCHMARK_PROMPTS has 5 prompts."""
        for key, prompts in DEFAULT_BENCHMARK_PROMPTS.items():
            assert len(prompts) == 5, f"{key} has {len(prompts)} prompts, expected 5"

    def test_gate_policy_values(self) -> None:
        """GatePolicy enum has expected members."""
        assert GatePolicy.NO_REGRESSION.value == "no_regression"
        assert GatePolicy.MUST_IMPROVE.value == "must_improve"
        assert GatePolicy.PARETO_DOMINANT.value == "pareto_dominant"
        assert GatePolicy.CUSTOM.value == "custom"
