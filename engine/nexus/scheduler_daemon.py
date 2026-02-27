"""
Scheduled Task Runner — Lightweight cron-like daemon for CosySim autonomous operations.

Manages recurring background tasks (Nexus maintenance, dedup, quality checks)
with persistent state, schedule parsing, and CLI interface.

Usage:
    python -m engine.nexus.scheduler_daemon status
    python -m engine.nexus.scheduler_daemon run <task_id>
    python -m engine.nexus.scheduler_daemon start
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Schedule Constants ────

_SCHEDULE_PATTERNS = {
    "daily": 24 * 3600,
    "weekly": 7 * 24 * 3600,
}

_INTERVAL_RE = re.compile(r"^every_(\d+)([hm])$")

_DEFAULT_STATE_PATH = Path("data/scheduler_state.json")


# ──── Data Model ────

@dataclass
class ScheduledTask:
    """A recurring task managed by the scheduler daemon."""

    id: str
    name: str
    schedule: str
    callback: Callable[[], Any]
    enabled: bool = True
    last_run: Optional[float] = None
    last_result: Optional[str] = None
    run_count: int = 0
    error_count: int = 0


# ──── Schedule Parsing ────

def parse_schedule_seconds(schedule: str) -> float:
    """Parse a schedule string into an interval in seconds.

    Args:
        schedule: One of "daily", "weekly", "every_Nh", "every_Nm".

    Returns:
        Interval in seconds.

    Raises:
        ValueError: If the schedule string is not recognised.
    """
    if schedule in _SCHEDULE_PATTERNS:
        return float(_SCHEDULE_PATTERNS[schedule])

    match = _INTERVAL_RE.match(schedule)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        if unit == "h":
            return float(value * 3600)
        if unit == "m":
            return float(value * 60)

    raise ValueError(f"Unrecognised schedule format: {schedule!r}")


# ──── Daemon Class ────

class TaskSchedulerDaemon:
    """Cron-like daemon for running recurring CosySim tasks.

    Not to be confused with the agent TaskScheduler — this manages
    time-based recurring operations such as Nexus maintenance.
    """

    def __init__(self, state_path: Optional[Path] = None) -> None:
        self._tasks: Dict[str, ScheduledTask] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._state_path = state_path or _DEFAULT_STATE_PATH
        self._persisted_state: Dict[str, Any] = {}
        self._load_state()

    # ──── Task Management ────

    def register(
        self,
        task_id: str,
        name: str,
        schedule: str,
        callback: Callable[[], Any],
        enabled: bool = True,
    ) -> None:
        """Register a recurring task.

        Args:
            task_id: Unique identifier for the task.
            name: Human-readable task name.
            schedule: Cron-like schedule string.
            callback: Zero-arg callable to execute.
            enabled: Whether the task is active.

        Raises:
            ValueError: If the schedule string is invalid.
        """
        parse_schedule_seconds(schedule)  # validate early
        with self._lock:
            existing = self._tasks.get(task_id)
            persisted = getattr(self, "_persisted_state", {}).get(task_id, {})
            task = ScheduledTask(
                id=task_id,
                name=name,
                schedule=schedule,
                callback=callback,
                enabled=enabled,
                last_run=existing.last_run if existing else persisted.get("last_run"),
                last_result=existing.last_result if existing else persisted.get("last_result"),
                run_count=existing.run_count if existing else persisted.get("run_count", 0),
                error_count=existing.error_count if existing else persisted.get("error_count", 0),
            )
            self._tasks[task_id] = task
            logger.info("Registered task %s (%s)", task_id, schedule)

    def unregister(self, task_id: str) -> None:
        """Remove a registered task.

        Args:
            task_id: The task to remove.
        """
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._save_state()
                logger.info("Unregistered task %s", task_id)

    # ──── Execution ────

    def run_task(self, task_id: str) -> Dict[str, Any]:
        """Run a specific task immediately.

        Args:
            task_id: The task to run.

        Returns:
            Dict with keys: task_id, success, result or error, duration_s.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return {"task_id": task_id, "success": False, "error": "Task not found"}

        return self._execute(task)

    def run_due(self) -> List[Dict[str, Any]]:
        """Run all tasks that are due according to their schedule.

        Returns:
            List of result dicts from each executed task.
        """
        now = time.time()
        results: List[Dict[str, Any]] = []

        with self._lock:
            due_tasks = [
                t for t in self._tasks.values()
                if t.enabled and self._is_due(t, now)
            ]

        for task in due_tasks:
            results.append(self._execute(task))

        return results

    def _is_due(self, task: ScheduledTask, now: float) -> bool:
        """Check whether a task is due to run."""
        if task.last_run is None:
            return True
        interval = parse_schedule_seconds(task.schedule)
        return (now - task.last_run) >= interval

    def _execute(self, task: ScheduledTask) -> Dict[str, Any]:
        """Execute a task, record results, and persist state."""
        start = time.time()
        try:
            raw = task.callback()
            duration = time.time() - start
            result_str = str(raw) if raw is not None else "ok"

            with self._lock:
                task.last_run = time.time()
                task.last_result = result_str[:500]
                task.run_count += 1
                self._save_state()

            logger.info(
                "Task %s completed in %.1fs (run #%d)",
                task.id, duration, task.run_count,
            )
            self._log_to_nexus(task, success=True, duration=duration)

            return {
                "task_id": task.id,
                "success": True,
                "result": result_str[:500],
                "duration_s": round(duration, 2),
            }

        except Exception as exc:
            duration = time.time() - start
            error_str = f"{type(exc).__name__}: {exc}"

            with self._lock:
                task.last_run = time.time()
                task.last_result = f"ERROR: {error_str}"
                task.run_count += 1
                task.error_count += 1
                self._save_state()

            logger.error("Task %s failed: %s", task.id, error_str)
            self._log_to_nexus(task, success=False, duration=duration, error=error_str)

            return {
                "task_id": task.id,
                "success": False,
                "error": error_str,
                "duration_s": round(duration, 2),
            }

    # ──── Daemon Loop ────

    def start(self, interval_seconds: float = 60) -> None:
        """Start the daemon loop in a background thread.

        Args:
            interval_seconds: How often to check for due tasks.
        """
        if self._running:
            logger.warning("Scheduler daemon already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            args=(interval_seconds,),
            daemon=True,
            name="SchedulerDaemon",
        )
        self._thread.start()
        logger.info("Scheduler daemon started (interval=%ds)", interval_seconds)

    def stop(self) -> None:
        """Stop the daemon loop."""
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Scheduler daemon stopped")

    def _loop(self, interval: float) -> None:
        """Background loop that checks and runs due tasks."""
        while self._running:
            try:
                results = self.run_due()
                if results:
                    logger.info(
                        "Scheduler tick: %d task(s) executed", len(results),
                    )
            except Exception as exc:
                logger.error("Scheduler loop error: %s", exc)

            # Sleep in small increments so stop() is responsive
            waited = 0.0
            while waited < interval and self._running:
                time.sleep(min(1.0, interval - waited))
                waited += 1.0

    # ──── Status ────

    def status(self) -> Dict[str, Any]:
        """Return status of all registered tasks.

        Returns:
            Dict with running flag and per-task status info.
        """
        now = time.time()
        tasks_status: List[Dict[str, Any]] = []

        with self._lock:
            for task in self._tasks.values():
                interval = parse_schedule_seconds(task.schedule)
                if task.last_run is not None:
                    next_due = task.last_run + interval
                else:
                    next_due = now  # due immediately

                tasks_status.append({
                    "id": task.id,
                    "name": task.name,
                    "schedule": task.schedule,
                    "enabled": task.enabled,
                    "last_run": (
                        datetime.fromtimestamp(task.last_run, tz=timezone.utc).isoformat()
                        if task.last_run else None
                    ),
                    "next_due": datetime.fromtimestamp(next_due, tz=timezone.utc).isoformat(),
                    "run_count": task.run_count,
                    "error_count": task.error_count,
                    "last_result": task.last_result,
                })

        return {
            "running": self._running,
            "task_count": len(tasks_status),
            "tasks": tasks_status,
        }

    def list_tasks(self) -> List[Dict[str, Any]]:
        """List all registered tasks.

        Returns:
            List of task summary dicts.
        """
        return self.status()["tasks"]

    # ──── State Persistence ────

    def _load_state(self) -> None:
        """Load last-run timestamps from the state file."""
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._persisted_state = data
            logger.debug("Loaded scheduler state from %s", self._state_path)
        except Exception as exc:
            logger.warning("Failed to load scheduler state: %s", exc)
            self._persisted_state = {}

    def _save_state(self) -> None:
        """Persist task run data to disk."""
        state: Dict[str, Any] = {}
        for task in self._tasks.values():
            state[task.id] = {
                "last_run": task.last_run,
                "last_result": task.last_result,
                "run_count": task.run_count,
                "error_count": task.error_count,
            }
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(state, indent=2), encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save scheduler state: %s", exc)

    # ──── Nexus Logging ────

    def _log_to_nexus(
        self,
        task: ScheduledTask,
        success: bool,
        duration: float,
        error: Optional[str] = None,
    ) -> None:
        """Log task execution to Nexus (best-effort)."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            status_str = "completed" if success else "failed"
            content = (
                f"Scheduled task '{task.name}' ({task.id}) {status_str} "
                f"in {duration:.1f}s. Run #{task.run_count}."
            )
            if error:
                content += f"\nError: {error}"
            client.add_entry(
                title=f"Scheduler: {task.name} {status_str}",
                content=content,
                content_type="history",
                category="system",
            )
        except Exception as exc:
            logger.debug("Could not log to Nexus: %s", exc)


# ──── Singleton ────

_daemon: Optional[TaskSchedulerDaemon] = None
_daemon_lock = threading.Lock()


def get_scheduler_daemon(state_path: Optional[Path] = None) -> TaskSchedulerDaemon:
    """Get or create the singleton TaskSchedulerDaemon.

    Args:
        state_path: Optional override for state file location.

    Returns:
        The singleton daemon instance.
    """
    global _daemon
    if _daemon is None:
        with _daemon_lock:
            if _daemon is None:
                _daemon = TaskSchedulerDaemon(state_path=state_path)
                _register_builtin_tasks(_daemon)
    return _daemon


# ──── Built-in Tasks ────

def _nexus_maintenance_callback() -> Dict[str, Any]:
    """Run Nexus health report and store results."""
    from engine.nexus.self_maintenance import nexus_health_report
    report = nexus_health_report()
    # Store the report in Nexus for trend tracking
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_entry(
            title=f"Health Report: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            content=json.dumps(report, indent=2, default=str),
            content_type="history",
            category="system",
        )
    except Exception as exc:
        logger.debug("Could not store health report in Nexus: %s", exc)
    return report


def _nexus_dedup_callback() -> Dict[str, Any]:
    """Run Nexus deduplication (dry-run) and report duplicates."""
    from engine.nexus.self_maintenance import nexus_merge_duplicates
    return nexus_merge_duplicates(dry_run=True)


def _knowledge_quality_callback() -> Dict[str, Any]:
    """Score all Nexus entries and auto-generate tasks for stale/low-quality ones."""
    from engine.nexus.self_maintenance import quality_report
    report = quality_report()

    # Auto-generate refresh tasks for stale entries
    stale = report.get("stale", [])
    if stale:
        try:
            from engine.nexus.task_scheduler import get_task_scheduler
            scheduler = get_task_scheduler()
            stale_entries = [
                {"id": s.get("entry_id", ""), "title": s.get("title", "")}
                for s in stale[:5]
            ]
            scheduler.generate_from_stale_knowledge(stale_entries)
        except Exception as exc:
            logger.debug("Could not generate stale knowledge tasks: %s", exc)

    # Store quality report in Nexus
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_entry(
            title=f"Quality Report: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            content=json.dumps(report, indent=2, default=str),
            content_type="history",
            category="system",
        )
    except Exception as exc:
        logger.debug("Could not store quality report in Nexus: %s", exc)

    return report


def _notebook_rotation_callback() -> Dict[str, Any]:
    """Check NLM notebook health and clean up stale research notebooks."""
    from engine.nexus.nlm_notebook_manager import get_notebook_manager
    mgr = get_notebook_manager()
    removed = mgr.cleanup_stale(max_age_days=30)
    health = mgr.health()
    return {"removed_slots": removed, "health": health}


def _news_fetch_callback() -> Dict[str, Any]:
    """Fetch news from all sources, filter, score, and store in Nexus."""
    from engine.nexus.news_sources import get_news_registry
    registry = get_news_registry()

    articles = registry.fetch_all()
    filtered = registry.filter_articles(articles)

    # Score and sort by relevance
    for article in filtered:
        article.score = registry.score_relevance(article)
    filtered.sort(key=lambda a: a.score, reverse=True)

    # Store top articles in Nexus
    stored = registry.store_to_nexus(filtered[:30])

    # Generate daily digest and store it
    if filtered:
        digest = registry.generate_digest(filtered[:20])
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            client.add_entry(
                title=f"News Digest: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                content=digest,
                content_type="document",
                category="news",
            )
        except Exception as exc:
            logger.debug("Could not store news digest: %s", exc)

    return {
        "fetched": len(articles),
        "filtered": len(filtered),
        "stored": stored,
    }


def _test_monitor_callback() -> Dict[str, Any]:
    """Run test suite and auto-generate bug-fix tasks from failures."""
    import subprocess

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest", "tests/", "--tb=line", "-q",
                "--ignore=tests/test_agent_loop.py",
                "--ignore=tests/live_wire_test.py",
            ],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return {"error": "Test suite timed out after 600s"}
    except Exception as exc:
        return {"error": f"Failed to run tests: {exc}"}

    # Parse pass/fail counts from pytest summary
    passed = failed = 0
    import re as _re
    match = _re.search(r"(\d+) passed", output)
    if match:
        passed = int(match.group(1))
    match = _re.search(r"(\d+) failed", output)
    if match:
        failed = int(match.group(1))

    # Auto-generate tasks from failures
    tasks_created = 0
    if failed > 0:
        try:
            from engine.nexus.task_scheduler import get_task_scheduler
            scheduler = get_task_scheduler()
            tasks = scheduler.generate_from_test_failures(output)
            tasks_created = len(tasks)
        except Exception as exc:
            logger.warning("Could not generate tasks from test failures: %s", exc)

    # Store test results in Nexus
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_entry(
            title=f"Test Results: {passed} passed, {failed} failed",
            content=f"Passed: {passed}\nFailed: {failed}\nTasks created: {tasks_created}",
            content_type="history",
            category="testing",
        )
    except Exception as exc:
        logger.debug("Could not store test results: %s", exc)

    return {
        "passed": passed,
        "failed": failed,
        "tasks_created": tasks_created,
    }


def _metrics_collect_callback() -> Dict[str, Any]:
    """Collect and record all system metrics."""
    from engine.nexus.meta_metrics import get_meta_metrics
    metrics = get_meta_metrics()
    collected = metrics.collect_all()

    # Check for regressions
    alerts = metrics.check_regressions(threshold_pct=10.0)
    if alerts:
        # Store regression alerts in Nexus
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            alert_text = "\n".join(
                f"- {a.metric_name}: {a.message}" for a in alerts
            )
            client.add_entry(
                title=f"Metric Alerts: {len(alerts)} regressions detected",
                content=alert_text,
                content_type="history",
                category="system",
            )
        except Exception as exc:
            logger.debug("Could not store metric alerts: %s", exc)

    return {
        "metrics_collected": len(collected),
        "alerts": len(alerts),
    }


def _training_sync_callback() -> Dict[str, Any]:
    """Sync Nexus Q&A into the training flywheel."""
    from engine.nexus.training_flywheel import get_training_flywheel
    flywheel = get_training_flywheel()
    result = flywheel.sync_from_nexus()
    stats = flywheel.stats()
    return {
        "synced": result.get("synced", 0),
        "total_examples": stats.get("total_examples", 0),
    }


def _register_builtin_tasks(daemon: TaskSchedulerDaemon) -> None:
    """Register all built-in autonomous tasks."""
    daemon.register(
        "nexus-maintenance",
        "Nexus Health Report",
        "daily",
        _nexus_maintenance_callback,
    )
    daemon.register(
        "nexus-dedup",
        "Nexus Deduplication",
        "weekly",
        _nexus_dedup_callback,
    )
    daemon.register(
        "knowledge-quality",
        "Knowledge Quality Scoring",
        "weekly",
        _knowledge_quality_callback,
    )
    daemon.register(
        "notebook-rotation",
        "NLM Notebook Rotation",
        "weekly",
        _notebook_rotation_callback,
    )
    daemon.register(
        "news-fetch",
        "News Fetch & Digest",
        "every_8h",
        _news_fetch_callback,
    )
    daemon.register(
        "test-monitor",
        "Test Suite Monitor",
        "daily",
        _test_monitor_callback,
    )
    daemon.register(
        "metrics-collect",
        "System Metrics Collection",
        "every_4h",
        _metrics_collect_callback,
    )
    daemon.register(
        "training-sync",
        "Training Data Sync",
        "daily",
        _training_sync_callback,
    )


# ──── CLI ────

def _cli_status() -> None:
    """Print status of all tasks."""
    daemon = get_scheduler_daemon()
    info = daemon.status()
    logger.info("Scheduler running: %s", info["running"])
    logger.info("Tasks registered: %d\n", info["task_count"])
    for t in info["tasks"]:
        enabled_str = "enabled" if t["enabled"] else "DISABLED"
        logger.info("  [%s] %s (%s, %s)", t["id"], t["name"], t["schedule"], enabled_str)
        logger.info("    Last run:  %s", t["last_run"] or "never")
        logger.info("    Next due:  %s", t["next_due"])
        logger.info("    Runs: %d  Errors: %d", t["run_count"], t["error_count"])
        if t["last_result"]:
            logger.info("    Result: %s", t["last_result"][:80])
        logger.info("")


def _cli_run(task_id: str) -> None:
    """Run a specific task immediately."""
    daemon = get_scheduler_daemon()
    logger.info("Running task: %s", task_id)
    result = daemon.run_task(task_id)
    if result["success"]:
        logger.info("  ✓ Completed in %ss", result["duration_s"])
        logger.info("  Result: %s", result.get("result", "")[:120])
    else:
        logger.info("  ✗ Failed: %s", result.get("error", "unknown"))


def _cli_start() -> None:
    """Start the daemon in blocking mode."""
    daemon = get_scheduler_daemon()
    logger.info("Starting scheduler daemon (Ctrl+C to stop)...")
    daemon.start(interval_seconds=60)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
        daemon.stop()


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    args = sys.argv[1:]
    if not args or args[0] == "status":
        _cli_status()
    elif args[0] == "run" and len(args) >= 2:
        _cli_run(args[1])
    elif args[0] == "start":
        _cli_start()
    else:
        logger.info("Usage: python -m engine.nexus.scheduler_daemon {status|run <task_id>|start}")
        sys.exit(1)


if __name__ == "__main__":
    main()
