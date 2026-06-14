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
    from engine.mcp.tools.system import system_status
    return system_status()



@mcp.tool()
def list_all_skills() -> str:
    """List all registered MCP skills grouped by pack."""
    from engine.mcp.tools.system import list_all_skills
    return list_all_skills()



@mcp.tool()
def get_skill_info(skill_name: str) -> str:
    """Get detailed information about a specific MCP skill."""
    from engine.mcp.tools.system import get_skill_info
    return get_skill_info(skill_name)



@mcp.tool()
def get_benchmark_stats() -> str:
    """Get performance benchmark statistics."""
    from engine.mcp.tools.system import get_benchmark_stats
    return get_benchmark_stats()



# ═══════════════════════════════════════════════════════════════════════
# NEXUS BRIDGE — Knowledge management
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def nexus_search(query: str, limit: int = 10) -> str:
    """Search the Nexus knowledge base for entries matching a query."""
    from engine.mcp.tools.nexus import nexus_search
    return nexus_search(query, limit)



@mcp.tool()
def nexus_ask(question: str, depth: str = "auto", category: str = "") -> str:
    """Smart Q&A against Nexus — checks Q&A cache first, then FTS5 search,
    then NotebookLM if needed."""
    from engine.mcp.tools.nexus import nexus_ask
    return nexus_ask(question, depth, category)



@mcp.tool()
def nexus_add(title: str, content: str, content_type: str = "note",
              category: str = "", tags: str = "") -> str:
    """Store a knowledge entry in Nexus. Tags should be comma-separated."""
    from engine.mcp.tools.nexus import nexus_add
    return nexus_add(title, content, content_type, category, tags)



@mcp.tool()
def nexus_add_qa(question: str, answer: str, category: str = "",
                 tags: str = "") -> str:
    """Store a question-answer pair in Nexus for future lookups."""
    from engine.mcp.tools.nexus import nexus_add_qa
    return nexus_add_qa(question, answer, category, tags)



@mcp.tool()
def nexus_get_rules(scope: str = "", rule_type: str = "") -> str:
    """Get active governance rules from Nexus."""
    from engine.mcp.tools.nexus import nexus_get_rules
    return nexus_get_rules(scope, rule_type)



@mcp.tool()
def nexus_store_prompt(name: str, content: str, category: str = "",
                       version: str = "") -> str:
    """Store or version a prompt template in Nexus."""
    from engine.mcp.tools.nexus import nexus_store_prompt
    return nexus_store_prompt(name, content, category, version)



@mcp.tool()
def nexus_get_prompts(category: str = "", name: str = "") -> str:
    """Retrieve stored prompts from Nexus."""
    from engine.mcp.tools.nexus import nexus_get_prompts
    return nexus_get_prompts(category, name)



@mcp.tool()
def nexus_research(question: str) -> str:
    """Start a deep research session via NotebookLM."""
    from engine.mcp.tools.nexus import nexus_research
    return nexus_research(question)



@mcp.tool()
def nexus_converse(research_id: str, message: str) -> str:
    """Continue an existing research session with a follow-up."""
    from engine.mcp.tools.nexus import nexus_converse
    return nexus_converse(research_id, message)



@mcp.tool()
def nexus_finish_research(research_id: str) -> str:
    """Close a research session and distill findings into Q&A pairs."""
    from engine.mcp.tools.nexus import nexus_finish_research
    return nexus_finish_research(research_id)



@mcp.tool()
def nexus_import_youtube(url: str, category: str = "", tags: str = "") -> str:
    """Import a YouTube video transcript into Nexus."""
    from engine.mcp.tools.nexus import nexus_import_youtube
    return nexus_import_youtube(url, category, tags)



@mcp.tool()
def nexus_log_session(project: str = "CosySim", repo: str = "",
                      branch: str = "") -> str:
    """Log a work session to Nexus for tracking."""
    from engine.mcp.tools.nexus import nexus_log_session
    return nexus_log_session(project, repo, branch)



@mcp.tool()
def nexus_status() -> str:
    """Check Nexus health and get basic stats."""
    from engine.mcp.tools.nexus import nexus_status
    return nexus_status()



@mcp.tool()
def nexus_list_plugins(scope: str = "") -> str:
    """List available Nexus plugins."""
    from engine.mcp.tools.nexus import nexus_list_plugins
    return nexus_list_plugins(scope)



# ═══════════════════════════════════════════════════════════════════════
# NEXUS MEMORY — Agent memory management
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def nexus_remember(content: str, agent_id: str = "copilot",
                   memory_type: str = "observation", importance: float = 0.5) -> str:
    """Store a memory in Nexus for an agent or Copilot."""
    from engine.mcp.tools.nexus import nexus_remember
    return nexus_remember(content, agent_id, memory_type, importance)



@mcp.tool()
def nexus_recall(query: str, agent_id: str = "copilot", limit: int = 5) -> str:
    """Recall memories from Nexus for an agent or Copilot."""
    from engine.mcp.tools.nexus import nexus_recall
    return nexus_recall(query, agent_id, limit)



@mcp.tool()
def nexus_memory_context(agent_id: str = "copilot", max_tokens: int = 500) -> str:
    """Get a compact memory context window for an agent."""
    from engine.mcp.tools.nexus import nexus_memory_context
    return nexus_memory_context(agent_id, max_tokens)



# ═══════════════════════════════════════════════════════════════════════
# NEXUS MAINTENANCE — Seeding, distillation, export
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def seed_nexus(source: str = "all") -> str:
    """Seed Nexus with project knowledge. Idempotent — safe to run repeatedly."""
    from engine.mcp.tools.nexus import seed_nexus
    return seed_nexus(source)



@mcp.tool()
def nexus_distill(action: str = "stats") -> str:
    """Distill raw session data into reusable knowledge. Actions:
    stats, distill, compact, primer, dedup, dedup-dry, skills, prompts, lineage, all"""
    from engine.mcp.tools.nexus import nexus_distill
    return nexus_distill(action)



@mcp.tool()
def nexus_export_session() -> str:
    """Export current Copilot session history to Nexus."""
    from engine.mcp.tools.nexus import nexus_export_session
    return nexus_export_session()



@mcp.tool()
def nexus_maintain(action: str = "health") -> str:
    """Run Nexus self-maintenance tasks. Actions:
    health, dedup, dedup-apply, compact, score, full, full-apply"""
    from engine.mcp.tools.nexus import nexus_maintain
    return nexus_maintain(action)



@mcp.tool()
def nexus_smart_query(question: str, min_confidence: float = 0.3,
                      use_llm: bool = True, category: str = "") -> str:
    """Route a query through the Nexus-first pipeline.
    Checks Q&A cache → FTS search → Nexus ask → LLM fallback."""
    from engine.mcp.tools.nexus import nexus_smart_query
    return nexus_smart_query(question, min_confidence, use_llm, category)



@mcp.tool()
def nexus_router_stats() -> str:
    """Get NexusQueryRouter statistics: hit rates, cache performance, tokens saved."""
    from engine.mcp.tools.nexus import nexus_router_stats
    return nexus_router_stats()



# ═══════════════════════════════════════════════════════════════════════
# TRAINING & CONTENT — Data capture and generation
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def capture_training_data(user_message: str, agent_response: str,
                          dataset_type: str = "conversation",
                          quality_score: float = 0.7,
                          character_id: str = "") -> str:
    """Capture an LLM interaction as training data for fine-tuning."""
    from engine.mcp.tools.training import capture_training_data
    return capture_training_data(user_message, agent_response, dataset_type, quality_score, character_id)



@mcp.tool()
def generate_content(character_id: str, content_type: str = "greetings") -> str:
    """Generate pre-built content for a character. Types: greetings, reactions."""
    from engine.mcp.tools.training import generate_content
    return generate_content(character_id, content_type)



# ═══════════════════════════════════════════════════════════════════════
# COPILOT INTEGRATION — Session helpers
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def copilot_store_snippet(title: str, code: str, language: str = "python",
                          tags: str = "") -> str:
    """Store a reusable code snippet in Nexus for future sessions."""
    from engine.mcp.tools.copilot import copilot_store_snippet
    return copilot_store_snippet(title, code, language, tags)



@mcp.tool()
def copilot_store_discovery(title: str, finding: str,
                            category: str = "debugging") -> str:
    """Store a discovery, workaround, or gotcha in Nexus."""
    from engine.mcp.tools.copilot import copilot_store_discovery
    return copilot_store_discovery(title, finding, category)



@mcp.tool()
def copilot_log_progress(task: str, status: str = "completed", details: str = "",
                         tests_passed: int = 0, commit_sha: str = "") -> str:
    """Log work progress to Nexus for tracking across sessions."""
    from engine.mcp.tools.copilot import copilot_log_progress
    return copilot_log_progress(task, status, details, tests_passed, commit_sha)



@mcp.tool()
def copilot_context_primer(project: str = "CosySim") -> str:
    """Generate a context primer from Nexus knowledge for new sessions."""
    from engine.mcp.tools.copilot import copilot_context_primer
    return copilot_context_primer(project)



@mcp.tool()
def copilot_local_model_guide(task_type: str = "general") -> str:
    """Get guidance text for local LMStudio models to safely use Nexus."""
    from engine.mcp.tools.copilot import copilot_local_model_guide
    return copilot_local_model_guide(task_type)



# ═══════════════════════════════════════════════════════════════════════
# AGENT TASK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def agent_create_task(title: str, description: str = "", agent: str = "copilot",
                      priority: str = "normal", tags: str = "") -> str:
    """Create a tracked agent task in Nexus. Returns task ID."""
    from engine.mcp.tools.scheduler import agent_create_task
    return agent_create_task(title, description, agent, priority, tags)



@mcp.tool()
def agent_update_task(task_id: str, status: str) -> str:
    """Update an agent task status (pending/in_progress/done/blocked/cancelled)."""
    from engine.mcp.tools.scheduler import agent_update_task
    return agent_update_task(task_id, status)



@mcp.tool()
def agent_complete_task(task_id: str, summary: str = "") -> str:
    """Mark an agent task as done with an optional completion summary."""
    from engine.mcp.tools.scheduler import agent_complete_task
    return agent_complete_task(task_id, summary)



@mcp.tool()
def agent_list_tasks(status: str = "", agent: str = "", limit: int = 20) -> str:
    """List agent tasks, optionally filtered by status and agent."""
    from engine.mcp.tools.scheduler import agent_list_tasks
    return agent_list_tasks(status, agent, limit)



# ═══════════════════════════════════════════════════════════════════════
# AUTONOMY — SCHEDULER, NEWS, NOTEBOOKS, QUALITY, GOVERNANCE
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def scheduler_status() -> str:
    """Get status of all scheduled autonomous tasks — running state,
    next-due times, run/error counts, and last results."""
    from engine.mcp.tools.scheduler import scheduler_status
    return scheduler_status()



@mcp.tool()
def scheduler_run_now(task_id: str) -> str:
    """Run a scheduled task immediately by ID. Returns success/failure
    with duration and result details."""
    from engine.mcp.tools.scheduler import scheduler_run_now
    return scheduler_run_now(task_id)



@mcp.tool()
def news_fetch(category: str = "") -> str:
    """Fetch, filter, and score news from all enabled sources. Returns
    top 20 articles with title, URL, relevance score, and source."""
    from engine.mcp.tools.news import news_fetch
    return news_fetch(category)



@mcp.tool()
def news_fetch_and_store(category: str = "", max_articles: int = 20) -> str:
    """Full news pipeline: fetch → filter → score → store in Nexus → generate digest.
    Returns counts of fetched, filtered, and stored articles."""
    from engine.mcp.tools.news import news_fetch_and_store
    return news_fetch_and_store(category, max_articles)



@mcp.tool()
def news_digest(category: str = "") -> str:
    """Generate a markdown daily news digest from configured sources."""
    from engine.mcp.tools.news import news_digest
    return news_digest(category)



@mcp.tool()
def news_sources() -> str:
    """List all configured news sources with fetch stats and error rates."""
    from engine.mcp.tools.news import news_sources
    return news_sources()



@mcp.tool()
def nlm_notebook_list() -> str:
    """List all managed NLM notebooks with health: source counts, ages,
    last seeded/asked dates, and overall slot health."""
    from engine.mcp.tools.nlm import nlm_notebook_list
    return nlm_notebook_list()



@mcp.tool()
def nlm_notebook_seed(slot_name: str = "cosysim-architecture", source_type: str = "docs") -> str:
    """Seed an NLM notebook from project files. source_type: 'docs' for
    documentation, 'code' for engine source files."""
    from engine.mcp.tools.nlm import nlm_notebook_seed
    return nlm_notebook_seed(slot_name, source_type)



@mcp.tool()
def nlm_notebook_rotate(slot_name: str) -> str:
    """Rotate (delete & recreate) an NLM notebook to refresh stale content."""
    from engine.mcp.tools.nlm import nlm_notebook_rotate
    return nlm_notebook_rotate(slot_name)



@mcp.tool()
def nexus_quality_report() -> str:
    """Score all Nexus entries by freshness, quality, uniqueness, and
    completeness. Returns distribution, low-quality entries, duplicates,
    stale entries, and actionable recommendations."""
    from engine.mcp.tools.nexus import nexus_quality_report
    return nexus_quality_report()



@mcp.tool()
def governance_validate(filepath: str) -> str:
    """Validate a Python file against all CosySim coding standards.
    Returns violations with rule names, severity, messages, and line numbers."""
    from engine.mcp.tools.governance import governance_validate
    return governance_validate(filepath)



@mcp.tool()
def governance_seed() -> str:
    """Seed all 18 governance rules into Nexus (idempotent). Rules cover
    coding standards, testing, Nexus workflow, agent permissions, and commits."""
    from engine.mcp.tools.governance import governance_seed
    return governance_seed()



@mcp.tool()
def governance_check_permission(agent_id: str, operation: str) -> str:
    """Check if an agent can perform an operation. Agent permission rules
    are based on model parameter count (sub-1B=read-only, 1-10B=write,
    10B+/Copilot=full access)."""
    from engine.mcp.tools.governance import governance_check_permission
    return governance_check_permission(agent_id, operation)



@mcp.tool()
def governance_enforce(filepath: str = "", agent_id: str = "copilot",
                       operation: str = "write", commit_message: str = "") -> str:
    """Enforce governance rules — raises error if blocking violations found.
    Unlike governance_validate (advisory), this blocks on reject/block severity."""
    from engine.mcp.tools.governance import governance_enforce
    return governance_enforce(filepath, agent_id, operation, commit_message)



@mcp.tool()
def task_auto_generate(source: str = "quality") -> str:
    """Auto-generate tasks from system events. source: 'quality' (from stale
    Nexus entries), 'tests' (run and parse test failures). Returns created tasks."""
    from engine.mcp.tools.scheduler import task_auto_generate
    return task_auto_generate(source)



@mcp.tool()
def task_from_template(template_name: str, title: str = "",
                       description: str = "", target_files: str = "") -> str:
    """Create a task from a template: bug-fix, feature, refactor, test,
    doc-update, skill-add, scene-polish, knowledge-refresh.
    target_files is comma-separated."""
    from engine.mcp.tools.scheduler import task_from_template
    return task_from_template(template_name, title, description, target_files)



@mcp.tool()
def task_list_templates() -> str:
    """List all available task templates with priorities and descriptions."""
    from engine.mcp.tools.scheduler import task_list_templates
    return task_list_templates()



@mcp.tool()
def diagnose_test_failures(pytest_output: str) -> str:
    """Auto-diagnose test failures from pytest output. Parses failures,
    checks Nexus for prior fixes, applies heuristics, asks NLM, stores
    diagnoses, and creates fix tasks. Returns root causes and suggested fixes."""
    from engine.mcp.tools.diagnostics import diagnose_test_failures
    return diagnose_test_failures(pytest_output)



@mcp.tool()
def diagnose_test_file(test_file: str, test_name: str = "") -> str:
    """Run a test file, auto-diagnose failures, and create fix tasks.
    Returns diagnoses with root cause, confidence, and suggested fixes."""
    from engine.mcp.tools.diagnostics import diagnose_test_file
    return diagnose_test_file(test_file, test_name)



@mcp.tool()
def training_stats() -> str:
    """Get training data flywheel statistics — example counts by source,
    total examples, export history, and quality distribution."""
    from engine.mcp.tools.training import training_stats
    return training_stats()



@mcp.tool()
def training_export(format: str = "jsonl", min_quality: float = 0.5) -> str:
    """Export training data for model fine-tuning. format: 'jsonl' (instruction),
    'sharegpt' (conversation), or 'dpo' (preference). Returns export path and count."""
    from engine.mcp.tools.training import training_export
    return training_export(format, min_quality)



@mcp.tool()
def training_sync_nexus() -> str:
    """Sync all Nexus Q&A pairs into the training flywheel for fine-tuning.
    Deduplicates against existing examples."""
    from engine.mcp.tools.training import training_sync_nexus
    return training_sync_nexus()



@mcp.tool()
def metrics_dashboard(hours: int = 24) -> str:
    """Generate a full system metrics dashboard in markdown with trends,
    comparisons, and active alerts."""
    from engine.mcp.tools.diagnostics import metrics_dashboard
    return metrics_dashboard(hours)



@mcp.tool()
def metrics_collect_all() -> str:
    """Collect and record all current system metrics — VRAM, Nexus stats,
    inference stats, test counts. Returns recorded values."""
    from engine.mcp.tools.diagnostics import metrics_collect_all
    return metrics_collect_all()



@mcp.tool()
def metrics_check_regressions(threshold_pct: float = 10.0) -> str:
    """Check all tracked metrics for regressions against baselines.
    Returns alerts for any metrics that degraded beyond the threshold."""
    from engine.mcp.tools.diagnostics import metrics_check_regressions
    return metrics_check_regressions(threshold_pct)



@mcp.tool()
def metrics_snapshot() -> str:
    """Get the most recent value for every tracked metric."""
    from engine.mcp.tools.diagnostics import metrics_snapshot
    return metrics_snapshot()



# ── System Reflection Tools ──────────────────────────────────────────


@mcp.tool()
def reflection_run(period: str = "weekly", days: int = 7, use_nlm: bool = False) -> str:
    """Run a system reflection analysis — collect metrics, analyze patterns, generate insights, create tasks."""
    from engine.mcp.tools.diagnostics import reflection_run
    return reflection_run(period, days, use_nlm)



@mcp.tool()
def reflection_history(limit: int = 5) -> str:
    """Get recent system reflection reports and their summaries."""
    from engine.mcp.tools.diagnostics import reflection_history
    return reflection_history(limit)



@mcp.tool()
def reflection_latest_insights(limit: int = 10) -> str:
    """Get insights from the most recent system reflection."""
    from engine.mcp.tools.diagnostics import reflection_latest_insights
    return reflection_latest_insights(limit)



# ── Experiment Proposal Tools ────────────────────────────────────────


@mcp.tool()
def experiment_scan_and_propose() -> str:
    """Scan current metrics against templates and propose experiments for triggered conditions."""
    from engine.mcp.tools.diagnostics import experiment_scan_and_propose
    return experiment_scan_and_propose()



@mcp.tool()
def experiment_list_proposals(status: str = "") -> str:
    """List experiment proposals. Filter: 'pending', 'active', or '' for all."""
    from engine.mcp.tools.diagnostics import experiment_list_proposals
    return experiment_list_proposals(status)



@mcp.tool()
def experiment_list_templates() -> str:
    """List all experiment templates with their triggers and thresholds."""
    from engine.mcp.tools.diagnostics import experiment_list_templates
    return experiment_list_templates()



# ── Copilot Self-Configuration Tools ─────────────────────────────────


@mcp.tool()
def copilot_sync_config() -> str:
    """Sync all Copilot instruction files, agent definitions, and hooks to Nexus."""
    from engine.mcp.tools.copilot import copilot_sync_config
    return copilot_sync_config()



@mcp.tool()
def copilot_config_status() -> str:
    """Get Copilot configuration status — counts of instructions, agents, hooks."""
    from engine.mcp.tools.copilot import copilot_config_status
    return copilot_config_status()



@mcp.tool()
def copilot_list_instructions() -> str:
    """List all Copilot instruction files with names and sizes."""
    from engine.mcp.tools.copilot import copilot_list_instructions
    return copilot_list_instructions()



@mcp.tool()
def copilot_list_agents() -> str:
    """List all Copilot agent definition files."""
    from engine.mcp.tools.copilot import copilot_list_agents
    return copilot_list_agents()



# ── Knowledge Graph Tools ────────────────────────────────────────────


@mcp.tool()
def knowledge_graph_build() -> str:
    """Build the knowledge graph from Nexus entries — extracts topics, edges, gaps, clusters."""
    from engine.mcp.tools.knowledge_graph import knowledge_graph_build
    return knowledge_graph_build()



@mcp.tool()
def knowledge_graph_gaps() -> str:
    """Detect knowledge gaps — topics with few entries that neighbor strong topics."""
    from engine.mcp.tools.knowledge_graph import knowledge_graph_gaps
    return knowledge_graph_gaps()



@mcp.tool()
def knowledge_graph_clusters() -> str:
    """Get topic clusters from the knowledge graph."""
    from engine.mcp.tools.knowledge_graph import knowledge_graph_clusters
    return knowledge_graph_clusters()



@mcp.tool()
def knowledge_graph_search(query: str) -> str:
    """Search topics in the knowledge graph by name."""
    from engine.mcp.tools.knowledge_graph import knowledge_graph_search
    return knowledge_graph_search(query)



@mcp.tool()
def knowledge_graph_research_tasks() -> str:
    """Auto-create research tasks for knowledge gaps."""
    from engine.mcp.tools.knowledge_graph import knowledge_graph_research_tasks
    return knowledge_graph_research_tasks()



# ── Home Assistant Tools ─────────────────────────────────────────────


@mcp.tool()
def ha_connect() -> str:
    """Connect to Home Assistant and discover entities."""
    from engine.mcp.tools.home_assistant import ha_connect
    return ha_connect()



@mcp.tool()
def ha_list_entities(domain: str = "", search: str = "") -> str:
    """List Home Assistant entities filtered by domain or search term."""
    from engine.mcp.tools.home_assistant import ha_list_entities
    return ha_list_entities(domain, search)



@mcp.tool()
def ha_get_state(entity_id: str) -> str:
    """Get current state of a Home Assistant entity."""
    from engine.mcp.tools.home_assistant import ha_get_state
    return ha_get_state(entity_id)



@mcp.tool()
def ha_toggle(entity_id: str) -> str:
    """Toggle a Home Assistant device on/off."""
    from engine.mcp.tools.home_assistant import ha_toggle
    return ha_toggle(entity_id)



@mcp.tool()
def ha_turn_on(entity_id: str) -> str:
    """Turn on a Home Assistant device."""
    from engine.mcp.tools.home_assistant import ha_turn_on
    return ha_turn_on(entity_id)



@mcp.tool()
def ha_turn_off(entity_id: str) -> str:
    """Turn off a Home Assistant device."""
    from engine.mcp.tools.home_assistant import ha_turn_off
    return ha_turn_off(entity_id)



@mcp.tool()
def ha_call_service(domain: str, service: str, entity_id: str = "", data_json: str = "{}") -> str:
    """Call any Home Assistant service with custom parameters."""
    from engine.mcp.tools.home_assistant import ha_call_service
    return ha_call_service(domain, service, entity_id, data_json)



@mcp.tool()
def ha_send_notification(message: str, title: str = "") -> str:
    """Send a push notification to the user's phone via Home Assistant."""
    from engine.mcp.tools.home_assistant import ha_send_notification
    return ha_send_notification(message, title)



@mcp.tool()
def ha_phone_sensors() -> str:
    """Read all phone sensors exposed via HA Companion (battery, wifi, GPS, etc.)."""
    from engine.mcp.tools.home_assistant import ha_phone_sensors
    return ha_phone_sensors()



@mcp.tool()
def ha_push_metrics() -> str:
    """Push CosySim system metrics to Home Assistant as sensor entities."""
    from engine.mcp.tools.home_assistant import ha_push_metrics
    return ha_push_metrics()



@mcp.tool()
def ha_status() -> str:
    """Get Home Assistant client connection status and statistics."""
    from engine.mcp.tools.home_assistant import ha_status
    return ha_status()



# ── NLM Deep Storage Tools ────────────────────────────────────────


@mcp.tool()
def deep_storage_archive(notebook_id: str) -> str:
    """Archive a single NLM notebook into Nexus deep storage — stores metadata, sources, conversations, notes."""
    from engine.mcp.tools.deep_storage import deep_storage_archive
    return deep_storage_archive(notebook_id)



@mcp.tool()
def deep_storage_archive_all() -> str:
    """Archive ALL NLM notebooks into Nexus deep storage."""
    from engine.mcp.tools.deep_storage import deep_storage_archive_all
    return deep_storage_archive_all()



@mcp.tool()
def deep_storage_from_har(har_path: str) -> str:
    """Archive notebook content extracted from a browser HAR capture."""
    from engine.mcp.tools.deep_storage import deep_storage_from_har
    return deep_storage_from_har(har_path)



@mcp.tool()
def deep_storage_retrieve(notebook_id: str) -> str:
    """Retrieve all archived content for a notebook from deep storage."""
    from engine.mcp.tools.deep_storage import deep_storage_retrieve
    return deep_storage_retrieve(notebook_id)



@mcp.tool()
def deep_storage_list() -> str:
    """List all archived NLM notebooks in deep storage."""
    from engine.mcp.tools.deep_storage import deep_storage_list
    return deep_storage_list()



@mcp.tool()
def deep_storage_search(query: str) -> str:
    """Search across all archived NLM conversations."""
    from engine.mcp.tools.deep_storage import deep_storage_search
    return deep_storage_search(query)



@mcp.tool()
def deep_storage_chain(chain_id: str) -> str:
    """Retrieve all entries in a conversation chain by chain ID."""
    from engine.mcp.tools.deep_storage import deep_storage_chain
    return deep_storage_chain(chain_id)



@mcp.tool()
def deep_storage_stats() -> str:
    """Get NLM deep storage statistics — archive counts, entries stored."""
    from engine.mcp.tools.deep_storage import deep_storage_stats
    return deep_storage_stats()



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
    from engine.mcp.tools.cache_pipeline import cache_pipeline_run
    return cache_pipeline_run(stages)



@mcp.tool()
def cache_pipeline_status() -> str:
    """Get the status of the last QA cache pipeline run — pair counts, gaps, timing."""
    from engine.mcp.tools.cache_pipeline import cache_pipeline_status
    return cache_pipeline_status()



@mcp.tool()
def review_sheet_generate(output_path: str = "") -> str:
    """Generate a fresh Excel review sheet for pending Q&A cache pairs.

    Creates an xlsx file with formulas (Include? column auto-fills YES for
    ESSENTIAL/USEFUL), dropdown validation, and conditional formatting.

    Args:
        output_path: Where to save the xlsx. Defaults to
            data/qa_review_{YYYY-MM-DD}.xlsx.
    """
    from engine.mcp.tools.review import review_sheet_generate
    return review_sheet_generate(output_path)



@mcp.tool()
def review_sheet_import(path: str) -> str:
    """Import a reviewed Excel Q&A review sheet back into the Nexus cache.

    Reads rows where Include? == "YES" and stores them in the Nexus Q&A cache
    with consumer, priority, and category metadata.

    Args:
        path: Path to the reviewed .xlsx file.
    """
    from engine.mcp.tools.review import review_sheet_import
    return review_sheet_import(path)



@mcp.resource("nexus://status")
def resource_nexus_status() -> str:
    """Nexus knowledge system health and stats."""
    from engine.mcp.tools.nexus import resource_nexus_status
    return resource_nexus_status()



# ── AnythingLLM Tools ────────────────────────────────────────────────

@mcp.tool()
def allm_connect(instance: str = "") -> str:
    """Connect to AnythingLLM instance(s). Leave empty for all."""
    from engine.mcp.tools.allm import allm_connect
    return allm_connect(instance)


@mcp.tool()
def allm_status() -> str:
    """Get status of all AnythingLLM instances."""
    from engine.mcp.tools.allm import allm_status
    return allm_status()


@mcp.tool()
def allm_list_workspaces(instance: str = "") -> str:
    """List workspaces on an AnythingLLM instance."""
    from engine.mcp.tools.allm import allm_list_workspaces
    return allm_list_workspaces(instance)


@mcp.tool()
def allm_chat(workspace: str, message: str, mode: str = "chat", instance: str = "") -> str:
    """Chat with an AnythingLLM workspace."""
    from engine.mcp.tools.allm import allm_chat
    return allm_chat(workspace, message, mode, instance)


@mcp.tool()
def allm_sync_to_nexus(workspace: str, instance: str = "") -> str:
    """Sync AnythingLLM workspace Q&A pairs to Nexus."""
    from engine.mcp.tools.allm import allm_sync_to_nexus
    return allm_sync_to_nexus(workspace, instance)


@mcp.tool()
def allm_sync_from_nexus(workspace: str, query: str = "*", limit: int = 50, instance: str = "") -> str:
    """Push Nexus knowledge into an AnythingLLM workspace for RAG."""
    from engine.mcp.tools.allm import allm_sync_from_nexus
    return allm_sync_from_nexus(workspace, query, limit, instance)



# ── Phone Assistant Tools ─────────────────────────────────────────────


@mcp.tool()
async def phone_assistant_chat(message: str, mode: str = "", voice: bool = False) -> str:
    """Chat with the phone assistant (cascade: system → nexus → anythingllm → fallback)."""
    from engine.mcp.tools.phone_assistant import phone_assistant_chat
    return phone_assistant_chat(message, mode, voice)



@mcp.tool()
async def phone_assistant_status() -> str:
    """Get phone assistant status: mode, connectivity, stats."""
    from engine.mcp.tools.phone_assistant import phone_assistant_status
    return phone_assistant_status()



@mcp.tool()
async def phone_assistant_set_mode(mode: str) -> str:
    """Set phone assistant mode: auto, passthrough, or offline."""
    from engine.mcp.tools.phone_assistant import phone_assistant_set_mode
    return phone_assistant_set_mode(mode)



@mcp.tool()
async def phone_assistant_history(limit: int = 20) -> str:
    """Get recent phone assistant conversation history."""
    from engine.mcp.tools.phone_assistant import phone_assistant_history
    return phone_assistant_history(limit)



# ── NotebookLM Node Bridge Tools ──────────────────────────────────────


@mcp.tool()
async def notebooklm_node_ask(notebook_id: str, question: str, session_id: str = "") -> str:
    """Ask a question to a NotebookLM notebook via the Node MCP bridge
    (Patchright browser automation). Always reliable — handles auth automatically.

    Pass ``session_id`` from a prior response to continue a multi-turn conversation.
    Returns JSON with ``answer``, ``sources``, and ``session_id``.
    """
    # v1.49.2 [2026-03-22] — await async tools.nlm delegates
    from engine.mcp.tools.nlm import notebooklm_node_ask
    return await notebooklm_node_ask(notebook_id, question, session_id)



@mcp.tool()
async def notebooklm_node_batch_ask(notebook_id: str, questions: str) -> str:
    """Ask multiple questions against a NotebookLM notebook in one batch,
    using session continuity so each question has full prior context.

    ``questions`` must be a JSON array of strings, e.g. ``["Q1?", "Q2?"]``.
    Returns a JSON array of ``{answer, sources, session_id}`` dicts.
    """
    from engine.mcp.tools.nlm import notebooklm_node_batch_ask
    return await notebooklm_node_batch_ask(notebook_id, questions)



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
    from engine.mcp.tools.nlm import notebooklm_node_add_source
    return await notebooklm_node_add_source(notebook_id, source_type, source_value, title)



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
    from engine.mcp.tools.nlm import notebooklm_node_create_notebook
    return await notebooklm_node_create_notebook(name, sources, description, topics)



@mcp.tool()
async def notebooklm_node_list_notebooks() -> str:
    """List all NotebookLM notebooks in the authenticated account.
    Returns JSON array of ``{id, title, source_count, url}`` objects.
    """
    from engine.mcp.tools.nlm import notebooklm_node_list_notebooks
    return await notebooklm_node_list_notebooks()



@mcp.tool()
async def notebooklm_node_generate_audio(notebook_id: str) -> str:
    """Generate a podcast-style audio overview of a NotebookLM notebook
    via the Node bridge. Returns JSON with ``status`` and ``progress``.
    """
    from engine.mcp.tools.nlm import notebooklm_node_generate_audio
    return await notebooklm_node_generate_audio(notebook_id)



@mcp.tool()
async def notebooklm_node_generate_video(notebook_id: str, style: str = "cinematic") -> str:
    """Generate a video overview of a NotebookLM notebook via the Node bridge.
    Supported styles: cinematic, documentary, minimalist, energetic, calm,
    data_viz, narrative, academic, news, creative.
    Returns JSON with ``video_id`` and ``status``.
    """
    from engine.mcp.tools.nlm import notebooklm_node_generate_video
    return await notebooklm_node_generate_video(notebook_id, style)



@mcp.tool()
async def notebooklm_node_extract_tables(notebook_id: str, query: str = "") -> str:
    """Extract structured data tables from a NotebookLM notebook's sources.
    Optionally filter by ``query`` topic. Returns JSON with ``tables`` list,
    each table having ``headers`` and ``rows``.
    """
    from engine.mcp.tools.nlm import notebooklm_node_extract_tables
    return await notebooklm_node_extract_tables(notebook_id, query)



@mcp.tool()
async def notebooklm_node_chat_history(notebook_id: str, limit: int = 20) -> str:
    """Get recent chat/Q&A history for a NotebookLM notebook.
    Returns JSON array of ``{question, answer, timestamp}`` objects.
    """
    from engine.mcp.tools.nlm import notebooklm_node_chat_history
    return await notebooklm_node_chat_history(notebook_id, limit)



@mcp.tool()
async def notebooklm_node_health() -> str:
    """Get combined health status of both NLM backends: Node MCP bridge
    (Patchright) and batchexecute proxy. Returns JSON with auth state,
    available tools, proxy reachability, and Chrome profile status.
    """
    from engine.mcp.tools.nlm import notebooklm_node_health
    return await notebooklm_node_health()



@mcp.tool()
async def notebooklm_node_setup_auth() -> str:
    """Run first-time Google authentication for the Node MCP bridge.
    Opens Chrome visibly — log in once and the profile is saved permanently.
    All subsequent calls work in headless mode automatically.
    Only callable by copilot (admin operation).
    """
    from engine.mcp.tools.nlm import notebooklm_node_setup_auth
    return await notebooklm_node_setup_auth()



@mcp.tool()
async def notebooklm_node_sync_nexus(notebook_id: str, questions: str) -> str:
    """Batch-ask questions against a NotebookLM notebook and automatically
    store every answer as a Q&A pair in Nexus. This is the primary method
    for distilling notebook knowledge into the Nexus knowledge base.

    ``questions`` must be a JSON array of strings.
    Returns JSON with ``stored`` count, ``errors``, and each Q&A pair.
    """
    from engine.mcp.tools.nlm import notebooklm_node_sync_nexus
    return await notebooklm_node_sync_nexus(notebook_id, questions)



# ── Local Agent Bridge Tools ──────────────────────────────────────────────

@mcp.tool()
async def local_agent_get_tasks(model_size: str = "worker", limit: int = 10,
                                 tags: str = "") -> str:
    """Get pending tasks for a local agent by model size.

    model_size: 'router', 'mini', 'worker', or 'expert'.
    tags: optional comma-separated tag filter.
    Returns JSON list of task dicts sorted by priority.
    """
    from engine.mcp.tools.scheduler import local_agent_get_tasks
    return local_agent_get_tasks(model_size, limit, tags)



@mcp.tool()
async def local_agent_claim_task(task_id: str, agent_id: str) -> str:
    """Claim a task for execution by this agent.

    task_id: ID of the task to claim.
    agent_id: Unique identifier for this agent (e.g. 'worker-qwen-7b-1').
    Returns claimed task dict or error.
    """
    from engine.mcp.tools.scheduler import local_agent_claim_task
    return local_agent_claim_task(task_id, agent_id)



@mcp.tool()
async def local_agent_task_context(task_id: str) -> str:
    """Get full execution context for a claimed task.

    Includes: task metadata, relevant Nexus knowledge, coding rules, and
    step-by-step execution guide. Inject this into the agent's system prompt.
    """
    from engine.mcp.tools.scheduler import local_agent_task_context
    return local_agent_task_context(task_id)



@mcp.tool()
async def local_agent_complete_task(task_id: str, result: str,
                                     files_changed: str = "") -> str:
    """Mark a task as completed and store the result in Nexus.

    task_id: ID of the completed task.
    result: 1-2 sentence summary of what was accomplished.
    files_changed: optional comma-separated list of files modified.
    """
    from engine.mcp.tools.scheduler import local_agent_complete_task
    return local_agent_complete_task(task_id, result, files_changed)



@mcp.tool()
async def local_agent_fail_task(task_id: str, reason: str, retry: bool = False) -> str:
    """Mark a task as failed.

    task_id: ID of the failed task.
    reason: Explanation of why it failed.
    retry: If True, reset to 'pending' so another agent can pick it up.
    """
    from engine.mcp.tools.scheduler import local_agent_fail_task
    return local_agent_fail_task(task_id, reason, retry)



@mcp.tool()
async def local_agent_manifest(model_size: str = "worker") -> str:
    """Get the system prompt manifest for a local agent of the specified size.

    Returns a formatted string ready to inject into an LLM system prompt.
    model_size: 'router', 'mini', 'worker', or 'expert'.
    """
    from engine.mcp.tools.scheduler import local_agent_manifest
    return local_agent_manifest(model_size)



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
    from engine.mcp.tools.master_notebook import master_notebook_build
    return master_notebook_build(sources_only, generators_only, notebook_id, dry_run)



@mcp.tool()
async def master_notebook_status() -> str:
    """Get status of the master notebook build (what's been done, what's pending)."""
    from engine.mcp.tools.master_notebook import master_notebook_status
    return master_notebook_status()



@mcp.tool()
async def master_notebook_reset() -> str:
    """Reset master notebook build state (forces fresh creation and full re-upload).

    WARNING: This will delete the stored notebook ID. A new notebook will be
    created on the next build. Use this when you want a completely fresh start.
    """
    from engine.mcp.tools.master_notebook import master_notebook_reset
    return master_notebook_reset()



@mcp.tool()
async def master_notebook_list_sources() -> str:
    """List all sources that will be included in the master notebook.

    Shows all 13 code bundles + 19 SDK documentation URLs.
    """
    from engine.mcp.tools.master_notebook import master_notebook_list_sources
    return master_notebook_list_sources()



# ── QA Expander Tools ─────────────────────────────────────────────────────────

@mcp.tool()
async def qa_expander_run(batch_size: int = 20, dry_run: bool = False) -> str:
    """Run one batch of QA expansion — reverse-generate Q&A pairs from Nexus entries.

    For each entry, asks NLM to generate 5 questions it answers, then stores
    the pairs in Nexus for instant cache hits. Processes batch_size entries per call.

    batch_size: Number of entries to process (default 20).
    dry_run: Show what would be processed without making NLM calls.
    """
    from engine.mcp.tools.qa import qa_expander_run
    return qa_expander_run(batch_size, dry_run)



@mcp.tool()
async def qa_expander_stats() -> str:
    """Show QA expansion progress: entries expanded, pairs generated, last run."""
    from engine.mcp.tools.qa import qa_expander_stats
    return qa_expander_stats()



@mcp.tool()
async def qa_expander_reset() -> str:
    """Reset QA expansion state — next run will start from the beginning.

    WARNING: This clears all progress tracking. The Q&A pairs already stored
    in Nexus are preserved, but expansion will re-process all entries.
    """
    from engine.mcp.tools.qa import qa_expander_reset
    return qa_expander_reset()



@mcp.tool()
async def qa_expander_reset() -> str:
    """Reset QA expansion state — next run will start from the beginning.    WARNING: This clears all progress tracking. The Q&A pairs already stored
    in Nexus are preserved, but expansion will re-process all entries.
    """
    from engine.mcp.tools.qa import qa_expander_reset
    return qa_expander_reset()



# ──── Fine-tune & Training MCP Tools ─────────────────────────────────────────

@mcp.tool()
async def finetune_submit(model_type: str, base_model: str = "") -> str:
    """Submit a new fine-tuning job for a micro-model type.

    Args:
        model_type: qa_evaluator | conversation_analyzer | syntax_fixer | router_v2 | knowledge_synthesizer
        base_model: HuggingFace model ID or alias (qwen-270m, qwen-1.7b, llama-3b). Default: auto.
    """
    from engine.mcp.tools.training import finetune_submit
    return finetune_submit(model_type, base_model)



@mcp.tool()
async def finetune_run_next() -> str:
    """Run the next pending fine-tuning job. Blocks until complete."""
    from engine.mcp.tools.training import finetune_run_next
    return finetune_run_next()



@mcp.tool()
async def finetune_list_jobs(status: str = "") -> str:
    """List all fine-tuning jobs.

    Args:
        status: Filter by status (pending|running|done|failed). Empty = all.
    """
    from engine.mcp.tools.training import finetune_list_jobs
    return finetune_list_jobs(status)



@mcp.tool()
async def finetune_build_dataset(model_type: str, count: int = 500) -> str:
    """Build training dataset for a micro-model type using NLM teacher.

    Args:
        model_type: Target model type.
        count: Number of examples to generate.
    """
    from engine.mcp.tools.training import finetune_build_dataset
    return finetune_build_dataset(model_type, count)



@mcp.tool()
async def finetune_dataset_status() -> str:
    """Show dataset sizes for all micro-model types."""
    from engine.mcp.tools.training import finetune_dataset_status
    return finetune_dataset_status()



@mcp.tool()
async def model_registry_list(model_type: str = "") -> str:
    """List registered fine-tuned models.

    Args:
        model_type: Filter by type. Empty = all.
    """
    from engine.mcp.tools.training import model_registry_list
    return model_registry_list(model_type)



@mcp.tool()
async def model_benchmark_run(model_type: str = "") -> str:
    """Run benchmarks on fine-tuned models.

    Args:
        model_type: Type to benchmark. Empty = run all.
    """
    from engine.mcp.tools.training import model_benchmark_run
    return model_benchmark_run(model_type)



@mcp.tool()
async def model_benchmark_leaderboard() -> str:
    """Show the best benchmark score per micro-model type."""
    from engine.mcp.tools.training import model_benchmark_leaderboard
    return model_benchmark_leaderboard()



@mcp.tool()
async def model_promote(model_id: str, model_type: str) -> str:
    """Manually promote a fine-tuned model as the active one for its type.

    Args:
        model_id: Registry model ID (8-char).
        model_type: Model type (qa_evaluator, router_v2, etc.).
    """
    from engine.mcp.tools.training import model_promote
    return model_promote(model_id, model_type)



@mcp.tool()
async def teacher_generate_dataset(model_type: str, count: int = 300) -> str:
    """Generate a training dataset via NLM teacher pipeline (Gemini 3.0).

    Args:
        model_type: Target micro-model type.
        count: Number of examples to generate.
    """
    from engine.mcp.tools.training import teacher_generate_dataset
    return teacher_generate_dataset(model_type, count)



@mcp.tool()
async def finetuned_router_status() -> str:
    """Show which fine-tuned models are currently active in the router."""
    from engine.mcp.tools.training import finetuned_router_status
    return finetuned_router_status()



@mcp.tool()
async def finetuned_router_load_registry() -> str:
    """Load all active fine-tuned models from the model registry into the router."""
    from engine.mcp.tools.training import finetuned_router_load_registry
    return finetuned_router_load_registry()



@mcp.tool()
async def backup_run() -> str:
    """Trigger an immediate database backup."""
    from engine.mcp.tools.backup import backup_run
    return backup_run()



@mcp.tool()
async def backup_list() -> str:
    """List all available database backups."""
    from engine.mcp.tools.backup import backup_list
    return backup_list()



@mcp.tool()
async def backup_restore(backup_path: str, target: str = "nexus") -> str:
    """Restore a specific database backup.

    Args:
        backup_path: Path to the backup file.
        target: Which database to restore (nexus | session | all).
    """
    from engine.mcp.tools.backup import backup_restore
    return backup_restore(backup_path, target)



@mcp.tool()
async def user_profile_get() -> str:
    """Retrieve the current user profile (extracted from conversations)."""
    from engine.mcp.tools.user_profile import user_profile_get
    return user_profile_get()



@mcp.tool()
async def user_profile_update(updates: str) -> str:
    """Merge updates into the user profile.

    Args:
        updates: JSON string with profile fields to update.
    """
    from engine.mcp.tools.user_profile import user_profile_update
    return user_profile_update(updates)



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