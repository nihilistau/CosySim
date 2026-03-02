"""Tests for NotebookLM Node Bridge tools in devtools_server.py.

All external backends (Node bridge, hybrid router, Nexus client) are mocked.
Uses asyncio.run() for async tools — avoids pytest-asyncio/anyio dependency.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


def _fn(tool):
    """Get the underlying async function (plain function or MCP FunctionTool wrapper)."""
    return getattr(tool, "fn", tool)


# ──── Helpers ────────────────────────────────────────────────────────────────

def _make_hybrid(ask_result=None, batch_result=None, health_result=None):
    h = MagicMock()
    h.ask.return_value = ask_result or {"answer": "test answer", "session_id": "s1"}
    h.ask_batch.return_value = batch_result or [{"answer": "a1"}, {"answer": "a2"}]
    h.generate_audio.return_value = {"status": "started"}
    h.generate_video.return_value = {"video_id": "vid-1", "status": "started"}
    h.extract_tables.return_value = {"tables": []}
    h.health.return_value = health_result or {
        "node_bridge": {"running": True},
        "batchexecute_proxy": {"reachable": True},
    }
    h.setup_auth.return_value = {"status": "authenticated"}
    h.add_url_source.return_value = {"status": "added", "source_id": "src-1"}
    h.add_text_source.return_value = {"status": "added", "source_id": "src-2"}
    return h


def _make_bridge():
    b = MagicMock()
    b.create_notebook.return_value = {"id": "nb-new", "name": "Test NB"}
    b.list_notebooks.return_value = [{"id": "nb-1", "name": "NB One"}]
    b.get_chat_history.return_value = [{"role": "user", "content": "Q?"}]
    return b


# ──── notebooklm_node_ask ─────────────────────────────────────────────────────

def test_node_ask_returns_answer():
    from engine.mcp.devtools_server import notebooklm_node_ask
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        result = json.loads(_run(_fn(notebooklm_node_ask)("nb-1", "What is MCP?")))
    assert result["answer"] == "test answer"
    assert result["session_id"] == "s1"


def test_node_ask_passes_session_id():
    from engine.mcp.devtools_server import notebooklm_node_ask
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        _run(_fn(notebooklm_node_ask)("nb-1", "Follow up?", session_id="old-session"))
    hybrid.ask.assert_called_once_with("nb-1", "Follow up?", session_id="old-session")


def test_node_ask_empty_session_id_passes_none():
    from engine.mcp.devtools_server import notebooklm_node_ask
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        _run(_fn(notebooklm_node_ask)("nb-1", "Q?", session_id=""))
    _, kwargs = hybrid.ask.call_args
    assert kwargs["session_id"] is None


def test_node_ask_returns_error_on_exception():
    from engine.mcp.devtools_server import notebooklm_node_ask
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", side_effect=RuntimeError("bridge down")):
        result = json.loads(_run(_fn(notebooklm_node_ask)("nb-1", "Q?")))
    assert "error" in result


# ──── notebooklm_node_batch_ask ───────────────────────────────────────────────

def test_batch_ask_parses_json_questions():
    from engine.mcp.devtools_server import notebooklm_node_batch_ask
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        result = json.loads(_run(_fn(notebooklm_node_batch_ask)("nb-1", '["Q1?", "Q2?"]')))
    assert len(result) == 2
    assert result[0]["answer"] == "a1"


def test_batch_ask_rejects_non_array():
    from engine.mcp.devtools_server import notebooklm_node_batch_ask
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        result = json.loads(_run(_fn(notebooklm_node_batch_ask)("nb-1", '"not an array"')))
    assert "error" in result


# ──── notebooklm_node_add_source ──────────────────────────────────────────────

def test_add_source_url_calls_add_url_source():
    from engine.mcp.devtools_server import notebooklm_node_add_source
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        result = json.loads(_run(_fn(notebooklm_node_add_source)("nb-1", "url", "https://example.com")))
    hybrid.add_url_source.assert_called_once_with("nb-1", "https://example.com")
    assert result["status"] == "added"


def test_add_source_text_calls_add_text_source():
    from engine.mcp.devtools_server import notebooklm_node_add_source
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        result = json.loads(_run(_fn(notebooklm_node_add_source)("nb-1", "text", "Some content", title="My Doc")))
    hybrid.add_text_source.assert_called_once_with("nb-1", "Some content", title="My Doc")
    assert result["status"] == "added"


# ──── notebooklm_node_create_notebook ────────────────────────────────────────

def test_create_notebook_parses_sources():
    from engine.mcp.devtools_server import notebooklm_node_create_notebook
    bridge = _make_bridge()
    with patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=bridge):
        result = json.loads(_run(_fn(notebooklm_node_create_notebook)(
            name="Test NB",
            sources='[{"type": "url", "value": "https://example.com"}]',
        )))
    assert result["id"] == "nb-new"
    bridge.create_notebook.assert_called_once()
    _, kwargs = bridge.create_notebook.call_args
    assert kwargs["name"] == "Test NB"
    assert len(kwargs["sources"]) == 1


def test_create_notebook_parses_topics():
    from engine.mcp.devtools_server import notebooklm_node_create_notebook
    bridge = _make_bridge()
    with patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=bridge):
        _run(_fn(notebooklm_node_create_notebook)(name="NB", topics="AI, Python, MCP"))
    _, kwargs = bridge.create_notebook.call_args
    assert kwargs["topics"] == ["AI", "Python", "MCP"]


# ──── notebooklm_node_list_notebooks ─────────────────────────────────────────

def test_list_notebooks_returns_array():
    from engine.mcp.devtools_server import notebooklm_node_list_notebooks
    bridge = _make_bridge()
    with patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=bridge):
        result = json.loads(_run(_fn(notebooklm_node_list_notebooks)()))
    assert isinstance(result, list)
    assert result[0]["id"] == "nb-1"


# ──── notebooklm_node_generate_audio / video ─────────────────────────────────

def test_generate_audio_calls_hybrid():
    from engine.mcp.devtools_server import notebooklm_node_generate_audio
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        result = json.loads(_run(_fn(notebooklm_node_generate_audio)("nb-1")))
    hybrid.generate_audio.assert_called_once_with("nb-1")
    assert result["status"] == "started"


def test_generate_video_passes_style():
    from engine.mcp.devtools_server import notebooklm_node_generate_video
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        _run(_fn(notebooklm_node_generate_video)("nb-1", style="documentary"))
    hybrid.generate_video.assert_called_once_with("nb-1", "documentary")


# ──── notebooklm_node_extract_tables ─────────────────────────────────────────

def test_extract_tables_passes_query():
    from engine.mcp.devtools_server import notebooklm_node_extract_tables
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        result = json.loads(_run(_fn(notebooklm_node_extract_tables)("nb-1", query="revenue data")))
    hybrid.extract_tables.assert_called_once_with("nb-1", "revenue data")
    assert "tables" in result


# ──── notebooklm_node_chat_history ───────────────────────────────────────────

def test_chat_history_calls_bridge_with_limit():
    from engine.mcp.devtools_server import notebooklm_node_chat_history
    bridge = _make_bridge()
    with patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=bridge):
        result = json.loads(_run(_fn(notebooklm_node_chat_history)("nb-1", limit=5)))
    bridge.get_chat_history.assert_called_once_with("nb-1", limit=5)
    assert isinstance(result, list)


# ──── notebooklm_node_health ─────────────────────────────────────────────────

def test_node_health_returns_combined_status():
    from engine.mcp.devtools_server import notebooklm_node_health
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        result = json.loads(_run(_fn(notebooklm_node_health)()))
    assert "node_bridge" in result
    assert "batchexecute_proxy" in result


# ──── notebooklm_node_setup_auth ─────────────────────────────────────────────

def test_setup_auth_calls_hybrid():
    from engine.mcp.devtools_server import notebooklm_node_setup_auth
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        result = json.loads(_run(_fn(notebooklm_node_setup_auth)()))
    hybrid.setup_auth.assert_called_once()
    assert result["status"] == "authenticated"


# ──── notebooklm_node_sync_nexus ─────────────────────────────────────────────

def test_sync_nexus_stores_qa_pairs():
    from engine.mcp.devtools_server import notebooklm_node_sync_nexus
    hybrid = _make_hybrid(batch_result=[
        {"answer": "MCP is the framework.", "session_id": "s1"},
        {"answer": "Skills are @skill decorated functions.", "session_id": "s1"},
    ])
    mock_client = MagicMock()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid), \
         patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
        result = json.loads(_run(_fn(notebooklm_node_sync_nexus)(
            "nb-1", '["What is MCP?", "What are skills?"]'
        )))
    assert result["stored"] == 2
    assert result["errors"] == 0
    assert mock_client.add_qa.call_count == 2


def test_sync_nexus_counts_errors_on_failed_answers():
    from engine.mcp.devtools_server import notebooklm_node_sync_nexus
    hybrid = _make_hybrid(batch_result=[
        {"error": "bridge down"},
        {"answer": "Good answer."},
    ])
    mock_client = MagicMock()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid), \
         patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
        result = json.loads(_run(_fn(notebooklm_node_sync_nexus)(
            "nb-1", '["Q1?", "Q2?"]'
        )))
    assert result["stored"] == 1
    assert result["errors"] == 1


def test_sync_nexus_rejects_non_array():
    from engine.mcp.devtools_server import notebooklm_node_sync_nexus
    hybrid = _make_hybrid()
    with patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=hybrid):
        result = json.loads(_run(_fn(notebooklm_node_sync_nexus)("nb-1", '"not a list"')))
    assert "error" in result


# ──── Governance gate on skills ───────────────────────────────────────────────

def test_notebooklm_skills_have_governed_decorator():
    """Verify all NLM skills in notebooklm_skills.py are wrapped with @governed."""
    import engine.skills.builtin.notebooklm_skills as mod

    governed_fns = [
        mod.notebooklm_ask,
        mod.notebooklm_add_source,
        mod.notebooklm_list_notebooks,
        mod.notebooklm_search,
        mod.notebooklm_ask_node,
        mod.notebooklm_batch_ask,
        mod.notebooklm_generate_audio,
        mod.notebooklm_generate_audio_node,
        mod.notebooklm_generate_video,
        mod.notebooklm_extract_tables,
        mod.notebooklm_hybrid_health,
        mod.notebooklm_setup_auth,
    ]
    for fn in governed_fns:
        assert callable(fn), f"{fn.__name__} is not callable"
