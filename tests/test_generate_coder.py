"""Tests for training/datasets/generate_coder.py."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest


def test_scan_codebase_returns_examples() -> None:
    """scan_codebase should return a non-empty list of examples."""
    from training.datasets.generate_coder import scan_codebase

    # This actually scans real code, should find examples
    examples = scan_codebase(max_files=10)
    # Should find at least some functions with docstrings
    assert isinstance(examples, list)


def test_bug_injection_creates_valid_bug() -> None:
    """Bug injection should create a modified version of the code."""
    from training.datasets.generate_coder import generate_bug_fix_examples

    examples = generate_bug_fix_examples()
    # Should find at least some functions to inject bugs into
    assert isinstance(examples, list)
    for ex in examples[:5]:
        assert "instruction" in ex
        assert "input" in ex
        assert "output" in ex
        assert ex["strategy"] == "bug_fix"
        assert "Fix the bug" in ex["instruction"]


def test_convention_examples_generated() -> None:
    """Convention examples should include at least 10 examples."""
    from training.datasets.generate_coder import generate_convention_examples

    examples = generate_convention_examples()
    assert len(examples) >= 10
    for ex in examples[:3]:
        assert ex["strategy"] == "convention"
        assert len(ex["output"]) >= 10


def test_skill_scaffolding_examples_found() -> None:
    """Skill scaffold strategy should find @skill decorated functions."""
    from training.datasets.generate_coder import generate_skill_scaffold_examples

    examples = generate_skill_scaffold_examples()
    assert isinstance(examples, list)
    for ex in examples[:5]:
        assert ex["strategy"] == "skill_scaffold"
        assert "@skill" in ex["output"]


def test_save_dataset_creates_jsonl(tmp_path: Path) -> None:
    """save_dataset should create a valid JSONL file."""
    from training.datasets.generate_coder import save_dataset

    examples = [
        {
            "instruction": "Complete this function",
            "input": "def foo():",
            "output": "def foo():\n    return 42",
            "model_type": "coder",
            "strategy": "fim_completion",
            "source_file": "test.py",
            "convention_type": None,
        }
    ]

    out_path = tmp_path / "test_coder.jsonl"
    result = save_dataset(examples, output_path=out_path)

    assert result == out_path
    assert out_path.exists()

    lines = out_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["model_type"] == "coder"
    assert record["strategy"] == "fim_completion"


def test_deduplication_works() -> None:
    """Deduplication should remove examples with identical (instruction[:50]+input[:100]) keys."""
    from training.datasets.generate_coder import _filter_and_dedup

    examples: List[Dict[str, Any]] = [
        {
            "instruction": "A" * 60,
            "input": "B" * 110,
            "output": "C" * 60,
            "strategy": "test",
            "source_file": "",
            "model_type": "coder",
            "convention_type": None,
        },
        {
            "instruction": "A" * 60,
            "input": "B" * 110,
            "output": "D" * 60,
            "strategy": "test",
            "source_file": "",
            "model_type": "coder",
            "convention_type": None,
        },  # duplicate key
        {
            "instruction": "X" * 60,
            "input": "Y" * 110,
            "output": "Z" * 60,
            "strategy": "test",
            "source_file": "",
            "model_type": "coder",
            "convention_type": None,
        },
    ]

    result = _filter_and_dedup(examples)
    assert len(result) == 2  # deduplicated


def test_main_runs_without_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() should run without raising exceptions."""
    monkeypatch.chdir(tmp_path)

    # Create minimal directory structure
    (tmp_path / "training" / "datasets").mkdir(parents=True)
    (tmp_path / "engine").mkdir(parents=True)

    # Mock Nexus to avoid real calls
    with patch("training.datasets.generate_coder.generate_nexus_qa_examples", return_value=[]):
        from training.datasets.generate_coder import main
        main()  # Should not raise

    # Should have created the dataset file
    dataset = tmp_path / "training" / "datasets" / "coder_train.jsonl"
    assert dataset.exists()
