"""News & intelligence skills for agent access."""
from __future__ import annotations
import logging
from typing import Optional

from engine.nexus.client import get_nexus_client
from engine.nexus.news.news_pipeline import get_news_pipeline
from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="news",
    description="Fetch latest news headlines for a category from Nexus",
    category="SYSTEM",
    tags=["news", "nexus", "information"],
)
def fetch_news(category: str = "ai_research", limit: int = 5) -> str:
    """Get latest news headlines for a category.

    Args:
        category: News category (ai_research, tech, world, science)
        limit: Maximum headlines to return

    Returns:
        Formatted news digest string
    """
    return get_news_pipeline().get_latest_digest(category, limit=limit)


@skill(
    pack="news",
    description="Search news Q&A in Nexus by keyword query",
    category="SYSTEM",
    tags=["news", "search", "nexus"],
)
def search_news(query: str, category: str = "", days_back: int = 7) -> str:
    """Search news knowledge in Nexus.

    Args:
        query: Search terms (e.g., "open source LLM", "climate change")
        category: Optional category filter (ai_research, tech, world, science)
        days_back: How many days back to search

    Returns:
        Formatted search results
    """
    try:
        client = get_nexus_client()
        search_query = f"{query} news"
        results = client.search(search_query, category="news", limit=5)
        if not results:
            return f"No news found for query: {query}"
        lines = [f"## News: '{query}'\n"]
        for r in results[:5]:
            lines.append(f"**Q:** {r.get('title', 'Unknown')}\n{r.get('content', '')[:300]}\n")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("search_news error: %s", e)
        return f"Error searching news: {e}"


@skill(
    pack="news",
    description="Trigger a news fetch cycle for all categories",
    category="SYSTEM",
    tags=["news", "fetch", "pipeline"],
    cost=2.0,
)
def run_news_fetch(category: Optional[str] = None) -> str:
    """Run a news fetch cycle.

    Args:
        category: Optional single category to fetch (default: all)

    Returns:
        Summary of items fetched and stored
    """
    pipeline = get_news_pipeline()

    if category:
        items = pipeline.fetch_category(category)
        stored = pipeline.store_items_to_nexus(items)
        return f"Fetched {len(items)} items for {category}, stored {stored} to Nexus"
    else:
        report = pipeline.run_fetch_cycle()
        return (
            f"News fetch complete: {report['total_items']} items across "
            f"{len(report['categories'])} categories, {report['total_stored']} stored to Nexus"
        )


@skill(
    pack="news",
    description="Get a 200-word news insight for a topic, sourced from the NLM-distilled Nexus Q&A cache",
    category="SYSTEM",
    tags=["news", "insight", "nexus", "nlm"],
)
def news_insight(topic: str) -> str:
    """Return a concise 200-word news digest for a topic.

    Checks the Nexus Q&A cache first for an instant answer. Falls back to a
    Nexus full-text search synthesis, then generates a summary from stored
    news articles if still nothing found.

    Args:
        topic: The news topic or question (e.g., "AI regulation", "neon city faction war")

    Returns:
        200-word news insight string, or a fallback message if nothing found.
    """
    try:
        client = get_nexus_client()

        # Tier 1 — Q&A cache hit
        qa_result = client.ask(topic)
        if isinstance(qa_result, dict):
            answer = qa_result.get("answer", "")
            source = qa_result.get("source", "unknown")
        else:
            answer = str(qa_result) if qa_result else ""
            source = "nexus"

        if answer and len(answer) > 40:
            words = answer.split()[:200]
            digest = " ".join(words)
            logger.debug("news_insight cache hit (%s): %d chars", source, len(digest))
            return f"[NEWS INSIGHT — {topic.upper()}]\n\n{digest}"

        # Tier 2 — FTS search synthesis
        results = client.search(f"{topic} news", category="news", limit=5)
        if results:
            lines = []
            for r in results[:3]:
                snippet = r.get("content", "")[:300].strip()
                if snippet:
                    lines.append(snippet)
            if lines:
                combined = " ".join(lines)
                words = combined.split()[:200]
                digest = " ".join(words)
                return f"[NEWS INSIGHT — {topic.upper()}]\n\n{digest}"

        return f"[NEWS INSIGHT — {topic.upper()}]\n\nNo recent intelligence found. Run news-fetch to populate."

    except Exception as exc:
        logger.warning("news_insight error: %s", exc)
        return f"[NEWS INSIGHT — {topic.upper()}]\n\nIntel unavailable: {exc}"
