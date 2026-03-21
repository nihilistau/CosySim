"""News Intelligence Scheduler Tasks — v1.43.

Registers 5 scheduled tasks into the CosySim task scheduler:

    news-quality-score    every_1h   — refresh quality scores for recent articles
    news-trend-detect     every_2h   — run trend detection on recent articles
    news-source-health    every_6h   — probe RSS source health
    news-realtime-distill every_30m  — flush the NLM distillation queue
    news-daily-digest     daily      — build and store daily digest in Nexus
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from engine.nexus.scheduler_daemon import TaskSchedulerDaemon

logger = logging.getLogger(__name__)


# ── Callbacks ─────────────────────────────────────────────────────────────────

def _news_quality_score_callback() -> Dict[str, Any]:
    """Refresh quality scores for articles fetched in the past hour."""
    try:
        from engine.nexus.news.article_scorer import get_article_scorer
        scorer = get_article_scorer()
        count = scorer.refresh_recent_titles(hours=2)
        return {"status": "ok", "articles_scored": count}
    except Exception as exc:
        logger.error("news-quality-score task failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _news_trend_detect_callback() -> Dict[str, Any]:
    """Run keyword-based trend detection on articles from the past 2 hours."""
    try:
        from engine.nexus.news.trend_detector import get_trend_detector
        from engine.nexus.news_sources import get_news_registry

        registry = get_news_registry()
        raw = registry.fetch_all()
        articles = [
            {
                "title": a.title,
                "summary": a.summary or "",
                "category": a.category,
                "published_at": a.fetched_at,
            }
            for a in raw
        ]
        detector = get_trend_detector()
        report = detector.detect_trends(articles=articles, window_hours=2)
        detector.persist_trends(report)
        return {
            "status": "ok",
            "trending_topics": len(report.trending_topics),
            "emerging_stories": len(report.emerging_stories),
        }
    except Exception as exc:
        logger.error("news-trend-detect task failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _news_source_health_callback() -> Dict[str, Any]:
    """Probe all RSS source URLs and update health records."""
    try:
        from engine.nexus.news.source_monitor import get_source_health_monitor
        monitor = get_source_health_monitor()
        results = monitor.check_all_sources()
        up = sum(1 for r in results if r.status == "UP")
        down = sum(1 for r in results if r.status == "DOWN")
        slow = sum(1 for r in results if r.status == "SLOW")
        return {
            "status": "ok",
            "total": len(results),
            "up": up,
            "down": down,
            "slow": slow,
        }
    except Exception as exc:
        logger.error("news-source-health task failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _news_realtime_distill_callback() -> Dict[str, Any]:
    """Flush the NLM distillation queue — process up to 20 pending articles."""
    try:
        from engine.nexus.news.realtime_distiller import get_realtime_distiller
        distiller = get_realtime_distiller()
        t0 = time.monotonic()
        entry_ids = distiller.process_pending_queue(limit=20)
        elapsed = round(time.monotonic() - t0, 2)
        return {
            "status": "ok",
            "distilled": len(entry_ids),
            "nexus_entries": entry_ids,
            "duration_seconds": elapsed,
        }
    except Exception as exc:
        logger.error("news-realtime-distill task failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _news_daily_digest_callback() -> Dict[str, Any]:
    """Build the daily news digest and store it in the Nexus knowledge base."""
    try:
        from engine.nexus.news.nexus_feed import get_nexus_feed
        feed = get_nexus_feed()
        digest = feed.get_daily_digest(top_n=10)

        # Store digest summary in Nexus
        stored_id: str | None = None
        try:
            stored_id = feed.sync_to_nexus(limit=10)
        except Exception as sync_exc:
            logger.warning("news-daily-digest Nexus sync failed: %s", sync_exc)

        return {
            "status": "ok",
            "date": digest.get("date"),
            "top_articles": len(digest.get("articles", [])),
            "categories": list(digest.get("by_category", {}).keys()),
            "nexus_entry": stored_id,
        }
    except Exception as exc:
        logger.error("news-daily-digest task failed: %s", exc)
        return {"status": "error", "error": str(exc)}


# ── Registration ──────────────────────────────────────────────────────────────

def register_news_intelligence_tasks(daemon: "TaskSchedulerDaemon") -> None:
    """Register all 5 v1.43 News Intelligence tasks into the scheduler."""
    daemon.register(
        "news-quality-score",
        "Refresh recent article quality scores",
        "every_1h",
        _news_quality_score_callback,
    )
    daemon.register(
        "news-trend-detect",
        "Detect trending news topics (2h window)",
        "every_2h",
        _news_trend_detect_callback,
    )
    daemon.register(
        "news-source-health",
        "Probe RSS source health and update records",
        "every_6h",
        _news_source_health_callback,
    )
    daemon.register(
        "news-realtime-distill",
        "Flush NLM distillation queue for high-quality articles",
        "every_30m",
        _news_realtime_distill_callback,
    )
    daemon.register(
        "news-daily-digest",
        "Build and store daily news digest in Nexus",
        "daily",
        _news_daily_digest_callback,
    )
    logger.debug("NewsIntelligence: 5 scheduler tasks registered")
