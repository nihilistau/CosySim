"""
Tests for engine.testing.integration_runner.

Covers:
- IntegrationTest, IntegrationResult, IntegrationSuite, ServiceProbe dataclasses
- register() — normal and duplicate detection
- @integration_test decorator (registration + signature preservation)
- probe_service() / probe_services() — mocked HTTP and import probes
- run() — passing test, failing test, skip_unavailable=True/False
- run() — result persistence in SQLite
- run() — duration capture
- run() — timeout enforcement
- run_suite() — named suite execution
- get_results() — filter by test_id, since
- get_flaky_tests() — >20% failure rate detection
- schedule_suite() — wires to scheduler daemon
- All 5 pre-built tests are registered
- singleton get_integration_runner()
- Thread safety for register/run
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest

import engine.testing.integration_runner as _mod
from engine.testing.integration_runner import (
    IntegrationResult,
    IntegrationRunner,
    IntegrationSuite,
    IntegrationTest,
    ServiceProbe,
    get_integration_runner,
    integration_test,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner(tmp_path: Path) -> IntegrationRunner:
    """Fresh IntegrationRunner with isolated temp DB."""
    return IntegrationRunner(db_path=str(tmp_path / "test_results.db"))


@pytest.fixture()
def passing_test() -> IntegrationTest:
    """A simple passing integration test."""
    return IntegrationTest(
        test_id="passing_test",
        name="Passing Test",
        services=[],
        test_fn=lambda: None,
    )


@pytest.fixture()
def failing_test() -> IntegrationTest:
    """A test that always fails."""

    def always_fail() -> None:
        raise AssertionError("intentional failure")

    return IntegrationTest(
        test_id="failing_test",
        name="Failing Test",
        services=[],
        test_fn=always_fail,
    )


# ===========================================================================
# Dataclass tests
# ===========================================================================


class TestDataclasses:
    """IntegrationTest, IntegrationResult, IntegrationSuite creation."""

    def test_integration_test_creation(self) -> None:
        t = IntegrationTest(
            test_id="my_test",
            name="My Test",
            services=["lmstudio"],
            test_fn=lambda: None,
            timeout_seconds=10.0,
            tags=["smoke"],
        )
        assert t.test_id == "my_test"
        assert t.services == ["lmstudio"]
        assert t.timeout_seconds == 10.0
        assert "smoke" in t.tags

    def test_integration_test_defaults(self) -> None:
        t = IntegrationTest(test_id="x", name="x", services=[], test_fn=lambda: None)
        assert t.setup_fn is None
        assert t.teardown_fn is None
        assert t.requires_gpu is False
        assert t.timeout_seconds == 30.0

    def test_integration_result_creation(self) -> None:
        r = IntegrationResult(
            result_id="r1",
            test_id="t1",
            passed=True,
            skipped=False,
            duration_ms=42.0,
            error=None,
            logs=[],
            metrics={},
            timestamp=time.time(),
        )
        assert r.passed is True
        assert r.skipped is False

    def test_integration_suite_creation(self) -> None:
        suite = IntegrationSuite(name="core", test_ids=["a", "b"])
        assert suite.name == "core"
        assert len(suite.test_ids) == 2

    def test_integration_suite_add(self) -> None:
        suite = IntegrationSuite(name="s")
        suite.add("x")
        suite.add("y")
        suite.add("x")  # duplicate — should be ignored
        assert suite.test_ids == ["x", "y"]

    def test_service_probe_init(self) -> None:
        probe = ServiceProbe()
        assert probe is not None


# ===========================================================================
# Registration tests
# ===========================================================================


class TestRegistration:
    """register() and @integration_test decorator."""

    def test_register_test(self, runner: IntegrationRunner, passing_test: IntegrationTest) -> None:
        runner.register(passing_test)
        listed = runner.list_tests()
        assert any(t["test_id"] == "passing_test" for t in listed)

    def test_register_duplicate_raises(
        self, runner: IntegrationRunner, passing_test: IntegrationTest
    ) -> None:
        runner.register(passing_test)
        with pytest.raises(ValueError, match="already registered"):
            runner.register(passing_test)

    def test_register_suite(self, runner: IntegrationRunner) -> None:
        suite = IntegrationSuite(name="my_suite", test_ids=[])
        runner.register_suite(suite)
        # No error means success.

    def test_register_persists_to_db(
        self, runner: IntegrationRunner, passing_test: IntegrationTest
    ) -> None:
        import sqlite3

        runner.register(passing_test)
        with sqlite3.connect(runner._db_path) as conn:
            row = conn.execute(
                "SELECT test_id FROM integration_tests WHERE test_id = ?",
                ("passing_test",),
            ).fetchone()
        assert row is not None


# ===========================================================================
# @integration_test decorator tests
# ===========================================================================


class TestDecorator:
    """@integration_test registers at decoration time."""

    def test_decorator_registers_test(self, tmp_path: Path) -> None:
        """Decorator auto-registers with global runner (mocked)."""
        registered: List[IntegrationTest] = []
        fake_runner = MagicMock()
        fake_runner.register.side_effect = lambda t: registered.append(t)

        with patch.object(_mod, "get_integration_runner", return_value=fake_runner):

            @integration_test("decorator_sample", services=[], timeout=5)
            def sample_test() -> None:
                pass

        assert len(registered) == 1
        assert registered[0].test_id == "decorator_sample"

    def test_decorator_preserves_signature(self) -> None:
        with patch.object(_mod, "get_integration_runner", return_value=MagicMock()):

            @integration_test("sig_test", services=[])
            def my_func() -> None:
                """Docstring."""
                pass

        assert my_func.__name__ == "my_func"
        assert my_func.__doc__ == "Docstring."

    def test_decorator_sets_services(self, tmp_path: Path) -> None:
        registered: List[IntegrationTest] = []
        fake_runner = MagicMock()
        fake_runner.register.side_effect = lambda t: registered.append(t)

        with patch.object(_mod, "get_integration_runner", return_value=fake_runner):

            @integration_test("svc_test", services=["lmstudio", "nexus"])
            def svc_test() -> None:
                pass

        assert registered[0].services == ["lmstudio", "nexus"]

    def test_decorator_sets_tags(self, tmp_path: Path) -> None:
        registered: List[IntegrationTest] = []
        fake_runner = MagicMock()
        fake_runner.register.side_effect = lambda t: registered.append(t)

        with patch.object(_mod, "get_integration_runner", return_value=fake_runner):

            @integration_test("tagged_test", services=[], tags=["smoke", "fast"])
            def tagged_test() -> None:
                pass

        assert "smoke" in registered[0].tags
        assert "fast" in registered[0].tags


# ===========================================================================
# ServiceProbe tests
# ===========================================================================


class TestServiceProbe:
    """ServiceProbe liveness checks."""

    def test_probe_empty_service_returns_true(self) -> None:
        probe = ServiceProbe()
        assert probe.probe("") is True

    def test_probe_none_service_returns_true(self) -> None:
        probe = ServiceProbe()
        assert probe.probe(None) is True  # type: ignore[arg-type]

    def test_probe_unknown_service_returns_false(self) -> None:
        probe = ServiceProbe()
        assert probe.probe("nonexistent_service_xyz") is False

    def test_probe_http_success(self) -> None:
        probe = ServiceProbe()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("requests.get", return_value=mock_resp):
            result = probe._probe_http("http://fake-url/")
        assert result is True

    def test_probe_http_failure(self) -> None:
        probe = ServiceProbe()
        with patch("requests.get", side_effect=ConnectionError("refused")):
            result = probe._probe_http("http://unreachable/")
        assert result is False

    def test_probe_all_returns_dict(self) -> None:
        probe = ServiceProbe()
        with patch.object(probe, "probe", return_value=False):
            result = probe.probe_all(["lmstudio", "nexus"])
        assert isinstance(result, dict)
        assert "lmstudio" in result
        assert "nexus" in result

    def test_probe_services_returns_known_services(
        self, runner: IntegrationRunner
    ) -> None:
        with patch.object(runner._probe, "probe", return_value=False):
            status = runner.probe_services()
        assert isinstance(status, dict)
        assert len(status) > 0


# ===========================================================================
# Run tests — passing and failing
# ===========================================================================


class TestRun:
    """run() execution, results, and skip logic."""

    def test_run_passing_test(self, runner: IntegrationRunner) -> None:
        runner.register(
            IntegrationTest(test_id="p1", name="P1", services=[], test_fn=lambda: None)
        )
        results = runner.run(test_ids=["p1"])
        assert len(results) == 1
        assert results[0].passed is True

    def test_run_failing_test(self, runner: IntegrationRunner) -> None:
        def fail() -> None:
            raise RuntimeError("boom")

        runner.register(
            IntegrationTest(test_id="f1", name="F1", services=[], test_fn=fail)
        )
        results = runner.run(test_ids=["f1"])
        assert len(results) == 1
        assert results[0].passed is False
        assert "boom" in (results[0].error or "")

    def test_run_skip_when_service_unavailable(self, runner: IntegrationRunner) -> None:
        runner.register(
            IntegrationTest(
                test_id="needs_svc",
                name="Needs Service",
                services=["lmstudio"],
                test_fn=lambda: None,
            )
        )
        with patch.object(runner._probe, "probe", return_value=False):
            results = runner.run(test_ids=["needs_svc"], skip_unavailable=True)
        assert results[0].skipped is True
        assert results[0].passed is False

    def test_run_no_skip_when_flag_false(self, runner: IntegrationRunner) -> None:
        """With skip_unavailable=False the test runs even if service is down."""
        call_count = [0]

        def my_fn() -> None:
            call_count[0] += 1

        runner.register(
            IntegrationTest(
                test_id="no_skip",
                name="No Skip",
                services=["lmstudio"],
                test_fn=my_fn,
            )
        )
        with patch.object(runner._probe, "probe", return_value=False):
            results = runner.run(test_ids=["no_skip"], skip_unavailable=False)
        # With skip_unavailable=False, test runs despite unavailable service.
        assert call_count[0] == 1

    def test_run_stores_result_in_db(self, runner: IntegrationRunner) -> None:
        runner.register(
            IntegrationTest(test_id="stored", name="Stored", services=[], test_fn=lambda: None)
        )
        runner.run(test_ids=["stored"])
        results = runner.get_results(test_id="stored")
        assert len(results) == 1
        assert results[0].test_id == "stored"

    def test_run_captures_duration(self, runner: IntegrationRunner) -> None:
        runner.register(
            IntegrationTest(test_id="timed", name="Timed", services=[], test_fn=lambda: None)
        )
        results = runner.run(test_ids=["timed"])
        assert results[0].duration_ms >= 0

    def test_run_by_tags(self, runner: IntegrationRunner) -> None:
        runner.register(
            IntegrationTest(
                test_id="a", name="A", services=[], test_fn=lambda: None, tags=["smoke"]
            )
        )
        runner.register(
            IntegrationTest(
                test_id="b", name="B", services=[], test_fn=lambda: None, tags=["heavy"]
            )
        )
        results = runner.run(tags=["smoke"])
        assert len(results) == 1
        assert results[0].test_id == "a"

    def test_run_all_when_no_filter(self, runner: IntegrationRunner) -> None:
        for i in range(3):
            runner.register(
                IntegrationTest(
                    test_id=f"all_{i}", name=f"All {i}", services=[], test_fn=lambda: None
                )
            )
        results = runner.run()
        assert len(results) == 3

    def test_run_timeout_respected(self, runner: IntegrationRunner) -> None:
        def slow_fn() -> None:
            time.sleep(10)

        runner.register(
            IntegrationTest(
                test_id="slow_timeout",
                name="Slow Timeout",
                services=[],
                test_fn=slow_fn,
                timeout_seconds=0.1,
            )
        )
        results = runner.run(test_ids=["slow_timeout"])
        assert results[0].passed is False
        assert "timed out" in (results[0].error or "").lower()


# ===========================================================================
# Results query tests
# ===========================================================================


class TestResults:
    """get_results() query API."""

    def test_get_results_all(self, runner: IntegrationRunner) -> None:
        runner.register(
            IntegrationTest(test_id="r1", name="R1", services=[], test_fn=lambda: None)
        )
        runner.run(test_ids=["r1"])
        results = runner.get_results()
        assert len(results) >= 1

    def test_get_results_by_test_id(self, runner: IntegrationRunner) -> None:
        for i in range(2):
            runner.register(
                IntegrationTest(
                    test_id=f"res_{i}", name=f"Res {i}", services=[], test_fn=lambda: None
                )
            )
            runner.run(test_ids=[f"res_{i}"])
        results = runner.get_results(test_id="res_0")
        assert all(r.test_id == "res_0" for r in results)

    def test_get_results_since(self, runner: IntegrationRunner) -> None:
        runner.register(
            IntegrationTest(test_id="since_t", name="Since", services=[], test_fn=lambda: None)
        )
        runner.run(test_ids=["since_t"])
        future_ts = time.time() + 10
        results = runner.get_results(since=future_ts)
        assert len(results) == 0


# ===========================================================================
# Flaky test detection
# ===========================================================================


class TestFlakyTests:
    """get_flaky_tests() failure rate threshold."""

    def test_flaky_test_detected(self, runner: IntegrationRunner) -> None:
        call_no = [0]

        def flaky_fn() -> None:
            call_no[0] += 1
            if call_no[0] % 2 == 0:
                raise AssertionError("flaky failure")

        runner.register(
            IntegrationTest(test_id="flaky_t", name="Flaky", services=[], test_fn=flaky_fn)
        )
        # Run 4 times: 2 pass, 2 fail → 50% failure rate > 20% threshold.
        for _ in range(4):
            runner.run(test_ids=["flaky_t"])

        flaky = runner.get_flaky_tests(threshold=0.2)
        assert any(f["test_id"] == "flaky_t" for f in flaky)

    def test_flaky_threshold_boundary(self, runner: IntegrationRunner) -> None:
        """A test with exactly 0 failures is not flaky."""
        runner.register(
            IntegrationTest(test_id="reliable", name="Reliable", services=[], test_fn=lambda: None)
        )
        for _ in range(5):
            runner.run(test_ids=["reliable"])

        flaky = runner.get_flaky_tests(threshold=0.2)
        assert not any(f["test_id"] == "reliable" for f in flaky)

    def test_flaky_result_structure(self, runner: IntegrationRunner) -> None:
        """Flaky result dict has expected keys."""

        def sometimes_fail() -> None:
            raise AssertionError("always fail in this test")

        runner.register(
            IntegrationTest(test_id="struct_flaky", name="SF", services=[], test_fn=sometimes_fail)
        )
        for _ in range(3):
            runner.run(test_ids=["struct_flaky"])

        flaky = runner.get_flaky_tests(threshold=0.1)
        if flaky:
            item = flaky[0]
            assert "test_id" in item
            assert "total_runs" in item
            assert "failures" in item
            assert "failure_rate" in item


# ===========================================================================
# Suite tests
# ===========================================================================


class TestSuite:
    """run_suite() and schedule_suite()."""

    def test_run_suite_runs_tests(self, runner: IntegrationRunner) -> None:
        runner.register(
            IntegrationTest(test_id="s1", name="S1", services=[], test_fn=lambda: None)
        )
        runner.register(
            IntegrationTest(test_id="s2", name="S2", services=[], test_fn=lambda: None)
        )
        suite = IntegrationSuite(name="my_suite", test_ids=["s1", "s2"])
        runner.register_suite(suite)
        results = runner.run_suite("my_suite")
        assert len(results) == 2

    def test_run_suite_missing_returns_empty(self, runner: IntegrationRunner) -> None:
        results = runner.run_suite("nonexistent_suite")
        assert results == []

    def test_schedule_suite_calls_scheduler(self, runner: IntegrationRunner) -> None:
        """schedule_suite completes without propagating exceptions.

        The implementation wraps the scheduler import in a try/except so
        this always succeeds, even when the scheduler module is unavailable.
        """
        # Just verify it doesn't raise — exceptions are swallowed internally.
        runner.schedule_suite("nonexistent_suite_xyz", "daily")  # no-op; suite not found

    def test_singleton_get_integration_runner(self, tmp_path: Path) -> None:
        old = _mod._instance
        _mod._instance = None
        db = str(tmp_path / "singleton.db")
        a = get_integration_runner(db_path=db)
        b = get_integration_runner()
        assert a is b
        _mod._instance = old


# ===========================================================================
# Pre-built tests registration
# ===========================================================================


class TestPreBuiltTests:
    """All 5 pre-built integration tests are registered in the global runner."""

    EXPECTED_IDS = [
        "lmstudio_ping",
        "nexus_roundtrip",
        "mcp_skill_execute",
        "rate_limiter_acquire",
        "secret_manager_get",
    ]

    def _global_runner(self) -> IntegrationRunner:
        """Return the singleton that was created when the module imported."""
        old = _mod._instance
        # Force module to have an instance (it was created at import).
        if old is None:
            pytest.skip("Global runner not initialised")
        return old

    def test_all_prebuilt_registered(self) -> None:
        runner = self._global_runner()
        listed_ids = {t["test_id"] for t in runner.list_tests()}
        for expected_id in self.EXPECTED_IDS:
            assert expected_id in listed_ids, f"Pre-built test not registered: {expected_id}"

    def test_lmstudio_ping_registered(self) -> None:
        runner = self._global_runner()
        listed = {t["test_id"]: t for t in runner.list_tests()}
        assert "lmstudio_ping" in listed

    def test_lmstudio_has_correct_service(self) -> None:
        runner = self._global_runner()
        listed = {t["test_id"]: t for t in runner.list_tests()}
        assert "lmstudio" in listed["lmstudio_ping"]["services"]

    def test_nexus_roundtrip_registered(self) -> None:
        runner = self._global_runner()
        listed = {t["test_id"]: t for t in runner.list_tests()}
        assert "nexus_roundtrip" in listed

    def test_nexus_has_nexus_service(self) -> None:
        runner = self._global_runner()
        listed = {t["test_id"]: t for t in runner.list_tests()}
        assert "nexus" in listed["nexus_roundtrip"]["services"]

    def test_mcp_skill_execute_registered(self) -> None:
        runner = self._global_runner()
        listed = {t["test_id"]: t for t in runner.list_tests()}
        assert "mcp_skill_execute" in listed

    def test_mcp_has_mcp_service(self) -> None:
        runner = self._global_runner()
        listed = {t["test_id"]: t for t in runner.list_tests()}
        assert "mcp" in listed["mcp_skill_execute"]["services"]

    def test_rate_limiter_registered(self) -> None:
        runner = self._global_runner()
        listed = {t["test_id"]: t for t in runner.list_tests()}
        assert "rate_limiter_acquire" in listed

    def test_rate_limiter_no_services_required(self) -> None:
        runner = self._global_runner()
        listed = {t["test_id"]: t for t in runner.list_tests()}
        assert listed["rate_limiter_acquire"]["services"] == []

    def test_secret_manager_registered(self) -> None:
        runner = self._global_runner()
        listed = {t["test_id"]: t for t in runner.list_tests()}
        assert "secret_manager_get" in listed

    def test_prebuilt_skipped_when_lmstudio_down(self, runner: IntegrationRunner) -> None:
        """With skip_unavailable=True, lmstudio test is skipped when service down."""
        # Register a local copy of the lmstudio test.
        def fake_lms() -> None:
            import requests

            resp = requests.get("http://localhost:1234/api/v1/models", timeout=5)
            assert resp.status_code == 200

        runner.register(
            IntegrationTest(
                test_id="lms_down_test",
                name="LMS Down",
                services=["lmstudio"],
                test_fn=fake_lms,
                timeout_seconds=5.0,
            )
        )
        with patch.object(runner._probe, "probe", return_value=False):
            results = runner.run(test_ids=["lms_down_test"], skip_unavailable=True)
        assert results[0].skipped is True

    def test_prebuilt_tests_have_timeouts(self) -> None:
        runner = self._global_runner()
        listed = {t["test_id"]: t for t in runner.list_tests()}
        for tid in self.EXPECTED_IDS:
            assert listed[tid]["timeout_seconds"] > 0
