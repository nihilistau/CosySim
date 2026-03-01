"""Tests for the v0.67 news system: sources config, filtering, scoring, storage."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
import yaml

from engine.nexus.news_sources import (
    NewsArticle,
    NewsSource,
    NewsSourceRegistry,
    get_news_registry,
)


# ──── Fixtures ───────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parents[1] / "config" / "news_sources.yaml"


@pytest.fixture()
def config() -> Dict[str, Any]:
    """Load the real news_sources.yaml config — returns the 'news' sub-key."""
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    # YAML is nested under top-level 'news:' key
    return raw.get("news", raw)


@pytest.fixture()
def registry() -> NewsSourceRegistry:
    """Return a fresh registry loaded from the real config."""
    reg = NewsSourceRegistry()
    reg.load_sources()
    return reg


def _make_article(
    title: str = "Test Article",
    summary: str = "",
    category: str = "ai_ml",
    source_id: str = "test_source",
) -> NewsArticle:
    return NewsArticle(
        source_id=source_id,
        title=title,
        url=f"https://example.com/{title.replace(' ', '-').lower()}",
        summary=summary,
        category=category,
    )


# ──── Config Structure Tests ─────────────────────────────────────────────────

def test_config_loads(config: Dict[str, Any]) -> None:
    """Config file must load as a non-empty dict."""
    assert isinstance(config, dict)
    assert "sources" in config


def test_at_least_25_sources(config: Dict[str, Any]) -> None:
    """Config must define at least 25 sources."""
    assert len(config["sources"]) >= 25


def test_sources_have_required_fields(config: Dict[str, Any]) -> None:
    """Every source entry must have id, name, type, url, and category."""
    required = {"id", "name", "type", "url", "category"}
    for src in config["sources"]:
        missing = required - src.keys()
        assert not missing, f"Source {src.get('id', '?')} missing: {missing}"


def test_seven_categories_present(config: Dict[str, Any]) -> None:
    """Config must cover all 7 target categories."""
    expected = {"ai_ml", "local_inference", "open_source", "python", "security", "science", "dev_tools"}
    actual = {s["category"] for s in config["sources"]}
    missing = expected - actual
    assert not missing, f"Missing categories: {missing}"


def test_category_filters_defined(config: Dict[str, Any]) -> None:
    """category_filters section must exist with per-category include lists."""
    assert "category_filters" in config
    filters = config["category_filters"]
    assert isinstance(filters, dict)
    # At least ai_ml and python should have entries
    assert "ai_ml" in filters
    assert "python" in filters


def test_global_excludes_defined(config: Dict[str, Any]) -> None:
    """keyword_filters.exclude list must be present."""
    kf = config.get("keyword_filters", {})
    assert "exclude" in kf
    assert isinstance(kf["exclude"], list)
    assert len(kf["exclude"]) > 0


# ──── Registry Load Tests ────────────────────────────────────────────────────

def test_registry_loads_all_sources(registry: NewsSourceRegistry) -> None:
    """Registry must load at least 25 sources from config."""
    stats = registry.stats()
    assert stats["total_sources"] >= 25


def test_registry_sources_have_last_fetch_status(registry: NewsSourceRegistry) -> None:
    """Every source in stats must include last_fetch_status field."""
    stats = registry.stats()
    for sid, sdata in stats["sources"].items():
        assert "last_fetch_status" in sdata, f"Source {sid} missing last_fetch_status"


def test_registry_sources_have_category(registry: NewsSourceRegistry) -> None:
    """Every source in stats must include category field."""
    stats = registry.stats()
    for sid, sdata in stats["sources"].items():
        assert "category" in sdata, f"Source {sid} missing category"


def test_registry_sources_have_quality_score(registry: NewsSourceRegistry) -> None:
    """Every source in stats must include quality_score field."""
    stats = registry.stats()
    for sid, sdata in stats["sources"].items():
        assert "quality_score" in sdata, f"Source {sid} missing quality_score"


# ──── Filter Tests ───────────────────────────────────────────────────────────

def test_filter_ai_ml_article_passes(registry: NewsSourceRegistry) -> None:
    """AI/ML articles that match ai_ml category include keywords must pass."""
    art = _make_article(
        title="New Large Language Model Achieves SOTA on Benchmarks",
        category="ai_ml",
    )
    filtered = registry.filter_articles([art])
    assert art in filtered


def test_filter_ai_ml_article_excluded_by_global_exclude(registry: NewsSourceRegistry) -> None:
    """Articles matching global exclude keywords must be filtered out."""
    excludes = registry.get_config().get("keyword_filters", {}).get("exclude", [])
    if not excludes:
        pytest.skip("No global exclude keywords configured")
    art = _make_article(
        title=excludes[0].upper() + " some content",
        category="ai_ml",
    )
    # Patch the exclude check directly
    with patch.object(registry, "_config", {
        **registry.get_config(),
        "keyword_filters": {"exclude": [excludes[0]]},
    }):
        filtered = registry.filter_articles([art])
    assert art not in filtered


def test_filter_python_article_passes_without_ai_keywords(registry: NewsSourceRegistry) -> None:
    """Python articles must pass through without needing AI/ML keywords."""
    art = _make_article(
        title="How to use dataclasses in Python 3.12",
        category="python",
    )
    filtered = registry.filter_articles([art])
    assert art in filtered


def test_filter_security_article_passes_without_ai_keywords(registry: NewsSourceRegistry) -> None:
    """Security articles must pass through without AI keywords."""
    art = _make_article(
        title="Critical CVE in OpenSSL 3.1 patched",
        category="security",
    )
    filtered = registry.filter_articles([art])
    assert art in filtered


def test_filter_science_article_passes(registry: NewsSourceRegistry) -> None:
    """Science articles matching science keywords must pass through."""
    art = _make_article(
        title="New research paper benchmarks neural compute algorithms",
        category="science",
    )
    filtered = registry.filter_articles([art])
    assert art in filtered


def test_filter_keyword_override(registry: NewsSourceRegistry) -> None:
    """Explicit keywords override must override category config."""
    art = _make_article(title="Python web scraping tutorial", category="ai_ml")
    # Override with 'python' keyword — article doesn't mention AI
    filtered = registry.filter_articles([art], keywords=["python"])
    assert art in filtered

    # Override with 'cuda' — article doesn't mention it → filtered out
    filtered_out = registry.filter_articles([art], keywords=["cuda_exclusive_keyword_xyz"])
    assert art not in filtered_out


# ──── Scoring Tests ──────────────────────────────────────────────────────────

def test_score_relevance_returns_float(registry: NewsSourceRegistry) -> None:
    """score_relevance must return a float between 0 and 1."""
    art = _make_article(title="Test article about LLM", category="ai_ml")
    score = registry.score_relevance(art)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_score_relevance_higher_for_matching_article(registry: NewsSourceRegistry) -> None:
    """Articles matching category keywords should score higher than random ones."""
    cat_filters = registry.get_config().get("category_filters", {})
    ai_kws = cat_filters.get("ai_ml", {}).get("include", [])
    if not ai_kws:
        pytest.skip("No ai_ml keywords configured")

    high_art = _make_article(
        title=f"Advanced {ai_kws[0]} techniques and benchmarks",
        category="ai_ml",
    )
    low_art = _make_article(title="Random unrelated content xyz123", category="ai_ml")

    high_score = registry.score_relevance(high_art)
    low_score = registry.score_relevance(low_art)
    assert high_score >= low_score


# ──── Storage Tests ──────────────────────────────────────────────────────────

def test_store_to_nexus_uses_news_content_type(registry: NewsSourceRegistry) -> None:
    """store_to_nexus must use content_type='news', not 'note'."""
    articles = [
        NewsArticle(
            source_id="test",
            title="Test News Article",
            url="https://example.com/test",
            summary="A test article summary.",
            category="ai_ml",
            score=0.8,
        )
    ]
    mock_client = MagicMock()
    mock_client.search.return_value = []
    mock_client.add_entry.return_value = {"id": "test-id"}

    with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
        count = registry.store_to_nexus(articles)

    assert count == 1
    call_kwargs = mock_client.add_entry.call_args
    assert call_kwargs.kwargs.get("content_type") == "news" or (
        call_kwargs.args and "news" in str(call_kwargs)
    ), "store_to_nexus must use content_type='news'"


def test_store_to_nexus_skips_empty_title(registry: NewsSourceRegistry) -> None:
    """Articles with empty title must not be stored."""
    art = NewsArticle(source_id="test", title="", url="https://example.com/x")
    mock_client = MagicMock()
    mock_client.search.return_value = []

    with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
        count = registry.store_to_nexus([art])

    assert count == 0
    mock_client.add_entry.assert_not_called()


def test_store_to_nexus_respects_max_store(registry: NewsSourceRegistry) -> None:
    """store_to_nexus must honour the max_store limit."""
    articles = [
        NewsArticle(source_id="s", title=f"Article {i}", url=f"https://x.com/{i}", category="ai_ml")
        for i in range(20)
    ]
    mock_client = MagicMock()
    mock_client.search.return_value = []
    mock_client.add_entry.return_value = {"id": "x"}

    with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
        count = registry.store_to_nexus(articles, max_store=5)

    assert count == 5


def test_store_to_nexus_graceful_on_nexus_unavailable(registry: NewsSourceRegistry) -> None:
    """store_to_nexus must return 0 and not raise if Nexus is unavailable."""
    articles = [_make_article()]
    with patch("engine.nexus.client.get_nexus_client", side_effect=RuntimeError("offline")):
        count = registry.store_to_nexus(articles)
    assert count == 0


# ──── get_news_registry Singleton ────────────────────────────────────────────

def test_get_news_registry_returns_instance() -> None:
    """get_news_registry() must return a NewsSourceRegistry instance."""
    reg = get_news_registry()
    assert isinstance(reg, NewsSourceRegistry)
