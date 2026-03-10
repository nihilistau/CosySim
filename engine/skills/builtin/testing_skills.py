"""Testing agent skills — MCP-exposed test automation tools.

Allows agents to trigger test runs, check status, and retrieve reports
from the CosySim automated testing scheduler.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _scheduler():
    """Lazy-initialise a shared TestScheduler singleton."""
    from scripts.test_scheduler import TestScheduler

    if not hasattr(_scheduler, "_instance"):
        _scheduler._instance = TestScheduler()
    return _scheduler._instance


@skill(
    pack="testing",
    description="Run a CosySim test suite (unit, health, browser, or full)",
    tags=["testing", "ci", "quality"],
    category=SkillCategory.SYSTEM,
    cooldown=30,
)
def run_tests(suite: str = "full", port: int = 0) -> str:
    """Trigger a test run and return the report.

    Args:
        suite: Test suite to run — one of 'unit', 'health', 'browser', 'full'.
        port: Scene port for health/browser suites.  0 uses config defaults.

    Returns:
        JSON string with the test report summary.
    """
    scheduler = _scheduler()
    target_port = port if port > 0 else None
    report = scheduler.run_suite(suite, port=target_port)

    if scheduler.config.get("store_results_in_nexus", True):
        scheduler.store_in_nexus(report)

    return json.dumps(
        {
            "run_id": report.run_id,
            "suite": report.suite,
            "overall_passed": report.overall_passed,
            "total_passed": report.total_passed,
            "total_failed": report.total_failed,
            "total_errors": report.total_errors,
            "duration_seconds": report.total_duration_seconds,
        },
        default=str,
    )


@skill(
    pack="testing",
    description="Get the status of the last or current test run",
    tags=["testing", "status"],
    category=SkillCategory.SYSTEM,
)
def test_status() -> str:
    """Return current/last test run status.

    Returns:
        JSON string with run status, or a message if no runs exist.
    """
    scheduler = _scheduler()

    if scheduler.is_running:
        return json.dumps({"status": "running"})

    last = scheduler.get_last_report()
    if last is None:
        return json.dumps({"status": "no_runs"})

    return json.dumps(
        {
            "status": "completed",
            "run_id": last.run_id,
            "timestamp": last.timestamp,
            "suite": last.suite,
            "overall_passed": last.overall_passed,
            "total_passed": last.total_passed,
            "total_failed": last.total_failed,
            "total_errors": last.total_errors,
            "duration_seconds": last.total_duration_seconds,
        },
        default=str,
    )


@skill(
    pack="testing",
    description="Get the full report for a specific test run by ID",
    tags=["testing", "report"],
    category=SkillCategory.SYSTEM,
)
def test_report(run_id: str) -> str:
    """Retrieve a specific test report by run ID.

    Args:
        run_id: The unique identifier of the test run.

    Returns:
        JSON string with the full report, or an error if not found.
    """
    scheduler = _scheduler()
    report = scheduler.get_report_by_id(run_id)
    if report is None:
        return json.dumps({"error": f"No report found for run_id '{run_id}'"})
    return json.dumps(asdict(report), default=str)


@skill(
    pack="testing",
    description="List recent test runs with summary info",
    tags=["testing", "history"],
    category=SkillCategory.SYSTEM,
)
def list_test_runs(limit: int = 20) -> str:
    """List recent test runs.

    Args:
        limit: Maximum number of runs to return.

    Returns:
        JSON string with a list of run summaries.
    """
    scheduler = _scheduler()
    runs = scheduler.list_runs(limit=limit)
    return json.dumps({"runs": runs, "count": len(runs)}, default=str)
