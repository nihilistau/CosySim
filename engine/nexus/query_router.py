"""Nexus Query Router — Smart query routing through Nexus-first pipeline.

Routes all queries through a confidence-scored pipeline:
  1. Q&A Cache (instant, high confidence)
  2. Vector Semantic Search (Gemini Embedding 2 + ChromaDB, high confidence)
  3. FTS Knowledge Search (fast, medium confidence)
  4. Nexus Smart Ask / NotebookLM-backed research
  5. Direct NotebookLM unified ask (when smart ask cannot answer)
  6. LLM Fallback (slow, variable confidence)

NLM and LLM answers are automatically stored back in Nexus for future reuse,
creating a self-improving knowledge loop that reduces expensive fallback calls
over time.

Usage:
    from engine.nexus.query_router import get_query_router
    router = get_query_router()

    result = router.query("How does the interceptor pipeline work?")
    # Returns: {answer, source, confidence, cached, tokens_saved}

    result = router.query("What is X?", min_confidence=0.7, use_llm=True)
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from engine.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Result from the query router pipeline."""
    answer: str = ""
    source: str = "none"          # cache | search | nexus-* | nlm* | llm | none
    confidence: float = 0.0       # 0.0 to 1.0
    cached: bool = False          # Was this served from Nexus?
    tokens_saved: int = 0         # Estimated tokens saved vs LLM call
    query_time_ms: float = 0.0
    sources: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "source": self.source,
            "confidence": self.confidence,
            "cached": self.cached,
            "tokens_saved": self.tokens_saved,
            "query_time_ms": round(self.query_time_ms, 1),
            "sources": self.sources,
        }


@dataclass
class RouterStats:
    """Cumulative router statistics."""
    total_queries: int = 0
    cache_hits: int = 0
    vector_hits: int = 0
    search_hits: int = 0
    nlm_hits: int = 0
    llm_fallbacks: int = 0
    no_answer: int = 0
    total_tokens_saved: int = 0
    answers_stored: int = 0

    def hit_rate(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return (self.cache_hits + self.vector_hits + self.search_hits + self.nlm_hits) / self.total_queries

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_queries": self.total_queries,
            "cache_hits": self.cache_hits,
            "vector_hits": self.vector_hits,
            "search_hits": self.search_hits,
            "nlm_hits": self.nlm_hits,
            "llm_fallbacks": self.llm_fallbacks,
            "no_answer": self.no_answer,
            "total_tokens_saved": self.total_tokens_saved,
            "answers_stored": self.answers_stored,
            "nexus_hit_rate": f"{self.hit_rate():.1%}",
        }


class NexusQueryRouter:
    """Routes queries through Nexus-first pipeline with LLM fallback.

    The router implements a 6-tier lookup:
      1. Q&A Cache — exact or fuzzy match on previously answered questions
      2. Vector Search — semantic similarity via Gemini Embedding 2 + ChromaDB
      3. FTS Search — synthesise answer from matching knowledge entries
      4. Nexus Smart Ask — server-side cache → FTS → NotebookLM pipeline
      5. Direct NotebookLM ask — use the unified backend before local GPU
      6. LLM Fallback — send to LMStudio, store answer back in Nexus

    Over time, as more answers accumulate in Nexus, fewer LLM calls are needed.
    """

    # Confidence thresholds
    CACHE_CONFIDENCE = 0.90    # Q&A cache hit — very high confidence
    VECTOR_CONFIDENCE = 0.82   # Strong vector search match
    SEARCH_HIGH = 0.75         # Strong search match
    SEARCH_MEDIUM = 0.50       # Decent search match
    SEARCH_LOW = 0.30          # Weak match
    MIN_ANSWER_LENGTH = 20     # Minimum chars for a valid answer

    def __init__(self, llm_callback: Optional[Callable] = None) -> None:
        self._client = None
        self._llm_callback = llm_callback
        self._stats = RouterStats()
        self._lock = threading.Lock()
        # Local answer cache to avoid repeated Nexus API calls within session
        self._local_cache: Dict[str, Tuple[QueryResult, float]] = {}
        self._local_cache_ttl = 300  # 5 minutes

    def _get_client(self):
        """Lazy-load NexusClient."""
        if self._client is None:
            try:
                from engine.nexus.client import get_nexus_client
                self._client = get_nexus_client()
            except Exception as exc:
                logger.warning("Failed to get NexusClient: %s", exc)
        return self._client

    @property
    def stats(self) -> RouterStats:
        return self._stats

    # ── Main Query Method ───────────────────────────────────────────

    def query(self, question: str, min_confidence: float = 0.3,
              use_llm: bool = True, category: str = "",
              tags: Optional[List[str]] = None,
              source_hint: str = "system",
              depth: str = "auto") -> QueryResult:
        """Route a query through the Nexus-first pipeline.

        Args:
            question: The question to answer.
            min_confidence: Minimum confidence to accept a Nexus answer.
            use_llm: Whether to fall back to LLM if Nexus can't answer.
            category: Category filter for Nexus search.
            tags: Tags to apply when storing new answers.
            source_hint: Who's asking (system, agent, copilot, scene).
            depth: "shallow", "auto", or "deep" for the Nexus smart-ask tier.

        Returns:
            QueryResult with answer, source, confidence, and metadata.
        """
        start = time.time()
        with self._lock:
            self._stats.total_queries += 1

        # Check local session cache
        cache_key = self._cache_key(question)
        cached = self._check_local_cache(cache_key)
        if cached:
            cached.query_time_ms = (time.time() - start) * 1000
            return cached

        client = self._get_client()
        if not client or not client.is_available():
            # Nexus offline — go straight to LLM if available
            if use_llm:
                result = self._llm_fallback(question, category, tags, source_hint)
                result.query_time_ms = (time.time() - start) * 1000
                return result
            return QueryResult(
                answer="Nexus is offline and LLM fallback is disabled.",
                source="none",
                query_time_ms=(time.time() - start) * 1000,
            )

        # Tier 1: Q&A Cache
        result = self._try_qa_cache(client, question)
        if result and result.confidence >= min_confidence:
            result.query_time_ms = (time.time() - start) * 1000
            self._store_local_cache(cache_key, result)
            return result

        # Tier 2: Vector Semantic Search (Gemini Embedding 2 + ChromaDB)
        result = self._try_vector_search(question)
        if result and result.confidence >= min_confidence:
            result.query_time_ms = (time.time() - start) * 1000
            self._store_local_cache(cache_key, result)
            return result

        # Tier 3: FTS Knowledge Search
        result = self._try_fts_search(client, question, category)
        if result and result.confidence >= min_confidence:
            # Store as Q&A for faster future lookups
            self._store_qa(client, question, result.answer, category, tags, source_hint)
            result.query_time_ms = (time.time() - start) * 1000
            self._store_local_cache(cache_key, result)
            return result

        # Tier 4: Nexus Smart Ask (server-side pipeline)
        result = self._try_nexus_ask(client, question, category, depth=depth)
        if result and result.confidence >= min_confidence:
            result.query_time_ms = (time.time() - start) * 1000
            self._store_local_cache(cache_key, result)
            return result

        # Tier 5: Direct NotebookLM ask
        result = self._try_direct_nlm(client, question)
        if result and result.confidence >= min_confidence:
            self._store_qa(client, question, result.answer, category, tags, source_hint)
            with self._lock:
                self._stats.answers_stored += 1
            result.query_time_ms = (time.time() - start) * 1000
            self._store_local_cache(cache_key, result)
            return result

        # Tier 6: LLM Fallback
        if use_llm:
            result = self._llm_fallback(question, category, tags, source_hint)
            if result.answer and len(result.answer) >= self.MIN_ANSWER_LENGTH:
                # Store LLM answer back in Nexus for future reuse
                self._store_qa(client, question, result.answer, category, tags, source_hint)
                with self._lock:
                    self._stats.answers_stored += 1
            result.query_time_ms = (time.time() - start) * 1000
            self._store_local_cache(cache_key, result)
            return result

        # No answer found
        with self._lock:
            self._stats.no_answer += 1
        return QueryResult(
            answer="",
            source="none",
            query_time_ms=(time.time() - start) * 1000,
        )

    # ── Pipeline Tiers ──────────────────────────────────────────────

    def _try_qa_cache(self, client, question: str) -> Optional[QueryResult]:
        """Tier 1: Check the Q&A cache for a matching answer."""
        try:
            qa_results = client.find_qa(question, limit=3)
            if qa_results:
                best = qa_results[0]
                answer = best.get("answer", "")
                if answer and len(answer) >= self.MIN_ANSWER_LENGTH:
                    with self._lock:
                        self._stats.cache_hits += 1
                        tokens_saved = self._estimate_tokens(answer)
                        self._stats.total_tokens_saved += tokens_saved
                    return QueryResult(
                        answer=answer,
                        source="cache",
                        confidence=self.CACHE_CONFIDENCE,
                        cached=True,
                        tokens_saved=tokens_saved,
                        sources=[best.get("question", "")],
                    )
        except Exception as exc:
            logger.debug("Q&A cache lookup failed: %s", exc)
        return None

    def _try_vector_search(self, question: str) -> Optional[QueryResult]:
        """Tier 2: Semantic vector search via Gemini Embedding 2 + ChromaDB."""
        try:
            from engine.nexus.vector_store import get_vector_store

            store = get_vector_store()
            # Search across knowledge and QA collections
            results = store.search_multi(
                query=question,
                collections=["knowledge", "qa", "code", "news"],
                top_k=5,
                min_score=0.5,
            )

            if not results:
                return None

            best = results[0]
            if best.score < 0.6:
                return None

            answer = best.text
            if not answer or len(answer) < self.MIN_ANSWER_LENGTH:
                return None

            # Build confidence from vector similarity score
            confidence = min(best.score * 0.95, 0.92)

            # Combine top results for richer answer
            if len(results) > 1 and results[1].score > 0.55:
                extra = results[1].text[:300]
                if extra:
                    answer += f"\n\nAlso relevant: {extra}"

            with self._lock:
                self._stats.vector_hits += 1
                tokens_saved = self._estimate_tokens(answer)
                self._stats.total_tokens_saved += tokens_saved

            return QueryResult(
                answer=answer,
                source="vector",
                confidence=confidence,
                cached=True,
                tokens_saved=tokens_saved,
                sources=[r.entry_id for r in results[:3]],
                metadata={
                    "top_score": best.score,
                    "collection": best.collection,
                    "result_count": len(results),
                },
            )
        except ImportError:
            logger.debug("Vector store not available (chromadb not installed)")
        except Exception as exc:
            logger.debug("Vector search failed: %s", exc)
        return None

    def _try_fts_search(self, client, question: str,
                        category: str = "") -> Optional[QueryResult]:
        """Tier 3: Full-text search across knowledge entries."""
        try:
            results = client.search(question, limit=5)
            if not results:
                return None

            # Score relevance based on title match and content length
            best = results[0]
            title = best.get("title", "").lower()
            question_words = set(question.lower().split())
            title_words = set(title.split())
            overlap = len(question_words & title_words)
            total = max(len(question_words), 1)
            title_score = overlap / total

            content = best.get("content", "")
            if len(content) < self.MIN_ANSWER_LENGTH:
                return None

            # Build confidence from title relevance + content length
            len_score = min(len(content) / 500, 1.0) * 0.3
            confidence = min(title_score * 0.7 + len_score, 0.85)

            if confidence < self.SEARCH_LOW:
                return None

            # Synthesise answer from top results
            answer = content[:800]
            if len(results) > 1:
                extra = results[1].get("content", "")[:200]
                if extra:
                    answer += f"\n\nAlso relevant: {extra}"

            with self._lock:
                self._stats.search_hits += 1
                tokens_saved = self._estimate_tokens(answer)
                self._stats.total_tokens_saved += tokens_saved

            return QueryResult(
                answer=answer,
                source="search",
                confidence=confidence,
                cached=True,
                tokens_saved=tokens_saved,
                sources=[r.get("title", "") for r in results[:3]],
            )
        except Exception as exc:
            logger.debug("FTS search failed: %s", exc)
        return None

    def _try_nexus_ask(self, client, question: str,
                       category: str = "", depth: str = "auto") -> Optional[QueryResult]:
        """Tier 3: Use Nexus server-side smart Q&A / NotebookLM pipeline."""
        try:
            ask_depth = depth if depth in {"shallow", "auto", "deep"} else "auto"
            result = client.ask(question, depth=ask_depth, category=category)
            answer = result.get("answer", "")
            if answer and len(answer) >= self.MIN_ANSWER_LENGTH:
                source = result.get("source", "nexus")
                confidence = result.get("confidence", 0.5)
                with self._lock:
                    if source == "nlm":
                        self._stats.nlm_hits += 1
                    else:
                        self._stats.cache_hits += 1
                    tokens_saved = self._estimate_tokens(answer)
                    self._stats.total_tokens_saved += tokens_saved
                return QueryResult(
                    answer=answer,
                    source=f"nexus-{source}",
                    confidence=confidence,
                    cached=True,
                    tokens_saved=tokens_saved,
                    sources=result.get("sources", []),
                )
        except Exception as exc:
            logger.debug("Nexus ask failed: %s", exc)
        return None

    def _try_direct_nlm(self, client, question: str) -> Optional[QueryResult]:
        """Tier 4: Ask NotebookLM directly through the unified backend."""
        if not self._nlm_backend_available(client):
            return None

        try:
            result = client.nlm_unified_ask(question)
            if not isinstance(result, dict):
                return None

            payload = result.get("data") if isinstance(result.get("data"), dict) else result
            answer = payload.get("answer", "")
            if not answer or len(answer) < self.MIN_ANSWER_LENGTH:
                return None

            raw_source = str(
                payload.get("source")
                or result.get("backend")
                or payload.get("backend")
                or "nlm"
            )
            source = raw_source if raw_source.startswith("nlm") else f"nlm-{raw_source}"
            confidence = float(payload.get("confidence", result.get("confidence", 0.8)))
            sources = payload.get("sources", result.get("sources", []))
            backend = result.get("backend") or payload.get("backend", "")

            with self._lock:
                self._stats.nlm_hits += 1
                tokens_saved = self._estimate_tokens(answer)
                self._stats.total_tokens_saved += tokens_saved

            return QueryResult(
                answer=answer,
                source=source,
                confidence=confidence,
                cached=True,
                tokens_saved=tokens_saved,
                sources=sources if isinstance(sources, list) else [],
                metadata={"backend": backend} if backend else {},
            )
        except Exception as exc:
            logger.debug("Direct NotebookLM ask failed: %s", exc)
        return None

    def _llm_fallback(self, question: str, category: str = "",
                      tags: Optional[List[str]] = None,
                      source_hint: str = "system") -> QueryResult:
        """Tier 5: Send to LLM and store the answer back in Nexus."""
        with self._lock:
            self._stats.llm_fallbacks += 1

        if self._llm_callback:
            try:
                answer = self._llm_callback(question)
                if answer:
                    return QueryResult(
                        answer=answer,
                        source="llm",
                        confidence=0.6,
                        cached=False,
                        tokens_saved=0,
                    )
            except Exception as exc:
                logger.warning("LLM callback failed: %s", exc)

        # Try LMStudio directly
        try:
            answer = self._call_lmstudio(question)
            if answer:
                return QueryResult(
                    answer=answer,
                    source="llm",
                    confidence=0.6,
                    cached=False,
                    tokens_saved=0,
                )
        except Exception as exc:
            logger.warning("LMStudio fallback failed: %s", exc)

        return QueryResult(answer="", source="llm", confidence=0.0)

    # ── LMStudio Integration ───────────────────────────────────────

    def _call_lmstudio(self, question: str) -> str:
        """Call LMStudio v1 API for inference."""
        cfg = get_config()
        host = cfg.get("lmstudio.host", "localhost")
        port = cfg.get("lmstudio.port", 1234)
        url = f"http://{host}:{port}/v1/chat/completions"

        payload = json.dumps({
            "messages": [
                {"role": "system", "content": (
                    "You are a knowledgeable assistant for the CosySim project. "
                    "Answer concisely and accurately. If unsure, say so."
                )},
                {"role": "user", "content": question},
            ],
            "temperature": 0.3,
            "max_tokens": 500,
            "stream": False,
        }).encode()

        import urllib.request
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
        except Exception as exc:
            logger.warning("LMStudio call failed: %s", exc)
        return ""

    # ── Storage ─────────────────────────────────────────────────────

    def _store_qa(self, client, question: str, answer: str,
                  category: str = "", tags: Optional[List[str]] = None,
                  source_hint: str = "system") -> None:
        """Store a Q&A pair in Nexus and feed to training flywheel."""
        try:
            all_tags = list(tags or []) + ["auto-cached", f"source:{source_hint}"]
            client.add_qa(
                question=question,
                answer=answer,
                category=category or "auto",
                tags=all_tags,
                quality_score=0.6,
            )
            logger.debug("Stored Q&A in Nexus: %s", question[:60])
        except Exception as exc:
            logger.debug("Failed to store Q&A: %s", exc)

        # Feed to training flywheel for fine-tuning data collection
        self._feed_training_flywheel(question, answer, source_hint, category)

    def _feed_training_flywheel(self, question: str, answer: str,
                                source: str, category: str) -> None:
        """Send Q&A pair to training flywheel for local model fine-tuning data."""
        try:
            from engine.nexus.training_flywheel import get_training_flywheel
            flywheel = get_training_flywheel()
            confidence = 0.7 if source in ("nlm", "nlm_direct") else 0.6
            flywheel.collect_from_qa(
                question=question,
                answer=answer,
                source=source,
                confidence=confidence,
                category=category or "auto",
            )
            logger.debug("Fed Q&A to training flywheel: %s", question[:60])
        except Exception as exc:
            logger.debug("Training flywheel feed failed (non-critical): %s", exc)

    def _nlm_backend_available(self, client) -> bool:
        """Best-effort check for any direct NotebookLM backend availability."""
        try:
            status = client.nlm_status()
        except Exception as exc:
            logger.debug("NLM status check failed; attempting unified ask anyway: %s", exc)
            return True

        details = (
            status.get("data")
            if isinstance(status, dict) and isinstance(status.get("data"), dict)
            else status
        )
        if not isinstance(details, dict):
            return True

        active_backend = details.get("active_backend")
        if isinstance(active_backend, str):
            return active_backend.lower() != "none"

        tiers = details.get("tiers")
        if isinstance(tiers, dict):
            nlm_tier = tiers.get("nlm")
            if isinstance(nlm_tier, dict) and "available" in nlm_tier:
                return bool(nlm_tier.get("available"))

        observed_backend_state = False
        for key in ("http", "browser"):
            backend = details.get(key)
            if isinstance(backend, dict) and "available" in backend:
                observed_backend_state = True
                if backend.get("available"):
                    return True
            elif isinstance(backend, bool):
                observed_backend_state = True
                if backend:
                    return True

        if "status" in details:
            return details.get("status") == "ok"

        if observed_backend_state:
            return False

        return True

    # ── Local Cache ─────────────────────────────────────────────────

    def _cache_key(self, question: str) -> str:
        normalized = question.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()

    def _check_local_cache(self, key: str) -> Optional[QueryResult]:
        cached = self._local_cache.get(key)
        if cached:
            result, ts = cached
            if time.time() - ts < self._local_cache_ttl:
                with self._lock:
                    self._stats.cache_hits += 1
                return QueryResult(
                    answer=result.answer,
                    source=f"{result.source}(local)",
                    confidence=result.confidence,
                    cached=True,
                    tokens_saved=result.tokens_saved,
                    sources=result.sources,
                )
            else:
                del self._local_cache[key]
        return None

    def _store_local_cache(self, key: str, result: QueryResult) -> None:
        self._local_cache[key] = (result, time.time())
        # Prune if too large
        if len(self._local_cache) > 200:
            oldest_key = min(self._local_cache, key=lambda k: self._local_cache[k][1])
            del self._local_cache[oldest_key]

    # ── Utilities ───────────────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate: ~4 chars per token."""
        return len(text) // 4

    def clear_local_cache(self) -> int:
        """Clear the local session cache. Returns count of cleared entries."""
        count = len(self._local_cache)
        self._local_cache.clear()
        return count

    def reset_stats(self) -> Dict[str, Any]:
        """Reset and return current stats."""
        with self._lock:
            current = self._stats.to_dict()
            self._stats = RouterStats()
        return current


# ── Singleton ───────────────────────────────────────────────────────

_router_instance: Optional[NexusQueryRouter] = None
_router_lock = threading.Lock()


def get_query_router(llm_callback: Optional[Callable] = None) -> NexusQueryRouter:
    """Get or create the singleton NexusQueryRouter."""
    global _router_instance
    with _router_lock:
        if _router_instance is None:
            _router_instance = NexusQueryRouter(llm_callback=llm_callback)
        return _router_instance
