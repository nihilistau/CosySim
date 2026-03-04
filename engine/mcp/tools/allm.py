"""MCP tool domain: allm.

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

# ──── ALLM TOOLS ─────────────────────────────────────────────────────────


@mcp_tool
def allm_connect(instance: str = "") -> str:
    """Connect to AnythingLLM instance(s). Leave empty for all."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client
        client = get_anythingllm_client()
        if instance:
            return json.dumps(client.connect(instance=instance))
        return json.dumps(client.connect_all())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
def allm_status() -> str:
    """Get status of all AnythingLLM instances."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client
        return json.dumps(get_anythingllm_client().status())
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
def allm_list_workspaces(instance: str = "") -> str:
    """List workspaces on an AnythingLLM instance."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client
        return json.dumps(get_anythingllm_client().list_workspaces(instance=instance or None))
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
def allm_chat(workspace: str, message: str, mode: str = "chat", instance: str = "") -> str:
    """Chat with an AnythingLLM workspace."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client
        result = get_anythingllm_client().chat(workspace, message, mode=mode, instance=instance or None)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
def allm_sync_to_nexus(workspace: str, instance: str = "") -> str:
    """Sync AnythingLLM workspace Q&A pairs to Nexus."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client
        return json.dumps(get_anythingllm_client().sync_to_nexus(workspace, instance=instance or None))
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
def allm_sync_from_nexus(workspace: str, query: str = "*", limit: int = 50, instance: str = "") -> str:
    """Push Nexus knowledge into an AnythingLLM workspace for RAG."""
    try:
        from engine.integrations.anythingllm import get_anythingllm_client
        return json.dumps(get_anythingllm_client().sync_from_nexus(workspace, query=query, limit=limit, instance=instance or None))
    except Exception as exc:
        return json.dumps({"error": str(exc)})
