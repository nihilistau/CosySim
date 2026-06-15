"""
Scheduler Hardening Tests
=========================

Hermetic tests for v1.60.0 scheduler hardening: per-task timeout enforcement and
honest "not implemented" stubs.

These tests construct fresh ``TaskSchedulerDaemon`` instances pointed at a temp
state file — they never touch the shared singleton or ``data/scheduler_state.json``,
so they are safe to run in parallel with other agents.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Initial: timeout enforcement, honest stubs, status fields.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from engine.nexus.scheduler_daemon import (
    TaskSchedulerDaemon,
    ScheduledTask,
    make_not_implemented,
    _is_not_implemented_result,
    _NOT_IMPLEMENTED_MARKER,
    parse_schedule_seconds,
)


# ──── Fixtures ────

@pytest.fixture()
def daemon(tmp_path: Path) -> TaskSchedulerDaemon:
    """Fresh daemon with an isolated state file and a tiny default timeout."""
    state = tmp_path / "sched_state.json"
    # Explicit default_timeout keeps the test independent of config/data state.
    return TaskSchedulerDaemon(state_path=state, default_timeout=1.0)


# ──── Schedule Parsing (sanity, unchanged behaviour) ────

def test_parse_schedule_seconds_known_and_interval() -> None:
    assert parse_schedule_seconds("daily") == 24 * 3600
    assert parse_schedule_seconds("weekly") == 7 * 24 * 3600
    assert parse_schedule_seconds("every_8h") == 8 * 3600
    assert parse_schedule_seconds("every_15m") == 15 * 60
    with pytest.raises(ValueError):
        parse_schedule_seconds("nonsense")


# ──── Timeout Enforcement ────

def test_hung_task_is_abandoned_and_does_not_block(daemon: TaskSchedulerDaemon) -> None:
    """A task that sleeps far past its timeout is abandoned quickly."""
    started = threading.Event()

    def hang() -> str:
        started.set()
        time.sleep(30)  # would block the loop for 30s without enforcement
        return "never returns in time"

    daemon.register("hang", "Hangs", "every_1m", hang, timeout=0.3)

    t0 = time.time()
    result = daemon.run_task("hang")
    elapsed = time.time() - t0

    assert started.is_set(), "worker should have started"
    assert result["success"] is False
    assert result.get("timed_out") is True
    # Must return promptly (cap 0.3s) — generous ceiling for CI jitter.
    assert elapsed < 5.0, f"abandon took too long: {elapsed:.2f}s"

    status = daemon.status()
    task = next(t for t in status["tasks"] if t["id"] == "hang")
    assert task["timeout_count"] == 1
    assert task["error_count"] == 1
    assert status["total_timeouts"] == 1
    assert "TIMEOUT" in task["last_result"]


def test_fast_task_completes_normally(daemon: TaskSchedulerDaemon) -> None:
    """A quick task under the timeout reports success and a real result."""
    daemon.register("fast", "Fast", "every_1m", lambda: {"ok": 1}, timeout=5.0)
    result = daemon.run_task("fast")

    assert result["success"] is True
    assert result.get("timed_out") is None
    assert "ok" in result["result"]

    status = daemon.status()
    task = next(t for t in status["tasks"] if t["id"] == "fast")
    assert task["run_count"] == 1
    assert task["error_count"] == 0
    assert task["timeout_count"] == 0


def test_per_task_timeout_overrides_default(daemon: TaskSchedulerDaemon) -> None:
    """Per-task timeout is used over the daemon default."""

    def hang() -> None:
        time.sleep(30)

    # Daemon default is 1.0s; per-task 0.2s should win and abandon faster.
    daemon.register("hang", "Hangs", "every_1m", hang, timeout=0.2)
    t0 = time.time()
    result = daemon.run_task("hang")
    elapsed = time.time() - t0
    assert result.get("timed_out") is True
    assert elapsed < 1.0  # would be >= 1.0 if the default had been applied


def test_default_timeout_applies_when_unset(daemon: TaskSchedulerDaemon) -> None:
    """A task with no explicit timeout inherits the daemon default."""

    def hang() -> None:
        time.sleep(30)

    daemon.register("hang", "Hangs", "every_1m", hang)  # no timeout -> default 1.0s
    status_task = next(
        t for t in daemon.status()["tasks"] if t["id"] == "hang"
    )
    assert status_task["timeout_s"] == 1.0

    t0 = time.time()
    result = daemon.run_task("hang")
    elapsed = time.time() - t0
    assert result.get("timed_out") is True
    # Default 1.0s cap -> abandon around 1s, well before the 30s sleep.
    assert 0.8 <= elapsed < 5.0


def test_zero_timeout_disables_enforcement(daemon: TaskSchedulerDaemon) -> None:
    """timeout <= 0 runs the callback inline with no cap."""
    daemon.register("inline", "Inline", "every_1m", lambda: "done", timeout=0)
    result = daemon.run_task("inline")
    assert result["success"] is True
    assert "done" in result["result"]
    # Effective timeout exposed as 0.0 (disabled).
    task = next(t for t in daemon.status()["tasks"] if t["id"] == "inline")
    assert task["timeout_s"] == 0.0


def test_raising_task_recorded_as_error_not_timeout(daemon: TaskSchedulerDaemon) -> None:
    """A callback that raises is an error, distinct from a timeout."""

    def boom() -> None:
        raise RuntimeError("kaboom")

    daemon.register("boom", "Boom", "every_1m", boom, timeout=5.0)
    result = daemon.run_task("boom")
    assert result["success"] is False
    assert result.get("timed_out") is None
    assert "kaboom" in result["error"]

    task = next(t for t in daemon.status()["tasks"] if t["id"] == "boom")
    assert task["error_count"] == 1
    assert task["timeout_count"] == 0


# ──── Honest Stubs ────

def test_make_not_implemented_logs_once_and_returns_sentinel(caplog) -> None:
    cb = make_not_implemented("demo_op")
    with caplog.at_level("WARNING"):
        out = cb()
    assert _is_not_implemented_result(out)
    assert out[_NOT_IMPLEMENTED_MARKER] is True
    assert out["operation"] == "demo_op"
    # Exactly one clear warning, in Oracle format.
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "not implemented" in msg.lower()
    assert "operation=demo_op" in msg


def test_register_stub_records_not_implemented(daemon: TaskSchedulerDaemon, caplog) -> None:
    daemon.register_stub("todo-task", "Future Feature", "daily", operation="future_feat")
    with caplog.at_level("WARNING"):
        result = daemon.run_task("todo-task")

    assert result["success"] is True
    assert result.get("not_implemented") is True
    assert result["result"] == "not_implemented"

    task = next(t for t in daemon.status()["tasks"] if t["id"] == "todo-task")
    assert task["last_result"] == "NOT IMPLEMENTED"
    assert task["run_count"] == 1
    # Not counted as an error — it is an honest, deliberate no-op.
    assert task["error_count"] == 0

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("operation=future_feat" in r.getMessage() for r in warnings)


def test_stub_does_not_inflate_error_rate(daemon: TaskSchedulerDaemon) -> None:
    daemon.register_stub("todo", "TODO", "daily")
    daemon.run_task("todo")
    status = daemon.status()
    assert status["total_errors"] == 0
    assert status["error_rate_pct"] == 0.0


# ──── State Persistence ────

def test_timeout_count_persists_across_reload(tmp_path: Path) -> None:
    state = tmp_path / "persist.json"

    def hang() -> None:
        time.sleep(30)

    d1 = TaskSchedulerDaemon(state_path=state, default_timeout=0.2)
    d1.register("hang", "Hang", "every_1m", hang)
    d1.run_task("hang")
    assert d1.status()["total_timeouts"] == 1

    # Fresh daemon loads persisted state and re-registers; counters survive.
    d2 = TaskSchedulerDaemon(state_path=state, default_timeout=0.2)
    d2.register("hang", "Hang", "every_1m", hang)
    task = next(t for t in d2.status()["tasks"] if t["id"] == "hang")
    assert task["timeout_count"] == 1


# ──── run_due integration ────

def test_run_due_executes_with_timeout(daemon: TaskSchedulerDaemon) -> None:
    """run_due() honours timeouts and never blocks on a hung task."""
    calls = {"fast": 0}

    def fast() -> str:
        calls["fast"] += 1
        return "ok"

    def hang() -> None:
        time.sleep(30)

    daemon.register("fast", "Fast", "every_1m", fast, timeout=5.0)
    daemon.register("hang", "Hang", "every_1m", hang, timeout=0.3)

    t0 = time.time()
    results = daemon.run_due()  # both are due (never run before)
    elapsed = time.time() - t0

    assert calls["fast"] == 1
    by_id = {r["task_id"]: r for r in results}
    assert by_id["fast"]["success"] is True
    assert by_id["hang"]["timed_out"] is True
    # The hung task must not have blocked the loop beyond its cap.
    assert elapsed < 5.0


def test_status_exposes_default_timeout(daemon: TaskSchedulerDaemon) -> None:
    assert daemon.status()["default_timeout_s"] == 1.0
