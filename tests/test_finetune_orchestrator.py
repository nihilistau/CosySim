"""Tests for FinetuneOrchestrator."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from training.finetune_orchestrator import (
    FinetuneOrchestrator,
    FinetuneJob,
    FinetuneConfig,
    JobStatus,
    BASE_MODEL_ALIASES,
    get_finetune_orchestrator,
)


@pytest.fixture
def orch(tmp_path):
    """Orchestrator with temp job file."""
    with patch("training.finetune_orchestrator._JOBS_PATH", tmp_path / "jobs.jsonl"):
        with patch("training.finetune_orchestrator._MODELS_DIR", tmp_path / "models"):
            yield FinetuneOrchestrator()


@pytest.fixture
def dataset_file(tmp_path):
    """Create a minimal training dataset."""
    ds_dir = tmp_path / "datasets"
    ds_dir.mkdir()
    path = ds_dir / "qa_evaluator_train.jsonl"
    path.write_text(json.dumps({"instruction": "test", "input": "q", "output": "ESSENTIAL"}) + "\n")
    return path


class TestFinetuneJob:
    def test_is_terminal(self):
        job = FinetuneJob(job_id="abc", model_type="qa_evaluator", base_model="test",
                         dataset_path="", output_dir="")
        assert not job.is_terminal()
        job.status = JobStatus.DONE
        assert job.is_terminal()
        job.status = JobStatus.FAILED
        assert job.is_terminal()

    def test_to_dict_from_dict_roundtrip(self):
        job = FinetuneJob(job_id="xyz", model_type="router_v2", base_model="Qwen/test",
                         dataset_path="/data", output_dir="/out")
        d = job.to_dict()
        restored = FinetuneJob.from_dict(d)
        assert restored.job_id == "xyz"
        assert restored.model_type == "router_v2"


class TestFinetuneOrchestrator:
    def test_submit_resolves_alias(self, orch, dataset_file):
        with patch("training.finetune_orchestrator._DATASETS_DIR", dataset_file.parent):
            job = orch.submit("qa_evaluator", base_model="qwen-270m")
        assert job.base_model == BASE_MODEL_ALIASES["qwen-270m"]
        assert job.status == JobStatus.PENDING

    def test_submit_missing_dataset_raises(self, orch, tmp_path):
        with patch("training.finetune_orchestrator._DATASETS_DIR", tmp_path / "nonexistent"):
            with pytest.raises(FileNotFoundError):
                orch.submit("qa_evaluator")

    def test_list_jobs_empty(self, orch):
        jobs = orch.list_jobs()
        assert jobs == []

    def test_queue_status(self, orch, dataset_file):
        with patch("training.finetune_orchestrator._DATASETS_DIR", dataset_file.parent):
            orch.submit("qa_evaluator")
            orch.submit("qa_evaluator")
        status = orch.queue_status()
        assert status["jobs"]["pending"] == 2
        assert status["total"] == 2

    def test_cancel_job(self, orch, dataset_file):
        with patch("training.finetune_orchestrator._DATASETS_DIR", dataset_file.parent):
            job = orch.submit("qa_evaluator")
        orch.cancel_job(job.job_id)
        updated = orch.get_job(job.job_id)
        assert updated["status"] == JobStatus.CANCELLED

    def test_cancel_unknown_job_raises(self, orch):
        with pytest.raises(KeyError):
            orch.cancel_job("notexist")

    def test_run_next_empty_queue(self, orch):
        result = orch.run_next()
        assert result is None

    def test_generate_training_script(self, orch, dataset_file):
        job = FinetuneJob(
            job_id="test1", model_type="qa_evaluator", base_model="Qwen/Qwen2.5-0.5B-Instruct",
            dataset_path=str(dataset_file), output_dir="/tmp/out",
        )
        script = orch.generate_training_script(job)
        assert "unsloth" in script
        assert "SFTTrainer" in script
        assert "qa_evaluator" in script
        assert str(dataset_file).replace('\\', '/') in script.replace('\\', '/')

    def test_default_config_small_model(self, orch):
        cfg = orch._default_config("Qwen/Qwen2.5-0.5B-Instruct")
        assert cfg.lora_r <= 16
        assert cfg.batch_size >= 4

    def test_default_config_large_model(self, orch):
        cfg = orch._default_config("Qwen/Qwen2.5-7B-Instruct")
        assert cfg.lora_r >= 16
        assert cfg.batch_size <= 4

    def test_jobs_persist_and_reload(self, tmp_path, dataset_file):
        jobs_path = tmp_path / "jobs.jsonl"
        with patch("training.finetune_orchestrator._JOBS_PATH", jobs_path):
            with patch("training.finetune_orchestrator._DATASETS_DIR", dataset_file.parent):
                orch1 = FinetuneOrchestrator()
                job = orch1.submit("qa_evaluator")
                job_id = job.job_id

            # Reload
            with patch("training.finetune_orchestrator._JOBS_PATH", jobs_path):
                with patch("training.finetune_orchestrator._DATASETS_DIR", dataset_file.parent):
                    orch2 = FinetuneOrchestrator()
                    loaded = orch2.get_job(job_id)
                    assert loaded is not None
                    assert loaded["job_id"] == job_id

    def test_singleton(self):
        o1 = get_finetune_orchestrator()
        o2 = get_finetune_orchestrator()
        assert o1 is o2
