"""Tests for the Nexus URL Manager — scraping, dissecting, and storage."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from engine.nexus.url_manager import (
    URLEntry, ScrapedPage, WebScraper, ContentDissector,
    URLManager, _HTMLTextExtractor,
)


# ── URLEntry ─────────────────────────────────────────────────────────────

class TestURLEntry:
    def test_default_values(self):
        e = URLEntry()
        assert e.url == ""
        assert e.scraped is False
        assert e.dissected is False

    def test_to_dict(self):
        e = URLEntry(url="https://example.com", title="Example", domain="example.com")
        d = e.to_dict()
        assert d["url"] == "https://example.com"
        assert d["domain"] == "example.com"

    def test_from_nexus_entry(self):
        data = {"url": "https://test.com", "title": "Test", "scraped": True,
                "domain": "test.com", "topic_tags": ["docs"]}
        entry = {"id": "e1", "title": "URL: Test", "content": json.dumps(data)}
        result = URLEntry.from_nexus_entry(entry)
        assert result.url == "https://test.com"
        assert result.scraped is True
        assert result.entry_id == "e1"

    def test_from_nexus_entry_bad_json(self):
        entry = {"id": "e2", "title": "Bad URL", "content": "not json"}
        result = URLEntry.from_nexus_entry(entry)
        assert result.entry_id == "e2"


# ── HTMLTextExtractor ────────────────────────────────────────────────────

class TestHTMLTextExtractor:
    def test_extracts_text(self):
        html = "<html><body><p>Hello world</p></body></html>"
        ext = _HTMLTextExtractor()
        ext.feed(html)
        text, title, meta, headings = ext.get_result()
        assert "Hello world" in text

    def test_extracts_title(self):
        html = "<html><head><title>My Page</title></head><body>Content</body></html>"
        ext = _HTMLTextExtractor()
        ext.feed(html)
        _, title, _, _ = ext.get_result()
        assert title == "My Page"

    def test_extracts_meta_description(self):
        html = '<html><head><meta name="description" content="A test page"></head><body>X</body></html>'
        ext = _HTMLTextExtractor()
        ext.feed(html)
        _, _, meta, _ = ext.get_result()
        assert meta == "A test page"

    def test_extracts_headings(self):
        html = "<html><body><h1>Title</h1><p>Content</p><h2>Section</h2><p>More</p></body></html>"
        ext = _HTMLTextExtractor()
        ext.feed(html)
        _, _, _, headings = ext.get_result()
        assert "Title" in headings
        assert "Section" in headings

    def test_skips_script_content(self):
        html = "<html><body><script>var x = 1;</script><p>Real content</p></body></html>"
        ext = _HTMLTextExtractor()
        ext.feed(html)
        text, _, _, _ = ext.get_result()
        assert "var x" not in text
        assert "Real content" in text

    def test_skips_style_content(self):
        html = "<html><body><style>.x{color:red}</style><p>Visible</p></body></html>"
        ext = _HTMLTextExtractor()
        ext.feed(html)
        text, _, _, _ = ext.get_result()
        assert "color" not in text
        assert "Visible" in text


# ── WebScraper ───────────────────────────────────────────────────────────

class TestWebScraper:
    def test_extract_domain(self):
        assert WebScraper._extract_domain("https://example.com/page") == "example.com"
        assert WebScraper._extract_domain("http://sub.test.org/a/b") == "sub.test.org"
        assert WebScraper._extract_domain("invalid") == ""

    def test_blocked_domain(self):
        scraper = WebScraper()
        result = scraper.scrape("http://localhost:8080/test")
        assert result is None

    def test_custom_blocklist(self):
        scraper = WebScraper(blocklist=frozenset({"blocked.com"}))
        result = scraper.scrape("https://blocked.com/page")
        assert result is None

    @patch("engine.nexus.url_manager.urllib.request.urlopen")
    def test_successful_scrape(self, mock_urlopen):
        html = b"<html><head><title>Test</title></head><body><p>Hello world content here that is long enough to pass the minimum threshold for meaningful text extraction from web pages.</p></body></html>"
        mock_resp = MagicMock()
        mock_resp.read.return_value = html
        mock_resp.headers = MagicMock()
        mock_resp.headers.get.return_value = str(len(html))
        mock_resp.headers.get_content_charset.return_value = "utf-8"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        scraper = WebScraper()
        page = scraper.scrape("https://example.com")
        assert page is not None
        assert page.title == "Test"
        assert "Hello world" in page.text

    @patch("engine.nexus.url_manager.urllib.request.urlopen")
    def test_page_too_large(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.headers = MagicMock()
        mock_resp.headers.get.return_value = "999999999"
        mock_resp.headers.get_content_charset.return_value = "utf-8"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        scraper = WebScraper()
        page = scraper.scrape("https://example.com/huge")
        assert page is None


# ── ContentDissector ─────────────────────────────────────────────────────

class TestContentDissector:
    def test_dissect_simple(self):
        page = ScrapedPage(
            url="https://example.com",
            title="Example",
            text="This is a test page with enough content to form a fragment. " * 5,
        )
        dissector = ContentDissector()
        fragments = dissector.dissect(page)
        assert len(fragments) >= 1
        assert fragments[0]["source_url"] == "https://example.com"

    def test_dissect_with_headings(self):
        text = "Intro paragraph with enough content to be useful for extraction that exceeds the minimum chunk size threshold of one hundred characters.\n\n"
        text += "## Section One\nFirst section content that is long enough to pass the minimum threshold for a fragment and contains useful information for testing purposes.\n\n"
        text += "## Section Two\nSecond section content that is also long enough to pass the minimum threshold and provides additional test coverage.\n"
        page = ScrapedPage(url="https://test.com", title="Test", text=text)
        dissector = ContentDissector()
        fragments = dissector.dissect(page)
        assert len(fragments) >= 2

    def test_dissect_skips_tiny_chunks(self):
        page = ScrapedPage(url="https://x.com", title="X", text="tiny")
        dissector = ContentDissector()
        fragments = dissector.dissect(page)
        assert len(fragments) == 0

    def test_chunk_text_respects_max_size(self):
        dissector = ContentDissector(max_chunk=100)
        text = "This is sentence one. " * 20  # ~440 chars
        chunks = dissector._chunk_text(text, 100)
        for chunk in chunks:
            assert len(chunk) <= 200  # some slack for sentence boundaries

    def test_generate_tags(self):
        page = ScrapedPage(url="https://docs.python.org/tutorial", title="Python Tutorial")
        tags = ContentDissector._generate_tags("content", "Installation Guide", page)
        assert "url_fragment" in tags
        assert any("domain:" in t for t in tags)

    def test_dissect_large_section_chunks(self):
        text = "Word " * 1000  # ~5000 chars
        page = ScrapedPage(url="https://test.com", title="Large", text=text)
        dissector = ContentDissector(max_chunk=500)
        fragments = dissector.dissect(page)
        assert len(fragments) >= 2  # Should be chunked into multiple


# ── URLManager ───────────────────────────────────────────────────────────

class TestURLManager:
    def setup_method(self):
        self.mgr = URLManager()
        self.mock_client = MagicMock()
        self.mgr._client = self.mock_client
        self.mgr._available = True
        self.mock_client.is_available.return_value = True
        self.mock_client.add_entry.return_value = "url-001"
        self.mock_client.search.return_value = []

    def test_add_url(self):
        entry_id = self.mgr.add_url("https://example.com", title="Example")
        assert entry_id == "url-001"
        self.mock_client.add_entry.assert_called_once()
        assert self.mgr.stats["urls_added"] == 1

    def test_add_url_dedup(self):
        self.mock_client.search.return_value = [
            {"content": json.dumps({"url": "https://example.com"})}
        ]
        entry_id = self.mgr.add_url("https://example.com")
        assert entry_id == ""

    def test_add_url_normalizes_protocol(self):
        self.mgr.add_url("example.com")
        call_kwargs = self.mock_client.add_entry.call_args
        content = json.loads(call_kwargs.kwargs.get("content", call_kwargs[1].get("content", "{}")))
        assert content["url"].startswith("https://")

    def test_add_url_offline(self):
        self.mgr._available = False
        assert self.mgr.add_url("https://x.com") == ""

    def test_add_url_empty(self):
        assert self.mgr.add_url("") == ""

    def test_list_urls(self):
        self.mock_client.list_entries.return_value = [
            {"id": "u1", "title": "URL: Test",
             "content": json.dumps({"url": "https://test.com", "domain": "test.com"})},
        ]
        urls = self.mgr.list_urls()
        assert len(urls) == 1
        assert urls[0].url == "https://test.com"

    def test_list_urls_filter_domain(self):
        self.mock_client.list_entries.return_value = [
            {"id": "u1", "content": json.dumps({"url": "https://a.com", "domain": "a.com"})},
            {"id": "u2", "content": json.dumps({"url": "https://b.com", "domain": "b.com"})},
        ]
        urls = self.mgr.list_urls(domain="a.com")
        assert len(urls) == 1

    def test_list_urls_offline(self):
        self.mgr._available = False
        assert self.mgr.list_urls() == []

    def test_stats_property(self):
        assert "urls_added" in self.mgr.stats
        assert "pages_scraped" in self.mgr.stats

    def test_is_available(self):
        assert self.mgr.is_available is True
        self.mgr._available = False
        assert self.mgr.is_available is False

    def test_process_url_offline(self):
        self.mgr._available = False
        result = self.mgr.process_url("https://test.com")
        assert result["status"] == "failed"


# ── Singleton ────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_url_manager(self):
        import engine.nexus.url_manager as um
        um._manager_instance = None
        m1 = um.get_url_manager()
        m2 = um.get_url_manager()
        assert m1 is m2
        um._manager_instance = None
