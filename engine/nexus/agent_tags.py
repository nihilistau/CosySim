"""Agent Task Tags — Tag-based task management via Nexus.

Provides a lightweight tagging system for managing agent tasks, work items,
and task routing.  Tags are stored as Nexus entries with structured metadata,
enabling status tracking, assignment, prioritisation, and filtering.

Usage:
    from engine.nexus.agent_tags import get_task_manager
    mgr = get_task_manager()

    task_id = mgr.create_task("Fix bedroom dropdowns", agent="copilot",
                              priority="high", tags=["bedroom", "bug"])
    mgr.update_status(task_id, "in_progress")
    mgr.complete_task(task_id, summary="Fixed character state broadcast")
    tasks = mgr.list_tasks(status="pending", agent="copilot")
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_manager_instance: Optional[AgentTaskManager] = None
_manager_lock = threading.Lock()


@dataclass
class AgentTask:
    """A tracked task managed through Nexus."""

    task_id: str = ""
    title: str = ""
    description: str = ""
    status: str = "pending"  # pending | in_progress | done | blocked | cancelled
    agent: str = ""          # who is assigned (copilot, scene:bedroom, etc.)
    priority: str = "normal" # low | normal | high | critical
    tags: List[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0
    completed_at: float = 0.0
    summary: str = ""        # completion summary

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to dict."""
        return asdict(self)

    @classmethod
    def from_nexus_entry(cls, entry: Dict[str, Any]) -> AgentTask:
        """Parse a Nexus entry back into an AgentTask."""
        try:
            content = entry.get("content", "{}")
            data = json.loads(content) if isinstance(content, str) else content
            return cls(
                task_id=entry.get("id", data.get("task_id", "")),
                title=entry.get("title", data.get("title", "")),
                description=data.get("description", ""),
                status=data.get("status", "pending"),
                agent=data.get("agent", ""),
                priority=data.get("priority", "normal"),
                tags=data.get("tags", []),
                created_at=data.get("created_at", 0.0),
                updated_at=data.get("updated_at", 0.0),
                completed_at=data.get("completed_at", 0.0),
                summary=data.get("summary", ""),
            )
        except (json.JSONDecodeError, TypeError):
            return cls(
                task_id=entry.get("id", ""),
                title=entry.get("title", ""),
                description=entry.get("content", ""),
            )


class AgentTaskManager:
    """Manages agent tasks via Nexus knowledge entries."""

    TASK_CONTENT_TYPE = "task"
    TASK_CATEGORY = "agent_tasks"

    def __init__(self) -> None:
        self._client = None
        self._available = False
        self._local_cache: Dict[str, AgentTask] = {}
        self._init_client()

    def _init_client(self) -> None:
        """Initialise the Nexus client."""
        try:
            from engine.nexus.client import get_nexus_client
            self._client = get_nexus_client()
            self._available = self._client.is_available()
        except Exception:
            self._available = False

    @property
    def is_available(self) -> bool:
        """Check if task management is available."""
        return self._available and self._client is not None

    def create_task(
        self,
        title: str,
        description: str = "",
        agent: str = "",
        priority: str = "normal",
        tags: Optional[List[str]] = None,
    ) -> str:
        """Create a new agent task and store in Nexus.

        Args:
            title: Task title.
            description: Detailed description.
            agent: Assigned agent identifier.
            priority: Task priority (low/normal/high/critical).
            tags: Additional categorisation tags.

        Returns:
            Task ID string, or empty string on failure.
        """
        now = time.time()
        task = AgentTask(
            title=title,
            description=description,
            status="pending",
            agent=agent,
            priority=priority,
            tags=tags or [],
            created_at=now,
            updated_at=now,
        )

        if not self.is_available:
            logger.debug("Nexus unavailable — task not stored: %s", title)
            return ""

        try:
            all_tags = ["task", f"agent:{agent}", f"priority:{priority}"] + (tags or [])
            entry_id = self._client.add_entry(
                title=f"Task: {title}",
                content=json.dumps(task.to_dict()),
                content_type=self.TASK_CONTENT_TYPE,
                category=self.TASK_CATEGORY,
                tags=all_tags,
                created_by=agent or "system",
            )
            task.task_id = entry_id
            self._local_cache[entry_id] = task
            logger.info("Created task '%s' (id=%s, agent=%s)", title, entry_id, agent)
            return entry_id
        except Exception as exc:
            logger.warning("Failed to create task: %s", exc)
            return ""

    def update_status(self, task_id: str, status: str) -> bool:
        """Update task status.

        Args:
            task_id: Nexus entry ID for the task.
            status: New status (pending/in_progress/done/blocked/cancelled).

        Returns:
            True if updated successfully.
        """
        if not self.is_available:
            return False

        try:
            task = self._get_task(task_id)
            if not task:
                return False

            task.status = status
            task.updated_at = time.time()
            if status == "done":
                task.completed_at = time.time()

            self._client.add_entry(
                title=f"Task: {task.title}",
                content=json.dumps(task.to_dict()),
                content_type=self.TASK_CONTENT_TYPE,
                category=self.TASK_CATEGORY,
                tags=["task", f"status:{status}"],
                created_by=task.agent or "system",
            )
            self._local_cache[task_id] = task
            return True
        except Exception as exc:
            logger.warning("Failed to update task %s: %s", task_id, exc)
            return False

    def complete_task(self, task_id: str, summary: str = "") -> bool:
        """Mark a task as done with an optional summary.

        Args:
            task_id: Nexus entry ID.
            summary: Completion summary.

        Returns:
            True if completed successfully.
        """
        if not self.is_available:
            return False

        try:
            task = self._get_task(task_id)
            if not task:
                return False

            task.status = "done"
            task.summary = summary
            task.completed_at = time.time()
            task.updated_at = time.time()

            self._client.add_entry(
                title=f"Task [DONE]: {task.title}",
                content=json.dumps(task.to_dict()),
                content_type=self.TASK_CONTENT_TYPE,
                category=self.TASK_CATEGORY,
                tags=["task", "status:done", f"agent:{task.agent}"],
                created_by=task.agent or "system",
            )
            self._local_cache[task_id] = task
            logger.info("Completed task '%s'", task.title)
            return True
        except Exception as exc:
            logger.warning("Failed to complete task %s: %s", task_id, exc)
            return False

    def list_tasks(
        self,
        status: Optional[str] = None,
        agent: Optional[str] = None,
        limit: int = 20,
    ) -> List[AgentTask]:
        """List tasks, optionally filtered by status and agent.

        Args:
            status: Filter by status (or None for all).
            agent: Filter by assigned agent (or None for all).
            limit: Maximum results.

        Returns:
            List of matching AgentTask objects.
        """
        if not self.is_available:
            return list(self._local_cache.values())[:limit]

        try:
            query_parts = ["task"]
            if agent:
                query_parts.append(f"agent:{agent}")
            if status:
                query_parts.append(f"status:{status}")

            results = self._client.search(" ".join(query_parts), limit=limit)
            tasks = []
            for entry in results:
                if entry.get("content_type") == self.TASK_CONTENT_TYPE or "Task:" in entry.get("title", ""):
                    task = AgentTask.from_nexus_entry(entry)
                    if status and task.status != status:
                        continue
                    if agent and task.agent != agent:
                        continue
                    tasks.append(task)
            return tasks[:limit]
        except Exception as exc:
            logger.debug("list_tasks failed: %s", exc)
            return []

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        """Get a specific task by ID.

        Args:
            task_id: Nexus entry ID.

        Returns:
            AgentTask or None.
        """
        return self._get_task(task_id)

    def _get_task(self, task_id: str) -> Optional[AgentTask]:
        """Internal: fetch task from cache or Nexus."""
        if task_id in self._local_cache:
            return self._local_cache[task_id]

        if not self.is_available:
            return None

        try:
            results = self._client.search(task_id, limit=1)
            if results:
                task = AgentTask.from_nexus_entry(results[0])
                self._local_cache[task_id] = task
                return task
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        return None


def get_task_manager() -> AgentTaskManager:
    """Get or create the singleton AgentTaskManager.

    Returns:
        AgentTaskManager instance.
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = AgentTaskManager()
    return _manager_instance
