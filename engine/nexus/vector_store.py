"""ChromaDB-backed vector store for Nexus semantic search.

Provides persistent vector storage and similarity search for all Nexus content
using the unified EmbeddingService (Gemini Embedding 2 or local fallback).

Collections mirror Nexus content types:
  - nexus_knowledge — general knowledge entries
  - nexus_qa — question-answer pairs
  - nexus_code — code snippets and patterns
  - nexus_news — news articles and digests

Usage:
    from engine.nexus.vector_store import get_vector_store

    store = get_vector_store()
    store.add("entry-123", "Content text...", metadata={"category": "arch"})
    results = store.search("How does the interceptor work?", top_k=5)
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from engine.config import get_config

logger = logging.getLogger(__name__)

# ──── Constants ──────────────────────────────────────────────────────────────

COLLECTION_MAP: Dict[str, str] = {
    "knowledge": "nexus_knowledge",
    "qa": "nexus_qa",
    "code": "nexus_code",
    "news": "nexus_news",
    "research": "nexus_research",
    "prompt": "nexus_prompts",
    "memory": "nexus_memories",
    "document": "nexus_documents",
}

DEFAULT_PERSIST_DIR = "data/nexus_vectors"


# ──── Custom ChromaDB embedding function ─────────────────────────────────────

class _ServiceEmbeddingFunction:
    """ChromaDB-compatible embedding function backed by EmbeddingService.

    This bridges ChromaDB's embedding function interface with our unified
    embedding service, so ChromaDB uses Gemini Embedding 2 instead of
    the default all-MiniLM-L6-v2.
    """

    def __init__(self, purpose: str = "knowledge") -> None:
        self._purpose = purpose
        self._svc: Any = None

    def _get_service(self) -> Any:
        if self._svc is None:
            from engine.nexus.embedding_service import get_embedding_service
            self._svc = get_embedding_service()
        return self._svc

    def name(self) -> str:
        """ChromaDB requires a name() method on embedding functions."""
        return "gemini-embedding-service"

    @property
    def is_legacy(self) -> bool:
        """ChromaDB compatibility — mark as non-legacy embedding function."""
        return False

    def __call__(self, input: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of documents (ChromaDB interface)."""
        svc = self._get_service()
        return svc.embed_batch(input, purpose=self._purpose)


# ──── Vector store ───────────────────────────────────────────────────────────

@dataclass
class VectorSearchResult:
    """A single vector search result."""
    entry_id: str
    text: str
    score: float  # similarity score (higher = more similar)
    metadata: Dict[str, Any] = field(default_factory=dict)
    collection: str = "knowledge"


class NexusVectorStore:
    """Persistent vector store for Nexus content using ChromaDB.

    Each Nexus content type maps to a separate ChromaDB collection with
    appropriate embedding functions. All collections use the same
    EmbeddingService (Gemini Embedding 2 or local fallback).
    """

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        embedding_service: Optional[Any] = None,
    ) -> None:
        cfg = get_config()
        self._persist_dir = Path(
            persist_dir or cfg.get("nexus.vector_store.persist_dir", DEFAULT_PERSIST_DIR)
        )
        self._persist_dir.mkdir(parents=True, exist_ok=True)

        self._embedding_service = embedding_service
        self._client: Any = None
        self._collections: Dict[str, Any] = {}
        self._lock = threading.Lock()

        # Stats
        self._adds = 0
        self._searches = 0
        self._removes = 0

    def _get_client(self) -> Any:
        """Lazy-init ChromaDB client."""
        if self._client is None:
            try:
                import chromadb
                from chromadb.config import Settings

                self._client = chromadb.PersistentClient(
                    path=str(self._persist_dir),
                    settings=Settings(
                        anonymized_telemetry=False,
                        allow_reset=True,
                    ),
                )
            except ImportError:
                raise RuntimeError(
                    "chromadb is required for vector store. "
                    "Install with: pip install chromadb"
                )
        return self._client

    def _get_collection(self, collection_key: str) -> Any:
        """Get or create a ChromaDB collection."""
        if collection_key in self._collections:
            return self._collections[collection_key]

        client = self._get_client()
        collection_name = COLLECTION_MAP.get(collection_key, f"nexus_{collection_key}")

        # Create embedding function that routes through our EmbeddingService
        # The purpose determines the task type (RETRIEVAL_DOCUMENT vs RETRIEVAL_QUERY)
        purpose = "knowledge" if collection_key != "qa" else "qa_answer"
        embed_fn = _ServiceEmbeddingFunction(purpose=purpose)

        try:
            collection = client.get_or_create_collection(
                name=collection_name,
                embedding_function=embed_fn,
                metadata={
                    "description": f"Nexus {collection_key} embeddings",
                    "hnsw:space": "cosine",
                },
            )
            self._collections[collection_key] = collection
            return collection
        except Exception as exc:
            logger.error("Failed to get/create collection %s: %s", collection_name, exc)
            raise

    # ──── Core operations ─────────────────────────────────────────────────

    def add(
        self,
        entry_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        collection: str = "knowledge",
    ) -> None:
        """Add or update a single entry in the vector store.

        Args:
            entry_id: Unique identifier for the entry.
            text: Text content to embed and store.
            metadata: Optional metadata dict (category, tags, etc.).
            collection: Collection key (knowledge, qa, code, news, etc.).
        """
        if not text or not text.strip():
            logger.debug("Skipping empty text for entry %s", entry_id)
            return

        coll = self._get_collection(collection)
        meta = _sanitize_metadata(metadata or {})
        meta["_added_at"] = time.time()

        try:
            coll.upsert(
                ids=[entry_id],
                documents=[text[:10000]],  # ChromaDB has a limit
                metadatas=[meta],
            )
            self._adds += 1
            logger.debug("Vector store: added %s to %s", entry_id, collection)
        except Exception as exc:
            logger.warning("Vector store add failed for %s: %s", entry_id, exc)
            raise

    def add_batch(
        self,
        entries: List[Dict[str, Any]],
        collection: str = "knowledge",
    ) -> int:
        """Add multiple entries in one batch.

        Args:
            entries: List of dicts with keys: id, text, metadata (optional).
            collection: Collection key.

        Returns:
            Number of entries successfully added.
        """
        if not entries:
            return 0

        coll = self._get_collection(collection)
        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        now = time.time()

        for entry in entries:
            eid = entry.get("id", "")
            text = entry.get("text", "")
            if not eid or not text or not text.strip():
                continue
            ids.append(eid)
            documents.append(text[:10000])
            meta = _sanitize_metadata(entry.get("metadata", {}))
            meta["_added_at"] = now
            metadatas.append(meta)

        if not ids:
            return 0

        # Process in chunks (ChromaDB recommends <= 5000 per batch)
        chunk_size = 500
        added = 0
        for i in range(0, len(ids), chunk_size):
            chunk_ids = ids[i:i + chunk_size]
            chunk_docs = documents[i:i + chunk_size]
            chunk_meta = metadatas[i:i + chunk_size]
            try:
                coll.upsert(
                    ids=chunk_ids,
                    documents=chunk_docs,
                    metadatas=chunk_meta,
                )
                added += len(chunk_ids)
            except Exception as exc:
                logger.warning(
                    "Batch add failed for chunk %d-%d: %s",
                    i, i + len(chunk_ids), exc,
                )

        self._adds += added
        logger.info("Vector store: batch added %d/%d to %s", added, len(entries), collection)
        return added

    def search(
        self,
        query: str,
        top_k: int = 5,
        collection: str = "knowledge",
        filters: Optional[Dict[str, Any]] = None,
        min_score: float = 0.0,
    ) -> List[VectorSearchResult]:
        """Semantic search across a collection.

        Args:
            query: Search query text.
            top_k: Maximum results to return.
            collection: Collection to search.
            filters: Optional ChromaDB where-clause filters.
            min_score: Minimum similarity score (0.0-1.0).

        Returns:
            List of VectorSearchResult sorted by descending similarity.
        """
        if not query or not query.strip():
            return []

        coll = self._get_collection(collection)
        self._searches += 1

        try:
            # ChromaDB query — uses the collection's embedding function
            # We override the query embedding to use RETRIEVAL_QUERY task type
            from engine.nexus.embedding_service import get_embedding_service
            svc = get_embedding_service()
            query_vec = svc.embed(query, purpose="query")

            kwargs: Dict[str, Any] = {
                "query_embeddings": [query_vec],
                "n_results": min(top_k, coll.count()) if coll.count() > 0 else top_k,
                "include": ["documents", "metadatas", "distances"],
            }
            if filters:
                kwargs["where"] = filters

            results = coll.query(**kwargs)

            if not results or not results.get("ids") or not results["ids"][0]:
                return []

            search_results: List[VectorSearchResult] = []
            for i, eid in enumerate(results["ids"][0]):
                # ChromaDB returns distances, convert to similarity
                # For cosine space: similarity = 1 - distance
                distance = results["distances"][0][i] if results.get("distances") else 0.0
                score = max(0.0, 1.0 - distance)

                if score < min_score:
                    continue

                doc = results["documents"][0][i] if results.get("documents") else ""
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}

                search_results.append(VectorSearchResult(
                    entry_id=eid,
                    text=doc,
                    score=round(score, 4),
                    metadata=meta,
                    collection=collection,
                ))

            return search_results

        except Exception as exc:
            logger.warning("Vector search failed in %s: %s", collection, exc)
            return []

    def search_multi(
        self,
        query: str,
        collections: Optional[List[str]] = None,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[VectorSearchResult]:
        """Search across multiple collections and merge results.

        Args:
            query: Search query text.
            collections: List of collection keys to search. None = all.
            top_k: Total top results across all collections.
            min_score: Minimum similarity score.

        Returns:
            Merged and sorted results from all searched collections.
        """
        if collections is None:
            collections = list(COLLECTION_MAP.keys())

        all_results: List[VectorSearchResult] = []
        for coll_key in collections:
            try:
                results = self.search(
                    query, top_k=top_k, collection=coll_key, min_score=min_score
                )
                all_results.extend(results)
            except Exception as exc:
                logger.debug("Search in %s failed: %s", coll_key, exc)

        # Sort by score descending and truncate
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[:top_k]

    # ──── Management operations ───────────────────────────────────────────

    def remove(self, entry_id: str, collection: str = "knowledge") -> bool:
        """Remove an entry from the vector store.

        Returns:
            True if removal succeeded, False otherwise.
        """
        try:
            coll = self._get_collection(collection)
            coll.delete(ids=[entry_id])
            self._removes += 1
            return True
        except Exception as exc:
            logger.debug("Remove %s from %s failed: %s", entry_id, collection, exc)
            return False

    def has(self, entry_id: str, collection: str = "knowledge") -> bool:
        """Check if an entry exists in a collection."""
        try:
            coll = self._get_collection(collection)
            result = coll.get(ids=[entry_id])
            return bool(result and result.get("ids"))
        except Exception:
            return False

    def count(self, collection: str = "knowledge") -> int:
        """Count entries in a collection."""
        try:
            coll = self._get_collection(collection)
            return coll.count()
        except Exception:
            return 0

    def stats(self) -> Dict[str, Any]:
        """Return vector store statistics."""
        collection_stats: Dict[str, int] = {}
        for key in COLLECTION_MAP:
            try:
                if key in self._collections:
                    collection_stats[key] = self._collections[key].count()
            except Exception:
                pass

        return {
            "persist_dir": str(self._persist_dir),
            "total_adds": self._adds,
            "total_searches": self._searches,
            "total_removes": self._removes,
            "collections": collection_stats,
            "total_vectors": sum(collection_stats.values()),
        }

    def list_collections(self) -> List[str]:
        """List available collection keys."""
        return list(COLLECTION_MAP.keys())

    def reset_collection(self, collection: str = "knowledge") -> None:
        """Delete and recreate a collection (loses all data)."""
        client = self._get_client()
        collection_name = COLLECTION_MAP.get(collection, f"nexus_{collection}")
        try:
            client.delete_collection(name=collection_name)
            if collection in self._collections:
                del self._collections[collection]
            logger.info("Reset collection: %s", collection_name)
        except Exception as exc:
            logger.warning("Reset collection %s failed: %s", collection_name, exc)


# ──── Helpers ────────────────────────────────────────────────────────────────

def _sanitize_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure metadata values are ChromaDB-compatible (str, int, float, bool)."""
    clean: Dict[str, Any] = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)):
            clean[k] = v
        elif isinstance(v, (list, tuple)):
            clean[k] = ",".join(str(x) for x in v)
        elif v is not None:
            clean[k] = str(v)
    return clean


# ──── Singleton ──────────────────────────────────────────────────────────────

_store_instance: Optional[NexusVectorStore] = None
_store_lock = threading.Lock()


def get_vector_store(**kwargs: Any) -> NexusVectorStore:
    """Get or create the singleton NexusVectorStore."""
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = NexusVectorStore(**kwargs)
    return _store_instance


def reset_vector_store() -> None:
    """Reset the singleton (for testing)."""
    global _store_instance
    with _store_lock:
        _store_instance = None
