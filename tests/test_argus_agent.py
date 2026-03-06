"""Tests for ArgusAgent — history mirror, 422 fallback, save/load, anchor batching.

All tests mock httpx and filesystem — no running LMStudio or Chrome required.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ──── Helpers ────────────────────────────────────────────────────────────────

def _make_agent(tmp_path: Path, target: str = "aistudio") -> Any:
    """Create an ArgusAgent with _base_url pointing to nowhere (mocked out)."""
    from scripts.argus.agent import ArgusAgent
    agent = ArgusAgent(target=target, max_turns=5)
    agent._base_url = "http://localhost:19234/api/v1/chat"
    agent._headers = {"Content-Type": "application/json"}
    # Override history path to use tmp dir
    agent.__class__._history_path = property(
        lambda self: tmp_path / f"{self.target}_history.json"
    )
    return agent


# ──── _save_history / _load_history ──────────────────────────────────────────

class TestHistoryPersistence:
    def test_save_creates_file(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        agent._history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        agent._save_history()
        hist_file = tmp_path / "aistudio_history.json"
        assert hist_file.exists()
        data = json.loads(hist_file.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["role"] == "user"

    def test_load_returns_false_when_no_file(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        assert agent._load_history() is False
        assert agent._history == []

    def test_load_restores_history(self, tmp_path: Path) -> None:
        hist_file = tmp_path / "aistudio_history.json"
        payload = [
            {"role": "user", "content": "init msg"},
            {"role": "assistant", "content": "ARGUS READY"},
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "(tool calls)"},
        ]
        hist_file.write_text(json.dumps(payload), encoding="utf-8")
        agent = _make_agent(tmp_path)
        result = agent._load_history()
        assert result is True
        assert len(agent._history) == 4
        assert agent._init_history_len == 4

    def test_load_handles_corrupt_file(self, tmp_path: Path) -> None:
        hist_file = tmp_path / "aistudio_history.json"
        hist_file.write_text("not valid json", encoding="utf-8")
        agent = _make_agent(tmp_path)
        assert agent._load_history() is False

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        original = [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ]
        agent._history = list(original)
        agent._save_history()
        agent2 = _make_agent(tmp_path)
        agent2._load_history()
        assert agent2._history == original

    def test_save_is_utf8_safe(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        agent._history = [{"role": "user", "content": "emoji: 🚀 unicode: ñ"}]
        agent._save_history()  # should not raise
        hist_file = tmp_path / "aistudio_history.json"
        data = json.loads(hist_file.read_text(encoding="utf-8"))
        assert "🚀" in data[0]["content"]


# ──── _init_session ───────────────────────────────────────────────────────────

class TestInitSession:
    def test_seeds_history_with_init_and_ready(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)

        async def _fake_store(text, previous_id=None):
            return "primed-001"

        agent._store_message = _fake_store

        asyncio.run(agent._init_session(["Home", "Playground"]))

        assert agent._primed_id == "primed-001"
        assert agent._progress_id == "primed-001"
        assert len(agent._history) == 2
        assert agent._history[0]["role"] == "user"
        assert agent._history[1]["content"] == "ARGUS READY"
        assert agent._init_history_len == 2

    def test_init_message_contains_sections(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        captured: List[str] = []

        async def _fake_store(text, previous_id=None):
            captured.append(text)
            return "primed-abc"

        agent._store_message = _fake_store
        asyncio.run(agent._init_session(["Home", "Apps", "Tuning"]))

        assert len(captured) == 1
        assert "Home" in captured[0]
        assert "Apps" in captured[0]
        assert "Tuning" in captured[0]


# ──── _advance_anchor ─────────────────────────────────────────────────────────

class TestAdvanceAnchor:
    def test_single_store_call_for_multiple_sections(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        agent._progress_id = "prog-0"
        store_calls: List[Dict] = []

        async def _fake_store(text, previous_id=None):
            store_calls.append({"text": text, "prev": previous_id})
            return "prog-1"

        agent._store_message = _fake_store
        asyncio.run(agent._advance_anchor(
            newly_visited=["Home", "Playground"],
            visited=["Home", "Playground"],
            remaining=["Apps"],
        ))

        # CRITICAL: exactly ONE store call even though 2 sections were visited
        assert len(store_calls) == 1
        assert store_calls[0]["prev"] == "prog-0"
        assert agent._progress_id == "prog-1"

    def test_mirrors_into_history(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        agent._history = [{"role": "user", "content": "init"}, {"role": "assistant", "content": "ARGUS READY"}]
        agent._progress_id = "prog-0"

        async def _fake_store(text, previous_id=None):
            return "prog-1"

        agent._store_message = _fake_store
        asyncio.run(agent._advance_anchor(["Home"], ["Home"], ["Apps"]))

        # History should have 2 new entries (user + assistant)
        assert len(agent._history) == 4
        assert agent._history[2]["role"] == "user"
        assert agent._history[3]["content"] == "ACKNOWLEDGED"

    def test_progress_message_includes_done_sections(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        agent._progress_id = "prog-0"
        captured_texts: List[str] = []

        async def _fake_store(text, previous_id=None):
            captured_texts.append(text)
            return "prog-new"

        agent._store_message = _fake_store
        asyncio.run(agent._advance_anchor(["Files", "Tuning"], ["Home", "Playground", "Files", "Tuning"], []))

        assert "'Files'" in captured_texts[0]
        assert "'Tuning'" in captured_texts[0]
        assert "argus_done" in captured_texts[0]  # no remaining → done

    def test_all_sections_done_message(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        agent._progress_id = "p0"
        captured: List[str] = []

        async def _fake_store(text, previous_id=None):
            captured.append(text)
            return "p1"

        agent._store_message = _fake_store
        asyncio.run(agent._advance_anchor(["Settings"], ["Home", "Settings"], remaining=[]))
        assert "ALL SECTIONS COMPLETE" in captured[0] or "argus_done" in captured[0]


# ──── _build_turn_input ───────────────────────────────────────────────────────

class TestBuildTurnInput:
    def test_turn_0_contains_begin(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        sections = ["Home", "Playground", "Apps"]
        msg = agent._build_turn_input(0, sections, current_url="https://aistudio.google.com/")
        assert "BEGIN" in msg
        assert "Home" in msg

    def test_loop_killed_message(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        sections = ["Home", "Playground"]
        msg = agent._build_turn_input(1, sections, loop_killed=True, remaining=["Playground"])
        assert "LOOP INTERRUPTED" in msg

    def test_all_done_message(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        msg = agent._build_turn_input(3, ["Home"], remaining=[])
        assert "argus_done" in msg or "done" in msg.lower()

    def test_normal_turn_has_section_hint(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        sections = ["Home", "Apps"]
        msg = agent._build_turn_input(2, sections, remaining=["Apps"])
        assert "Apps" in msg

    def test_vision_context_injected_on_loop_kill(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        sections = ["Home", "Playground"]
        msg = agent._build_turn_input(
            2, sections,
            loop_killed=True,
            remaining=["Playground"],
            vision_context="Chrome shows a 'Session expired' modal with a Reload button.",
        )
        assert "LOOP INTERRUPTED" in msg
        assert "Session expired" in msg
        assert "VISION" in msg

    def test_vision_context_injected_on_normal_turn(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        sections = ["Home", "Apps"]
        msg = agent._build_turn_input(
            2, sections,
            remaining=["Apps"],
            vision_context="Chrome is showing a loading spinner on the Apps page.",
        )
        assert "Apps" in msg
        assert "loading spinner" in msg
        assert "VISION" in msg

    def test_no_vision_context_no_vision_prefix(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        msg = agent._build_turn_input(1, ["Home", "Apps"], remaining=["Apps"])
        assert "VISION" not in msg


# ──── _post_turn — 422 fallback ───────────────────────────────────────────────

class TestPostTurn422Fallback:
    """Verify that a 422 response triggers history-array fallback on retry."""

    def _sse_lines(self, response_id: str = "resp-abc") -> bytes:
        """Minimal SSE stream: chat.end event with a response_id."""
        body = (
            f"event: chat.end\n"
            f'data: {{"result": {{"response_id": "{response_id}", "output": [{{"type": "text", "text": "OK"}}]}}}}\n\n'
        )
        return body.encode()

    def test_422_triggers_fallback_and_retries(self, tmp_path: Path) -> None:
        """First response is 422 → retry with history array → success."""
        agent = _make_agent(tmp_path)
        agent._primed_id = "primed-001"
        agent._progress_id = "prog-001"
        agent._history = [
            {"role": "user", "content": "init"},
            {"role": "assistant", "content": "ARGUS READY"},
        ]

        call_count = 0
        payloads_sent: List[Dict] = []

        async def _run():
            nonlocal call_count

            class FakeResp422:
                status_code = 422
                headers = {}
                async def aclose(self): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass

            class FakeRespOK:
                status_code = 200
                headers = {}
                async def aclose(self): pass
                async def aiter_lines(self):
                    lines = [
                        "event: chat.end",
                        'data: {"result": {"response_id": "resp-ok", "output": [{"type": "text", "text": "done"}]}}',
                        "",
                    ]
                    for line in lines:
                        yield line
                def raise_for_status(self): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass

            class FakeClient:
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass
                def stream(self, method, url, json=None):
                    nonlocal call_count
                    payloads_sent.append(json or {})
                    call_count += 1
                    if call_count == 1:
                        return FakeResp422()
                    return FakeRespOK()

            with patch("scripts.argus.agent.httpx.AsyncClient", return_value=FakeClient()):
                return await agent._post_turn(0, "navigate to Home")

        result = asyncio.run(_run())
        assert call_count == 2
        # Second call should use history array as input, not string
        assert isinstance(payloads_sent[1].get("input"), list)
        assert "previous_response_id" not in payloads_sent[1]

    def test_successful_turn_mirrors_into_history(self, tmp_path: Path) -> None:
        """A successful turn appends user + assistant entries to _history."""
        agent = _make_agent(tmp_path)
        agent._primed_id = "primed-001"
        agent._progress_id = "prog-001"
        agent._history = [
            {"role": "user", "content": "init"},
            {"role": "assistant", "content": "ARGUS READY"},
        ]
        initial_len = len(agent._history)

        async def _run():
            class FakeRespOK:
                status_code = 200
                async def aclose(self): pass
                async def aiter_lines(self):
                    for line in [
                        "event: chat.end",
                        'data: {"result": {"response_id": "resp-123", "output": [{"type": "text", "text": "navigated"}]}}',
                        "",
                    ]:
                        yield line
                def raise_for_status(self): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass

            class FakeClient:
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass
                def stream(self, *a, **kw): return FakeRespOK()

            with patch("scripts.argus.agent.httpx.AsyncClient", return_value=FakeClient()):
                return await agent._post_turn(1, "go to Playground")

        asyncio.run(_run())
        # Two new entries: user + assistant
        assert len(agent._history) == initial_len + 2
        assert agent._history[-2]["content"] == "go to Playground"
        assert agent._history[-1]["content"] == "navigated"

    def test_loop_killed_turn_does_not_mirror_history(self, tmp_path: Path) -> None:
        """A loop-killed turn (stream aborted) should NOT be mirrored."""
        agent = _make_agent(tmp_path)
        agent._primed_id = "p0"
        agent._progress_id = "p0"
        agent._history = [{"role": "user", "content": "init"}, {"role": "assistant", "content": "READY"}]
        initial_len = len(agent._history)

        async def _run():
            class FakeRespLoop:
                status_code = 200
                _closed = False
                async def aclose(self): self._closed = True
                async def aiter_lines(self):
                    # Emit same tool 4 times to trigger loop kill
                    for _ in range(5):
                        yield "event: tool_call.arguments"
                        yield 'data: {"tool": "argus_screenshot", "arguments": {"url": "x"}}'
                        yield ""
                def raise_for_status(self): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass

            class FakeClient:
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass
                def stream(self, *a, **kw): return FakeRespLoop()

            with patch("scripts.argus.agent.httpx.AsyncClient", return_value=FakeClient()):
                return await agent._post_turn(2, "continue")

        result = asyncio.run(_run())
        assert result["loop_killed"] is True
        # History unchanged
        assert len(agent._history) == initial_len


# ──── _store_message ─────────────────────────────────────────────────────────

class TestStoreMessage:
    def test_returns_response_id(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)

        async def _run():
            class FakeResp:
                status_code = 200
                def raise_for_status(self): pass
                def json(self): return {"response_id": "stored-001"}

            class FakeClient:
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass
                async def post(self, *a, **kw): return FakeResp()

            with patch("scripts.argus.agent.httpx.AsyncClient", return_value=FakeClient()):
                return await agent._store_message("hello world")

        rid = asyncio.run(_run())
        assert rid == "stored-001"

    def test_includes_previous_id_in_payload(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        captured: List[Dict] = []

        async def _run():
            class FakeResp:
                status_code = 200
                def raise_for_status(self): pass
                def json(self): return {"response_id": "r2"}

            class FakeClient:
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass
                async def post(self, url, json=None, **kw):
                    captured.append(json or {})
                    return FakeResp()

            with patch("scripts.argus.agent.httpx.AsyncClient", return_value=FakeClient()):
                return await agent._store_message("update", previous_id="prev-123")

        asyncio.run(_run())
        assert captured[0].get("previous_response_id") == "prev-123"
        assert captured[0].get("store") is True
