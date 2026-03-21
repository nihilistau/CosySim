"""Nexus News Feed — queryable, filterable, personalized news feed.

Surfaces news articles as a Nexus-native feed with scoring, trend
integration, personalization, and daily digest generation.

Usage::

    from engine.nexus.news.nexus_feed import NexusFeed

    feed   = NexusFeed()
    items  = feed.get_feed(category="ai_ml", limit=10)
    digest = feed.get_daily_digest()
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from engine.nexus.news.article_scorer import get_article_scorer
from engine.nexus.news.trend_detector import get_trend_detector

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_DB_PATH = Path("data/news_profile.db")


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class FeedItem:
    """A single item in the news feed.

    Attributes:
        article_id: Unique identifier for the article.
        title: Article headline.
        summary: Short article summary.
        url: Source URL.
        source: Source name/domain.
        category: News category.
        published_at: Unix timestamp of publication.
        quality_score: ArticleScorer quality score 0.0–1.0.
        trend_score: Trend velocity for this article's topic.
        nexus_entry_id: Nexus entry ID if distilled, else empty.
        is_distilled: Whether the article has been NLM-distilled.
        tags: List of descriptive tags.
    """

    article_id: str = ""
    title: str = ""
    summary: str = ""
    url: str = ""
    source: str = ""
    category: str = ""
    published_at: float = 0.0
    quality_score: float = 0.0
    trend_score: float = 0.0
    nexus_entry_id: str = ""
    is_distilled: bool = False
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """Convert to a plain dict for JSON serialisation.

        Returns:
            Dict representation.
        """
        return asdict(self)


class NexusFeed:
    """Nexus-native news feed — queryable, filterable, personalized.

    Integrates with ArticleScorer, TrendDetector, and the Nexus client.
    Gracefully degrades if Nexus is unreachable.

    Args:
        db_path: Override for the profile/interaction SQLite database.
        scorer: Optional ArticleScorer (defaults to singleton).
        trend_detector: Optional TrendDetector (defaults to singleton).
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        scorer=None,
        trend_detector=None,
    ) -> None:
        self._db_path = db_path or _DB_PATH
        self._scorer = scorer or get_article_scorer()
        self._trends = trend_detector or get_trend_detector()
        self._lock = threading.Lock()
        self._ensure_db()

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _ensure_db(self) -> None:
        """Create the feed interaction and profile database schema."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS article_interactions (
                        interaction_id TEXT PRIMARY KEY,
                        article_id     TEXT NOT NULL,
                        url            TEXT,
                        title          TEXT,
                        category       TEXT,
                        action         TEXT NOT NULL,  -- 'read' | 'useful' | 'not_useful'
                        recorded_at    REAL NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS interest_profile (
                        key   TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ai_article ON article_interactions(article_id)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ai_action ON article_interactions(action)"
                )
                conn.commit()
        except Exception as exc:
            logger.warning("NexusFeed DB init error: %s", exc)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ── Nexus helpers ─────────────────────────────────────────────────────────

    def _get_nexus_client(self):
        """Get Nexus client or return None on failure.

        Returns:
            NexusClient or None.
        """
        try:
            from engine.nexus.client import get_nexus_client
            return get_nexus_client()
        except Exception as exc:
            logger.debug("Nexus unavailable: %s", exc)
            return None

    def _nexus_search(self, query: str, category: str = "", limit: int = 20) -> List[Dict]:
        """Search Nexus with graceful degradation.

        Args:
            query: Search query string.
            category: Optional category filter.
            limit: Maximum results.

        Returns:
            List of Nexus result dicts.
        """
        client = self._get_nexus_client()
        if not client:
            return []
        try:
            kwargs: Dict = {"limit": limit}
            if category:
                kwargs["category"] = category
            return client.search(query, **kwargs) or []
        except Exception as exc:
            logger.debug("Nexus search error: %s", exc)
            return []

    @staticmethod
    def _nexus_result_to_feed_item(result: Dict) -> FeedItem:
        """Convert a raw Nexus search result to a FeedItem.

        Args:
            result: Nexus result dict.

        Returns:
            FeedItem.
        """
        title = result.get("title", "")
        content = result.get("content", "")
        tags = result.get("tags", [])

        # Derive category from tags
        category = ""
        for tag in tags:
            if tag not in {"news", "raw_news", "distilled", "auto-distilled"}:
                category = tag
                break

        # Try to extract URL from content
        url = ""
        for line in content.split("\n"):
            if line.startswith("Source:"):
                url = line.replace("Source:", "").strip()
                break

        created_at = result.get("created_at")
        if created_at:
            if isinstance(created_at, str):
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    published_at = dt.timestamp()
                except Exception:
                    published_at = time.time()
            elif isinstance(created_at, (int, float)):
                published_at = float(created_at)
            else:
                published_at = time.time()
        else:
            published_at = time.time()

        is_distilled = "distilled" in tags or "auto-distilled" in tags
        article_id = result.get("id", str(uuid.uuid4()))
        summary = content[:300].strip()

        return FeedItem(
            article_id=str(article_id),
            title=title.replace("[NEWS] ", "").replace("[ai_ml] ", ""),
            summary=summary,
            url=url,
            source="",
            category=category,
            published_at=published_at,
            quality_score=0.0,
            trend_score=0.0,
            nexus_entry_id=str(article_id),
            is_distilled=is_distilled,
            tags=tags,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_feed(
        self,
        category: str = "",
        limit: int = 20,
        since_hours: int = 24,
        min_score: float = 0.4,
    ) -> List[FeedItem]:
        """Return a curated news feed from Nexus.

        Args:
            category: Optional category filter (e.g., "ai_ml", "security").
            limit: Maximum items to return.
            since_hours: Only include articles from the last N hours.
            min_score: Minimum quality score (applied to any scored articles).

        Returns:
            List of FeedItem objects, most recent first.
        """
        query = f"news {category}" if category else "news"
        results = self._nexus_search(query, category="news", limit=limit * 2)

        if not results:
            return []

        cutoff = time.time() - (since_hours * 3600)
        items = []

        for result in results:
            item = self._nexus_result_to_feed_item(result)
            if item.published_at < cutoff:
                continue
            items.append(item)

        # Sort by published_at descending
        items.sort(key=lambda i: i.published_at, reverse=True)
        return items[:limit]

    def get_trending_feed(self, limit: int = 10) -> List[FeedItem]:
        """Return news items for currently trending topics.

        Uses TrendDetector to identify hot topics, then fetches matching
        articles from Nexus.

        Args:
            limit: Maximum items to return.

        Returns:
            List of FeedItem objects.
        """
        trending_topics = self._trends.get_trending_topics(limit=limit)
        if not trending_topics:
            # Fall back to general recent feed
            return self.get_feed(limit=limit, since_hours=12)

        items: List[FeedItem] = []
        seen_ids: set = set()

        for topic_data in trending_topics:
            topic = topic_data.get("topic", "")
            velocity = topic_data.get("article_count", 0)
            if not topic:
                continue

            results = self._nexus_search(f"news {topic}", category="news", limit=5)
            for result in results:
                item = self._nexus_result_to_feed_item(result)
                if item.article_id not in seen_ids:
                    item.trend_score = float(velocity)
                    items.append(item)
                    seen_ids.add(item.article_id)

        # Sort by trend_score, then recency
        items.sort(key=lambda i: (i.trend_score, i.published_at), reverse=True)
        return items[:limit]

    def get_personalized_feed(
        self,
        interests: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[FeedItem]:
        """Return a personalized feed based on interests or stored profile.

        Args:
            interests: Optional list of interest keywords. If None, uses
                the stored interest profile.
            limit: Maximum items to return.

        Returns:
            List of FeedItem objects.
        """
        if interests is None:
            profile = self.get_interest_profile()
            interests = profile.get("top_categories", []) + profile.get("top_keywords", [])

        if not interests:
            return self.get_feed(limit=limit)

        items: List[FeedItem] = []
        seen_ids: set = set()

        for interest in interests[:5]:
            results = self._nexus_search(f"news {interest}", category="news", limit=limit // 5 + 2)
            for result in results:
                item = self._nexus_result_to_feed_item(result)
                if item.article_id not in seen_ids:
                    items.append(item)
                    seen_ids.add(item.article_id)

        items.sort(key=lambda i: i.published_at, reverse=True)
        return items[:limit]

    def mark_read(self, article_id: str) -> None:
        """Record that an article was read.

        Args:
            article_id: The article identifier.
        """
        self._record_interaction(article_id, action="read")

    def mark_useful(self, article_id: str, useful: bool) -> None:
        """Record a usefulness signal for an article.

        Args:
            article_id: The article identifier.
            useful: True if useful, False if not useful.
        """
        action = "useful" if useful else "not_useful"
        self._record_interaction(article_id, action=action)

    def _record_interaction(
        self,
        article_id: str,
        action: str,
        url: str = "",
        title: str = "",
        category: str = "",
    ) -> None:
        """Persist an article interaction to the database.

        Args:
            article_id: Article identifier.
            action: Interaction type string.
            url: Optional article URL.
            title: Optional article title.
            category: Optional article category.
        """
        try:
            interaction_id = str(uuid.uuid4())
            now = time.time()
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO article_interactions
                       (interaction_id, article_id, url, title, category, action, recorded_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (interaction_id, article_id, url, title, category, action, now),
                )
                conn.commit()
        except Exception as exc:
            logger.debug("record_interaction error: %s", exc)

    def get_daily_digest(self) -> Dict:
        """Return a structured daily digest of top stories, trends, and categories.

        Returns:
            Dict with keys: date, top_stories, trending_topics, categories,
            total_articles, generated_at.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        top_stories = self.get_feed(limit=5, since_hours=24)
        trending = self._trends.get_trending_topics(limit=5)

        # Get per-category counts
        categories: Dict[str, int] = {}
        for item in self.get_feed(limit=50, since_hours=24):
            cat = item.category or "general"
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "date": today,
            "top_stories": [item.to_dict() for item in top_stories],
            "trending_topics": trending,
            "categories": categories,
            "total_articles": sum(categories.values()),
            "generated_at": time.time(),
        }

    def sync_to_nexus(self, article: Dict) -> str:
        """Ensure an article is distilled and present in Nexus.

        If already distilled, returns the existing entry ID.
        If not, triggers distillation immediately.

        Args:
            article: Article dict.

        Returns:
            Nexus entry ID string, or empty string on failure.
        """
        url = article.get("url", "")
        if not url:
            return ""

        # Check if already distilled
        try:
            from engine.nexus.news.article_scorer import ArticleScorer
            from pathlib import Path as _Path
            news_db = _Path("data/news.db")
            if news_db.exists():
                with sqlite3.connect(str(news_db)) as conn:
                    row = conn.execute(
                        "SELECT distilled FROM articles WHERE url=?",
                        (url,),
                    ).fetchone()
                    if row and row[0]:
                        # Search Nexus for the existing entry
                        results = self._nexus_search(
                            article.get("title", url),
                            category="news",
                            limit=1,
                        )
                        if results:
                            return str(results[0].get("id", ""))
        except Exception as exc:
            logger.debug("sync_to_nexus lookup error: %s", exc)

        # Trigger distillation
        try:
            from engine.nexus.news.realtime_distiller import get_realtime_distiller
            distiller = get_realtime_distiller()
            entry_id = distiller.distill_article(article)
            return entry_id or ""
        except Exception as exc:
            logger.warning("sync_to_nexus distillation error: %s", exc)
            return ""

    def get_interest_profile(self) -> Dict:
        """Return the inferred interest profile from interaction history.

        Returns:
            Dict with keys: top_categories, top_keywords, read_count,
            useful_count, last_updated.
        """
        try:
            with self._conn() as conn:
                # Category preferences from positive interactions
                cat_rows = conn.execute(
                    """SELECT category, COUNT(*) as cnt
                       FROM article_interactions
                       WHERE action IN ('useful', 'read') AND category != ''
                       GROUP BY category ORDER BY cnt DESC LIMIT 10""",
                ).fetchall()

                # Load stored extra profile data
                kw_row = conn.execute(
                    "SELECT value FROM interest_profile WHERE key='top_keywords'"
                ).fetchone()

                read_count = conn.execute(
                    "SELECT COUNT(*) FROM article_interactions WHERE action='read'"
                ).fetchone()[0]

                useful_count = conn.execute(
                    "SELECT COUNT(*) FROM article_interactions WHERE action='useful'"
                ).fetchone()[0]

            top_categories = [row["category"] for row in cat_rows]
            top_keywords = json.loads(kw_row["value"]) if kw_row else []

            return {
                "top_categories": top_categories,
                "top_keywords": top_keywords,
                "read_count": read_count,
                "useful_count": useful_count,
                "last_updated": time.time(),
            }
        except Exception as exc:
            logger.warning("get_interest_profile error: %s", exc)
            return {
                "top_categories": [],
                "top_keywords": [],
                "read_count": 0,
                "useful_count": 0,
                "last_updated": 0.0,
            }

    def update_interest_profile(self, feedback: Dict) -> None:
        """Update the stored interest profile with new feedback signals.

        Args:
            feedback: Dict with optional keys: top_keywords (list), category (str),
                action ('useful' | 'read' | 'not_useful'), article_id (str).
        """
        now = time.time()

        # Record interaction if article info provided
        article_id = feedback.get("article_id", "")
        if article_id:
            action = feedback.get("action", "read")
            self._record_interaction(
                article_id=article_id,
                action=action,
                url=feedback.get("url", ""),
                title=feedback.get("title", ""),
                category=feedback.get("category", ""),
            )

        # Update keyword list if provided
        keywords = feedback.get("top_keywords")
        if keywords and isinstance(keywords, list):
            try:
                with self._conn() as conn:
                    conn.execute(
                        """INSERT INTO interest_profile (key, value, updated_at)
                           VALUES ('top_keywords', ?, ?)
                           ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                               updated_at=excluded.updated_at""",
                        (json.dumps(keywords[:20]), now),
                    )
                    conn.commit()
            except Exception as exc:
                logger.debug("update_interest_profile error: %s", exc)


# ── Module-level singleton ─────────────────────────────────────────────────

_feed_instance: Optional[NexusFeed] = None
_feed_lock = threading.Lock()


def get_nexus_feed() -> NexusFeed:
    """Return the module-level NexusFeed singleton.

    Returns:
        Shared NexusFeed instance.
    """
    global _feed_instance
    with _feed_lock:
        if _feed_instance is None:
            _feed_instance = NexusFeed()
    return _feed_instance
