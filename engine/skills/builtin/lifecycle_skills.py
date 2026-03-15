"""
Lifecycle MCP skills — autonomous feedback loop control for CosySim agents.

v1.33: 12 skills (pack="lifecycle") exposing the autonomous improvement
systems: auto-loop orchestration, experiment execution, online evaluation,
training pipeline, conversation sync, and impact tracking.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────


def _ts(epoch: Optional[float]) -> str:
    """Format an epoch timestamp as a readable string, or 'never'."""
    if not epoch:
        return "never"
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def _duration(seconds: Optional[float]) -> str:
    """Format a duration in seconds as a human-readable string."""
    if seconds is None:
        return "n/a"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def _safe_json(obj: Any, indent: int = 2) -> str:
    """JSON-serialize with fallback to str() for non-serializable objects."""
    try:
        return json.dumps(obj, indent=indent, default=str)
    except (TypeError, ValueError):
        return str(obj)


# ── 1. Loop Status ────────────────────────────────────────────


@skill(
    pack="lifecycle",
    description="Get status of all autonomous feedback loops including health, "
                "task registration, and recent cycle history",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "status"],
)
def get_loop_status() -> str:
    """Get autonomous loop status."""
    try:
        from engine.nexus.auto_loop import get_auto_loop

        loop = get_auto_loop()
        status = loop.get_loop_status()
    except Exception as exc:
        logger.warning("get_loop_status failed: %s", exc)
        return f"Loop status unavailable: {exc}"

    lines: List[str] = ["=== Autonomous Loop Status ===", ""]

    # Health
    health = status.get("health", "unknown")
    lines.append(f"Health: {health.upper()}")
    lines.append(f"Tasks registered: {status.get('loop_registered', False)}")
    lines.append("")

    # Tasks
    tasks = status.get("tasks", [])
    if tasks:
        lines.append("--- Registered Tasks ---")
        for t in tasks:
            enabled = "ON" if t.get("enabled", True) else "OFF"
            last = _ts(t.get("last_run"))
            runs = t.get("run_count", 0)
            errs = t.get("error_count", 0)
            lines.append(
                f"  [{enabled}] {t.get('id', '?')} — {t.get('name', '?')} "
                f"| runs={runs} errors={errs} last={last}"
            )
        lines.append("")

    # Recent cycles
    recent = status.get("recent_cycles", [])
    if recent:
        lines.append("--- Recent Cycles (last 10) ---")
        for c in recent[:10]:
            started = _ts(c.get("started_at"))
            dur = _duration(c.get("duration_s"))
            lines.append(
                f"  {c.get('cycle_type', '?'):20s} "
                f"{c.get('status', '?'):10s} "
                f"started={started} duration={dur}"
            )
        lines.append("")

    # Last-run timestamps
    for key in ("last_experiment", "last_eval", "last_training", "last_full"):
        val = status.get(key)
        if val:
            lines.append(f"  {key}: {_ts(val)}")

    return "\n".join(lines)


# ── 2. Trigger Experiment Cycle ───────────────────────────────


@skill(
    pack="lifecycle",
    description="Manually trigger the experiment execution cycle to run "
                "pending experiments immediately",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "experiment"],
    cooldown=60.0,
)
def trigger_experiment_cycle() -> str:
    """Trigger experiment execution cycle."""
    try:
        from engine.nexus.auto_loop import get_auto_loop

        loop = get_auto_loop()
        result = loop._experiment_execution_callback()
    except Exception as exc:
        logger.error("trigger_experiment_cycle failed: %s", exc)
        return f"Experiment cycle failed: {exc}"

    action = result.get("action", "unknown")
    lines = [
        "=== Experiment Cycle Result ===",
        f"Action: {action}",
    ]
    if action == "executed":
        lines.append(f"Run ID: {result.get('run_id', 'n/a')}")
        run_result = result.get("result", {})
        lines.append(f"Status: {run_result.get('status', 'n/a')}")
        if "recommendation" in run_result:
            lines.append(f"Recommendation: {run_result['recommendation']}")
    elif action == "skipped":
        lines.append("No pending experiments to execute.")
    elif action == "failed":
        lines.append(f"Error: {result.get('error', 'unknown')}")

    return "\n".join(lines)


# ── 3. Trigger Eval Sweep ─────────────────────────────────────


@skill(
    pack="lifecycle",
    description="Manually trigger the online evaluation sweep to check and "
                "decide on all running evaluation sessions",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "evaluation"],
    cooldown=30.0,
)
def trigger_eval_sweep() -> str:
    """Trigger online evaluation sweep."""
    try:
        from engine.nexus.auto_loop import get_auto_loop

        loop = get_auto_loop()
        result = loop._eval_sweep_callback()
    except Exception as exc:
        logger.error("trigger_eval_sweep failed: %s", exc)
        return f"Eval sweep failed: {exc}"

    lines = [
        "=== Evaluation Sweep Result ===",
        f"Sessions checked: {result.get('sessions_checked', 0)}",
        f"Promotions:       {result.get('promotions', 0)}",
        f"Rollbacks:        {result.get('rollbacks', 0)}",
        f"Continues:        {result.get('continues', 0)}",
    ]
    return "\n".join(lines)


# ── 4. Trigger Training Cycle ─────────────────────────────────


@skill(
    pack="lifecycle",
    description="Manually trigger the training check cycle to evaluate "
                "training data thresholds and auto-train eligible models",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "training"],
    cooldown=120.0,
)
def trigger_training_cycle() -> str:
    """Trigger training check cycle."""
    try:
        from engine.nexus.auto_loop import get_auto_loop

        loop = get_auto_loop()
        result = loop._training_check_callback()
    except Exception as exc:
        logger.error("trigger_training_cycle failed: %s", exc)
        return f"Training cycle failed: {exc}"

    lines = ["=== Training Cycle Result ==="]

    if isinstance(result, dict):
        for dataset, outcome in result.items():
            if isinstance(outcome, dict):
                status = outcome.get("status", outcome.get("action", "unknown"))
                lines.append(f"  {dataset}: {status}")
                if "examples" in outcome:
                    lines.append(f"    examples={outcome['examples']}")
                if "loss" in outcome:
                    lines.append(f"    loss={outcome['loss']:.4f}")
            else:
                lines.append(f"  {dataset}: {outcome}")
    else:
        lines.append(f"Result: {result}")

    return "\n".join(lines)


# ── 5. Trigger Full Cycle ─────────────────────────────────────


@skill(
    pack="lifecycle",
    description="Run a complete autonomous improvement cycle: experiments, "
                "evaluations, training, and impact assessment in sequence",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "automation"],
    cooldown=300.0,
)
def trigger_full_cycle() -> str:
    """Run a complete autonomous improvement cycle."""
    try:
        from engine.nexus.auto_loop import get_auto_loop

        loop = get_auto_loop()
        result = loop._full_cycle_callback()
    except Exception as exc:
        logger.error("trigger_full_cycle failed: %s", exc)
        return f"Full cycle failed: {exc}"

    lines = ["=== Full Improvement Cycle ==="]

    summary = result.get("summary", {})
    if summary:
        lines.append("")
        lines.append("--- Summary ---")
        for key, val in summary.items():
            lines.append(f"  {key}: {val}")

    sub_results = result.get("sub_results", {})
    if sub_results:
        lines.append("")
        lines.append("--- Sub-Cycle Results ---")
        for phase, phase_result in sub_results.items():
            if isinstance(phase_result, dict):
                status = phase_result.get("action",
                         phase_result.get("status", "done"))
                lines.append(f"  {phase}: {status}")
            else:
                lines.append(f"  {phase}: {phase_result}")

    health = result.get("health", "unknown")
    lines.append("")
    lines.append(f"Post-cycle health: {health}")

    return "\n".join(lines)


# ── 6. Cycle History ──────────────────────────────────────────


@skill(
    pack="lifecycle",
    description="Get recent cycle execution history showing what autonomous "
                "improvements have run and their results",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "history"],
)
def get_cycle_history(cycle_type: str = "", days: int = 7) -> str:
    """Get recent cycle execution history."""
    try:
        from engine.nexus.auto_loop import get_auto_loop

        loop = get_auto_loop()
        history = loop.get_cycle_history(
            cycle_type=cycle_type or None,
            days=days,
        )
    except Exception as exc:
        logger.warning("get_cycle_history failed: %s", exc)
        return f"Cycle history unavailable: {exc}"

    if not history:
        filter_msg = f" (type={cycle_type})" if cycle_type else ""
        return f"No cycles recorded in the last {days} days{filter_msg}."

    lines = [f"=== Cycle History (last {days} days) ===", ""]

    for rec in history:
        started = _ts(rec.get("started_at"))
        dur = _duration(rec.get("duration_s"))
        status = rec.get("status", "?")
        ctype = rec.get("cycle_type", "?")
        cid = rec.get("cycle_id", "")[:8]

        lines.append(f"[{cid}] {ctype:20s} {status:10s} {started} ({dur})")

        result = rec.get("result", {})
        if isinstance(result, dict) and result:
            for k, v in list(result.items())[:5]:
                lines.append(f"       {k}: {v}")

        error = rec.get("error")
        if error:
            lines.append(f"       ERROR: {error}")

        lines.append("")

    lines.append(f"Total: {len(history)} cycles")
    return "\n".join(lines)


# ── 7. Training Queue Status ─────────────────────────────────


@skill(
    pack="lifecycle",
    description="Get current training data queue status showing candidate "
                "counts per dataset and thresholds for auto-training",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "training"],
)
def get_training_queue_status() -> str:
    """Get training pipeline status."""
    try:
        from training.auto_train import get_status

        status = get_status()
    except Exception as exc:
        logger.warning("get_training_queue_status failed: %s", exc)
        return f"Training status unavailable: {exc}"

    lines = ["=== Training Queue Status ===", ""]

    # Candidate counts vs thresholds
    counts = status.get("candidate_counts", {})
    thresholds = status.get("thresholds", {})
    all_datasets = sorted(set(list(counts.keys()) + list(thresholds.keys())))

    if all_datasets:
        lines.append("--- Datasets ---")
        for ds in all_datasets:
            count = counts.get(ds, 0)
            threshold = thresholds.get(ds, "?")
            ready = "READY" if isinstance(threshold, (int, float)) and count >= threshold else "waiting"
            lines.append(f"  {ds:25s} {count:>5}/{threshold:<5} [{ready}]")
        lines.append("")

    # Last train times
    last_train = status.get("last_train", {})
    if last_train:
        lines.append("--- Last Training ---")
        for ds, info in last_train.items():
            if isinstance(info, dict):
                ts = _ts(info.get("timestamp"))
                examples = info.get("examples", "?")
                loss = info.get("loss")
                loss_str = f" loss={loss:.4f}" if loss is not None else ""
                lines.append(f"  {ds}: {ts} ({examples} examples{loss_str})")
            else:
                lines.append(f"  {ds}: {info}")
        lines.append("")

    # Recent history
    recent = status.get("recent_history", [])
    if recent:
        lines.append("--- Recent Runs ---")
        for entry in recent[-5:]:
            ts = _ts(entry.get("timestamp"))
            results = entry.get("results", {})
            summary = ", ".join(f"{k}={v}" for k, v in results.items())
            lines.append(f"  {ts}: {summary}")

    last_check = _ts(status.get("last_check"))
    lines.append("")
    lines.append(f"Last check: {last_check}")

    return "\n".join(lines)


# ── 8. Force Conversation Sync ────────────────────────────────


@skill(
    pack="lifecycle",
    description="Force an immediate sync of scene conversation data to Nexus "
                "knowledge base and training pipeline",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "sync"],
    cooldown=60.0,
)
def force_conversation_sync() -> str:
    """Force immediate conversation sync to Nexus."""
    try:
        from engine.nexus.conversation_sync import get_conversation_sync

        sync = get_conversation_sync()
        result = sync.force_sync()
    except Exception as exc:
        logger.error("force_conversation_sync failed: %s", exc)
        return f"Conversation sync failed: {exc}"

    lines = ["=== Conversation Sync Result ==="]

    if isinstance(result, dict):
        for sync_type, details in result.items():
            if isinstance(details, dict):
                processed = details.get("events_processed", 0)
                created = details.get("entries_created", 0)
                lines.append(
                    f"  {sync_type}: {processed} processed, "
                    f"{created} entries created"
                )
            else:
                lines.append(f"  {sync_type}: {details}")
    else:
        lines.append(f"Result: {result}")

    return "\n".join(lines)


# ── 9. Conversation Sync Status ──────────────────────────────


@skill(
    pack="lifecycle",
    description="Get current status of scene-to-Nexus conversation sync "
                "including pending events and sync history",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "sync"],
)
def get_conversation_sync_status() -> str:
    """Get conversation sync status."""
    try:
        from engine.nexus.conversation_sync import get_conversation_sync

        sync = get_conversation_sync()
        status = sync.get_sync_status()
    except Exception as exc:
        logger.warning("get_conversation_sync_status failed: %s", exc)
        return f"Conversation sync status unavailable: {exc}"

    lines = [
        "=== Conversation Sync Status ===",
        "",
        f"Last sync:      {_ts(status.get('last_sync_timestamp'))}",
        f"Last event ID:  {status.get('last_event_id', 'n/a')}",
        f"Events pending: {status.get('events_pending', 0)}",
        f"Total synced:   {status.get('total_synced', 0)}",
    ]

    recent = status.get("recent_syncs", [])
    if recent:
        lines.append("")
        lines.append("--- Recent Syncs ---")
        for rec in recent[-5:]:
            ts = _ts(rec.get("started_at"))
            stype = rec.get("sync_type", "?")
            sstatus = rec.get("status", "?")
            processed = rec.get("events_processed", 0)
            created = rec.get("entries_created", 0)
            lines.append(
                f"  {ts} {stype:22s} {sstatus:10s} "
                f"processed={processed} created={created}"
            )
            if rec.get("error"):
                lines.append(f"    error: {rec['error']}")

    return "\n".join(lines)


# ── 10. Improvement Report ────────────────────────────────────


@skill(
    pack="lifecycle",
    description="Generate a comprehensive improvement report showing recent "
                "experiments, evaluations, training runs, and their impacts",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "report"],
)
def get_improvement_report(days: int = 7) -> str:
    """Generate improvement report spanning the last N days."""
    lines = [f"=== Improvement Report ({days}-day window) ===", ""]
    errors: List[str] = []

    # Experiments
    try:
        from engine.nexus.experiment_executor import get_experiment_executor

        executor = get_experiment_executor()
        stats = executor.run_stats()
        runs = executor.list_runs(days=days)

        lines.append("--- Experiments ---")
        lines.append(f"  Total runs (all-time): {stats.get('total_runs', 0)}")
        lines.append(f"  Success rate: {stats.get('success_rate', 0):.1%}")
        lines.append(f"  Avg effect size: {stats.get('avg_effect_size', 0):.4f}")
        if runs:
            lines.append(f"  Runs in window: {len(runs)}")
            by_status: Dict[str, int] = {}
            for r in runs:
                s = r.get("status", "unknown")
                by_status[s] = by_status.get(s, 0) + 1
            for s, c in sorted(by_status.items()):
                lines.append(f"    {s}: {c}")
        lines.append("")
    except Exception as exc:
        errors.append(f"experiments: {exc}")

    # Online evaluations
    try:
        from engine.nexus.online_evaluator import get_online_evaluator

        evaluator = get_online_evaluator()
        sessions = evaluator.list_sessions(limit=50)
        cutoff = time.time() - days * 86400
        recent = [
            s for s in sessions
            if s.get("started_at", 0) >= cutoff
        ]

        lines.append("--- Online Evaluations ---")
        lines.append(f"  Sessions in window: {len(recent)}")
        if recent:
            by_status = {}
            for s in recent:
                st = s.get("status", "unknown")
                by_status[st] = by_status.get(st, 0) + 1
            for st, cnt in sorted(by_status.items()):
                lines.append(f"    {st}: {cnt}")
            promoted = sum(
                1 for s in recent
                if s.get("decision") == "promote"
            )
            rolled_back = sum(
                1 for s in recent
                if s.get("decision") == "rollback"
            )
            lines.append(f"  Promoted: {promoted}  Rolled back: {rolled_back}")
        lines.append("")
    except Exception as exc:
        errors.append(f"evaluations: {exc}")

    # Impact attribution
    try:
        from engine.nexus.impact_tracker import get_impact_tracker

        tracker = get_impact_tracker()
        report = tracker.attribution_report(days=days)

        lines.append("--- Impact Attribution ---")
        lines.append(f"  Total changes tracked: {report.get('total_changes', 0)}")
        lines.append(f"  Impact computed: {report.get('computed', 0)}")
        lines.append(f"  Uncomputed: {report.get('uncomputed', 0)}")

        top_pos = report.get("top_positive", [])
        if top_pos:
            lines.append("  Top positive impacts:")
            for item in top_pos[:3]:
                lines.append(
                    f"    + {item.get('title', '?')}: "
                    f"{item.get('percentage_delta', 0):+.1%}"
                )

        top_neg = report.get("top_negative", [])
        if top_neg:
            lines.append("  Top negative impacts:")
            for item in top_neg[:3]:
                lines.append(
                    f"    - {item.get('title', '?')}: "
                    f"{item.get('percentage_delta', 0):+.1%}"
                )
        lines.append("")
    except Exception as exc:
        errors.append(f"impact: {exc}")

    # Training
    try:
        from training.auto_train import get_status

        t_status = get_status()
        recent_hist = t_status.get("recent_history", [])
        cutoff_ts = time.time() - days * 86400
        window_runs = [
            h for h in recent_hist
            if h.get("timestamp", 0) >= cutoff_ts
        ]

        lines.append("--- Training Pipeline ---")
        lines.append(f"  Training runs in window: {len(window_runs)}")
        counts = t_status.get("candidate_counts", {})
        thresholds = t_status.get("thresholds", {})
        ready = sum(
            1 for ds in counts
            if isinstance(thresholds.get(ds), (int, float))
            and counts[ds] >= thresholds[ds]
        )
        lines.append(f"  Datasets ready to train: {ready}/{len(counts)}")
        lines.append("")
    except Exception as exc:
        errors.append(f"training: {exc}")

    # Errors
    if errors:
        lines.append("--- Subsystem Errors ---")
        for e in errors:
            lines.append(f"  ! {e}")

    return "\n".join(lines)


# ── 11. Loop Health ───────────────────────────────────────────


@skill(
    pack="lifecycle",
    description="Quick health check of all autonomous loop components: "
                "scheduler, auto-loop, conversation sync, training pipeline",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "health"],
)
def get_loop_health() -> str:
    """Quick health check of all autonomous systems."""
    checks: List[str] = ["=== Loop Health Check ===", ""]

    # Scheduler daemon
    try:
        from engine.nexus.scheduler_daemon import get_scheduler_daemon

        daemon = get_scheduler_daemon()
        status = daemon.status()
        running = status.get("running", False)
        task_count = status.get("task_count", 0)
        state = "OK" if running else "WARN"
        checks.append(
            f"[{state:4s}] Scheduler daemon — "
            f"running={running}, tasks={task_count}"
        )
    except Exception as exc:
        checks.append(f"[FAIL] Scheduler daemon — {exc}")

    # Auto-loop
    try:
        from engine.nexus.auto_loop import get_auto_loop

        loop = get_auto_loop()
        loop_status = loop.get_loop_status()
        registered = loop_status.get("loop_registered", False)
        health = loop_status.get("health", "unknown")
        state = "OK" if registered and health in ("healthy", "ok") else "WARN"
        checks.append(
            f"[{state:4s}] Auto-loop — "
            f"registered={registered}, health={health}"
        )
    except Exception as exc:
        checks.append(f"[FAIL] Auto-loop — {exc}")

    # Conversation sync
    try:
        from engine.nexus.conversation_sync import get_conversation_sync

        sync = get_conversation_sync()
        sync_status = sync.get_sync_status()
        pending = sync_status.get("events_pending", 0)
        total = sync_status.get("total_synced", 0)
        state = "OK" if pending < 100 else "WARN"
        checks.append(
            f"[{state:4s}] Conversation sync — "
            f"pending={pending}, total_synced={total}"
        )
    except Exception as exc:
        checks.append(f"[FAIL] Conversation sync — {exc}")

    # Training pipeline
    try:
        from training.auto_train import get_status

        t_status = get_status()
        counts = t_status.get("candidate_counts", {})
        total_candidates = sum(counts.values()) if counts else 0
        state = "OK"
        checks.append(
            f"[{state:4s}] Training pipeline — "
            f"datasets={len(counts)}, candidates={total_candidates}"
        )
    except Exception as exc:
        checks.append(f"[FAIL] Training pipeline — {exc}")

    # Impact tracker
    try:
        from engine.nexus.impact_tracker import get_impact_tracker

        tracker = get_impact_tracker()
        report = tracker.attribution_report(days=1)
        changes = report.get("total_changes", 0)
        checks.append(f"[ OK ] Impact tracker — changes_24h={changes}")
    except Exception as exc:
        checks.append(f"[FAIL] Impact tracker — {exc}")

    # Experiment executor
    try:
        from engine.nexus.experiment_executor import get_experiment_executor

        executor = get_experiment_executor()
        stats = executor.run_stats()
        total = stats.get("total_runs", 0)
        checks.append(f"[ OK ] Experiment executor — total_runs={total}")
    except Exception as exc:
        checks.append(f"[FAIL] Experiment executor — {exc}")

    # Online evaluator
    try:
        from engine.nexus.online_evaluator import get_online_evaluator

        evaluator = get_online_evaluator()
        sessions = evaluator.list_sessions(limit=5)
        active = sum(
            1 for s in sessions
            if s.get("status") in ("running", "RUNNING")
        )
        checks.append(f"[ OK ] Online evaluator — active_sessions={active}")
    except Exception as exc:
        checks.append(f"[FAIL] Online evaluator — {exc}")

    # Summary
    fail_count = sum(1 for c in checks if "[FAIL]" in c)
    warn_count = sum(1 for c in checks if "[WARN]" in c)
    checks.append("")
    if fail_count:
        checks.append(f"Overall: {fail_count} FAILED, {warn_count} WARNINGS")
    elif warn_count:
        checks.append(f"Overall: DEGRADED ({warn_count} warnings)")
    else:
        checks.append("Overall: ALL SYSTEMS OK")

    return "\n".join(checks)


# ── 12. Configure Loop ────────────────────────────────────────


@skill(
    pack="lifecycle",
    description="Enable or disable specific autonomous loop tasks. Use "
                "task_id from get_loop_status to target specific loops.",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "config"],
)
def configure_loop(task_id: str, enabled: bool = True) -> str:
    """Enable or disable a specific autonomous loop task."""
    if not task_id:
        return "Error: task_id is required. Use get_loop_status to list tasks."

    try:
        from engine.nexus.scheduler_daemon import get_scheduler_daemon

        daemon = get_scheduler_daemon()
        status = daemon.status()
        task_ids = [t["id"] for t in status.get("tasks", [])]

        if task_id not in task_ids:
            return (
                f"Error: task '{task_id}' not found. "
                f"Available tasks: {', '.join(task_ids)}"
            )

        if enabled:
            daemon.enable_task(task_id)
            action = "enabled"
        else:
            daemon.disable_task(task_id)
            action = "disabled"

        logger.info("Lifecycle loop task '%s' %s", task_id, action)
        return f"Task '{task_id}' has been {action}."

    except Exception as exc:
        logger.error("configure_loop failed: %s", exc)
        return f"Failed to configure task '{task_id}': {exc}"
