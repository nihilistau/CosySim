"""RSS feed fetcher for news items."""
from __future__ import annotations
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from engine.nexus.news.news_models import NewsItem
from engine.nexus.news.source_registry import get_sources

logger = logging.getLogger(__name__)

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


def _fetch_url(url: str, timeout: int = 10) -> Optional[str]:
    try:
        req = Request(url, headers={"User-Agent": "CosySim-NewsFetcher/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None


def _parse_rss(xml_text: str, source_name: str, category: str) -> List[NewsItem]:
    items: List[NewsItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("XML parse error: %s", e)
        return items

    # Handle both RSS and Atom
    entries = root.findall(".//item") or root.findall(".//atom:entry", _NS)
    for entry in entries:
        title_el = entry.find("title")
        if title_el is None:
            title_el = entry.find("atom:title", _NS)
        link_el = entry.find("link")
        if link_el is None:
            link_el = entry.find("atom:link", _NS)
        desc_el = entry.find("description")
        if desc_el is None:
            desc_el = entry.find("atom:summary", _NS)
        if desc_el is None:
            desc_el = entry.find("summary")
        pub_el = entry.find("pubDate")
        if pub_el is None:
            pub_el = entry.find("atom:published", _NS)
        if pub_el is None:
            pub_el = entry.find("published")

        title = (title_el.text or "").strip() if title_el is not None else ""
        url = ""
        if link_el is not None:
            url = link_el.get("href", link_el.text or "").strip()
        summary = (desc_el.text or "").strip() if desc_el is not None else ""
        summary = re.sub(r"<[^>]+>", "", summary)[:500]

        pub_date = datetime.utcnow()
        if pub_el is not None and pub_el.text:
            try:
                from email.utils import parsedate_to_datetime
                pub_date = parsedate_to_datetime(pub_el.text)
            except Exception:
                pass

        if title and url:
            items.append(NewsItem(
                title=title,
                url=url,
                summary=summary,
                published_at=pub_date,
                source_name=source_name,
                category=category,
            ))
    return items


class RSSFetcher:
    """Fetches news items from RSS feeds."""

    def __init__(self, rate_limit_seconds: float = 2.0) -> None:
        self._rate_limit = rate_limit_seconds

    def fetch_category(self, category: str, limit: int = 20) -> List[NewsItem]:
        """Fetch up to `limit` items from all sources for a category."""
        sources = get_sources(category)
        all_items: List[NewsItem] = []

        for source in sources:
            xml = _fetch_url(source["rss"])
            if xml:
                items = _parse_rss(xml, source["name"], category)
                all_items.extend(items)
                logger.info("Fetched %d items from %s", len(items), source["name"])
            time.sleep(self._rate_limit)

        all_items.sort(key=lambda x: x.published_at, reverse=True)
        return all_items[:limit]
