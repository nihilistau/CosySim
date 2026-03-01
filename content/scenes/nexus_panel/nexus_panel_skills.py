"""MCP skills for the Nexus Control Panel / Librarian agent."""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _get_panel():
    """Get the active NexusPanelScene instance."""
    from engine.scenes.base_scene import BaseScene
    return BaseScene.get_active_scene("nexus_panel")


def _get_client():
    """Get NexusClient."""
    from engine.nexus.client import get_nexus_client
    return get_nexus_client()


@skill(
    pack="nexus_panel",
    tags=["nexus", "knowledge", "search"],
    category="SYSTEM",
    description="Search the Nexus knowledge base for entries matching a query.",
)
def librarian_search(query: str, limit: int = 10) -> str:
    """Search Nexus knowledge base."""
    client = _get_client()
    results = client.search(query, limit=limit)
    if not results:
        return f"No results found for '{query}'."
    lines = [f"Found {len(results)} results for '{query}':"]
    for r in results:
        title = r.get("title", "Untitled")
        content = r.get("content", "")[:100]
        lines.append(f"  - {title}: {content}...")
    return "\n".join(lines)


@skill(
    pack="nexus_panel",
    tags=["nexus", "knowledge", "qa", "routing"],
    category="SYSTEM",
    description=(
        "Ask the Librarian a question. Uses smart routing: "
        "Nexus cache → FTS → NLM hybrid (when confidence < 0.35 or no cache hit). "
        "Routing decision and source are included in the response."
    ),
)
def librarian_ask(question: str, depth: str = "auto") -> str:
    """Smart Q&A with confidence-based NLM escalation."""
    client = _get_client()
    result = client.ask(question, depth=depth)
    answer = result.get("answer", "")
    source = result.get("source", "unknown")
    confidence = result.get("confidence", 0.0)

    # Escalate to NLM hybrid when confidence is low or no answer
    _NLM_THRESHOLD = 0.35
    if not answer or confidence < _NLM_THRESHOLD:
        try:
            hybrid = _get_hybrid()
            # Find the most relevant notebook (use first available)
            notebooks = _get_node_bridge().list_notebooks()
            nb_id = notebooks[0].get("notebook_id", "") if notebooks else ""
            if nb_id:
                nlm_result = hybrid.ask(nb_id, question)
                nlm_answer = nlm_result.get("answer", "")
                if nlm_answer:
                    # Store the NLM answer back in Nexus for future cache hits
                    try:
                        client.add_qa(question, nlm_answer, category="nlm-distilled")
                    except Exception:
                        pass
                    route_note = f"[Routed to NLM — Nexus confidence was {confidence:.0%}]"
                    return f"{route_note}\n[Source: nlm_hybrid]\n{nlm_answer}"
        except Exception as exc:
            logger.debug("NLM escalation failed: %s", exc)

    return f"[Source: {source}, Confidence: {confidence:.0%}]\n{answer or 'No answer found.'}"


@skill(
    pack="nexus_panel",
    tags=["nexus", "knowledge", "add"],
    category="SYSTEM",
    description="Store a new knowledge entry in Nexus.",
)
def librarian_store(title: str, content: str, content_type: str = "note",
                    category: str = "general") -> str:
    """Add a knowledge entry to Nexus."""
    client = _get_client()
    result = client.add_entry(title=title, content=content,
                              content_type=content_type, category=category)
    return f"Stored entry: '{title}' (type={content_type}, category={category})"


@skill(
    pack="nexus_panel",
    tags=["nexus", "maintenance", "health"],
    category="SYSTEM",
    description="Run Nexus maintenance: health check, dedup, compact, score, or full.",
)
def librarian_maintain(action: str = "health") -> str:
    """Run a Nexus maintenance action."""
    from engine.nexus.self_maintenance import (
        nexus_health_report,
        nexus_merge_duplicates,
        nexus_compact_sessions,
        nexus_score_entries,
        nexus_full_maintenance,
    )
    actions = {
        "health": nexus_health_report,
        "dedup": lambda: nexus_merge_duplicates(dry_run=True),
        "dedup-apply": lambda: nexus_merge_duplicates(dry_run=False),
        "compact": nexus_compact_sessions,
        "score": nexus_score_entries,
        "full": lambda: nexus_full_maintenance(dry_run=True),
        "full-apply": lambda: nexus_full_maintenance(dry_run=False),
    }
    if action not in actions:
        return f"Unknown action: {action}. Available: {', '.join(actions.keys())}"
    import json
    result = actions[action]()
    return json.dumps(result, indent=2, default=str)


@skill(
    pack="nexus_panel",
    tags=["nexus", "research"],
    category="SYSTEM",
    description="Start a deep research session via Nexus NLM integration.",
)
def librarian_research(question: str) -> str:
    """Start a research session."""
    client = _get_client()
    result = client.research(question)
    rid = result.get("research_id", "unknown")
    return f"Research session started: {rid}\nQuestion: {question}\nUse 'converse' to follow up."


@skill(
    pack="nexus_panel",
    tags=["nexus", "stats"],
    category="SYSTEM",
    description="Get Nexus system statistics: entries, Q&A pairs, sessions, health.",
)
def librarian_stats() -> str:
    """Get Nexus statistics."""
    client = _get_client()
    stats = client.stats()
    health = client.health()
    lines = ["Nexus Statistics:"]
    for key, val in stats.items():
        lines.append(f"  {key}: {val}")
    lines.append(f"\nHealth: {health}")
    return "\n".join(lines)


@skill(
    pack="nexus_panel",
    tags=["nexus", "routing", "stats", "librarian"],
    category="SYSTEM",
    description=(
        "Show routing statistics for the Librarian's smart Q&A routing. "
        "Includes how often Nexus cache, FTS, or NLM is used; tokens saved."
    ),
)
def librarian_route_stats() -> str:
    """Show Librarian routing statistics — where answers come from."""
    try:
        from engine.nexus.query_router import get_query_router
        router = get_query_router()
        stats = router.stats() if hasattr(router, "stats") else {}
        lines = ["Librarian Routing Statistics:"]
        if not stats:
            lines.append("  (No routing stats available yet.)")
        else:
            cache_hits = stats.get("cache_hits", 0)
            fts_hits = stats.get("fts_hits", 0)
            nlm_hits = stats.get("nlm_hits", 0)
            llm_hits = stats.get("llm_hits", 0)
            total = cache_hits + fts_hits + nlm_hits + llm_hits or 1
            tokens_saved = stats.get("tokens_saved", 0)
            lines.append(f"  Total queries : {total}")
            lines.append(f"  Cache hits    : {cache_hits} ({cache_hits*100//total}%)")
            lines.append(f"  FTS hits      : {fts_hits} ({fts_hits*100//total}%)")
            lines.append(f"  NLM hits      : {nlm_hits} ({nlm_hits*100//total}%)")
            lines.append(f"  LLM fallback  : {llm_hits} ({llm_hits*100//total}%)")
            lines.append(f"  Tokens saved  : {tokens_saved:,}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Could not load routing stats: {exc}"


# ── NLM Panel Skills ──────────────────────────────────────────────────────

def _get_hybrid():
    """Get NLM hybrid router."""
    from engine.mcp.nlm_hybrid import get_nlm_hybrid
    return get_nlm_hybrid()


def _get_node_bridge():
    """Get NLM node bridge."""
    from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
    return get_nlm_node_bridge()


@skill(
    pack="nexus_panel",
    tags=["nlm", "notebooks", "list"],
    category="SYSTEM",
    description="List all NotebookLM notebooks. Returns names, IDs, and source counts.",
)
def nlm_panel_list_notebooks() -> str:
    """List all NLM notebooks available."""
    try:
        notebooks = _get_node_bridge().list_notebooks()
        if not notebooks:
            return "No notebooks found. Use nlm_panel_setup_auth if NLM is not authenticated."
        lines = [f"Found {len(notebooks)} notebooks:"]
        for nb in notebooks:
            nb_id = nb.get("notebook_id", nb.get("id", "unknown"))
            name = nb.get("title", nb.get("name", "Untitled"))
            source_count = nb.get("source_count", "?")
            lines.append(f"  [{nb_id}] {name} ({source_count} sources)")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error listing notebooks: {exc}"


@skill(
    pack="nexus_panel",
    tags=["nlm", "distill", "qa"],
    category="SYSTEM",
    description=(
        "Distil a NLM notebook into Q&A pairs and store them in Nexus. "
        "topic: optional topic filter. count: number of pairs to generate (default 20)."
    ),
)
def nlm_panel_distill(notebook_id: str, topic: str = "", count: int = 20) -> str:
    """Distil a NLM notebook into Q&A pairs stored in Nexus."""
    try:
        from engine.nexus.knowledge_forge import get_knowledge_forge
        result = get_knowledge_forge().distill(notebook_id, topic=topic, n_pairs=count)
        qa_count = len(getattr(result, "qa_pairs", []))
        nexus_ids = getattr(result, "nexus_ids", [])
        return (
            f"Distilled {qa_count} Q&A pairs from notebook {notebook_id}.\n"
            f"Stored in Nexus: {len(nexus_ids)} entries.\n"
            f"Topic: {topic or '(all)'}"
        )
    except Exception as exc:
        return f"Distillation failed: {exc}"


@skill(
    pack="nexus_panel",
    tags=["nlm", "audio", "generate"],
    category="SYSTEM",
    description=(
        "Generate an audio overview for a NLM notebook. "
        "style: 'standard' (default) or 'deep_dive'."
    ),
)
def nlm_panel_audio(notebook_id: str, style: str = "standard") -> str:
    """Generate a NotebookLM audio overview."""
    try:
        result = _get_hybrid().generate_audio(notebook_id, style=style)
        if result.get("error"):
            return f"Audio generation failed: {result['error']}"
        status = result.get("status", "unknown")
        audio_url = result.get("audio_url", "")
        return (
            f"Audio overview generation: {status}\n"
            f"Style: {style}\n"
            f"URL: {audio_url or '(pending — check back shortly)'}"
        )
    except Exception as exc:
        return f"Audio generation failed: {exc}"


@skill(
    pack="nexus_panel",
    tags=["nlm", "bulk", "qa", "ask"],
    category="SYSTEM",
    description=(
        "Ask multiple questions to a NLM notebook in bulk and store answers in Nexus. "
        "questions: newline-separated list of questions. Stores Q&A pairs automatically."
    ),
)
def nlm_panel_bulk_ask(notebook_id: str, questions: str, store_to_nexus: bool = True) -> str:
    """Bulk-ask questions to a NLM notebook, optionally storing answers in Nexus."""
    q_list = [q.strip() for q in questions.strip().splitlines() if q.strip()]
    if not q_list:
        return "No questions provided."
    try:
        results = _get_hybrid().ask_batch(notebook_id, q_list)
        stored = 0
        lines = [f"Answers for {len(q_list)} questions from notebook {notebook_id}:\n"]
        for q, r in zip(q_list, results):
            answer = r.get("answer", "(no answer)") if isinstance(r, dict) else str(r)
            lines.append(f"Q: {q}\nA: {answer[:300]}\n")
            if store_to_nexus and answer and "error" not in answer.lower()[:20]:
                try:
                    _get_client().add_qa(q, answer, category="nlm-distilled")
                    stored += 1
                except Exception:
                    pass
        if store_to_nexus:
            lines.append(f"\n{stored}/{len(q_list)} answers stored in Nexus.")
        return "\n".join(lines)
    except Exception as exc:
        return f"Bulk ask failed: {exc}"


@skill(
    pack="nexus_panel",
    tags=["nlm", "news", "digest"],
    category="SYSTEM",
    description=(
        "Trigger the news NLM distillation pipeline manually. "
        "Reads today's news from Nexus, uploads to NLM, extracts insights."
    ),
)
def nlm_panel_news_digest(max_articles: int = 20) -> str:
    """Manually trigger news NLM distillation for today's articles."""
    try:
        from engine.nexus.news_nlm_pipeline import get_news_nlm_pipeline
        result = get_news_nlm_pipeline().run(max_articles=max_articles)
        if result.get("error"):
            return f"News distillation error: {result['error']}"
        return (
            f"News NLM distillation complete.\n"
            f"Notebook: {result.get('notebook_id', 'N/A')}\n"
            f"Uploaded: {result.get('uploaded', False)}\n"
            f"Q&A pairs generated: {result.get('qa_count', 0)}\n"
            f"Stored in Nexus: {result.get('stored', 0)}"
        )
    except Exception as exc:
        return f"News distillation failed: {exc}"


@skill(
    pack="nexus_panel",
    tags=["nlm", "auth", "setup"],
    category="SYSTEM",
    description=(
        "Set up or refresh NLM authentication. "
        "Opens browser for Google sign-in if cookie session is stale."
    ),
)
def nlm_panel_setup_auth() -> str:
    """Set up NLM authentication."""
    try:
        result = _get_hybrid().setup_auth()
        if result.get("error"):
            return f"Auth setup failed: {result['error']}"
        return f"NLM auth setup: {result.get('status', 'completed')}\n{result.get('message', '')}"
    except Exception as exc:
        return f"Auth setup failed: {exc}"
