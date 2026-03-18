"""
Observability MCP Skills for CosySim — pack ``observability``, category ``system``.

Provides 10 skills bridging the StructuredLogger and IntegrationRunner APIs
to the MCP tool interface so agents can query logs, inspect health, and run
integration tests directly.

Skills:
    query_logs             — search structured log store
    get_error_summary      — error counts by type/service
    get_slow_operations    — slow span report
    flush_old_logs         — purge aged log records
    get_trace              — retrieve all events for a trace_id
    run_integration_tests  — execute integration test suite
    get_integration_results — recent test run history
    get_flaky_tests        — tests with high failure rate
    probe_services         — check which services are reachable
    register_integration_test — dynamic test registration from code string
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy accessors (avoid circular imports at module load time)
# ---------------------------------------------------------------------------


def _sl():
    """Return the global StructuredLogger singleton."""
    from engine.observability.structured_logger import get_structured_logger

    return get_structured_logger()


def _ir():
    """Return the global IntegrationRunner singleton."""
    from engine.testing.integration_runner import get_integration_runner

    return get_integration_runner()


# ---------------------------------------------------------------------------
# Logging skills (5)
# ---------------------------------------------------------------------------


@skill(
    pack="observability",
    description=(
        "Search the structured log store for recent events.  "
        "Optionally filter by level (DEBUG/INFO/WARNING/ERROR/CRITICAL), "
        "service name, and look-back window in hours.  "
        "Returns a JSON list of log events."
    ),
    category="system",
    cooldown=0.0,
    cost=1.0,
    tags=["observability", "logs", "query"],
)
def query_logs(
    level: Optional[str] = None,
    service: Optional[str] = None,
    since_hours: float = 1.0,
    limit: int = 50,
) -> str:
    """Query the structured log store.

    Args:
        level: Optional level filter (DEBUG/INFO/WARNING/ERROR/CRITICAL).
        service: Optional service name filter.
        since_hours: Look-back window in hours (default 1).
        limit: Maximum number of events to return (default 50).

    Returns:
        JSON string containing a list of log event dicts.
    """
    import time

    from engine.observability.structured_logger import LogLevel

    level_obj = None
    if level:
        try:
            level_obj = LogLevel[level.upper()]
        except KeyError:
            return json.dumps({"error": f"Unknown log level: {level}"})

    since_ts = time.time() - since_hours * 3600
    events = _sl().query(
        level=level_obj,
        service=service or None,
        since=since_ts,
        limit=limit,
    )
    return json.dumps(
        [
            {
                "event_id": e.event_id,
                "timestamp": e.timestamp,
                "level": e.level,
                "service": e.service,
                "message": e.message,
                "context": e.context,
                "trace_id": e.trace_id,
                "duration_ms": e.duration_ms,
                "error_type": e.error_type,
                "tags": e.tags,
            }
            for e in events
        ]
    )


@skill(
    pack="observability",
    description=(
        "Return error counts grouped by error type and service for the last N hours. "
        "Useful for spotting recurring error patterns at a glance."
    ),
    category="system",
    cooldown=0.0,
    cost=1.0,
    tags=["observability", "errors", "summary"],
)
def get_error_summary(hours: float = 24.0) -> str:
    """Summarise errors in the structured log store.

    Args:
        hours: Look-back window in hours (default 24).

    Returns:
        JSON string with keys: period_hours, total_errors, by_type, by_service.
    """
    summary = _sl().get_error_summary(hours=hours)
    return json.dumps(summary)


@skill(
    pack="observability",
    description=(
        "Find traced operations that exceeded the duration threshold (ms). "
        "Helps identify performance bottlenecks in the system."
    ),
    category="system",
    cooldown=0.0,
    cost=1.0,
    tags=["observability", "performance", "slow"],
)
def get_slow_operations(threshold_ms: float = 500.0, hours: float = 24.0) -> str:
    """Find operations slower than *threshold_ms*.

    Args:
        threshold_ms: Minimum duration to consider slow (default 500 ms).
        hours: Look-back window in hours (default 24).

    Returns:
        JSON string containing a list of slow operation dicts.
    """
    ops = _sl().get_slow_operations(threshold_ms=threshold_ms, hours=hours)
    return json.dumps(ops)


@skill(
    pack="observability",
    description=(
        "Purge structured log records older than N days from the log store. "
        "Returns the number of records deleted."
    ),
    category="system",
    cooldown=60.0,
    cost=1.0,
    tags=["observability", "maintenance", "purge"],
)
def flush_old_logs(days: int = 7) -> str:
    """Delete log events older than *days* days.

    Args:
        days: Retention window in days (default 7).

    Returns:
        JSON string with key: deleted_count.
    """
    count = _sl().flush_old_logs(days=days)
    return json.dumps({"deleted_count": count, "days": days})


@skill(
    pack="observability",
    description=(
        "Retrieve all log events that share a specific trace_id. "
        "Useful for tracing a single request or workflow end-to-end."
    ),
    category="system",
    cooldown=0.0,
    cost=1.0,
    tags=["observability", "tracing", "trace"],
)
def get_trace(trace_id: str) -> str:
    """Retrieve all events for a trace.

    Args:
        trace_id: The trace identifier to look up.

    Returns:
        JSON string containing a list of log event dicts for the trace.
    """
    events = _sl().get_trace(trace_id)
    return json.dumps(
        [
            {
                "event_id": e.event_id,
                "timestamp": e.timestamp,
                "level": e.level,
                "service": e.service,
                "message": e.message,
                "span_id": e.span_id,
                "duration_ms": e.duration_ms,
                "error_type": e.error_type,
            }
            for e in events
        ]
    )


# ---------------------------------------------------------------------------
# Integration test skills (5)
# ---------------------------------------------------------------------------


@skill(
    pack="observability",
    description=(
        "Run the integration test suite.  Pass optional comma-separated tags "
        "to filter which tests to execute.  Services that are unavailable are "
        "automatically skipped.  Returns a JSON list of test results."
    ),
    category="system",
    cooldown=10.0,
    cost=2.0,
    tags=["observability", "integration", "testing"],
)
def run_integration_tests(tags: Optional[str] = None) -> str:
    """Execute integration tests (skipping unavailable services).

    Args:
        tags: Optional comma-separated tag filter (e.g. ``"smoke,nexus"``).

    Returns:
        JSON string containing a list of result dicts.
    """
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    results = _ir().run(tags=tag_list, skip_unavailable=True)
    return json.dumps(
        [
            {
                "test_id": r.test_id,
                "passed": r.passed,
                "skipped": r.skipped,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in results
        ]
    )


@skill(
    pack="observability",
    description=(
        "Retrieve recent integration test run history from the results store. "
        "Optionally filter by test_id and limit the number of records."
    ),
    category="system",
    cooldown=0.0,
    cost=1.0,
    tags=["observability", "integration", "history"],
)
def get_integration_results(test_id: Optional[str] = None, limit: int = 20) -> str:
    """Query historical integration test results.

    Args:
        test_id: Optional filter for a specific test.
        limit: Maximum number of rows to return (default 20).

    Returns:
        JSON string containing a list of result dicts.
    """
    results = _ir().get_results(test_id=test_id or None, limit=limit)
    return json.dumps(
        [
            {
                "result_id": r.result_id,
                "test_id": r.test_id,
                "passed": r.passed,
                "skipped": r.skipped,
                "duration_ms": r.duration_ms,
                "error": r.error,
                "timestamp": r.timestamp,
            }
            for r in results
        ]
    )


@skill(
    pack="observability",
    description=(
        "Identify integration tests with a failure rate above 20% (flaky tests). "
        "Returns test IDs, total runs, failure counts, and failure rates."
    ),
    category="system",
    cooldown=0.0,
    cost=1.0,
    tags=["observability", "integration", "flaky"],
)
def get_flaky_tests() -> str:
    """Find integration tests with a high failure rate.

    Returns:
        JSON string containing a list of flaky test dicts.
    """
    flaky = _ir().get_flaky_tests(threshold=0.2)
    return json.dumps(flaky)


@skill(
    pack="observability",
    description=(
        "Probe all known external services (lmstudio, nexus, comfyui, mcp) "
        "to check which are currently reachable.  "
        "Returns a JSON object mapping service name to boolean."
    ),
    category="system",
    cooldown=5.0,
    cost=1.0,
    tags=["observability", "health", "services"],
)
def probe_services() -> str:
    """Check reachability of all known services.

    Returns:
        JSON string mapping service name to reachability boolean.
    """
    status = _ir().probe_services()
    return json.dumps(status)


@skill(
    pack="observability",
    description=(
        "Dynamically register a new integration test from a Python code string. "
        "The code must define a callable named 'run_test' with no parameters. "
        "Provide a test name, comma-separated service dependencies, and the code."
    ),
    category="system",
    cooldown=5.0,
    cost=1.0,
    tags=["observability", "integration", "dynamic"],
)
def register_integration_test(
    name: str,
    services_json: str = "[]",
    test_code: str = "def run_test(): pass",
) -> str:
    """Register an integration test from a code string.

    Args:
        name: Human-readable test name (used as test_id slug).
        services_json: JSON array of required service names (default ``[]``).
        test_code: Python source defining a ``run_test()`` callable.

    Returns:
        JSON string with keys: test_id, status.
    """
    try:
        services = json.loads(services_json)
        if not isinstance(services, list):
            return json.dumps({"error": "services_json must be a JSON array"})
        test_id = _ir().register_dynamic(
            name=name,
            services=services,
            test_code=test_code,
        )
        return json.dumps({"test_id": test_id, "status": "registered"})
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.warning("register_integration_test failed: %s", exc)
        return json.dumps({"error": str(exc)})
