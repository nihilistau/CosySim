"""MCP tool domain: user_profile.

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

# ──── USER_PROFILE TOOLS ─────────────────────────────────────────────────


@mcp_tool
async def user_profile_get() -> str:
    """Retrieve the current user profile (extracted from conversations)."""
    from engine.nexus.user_profile import get_user_profile_store
    store = get_user_profile_store()
    profile = store.get()
    return json.dumps(profile, indent=2)


@mcp_tool
async def user_profile_update(updates: str) -> str:
    """Merge updates into the user profile.

    Args:
        updates: JSON string with profile fields to update.
    """
    from engine.nexus.user_profile import get_user_profile_store
    store = get_user_profile_store()
    try:
        data = json.loads(updates)
    except json.JSONDecodeError as exc:
        return f"ERROR: Invalid JSON: {exc}"
    result = store.merge(data)
    return json.dumps(result, indent=2)
