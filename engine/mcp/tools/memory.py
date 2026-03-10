"""MCP tool domain: memory.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── MEMORY TOOLS ───────────────────────────────────────────────────────


@mcp_tool
def search_memory(query: str, character_id: Optional[str] = None, top_k: int = 5) -> str:
    """
    Search character memories using RAG vector search.
    Returns the most relevant stored memories for the given query.
    Use this to recall past conversations, facts, or context.
    """
    try:
        from engine.mcp.tools.memory_tools import search_memory as _impl
        return _impl(query, _get_rag(), character_id=character_id, top_k=top_k)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def store_memory(text: str, character_id: str, metadata: Optional[str] = None) -> str:
    """
    Store a new memory for a character in the RAG system.
    Use this to save important facts, conversation summaries, or observations.
    """
    try:
        from engine.mcp.tools.memory_tools import store_memory as _impl
        return _impl(text, character_id, _get_rag(), metadata=metadata)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def memory_recall(
    character_id: str,
    query: str,
    context_limit: int = 5,
    scene_id: str = "",
) -> str:
    """
    **MEMORY SKILL** — Retrieve the character's most relevant memories for a query.

    This is the memory skill entry point.  It layers:
    1. RAG search of long-term memory (ChromaDB)
    2. Recent scene narrative (short-term)
    3. A formatted "You remember:" hook ready for system prompt injection

    Use this at the start of every response to ground the character in their
    history and ensure continuity.

    Args:
        character_id:  The character doing the remembering
        query:         What to search for — use the current topic/context
        context_limit: Max memory snippets to return
        scene_id:      Current scene (pulls recent narrative)
    """
    try:
        results: Dict[str, Any] = {}

        # Long-term memory (RAG)
        try:
            rag = _get_rag()
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
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()
            entries = ssm.get_narrative_entries(scene_id or "penthouse", limit=4)
            results["recent"] = [e.get("event", "") for e in entries if e.get("event")]
        except Exception:
            results["recent"] = []

        # Build the memory hook
        try:
            from engine.mcp.dialog_system import get_dialog_system
            name = character_id
            try:
                from engine.mcp.character_registry import get_character_registry
                rec = get_character_registry().get_record(character_id)
                if rec:
                    name = rec.profile.name
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)
            all_memories = results["long_term"] + results["recent"]
            hook = get_dialog_system().build_memory_hook(all_memories, name)
            results["memory_hook"] = hook
        except Exception:
            results["memory_hook"] = ""

        results["character_id"] = character_id
        results["query"]        = query
        return json.dumps(results, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
