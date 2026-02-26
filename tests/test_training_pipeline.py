"""Tests for training pipeline: finetune_local, auto_train, prepare_from_live."""

import json
import sys
import tempfile
import time
import unittest
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
        # With HF fallback, missing unsloth alone doesn't raise.
        # Mock both backends unavailable to trigger ImportError.
        with patch("training.finetune_local._has_unsloth", return_value=False), \
             patch("training.finetune_local._finetune_hf",
                   side_effect=ImportError("Missing transformers")):
            with pytest.raises(ImportError):
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


# ═══════════════════════════════════════════════════════════════
# generate_datasets tests
# ═══════════════════════════════════════════════════════════════


class TestGenerateDatasets(unittest.TestCase):
    """Tests for training.generate_datasets module."""

    def test_generates_all_datasets(self):
        """Run all generators, verify 10 JSONL files created in a temp dir."""
        import random
        from training.generate_datasets import GENERATORS, write_jsonl

        random.seed(42)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            for name, (gen_fn, count) in GENERATORS.items():
                data = gen_fn(count)
                random.shuffle(data)
                split = int(len(data) * 0.9)
                write_jsonl(data[:split], out_dir / f"{name}_train.jsonl")
                write_jsonl(data[split:], out_dir / f"{name}_val.jsonl")
            self.assertEqual(len(list(out_dir.glob("*.jsonl"))), 10)

    def test_jsonl_format(self):
        """Each line must be valid JSON with 'instruction' and 'output' keys."""
        from training.generate_datasets import generate_tag_extraction, write_jsonl

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            write_jsonl(generate_tag_extraction(10), path)
            for line in path.read_text(encoding="utf-8").strip().splitlines():
                row = json.loads(line)
                self.assertIn("instruction", row)
                self.assertIn("output", row)

    def test_dataset_counts(self):
        """Each generator must produce exactly its default count."""
        from training.generate_datasets import GENERATORS

        expected = {
            "tag_extraction": 800, "tool_routing": 600,
            "priority_classify": 400, "decision_classify": 400,
            "response_validate": 400,
        }
        for name, (gen_fn, default_count) in GENERATORS.items():
            self.assertEqual(default_count, expected[name], f"{name} default mismatch")
            self.assertEqual(len(gen_fn(default_count)), expected[name])


# ═══════════════════════════════════════════════════════════════
# merge_adapters tests
# ═══════════════════════════════════════════════════════════════


class TestMergeAdapters(unittest.TestCase):
    """Tests for training.merge_adapters module."""

    def test_check_dependencies(self):
        """check_dependencies returns a dict of {pkg: bool}."""
        from training.merge_adapters import check_dependencies

        deps = check_dependencies()
        self.assertIsInstance(deps, dict)
        for pkg in ("unsloth", "transformers", "peft", "torch"):
            self.assertIn(pkg, deps)
            self.assertIsInstance(deps[pkg], bool)

    def test_merge_requires_adapters(self):
        """Empty adapter list raises ValueError."""
        from training.merge_adapters import merge_adapters

        with self.assertRaises(ValueError):
            merge_adapters([])


# ═══════════════════════════════════════════════════════════════
# training_skills tests
# ═══════════════════════════════════════════════════════════════


class TestTrainingSkills(unittest.TestCase):
    """Tests for engine.skills.builtin.training_skills."""

    def test_list_trained_models(self):
        """list_trained_models returns valid JSON."""
        from engine.skills.builtin.training_skills import list_trained_models

        result = list_trained_models()
        parsed = json.loads(result)
        self.assertIsInstance(parsed, (list, dict))

    def test_get_training_status_no_jobs(self):
        """Empty job_id with no recorded jobs returns message JSON."""
        from engine.skills.builtin.training_skills import (
            get_training_status, _training_jobs,
        )

        _training_jobs.clear()
        result = get_training_status("")
        parsed = json.loads(result)
        self.assertIn("message", parsed)

    def test_export_training_data_no_db(self):
        """Graceful error when the metrics DB module is unavailable."""
        from engine.skills.builtin.training_skills import export_training_data

        with patch.dict(sys.modules, {"training.prepare_from_live": None}):
            result = export_training_data()
            parsed = json.loads(result)
            self.assertIn("error", parsed)


# ═══════════════════════════════════════════════════════════════
# notebooklm_skills tests
# ═══════════════════════════════════════════════════════════════


class TestNotebookLMSkills(unittest.TestCase):
    """Tests for engine.skills.builtin.notebooklm_skills."""

    @patch("engine.skills.builtin.notebooklm_skills._get",
           side_effect=Exception("Connection refused"))
    def test_list_notebooks_server_down(self, _mock):
        """Returns JSON error when the proxy server is unreachable."""
        from engine.skills.builtin.notebooklm_skills import notebooklm_list_notebooks

        result = notebooklm_list_notebooks()
        parsed = json.loads(result)
        self.assertIn("error", parsed)

    @patch("engine.skills.builtin.notebooklm_skills._post",
           side_effect=Exception("Connection refused"))
    def test_ask_server_down(self, _mock):
        """Returns JSON error when asking with server down."""
        from engine.skills.builtin.notebooklm_skills import notebooklm_ask

        result = notebooklm_ask("test question")
        parsed = json.loads(result)
        self.assertIn("error", parsed)


# ═══════════════════════════════════════════════════════════════
# NotebookLMProxy tests
# ═══════════════════════════════════════════════════════════════


class TestNotebookLMProxy(unittest.TestCase):
    """Tests for engine.mcp.notebooklm_proxy.NotebookLMProxy."""

    def test_proxy_not_running(self):
        """Freshly created proxy reports not running."""
        from engine.mcp.notebooklm_proxy import NotebookLMProxy

        proxy = NotebookLMProxy({})
        self.assertFalse(proxy.is_running())

    def test_proxy_ask_not_running(self):
        """ask() returns error dict when process is not running."""
        from engine.mcp.notebooklm_proxy import NotebookLMProxy

        proxy = NotebookLMProxy({})
        result = proxy.ask("nb-1", "test question")
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
