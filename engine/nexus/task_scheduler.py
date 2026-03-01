"""
Agent Task Scheduler — Ticketing system for local and Copilot agents.

Manages task queues with priorities, dependencies, and atomic sub-tasks.
Tasks are stored in Nexus for persistence and cross-agent visibility.

Includes auto-task generation from test failures, benchmark regressions,
stale knowledge, and audit findings. Task templates provide repeatable
patterns for common operations.

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

    # Auto-generate tasks from test failures
    scheduler.generate_from_test_failures(test_output)

    # Use task templates
    task = scheduler.from_template("bug-fix", title="Fix auth bug",
                                    target_files=["engine/auth.py"])
"""
from __future__ import annotations

import json
import logging
import re
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

    def claim_task_by_id(self, task_id: str, agent_id: str) -> Optional[AgentTask]:
        """Claim a specific task by ID for an agent.

        Args:
            task_id: Exact task ID to claim.
            agent_id: Unique identifier for the claiming agent.

        Returns:
            The claimed AgentTask, or None if not found / already claimed.
        """
        task = self._tasks.get(task_id)
        if not task or task.status not in (TaskStatus.PENDING, TaskStatus.BLOCKED):
            return None

        task.status = TaskStatus.CLAIMED
        task.assigned_agent = agent_id
        task.claimed_at = time.time()
        self._sync_to_nexus(task)
        logger.info("Task %s claimed by %s (direct)", task_id, agent_id)
        return task

    def get_pending_tasks(self) -> List[AgentTask]:
        """Return all pending (unclaimed) tasks sorted by priority."""
        pending = [
            t for t in self._tasks.values()
            if t.status == TaskStatus.PENDING
        ]
        pending.sort(key=lambda t: (t.priority, t.created_at))
        return pending


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

    def fail_task(self, task_id: str, reason: str = "", retry: bool = False) -> bool:
        """Mark a task as failed (or reset to pending if retry=True)."""
        task = self._tasks.get(task_id)
        if not task:
            return False

        if retry:
            task.status = TaskStatus.PENDING
            task.assigned_agent = ""
            task.claimed_at = 0.0
        else:
            task.status = TaskStatus.FAILED
        task.result_summary = f"FAILED: {reason}"
        self._sync_to_nexus(task)
        logger.warning("Task %s failed (retry=%s): %s", task_id, retry, reason)
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

    # ── Auto-Generation ─────────────────────────────────────────────

    def generate_from_test_failures(self, test_output: str) -> List[AgentTask]:
        """Parse pytest output and create bug-fix tasks for each failure.

        Args:
            test_output: Raw pytest output text.

        Returns:
            List of created AgentTask instances.
        """
        tasks = []
        failure_pattern = re.compile(
            r"FAILED\s+(tests/\S+)::(\S+)"
        )
        matches = failure_pattern.findall(test_output)

        for test_file, test_name in matches:
            existing = [
                t for t in self._tasks.values()
                if test_name in t.title and t.status in (
                    TaskStatus.PENDING, TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS
                )
            ]
            if existing:
                continue

            task = self.create_task(
                title=f"Fix failing test: {test_name}",
                description=(
                    f"Test `{test_name}` in `{test_file}` is failing.\n"
                    f"Diagnose the failure, fix the underlying code or test, "
                    f"and verify all tests pass."
                ),
                priority=TaskPriority.HIGH,
                complexity=TaskComplexity.MEDIUM,
                allowed_operations=["read", "edit", "test"],
                target_files=[test_file],
                tags=["auto-generated", "bug-fix", "test-failure"],
            )
            tasks.append(task)

        if tasks:
            logger.info(
                "Generated %d tasks from %d test failures",
                len(tasks), len(matches),
            )
        return tasks

    def generate_from_benchmark(
        self,
        metric_name: str,
        current_value: float,
        baseline_value: float,
        threshold_pct: float = 10.0,
    ) -> Optional[AgentTask]:
        """Create an optimization task if a benchmark metric regresses.

        Args:
            metric_name: Name of the metric (e.g., "inference_tps").
            current_value: Current measured value.
            baseline_value: Previous baseline value.
            threshold_pct: Percentage degradation threshold to trigger task.

        Returns:
            Created AgentTask if regression detected, None otherwise.
        """
        if baseline_value == 0:
            return None

        change_pct = ((current_value - baseline_value) / abs(baseline_value)) * 100
        is_regression = change_pct < -threshold_pct

        if not is_regression:
            return None

        task = self.create_task(
            title=f"Optimize: {metric_name} regressed {abs(change_pct):.1f}%",
            description=(
                f"Benchmark metric `{metric_name}` has regressed.\n"
                f"Baseline: {baseline_value}, Current: {current_value} "
                f"(change: {change_pct:+.1f}%).\n"
                f"Investigate root cause and restore performance."
            ),
            priority=TaskPriority.HIGH,
            complexity=TaskComplexity.HIGH,
            tags=["auto-generated", "optimization", "benchmark", metric_name],
        )
        logger.info(
            "Generated optimization task for %s: %.1f%% regression",
            metric_name, abs(change_pct),
        )
        return task

    def generate_from_stale_knowledge(
        self,
        stale_entries: List[Dict[str, Any]],
    ) -> List[AgentTask]:
        """Create refresh tasks for stale Nexus knowledge entries.

        Args:
            stale_entries: List of stale entry dicts (must have "id", "title").

        Returns:
            List of created refresh tasks.
        """
        tasks = []
        for entry in stale_entries[:10]:
            title = entry.get("title", "Unknown")
            entry_id = entry.get("id", "")
            task = self.create_task(
                title=f"Refresh stale knowledge: {title[:60]}",
                description=(
                    f"Nexus entry `{entry_id}` — \"{title}\" — is stale.\n"
                    f"Review, update if still relevant, or delete if obsolete."
                ),
                priority=TaskPriority.LOW,
                complexity=TaskComplexity.LOW,
                allowed_operations=["read", "edit"],
                tags=["auto-generated", "knowledge-refresh", "nexus"],
            )
            tasks.append(task)

        if tasks:
            logger.info("Generated %d knowledge refresh tasks", len(tasks))
        return tasks

    def generate_from_audit(
        self,
        audit_findings: List[Dict[str, Any]],
    ) -> List[AgentTask]:
        """Create tasks from audit findings.

        Args:
            audit_findings: List of findings, each with "title", "description",
                "severity" (critical/high/medium/low), and optional "files".

        Returns:
            List of created tasks.
        """
        severity_to_priority = {
            "critical": TaskPriority.CRITICAL,
            "high": TaskPriority.HIGH,
            "medium": TaskPriority.MEDIUM,
            "low": TaskPriority.LOW,
        }
        tasks = []
        for finding in audit_findings:
            severity = finding.get("severity", "medium")
            task = self.create_task(
                title=f"Audit: {finding.get('title', 'Fix finding')}",
                description=finding.get("description", ""),
                priority=severity_to_priority.get(severity, TaskPriority.MEDIUM),
                complexity=(
                    TaskComplexity.HIGH if severity == "critical"
                    else TaskComplexity.MEDIUM
                ),
                allowed_operations=["read", "edit", "create", "test"],
                target_files=finding.get("files", []),
                tags=["auto-generated", "audit", f"severity-{severity}"],
            )
            tasks.append(task)

        if tasks:
            logger.info("Generated %d tasks from audit findings", len(tasks))
        return tasks

    # ── Task Templates ──────────────────────────────────────────────

    def from_template(
        self,
        template_name: str,
        title: str = "",
        description: str = "",
        target_files: Optional[List[str]] = None,
        extra_tags: Optional[List[str]] = None,
    ) -> AgentTask:
        """Create a task from a predefined template.

        Args:
            template_name: Template name (bug-fix, feature, refactor, test,
                doc-update, skill-add, scene-polish, knowledge-refresh).
            title: Task title (overrides template default).
            description: Task description (appended to template default).
            target_files: Files to target.
            extra_tags: Additional tags.

        Returns:
            Created AgentTask.

        Raises:
            ValueError: If template_name is not recognized.
        """
        templates = self._get_templates()
        tmpl = templates.get(template_name)
        if not tmpl:
            raise ValueError(
                f"Unknown template: {template_name}. "
                f"Available: {', '.join(templates.keys())}"
            )

        full_desc = tmpl["description"]
        if description:
            full_desc += f"\n\n{description}"

        tags = tmpl.get("tags", []) + (extra_tags or []) + ["from-template"]

        return self.create_task(
            title=title or tmpl["title"],
            description=full_desc,
            priority=tmpl.get("priority", TaskPriority.MEDIUM),
            complexity=tmpl.get("complexity", TaskComplexity.MEDIUM),
            allowed_operations=tmpl.get("operations", ["read", "edit", "test"]),
            target_files=target_files or [],
            tags=tags,
        )

    @staticmethod
    def _get_templates() -> Dict[str, Dict[str, Any]]:
        """Return predefined task templates."""
        return {
            "bug-fix": {
                "title": "Fix bug",
                "description": (
                    "Diagnose the bug, identify root cause, implement fix, "
                    "add regression test, verify all tests pass."
                ),
                "priority": TaskPriority.HIGH,
                "complexity": TaskComplexity.MEDIUM,
                "operations": ["read", "edit", "test"],
                "tags": ["bug-fix"],
            },
            "feature": {
                "title": "Implement feature",
                "description": (
                    "Implement the feature following CosySim conventions. "
                    "Add type hints, docstrings, tests. Update docs if needed. "
                    "Search Nexus first for existing patterns."
                ),
                "priority": TaskPriority.MEDIUM,
                "complexity": TaskComplexity.HIGH,
                "operations": ["read", "edit", "create", "test"],
                "tags": ["feature"],
            },
            "refactor": {
                "title": "Refactor code",
                "description": (
                    "Improve code structure without changing behavior. "
                    "Run full test suite before and after to verify no regressions."
                ),
                "priority": TaskPriority.LOW,
                "complexity": TaskComplexity.MEDIUM,
                "operations": ["read", "edit", "test"],
                "tags": ["refactor"],
            },
            "test": {
                "title": "Add tests",
                "description": (
                    "Add comprehensive pytest tests. Mock external services. "
                    "Cover happy path and edge cases. Use existing fixtures "
                    "from conftest.py."
                ),
                "priority": TaskPriority.MEDIUM,
                "complexity": TaskComplexity.LOW,
                "operations": ["read", "create", "test"],
                "tags": ["testing"],
            },
            "doc-update": {
                "title": "Update documentation",
                "description": (
                    "Update documentation to reflect current code state. "
                    "Check for accuracy, add examples, update version numbers."
                ),
                "priority": TaskPriority.LOW,
                "complexity": TaskComplexity.LOW,
                "operations": ["read", "edit"],
                "tags": ["documentation"],
            },
            "skill-add": {
                "title": "Add MCP skill",
                "description": (
                    "Create a new @skill-decorated function. Follow the skill "
                    "decorator pattern in engine/skills/skill.py. Register in "
                    "the appropriate pack. Add tests."
                ),
                "priority": TaskPriority.MEDIUM,
                "complexity": TaskComplexity.MEDIUM,
                "operations": ["read", "edit", "create", "test"],
                "tags": ["skill", "mcp"],
            },
            "scene-polish": {
                "title": "Polish scene",
                "description": (
                    "Improve scene quality: better error handling, UI polish, "
                    "skill coverage, test coverage. Reference bedroom scene as AAA standard."
                ),
                "priority": TaskPriority.LOW,
                "complexity": TaskComplexity.MEDIUM,
                "operations": ["read", "edit", "test"],
                "tags": ["scene", "polish"],
            },
            "knowledge-refresh": {
                "title": "Refresh knowledge entry",
                "description": (
                    "Review and update a stale Nexus knowledge entry. "
                    "Verify accuracy, update content, or delete if obsolete."
                ),
                "priority": TaskPriority.BACKGROUND,
                "complexity": TaskComplexity.LOW,
                "operations": ["read", "edit"],
                "tags": ["nexus", "knowledge"],
            },
        }

    def list_templates(self) -> List[Dict[str, Any]]:
        """List available task templates.

        Returns:
            List of template summaries.
        """
        return [
            {
                "name": name,
                "title": tmpl["title"],
                "priority": tmpl.get("priority", TaskPriority.MEDIUM),
                "complexity": tmpl.get("complexity", TaskComplexity.MEDIUM),
                "tags": tmpl.get("tags", []),
            }
            for name, tmpl in self._get_templates().items()
        ]

    # ── Capability Matching ─────────────────────────────────────────

    def match_agent(
        self,
        task: AgentTask,
        agent_capabilities: Dict[str, Any],
    ) -> float:
        """Score how well an agent matches a task (0.0 to 1.0).

        Args:
            task: The task to match.
            agent_capabilities: Dict with "model_size_b" (float),
                "can_edit" (bool), "can_test" (bool), "tags" (List[str]).

        Returns:
            Match score from 0.0 (no match) to 1.0 (perfect match).
        """
        score = 0.0
        model_size = agent_capabilities.get("model_size_b", 0)

        # Complexity → model size matching
        complexity_min = {
            TaskComplexity.LOW: 0.5,
            TaskComplexity.MEDIUM: 3.0,
            TaskComplexity.HIGH: 9.0,
        }
        min_size = complexity_min.get(task.complexity, 3.0)
        if model_size >= min_size:
            score += 0.4
        elif model_size >= min_size * 0.5:
            score += 0.2

        # Operation capability matching
        can_edit = agent_capabilities.get("can_edit", False)
        can_test = agent_capabilities.get("can_test", False)
        needs_edit = "edit" in task.allowed_operations or "create" in task.allowed_operations
        needs_test = "test" in task.allowed_operations

        if needs_edit and can_edit:
            score += 0.3
        elif needs_edit and not can_edit:
            score -= 0.5
        if needs_test and can_test:
            score += 0.2

        # Tag overlap
        agent_tags = set(agent_capabilities.get("tags", []))
        task_tags = set(task.tags)
        if agent_tags and task_tags:
            overlap = len(agent_tags & task_tags) / max(len(task_tags), 1)
            score += overlap * 0.1

        return max(0.0, min(1.0, score))

    def auto_assign(
        self,
        agents: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Auto-assign pending tasks to available agents.

        Args:
            agents: List of agent capability dicts. Each must have
                "id" (str) and capability fields for match_agent().

        Returns:
            List of assignment dicts with "task_id", "agent_id", "score".
        """
        available = self._get_available_tasks()
        assignments = []

        for task in available:
            best_agent = None
            best_score = 0.0

            for agent in agents:
                score = self.match_agent(task, agent)
                if score > best_score:
                    best_score = score
                    best_agent = agent

            if best_agent and best_score >= 0.3:
                self.claim_task(best_agent["id"])
                assignments.append({
                    "task_id": task.id,
                    "agent_id": best_agent["id"],
                    "score": round(best_score, 2),
                })

        if assignments:
            logger.info("Auto-assigned %d tasks", len(assignments))
        return assignments


# ── Singleton ───────────────────────────────────────────────────────────

_scheduler: Optional[TaskScheduler] = None


def get_task_scheduler() -> TaskScheduler:
    """Get or create the singleton TaskScheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler
