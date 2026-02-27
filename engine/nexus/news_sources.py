"""News source registry for the CosySim intelligence system.

Fetches, filters, and scores news articles from configured sources
(Hacker News API, RSS feeds, web scraping) and stores them via Nexus.

Usage:
    from engine.nexus.news_sources import get_news_registry
    registry = get_news_registry()

    articles = registry.fetch_all()
    filtered = registry.filter_articles(articles)
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_registry_instance: Optional[NewsSourceRegistry] = None
_registry_lock = threading.Lock()

REQUEST_TIMEOUT = 20
USER_AGENT = "CosySim-News/1.0"


# ──── Data Classes ────────────────────────────────────────────────────────

@dataclass
class NewsSource:
    """A configured news source."""

    id: str = ""
    name: str = ""
    type: str = ""  # api | rss | web_scrape
    url: str = ""
    category: str = ""
    enabled: bool = True
    quality_score: float = 0.5
    max_items: int = 10
    last_fetched: Optional[float] = None
    fetch_count: int = 0
    error_count: int = 0


@dataclass
class NewsArticle:
    """A fetched news article."""

    source_id: str = ""
    title: str = ""
    url: str = ""
    summary: str = ""
    score: float = 0.0
    published_at: str = ""
    category: str = ""
    keywords: List[str] = field(default_factory=list)
    fetched_at: float = field(default_factory=time.time)


# ──── Registry ────────────────────────────────────────────────────────────

class NewsSourceRegistry:
    """Thread-safe registry that loads, manages, and fetches news sources."""

    def __init__(self) -> None:
        self._sources: Dict[str, NewsSource] = {}
        self._config: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self.load_sources()

    # ──── Source Management ───────────────────────────────────────────────

    def load_sources(self) -> int:
        """Load or reload sources from config/news_sources.yaml.

        Returns:
            Number of sources loaded.
        """
        try:
            from engine.config import get_config
            cfg = get_config()
            news_cfg = cfg.get("news", {})
        except Exception:
            news_cfg = self._load_yaml_fallback()

        if not news_cfg:
            news_cfg = self._load_yaml_fallback()

        with self._lock:
            self._config = news_cfg or {}
            self._sources.clear()
            for src_data in self._config.get("sources", []):
                source = NewsSource(
                    id=src_data.get("id", ""),
                    name=src_data.get("name", ""),
                    type=src_data.get("type", ""),
                    url=src_data.get("url", ""),
                    category=src_data.get("category", ""),
                    enabled=src_data.get("enabled", True),
                    quality_score=src_data.get("quality_score", 0.5),
                    max_items=src_data.get("max_items", 10),
                )
                self._sources[source.id] = source
            count = len(self._sources)
        logger.info("Loaded %d news sources", count)
        return count

    @staticmethod
    def _load_yaml_fallback() -> Dict[str, Any]:
        """Load news_sources.yaml directly as fallback when ConfigManager
        does not include the news key."""
        try:
            import yaml
            config_path = Path(__file__).resolve().parents[2] / "config" / "news_sources.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                return data.get("news", data)
        except Exception as exc:
            logger.warning("Fallback YAML load failed: %s", exc)
        return {}

    def list_sources(
        self, category: Optional[str] = None, enabled_only: bool = True
    ) -> List[NewsSource]:
        """Return sources, optionally filtered by category and enabled flag.

        Args:
            category: Filter to this category (None = all).
            enabled_only: If True, return only enabled sources.

        Returns:
            List of matching NewsSource objects.
        """
        with self._lock:
            result: List[NewsSource] = []
            for src in self._sources.values():
                if enabled_only and not src.enabled:
                    continue
                if category and src.category != category:
                    continue
                result.append(src)
        return result

    def get_source(self, source_id: str) -> Optional[NewsSource]:
        """Get a single source by ID.

        Args:
            source_id: The source identifier.

        Returns:
            NewsSource or None if not found.
        """
        with self._lock:
            return self._sources.get(source_id)

    def add_source(self, source: NewsSource) -> bool:
        """Add a source at runtime.

        Args:
            source: NewsSource to add.

        Returns:
            True if added, False if ID already exists.
        """
        with self._lock:
            if source.id in self._sources:
                return False
            self._sources[source.id] = source
        logger.info("Added news source: %s", source.id)
        return True

    def remove_source(self, source_id: str) -> bool:
        """Remove a source by ID.

        Args:
            source_id: The source identifier.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            if source_id not in self._sources:
                return False
            del self._sources[source_id]
        logger.info("Removed news source: %s", source_id)
        return True

    # ──── Fetching ────────────────────────────────────────────────────────

    def fetch_source(self, source_id: str) -> List[NewsArticle]:
        """Fetch articles from a single source.

        Args:
            source_id: The source identifier.

        Returns:
            List of fetched NewsArticle objects.
        """
        source = self.get_source(source_id)
        if not source:
            logger.warning("Source not found: %s", source_id)
            return []
        return self._dispatch_fetch(source)

    def fetch_all(self, category: Optional[str] = None) -> List[NewsArticle]:
        """Fetch articles from all enabled sources.

        Args:
            category: Optional category filter.

        Returns:
            Combined list of NewsArticle objects.
        """
        sources = self.list_sources(category=category, enabled_only=True)
        articles: List[NewsArticle] = []
        for source in sources:
            try:
                articles.extend(self._dispatch_fetch(source))
            except Exception as exc:
                logger.error("Fetch failed for %s: %s", source.id, exc)
                with self._lock:
                    source.error_count += 1
        return articles

    def _dispatch_fetch(self, source: NewsSource) -> List[NewsArticle]:
        """Route fetch to the correct handler based on source type."""
        fetchers = {
            "api": self._fetch_hn,
            "rss": self._fetch_rss,
            "web_scrape": self._fetch_web,
        }
        fetcher = fetchers.get(source.type)
        if not fetcher:
            logger.warning("Unknown source type: %s", source.type)
            return []
        try:
            articles = fetcher(source)
            with self._lock:
                source.last_fetched = time.time()
                source.fetch_count += 1
            return articles
        except Exception as exc:
            logger.error("Error fetching %s: %s", source.id, exc)
            with self._lock:
                source.error_count += 1
            return []

    def _fetch_hn(self, source: NewsSource) -> List[NewsArticle]:
        """Fetch articles from Hacker News API.

        Args:
            source: The HN source definition.

        Returns:
            List of NewsArticle objects.
        """
        story_ids = self._http_get_json(source.url)
        if not isinstance(story_ids, list):
            return []

        articles: List[NewsArticle] = []
        for story_id in story_ids[: source.max_items]:
            detail_url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            item = self._http_get_json(detail_url)
            if not isinstance(item, dict):
                continue
            articles.append(NewsArticle(
                source_id=source.id,
                title=item.get("title", ""),
                url=item.get("url", ""),
                summary="",
                score=float(item.get("score", 0)),
                published_at=str(item.get("time", "")),
                category=source.category,
            ))
        return articles

    def _fetch_rss(self, source: NewsSource) -> List[NewsArticle]:
        """Fetch articles from an RSS/Atom feed using xml.etree.

        Args:
            source: The RSS source definition.

        Returns:
            List of NewsArticle objects.
        """
        raw = self._http_get_text(source.url)
        if not raw:
            return []

        articles: List[NewsArticle] = []
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            logger.warning("RSS parse error for %s: %s", source.id, exc)
            return []

        # Handle both RSS <item> and Atom <entry>
        items = root.findall(".//item")
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//atom:entry", ns)

        for item in items[: source.max_items]:
            title = self._xml_text(item, "title")
            link = self._xml_text(item, "link")
            if not link:
                link_el = item.find("{http://www.w3.org/2005/Atom}link")
                if link_el is not None:
                    link = link_el.get("href", "")
            description = self._xml_text(item, "description")
            pub_date = self._xml_text(item, "pubDate") or self._xml_text(item, "published")
            articles.append(NewsArticle(
                source_id=source.id,
                title=title,
                url=link,
                summary=description[:500] if description else "",
                category=source.category,
                published_at=pub_date,
            ))
        return articles

    def _fetch_web(self, source: NewsSource) -> List[NewsArticle]:
        """Basic web scraping — extract links and titles from HTML.

        Args:
            source: The web scrape source definition.

        Returns:
            List of NewsArticle objects.
        """
        raw = self._http_get_text(source.url)
        if not raw:
            return []

        articles: List[NewsArticle] = []
        # Simple regex-based link extraction (no bs4 dependency)
        import re
        pattern = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
        seen_urls: set = set()
        for match in pattern.finditer(raw):
            href, text = match.group(1), match.group(2)
            # Strip HTML tags from link text
            clean_text = re.sub(r"<[^>]+>", "", text).strip()
            if not clean_text or not href or href in seen_urls:
                continue
            seen_urls.add(href)
            articles.append(NewsArticle(
                source_id=source.id,
                title=clean_text,
                url=href,
                category=source.category,
            ))
            if len(articles) >= source.max_items:
                break
        return articles

    # ──── Filtering & Scoring ─────────────────────────────────────────────

    def filter_articles(
        self, articles: List[NewsArticle], keywords: Optional[List[str]] = None
    ) -> List[NewsArticle]:
        """Filter articles by keyword inclusion/exclusion.

        Args:
            articles: Articles to filter.
            keywords: Override include keywords (None uses config).

        Returns:
            Filtered list of articles.
        """
        filters = self._config.get("keyword_filters", {})
        include_kw = keywords or filters.get("include", [])
        exclude_kw = filters.get("exclude", [])

        result: List[NewsArticle] = []
        for article in articles:
            text = f"{article.title} {article.summary}".lower()
            if exclude_kw and any(kw.lower() in text for kw in exclude_kw):
                continue
            if include_kw and not any(kw.lower() in text for kw in include_kw):
                continue
            result.append(article)
        return result

    def score_relevance(self, article: NewsArticle) -> float:
        """Score an article's relevance based on keyword matches.

        Args:
            article: The article to score.

        Returns:
            Relevance score between 0.0 and 1.0.
        """
        filters = self._config.get("keyword_filters", {})
        include_kw = filters.get("include", [])
        if not include_kw:
            return 0.5

        text = f"{article.title} {article.summary}".lower()
        matches = sum(1 for kw in include_kw if kw.lower() in text)
        source = self.get_source(article.source_id)
        quality = source.quality_score if source else 0.5

        raw_score = (matches / len(include_kw)) * quality
        return min(1.0, raw_score + (article.score / 1000.0 if article.score else 0.0))

    # ──── Config & Stats ──────────────────────────────────────────────────

    def get_config(self) -> Dict[str, Any]:
        """Return the current news configuration dict.

        Returns:
            News config dictionary.
        """
        with self._lock:
            return dict(self._config)

    def stats(self) -> Dict[str, Any]:
        """Return fetch counts and error rates per source.

        Returns:
            Dict with per-source statistics.
        """
        with self._lock:
            source_stats = {}
            for sid, src in self._sources.items():
                source_stats[sid] = {
                    "name": src.name,
                    "fetch_count": src.fetch_count,
                    "error_count": src.error_count,
                    "last_fetched": src.last_fetched,
                    "enabled": src.enabled,
                }
            return {
                "total_sources": len(self._sources),
                "enabled_sources": sum(1 for s in self._sources.values() if s.enabled),
                "sources": source_stats,
            }

    # ──── Nexus Storage ─────────────────────────────────────────────────

    def store_to_nexus(
        self, articles: List[NewsArticle], max_store: int = 30
    ) -> int:
        """Store filtered articles in Nexus with URL-based deduplication.

        Args:
            articles: Articles to store (already filtered and scored).
            max_store: Maximum articles to store per call.

        Returns:
            Number of articles successfully stored.
        """
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
        except Exception as exc:
            logger.warning("Cannot store news — Nexus unavailable: %s", exc)
            return 0

        stored = 0
        for article in articles[:max_store]:
            if not article.title:
                continue

            # Dedup by URL
            if article.url:
                try:
                    existing = client.search(article.url, limit=1)
                    if existing and any(article.url in str(e) for e in existing):
                        continue
                except Exception:
                    pass

            content = (
                f"**{article.title}**\n\n"
                f"Source: {article.source_id}\n"
                f"URL: {article.url}\n"
                f"Published: {article.published_at}\n"
                f"Relevance: {article.score:.2f}\n\n"
                f"{article.summary}"
            )

            try:
                client.add_entry(
                    title=f"News: {article.title[:80]}",
                    content=content,
                    content_type="note",
                    category=article.category or "news",
                    tags=["news", article.source_id] + article.keywords,
                )
                stored += 1
            except Exception as exc:
                logger.debug("Failed to store article '%s': %s", article.title, exc)

        if stored:
            logger.info("Stored %d news articles in Nexus", stored)
        return stored

    def generate_digest(
        self, articles: List[NewsArticle], max_articles: int = 20
    ) -> str:
        """Generate a markdown daily digest from top articles.

        Args:
            articles: Scored and sorted articles.
            max_articles: Maximum articles in digest.

        Returns:
            Markdown digest string.
        """
        if not articles:
            return "No articles today."

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"# Daily News Digest — {now_str}\n"]

        by_category: Dict[str, List[NewsArticle]] = defaultdict(list)
        for a in articles[:max_articles]:
            by_category[a.category or "general"].append(a)

        for cat, arts in sorted(by_category.items()):
            lines.append(f"\n## {cat.replace('_', ' ').title()}\n")
            for art in arts[:10]:
                lines.append(f"- **{art.title}**")
                if art.url:
                    lines.append(f"  [{art.url}]({art.url})")
                if art.summary:
                    lines.append(f"  {art.summary[:200]}")
                if art.score > 0:
                    lines.append(f"  Relevance: {art.score:.2f}")

        lines.append(f"\n---\n*Generated by CosySim News Engine*")
        return "\n".join(lines)

    # ──── HTTP Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _http_get_json(url: str) -> Any:
        """Fetch URL and parse JSON response.

        Args:
            url: The URL to fetch.

        Returns:
            Parsed JSON (list or dict), or None on error.
        """
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("HTTP JSON fetch failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _http_get_text(url: str) -> str:
        """Fetch URL and return text content.

        Args:
            url: The URL to fetch.

        Returns:
            Response text, or empty string on error.
        """
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning("HTTP text fetch failed for %s: %s", url, exc)
            return ""

    @staticmethod
    def _xml_text(element: ET.Element, tag: str) -> str:
        """Extract text from an XML child element.

        Args:
            element: Parent XML element.
            tag: Child tag name.

        Returns:
            Text content or empty string.
        """
        child = element.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return ""


# ──── Singleton ───────────────────────────────────────────────────────────

def get_news_registry() -> NewsSourceRegistry:
    """Get or create the singleton NewsSourceRegistry.

    Returns:
        NewsSourceRegistry instance.
    """
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = NewsSourceRegistry()
    return _registry_instance
