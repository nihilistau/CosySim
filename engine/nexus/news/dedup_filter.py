"""Deduplication filter for news items using fingerprint hashing."""
from __future__ import annotations
import hashlib
import logging
from typing import List, Set

from engine.nexus.news.news_models import NewsItem

logger = logging.getLogger(__name__)


def _fingerprint(item: NewsItem) -> str:
    """URL + normalised title hash."""
    key = item.url + item.title.lower().strip()
    return hashlib.md5(key.encode()).hexdigest()[:16]


class DedupFilter:
    """Deduplicates news items using fingerprint set."""

    def __init__(self) -> None:
        self._seen: Set[str] = set()

    def filter(self, items: List[NewsItem]) -> List[NewsItem]:
        """Return only unseen items; updates internal seen set."""
        fresh = []
        for item in items:
            fp = _fingerprint(item)
            item.fingerprint = fp
            if fp not in self._seen:
                self._seen.add(fp)
                fresh.append(item)
        logger.info("DedupFilter: %d/%d items are fresh", len(fresh), len(items))
        return fresh

    def mark_seen(self, fingerprints: List[str]) -> None:
        """Pre-seed seen set from Nexus persistence."""
        self._seen.update(fingerprints)

    def get_seen_fingerprints(self) -> List[str]:
        return list(self._seen)
