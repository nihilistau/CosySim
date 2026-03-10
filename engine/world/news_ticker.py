"""News ticker — formats and serves headlines for the scene ticker crawl.

Pulls articles from WorldNewsGenerator, formats them for display in the
bottom-of-screen news crawl, handles breaking news interrupts, and
exposes a Flask blueprint for ticker API endpoints.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)


@dataclass
class TickerItem:
    """A single ticker entry ready for display."""

    article_id: str = ""
    text: str = ""
    category: str = ""
    severity: int = 1
    is_breaking: bool = False
    timestamp: float = field(default_factory=time.time)
    display_duration_ms: int = 8000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "article_id": self.article_id,
            "text": self.text,
            "category": self.category,
            "severity": self.severity,
            "is_breaking": self.is_breaking,
            "timestamp": self.timestamp,
            "display_duration_ms": self.display_duration_ms,
        }


_SEVERITY_PREFIX = {
    1: "",
    2: "◐ ",
    3: "● ",
    4: "◆ ALERT: ",
    5: "⚡ BREAKING: ",
}

_CATEGORY_TAGS = {
    "crime": "[CRIME]",
    "economy": "[ECON]",
    "faction": "[FACTION]",
    "tech": "[TECH]",
    "social": "[SOCIAL]",
    "breaking": "[BREAKING]",
    "sports": "[SPORTS]",
    "underworld": "[UNDERWORLD]",
}


class NewsTicker:
    """Formats and serves news headlines for the scene ticker crawl.

    Pulls from WorldNewsGenerator on demand, formats headlines with
    severity indicators and category tags, and handles breaking news
    prioritization.
    """

    DEFAULT_TICKER_COUNT = 8
    BREAKING_DURATION_MS = 12000
    NORMAL_DURATION_MS = 8000

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._muted_categories: set = set()
        self._stats = {
            "ticker_requests": 0,
            "breaking_alerts": 0,
        }

    def get_ticker_items(
        self, count: int = DEFAULT_TICKER_COUNT, category: Optional[str] = None
    ) -> List[TickerItem]:
        """Get formatted ticker items from the news generator.

        Args:
            count: Number of ticker items to return.
            category: Optional category filter.

        Returns:
            List of TickerItem ready for frontend display.
        """
        from engine.world.news_generator import get_news_generator

        gen = get_news_generator()

        with self._lock:
            self._stats["ticker_requests"] += 1
            muted = set(self._muted_categories)

        headlines = gen.get_headlines(limit=count * 2, category=category)

        items: List[TickerItem] = []
        for h in headlines:
            cat = h.get("category", "")
            if cat in muted:
                continue

            severity = h.get("severity", 1)
            is_breaking = severity >= 4
            prefix = _SEVERITY_PREFIX.get(severity, "")
            tag = _CATEGORY_TAGS.get(cat, "")
            text = f"{prefix}{tag} {h['headline']}"

            item = TickerItem(
                article_id=h.get("article_id", ""),
                text=text.strip(),
                category=cat,
                severity=severity,
                is_breaking=is_breaking,
                timestamp=h.get("timestamp", time.time()),
                display_duration_ms=(
                    self.BREAKING_DURATION_MS if is_breaking else self.NORMAL_DURATION_MS
                ),
            )
            items.append(item)

            if len(items) >= count:
                break

        # Breaking news always goes first
        items.sort(key=lambda x: (-x.severity, -x.timestamp))

        if items and items[0].is_breaking:
            with self._lock:
                self._stats["breaking_alerts"] += 1

        return items

    def get_ticker_strings(
        self, count: int = DEFAULT_TICKER_COUNT
    ) -> List[str]:
        """Get simple string list for basic ticker display."""
        items = self.get_ticker_items(count)
        return [item.text for item in items]

    def mute_category(self, category: str) -> None:
        """Mute a news category from ticker display."""
        with self._lock:
            self._muted_categories.add(category)

    def unmute_category(self, category: str) -> None:
        """Unmute a news category."""
        with self._lock:
            self._muted_categories.discard(category)

    def get_muted(self) -> List[str]:
        """Return list of muted categories."""
        with self._lock:
            return list(self._muted_categories)

    def stats(self) -> Dict[str, Any]:
        """Return ticker statistics."""
        with self._lock:
            return dict(self._stats)

    def reset(self) -> None:
        """Reset ticker state."""
        with self._lock:
            self._muted_categories.clear()
            self._stats = {
                "ticker_requests": 0,
                "breaking_alerts": 0,
            }


# ──── Singleton ────

_instance: Optional[NewsTicker] = None
_instance_lock = threading.Lock()


def get_news_ticker() -> NewsTicker:
    """Get or create the singleton NewsTicker."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = NewsTicker()
    return _instance


def reset_news_ticker() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


# ──── Flask Blueprint ────


def create_news_ticker_blueprint() -> Blueprint:
    """Create Flask blueprint for news ticker API endpoints."""
    bp = Blueprint("news_ticker", __name__)

    @bp.route("/api/news/ticker")
    def ticker_feed():
        """Get formatted ticker items for the news crawl."""
        count = request.args.get("count", 8, type=int)
        category = request.args.get("category", None)
        ticker = get_news_ticker()
        items = ticker.get_ticker_items(count, category)
        return jsonify({
            "items": [item.to_dict() for item in items],
            "count": len(items),
        })

    @bp.route("/api/news/headlines")
    def headlines():
        """Get latest headlines."""
        from engine.world.news_generator import get_news_generator

        gen = get_news_generator()
        limit = request.args.get("limit", 10, type=int)
        category = request.args.get("category", None)
        return jsonify({
            "headlines": gen.get_headlines(limit, category),
        })

    @bp.route("/api/news/article/<article_id>")
    def article_detail(article_id):
        """Get full article by ID."""
        from engine.world.news_generator import get_news_generator

        gen = get_news_generator()
        article = gen.get_article(article_id)
        if article is None:
            return jsonify({"error": "Article not found"}), 404
        return jsonify(article)

    @bp.route("/api/news/breaking")
    def breaking_news():
        """Get breaking news only."""
        from engine.world.news_generator import get_news_generator

        gen = get_news_generator()
        limit = request.args.get("limit", 5, type=int)
        return jsonify({
            "articles": gen.get_breaking_news(limit),
        })

    @bp.route("/api/news/search")
    def search_news():
        """Search articles by keyword."""
        from engine.world.news_generator import get_news_generator

        gen = get_news_generator()
        query = request.args.get("q", "")
        limit = request.args.get("limit", 10, type=int)
        if not query:
            return jsonify({"error": "Missing query parameter 'q'"}), 400
        return jsonify({
            "results": gen.search_articles(query, limit),
            "query": query,
        })

    @bp.route("/api/news/digest")
    def editorial_digest():
        """Get editorial digest for NPC awareness."""
        from engine.world.news_generator import get_news_generator

        gen = get_news_generator()
        count = request.args.get("count", 5, type=int)
        return jsonify({
            "digest": gen.get_editorial_digest(count),
        })

    @bp.route("/api/news/stats")
    def news_stats():
        """Get news generator and ticker stats."""
        from engine.world.news_generator import get_news_generator

        gen = get_news_generator()
        ticker = get_news_ticker()
        return jsonify({
            "generator": gen.stats(),
            "ticker": ticker.stats(),
        })

    return bp
