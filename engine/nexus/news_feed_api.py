"""
News Feed API — REST endpoints for curated news from Nexus.

Provides agents and users with access to curated, NLM-distilled news
intelligence stored in Nexus.  Runs as a Flask blueprint that can be
registered on any CosySim scene or standalone.

Endpoints:
    GET /api/news/latest     — Latest curated news articles
    GET /api/news/digest     — Daily digest summary
    GET /api/news/search     — Search news by keyword
    GET /api/news/sources    — List configured news sources
    GET /api/news/stats      — News pipeline statistics

Each endpoint returns JSON.  All data comes from the Nexus knowledge
base — this API is read-only.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def create_news_blueprint():
    """Create and return the news feed Flask blueprint.

    Returns:
        Flask Blueprint with news endpoints, or None if Flask unavailable.
    """
    try:
        from flask import Blueprint, jsonify, request
    except ImportError:
        logger.warning("Flask not installed — news feed API unavailable")
        return None

    news_bp = Blueprint("news_feed", __name__, url_prefix="/api/news")

    @news_bp.route("/latest", methods=["GET"])
    def latest():
        """Return the latest curated news articles from Nexus."""
        limit = request.args.get("limit", 20, type=int)
        category = request.args.get("category", "")

        articles = _fetch_news_from_nexus(limit=limit, category=category)
        return jsonify({
            "count": len(articles),
            "articles": articles,
        })

    @news_bp.route("/digest", methods=["GET"])
    def digest():
        """Return the latest daily digest."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            results = client.search("Daily News Digest", limit=1)
            if results:
                return jsonify({
                    "digest": results[0].get("content", ""),
                    "title": results[0].get("title", ""),
                    "created_at": str(results[0].get("created_at", "")),
                })
            return jsonify({"digest": "No digest available yet."})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @news_bp.route("/search", methods=["GET"])
    def search():
        """Search news articles by keyword."""
        query = request.args.get("q", "")
        limit = request.args.get("limit", 20, type=int)

        if not query:
            return jsonify({"error": "Missing 'q' parameter"}), 400

        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            results = client.search(f"news {query}", limit=limit)
            articles = [
                {
                    "title": r.get("title", ""),
                    "content": str(r.get("content", ""))[:500],
                    "category": r.get("category", ""),
                    "tags": r.get("tags", []),
                    "created_at": str(r.get("created_at", "")),
                }
                for r in (results or [])
            ]
            return jsonify({"count": len(articles), "query": query, "articles": articles})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @news_bp.route("/sources", methods=["GET"])
    def sources():
        """List configured news sources."""
        try:
            from engine.nexus.news_sources import get_news_registry
            registry = get_news_registry()
            source_list = registry.list_sources()
            return jsonify({"count": len(source_list), "sources": source_list})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @news_bp.route("/stats", methods=["GET"])
    def stats():
        """Return news pipeline statistics."""
        try:
            from engine.nexus.news_sources import get_news_registry
            registry = get_news_registry()
            return jsonify(registry.stats())
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    return news_bp


def _fetch_news_from_nexus(
    limit: int = 20,
    category: str = "",
) -> List[Dict[str, Any]]:
    """Fetch news entries from Nexus.

    Args:
        limit: Maximum number of articles to return.
        category: Optional category filter.

    Returns:
        List of article dicts.
    """
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()

        query = "news"
        if category:
            query = f"news {category}"

        results = client.search(query, limit=limit)
        if not results:
            return []

        return [
            {
                "title": r.get("title", ""),
                "content": str(r.get("content", ""))[:500],
                "category": r.get("category", ""),
                "tags": r.get("tags", []),
                "created_at": str(r.get("created_at", "")),
            }
            for r in results
        ]
    except Exception as exc:
        logger.warning("Failed to fetch news: %s", exc)
        return []
