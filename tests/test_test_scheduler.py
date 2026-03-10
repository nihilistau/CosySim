"""Tests for the CosySim automated testing scheduler.

Covers TestScheduler instantiation, report generation, CLI argument
parsing, mocked subprocess execution, and mocked Nexus storage.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from scripts.test_scheduler import (
    SuiteReport,
    RunResult,
    TestScheduler,
    _parse_pytest_output,
    build_parser,
    main,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def scheduler():
    """Return a TestScheduler with deterministic test config."""
    config = {
        "default_suite": "full",
        "scene_ports": [5555, 5556],
        "unit_test_timeout": 60,
        "health_check_timeout": 10,
        "browser_checks": ["console_errors", "network_failures", "dom_health"],
        "store_results_in_nexus": False,
        "schedule_interval_minutes": 0,
    }
    return TestScheduler(config=config)


# ── Instantiation ────────────────────────────────────────────────────

class TestSchedulerInit:
    """TestScheduler instantiation and basic attributes."""

    def test_creates_with_explicit_config(self, scheduler):
        """Scheduler uses provided config dict."""
        assert scheduler.config["default_suite"] == "full"
        assert scheduler.config["scene_ports"] == [5555, 5556]

    def test_creates_with_default_config(self):
        """Scheduler falls back to _load_testing_config when no config given."""
        with patch("scripts.test_scheduler._load_testing_config") as mock_load:
            mock_load.return_value = {"default_suite": "unit", "scene_ports": []}
            sched = TestScheduler()
            assert sched.config["default_suite"] == "unit"
            mock_load.assert_called_once()

    def test_initial_state(self, scheduler):
        """Freshly created scheduler has no history and is not running."""
        assert scheduler.get_last_report() is None
        assert scheduler.is_running is False
        assert scheduler.list_runs() == []


# ── Pytest Output Parsing ────────────────────────────────────────────

class TestPytestParsing:
    """Parse pytest output for pass/fail counts and test names."""

    def test_parses_passing_summary(self):
        output = "===== 42 passed in 5.12s ====="
        info = _parse_pytest_output(output)
        assert info["passed"] == 42

    def test_parses_mixed_summary(self):
        output = "===== 10 passed, 3 failed, 1 error in 12.34s ====="
        info = _parse_pytest_output(output)
        assert info["passed"] == 10
        assert info["failed"] == 3
        assert info["error"] == 1

    def test_extracts_failed_test_names(self):
        output = (
            "FAILED tests/test_foo.py::test_bar\n"
            "FAILED tests/test_baz.py::test_qux\n"
            "===== 1 passed, 2 failed in 0.5s ====="
        )
        info = _parse_pytest_output(output)
        assert "tests/test_foo.py::test_bar" in info["failed_tests"]
        assert "tests/test_baz.py::test_qux" in info["failed_tests"]

    def test_handles_empty_output(self):
        info = _parse_pytest_output("")
        assert info.get("failed_tests") == []


# ── Unit Test Runner ─────────────────────────────────────────────────

class TestRunUnitTests:
    """Unit test runner via subprocess."""

    def test_passing_run(self, scheduler):
        """Successful pytest returns passed=True with extracted counts."""
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="===== 20 passed in 3.00s =====\n",
            stderr="",
        )
        with patch("scripts.test_scheduler.subprocess.run", return_value=mock_result):
            result = scheduler.run_unit_tests()

        assert result.category == "unit"
        assert result.passed is True
        assert result.duration_seconds >= 0
        assert result.details.get("passed") == 20

    def test_failing_run(self, scheduler):
        """Failed pytest returns passed=False with failure list."""
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout=(
                "FAILED tests/test_x.py::test_y\n"
                "===== 1 passed, 1 failed in 1.00s ====="
            ),
            stderr="",
        )
        with patch("scripts.test_scheduler.subprocess.run", return_value=mock_result):
            result = scheduler.run_unit_tests()

        assert result.passed is False
        assert "tests/test_x.py::test_y" in result.failures

    def test_timeout_handling(self, scheduler):
        """Timeout produces an error result, not an exception."""
        with patch(
            "scripts.test_scheduler.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=60),
        ):
            result = scheduler.run_unit_tests()

        assert result.passed is False
        assert "timed out" in result.error


# ── Scene Health Runner ──────────────────────────────────────────────

class TestRunSceneHealth:
    """Scene health checker integration."""

    def _fake_scene_result(self, port, ok=True):
        """Build a minimal mock SceneResult."""
        mock = MagicMock()
        mock.port = port
        mock.name = f"scene_{port}"
        mock.ok = ok
        mock.reachable = True
        mock.health_ok = ok
        mock.missing_routes = [] if ok else ["/api/health"]
        mock.shared_404s = []
        mock.console_errors = [] if ok else ["SomeError"]
        mock.known_bugs = []
        return mock

    def test_all_healthy(self, scheduler):
        """All scenes healthy → passed=True."""
        scenes = [self._fake_scene_result(5555), self._fake_scene_result(5556)]
        with patch("scripts.scene_health_check.check_scenes", return_value=scenes):
            result = scheduler.run_scene_health()

        assert result.category == "health"
        assert result.passed is True
        assert result.details["scenes_healthy"] == 2

    def test_one_unhealthy(self, scheduler):
        """One failing scene → passed=False with failure detail."""
        scenes = [
            self._fake_scene_result(5555, ok=True),
            self._fake_scene_result(5556, ok=False),
        ]
        with patch("scripts.scene_health_check.check_scenes", return_value=scenes):
            result = scheduler.run_scene_health()

        assert result.passed is False
        assert result.details["scenes_unhealthy"] == 1
        assert any("5556" in f for f in result.failures)

    def test_single_port(self, scheduler):
        """Passing a specific port checks only that port."""
        scenes = [self._fake_scene_result(5556)]
        with patch("scripts.scene_health_check.check_scenes", return_value=scenes) as mock_cs:
            scheduler.run_scene_health(port=5556)
            call_kwargs = mock_cs.call_args
            assert call_kwargs[1].get("ports") == [5556] or call_kwargs[0][0] == [5556]


# ── Report Generation ───────────────────────────────────────────────

class TestGenerateReport:
    """Structured report generation from run results."""

    def test_all_passed(self, scheduler):
        """Report reflects all-passing results."""
        results = [
            RunResult("unit", True, 1.5, details={"passed": 5}),
            RunResult("health", True, 0.8),
        ]
        report = scheduler.generate_report(results)

        assert report.overall_passed is True
        assert report.total_passed == 2
        assert report.total_failed == 0
        assert report.total_errors == 0
        assert report.total_duration_seconds == pytest.approx(2.3, abs=0.01)
        assert len(report.results) == 2

    def test_mixed_results(self, scheduler):
        """Report correctly tallies mixed pass/fail/error outcomes."""
        results = [
            RunResult("unit", True, 2.0),
            RunResult("health", False, 1.0, failures=["scene_5555"]),
            RunResult("browser", False, 0.5, error="CDP connection failed"),
        ]
        report = scheduler.generate_report(results)

        assert report.overall_passed is False
        assert report.total_passed == 1
        assert report.total_failed == 1
        assert report.total_errors == 1

    def test_report_serialisable(self, scheduler):
        """Report can round-trip through JSON."""
        results = [RunResult("unit", True, 1.0)]
        report = scheduler.generate_report(results)
        report.run_id = "test123"
        report.suite = "unit"
        data = json.loads(json.dumps(asdict(report), default=str))
        assert data["run_id"] == "test123"
        assert data["overall_passed"] is True

    def test_empty_results(self, scheduler):
        """Report for zero results is valid and passes."""
        report = scheduler.generate_report([])
        assert report.overall_passed is True
        assert report.total_passed == 0


# ── Nexus Storage ────────────────────────────────────────────────────

class TestStoreInNexus:
    """Nexus bridge storage via subprocess."""

    def test_successful_store(self, scheduler):
        """Successful bridge call returns True."""
        report = SuiteReport(
            run_id="abc",
            timestamp="2025-01-01T00:00:00Z",
            suite="unit",
            overall_passed=True,
        )
        mock_proc = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"status":"stored"}', stderr="",
        )
        with patch("scripts.test_scheduler.subprocess.run", return_value=mock_proc):
            assert scheduler.store_in_nexus(report) is True

    def test_failed_store(self, scheduler):
        """Non-zero return code from bridge returns False."""
        report = SuiteReport(
            run_id="abc",
            timestamp="2025-01-01T00:00:00Z",
            suite="unit",
            overall_passed=False,
        )
        mock_proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Connection refused",
        )
        with patch("scripts.test_scheduler.subprocess.run", return_value=mock_proc):
            assert scheduler.store_in_nexus(report) is False

    def test_exception_during_store(self, scheduler):
        """Exception during subprocess call returns False gracefully."""
        report = SuiteReport(
            run_id="abc",
            timestamp="2025-01-01T00:00:00Z",
            suite="unit",
            overall_passed=True,
        )
        with patch(
            "scripts.test_scheduler.subprocess.run",
            side_effect=OSError("No such file"),
        ):
            assert scheduler.store_in_nexus(report) is False


# ── History & Status ─────────────────────────────────────────────────

class TestHistoryAndStatus:
    """Run history tracking and status queries."""

    def test_run_suite_records_history(self, scheduler):
        """Running a suite appends to history."""
        mock_proc = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="===== 5 passed in 1.0s =====\n",
            stderr="",
        )
        with patch("scripts.test_scheduler.subprocess.run", return_value=mock_proc):
            scheduler.run_suite("unit")

        assert len(scheduler.list_runs()) == 1
        assert scheduler.get_last_report() is not None
        assert scheduler.get_last_report().suite == "unit"

    def test_get_report_by_id(self, scheduler):
        """Reports are retrievable by run_id."""
        mock_proc = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="===== 1 passed in 0.1s =====\n",
            stderr="",
        )
        with patch("scripts.test_scheduler.subprocess.run", return_value=mock_proc):
            report = scheduler.run_suite("unit")

        found = scheduler.get_report_by_id(report.run_id)
        assert found is not None
        assert found.run_id == report.run_id

    def test_missing_report_returns_none(self, scheduler):
        """Unknown run_id returns None."""
        assert scheduler.get_report_by_id("nonexistent") is None


# ── Scheduling ───────────────────────────────────────────────────────

class TestScheduling:
    """Recurring schedule setup and teardown."""

    def test_schedule_creates_timer(self, scheduler):
        """schedule_run starts a daemon timer."""
        scheduler.schedule_run(5)
        assert scheduler._running is True
        assert scheduler._timer is not None
        assert scheduler._timer.daemon is True
        scheduler.stop_schedule()

    def test_stop_cancels_timer(self, scheduler):
        """stop_schedule cancels the timer and clears running flag."""
        scheduler.schedule_run(10)
        scheduler.stop_schedule()
        assert scheduler._running is False
        assert scheduler._timer is None

    def test_invalid_interval_rejected(self, scheduler):
        """Zero or negative interval is rejected without starting."""
        scheduler.schedule_run(0)
        assert scheduler._running is False
        scheduler.schedule_run(-5)
        assert scheduler._running is False


# ── CLI Argument Parsing ─────────────────────────────────────────────

class TestCLIParsing:
    """argparse configuration for the CLI entry point."""

    def test_run_now_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--run-now"])
        assert args.run_now is True

    def test_schedule_value(self):
        parser = build_parser()
        args = parser.parse_args(["--schedule", "30"])
        assert args.schedule == 30

    def test_suite_choices(self):
        parser = build_parser()
        for suite in ("unit", "health", "browser", "full"):
            args = parser.parse_args(["--suite", suite])
            assert args.suite == suite

    def test_port_option(self):
        parser = build_parser()
        args = parser.parse_args(["--port", "5556"])
        assert args.port == 5556

    def test_store_nexus_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--store-nexus"])
        assert args.store_nexus is True

    def test_json_output_path(self):
        parser = build_parser()
        args = parser.parse_args(["--json-output", "out.json"])
        assert args.json_output == "out.json"

    def test_defaults(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.run_now is False
        assert args.schedule == 0
        assert args.suite is None
        assert args.port is None
        assert args.store_nexus is False
        assert args.json_output is None


# ── CLI main() Integration ───────────────────────────────────────────

class TestCLIMain:
    """End-to-end CLI main() calls."""

    def test_run_now_unit_returns_zero_on_pass(self):
        """--run-now --suite unit returns 0 when tests pass."""
        mock_proc = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="===== 5 passed in 1.0s =====\n",
            stderr="",
        )
        with patch("scripts.test_scheduler.subprocess.run", return_value=mock_proc), \
             patch("scripts.test_scheduler._load_testing_config", return_value={
                 "default_suite": "full",
                 "scene_ports": [],
                 "unit_test_timeout": 60,
                 "health_check_timeout": 10,
                 "browser_checks": [],
                 "store_results_in_nexus": False,
                 "schedule_interval_minutes": 0,
             }):
            code = main(["--run-now", "--suite", "unit"])

        assert code == 0

    def test_run_now_returns_one_on_fail(self):
        """--run-now returns 1 when tests fail."""
        mock_proc = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="FAILED tests/test_x.py::test_y\n===== 1 failed in 0.5s =====",
            stderr="",
        )
        with patch("scripts.test_scheduler.subprocess.run", return_value=mock_proc), \
             patch("scripts.test_scheduler._load_testing_config", return_value={
                 "default_suite": "full",
                 "scene_ports": [],
                 "unit_test_timeout": 60,
                 "health_check_timeout": 10,
                 "browser_checks": [],
                 "store_results_in_nexus": False,
                 "schedule_interval_minutes": 0,
             }):
            code = main(["--run-now", "--suite", "unit"])

        assert code == 1

    def test_json_output_writes_file(self, tmp_path):
        """--json-output writes a valid JSON report."""
        out = tmp_path / "report.json"
        mock_proc = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="===== 3 passed in 0.8s =====\n",
            stderr="",
        )
        with patch("scripts.test_scheduler.subprocess.run", return_value=mock_proc), \
             patch("scripts.test_scheduler._load_testing_config", return_value={
                 "default_suite": "full",
                 "scene_ports": [],
                 "unit_test_timeout": 60,
                 "health_check_timeout": 10,
                 "browser_checks": [],
                 "store_results_in_nexus": False,
                 "schedule_interval_minutes": 0,
             }):
            main(["--run-now", "--suite", "unit", "--json-output", str(out)])

        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["overall_passed"] is True

    def test_no_args_prints_help(self, capsys):
        """No arguments prints help and returns 0."""
        with patch("scripts.test_scheduler._load_testing_config", return_value={
            "default_suite": "full",
            "scene_ports": [],
            "unit_test_timeout": 60,
            "health_check_timeout": 10,
            "browser_checks": [],
            "store_results_in_nexus": False,
            "schedule_interval_minutes": 0,
        }):
            code = main([])
        assert code == 0
        captured = capsys.readouterr()
        assert "test_scheduler" in captured.out or "usage" in captured.out.lower()
