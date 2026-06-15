"""
Market world-event & territory-pricing tests (v1.60.0)
======================================================

Verifies the "Living Systems" economy feedback loop wired in v1.60.0:

* ``Market.apply_event`` moves supply/demand for the right categories and
  normalises scene-vocabulary event types (gang_war → war, etc.).
* ``Market.subscribe_to_world_events`` makes world events published on the
  EventBus actually drive market shocks (the audit gap).
* ``Market.refresh_territory_multipliers`` feeds faction control into
  specialty-good pricing.
* Configurable shock scale (``economy.event_shocks.scale``) is honoured.
* The pre-existing v1.59 buy/sell settlement path is preserved.

Tests are HERMETIC: each builds a *fresh* ``Market`` whose save-path points at
a tmp file (no shared ``data/market_state.json``), wires it to a *fresh*
``EventBus`` instance, and disables credit/inventory settlement so no global
player/inventory singletons are touched.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team
"""
from __future__ import annotations

from typing import Dict

import pytest

from engine.events.event_bus import EventBus
from engine.world import market as market_mod
from engine.world.market import Market, WORLD_EVENT_MARKET_MAP, GoodCategory


# ──── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_market(tmp_path, monkeypatch) -> Market:
    """A fully isolated Market: tmp save-path, no settlement, no persistence."""
    # Point persistence at a throwaway file so no shared state leaks in/out.
    monkeypatch.setattr(Market, "_SAVE_PATH", tmp_path / "market_state.json")
    # Disable settlement so buy/sell never touch player/inventory singletons.
    monkeypatch.setattr(
        Market, "_economy_cfg",
        staticmethod(lambda: {"settle": False, "heat_per_unit": 0,
                              "sell_to_inventory": False}),
    )
    mkt = Market()  # seeds fresh from catalog (tmp file does not exist yet)
    return mkt


@pytest.fixture
def fresh_bus(monkeypatch) -> EventBus:
    """A fresh EventBus wired into the market module (no Nexus persistence)."""
    bus = EventBus()
    monkeypatch.setattr(bus, "_persist_to_nexus", lambda event: None)
    monkeypatch.setattr(market_mod, "_get_event_bus", lambda: bus)
    monkeypatch.setattr(market_mod, "_HAS_BUS", True)
    return bus


def _avg(mkt: Market, category: str, attr: str) -> float:
    """Mean supply/demand for a category."""
    vals = [getattr(g, attr) for g in mkt._goods.values() if g.category == category]
    return sum(vals) / len(vals) if vals else 0.0


# ──── apply_event ────────────────────────────────────────────────────────────


def test_apply_event_war_raises_weapon_demand(fresh_market):
    before = _avg(fresh_market, "weapons", "demand")
    res = fresh_market.apply_event("war")
    after = _avg(fresh_market, "weapons", "demand")

    assert res["status"] == "ok"
    assert res["applied"] is True
    assert "weapons" in res["categories"]
    assert after > before  # war drives weapon demand up


def test_apply_event_festival_raises_luxury_demand(fresh_market):
    before = _avg(fresh_market, "luxury", "demand")
    fresh_market.apply_event("festival")
    assert _avg(fresh_market, "luxury", "demand") > before


def test_apply_event_shortage_drops_consumable_supply(fresh_market):
    before = _avg(fresh_market, "consumables", "supply")
    fresh_market.apply_event("shortage")
    assert _avg(fresh_market, "consumables", "supply") < before


def test_apply_event_maps_scene_vocabulary(fresh_market):
    """gang_war must behave exactly like the canonical 'war'."""
    assert WORLD_EVENT_MARKET_MAP["gang_war"] == "war"
    before = _avg(fresh_market, "weapons", "demand")
    res = fresh_market.apply_event("gang_war")
    assert res["event_type"] == "war"  # normalised
    assert _avg(fresh_market, "weapons", "demand") > before


def test_apply_event_unknown_is_ignored(fresh_market):
    res = fresh_market.apply_event("totally_unknown_event")
    assert res["applied"] is False
    assert res["status"] == "ignored"


def test_apply_event_moves_price(fresh_market):
    """A demand shock must actually change a good's current_price."""
    weapon = next(g for g in fresh_market._goods.values() if g.category == "weapons")
    p0 = weapon.current_price
    fresh_market.apply_event("war", magnitude=2.0)
    assert weapon.current_price > p0


# ──── Configurable shock magnitude ───────────────────────────────────────────


def test_shock_scale_config_amplifies(fresh_market, monkeypatch):
    """economy.event_shocks.scale multiplies the applied magnitude."""
    # scale 0 → no movement at all
    monkeypatch.setattr(Market, "_event_shock_scale", staticmethod(lambda: 0.0))
    before = _avg(fresh_market, "weapons", "demand")
    fresh_market.apply_event("war")
    assert _avg(fresh_market, "weapons", "demand") == pytest.approx(before)

    # scale 3 → larger movement than scale 1
    monkeypatch.setattr(Market, "_event_shock_scale", staticmethod(lambda: 1.0))
    fresh_market.apply_event("war")
    delta_1x = _avg(fresh_market, "weapons", "demand") - before

    fresh_market.reset()  # back to clean baseline
    before2 = _avg(fresh_market, "weapons", "demand")
    monkeypatch.setattr(Market, "_event_shock_scale", staticmethod(lambda: 3.0))
    fresh_market.apply_event("war")
    delta_3x = _avg(fresh_market, "weapons", "demand") - before2

    assert delta_3x > delta_1x


# ──── EventBus wiring ────────────────────────────────────────────────────────


def test_subscribe_is_idempotent(fresh_market, fresh_bus):
    ids1 = fresh_market.subscribe_to_world_events()
    ids2 = fresh_market.subscribe_to_world_events()
    assert ids1 == ids2
    assert len(ids1) > 0


def test_world_event_on_bus_drives_market(fresh_market, fresh_bus):
    """Publishing a world event must shock the market via the subscription."""
    fresh_market.subscribe_to_world_events()
    before = _avg(fresh_market, "weapons", "demand")

    fresh_bus.publish(
        "world.major_event",
        {"event_type": "gang_war", "intensity": 2.0, "title": "Gang War"},
        scene="neoncity",
    )

    assert _avg(fresh_market, "weapons", "demand") > before


def test_world_event_uses_world_event_type_key(fresh_market, fresh_bus):
    """world_sim publishes 'world_event_type' too — both keys must work."""
    fresh_market.subscribe_to_world_events()
    before = _avg(fresh_market, "luxury", "demand")
    fresh_bus.publish(
        "world.major_event",
        {"world_event_type": "festival", "intensity": 1.5},
    )
    assert _avg(fresh_market, "luxury", "demand") > before


def test_unsubscribe_stops_reactions(fresh_market, fresh_bus):
    fresh_market.subscribe_to_world_events()
    fresh_market.unsubscribe_from_world_events()
    before = _avg(fresh_market, "weapons", "demand")
    fresh_bus.publish("world.major_event", {"event_type": "war"})
    assert _avg(fresh_market, "weapons", "demand") == pytest.approx(before)


def test_disabled_config_skips_subscription(fresh_market, fresh_bus, monkeypatch):
    monkeypatch.setattr(Market, "_world_events_enabled", staticmethod(lambda: False))
    ids = fresh_market.subscribe_to_world_events()
    assert ids == []


# ──── Territory pricing ──────────────────────────────────────────────────────


def test_refresh_territory_with_explicit_control(fresh_market):
    """Dominant faction makes its specialty goods cheaper (<1.0 multiplier)."""
    # OmniCorp specialises in tech+luxury; 90% control in DOWNTOWN.
    control: Dict[str, Dict[str, float]] = {"DOWNTOWN": {"OmniCorp": 90.0, "NeoTech": 10.0}}
    active = fresh_market.refresh_territory_multipliers(control)

    assert "DOWNTOWN" in active
    mults = active["DOWNTOWN"]
    assert mults["tech"] < 1.0     # specialty → cheaper
    assert mults["luxury"] < 1.0
    # A non-specialty category at high control gets nudged up.
    assert mults["consumables"] >= 1.0


def test_territory_modifier_changes_shop_price(fresh_market):
    """Territory control must flow into the quoted shop price."""
    prices_before = {
        p["good_id"]: p["shop_price"]
        for p in fresh_market.get_prices("DOWNTOWN", category="tech")
    }
    fresh_market.refresh_territory_multipliers(
        {"DOWNTOWN": {"OmniCorp": 95.0}}
    )
    prices_after = {
        p["good_id"]: p["shop_price"]
        for p in fresh_market.get_prices("DOWNTOWN", category="tech")
    }
    assert prices_before, "expected tech goods in DOWNTOWN"
    # At least one tech good should now be cheaper under OmniCorp dominance.
    assert any(prices_after[g] < prices_before[g] for g in prices_before)


def test_refresh_territory_fetches_live_when_omitted(fresh_market, monkeypatch):
    """With no arg, it pulls get_all_control() from the territory manager."""
    class _FakeTM:
        def get_all_control(self) -> Dict[str, Dict[str, float]]:
            return {"HIGHRISE": {"OmniCorp": 80.0}}

    import engine.world.territory as territory_mod
    monkeypatch.setattr(territory_mod, "get_territory_manager", lambda: _FakeTM())

    active = fresh_market.refresh_territory_multipliers()
    assert "HIGHRISE" in active
    assert active["HIGHRISE"]["tech"] < 1.0  # OmniCorp specialty


def test_faction_shift_event_refreshes_territory(fresh_market, fresh_bus, monkeypatch):
    class _FakeTM:
        def get_all_control(self) -> Dict[str, Dict[str, float]]:
            return {"DOWNTOWN": {"OmniCorp": 88.0}}

    import engine.world.territory as territory_mod
    monkeypatch.setattr(territory_mod, "get_territory_manager", lambda: _FakeTM())

    fresh_market.subscribe_to_world_events()
    fresh_bus.publish("neoncity.faction_shift", {"faction": "OmniCorp"})

    mod = fresh_market._get_territory_modifier("DOWNTOWN", "tech")
    assert mod < 1.0


# ──── Settlement preservation (v1.59 regression guard) ───────────────────────


def test_settlement_path_preserved(tmp_path, monkeypatch):
    """With settlement enabled, buy() still rejects an unaffordable purchase
    via the v1.59 _settle_buy path (proving it was not removed)."""
    monkeypatch.setattr(Market, "_SAVE_PATH", tmp_path / "market_state.json")

    class _BrokePS:
        credits = 0
        def spend_credits(self, total, reason=""):
            return None  # never affordable

    import engine.world.player_state as ps_mod
    import engine.world.inventory as inv_mod
    monkeypatch.setattr(ps_mod, "get_player_state", lambda: _BrokePS())
    monkeypatch.setattr(inv_mod, "get_inventory", lambda: object())
    # Force settlement ON regardless of real config.
    monkeypatch.setattr(
        Market, "_economy_cfg",
        staticmethod(lambda: {"settle": True, "heat_per_unit": 0,
                              "sell_to_inventory": True}),
    )
    mkt = Market()
    # DOWNTOWN/neon_arms sells weapons+tech.
    res = mkt.buy("DOWNTOWN", "street_pistol", quantity=1)
    assert res["status"] == "error"
    assert res["reason"] == "insufficient_credits"
