"""Tests for the NLM Teacher Pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.teacher_pipeline import (
    TeacherPipeline,
    TrainingExample,
    MICRO_MODEL_TYPES,
    get_teacher_pipeline,
)


class TestTrainingExample:
    def test_to_dict_roundtrip(self):
        ex = TrainingExample(input="Q?", output="A", model_type="qa_evaluator")
        d = ex.to_dict()
        assert d["input"] == "Q?"
        assert d["output"] == "A"
        assert d["model_type"] == "qa_evaluator"

    def test_to_alpaca_format(self):
        ex = TrainingExample(
            input="classify this", output="ESSENTIAL", model_type="qa_evaluator",
            metadata={"instruction": "Rate the pair"}
        )
        alpaca = ex.to_alpaca()
        assert alpaca["instruction"] == "Rate the pair"
        assert alpaca["output"] == "ESSENTIAL"

    def test_to_sharegpt_format(self):
        ex = TrainingExample(input="Hello", output="Hi", model_type="router_v2")
        sharegpt = ex.to_sharegpt()
        assert sharegpt["conversations"][0]["from"] == "human"
        assert sharegpt["conversations"][1]["from"] == "gpt"
        assert sharegpt["conversations"][1]["value"] == "Hi"


class TestTeacherPipeline:
    def test_invalid_model_type_raises(self):
        pipeline = TeacherPipeline()
        with pytest.raises(ValueError, match="Unknown model_type"):
            pipeline.generate_dataset("not_a_real_model")

    def test_all_model_types_valid(self):
        pipeline = TeacherPipeline()
        for model_type in MICRO_MODEL_TYPES:
            # Should not raise on submit — will fall to synthetic fallback
            result = pipeline.generate_dataset(model_type, count=5, use_existing_notebook=False)
            assert result.model_type == model_type
            assert result.count_generated > 0

    def test_synthetic_fallback_generates_examples(self):
        pipeline = TeacherPipeline()
        examples = pipeline._generate_synthetic_fallback("qa_evaluator", 10)
        assert len(examples) == 10
        for ex in examples:
            assert ex.input
            assert ex.output
            assert ex.model_type == "qa_evaluator"

    def test_parse_csv_output(self):
        pipeline = TeacherPipeline()
        csv_text = "question,answer\nHow does Nexus work?,ESSENTIAL\nWhat is 2+2?,SKIP\n"
        examples = pipeline._parse_csv("qa_evaluator", csv_text)
        assert len(examples) == 2
        assert examples[0].input == "How does Nexus work?"
        assert examples[0].output == "ESSENTIAL"

    def test_parse_jsonl_output(self):
        pipeline = TeacherPipeline()
        lines = '\n'.join([
            json.dumps({"input": "Hello?", "output": "nexus_ask"}),
            json.dumps({"input": "Start scene", "output": "scene_control"}),
        ])
        examples = pipeline._parse_jsonl("router_v2", lines)
        assert len(examples) == 2
        assert examples[0].input == "Hello?"

    def test_save_and_load_dataset(self, tmp_path):
        pipeline = TeacherPipeline()
        with patch("engine.nexus.teacher_pipeline._DATASET_DIR", tmp_path):
            examples = [
                TrainingExample(input=f"Q{i}", output=f"A{i}", model_type="qa_evaluator")
                for i in range(5)
            ]
            path = pipeline._save_dataset("qa_evaluator", examples)
            assert Path(path).exists()
            loaded = pipeline.load_dataset("qa_evaluator")
            assert len(loaded) == 5

    def test_get_dataset_stats(self, tmp_path):
        with patch("engine.nexus.teacher_pipeline._DATASET_DIR", tmp_path):
            pipeline = TeacherPipeline()
            stats = pipeline.get_dataset_stats()
            assert set(stats.keys()) == set(MICRO_MODEL_TYPES)
            for v in stats.values():
                assert v["exists"] is False
                assert v["examples"] == 0

    def test_singleton(self):
        p1 = get_teacher_pipeline()
        p2 = get_teacher_pipeline()
        assert p1 is p2


class TestTeacherPipelineNlmUnavailable:
    """Test that pipeline falls back gracefully when NLM is unavailable."""

    def test_generate_uses_synthetic_when_nlm_fails(self):
        pipeline = TeacherPipeline()
        with patch.object(pipeline, "_get_or_create_notebook", side_effect=RuntimeError("NLM down")):
            result = pipeline.generate_dataset("router_v2", count=5)
        assert result.count_generated > 0
        assert len(result.errors) > 0
