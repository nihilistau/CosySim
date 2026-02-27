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
