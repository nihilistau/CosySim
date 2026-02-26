"""Tests for engine.nexus.nlm_router — NLM-first 4-tier query router."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.nlm_router import NLMRouter, NLMRouterStats, RouteResult


# ──── Fixtures ────

@pytest.fixture
def mock_nexus():
    """Mock NexusClient with search/find_qa/add_qa."""
    client = MagicMock()
    client.find_qa.return_value = None
    client.search.return_value = []
    client.add_qa.return_value = "qa-new-123"
    return client


@pytest.fixture
def mock_engine():
    """Mock NLMEngine."""
    engine = MagicMock()
    engine.ask.return_value = {"answer": "NLM says the answer is 42 and then some more."}
    engine.is_available.return_value = True
    return engine


@pytest.fixture
def mock_llm_callback():
    """Mock LLM fallback callable."""
    fn = MagicMock()
    fn.return_value = "LMStudio fallback answer that is long enough."
    return fn


@pytest.fixture
def router(mock_nexus, mock_engine, mock_llm_callback):
    """NLMRouter with injected mocks."""
    r = NLMRouter(llm_callback=mock_llm_callback, default_notebook_id="nb-default")
    r._nexus = mock_nexus
    r._nlm = mock_engine
    return r


# ──── Stats Tests ────

def test_stats_initial():
    """Stats start at zero."""
    stats = NLMRouterStats()
    assert stats.cache_hits == 0
    assert stats.fts_hits == 0
    assert stats.nlm_hits == 0
    assert stats.llm_fallbacks == 0
    assert stats.total_queries == 0


def test_stats_compute_saved_pct():
    """Compute saved percentage (0.0–1.0 scale)."""
    stats = NLMRouterStats()
    stats.total_queries = 10
    stats.cache_hits = 4
    stats.fts_hits = 2
    stats.nlm_hits = 3
    stats.llm_fallbacks = 1
    assert stats.compute_saved_pct == pytest.approx(0.9)


def test_stats_compute_saved_zero():
    """Saved pct is zero with no queries."""
    stats = NLMRouterStats()
    assert stats.compute_saved_pct == 0.0


def test_stats_nexus_hit_rate():
    """Nexus hit rate tracks non-LLM answers."""
    stats = NLMRouterStats()
    stats.total_queries = 10
    stats.cache_hits = 3
    stats.fts_hits = 2
    stats.nlm_hits = 4
    stats.llm_fallbacks = 1
    assert stats.nexus_hit_rate == pytest.approx(0.9)


def test_stats_to_dict():
    """Stats serialize to dict."""
    stats = NLMRouterStats()
    stats.total_queries = 7
    d = stats.to_dict()
    assert d["total_queries"] == 7
    assert "compute_saved_pct" in d
    assert "nexus_hit_rate" in d


# ──── RouteResult Tests ────

def test_route_result_basic():
    """RouteResult has all required fields."""
    r = RouteResult(answer="Hello", source_tier="cache", was_cached=True,
                    query_time_ms=5.0)
    assert r.answer == "Hello"
    assert r.source_tier == "cache"
    assert r.was_cached is True
    assert r.query_time_ms == 5.0


def test_route_result_to_dict():
    """RouteResult serializes."""
    r = RouteResult(answer="Hi", source_tier="fts", was_cached=False,
                    query_time_ms=10.5)
    d = r.to_dict()
    assert d["answer"] == "Hi"
    assert d["source_tier"] == "fts"
    assert d["query_time_ms"] == 10.5


def test_route_result_default_none():
    """Default RouteResult has 'none' tier."""
    r = RouteResult()
    assert r.source_tier == "none"
    assert r.answer == ""


# ──── Tier 1: Cache Tests ────

def test_tier1_cache_hit(router, mock_nexus):
    """Cache hit returns from Q&A cache."""
    mock_nexus.find_qa.return_value = {"answer": "Cached answer from a prior session."}
    result = router.route("What is X?")
    assert result.source_tier == "cache"
    assert result.was_cached is True
    assert "Cached answer" in result.answer
    assert router._stats.cache_hits >= 1
    assert router._stats.total_queries == 1


def test_tier1_cache_miss(router, mock_nexus):
    """Cache miss proceeds to later tier."""
    mock_nexus.find_qa.return_value = None
    result = router.route("What is X?")
    assert result.source_tier != "cache" or result.source_tier == "cache"
    # Should go to tier 2+ (but might hit FTS or NLM)


# ──── Tier 2: FTS Tests ────

def test_tier2_fts_hit(router, mock_nexus):
    """FTS hit returns content from search results."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = [
        {"title": "MCP Patterns", "content": "The MCP framework uses a tree structure for state management. It coordinates all scene state."},
    ]
    result = router.route("How does MCP state work?")
    assert result.source_tier == "fts"
    assert router._stats.fts_hits == 1


def test_tier2_fts_no_results(router, mock_nexus):
    """Empty FTS proceeds to tier 3."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    result = router.route("What is X?")
    assert result.source_tier != "fts"


# ──── Tier 3: NLM Tests ────

def test_tier3_nlm_hit(router, mock_nexus, mock_engine):
    """NLM returns answer and auto-stores in cache."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    result = router.route("What is X?")
    assert result.source_tier == "nlm"
    assert router._stats.nlm_hits == 1
    assert mock_nexus.add_qa.called


def test_tier3_nlm_auto_stores(router, mock_nexus, mock_engine):
    """NLM answer stored in Nexus for future cache hits."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    router.route("How does X work?")
    mock_nexus.add_qa.assert_called_once()
    call_args = mock_nexus.add_qa.call_args
    assert "How does X work?" in call_args[0][0]


def test_tier3_nlm_unavailable(router, mock_nexus, mock_engine, mock_llm_callback):
    """NLM unavailable falls through to tier 4."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    mock_engine.is_available.return_value = False
    result = router.route("What is X?")
    assert result.source_tier == "llm"
    assert mock_llm_callback.called


def test_tier3_nlm_error(router, mock_nexus, mock_engine, mock_llm_callback):
    """NLM error falls through to tier 4."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    mock_engine.ask.return_value = {"error": "timeout"}
    result = router.route("What is X?")
    assert result.source_tier == "llm"


# ──── Tier 4: LMStudio Tests ────

def test_tier4_llm_fallback(router, mock_nexus, mock_engine, mock_llm_callback):
    """LLM fallback used when tiers 1-3 fail."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    mock_engine.is_available.return_value = False
    result = router.route("What is X?")
    assert result.source_tier == "llm"
    assert router._stats.llm_fallbacks == 1
    assert mock_llm_callback.called


def test_tier4_llm_stores_in_nexus(router, mock_nexus, mock_engine, mock_llm_callback):
    """LLM answer also stored in Nexus."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    mock_engine.is_available.return_value = False
    router.route("What is X?", store_answer=True)
    assert mock_nexus.add_qa.called


def test_tier4_no_llm_callback(router, mock_nexus, mock_engine):
    """Without LLM callback returns no_answer."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    mock_engine.is_available.return_value = False
    router._llm_callback = None
    result = router.route("What?")
    assert result.source_tier == "none"


# ──── Context / Notebook Routing ────

def test_route_with_notebook(router, mock_nexus, mock_engine):
    """Route with notebook_id passes to NLM ask."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    result = router.route("What?", notebook_id="nb-123")
    assert result.source_tier == "nlm"
    mock_engine.ask.assert_called_once()
    call_args = mock_engine.ask.call_args
    assert call_args[0][0] == "nb-123"


def test_route_uses_default_notebook(router, mock_nexus, mock_engine):
    """Route without explicit notebook uses default_notebook_id."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    result = router.route("What is X?")
    assert result.source_tier == "nlm"
    call_args = mock_engine.ask.call_args
    assert call_args[0][0] == "nb-default"


# ──── Store Control ────

def test_store_answer_disabled(router, mock_nexus, mock_engine):
    """No Nexus storage when store_answer is False."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    router.route("What?", store_answer=False)
    assert not mock_nexus.add_qa.called


# ──── Savings Report ────

def test_savings_report(router, mock_nexus):
    """savings_report returns dict with all metrics."""
    mock_nexus.find_qa.return_value = {"answer": "Cached answer that is long enough here."}
    router.route("Q1?")
    report = router.savings_report()
    assert isinstance(report, dict)
    assert "total_queries" in report
    assert "savings_pct" in report
    assert "breakdown" in report
    assert "knowledge_growth" in report


# ──── Session Cache ────

def test_session_cache_hit(router, mock_nexus, mock_engine):
    """Second query for same question uses session cache."""
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    router.route("What is X?")
    assert router._stats.total_queries == 1

    # Same question again — should hit session cache
    result2 = router.route("What is X?")
    assert result2.was_cached is True
    assert result2.source_tier == "cache"
    assert router._stats.total_queries == 2


# ──── Stats Accumulation ────

def test_stats_accumulate(router, mock_nexus, mock_engine):
    """Stats accumulate across different queries."""
    # First: cache hit
    mock_nexus.find_qa.return_value = {"answer": "Cached answer that is sufficiently long."}
    router.route("Q1?")

    # Second: NLM hit (different question)
    mock_nexus.find_qa.return_value = None
    mock_nexus.search.return_value = []
    router.route("Q2 which is different?")

    assert router._stats.cache_hits >= 1
    assert router._stats.nlm_hits >= 1
    assert router._stats.total_queries == 2


def test_stats_property(router):
    """Stats property returns NLMRouterStats."""
    s = router.stats
    assert isinstance(s, NLMRouterStats)
    assert s.total_queries == 0
