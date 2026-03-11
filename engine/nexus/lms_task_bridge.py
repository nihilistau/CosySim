"""
LMS Task Bridge — Copilot → LMStudio task delegation with priority queue.

Allows Copilot CLI to dispatch subtasks to local LMStudio models via the
InferenceOrchestrator. Subtasks run locally on GPU/CPU and return results
to the caller for integration.

Features:
    - Synchronous single/batch execution (original API)
    - Async task submission with priority queue
    - Configurable worker concurrency
    - Retry with exponential backoff and fallback model
    - Per-model metrics and round-robin load balancing
    - 11 structured task types (evaluate, summarize, generate, classify,
      compare, code_review, security_check, test_generate, doc_generate,
      translate, refactor)

Usage::

    from engine.nexus.lms_task_bridge import LMSTaskBridge

    bridge = LMSTaskBridge()

    # Synchronous (unchanged)
    result = bridge.run_prompt("Summarize this code", model="qwen3-0.6b")

    # Async submission
    task_id = bridge.submit("Summarize this code", priority="high")
    result = bridge.get_result(task_id, timeout=30)

    # Batch async
    ids = bridge.submit_batch(["prompt1", "prompt2"], priority="normal")
    results = bridge.get_results(ids, timeout=60)
"""
from __future__ import annotations

import enum
import logging
import queue
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Priority Levels ─────────────────────────────────────────────────────

class Priority(enum.IntEnum):
    """Task priority levels (lower value = higher priority)."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4

    @classmethod
    def from_str(cls, name: str) -> "Priority":
        """Parse a priority name string (case-insensitive).

        Args:
            name: Priority name (e.g. "high", "NORMAL", "background").

        Returns:
            Matching Priority enum member, NORMAL if unrecognised.
        """
        try:
            return cls[name.upper()]
        except (KeyError, AttributeError):
            return cls.NORMAL


# ── Task Result ─────────────────────────────────────────────────────────

@dataclass
class TaskResult:
    """Result from a delegated LMStudio task."""

    task_id: str = ""
    status: str = "pending"  # pending, running, completed, failed, cancelled
    output: str = ""
    model: str = ""
    latency_ms: float = 0.0
    tokens_generated: int = 0
    tps: float = 0.0
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when the task completed without errors."""
        return self.status == "completed" and not self.error

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the result to a plain dict."""
        return {
            "task_id": self.task_id,
            "status": self.status,
            "output": self.output,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 1),
            "tokens_generated": self.tokens_generated,
            "tps": round(self.tps, 1),
            "error": self.error,
            "metadata": self.metadata,
        }


# ── Queued Task ─────────────────────────────────────────────────────────

@dataclass(order=False)
class QueuedTask:
    """A task waiting in the priority queue."""

    task_id: str
    priority: Priority
    prompt: str
    model: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024
    task_type: str = "chat"
    callback: Optional[Callable[[TaskResult], None]] = field(default=None, repr=False)
    created_at: float = field(default_factory=time.monotonic)
    retries: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, QueuedTask):
            return NotImplemented
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QueuedTask):
            return NotImplemented
        return self.task_id == other.task_id


# ── Task Queue ──────────────────────────────────────────────────────────

class TaskQueue:
    """Thread-safe priority queue for LMStudio tasks.

    Tasks are dequeued in priority order (CRITICAL first, BACKGROUND last).
    Within the same priority level, FIFO ordering is maintained via
    monotonic timestamps.

    Args:
        max_size: Maximum number of tasks allowed in the queue (0 = unbounded).
    """

    def __init__(self, max_size: int = 0) -> None:
        self._queue: queue.PriorityQueue[QueuedTask] = queue.PriorityQueue(maxsize=max_size)
        self._lock = threading.Lock()
        self._tasks: Dict[str, QueuedTask] = {}
        self._cancelled: set[str] = set()
        self._total_enqueued = 0
        self._total_dequeued = 0

    def enqueue(self, task: QueuedTask) -> bool:
        """Add a task to the queue.

        Args:
            task: The queued task to add.

        Returns:
            True if the task was added, False if the queue is full.
        """
        try:
            self._queue.put_nowait(task)
        except queue.Full:
            logger.warning("Task queue full — rejecting %s", task.task_id)
            return False
        with self._lock:
            self._tasks[task.task_id] = task
            self._total_enqueued += 1
        return True

    def dequeue(self, timeout: Optional[float] = None) -> Optional[QueuedTask]:
        """Remove and return the highest-priority task.

        Args:
            timeout: Seconds to wait for a task (None = block forever).

        Returns:
            The next task, or None on timeout / empty queue.
        """
        try:
            task = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        with self._lock:
            self._tasks.pop(task.task_id, None)
            self._total_dequeued += 1
        return task

    def peek(self) -> Optional[QueuedTask]:
        """Inspect the next task without removing it.

        Returns:
            The highest-priority task, or None if the queue is empty.

        Note:
            This is inherently racy in a multi-threaded context. Use only
            for monitoring / diagnostics.
        """
        with self._lock:
            if not self._tasks:
                return None
            return min(self._tasks.values())

    def cancel(self, task_id: str) -> bool:
        """Cancel a queued task.

        The task remains in the underlying PriorityQueue but will be
        skipped by workers on dequeue.

        Args:
            task_id: Identifier of the task to cancel.

        Returns:
            True if the task was found and marked for cancellation.
        """
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._cancelled.add(task_id)
                return True
            return False

    def is_cancelled(self, task_id: str) -> bool:
        """Check whether *task_id* was cancelled.

        Args:
            task_id: Identifier to check.

        Returns:
            True if the task was explicitly cancelled.
        """
        with self._lock:
            return task_id in self._cancelled

    @property
    def size(self) -> int:
        """Number of tasks currently in the queue."""
        with self._lock:
            return len(self._tasks)

    def clear(self) -> int:
        """Remove all tasks from the queue.

        Returns:
            Number of tasks that were removed.
        """
        removed = 0
        with self._lock:
            removed = len(self._tasks)
            self._tasks.clear()
            self._cancelled.clear()
        # Drain the PriorityQueue
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        return removed

    def get_stats(self) -> Dict[str, Any]:
        """Return queue statistics.

        Returns:
            Dict with current depth, total enqueued/dequeued counts.
        """
        with self._lock:
            return {
                "depth": len(self._tasks),
                "total_enqueued": self._total_enqueued,
                "total_dequeued": self._total_dequeued,
            }


# ── Model Metrics ───────────────────────────────────────────────────────

class _ModelMetrics:
    """Per-model performance metrics (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total: int = 0
        self.successes: int = 0
        self.failures: int = 0
        self.total_latency_ms: float = 0.0

    def record_success(self, latency_ms: float) -> None:
        with self._lock:
            self.total += 1
            self.successes += 1
            self.total_latency_ms += latency_ms

    def record_failure(self) -> None:
        with self._lock:
            self.total += 1
            self.failures += 1

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            avg = self.total_latency_ms / self.successes if self.successes else 0.0
            rate = self.successes / self.total if self.total else 0.0
            return {
                "total": self.total,
                "successes": self.successes,
                "failures": self.failures,
                "avg_latency_ms": round(avg, 1),
                "success_rate": round(rate, 4),
            }


# ── Queue Worker ────────────────────────────────────────────────────────

class QueueWorker:
    """Background worker that dequeues and executes tasks.

    Args:
        worker_id: Unique identifier for this worker.
        task_queue: The shared task queue to pull from.
        execute_fn: Callable that runs a single ``QueuedTask`` and returns
            a ``TaskResult``.
        result_store: Dict mapping ``task_id`` → ``TaskResult`` for callers
            waiting on ``get_result``.
        result_events: Dict mapping ``task_id`` → ``threading.Event`` that
            is set when the result is ready.
        retry_max: Maximum number of retries per task.
        retry_backoff: List of backoff durations (seconds) per retry attempt.
        fallback_model: Model to try when the primary model fails.
        model_metrics: Shared per-model metrics dict.
    """

    def __init__(
        self,
        worker_id: str,
        task_queue: TaskQueue,
        execute_fn: Callable[[QueuedTask], TaskResult],
        result_store: Dict[str, TaskResult],
        result_events: Dict[str, threading.Event],
        *,
        retry_max: int = 3,
        retry_backoff: Optional[List[float]] = None,
        fallback_model: str = "",
        model_metrics: Optional[Dict[str, _ModelMetrics]] = None,
    ) -> None:
        self.worker_id = worker_id
        self._queue = task_queue
        self._execute = execute_fn
        self._results = result_store
        self._events = result_events
        self._retry_max = retry_max
        self._retry_backoff = retry_backoff or [1.0, 2.0, 4.0]
        self._fallback_model = fallback_model
        self._model_metrics = model_metrics if model_metrics is not None else {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._tasks_processed = 0

    # ── lifecycle ────

    def start(self) -> None:
        """Start the worker thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"lms-worker-{self.worker_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info("Worker %s started", self.worker_id)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the worker to stop and wait for it to finish.

        Args:
            timeout: Seconds to wait for the thread to join.
        """
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("Worker %s stopped (%d tasks processed)", self.worker_id, self._tasks_processed)

    @property
    def is_running(self) -> bool:
        """Whether the worker loop is active."""
        with self._lock:
            return self._running

    # ── internal loop ────

    def _run_loop(self) -> None:
        """Main worker loop — dequeue, execute, store result."""
        while self._running:
            task = self._queue.dequeue(timeout=0.5)
            if task is None:
                continue
            # Skip cancelled tasks
            if self._queue.is_cancelled(task.task_id):
                self._publish(task.task_id, TaskResult(
                    task_id=task.task_id, status="cancelled",
                ))
                continue
            self._handle_task(task)

    def _handle_task(self, task: QueuedTask) -> None:
        """Execute a task with retry and fallback logic."""
        result: Optional[TaskResult] = None
        attempt = 0

        while attempt <= self._retry_max:
            model_for_attempt = task.model
            if attempt > 0 and self._fallback_model and not task.model:
                model_for_attempt = self._fallback_model

            modified_task = QueuedTask(
                task_id=task.task_id,
                priority=task.priority,
                prompt=task.prompt,
                model=model_for_attempt,
                system_prompt=task.system_prompt,
                temperature=task.temperature,
                max_tokens=task.max_tokens,
                task_type=task.task_type,
                metadata=task.metadata,
                retries=attempt,
            )

            try:
                result = self._execute(modified_task)
            except Exception as exc:
                result = TaskResult(
                    task_id=task.task_id,
                    status="failed",
                    error=str(exc),
                    model=model_for_attempt or "default",
                )
                logger.error("Worker %s task %s attempt %d error: %s",
                             self.worker_id, task.task_id, attempt, exc)

            used_model = (result.model if result else model_for_attempt) or "default"

            if result and result.ok:
                metrics = self._model_metrics.setdefault(used_model, _ModelMetrics())
                metrics.record_success(result.latency_ms)
                break

            metrics = self._model_metrics.setdefault(used_model, _ModelMetrics())
            metrics.record_failure()

            if attempt < self._retry_max:
                backoff_idx = min(attempt, len(self._retry_backoff) - 1)
                time.sleep(self._retry_backoff[backoff_idx])
            attempt += 1

        self._tasks_processed += 1
        if result is None:
            result = TaskResult(task_id=task.task_id, status="failed", error="exhausted retries")

        if task.callback:
            try:
                task.callback(result)
            except Exception as exc:
                logger.warning("Callback for %s raised: %s", task.task_id, exc)

        self._publish(task.task_id, result)

    def _publish(self, task_id: str, result: TaskResult) -> None:
        """Store result and notify waiters."""
        self._results[task_id] = result
        evt = self._events.get(task_id)
        if evt:
            evt.set()


# ── LMS Task Bridge (main API) ─────────────────────────────────────────

class LMSTaskBridge:
    """Bridge between Copilot CLI and local LMStudio inference.

    Delegates tasks to the InferenceOrchestrator for execution on
    locally loaded models. Results can optionally be stored in Nexus.

    Supports both synchronous (``run_prompt``, ``run_batch``, ``run_task``)
    and asynchronous (``submit``, ``get_result``) task execution via a
    background priority queue with configurable concurrency.
    """

    # Structured task system prompts (original 5 + 6 new)
    TASK_SYSTEM_PROMPTS: Dict[str, str] = {
        "evaluate": "You are an expert evaluator. Provide a rating (1-10) and brief justification.",
        "summarize": "Summarize the following concisely. Focus on key facts and decisions.",
        "generate": "Generate high-quality content based on the requirements.",
        "classify": "Classify the input into the most appropriate category. Return the category name and confidence.",
        "compare": "Compare the inputs and highlight similarities, differences, and which is better.",
        "code_review": (
            "You are a senior code reviewer. Analyse the code for bugs, style issues, "
            "performance problems, and security concerns. Provide actionable feedback."
        ),
        "security_check": (
            "You are a security analyst. Analyse the provided code or configuration for "
            "security vulnerabilities, injection risks, credential leaks, and unsafe patterns. "
            "Classify severity as critical/high/medium/low."
        ),
        "test_generate": (
            "You are a test engineer. Generate comprehensive test cases for the provided code. "
            "Include happy path, edge cases, and error scenarios. Use pytest style with plain assert."
        ),
        "doc_generate": (
            "You are a technical writer. Generate clear, concise documentation for the provided "
            "code or function. Follow Google-style docstrings. Include Args, Returns, and Raises sections."
        ),
        "translate": (
            "You are a translator. Translate the provided content between the specified languages "
            "or formats while preserving meaning, tone, and structure."
        ),
        "refactor": (
            "You are a refactoring expert. Suggest concrete refactoring improvements for the "
            "provided code. Focus on readability, maintainability, and reducing duplication. "
            "Never change behaviour, only structure."
        ),
    }

    # Task types that should prefer code-oriented models
    _CODE_TASK_TYPES = frozenset({
        "code_review", "security_check", "test_generate", "doc_generate", "refactor",
    })

    def __init__(self, config: Any = None) -> None:
        self._config = config
        self._orchestrator = None
        self._nexus = None
        self._task_counter = 0
        self._counter_lock = threading.Lock()

        # Queue infrastructure (lazily initialised)
        self._queue: Optional[TaskQueue] = None
        self._workers: List[QueueWorker] = []
        self._result_store: Dict[str, TaskResult] = {}
        self._result_events: Dict[str, threading.Event] = {}
        self._model_metrics: Dict[str, _ModelMetrics] = {}
        self._workers_started = False
        self._workers_lock = threading.Lock()
        self._rr_index = 0  # round-robin counter for load balancing

        # Clean up workers on garbage collection
        weakref.finalize(self, LMSTaskBridge._ensure_stopped, self._workers)

    @staticmethod
    def _ensure_stopped(workers: List[QueueWorker]) -> None:
        """Stop all workers — invoked by the weak-ref destructor."""
        for w in workers:
            try:
                w.stop(timeout=2.0)
            except Exception:
                pass

    # ── Properties ───────────────────────────────────────────────

    @property
    def orchestrator(self) -> Any:
        """Lazy-loaded InferenceOrchestrator."""
        if self._orchestrator is None:
            from engine.lmstudio.orchestrator import get_orchestrator
            self._orchestrator = get_orchestrator(self._config)
        return self._orchestrator

    @property
    def nexus(self) -> Any:
        """Lazy-loaded Nexus client."""
        if self._nexus is None:
            from engine.nexus.client import get_nexus_client
            self._nexus = get_nexus_client()
        return self._nexus

    # ── Helpers ──────────────────────────────────────────────────

    def _get_config_value(self, key: str, default: Any = None) -> Any:
        """Read a config key with fallback to default.

        Args:
            key: Dot-notation config key.
            default: Value returned when the key is absent.

        Returns:
            Config value or *default*.
        """
        try:
            from engine.config import get_config
            return get_config().get(key, default)
        except Exception:
            return default

    def _next_id(self) -> str:
        """Generate a unique, monotonically increasing task ID.

        Returns:
            String like ``lms-0001``.
        """
        with self._counter_lock:
            self._task_counter += 1
            return f"lms-{self._task_counter:04d}"

    def _select_model(self, task_type: str, requested_model: str) -> str:
        """Select the best model for a task using routing config and load balancing.

        Args:
            task_type: The type of task (e.g. "code_review", "summarize").
            requested_model: Explicitly requested model (takes precedence).

        Returns:
            Model identifier string (may be empty to use orchestrator default).
        """
        if requested_model:
            return requested_model

        # Check task routing config
        routed = self._get_config_value(f"lmstudio.task_queue.task_routing.{task_type}", "")
        if routed:
            return routed

        # Try round-robin across loaded models for generic tasks
        try:
            status = self.check_lmstudio()
            models = status.get("model_ids", [])
            if len(models) > 1:
                idx = self._rr_index % len(models)
                self._rr_index += 1
                return models[idx]
        except Exception:
            pass

        return ""

    # ── Queue management ─────────────────────────────────────────

    def _ensure_queue(self) -> TaskQueue:
        """Lazily create the task queue.

        Returns:
            The shared TaskQueue instance.
        """
        if self._queue is None:
            max_size = int(self._get_config_value("lmstudio.task_queue.max_queue_size", 100))
            self._queue = TaskQueue(max_size=max_size)
        return self._queue

    def _ensure_workers(self) -> None:
        """Start background workers if not yet started."""
        with self._workers_lock:
            if self._workers_started:
                return
            self._ensure_queue()
            num_workers = int(self._get_config_value("lmstudio.task_queue.workers", 1))
            retry_max = int(self._get_config_value("lmstudio.task_queue.retry_max", 3))
            retry_backoff = self._get_config_value("lmstudio.task_queue.retry_backoff", [1, 2, 4])
            fallback_model = self._get_config_value("lmstudio.task_queue.fallback_model", "")

            for i in range(num_workers):
                worker = QueueWorker(
                    worker_id=str(i),
                    task_queue=self._queue,
                    execute_fn=self._execute_queued,
                    result_store=self._result_store,
                    result_events=self._result_events,
                    retry_max=retry_max,
                    retry_backoff=[float(b) for b in retry_backoff],
                    fallback_model=fallback_model,
                    model_metrics=self._model_metrics,
                )
                worker.start()
                self._workers.append(worker)

            self._workers_started = True
            logger.info("Started %d queue worker(s)", num_workers)

    def _execute_queued(self, task: QueuedTask) -> TaskResult:
        """Execute a single queued task (called by workers).

        Args:
            task: The dequeued task to run.

        Returns:
            Completed or failed TaskResult.
        """
        model = self._select_model(task.task_type, task.model)
        return self._run_prompt_internal(
            task_id=task.task_id,
            prompt=task.prompt,
            model=model,
            system_prompt=task.system_prompt,
            temperature=task.temperature,
            max_tokens=task.max_tokens,
            task_type=task.task_type,
            priority=task.priority.name.lower(),
        )

    def start_workers(self) -> None:
        """Explicitly start the queue workers.

        Workers are also started automatically on the first ``submit()`` call.
        """
        self._ensure_workers()

    def stop_workers(self, timeout: float = 5.0) -> None:
        """Stop all queue workers gracefully.

        Args:
            timeout: Seconds to wait per worker for thread join.
        """
        with self._workers_lock:
            for w in self._workers:
                w.stop(timeout=timeout)
            self._workers.clear()
            self._workers_started = False
        logger.info("All queue workers stopped")

    # ── Async submission API ─────────────────────────────────────

    def submit(
        self,
        prompt: str,
        *,
        priority: str = "normal",
        model: str = "",
        callback: Optional[Callable[[TaskResult], None]] = None,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        task_type: str = "chat",
        **kwargs: Any,
    ) -> str:
        """Submit a task to the priority queue.

        The task is enqueued and executed asynchronously by a background worker.

        Args:
            prompt: The user prompt.
            priority: Priority name ("critical", "high", "normal", "low", "background").
            model: Target model (empty = auto-select).
            callback: Optional function called with the TaskResult when done.
            system_prompt: System prompt override.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            task_type: Task type for routing and prompt injection.
            **kwargs: Extra metadata stored on the queued task.

        Returns:
            A unique ``task_id`` string.
        """
        self._ensure_workers()
        task_id = self._next_id()
        evt = threading.Event()
        self._result_events[task_id] = evt

        task = QueuedTask(
            task_id=task_id,
            priority=Priority.from_str(priority),
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            task_type=task_type,
            callback=callback,
            metadata=kwargs,
        )

        q = self._ensure_queue()
        if not q.enqueue(task):
            result = TaskResult(task_id=task_id, status="failed", error="queue full")
            self._result_store[task_id] = result
            evt.set()

        return task_id

    def submit_batch(
        self,
        prompts: List[str],
        *,
        priority: str = "normal",
        model: str = "",
        callback: Optional[Callable[[TaskResult], None]] = None,
    ) -> List[str]:
        """Submit multiple prompts to the queue.

        Args:
            prompts: List of prompt strings.
            priority: Shared priority for all tasks.
            model: Model override (empty = auto-select per task).
            callback: Optional callback invoked for each completed task.

        Returns:
            List of ``task_id`` strings, one per prompt.
        """
        return [
            self.submit(p, priority=priority, model=model, callback=callback)
            for p in prompts
        ]

    def get_result(self, task_id: str, timeout: Optional[float] = None) -> Optional[TaskResult]:
        """Block until a submitted task completes and return its result.

        Args:
            task_id: The task identifier returned by ``submit()``.
            timeout: Seconds to wait. ``None`` = wait indefinitely.

        Returns:
            The ``TaskResult``, or ``None`` if the timeout elapsed.
        """
        evt = self._result_events.get(task_id)
        if evt is None:
            return self._result_store.get(task_id)
        evt.wait(timeout=timeout)
        return self._result_store.get(task_id)

    def get_results(
        self,
        task_ids: List[str],
        timeout: Optional[float] = None,
    ) -> Dict[str, Optional[TaskResult]]:
        """Get results for multiple tasks, blocking until all are ready.

        Args:
            task_ids: List of task identifiers.
            timeout: Per-task timeout (seconds).

        Returns:
            Dict mapping each ``task_id`` to its result (or ``None``).
        """
        return {tid: self.get_result(tid, timeout=timeout) for tid in task_ids}

    def cancel(self, task_id: str) -> bool:
        """Cancel a queued (not yet running) task.

        Args:
            task_id: The task identifier to cancel.

        Returns:
            True if the task was found in the queue and cancelled.
        """
        q = self._ensure_queue()
        cancelled = q.cancel(task_id)
        if cancelled:
            result = TaskResult(task_id=task_id, status="cancelled")
            self._result_store[task_id] = result
            evt = self._result_events.get(task_id)
            if evt:
                evt.set()
        return cancelled

    def queue_stats(self) -> Dict[str, Any]:
        """Return queue and worker statistics.

        Returns:
            Dict with queue depth, totals, per-model metrics, and worker count.
        """
        q_stats = self._ensure_queue().get_stats()
        model_stats = {m: metrics.to_dict() for m, metrics in self._model_metrics.items()}

        total_tasks = sum(m.total for m in self._model_metrics.values())
        total_success = sum(m.successes for m in self._model_metrics.values())
        total_latency = sum(m.total_latency_ms for m in self._model_metrics.values())

        return {
            "queue": q_stats,
            "workers": len(self._workers),
            "workers_running": sum(1 for w in self._workers if w.is_running),
            "total_tasks": total_tasks,
            "success_rate": round(total_success / total_tasks, 4) if total_tasks else 0.0,
            "avg_latency_ms": round(total_latency / total_success, 1) if total_success else 0.0,
            "per_model": model_stats,
        }

    # ── Single prompt (synchronous — original API) ───────────────

    def _run_prompt_internal(
        self,
        *,
        task_id: str,
        prompt: str,
        model: str = "",
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        task_type: str = "chat",
        priority: str = "background",
    ) -> TaskResult:
        """Core prompt execution — shared by sync and async paths.

        Args:
            task_id: Unique identifier for this execution.
            prompt: User prompt text.
            model: Target model identifier.
            system_prompt: System prompt to prepend.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.
            task_type: Type string forwarded to the orchestrator.
            priority: Priority string forwarded to the orchestrator.

        Returns:
            Completed or failed ``TaskResult``.
        """
        result = TaskResult(task_id=task_id, status="running", model=model or "default")
        messages = [{"role": "user", "content": prompt}]
        t0 = time.monotonic()

        try:
            resp = self.orchestrator.infer(
                agent_id=f"bridge-{task_id}",
                messages=messages,
                task_type=task_type,
                priority=priority,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )

            latency_ms = (time.monotonic() - t0) * 1000
            content = resp.content if hasattr(resp, "content") else str(resp)

            tokens = 0
            if hasattr(resp, "usage") and resp.usage:
                tokens = int(getattr(resp.usage, "completion_tokens", 0) or 0)

            tps = tokens / (latency_ms / 1000) if tokens > 0 and latency_ms > 0 else 0.0

            result.status = "completed"
            result.output = content
            result.model = model or "default"
            result.latency_ms = latency_ms
            result.tokens_generated = tokens
            result.tps = tps

        except Exception as exc:
            result.status = "failed"
            result.error = str(exc)
            result.latency_ms = (time.monotonic() - t0) * 1000
            logger.error("Task %s failed: %s", task_id, exc)

        return result

    def run_prompt(
        self,
        prompt: str,
        *,
        model: str = "",
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        task_type: str = "chat",
        priority: str = "background",
    ) -> TaskResult:
        """Run a single prompt through LMStudio and return the result.

        This is the synchronous API — it blocks until the inference completes.

        Args:
            prompt: User prompt text.
            model: Target model identifier (empty = default).
            system_prompt: System prompt to prepend.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.
            task_type: Task type forwarded to the orchestrator.
            priority: Priority string forwarded to the orchestrator.

        Returns:
            Completed or failed ``TaskResult``.
        """
        task_id = self._next_id()
        return self._run_prompt_internal(
            task_id=task_id,
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            task_type=task_type,
            priority=priority,
        )

    # ── Batch execution (synchronous — original API) ─────────────

    def run_batch(
        self,
        prompts: List[Dict[str, Any]],
        *,
        model: str = "",
        system_prompt: str = "",
        store_results: bool = False,
    ) -> List[TaskResult]:
        """Run multiple prompts sequentially and return all results.

        Each item in *prompts* should have at minimum a ``"prompt"`` key.
        Optional keys: ``temperature``, ``max_tokens``, ``task_type``.

        Args:
            prompts: List of dicts, each with at least ``{"prompt": "..."}``.
            model: Model override applied to all items.
            system_prompt: System prompt override applied to all items.
            store_results: If True, store a summary in Nexus.

        Returns:
            List of ``TaskResult`` objects, one per valid prompt.
        """
        results: List[TaskResult] = []
        for item in prompts:
            p = item.get("prompt", "")
            if not p:
                continue
            result = self.run_prompt(
                p,
                model=model or item.get("model", ""),
                system_prompt=system_prompt or item.get("system_prompt", ""),
                temperature=item.get("temperature", 0.7),
                max_tokens=item.get("max_tokens", 1024),
                task_type=item.get("task_type", "chat"),
            )
            results.append(result)

        if store_results:
            self._store_batch_results(results)

        return results

    # ── Structured task (synchronous — extended) ─────────────────

    def run_task(
        self,
        task_type: str,
        prompt: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        model: str = "",
        store_result: bool = False,
    ) -> TaskResult:
        """Run a structured task with context injection.

        Supported task types:
            - evaluate: Rate/score content
            - summarize: Summarize text
            - generate: Generate content
            - classify: Classify input
            - compare: Compare two inputs
            - code_review: Review code for issues, style, bugs
            - security_check: Analyse code/config for security concerns
            - test_generate: Generate test cases for given code
            - doc_generate: Generate documentation for code/functions
            - translate: Translate between languages/formats
            - refactor: Suggest refactoring for given code

        Args:
            task_type: One of the supported task type strings.
            prompt: User prompt / input text.
            context: Optional key-value context appended to the prompt.
            model: Model override (empty = use task routing or default).
            store_result: If True, persist the result in Nexus.

        Returns:
            Completed or failed ``TaskResult``.
        """
        sys_prompt = self.TASK_SYSTEM_PROMPTS.get(task_type, "")
        full_prompt = prompt
        if context:
            ctx_str = "\n".join(f"{k}: {v}" for k, v in context.items())
            full_prompt = f"{prompt}\n\nContext:\n{ctx_str}"

        selected_model = self._select_model(task_type, model)

        result = self.run_prompt(
            full_prompt,
            model=selected_model,
            system_prompt=sys_prompt,
            task_type="chat",
            priority="background",
        )
        result.metadata["task_type"] = task_type

        if store_result and result.ok:
            self._store_single_result(result, task_type)

        return result

    # ── LMStudio health check ────────────────────────────────────

    def check_lmstudio(self) -> Dict[str, Any]:
        """Check LMStudio server status and loaded models.

        Uses the configured API token for authentication when available.

        Returns:
            Dict with ``status``, ``models_loaded``, and ``model_ids`` on
            success, or ``status`` and ``error`` on failure.
        """
        import requests

        base_url = self._get_config_value("lmstudio.base_url", "http://localhost:1234")
        token = self._get_config_value("lmstudio.api_token", "")
        headers: Dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            r = requests.get(f"{base_url}/api/v1/models", headers=headers, timeout=5)
            data = r.json()
            models = [m.get("id", "unknown") for m in data.get("data", [])]
            return {
                "status": "online",
                "models_loaded": len(models),
                "model_ids": models,
            }
        except Exception as exc:
            return {"status": "offline", "error": str(exc)}

    # ── Nexus storage ────────────────────────────────────────────

    def _store_single_result(self, result: TaskResult, task_type: str) -> None:
        """Store a single task result in Nexus.

        Args:
            result: The completed task result.
            task_type: The structured task type label.
        """
        try:
            self.nexus.add_entry(
                title=f"LMS Task [{task_type}]: {result.task_id}",
                content=(
                    f"Model: {result.model}\n"
                    f"Latency: {result.latency_ms:.0f}ms\n"
                    f"TPS: {result.tps:.1f}\n"
                    f"Output:\n{result.output[:3000]}"
                ),
                content_type="note",
                category="lms_tasks",
                tags=["lms-bridge", task_type, result.model],
            )
        except Exception as exc:
            logger.warning("Failed to store task result: %s", exc)

    def _store_batch_results(self, results: List[TaskResult]) -> None:
        """Store batch results summary in Nexus.

        Args:
            results: List of completed/failed task results.
        """
        completed = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]

        summary = (
            f"Batch: {len(results)} tasks\n"
            f"Completed: {len(completed)}\n"
            f"Failed: {len(failed)}\n"
        )
        if completed:
            avg_latency = sum(r.latency_ms for r in completed) / len(completed)
            avg_tps = sum(r.tps for r in completed) / len(completed)
            summary += f"Avg latency: {avg_latency:.0f}ms\nAvg TPS: {avg_tps:.1f}\n"

        try:
            self.nexus.add_entry(
                title=f"LMS Batch: {len(results)} tasks",
                content=summary,
                content_type="note",
                category="lms_tasks",
                tags=["lms-bridge", "batch"],
            )
        except Exception as exc:
            logger.warning("Failed to store batch results: %s", exc)
