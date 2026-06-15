"""Phone-OS upgrade skills (PH-T2) — buy/skill-install phone software & hardware.

Exposes two ``@skill(pack="phone")`` callables for the agent and the PH-T5 UI:

* :func:`install_phone_upgrade` — install a phone-OS upgrade onto a phone record.
  Gating is layered: if the player OWNS the item it is consumed; otherwise the
  player must PAY its credit price; otherwise, for upgrades that declare a
  ``skill_check``, a high-enough skill lets them self-mod the upgrade for free.
  The actual phone-record mutation goes through :class:`PhoneOS` / PhoneDB
  (``add_installed_app`` for the effect id + the upgrade's ``add_app``, and
  ``set_phone_fields`` for an ``os_version`` bump). Idempotent: installing an
  already-installed upgrade does NOT re-charge or re-stack.
* :func:`list_phone_upgrades` — the available upgrade catalog (id, name, price,
  effects, owned flag) plus the target phone's current derived stats, for the UI.

Effect magnitudes are NOT declared here. They are the single source of truth on
each upgrade item in :data:`engine.world.inventory.ITEM_CATALOG`
(``phone_upgrade`` block); :mod:`engine.world.phone_os` derives the same numbers.

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — PH-T2: initial install/list phone-upgrade skills.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────


def _apply_upgrade_effect(
    char_id: str, item_id: str, meta: Dict[str, Any]
) -> Dict[str, Any]:
    """Mutate *char_id*'s phone record to apply *item_id*'s declared effect.

    The effect comes from the catalog ``phone_upgrade`` block (single source of
    truth). The upgrade's effect is realised by installing its ``item_id`` into
    ``installed_apps`` (so :class:`PhoneOS` derives the stat deltas), installing
    any ``add_app`` it enables, and bumping ``os_version`` if declared.

    Args:
        char_id: The phone owner (``'user'`` for the player).
        item_id: The upgrade item id (also the installed-effect id).
        meta: The catalog metadata for *item_id*.

    Returns:
        The updated phone record dict.
    """
    from engine.world.phone_os import get_phone_os

    pos = get_phone_os()
    db = pos._get_db()  # PhoneDB-like backing store
    upgrade = meta.get("phone_upgrade") or {}

    db.add_installed_app(char_id, item_id)
    add_app = upgrade.get("add_app")
    if add_app:
        db.add_installed_app(char_id, add_app)
    os_version = upgrade.get("os_version")
    if os_version:
        db.set_phone_fields(char_id, os_version=os_version)
    return db.get_phone(char_id)


# ── skills ───────────────────────────────────────────────────────────────────


@skill(
    pack="phone",
    tags=["phone", "upgrade", "hacking", "shop"],
    category=SkillCategory.SYSTEM,
    description="Install a phone-OS upgrade (software/hardware) onto a phone.",
)
def install_phone_upgrade(item_id: str = "", target: str = "user") -> str:
    """Install a phone-OS upgrade onto *target*'s phone.

    Gating order:
        1. If the player already owns *item_id*, it is consumed.
        2. Else the player pays the item's credit price.
        3. Else, if the upgrade declares a ``skill_check`` and the player meets
           the required skill level, it is self-modded for free.
        4. Otherwise the install is refused.

    Idempotent: if the upgrade is already installed on *target*, no item is
    consumed, no credits are charged, and the phone is left unchanged.

    Args:
        item_id: The phone-upgrade item id (see
            :func:`engine.world.inventory.get_phone_upgrades`).
        target: The phone owner to install onto. Defaults to ``'user'``.

    Returns:
        A JSON string result dict with ``success`` and, on success,
        ``before`` / ``after`` derived stats, the ``method`` used
        (``owned`` / ``bought`` / ``skill_check``), and ``credits_left``.
    """
    if not item_id:
        return json.dumps({"success": False, "error": "Provide an item_id."})
    try:
        from engine.world.inventory import get_inventory, get_phone_upgrade
        from engine.world.phone_os import get_phone_os
        from engine.world.player_state import get_player_state

        meta = get_phone_upgrade(item_id)
        if meta is None:
            logger.error(
                "[phone_upgrade] unknown upgrade refused "
                "(operation=install_phone_upgrade, item_id=%s)", item_id,
            )
            return json.dumps(
                {"success": False, "error": f"Unknown phone upgrade: {item_id}"}
            )

        pos = get_phone_os()
        inv = get_inventory()
        ps = get_player_state()

        # Idempotency: already installed → no-op (don't re-charge / re-stack).
        rec = pos.get_phone(target)
        if item_id in (rec.get("installed_apps") or []):
            logger.info(
                "[phone_upgrade] already installed, no-op "
                "(operation=install_phone_upgrade, item_id=%s, target=%s)",
                item_id, target,
            )
            return json.dumps({
                "success": True,
                "already_installed": True,
                "item_id": item_id,
                "target": target,
                "stats": pos.stats(target),
                "message": f"{meta['name']} is already installed.",
            })

        before = pos.stats(target)
        price = int(meta.get("price", 0))
        skill_req = meta.get("skill_check") or {}

        # ── gating ──────────────────────────────────────────────────────────
        method: Optional[str] = None
        if inv.has_item(item_id):
            inv.remove_item(item_id, quantity=1)
            method = "owned"
        elif ps.credits >= price:
            ps.spend_credits(price, f"phone_upgrade:{item_id}")
            method = "bought"
        elif skill_req and ps.get_skill(
            skill_req.get("skill", "")
        ) >= int(skill_req.get("level", 99)):
            method = "skill_check"
        else:
            need_skill = (
                f" or {skill_req['skill']} level {skill_req['level']}"
                if skill_req else ""
            )
            logger.info(
                "[phone_upgrade] install gated — cannot afford/lacks item "
                "(operation=install_phone_upgrade, item_id=%s, target=%s)",
                item_id, target,
            )
            return json.dumps({
                "success": False,
                "error": (
                    f"Cannot install {meta['name']}: need the item, "
                    f"₵{price} credits{need_skill}."
                ),
                "credits": ps.credits,
            })

        after_rec = _apply_upgrade_effect(target, item_id, meta)
        after = pos.stats(target)
        logger.info(
            "[phone_upgrade] installed "
            "(operation=install_phone_upgrade, item_id=%s, target=%s, "
            "method=%s, sec=%d->%d, slots=%d->%d)",
            item_id, target, method,
            before["effective_security"], after["effective_security"],
            before["app_slots"], after["app_slots"],
        )
        return json.dumps({
            "success": True,
            "item_id": item_id,
            "name": meta["name"],
            "target": target,
            "method": method,
            "before": before,
            "after": after,
            "installed_apps": after_rec.get("installed_apps", []),
            "os_version": after_rec.get("os_version"),
            "credits_left": ps.credits,
        })
    except Exception as exc:
        logger.error(
            "[phone_upgrade] install failed "
            "(operation=install_phone_upgrade, item_id=%s, target=%s): %s",
            item_id, target, exc,
        )
        return json.dumps({"success": False, "error": str(exc)})


@skill(
    pack="phone",
    tags=["phone", "upgrade", "shop"],
    category=SkillCategory.SYSTEM,
    description="List available phone-OS upgrades with prices and current stats.",
)
def list_phone_upgrades(target: str = "user") -> str:
    """Return the phone-upgrade catalog plus *target*'s current derived stats.

    Args:
        target: The phone owner to report current stats for. Defaults to
            ``'user'``.

    Returns:
        A JSON string with an ``upgrades`` list (id, name, category, price,
        effects, ``add_app``, ``os_version``, ``owned``, ``installed``) and the
        target's current ``stats``.
    """
    try:
        from engine.world.inventory import get_inventory, get_phone_upgrades
        from engine.world.phone_os import get_phone_os

        pos = get_phone_os()
        inv = get_inventory()
        rec = pos.get_phone(target)
        installed = set(rec.get("installed_apps") or [])

        upgrades = []
        for iid, meta in get_phone_upgrades().items():
            up = meta.get("phone_upgrade") or {}
            upgrades.append({
                "item_id": iid,
                "name": meta.get("name", iid),
                "category": meta.get("category", "misc"),
                "rarity": meta.get("rarity", "common"),
                "desc": meta.get("desc", ""),
                "price": int(meta.get("price", 0)),
                "effects": dict(up.get("effects") or {}),
                "add_app": up.get("add_app"),
                "os_version": up.get("os_version"),
                "skill_check": meta.get("skill_check"),
                "owned": inv.has_item(iid),
                "installed": iid in installed,
            })
        return json.dumps({
            "target": target,
            "stats": pos.stats(target),
            "upgrades": upgrades,
            "total": len(upgrades),
        }, indent=2)
    except Exception as exc:
        logger.error(
            "[phone_upgrade] list failed "
            "(operation=list_phone_upgrades, target=%s): %s", target, exc,
        )
        return json.dumps({"success": False, "error": str(exc)})
