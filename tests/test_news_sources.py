"""Tests for the news source registry module."""
from __future__ import annotations

import json
import textwrap
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.news_sources import (
    NewsArticle,
    NewsSource,
    NewsSourceRegistry,
)


# ──── Fixtures ────────────────────────────────────────────────────────────

SAMPLE_CONFIG = {
    "enabled": True,
    "fetch_interval_hours": 8,
    "max_articles_per_fetch": 30,
    "max_article_age_hours": 48,
    "categories": ["ai_ml", "local_inference"],
    "sources": [
        {
            "id": "hn_top",
            "name": "Hacker News - Top",
            "type": "api",
            "url": "https://hacker-news.firebaseio.com/v0/topstories.json",
            "category": "ai_ml",
            "enabled": True,
            "quality_score": 0.9,
            "max_items": 5,
        },
        {
            "id": "reddit_localllama",
            "name": "Reddit - LocalLLaMA",
            "type": "rss",
            "url": "https://www.reddit.com/r/LocalLLaMA/.rss",
            "category": "local_inference",
            "enabled": True,
            "quality_score": 0.8,
            "max_items": 5,
        },
        {
            "id": "disabled_source",
            "name": "Disabled",
            "type": "rss",
            "url": "https://example.com/rss",
            "category": "ai_ml",
            "enabled": False,
            "quality_score": 0.5,
            "max_items": 5,
        },
    ],
    "keyword_filters": {
        "include": ["llm", "inference", "agent"],
        "exclude": ["crypto", "blockchain"],
    },
}


@pytest.fixture
def registry():
    """Create a NewsSourceRegistry loaded from sample config."""
    with patch.object(NewsSourceRegistry, "load_sources"):
        reg = NewsSourceRegistry()
    reg._config = SAMPLE_CONFIG
    reg._sources = {}
    for src_data in SAMPLE_CONFIG["sources"]:
        source = NewsSource(
            id=src_data["id"],
            name=src_data["name"],
            type=src_data["type"],
            url=src_data["url"],
            category=src_data["category"],
            enabled=src_data["enabled"],
            quality_score=src_data["quality_score"],
            max_items=src_data["max_items"],
        )
        reg._sources[source.id] = source
    return reg


# ──── Load Sources ────────────────────────────────────────────────────────

def test_load_sources_from_config(tmp_path):
    """Loading sources from YAML config populates the registry."""
    import yaml

    yaml_content = {"news": SAMPLE_CONFIG}
    config_file = tmp_path / "news_sources.yaml"
    config_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

    with patch.object(NewsSourceRegistry, "load_sources"):
        reg = NewsSourceRegistry()

    mock_cfg = MagicMock()
    mock_cfg.get.return_value = SAMPLE_CONFIG
    with patch("engine.config.get_config", return_value=mock_cfg):
        count = NewsSourceRegistry.load_sources(reg)

    assert count == 3
    assert "hn_top" in reg._sources
    assert "reddit_localllama" in reg._sources


def test_load_sources_yaml_fallback(tmp_path):
    """Fallback YAML loading works when get_config fails."""
    import yaml

    yaml_content = {"news": SAMPLE_CONFIG}
    config_file = tmp_path / "news_sources.yaml"
    config_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

    with patch.object(NewsSourceRegistry, "load_sources"):
        reg = NewsSourceRegistry()

    with (
        patch("engine.config.get_config", side_effect=Exception("no config")),
        patch.object(
            NewsSourceRegistry,
            "_load_yaml_fallback",
            return_value=SAMPLE_CONFIG,
        ),
    ):
        count = NewsSourceRegistry.load_sources(reg)

    assert count == 3


# ──── List Sources ────────────────────────────────────────────────────────

def test_list_sources_all(registry):
    """Listing sources returns all enabled sources by default."""
    sources = registry.list_sources()
    assert len(sources) == 2
    ids = {s.id for s in sources}
    assert "disabled_source" not in ids


def test_list_sources_with_category(registry):
    """Listing sources with category filter returns matching sources."""
    sources = registry.list_sources(category="local_inference")
    assert len(sources) == 1
    assert sources[0].id == "reddit_localllama"


def test_list_sources_include_disabled(registry):
    """Listing sources with enabled_only=False includes disabled."""
    sources = registry.list_sources(enabled_only=False)
    assert len(sources) == 3


# ──── Get Source ──────────────────────────────────────────────────────────

def test_get_source_exists(registry):
    """Getting an existing source returns it."""
    source = registry.get_source("hn_top")
    assert source is not None
    assert source.name == "Hacker News - Top"


def test_get_source_missing(registry):
    """Getting a missing source returns None."""
    assert registry.get_source("nonexistent") is None


# ──── Add / Remove Source ─────────────────────────────────────────────────

def test_add_source(registry):
    """Adding a new source succeeds."""
    new_source = NewsSource(id="test_src", name="Test", type="rss", url="https://example.com")
    assert registry.add_source(new_source) is True
    assert registry.get_source("test_src") is not None


def test_add_source_duplicate(registry):
    """Adding a source with an existing ID fails."""
    dup = NewsSource(id="hn_top", name="Duplicate")
    assert registry.add_source(dup) is False


def test_remove_source(registry):
    """Removing an existing source succeeds."""
    assert registry.remove_source("hn_top") is True
    assert registry.get_source("hn_top") is None


def test_remove_source_missing(registry):
    """Removing a nonexistent source fails."""
    assert registry.remove_source("nonexistent") is False


# ──── Fetch HN ────────────────────────────────────────────────────────────

def test_fetch_hn(registry):
    """Fetching from HN API returns articles from mocked responses."""
    story_ids = [101, 102, 103]
    item_101 = {"title": "LLM News", "url": "https://example.com/1", "score": 200, "time": 1700000000}
    item_102 = {"title": "Agent Framework", "url": "https://example.com/2", "score": 150, "time": 1700000001}
    item_103 = {"title": "Python Update", "url": "https://example.com/3", "score": 100, "time": 1700000002}

    def mock_json(url):
        if "topstories" in url:
            return story_ids
        if "101" in url:
            return item_101
        if "102" in url:
            return item_102
        if "103" in url:
            return item_103
        return None

    with patch.object(registry, "_http_get_json", side_effect=mock_json):
        articles = registry.fetch_source("hn_top")

    assert len(articles) == 3
    assert articles[0].title == "LLM News"
    assert articles[0].score == 200.0
    assert articles[0].source_id == "hn_top"


def test_fetch_hn_bad_response(registry):
    """HN fetch returns empty list when API returns non-list."""
    with patch.object(registry, "_http_get_json", return_value=None):
        articles = registry.fetch_source("hn_top")
    assert articles == []


# ──── Fetch RSS ───────────────────────────────────────────────────────────

SAMPLE_RSS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>LocalLLaMA</title>
        <item>
          <title>New GGUF quantization method</title>
          <link>https://reddit.com/r/LocalLLaMA/1</link>
          <description>A new quantization approach for local inference</description>
          <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
        </item>
        <item>
          <title>LMStudio 0.3 released</title>
          <link>https://reddit.com/r/LocalLLaMA/2</link>
          <description>Major update to LMStudio</description>
          <pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
""")


def test_fetch_rss(registry):
    """RSS fetch parses items from XML feed."""
    with patch.object(registry, "_http_get_text", return_value=SAMPLE_RSS):
        articles = registry.fetch_source("reddit_localllama")

    assert len(articles) == 2
    assert articles[0].title == "New GGUF quantization method"
    assert articles[0].url == "https://reddit.com/r/LocalLLaMA/1"
    assert articles[0].category == "local_inference"


def test_fetch_rss_empty(registry):
    """RSS fetch returns empty list on empty response."""
    with patch.object(registry, "_http_get_text", return_value=""):
        articles = registry.fetch_source("reddit_localllama")
    assert articles == []


def test_fetch_rss_bad_xml(registry):
    """RSS fetch returns empty list on malformed XML."""
    with patch.object(registry, "_http_get_text", return_value="<not><valid>"):
        articles = registry.fetch_source("reddit_localllama")
    assert articles == []


# ──── Filter Articles ─────────────────────────────────────────────────────

def test_filter_articles_include(registry):
    """Filter keeps articles matching category include keywords.

    Uses category_filters per-category include lists (v0.67 design).
    Articles with a category not in category_filters pass without include filtering.
    """
    # Temporarily set category_filters so ai_ml articles are filtered by keywords
    registry._config = {
        **SAMPLE_CONFIG,
        "category_filters": {
            "ai_ml": {"include": ["llm", "inference", "agent"]},
        },
    }
    articles = [
        NewsArticle(title="New LLM benchmark", source_id="hn_top", category="ai_ml"),
        NewsArticle(title="Cooking recipes", source_id="hn_top", category="ai_ml"),
        NewsArticle(title="Agent framework released", source_id="hn_top", category="ai_ml"),
    ]
    filtered = registry.filter_articles(articles)
    assert len(filtered) == 2
    titles = {a.title for a in filtered}
    assert "Cooking recipes" not in titles


def test_filter_articles_exclude(registry):
    """Filter removes articles matching exclude keywords."""
    articles = [
        NewsArticle(title="LLM crypto integration", source_id="hn_top"),
        NewsArticle(title="LLM inference guide", source_id="hn_top"),
    ]
    filtered = registry.filter_articles(articles)
    assert len(filtered) == 1
    assert filtered[0].title == "LLM inference guide"


def test_filter_articles_custom_keywords(registry):
    """Filter uses custom keywords when provided."""
    articles = [
        NewsArticle(title="Python 3.13 released", source_id="hn_top"),
        NewsArticle(title="Rust update", source_id="hn_top"),
    ]
    filtered = registry.filter_articles(articles, keywords=["python"])
    assert len(filtered) == 1
    assert filtered[0].title == "Python 3.13 released"


# ──── Score Relevance ─────────────────────────────────────────────────────

def test_score_relevance_high(registry):
    """Article matching multiple keywords gets a higher score."""
    article = NewsArticle(
        title="LLM inference agent benchmark",
        source_id="hn_top",
        score=500,
    )
    score = registry.score_relevance(article)
    assert score > 0.0
    assert score <= 1.0


def test_score_relevance_no_match(registry):
    """Article matching no keywords gets a low score."""
    article = NewsArticle(title="Cooking tips", source_id="hn_top")
    score = registry.score_relevance(article)
    assert score < 0.1


def test_score_relevance_no_config(registry):
    """With no keyword config, returns the source quality_score as base score."""
    registry._config = {}
    article = NewsArticle(title="Anything", source_id="hn_top")
    score = registry.score_relevance(article)
    # hn_top has quality_score=0.9 in config; with no keywords, quality is returned
    assert 0.0 < score <= 1.0


# ──── Stats ───────────────────────────────────────────────────────────────

def test_stats_initial(registry):
    """Stats returns correct initial state."""
    result = registry.stats()
    assert result["total_sources"] == 3
    assert result["enabled_sources"] == 2
    assert "hn_top" in result["sources"]
    assert result["sources"]["hn_top"]["fetch_count"] == 0


def test_stats_after_fetch(registry):
    """Stats reflect fetch count after a successful fetch."""
    with patch.object(registry, "_http_get_json", return_value=[]):
        registry.fetch_source("hn_top")

    result = registry.stats()
    assert result["sources"]["hn_top"]["fetch_count"] == 1
    assert result["sources"]["hn_top"]["last_fetched"] is not None


def test_stats_after_error(registry):
    """Stats reflect error count after a failed fetch."""
    with patch.object(registry, "_http_get_json", side_effect=Exception("timeout")):
        registry.fetch_source("hn_top")

    result = registry.stats()
    assert result["sources"]["hn_top"]["error_count"] == 1


# ──── Get Config ──────────────────────────────────────────────────────────

def test_get_config_returns_dict(registry):
    """get_config returns the news configuration dictionary."""
    cfg = registry.get_config()
    assert cfg["enabled"] is True
    assert "sources" in cfg


# ──── Fetch All ───────────────────────────────────────────────────────────

def test_fetch_all(registry):
    """fetch_all aggregates articles from all enabled sources."""
    def mock_dispatch(source):
        return [NewsArticle(title=f"From {source.id}", source_id=source.id)]

    with patch.object(registry, "_dispatch_fetch", side_effect=mock_dispatch):
        articles = registry.fetch_all()

    assert len(articles) == 2
    ids = {a.source_id for a in articles}
    assert "hn_top" in ids
    assert "reddit_localllama" in ids
    assert "disabled_source" not in ids


def test_fetch_all_with_category(registry):
    """fetch_all with category filter fetches only matching sources."""
    def mock_dispatch(source):
        return [NewsArticle(title=f"From {source.id}", source_id=source.id)]

    with patch.object(registry, "_dispatch_fetch", side_effect=mock_dispatch):
        articles = registry.fetch_all(category="local_inference")

    assert len(articles) == 1
    assert articles[0].source_id == "reddit_localllama"
