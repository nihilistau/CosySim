"""Tests for engine.nexus.vector_store — ChromaDB-backed Nexus vector store."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.vector_store import (
    COLLECTION_MAP,
    NexusVectorStore,
    VectorSearchResult,
    _sanitize_metadata,
    reset_vector_store,
)


# ──── Metadata sanitization ─────────────────────────────────────────────────

class TestSanitizeMetadata:
    def test_string_values_pass_through(self) -> None:
        result = _sanitize_metadata({"key": "value"})
        assert result == {"key": "value"}

    def test_numeric_values_pass_through(self) -> None:
        result = _sanitize_metadata({"count": 42, "rate": 0.95})
        assert result == {"count": 42, "rate": 0.95}

    def test_bool_values_pass_through(self) -> None:
        result = _sanitize_metadata({"active": True})
        assert result == {"active": True}

    def test_list_values_joined(self) -> None:
        result = _sanitize_metadata({"tags": ["a", "b", "c"]})
        assert result == {"tags": "a,b,c"}

    def test_none_values_excluded(self) -> None:
        result = _sanitize_metadata({"key": None})
        assert result == {}

    def test_complex_values_stringified(self) -> None:
        result = _sanitize_metadata({"data": {"nested": True}})
        assert result == {"data": "{'nested': True}"}


# ──── VectorSearchResult tests ───────────────────────────────────────────────

class TestVectorSearchResult:
    def test_creation(self) -> None:
        r = VectorSearchResult(
            entry_id="test-1",
            text="Hello world",
            score=0.85,
            metadata={"category": "test"},
            collection="knowledge",
        )
        assert r.entry_id == "test-1"
        assert r.score == 0.85
        assert r.collection == "knowledge"

    def test_default_values(self) -> None:
        r = VectorSearchResult(entry_id="x", text="y", score=0.5)
        assert r.metadata == {}
        assert r.collection == "knowledge"


# ──── Collection map tests ───────────────────────────────────────────────────

class TestCollectionMap:
    def test_standard_collections_exist(self) -> None:
        assert "knowledge" in COLLECTION_MAP
        assert "qa" in COLLECTION_MAP
        assert "code" in COLLECTION_MAP
        assert "news" in COLLECTION_MAP

    def test_collection_names_are_prefixed(self) -> None:
        for key, name in COLLECTION_MAP.items():
            assert name.startswith("nexus_"), f"{key} -> {name} missing prefix"


# ──── NexusVectorStore unit tests (mocked ChromaDB) ──────────────────────────

class TestNexusVectorStoreUnit:
    """Unit tests with mocked ChromaDB — no real DB needed."""

    def setup_method(self) -> None:
        reset_vector_store()

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_add_calls_upsert(self, mock_get_client) -> None:
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        store = NexusVectorStore(persist_dir="/tmp/test_vectors")
        store._client = mock_client
        store.add("entry-1", "Hello world", metadata={"category": "test"})

        mock_collection.upsert.assert_called_once()
        call_kwargs = mock_collection.upsert.call_args
        assert call_kwargs[1]["ids"] == ["entry-1"]
        assert call_kwargs[1]["documents"] == ["Hello world"]

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_add_skips_empty_text(self, mock_get_client) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        store = NexusVectorStore(persist_dir="/tmp/test_vectors")
        store._client = mock_client
        store.add("entry-1", "")  # empty text

        # Should not try to get/create collection
        mock_client.get_or_create_collection.assert_not_called()

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_add_truncates_long_text(self, mock_get_client) -> None:
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        store = NexusVectorStore(persist_dir="/tmp/test_vectors")
        store._client = mock_client
        long_text = "x" * 20000
        store.add("entry-1", long_text)

        call_kwargs = mock_collection.upsert.call_args
        assert len(call_kwargs[1]["documents"][0]) == 10000

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_remove(self, mock_get_client) -> None:
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        store = NexusVectorStore(persist_dir="/tmp/test_vectors")
        store._client = mock_client
        result = store.remove("entry-1")

        assert result is True
        mock_collection.delete.assert_called_once_with(ids=["entry-1"])

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_has_returns_true_when_found(self, mock_get_client) -> None:
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": ["entry-1"]}
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        store = NexusVectorStore(persist_dir="/tmp/test_vectors")
        store._client = mock_client
        assert store.has("entry-1") is True

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_has_returns_false_when_missing(self, mock_get_client) -> None:
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        store = NexusVectorStore(persist_dir="/tmp/test_vectors")
        store._client = mock_client
        assert store.has("entry-1") is False

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_count(self, mock_get_client) -> None:
        mock_collection = MagicMock()
        mock_collection.count.return_value = 42
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        store = NexusVectorStore(persist_dir="/tmp/test_vectors")
        store._client = mock_client
        assert store.count("knowledge") == 42

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_search_returns_results(self, mock_get_client) -> None:
        mock_collection = MagicMock()
        mock_collection.count.return_value = 5
        mock_collection.query.return_value = {
            "ids": [["id1", "id2"]],
            "documents": [["doc1 content", "doc2 content"]],
            "metadatas": [[{"category": "test"}, {}]],
            "distances": [[0.2, 0.5]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        with patch("engine.nexus.embedding_service.get_embedding_service") as mock_svc:
            mock_svc_instance = MagicMock()
            mock_svc_instance.embed.return_value = [0.1, 0.2, 0.3]
            mock_svc.return_value = mock_svc_instance

            store = NexusVectorStore(persist_dir="/tmp/test_vectors")
            store._client = mock_client
            results = store.search("test query", top_k=5)

        assert len(results) == 2
        assert results[0].entry_id == "id1"
        assert results[0].score == 0.8  # 1.0 - 0.2
        assert results[1].entry_id == "id2"
        assert results[1].score == 0.5  # 1.0 - 0.5

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_search_respects_min_score(self, mock_get_client) -> None:
        mock_collection = MagicMock()
        mock_collection.count.return_value = 5
        mock_collection.query.return_value = {
            "ids": [["id1", "id2"]],
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{}, {}]],
            "distances": [[0.1, 0.8]],  # scores: 0.9, 0.2
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        with patch("engine.nexus.embedding_service.get_embedding_service") as mock_svc:
            mock_svc_instance = MagicMock()
            mock_svc_instance.embed.return_value = [0.1]
            mock_svc.return_value = mock_svc_instance

            store = NexusVectorStore(persist_dir="/tmp/test_vectors")
            store._client = mock_client
            results = store.search("test", min_score=0.5)

        # Only id1 (score 0.9) should pass the 0.5 threshold
        assert len(results) == 1
        assert results[0].entry_id == "id1"

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_search_empty_query_returns_empty(self, mock_get_client) -> None:
        store = NexusVectorStore(persist_dir="/tmp/test_vectors")
        results = store.search("")
        assert results == []

    def test_stats(self) -> None:
        store = NexusVectorStore(persist_dir="/tmp/test_vectors")
        stats = store.stats()
        assert "persist_dir" in stats
        assert stats["total_adds"] == 0
        assert stats["total_searches"] == 0

    def test_list_collections(self) -> None:
        store = NexusVectorStore(persist_dir="/tmp/test_vectors")
        colls = store.list_collections()
        assert "knowledge" in colls
        assert "qa" in colls
        assert len(colls) >= 4

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_batch_add(self, mock_get_client) -> None:
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        store = NexusVectorStore(persist_dir="/tmp/test_vectors")
        store._client = mock_client
        entries = [
            {"id": "e1", "text": "First entry", "metadata": {"cat": "a"}},
            {"id": "e2", "text": "Second entry"},
            {"id": "e3", "text": ""},  # empty — should be skipped
        ]
        count = store.add_batch(entries)
        assert count == 2  # e3 skipped
        mock_collection.upsert.assert_called_once()

    @patch("engine.nexus.vector_store.NexusVectorStore._get_client")
    def test_search_multi(self, mock_get_client) -> None:
        """search_multi merges results from multiple collections."""
        mock_collection = MagicMock()
        mock_collection.count.return_value = 1
        mock_collection.query.return_value = {
            "ids": [["id1"]],
            "documents": [["content"]],
            "metadatas": [[{}]],
            "distances": [[0.3]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        with patch("engine.nexus.embedding_service.get_embedding_service") as mock_svc:
            mock_svc_instance = MagicMock()
            mock_svc_instance.embed.return_value = [0.1]
            mock_svc.return_value = mock_svc_instance

            store = NexusVectorStore(persist_dir="/tmp/test_vectors")
            store._client = mock_client
            results = store.search_multi("test", collections=["knowledge", "qa"])

        # Should have searched both collections
        assert len(results) >= 1


# ──── Integration-style test with real ChromaDB (if available) ──────────────

class TestNexusVectorStoreIntegration:
    """Integration tests using real ChromaDB in a temp directory."""

    @pytest.fixture
    def store(self, tmp_path) -> NexusVectorStore:
        """Create a store with mocked embedding service in temp dir."""
        mock_svc = MagicMock()
        mock_svc.embed_batch.return_value = [[0.1, 0.2, 0.3]]
        mock_svc.embed.return_value = [0.1, 0.2, 0.3]
        with patch("engine.nexus.embedding_service.get_embedding_service", return_value=mock_svc):
            s = NexusVectorStore(persist_dir=str(tmp_path / "vectors"))
            yield s

    def test_add_and_count(self, store: NexusVectorStore) -> None:
        store.add("test-1", "Hello world")
        assert store.count("knowledge") == 1

    def test_add_and_has(self, store: NexusVectorStore) -> None:
        store.add("test-1", "Hello world")
        assert store.has("test-1", "knowledge") is True
        assert store.has("nonexistent", "knowledge") is False

    def test_add_and_remove(self, store: NexusVectorStore) -> None:
        store.add("test-1", "Hello world")
        assert store.count("knowledge") == 1
        store.remove("test-1")
        assert store.count("knowledge") == 0

    def test_upsert_overwrites(self, store: NexusVectorStore) -> None:
        store.add("test-1", "Version 1")
        store.add("test-1", "Version 2")
        assert store.count("knowledge") == 1  # upsert, not duplicate

    def test_different_collections_are_independent(self, store: NexusVectorStore) -> None:
        store.add("e1", "Knowledge entry", collection="knowledge")
        store.add("e2", "Code snippet", collection="code")
        assert store.count("knowledge") == 1
        assert store.count("code") == 1
