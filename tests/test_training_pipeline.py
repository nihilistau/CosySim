"""Tests for training pipeline: finetune_local, auto_train, prepare_from_live."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════
# finetune_local tests
# ═══════════════════════════════════════════════════════════════


class TestFinetuneLocal:
    def test_import(self):
        from training.finetune_local import (
            finetune, evaluate_model, check_dependencies,
            _load_dataset, _format_prompt,
        )
        assert callable(finetune)
        assert callable(check_dependencies)

    def test_check_dependencies(self):
        from training.finetune_local import check_dependencies
        deps = check_dependencies()
        assert "torch" in deps
        assert "transformers" in deps
        # unsloth may or may not be installed
        assert isinstance(deps, dict)

    def test_format_prompt(self):
        from training.finetune_local import _format_prompt
        example = {"instruction": "What is 2+2?", "output": "4"}
        result = _format_prompt(example)
        assert "<start_of_turn>user" in result
        assert "What is 2+2?" in result
        assert "<start_of_turn>model" in result
        assert "4" in result

    def test_load_dataset_from_train_file(self):
        from training.finetune_local import _load_dataset, DATASETS_DIR
        # tag_extraction_train.jsonl should exist from generate_datasets
        examples = _load_dataset("tag_extraction")
        assert isinstance(examples, list)
        # Should have loaded from the train file
        assert len(examples) > 0

    def test_load_dataset_nonexistent(self):
        from training.finetune_local import _load_dataset
        examples = _load_dataset("nonexistent_dataset_xyz")
        assert examples == []

    def test_finetune_missing_deps(self):
        from training.finetune_local import finetune
        # Without unsloth installed, should raise ImportError
        with patch("training.finetune_local.check_dependencies",
                    return_value={"unsloth": False, "transformers": True, "peft": True,
                                  "trl": True, "torch": True, "datasets": True}):
            with pytest.raises(ImportError, match="Missing training dependencies"):
                finetune(dataset_name="tag_extraction")

    def test_finetune_no_data(self):
        from training.finetune_local import finetune
        with patch("training.finetune_local._load_dataset", return_value=[]):
            with patch("training.finetune_local.check_dependencies",
                        return_value={k: True for k in ["unsloth", "transformers", "peft", "trl", "torch", "datasets"]}):
                with pytest.raises(ValueError, match="No training data"):
                    finetune(dataset_name="empty_dataset")

    def test_all_datasets_constant(self):
        from training.finetune_local import ALL_DATASETS
        assert len(ALL_DATASETS) == 5
        assert "tag_extraction" in ALL_DATASETS


# ═══════════════════════════════════════════════════════════════
# auto_train tests
# ═══════════════════════════════════════════════════════════════


class TestAutoTrain:
    def test_import(self):
        from training.auto_train import (
            check_and_train, check_candidates, get_status,
            daemon_loop, DEFAULT_THRESHOLDS,
        )
        assert callable(check_and_train)
        assert callable(get_status)

    def test_default_thresholds(self):
        from training.auto_train import DEFAULT_THRESHOLDS
        assert "tag_extraction" in DEFAULT_THRESHOLDS
        assert DEFAULT_THRESHOLDS["tag_extraction"] == 100

    def test_load_save_state(self, tmp_path):
        from training.auto_train import _load_state, _save_state, STATE_FILE

        # Save original state file if it exists
        original = STATE_FILE.read_text() if STATE_FILE.exists() else None

        try:
            state = {"last_check": time.time(), "last_train": {}, "history": []}
            _save_state(state)
            loaded = _load_state()
            assert abs(loaded["last_check"] - state["last_check"]) < 1
        finally:
            if original:
                STATE_FILE.write_text(original)
            elif STATE_FILE.exists():
                STATE_FILE.unlink()

    def test_check_candidates_empty(self):
        from training.auto_train import check_candidates
        mock_db = MagicMock()
        mock_db.get_training_candidates.return_value = []
        with patch("training.auto_train._get_metrics_db", return_value=mock_db):
            counts = check_candidates()
            assert all(v == 0 for v in counts.values())

    def test_check_and_train_below_threshold(self):
        from training.auto_train import check_and_train, STATE_FILE

        original = STATE_FILE.read_text() if STATE_FILE.exists() else None

        mock_db = MagicMock()
        mock_db.get_training_candidates.return_value = []

        try:
            with patch("training.auto_train._get_metrics_db", return_value=mock_db):
                results = check_and_train()
                assert results == {}  # nothing to train
        finally:
            if original:
                STATE_FILE.write_text(original)
            elif STATE_FILE.exists():
                STATE_FILE.unlink()

    def test_check_and_train_dry_run(self):
        from training.auto_train import check_and_train, STATE_FILE

        original = STATE_FILE.read_text() if STATE_FILE.exists() else None

        mock_db = MagicMock()
        # Return 200 candidates for tag_extraction
        mock_db.get_training_candidates.return_value = [{"id": i} for i in range(200)]

        try:
            with patch("training.auto_train._get_metrics_db", return_value=mock_db):
                results = check_and_train(
                    thresholds={"tag_extraction": 50},
                    dry_run=True,
                )
                assert "tag_extraction" in results
                assert results["tag_extraction"]["action"] == "would_train"
        finally:
            if original:
                STATE_FILE.write_text(original)
            elif STATE_FILE.exists():
                STATE_FILE.unlink()

    def test_get_status_structure(self):
        from training.auto_train import get_status, STATE_FILE

        original = STATE_FILE.read_text() if STATE_FILE.exists() else None

        mock_db = MagicMock()
        mock_db.get_training_candidates.return_value = []

        try:
            with patch("training.auto_train._get_metrics_db", return_value=mock_db):
                status = get_status()
                assert "last_check" in status
                assert "thresholds" in status
                assert "candidate_counts" in status
        finally:
            if original:
                STATE_FILE.write_text(original)
            elif STATE_FILE.exists():
                STATE_FILE.unlink()
