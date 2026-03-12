"""MCP skills for the embedding and vector search system.

Exposes Gemini Embedding 2 vector operations to agents so they can:
  - Embed text into vectors for semantic comparison
  - Search the Nexus vector store semantically
  - Add content to the vector store for future retrieval
  - Check embedding service health and statistics
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from engine.skills.registry import skill

logger = logging.getLogger(__name__)


@skill(
    pack="nexus",
    description="Semantic search across Nexus knowledge using Gemini Embedding 2 vectors",
    category="SYSTEM",
    cooldown=1.0,
    cost=0.5,
    tags=["nexus", "search", "embedding", "semantic", "vector"],
)
def nexus_semantic_search(
    query: str,
    top_k: int = 5,
    collections: str = "knowledge,qa,code,news",
    min_score: float = 0.5,
) -> str:
    """Search Nexus content by semantic similarity using Gemini Embedding 2.

    Unlike FTS keyword search, this finds conceptually similar content even
    when exact keywords don't match. Uses MRL (Matryoshka Representation
    Learning) for efficient variable-dimension embeddings.

    Args:
        query: Natural language search query.
        top_k: Maximum number of results (default 5).
        collections: Comma-separated collection names to search.
        min_score: Minimum similarity score threshold (0.0-1.0).

    Returns:
        Formatted search results with scores and content previews.
    """
    try:
        from engine.nexus.vector_store import get_vector_store

        store = get_vector_store()
        coll_list = [c.strip() for c in collections.split(",") if c.strip()]

        results = store.search_multi(
            query=query,
            collections=coll_list,
            top_k=top_k,
            min_score=min_score,
        )

        if not results:
            return f"No semantic matches found for: {query}"

        lines = [f"Found {len(results)} semantic matches:\n"]
        for i, r in enumerate(results, 1):
            preview = r.text[:200].replace("\n", " ")
            lines.append(
                f"{i}. [{r.collection}] {r.entry_id} (score: {r.score:.3f})\n"
                f"   {preview}..."
            )
        return "\n".join(lines)

    except Exception as exc:
        logger.warning("nexus_semantic_search failed: %s", exc)
        return f"Semantic search failed: {exc}"


@skill(
    pack="nexus",
    description="Add content to the Nexus vector store for semantic retrieval",
    category="SYSTEM",
    cooldown=1.0,
    cost=1.0,
    tags=["nexus", "embedding", "store", "vector"],
)
def nexus_vector_add(
    entry_id: str,
    text: str,
    collection: str = "knowledge",
    category: str = "",
) -> str:
    """Add or update an entry in the Nexus vector store.

    Content is embedded using Gemini Embedding 2 and stored in ChromaDB
    for future semantic search retrieval.

    Args:
        entry_id: Unique identifier for the entry.
        text: Text content to embed and store.
        collection: Target collection (knowledge, qa, code, news, etc.).
        category: Optional category tag for metadata filtering.

    Returns:
        Confirmation message.
    """
    try:
        from engine.nexus.vector_store import get_vector_store

        store = get_vector_store()
        metadata: Dict[str, Any] = {}
        if category:
            metadata["category"] = category

        store.add(entry_id, text, metadata=metadata, collection=collection)
        return f"Added '{entry_id}' to vector store ({collection})"

    except Exception as exc:
        logger.warning("nexus_vector_add failed: %s", exc)
        return f"Vector store add failed: {exc}"


@skill(
    pack="nexus",
    description="Compute semantic similarity between two texts using Gemini Embedding 2",
    category="SYSTEM",
    cooldown=1.0,
    cost=1.0,
    tags=["nexus", "embedding", "similarity"],
)
def nexus_text_similarity(text_a: str, text_b: str) -> str:
    """Compute cosine similarity between two texts using Gemini Embedding 2.

    Useful for:
      - Deduplication: check if two entries are semantically equivalent
      - Relevance: measure how related two concepts are
      - Quality: compare model output against reference text

    Args:
        text_a: First text.
        text_b: Second text.

    Returns:
        Similarity score (0.0 to 1.0) with interpretation.
    """
    try:
        from engine.nexus.embedding_service import get_embedding_service

        svc = get_embedding_service()
        vec_a = svc.embed(text_a, purpose="similarity")
        vec_b = svc.embed(text_b, purpose="similarity")
        score = svc.similarity(vec_a, vec_b)

        if score > 0.9:
            interpretation = "Nearly identical"
        elif score > 0.75:
            interpretation = "Highly similar"
        elif score > 0.5:
            interpretation = "Moderately related"
        elif score > 0.3:
            interpretation = "Loosely related"
        else:
            interpretation = "Unrelated"

        return f"Similarity: {score:.4f} — {interpretation}"

    except Exception as exc:
        logger.warning("nexus_text_similarity failed: %s", exc)
        return f"Similarity computation failed: {exc}"


@skill(
    pack="nexus",
    description="Get embedding service and vector store health statistics",
    category="SYSTEM",
    cooldown=5.0,
    cost=0.1,
    tags=["nexus", "embedding", "stats", "health"],
)
def nexus_embedding_stats() -> str:
    """Get statistics for the embedding service and vector store.

    Returns:
        Formatted stats including model, dimensions, cache hit rate,
        vector counts per collection, and provider usage.
    """
    lines: List[str] = ["=== Embedding System Stats ===\n"]

    try:
        from engine.nexus.embedding_service import get_embedding_service
        svc = get_embedding_service()
        stats = svc.stats()
        lines.append(f"Model: {stats['model']}")
        lines.append(f"Dimensions: {stats['dimensions']}")
        lines.append(f"Provider: {stats['provider']}")
        lines.append(f"Total embeds: {stats['total_embeds']}")
        lines.append(f"Total texts: {stats['total_texts']}")
        lines.append(f"Avg latency: {stats['avg_latency_ms']}ms")
        lines.append(f"Errors: {stats['errors']}")
        cache = stats.get("cache", {})
        lines.append(
            f"Cache: {cache.get('size', 0)}/{cache.get('max_size', 0)} "
            f"(hit rate: {cache.get('hit_rate', 0):.1%})"
        )
    except Exception as exc:
        lines.append(f"Embedding service: unavailable ({exc})")

    lines.append("")

    try:
        from engine.nexus.vector_store import get_vector_store
        store = get_vector_store()
        vs_stats = store.stats()
        lines.append("=== Vector Store Stats ===\n")
        lines.append(f"Total vectors: {vs_stats['total_vectors']}")
        lines.append(f"Total adds: {vs_stats['total_adds']}")
        lines.append(f"Total searches: {vs_stats['total_searches']}")
        for coll, count in vs_stats.get("collections", {}).items():
            lines.append(f"  {coll}: {count} vectors")
    except Exception as exc:
        lines.append(f"Vector store: unavailable ({exc})")

    return "\n".join(lines)
