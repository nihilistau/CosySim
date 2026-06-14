"""Tests for NEXUS task auto-assignment, stale cleanup, and agent registry.

v1.50.2 [2026-03-24] — Tests for the auto-assignment pipeline.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.task_scheduler import (
    AgentTask,
    TaskComplexity,
    TaskPriority,
    TaskScheduler,
    TaskStatus,
)


# ── Auto-assign bug fix ──────────────────────────────────────────────────

class TestAutoAssign:
    """Verify auto_assign claims the correct specific task, not just any task."""

    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_auto_assign_claims_correct_task(self):
        """Bug fix: auto_assign must claim the specific task being matched,
        not the highest-priority available task for the agent."""
        task = self.scheduler.create_task(
            title="The only task",
            description="Test auto-assign",
            priority=TaskPriority.MEDIUM,
            complexity=TaskComplexity.MEDIUM,
            tags=["python"],
        )

        agents = [
            {"id": "worker-7b", "model_size_b": 7.0, "can_edit": True,
             "can_test": True, "tags": ["qwen"]},
        ]

        assignments = self.scheduler.auto_assign(agents, min_score=0.0)

        assert len(assignments) == 1
        assert assignments[0]["task_id"] == task.id
        assert assignments[0]["agent_id"] == "worker-7b"

        # The assigned task must be CLAIMED
        assert self.scheduler._tasks[task.id].status == TaskStatus.CLAIMED
        assert self.scheduler._tasks[task.id].assigned_agent == "worker-7b"

    def test_auto_assign_no_double_booking(self):
        """Each agent should only be assigned one task per round."""
        self.scheduler.create_task(title="Task A", priority=TaskPriority.HIGH)
        self.scheduler.create_task(title="Task B", priority=TaskPriority.LOW)

        agents = [{"id": "single-agent", "model_size_b": 7.0, "can_edit": True, "tags": []}]

        assignments = self.scheduler.auto_assign(agents, min_score=0.0)
        assert len(assignments) == 1  # One agent = one assignment

    def test_auto_assign_empty_agents(self):
        """No agents = no assignments."""
        self.scheduler.create_task(title="Orphan task")
        assignments = self.scheduler.auto_assign([], min_score=0.0)
        assert assignments == []

    def test_auto_assign_min_score_filter(self):
        """Tasks with too-low match score should not be assigned."""
        self.scheduler.create_task(title="Task", complexity=TaskComplexity.HIGH)
        agents = [{"id": "tiny-agent", "model_size_b": 0.5, "tags": []}]

        # With very high min_score, nothing should match
        assignments = self.scheduler.auto_assign(agents, min_score=0.99)
        assert assignments == []


# ── Stale task cleanup ────────────────────────────────────────────────────

class TestStaleCleanup:

    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_cleanup_stale_tasks(self):
        """CLAIMED tasks past timeout should be reset to PENDING."""
        task = self.scheduler.create_task(title="Stale task")
        # Manually claim it and set claimed_at to 25 hours ago
        task.status = TaskStatus.CLAIMED
        task.assigned_agent = "agent-x"
        task.claimed_at = time.time() - (25 * 3600)

        count = self.scheduler.cleanup_stale_tasks(timeout_hours=24.0)

        assert count == 1
        assert task.status == TaskStatus.PENDING
        assert task.assigned_agent == ""
        assert task.claimed_at == 0.0

    def test_cleanup_skips_recent_claims(self):
        """Recently claimed tasks should not be reset."""
        task = self.scheduler.create_task(title="Fresh claim")
        task.status = TaskStatus.CLAIMED
        task.assigned_agent = "agent-y"
        task.claimed_at = time.time() - 3600  # 1 hour ago

        count = self.scheduler.cleanup_stale_tasks(timeout_hours=24.0)
        assert count == 0
        assert task.status == TaskStatus.CLAIMED

    def test_cleanup_skips_non_claimed(self):
        """Only CLAIMED tasks should be cleaned up."""
        task = self.scheduler.create_task(title="Pending task")
        assert task.status == TaskStatus.PENDING

        count = self.scheduler.cleanup_stale_tasks(timeout_hours=0.0)
        assert count == 0  # PENDING is not CLAIMED


# ── Task status query ─────────────────────────────────────────────────────

class TestGetTaskStatuses:

    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_get_task_statuses(self):
        """Returns status map for known task IDs."""
        t1 = self.scheduler.create_task(title="Task 1")
        t2 = self.scheduler.create_task(title="Task 2")
        t2.status = TaskStatus.COMPLETED

        result = self.scheduler.get_task_statuses([t1.id, t2.id])
        assert result[t1.id] == TaskStatus.PENDING
        assert result[t2.id] == TaskStatus.COMPLETED

    def test_get_task_statuses_missing_ids(self):
        """Missing task IDs should be omitted from result."""
        result = self.scheduler.get_task_statuses(["nonexistent-id"])
        assert result == {}

    def test_get_task_statuses_empty_list(self):
        """Empty input returns empty output."""
        result = self.scheduler.get_task_statuses([])
        assert result == {}


# ── Agent registry ────────────────────────────────────────────────────────

class TestBuildAgentRegistry:

    def test_build_registry_with_models(self):
        """Should return capability dicts from loaded models."""
        from engine.nexus.local_agent_bridge import LocalAgentBridge

        mock_model = MagicMock()
        mock_model.id = "qwen3-7b-instruct"
        mock_model.architecture = "qwen3"
        mock_model.type = "llm"

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.get_models.return_value = [mock_model]

        bridge = LocalAgentBridge()
        with patch("engine.lmstudio.get_lms_client", return_value=mock_client):
            agents = bridge.build_agent_registry()

        assert len(agents) == 1
        assert agents[0]["id"] == "qwen3-7b-instruct"
        assert agents[0]["model_size_b"] == 7.0
        assert agents[0]["can_edit"] is True

    def test_build_registry_lmstudio_offline(self):
        """Should return empty list when LMStudio is offline."""
        from engine.nexus.local_agent_bridge import LocalAgentBridge

        mock_client = MagicMock()
        mock_client.is_available.return_value = False

        bridge = LocalAgentBridge()
        with patch("engine.lmstudio.get_lms_client", return_value=mock_client):
            agents = bridge.build_agent_registry()

        assert agents == []


# ── Model size parsing ────────────────────────────────────────────────────

class TestParseModelSize:

    def test_parse_from_id_string(self):
        from engine.nexus.local_agent_bridge import _parse_model_size
        model = MagicMock()
        model.id = "qwen3-0.6b-instruct"
        model.params = None
        model.parameters = None
        model.size = None
        assert _parse_model_size(model) == 0.6

    def test_parse_from_params_attr(self):
        from engine.nexus.local_agent_bridge import _parse_model_size
        model = MagicMock()
        model.params = 14.0
        assert _parse_model_size(model) == 14.0

    def test_parse_large_params(self):
        from engine.nexus.local_agent_bridge import _parse_model_size
        model = MagicMock()
        model.params = 7000000000  # 7 billion as integer
        assert _parse_model_size(model) == 7.0

    def test_parse_no_size(self):
        from engine.nexus.local_agent_bridge import _parse_model_size
        model = MagicMock()
        model.id = "mystery-model"
        model.params = None
        model.parameters = None
        model.size = None
        assert _parse_model_size(model) == 0.0
