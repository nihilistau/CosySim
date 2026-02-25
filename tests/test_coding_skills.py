"""Tests for coding agent skills pack."""
import json
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_client():
    """Mock NexusClient for coding skills tests."""
    client = MagicMock()
    client.search.return_value = [
        {"id": "e1", "title": "Test Pattern", "content_type": "code",
         "category": "development", "content": "some code here"}
    ]
    client.add_entry.return_value = "entry-123"
    client.ask.return_value = {
        "answer": "Use the interceptor pipeline",
        "source": "qa_cache", "confidence": 0.9,
    }
    client.log_session.return_value = "sess-123"
    client.update_session.return_value = True
    client.stats.return_value = {"data": {"knowledge_entries": 100}}
    client.list_sessions.return_value = []
    client.list_research.return_value = []
    return client


class TestCodingStoreSnippet:
    def test_stores_snippet(self, mock_client):
        with patch("engine.skills.builtin.coding_skills._client", return_value=mock_client):
            from engine.skills.builtin.coding_skills import coding_store_snippet
            result = json.loads(coding_store_snippet("My Pattern", "def foo(): pass", "python"))
            assert result["ok"]
            assert result["entry_id"] == "entry-123"
            mock_client.add_entry.assert_called_once()
            call_kwargs = mock_client.add_entry.call_args
            assert "snippet" in call_kwargs[1].get("tags", call_kwargs[0][4] if len(call_kwargs[0]) > 4 else [])


class TestCodingSearch:
    def test_search_general(self, mock_client):
        with patch("engine.skills.builtin.coding_skills._client", return_value=mock_client):
            from engine.skills.builtin.coding_skills import coding_search
            result = json.loads(coding_search("pattern"))
            assert len(result) >= 1
            mock_client.search.assert_called_once()


class TestCodingStoreDecision:
    def test_stores_decision(self, mock_client):
        with patch("engine.skills.builtin.coding_skills._client", return_value=mock_client):
            from engine.skills.builtin.coding_skills import coding_store_decision
            result = json.loads(coding_store_decision(
                "Use SQLite", "SQLite for local storage",
                rationale="Simple, embedded, fast",
                alternatives="PostgreSQL, MongoDB",
            ))
            assert result["ok"]
            call_args = mock_client.add_entry.call_args
            content = call_args[1].get("content", call_args[0][1] if len(call_args[0]) > 1 else "")
            assert "Decision" in content
            assert "Rationale" in content
            assert "Alternatives" in content


class TestCodingLogSession:
    def test_logs_session(self, mock_client):
        with patch("engine.skills.builtin.coding_skills._client", return_value=mock_client):
            from engine.skills.builtin.coding_skills import coding_log_session
            result = json.loads(coding_log_session(
                "Fixed FTS5 bug", files_changed="store.py,routes.py",
                commits="abc1234"
            ))
            assert result["ok"]
            assert result["session_id"] == "sess-123"
            mock_client.log_session.assert_called_once()
            mock_client.update_session.assert_called_once()


class TestCodingResearch:
    def test_research_question(self, mock_client):
        with patch("engine.skills.builtin.coding_skills._client", return_value=mock_client):
            from engine.skills.builtin.coding_skills import coding_research
            result = json.loads(coding_research("How does the pipeline work?"))
            assert result["answer"] == "Use the interceptor pipeline"
            mock_client.ask.assert_called_once()


class TestCodingStoreBug:
    def test_stores_bug(self, mock_client):
        with patch("engine.skills.builtin.coding_skills._client", return_value=mock_client):
            from engine.skills.builtin.coding_skills import coding_store_bug
            result = json.loads(coding_store_bug(
                "FTS5 crash", "Crashes on ? chars",
                fix="Sanitize query", root_cause="FTS5 special chars"
            ))
            assert result["ok"]


class TestCodingProjectStatus:
    def test_gets_status(self, mock_client):
        with patch("engine.skills.builtin.coding_skills._client", return_value=mock_client):
            from engine.skills.builtin.coding_skills import coding_project_status
            result = json.loads(coding_project_status())
            assert "nexus_stats" in result
            assert "recent_sessions" in result
            assert "active_research" in result
