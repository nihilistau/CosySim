"""MCP tool domain: nexus.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── NEXUS TOOLS ────────────────────────────────────────────────────────


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
def nexus_store_prompt(name: str, content: str, category: str = "",
                       version: str = "") -> str:
    """Store or version a prompt template in Nexus."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        result = nx.store_prompt(name, content, category=category, version=version)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
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


@mcp_tool
def nexus_research(question: str) -> str:
    """Start a deep research session via NotebookLM."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        result = nx.research(question)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def nexus_converse(research_id: str, message: str) -> str:
    """Continue an existing research session with a follow-up."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        result = nx.converse(research_id, message)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def nexus_finish_research(research_id: str) -> str:
    """Close a research session and distill findings into Q&A pairs."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        result = nx.finish_research(research_id)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def nexus_import_youtube(url: str, category: str = "", tags: str = "") -> str:
    """Import a YouTube video transcript into Nexus."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        result = nx.import_youtube(url, category=category, tags=tag_list)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def nexus_log_session(project: str = "CosySim", repo: str = "",
                      branch: str = "") -> str:
    """Log a work session to Nexus for tracking."""
    try:
        nx = _get_nexus()
        if not nx:
            return json.dumps({"error": "Nexus unavailable"})
        result = nx.log_session(project=project, repo=repo, branch=branch)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
def nexus_router_stats() -> str:
    """Get NexusQueryRouter statistics: hit rates, cache performance, tokens saved."""
    try:
        from engine.nexus.query_router import get_query_router
        router = get_query_router()
        return json.dumps(router.stats.to_dict(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def nexus_quality_report() -> str:
    """Score all Nexus entries by freshness, quality, uniqueness, and
    completeness. Returns distribution, low-quality entries, duplicates,
    stale entries, and actionable recommendations."""
    try:
        from engine.nexus.self_maintenance import quality_report
        return json.dumps(quality_report(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.resource("nexus://status")
def resource_nexus_status() -> str:
    """Nexus knowledge system health and stats."""
    return nexus_status()
