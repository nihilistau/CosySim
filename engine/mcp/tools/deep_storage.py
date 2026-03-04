"""MCP tool domain: deep_storage.

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

# ──── DEEP_STORAGE TOOLS ─────────────────────────────────────────────────


@mcp_tool
def deep_storage_archive(notebook_id: str) -> str:
    """Archive a single NLM notebook into Nexus deep storage — stores metadata, sources, conversations, notes."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().archive_notebook(notebook_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def deep_storage_archive_all() -> str:
    """Archive ALL NLM notebooks into Nexus deep storage."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().archive_all(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def deep_storage_from_har(har_path: str) -> str:
    """Archive notebook content extracted from a browser HAR capture."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().archive_from_har(har_path), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def deep_storage_retrieve(notebook_id: str) -> str:
    """Retrieve all archived content for a notebook from deep storage."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().retrieve(notebook_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def deep_storage_list() -> str:
    """List all archived NLM notebooks in deep storage."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().list_archives(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def deep_storage_search(query: str) -> str:
    """Search across all archived NLM conversations."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().search_conversations(query), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def deep_storage_chain(chain_id: str) -> str:
    """Retrieve all entries in a conversation chain by chain ID."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().get_chain(chain_id), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def deep_storage_stats() -> str:
    """Get NLM deep storage statistics — archive counts, entries stored."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage
        return json.dumps(get_deep_storage().stats(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
