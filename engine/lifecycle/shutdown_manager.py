"""Graceful Shutdown Manager for CosySim.

Centralised shutdown orchestrator that coordinates ordered teardown across
all CosySim services — scenes, databases, schedulers, Flask servers, and
thread pools.  Replaces the ad-hoc ``KeyboardInterrupt`` handling in
``launcher.py`` with a phased, priority-driven pipeline.

Usage::

    from engine.lifecycle.shutdown_manager import get_shutdown_manager, ShutdownPhase

    mgr = get_shutdown_manager()
    mgr.register_simple("my-db", db.close, ShutdownPhase.CLOSE)
    mgr.install_signal_handlers()
"""
from __future__ import annotations

import atexit
import datetime
import logging
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Enums ────────────────────────────────────────────────────────────────


class ShutdownPhase(Enum):
    """Ordered phases of a graceful shutdown."""

    DRAIN = "drain"        # Stop accepting new requests, finish in-flight
    FLUSH = "flush"        # Flush buffers, persist state, write logs
    CLOSE = "close"        # Close connections, sockets, file handles
    CLEANUP = "cleanup"    # Remove temp files, final logging

    @property
    def order(self) -> int:
        """Return numeric ordering for phase sequencing."""
        return _PHASE_ORDER[self]


_PHASE_ORDER: Dict[ShutdownPhase, int] = {
    ShutdownPhase.DRAIN: 0,
    ShutdownPhase.FLUSH: 1,
    ShutdownPhase.CLOSE: 2,
    ShutdownPhase.CLEANUP: 3,
}


class ShutdownState(Enum):
    """Current state of the shutdown lifecycle."""

    RUNNING = "running"
    DRAINING = "draining"
    SHUTTING_DOWN = "shutting_down"
    COMPLETED = "completed"
    FORCED = "forced"


# ──── Data Classes ─────────────────────────────────────────────────────────


@dataclass
class ShutdownHandler:
    """A single shutdown callback with metadata.

    Attributes:
        name: Human-readable identifier (must be unique).
        phase: Which shutdown phase this handler runs in.
        callback: Synchronous callable to execute during shutdown.
        timeout: Maximum seconds before the handler is considered timed-out.
        priority: Lower values run first within a phase.
        critical: If ``True``, a failure here aborts the entire shutdown.
    """

    name: str
    phase: ShutdownPhase
    callback: Callable[[], None]
    timeout: float = 10.0
    priority: int = 50
    critical: bool = False


@dataclass
class PhaseResult:
    """Outcome of executing all handlers in a single phase.

    Attributes:
        phase: The phase that was executed.
        total_handlers: Number of handlers registered for the phase.
        succeeded: Number of handlers that completed successfully.
        failed: Number of handlers that raised an exception.
        timed_out: Number of handlers that exceeded their timeout.
        duration_ms: Wall-clock time for the entire phase.
        errors: List of ``{name, error}`` dicts for failed/timed-out handlers.
    """

    phase: ShutdownPhase
    total_handlers: int = 0
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    duration_ms: float = 0.0
    errors: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class ShutdownReport:
    """Full report produced after shutdown completes.

    Attributes:
        reason: Why shutdown was initiated (e.g. ``"SIGINT"``, ``"manual"``).
        started_at: ISO-8601 timestamp of shutdown start.
        completed_at: ISO-8601 timestamp of shutdown end.
        total_duration_ms: Wall-clock duration of the full shutdown.
        phases: Per-phase results in execution order.
        success: ``True`` if all phases completed without critical failures.
        forced: ``True`` if shutdown was forcibly terminated after timeout.
    """

    reason: str
    started_at: str
    completed_at: str
    total_duration_ms: float
    phases: List[PhaseResult]
    success: bool
    forced: bool


# ──── Shutdown Manager ─────────────────────────────────────────────────────


class ShutdownManager:
    """Centralised, phased shutdown orchestrator for CosySim.

    Thread-safe singleton that coordinates ordered teardown of all registered
    services.  Handlers are grouped by :class:`ShutdownPhase` and sorted by
    ``priority`` within each phase.
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._handlers: Dict[str, ShutdownHandler] = {}
        self._state: ShutdownState = ShutdownState.RUNNING
        self._report: Optional[ShutdownReport] = None
        self._signals_installed: bool = False

        # Public event — other threads can ``wait()`` on this to learn that
        # shutdown has been requested.
        self.shutdown_event: threading.Event = threading.Event()

    # ── Registration ───────────────────────────────────────────────────

    def register(self, handler: ShutdownHandler) -> None:
        """Register a shutdown handler.

        Args:
            handler: The :class:`ShutdownHandler` to register.

        Raises:
            ValueError: If a handler with the same ``name`` is already
                registered, or if shutdown is already in progress.
        """
        with self._lock:
            if self._state != ShutdownState.RUNNING:
                raise ValueError(
                    f"Cannot register handler '{handler.name}' — "
                    f"shutdown already in state {self._state.value}"
                )
            if handler.name in self._handlers:
                raise ValueError(
                    f"Handler '{handler.name}' is already registered"
                )
            self._handlers[handler.name] = handler
            logger.debug(
                "Registered shutdown handler '%s' (phase=%s, priority=%d)",
                handler.name,
                handler.phase.value,
                handler.priority,
            )

    def register_simple(
        self,
        name: str,
        callback: Callable[[], None],
        phase: ShutdownPhase = ShutdownPhase.CLOSE,
        timeout: float = 10.0,
    ) -> None:
        """Convenience wrapper to register a handler with defaults.

        Args:
            name: Unique identifier for the handler.
            callback: Callable to execute during shutdown.
            phase: Shutdown phase (default :attr:`ShutdownPhase.CLOSE`).
            timeout: Maximum seconds for the callback.
        """
        self.register(ShutdownHandler(
            name=name,
            phase=phase,
            callback=callback,
            timeout=timeout,
        ))

    def unregister(self, name: str) -> None:
        """Remove a previously registered handler by name.

        Args:
            name: The handler name to remove.

        Raises:
            KeyError: If no handler with that name exists.
        """
        with self._lock:
            if name not in self._handlers:
                raise KeyError(f"No handler registered with name '{name}'")
            del self._handlers[name]
            logger.debug("Unregistered shutdown handler '%s'", name)

    # ── Signal Installation ────────────────────────────────────────────

    def install_signal_handlers(self) -> None:
        """Install OS signal handlers for graceful shutdown.

        Windows: ``SIGINT`` + ``SIGBREAK`` + ``atexit``
        Unix:    ``SIGTERM`` + ``SIGINT`` + ``atexit``

        Safe to call multiple times; subsequent calls are no-ops.
        """
        if self._signals_installed:
            return

        def _signal_handler(signum: int, _frame: Any) -> None:
            sig_name = signal.Signals(signum).name
            logger.info("Received signal %s — initiating shutdown", sig_name)
            self.initiate_shutdown(reason=sig_name)

        signal.signal(signal.SIGINT, _signal_handler)

        if sys.platform == "win32":
            # SIGBREAK is Windows-specific (Ctrl+Break / console close)
            signal.signal(signal.SIGBREAK, _signal_handler)  # type: ignore[attr-defined]
        else:
            signal.signal(signal.SIGTERM, _signal_handler)

        atexit.register(self._atexit_handler)
        self._signals_installed = True
        logger.debug("Signal handlers installed (platform=%s)", sys.platform)

    def _atexit_handler(self) -> None:
        """Fallback handler called by :mod:`atexit` on interpreter exit."""
        if self._state == ShutdownState.RUNNING:
            logger.info("atexit triggered — running shutdown handlers")
            self.initiate_shutdown(reason="atexit")

    # ── Shutdown Execution ─────────────────────────────────────────────

    def initiate_shutdown(self, reason: str = "manual") -> Optional[ShutdownReport]:
        """Begin orderly shutdown.  Idempotent — safe to call repeatedly.

        Executes all four phases in order: DRAIN → FLUSH → CLOSE → CLEANUP.
        Each phase runs its handlers sorted by ``priority`` (ascending).

        Args:
            reason: Descriptive string for why shutdown was initiated.

        Returns:
            A :class:`ShutdownReport` on the first call, or the cached report
            on subsequent calls.  Returns ``None`` only if a concurrent
            shutdown is already in progress on another thread.
        """
        with self._lock:
            if self._state in (
                ShutdownState.COMPLETED,
                ShutdownState.FORCED,
            ):
                logger.debug("Shutdown already finished (state=%s)", self._state.value)
                return self._report
            if self._state in (
                ShutdownState.DRAINING,
                ShutdownState.SHUTTING_DOWN,
            ):
                logger.debug("Shutdown already in progress")
                return None
            self._state = ShutdownState.DRAINING

        # Signal all waiters
        self.shutdown_event.set()

        started_at = datetime.datetime.now(datetime.timezone.utc)
        logger.info("Shutdown initiated (reason=%s)", reason)
        self._log_to_nexus_start(reason)

        phase_results: List[PhaseResult] = []
        forced = False
        phases = sorted(ShutdownPhase, key=lambda p: p.order)

        for phase in phases:
            with self._lock:
                self._state = ShutdownState.SHUTTING_DOWN
            result = self._execute_phase(phase)
            phase_results.append(result)

            # Abort on critical failure
            if any(
                self._handlers.get(err["name"], ShutdownHandler(
                    name="", phase=phase, callback=lambda: None
                )).critical
                for err in result.errors
                if err["name"] in self._handlers
            ):
                logger.error(
                    "Critical handler failed in phase %s — aborting shutdown",
                    phase.value,
                )
                forced = True
                break

        completed_at = datetime.datetime.now(datetime.timezone.utc)
        total_ms = (completed_at - started_at).total_seconds() * 1000

        overall_success = all(
            r.failed == 0 and r.timed_out == 0 for r in phase_results
        ) and not forced

        report = ShutdownReport(
            reason=reason,
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat(),
            total_duration_ms=round(total_ms, 2),
            phases=phase_results,
            success=overall_success,
            forced=forced,
        )

        with self._lock:
            self._state = ShutdownState.FORCED if forced else ShutdownState.COMPLETED
            self._report = report

        logger.info(
            "Shutdown complete — success=%s, forced=%s, duration=%.1fms, "
            "handlers=%d",
            overall_success,
            forced,
            total_ms,
            sum(r.total_handlers for r in phase_results),
        )
        self._log_to_nexus_complete(report)
        return report

    def _execute_phase(self, phase: ShutdownPhase) -> PhaseResult:
        """Run all handlers registered for a single phase.

        Handlers are sorted by ``priority`` (ascending) and executed
        sequentially.  Each handler is run in a worker thread so that
        its ``timeout`` can be enforced via :meth:`threading.Thread.join`.

        Args:
            phase: The shutdown phase to execute.

        Returns:
            A :class:`PhaseResult` summarising the outcome.
        """
        with self._lock:
            handlers = sorted(
                [h for h in self._handlers.values() if h.phase == phase],
                key=lambda h: h.priority,
            )

        result = PhaseResult(phase=phase, total_handlers=len(handlers))
        if not handlers:
            return result

        phase_start = time.monotonic()
        logger.info(
            "Shutdown phase %s — %d handler(s)", phase.value, len(handlers)
        )

        for handler in handlers:
            outcome = self._run_handler(handler)
            if outcome == "ok":
                result.succeeded += 1
            elif outcome == "timeout":
                result.timed_out += 1
                result.errors.append({
                    "name": handler.name,
                    "error": f"Timed out after {handler.timeout}s",
                })
            else:
                result.failed += 1
                result.errors.append({
                    "name": handler.name,
                    "error": outcome,
                })

        result.duration_ms = round(
            (time.monotonic() - phase_start) * 1000, 2
        )
        return result

    def _run_handler(self, handler: ShutdownHandler) -> str:
        """Execute a single handler with timeout enforcement.

        Args:
            handler: The handler to execute.

        Returns:
            ``"ok"`` on success, ``"timeout"`` if the handler exceeded its
            timeout, or an error message string on exception.
        """
        exception_holder: List[str] = []
        completed = threading.Event()

        def _target() -> None:
            try:
                handler.callback()
            except Exception as exc:
                exception_holder.append(f"{type(exc).__name__}: {exc}")
            finally:
                completed.set()

        thread = threading.Thread(
            target=_target,
            name=f"shutdown-{handler.name}",
            daemon=True,
        )
        thread.start()
        completed.wait(timeout=handler.timeout)

        if not completed.is_set():
            logger.warning(
                "Handler '%s' timed out (%.1fs)", handler.name, handler.timeout
            )
            return "timeout"

        if exception_holder:
            err = exception_holder[0]
            logger.error("Handler '%s' failed: %s", handler.name, err)
            return err

        logger.debug("Handler '%s' completed successfully", handler.name)
        return "ok"

    # ── State & Status ─────────────────────────────────────────────────

    @property
    def state(self) -> ShutdownState:
        """Return the current shutdown state."""
        return self._state

    @property
    def is_shutting_down(self) -> bool:
        """Return ``True`` if shutdown has been initiated."""
        return self._state != ShutdownState.RUNNING

    def get_status(self) -> Dict[str, Any]:
        """Return current shutdown state, registered handlers, and report.

        Returns:
            Dict with ``state``, ``handler_count``, ``phases``,
            ``signals_installed``, and (if available) ``report`` keys.
        """
        with self._lock:
            handler_count = len(self._handlers)
            phase_counts = {}
            for phase in ShutdownPhase:
                phase_counts[phase.value] = sum(
                    1 for h in self._handlers.values() if h.phase == phase
                )

        return {
            "state": self._state.value,
            "handler_count": handler_count,
            "phases": phase_counts,
            "signals_installed": self._signals_installed,
            "shutdown_event_set": self.shutdown_event.is_set(),
            "report": self._report_to_dict(self._report) if self._report else None,
        }

    def get_handler_list(self) -> List[Dict[str, Any]]:
        """Return metadata for every registered handler.

        Returns:
            List of dicts with ``name``, ``phase``, ``priority``, ``timeout``,
            and ``critical`` keys, sorted by phase order then priority.
        """
        with self._lock:
            handlers = list(self._handlers.values())

        handlers.sort(key=lambda h: (h.phase.order, h.priority))
        return [
            {
                "name": h.name,
                "phase": h.phase.value,
                "priority": h.priority,
                "timeout": h.timeout,
                "critical": h.critical,
            }
            for h in handlers
        ]

    # ── Nexus Integration (best-effort) ────────────────────────────────

    def _log_to_nexus_start(self, reason: str) -> None:
        """Log shutdown initiation to Nexus.  Never raises."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            handler_summary = ", ".join(
                f"{h.name}({h.phase.value})"
                for h in sorted(
                    self._handlers.values(),
                    key=lambda h: (h.phase.order, h.priority),
                )
            )
            client.add_entry(
                title=f"Shutdown initiated: {reason}",
                content=(
                    f"CosySim shutdown initiated.\n"
                    f"Reason: {reason}\n"
                    f"Registered handlers ({len(self._handlers)}): "
                    f"{handler_summary}\n"
                    f"Timestamp: {datetime.datetime.now(datetime.timezone.utc).isoformat()}"
                ),
                content_type="note",
                category="operations",
                tags=["shutdown", "lifecycle"],
                created_by="shutdown_manager",
            )
        except Exception:
            logger.debug("Nexus log (shutdown start) failed", exc_info=True)

    def _log_to_nexus_complete(self, report: ShutdownReport) -> None:
        """Log shutdown completion to Nexus.  Never raises."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()

            phase_lines = []
            for pr in report.phases:
                status = "✓" if pr.failed == 0 and pr.timed_out == 0 else "✗"
                phase_lines.append(
                    f"  {status} {pr.phase.value}: "
                    f"{pr.succeeded}/{pr.total_handlers} ok, "
                    f"{pr.failed} failed, {pr.timed_out} timed out "
                    f"({pr.duration_ms:.1f}ms)"
                )
                for err in pr.errors:
                    phase_lines.append(f"    - {err['name']}: {err['error']}")

            client.add_entry(
                title=f"Shutdown complete: {'success' if report.success else 'with errors'}",
                content=(
                    f"CosySim shutdown report.\n"
                    f"Reason: {report.reason}\n"
                    f"Duration: {report.total_duration_ms:.1f}ms\n"
                    f"Success: {report.success}\n"
                    f"Forced: {report.forced}\n"
                    f"Started: {report.started_at}\n"
                    f"Completed: {report.completed_at}\n\n"
                    f"Phase results:\n" + "\n".join(phase_lines)
                ),
                content_type="note",
                category="operations",
                tags=["shutdown", "lifecycle"],
                created_by="shutdown_manager",
            )
        except Exception:
            logger.debug("Nexus log (shutdown complete) failed", exc_info=True)

    # ── Serialisation helpers ──────────────────────────────────────────

    @staticmethod
    def _report_to_dict(report: ShutdownReport) -> Dict[str, Any]:
        """Serialise a :class:`ShutdownReport` to a plain dict."""
        return {
            "reason": report.reason,
            "started_at": report.started_at,
            "completed_at": report.completed_at,
            "total_duration_ms": report.total_duration_ms,
            "success": report.success,
            "forced": report.forced,
            "phases": [
                {
                    "phase": pr.phase.value,
                    "total_handlers": pr.total_handlers,
                    "succeeded": pr.succeeded,
                    "failed": pr.failed,
                    "timed_out": pr.timed_out,
                    "duration_ms": pr.duration_ms,
                    "errors": pr.errors,
                }
                for pr in report.phases
            ],
        }


# ──── Pre-built Handler Factories ──────────────────────────────────────────


def create_database_flush_handler(
    db_name: str,
    close_fn: Callable[[], None],
) -> ShutdownHandler:
    """Create a handler that flushes and closes a database connection.

    Args:
        db_name: Human-readable database identifier.
        close_fn: Callable that commits pending transactions and closes the
            connection.

    Returns:
        A :class:`ShutdownHandler` assigned to the FLUSH phase.
    """
    return ShutdownHandler(
        name=f"db-{db_name}",
        phase=ShutdownPhase.FLUSH,
        callback=close_fn,
        timeout=15.0,
        priority=30,
        critical=False,
    )


def create_scheduler_drain_handler() -> ShutdownHandler:
    """Create a handler that stops the task scheduler from picking new tasks.

    Imports :func:`engine.nexus.task_scheduler.get_task_scheduler` at call
    time and invokes its ``stop()`` method.

    Returns:
        A :class:`ShutdownHandler` assigned to the DRAIN phase.
    """
    def _drain_scheduler() -> None:
        try:
            from engine.nexus.task_scheduler import get_task_scheduler
            scheduler = get_task_scheduler()
            if hasattr(scheduler, "stop"):
                scheduler.stop()
                logger.debug("Task scheduler drained")
        except ImportError:
            logger.debug("task_scheduler not available — skipping drain")

    return ShutdownHandler(
        name="scheduler-drain",
        phase=ShutdownPhase.DRAIN,
        callback=_drain_scheduler,
        timeout=10.0,
        priority=20,
        critical=False,
    )


def create_thread_pool_drain_handler(
    pool_name: str,
    executor: ThreadPoolExecutor,
) -> ShutdownHandler:
    """Create a handler that shuts down a :class:`ThreadPoolExecutor`.

    Calls ``executor.shutdown(wait=True)`` within the handler's timeout
    budget.  Already-submitted futures are allowed to complete; no new
    submissions are accepted.

    Args:
        pool_name: Human-readable name for the pool.
        executor: The executor instance to drain.

    Returns:
        A :class:`ShutdownHandler` assigned to the DRAIN phase.
    """
    def _drain_pool() -> None:
        logger.debug("Draining thread pool '%s'", pool_name)
        executor.shutdown(wait=True)
        logger.debug("Thread pool '%s' drained", pool_name)

    return ShutdownHandler(
        name=f"threadpool-{pool_name}",
        phase=ShutdownPhase.DRAIN,
        callback=_drain_pool,
        timeout=15.0,
        priority=40,
        critical=False,
    )


def create_flask_shutdown_handler(
    app_name: str,
    shutdown_fn: Callable[[], None],
) -> ShutdownHandler:
    """Create a handler that stops a Flask/Werkzeug server.

    Args:
        app_name: Human-readable name for the Flask application.
        shutdown_fn: Callable that triggers Werkzeug shutdown (e.g. by
            calling ``werkzeug.server.shutdown`` via the ``/shutdown``
            endpoint or raising ``SystemExit``).

    Returns:
        A :class:`ShutdownHandler` assigned to the DRAIN phase.
    """
    return ShutdownHandler(
        name=f"flask-{app_name}",
        phase=ShutdownPhase.DRAIN,
        callback=shutdown_fn,
        timeout=10.0,
        priority=10,
        critical=False,
    )


# ──── Singleton ────────────────────────────────────────────────────────────

_INSTANCE: Optional[ShutdownManager] = None
_INSTANCE_LOCK: threading.Lock = threading.Lock()


def get_shutdown_manager() -> ShutdownManager:
    """Return the process-global :class:`ShutdownManager` singleton.

    Thread-safe via double-checked locking.

    Returns:
        The singleton :class:`ShutdownManager` instance.
    """
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = ShutdownManager()
                logger.debug("ShutdownManager singleton created")
    return _INSTANCE
