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
    """Run Nexus health report."""
    from engine.nexus.self_maintenance import nexus_health_report
    return nexus_health_report()


def _nexus_dedup_callback() -> Dict[str, Any]:
    """Run Nexus deduplication (dry-run)."""
    from engine.nexus.self_maintenance import nexus_merge_duplicates
    return nexus_merge_duplicates(dry_run=True)


def _knowledge_quality_callback() -> str:
    """Placeholder for knowledge quality checks."""
    logger.info("Knowledge quality check — placeholder (no-op)")
    return "ok"


def _register_builtin_tasks(daemon: TaskSchedulerDaemon) -> None:
    """Register the default built-in tasks."""
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
        "Knowledge Quality Check",
        "weekly",
        _knowledge_quality_callback,
    )


# ──── CLI ────

def _cli_status() -> None:
    """Print status of all tasks."""
    daemon = get_scheduler_daemon()
    info = daemon.status()
    print(f"Scheduler running: {info['running']}")
    print(f"Tasks registered: {info['task_count']}\n")
    for t in info["tasks"]:
        enabled_str = "enabled" if t["enabled"] else "DISABLED"
        print(f"  [{t['id']}] {t['name']} ({t['schedule']}, {enabled_str})")
        print(f"    Last run:  {t['last_run'] or 'never'}")
        print(f"    Next due:  {t['next_due']}")
        print(f"    Runs: {t['run_count']}  Errors: {t['error_count']}")
        if t["last_result"]:
            print(f"    Result: {t['last_result'][:80]}")
        print()


def _cli_run(task_id: str) -> None:
    """Run a specific task immediately."""
    daemon = get_scheduler_daemon()
    print(f"Running task: {task_id}")
    result = daemon.run_task(task_id)
    if result["success"]:
        print(f"  ✓ Completed in {result['duration_s']}s")
        print(f"  Result: {result.get('result', '')[:120]}")
    else:
        print(f"  ✗ Failed: {result.get('error', 'unknown')}")


def _cli_start() -> None:
    """Start the daemon in blocking mode."""
    daemon = get_scheduler_daemon()
    print("Starting scheduler daemon (Ctrl+C to stop)...")
    daemon.start(interval_seconds=60)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
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
        print("Usage: python -m engine.nexus.scheduler_daemon {status|run <task_id>|start}")
        sys.exit(1)


if __name__ == "__main__":
    main()
