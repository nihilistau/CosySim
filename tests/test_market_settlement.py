"""
Market settlement tests (v1.59.0)
=================================

Verifies the inventory↔market↔heat feedback loop: buying deducts credits,
adds to inventory, and raises heat on contraband; selling requires possession
and credits the wallet.

Version: v1.59.0 [2026-06-13]
"""
from __future__ import annotations

import pytest

from engine.world.market import get_market
from engine.world.player_state import get_player_state
from engine.world.inventory import get_inventory


@pytest.fixture
def fresh_world(monkeypatch):
    """Reset market, give the player a known wallet + empty-ish inventory."""
    mkt = get_market()
    ps = get_player_state()
    inv = get_inventory()
    # known starting credits / heat
    ps.set_credits(10_000) if hasattr(ps, "set_credits") else None
    with ps._lock:  # direct set for a deterministic baseline
        ps._credits = 10_000
        ps._heat = 0
    return mkt, ps, inv


def _first_good(mkt, illegal=None):
    """Return (district, good_id, good) for the first good matching illegal flag."""
    for gid, good in mkt._goods.items():
        if illegal is None or bool(getattr(good, "illegal", False)) == illegal:
            # find a district that sells it
            for shop in mkt._shops.values():
                if good.category in shop.categories:
                    return shop.district, gid, good
    return None, None, None


@pytest.mark.unit
def test_buy_deducts_credits_and_adds_inventory(fresh_world):
    mkt, ps, inv = fresh_world
    district, gid, good = _first_good(mkt, illegal=False)
    assert gid, "no legal good found in market"

    before = ps.credits
    held_before = inv.get_item(gid).quantity if inv.get_item(gid) else 0
    res = mkt.buy(district, gid, quantity=2)

    assert res["status"] == "ok"
    assert ps.credits == before - res["total"]
    assert res["balance"] == ps.credits
    held_after = inv.get_item(gid).quantity if inv.get_item(gid) else 0
    assert held_after == held_before + 2


@pytest.mark.unit
def test_buy_insufficient_credits_blocks(fresh_world):
    mkt, ps, inv = fresh_world
    with ps._lock:
        ps._credits = 1  # too poor for anything
    district, gid, good = _first_good(mkt, illegal=False)
    res = mkt.buy(district, gid, quantity=1)
    assert res["status"] == "error"
    assert res["reason"] == "insufficient_credits"
    assert ps.credits == 1  # untouched


@pytest.mark.unit
def test_contraband_raises_heat(fresh_world):
    mkt, ps, inv = fresh_world
    district, gid, good = _first_good(mkt, illegal=True)
    if not gid:
        pytest.skip("no contraband good in catalog")
    heat_before = ps.heat
    res = mkt.buy(district, gid, quantity=3)
    assert res["status"] == "ok"
    # default config: 4 heat per unit * 3 = 12
    assert ps.heat > heat_before
    assert res.get("heat") == ps.heat


@pytest.mark.unit
def test_sell_requires_possession(fresh_world):
    mkt, ps, inv = fresh_world
    district, gid, good = _first_good(mkt, illegal=False)
    # ensure we hold none
    if inv.get_item(gid):
        inv.remove_item(gid, inv.get_item(gid).quantity)
    res = mkt.sell(district, gid, quantity=1)
    assert res["status"] == "error"
    assert res["reason"] == "not_in_inventory"


@pytest.mark.unit
def test_sell_credits_wallet_and_removes_item(fresh_world):
    mkt, ps, inv = fresh_world
    district, gid, good = _first_good(mkt, illegal=False)
    inv.add_item(gid, 2)
    before = ps.credits
    res = mkt.sell(district, gid, quantity=2)
    assert res["status"] == "ok"
    assert ps.credits == before + res["total"]
    assert not inv.has_item(gid, 1)
