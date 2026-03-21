"""Tests for engine.nexus.news.nexus_feed — NexusFeed.

NexusFeed reads articles from Nexus (via _nexus_search) and stores
interactions in a local SQLite DB. Tests mock _nexus_search to avoid
live Nexus calls, and use tmp_path for DB isolation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_nexus_result(
    url: str = "https://example.com/article",
    category: str = "ai_ml",
    published_offset: int = 0,
) -> Dict:
    """Fake Nexus search result dict matching _nexus_result_to_feed_item() format."""
    return {
        "id": f"entry-{abs(hash(url)) % 100000}",
        "title": f"Article {url.split('/')[-1]}",
        "content": f"Source: {url}\n\nSummary for {url}",
        "category": "news",
        "tags": [category],
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00",
            time.gmtime(time.time() - published_offset),
        ),
    }


def _make_n_results(n: int, category: str = "ai_ml") -> List[Dict]:
    return [
        _make_nexus_result(f"https://example.com/{i}", category, i * 600)
        for i in range(n)
    ]


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def feed(tmp_path: Path):
    """NexusFeed with isolated DB, _nexus_search always returns empty list."""
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "test_feed.db")
    # Default: no results
    nf._nexus_search = MagicMock(return_value=[])
    return nf


@pytest.fixture()
def feed_with_articles(tmp_path: Path):
    """NexusFeed that returns 5 fake articles from _nexus_search."""
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "test_feed_articles.db")
    results = _make_n_results(5, "ai_ml")
    nf._nexus_search = MagicMock(return_value=results)
    return nf


# ── Test: get_feed ────────────────────────────────────────────────────────────

def test_get_feed_empty_nexus(feed):
    items = feed.get_feed(limit=10)
    assert items == []


def test_get_feed_returns_feed_items(feed_with_articles):
    from engine.nexus.news.nexus_feed import FeedItem
    items = feed_with_articles.get_feed(limit=10)
    assert len(items) == 5
    for item in items:
        assert isinstance(item, FeedItem)


def test_get_feed_respects_limit(tmp_path):
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "lim.db")
    results = _make_n_results(10)
    nf._nexus_search = MagicMock(return_value=results)
    items = nf.get_feed(limit=3)
    assert len(items) <= 3


def test_get_feed_items_have_url(feed_with_articles):
    items = feed_with_articles.get_feed(limit=5)
    for item in items:
        assert item.url


def test_get_feed_ordered_by_published_descending(tmp_path):
    """get_feed should return most-recent first."""
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "ord.db")
    # Older articles have higher offset
    results = _make_n_results(5)
    nf._nexus_search = MagicMock(return_value=results)
    items = nf.get_feed(limit=5)
    times = [i.published_at for i in items]
    assert times == sorted(times, reverse=True)


def test_get_feed_calls_nexus_search(feed):
    feed.get_feed(category="ai_ml", limit=5)
    assert feed._nexus_search.called


# ── Test: get_trending_feed ───────────────────────────────────────────────────

def test_get_trending_feed_returns_list(feed):
    """With no trending topics and empty Nexus, should still return a list."""
    # Mock trends to return empty topics → falls back to get_feed
    feed._trends = MagicMock()
    feed._trends.get_trending_topics.return_value = []
    items = feed.get_trending_feed(limit=5)
    assert isinstance(items, list)


def test_get_trending_feed_with_topics(tmp_path):
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "trend.db")
    nf._nexus_search = MagicMock(return_value=_make_n_results(2))
    nf._trends = MagicMock()
    nf._trends.get_trending_topics.return_value = [
        {"topic": "GPT-4", "article_count": 10},
    ]
    items = nf.get_trending_feed(limit=5)
    assert isinstance(items, list)


# ── Test: get_personalized_feed ───────────────────────────────────────────────

def test_get_personalized_feed_no_interests(feed):
    items = feed.get_personalized_feed(interests=[])
    assert isinstance(items, list)


def test_get_personalized_feed_with_interests(tmp_path):
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "pers.db")
    nf._nexus_search = MagicMock(return_value=_make_n_results(2))
    items = nf.get_personalized_feed(interests=["AI", "LLM"], limit=5)
    assert isinstance(items, list)


# ── Test: mark_read ───────────────────────────────────────────────────────────

def test_mark_read_doesnt_raise(feed):
    feed.mark_read("https://example.com/article-1")  # should not raise


def test_mark_read_records_to_db(tmp_path):
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "read.db")
    nf._nexus_search = MagicMock(return_value=[])
    nf.mark_read("https://test.com/a")

    with nf._conn() as conn:
        row = conn.execute(
            "SELECT action FROM article_interactions WHERE article_id=?",
            ("https://test.com/a",),
        ).fetchone()
    assert row is not None
    assert row["action"] == "read"


def test_mark_read_nonexistent_url_ok(feed):
    feed.mark_read("https://nonexistent.com")  # no error expected


# ── Test: mark_useful ─────────────────────────────────────────────────────────

def test_mark_useful_true(tmp_path):
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "useful.db")
    nf._nexus_search = MagicMock(return_value=[])
    nf.mark_useful("http://x.com", useful=True)

    with nf._conn() as conn:
        row = conn.execute(
            "SELECT action FROM article_interactions WHERE article_id=?",
            ("http://x.com",),
        ).fetchone()
    assert row is not None
    assert row["action"] == "useful"


def test_mark_useful_false(tmp_path):
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "not_useful.db")
    nf._nexus_search = MagicMock(return_value=[])
    nf.mark_useful("http://y.com", useful=False)

    with nf._conn() as conn:
        row = conn.execute(
            "SELECT action FROM article_interactions WHERE article_id=?",
            ("http://y.com",),
        ).fetchone()
    assert row is not None
    assert row["action"] == "not_useful"


# ── Test: get_daily_digest ────────────────────────────────────────────────────

def test_get_daily_digest_structure(tmp_path):
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "digest.db")
    nf._nexus_search = MagicMock(return_value=_make_n_results(3))
    nf._trends = MagicMock()
    nf._trends.get_trending_topics.return_value = []
    digest = nf.get_daily_digest()
    assert isinstance(digest, dict)
    assert "date" in digest
    assert "top_stories" in digest
    assert "trending_topics" in digest
    assert "categories" in digest


def test_get_daily_digest_total_articles(tmp_path):
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "digest2.db")
    nf._nexus_search = MagicMock(return_value=_make_n_results(5))
    nf._trends = MagicMock()
    nf._trends.get_trending_topics.return_value = []
    digest = nf.get_daily_digest()
    assert "total_articles" in digest
    assert isinstance(digest["total_articles"], int)


def test_get_daily_digest_empty_nexus(feed):
    feed._trends = MagicMock()
    feed._trends.get_trending_topics.return_value = []
    digest = feed.get_daily_digest()
    assert digest["top_stories"] == []


# ── Test: get_interest_profile ────────────────────────────────────────────────

def test_get_interest_profile_structure(feed):
    profile = feed.get_interest_profile()
    assert isinstance(profile, dict)
    assert "top_categories" in profile
    assert "top_keywords" in profile
    assert "read_count" in profile
    assert "useful_count" in profile


def test_get_interest_profile_empty_db(feed):
    profile = feed.get_interest_profile()
    assert profile["read_count"] == 0
    assert profile["useful_count"] == 0


def test_get_interest_profile_after_interactions(tmp_path):
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "profile.db")
    nf._nexus_search = MagicMock(return_value=[])

    nf._record_interaction("url1", action="read", category="ai_ml")
    nf._record_interaction("url2", action="useful", category="ai_ml")
    nf._record_interaction("url3", action="useful", category="tech")

    profile = nf.get_interest_profile()
    assert profile["read_count"] >= 1
    assert profile["useful_count"] >= 2
    assert "ai_ml" in profile["top_categories"]


# ── Test: update_interest_profile ────────────────────────────────────────────

def test_update_interest_profile_stores_keywords(tmp_path):
    from engine.nexus.news.nexus_feed import NexusFeed
    nf = NexusFeed(db_path=tmp_path / "update_profile.db")
    nf._nexus_search = MagicMock(return_value=[])
    nf.update_interest_profile({"top_keywords": ["LLM", "transformer"]})
    profile = nf.get_interest_profile()
    assert "LLM" in profile.get("top_keywords", [])


def test_update_interest_profile_doesnt_raise(feed):
    feed.update_interest_profile({"action": "useful", "category": "ai_ml"})


# ── Test: sync_to_nexus ───────────────────────────────────────────────────────

def test_sync_to_nexus_returns_string_or_empty(feed):
    with patch("engine.nexus.news.realtime_distiller.get_realtime_distiller") as mock_d:
        mock_d.return_value.distill_article.return_value = "entry-abc"
        result = feed.sync_to_nexus({"url": "http://x.com", "title": "T"})
    assert isinstance(result, str)


def test_sync_to_nexus_empty_url_returns_empty(feed):
    result = feed.sync_to_nexus({})
    assert result == ""


def test_sync_to_nexus_distillation_failure_returns_empty(feed):
    with patch("engine.nexus.news.realtime_distiller.get_realtime_distiller") as mock_d:
        mock_d.return_value.distill_article.side_effect = RuntimeError("fail")
        result = feed.sync_to_nexus({"url": "http://x.com", "title": "T"})
    assert result == ""


# ── Test: singleton ────────────────────────────────────────────────────────────

def test_get_nexus_feed_returns_instance():
    from engine.nexus.news.nexus_feed import get_nexus_feed
    nf = get_nexus_feed()
    assert nf is not None


def test_get_nexus_feed_same_instance():
    from engine.nexus.news.nexus_feed import get_nexus_feed
    nf1 = get_nexus_feed()
    nf2 = get_nexus_feed()
    assert nf1 is nf2
