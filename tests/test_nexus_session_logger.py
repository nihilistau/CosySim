"""Focused tests for Nexus session logger state persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from engine.nexus import nexus_session_logger as logger_mod


def test_handle_start_preserves_existing_knowledge_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Session start should merge metadata instead of overwriting consultation state."""
    session_file = tmp_path / "current_session.json"
    session_file.write_text(
        json.dumps(
            {
                "session_id": "existing-session",
                "nexus_consulted": True,
                "nexus_last_tool": "functions.notebooklm-ask_question",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(logger_mod, "SESSION_FILE", session_file)
    monkeypatch.setattr(logger_mod, "LOG_DIR", tmp_path)
    monkeypatch.setattr(logger_mod, "_find_session_id", lambda: None)
    monkeypatch.setattr(logger_mod, "_get_git_context", lambda: {"branch": "feature/test"})
    monkeypatch.setattr(logger_mod, "_now", lambda: "2026-03-06T12:00:00+00:00")
    monkeypatch.setattr(logger_mod, "_post", lambda *args, **kwargs: None)
    monkeypatch.setattr(logger_mod, "_log_local", lambda *args, **kwargs: None)
    monkeypatch.setattr(logger_mod.os, "getcwd", lambda: str(tmp_path))

    logger_mod.handle_start()

    session = json.loads(session_file.read_text(encoding="utf-8"))
    assert session["session_id"] == "existing-session"
    assert session["nexus_consulted"] is True
    assert session["nexus_last_tool"] == "functions.notebooklm-ask_question"
    assert session["started_at"] == "2026-03-06T12:00:00+00:00"
    assert session["prompts"] == 0


def test_handle_prompt_backfills_session_id_before_saving(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Prompt tracking should capture a discovered Copilot session id for later exports."""
    session_file = tmp_path / "current_session.json"
    session_file.write_text(json.dumps({"prompts": 1}, indent=2), encoding="utf-8")

    monkeypatch.setattr(logger_mod, "SESSION_FILE", session_file)
    monkeypatch.setattr(logger_mod, "LOG_DIR", tmp_path)
    monkeypatch.setattr(logger_mod, "_find_session_id", lambda: "abc123")
    monkeypatch.setattr(logger_mod, "_auto_export_checkpoints", lambda session: None)
    monkeypatch.setattr(logger_mod, "_log_local", lambda *args, **kwargs: None)
    monkeypatch.setattr(logger_mod, "_now", lambda: "2026-03-06T12:30:00+00:00")

    logger_mod.handle_prompt()

    session = json.loads(session_file.read_text(encoding="utf-8"))
    assert session["session_id"] == "abc123"
    assert session["prompts"] == 2
    assert session["last_prompt_at"] == "2026-03-06T12:30:00+00:00"


def test_build_history_entry_includes_knowledge_sync_fields() -> None:
    """Session summaries should capture whether durable knowledge was consulted."""
    summary = logger_mod._build_history_entry(
        {
            "started_at": "start",
            "ended_at": "end",
            "prompts": 4,
            "cwd": "C:/repo",
            "session_id": "copilot-1",
            "nexus_session_id": "nexus-1",
            "nexus_consulted": True,
            "nexus_last_tool": "functions.notebooklm-ask_question",
            "nexus_last_success_at": "2026-03-06T13:00:00Z",
        },
        {"branch": "feature/runtime"},
        {},
    )

    assert "Knowledge consulted: yes" in summary
    assert "Last knowledge tool: functions.notebooklm-ask_question" in summary
    assert "Last knowledge sync: 2026-03-06T13:00:00Z" in summary
    assert "Nexus session ID: nexus-1" in summary


def test_post_routes_entry_writes_through_client(monkeypatch) -> None:
    """Known logger entry writes should prefer the governed Nexus client."""
    client = MagicMock()
    client.add_entry.return_value = "entry-1"

    monkeypatch.setattr(
        "engine.nexus.client.get_nexus_client",
        lambda: client,
        raising=False,
    )

    result = logger_mod._post(
        "/api/entries",
        {
            "title": "Checkpoint",
            "content": "Checkpoint content",
            "content_type": "history",
            "category": "sessions",
            "tags": ["copilot"],
        },
    )

    assert result == {"id": "entry-1", "ok": True}
    client.add_entry.assert_called_once()


def test_handle_checkpoint_stores_context_packet(monkeypatch, tmp_path: Path) -> None:
    """Manual checkpoint export should persist a structured context packet."""
    session_file = tmp_path / "current_session.json"
    session_file.write_text(json.dumps({"prompts": 2}, indent=2), encoding="utf-8")
    posts: list[tuple[str, dict]] = []

    monkeypatch.setattr(logger_mod, "SESSION_FILE", session_file)
    monkeypatch.setattr(logger_mod, "LOG_DIR", tmp_path)
    monkeypatch.setattr(logger_mod, "_find_session_id", lambda: "abc123")
    monkeypatch.setattr(logger_mod, "_auto_export_checkpoints", lambda session: None)
    monkeypatch.setattr(logger_mod, "_get_git_context", lambda: {"branch": "main", "last_commit": "abc"})
    monkeypatch.setattr(
        logger_mod,
        "_get_session_history",
        lambda session_id: {
            "turns": [{"turn": 1, "user": "Do the thing", "assistant": "Decision: Keep hooks active."}],
            "checkpoints": [{"number": 1, "title": "Checkpoint", "overview": "overview", "work_done": "done"}],
            "plan": "Current plan",
        },
    )
    monkeypatch.setattr(logger_mod, "_run_hook_control", lambda *args, **kwargs: {"event": "checkpoint"})
    monkeypatch.setattr(logger_mod, "_log_local", lambda *args, **kwargs: None)
    monkeypatch.setattr(logger_mod, "_now", lambda: "2026-03-07T14:00:00+00:00")

    def _capture_post(path: str, data: dict, timeout: int = 5, method: str = "POST") -> dict:
        posts.append((path, data))
        return {"ok": True, "id": "entry-1"}

    monkeypatch.setattr(logger_mod, "_post", _capture_post)

    logger_mod.handle_checkpoint()

    context_posts = [payload for path, payload in posts if payload["title"].startswith("Copilot Context Packet")]
    assert context_posts
    assert "\"packet_type\": \"checkpoint\"" in context_posts[0]["content"]


def test_handle_compaction_stores_context_packet(monkeypatch, tmp_path: Path) -> None:
    """Compaction export should persist the structured compaction packet."""
    session_file = tmp_path / "current_session.json"
    session_file.write_text(json.dumps({"prompts": 4, "started_at": "start"}, indent=2), encoding="utf-8")
    posts: list[tuple[str, dict]] = []

    monkeypatch.setattr(logger_mod, "SESSION_FILE", session_file)
    monkeypatch.setattr(logger_mod, "LOG_DIR", tmp_path)
    monkeypatch.setattr(logger_mod, "_find_session_id", lambda: "abc123")
    monkeypatch.setattr(logger_mod, "_auto_export_checkpoints", lambda session: None)
    monkeypatch.setattr(logger_mod, "_get_git_context", lambda: {"branch": "main", "last_commit": "abc"})
    monkeypatch.setattr(
        logger_mod,
        "_get_session_history",
        lambda session_id: {
            "turns": [{"turn": 1, "user": "Do the thing", "assistant": "Decision: Keep hooks active."}],
            "checkpoints": [{"number": 1, "title": "Checkpoint", "overview": "overview", "work_done": "done"}],
            "plan": "Current plan",
        },
    )
    monkeypatch.setattr(logger_mod, "_run_hook_control", lambda *args, **kwargs: {"event": "preCompaction"})
    monkeypatch.setattr(logger_mod, "_log_local", lambda *args, **kwargs: None)
    monkeypatch.setattr(logger_mod, "_now", lambda: "2026-03-07T14:05:00+00:00")

    def _capture_post(path: str, data: dict, timeout: int = 5, method: str = "POST") -> dict:
        posts.append((path, data))
        return {"ok": True, "id": "entry-2"}

    monkeypatch.setattr(logger_mod, "_post", _capture_post)

    logger_mod.handle_compaction()

    context_posts = [payload for path, payload in posts if payload["title"].startswith("Copilot Context Packet")]
    assert context_posts
    assert "\"packet_type\": \"compaction\"" in context_posts[0]["content"]
