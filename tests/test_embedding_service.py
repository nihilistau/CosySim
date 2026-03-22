"""Tests for engine.nexus.embedding_service — Gemini Embedding 2 integration."""
from __future__ import annotations

import math
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from engine.nexus.embedding_service import (
    EmbeddingCache,
    EmbeddingService,
    GeminiEmbeddingProvider,
    LMStudioEmbeddingProvider,
    TASK_TYPE_MAP,
    _l2_normalize,
    reset_embedding_service,
)


# ──── EmbeddingCache tests ────────────────────────────────────────────────────

class TestEmbeddingCache:
    def test_put_and_get(self) -> None:
        cache = EmbeddingCache(max_size=100)
        cache.put("hello", "RETRIEVAL_DOCUMENT", 768, [1.0, 2.0, 3.0])
        result = cache.get("hello", "RETRIEVAL_DOCUMENT", 768)
        assert result == [1.0, 2.0, 3.0]

    def test_miss_returns_none(self) -> None:
        cache = EmbeddingCache(max_size=100)
        assert cache.get("missing", "RETRIEVAL_DOCUMENT", 768) is None

    def test_different_task_types_are_separate(self) -> None:
        cache = EmbeddingCache(max_size=100)
        cache.put("hello", "RETRIEVAL_DOCUMENT", 768, [1.0])
        cache.put("hello", "RETRIEVAL_QUERY", 768, [2.0])
        assert cache.get("hello", "RETRIEVAL_DOCUMENT", 768) == [1.0]
        assert cache.get("hello", "RETRIEVAL_QUERY", 768) == [2.0]

    def test_different_dimensions_are_separate(self) -> None:
        cache = EmbeddingCache(max_size=100)
        cache.put("hello", "RETRIEVAL_DOCUMENT", 768, [1.0])
        cache.put("hello", "RETRIEVAL_DOCUMENT", 1536, [2.0])
        assert cache.get("hello", "RETRIEVAL_DOCUMENT", 768) == [1.0]
        assert cache.get("hello", "RETRIEVAL_DOCUMENT", 1536) == [2.0]

    def test_eviction_on_max_size(self) -> None:
        cache = EmbeddingCache(max_size=3)
        cache.put("a", "R", 768, [1.0])
        cache.put("b", "R", 768, [2.0])
        cache.put("c", "R", 768, [3.0])
        # Adding a 4th should evict "a"
        cache.put("d", "R", 768, [4.0])
        assert cache.get("a", "R", 768) is None
        assert cache.get("b", "R", 768) == [2.0]
        assert cache.get("d", "R", 768) == [4.0]

    def test_stats(self) -> None:
        cache = EmbeddingCache(max_size=100)
        cache.put("x", "R", 768, [1.0])
        cache.get("x", "R", 768)  # hit
        cache.get("y", "R", 768)  # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["hit_rate"] == 0.5


# ──── L2 normalization tests ─────────────────────────────────────────────────

class TestL2Normalize:
    def test_unit_vector_unchanged(self) -> None:
        vec = [1.0, 0.0, 0.0]
        result = _l2_normalize(vec)
        assert abs(result[0] - 1.0) < 1e-6
        assert abs(result[1]) < 1e-6

    def test_normalizes_to_unit_length(self) -> None:
        vec = [3.0, 4.0]
        result = _l2_normalize(vec)
        length = math.sqrt(sum(v * v for v in result))
        assert abs(length - 1.0) < 1e-6
        assert abs(result[0] - 0.6) < 1e-6
        assert abs(result[1] - 0.8) < 1e-6

    def test_zero_vector_unchanged(self) -> None:
        vec = [0.0, 0.0, 0.0]
        result = _l2_normalize(vec)
        assert result == [0.0, 0.0, 0.0]


# ──── Task type mapping tests ────────────────────────────────────────────────

class TestTaskTypeMap:
    def test_knowledge_maps_to_retrieval_document(self) -> None:
        assert TASK_TYPE_MAP["knowledge"] == "RETRIEVAL_DOCUMENT"

    def test_query_maps_to_retrieval_query(self) -> None:
        assert TASK_TYPE_MAP["query"] == "RETRIEVAL_QUERY"

    def test_code_maps_to_code_retrieval(self) -> None:
        assert TASK_TYPE_MAP["code"] == "CODE_RETRIEVAL_QUERY"

    def test_all_values_are_uppercase(self) -> None:
        for key, value in TASK_TYPE_MAP.items():
            assert value == value.upper(), f"{key} -> {value} should be uppercase"


# ──── GeminiEmbeddingProvider tests ──────────────────────────────────────────

class TestGeminiEmbeddingProvider:
    @patch("engine.nexus.embedding_service.GeminiEmbeddingProvider._get_client")
    def test_embed_calls_api_with_dimensions(self, mock_get) -> None:
        mock_client = MagicMock()
        mock_client.embed_content.return_value = [0.1, 0.2, 0.3]
        mock_get.return_value = mock_client

        provider = GeminiEmbeddingProvider(
            model="gemini-embedding-exp-03-07",
            output_dimensions=768,
        )
        result = provider.embed("test text", task_type="RETRIEVAL_DOCUMENT")

        mock_client.embed_content.assert_called_once_with(
            model="gemini-embedding-exp-03-07",
            content="test text",
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=768,
        )
        # Result should be L2-normalized since 768 < 3072
        assert len(result) == 3

    @patch("engine.nexus.embedding_service.GeminiEmbeddingProvider._get_client")
    def test_embed_no_normalize_at_3072(self, mock_get) -> None:
        mock_client = MagicMock()
        mock_client.embed_content.return_value = [1.0, 2.0, 3.0]
        mock_get.return_value = mock_client

        provider = GeminiEmbeddingProvider(output_dimensions=3072)
        result = provider.embed("test")

        mock_client.embed_content.assert_called_once()
        # At 3072 dims, output_dimensionality should not be passed
        call_kwargs = mock_client.embed_content.call_args
        assert call_kwargs[1].get("output_dimensionality") is None
        # And no normalization should happen
        assert result == [1.0, 2.0, 3.0]

    @patch("engine.nexus.embedding_service.GeminiEmbeddingProvider._get_client")
    def test_embed_batch(self, mock_get) -> None:
        mock_client = MagicMock()
        mock_client.batch_embed_contents.return_value = [[0.1], [0.2]]
        mock_get.return_value = mock_client

        provider = GeminiEmbeddingProvider(output_dimensions=768)
        result = provider.embed_batch(["a", "b"], task_type="RETRIEVAL_DOCUMENT")

        assert len(result) == 2
        mock_client.batch_embed_contents.assert_called_once()

    def test_properties(self) -> None:
        provider = GeminiEmbeddingProvider(
            model="gemini-embedding-exp-03-07",
            output_dimensions=1536,
        )
        assert provider.name == "gemini:gemini-embedding-exp-03-07"
        assert provider.dimensions == 1536


# ──── LMStudioEmbeddingProvider tests ────────────────────────────────────────

class TestLMStudioEmbeddingProvider:
    # v1.49.3 [2026-03-22] — Rewritten: mock _post() instead of removed _get_sdk()
    @patch.object(LMStudioEmbeddingProvider, "_post")
    def test_embed_single(self, mock_post) -> None:
        mock_post.return_value = {"data": [{"embedding": [0.5, 0.5]}]}
        provider = LMStudioEmbeddingProvider(model_key="test-model")
        result = provider.embed("hello")
        assert result == [0.5, 0.5]
        mock_post.assert_called_once()

    @patch.object(LMStudioEmbeddingProvider, "_post")
    def test_embed_batch_calls_post(self, mock_post) -> None:
        mock_post.return_value = {"data": [
            {"embedding": [0.1]}, {"embedding": [0.2]}, {"embedding": [0.3]}
        ]}
        provider = LMStudioEmbeddingProvider()
        result = provider.embed_batch(["a", "b", "c"])
        assert len(result) == 3
        assert result == [[0.1], [0.2], [0.3]]

    def test_name_with_model(self) -> None:
        provider = LMStudioEmbeddingProvider(model_key="nomic-embed")
        assert provider.name == "lmstudio:nomic-embed"

    def test_name_default(self) -> None:
        provider = LMStudioEmbeddingProvider()
        # Default model_key is "text-embedding"
        assert provider.name == "lmstudio:text-embedding"


# ──── EmbeddingService tests ────────────────────────────────────────────────

class TestEmbeddingService:
    def setup_method(self) -> None:
        reset_embedding_service()

    # v1.49.3 [2026-03-22] — Rewritten: inject mock provider via _providers list
    def test_embed_uses_cache(self) -> None:
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.embed.return_value = [0.1, 0.2, 0.3]

        svc = EmbeddingService(provider="gemini")
        svc._providers = [mock_provider]

        result1 = svc.embed("test query", purpose="knowledge")
        assert result1 == [0.1, 0.2, 0.3]
        assert mock_provider.embed.call_count == 1

        # Second call should hit cache
        result2 = svc.embed("test query", purpose="knowledge")
        assert result2 == [0.1, 0.2, 0.3]
        assert mock_provider.embed.call_count == 1  # still 1 — cache hit

    def test_purpose_maps_to_task_type(self) -> None:
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.embed.return_value = [0.1]

        svc = EmbeddingService(provider="gemini")
        svc._providers = [mock_provider]

        svc.embed("test_q", purpose="query")
        mock_provider.embed.assert_called_with("test_q", task_type="RETRIEVAL_QUERY")

        svc.embed("test_c", purpose="code")
        mock_provider.embed.assert_called_with("test_c", task_type="CODE_RETRIEVAL_QUERY")

    def test_embed_batch_caches_results(self) -> None:
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.embed_batch.return_value = [[0.1], [0.2]]

        svc = EmbeddingService(provider="gemini")
        svc._providers = [mock_provider]

        result = svc.embed_batch(["a", "b"], purpose="knowledge")
        assert len(result) == 2
        assert mock_provider.embed_batch.call_count == 1

        # Now "a" should be cached
        cached = svc._cache.get("a", "RETRIEVAL_DOCUMENT", svc._dimensions)
        assert cached == [0.1]

    def test_cosine_similarity_identical(self) -> None:
        svc = EmbeddingService(provider="gemini")
        score = svc.cosine_similarity([1.0, 0.0], [1.0, 0.0])
        assert abs(score - 1.0) < 1e-6

    def test_cosine_similarity_orthogonal(self) -> None:
        svc = EmbeddingService(provider="gemini")
        score = svc.cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(score) < 1e-6

    def test_cosine_similarity_opposite(self) -> None:
        svc = EmbeddingService(provider="gemini")
        score = svc.cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        assert abs(score - (-1.0)) < 1e-6

    def test_cosine_similarity_dimension_mismatch(self) -> None:
        svc = EmbeddingService(provider="gemini")
        with pytest.raises(ValueError, match="dimension mismatch"):
            svc.cosine_similarity([1.0], [1.0, 2.0])

    def test_find_similar(self) -> None:
        svc = EmbeddingService(provider="gemini")
        query = [1.0, 0.0, 0.0]
        candidates = [
            [0.9, 0.1, 0.0],  # most similar
            [0.0, 1.0, 0.0],  # orthogonal
            [0.7, 0.7, 0.0],  # moderately similar
        ]
        results = svc.find_similar(query, candidates, top_k=2)
        assert len(results) == 2
        assert results[0][0] == 0  # index 0 is most similar
        assert results[0][1] > results[1][1]

    def test_stats(self) -> None:
        svc = EmbeddingService(provider="gemini")
        stats = svc.stats()
        assert "model" in stats
        assert "dimensions" in stats
        assert "cache" in stats
        assert stats["total_embeds"] == 0

    def test_empty_batch_returns_empty(self) -> None:
        svc = EmbeddingService(provider="gemini")
        result = svc.embed_batch([], purpose="knowledge")
        assert result == []

    # v1.49.3 [2026-03-22] — Rewritten: inject mock providers for fallback test
    def test_fallback_on_provider_failure(self) -> None:
        failing_provider = MagicMock()
        failing_provider.name = "gemini"
        failing_provider.embed.side_effect = RuntimeError("API down")

        fallback_provider = MagicMock()
        fallback_provider.name = "lmstudio"
        fallback_provider.embed.return_value = [0.5, 0.5]

        svc = EmbeddingService(provider="auto")
        svc._providers = [failing_provider, fallback_provider]

        result = svc.embed("test", purpose="knowledge")
        assert result == [0.5, 0.5]
        assert failing_provider.embed.call_count == 1
        assert fallback_provider.embed.call_count == 1

    def test_active_provider_name_default(self) -> None:
        svc = EmbeddingService(provider="gemini")
        assert svc.active_provider_name == "none"  # not yet used

    def test_model_and_dimensions_properties(self) -> None:
        svc = EmbeddingService(
            model="test-model",
            dimensions=1536,
            provider="gemini",
        )
        assert svc.model == "test-model"
        assert svc.dimensions == 1536
