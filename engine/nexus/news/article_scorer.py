"""Article Quality Scorer — scores news articles 0.0–1.0 before NLM distillation.

Scoring factors (weighted):
- Content length   (0.15) — 200–2000 words ideal
- Source reputation(0.20) — tier-1 sources score higher
- Recency          (0.20) — articles <2h score 1.0, decay over 48h
- Title quality    (0.10) — no clickbait patterns
- Category         (0.15) — tech/AI/science weighted higher
- Dedup novelty    (0.20) — penalise articles similar to already-distilled content

Usage::

    from engine.nexus.news.article_scorer import ArticleScorer

    scorer = ArticleScorer()
    score  = scorer.score(article)
    top    = scorer.get_top(articles, n=10)
"""
from __future__ import annotations

import logging
import math
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_DB_PATH = Path("data/news.db")

# Weights must sum to 1.0
_W_LENGTH     = 0.15
_W_REPUTATION = 0.20
_W_RECENCY    = 0.20
_W_TITLE      = 0.10
_W_CATEGORY   = 0.15
_W_NOVELTY    = 0.20

# Tier-1 source domains and names that get the highest reputation score
_TIER1_SOURCES = frozenset({
    "reuters", "bbc", "nature", "arxiv", "science", "sciencedaily",
    "techcrunch", "theverge", "wired", "arstechnica", "ieee",
    "mit", "stanford", "openai", "anthropic", "deepmind", "google",
    "hacker news", "hackernews", "ycombinator",
})

# Category weight map — higher means more relevant to core audience
_CATEGORY_WEIGHTS: Dict[str, float] = {
    "ai_ml": 1.0,
    "ai_research": 1.0,
    "local_inference": 1.0,
    "open_source": 0.9,
    "python": 0.85,
    "science": 0.8,
    "dev_tools": 0.8,
    "security": 0.75,
    "tech": 0.7,
    "world": 0.5,
    "sports": 0.2,
    "celebrity": 0.1,
    "entertainment": 0.3,
}

# Clickbait detection patterns (case-insensitive)
_CLICKBAIT_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"you won.t believe",
        r"shocking(ly)?",
        r"mind[\s-]?blow",
        r"\d+\s+(things|reasons|ways|tips|tricks|facts|secrets)\s+(that|you|to|about|for)",
        r"this (one )?weird (trick|tip|hack)",
        r"doctors hate",
        r"before it.s deleted",
        r"(what|here.s what) happened next",
        r"won.t believe what",
        r"broke the internet",
        r"goes viral",
        r"click(bait)?",
        r"!!!+",
    ]
]

# Recency: half-life decay constant
_RECENCY_HALF_LIFE_HOURS = 12.0  # score halves every 12 hours
_RECENCY_FULL_SCORE_HOURS = 2.0  # articles <2h get full recency score
_RECENCY_ZERO_HOURS = 48.0       # articles >48h get 0 recency


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of an article quality score.

    Attributes:
        total: Final weighted score 0.0–1.0.
        length: Raw length sub-score 0.0–1.0.
        reputation: Raw reputation sub-score 0.0–1.0.
        recency: Raw recency sub-score 0.0–1.0.
        title: Raw title-quality sub-score 0.0–1.0.
        category: Raw category-relevance sub-score 0.0–1.0.
        novelty: Raw dedup-novelty sub-score 0.0–1.0.
    """

    total: float = 0.0
    length: float = 0.0
    reputation: float = 0.0
    recency: float = 0.0
    title: float = 0.0
    category: float = 0.0
    novelty: float = 0.0


class ArticleScorer:
    """Scores news articles for quality and relevance before NLM distillation.

    Scores are deterministic for the same article (no randomness),
    except for recency which is time-dependent.  Use ``score_at``
    for deterministic recency in tests.

    Args:
        db_path: Override for the article storage SQLite database path.
        recent_titles: Optional list of recent distilled titles for novelty scoring.
            If None, the scorer attempts to load from ``data/news.db``.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        recent_titles: Optional[List[str]] = None,
    ) -> None:
        self._db_path = db_path or _DB_PATH
        self._lock = threading.Lock()
        self._recent_titles: List[str] = recent_titles or []
        self._recent_tfidf: Optional[Dict[str, float]] = None
        self._ensure_db()

    # ── DB helpers ───────────────────────────────────────────────────────────

    def _ensure_db(self) -> None:
        """Create the news.db article table + quality_score column if absent."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS articles (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        url         TEXT UNIQUE NOT NULL,
                        title       TEXT,
                        summary     TEXT,
                        category    TEXT,
                        source_id   TEXT,
                        source_name TEXT,
                        published_at REAL,
                        fetched_at  REAL,
                        quality_score REAL,
                        distilled   INTEGER DEFAULT 0,
                        word_count  INTEGER DEFAULT 0
                    )
                """)
                # Add quality_score column if it doesn't exist (migration)
                cursor = conn.execute("PRAGMA table_info(articles)")
                cols = {row[1] for row in cursor.fetchall()}
                if "quality_score" not in cols:
                    conn.execute("ALTER TABLE articles ADD COLUMN quality_score REAL")
                if "distilled" not in cols:
                    conn.execute("ALTER TABLE articles ADD COLUMN distilled INTEGER DEFAULT 0")
                conn.commit()
        except Exception as exc:
            logger.warning("ArticleScorer DB init error: %s", exc)

    def _load_recent_titles(self, limit: int = 200) -> List[str]:
        """Load recently distilled article titles for novelty comparison."""
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                rows = conn.execute(
                    "SELECT title FROM articles WHERE distilled=1 "
                    "ORDER BY fetched_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [r[0] for r in rows if r[0]]
        except Exception as exc:
            logger.debug("Could not load recent titles: %s", exc)
            return []

    def save_score(self, url: str, score: float) -> None:
        """Persist a quality score for an article URL.

        Args:
            url: Article URL (primary key).
            score: Quality score 0.0–1.0 to persist.
        """
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    "UPDATE articles SET quality_score=? WHERE url=?",
                    (score, url),
                )
                conn.commit()
        except Exception as exc:
            logger.debug("Could not save score: %s", exc)

    # ── Scoring sub-components ───────────────────────────────────────────────

    @staticmethod
    def _score_length(text: str) -> float:
        """Score based on word count.  200–2000 words is ideal.

        Args:
            text: The article body or summary text.

        Returns:
            Score 0.0–1.0.
        """
        words = len(text.split()) if text else 0
        if words < 10:
            return 0.05
        if words < 50:
            return 0.2
        if words < 200:
            return 0.5 + 0.5 * (words / 200)
        if words <= 2000:
            return 1.0
        if words <= 10000:
            # gentle decline beyond 2000
            return max(0.5, 1.0 - (words - 2000) / 16000)
        return 0.2

    @staticmethod
    def _score_reputation(article: Dict) -> float:
        """Score based on source name/domain tier.

        Args:
            article: Article dict with optional 'source_name' / 'source_id' fields.

        Returns:
            Score 0.0–1.0.
        """
        name = (article.get("source_name") or article.get("source_id") or "").lower()
        url = (article.get("url") or "").lower()

        # Check tier-1 membership in name or domain
        for t1 in _TIER1_SOURCES:
            if t1 in name or t1 in url:
                return 1.0

        # Fall back to explicit quality_score if present in the source registry
        q = article.get("quality_score")
        if q is not None:
            try:
                return max(0.0, min(1.0, float(q)))
            except (TypeError, ValueError):
                pass

        return 0.5  # neutral for unknown sources

    @staticmethod
    def _score_recency(article: Dict, now: Optional[float] = None) -> float:
        """Score based on article age with exponential decay.

        Args:
            article: Article dict with 'published_at' (UNIX timestamp or ISO string).
            now: Reference time (seconds since epoch). Defaults to ``time.time()``.

        Returns:
            Score 0.0–1.0.
        """
        if now is None:
            now = time.time()

        pub = article.get("published_at")
        if pub is None:
            return 0.5  # neutral when unknown

        # Accept both float timestamps and ISO-8601 strings
        if isinstance(pub, str):
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                pub = dt.timestamp()
            except Exception:
                return 0.5
        elif hasattr(pub, "timestamp"):
            pub = pub.timestamp()

        try:
            age_hours = max(0.0, (now - float(pub)) / 3600)
        except (TypeError, ValueError):
            return 0.5

        if age_hours <= _RECENCY_FULL_SCORE_HOURS:
            return 1.0
        if age_hours >= _RECENCY_ZERO_HOURS:
            return 0.0

        # Exponential decay between 2h and 48h
        adjusted = age_hours - _RECENCY_FULL_SCORE_HOURS
        decay = math.exp(-math.log(2) * adjusted / _RECENCY_HALF_LIFE_HOURS)
        return max(0.0, min(1.0, decay))

    @staticmethod
    def _score_title(title: str) -> float:
        """Score based on title quality — penalise clickbait patterns.

        Args:
            title: Article headline text.

        Returns:
            Score 0.0–1.0.
        """
        if not title or len(title) < 5:
            return 0.2

        for pattern in _CLICKBAIT_PATTERNS:
            if pattern.search(title):
                return 0.1

        # Bonus for substantive titles (>= 5 words)
        word_count = len(title.split())
        if word_count < 3:
            return 0.4
        if word_count >= 5:
            return 1.0
        return 0.8

    @staticmethod
    def _score_category(category: str) -> float:
        """Score based on category relevance.

        Args:
            category: Article category string.

        Returns:
            Score 0.0–1.0.
        """
        cat = (category or "").lower().strip()
        return _CATEGORY_WEIGHTS.get(cat, 0.5)

    def _score_novelty(self, article: Dict) -> float:
        """Score based on novelty vs. already-distilled content.

        Uses TF-IDF cosine similarity against recent distilled titles.
        Penalises articles that are very similar to already-seen content.

        Args:
            article: Article dict with 'title' and/or 'summary'.

        Returns:
            Score 0.0–1.0 (1.0 = fully novel, 0.0 = duplicate).
        """
        text = f"{article.get('title', '')} {article.get('summary', '')}".strip()
        if not text:
            return 0.7

        if not self._recent_titles:
            # Try loading from DB once
            with self._lock:
                if not self._recent_titles:
                    self._recent_titles = self._load_recent_titles()

        if not self._recent_titles:
            return 1.0  # no comparison data → assume novel

        # Build TF-IDF similarity using simple word frequencies
        article_words = set(_tokenise(text))
        if not article_words:
            return 1.0

        max_sim = 0.0
        for past_title in self._recent_titles[:100]:
            past_words = set(_tokenise(past_title))
            if not past_words:
                continue
            intersection = len(article_words & past_words)
            if intersection == 0:
                continue
            sim = intersection / math.sqrt(len(article_words) * len(past_words))
            if sim > max_sim:
                max_sim = sim

        # High similarity → low novelty score
        novelty = 1.0 - min(1.0, max_sim * 2)
        return max(0.0, novelty)

    # ── Public API ────────────────────────────────────────────────────────────

    def score(self, article: Dict, now: Optional[float] = None) -> float:
        """Score a single article for quality and relevance.

        Args:
            article: Dict with keys: title, summary, url, source_name,
                published_at, category, quality_score (optional).
            now: Reference timestamp for recency (default: current time).

        Returns:
            Float score in [0.0, 1.0].
        """
        breakdown = self.score_detailed(article, now=now)
        return breakdown.total

    def score_detailed(self, article: Dict, now: Optional[float] = None) -> ScoreBreakdown:
        """Score an article and return the full sub-score breakdown.

        Args:
            article: Article dict (same as ``score()``).
            now: Reference timestamp for recency.

        Returns:
            ScoreBreakdown with total and per-factor scores.
        """
        text = f"{article.get('title', '')} {article.get('summary', '')}"

        length     = self._score_length(text)
        reputation = self._score_reputation(article)
        recency    = self._score_recency(article, now=now)
        title      = self._score_title(article.get("title", ""))
        category   = self._score_category(article.get("category", ""))
        novelty    = self._score_novelty(article)

        total = (
            _W_LENGTH     * length
            + _W_REPUTATION * reputation
            + _W_RECENCY    * recency
            + _W_TITLE      * title
            + _W_CATEGORY   * category
            + _W_NOVELTY    * novelty
        )
        total = round(max(0.0, min(1.0, total)), 4)

        return ScoreBreakdown(
            total=total,
            length=length,
            reputation=reputation,
            recency=recency,
            title=title,
            category=category,
            novelty=novelty,
        )

    def score_batch(
        self,
        articles: List[Dict],
        now: Optional[float] = None,
    ) -> List[Tuple[Dict, float]]:
        """Score a batch of articles, sorted descending by score.

        Args:
            articles: List of article dicts.
            now: Reference timestamp for recency.

        Returns:
            List of (article, score) tuples, highest score first.
        """
        results = [(a, self.score(a, now=now)) for a in articles]
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def get_top(
        self,
        articles: List[Dict],
        n: int = 10,
        threshold: float = 0.4,
        now: Optional[float] = None,
    ) -> List[Dict]:
        """Return top-N articles above a quality threshold.

        Args:
            articles: List of article dicts.
            n: Maximum number of articles to return.
            threshold: Minimum quality score to include.
            now: Reference timestamp for recency.

        Returns:
            Up to N articles above the threshold, sorted by score.
        """
        scored = self.score_batch(articles, now=now)
        return [a for a, s in scored if s >= threshold][:n]

    def refresh_recent_titles(self) -> None:
        """Reload recent distilled titles from the database."""
        with self._lock:
            self._recent_titles = self._load_recent_titles()
            self._recent_tfidf = None


# ── Helpers ────────────────────────────────────────────────────────────────

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "as", "up", "if", "not", "no",
})


def _tokenise(text: str) -> List[str]:
    """Tokenise text into lowercase non-stopword words >= 3 chars.

    Args:
        text: Raw text to tokenise.

    Returns:
        List of cleaned tokens.
    """
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return [w for w in words if w not in _STOPWORDS]


# ── Module-level singleton ─────────────────────────────────────────────────

_scorer_instance: Optional[ArticleScorer] = None
_scorer_lock = threading.Lock()


def get_article_scorer() -> ArticleScorer:
    """Return the module-level ArticleScorer singleton.

    Returns:
        Shared ArticleScorer instance.
    """
    global _scorer_instance
    with _scorer_lock:
        if _scorer_instance is None:
            _scorer_instance = ArticleScorer()
    return _scorer_instance
