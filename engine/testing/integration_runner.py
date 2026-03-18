"""
Integration testing framework for CosySim service boundaries.

Provides a lightweight harness for tests that exercise real service
boundaries (LMStudio, Nexus, MCP skills, ComfyUI, etc.).  Tests that
depend on an unavailable service are automatically *skipped* rather
than marked as failures.

Exports:
    get_integration_runner()           — global IntegrationRunner singleton
    IntegrationRunner                  — core orchestrator class
    IntegrationTest                    — test definition dataclass
    IntegrationResult                  — test result dataclass
    IntegrationSuite                   — named test collection
    ServiceProbe                       — liveness checker for services
    integration_test(...)              — decorator for inline test registration
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
import sqlite3
import threading
import time
import traceback
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "data/integration_results.db"

# Module-level singleton.
_instance: Optional["IntegrationRunner"] = None
_instance_lock: threading.Lock = threading.Lock()

# ---------------------------------------------------------------------------
# Known service probe endpoints / strategies
# ---------------------------------------------------------------------------

_SERVICE_PROBES: Dict[str, Dict[str, Any]] = {
    "lmstudio": {"type": "http", "url": "http://localhost:1234/api/v1/models"},
    "comfyui": {"type": "http", "url": "http://localhost:8188/"},
    "nexus": {"type": "http", "url": "http://localhost:8765/api/health"},
    "mcp": {"type": "import", "module": "engine.skills.skill", "attr": None},
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class IntegrationTest:
    """Definition of a single integration test.

    Attributes:
        test_id: Unique identifier (slug style, e.g. ``lmstudio_ping``).
        name: Human-readable name.
        services: List of service names that must be reachable.
        test_fn: The callable that performs the test (no args, no return).
        setup_fn: Optional pre-test callable.
        teardown_fn: Optional post-test callable.
        timeout_seconds: Maximum wall-clock time before timeout.
        tags: Free-form tags for filtering.
        requires_gpu: Whether GPU must be available.
    """

    test_id: str
    name: str
    services: List[str]
    test_fn: Callable[[], None]
    setup_fn: Optional[Callable[[], None]] = None
    teardown_fn: Optional[Callable[[], None]] = None
    timeout_seconds: float = 30.0
    tags: List[str] = dataclasses.field(default_factory=list)
    requires_gpu: bool = False


@dataclasses.dataclass
class IntegrationResult:
    """Result of a single integration test run.

    Attributes:
        result_id: Unique UUID for this result row.
        test_id: The test that was run.
        passed: True if the test passed, False otherwise.
        skipped: True if the test was skipped (service unavailable).
        duration_ms: Wall-clock duration in milliseconds.
        error: Exception message if the test failed.
        logs: Captured log lines.
        metrics: Arbitrary metrics collected during the run.
        timestamp: Unix epoch when the run started.
    """

    result_id: str
    test_id: str
    passed: bool
    skipped: bool
    duration_ms: float
    error: Optional[str]
    logs: List[str]
    metrics: Dict[str, Any]
    timestamp: float


@dataclasses.dataclass
class IntegrationSuite:
    """Named collection of IntegrationTest instances.

    Attributes:
        name: Suite identifier.
        test_ids: Ordered list of test IDs belonging to this suite.
    """

    name: str
    test_ids: List[str] = dataclasses.field(default_factory=list)

    def add(self, test_id: str) -> None:
        """Append *test_id* to this suite."""
        if test_id not in self.test_ids:
            self.test_ids.append(test_id)


# ---------------------------------------------------------------------------
# ServiceProbe
# ---------------------------------------------------------------------------


class ServiceProbe:
    """Checks whether a named service is reachable.

    Uses lightweight probes: HTTP GET for HTTP services, import checks for
    in-process services.  Results are intentionally NOT cached so that
    transient failures are detectable between test runs.
    """

    def probe(self, service_name: str) -> bool:
        """Return True if *service_name* appears to be reachable.

        An empty / None service name always returns True (no dependency).

        Args:
            service_name: Service identifier key.

        Returns:
            Boolean reachability flag.
        """
        if not service_name:
            return True

        spec = _SERVICE_PROBES.get(service_name)
        if spec is None:
            logger.debug("ServiceProbe: unknown service '%s' — assuming down", service_name)
            return False

        probe_type = spec.get("type")
        if probe_type == "http":
            return self._probe_http(spec["url"])
        if probe_type == "import":
            return self._probe_import(spec["module"])
        return False

    def probe_all(self, service_names: List[str]) -> Dict[str, bool]:
        """Probe multiple services, returning a name → bool mapping."""
        return {svc: self.probe(svc) for svc in service_names}

    @staticmethod
    def _probe_http(url: str, timeout: float = 3.0) -> bool:
        """Attempt an HTTP GET and return True on HTTP 2xx response."""
        try:
            import requests  # optional dependency

            resp = requests.get(url, timeout=timeout)
            return resp.status_code < 400
        except Exception:
            return False

    @staticmethod
    def _probe_import(module_path: str) -> bool:
        """Return True if *module_path* can be imported successfully."""
        try:
            import importlib

            importlib.import_module(module_path)
            return True
        except ImportError:
            return False


# ---------------------------------------------------------------------------
# IntegrationRunner
# ---------------------------------------------------------------------------


class IntegrationRunner:
    """Orchestrates integration test registration, execution, and history.

    Thread-safe singleton obtained via :func:`get_integration_runner`.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._tests: Dict[str, IntegrationTest] = {}
        self._suites: Dict[str, IntegrationSuite] = {}
        self._probe = ServiceProbe()
        import os

        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # DB initialisation
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS integration_tests (
                        test_id         TEXT PRIMARY KEY,
                        name            TEXT NOT NULL,
                        services        TEXT NOT NULL DEFAULT '[]',
                        tags            TEXT NOT NULL DEFAULT '[]',
                        requires_gpu    INTEGER NOT NULL DEFAULT 0,
                        timeout_seconds REAL NOT NULL DEFAULT 30,
                        registered_at   REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS integration_results (
                        result_id   TEXT PRIMARY KEY,
                        test_id     TEXT NOT NULL,
                        passed      INTEGER NOT NULL,
                        skipped     INTEGER NOT NULL DEFAULT 0,
                        duration_ms REAL NOT NULL,
                        error       TEXT,
                        logs        TEXT NOT NULL DEFAULT '[]',
                        metrics     TEXT NOT NULL DEFAULT '{}',
                        timestamp   REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_results_test_ts "
                    "ON integration_results(test_id, timestamp)"
                )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, test: IntegrationTest) -> None:
        """Add an IntegrationTest to the registry.

        Args:
            test: The test to register.

        Raises:
            ValueError: If a test with the same test_id is already registered.
        """
        with self._lock:
            if test.test_id in self._tests:
                raise ValueError(f"Integration test '{test.test_id}' is already registered.")
            self._tests[test.test_id] = test
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO integration_tests
                        (test_id, name, services, tags, requires_gpu, timeout_seconds, registered_at)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        test.test_id,
                        test.name,
                        json.dumps(test.services),
                        json.dumps(test.tags),
                        int(test.requires_gpu),
                        test.timeout_seconds,
                        time.time(),
                    ),
                )

    def register_suite(self, suite: IntegrationSuite) -> None:
        """Register a named suite.

        Args:
            suite: The suite to register.
        """
        with self._lock:
            self._suites[suite.name] = suite

    # ------------------------------------------------------------------
    # Probing
    # ------------------------------------------------------------------

    def probe_service(self, service_name: str) -> bool:
        """Check if a single service is reachable.

        Args:
            service_name: Service identifier.

        Returns:
            True if reachable.
        """
        return self._probe.probe(service_name)

    def probe_services(self, service_names: Optional[List[str]] = None) -> Dict[str, bool]:
        """Check all known (or provided) services.

        Args:
            service_names: Subset to probe; defaults to all known services.

        Returns:
            Dict mapping service name → bool.
        """
        names = service_names if service_names is not None else list(_SERVICE_PROBES.keys())
        return self._probe.probe_all(names)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(
        self,
        test_ids: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        skip_unavailable: bool = True,
    ) -> List[IntegrationResult]:
        """Execute integration tests and return results.

        Args:
            test_ids: Subset of test IDs to run.  Runs all if None.
            tags: Only run tests whose tags overlap with this list.
            skip_unavailable: If True, skip tests whose required services
                are unreachable rather than failing them.

        Returns:
            List of IntegrationResult, one per test.
        """
        with self._lock:
            candidates = list(self._tests.values())

        if test_ids is not None:
            candidates = [t for t in candidates if t.test_id in test_ids]
        if tags:
            candidates = [
                t for t in candidates if any(tag in t.tags for tag in tags)
            ]

        results = []
        for test in candidates:
            result = self._execute_one(test, skip_unavailable=skip_unavailable)
            results.append(result)
        return results

    def run_suite(self, suite_name: str, skip_unavailable: bool = True) -> List[IntegrationResult]:
        """Run all tests belonging to a named suite.

        Args:
            suite_name: Suite to execute.
            skip_unavailable: Passed to :meth:`run`.

        Returns:
            List of IntegrationResult.
        """
        suite = self._suites.get(suite_name)
        if suite is None:
            logger.warning("IntegrationRunner: suite '%s' not found", suite_name)
            return []
        return self.run(test_ids=suite.test_ids, skip_unavailable=skip_unavailable)

    def _execute_one(
        self, test: IntegrationTest, skip_unavailable: bool
    ) -> IntegrationResult:
        """Run a single test, handling setup/teardown and timeouts.

        Args:
            test: The test to execute.
            skip_unavailable: Skip instead of fail when services are down.

        Returns:
            IntegrationResult for this run.
        """
        start_ts = time.time()
        logs: List[str] = []
        metrics: Dict[str, Any] = {}

        # Service availability check.
        if skip_unavailable and test.services:
            for svc in test.services:
                if not self._probe.probe(svc):
                    duration_ms = (time.time() - start_ts) * 1000.0
                    result = IntegrationResult(
                        result_id=str(uuid.uuid4()),
                        test_id=test.test_id,
                        passed=False,
                        skipped=True,
                        duration_ms=duration_ms,
                        error=f"Service '{svc}' is not available",
                        logs=logs,
                        metrics=metrics,
                        timestamp=start_ts,
                    )
                    self._persist_result(result)
                    return result

        # Setup.
        if test.setup_fn is not None:
            try:
                test.setup_fn()
            except Exception as exc:
                duration_ms = (time.time() - start_ts) * 1000.0
                result = IntegrationResult(
                    result_id=str(uuid.uuid4()),
                    test_id=test.test_id,
                    passed=False,
                    skipped=False,
                    duration_ms=duration_ms,
                    error=f"Setup failed: {exc}",
                    logs=logs,
                    metrics=metrics,
                    timestamp=start_ts,
                )
                self._persist_result(result)
                return result

        # Execute with timeout (thread-based, best-effort).
        error: Optional[str] = None
        passed = False

        try:
            result_container: Dict[str, Any] = {}

            def _run() -> None:
                try:
                    test.test_fn()
                    result_container["passed"] = True
                except Exception as exc:
                    result_container["passed"] = False
                    result_container["error"] = (
                        f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                    )

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
            thread.join(timeout=test.timeout_seconds)

            if thread.is_alive():
                error = f"Test timed out after {test.timeout_seconds}s"
                passed = False
            else:
                passed = result_container.get("passed", False)
                error = result_container.get("error")

        except Exception as exc:
            error = f"Runner error: {exc}\n{traceback.format_exc()}"
            passed = False

        # Teardown.
        if test.teardown_fn is not None:
            try:
                test.teardown_fn()
            except Exception as exc:
                logs.append(f"Teardown warning: {exc}")

        duration_ms = (time.time() - start_ts) * 1000.0
        result = IntegrationResult(
            result_id=str(uuid.uuid4()),
            test_id=test.test_id,
            passed=passed,
            skipped=False,
            duration_ms=duration_ms,
            error=error,
            logs=logs,
            metrics=metrics,
            timestamp=start_ts,
        )
        self._persist_result(result)
        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_result(self, result: IntegrationResult) -> None:
        with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO integration_results
                        (result_id, test_id, passed, skipped, duration_ms,
                         error, logs, metrics, timestamp)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        result.result_id,
                        result.test_id,
                        int(result.passed),
                        int(result.skipped),
                        result.duration_ms,
                        result.error,
                        json.dumps(result.logs),
                        json.dumps(result.metrics),
                        result.timestamp,
                    ),
                )

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_results(
        self,
        test_id: Optional[str] = None,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> List[IntegrationResult]:
        """Query historical test results.

        Args:
            test_id: Filter by a specific test.
            since: Unix timestamp lower bound.
            limit: Maximum rows to return.

        Returns:
            List of IntegrationResult, newest first.
        """
        clauses: List[str] = []
        params: List[Any] = []

        if test_id is not None:
            clauses.append("test_id = ?")
            params.append(test_id)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT result_id, test_id, passed, skipped, duration_ms, "
            f"error, logs, metrics, timestamp "
            f"FROM integration_results {where} "
            f"ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            IntegrationResult(
                result_id=r[0],
                test_id=r[1],
                passed=bool(r[2]),
                skipped=bool(r[3]),
                duration_ms=r[4],
                error=r[5],
                logs=json.loads(r[6] or "[]"),
                metrics=json.loads(r[7] or "{}"),
                timestamp=r[8],
            )
            for r in rows
        ]

    def get_flaky_tests(self, threshold: float = 0.2) -> List[Dict[str, Any]]:
        """Return tests whose failure rate exceeds *threshold*.

        Only non-skipped runs are counted.

        Args:
            threshold: Failure rate (0–1) above which a test is flagged.

        Returns:
            List of dicts with keys: test_id, total_runs, failures, failure_rate.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    test_id,
                    COUNT(*) AS total_runs,
                    SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END) AS failures,
                    CAST(SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) AS failure_rate
                FROM integration_results
                WHERE skipped = 0
                GROUP BY test_id
                HAVING failure_rate > ?
                ORDER BY failure_rate DESC
                """,
                (threshold,),
            ).fetchall()

        return [
            {
                "test_id": r[0],
                "total_runs": r[1],
                "failures": r[2],
                "failure_rate": r[3],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Scheduler integration
    # ------------------------------------------------------------------

    def schedule_suite(self, suite_name: str, cron_expr: str) -> None:
        """Wire a suite to the CosySim scheduler daemon.

        Args:
            suite_name: Name of the registered suite to schedule.
            cron_expr: Schedule string accepted by TaskSchedulerDaemon
                (e.g. ``"daily"``, ``"every_6h"``).
        """
        try:
            from engine.nexus.scheduler_daemon import TaskSchedulerDaemon

            daemon = TaskSchedulerDaemon()
            task_id = f"integration_suite_{suite_name}"
            daemon.register(
                task_id=task_id,
                name=f"Integration Suite: {suite_name}",
                schedule=cron_expr,
                callback=lambda: self.run_suite(suite_name),
            )
            logger.info(
                "IntegrationRunner: suite '%s' scheduled as '%s' (%s)",
                suite_name,
                task_id,
                cron_expr,
            )
        except Exception as exc:
            logger.warning(
                "IntegrationRunner: could not schedule suite '%s': %s",
                suite_name,
                exc,
            )

    # ------------------------------------------------------------------
    # Dynamic registration helpers (used by pre-built tests module)
    # ------------------------------------------------------------------

    def register_dynamic(
        self,
        name: str,
        services: List[str],
        test_code: str,
        tags: Optional[List[str]] = None,
        timeout_seconds: float = 30.0,
    ) -> str:
        """Register a test from a code string (exec-based).

        Args:
            name: Human-readable name (used as test_id slug).
            services: Required service names.
            test_code: Python source of a callable named ``run_test``.
            tags: Optional tags.
            timeout_seconds: Execution timeout.

        Returns:
            The assigned test_id.

        Raises:
            ValueError: If the code does not define ``run_test``.
        """
        namespace: Dict[str, Any] = {}
        exec(compile(test_code, "<dynamic>", "exec"), namespace)  # noqa: S102
        fn = namespace.get("run_test")
        if fn is None or not callable(fn):
            raise ValueError("test_code must define a callable named 'run_test'")

        test_id = name.lower().replace(" ", "_")
        test = IntegrationTest(
            test_id=test_id,
            name=name,
            services=services,
            test_fn=fn,
            tags=tags or [],
            timeout_seconds=timeout_seconds,
        )
        self.register(test)
        return test_id

    def list_tests(self) -> List[Dict[str, Any]]:
        """Return metadata for all registered tests."""
        with self._lock:
            return [
                {
                    "test_id": t.test_id,
                    "name": t.name,
                    "services": t.services,
                    "tags": t.tags,
                    "timeout_seconds": t.timeout_seconds,
                    "requires_gpu": t.requires_gpu,
                }
                for t in self._tests.values()
            ]


# ---------------------------------------------------------------------------
# @integration_test decorator
# ---------------------------------------------------------------------------


def integration_test(
    name: str,
    services: Optional[List[str]] = None,
    timeout: float = 30.0,
    tags: Optional[List[str]] = None,
    requires_gpu: bool = False,
) -> Callable[[Callable[[], None]], Callable[[], None]]:
    """Decorator that registers the wrapped function as an IntegrationTest.

    Usage::

        @integration_test("my_test", services=["lmstudio"], timeout=10)
        def test_lmstudio():
            import requests
            resp = requests.get("http://localhost:1234/api/v1/models", timeout=5)
            assert resp.status_code == 200

    Args:
        name: Human-readable test name; also used as test_id slug.
        services: Service names that must be reachable.
        timeout: Timeout in seconds.
        tags: Free-form tags.
        requires_gpu: GPU requirement flag.

    Returns:
        The original function (decorator is side-effect only).
    """
    svc_list = services or []
    tag_list = tags or []

    def decorator(func: Callable[[], None]) -> Callable[[], None]:
        test_id = name.lower().replace(" ", "_")
        it = IntegrationTest(
            test_id=test_id,
            name=name,
            services=svc_list,
            test_fn=func,
            tags=tag_list,
            timeout_seconds=timeout,
            requires_gpu=requires_gpu,
        )
        try:
            get_integration_runner().register(it)
        except ValueError:
            # Already registered (e.g. module reloaded in tests).
            pass

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Public singleton factory
# ---------------------------------------------------------------------------


def get_integration_runner(db_path: str = _DEFAULT_DB_PATH) -> IntegrationRunner:
    """Return the global IntegrationRunner singleton.

    Args:
        db_path: SQLite file path (used only on first call).

    Returns:
        The global IntegrationRunner singleton.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = IntegrationRunner(db_path=db_path)
    return _instance


# ---------------------------------------------------------------------------
# Pre-built integration tests
# ---------------------------------------------------------------------------
# These are registered at module import time.  Each is skipped automatically
# when its required service is unavailable (skip_unavailable=True default).


@integration_test("lmstudio_ping", services=["lmstudio"], timeout=10, tags=["smoke", "lmstudio"])
def _test_lmstudio_reachable() -> None:
    """Verify that the LMStudio API is reachable."""
    import requests

    resp = requests.get(
        "http://localhost:1234/api/v1/models",
        timeout=5,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"


@integration_test("nexus_roundtrip", services=["nexus"], timeout=15, tags=["smoke", "nexus"])
def _test_nexus_write_read() -> None:
    """Write an entry to Nexus and verify it can be read back."""
    from engine.nexus.client import get_nexus_client

    client = get_nexus_client()
    entry_id = client.add_entry(
        "Integration Test",
        "test content from integration runner",
        content_type="note",
    )
    try:
        results = client.search("Integration Test")
        assert any(
            "Integration Test" in r.get("title", "") for r in results
        ), "Could not find written entry in search results"
    finally:
        if entry_id:
            client.delete_entry(entry_id)


@integration_test("mcp_skill_execute", services=["mcp"], timeout=10, tags=["smoke", "mcp"])
def _test_mcp_skill_runs() -> None:
    """Verify the skill registry has more than 100 registered skills."""
    from engine.skills.registry import SKILL_REGISTRY

    all_tools = SKILL_REGISTRY.all_tools()
    assert len(all_tools) > 100, f"Expected >100 skills, got {len(all_tools)}"


@integration_test("rate_limiter_acquire", services=[], timeout=5, tags=["smoke", "security"])
def _test_rate_limiter_works() -> None:
    """Verify the rate limiter allows a token acquisition."""
    from engine.security.rate_limiter import get_rate_limiter

    rl = get_rate_limiter()
    result = rl.try_acquire("nexus", tokens=1)
    assert result.allowed, "Rate limiter denied acquisition unexpectedly"


@integration_test("secret_manager_get", services=[], timeout=5, tags=["smoke", "security"])
def _test_secret_manager_works() -> None:
    """Verify the secret manager can produce a safe report."""
    from engine.security.secret_manager import get_secret_manager

    sm = get_secret_manager()
    report = sm.export_safe_report()
    assert "secrets_count" in report or "total_secrets" in report, (
        f"Safe report missing expected keys: {list(report.keys())}"
    )
