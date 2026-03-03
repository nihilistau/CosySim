"""Inventory skills for CosySim LLM agents.

Exposes the InventoryManager as @skill tools so agents can check,
add, remove, and equip items on behalf of the player.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="inventory",
    description="Check what items the player currently has in their inventory.",
    category="GAME",
    tags=["inventory", "items"],
)
def inventory_list() -> str:
    """Return the player's current inventory as a formatted list."""
    try:
        from engine.world.inventory import get_inventory
        inv = get_inventory()
        items = inv.to_dict()["items"]
        if not items:
            return "Inventory is empty."
        lines = []
        for item in items:
            eq = " [EQUIPPED]" if item.get("equipped") else ""
            lines.append(
                f"  {item['icon']} {item['name']} ×{item['quantity']}"
                f"  [{item['rarity'].upper()}]{eq}"
                f"  — {item['desc']}"
            )
        return f"Inventory ({len(items)} items):\n" + "\n".join(lines)
    except Exception as exc:
        logger.warning("inventory_list failed: %s", exc)
        return f"Error retrieving inventory: {exc}"


@skill(
    pack="inventory",
    description="Add an item to the player's inventory by item_id.",
    category="GAME",
    tags=["inventory", "pickup"],
)
def inventory_add(item_id: str, quantity: int = 1) -> str:
    """Add *quantity* of *item_id* to inventory.

    Args:
        item_id: The item identifier (e.g. 'stim_pack', 'neural_jack').
        quantity: Number of items to add.
    """
    try:
        from engine.world.inventory import get_inventory, ITEM_CATALOG
        if item_id not in ITEM_CATALOG:
            return f"Unknown item '{item_id}'. Check available items first."
        inv = get_inventory()
        item = inv.add_item(item_id, quantity=quantity)
        if item is None:
            return "Cannot add item — inventory is full (30 slots max)."
        name = ITEM_CATALOG[item_id].get("name", item_id)
        return f"Added {quantity}× {name} to inventory."
    except Exception as exc:
        logger.warning("inventory_add failed: %s", exc)
        return f"Error adding item: {exc}"


@skill(
    pack="inventory",
    description="Remove an item from the player's inventory.",
    category="GAME",
    tags=["inventory", "drop"],
)
def inventory_remove(item_id: str, quantity: int = 1) -> str:
    """Remove *quantity* of *item_id* from inventory.

    Args:
        item_id: The item identifier.
        quantity: Number to remove.
    """
    try:
        from engine.world.inventory import get_inventory, ITEM_CATALOG
        inv = get_inventory()
        ok = inv.remove_item(item_id, quantity=quantity)
        if not ok:
            name = ITEM_CATALOG.get(item_id, {}).get("name", item_id)
            return f"Cannot remove '{name}' — item not found or insufficient quantity."
        name = ITEM_CATALOG.get(item_id, {}).get("name", item_id)
        return f"Removed {quantity}× {name} from inventory."
    except Exception as exc:
        logger.warning("inventory_remove failed: %s", exc)
        return f"Error removing item: {exc}"


@skill(
    pack="inventory",
    description="Equip an item to an equipment slot (weapon_main, cyberdeck, cyberware_1, etc.).",
    category="GAME",
    tags=["inventory", "equip"],
)
def inventory_equip(item_id: str, slot: str) -> str:
    """Equip *item_id* to *slot*.

    Args:
        item_id: The item identifier.
        slot: Equipment slot (head/torso/legs/weapon_main/cyberdeck/cyberware_1..3/etc.).
    """
    try:
        from engine.world.inventory import get_inventory, ITEM_CATALOG, EQUIPMENT_SLOTS
        if slot not in EQUIPMENT_SLOTS:
            return f"Unknown slot '{slot}'. Valid slots: {', '.join(EQUIPMENT_SLOTS)}"
        inv = get_inventory()
        ok = inv.equip(item_id, slot)
        if not ok:
            return f"Cannot equip '{item_id}' to {slot} — item not in inventory or slot invalid."
        name = ITEM_CATALOG.get(item_id, {}).get("name", item_id)
        return f"{name} equipped to {slot}."
    except Exception as exc:
        logger.warning("inventory_equip failed: %s", exc)
        return f"Error equipping item: {exc}"


@skill(
    pack="inventory",
    description="Check which items are currently equipped in equipment slots.",
    category="GAME",
    tags=["inventory", "equipment"],
)
def inventory_equipped() -> str:
    """Return a list of all currently equipped items by slot."""
    try:
        from engine.world.inventory import get_inventory, ITEM_CATALOG
        inv = get_inventory()
        equipment = inv.get_equipped()
        lines = []
        for slot, item_id in equipment.items():
            if item_id:
                name = ITEM_CATALOG.get(item_id, {}).get("name", item_id)
                lines.append(f"  [{slot}] {name}")
        if not lines:
            return "No items equipped."
        return "Equipped loadout:\n" + "\n".join(lines)
    except Exception as exc:
        logger.warning("inventory_equipped failed: %s", exc)
        return f"Error getting equipped items: {exc}"


@skill(
    pack="inventory",
    description="Check if the player has a specific item (and optionally how many).",
    category="GAME",
    tags=["inventory", "check"],
)
def inventory_has(item_id: str, quantity: int = 1) -> str:
    """Check if inventory contains at least *quantity* of *item_id*.

    Args:
        item_id: The item identifier.
        quantity: Minimum quantity to check for.
    """
    try:
        from engine.world.inventory import get_inventory, ITEM_CATALOG
        inv = get_inventory()
        has = inv.has_item(item_id, quantity=quantity)
        name = ITEM_CATALOG.get(item_id, {}).get("name", item_id)
        if has:
            item = inv.get_item(item_id)
            qty_msg = f" (×{item.quantity})" if item else ""
            return f"Yes — player has {name}{qty_msg}."
        return f"No — player does not have {quantity}× {name}."
    except Exception as exc:
        logger.warning("inventory_has failed: %s", exc)
        return f"Error checking inventory: {exc}"


@skill(
    pack="inventory",
    description="List all available items in the item catalog with their categories and descriptions.",
    category="GAME",
    tags=["inventory", "catalog"],
)
def inventory_catalog(category: Optional[str] = None) -> str:
    """Return items available in the item catalog.

    Args:
        category: Filter by category (weapon/cyberware/drug/food/etc.) or omit for all.
    """
    try:
        from engine.world.inventory import ITEM_CATALOG, ITEM_CATEGORIES
        items = ITEM_CATALOG.items()
        if category:
            items = [(k, v) for k, v in items if v.get("category") == category]
        else:
            items = list(items)
        if not items:
            return f"No items found for category '{category}'."
        lines = []
        for item_id, data in sorted(items, key=lambda x: x[1].get("category", "")):
            icon = ITEM_CATEGORIES.get(data.get("category", "misc"), {}).get("icon", "📦")
            lines.append(
                f"  {icon} {data['name']} (id: {item_id}, {data['rarity']})"
                f"  — {data['desc']}"
            )
        header = f"Item catalog ({len(lines)} items)"
        if category:
            header += f" filtered by '{category}'"
        return header + ":\n" + "\n".join(lines)
    except Exception as exc:
        logger.warning("inventory_catalog failed: %s", exc)
        return f"Error getting catalog: {exc}"
