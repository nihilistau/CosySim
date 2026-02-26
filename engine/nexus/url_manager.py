"""Nexus URL Manager — Store, scrape, and dissect web content into Nexus.

Three-layer architecture:
  1. Storage Layer:  URLEntry bookmarks with metadata (content_type="url")
  2. Scraping Layer: WebScraper fetches pages via bs4 (content_type="webpage")
  3. Dissection Layer: ContentDissector splits pages into knowledge fragments

Guardrails:
  - Max page size: 500KB
  - Dedup: skip if URL already in Nexus
  - Rate limit: 2s between scrapes
  - Chunk size: max 2000 chars per fragment
  - Domain blocklist: configurable

Usage:
    from engine.nexus.url_manager import get_url_manager
    mgr = get_url_manager()

    entry_id = mgr.add_url("https://example.com", tags=["docs"])
    mgr.scrape_url(entry_id)     # fetch + store full page
    mgr.dissect_url(entry_id)    # split into knowledge fragments
    mgr.process_url("https://example.com")  # add + scrape + dissect
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

_manager_instance: Optional[URLManager] = None
_manager_lock = threading.Lock()

# ── Constants ────────────────────────────────────────────────────────────

MAX_PAGE_BYTES = 500_000       # 500KB
MAX_CHUNK_CHARS = 2000         # per dissected fragment
MIN_CHUNK_CHARS = 100          # skip tiny fragments
SCRAPE_DELAY_SECONDS = 2.0     # rate limit between scrapes
REQUEST_TIMEOUT = 30           # HTTP timeout
USER_AGENT = "CosySim-Nexus/1.0 (Knowledge Indexer)"

DEFAULT_BLOCKLIST = frozenset({
    "localhost", "127.0.0.1", "0.0.0.0",
})


# ── Data Classes ─────────────────────────────────────────────────────────

@dataclass
class URLEntry:
    """A stored URL bookmark with metadata."""

    url: str = ""
    title: str = ""
    synopsis: str = ""
    domain: str = ""
    topic_tags: List[str] = field(default_factory=list)
    added_by: str = "copilot"
    scraped: bool = False
    dissected: bool = False
    added_at: float = 0.0
    scraped_at: float = 0.0
    entry_id: str = ""        # Nexus entry ID
    page_entry_id: str = ""   # Nexus entry ID for scraped page

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to dict."""
        return asdict(self)

    @classmethod
    def from_nexus_entry(cls, entry: Dict[str, Any]) -> URLEntry:
        """Parse a Nexus entry back into a URLEntry."""
        try:
            content = entry.get("content", "{}")
            data = json.loads(content) if isinstance(content, str) else content
            return cls(
                url=data.get("url", ""),
                title=data.get("title", entry.get("title", "")),
                synopsis=data.get("synopsis", ""),
                domain=data.get("domain", ""),
                topic_tags=data.get("topic_tags", []),
                added_by=data.get("added_by", ""),
                scraped=data.get("scraped", False),
                dissected=data.get("dissected", False),
                added_at=data.get("added_at", 0.0),
                scraped_at=data.get("scraped_at", 0.0),
                entry_id=entry.get("id", data.get("entry_id", "")),
                page_entry_id=data.get("page_entry_id", ""),
            )
        except (json.JSONDecodeError, TypeError):
            return cls(url=entry.get("title", ""), entry_id=entry.get("id", ""))


@dataclass
class ScrapedPage:
    """Result of scraping a URL."""

    url: str = ""
    title: str = ""
    text: str = ""
    meta_description: str = ""
    headings: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    word_count: int = 0
    byte_size: int = 0
    scraped_at: float = 0.0


# ── HTML Text Extractor ─────────────────────────────────────────────────

class _HTMLTextExtractor(HTMLParser):
    """Simple HTML→text extractor using stdlib HTMLParser."""

    SKIP_TAGS = frozenset({
        "script", "style", "noscript", "svg", "path",
    })

    def __init__(self) -> None:
        super().__init__()
        self._text_parts: List[str] = []
        self._headings: List[str] = []
        self._title: str = ""
        self._meta_desc: str = ""
        self._skip_depth: int = 0
        self._in_title: bool = False
        self._in_heading: bool = False
        self._current_heading: List[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag_lower = tag.lower()
        if tag_lower in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag_lower == "title":
            self._in_title = True
        elif tag_lower in ("h1", "h2", "h3", "h4"):
            self._in_heading = True
            self._current_heading = []
        elif tag_lower == "meta":
            attr_dict = dict(attrs)
            if attr_dict.get("name", "").lower() == "description":
                self._meta_desc = attr_dict.get("content", "")
        elif tag_lower in ("br", "p", "div", "li", "tr"):
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag_lower == "title":
            self._in_title = False
        elif tag_lower in ("h1", "h2", "h3", "h4"):
            self._in_heading = False
            heading_text = " ".join(self._current_heading).strip()
            if heading_text:
                self._headings.append(heading_text)
                self._text_parts.append(f"\n## {heading_text}\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title = data.strip()
        if self._in_heading:
            self._current_heading.append(data)
        self._text_parts.append(data)

    def get_result(self) -> Tuple[str, str, str, List[str]]:
        """Return (text, title, meta_description, headings)."""
        text = " ".join(self._text_parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text.strip(), self._title, self._meta_desc, self._headings


# ── WebScraper ───────────────────────────────────────────────────────────

class WebScraper:
    """Fetches and parses web pages into clean text."""

    def __init__(
        self,
        max_bytes: int = MAX_PAGE_BYTES,
        timeout: int = REQUEST_TIMEOUT,
        blocklist: Optional[frozenset] = None,
    ) -> None:
        self._max_bytes = max_bytes
        self._timeout = timeout
        self._blocklist = blocklist or DEFAULT_BLOCKLIST

    def scrape(self, url: str) -> Optional[ScrapedPage]:
        """Fetch and parse a URL into a ScrapedPage.

        Args:
            url: The URL to scrape.

        Returns:
            ScrapedPage on success, None on failure.
        """
        domain = self._extract_domain(url)
        if domain in self._blocklist:
            logger.warning("Blocked domain: %s", domain)
            return None

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                content_length = resp.headers.get("Content-Length", "0")
                if content_length.isdigit() and int(content_length) > self._max_bytes:
                    logger.warning("Page too large (%s bytes): %s", content_length, url)
                    return None

                raw = resp.read(self._max_bytes + 1)
                if len(raw) > self._max_bytes:
                    logger.warning("Page exceeds %d bytes: %s", self._max_bytes, url)
                    return None

                charset = resp.headers.get_content_charset() or "utf-8"
                html = raw.decode(charset, errors="replace")

        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            return None

        extractor = _HTMLTextExtractor()
        try:
            extractor.feed(html)
        except Exception as exc:
            logger.warning("HTML parse error for %s: %s", url, exc)
            return None

        text, title, meta_desc, headings = extractor.get_result()

        if not text or len(text) < 50:
            logger.debug("No meaningful text extracted from %s", url)
            return None

        return ScrapedPage(
            url=url,
            title=title or url,
            text=text,
            meta_description=meta_desc,
            headings=headings,
            word_count=len(text.split()),
            byte_size=len(raw),
            scraped_at=time.time(),
        )

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.hostname or ""
        except Exception:
            return ""


# ── ContentDissector ─────────────────────────────────────────────────────

class ContentDissector:
    """Splits scraped page content into knowledge fragments."""

    def __init__(
        self,
        max_chunk: int = MAX_CHUNK_CHARS,
        min_chunk: int = MIN_CHUNK_CHARS,
    ) -> None:
        self._max_chunk = max_chunk
        self._min_chunk = min_chunk

    def dissect(self, page: ScrapedPage) -> List[Dict[str, Any]]:
        """Split a scraped page into tagged knowledge fragments.

        Args:
            page: The ScrapedPage to dissect.

        Returns:
            List of fragment dicts with title, content, tags.
        """
        fragments: List[Dict[str, Any]] = []

        # Split by headings or double newlines
        sections = self._split_sections(page.text)

        for i, section in enumerate(sections):
            text = section["text"].strip()
            if len(text) < self._min_chunk:
                continue

            # Further chunk if section is too large
            chunks = self._chunk_text(text, self._max_chunk)

            for j, chunk in enumerate(chunks):
                heading = section.get("heading", "")
                suffix = f" (part {j + 1})" if len(chunks) > 1 else ""
                title = f"{page.title}: {heading}{suffix}" if heading else f"{page.title} (section {i + 1}{suffix})"

                fragment = {
                    "title": title[:200],
                    "content": chunk,
                    "tags": self._generate_tags(chunk, heading, page),
                    "source_url": page.url,
                    "heading": heading,
                }
                fragments.append(fragment)

        return fragments

    def _split_sections(self, text: str) -> List[Dict[str, str]]:
        """Split text into sections by headings or double newlines."""
        sections: List[Dict[str, str]] = []
        # Split on markdown-style headings
        parts = re.split(r"\n+## (.+?)\n", text)

        if len(parts) <= 1:
            # No headings — split by double newlines or by max_chunk
            paragraphs = text.split("\n\n")
            current = ""
            for p in paragraphs:
                if len(current) + len(p) < self._max_chunk:
                    current += "\n\n" + p if current else p
                else:
                    if current:
                        sections.append({"text": current, "heading": ""})
                    current = p
            if current:
                sections.append({"text": current, "heading": ""})

            # If we got a single section larger than max_chunk, force-chunk it
            if len(sections) == 1 and len(sections[0]["text"]) > self._max_chunk:
                big = sections[0]["text"]
                sections = []
                for chunk in self._chunk_text(big, self._max_chunk):
                    sections.append({"text": chunk, "heading": ""})
        else:
            # Has headings — pair heading with content
            if parts[0].strip():
                sections.append({"text": parts[0], "heading": "Introduction"})
            for k in range(1, len(parts), 2):
                heading = parts[k] if k < len(parts) else ""
                content = parts[k + 1] if k + 1 < len(parts) else ""
                if content.strip():
                    sections.append({"text": content, "heading": heading})

        return sections

    def _chunk_text(self, text: str, max_size: int) -> List[str]:
        """Break text into chunks at sentence boundaries."""
        if len(text) <= max_size:
            return [text]

        chunks: List[str] = []
        sentences = re.split(r"(?<=[.!?])\s+", text)
        current = ""

        for sentence in sentences:
            if len(current) + len(sentence) + 1 <= max_size:
                current += (" " + sentence) if current else sentence
            else:
                if current:
                    chunks.append(current.strip())
                # If single sentence exceeds max, hard-split by words
                if len(sentence) > max_size:
                    words = sentence.split()
                    part = ""
                    for w in words:
                        if len(part) + len(w) + 1 <= max_size:
                            part += (" " + w) if part else w
                        else:
                            if part:
                                chunks.append(part)
                            part = w
                    current = part
                else:
                    current = sentence

        if current:
            chunks.append(current.strip())

        return chunks if chunks else [text[:max_size]]

    @staticmethod
    def _generate_tags(content: str, heading: str, page: ScrapedPage) -> List[str]:
        """Auto-generate topic tags from content."""
        tags = ["url_fragment"]
        domain = WebScraper._extract_domain(page.url)
        if domain:
            tags.append(f"domain:{domain}")

        # Extract key terms from heading
        if heading:
            words = re.findall(r"\w{4,}", heading.lower())
            tags.extend(words[:3])

        return tags


# ── URLManager ───────────────────────────────────────────────────────────

class URLManager:
    """Manages URL storage, scraping, and dissection via Nexus."""

    URL_CONTENT_TYPE = "url"
    PAGE_CONTENT_TYPE = "webpage"
    FRAGMENT_CONTENT_TYPE = "note"

    def __init__(self) -> None:
        self._client = None
        self._available = False
        self._scraper = WebScraper()
        self._dissector = ContentDissector()
        self._last_scrape_time: float = 0.0
        self._stats = {
            "urls_added": 0,
            "pages_scraped": 0,
            "fragments_created": 0,
            "qa_generated": 0,
            "bytes_processed": 0,
        }
        self._init_client()

    def _init_client(self) -> None:
        """Initialise Nexus client."""
        try:
            from engine.nexus.client import get_nexus_client
            self._client = get_nexus_client()
            self._available = self._client.is_available()
        except Exception:
            self._available = False

    @property
    def is_available(self) -> bool:
        """Check if URL manager is operational."""
        return self._available and self._client is not None

    @property
    def stats(self) -> Dict[str, int]:
        """Get URL system statistics."""
        return dict(self._stats)

    def add_url(
        self,
        url: str,
        title: str = "",
        synopsis: str = "",
        tags: Optional[List[str]] = None,
        added_by: str = "copilot",
        scrape: bool = False,
    ) -> str:
        """Add a URL bookmark to Nexus.

        Args:
            url: The URL to store.
            title: Optional human-readable title.
            synopsis: Optional short description.
            tags: Topic tags for categorisation.
            added_by: Who added this URL.
            scrape: If True, immediately scrape and dissect.

        Returns:
            Entry ID string, or empty string on failure.
        """
        if not url:
            return ""

        # Normalise URL
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        domain = WebScraper._extract_domain(url)

        # Check for duplicate
        if self.is_available and self._is_duplicate(url):
            logger.info("URL already exists in Nexus: %s", url)
            return ""

        entry = URLEntry(
            url=url,
            title=title or url,
            synopsis=synopsis,
            domain=domain,
            topic_tags=tags or [],
            added_by=added_by,
            added_at=time.time(),
        )

        if not self.is_available:
            logger.debug("Nexus unavailable — URL not stored: %s", url)
            return ""

        try:
            all_tags = ["url", f"domain:{domain}"] + (tags or [])
            entry_id = self._client.add_entry(
                title=f"URL: {title or url}",
                content=json.dumps(entry.to_dict()),
                content_type=self.URL_CONTENT_TYPE,
                category="urls",
                tags=all_tags,
                created_by=added_by,
            )
            entry.entry_id = entry_id
            self._stats["urls_added"] += 1
            logger.info("Stored URL: %s (id=%s)", url, entry_id)

            if scrape and entry_id:
                self.scrape_url(entry_id, url=url)

            return entry_id or ""
        except Exception as exc:
            logger.warning("Failed to add URL: %s", exc)
            return ""

    def scrape_url(
        self,
        entry_id: str = "",
        url: str = "",
    ) -> Optional[ScrapedPage]:
        """Scrape a URL and store the full page in Nexus.

        Args:
            entry_id: Nexus entry ID of the URL bookmark.
            url: URL to scrape (if entry_id not provided).

        Returns:
            ScrapedPage on success, None on failure.
        """
        if not url and entry_id and self.is_available:
            entry = self._client.get_entry(entry_id)
            if entry:
                try:
                    data = json.loads(entry.get("content", "{}"))
                    url = data.get("url", "")
                except (json.JSONDecodeError, TypeError):
                    logger.debug("Suppressed exception", exc_info=True)

        if not url:
            return None

        # Rate limiting
        elapsed = time.time() - self._last_scrape_time
        if elapsed < SCRAPE_DELAY_SECONDS:
            time.sleep(SCRAPE_DELAY_SECONDS - elapsed)

        page = self._scraper.scrape(url)
        self._last_scrape_time = time.time()

        if not page:
            return None

        if not self.is_available:
            return page

        # Store full page
        try:
            page_id = self._client.add_entry(
                title=f"Page: {page.title}",
                content=page.text[:50000],  # Cap at 50K chars
                content_type=self.PAGE_CONTENT_TYPE,
                category="url_content",
                tags=["webpage", f"domain:{WebScraper._extract_domain(url)}", "scraped"],
                created_by="url_manager",
            )
            self._stats["pages_scraped"] += 1
            self._stats["bytes_processed"] += page.byte_size

            # Update original URL entry with scrape status
            if entry_id:
                self._update_url_entry(entry_id, scraped=True, page_entry_id=page_id)

            # Auto-dissect
            self._dissect_and_store(page, entry_id)

            return page
        except Exception as exc:
            logger.warning("Failed to store scraped page: %s", exc)
            return page

    def dissect_url(self, entry_id: str) -> int:
        """Dissect a previously scraped URL into knowledge fragments.

        Args:
            entry_id: Nexus entry ID of the URL bookmark.

        Returns:
            Number of fragments created.
        """
        if not self.is_available:
            return 0

        entry = self._client.get_entry(entry_id)
        if not entry:
            return 0

        try:
            data = json.loads(entry.get("content", "{}"))
            page_id = data.get("page_entry_id", "")
            url = data.get("url", "")
        except (json.JSONDecodeError, TypeError):
            return 0

        if not page_id:
            return 0

        page_entry = self._client.get_entry(page_id)
        if not page_entry:
            return 0

        page = ScrapedPage(
            url=url,
            title=page_entry.get("title", "").replace("Page: ", ""),
            text=page_entry.get("content", ""),
        )

        return self._dissect_and_store(page, entry_id)

    def process_url(
        self,
        url: str,
        title: str = "",
        tags: Optional[List[str]] = None,
        added_by: str = "copilot",
    ) -> Dict[str, Any]:
        """Full pipeline: add → scrape → dissect a URL.

        Args:
            url: The URL to process.
            title: Optional title.
            tags: Optional tags.
            added_by: Who added this.

        Returns:
            Dict with entry_id, fragments_count, word_count, status.
        """
        entry_id = self.add_url(url, title=title, tags=tags,
                                added_by=added_by, scrape=True)
        if not entry_id:
            return {"status": "failed", "reason": "could not add URL"}

        return {
            "status": "ok",
            "entry_id": entry_id,
            "urls_added": self._stats["urls_added"],
            "pages_scraped": self._stats["pages_scraped"],
            "fragments_created": self._stats["fragments_created"],
        }

    def list_urls(
        self,
        limit: int = 20,
        domain: str = "",
    ) -> List[URLEntry]:
        """List stored URLs.

        Args:
            limit: Maximum results.
            domain: Filter by domain.

        Returns:
            List of URLEntry objects.
        """
        if not self.is_available:
            return []

        try:
            entries = self._client.list_entries(
                content_type=self.URL_CONTENT_TYPE,
                category="urls",
                limit=limit,
            )
            urls = []
            for entry in entries:
                url_entry = URLEntry.from_nexus_entry(entry)
                if domain and url_entry.domain != domain:
                    continue
                urls.append(url_entry)
            return urls
        except Exception as exc:
            logger.debug("list_urls failed: %s", exc)
            return []

    def _is_duplicate(self, url: str) -> bool:
        """Check if URL already exists in Nexus."""
        try:
            results = self._client.search(url, limit=5)
            for r in results:
                try:
                    data = json.loads(r.get("content", "{}"))
                    if data.get("url") == url:
                        return True
                except (json.JSONDecodeError, TypeError):
                    logger.debug("Suppressed exception", exc_info=True)
            return False
        except Exception:
            return False

    def _update_url_entry(
        self,
        entry_id: str,
        scraped: bool = False,
        page_entry_id: str = "",
    ) -> None:
        """Update URL entry with scrape metadata."""
        try:
            entry = self._client.get_entry(entry_id)
            if not entry:
                return
            data = json.loads(entry.get("content", "{}"))
            data["scraped"] = scraped
            data["scraped_at"] = time.time()
            if page_entry_id:
                data["page_entry_id"] = page_entry_id
            self._client.update_entry(entry_id, content=json.dumps(data))
        except Exception as exc:
            logger.debug("Failed to update URL entry: %s", exc)

    def _dissect_and_store(self, page: ScrapedPage, entry_id: str = "") -> int:
        """Dissect page and store fragments + Q&A pairs."""
        fragments = self._dissector.dissect(page)
        stored = 0

        for frag in fragments:
            try:
                self._client.add_entry(
                    title=frag["title"],
                    content=frag["content"],
                    content_type=self.FRAGMENT_CONTENT_TYPE,
                    category="url_fragments",
                    tags=frag["tags"],
                    created_by="url_manager",
                )
                stored += 1
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

        self._stats["fragments_created"] += stored

        # Generate Q&A from headings
        qa_count = self._generate_qa(page)
        self._stats["qa_generated"] += qa_count

        # Update entry with dissection status
        if entry_id:
            try:
                entry = self._client.get_entry(entry_id)
                if entry:
                    data = json.loads(entry.get("content", "{}"))
                    data["dissected"] = True
                    self._client.update_entry(entry_id, content=json.dumps(data))
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

        return stored

    def _generate_qa(self, page: ScrapedPage) -> int:
        """Generate Q&A pairs from page headings + content."""
        if not self.is_available or not page.headings:
            return 0

        count = 0
        for heading in page.headings[:5]:  # Max 5 Q&A per page
            # Find content under this heading
            pattern = re.escape(heading) + r"\n(.+?)(?=\n## |\Z)"
            match = re.search(pattern, page.text, re.DOTALL)
            if not match:
                continue

            answer = match.group(1).strip()[:500]
            if len(answer) < 50:
                continue

            try:
                self._client.add_qa(
                    question=f"What is {heading}? (from {page.title})",
                    answer=answer,
                    category="url_content",
                    tags=["url_qa", f"source:{page.url[:100]}"],
                )
                count += 1
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

        return count


def get_url_manager() -> URLManager:
    """Get or create the singleton URLManager.

    Returns:
        URLManager instance.
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = URLManager()
    return _manager_instance
