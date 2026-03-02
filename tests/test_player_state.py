"""Tests for engine/world/player_state.py — CosySim v0.75."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def fresh_player_state():
    """Reset PlayerState singleton before each test."""
    import engine.world.player_state as ps_mod
    ps_mod.reset_player_state()
    yield
    ps_mod.reset_player_state()


# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────

def test_player_state_defaults():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    d = ps.to_dict()
    assert d["credits"] == 5000
    assert d["reputation"] == 50
    assert d["heat"] == 0
    assert isinstance(d["faction_standings"], dict)
    assert len(d["faction_standings"]) == 6


def test_player_state_singleton():
    from engine.world.player_state import get_player_state
    ps1 = get_player_state()
    ps2 = get_player_state()
    assert ps1 is ps2


# ──────────────────────────────────────────────────────────────────────────────
# Credits
# ──────────────────────────────────────────────────────────────────────────────

def test_earn_credits():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    new_bal = ps.earn_credits(200, "test")
    assert new_bal == 5200
    assert ps.to_dict()["credits"] == 5200


def test_spend_credits_success():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    result = ps.spend_credits(1000, "purchase")
    assert result == 4000
    assert ps.to_dict()["credits"] == 4000


def test_spend_credits_insufficient():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    result = ps.spend_credits(9999, "too_much")
    assert result is None
    assert ps.to_dict()["credits"] == 5000  # unchanged


def test_credits_clamp_at_zero():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    ps.spend_credits(5000, "all")
    assert ps.to_dict()["credits"] == 0
    result = ps.spend_credits(1, "below_zero")
    assert result is None  # still 0, can't go below


# ──────────────────────────────────────────────────────────────────────────────
# Reputation
# ──────────────────────────────────────────────────────────────────────────────

def test_update_reputation_gain():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    new_rep = ps.update_reputation(10, "task")
    assert new_rep == 60
    assert ps.to_dict()["reputation"] == 60


def test_update_reputation_loss():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    new_rep = ps.update_reputation(-20, "crime")
    assert new_rep == 30


def test_reputation_clamps_0_100():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    ps.update_reputation(200, "overflow")
    assert ps.to_dict()["reputation"] == 100
    ps.update_reputation(-999, "underflow")
    assert ps.to_dict()["reputation"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Heat
# ──────────────────────────────────────────────────────────────────────────────

def test_set_heat():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    ps.set_heat(75)
    assert ps.to_dict()["heat"] == 75


def test_adjust_heat_positive():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    ps.adjust_heat(30)
    assert ps.to_dict()["heat"] == 30


def test_adjust_heat_negative():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    ps.set_heat(50)
    ps.adjust_heat(-15)
    assert ps.to_dict()["heat"] == 35


def test_heat_clamps_0_100():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    ps.adjust_heat(200)
    assert ps.to_dict()["heat"] == 100
    ps.adjust_heat(-999)
    assert ps.to_dict()["heat"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Location
# ──────────────────────────────────────────────────────────────────────────────

def test_set_location():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    ps.set_location("CLUB NOIR")
    assert ps.to_dict()["active_location"] == "CLUB NOIR"


# ──────────────────────────────────────────────────────────────────────────────
# Faction standings
# ──────────────────────────────────────────────────────────────────────────────

def test_update_faction_standing():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    new_val = ps.update_faction_standing("OmniCorp", 20)
    assert new_val == 20  # starts at 0, + 20
    assert ps.to_dict()["faction_standings"]["OmniCorp"] == 20


def test_faction_standing_clamp():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    ps.update_faction_standing("OmniCorp", 200)
    assert ps.to_dict()["faction_standings"]["OmniCorp"] == 100
    ps.update_faction_standing("OmniCorp", -999)
    assert ps.to_dict()["faction_standings"]["OmniCorp"] == -100


# ──────────────────────────────────────────────────────────────────────────────
# to_dict / REST serialisation
# ──────────────────────────────────────────────────────────────────────────────

def test_to_dict_has_all_keys():
    from engine.world.player_state import get_player_state
    d = get_player_state().to_dict()
    for key in ("credits", "reputation", "heat", "faction_standings", "active_location", "inventory"):
        assert key in d, f"Missing key: {key}"


def test_to_dict_credits_type():
    from engine.world.player_state import get_player_state
    d = get_player_state().to_dict()
    assert isinstance(d["credits"], (int, float))


# ──────────────────────────────────────────────────────────────────────────────
# WorldSim hooks
# ──────────────────────────────────────────────────────────────────────────────

def test_on_economy_tick_earn():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    before = ps.to_dict()["credits"]
    ps.on_economy_tick("black_market_sale", {"credit_delta": 150})
    assert ps.to_dict()["credits"] >= before  # should earn on sale events


def test_on_economy_tick_spend():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    ps.set_heat(30)
    before_heat = ps.to_dict()["heat"]
    ps.on_economy_tick("corp_tax", {"credit_delta": 50})
    # heat naturally decays on economy tick
    assert ps.to_dict()["heat"] <= before_heat


def test_on_faction_shift():
    from engine.world.player_state import get_player_state
    ps = get_player_state()
    ps.on_faction_shift("OmniCorp", "raises_taxes", 10)
    # Any change or none — just verify no crash
    assert isinstance(ps.to_dict()["faction_standings"]["OmniCorp"], (int, float))


# ──────────────────────────────────────────────────────────────────────────────
# reset_player_state
# ──────────────────────────────────────────────────────────────────────────────

def test_reset_player_state():
    from engine.world.player_state import get_player_state, reset_player_state
    ps = get_player_state()
    ps.earn_credits(9999, "test")
    ps.set_heat(80)
    reset_player_state()
    ps2 = get_player_state()
    assert ps2.to_dict()["credits"] == 5000
    assert ps2.to_dict()["heat"] == 0
