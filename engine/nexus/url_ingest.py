"""
URL Ingestion Pipeline — fetch web pages, convert to markdown, store in Nexus.

Provides a reusable workflow for batch-ingesting web content into the Nexus
knowledge system. Strips HTML, extracts text, and stores as markdown documents.

Sprint 8.5: Initial implementation.
"""
import html
import json
import logging
import re
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """Result of a single URL ingestion."""
    url: str
    title: str = ""
    success: bool = False
    entry_id: str = ""
    error: str = ""
    content_length: int = 0


@dataclass
class IngestBatch:
    """Result of a batch URL ingestion."""
    results: List[IngestResult] = field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.success)

    def summary(self) -> Dict[str, Any]:
        return {
            "total": len(self.results),
            "succeeded": self.succeeded,
            "failed": self.failed,
            "entries": [
                {"url": r.url, "title": r.title, "ok": r.success, "error": r.error}
                for r in self.results
            ],
        }


# ── HTML → Markdown Conversion ────────────────────────────────


def _strip_tags(html_text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Convert headers
    for i in range(1, 7):
        text = re.sub(
            rf"<h{i}[^>]*>(.*?)</h{i}>",
            lambda m, level=i: f"\n{'#' * level} {m.group(1).strip()}\n",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

    # Convert paragraphs and line breaks (negative lookahead to skip <pre>)
    text = re.sub(r"<p(?![a-z])[^>]*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # Convert lists
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "", text, flags=re.IGNORECASE)

    # Convert code blocks
    text = re.sub(
        r"<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>",
        lambda m: f"\n```\n{m.group(1).strip()}\n```\n",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Also handle <pre> without <code>
    text = re.sub(
        r"<pre[^>]*>(.*?)</pre>",
        lambda m: f"\n```\n{m.group(1).strip()}\n```\n",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(
        r"<code[^>]*>(.*?)</code>",
        lambda m: f"`{m.group(1).strip()}`",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Convert links
    text = re.sub(
        r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        lambda m: f"[{m.group(2).strip()}]({m.group(1)})",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Convert bold/italic
    text = re.sub(r"<(strong|b)[^>]*>(.*?)</\1>", r"**\2**", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(em|i)[^>]*>(.*?)</\1>", r"*\2*", text, flags=re.DOTALL | re.IGNORECASE)

    # Remove remaining tags
    text = re.sub(r"<[^>]+>", "", text)

    # Decode HTML entities
    text = html.unescape(text)

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _extract_title(html_text: str, url: str) -> str:
    """Extract page title from HTML or derive from URL."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.DOTALL | re.IGNORECASE)
    if match:
        title = html.unescape(match.group(1).strip())
        # Clean common suffixes
        for sep in [" | ", " - ", " — ", " :: "]:
            if sep in title:
                title = title.split(sep)[0].strip()
        return title

    # Derive from URL
    slug = url.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").replace("_", " ").title()


# ── Fetch ─────────────────────────────────────────────────────


def fetch_url(url: str, timeout: int = 15) -> Dict[str, Any]:
    """Fetch a URL and convert HTML content to markdown.

    Args:
        url: The URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        Dict with title, markdown, url, and content_length.
    """
    headers = {
        "User-Agent": "CosySim-URLIngest/1.0",
        "Accept": "text/html,application/xhtml+xml,*/*",
    }
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}

    title = _extract_title(raw, url)
    markdown = _strip_tags(raw)

    return {
        "title": title,
        "markdown": markdown,
        "url": url,
        "content_length": len(markdown),
    }


# ── Store in Nexus ────────────────────────────────────────────


def ingest_url(url: str, category: str = "reference",
               tags: Optional[List[str]] = None,
               timeout: int = 15) -> IngestResult:
    """Fetch a single URL, convert to markdown, and store in Nexus.

    Args:
        url: The URL to ingest.
        category: Nexus category for the entry.
        tags: Optional tags for the entry.
        timeout: Request timeout in seconds.

    Returns:
        IngestResult with success/failure details.
    """
    from engine.nexus.client import get_nexus_client

    result = IngestResult(url=url)

    fetched = fetch_url(url, timeout=timeout)
    if "error" in fetched:
        result.error = fetched["error"]
        return result

    result.title = fetched["title"]
    result.content_length = fetched["content_length"]

    # Prepend source URL
    content = f"Source: {url}\n\n{fetched['markdown']}"

    try:
        client = get_nexus_client()
        entry_id = client.add_entry(
            title=fetched["title"],
            content=content,
            content_type="document",
            category=category,
        )
        if entry_id:
            result.success = True
            result.entry_id = str(entry_id)
            logger.info("Ingested: %s → Nexus entry %s", url, entry_id)
        else:
            result.error = "Nexus returned empty entry_id"
    except Exception as e:
        result.error = str(e)
        logger.error("Failed to store %s in Nexus: %s", url, e)

    return result


def ingest_batch(urls: List[str], category: str = "reference",
                 tags: Optional[List[str]] = None,
                 timeout: int = 15) -> IngestBatch:
    """Fetch and store multiple URLs in Nexus.

    Args:
        urls: List of URLs to ingest.
        category: Nexus category for all entries.
        tags: Optional tags applied to all entries.
        timeout: Per-request timeout in seconds.

    Returns:
        IngestBatch with per-URL results and summary.
    """
    batch = IngestBatch()
    for url in urls:
        result = ingest_url(url, category=category, tags=tags, timeout=timeout)
        batch.results.append(result)
        logger.info(
            "Batch [%d/%d] %s: %s",
            len(batch.results), len(urls),
            "OK" if result.success else "FAIL",
            url,
        )
    return batch


# ── Singleton ─────────────────────────────────────────────────

_ingest_lock = None


def get_url_ingester():
    """Return the module-level ingest functions (stateless, no singleton needed)."""
    return {
        "fetch_url": fetch_url,
        "ingest_url": ingest_url,
        "ingest_batch": ingest_batch,
    }
