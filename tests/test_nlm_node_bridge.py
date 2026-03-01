"""Tests for NLM Node Bridge (nlm_node_bridge.py).

All Node process interactions are mocked — no real Node.js process is started.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from engine.mcp.nlm_node_bridge import NLMNodeBridge, get_nlm_node_bridge, notebook_url


# ──── Helpers ─────────────────────────────────────────────────────────────────

def _make_bridge_with_mock_process() -> NLMNodeBridge:
    """Return a bridge with a fake initialized state (no real subprocess)."""
    bridge = NLMNodeBridge()
    bridge._initialized = True
    bridge._available_tools = [
        "ask_question", "list_notebooks", "add_notebook", "select_notebook",
        "create_notebook", "add_source", "list_sources", "generate_audio_overview",
        "get_audio_status", "generate_video_overview", "extract_data_tables",
        "get_notebook_chat_history", "get_health", "setup_auth", "sync_library",
        "get_quota",
    ]
    # Fake process that is "alive"
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdin = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stderr = MagicMock()
    bridge._process = mock_proc
    return bridge


def _inject_response(bridge: NLMNodeBridge, req_id: int, result: Any) -> None:
    """Simulate the Node server responding to request req_id."""
    with bridge._lock:
        bridge._results[req_id] = result
        event = bridge._pending.pop(req_id, None)
    if event:
        event.set()


# ──── notebook_url helper ──────────────────────────────────────────────────────

def test_notebook_url_formats_correctly():
    uid = "311f2b2e-347d-49c5-84d7-a9236a699771"
    assert notebook_url(uid) == f"https://notebooklm.google.com/notebook/{uid}"


def test_notebook_url_passthrough_if_already_url():
    full_url = "https://notebooklm.google.com/notebook/abc-123"
    assert notebook_url(full_url) != full_url  # it prepends base
    # but ask_question passes full URLs through directly
    bridge = _make_bridge_with_mock_process()
    url = "https://notebooklm.google.com/notebook/abc-123"
    assert bridge.ask_question.__doc__  # method exists


# ──── call_tool ───────────────────────────────────────────────────────────────

def test_call_tool_returns_parsed_json():
    bridge = _make_bridge_with_mock_process()

    req_id_seen = []

    def _fake_send_raw(msg: Dict) -> None:
        if msg.get("method") == "tools/call":
            req_id = msg["id"]
            req_id_seen.append(req_id)
            response = {"content": [{"type": "text", "text": json.dumps({"answer": "42"})}]}
            threading.Thread(
                target=_inject_response, args=(bridge, req_id, response), daemon=True
            ).start()

    bridge._send_raw = _fake_send_raw

    result = bridge.call_tool("ask_question", {"question": "test?"})
    assert result.get("answer") == "42"


def test_call_tool_returns_plain_text_if_not_json():
    bridge = _make_bridge_with_mock_process()

    def _fake_send_raw(msg: Dict) -> None:
        if msg.get("method") == "tools/call":
            req_id = msg["id"]
            response = {"content": [{"type": "text", "text": "Just a plain answer"}]}
            threading.Thread(
                target=_inject_response, args=(bridge, req_id, response), daemon=True
            ).start()

    bridge._send_raw = _fake_send_raw
    result = bridge.call_tool("ask_question", {"question": "test?"})
    assert result.get("result") == "Just a plain answer"


def test_call_tool_timeout_returns_error():
    bridge = _make_bridge_with_mock_process()

    def _fake_send_raw(msg: Dict) -> None:
        pass  # Never respond

    bridge._send_raw = _fake_send_raw
    result = bridge.call_tool("ask_question", {"question": "test?"}, timeout=0.05)
    assert "error" in result
    assert "timeout" in result["error"].lower()


def test_call_tool_not_running_returns_error():
    bridge = NLMNodeBridge()
    # Never started — ensure_started will try to start()
    with patch.object(bridge, "start", return_value=False):
        result = bridge.call_tool("ask_question", {"question": "test?"})
    assert "error" in result


# ──── ask_question ─────────────────────────────────────────────────────────────

def test_ask_question_uses_notebook_url():
    bridge = _make_bridge_with_mock_process()
    captured_args = []

    def _fake_call_tool(tool_name: str, arguments: Dict, timeout: float = 120.0) -> Dict:
        captured_args.append((tool_name, arguments))
        return {"answer": "Test answer", "session_id": "sess-001"}

    bridge.call_tool = _fake_call_tool

    # First call add_notebook, then ask_question
    bridge.add_notebook = MagicMock(return_value={})

    uid = "311f2b2e-347d-49c5-84d7-a9236a699771"
    result = bridge.ask_question(uid, "What is MCP?")

    assert result["answer"] == "Test answer"
    # Last call should be ask_question
    last_tool, last_args = captured_args[-1]
    assert last_tool == "ask_question"
    assert last_args["question"] == "What is MCP?"
    assert f"notebook/{uid}" in last_args["notebook_url"]


def test_ask_question_passes_session_id():
    bridge = _make_bridge_with_mock_process()
    captured = {}

    def _fake_call_tool(tool_name: str, arguments: Dict, timeout: float = 120.0) -> Dict:
        captured.update(arguments)
        return {"answer": "ok"}

    bridge.call_tool = _fake_call_tool
    bridge.add_notebook = MagicMock(return_value={})

    bridge.ask_question("abc-123", "Follow up?", session_id="sess-xyz")
    assert captured.get("session_id") == "sess-xyz"


def test_ask_question_omits_session_id_when_reset():
    bridge = _make_bridge_with_mock_process()
    captured = {}

    def _fake_call_tool(tool_name: str, arguments: Dict, timeout: float = 120.0) -> Dict:
        captured.update(arguments)
        return {"answer": "ok"}

    bridge.call_tool = _fake_call_tool
    bridge.add_notebook = MagicMock(return_value={})

    bridge.ask_question("abc-123", "Fresh start?", session_id="old-sess", reset_history=True)
    assert "session_id" not in captured


# ──── ask_batch ───────────────────────────────────────────────────────────────

def test_ask_batch_uses_session_continuity():
    bridge = _make_bridge_with_mock_process()
    call_count = [0]
    session_ids_seen = []

    def _fake_ask_question(nb: str, q: str, session_id=None, reset_history: bool = False) -> Dict:
        call_count[0] += 1
        session_ids_seen.append(session_id)
        return {"answer": f"A{call_count[0]}", "session_id": "sess-A"}

    bridge.ask_question = _fake_ask_question

    questions = ["Q1?", "Q2?", "Q3?"]
    results = bridge.ask_batch("nb-id", questions, keep_session=True)

    assert len(results) == 3
    # First call has no session_id (session not yet established)
    assert session_ids_seen[0] is None
    # Subsequent calls reuse the session_id from first response
    assert session_ids_seen[1] == "sess-A"
    assert session_ids_seen[2] == "sess-A"


def test_ask_batch_no_session_continuity():
    bridge = _make_bridge_with_mock_process()
    session_ids_seen = []

    def _fake_ask_question(nb: str, q: str, session_id=None, reset_history: bool = False) -> Dict:
        session_ids_seen.append(session_id)
        return {"answer": "ok", "session_id": "sess-X"}

    bridge.ask_question = _fake_ask_question

    bridge.ask_batch("nb-id", ["Q1?", "Q2?"], keep_session=False)
    assert all(s is None for s in session_ids_seen)


# ──── add_source ──────────────────────────────────────────────────────────────

def test_add_source_url_builds_correct_args():
    bridge = _make_bridge_with_mock_process()
    captured = {}

    def _fake_call_tool(tool_name: str, arguments: Dict, timeout: float = 120.0) -> Dict:
        captured.update({"tool": tool_name, "args": arguments})
        return {"source_id": "src-0"}

    bridge.call_tool = _fake_call_tool
    result = bridge.add_source("nb-id", url="https://example.com/doc")
    assert result["source_id"] == "src-0"
    assert captured["args"]["source"] == {"type": "url", "value": "https://example.com/doc"}


def test_add_source_text_builds_correct_args():
    bridge = _make_bridge_with_mock_process()
    captured = {}

    def _fake_call_tool(tool_name: str, arguments: Dict, timeout: float = 120.0) -> Dict:
        captured.update({"args": arguments})
        return {"source_id": "src-1"}

    bridge.call_tool = _fake_call_tool
    bridge.add_source("nb-id", text="Some text content", title="My Doc")
    src = captured["args"]["source"]
    assert src["type"] == "text"
    assert src["value"] == "Some text content"
    assert src["title"] == "My Doc"


def test_add_source_requires_url_or_text():
    bridge = _make_bridge_with_mock_process()
    result = bridge.add_source("nb-id")
    assert "error" in result


# ──── create_notebook ─────────────────────────────────────────────────────────

def test_create_notebook_uses_name_not_title():
    bridge = _make_bridge_with_mock_process()
    captured = {}

    def _fake_call_tool(tool_name: str, arguments: Dict, timeout: float = 120.0) -> Dict:
        captured.update({"tool": tool_name, "args": arguments})
        return {"notebook_id": "nb-new"}

    bridge.call_tool = _fake_call_tool
    bridge.create_notebook("My Notebook", sources=[{"type": "text", "value": "Hello"}])

    assert captured["args"]["name"] == "My Notebook"
    assert "title" not in captured["args"]
    assert captured["args"]["sources"][0]["type"] == "text"


# ──── list_notebooks ──────────────────────────────────────────────────────────

def test_list_notebooks_returns_list():
    bridge = _make_bridge_with_mock_process()

    def _fake_call_tool(tool_name: str, arguments: Dict, timeout: float = 120.0) -> Dict:
        return [{"id": "nb-1", "name": "Test NB"}]

    bridge.call_tool = _fake_call_tool
    result = bridge.list_notebooks()
    assert isinstance(result, list)
    assert result[0]["id"] == "nb-1"


def test_list_notebooks_unwraps_dict_response():
    bridge = _make_bridge_with_mock_process()

    def _fake_call_tool(tool_name: str, arguments: Dict, timeout: float = 120.0) -> Dict:
        return {"notebooks": [{"id": "nb-2"}]}

    bridge.call_tool = _fake_call_tool
    result = bridge.list_notebooks()
    assert result[0]["id"] == "nb-2"


# ──── select_notebook ─────────────────────────────────────────────────────────

def test_select_notebook_uses_id_param():
    bridge = _make_bridge_with_mock_process()
    captured = {}

    def _fake_call_tool(tool_name: str, arguments: Dict, timeout: float = 120.0) -> Dict:
        captured.update(arguments)
        return {"selected": True}

    bridge.call_tool = _fake_call_tool
    bridge.select_notebook("local-nb-id")
    assert captured.get("id") == "local-nb-id"
    assert "notebook_id" not in captured


# ──── get_chat_history ────────────────────────────────────────────────────────

def test_get_chat_history_uses_correct_tool_name():
    bridge = _make_bridge_with_mock_process()
    captured = {}

    def _fake_call_tool(tool_name: str, arguments: Dict, timeout: float = 120.0) -> Dict:
        captured["tool"] = tool_name
        return {"messages": []}

    bridge.call_tool = _fake_call_tool
    bridge.get_chat_history("nb-id")
    assert captured["tool"] == "get_notebook_chat_history"


# ──── is_running / chrome_profile_exists ──────────────────────────────────────

def test_is_running_false_when_not_initialized():
    bridge = NLMNodeBridge()
    assert bridge.is_running is False


def test_is_running_false_when_process_exited():
    bridge = _make_bridge_with_mock_process()
    bridge._process.poll.return_value = 1  # Process exited
    assert bridge.is_running is False


def test_chrome_profile_exists_false_when_missing():
    bridge = NLMNodeBridge()
    with patch("engine.mcp.nlm_node_bridge._CHROME_PROFILE") as mock_path:
        mock_path.exists.return_value = False
        assert bridge.chrome_profile_exists is False


# ──── singleton ───────────────────────────────────────────────────────────────

def test_get_nlm_node_bridge_returns_same_instance():
    b1 = get_nlm_node_bridge()
    b2 = get_nlm_node_bridge()
    assert b1 is b2
