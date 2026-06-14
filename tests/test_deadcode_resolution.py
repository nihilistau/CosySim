"""
Dead-code resolution tests (v1.60.0 "Living Systems")
=====================================================

Pins the audit verdict for the three modules flagged as dead code:

  1. ``engine.lmstudio.task_queue`` — WIRED. Was functionally dead (the
     ``lms_submit_task`` skill enqueued tasks but no path ever started the
     worker pool, so tasks sat permanently QUEUED). v1.60.0 makes the pool
     auto-start lazily on first ``submit()``. These tests prove a submitted
     task is actually dispatched and completed end-to-end (with a mocked LMS
     client, so they are hermetic and require no live LMStudio).

  2. ``training.finetune_orchestrator`` — KEPT (verified reachable). Wired into
     three registered scheduler tasks via ``engine.nexus.scheduler_daemon``.

  3. ``training.auto_train`` — KEPT (verified reachable). ``check_and_train_all_zoo``
     is wired into the registered ``model-zoo-train`` scheduler task.

All tests reset the relevant singletons so parallel suite runs do not leak
worker threads or queue state.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Initial dead-code resolution proof suite.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──── Hermetic config ────────────────────────────────────────────────────────

def _queue_config(overrides: dict | None = None):
    """A mock config exposing the task_queue_v2 + affinity keys the queue reads."""
    defaults = {
        "lmstudio.task_queue_v2.workers": 1,
        "lmstudio.task_queue_v2.max_queue_depth": 16,
        "lmstudio.task_queue_v2.auto_start": True,
        "lmstudio.task_queue.affinity": {},
        "lmstudio.models.primary.path": "qwen3-8b",
    }
    if overrides:
        defaults.update(overrides)
    cfg = MagicMock()
    cfg.get = lambda key, default=None: defaults.get(key, default)
    return cfg


# ──── 1. task_queue — imports resolve after the wiring change ─────────────────

def test_package_imports_resolve_after_changes():
    """The owned package + new symbol still import cleanly (regression guard)."""
    import engine.lmstudio as lms

    assert hasattr(lms, "TaskQueue")
    assert hasattr(lms, "get_task_queue")
    assert hasattr(lms, "reset_task_queue")  # new in v1.60.0
    assert "reset_task_queue" in lms.__all__
    # The training modules under audit must import without side effects.
    import training.finetune_orchestrator as fo
    import training.auto_train as at
    assert hasattr(fo, "get_finetune_orchestrator")
    assert hasattr(at, "check_and_train_all_zoo")


# ──── 1. task_queue — the loop is now closed (auto-start dispatch) ────────────

class TestTaskQueueWiring:
    """Prove the queue actually executes work — the previously-dead path."""

    def _fake_client(self, content: str = "wired-result", tokens: int = 7):
        client = MagicMock()
        resp = MagicMock()
        resp.content = content
        resp.tokens_used = tokens
        client.chat.return_value = resp
        return client

    def test_submit_auto_starts_workers_and_completes(self):
        """submit() spins up the pool and the task reaches COMPLETED."""
        from engine.lmstudio.task_queue import TaskQueue, TaskType, TaskStatus

        q = TaskQueue(config=_queue_config())
        assert not q._started  # nothing running yet

        fake = self._fake_client("hello-from-worker", tokens=11)
        with patch("engine.lmstudio.lms_client.get_lms_client", return_value=fake):
            # model_hint short-circuits _resolve_model so no server_controller is hit
            task = q.submit(TaskType.CHAT, prompt="ping", model_hint="qwen3-8b")
            assert q._started, "submit() must auto-start the worker pool"

            done = q.wait_for(task.id, timeout=10)

        assert done is not None
        assert done.status == TaskStatus.COMPLETED
        assert done.result == "hello-from-worker"
        assert done.assigned_model == "qwen3-8b"
        assert done.tokens_used == 11
        fake.chat.assert_called_once()
        q.shutdown()

    def test_auto_start_disabled_leaves_task_queued(self):
        """With auto_start False the loop stays open (proves the wiring is the fix)."""
        from engine.lmstudio.task_queue import TaskQueue, TaskType, TaskStatus

        q = TaskQueue(config=_queue_config({"lmstudio.task_queue_v2.auto_start": False}))
        task = q.submit(TaskType.CHAT, prompt="ping", model_hint="qwen3-8b")
        assert not q._started
        # No worker → task never leaves the queue.
        time.sleep(0.2)
        assert task.status == TaskStatus.QUEUED
        assert q.queue_depth == 1
        q.shutdown()

    def test_priority_ordering_executes_high_first(self):
        """Higher-priority work is dispatched ahead of lower-priority work."""
        from engine.lmstudio.task_queue import TaskQueue, TaskType, TaskPriority

        order: list[str] = []
        client = MagicMock()

        def _chat(messages, **kwargs):
            order.append(messages[-1]["content"])
            resp = MagicMock()
            resp.content = "ok"
            resp.tokens_used = 1
            time.sleep(0.01)
            return resp

        client.chat.side_effect = _chat

        # Single worker, do NOT auto-start: enqueue everything, then start once
        # so ordering is deterministic.
        q = TaskQueue(config=_queue_config({"lmstudio.task_queue_v2.auto_start": False}))
        with patch("engine.lmstudio.lms_client.get_lms_client", return_value=client):
            low = q.submit(TaskType.CHAT, prompt="low", model_hint="m",
                           priority=TaskPriority.LOW)
            high = q.submit(TaskType.CHAT, prompt="high", model_hint="m",
                            priority=TaskPriority.REALTIME)
            q.start(num_workers=1)
            q.wait_for(low.id, timeout=10)
            q.wait_for(high.id, timeout=10)

        assert order[0] == "high", f"expected high-priority first, got {order}"
        q.shutdown()

    def test_metrics_recorded_on_completion(self):
        """Completed tasks feed the queue metrics (observability hook works)."""
        from engine.lmstudio.task_queue import TaskQueue, TaskType

        fake = self._fake_client(tokens=5)
        q = TaskQueue(config=_queue_config())
        with patch("engine.lmstudio.lms_client.get_lms_client", return_value=fake):
            t = q.submit(TaskType.CODE, prompt="x", model_hint="qwen3-8b")
            q.wait_for(t.id, timeout=10)

        status = q.get_status()
        assert status["metrics"]["total_completed"] >= 1
        assert status["metrics"]["total_tokens"] >= 5
        q.shutdown()


# ──── 1. task_queue — singleton reset is hermetic ────────────────────────────

def test_reset_task_queue_clears_singleton():
    """reset_task_queue() shuts down workers and discards the global instance."""
    from engine.lmstudio import task_queue as tq

    tq.reset_task_queue()  # clean slate
    q1 = tq.get_task_queue(config=_queue_config())
    assert tq.get_task_queue() is q1  # same singleton
    tq.reset_task_queue()
    # After reset a brand-new instance is created.
    q2 = tq.get_task_queue(config=_queue_config())
    assert q2 is not q1
    tq.reset_task_queue()


# ──── 2 & 3. finetune_orchestrator + auto_train are REACHABLE ────────────────

class TestTrainingReachability:
    """Prove the 'orphaned' training modules are actually wired into scheduling."""

    def _fresh_daemon(self, tmp_path: Path):
        from engine.nexus.scheduler_daemon import TaskSchedulerDaemon
        # Isolated state file + disabled timeout so no shared global state leaks.
        return TaskSchedulerDaemon(
            state_path=tmp_path / "sched_state.json",
            default_timeout=0,
        )

    def test_finetune_orchestrator_wired_into_scheduler(self, tmp_path):
        """finetune_orchestrator is reachable via registered scheduler tasks."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = self._fresh_daemon(tmp_path)
        _register_builtin_tasks(daemon)

        tasks = daemon._tasks
        # The two tasks whose callbacks import get_finetune_orchestrator.
        assert "finetune-if-ready" in tasks
        assert "router-finetune-cycle" in tasks
        # Callbacks are zero-arg callables (the scheduler contract).
        assert callable(tasks["finetune-if-ready"].callback)
        assert callable(tasks["router-finetune-cycle"].callback)

    def test_auto_train_wired_into_scheduler(self, tmp_path):
        """auto_train.check_and_train_all_zoo is reachable via 'model-zoo-train'."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = self._fresh_daemon(tmp_path)
        _register_builtin_tasks(daemon)

        assert "model-zoo-train" in daemon._tasks
        assert callable(daemon._tasks["model-zoo-train"].callback)

    def test_finetune_callback_invokes_orchestrator(self, tmp_path):
        """The registered callback genuinely drives the orchestrator (not a stub).

        We stub the heavy collaborators (dataset manager + orchestrator) and assert
        the callback reaches ``get_finetune_orchestrator().submit`` through the
        real scheduler-registered code path.
        """
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = self._fresh_daemon(tmp_path)
        _register_builtin_tasks(daemon)
        callback = daemon._tasks["finetune-if-ready"].callback

        fake_orch = MagicMock()
        fake_orch.list_jobs.return_value = []
        fake_job = MagicMock()
        fake_job.job_id = "job123"
        fake_orch.submit.return_value = fake_job

        fake_mgr = MagicMock()
        # Report one model type over the 500-example threshold.
        fake_mgr.status.return_value = {"router_v2": {"train": 600}}

        with patch("training.finetune_orchestrator.get_finetune_orchestrator",
                   return_value=fake_orch), \
             patch("training.micro_datasets.MicroDatasetManager",
                   return_value=fake_mgr), \
             patch("training.micro_datasets.MODELS", ["router_v2"]):
            result = callback()

        # The orchestrator was actually driven through the registered path.
        assert fake_orch.submit.called
        assert "submitted" in result
        assert any("router_v2" in s for s in result["submitted"])


def test_finetune_orchestrator_singleton_constructs(tmp_path):
    """get_finetune_orchestrator() constructs without requiring live services."""
    from training import finetune_orchestrator as fo

    # Reset the module-level singleton so we exercise fresh construction.
    fo._instance = None
    orch = fo.get_finetune_orchestrator()
    assert orch is fo.get_finetune_orchestrator()  # idempotent singleton
    status = orch.queue_status()
    assert "jobs" in status and "total" in status
    fo._instance = None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
