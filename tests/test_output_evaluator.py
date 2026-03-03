"""Tests for engine.agents.output_evaluator."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.agents.output_evaluator import OutputEvaluator, get_output_evaluator


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def evaluator() -> OutputEvaluator:
    """Return a fresh OutputEvaluator instance (not the singleton)."""
    return OutputEvaluator()


# ── score() tests ─────────────────────────────────────────────────────


def test_perfect_score(evaluator: OutputEvaluator) -> None:
    """Well-formed, complete sentence with varied vocabulary scores 1.0."""
    response = "The quick brown fox jumped over the lazy sleeping dog."
    score = evaluator.score(response, {})
    assert score == 1.0


def test_empty_response(evaluator: OutputEvaluator) -> None:
    """Empty string yields 0.0 — no checks can pass."""
    assert evaluator.score("", {}) == 0.0


def test_low_score_truncated(evaluator: OutputEvaluator) -> None:
    """A short response with truncation punctuation scores below 0.4.

    Fails: length_ok (3 < 10), sentence_complete (ends ','), no_truncation
    (comma), coherent (no spaces).  Only no_repetition passes → score = 0.2.
    """
    response = "ok,"
    score = evaluator.score(response, {})
    assert score < 0.4


def test_repetition_detected(evaluator: OutputEvaluator) -> None:
    """Responses with a 4+ word phrase repeated three times score lower."""
    phrase = "this is a repeated phrase"
    # Repeat the phrase three times to trigger the repetition check
    response = f"{phrase} {phrase} {phrase} and some extra padding here."
    score_repeated = evaluator.score(response, {})
    score_clean = evaluator.score("The weather today is sunny and warm outside.", {})
    assert score_repeated < score_clean


# ── evaluate_and_store() tests ────────────────────────────────────────


def test_evaluate_and_store_calls_nexus(evaluator: OutputEvaluator) -> None:
    """Low-quality response triggers Nexus storage; DataCollector is also called."""
    low_quality_response = "Bad,"  # truncated, very short → score < 0.4

    mock_nexus_client = MagicMock()
    mock_data_collector = MagicMock()

    with (
        patch("engine.agents.output_evaluator.OutputEvaluator._store_in_nexus") as mock_store,
        patch(
            "engine.agents.output_evaluator.OutputEvaluator._collect_training_signal"
        ) as mock_collect,
    ):
        score = evaluator.evaluate_and_store(
            low_quality_response,
            {"user_message": "Tell me something."},
            agent_name="aria",
        )

    assert score < 0.4
    mock_store.assert_called_once()
    mock_collect.assert_called_once()

    # Verify arguments passed to Nexus store
    call_args = mock_store.call_args
    assert call_args[0][2] == "aria"  # agent_name positional arg
    assert call_args[0][3] == score   # quality positional arg


def test_evaluate_and_store_high_quality_skips_nexus(evaluator: OutputEvaluator) -> None:
    """High-quality responses do NOT trigger Nexus storage."""
    good_response = "The simulation is running smoothly and all systems are nominal."

    with (
        patch("engine.agents.output_evaluator.OutputEvaluator._store_in_nexus") as mock_store,
        patch("engine.agents.output_evaluator.OutputEvaluator._collect_training_signal"),
    ):
        score = evaluator.evaluate_and_store(good_response, {}, agent_name="viktor")

    assert score >= 0.4
    mock_store.assert_not_called()


# ── Singleton test ────────────────────────────────────────────────────


def test_singleton_returns_same_instance() -> None:
    """get_output_evaluator() returns the same instance on repeated calls."""
    a = get_output_evaluator()
    b = get_output_evaluator()
    assert a is b
