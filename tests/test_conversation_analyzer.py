"""Tests for ConversationAnalyzer and UserProfileStore."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.conversation_analyzer import (
    ConversationAnalyzer,
    ExtractionResult,
    get_conversation_analyzer,
    run_conversation_analysis,
)
from engine.nexus.user_profile import UserProfileStore, get_user_profile_store


_SAMPLE_CONVERSATION = """\
User: I'm Knack, working on CosySim with Python on my RTX 2060.
Assistant: Great, how can I help?
User: I want to add QLoRA fine-tuning via Unsloth. I use VS Code and LMStudio.
Assistant: Sure, the training pipeline supports that.
User: Next I want to benchmark the finetuned models and auto-promote them.
"""


class TestExtractionResult:
    def test_to_dict_has_all_keys(self):
        r = ExtractionResult()
        d = r.to_dict()
        for key in ("name", "age", "technical_background", "projects",
                    "preferences", "facts", "topics_of_interest",
                    "decisions_made", "action_items", "extraction_mode", "confidence"):
            assert key in d

    def test_to_profile_update_excludes_empty(self):
        r = ExtractionResult(name="Knack", facts=["Has RTX 2060"])
        update = r.to_profile_update()
        assert update["name"] == "Knack"
        assert "Has RTX 2060" in update["facts"]
        # Empty fields should not appear
        assert "age" not in update

    def test_to_profile_update_no_name_excluded(self):
        r = ExtractionResult()
        update = r.to_profile_update()
        assert "name" not in update


class TestConversationAnalyzerHeuristic:
    def test_heuristic_finds_tech_keywords(self):
        analyzer = ConversationAnalyzer()
        result = analyzer.analyze(_SAMPLE_CONVERSATION, mode="heuristic", store_to_profile=False)
        assert result.extraction_mode == "heuristic"
        tech = [t.lower() for t in result.technical_background]
        # Should find Python, LMStudio or VS Code, Unsloth
        assert any(kw in tech for kw in ["python", "lmstudio", "unsloth", "vs code"])

    def test_heuristic_finds_hardware(self):
        analyzer = ConversationAnalyzer()
        result = analyzer.analyze(
            "I have a machine with RTX 2060 GPU and 32GB RAM for running models.",
            mode="heuristic",
            store_to_profile=False,
        )
        # Heuristic should find hardware or tech mentions
        assert result.facts or result.technical_background, \
            "Heuristic should extract something from hardware text"

    def test_heuristic_finds_cosysim_project(self):
        analyzer = ConversationAnalyzer()
        result = analyzer.analyze(_SAMPLE_CONVERSATION, mode="heuristic", store_to_profile=False)
        assert "CosySim" in result.projects or result.technical_background

    def test_short_text_returns_error(self):
        analyzer = ConversationAnalyzer()
        result = analyzer.analyze("hi", store_to_profile=False)
        assert result.error

    def test_empty_text_returns_error(self):
        analyzer = ConversationAnalyzer()
        result = analyzer.analyze("", store_to_profile=False)
        assert result.error


class TestConversationAnalyzerNLMFallback:
    """Tests the NLM extraction path via mocking."""

    def test_nlm_failure_falls_back_to_lm(self):
        analyzer = ConversationAnalyzer()
        with patch.object(analyzer, "_extract_nlm", return_value=None):
            with patch.object(
                analyzer, "_extract_lm",
                return_value=ExtractionResult(extraction_mode="lm", name="Knack"),
            ):
                result = analyzer.analyze(_SAMPLE_CONVERSATION, mode="auto", store_to_profile=False)
        assert result.extraction_mode == "lm"
        assert result.name == "Knack"

    def test_lm_failure_falls_back_to_heuristic(self):
        analyzer = ConversationAnalyzer()
        with patch.object(analyzer, "_extract_nlm", return_value=None):
            with patch.object(analyzer, "_extract_lm", return_value=None):
                result = analyzer.analyze(_SAMPLE_CONVERSATION, mode="auto", store_to_profile=False)
        assert result.extraction_mode == "heuristic"

    def test_parse_json_response_valid(self):
        analyzer = ConversationAnalyzer()
        json_text = json.dumps({
            "name": "Knack",
            "technical_background": ["Python", "PyTorch"],
            "projects": {"CosySim": {"description": "AI sim framework"}},
            "preferences": {"style": "concise"},
            "facts": ["Has RTX 2060"],
            "topics_of_interest": ["fine-tuning"],
            "decisions_made": ["Use QLoRA"],
            "action_items": ["Benchmark finetuned models"],
        })
        result = analyzer._parse_json_response(json_text, mode="lm")
        assert result is not None
        assert result.name == "Knack"
        assert "Python" in result.technical_background
        assert result.decisions_made == ["Use QLoRA"]
        assert result.action_items == ["Benchmark finetuned models"]

    def test_parse_json_response_with_fences(self):
        analyzer = ConversationAnalyzer()
        fenced = '```json\n{"name": "Knack", "facts": ["Test fact"]}\n```'
        result = analyzer._parse_json_response(fenced, mode="nlm")
        assert result is not None
        assert result.name == "Knack"

    def test_parse_json_response_invalid_returns_none(self):
        analyzer = ConversationAnalyzer()
        result = analyzer._parse_json_response("not json at all", mode="lm")
        assert result is None


class TestConversationAnalyzerStore:
    def test_store_stores_action_items_to_nexus(self, tmp_path):
        analyzer = ConversationAnalyzer()
        result = ExtractionResult(
            action_items=["Fix the benchmark loop"],
            extraction_mode="heuristic",
        )
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        with patch("engine.nexus.user_profile.get_user_profile_store") as mock_ps:
            mock_ps.return_value.merge = MagicMock()
            with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
                analyzer._store_result(result)
        mock_client.add_entry.assert_called_once()
        call_kwargs = mock_client.add_entry.call_args[1]
        assert "Fix the benchmark loop" in call_kwargs.get("content", "")

    def test_get_last_result_none_initially(self):
        analyzer = ConversationAnalyzer()
        assert analyzer.get_last_result() is None

    def test_get_last_result_after_analyze(self):
        analyzer = ConversationAnalyzer()
        analyzer.analyze(_SAMPLE_CONVERSATION, mode="heuristic", store_to_profile=False)
        result = analyzer.get_last_result()
        assert result is not None
        assert "extraction_mode" in result


class TestConversationAnalyzerSingleton:
    def test_singleton_returns_same_instance(self):
        a = get_conversation_analyzer()
        b = get_conversation_analyzer()
        assert a is b


class TestRunConversationAnalysis:
    def test_run_returns_dict(self):
        with patch.object(ConversationAnalyzer, "analyze_recent_turns") as mock_analyze:
            mock_analyze.return_value = ExtractionResult(
                facts=["Has RTX 2060"], extraction_mode="heuristic"
            )
            result = run_conversation_analysis()
        assert isinstance(result, dict)
        assert "extraction_mode" in result


# ──── UserProfileStore Tests ────────────────────────────────────────────────────

class TestUserProfileStore:
    @pytest.fixture
    def store(self, tmp_path) -> UserProfileStore:
        return UserProfileStore(cache_path=tmp_path / "profile.json")

    def test_default_profile_has_name_knack(self, store):
        profile = store.get_profile()
        assert profile["name"] == "Knack"

    def test_add_fact_persists(self, store):
        store.add_fact("Has RTX 2060")
        assert "Has RTX 2060" in store.get_profile()["facts"]

    def test_add_fact_no_duplicates(self, store):
        store.add_fact("Has RTX 2060")
        store.add_fact("Has RTX 2060")
        count = sum(1 for f in store.get_profile()["facts"] if f == "Has RTX 2060")
        assert count == 1

    def test_add_fact_empty_ignored(self, store):
        store.add_fact("   ")
        assert store.get_profile()["facts"] == []

    def test_add_preference(self, store):
        store.add_preference("output_verbosity", "concise")
        assert store.get_profile()["preferences"]["output_verbosity"] == "concise"

    def test_add_project(self, store):
        store.add_project("CosySim", {"status": "active", "tech": ["Python"]})
        profile = store.get_profile()
        assert "CosySim" in profile["projects"]
        assert profile["projects"]["CosySim"]["status"] == "active"

    def test_merge_extends_lists_uniquely(self, store):
        store.merge({"technical_background": ["Python"]})
        store.merge({"technical_background": ["Python", "Rust"]})
        tb = store.get_profile()["technical_background"]
        assert tb.count("Python") == 1
        assert "Rust" in tb

    def test_merge_nested_dicts(self, store):
        store.merge({"preferences": {"a": 1}})
        store.merge({"preferences": {"b": 2}})
        prefs = store.get_profile()["preferences"]
        assert prefs["a"] == 1
        assert prefs["b"] == 2

    def test_increment_conversation_count(self, store):
        assert store.increment_conversation_count() == 1
        assert store.increment_conversation_count() == 2

    def test_get_context_summary_has_profile_heading(self, store):
        store.add_fact("Has RTX 2060")
        summary = store.get_context_summary()
        assert "User Profile" in summary

    def test_profile_loads_from_disk(self, tmp_path):
        """Profile written by one instance is readable by another."""
        path = tmp_path / "profile.json"
        s1 = UserProfileStore(cache_path=path)
        s1.add_fact("Persistent fact")
        s2 = UserProfileStore(cache_path=path)
        assert "Persistent fact" in s2.get_profile()["facts"]

    def test_nexus_sync_skipped_when_unavailable(self, store):
        mock_client = MagicMock()
        mock_client.is_available.return_value = False
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            store.merge({"facts": ["test"]})
        mock_client.add_entry.assert_not_called()

    def test_singleton(self, tmp_path):
        # get_user_profile_store returns consistent singleton per process
        s1 = get_user_profile_store()
        s2 = get_user_profile_store()
        assert s1 is s2
