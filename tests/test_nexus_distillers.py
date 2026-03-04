"""Tests for Nexus knowledge distillers: NexusDistiller, QADeduplicator,
SkillUsageDistiller, PromptEvolutionDistiller, run_all_distillers."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════
#  Pattern Extractor Tests
# ══════════════════════════════════════════════════════════════════════


class TestPatternExtractors:
    """Tests for standalone extraction helpers."""

    def test_extract_decisions_from_text(self):
        from engine.nexus.nexus_distiller import _extract_decisions_from_text
        text = "Decision: Use FTS5 for full-text search in Nexus. Also we decided to keep SQLite."
        result = _extract_decisions_from_text(text)
        assert len(result) >= 1
        assert any("FTS5" in d for d in result)

    def test_extract_decisions_ignores_short(self):
        from engine.nexus.nexus_distiller import _extract_decisions_from_text
        text = "Decision: ok"
        result = _extract_decisions_from_text(text)
        assert len(result) == 0

    def test_extract_decisions_created_pattern(self):
        from engine.nexus.nexus_distiller import _extract_decisions_from_text
        text = "Created engine/nexus/nexus_distiller.py with 4 distiller classes."
        result = _extract_decisions_from_text(text)
        assert len(result) >= 1

    def test_extract_fixes_from_text(self):
        from engine.nexus.nexus_distiller import _extract_fixes_from_text
        text = "Fixed the session logger endpoint by changing /api/agent/submit to /api/entries."
        result = _extract_fixes_from_text(text)
        assert len(result) >= 1
        assert "session logger" in result[0]["problem"].lower() or "endpoint" in result[0]["problem"].lower()

    def test_extract_fixes_empty_text(self):
        from engine.nexus.nexus_distiller import _extract_fixes_from_text
        assert _extract_fixes_from_text("") == []

    def test_extract_file_conventions(self):
        from engine.nexus.nexus_distiller import _extract_file_conventions
        text = "We store all config in file `config/default.yaml` which uses 2-space indentation."
        result = _extract_file_conventions(text)
        assert "config/default.yaml" in result

    def test_extract_file_conventions_no_files(self):
        from engine.nexus.nexus_distiller import _extract_file_conventions
        result = _extract_file_conventions("No file paths mentioned here at all.")
        assert result == {}


# ══════════════════════════════════════════════════════════════════════
#  NexusDistiller Tests
# ══════════════════════════════════════════════════════════════════════


class TestNexusDistiller:
    """Tests for the core session data distiller."""

    def test_init(self):
        from engine.nexus.nexus_distiller import NexusDistiller
        d = NexusDistiller("http://test:1234")
        assert d._url == "http://test:1234"

    def test_get_stats_returns_structure(self):
        from engine.nexus.nexus_distiller import NexusDistiller
        entries = [{"content": "abc", "content_type": "note", "tags": "system"}]
        qa = [{"question": "Q?", "answer": "A"}]
        rules = [{"scope": "global", "name": "r1"}]

        mock_client = MagicMock()
        mock_client.list_entries.return_value = entries
        mock_client.find_qa.return_value = qa
        mock_client.get_rules.return_value = rules

        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            stats = NexusDistiller().get_stats()
        assert stats["total_entries"] == 1
        assert stats["total_qa"] == 1
        assert stats["total_rules"] == 1
        assert "by_namespace" in stats
        assert "token_estimate" in stats

    def test_distill_no_logs(self):
        from engine.nexus.nexus_distiller import NexusDistiller
        mock_client = MagicMock()
        mock_client.search.return_value = []
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            result = NexusDistiller().distill()
        assert result["decisions"] == 0
        assert result["fixes"] == 0

    @patch("requests.put")
    def test_distill_extracts_from_log(self, mock_put):
        from engine.nexus.nexus_distiller import NexusDistiller
        log_entry = {
            "id": "log1",
            "content": "Decision: Use namespace tags for separation. "
                       "Fixed the broken endpoint by switching to /api/entries.",
            "tags": '["conversation-log"]',
        }
        mock_client = MagicMock()
        mock_client.search.side_effect = [[log_entry], []]
        mock_client.add_entry.return_value = "new1"
        mock_client.add_qa.return_value = "new2"
        mock_put.return_value = MagicMock(ok=True)

        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            result = NexusDistiller().distill()
        assert result["decisions"] >= 1
        assert mock_client.add_entry.called

    def test_compact_sessions_empty(self):
        from engine.nexus.nexus_distiller import NexusDistiller
        mock_client = MagicMock()
        mock_client.list_entries.return_value = []
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            result = NexusDistiller().compact_sessions()
        assert result["days_compacted"] == 0

    def test_generate_context_primer(self):
        from engine.nexus.nexus_distiller import NexusDistiller
        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_client.get_rules.return_value = []
        mock_client.find_qa.return_value = []
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            primer = NexusDistiller().generate_context_primer()
        assert isinstance(primer, str)


# ══════════════════════════════════════════════════════════════════════
#  QADeduplicator Tests
# ══════════════════════════════════════════════════════════════════════


class TestQADeduplicator:
    """Tests for Q&A deduplication."""

    def test_normalise(self):
        from engine.nexus.nexus_distiller import _normalise
        assert _normalise("Hello, World!") == "hello world"
        assert _normalise("  spaces   here  ") == "spaces here"

    def test_jaccard_identical(self):
        from engine.nexus.nexus_distiller import _jaccard
        assert _jaccard("hello world", "hello world") == 1.0

    def test_jaccard_disjoint(self):
        from engine.nexus.nexus_distiller import _jaccard
        assert _jaccard("hello world", "foo bar") == 0.0

    def test_jaccard_partial(self):
        from engine.nexus.nexus_distiller import _jaccard
        sim = _jaccard("how does the MCP framework work",
                       "how does MCP framework function")
        assert 0.4 < sim < 1.0

    def test_jaccard_empty(self):
        from engine.nexus.nexus_distiller import _jaccard
        assert _jaccard("", "") == 0.0

    def test_find_duplicates_none(self):
        from engine.nexus.nexus_distiller import QADeduplicator
        mock_client = MagicMock()
        mock_client.find_qa.return_value = [
            {"id": "1", "question": "What is X?", "answer": "A"},
            {"id": "2", "question": "Totally different", "answer": "B"},
        ]
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            dupes = QADeduplicator().find_duplicates()
        assert len(dupes) == 0

    def test_find_duplicates_matching(self):
        from engine.nexus.nexus_distiller import QADeduplicator
        mock_client = MagicMock()
        mock_client.find_qa.return_value = [
            {"id": "1", "question": "How does MCP work?", "answer": "It works via tools"},
            {"id": "2", "question": "How does MCP work exactly?", "answer": "MCP works via tool calling with the @skill decorator"},
        ]
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            dupes = QADeduplicator(similarity_threshold=0.5).find_duplicates()
        assert len(dupes) == 1
        # Should keep the longer answer
        assert dupes[0]["keep_id"] == "2"

    @patch("requests.delete")
    def test_deduplicate_removes(self, mock_delete):
        from engine.nexus.nexus_distiller import QADeduplicator
        mock_client = MagicMock()
        mock_client.find_qa.return_value = [
            {"id": "1", "question": "How does MCP work?", "answer": "Short"},
            {"id": "2", "question": "How does MCP work exactly?", "answer": "Longer detailed answer here"},
        ]
        mock_delete.return_value = MagicMock(ok=True)

        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            result = QADeduplicator(similarity_threshold=0.5).deduplicate(dry_run=False)
        assert result["duplicates_found"] == 1
        assert result["removed"] == 1
        assert result["dry_run"] is False

    def test_deduplicate_dry_run(self):
        from engine.nexus.nexus_distiller import QADeduplicator
        mock_client = MagicMock()
        mock_client.find_qa.return_value = [
            {"id": "1", "question": "How does MCP work?", "answer": "Short"},
            {"id": "2", "question": "How does MCP work exactly?", "answer": "Longer answer"},
        ]
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            result = QADeduplicator(similarity_threshold=0.5).deduplicate(dry_run=True)
        assert result["duplicates_found"] == 1
        assert result["removed"] == 0
        assert result["dry_run"] is True


# ══════════════════════════════════════════════════════════════════════
#  SkillUsageDistiller Tests
# ══════════════════════════════════════════════════════════════════════


class TestSkillUsageDistiller:
    """Tests for skill usage analysis distiller."""

    def test_extract_skill_mentions(self):
        from engine.nexus.nexus_distiller import SkillUsageDistiller
        d = SkillUsageDistiller()
        text = "Called nexus_search() and also used nexus_ask tool"
        mentions = d._extract_skill_mentions(text)
        assert "search" in mentions or "nexus_search" in mentions

    def test_extract_skill_mentions_empty(self):
        from engine.nexus.nexus_distiller import SkillUsageDistiller
        d = SkillUsageDistiller()
        assert d._extract_skill_mentions("") == []

    def test_analyse_empty(self):
        from engine.nexus.nexus_distiller import SkillUsageDistiller
        mock_client = MagicMock()
        mock_client.search.return_value = []
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            result = SkillUsageDistiller().analyse()
        assert result["total_mentions"] == 0
        assert result["unique_skills"] == 0

    def test_analyse_finds_skills(self):
        from engine.nexus.nexus_distiller import SkillUsageDistiller
        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"content": "tool call: nexus_search and skill: nexus_ask were used"},
            {"content": "Called nexus_search() again, error with nexus_add failed"},
        ]
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            result = SkillUsageDistiller().analyse()
        assert result["total_mentions"] >= 2
        assert result["unique_skills"] >= 1

    def test_distill_and_store(self):
        from engine.nexus.nexus_distiller import SkillUsageDistiller
        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"content": "tool call: nexus_search used frequently"},
        ]
        mock_client.add_entry.return_value = "stored1"
        mock_client.add_qa.return_value = "qa1"
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            result = SkillUsageDistiller().distill_and_store()
        assert "entries_stored" in result


# ══════════════════════════════════════════════════════════════════════
#  PromptEvolutionDistiller Tests
# ══════════════════════════════════════════════════════════════════════


class TestPromptEvolutionDistiller:
    """Tests for prompt evolution analysis distiller."""

    def test_group_prompts(self):
        from engine.nexus.nexus_distiller import PromptEvolutionDistiller
        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"title": "system prompt v1", "content": "You are...",
             "content_type": "prompt", "tags": "", "created_at": "2025-01-01"},
            {"title": "system prompt v2", "content": "You are a helpful...",
             "content_type": "prompt", "tags": "", "created_at": "2025-02-01"},
            {"title": "character prompt", "content": "Act as...",
             "content_type": "prompt", "tags": "", "created_at": "2025-01-15"},
        ]
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            groups = PromptEvolutionDistiller()._group_prompts()
        assert "system prompt" in groups
        assert len(groups["system prompt"]) == 2
        assert "character prompt" in groups

    def test_get_lineage(self):
        from engine.nexus.nexus_distiller import PromptEvolutionDistiller
        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"title": "base prompt v1", "content": "short",
             "content_type": "prompt", "tags": "", "created_at": "2025-01-01"},
            {"title": "base prompt v2", "content": "much longer content here",
             "content_type": "prompt", "tags": "", "created_at": "2025-02-01"},
        ]
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            lineage = PromptEvolutionDistiller().get_lineage()
        assert lineage["total_prompts"] == 2
        assert lineage["multi_version"] == 1
        assert lineage["lineage"][0]["grew"] is True

    def test_get_lineage_empty(self):
        from engine.nexus.nexus_distiller import PromptEvolutionDistiller
        mock_client = MagicMock()
        mock_client.search.return_value = []
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            lineage = PromptEvolutionDistiller().get_lineage()
        assert lineage["total_prompts"] == 0

    def test_distill_patterns(self):
        from engine.nexus.nexus_distiller import PromptEvolutionDistiller
        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"content_type": "prompt",
             "content": "You are a helpful assistant. Never reveal secrets. "
                        "Format: JSON output. Example: {\"key\": \"value\"}",
             "title": "test prompt", "tags": ""},
        ]
        mock_client.add_entry.return_value = "p1"
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            result = PromptEvolutionDistiller().distill_patterns()
        assert result["prompts_analysed"] == 1
        assert "role_definition" in result["patterns_found"]
        assert "constraint_list" in result["patterns_found"]
        assert "output_format" in result["patterns_found"]
        assert result["stored"] is True

    def test_distill_patterns_no_prompts(self):
        from engine.nexus.nexus_distiller import PromptEvolutionDistiller
        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"content_type": "note", "content": "not a prompt", "title": "x", "tags": ""},
        ]
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            result = PromptEvolutionDistiller().distill_patterns()
        assert result["prompts_analysed"] == 0


# ══════════════════════════════════════════════════════════════════════
#  run_all_distillers Tests
# ══════════════════════════════════════════════════════════════════════


class TestRunAllDistillers:
    """Tests for the unified distiller runner."""

    @patch("requests.delete")
    @patch("requests.put")
    def test_run_all(self, mock_put, mock_delete):
        from engine.nexus.nexus_distiller import run_all_distillers
        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_client.find_qa.return_value = []
        mock_client.list_entries.return_value = []
        mock_client.add_entry.return_value = "x"
        mock_client.add_qa.return_value = "x"
        mock_put.return_value = MagicMock(ok=True)
        mock_delete.return_value = MagicMock(ok=True)

        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            result = run_all_distillers()
        assert "session_distiller" in result
        assert "qa_dedup" in result
        assert "skill_usage" in result
        assert "prompt_evolution" in result


# ══════════════════════════════════════════════════════════════════════
#  API Helper Tests
# ══════════════════════════════════════════════════════════════════════


class TestAPIHelpers:
    """Tests for _api_get, _api_post, _api_delete."""

    def test_api_get_success(self):
        from engine.nexus.nexus_distiller import _api_get
        expected = [{"id": "1"}]
        mock_client = MagicMock()
        mock_client.list_entries.return_value = expected
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            assert _api_get("/api/entries") == expected

    def test_api_get_failure(self):
        from engine.nexus.nexus_distiller import _api_get
        mock_client = MagicMock()
        mock_client.list_entries.side_effect = ConnectionError("offline")
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            assert _api_get("/api/entries") == []

    def test_api_post_success(self):
        from engine.nexus.nexus_distiller import _api_post
        mock_client = MagicMock()
        mock_client.add_entry.return_value = "new1"
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            assert _api_post("/api/entries", {"title": "t"}) == "new1"

    def test_api_post_failure(self):
        from engine.nexus.nexus_distiller import _api_post
        mock_client = MagicMock()
        mock_client.add_entry.side_effect = ConnectionError("offline")
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            assert _api_post("/api/entries", {}) is None

    def test_api_delete_success(self):
        from engine.nexus.nexus_distiller import _api_delete
        mock_client = MagicMock()
        mock_client.delete_entry.return_value = True
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            assert _api_delete("entry1") is True

    @patch("requests.delete")
    def test_api_delete_failure(self, mock_delete):
        from engine.nexus.nexus_distiller import _api_delete
        mock_client = MagicMock()
        mock_client.delete_entry.side_effect = ConnectionError("offline")
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            assert _api_delete("entry1") is False


# ══════════════════════════════════════════════════════════════════════
#  MCP Tool Integration Tests
# ══════════════════════════════════════════════════════════════════════


class TestMCPDistillTool:
    """Tests for the nexus_distill MCP tool actions."""

    def test_stats_action(self):
        mock_client = MagicMock()
        mock_client.list_entries.return_value = []
        mock_client.find_qa.return_value = []
        mock_client.get_rules.return_value = []
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            from engine.nexus.nexus_distiller import NexusDistiller
            result = NexusDistiller().get_stats()
        assert "total_entries" in result

    def test_dedup_dry_action(self):
        mock_client = MagicMock()
        mock_client.find_qa.return_value = []
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            from engine.nexus.nexus_distiller import QADeduplicator
            result = QADeduplicator().deduplicate(dry_run=True)
        assert result["dry_run"] is True

    def test_skills_action(self):
        mock_client = MagicMock()
        mock_client.search.return_value = []
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            from engine.nexus.nexus_distiller import SkillUsageDistiller
            result = SkillUsageDistiller().analyse()
        assert result["total_mentions"] == 0

    def test_lineage_action(self):
        mock_client = MagicMock()
        mock_client.search.return_value = []
        with patch("engine.nexus.nexus_distiller.get_nexus_client", return_value=mock_client):
            from engine.nexus.nexus_distiller import PromptEvolutionDistiller
            result = PromptEvolutionDistiller().get_lineage()
        assert result["total_prompts"] == 0
