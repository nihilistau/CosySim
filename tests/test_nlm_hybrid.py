"""Tests for NLM Hybrid Router (nlm_hybrid.py).

All external backends are mocked — no real process or HTTP calls.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from engine.mcp.nlm_hybrid import NLMHybrid, get_nlm_hybrid


# ──── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def hybrid():
    """Fresh NLMHybrid instance with mocked Node bridge."""
    h = NLMHybrid()
    mock_node = MagicMock()
    mock_node.is_running = True
    mock_node.ensure_started.return_value = True
    mock_node.chrome_profile_exists = True
    mock_node.list_available_tools.return_value = ["ask_question"] * 33
    h._node = mock_node
    return h


# ──── ask ────────────────────────────────────────────────────────────────────

def test_ask_delegates_to_node_bridge(hybrid):
    hybrid._node.ask_question.return_value = {"answer": "42", "session_id": "s1"}
    result = hybrid.ask("nb-uuid", "What is MCP?")
    assert result["answer"] == "42"
    hybrid._node.ask_question.assert_called_once()


def test_ask_passes_session_id(hybrid):
    hybrid._node.ask_question.return_value = {"answer": "ok"}
    hybrid.ask("nb-uuid", "Follow up?", session_id="old-sess")
    _, kwargs = hybrid._node.ask_question.call_args
    assert kwargs.get("session_id") == "old-sess"


def test_ask_reset_history_clears_session(hybrid):
    hybrid._node.ask_question.return_value = {"answer": "fresh"}
    hybrid.ask("nb-uuid", "New topic?", reset_history=True, session_id="stale-sess")
    _, kwargs = hybrid._node.ask_question.call_args
    assert kwargs.get("session_id") is None


def test_ask_returns_error_when_node_unavailable():
    h = NLMHybrid()
    mock_node = MagicMock()
    mock_node.ensure_started.return_value = False
    h._node = mock_node
    result = h.ask("nb-uuid", "Test?")
    assert "error" in result


# ──── ask_batch ───────────────────────────────────────────────────────────────

def test_ask_batch_delegates_to_node(hybrid):
    hybrid._node.ask_batch.return_value = [
        {"answer": "A1"}, {"answer": "A2"}
    ]
    results = hybrid.ask_batch("nb-uuid", ["Q1?", "Q2?"])
    assert len(results) == 2
    assert results[0]["answer"] == "A1"


def test_ask_batch_returns_errors_when_node_unavailable():
    h = NLMHybrid()
    mock_node = MagicMock()
    mock_node.ensure_started.return_value = False
    h._node = mock_node
    results = h.ask_batch("nb-uuid", ["Q1?", "Q2?", "Q3?"])
    assert len(results) == 3
    assert all("error" in r for r in results)


# ──── add_text_source ─────────────────────────────────────────────────────────

def test_add_text_source_uses_proxy_first(hybrid):
    with patch.object(hybrid, "_proxy_post", return_value={"source_id": "s1"}) as mock_post:
        result = hybrid.add_text_source("nb-uuid", "Doc Title", "Content here")
    assert result["source_id"] == "s1"
    mock_post.assert_called_once()


def test_add_text_source_falls_back_to_node_on_proxy_failure(hybrid):
    with patch.object(hybrid, "_proxy_post", return_value={"error": "unreachable"}):
        hybrid._node.add_source.return_value = {"source_id": "s-node"}
        result = hybrid.add_text_source("nb-uuid", "Title", "Text")
    assert result["source_id"] == "s-node"
    hybrid._node.add_source.assert_called_once()


# ──── add_url_source ──────────────────────────────────────────────────────────

def test_add_url_source_uses_proxy_first(hybrid):
    with patch.object(hybrid, "_proxy_post", return_value={"source_id": "s2"}) as mock_post:
        result = hybrid.add_url_source("nb-uuid", "https://example.com/doc")
    assert result["source_id"] == "s2"
    mock_post.assert_called_once()


def test_add_url_source_falls_back_to_node(hybrid):
    with patch.object(hybrid, "_proxy_post", return_value={"error": "500"}):
        hybrid._node.add_source.return_value = {"source_id": "s-url-node"}
        result = hybrid.add_url_source("nb-uuid", "https://example.com")
    assert result["source_id"] == "s-url-node"


# ──── generate_audio ──────────────────────────────────────────────────────────

def test_generate_audio_uses_node(hybrid):
    hybrid._node.generate_audio_overview.return_value = {"status": "generating"}
    result = hybrid.generate_audio("nb-uuid")
    assert result["status"] == "generating"
    hybrid._node.generate_audio_overview.assert_called_once_with("nb-uuid", "standard")


# ──── generate_video ──────────────────────────────────────────────────────────

def test_generate_video_uses_node(hybrid):
    hybrid._node.generate_video_overview.return_value = {"video_id": "vid-1"}
    result = hybrid.generate_video("nb-uuid", style="documentary")
    hybrid._node.generate_video_overview.assert_called_once_with("nb-uuid", "documentary")
    assert result["video_id"] == "vid-1"


# ──── extract_tables ──────────────────────────────────────────────────────────

def test_extract_tables_uses_node(hybrid):
    hybrid._node.extract_data_tables.return_value = {"tables": [{"headers": ["A", "B"]}]}
    result = hybrid.extract_tables("nb-uuid", query="revenue")
    assert "tables" in result
    hybrid._node.extract_data_tables.assert_called_once_with("nb-uuid", "revenue")


# ──── health ─────────────────────────────────────────────────────────────────

def test_health_combines_node_and_proxy_status(hybrid):
    hybrid._node.is_running = True
    hybrid._node.get_health.return_value = {"status": "ok"}
    with patch("urllib.request.urlopen") as mock_urlopen:
        import io
        import json
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value.read.return_value = json.dumps({"status": "running"}).encode()
        result = hybrid.health()
    assert "node_bridge" in result
    assert "batchexecute_proxy" in result


def test_health_handles_proxy_unreachable(hybrid):
    hybrid._node.is_running = True
    hybrid._node.get_health.return_value = {"status": "ok"}
    with patch("urllib.request.urlopen", side_effect=Exception("refused")):
        result = hybrid.health()
    assert result["batchexecute_proxy"]["status"] == "unreachable"


# ──── _proxy_post ─────────────────────────────────────────────────────────────

def test_proxy_post_returns_error_on_connection_failure(hybrid):
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        result = hybrid._proxy_post("/notebooks/x/sources/text", {})
    assert "error" in result


def test_proxy_post_posts_to_correct_path(hybrid):
    import json as _json

    captured = {}

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return _json.dumps({"ok": True}).encode()

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _FakeResp()
        result = hybrid._proxy_post("/notebooks/nb-1/sources/text", {"title": "T"})

    assert result.get("ok") is True


# ──── singleton ───────────────────────────────────────────────────────────────

def test_get_nlm_hybrid_returns_same_instance():
    h1 = get_nlm_hybrid()
    h2 = get_nlm_hybrid()
    assert h1 is h2
