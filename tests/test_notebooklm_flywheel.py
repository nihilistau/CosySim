"""Tests for the NotebookLM control flywheel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from engine.nexus.notebooklm_flywheel import CONTROL_NOTEBOOK_NAME, NotebookLMFlywheel
from engine.nexus.task_scheduler import AgentTask


class _Config:
    """Small dict-backed config stub for flywheel tests."""

    def __init__(self, values: Dict[str, Any] | None = None) -> None:
        self._values = values or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


class _FakeScheduler:
    """Minimal TaskScheduler stand-in used for task creation assertions."""

    def __init__(self) -> None:
        self._tasks: Dict[str, AgentTask] = {}

    def load_from_nexus(self) -> int:
        return 0

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: int = 2,
        complexity: str = "medium",
        allowed_operations: List[str] | None = None,
        target_files: List[str] | None = None,
        tags: List[str] | None = None,
        depends_on: List[str] | None = None,
    ) -> AgentTask:
        task = AgentTask(
            title=title,
            description=description,
            priority=priority,
            complexity=complexity,
            allowed_operations=allowed_operations or ["read", "edit", "test"],
            target_files=target_files or [],
            tags=tags or [],
            depends_on=depends_on or [],
        )
        self._tasks[task.id] = task
        return task


def _report_payload(tasks: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """Build a valid NotebookLM JSON report payload."""
    return {
        "summary": "Control notebook summary",
        "system_state": ["Hooks are healthy", "Control notebook is seeded"],
        "priorities": ["Keep auth fresh", "Materialize downstream tasks"],
        "keepalive_actions": ["Refresh browser auth"],
        "distillation_topics": ["Copilot runtime"],
        "context_packet": {
            "immediate_summary": "Resume from the last control notebook artifact.",
            "startup_focus": ["NotebookLM flywheel", "Operator inbox"],
            "watch_surfaces": ["hooks", "scheduler"],
        },
        "tasks": tasks or [
            {
                "title": "Refresh control notebook tasks",
                "template": "feature",
                "description": "Update the control notebook follow-up wiring.",
                "target_files": ["engine/nexus/bootstrap_notebooks.py"],
                "tags": ["control", "notebooklm"],
                "priority": "high",
                "complexity": "medium",
                "allowed_operations": ["read", "edit", "test"],
                "depends_on": [],
            },
            {
                "title": "Validate flywheel scheduler task",
                "template": "test",
                "description": "Add coverage for the recurring control notebook flywheel task.",
                "target_files": ["tests/test_scheduler_daemon.py"],
                "tags": ["control", "scheduler"],
                "priority": "medium",
                "complexity": "low",
                "allowed_operations": ["read", "create", "test"],
                "depends_on": ["Refresh control notebook tasks"],
            },
        ],
    }


def _write_bootstrap_state(path: Path, notebook_url: str) -> None:
    """Write a minimal control notebook bootstrap state file."""
    path.write_text(
        json.dumps(
            {
                "notebooks": {CONTROL_NOTEBOOK_NAME: notebook_url},
                "notebooks_detail": {
                    CONTROL_NOTEBOOK_NAME: {
                        "notebook_url": notebook_url,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_resolve_control_notebook_url_reads_bootstrap_state(tmp_path: Path) -> None:
    """The flywheel should resolve the control notebook URL from bootstrap state."""
    bootstrap_state = tmp_path / "bootstrap.json"
    _write_bootstrap_state(
        bootstrap_state,
        "https://notebooklm.google.com/notebook/control-123",
    )

    flywheel = NotebookLMFlywheel(
        config=_Config({}),
        state_path=tmp_path / "state.json",
        bootstrap_state_path=bootstrap_state,
    )

    assert flywheel._resolve_control_notebook_url() == "https://notebooklm.google.com/notebook/control-123"


def test_run_creates_artifacts_tasks_and_training_examples(tmp_path: Path) -> None:
    """A full flywheel run should store artifacts, create tasks, and capture training."""
    bootstrap_state = tmp_path / "bootstrap.json"
    _write_bootstrap_state(
        bootstrap_state,
        "https://notebooklm.google.com/notebook/control-456",
    )
    config = _Config(
        {
            "notebooklm.flywheel.enabled": True,
            "notebooklm.flywheel.min_interval_hours": 0,
            "notebooklm.flywheel.max_tasks": 3,
            "notebooklm.flywheel.multi_ask_questions": ["State?", "Next?", "Keepalive?"],
            "notebooklm.flywheel.distill_category": "notebooklm-flywheel",
            "nexus.base_url": "http://localhost:8700",
        }
    )
    flywheel = NotebookLMFlywheel(
        config=config,
        state_path=tmp_path / "flywheel_state.json",
        bootstrap_state_path=bootstrap_state,
    )

    bridge = MagicMock()
    bridge.get_health.return_value = {"authenticated": True}
    bridge.add_notebook.return_value = {"id": "lib-control"}
    bridge.ask_multi.return_value = {
        "answers": [
            {"question": "State?", "answer": "Hooks are green.", "session_id": "sess-1"},
            {"question": "Next?", "answer": "Wire the scheduler task.", "session_id": "sess-1"},
            {"question": "Keepalive?", "answer": "Refresh auth daily.", "session_id": "sess-1"},
        ]
    }
    bridge.generate_report_with_prompt.return_value = {
        "content": json.dumps(_report_payload())
    }
    bridge.distill_to_nexus.return_value = {"nexus_count": 5}

    nexus = MagicMock()
    nexus.add_qa.return_value = "qa-entry"
    nexus.add_entry.side_effect = ["artifact-entry", "context-entry", "report-entry"]

    scheduler = _FakeScheduler()

    training = MagicMock()
    training.collect_from_qa.side_effect = ["qa-train-1", "qa-train-2", "qa-train-3"]
    training.collect_from_nlm.return_value = ["nlm-1", "nlm-2", "nlm-3"]
    training.collect_from_task.side_effect = ["task-train-1", "task-train-2"]

    with (
        patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=bridge),
        patch("engine.nexus.notebooklm_flywheel.get_nexus_client", return_value=nexus),
        patch("engine.nexus.notebooklm_flywheel.get_task_scheduler", return_value=scheduler),
        patch("engine.nexus.notebooklm_flywheel.get_training_flywheel", return_value=training),
    ):
        result = flywheel.run(reason="scheduler")

    assert result["status"] == "ok"
    assert result["notebook_ref"] == "lib-control"
    assert result["qa_method"] == "ask_multi"
    assert result["report_method"] == "studio_report"
    assert result["tasks_created"] == 2
    assert result["distilled_pairs"] == 5
    assert result["training"] == {
        "qa_examples": 3,
        "nlm_examples": 3,
        "task_examples": 2,
    }
    assert result["warnings"] == []
    assert nexus.add_qa.call_count == 3
    assert len(scheduler._tasks) == 2

    tasks_by_title = {task.title: task for task in scheduler._tasks.values()}
    assert tasks_by_title["Validate flywheel scheduler task"].depends_on == [
        tasks_by_title["Refresh control notebook tasks"].id
    ]

    saved_state = json.loads((tmp_path / "flywheel_state.json").read_text(encoding="utf-8"))
    assert saved_state["last_session_id"] == "sess-1"
    assert saved_state["last_result"]["artifact_entry_id"] == "artifact-entry"


def test_run_falls_back_to_batch_and_chat_report_when_needed(tmp_path: Path) -> None:
    """The flywheel should fall back to chat batch/report flows when Studio paths fail."""
    bootstrap_state = tmp_path / "bootstrap.json"
    _write_bootstrap_state(
        bootstrap_state,
        "https://notebooklm.google.com/notebook/control-789",
    )
    config = _Config(
        {
            "notebooklm.flywheel.enabled": True,
            "notebooklm.flywheel.min_interval_hours": 0,
            "notebooklm.flywheel.max_tasks": 2,
            "notebooklm.flywheel.multi_ask_questions": ["State?", "Next?"],
            "nexus.base_url": "http://localhost:8700",
        }
    )
    flywheel = NotebookLMFlywheel(
        config=config,
        state_path=tmp_path / "flywheel_state.json",
        bootstrap_state_path=bootstrap_state,
    )

    bridge = MagicMock()
    bridge.get_health.return_value = {"authenticated": True}
    bridge.add_notebook.return_value = {"id": "lib-control"}
    bridge.ask_multi.return_value = {"answers": [], "error": "ask_multi unavailable"}
    bridge.ask_batch.return_value = [
        {"answer": "Hooks are stable.", "session_id": "sess-batch"},
        {"answer": "Next task is testing.", "session_id": "sess-batch"},
    ]
    bridge.generate_report_with_prompt.return_value = {"content": "not-json"}
    bridge.ask_question.return_value = {"answer": json.dumps(_report_payload())}
    bridge.distill_to_nexus.return_value = {"error": "studio tile unavailable"}

    nexus = MagicMock()
    nexus.add_qa.return_value = "qa-entry"
    nexus.add_entry.side_effect = ["artifact-entry", "context-entry", "report-entry"]

    training = MagicMock()
    training.collect_from_qa.side_effect = ["qa-train-1", "qa-train-2"]
    training.collect_from_nlm.return_value = ["nlm-1", "nlm-2"]
    training.collect_from_task.side_effect = ["task-train-1", "task-train-2"]

    with (
        patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=bridge),
        patch("engine.nexus.notebooklm_flywheel.get_nexus_client", return_value=nexus),
        patch("engine.nexus.notebooklm_flywheel.get_task_scheduler", return_value=_FakeScheduler()),
        patch("engine.nexus.notebooklm_flywheel.get_training_flywheel", return_value=training),
    ):
        result = flywheel.run(reason="manual")

    assert result["status"] == "ok"
    assert result["qa_method"] == "chat_batch_fallback"
    assert result["report_method"] == "chat_report_fallback"
    assert "ask_multi unavailable" in result["warnings"]
    assert "studio tile unavailable" in result["warnings"]


def test_run_skips_when_artifact_hash_is_unchanged(tmp_path: Path) -> None:
    """Repeated identical runs should skip before storing duplicate Nexus artifacts."""
    bootstrap_state = tmp_path / "bootstrap.json"
    _write_bootstrap_state(
        bootstrap_state,
        "https://notebooklm.google.com/notebook/control-repeat",
    )
    config = _Config(
        {
            "notebooklm.flywheel.enabled": True,
            "notebooklm.flywheel.min_interval_hours": 0,
            "notebooklm.flywheel.max_tasks": 2,
            "notebooklm.flywheel.multi_ask_questions": ["State?", "Next?"],
            "nexus.base_url": "http://localhost:8700",
        }
    )
    flywheel = NotebookLMFlywheel(
        config=config,
        state_path=tmp_path / "flywheel_state.json",
        bootstrap_state_path=bootstrap_state,
    )

    bridge = MagicMock()
    bridge.get_health.return_value = {"authenticated": True}
    bridge.add_notebook.return_value = {"id": "lib-control"}
    bridge.ask_multi.return_value = {
        "answers": [
            {"question": "State?", "answer": "Stable.", "session_id": "sess-dup"},
            {"question": "Next?", "answer": "Keep going.", "session_id": "sess-dup"},
        ]
    }
    bridge.generate_report_with_prompt.return_value = {
        "content": json.dumps(_report_payload(tasks=[]))
    }
    bridge.distill_to_nexus.return_value = {"nexus_count": 1}

    nexus = MagicMock()
    nexus.add_qa.return_value = "qa-entry"
    nexus.add_entry.side_effect = ["artifact-entry", "context-entry", "report-entry"]

    training = MagicMock()
    training.collect_from_qa.side_effect = ["qa-train-1", "qa-train-2"]
    training.collect_from_nlm.return_value = ["nlm-1", "nlm-2"]
    training.collect_from_task.return_value = "task-train-1"

    scheduler = _FakeScheduler()

    with (
        patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=bridge),
        patch("engine.nexus.notebooklm_flywheel.get_nexus_client", return_value=nexus),
        patch("engine.nexus.notebooklm_flywheel.get_task_scheduler", return_value=scheduler),
        patch("engine.nexus.notebooklm_flywheel.get_training_flywheel", return_value=training),
    ):
        first = flywheel.run(reason="scheduler")

    assert first["status"] == "ok"

    nexus.reset_mock()
    bridge.distill_to_nexus.reset_mock()

    with (
        patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=bridge),
        patch("engine.nexus.notebooklm_flywheel.get_nexus_client", return_value=nexus),
        patch("engine.nexus.notebooklm_flywheel.get_task_scheduler", return_value=scheduler),
        patch("engine.nexus.notebooklm_flywheel.get_training_flywheel", return_value=training),
    ):
        second = flywheel.run(reason="scheduler")

    assert second["status"] == "skipped"
    assert second["reason"] == "artifact_unchanged"
    nexus.add_entry.assert_not_called()
    bridge.distill_to_nexus.assert_not_called()
