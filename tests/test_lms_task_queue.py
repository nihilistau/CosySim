"""
Tests for the LMS Task Bridge priority queue system.

Covers queue priority ordering, task submission/retrieval, retry logic,
queue stats, worker lifecycle, and backward compatibility with the
original synchronous API.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.lms_task_bridge import (
    LMSTaskBridge,
    Priority,
    QueuedTask,
    QueueWorker,
    TaskQueue,
    TaskResult,
    _ModelMetrics,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def task_queue():
    """An empty TaskQueue with a size limit of 50."""
    return TaskQueue(max_size=50)


@pytest.fixture
def mock_orchestrator():
    """A MagicMock that mimics the InferenceOrchestrator."""
    orch = MagicMock()
    resp = MagicMock()
    resp.content = "mock output"
    resp.usage = MagicMock()
    resp.usage.completion_tokens = 42
    orch.infer.return_value = resp
    return orch


@pytest.fixture
def bridge(mock_orchestrator):
    """LMSTaskBridge with mocked orchestrator and config."""
    with patch("engine.nexus.lms_task_bridge.LMSTaskBridge.orchestrator",
               new_callable=lambda: property(lambda self: mock_orchestrator)):
        b = LMSTaskBridge()
        b._orchestrator = mock_orchestrator
        yield b
        b.stop_workers(timeout=1.0)


# ── Priority enum ───────────────────────────────────────────────────────


class TestPriority:
    """Priority enum parsing and ordering."""

    def test_priority_ordering(self):
        """CRITICAL < HIGH < NORMAL < LOW < BACKGROUND."""
        assert Priority.CRITICAL < Priority.HIGH
        assert Priority.HIGH < Priority.NORMAL
        assert Priority.NORMAL < Priority.LOW
        assert Priority.LOW < Priority.BACKGROUND

    def test_from_str_known(self):
        """Recognises valid priority names (case-insensitive)."""
        assert Priority.from_str("critical") == Priority.CRITICAL
        assert Priority.from_str("HIGH") == Priority.HIGH
        assert Priority.from_str("Normal") == Priority.NORMAL

    def test_from_str_unknown_returns_normal(self):
        """Unknown strings fall back to NORMAL."""
        assert Priority.from_str("nonexistent") == Priority.NORMAL
        assert Priority.from_str("") == Priority.NORMAL


# ── TaskQueue ───────────────────────────────────────────────────────────


class TestTaskQueue:
    """TaskQueue enqueue, dequeue, peek, cancel, stats."""

    def test_enqueue_dequeue_fifo_within_priority(self, task_queue):
        """Same-priority tasks are dequeued in FIFO order."""
        t1 = QueuedTask(task_id="a", priority=Priority.NORMAL, prompt="p1")
        t2 = QueuedTask(task_id="b", priority=Priority.NORMAL, prompt="p2")
        task_queue.enqueue(t1)
        task_queue.enqueue(t2)

        out1 = task_queue.dequeue(timeout=0.1)
        out2 = task_queue.dequeue(timeout=0.1)
        assert out1 is not None and out1.task_id == "a"
        assert out2 is not None and out2.task_id == "b"

    def test_priority_ordering(self, task_queue):
        """Higher-priority tasks are dequeued first."""
        low = QueuedTask(task_id="low", priority=Priority.LOW, prompt="p")
        high = QueuedTask(task_id="high", priority=Priority.HIGH, prompt="p")
        crit = QueuedTask(task_id="crit", priority=Priority.CRITICAL, prompt="p")

        task_queue.enqueue(low)
        task_queue.enqueue(high)
        task_queue.enqueue(crit)

        assert task_queue.dequeue(timeout=0.1).task_id == "crit"
        assert task_queue.dequeue(timeout=0.1).task_id == "high"
        assert task_queue.dequeue(timeout=0.1).task_id == "low"

    def test_peek_returns_highest_priority(self, task_queue):
        """peek() returns the next task without removing it."""
        t1 = QueuedTask(task_id="bg", priority=Priority.BACKGROUND, prompt="p")
        t2 = QueuedTask(task_id="hi", priority=Priority.HIGH, prompt="p")
        task_queue.enqueue(t1)
        task_queue.enqueue(t2)

        peeked = task_queue.peek()
        assert peeked is not None and peeked.task_id == "hi"
        assert task_queue.size == 2

    def test_peek_empty_queue(self, task_queue):
        """peek() returns None on an empty queue."""
        assert task_queue.peek() is None

    def test_dequeue_empty_returns_none(self, task_queue):
        """dequeue() with timeout returns None when empty."""
        assert task_queue.dequeue(timeout=0.05) is None

    def test_size_property(self, task_queue):
        """size reflects the number of un-dequeued tasks."""
        assert task_queue.size == 0
        task_queue.enqueue(QueuedTask(task_id="x", priority=Priority.NORMAL, prompt="p"))
        assert task_queue.size == 1

    def test_clear(self, task_queue):
        """clear() empties the queue and returns removed count."""
        for i in range(5):
            task_queue.enqueue(QueuedTask(task_id=f"t{i}", priority=Priority.NORMAL, prompt="p"))
        removed = task_queue.clear()
        assert removed == 5
        assert task_queue.size == 0

    def test_cancel_task(self, task_queue):
        """cancel() marks a task so workers will skip it."""
        task_queue.enqueue(QueuedTask(task_id="c1", priority=Priority.NORMAL, prompt="p"))
        assert task_queue.cancel("c1") is True
        assert task_queue.is_cancelled("c1") is True
        assert task_queue.cancel("nonexistent") is False

    def test_get_stats(self, task_queue):
        """get_stats() returns correct totals."""
        task_queue.enqueue(QueuedTask(task_id="s1", priority=Priority.NORMAL, prompt="p"))
        task_queue.enqueue(QueuedTask(task_id="s2", priority=Priority.NORMAL, prompt="p"))
        task_queue.dequeue(timeout=0.1)

        stats = task_queue.get_stats()
        assert stats["total_enqueued"] == 2
        assert stats["total_dequeued"] == 1
        assert stats["depth"] == 1

    def test_queue_full_rejects(self):
        """Enqueue returns False when queue is at max capacity."""
        q = TaskQueue(max_size=1)
        assert q.enqueue(QueuedTask(task_id="ok", priority=Priority.NORMAL, prompt="p"))
        assert q.enqueue(QueuedTask(task_id="fail", priority=Priority.NORMAL, prompt="p")) is False


# ── QueueWorker ─────────────────────────────────────────────────────────


class TestQueueWorker:
    """Worker start/stop lifecycle, retry, and task execution."""

    def _make_worker(self, tq, execute_fn, *, retry_max=0, fallback=""):
        """Helper to construct a worker with shared result stores."""
        results: dict = {}
        events: dict = {}
        metrics: dict = {}
        worker = QueueWorker(
            worker_id="test",
            task_queue=tq,
            execute_fn=execute_fn,
            result_store=results,
            result_events=events,
            retry_max=retry_max,
            fallback_model=fallback,
            model_metrics=metrics,
        )
        return worker, results, events, metrics

    def test_worker_start_stop(self):
        """Worker thread starts and stops cleanly."""
        tq = TaskQueue()
        worker, _, _, _ = self._make_worker(tq, lambda t: TaskResult(task_id=t.task_id, status="completed"))
        worker.start()
        assert worker.is_running
        worker.stop(timeout=2.0)
        assert not worker.is_running

    def test_worker_processes_task(self):
        """Worker dequeues and executes a task, publishing the result."""
        tq = TaskQueue()
        results: dict = {}
        events: dict = {}
        evt = threading.Event()
        events["w1"] = evt

        def execute(t):
            return TaskResult(task_id=t.task_id, status="completed", output="done")

        worker = QueueWorker(
            worker_id="proc",
            task_queue=tq,
            execute_fn=execute,
            result_store=results,
            result_events=events,
            retry_max=0,
            model_metrics={},
        )

        tq.enqueue(QueuedTask(task_id="w1", priority=Priority.NORMAL, prompt="hello"))
        worker.start()
        evt.wait(timeout=3.0)
        worker.stop(timeout=2.0)

        assert "w1" in results
        assert results["w1"].status == "completed"

    def test_retry_on_failure(self):
        """Worker retries up to retry_max times with backoff."""
        tq = TaskQueue()
        call_count = 0

        def flaky_execute(t):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return TaskResult(task_id=t.task_id, status="failed", error="boom")
            return TaskResult(task_id=t.task_id, status="completed", output="ok")

        results: dict = {}
        events: dict = {}
        evt = threading.Event()
        events["r1"] = evt

        worker = QueueWorker(
            worker_id="retry",
            task_queue=tq,
            execute_fn=flaky_execute,
            result_store=results,
            result_events=events,
            retry_max=3,
            retry_backoff=[0.01, 0.01, 0.01],
            model_metrics={},
        )

        tq.enqueue(QueuedTask(task_id="r1", priority=Priority.NORMAL, prompt="p"))
        worker.start()
        evt.wait(timeout=5.0)
        worker.stop(timeout=2.0)

        assert results["r1"].status == "completed"
        assert call_count == 3

    def test_callback_invoked(self):
        """Callback function is called with the result."""
        tq = TaskQueue()
        callback_results = []

        def execute(t):
            return TaskResult(task_id=t.task_id, status="completed", output="cb")

        results: dict = {}
        events: dict = {}
        evt = threading.Event()
        events["cb1"] = evt

        worker = QueueWorker(
            worker_id="cb",
            task_queue=tq,
            execute_fn=execute,
            result_store=results,
            result_events=events,
            retry_max=0,
            model_metrics={},
        )

        tq.enqueue(QueuedTask(
            task_id="cb1", priority=Priority.NORMAL, prompt="p",
            callback=lambda r: callback_results.append(r),
        ))
        worker.start()
        evt.wait(timeout=3.0)
        worker.stop(timeout=2.0)

        assert len(callback_results) == 1
        assert callback_results[0].output == "cb"


# ── ModelMetrics ────────────────────────────────────────────────────────


class TestModelMetrics:
    """Per-model metric tracking."""

    def test_success_tracking(self):
        """record_success accumulates latency and count."""
        m = _ModelMetrics()
        m.record_success(100.0)
        m.record_success(200.0)
        d = m.to_dict()
        assert d["total"] == 2
        assert d["successes"] == 2
        assert d["avg_latency_ms"] == 150.0
        assert d["success_rate"] == 1.0

    def test_failure_tracking(self):
        """record_failure increments failure count."""
        m = _ModelMetrics()
        m.record_failure()
        m.record_success(100.0)
        d = m.to_dict()
        assert d["total"] == 2
        assert d["failures"] == 1
        assert d["success_rate"] == 0.5


# ── LMSTaskBridge (async API) ──────────────────────────────────────────


class TestBridgeAsyncSubmission:
    """submit(), get_result(), cancel(), queue_stats()."""

    def test_submit_returns_task_id(self, bridge, mock_orchestrator):
        """submit() returns a string task_id immediately."""
        task_id = bridge.submit("hello world", priority="normal")
        assert isinstance(task_id, str)
        assert task_id.startswith("lms-")

    def test_submit_and_get_result(self, bridge, mock_orchestrator):
        """Submitted task can be retrieved via get_result()."""
        task_id = bridge.submit("test prompt", priority="high")
        result = bridge.get_result(task_id, timeout=5.0)
        assert result is not None
        assert result.status == "completed"
        assert result.output == "mock output"

    def test_submit_batch(self, bridge, mock_orchestrator):
        """submit_batch() returns multiple task_ids, all resolve."""
        ids = bridge.submit_batch(["p1", "p2", "p3"], priority="normal")
        assert len(ids) == 3
        results = bridge.get_results(ids, timeout=5.0)
        assert all(r is not None and r.status == "completed" for r in results.values())

    def test_cancel_queued_task(self, bridge, mock_orchestrator):
        """cancel() marks a not-yet-running task as cancelled."""
        # Stop workers so the task stays queued
        bridge.stop_workers(timeout=1.0)
        bridge._workers_started = False
        bridge._ensure_queue()

        task_id = bridge._next_id()
        evt = threading.Event()
        bridge._result_events[task_id] = evt

        task = QueuedTask(task_id=task_id, priority=Priority.LOW, prompt="cancel me")
        bridge._queue.enqueue(task)

        assert bridge.cancel(task_id) is True
        result = bridge._result_store.get(task_id)
        assert result is not None
        assert result.status == "cancelled"

    def test_queue_stats_structure(self, bridge, mock_orchestrator):
        """queue_stats() returns the expected keys."""
        task_id = bridge.submit("stat test")
        bridge.get_result(task_id, timeout=5.0)

        stats = bridge.queue_stats()
        assert "queue" in stats
        assert "workers" in stats
        assert "total_tasks" in stats
        assert "success_rate" in stats
        assert "avg_latency_ms" in stats
        assert "per_model" in stats

    def test_get_result_timeout_returns_none(self, bridge, mock_orchestrator):
        """get_result() returns None when timeout expires and task is unfinished."""
        bridge.stop_workers(timeout=1.0)
        bridge._workers_started = False
        bridge._ensure_queue()

        task_id = bridge._next_id()
        evt = threading.Event()
        bridge._result_events[task_id] = evt

        task = QueuedTask(task_id=task_id, priority=Priority.NORMAL, prompt="slow")
        bridge._queue.enqueue(task)

        result = bridge.get_result(task_id, timeout=0.05)
        assert result is None


# ── LMSTaskBridge (backward compatibility) ─────────────────────────────


class TestBridgeBackwardCompat:
    """Existing synchronous API must still work unchanged."""

    def test_run_prompt(self, bridge, mock_orchestrator):
        """run_prompt() returns a completed TaskResult."""
        result = bridge.run_prompt("hello")
        assert result.ok
        assert result.output == "mock output"
        assert result.task_id.startswith("lms-")

    def test_run_batch(self, bridge, mock_orchestrator):
        """run_batch() processes multiple prompts sequentially."""
        results = bridge.run_batch([
            {"prompt": "a", "temperature": 0.5},
            {"prompt": "b"},
        ])
        assert len(results) == 2
        assert all(r.ok for r in results)

    def test_run_batch_skips_empty_prompts(self, bridge, mock_orchestrator):
        """run_batch() skips items without a 'prompt' key."""
        results = bridge.run_batch([{"prompt": ""}, {"prompt": "valid"}])
        assert len(results) == 1

    def test_run_task_original_types(self, bridge, mock_orchestrator):
        """run_task() works for all original 5 task types."""
        for tt in ("evaluate", "summarize", "generate", "classify", "compare"):
            result = bridge.run_task(tt, "test input")
            assert result.ok
            assert result.metadata["task_type"] == tt

    def test_run_task_new_types(self, bridge, mock_orchestrator):
        """run_task() works for the 6 new task types."""
        for tt in ("code_review", "security_check", "test_generate",
                    "doc_generate", "translate", "refactor"):
            result = bridge.run_task(tt, "test input")
            assert result.ok
            assert result.metadata["task_type"] == tt

    def test_task_result_to_dict(self):
        """TaskResult.to_dict() serialises all fields."""
        r = TaskResult(task_id="x", status="completed", output="hi", model="m")
        d = r.to_dict()
        assert d["task_id"] == "x"
        assert d["status"] == "completed"
        assert d["output"] == "hi"

    def test_check_lmstudio_with_auth(self, bridge):
        """check_lmstudio() sends the auth token from config."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"id": "model-a"}, {"id": "model-b"}],
        }

        with patch.object(bridge, "_get_config_value", side_effect=lambda k, d=None: {
            "lmstudio.base_url": "http://localhost:1234",
            "lmstudio.api_token": "sk-test-token",
        }.get(k, d)):
            with patch("requests.get", return_value=mock_response) as mock_get:
                status = bridge.check_lmstudio()

        assert status["status"] == "online"
        assert status["models_loaded"] == 2
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer sk-test-token"


# ── Worker lifecycle on bridge ──────────────────────────────────────────


class TestBridgeWorkerLifecycle:
    """start_workers() / stop_workers() on the bridge."""

    def test_start_and_stop_workers(self, bridge, mock_orchestrator):
        """Workers can be explicitly started and stopped."""
        bridge.start_workers()
        assert bridge._workers_started
        assert len(bridge._workers) >= 1

        bridge.stop_workers(timeout=2.0)
        assert not bridge._workers_started
        assert len(bridge._workers) == 0

    def test_auto_start_on_submit(self, bridge, mock_orchestrator):
        """Workers auto-start on first submit() call."""
        assert not bridge._workers_started
        bridge.submit("auto start test")
        assert bridge._workers_started
