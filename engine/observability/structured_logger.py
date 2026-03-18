"""
Structured logging with SQLite backend, trace correlation, and JSON formatter.

Provides a queryable, correlated log store layered on top of stdlib logging.
All log events are persisted to SQLite and optionally written as JSON lines.

Exports:
    get_structured_logger() — global StructuredLogger singleton
    get_logger(name)        — BoundLogger pre-filled with service=name
    StructuredLogger        — core class
    BoundLogger             — service-scoped wrapper
    LogEvent                — structured log event dataclass
    LogLevel                — stdlib-mapped log level enum
    TraceContext            — thread-local trace/span holder
    traced(service, op)     — decorator: auto-span + duration + exception capture
    install_root_handler()  — capture existing logging.getLogger() calls
"""

from __future__ import annotations

import dataclasses
import enum
import functools
import json
import logging
import os
import sqlite3
import sys
import threading
import time
import traceback
import uuid
from typing import Any, Callable, Dict, List, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_DEFAULT_DB_PATH = "data/structured_logs.db"
_DEFAULT_JSONL_PATH = "data/structured_logs.jsonl"

# Thread-local storage for trace context and recursion guard.
_thread_local = threading.local()

# Module-level singleton.
_instance: Optional["StructuredLogger"] = None
_instance_lock: threading.Lock = threading.Lock()

# Track whether root handler has been installed.
_root_handler_installed: bool = False
_root_handler_lock: threading.Lock = threading.Lock()


# ---------------------------------------------------------------------------
# Data classes and enums
# ---------------------------------------------------------------------------


class LogLevel(enum.Enum):
    """Log levels that map 1-to-1 with stdlib logging constants."""

    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


@dataclasses.dataclass
class LogEvent:
    """A single structured log event.

    Attributes:
        event_id: Unique UUID for this event.
        timestamp: Unix epoch timestamp (float seconds).
        level: Level name string ("INFO", "ERROR", etc.).
        logger_name: Originating logger name.
        message: Human-readable log message.
        context: Arbitrary key-value context dictionary.
        trace_id: Optional distributed trace identifier.
        span_id: Optional span identifier within a trace.
        service: Service / component name.
        tags: Free-form classification tags.
        duration_ms: Optional operation duration in milliseconds.
        error_type: Exception class name if an error occurred.
        error_msg: Exception message if an error occurred.
        stack_trace: Full stack trace string if an error occurred.
    """

    event_id: str
    timestamp: float
    level: str
    logger_name: str
    message: str
    context: Dict[str, Any]
    trace_id: Optional[str]
    span_id: Optional[str]
    service: str
    tags: List[str]
    duration_ms: Optional[float]
    error_type: Optional[str]
    error_msg: Optional[str]
    stack_trace: Optional[str]


@dataclasses.dataclass
class TraceContext:
    """Thread-local trace and span identifiers for request correlation.

    Attributes:
        trace_id: Identifies a logical request or workflow.
        span_id: Identifies a single operation within the trace.
    """

    trace_id: str
    span_id: str


# ---------------------------------------------------------------------------
# Stdlib handler for root-logger capture
# ---------------------------------------------------------------------------


class _StructuredHandler(logging.Handler):
    """Logging handler that forwards stdlib records to StructuredLogger."""

    def __init__(self, structured_logger: "StructuredLogger") -> None:
        super().__init__()
        self._sl = structured_logger

    def emit(self, record: logging.LogRecord) -> None:
        """Forward a LogRecord to StructuredLogger.

        Guards against recursion that arises when StructuredLogger itself
        calls stdlib logging internally.
        """
        if getattr(_thread_local, "_in_structured_log", False):
            return

        try:
            level_map: Dict[int, LogLevel] = {
                logging.DEBUG: LogLevel.DEBUG,
                logging.INFO: LogLevel.INFO,
                logging.WARNING: LogLevel.WARNING,
                logging.ERROR: LogLevel.ERROR,
                logging.CRITICAL: LogLevel.CRITICAL,
            }
            level = level_map.get(record.levelno, LogLevel.INFO)

            error_type: Optional[str] = None
            error_msg: Optional[str] = None
            stack_trace: Optional[str] = None

            if record.exc_info:
                exc_type, exc_val, _ = record.exc_info
                if exc_type is not None:
                    error_type = exc_type.__name__
                    error_msg = str(exc_val)
                    stack_trace = "".join(traceback.format_exception(*record.exc_info))

            self._sl.log(
                level=level,
                message=record.getMessage(),
                service=record.name,
                error_type=error_type,
                error_msg=error_msg,
                stack_trace=stack_trace,
            )
        except Exception:  # pylint: disable=broad-except
            self.handleError(record)


# ---------------------------------------------------------------------------
# Core StructuredLogger
# ---------------------------------------------------------------------------


class StructuredLogger:
    """Singleton structured logger backed by SQLite with JSON line output.

    Thread-safe.  All writes use a dedicated lock and are wrapped in
    transactions.  Trace context is stored in thread-local state so that
    concurrent requests each maintain an independent correlation chain.

    Usage::

        sl = get_structured_logger()
        with sl.begin_trace() as ctx:
            sl.info("Processing started", user_id=42)
    """

    def __init__(
        self,
        db_path: str = _DEFAULT_DB_PATH,
        jsonl_path: str = _DEFAULT_JSONL_PATH,
    ) -> None:
        self._db_path = db_path
        self._jsonl_path = jsonl_path
        self._write_lock = threading.Lock()
        self._ensure_dirs()
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        """Create parent directories for db and jsonl files."""
        for path in (self._db_path, self._jsonl_path):
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._write_lock:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS log_events (
                        event_id    TEXT    PRIMARY KEY,
                        timestamp   REAL    NOT NULL,
                        level       TEXT    NOT NULL,
                        logger_name TEXT    NOT NULL DEFAULT '',
                        message     TEXT    NOT NULL DEFAULT '',
                        context     TEXT    NOT NULL DEFAULT '{}',
                        trace_id    TEXT,
                        span_id     TEXT,
                        service     TEXT    NOT NULL DEFAULT '',
                        tags        TEXT    NOT NULL DEFAULT '[]',
                        duration_ms REAL,
                        error_type  TEXT,
                        error_msg   TEXT,
                        stack_trace TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_log_ts "
                    "ON log_events(timestamp)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_log_level "
                    "ON log_events(level)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_log_service "
                    "ON log_events(service)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_log_trace "
                    "ON log_events(trace_id)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_log_composite "
                    "ON log_events(timestamp, level, service, trace_id)"
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _persist(self, event: LogEvent) -> None:
        """Insert a LogEvent into SQLite within a transaction."""
        with self._write_lock:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO log_events (
                        event_id, timestamp, level, logger_name, message,
                        context, trace_id, span_id, service, tags,
                        duration_ms, error_type, error_msg, stack_trace
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event.event_id,
                        event.timestamp,
                        event.level,
                        event.logger_name,
                        event.message,
                        json.dumps(event.context),
                        event.trace_id,
                        event.span_id,
                        event.service,
                        json.dumps(event.tags),
                        event.duration_ms,
                        event.error_type,
                        event.error_msg,
                        event.stack_trace,
                    ),
                )

    def _emit_json(self, event: LogEvent) -> None:
        """Append a compact JSON line to the jsonl output file."""
        record = {
            "ts": event.timestamp,
            "level": event.level,
            "svc": event.service,
            "msg": event.message,
            "ctx": event.context,
            "trace": event.trace_id,
            "span": event.span_id,
        }
        line = json.dumps(record, separators=(",", ":"))
        try:
            with open(self._jsonl_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass  # Never let file I/O break logging.

    def _row_to_event(self, row: tuple) -> LogEvent:
        """Deserialise a SQLite row into a LogEvent."""
        (
            event_id,
            timestamp,
            level,
            logger_name,
            message,
            context_json,
            trace_id,
            span_id,
            service,
            tags_json,
            duration_ms,
            error_type,
            error_msg,
            stack_trace,
        ) = row
        return LogEvent(
            event_id=event_id,
            timestamp=timestamp,
            level=level,
            logger_name=logger_name,
            message=message,
            context=json.loads(context_json or "{}"),
            trace_id=trace_id,
            span_id=span_id,
            service=service,
            tags=json.loads(tags_json or "[]"),
            duration_ms=duration_ms,
            error_type=error_type,
            error_msg=error_msg,
            stack_trace=stack_trace,
        )

    # ------------------------------------------------------------------
    # Public logging API
    # ------------------------------------------------------------------

    def log(
        self,
        level: LogLevel,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        duration_ms: Optional[float] = None,
        service: str = "",
        error_type: Optional[str] = None,
        error_msg: Optional[str] = None,
        stack_trace: Optional[str] = None,
    ) -> LogEvent:
        """Emit a structured log event.

        Args:
            level: Severity level.
            message: Human-readable message.
            context: Arbitrary extra key-value pairs.
            tags: Free-form classification tags.
            duration_ms: Optional operation duration.
            service: Component / service name.
            error_type: Exception class name.
            error_msg: Exception message string.
            stack_trace: Full traceback string.

        Returns:
            The persisted LogEvent.
        """
        trace_ctx: Optional[TraceContext] = getattr(
            _thread_local, "trace_context", None
        )
        event = LogEvent(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            level=level.name,
            logger_name=service or "",
            message=message,
            context=context or {},
            trace_id=trace_ctx.trace_id if trace_ctx else None,
            span_id=trace_ctx.span_id if trace_ctx else None,
            service=service,
            tags=tags or [],
            duration_ms=duration_ms,
            error_type=error_type,
            error_msg=error_msg,
            stack_trace=stack_trace,
        )
        self._persist(event)
        self._emit_json(event)

        # Forward to stdlib only if not already inside a stdlib→structured call.
        if not getattr(_thread_local, "_in_structured_log", False):
            _thread_local._in_structured_log = True
            try:
                std = logging.getLogger(service or "cosysim.structured")
                std.log(level.value, message)
            finally:
                _thread_local._in_structured_log = False

        return event

    def info(self, message: str, **context: Any) -> LogEvent:
        """Log at INFO level.  Keyword args populate the context dict."""
        return self.log(LogLevel.INFO, message, context=context or None)

    def debug(self, message: str, **context: Any) -> LogEvent:
        """Log at DEBUG level."""
        return self.log(LogLevel.DEBUG, message, context=context or None)

    def warning(self, message: str, **context: Any) -> LogEvent:
        """Log at WARNING level."""
        return self.log(LogLevel.WARNING, message, context=context or None)

    def error(self, message: str, **context: Any) -> LogEvent:
        """Log at ERROR level."""
        return self.log(LogLevel.ERROR, message, context=context or None)

    def critical(self, message: str, **context: Any) -> LogEvent:
        """Log at CRITICAL level."""
        return self.log(LogLevel.CRITICAL, message, context=context or None)

    # ------------------------------------------------------------------
    # Trace context management
    # ------------------------------------------------------------------

    def begin_trace(self, trace_id: Optional[str] = None) -> TraceContext:
        """Start a new correlated trace on this thread.

        Args:
            trace_id: Explicit ID; auto-generated UUID4 if omitted.

        Returns:
            The active TraceContext for this thread.
        """
        ctx = TraceContext(
            trace_id=trace_id or str(uuid.uuid4()),
            span_id=str(uuid.uuid4()),
        )
        _thread_local.trace_context = ctx
        return ctx

    def end_trace(self) -> None:
        """Clear the trace context on the current thread."""
        _thread_local.trace_context = None

    # ------------------------------------------------------------------
    # Query / analytics API
    # ------------------------------------------------------------------

    def query(
        self,
        level: Optional[LogLevel] = None,
        service: Optional[str] = None,
        tags: Optional[List[str]] = None,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> List[LogEvent]:
        """Query stored log events.

        Args:
            level: Filter by exact level.
            service: Filter by service name (exact match).
            tags: Filter to events that contain ALL provided tags.
            since: Unix timestamp lower bound (inclusive).
            limit: Maximum number of results.

        Returns:
            List of matching LogEvent objects, newest first.
        """
        clauses: List[str] = []
        params: List[Any] = []

        if level is not None:
            clauses.append("level = ?")
            params.append(level.name)
        if service is not None:
            clauses.append("service = ?")
            params.append(service)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if tags:
            for tag in tags:
                clauses.append('tags LIKE ?')
                params.append(f'%"{tag}"%')

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT event_id, timestamp, level, logger_name, message, "
            f"context, trace_id, span_id, service, tags, duration_ms, "
            f"error_type, error_msg, stack_trace "
            f"FROM log_events {where} "
            f"ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def get_error_summary(self, hours: float = 24) -> Dict[str, Any]:
        """Count errors by type and service in the last N hours.

        Args:
            hours: Look-back window in hours.

        Returns:
            Dict with keys: period_hours, total_errors, by_type, by_service.
        """
        since_ts = time.time() - hours * 3600
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT error_type, service, COUNT(*) "
                "FROM log_events "
                "WHERE level IN ('ERROR','CRITICAL') AND timestamp >= ? "
                "GROUP BY error_type, service",
                (since_ts,),
            ).fetchall()

        by_type: Dict[str, int] = {}
        by_service: Dict[str, int] = {}
        total = 0
        for error_type, svc, cnt in rows:
            key_type = error_type or "unknown"
            by_type[key_type] = by_type.get(key_type, 0) + cnt
            key_svc = svc or "unknown"
            by_service[key_svc] = by_service.get(key_svc, 0) + cnt
            total += cnt

        return {
            "period_hours": hours,
            "total_errors": total,
            "by_type": by_type,
            "by_service": by_service,
        }

    def get_slow_operations(
        self,
        threshold_ms: float = 1000,
        hours: float = 24,
    ) -> List[Dict[str, Any]]:
        """Find operations that exceeded the duration threshold.

        Args:
            threshold_ms: Minimum duration to consider slow (milliseconds).
            hours: Look-back window in hours.

        Returns:
            List of dicts with keys: event_id, service, message, duration_ms, timestamp.
        """
        since_ts = time.time() - hours * 3600
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT event_id, service, message, duration_ms, timestamp "
                "FROM log_events "
                "WHERE duration_ms >= ? AND timestamp >= ? "
                "ORDER BY duration_ms DESC",
                (threshold_ms, since_ts),
            ).fetchall()
        return [
            {
                "event_id": r[0],
                "service": r[1],
                "message": r[2],
                "duration_ms": r[3],
                "timestamp": r[4],
            }
            for r in rows
        ]

    def get_trace(self, trace_id: str) -> List[LogEvent]:
        """Retrieve all events belonging to a trace.

        Args:
            trace_id: The trace identifier to look up.

        Returns:
            List of LogEvent objects for that trace, oldest first.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT event_id, timestamp, level, logger_name, message, "
                "context, trace_id, span_id, service, tags, duration_ms, "
                "error_type, error_msg, stack_trace "
                "FROM log_events WHERE trace_id = ? ORDER BY timestamp ASC",
                (trace_id,),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def flush_old_logs(self, days: int = 7) -> int:
        """Delete log events older than N days.

        Args:
            days: Retention period.  Events older than this are deleted.

        Returns:
            Number of rows deleted.
        """
        cutoff = time.time() - days * 86400
        with self._write_lock:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    "DELETE FROM log_events WHERE timestamp < ?", (cutoff,)
                )
                return cursor.rowcount

    # ------------------------------------------------------------------
    # BoundLogger factory
    # ------------------------------------------------------------------

    def get_bound_logger(self, service: str) -> "BoundLogger":
        """Return a BoundLogger pre-filled with *service*.

        Args:
            service: The service/component name to pre-fill.

        Returns:
            A BoundLogger instance.
        """
        return BoundLogger(self, service)

    # ------------------------------------------------------------------
    # Root handler installation & excepthook
    # ------------------------------------------------------------------

    def install_root_handler(self) -> None:
        """Install a structured handler on the Python root logger.

        Idempotent — calling multiple times has no additional effect.
        Existing ``logging.getLogger()`` calls are captured automatically
        after this is called.
        """
        global _root_handler_installed
        with _root_handler_lock:
            if _root_handler_installed:
                return
            handler = _StructuredHandler(self)
            handler.setLevel(logging.DEBUG)
            root = logging.getLogger()
            root.addHandler(handler)
            _root_handler_installed = True

        # Install excepthook to capture uncaught exceptions.
        _original_excepthook = sys.excepthook

        def _excepthook(
            exc_type: type,
            exc_value: BaseException,
            exc_tb: Any,
        ) -> None:
            if not issubclass(exc_type, KeyboardInterrupt):
                self.log(
                    LogLevel.CRITICAL,
                    f"Uncaught exception: {exc_type.__name__}: {exc_value}",
                    service="cosysim.excepthook",
                    error_type=exc_type.__name__,
                    error_msg=str(exc_value),
                    stack_trace="".join(
                        traceback.format_exception(exc_type, exc_value, exc_tb)
                    ),
                )
            _original_excepthook(exc_type, exc_value, exc_tb)

        sys.excepthook = _excepthook


# ---------------------------------------------------------------------------
# BoundLogger — service-scoped wrapper
# ---------------------------------------------------------------------------


class BoundLogger:
    """Wraps StructuredLogger and pre-fills ``service`` on every call.

    Obtain via :func:`get_logger` or ``StructuredLogger.get_bound_logger``.
    """

    def __init__(self, sl: StructuredLogger, service: str) -> None:
        self._sl = sl
        self._service = service

    @property
    def service(self) -> str:
        """The service name pre-filled on every log call."""
        return self._service

    def log(
        self,
        level: LogLevel,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        duration_ms: Optional[float] = None,
        error_type: Optional[str] = None,
        error_msg: Optional[str] = None,
        stack_trace: Optional[str] = None,
    ) -> LogEvent:
        """Emit a structured log event with the pre-filled service name."""
        return self._sl.log(
            level=level,
            message=message,
            context=context,
            tags=tags,
            duration_ms=duration_ms,
            service=self._service,
            error_type=error_type,
            error_msg=error_msg,
            stack_trace=stack_trace,
        )

    def info(self, message: str, **context: Any) -> LogEvent:
        """Log at INFO level."""
        return self.log(LogLevel.INFO, message, context=context or None)

    def debug(self, message: str, **context: Any) -> LogEvent:
        """Log at DEBUG level."""
        return self.log(LogLevel.DEBUG, message, context=context or None)

    def warning(self, message: str, **context: Any) -> LogEvent:
        """Log at WARNING level."""
        return self.log(LogLevel.WARNING, message, context=context or None)

    def error(self, message: str, **context: Any) -> LogEvent:
        """Log at ERROR level."""
        return self.log(LogLevel.ERROR, message, context=context or None)

    def critical(self, message: str, **context: Any) -> LogEvent:
        """Log at CRITICAL level."""
        return self.log(LogLevel.CRITICAL, message, context=context or None)

    def begin_trace(self, trace_id: Optional[str] = None) -> TraceContext:
        """Delegate to parent StructuredLogger."""
        return self._sl.begin_trace(trace_id)

    def end_trace(self) -> None:
        """Delegate to parent StructuredLogger."""
        self._sl.end_trace()

    def query(self, **kwargs: Any) -> List[LogEvent]:
        """Query restricted to this service by default."""
        kwargs.setdefault("service", self._service)
        return self._sl.query(**kwargs)


# ---------------------------------------------------------------------------
# @traced decorator
# ---------------------------------------------------------------------------


def traced(service: str = "", operation: str = "") -> Callable[[F], F]:
    """Decorator: auto-start a span, capture duration, log exceptions.

    Usage::

        @traced("my_service", "process_request")
        def process(data):
            ...

    Args:
        service: Service name for the log event.
        operation: Operation label; defaults to function name.

    Returns:
        Decorator that wraps the target function.
    """

    def decorator(func: F) -> F:
        op_label = operation or func.__name__
        svc_label = service or func.__module__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            sl = get_structured_logger()
            existing_trace = getattr(_thread_local, "trace_context", None)
            if not existing_trace:
                sl.begin_trace()
            start = time.monotonic()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.monotonic() - start) * 1000.0
                sl.log(
                    LogLevel.INFO,
                    f"[traced] {op_label} completed",
                    duration_ms=duration_ms,
                    service=svc_label,
                    tags=["traced", op_label],
                )
                return result
            except Exception as exc:
                duration_ms = (time.monotonic() - start) * 1000.0
                sl.log(
                    LogLevel.ERROR,
                    f"[traced] {op_label} failed: {exc}",
                    duration_ms=duration_ms,
                    service=svc_label,
                    error_type=type(exc).__name__,
                    error_msg=str(exc),
                    stack_trace=traceback.format_exc(),
                    tags=["traced", "error", op_label],
                )
                raise
            finally:
                if not existing_trace:
                    sl.end_trace()

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# Public singletons and factories
# ---------------------------------------------------------------------------


def get_structured_logger(
    db_path: str = _DEFAULT_DB_PATH,
    jsonl_path: str = _DEFAULT_JSONL_PATH,
) -> StructuredLogger:
    """Return the global StructuredLogger singleton.

    The singleton is initialised with *db_path* only on first call;
    subsequent calls with different paths return the existing instance.

    Args:
        db_path: SQLite file path (used only on first call).
        jsonl_path: JSON-lines output file path (used only on first call).

    Returns:
        The global StructuredLogger singleton.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = StructuredLogger(db_path=db_path, jsonl_path=jsonl_path)
    return _instance


def get_logger(name: str) -> BoundLogger:
    """Return a BoundLogger pre-filled with ``service=name``.

    This is the recommended entry point for component-level logging::

        _log = get_logger(__name__)
        _log.info("Component started")

    Args:
        name: Service / component name (typically ``__name__``).

    Returns:
        A BoundLogger scoped to *name*.
    """
    return get_structured_logger().get_bound_logger(name)


def install_root_handler() -> None:
    """Install the structured handler on the Python root logger.

    Convenience module-level function that delegates to the global singleton.
    """
    get_structured_logger().install_root_handler()
