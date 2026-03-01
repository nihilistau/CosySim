"""Tests for Model Registry and Benchmark Runner."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from training.model_registry import ModelRegistry, RegisteredModel, get_model_registry
from training.benchmark_runner import BenchmarkRunner, BenchmarkResult, get_benchmark_runner


# ──── Model Registry Tests ─────────────────────────────────────────────────────

@pytest.fixture
def registry(tmp_path):
    reg_path = tmp_path / "model_registry.json"
    with patch("training.model_registry._REGISTRY_PATH", reg_path):
        with patch("training.model_registry._MODELS_DIR", tmp_path / "models"):
            yield ModelRegistry()


class TestModelRegistry:
    def test_register_creates_model(self, registry):
        m = registry.register(
            model_type="qa_evaluator",
            adapter_path="/tmp/adapters/qa",
            base_model="Qwen/Qwen2.5-0.5B-Instruct",
        )
        assert m.model_id
        assert m.model_type == "qa_evaluator"
        assert not m.active

    def test_list_models_empty(self, registry):
        models = registry.list_models()
        assert models == []

    def test_promote_sets_active(self, registry):
        m = registry.register("qa_evaluator", "/tmp/adapter", "Qwen/test")
        registry.promote("qa_evaluator", m.model_id)
        assert registry.get_active("qa_evaluator").model_id == m.model_id

    def test_promote_demotes_previous(self, registry):
        m1 = registry.register("qa_evaluator", "/tmp/adapter1", "Qwen/test")
        m2 = registry.register("qa_evaluator", "/tmp/adapter2", "Qwen/test")
        registry.promote("qa_evaluator", m1.model_id)
        registry.promote("qa_evaluator", m2.model_id)
        assert registry.get_active("qa_evaluator").model_id == m2.model_id
        # m1 should no longer be active
        assert not registry._models[m1.model_id].active

    def test_update_benchmark(self, registry):
        m = registry.register("router_v2", "/tmp/adapter", "Qwen/test")
        registry.update_benchmark(m.model_id, 0.87, {"accuracy": 0.87})
        updated = registry.get_model(m.model_id)
        assert updated["benchmark_score"] == 0.87

    def test_auto_promote_best_score(self, registry):
        m1 = registry.register("qa_evaluator", "/tmp/a1", "Qwen/test")
        m2 = registry.register("qa_evaluator", "/tmp/a2", "Qwen/test")
        registry.update_benchmark(m1.model_id, 0.75)
        registry.update_benchmark(m2.model_id, 0.92)
        promoted = registry.auto_promote("qa_evaluator")
        assert promoted.model_id == m2.model_id

    def test_auto_promote_no_models_returns_none(self, registry):
        result = registry.auto_promote("knowledge_synthesizer")
        assert result is None

    def test_delete_removes_model(self, registry):
        m = registry.register("syntax_fixer", "/tmp/adapter", "Qwen/test")
        registry.delete(m.model_id)
        assert registry.get_model(m.model_id) is None

    def test_delete_unknown_raises(self, registry):
        with pytest.raises(KeyError):
            registry.delete("doesnotexist")

    def test_summary_covers_all_types(self, registry):
        summary = registry.summary()
        from training.micro_datasets import MODELS
        assert set(summary.keys()) == set(MODELS)

    def test_persist_and_reload(self, tmp_path):
        reg_path = tmp_path / "model_registry.json"
        with patch("training.model_registry._REGISTRY_PATH", reg_path):
            with patch("training.model_registry._MODELS_DIR", tmp_path / "models"):
                r1 = ModelRegistry()
                m = r1.register("qa_evaluator", "/tmp/adapter", "Qwen/test")
                r1.promote("qa_evaluator", m.model_id)
            with patch("training.model_registry._REGISTRY_PATH", reg_path):
                with patch("training.model_registry._MODELS_DIR", tmp_path / "models"):
                    r2 = ModelRegistry()
                    assert r2.get_active("qa_evaluator") is not None
                    assert r2.get_active("qa_evaluator").model_id == m.model_id

    def test_singleton(self):
        r1 = get_model_registry()
        r2 = get_model_registry()
        assert r1 is r2


# ──── Benchmark Runner Tests ───────────────────────────────────────────────────

@pytest.fixture
def runner(tmp_path):
    bench_path = tmp_path / "benchmarks.jsonl"
    ds_dir = tmp_path / "datasets"
    ds_dir.mkdir()
    with patch("training.benchmark_runner._BENCHMARKS_PATH", bench_path):
        with patch("training.benchmark_runner._DATASETS_DIR", ds_dir):
            yield BenchmarkRunner()


@pytest.fixture
def test_dataset(tmp_path):
    """Create a small test dataset."""
    ds_dir = tmp_path / "datasets"
    ds_dir.mkdir(exist_ok=True)
    path = ds_dir / "qa_evaluator_test.jsonl"
    examples = [
        {"input": "How does Nexus work?", "output": "essential"},
        {"input": "What is the weather?", "output": "skip"},
        {"input": "What port is LMStudio on?", "output": "essential"},
    ]
    path.write_text("\n".join(json.dumps(e) for e in examples))
    return path


class TestBenchmarkRunner:
    def test_token_f1_identical(self):
        runner = BenchmarkRunner()
        assert runner._token_f1("hello world", "hello world") == 1.0

    def test_token_f1_disjoint(self):
        runner = BenchmarkRunner()
        assert runner._token_f1("foo bar", "baz qux") == 0.0

    def test_token_f1_partial(self):
        runner = BenchmarkRunner()
        score = runner._token_f1("hello world", "hello there")
        assert 0.0 < score < 1.0

    def test_token_f1_empty_strings(self):
        runner = BenchmarkRunner()
        assert runner._token_f1("", "") == 1.0
        assert runner._token_f1("hello", "") == 0.0

    def test_run_no_registered_model_returns_error(self, runner, tmp_path):
        ds_dir = tmp_path / "datasets"
        ds_dir.mkdir(exist_ok=True)
        with patch("training.benchmark_runner._DATASETS_DIR", ds_dir):
            with patch("training.model_registry.get_model_registry") as mock_reg:
                mock_reg.return_value.get_active.return_value = None
                mock_reg.return_value.list_models.return_value = []
                result = runner.run("qa_evaluator")
        assert result.error is not None
        assert result.aggregate_score == 0.0

    def test_run_missing_test_set_returns_error(self, runner, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with patch("training.benchmark_runner._DATASETS_DIR", empty_dir):
            with patch("training.model_registry.get_model_registry") as mock_reg:
                mock_reg.return_value.get_active.return_value = None
                mock_model = MagicMock()
                mock_model.model_id = "test123"
                mock_reg.return_value.list_models.return_value = [{"model_id": "test123"}]
                result = runner.run("qa_evaluator")
        assert result.error is not None

    def test_rule_predictor_qa(self):
        runner = BenchmarkRunner()
        predictor = runner._rule_predictor("qa_evaluator")
        # Short vague → SKIP
        assert predictor("Can you help?") == "SKIP"
        # Technical → ESSENTIAL
        assert predictor("What port does Nexus run on?") == "ESSENTIAL"

    def test_rule_predictor_router(self):
        runner = BenchmarkRunner()
        predictor = runner._rule_predictor("router_v2")
        assert predictor("search nexus for docs") == "nexus_search"
        assert predictor("start bedroom scene") == "scene_control"
        assert predictor("speak this text") == "tts_request"

    def test_get_history_empty(self, runner):
        history = runner.get_history()
        assert history == []

    def test_persist_and_retrieve_history(self, runner, tmp_path):
        bench_path = tmp_path / "benchmarks.jsonl"
        with patch("training.benchmark_runner._BENCHMARKS_PATH", bench_path):
            result = BenchmarkResult(
                model_id="test001", model_type="qa_evaluator",
                accuracy=0.8, f1=0.75, exact_match=0.7,
                total_examples=10, correct=8, latency_ms_avg=50.0,
                aggregate_score=0.77,
            )
            runner._persist(result)
            history = runner.get_history()
        assert len(history) == 1
        assert history[0]["model_id"] == "test001"

    def test_leaderboard_structure(self, runner):
        board = runner.get_leaderboard()
        from training.micro_datasets import MODELS
        assert set(board.keys()) == set(MODELS)
        for v in board.values():
            assert "best_score" in v
            assert "model_id" in v

    def test_singleton(self):
        r1 = get_benchmark_runner()
        r2 = get_benchmark_runner()
        assert r1 is r2
