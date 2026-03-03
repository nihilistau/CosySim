"""Inventory system for CosySim — item management, equipment, and cyberware.

Provides an InventoryManager singleton that tracks:
- Items (type, quantity, equipped state)
- Equipment slots (cyberware, weapons, clothing, tools)
- Item categories with HUD display metadata

Persists to ``data/inventory.json`` and integrates with PlayerState
so ``/api/hud/state`` returns a full inventory snapshot.

Usage::

    from engine.world.inventory import get_inventory

    inv = get_inventory()
    inv.add_item("neural_jack", quantity=1)
    inv.equip("neural_jack", slot="cyberware_1")
    snapshot = inv.to_dict()
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Item Category Definitions ────────────────────────────────────────────────

ITEM_CATEGORIES = {
    "weapon":    {"label": "Weapons",    "icon": "🔫", "stackable": False},
    "cyberware": {"label": "Cyberware",  "icon": "🦾", "stackable": False},
    "software":  {"label": "Software",   "icon": "💾", "stackable": True},
    "cyberdeck": {"label": "Cyberdecks", "icon": "💻", "stackable": False},
    "drug":      {"label": "Chems",      "icon": "💊", "stackable": True},
    "food":      {"label": "Food",       "icon": "🍜", "stackable": True},
    "clothing":  {"label": "Clothing",   "icon": "👗", "stackable": False},
    "tool":      {"label": "Tools",      "icon": "🔧", "stackable": True},
    "data":      {"label": "Data",       "icon": "📁", "stackable": True},
    "credit":    {"label": "Currency",   "icon": "₵",  "stackable": True},
    "key":       {"label": "Keys",       "icon": "🔑", "stackable": False},
    "misc":      {"label": "Misc",       "icon": "📦", "stackable": True},
}

# Equipment slots
EQUIPMENT_SLOTS = [
    "head",
    "torso",
    "legs",
    "hands",
    "feet",
    "weapon_main",
    "weapon_off",
    "cyberware_1",
    "cyberware_2",
    "cyberware_3",
    "cyberdeck",
    "accessory_1",
    "accessory_2",
]

# Built-in item catalog (item_id → metadata)
ITEM_CATALOG: Dict[str, Dict[str, Any]] = {
    # ── Cyberware ──
    "neural_jack":       {"name": "Neural Jack",        "category": "cyberware", "rarity": "common",    "slot": "cyberware_1", "desc": "+1 Hacking speed"},
    "reflex_booster":    {"name": "Reflex Booster",     "category": "cyberware", "rarity": "rare",      "slot": "cyberware_2", "desc": "+2 Combat reaction"},
    "subdermal_armor":   {"name": "Subdermal Armor",    "category": "cyberware", "rarity": "rare",      "slot": "cyberware_1", "desc": "+15 max health"},
    "optic_implant":     {"name": "Optic Implant",      "category": "cyberware", "rarity": "uncommon",  "slot": "cyberware_2", "desc": "Enhanced vision, thermal"},
    "voice_modulator":   {"name": "Voice Modulator",    "category": "cyberware", "rarity": "uncommon",  "slot": "cyberware_3", "desc": "+1 Social manipulation"},
    "pain_editor":       {"name": "Pain Editor",        "category": "cyberware", "rarity": "rare",      "slot": "cyberware_1", "desc": "Ignore 20% damage penalty"},
    # ── Cyberdecks ──
    "netrunner_mk1":     {"name": "Netrunner MK1",      "category": "cyberdeck", "rarity": "common",    "slot": "cyberdeck",   "desc": "Basic hacking deck, 3 slots"},
    "void_runner":       {"name": "Void Runner",        "category": "cyberdeck", "rarity": "rare",      "slot": "cyberdeck",   "desc": "Advanced deck, 6 slots, ICE breach"},
    "specter_3000":      {"name": "Specter 3000",       "category": "cyberdeck", "rarity": "legendary", "slot": "cyberdeck",   "desc": "Military-grade, 8 slots, silent"},
    # ── Software ──
    "ice_breaker_v1":    {"name": "ICE Breaker v1",     "category": "software",  "rarity": "common",    "slot": None,          "desc": "Cracks basic security"},
    "shadow_protocol":   {"name": "Shadow Protocol",    "category": "software",  "rarity": "rare",      "slot": None,          "desc": "Masks netrunner signature"},
    "data_mine":         {"name": "Data Mine",          "category": "software",  "rarity": "uncommon",  "slot": None,          "desc": "Extract encrypted data packets"},
    "tracer_kill":       {"name": "Tracer Kill",        "category": "software",  "rarity": "rare",      "slot": None,          "desc": "Destroys tracking daemons"},
    # ── Weapons ──
    "monofilament":      {"name": "Monofilament Wire",  "category": "weapon",    "rarity": "uncommon",  "slot": "weapon_main", "desc": "Silent. Lethal."},
    "nano_blade":        {"name": "Nano Blade",         "category": "weapon",    "rarity": "rare",      "slot": "weapon_main", "desc": "Vibro-edge, cuts through light armor"},
    "rail_pistol":       {"name": "Rail Pistol",        "category": "weapon",    "rarity": "uncommon",  "slot": "weapon_main", "desc": "Electromagnetic discharge, 15 rounds"},
    # ── Drugs / Chems ──
    "stim_pack":         {"name": "Stim Pack",          "category": "drug",      "rarity": "common",    "slot": None,          "desc": "+30 energy for 1 hour"},
    "health_booster":    {"name": "Health Booster",     "category": "drug",      "rarity": "common",    "slot": None,          "desc": "+25 health"},
    "focus_chip":        {"name": "Focus Chip",         "category": "drug",      "rarity": "uncommon",  "slot": None,          "desc": "+2 Hacking & Tech for 30 mins"},
    "black_lotus":       {"name": "Black Lotus",        "category": "drug",      "rarity": "rare",      "slot": None,          "desc": "High-grade synthetic. Euphoric. Addictive."},
    # ── Food ──
    "synth_ramen":       {"name": "Synth Ramen",        "category": "food",      "rarity": "common",    "slot": None,          "desc": "+20 hunger"},
    "protein_bar":       {"name": "Protein Bar",        "category": "food",      "rarity": "common",    "slot": None,          "desc": "+10 hunger, +5 energy"},
    "corp_ration":       {"name": "Corp Ration",        "category": "food",      "rarity": "common",    "slot": None,          "desc": "+15 hunger"},
    # ── Data / Keys ──
    "encrypted_file":    {"name": "Encrypted File",     "category": "data",      "rarity": "uncommon",  "slot": None,          "desc": "Contents unknown. Someone wants this."},
    "corp_keycard":      {"name": "Corp Keycard",       "category": "key",       "rarity": "uncommon",  "slot": None,          "desc": "Access to OmniCorp service elevators"},
    "ghost_net_token":   {"name": "Ghost Net Token",    "category": "data",      "rarity": "rare",      "slot": None,          "desc": "Darknet access credential"},
}


# ──── Data structures ───────────────────────────────────────────────────────────

@dataclass
class InventoryItem:
    item_id: str
    quantity: int = 1
    equipped: bool = False
    equipped_slot: Optional[str] = None
    acquired_at: float = field(default_factory=time.time)
    custom_name: Optional[str] = None
    condition: int = 100  # 0–100
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        catalog_data = ITEM_CATALOG.get(self.item_id, {})
        return {
            "item_id": self.item_id,
            "quantity": self.quantity,
            "equipped": self.equipped,
            "equipped_slot": self.equipped_slot,
            "acquired_at": self.acquired_at,
            "custom_name": self.custom_name,
            "condition": self.condition,
            "tags": list(self.tags),
            # Catalog data merged in for convenience
            "name": self.custom_name or catalog_data.get("name", self.item_id),
            "category": catalog_data.get("category", "misc"),
            "rarity": catalog_data.get("rarity", "common"),
            "desc": catalog_data.get("desc", ""),
            "icon": ITEM_CATEGORIES.get(catalog_data.get("category", "misc"), {}).get("icon", "📦"),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InventoryItem":
        return cls(
            item_id=data["item_id"],
            quantity=int(data.get("quantity", 1)),
            equipped=bool(data.get("equipped", False)),
            equipped_slot=data.get("equipped_slot"),
            acquired_at=float(data.get("acquired_at", time.time())),
            custom_name=data.get("custom_name"),
            condition=int(data.get("condition", 100)),
            tags=list(data.get("tags", [])),
        )


# ──── InventoryManager ──────────────────────────────────────────────────────────

class InventoryManager:
    """Thread-safe inventory singleton.

    Tracks the player's items with full metadata. Persists to
    ``data/inventory.json``.
    """

    _SAVE_PATH: Path = Path("data") / "inventory.json"
    _instance: Optional["InventoryManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._item_lock = threading.Lock()
        self._items: Dict[str, InventoryItem] = {}
        self._equipment: Dict[str, Optional[str]] = {slot: None for slot in EQUIPMENT_SLOTS}
        self._max_slots: int = 30
        if self._SAVE_PATH.exists():
            try:
                self._load()
            except Exception as exc:
                logger.warning("InventoryManager: load failed: %s", exc)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def add_item(
        self,
        item_id: str,
        quantity: int = 1,
        auto_equip: bool = False,
        tags: Optional[List[str]] = None,
    ) -> Optional[InventoryItem]:
        """Add *quantity* of *item_id* to the inventory.

        Args:
            item_id: Item identifier (see ITEM_CATALOG).
            quantity: Amount to add.
            auto_equip: If True and item has a preferred slot, equip it automatically.
            tags: Optional extra tags for this item instance.

        Returns:
            The InventoryItem, or None if inventory is full.
        """
        with self._item_lock:
            # Check capacity for non-stackable new items
            catalog_data = ITEM_CATALOG.get(item_id, {})
            is_stackable = ITEM_CATEGORIES.get(catalog_data.get("category", "misc"), {}).get("stackable", True)

            if item_id in self._items and is_stackable:
                self._items[item_id].quantity += quantity
                item = self._items[item_id]
            else:
                if len(self._items) >= self._max_slots and item_id not in self._items:
                    logger.warning("Inventory full (%d slots), cannot add %s", self._max_slots, item_id)
                    return None
                self._items[item_id] = InventoryItem(
                    item_id=item_id,
                    quantity=quantity,
                    tags=list(tags or []),
                )
                item = self._items[item_id]

        if auto_equip:
            preferred_slot = catalog_data.get("slot")
            if preferred_slot and self._equipment.get(preferred_slot) is None:
                self.equip(item_id, preferred_slot)

        self._save()
        logger.debug("add_item: %s ×%d → inventory", item_id, quantity)
        return item

    def remove_item(self, item_id: str, quantity: int = 1) -> bool:
        """Remove *quantity* of *item_id* from inventory.

        Args:
            item_id: Item identifier.
            quantity: Amount to remove.

        Returns:
            True if removed, False if not found or insufficient quantity.
        """
        with self._item_lock:
            if item_id not in self._items:
                return False
            item = self._items[item_id]
            if item.quantity < quantity:
                return False
            item.quantity -= quantity
            if item.quantity <= 0:
                # Unequip first
                if item.equipped and item.equipped_slot:
                    self._equipment[item.equipped_slot] = None
                del self._items[item_id]
        self._save()
        return True

    def has_item(self, item_id: str, quantity: int = 1) -> bool:
        """Return True if inventory contains at least *quantity* of *item_id*."""
        with self._item_lock:
            item = self._items.get(item_id)
            return item is not None and item.quantity >= quantity

    def get_item(self, item_id: str) -> Optional[InventoryItem]:
        """Return the InventoryItem for *item_id*, or None."""
        with self._item_lock:
            return self._items.get(item_id)

    # ── Equipment ─────────────────────────────────────────────────────────────

    def equip(self, item_id: str, slot: str) -> bool:
        """Equip *item_id* to *slot*.

        Args:
            item_id: Item to equip.
            slot: Equipment slot name.

        Returns:
            True if equipped successfully.
        """
        with self._item_lock:
            if item_id not in self._items:
                return False
            if slot not in self._equipment:
                return False
            # Unequip anything in that slot
            current = self._equipment.get(slot)
            if current and current in self._items:
                self._items[current].equipped = False
                self._items[current].equipped_slot = None
            # Equip
            self._equipment[slot] = item_id
            item = self._items[item_id]
            item.equipped = True
            item.equipped_slot = slot
        self._save()
        return True

    def unequip(self, item_id: str) -> bool:
        """Unequip *item_id* from its current slot.

        Args:
            item_id: Item to unequip.

        Returns:
            True if unequipped.
        """
        with self._item_lock:
            item = self._items.get(item_id)
            if not item or not item.equipped:
                return False
            if item.equipped_slot and item.equipped_slot in self._equipment:
                self._equipment[item.equipped_slot] = None
            item.equipped = False
            item.equipped_slot = None
        self._save()
        return True

    def get_equipped(self) -> Dict[str, Optional[str]]:
        """Return the equipment slots dict (slot → item_id or None)."""
        with self._item_lock:
            return dict(self._equipment)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_items_by_category(self, category: str) -> List[InventoryItem]:
        """Return all items in *category*."""
        with self._item_lock:
            return [
                item for item in self._items.values()
                if ITEM_CATALOG.get(item.item_id, {}).get("category") == category
            ]

    def get_cyberware(self) -> List[InventoryItem]:
        """Return all cyberware items."""
        return self.get_items_by_category("cyberware")

    def get_cyberdeck(self) -> Optional[InventoryItem]:
        """Return the equipped cyberdeck, or None."""
        with self._item_lock:
            deck_id = self._equipment.get("cyberdeck")
            return self._items.get(deck_id) if deck_id else None

    def item_count(self) -> int:
        """Return number of unique item types in inventory."""
        with self._item_lock:
            return len(self._items)

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a full JSON-safe snapshot for REST responses."""
        with self._item_lock:
            items = [item.to_dict() for item in self._items.values()]
        return {
            "items": items,
            "equipment": dict(self._equipment),
            "item_count": len(items),
            "max_slots": self._max_slots,
            "categories": ITEM_CATEGORIES,
        }

    def to_hud_dict(self) -> List[Dict[str, Any]]:
        """Return compact item list for HUD display (first 12 items)."""
        with self._item_lock:
            items = list(self._items.values())
        result = []
        for item in items[:12]:
            cat = ITEM_CATALOG.get(item.item_id, {})
            result.append({
                "id":       item.item_id,
                "name":     item.custom_name or cat.get("name", item.item_id),
                "qty":      item.quantity,
                "equipped": item.equipped,
                "icon":     ITEM_CATEGORIES.get(cat.get("category", "misc"), {}).get("icon", "📦"),
                "rarity":   cat.get("rarity", "common"),
            })
        return result

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            self._SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with self._item_lock:
                data = {
                    "items": {k: v.to_dict() for k, v in self._items.items()},
                    "equipment": dict(self._equipment),
                    "max_slots": self._max_slots,
                    "_saved_at": time.time(),
                }
            self._SAVE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("InventoryManager._save failed: %s", exc)

    def _load(self) -> None:
        data = json.loads(self._SAVE_PATH.read_text(encoding="utf-8"))
        with self._item_lock:
            items_raw = data.get("items", {})
            self._items = {}
            for item_id, item_data in items_raw.items():
                if isinstance(item_data, dict):
                    self._items[item_id] = InventoryItem.from_dict(item_data)
            equipment_raw = data.get("equipment", {})
            for slot in EQUIPMENT_SLOTS:
                self._equipment[slot] = equipment_raw.get(slot)
            self._max_slots = int(data.get("max_slots", 30))
        logger.info("InventoryManager loaded %d items", len(self._items))


# ──── Singleton accessor ──────────────────────────────────────────────────────


def get_inventory() -> InventoryManager:
    """Return the process-wide InventoryManager singleton."""
    if InventoryManager._instance is None:
        with InventoryManager._lock:
            if InventoryManager._instance is None:
                InventoryManager._instance = InventoryManager()
    return InventoryManager._instance
