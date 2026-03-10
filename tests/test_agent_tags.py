"""Tests for the AgentTaskManager and agent tags system."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.agent_tags import AgentTask, AgentTaskManager


# ── AgentTask dataclass ──────────────────────────────────────────────────

class TestAgentTask:
    def test_default_values(self):
        t = AgentTask()
        assert t.status == "pending"
        assert t.priority == "normal"
        assert t.tags == []

    def test_to_dict(self):
        t = AgentTask(title="Test", agent="copilot", priority="high")
        d = t.to_dict()
        assert d["title"] == "Test"
        assert d["agent"] == "copilot"
        assert d["priority"] == "high"

    def test_from_nexus_entry_json(self):
        data = {"task_id": "t1", "title": "Fix", "status": "done", "agent": "copilot",
                "priority": "high", "tags": ["bug"], "description": "desc"}
        entry = {"id": "t1", "title": "Task: Fix", "content": json.dumps(data)}
        task = AgentTask.from_nexus_entry(entry)
        assert task.task_id == "t1"
        assert task.status == "done"
        assert task.agent == "copilot"

    def test_from_nexus_entry_bad_json(self):
        entry = {"id": "t2", "title": "Task: Broken", "content": "not json"}
        task = AgentTask.from_nexus_entry(entry)
        assert task.task_id == "t2"
        assert task.title == "Task: Broken"


# ── AgentTaskManager ────────────────────────────────────────────────────

class TestAgentTaskManager:
    def setup_method(self):
        self.mgr = AgentTaskManager()
        self.mock_client = MagicMock()
        self.mgr._client = self.mock_client
        self.mgr._available = True
        self.mock_client.is_available.return_value = True
        self.mock_client.add_entry.return_value = "entry-123"

    def test_create_task(self):
        task_id = self.mgr.create_task("Fix bug", agent="copilot", priority="high")
        assert task_id == "entry-123"
        self.mock_client.add_entry.assert_called_once()
        call_kwargs = self.mock_client.add_entry.call_args
        assert "Task: Fix bug" in call_kwargs.kwargs.get("title", call_kwargs[1].get("title", ""))

    def test_create_task_offline(self):
        self.mgr._available = False
        task_id = self.mgr.create_task("Offline task")
        assert task_id == ""

    def test_create_task_with_tags(self):
        self.mgr.create_task("Tagged task", tags=["penthouse", "bug"])
        call_kwargs = self.mock_client.add_entry.call_args
        tags = call_kwargs.kwargs.get("tags", call_kwargs[1].get("tags", []))
        assert "penthouse" in tags
        assert "bug" in tags

    def test_update_status(self):
        # Pre-populate cache
        task = AgentTask(task_id="entry-123", title="Test", agent="copilot")
        self.mgr._local_cache["entry-123"] = task
        result = self.mgr.update_status("entry-123", "in_progress")
        assert result is True
        assert self.mgr._local_cache["entry-123"].status == "in_progress"

    def test_update_status_sets_completed_at(self):
        task = AgentTask(task_id="entry-123", title="Test")
        self.mgr._local_cache["entry-123"] = task
        self.mgr.update_status("entry-123", "done")
        assert self.mgr._local_cache["entry-123"].completed_at > 0

    def test_complete_task(self):
        task = AgentTask(task_id="entry-123", title="Test", agent="copilot")
        self.mgr._local_cache["entry-123"] = task
        result = self.mgr.complete_task("entry-123", summary="Fixed it")
        assert result is True
        assert self.mgr._local_cache["entry-123"].status == "done"
        assert self.mgr._local_cache["entry-123"].summary == "Fixed it"

    def test_complete_task_offline(self):
        self.mgr._available = False
        assert self.mgr.complete_task("x") is False

    def test_list_tasks_from_cache_when_offline(self):
        self.mgr._available = False
        self.mgr._local_cache["t1"] = AgentTask(title="A")
        self.mgr._local_cache["t2"] = AgentTask(title="B")
        tasks = self.mgr.list_tasks()
        assert len(tasks) == 2

    def test_list_tasks_from_nexus(self):
        self.mock_client.search.return_value = [
            {"id": "t1", "title": "Task: Fix A",
             "content": json.dumps({"status": "pending", "agent": "copilot", "title": "Fix A"}),
             "content_type": "task"},
            {"id": "t2", "title": "Task: Fix B",
             "content": json.dumps({"status": "done", "agent": "copilot", "title": "Fix B"}),
             "content_type": "task"},
        ]
        tasks = self.mgr.list_tasks(status="pending")
        assert len(tasks) == 1
        assert "Fix A" in tasks[0].title

    def test_list_tasks_filter_agent(self):
        self.mock_client.search.return_value = [
            {"id": "t1", "title": "Task: A",
             "content": json.dumps({"status": "pending", "agent": "copilot", "title": "A"}),
             "content_type": "task"},
            {"id": "t2", "title": "Task: B",
             "content": json.dumps({"status": "pending", "agent": "scene:bedroom", "title": "B"}),
             "content_type": "task"},
        ]
        tasks = self.mgr.list_tasks(agent="copilot")
        assert len(tasks) == 1
        assert tasks[0].agent == "copilot"

    def test_get_task_from_cache(self):
        task = AgentTask(task_id="t1", title="Cached")
        self.mgr._local_cache["t1"] = task
        assert self.mgr.get_task("t1") is task

    def test_get_task_not_found(self):
        self.mock_client.search.return_value = []
        assert self.mgr.get_task("nonexistent") is None

    def test_is_available_property(self):
        assert self.mgr.is_available is True
        self.mgr._available = False
        assert self.mgr.is_available is False


# ── Singleton ────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_task_manager(self):
        import engine.nexus.agent_tags as at
        at._manager_instance = None
        m1 = at.get_task_manager()
        m2 = at.get_task_manager()
        assert m1 is m2
        at._manager_instance = None
