from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from engine.mcp.decorators import mcp_tool, ToolExecutionError

# We will define response models where appropriate to enforce structure,
# or return dicts that are serialized properly by the decorator.


class NexusSearchResponse(BaseModel):
    results: List[Any]
    count: int


@mcp_tool
def nexus_search_impl(query: str, limit: int, nexus_getter: Any) -> NexusSearchResponse:
    """Search the Nexus knowledge base for entries matching a query."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    results = nx.search(query, limit=limit)
    return NexusSearchResponse(results=results, count=len(results))


@mcp_tool
def nexus_ask_impl(
    question: str, depth: str, category: str, nexus_getter: Any
) -> Dict[str, Any]:
    """Smart Q&A against Nexus."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    # nx.ask usually returns a dict or string; we assume string or dict here.
    answer = nx.ask(question, depth=depth, category=category)
    if isinstance(answer, dict):
        return answer
    return {"answer": answer}


@mcp_tool
def nexus_add_impl(
    title: str,
    content: str,
    content_type: str,
    category: str,
    tags: str,
    nexus_getter: Any,
) -> Dict[str, Any]:
    """Store a knowledge entry in Nexus."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    entry_id = nx.add_entry(
        title, content, content_type=content_type, category=category, tags=tag_list
    )
    if entry_id:
        return {"ok": True, "id": entry_id}
    raise ToolExecutionError("Failed to add entry")


@mcp_tool
def nexus_add_qa_impl(
    question: str, answer: str, category: str, tags: str, nexus_getter: Any
) -> Dict[str, Any]:
    """Store a question-answer pair in Nexus."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    qa_id = nx.add_qa(question, answer, category=category, tags=tag_list)
    if qa_id:
        return {"ok": True, "id": qa_id}
    raise ToolExecutionError("Failed to add Q&A")


@mcp_tool
def nexus_get_rules_impl(
    scope: str, rule_type: str, nexus_getter: Any
) -> Dict[str, Any]:
    """Get active governance rules from Nexus."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    rules = nx.get_rules(scope=scope, rule_type=rule_type)
    return {"rules": rules, "count": len(rules)}


@mcp_tool
def nexus_store_prompt_impl(
    name: str, content: str, category: str, version: str, nexus_getter: Any
) -> Dict[str, Any]:
    """Store or version a prompt template in Nexus."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    result = nx.store_prompt(name, content, category=category, version=version)
    if isinstance(result, dict):
        return result
    return {"status": "ok", "result": result}


@mcp_tool
def nexus_get_prompts_impl(
    category: str, name: str, nexus_getter: Any
) -> Dict[str, Any]:
    """Retrieve stored prompts from Nexus."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    prompts = nx.get_prompts(category=category, name=name)
    return {"prompts": prompts, "count": len(prompts)}


@mcp_tool
def nexus_research_impl(question: str, nexus_getter: Any) -> Dict[str, Any]:
    """Start a deep research session via NotebookLM."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    result = nx.research(question)
    if isinstance(result, dict):
        return result
    return {"status": "ok", "result": result}


@mcp_tool
def nexus_converse_impl(
    research_id: str, message: str, nexus_getter: Any
) -> Dict[str, Any]:
    """Continue an existing research session with a follow-up."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    result = nx.converse(research_id, message)
    if isinstance(result, dict):
        return result
    return {"status": "ok", "result": result}


@mcp_tool
def nexus_finish_research_impl(research_id: str, nexus_getter: Any) -> Dict[str, Any]:
    """Close a research session and distill findings into Q&A pairs."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    result = nx.finish_research(research_id)
    if isinstance(result, dict):
        return result
    return {"status": "ok", "result": result}


@mcp_tool
def nexus_import_youtube_impl(
    url: str, category: str, tags: str, nexus_getter: Any
) -> Dict[str, Any]:
    """Import a YouTube video transcript into Nexus."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    result = nx.import_youtube(url, category=category, tags=tag_list)
    if isinstance(result, dict):
        return result
    return {"status": "ok", "result": result}


@mcp_tool
def nexus_log_session_impl(
    project: str, repo: str, branch: str, nexus_getter: Any
) -> Dict[str, Any]:
    """Log a work session to Nexus for tracking."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    result = nx.log_session(project=project, repo=repo, branch=branch)
    if isinstance(result, dict):
        return result
    return {"status": "ok", "result": result}


@mcp_tool
def nexus_status_impl(nexus_getter: Any) -> Dict[str, Any]:
    """Check Nexus health and get basic stats."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    status = nx.status()
    if isinstance(status, dict):
        return status
    return {"status": status}


@mcp_tool
def nexus_list_plugins_impl(scope: str, nexus_getter: Any) -> Dict[str, Any]:
    """List available Nexus plugins."""
    nx = nexus_getter()
    if not nx:
        raise ToolExecutionError("Nexus unavailable")
    plugins = nx.list_plugins(scope=scope)
    return {"plugins": plugins, "count": len(plugins)}


@mcp_tool
def nexus_remember_impl(
    content: str, agent_id: str, memory_type: str, importance: float
) -> Dict[str, Any]:
    """Store a memory in Nexus for an agent or Copilot."""
    try:
        from engine.nexus.nexus_memory import NexusMemory

        namespace = "copilot" if agent_id == "copilot" else "agent"
        mem = NexusMemory(namespace=namespace, agent_id=agent_id)
        entry_id = mem.remember(content, importance=importance, memory_type=memory_type)
        return {"status": "ok", "entry_id": entry_id, "agent": agent_id}
    except ImportError:
        raise ToolExecutionError("NexusMemory module not available.")


@mcp_tool
def nexus_recall_impl(query: str, agent_id: str, limit: int) -> Dict[str, Any]:
    """Recall memories from Nexus for an agent or Copilot."""
    try:
        from engine.nexus.nexus_memory import NexusMemory

        namespace = "copilot" if agent_id == "copilot" else "agent"
        mem = NexusMemory(namespace=namespace, agent_id=agent_id)
        memories = mem.recall(query, top_k=limit)
        return {"status": "ok", "memories": memories, "count": len(memories)}
    except ImportError:
        raise ToolExecutionError("NexusMemory module not available.")


@mcp_tool
def nexus_memory_context_impl(agent_id: str, max_tokens: int) -> Dict[str, Any]:
    """Get a compact memory context window for an agent."""
    try:
        from engine.nexus.nexus_memory import NexusMemory

        namespace = "copilot" if agent_id == "copilot" else "agent"
        mem = NexusMemory(namespace=namespace, agent_id=agent_id)
        context = mem.get_context_window(max_chars=max_tokens)
        return {"status": "ok", "context": context, "agent": agent_id}
    except ImportError:
        raise ToolExecutionError("NexusMemory module not available.")


@mcp_tool
def nexus_distill_impl(action: str) -> Dict[str, Any]:
    """Distill raw session data into reusable knowledge."""
    try:
        from engine.nexus.nexus_distiller import (
            NexusDistiller,
            QADeduplicator,
            SkillUsageDistiller,
            PromptEvolutionDistiller,
            run_all_distillers,
        )
    except ImportError:
        raise ToolExecutionError("Nexus distiller modules not available.")

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
        raise ToolExecutionError(
            f"Unknown action '{action}'. Use: {sorted(dispatch.keys())}"
        )

    result = dispatch[action]()
    if isinstance(result, str):
        return {"result": result}
    if isinstance(result, dict):
        return result
    return {"result": str(result)}


@mcp_tool
def nexus_export_session_impl() -> Dict[str, Any]:
    """Export current Copilot session history to Nexus."""
    try:
        from engine.nexus.nexus_session_logger import (
            _find_session_id,
            _get_session_history,
            _build_conversation_log,
            _now,
        )
        import requests as req
    except ImportError:
        raise ToolExecutionError("Session logger or requests module not available.")

    session_id = _find_session_id()
    if not session_id:
        raise ToolExecutionError("No active session found")

    history = _get_session_history(session_id)
    if not history:
        raise ToolExecutionError("Could not retrieve session history")

    stored = 0
    conv = _build_conversation_log(history)

    if conv and len(conv) > 100:
        if len(conv) > 50000:
            conv = conv[:50000] + "\n\n[TRUNCATED]"

        try:
            r = req.post(
                "http://127.0.0.1:8700/api/entries",
                json={
                    "title": f"Conversation log — {_now()} ({len(history.get('turns', []))} turns)",
                    "content": conv,
                    "content_type": "history",
                    "category": "sessions",
                    "tags": [
                        "session",
                        "copilot",
                        "conversation-log",
                        f"turns:{len(history.get('turns', []))}",
                    ],
                },
                timeout=10,
            )
            if r.ok:
                stored += 1
        except Exception:
            pass  # Ignore request failures

    for cp in history.get("checkpoints", []):
        if cp.get("work_done"):
            try:
                r = req.post(
                    "http://127.0.0.1:8700/api/entries",
                    json={
                        "title": f"Checkpoint {cp.get('number', 'X')}: {cp.get('title', '')}",
                        "content": f"Overview: {cp.get('overview', '')}\n\nWork: {cp.get('work_done', '')}",
                        "content_type": "history",
                        "category": "sessions",
                        "tags": ["session", "copilot", "checkpoint"],
                    },
                    timeout=10,
                )
                if r.ok:
                    stored += 1
            except Exception:
                pass

    return {
        "status": "ok",
        "session_id": session_id,
        "turns": len(history.get("turns", [])),
        "checkpoints": len(history.get("checkpoints", [])),
        "files": len(history.get("files", [])),
        "entries_stored": stored,
    }


@mcp_tool
def nexus_maintain_impl(action: str) -> Dict[str, Any]:
    """Run Nexus self-maintenance tasks."""
    try:
        from engine.nexus.self_maintenance import (
            nexus_health_report,
            nexus_merge_duplicates,
            nexus_compact_sessions,
            nexus_score_entries,
            nexus_full_maintenance,
        )
    except ImportError:
        raise ToolExecutionError("Self maintenance module not available.")

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
        raise ToolExecutionError(
            f"Unknown action: {action}. Available: {sorted(dispatch.keys())}"
        )

    result = dispatch[action]()
    if isinstance(result, dict):
        return result
    return {"result": str(result)}


@mcp_tool
def nexus_smart_query_impl(
    question: str, min_confidence: float, use_llm: bool, category: str
) -> Dict[str, Any]:
    """Route a query through the Nexus-first pipeline."""
    try:
        from engine.nexus.query_router import get_query_router

        router = get_query_router()
        result = router.query(
            question,
            min_confidence=min_confidence,
            use_llm=use_llm,
            category=category,
            source_hint="copilot",
        )
        return result.to_dict()
    except ImportError:
        raise ToolExecutionError("Query router not available.")


@mcp_tool
def nexus_router_stats_impl() -> Dict[str, Any]:
    """Get NexusQueryRouter statistics."""
    try:
        from engine.nexus.query_router import get_query_router

        router = get_query_router()
        return router.stats.to_dict()
    except ImportError:
        raise ToolExecutionError("Query router not available.")


@mcp_tool
def nexus_quality_report_impl() -> Dict[str, Any]:
    """Score all Nexus entries by freshness, quality, uniqueness, and completeness."""
    try:
        from engine.nexus.self_maintenance import quality_report

        result = quality_report()
        if isinstance(result, dict):
            return result
        return {"report": str(result)}
    except ImportError:
        raise ToolExecutionError("Quality report not available.")
