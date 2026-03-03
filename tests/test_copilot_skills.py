"""Tests for the GitHub Copilot skill pack.

All GithubCopilotClient calls are mocked — no real HTTP requests made.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    """Return a MagicMock replacing GithubCopilotClient."""
    client = MagicMock()
    client.ask.return_value = "Mocked response"
    client.list_models.return_value = [
        {"id": "claude-sonnet-4.6", "vendor": "Anthropic"},
        {"id": "gpt-5.2-codex", "vendor": "OpenAI"},
        {"id": "gemini-3.1-pro-preview", "vendor": "Google"},
    ]
    client.create_thread.return_value = "thread-mock-001"
    client.send_message.return_value = ("Assistant reply", "msg-mock-001")
    return client


@pytest.fixture(autouse=True)
def patch_copilot_client(mock_client):
    """Patch get_copilot_client used inside skill functions."""
    with patch(
        "engine.skills.builtin.copilot_skills._client",
        return_value=mock_client,
    ):
        yield mock_client


# ──── copilot_ask ─────────────────────────────────────────────────────────────


class TestCopilotAsk:
    def test_returns_response(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_ask

        result = copilot_ask("What is the sky?")
        assert result == "Mocked response"
        mock_client.ask.assert_called_once_with("What is the sky?", model="claude-sonnet-4.6")

    def test_custom_model(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_ask

        copilot_ask("Hello", model="gpt-5.2-codex")
        mock_client.ask.assert_called_once_with("Hello", model="gpt-5.2-codex")

    def test_returns_error_string_on_exception(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_ask

        mock_client.ask.side_effect = RuntimeError("API down")
        result = copilot_ask("test")
        assert "Copilot error" in result
        assert "API down" in result


# ──── copilot_code ────────────────────────────────────────────────────────────


class TestCopilotCode:
    def test_default_model_is_codex(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_code

        copilot_code("sort a list")
        _, kwargs = mock_client.ask.call_args
        assert kwargs.get("model") == "gpt-5.2-codex"

    def test_prompt_includes_language(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_code

        copilot_code("http server", language="go")
        call_args = mock_client.ask.call_args[0][0]
        assert "go" in call_args.lower()

    def test_returns_error_on_exception(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_code

        mock_client.ask.side_effect = Exception("timeout")
        result = copilot_code("code")
        assert "error" in result.lower()


# ──── copilot_review ─────────────────────────────────────────────────────────


class TestCopilotReview:
    def test_includes_code_in_prompt(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_review

        copilot_review("def foo(): pass", language="python")
        prompt = mock_client.ask.call_args[0][0]
        assert "def foo(): pass" in prompt
        assert "python" in prompt.lower()

    def test_uses_sonnet(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_review

        copilot_review("x = 1")
        _, kwargs = mock_client.ask.call_args
        assert "sonnet" in kwargs.get("model", "")

    def test_returns_error_string_on_failure(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_review

        mock_client.ask.side_effect = ValueError("bad")
        result = copilot_review("code")
        assert "error" in result.lower()


# ──── copilot_fast ────────────────────────────────────────────────────────────


class TestCopilotFast:
    def test_uses_haiku(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_fast

        copilot_fast("quick question")
        _, kwargs = mock_client.ask.call_args
        assert "haiku" in kwargs.get("model", "")

    def test_returns_response(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_fast

        result = copilot_fast("Hi")
        assert result == "Mocked response"


# ──── copilot_smart ───────────────────────────────────────────────────────────


class TestCopilotSmart:
    def test_uses_opus(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_smart

        copilot_smart("hard problem")
        _, kwargs = mock_client.ask.call_args
        assert "opus" in kwargs.get("model", "")

    def test_returns_response(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_smart

        result = copilot_smart("Deep question")
        assert result == "Mocked response"


# ──── copilot_models ─────────────────────────────────────────────────────────


class TestCopilotModels:
    def test_returns_formatted_string(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_models

        result = copilot_models()
        assert "claude-sonnet-4.6" in result
        assert "gpt-5.2-codex" in result
        assert "3 total" in result

    def test_groups_by_vendor(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_models

        result = copilot_models()
        assert "Anthropic" in result
        assert "OpenAI" in result

    def test_returns_no_models_message(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_models

        mock_client.list_models.return_value = []
        result = copilot_models()
        assert "No models" in result

    def test_returns_error_on_exception(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_models

        mock_client.list_models.side_effect = RuntimeError("fail")
        result = copilot_models()
        assert "error" in result.lower()


# ──── copilot_thread ─────────────────────────────────────────────────────────


class TestCopilotThread:
    def test_creates_thread_and_sends_messages(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_thread

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "And again"},
        ]
        result = copilot_thread(messages)
        assert mock_client.create_thread.called
        assert mock_client.send_message.call_count == 2
        assert result == "Assistant reply"

    def test_skips_assistant_role_messages(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_thread

        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hey back"},  # should be skipped
            {"role": "user", "content": "Follow up"},
        ]
        copilot_thread(messages)
        # Only 2 user messages sent
        assert mock_client.send_message.call_count == 2

    def test_returns_empty_message_list(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_thread

        result = copilot_thread([])
        assert "No messages" in result

    def test_threads_parent_message_id(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_thread

        # first send returns ("reply1", "id-first"), second returns ("reply2", "id-second")
        mock_client.send_message.side_effect = [
            ("reply1", "id-first"),
            ("reply2", "id-second"),
        ]
        copilot_thread([
            {"role": "user", "content": "msg1"},
            {"role": "user", "content": "msg2"},
        ])
        second_call = mock_client.send_message.call_args_list[1]
        # send_message(thread_id, content, model=..., parent_message_id=...)
        kwargs = second_call.kwargs
        parent = kwargs.get("parent_message_id")
        assert parent == "id-first"

    def test_returns_error_on_exception(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_thread

        mock_client.create_thread.side_effect = RuntimeError("no thread")
        result = copilot_thread([{"role": "user", "content": "hi"}])
        assert "error" in result.lower()


# ──── copilot_summarize ───────────────────────────────────────────────────────


class TestCopilotSummarize:
    def test_concise_style(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_summarize

        copilot_summarize("Long text here", style="concise")
        prompt = mock_client.ask.call_args[0][0]
        assert "2-3 sentences" in prompt

    def test_bullet_style(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_summarize

        copilot_summarize("Long text", style="bullet")
        prompt = mock_client.ask.call_args[0][0]
        assert "bullet" in prompt

    def test_returns_response(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_summarize

        result = copilot_summarize("some text")
        assert result == "Mocked response"


# ──── copilot_explain ────────────────────────────────────────────────────────


class TestCopilotExplain:
    def test_includes_code_in_prompt(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_explain

        copilot_explain("for i in range(10): pass", language="python")
        prompt = mock_client.ask.call_args[0][0]
        assert "for i in range(10)" in prompt

    def test_no_language_hint_still_works(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_explain

        result = copilot_explain("x = 1")
        assert result == "Mocked response"

    def test_returns_error_on_exception(self, mock_client):
        from engine.skills.builtin.copilot_skills import copilot_explain

        mock_client.ask.side_effect = Exception("timeout")
        result = copilot_explain("code")
        assert "error" in result.lower()
