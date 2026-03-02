"""Tests for news skills."""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_pipeline():
    mock = MagicMock()
    mock.get_latest_digest.return_value = "## AI News\n\n**Test headline**\nSummary text."
    mock.fetch_category.return_value = []
    mock.store_items_to_nexus.return_value = 0
    mock.run_fetch_cycle.return_value = {"total_items": 10, "total_stored": 8, "categories": {}}
    with patch("engine.skills.builtin.news_skills.get_news_pipeline", return_value=mock):
        yield mock


def test_fetch_news_skill():
    from engine.skills.builtin.news_skills import fetch_news
    result = fetch_news("ai_research", 5)
    assert isinstance(result, str)
    assert len(result) > 0


def test_fetch_news_default_category():
    from engine.skills.builtin.news_skills import fetch_news
    result = fetch_news()
    assert isinstance(result, str)


def test_search_news_skill():
    from engine.skills.builtin.news_skills import search_news
    mock_client = MagicMock()
    mock_client.search.return_value = [
        {"title": "LLM research", "content": "Large language models..."}
    ]
    with patch("engine.skills.builtin.news_skills.get_nexus_client", return_value=mock_client):
        result = search_news("LLM research", "ai_research")
    assert isinstance(result, str)


def test_search_news_no_results():
    from engine.skills.builtin.news_skills import search_news
    mock_client = MagicMock()
    mock_client.search.return_value = []
    with patch("engine.skills.builtin.news_skills.get_nexus_client", return_value=mock_client):
        result = search_news("nonexistent topic")
    assert "No news found" in result


def test_run_news_fetch_skill():
    from engine.skills.builtin.news_skills import run_news_fetch
    result = run_news_fetch()
    assert "complete" in result or "Fetch" in result


def test_run_news_fetch_single_category():
    from engine.skills.builtin.news_skills import run_news_fetch
    result = run_news_fetch("tech")
    assert isinstance(result, str)
