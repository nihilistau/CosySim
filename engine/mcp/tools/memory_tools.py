"""
Pure business-logic helpers for memory MCP tools.

These functions are called by the thin ``@mcp.tool()`` wrappers in
``cosysim_server.py``.  They receive service dependencies (``rag``) as
explicit parameters so they stay free of module-level globals.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def search_memory(
    query: str,
    rag: Any,
    character_id: Optional[str] = None,
    top_k: int = 5,
) -> str:
    """Search character memories using RAG vector search.

    Args:
        query:        Free-text search query.
        rag:          A ``RAGManager`` instance (or *None* if unavailable).
        character_id: Optional character filter.
        top_k:        Maximum results to return.

    Returns:
        Formatted string of matching memories, or an error/status message.
    """
    if rag is None:
        return "RAG system unavailable."
    try:
        results = rag.search(query, character_id=character_id, top_k=top_k)
        if not results:
            return "No relevant memories found."
        entries: list[str] = []
        for i, r in enumerate(results, 1):
            text = r.get("text", r.get("document", str(r)))
            score = r.get("score", r.get("distance", "?"))
            entries.append(f"{i}. [score={score}] {text}")
        return "\n".join(entries)
    except Exception as e:
        return f"Memory search failed: {e}"


def store_memory(
    text: str,
    character_id: str,
    rag: Any,
    metadata: Optional[str] = None,
) -> str:
    """Store a new memory for a character in the RAG system.

    Args:
        text:         The text content to store.
        character_id: Character this memory belongs to.
        rag:          A ``RAGManager`` instance (or *None* if unavailable).
        metadata:     Optional JSON string of extra metadata.

    Returns:
        Confirmation or error message.
    """
    if rag is None:
        return "RAG system unavailable."
    try:
        meta = json.loads(metadata) if metadata else {}
        rag.add(text, character_id=character_id, metadata=meta)
        return f"Memory stored for character {character_id}."
    except Exception as e:
        return f"Failed to store memory: {e}"
