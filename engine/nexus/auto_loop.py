"""Autonomous feedback loop orchestrator.

Coordinates experiment execution, online evaluation, training automation,
and impact tracking into closed-loop improvement cycles that run
autonomously via the scheduler daemon.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Data Model ────────────────────────────────────────────────────────────


@dataclass
class CycleRecord:
    """Track each autonomous cycle execution."""

    cycle_id: str
    cycle_type: str
    started_at: float
    completed_at: Optional[float] = None
    status: str = "running"
    result: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# ──── AutoLoop ──────────────────────────────────────────────────────────────


class AutoLoop:
    """Central orchestrator for autonomous improvement cycles.

    Registers scheduler tasks that periodically execute experiments,
    sweep online evaluations, check training readiness, compute impact
    assessments, and run full daily improvement cycles — all without
    human intervention.

    Args:
        db_path: Path to the SQLite database for cycle tracking.
    """

    # Scheduler task definitions: (task_id, name, schedule)
    _TASK_DEFS: List[tuple] = [
        (
            "auto-loop-experiment",
            "Auto-Loop: Experiment Execution",
            "every_2h",
        ),
        (
            "auto-loop-eval-sweep",
            "Auto-Loop: Evaluation Sweep",
            "every_30m",
        ),
        (
            "auto-loop-training",
            "Auto-Loop: Training Check",
            "every_4h",
        ),
        (
            "auto-loop-impact",
            "Auto-Loop: Impact Assessment",
            "every_6h",
        ),
        (
            "auto-loop-full-cycle",
            "Auto-Loop: Full Daily Cycle",
            "daily",
        ),
    ]

    def __init__(self, db_path: str = "data/auto_loop.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._tasks_registered = False
        self._init_db()
        logger.info("AutoLoop initialised (db=%s)", self._db_path)

    # ──── Database Setup ────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create the SQLite tables if they don't exist."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cycle_records (
                    cycle_id     TEXT PRIMARY KEY,
                    cycle_type   TEXT NOT NULL,
                    started_at   REAL NOT NULL,
                    completed_at REAL,
                    status       TEXT NOT NULL DEFAULT 'running',
                    result       TEXT NOT NULL DEFAULT '{}',
                    error        TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cycle_metrics (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    cycle_id     TEXT NOT NULL,
                    metric_name  TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    recorded_at  REAL NOT NULL,
                    FOREIGN KEY (cycle_id) REFERENCES cycle_records(cycle_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cycle_type
                ON cycle_records(cycle_type)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cycle_status
                ON cycle_records(status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_metrics_cycle
                ON cycle_metrics(cycle_id)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """Open a connection to the cycle-tracking database."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ──── Task Registration ─────────────────────────────────────────────

    def register_tasks(self) -> int:
        """Register all autonomous loop tasks with the scheduler daemon.

        Uses lazy import of ``get_scheduler_daemon`` to avoid circular
        dependencies at module load time.

        Returns:
            Number of tasks successfully registered.
        """
        from engine.nexus.scheduler_daemon import get_scheduler_daemon

        daemon = get_scheduler_daemon()

        callbacks: Dict[str, Callable[[], Dict[str, Any]]] = {
            "auto-loop-experiment": self._experiment_execution_callback,
            "auto-loop-eval-sweep": self._eval_sweep_callback,
            "auto-loop-training": self._training_check_callback,
            "auto-loop-impact": self._impact_assessment_callback,
            "auto-loop-full-cycle": self._full_cycle_callback,
        }

        registered = 0
        for task_id, name, schedule in self._TASK_DEFS:
            try:
                daemon.register(
                    task_id=task_id,
                    name=name,
                    schedule=schedule,
                    callback=callbacks[task_id],
                    enabled=True,
                )
                registered += 1
                logger.debug("Registered scheduler task: %s", task_id)
            except Exception as exc:
                logger.warning(
                    "Failed to register task %s: %s", task_id, exc
                )

        self._tasks_registered = registered > 0
        logger.info(
            "AutoLoop registered %d/%d scheduler tasks",
            registered,
            len(self._TASK_DEFS),
        )
        return registered

    # ──── Scheduler Callbacks ───────────────────────────────────────────

    def _experiment_execution_callback(self) -> Dict[str, Any]:
        """Execute pending experiments automatically.

        Checks for PENDING experiment runs via the ExperimentExecutor and
        executes the oldest one.  Only one experiment is run per cycle to
        keep system load predictable.

        Returns:
            Summary dict with action taken and result details.
        """
        from engine.nexus.experiment_executor import (
            ExperimentStatus,
            get_experiment_executor,
        )
        from engine.nexus.impact_tracker import (
            ChangeType,
            get_impact_tracker,
        )

        executor = get_experiment_executor()
        tracker = get_impact_tracker()

        pending = executor.list_runs(status=ExperimentStatus.PENDING)
        if not pending:
            return {"action": "skipped", "reason": "no_pending_experiments"}

        experiment = pending[0]
        cycle = self._start_cycle("experiment_execution")

        try:
            result = executor.execute_experiment(experiment["proposal_id"])

            if result.get("status") in ("COMPLETED", "ROLLED_BACK"):
                exp_name = experiment.get("experiment_name", "unknown")
                recommendation = result.get("recommendation", "unknown")
                change = tracker.record_change(
                    change_type=ChangeType.EXPERIMENT_RESULT,
                    title=f"Experiment: {exp_name}",
                    description=(
                        f"Auto-executed experiment "
                        f"{experiment['run_id']}: {recommendation}"
                    ),
                    source="auto_loop",
                    metadata={
                        "run_id": experiment["run_id"],
                        "proposal_id": experiment["proposal_id"],
                        "result": result,
                    },
                )
                try:
                    tracker.finalize_change(change.change_id)
                except Exception as fin_err:
                    logger.warning(
                        "Impact finalization deferred for %s: %s",
                        change.change_id,
                        fin_err,
                    )

            self._complete_cycle(cycle, result)
            return {
                "action": "executed",
                "run_id": experiment["run_id"],
                "proposal_id": experiment["proposal_id"],
                "result": result,
            }

        except Exception as exc:
            self._fail_cycle(cycle, str(exc))
            return {"action": "failed", "error": str(exc)}

    def _eval_sweep_callback(self) -> Dict[str, Any]:
        """Sweep all running evaluation sessions and make decisions.

        Calls ``OnlineEvaluator.auto_check()`` which inspects every
        RUNNING eval session, promotes or rolls back models that have
        crossed their configured thresholds, and returns a list of
        per-session decision dicts.

        Returns:
            Summary dict with counts of promotions, rollbacks, and
            sessions that continue collecting data.
        """
        from engine.nexus.impact_tracker import (
            ChangeType,
            get_impact_tracker,
        )
        from engine.nexus.online_evaluator import get_online_evaluator

        evaluator = get_online_evaluator()
        tracker = get_impact_tracker()

        cycle = self._start_cycle("eval_sweep")

        try:
            decisions = evaluator.auto_check()

            promotions = 0
            rollbacks = 0

            for decision in decisions:
                action = decision.get("decision", "").upper()
                if action in ("PROMOTE", "ROLLBACK"):
                    session_id = decision.get("session_id", "")
                    metrics_summary = decision.get("metrics_summary", "")
                    change = tracker.record_change(
                        change_type=ChangeType.MODEL_PROMOTION,
                        title=(
                            f"Model {action.lower()}: {session_id}"
                        ),
                        description=(
                            f"Auto-eval {action}: {metrics_summary}"
                        ),
                        source="auto_loop",
                        metadata=decision,
                    )
                    try:
                        tracker.finalize_change(change.change_id)
                    except Exception as fin_err:
                        logger.warning(
                            "Impact finalization deferred for %s: %s",
                            change.change_id,
                            fin_err,
                        )

                    if action == "PROMOTE":
                        promotions += 1
                    else:
                        rollbacks += 1

            result: Dict[str, Any] = {
                "sessions_checked": len(decisions),
                "promotions": promotions,
                "rollbacks": rollbacks,
                "continues": len(decisions) - promotions - rollbacks,
            }

            self._complete_cycle(cycle, result)
            return result

        except Exception as exc:
            self._fail_cycle(cycle, str(exc))
            return {"action": "failed", "error": str(exc)}

    def _training_check_callback(self) -> Dict[str, Any]:
        """Check training data thresholds and auto-train when ready.

        Delegates to ``training.auto_train.check_and_train_all_zoo``
        which iterates every model in the MODEL_ZOO configuration,
        checks whether enough new training examples have accumulated,
        and fine-tunes models that have crossed their threshold.

        Returns:
            Summary dict with candidate counts, trained models, and
            skipped models.
        """
        from engine.nexus.impact_tracker import (
            ChangeType,
            get_impact_tracker,
        )

        cycle = self._start_cycle("training_check")

        try:
            from training.auto_train import check_and_train_all_zoo, get_status

            status = get_status()
            candidates = status.get("candidate_counts", {})

            results = check_and_train_all_zoo()

            trained = {
                k: v
                for k, v in results.items()
                if v.get("action") == "trained"
            }

            if trained:
                tracker = get_impact_tracker()
                for dataset, info in trained.items():
                    count = info.get("count", 0)
                    loss = info.get("loss", "N/A")
                    change = tracker.record_change(
                        change_type=ChangeType.MODEL_PROMOTION,
                        title=f"Auto-trained: {dataset}",
                        description=(
                            f"Fine-tuned {dataset} with {count} examples, "
                            f"loss={loss}"
                        ),
                        source="auto_loop",
                        metadata={"dataset": dataset, "info": info},
                    )
                    try:
                        tracker.finalize_change(change.change_id)
                    except Exception as fin_err:
                        logger.warning(
                            "Impact finalization deferred for %s: %s",
                            change.change_id,
                            fin_err,
                        )

            result: Dict[str, Any] = {
                "candidates": candidates,
                "trained": list(trained.keys()),
                "skipped": [
                    k
                    for k, v in results.items()
                    if v.get("action") != "trained"
                ],
            }

            self._complete_cycle(cycle, result)
            return result

        except Exception as exc:
            self._fail_cycle(cycle, str(exc))
            return {"action": "failed", "error": str(exc)}

    def _impact_assessment_callback(self) -> Dict[str, Any]:
        """Finalize pending impact assessments and store summaries.

        Reviews all system changes from the past week that have a
        baseline snapshot but whose impact has not yet been computed,
        finalizes them (capturing the *after* snapshot and computing
        deltas), then stores a severity-distribution summary in Nexus.

        Returns:
            Summary dict with finalization counts and severity
            distribution.
        """
        from engine.nexus.impact_tracker import get_impact_tracker

        tracker = get_impact_tracker()
        cycle = self._start_cycle("impact_assessment")

        try:
            pending = tracker.list_changes(days=7, limit=50)
            unfinalized = [
                c for c in pending if not c.get("impact_computed", False)
            ]

            finalized = 0
            for change in unfinalized:
                try:
                    tracker.finalize_change(change["change_id"])
                    finalized += 1
                except Exception as fin_err:
                    logger.warning(
                        "Failed to finalize %s: %s",
                        change["change_id"],
                        fin_err,
                    )

            # Gather severity distribution from all computed impacts
            severity_counts: Dict[str, int] = {}
            for change in pending:
                if change.get("impact_computed"):
                    try:
                        impacts = tracker.get_impact(change["change_id"])
                    except Exception:
                        continue
                    for impact in impacts:
                        if isinstance(impact, dict):
                            sev = impact.get("severity", "NEUTRAL")
                        else:
                            sev = getattr(impact, "severity", "NEUTRAL")
                        sev_str = str(sev)
                        severity_counts[sev_str] = (
                            severity_counts.get(sev_str, 0) + 1
                        )

            result: Dict[str, Any] = {
                "pending_finalized": finalized,
                "total_changes_reviewed": len(pending),
                "severity_distribution": severity_counts,
            }

            if finalized > 0 or severity_counts:
                self._store_impact_summary(result)

            self._complete_cycle(cycle, result)
            return result

        except Exception as exc:
            self._fail_cycle(cycle, str(exc))
            return {"action": "failed", "error": str(exc)}

    def _full_cycle_callback(self) -> Dict[str, Any]:
        """Run a complete autonomous improvement cycle.

        Executes all four sub-cycles in sequence, aggregates their
        results into a daily improvement report, and stores the report
        in Nexus for historical tracking.

        Steps:
            1. Execute pending experiments.
            2. Sweep online evaluations.
            3. Check training candidates.
            4. Compute pending impact assessments.
            5. Generate and store daily report.

        Returns:
            Aggregated report dict covering all sub-cycles.
        """
        cycle = self._start_cycle("full_cycle")

        sub_results: Dict[str, Dict[str, Any]] = {}
        sub_errors: Dict[str, str] = {}

        # 1. Experiments
        try:
            sub_results["experiments"] = (
                self._experiment_execution_callback()
            )
        except Exception as exc:
            sub_errors["experiments"] = str(exc)
            sub_results["experiments"] = {
                "action": "failed",
                "error": str(exc),
            }

        # 2. Eval sweep
        try:
            sub_results["eval_sweep"] = self._eval_sweep_callback()
        except Exception as exc:
            sub_errors["eval_sweep"] = str(exc)
            sub_results["eval_sweep"] = {
                "action": "failed",
                "error": str(exc),
            }

        # 3. Training
        try:
            sub_results["training"] = self._training_check_callback()
        except Exception as exc:
            sub_errors["training"] = str(exc)
            sub_results["training"] = {
                "action": "failed",
                "error": str(exc),
            }

        # 4. Impact assessment
        try:
            sub_results["impact"] = self._impact_assessment_callback()
        except Exception as exc:
            sub_errors["impact"] = str(exc)
            sub_results["impact"] = {
                "action": "failed",
                "error": str(exc),
            }

        # 5. Build daily report
        report: Dict[str, Any] = {
            "timestamp": time.time(),
            "date": time.strftime("%Y-%m-%d"),
            "sub_results": sub_results,
            "errors": sub_errors,
            "summary": self._build_daily_summary(sub_results),
        }

        self._store_daily_report(report)

        if sub_errors:
            self._complete_cycle(
                cycle,
                {
                    "status": "partial",
                    "completed_sub_cycles": len(sub_results) - len(sub_errors),
                    "failed_sub_cycles": len(sub_errors),
                    "errors": sub_errors,
                    "report_date": report["date"],
                },
            )
        else:
            self._complete_cycle(
                cycle,
                {
                    "status": "complete",
                    "completed_sub_cycles": len(sub_results),
                    "report_date": report["date"],
                },
            )

        return report

    # ──── Cycle Lifecycle Helpers ───────────────────────────────────────

    def _start_cycle(self, cycle_type: str) -> CycleRecord:
        """Create and persist a new cycle record.

        Args:
            cycle_type: Kind of cycle being started.

        Returns:
            The new CycleRecord with status *running*.
        """
        cycle = CycleRecord(
            cycle_id=f"cycle-{str(uuid.uuid4())[:8]}",
            cycle_type=cycle_type,
            started_at=time.time(),
            status="running",
        )

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO cycle_records
                        (cycle_id, cycle_type, started_at, status, result)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        cycle.cycle_id,
                        cycle.cycle_type,
                        cycle.started_at,
                        cycle.status,
                        json.dumps(cycle.result),
                    ),
                )
                conn.commit()

        logger.debug(
            "Started cycle %s (type=%s)", cycle.cycle_id, cycle.cycle_type
        )
        return cycle

    def _complete_cycle(
        self, cycle: CycleRecord, result: Dict[str, Any]
    ) -> None:
        """Mark a cycle as completed and persist the result.

        Args:
            cycle: The running cycle record.
            result: Outcome dict to store alongside the record.
        """
        cycle.completed_at = time.time()
        cycle.status = "completed"
        cycle.result = result

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE cycle_records
                    SET completed_at = ?, status = ?, result = ?
                    WHERE cycle_id = ?
                    """,
                    (
                        cycle.completed_at,
                        cycle.status,
                        json.dumps(result),
                        cycle.cycle_id,
                    ),
                )
                conn.commit()

        elapsed = cycle.completed_at - cycle.started_at
        logger.info(
            "Completed cycle %s (type=%s) in %.1fs",
            cycle.cycle_id,
            cycle.cycle_type,
            elapsed,
        )

    def _fail_cycle(self, cycle: CycleRecord, error: str) -> None:
        """Mark a cycle as failed and persist the error.

        Args:
            cycle: The running cycle record.
            error: Error message describing the failure.
        """
        cycle.completed_at = time.time()
        cycle.status = "failed"
        cycle.error = error

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE cycle_records
                    SET completed_at = ?, status = ?, error = ?
                    WHERE cycle_id = ?
                    """,
                    (
                        cycle.completed_at,
                        cycle.status,
                        error,
                        cycle.cycle_id,
                    ),
                )
                conn.commit()

        elapsed = cycle.completed_at - cycle.started_at
        logger.warning(
            "Failed cycle %s (type=%s) after %.1fs: %s",
            cycle.cycle_id,
            cycle.cycle_type,
            elapsed,
            error,
        )

    # ──── Reporting Helpers ─────────────────────────────────────────────

    def _build_daily_summary(
        self, sub_results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Distil sub-cycle results into a human-readable summary.

        Args:
            sub_results: Results from each sub-cycle keyed by name.

        Returns:
            Summary dict suitable for Nexus storage.
        """
        experiments = sub_results.get("experiments", {})
        eval_sweep = sub_results.get("eval_sweep", {})
        training = sub_results.get("training", {})
        impact = sub_results.get("impact", {})

        summary: Dict[str, Any] = {
            "experiments_executed": (
                1 if experiments.get("action") == "executed" else 0
            ),
            "experiments_skipped": (
                1 if experiments.get("action") == "skipped" else 0
            ),
            "sessions_evaluated": eval_sweep.get("sessions_checked", 0),
            "models_promoted": eval_sweep.get("promotions", 0),
            "models_rolled_back": eval_sweep.get("rollbacks", 0),
            "models_trained": len(training.get("trained", [])),
            "models_skipped": len(training.get("skipped", [])),
            "impacts_finalized": impact.get("pending_finalized", 0),
            "severity_distribution": impact.get(
                "severity_distribution", {}
            ),
        }

        # Derive overall health label
        errors = sum(
            1
            for r in sub_results.values()
            if r.get("action") == "failed" or r.get("error")
        )
        if errors == 0:
            summary["health"] = "healthy"
        elif errors < len(sub_results):
            summary["health"] = "degraded"
        else:
            summary["health"] = "failed"

        return summary

    def _store_impact_summary(self, summary: Dict[str, Any]) -> None:
        """Store an impact-assessment summary in Nexus.

        Args:
            summary: The assessment result dict.
        """
        try:
            from engine.nexus.client import get_nexus_client

            client = get_nexus_client()
            client.add_entry(
                title=f"Impact Assessment {time.strftime('%Y-%m-%d')}",
                content=json.dumps(summary, indent=2),
                content_type="note",
                category="system",
            )
            logger.debug("Stored impact summary in Nexus")
        except Exception:
            logger.debug("Nexus unavailable for impact summary storage")

    def _store_daily_report(self, report: Dict[str, Any]) -> None:
        """Store the daily improvement report in Nexus.

        Args:
            report: Full daily report including sub-cycle results and
                summary.
        """
        try:
            from engine.nexus.client import get_nexus_client

            client = get_nexus_client()

            summary = report.get("summary", {})
            date_str = report.get("date", time.strftime("%Y-%m-%d"))
            health = summary.get("health", "unknown")

            lines = [
                f"# Daily Improvement Report — {date_str}",
                "",
                f"**Health:** {health}",
                "",
                "## Experiments",
                f"- Executed: {summary.get('experiments_executed', 0)}",
                f"- Skipped: {summary.get('experiments_skipped', 0)}",
                "",
                "## Online Evaluation",
                f"- Sessions checked: {summary.get('sessions_evaluated', 0)}",
                f"- Promoted: {summary.get('models_promoted', 0)}",
                f"- Rolled back: {summary.get('models_rolled_back', 0)}",
                "",
                "## Training",
                f"- Trained: {summary.get('models_trained', 0)}",
                f"- Skipped: {summary.get('models_skipped', 0)}",
                "",
                "## Impact",
                f"- Finalized: {summary.get('impacts_finalized', 0)}",
                f"- Severity: {json.dumps(summary.get('severity_distribution', {}))}",
            ]

            if report.get("errors"):
                lines.append("")
                lines.append("## Errors")
                for name, err in report["errors"].items():
                    lines.append(f"- **{name}:** {err}")

            client.add_entry(
                title=f"Auto-Loop Daily Report {date_str}",
                content="\n".join(lines),
                content_type="note",
                category="system",
            )
            logger.info("Stored daily improvement report in Nexus (%s)", date_str)
        except Exception:
            logger.debug("Nexus unavailable for daily report storage")

    # ──── Status & History ──────────────────────────────────────────────

    def get_cycle_history(
        self,
        cycle_type: Optional[str] = None,
        days: int = 7,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get recent cycle execution history.

        Args:
            cycle_type: Filter by a specific cycle type, or ``None``
                for all types.
            days: Only include cycles from the last *N* days.
            limit: Maximum number of records to return.

        Returns:
            List of cycle dicts ordered by ``started_at`` descending.
        """
        cutoff = time.time() - (days * 86400)
        clauses = ["started_at > ?"]
        params: list = [cutoff]

        if cycle_type is not None:
            clauses.append("cycle_type = ?")
            params.append(cycle_type)

        where = " AND ".join(clauses)
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM cycle_records WHERE {where} "
                "ORDER BY started_at DESC LIMIT ?",
                params,
            ).fetchall()

        results: List[Dict[str, Any]] = []
        for row in rows:
            record: Dict[str, Any] = {
                "cycle_id": row["cycle_id"],
                "cycle_type": row["cycle_type"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "status": row["status"],
                "error": row["error"],
            }
            try:
                record["result"] = json.loads(row["result"])
            except (json.JSONDecodeError, TypeError):
                record["result"] = {}

            if record["completed_at"] and record["started_at"]:
                record["duration_s"] = round(
                    record["completed_at"] - record["started_at"], 2
                )
            else:
                record["duration_s"] = None

            results.append(record)

        return results

    def _get_last_timestamp(self, cycle_type: str) -> Optional[float]:
        """Return the most recent ``completed_at`` for a cycle type.

        Args:
            cycle_type: The cycle type to look up.

        Returns:
            Unix timestamp of the most recent completion, or ``None``
            if no completed cycles exist.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(completed_at) AS ts FROM cycle_records "
                "WHERE cycle_type = ? AND status = 'completed'",
                (cycle_type,),
            ).fetchone()

        if row and row["ts"]:
            return float(row["ts"])
        return None

    def get_loop_status(self) -> Dict[str, Any]:
        """Get current status of all autonomous loops.

        Returns:
            Dict with registration state, task statuses from the
            scheduler, recent cycle history, per-loop last-run
            timestamps, and an overall health label.
        """
        # Scheduler task statuses
        scheduler_tasks: List[Dict[str, Any]] = []
        try:
            from engine.nexus.scheduler_daemon import get_scheduler_daemon

            daemon = get_scheduler_daemon()
            all_tasks = daemon.list_tasks()
            scheduler_tasks = [
                t for t in all_tasks if str(t.get("id", "")).startswith("auto-loop-")
            ]
        except Exception as exc:
            logger.debug("Could not fetch scheduler tasks: %s", exc)

        # Recent cycles
        recent = self.get_cycle_history(days=7, limit=10)

        # Per-type last timestamps
        last_experiment = self._get_last_timestamp("experiment_execution")
        last_eval = self._get_last_timestamp("eval_sweep")
        last_training = self._get_last_timestamp("training_check")
        last_impact = self._get_last_timestamp("impact_assessment")
        last_full = self._get_last_timestamp("full_cycle")

        # Health derivation: stalled if no cycle completed in 24 h,
        # degraded if any recent cycle failed, healthy otherwise.
        now = time.time()
        all_lasts = [
            ts
            for ts in [
                last_experiment,
                last_eval,
                last_training,
                last_impact,
                last_full,
            ]
            if ts is not None
        ]

        if not all_lasts:
            health = "stalled"
        elif (now - max(all_lasts)) > 86400:
            health = "stalled"
        else:
            recent_failures = [
                c for c in recent if c.get("status") == "failed"
            ]
            if recent_failures:
                health = "degraded"
            else:
                health = "healthy"

        return {
            "loop_registered": self._tasks_registered,
            "tasks": scheduler_tasks,
            "recent_cycles": recent,
            "last_experiment": last_experiment,
            "last_eval_sweep": last_eval,
            "last_training": last_training,
            "last_impact": last_impact,
            "last_full_cycle": last_full,
            "health": health,
        }

    # ──── Metric Recording ──────────────────────────────────────────────

    def record_cycle_metric(
        self,
        cycle_id: str,
        metric_name: str,
        metric_value: float,
    ) -> None:
        """Attach a named metric to a cycle record.

        Args:
            cycle_id: The cycle to attach the metric to.
            metric_name: Name of the metric.
            metric_value: Numeric value of the metric.
        """
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO cycle_metrics
                        (cycle_id, metric_name, metric_value, recorded_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (cycle_id, metric_name, metric_value, time.time()),
                )
                conn.commit()

    def get_cycle_metrics(
        self, cycle_id: str
    ) -> List[Dict[str, Any]]:
        """Retrieve all metrics attached to a cycle.

        Args:
            cycle_id: The cycle to query.

        Returns:
            List of metric dicts.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT metric_name, metric_value, recorded_at "
                "FROM cycle_metrics WHERE cycle_id = ? "
                "ORDER BY recorded_at",
                (cycle_id,),
            ).fetchall()

        return [
            {
                "metric_name": row["metric_name"],
                "metric_value": row["metric_value"],
                "recorded_at": row["recorded_at"],
            }
            for row in rows
        ]


# ──── Module-Level Singleton ────────────────────────────────────────────────

_auto_loop: Optional[AutoLoop] = None
_lock = threading.Lock()


def get_auto_loop(db_path: str = "data/auto_loop.db") -> AutoLoop:
    """Return the module-level AutoLoop singleton.

    Thread-safe double-checked locking ensures exactly one instance is
    created even under concurrent access.

    Args:
        db_path: Path to the SQLite database for cycle tracking.
            Only used on first call.

    Returns:
        The singleton AutoLoop instance.
    """
    global _auto_loop
    if _auto_loop is None:
        with _lock:
            if _auto_loop is None:
                _auto_loop = AutoLoop(db_path=db_path)
    return _auto_loop
