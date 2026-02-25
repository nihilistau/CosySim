"""
Pure business-logic helpers for wardrobe MCP tools.

Each function receives its dependencies (scene-state manager, etc.) as
explicit parameters so the module stays free of global MCP state.
"""

from __future__ import annotations

import json
from typing import Any, Dict


# ── wardrobe_get ─────────────────────────────────────────────────────

def wardrobe_get(ssm: Any, character_id: str) -> str:
    """Return full clothing inventory for *character_id* as JSON."""
    wardrobe = ssm.get_wardrobe(character_id)
    return json.dumps(wardrobe.to_dict(), indent=2)


# ── wardrobe_init ────────────────────────────────────────────────────

def wardrobe_init(ssm: Any, character_id: str, style: str = "casual") -> str:
    """Give *character_id* a starter wardrobe of the given *style*."""
    wardrobe = ssm.initialise_wardrobe(character_id, style=style)
    return json.dumps({
        "initialised": True,
        "style": style,
        "item_count": len(wardrobe.items),
        "description": wardrobe.coverage_description(),
        "worn_items": [
            {"id": i.id, "name": i.name, "category": i.category}
            for i in wardrobe.worn_items()
        ],
    }, indent=2)


# ── wardrobe_remove_item ─────────────────────────────────────────────

def wardrobe_remove_item(
    ssm: Any,
    character_id: str,
    item_id: str,
    removed_by: str = "",
) -> str:
    """Remove a specific clothing *item_id* from *character_id*."""
    item = ssm.remove_clothing(character_id, item_id, removed_by=removed_by)
    if not item:
        wardrobe = ssm.get_wardrobe(character_id)
        existing = wardrobe.get_item(item_id)
        if existing and not existing.is_worn:
            return json.dumps({"error": f"'{item_id}' is already removed.", "already_removed": True})
        return json.dumps({"error": f"Item '{item_id}' not found in wardrobe."})

    wardrobe = ssm.get_wardrobe(character_id)
    ssm.update_stats(character_id, arousal=8, openness=3)
    return json.dumps({
        "removed": True,
        "item": item.to_dict(),
        "now_wearing": wardrobe.coverage_description(),
        "is_naked": len(wardrobe.worn_items()) == 0,
        "stat_effect": "arousal+8, openness+3",
    }, indent=2)


# ── wardrobe_remove_outermost ────────────────────────────────────────

def wardrobe_remove_outermost(
    ssm: Any,
    character_id: str,
    removed_by: str = "",
) -> str:
    """Strip the outermost clothing layer from *character_id*."""
    item = ssm.remove_outermost(character_id, removed_by=removed_by)
    if not item:
        return json.dumps({
            "removed": False,
            "message": f"{character_id} is already wearing nothing.",
            "is_naked": True,
        })
    wardrobe = ssm.get_wardrobe(character_id)
    ssm.update_stats(character_id, arousal=12, openness=5)
    return json.dumps({
        "removed": True,
        "item": item.to_dict(),
        "now_wearing": wardrobe.coverage_description(),
        "remaining_layers": len(wardrobe.worn_items()),
        "is_naked": len(wardrobe.worn_items()) == 0,
        "stat_effect": "arousal+12, openness+5",
    }, indent=2)


# ── wardrobe_add_item ────────────────────────────────────────────────

def wardrobe_add_item(
    ssm: Any,
    character_id: str,
    item_id: str,
    name: str,
    category: str,
    color: str = "black",
    style: str = "casual",
) -> str:
    """Add a new clothing item (as worn) to *character_id*'s wardrobe."""
    from engine.mcp.scene_state import ClothingItem

    item = ClothingItem(id=item_id, name=name, category=category, color=color, style=style)
    ssm.add_clothing(character_id, item)
    wardrobe = ssm.get_wardrobe(character_id)
    return json.dumps({
        "added": True,
        "item": item.to_dict(),
        "now_wearing": wardrobe.coverage_description(),
    }, indent=2)


# ── wardrobe_redress ─────────────────────────────────────────────────

def wardrobe_redress(ssm: Any, character_id: str) -> str:
    """Put all previously removed clothing back on *character_id*."""
    count = ssm.re_dress(character_id)
    wardrobe = ssm.get_wardrobe(character_id)
    return json.dumps({
        "redressed": True,
        "items_restored": count,
        "now_wearing": wardrobe.coverage_description(),
    }, indent=2)
