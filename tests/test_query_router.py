"""Tests for the NexusQueryRouter."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.query_router import NexusQueryRouter, QueryResult, RouterStats


# v1.50.2 [2026-03-24] — Mock vector store instead of disabling it entirely.
# Vector search (Tier 2) uses real ChromaDB, bypassing mocked Nexus client.
# We mock get_vector_store and is_vector_store_enabled so Tier 2 returns
# no results by default, but individual tests can override the mock.
@pytest.fixture(autouse=True)
def _mock_vector_store(monkeypatch):
    """Mock vector store with no results by default (override per-test)."""
    mock_store = MagicMock()
    mock_store.search_multi.return_value = []
    monkeypatch.setattr(
        "engine.nexus.vector_store.is_vector_store_enabled", lambda: True
    )
    monkeypatch.setattr(
        "engine.nexus.vector_store.get_vector_store", lambda **kw: mock_store
    )
    return mock_store


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
        s = RouterStats(total_queries=10, cache_hits=3, search_hits=2, nlm_hits=1)
        assert s.hit_rate() == 0.6

    def test_to_dict(self):
        s = RouterStats(total_queries=5, cache_hits=2, nlm_hits=1, llm_fallbacks=1)
        d = s.to_dict()
        assert d["total_queries"] == 5
        assert d["cache_hits"] == 2
        assert d["nlm_hits"] == 1
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


# ── Tier 2: Vector Semantic Search ──────────────────────────────────────
# v1.50.2 [2026-03-24] — Test vector search path (was globally disabled before)

class TestVectorSearch:
    def setup_method(self):
        self.router = NexusQueryRouter()
        self.mock_client = MagicMock()
        self.router._client = self.mock_client
        self.mock_client.is_available.return_value = True
        self.mock_client.find_qa.return_value = []  # No cache hit

    def test_vector_hit_returns_result(self, _mock_vector_store):
        from engine.nexus.vector_store import VectorSearchResult
        _mock_vector_store.search_multi.return_value = [
            VectorSearchResult(
                entry_id="v1",
                text="The interceptor pipeline is a chain of processors that "
                     "govern agent behavior in CosySim. Each interceptor has a "
                     "priority that determines execution order.",
                score=0.88,
                collection="knowledge",
            ),
        ]
        result = self.router.query("How does the interceptor pipeline work?", use_llm=False)
        assert result.source == "vector"
        assert result.confidence > 0.5
        assert "interceptor" in result.answer.lower()
        assert self.router.stats.vector_hits == 1

    def test_vector_miss_falls_through(self, _mock_vector_store):
        _mock_vector_store.search_multi.return_value = []
        self.mock_client.search.return_value = []
        self.mock_client.ask.return_value = {}
        result = self.router.query("Completely unknown topic", use_llm=False)
        assert result.source != "vector"

    def test_vector_low_score_falls_through(self, _mock_vector_store):
        from engine.nexus.vector_store import VectorSearchResult
        _mock_vector_store.search_multi.return_value = [
            VectorSearchResult(entry_id="v2", text="Barely relevant text", score=0.3, collection="knowledge"),
        ]
        self.mock_client.search.return_value = []
        self.mock_client.ask.return_value = {}
        result = self.router.query("Something specific", use_llm=False)
        assert result.source != "vector"

    def test_vector_disabled_skips_tier(self, _mock_vector_store, monkeypatch):
        from engine.nexus.vector_store import VectorSearchResult
        _mock_vector_store.search_multi.return_value = [
            VectorSearchResult(entry_id="v3", text="This should not be returned " * 5, score=0.95, collection="qa"),
        ]
        monkeypatch.setattr("engine.nexus.vector_store.is_vector_store_enabled", lambda: False)
        self.mock_client.search.return_value = []
        self.mock_client.ask.return_value = {}
        result = self.router.query("Vector disabled", use_llm=False)
        assert result.source != "vector"


# ── Tier 3: FTS Search ──────────────────────────────────────────────────

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

    def test_nexus_ask_uses_deep_depth_when_requested(self):
        self.mock_client.ask.return_value = {
            "answer": "NotebookLM-backed answer with enough detail to be valid.",
            "source": "nlm",
            "confidence": 0.8,
            "sources": ["notebook"],
        }
        result = self.router.query("Deep question?", use_llm=False, depth="deep")
        self.mock_client.ask.assert_called_once_with(
            "Deep question?",
            depth="deep",
            category="",
        )
        assert result.source == "nexus-nlm"

    def test_nexus_ask_defaults_invalid_depth_to_auto(self):
        self.mock_client.ask.return_value = {
            "answer": "Auto depth answer with enough detail to be valid.",
            "source": "ask",
            "confidence": 0.6,
            "sources": ["router"],
        }
        self.router.query("Odd depth?", use_llm=False, depth="weird")
        self.mock_client.ask.assert_called_once_with(
            "Odd depth?",
            depth="auto",
            category="",
        )


# ── Tier 4: Direct NotebookLM Fallback ─────────────────────────────────

class TestDirectNLMFallback:
    def setup_method(self):
        self.router = NexusQueryRouter(llm_callback=lambda q: f"LLM says: {q}")
        self.mock_client = MagicMock()
        self.router._client = self.mock_client
        self.mock_client.is_available.return_value = True
        self.mock_client.find_qa.return_value = []
        self.mock_client.search.return_value = []
        self.mock_client.ask.return_value = {}

    def test_direct_nlm_hit_before_llm(self):
        self.mock_client.nlm_status.return_value = {
            "ok": True,
            "data": {"active_backend": "browser"},
        }
        self.mock_client.nlm_unified_ask.return_value = {
            "answer": "NotebookLM browser answer with enough detail to be reused later.",
            "backend": "browser",
            "confidence": 0.82,
            "sources": ["nb-1"],
        }

        result = self.router.query("What did NotebookLM find?")

        assert result.source == "nlm-browser"
        assert result.confidence == 0.82
        assert result.cached is True
        assert self.router.stats.nlm_hits == 1
        assert self.router.stats.llm_fallbacks == 0
        self.mock_client.add_qa.assert_called_once()

    def test_direct_nlm_skips_when_no_backend_available(self):
        self.mock_client.nlm_status.return_value = {
            "ok": True,
            "data": {"active_backend": "none"},
        }

        result = self.router.query("Fallback to LLM?")

        assert result.source == "llm"
        self.mock_client.nlm_unified_ask.assert_not_called()

    def test_direct_nlm_uses_nested_payload(self):
        self.mock_client.nlm_status.return_value = {
            "ok": True,
            "data": {"http": {"available": True}},
        }
        self.mock_client.nlm_unified_ask.return_value = {
            "backend": "http",
            "data": {
                "answer": "Nested NotebookLM payload answer that is long enough to accept.",
                "confidence": 0.77,
                "sources": ["nb-2"],
            },
        }

        result = self.router.query("Use the nested payload?")

        assert result.source == "nlm-http"
        assert result.confidence == 0.77
        assert result.sources == ["nb-2"]


# ── Tier 5: LLM Fallback ────────────────────────────────────────────────

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
