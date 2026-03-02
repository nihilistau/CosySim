"""
Pure business-logic helpers for memory MCP tools.

These functions are called by the thin ``@mcp.tool()`` wrappers in
``cosysim_server.py``.  They receive service dependencies (``rag``) as
explicit parameters so they stay free of module-level globals.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from engine.mcp.decorators import mcp_tool

logger = logging.getLogger(__name__)


class MemorySearchResponse(BaseModel):
    status: str
    results: List[str] = Field(default_factory=list)


class MemoryStoreResponse(BaseModel):
    status: str


class MemoryRecallResponse(BaseModel):
    long_term: List[str]
    recent: List[str]
    memory_hook: str
    character_id: str
    query: str


class TimeEchoResponse(BaseModel):
    ok: bool
    character_id: str
    echo_text: str
    applied_effects: Dict[str, Any]


@mcp_tool
def search_memory(
    query: str,
    rag: Any,
    character_id: Optional[str] = None,
    top_k: int = 5,
) -> MemorySearchResponse:
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
        return MemorySearchResponse(status="RAG system unavailable.")

    results = rag.search(query, character_id=character_id, top_k=top_k)
    if not results:
        return MemorySearchResponse(status="No relevant memories found.")

    entries: list[str] = []
    for i, r in enumerate(results, 1):
        text = r.get("text", r.get("document", str(r)))
        score = r.get("score", r.get("distance", "?"))
        entries.append(f"{i}. [score={score}] {text}")

    return MemorySearchResponse(status="Memories found.", results=entries)


@mcp_tool
def store_memory(
    text: str,
    character_id: str,
    rag: Any,
    metadata: Optional[str] = None,
) -> MemoryStoreResponse:
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
        return MemoryStoreResponse(status="RAG system unavailable.")

    meta = json.loads(metadata) if metadata else {}
    rag.add(text, character_id=character_id, metadata=meta)
    return MemoryStoreResponse(status=f"Memory stored for character {character_id}.")


@mcp_tool
def memory_recall(
    character_id: str,
    query: str,
    rag: Any,
    ssm: Any,
    dialog_system: Any,
    character_registry: Any,
    context_limit: int = 5,
    scene_id: str = "",
) -> MemoryRecallResponse:
    """Retrieve the character's most relevant memories for a query."""
    results: Dict[str, Any] = {}

    # Long-term memory (RAG)
    try:
        if rag:
            raw = rag.search(query, character_id=character_id, top_k=context_limit)
            if isinstance(raw, list):
                results["long_term"] = [
                    r.get("text", r) if isinstance(r, dict) else str(r)
                    for r in raw[:context_limit]
                ]
            else:
                results["long_term"] = []
        else:
            results["long_term"] = []
    except Exception:
        results["long_term"] = []

    # Short-term narrative
    try:
        entries = ssm.get_narrative_entries(scene_id or "bedroom", limit=4)
        results["recent"] = [e.get("event", "") for e in entries if e.get("event")]
    except Exception:
        results["recent"] = []

    # Build the memory hook
    try:
        name = character_id
        try:
            rec = character_registry.get_record(character_id)
            if rec:
                name = rec.profile.name
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        all_memories = results["long_term"] + results["recent"]
        hook = dialog_system.build_memory_hook(all_memories, name)
        results["memory_hook"] = hook
    except Exception:
        results["memory_hook"] = ""

    return MemoryRecallResponse(
        long_term=results["long_term"],
        recent=results["recent"],
        memory_hook=results["memory_hook"],
        character_id=character_id,
        query=query,
    )


@mcp_tool
def time_echo(
    character_id: str,
    echo_query: str,
    rag: Any,
    dialog_system: Any,
    ssm: Any,
    fw: Any,
    emotional_tone: str = "nostalgic",
    scene_id: str = "",
) -> TimeEchoResponse:
    """Pull a specific memory forward into this moment with full emotional resonance."""
    memory_fragment = None
    try:
        if rag:
            results = rag.search(echo_query, n_results=3, character_id=character_id)
            if results:
                best = results[0]
                memory_fragment = (best.get("content") or str(best))[:200]
    except Exception:
        logger.debug("Suppressed exception", exc_info=True)

    # Build the echoed fragment
    if memory_fragment:
        echo_text = (
            f"[{emotional_tone.upper()} ECHO — drawn from memory] "
            f'"{memory_fragment}" — this surfaces now, vivid and unbidden.'
        )
    else:
        echo_text = (
            f"[{emotional_tone.upper()} ECHO — a felt memory, no exact words] "
            f"Something about '{echo_query}' rises up — not a thought, but a feeling."
            f" The specific gravity of something real."
        )

    # Determine target scene
    target_scene = scene_id
    if not target_scene:
        try:
            char = fw.get_character(character_id)
            target_scene = char.current_scene or "phone"
        except Exception:
            target_scene = "phone"

    dialog_system.set_directive(
        character_id=character_id,
        scene_id=target_scene,
        directive_type="must_include",
        value=echo_text,
        turns=1,
        issued_by="time_echo_skill",
    )

    # Stat effect based on emotional tone
    tone_effects = {
        "nostalgic": {"happiness": 8, "affection": 12, "arousal": 0},
        "warm": {"happiness": 12, "affection": 10, "arousal": 3},
        "aching": {"happiness": -5, "affection": 15, "arousal": 5},
        "amused": {"happiness": 15, "affection": 8, "arousal": 2},
        "bittersweet": {"happiness": 3, "affection": 12, "arousal": 4},
        "excited": {"happiness": 10, "affection": 8, "arousal": 15},
    }
    effects = tone_effects.get(emotional_tone, {"happiness": 5, "affection": 8})
    ssm.update_stats(character_id, **effects)

    ssm.add_narrative(
        target_scene,
        f"[{character_id} experiences a {emotional_tone} Time Echo.]",
        entry_type="system",
        character_id=character_id,
    )

    return TimeEchoResponse(
        ok=True,
        character_id=character_id,
        echo_text=echo_text,
        applied_effects=effects,
    )
