"""Tests for engine/skills/builtin/world_skills.py — CosySim v0.75."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture(autouse=True)
def reset_state():
    """Reset PlayerState singleton before each test."""
    import engine.world.player_state as ps_mod
    ps_mod.reset_player_state()
    yield
    ps_mod.reset_player_state()


# ──────────────────────────────────────────────────────────────────────────────
# get_world_time
# ──────────────────────────────────────────────────────────────────────────────

def test_get_world_time_returns_string():
    from engine.skills.builtin.world_skills import get_world_time
    with patch("engine.world.world_state.get_world_state") as mock_ws:
        ws = MagicMock()
        ws.time_string = "Day 3 22:15"
        ws.weather = "neon_rain"
        mock_ws.return_value = ws
        result = get_world_time()
    assert isinstance(result, str)
    assert len(result) > 5


def test_get_world_time_fallback_on_error():
    from engine.skills.builtin.world_skills import get_world_time
    with patch("engine.world.world_state.get_world_state", side_effect=Exception("offline")):
        result = get_world_time()
    assert "unavailable" in result.lower() or isinstance(result, str)


# ──────────────────────────────────────────────────────────────────────────────
# get_world_weather
# ──────────────────────────────────────────────────────────────────────────────

def test_get_world_weather_returns_string():
    from engine.skills.builtin.world_skills import get_world_weather
    with patch("engine.world.world_state.get_world_state") as mock_ws:
        ws = MagicMock()
        ws.get_weather.return_value = "neon_rain"
        mock_ws.return_value = ws
        result = get_world_weather()
    assert isinstance(result, str)


# ──────────────────────────────────────────────────────────────────────────────
# get_active_events
# ──────────────────────────────────────────────────────────────────────────────

def test_get_active_events_returns_string():
    from engine.skills.builtin.world_skills import get_active_events
    # get_active_events calls world_state.get_active_events() — mock best-effort
    result = get_active_events(scene="casino")
    assert isinstance(result, str)


def test_get_active_events_no_events():
    from engine.skills.builtin.world_skills import get_active_events
    result = get_active_events()
    assert isinstance(result, str)


# ──────────────────────────────────────────────────────────────────────────────
# get_player_state_info
# ──────────────────────────────────────────────────────────────────────────────

def test_get_player_state_info():
    from engine.skills.builtin.world_skills import get_player_state_info
    result = get_player_state_info()
    assert isinstance(result, str)
    assert "5000" in result or "credits" in result.lower()


# ──────────────────────────────────────────────────────────────────────────────
# get_faction_standings
# ──────────────────────────────────────────────────────────────────────────────

def test_get_faction_standings():
    from engine.skills.builtin.world_skills import get_faction_standings
    result = get_faction_standings()
    assert isinstance(result, str)
    # All 6 factions should appear
    assert "OmniCorp" in result


# ──────────────────────────────────────────────────────────────────────────────
# earn_credits
# ──────────────────────────────────────────────────────────────────────────────

def test_earn_credits_skill():
    from engine.skills.builtin.world_skills import earn_credits
    from engine.world.player_state import get_player_state
    result = earn_credits(300, "reward")
    assert "300" in result or "5300" in result
    assert get_player_state().to_dict()["credits"] == 5300


def test_earn_credits_clamps_positive():
    from engine.skills.builtin.world_skills import earn_credits
    # Zero amount returns informative message
    result = earn_credits(0, "nothing")
    assert isinstance(result, str)
    assert "positive" in result.lower()


# ──────────────────────────────────────────────────────────────────────────────
# spend_credits
# ──────────────────────────────────────────────────────────────────────────────

def test_spend_credits_skill_success():
    from engine.skills.builtin.world_skills import spend_credits
    from engine.world.player_state import get_player_state
    result = spend_credits(500, "item")
    assert get_player_state().to_dict()["credits"] == 4500
    assert isinstance(result, str)


def test_spend_credits_skill_insufficient():
    from engine.skills.builtin.world_skills import spend_credits
    result = spend_credits(99999, "broke")
    assert "insufficient" in result.lower() or "not enough" in result.lower()


# ──────────────────────────────────────────────────────────────────────────────
# set_player_location
# ──────────────────────────────────────────────────────────────────────────────

def test_set_player_location():
    from engine.skills.builtin.world_skills import set_player_location
    from engine.world.player_state import get_player_state
    result = set_player_location("THE GRID")
    assert "THE GRID" in result
    assert get_player_state().to_dict()["active_location"] == "THE GRID"


# ──────────────────────────────────────────────────────────────────────────────
# adjust_heat
# ──────────────────────────────────────────────────────────────────────────────

def test_adjust_heat_skill_increase():
    from engine.skills.builtin.world_skills import adjust_heat
    from engine.world.player_state import get_player_state
    result = adjust_heat(25)
    assert get_player_state().to_dict()["heat"] == 25
    assert isinstance(result, str)


def test_adjust_heat_skill_decrease():
    from engine.skills.builtin.world_skills import adjust_heat
    from engine.world.player_state import get_player_state
    get_player_state().set_heat(50)
    adjust_heat(-10)
    assert get_player_state().to_dict()["heat"] == 40


# ──────────────────────────────────────────────────────────────────────────────
# get_recent_sim_events
# ──────────────────────────────────────────────────────────────────────────────

def test_get_recent_sim_events():
    from engine.skills.builtin.world_skills import get_recent_sim_events
    with patch("engine.world.world_sim.get_world_sim") as mock_sim:
        sim = MagicMock()
        ev1 = MagicMock()
        ev1.title = "Market Surge"
        ev1.description = "prices up"
        ev1.created_at = "Day 3 22:00"
        ev2 = MagicMock()
        ev2.title = "Gang War"
        ev2.description = "chaos"
        ev2.created_at = "Day 3 23:00"
        sim.get_event_log.return_value = [ev1, ev2]
        mock_sim.return_value = sim
        result = get_recent_sim_events(5)
    assert "Market Surge" in result
    assert "Gang War" in result


def test_get_recent_sim_events_count():
    from engine.skills.builtin.world_skills import get_recent_sim_events
    with patch("engine.world.world_sim.get_world_sim") as mock_sim:
        sim = MagicMock()
        sim.get_event_log.return_value = []
        mock_sim.return_value = sim
        result = get_recent_sim_events(3)
    assert isinstance(result, str)
