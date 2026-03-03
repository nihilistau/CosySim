"""Tests for coder_skills skill pack."""
from __future__ import annotations

import pytest
from unittest.mock import patch


def test_coder_scaffold_skill_returns_valid_python() -> None:
    """coder_scaffold_skill should return valid Python @skill code."""
    from engine.skills.builtin.coder_skills import coder_scaffold_skill

    result = coder_scaffold_skill("my_skill", "Do something useful", pack="test", category="GAME")

    assert "@skill(" in result
    assert "def my_skill(" in result
    assert 'pack="test"' in result
    assert 'category="GAME"' in result
    assert "-> str:" in result


def test_coder_review_catches_relative_import() -> None:
    """coder_review should detect relative imports."""
    from engine.skills.builtin.coder_skills import coder_review

    code = "from .config import get_config\n\ndef foo() -> str:\n    return 'hi'"
    result = coder_review(code)

    assert "relative import" in result.lower()


def test_coder_review_catches_print_statement() -> None:
    """coder_review should detect print() calls."""
    from engine.skills.builtin.coder_skills import coder_review

    code = "def foo() -> None:\n    print('hello')\n"
    result = coder_review(code)

    assert "print(" in result


def test_coder_review_passes_clean_code() -> None:
    """coder_review should pass clean code."""
    from engine.skills.builtin.coder_skills import coder_review

    code = (
        "import logging\n"
        "from engine.config import get_config\n\n"
        "logger = logging.getLogger(__name__)\n\n"
        "def process(data: dict) -> dict:\n"
        '    """Process data.\n\n    Args:\n        data: Input data.\n\n    Returns:\n        Processed data.\n    """\n'
        "    return data\n"
    )
    result = coder_review(code)

    assert result == "OK — no violations found"


def test_coder_status_returns_string() -> None:
    """coder_status should always return a string."""
    from engine.skills.builtin.coder_skills import coder_status

    with patch("training.coder_pipeline.get_coder_pipeline", side_effect=ImportError):
        result = coder_status()

    assert isinstance(result, str)
    assert len(result) > 0


def test_coder_rebuild_dataset_returns_string() -> None:
    """coder_rebuild_dataset should always return a string."""
    from engine.skills.builtin.coder_skills import coder_rebuild_dataset

    with patch("training.coder_pipeline.get_coder_pipeline", side_effect=ImportError):
        result = coder_rebuild_dataset()

    assert isinstance(result, str)
    assert len(result) > 0
