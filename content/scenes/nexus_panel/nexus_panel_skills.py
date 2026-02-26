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
    tags=["nexus", "knowledge", "qa"],
    category="SYSTEM",
    description="Ask the Librarian a question. Uses Nexus Q&A pipeline (cache, FTS, NLM).",
)
def librarian_ask(question: str, depth: str = "auto") -> str:
    """Smart Q&A through the Nexus pipeline."""
    client = _get_client()
    result = client.ask(question, depth=depth)
    answer = result.get("answer", "I don't have an answer for that.")
    source = result.get("source", "unknown")
    confidence = result.get("confidence", 0)
    return f"[Source: {source}, Confidence: {confidence:.0%}]\n{answer}"


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
