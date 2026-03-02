"""Tests for the news pipeline system."""
from __future__ import annotations
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ──── Fixtures ────

@pytest.fixture(autouse=True)
def mock_nexus(monkeypatch):
    """Mock nexus client to prevent real calls."""
    mock_client = MagicMock()
    mock_client.search.return_value = []
    mock_client.add_entry.return_value = {"id": "test-id"}
    mock_client.add_qa.return_value = {"id": "qa-id"}

    with patch("engine.nexus.news.news_pipeline.get_nexus_client", return_value=mock_client):
        yield mock_client


# ──── NewsItem Tests ────

def test_news_item_creation():
    from engine.nexus.news.news_models import NewsItem
    item = NewsItem(
        title="GPT-5 Released",
        url="https://example.com/gpt5",
        summary="OpenAI released GPT-5",
        published_at=datetime.utcnow(),
        source_name="OpenAI Blog",
        category="ai_research",
    )
    assert item.title == "GPT-5 Released"
    assert item.category == "ai_research"
    assert item.fingerprint == ""


def test_news_digest_creation():
    from engine.nexus.news.news_models import NewsDigest
    d = NewsDigest(category="tech", date="2026-01-15")
    assert d.items == []
    assert d.qa_pairs == []
    assert d.session_id is None


# ──── DedupFilter Tests ────

def test_dedup_filter_removes_duplicates():
    from engine.nexus.news.dedup_filter import DedupFilter
    from engine.nexus.news.news_models import NewsItem

    item1 = NewsItem("Title A", "https://a.com/1", "Summary", datetime.utcnow(), "Source", "tech")
    item2 = NewsItem("Title A", "https://a.com/1", "Summary", datetime.utcnow(), "Source", "tech")
    item3 = NewsItem("Title B", "https://a.com/2", "Summary", datetime.utcnow(), "Source", "tech")

    dedup = DedupFilter()
    fresh = dedup.filter([item1, item2, item3])
    assert len(fresh) == 2


def test_dedup_filter_fingerprints_items():
    from engine.nexus.news.dedup_filter import DedupFilter
    from engine.nexus.news.news_models import NewsItem

    item = NewsItem("Title", "https://a.com/1", "", datetime.utcnow(), "S", "tech")
    dedup = DedupFilter()
    filtered = dedup.filter([item])
    assert filtered[0].fingerprint != ""


def test_dedup_filter_empty_input():
    from engine.nexus.news.dedup_filter import DedupFilter
    dedup = DedupFilter()
    assert dedup.filter([]) == []


def test_dedup_filter_mark_seen():
    from engine.nexus.news.dedup_filter import DedupFilter, _fingerprint
    from engine.nexus.news.news_models import NewsItem

    item = NewsItem("Title", "https://a.com/1", "", datetime.utcnow(), "S", "tech")
    fp = _fingerprint(item)

    dedup = DedupFilter()
    dedup.mark_seen([fp])
    fresh = dedup.filter([item])
    assert len(fresh) == 0  # already seen


def test_dedup_filter_get_seen_fingerprints():
    from engine.nexus.news.dedup_filter import DedupFilter
    from engine.nexus.news.news_models import NewsItem

    item = NewsItem("Title", "https://a.com/1", "", datetime.utcnow(), "S", "tech")
    dedup = DedupFilter()
    dedup.filter([item])
    fps = dedup.get_seen_fingerprints()
    assert len(fps) == 1


# ──── Source Registry Tests ────

def test_source_registry_returns_sources():
    from engine.nexus.news.source_registry import get_sources
    sources = get_sources("ai_research")
    assert len(sources) > 0
    assert "rss" in sources[0]
    assert "name" in sources[0]


def test_source_registry_unknown_category():
    from engine.nexus.news.source_registry import get_sources
    assert get_sources("nonexistent") == []


def test_source_registry_curated_questions():
    from engine.nexus.news.source_registry import get_questions
    questions = get_questions("ai_research")
    assert len(questions) >= 5
    assert all(isinstance(q, str) for q in questions)


def test_source_registry_all_categories():
    from engine.nexus.news.source_registry import get_all_categories
    cats = get_all_categories()
    assert "ai_research" in cats
    assert "tech" in cats
    assert len(cats) >= 3


# ──── RSSFetcher Tests ────

def test_rss_fetcher_fetch_category_success():
    from engine.nexus.news.rss_fetcher import RSSFetcher

    sample_rss = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>Test Article</title>
          <link>https://example.com/article1</link>
          <description>Test description</description>
          <pubDate>Mon, 01 Jan 2026 00:00:00 +0000</pubDate>
        </item>
      </channel>
    </rss>"""

    with patch("engine.nexus.news.rss_fetcher._fetch_url", return_value=sample_rss):
        fetcher = RSSFetcher(rate_limit_seconds=0)
        items = fetcher.fetch_category("ai_research", limit=10)
        assert len(items) >= 1
        assert items[0].title == "Test Article"
        assert items[0].url == "https://example.com/article1"
        assert items[0].category == "ai_research"


def test_rss_fetcher_handles_fetch_failure():
    from engine.nexus.news.rss_fetcher import RSSFetcher
    with patch("engine.nexus.news.rss_fetcher._fetch_url", return_value=None):
        fetcher = RSSFetcher(rate_limit_seconds=0)
        items = fetcher.fetch_category("tech", limit=10)
        assert items == []


def test_rss_fetcher_respects_limit():
    from engine.nexus.news.rss_fetcher import RSSFetcher

    items_xml = "\n".join([
        f"<item><title>Article {i}</title><link>https://example.com/{i}</link>"
        f"<description>Desc</description></item>"
        for i in range(30)
    ])
    rss = f"<?xml version='1.0'?><rss><channel>{items_xml}</channel></rss>"

    with patch("engine.nexus.news.rss_fetcher._fetch_url", return_value=rss):
        fetcher = RSSFetcher(rate_limit_seconds=0)
        items = fetcher.fetch_category("tech", limit=5)
        assert len(items) <= 5


# ──── NewsPipeline Tests ────

def test_news_pipeline_singleton():
    import engine.nexus.news.news_pipeline as module
    module._pipeline_instance = None
    p1 = module.get_news_pipeline()
    p2 = module.get_news_pipeline()
    assert p1 is p2
    module._pipeline_instance = None


def test_news_pipeline_fetch_category():
    from engine.nexus.news.news_models import NewsItem
    from engine.nexus.news.news_pipeline import NewsPipeline

    mock_items = [
        NewsItem("Title 1", "https://a.com/1", "Summary", datetime.utcnow(), "Src", "tech"),
        NewsItem("Title 2", "https://a.com/2", "Summary", datetime.utcnow(), "Src", "tech"),
    ]

    pipeline = NewsPipeline()
    with patch.object(pipeline._fetcher, "fetch_category", return_value=mock_items):
        items = pipeline.fetch_category("tech")
        assert len(items) == 2


def test_news_pipeline_store_items_to_nexus(mock_nexus):
    from engine.nexus.news.news_models import NewsItem
    from engine.nexus.news.news_pipeline import NewsPipeline

    items = [
        NewsItem("Title", "https://a.com/1", "Summary", datetime.utcnow(), "Src", "tech"),
    ]
    pipeline = NewsPipeline()
    count = pipeline.store_items_to_nexus(items)
    assert count == 1
    mock_nexus.add_entry.assert_called_once()


def test_news_pipeline_store_qa_to_nexus(mock_nexus):
    from engine.nexus.news.news_pipeline import NewsPipeline
    pipeline = NewsPipeline()
    result = pipeline.store_qa_to_nexus("Question?", "Answer.", "tech")
    assert result is True
    mock_nexus.add_qa.assert_called_once()


def test_news_pipeline_build_digest():
    from engine.nexus.news.news_models import NewsDigest, NewsItem
    from engine.nexus.news.news_pipeline import NewsPipeline

    items = [NewsItem("T", "https://a.com", "S", datetime.utcnow(), "Src", "tech")]
    pipeline = NewsPipeline()
    digest = pipeline.build_digest(items, "tech")
    assert isinstance(digest, NewsDigest)
    assert digest.category == "tech"
    assert len(digest.items) == 1


def test_news_pipeline_run_fetch_cycle():
    from engine.nexus.news.news_models import NewsItem
    from engine.nexus.news.news_pipeline import NewsPipeline

    mock_item = NewsItem("Title", "https://a.com/1", "Summary", datetime.utcnow(), "Src", "ai_research")
    pipeline = NewsPipeline()

    with patch.object(pipeline._fetcher, "fetch_category", return_value=[mock_item]):
        report = pipeline.run_fetch_cycle()

    assert "total_items" in report
    assert "total_stored" in report
    assert "categories" in report


def test_news_pipeline_get_latest_digest_with_results(mock_nexus):
    from engine.nexus.news.news_pipeline import NewsPipeline

    mock_nexus.search.return_value = [
        {"title": "AI news", "content": "OpenAI released GPT-5 today."},
    ]
    pipeline = NewsPipeline()
    result = pipeline.get_latest_digest("ai_research")
    assert "AI" in result or "ai" in result.lower()


def test_news_pipeline_get_latest_digest_empty(mock_nexus):
    from engine.nexus.news.news_pipeline import NewsPipeline
    mock_nexus.search.return_value = []
    pipeline = NewsPipeline()
    result = pipeline.get_latest_digest("ai_research")
    assert "No news" in result or "available" in result
