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
    status = {"version": "0.52b", "services": {}, "scenes": {}, "skills": {}}

    try:
        cfg = _get_config()
        status["config"] = {
            "lmstudio_url": cfg.get("lmstudio.base_url", "unknown"),
            "load_mode": cfg.get("lmstudio.load_mode", "unknown"),
        }
    except Exception:
        status["config"] = {"error": "unavailable"}

    try:
        from engine.lmstudio.lms_client import LMSClient
        client = LMSClient()
        models = client.get_models(loaded_only=False)
        loaded = client.get_models(loaded_only=True)
        status["services"]["lmstudio"] = {
            "available": True,
            "models_available": len(models) if models else 0,
            "models_loaded": len(loaded) if loaded else 0,
        }
    except Exception:
        status["services"]["lmstudio"] = {"available": False}

    nx = _get_nexus()
    if nx:
        try:
            status["services"]["nexus"] = {"available": nx.is_available()}
        except Exception:
            status["services"]["nexus"] = {"available": False}
    else:
        status["services"]["nexus"] = {"available": False}

    try:
        from engine.skills.registry import SKILL_REGISTRY
        desc = SKILL_REGISTRY.describe()
        packs = SKILL_REGISTRY.all_packs()
        status["skills"] = {
            "total": len(desc),
            "packs": len(packs),
            "pack_names": sorted(packs),
        }
    except Exception:
        status["skills"] = {"error": "unavailable"}

    try:
        from engine.scenes.base_scene import BaseScene
        active = BaseScene.get_active_scenes() if hasattr(BaseScene, "get_active_scenes") else {}
        status["scenes"]["active"] = list(active.keys()) if active else []
    except Exception:
        status["scenes"]["active"] = []

    return json.dumps(status)


@mcp.tool()
def list_all_skills() -> str:
    """List all registered MCP skills grouped by pack."""
    try:
        from engine.skills.registry import SKILL_REGISTRY
        desc = SKILL_REGISTRY.describe()
        packs_map: dict = {}
        for name, meta in desc.items():
            pack = meta.get("pack", "unknown")
            packs_map.setdefault(pack, []).append({
                "name": name,
                "description": meta.get("description", ""),
                "cooldown": meta.get("cooldown", 0),
            })
        return json.dumps({
            "packs": packs_map,
            "total_skills": sum(len(v) for v in packs_map.values()),
            "total_packs": len(packs_map),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_skill_info(skill_name: str) -> str:
    """Get detailed information about a specific MCP skill."""
    try:
        from engine.skills.registry import SKILL_REGISTRY
        desc = SKILL_REGISTRY.describe()
        if skill_name not in desc:
            return json.dumps({"error": f"Skill '{skill_name}' not found"})
        meta = desc[skill_name]
        return json.dumps({
            "name": skill_name,
            "description": meta.get("description", ""),
            "pack": meta.get("pack", "unknown"),
            "cooldown": meta.get("cooldown", 0),
            "parameters": meta.get("parameters", {}),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_benchmark_stats() -> str:
    """Get performance benchmark statistics."""
    try:
        from engine.mcp.tools.utility_tools import get_benchmark_stats_logic as _impl
        return _impl()
    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════════
# NEXUS BRIDGE — Knowledge management
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def nexus_search(query: str, limit: int = 10) -> str:
    """Search the Nexus knowledge base for entries matching a query."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        results = nx.search(query, limit=limit)
        return json.dumps({"results": results, "count": len(results)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_ask(question: str, depth: str = "auto", category: str = "") -> str:
    """Smart Q&A against Nexus — checks Q&A cache first, then FTS5 search,
    then NotebookLM if needed."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        answer = nx.ask(question, depth=depth, category=category)
        return json.dumps(answer)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_add(title: str, content: str, content_type: str = "note",
              category: str = "", tags: str = "") -> str:
    """Store a knowledge entry in Nexus. Tags should be comma-separated."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        entry_id = nx.add_entry(title, content, content_type=content_type,
                                category=category, tags=tag_list)
        if entry_id:
            return json.dumps({"ok": True, "id": entry_id})
        return json.dumps({"ok": False, "error": "Failed to add entry"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_add_qa(question: str, answer: str, category: str = "",
                 tags: str = "") -> str:
    """Store a question-answer pair in Nexus for future lookups."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        qa_id = nx.add_qa(question, answer, category=category, tags=tag_list)
        if qa_id:
            return json.dumps({"ok": True, "id": qa_id})
        return json.dumps({"ok": False, "error": "Failed to add Q&A"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_get_rules(scope: str = "", rule_type: str = "") -> str:
    """Get active governance rules from Nexus."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        rules = nx.get_rules(scope=scope, rule_type=rule_type)
        return json.dumps({"rules": rules, "count": len(rules)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_store_prompt(name: str, content: str, category: str = "",
                       version: str = "") -> str:
    """Store or version a prompt template in Nexus."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        result = nx.store_prompt(name, content, category=category, version=version)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_get_prompts(category: str = "", name: str = "") -> str:
    """Retrieve stored prompts from Nexus."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        prompts = nx.get_prompts(category=category, name=name)
        return json.dumps({"prompts": prompts, "count": len(prompts)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_research(question: str) -> str:
    """Start a deep research session via NotebookLM."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        result = nx.research(question)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_converse(research_id: str, message: str) -> str:
    """Continue an existing research session with a follow-up."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        result = nx.converse(research_id, message)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_finish_research(research_id: str) -> str:
    """Close a research session and distill findings into Q&A pairs."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        result = nx.finish_research(research_id)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_import_youtube(url: str, category: str = "", tags: str = "") -> str:
    """Import a YouTube video transcript into Nexus."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        result = nx.import_youtube(url, category=category, tags=tag_list)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_log_session(project: str = "CosySim", repo: str = "",
                      branch: str = "") -> str:
    """Log a work session to Nexus for tracking."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        result = nx.log_session(project=project, repo=repo, branch=branch)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_status() -> str:
    """Check Nexus health and get basic stats."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable", "available": False})
        status = nx.status()
        return json.dumps(status)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_list_plugins(scope: str = "") -> str:
    """List available Nexus plugins."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        plugins = nx.list_plugins(scope=scope)
        return json.dumps({"plugins": plugins, "count": len(plugins)})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════════
# NEXUS MEMORY — Agent memory management
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def nexus_remember(content: str, agent_id: str = "copilot",
                   memory_type: str = "observation", importance: float = 0.5) -> str:
    """Store a memory in Nexus for an agent or Copilot."""
    try:
        from engine.nexus.nexus_memory import NexusMemory
        namespace = "copilot" if agent_id == "copilot" else "agent"
        mem = NexusMemory(namespace=namespace, agent_id=agent_id)
        entry_id = mem.remember(content, importance=importance, memory_type=memory_type)
        return json.dumps({"status": "ok", "entry_id": entry_id, "agent": agent_id})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_recall(query: str, agent_id: str = "copilot", limit: int = 5) -> str:
    """Recall memories from Nexus for an agent or Copilot."""
    try:
        from engine.nexus.nexus_memory import NexusMemory
        namespace = "copilot" if agent_id == "copilot" else "agent"
        mem = NexusMemory(namespace=namespace, agent_id=agent_id)
        memories = mem.recall(query, top_k=limit)
        return json.dumps({"status": "ok", "memories": memories, "count": len(memories)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_memory_context(agent_id: str = "copilot", max_tokens: int = 500) -> str:
    """Get a compact memory context window for an agent."""
    try:
        from engine.nexus.nexus_memory import NexusMemory
        namespace = "copilot" if agent_id == "copilot" else "agent"
        mem = NexusMemory(namespace=namespace, agent_id=agent_id)
        context = mem.get_context_window(max_chars=max_tokens)
        return json.dumps({"status": "ok", "context": context, "agent": agent_id})
    except Exception as e:
        return json.dumps({"error": str(e)})


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
            return json.dumps({"error": f"Invalid source '{source}'. Use: {sorted(valid)}"})
        counts = seeder.seed(source)
        return json.dumps({"status": "ok", "source": source, "created": counts})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_distill(action: str = "stats") -> str:
    """Distill raw session data into reusable knowledge. Actions:
    stats, distill, compact, primer, dedup, dedup-dry, skills, prompts, lineage, all"""
    try:
        from engine.nexus.nexus_distiller import (
            NexusDistiller, QADeduplicator, SkillUsageDistiller,
            PromptEvolutionDistiller, run_all_distillers,
        )
        dispatch = {
            "stats": lambda: NexusDistiller().get_stats(),
            "distill": lambda: NexusDistiller().distill(),
            "compact": lambda: NexusDistiller().compact_sessions(),
            "primer": lambda: NexusDistiller().generate_context_primer(),
            "dedup": lambda: QADeduplicator().deduplicate(dry_run=False),
            "dedup-dry": lambda: QADeduplicator().deduplicate(dry_run=True),
            "skills": lambda: SkillUsageDistiller().distill_and_store(),
            "prompts": lambda: PromptEvolutionDistiller().distill_patterns(),
            "lineage": lambda: PromptEvolutionDistiller().get_lineage(),
            "all": lambda: run_all_distillers(),
        }
        if action not in dispatch:
            return json.dumps({"error": f"Unknown action '{action}'. Use: {sorted(dispatch)}"})
        result = dispatch[action]()
        if isinstance(result, str):
            return result
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_export_session() -> str:
    """Export current Copilot session history to Nexus."""
    try:
        from engine.nexus.nexus_session_logger import _find_session_id, _get_session_history
        session_id = _find_session_id()
        if not session_id:
            return json.dumps({"error": "No active session found"})

        history = _get_session_history(session_id)
        stored = 0

        from engine.nexus.nexus_session_logger import _build_conversation_log, _now
        conv = _build_conversation_log(history)
        if conv and len(conv) > 100:
            if len(conv) > 50000:
                conv = conv[:50000] + "\n\n[TRUNCATED]"
            import requests as req
            r = req.post("http://127.0.0.1:8700/api/entries", json={
                "title": f"Conversation log — {_now()} ({len(history.get('turns', []))} turns)",
                "content": conv,
                "content_type": "history",
                "category": "sessions",
                "tags": ["session", "copilot", "conversation-log",
                         f"turns:{len(history.get('turns', []))}"],
            }, timeout=10)
            if r.ok:
                stored += 1

        for cp in history.get("checkpoints", []):
            if cp.get("work_done"):
                import requests as req
                r = req.post("http://127.0.0.1:8700/api/entries", json={
                    "title": f"Checkpoint {cp['number']}: {cp.get('title', '')}",
                    "content": f"Overview: {cp.get('overview', '')}\n\nWork: {cp.get('work_done', '')}",
                    "content_type": "history",
                    "category": "sessions",
                    "tags": ["session", "copilot", "checkpoint"],
                }, timeout=10)
                if r.ok:
                    stored += 1

        return json.dumps({
            "status": "ok",
            "session_id": session_id,
            "turns": len(history.get("turns", [])),
            "checkpoints": len(history.get("checkpoints", [])),
            "files": len(history.get("files", [])),
            "entries_stored": stored,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_maintain(action: str = "health") -> str:
    """Run Nexus self-maintenance tasks. Actions:
    health, dedup, dedup-apply, compact, score, full, full-apply"""
    try:
        from engine.nexus.self_maintenance import (
            nexus_health_report, nexus_merge_duplicates,
            nexus_compact_sessions, nexus_score_entries,
            nexus_full_maintenance,
        )
        dispatch = {
            "health": lambda: nexus_health_report(),
            "dedup": lambda: nexus_merge_duplicates(dry_run=True),
            "dedup-apply": lambda: nexus_merge_duplicates(dry_run=False),
            "compact": lambda: nexus_compact_sessions(),
            "score": lambda: nexus_score_entries(),
            "full": lambda: nexus_full_maintenance(dry_run=True),
            "full-apply": lambda: nexus_full_maintenance(dry_run=False),
        }
        if action not in dispatch:
            return json.dumps({"error": f"Unknown action: {action}",
                              "available": sorted(dispatch)})
        result = dispatch[action]()
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_smart_query(question: str, min_confidence: float = 0.3,
                      use_llm: bool = True, category: str = "") -> str:
    """Route a query through the Nexus-first pipeline.
    Checks Q&A cache → FTS search → Nexus ask → LLM fallback."""
    try:
        from engine.nexus.query_router import get_query_router
        router = get_query_router()
        result = router.query(
            question, min_confidence=min_confidence,
            use_llm=use_llm, category=category,
            source_hint="copilot",
        )
        return json.dumps(result.to_dict(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_router_stats() -> str:
    """Get NexusQueryRouter statistics: hit rates, cache performance, tokens saved."""
    try:
        from engine.nexus.query_router import get_query_router
        router = get_query_router()
        return json.dumps(router.stats.to_dict(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════════
# TRAINING & CONTENT — Data capture and generation
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def capture_training_data(user_message: str, agent_response: str,
                          dataset_type: str = "conversation",
                          quality_score: float = 0.7,
                          character_id: str = "") -> str:
    """Capture an LLM interaction as training data for fine-tuning."""
    try:
        from engine.nexus.training_pipeline import get_training_pipeline
        tp = get_training_pipeline()
        entry_id = tp.capture_interaction(
            user_message, agent_response,
            dataset_type=dataset_type,
            quality_score=quality_score,
            character_id=character_id or None,
        )
        return json.dumps({"status": "ok", "entry_id": entry_id, "type": dataset_type})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def generate_content(character_id: str, content_type: str = "greetings") -> str:
    """Generate pre-built content for a character. Types: greetings, reactions."""
    try:
        from engine.nexus.workflows import ContentWorkflow
        cw = ContentWorkflow()
        if content_type == "greetings":
            ids = cw.generate_greetings(character_id)
        elif content_type == "reactions":
            ids = cw.generate_reactions(character_id)
        else:
            return json.dumps({"error": f"Unknown type '{content_type}'. Use: greetings, reactions"})
        return json.dumps({"status": "ok", "entries_created": len(ids), "ids": ids[:5]})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════════
# COPILOT INTEGRATION — Session helpers
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def copilot_store_snippet(title: str, code: str, language: str = "python",
                          tags: str = "") -> str:
    """Store a reusable code snippet in Nexus for future sessions."""
    try:
        from engine.nexus.copilot_helpers import store_snippet
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        result = store_snippet(title, code, language, tag_list)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def copilot_store_discovery(title: str, finding: str,
                            category: str = "debugging") -> str:
    """Store a discovery, workaround, or gotcha in Nexus."""
    try:
        from engine.nexus.copilot_helpers import store_discovery
        result = store_discovery(title, finding, category)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def copilot_log_progress(task: str, status: str = "completed", details: str = "",
                         tests_passed: int = 0, commit_sha: str = "") -> str:
    """Log work progress to Nexus for tracking across sessions."""
    try:
        from engine.nexus.copilot_helpers import log_work_progress
        result = log_work_progress(task, status, details, tests_passed=tests_passed,
                                   commit_sha=commit_sha)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def copilot_context_primer(project: str = "CosySim") -> str:
    """Generate a context primer from Nexus knowledge for new sessions."""
    try:
        from engine.nexus.copilot_helpers import generate_context_primer
        return generate_context_primer(project)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def copilot_local_model_guide(task_type: str = "general") -> str:
    """Get guidance text for local LMStudio models to safely use Nexus."""
    try:
        from engine.nexus.copilot_helpers import generate_local_model_guidance
        return generate_local_model_guidance(task_type)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════════
# AGENT TASK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
def agent_create_task(title: str, description: str = "", agent: str = "copilot",
                      priority: str = "normal", tags: str = "") -> str:
    """Create a tracked agent task in Nexus. Returns task ID."""
    try:
        from engine.nexus.agent_tags import get_task_manager
        mgr = get_task_manager()
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        task_id = mgr.create_task(title, description, agent, priority, tag_list)
        return json.dumps({"task_id": task_id, "status": "created"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def agent_update_task(task_id: str, status: str) -> str:
    """Update an agent task status (pending/in_progress/done/blocked/cancelled)."""
    try:
        from engine.nexus.agent_tags import get_task_manager
        ok = get_task_manager().update_status(task_id, status)
        return json.dumps({"updated": ok})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def agent_complete_task(task_id: str, summary: str = "") -> str:
    """Mark an agent task as done with an optional completion summary."""
    try:
        from engine.nexus.agent_tags import get_task_manager
        ok = get_task_manager().complete_task(task_id, summary)
        return json.dumps({"completed": ok})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def agent_list_tasks(status: str = "", agent: str = "", limit: int = 20) -> str:
    """List agent tasks, optionally filtered by status and agent."""
    try:
        from engine.nexus.agent_tags import get_task_manager
        tasks = get_task_manager().list_tasks(
            status=status or None, agent=agent or None, limit=limit)
        return json.dumps([t.to_dict() for t in tasks], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


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
        return json.dumps(get_scheduler_daemon().run_task(task_id), indent=2, default=str)
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
            [{"title": a.title, "url": a.url, "score": round(a.score, 2),
              "source": a.source_id, "category": a.category}
             for a in filtered[:20]],
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
        return json.dumps({"fetched": len(articles), "filtered": len(filtered), "stored": stored})
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
    """List all managed NLM notebooks with health: source counts, ages,
    last seeded/asked dates, and overall slot health."""
    try:
        from engine.nexus.nlm_notebook_manager import get_notebook_manager
        return json.dumps(get_notebook_manager().health(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nlm_notebook_seed(slot_name: str = "cosysim-architecture", source_type: str = "docs") -> str:
    """Seed an NLM notebook from project files. source_type: 'docs' for
    documentation, 'code' for engine source files."""
    try:
        from engine.nexus.nlm_notebook_manager import get_notebook_manager
        mgr = get_notebook_manager()
        if source_type == "code":
            return json.dumps(mgr.seed_from_code(slot_name), indent=2, default=str)
        return json.dumps(mgr.seed_from_docs(slot_name), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nlm_notebook_rotate(slot_name: str) -> str:
    """Rotate (delete & recreate) an NLM notebook to refresh stale content."""
    try:
        from engine.nexus.nlm_notebook_manager import get_notebook_manager
        return json.dumps(get_notebook_manager().rotate_notebook(slot_name), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def nexus_quality_report() -> str:
    """Score all Nexus entries by freshness, quality, uniqueness, and
    completeness. Returns distribution, low-quality entries, duplicates,
    stale entries, and actionable recommendations."""
    try:
        from engine.nexus.self_maintenance import quality_report
        return json.dumps(quality_report(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def governance_validate(filepath: str) -> str:
    """Validate a Python file against all CosySim coding standards.
    Returns violations with rule names, severity, messages, and line numbers."""
    try:
        from engine.nexus.governance_rules import get_governance_manager
        return json.dumps(get_governance_manager().validate_file(filepath), indent=2, default=str)
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
        return json.dumps({"agent_id": agent_id, "operation": operation, "allowed": allowed})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def governance_enforce(filepath: str = "", agent_id: str = "copilot",
                       operation: str = "write", commit_message: str = "") -> str:
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
            return json.dumps({
                "allowed": False,
                "rule": ge.rule,
                "message": str(ge),
                "severity": ge.severity,
                "violations": ge.violations,
            }, default=str)
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
            stale = [{"id": s.get("entry_id", ""), "title": s.get("title", "")}
                     for s in report.get("stale", [])[:5]]
            tasks = scheduler.generate_from_stale_knowledge(stale)
        elif source == "tests":
            import subprocess, sys
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "--tb=line", "-q",
                 "--ignore=tests/test_agent_loop.py", "--ignore=tests/live_wire_test.py"],
                capture_output=True, text=True, timeout=600
            )
            tasks = scheduler.generate_from_test_failures(result.stdout + result.stderr)
        return json.dumps(
            {"source": source, "tasks_created": len(tasks),
             "tasks": [{"id": t.id, "title": t.title} for t in tasks]},
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def task_from_template(template_name: str, title: str = "",
                       description: str = "", target_files: str = "") -> str:
    """Create a task from a template: bug-fix, feature, refactor, test,
    doc-update, skill-add, scene-polish, knowledge-refresh.
    target_files is comma-separated."""
    try:
        from engine.nexus.task_scheduler import get_task_scheduler
        files = [f.strip() for f in target_files.split(",") if f.strip()] if target_files else []
        task = get_task_scheduler().from_template(
            template_name, title=title, description=description, target_files=files
        )
        return json.dumps({"id": task.id, "title": task.title, "template": template_name})
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
        return json.dumps(get_auto_diagnosis().full_pipeline(pytest_output), indent=2, default=str)
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
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def training_stats() -> str:
    """Get training data flywheel statistics — example counts by source,
    total examples, export history, and quality distribution."""
    try:
        from engine.nexus.training_flywheel import get_training_flywheel
        return json.dumps(get_training_flywheel().stats(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def training_export(format: str = "jsonl", min_quality: float = 0.5) -> str:
    """Export training data for model fine-tuning. format: 'jsonl' (instruction),
    'sharegpt' (conversation), or 'dpo' (preference). Returns export path and count."""
    try:
        from engine.nexus.training_flywheel import get_training_flywheel
        fw = get_training_flywheel()
        if format == "sharegpt":
            return json.dumps(fw.export_sharegpt(min_quality=min_quality), indent=2, default=str)
        elif format == "dpo":
            return json.dumps(fw.export_dpo(), indent=2, default=str)
        else:
            return json.dumps(fw.export_jsonl(min_quality=min_quality), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def training_sync_nexus() -> str:
    """Sync all Nexus Q&A pairs into the training flywheel for fine-tuning.
    Deduplicates against existing examples."""
    try:
        from engine.nexus.training_flywheel import get_training_flywheel
        return json.dumps(get_training_flywheel().sync_from_nexus(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def metrics_dashboard(hours: int = 24) -> str:
    """Generate a full system metrics dashboard in markdown with trends,
    comparisons, and active alerts."""
    try:
        from engine.nexus.meta_metrics import get_meta_metrics
        return get_meta_metrics().dashboard(hours=hours)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def metrics_collect_all() -> str:
    """Collect and record all current system metrics — VRAM, Nexus stats,
    inference stats, test counts. Returns recorded values."""
    try:
        from engine.nexus.meta_metrics import get_meta_metrics
        return json.dumps(get_meta_metrics().collect_all(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def metrics_check_regressions(threshold_pct: float = 10.0) -> str:
    """Check all tracked metrics for regressions against baselines.
    Returns alerts for any metrics that degraded beyond the threshold."""
    try:
        from engine.nexus.meta_metrics import get_meta_metrics
        alerts = get_meta_metrics().check_regressions(threshold_pct=threshold_pct)
        return json.dumps(
            [{"metric": a.metric_name, "type": a.alert_type, "message": a.message,
              "current": a.current_value, "baseline": a.baseline_value}
             for a in alerts],
            indent=2, default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def metrics_snapshot() -> str:
    """Get the most recent value for every tracked metric."""
    try:
        from engine.nexus.meta_metrics import get_meta_metrics
        return json.dumps(get_meta_metrics().snapshot(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── System Reflection Tools ──────────────────────────────────────────


@mcp.tool()
def reflection_run(period: str = "weekly", days: int = 7, use_nlm: bool = False) -> str:
    """Run a system reflection analysis — collect metrics, analyze patterns, generate insights, create tasks."""
    try:
        from engine.nexus.system_reflection import get_system_reflection
        report = get_system_reflection().run_reflection(period=period, days=days, use_nlm=use_nlm)
        return json.dumps({
            "report_id": report.report_id,
            "period": report.period,
            "insight_count": len(report.insights),
            "tasks_created": len(report.tasks_created),
            "insights": [
                {"title": i.title, "category": i.category, "priority": i.priority,
                 "actionable": i.actionable, "description": i.description[:200]}
                for i in report.insights
            ],
            "duration_seconds": report.duration_seconds,
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def reflection_history(limit: int = 5) -> str:
    """Get recent system reflection reports and their summaries."""
    try:
        from engine.nexus.system_reflection import get_system_reflection
        return json.dumps(get_system_reflection().get_history(limit=limit), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def reflection_latest_insights(limit: int = 10) -> str:
    """Get insights from the most recent system reflection."""
    try:
        from engine.nexus.system_reflection import get_system_reflection
        return json.dumps(get_system_reflection().latest_insights(limit=limit), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Experiment Proposal Tools ────────────────────────────────────────


@mcp.tool()
def experiment_scan_and_propose() -> str:
    """Scan current metrics against templates and propose experiments for triggered conditions."""
    try:
        from engine.nexus.experiment_proposals import get_experiment_proposer
        proposals = get_experiment_proposer().scan_and_propose()
        return json.dumps([
            {"proposal_id": p.proposal_id, "experiment_name": p.experiment_name,
             "trigger_metric": p.trigger_metric, "trigger_value": p.trigger_value,
             "priority": p.priority, "hypothesis": p.hypothesis}
            for p in proposals
        ], default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def experiment_list_proposals(status: str = "") -> str:
    """List experiment proposals. Filter: 'pending', 'active', or '' for all."""
    try:
        from engine.nexus.experiment_proposals import get_experiment_proposer
        s = status if status else None
        return json.dumps(get_experiment_proposer().get_proposals(status=s), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def experiment_list_templates() -> str:
    """List all experiment templates with their triggers and thresholds."""
    try:
        from engine.nexus.experiment_proposals import get_experiment_proposer
        return json.dumps(get_experiment_proposer().list_templates(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Copilot Self-Configuration Tools ─────────────────────────────────


@mcp.tool()
def copilot_sync_config() -> str:
    """Sync all Copilot instruction files, agent definitions, and hooks to Nexus."""
    try:
        from engine.nexus.copilot_self_config import get_copilot_config
        return json.dumps(get_copilot_config().sync_all_to_nexus(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def copilot_config_status() -> str:
    """Get Copilot configuration status — counts of instructions, agents, hooks."""
    try:
        from engine.nexus.copilot_self_config import get_copilot_config
        return json.dumps(get_copilot_config().status(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def copilot_list_instructions() -> str:
    """List all Copilot instruction files with names and sizes."""
    try:
        from engine.nexus.copilot_self_config import get_copilot_config
        return json.dumps(get_copilot_config().list_instructions(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def copilot_list_agents() -> str:
    """List all Copilot agent definition files."""
    try:
        from engine.nexus.copilot_self_config import get_copilot_config
        return json.dumps(get_copilot_config().list_agents(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Knowledge Graph Tools ────────────────────────────────────────────


@mcp.tool()
def knowledge_graph_build() -> str:
    """Build the knowledge graph from Nexus entries — extracts topics, edges, gaps, clusters."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph
        from dataclasses import asdict
        snap = get_knowledge_graph().build()
        return json.dumps({
            "topic_count": snap.topic_count,
            "edge_count": snap.edge_count,
            "gap_count": snap.gap_count,
            "top_topics": snap.top_topics[:15],
            "gaps": snap.gaps[:10],
            "clusters": snap.clusters[:5],
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def knowledge_graph_gaps() -> str:
    """Detect knowledge gaps — topics with few entries that neighbor strong topics."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph
        from dataclasses import asdict
        gaps = get_knowledge_graph().detect_gaps()
        return json.dumps([asdict(g) for g in gaps], default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def knowledge_graph_clusters() -> str:
    """Get topic clusters from the knowledge graph."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph
        return json.dumps(get_knowledge_graph().cluster_topics(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def knowledge_graph_search(query: str) -> str:
    """Search topics in the knowledge graph by name."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph
        return json.dumps(get_knowledge_graph().search_topics(query), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def knowledge_graph_research_tasks() -> str:
    """Auto-create research tasks for knowledge gaps."""
    try:
        from engine.nexus.knowledge_graph import get_knowledge_graph
        return json.dumps(get_knowledge_graph().create_research_tasks(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Home Assistant Tools ─────────────────────────────────────────────


@mcp.tool()
def ha_connect() -> str:
    """Connect to Home Assistant and discover entities."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        return json.dumps(get_ha_client().connect(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def ha_list_entities(domain: str = "", search: str = "") -> str:
    """List Home Assistant entities filtered by domain or search term."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        entities = get_ha_client().list_entities(
            domain=domain or None, search=search or None,
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
def ha_call_service(domain: str, service: str, entity_id: str = "", data_json: str = "{}") -> str:
    """Call any Home Assistant service with custom parameters."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        extra = json.loads(data_json) if data_json.strip() != "{}" else None
        return json.dumps(get_ha_client().call_service(
            domain, service, entity_id=entity_id or None, data=extra,
        ), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def ha_send_notification(message: str, title: str = "") -> str:
    """Send a push notification to the user's phone via Home Assistant."""
    try:
        from engine.integrations.homeassistant import get_ha_client
        return json.dumps(get_ha_client().send_notification(
            message, title=title or None,
        ), default=str)
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
    """Archive a single NLM notebook into Nexus deep storage — stores metadata, sources, conversations, notes."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().archive_notebook(notebook_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def deep_storage_archive_all() -> str:
    """Archive ALL NLM notebooks into Nexus deep storage."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().archive_all(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def deep_storage_from_har(har_path: str) -> str:
    """Archive notebook content extracted from a browser HAR capture."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().archive_from_har(har_path), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def deep_storage_retrieve(notebook_id: str) -> str:
    """Retrieve all archived content for a notebook from deep storage."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().retrieve(notebook_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def deep_storage_list() -> str:
    """List all archived NLM notebooks in deep storage."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().list_archives(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def deep_storage_search(query: str) -> str:
    """Search across all archived NLM conversations."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().search_conversations(query), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def deep_storage_chain(chain_id: str) -> str:
    """Retrieve all entries in a conversation chain by chain ID."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().get_chain(chain_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def deep_storage_stats() -> str:
    """Get NLM deep storage statistics — archive counts, entries stored."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().stats(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


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
        return json.dumps({
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
        }, default=str)
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
                    pending_pairs.append(CandidatePair(
                        q=p.get("q", ""),
                        a=p.get("a", ""),
                        consumer=p.get("consumer", "developer"),
                        priority=int(p.get("priority", 3)),
                        category=p.get("category", "general"),
                    ))
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
        return json.dumps(get_anythingllm_client().list_workspaces(instance=instance or None))
    except Exception as exc:
        return json.dumps({"error": str(exc)})

@mcp.tool()
def allm_chat(workspace: str, message: str, mode: str = "chat", instance: str = "") -> str:
    """Chat with an AnythingLLM workspace."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client
        result = get_anythingllm_client().chat(workspace, message, mode=mode, instance=instance or None)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})

@mcp.tool()
def allm_sync_to_nexus(workspace: str, instance: str = "") -> str:
    """Sync AnythingLLM workspace Q&A pairs to Nexus."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client
        return json.dumps(get_anythingllm_client().sync_to_nexus(workspace, instance=instance or None))
    except Exception as exc:
        return json.dumps({"error": str(exc)})

@mcp.tool()
def allm_sync_from_nexus(workspace: str, query: str = "*", limit: int = 50, instance: str = "") -> str:
    """Push Nexus knowledge into an AnythingLLM workspace for RAG."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client
        return json.dumps(get_anythingllm_client().sync_from_nexus(workspace, query=query, limit=limit, instance=instance or None))
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── Phone Assistant Tools ─────────────────────────────────────────────


@mcp.tool()
async def phone_assistant_chat(message: str, mode: str = "", voice: bool = False) -> str:
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
async def notebooklm_node_ask(notebook_id: str, question: str, session_id: str = "") -> str:
    """Ask a question to a NotebookLM notebook via the Node MCP bridge
    (Patchright browser automation). Always reliable — handles auth automatically.

    Pass ``session_id`` from a prior response to continue a multi-turn conversation.
    Returns JSON with ``answer``, ``sources``, and ``session_id``.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().ask(
            notebook_id, question,
            session_id=session_id or None,
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def notebooklm_node_batch_ask(notebook_id: str, questions: str) -> str:
    """Ask multiple questions against a NotebookLM notebook in one batch,
    using session continuity so each question has full prior context.

    ``questions`` must be a JSON array of strings, e.g. ``["Q1?", "Q2?"]``.
    Returns a JSON array of ``{answer, sources, session_id}`` dicts.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        q_list = json.loads(questions) if isinstance(questions, str) else questions
        if not isinstance(q_list, list):
            return json.dumps({"error": "questions must be a JSON array"})
        results = get_nlm_hybrid().ask_batch(notebook_id, q_list)
        return json.dumps(results)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


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
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        hybrid = get_nlm_hybrid()
        if source_type == "url" or source_type == "youtube":
            result = hybrid.add_url_source(notebook_id, source_value)
        else:
            result = hybrid.add_text_source(notebook_id, source_value, title=title)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


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
    try:
        from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
        src_list = json.loads(sources) if isinstance(sources, str) else sources
        result = get_nlm_node_bridge().create_notebook(
            name=name,
            sources=src_list,
            description=description,
            topics=[t.strip() for t in topics.split(",") if t.strip()],
        )
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def notebooklm_node_list_notebooks() -> str:
    """List all NotebookLM notebooks in the authenticated account.
    Returns JSON array of ``{id, title, source_count, url}`` objects.
    """
    try:
        from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
        result = get_nlm_node_bridge().list_notebooks()
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def notebooklm_node_generate_audio(notebook_id: str) -> str:
    """Generate a podcast-style audio overview of a NotebookLM notebook
    via the Node bridge. Returns JSON with ``status`` and ``progress``.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().generate_audio(notebook_id)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def notebooklm_node_generate_video(notebook_id: str, style: str = "cinematic") -> str:
    """Generate a video overview of a NotebookLM notebook via the Node bridge.
    Supported styles: cinematic, documentary, minimalist, energetic, calm,
    data_viz, narrative, academic, news, creative.
    Returns JSON with ``video_id`` and ``status``.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().generate_video(notebook_id, style)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def notebooklm_node_extract_tables(notebook_id: str, query: str = "") -> str:
    """Extract structured data tables from a NotebookLM notebook's sources.
    Optionally filter by ``query`` topic. Returns JSON with ``tables`` list,
    each table having ``headers`` and ``rows``.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().extract_tables(notebook_id, query)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def notebooklm_node_chat_history(notebook_id: str, limit: int = 20) -> str:
    """Get recent chat/Q&A history for a NotebookLM notebook.
    Returns JSON array of ``{question, answer, timestamp}`` objects.
    """
    try:
        from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
        result = get_nlm_node_bridge().get_chat_history(notebook_id, limit=limit)
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def notebooklm_node_health() -> str:
    """Get combined health status of both NLM backends: Node MCP bridge
    (Patchright) and batchexecute proxy. Returns JSON with auth state,
    available tools, proxy reachability, and Chrome profile status.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().health()
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def notebooklm_node_setup_auth() -> str:
    """Run first-time Google authentication for the Node MCP bridge.
    Opens Chrome visibly — log in once and the profile is saved permanently.
    All subsequent calls work in headless mode automatically.
    Only callable by copilot (admin operation).
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().setup_auth()
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def notebooklm_node_sync_nexus(notebook_id: str, questions: str) -> str:
    """Batch-ask questions against a NotebookLM notebook and automatically
    store every answer as a Q&A pair in Nexus. This is the primary method
    for distilling notebook knowledge into the Nexus knowledge base.

    ``questions`` must be a JSON array of strings.
    Returns JSON with ``stored`` count, ``errors``, and each Q&A pair.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        from engine.nexus.client import get_nexus_client

        q_list = json.loads(questions) if isinstance(questions, str) else questions
        if not isinstance(q_list, list):
            return json.dumps({"error": "questions must be a JSON array"})

        results = get_nlm_hybrid().ask_batch(notebook_id, q_list)
        client = get_nexus_client()

        stored = 0
        errors = 0
        pairs = []
        for q, r in zip(q_list, results):
            answer = r.get("answer", "") if isinstance(r, dict) else str(r)
            if answer and "error" not in r:
                try:
                    client.add_qa(q, answer, category="nlm-distilled")
                    stored += 1
                    pairs.append({"question": q, "answer": answer[:200]})
                except Exception:
                    errors += 1
            else:
                errors += 1

        return json.dumps({"stored": stored, "errors": errors, "pairs": pairs})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── Local Agent Bridge Tools ──────────────────────────────────────────────

@mcp.tool()
async def local_agent_get_tasks(model_size: str = "worker", limit: int = 10,
                                 tags: str = "") -> str:
    """Get pending tasks for a local agent by model size.

    model_size: 'router', 'mini', 'worker', or 'expert'.
    tags: optional comma-separated tag filter.
    Returns JSON list of task dicts sorted by priority.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    tasks = get_local_agent_bridge().get_ready_tasks(model_size=model_size, limit=limit,
                                                      tags=tag_list)
    return json.dumps({"tasks": tasks, "count": len(tasks)})


@mcp.tool()
async def local_agent_claim_task(task_id: str, agent_id: str) -> str:
    """Claim a task for execution by this agent.

    task_id: ID of the task to claim.
    agent_id: Unique identifier for this agent (e.g. 'worker-qwen-7b-1').
    Returns claimed task dict or error.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    result = get_local_agent_bridge().claim_task(task_id=task_id, agent_id=agent_id)
    return json.dumps(result)


@mcp.tool()
async def local_agent_task_context(task_id: str) -> str:
    """Get full execution context for a claimed task.

    Includes: task metadata, relevant Nexus knowledge, coding rules, and
    step-by-step execution guide. Inject this into the agent's system prompt.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    ctx = get_local_agent_bridge().get_task_context(task_id=task_id)
    return json.dumps(ctx)


@mcp.tool()
async def local_agent_complete_task(task_id: str, result: str,
                                     files_changed: str = "") -> str:
    """Mark a task as completed and store the result in Nexus.

    task_id: ID of the completed task.
    result: 1-2 sentence summary of what was accomplished.
    files_changed: optional comma-separated list of files modified.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    file_list = [f.strip() for f in files_changed.split(",") if f.strip()] if files_changed else []
    out = get_local_agent_bridge().complete_task(task_id=task_id, result=result,
                                                  files_changed=file_list)
    return json.dumps(out)


@mcp.tool()
async def local_agent_fail_task(task_id: str, reason: str, retry: bool = False) -> str:
    """Mark a task as failed.

    task_id: ID of the failed task.
    reason: Explanation of why it failed.
    retry: If True, reset to 'pending' so another agent can pick it up.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    out = get_local_agent_bridge().fail_task(task_id=task_id, reason=reason, retry=retry)
    return json.dumps(out)


@mcp.tool()
async def local_agent_manifest(model_size: str = "worker") -> str:
    """Get the system prompt manifest for a local agent of the specified size.

    Returns a formatted string ready to inject into an LLM system prompt.
    model_size: 'router', 'mini', 'worker', or 'expert'.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    return get_local_agent_bridge().get_agent_manifest(model_size=model_size)


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
    from engine.nexus.master_notebook_builder import MasterNotebookBuilder
    builder = MasterNotebookBuilder(dry_run=dry_run)
    result = builder.build(
        notebook_id=notebook_id or None,
        sources_only=sources_only,
        generators_only=generators_only,
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def master_notebook_status() -> str:
    """Get status of the master notebook build (what's been done, what's pending)."""
    from engine.nexus.master_notebook_builder import _load_state, DISTILLATION_QUESTIONS
    state = _load_state()
    nb_id = state.get("notebook_id", "not created yet")
    sources_done = len(state.get("sources_uploaded", []))
    gens_done = state.get("generators_done", [])
    qa_done = state.get("qa_done_index", 0)
    qa_total = len(DISTILLATION_QUESTIONS)
    lines = [
        "=== Master Notebook Status ===",
        f"Notebook ID   : {nb_id}",
        f"Last build    : {state.get('last_build', 'never')}",
        f"Sources done  : {sources_done}",
        f"Generators    : {', '.join(gens_done) or 'none yet'}",
        f"Q&A distilled : {qa_done}/{qa_total}",
    ]
    return "\n".join(lines)


@mcp.tool()
async def master_notebook_reset() -> str:
    """Reset master notebook build state (forces fresh creation and full re-upload).

    WARNING: This will delete the stored notebook ID. A new notebook will be
    created on the next build. Use this when you want a completely fresh start.
    """
    from engine.nexus.master_notebook_builder import _STATE_FILE
    try:
        if _STATE_FILE.exists():
            _STATE_FILE.unlink()
        return "Master notebook state reset. Next build will create a fresh notebook."
    except Exception as exc:
        return f"Reset failed: {exc}"


@mcp.tool()
async def master_notebook_list_sources() -> str:
    """List all sources that will be included in the master notebook.

    Shows all 13 code bundles + 19 SDK documentation URLs.
    """
    from engine.nexus.master_notebook_builder import SDK_URLS
    lines = ["=== Master Notebook Source Manifest ===\n", "TEXT BUNDLES (code + docs):"]
    text_bundles = [
        "CosySim Hardware & System Specification",
        "Engine Framework: Config, MCP, Scenes, Agents",
        "Engine Nexus: Knowledge Management System",
        "Engine LMStudio: LLM Inference Integration",
        "Engine MCP Servers: DevTools, NLM Hybrid, Bridges",
        "Engine Skills: @skill Decorator + All Builtin Packs",
        "Engine Services: TTS, Integrations, Assistant",
        "Scene Implementations: Top 8 Scenes",
        "Config Files, Governance Rules & Copilot Instructions",
        "Documentation: Architecture, Guides, Protocols",
        "Frontend JavaScript: All Scene + Shared JS",
        "Test Suite: Patterns and Conventions",
        "Dependencies: requirements.txt, package.json, pyproject.toml",
    ]
    for i, b in enumerate(text_bundles, 1):
        lines.append(f"  {i:2}. {b}")
    lines.append(f"\nSDK / API DOCUMENTATION URLs ({len(SDK_URLS)} sources):")
    for i, sdk in enumerate(SDK_URLS, 1):
        lines.append(f"  {i:2}. {sdk['label']} → {sdk['url']}")
    lines.append(f"\nTotal sources: {len(text_bundles) + len(SDK_URLS)}")
    return "\n".join(lines)


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
    """Submit a new fine-tuning job for a micro-model type.

    Args:
        model_type: qa_evaluator | conversation_analyzer | syntax_fixer | router_v2 | knowledge_synthesizer
        base_model: HuggingFace model ID or alias (qwen-270m, qwen-1.7b, llama-3b). Default: auto.
    """
    from training.finetune_orchestrator import get_finetune_orchestrator
    orch = get_finetune_orchestrator()
    kwargs: dict = {"model_type": model_type}
    if base_model:
        kwargs["base_model"] = base_model
    try:
        job = orch.submit(**kwargs)
        return json.dumps(job.to_dict(), indent=2)
    except FileNotFoundError as exc:
        return f"ERROR: {exc}\nRun finetune_build_dataset first."


@mcp.tool()
async def finetune_run_next() -> str:
    """Run the next pending fine-tuning job. Blocks until complete."""
    from training.finetune_orchestrator import get_finetune_orchestrator
    orch = get_finetune_orchestrator()
    job = orch.run_next()
    if job is None:
        return "No pending fine-tuning jobs."
    return json.dumps(job.to_dict(), indent=2)


@mcp.tool()
async def finetune_list_jobs(status: str = "") -> str:
    """List all fine-tuning jobs.

    Args:
        status: Filter by status (pending|running|done|failed). Empty = all.
    """
    from training.finetune_orchestrator import get_finetune_orchestrator
    orch = get_finetune_orchestrator()
    jobs = orch.list_jobs(status=status or None)
    lines = ["=== Fine-tune Jobs ===", f"Queue: {orch.queue_status()}", ""]
    for j in jobs[:20]:
        lines.append(
            f"[{j['status']}] {j['job_id']} {j['model_type']} ({j['base_model']}) "
            f"progress={j['progress']:.0%}"
        )
    return "\n".join(lines)


@mcp.tool()
async def finetune_build_dataset(model_type: str, count: int = 500) -> str:
    """Build training dataset for a micro-model type using NLM teacher.

    Args:
        model_type: Target model type.
        count: Number of examples to generate.
    """
    from training.micro_datasets import MicroDatasetManager
    mgr = MicroDatasetManager()
    stats = mgr.build(model_type, count=count)
    return json.dumps(stats.to_dict(), indent=2)


@mcp.tool()
async def finetune_dataset_status() -> str:
    """Show dataset sizes for all micro-model types."""
    from training.micro_datasets import MicroDatasetManager
    mgr = MicroDatasetManager()
    status = mgr.status()
    lines = ["=== Dataset Status ==="]
    for model_type, info in status.items():
        ready = "✓" if info["ready"] else "✗"
        lines.append(f"  {ready} {model_type}: train={info['train']} val={info['val']} test={info['test']}")
    return "\n".join(lines)


@mcp.tool()
async def model_registry_list(model_type: str = "") -> str:
    """List registered fine-tuned models.

    Args:
        model_type: Filter by type. Empty = all.
    """
    from training.model_registry import get_model_registry
    registry = get_model_registry()
    models = registry.list_models(model_type=model_type or None)
    lines = ["=== Model Registry ==="]
    for m in models:
        active = "★ ACTIVE" if m["active"] else "  "
        score = f"score={m['benchmark_score']:.3f}" if m["benchmark_score"] else "score=?"
        lines.append(f"  {active} [{m['model_id']}] {m['model_type']} {score} base={m['base_model']}")
    lines.append(f"\nSummary: {json.dumps(registry.summary(), indent=2)}")
    return "\n".join(lines)


@mcp.tool()
async def model_benchmark_run(model_type: str = "") -> str:
    """Run benchmarks on fine-tuned models.

    Args:
        model_type: Type to benchmark. Empty = run all.
    """
    from training.benchmark_runner import get_benchmark_runner
    runner = get_benchmark_runner()
    if model_type:
        result = runner.run(model_type)
        return result.summary()
    else:
        results = runner.run_all()
        return "\n".join(r.summary() for r in results)


@mcp.tool()
async def model_benchmark_leaderboard() -> str:
    """Show the best benchmark score per micro-model type."""
    from training.benchmark_runner import get_benchmark_runner
    board = get_benchmark_runner().get_leaderboard()
    lines = ["=== Model Leaderboard ==="]
    for model_type, info in board.items():
        score = f"{info['best_score']:.3f}" if info["best_score"] is not None else "no data"
        lines.append(f"  {model_type}: {score} (id={info['model_id']})")
    return "\n".join(lines)


@mcp.tool()
async def model_promote(model_id: str, model_type: str) -> str:
    """Manually promote a fine-tuned model as the active one for its type.

    Args:
        model_id: Registry model ID (8-char).
        model_type: Model type (qa_evaluator, router_v2, etc.).
    """
    from training.model_registry import get_model_registry
    registry = get_model_registry()
    registry.promote(model_type, model_id)
    return f"Promoted model {model_id} as active {model_type}."


@mcp.tool()
async def teacher_generate_dataset(model_type: str, count: int = 300) -> str:
    """Generate a training dataset via NLM teacher pipeline (Gemini 3.0).

    Args:
        model_type: Target micro-model type.
        count: Number of examples to generate.
    """
    from engine.nexus.teacher_pipeline import get_teacher_pipeline
    pipeline = get_teacher_pipeline()
    result = pipeline.generate_dataset(model_type, count=count)
    return json.dumps(result.to_dict(), indent=2)


@mcp.tool()
async def finetuned_router_status() -> str:
    """Show which fine-tuned models are currently active in the router."""
    from engine.lmstudio.finetuned_router import get_finetuned_router
    router = get_finetuned_router()
    active = router.get_active_models()
    lines = ["=== Fine-tuned Router ==="]
    if not active:
        lines.append("  No fine-tuned models loaded.")
        lines.append("  Run: finetuned_router_load_registry")
    else:
        for task_type, path in active.items():
            lines.append(f"  {task_type}: {path}")
    return "\n".join(lines)


@mcp.tool()
async def finetuned_router_load_registry() -> str:
    """Load all active fine-tuned models from the model registry into the router."""
    from engine.lmstudio.finetuned_router import get_finetuned_router
    router = get_finetuned_router()
    count = router.load_from_registry()
    return f"Loaded {count} fine-tuned models from registry."


@mcp.tool()
async def backup_run() -> str:
    """Trigger an immediate database backup."""
    from engine.nexus.backup_manager import get_backup_manager
    mgr = get_backup_manager()
    result = mgr.run_backup()
    return json.dumps(result.to_dict() if hasattr(result, "to_dict") else {"result": str(result)}, indent=2)


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
        lines.append(f"  {b.get('timestamp', '?')} | {b.get('size_mb', 0):.1f}MB | {b.get('targets', [])}")
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
