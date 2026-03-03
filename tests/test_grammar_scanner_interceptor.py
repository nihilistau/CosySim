"""Tests for GrammarScannerInterceptor."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.agents.grammar_scanner_interceptor import GrammarScannerInterceptor


def _make_ctx(response: str) -> dict:
    return {"response": response, "reply": response}


@pytest.fixture()
def interceptor() -> GrammarScannerInterceptor:
    return GrammarScannerInterceptor()


@patch("training.data_collector.DataCollector")
def test_clean_response_no_issues(mock_dc_class, interceptor):
    """A normal sentence should trigger no issues and not call DataCollector."""
    ctx = _make_ctx("Hello, how are you today?")
    with patch("training.data_collector.get_data_collector") as mock_get:
        interceptor.post_call(ctx)
        mock_get.assert_not_called()


@patch("training.data_collector.get_data_collector")
def test_truncated_response(mock_get_dc, interceptor):
    """A long response without terminal punctuation should flag 'truncated'."""
    mock_collector = MagicMock()
    mock_get_dc.return_value = mock_collector

    # 60-char string with no sentence-ending punctuation
    response = "This is a really long response that just keeps going without end" + " x" * 5
    ctx = _make_ctx(response)
    interceptor.post_call(ctx)

    mock_get_dc.assert_called_once()
    calls = mock_collector.collect_grammar_error.call_args_list
    issue_types = [c.kwargs.get("error_type") or c.args[2] for c in calls]
    assert "truncated" in issue_types


@patch("training.data_collector.get_data_collector")
def test_repeated_phrase_detected(mock_get_dc, interceptor):
    """A phrase repeated 3 times should flag 'repeated_phrase'."""
    mock_collector = MagicMock()
    mock_get_dc.return_value = mock_collector

    phrase = "the quick brown fox jumps"
    response = f"{phrase} over something. {phrase} over other things. {phrase} again today."
    ctx = _make_ctx(response)
    interceptor.post_call(ctx)

    mock_get_dc.assert_called_once()
    calls = mock_collector.collect_grammar_error.call_args_list
    issue_types = [c.kwargs.get("error_type") or c.args[2] for c in calls]
    assert "repeated_phrase" in issue_types


@patch("training.data_collector.get_data_collector")
def test_empty_response(mock_get_dc, interceptor):
    """An empty string should flag 'empty_response'."""
    mock_collector = MagicMock()
    mock_get_dc.return_value = mock_collector

    ctx = _make_ctx("")
    interceptor.post_call(ctx)

    mock_get_dc.assert_called_once()
    calls = mock_collector.collect_grammar_error.call_args_list
    issue_types = [c.kwargs.get("error_type") or c.args[2] for c in calls]
    assert "empty_response" in issue_types


@patch("training.data_collector.get_data_collector")
def test_broken_symbols(mock_get_dc, interceptor):
    """A response containing □ characters should flag 'broken_symbols'."""
    mock_collector = MagicMock()
    mock_get_dc.return_value = mock_collector

    ctx = _make_ctx("The output was □□□ corrupted here.")
    interceptor.post_call(ctx)

    mock_get_dc.assert_called_once()
    calls = mock_collector.collect_grammar_error.call_args_list
    issue_types = [c.kwargs.get("error_type") or c.args[2] for c in calls]
    assert "broken_symbols" in issue_types


@patch("training.data_collector.get_data_collector")
def test_all_caps_spam(mock_get_dc, interceptor):
    """A response that is mostly uppercase should flag 'all_caps_spam'."""
    mock_collector = MagicMock()
    mock_get_dc.return_value = mock_collector

    ctx = _make_ctx("THIS IS COMPLETELY IN ALL CAPS AND IT IS VERY LONG TEXT.")
    interceptor.post_call(ctx)

    mock_get_dc.assert_called_once()
    calls = mock_collector.collect_grammar_error.call_args_list
    issue_types = [c.kwargs.get("error_type") or c.args[2] for c in calls]
    assert "all_caps_spam" in issue_types
