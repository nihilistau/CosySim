"""NLM-First Query Router — Extends NexusQueryRouter with NLM tier.

Inserts NotebookLM (free Gemini compute) as Tier 3 in the query pipeline,
between FTS search and local LLM fallback. Every NLM answer is auto-stored
in Nexus Q&A cache, promoting it to Tier 1 for future queries.

Pipeline:
    Tier 1: Q&A Cache     (instant, free, 0 compute)
    Tier 2: FTS5 Search   (fast, free, synthesize from entries)
    Tier 3: NLM Ask       (free Gemini — NEW)
    Tier 4: LMStudio LLM  (local GPU, absolute last resort)

Every answer from Tier 3 auto-promotes to Tier 1 (stored in Q&A cache).
Over time, cache hit rate increases, NLM and LLM calls decrease.

Usage:
    from engine.nexus.nlm_router import get_nlm_router
    router = get_nlm_router()
    result = router.query("How does the interceptor pipeline work?")
    print(result.source)  # "cache", "search", "nlm", or "llm"
    print(router.savings_report())
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class NLMRouterStats:
    """Extended stats tracking NLM tier separately."""

    total_queries: int = 0
    cache_hits: int = 0
    fts_hits: int = 0
    nlm_hits: int = 0
    llm_fallbacks: int = 0
    no_answer: int = 0
    answers_stored: int = 0
    estimated_tokens_saved: int = 0
    _start_time: float = field(default_factory=time.monotonic)

    @property
    def nexus_hit_rate(self) -> float:
        """Percentage of queries answered without any LLM call."""
        if self.total_queries == 0:
            return 0.0
        return (self.cache_hits + self.fts_hits + self.nlm_hits) / self.total_queries

    @property
    def compute_saved_pct(self) -> float:
        """Percentage of queries that avoided local GPU."""
        if self.total_queries == 0:
            return 0.0
        return 1.0 - (self.llm_fallbacks / self.total_queries)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        uptime = time.monotonic() - self._start_time
        return {
            "total_queries": self.total_queries,
            "cache_hits": self.cache_hits,
            "fts_hits": self.fts_hits,
            "nlm_hits": self.nlm_hits,
            "llm_fallbacks": self.llm_fallbacks,
            "no_answer": self.no_answer,
            "answers_stored": self.answers_stored,
            "nexus_hit_rate": f"{self.nexus_hit_rate:.1%}",
            "compute_saved_pct": f"{self.compute_saved_pct:.1%}",
            "estimated_tokens_saved": self.estimated_tokens_saved,
            "uptime_seconds": round(uptime, 1),
        }


@dataclass
class RouteResult:
    """Result from the NLM-first router."""

    answer: str = ""
    source_tier: str = "none"  # cache, fts, nlm, llm, none
    confidence: float = 0.0
    was_cached: bool = False
    query_time_ms: float = 0.0
    stored_in_nexus: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "answer": self.answer,
            "source_tier": self.source_tier,
            "confidence": self.confidence,
            "was_cached": self.was_cached,
            "query_time_ms": round(self.query_time_ms, 1),
            "stored_in_nexus": self.stored_in_nexus,
        }


class NLMRouter:
    """4-tier query router with NLM before local LLM.

    The router checks each tier in order and returns the first
    confident answer. NLM answers are auto-stored in Nexus Q&A cache
    so the same question is instant next time.
    """

    MIN_ANSWER_LENGTH = 20
    CACHE_CONFIDENCE = 0.90
    FTS_CONFIDENCE = 0.60
    NLM_CONFIDENCE = 0.80

    def __init__(
        self,
        llm_callback: Optional[Callable[[str], str]] = None,
        default_notebook_id: str = "",
    ) -> None:
        self._llm_callback = llm_callback
        self._default_nb = default_notebook_id
        self._stats = NLMRouterStats()
        self._lock = threading.Lock()
        self._nexus = None
        self._nlm = None
        # Local session cache
        self._cache: Dict[str, tuple[RouteResult, float]] = {}
        self._cache_ttl = 300.0

    def _get_nexus(self) -> Any:
        """Lazy-load NexusClient."""
        if self._nexus is None:
            try:
                from engine.nexus.client import get_nexus_client
                self._nexus = get_nexus_client()
            except Exception as e:
                logger.warning("NexusClient unavailable: %s", e)
        return self._nexus

    def _get_nlm(self) -> Any:
        """Lazy-load NLMEngine."""
        if self._nlm is None:
            try:
                from engine.nexus.nlm_engine import get_nlm_engine
                self._nlm = get_nlm_engine()
            except Exception as e:
                logger.warning("NLMEngine unavailable: %s", e)
        return self._nlm

    @property
    def stats(self) -> NLMRouterStats:
        """Return current stats."""
        return self._stats

    # ──── Main Route Method ────

    def route(
        self,
        question: str,
        context: str = "",
        notebook_id: str = "",
        min_confidence: float = 0.3,
        use_nlm: bool = True,
        use_llm: bool = True,
        store_answer: bool = True,
        category: str = "",
    ) -> RouteResult:
        """Route a question through the 4-tier pipeline.

        Args:
            question: The question to answer.
            context: Optional context for better search.
            notebook_id: NLM notebook to ask (or default).
            min_confidence: Minimum confidence to accept an answer.
            use_nlm: Whether to use NLM tier (disable for offline).
            use_llm: Whether to use LLM fallback.
            store_answer: Auto-store answers in Nexus Q&A.
            category: Category for Nexus storage.

        Returns:
            RouteResult with answer and source tier.
        """
        start = time.monotonic()
        with self._lock:
            self._stats.total_queries += 1

        # Check local session cache
        cache_key = question.strip().lower()
        cached = self._check_cache(cache_key)
        if cached:
            cached.query_time_ms = (time.monotonic() - start) * 1000
            return cached

        nexus = self._get_nexus()

        # Tier 1: Q&A Cache
        if nexus:
            result = self._tier_qa_cache(nexus, question)
            if result and result.confidence >= min_confidence:
                result.query_time_ms = (time.monotonic() - start) * 1000
                self._store_cache(cache_key, result)
                return result

        # Tier 2: FTS5 Search
        if nexus:
            result = self._tier_fts(nexus, question)
            if result and result.confidence >= min_confidence:
                if store_answer:
                    self._store_qa(nexus, question, result.answer, category)
                result.query_time_ms = (time.monotonic() - start) * 1000
                self._store_cache(cache_key, result)
                return result

        # Tier 3: NLM Ask (free Gemini)
        if use_nlm:
            nb_id = notebook_id or self._default_nb
            if nb_id:
                result = self._tier_nlm(question, nb_id)
                if result and result.confidence >= min_confidence:
                    if store_answer and nexus:
                        self._store_qa(nexus, question, result.answer, category)
                        result.stored_in_nexus = True
                    result.query_time_ms = (time.monotonic() - start) * 1000
                    self._store_cache(cache_key, result)
                    return result

        # Tier 4: LLM Fallback
        if use_llm and self._llm_callback:
            result = self._tier_llm(question)
            if result and result.answer:
                if store_answer and nexus:
                    self._store_qa(nexus, question, result.answer, category)
                    result.stored_in_nexus = True
                result.query_time_ms = (time.monotonic() - start) * 1000
                self._store_cache(cache_key, result)
                return result

        # No answer
        with self._lock:
            self._stats.no_answer += 1
        return RouteResult(
            source_tier="none",
            query_time_ms=(time.monotonic() - start) * 1000,
        )

    # ──── Tier Implementations ────

    def _tier_qa_cache(self, nexus: Any, question: str) -> Optional[RouteResult]:
        """Tier 1: Check Nexus Q&A cache."""
        try:
            result = nexus.find_qa(question)
            if result and result.get("answer"):
                answer = result["answer"]
                if len(answer) >= self.MIN_ANSWER_LENGTH:
                    with self._lock:
                        self._stats.cache_hits += 1
                        self._stats.estimated_tokens_saved += len(answer.split()) * 2
                    return RouteResult(
                        answer=answer,
                        source_tier="cache",
                        confidence=self.CACHE_CONFIDENCE,
                        was_cached=True,
                    )
        except Exception as e:
            logger.debug("Q&A cache lookup failed: %s", e)
        return None

    def _tier_fts(self, nexus: Any, question: str) -> Optional[RouteResult]:
        """Tier 2: FTS5 full-text search."""
        try:
            results = nexus.search(question, limit=5)
            if results:
                # Use the best match
                best = results[0]
                content = best.get("content", "")
                if content and len(content) >= self.MIN_ANSWER_LENGTH:
                    with self._lock:
                        self._stats.fts_hits += 1
                        self._stats.estimated_tokens_saved += len(content.split()) * 2
                    return RouteResult(
                        answer=content,
                        source_tier="fts",
                        confidence=self.FTS_CONFIDENCE,
                        was_cached=True,
                        metadata={"entry_id": best.get("id", "")},
                    )
        except Exception as e:
            logger.debug("FTS search failed: %s", e)
        return None

    def _tier_nlm(self, question: str, notebook_id: str) -> Optional[RouteResult]:
        """Tier 3: NLM Ask (free Gemini compute)."""
        nlm = self._get_nlm()
        if not nlm or not nlm.is_available():
            return None
        try:
            result = nlm.ask(notebook_id, question)
            answer = result.get("answer", result.get("response", ""))
            if answer and isinstance(answer, str) and len(answer) >= self.MIN_ANSWER_LENGTH:
                with self._lock:
                    self._stats.nlm_hits += 1
                    self._stats.estimated_tokens_saved += len(answer.split()) * 2
                logger.info("NLM answered: %s (len=%d)", question[:60], len(answer))
                return RouteResult(
                    answer=answer,
                    source_tier="nlm",
                    confidence=self.NLM_CONFIDENCE,
                    was_cached=False,
                )
        except Exception as e:
            logger.debug("NLM ask failed: %s", e)
        return None

    def _tier_llm(self, question: str) -> Optional[RouteResult]:
        """Tier 4: Local LLM fallback."""
        try:
            answer = self._llm_callback(question)
            if answer and len(answer) >= self.MIN_ANSWER_LENGTH:
                with self._lock:
                    self._stats.llm_fallbacks += 1
                return RouteResult(
                    answer=answer,
                    source_tier="llm",
                    confidence=0.70,
                    was_cached=False,
                )
        except Exception as e:
            logger.debug("LLM fallback failed: %s", e)
        return None

    # ──── Storage ────

    def _store_qa(self, nexus: Any, question: str, answer: str, category: str) -> None:
        """Store Q&A pair in Nexus for future cache hits."""
        try:
            nexus.add_qa(question, answer, category=category or "nlm_routed")
            with self._lock:
                self._stats.answers_stored += 1
        except Exception as e:
            logger.debug("Failed to store Q&A: %s", e)

    # ──── Local Session Cache ────

    def _check_cache(self, key: str) -> Optional[RouteResult]:
        """Check local session cache."""
        entry = self._cache.get(key)
        if entry:
            result, ts = entry
            if time.monotonic() - ts < self._cache_ttl:
                with self._lock:
                    self._stats.cache_hits += 1
                return RouteResult(
                    answer=result.answer,
                    source_tier="cache",
                    confidence=result.confidence,
                    was_cached=True,
                )
            else:
                del self._cache[key]
        return None

    def _store_cache(self, key: str, result: RouteResult) -> None:
        """Store in local session cache."""
        self._cache[key] = (result, time.monotonic())

    # ──── Reports ────

    def savings_report(self) -> Dict[str, Any]:
        """Generate a savings report showing compute avoided.

        Returns:
            Dict with savings metrics.
        """
        s = self._stats
        return {
            "total_queries": s.total_queries,
            "answered_without_gpu": s.cache_hits + s.fts_hits + s.nlm_hits,
            "gpu_calls": s.llm_fallbacks,
            "savings_pct": f"{s.compute_saved_pct:.1%}",
            "breakdown": {
                "cache_hits": s.cache_hits,
                "fts_hits": s.fts_hits,
                "nlm_hits (free Gemini)": s.nlm_hits,
                "llm_fallbacks (GPU)": s.llm_fallbacks,
                "no_answer": s.no_answer,
            },
            "knowledge_growth": s.answers_stored,
            "estimated_tokens_saved": s.estimated_tokens_saved,
        }


# ──── Singleton ────

_router: Optional[NLMRouter] = None
_router_lock = threading.Lock()


def get_nlm_router(
    llm_callback: Optional[Callable[[str], str]] = None,
    default_notebook_id: str = "",
) -> NLMRouter:
    """Return the global NLMRouter singleton."""
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = NLMRouter(
                    llm_callback=llm_callback,
                    default_notebook_id=default_notebook_id,
                )
    return _router
