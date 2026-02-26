"""
Agent Task Scheduler — Ticketing system for local and Copilot agents.

Manages task queues with priorities, dependencies, and atomic sub-tasks.
Tasks are stored in Nexus for persistence and cross-agent visibility.

Usage::

    from engine.nexus.task_scheduler import TaskScheduler

    scheduler = TaskScheduler()

    # Create a task
    task = scheduler.create_task(
        title="Add lounge skills",
        description="Create 3 new skills for the lounge scene",
        priority=2,
        complexity="medium",
        allowed_operations=["read", "edit", "create", "test"],
        target_files=["content/scenes/lounge/lounge_skills.py"],
    )

    # Break into sub-tasks
    scheduler.add_subtask(task.id, "Add ambient_music skill")
    scheduler.add_subtask(task.id, "Add change_topic skill")
    scheduler.add_subtask(task.id, "Add test_lounge_skills test")

    # Agent claims and completes
    claimed = scheduler.claim_task("bug-fixer-agent")
    scheduler.complete_task(claimed.id, "Done — 3 skills added, tests pass")
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import requests

from engine.config import get_config

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task lifecycle states."""

    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskPriority(int, Enum):
    """Task priority levels (lower = higher priority)."""

    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    BACKGROUND = 4


class TaskComplexity(str, Enum):
    """Task complexity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class AgentTask:
    """A task that can be assigned to an agent."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    description: str = ""
    priority: int = TaskPriority.MEDIUM
    complexity: str = TaskComplexity.MEDIUM
    status: str = TaskStatus.PENDING

    # Assignment
    assigned_agent: str = ""
    claimed_at: float = 0.0
    completed_at: float = 0.0

    # Scope
    allowed_operations: List[str] = field(default_factory=lambda: ["read", "edit", "test"])
    target_files: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    # Relationships
    parent_task: str = ""
    depends_on: List[str] = field(default_factory=list)

    # Results
    result_summary: str = ""
    files_changed: List[str] = field(default_factory=list)
    nexus_entries: List[str] = field(default_factory=list)

    # Timestamps
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "complexity": self.complexity,
            "status": self.status,
            "assigned_agent": self.assigned_agent,
            "allowed_operations": self.allowed_operations,
            "target_files": self.target_files,
            "tags": self.tags,
            "parent_task": self.parent_task,
            "depends_on": self.depends_on,
            "result_summary": self.result_summary,
            "files_changed": self.files_changed,
            "created_at": self.created_at,
            "claimed_at": self.claimed_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentTask":
        """Deserialize from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_markdown(self) -> str:
        """Format as markdown for display."""
        lines = [
            f"### Task: {self.title}",
            f"**ID:** {self.id} | **Priority:** {self.priority} | "
            f"**Status:** {self.status} | **Complexity:** {self.complexity}",
            "",
            self.description,
            "",
        ]
        if self.target_files:
            lines.append(f"**Files:** {', '.join(self.target_files)}")
        if self.allowed_operations:
            lines.append(f"**Allowed:** {', '.join(self.allowed_operations)}")
        if self.assigned_agent:
            lines.append(f"**Assigned to:** {self.assigned_agent}")
        if self.depends_on:
            lines.append(f"**Depends on:** {', '.join(self.depends_on)}")
        return "\n".join(lines)


class TaskScheduler:
    """Priority-based task queue with dependency tracking."""

    def __init__(self, config: Optional[Any] = None) -> None:
        self._config = config or get_config()
        self._nexus_url = self._config.get("nexus.url", "http://localhost:8700/api")
        self._tasks: Dict[str, AgentTask] = {}

    # ── CRUD ────────────────────────────────────────────────────────

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: int = TaskPriority.MEDIUM,
        complexity: str = TaskComplexity.MEDIUM,
        allowed_operations: Optional[List[str]] = None,
        target_files: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        depends_on: Optional[List[str]] = None,
    ) -> AgentTask:
        """Create a new task."""
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
        self._sync_to_nexus(task)
        logger.info("Created task: %s — %s", task.id, title)
        return task

    def add_subtask(
        self,
        parent_id: str,
        title: str,
        description: str = "",
    ) -> AgentTask:
        """Create a sub-task linked to a parent."""
        parent = self._tasks.get(parent_id)
        if not parent:
            raise ValueError(f"Parent task not found: {parent_id}")

        subtask = AgentTask(
            title=title,
            description=description or f"Sub-task of: {parent.title}",
            priority=parent.priority,
            complexity=TaskComplexity.LOW,
            allowed_operations=parent.allowed_operations,
            target_files=parent.target_files,
            tags=parent.tags + ["subtask"],
            parent_task=parent_id,
        )
        self._tasks[subtask.id] = subtask
        logger.debug("Created subtask %s under %s", subtask.id, parent_id)
        return subtask

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    # ── Queue operations ────────────────────────────────────────────

    def claim_task(
        self,
        agent_id: str,
        preferred_complexity: Optional[str] = None,
        preferred_tags: Optional[List[str]] = None,
    ) -> Optional[AgentTask]:
        """Claim the highest-priority available task for an agent."""
        available = self._get_available_tasks()

        # Filter by preferences
        if preferred_complexity:
            filtered = [t for t in available if t.complexity == preferred_complexity]
            if filtered:
                available = filtered

        if preferred_tags:
            tag_set = set(preferred_tags)
            tagged = [t for t in available if tag_set.intersection(t.tags)]
            if tagged:
                available = tagged

        if not available:
            return None

        # Sort by priority (lower = higher priority)
        available.sort(key=lambda t: (t.priority, t.created_at))
        task = available[0]

        task.status = TaskStatus.CLAIMED
        task.assigned_agent = agent_id
        task.claimed_at = time.time()

        self._sync_to_nexus(task)
        logger.info("Task %s claimed by %s", task.id, agent_id)
        return task

    def complete_task(
        self,
        task_id: str,
        summary: str = "",
        files_changed: Optional[List[str]] = None,
    ) -> bool:
        """Mark a task as completed."""
        task = self._tasks.get(task_id)
        if not task:
            return False

        task.status = TaskStatus.COMPLETED
        task.completed_at = time.time()
        task.result_summary = summary
        task.files_changed = files_changed or []

        self._sync_to_nexus(task)
        logger.info("Task %s completed: %s", task_id, summary[:60])
        return True

    def fail_task(self, task_id: str, reason: str = "") -> bool:
        """Mark a task as failed."""
        task = self._tasks.get(task_id)
        if not task:
            return False

        task.status = TaskStatus.FAILED
        task.result_summary = f"FAILED: {reason}"
        self._sync_to_nexus(task)
        logger.warning("Task %s failed: %s", task_id, reason)
        return True

    def block_task(self, task_id: str, reason: str = "") -> bool:
        """Mark a task as blocked."""
        task = self._tasks.get(task_id)
        if not task:
            return False

        task.status = TaskStatus.BLOCKED
        task.result_summary = f"BLOCKED: {reason}"
        logger.info("Task %s blocked: %s", task_id, reason)
        return True

    # ── Queries ─────────────────────────────────────────────────────

    def list_tasks(
        self,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> List[AgentTask]:
        """List tasks, optionally filtered."""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        if agent_id:
            tasks = [t for t in tasks if t.assigned_agent == agent_id]
        return sorted(tasks, key=lambda t: (t.priority, t.created_at))

    def get_queue_status(self) -> Dict[str, Any]:
        """Get queue summary statistics."""
        all_tasks = list(self._tasks.values())
        return {
            "total": len(all_tasks),
            "pending": len([t for t in all_tasks if t.status == TaskStatus.PENDING]),
            "claimed": len([t for t in all_tasks if t.status == TaskStatus.CLAIMED]),
            "in_progress": len([t for t in all_tasks if t.status == TaskStatus.IN_PROGRESS]),
            "completed": len([t for t in all_tasks if t.status == TaskStatus.COMPLETED]),
            "failed": len([t for t in all_tasks if t.status == TaskStatus.FAILED]),
            "blocked": len([t for t in all_tasks if t.status == TaskStatus.BLOCKED]),
        }

    def _get_available_tasks(self) -> List[AgentTask]:
        """Get tasks that are ready to be claimed."""
        available = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            # Check dependencies
            if task.depends_on:
                all_done = all(
                    self._tasks.get(dep_id, AgentTask()).status == TaskStatus.COMPLETED
                    for dep_id in task.depends_on
                )
                if not all_done:
                    continue
            available.append(task)
        return available

    # ── Nexus sync ──────────────────────────────────────────────────

    def _sync_to_nexus(self, task: AgentTask) -> None:
        """Store/update task in Nexus."""
        try:
            import json
            requests.post(
                f"{self._nexus_url}/entries",
                json={
                    "title": f"Task: {task.title} [{task.status}]",
                    "content": json.dumps(task.to_dict(), indent=2),
                    "content_type": "task",
                    "category": "dev",
                    "tags": ["task", f"priority-{task.priority}", task.status] + task.tags,
                },
                timeout=5,
            )
        except Exception as e:
            logger.debug("Nexus sync failed for task %s: %s", task.id, e)

    def load_from_nexus(self) -> int:
        """Load tasks from Nexus (for recovery/sync)."""
        try:
            resp = requests.get(
                f"{self._nexus_url}/search",
                params={"q": "Task:", "limit": 100},
                timeout=10,
            )
            if resp.ok:
                results = resp.json().get("results", [])
                loaded = 0
                import json
                for r in results:
                    try:
                        data = json.loads(r.get("content", "{}"))
                        if "id" in data and "title" in data:
                            task = AgentTask.from_dict(data)
                            self._tasks[task.id] = task
                            loaded += 1
                    except (json.JSONDecodeError, TypeError):
                        continue
                logger.info("Loaded %d tasks from Nexus", loaded)
                return loaded
        except Exception as e:
            logger.warning("Cannot load tasks from Nexus: %s", e)
        return 0


# ── Singleton ───────────────────────────────────────────────────────────

_scheduler: Optional[TaskScheduler] = None


def get_task_scheduler() -> TaskScheduler:
    """Get or create the singleton TaskScheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler
