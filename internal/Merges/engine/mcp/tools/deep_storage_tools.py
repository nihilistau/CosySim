from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from engine.mcp.decorators import mcp_tool, ToolExecutionError


@mcp_tool
def deep_storage_archive_impl(notebook_id: str) -> Dict[str, Any]:
    """Archive a single NLM notebook into Nexus deep storage — stores metadata, sources, conversations, notes."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage

        return get_deep_storage().archive_notebook(notebook_id)
    except ImportError:
        raise ToolExecutionError("Deep Storage module not available.")


@mcp_tool
def deep_storage_archive_all_impl() -> Dict[str, Any]:
    """Archive ALL NLM notebooks into Nexus deep storage."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage

        return get_deep_storage().archive_all()
    except ImportError:
        raise ToolExecutionError("Deep Storage module not available.")


@mcp_tool
def deep_storage_from_har_impl(har_path: str) -> Dict[str, Any]:
    """Archive notebook content extracted from a browser HAR capture."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage

        return get_deep_storage().archive_from_har(har_path)
    except ImportError:
        raise ToolExecutionError("Deep Storage module not available.")


@mcp_tool
def deep_storage_retrieve_impl(notebook_id: str) -> Dict[str, Any]:
    """Retrieve all archived content for a notebook from deep storage."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage

        return get_deep_storage().retrieve(notebook_id)
    except ImportError:
        raise ToolExecutionError("Deep Storage module not available.")


@mcp_tool
def deep_storage_list_impl() -> List[Dict[str, Any]]:
    """List all archived NLM notebooks in deep storage."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage

        return get_deep_storage().list_archives()
    except ImportError:
        raise ToolExecutionError("Deep Storage module not available.")


@mcp_tool
def deep_storage_search_impl(query: str) -> List[Dict[str, Any]]:
    """Search across all archived NLM conversations."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage

        return get_deep_storage().search_conversations(query)
    except ImportError:
        raise ToolExecutionError("Deep Storage module not available.")


@mcp_tool
def deep_storage_chain_impl(chain_id: str) -> Dict[str, Any]:
    """Retrieve all entries in a conversation chain by chain ID."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage

        return get_deep_storage().get_chain(chain_id)
    except ImportError:
        raise ToolExecutionError("Deep Storage module not available.")


@mcp_tool
def deep_storage_stats_impl() -> Dict[str, Any]:
    """Get NLM deep storage statistics — archive counts, entries stored."""
    try:
        from engine.nexus.nlm_deep_storage import get_deep_storage

        return get_deep_storage().stats()
    except ImportError:
        raise ToolExecutionError("Deep Storage module not available.")
