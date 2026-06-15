"""Unit tests for phone-OS upgrades (PH-T2).

Covers the install/list upgrade skills and the single-source-of-truth contract:

* Installing a security patch raises ``effective_security``; a CPU upgrade raises
  ``app_slots`` — by exactly the amount the catalog declares (consistency between
  the inventory catalog and the PhoneOS derivation).
* Install consumes an owned item (no credits spent) OR deducts credits when not
  owned; the chosen ``method`` is reported.
* Gating: with neither the item nor enough credits (and no passing skill check),
  the install is refused and nothing is mutated.
* The ``skill_check`` self-mod path installs for free when the player's skill is
  high enough.
* Installing an unknown item errors gracefully (no exception).
* Idempotency: re-installing an already-installed upgrade neither re-charges nor
  re-stacks.

All tests mock at the boundary: an isolated temp PhoneDB is injected into the
PhoneOS singleton, and fake Inventory / PlayerState objects stand in for the
real singletons so no real save files are touched and no services are needed.

Version: v1.62.0 [2026-06-15]
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from content.scenes.phone.phone_db import PhoneDB
from engine.world.inventory import get_phone_upgrade
from engine.world.phone_os import PhoneOS, PLAYER_ID
import content.scenes.phone.phone_upgrade_skills as ups
import engine.world.phone_os as phone_os_mod


# ── fakes ───────────────────────────────────────────────────────────────────


class FakeInventory:
    """Minimal InventoryManager stand-in tracking owned item counts."""

    def __init__(self, owned: Optional[Dict[str, int]] = None) -> None:
        self.owned: Dict[str, int] = dict(owned or {})
        self.added: List[str] = []

    def has_item(self, item_id: str, quantity: int = 1) -> bool:
        return self.owned.get(item_id, 0) >= quantity

    def remove_item(self, item_id: str, quantity: int = 1) -> bool:
        if self.owned.get(item_id, 0) < quantity:
            return False
        self.owned[item_id] -= quantity
        return True

    def add_item(self, item_id: str, quantity: int = 1, **_: Any) -> None:
        self.owned[item_id] = self.owned.get(item_id, 0) + quantity
        self.added.append(item_id)


class FakePlayerState:
    """Minimal PlayerState stand-in for credits + skills."""

    def __init__(self, credits: int = 0, skills: Optional[Dict[str, int]] = None) -> None:
        self.credits = credits
        self._skills = dict(skills or {})
        self.spent: List[int] = []

    def spend_credits(self, amount: int, reason: str = "") -> Optional[int]:
        if self.credits < amount:
            return None
        self.credits -= amount
        self.spent.append(amount)
        return self.credits

    def get_skill(self, skill: str) -> int:
        return self._skills.get(skill, 0)


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Wire isolated PhoneDB + fake inventory/player into the skill module.

    Yields a ``(pos, inv, ps)`` tuple. The PhoneOS singleton used by the skills
    is replaced with one backed by a temp DB; ``get_inventory`` /
    ``get_player_state`` are patched where the skill module imports them.
    """
    db = PhoneDB(tmp_path / "upgrades_test.db")
    pos = PhoneOS(db=db)

    inv = FakeInventory()
    ps = FakePlayerState()

    monkeypatch.setattr(phone_os_mod, "get_phone_os", lambda: pos)
    monkeypatch.setattr("engine.world.inventory.get_inventory", lambda: inv)
    monkeypatch.setattr("engine.world.player_state.get_player_state", lambda: ps)
    return pos, inv, ps


# ── single source of truth ──────────────────────────────────────────────────


def test_security_patch_raises_effective_security_by_catalog_amount(env) -> None:
    pos, inv, ps = env
    inv.owned["phone_encryption_patch"] = 1
    declared = get_phone_upgrade("phone_encryption_patch")["phone_upgrade"]["effects"]["security"]

    before = pos.effective_security(PLAYER_ID)
    res = json.loads(ups.install_phone_upgrade("phone_encryption_patch", PLAYER_ID))
    assert res["success"] is True
    after = pos.effective_security(PLAYER_ID)
    assert after == before + declared  # derivation == catalog single source


def test_cpu_upgrade_raises_app_slots_by_catalog_amount(env) -> None:
    pos, inv, ps = env
    inv.owned["phone_cpu_v2"] = 1
    declared = get_phone_upgrade("phone_cpu_v2")["phone_upgrade"]["effects"]["app_slots"]

    before = pos.app_slots(PLAYER_ID)
    res = json.loads(ups.install_phone_upgrade("phone_cpu_v2", PLAYER_ID))
    assert res["success"] is True
    assert pos.app_slots(PLAYER_ID) == before + declared


# ── consumption / payment ───────────────────────────────────────────────────


def test_install_consumes_owned_item_without_charging(env) -> None:
    pos, inv, ps = env
    inv.owned["phone_firewall_v1"] = 1
    ps.credits = 10_000

    res = json.loads(ups.install_phone_upgrade("phone_firewall_v1", PLAYER_ID))
    assert res["success"] is True
    assert res["method"] == "owned"
    assert inv.owned["phone_firewall_v1"] == 0  # consumed
    assert ps.spent == []                        # not charged


def test_install_deducts_credits_when_not_owned(env) -> None:
    pos, inv, ps = env
    price = get_phone_upgrade("phone_firewall_v1")["price"]
    ps.credits = price + 500

    res = json.loads(ups.install_phone_upgrade("phone_firewall_v1", PLAYER_ID))
    assert res["success"] is True
    assert res["method"] == "bought"
    assert ps.credits == 500
    assert res["credits_left"] == 500


# ── gating ──────────────────────────────────────────────────────────────────


def test_install_refused_without_item_and_without_credits(env) -> None:
    pos, inv, ps = env
    ps.credits = 0  # broke, owns nothing

    before = pos.stats(PLAYER_ID)
    res = json.loads(ups.install_phone_upgrade("phone_firewall_v2", PLAYER_ID))
    assert res["success"] is False
    assert "Cannot install" in res["error"]
    # Nothing mutated.
    assert pos.stats(PLAYER_ID) == before
    assert "phone_firewall_v2" not in (pos.get_phone(PLAYER_ID)["installed_apps"])


def test_skill_check_self_mod_installs_for_free(env) -> None:
    pos, inv, ps = env
    ps.credits = 0  # cannot pay
    req = get_phone_upgrade("phone_ice_v1")["skill_check"]
    ps._skills[req["skill"]] = req["level"]  # meets the check exactly

    before = pos.hack_power(PLAYER_ID)
    res = json.loads(ups.install_phone_upgrade("phone_ice_v1", PLAYER_ID))
    assert res["success"] is True
    assert res["method"] == "skill_check"
    assert ps.spent == []
    declared = get_phone_upgrade("phone_ice_v1")["phone_upgrade"]["effects"]["hack_power"]
    assert pos.hack_power(PLAYER_ID) == before + declared


def test_unknown_item_errors_gracefully(env) -> None:
    res = json.loads(ups.install_phone_upgrade("not_a_real_upgrade", PLAYER_ID))
    assert res["success"] is False
    assert "Unknown phone upgrade" in res["error"]


# ── idempotency + os bump + add_app ─────────────────────────────────────────


def test_idempotent_reinstall_does_not_recharge_or_restack(env) -> None:
    pos, inv, ps = env
    price = get_phone_upgrade("phone_firewall_v1")["price"]
    ps.credits = price * 3

    first = json.loads(ups.install_phone_upgrade("phone_firewall_v1", PLAYER_ID))
    assert first["success"] is True
    spent_after_first = list(ps.spent)
    stats_after_first = pos.stats(PLAYER_ID)

    second = json.loads(ups.install_phone_upgrade("phone_firewall_v1", PLAYER_ID))
    assert second["success"] is True
    assert second.get("already_installed") is True
    assert ps.spent == spent_after_first              # not re-charged
    assert pos.stats(PLAYER_ID) == stats_after_first  # not re-stacked
    apps = pos.get_phone(PLAYER_ID)["installed_apps"]
    assert apps.count("phone_firewall_v1") == 1


def test_kernel_upgrade_bumps_os_version_and_adds_all_round(env) -> None:
    pos, inv, ps = env
    inv.owned["phone_os_kernel_v2"] = 1

    res = json.loads(ups.install_phone_upgrade("phone_os_kernel_v2", PLAYER_ID))
    assert res["success"] is True
    rec = pos.get_phone(PLAYER_ID)
    assert rec["os_version"] == "NeonOS 2.0"


def test_comms_tap_enables_intercept_app(env) -> None:
    pos, inv, ps = env
    inv.owned["phone_comms_tap"] = 1

    res = json.loads(ups.install_phone_upgrade("phone_comms_tap", PLAYER_ID))
    assert res["success"] is True
    apps = pos.get_phone(PLAYER_ID)["installed_apps"]
    assert "intercept" in apps


# ── list skill ──────────────────────────────────────────────────────────────


def test_list_phone_upgrades_reports_catalog_and_stats(env) -> None:
    pos, inv, ps = env
    inv.owned["phone_cpu_v2"] = 1

    data = json.loads(ups.list_phone_upgrades(PLAYER_ID))
    assert data["total"] >= 1
    ids = {u["item_id"] for u in data["upgrades"]}
    assert "phone_cpu_v2" in ids and "phone_encryption_patch" in ids
    cpu = next(u for u in data["upgrades"] if u["item_id"] == "phone_cpu_v2")
    assert cpu["owned"] is True
    assert cpu["effects"]["app_slots"] == 3
    assert "effective_security" in data["stats"]
