"""MCP tool domain: wardrobe.

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

# ──── WARDROBE TOOLS ─────────────────────────────────────────────────────


@mcp_tool
def wardrobe_get(character_id: str) -> str:
    """
    Get the full clothing inventory for a character — what they're wearing and
    what has already been removed.  Call this before any undressing action so
    you know what items exist.

    Returns JSON with 'worn' list, 'removed' list, 'description' (human-readable),
    and 'is_naked' boolean.
    """
    try:
        from engine.mcp.tools.wardrobe_tools import wardrobe_get as _impl
        return _impl(_ssm(), character_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def wardrobe_init(character_id: str, style: str = "casual") -> str:
    """
    Give a character a full starter wardrobe.  Call this when a character first
    enters a scene so they have a clothing inventory.

    style: 'casual' | 'lingerie' | 'party' | 'nightwear' | 'swimwear'
    """
    try:
        from engine.mcp.tools.wardrobe_tools import wardrobe_init as _impl
        return _impl(_ssm(), character_id, style=style)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def wardrobe_remove_item(character_id: str, item_id: str, removed_by: str = "") -> str:
    """
    Remove a specific clothing item from a character.  The item must exist in
    their wardrobe and be currently worn.

    Use wardrobe_get() first to find the correct item_id.
    removed_by: the character_id doing the removing (leave blank if self).

    Returns the item details and updated coverage description, or an error if
    the item is not found or already removed.
    """
    try:
        from engine.mcp.tools.wardrobe_tools import wardrobe_remove_item as _impl
        return _impl(_ssm(), character_id, item_id, removed_by=removed_by)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def wardrobe_remove_outermost(character_id: str, removed_by: str = "") -> str:
    """
    Strip the outermost clothing layer from a character — perfect for a
    striptease or when the Director wants the next item to come off without
    specifying which one.

    Returns what was removed and what's left.  Call repeatedly to fully
    undress.
    """
    try:
        from engine.mcp.tools.wardrobe_tools import wardrobe_remove_outermost as _impl
        return _impl(_ssm(), character_id, removed_by=removed_by)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def wardrobe_add_item(
    character_id: str,
    item_id: str,
    name: str,
    category: str,
    color: str = "black",
    style: str = "casual",
) -> str:
    """
    Add a new clothing item to a character's wardrobe (as worn).
    Useful when the Director gives them something to put on.

    category: bra | underwear | top | bottom | full_outfit | shoes | outerwear | accessory | socks
    """
    try:
        from engine.mcp.tools.wardrobe_tools import wardrobe_add_item as _impl
        return _impl(_ssm(), character_id, item_id, name, category, color=color, style=style)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def wardrobe_redress(character_id: str) -> str:
    """
    Put all previously removed clothing back on a character.
    Use at scene reset or morning-after scenarios.
    """
    try:
        from engine.mcp.tools.wardrobe_tools import wardrobe_redress as _impl
        return _impl(_ssm(), character_id)
    except Exception as e:
        return json.dumps({"error": str(e)})
