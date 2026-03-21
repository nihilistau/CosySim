"""Extended News Intelligence Skills — 10 advanced news skills for agent use.

Pack: news_extended  |  Category: SOCIAL

Skills:
    1. get_news_feed           — Nexus-native feed query
    2. get_trending_news       — trending topics + stories
    3. get_daily_digest        — structured daily digest
    4. score_article           — score a specific article by URL
    5. get_source_health       — RSS source health report
    6. get_distillation_stats  — distillation queue statistics
    7. get_news_trends         — trend detection report
    8. mark_article_useful     — feedback signal
    9. get_interest_profile    — inferred user interests
    10. trigger_distillation   — force immediate distillation for a category
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


# ── 1. get_news_feed ──────────────────────────────────────────────────────────

@skill(
    pack="news_extended",
    description="Get a curated news feed from Nexus, filtered by category and time window",
    category="SOCIAL",
    tags=["news", "feed", "nexus", "curated"],
)
def get_news_feed(
    category: str = "",
    hours: int = 24,
    limit: int = 20,
    min_score: float = 0.4,
) -> str:
    """Return a curated news feed from the Nexus-native feed system.

    Args:
        category: Optional category filter (e.g., "ai_ml", "security").
            Leave empty for all categories.
        hours: How many hours back to look for articles.
        limit: Maximum number of articles to return.
        min_score: Minimum article quality score (0.0–1.0).

    Returns:
        JSON string with feed items or an error message.
    """
    try:
        from engine.nexus.news.nexus_feed import get_nexus_feed
        feed = get_nexus_feed()
        items = feed.get_feed(
            category=category,
            limit=limit,
            since_hours=hours,
            min_score=min_score,
        )
        return json.dumps({
            "count": len(items),
            "category": category or "all",
            "hours": hours,
            "items": [item.to_dict() for item in items],
        }, indent=2)
    except Exception as exc:
        logger.warning("get_news_feed error: %s", exc)
        return json.dumps({"error": str(exc), "items": []})


# ── 2. get_trending_news ──────────────────────────────────────────────────────

@skill(
    pack="news_extended",
    description="Get currently trending news topics and stories based on article velocity",
    category="SOCIAL",
    tags=["news", "trending", "velocity", "topics"],
)
def get_trending_news(limit: int = 10) -> str:
    """Return trending news topics with article velocity and story clusters.

    Args:
        limit: Maximum number of trending topics to return.

    Returns:
        JSON string with trending topics and story summaries.
    """
    try:
        from engine.nexus.news.nexus_feed import get_nexus_feed
        feed = get_nexus_feed()
        items = feed.get_trending_feed(limit=limit)

        from engine.nexus.news.trend_detector import get_trend_detector
        detector = get_trend_detector()
        trending_topics = detector.get_trending_topics(limit=limit)

        return json.dumps({
            "count": len(items),
            "trending_items": [item.to_dict() for item in items],
            "trending_topics": trending_topics,
        }, indent=2)
    except Exception as exc:
        logger.warning("get_trending_news error: %s", exc)
        return json.dumps({"error": str(exc), "trending_items": [], "trending_topics": []})


# ── 3. get_daily_digest ───────────────────────────────────────────────────────

@skill(
    pack="news_extended",
    description="Get a structured daily news digest with top stories, trends, and category breakdown",
    category="SOCIAL",
    tags=["news", "digest", "daily", "summary"],
)
def get_daily_digest() -> str:
    """Return a structured daily news digest.

    Includes top stories from the last 24 hours, trending topics,
    and a breakdown by category.

    Returns:
        JSON string with digest structure.
    """
    try:
        from engine.nexus.news.nexus_feed import get_nexus_feed
        feed = get_nexus_feed()
        digest = feed.get_daily_digest()
        return json.dumps(digest, indent=2)
    except Exception as exc:
        logger.warning("get_daily_digest error: %s", exc)
        return json.dumps({"error": str(exc)})


# ── 4. score_article ──────────────────────────────────────────────────────────

@skill(
    pack="news_extended",
    description="Score a news article by URL for quality, recency, and relevance",
    category="SOCIAL",
    tags=["news", "quality", "scoring", "article"],
)
def score_article(url: str, title: str = "", category: str = "") -> str:
    """Score a specific news article for quality and relevance.

    Args:
        url: The article URL to score.
        title: Optional article title (improves scoring accuracy).
        category: Optional article category.

    Returns:
        JSON string with quality score and sub-score breakdown.
    """
    try:
        from engine.nexus.news.article_scorer import get_article_scorer
        scorer = get_article_scorer()
        article = {"url": url, "title": title, "category": category}
        breakdown = scorer.score_detailed(article)
        return json.dumps({
            "url": url,
            "total_score": breakdown.total,
            "breakdown": {
                "length": breakdown.length,
                "reputation": breakdown.reputation,
                "recency": breakdown.recency,
                "title_quality": breakdown.title,
                "category_relevance": breakdown.category,
                "novelty": breakdown.novelty,
            },
        }, indent=2)
    except Exception as exc:
        logger.warning("score_article error: %s", exc)
        return json.dumps({"error": str(exc), "url": url})


# ── 5. get_source_health ──────────────────────────────────────────────────────

@skill(
    pack="news_extended",
    description="Get a health report for all configured RSS news sources",
    category="SOCIAL",
    tags=["news", "sources", "health", "rss", "monitoring"],
    cost=1.0,
)
def get_source_health() -> str:
    """Return a health report for all configured RSS news sources.

    Shows UP/DOWN/SLOW/FLAKY status, consecutive failures,
    and average response times.

    Returns:
        JSON string with source health report.
    """
    try:
        from engine.nexus.news.source_monitor import get_source_health_monitor
        monitor = get_source_health_monitor()
        report = monitor.get_health_report()
        return json.dumps(report, indent=2)
    except Exception as exc:
        logger.warning("get_source_health error: %s", exc)
        return json.dumps({"error": str(exc)})


# ── 6. get_distillation_stats ─────────────────────────────────────────────────

@skill(
    pack="news_extended",
    description="Get statistics about the NLM distillation queue for the past N hours",
    category="SOCIAL",
    tags=["news", "distillation", "stats", "nlm", "queue"],
)
def get_distillation_stats(hours: int = 24) -> str:
    """Return distillation queue statistics for the past N hours.

    Shows total articles processed, success/failure counts,
    and average quality scores.

    Args:
        hours: How many hours back to include in statistics.

    Returns:
        JSON string with distillation statistics.
    """
    try:
        from engine.nexus.news.realtime_distiller import get_realtime_distiller
        distiller = get_realtime_distiller()
        stats = distiller.get_distillation_stats(hours=hours)
        queue = distiller.get_distillation_queue()
        stats["pending_in_queue"] = len(queue)
        return json.dumps(stats, indent=2)
    except Exception as exc:
        logger.warning("get_distillation_stats error: %s", exc)
        return json.dumps({"error": str(exc)})


# ── 7. get_news_trends ────────────────────────────────────────────────────────

@skill(
    pack="news_extended",
    description="Run trend detection on recent news articles and return a trend report",
    category="SOCIAL",
    tags=["news", "trends", "detection", "analysis"],
    cost=1.5,
)
def get_news_trends(window_hours: int = 24, limit: int = 10) -> str:
    """Detect and return trending topics from recent news articles.

    Fetches recent articles from Nexus, runs TF-IDF based keyword
    clustering, and reports trending stories with velocity scores.

    Args:
        window_hours: Time window for trend detection (hours).
        limit: Maximum trending topics to return.

    Returns:
        JSON string with trend report.
    """
    try:
        from engine.nexus.news.trend_detector import get_trend_detector
        from engine.nexus.client import get_nexus_client

        # Fetch recent articles from Nexus
        client = get_nexus_client()
        results = client.search("news", category="news", limit=100)

        articles = []
        import time
        now = time.time()
        cutoff = now - (window_hours * 3600)
        for r in (results or []):
            created = r.get("created_at")
            ts = now
            if created:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                    ts = dt.timestamp()
                except Exception:
                    logger.debug("Failed to parse created_at timestamp %r", created, exc_info=True)
            if ts >= cutoff:
                articles.append({
                    "title": r.get("title", ""),
                    "summary": r.get("content", "")[:500],
                    "category": "",
                    "published_at": ts,
                })

        detector = get_trend_detector()
        report = detector.get_trend_report_dict(
            articles=articles,
            window_hours=window_hours,
            limit=limit,
        )
        return json.dumps(report, indent=2)
    except Exception as exc:
        logger.warning("get_news_trends error: %s", exc)
        return json.dumps({"error": str(exc), "trending_topics": []})


# ── 8. mark_article_useful ────────────────────────────────────────────────────

@skill(
    pack="news_extended",
    description="Record a usefulness feedback signal for a news article",
    category="SOCIAL",
    tags=["news", "feedback", "personalization", "useful"],
)
def mark_article_useful(article_id: str, useful: bool = True) -> str:
    """Record a usefulness feedback signal for a news article.

    This signal is used to infer user interests and personalise
    future feed results.

    Args:
        article_id: The article identifier from the feed.
        useful: True if useful, False if not useful.

    Returns:
        JSON string confirming the feedback was recorded.
    """
    try:
        from engine.nexus.news.nexus_feed import get_nexus_feed
        feed = get_nexus_feed()
        feed.mark_useful(article_id, useful=useful)
        return json.dumps({
            "article_id": article_id,
            "feedback": "useful" if useful else "not_useful",
            "recorded": True,
        })
    except Exception as exc:
        logger.warning("mark_article_useful error: %s", exc)
        return json.dumps({"error": str(exc), "recorded": False})


# ── 9. get_interest_profile ───────────────────────────────────────────────────

@skill(
    pack="news_extended",
    description="Get the inferred user interest profile based on article reading and feedback history",
    category="SOCIAL",
    tags=["news", "interests", "personalization", "profile"],
)
def get_interest_profile() -> str:
    """Return the inferred user interest profile.

    Based on read history and useful/not-useful feedback signals.
    Shows top categories and keywords the user engages with.

    Returns:
        JSON string with interest profile.
    """
    try:
        from engine.nexus.news.nexus_feed import get_nexus_feed
        feed = get_nexus_feed()
        profile = feed.get_interest_profile()
        return json.dumps(profile, indent=2)
    except Exception as exc:
        logger.warning("get_interest_profile error: %s", exc)
        return json.dumps({"error": str(exc)})


# ── 10. trigger_distillation ──────────────────────────────────────────────────

@skill(
    pack="news_extended",
    description="Force immediate NLM distillation for all pending articles in a category",
    category="SOCIAL",
    tags=["news", "distillation", "nlm", "trigger", "force"],
    cost=3.0,
)
def trigger_distillation(category: str = "") -> str:
    """Force immediate distillation of pending high-quality articles.

    Processes the distillation queue immediately rather than waiting
    for the next scheduled run. Optionally filtered by category.

    Args:
        category: Optional category filter (empty = all pending).

    Returns:
        JSON string with distillation results.
    """
    try:
        from engine.nexus.news.realtime_distiller import get_realtime_distiller
        distiller = get_realtime_distiller()

        # If category specified, fetch and distill that category directly
        if category:
            from engine.nexus.news_sources import get_news_registry
            registry = get_news_registry()
            articles_raw = registry.fetch_all(category=category)
            articles = [
                {
                    "url": a.url,
                    "title": a.title,
                    "summary": a.summary,
                    "category": a.category,
                    "source_name": a.source_id,
                    "published_at": a.fetched_at,
                }
                for a in articles_raw
            ]
            entry_ids = distiller.distill_batch(articles, max_concurrent=3)
        else:
            # Process the existing pending queue
            entry_ids = distiller.process_pending_queue(limit=20)

        stats = distiller.get_distillation_stats(hours=1)
        return json.dumps({
            "category": category or "all",
            "distilled_count": len(entry_ids),
            "nexus_entry_ids": entry_ids,
            "queue_stats": stats,
        }, indent=2)
    except Exception as exc:
        logger.warning("trigger_distillation error: %s", exc)
        return json.dumps({"error": str(exc), "distilled_count": 0})
