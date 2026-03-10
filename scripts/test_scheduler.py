"""CosySim Automated Testing Scheduler.

Runs pytest suites, scene health checks, and CDP browser tests on schedule
or on demand.  Generates structured reports and stores results in Nexus.

Usage::

    # Run full test suite now
    python scripts/test_scheduler.py --run-now

    # Run only unit tests
    python scripts/test_scheduler.py --run-now --suite unit

    # Schedule recurring runs every 30 minutes
    python scripts/test_scheduler.py --schedule 30

    # Browser-test a running scene on port 5556
    python scripts/test_scheduler.py --run-now --suite browser --port 5556

    # Output report as JSON file
    python scripts/test_scheduler.py --run-now --json-output report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PYTEST_ARGS = [
    sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short",
    "--ignore=tests/test_agent_loop.py",
    "--ignore=tests/live_wire_test.py",
]
NEXUS_BRIDGE = [sys.executable, "-m", "engine.nexus.bridge"]


# ── Data Classes ─────────────────────────────────────────────────────

@dataclass
class RunResult:
    """Result of a single test category run."""
    category: str
    passed: bool
    duration_seconds: float
    details: Dict[str, Any] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class SuiteReport:
    """Aggregate report for a full scheduler run."""
    run_id: str
    timestamp: str
    suite: str
    total_passed: int = 0
    total_failed: int = 0
    total_errors: int = 0
    total_duration_seconds: float = 0.0
    results: List[Dict[str, Any]] = field(default_factory=list)
    overall_passed: bool = False


# ── Helpers ──────────────────────────────────────────────────────────

def _parse_pytest_output(output: str) -> Dict[str, Any]:
    """Extract pass/fail counts from pytest output text."""
    info: Dict[str, Any] = {"raw_tail": output[-2000:] if len(output) > 2000 else output}

    # Match summary line like "5 passed, 2 failed, 1 error in 3.42s"
    summary_match = re.search(
        r"=+\s*(.*?)\s*=+\s*$", output, re.MULTILINE,
    )
    if summary_match:
        summary = summary_match.group(1)
        info["summary_line"] = summary

        for token in ("passed", "failed", "error", "warning", "skipped", "deselected"):
            m = re.search(rf"(\d+)\s+{token}", summary)
            if m:
                info[token] = int(m.group(1))

    # Collect FAILED test names
    failures: List[str] = []
    for m in re.finditer(r"^FAILED\s+(\S+)", output, re.MULTILINE):
        failures.append(m.group(1))
    info["failed_tests"] = failures
    return info


def _load_testing_config() -> Dict[str, Any]:
    """Load the testing section from CosySim config."""
    cfg = get_config()
    return {
        "default_suite": cfg.get("testing.default_suite", "full"),
        "scene_ports": cfg.get("testing.scene_ports", [5555, 5556, 5571, 8500]),
        "unit_test_timeout": cfg.get("testing.unit_test_timeout", 300),
        "health_check_timeout": cfg.get("testing.health_check_timeout", 30),
        "browser_checks": cfg.get(
            "testing.browser_checks",
            ["console_errors", "network_failures", "dom_health"],
        ),
        "store_results_in_nexus": cfg.get("testing.store_results_in_nexus", True),
        "schedule_interval_minutes": cfg.get("testing.schedule_interval_minutes", 0),
    }


# ── TestScheduler ────────────────────────────────────────────────────

class TestScheduler:
    """Automated testing scheduler for CosySim.

    Orchestrates pytest, scene health checks, and CDP browser diagnostics.
    Results are collected into structured reports and optionally stored in
    Nexus for long-term tracking.
    """

    __test__ = False  # prevent pytest collection

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or _load_testing_config()
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._history: List[SuiteReport] = []
        self._current_run: Optional[SuiteReport] = None
        self._lock = threading.Lock()

    # ── Unit Tests ───────────────────────────────────────────────────

    def run_unit_tests(self) -> RunResult:
        """Run the project pytest suite via subprocess.

        Returns:
            RunResult with pass/fail data extracted from pytest output.
        """
        logger.info("Running unit tests …")
        timeout = self.config.get("unit_test_timeout", 300)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                DEFAULT_PYTEST_ARGS,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(PROJECT_ROOT),
            )
            duration = time.monotonic() - start
            info = _parse_pytest_output(proc.stdout + "\n" + proc.stderr)
            passed = proc.returncode == 0
            failures = info.get("failed_tests", [])
            return RunResult(
                category="unit",
                passed=passed,
                duration_seconds=round(duration, 2),
                details=info,
                failures=failures,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return RunResult(
                category="unit",
                passed=False,
                duration_seconds=round(duration, 2),
                error=f"Pytest timed out after {timeout}s",
            )
        except Exception as exc:
            duration = time.monotonic() - start
            return RunResult(
                category="unit",
                passed=False,
                duration_seconds=round(duration, 2),
                error=str(exc),
            )

    # ── Scene Health ─────────────────────────────────────────────────

    def run_scene_health(self, port: Optional[int] = None) -> RunResult:
        """Run scene health checks via scene_health_check.

        Args:
            port: Specific scene port, or ``None`` to check all configured ports.

        Returns:
            RunResult summarising which scenes are healthy.
        """
        from scripts.scene_health_check import check_scenes

        ports = [port] if port else self.config.get("scene_ports", [])
        logger.info("Running scene health checks on ports %s", ports)
        start = time.monotonic()
        try:
            results = asyncio.run(check_scenes(ports=ports))
            duration = time.monotonic() - start
            failures = [
                f"{r.name} (port {r.port}): "
                + ", ".join(r.console_errors[:3] + r.known_bugs[:3] + r.missing_routes)
                for r in results if not r.ok
            ]
            details: Dict[str, Any] = {
                "scenes_checked": len(results),
                "scenes_healthy": sum(1 for r in results if r.ok),
                "scenes_unhealthy": sum(1 for r in results if not r.ok),
                "per_scene": [
                    {
                        "port": r.port,
                        "name": r.name,
                        "ok": r.ok,
                        "reachable": r.reachable,
                        "health_ok": r.health_ok,
                        "missing_routes": r.missing_routes,
                        "shared_404s": r.shared_404s,
                        "console_errors": r.console_errors[:5],
                        "known_bugs": r.known_bugs,
                    }
                    for r in results
                ],
            }
            return RunResult(
                category="health",
                passed=all(r.ok for r in results) if results else True,
                duration_seconds=round(duration, 2),
                details=details,
                failures=failures,
            )
        except Exception as exc:
            duration = time.monotonic() - start
            return RunResult(
                category="health",
                passed=False,
                duration_seconds=round(duration, 2),
                error=str(exc),
            )

    # ── Browser Tests ────────────────────────────────────────────────

    def run_browser_test(
        self,
        port: int,
        checks: Optional[List[str]] = None,
    ) -> RunResult:
        """Run CDP-based browser diagnostics on a running scene.

        Uses ARGUS LiveDebugger to inspect console errors, network failures,
        and DOM health via Chrome DevTools Protocol.

        Args:
            port: The scene port to test.
            checks: List of check names to run.  Defaults to config value.

        Returns:
            RunResult with browser diagnostic details.
        """
        checks = checks or self.config.get(
            "browser_checks",
            ["console_errors", "network_failures", "dom_health"],
        )
        logger.info("Running browser tests on port %d (checks: %s)", port, checks)
        return asyncio.run(self._browser_test_async(port, checks))

    async def _browser_test_async(
        self, port: int, checks: List[str],
    ) -> RunResult:
        """Async implementation of browser testing."""
        from scripts.argus.live_debugger import LiveDebugger

        start = time.monotonic()
        failures: List[str] = []
        details: Dict[str, Any] = {"port": port, "checks_run": checks}

        try:
            async with LiveDebugger(f"localhost:{port}") as dbg:
                # Allow the page to settle and events to accumulate
                await asyncio.sleep(2)

                if "console_errors" in checks:
                    errors = await dbg.get_console_logs(level="error")
                    details["console_errors"] = [str(e) for e in errors[:20]]
                    if errors:
                        failures.append(
                            f"{len(errors)} console error(s) on port {port}"
                        )

                if "network_failures" in checks:
                    net_errors = await dbg.get_network_errors()
                    details["network_failures"] = [str(e) for e in net_errors[:20]]
                    if net_errors:
                        failures.append(
                            f"{len(net_errors)} network error(s) on port {port}"
                        )

                if "dom_health" in checks:
                    dom = await dbg.eval_js(
                        "JSON.stringify({"
                        "  title: document.title,"
                        "  bodyChildren: document.body ? document.body.childElementCount : 0,"
                        "  hasSocketIO: typeof io !== 'undefined',"
                        "  readyState: document.readyState"
                        "})"
                    )
                    try:
                        dom_info = json.loads(dom) if isinstance(dom, str) else dom
                    except (json.JSONDecodeError, TypeError):
                        dom_info = {"raw": str(dom)}
                    details["dom_health"] = dom_info
                    if isinstance(dom_info, dict) and dom_info.get("bodyChildren", 0) == 0:
                        failures.append(f"Empty DOM body on port {port}")

            duration = time.monotonic() - start
            return RunResult(
                category="browser",
                passed=len(failures) == 0,
                duration_seconds=round(duration, 2),
                details=details,
                failures=failures,
            )
        except Exception as exc:
            duration = time.monotonic() - start
            return RunResult(
                category="browser",
                passed=False,
                duration_seconds=round(duration, 2),
                details=details,
                error=str(exc),
            )

    # ── Full Suite ───────────────────────────────────────────────────

    def run_full_suite(self) -> SuiteReport:
        """Run all test categories sequentially and return aggregate report.

        Order: unit tests → scene health → browser tests (per configured port).

        Returns:
            SuiteReport aggregating results from every test category.
        """
        run_id = uuid.uuid4().hex[:12]
        logger.info("Starting full test suite run %s", run_id)
        self._current_run = SuiteReport(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            suite="full",
        )

        all_results: List[RunResult] = []

        # 1. Unit tests
        all_results.append(self.run_unit_tests())

        # 2. Scene health
        all_results.append(self.run_scene_health())

        # 3. Browser tests — one per configured port
        for p in self.config.get("scene_ports", []):
            all_results.append(self.run_browser_test(p))

        report = self.generate_report(all_results)
        report.run_id = run_id
        report.suite = "full"
        with self._lock:
            self._history.append(report)
            self._current_run = None
        return report

    def run_suite(self, suite: str, port: Optional[int] = None) -> SuiteReport:
        """Run a specific test suite and return the report.

        Args:
            suite: One of ``"unit"``, ``"health"``, ``"browser"``, ``"full"``.
            port: Scene port (required for ``"browser"`` and ``"health"``
                  when targeting a single scene).

        Returns:
            SuiteReport for the requested suite.
        """
        if suite == "full":
            return self.run_full_suite()

        run_id = uuid.uuid4().hex[:12]
        results: List[RunResult] = []

        if suite == "unit":
            results.append(self.run_unit_tests())
        elif suite == "health":
            results.append(self.run_scene_health(port))
        elif suite == "browser":
            target_port = port or (self.config.get("scene_ports", [5555])[0])
            results.append(self.run_browser_test(target_port))
        else:
            logger.warning("Unknown suite %r, falling back to unit", suite)
            results.append(self.run_unit_tests())

        report = self.generate_report(results)
        report.run_id = run_id
        report.suite = suite
        with self._lock:
            self._history.append(report)
        return report

    # ── Report Generation ────────────────────────────────────────────

    def generate_report(self, results: List[RunResult]) -> SuiteReport:
        """Generate a structured SuiteReport from a list of run results.

        Args:
            results: Individual test run results to aggregate.

        Returns:
            Aggregated SuiteReport with totals and per-category breakdowns.
        """
        total_passed = sum(1 for r in results if r.passed)
        total_failed = sum(1 for r in results if not r.passed and not r.error)
        total_errors = sum(1 for r in results if r.error)
        total_duration = sum(r.duration_seconds for r in results)

        return SuiteReport(
            run_id="",
            timestamp=datetime.now(timezone.utc).isoformat(),
            suite="",
            total_passed=total_passed,
            total_failed=total_failed,
            total_errors=total_errors,
            total_duration_seconds=round(total_duration, 2),
            results=[asdict(r) for r in results],
            overall_passed=all(r.passed for r in results),
        )

    # ── Nexus Storage ────────────────────────────────────────────────

    def store_in_nexus(self, report: SuiteReport) -> bool:
        """Store a test report in Nexus via the CLI bridge.

        Args:
            report: The report to persist.

        Returns:
            True if the bridge command succeeded.
        """
        title = (
            f"Test Report {report.run_id} — "
            f"{'PASS' if report.overall_passed else 'FAIL'} "
            f"({report.suite})"
        )
        content = json.dumps(asdict(report), indent=2, default=str)
        cmd = [
            *NEXUS_BRIDGE,
            "store",
            title,
            content,
            "--type", "note",
            "--category", "testing",
            "--tags", f"test-run,{report.suite},{'pass' if report.overall_passed else 'fail'}",
        ]
        logger.info("Storing report %s in Nexus", report.run_id)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(PROJECT_ROOT),
            )
            if proc.returncode != 0:
                logger.warning("Nexus store returned %d: %s", proc.returncode, proc.stderr)
                return False
            return True
        except Exception as exc:
            logger.error("Failed to store report in Nexus: %s", exc)
            return False

    # ── Scheduling ───────────────────────────────────────────────────

    def schedule_run(self, interval_minutes: int) -> None:
        """Set up recurring test runs using threading.Timer.

        Args:
            interval_minutes: Minutes between runs.  Must be > 0.
        """
        if interval_minutes <= 0:
            logger.error("Interval must be positive, got %d", interval_minutes)
            return

        self._running = True
        logger.info("Scheduling test runs every %d minutes", interval_minutes)
        self._schedule_next(interval_minutes)

    def _schedule_next(self, interval_minutes: int) -> None:
        """Internal: schedule the next recurring run."""
        if not self._running:
            return
        self._timer = threading.Timer(
            interval_minutes * 60,
            self._scheduled_run,
            args=(interval_minutes,),
        )
        self._timer.daemon = True
        self._timer.start()

    def _scheduled_run(self, interval_minutes: int) -> None:
        """Execute a single scheduled run, then reschedule."""
        logger.info("Scheduled test run triggered")
        try:
            report = self.run_full_suite()
            if self.config.get("store_results_in_nexus", True):
                self.store_in_nexus(report)
            status = "PASS" if report.overall_passed else "FAIL"
            logger.info(
                "Scheduled run %s complete: %s (%d passed, %d failed, %d errors)",
                report.run_id, status,
                report.total_passed, report.total_failed, report.total_errors,
            )
        except Exception as exc:
            logger.error("Scheduled run failed: %s", exc)
        finally:
            self._schedule_next(interval_minutes)

    def stop_schedule(self) -> None:
        """Cancel any pending scheduled run."""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        logger.info("Scheduled runs stopped")

    # ── History Access ───────────────────────────────────────────────

    def get_last_report(self) -> Optional[SuiteReport]:
        """Return the most recent test report, if any."""
        with self._lock:
            return self._history[-1] if self._history else None

    def get_report_by_id(self, run_id: str) -> Optional[SuiteReport]:
        """Look up a report by its run ID."""
        with self._lock:
            for report in reversed(self._history):
                if report.run_id == run_id:
                    return report
        return None

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return summary dicts of recent test runs.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of summary dicts (run_id, timestamp, suite, overall_passed).
        """
        with self._lock:
            runs = self._history[-limit:]
        return [
            {
                "run_id": r.run_id,
                "timestamp": r.timestamp,
                "suite": r.suite,
                "overall_passed": r.overall_passed,
                "total_passed": r.total_passed,
                "total_failed": r.total_failed,
                "total_errors": r.total_errors,
                "duration": r.total_duration_seconds,
            }
            for r in reversed(runs)
        ]

    @property
    def is_running(self) -> bool:
        """True if a test run is currently in progress."""
        return self._current_run is not None


# ── CLI ──────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="test_scheduler",
        description="CosySim Automated Testing Scheduler",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run tests immediately and exit.",
    )
    parser.add_argument(
        "--schedule",
        type=int,
        metavar="MINUTES",
        default=0,
        help="Schedule recurring test runs every N minutes.",
    )
    parser.add_argument(
        "--suite",
        choices=["unit", "health", "browser", "full"],
        default=None,
        help="Test suite to run (default: from config or 'full').",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Scene port for health/browser tests.",
    )
    parser.add_argument(
        "--store-nexus",
        action="store_true",
        help="Store results in Nexus (overrides config).",
    )
    parser.add_argument(
        "--json-output",
        type=str,
        metavar="PATH",
        default=None,
        help="Write JSON report to file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Command-line arguments.  Defaults to sys.argv[1:].

    Returns:
        Exit code (0 on success, 1 on test failures).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    scheduler = TestScheduler()
    config = scheduler.config
    suite = args.suite or config.get("default_suite", "full")
    store = args.store_nexus or config.get("store_results_in_nexus", False)

    if args.run_now:
        report = scheduler.run_suite(suite, port=args.port)

        if store:
            scheduler.store_in_nexus(report)

        if args.json_output:
            out_path = Path(args.json_output)
            out_path.write_text(
                json.dumps(asdict(report), indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Report written to %s", out_path)

        status = "PASS" if report.overall_passed else "FAIL"
        logger.info(
            "Run %s complete: %s  |  passed=%d  failed=%d  errors=%d  "
            "duration=%.1fs",
            report.run_id, status,
            report.total_passed, report.total_failed, report.total_errors,
            report.total_duration_seconds,
        )
        return 0 if report.overall_passed else 1

    if args.schedule and args.schedule > 0:
        # Run once immediately, then schedule
        logger.info("Initial run before scheduling …")
        report = scheduler.run_suite(suite, port=args.port)
        if store:
            scheduler.store_in_nexus(report)

        scheduler.schedule_run(args.schedule)
        logger.info(
            "Scheduler active — running %s suite every %d minutes. "
            "Press Ctrl+C to stop.",
            suite, args.schedule,
        )
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            scheduler.stop_schedule()
            logger.info("Scheduler stopped by user")
        return 0

    # No action specified — print help
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
