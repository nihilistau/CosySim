"""Auto-embedding hooks for the Nexus knowledge pipeline.

Wires automatic vector embedding into every Nexus write path so the
ChromaDB vector store fills organically with every knowledge entry,
Q&A pair, and code snippet added to Nexus.

Usage (called automatically by NexusClient and QueryRouter)::

    from engine.nexus.embedding_hooks import auto_embed_entry, auto_embed_qa

    # After NexusClient.add_entry() succeeds:
    auto_embed_entry(entry_id, text, content_type, category, tags)

    # After NexusClient.add_qa() succeeds:
    auto_embed_qa(qa_id, question, answer, category)

    # Scheduler batch re-index:
    from engine.nexus.embedding_hooks import batch_embed_nexus_entries
    result = batch_embed_nexus_entries(limit=500)
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# v1.49.4 [2026-03-22] — File-based retry queue for failed embeddings
_RETRY_QUEUE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "embed_retry_queue.jsonl"

# ──── Content-Type → Collection Mapping ────

_CONTENT_TYPE_TO_COLLECTION = {
    "note": "knowledge",
    "document": "document",
    "code": "code",
    "prompt": "prompt",
    "memory": "memory",
    "research": "research",
    "transcript": "knowledge",
    "history": "document",
    "plan": "document",
    "news": "news",
}

_DEFAULT_COLLECTION = "knowledge"


def content_type_to_collection(content_type: str) -> str:
    """Map a Nexus content_type to a vector store collection name.

    Args:
        content_type: Nexus content type (note, code, prompt, etc.).

    Returns:
        Vector store collection name.
    """
    return _CONTENT_TYPE_TO_COLLECTION.get(content_type, _DEFAULT_COLLECTION)


# ──── Auto-Embed Functions ────

def auto_embed_entry(
    entry_id: str,
    text: str,
    content_type: str = "note",
    category: str = "",
    tags: Optional[List[str]] = None,
) -> bool:
    """Embed a Nexus entry into the vector store after storage.

    Called automatically by NexusClient.add_entry() after a successful
    server-side store.  Failures are logged but never raised — embedding
    is best-effort and must not break the primary write path.

    Args:
        entry_id: Nexus entry ID returned by the server.
        text: Full text content of the entry.
        content_type: Nexus content type (note, code, prompt, etc.).
        category: Entry category (architecture, api, debugging, etc.).
        tags: Optional tag list.

    Returns:
        True if embedding succeeded, False otherwise.
    """
    if not entry_id or not text:
        return False

    collection = content_type_to_collection(content_type)
    try:
        from engine.nexus.vector_store import get_vector_store

        store = get_vector_store()

        metadata: Dict[str, Any] = {}
        if category:
            metadata["category"] = category
        if content_type:
            metadata["content_type"] = content_type
        if tags:
            metadata["tags"] = ",".join(tags)

        store.add(
            entry_id=entry_id,
            text=text,
            metadata=metadata,
            collection=collection,
        )
        logger.debug(
            "Auto-embedded entry %s into '%s' collection", entry_id, collection
        )
        return True
    except Exception as exc:
        # v1.49.4 [2026-03-22] — Upgraded to ERROR + retry queue for data loss visibility
        logger.error(
            "Auto-embed FAILED for entry %s (collection=%s): %s — entry stored but NOT searchable",
            entry_id, collection, exc,
        )
        _enqueue_retry("entry", entry_id, text, {"content_type": content_type,
                                                   "category": category,
                                                   "tags": tags or []})
        return False


def auto_embed_qa(
    qa_id: str,
    question: str,
    answer: str,
    category: str = "",
) -> bool:
    """Embed a Q&A pair into the vector store after storage.

    The combined question + answer text is embedded into the ``qa``
    collection so semantic search can find relevant Q&A pairs.

    Args:
        qa_id: Nexus Q&A pair ID.
        question: The question text.
        answer: The answer text.
        category: Optional category.

    Returns:
        True if embedding succeeded, False otherwise.
    """
    if not qa_id or not question:
        return False

    try:
        from engine.nexus.vector_store import get_vector_store

        store = get_vector_store()

        combined = f"Q: {question}\nA: {answer}" if answer else question

        metadata: Dict[str, Any] = {"source": "qa"}
        if category:
            metadata["category"] = category

        store.add(
            entry_id=qa_id,
            text=combined,
            metadata=metadata,
            collection="qa",
        )
        logger.debug("Auto-embedded Q&A %s into 'qa' collection", qa_id)
        return True
    except Exception as exc:
        logger.warning(
            "Auto-embed failed for Q&A %s: %s", qa_id, exc, exc_info=True
        )
        return False


# ──── Retry Queue ────
# v1.49.4 [2026-03-22] — File-based retry queue for failed embeddings

def _enqueue_retry(embed_type: str, entry_id: str, text: str, metadata: Dict[str, Any]) -> None:
    """Append a failed embedding to the retry queue file."""
    try:
        _RETRY_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "type": embed_type, "id": entry_id,
            "text": text[:5000], "metadata": metadata,
            "failed_at": time.time(),
        }
        with open(_RETRY_QUEUE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.error("Failed to write to embedding retry queue: %s", exc)


def process_retry_queue(limit: int = 100) -> Dict[str, int]:
    """Process the embedding retry queue — re-attempt failed embeddings."""
    result = {"succeeded": 0, "failed": 0, "total": 0}
    if not _RETRY_QUEUE_PATH.exists():
        return result
    try:
        lines = _RETRY_QUEUE_PATH.read_text(encoding="utf-8").strip().split("\n")
    except Exception:
        return result
    remaining: List[str] = []
    processed = 0
    for line in lines:
        if not line.strip():
            continue
        if processed >= limit:
            remaining.append(line)
            continue
        try:
            record = json.loads(line)
            result["total"] += 1
            processed += 1
            from engine.nexus.vector_store import get_vector_store
            store = get_vector_store()
            collection = content_type_to_collection(
                record.get("metadata", {}).get("content_type", "note")
            ) if record["type"] == "entry" else "qa"
            store.add(entry_id=record["id"], text=record["text"],
                      metadata=record.get("metadata", {}), collection=collection)
            result["succeeded"] += 1
        except Exception:
            result["failed"] += 1
            remaining.append(line)
    try:
        if remaining:
            _RETRY_QUEUE_PATH.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        else:
            _RETRY_QUEUE_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    return result


# ──── Batch Embedding ────

def batch_embed_nexus_entries(limit: int = 500) -> Dict[str, Any]:
    """Batch-embed Nexus entries that are missing from the vector store.

    Queries the Nexus server for recent entries, checks which ones are
    already in the vector store, and embeds the missing ones.  Designed
    to be called by the scheduler daemon on a recurring schedule.

    Args:
        limit: Maximum number of entries to process per run.

    Returns:
        Dict with ``embedded``, ``skipped``, ``errors``, and ``total`` counts.
    """
    result: Dict[str, Any] = {
        "embedded": 0,
        "skipped": 0,
        "errors": 0,
        "total": 0,
    }

    try:
        from engine.nexus.client import get_nexus_client
        from engine.nexus.vector_store import get_vector_store

        client = get_nexus_client()
        store = get_vector_store()

        entries = client.search("", limit=limit) or []
        result["total"] = len(entries)

        batch_by_collection: Dict[str, List[Dict[str, Any]]] = {}

        for entry in entries:
            entry_id = entry.get("id", "")
            if not entry_id:
                result["skipped"] += 1
                continue

            content_type = entry.get("content_type", "note")
            collection = content_type_to_collection(content_type)

            if store.has(entry_id, collection=collection):
                result["skipped"] += 1
                continue

            text = entry.get("content", "") or entry.get("title", "")
            if not text:
                result["skipped"] += 1
                continue

            metadata: Dict[str, Any] = {}
            if entry.get("category"):
                metadata["category"] = entry["category"]
            if content_type:
                metadata["content_type"] = content_type
            tags = entry.get("tags")
            if tags:
                if isinstance(tags, list):
                    metadata["tags"] = ",".join(tags)
                else:
                    metadata["tags"] = str(tags)

            batch_by_collection.setdefault(collection, []).append(
                {"id": entry_id, "text": text, "metadata": metadata}
            )

        for collection, batch in batch_by_collection.items():
            try:
                added = store.add_batch(batch, collection=collection)
                result["embedded"] += added
                logger.info(
                    "Batch-embedded %d entries into '%s'", added, collection
                )
            except Exception as exc:
                result["errors"] += len(batch)
                logger.warning(
                    "Batch embed failed for '%s': %s", collection, exc,
                    exc_info=True,
                )

    except Exception as exc:
        logger.error("batch_embed_nexus_entries failed: %s", exc, exc_info=True)
        result["error"] = str(exc)

    return result


def batch_embed_qa_entries(limit: int = 500) -> Dict[str, Any]:
    """Batch-embed Nexus Q&A pairs that are missing from the vector store.

    Args:
        limit: Maximum number of Q&A pairs to process.

    Returns:
        Dict with ``embedded``, ``skipped``, ``errors``, and ``total`` counts.
    """
    result: Dict[str, Any] = {
        "embedded": 0,
        "skipped": 0,
        "errors": 0,
        "total": 0,
    }

    try:
        from engine.nexus.client import get_nexus_client
        from engine.nexus.vector_store import get_vector_store

        client = get_nexus_client()
        store = get_vector_store()

        qa_pairs = client.list_qa(limit=limit) or []
        result["total"] = len(qa_pairs)

        batch: List[Dict[str, Any]] = []

        for qa in qa_pairs:
            qa_id = qa.get("id", "")
            if not qa_id:
                result["skipped"] += 1
                continue

            if store.has(qa_id, collection="qa"):
                result["skipped"] += 1
                continue

            question = qa.get("question", "")
            answer = qa.get("answer", "")
            if not question:
                result["skipped"] += 1
                continue

            combined = f"Q: {question}\nA: {answer}" if answer else question
            metadata: Dict[str, Any] = {"source": "qa"}
            if qa.get("category"):
                metadata["category"] = qa["category"]

            batch.append({"id": qa_id, "text": combined, "metadata": metadata})

        if batch:
            try:
                added = store.add_batch(batch, collection="qa")
                result["embedded"] += added
                logger.info("Batch-embedded %d Q&A pairs", added)
            except Exception as exc:
                result["errors"] += len(batch)
                logger.warning(
                    "Batch embed Q&A failed: %s", exc, exc_info=True
                )

    except Exception as exc:
        logger.error("batch_embed_qa_entries failed: %s", exc, exc_info=True)
        result["error"] = str(exc)

    return result
