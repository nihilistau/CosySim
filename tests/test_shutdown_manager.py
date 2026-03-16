"""Comprehensive tests for the Graceful Shutdown Manager.

Covers all public classes, enums, factory functions, signal installation,
singleton behaviour, edge cases, and phase execution ordering.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from unittest.mock import MagicMock, patch

import pytest

from engine.lifecycle.shutdown_manager import (
    PhaseResult,
    ShutdownHandler,
    ShutdownManager,
    ShutdownPhase,
    ShutdownReport,
    ShutdownState,
    create_database_flush_handler,
    create_flask_shutdown_handler,
    create_scheduler_drain_handler,
    create_thread_pool_drain_handler,
    get_shutdown_manager,
)


# ──── Helpers ──────────────────────────────────────────────────────────────


def _fresh_manager() -> ShutdownManager:
    """Create a brand-new ShutdownManager, bypassing the singleton."""
    return ShutdownManager()


def _noop() -> None:
    """No-op callback for handler registration."""


# ──── TestShutdownPhase ────────────────────────────────────────────────────


class TestShutdownPhase:
    """Verify the ShutdownPhase enum values and ordering."""

    def test_all_four_phases_exist(self) -> None:
        """All four expected shutdown phases are present."""
        names = {p.name for p in ShutdownPhase}
        assert names == {"DRAIN", "FLUSH", "CLOSE", "CLEANUP"}

    def test_phase_ordering(self) -> None:
        """DRAIN < FLUSH < CLOSE < CLEANUP in execution order."""
        assert ShutdownPhase.DRAIN.order < ShutdownPhase.FLUSH.order
        assert ShutdownPhase.FLUSH.order < ShutdownPhase.CLOSE.order
        assert ShutdownPhase.CLOSE.order < ShutdownPhase.CLEANUP.order


# ──── TestShutdownHandler ──────────────────────────────────────────────────


class TestShutdownHandler:
    """Verify the ShutdownHandler dataclass."""

    def test_handler_defaults(self) -> None:
        """Handler created with only required fields uses correct defaults."""
        h = ShutdownHandler(name="h1", phase=ShutdownPhase.CLOSE, callback=_noop)
        assert h.timeout == 10.0
        assert h.priority == 50
        assert h.critical is False

    def test_handler_all_fields(self) -> None:
        """Handler with all fields stores them faithfully."""
        h = ShutdownHandler(
            name="custom",
            phase=ShutdownPhase.DRAIN,
            callback=_noop,
            timeout=5.0,
            priority=1,
            critical=True,
        )
        assert h.name == "custom"
        assert h.phase == ShutdownPhase.DRAIN
        assert h.callback is _noop
        assert h.timeout == 5.0
        assert h.priority == 1
        assert h.critical is True

    def test_handler_dataclass_fields(self) -> None:
        """ShutdownHandler exposes the expected dataclass field names."""
        field_names = {f.name for f in fields(ShutdownHandler)}
        assert field_names == {"name", "phase", "callback", "timeout", "priority", "critical"}


# ──── TestShutdownState ────────────────────────────────────────────────────


class TestShutdownState:
    """Verify the ShutdownState enum."""

    def test_all_states_exist(self) -> None:
        """All five expected shutdown states are present."""
        names = {s.name for s in ShutdownState}
        assert names == {"RUNNING", "DRAINING", "SHUTTING_DOWN", "COMPLETED", "FORCED"}

    def test_initial_state_is_running(self) -> None:
        """A fresh ShutdownManager starts in RUNNING state."""
        mgr = _fresh_manager()
        assert mgr.state == ShutdownState.RUNNING


# ──── TestShutdownManager ──────────────────────────────────────────────────


class TestShutdownManager:
    """Tests for ShutdownManager registration, state, and shutdown logic."""

    def test_constructor_running_state(self) -> None:
        """Constructor initialises manager in RUNNING state."""
        mgr = _fresh_manager()
        assert mgr.state == ShutdownState.RUNNING
        assert mgr.is_shutting_down is False

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_register_stores_handler(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """register() stores the handler retrievable via get_handler_list."""
        mgr = _fresh_manager()
        h = ShutdownHandler(name="db-main", phase=ShutdownPhase.FLUSH, callback=_noop)
        mgr.register(h)
        names = [entry["name"] for entry in mgr.get_handler_list()]
        assert "db-main" in names

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_register_simple_defaults(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """register_simple creates a handler with CLOSE phase and 10s timeout."""
        mgr = _fresh_manager()
        mgr.register_simple("fast-close", _noop)
        handlers = mgr.get_handler_list()
        match = [h for h in handlers if h["name"] == "fast-close"]
        assert len(match) == 1
        assert match[0]["phase"] == "close"
        assert match[0]["timeout"] == 10.0

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_unregister_removes_handler(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """unregister() removes a previously registered handler."""
        mgr = _fresh_manager()
        mgr.register_simple("removable", _noop)
        mgr.unregister("removable")
        names = [h["name"] for h in mgr.get_handler_list()]
        assert "removable" not in names

    def test_unregister_unknown_raises(self) -> None:
        """unregister() raises KeyError for an unknown name."""
        mgr = _fresh_manager()
        with pytest.raises(KeyError, match="no-such-handler"):
            mgr.unregister("no-such-handler")

    def test_duplicate_handler_raises(self) -> None:
        """Registering a handler with a duplicate name raises ValueError."""
        mgr = _fresh_manager()
        mgr.register_simple("dup", _noop)
        with pytest.raises(ValueError, match="already registered"):
            mgr.register_simple("dup", _noop)

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_handlers_sorted_by_phase_then_priority(
        self, _nex_end: MagicMock, _nex_start: MagicMock
    ) -> None:
        """get_handler_list returns handlers in phase-order then priority-order."""
        mgr = _fresh_manager()
        mgr.register(ShutdownHandler(name="cleanup-z", phase=ShutdownPhase.CLEANUP, callback=_noop, priority=99))
        mgr.register(ShutdownHandler(name="drain-a", phase=ShutdownPhase.DRAIN, callback=_noop, priority=10))
        mgr.register(ShutdownHandler(name="drain-b", phase=ShutdownPhase.DRAIN, callback=_noop, priority=5))
        mgr.register(ShutdownHandler(name="flush-c", phase=ShutdownPhase.FLUSH, callback=_noop, priority=50))

        names = [h["name"] for h in mgr.get_handler_list()]
        assert names == ["drain-b", "drain-a", "flush-c", "cleanup-z"]

    def test_is_shutting_down_initially_false(self) -> None:
        """is_shutting_down is False on a fresh manager."""
        mgr = _fresh_manager()
        assert mgr.is_shutting_down is False

    def test_shutdown_event_not_set_initially(self) -> None:
        """shutdown_event is clear on a fresh manager."""
        mgr = _fresh_manager()
        assert not mgr.shutdown_event.is_set()

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_initiate_shutdown_changes_state(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """initiate_shutdown transitions state away from RUNNING."""
        mgr = _fresh_manager()
        mgr.initiate_shutdown(reason="test")
        assert mgr.state in (ShutdownState.COMPLETED, ShutdownState.FORCED)
        assert mgr.is_shutting_down is True

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_initiate_shutdown_idempotent(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """Second call to initiate_shutdown returns the cached report."""
        mgr = _fresh_manager()
        report1 = mgr.initiate_shutdown(reason="first")
        report2 = mgr.initiate_shutdown(reason="second")
        assert report1 is report2

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_handlers_execute_in_phase_order(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """Handlers across phases execute in DRAIN → FLUSH → CLOSE → CLEANUP order."""
        call_order: list[str] = []
        mgr = _fresh_manager()
        mgr.register(ShutdownHandler(name="cleanup-h", phase=ShutdownPhase.CLEANUP, callback=lambda: call_order.append("cleanup")))
        mgr.register(ShutdownHandler(name="drain-h", phase=ShutdownPhase.DRAIN, callback=lambda: call_order.append("drain")))
        mgr.register(ShutdownHandler(name="flush-h", phase=ShutdownPhase.FLUSH, callback=lambda: call_order.append("flush")))
        mgr.register(ShutdownHandler(name="close-h", phase=ShutdownPhase.CLOSE, callback=lambda: call_order.append("close")))

        mgr.initiate_shutdown(reason="order-test")
        assert call_order == ["drain", "flush", "close", "cleanup"]

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_handler_timeout_enforced(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """A handler that sleeps beyond its timeout is reported as timed out."""
        mgr = _fresh_manager()
        mgr.register(ShutdownHandler(
            name="slow",
            phase=ShutdownPhase.DRAIN,
            callback=lambda: time.sleep(5),
            timeout=0.2,
        ))
        report = mgr.initiate_shutdown(reason="timeout-test")
        assert report is not None
        drain_phase = [p for p in report.phases if p.phase == ShutdownPhase.DRAIN][0]
        assert drain_phase.timed_out == 1
        assert any("slow" in e["name"] for e in drain_phase.errors)

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_critical_handler_failure_aborts(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """A critical handler failing aborts further phases."""
        later_called = threading.Event()
        mgr = _fresh_manager()
        mgr.register(ShutdownHandler(
            name="critical-drain",
            phase=ShutdownPhase.DRAIN,
            callback=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            critical=True,
        ))
        mgr.register(ShutdownHandler(
            name="flush-should-not-run",
            phase=ShutdownPhase.FLUSH,
            callback=lambda: later_called.set(),
        ))

        report = mgr.initiate_shutdown(reason="critical-test")
        assert report is not None
        assert report.forced is True
        assert not later_called.is_set()

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_get_status_structure(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """get_status returns a dict with expected keys."""
        mgr = _fresh_manager()
        mgr.register_simple("s1", _noop, ShutdownPhase.DRAIN)
        status = mgr.get_status()
        assert "state" in status
        assert "handler_count" in status
        assert "phases" in status
        assert "signals_installed" in status
        assert "shutdown_event_set" in status
        assert "report" in status
        assert status["handler_count"] == 1
        assert status["state"] == "running"

    def test_get_handler_list_returns_all(self) -> None:
        """get_handler_list includes every registered handler."""
        mgr = _fresh_manager()
        mgr.register_simple("a", _noop, ShutdownPhase.DRAIN)
        mgr.register_simple("b", _noop, ShutdownPhase.FLUSH)
        mgr.register_simple("c", _noop, ShutdownPhase.CLOSE)
        handlers = mgr.get_handler_list()
        assert len(handlers) == 3
        assert {h["name"] for h in handlers} == {"a", "b", "c"}


# ──── TestPhaseExecution ───────────────────────────────────────────────────


class TestPhaseExecution:
    """Detailed tests for per-phase handler execution."""

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_all_handlers_in_phase_execute(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """Every handler registered for a phase is called."""
        calls: list[str] = []
        mgr = _fresh_manager()
        mgr.register(ShutdownHandler(name="f1", phase=ShutdownPhase.FLUSH, callback=lambda: calls.append("f1")))
        mgr.register(ShutdownHandler(name="f2", phase=ShutdownPhase.FLUSH, callback=lambda: calls.append("f2")))
        mgr.register(ShutdownHandler(name="f3", phase=ShutdownPhase.FLUSH, callback=lambda: calls.append("f3")))

        mgr.initiate_shutdown(reason="phase-all")
        assert sorted(calls) == ["f1", "f2", "f3"]

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_handler_exception_caught(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """A handler that raises is caught and recorded as failed."""
        mgr = _fresh_manager()
        mgr.register(ShutdownHandler(
            name="raiser",
            phase=ShutdownPhase.CLOSE,
            callback=lambda: (_ for _ in ()).throw(ValueError("bad")),
        ))
        report = mgr.initiate_shutdown(reason="exception-test")
        assert report is not None
        close_phase = [p for p in report.phases if p.phase == ShutdownPhase.CLOSE][0]
        assert close_phase.failed == 1
        assert any("raiser" in e["name"] for e in close_phase.errors)

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_handler_timeout_recorded(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """A timed-out handler is recorded in PhaseResult.timed_out."""
        mgr = _fresh_manager()
        mgr.register(ShutdownHandler(
            name="sleepy",
            phase=ShutdownPhase.FLUSH,
            callback=lambda: time.sleep(5),
            timeout=0.15,
        ))
        report = mgr.initiate_shutdown(reason="timeout-record")
        assert report is not None
        flush_phase = [p for p in report.phases if p.phase == ShutdownPhase.FLUSH][0]
        assert flush_phase.timed_out == 1
        assert flush_phase.succeeded == 0

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_priority_ordering_within_phase(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """Within a phase, lower priority runs first."""
        order: list[str] = []
        mgr = _fresh_manager()
        mgr.register(ShutdownHandler(name="p90", phase=ShutdownPhase.DRAIN, callback=lambda: order.append("p90"), priority=90))
        mgr.register(ShutdownHandler(name="p10", phase=ShutdownPhase.DRAIN, callback=lambda: order.append("p10"), priority=10))
        mgr.register(ShutdownHandler(name="p50", phase=ShutdownPhase.DRAIN, callback=lambda: order.append("p50"), priority=50))

        mgr.initiate_shutdown(reason="priority-test")
        assert order == ["p10", "p50", "p90"]

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_empty_phase_succeeds(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """A phase with no handlers produces a successful PhaseResult."""
        mgr = _fresh_manager()
        # Register only in DRAIN — other phases are empty
        mgr.register_simple("only-drain", _noop, ShutdownPhase.DRAIN)
        report = mgr.initiate_shutdown(reason="empty-phase")
        assert report is not None
        flush_phase = [p for p in report.phases if p.phase == ShutdownPhase.FLUSH][0]
        assert flush_phase.total_handlers == 0
        assert flush_phase.succeeded == 0
        assert flush_phase.failed == 0
        assert flush_phase.timed_out == 0

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_phase_result_correct_counts(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """PhaseResult has correct succeeded/failed/timed_out counts."""
        mgr = _fresh_manager()
        mgr.register(ShutdownHandler(name="ok1", phase=ShutdownPhase.CLOSE, callback=_noop, priority=10))
        mgr.register(ShutdownHandler(name="ok2", phase=ShutdownPhase.CLOSE, callback=_noop, priority=20))
        mgr.register(ShutdownHandler(
            name="fail1",
            phase=ShutdownPhase.CLOSE,
            callback=lambda: (_ for _ in ()).throw(RuntimeError("oops")),
            priority=30,
        ))
        mgr.register(ShutdownHandler(
            name="slow1",
            phase=ShutdownPhase.CLOSE,
            callback=lambda: time.sleep(5),
            timeout=0.15,
            priority=40,
        ))

        report = mgr.initiate_shutdown(reason="counts-test")
        assert report is not None
        close_phase = [p for p in report.phases if p.phase == ShutdownPhase.CLOSE][0]
        assert close_phase.total_handlers == 4
        assert close_phase.succeeded == 2
        assert close_phase.failed == 1
        assert close_phase.timed_out == 1


# ──── TestShutdownReport ───────────────────────────────────────────────────


class TestShutdownReport:
    """Tests for the ShutdownReport returned after shutdown."""

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_report_includes_all_phases(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """Report contains results for all four phases when shutdown completes fully."""
        mgr = _fresh_manager()
        report = mgr.initiate_shutdown(reason="report-phases")
        assert report is not None
        phase_names = {pr.phase for pr in report.phases}
        assert phase_names == {ShutdownPhase.DRAIN, ShutdownPhase.FLUSH, ShutdownPhase.CLOSE, ShutdownPhase.CLEANUP}

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_report_timing_is_reasonable(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """Report total_duration_ms is non-negative and below a generous ceiling."""
        mgr = _fresh_manager()
        mgr.register_simple("quick", _noop, ShutdownPhase.CLOSE)
        report = mgr.initiate_shutdown(reason="timing")
        assert report is not None
        assert report.total_duration_ms >= 0
        assert report.total_duration_ms < 5000  # well under 5 seconds

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_report_success_flag_correct(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """Success flag is True when all handlers succeed, False otherwise."""
        # Successful shutdown
        mgr_ok = _fresh_manager()
        mgr_ok.register_simple("good", _noop)
        report_ok = mgr_ok.initiate_shutdown(reason="success-test")
        assert report_ok is not None
        assert report_ok.success is True

        # Failing shutdown
        mgr_fail = _fresh_manager()
        mgr_fail.register(ShutdownHandler(
            name="bad",
            phase=ShutdownPhase.CLOSE,
            callback=lambda: (_ for _ in ()).throw(RuntimeError("fail")),
        ))
        report_fail = mgr_fail.initiate_shutdown(reason="fail-test")
        assert report_fail is not None
        assert report_fail.success is False


# ──── TestFactoryFunctions ─────────────────────────────────────────────────


class TestFactoryFunctions:
    """Tests for pre-built handler factory functions."""

    def test_create_database_flush_handler(self) -> None:
        """create_database_flush_handler returns a FLUSH-phase handler."""
        close_fn = MagicMock()
        h = create_database_flush_handler("orders", close_fn)
        assert isinstance(h, ShutdownHandler)
        assert h.name == "db-orders"
        assert h.phase == ShutdownPhase.FLUSH
        assert h.timeout == 15.0
        assert h.priority == 30
        assert h.critical is False
        # Verify the callback wraps our function
        h.callback()
        close_fn.assert_called_once()

    @patch("engine.lifecycle.shutdown_manager.get_task_scheduler", create=True)
    def test_create_scheduler_drain_handler(self, mock_sched: MagicMock) -> None:
        """create_scheduler_drain_handler returns a DRAIN-phase handler."""
        h = create_scheduler_drain_handler()
        assert isinstance(h, ShutdownHandler)
        assert h.name == "scheduler-drain"
        assert h.phase == ShutdownPhase.DRAIN
        assert h.timeout == 10.0
        assert h.priority == 20
        assert h.critical is False

    def test_create_thread_pool_drain_handler(self) -> None:
        """create_thread_pool_drain_handler returns a DRAIN-phase handler."""
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            h = create_thread_pool_drain_handler("worker-pool", pool)
            assert isinstance(h, ShutdownHandler)
            assert h.name == "threadpool-worker-pool"
            assert h.phase == ShutdownPhase.DRAIN
            assert h.timeout == 15.0
            assert h.priority == 40
            assert h.critical is False
        finally:
            pool.shutdown(wait=False)

    def test_create_flask_shutdown_handler(self) -> None:
        """create_flask_shutdown_handler returns a DRAIN-phase handler."""
        shutdown_fn = MagicMock()
        h = create_flask_shutdown_handler("hub", shutdown_fn)
        assert isinstance(h, ShutdownHandler)
        assert h.name == "flask-hub"
        assert h.phase == ShutdownPhase.DRAIN
        assert h.timeout == 10.0
        assert h.priority == 10
        assert h.critical is False
        h.callback()
        shutdown_fn.assert_called_once()


# ──── TestSignalHandlers ───────────────────────────────────────────────────


class TestSignalHandlers:
    """Tests for signal handler installation."""

    def test_install_signal_handlers_no_raise(self) -> None:
        """install_signal_handlers completes without raising."""
        mgr = _fresh_manager()
        mgr.install_signal_handlers()
        assert mgr._signals_installed is True

    def test_install_signal_handlers_idempotent(self) -> None:
        """Calling install_signal_handlers twice is a no-op the second time."""
        mgr = _fresh_manager()
        mgr.install_signal_handlers()
        mgr.install_signal_handlers()  # should not raise
        assert mgr._signals_installed is True


# ──── TestSingleton ────────────────────────────────────────────────────────


class TestSingleton:
    """Tests for the get_shutdown_manager singleton accessor."""

    def test_singleton_returns_same_instance(self) -> None:
        """get_shutdown_manager returns the same object on repeated calls."""
        with patch.dict("engine.lifecycle.shutdown_manager.__dict__", {"_INSTANCE": None}):
            a = get_shutdown_manager()
            b = get_shutdown_manager()
            assert a is b

    def test_singleton_thread_safe(self) -> None:
        """Concurrent calls to get_shutdown_manager converge on one instance."""
        results: list[ShutdownManager] = []
        barrier = threading.Barrier(4)

        def _get() -> None:
            barrier.wait()
            results.append(get_shutdown_manager())

        with patch.dict("engine.lifecycle.shutdown_manager.__dict__", {"_INSTANCE": None}):
            threads = [threading.Thread(target=_get) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        assert len(results) == 4
        assert all(r is results[0] for r in results)


# ──── TestEdgeCases ────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge-case and boundary-condition tests."""

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_shutdown_no_handlers(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """Shutdown with zero registered handlers succeeds cleanly."""
        mgr = _fresh_manager()
        report = mgr.initiate_shutdown(reason="empty")
        assert report is not None
        assert report.success is True
        assert report.forced is False
        assert sum(p.total_handlers for p in report.phases) == 0

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_shutdown_only_cleanup_handlers(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """Shutdown with handlers only in CLEANUP phase runs successfully."""
        called = threading.Event()
        mgr = _fresh_manager()
        mgr.register(ShutdownHandler(
            name="cleanup-only",
            phase=ShutdownPhase.CLEANUP,
            callback=lambda: called.set(),
        ))

        report = mgr.initiate_shutdown(reason="cleanup-only-test")
        assert report is not None
        assert report.success is True
        assert called.is_set()
        cleanup_phase = [p for p in report.phases if p.phase == ShutdownPhase.CLEANUP][0]
        assert cleanup_phase.succeeded == 1

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_handler_modifies_state_during_execution(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """A handler that sets the shutdown_event during execution is safe."""
        mgr = _fresh_manager()
        mgr.register(ShutdownHandler(
            name="event-setter",
            phase=ShutdownPhase.DRAIN,
            callback=lambda: mgr.shutdown_event.set(),
        ))
        report = mgr.initiate_shutdown(reason="state-modify")
        assert report is not None
        assert mgr.shutdown_event.is_set()
        assert report.success is True

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_very_long_handler_name(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """A handler with a very long name registers and executes normally."""
        long_name = "x" * 500
        mgr = _fresh_manager()
        mgr.register_simple(long_name, _noop, ShutdownPhase.CLOSE)
        handlers = mgr.get_handler_list()
        assert any(h["name"] == long_name for h in handlers)
        report = mgr.initiate_shutdown(reason="long-name")
        assert report is not None
        assert report.success is True


# ──── TestRegistrationDuringShutdown ───────────────────────────────────────


class TestRegistrationDuringShutdown:
    """Verify that registering handlers during/after shutdown is rejected."""

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_register_after_shutdown_raises(self, _nex_end: MagicMock, _nex_start: MagicMock) -> None:
        """Registering a handler after shutdown completed raises ValueError."""
        mgr = _fresh_manager()
        mgr.initiate_shutdown(reason="done")
        with pytest.raises(ValueError, match="shutdown already in state"):
            mgr.register_simple("late", _noop)


# ──── TestNexusLogging ─────────────────────────────────────────────────────


class TestNexusLogging:
    """Verify Nexus integration calls are made (and failures are swallowed)."""

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_nexus_start_called(self, mock_complete: MagicMock, mock_start: MagicMock) -> None:
        """_log_to_nexus_start is invoked with the shutdown reason."""
        mgr = _fresh_manager()
        mgr.initiate_shutdown(reason="nexus-test")
        mock_start.assert_called_once_with("nexus-test")

    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_start")
    @patch("engine.lifecycle.shutdown_manager.ShutdownManager._log_to_nexus_complete")
    def test_nexus_complete_called(self, mock_complete: MagicMock, mock_start: MagicMock) -> None:
        """_log_to_nexus_complete is invoked with the ShutdownReport."""
        mgr = _fresh_manager()
        report = mgr.initiate_shutdown(reason="nexus-done")
        mock_complete.assert_called_once()
        passed_report = mock_complete.call_args[0][0]
        assert isinstance(passed_report, ShutdownReport)
        assert passed_report is report

    def test_nexus_failure_swallowed(self) -> None:
        """If Nexus client import fails, shutdown still succeeds."""
        mgr = _fresh_manager()
        mgr.register_simple("safe", _noop, ShutdownPhase.CLOSE)
        # Patch the actual import inside the Nexus logging methods so the
        # internal try/except catches the failure.
        with patch(
            "engine.nexus.client.get_nexus_client",
            side_effect=Exception("nexus down"),
        ):
            report = mgr.initiate_shutdown(reason="nexus-broken")
        assert report is not None
        assert mgr.state in (ShutdownState.COMPLETED, ShutdownState.FORCED)
