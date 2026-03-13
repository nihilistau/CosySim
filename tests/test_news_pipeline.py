"""Tests for the news pipeline system.

All DedupFilter tests use ``tmp_path`` to isolate SQLite state between tests.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
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


@pytest.fixture()
def dedup_db(tmp_path: Path) -> Path:
    """Return an isolated SQLite path for DedupFilter."""
    return tmp_path / "test_dedup.db"


# ──── NewsItem Tests ────

def test_news_item_creation():
    from engine.nexus.news.news_models import NewsItem
    item = NewsItem(
        title="GPT-5 Released",
        url="https://example.com/gpt5",
        summary="OpenAI released GPT-5",
        published_at=datetime.now(timezone.utc),
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

def test_dedup_filter_removes_duplicates(dedup_db):
    from engine.nexus.news.dedup_filter import DedupFilter
    from engine.nexus.news.news_models import NewsItem

    item1 = NewsItem("Title A", "https://a.com/1", "Summary", datetime.now(timezone.utc), "Source", "tech")
    item2 = NewsItem("Title A", "https://a.com/1", "Summary", datetime.now(timezone.utc), "Source", "tech")
    item3 = NewsItem("Title B", "https://a.com/2", "Summary", datetime.now(timezone.utc), "Source", "tech")

    dedup = DedupFilter(db_path=dedup_db)
    fresh = dedup.filter([item1, item2, item3])
    assert len(fresh) == 2


def test_dedup_filter_fingerprints_items(dedup_db):
    from engine.nexus.news.dedup_filter import DedupFilter
    from engine.nexus.news.news_models import NewsItem

    item = NewsItem("Title", "https://a.com/1", "", datetime.now(timezone.utc), "S", "tech")
    dedup = DedupFilter(db_path=dedup_db)
    filtered = dedup.filter([item])
    assert filtered[0].fingerprint != ""


def test_dedup_filter_empty_input(dedup_db):
    from engine.nexus.news.dedup_filter import DedupFilter
    dedup = DedupFilter(db_path=dedup_db)
    assert dedup.filter([]) == []


def test_dedup_filter_mark_seen(dedup_db):
    from engine.nexus.news.dedup_filter import DedupFilter, _fingerprint
    from engine.nexus.news.news_models import NewsItem

    item = NewsItem("Title", "https://a.com/1", "", datetime.now(timezone.utc), "S", "tech")
    fp = _fingerprint(item)

    dedup = DedupFilter(db_path=dedup_db)
    dedup.mark_seen([fp])
    fresh = dedup.filter([item])
    assert len(fresh) == 0  # already seen


def test_dedup_filter_get_seen_fingerprints(dedup_db):
    from engine.nexus.news.dedup_filter import DedupFilter
    from engine.nexus.news.news_models import NewsItem

    item = NewsItem("Title", "https://a.com/1", "", datetime.now(timezone.utc), "S", "tech")
    dedup = DedupFilter(db_path=dedup_db)
    dedup.filter([item])
    fps = dedup.get_seen_fingerprints()
    assert len(fps) == 1


def test_dedup_filter_persistence_across_instances(dedup_db):
    """Fingerprints survive across DedupFilter instances (SQLite persistence)."""
    from engine.nexus.news.dedup_filter import DedupFilter
    from engine.nexus.news.news_models import NewsItem

    item = NewsItem("Persist", "https://persist.com/1", "", datetime.now(timezone.utc), "S", "tech")

    # Instance 1 sees the item
    d1 = DedupFilter(db_path=dedup_db)
    d1.filter([item])
    assert d1.count() == 1

    # Instance 2 (same DB) should recognise it as seen
    d2 = DedupFilter(db_path=dedup_db)
    assert d2.count() == 1
    fresh = d2.filter([item])
    assert len(fresh) == 0


def test_dedup_filter_prune(dedup_db):
    """Expired fingerprints are removed by prune()."""
    from engine.nexus.news.dedup_filter import DedupFilter
    from engine.nexus.news.news_models import NewsItem
    import sqlite3

    item = NewsItem("Old", "https://old.com/1", "", datetime.now(timezone.utc), "S", "tech")
    dedup = DedupFilter(db_path=dedup_db, retention_days=1)
    dedup.filter([item])
    assert dedup.count() == 1

    # Backdate the fingerprint to simulate age
    conn = sqlite3.connect(str(dedup_db))
    conn.execute(
        "UPDATE seen_fingerprints SET first_seen = ?",
        (time.time() - 200_000,),  # ~2.3 days ago
    )
    conn.commit()
    conn.close()

    pruned = dedup.prune()
    assert pruned == 1
    assert dedup.count() == 0


def test_dedup_filter_count(dedup_db):
    """count() returns the number of tracked fingerprints."""
    from engine.nexus.news.dedup_filter import DedupFilter
    from engine.nexus.news.news_models import NewsItem

    dedup = DedupFilter(db_path=dedup_db)
    assert dedup.count() == 0

    items = [
        NewsItem(f"T{i}", f"https://x.com/{i}", "", datetime.now(timezone.utc), "S", "tech")
        for i in range(5)
    ]
    dedup.filter(items)
    assert dedup.count() == 5


# ──── Source Registry Tests ────

def test_source_registry_returns_sources():
    from engine.nexus.news_sources import get_sources
    sources = get_sources("ai_research")
    assert len(sources) > 0
    assert "rss" in sources[0]
    assert "name" in sources[0]


def test_source_registry_unknown_category():
    from engine.nexus.news_sources import get_sources
    assert get_sources("nonexistent") == []


def test_source_registry_curated_questions():
    from engine.nexus.news_sources import get_questions
    questions = get_questions("ai_research")
    assert len(questions) >= 5
    assert all(isinstance(q, str) for q in questions)


def test_source_registry_all_categories():
    from engine.nexus.news_sources import get_all_categories
    cats = get_all_categories()
    assert "ai_ml" in cats
    assert "science" in cats
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


def test_rss_fetcher_circuit_breaker():
    """After MAX_CONSECUTIVE_FAILURES, a source is skipped (tripped)."""
    from engine.nexus.news.rss_fetcher import RSSFetcher, _SourceHealth

    fetcher = RSSFetcher(
        rate_limit_seconds=0,
        max_retries=1,
        max_consecutive_failures=3,
    )

    # Simulate 3 consecutive failures for a URL
    health = fetcher._get_health("https://broken.rss/feed")
    for _ in range(3):
        health.record_failure("timeout")

    assert health.is_tripped(3, 3600)
    assert health.consecutive_failures == 3


def test_rss_fetcher_circuit_breaker_resets_on_success():
    """A successful fetch resets the consecutive failure counter."""
    from engine.nexus.news.rss_fetcher import _SourceHealth

    health = _SourceHealth()
    health.record_failure("e1")
    health.record_failure("e2")
    assert health.consecutive_failures == 2

    health.record_success()
    assert health.consecutive_failures == 0
    assert health.total_successes == 1


def test_rss_fetcher_source_health_report():
    """get_source_health() returns per-source error summaries."""
    from engine.nexus.news.rss_fetcher import RSSFetcher

    fetcher = RSSFetcher(rate_limit_seconds=0)
    h = fetcher._get_health("https://test.com/feed")
    h.record_success()
    h.record_failure("timeout")

    report = fetcher.get_source_health()
    assert "https://test.com/feed" in report
    assert report["https://test.com/feed"]["error_count"] == 1
    assert report["https://test.com/feed"]["total_successes"] == 1


def test_rss_fetcher_skips_tripped_sources():
    """Sources with open circuit-breaker are skipped in fetch_category."""
    from engine.nexus.news.rss_fetcher import RSSFetcher

    sample_rss = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item><title>A</title><link>https://a.com/1</link><description>X</description></item>
    </channel></rss>"""

    fetcher = RSSFetcher(
        rate_limit_seconds=0,
        max_retries=1,
        max_consecutive_failures=2,
    )

    call_count = 0
    original_fetch = None

    def counting_fetch(url, **kw):
        nonlocal call_count
        call_count += 1
        return sample_rss

    with patch("engine.nexus.news.rss_fetcher._fetch_url", side_effect=counting_fetch):
        from engine.nexus.news_sources import get_sources
        sources = get_sources("ai_research")
        if sources:
            # Trip the first source
            first_url = sources[0]["rss"]
            h = fetcher._get_health(first_url)
            for _ in range(3):
                h.record_failure("test")

        items = fetcher.fetch_category("ai_research", limit=10)
        # call_count should be less than total sources (one was skipped)
        if len(sources) > 1:
            assert call_count < len(sources)


# ──── NewsPipeline Tests ────

def test_news_pipeline_singleton():
    import engine.nexus.news.news_pipeline as module
    module._pipeline_instance = None
    p1 = module.get_news_pipeline()
    p2 = module.get_news_pipeline()
    assert p1 is p2
    module._pipeline_instance = None


def test_news_pipeline_fetch_category(dedup_db):
    from engine.nexus.news.news_models import NewsItem
    from engine.nexus.news.news_pipeline import NewsPipeline

    mock_items = [
        NewsItem("Title 1", "https://a.com/1", "Summary", datetime.now(timezone.utc), "Src", "tech"),
        NewsItem("Title 2", "https://a.com/2", "Summary", datetime.now(timezone.utc), "Src", "tech"),
    ]

    pipeline = NewsPipeline(db_path=dedup_db)
    with patch.object(pipeline._fetcher, "fetch_category", return_value=mock_items):
        items = pipeline.fetch_category("tech")
        assert len(items) == 2


def test_news_pipeline_store_items_to_nexus(mock_nexus, dedup_db):
    from engine.nexus.news.news_models import NewsItem
    from engine.nexus.news.news_pipeline import NewsPipeline

    items = [
        NewsItem("Title", "https://a.com/1", "Summary", datetime.now(timezone.utc), "Src", "tech"),
    ]
    pipeline = NewsPipeline(db_path=dedup_db)
    count = pipeline.store_items_to_nexus(items)
    assert count == 1
    mock_nexus.add_entry.assert_called_once()


def test_news_pipeline_store_qa_to_nexus(mock_nexus, dedup_db):
    from engine.nexus.news.news_pipeline import NewsPipeline
    pipeline = NewsPipeline(db_path=dedup_db)
    result = pipeline.store_qa_to_nexus("Question?", "Answer.", "tech")
    assert result is True
    mock_nexus.add_qa.assert_called_once()


def test_news_pipeline_build_digest(dedup_db):
    from engine.nexus.news.news_models import NewsDigest, NewsItem
    from engine.nexus.news.news_pipeline import NewsPipeline

    items = [NewsItem("T", "https://a.com", "S", datetime.now(timezone.utc), "Src", "tech")]
    pipeline = NewsPipeline(db_path=dedup_db)
    digest = pipeline.build_digest(items, "tech")
    assert isinstance(digest, NewsDigest)
    assert digest.category == "tech"
    assert len(digest.items) == 1


def test_news_pipeline_run_fetch_cycle(dedup_db):
    from engine.nexus.news.news_models import NewsItem
    from engine.nexus.news.news_pipeline import NewsPipeline

    mock_item = NewsItem("Title", "https://a.com/1", "Summary", datetime.now(timezone.utc), "Src", "ai_research")
    pipeline = NewsPipeline(db_path=dedup_db)

    with patch.object(pipeline._fetcher, "fetch_category", return_value=[mock_item]):
        report = pipeline.run_fetch_cycle()

    assert "total_items" in report
    assert "total_stored" in report
    assert "categories" in report
    assert "duration_s" in report


def test_news_pipeline_get_latest_digest_with_results(mock_nexus, dedup_db):
    from engine.nexus.news.news_pipeline import NewsPipeline

    mock_nexus.search.return_value = [
        {"title": "AI news", "content": "OpenAI released GPT-5 today."},
    ]
    pipeline = NewsPipeline(db_path=dedup_db)
    result = pipeline.get_latest_digest("ai_research")
    assert "AI" in result or "ai" in result.lower()


def test_news_pipeline_get_latest_digest_empty(mock_nexus, dedup_db):
    from engine.nexus.news.news_pipeline import NewsPipeline
    mock_nexus.search.return_value = []
    pipeline = NewsPipeline(db_path=dedup_db)
    result = pipeline.get_latest_digest("ai_research")
    assert "No news" in result or "available" in result


# ──── Metrics Integration Tests ────

def test_news_pipeline_records_metrics(dedup_db):
    """run_fetch_cycle records news.cycle.duration_s metric."""
    from engine.nexus.news.news_models import NewsItem
    from engine.nexus.news.news_pipeline import NewsPipeline

    recorded: list = []

    def mock_record(name, value, tags=None):
        recorded.append((name, value, tags))

    mock_mm = MagicMock()
    mock_mm.record = mock_record

    mock_item = NewsItem("M", "https://m.com/1", "S", datetime.now(timezone.utc), "Src", "tech")
    pipeline = NewsPipeline(db_path=dedup_db)

    with patch("engine.nexus.meta_metrics.get_meta_metrics", return_value=mock_mm):
        with patch.object(pipeline._fetcher, "fetch_category", return_value=[mock_item]):
            report = pipeline.run_fetch_cycle()

    metric_names = [r[0] for r in recorded]
    assert "news.fetch.total" in metric_names
    assert "news.fetch.fresh" in metric_names
    assert "news.dedup.filtered" in metric_names
    assert "news.cycle.duration_s" in metric_names


def test_news_metrics_category_exists():
    """NEWS_METRICS is defined and included in ALL_METRIC_NAMES."""
    from engine.nexus.meta_metrics import NEWS_METRICS, ALL_METRIC_NAMES
    assert len(NEWS_METRICS) >= 10
    assert "news.fetch.total" in NEWS_METRICS
    assert "news.cycle.duration_s" in NEWS_METRICS
    for name in NEWS_METRICS:
        assert name in ALL_METRIC_NAMES
