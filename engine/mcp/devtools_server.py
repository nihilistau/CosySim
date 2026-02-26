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


# ── Resources ─────────────────────────────────────────────────────────

@mcp.resource("nexus://status")
def resource_nexus_status() -> str:
    """Nexus knowledge system health and stats."""
    return nexus_status()


# ── Entry point ───────────────────────────────────────────────────────

def run_server(mode: str = "stdio"):
    """Start the DevTools MCP server."""
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
