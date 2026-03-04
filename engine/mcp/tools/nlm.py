"""MCP tool domain: nlm.

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

# ──── NLM TOOLS ──────────────────────────────────────────────────────────


@mcp_tool
def nlm_notebook_list() -> str:
    """List all managed NLM notebooks with health: source counts, ages,
    last seeded/asked dates, and overall slot health."""
    try:
        from engine.nexus.nlm_notebook_manager import get_notebook_manager
        return json.dumps(get_notebook_manager().health(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def nlm_notebook_seed(slot_name: str = "cosysim-architecture", source_type: str = "docs") -> str:
    """Seed an NLM notebook from project files. source_type: 'docs' for
    documentation, 'code' for engine source files."""
    try:
        from engine.nexus.nlm_notebook_manager import get_notebook_manager
        mgr = get_notebook_manager()
        if source_type == "code":
            return json.dumps(mgr.seed_from_code(slot_name), indent=2, default=str)
        return json.dumps(mgr.seed_from_docs(slot_name), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def nlm_notebook_rotate(slot_name: str) -> str:
    """Rotate (delete & recreate) an NLM notebook to refresh stale content."""
    try:
        from engine.nexus.nlm_notebook_manager import get_notebook_manager
        return json.dumps(get_notebook_manager().rotate_notebook(slot_name), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
async def notebooklm_node_ask(notebook_id: str, question: str, session_id: str = "") -> str:
    """Ask a question to a NotebookLM notebook via the Node MCP bridge
    (Patchright browser automation). Always reliable — handles auth automatically.

    Pass ``session_id`` from a prior response to continue a multi-turn conversation.
    Returns JSON with ``answer``, ``sources``, and ``session_id``.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().ask(
            notebook_id, question,
            session_id=session_id or None,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def notebooklm_node_batch_ask(notebook_id: str, questions: str) -> str:
    """Ask multiple questions against a NotebookLM notebook in one batch,
    using session continuity so each question has full prior context.

    ``questions`` must be a JSON array of strings, e.g. ``["Q1?", "Q2?"]``.
    Returns a JSON array of ``{answer, sources, session_id}`` dicts.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        q_list = json.loads(questions) if isinstance(questions, str) else questions
        if not isinstance(q_list, list):
            return json.dumps({"error": "questions must be a JSON array"})
        results = get_nlm_hybrid().ask_batch(notebook_id, q_list)
        return json.dumps(results)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def notebooklm_node_add_source(
    notebook_id: str,
    source_type: str,
    source_value: str,
    title: str = "",
) -> str:
    """Add a source to a NotebookLM notebook via the Node bridge.

    ``source_type``: ``url``, ``text``, ``file``, or ``youtube``.
    Returns JSON with ``status`` and ``source_id``.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        hybrid = get_nlm_hybrid()
        if source_type == "url" or source_type == "youtube":
            result = hybrid.add_url_source(notebook_id, source_value)
        else:
            result = hybrid.add_text_source(notebook_id, source_value, title=title)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def notebooklm_node_create_notebook(
    name: str,
    sources: str = "[]",
    description: str = "",
    topics: str = "",
) -> str:
    """Create a new NotebookLM notebook via the Node bridge.

    ``sources`` is a JSON array of ``{type, value}`` dicts.
    Returns JSON with notebook ``id`` and ``url``.
    """
    try:
        from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
        src_list = json.loads(sources) if isinstance(sources, str) else sources
        result = get_nlm_node_bridge().create_notebook(
            name=name,
            sources=src_list,
            description=description,
            topics=[t.strip() for t in topics.split(",") if t.strip()],
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def notebooklm_node_list_notebooks() -> str:
    """List all NotebookLM notebooks in the authenticated account.
    Returns JSON array of ``{id, title, source_count, url}`` objects.
    """
    try:
        from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
        result = get_nlm_node_bridge().list_notebooks()
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def notebooklm_node_generate_audio(notebook_id: str) -> str:
    """Generate a podcast-style audio overview of a NotebookLM notebook
    via the Node bridge. Returns JSON with ``status`` and ``progress``.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().generate_audio(notebook_id)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def notebooklm_node_generate_video(notebook_id: str, style: str = "cinematic") -> str:
    """Generate a video overview of a NotebookLM notebook via the Node bridge.
    Supported styles: cinematic, documentary, minimalist, energetic, calm,
    data_viz, narrative, academic, news, creative.
    Returns JSON with ``video_id`` and ``status``.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().generate_video(notebook_id, style)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def notebooklm_node_extract_tables(notebook_id: str, query: str = "") -> str:
    """Extract structured data tables from a NotebookLM notebook's sources.
    Optionally filter by ``query`` topic. Returns JSON with ``tables`` list,
    each table having ``headers`` and ``rows``.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().extract_tables(notebook_id, query)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def notebooklm_node_chat_history(notebook_id: str, limit: int = 20) -> str:
    """Get recent chat/Q&A history for a NotebookLM notebook.
    Returns JSON array of ``{question, answer, timestamp}`` objects.
    """
    try:
        from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
        result = get_nlm_node_bridge().get_chat_history(notebook_id, limit=limit)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def notebooklm_node_health() -> str:
    """Get combined health status of both NLM backends: Node MCP bridge
    (Patchright) and batchexecute proxy. Returns JSON with auth state,
    available tools, proxy reachability, and Chrome profile status.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().health()
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def notebooklm_node_setup_auth() -> str:
    """Run first-time Google authentication for the Node MCP bridge.
    Opens Chrome visibly — log in once and the profile is saved permanently.
    All subsequent calls work in headless mode automatically.
    Only callable by copilot (admin operation).
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        result = get_nlm_hybrid().setup_auth()
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def notebooklm_node_sync_nexus(notebook_id: str, questions: str) -> str:
    """Batch-ask questions against a NotebookLM notebook and automatically
    store every answer as a Q&A pair in Nexus. This is the primary method
    for distilling notebook knowledge into the Nexus knowledge base.

    ``questions`` must be a JSON array of strings.
    Returns JSON with ``stored`` count, ``errors``, and each Q&A pair.
    """
    try:
        from engine.mcp.nlm_hybrid import get_nlm_hybrid
        from engine.nexus.client import get_nexus_client

        q_list = json.loads(questions) if isinstance(questions, str) else questions
        if not isinstance(q_list, list):
            return json.dumps({"error": "questions must be a JSON array"})

        results = get_nlm_hybrid().ask_batch(notebook_id, q_list)
        client = get_nexus_client()

        stored = 0
        errors = 0
        pairs = []
        for q, r in zip(q_list, results):
            answer = r.get("answer", "") if isinstance(r, dict) else str(r)
            if answer and "error" not in r:
                try:
                    client.add_qa(q, answer, category="nlm-distilled")
                    stored += 1
                    pairs.append({"question": q, "answer": answer[:200]})
                except Exception:
                    errors += 1
            else:
                errors += 1

        return json.dumps({"stored": stored, "errors": errors, "pairs": pairs})
    except Exception as exc:
        return json.dumps({"error": str(exc)})
