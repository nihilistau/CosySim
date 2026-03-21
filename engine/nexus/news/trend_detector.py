"""Trend Detector — identifies trending topics and emerging stories.

Analyses a rolling window of news articles to detect topic velocity,
group related articles into "stories", and surface emerging content.
All story tracking is persisted in ``data/news_trends.db``.

Usage::

    from engine.nexus.news.trend_detector import TrendDetector

    detector = TrendDetector()
    reports  = detector.detect_trends(articles, window_hours=24)
    topics   = detector.get_trending_topics(limit=10)
"""
from __future__ import annotations

import logging
import math
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_DB_PATH = Path("data/news_trends.db")

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "as", "up", "if", "not", "no", "new",
    "says", "said", "according", "report", "reports", "use", "using",
    "now", "just", "also", "more", "one", "two", "three", "four", "five",
    "after", "before", "over", "about", "out", "get", "got", "his", "her",
    "their", "our", "your", "its", "via", "per", "due", "into",
})

_MIN_KEYWORD_LEN = 3
_MIN_KEYWORD_FREQUENCY = 2  # must appear in ≥ 2 articles to form a trend
_STORY_SIMILARITY_THRESHOLD = 0.15  # min keyword overlap to group articles
_VELOCITY_WINDOW_HOURS = 2.0   # short window for velocity calculation
_MAX_KEYWORDS_PER_ARTICLE = 15


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class TrendReport:
    """A detected trending topic or story cluster.

    Attributes:
        topic: Primary keyword/phrase representing the trend.
        article_count: Total articles in the window mentioning this topic.
        velocity: Articles per hour mentioning topic in the velocity window.
        peak_time: Timestamp of highest article concentration.
        sample_titles: Up to 3 representative article titles.
        story_id: Stable UUID for this story cluster.
        first_seen: Unix timestamp when this trend was first detected.
        category: Dominant news category among articles.
    """

    topic: str
    article_count: int
    velocity: float
    peak_time: float
    sample_titles: List[str] = field(default_factory=list)
    story_id: str = ""
    first_seen: float = 0.0
    category: str = ""


@dataclass
class _StoryRecord:
    """Internal story tracking record (DB row)."""

    story_id: str
    topic: str
    first_seen: float
    last_seen: float
    article_count: int
    category: str
    sample_titles: str  # JSON-encoded list
    keywords: str       # JSON-encoded list


# ── Trend Detector ───────────────────────────────────────────────────────────

class TrendDetector:
    """Detects trending topics and emerging stories from news articles.

    Stores story tracking in ``data/news_trends.db``.

    Args:
        db_path: Override for the SQLite trends database path.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._lock = threading.Lock()
        self._ensure_db()

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _ensure_db(self) -> None:
        """Create trends database schema if absent."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS stories (
                        story_id    TEXT PRIMARY KEY,
                        topic       TEXT NOT NULL,
                        first_seen  REAL NOT NULL,
                        last_seen   REAL NOT NULL,
                        article_count INTEGER DEFAULT 1,
                        category    TEXT DEFAULT '',
                        sample_titles TEXT DEFAULT '[]',
                        keywords    TEXT DEFAULT '[]'
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS story_articles (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        story_id    TEXT NOT NULL,
                        article_url TEXT,
                        article_title TEXT,
                        published_at REAL,
                        tracked_at  REAL NOT NULL
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_stories_last_seen "
                    "ON stories(last_seen)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sa_story_id "
                    "ON story_articles(story_id)"
                )
                conn.commit()
        except Exception as exc:
            logger.warning("TrendDetector DB init error: %s", exc)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ── NLP helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """Extract meaningful keywords from text.

        Tokenises, removes stopwords, and returns unique words >= min length.

        Args:
            text: Input text (title + summary concatenated).

        Returns:
            List of unique keyword strings (lowercase, alphabetic only).
        """
        words = re.findall(r"[a-zA-Z]{%d,}" % _MIN_KEYWORD_LEN, text.lower())
        seen: dict[str, int] = {}
        for w in words:
            if w not in _STOPWORDS:
                seen[w] = seen.get(w, 0) + 1

        # Sort by frequency descending
        sorted_words = sorted(seen, key=lambda w: seen[w], reverse=True)
        return sorted_words[:_MAX_KEYWORDS_PER_ARTICLE]

    @staticmethod
    def _article_timestamp(article: Dict) -> float:
        """Extract a Unix timestamp from an article dict.

        Args:
            article: Article dict with 'published_at' or 'fetched_at'.

        Returns:
            Unix timestamp, or current time if unparseable.
        """
        for key in ("published_at", "fetched_at"):
            val = article.get(key)
            if val is None:
                continue
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                try:
                    dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    return dt.timestamp()
                except Exception:
                    pass
            if hasattr(val, "timestamp"):
                return val.timestamp()
        return time.time()

    @staticmethod
    def _keyword_similarity(kw_a: List[str], kw_b: List[str]) -> float:
        """Jaccard-like similarity between two keyword lists.

        Args:
            kw_a: Keywords for article A.
            kw_b: Keywords for article B.

        Returns:
            Similarity score 0.0–1.0.
        """
        set_a = set(kw_a)
        set_b = set(kw_b)
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union else 0.0

    # ── Core Detection ────────────────────────────────────────────────────────

    def detect_trends(
        self,
        articles: List[Dict],
        window_hours: int = 24,
        now: Optional[float] = None,
    ) -> List[TrendReport]:
        """Detect trending topics from a list of articles.

        Groups articles by keyword co-occurrence into "stories", scores
        each by velocity (articles per hour in the short window), and
        returns TrendReport objects sorted by velocity descending.

        Args:
            articles: List of article dicts.
            window_hours: How many hours back to consider.
            now: Reference time (default: current time).

        Returns:
            List of TrendReport objects, highest velocity first.
        """
        if not articles:
            return []

        if now is None:
            now = time.time()

        cutoff = now - (window_hours * 3600)

        # Filter to window
        windowed = [
            a for a in articles
            if self._article_timestamp(a) >= cutoff
        ]
        if not windowed:
            return []

        # Extract keywords per article
        kw_map: Dict[int, List[str]] = {}
        for idx, article in enumerate(windowed):
            text = f"{article.get('title', '')} {article.get('summary', '')}"
            kw_map[idx] = self._extract_keywords(text)

        # Count keyword frequencies
        freq: Dict[str, int] = {}
        for kws in kw_map.values():
            for kw in kws:
                freq[kw] = freq.get(kw, 0) + 1

        # Keep keywords appearing in ≥ 2 articles
        trending_kws = {kw for kw, cnt in freq.items() if cnt >= _MIN_KEYWORD_FREQUENCY}

        if not trending_kws:
            return []

        # Group articles into story clusters by keyword co-occurrence
        clusters: List[Dict] = []  # [{topic, article_indices, keywords}]

        for kw in sorted(trending_kws, key=lambda k: freq[k], reverse=True):
            # Find articles containing this keyword
            matching = [idx for idx, kws in kw_map.items() if kw in kws]

            # Check if any existing cluster covers this keyword set
            merged = False
            for cluster in clusters:
                sim = self._keyword_similarity(
                    [kw], cluster["keywords"]
                )
                if sim >= _STORY_SIMILARITY_THRESHOLD or kw in cluster["keywords"]:
                    cluster["article_indices"].update(matching)
                    cluster["keywords"].add(kw)
                    merged = True
                    break

            if not merged:
                clusters.append({
                    "topic": kw,
                    "keywords": {kw},
                    "article_indices": set(matching),
                })

        # Build TrendReports
        reports: List[TrendReport] = []
        velocity_cutoff = now - (_VELOCITY_WINDOW_HOURS * 3600)

        for cluster in clusters:
            indices = sorted(cluster["article_indices"])
            cluster_articles = [windowed[i] for i in indices]
            article_count = len(cluster_articles)

            if article_count < _MIN_KEYWORD_FREQUENCY:
                continue

            # Velocity: articles in the short window
            recent_count = sum(
                1 for a in cluster_articles
                if self._article_timestamp(a) >= velocity_cutoff
            )
            velocity = recent_count / _VELOCITY_WINDOW_HOURS

            # Peak time: timestamp of the most recent article
            timestamps = [self._article_timestamp(a) for a in cluster_articles]
            peak_time = max(timestamps)
            first_seen = min(timestamps)

            sample_titles = [
                a.get("title", "")[:100]
                for a in cluster_articles
                if a.get("title")
            ][:3]

            # Dominant category
            cats = [a.get("category", "") for a in cluster_articles if a.get("category")]
            category = max(set(cats), key=cats.count) if cats else ""

            # Find or assign a stable story_id
            story_id = self._get_or_create_story_id(
                cluster["topic"],
                list(cluster["keywords"]),
            )

            reports.append(TrendReport(
                topic=cluster["topic"],
                article_count=article_count,
                velocity=round(velocity, 3),
                peak_time=peak_time,
                sample_titles=sample_titles,
                story_id=story_id,
                first_seen=first_seen,
                category=category,
            ))

        # Sort by velocity descending, then article_count
        reports.sort(key=lambda r: (r.velocity, r.article_count), reverse=True)
        return reports

    def _get_or_create_story_id(self, topic: str, keywords: List[str]) -> str:
        """Find or create a stable story_id for a topic cluster.

        Args:
            topic: Primary keyword.
            keywords: All keywords in the cluster.

        Returns:
            UUID string story_id.
        """
        try:
            import json
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT story_id FROM stories WHERE topic=? LIMIT 1",
                    (topic,),
                ).fetchone()
                if row:
                    return row["story_id"]

                story_id = str(uuid.uuid4())
                now = time.time()
                conn.execute(
                    """INSERT INTO stories
                       (story_id, topic, first_seen, last_seen, article_count,
                        category, sample_titles, keywords)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (story_id, topic, now, now, 1, "", "[]", json.dumps(keywords)),
                )
                conn.commit()
                return story_id
        except Exception as exc:
            logger.debug("Could not persist story: %s", exc)
            return str(uuid.uuid4())

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_trending_topics(self, limit: int = 10) -> List[Dict]:
        """Return the most recently active stories from the database.

        Args:
            limit: Maximum number of topics to return.

        Returns:
            List of story dicts sorted by last_seen descending.
        """
        try:
            import json
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT story_id, topic, first_seen, last_seen,
                              article_count, category, sample_titles, keywords
                       FROM stories
                       ORDER BY last_seen DESC, article_count DESC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
            result = []
            for row in rows:
                result.append({
                    "story_id": row["story_id"],
                    "topic": row["topic"],
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "article_count": row["article_count"],
                    "category": row["category"],
                    "sample_titles": json.loads(row["sample_titles"]),
                    "keywords": json.loads(row["keywords"]),
                })
            return result
        except Exception as exc:
            logger.warning("get_trending_topics error: %s", exc)
            return []

    def get_emerging_stories(self, threshold: int = 3) -> List[Dict]:
        """Return stories with article_count >= threshold detected recently.

        "Recently" means the story's last_seen is within the last 12 hours.

        Args:
            threshold: Minimum article count for a story to be "emerging".

        Returns:
            List of story dicts.
        """
        try:
            import json
            cutoff = time.time() - (12 * 3600)
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT story_id, topic, first_seen, last_seen,
                              article_count, category, sample_titles, keywords
                       FROM stories
                       WHERE article_count >= ? AND last_seen >= ?
                       ORDER BY article_count DESC""",
                    (threshold, cutoff),
                ).fetchall()
            return [
                {
                    "story_id": row["story_id"],
                    "topic": row["topic"],
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "article_count": row["article_count"],
                    "category": row["category"],
                    "sample_titles": json.loads(row["sample_titles"]),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("get_emerging_stories error: %s", exc)
            return []

    def track_story(self, story_id: str, article: Dict) -> None:
        """Register an article as belonging to a story.

        Updates last_seen and article_count for the story in the DB.

        Args:
            story_id: The story UUID to update.
            article: Article dict with url, title, published_at.
        """
        try:
            import json
            now = time.time()
            title = article.get("title", "")
            url = article.get("url", "")
            pub = self._article_timestamp(article)

            with self._conn() as conn:
                conn.execute(
                    """UPDATE stories
                       SET last_seen=?, article_count=article_count+1
                       WHERE story_id=?""",
                    (now, story_id),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO story_articles
                       (story_id, article_url, article_title, published_at, tracked_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (story_id, url, title, pub, now),
                )
                conn.commit()
        except Exception as exc:
            logger.debug("track_story error: %s", exc)

    def get_story_timeline(self, story_id: str) -> List[Dict]:
        """Return all articles tracked for a story, ordered by time.

        Args:
            story_id: The story UUID.

        Returns:
            List of article dicts: {article_url, article_title, published_at}.
        """
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT article_url, article_title, published_at, tracked_at
                       FROM story_articles
                       WHERE story_id=?
                       ORDER BY published_at ASC""",
                    (story_id,),
                ).fetchall()
            return [
                {
                    "url": row["article_url"],
                    "title": row["article_title"],
                    "published_at": row["published_at"],
                    "tracked_at": row["tracked_at"],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("get_story_timeline error: %s", exc)
            return []

    def persist_trends(self, reports: List[TrendReport]) -> None:
        """Persist a batch of TrendReports to the database.

        Updates existing stories or creates new ones. Also updates sample
        titles for any story that has new article count.

        Args:
            reports: List of TrendReport objects from detect_trends().
        """
        try:
            import json
            now = time.time()
            with self._conn() as conn:
                for report in reports:
                    conn.execute(
                        """INSERT INTO stories
                           (story_id, topic, first_seen, last_seen,
                            article_count, category, sample_titles, keywords)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(story_id) DO UPDATE SET
                               last_seen=excluded.last_seen,
                               article_count=excluded.article_count,
                               category=excluded.category,
                               sample_titles=excluded.sample_titles""",
                        (
                            report.story_id,
                            report.topic,
                            report.first_seen or now,
                            report.peak_time or now,
                            report.article_count,
                            report.category,
                            json.dumps(report.sample_titles),
                            "[]",
                        ),
                    )
                conn.commit()
        except Exception as exc:
            logger.warning("persist_trends error: %s", exc)

    def get_trend_report_dict(
        self,
        articles: List[Dict],
        window_hours: int = 24,
        limit: int = 10,
    ) -> Dict:
        """Convenience method: detect + format a trend report dict.

        Args:
            articles: Article dicts.
            window_hours: Detection window.
            limit: Max trends to include.

        Returns:
            Dict with keys: trending_topics, emerging_stories, total_articles, window_hours.
        """
        reports = self.detect_trends(articles, window_hours=window_hours)
        self.persist_trends(reports)

        return {
            "trending_topics": [
                {
                    "topic": r.topic,
                    "article_count": r.article_count,
                    "velocity": r.velocity,
                    "category": r.category,
                    "story_id": r.story_id,
                    "sample_titles": r.sample_titles,
                }
                for r in reports[:limit]
            ],
            "emerging_stories": self.get_emerging_stories(threshold=3),
            "total_articles": len(articles),
            "window_hours": window_hours,
        }


# ── Module-level singleton ─────────────────────────────────────────────────

_detector_instance: Optional[TrendDetector] = None
_detector_lock = threading.Lock()


def get_trend_detector() -> TrendDetector:
    """Return the module-level TrendDetector singleton.

    Returns:
        Shared TrendDetector instance.
    """
    global _detector_instance
    with _detector_lock:
        if _detector_instance is None:
            _detector_instance = TrendDetector()
    return _detector_instance
