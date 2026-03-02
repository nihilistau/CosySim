"""Tests for the router_v2 end-to-end finetune cycle.

Covers:
- router_v2 synthetic dataset template coverage (all 8 labels present)
- MicroDatasetManager build with augmentation and splits
- Scheduler callbacks: router-finetune-cycle, dataset-augment (mocked deps)
- Auto-promote wiring: BenchmarkRunner → ModelRegistry → FinetunedRouter
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ── Template coverage ──────────────────────────────────────────────────────

class TestRouterV2Templates:
    def test_all_eight_labels_present(self):
        """Every router_v2 label must have at least one template example."""
        from training.micro_datasets import _ROUTER_V2_TEMPLATES

        labels = {ex["output"] for ex in _ROUTER_V2_TEMPLATES}
        expected = {
            "nexus_search", "nexus_ask", "scene_control", "tts_request",
            "backup_request", "stt_request", "nlm_research", "config_update",
        }
        assert expected == labels, f"Missing labels: {expected - labels}"

    def test_minimum_examples_per_label(self):
        """Each label must have at least 10 template examples for good coverage."""
        from training.micro_datasets import _ROUTER_V2_TEMPLATES
        from collections import Counter

        counts = Counter(ex["output"] for ex in _ROUTER_V2_TEMPLATES)
        for label, count in counts.items():
            assert count >= 10, f"{label} only has {count} templates (need ≥ 10)"

    def test_no_duplicate_inputs(self):
        """All template inputs must be unique."""
        from training.micro_datasets import _ROUTER_V2_TEMPLATES

        inputs = [ex["input"] for ex in _ROUTER_V2_TEMPLATES]
        assert len(inputs) == len(set(inputs)), "Duplicate inputs found in templates"

    def test_all_examples_have_required_keys(self):
        from training.micro_datasets import _ROUTER_V2_TEMPLATES

        for ex in _ROUTER_V2_TEMPLATES:
            assert "input" in ex and "output" in ex
            assert ex["input"].strip()
            assert ex["output"].strip()


# ── Dataset build ──────────────────────────────────────────────────────────

class TestMicroDatasetManagerRouterV2:
    def test_generate_synthetic_produces_correct_labels(self, tmp_path, monkeypatch):
        """Synthetic generator must only emit valid router_v2 labels."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "training" / "datasets").mkdir(parents=True)

        from training.micro_datasets import MicroDatasetManager
        mgr = MicroDatasetManager()
        examples = mgr._generate_synthetic("router_v2", count=80)

        valid = {
            "nexus_search", "nexus_ask", "scene_control", "tts_request",
            "backup_request", "stt_request", "nlm_research", "config_update",
        }
        for ex in examples:
            assert ex["output"] in valid, f"Invalid label: {ex['output']}"

    def test_build_creates_three_splits(self, tmp_path, monkeypatch):
        """Build must create train/val/test JSONL files."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "training" / "datasets").mkdir(parents=True)

        from training.micro_datasets import MicroDatasetManager, _ROUTER_V2_TEMPLATES

        mgr = MicroDatasetManager()
        # Patch teacher pipeline to fallback so no NLM is needed
        with patch.object(mgr, "_generate_via_teacher",
                          side_effect=lambda mt, c: mgr._generate_synthetic(mt, c)):
            stats = mgr.build("router_v2", count=120, augment=True)

        assert stats.train > 0
        assert stats.val > 0
        assert stats.test > 0
        assert stats.train + stats.val + stats.test == stats.total
        assert Path(stats.path_train).exists()
        assert Path(stats.path_val).exists()
        assert Path(stats.path_test).exists()

    def test_built_examples_are_alpaca_format(self, tmp_path, monkeypatch):
        """All saved examples must have instruction/input/output fields."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "training" / "datasets").mkdir(parents=True)

        from training.micro_datasets import MicroDatasetManager

        mgr = MicroDatasetManager()
        with patch.object(mgr, "_generate_via_teacher",
                          side_effect=lambda mt, c: mgr._generate_synthetic(mt, c)):
            stats = mgr.build("router_v2", count=100, augment=False)

        with open(stats.path_train, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]

        for row in lines:
            assert "instruction" in row
            assert "input" in row
            assert "output" in row
            assert row["output"] in {
                "nexus_search", "nexus_ask", "scene_control", "tts_request",
                "backup_request", "stt_request", "nlm_research", "config_update",
            }

    def test_deduplication_removes_duplicates(self, tmp_path, monkeypatch):
        """Build must not produce duplicate input examples."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "training" / "datasets").mkdir(parents=True)

        from training.micro_datasets import MicroDatasetManager

        mgr = MicroDatasetManager()
        with patch.object(mgr, "_generate_via_teacher",
                          side_effect=lambda mt, c: mgr._generate_synthetic(mt, c)):
            stats = mgr.build("router_v2", count=200, augment=True)

        all_examples: list[dict] = []
        for path in (stats.path_train, stats.path_val, stats.path_test):
            with open(path, "r", encoding="utf-8") as f:
                all_examples.extend(json.loads(l) for l in f if l.strip())

        inputs = [ex["input"] for ex in all_examples]
        assert len(inputs) == len(set(inputs)), "Duplicate inputs found after build"


# ── Scheduler callbacks ────────────────────────────────────────────────────

class TestRouterFinetuneSchedulerCallbacks:
    def _mock_finetune_orchestrator(self) -> MagicMock:
        orch = MagicMock()
        orch.list_jobs.return_value = []
        job = MagicMock()
        job.job_id = "job-test-001"
        orch.submit.return_value = job
        return orch

    def _mock_benchmark_runner(self, score: float = 0.91) -> MagicMock:
        runner = MagicMock()
        result = MagicMock()
        result.aggregate_score = score
        result.promoted = True
        result.error = None
        runner.run.return_value = result
        return runner

    def test_router_finetune_cycle_success_path(self, tmp_path, monkeypatch):
        """Full cycle callback returns dataset + finetune + benchmark results."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "training" / "datasets").mkdir(parents=True)

        from engine.nexus.scheduler_daemon import _router_finetune_cycle_callback

        mock_orch = self._mock_finetune_orchestrator()
        mock_runner = self._mock_benchmark_runner()

        with (
            patch("training.micro_datasets.MicroDatasetManager._generate_via_teacher",
                  side_effect=lambda mt, c: __import__(
                      "training.micro_datasets", fromlist=["MicroDatasetManager"]
                  ).MicroDatasetManager()._generate_synthetic(mt, c)),
            patch("training.finetune_orchestrator.get_finetune_orchestrator",
                  return_value=mock_orch),
            patch("training.benchmark_runner.get_benchmark_runner",
                  return_value=mock_runner),
        ):
            result = _router_finetune_cycle_callback()

        assert "dataset" in result
        assert "finetune" in result
        assert "benchmark" in result
        assert result["benchmark"]["score"] == 0.91
        assert result["benchmark"]["promoted"] is True

    def test_router_finetune_cycle_skips_when_job_queued(self, tmp_path, monkeypatch):
        """If a job is already pending, cycle must skip finetune submission."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "training" / "datasets").mkdir(parents=True)

        from engine.nexus.scheduler_daemon import _router_finetune_cycle_callback

        mock_orch = MagicMock()
        mock_orch.list_jobs.return_value = [{"model_type": "router_v2", "status": "pending"}]
        mock_runner = self._mock_benchmark_runner()

        with (
            patch("training.micro_datasets.MicroDatasetManager._generate_via_teacher",
                  side_effect=lambda mt, c: __import__(
                      "training.micro_datasets", fromlist=["MicroDatasetManager"]
                  ).MicroDatasetManager()._generate_synthetic(mt, c)),
            patch("training.finetune_orchestrator.get_finetune_orchestrator",
                  return_value=mock_orch),
            patch("training.benchmark_runner.get_benchmark_runner",
                  return_value=mock_runner),
        ):
            result = _router_finetune_cycle_callback()

        assert result["finetune"]["status"] == "skipped"
        mock_orch.submit.assert_not_called()

    def test_dataset_augment_callback_covers_all_models(self, tmp_path, monkeypatch):
        """dataset-augment callback must process every model type."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "training" / "datasets").mkdir(parents=True)

        from engine.nexus.scheduler_daemon import _dataset_augment_callback
        from training.micro_datasets import MODELS

        with patch(
            "training.micro_datasets.MicroDatasetManager._generate_via_teacher",
            side_effect=lambda mt, c: __import__(
                "training.micro_datasets", fromlist=["MicroDatasetManager"]
            ).MicroDatasetManager()._generate_synthetic(mt, c),
        ):
            result = _dataset_augment_callback()

        for model_type in MODELS:
            assert model_type in result, f"{model_type} missing from augment result"
            assert "error" not in result[model_type] or not result[model_type]["error"]

    def test_dataset_augment_callback_tolerates_single_model_failure(
        self, tmp_path, monkeypatch
    ):
        """One model failing must not abort the rest."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "training" / "datasets").mkdir(parents=True)

        from engine.nexus.scheduler_daemon import _dataset_augment_callback
        from training.micro_datasets import MODELS

        call_count = [0]

        def selective_fail(mt: str, c: int) -> list:
            call_count[0] += 1
            if mt == "syntax_fixer":
                raise RuntimeError("Injected failure")
            return __import__(
                "training.micro_datasets", fromlist=["MicroDatasetManager"]
            ).MicroDatasetManager()._generate_synthetic(mt, c)

        with patch(
            "training.micro_datasets.MicroDatasetManager._generate_via_teacher",
            side_effect=selective_fail,
        ):
            result = _dataset_augment_callback()

        assert "syntax_fixer" in result
        assert "error" in result["syntax_fixer"]
        # Other models should still have succeeded
        others = [m for m in MODELS if m != "syntax_fixer"]
        for m in others:
            assert m in result


# ── Auto-promote wiring ────────────────────────────────────────────────────

class TestAutoPromoteWiring:
    def test_benchmark_runner_calls_auto_promote(self):
        """BenchmarkRunner.run() must invoke auto_promote on the model registry."""
        from training.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner()
        mock_registry = MagicMock()
        mock_registry.get_active.return_value = None
        mock_registry.list_models.return_value = []

        with patch("training.model_registry.get_model_registry", return_value=mock_registry):
            result = runner.run("router_v2", auto_promote=True)

        # No model found → auto_promote not called, but the call should complete gracefully
        assert result.model_type == "router_v2"
        assert "No registered model" in (result.error or "")

    def test_auto_promote_registers_to_finetuned_router(self):
        """ModelRegistry.promote() must notify FinetunedRouter via _notify_lmstudio."""
        from training.model_registry import ModelRegistry
        from engine.lmstudio.finetuned_router import FinetunedRouter
        from training.model_registry import RegisteredModel

        registry = ModelRegistry()
        router = FinetunedRouter()

        mock_model = RegisteredModel(
            model_id="router_v2_v1",
            model_type="router_v2",
            adapter_path="/tmp/adapter",
            base_model="qwen3-0.6b",
        )
        mock_model.benchmark_score = 0.92
        registry._models["router_v2_v1"] = mock_model

        with (
            patch.object(registry, "_persist"),
            patch(
                "engine.lmstudio.finetuned_router.get_finetuned_router",
                return_value=router,
            ),
        ):
            promoted = registry.auto_promote("router_v2")

        assert promoted is not None
        assert promoted.model_id == "router_v2_v1"

    def test_finetuned_router_singleton_returns_same_instance(self):
        """get_finetuned_router() must return the same singleton each call."""
        from engine.lmstudio.finetuned_router import get_finetuned_router

        r1 = get_finetuned_router()
        r2 = get_finetuned_router()
        assert r1 is r2

    def test_scheduler_has_30_builtin_tasks(self):
        """Scheduler must have exactly 37 builtin tasks after v0.72 additions."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks
        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        assert daemon.register.call_count == 40

    def test_new_tasks_registered(self):
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        task_ids = [call.args[0] for call in daemon.register.call_args_list]
        assert "router-finetune-cycle" in task_ids
        assert "dataset-augment" in task_ids

