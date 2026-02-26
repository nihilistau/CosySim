"""Tests for URL ingestion pipeline."""
import json
from unittest.mock import patch, MagicMock

import pytest

from engine.nexus.url_ingest import (
    _strip_tags,
    _extract_title,
    fetch_url,
    ingest_url,
    ingest_batch,
    IngestResult,
    IngestBatch,
)


# ── HTML → Markdown Conversion ────────────────────────────────


class TestStripTags:
    """Tests for HTML to markdown conversion."""

    def test_removes_script_tags(self):
        html = "<p>Hello</p><script>alert('x')</script><p>World</p>"
        result = _strip_tags(html)
        assert "alert" not in result
        assert "Hello" in result
        assert "World" in result

    def test_removes_style_tags(self):
        html = "<style>.x{color:red}</style><p>Content</p>"
        result = _strip_tags(html)
        assert "color" not in result
        assert "Content" in result

    def test_converts_headers(self):
        html = "<h1>Title</h1><h2>Subtitle</h2><h3>Section</h3>"
        result = _strip_tags(html)
        assert "# Title" in result
        assert "## Subtitle" in result
        assert "### Section" in result

    def test_converts_paragraphs(self):
        html = "<p>First paragraph</p><p>Second paragraph</p>"
        result = _strip_tags(html)
        assert "First paragraph" in result
        assert "Second paragraph" in result

    def test_converts_lists(self):
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        result = _strip_tags(html)
        assert "- Item 1" in result
        assert "- Item 2" in result

    def test_converts_code_blocks(self):
        html = "<pre><code>print('hello')</code></pre>"
        result = _strip_tags(html)
        assert "```" in result
        assert "print('hello')" in result

    def test_converts_inline_code(self):
        html = "Use <code>git commit</code> to save."
        result = _strip_tags(html)
        assert "`git commit`" in result

    def test_converts_links(self):
        html = '<a href="https://example.com">Click here</a>'
        result = _strip_tags(html)
        assert "[Click here](https://example.com)" in result

    def test_converts_bold(self):
        html = "<strong>Important</strong> and <b>bold</b>"
        result = _strip_tags(html)
        assert "**Important**" in result
        assert "**bold**" in result

    def test_converts_italic(self):
        html = "<em>Emphasis</em> and <i>italic</i>"
        result = _strip_tags(html)
        assert "*Emphasis*" in result
        assert "*italic*" in result

    def test_decodes_entities(self):
        html = "<p>Tom &amp; Jerry &lt;3 &quot;fun&quot;</p>"
        result = _strip_tags(html)
        assert "Tom & Jerry" in result
        assert '<3' in result

    def test_removes_nav_footer_header(self):
        html = "<nav>Menu</nav><main>Content</main><footer>Footer</footer>"
        result = _strip_tags(html)
        assert "Menu" not in result
        assert "Footer" not in result
        assert "Content" in result

    def test_handles_empty_input(self):
        assert _strip_tags("") == ""

    def test_handles_plain_text(self):
        assert _strip_tags("Just plain text") == "Just plain text"

    def test_collapses_excessive_newlines(self):
        html = "<p>A</p>\n\n\n\n\n<p>B</p>"
        result = _strip_tags(html)
        assert "\n\n\n" not in result


# ── Title Extraction ──────────────────────────────────────────


class TestExtractTitle:
    """Tests for HTML title extraction."""

    def test_extracts_simple_title(self):
        html = "<html><head><title>My Page</title></head></html>"
        assert _extract_title(html, "https://example.com") == "My Page"

    def test_strips_site_suffix(self):
        html = "<title>My Page | GitHub Docs</title>"
        assert _extract_title(html, "https://docs.github.com/page") == "My Page"

    def test_strips_dash_suffix(self):
        html = "<title>Article - Medium</title>"
        assert _extract_title(html, "https://medium.com") == "Article"

    def test_fallback_to_url_slug(self):
        html = "<html><body>No title</body></html>"
        result = _extract_title(html, "https://example.com/my-great-page")
        assert result == "My Great Page"

    def test_handles_entities_in_title(self):
        html = "<title>Tom &amp; Jerry</title>"
        assert _extract_title(html, "https://example.com") == "Tom & Jerry"


# ── fetch_url ─────────────────────────────────────────────────


class TestFetchUrl:
    """Tests for URL fetching."""

    @patch("engine.nexus.url_ingest.urllib.request.urlopen")
    def test_fetch_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html><head><title>Test</title></head><body><p>Hello</p></body></html>"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_url("https://example.com/test")
        assert result["title"] == "Test"
        assert "Hello" in result["markdown"]
        assert result["content_length"] > 0

    @patch("engine.nexus.url_ingest.urllib.request.urlopen")
    def test_fetch_http_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://example.com", 404, "Not Found", {}, None
        )
        result = fetch_url("https://example.com/missing")
        assert "error" in result
        assert "404" in result["error"]

    @patch("engine.nexus.url_ingest.urllib.request.urlopen")
    def test_fetch_connection_error(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionError("refused")
        result = fetch_url("https://example.com")
        assert "error" in result


# ── IngestResult & IngestBatch ────────────────────────────────


class TestDataClasses:
    """Tests for result data classes."""

    def test_ingest_result_defaults(self):
        r = IngestResult(url="https://example.com")
        assert not r.success
        assert r.title == ""
        assert r.error == ""

    def test_ingest_batch_counts(self):
        batch = IngestBatch(results=[
            IngestResult(url="a", success=True),
            IngestResult(url="b", success=False, error="fail"),
            IngestResult(url="c", success=True),
        ])
        assert batch.succeeded == 2
        assert batch.failed == 1

    def test_ingest_batch_summary(self):
        batch = IngestBatch(results=[
            IngestResult(url="https://a.com", title="A", success=True),
        ])
        summary = batch.summary()
        assert summary["total"] == 1
        assert summary["succeeded"] == 1
        assert summary["entries"][0]["url"] == "https://a.com"

    def test_empty_batch(self):
        batch = IngestBatch()
        assert batch.succeeded == 0
        assert batch.failed == 0


# ── ingest_url ────────────────────────────────────────────────


class TestIngestUrl:
    """Tests for single URL ingestion."""

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.nexus.url_ingest.fetch_url")
    def test_ingest_success(self, mock_fetch, mock_nexus):
        mock_fetch.return_value = {
            "title": "Test Page",
            "markdown": "# Test\n\nContent here",
            "url": "https://example.com/test",
            "content_length": 25,
        }
        client = MagicMock()
        client.add_entry.return_value = "entry-42"
        mock_nexus.return_value = client

        result = ingest_url("https://example.com/test", category="docs")
        assert result.success
        assert result.title == "Test Page"
        assert result.entry_id == "entry-42"
        client.add_entry.assert_called_once()

    @patch("engine.nexus.url_ingest.fetch_url")
    def test_ingest_fetch_failure(self, mock_fetch):
        mock_fetch.return_value = {"error": "HTTP 404", "url": "https://example.com"}

        result = ingest_url("https://example.com")
        assert not result.success
        assert "404" in result.error

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.nexus.url_ingest.fetch_url")
    def test_ingest_nexus_failure(self, mock_fetch, mock_nexus):
        mock_fetch.return_value = {
            "title": "Test",
            "markdown": "content",
            "url": "https://example.com",
            "content_length": 7,
        }
        client = MagicMock()
        client.add_entry.side_effect = Exception("Nexus down")
        mock_nexus.return_value = client

        result = ingest_url("https://example.com")
        assert not result.success
        assert "Nexus down" in result.error


# ── ingest_batch ──────────────────────────────────────────────


class TestIngestBatch:
    """Tests for batch URL ingestion."""

    @patch("engine.nexus.url_ingest.ingest_url")
    def test_batch_processes_all(self, mock_ingest):
        mock_ingest.side_effect = [
            IngestResult(url="https://a.com", success=True, title="A"),
            IngestResult(url="https://b.com", success=False, error="fail"),
        ]
        batch = ingest_batch(["https://a.com", "https://b.com"])
        assert len(batch.results) == 2
        assert batch.succeeded == 1
        assert batch.failed == 1

    @patch("engine.nexus.url_ingest.ingest_url")
    def test_batch_empty_list(self, mock_ingest):
        batch = ingest_batch([])
        assert len(batch.results) == 0
        mock_ingest.assert_not_called()
