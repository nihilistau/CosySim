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


# ──────────────────────────────────────────────────────────────────────────────
# news_insight
# ──────────────────────────────────────────────────────────────────────────────

def test_news_insight_cache_hit():
    """Returns cached Q&A answer when Nexus has a match."""
    from engine.skills.builtin.news_skills import news_insight
    mock_client = MagicMock()
    mock_client.ask.return_value = {"answer": "AI regulation is advancing rapidly with new frameworks.", "source": "qa_cache"}
    mock_client.search.return_value = []
    with patch("engine.skills.builtin.news_skills.get_nexus_client", return_value=mock_client):
        result = news_insight("AI regulation")
    assert "NEWS INSIGHT" in result
    assert "AI REGULATION" in result.upper()
    assert "advancing" in result


def test_news_insight_search_fallback():
    """Falls back to FTS search when Q&A cache is empty."""
    from engine.skills.builtin.news_skills import news_insight
    mock_client = MagicMock()
    mock_client.ask.return_value = {"answer": "", "source": "none"}
    mock_client.search.return_value = [
        {"content": "Tech market sees new entrants in the AI space this quarter."}
    ]
    with patch("engine.skills.builtin.news_skills.get_nexus_client", return_value=mock_client):
        result = news_insight("tech market")
    assert "NEWS INSIGHT" in result
    assert "Tech market" in result


def test_news_insight_nothing_found():
    """Returns helpful message when nothing is in Nexus."""
    from engine.skills.builtin.news_skills import news_insight
    mock_client = MagicMock()
    mock_client.ask.return_value = {"answer": "", "source": "none"}
    mock_client.search.return_value = []
    with patch("engine.skills.builtin.news_skills.get_nexus_client", return_value=mock_client):
        result = news_insight("very obscure topic")
    assert "No recent intelligence" in result or "unavailable" in result.lower()


def test_news_insight_exception_handled():
    """Handles exceptions gracefully."""
    from engine.skills.builtin.news_skills import news_insight
    mock_client = MagicMock()
    mock_client.ask.side_effect = RuntimeError("Nexus down")
    with patch("engine.skills.builtin.news_skills.get_nexus_client", return_value=mock_client):
        result = news_insight("anything")
    assert "NEWS INSIGHT" in result
    assert isinstance(result, str)


def test_news_insight_truncates_to_200_words():
    """Result is at most ~200 words when cache has long content."""
    from engine.skills.builtin.news_skills import news_insight
    long_answer = " ".join(["word"] * 500)
    mock_client = MagicMock()
    mock_client.ask.return_value = {"answer": long_answer, "source": "qa_cache"}
    mock_client.search.return_value = []
    with patch("engine.skills.builtin.news_skills.get_nexus_client", return_value=mock_client):
        result = news_insight("any topic")
    # Should be truncated to roughly 200 words plus header
    word_count = len(result.split())
    assert word_count <= 215, f"Too many words: {word_count}"
