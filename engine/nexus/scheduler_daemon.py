"""Scheduled Task Runner — Lightweight cron-like daemon for CosySim autonomous operations.

Version: v1.50.2 [2026-03-24]

Change Log:
    v1.50.2 [2026-03-24] — Enhanced status() with overdue/error tracking, register task-auto-assign

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

_REPO_ROOT = Path(__file__).resolve().parents[2]

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

    # v1.50.2 [2026-03-24] — Enhanced status with overdue tracking and summary stats
    def status(self) -> Dict[str, Any]:
        """Return comprehensive daemon status for Oracle observability.

        Returns:
            Dict with running flag, summary stats, and per-task details.
        """
        now = time.time()
        tasks_status: List[Dict[str, Any]] = []
        overdue_count = 0
        total_runs = 0
        total_errors = 0

        with self._lock:
            for task in self._tasks.values():
                interval = parse_schedule_seconds(task.schedule)
                if task.last_run is not None:
                    next_due = task.last_run + interval
                else:
                    next_due = now  # due immediately

                is_overdue = task.enabled and now > next_due
                if is_overdue:
                    overdue_count += 1
                total_runs += task.run_count
                total_errors += task.error_count

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
                    "next_due_in_s": max(0, int(next_due - now)),
                    "overdue": is_overdue,
                    "run_count": task.run_count,
                    "error_count": task.error_count,
                    "last_result": (task.last_result or "")[:200],
                })

        # Sort: overdue first, then by next_due_in_s ascending
        tasks_status.sort(key=lambda t: (not t["overdue"], t["next_due_in_s"]))

        enabled_count = sum(1 for t in tasks_status if t["enabled"])
        error_rate = (total_errors / total_runs * 100) if total_runs > 0 else 0.0

        return {
            "running": self._running,
            "task_count": len(tasks_status),
            "enabled_count": enabled_count,
            "overdue_count": overdue_count,
            "total_runs": total_runs,
            "total_errors": total_errors,
            "error_rate_pct": round(error_rate, 1),
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
    digest_text = ""
    if filtered:
        digest_text = registry.generate_digest(filtered[:20])
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            client.add_entry(
                title=f"News Digest: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                content=digest_text,
                content_type="document",
                category="news",
            )
        except Exception as exc:
            logger.debug("Could not store news digest: %s", exc)

    # Best-effort NLM distillation (skips gracefully if NLM offline)
    nlm_result: Dict[str, Any] = {"skipped": True}
    try:
        from engine.nexus.news_nlm_pipeline import get_news_nlm_pipeline
        pipeline = get_news_nlm_pipeline()
        nlm_result = pipeline.run(
            articles=filtered[:20],
            digest_text=digest_text or None,
        )
    except Exception as exc:
        logger.debug("News NLM distillation skipped: %s", exc)

    return {
        "fetched": len(articles),
        "filtered": len(filtered),
        "stored": stored,
        "nlm": nlm_result,
    }


def _news_nlm_retry_callback() -> Dict[str, Any]:
    """Process the NLM distillation retry queue."""
    try:
        from engine.nexus.news_nlm_pipeline import get_news_nlm_pipeline

        pipeline = get_news_nlm_pipeline()
        return pipeline.process_retries(max_retries=3)
    except Exception as exc:
        logger.debug("News NLM retry processing skipped: %s", exc)
        return {"skipped": True, "error": str(exc)}


def _operator_inbox_sync_callback() -> Dict[str, Any]:
    """Promote pending operator inbox items into tasks and plan digests."""
    try:
        from engine.config import get_config
        from engine.nexus.operator_inbox import get_operator_inbox

        cfg = get_config()
        limit = int(cfg.get("nexus.operator_inbox.plan_digest_limit", 10))
        return get_operator_inbox().process_items(limit=limit)
    except Exception as exc:
        logger.warning("Operator inbox sync failed: %s", exc)
        return {
            "ok": False,
            "processed": 0,
            "created_tasks": 0,
            "errors": [str(exc)],
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
    """Sync Nexus Q&A into the training flywheel and export if threshold met."""
    from engine.nexus.training_flywheel import get_training_flywheel
    flywheel = get_training_flywheel()
    result = flywheel.sync_from_nexus()
    stats = flywheel.stats()

    export_result: Dict[str, Any] = {}
    unexported = stats.get("unexported", 0)
    if unexported >= 50:
        export_result = flywheel.export_jsonl(min_quality=0.7)
        logger.info(
            "training-sync exported %d examples to %s",
            export_result.get("count", 0),
            export_result.get("file", ""),
        )

    return {
        "synced": result.get("synced", 0),
        "total_examples": stats.get("total_examples", 0),
        "unexported": unexported,
        "exported_count": export_result.get("count", 0),
        "exported_file": export_result.get("file", ""),
    }


def _system_reflection_callback() -> Dict[str, Any]:
    """Run weekly system reflection — analyze metrics, generate insights, create tasks."""
    from engine.nexus.system_reflection import get_system_reflection
    reflection = get_system_reflection()
    report = reflection.run_reflection(period="weekly", days=7, use_nlm=False)
    return {
        "report_id": report.report_id,
        "insights": len(report.insights),
        "tasks_created": len(report.tasks_created),
        "duration_seconds": report.duration_seconds,
    }


def _experiment_scan_callback() -> Dict[str, Any]:
    """Scan metrics for experiment opportunities and propose new experiments."""
    from engine.nexus.experiment_proposals import get_experiment_proposer
    proposer = get_experiment_proposer()
    proposals = proposer.scan_and_propose()
    return {
        "proposals": len(proposals),
        "experiments": [p.experiment_name for p in proposals],
    }


def _governance_audit_callback() -> Dict[str, Any]:
    """Validate key source files against governance rules and store results."""
    from engine.nexus.governance_rules import get_governance_manager
    gm = get_governance_manager()
    report = gm.stats()

    # Store audit in Nexus
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_entry(
            title="[Audit] Governance validation",
            content=json.dumps(report, indent=2, default=str),
            content_type="audit",
            category="governance",
            tags=["governance", "audit", "automated"],
        )
    except Exception as exc:
        logger.debug("Could not store governance audit: %s", exc)

    return {
        "total_rules": report.get("total_rules", 0),
        "categories": list(report.get("by_category", {}).keys()),
    }


def _ha_news_push_callback() -> Dict[str, Any]:
    """Push high-relevance news articles to Home Assistant as notifications."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        from engine.nexus.client import get_nexus_client
    except Exception as exc:
        return {"error": f"Import failed: {exc}"}

    ha = get_ha_client()
    if not ha.is_connected():
        conn = ha.connect()
        if not conn.get("connected"):
            return {"skipped": True, "reason": "HA not reachable"}

    # Get recent news from Nexus
    try:
        client = get_nexus_client()
        results = client.search("content_type:news", limit=20)
    except Exception as exc:
        return {"error": f"Nexus search failed: {exc}"}

    from engine.config import get_config
    threshold = get_config().get("homeassistant.news_alert_threshold", 0.7)

    pushed = 0
    errors = 0
    for entry in results:
        relevance = 0.0
        content = entry.get("content", "")
        title = entry.get("title", "")
        # Check if already pushed (simple heuristic: skip if older than 24h)
        from datetime import datetime, timezone
        created = entry.get("created_at", "")
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                if age_hours > 24:
                    continue
            except Exception:
                logger.debug("Could not parse article timestamp: %s", created)

        # Extract relevance from content if available
        if "relevance" in content.lower():
            try:
                import re
                match = re.search(r"relevance[:\s]+([0-9.]+)", content, re.IGNORECASE)
                if match:
                    relevance = float(match.group(1))
            except Exception:
                logger.debug("Could not parse relevance score from content")

        if relevance >= threshold or "breaking" in title.lower():
            try:
                url = ""
                if "http" in content:
                    import re
                    url_match = re.search(r"(https?://\S+)", content)
                    if url_match:
                        url = url_match.group(1)
                ha.send_news_alert(title, content[:200], url=url, relevance=relevance)
                pushed += 1
            except Exception:
                errors += 1

    return {"pushed": pushed, "errors": errors, "checked": len(results)}


def _doc_sync_callback() -> Dict[str, Any]:
    """Detect recent git changes and trigger documentation updates via Nexus."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "--no-pager", "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=15,
        )
        changed = [f for f in result.stdout.strip().splitlines() if f]
    except Exception as exc:
        return {"error": f"git diff failed: {exc}"}

    if not changed:
        return {"skipped": True, "reason": "no changes since last commit"}

    doc_paths = {"engine/mcp", "engine/skills", "engine/lmstudio", "engine/nexus",
                 "engine/tts", "engine/agents", "content/scenes", "config"}
    relevant = [f for f in changed if any(f.startswith(p) for p in doc_paths)]

    if not relevant:
        return {"skipped": True, "reason": "no doc-relevant changes"}

    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        summary = f"Changed files requiring doc update:\n" + "\n".join(f"  - {f}" for f in relevant)
        client.add_entry(
            title="Doc Sync: Pending Updates",
            content=summary,
            content_type="note",
            category="architecture",
            tags=["doc-sync", "pending"],
        )
    except Exception as exc:
        return {"error": f"Nexus store failed: {exc}"}

    return {"files_changed": len(changed), "doc_relevant": len(relevant), "queued": True}


def _coverage_eval_callback() -> Dict[str, Any]:
    """Daily knowledge coverage evaluation and auto-gap-filling."""
    try:
        from engine.nexus.knowledge_evaluator import run_coverage_evaluation
        return run_coverage_evaluation()
    except Exception as exc:
        logger.error("Coverage evaluation failed: %s", exc)
        return {"error": str(exc)}


def _copilot_rules_refresh_callback() -> Dict[str, Any]:
    """Weekly re-seed of all Copilot rules, instructions, and agent defs into Nexus."""
    try:
        from engine.nexus.seed_copilot_rules import run_copilot_rules_refresh
        return run_copilot_rules_refresh()
    except Exception as exc:
        logger.error("Copilot rules refresh failed: %s", exc)
        return {"error": str(exc)}


def _notebook_bootstrap_callback() -> Dict[str, Any]:
    """Weekly refresh of architecture/instructions/history NLM notebooks."""
    try:
        from engine.nexus.bootstrap_notebooks import run_notebook_bootstrap
        return run_notebook_bootstrap()
    except Exception as exc:
        logger.error("Notebook bootstrap failed: %s", exc)
        return {"error": str(exc)}


def _control_notebook_flywheel_callback() -> Dict[str, Any]:
    """Recurring control-notebook distillation into Nexus artifacts and agent tasks."""
    try:
        from engine.nexus.notebooklm_flywheel import run_control_notebook_flywheel

        return run_control_notebook_flywheel(reason="scheduler")
    except Exception as exc:
        logger.error("Control notebook flywheel failed: %s", exc)
        return {"error": str(exc)}


def _session_distillation_callback() -> Dict[str, Any]:
    """Daily distillation of Copilot session history into NLM Q&A pairs."""
    try:
        from engine.nexus.session_distillation import run_session_distillation
        return run_session_distillation()
    except Exception as exc:
        logger.error("Session distillation failed: %s", exc)
        return {"error": str(exc)}


def _qa_generation_callback() -> Dict[str, Any]:
    """Daily rule-based QA pair generation from Nexus knowledge entries.

    Generates Q&A pairs from entry titles and content using pattern matching.
    Significantly increases cache hit rate over time.
    """
    try:
        from engine.nexus.qa_generator import run_rule_based
        added = run_rule_based(limit=200, dry_run=False)
        return {"qa_pairs_added": added}
    except Exception as exc:
        logger.error("QA generation failed: %s", exc)
        return {"error": str(exc)}


def _copilot_self_sync_callback() -> Dict[str, Any]:
    """Weekly sync of Copilot instructions, agents, and hooks to Nexus.

    Ensures local agents always have access to the latest Copilot rules,
    agent definitions, and hook configurations via Nexus search.
    """
    try:
        from engine.nexus.copilot_self_config import get_copilot_config
        result = get_copilot_config().sync_all_to_nexus()
        return result
    except Exception as exc:
        logger.error("Copilot self sync failed: %s", exc)
        return {"error": str(exc)}


def _register_builtin_tasks(daemon: "SchedulerDaemon") -> None:
    """Register all built-in autonomous tasks."""
    try:
        from engine.config import get_config

        operator_inbox_schedule = get_config().get(
            "nexus.operator_inbox.auto_sync_schedule",
            "every_15m",
        )
    except Exception:
        operator_inbox_schedule = "every_15m"

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
        "news-nlm-retry",
        "News NLM Retry Queue",
        "every_12h",
        _news_nlm_retry_callback,
    )
    daemon.register(
        "news-distill-nlm",
        "News NLM Distillation",
        "every_6h",
        _news_distill_nlm_callback,
    )
    daemon.register(
        "feed-health",
        "RSS Feed Health Check",
        "every_12h",
        _feed_health_callback,
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
    daemon.register(
        "system-reflection",
        "Weekly System Reflection",
        "weekly",
        _system_reflection_callback,
    )
    daemon.register(
        "experiment-scan",
        "Experiment Proposal Scan",
        "weekly",
        _experiment_scan_callback,
    )
    daemon.register(
        "governance-audit",
        "Governance Rules Audit",
        "weekly",
        _governance_audit_callback,
    )
    daemon.register(
        "ha-news-push",
        "Push News to Home Assistant",
        "every_8h",
        _ha_news_push_callback,
    )
    daemon.register(
        "doc-sync",
        "Auto Documentation Sync",
        "daily",
        _doc_sync_callback,
    )
    daemon.register(
        "coverage-eval",
        "Knowledge Coverage Evaluation",
        "daily",
        _coverage_eval_callback,
    )
    daemon.register(
        "copilot-rules-refresh",
        "Copilot Rules Refresh",
        "weekly",
        _copilot_rules_refresh_callback,
    )
    daemon.register(
        "notebook-bootstrap",
        "NLM Notebook Bootstrap",
        "weekly",
        _notebook_bootstrap_callback,
    )
    daemon.register(
        "control-notebook-flywheel",
        "Control Notebook Flywheel — distill the control notebook into Nexus artifacts, tasks, and training examples",
        "every_8h",
        _control_notebook_flywheel_callback,
    )
    daemon.register(
        "session-distillation",
        "Copilot Session Distillation",
        "daily",
        _session_distillation_callback,
    )
    daemon.register(
        "qa-generation",
        "Nexus QA Pair Generation",
        "daily",
        _qa_generation_callback,
    )
    daemon.register(
        "copilot-self-sync",
        "Copilot Config Sync to Nexus",
        "weekly",
        _copilot_self_sync_callback,
    )
    daemon.register(
        "operator-inbox-sync",
        "Operator Inbox Sync",
        operator_inbox_schedule,
        _operator_inbox_sync_callback,
    )
    daemon.register(
        "master-notebook-refresh",
        "Master Notebook Weekly Refresh",
        "weekly",
        _master_notebook_refresh_callback,
    )
    daemon.register(
        "qa-expansion",
        "Nexus QA Expansion (reverse-generate Q&A pairs)",
        "daily",
        _qa_expansion_callback,
    )
    daemon.register(
        "qa-history-mine",
        "NLM-Driven QA Cache Pipeline (Gemini 3.0 generation cycle)",
        "weekly",
        _qa_history_mine_callback,
    )
    daemon.register(
        "qa-cache-prune",
        "QA Cache Pruning (remove stale zero-hit pairs)",
        "weekly",
        _qa_cache_prune_callback,
    )
    daemon.register(
        "teacher-dataset-gen",
        "NLM Teacher Dataset Generation (micro-model training data)",
        "weekly",
        _teacher_dataset_gen_callback,
    )
    daemon.register(
        "finetune-if-ready",
        "Auto Fine-tune When Dataset Grows 500+ Examples",
        "weekly",
        _finetune_if_ready_callback,
    )
    daemon.register(
        "model-benchmark",
        "Daily Micro-Model Benchmarks",
        "daily",
        _model_benchmark_callback,
    )
    daemon.register(
        "backup-databases",
        "Scheduled Database Backups (Nexus + session store)",
        "daily",
        _backup_databases_callback,
    )
    daemon.register(
        "conversation-analyze",
        "Post-Session Conversation Analysis",
        "daily",
        _conversation_analyze_callback,
    )
    daemon.register(
        "router-finetune-cycle",
        "Router v2 Full Finetune Cycle (dataset → train → benchmark → promote)",
        "weekly",
        _router_finetune_cycle_callback,
    )
    daemon.register(
        "dataset-augment",
        "Dataset Augmentation — Re-augment all micro-model datasets with new session data",
        "weekly",
        _dataset_augment_callback,
    )
    daemon.register(
        "world-sim-tick",
        "World Simulation Tick (5-minute sim-time advance)",
        "every_5m",
        _world_sim_tick_callback,
    )
    daemon.register(
        "director-tick",
        "Scene Director Beat (15-minute narrative advance)",
        "every_15m",
        _director_tick_callback,
    )
    daemon.register(
        "content-refresh",
        "Content Pool Refresh (6-hour NLM refill for depleted pools)",
        "every_6h",
        _content_refresh_callback,
    )
    daemon.register(
        "nlm-content-seed",
        "NLM Content Seed — weekly deep-seed all scene pools + director beats via NLM",
        "weekly",
        _nlm_content_seed_callback,
    )
    daemon.register(
        "scene-lore-seed",
        "Scene Lore Seed — weekly NLM lore generation for all scenes",
        "weekly",
        _scene_lore_seed_callback,
    )
    daemon.register(
        "daily-challenge-seed",
        "Daily Challenge Seed — pre-generate scene challenges for all 9 scenes",
        "daily",
        _daily_challenge_seed_callback,
    )
    daemon.register(
        "npc-world-tick",
        "NPC World Tick",
        "every_1m",
        _npc_world_tick_callback,
    )
    daemon.register(
        "router-data-export",
        "Router Training Data Export (hourly RouterDataCollector → JSONL)",
        "every_4h",
        _router_data_export_callback,
    )
    daemon.register(
        "router-v3-retrain",
        "Router v3 Retrain Cycle (weekly export → finetune → evaluate → promote)",
        "weekly",
        _router_v3_retrain_callback,
    )
    daemon.register(
        "news-distill-nlm",
        "News NLM Distillation — distill news articles into Nexus Q&A via NotebookLM",
        "every_1h",
        _news_distill_nlm_callback,
    )
    daemon.register(
        "collect-flush",
        "DataCollector Flush — merge live collected samples into training datasets",
        "every_4h",
        _collect_flush_callback,
    )
    daemon.register(
        "model-zoo-train",
        "Model Zoo Auto-Train — check thresholds and submit finetune jobs",
        "daily",
        _model_zoo_train_callback,
    )
    daemon.register(
        "voice-auto-train",
        "Voice Auto-Train — train Piper/Qwen3/Orpheus from collected voice samples",
        "weekly",
        _voice_auto_train_callback,
    )
    daemon.register(
        "coder-dataset-refresh",
        "Coder Dataset Refresh — weekly rescan codebase + Nexus for training data",
        "weekly",
        _coder_dataset_refresh_callback,
    )
    daemon.register(
        "improvement-review",
        "Output Improvement Review — batch NLM review of low-quality responses for training signal",
        "weekly",
        _improvement_review_callback,
    )
    daemon.register(
        "colab-pipeline-sync",
        "Colab Pipeline Sync — daily NLM→Drive→Colab analysis of improvement entries",
        "daily",
        _colab_pipeline_sync_callback,
    )
    daemon.register(
        "cdp-mine",
        "CDP Log Miner — extract browser_debugger/error_classifier training examples from CDP monitor log",
        "daily",
        _cdp_mine_callback,
    )
    daemon.register(
        "cookie-health-check",
        "Cookie Health Check — probe Google account pool, warn if stale, store in Nexus",
        "daily",
        _cookie_health_check_callback,
    )
    daemon.register(
        "cookie-auto-refresh",
        "Cookie Auto-Refresh — CDP cookie extraction from running Chrome every 12h",
        "every_12h",
        _cookie_auto_refresh_callback,
    )
    daemon.register(
        "test-suite-benchmark",
        "Test Suite Benchmark — time the full pytest suite and store results/trends in Nexus",
        "weekly",
        _test_suite_benchmark_callback,
    )
    daemon.register(
        "argus-weekly-scan",
        "ARGUS Weekly Scan — crawl NLM/Gemini/AI Studio via Playwright+CDP, detect new rpcids/methods, store in Nexus",
        "weekly",
        _argus_weekly_scan_callback,
    )
    daemon.register(
        "argus-diff-report",
        "ARGUS Diff Report — compare latest ARGUS registry vs prior scan, store delta in Nexus",
        "weekly",
        _argus_diff_report_callback,
    )
    daemon.register(
        "argus-nlm-distil",
        "ARGUS NLM Distillation — upload discovery doc to NotebookLM, batch-ask API questions, store Q&A in Nexus",
        "weekly",
        _argus_nlm_distil_callback,
    )
    daemon.register(
        "auto-embedding",
        "Auto-Embed — batch-embed new Nexus entries and Q&A pairs into ChromaDB vector store",
        "every_4h",
        _auto_embedding_callback,
    )

    # ── Workspace Pipeline Tasks ──────────────────────────────────────────
    daemon.register(
        "workspace-news-pipeline",
        "Workspace News Pipeline — fetch RSS → optional NLM distillation → store in Nexus",
        "every_8h",
        _workspace_news_pipeline_callback,
    )
    daemon.register(
        "workspace-news-to-knowledge",
        "News-to-Knowledge — fetch news → NLM research → Docs → Drive → Nexus",
        "daily",
        _workspace_news_to_knowledge_callback,
    )
    daemon.register(
        "workspace-research-cycle",
        "Research Cycle — run research_and_distill pipeline for queued topics",
        "every_12h",
        _workspace_research_cycle_callback,
    )
    daemon.register(
        "workspace-pipeline-health",
        "Pipeline Health Check — verify pipeline stages and client connectivity",
        "every_6h",
        _workspace_pipeline_health_callback,
    )
    daemon.register(
        "benchmark-flush",
        "Flush in-memory benchmarks to MetaMetrics SQLite persistence",
        "every_5m",
        _benchmark_flush_callback,
    )
    daemon.register(
        "copilot-auto-repair",
        "Detect Copilot drift and auto-repair via CopilotSelfConfig sync",
        "daily",
        _copilot_auto_repair_callback,
    )
    daemon.register(
        "process-monitor-snapshot",
        "Capture full process snapshot and record to MetricsDB",
        "every_4h",
        _process_snapshot_callback,
    )
    daemon.register(
        "git-operation-check",
        "Check for running or stalled git operations",
        "every_15m",
        _git_operation_check_callback,
    )
    daemon.register(
        "stall-detection-sweep",
        "Scan for stalled processes across all tracked categories",
        "every_4h",
        _stall_detection_callback,
    )

    # ──── v1.29 Self-Improvement Execution Loop ────
    try:
        from engine.nexus.experiment_executor import register_experiment_tasks
        register_experiment_tasks(daemon)
    except Exception as exc:
        logger.debug("ExperimentExecutor registration skipped: %s", exc)

    try:
        from engine.nexus.online_evaluator import register_online_eval_tasks
        register_online_eval_tasks(daemon)
    except Exception as exc:
        logger.debug("OnlineEvaluator registration skipped: %s", exc)

    try:
        from engine.nexus.impact_tracker import register_impact_tasks
        register_impact_tasks(daemon)
    except Exception as exc:
        logger.debug("ImpactTracker registration skipped: %s", exc)

    try:
        from engine.observability.anomaly_trigger import register_anomaly_trigger_tasks
        register_anomaly_trigger_tasks(daemon)
    except Exception as exc:
        logger.debug("AnomalyTrigger registration skipped: %s", exc)

    # ──── PM2 Process Management ────
    try:
        from engine.system.pm2_manager import register_pm2_tasks
        register_pm2_tasks(daemon)
    except Exception as exc:
        logger.debug("PM2 task registration skipped: %s", exc)

    # ──── Causal Analysis ────
    try:
        from engine.observability.causal_engine import register_causal_tasks
        register_causal_tasks(daemon)
    except Exception as exc:
        logger.debug("CausalEngine task registration skipped: %s", exc)

    # ──── Predictive Refresh ────
    try:
        from engine.nexus.predictive_refresh import register_refresh_tasks
        register_refresh_tasks(daemon)
    except Exception as exc:
        logger.debug("PredictiveRefresh task registration skipped: %s", exc)

    # ──── v1.43 News Intelligence ────
    try:
        from engine.nexus.news.scheduler_tasks import register_news_intelligence_tasks
        register_news_intelligence_tasks(daemon)
    except Exception as exc:
        logger.debug("NewsIntelligence task registration skipped: %s", exc)

    # ──── CDP Auth Recovery ────
    try:
        from engine.nexus.cdp_auth_recovery import check_and_recover_if_needed
        daemon.register(
            "cdp-auth-health",
            "Google Auth Health Check + Auto-Recovery",
            "every_30m",
            check_and_recover_if_needed,
        )
    except Exception as exc:
        logger.debug("CDP auth recovery task registration skipped: %s", exc)

    # ──── NLM Auto-Distillation ────
    daemon.register("nlm-auto-distill", "Auto-distill Q&A from high-traffic Nexus topics", "every_6h", _nlm_auto_distill_callback)

    # ──── ARGUS Periodic Crawl ────
    daemon.register("argus-periodic-crawl", "Periodic ARGUS API surface scan (NLM rpcid coverage)", "weekly", _argus_periodic_crawl_callback)

    # v1.50.2 [2026-03-24] — Task auto-assignment: push tasks to available LMStudio agents
    try:
        from engine.config import get_config as _gc2
        aa_enabled = _gc2().get("nexus.tasks.auto_assign.enabled", True)
        aa_interval = _gc2().get("nexus.tasks.auto_assign.interval", "every_5m")
        if aa_enabled:
            daemon.register("task-auto-assign", "Task Auto-Assignment", aa_interval, _auto_assign_callback)
    except Exception as exc:
        logger.debug("Task auto-assign registration skipped: %s", exc)

    # v1.51.0 [2026-03-24] — System maintenance: cleanup + conversation eviction
    daemon.register(
        "system-cleanup",
        "System Cleanup — chrome caches, HAR files, WAL checkpoint, log retention, backup pruning",
        "daily",
        _system_cleanup_callback,
    )
    daemon.register(
        "conversation-evict",
        "Conversation Eviction — remove idle conversations to reclaim memory",
        "every_1h",
        _conversation_evict_callback,
    )


# v1.51.0 [2026-03-24] — System maintenance callbacks
def _system_cleanup_callback() -> Dict[str, Any]:
    """Daily: run full system cleanup — chrome caches, HAR files, WAL checkpoint, log retention."""
    try:
        from engine.maintenance.cleanup import run_full_cleanup
        return run_full_cleanup()
    except Exception as exc:
        logger.warning("[SchedulerDaemon] System cleanup failed (operation=system_cleanup): %s", exc)
        return {"error": str(exc)}


def _conversation_evict_callback() -> Dict[str, Any]:
    """Hourly: evict stale conversations from ConversationManager."""
    try:
        from engine.maintenance.cleanup import evict_stale_conversations
        evicted = evict_stale_conversations()
        return {"evicted": evicted}
    except Exception as exc:
        logger.warning("[SchedulerDaemon] Conversation eviction failed (operation=conv_evict): %s", exc)
        return {"error": str(exc)}


def _nlm_auto_distill_callback() -> Dict[str, Any]:
    try:
        from engine.nexus.query_router import get_query_router
        router = get_query_router()
        stats = router.stats
        if stats.llm_fallbacks < 5:
            return {"skipped": True, "reason": "too few fallbacks", "fallbacks": stats.llm_fallbacks}
        from engine.nexus.nlm_qa_distiller import NLMQADistiller
        distiller = NLMQADistiller()
        result = distiller.distill_from_entries(category="auto", limit=10)
        return {"distilled_pairs": result.get("pairs_stored", 0) if isinstance(result, dict) else 0,
                "llm_fallbacks_at_start": stats.llm_fallbacks, "total_queries": stats.total_queries}
    except Exception as exc:
        logger.warning("[SchedulerDaemon] NLM auto-distill failed (operation=nlm_distill): %s", exc)
        return {"error": str(exc)}

def _argus_periodic_crawl_callback() -> Dict[str, Any]:
    try:
        from scripts.argus.config import NLM_RPCIDS
        from scripts.argus.discovery.endpoint_registry import EndpointRegistry
        registry = EndpointRegistry()
        stats = registry.stats()
        nlm_coverage = len(NLM_RPCIDS)
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            client.add_entry(title=f"ARGUS Coverage Snapshot ({time.strftime('%Y-%m-%d')})",
                           content=json.dumps(stats, indent=2) if isinstance(stats, dict) else str(stats),
                           content_type="note", category="system", tags=["argus", "coverage", "periodic"])
        except Exception:
            pass
        return {"nlm_rpcids_known": nlm_coverage, "registry_stats": stats if isinstance(stats, dict) else str(stats)}
    except Exception as exc:
        logger.warning("[SchedulerDaemon] ARGUS periodic crawl failed (operation=argus_crawl): %s", exc)
        return {"error": str(exc)}


# v1.50.2 [2026-03-24] — Auto-assign pending tasks to available LMStudio agents
# CONNECTS: TaskScheduler.auto_assign(), LocalAgentBridge.build_agent_registry()
# CALLED BY: scheduler daemon every 5m (configurable)
def _auto_assign_callback() -> Dict[str, Any]:
    """Discover available agents, clean stale tasks, and auto-assign pending work."""
    try:
        from engine.config import get_config
        from engine.nexus.task_scheduler import get_task_scheduler
        from engine.nexus.local_agent_bridge import get_local_agent_bridge

        cfg = get_config()
        timeout_hours = cfg.get("nexus.tasks.auto_assign.stale_timeout_hours", 24.0)
        min_score = cfg.get("nexus.tasks.auto_assign.min_match_score", 0.3)

        bridge = get_local_agent_bridge()
        scheduler = get_task_scheduler()

        # Step 1: Clean up stale claimed tasks
        stale_count = scheduler.cleanup_stale_tasks(timeout_hours=timeout_hours)

        # Step 2: Build agent registry from loaded LMStudio models
        agents = bridge.build_agent_registry()
        if not agents:
            return {
                "skipped": True,
                "reason": "no loaded models",
                "stale_cleaned": stale_count,
            }

        # Step 3: Auto-assign pending tasks to best-matching agents
        assignments = scheduler.auto_assign(agents, min_score=min_score)

        return {
            "agents_available": len(agents),
            "tasks_assigned": len(assignments),
            "stale_cleaned": stale_count,
            "assignments": assignments,
        }
    except Exception as exc:
        logger.warning(
            "[SchedulerDaemon] Task auto-assign failed (operation=auto_assign): %s", exc
        )
        return {"error": str(exc)}


def _auto_embedding_callback() -> Dict[str, Any]:
    """Batch-embed new Nexus entries and Q&A pairs into the vector store.

    Also processes the retry queue for previously failed embeddings.
    """
    try:
        from engine.nexus.embedding_hooks import (
            batch_embed_nexus_entries,
            batch_embed_qa_entries,
            process_retry_queue,
        )
        entries_result = batch_embed_nexus_entries(limit=500)
        qa_result = batch_embed_qa_entries(limit=500)
        # v1.49.5 [2026-03-22] — Process retry queue for previously failed embeddings
        retry_result = process_retry_queue(limit=100)
        return {
            "entries_embedded": entries_result.get("embedded", 0),
            "entries_skipped": entries_result.get("skipped", 0),
            "qa_embedded": qa_result.get("embedded", 0),
            "qa_skipped": qa_result.get("skipped", 0),
            "retry_succeeded": retry_result.get("succeeded", 0),
            "retry_failed": retry_result.get("failed", 0),
        }
    except Exception as exc:
        logger.error("[SchedulerDaemon] Auto-embedding task failed (operation=embed): %s", exc)
        return {"error": str(exc)}


# ── Process Monitor Callbacks ─────────────────────────────────────────────────


def _process_snapshot_callback() -> Dict[str, Any]:
    """Capture a full process snapshot and record to MetricsDB."""
    try:
        from engine.system import get_process_monitor

        mon = get_process_monitor()
        snapshot = mon.system_snapshot()
        recorded = mon.record_to_metrics_db()
        return {
            "total_processes": snapshot.get("total_processes", 0),
            "git_operations": len(snapshot.get("git_operations", [])),
            "tracked_operations": len(snapshot.get("tracked_operations", [])),
            "stalled": len(snapshot.get("stalled", [])),
            "total_memory_mb": snapshot.get("total_memory_mb", 0.0),
            "recorded_to_db": recorded,
        }
    except Exception as exc:
        logger.error("Process snapshot task failed: %s", exc)
        return {"error": str(exc)}


def _git_operation_check_callback() -> Dict[str, Any]:
    """Check for running or stalled git operations."""
    try:
        from engine.system import get_process_monitor

        mon = get_process_monitor()
        git_ops = mon.git_operations()
        stalled = [
            op for op in git_ops
            if op.elapsed_seconds > 300
        ]
        if stalled:
            logger.warning(
                "Detected %d stalled git operations: %s",
                len(stalled),
                ", ".join(f"{o.op_type.value}({o.pid})" for o in stalled),
            )
        return {
            "active_git_ops": len(git_ops),
            "stalled_git_ops": len(stalled),
            "operations": [
                {
                    "pid": op.pid,
                    "type": op.op_type.value,
                    "phase": op.phase.value,
                    "elapsed_seconds": round(op.elapsed_seconds, 1),
                }
                for op in git_ops
            ],
        }
    except Exception as exc:
        logger.error("Git operation check failed: %s", exc)
        return {"error": str(exc)}


def _stall_detection_callback() -> Dict[str, Any]:
    """Sweep all tracked categories for stalled processes."""
    try:
        from engine.system import get_process_monitor

        mon = get_process_monitor()
        stalls = mon.stall_detection()
        if stalls:
            logger.warning(
                "Detected %d stalled processes: %s",
                len(stalls),
                ", ".join(
                    f"{s.process.name}(PID {s.process.pid})" for s in stalls
                ),
            )
        return {
            "stalled_count": len(stalls),
            "stalls": [
                {
                    "pid": s.process.pid,
                    "name": s.process.name,
                    "category": s.process.category.value if s.process.category else "unknown",
                    "cpu_seconds": round(s.process.cpu_seconds, 1),
                    "memory_mb": round(s.process.memory_mb, 1),
                    "reason": s.reason,
                }
                for s in stalls
            ],
        }
    except Exception as exc:
        logger.error("Stall detection sweep failed: %s", exc)
        return {"error": str(exc)}


# ── Workspace Pipeline Callbacks ──────────────────────────────────────────────


def _workspace_news_pipeline_callback() -> Dict[str, Any]:
    """Run the workspace news_pipeline template: fetch RSS → NLM → Sheets → Nexus."""
    try:
        from engine.nexus.workspace_pipeline import get_workspace_pipeline

        pipeline = get_workspace_pipeline()
        run = pipeline.run(
            "news_pipeline",
            topic="Latest AI & Technology News",
            categories=["ai_research", "tech"],
            max_articles=30,
            store_articles=True,
        )

        result: Dict[str, Any] = {
            "run_id": run.run_id,
            "pipeline": run.pipeline_name,
            "status": run.status.value,
            "stages_completed": len([s for s in run.stages if s.get("status") == "completed"]),
            "stages_total": len(run.stages),
        }

        if run.final_output:
            result["articles_fetched"] = run.final_output.get("articles_fetched", 0)
            result["articles_stored"] = run.final_output.get("stored", 0)

        # Store pipeline run summary in Nexus
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            client.add_entry(
                title=f"News Pipeline Run: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                content=json.dumps(result, default=str),
                content_type="history",
                category="news",
            )
        except Exception:
            pass

        return result
    except Exception as exc:
        logger.error("Workspace news pipeline failed: %s", exc)
        return {"error": str(exc)}


def _workspace_news_to_knowledge_callback() -> Dict[str, Any]:
    """Run the news_to_knowledge pipeline: fetch → NLM → Docs → Drive → Nexus."""
    try:
        from engine.nexus.workspace_pipeline import get_workspace_pipeline

        pipeline = get_workspace_pipeline()
        run = pipeline.run(
            "news_to_knowledge",
            topic="Daily Knowledge Distillation",
            categories=["ai_research", "science"],
            max_articles=15,
            store_articles=True,
        )

        result: Dict[str, Any] = {
            "run_id": run.run_id,
            "pipeline": run.pipeline_name,
            "status": run.status.value,
            "stages_completed": len([s for s in run.stages if s.get("status") == "completed"]),
            "stages_total": len(run.stages),
        }
        if run.final_output:
            result["doc_id"] = run.final_output.get("doc_id")
            result["drive_file_id"] = run.final_output.get("file_id")

        return result
    except Exception as exc:
        logger.error("News-to-knowledge pipeline failed: %s", exc)
        return {"error": str(exc)}


def _workspace_research_cycle_callback() -> Dict[str, Any]:
    """Run research_and_distill for queued topics from Nexus."""
    try:
        from engine.nexus.workspace_pipeline import get_workspace_pipeline
        from engine.nexus.client import get_nexus_client

        pipeline = get_workspace_pipeline()
        client = get_nexus_client()

        # Look for pending research topics in Nexus
        topics_to_research: list = []
        try:
            search_result = client.search("research_queue pending")
            if search_result and isinstance(search_result, list):
                for entry in search_result[:3]:
                    if isinstance(entry, dict):
                        topics_to_research.append(
                            entry.get("title", "").replace("research_queue: ", "")
                        )
        except Exception:
            pass

        # Fallback to default topics if nothing queued
        if not topics_to_research:
            topics_to_research = ["latest AI agent frameworks and tool calling"]

        results = []
        for topic in topics_to_research[:3]:
            try:
                run = pipeline.run("research_and_distill", topic=topic)
                results.append({
                    "topic": topic,
                    "run_id": run.run_id,
                    "status": run.status.value,
                })
            except Exception as exc:
                results.append({"topic": topic, "error": str(exc)})

        return {
            "topics_processed": len(results),
            "results": results,
        }
    except Exception as exc:
        logger.error("Research cycle failed: %s", exc)
        return {"error": str(exc)}


def _workspace_pipeline_health_callback() -> Dict[str, Any]:
    """Check workspace pipeline stage connectivity and client availability."""
    try:
        from engine.nexus.workspace_pipeline import (
            PIPELINE_TEMPLATES,
            STAGE_REGISTRY,
            get_workspace_pipeline,
        )

        pipeline = get_workspace_pipeline()
        health: Dict[str, Any] = {
            "stages_registered": len(STAGE_REGISTRY),
            "templates_available": len(PIPELINE_TEMPLATES),
            "template_names": list(PIPELINE_TEMPLATES.keys()),
            "clients": {},
        }

        # Check each client's availability
        client_checks = {
            "workspace_gemini": "engine.integrations.workspace_gemini_client.get_workspace_gemini_client",
            "sheets": "engine.integrations.gsheets_client.get_sheets_client",
            "docs": "engine.integrations.google_docs_client.get_docs_client",
            "drive": "engine.integrations.google_drive_client.get_drive_client",
            "nlm": "engine.integrations.nlm_direct_client.get_nlm_client",
            "nexus": "engine.nexus.client.get_nexus_client",
        }
        for client_name, import_path in client_checks.items():
            try:
                module_path, func_name = import_path.rsplit(".", 1)
                import importlib
                mod = importlib.import_module(module_path)
                getter = getattr(mod, func_name)
                obj = getter()
                health["clients"][client_name] = obj is not None
            except Exception:
                health["clients"][client_name] = False

        # Check recent pipeline runs
        runs = pipeline.list_runs()
        health["recent_runs"] = len(runs)
        if runs:
            latest = runs[-1]
            health["latest_run"] = {
                "id": latest.get("run_id"),
                "pipeline": latest.get("pipeline_name"),
                "status": latest.get("status"),
            }

        # Store health snapshot in Nexus
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            client.add_entry(
                title=f"Pipeline Health: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                content=json.dumps(health, default=str),
                content_type="note",
                category="system",
            )
        except Exception:
            pass

        return health
    except Exception as exc:
        logger.error("Pipeline health check failed: %s", exc)
        return {"error": str(exc)}


def _benchmark_flush_callback() -> Dict[str, Any]:
    """Flush in-memory benchmark data to MetaMetrics SQLite persistence."""
    try:
        from engine.logging.benchmark import flush_to_meta_metrics

        flushed = flush_to_meta_metrics(clear=False)
        return {
            "metrics_flushed": len(flushed),
            "details": {k: round(v, 2) for k, v in flushed.items()},
        }
    except Exception as exc:
        logger.error("Benchmark flush failed: %s", exc)
        return {"error": str(exc)}


def _copilot_auto_repair_callback() -> Dict[str, Any]:
    """Detect Copilot drift and auto-repair via CopilotSelfConfig sync."""
    try:
        from engine.nexus.copilot_validation import auto_repair

        result = auto_repair()

        # Store repair report in Nexus
        if result.get("actions"):
            try:
                from engine.nexus.client import get_nexus_client

                client = get_nexus_client()
                client.add_entry(
                    title=(
                        f"Copilot Auto-Repair: "
                        f"{result.get('before_issues', '?')} → "
                        f"{result.get('after_issues', '?')} issues"
                    ),
                    content=json.dumps(result, default=str),
                    content_type="history",
                    category="system",
                )
            except Exception:
                pass

        return {
            "before_issues": result.get("before_issues", 0),
            "after_issues": result.get("after_issues", 0),
            "repaired": result.get("repaired", False),
            "actions": result.get("actions", []),
            "message": result.get("message", ""),
        }
    except Exception as exc:
        logger.error("Copilot auto-repair failed: %s", exc)
        return {"error": str(exc)}


def _cdp_mine_callback() -> Dict[str, Any]:
    """Daily: mine CDP monitor logs for browser_debugger + error_classifier training data."""
    try:
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "scripts/cdp_data_miner.py", "run"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {"status": "error", "stderr": result.stderr[:500]}
        # Also trigger DataCollector flush for the two new types
        from training.data_collector import get_data_collector
        collector = get_data_collector()
        flushed_d = collector.flush("browser_debugger")
        flushed_c = collector.flush("error_classifier")
        return {
            "status":   "ok",
            "stdout":   result.stdout[:500],
            "flushed":  {"browser_debugger": flushed_d, "error_classifier": flushed_c},
        }
    except Exception as exc:
        logger.error("cdp_mine failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _cookie_health_check_callback() -> Dict[str, Any]:
    """Daily: probe Google account pool, log stale accounts, store result in Nexus."""
    try:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "scripts/har_watchfolder.py", "health"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {"status": "error", "stderr": result.stderr[:300]}

        import json as _json
        try:
            report = _json.loads(result.stdout)
        except Exception:
            return {"status": "error", "parse_error": result.stdout[:200]}

        stale = report.get("stale_count", 0)
        total = report.get("total", 0)
        healthy = report.get("healthy_count", 0)

        if stale:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            stale_names = [a["name"] for a in report.get("accounts", []) if a.get("stale")]
            client.add_entry(
                f"Cookie Health Alert: {stale} stale account(s)",
                (
                    f"Daily cookie health check found {stale}/{total} accounts with stale cookies.\n"
                    f"Stale accounts: {', '.join(stale_names)}\n\n"
                    "Action required: export a fresh HAR from Chrome and drop it into data/hars/\n"
                    "The HAR watchfolder will auto-import it within 30 seconds.\n\n"
                    "How to capture HAR:\n"
                    "  1. Open notebooklm.google.com in Chrome\n"
                    "  2. DevTools (F12) → Network tab\n"
                    "  3. Interact with the page\n"
                    "  4. Right-click any request → Save all as HAR\n"
                    "  5. Save to data/hars/<account_name>.har"
                ),
                content_type="note",
                category="system",
            )
            logger.warning("cookie_health_check: %d stale accounts: %s", stale, stale_names)

        return {
            "status": "ok",
            "total": total,
            "healthy": healthy,
            "stale": stale,
            "accounts": report.get("accounts", []),
        }
    except Exception as exc:
        logger.error("cookie_health_check failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _cookie_auto_refresh_callback() -> Dict[str, Any]:
    """Every 3 days: silently refresh Google cookies via CDP from running Chrome.

    Prefers the ARGUS token harvester (python -m scripts.argus.tools tokens)
    which uses direct CDP cookie extraction and is faster/more reliable.
    Falls back to har_capture.py --mode auto if ARGUS tools are unavailable.
    Logs outcome to Nexus.
    """
    import subprocess
    import sys
    import time as _time

    repo_root = str(Path(__file__).parent.parent.parent)

    # Try ARGUS token harvester first (preferred path)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.argus.tools", "tokens"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_root,
        )
        success = result.returncode == 0
        stdout = result.stdout[-800:] if result.stdout else ""
        stderr = result.stderr[-400:] if result.stderr else ""
        method = "argus-token-harvester"
    except Exception:
        # Fallback to har_capture.py
        result = subprocess.run(
            [sys.executable, "scripts/har_capture.py", "--mode", "auto"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=repo_root,
        )
        success = result.returncode == 0
        stdout = result.stdout[-800:] if result.stdout else ""
        stderr = result.stderr[-400:] if result.stderr else ""
        method = "har-capture-fallback"

    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_entry(
            f"Cookie Auto-Refresh: {'success' if success else 'failed'} — {_time.strftime('%Y-%m-%d %H:%M')}",
            f"Scheduled cookie refresh via {method}.\n\nOutput:\n{stdout}\n{stderr}",
            content_type="note",
            category="system",
            tags=["cookie-refresh", "scheduled", "cdp"],
        )
    except Exception as nexus_exc:
        logger.warning("cookie_auto_refresh: nexus log failed: %s", nexus_exc)

    if success:
        logger.info("cookie_auto_refresh: success via %s", method)
    else:
        logger.warning("cookie_auto_refresh: failed via %s — %s", method, stderr[:200])

    return {"status": "ok" if success else "error", "method": method, "stdout": stdout, "stderr": stderr}


def _test_suite_benchmark_callback() -> Dict[str, Any]:
    """Weekly: time the full pytest suite and store trend data in Nexus.

    Uses test_timer.py to run and parse the full suite, then stores the result
    in Nexus with category='testing' so trends are queryable over time.
    Logs a warning if the suite duration regressed by >20% vs the prior run.
    """
    import subprocess
    import sys
    import json as _json
    import time as _time
    from pathlib import Path as _Path

    root = _Path(__file__).parent.parent.parent
    history_file = root / "logs" / "test_timings" / "history.jsonl"

    try:
        # Run the test suite via test_timer so results land in history.jsonl
        result = subprocess.run(
            [sys.executable, "scripts/test_timer.py", "run", "--label", "scheduled-weekly"],
            capture_output=True,
            text=True,
            timeout=1800,  # 30-minute hard cap
            cwd=str(root),
        )

        # Read the last record from history.jsonl
        record: Dict[str, Any] = {}
        if history_file.exists():
            lines = [l for l in history_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            if lines:
                record = _json.loads(lines[-1])

        duration_s = record.get("duration", 0)
        passed = record.get("stats", {}).get("passed", 0)
        failed = record.get("stats", {}).get("failed", 0)

        # Regression check: compare with the run before this one
        regression_warning = ""
        if len(lines) >= 2:
            prev = _json.loads(lines[-2])
            prev_dur = prev.get("duration", duration_s)
            if prev_dur > 0 and duration_s > prev_dur * 1.20:
                pct = int((duration_s / prev_dur - 1) * 100)
                regression_warning = f"⚠️ Suite time regressed +{pct}% ({prev_dur:.0f}s → {duration_s:.0f}s)"
                logger.warning("test_suite_benchmark: %s", regression_warning)

        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_entry(
            f"Test Suite Benchmark — {_time.strftime('%Y-%m-%d')} — {_fmt_duration(duration_s)}",
            (
                f"Scheduled weekly test suite run.\n\n"
                f"Duration : {_fmt_duration(duration_s)}\n"
                f"Passed   : {passed}\n"
                f"Failed   : {failed}\n"
                f"{regression_warning}\n\n"
                f"Full record:\n{_json.dumps(record, indent=2)}"
            ),
            content_type="note",
            category="testing",
            tags=["test-benchmark", "pytest", "scheduled"],
        )

        return {
            "status": "ok",
            "duration_s": duration_s,
            "passed": passed,
            "failed": failed,
            "regression": regression_warning,
        }
    except Exception as exc:
        logger.error("test_suite_benchmark failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _fmt_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


def _argus_weekly_scan_callback() -> Dict[str, Any]:
    """Weekly: run full ARGUS scan (NLM + Gemini + AI Studio) via Playwright + CDP.

    Requires Chrome to be running with ``--remote-debugging-port=9223``
    and the user to be logged into Google services.
    On success, stores discoveries in Nexus and regenerates API reference docs.
    """
    import asyncio
    try:
        from scripts.argus.orchestrator import ArgusOrchestrator
    except ImportError:
        return {"status": "skipped", "reason": "ARGUS not installed — run: pip install playwright"}

    try:
        orchestrator = ArgusOrchestrator()
        results = asyncio.run(orchestrator.run_full_scan())
        total_new = sum(r.total_new for r in results)
        errors = [r.error for r in results if r.error]
        return {
            "status": "ok" if not errors else "partial",
            "total_new_discoveries": total_new,
            "targets_scanned": [r.target for r in results],
            "errors": errors,
        }
    except Exception as exc:
        logger.error("argus_weekly_scan failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _argus_diff_report_callback() -> Dict[str, Any]:
    """Weekly: compare current ARGUS registry vs previous scan, store delta in Nexus."""
    try:
        from scripts.argus.discovery.endpoint_registry import get_registry
        from scripts.argus.reporting.api_doc_generator import DiffReporter
        from scripts.argus.nexus_sink import get_sink

        registry = get_registry()
        diff_result = registry.diff_vs_baseline()
        total_new = sum(len(v) for v in diff_result.values() if isinstance(v, list) and "unseen" not in "".join(k for k in diff_result))

        # Generate human-readable diff report
        lines = [
            "# ARGUS Diff Report (vs Baseline)",
            "",
            f"Generated: {__import__('time').strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        for key, items in diff_result.items():
            if items:
                lines.append(f"## {key} ({len(items)})")
                for item in items:
                    lines.append(f"- `{item}`")
                lines.append("")

        report = "\n".join(lines)
        get_sink().store_diff_report(report)
        stats = registry.get_stats()

        return {
            "status": "ok",
            "stats": stats,
            "diff": diff_result,
        }
    except Exception as exc:
        logger.error("argus_diff_report failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _argus_nlm_distil_callback() -> Dict[str, Any]:
    """Weekly: upload ARGUS discovery document to NotebookLM, distil API Q&A into Nexus."""
    try:
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        result = ArgusNLMPipeline().run(target="all")
        return {
            "status": "ok",
            "total_qa": result.get("total_qa", 0),
            "total_stored": result.get("total_stored", 0),
            "targets": result.get("targets", []),
        }
    except Exception as exc:
        logger.error("argus_nlm_distil failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _colab_pipeline_sync_callback() -> Dict[str, Any]:
    """Daily at 04:00: NLM→Drive→Colab analysis pipeline for improvement entries.

    For each pending Nexus entry with category="improvement":
      1. Asks NLM to suggest improvements via nlm_direct_client.
      2. Uploads suggestions to Drive.
      3. Builds a Colab analysis notebook via ColabNotebookBuilder.
      4. Stores the Colab output back in Nexus.
    """
    processed = 0
    errors = 0
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()

        results = client.search("category:improvement", limit=20)
        entries = results if isinstance(results, list) else results.get("results", [])

        if not entries:
            return {"status": "ok", "processed": 0, "note": "no improvement entries"}

        # Lazy imports — services may not be configured
        try:
            from engine.integrations.nlm_direct_client import get_nlm_direct_client
            nlm = get_nlm_direct_client()
        except Exception:
            nlm = None

        try:
            from engine.integrations.colab_notebook_builder import get_notebook_builder
            builder = get_notebook_builder()
        except Exception:
            builder = None

        for entry in entries[:10]:
            try:
                content = entry.get("content", entry.get("text", ""))
                if not content:
                    continue

                # Step 1: NLM suggestions
                suggestion = ""
                if nlm:
                    try:
                        suggestion = nlm.ask_simple(
                            f"Suggest specific improvements for this AI response:\n{content[:400]}"
                        )
                    except Exception as exc:
                        logger.debug("NLM suggestion failed: %s", exc)

                # Step 2 + 3: Colab analysis
                if builder:
                    try:
                        context = f"Entry:\n{content[:800]}\n\nSuggestions:\n{suggestion[:400]}"
                        execution = builder.build_and_run(
                            task_description=(
                                "Analyze this AI response quality entry and produce a "
                                "structured improvement report with metrics."
                            ),
                            initial_context=context,
                            save_to_drive=True,
                            save_to_nexus=False,
                        )
                        # Step 4: store Colab output in Nexus
                        if execution.total_output:
                            client.add_entry(
                                title=f"Colab Improvement Analysis: {entry.get('title', 'entry')[:60]}",
                                content=execution.total_output[:2000],
                                content_type="note",
                                category="training",
                            )
                    except Exception as exc:
                        logger.warning("Colab analysis failed for entry: %s", exc)

                processed += 1
            except Exception as exc:
                logger.warning("colab-pipeline-sync entry error: %s", exc)
                errors += 1

    except Exception as exc:
        logger.error("colab_pipeline_sync_callback failed: %s", exc)
        return {"status": "error", "error": str(exc), "processed": processed}

    return {"status": "ok", "processed": processed, "errors": errors}


def _news_distill_nlm_callback() -> Dict[str, Any]:
    """Every hour: distill news articles into Nexus Q&A via NotebookLM notebooks.

    Per distillation super-category (ai_research/tech/world/science):
    - Looks up which YAML source categories map to this super-category
    - Fetches latest news items from Nexus for ALL mapped source categories
    - Adds article summaries as a text source to the NLM notebook
    - Asks targeted questions (from YAML config) via NLM (Gemini-backed)
    - Stores Q&A pairs in Nexus under category='news'
    """
    from engine.nexus.news_sources import get_news_registry
    registry = get_news_registry()

    # Load distillation config from YAML
    super_cats = registry.get_distillation_categories()
    if not super_cats:
        return {"status": "skipped", "reason": "No distillation super_categories in YAML config"}

    total_qa = 0
    errors: List[str] = []

    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
    except Exception as exc:
        return {"status": "skipped", "reason": f"Nexus unavailable: {exc}"}

    try:
        from engine.nexus.nlm_engine import get_nlm_engine
        nlm = get_nlm_engine()
        nlm_available = True
    except Exception:
        nlm_available = False

    for cat in super_cats:
        notebook_id = registry.get_nlm_notebook_id(cat)
        if not notebook_id:
            errors.append(f"{cat}: no NLM notebook ID configured")
            continue

        # Validate NLM notebook exists before expensive operations
        if nlm_available:
            try:
                nb_list = nlm.list_notebooks() or []
                nb_ids = {nb.get("id", "") for nb in nb_list if isinstance(nb, dict)}
                if notebook_id not in nb_ids:
                    logger.warning(
                        "NLM notebook %s for super-category '%s' not found "
                        "(%d notebooks visible) — skipping distillation",
                        notebook_id,
                        cat,
                        len(nb_ids),
                    )
                    errors.append(f"{cat}: notebook {notebook_id[:12]}… not found")
                    continue
            except Exception as exc:
                logger.debug(
                    "NLM notebook validation failed for '%s': %s — proceeding anyway",
                    cat,
                    exc,
                )

        try:
            # Find all YAML source categories that map to this super-category
            source_cats = registry.get_source_categories_for_super(cat)

            # Fetch recent news items from Nexus for ALL mapped source categories
            summaries: List[str] = []
            for src_cat in source_cats:
                results = client.search(f"news {src_cat}", limit=6)
                for item in results[:4]:
                    title = item.get("title", "Untitled")
                    content = item.get("content", "")[:500]
                    summaries.append(f"## {title}\n{content}")

            # Also search by super-category name (catches items stored under old names)
            if cat not in source_cats:
                fallback_results = client.search(f"news {cat}", limit=6)
                for item in fallback_results[:3]:
                    title = item.get("title", "Untitled")
                    content = item.get("content", "")[:500]
                    summaries.append(f"## {title}\n{content}")

            questions = registry.get_distillation_questions(cat)

            if nlm_available and summaries:
                # Inject article digest as a new text source into the notebook
                digest = (
                    f"# News Digest: {cat.upper()} — "
                    f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}\n\n"
                )
                digest += "\n\n---\n\n".join(summaries)
                try:
                    nlm.add_source(notebook_id, "text", digest)
                except Exception:
                    pass  # proceed to ask even if source injection fails

            # Ask questions via NLM or fall back to nexus_ask
            for q in questions:
                try:
                    if nlm_available:
                        resp = nlm.ask(notebook_id, q)
                        ans_text = resp.get("answer", "") if isinstance(resp, dict) else str(resp)
                    else:
                        ctx = "\n\n".join(summaries)[:800] if summaries else ""
                        resp = client.ask(f"{q}\n\nContext:\n{ctx}" if ctx else q)
                        ans_text = resp.get("answer", "") if isinstance(resp, dict) else str(resp)

                    if ans_text and len(ans_text) > 30:
                        client.add_qa(q, ans_text, category="news")
                        total_qa += 1
                except Exception:
                    pass

        except Exception as exc:
            errors.append(f"{cat}: {exc}")

    result: Dict[str, Any] = {
        "status": "ok",
        "qa_pairs_stored": total_qa,
        "nlm_used": nlm_available,
        "categories": super_cats,
    }
    if errors:
        result["errors"] = errors
    logger.info(
        "news_distill_nlm: stored %d Q&A pairs via %s (errors: %s)",
        total_qa,
        "NLM" if nlm_available else "nexus_ask fallback",
        errors or "none",
    )
    return result


def _feed_health_callback() -> Dict[str, Any]:
    """Every 12h: probe all RSS feeds and report dead/tripped sources."""
    try:
        from engine.nexus.news.rss_fetcher import RSSFetcher
        fetcher = RSSFetcher(rate_limit_seconds=0.5, timeout=5, max_retries=1)
        report = fetcher.check_all_feeds()
        return {"status": "ok", **report}
    except Exception as exc:
        logger.error("feed_health_callback failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _npc_world_tick_callback() -> Dict[str, Any]:
    """Every minute: drive NPC autonomous activity via NPCScheduler."""
    try:
        from engine.agents.npc_scheduler import get_npc_scheduler
        get_npc_scheduler().tick()
        return {"status": "ok"}
    except Exception as exc:
        logger.debug("npc_world_tick skipped: %s", exc)
        return {"status": "skipped", "reason": str(exc)}


def _world_sim_tick_callback() -> Dict[str, Any]:
    """Every 5 min: advance world simulation time by one sim-hour."""
    try:
        from engine.world.world_sim import get_world_sim
        sim = get_world_sim()
        if not sim.is_running:
            sim.start()
        return {"status": "ok", "running": sim.is_running}
    except Exception as exc:
        logger.debug("world_sim_tick skipped: %s", exc)
        return {"status": "skipped", "reason": str(exc)}


def _director_tick_callback() -> Dict[str, Any]:
    """Every 15 min: advance scene director narrative beats."""
    try:
        from engine.scenes.scene_director import get_scene_director
        director = get_scene_director()
        director.tick()
        return {"status": "ok"}
    except Exception as exc:
        logger.debug("director_tick skipped: %s", exc)
        return {"status": "skipped", "reason": str(exc)}


def _content_refresh_callback() -> Dict[str, Any]:
    """Every 6 hours: trigger NLM refills for depleted content pools."""
    try:
        from engine.content.content_engine import get_content_engine
        engine = get_content_engine()
        results = engine.refresh_pools()
        total = sum(results.values())
        logger.info("content_refresh: added %d items across %d pools", total, len(results))
        return {"status": "ok", "pools_refilled": len(results), "items_added": total}
    except Exception as exc:
        logger.debug("content_refresh skipped: %s", exc)
        return {"status": "skipped", "reason": str(exc)}


def _nlm_content_seed_callback() -> Dict[str, Any]:
    """Weekly: deep-seed all scene pools + director beat instructions via NLM."""
    try:
        from engine.content.nlm_generator import get_nlm_generator
        gen = get_nlm_generator()
        results = gen.seed_all_scenes(intensity=2, beat_count=3, content_count=5)
        totals = results.get("_totals", {"beats": 0, "content": 0})
        logger.info(
            "nlm_content_seed: %d beats + %d content items across %d scenes",
            totals["beats"], totals["content"], len(results) - 1,
        )
        return {"status": "ok", **totals, "scenes": len(results) - 1}
    except Exception as exc:
        logger.debug("nlm_content_seed skipped: %s", exc)
        return {"status": "skipped", "reason": str(exc)}


def _scene_lore_seed_callback() -> Dict[str, Any]:
    """Weekly: generate world lore entries for all scenes via NLM."""
    try:
        from engine.content.nlm_generator import get_nlm_generator
        gen = get_nlm_generator()
        results = gen.seed_lore_all_scenes(lore_count=10)
        total = sum(v for k, v in results.items() if k != "_totals")
        return {"status": "ok", "scenes": len(results), "lore_entries": total}
    except Exception as exc:
        logger.debug("scene_lore_seed skipped: %s", exc)
        return {"status": "skipped", "reason": str(exc)}


def _daily_challenge_seed_callback() -> Dict[str, Any]:
    """Daily: pre-generate challenges for all 9 scenes and store in Nexus."""
    try:
        from engine.nexus.daily_challenge import get_daily_challenge_manager
        mgr = get_daily_challenge_manager()
        results = mgr.seed_all()
        return {"status": "ok", "scenes": len(results), "challenges": results}
    except Exception as exc:
        logger.error("daily_challenge_seed failed: %s", exc)
        return {"error": str(exc)}


def _qa_history_mine_callback() -> Dict[str, Any]:
    """Weekly: run the full NLM-driven QA cache generation pipeline.

    Mines 164 checkpoints from session history, uploads to NLM notebooks,
    generates Q&A pairs via quota-free Studio tiles (flashcards, quiz,
    custom report), self-evaluates with Gemini 3.0, and stores approved
    pairs in the Nexus Q&A cache.

    Expected: +500-1000 net new pairs per cycle.
    """
    try:
        from engine.nexus.cache_pipeline import get_cache_pipeline
        pipeline = get_cache_pipeline()
        result = pipeline.run_full_cycle()
        return {
            "stored": result.stored,
            "direct_seeded": result.direct_seeded,
            "essential": result.essential,
            "useful": result.useful,
            "skipped": result.skipped,
            "gaps": len(result.gaps),
            "duration_s": result.duration_s,
            "errors": result.errors,
        }
    except Exception as exc:
        logger.error("QA history mine callback failed: %s", exc)
        return {"error": str(exc)}


def _qa_cache_prune_callback() -> Dict[str, Any]:
    """Weekly: remove Q&A cache entries that have never been accessed.

    Pairs that have been in the cache for 30+ days with zero hits are
    removed to keep the cache lean and the hit rate meaningful.
    """
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        if not client or not client.is_available():
            return {"error": "Nexus unavailable"}

        # Fetch Q&A pairs, remove stale ones (zero-hit + older than 30 days)
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        pruned = 0
        try:
            qa_list = client.list_entries(
                content_type="qa",
                limit=2000,
            ) or []
            for entry in qa_list:
                if not isinstance(entry, dict):
                    continue
                hits = entry.get("hits", entry.get("access_count", 1))
                created = entry.get("created_at", "")
                if hits == 0 and created and created < cutoff:
                    entry_id = entry.get("id", "")
                    if entry_id:
                        try:
                            client.delete_entry(entry_id)
                            pruned += 1
                        except Exception:
                            pass
        except Exception as exc:
            logger.warning("QA prune: error during pruning: %s", exc)

        logger.info("QA cache pruned: %d stale entries removed", pruned)
        return {"pruned": pruned}
    except Exception as exc:
        logger.error("QA cache prune callback failed: %s", exc)
        return {"error": str(exc)}


def _qa_expansion_callback() -> Dict[str, Any]:
    """Daily batch expansion: reverse-generates Q&A pairs from Nexus entries.

    Processes 20 entries per run, accumulating toward the 3,000+ pair target.
    """
    try:
        from engine.nexus.qa_expander import run_qa_expansion
        return run_qa_expansion(batch_size=20)
    except Exception as exc:
        logger.error("QA expansion callback failed: %s", exc)
        return {"error": str(exc)}


def _master_notebook_refresh_callback() -> Dict[str, Any]:
    """Weekly refresh of the CosySim Master Intelligence notebook.

    Re-uploads all source bundles (picking up code changes) and
    runs a fresh Q&A distillation pass to capture new knowledge.
    """
    try:
        from engine.nexus.master_notebook_builder import refresh_master_notebook
        return refresh_master_notebook()
    except Exception as exc:
        logger.error("Master notebook refresh failed: %s", exc)
        return {"error": str(exc)}


def _router_data_export_callback() -> Dict[str, Any]:
    """Every 4 hours: export RouterDataCollector decisions to JSONL training file.

    Reads accumulated router decisions and appends them to the training
    datasets directory in Alpaca JSONL format for the router-v3 model.
    """
    try:
        from engine.lmstudio.router_data import get_router_data_collector
        collector = get_router_data_collector()

        # Flush any buffered records first
        collector.flush()

        export_dir = Path(_REPO_ROOT) / "training" / "datasets"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / "router_v3_incremental.jsonl"

        stats = collector.get_stats()
        total = stats.get("total_records", 0)
        if total == 0:
            return {"status": "ok", "exported": 0, "message": "no records"}

        written = collector.export_jsonl(str(export_path))
        logger.info("router_data_export: wrote %d records to %s", written, export_path.name)
        return {"status": "ok", "exported": written, "path": str(export_path)}
    except Exception as exc:
        logger.debug("router_data_export skipped: %s", exc)
        return {"status": "skipped", "reason": str(exc)}


def _router_v3_retrain_callback() -> Dict[str, Any]:
    """Weekly: trigger a full Router v3 retrain cycle.

    Flow:
    1. Accumulate all JSONL shards into one dataset
    2. Launch fine-tuning subprocess (same script as training/models/router_v3*)
    3. Evaluate new model vs current active — compare routing accuracy
    4. Promote new model by updating model_registry.json if improved

    Returns a summary dict that is stored in Nexus for tracking.
    """
    try:
        import subprocess
        registry_path = Path(_REPO_ROOT) / "training" / "model_registry.json"
        dataset_dir = Path(_REPO_ROOT) / "training" / "datasets"
        train_script = Path(_REPO_ROOT) / "training" / "scripts" / "train_router_v3.py"

        if not train_script.exists():
            return {"status": "skipped", "reason": "train script not found"}

        # Merge all router JSONL shards
        merged_path = dataset_dir / "router_v3_merged.jsonl"
        shards = list(dataset_dir.glob("router_v3*.jsonl"))
        if not shards:
            return {"status": "skipped", "reason": "no training data"}

        total_examples = 0
        with open(merged_path, "w", encoding="utf-8") as out:
            for shard in shards:
                for line in shard.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        out.write(line + "\n")
                        total_examples += 1

        if total_examples < 100:
            return {
                "status": "skipped",
                "reason": f"insufficient data ({total_examples} < 100 examples)",
            }

        # Launch fine-tune subprocess (non-blocking, returns PID)
        result = subprocess.Popen(
            ["python", str(train_script), "--dataset", str(merged_path)],
            cwd=str(_REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info(
            "router_v3_retrain: launched training PID=%d with %d examples",
            result.pid,
            total_examples,
        )

        # Store launch record in Nexus
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            if client and client.is_available():
                client.add_entry(
                    f"Router v3 Retrain — {total_examples} examples",
                    json.dumps({
                        "pid": result.pid,
                        "examples": total_examples,
                        "shards": [s.name for s in shards],
                    }),
                    content_type="note",
                    category="training",
                )
        except Exception:
            pass

        return {
            "status": "ok",
            "pid": result.pid,
            "examples": total_examples,
            "shards": len(shards),
        }
    except Exception as exc:
        logger.debug("router_v3_retrain skipped: %s", exc)
        return {"status": "skipped", "reason": str(exc)}


def _collect_flush_callback() -> Dict[str, Any]:
    """Every 4h: flush DataCollector live files into training datasets."""
    try:
        from training.data_collector import get_data_collector
        collector = get_data_collector()
        total = collector.flush_all()
        return {"status": "ok", "records_flushed": total}
    except Exception as exc:
        logger.error("collect_flush failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _model_zoo_train_callback() -> Dict[str, Any]:
    """Daily: check MODEL_ZOO thresholds and submit finetune jobs for ready types."""
    try:
        from training.auto_train import check_and_train_all_zoo
        results = check_and_train_all_zoo()
        submitted = sum(1 for v in results.values() if v.get("action") == "submitted")
        return {"status": "ok", "submitted": submitted, "details": results}
    except Exception as exc:
        logger.error("model_zoo_train failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _voice_auto_train_callback() -> Dict[str, Any]:
    """Weekly: train Piper/Qwen3/Orpheus from collected voice samples."""
    try:
        from training.voice_trainer import get_voice_trainer
        results = get_voice_trainer().auto_train_all()
        succeeded = sum(1 for r in results if r.success)
        return {"status": "ok", "trained": succeeded, "total": len(results)}
    except Exception as exc:
        logger.error("voice_auto_train failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _coder_dataset_refresh_callback() -> Dict[str, Any]:
    """Weekly coder dataset refresh — re-scans codebase + Nexus Q&A + flushes collected."""
    try:
        from training.coder_pipeline import get_coder_pipeline
        pipeline = get_coder_pipeline()
        count = pipeline.refresh_dataset()
        return {"status": "ok", "examples": count}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _improvement_review_callback() -> Dict[str, Any]:
    """Weekly output improvement review.

    Fetches low-quality responses stored in Nexus (category=improvement),
    batch-asks NLM notebook for improvement suggestions, and stores the
    NLM answers as output_evaluator training examples.

    Returns:
        Dict with status, reviewed count, and stored count.
    """
    reviewed = 0
    stored = 0
    try:
        from engine.nexus.client import get_nexus_client
        from training.data_collector import get_data_collector

        client = get_nexus_client()
        collector = get_data_collector()

        results = client.search("category:improvement", limit=100)
        entries = results if isinstance(results, list) else results.get("results", [])

        if not entries:
            return {"status": "ok", "reviewed": 0, "stored": 0, "note": "no improvement entries found"}

        # Build batch questions for NLM review
        questions: List[str] = []
        texts: List[str] = []
        for entry in entries[:50]:
            content = entry.get("content", entry.get("text", ""))
            if not content:
                continue
            texts.append(content[:400])
            questions.append(
                f"How could this AI response be improved to be more helpful, coherent, and complete?\n\n{content[:400]}"
            )

        # Try NLM batch-ask for improvement suggestions
        try:
            from engine.nexus.nlm_engine import get_nlm_engine
            nlm = get_nlm_engine()
            for i, (question, original) in enumerate(zip(questions, texts)):
                try:
                    answer = nlm.ask(question, notebook_id=None, timeout=30)
                    if answer and len(answer) > 20:
                        collector.collect_output_rating(
                            output=original,
                            rating=0.6,
                            context=f"NLM improvement review #{i}: {answer[:200]}",
                            source="improvement_review",
                        )
                        stored += 1
                    reviewed += 1
                except Exception:
                    reviewed += 1
        except Exception as nlm_err:
            logger.debug("NLM unavailable for improvement review: %s", nlm_err)
            # Fallback: store raw entries as low-quality training signal
            for text in texts:
                collector.collect_output_rating(
                    output=text,
                    rating=0.3,
                    context="improvement_review_fallback",
                    source="improvement_review",
                )
                stored += 1
                reviewed += 1

        return {"status": "ok", "reviewed": reviewed, "stored": stored}

    except Exception as e:
        logger.error("_improvement_review_callback failed: %s", e)
        return {"status": "error", "error": str(e), "reviewed": reviewed, "stored": stored}


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


def _teacher_dataset_gen_callback() -> Dict[str, Any]:
    """Weekly: generate NLM teacher datasets for all micro-model types."""
    results: Dict[str, Any] = {}
    try:
        from engine.nexus.teacher_pipeline import get_teacher_pipeline
        pipeline = get_teacher_pipeline()
        for model_type in ["qa_evaluator", "router_v2", "syntax_fixer", "conversation_analyzer", "knowledge_synthesizer"]:
            try:
                result = pipeline.generate_dataset(model_type, count=300)
                results[model_type] = {
                    "generated": result.count_generated,
                    "path": result.dataset_path,
                    "errors": result.errors,
                }
            except Exception as exc:
                results[model_type] = {"error": str(exc)}
    except Exception as exc:
        return {"error": str(exc)}
    return {"datasets": results, "timestamp": datetime.now(timezone.utc).isoformat()}


def _finetune_if_ready_callback() -> Dict[str, Any]:
    """Weekly: submit fine-tune jobs if any dataset has grown 500+ examples."""
    submitted: List[str] = []
    skipped: List[str] = []
    try:
        from training.micro_datasets import MicroDatasetManager, MODELS
        from training.finetune_orchestrator import get_finetune_orchestrator
        mgr = MicroDatasetManager()
        orch = get_finetune_orchestrator()
        status = mgr.status()
        for model_type in MODELS:
            train_count = status.get(model_type, {}).get("train", 0)
            if train_count >= 500:
                # Check if there's already a pending/running job
                existing = [
                    j for j in orch.list_jobs()
                    if j["model_type"] == model_type and j["status"] in ("pending", "running")
                ]
                if not existing:
                    try:
                        job = orch.submit(model_type)
                        submitted.append(f"{model_type} ({job.job_id})")
                    except Exception as exc:
                        skipped.append(f"{model_type}: {exc}")
                else:
                    skipped.append(f"{model_type}: already queued")
            else:
                skipped.append(f"{model_type}: only {train_count} examples")
    except Exception as exc:
        return {"error": str(exc)}
    return {"submitted": submitted, "skipped": skipped}


def _model_benchmark_callback() -> Dict[str, Any]:
    """Daily: benchmark all active fine-tuned micro-models."""
    try:
        from training.benchmark_runner import get_benchmark_runner
        runner = get_benchmark_runner()
        results = runner.run_all(auto_promote=True)
        return {
            "benchmarked": len(results),
            "results": [
                {"model_type": r.model_type, "score": r.aggregate_score, "promoted": r.promoted}
                for r in results
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {"error": str(exc), "benchmarked": 0}


def _backup_databases_callback() -> Dict[str, Any]:
    """Daily: run automated database backups."""
    try:
        from engine.nexus.backup_manager import get_backup_manager
        mgr = get_backup_manager()
        result = mgr.run_backup()
        return result.to_dict() if hasattr(result, "to_dict") else {"result": str(result)}
    except Exception as exc:
        return {"error": str(exc)}


def _conversation_analyze_callback() -> Dict[str, Any]:
    """Daily: analyze the most recent Copilot session and extract user facts.

    Reads recent turns from the session store, runs the ConversationAnalyzer
    cascade (NLM → LMStudio → heuristic), merges results into UserProfileStore,
    and stores action items in Nexus.

    On the first run (when the profile has no facts), performs a bootstrap pass
    over the last 10 sessions to populate the profile from historical data.
    """
    try:
        from engine.nexus.conversation_analyzer import run_conversation_analysis
        from engine.nexus.user_profile import get_user_profile_store

        # Bootstrap: scan more sessions when profile is still empty
        profile = get_user_profile_store().get_profile()
        lookback = 10 if not profile.get("facts") else 1

        result = run_conversation_analysis(lookback_sessions=lookback)
        return {
            "extraction_mode": result.get("extraction_mode", "unknown"),
            "facts_extracted": len(result.get("facts", [])),
            "action_items": len(result.get("action_items", [])),
            "topics": len(result.get("topics_of_interest", [])),
            "lookback_sessions": lookback,
            "error": result.get("error", ""),
        }
    except Exception as exc:
        logger.error("Conversation analyze callback failed: %s", exc)
        return {"error": str(exc)}


def _router_finetune_cycle_callback() -> Dict[str, Any]:
    """Weekly: end-to-end router_v2 finetune cycle.

    Runs the complete pipeline:
      1. Generate / augment router_v2 dataset (target 500 examples).
      2. Submit a finetune job if dataset threshold is met and no job is pending.
      3. Benchmark the latest trained router_v2 model.
      4. Auto-promote if accuracy improves over baseline.
    """
    results: Dict[str, Any] = {}
    try:
        from training.micro_datasets import MicroDatasetManager
        mgr = MicroDatasetManager()
        stats = mgr.build("router_v2", count=500, augment=True)
        results["dataset"] = {"total": stats.total, "train": stats.train}
    except Exception as exc:
        logger.warning("Dataset build failed: %s", exc)
        results["dataset"] = {"error": str(exc)}

    try:
        from training.finetune_orchestrator import get_finetune_orchestrator
        orch = get_finetune_orchestrator()
        existing = [j for j in orch.list_jobs()
                    if j["model_type"] == "router_v2" and j["status"] in ("pending", "running")]
        if not existing and results.get("dataset", {}).get("train", 0) >= 400:
            job = orch.submit("router_v2")
            results["finetune"] = {"job_id": job.job_id, "status": "submitted"}
        else:
            results["finetune"] = {"status": "skipped", "reason": "already queued or insufficient data"}
    except Exception as exc:
        logger.warning("Finetune submit failed: %s", exc)
        results["finetune"] = {"error": str(exc)}

    try:
        from training.benchmark_runner import get_benchmark_runner
        runner = get_benchmark_runner()
        bench = runner.run("router_v2", auto_promote=True)
        results["benchmark"] = {
            "score": bench.aggregate_score,
            "promoted": bench.promoted,
            "error": bench.error or "",
        }
    except Exception as exc:
        logger.warning("Benchmark failed: %s", exc)
        results["benchmark"] = {"error": str(exc)}

    return results


def _dataset_augment_callback() -> Dict[str, Any]:
    """Weekly: re-augment all micro-model datasets with new session data.

    Rebuilds all 5 micro-model datasets from existing saved examples plus any
    new examples accumulated since the last run.  Does NOT call the teacher
    pipeline — uses augmentation only, so it is safe to run without NLM.
    """
    from training.micro_datasets import MicroDatasetManager, MODELS
    results: Dict[str, Any] = {}
    mgr = MicroDatasetManager()
    for model_type in MODELS:
        try:
            stats = mgr.build(model_type, count=500, augment=True)
            results[model_type] = {"total": stats.total, "aug": stats.augmented}
        except Exception as exc:
            logger.warning("Augment failed for %s: %s", model_type, exc)
            results[model_type] = {"error": str(exc)}
    return results


def main() -> None:
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
