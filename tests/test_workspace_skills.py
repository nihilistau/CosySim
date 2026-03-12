"""Tests for workspace MCP skills — workspace_skills.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _parse(result: str) -> dict:
    """Parse JSON skill result string."""
    return json.loads(result)


# ──── Search & Discovery Skills ───────────────────────────────────────────────


class TestWorkspaceSearch:
    """Tests for workspace_search skill."""

    def test_search_returns_results(self):
        """workspace_search returns search results."""
        with patch("engine.skills.builtin.workspace_skills._drive") as mock_drive:
            mock_client = MagicMock()
            mock_client.ai_overview_search.return_value = {"results": [{"id": "1"}], "total": 1}
            mock_drive.return_value = mock_client

            from engine.skills.builtin.workspace_skills import workspace_search
            result = _parse(workspace_search("quantum"))
            assert "results" in result

    def test_search_no_account(self):
        """workspace_search returns error when no account."""
        with patch("engine.skills.builtin.workspace_skills._drive", return_value=None):
            from engine.skills.builtin.workspace_skills import workspace_search
            result = _parse(workspace_search("test"))
            assert "error" in result

    def test_search_handles_exception(self):
        """workspace_search handles exceptions gracefully."""
        with patch("engine.skills.builtin.workspace_skills._drive") as mock_drive:
            mock_client = MagicMock()
            mock_client.ai_overview_search.side_effect = Exception("network error")
            mock_drive.return_value = mock_client

            from engine.skills.builtin.workspace_skills import workspace_search
            result = _parse(workspace_search("test"))
            assert "error" in result


class TestWorkspaceAsk:
    """Tests for workspace_ask skill."""

    def test_ask_returns_answer(self):
        """workspace_ask returns synthesised answer."""
        with patch("engine.skills.builtin.workspace_skills._drive") as mock_drive:
            mock_client = MagicMock()
            mock_client.ask_gemini.return_value = {"answer": "42", "sources": []}
            mock_drive.return_value = mock_client

            from engine.skills.builtin.workspace_skills import workspace_ask
            result = _parse(workspace_ask("What is the answer?"))
            assert "answer" in result

    def test_ask_with_file_ids(self):
        """workspace_ask parses comma-separated file_ids."""
        with patch("engine.skills.builtin.workspace_skills._drive") as mock_drive:
            mock_client = MagicMock()
            mock_client.ask_gemini.return_value = {"answer": "done"}
            mock_drive.return_value = mock_client

            from engine.skills.builtin.workspace_skills import workspace_ask
            workspace_ask("Question?", file_ids="file1,file2,file3")
            _, kwargs = mock_client.ask_gemini.call_args
            assert kwargs["file_ids"] == ["file1", "file2", "file3"]


# ──── Document Skills ─────────────────────────────────────────────────────────


class TestWorkspaceCreateDoc:
    """Tests for workspace_create_doc skill."""

    def test_create_doc_with_prompt(self):
        """workspace_create_doc with prompt calls create_with_gemini."""
        with patch("engine.skills.builtin.workspace_skills._docs") as mock_docs:
            mock_client = MagicMock()
            mock_client.create_with_gemini.return_value = {"documentId": "doc123"}
            mock_docs.return_value = mock_client

            from engine.skills.builtin.workspace_skills import workspace_create_doc
            result = _parse(workspace_create_doc("AI Report", prompt="Write about AI"))
            assert result["doc_id"] == "doc123"

    def test_create_doc_with_content(self):
        """workspace_create_doc with content calls create_doc + append."""
        with patch("engine.skills.builtin.workspace_skills._docs") as mock_docs:
            mock_client = MagicMock()
            mock_client.create_doc.return_value = {"documentId": "doc456"}
            mock_docs.return_value = mock_client

            from engine.skills.builtin.workspace_skills import workspace_create_doc
            result = _parse(workspace_create_doc("Manual Doc", content="Some text"))
            assert result["doc_id"] == "doc456"
            mock_client.append_to_doc.assert_called_once()

    def test_create_doc_no_account(self):
        """workspace_create_doc returns error when no account."""
        with patch("engine.skills.builtin.workspace_skills._docs", return_value=None):
            from engine.skills.builtin.workspace_skills import workspace_create_doc
            result = _parse(workspace_create_doc("Test"))
            assert "error" in result


# ──── Sheet Skills ────────────────────────────────────────────────────────────


class TestWorkspaceCreateSheet:
    """Tests for workspace_create_sheet skill."""

    def test_create_sheet(self):
        """workspace_create_sheet calls build_with_gemini."""
        with patch("engine.skills.builtin.workspace_skills._sheets") as mock_sheets:
            mock_client = MagicMock()
            mock_client.build_with_gemini.return_value = {"spreadsheetId": "sheet789"}
            mock_sheets.return_value = mock_client

            from engine.skills.builtin.workspace_skills import workspace_create_sheet
            result = _parse(workspace_create_sheet("Budget", "Monthly budget tracker"))
            assert result["sheet_id"] == "sheet789"

    def test_create_sheet_no_account(self):
        """workspace_create_sheet returns error when no account."""
        with patch("engine.skills.builtin.workspace_skills._sheets", return_value=None):
            from engine.skills.builtin.workspace_skills import workspace_create_sheet
            result = _parse(workspace_create_sheet("Test", "Test prompt"))
            assert "error" in result


class TestWorkspaceFillSheet:
    """Tests for workspace_fill_sheet skill."""

    def test_fill_sheet(self):
        """workspace_fill_sheet calls fill_with_gemini."""
        with patch("engine.skills.builtin.workspace_skills._sheets") as mock_sheets:
            mock_client = MagicMock()
            mock_client.fill_with_gemini.return_value = {"updated_range": "B2:B10"}
            mock_sheets.return_value = mock_client

            from engine.skills.builtin.workspace_skills import workspace_fill_sheet
            result = _parse(workspace_fill_sheet("sheet1", "B2:B10", "Population of each city"))
            assert "updated_range" in result


class TestWorkspaceColumnsmith:
    """Tests for workspace_columnsmith skill."""

    def test_columnsmith(self):
        """workspace_columnsmith calls execute_columnsmith."""
        with patch("engine.skills.builtin.workspace_skills._sheets") as mock_sheets:
            mock_client = MagicMock()
            mock_client.execute_columnsmith.return_value = {"status": "ok"}
            mock_sheets.return_value = mock_client

            from engine.skills.builtin.workspace_skills import workspace_columnsmith
            result = _parse(workspace_columnsmith("sheet1", "C", "Classify sentiment"))
            assert "status" in result


# ──── Generation Skills ───────────────────────────────────────────────────────


class TestWorkspaceGenerate:
    """Tests for workspace_generate skill."""

    def test_generate(self):
        """workspace_generate calls stream_generate."""
        with patch("engine.skills.builtin.workspace_skills._ws_gemini") as mock_ws:
            mock_client = MagicMock()
            mock_client.stream_generate.return_value = {"text": "Generated text"}
            mock_ws.return_value = mock_client

            from engine.skills.builtin.workspace_skills import workspace_generate
            result = _parse(workspace_generate("Write a haiku"))
            assert "text" in result

    def test_generate_no_account(self):
        """workspace_generate returns error when no account."""
        with patch("engine.skills.builtin.workspace_skills._ws_gemini", return_value=None):
            from engine.skills.builtin.workspace_skills import workspace_generate
            result = _parse(workspace_generate("test"))
            assert "error" in result


class TestWorkspaceQuota:
    """Tests for workspace_quota skill."""

    def test_quota(self):
        """workspace_quota returns usage info."""
        with patch("engine.skills.builtin.workspace_skills._ws_gemini") as mock_ws:
            mock_client = MagicMock()
            mock_client.quota_summary.return_value = {"daily_used": 5}
            mock_ws.return_value = mock_client

            from engine.skills.builtin.workspace_skills import workspace_quota
            result = _parse(workspace_quota())
            assert "daily_used" in result


# ──── Pipeline Skills ─────────────────────────────────────────────────────────


class TestWorkspaceResearch:
    """Tests for workspace_research skill."""

    def test_research(self):
        """workspace_research runs the research pipeline."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed", "run_id": "abc"}
            mock_pipe.return_value.research_and_distill.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_research
            result = _parse(workspace_research("quantum computing"))
            assert result["status"] == "completed"

    def test_research_with_questions(self):
        """workspace_research parses pipe-separated questions."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed"}
            mock_pipe.return_value.research_and_distill.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_research
            workspace_research("AI", questions="What is AI?|How does it work?")
            _, kwargs = mock_pipe.return_value.research_and_distill.call_args
            assert kwargs.get("questions") == ["What is AI?", "How does it work?"]


class TestWorkspacePipelineSkill:
    """Tests for workspace_pipeline skill."""

    def test_run_template(self):
        """workspace_pipeline runs a named template."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed"}
            mock_pipe.return_value.run.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_pipeline
            result = _parse(workspace_pipeline("research_and_distill", topic="test"))
            assert result["status"] == "completed"


class TestWorkspaceListPipelines:
    """Tests for workspace_list_pipelines skill."""

    def test_list_pipelines(self):
        """workspace_list_pipelines returns template names."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_pipe.return_value.list_templates.return_value = {
                "research_and_distill": ["nlm_research", "create_sheet"],
            }

            from engine.skills.builtin.workspace_skills import workspace_list_pipelines
            result = _parse(workspace_list_pipelines())
            assert "research_and_distill" in result


class TestWorkspacePipelineStatus:
    """Tests for workspace_pipeline_status skill."""

    def test_status_found(self):
        """workspace_pipeline_status returns run info."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"run_id": "abc", "status": "completed"}
            mock_pipe.return_value.get_run.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_pipeline_status
            result = _parse(workspace_pipeline_status("abc"))
            assert result["run_id"] == "abc"

    def test_status_not_found(self):
        """workspace_pipeline_status returns error for unknown run."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_pipe.return_value.get_run.return_value = None

            from engine.skills.builtin.workspace_skills import workspace_pipeline_status
            result = _parse(workspace_pipeline_status("zzz"))
            assert "error" in result


class TestWorkspaceKnowledgeDoc:
    """Tests for workspace_knowledge_doc skill."""

    def test_knowledge_doc(self):
        """workspace_knowledge_doc runs pipeline."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed"}
            mock_pipe.return_value.create_knowledge_doc.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_knowledge_doc
            result = _parse(workspace_knowledge_doc("AI safety"))
            assert result["status"] == "completed"


class TestWorkspaceSynthesize:
    """Tests for workspace_synthesize skill."""

    def test_synthesize(self):
        """workspace_synthesize runs pipeline."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed"}
            mock_pipe.return_value.cross_source_synthesis.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_synthesize
            result = _parse(workspace_synthesize("climate change"))
            assert result["status"] == "completed"


class TestWorkspaceNews:
    """Tests for workspace_news skill."""

    def test_news_digest(self):
        """workspace_news runs the news pipeline."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed"}
            mock_pipe.return_value.news_digest.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_news
            result = _parse(workspace_news("tech news"))
            assert result["status"] == "completed"

    def test_news_with_sources(self):
        """workspace_news parses pipe-separated sources."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed"}
            mock_pipe.return_value.news_digest.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_news
            workspace_news("AI", sources="https://a.com|https://b.com")
            _, kwargs = mock_pipe.return_value.news_digest.call_args
            assert kwargs.get("sources") == ["https://a.com", "https://b.com"]


class TestWorkspaceGenerate:
    """Tests for workspace_generate skill."""

    def test_generate_with_store(self):
        """workspace_generate runs generate_and_store template by default."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed", "generated": "text"}
            mock_pipe.return_value.run.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_generate
            result = _parse(workspace_generate("Write a summary of AI trends"))
            assert result["status"] == "completed"
            mock_pipe.return_value.run.assert_called_once_with(
                "generate_and_store", topic="Write a summary of AI trends", context="sheets"
            )

    def test_generate_without_store(self):
        """workspace_generate runs only generation stage when store=False."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed"}
            mock_pipe.return_value.run_stages.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_generate
            result = _parse(workspace_generate("test prompt", store=False))
            assert result["status"] == "completed"
            mock_pipe.return_value.run_stages.assert_called_once()

    def test_generate_docs_context(self):
        """workspace_generate passes context parameter to pipeline."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed"}
            mock_pipe.return_value.run.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_generate
            workspace_generate("draft a report", context="docs")
            _, kwargs = mock_pipe.return_value.run.call_args
            assert kwargs.get("context") == "docs"

    def test_generate_error_returns_json(self):
        """workspace_generate returns error JSON on failure."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_pipe.return_value.run.side_effect = RuntimeError("API down")

            from engine.skills.builtin.workspace_skills import workspace_generate
            result = _parse(workspace_generate("test"))
            assert "error" in result


class TestWorkspaceFetchNews:
    """Tests for workspace_fetch_news skill."""

    def test_fetch_news_default_category(self):
        """workspace_fetch_news uses ai_research category by default."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed", "articles": 5}
            mock_pipe.return_value.run_stages.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_fetch_news
            result = _parse(workspace_fetch_news())
            assert result["status"] == "completed"
            call_kwargs = mock_pipe.return_value.run_stages.call_args
            assert call_kwargs[1].get("categories") == ["ai_research"]

    def test_fetch_news_multiple_categories(self):
        """workspace_fetch_news parses pipe-separated categories."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed"}
            mock_pipe.return_value.run_stages.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_fetch_news
            workspace_fetch_news(categories="ai_research|tech|world")
            call_kwargs = mock_pipe.return_value.run_stages.call_args
            assert call_kwargs[1].get("categories") == ["ai_research", "tech", "world"]

    def test_fetch_news_custom_max_articles(self):
        """workspace_fetch_news passes max_articles parameter."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed"}
            mock_pipe.return_value.run_stages.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_fetch_news
            workspace_fetch_news(max_articles=50)
            call_kwargs = mock_pipe.return_value.run_stages.call_args
            assert call_kwargs[1].get("max_articles") == 50

    def test_fetch_news_no_store(self):
        """workspace_fetch_news respects store=False."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_run = MagicMock()
            mock_run.to_dict.return_value = {"status": "completed"}
            mock_pipe.return_value.run_stages.return_value = mock_run

            from engine.skills.builtin.workspace_skills import workspace_fetch_news
            workspace_fetch_news(store=False)
            call_kwargs = mock_pipe.return_value.run_stages.call_args
            assert call_kwargs[1].get("store_articles") is False

    def test_fetch_news_error_returns_json(self):
        """workspace_fetch_news returns error JSON on failure."""
        with patch("engine.skills.builtin.workspace_skills._pipeline") as mock_pipe:
            mock_pipe.return_value.run_stages.side_effect = RuntimeError("feed timeout")

            from engine.skills.builtin.workspace_skills import workspace_fetch_news
            result = _parse(workspace_fetch_news())
            assert "error" in result
