"""
Tests for engine.observability.structured_logger.

Covers:
- LogEvent, LogLevel, TraceContext data classes
- StructuredLogger init, singleton, DB creation
- log(), info(), debug(), warning(), error(), critical()
- begin_trace(), end_trace(), trace ID propagation
- @traced decorator (duration, exception capture, signature preservation)
- query() — level, service, tags, since, limit filters
- get_error_summary() — counts by type and service
- get_slow_operations() — threshold filtering
- get_trace() — fetch all events for a trace
- flush_old_logs() — retention window purge
- JSON output format and single-line guarantee
- install_root_handler() — idempotency and stdlib capture
- BoundLogger — service pre-fill, all convenience methods
- get_logger() module-level factory
- Thread safety — concurrent writes
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from engine.observability.structured_logger import (
    BoundLogger,
    LogEvent,
    LogLevel,
    StructuredLogger,
    TraceContext,
    get_logger,
    get_structured_logger,
    install_root_handler,
    traced,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sl(tmp_path: Path) -> StructuredLogger:
    """Fresh StructuredLogger backed by a temp SQLite file."""
    db = str(tmp_path / "test_logs.db")
    jsonl = str(tmp_path / "test_logs.jsonl")
    return StructuredLogger(db_path=db, jsonl_path=jsonl)


@pytest.fixture()
def bound(sl: StructuredLogger) -> BoundLogger:
    """BoundLogger wrapping *sl* with service='test_svc'."""
    return sl.get_bound_logger("test_svc")


# ===========================================================================
# LogEvent and enum tests
# ===========================================================================


class TestLogEvent:
    """LogEvent dataclass creation and field validation."""

    def test_log_event_all_fields(self) -> None:
        event = LogEvent(
            event_id="abc",
            timestamp=1000.0,
            level="INFO",
            logger_name="svc",
            message="hello",
            context={"k": "v"},
            trace_id="t1",
            span_id="s1",
            service="svc",
            tags=["a"],
            duration_ms=42.0,
            error_type=None,
            error_msg=None,
            stack_trace=None,
        )
        assert event.event_id == "abc"
        assert event.level == "INFO"
        assert event.context == {"k": "v"}
        assert event.tags == ["a"]
        assert event.duration_ms == 42.0

    def test_log_event_optional_fields_none(self) -> None:
        event = LogEvent(
            event_id="x",
            timestamp=0.0,
            level="DEBUG",
            logger_name="",
            message="",
            context={},
            trace_id=None,
            span_id=None,
            service="",
            tags=[],
            duration_ms=None,
            error_type=None,
            error_msg=None,
            stack_trace=None,
        )
        assert event.trace_id is None
        assert event.span_id is None
        assert event.error_type is None

    def test_log_level_enum_values(self) -> None:
        assert LogLevel.DEBUG.value == logging.DEBUG
        assert LogLevel.INFO.value == logging.INFO
        assert LogLevel.WARNING.value == logging.WARNING
        assert LogLevel.ERROR.value == logging.ERROR
        assert LogLevel.CRITICAL.value == logging.CRITICAL

    def test_log_level_names(self) -> None:
        assert LogLevel.DEBUG.name == "DEBUG"
        assert LogLevel.CRITICAL.name == "CRITICAL"

    def test_trace_context_creation(self) -> None:
        ctx = TraceContext(trace_id="trace-1", span_id="span-1")
        assert ctx.trace_id == "trace-1"
        assert ctx.span_id == "span-1"

    def test_log_event_has_event_id(self) -> None:
        event = LogEvent("id1", 0.0, "INFO", "", "", {}, None, None, "", [], None, None, None, None)
        assert event.event_id == "id1"

    def test_log_event_has_timestamp(self) -> None:
        ts = time.time()
        event = LogEvent("id2", ts, "INFO", "", "", {}, None, None, "", [], None, None, None, None)
        assert event.timestamp == pytest.approx(ts, abs=1.0)

    def test_log_event_context_default_empty(self) -> None:
        event = LogEvent("id3", 0.0, "INFO", "", "", {}, None, None, "", [], None, None, None, None)
        assert event.context == {}


# ===========================================================================
# Initialisation tests
# ===========================================================================


class TestStructuredLoggerInit:
    """StructuredLogger creation and database setup."""

    def test_creates_db_file(self, tmp_path: Path) -> None:
        db = str(tmp_path / "init.db")
        StructuredLogger(db_path=db, jsonl_path=str(tmp_path / "x.jsonl"))
        assert os.path.exists(db)

    def test_creates_table(self, sl: StructuredLogger) -> None:
        import sqlite3

        with sqlite3.connect(sl._db_path) as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
        assert "log_events" in tables

    def test_creates_indexes(self, sl: StructuredLogger) -> None:
        import sqlite3

        with sqlite3.connect(sl._db_path) as conn:
            indexes = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            ]
        assert any("log" in idx.lower() for idx in indexes)

    def test_singleton_get_structured_logger(self, tmp_path: Path) -> None:
        import engine.observability.structured_logger as mod

        old = mod._instance
        mod._instance = None
        db = str(tmp_path / "singleton.db")
        jsonl = str(tmp_path / "singleton.jsonl")
        a = get_structured_logger(db_path=db, jsonl_path=jsonl)
        b = get_structured_logger()
        assert a is b
        mod._instance = old  # restore

    def test_custom_db_path(self, tmp_path: Path) -> None:
        custom_path = str(tmp_path / "custom" / "logs.db")
        sl = StructuredLogger(db_path=custom_path, jsonl_path=str(tmp_path / "c.jsonl"))
        assert os.path.exists(custom_path)


# ===========================================================================
# Logging API tests
# ===========================================================================


class TestLogging:
    """log(), info(), debug(), warning(), error(), critical()."""

    def test_log_info_creates_event(self, sl: StructuredLogger) -> None:
        event = sl.log(LogLevel.INFO, "hello world")
        assert isinstance(event, LogEvent)
        assert event.level == "INFO"
        assert event.message == "hello world"

    def test_log_error_creates_event(self, sl: StructuredLogger) -> None:
        event = sl.log(LogLevel.ERROR, "something went wrong")
        assert event.level == "ERROR"

    def test_convenience_info(self, sl: StructuredLogger) -> None:
        event = sl.info("info msg")
        assert event.level == "INFO"

    def test_convenience_debug(self, sl: StructuredLogger) -> None:
        event = sl.debug("debug msg")
        assert event.level == "DEBUG"

    def test_convenience_warning(self, sl: StructuredLogger) -> None:
        event = sl.warning("warn msg")
        assert event.level == "WARNING"

    def test_convenience_error(self, sl: StructuredLogger) -> None:
        event = sl.error("error msg")
        assert event.level == "ERROR"

    def test_convenience_critical(self, sl: StructuredLogger) -> None:
        event = sl.critical("critical msg")
        assert event.level == "CRITICAL"

    def test_log_with_context(self, sl: StructuredLogger) -> None:
        event = sl.log(LogLevel.INFO, "ctx test", context={"user": "alice", "req": 99})
        assert event.context == {"user": "alice", "req": 99}

    def test_log_with_tags(self, sl: StructuredLogger) -> None:
        event = sl.log(LogLevel.INFO, "tagged", tags=["a", "b"])
        assert "a" in event.tags
        assert "b" in event.tags

    def test_log_with_duration_ms(self, sl: StructuredLogger) -> None:
        event = sl.log(LogLevel.INFO, "timed", duration_ms=123.5)
        assert event.duration_ms == pytest.approx(123.5)

    def test_log_returns_log_event(self, sl: StructuredLogger) -> None:
        result = sl.log(LogLevel.DEBUG, "return type")
        assert isinstance(result, LogEvent)

    def test_log_event_id_is_uuid(self, sl: StructuredLogger) -> None:
        import uuid

        event = sl.log(LogLevel.INFO, "id test")
        # Should not raise
        uuid.UUID(event.event_id)

    def test_log_persisted_to_db(self, sl: StructuredLogger) -> None:
        event = sl.log(LogLevel.INFO, "persisted")
        results = sl.query(limit=10)
        assert any(e.event_id == event.event_id for e in results)


# ===========================================================================
# Trace context tests
# ===========================================================================


class TestTraceContext:
    """begin_trace(), end_trace(), and thread-local propagation."""

    def test_begin_trace_returns_context(self, sl: StructuredLogger) -> None:
        ctx = sl.begin_trace()
        sl.end_trace()
        assert isinstance(ctx, TraceContext)

    def test_begin_trace_auto_generates_id(self, sl: StructuredLogger) -> None:
        ctx = sl.begin_trace()
        sl.end_trace()
        assert ctx.trace_id
        assert len(ctx.trace_id) > 0

    def test_begin_trace_with_explicit_id(self, sl: StructuredLogger) -> None:
        ctx = sl.begin_trace(trace_id="my-trace-123")
        sl.end_trace()
        assert ctx.trace_id == "my-trace-123"

    def test_end_trace_clears_context(self, sl: StructuredLogger) -> None:
        import engine.observability.structured_logger as mod

        sl.begin_trace()
        sl.end_trace()
        assert mod._thread_local.trace_context is None

    def test_log_captures_trace_id(self, sl: StructuredLogger) -> None:
        ctx = sl.begin_trace(trace_id="trace-xyz")
        event = sl.log(LogLevel.INFO, "traced event")
        sl.end_trace()
        assert event.trace_id == "trace-xyz"

    def test_multiple_logs_same_trace_id(self, sl: StructuredLogger) -> None:
        sl.begin_trace(trace_id="shared-trace")
        e1 = sl.log(LogLevel.INFO, "first")
        e2 = sl.log(LogLevel.INFO, "second")
        sl.end_trace()
        assert e1.trace_id == e2.trace_id == "shared-trace"


# ===========================================================================
# @traced decorator tests
# ===========================================================================


class TestTracedDecorator:
    """@traced captures duration, sets trace context, re-raises exceptions."""

    def test_traced_captures_duration(self, tmp_path: Path) -> None:
        import engine.observability.structured_logger as mod

        old = mod._instance
        mod._instance = StructuredLogger(
            db_path=str(tmp_path / "traced.db"),
            jsonl_path=str(tmp_path / "traced.jsonl"),
        )

        @traced("svc", "fast_op")
        def fast_op() -> str:
            return "done"

        fast_op()

        events = mod._instance.query(service="svc")
        durations = [e.duration_ms for e in events if e.duration_ms is not None]
        assert len(durations) > 0
        assert durations[0] >= 0
        mod._instance = old

    def test_traced_logs_on_success(self, tmp_path: Path) -> None:
        import engine.observability.structured_logger as mod

        old = mod._instance
        mod._instance = StructuredLogger(
            db_path=str(tmp_path / "ts.db"),
            jsonl_path=str(tmp_path / "ts.jsonl"),
        )

        @traced("test_service", "my_op")
        def my_op() -> None:
            pass

        my_op()

        events = mod._instance.query(service="test_service", limit=5)
        assert any("my_op" in e.message for e in events)
        mod._instance = old

    def test_traced_captures_exception(self, tmp_path: Path) -> None:
        import engine.observability.structured_logger as mod

        old = mod._instance
        mod._instance = StructuredLogger(
            db_path=str(tmp_path / "te.db"),
            jsonl_path=str(tmp_path / "te.jsonl"),
        )

        @traced("exc_svc", "boom_op")
        def boom_op() -> None:
            raise ValueError("test error")

        with pytest.raises(ValueError):
            boom_op()

        events = mod._instance.query(service="exc_svc")
        error_events = [e for e in events if e.error_type == "ValueError"]
        assert len(error_events) > 0
        mod._instance = old

    def test_traced_re_raises_exception(self, sl: StructuredLogger) -> None:
        @traced("svc", "op")
        def fail_op() -> None:
            raise RuntimeError("kaboom")

        with pytest.raises(RuntimeError, match="kaboom"):
            fail_op()

    def test_traced_preserves_function_signature(self) -> None:
        @traced("svc", "named")
        def my_named_func(x: int, y: int) -> int:
            """My docstring."""
            return x + y

        assert my_named_func.__name__ == "my_named_func"
        assert my_named_func.__doc__ == "My docstring."

    def test_traced_sets_trace_context(self, tmp_path: Path) -> None:
        import engine.observability.structured_logger as mod

        old = mod._instance
        mod._instance = StructuredLogger(
            db_path=str(tmp_path / "ttc.db"),
            jsonl_path=str(tmp_path / "ttc.jsonl"),
        )
        captured_trace_ids: List[str] = []

        @traced("svc", "ctx_op")
        def ctx_op() -> None:
            ctx = getattr(mod._thread_local, "trace_context", None)
            if ctx:
                captured_trace_ids.append(ctx.trace_id)

        ctx_op()
        assert len(captured_trace_ids) > 0
        mod._instance = old

    def test_traced_with_return_value(self, sl: StructuredLogger) -> None:
        @traced("svc", "return_op")
        def add(a: int, b: int) -> int:
            return a + b

        result = add(3, 4)
        assert result == 7

    def test_traced_with_no_service_arg(self, sl: StructuredLogger) -> None:
        @traced()
        def bare_func() -> str:
            return "bare"

        assert bare_func() == "bare"


# ===========================================================================
# Query API tests
# ===========================================================================


class TestQuery:
    """query() filters and pagination."""

    def test_query_returns_events(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "q1")
        sl.log(LogLevel.INFO, "q2")
        results = sl.query(limit=10)
        assert len(results) >= 2

    def test_query_by_level(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "info event")
        sl.log(LogLevel.ERROR, "error event")
        errors = sl.query(level=LogLevel.ERROR)
        assert all(e.level == "ERROR" for e in errors)

    def test_query_by_service(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "svc-a event", service="svc_a")
        sl.log(LogLevel.INFO, "svc-b event", service="svc_b")
        results = sl.query(service="svc_a")
        assert all(e.service == "svc_a" for e in results)

    def test_query_by_tags(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "tagged event", tags=["special"])
        sl.log(LogLevel.INFO, "untagged event")
        results = sl.query(tags=["special"])
        assert all("special" in e.tags for e in results)

    def test_query_with_since(self, sl: StructuredLogger) -> None:
        before = time.time() - 10
        sl.log(LogLevel.INFO, "old-ish event")
        results = sl.query(since=before)
        assert len(results) >= 1

    def test_query_with_limit(self, sl: StructuredLogger) -> None:
        for i in range(10):
            sl.log(LogLevel.DEBUG, f"event {i}")
        results = sl.query(limit=3)
        assert len(results) <= 3

    def test_query_returns_log_event_objects(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "type check")
        results = sl.query()
        assert all(isinstance(e, LogEvent) for e in results)

    def test_query_empty_db(self, tmp_path: Path) -> None:
        fresh = StructuredLogger(
            db_path=str(tmp_path / "empty.db"),
            jsonl_path=str(tmp_path / "empty.jsonl"),
        )
        assert fresh.query() == []


# ===========================================================================
# Error summary tests
# ===========================================================================


class TestErrorSummary:
    """get_error_summary() counts errors correctly."""

    def test_error_summary_counts(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.ERROR, "e1", service="svc", error_type="ValueError")
        sl.log(LogLevel.ERROR, "e2", service="svc", error_type="ValueError")
        sl.log(LogLevel.CRITICAL, "e3", service="svc2", error_type="RuntimeError")
        summary = sl.get_error_summary(hours=1)
        assert summary["total_errors"] == 3
        assert summary["by_type"]["ValueError"] == 2
        assert summary["by_type"]["RuntimeError"] == 1

    def test_error_summary_by_service(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.ERROR, "e1", service="alpha", error_type="T")
        sl.log(LogLevel.ERROR, "e2", service="beta", error_type="T")
        summary = sl.get_error_summary(hours=1)
        assert "alpha" in summary["by_service"]
        assert "beta" in summary["by_service"]

    def test_error_summary_empty(self, sl: StructuredLogger) -> None:
        summary = sl.get_error_summary(hours=1)
        assert summary["total_errors"] == 0
        assert summary["by_type"] == {}
        assert summary["by_service"] == {}

    def test_error_summary_structure(self, sl: StructuredLogger) -> None:
        summary = sl.get_error_summary()
        assert "period_hours" in summary
        assert "total_errors" in summary
        assert "by_type" in summary
        assert "by_service" in summary


# ===========================================================================
# Slow operations tests
# ===========================================================================


class TestSlowOperations:
    """get_slow_operations() threshold filtering."""

    def test_slow_operations_found(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "slow op", duration_ms=2000.0)
        sl.log(LogLevel.INFO, "fast op", duration_ms=10.0)
        slow = sl.get_slow_operations(threshold_ms=500, hours=1)
        assert any(op["duration_ms"] == 2000.0 for op in slow)

    def test_slow_operations_threshold(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "borderline", duration_ms=499.0)
        sl.log(LogLevel.INFO, "over", duration_ms=501.0)
        slow = sl.get_slow_operations(threshold_ms=500, hours=1)
        durations = [op["duration_ms"] for op in slow]
        assert 499.0 not in durations
        assert 501.0 in durations

    def test_slow_operations_empty(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "no duration event")
        slow = sl.get_slow_operations(threshold_ms=500, hours=1)
        # Events without duration_ms should not appear
        assert all(op["duration_ms"] is not None for op in slow)


# ===========================================================================
# get_trace tests
# ===========================================================================


class TestGetTrace:
    """get_trace() retrieves events by trace_id."""

    def test_get_trace_returns_events(self, sl: StructuredLogger) -> None:
        sl.begin_trace(trace_id="tr-99")
        sl.log(LogLevel.INFO, "trace event 1")
        sl.log(LogLevel.INFO, "trace event 2")
        sl.end_trace()
        events = sl.get_trace("tr-99")
        assert len(events) == 2
        assert all(e.trace_id == "tr-99" for e in events)

    def test_get_trace_unknown_returns_empty(self, sl: StructuredLogger) -> None:
        events = sl.get_trace("nonexistent-trace")
        assert events == []


# ===========================================================================
# flush_old_logs tests
# ===========================================================================


class TestFlushOldLogs:
    """flush_old_logs() retention window purge."""

    def test_flush_deletes_old_records(self, sl: StructuredLogger) -> None:
        import sqlite3

        # Insert a record with a very old timestamp directly.
        old_ts = time.time() - 8 * 86400  # 8 days ago
        with sl._write_lock:
            with sqlite3.connect(sl._db_path) as conn:
                conn.execute(
                    "INSERT INTO log_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "old-id",
                        old_ts,
                        "INFO",
                        "svc",
                        "old msg",
                        "{}",
                        None,
                        None,
                        "svc",
                        "[]",
                        None,
                        None,
                        None,
                        None,
                    ),
                )

        deleted = sl.flush_old_logs(days=7)
        assert deleted >= 1

        # Verify the old record is gone.
        with sqlite3.connect(sl._db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM log_events WHERE event_id = 'old-id'"
            ).fetchone()
        assert row[0] == 0

    def test_flush_keeps_recent(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "recent event")
        deleted = sl.flush_old_logs(days=7)
        results = sl.query()
        assert any(e.message == "recent event" for e in results)


# ===========================================================================
# JSON formatter tests
# ===========================================================================


class TestJSONFormatter:
    """JSON line output format."""

    def test_json_output_is_valid_json(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "json test")
        with open(sl._jsonl_path, encoding="utf-8") as fh:
            line = fh.readline().strip()
        parsed = json.loads(line)
        assert isinstance(parsed, dict)

    def test_json_has_required_fields(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "fields test")
        with open(sl._jsonl_path, encoding="utf-8") as fh:
            line = fh.readline().strip()
        parsed = json.loads(line)
        for field in ("ts", "level", "svc", "msg", "ctx"):
            assert field in parsed, f"Missing field: {field}"

    def test_json_single_line(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "single line test")
        with open(sl._jsonl_path, encoding="utf-8") as fh:
            content = fh.read()
        lines = [l for l in content.split("\n") if l.strip()]
        assert len(lines) == 1
        # Must be parseable as a single JSON object.
        parsed = json.loads(lines[0])
        assert isinstance(parsed, dict)

    def test_json_no_pretty_print(self, sl: StructuredLogger) -> None:
        sl.log(LogLevel.INFO, "compact test", context={"a": 1})
        with open(sl._jsonl_path, encoding="utf-8") as fh:
            line = fh.readline().strip()
        # Compact JSON has no indentation whitespace after colons.
        assert "\n" not in line


# ===========================================================================
# install_root_handler tests
# ===========================================================================


class TestInstallRootHandler:
    """install_root_handler() idempotency and stdlib capture."""

    def test_install_idempotent(self, sl: StructuredLogger) -> None:
        import engine.observability.structured_logger as mod

        old_flag = mod._root_handler_installed
        mod._root_handler_installed = False

        sl.install_root_handler()
        sl.install_root_handler()  # second call must not raise or double-add

        root = logging.getLogger()
        struct_handlers = [
            h
            for h in root.handlers
            if h.__class__.__name__ == "_StructuredHandler"
        ]
        assert len(struct_handlers) <= 1
        mod._root_handler_installed = old_flag

    def test_install_captures_stdlib(self, tmp_path: Path) -> None:
        """Stdlib logging after install_root_handler is stored in SQLite."""
        import engine.observability.structured_logger as mod

        old_instance = mod._instance
        old_flag = mod._root_handler_installed
        mod._root_handler_installed = False
        mod._instance = StructuredLogger(
            db_path=str(tmp_path / "hook.db"),
            jsonl_path=str(tmp_path / "hook.jsonl"),
        )

        sl_local = mod._instance
        sl_local.install_root_handler()

        stdlib_log = logging.getLogger("cosysim.test_hook")
        stdlib_log.setLevel(logging.DEBUG)
        stdlib_log.info("stdlib captured message")

        events = sl_local.query(service="cosysim.test_hook", limit=10)
        assert any("stdlib captured" in e.message for e in events)

        mod._instance = old_instance
        mod._root_handler_installed = old_flag


# ===========================================================================
# BoundLogger tests
# ===========================================================================


class TestBoundLogger:
    """BoundLogger pre-fills service name on every call."""

    def test_bound_logger_prefills_service(self, bound: BoundLogger) -> None:
        event = bound.info("bound test")
        assert event.service == "test_svc"

    def test_bound_logger_all_methods(self, bound: BoundLogger) -> None:
        assert bound.info("i").level == "INFO"
        assert bound.debug("d").level == "DEBUG"
        assert bound.warning("w").level == "WARNING"
        assert bound.error("e").level == "ERROR"
        assert bound.critical("c").level == "CRITICAL"

    def test_get_logger_returns_bound_logger(self, tmp_path: Path) -> None:
        import engine.observability.structured_logger as mod

        old = mod._instance
        mod._instance = StructuredLogger(
            db_path=str(tmp_path / "gl.db"),
            jsonl_path=str(tmp_path / "gl.jsonl"),
        )
        bl = get_logger("my.module")
        assert isinstance(bl, BoundLogger)
        assert bl.service == "my.module"
        mod._instance = old

    def test_bound_logger_query_restricted_by_service(self, bound: BoundLogger) -> None:
        bound.info("specific service event")
        results = bound.query(limit=10)
        assert all(e.service == "test_svc" for e in results)

    def test_bound_logger_begin_end_trace(self, bound: BoundLogger) -> None:
        ctx = bound.begin_trace("bl-trace")
        assert ctx.trace_id == "bl-trace"
        bound.end_trace()


# ===========================================================================
# Thread safety tests
# ===========================================================================


class TestThreadSafety:
    """Concurrent log writes do not corrupt the database."""

    def test_concurrent_writes(self, sl: StructuredLogger) -> None:
        errors: List[Exception] = []

        def write_logs(service: str, n: int) -> None:
            try:
                for i in range(n):
                    sl.log(LogLevel.INFO, f"msg {i}", service=service)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write_logs, args=(f"svc{j}", 20)) for j in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        events = sl.query(limit=200)
        assert len(events) == 100

    def test_thread_local_trace_context(self, sl: StructuredLogger) -> None:
        """Each thread gets its own trace context."""
        trace_ids: dict = {}

        def run(tid: int) -> None:
            ctx = sl.begin_trace()
            trace_ids[tid] = ctx.trace_id
            time.sleep(0.02)
            sl.end_trace()

        threads = [threading.Thread(target=run, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All trace IDs should be distinct.
        assert len(set(trace_ids.values())) == 4

    def test_concurrent_different_traces(self, sl: StructuredLogger) -> None:
        errors: List[Exception] = []

        def run() -> None:
            try:
                ctx = sl.begin_trace()
                event = sl.log(LogLevel.INFO, "traced event")
                assert event.trace_id == ctx.trace_id
                sl.end_trace()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors: {errors}"
