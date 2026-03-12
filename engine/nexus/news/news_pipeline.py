"""News & Intelligence Pipeline — fetch → dedup → distill → store."""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Dict, List, Optional

from engine.nexus.news.news_models import NewsDigest, NewsItem
from engine.nexus.news.dedup_filter import DedupFilter
from engine.nexus.news.rss_fetcher import RSSFetcher
from engine.nexus.news_sources import get_all_categories, get_questions
from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)

_pipeline_instance: Optional[NewsPipeline] = None


class NewsPipeline:
    """Orchestrates news fetch → dedup → Nexus storage."""

    def __init__(self) -> None:
        self._fetcher = RSSFetcher()
        self._dedup = DedupFilter()

    # ──── Fetch Stage ────

    def fetch_category(self, category: str, limit: int = 20) -> List[NewsItem]:
        """Fetch and deduplicate news for a category."""
        raw = self._fetcher.fetch_category(category, limit=limit)
        fresh = self._dedup.filter(raw)
        logger.info("fetch_category(%s): %d fresh items", category, len(fresh))
        return fresh

    def fetch_all(self) -> Dict[str, List[NewsItem]]:
        """Fetch all categories. Returns {category: [items]}."""
        results: Dict[str, List[NewsItem]] = {}
        for cat in get_all_categories():
            results[cat] = self.fetch_category(cat)
        return results

    # ──── Storage Stage ────

    def store_items_to_nexus(self, items: List[NewsItem]) -> int:
        """Store raw news items to Nexus. Returns count stored."""
        try:
            client = get_nexus_client()
        except Exception as e:
            logger.warning("Nexus unavailable, skipping storage: %s", e)
            return 0

        stored = 0
        today = datetime.utcnow().strftime("%Y-%m-%d")
        for item in items:
            try:
                content = f"**{item.title}**\n\n{item.summary}\n\nSource: {item.url}"
                client.add_entry(
                    title=f"[{item.category}] {item.title}",
                    content=content,
                    content_type="raw_news",
                    category="news",
                    tags=[today, item.category, "raw_news", item.source_name.lower().replace(" ", "_")],
                )
                stored += 1
            except Exception as e:
                logger.warning("Failed to store item '%s': %s", item.title[:50], e)

        logger.info("Stored %d/%d items to Nexus", stored, len(items))
        return stored

    def store_qa_to_nexus(self, question: str, answer: str, category: str) -> bool:
        """Store a distilled Q&A pair to Nexus."""
        try:
            client = get_nexus_client()
            today = datetime.utcnow().strftime("%Y-%m-%d")
            client.add_qa(
                question=question,
                answer=answer,
                category="news",
                tags=[today, category, "news", "distilled"],
            )
            return True
        except Exception as e:
            logger.warning("Failed to store Q&A: %s", e)
            return False

    # ──── Digest Creation ────

    def build_digest(self, items: List[NewsItem], category: str) -> NewsDigest:
        """Build a digest object from items."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        return NewsDigest(
            category=category,
            date=today,
            items=items,
        )

    def get_latest_digest(self, category: str, limit: int = 5) -> str:
        """Get latest news for a category as formatted text."""
        try:
            client = get_nexus_client()
            results = client.search(f"news {category}", category="news", limit=limit)
            if results:
                lines = [f"## Latest {category.replace('_', ' ').title()} News\n"]
                for r in results[:limit]:
                    lines.append(f"**{r.get('title', 'Unknown')}**\n{r.get('content', '')[:200]}\n")
                return "\n".join(lines)
        except Exception as e:
            logger.warning("Failed to get digest: %s", e)
        return f"No news digest available for {category}"

    # ──── Full Pipeline ────

    def run_fetch_cycle(self) -> Dict:
        """Run a full fetch + store cycle for all categories."""
        all_items = self.fetch_all()
        report: Dict = {"categories": {}, "total_items": 0, "total_stored": 0}

        for category, items in all_items.items():
            stored = self.store_items_to_nexus(items)
            report["categories"][category] = {"fetched": len(items), "stored": stored}
            report["total_items"] += len(items)
            report["total_stored"] += stored

        logger.info(
            "Fetch cycle complete: %d items, %d stored",
            report["total_items"],
            report["total_stored"],
        )
        return report


def get_news_pipeline() -> NewsPipeline:
    """Singleton accessor."""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = NewsPipeline()
    return _pipeline_instance
