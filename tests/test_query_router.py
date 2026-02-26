"""Tests for the NexusQueryRouter."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.query_router import NexusQueryRouter, QueryResult, RouterStats


# ── QueryResult tests ────────────────────────────────────────────────────

class TestQueryResult:
    def test_default_values(self):
        r = QueryResult()
        assert r.answer == ""
        assert r.source == "none"
        assert r.confidence == 0.0
        assert r.cached is False
        assert r.tokens_saved == 0

    def test_to_dict(self):
        r = QueryResult(answer="test", source="cache", confidence=0.9,
                        cached=True, tokens_saved=100, query_time_ms=5.3)
        d = r.to_dict()
        assert d["answer"] == "test"
        assert d["source"] == "cache"
        assert d["confidence"] == 0.9
        assert d["cached"] is True
        assert d["tokens_saved"] == 100
        assert d["query_time_ms"] == 5.3


class TestRouterStats:
    def test_hit_rate_empty(self):
        s = RouterStats()
        assert s.hit_rate() == 0.0

    def test_hit_rate_calculation(self):
        s = RouterStats(total_queries=10, cache_hits=3, search_hits=2)
        assert s.hit_rate() == 0.5

    def test_to_dict(self):
        s = RouterStats(total_queries=5, cache_hits=2, llm_fallbacks=1)
        d = s.to_dict()
        assert d["total_queries"] == 5
        assert d["cache_hits"] == 2
        assert "nexus_hit_rate" in d


# ── Tier 1: Q&A Cache ───────────────────────────────────────────────────

class TestQACache:
    def setup_method(self):
        self.router = NexusQueryRouter()
        self.mock_client = MagicMock()
        self.router._client = self.mock_client
        self.mock_client.is_available.return_value = True

    def test_cache_hit(self):
        self.mock_client.find_qa.return_value = [
            {"question": "What is MCP?", "answer": "MCP is the Model Context Protocol framework."}
        ]
        result = self.router.query("What is MCP?")
        assert result.source == "cache"
        assert result.confidence >= 0.9
        assert result.cached is True
        assert "MCP" in result.answer
        assert self.router.stats.cache_hits == 1

    def test_cache_miss_short_answer(self):
        self.mock_client.find_qa.return_value = [
            {"question": "What?", "answer": "yes"}  # Too short
        ]
        self.mock_client.search.return_value = []
        self.mock_client.ask.return_value = {}
        result = self.router.query("What?", use_llm=False)
        assert result.source != "cache"

    def test_cache_miss_empty(self):
        self.mock_client.find_qa.return_value = []
        self.mock_client.search.return_value = []
        self.mock_client.ask.return_value = {}
        result = self.router.query("Unknown question", use_llm=False)
        assert result.answer == ""
        assert self.router.stats.no_answer == 1


# ── Tier 2: FTS Search ──────────────────────────────────────────────────

class TestFTSSearch:
    def setup_method(self):
        self.router = NexusQueryRouter()
        self.mock_client = MagicMock()
        self.router._client = self.mock_client
        self.mock_client.is_available.return_value = True
        self.mock_client.find_qa.return_value = []  # No cache hit

    def test_search_hit_good_match(self):
        self.mock_client.search.return_value = [
            {"title": "Interceptor Pipeline", "content": "The interceptor pipeline is a chain of pre/post processors that govern agent behavior. " * 3},
        ]
        result = self.router.query("interceptor pipeline")
        assert result.source == "search"
        assert result.confidence > 0.3
        assert result.cached is True
        assert self.router.stats.search_hits == 1

    def test_search_stores_qa(self):
        self.mock_client.search.return_value = [
            {"title": "Test Topic", "content": "Detailed explanation of the test topic with enough content to be useful." * 2},
        ]
        self.router.query("test topic")
        self.mock_client.add_qa.assert_called_once()

    def test_search_no_results(self):
        self.mock_client.search.return_value = []
        self.mock_client.ask.return_value = {}
        result = self.router.query("completely unknown", use_llm=False)
        assert result.answer == ""

    def test_search_too_short_content(self):
        self.mock_client.search.return_value = [
            {"title": "Short", "content": "tiny"}
        ]
        self.mock_client.ask.return_value = {}
        result = self.router.query("short entry", use_llm=False)
        assert result.source != "search"


# ── Tier 3: Nexus Ask ───────────────────────────────────────────────────

class TestNexusAsk:
    def setup_method(self):
        self.router = NexusQueryRouter()
        self.mock_client = MagicMock()
        self.router._client = self.mock_client
        self.mock_client.is_available.return_value = True
        self.mock_client.find_qa.return_value = []
        self.mock_client.search.return_value = []

    def test_nexus_ask_hit(self):
        self.mock_client.ask.return_value = {
            "answer": "The system works by routing queries through multiple tiers.",
            "source": "fts",
            "confidence": 0.7,
            "sources": ["doc1"],
        }
        result = self.router.query("How does the system work?")
        assert "nexus" in result.source
        assert result.confidence == 0.7
        assert result.cached is True

    def test_nexus_ask_no_answer(self):
        self.mock_client.ask.return_value = {}
        result = self.router.query("What is nothing?", use_llm=False)
        assert result.answer == ""


# ── Tier 4: LLM Fallback ────────────────────────────────────────────────

class TestLLMFallback:
    def setup_method(self):
        self.router = NexusQueryRouter()
        self.mock_client = MagicMock()
        self.router._client = self.mock_client
        self.mock_client.is_available.return_value = True
        self.mock_client.find_qa.return_value = []
        self.mock_client.search.return_value = []
        self.mock_client.ask.return_value = {}

    def test_llm_callback_used(self):
        self.router._llm_callback = lambda q: f"LLM says: {q} answer is 42"
        result = self.router.query("What is the answer?", use_llm=True)
        assert result.source == "llm"
        assert "42" in result.answer
        assert result.cached is False
        assert self.router.stats.llm_fallbacks == 1

    def test_llm_answer_stored_in_nexus(self):
        self.router._llm_callback = lambda q: "A detailed LLM answer with enough content to be stored."
        self.router.query("Question for LLM?", use_llm=True)
        self.mock_client.add_qa.assert_called_once()
        assert self.router.stats.answers_stored == 1

    def test_llm_disabled(self):
        result = self.router.query("Unknown question", use_llm=False)
        assert result.source == "none"
        assert result.answer == ""
        assert self.router.stats.llm_fallbacks == 0

    def test_llm_callback_exception(self):
        self.router._llm_callback = lambda q: (_ for _ in ()).throw(Exception("fail"))
        # Should still try LMStudio (which will also fail in test)
        with patch.object(self.router, "_call_lmstudio", return_value=""):
            result = self.router.query("error question", use_llm=True)
            assert self.router.stats.llm_fallbacks == 1


# ── Nexus Offline ────────────────────────────────────────────────────────

class TestNexusOffline:
    def test_nexus_offline_with_llm(self):
        router = NexusQueryRouter(llm_callback=lambda q: "offline answer")
        router._client = MagicMock()
        router._client.is_available.return_value = False
        result = router.query("Test question")
        assert result.source == "llm"
        assert result.answer == "offline answer"

    def test_nexus_offline_no_llm(self):
        router = NexusQueryRouter()
        router._client = MagicMock()
        router._client.is_available.return_value = False
        result = router.query("Test question", use_llm=False)
        assert "offline" in result.answer.lower()


# ── Local Cache ──────────────────────────────────────────────────────────

class TestLocalCache:
    def test_local_cache_hit(self):
        router = NexusQueryRouter()
        mock_client = MagicMock()
        router._client = mock_client
        mock_client.is_available.return_value = True
        mock_client.find_qa.return_value = [
            {"question": "cached?", "answer": "Yes, this is a cached answer from Nexus."}
        ]

        # First call — hits Q&A cache, stores locally
        result1 = router.query("cached?")
        assert result1.source == "cache"

        # Second call — should hit local cache
        result2 = router.query("cached?")
        assert "(local)" in result2.source

    def test_clear_local_cache(self):
        router = NexusQueryRouter()
        key = router._cache_key("test")
        router._local_cache[key] = (QueryResult(answer="test"), 0)
        assert router.clear_local_cache() == 1
        assert len(router._local_cache) == 0


# ── Stats ────────────────────────────────────────────────────────────────

class TestStats:
    def test_reset_stats(self):
        router = NexusQueryRouter()
        router._stats.total_queries = 10
        router._stats.cache_hits = 5
        old = router.reset_stats()
        assert old["total_queries"] == 10
        assert router.stats.total_queries == 0

    def test_token_estimation(self):
        assert NexusQueryRouter._estimate_tokens("a" * 100) == 25

    def test_query_increments_total(self):
        router = NexusQueryRouter()
        router._client = MagicMock()
        router._client.is_available.return_value = False
        router.query("test", use_llm=False)
        assert router.stats.total_queries == 1


# ── Singleton ────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_query_router(self):
        import engine.nexus.query_router as qr
        qr._router_instance = None  # Reset
        r1 = qr.get_query_router()
        r2 = qr.get_query_router()
        assert r1 is r2
        qr._router_instance = None  # Cleanup
