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

    @patch("requests.get")
    def test_get_stats_returns_structure(self, mock_get):
        from engine.nexus.nexus_distiller import NexusDistiller
        entries = [{"content": "abc", "content_type": "note", "tags": "system"}]
        qa = [{"question": "Q?", "answer": "A"}]
        rules = [{"scope": "global", "name": "r1"}]

        def side_effect(url, **kw):
            resp = MagicMock()
            resp.ok = True
            if "/api/entries" in url:
                resp.json.return_value = {"data": entries}
            elif "/api/qa" in url:
                resp.json.return_value = {"data": qa}
            elif "/api/rules" in url:
                resp.json.return_value = {"data": rules}
            return resp

        mock_get.side_effect = side_effect
        stats = NexusDistiller().get_stats()
        assert stats["total_entries"] == 1
        assert stats["total_qa"] == 1
        assert stats["total_rules"] == 1
        assert "by_namespace" in stats
        assert "token_estimate" in stats

    @patch("requests.get")
    def test_distill_no_logs(self, mock_get):
        from engine.nexus.nexus_distiller import NexusDistiller
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": []}
        mock_get.return_value = resp

        result = NexusDistiller().distill()
        assert result["decisions"] == 0
        assert result["fixes"] == 0

    @patch("requests.put")
    @patch("requests.post")
    @patch("requests.get")
    def test_distill_extracts_from_log(self, mock_get, mock_post, mock_put):
        from engine.nexus.nexus_distiller import NexusDistiller
        log_entry = {
            "id": "log1",
            "content": "Decision: Use namespace tags for separation. "
                       "Fixed the broken endpoint by switching to /api/entries.",
            "tags": '["conversation-log"]',
        }

        def get_side(url, **kw):
            resp = MagicMock()
            resp.ok = True
            if "search" in url:
                resp.json.return_value = {"data": [log_entry]}
            else:
                resp.json.return_value = {"data": []}
            return resp

        mock_get.side_effect = get_side
        post_resp = MagicMock()
        post_resp.ok = True
        post_resp.json.return_value = {"data": {"id": "new1"}}
        mock_post.return_value = post_resp
        mock_put.return_value = MagicMock(ok=True)

        result = NexusDistiller().distill()
        assert result["decisions"] >= 1
        assert mock_post.called

    @patch("requests.get")
    def test_compact_sessions_empty(self, mock_get):
        from engine.nexus.nexus_distiller import NexusDistiller
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": []}
        mock_get.return_value = resp

        result = NexusDistiller().compact_sessions()
        assert result["days_compacted"] == 0

    @patch("requests.get")
    def test_generate_context_primer(self, mock_get):
        from engine.nexus.nexus_distiller import NexusDistiller
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": []}
        mock_get.return_value = resp

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

    @patch("requests.get")
    def test_find_duplicates_none(self, mock_get):
        from engine.nexus.nexus_distiller import QADeduplicator
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": [
            {"id": "1", "question": "What is X?", "answer": "A"},
            {"id": "2", "question": "Totally different", "answer": "B"},
        ]}
        mock_get.return_value = resp

        dupes = QADeduplicator().find_duplicates()
        assert len(dupes) == 0

    @patch("requests.get")
    def test_find_duplicates_matching(self, mock_get):
        from engine.nexus.nexus_distiller import QADeduplicator
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": [
            {"id": "1", "question": "How does MCP work?", "answer": "It works via tools"},
            {"id": "2", "question": "How does MCP work exactly?", "answer": "MCP works via tool calling with the @skill decorator"},
        ]}
        mock_get.return_value = resp

        dupes = QADeduplicator(similarity_threshold=0.5).find_duplicates()
        assert len(dupes) == 1
        # Should keep the longer answer
        assert dupes[0]["keep_id"] == "2"

    @patch("requests.delete")
    @patch("requests.get")
    def test_deduplicate_removes(self, mock_get, mock_delete):
        from engine.nexus.nexus_distiller import QADeduplicator
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": [
            {"id": "1", "question": "How does MCP work?", "answer": "Short"},
            {"id": "2", "question": "How does MCP work exactly?", "answer": "Longer detailed answer here"},
        ]}
        mock_get.return_value = resp
        mock_delete.return_value = MagicMock(ok=True)

        result = QADeduplicator(similarity_threshold=0.5).deduplicate(dry_run=False)
        assert result["duplicates_found"] == 1
        assert result["removed"] == 1
        assert result["dry_run"] is False

    @patch("requests.get")
    def test_deduplicate_dry_run(self, mock_get):
        from engine.nexus.nexus_distiller import QADeduplicator
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": [
            {"id": "1", "question": "How does MCP work?", "answer": "Short"},
            {"id": "2", "question": "How does MCP work exactly?", "answer": "Longer answer"},
        ]}
        mock_get.return_value = resp

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

    @patch("requests.get")
    def test_analyse_empty(self, mock_get):
        from engine.nexus.nexus_distiller import SkillUsageDistiller
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": []}
        mock_get.return_value = resp

        result = SkillUsageDistiller().analyse()
        assert result["total_mentions"] == 0
        assert result["unique_skills"] == 0

    @patch("requests.get")
    def test_analyse_finds_skills(self, mock_get):
        from engine.nexus.nexus_distiller import SkillUsageDistiller
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": [
            {"content": "tool call: nexus_search and skill: nexus_ask were used"},
            {"content": "Called nexus_search() again, error with nexus_add failed"},
        ]}
        mock_get.return_value = resp

        result = SkillUsageDistiller().analyse()
        assert result["total_mentions"] >= 2
        assert result["unique_skills"] >= 1

    @patch("requests.post")
    @patch("requests.get")
    def test_distill_and_store(self, mock_get, mock_post):
        from engine.nexus.nexus_distiller import SkillUsageDistiller
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": [
            {"content": "tool call: nexus_search used frequently"},
        ]}
        mock_get.return_value = resp
        post_resp = MagicMock()
        post_resp.ok = True
        post_resp.json.return_value = {"data": {"id": "stored1"}}
        mock_post.return_value = post_resp

        result = SkillUsageDistiller().distill_and_store()
        assert "entries_stored" in result


# ══════════════════════════════════════════════════════════════════════
#  PromptEvolutionDistiller Tests
# ══════════════════════════════════════════════════════════════════════


class TestPromptEvolutionDistiller:
    """Tests for prompt evolution analysis distiller."""

    @patch("requests.get")
    def test_group_prompts(self, mock_get):
        from engine.nexus.nexus_distiller import PromptEvolutionDistiller
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": [
            {"title": "system prompt v1", "content": "You are...",
             "content_type": "prompt", "tags": "", "created_at": "2025-01-01"},
            {"title": "system prompt v2", "content": "You are a helpful...",
             "content_type": "prompt", "tags": "", "created_at": "2025-02-01"},
            {"title": "character prompt", "content": "Act as...",
             "content_type": "prompt", "tags": "", "created_at": "2025-01-15"},
        ]}
        mock_get.return_value = resp

        groups = PromptEvolutionDistiller()._group_prompts()
        assert "system prompt" in groups
        assert len(groups["system prompt"]) == 2
        assert "character prompt" in groups

    @patch("requests.get")
    def test_get_lineage(self, mock_get):
        from engine.nexus.nexus_distiller import PromptEvolutionDistiller
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": [
            {"title": "base prompt v1", "content": "short",
             "content_type": "prompt", "tags": "", "created_at": "2025-01-01"},
            {"title": "base prompt v2", "content": "much longer content here",
             "content_type": "prompt", "tags": "", "created_at": "2025-02-01"},
        ]}
        mock_get.return_value = resp

        lineage = PromptEvolutionDistiller().get_lineage()
        assert lineage["total_prompts"] == 2
        assert lineage["multi_version"] == 1
        assert lineage["lineage"][0]["grew"] is True

    @patch("requests.get")
    def test_get_lineage_empty(self, mock_get):
        from engine.nexus.nexus_distiller import PromptEvolutionDistiller
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": []}
        mock_get.return_value = resp

        lineage = PromptEvolutionDistiller().get_lineage()
        assert lineage["total_prompts"] == 0

    @patch("requests.post")
    @patch("requests.get")
    def test_distill_patterns(self, mock_get, mock_post):
        from engine.nexus.nexus_distiller import PromptEvolutionDistiller
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": [
            {"content_type": "prompt",
             "content": "You are a helpful assistant. Never reveal secrets. "
                        "Format: JSON output. Example: {\"key\": \"value\"}",
             "title": "test prompt", "tags": ""},
        ]}
        mock_get.return_value = resp
        post_resp = MagicMock()
        post_resp.ok = True
        post_resp.json.return_value = {"data": {"id": "p1"}}
        mock_post.return_value = post_resp

        result = PromptEvolutionDistiller().distill_patterns()
        assert result["prompts_analysed"] == 1
        assert "role_definition" in result["patterns_found"]
        assert "constraint_list" in result["patterns_found"]
        assert "output_format" in result["patterns_found"]
        assert result["stored"] is True

    @patch("requests.get")
    def test_distill_patterns_no_prompts(self, mock_get):
        from engine.nexus.nexus_distiller import PromptEvolutionDistiller
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": [
            {"content_type": "note", "content": "not a prompt", "title": "x", "tags": ""},
        ]}
        mock_get.return_value = resp

        result = PromptEvolutionDistiller().distill_patterns()
        assert result["prompts_analysed"] == 0


# ══════════════════════════════════════════════════════════════════════
#  run_all_distillers Tests
# ══════════════════════════════════════════════════════════════════════


class TestRunAllDistillers:
    """Tests for the unified distiller runner."""

    @patch("requests.delete")
    @patch("requests.put")
    @patch("requests.post")
    @patch("requests.get")
    def test_run_all(self, mock_get, mock_post, mock_put, mock_delete):
        from engine.nexus.nexus_distiller import run_all_distillers
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": []}
        mock_get.return_value = resp
        mock_post.return_value = MagicMock(ok=True, json=MagicMock(return_value={"data": {"id": "x"}}))
        mock_put.return_value = MagicMock(ok=True)
        mock_delete.return_value = MagicMock(ok=True)

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

    @patch("requests.get")
    def test_api_get_success(self, mock_get):
        from engine.nexus.nexus_distiller import _api_get
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": [{"id": "1"}]}
        mock_get.return_value = resp
        assert _api_get("/api/entries") == [{"id": "1"}]

    @patch("requests.get")
    def test_api_get_failure(self, mock_get):
        from engine.nexus.nexus_distiller import _api_get
        mock_get.side_effect = ConnectionError("offline")
        assert _api_get("/api/entries") == []

    @patch("requests.post")
    def test_api_post_success(self, mock_post):
        from engine.nexus.nexus_distiller import _api_post
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": {"id": "new1"}}
        mock_post.return_value = resp
        assert _api_post("/api/entries", {"title": "t"}) == "new1"

    @patch("requests.post")
    def test_api_post_failure(self, mock_post):
        from engine.nexus.nexus_distiller import _api_post
        mock_post.side_effect = ConnectionError("offline")
        assert _api_post("/api/entries", {}) is None

    @patch("requests.delete")
    def test_api_delete_success(self, mock_delete):
        from engine.nexus.nexus_distiller import _api_delete
        mock_delete.return_value = MagicMock(ok=True)
        assert _api_delete("entry1") is True

    @patch("requests.delete")
    def test_api_delete_failure(self, mock_delete):
        from engine.nexus.nexus_distiller import _api_delete
        mock_delete.side_effect = ConnectionError("offline")
        assert _api_delete("entry1") is False


# ══════════════════════════════════════════════════════════════════════
#  MCP Tool Integration Tests
# ══════════════════════════════════════════════════════════════════════


class TestMCPDistillTool:
    """Tests for the nexus_distill MCP tool actions."""

    @patch("requests.get")
    def test_stats_action(self, mock_get):
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": []}
        mock_get.return_value = resp

        from engine.nexus.nexus_distiller import NexusDistiller
        result = NexusDistiller().get_stats()
        assert "total_entries" in result

    @patch("requests.get")
    def test_dedup_dry_action(self, mock_get):
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": []}
        mock_get.return_value = resp

        from engine.nexus.nexus_distiller import QADeduplicator
        result = QADeduplicator().deduplicate(dry_run=True)
        assert result["dry_run"] is True

    @patch("requests.get")
    def test_skills_action(self, mock_get):
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": []}
        mock_get.return_value = resp

        from engine.nexus.nexus_distiller import SkillUsageDistiller
        result = SkillUsageDistiller().analyse()
        assert result["total_mentions"] == 0

    @patch("requests.get")
    def test_lineage_action(self, mock_get):
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"data": []}
        mock_get.return_value = resp

        from engine.nexus.nexus_distiller import PromptEvolutionDistiller
        result = PromptEvolutionDistiller().get_lineage()
        assert result["total_prompts"] == 0
