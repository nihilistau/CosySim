"""MCP tool domain: news.

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

# ──── NEWS TOOLS ─────────────────────────────────────────────────────────


@mcp_tool
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


@mcp_tool
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


@mcp_tool
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


@mcp_tool
def news_sources() -> str:
    """List all configured news sources with fetch stats and error rates."""
    try:
        from engine.nexus.news_sources import get_news_registry
        return json.dumps(get_news_registry().stats(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
