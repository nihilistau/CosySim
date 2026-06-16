"""Unit tests for the War Room live state assembler (v1.63.0 C-T2).

Exercises the pure state-assembly helpers on :class:`WarRoomScene` against
mocked engine managers (territory, faction AI, crew, player state). Covers:

* the factions list (power / territory / relations / traits),
* the my-faction block (power, territory, rank, crews, hq),
* rivals with relations + active wars + recent decisions,
* rank-threshold mapping from config,
* the no-allegiance picker payload,
* defensive defaults when a manager raises.

The scene is built once (it boots without a live world) and its assembler
methods are called directly — no socket / HTTP needed.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

import content.scenes.war_room.war_room_scene as wr


# ──── Fakes ────────────────────────────────────────────────────


class _FakeTerritory:
    """Minimal stand-in for TerritoryManager."""

    def __init__(self) -> None:
        self._totals = {
            "OmniCorp": 150.0, "NeoTech": 120.0, "BlackMarket": 100.0,
            "Ghost_Net": 80.0, "SynthSec": 90.0, "DeepState": 60.0,
        }
        # district -> faction -> pct
        self._all = {
            "DOWNTOWN": {"OmniCorp": 55.0, "Ghost_Net": 10.0},
            "TECH_DISTRICT": {"Ghost_Net": 60.0, "NeoTech": 30.0},
            "UNDERWORLD": {"Ghost_Net": 40.0, "BlackMarket": 35.0},
        }

    def get_faction_total_control(self, faction: str) -> float:
        return self._totals.get(faction, 0.0)

    def get_all_control(self) -> Dict[str, Dict[str, float]]:
        return {d: dict(c) for d, c in self._all.items()}

    def get_wars_active(self) -> List[Dict[str, Any]]:
        return [{"district": "TECH_DISTRICT", "faction": "SynthSec", "triggered_war": True}]

    def get_hq(self, crew_id: str):
        return None


class _FakeFactionAI:
    """Minimal stand-in for FactionAI."""

    def __init__(self) -> None:
        self.context_calls: List[Dict[str, Any]] = []

    def get_history(self, faction: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        return [{"faction": "SynthSec", "action": "raid", "narrative": "n"}][:limit]

    def get_active_wars(self) -> Dict[str, Dict[str, str]]:
        return {"TECH_DISTRICT": {"attacker": "SynthSec", "defender": "Ghost_Net"}}

    def set_player_context(self, standings=None, district: str = "") -> None:
        self.context_calls.append({"standings": standings, "district": district})


class _FakeCrewMember:
    def __init__(self, cid: str) -> None:
        self.character_id = cid
        self.role = "hacker"

    def to_dict(self) -> Dict[str, Any]:
        return {"character_id": self.character_id, "role": self.role}


class _FakeCrew:
    def get_all_members(self) -> List[_FakeCrewMember]:
        return [_FakeCrewMember("nyx"), _FakeCrewMember("rook")]

    def get_active_operations(self) -> List[Any]:
        return []


class _FakePlayerState:
    def __init__(self, allegiance=None) -> None:
        self._allegiance = allegiance
        self.faction_standings = {
            "OmniCorp": -40, "NeoTech": 10, "BlackMarket": -10,
            "Ghost_Net": 50, "SynthSec": -60, "DeepState": 0,
        }
        self.active_location = "TECH_DISTRICT"

    @property
    def allegiance(self):
        return self._allegiance


class _FakeFaction:
    """faction_politics Faction stand-in."""

    def __init__(self, fid: str) -> None:
        self.id = fid
        self.name = fid
        self.player_standing = 5
        self.relationships = {"NeoTech": 40, "BlackMarket": -30}


class _FakeFactionManager:
    def get(self, faction_id: str):
        return _FakeFaction(faction_id)


@pytest.fixture()
def scene(monkeypatch) -> wr.WarRoomScene:
    """Boot a WarRoomScene with all manager accessors patched to fakes."""
    s = wr.WarRoomScene()
    monkeypatch.setattr(s, "_territory", lambda: _FakeTerritory())
    monkeypatch.setattr(s, "_faction_ai", lambda: _FakeFactionAI())
    monkeypatch.setattr(s, "_crew", lambda: _FakeCrew())
    monkeypatch.setattr(s, "_faction_mgr", lambda: _FakeFactionManager())
    return s


# ──── factions list ────


def test_factions_list_has_six(scene) -> None:
    factions = scene._assemble_factions()
    assert len(factions) == 6
    names = {f["faction"] for f in factions}
    assert names == {
        "OmniCorp", "NeoTech", "BlackMarket",
        "Ghost_Net", "SynthSec", "DeepState",
    }


def test_factions_list_power_and_territory(scene) -> None:
    factions = {f["faction"]: f for f in scene._assemble_factions()}
    # OmniCorp power from fake totals
    assert factions["OmniCorp"]["power"] == 150.0
    # OmniCorp dominates DOWNTOWN (55%) → it's in its territory
    assert "DOWNTOWN" in factions["OmniCorp"]["territory"]
    # Ghost_Net dominates TECH_DISTRICT and UNDERWORLD
    assert set(factions["Ghost_Net"]["territory"]) == {"TECH_DISTRICT", "UNDERWORLD"}


def test_factions_list_has_traits(scene) -> None:
    factions = {f["faction"]: f for f in scene._assemble_factions()}
    assert factions["OmniCorp"]["traits"]  # FACTION_TRAITS entry
    assert "aggression" in factions["OmniCorp"]["traits"]


# ──── state assembler: my faction / rivals ────


def test_state_with_allegiance(scene, monkeypatch) -> None:
    monkeypatch.setattr(scene, "_player", lambda: _FakePlayerState("Ghost_Net"))
    state = scene._assemble_state()

    assert state["allegiance"] == "Ghost_Net"
    assert state["my"]["faction"] == "Ghost_Net"
    assert state["my"]["power"] == 80.0
    assert set(state["my"]["territory"]) == {"TECH_DISTRICT", "UNDERWORLD"}
    assert "rank" in state["my"]
    # crews come from the crew manager
    assert len(state["my"]["crews"]) == 2

    # rivals exclude the player's own faction and carry relation values
    rival_names = {r["faction"] for r in state["rivals"]}
    assert "Ghost_Net" not in rival_names
    assert len(rival_names) == 5
    for r in state["rivals"]:
        assert "relation" in r and "power" in r

    assert state["wars"]  # from get_active_wars
    assert state["recent_decisions"]  # from get_history
    assert state["standings"]["Ghost_Net"] == 50


def test_state_no_allegiance_returns_picker(scene, monkeypatch) -> None:
    monkeypatch.setattr(scene, "_player", lambda: _FakePlayerState(None))
    state = scene._assemble_state()
    assert state["allegiance"] is None
    # picker payload: factions list present so UI can show the chooser
    assert "factions" in state
    assert len(state["factions"]) == 6
    # no my-faction block when unset
    assert state.get("my") in (None, {})


# ──── rank thresholds ────


def test_rank_threshold_mapping(scene) -> None:
    # Default thresholds (see config / _cfg defaults): map ascending power.
    assert scene._rank_for_power(5.0) == scene._rank_for_power(5.0)  # deterministic
    low = scene._rank_for_power(10.0)
    high = scene._rank_for_power(500.0)
    assert isinstance(low, str) and isinstance(high, str)
    assert low != high  # different power bands → different rank labels


def test_rank_uses_config_thresholds(scene, monkeypatch) -> None:
    # Inject custom thresholds and verify boundary behaviour.
    thresholds = [
        {"min": 0, "rank": "Nobody"},
        {"min": 100, "rank": "Player"},
        {"min": 300, "rank": "Kingpin"},
    ]
    monkeypatch.setattr(scene, "_cfg", lambda k, d: thresholds if k == "rank_thresholds" else d)
    assert scene._rank_for_power(50.0) == "Nobody"
    assert scene._rank_for_power(100.0) == "Player"
    assert scene._rank_for_power(250.0) == "Player"
    assert scene._rank_for_power(400.0) == "Kingpin"


# ──── defensive ────


def test_failing_territory_yields_safe_defaults(scene, monkeypatch) -> None:
    def _boom():
        raise RuntimeError("territory offline")

    monkeypatch.setattr(scene, "_territory", _boom)
    monkeypatch.setattr(scene, "_player", lambda: _FakePlayerState("Ghost_Net"))

    # Must not raise; my-faction power/territory degrade to safe defaults.
    state = scene._assemble_state()
    assert state["allegiance"] == "Ghost_Net"
    assert state["my"]["power"] == 0.0
    assert state["my"]["territory"] == []


def test_factions_list_defensive_on_failure(scene, monkeypatch) -> None:
    def _boom():
        raise RuntimeError("offline")

    monkeypatch.setattr(scene, "_territory", _boom)
    # Still returns the 6 factions with zeroed power, never raises.
    factions = scene._assemble_factions()
    assert len(factions) == 6
    assert all(f["power"] == 0.0 for f in factions)
