"""Unified embedding service — Gemini Embedding 2 with MRL + local fallback.

Provides a single interface for generating text embeddings using:
  1. Gemini Embedding 2 (primary) — MRL support, 768/1536/3072 dimensions
  2. LMStudio SDK (local fallback) — offline capable, any loaded embedding model
  3. sentence-transformers (legacy fallback) — ChromaDB-compatible

The service auto-selects the best available provider and handles caching,
normalization, batching, and rate limiting transparently.

Usage:
    from engine.nexus.embedding_service import get_embedding_service

    svc = get_embedding_service()
    vec = svc.embed("How does the interceptor pipeline work?", purpose="query")
    vecs = svc.embed_batch(["text1", "text2"], purpose="knowledge")
    score = svc.similarity(vec_a, vec_b)
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, Union

import requests

from engine.config import get_config

logger = logging.getLogger(__name__)

# ──── Task type mapping ──────────────────────────────────────────────────────

TASK_TYPE_MAP: Dict[str, str] = {
    "knowledge": "RETRIEVAL_DOCUMENT",
    "document": "RETRIEVAL_DOCUMENT",
    "query": "RETRIEVAL_QUERY",
    "search": "RETRIEVAL_QUERY",
    "qa_question": "QUESTION_ANSWERING",
    "qa_answer": "RETRIEVAL_DOCUMENT",
    "similarity": "SEMANTIC_SIMILARITY",
    "code": "CODE_RETRIEVAL_QUERY",
    "code_doc": "RETRIEVAL_DOCUMENT",
    "classify": "CLASSIFICATION",
    "cluster": "CLUSTERING",
    "fact_check": "FACT_VERIFICATION",
}

# Valid MRL dimensions for Gemini Embedding 2
VALID_MRL_DIMENSIONS = {768, 1536, 3072}


# ──── Embedding cache ────────────────────────────────────────────────────────

class EmbeddingCache:
    """Thread-safe in-memory LRU cache for embedding vectors."""

    def __init__(self, max_size: int = 10000) -> None:
        self._cache: Dict[str, List[float]] = {}
        self._access_order: List[str] = []
        self._max_size = max_size
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _make_key(self, text: str, task_type: str, dimensions: int) -> str:
        h = hashlib.sha256(f"{text}|{task_type}|{dimensions}".encode()).hexdigest()[:24]
        return h

    def get(self, text: str, task_type: str, dimensions: int) -> Optional[List[float]]:
        key = self._make_key(text, task_type, dimensions)
        with self._lock:
            if key in self._cache:
                self._hits += 1
                self._access_order.remove(key)
                self._access_order.append(key)
                return self._cache[key]
            self._misses += 1
        return None

    def put(self, text: str, task_type: str, dimensions: int,
            vector: List[float]) -> None:
        key = self._make_key(text, task_type, dimensions)
        with self._lock:
            if key in self._cache:
                self._access_order.remove(key)
            elif len(self._cache) >= self._max_size:
                oldest = self._access_order.pop(0)
                del self._cache[oldest]
            self._cache[key] = vector
            self._access_order.append(key)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / max(total, 1), 3),
            }


# ──── Provider protocol ──────────────────────────────────────────────────────

class EmbeddingProvider(Protocol):
    """Interface for embedding providers."""

    @property
    def name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]: ...

    def embed_batch(self, texts: List[str],
                    task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]: ...


# ──── Gemini Embedding 2 provider ────────────────────────────────────────────

class GeminiEmbeddingProvider:
    """Gemini Embedding 2 via AIStudio REST API with MRL support."""

    def __init__(
        self,
        model: str = "gemini-embedding-exp-03-07",
        output_dimensions: int = 768,
        api_key_index: int = 0,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._model = model
        self._dimensions = output_dimensions
        self._api_key_index = api_key_index
        self._client: Any = None
        self._lock = threading.Lock()
        self._call_count = 0
        self._error_count = 0
        self._last_error: Optional[str] = None

    @property
    def name(self) -> str:
        return f"gemini:{self._model}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _get_client(self) -> Any:
        if not self._enabled:
            raise RuntimeError("Gemini embedding provider disabled")
        if self._client is None:
            try:
                from engine.integrations.aistudio_client import get_aistudio_client

                self._client = get_aistudio_client()
            except Exception as exc:
                logger.error("Failed to create AIStudioClient: %s", exc)
                raise
        return self._client

    def embed(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]:
        """Generate a single embedding vector."""
        client = self._get_client()
        try:
            vector = client.embed_content(
                model=self._model,
                content=text,
                task_type=task_type,
                output_dimensionality=self._dimensions if self._dimensions != 3072 else None,
            )
            self._call_count += 1
            if self._dimensions < 3072:
                vector = _l2_normalize(vector)
            return vector
        except Exception as exc:
            self._error_count += 1
            self._last_error = str(exc)
            logger.warning("Gemini embed failed: %s", exc)
            raise

    def embed_batch(self, texts: List[str],
                    task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
        """Generate embeddings for multiple texts in one API call."""
        if not texts:
            return []
        client = self._get_client()
        try:
            vectors = client.batch_embed_contents(
                model=self._model,
                texts=texts,
                task_type=task_type,
                output_dimensionality=self._dimensions if self._dimensions != 3072 else None,
            )
            self._call_count += 1
            if self._dimensions < 3072:
                vectors = [_l2_normalize(v) for v in vectors]
            return vectors
        except Exception as exc:
            self._error_count += 1
            self._last_error = str(exc)
            logger.warning("Gemini batch embed failed (%d texts): %s", len(texts), exc)
            raise


# ──── LMStudio local provider ────────────────────────────────────────────────

class LMStudioEmbeddingProvider:
    """Local embedding via LMStudio REST API (OpenAI-compatible)."""

    # v1.44.0 [2026-03-21] — Reads api_token from config instead of constructor param
    def __init__(
        self,
        model_key: Optional[str] = None,
        api_host: Optional[str] = None,
        api_token: Optional[str] = None,
    ) -> None:
        self._model_key = model_key or "text-embedding"
        base = api_host or "127.0.0.1:1234"
        self._base_url = base if base.startswith("http") else f"http://{base}"
        # Resolve token: explicit param → config → None
        if api_token:
            self._api_token = api_token
        else:
            try:
                from engine.config import get_config
                self._api_token = get_config().get("lmstudio.api_token", "") or None
            except Exception:
                self._api_token = None
        self._session = requests.Session()
        self._dimensions_cache: Optional[int] = None
        self._call_count = 0
        self._error_count = 0

    @property
    def name(self) -> str:
        return f"lmstudio:{self._model_key or 'auto'}"

    @property
    def dimensions(self) -> int:
        if self._dimensions_cache is not None:
            return self._dimensions_cache
        try:
            test_vec = self.embed("test")
            self._dimensions_cache = len(test_vec)
            return self._dimensions_cache
        except Exception:
            return 768  # reasonable default

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        return headers

    # v1.50.1 [2026-03-22] — Retry logic + dual endpoint fallback for LMStudio
    # CONNECTS: LMStudio REST API (/v1/embeddings or /api/v0/embeddings)
    # CALLED BY: embed(), embed_batch()
    _ENDPOINTS = ["/v1/embeddings", "/api/v0/embeddings"]

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            for endpoint in self._ENDPOINTS:
                try:
                    resp = self._session.post(
                        f"{self._base_url}{endpoint}",
                        headers=self._headers(),
                        json=payload,
                        timeout=45,
                    )
                    if resp.status_code >= 400:
                        raise RuntimeError(
                            f"LMStudio embed HTTP {resp.status_code} on {endpoint}: "
                            f"{resp.text[:200]}"
                        )
                    try:
                        data = resp.json()
                    except Exception as exc:
                        raise RuntimeError(f"LMStudio embed invalid JSON: {exc}") from exc
                    # LMStudio may return 200 with error body when no model loaded
                    if "error" in data:
                        err_msg = data.get("error", {})
                        if isinstance(err_msg, dict):
                            err_msg = err_msg.get("message", str(err_msg))
                        raise RuntimeError(f"LMStudio embed error: {err_msg}")
                    if not data.get("data"):
                        raise RuntimeError(
                            "LMStudio embed returned no data — is an embedding model loaded?"
                        )
                    return data
                except Exception as exc:
                    last_exc = exc
                    logger.debug(
                        "LMStudio embed attempt %d/%d on %s failed: %s",
                        attempt + 1, 3, endpoint, exc,
                    )
            # Brief pause before retry (model may be loading)
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(
            f"LMStudio embed failed after 3 attempts across {len(self._ENDPOINTS)} "
            f"endpoints. Last error: {last_exc}"
        )

    def _extract_embeddings(self, data: Dict[str, Any]) -> List[List[float]]:
        items = data.get("data") or []
        vectors: List[List[float]] = []
        for item in items:
            vec = item.get("embedding")
            if vec is None:
                continue
            vectors.append(list(vec))
        return vectors

    def embed(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]:
        """Generate embedding using LMStudio's REST API."""
        payload = {
            "model": self._model_key,
            "input": text,
        }
        data = self._post(payload)
        vectors = self._extract_embeddings(data)
        if not vectors:
            raise RuntimeError("LMStudio embed returned no vectors")
        self._call_count += 1
        return vectors[0]

    def embed_batch(
        self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> List[List[float]]:
        """Generate embeddings via a single LMStudio batch call."""
        if not texts:
            return []
        payload = {
            "model": self._model_key,
            "input": texts,
        }
        data = self._post(payload)
        vectors = self._extract_embeddings(data)
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"LMStudio embed_batch mismatch: expected {len(texts)}, got {len(vectors)}"
            )
        self._call_count += 1
        return vectors


# ──── Embedding service (unified interface) ──────────────────────────────────

@dataclass
class EmbeddingStats:
    """Cumulative embedding service statistics."""
    total_embeds: int = 0
    batch_embeds: int = 0
    cache_hits: int = 0
    provider_used: Dict[str, int] = field(default_factory=dict)
    errors: int = 0
    total_texts: int = 0
    avg_latency_ms: float = 0.0
    _latency_sum: float = 0.0


class EmbeddingService:
    """Unified embedding service with automatic provider selection and caching.

    Tries providers in order:
      1. Gemini Embedding 2 (primary — best quality, MRL support)
      2. LMStudio SDK (local fallback — offline capable)

    All vectors are cached in memory to avoid redundant API calls.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        provider: Optional[str] = None,
        local_model_key: Optional[str] = None,
        cache_size: int = 10000,
        batch_size: int = 100,
        api_key_index: int = 0,
    ) -> None:
        cfg = get_config()
        self._model = model or cfg.get(
            "nexus.embeddings.model", "gemini-embedding-exp-03-07"
        )
        self._dimensions = dimensions or cfg.get(
            "nexus.embeddings.dimensions", 768
        )
        self._preferred_provider = provider or cfg.get(
            "nexus.embeddings.provider", "gemini"
        )
        self._local_model_key = local_model_key or cfg.get(
            "nexus.embeddings.local_model", None
        )
        self._batch_size = batch_size
        self._api_key_index = api_key_index
        self._enable_gemini = cfg.get("nexus.embeddings.enable_gemini", False)
        self._lmstudio_host = cfg.get("lmstudio.host", "127.0.0.1")
        self._lmstudio_port = cfg.get("lmstudio.port", 1234)
        self._lmstudio_token = cfg.get("lmstudio.api_token", None)

        self._cache = EmbeddingCache(max_size=cache_size)
        self._stats = EmbeddingStats()
        self._lock = threading.Lock()

        # Build provider chain (lazy — providers instantiated on first use)
        self._providers: List[EmbeddingProvider] = []
        self._active_provider: Optional[EmbeddingProvider] = None

    def _ensure_providers(self) -> None:
        """Lazily build the provider chain."""
        if self._providers:
            return

        providers: List[EmbeddingProvider] = []

        if self._enable_gemini and self._preferred_provider in ("gemini", "auto"):
            try:
                gp = GeminiEmbeddingProvider(
                    model=self._model,
                    output_dimensions=self._dimensions,
                    api_key_index=self._api_key_index,
                    enabled=self._enable_gemini,
                )
                providers.append(gp)
            except Exception as exc:
                logger.warning("Cannot create Gemini provider: %s", exc)

        if self._preferred_provider in ("local", "auto", "gemini"):
            try:
                api_host = f"{self._lmstudio_host}:{self._lmstudio_port}"
                lp = LMStudioEmbeddingProvider(
                    model_key=self._local_model_key,
                    api_host=api_host,
                    api_token=self._lmstudio_token,
                )
                providers.append(lp)
            except Exception as exc:
                logger.debug("Cannot create LMStudio provider: %s", exc)

        if not providers:
            logger.error("No embedding providers available!")

        self._providers = providers
        if providers:
            self._active_provider = providers[0]

    def _resolve_task_type(self, purpose: str) -> str:
        """Map a human-readable purpose to a Gemini task type."""
        return TASK_TYPE_MAP.get(purpose, purpose)

    def embed(self, text: str, purpose: str = "knowledge") -> List[float]:
        """Generate an embedding vector for a single text.

        Args:
            text: Text to embed.
            purpose: Semantic purpose — one of: knowledge, query, qa_question,
                qa_answer, similarity, code, classify, cluster, fact_check.
                Can also be a raw Gemini task type like RETRIEVAL_DOCUMENT.

        Returns:
            List of float embedding values.
        """
        task_type = self._resolve_task_type(purpose)

        # Check cache first
        cached = self._cache.get(text, task_type, self._dimensions)
        if cached is not None:
            with self._lock:
                self._stats.cache_hits += 1
            return cached

        self._ensure_providers()
        start = time.time()
        last_exc: Optional[Exception] = None

        for provider in self._providers:
            try:
                vector = provider.embed(text, task_type=task_type)
                elapsed_ms = (time.time() - start) * 1000

                self._cache.put(text, task_type, self._dimensions, vector)
                with self._lock:
                    self._stats.total_embeds += 1
                    self._stats.total_texts += 1
                    pname = provider.name
                    self._stats.provider_used[pname] = (
                        self._stats.provider_used.get(pname, 0) + 1
                    )
                    self._stats._latency_sum += elapsed_ms
                    self._stats.avg_latency_ms = (
                        self._stats._latency_sum
                        / (self._stats.total_embeds + self._stats.batch_embeds)
                    )
                    self._active_provider = provider

                return vector

            except Exception as exc:
                last_exc = exc
                logger.debug("Provider %s failed, trying next: %s", provider.name, exc)
                continue

        with self._lock:
            self._stats.errors += 1
        if last_exc:
            logger.warning(
                "All embedding providers failed (graceful skip). Last: %s",
                last_exc,
            )
        else:
            logger.warning("No embedding providers configured (graceful skip)")
        return []

    def embed_batch(
        self, texts: List[str], purpose: str = "knowledge"
    ) -> List[List[float]]:
        """Generate embeddings for multiple texts with batching.

        Args:
            texts: List of texts to embed.
            purpose: Semantic purpose for all texts.

        Returns:
            List of embedding vectors, one per input text.
        """
        if not texts:
            return []

        task_type = self._resolve_task_type(purpose)
        results: List[Optional[List[float]]] = [None] * len(texts)
        uncached_indices: List[int] = []

        # Check cache for each text
        for i, text in enumerate(texts):
            cached = self._cache.get(text, task_type, self._dimensions)
            if cached is not None:
                results[i] = cached
                with self._lock:
                    self._stats.cache_hits += 1
            else:
                uncached_indices.append(i)

        if not uncached_indices:
            return results  # type: ignore[return-value]

        # Batch embed uncached texts
        uncached_texts = [texts[i] for i in uncached_indices]
        self._ensure_providers()
        start = time.time()
        last_exc: Optional[Exception] = None

        for provider in self._providers:
            try:
                # Process in chunks of batch_size
                all_vectors: List[List[float]] = []
                for chunk_start in range(0, len(uncached_texts), self._batch_size):
                    chunk = uncached_texts[chunk_start:chunk_start + self._batch_size]
                    chunk_vectors = provider.embed_batch(chunk, task_type=task_type)
                    all_vectors.extend(chunk_vectors)

                elapsed_ms = (time.time() - start) * 1000

                # Place results and cache them
                for j, idx in enumerate(uncached_indices):
                    results[idx] = all_vectors[j]
                    self._cache.put(
                        texts[idx], task_type, self._dimensions, all_vectors[j]
                    )

                with self._lock:
                    self._stats.batch_embeds += 1
                    self._stats.total_texts += len(uncached_texts)
                    pname = provider.name
                    self._stats.provider_used[pname] = (
                        self._stats.provider_used.get(pname, 0) + 1
                    )
                    self._stats._latency_sum += elapsed_ms
                    self._stats.avg_latency_ms = (
                        self._stats._latency_sum
                        / max(self._stats.total_embeds + self._stats.batch_embeds, 1)
                    )
                    self._active_provider = provider

                return results  # type: ignore[return-value]

            except Exception as exc:
                last_exc = exc
                logger.debug(
                    "Provider %s batch failed, trying next: %s", provider.name, exc
                )
                continue

        with self._lock:
            self._stats.errors += 1
        if last_exc:
            logger.warning(
                "All providers failed for batch embed (graceful skip). Last: %s",
                last_exc,
            )
        else:
            logger.warning("No embedding providers configured for batch (graceful skip)")
        return []

    # ──── Similarity utilities ────────────────────────────────────────────

    @staticmethod
    def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(vec_a) != len(vec_b):
            raise ValueError(
                f"Vector dimension mismatch: {len(vec_a)} vs {len(vec_b)}"
            )
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two embedding vectors."""
        return self.cosine_similarity(vec_a, vec_b)

    def find_similar(
        self,
        query_vec: List[float],
        candidates: List[List[float]],
        top_k: int = 5,
    ) -> List[Tuple[int, float]]:
        """Find the top-K most similar vectors from a candidate list.

        Args:
            query_vec: Query embedding vector.
            candidates: List of candidate embedding vectors.
            top_k: Number of top results to return.

        Returns:
            List of (index, similarity_score) tuples, sorted descending.
        """
        scores = [
            (i, self.cosine_similarity(query_vec, c)) for i, c in enumerate(candidates)
        ]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    # ──── Service metadata ────────────────────────────────────────────────

    @property
    def active_provider_name(self) -> str:
        if self._active_provider:
            return self._active_provider.name
        return "none"

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def stats(self) -> Dict[str, Any]:
        """Return cumulative service statistics."""
        with self._lock:
            return {
                "model": self._model,
                "dimensions": self._dimensions,
                "provider": self.active_provider_name,
                "total_embeds": self._stats.total_embeds,
                "batch_embeds": self._stats.batch_embeds,
                "total_texts": self._stats.total_texts,
                "cache": self._cache.stats(),
                "errors": self._stats.errors,
                "avg_latency_ms": round(self._stats.avg_latency_ms, 1),
                "provider_usage": dict(self._stats.provider_used),
            }


# ──── Math helpers ────────────────────────────────────────────────────────────

def _l2_normalize(vector: List[float]) -> List[float]:
    """L2-normalize a vector (required for MRL dimensions < 3072)."""
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


# ──── Singleton ───────────────────────────────────────────────────────────────

_service_instance: Optional[EmbeddingService] = None
_service_lock = threading.Lock()


def get_embedding_service(**kwargs: Any) -> EmbeddingService:
    """Get or create the singleton EmbeddingService."""
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            if _service_instance is None:
                _service_instance = EmbeddingService(**kwargs)
    return _service_instance


def reset_embedding_service() -> None:
    """Reset the singleton (for testing)."""
    global _service_instance
    with _service_lock:
        _service_instance = None
