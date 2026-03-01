"""Tests for user profile context injection into SystemAssistant._get_llm_reply."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# ConversationAnalyzer lookback_sessions
# ──────────────────────────────────────────────────────────────────────────────


class TestConversationAnalyzerLookback:
    """analyze_recent_turns accepts and forwards lookback_sessions."""

    def test_lookback_param_forwarded_to_fetch(self):
        """analyze_recent_turns passes lookback_sessions to _fetch_recent_turns."""
        from engine.nexus.conversation_analyzer import ConversationAnalyzer
        analyzer = ConversationAnalyzer()

        with patch.object(analyzer, "_fetch_recent_turns", return_value="") as mock_fetch:
            analyzer.analyze_recent_turns(lookback_sessions=5)

        mock_fetch.assert_called_once()
        _, _, actual_lookback = mock_fetch.call_args[0]
        assert actual_lookback == 5

    def test_lookback_sessions_clamped_to_50(self):
        """lookback_sessions > 50 is clamped to 50."""
        from engine.nexus.conversation_analyzer import ConversationAnalyzer
        analyzer = ConversationAnalyzer()

        with patch.object(analyzer, "_fetch_recent_turns", return_value="") as mock_fetch:
            analyzer.analyze_recent_turns(lookback_sessions=999)

        mock_fetch.assert_called_once()
        _, _, actual_lookback = mock_fetch.call_args[0]
        assert actual_lookback == 50

    def test_lookback_sessions_minimum_one(self):
        """lookback_sessions < 1 is clamped to 1."""
        from engine.nexus.conversation_analyzer import ConversationAnalyzer
        analyzer = ConversationAnalyzer()

        with patch.object(analyzer, "_fetch_recent_turns", return_value="") as mock_fetch:
            analyzer.analyze_recent_turns(lookback_sessions=0)

        mock_fetch.assert_called_once()
        _, _, actual_lookback = mock_fetch.call_args[0]
        assert actual_lookback == 1

    def test_lookback_default_is_one(self):
        """Default lookback_sessions is 1 (single most-recent session)."""
        from engine.nexus.conversation_analyzer import ConversationAnalyzer
        analyzer = ConversationAnalyzer()

        with patch.object(analyzer, "_fetch_recent_turns", return_value="") as mock_fetch:
            analyzer.analyze_recent_turns()  # no lookback_sessions arg

        mock_fetch.assert_called_once()
        _, _, actual_lookback = mock_fetch.call_args[0]
        assert actual_lookback == 1

    def test_run_conversation_analysis_passes_lookback(self):
        """run_conversation_analysis() proxies lookback_sessions."""
        from engine.nexus.conversation_analyzer import get_conversation_analyzer, run_conversation_analysis

        analyzer = get_conversation_analyzer()
        with patch.object(analyzer, "analyze_recent_turns") as mock_analyze:
            mock_analyze.return_value = MagicMock(to_dict=lambda: {})
            run_conversation_analysis(lookback_sessions=7)

        mock_analyze.assert_called_once()
        kwargs = mock_analyze.call_args[1]
        assert kwargs.get("lookback_sessions") == 7


# ──────────────────────────────────────────────────────────────────────────────
# SystemAssistant profile injection
# ──────────────────────────────────────────────────────────────────────────────


class TestSystemAssistantProfileInjection:
    """User profile context is prepended to the LLM system prompt."""

    def _make_assistant(self):
        from engine.assistant.system_assistant import SystemAssistant

        with patch("engine.config.get_config", return_value=MagicMock(get=lambda k, d=None: d)):
            assistant = SystemAssistant.__new__(SystemAssistant)
            assistant._current_scene = "test"
            assistant._conversation_history = []
            assistant._max_history = 50
            # Assign minimal Aria profile attributes expected by _get_llm_reply
            assistant.id = "aria"
        return assistant

    def test_profile_context_prepended_to_system_prompt(self):
        """When profile has facts, context summary is prepended."""
        assistant = self._make_assistant()

        mock_profile_store = MagicMock()
        mock_profile_store.get_context_summary.return_value = (
            "## User Profile: Dave\n**Tech Background:** Python"
        )

        captured_prompts: list = []

        def fake_req(**kw):
            captured_prompts.append(kw.get("system_prompt", ""))
            return MagicMock()

        mock_vam = MagicMock()
        mock_proc = MagicMock()
        mock_proc.clean_text = "Hello, Dave!"
        mock_vam.infer_processed.return_value = mock_proc

        with (
            patch("engine.nexus.user_profile.get_user_profile_store", return_value=mock_profile_store),
            patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager", return_value=mock_vam),
            patch("engine.agents.virtual_agent.InferenceRequest", side_effect=fake_req),
        ):
            assistant.get_system_summary = MagicMock(return_value={})
            assistant._get_llm_reply("Hi Aria")

        assert captured_prompts, "InferenceRequest was not called"
        system_prompt = captured_prompts[0]
        assert "User Profile" in system_prompt
        assert "Dave" in system_prompt

    def test_profile_unavailable_does_not_raise(self):
        """If profile store raises, the LLM call proceeds without profile context."""
        assistant = self._make_assistant()

        captured_prompts: list = []

        def fake_req(**kw):
            captured_prompts.append(kw.get("system_prompt", ""))
            return MagicMock()

        mock_vam = MagicMock()
        mock_proc = MagicMock()
        mock_proc.clean_text = "Hello!"
        mock_vam.infer_processed.return_value = mock_proc

        with (
            patch(
                "engine.nexus.user_profile.get_user_profile_store",
                side_effect=RuntimeError("nexus unavailable"),
            ),
            patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager", return_value=mock_vam),
            patch("engine.agents.virtual_agent.InferenceRequest", side_effect=fake_req),
        ):
            assistant.get_system_summary = MagicMock(return_value={})
            # Should not raise
            assistant._get_llm_reply("Hi")

        assert captured_prompts, "InferenceRequest was not called"
        assert captured_prompts[0]  # System prompt still set

    def test_empty_profile_context_not_prepended(self):
        """Empty context summary (no facts yet) does not add separator."""
        assistant = self._make_assistant()

        mock_profile_store = MagicMock()
        mock_profile_store.get_context_summary.return_value = ""

        captured_prompts: list = []

        def fake_req(**kw):
            captured_prompts.append(kw.get("system_prompt", ""))
            return MagicMock()

        mock_vam = MagicMock()
        mock_proc = MagicMock()
        mock_proc.clean_text = "Hello!"
        mock_vam.infer_processed.return_value = mock_proc

        with (
            patch("engine.nexus.user_profile.get_user_profile_store", return_value=mock_profile_store),
            patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager", return_value=mock_vam),
            patch("engine.agents.virtual_agent.InferenceRequest", side_effect=fake_req),
        ):
            assistant.get_system_summary = MagicMock(return_value={})
            assistant._get_llm_reply("Hi")

        assert captured_prompts
        # No profile block or separator when context is empty
        assert "User Profile" not in captured_prompts[0]
        assert "---" not in captured_prompts[0]

