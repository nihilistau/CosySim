"""
Autonomy system skills for CosySim agents.

Skills for the self-improving autonomous pipeline: scheduler management,
news intelligence, NLM notebook fleet, knowledge quality, governance
validation, and task auto-generation.

These skills let LLM agents participate in the autonomy loop:
schedule tasks, fetch and curate news, manage notebooks, score knowledge,
validate code, and generate tasks from system events.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ── Lazy getters ──────────────────────────────────────────────────

def _scheduler():
    from engine.nexus.scheduler_daemon import get_scheduler_daemon
    return get_scheduler_daemon()


def _news():
    from engine.nexus.news_sources import get_news_registry
    return get_news_registry()


def _notebooks():
    from engine.nexus.nlm_notebook_manager import get_notebook_manager
    return get_notebook_manager()


def _governance():
    from engine.nexus.governance_rules import get_governance_manager
    return get_governance_manager()


def _tasks():
    from engine.nexus.task_scheduler import get_task_scheduler
    return get_task_scheduler()


def _diagnosis():
    from engine.nexus.auto_diagnosis import get_auto_diagnosis
    return get_auto_diagnosis()


def _flywheel():
    from engine.nexus.training_flywheel import get_training_flywheel
    return get_training_flywheel()


def _metrics():
    from engine.nexus.meta_metrics import get_meta_metrics
    return get_meta_metrics()


def _deep_storage():
    from engine.nexus.nlm_deep_storage import get_deep_storage
    return get_deep_storage()


# ═══════════════════════════════════════════════════════════════════
# SCHEDULER SKILLS
# ═══════════════════════════════════════════════════════════════════

@skill(pack="autonomy", description="Get status of all scheduled autonomous tasks",
       tags=["scheduler", "status", "autonomy"], category=SkillCategory.SYSTEM)
def scheduler_status() -> str:
    """Return running state, task list, next-due times, and run/error counts
    for the CosySim scheduler daemon."""
    return json.dumps(_scheduler().status(), indent=2, default=str)


@skill(pack="autonomy", description="Run a scheduled task immediately by ID",
       tags=["scheduler", "run", "autonomy"], category=SkillCategory.SYSTEM)
def scheduler_run_now(task_id: str) -> str:
    """Execute a registered scheduler task right now, regardless of schedule.
    Returns success/failure, duration, and result."""
    result = _scheduler().run_task(task_id)
    return json.dumps(result, indent=2, default=str)


@skill(pack="autonomy", description="List all registered scheduled tasks",
       tags=["scheduler", "list", "autonomy"], category=SkillCategory.SYSTEM)
def scheduler_list_tasks() -> str:
    """List all tasks registered in the scheduler daemon with their
    schedules, run counts, and enabled status."""
    return json.dumps(_scheduler().list_tasks(), indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# NEWS INTELLIGENCE SKILLS
# ═══════════════════════════════════════════════════════════════════

@skill(pack="autonomy", description="Fetch news from all enabled sources",
       tags=["news", "fetch", "autonomy"], category=SkillCategory.SYSTEM)
def news_fetch(category: str = "") -> str:
    """Fetch latest articles from all configured news sources.
    Optionally filter by category (ai_ml, python, llm, etc).
    Returns article titles, URLs, scores, and source info."""
    registry = _news()
    articles = registry.fetch_all(category=category or None)
    filtered = registry.filter_articles(articles)
    for a in filtered:
        a.score = registry.score_relevance(a)
    filtered.sort(key=lambda a: a.score, reverse=True)
    return json.dumps(
        [{"title": a.title, "url": a.url, "score": round(a.score, 2),
          "source": a.source_id, "category": a.category}
         for a in filtered[:20]],
        indent=2,
    )


@skill(pack="autonomy", description="Fetch news and store top articles in Nexus",
       tags=["news", "store", "nexus", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=30)
def news_fetch_and_store(category: str = "", max_articles: int = 20) -> str:
    """Fetch, filter, score, and store top news articles in Nexus.
    Also generates and stores a daily digest document."""
    registry = _news()
    articles = registry.fetch_all(category=category or None)
    filtered = registry.filter_articles(articles)
    for a in filtered:
        a.score = registry.score_relevance(a)
    filtered.sort(key=lambda a: a.score, reverse=True)

    stored = registry.store_to_nexus(filtered[:max_articles])
    digest = registry.generate_digest(filtered[:max_articles])

    # Store digest
    if filtered:
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            from datetime import datetime, timezone
            client.add_entry(
                title=f"News Digest: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                content=digest,
                content_type="document",
                category="news",
            )
        except Exception:
            pass

    return json.dumps({
        "fetched": len(articles),
        "filtered": len(filtered),
        "stored": stored,
    })


@skill(pack="autonomy", description="Generate a daily news digest from recent articles",
       tags=["news", "digest", "autonomy"], category=SkillCategory.SYSTEM)
def news_digest(category: str = "") -> str:
    """Fetch articles and generate a readable markdown digest.
    Returns the digest text for display or further processing."""
    registry = _news()
    articles = registry.fetch_all(category=category or None)
    filtered = registry.filter_articles(articles)
    for a in filtered:
        a.score = registry.score_relevance(a)
    filtered.sort(key=lambda a: a.score, reverse=True)
    return registry.generate_digest(filtered[:20])


@skill(pack="autonomy", description="List configured news sources and their stats",
       tags=["news", "sources", "autonomy"], category=SkillCategory.SYSTEM)
def news_list_sources() -> str:
    """Show all configured news sources with fetch counts, error rates,
    and enabled status."""
    return json.dumps(_news().stats(), indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# NLM NOTEBOOK MANAGEMENT SKILLS
# ═══════════════════════════════════════════════════════════════════

@skill(pack="autonomy", description="List all managed NLM notebooks with health status",
       tags=["nlm", "notebooks", "status", "autonomy"], category=SkillCategory.SYSTEM)
def nlm_notebook_list() -> str:
    """List all managed NotebookLM notebook slots with metadata:
    source counts, ages, last seeded/asked dates."""
    return json.dumps(_notebooks().health(), indent=2, default=str)


@skill(pack="autonomy", description="Seed NLM notebook from project documentation",
       tags=["nlm", "notebooks", "seed", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=60)
def nlm_notebook_seed_docs(slot_name: str = "cosysim-architecture") -> str:
    """Seed a NotebookLM notebook with all files from the docs/ directory.
    Creates the notebook if it doesn't exist."""
    return json.dumps(_notebooks().seed_from_docs(slot_name), indent=2, default=str)


@skill(pack="autonomy", description="Seed NLM notebook from engine source code",
       tags=["nlm", "notebooks", "seed", "code", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=60)
def nlm_notebook_seed_code(slot_name: str = "cosysim-codebase") -> str:
    """Seed a NotebookLM notebook with key engine source files.
    Creates the notebook if it doesn't exist."""
    return json.dumps(_notebooks().seed_from_code(slot_name), indent=2, default=str)


@skill(pack="autonomy", description="Create or get a research NLM notebook for a topic",
       tags=["nlm", "notebooks", "research", "autonomy"], category=SkillCategory.SYSTEM)
def nlm_notebook_research(topic: str) -> str:
    """Get or create a dedicated research notebook for a topic.
    Returns notebook metadata including the notebook_id for further NLM queries."""
    return json.dumps(_notebooks().get_or_create_research(topic), indent=2, default=str)


@skill(pack="autonomy", description="Rotate (delete & recreate) an NLM notebook slot",
       tags=["nlm", "notebooks", "rotate", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=30)
def nlm_notebook_rotate(slot_name: str) -> str:
    """Delete and recreate a notebook slot to refresh stale content.
    The old notebook and all its sources are deleted."""
    return json.dumps(_notebooks().rotate_notebook(slot_name), indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# KNOWLEDGE QUALITY SKILLS
# ═══════════════════════════════════════════════════════════════════

@skill(pack="autonomy", description="Run a full quality report on all Nexus knowledge entries",
       tags=["nexus", "quality", "scoring", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=30)
def nexus_quality_report() -> str:
    """Score all Nexus entries by freshness, quality, uniqueness, and
    completeness. Returns distribution, low-quality entries, duplicates,
    stale entries, and recommendations."""
    from engine.nexus.self_maintenance import quality_report
    return json.dumps(quality_report(), indent=2, default=str)


@skill(pack="autonomy", description="Run full Nexus maintenance (health, dedup, quality, compact)",
       tags=["nexus", "maintenance", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=60)
def nexus_full_maintenance(apply_changes: str = "false") -> str:
    """Run all Nexus maintenance tasks: health report, duplicate scan,
    quality scoring, and session compaction. Set apply_changes='true'
    to actually merge duplicates and compact sessions."""
    from engine.nexus.self_maintenance import nexus_full_maintenance as _impl
    dry_run = apply_changes.lower() not in ("true", "yes", "1")
    return json.dumps(_impl(dry_run=dry_run), indent=2, default=str)


@skill(pack="autonomy", description="Backup the entire Nexus knowledge base to JSON",
       tags=["nexus", "backup", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=60)
def nexus_backup(label: str = "") -> str:
    """Export all Nexus entries and Q&A pairs to a timestamped JSON backup file."""
    from engine.nexus.self_maintenance import nexus_backup as _impl
    return json.dumps(_impl(label=label), indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# GOVERNANCE SKILLS
# ═══════════════════════════════════════════════════════════════════

@skill(pack="autonomy", description="Validate a Python file against CosySim coding standards",
       tags=["governance", "validate", "coding", "autonomy"], category=SkillCategory.SYSTEM)
def governance_validate_file(filepath: str) -> str:
    """Check a Python file for violations of CosySim coding standards:
    absolute imports, no print(), logger required, type hints, docstrings,
    future annotations. Returns list of violations with line numbers."""
    violations = _governance().validate_file(filepath)
    return json.dumps(violations, indent=2, default=str)


@skill(pack="autonomy", description="Validate a commit message against CosySim standards",
       tags=["governance", "validate", "commit", "autonomy"], category=SkillCategory.SYSTEM)
def governance_validate_commit(message: str) -> str:
    """Check a commit message for conventional format and Co-authored-by
    trailer. Returns list of violations."""
    violations = _governance().validate_commit(message)
    return json.dumps(violations, indent=2, default=str)


@skill(pack="autonomy", description="Check if an agent is allowed to perform an operation",
       tags=["governance", "permissions", "agent", "autonomy"], category=SkillCategory.SYSTEM)
def governance_check_permissions(agent_id: str, operation: str) -> str:
    """Check whether an agent (identified by model name or 'copilot')
    is permitted to perform an operation (read/write/delete/admin).
    Permission rules are based on model parameter count."""
    allowed = _governance().check_permissions(agent_id, operation)
    return json.dumps({"agent_id": agent_id, "operation": operation, "allowed": allowed})


@skill(pack="autonomy", description="Enforce governance — block if violations found",
       tags=["governance", "enforce", "blocking", "autonomy"], category=SkillCategory.SYSTEM)
def governance_enforce(filepath: str = "", agent_id: str = "copilot",
                       operation: str = "write") -> str:
    """Actively enforce governance rules. Unlike governance_validate_file
    (advisory), this raises an error on reject/block violations. Use before
    writing files or performing restricted operations."""
    from engine.nexus.governance_rules import enforce_governance, GovernanceError
    try:
        violations = enforce_governance(
            filepath=filepath or None,
            agent_id=agent_id,
            operation=operation,
        )
        return json.dumps({"allowed": True, "advisory_violations": len(violations)})
    except GovernanceError as ge:
        return json.dumps({
            "allowed": False,
            "rule": ge.rule,
            "message": str(ge),
            "severity": ge.severity,
            "violation_count": len(ge.violations),
        }, default=str)


@skill(pack="autonomy", description="Seed all governance rules into Nexus",
       tags=["governance", "seed", "nexus", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=60)
def governance_seed_rules() -> str:
    """Seed all 18 governance rules (coding standards, testing, Nexus
    workflow, agent permissions, commit standards) into Nexus. Idempotent."""
    return json.dumps(_governance().seed_rules(), indent=2, default=str)


@skill(pack="autonomy", description="Get governance rule statistics",
       tags=["governance", "stats", "autonomy"], category=SkillCategory.SYSTEM)
def governance_stats() -> str:
    """Show rule counts grouped by scope and type."""
    return json.dumps(_governance().stats(), indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# TASK AUTO-GENERATION SKILLS
# ═══════════════════════════════════════════════════════════════════

@skill(pack="autonomy", description="Generate bug-fix tasks from pytest output",
       tags=["tasks", "testing", "auto-generate", "autonomy"], category=SkillCategory.SYSTEM)
def tasks_from_test_failures(test_output: str) -> str:
    """Parse pytest output and create bug-fix tasks for each FAILED test.
    Deduplicates against existing pending tasks."""
    tasks = _tasks().generate_from_test_failures(test_output)
    return json.dumps(
        [{"id": t.id, "title": t.title} for t in tasks],
        indent=2,
    )


@skill(pack="autonomy", description="Generate task from benchmark regression",
       tags=["tasks", "benchmark", "auto-generate", "autonomy"], category=SkillCategory.SYSTEM)
def tasks_from_benchmark(
    metric_name: str,
    current_value: str,
    baseline_value: str,
    threshold_pct: str = "10",
) -> str:
    """Create an optimization task if a benchmark metric has regressed
    beyond the threshold percentage. String params are converted to float."""
    task = _tasks().generate_from_benchmark(
        metric_name,
        float(current_value),
        float(baseline_value),
        float(threshold_pct),
    )
    if task:
        return json.dumps({"created": True, "id": task.id, "title": task.title})
    return json.dumps({"created": False, "reason": "No regression detected"})


@skill(pack="autonomy", description="Create a task from a predefined template",
       tags=["tasks", "template", "autonomy"], category=SkillCategory.SYSTEM)
def task_from_template(
    template_name: str,
    title: str = "",
    description: str = "",
    target_files: str = "",
) -> str:
    """Create a task from a template: bug-fix, feature, refactor, test,
    doc-update, skill-add, scene-polish, knowledge-refresh.
    target_files is a comma-separated list of file paths."""
    files = [f.strip() for f in target_files.split(",") if f.strip()] if target_files else []
    task = _tasks().from_template(
        template_name, title=title, description=description, target_files=files
    )
    return json.dumps({"id": task.id, "title": task.title, "template": template_name})


@skill(pack="autonomy", description="List available task templates",
       tags=["tasks", "templates", "autonomy"], category=SkillCategory.SYSTEM)
def task_list_templates() -> str:
    """Show all available task templates with their default priorities,
    complexities, and tags."""
    return json.dumps(_tasks().list_templates(), indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# AUTO-DIAGNOSIS SKILLS
# ═══════════════════════════════════════════════════════════════════

@skill(pack="autonomy", description="Diagnose test failures from pytest output",
       tags=["diagnosis", "testing", "auto-fix", "autonomy"], category=SkillCategory.SYSTEM)
def diagnose_failures(pytest_output: str) -> str:
    """Parse pytest output, diagnose each failure using Nexus cache and NLM,
    and create fix tasks for the agent fleet. Returns diagnoses with root cause,
    suggested fix, and confidence."""
    result = _diagnosis().full_pipeline(pytest_output)
    return json.dumps(result, indent=2, default=str)


@skill(pack="autonomy", description="Run a test file and auto-diagnose failures",
       tags=["diagnosis", "testing", "auto-fix", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=30)
def diagnose_test_file(test_file: str, test_name: str = "") -> str:
    """Run a specific test file, diagnose any failures, and create fix tasks.
    Returns diagnoses with root cause and suggested fix."""
    diagnoses = _diagnosis().diagnose_file(test_file, test_name)
    tasks = _diagnosis().create_fix_tasks(diagnoses)
    return json.dumps({
        "failures_found": len(diagnoses),
        "diagnoses": [
            {
                "test": f"{d.failure.test_file}::{d.failure.test_name}",
                "error": d.failure.error_type,
                "root_cause": d.root_cause[:200],
                "suggested_fix": d.suggested_fix[:200],
                "confidence": d.confidence,
                "source": d.source,
            }
            for d in diagnoses
        ],
        "tasks_created": len(tasks),
    }, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# TRAINING DATA FLYWHEEL SKILLS
# ═══════════════════════════════════════════════════════════════════

@skill(pack="autonomy", description="Collect a training example from a completed task",
       tags=["training", "flywheel", "collect", "autonomy"], category=SkillCategory.SYSTEM)
def training_collect_task(task_description: str, result: str, model: str = "") -> str:
    """Store a task completion as a training example for model fine-tuning.
    Records the task description as input and the result as output."""
    # Create a lightweight task-like object
    class _TaskProxy:
        def __init__(self, desc: str) -> None:
            self.title = desc[:100]
            self.description = desc
            self.tags: List[str] = []
            self.complexity = "medium"
            self.assigned_agent = model
            self.id = ""
            self.completed_at = 0.0
            self.created_at = 0.0
    example_id = _flywheel().collect_from_task(_TaskProxy(task_description), result, model)
    return json.dumps({"id": example_id, "source": "task"})


@skill(pack="autonomy", description="Collect a Q&A pair as training data",
       tags=["training", "flywheel", "collect", "autonomy"], category=SkillCategory.SYSTEM)
def training_collect_qa(question: str, answer: str, source: str = "manual") -> str:
    """Store a question-answer pair as instruction-tuning training data."""
    example_id = _flywheel().collect_from_qa(question, answer, source)
    return json.dumps({"id": example_id, "source": "qa"})


@skill(pack="autonomy", description="Export training data in JSONL format",
       tags=["training", "flywheel", "export", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=30)
def training_export_jsonl(min_quality: str = "0.5", source_filter: str = "") -> str:
    """Export training examples as JSONL for instruction tuning.
    Returns path and count of exported examples."""
    result = _flywheel().export_jsonl(
        min_quality=float(min_quality),
        source_filter=source_filter or "",
    )
    return json.dumps(result, indent=2, default=str)


@skill(pack="autonomy", description="Export training data in ShareGPT format",
       tags=["training", "flywheel", "export", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=30)
def training_export_sharegpt(min_quality: str = "0.5") -> str:
    """Export training examples in ShareGPT conversation format.
    Returns path and count of exported conversations."""
    result = _flywheel().export_sharegpt(min_quality=float(min_quality))
    return json.dumps(result, indent=2, default=str)


@skill(pack="autonomy", description="Export preference data in DPO format",
       tags=["training", "flywheel", "export", "dpo", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=30)
def training_export_dpo() -> str:
    """Export preference pairs (chosen/rejected) for DPO training.
    Returns path and count of exported pairs."""
    result = _flywheel().export_dpo()
    return json.dumps(result, indent=2, default=str)


@skill(pack="autonomy", description="Sync training data from Nexus Q&A pairs",
       tags=["training", "flywheel", "sync", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=60)
def training_sync_nexus() -> str:
    """Pull all Q&A pairs from Nexus into the training flywheel.
    Deduplicates against existing examples."""
    result = _flywheel().sync_from_nexus()
    return json.dumps(result, indent=2, default=str)


@skill(pack="autonomy", description="Get training flywheel statistics",
       tags=["training", "flywheel", "stats", "autonomy"], category=SkillCategory.SYSTEM)
def training_stats() -> str:
    """Show training data counts by source, total examples, export history."""
    return json.dumps(_flywheel().stats(), indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# META-METRICS DASHBOARD SKILLS
# ═══════════════════════════════════════════════════════════════════

@skill(pack="autonomy", description="Record a metric value",
       tags=["metrics", "record", "autonomy"], category=SkillCategory.SYSTEM)
def metrics_record(name: str, value: str) -> str:
    """Record a named metric value. Name uses dot-notation (e.g.
    'nexus.entries.total', 'llm.latency.avg_ms')."""
    _metrics().record(name, float(value))
    return json.dumps({"recorded": True, "name": name, "value": float(value)})


@skill(pack="autonomy", description="Get metric trend over time",
       tags=["metrics", "trend", "autonomy"], category=SkillCategory.SYSTEM)
def metrics_trend(name: str, days: str = "7") -> str:
    """Analyze a metric's trend: direction, rate of change, min, max, avg
    over the specified number of days."""
    return json.dumps(_metrics().trend(name, days=int(days)), indent=2, default=str)


@skill(pack="autonomy", description="Check all metrics for regressions",
       tags=["metrics", "regressions", "alerting", "autonomy"], category=SkillCategory.SYSTEM)
def metrics_check_regressions(threshold_pct: str = "10") -> str:
    """Compare recent metrics against baselines and flag regressions
    beyond the threshold percentage."""
    alerts = _metrics().check_regressions(threshold_pct=float(threshold_pct))
    return json.dumps(
        [{"metric": a.metric_name, "type": a.alert_type, "message": a.message,
          "current": a.current_value, "baseline": a.baseline_value}
         for a in alerts],
        indent=2, default=str,
    )


@skill(pack="autonomy", description="Generate a full system metrics dashboard",
       tags=["metrics", "dashboard", "autonomy"], category=SkillCategory.SYSTEM)
def metrics_dashboard(hours: str = "24") -> str:
    """Generate a markdown dashboard with all system metrics, trends,
    and active alerts."""
    return _metrics().dashboard(hours=int(hours))


@skill(pack="autonomy", description="Collect and record all system metrics now",
       tags=["metrics", "collect", "autonomy"], category=SkillCategory.SYSTEM,
       cooldown=30)
def metrics_collect_all() -> str:
    """Collect current system metrics (VRAM, Nexus stats, inference stats)
    and record them all. Returns the collected values."""
    return json.dumps(_metrics().collect_all(), indent=2, default=str)


@skill(pack="autonomy", description="Take a snapshot of all latest metrics",
       tags=["metrics", "snapshot", "autonomy"], category=SkillCategory.SYSTEM)
def metrics_snapshot() -> str:
    """Return the most recent value for every tracked metric."""
    return json.dumps(_metrics().snapshot(), indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# SYSTEM REFLECTION SKILLS
# ═══════════════════════════════════════════════════════════════════

def _reflection():
    from engine.nexus.system_reflection import get_system_reflection
    return get_system_reflection()


@skill(pack="autonomy", description="Run a system reflection analysis",
       tags=["reflection", "analysis", "autonomy"], category=SkillCategory.SYSTEM)
def reflection_run(period: str = "weekly", days: int = 7, use_nlm: bool = False) -> str:
    """Run a full reflection cycle: collect metrics, analyze patterns,
    generate insights, and create improvement tasks.

    Args:
        period: 'weekly' or 'monthly'.
        days: Number of days of data to analyze.
        use_nlm: Whether to use NotebookLM for deep analysis.
    """
    report = _reflection().run_reflection(period=period, days=days, use_nlm=use_nlm)
    return json.dumps({
        "report_id": report.report_id,
        "insight_count": len(report.insights),
        "tasks_created": len(report.tasks_created),
        "duration_seconds": report.duration_seconds,
    }, default=str)


@skill(pack="autonomy", description="Get recent reflection history",
       tags=["reflection", "history", "autonomy"], category=SkillCategory.SYSTEM)
def reflection_history(limit: int = 5) -> str:
    """Return summaries of recent system reflection reports."""
    return json.dumps(_reflection().get_history(limit=limit), default=str)


@skill(pack="autonomy", description="Get insights from the latest reflection",
       tags=["reflection", "insights", "autonomy"], category=SkillCategory.SYSTEM)
def reflection_latest_insights(limit: int = 10) -> str:
    """Return actionable insights from the most recent reflection."""
    return json.dumps(_reflection().latest_insights(limit=limit), default=str)


# ═══════════════════════════════════════════════════════════════════
# EXPERIMENT PROPOSAL SKILLS
# ═══════════════════════════════════════════════════════════════════

def _proposer():
    from engine.nexus.experiment_proposals import get_experiment_proposer
    return get_experiment_proposer()


@skill(pack="autonomy", description="Scan metrics and propose new experiments",
       tags=["experiment", "proposal", "autonomy"], category=SkillCategory.SYSTEM)
def experiment_scan_and_propose() -> str:
    """Scan current metrics against experiment templates and propose
    experiments for any triggered conditions."""
    proposals = _proposer().scan_and_propose()
    return json.dumps([
        {"proposal_id": p.proposal_id, "experiment_name": p.experiment_name,
         "trigger": p.trigger_metric, "priority": p.priority}
        for p in proposals
    ], default=str)


@skill(pack="autonomy", description="List experiment proposal history",
       tags=["experiment", "history", "autonomy"], category=SkillCategory.SYSTEM)
def experiment_list_proposals(status: str = "") -> str:
    """List experiment proposals. Filter by 'pending' or 'active'."""
    s = status if status else None
    return json.dumps(_proposer().get_proposals(status=s), default=str)


@skill(pack="autonomy", description="List experiment templates",
       tags=["experiment", "templates", "autonomy"], category=SkillCategory.SYSTEM)
def experiment_list_templates() -> str:
    """Return all registered experiment templates and their triggers."""
    return json.dumps(_proposer().list_templates(), default=str)


# ═══════════════════════════════════════════════════════════════════
# COPILOT SELF-CONFIG SKILLS
# ═══════════════════════════════════════════════════════════════════

def _copilot_cfg():
    from engine.nexus.copilot_self_config import get_copilot_config
    return get_copilot_config()


@skill(pack="autonomy", description="Sync all Copilot config to Nexus",
       tags=["copilot", "config", "sync", "autonomy"], category=SkillCategory.SYSTEM)
def copilot_sync_config() -> str:
    """Push instruction files, agent definitions, and hook scripts to Nexus."""
    return json.dumps(_copilot_cfg().sync_all_to_nexus(), default=str)


@skill(pack="autonomy", description="Get Copilot configuration status",
       tags=["copilot", "config", "status", "autonomy"], category=SkillCategory.SYSTEM)
def copilot_config_status() -> str:
    """Return counts of instruction files, agents, hooks, and preferences."""
    return json.dumps(_copilot_cfg().status(), default=str)


@skill(pack="autonomy", description="List Copilot instruction files",
       tags=["copilot", "instructions", "autonomy"], category=SkillCategory.SYSTEM)
def copilot_list_instructions() -> str:
    """List all Copilot instruction files with names and sizes."""
    return json.dumps(_copilot_cfg().list_instructions(), default=str)


@skill(pack="autonomy", description="List Copilot agent definitions",
       tags=["copilot", "agents", "autonomy"], category=SkillCategory.SYSTEM)
def copilot_list_agents() -> str:
    """List all Copilot agent definition files."""
    return json.dumps(_copilot_cfg().list_agents(), default=str)


# ═══════════════════════════════════════════════════════════════════
# KNOWLEDGE GRAPH SKILLS
# ═══════════════════════════════════════════════════════════════════

def _graph():
    from engine.nexus.knowledge_graph import get_knowledge_graph
    return get_knowledge_graph()


@skill(pack="autonomy", description="Build the knowledge graph from Nexus entries",
       tags=["knowledge", "graph", "build", "autonomy"], category=SkillCategory.SYSTEM)
def knowledge_graph_build() -> str:
    """Build the topic graph from all Nexus entries. Returns summary with
    topic count, edges, gaps, and clusters."""
    snap = _graph().build()
    return json.dumps({
        "topic_count": snap.topic_count,
        "edge_count": snap.edge_count,
        "gap_count": snap.gap_count,
        "top_topics": snap.top_topics[:10],
    }, default=str)


@skill(pack="autonomy", description="Detect knowledge gaps from the graph",
       tags=["knowledge", "gaps", "autonomy"], category=SkillCategory.SYSTEM)
def knowledge_graph_gaps() -> str:
    """Return topics that are underrepresented relative to related strong topics."""
    gaps = _graph().detect_gaps()
    return json.dumps([
        {"topic": g.topic, "entries": g.entry_count, "priority": g.priority,
         "research": g.suggested_research}
        for g in gaps
    ], default=str)


@skill(pack="autonomy", description="Get topic clusters from the knowledge graph",
       tags=["knowledge", "clusters", "autonomy"], category=SkillCategory.SYSTEM)
def knowledge_graph_clusters() -> str:
    """Return topic clusters based on co-occurrence in entries."""
    return json.dumps(_graph().cluster_topics(), default=str)


@skill(pack="autonomy", description="Search topics in the knowledge graph",
       tags=["knowledge", "search", "autonomy"], category=SkillCategory.SYSTEM)
def knowledge_graph_search(query: str) -> str:
    """Search for topics by name substring."""
    return json.dumps(_graph().search_topics(query), default=str)


@skill(pack="autonomy", description="Create research tasks for knowledge gaps",
       tags=["knowledge", "research", "tasks", "autonomy"], category=SkillCategory.SYSTEM)
def knowledge_graph_research_tasks() -> str:
    """Auto-create task scheduler entries for detected knowledge gaps."""
    return json.dumps(_graph().create_research_tasks(), default=str)


# ═══════════════════════════════════════════════════════════════════
# NLM DEEP STORAGE SKILLS
# ═══════════════════════════════════════════════════════════════════

@skill(pack="autonomy", description="Archive a single NLM notebook into Nexus deep storage",
       tags=["nlm", "deep_storage", "archive", "autonomy"], category=SkillCategory.SYSTEM)
def deep_storage_archive(notebook_id: str) -> str:
    """Archive all content from an NLM notebook (metadata, sources, conversations,
    notes) into Nexus deep storage with chain IDs for retrieval."""
    return json.dumps(_deep_storage().archive_notebook(notebook_id), default=str)


@skill(pack="autonomy", description="Archive ALL NLM notebooks into Nexus deep storage",
       tags=["nlm", "deep_storage", "archive_all", "autonomy"], category=SkillCategory.SYSTEM)
def deep_storage_archive_all() -> str:
    """Pull every NLM notebook into Nexus deep storage. Stores metadata, sources,
    conversations, notes, and generated content for each notebook."""
    return json.dumps(_deep_storage().archive_all(), default=str)


@skill(pack="autonomy", description="Archive notebook content from a browser HAR capture",
       tags=["nlm", "deep_storage", "har", "autonomy"], category=SkillCategory.SYSTEM)
def deep_storage_from_har(har_path: str) -> str:
    """Extract notebook content from a browser HAR file and store in deep storage."""
    return json.dumps(_deep_storage().archive_from_har(har_path), default=str)


@skill(pack="autonomy", description="Retrieve all archived content for a notebook",
       tags=["nlm", "deep_storage", "retrieve", "autonomy"], category=SkillCategory.SYSTEM)
def deep_storage_retrieve(notebook_id: str) -> str:
    """Get all archived content for a notebook including metadata, sources,
    conversations, and notes."""
    return json.dumps(_deep_storage().retrieve(notebook_id), default=str)


@skill(pack="autonomy", description="List all archived NLM notebooks",
       tags=["nlm", "deep_storage", "list", "autonomy"], category=SkillCategory.SYSTEM)
def deep_storage_list() -> str:
    """List all notebooks that have been archived in deep storage."""
    return json.dumps(_deep_storage().list_archives(), default=str)


@skill(pack="autonomy", description="Search across all archived NLM conversations",
       tags=["nlm", "deep_storage", "search", "autonomy"], category=SkillCategory.SYSTEM)
def deep_storage_search_conversations(query: str) -> str:
    """Search for conversations across all archived notebooks by keyword."""
    return json.dumps(_deep_storage().search_conversations(query), default=str)


@skill(pack="autonomy", description="Get a full conversation chain by chain ID",
       tags=["nlm", "deep_storage", "chain", "autonomy"], category=SkillCategory.SYSTEM)
def deep_storage_get_chain(chain_id: str) -> str:
    """Retrieve all entries in a conversation chain, ordered chronologically."""
    return json.dumps(_deep_storage().get_chain(chain_id), default=str)


@skill(pack="autonomy", description="Store a conversation in NLM deep storage",
       tags=["nlm", "deep_storage", "conversation", "autonomy"], category=SkillCategory.SYSTEM)
def deep_storage_store_conversation(
    notebook_id: str,
    messages_json: str,
    topic: str = "",
) -> str:
    """Store a conversation (list of {role, content} messages) in deep storage
    with a unique chain ID for later retrieval."""
    messages = json.loads(messages_json)
    return json.dumps(
        _deep_storage().store_conversation(notebook_id, messages, topic=topic),
        default=str,
    )


@skill(pack="autonomy", description="Get NLM deep storage statistics",
       tags=["nlm", "deep_storage", "stats", "autonomy"], category=SkillCategory.SYSTEM)
def deep_storage_stats() -> str:
    """Get statistics on archived notebooks, entries stored, and storage usage."""
    return json.dumps(_deep_storage().stats(), default=str)


# ── Phone Assistant Skills ──────────────────────────────────────────────


def _phone_assistant() -> Any:
    """Lazy accessor for the phone assistant."""
    from engine.assistant.phone_assistant import get_phone_assistant
    return get_phone_assistant()


@skill(pack="autonomy", description="Chat with the phone assistant (cascading tiers)",
       tags=["assistant", "phone", "chat", "autonomy"], category=SkillCategory.COMMUNICATION)
def phone_assistant_chat(message: str, mode: str = "", voice: bool = False) -> str:
    """Send a message to the phone assistant. Mode: auto/passthrough/offline."""
    result = _phone_assistant().chat(message, mode=mode or None, voice=voice)
    return json.dumps(result, default=str)


@skill(pack="autonomy", description="Get phone assistant status and connectivity",
       tags=["assistant", "phone", "status", "autonomy"], category=SkillCategory.SYSTEM)
def phone_assistant_status() -> str:
    """Check phone assistant routing mode, connectivity, and hit rates."""
    return json.dumps(_phone_assistant().status(), default=str)


@skill(pack="autonomy", description="Set phone assistant routing mode",
       tags=["assistant", "phone", "mode", "autonomy"], category=SkillCategory.SYSTEM)
def phone_assistant_set_mode(mode: str) -> str:
    """Set routing mode: auto (cascade all), passthrough (server only), offline (local only)."""
    result = _phone_assistant().set_mode(mode)
    return json.dumps({"mode": result})
