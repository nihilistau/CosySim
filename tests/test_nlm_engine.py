"""Tests for engine.nexus.nlm_engine — Unified NLM client."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from engine.nexus.nlm_engine import NLMEngine, NLMStats


# ──── Fixtures ────

@pytest.fixture
def engine():
    """NLMEngine with mocked config."""
    with patch("engine.nexus.nlm_engine.get_config") as mock_cfg:
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None: {
            "notebooklm.base_url": "http://localhost:8800",
            "notebooklm.nexus_nlm_url": "http://localhost:3000",
            "notebooklm.timeout": 10,
        }.get(key, default)
        mock_cfg.return_value = cfg
        e = NLMEngine()
    return e


# ──── Stats Tests ────

def test_stats_initial():
    """Initial stats are all zero."""
    stats = NLMStats()
    d = stats.to_dict()
    assert d["asks"] == 0
    assert d["total_questions"] == 0
    assert d["errors"] == 0
    assert "uptime_seconds" in d


def test_stats_increment():
    """Stats increment correctly."""
    stats = NLMStats()
    stats.asks = 5
    stats.cache_hits = 3
    stats.total_questions = 8
    d = stats.to_dict()
    assert d["asks"] == 5
    assert d["total_questions"] == 8


# ──── Status Tests ────

def test_is_available_false(engine):
    """Not available when no backend responds."""
    with patch.object(engine, "_check_backend", return_value=False):
        assert engine.is_available() is False


def test_is_available_proxy(engine):
    """Available when proxy responds."""
    def check(url):
        return "8800" in url
    with patch.object(engine, "_check_backend", side_effect=check):
        assert engine.is_available() is True


def test_status(engine):
    """Status returns all backend info."""
    with patch.object(engine, "_check_backend", return_value=False):
        s = engine.status()
    assert "available" in s
    assert "proxy" in s
    assert "nexus_nlm" in s
    assert "has_cookies" in s
    assert "stats" in s


# ──── Cookie Management ────

def test_set_cookies(engine):
    """Set and retrieve cookies."""
    engine.set_cookies({"SID": "abc", "HSID": "def"})
    cookies = engine.get_cookies()
    assert cookies["SID"] == "abc"
    assert cookies["HSID"] == "def"


def test_cookies_are_copied(engine):
    """Cookies are copied, not referenced."""
    original = {"SID": "abc"}
    engine.set_cookies(original)
    original["SID"] = "modified"
    assert engine.get_cookies()["SID"] == "abc"


# ──── Notebook Management ────

def test_create_notebook(engine):
    """Create notebook calls POST."""
    with patch.object(engine, "_post_any", return_value={"notebook_id": "nb-123"}) as mock:
        result = engine.create_notebook("Test NB", sources=["https://example.com"])
    assert result["notebook_id"] == "nb-123"
    mock.assert_called_once()
    assert engine._stats.creates == 1


def test_list_notebooks(engine):
    """List returns notebook array."""
    with patch.object(engine, "_get_any", return_value={"notebooks": [{"id": "nb-1"}]}):
        result = engine.list_notebooks()
    assert len(result) == 1
    assert result[0]["id"] == "nb-1"


def test_list_notebooks_empty(engine):
    """List returns empty when no data."""
    with patch.object(engine, "_get_any", return_value={"error": "No backend"}):
        result = engine.list_notebooks()
    assert result == []


def test_delete_notebook(engine):
    """Delete calls DELETE endpoint."""
    with patch.object(engine, "_delete_any", return_value={"success": True}) as mock:
        result = engine.delete_notebook("nb-123")
    assert result["success"] is True


def test_get_notebook(engine):
    """Get returns notebook details."""
    with patch.object(engine, "_get_any", return_value={"id": "nb-123", "name": "Test"}):
        result = engine.get_notebook("nb-123")
    assert result["name"] == "Test"


# ──── Source Management ────

def test_add_source(engine):
    """Add source calls POST with correct payload."""
    with patch.object(engine, "_post_any", return_value={"success": True}) as mock:
        result = engine.add_source("nb-1", "url", "https://example.com")
    assert result["success"] is True
    assert engine._stats.sources_added == 1


def test_add_sources_batch(engine):
    """Batch add calls add_source for each."""
    with patch.object(engine, "_post_any", return_value={"success": True}):
        results = engine.add_sources_batch("nb-1", [
            {"type": "url", "value": "https://a.com"},
            {"type": "text", "value": "some content"},
        ])
    assert len(results) == 2


def test_remove_source(engine):
    """Remove source calls DELETE."""
    with patch.object(engine, "_delete_any", return_value={"success": True}):
        result = engine.remove_source("src-1", notebook_id="nb-1")
    assert result["success"] is True


# ──── Codebase Notebooks ────

def test_create_from_files(engine, tmp_path):
    """Create notebook from source files."""
    (tmp_path / "test.py").write_text("def hello(): pass")

    with patch.object(engine, "create_notebook", return_value={"notebook_id": "nb-code"}):
        with patch.object(engine, "add_source", return_value={"success": True}):
            result = engine.create_from_files(
                [str(tmp_path / "test.py")], "Code Analysis"
            )
    assert result["notebook_id"] == "nb-code"


def test_create_from_files_missing(engine, tmp_path):
    """Handle missing files gracefully."""
    with patch.object(engine, "create_notebook", return_value={"notebook_id": "nb-code"}):
        with patch.object(engine, "add_source", return_value={"success": True}):
            result = engine.create_from_files(
                [str(tmp_path / "missing.py")], "Code"
            )
    assert any("not found" in str(r.get("error", "")) for r in result.get("source_results", []))


# ──── Q&A ────

def test_ask(engine):
    """Ask increments stats and returns answer."""
    with patch.object(engine, "_post_any", return_value={"answer": "42"}):
        result = engine.ask("nb-1", "What is the meaning?")
    assert result["answer"] == "42"
    assert engine._stats.asks == 1
    assert engine._stats.total_questions == 1


def test_ask_error(engine):
    """Ask tracks errors."""
    with patch.object(engine, "_post_any", return_value={"error": "backend down"}):
        result = engine.ask("nb-1", "test?")
    assert "error" in result
    assert engine._stats.errors == 1


def test_ask_batch(engine):
    """Batch ask processes all questions."""
    with patch.object(engine, "_post_any", return_value={"answer": "yes"}):
        results = engine.ask_batch("nb-1", ["Q1?", "Q2?", "Q3?"], delay=0)
    assert len(results) == 3
    assert all(r["answer"]["answer"] == "yes" for r in results)
    assert engine._stats.batch_asks == 1
    assert engine._stats.total_questions == 3


def test_ask_batch_with_progress(engine):
    """Batch ask calls progress callback."""
    progress = []
    def on_progress(cur, total, q):
        progress.append((cur, total, q))

    with patch.object(engine, "_post_any", return_value={"answer": "x"}):
        engine.ask_batch("nb-1", ["A?", "B?"], delay=0, on_progress=on_progress)

    assert len(progress) == 2
    assert progress[0] == (1, 2, "A?")
    assert progress[1] == (2, 2, "B?")


# ──── Generation ────

def test_generate(engine):
    """Generate document calls correct endpoint."""
    with patch.object(engine, "_post_any", return_value={"content": "study guide..."}) as mock:
        result = engine.generate("nb-1", "study_guide", instructions="Focus on security")
    assert result["content"] == "study guide..."
    assert engine._stats.docs_generated == 1


def test_generate_audio(engine):
    """Generate audio tries proxy first."""
    with patch.object(engine, "_try_post", return_value={"status": "generating"}):
        result = engine.generate_audio("nb-1", customization="Focus on deployment")
    assert result["status"] == "generating"


def test_create_note(engine):
    """Create note in notebook."""
    with patch.object(engine, "_post_any", return_value={"success": True}):
        result = engine.create_note("nb-1", "My Note", "Note content")
    assert result["success"] is True


# ──── Backend Fallback ────

def test_post_any_tries_both_backends(engine):
    """POST falls back to second backend if first fails."""
    call_count = 0
    def mock_try_post(base_url, path, payload):
        nonlocal call_count
        call_count += 1
        if "8800" in base_url:
            return None  # proxy down
        return {"success": True}  # nexus nlm works

    with patch.object(engine, "_try_post", side_effect=mock_try_post):
        result = engine._post_any("/test", {})
    assert result["success"] is True
    assert call_count == 2


def test_post_any_no_backend(engine):
    """POST returns error when both backends fail."""
    with patch.object(engine, "_try_post", return_value=None):
        result = engine._post_any("/test", {})
    assert "error" in result
