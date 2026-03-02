"""
CosySim DevTools MCP Server — Nexus, Copilot, System, and Agent tools.

Separated from the main CosySim MCP server to keep game/scene tools
distinct from development workflow tools.

Run standalone::

    python -m engine.mcp.devtools_server          # stdio mode
    python -m engine.mcp.devtools_server --http    # HTTP/SSE mode
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Optional

from engine.paths import ROOT as _root

if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from fastmcp import FastMCP
from engine.mcp.tools.kg_tools import (
    knowledge_graph_build_impl,
    knowledge_graph_gaps_impl,
    knowledge_graph_clusters_impl,
    knowledge_graph_search_impl,
    knowledge_graph_research_tasks_impl,
)
from engine.mcp.tools.deep_storage_tools import (
    deep_storage_archive_impl,
    deep_storage_archive_all_impl,
    deep_storage_from_har_impl,
    deep_storage_retrieve_impl,
    deep_storage_list_impl,
    deep_storage_search_impl,
    deep_storage_chain_impl,
    deep_storage_stats_impl,
)
from engine.mcp.tools.copilot_tools import (
    copilot_store_snippet_impl,
    copilot_store_discovery_impl,
    copilot_log_progress_impl,
    copilot_context_primer_impl,
    copilot_local_model_guide_impl,
    copilot_sync_config_impl,
    copilot_config_status_impl,
    copilot_list_instructions_impl,
    copilot_list_agents_impl,
)
from engine.mcp.tools.agent_tools import (
    agent_create_task_impl,
    agent_update_task_impl,
    agent_complete_task_impl,
    agent_list_tasks_impl,
)
from engine.mcp.tools.notebook_tools import (
    nlm_notebook_list_impl,
    nlm_notebook_seed_impl,
    nlm_notebook_rotate_impl,
)
from engine.mcp.tools.nexus_tools import (
    nexus_search_impl,
    nexus_ask_impl,
    nexus_add_impl,
    nexus_add_qa_impl,
    nexus_get_rules_impl,
    nexus_store_prompt_impl,
    nexus_get_prompts_impl,
    nexus_research_impl,
    nexus_converse_impl,
    nexus_finish_research_impl,
    nexus_import_youtube_impl,
    nexus_log_session_impl,
    nexus_status_impl,
    nexus_list_plugins_impl,
    nexus_remember_impl,
    nexus_recall_impl,
    nexus_memory_context_impl,
    nexus_distill_impl,
    nexus_export_session_impl,
    nexus_maintain_impl,
    nexus_smart_query_impl,
    nexus_router_stats_impl,
    nexus_quality_report_impl,
)
from engine.mcp.tools.ha_tools import (
    ha_connect_impl,
    ha_list_entities_impl,
    ha_get_state_impl,
    ha_toggle_impl,
    ha_turn_on_impl,
    ha_turn_off_impl,
    ha_call_service_impl,
    ha_send_notification_impl,
    ha_phone_sensors_impl,
    ha_push_metrics_impl,
    ha_status_impl,
)

from engine.mcp.tools.training_tools import (
    capture_training_data_impl,
    generate_content_impl,
    training_stats_impl,
    training_export_impl,
    training_sync_nexus_impl,
    finetune_submit_impl,
    finetune_run_next_impl,
    finetune_list_jobs_impl,
    finetune_build_dataset_impl,
    finetune_dataset_status_impl,
    model_registry_list_impl,
    model_benchmark_run_impl,
    model_benchmark_leaderboard_impl,
    model_promote_impl,
    teacher_generate_dataset_impl,
    finetuned_router_status_impl,
    finetuned_router_load_registry_impl,
)

from engine.mcp.tools.metrics_tools import (
    metrics_dashboard_impl,
    metrics_collect_all_impl,
    metrics_check_regressions_impl,
    metrics_snapshot_impl,
    reflection_run_impl,
    reflection_history_impl,
    reflection_latest_insights_impl,
    experiment_scan_and_propose_impl,
    experiment_list_proposals_impl,
    experiment_list_templates_impl,
)
from engine.mcp.tools.notebook_node_tools import (
    notebooklm_node_ask_impl,
    notebooklm_node_batch_ask_impl,
    notebooklm_node_add_source_impl,
    notebooklm_node_create_notebook_impl,
    notebooklm_node_list_notebooks_impl,
    notebooklm_node_generate_audio_impl,
    notebooklm_node_generate_video_impl,
    notebooklm_node_extract_tables_impl,
    notebooklm_node_chat_history_impl,
    notebooklm_node_health_impl,
    notebooklm_node_setup_auth_impl,
    notebooklm_node_sync_nexus_impl,
    master_notebook_build_impl,
    master_notebook_status_impl,
    master_notebook_reset_impl,
    master_notebook_list_sources_impl,
)
from engine.mcp.tools.local_agent_tools import (
    local_agent_get_tasks_impl,
    local_agent_claim_task_impl,
    local_agent_task_context_impl,
    local_agent_complete_task_impl,
    local_agent_fail_task_impl,
    local_agent_manifest_impl,
)

logger = logging.getLogger(__name__)

# ── Server instance ────────────────────────────────────────────────────

mcp = FastMCP(
    "CosySim-DevTools",
    instructions=(
        "CosySim DevTools server provides Nexus knowledge management, "
        "Copilot integration, system monitoring, skill discovery, "
        "and agent task management tools."
    ),
)


# ── Lazy service getters ──────────────────────────────────────────────


def _get_nexus():
    """Lazy Nexus client getter."""
    try:
        from engine.nexus.client import get_nexus_client

        return get_nexus_client()
    except Exception as e:
        logger.warning("Nexus client unavailable: %s", e)
        return None


def _get_config():
    from engine.config import get_config

    return get_config()


# ═══════════════════════════════════════════════════════════════════════
# SYSTEM STATUS & DISCOVERY
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def system_status() -> str:
    """Get comprehensive CosySim system status — services, models,
    scenes, skills, orchestrator, and Nexus connectivity."""
    from engine.mcp.tools.system_tools import system_status_impl

    return system_status_impl(_get_nexus, _get_config).model_dump_json(indent=2)


@mcp.tool()
def list_all_skills() -> str:
    """List all registered MCP skills grouped by pack."""
    from engine.mcp.tools.system_tools import list_all_skills_impl

    return list_all_skills_impl().model_dump_json(indent=2)


@mcp.tool()
def get_skill_info(skill_name: str) -> str:
    """Get detailed information about a specific MCP skill."""
    from engine.mcp.tools.system_tools import get_skill_info_impl

    return get_skill_info_impl(skill_name).model_dump_json(indent=2)


@mcp.tool()
def get_benchmark_stats() -> str:
    """Get performance benchmark statistics."""
    from engine.mcp.tools.utility_tools import get_benchmark_stats_logic

    return get_benchmark_stats_logic()


# ═══════════════════════════════════════════════════════════════════════
# NEXUS BRIDGE — Knowledge management
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def nexus_search(query: str, limit: int = 10) -> str:
    return nexus_search_impl(query=query, limit=limit, nexus_getter=_get_nexus)


@mcp.tool()
def nexus_ask(question: str, depth: str = "auto", category: str = "") -> str:
    return nexus_ask_impl(
        question=question, depth=depth, category=category, nexus_getter=_get_nexus
    )


@mcp.tool()
def nexus_add(
    title: str,
    content: str,
    content_type: str = "note",
    category: str = "",
    tags: str = "",
) -> str:
    return nexus_add_impl(
        title=title,
        content=content,
        content_type=content_type,
        category=category,
        tags=tags,
        nexus_getter=_get_nexus,
    )


@mcp.tool()
def nexus_add_qa(question: str, answer: str, category: str = "", tags: str = "") -> str:
    return nexus_add_qa_impl(
        question=question,
        answer=answer,
        category=category,
        tags=tags,
        nexus_getter=_get_nexus,
    )


@mcp.tool()
def nexus_get_rules(scope: str = "", rule_type: str = "") -> str:
    return nexus_get_rules_impl(
        scope=scope, rule_type=rule_type, nexus_getter=_get_nexus
    )


@mcp.tool()
def nexus_store_prompt(
    name: str, content: str, category: str = "", version: str = ""
) -> str:
    return nexus_store_prompt_impl(
        name=name,
        content=content,
        category=category,
        version=version,
        nexus_getter=_get_nexus,
    )


@mcp.tool()
def nexus_get_prompts(category: str = "", name: str = "") -> str:
    return nexus_get_prompts_impl(category=category, name=name, nexus_getter=_get_nexus)


@mcp.tool()
def nexus_research(question: str) -> str:
    return nexus_research_impl(question=question, nexus_getter=_get_nexus)


@mcp.tool()
def nexus_converse(research_id: str, message: str) -> str:
    return nexus_converse_impl(
        research_id=research_id, message=message, nexus_getter=_get_nexus
    )


@mcp.tool()
def nexus_finish_research(research_id: str) -> str:
    return nexus_finish_research_impl(research_id=research_id, nexus_getter=_get_nexus)


@mcp.tool()
def nexus_import_youtube(url: str, category: str = "", tags: str = "") -> str:
    return nexus_import_youtube_impl(
        url=url, category=category, tags=tags, nexus_getter=_get_nexus
    )


@mcp.tool()
def nexus_log_session(
    project: str = "CosySim", repo: str = "", branch: str = ""
) -> str:
    return nexus_log_session_impl(
        project=project, repo=repo, branch=branch, nexus_getter=_get_nexus
    )


@mcp.tool()
def nexus_status() -> str:
    return nexus_status_impl(nexus_getter=_get_nexus)


@mcp.tool()
def nexus_list_plugins(scope: str = "") -> str:
    return nexus_list_plugins_impl(scope=scope, nexus_getter=_get_nexus)


# ═══════════════════════════════════════════════════════════════════════
# NEXUS MEMORY — Agent memory management
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def nexus_remember(
    content: str,
    agent_id: str = "copilot",
    memory_type: str = "observation",
    importance: float = 0.5,
) -> str:
    return nexus_remember_impl(
        content=content,
        agent_id=agent_id,
        memory_type=memory_type,
        importance=importance,
    )


@mcp.tool()
def nexus_recall(query: str, agent_id: str = "copilot", limit: int = 5) -> str:
    return nexus_recall_impl(query=query, agent_id=agent_id, limit=limit)


@mcp.tool()
def nexus_memory_context(agent_id: str = "copilot", max_tokens: int = 500) -> str:
    return nexus_memory_context_impl(agent_id=agent_id, max_tokens=max_tokens)


# ═══════════════════════════════════════════════════════════════════════
# NEXUS MAINTENANCE — Seeding, distillation, export
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def seed_nexus(source: str = "all") -> str:
    """Seed Nexus with project knowledge. Idempotent — safe to run repeatedly."""
    try:
        from engine.nexus.nexus_seeder import NexusSeeder

        seeder = NexusSeeder()
        valid = {"docs", "qa", "rules", "prompts", "conventions", "all"}
        if source not in valid:
            return json.dumps(
                {"error": f"Invalid source '{source}'. Use: {sorted(valid)}"}
            )
        counts = seeder.seed(source)
        return json.dumps({"status": "ok", "source": source, "created": counts})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_distill(action: str = "stats") -> str:
    return nexus_distill_impl(action=action)


@mcp.tool()
def nexus_export_session() -> str:
    return nexus_export_session_impl()


@mcp.tool()
def nexus_maintain(action: str = "health") -> str:
    return nexus_maintain_impl(action=action)


@mcp.tool()
def nexus_smart_query(
    question: str, min_confidence: float = 0.3, use_llm: bool = True, category: str = ""
) -> str:
    return nexus_smart_query_impl(
        question=question,
        min_confidence=min_confidence,
        use_llm=use_llm,
        category=category,
    )


@mcp.tool()
def nexus_router_stats() -> str:
    return nexus_router_stats_impl()


# ═══════════════════════════════════════════════════════════════════════
# TRAINING & CONTENT — Data capture and generation
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def capture_training_data(
    user_message: str,
    agent_response: str,
    dataset_type: str = "conversation",
    quality_score: float = 0.7,
    character_id: str = "",
) -> str:
    return capture_training_data_impl(
        user_message=user_message,
        agent_response=agent_response,
        dataset_type=dataset_type,
        quality_score=quality_score,
        character_id=character_id,
    )


@mcp.tool()
def generate_content(character_id: str, content_type: str = "greetings") -> str:
    return generate_content_impl(character_id=character_id, content_type=content_type)


@mcp.tool()
def copilot_store_snippet(
    title: str, code: str, language: str = "python", tags: str = ""
) -> str:
    return copilot_store_snippet_impl(
        title=title, code=code, language=language, tags=tags
    )


@mcp.tool()
def copilot_store_discovery(
    title: str, finding: str, category: str = "debugging"
) -> str:
    return copilot_store_discovery_impl(title=title, finding=finding, category=category)


@mcp.tool()
def copilot_log_progress(
    task: str,
    status: str = "completed",
    details: str = "",
    tests_passed: int = 0,
    commit_sha: str = "",
) -> str:
    return copilot_log_progress_impl(
        task=task,
        status=status,
        details=details,
        tests_passed=tests_passed,
        commit_sha=commit_sha,
    )


@mcp.tool()
def copilot_context_primer(project: str = "CosySim") -> str:
    return copilot_context_primer_impl(project=project)


@mcp.tool()
def copilot_local_model_guide(task_type: str = "general") -> str:
    return copilot_local_model_guide_impl(task_type=task_type)


# ═══════════════════════════════════════════════════════════════════════
# AGENT TASK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def agent_create_task(
    title: str,
    description: str = "",
    agent: str = "copilot",
    priority: str = "normal",
    tags: str = "",
) -> str:
    return agent_create_task_impl(
        title=title, description=description, agent=agent, priority=priority, tags=tags
    )


@mcp.tool()
def agent_update_task(task_id: str, status: str) -> str:
    return agent_update_task_impl(task_id=task_id, status=status)


@mcp.tool()
def agent_complete_task(task_id: str, summary: str = "") -> str:
    return agent_complete_task_impl(task_id=task_id, summary=summary)


@mcp.tool()
def agent_list_tasks(status: str = "", agent: str = "", limit: int = 20) -> str:
    return agent_list_tasks_impl(status=status, agent=agent, limit=limit)


# ═══════════════════════════════════════════════════════════════════════
# AUTONOMY — SCHEDULER, NEWS, NOTEBOOKS, QUALITY, GOVERNANCE
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
def scheduler_status() -> str:
    """Get status of all scheduled autonomous tasks — running state,
    next-due times, run/error counts, and last results."""
    try:
        from engine.nexus.scheduler_daemon import get_scheduler_daemon

        return json.dumps(get_scheduler_daemon().status(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def scheduler_run_now(task_id: str) -> str:
    """Run a scheduled task immediately by ID. Returns success/failure
    with duration and result details."""
    try:
        from engine.nexus.scheduler_daemon import get_scheduler_daemon

        return json.dumps(
            get_scheduler_daemon().run_task(task_id), indent=2, default=str
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def news_fetch(category: str = "") -> str:
    """Fetch, filter, and score news from all enabled sources. Returns
    top 20 articles with title, URL, relevance score, and source."""
    try:
        from engine.nexus.news_sources import get_news_registry

        registry = get_news_registry()
        articles = registry.fetch_all(category=category or None)
        filtered = registry.filter_articles(articles)
        for a in filtered:
            a.score = registry.score_relevance(a)
        filtered.sort(key=lambda a: a.score, reverse=True)
        return json.dumps(
            [
                {
                    "title": a.title,
                    "url": a.url,
                    "score": round(a.score, 2),
                    "source": a.source_id,
                    "category": a.category,
                }
                for a in filtered[:20]
            ],
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def news_fetch_and_store(category: str = "", max_articles: int = 20) -> str:
    """Full news pipeline: fetch → filter → score → store in Nexus → generate digest.
    Returns counts of fetched, filtered, and stored articles."""
    try:
        from engine.nexus.news_sources import get_news_registry

        registry = get_news_registry()
        articles = registry.fetch_all(category=category or None)
        filtered = registry.filter_articles(articles)
        for a in filtered:
            a.score = registry.score_relevance(a)
        filtered.sort(key=lambda a: a.score, reverse=True)
        stored = registry.store_to_nexus(filtered[:max_articles])
        digest = registry.generate_digest(filtered[:max_articles])
        if filtered:
            try:
                client = _get_nexus()
                if client:
                    from datetime import datetime, timezone

                    client.add_entry(
                        title=f"News Digest: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                        content=digest,
                        content_type="document",
                        category="news",
                    )
            except Exception:
                pass
        return json.dumps(
            {"fetched": len(articles), "filtered": len(filtered), "stored": stored}
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def news_digest(category: str = "") -> str:
    """Generate a markdown daily news digest from configured sources."""
    try:
        from engine.nexus.news_sources import get_news_registry

        registry = get_news_registry()
        articles = registry.fetch_all(category=category or None)
        filtered = registry.filter_articles(articles)
        for a in filtered:
            a.score = registry.score_relevance(a)
        filtered.sort(key=lambda a: a.score, reverse=True)
        return registry.generate_digest(filtered[:20])
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def news_sources() -> str:
    """List all configured news sources with fetch stats and error rates."""
    try:
        from engine.nexus.news_sources import get_news_registry

        return json.dumps(get_news_registry().stats(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nlm_notebook_list() -> str:
    return nlm_notebook_list_impl()


@mcp.tool()
def nlm_notebook_seed(
    slot_name: str = "cosysim-architecture", source_type: str = "docs"
) -> str:
    return nlm_notebook_seed_impl(slot_name=slot_name, source_type=source_type)


@mcp.tool()
def nlm_notebook_rotate(slot_name: str) -> str:
    return nlm_notebook_rotate_impl(slot_name=slot_name)


@mcp.tool()
def nexus_quality_report() -> str:
    return nexus_quality_report_impl()


@mcp.tool()
def governance_validate(filepath: str) -> str:
    """Validate a Python file against all CosySim coding standards.
    Returns violations with rule names, severity, messages, and line numbers."""
    try:
        from engine.nexus.governance_rules import get_governance_manager

        return json.dumps(
            get_governance_manager().validate_file(filepath), indent=2, default=str
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def governance_seed() -> str:
    """Seed all 18 governance rules into Nexus (idempotent). Rules cover
    coding standards, testing, Nexus workflow, agent permissions, and commits."""
    try:
        from engine.nexus.governance_rules import get_governance_manager

        return json.dumps(get_governance_manager().seed_rules(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def governance_check_permission(agent_id: str, operation: str) -> str:
    """Check if an agent can perform an operation. Agent permission rules
    are based on model parameter count (sub-1B=read-only, 1-10B=write,
    10B+/Copilot=full access)."""
    try:
        from engine.nexus.governance_rules import get_governance_manager

        allowed = get_governance_manager().check_permissions(agent_id, operation)
        return json.dumps(
            {"agent_id": agent_id, "operation": operation, "allowed": allowed}
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def governance_enforce(
    filepath: str = "",
    agent_id: str = "copilot",
    operation: str = "write",
    commit_message: str = "",
) -> str:
    """Enforce governance rules — raises error if blocking violations found.
    Unlike governance_validate (advisory), this blocks on reject/block severity."""
    try:
        from engine.nexus.governance_rules import enforce_governance, GovernanceError

        try:
            violations = enforce_governance(
                filepath=filepath or None,
                agent_id=agent_id,
                operation=operation,
                commit_message=commit_message or None,
            )
            return json.dumps({"allowed": True, "advisory_violations": len(violations)})
        except GovernanceError as ge:
            return json.dumps(
                {
                    "allowed": False,
                    "rule": ge.rule,
                    "message": str(ge),
                    "severity": ge.severity,
                    "violations": ge.violations,
                },
                default=str,
            )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def task_auto_generate(source: str = "quality") -> str:
    """Auto-generate tasks from system events. source: 'quality' (from stale
    Nexus entries), 'tests' (run and parse test failures). Returns created tasks."""
    try:
        from engine.nexus.task_scheduler import get_task_scheduler

        scheduler = get_task_scheduler()
        tasks = []
        if source == "quality":
            from engine.nexus.self_maintenance import quality_report

            report = quality_report()
            stale = [
                {"id": s.get("entry_id", ""), "title": s.get("title", "")}
                for s in report.get("stale", [])[:5]
            ]
            tasks = scheduler.generate_from_stale_knowledge(stale)
        elif source == "tests":
            import subprocess, sys

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/",
                    "--tb=line",
                    "-q",
                    "--ignore=tests/test_agent_loop.py",
                    "--ignore=tests/live_wire_test.py",
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            tasks = scheduler.generate_from_test_failures(result.stdout + result.stderr)
        return json.dumps(
            {
                "source": source,
                "tasks_created": len(tasks),
                "tasks": [{"id": t.id, "title": t.title} for t in tasks],
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def task_from_template(
    template_name: str, title: str = "", description: str = "", target_files: str = ""
) -> str:
    """Create a task from a template: bug-fix, feature, refactor, test,
    doc-update, skill-add, scene-polish, knowledge-refresh.
    target_files is comma-separated."""
    try:
        from engine.nexus.task_scheduler import get_task_scheduler

        files = (
            [f.strip() for f in target_files.split(",") if f.strip()]
            if target_files
            else []
        )
        task = get_task_scheduler().from_template(
            template_name, title=title, description=description, target_files=files
        )
        return json.dumps(
            {"id": task.id, "title": task.title, "template": template_name}
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def task_list_templates() -> str:
    """List all available task templates with priorities and descriptions."""
    try:
        from engine.nexus.task_scheduler import get_task_scheduler

        return json.dumps(get_task_scheduler().list_templates(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def diagnose_test_failures(pytest_output: str) -> str:
    """Auto-diagnose test failures from pytest output. Parses failures,
    checks Nexus for prior fixes, applies heuristics, asks NLM, stores
    diagnoses, and creates fix tasks. Returns root causes and suggested fixes."""
    try:
        from engine.nexus.auto_diagnosis import get_auto_diagnosis

        return json.dumps(
            get_auto_diagnosis().full_pipeline(pytest_output), indent=2, default=str
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def diagnose_test_file(test_file: str, test_name: str = "") -> str:
    """Run a test file, auto-diagnose failures, and create fix tasks.
    Returns diagnoses with root cause, confidence, and suggested fixes."""
    try:
        from engine.nexus.auto_diagnosis import get_auto_diagnosis

        diag = get_auto_diagnosis()
        diagnoses = diag.diagnose_file(test_file, test_name)
        tasks = diag.create_fix_tasks(diagnoses)
        return json.dumps(
            {
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
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def training_stats() -> str:
    return training_stats_impl()


@mcp.tool()
def training_export(format: str = "jsonl", min_quality: float = 0.5) -> str:
    return training_export_impl(format=format, min_quality=min_quality)


@mcp.tool()
def training_sync_nexus() -> str:
    return training_sync_nexus_impl()


@mcp.tool()
def metrics_dashboard(hours: int = 24) -> str:
    return metrics_dashboard_impl(hours=hours)


@mcp.tool()
def metrics_collect_all() -> str:
    return metrics_collect_all_impl()


@mcp.tool()
def metrics_check_regressions(threshold_pct: float = 10.0) -> str:
    return metrics_check_regressions_impl(threshold_pct=threshold_pct)


@mcp.tool()
def metrics_snapshot() -> str:
    return metrics_snapshot_impl()


@mcp.tool()
def reflection_run(period: str = "weekly", days: int = 7, use_nlm: bool = False) -> str:
    return reflection_run_impl(period=period, days=days, use_nlm=use_nlm)


@mcp.tool()
def reflection_history(limit: int = 5) -> str:
    return reflection_history_impl(limit=limit)


@mcp.tool()
def reflection_latest_insights(limit: int = 10) -> str:
    return reflection_latest_insights_impl(limit=limit)


@mcp.tool()
def experiment_scan_and_propose() -> str:
    return experiment_scan_and_propose_impl()


@mcp.tool()
def experiment_list_proposals(status: str = "") -> str:
    return experiment_list_proposals_impl(status=status)


@mcp.tool()
def experiment_list_templates() -> str:
    return experiment_list_templates_impl()


@mcp.tool()
def copilot_sync_config() -> str:
    return copilot_sync_config_impl()


@mcp.tool()
def copilot_config_status() -> str:
    return copilot_config_status_impl()


@mcp.tool()
def copilot_list_instructions() -> str:
    return copilot_list_instructions_impl()


@mcp.tool()
def copilot_list_agents() -> str:
    return copilot_list_agents_impl()


# ── Knowledge Graph Tools ────────────────────────────────────────────


@mcp.tool()
def knowledge_graph_build() -> str:
    return knowledge_graph_build_impl()


@mcp.tool()
def knowledge_graph_gaps() -> str:
    return knowledge_graph_gaps_impl()


@mcp.tool()
def knowledge_graph_clusters() -> str:
    return knowledge_graph_clusters_impl()


@mcp.tool()
def knowledge_graph_search(query: str) -> str:
    return knowledge_graph_search_impl(query=query)


@mcp.tool()
def knowledge_graph_research_tasks() -> str:
    return knowledge_graph_research_tasks_impl()


# ── Home Assistant Tools ─────────────────────────────────────────────


@mcp.tool()
def ha_connect() -> str:
    """Connect to Home Assistant and discover entities."""
    return ha_connect_impl()


@mcp.tool()
def ha_list_entities(domain: str = "", search: str = "") -> str:
    """List Home Assistant entities filtered by domain or search term."""
    return ha_list_entities_impl(domain=domain, search=search)


@mcp.tool()
def ha_get_state(entity_id: str) -> str:
    """Get current state of a Home Assistant entity."""
    return ha_get_state_impl(entity_id=entity_id)


@mcp.tool()
def ha_toggle(entity_id: str) -> str:
    """Toggle a Home Assistant device on/off."""
    return ha_toggle_impl(entity_id=entity_id)


@mcp.tool()
def ha_turn_on(entity_id: str) -> str:
    """Turn on a Home Assistant device."""
    return ha_turn_on_impl(entity_id=entity_id)


@mcp.tool()
def ha_turn_off(entity_id: str) -> str:
    """Turn off a Home Assistant device."""
    return ha_turn_off_impl(entity_id=entity_id)


@mcp.tool()
def ha_call_service(
    domain: str, service: str, entity_id: str = "", data_json: str = "{}"
) -> str:
    """Call any Home Assistant service with custom parameters."""
    return ha_call_service_impl(
        domain=domain, service=service, entity_id=entity_id, data_json=data_json
    )


@mcp.tool()
def ha_send_notification(message: str, title: str = "") -> str:
    """Send a push notification to the user's phone via Home Assistant."""
    return ha_send_notification_impl(message=message, title=title)


@mcp.tool()
def ha_phone_sensors() -> str:
    """Read all phone sensors exposed via HA Companion (battery, wifi, GPS, etc.)."""
    return ha_phone_sensors_impl()


@mcp.tool()
def ha_push_metrics() -> str:
    """Push CosySim system metrics to Home Assistant as sensor entities."""
    return ha_push_metrics_impl()


@mcp.tool()
def ha_status() -> str:
    """Get Home Assistant client connection status and statistics."""
    return ha_status_impl()


@mcp.tool()
def ha_list_entities(domain: str = "", search: str = "") -> str:
    """List Home Assistant entities filtered by domain or search term."""
    try:
        from engine.integrations.homeassistant import get_ha_client

        entities = get_ha_client().list_entities(
            domain=domain or None,
            search=search or None,
        )
        return json.dumps({"count": len(entities), "entities": entities[:100]})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def ha_get_state(entity_id: str) -> str:
    """Get current state of a Home Assistant entity."""
    try:
        from engine.integrations.homeassistant import get_ha_client

        state = get_ha_client().get_state(entity_id)
        return json.dumps(state or {"error": "not found"}, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def ha_toggle(entity_id: str) -> str:
    """Toggle a Home Assistant device on/off."""
    try:
        from engine.integrations.homeassistant import get_ha_client

        return json.dumps(get_ha_client().toggle(entity_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def ha_turn_on(entity_id: str) -> str:
    """Turn on a Home Assistant device."""
    try:
        from engine.integrations.homeassistant import get_ha_client

        return json.dumps(get_ha_client().turn_on(entity_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def ha_turn_off(entity_id: str) -> str:
    """Turn off a Home Assistant device."""
    try:
        from engine.integrations.homeassistant import get_ha_client

        return json.dumps(get_ha_client().turn_off(entity_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def ha_call_service(
    domain: str, service: str, entity_id: str = "", data_json: str = "{}"
) -> str:
    """Call any Home Assistant service with custom parameters."""
    try:
        from engine.integrations.homeassistant import get_ha_client

        extra = json.loads(data_json) if data_json.strip() != "{}" else None
        return json.dumps(
            get_ha_client().call_service(
                domain,
                service,
                entity_id=entity_id or None,
                data=extra,
            ),
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def ha_send_notification(message: str, title: str = "") -> str:
    """Send a push notification to the user's phone via Home Assistant."""
    try:
        from engine.integrations.homeassistant import get_ha_client

        return json.dumps(
            get_ha_client().send_notification(
                message,
                title=title or None,
            ),
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def ha_phone_sensors() -> str:
    """Read all phone sensors exposed via HA Companion (battery, wifi, GPS, etc.)."""
    try:
        from engine.integrations.homeassistant import get_ha_client

        sensors = get_ha_client().get_phone_sensors()
        return json.dumps({"count": len(sensors), "sensors": sensors}, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def ha_push_metrics() -> str:
    """Push CosySim system metrics to Home Assistant as sensor entities."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        from engine.nexus.meta_metrics import get_meta_metrics

        mm = get_meta_metrics()
        collected = mm.collect_system_metrics()
        metrics = {}
        for name in collected:
            trend = mm.trend(name, days=1)
            if trend.get("count", 0) > 0:
                metrics[name] = trend.get("last", 0.0)
        return json.dumps(get_ha_client().push_system_metrics(metrics), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def ha_status() -> str:
    """Get Home Assistant client connection status and statistics."""
    try:
        from engine.integrations.homeassistant import get_ha_client

        return json.dumps(get_ha_client().status(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── NLM Deep Storage Tools ────────────────────────────────────────


@mcp.tool()
def deep_storage_archive(notebook_id: str) -> str:
    return deep_storage_archive_impl(notebook_id=notebook_id)


@mcp.tool()
def deep_storage_archive_all() -> str:
    return deep_storage_archive_all_impl()


@mcp.tool()
def deep_storage_from_har(har_path: str) -> str:
    return deep_storage_from_har_impl(har_path=har_path)


@mcp.tool()
def deep_storage_retrieve(notebook_id: str) -> str:
    return deep_storage_retrieve_impl(notebook_id=notebook_id)


@mcp.tool()
def deep_storage_list() -> str:
    return deep_storage_list_impl()


@mcp.tool()
def deep_storage_search(query: str) -> str:
    return deep_storage_search_impl(query=query)


@mcp.tool()
def deep_storage_chain(chain_id: str) -> str:
    return deep_storage_chain_impl(chain_id=chain_id)


@mcp.tool()
def deep_storage_stats() -> str:
    return deep_storage_stats_impl()


@mcp.tool()
def cache_pipeline_run(stages: str = "") -> str:
    """Run the NLM-driven QA cache generation pipeline (Gemini 3.0 full cycle).

    Mines session history, uploads to NLM notebooks, generates Q&A pairs via
    quota-free Studio tiles, evaluates with Gemini 3.0, and stores approved
    pairs in Nexus. Expected output: +500-1000 net new pairs per cycle.

    Args:
        stages: Optional JSON array of stage letters to run (e.g. '["A","B","C"]').
            Defaults to full cycle (all stages A-J).
    """
    try:
        from engine.nexus.cache_pipeline import get_cache_pipeline

        pipeline = get_cache_pipeline()
        result = pipeline.run_full_cycle()
        return json.dumps(
            {
                "stored": result.stored,
                "direct_seeded": result.direct_seeded,
                "essential": result.essential,
                "useful": result.useful,
                "skipped": result.skipped,
                "gaps": result.gaps[:10],
                "review_sheet_path": result.review_sheet_path,
                "duration_s": round(result.duration_s, 1),
                "errors": result.errors[:5],
                "timestamp": result.timestamp,
            },
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def cache_pipeline_status() -> str:
    """Get the status of the last QA cache pipeline run — pair counts, gaps, timing."""
    try:
        from engine.nexus.cache_pipeline import get_cache_pipeline

        pipeline = get_cache_pipeline()
        return json.dumps(pipeline.get_status(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def review_sheet_generate(output_path: str = "") -> str:
    """Generate a fresh Excel review sheet for pending Q&A cache pairs.

    Creates an xlsx file with formulas (Include? column auto-fills YES for
    ESSENTIAL/USEFUL), dropdown validation, and conditional formatting.

    Args:
        output_path: Where to save the xlsx. Defaults to
            data/qa_review_{YYYY-MM-DD}.xlsx.
    """
    try:
        from datetime import datetime
        from engine.nexus.review_sheet import get_review_sheet
        from engine.nexus.cache_pipeline import get_cache_pipeline, CandidatePair

        if not output_path:
            date_str = datetime.now().strftime("%Y-%m-%d")
            output_path = f"data/qa_review_{date_str}.xlsx"

        pipeline = get_cache_pipeline()
        pending_pairs: list = []
        try:
            import json as _json
            from pathlib import Path

            state_path = getattr(pipeline, "_state_path", None)
            if state_path and Path(state_path).exists():
                state = _json.loads(Path(state_path).read_text())
                for p in state.get("last_candidates", []):
                    pending_pairs.append(
                        CandidatePair(
                            q=p.get("q", ""),
                            a=p.get("a", ""),
                            consumer=p.get("consumer", "developer"),
                            priority=int(p.get("priority", 3)),
                            category=p.get("category", "general"),
                        )
                    )
        except Exception:
            pass

        rs = get_review_sheet()
        saved = rs.generate(pending_pairs, output_path)
        return json.dumps({"saved_path": saved, "row_count": len(pending_pairs)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def review_sheet_import(path: str) -> str:
    """Import a reviewed Excel Q&A review sheet back into the Nexus cache.

    Reads rows where Include? == "YES" and stores them in the Nexus Q&A cache
    with consumer, priority, and category metadata.

    Args:
        path: Path to the reviewed .xlsx file.
    """
    try:
        from engine.nexus.review_sheet import get_review_sheet
        from engine.nexus.client import get_nexus_client

        rs = get_review_sheet()
        count = rs.import_reviewed(path, get_nexus_client())
        return json.dumps({"imported": count, "path": path})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.resource("nexus://status")
def resource_nexus_status() -> str:
    """Nexus knowledge system health and stats."""
    return nexus_status()


# ── AnythingLLM Tools ────────────────────────────────────────────────


@mcp.tool()
def allm_connect(instance: str = "") -> str:
    """Connect to AnythingLLM instance(s). Leave empty for all."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        client = get_anythingllm_client()
        if instance:
            return json.dumps(client.connect(instance=instance))
        return json.dumps(client.connect_all())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def allm_status() -> str:
    """Get status of all AnythingLLM instances."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        return json.dumps(get_anythingllm_client().status())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def allm_list_workspaces(instance: str = "") -> str:
    """List workspaces on an AnythingLLM instance."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        return json.dumps(
            get_anythingllm_client().list_workspaces(instance=instance or None)
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def allm_chat(
    workspace: str, message: str, mode: str = "chat", instance: str = ""
) -> str:
    """Chat with an AnythingLLM workspace."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        result = get_anythingllm_client().chat(
            workspace, message, mode=mode, instance=instance or None
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def allm_sync_to_nexus(workspace: str, instance: str = "") -> str:
    """Sync AnythingLLM workspace Q&A pairs to Nexus."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        return json.dumps(
            get_anythingllm_client().sync_to_nexus(workspace, instance=instance or None)
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def allm_sync_from_nexus(
    workspace: str, query: str = "*", limit: int = 50, instance: str = ""
) -> str:
    """Push Nexus knowledge into an AnythingLLM workspace for RAG."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client

        return json.dumps(
            get_anythingllm_client().sync_from_nexus(
                workspace, query=query, limit=limit, instance=instance or None
            )
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── Phone Assistant Tools ─────────────────────────────────────────────


@mcp.tool()
async def phone_assistant_chat(
    message: str, mode: str = "", voice: bool = False
) -> str:
    """Chat with the phone assistant (cascade: system → nexus → anythingllm → fallback)."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant

        result = get_phone_assistant().chat(message, mode=mode or None, voice=voice)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def phone_assistant_status() -> str:
    """Get phone assistant status: mode, connectivity, stats."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant

        return json.dumps(get_phone_assistant().status(), default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def phone_assistant_set_mode(mode: str) -> str:
    """Set phone assistant mode: auto, passthrough, or offline."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant

        result = get_phone_assistant().set_mode(mode)
        return json.dumps({"mode": result})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def phone_assistant_history(limit: int = 20) -> str:
    """Get recent phone assistant conversation history."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant

        return json.dumps(get_phone_assistant().get_history(limit), default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── NotebookLM Node Bridge Tools ──────────────────────────────────────


@mcp.tool()
async def notebooklm_node_ask(
    notebook_id: str, question: str, session_id: str = ""
) -> str:
    """Ask a question to a NotebookLM notebook via the Node MCP bridge
    (Patchright browser automation). Always reliable — handles auth automatically.

    Pass ``session_id`` from a prior response to continue a multi-turn conversation.
    Returns JSON with ``answer``, ``sources``, and ``session_id``.
    """
    return notebooklm_node_ask_impl(notebook_id, question, session_id)


@mcp.tool()
async def notebooklm_node_batch_ask(notebook_id: str, questions: str) -> str:
    """Ask multiple questions against a NotebookLM notebook in one batch,
    using session continuity so each question has full prior context.

    ``questions`` must be a JSON array of strings, e.g. ``["Q1?", "Q2?"]``.
    Returns a JSON array of ``{answer, sources, session_id}`` dicts.
    """
    return notebooklm_node_batch_ask_impl(notebook_id, questions)


@mcp.tool()
async def notebooklm_node_add_source(
    notebook_id: str,
    source_type: str,
    source_value: str,
    title: str = "",
) -> str:
    """Add a source to a NotebookLM notebook via the Node bridge.

    ``source_type``: ``url``, ``text``, ``file``, or ``youtube``.
    Returns JSON with ``status`` and ``source_id``.
    """
    return notebooklm_node_add_source_impl(
        notebook_id, source_type, source_value, title
    )


@mcp.tool()
async def notebooklm_node_create_notebook(
    name: str,
    sources: str = "[]",
    description: str = "",
    topics: str = "",
) -> str:
    """Create a new NotebookLM notebook via the Node bridge.

    ``sources`` is a JSON array of ``{type, value}`` dicts.
    Returns JSON with notebook ``id`` and ``url``.
    """
    return notebooklm_node_create_notebook_impl(name, sources, description, topics)


@mcp.tool()
async def notebooklm_node_list_notebooks() -> str:
    """List all NotebookLM notebooks in the authenticated account.
    Returns JSON array of ``{id, title, source_count, url}`` objects.
    """
    return notebooklm_node_list_notebooks_impl()


@mcp.tool()
async def notebooklm_node_generate_audio(notebook_id: str) -> str:
    """Generate a podcast-style audio overview of a NotebookLM notebook
    via the Node bridge. Returns JSON with ``status`` and ``progress``.
    """
    return notebooklm_node_generate_audio_impl(notebook_id)


@mcp.tool()
async def notebooklm_node_generate_video(
    notebook_id: str, style: str = "cinematic"
) -> str:
    """Generate a video overview of a NotebookLM notebook via the Node bridge.
    Supported styles: cinematic, documentary, minimalist, energetic, calm,
    data_viz, narrative, academic, news, creative.
    Returns JSON with ``video_id`` and ``status``.
    """
    return notebooklm_node_generate_video_impl(notebook_id, style)


@mcp.tool()
async def notebooklm_node_extract_tables(notebook_id: str, query: str = "") -> str:
    """Extract structured data tables from a NotebookLM notebook's sources.
    Optionally filter by ``query`` topic. Returns JSON with ``tables`` list,
    each table having ``headers`` and ``rows``.
    """
    return notebooklm_node_extract_tables_impl(notebook_id, query)


@mcp.tool()
async def notebooklm_node_chat_history(notebook_id: str, limit: int = 20) -> str:
    """Get recent chat/Q&A history for a NotebookLM notebook.
    Returns JSON array of ``{question, answer, timestamp}`` objects.
    """
    return notebooklm_node_chat_history_impl(notebook_id, limit)


@mcp.tool()
async def notebooklm_node_health() -> str:
    """Get combined health status of both NLM backends: Node MCP bridge
    (Patchright) and batchexecute proxy. Returns JSON with auth state,
    available tools, proxy reachability, and Chrome profile status.
    """
    return notebooklm_node_health_impl()


@mcp.tool()
async def notebooklm_node_setup_auth() -> str:
    """Run first-time Google authentication for the Node MCP bridge.
    Opens Chrome visibly — log in once and the profile is saved permanently.
    All subsequent calls work in headless mode automatically.
    Only callable by copilot (admin operation).
    """
    return notebooklm_node_setup_auth_impl()


@mcp.tool()
async def notebooklm_node_sync_nexus(notebook_id: str, questions: str) -> str:
    """Batch-ask questions against a NotebookLM notebook and automatically
    store every answer as a Q&A pair in Nexus. This is the primary method
    for distilling notebook knowledge into the Nexus knowledge base.

    ``questions`` must be a JSON array of strings.
    Returns JSON with ``stored`` count, ``errors``, and each Q&A pair.
    """
    return notebooklm_node_sync_nexus_impl(notebook_id, questions)


# ── Local Agent Bridge Tools ──────────────────────────────────────────────


@mcp.tool()
async def local_agent_get_tasks(
    model_size: str = "worker", limit: int = 10, tags: str = ""
) -> str:
    """Get pending tasks for a local agent by model size.

    model_size: 'router', 'mini', 'worker', or 'expert'.
    tags: optional comma-separated tag filter.
    Returns JSON list of task dicts sorted by priority.
    """
    return local_agent_get_tasks_impl(model_size, limit, tags)


@mcp.tool()
async def local_agent_claim_task(task_id: str, agent_id: str) -> str:
    """Claim a task for execution by this agent.

    task_id: ID of the task to claim.
    agent_id: Unique identifier for this agent (e.g. 'worker-qwen-7b-1').
    Returns claimed task dict or error.
    """
    return local_agent_claim_task_impl(task_id, agent_id)


@mcp.tool()
async def local_agent_task_context(task_id: str) -> str:
    """Get full execution context for a claimed task.

    Includes: task metadata, relevant Nexus knowledge, coding rules, and
    step-by-step execution guide. Inject this into the agent's system prompt.
    """
    return local_agent_task_context_impl(task_id)


@mcp.tool()
async def local_agent_complete_task(
    task_id: str, result: str, files_changed: str = ""
) -> str:
    """Mark a task as completed and store the result in Nexus.

    task_id: ID of the completed task.
    result: 1-2 sentence summary of what was accomplished.
    files_changed: optional comma-separated list of files modified.
    """
    return local_agent_complete_task_impl(task_id, result, files_changed)


@mcp.tool()
async def local_agent_fail_task(task_id: str, reason: str, retry: bool = False) -> str:
    """Mark a task as failed.

    task_id: ID of the failed task.
    reason: Explanation of why it failed.
    retry: If True, reset to 'pending' so another agent can pick it up.
    """
    return local_agent_fail_task_impl(task_id, reason, retry)


@mcp.tool()
async def local_agent_manifest(model_size: str = "worker") -> str:
    """Get the system prompt manifest for a local agent of the specified size.

    Returns a formatted string ready to inject into an LLM system prompt.
    model_size: 'router', 'mini', 'worker', or 'expert'.
    """
    return local_agent_manifest_impl(model_size)


# ── Master Notebook Builder Tools ─────────────────────────────────────────


@mcp.tool()
async def master_notebook_build(
    sources_only: bool = False,
    generators_only: bool = False,
    notebook_id: str = "",
    dry_run: bool = False,
) -> str:
    """Build or refresh the CosySim Master Intelligence notebook.

    Bundles all engine code, docs, configs, JS, and SDK URLs into NotebookLM,
    then runs all generators (audio, video, study guide, FAQ, briefing, Q&A).

    sources_only: Only upload sources, skip generators.
    generators_only: Skip upload, only run generators.
    notebook_id: Use existing notebook ID (skips creation).
    dry_run: Print plan without making NLM calls.
    """
    return master_notebook_build_impl(
        sources_only, generators_only, notebook_id, dry_run
    )


@mcp.tool()
async def master_notebook_status() -> str:
    """Get status of the master notebook build (what's been done, what's pending)."""
    return master_notebook_status_impl()


@mcp.tool()
async def master_notebook_reset() -> str:
    """Reset master notebook build state (forces fresh creation and full re-upload).

    WARNING: This will delete the stored notebook ID. A new notebook will be
    created on the next build. Use this when you want a completely fresh start.
    """
    return master_notebook_reset_impl()


@mcp.tool()
async def master_notebook_list_sources() -> str:
    """List all sources that will be included in the master notebook.

    Shows all 13 code bundles + 19 SDK documentation URLs.
    """
    return master_notebook_list_sources_impl()


# ── QA Expander Tools ─────────────────────────────────────────────────────────


@mcp.tool()
async def qa_expander_run(batch_size: int = 20, dry_run: bool = False) -> str:
    """Run one batch of QA expansion — reverse-generate Q&A pairs from Nexus entries.

    For each entry, asks NLM to generate 5 questions it answers, then stores
    the pairs in Nexus for instant cache hits. Processes batch_size entries per call.

    batch_size: Number of entries to process (default 20).
    dry_run: Show what would be processed without making NLM calls.
    """
    from engine.nexus.qa_expander import QAExpander

    expander = QAExpander(dry_run=dry_run)
    result = expander.run(batch_size=batch_size)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def qa_expander_stats() -> str:
    """Show QA expansion progress: entries expanded, pairs generated, last run."""
    from engine.nexus.qa_expander import get_qa_expander

    stats = get_qa_expander().stats()
    lines = [
        "=== QA Expander Stats ===",
        f"Entries expanded : {stats['entries_expanded']}",
        f"Pairs generated  : {stats['total_generated']}",
        f"Nexus Q&A count  : {stats['nexus_qa_count']}",
        f"Last run         : {stats['last_run']}",
        f"Total runs       : {stats['runs']}",
        f"Notebook ID      : {stats['notebook_id']}",
    ]
    return "\n".join(lines)


@mcp.tool()
async def qa_expander_reset() -> str:
    """Reset QA expansion state — next run will start from the beginning.

    WARNING: This clears all progress tracking. The Q&A pairs already stored
    in Nexus are preserved, but expansion will re-process all entries.
    """
    from engine.nexus.qa_expander import QAExpander

    QAExpander().reset()
    return "QA expander state reset. Next run will process all entries from scratch."


@mcp.tool()
async def qa_expander_reset() -> str:
    """Reset QA expansion state — next run will start from the beginning.    WARNING: This clears all progress tracking. The Q&A pairs already stored
    in Nexus are preserved, but expansion will re-process all entries.
    """
    from engine.nexus.qa_expander import QAExpander

    QAExpander().reset()
    return "QA expander state reset. Next run will process all entries from scratch."


# ──── Fine-tune & Training MCP Tools ─────────────────────────────────────────


@mcp.tool()
async def finetune_submit(model_type: str, base_model: str = "") -> str:
    return finetune_submit_impl(model_type=model_type, base_model=base_model)


@mcp.tool()
async def finetune_run_next() -> str:
    return finetune_run_next_impl()


@mcp.tool()
async def finetune_list_jobs(status: str = "") -> str:
    return finetune_list_jobs_impl(status=status)


@mcp.tool()
async def finetune_build_dataset(model_type: str, count: int = 500) -> str:
    return finetune_build_dataset_impl(model_type=model_type, count=count)


@mcp.tool()
async def finetune_dataset_status() -> str:
    return finetune_dataset_status_impl()


@mcp.tool()
async def model_registry_list(model_type: str = "") -> str:
    return model_registry_list_impl(model_type=model_type)


@mcp.tool()
async def model_benchmark_run(model_type: str = "") -> str:
    return model_benchmark_run_impl(model_type=model_type)


@mcp.tool()
async def model_benchmark_leaderboard() -> str:
    return model_benchmark_leaderboard_impl()


@mcp.tool()
async def model_promote(model_id: str, model_type: str) -> str:
    return model_promote_impl(model_id=model_id, model_type=model_type)


@mcp.tool()
async def teacher_generate_dataset(model_type: str, count: int = 300) -> str:
    return teacher_generate_dataset_impl(model_type=model_type, count=count)


@mcp.tool()
async def finetuned_router_status() -> str:
    return finetuned_router_status_impl()


@mcp.tool()
async def finetuned_router_load_registry() -> str:
    return finetuned_router_load_registry_impl()


@mcp.tool()
async def backup_run() -> str:
    """Trigger an immediate database backup."""
    from engine.nexus.backup_manager import get_backup_manager

    mgr = get_backup_manager()
    result = mgr.run_backup()
    return json.dumps(
        result.to_dict() if hasattr(result, "to_dict") else {"result": str(result)},
        indent=2,
    )


@mcp.tool()
async def backup_list() -> str:
    """List all available database backups."""
    from engine.nexus.backup_manager import get_backup_manager

    mgr = get_backup_manager()
    backups = mgr.list_backups()
    if not backups:
        return "No backups found."
    lines = ["=== Database Backups ==="]
    for b in backups[:20]:
        lines.append(
            f"  {b.get('timestamp', '?')} | {b.get('size_mb', 0):.1f}MB | {b.get('targets', [])}"
        )
    return "\n".join(lines)


@mcp.tool()
async def backup_restore(backup_path: str, target: str = "nexus") -> str:
    """Restore a specific database backup.

    Args:
        backup_path: Path to the backup file.
        target: Which database to restore (nexus | session | all).
    """
    from engine.nexus.backup_manager import get_backup_manager

    result = get_backup_manager().restore_backup(backup_path, target)
    return json.dumps(result, indent=2)


@mcp.tool()
async def user_profile_get() -> str:
    """Retrieve the current user profile (extracted from conversations)."""
    from engine.nexus.user_profile import get_user_profile_store

    store = get_user_profile_store()
    profile = store.get()
    return json.dumps(profile, indent=2)


@mcp.tool()
async def user_profile_update(updates: str) -> str:
    """Merge updates into the user profile.

    Args:
        updates: JSON string with profile fields to update.
    """
    from engine.nexus.user_profile import get_user_profile_store

    store = get_user_profile_store()
    try:
        data = json.loads(updates)
    except json.JSONDecodeError as exc:
        return f"ERROR: Invalid JSON: {exc}"
    result = store.merge(data)
    return json.dumps(result, indent=2)


def main(mode: str = "stdio") -> None:
    if mode == "http":
        logger.info("Starting CosySim DevTools MCP server in HTTP mode...")
        mcp.run(transport="sse")
    else:
        logger.info("Starting CosySim DevTools MCP server in stdio mode...")
        mcp.run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CosySim DevTools MCP Server")
    parser.add_argument("--http", action="store_true", help="Run in HTTP/SSE mode")
    args = parser.parse_args()
    run_server("http" if args.http else "stdio")
