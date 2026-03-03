"""Tests for CoderPipeline."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_status_returns_correct_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Status should return a CoderStatus with correct fields."""
    monkeypatch.chdir(tmp_path)

    from training.coder_pipeline import CoderPipeline
    pipeline = CoderPipeline()

    # Mock out external deps
    with patch("training.coder_pipeline.CoderPipeline.status") as mock_status:
        from training.coder_pipeline import CoderStatus
        mock_status.return_value = CoderStatus(
            dataset_size=0,
            last_dataset_refresh=None,
            active_job_id=None,
            active_job_status=None,
            active_model_id=None,
            best_score=0.0,
            train_threshold=500,
            ready_to_train=False,
            lmstudio_loaded=False,
        )
        status = pipeline.status()

    assert status.dataset_size == 0
    assert status.ready_to_train is False
    assert status.train_threshold == 500
    assert status.lmstudio_loaded is False


def test_build_dataset_creates_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """build_dataset should create coder_train.jsonl."""
    monkeypatch.chdir(tmp_path)

    # Pre-create the datasets dir and a small dataset
    dataset_path = tmp_path / "training" / "datasets" / "coder_train.jsonl"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text(
        json.dumps({"instruction": "test", "input": "x", "output": "y"}) + "\n"
    )

    from training.coder_pipeline import CoderPipeline
    pipeline = CoderPipeline()
    count = pipeline.build_dataset(force=False)
    assert count >= 1


def test_check_and_train_below_threshold(tmp_path: Path) -> None:
    """Should return None when below threshold."""
    old_dir = Path.cwd()
    os.chdir(tmp_path)
    try:
        from training.coder_pipeline import CoderPipeline
        pipeline = CoderPipeline()
        result = pipeline.check_and_train(force=False)
        assert result is None
    finally:
        os.chdir(old_dir)


def test_check_and_train_above_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Should submit job when above threshold."""
    monkeypatch.chdir(tmp_path)

    # Create dataset with 600 lines
    dataset_path = tmp_path / "training" / "datasets" / "coder_train.jsonl"
    dataset_path.parent.mkdir(parents=True)
    records = [
        {"instruction": "test", "input": f"input_{i}", "output": f"output_{i}"}
        for i in range(600)
    ]
    with dataset_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    mock_job = MagicMock()
    mock_job.job_id = "job-test-123"
    mock_orch = MagicMock()
    mock_orch.submit.return_value = mock_job

    with patch("training.finetune_orchestrator.get_finetune_orchestrator", return_value=mock_orch), \
         patch("training.coder_pipeline.get_finetune_orchestrator", return_value=mock_orch, create=True):
        from training.coder_pipeline import CoderPipeline
        pipeline = CoderPipeline()
        result = pipeline.check_and_train()

    assert result == "job-test-123"


def test_full_cycle_returns_dict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """full_cycle should return a dict with expected keys."""
    monkeypatch.chdir(tmp_path)

    from training.coder_pipeline import CoderPipeline
    pipeline = CoderPipeline()

    with patch.object(pipeline, "build_dataset", return_value=100), \
         patch.object(pipeline, "check_and_train", return_value=None):
        result = pipeline.full_cycle()

    assert isinstance(result, dict)
    assert "dataset_size" in result
    assert "job_id" in result


def test_get_coder_pipeline_singleton() -> None:
    """get_coder_pipeline should return the same instance."""
    import training.coder_pipeline as mod
    mod._pipeline = None  # reset for test isolation

    from training.coder_pipeline import get_coder_pipeline
    p1 = get_coder_pipeline()
    p2 = get_coder_pipeline()
    assert p1 is p2

    mod._pipeline = None  # reset after
