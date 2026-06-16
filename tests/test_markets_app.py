"""Tests for the Executive Suite Markets app backend (v1.63.0 — D-T2/D-T3
"The Exchange").

Verifies that the Executive Suite *Markets* app trades the *one* live engine
economy (``engine.world.market.get_market``) — the SAME ``Market`` The Grid
surfaces (D-T1), district DOWNTOWN — rather than a parallel price book:

* ``_markets_state`` prices/goods come straight from ``Market.get_prices`` and
  MATCH what the engine reports (one economy);
* ``_markets_trade`` routes buy/sell through ``Market.buy``/``Market.sell`` with
  the Grid's player id, so credits/inventory/heat settle on the shared wallet;
* an engine-side rejection surfaces a clean player-facing error (never a 500);
* a Market outage degrades gracefully (empty table, no raise).

The scene is exercised via a bare instance (``object.__new__``) so the test does
not boot Socket.IO / agents — only the pure Markets backend methods are called.
"""
from __future__ import annotations

import os
import platform as _platform

# Pre-seed platform.uname() (WMI hang guard on this Windows host) BEFORE the
# scene import chain (flask_socketio/engineio) touches it.
try:  # pragma: no cover - environment guard
    _platform._uname_cache = _platform.uname_result(
        "Windows", "Beast", "11", "10.0.26200", "AMD64",
    )
except Exception:  # pragma: no cover
    pass

from typing import Any, Dict, List  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from content.scenes.executive_suite.executive_suite_scene import (  # noqa: E402
    ExecutiveSuiteScene,
    _MARKETS_LAST_PRICES,
    _MARKETS_PLAYER_ID,
)


@pytest.fixture()
def scene():
    """A bare ExecutiveSuiteScene (no Flask/Socket.IO boot) for backend methods."""
    _MARKETS_LAST_PRICES.clear()
    return object.__new__(ExecutiveSuiteScene)


def _fake_prices(price_pistol: int = 275, price_stim: int = 55) -> List[Dict[str, Any]]:
    """Return a minimal get_prices()-shaped DOWNTOWN payload (one shop/good)."""
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
    return patch("engine.world.market.get_market", return_value=mock_market)


# ── State prices come from the engine Market (one economy, DOWNTOWN) ──────────

def test_markets_state_prices_come_from_engine_market(scene):
    """_markets_state surfaces engine-Market prices for the configured district."""
    mkt = MagicMock()
    mkt.get_prices.return_value = _fake_prices(price_pistol=300, price_stim=60)
    mkt.get_stats.return_value = {"total_goods": 27}
    with _patch_market(mkt), \
            patch("engine.world.inventory.get_inventory", side_effect=RuntimeError("x")), \
            patch("engine.world.player_state.get_player_state", side_effect=RuntimeError("x")):
        state = scene._markets_state()

    # Reads the SAME district the Grid trades (DOWNTOWN by default).
    mkt.get_prices.assert_called_once_with("DOWNTOWN")
    assert state["district"] == "DOWNTOWN"
    by_id = {g["good_id"]: g for g in state["goods"]}
    assert by_id["street_pistol"]["price"] == 300
    assert by_id["stim_pack"]["price"] == 60
    assert by_id["street_pistol"]["category"] == "weapons"


def test_markets_state_one_row_per_good(scene):
    """Duplicate shop rows for a good collapse to one (cheapest shop wins on buy)."""
    rows = _fake_prices()
    dup = dict(rows[0]); dup["shop_price"] = 999; dup["shop_id"] = "other"
    mkt = MagicMock()
    mkt.get_prices.return_value = [rows[0], dup, rows[1]]
    mkt.get_stats.return_value = {}
    with _patch_market(mkt), \
            patch("engine.world.inventory.get_inventory", side_effect=RuntimeError("x")), \
            patch("engine.world.player_state.get_player_state", side_effect=RuntimeError("x")):
        state = scene._markets_state()
    pistols = [g for g in state["goods"] if g["good_id"] == "street_pistol"]
    assert len(pistols) == 1
    assert pistols[0]["price"] == 275  # first (cheapest, matching buy()) wins


def test_markets_state_trend_rises_and_falls(scene):
    """A higher then lower price across reads yields ▲ then ▼ trends."""
    mkt = MagicMock()
    mkt.get_stats.return_value = {}
    with _patch_market(mkt), \
            patch("engine.world.inventory.get_inventory", side_effect=RuntimeError("x")), \
            patch("engine.world.player_state.get_player_state", side_effect=RuntimeError("x")):
        mkt.get_prices.return_value = _fake_prices(price_pistol=275)
        first = {g["good_id"]: g for g in scene._markets_state()["goods"]}
        assert first["street_pistol"]["trend"] == "▬"  # no prior snapshot

        mkt.get_prices.return_value = _fake_prices(price_pistol=320)
        second = {g["good_id"]: g for g in scene._markets_state()["goods"]}
        assert second["street_pistol"]["trend"] == "▲"

        mkt.get_prices.return_value = _fake_prices(price_pistol=290)
        third = {g["good_id"]: g for g in scene._markets_state()["goods"]}
        assert third["street_pistol"]["trend"] == "▼"


def test_markets_state_credits_and_positions(scene):
    """Credits read the shared wallet; positions are tradable inventory holdings."""
    mkt = MagicMock()
    mkt.get_prices.return_value = _fake_prices(price_pistol=300)
    mkt.get_stats.return_value = {}
    ps = MagicMock(); ps.credits = 4242
    inv = MagicMock()
    inv.to_dict.return_value = {"items": [
        {"item_id": "street_pistol", "name": "Street Pistol", "quantity": 3, "category": "weapons"},
        {"item_id": "untradable_here", "name": "Nope", "quantity": 9, "category": "misc"},
    ]}
    with _patch_market(mkt), \
            patch("engine.world.inventory.get_inventory", return_value=inv), \
            patch("engine.world.player_state.get_player_state", return_value=ps):
        state = scene._markets_state()
    assert state["credits"] == 4242
    pos = {p["good_id"]: p for p in state["inventory"]}
    assert "street_pistol" in pos
    assert pos["street_pistol"]["value"] == 300 * 3  # priced at live market price
    assert "untradable_here" not in pos  # only positions tradable in this market


# ── Trade routes through the engine Market (shared wallet) ────────────────────

def test_markets_buy_routes_through_engine_market(scene):
    """_markets_trade('buy') calls Market.buy with the Grid's player id + district."""
    mkt = MagicMock()
    mkt.buy.return_value = {
        "status": "ok", "good_id": "street_pistol", "good_name": "Street Pistol",
        "quantity": 2, "unit_price": 300, "total": 600, "balance": 9400,
        "shop": "Neon Arms", "illegal": False,
    }
    mkt.get_prices.return_value = _fake_prices()
    mkt.get_stats.return_value = {}
    with _patch_market(mkt), \
            patch("engine.world.inventory.get_inventory", side_effect=RuntimeError("x")), \
            patch("engine.world.player_state.get_player_state", side_effect=RuntimeError("x")):
        out = scene._markets_trade("buy", {"good_id": "street_pistol", "quantity": 2})

    assert mkt.buy.call_args.args[0] == "DOWNTOWN"             # same district as Grid
    assert mkt.buy.call_args.args[1] == "street_pistol"
    assert mkt.buy.call_args.kwargs.get("quantity") == 2
    assert mkt.buy.call_args.kwargs.get("player_id") == _MARKETS_PLAYER_ID == "player1"
    assert out["success"] is True
    assert out["total"] == 600
    assert out["balance"] == 9400
    assert "state" in out  # one round-trip refresh


def test_markets_sell_routes_through_engine_market(scene):
    """_markets_trade('sell') calls Market.sell and reports proceeds + balance."""
    mkt = MagicMock()
    mkt.sell.return_value = {
        "status": "ok", "good_id": "street_pistol", "good_name": "Street Pistol",
        "quantity": 1, "unit_price": 180, "total": 180, "balance": 9580,
    }
    mkt.get_prices.return_value = _fake_prices()
    mkt.get_stats.return_value = {}
    with _patch_market(mkt), \
            patch("engine.world.inventory.get_inventory", side_effect=RuntimeError("x")), \
            patch("engine.world.player_state.get_player_state", side_effect=RuntimeError("x")):
        out = scene._markets_trade("sell", {"good_id": "street_pistol", "quantity": 1})

    mkt.sell.assert_called_once()
    assert mkt.sell.call_args.kwargs.get("player_id") == "player1"
    assert out["success"] is True
    assert out["total"] == 180
    assert out["balance"] == 9580


def test_markets_buy_insufficient_credits_surfaces_engine_error(scene):
    """An engine rejection (insufficient credits) maps to a clean player message."""
    mkt = MagicMock()
    mkt.buy.return_value = {"status": "error", "reason": "insufficient_credits",
                            "needed": 600, "balance": 100}
    mkt.get_prices.return_value = _fake_prices()
    mkt.get_stats.return_value = {}
    with _patch_market(mkt), \
            patch("engine.world.inventory.get_inventory", side_effect=RuntimeError("x")), \
            patch("engine.world.player_state.get_player_state", side_effect=RuntimeError("x")):
        out = scene._markets_trade("buy", {"good_id": "street_pistol", "quantity": 2})
    assert out["success"] is False
    assert "Insufficient credits" in out["error"]


# ── Graceful degradation — never 500 ─────────────────────────────────────────

def test_markets_state_offline_degrades_gracefully(scene):
    """Market unavailable → empty goods, no raise (route never 500s)."""
    with patch("engine.world.market.get_market", side_effect=RuntimeError("boom")), \
            patch("engine.world.inventory.get_inventory", side_effect=RuntimeError("x")), \
            patch("engine.world.player_state.get_player_state", side_effect=RuntimeError("x")):
        state = scene._markets_state()
    assert state["goods"] == []
    assert state["district"] == "DOWNTOWN"


def test_markets_trade_offline_returns_error(scene):
    """A trade with the Market offline returns a clean error, not an exception."""
    with patch("engine.world.market.get_market", side_effect=RuntimeError("boom")), \
            patch("engine.world.inventory.get_inventory", side_effect=RuntimeError("x")), \
            patch("engine.world.player_state.get_player_state", side_effect=RuntimeError("x")):
        out = scene._markets_trade("buy", {"good_id": "street_pistol", "quantity": 1})
    assert out["success"] is False
    assert out["error"]


def test_markets_trade_requires_good_id(scene):
    """A trade with no good_id is rejected before touching the Market."""
    with patch("engine.world.market.get_market", side_effect=RuntimeError("x")), \
            patch("engine.world.inventory.get_inventory", side_effect=RuntimeError("x")), \
            patch("engine.world.player_state.get_player_state", side_effect=RuntimeError("x")):
        out = scene._markets_trade("buy", {"good_id": "", "quantity": 1})
    assert out["success"] is False
    assert "good_id" in out["error"]
