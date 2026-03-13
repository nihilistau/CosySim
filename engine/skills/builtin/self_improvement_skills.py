"""MCP self-improvement skills — experiment execution, online evaluation,
impact tracking, and anomaly-triggered automation.

Exposes 20 skills across four v1.29 modules:
    ExperimentExecutor  — run, track, and rollback prompt/config experiments
    OnlineEvaluator     — shadow, canary, and A/B model evaluation
    ImpactTracker       — record changes, measure impact, attribution reports
    AnomalyTrigger      — register anomaly→task trigger rules
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ──── ExperimentExecutor Skills ───────────────────────────────────────


@skill(
    pack="self_improvement",
    description="Execute a specific experiment proposal by ID. Runs baseline, applies treatment, collects metrics, and analyzes results.",
    category=SkillCategory.SYSTEM,
    tags=["experiment", "execution"],
    cooldown=5.0,
)
def run_experiment(proposal_id: str) -> str:
    """Execute an experiment proposal end-to-end.

    Args:
        proposal_id: Identifier of the experiment proposal to execute.

    Returns:
        Experiment run summary including status and key metrics.
    """
    from engine.nexus.experiment_executor import get_experiment_executor

    try:
        result = get_experiment_executor().execute_experiment(proposal_id)
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        logger.error("run_experiment failed: %s", exc)
        return f"Error executing experiment '{proposal_id}': {exc}"


@skill(
    pack="self_improvement",
    description="Execute all pending experiment proposals. Returns a list of completed runs.",
    category=SkillCategory.SYSTEM,
    tags=["experiment", "batch"],
    cooldown=10.0,
)
def run_pending_experiments() -> str:
    """Run every experiment proposal that is still in pending state.

    Returns:
        Summary of all executed runs with their outcomes.
    """
    from engine.nexus.experiment_executor import get_experiment_executor

    try:
        results = get_experiment_executor().run_pending()
        if not results:
            return "No pending experiments to execute."
        return json.dumps(results, indent=2, default=str)
    except Exception as exc:
        logger.error("run_pending_experiments failed: %s", exc)
        return f"Error running pending experiments: {exc}"


@skill(
    pack="self_improvement",
    description="List experiment runs with optional status filter (pending, running, completed, failed, rolled_back). Defaults to last 30 days.",
    category=SkillCategory.SYSTEM,
    tags=["experiment", "list"],
    cooldown=2.0,
)
def list_experiments(status: str = "", days: int = 30, limit: int = 50) -> str:
    """List experiment runs, optionally filtered by status.

    Args:
        status: Filter by ExperimentStatus value (e.g. 'completed', 'failed').
                Empty string returns all statuses.
        days: Look-back window in days.
        limit: Maximum number of results.

    Returns:
        Formatted list of experiment runs.
    """
    from engine.nexus.experiment_executor import (
        get_experiment_executor,
        ExperimentStatus,
    )

    try:
        parsed_status = None
        if status:
            try:
                parsed_status = ExperimentStatus(status.lower())
            except ValueError:
                valid = ", ".join(s.value for s in ExperimentStatus)
                return f"Invalid status '{status}'. Valid values: {valid}"

        runs = get_experiment_executor().list_runs(
            status=parsed_status, days=days, limit=limit,
        )
        if not runs:
            qualifier = f" with status '{status}'" if status else ""
            return f"No experiment runs found{qualifier} in the last {days} days."
        return json.dumps(runs, indent=2, default=str)
    except Exception as exc:
        logger.error("list_experiments failed: %s", exc)
        return f"Error listing experiments: {exc}"


@skill(
    pack="self_improvement",
    description="Get detailed status and results of a specific experiment run by its run ID.",
    category=SkillCategory.SYSTEM,
    tags=["experiment", "detail"],
    cooldown=2.0,
)
def get_experiment_status(run_id: str) -> str:
    """Retrieve full details of an experiment run.

    Args:
        run_id: Unique identifier of the experiment run.

    Returns:
        Detailed run information including config, metrics, and timeline.
    """
    from engine.nexus.experiment_executor import get_experiment_executor

    try:
        run = get_experiment_executor().get_run(run_id)
        if run is None:
            return f"Experiment run '{run_id}' not found."
        data = run.to_dict() if hasattr(run, "to_dict") else run.__dict__
        return json.dumps(data, indent=2, default=str)
    except Exception as exc:
        logger.error("get_experiment_status failed: %s", exc)
        return f"Error getting experiment run '{run_id}': {exc}"


@skill(
    pack="self_improvement",
    description="Get aggregate experiment statistics — total runs, success/failure rates, average durations, and status breakdown.",
    category=SkillCategory.SYSTEM,
    tags=["experiment", "stats"],
    cooldown=2.0,
)
def experiment_stats() -> str:
    """Return aggregate statistics across all experiment runs.

    Returns:
        JSON with counts, rates, and timing summaries.
    """
    from engine.nexus.experiment_executor import get_experiment_executor

    try:
        stats = get_experiment_executor().run_stats()
        return json.dumps(stats, indent=2, default=str)
    except Exception as exc:
        logger.error("experiment_stats failed: %s", exc)
        return f"Error fetching experiment stats: {exc}"


# ──── OnlineEvaluator Skills ─────────────────────────────────────────


@skill(
    pack="self_improvement",
    description=(
        "Start an online model evaluation session. Modes: 'shadow' (mirror traffic), "
        "'canary' (partial traffic), 'ab_test' (split traffic). Provide candidate_model "
        "and optionally production_model, min_samples, max_duration_hours."
    ),
    category=SkillCategory.SYSTEM,
    tags=["evaluation", "model", "start"],
    cooldown=5.0,
)
def start_model_evaluation(
    mode: str,
    candidate_model: str,
    production_model: str = "",
    min_samples: int = 0,
    max_duration_hours: float = 0.0,
    traffic_percentage: float = 0.05,
    promote_threshold: float = 0.05,
) -> str:
    """Start a shadow, canary, or A/B test evaluation session.

    Args:
        mode: Evaluation mode — 'shadow', 'canary', or 'ab_test'.
        candidate_model: Model identifier to evaluate.
        production_model: Current production model (auto-detected if empty).
        min_samples: Minimum sample count before deciding. 0 uses mode default.
        max_duration_hours: Maximum evaluation hours. 0 uses mode default.
        traffic_percentage: Traffic fraction for canary mode (0.0–1.0).
        promote_threshold: Improvement threshold for shadow mode promotion.

    Returns:
        Session details including session_id for follow-up queries.
    """
    from engine.nexus.online_evaluator import get_online_evaluator

    try:
        evaluator = get_online_evaluator()
        prod = production_model or None
        mode_lower = mode.lower().replace("-", "_")

        if mode_lower == "shadow":
            kwargs: Dict[str, Any] = {
                "candidate_model": candidate_model,
                "production_model": prod,
                "promote_threshold": promote_threshold,
            }
            if min_samples:
                kwargs["min_samples"] = min_samples
            if max_duration_hours:
                kwargs["max_duration_hours"] = max_duration_hours
            session = evaluator.start_shadow(**kwargs)

        elif mode_lower == "canary":
            kwargs = {
                "candidate_model": candidate_model,
                "production_model": prod,
                "traffic_percentage": traffic_percentage,
            }
            if min_samples:
                kwargs["min_samples"] = min_samples
            if max_duration_hours:
                kwargs["max_duration_hours"] = max_duration_hours
            session = evaluator.start_canary(**kwargs)

        elif mode_lower in ("ab_test", "ab"):
            kwargs = {
                "candidate_model": candidate_model,
                "production_model": prod,
            }
            if min_samples:
                kwargs["min_samples"] = min_samples
            if max_duration_hours:
                kwargs["max_duration_hours"] = max_duration_hours
            session = evaluator.start_ab_test(**kwargs)

        else:
            return f"Invalid mode '{mode}'. Use 'shadow', 'canary', or 'ab_test'."

        data = session.to_dict() if hasattr(session, "to_dict") else session.__dict__
        return json.dumps(data, indent=2, default=str)
    except Exception as exc:
        logger.error("start_model_evaluation failed: %s", exc)
        return f"Error starting {mode} evaluation: {exc}"


@skill(
    pack="self_improvement",
    description="Get status and metrics of a specific online evaluation session by session ID.",
    category=SkillCategory.SYSTEM,
    tags=["evaluation", "status"],
    cooldown=2.0,
)
def check_eval_status(session_id: str) -> str:
    """Retrieve current state and metrics of an evaluation session.

    Args:
        session_id: Evaluation session identifier.

    Returns:
        Session details with sample counts, metrics, and current decision.
    """
    from engine.nexus.online_evaluator import get_online_evaluator

    try:
        session = get_online_evaluator().get_session(session_id)
        if session is None:
            return f"Evaluation session '{session_id}' not found."
        data = session.to_dict() if hasattr(session, "to_dict") else session.__dict__
        return json.dumps(data, indent=2, default=str)
    except Exception as exc:
        logger.error("check_eval_status failed: %s", exc)
        return f"Error checking evaluation session '{session_id}': {exc}"


@skill(
    pack="self_improvement",
    description="List evaluation sessions with optional status filter (running, completed, failed). Defaults to last 30 days.",
    category=SkillCategory.SYSTEM,
    tags=["evaluation", "list"],
    cooldown=2.0,
)
def list_evaluations(status: str = "", days: int = 30, limit: int = 50) -> str:
    """List online evaluation sessions, optionally filtered by status.

    Args:
        status: Filter by EvalStatus value (e.g. 'running', 'completed').
                Empty string returns all.
        days: Look-back window in days.
        limit: Maximum number of results.

    Returns:
        Formatted list of evaluation sessions.
    """
    from engine.nexus.online_evaluator import get_online_evaluator, EvalStatus

    try:
        parsed_status = None
        if status:
            try:
                parsed_status = EvalStatus(status.lower())
            except ValueError:
                valid = ", ".join(s.value for s in EvalStatus)
                return f"Invalid status '{status}'. Valid values: {valid}"

        sessions = get_online_evaluator().list_sessions(
            status=parsed_status, days=days, limit=limit,
        )
        if not sessions:
            qualifier = f" with status '{status}'" if status else ""
            return f"No evaluation sessions found{qualifier} in the last {days} days."
        return json.dumps(sessions, indent=2, default=str)
    except Exception as exc:
        logger.error("list_evaluations failed: %s", exc)
        return f"Error listing evaluations: {exc}"


@skill(
    pack="self_improvement",
    description="Promote the candidate model from an evaluation session, making it the new production model.",
    category=SkillCategory.SYSTEM,
    tags=["evaluation", "promote", "model"],
    cooldown=5.0,
)
def promote_candidate_model(session_id: str) -> str:
    """Promote a candidate model to production based on evaluation results.

    Args:
        session_id: Evaluation session whose candidate should be promoted.

    Returns:
        Promotion result including old and new production model identifiers.
    """
    from engine.nexus.online_evaluator import get_online_evaluator

    try:
        result = get_online_evaluator().promote_model(session_id)
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        logger.error("promote_candidate_model failed: %s", exc)
        return f"Error promoting model for session '{session_id}': {exc}"


@skill(
    pack="self_improvement",
    description="Rollback a failing candidate model from an evaluation session, reverting to the production model.",
    category=SkillCategory.SYSTEM,
    tags=["evaluation", "rollback", "model"],
    cooldown=5.0,
)
def rollback_candidate_model(session_id: str) -> str:
    """Rollback a candidate model and restore the previous production model.

    Args:
        session_id: Evaluation session whose candidate should be rolled back.

    Returns:
        Rollback result with restored model details.
    """
    from engine.nexus.online_evaluator import get_online_evaluator

    try:
        result = get_online_evaluator().rollback_model(session_id)
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        logger.error("rollback_candidate_model failed: %s", exc)
        return f"Error rolling back model for session '{session_id}': {exc}"


@skill(
    pack="self_improvement",
    description="Get aggregate evaluation statistics — total sessions, promotion rate, average durations, mode breakdown.",
    category=SkillCategory.SYSTEM,
    tags=["evaluation", "stats"],
    cooldown=2.0,
)
def evaluation_stats() -> str:
    """Return aggregate statistics across all evaluation sessions.

    Returns:
        JSON with counts, rates, mode distribution, and timing summaries.
    """
    from engine.nexus.online_evaluator import get_online_evaluator

    try:
        stats = get_online_evaluator().eval_stats()
        return json.dumps(stats, indent=2, default=str)
    except Exception as exc:
        logger.error("evaluation_stats failed: %s", exc)
        return f"Error fetching evaluation stats: {exc}"


# ──── ImpactTracker Skills ───────────────────────────────────────────


@skill(
    pack="self_improvement",
    description=(
        "Record a system change for impact tracking. change_type: config_change, "
        "model_promotion, experiment_result, code_deploy, knowledge_update, "
        "scheduler_change, rule_update."
    ),
    category=SkillCategory.SYSTEM,
    tags=["impact", "change", "record"],
    cooldown=2.0,
)
def record_system_change(
    change_type: str,
    title: str,
    description: str,
    source: str = "manual",
    metadata_json: str = "",
    auto_snapshot: bool = True,
) -> str:
    """Record a system change so its impact can be measured later.

    Args:
        change_type: Type of change (e.g. 'config_change', 'model_promotion').
        title: Short title describing the change.
        description: Detailed description of what changed and why.
        source: Origin of the change (e.g. 'copilot', 'scheduler', 'manual').
        metadata_json: Optional JSON string with extra metadata.
        auto_snapshot: Whether to capture a metric snapshot automatically.

    Returns:
        Recorded change details including change_id for finalization.
    """
    from engine.nexus.impact_tracker import (
        get_impact_tracker,
        ChangeType,
    )

    try:
        try:
            ct = ChangeType(change_type.lower())
        except ValueError:
            valid = ", ".join(c.value for c in ChangeType)
            return f"Invalid change_type '{change_type}'. Valid values: {valid}"

        metadata = None
        if metadata_json:
            try:
                metadata = json.loads(metadata_json)
            except json.JSONDecodeError as je:
                return f"Invalid metadata_json: {je}"

        change = get_impact_tracker().record_change(
            change_type=ct,
            title=title,
            description=description,
            source=source,
            metadata=metadata,
            auto_snapshot=auto_snapshot,
        )
        data = change.to_dict() if hasattr(change, "to_dict") else change.__dict__
        return json.dumps(data, indent=2, default=str)
    except Exception as exc:
        logger.error("record_system_change failed: %s", exc)
        return f"Error recording system change: {exc}"


@skill(
    pack="self_improvement",
    description="Finalize impact measurement for a previously recorded change. Captures post-change metrics and computes deltas.",
    category=SkillCategory.SYSTEM,
    tags=["impact", "finalize"],
    cooldown=2.0,
)
def finalize_impact(change_id: str) -> str:
    """Finalize a change by capturing post-change metrics and computing impact.

    Args:
        change_id: Identifier of the change to finalize.

    Returns:
        Impact measurement results with before/after metric deltas.
    """
    from engine.nexus.impact_tracker import get_impact_tracker

    try:
        result = get_impact_tracker().finalize_change(change_id)
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        logger.error("finalize_impact failed: %s", exc)
        return f"Error finalizing impact for change '{change_id}': {exc}"


@skill(
    pack="self_improvement",
    description=(
        "Get impact attribution report showing which changes had the biggest effect. "
        "Ranks changes by measured metric deltas."
    ),
    category=SkillCategory.SYSTEM,
    tags=["impact", "report", "attribution"],
    cooldown=2.0,
)
def impact_report(days: int = 30, limit: int = 20) -> str:
    """Generate an attribution report ranking changes by impact magnitude.

    Args:
        days: Look-back window in days.
        limit: Maximum number of changes to include.

    Returns:
        Attribution report with ranked changes and their metric deltas.
    """
    from engine.nexus.impact_tracker import get_impact_tracker

    try:
        report = get_impact_tracker().attribution_report(days=days, limit=limit)
        return json.dumps(report, indent=2, default=str)
    except Exception as exc:
        logger.error("impact_report failed: %s", exc)
        return f"Error generating impact report: {exc}"


@skill(
    pack="self_improvement",
    description="List the top positive-impact system changes — improvements that moved metrics the most in the right direction.",
    category=SkillCategory.SYSTEM,
    tags=["impact", "improvements", "top"],
    cooldown=2.0,
)
def top_system_improvements(days: int = 30, limit: int = 10) -> str:
    """List changes that had the largest positive impact on system metrics.

    Args:
        days: Look-back window in days.
        limit: Maximum number of results.

    Returns:
        Ranked list of top improvements with metric details.
    """
    from engine.nexus.impact_tracker import get_impact_tracker

    try:
        improvements = get_impact_tracker().top_improvements(days=days, limit=limit)
        if not improvements:
            return f"No positive-impact changes recorded in the last {days} days."
        return json.dumps(improvements, indent=2, default=str)
    except Exception as exc:
        logger.error("top_system_improvements failed: %s", exc)
        return f"Error fetching top improvements: {exc}"


@skill(
    pack="self_improvement",
    description="Chronological timeline of system changes and their measured impacts over a given period.",
    category=SkillCategory.SYSTEM,
    tags=["impact", "timeline"],
    cooldown=2.0,
)
def impact_timeline_view(days: int = 30) -> str:
    """Show a chronological view of changes and their impacts.

    Args:
        days: Look-back window in days.

    Returns:
        Timeline entries ordered by time with change and impact summaries.
    """
    from engine.nexus.impact_tracker import get_impact_tracker

    try:
        timeline = get_impact_tracker().impact_timeline(days=days)
        if not timeline:
            return f"No changes recorded in the last {days} days."
        return json.dumps(timeline, indent=2, default=str)
    except Exception as exc:
        logger.error("impact_timeline_view failed: %s", exc)
        return f"Error fetching impact timeline: {exc}"


# ──── AnomalyTrigger Skills ──────────────────────────────────────────


@skill(
    pack="self_improvement",
    description=(
        "Register a new anomaly→task trigger rule. When an anomaly matches the "
        "pattern (node, metric, node_prefix, metric_contains), the specified task "
        "is automatically scheduled."
    ),
    category=SkillCategory.SYSTEM,
    tags=["anomaly", "trigger", "automation"],
    cooldown=2.0,
)
def add_anomaly_trigger(
    name: str,
    task_id: str,
    node: str = "",
    metric: str = "",
    node_prefix: str = "",
    metric_contains: str = "",
    cooldown_seconds: float = 300.0,
    enabled: bool = True,
    metadata_json: str = "",
) -> str:
    """Register a trigger that fires a task when an anomaly matches a pattern.

    Args:
        name: Human-readable name for this trigger rule.
        task_id: Task identifier to schedule when the trigger fires.
        node: Exact node name to match (empty = any).
        metric: Exact metric name to match (empty = any).
        node_prefix: Node name prefix to match (empty = any).
        metric_contains: Substring to match within metric name (empty = any).
        cooldown_seconds: Minimum seconds between trigger firings.
        enabled: Whether the trigger starts enabled.
        metadata_json: Optional JSON string with extra metadata for the task.

    Returns:
        Registered trigger rule details including rule_id.
    """
    from engine.observability.anomaly_trigger import (
        get_anomaly_trigger,
        TriggerPattern,
    )

    try:
        pattern = TriggerPattern(
            node=node or None,
            metric=metric or None,
            node_prefix=node_prefix or None,
            metric_contains=metric_contains or None,
        )

        metadata = None
        if metadata_json:
            try:
                metadata = json.loads(metadata_json)
            except json.JSONDecodeError as je:
                return f"Invalid metadata_json: {je}"

        rule = get_anomaly_trigger().register_trigger(
            name=name,
            pattern=pattern,
            task_id=task_id,
            cooldown_seconds=cooldown_seconds,
            enabled=enabled,
            metadata=metadata,
        )
        data = rule.to_dict() if hasattr(rule, "to_dict") else rule.__dict__
        return json.dumps(data, indent=2, default=str)
    except Exception as exc:
        logger.error("add_anomaly_trigger failed: %s", exc)
        return f"Error registering anomaly trigger: {exc}"


@skill(
    pack="self_improvement",
    description="List all anomaly trigger rules and their current status. Use enabled_only=True to filter to active rules.",
    category=SkillCategory.SYSTEM,
    tags=["anomaly", "trigger", "list"],
    cooldown=2.0,
)
def list_anomaly_triggers(enabled_only: bool = False) -> str:
    """List all registered anomaly trigger rules.

    Args:
        enabled_only: If True, only return enabled triggers.

    Returns:
        List of trigger rules with patterns, task IDs, and firing stats.
    """
    from engine.observability.anomaly_trigger import get_anomaly_trigger

    try:
        triggers = get_anomaly_trigger().list_triggers(enabled_only=enabled_only)
        if not triggers:
            qualifier = "enabled " if enabled_only else ""
            return f"No {qualifier}anomaly triggers registered."
        return json.dumps(triggers, indent=2, default=str)
    except Exception as exc:
        logger.error("list_anomaly_triggers failed: %s", exc)
        return f"Error listing anomaly triggers: {exc}"


@skill(
    pack="self_improvement",
    description="View recent anomaly trigger firings. Optionally filter by rule_id. Shows what anomalies were matched and what tasks were scheduled.",
    category=SkillCategory.SYSTEM,
    tags=["anomaly", "trigger", "history"],
    cooldown=2.0,
)
def trigger_history_view(
    rule_id: str = "",
    hours: float = 24.0,
    limit: int = 100,
) -> str:
    """View recent trigger firing history.

    Args:
        rule_id: Filter to a specific trigger rule (empty = all rules).
        hours: Look-back window in hours.
        limit: Maximum number of results.

    Returns:
        List of trigger firings with timestamps, matched anomalies, and tasks.
    """
    from engine.observability.anomaly_trigger import get_anomaly_trigger

    try:
        history = get_anomaly_trigger().trigger_history(
            rule_id=rule_id or None,
            hours=hours,
            limit=limit,
        )
        if not history:
            qualifier = f" for rule '{rule_id}'" if rule_id else ""
            return f"No trigger firings{qualifier} in the last {hours:.0f} hours."
        return json.dumps(history, indent=2, default=str)
    except Exception as exc:
        logger.error("trigger_history_view failed: %s", exc)
        return f"Error fetching trigger history: {exc}"


@skill(
    pack="self_improvement",
    description="Get overall anomaly trigger system status — total rules, enabled count, recent firings, cooldown states.",
    category=SkillCategory.SYSTEM,
    tags=["anomaly", "trigger", "overview"],
    cooldown=2.0,
)
def trigger_overview() -> str:
    """Get a high-level status overview of the anomaly trigger system.

    Returns:
        JSON with rule counts, firing stats, and system health indicators.
    """
    from engine.observability.anomaly_trigger import get_anomaly_trigger

    try:
        status = get_anomaly_trigger().trigger_status()
        return json.dumps(status, indent=2, default=str)
    except Exception as exc:
        logger.error("trigger_overview failed: %s", exc)
        return f"Error fetching trigger status: {exc}"
