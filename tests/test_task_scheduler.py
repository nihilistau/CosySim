"""Tests for engine.nexus.task_scheduler — TaskScheduler."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.task_scheduler import (
    AgentTask,
    TaskComplexity,
    TaskPriority,
    TaskScheduler,
    TaskStatus,
    get_task_scheduler,
)


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_config():
    """MagicMock config with .get() support."""
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda k, d=None: {
        "nexus.url": "http://localhost:8700/api",
    }.get(k, d))
    return cfg


@pytest.fixture
def scheduler(mock_config):
    """TaskScheduler with mocked config and Nexus calls."""
    with patch("engine.nexus.task_scheduler.requests.post"):
        s = TaskScheduler(mock_config)
        yield s


# ── AgentTask ───────────────────────────────────────────────────────────

def test_agent_task_defaults():
    """AgentTask has sensible defaults."""
    task = AgentTask()
    assert task.status == TaskStatus.PENDING
    assert task.priority == TaskPriority.MEDIUM
    assert "read" in task.allowed_operations
    assert task.assigned_agent == ""


def test_agent_task_to_dict():
    """AgentTask serializes to dict with all fields."""
    task = AgentTask(title="Test task", priority=TaskPriority.HIGH)
    d = task.to_dict()
    assert d["title"] == "Test task"
    assert d["priority"] == TaskPriority.HIGH
    assert "id" in d
    assert "status" in d


def test_agent_task_from_dict():
    """AgentTask deserializes from dict."""
    data = {
        "id": "test-123",
        "title": "Restored task",
        "status": "completed",
        "priority": 1,
    }
    task = AgentTask.from_dict(data)
    assert task.id == "test-123"
    assert task.title == "Restored task"
    assert task.status == "completed"


def test_agent_task_from_dict_ignores_unknown_keys():
    """from_dict ignores keys not in dataclass."""
    data = {"id": "x", "title": "Y", "unknown_field": "value"}
    task = AgentTask.from_dict(data)
    assert task.id == "x"
    assert not hasattr(task, "unknown_field")


def test_agent_task_to_markdown():
    """AgentTask renders readable markdown."""
    task = AgentTask(
        title="Fix bug",
        description="Fix the null pointer",
        priority=TaskPriority.HIGH,
        target_files=["src/main.py"],
        assigned_agent="bug-fixer",
    )
    md = task.to_markdown()
    assert "Fix bug" in md
    assert "src/main.py" in md
    assert "bug-fixer" in md


# ── TaskScheduler.create_task ───────────────────────────────────────────

def test_create_task_returns_task(scheduler):
    """create_task creates and stores task."""
    task = scheduler.create_task(
        title="Build feature",
        description="Add new scene",
        priority=TaskPriority.HIGH,
    )
    assert task.title == "Build feature"
    assert task.status == TaskStatus.PENDING
    assert scheduler.get_task(task.id) is task


def test_create_task_with_all_options(scheduler):
    """create_task accepts all optional fields."""
    task = scheduler.create_task(
        title="Complex task",
        description="Multi-file change",
        priority=TaskPriority.CRITICAL,
        complexity=TaskComplexity.HIGH,
        allowed_operations=["read", "edit", "create", "test"],
        target_files=["a.py", "b.py"],
        tags=["urgent", "refactor"],
        depends_on=["other-task"],
    )
    assert task.priority == TaskPriority.CRITICAL
    assert task.complexity == TaskComplexity.HIGH
    assert "create" in task.allowed_operations
    assert "urgent" in task.tags
    assert "other-task" in task.depends_on


# ── TaskScheduler.add_subtask ───────────────────────────────────────────

def test_add_subtask(scheduler):
    """add_subtask creates child task linked to parent."""
    parent = scheduler.create_task(title="Parent task")
    child = scheduler.add_subtask(parent.id, "Sub-task 1")

    assert child.parent_task == parent.id
    assert "subtask" in child.tags
    assert child.priority == parent.priority


def test_add_subtask_invalid_parent(scheduler):
    """add_subtask raises on non-existent parent."""
    with pytest.raises(ValueError, match="Parent task not found"):
        scheduler.add_subtask("nonexistent", "Sub-task")


# ── TaskScheduler.claim_task ────────────────────────────────────────────

def test_claim_task_picks_highest_priority(scheduler):
    """claim_task returns highest-priority pending task."""
    scheduler.create_task(title="Low", priority=TaskPriority.LOW)
    scheduler.create_task(title="Critical", priority=TaskPriority.CRITICAL)
    scheduler.create_task(title="Medium", priority=TaskPriority.MEDIUM)

    claimed = scheduler.claim_task("agent-1")

    assert claimed is not None
    assert claimed.title == "Critical"
    assert claimed.status == TaskStatus.CLAIMED
    assert claimed.assigned_agent == "agent-1"
    assert claimed.claimed_at > 0


def test_claim_task_skips_already_claimed(scheduler):
    """claim_task doesn't return already-claimed tasks."""
    scheduler.create_task(title="Task 1", priority=TaskPriority.HIGH)
    scheduler.create_task(title="Task 2", priority=TaskPriority.MEDIUM)

    first = scheduler.claim_task("agent-1")
    second = scheduler.claim_task("agent-2")

    assert first.title == "Task 1"
    assert second.title == "Task 2"


def test_claim_task_returns_none_when_empty(scheduler):
    """claim_task returns None when no tasks available."""
    result = scheduler.claim_task("agent-1")
    assert result is None


def test_claim_task_respects_dependencies(scheduler):
    """claim_task skips tasks with unresolved dependencies."""
    t1 = scheduler.create_task(title="Dep task", priority=TaskPriority.HIGH)
    scheduler.create_task(
        title="Blocked task",
        priority=TaskPriority.CRITICAL,
        depends_on=[t1.id],
    )
    scheduler.create_task(title="Free task", priority=TaskPriority.LOW)

    claimed = scheduler.claim_task("agent-1")

    # Should get the dep task (HIGH) since blocked task can't be claimed
    assert claimed.title == "Dep task"


def test_claim_task_unblocks_after_dependency_done(scheduler):
    """Blocked task becomes available after dependency completes."""
    dep = scheduler.create_task(title="Dependency")
    blocked = scheduler.create_task(
        title="Blocked",
        priority=TaskPriority.CRITICAL,
        depends_on=[dep.id],
    )

    # Complete the dependency
    scheduler.complete_task(dep.id, "Done")

    claimed = scheduler.claim_task("agent-1")
    assert claimed is not None
    assert claimed.title == "Blocked"


def test_claim_task_with_preferred_complexity(scheduler):
    """claim_task filters by preferred complexity."""
    scheduler.create_task(title="Big", complexity=TaskComplexity.HIGH)
    scheduler.create_task(title="Small", complexity=TaskComplexity.LOW)

    claimed = scheduler.claim_task("agent-1", preferred_complexity=TaskComplexity.LOW)

    assert claimed.title == "Small"


def test_claim_task_with_preferred_tags(scheduler):
    """claim_task filters by preferred tags."""
    scheduler.create_task(title="Backend", tags=["python", "api"])
    scheduler.create_task(title="Frontend", tags=["js", "css"])

    claimed = scheduler.claim_task("agent-1", preferred_tags=["css"])

    assert claimed.title == "Frontend"


# ── TaskScheduler.complete_task ─────────────────────────────────────────

def test_complete_task(scheduler):
    """complete_task marks task as completed."""
    task = scheduler.create_task(title="Do thing")
    result = scheduler.complete_task(task.id, "All done", ["a.py"])

    assert result is True
    assert task.status == TaskStatus.COMPLETED
    assert task.result_summary == "All done"
    assert task.files_changed == ["a.py"]
    assert task.completed_at > 0


def test_complete_nonexistent_task(scheduler):
    """complete_task returns False for unknown task."""
    assert scheduler.complete_task("nonexistent") is False


# ── TaskScheduler.fail_task ─────────────────────────────────────────────

def test_fail_task(scheduler):
    """fail_task marks task as failed."""
    task = scheduler.create_task(title="Risky thing")
    result = scheduler.fail_task(task.id, "Test failures")

    assert result is True
    assert task.status == TaskStatus.FAILED
    assert "FAILED" in task.result_summary


# ── TaskScheduler.block_task ────────────────────────────────────────────

def test_block_task(scheduler):
    """block_task marks task as blocked."""
    task = scheduler.create_task(title="Needs review")
    result = scheduler.block_task(task.id, "Waiting for review")

    assert result is True
    assert task.status == TaskStatus.BLOCKED


# ── TaskScheduler.list_tasks ────────────────────────────────────────────

def test_list_tasks_all(scheduler):
    """list_tasks returns all tasks."""
    scheduler.create_task(title="A")
    scheduler.create_task(title="B")
    scheduler.create_task(title="C")

    tasks = scheduler.list_tasks()
    assert len(tasks) == 3


def test_list_tasks_by_status(scheduler):
    """list_tasks filters by status."""
    t1 = scheduler.create_task(title="Pending")
    t2 = scheduler.create_task(title="Done")
    scheduler.complete_task(t2.id, "Complete")

    pending = scheduler.list_tasks(status=TaskStatus.PENDING)
    completed = scheduler.list_tasks(status=TaskStatus.COMPLETED)

    assert len(pending) == 1
    assert len(completed) == 1


def test_list_tasks_by_agent(scheduler):
    """list_tasks filters by assigned agent."""
    scheduler.create_task(title="A")
    scheduler.create_task(title="B")
    scheduler.claim_task("agent-1")

    agent_tasks = scheduler.list_tasks(agent_id="agent-1")
    assert len(agent_tasks) == 1


# ── TaskScheduler.get_queue_status ──────────────────────────────────────

def test_get_queue_status(scheduler):
    """get_queue_status returns counts per status."""
    scheduler.create_task(title="A")
    scheduler.create_task(title="B")
    t3 = scheduler.create_task(title="C")
    scheduler.complete_task(t3.id, "Done")

    status = scheduler.get_queue_status()
    assert status["total"] == 3
    assert status["pending"] == 2
    assert status["completed"] == 1


def test_get_pending_tasks_respects_limit(scheduler):
    """get_pending_tasks returns the requested number of tasks."""
    scheduler.create_task(title="Low", priority=TaskPriority.LOW)
    scheduler.create_task(title="Critical", priority=TaskPriority.CRITICAL)
    scheduler.create_task(title="Medium", priority=TaskPriority.MEDIUM)

    pending = scheduler.get_pending_tasks(limit=2)

    assert len(pending) == 2
    assert pending[0].title == "Critical"
    assert pending[1].title == "Medium"


# ── TaskScheduler.load_from_nexus ───────────────────────────────────────

@patch("engine.nexus.task_scheduler.requests.get")
def test_load_from_nexus_restores_tasks(mock_get, scheduler):
    """load_from_nexus restores tasks from Nexus entries."""
    import json
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {
        "results": [
            {"content": json.dumps({"id": "task-1", "title": "Restored"})},
            {"content": json.dumps({"id": "task-2", "title": "Also restored"})},
            {"content": "not-json"},
        ]
    }
    mock_get.return_value = mock_response

    count = scheduler.load_from_nexus()
    assert count == 2
    assert scheduler.get_task("task-1") is not None
    assert scheduler.get_task("task-2") is not None


@patch("engine.nexus.task_scheduler.requests.get")
def test_load_from_nexus_handles_failure(mock_get, scheduler):
    """load_from_nexus returns 0 on failure."""
    mock_get.side_effect = Exception("connection refused")

    count = scheduler.load_from_nexus()
    assert count == 0


def test_get_task_scheduler_preloads_from_nexus_once():
    """Singleton creation preloads persisted tasks from Nexus."""
    import engine.nexus.task_scheduler as mod

    mod._scheduler = None
    try:
        with patch.object(TaskScheduler, "load_from_nexus", return_value=3) as mock_load:
            scheduler = get_task_scheduler()
        assert isinstance(scheduler, TaskScheduler)
        mock_load.assert_called_once_with()
    finally:
        mod._scheduler = None


# ── Enums ───────────────────────────────────────────────────────────────

def test_task_status_values():
    """TaskStatus has all expected states."""
    assert TaskStatus.PENDING == "pending"
    assert TaskStatus.COMPLETED == "completed"
    assert TaskStatus.FAILED == "failed"
    assert TaskStatus.BLOCKED == "blocked"


def test_task_priority_ordering():
    """TaskPriority sorts correctly (lower = higher priority)."""
    assert TaskPriority.CRITICAL < TaskPriority.HIGH < TaskPriority.MEDIUM
    assert TaskPriority.MEDIUM < TaskPriority.LOW < TaskPriority.BACKGROUND
