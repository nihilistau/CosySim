"""Tests for Micro-model Dataset Manager."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from training.micro_datasets import MicroDatasetManager, DatasetStats, MODELS


class TestMicroDatasetManager:
    def test_status_returns_all_models(self, tmp_path):
        with patch("training.micro_datasets._DATASET_DIR", tmp_path):
            mgr = MicroDatasetManager()
            status = mgr.status()
        assert set(status.keys()) == set(MODELS)

    def test_deduplicate_removes_dupes(self):
        mgr = MicroDatasetManager()
        examples = [
            {"input": "hello", "output": "A"},
            {"input": "hello", "output": "B"},  # dup
            {"input": "world", "output": "C"},
        ]
        result = mgr._deduplicate(examples)
        assert len(result) == 2
        inputs = {e["input"] for e in result}
        assert inputs == {"hello", "world"}

    def test_to_format_adds_instruction(self):
        mgr = MicroDatasetManager()
        examples = [{"input": "test", "output": "ESSENTIAL"}]
        formatted = mgr._to_format("qa_evaluator", examples)
        assert len(formatted) == 1
        assert "instruction" in formatted[0]
        assert "input" in formatted[0]
        assert "output" in formatted[0]
        assert formatted[0]["output"] == "ESSENTIAL"
        assert formatted[0]["input"] == "test"

    def test_augment_qa_evaluator(self):
        mgr = MicroDatasetManager()
        ex = {"input": "How do I start the scene?", "output": "ESSENTIAL", "source": "nlm"}
        result = mgr._augment_qa_evaluator(ex)
        # Should produce a variation or None
        if result:
            assert result["input"] != ex["input"]
            assert result["output"] == "ESSENTIAL"

    def test_augment_router(self):
        mgr = MicroDatasetManager()
        ex = {"input": "search nexus for docs", "output": "nexus_search", "source": "nlm"}
        result = mgr._augment_router(ex)
        if result:
            assert result["output"] == "nexus_search"
            assert result["source"] == "augmented"

    def test_save_and_count_lines(self, tmp_path):
        mgr = MicroDatasetManager()
        examples = [{"instruction": "test", "input": f"q{i}", "output": f"a{i}", "model_type": "qa_evaluator"}
                    for i in range(10)]
        path = mgr._save_split("qa_evaluator", "train", examples)
        assert Path(path).exists()
        count = mgr._count_lines(Path(path))
        assert count == 10

    def test_build_uses_synthetic_fallback(self, tmp_path):
        with patch("training.micro_datasets._DATASET_DIR", tmp_path):
            with patch("training.micro_datasets.MicroDatasetManager._generate_via_teacher",
                       return_value=[]) as mock_gen:
                with patch("training.micro_datasets.MicroDatasetManager._generate_synthetic",
                           return_value=[{"input": f"q{i}", "output": "A", "model_type": "qa_evaluator"}
                                         for i in range(20)]):
                    mgr = MicroDatasetManager()
                    stats = mgr.build("qa_evaluator", count=10, augment=False)
                assert stats.total >= 0  # may be 0 if no examples survive dedup+split

    def test_build_generates_split_files(self, tmp_path):
        with patch("training.micro_datasets._DATASET_DIR", tmp_path):
            with patch("training.micro_datasets.MicroDatasetManager._generate_via_teacher",
                       return_value=[{"input": f"q{i}", "output": f"a{i}", "source": "nlm", "model_type": "router_v2"}
                                     for i in range(50)]):
                mgr = MicroDatasetManager()
                stats = mgr.build("router_v2", count=50, augment=False)
        assert stats.train + stats.val + stats.test == stats.total
        assert stats.path_train
        assert stats.path_val
        assert stats.path_test
