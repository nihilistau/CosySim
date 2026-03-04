"""MCP tool domain: phone_assistant.

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

# ──── PHONE_ASSISTANT TOOLS ──────────────────────────────────────────────


@mcp_tool
async def phone_assistant_chat(message: str, mode: str = "", voice: bool = False) -> str:
    """Chat with the phone assistant (cascade: system → nexus → anythingllm → fallback)."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant
        result = get_phone_assistant().chat(message, mode=mode or None, voice=voice)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def phone_assistant_status() -> str:
    """Get phone assistant status: mode, connectivity, stats."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant
        return json.dumps(get_phone_assistant().status(), default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def phone_assistant_set_mode(mode: str) -> str:
    """Set phone assistant mode: auto, passthrough, or offline."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant
        result = get_phone_assistant().set_mode(mode)
        return json.dumps({"mode": result})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp_tool
async def phone_assistant_history(limit: int = 20) -> str:
    """Get recent phone assistant conversation history."""
    try:
        from engine.assistant.phone_assistant import get_phone_assistant
        return json.dumps(get_phone_assistant().get_history(limit), default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
