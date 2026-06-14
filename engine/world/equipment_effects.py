"""
Equipment Bonuses & Consumable Effects
======================================

Closes the v1.59 audit gap where equipping cyberware/weapons gave **+0**
mechanical bonus and consumable effects were hardcoded for only 9 items.

This module is the single source of truth for:

1. **Equipment bonuses** — a structured map (``EQUIPMENT_BONUSES``) of
   ``item_id`` → skill/stat deltas (e.g. Reflex Booster → ``{"combat": +2}``).
   :func:`get_equipment_bonuses` aggregates every *equipped* item in an
   inventory into one dict that scenes and skill-checks can consume directly.

2. **Consumable effects by CATEGORY** — instead of a hardcoded per-item list,
   :func:`get_consumable_effect` resolves an effect for ANY item whose catalog
   ``category`` is consumable (``drug`` / ``stim`` / ``medkit`` / ``food`` …),
   falling back to sensible per-category defaults. Explicit per-item overrides
   still win. :func:`apply_consumable` applies the effect to a ``PlayerState``
   and (optionally, config-gated) decrements the item ``condition`` / removes a
   stack on use.

Everything is configurable via ``get_config().get("world.equipment.*")`` with
safe defaults baked in, so the module works standalone (and in hermetic tests)
even when no config file is present.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Initial release. Equipment bonus aggregation,
        category-driven consumable effects, condition decrement on use.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from engine.world.inventory import (
    ITEM_CATALOG,
    InventoryItem,
    InventoryManager,
)

logger = logging.getLogger(__name__)

# ──── Public bonus vocabulary ───────────────────────────────────────────────
# Skills mirror engine.world.player_state._DEFAULT_SKILLS; stats are vitals /
# derived modifiers that scenes can read off the aggregate dict.

SKILL_KEYS: tuple[str, ...] = (
    "hacking",
    "combat",
    "stealth",
    "social",
    "tech",
    "driving",
    "medicine",
    "trading",
)

# Stat / derived-modifier keys an equipped item may contribute.
STAT_KEYS: tuple[str, ...] = (
    "max_health",      # bonus to the health ceiling (e.g. subdermal armor)
    "damage_resist",   # % incoming damage ignored
    "crack_speed",     # netrunning crack speed (also on cyberdecks)
    "trace_resist",    # netrunning trace resistance
    "stealth_bonus",   # extra concealment beyond the stealth skill
)

# ──── Equipment bonus table ─────────────────────────────────────────────────
# item_id → {bonus_key: delta}. Keys may be any SKILL_KEYS or STAT_KEYS entry.
# Mirrors the human-readable ``desc`` strings in ITEM_CATALOG, but structured
# so skill-checks can consume them deterministically (no free-text parsing).
#
# CONNECTS: engine.world.inventory.ITEM_CATALOG, engine.world.player_state
# CALLED BY: get_equipment_bonuses()

EQUIPMENT_BONUSES: Dict[str, Dict[str, int]] = {
    # ── Cyberware ──
    "neural_jack":     {"hacking": 1},                       # +1 Hacking speed
    "reflex_booster":  {"combat": 2},                        # +2 Combat reaction
    "subdermal_armor": {"max_health": 15},                   # +15 max health
    "optic_implant":   {"combat": 1, "stealth_bonus": 1},    # thermal/enhanced vision
    "voice_modulator": {"social": 1},                        # +1 Social manipulation
    "pain_editor":     {"damage_resist": 20},                # ignore 20% damage
    # ── Cyberdecks (netrunning gear) ──
    "netrunner_mk1":   {"crack_speed": 1, "trace_resist": 1},
    "void_runner":     {"crack_speed": 3, "trace_resist": 3, "hacking": 1},
    "specter_3000":    {"crack_speed": 6, "trace_resist": 6, "hacking": 2, "stealth_bonus": 2},
    # ── Weapons ──
    "monofilament":    {"combat": 1, "stealth_bonus": 1},    # silent + lethal
    "nano_blade":      {"combat": 2},                        # vibro-edge
    "rail_pistol":     {"combat": 2},                        # EM discharge
}


# ──── Consumable effect tables ──────────────────────────────────────────────
# Per-CATEGORY default effects. Any inventory item whose catalog category is a
# key here is consumable, even if it has no explicit per-item override below.
# Effect keys: health / energy / hunger / heat (PlayerState vitals) and
# ``skill_buffs`` (transient skill nudges scenes may surface).
#
# CONNECTS: engine.world.player_state vitals
# CALLED BY: get_consumable_effect(), apply_consumable()

CATEGORY_CONSUMABLE_EFFECTS: Dict[str, Dict[str, Any]] = {
    "drug":   {"energy": 20, "message_verb": "consumed"},
    "stim":   {"energy": 30, "message_verb": "injected"},
    "medkit": {"health": 40, "message_verb": "applied"},
    "food":   {"hunger": 15, "energy": 3, "message_verb": "eaten"},
}

# Explicit per-item overrides (win over the category default). Preserves the
# exact numbers the original neoncity hardcoded list used so behaviour for the
# 9 legacy items is unchanged, while every *other* consumable now also works.
ITEM_CONSUMABLE_EFFECTS: Dict[str, Dict[str, Any]] = {
    "stim_pack":      {"energy": 30, "message": "Stim Pack injected. +30 energy."},
    "health_booster": {"health": 25, "message": "Health Booster applied. +25 health."},
    "focus_chip":     {"skill_buffs": {"hacking": 2, "tech": 2},
                       "message": "Focus Chip activated. Enhanced hacking and tech."},
    "black_lotus":    {"energy": 15, "health": 10, "heat": 5,
                       "message": "Black Lotus consumed. Euphoric rush. +5 heat."},
    "synth_ramen":    {"health": 10, "energy": 5, "hunger": 20,
                       "message": "Synth Ramen consumed. +10 health, +5 energy."},
    "protein_bar":    {"energy": 10, "health": 5, "hunger": 10,
                       "message": "Protein Bar consumed. +10 energy, +5 health."},
    "corp_ration":    {"health": 8, "energy": 3, "hunger": 15,
                       "message": "Corp Ration consumed. +8 health."},
}

# Catalog categories considered consumable when resolving by category.
CONSUMABLE_CATEGORIES: tuple[str, ...] = tuple(CATEGORY_CONSUMABLE_EFFECTS.keys())

# Vitals an effect dict may carry, mapped to the (clamped) PlayerState mutator.
_VITAL_KEYS: tuple[str, ...] = ("health", "energy", "hunger", "heat")

# ──── Config helpers ────────────────────────────────────────────────────────


def _cfg(key: str, default: Any) -> Any:
    """Read ``world.equipment.<key>`` from config, defaulting safely.

    Resolves config lazily so the module imports cleanly in hermetic tests
    that never initialise the global config.

    Args:
        key: Sub-key under the ``world.equipment`` namespace.
        default: Value to return if config is unavailable or the key is unset.

    Returns:
        The configured value, or *default*.
    """
    try:
        from engine.config import get_config

        return get_config().get(f"world.equipment.{key}", default)
    except Exception:
        return default


# ──── Equipment bonus aggregation ───────────────────────────────────────────


def get_bonuses_for_item(item_id: str) -> Dict[str, int]:
    """Return the structured bonus dict for a single *item_id* (may be empty).

    Args:
        item_id: Inventory item identifier (see ``ITEM_CATALOG``).

    Returns:
        Mapping of skill/stat key → integer delta. Empty if the item grants
        no mechanical bonus.
    """
    return dict(EQUIPMENT_BONUSES.get(item_id, {}))


def _empty_bonus_dict() -> Dict[str, int]:
    """Return a zero-initialised aggregate covering all known bonus keys."""
    agg: Dict[str, int] = {k: 0 for k in SKILL_KEYS}
    agg.update({k: 0 for k in STAT_KEYS})
    return agg


def _iter_equipped_items(
    inventory: Any,
) -> Iterable[InventoryItem]:
    """Yield the equipped :class:`InventoryItem` objects from *inventory*.

    Accepts either an :class:`InventoryManager` or any iterable of
    :class:`InventoryItem` (so callers can pass a filtered list directly).

    Args:
        inventory: An InventoryManager, an iterable of InventoryItem, or None.

    Yields:
        Equipped InventoryItem instances.
    """
    if inventory is None:
        return
    if isinstance(inventory, InventoryManager):
        equipped_map = inventory.get_equipped()  # slot -> item_id
        for item_id in equipped_map.values():
            if not item_id:
                continue
            item = inventory.get_item(item_id)
            if item is not None:
                yield item
        return
    # Iterable of InventoryItem (or item-like): honour .equipped when present.
    for item in inventory:
        if isinstance(item, InventoryItem):
            if item.equipped:
                yield item
        else:  # pragma: no cover - defensive: dict-like fallback
            if getattr(item, "equipped", False) or (isinstance(item, dict) and item.get("equipped")):
                yield item


def get_equipment_bonuses(inventory: Any) -> Dict[str, int]:
    """Aggregate skill/stat bonuses from every *equipped* item.

    This is the headline API: scenes and skill-checks call this and add the
    relevant key to the player's base skill/stat.

    Condition scaling: an item at low ``condition`` contributes proportionally
    less when ``world.equipment.condition_scales_bonus`` is enabled (default
    True). A full-condition item contributes 100%; a 50%-condition item
    contributes ~half (rounded). Items always contribute at least their sign
    while condition > 0 so a worn-but-working implant never reads as zero.

    Args:
        inventory: An :class:`InventoryManager`, an iterable of
            :class:`InventoryItem`, or None. When an InventoryManager is
            passed only currently-equipped slots are counted.

    Returns:
        Aggregate dict with **every** known skill/stat key present (zeros for
        un-bonused keys), so callers can index without ``KeyError``.
    """
    agg = _empty_bonus_dict()
    scales = bool(_cfg("condition_scales_bonus", True))

    for item in _iter_equipped_items(inventory):
        item_id = item.item_id if isinstance(item, InventoryItem) else item.get("item_id")  # type: ignore[union-attr]
        bonuses = EQUIPMENT_BONUSES.get(item_id or "")
        if not bonuses:
            continue
        condition = getattr(item, "condition", 100)
        if isinstance(item, dict):
            condition = item.get("condition", 100)
        for key, delta in bonuses.items():
            scaled = _scale_by_condition(delta, condition) if scales else delta
            agg[key] = agg.get(key, 0) + scaled

    return agg


def _scale_by_condition(delta: int, condition: int) -> int:
    """Scale *delta* by item *condition* (0–100), never flipping its sign.

    Args:
        delta: Raw bonus magnitude.
        condition: Item condition 0–100.

    Returns:
        Condition-scaled delta. A non-zero delta on a >0-condition item keeps
        at least magnitude 1 in its original direction.
    """
    cond = max(0, min(100, int(condition)))
    if delta == 0 or cond <= 0:
        return 0
    scaled = round(delta * cond / 100.0)
    if scaled == 0:  # worn but functional → keep minimal effect
        scaled = 1 if delta > 0 else -1
    return int(scaled)


def describe_equipment_bonuses(inventory: Any) -> Dict[str, int]:
    """Like :func:`get_equipment_bonuses` but drops zero-valued keys.

    Convenient for HUD/tooltip display where only active bonuses matter.

    Args:
        inventory: See :func:`get_equipment_bonuses`.

    Returns:
        Aggregate dict containing only non-zero bonus keys.
    """
    return {k: v for k, v in get_equipment_bonuses(inventory).items() if v}


# ──── Consumable effect resolution ──────────────────────────────────────────


def is_consumable(item_id: str) -> bool:
    """Return True if *item_id* can be consumed (by explicit map or category).

    Args:
        item_id: Inventory item identifier.

    Returns:
        True when the item has an explicit effect OR its catalog category is
        in :data:`CONSUMABLE_CATEGORIES`.
    """
    if item_id in ITEM_CONSUMABLE_EFFECTS:
        return True
    category = ITEM_CATALOG.get(item_id, {}).get("category", "")
    return category in CONSUMABLE_CATEGORIES


def get_consumable_effect(item_id: str) -> Optional[Dict[str, Any]]:
    """Resolve the effect dict for *item_id*, by category when not hardcoded.

    Resolution order:
        1. Explicit per-item override (:data:`ITEM_CONSUMABLE_EFFECTS`).
        2. Category default (:data:`CATEGORY_CONSUMABLE_EFFECTS`) — this is the
           generalisation that makes ANY drug/stim/medkit/food item work.

    Args:
        item_id: Inventory item identifier.

    Returns:
        A normalised effect dict (always carrying a ``message``), or None if
        the item is not consumable.
    """
    catalog = ITEM_CATALOG.get(item_id, {})
    name = catalog.get("name", item_id)

    # 1. Explicit override.
    if item_id in ITEM_CONSUMABLE_EFFECTS:
        effect = dict(ITEM_CONSUMABLE_EFFECTS[item_id])
        effect.setdefault("message", f"Used {name}.")
        return effect

    # 2. Category default.
    category = catalog.get("category", "")
    if category in CATEGORY_CONSUMABLE_EFFECTS:
        base = dict(CATEGORY_CONSUMABLE_EFFECTS[category])
        verb = base.pop("message_verb", "used")
        effect: Dict[str, Any] = {k: v for k, v in base.items() if k in _VITAL_KEYS or k == "skill_buffs"}
        parts: List[str] = []
        for vital in _VITAL_KEYS:
            if vital in effect:
                parts.append(f"+{effect[vital]} {vital}")
        detail = (" " + ", ".join(parts)) if parts else ""
        effect["message"] = f"{name} {verb}.{detail}".rstrip()
        return effect

    return None


def apply_consumable(
    item_id: str,
    player_state: Any,
    inventory: Optional[InventoryManager] = None,
    consume_stack: bool = True,
) -> Dict[str, Any]:
    """Apply a consumable's effect to *player_state* and (optionally) consume it.

    Generalises the old neoncity ``_apply_consumable_effect`` so that **any**
    item resolved by :func:`get_consumable_effect` works — no per-item code.

    Behaviour is config-gated under ``world.equipment``:
        * ``decrement_condition_on_use`` (default True) — reduce the item's
          ``condition`` by ``condition_loss_per_use`` (default 0 for
          consumables, but honoured if set; see note below).
        * For true consumables we remove one from the stack when
          *consume_stack* is True (default), independent of condition.

    Args:
        item_id: Inventory item identifier.
        player_state: A PlayerState-like object exposing vital mutators
            (``adjust_health``/``set_health`` etc.) or raw ``health`` attrs.
        inventory: Optional InventoryManager; when provided, the consumed unit
            is removed from it (and condition decremented on the instance).
        consume_stack: If True, remove one unit from the inventory stack.

    Returns:
        ``{"success": bool, "message": str, "changes": {vital: delta},
           "skill_buffs": {...}, "consumed": bool}``.
    """
    effect = get_consumable_effect(item_id)
    if effect is None:
        return {
            "success": False,
            "message": f"{item_id} is not consumable.",
            "changes": {},
            "skill_buffs": {},
            "consumed": False,
        }

    changes = _apply_vitals(player_state, effect)
    skill_buffs = dict(effect.get("skill_buffs", {}))

    consumed = False
    if inventory is not None and consume_stack:
        # Decrement condition on the live instance before removal (so a future
        # config that keeps multi-use consumables still reflects wear).
        if bool(_cfg("decrement_condition_on_use", True)):
            loss = int(_cfg("condition_loss_per_use", 0))
            if loss > 0:
                item = inventory.get_item(item_id)
                if item is not None:
                    item.condition = max(0, item.condition - loss)
        consumed = inventory.remove_item(item_id, quantity=1)

    logger.info(
        "[equipment_effects] Consumable applied (operation=consume, item=%s): %s buffs=%s consumed=%s",
        item_id,
        changes,
        skill_buffs,
        consumed,
    )
    return {
        "success": True,
        "message": effect.get("message", f"Used {item_id}."),
        "changes": changes,
        "skill_buffs": skill_buffs,
        "consumed": consumed,
    }


def _apply_vitals(player_state: Any, effect: Dict[str, Any]) -> Dict[str, int]:
    """Apply vital deltas from *effect* to *player_state*, returning the changes.

    Each vital is applied through the most appropriate mutator available:
        * a delta mutator (``adjust_*`` / ``add_*``) if present — preferred,
          since these clamp and persist; otherwise
        * an absolute setter (``set_*``) fed ``current + delta``; otherwise
        * raw attribute assignment (for duck-typed mocks in tests).

    PlayerState exposes ``adjust_health``/``adjust_heat`` (delta) but only
    ``set_energy``/``set_hunger`` (absolute) with read-only properties, so the
    set-with-current path is the real workhorse for energy/hunger.

    Args:
        player_state: PlayerState-like target.
        effect: Effect dict possibly containing health/energy/hunger/heat.

    Returns:
        Mapping of vital → applied delta (only for vitals present in *effect*).
    """
    changes: Dict[str, int] = {}

    # Per vital: (effect_key, [delta methods], [absolute setters], attr).
    plan = [
        ("health", ["adjust_health", "add_health"], ["set_health"], "health"),
        ("energy", ["adjust_energy", "add_energy"], ["set_energy"], "energy"),
        ("hunger", ["adjust_hunger", "add_hunger"], ["set_hunger"], "hunger"),
        ("heat", ["add_heat", "adjust_heat"], ["set_heat"], "heat"),
    ]

    for key, delta_methods, set_methods, attr in plan:
        if key not in effect:
            continue
        delta = int(effect[key])
        if _apply_one_vital(player_state, key, delta, delta_methods, set_methods, attr):
            changes[key] = delta

    # Persist if the object exposes a save hook.
    saver = getattr(player_state, "_save", None) or getattr(player_state, "save_to_file", None)
    if callable(saver):
        try:
            saver()
        except Exception:  # pragma: no cover - persistence best-effort
            pass

    return changes


def _apply_one_vital(
    player_state: Any,
    key: str,
    delta: int,
    delta_methods: List[str],
    set_methods: List[str],
    attr: str,
) -> bool:
    """Apply a single vital *delta*, trying mutators in priority order.

    Returns:
        True if the change was applied by any path.
    """
    # 1. Delta mutator (clamps + persists internally).
    for method_name in delta_methods:
        method = getattr(player_state, method_name, None)
        if callable(method):
            try:
                method(delta, reason=f"consumable:{key}")
            except TypeError:
                method(delta)
            return True

    # 2. Absolute setter fed current + delta.
    for method_name in set_methods:
        method = getattr(player_state, method_name, None)
        if callable(method):
            current = int(getattr(player_state, attr, 0) or 0)
            try:
                method(current + delta, reason=f"consumable:{key}")
            except TypeError:
                method(current + delta)
            return True

    # 3. Raw attribute fallback (clamped 0–100) for minimal/mock objects.
    try:
        current = int(getattr(player_state, attr, 0) or 0)
        setattr(player_state, attr, max(0, min(100, current + delta)))
        return True
    except Exception:  # pragma: no cover - last-resort defensive
        return False
