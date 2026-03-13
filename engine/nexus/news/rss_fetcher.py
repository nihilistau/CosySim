"""RSS feed fetcher with retry, circuit-breaker, and per-source error tracking.

Each source URL has an error counter.  After ``MAX_CONSECUTIVE_FAILURES``
consecutive failures the source is *tripped* (circuit open) and skipped
for ``CIRCUIT_RESET_SECONDS``.  Transient failures use exponential back-off
with up to ``MAX_RETRIES`` attempts.

Metrics are emitted via :pymod:`engine.nexus.meta_metrics` when available.
"""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from engine.nexus.news.news_models import NewsItem
from engine.nexus.news_sources import get_sources

logger = logging.getLogger(__name__)

# ── Config defaults (can be overridden via constructor) ─────────────
MAX_RETRIES = 3
BACKOFF_BASE_S = 1.0  # 1s, 2s, 4s
MAX_CONSECUTIVE_FAILURES = 5
CIRCUIT_RESET_SECONDS = 3600  # 1 hour
DEFAULT_TIMEOUT = 10

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


# ── Source health tracker ───────────────────────────────────────────

class _SourceHealth:
    """Tracks per-source error state for circuit-breaker logic."""

    __slots__ = (
        "error_count",
        "consecutive_failures",
        "last_error",
        "last_failure_ts",
        "total_successes",
    )

    def __init__(self) -> None:
        self.error_count: int = 0
        self.consecutive_failures: int = 0
        self.last_error: str = ""
        self.last_failure_ts: float = 0.0
        self.total_successes: int = 0

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.total_successes += 1

    def record_failure(self, error: str) -> None:
        self.error_count += 1
        self.consecutive_failures += 1
        self.last_error = error
        self.last_failure_ts = time.time()

    def is_tripped(self, max_failures: int, reset_seconds: float) -> bool:
        """True if circuit is open (source should be skipped)."""
        if self.consecutive_failures < max_failures:
            return False
        elapsed = time.time() - self.last_failure_ts
        if elapsed >= reset_seconds:
            # Auto-reset after cool-down
            self.consecutive_failures = 0
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_count": self.error_count,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "total_successes": self.total_successes,
        }


# ── URL fetcher with retry ─────────────────────────────────────────

def _fetch_url(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    backoff_base: float = BACKOFF_BASE_S,
) -> Optional[str]:
    """Fetch a URL with exponential back-off retries."""
    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            req = Request(url, headers={"User-Agent": "CosySim-NewsFetcher/1.0"})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (URLError, OSError) as exc:
            last_err = exc
            if attempt < max_retries:
                delay = backoff_base * (2 ** (attempt - 1))
                logger.debug(
                    "Retry %d/%d for %s (%.1fs delay): %s",
                    attempt, max_retries, url, delay, exc,
                )
                time.sleep(delay)
    logger.warning("Failed to fetch %s after %d attempts: %s", url, max_retries, last_err)
    return None


# ── RSS / Atom parser ───────────────────────────────────────────────

def _parse_rss(xml_text: str, source_name: str, category: str) -> List[NewsItem]:
    items: List[NewsItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("XML parse error: %s", exc)
        return items

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

        pub_date = datetime.now(timezone.utc)
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


# ── RSSFetcher ──────────────────────────────────────────────────────

class RSSFetcher:
    """Fetches news items from RSS feeds with retry and circuit-breaker.

    Args:
        rate_limit_seconds: Minimum pause between consecutive source fetches.
        timeout: HTTP request timeout in seconds.
        max_retries: Maximum retry attempts per URL.
        max_consecutive_failures: Failures before a source is tripped.
        circuit_reset_seconds: Seconds before a tripped source auto-resets.
    """

    def __init__(
        self,
        rate_limit_seconds: float = 2.0,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES,
        circuit_reset_seconds: float = CIRCUIT_RESET_SECONDS,
    ) -> None:
        self._rate_limit = rate_limit_seconds
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_failures = max_consecutive_failures
        self._circuit_reset = circuit_reset_seconds
        self._health: Dict[str, _SourceHealth] = {}

    def _get_health(self, source_url: str) -> _SourceHealth:
        if source_url not in self._health:
            self._health[source_url] = _SourceHealth()
        return self._health[source_url]

    def get_source_health(self) -> Dict[str, Dict[str, Any]]:
        """Return health summary for all known sources."""
        return {url: h.to_dict() for url, h in self._health.items()}

    def fetch_category(self, category: str, limit: int = 20) -> List[NewsItem]:
        """Fetch up to *limit* items from all sources for *category*.

        Sources that are tripped (circuit-breaker open) are skipped.
        """
        sources = get_sources(category)
        all_items: List[NewsItem] = []
        metrics: Dict[str, int] = {"success": 0, "failure": 0, "skipped": 0}

        for source in sources:
            url = source["rss"]
            health = self._get_health(url)

            # Circuit-breaker check
            if health.is_tripped(self._max_failures, self._circuit_reset):
                logger.info(
                    "Skipping tripped source %s (%d consecutive failures)",
                    source["name"], health.consecutive_failures,
                )
                metrics["skipped"] += 1
                continue

            t0 = time.time()
            xml = _fetch_url(
                url,
                timeout=self._timeout,
                max_retries=self._max_retries,
            )
            latency_ms = (time.time() - t0) * 1000

            if xml:
                items = _parse_rss(xml, source["name"], category)
                all_items.extend(items)
                health.record_success()
                metrics["success"] += 1
                logger.info(
                    "Fetched %d items from %s (%.0fms)",
                    len(items), source["name"], latency_ms,
                )
            else:
                health.record_failure(f"Fetch failed after retries ({category})")
                metrics["failure"] += 1
                logger.warning(
                    "Source %s failed (%d consecutive)",
                    source["name"], health.consecutive_failures,
                )

            # Record metrics if available
            try:
                from engine.nexus.meta_metrics import get_meta_metrics
                mm = get_meta_metrics()
                mm.record("news.fetch.latency_ms", latency_ms, {"source": source["name"], "category": category})
            except Exception:
                pass

            if self._rate_limit > 0:
                time.sleep(self._rate_limit)

        # Record aggregate fetch metrics
        try:
            from engine.nexus.meta_metrics import get_meta_metrics
            mm = get_meta_metrics()
            mm.record("news.fetch.sources_success", float(metrics["success"]), {"category": category})
            mm.record("news.fetch.sources_failure", float(metrics["failure"]), {"category": category})
            mm.record("news.fetch.sources_skipped", float(metrics["skipped"]), {"category": category})
        except Exception:
            pass

        all_items.sort(key=lambda x: x.published_at, reverse=True)
        return all_items[:limit]

    def check_all_feeds(self) -> Dict[str, Any]:
        """Probe every configured RSS feed and report health status.

        Performs a lightweight HEAD-style fetch (timeout=5s, 1 retry) on
        every source URL across all categories.  Dead feeds are auto-tripped
        in the circuit-breaker so subsequent ``fetch_category`` calls skip
        them until the cooldown expires.

        Returns:
            Summary dict with alive/dead/tripped counts and per-feed detail.
        """
        from engine.nexus.news_sources import get_news_registry

        registry = get_news_registry()
        categories = registry.get_categories()
        alive: List[str] = []
        dead: List[str] = []
        tripped: List[str] = []
        details: Dict[str, Dict[str, Any]] = {}

        for cat in categories:
            sources = get_sources(cat)
            for source in sources:
                url = source["rss"]
                name = source.get("name", url)
                health = self._get_health(url)

                if health.is_tripped(self._max_failures, self._circuit_reset):
                    tripped.append(name)
                    details[name] = {
                        "url": url,
                        "category": cat,
                        "status": "tripped",
                        "consecutive_failures": health.consecutive_failures,
                    }
                    continue

                xml = _fetch_url(url, timeout=5, max_retries=1)
                if xml:
                    health.record_success()
                    alive.append(name)
                    details[name] = {
                        "url": url,
                        "category": cat,
                        "status": "alive",
                    }
                else:
                    health.record_failure(f"Health-check failed ({cat})")
                    dead.append(name)
                    details[name] = {
                        "url": url,
                        "category": cat,
                        "status": "dead",
                        "consecutive_failures": health.consecutive_failures,
                    }
                    logger.warning(
                        "Feed health-check FAILED: %s (%s) — %d consecutive failures",
                        name,
                        url,
                        health.consecutive_failures,
                    )

                time.sleep(0.5)  # polite rate-limit between probes

        # Emit aggregate metrics
        try:
            from engine.nexus.meta_metrics import get_meta_metrics
            mm = get_meta_metrics()
            mm.record("news.health.alive", float(len(alive)))
            mm.record("news.health.dead", float(len(dead)))
            mm.record("news.health.tripped", float(len(tripped)))
        except Exception:
            pass

        logger.info(
            "Feed health check: %d alive, %d dead, %d tripped",
            len(alive),
            len(dead),
            len(tripped),
        )
        return {
            "alive": len(alive),
            "dead": len(dead),
            "tripped": len(tripped),
            "dead_feeds": dead,
            "tripped_feeds": tripped,
            "details": details,
        }
