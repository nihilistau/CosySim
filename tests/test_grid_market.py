"""Tests for THE GRID → engine-Market adapter (v1.63.0 — D-T1 "The Exchange").

Verifies that THE GRID surfaces the *live* engine economy
(``engine.world.market.get_market``) rather than a parallel price book:

* prices/goods come from ``Market.get_prices``;
* buy/sell route through ``Market.buy``/``Market.sell``;
* the ▲/▼ trend is derived from successive reads;
* a Market failure degrades gracefully (Grid still renders, never raises);
* PH-T2 phone-upgrade specials are preserved on the Grid-vendor path.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def grid_state():
    """Return a fresh _GridState with the engine-Market singleton reset."""
    import content.scenes.grid.grid_scene as gs_mod
    gs_mod._grid_state_instance = None
    return gs_mod._get_grid_state()


def _fake_prices(price_pistol: int = 275, price_stim: int = 55) -> List[Dict[str, Any]]:
    """Return a minimal get_prices()-shaped payload."""
    return [
        {"good_id": "street_pistol", "name": "Street Pistol", "category": "weapons",
         "base_price": 250, "current_price": price_pistol, "shop_price": price_pistol,
         "shop_id": "neon_arms", "shop_name": "Neon Arms", "district": "DOWNTOWN",
         "supply": 50.0, "demand": 55.0, "illegal": False, "rarity": 1},
        {"good_id": "stim_pack", "name": "Stim Pack", "category": "consumables",
         "base_price": 50, "current_price": price_stim, "shop_price": price_stim,
         "shop_id": "velvet_boutique", "shop_name": "Velvet Boutique", "district": "DOWNTOWN",
         "supply": 50.0, "demand": 55.0, "illegal": False, "rarity": 1},
    ]


def _patch_market(mock_market: MagicMock):
    """Patch engine.world.market.get_market to return mock_market."""
    return patch("engine.world.market.get_market", return_value=mock_market)


# ── Prices come from the engine Market ───────────────────────────────────────

def test_market_items_come_from_engine_market(grid_state):
    """get_market_items surfaces engine-Market prices (not a local book)."""
    mkt = MagicMock()
    mkt.get_prices.return_value = _fake_prices(price_pistol=300, price_stim=60)
    with _patch_market(mkt):
        items = grid_state.get_market_items()

    mkt.get_prices.assert_called_once()
    by_id = {i["id"]: i for i in items if i.get("source") == "engine_market"}
    assert by_id["street_pistol"]["price"] == 300
    assert by_id["stim_pack"]["price"] == 60
    # categories are mapped onto Grid vendor NPCs
    assert by_id["street_pistol"]["vendor"] == "viktor"   # weapons -> viktor
    assert by_id["stim_pack"]["vendor"] == "frankie"      # consumables -> frankie
    # int rarity is mapped to a CSS rarity name
    assert by_id["street_pistol"]["rarity"] == "common"


def test_market_items_use_configured_district(grid_state):
    """The adapter reads the district from config (scenes.grid.market_district)."""
    mkt = MagicMock()
    mkt.get_prices.return_value = _fake_prices()
    cfg = MagicMock()
    cfg.get.return_value = "UNDERWORLD"
    with _patch_market(mkt), patch("engine.config.get_config", return_value=cfg):
        grid_state.get_market_items()
    mkt.get_prices.assert_called_once_with("UNDERWORLD")


# ── Trend (▲/▼) is derived from successive reads ─────────────────────────────

def test_price_trend_rises_and_falls(grid_state):
    """A higher then lower price across reads yields rising then falling."""
    mkt = MagicMock()
    with _patch_market(mkt):
        mkt.get_prices.return_value = _fake_prices(price_pistol=275)
        first = {i["id"]: i for i in grid_state.get_market_items()}
        assert first["street_pistol"]["trend"] == "stable"  # no prior snapshot

        mkt.get_prices.return_value = _fake_prices(price_pistol=320)
        second = {i["id"]: i for i in grid_state.get_market_items()}
        assert second["street_pistol"]["trend"] == "rising"

        mkt.get_prices.return_value = _fake_prices(price_pistol=290)
        third = {i["id"]: i for i in grid_state.get_market_items()}
        assert third["street_pistol"]["trend"] == "falling"


# ── Buy/sell route through the engine Market ─────────────────────────────────

def test_buy_routes_through_engine_market(grid_state):
    """buy_item calls Market.buy and reports the engine settlement."""
    mkt = MagicMock()
    mkt.get_good.return_value = {"category": "weapons"}
    mkt.buy.return_value = {
        "status": "ok", "good_id": "street_pistol", "good_name": "Street Pistol",
        "quantity": 2, "unit_price": 300, "total": 600, "balance": 9400,
        "shop": "Neon Arms", "illegal": False,
    }
    with _patch_market(mkt):
        result = grid_state.buy_item("street_pistol", 2)

    assert mkt.buy.call_args.args[1] == "street_pistol"   # good_id
    assert mkt.buy.call_args.kwargs.get("quantity") == 2
    assert result["success"] is True
    assert result["paid"] == 600
    assert result["balance"] == 9400
    assert result["source"] == "engine_market"


def test_sell_routes_through_engine_market(grid_state):
    """sell_item calls Market.sell and reports proceeds."""
    mkt = MagicMock()
    mkt.get_good.return_value = {"category": "weapons"}
    mkt.sell.return_value = {
        "status": "ok", "good_id": "street_pistol", "good_name": "Street Pistol",
        "quantity": 1, "unit_price": 180, "total": 180, "balance": 9580,
    }
    with _patch_market(mkt):
        result = grid_state.sell_item("street_pistol", 1)

    mkt.sell.assert_called_once()
    assert result["success"] is True
    assert result["earned"] == 180
    assert result["balance"] == 9580


def test_buy_insufficient_credits_surfaces_engine_error(grid_state):
    """An engine-side rejection (insufficient credits) maps to a Grid error."""
    mkt = MagicMock()
    mkt.get_good.return_value = {"category": "weapons"}
    mkt.buy.return_value = {"status": "error", "reason": "insufficient_credits",
                            "needed": 600, "balance": 100}
    with _patch_market(mkt):
        result = grid_state.buy_item("street_pistol", 2)
    assert result["success"] is False
    assert "Insufficient credits" in result["error"]


# ── Graceful degradation — never 500 ─────────────────────────────────────────

def test_market_failure_degrades_gracefully(grid_state):
    """If the engine Market raises/imports fail, get_market_items still returns
    the PH-T2 specials rather than raising."""
    with patch("engine.world.market.get_market", side_effect=RuntimeError("boom")):
        items = grid_state.get_market_items()
    # Engine goods are gone but the Grid still renders the phone-upgrade specials.
    assert all(i.get("source") != "engine_market" for i in items)
    assert any(i["id"] == "phone_firewall_v1" for i in items)


def test_buy_when_market_offline_returns_error(grid_state):
    """A buy with the Market offline returns a clean error, not an exception."""
    with patch("engine.world.market.get_market", side_effect=RuntimeError("boom")):
        result = grid_state.buy_item("street_pistol", 1)
    assert result["success"] is False
    assert result["error"]


def test_get_prices_exception_returns_empty(grid_state):
    """If Market.get_prices raises, the adapter yields no engine goods (no 500)."""
    mkt = MagicMock()
    mkt.get_prices.side_effect = ValueError("bad district")
    with _patch_market(mkt):
        items = grid_state.get_market_items()
    assert all(i.get("source") != "engine_market" for i in items)


# ── PH-T2 phone-upgrade specials are preserved ───────────────────────────────

def test_phone_upgrade_specials_layered_on_top(grid_state):
    """PH-T2 upgrades appear in the market on top of the live engine goods."""
    mkt = MagicMock()
    mkt.get_prices.return_value = _fake_prices()
    with _patch_market(mkt):
        items = grid_state.get_market_items()
    specials = [i for i in items if i.get("source") == "grid_special"]
    ids = {i["id"] for i in specials}
    assert "phone_firewall_v1" in ids
    assert "phone_os_kernel_v2" in ids
    # specials keep their static catalogue price + stock gating
    fw = next(i for i in specials if i["id"] == "phone_firewall_v1")
    assert fw["price"] == 350
    assert fw["stock"] == 5


def test_buy_phone_upgrade_uses_grid_vendor_path(grid_state):
    """Buying a phone upgrade does NOT hit Market.buy; it grants the real item."""
    mkt = MagicMock()
    ps = MagicMock()
    ps.credits = 100000
    inv = MagicMock()
    with _patch_market(mkt), \
            patch("engine.world.player_state.get_player_state", return_value=ps), \
            patch("engine.world.inventory.get_inventory", return_value=inv), \
            patch.dict("engine.world.inventory.ITEM_CATALOG",
                       {"phone_firewall_v1": {}}, clear=False):
        result = grid_state.buy_item("phone_firewall_v1", 1)

    mkt.buy.assert_not_called()                 # specials never touch engine Market
    assert result["success"] is True
    assert result["source"] == "grid_special"
    ps.spend_credits.assert_called_once()       # credits settled via PlayerState
    inv.add_item.assert_called_once_with("phone_firewall_v1", quantity=1)  # real grant
