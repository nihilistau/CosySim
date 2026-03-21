"""Real-Time Distillation Trigger — event-driven NLM distillation.

Triggers NLM distillation immediately when high-quality articles arrive,
rather than waiting for a scheduled batch run. Maintains a queue of
pending articles and tracks distillation statistics.

Usage::

    from engine.nexus.news.realtime_distiller import RealtimeDistiller

    distiller = RealtimeDistiller()
    distiller.on_articles_stored(articles)  # call after fetch
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from engine.nexus.news.article_scorer import ArticleScorer, get_article_scorer

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_DB_PATH = Path("data/news_distill_queue.db")

# Per-article NLM questions
_ARTICLE_QUESTIONS = [
    "What is the key development described in this article?",
    "What are the main implications or consequences of this development?",
    "What should an informed person know or do based on this news?",
]


@dataclass
class DistillationRecord:
    """Tracking record for a distillation attempt.

    Attributes:
        queue_id: Unique ID for this queue entry.
        url: Article URL.
        title: Article title.
        category: Article category.
        quality_score: Score that caused this article to be queued.
        queued_at: Unix timestamp when queued.
        distilled_at: Unix timestamp when distillation completed (or None).
        nexus_entry_id: Nexus entry ID if distillation succeeded.
        status: 'pending' | 'distilling' | 'done' | 'failed' | 'skipped'.
        error: Error message if status is 'failed'.
    """

    queue_id: str = ""
    url: str = ""
    title: str = ""
    category: str = ""
    quality_score: float = 0.0
    queued_at: float = 0.0
    distilled_at: Optional[float] = None
    nexus_entry_id: Optional[str] = None
    status: str = "pending"
    error: str = ""


class RealtimeDistiller:
    """Triggers NLM distillation when high-quality articles arrive.

    Articles above ``QUALITY_THRESHOLD`` are added to a persistent queue
    and distilled via NotebookLM. Results are stored in Nexus.

    Args:
        quality_threshold: Minimum ArticleScorer score to distill.
        db_path: Override for the queue SQLite database path.
        scorer: Optional ArticleScorer instance (defaults to singleton).
    """

    QUALITY_THRESHOLD: float = 0.6

    def __init__(
        self,
        quality_threshold: float = QUALITY_THRESHOLD,
        db_path: Optional[Path] = None,
        scorer: Optional[ArticleScorer] = None,
    ) -> None:
        self.quality_threshold = quality_threshold
        self._db_path = db_path or _DB_PATH
        self._scorer = scorer or get_article_scorer()
        self._lock = threading.Lock()
        self._ensure_db()

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _ensure_db(self) -> None:
        """Create the distillation queue database schema if absent."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS distill_queue (
                        queue_id        TEXT PRIMARY KEY,
                        url             TEXT NOT NULL,
                        title           TEXT DEFAULT '',
                        category        TEXT DEFAULT '',
                        quality_score   REAL DEFAULT 0.0,
                        queued_at       REAL NOT NULL,
                        distilled_at    REAL,
                        nexus_entry_id  TEXT,
                        status          TEXT DEFAULT 'pending',
                        error           TEXT DEFAULT ''
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_dq_status ON distill_queue(status)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_dq_queued ON distill_queue(queued_at)"
                )
                conn.commit()
        except Exception as exc:
            logger.warning("RealtimeDistiller DB init error: %s", exc)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _enqueue(self, article: Dict, score: float) -> str:
        """Add an article to the distillation queue.

        Args:
            article: Article dict.
            score: Pre-computed quality score.

        Returns:
            queue_id string.
        """
        queue_id = str(uuid.uuid4())
        now = time.time()
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO distill_queue
                       (queue_id, url, title, category, quality_score, queued_at, status)
                       VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                    (
                        queue_id,
                        article.get("url", ""),
                        article.get("title", "")[:500],
                        article.get("category", ""),
                        score,
                        now,
                    ),
                )
                conn.commit()
        except Exception as exc:
            logger.debug("Enqueue error: %s", exc)
        return queue_id

    def _update_status(
        self,
        queue_id: str,
        status: str,
        nexus_entry_id: Optional[str] = None,
        error: str = "",
    ) -> None:
        """Update a queue entry's status.

        Args:
            queue_id: Queue entry ID.
            status: New status string.
            nexus_entry_id: Nexus entry ID on success.
            error: Error message on failure.
        """
        now = time.time()
        try:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE distill_queue
                       SET status=?, nexus_entry_id=?, error=?, distilled_at=?
                       WHERE queue_id=?""",
                    (status, nexus_entry_id, error, now if status in ("done", "failed") else None, queue_id),
                )
                conn.commit()
        except Exception as exc:
            logger.debug("update_status error: %s", exc)

    # ── NLM helpers ───────────────────────────────────────────────────────────

    def _get_or_create_notebook(self, category: str) -> Optional[str]:
        """Get or create an NLM notebook for a news category.

        Args:
            category: News category string.

        Returns:
            Notebook ID string, or None if NLM unavailable.
        """
        try:
            from engine.nexus.nlm_client_router import get_nlm_router
            router = get_nlm_router()
            name = f"CosySim News — {category.replace('_', ' ').title()}"
            notebook_id = router.get_or_create_notebook(name)
            return notebook_id
        except Exception as exc:
            logger.debug("NLM notebook access error: %s", exc)
            return None

    def _ask_nlm(
        self,
        notebook_id: str,
        text_source: str,
        questions: List[str],
    ) -> List[str]:
        """Add text source to notebook and ask distillation questions.

        Args:
            notebook_id: Target NLM notebook.
            text_source: Article text to add as a source.
            questions: Questions to ask the notebook.

        Returns:
            List of answer strings (empty strings on failure).
        """
        answers: List[str] = []
        try:
            from engine.nexus.nlm_client_router import get_nlm_router
            router = get_nlm_router()
            # Add article as text source
            router.add_text_source(notebook_id, text_source)
            # Ask questions
            for question in questions:
                try:
                    answer = router.ask(notebook_id, question)
                    answers.append(str(answer) if answer else "")
                except Exception as exc:
                    logger.debug("NLM question failed: %s", exc)
                    answers.append("")
        except Exception as exc:
            logger.debug("NLM batch ask error: %s", exc)
        return answers

    def _store_in_nexus(
        self,
        article: Dict,
        answers: List[str],
        score: float,
    ) -> Optional[str]:
        """Store distillation Q&A in Nexus.

        Args:
            article: Source article dict.
            answers: List of answers corresponding to _ARTICLE_QUESTIONS.
            score: Article quality score.

        Returns:
            Nexus entry ID string, or None on failure.
        """
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()

            category = article.get("category", "news")
            title = article.get("title", "Unknown")
            url = article.get("url", "")
            source = article.get("source_name") or article.get("source_id") or "unknown"
            from urllib.parse import urlparse
            source_domain = urlparse(url).netloc or source

            content_parts = [f"**{title}**\n\nSource: {url}\nScore: {score:.2f}"]
            for q, a in zip(_ARTICLE_QUESTIONS, answers):
                if a:
                    content_parts.append(f"\n**Q: {q}**\n{a}")

            content = "\n".join(content_parts)
            tags = ["news", category, source_domain, "auto-distilled"]

            result = client.add_entry(
                title=f"[NEWS] {title}",
                content=content,
                content_type="distilled_news",
                category="news",
                tags=tags,
            )
            entry_id = result.get("id", "") if isinstance(result, dict) else str(result)
            return entry_id or None
        except Exception as exc:
            logger.debug("Nexus store error: %s", exc)
            return None

    def _mark_article_distilled(self, url: str) -> None:
        """Set distilled=1 for an article URL in the news.db.

        Args:
            url: Article URL.
        """
        try:
            news_db = Path("data/news.db")
            if news_db.exists():
                with sqlite3.connect(str(news_db)) as conn:
                    conn.execute(
                        "UPDATE articles SET distilled=1 WHERE url=?",
                        (url,),
                    )
                    conn.commit()
        except Exception as exc:
            logger.debug("mark_distilled error: %s", exc)

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_articles_stored(self, articles: List[Dict]) -> None:
        """Called after RSS fetch stores new articles.

        Scores each article and enqueues those above the quality threshold
        for immediate distillation.

        Args:
            articles: Newly fetched article dicts.
        """
        if not articles:
            return

        now = time.time()
        queued_count = 0

        for article in articles:
            try:
                score = self._scorer.score(article, now=now)
                if score >= self.quality_threshold:
                    self._enqueue(article, score)
                    queued_count += 1
                    logger.debug(
                        "Queued article for distillation (score=%.3f): %s",
                        score,
                        article.get("title", "")[:60],
                    )
            except Exception as exc:
                logger.warning("Error scoring article for queue: %s", exc)

        if queued_count:
            logger.info(
                "on_articles_stored: queued %d/%d articles for realtime distillation",
                queued_count,
                len(articles),
            )

    def distill_article(self, article: Dict) -> Optional[str]:
        """Immediately distill a single high-quality article to Nexus.

        Scores the article, and if above threshold, adds it to an NLM notebook,
        asks the three key questions, and stores the Q&A in Nexus.

        Args:
            article: Article dict.

        Returns:
            Nexus entry ID string, or None on failure/below threshold.
        """
        now = time.time()
        score = self._scorer.score(article, now=now)

        if score < self.quality_threshold:
            logger.debug(
                "Article below threshold (%.3f < %.3f), skipping: %s",
                score,
                self.quality_threshold,
                article.get("title", "")[:60],
            )
            return None

        queue_id = self._enqueue(article, score)
        self._update_status(queue_id, "distilling")

        try:
            # Build article text source
            text_source = (
                f"Title: {article.get('title', '')}\n"
                f"Source: {article.get('source_name', '')}\n"
                f"Category: {article.get('category', '')}\n"
                f"URL: {article.get('url', '')}\n\n"
                f"{article.get('summary', '')}\n"
                f"{article.get('raw_content', '')}"
            )[:10000]  # cap at 10k chars

            # Try NLM distillation
            answers: List[str] = []
            category = article.get("category", "news")
            notebook_id = self._get_or_create_notebook(category)

            if notebook_id:
                answers = self._ask_nlm(notebook_id, text_source, _ARTICLE_QUESTIONS)
            else:
                # Fallback: generate simple summary without NLM
                summary = article.get("summary", "")
                answers = [
                    summary[:500] if summary else "No summary available.",
                    "Unable to determine implications (NLM unavailable).",
                    "Review the source article directly.",
                ]

            entry_id = self._store_in_nexus(article, answers, score)

            if entry_id:
                self._update_status(queue_id, "done", nexus_entry_id=entry_id)
                self._mark_article_distilled(article.get("url", ""))
                logger.info(
                    "Distilled article to Nexus (score=%.3f, entry=%s): %s",
                    score,
                    entry_id,
                    article.get("title", "")[:60],
                )
                return entry_id
            else:
                self._update_status(queue_id, "failed", error="Nexus store returned no ID")
                return None

        except Exception as exc:
            error_msg = str(exc)[:300]
            self._update_status(queue_id, "failed", error=error_msg)
            logger.warning(
                "Distillation failed for '%s': %s",
                article.get("title", "")[:60],
                exc,
            )
            return None

    def distill_batch(
        self,
        articles: List[Dict],
        max_concurrent: int = 3,
    ) -> List[str]:
        """Distill multiple articles concurrently.

        Uses threading for concurrent NLM calls up to ``max_concurrent``
        at a time. Only articles above the quality threshold are processed.

        Args:
            articles: List of article dicts.
            max_concurrent: Maximum concurrent distillation threads.

        Returns:
            List of Nexus entry IDs for successfully distilled articles.
        """
        if not articles:
            return []

        # Score and filter
        now = time.time()
        eligible = [
            a for a in articles
            if self._scorer.score(a, now=now) >= self.quality_threshold
        ]

        if not eligible:
            logger.debug("distill_batch: no articles above threshold %.2f", self.quality_threshold)
            return []

        results: List[Optional[str]] = [None] * len(eligible)
        semaphore = threading.Semaphore(max_concurrent)

        def _distill_one(idx: int, article: Dict) -> None:
            with semaphore:
                results[idx] = self.distill_article(article)

        threads = [
            threading.Thread(target=_distill_one, args=(i, a), daemon=True)
            for i, a in enumerate(eligible)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)  # 2-min per article max

        entry_ids = [r for r in results if r]
        logger.info(
            "distill_batch: %d/%d articles distilled to Nexus",
            len(entry_ids),
            len(eligible),
        )
        return entry_ids

    def get_distillation_queue(self) -> List[Dict]:
        """Return all pending/distilling queue entries.

        Returns:
            List of queue entry dicts.
        """
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT queue_id, url, title, category, quality_score,
                              queued_at, status
                       FROM distill_queue
                       WHERE status IN ('pending', 'distilling')
                       ORDER BY quality_score DESC, queued_at ASC""",
                ).fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.warning("get_distillation_queue error: %s", exc)
            return []

    def get_distillation_stats(self, hours: int = 24) -> Dict:
        """Return distillation statistics for the past N hours.

        Args:
            hours: Lookback window in hours.

        Returns:
            Dict with counts and averages.
        """
        try:
            cutoff = time.time() - (hours * 3600)
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT status, COUNT(*) as cnt,
                              AVG(quality_score) as avg_score
                       FROM distill_queue
                       WHERE queued_at >= ?
                       GROUP BY status""",
                    (cutoff,),
                ).fetchall()

            stats: Dict = {
                "window_hours": hours,
                "total": 0,
                "done": 0,
                "failed": 0,
                "pending": 0,
                "distilling": 0,
                "skipped": 0,
                "avg_score": 0.0,
            }
            score_sum = 0.0
            score_count = 0
            for row in rows:
                status = row["status"]
                count = row["cnt"]
                avg = row["avg_score"] or 0.0
                if status in stats:
                    stats[status] = count
                stats["total"] += count
                score_sum += avg * count
                score_count += count

            if score_count:
                stats["avg_score"] = round(score_sum / score_count, 3)
            return stats
        except Exception as exc:
            logger.warning("get_distillation_stats error: %s", exc)
            return {"error": str(exc)}

    def process_pending_queue(self, limit: int = 20) -> List[str]:
        """Process the oldest pending articles from the queue.

        This is called by the scheduler task every 30 minutes.

        Args:
            limit: Maximum articles to process in one run.

        Returns:
            List of Nexus entry IDs.
        """
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT queue_id, url, title, category, quality_score
                       FROM distill_queue
                       WHERE status='pending'
                       ORDER BY quality_score DESC, queued_at ASC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
            articles = [
                {
                    "url": row["url"],
                    "title": row["title"],
                    "category": row["category"],
                    "quality_score": row["quality_score"],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("process_pending_queue read error: %s", exc)
            return []

        return self.distill_batch(articles, max_concurrent=3)


# ── Module-level singleton ─────────────────────────────────────────────────

_distiller_instance: Optional[RealtimeDistiller] = None
_distiller_lock = threading.Lock()


def get_realtime_distiller() -> RealtimeDistiller:
    """Return the module-level RealtimeDistiller singleton.

    Returns:
        Shared RealtimeDistiller instance.
    """
    global _distiller_instance
    with _distiller_lock:
        if _distiller_instance is None:
            _distiller_instance = RealtimeDistiller()
    return _distiller_instance
