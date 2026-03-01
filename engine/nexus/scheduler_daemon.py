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
