"""
TaskQueue — Priority queue for model-affinity task dispatch
===========================================================

Routes coding, vision, chat, and router tasks to the best model
instance based on capability, affinity, and priority.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Living Systems: closed the dead-code loop.
        Workers now AUTO-START lazily on the first ``submit()`` (config-gated
        via ``lmstudio.task_queue_v2.*``) so the ``lms_submit_task`` /
        ``lms_queue_status`` skills actually execute enqueued tasks instead of
        leaving them permanently QUEUED. Added ``reset_task_queue()`` for
        hermetic singleton teardown in tests.
    v1.44.0 [2026-03-21] — InferenceMonitor feed on task completion.

Usage::

    from engine.lmstudio.task_queue import get_task_queue, Task, TaskType

    queue = get_task_queue()           # workers auto-start on first submit
    task = queue.submit(
        TaskType.CODE,
        prompt="Fix the bug in parser.py",
        model_hint="qwen3-8b",
    )
    result = queue.wait_for(task.id, timeout=60)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from queue import PriorityQueue, Empty
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """Task type determines model affinity routing."""
    CODE = "code"
    VISION = "vision"
    CHAT = "chat"
    ROUTER = "router"
    EMBEDDING = "embedding"
    EVALUATION = "evaluation"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskPriority(int, Enum):
    """Lower number = higher priority."""
    REALTIME = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BATCH = 4


# Default model affinity map (task type → preferred model patterns)
DEFAULT_AFFINITY: Dict[str, List[str]] = {
    TaskType.CODE: ["*coder*", "*codex*", "*starcoder*", "*deepseek-coder*", "*qwen*coder*"],
    TaskType.VISION: ["*vision*", "*llava*", "*qwen*vl*", "*pixtral*"],
    TaskType.CHAT: ["*chat*", "*instruct*", "*qwen*", "*llama*"],
    TaskType.ROUTER: ["*0.6b*", "*270m*", "*router*"],
    TaskType.EMBEDDING: ["*embed*", "*bge*", "*e5*"],
    TaskType.EVALUATION: ["*judge*", "*eval*", "*qwen*"],
}


@dataclass
class Task:
    """A queued inference task."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_type: TaskType = TaskType.CHAT
    priority: TaskPriority = TaskPriority.NORMAL
    prompt: str = ""
    system_prompt: str = ""
    messages: List[Dict[str, str]] = field(default_factory=list)
    model_hint: str = ""
    stop_strings: List[str] = field(default_factory=list)
    max_tokens: int = 2048
    temperature: float = 0.7
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Runtime state
    status: TaskStatus = TaskStatus.QUEUED
    assigned_model: str = ""
    assigned_peer: str = ""
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    latency_ms: float = 0.0
    tokens_used: int = 0

    def __lt__(self, other: "Task") -> bool:
        """Priority queue ordering: lower priority value = higher priority."""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at

    @property
    def queue_time_ms(self) -> float:
        if self.started_at > 0:
            return (self.started_at - self.created_at) * 1000
        return (time.time() - self.created_at) * 1000

    @property
    def total_time_ms(self) -> float:
        if self.completed_at > 0:
            return (self.completed_at - self.created_at) * 1000
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task_type": self.task_type.value,
            "priority": self.priority.name,
            "status": self.status.value,
            "model_hint": self.model_hint,
            "assigned_model": self.assigned_model,
            "assigned_peer": self.assigned_peer,
            "queue_time_ms": round(self.queue_time_ms, 1),
            "latency_ms": round(self.latency_ms, 1),
            "total_time_ms": round(self.total_time_ms, 1),
            "tokens_used": self.tokens_used,
            "error": self.error,
            "created_at": self.created_at,
        }


@dataclass
class TaskQueueMetrics:
    """Aggregate metrics for the task queue."""

    total_submitted: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_cancelled: int = 0
    total_timeouts: int = 0
    total_tokens: int = 0
    avg_queue_time_ms: float = 0.0
    avg_latency_ms: float = 0.0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_model: Dict[str, int] = field(default_factory=dict)

    def record_completion(self, task: Task) -> None:
        self.total_completed += 1
        self.total_tokens += task.tokens_used
        # Track by type
        ttype = task.task_type.value
        self.by_type[ttype] = self.by_type.get(ttype, 0) + 1
        # Track by model
        if task.assigned_model:
            self.by_model[task.assigned_model] = (
                self.by_model.get(task.assigned_model, 0) + 1
            )
        # Update averages (exponential moving average)
        alpha = 0.1
        if task.latency_ms > 0:
            self.avg_latency_ms = (
                alpha * task.latency_ms + (1 - alpha) * self.avg_latency_ms
                if self.avg_latency_ms > 0
                else task.latency_ms
            )
        if task.queue_time_ms > 0:
            self.avg_queue_time_ms = (
                alpha * task.queue_time_ms + (1 - alpha) * self.avg_queue_time_ms
                if self.avg_queue_time_ms > 0
                else task.queue_time_ms
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_submitted": self.total_submitted,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "total_cancelled": self.total_cancelled,
            "total_timeouts": self.total_timeouts,
            "total_tokens": self.total_tokens,
            "avg_queue_time_ms": round(self.avg_queue_time_ms, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "by_type": dict(self.by_type),
            "by_model": dict(self.by_model),
        }


class TaskQueue:
    """
    Priority task queue with model-affinity routing.

    Dispatches tasks to the best available model via the ServerController
    and LMLinkManager. Workers pull from the queue and execute against
    the assigned model.
    """

    def __init__(
        self,
        config: Any = None,
        *,
        max_workers: int = 4,
        max_queue_depth: int = 100,
        auto_start: Optional[bool] = None,
    ) -> None:
        if config is None:
            from engine.config import get_config
            config = get_config()

        self._config = config

        # v1.60.0 [2026-06-13] — Config-driven worker pool. Use a DEDICATED
        # config namespace (`lmstudio.task_queue_v2`) so we never collide with
        # the legacy `lmstudio.task_queue` block, which is owned by the
        # separate LMSTaskBridge queue in engine.nexus.lms_task_bridge.
        cfg_workers = config.get("lmstudio.task_queue_v2.workers", max_workers)
        cfg_depth = config.get("lmstudio.task_queue_v2.max_queue_depth", max_queue_depth)
        self._max_workers = int(cfg_workers) if cfg_workers else max_workers
        self._max_queue_depth = int(cfg_depth) if cfg_depth else max_queue_depth

        # When True, the first submit() spins up the worker pool automatically.
        # This is what makes the queue actually execute tasks end-to-end — the
        # skill callers (lms_submit_task) never call start() explicitly.
        #
        # Resolution order: explicit constructor arg wins (used by tests and by
        # the singleton factory); otherwise fall back to config. The DEFAULT is
        # False so a bare, directly-constructed TaskQueue stays inert until told
        # to run — the production wiring is opt-in through get_task_queue(), which
        # enables auto-start from config so the skill dispatch loop is closed.
        if auto_start is not None:
            self._auto_start: bool = bool(auto_start)
        else:
            self._auto_start = bool(
                config.get("lmstudio.task_queue_v2.auto_start", False)
            )

        # Priority queue (lower priority value = higher priority)
        self._queue: PriorityQueue[Task] = PriorityQueue(maxsize=self._max_queue_depth)
        self._lock = threading.Lock()

        # Task registry for lookup
        self._tasks: Dict[str, Task] = {}
        self._completion_events: Dict[str, threading.Event] = {}

        # Model affinity configuration
        affinity_config = config.get("lmstudio.task_queue.affinity", {})
        self._affinity: Dict[str, List[str]] = {}
        for task_type in TaskType:
            patterns = affinity_config.get(task_type.value, [])
            if isinstance(patterns, list) and patterns:
                self._affinity[task_type.value] = patterns
            else:
                self._affinity[task_type.value] = DEFAULT_AFFINITY.get(
                    task_type.value, []
                )

        # Metrics
        self._metrics = TaskQueueMetrics()

        # Worker threads
        self._workers: List[threading.Thread] = []
        self._stop_event = threading.Event()
        self._started = False

        # Callbacks
        self._on_complete: Optional[Callable[[Task], None]] = None
        self._on_error: Optional[Callable[[Task, Exception], None]] = None

        logger.info(
            "[task_queue] TaskQueue initialized (operation=init): "
            "max_workers=%d, max_depth=%d, auto_start=%s",
            self._max_workers, self._max_queue_depth, self._auto_start,
        )

    # v1.60.0 [2026-06-13] — Lazy worker bootstrap.
    # CONNECTS: lms_submit_task skill, worker_loop
    # CALLED BY: submit()
    def _ensure_started(self) -> None:
        """Start the worker pool on demand if auto-start is enabled.

        The skill callers (``lms_submit_task``) never invoke ``start()``
        explicitly, so without this hook every submitted task would remain
        permanently QUEUED. This is the wire that closes the dispatch loop.
        """
        if self._started or not self._auto_start:
            return
        # Double-checked under the start lock inside start().
        self.start()

    # ── Task submission ──────────────────────────────────────────────

    def submit(
        self,
        task_type: TaskType,
        *,
        prompt: str = "",
        system_prompt: str = "",
        messages: Optional[List[Dict[str, str]]] = None,
        model_hint: str = "",
        priority: TaskPriority = TaskPriority.NORMAL,
        stop_strings: Optional[List[str]] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """
        Submit a task to the queue.

        Parameters
        ----------
        task_type : TaskType
            Determines model affinity routing.
        prompt : str
            The main prompt text.
        system_prompt : str
            Optional system prompt.
        messages : list, optional
            Pre-built message list (overrides prompt).
        model_hint : str
            Preferred model (overrides affinity).
        priority : TaskPriority
            Queue priority.
        stop_strings : list, optional
            Stop sequences for this task.
        max_tokens : int
            Maximum output tokens.
        temperature : float
            Sampling temperature.
        metadata : dict, optional
            Arbitrary metadata.

        Returns
        -------
        Task
            The queued task descriptor.
        """
        task = Task(
            task_type=task_type,
            priority=priority,
            prompt=prompt,
            system_prompt=system_prompt,
            messages=messages or [],
            model_hint=model_hint,
            stop_strings=stop_strings or [],
            max_tokens=max_tokens,
            temperature=temperature,
            metadata=metadata or {},
        )

        # Build messages from prompt if not provided
        if not task.messages and task.prompt:
            if task.system_prompt:
                task.messages = [
                    {"role": "system", "content": task.system_prompt},
                    {"role": "user", "content": task.prompt},
                ]
            else:
                task.messages = [
                    {"role": "user", "content": task.prompt},
                ]

        with self._lock:
            self._tasks[task.id] = task
            completion = threading.Event()
            self._completion_events[task.id] = completion
            self._metrics.total_submitted += 1

        # v1.60.0 [2026-06-13] — Ensure workers are running before enqueue so
        # the task is actually dispatched (closes the previously-dead loop).
        self._ensure_started()

        try:
            self._queue.put_nowait(task)
        except Exception:
            task.status = TaskStatus.FAILED
            task.error = "Queue full"
            self._completion_events[task.id].set()
            logger.warning("Task queue full, rejecting task %s", task.id)

        logger.debug(
            "Task submitted: id=%s type=%s priority=%s model=%s",
            task.id, task.task_type.value, task.priority.name, task.model_hint,
        )
        return task

    def cancel(self, task_id: str) -> bool:
        """Cancel a queued task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.status != TaskStatus.QUEUED:
                return False

            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
            self._metrics.total_cancelled += 1

            event = self._completion_events.get(task_id)
            if event:
                event.set()

        return True

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def wait_for(self, task_id: str, timeout: float = 60.0) -> Optional[Task]:
        """
        Wait for a task to complete.

        Returns
        -------
        Task or None
            The completed task, or None if timeout.
        """
        event = self._completion_events.get(task_id)
        if event is None:
            return self._tasks.get(task_id)

        completed = event.wait(timeout=timeout)
        task = self._tasks.get(task_id)

        if not completed and task and task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.TIMEOUT
            task.completed_at = time.time()
            self._metrics.total_timeouts += 1

        return task

    # ── Worker management ────────────────────────────────────────────

    def start(self, num_workers: Optional[int] = None) -> None:
        """Start worker threads (idempotent, thread-safe)."""
        # v1.60.0 [2026-06-13] — Guard against concurrent lazy-start races from
        # multiple submitters by double-checking under the instance lock.
        with self._lock:
            if self._started:
                return

            n = num_workers or self._max_workers
            self._stop_event.clear()

            for i in range(n):
                t = threading.Thread(
                    target=self._worker_loop,
                    name=f"task-queue-worker-{i}",
                    daemon=True,
                )
                t.start()
                self._workers.append(t)

            self._started = True

        logger.info("[task_queue] Workers started (operation=start): count=%d", n)

    def stop(self) -> None:
        """Stop all worker threads."""
        self._stop_event.set()
        for t in self._workers:
            t.join(timeout=5)
        self._workers.clear()
        self._started = False
        logger.info("TaskQueue stopped")

    def _worker_loop(self) -> None:
        """Worker thread: pull tasks from queue and execute them."""
        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=1)
            except Empty:
                continue

            if task.status == TaskStatus.CANCELLED:
                continue

            try:
                self._execute_task(task)
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.completed_at = time.time()
                self._metrics.total_failed += 1
                logger.error("Task %s failed: %s", task.id, e)

                if self._on_error:
                    try:
                        self._on_error(task, e)
                    except Exception as cb_exc:
                        logger.warning("on_error callback failed: %s", cb_exc, exc_info=True)

            # Signal completion
            event = self._completion_events.get(task.id)
            if event:
                event.set()

    def _execute_task(self, task: Task) -> None:
        """Execute a single task against the resolved model."""
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()

        # Resolve model
        model = self._resolve_model(task)
        task.assigned_model = model

        # Build inference config
        from engine.lmstudio.inference_config import InferenceConfig

        config = InferenceConfig(
            temperature=task.temperature,
            max_output_tokens=task.max_tokens,
            stop_strings=task.stop_strings if task.stop_strings else None,
        )

        # Execute via LMS client
        from engine.lmstudio.lms_client import get_lms_client

        client = get_lms_client()
        start = time.monotonic()

        response = client.chat(
            messages=task.messages,
            model=model,
            config=config,
        )

        elapsed_ms = (time.monotonic() - start) * 1000

        # Record results
        task.result = response.content if response else ""
        task.tokens_used = getattr(response, "tokens_used", 0)
        task.latency_ms = elapsed_ms
        task.completed_at = time.time()
        task.status = TaskStatus.COMPLETED

        self._metrics.record_completion(task)

        # v1.44.0 [2026-03-21] — Feed InferenceMonitor for unified metrics
        try:
            from engine.lmstudio.inference_monitor import get_inference_monitor
            tps = (task.tokens_used / (elapsed_ms / 1000)) if elapsed_ms > 0 and task.tokens_used > 0 else 0.0
            get_inference_monitor().record(
                agent_id=task.metadata.get("agent_id", "task_queue") if hasattr(task, "metadata") and task.metadata else "task_queue",
                model=model,
                tier="task_queue",
                task_type=task.task_type.value if hasattr(task.task_type, "value") else str(task.task_type),
                latency_ms=elapsed_ms,
                tokens=task.tokens_used,
                tps=tps,
                success=True,
            )
        except Exception:
            logger.debug("InferenceMonitor task record failed", exc_info=True)

        if self._on_complete:
            try:
                self._on_complete(task)
            except Exception as cb_exc:
                logger.warning("on_complete callback failed: %s", cb_exc, exc_info=True)

        logger.debug(
            "Task %s completed: model=%s, latency=%.0fms, tokens=%d",
            task.id, model, elapsed_ms, task.tokens_used,
        )

    def _resolve_model(self, task: Task) -> str:
        """
        Resolve the best model for a task.

        Priority order:
        1. Explicit model_hint from the task
        2. Affinity-matched model from loaded models
        3. Config default model
        """
        if task.model_hint:
            return task.model_hint

        # Try affinity matching against loaded models
        try:
            from engine.lmstudio.server_controller import get_server_controller
            import fnmatch

            ctrl = get_server_controller()
            health = ctrl.last_health or ctrl.get_server_status()
            loaded = health.model_names

            patterns = self._affinity.get(task.task_type.value, [])
            for pattern in patterns:
                for model_name in loaded:
                    if fnmatch.fnmatch(model_name.lower(), pattern.lower()):
                        return model_name
        except Exception:
            logger.debug("Model affinity resolution failed", exc_info=True)

        # Try LMLink peer routing
        try:
            from engine.lmstudio.lmlink_manager import get_lmlink_manager
            mgr = get_lmlink_manager()
            if mgr.enabled:
                capability = None
                if task.task_type == TaskType.VISION:
                    capability = "vision"
                elif task.task_type == TaskType.EMBEDDING:
                    capability = "embedding"

                decision = mgr.resolve_peer(
                    task.model_hint or task.task_type.value,
                    require_capability=capability,
                )
                if decision:
                    task.assigned_peer = decision.peer.name
                    if decision.peer.loaded_models:
                        return decision.peer.loaded_models[0]
        except Exception:
            logger.debug("LMLink peer routing failed", exc_info=True)

        # Fall back to config default
        from engine.config import get_config
        cfg = get_config()
        return str(cfg.get("lmstudio.models.primary.path", ""))

    # ── Queue status ─────────────────────────────────────────────────

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def active_tasks(self) -> int:
        with self._lock:
            return sum(
                1 for t in self._tasks.values()
                if t.status == TaskStatus.RUNNING
            )

    def get_status(self) -> Dict[str, Any]:
        """Get queue status summary."""
        with self._lock:
            by_status = {}
            for task in self._tasks.values():
                s = task.status.value
                by_status[s] = by_status.get(s, 0) + 1

        return {
            "queue_depth": self.queue_depth,
            "active_tasks": self.active_tasks,
            "total_tasks": len(self._tasks),
            "by_status": by_status,
            "workers": len(self._workers),
            "started": self._started,
            "metrics": self._metrics.to_dict(),
        }

    def get_recent_tasks(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get the most recent tasks."""
        with self._lock:
            tasks = sorted(
                self._tasks.values(),
                key=lambda t: t.created_at,
                reverse=True,
            )[:limit]
        return [t.to_dict() for t in tasks]

    # ── Callbacks ────────────────────────────────────────────────────

    def on_complete(self, callback: Callable[[Task], None]) -> None:
        """Register a completion callback."""
        self._on_complete = callback

    def on_error(self, callback: Callable[[Task, Exception], None]) -> None:
        """Register an error callback."""
        self._on_error = callback

    # ── Shutdown ─────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Stop workers and clean up."""
        self.stop()
        with self._lock:
            # Signal all waiting tasks
            for event in self._completion_events.values():
                event.set()
        logger.info("TaskQueue shut down")


# ── Singleton ────────────────────────────────────────────────────────────

_instance: Optional[TaskQueue] = None
_instance_lock = threading.Lock()


def get_task_queue(config: Any = None) -> TaskQueue:
    """Return the global TaskQueue singleton."""
    global _instance
    if _instance is not None:
        return _instance

    with _instance_lock:
        if _instance is not None:
            return _instance
        # v1.60.0 [2026-06-13] — The singleton IS the production dispatch path
        # used by the lms_submit_task / lms_queue_status skills, so it auto-starts
        # its workers by default (config-overridable). Without this the skills
        # would enqueue tasks that never execute.
        if config is None:
            from engine.config import get_config
            config = get_config()
        auto_start = bool(config.get("lmstudio.task_queue_v2.auto_start", True))
        _instance = TaskQueue(config=config, auto_start=auto_start)
        return _instance


# v1.60.0 [2026-06-13] — Hermetic singleton teardown for tests.
def reset_task_queue() -> None:
    """Shut down and discard the global TaskQueue singleton.

    Intended for test isolation: parallel test runs (and the rest of the
    suite) must not inherit worker threads or queued state from a prior
    ``get_task_queue()`` call.
    """
    global _instance
    with _instance_lock:
        if _instance is not None:
            try:
                _instance.shutdown()
            except Exception:  # pragma: no cover - best-effort teardown
                logger.debug(
                    "[task_queue] Singleton shutdown failed (operation=reset)",
                    exc_info=True,
                )
            _instance = None
