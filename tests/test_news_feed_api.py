"""Tests for engine.nexus.news_feed_api — REST endpoints for curated news."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.news_feed_api import create_news_blueprint, _fetch_news_from_nexus


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def app():
    """Flask app with news blueprint registered."""
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = True
    bp = create_news_blueprint()
    assert bp is not None
    app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


# ── Blueprint Creation ─────────────────────────────────────────────────


class TestBlueprintCreation:
    """Test blueprint factory."""

    def test_creates_blueprint(self):
        """create_news_blueprint returns a Blueprint."""
        bp = create_news_blueprint()
        assert bp is not None
        assert bp.name == "news_feed"

    def test_blueprint_has_routes(self):
        """Blueprint registers all expected routes."""
        bp = create_news_blueprint()
        from flask import Flask
        app = Flask(__name__)
        app.register_blueprint(bp)
        urls = [rule.rule for rule in app.url_map.iter_rules()]
        assert "/api/news/latest" in urls
        assert "/api/news/digest" in urls
        assert "/api/news/search" in urls
        assert "/api/news/sources" in urls
        assert "/api/news/stats" in urls


# ── Latest Endpoint ────────────────────────────────────────────────────


class TestLatestEndpoint:
    """Test GET /api/news/latest."""

    @patch("engine.nexus.news_feed_api._fetch_news_from_nexus")
    def test_latest_returns_json(self, mock_fetch, client):
        """Returns JSON with count and articles."""
        mock_fetch.return_value = [
            {"title": "AI News", "content": "...", "category": "ai"},
        ]
        resp = client.get("/api/news/latest")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 1
        assert len(data["articles"]) == 1

    @patch("engine.nexus.news_feed_api._fetch_news_from_nexus")
    def test_latest_with_limit(self, mock_fetch, client):
        """Passes limit parameter through."""
        mock_fetch.return_value = []
        client.get("/api/news/latest?limit=5")
        mock_fetch.assert_called_once_with(limit=5, category="")

    @patch("engine.nexus.news_feed_api._fetch_news_from_nexus")
    def test_latest_with_category(self, mock_fetch, client):
        """Passes category parameter through."""
        mock_fetch.return_value = []
        client.get("/api/news/latest?category=ai")
        mock_fetch.assert_called_once_with(limit=20, category="ai")

    @patch("engine.nexus.news_feed_api._fetch_news_from_nexus")
    def test_latest_empty(self, mock_fetch, client):
        """Empty results return count 0."""
        mock_fetch.return_value = []
        resp = client.get("/api/news/latest")
        assert resp.get_json()["count"] == 0


# ── Digest Endpoint ────────────────────────────────────────────────────


class TestDigestEndpoint:
    """Test GET /api/news/digest."""

    @patch("engine.nexus.client.get_nexus_client")
    def test_digest_returns_content(self, mock_client, client):
        """Returns digest content from Nexus."""
        nexus = MagicMock()
        nexus.search.return_value = [
            {"title": "Daily Digest", "content": "# Today's News\n...", "created_at": "2024-01-01"},
        ]
        mock_client.return_value = nexus

        resp = client.get("/api/news/digest")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "digest" in data
        assert "Today's News" in data["digest"]

    @patch("engine.nexus.client.get_nexus_client")
    def test_digest_no_results(self, mock_client, client):
        """Returns fallback when no digest available."""
        nexus = MagicMock()
        nexus.search.return_value = []
        mock_client.return_value = nexus

        resp = client.get("/api/news/digest")
        data = resp.get_json()
        assert "No digest available" in data["digest"]


# ── Search Endpoint ────────────────────────────────────────────────────


class TestSearchEndpoint:
    """Test GET /api/news/search."""

    def test_search_missing_query(self, client):
        """Missing q parameter returns 400."""
        resp = client.get("/api/news/search")
        assert resp.status_code == 400

    @patch("engine.nexus.client.get_nexus_client")
    def test_search_with_query(self, mock_client, client):
        """Search returns matching articles."""
        nexus = MagicMock()
        nexus.search.return_value = [
            {"title": "LLM News", "content": "Content about LLMs", "category": "ai", "tags": [], "created_at": "2024-01-01"},
        ]
        mock_client.return_value = nexus

        resp = client.get("/api/news/search?q=llm")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["query"] == "llm"
        assert data["count"] == 1


# ── Sources Endpoint ───────────────────────────────────────────────────


class TestSourcesEndpoint:
    """Test GET /api/news/sources."""

    @patch("engine.nexus.news_sources.get_news_registry")
    def test_sources_list(self, mock_registry, client):
        """Returns configured news sources."""
        registry = MagicMock()
        registry.list_sources.return_value = [
            {"id": "hn", "name": "Hacker News", "type": "api"},
        ]
        mock_registry.return_value = registry

        resp = client.get("/api/news/sources")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 1


# ── Stats Endpoint ─────────────────────────────────────────────────────


class TestStatsEndpoint:
    """Test GET /api/news/stats."""

    @patch("engine.nexus.news_sources.get_news_registry")
    def test_stats(self, mock_registry, client):
        """Returns pipeline statistics."""
        registry = MagicMock()
        registry.stats.return_value = {"fetched": 100, "stored": 80}
        mock_registry.return_value = registry

        resp = client.get("/api/news/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["fetched"] == 100


# ── Fetch Helper ───────────────────────────────────────────────────────


class TestFetchHelper:
    """Test _fetch_news_from_nexus helper."""

    @patch("engine.nexus.client.get_nexus_client")
    def test_fetches_from_nexus(self, mock_client):
        """Helper queries Nexus for news."""
        nexus = MagicMock()
        nexus.search.return_value = [
            {"title": "Article", "content": "Text", "category": "ai", "tags": [], "created_at": "2024"},
        ]
        mock_client.return_value = nexus

        articles = _fetch_news_from_nexus(limit=10)
        assert len(articles) == 1
        assert articles[0]["title"] == "Article"

    @patch("engine.nexus.client.get_nexus_client")
    def test_fetches_with_category(self, mock_client):
        """Category is included in search query."""
        nexus = MagicMock()
        nexus.search.return_value = []
        mock_client.return_value = nexus

        _fetch_news_from_nexus(category="python")
        nexus.search.assert_called_once_with("news python", limit=20)

    def test_handles_nexus_failure(self):
        """Returns empty list on Nexus failure."""
        articles = _fetch_news_from_nexus()
        assert isinstance(articles, list)

    @patch("engine.nexus.client.get_nexus_client")
    def test_truncates_content(self, mock_client):
        """Content is truncated to 500 chars."""
        nexus = MagicMock()
        nexus.search.return_value = [
            {"title": "Long", "content": "x" * 1000, "category": "", "tags": [], "created_at": ""},
        ]
        mock_client.return_value = nexus

        articles = _fetch_news_from_nexus()
        assert len(articles[0]["content"]) <= 500
