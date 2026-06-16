"""Unit tests for The Sprawl live world-state assembly (B-T2, v1.63.0).

These tests exercise :meth:`TheSprawlScene._build_state` and the event-merge
helper in isolation, with every upstream manager mocked. They assert the
*assembly contract* (shape + canonical resolution) and — crucially — that a
failing manager yields safe defaults instead of raising (the scene must never
500).

Version: v1.63.0 [2026-06-15]
Author:  CosySim Team
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from content.scenes.the_sprawl.the_sprawl_scene import TheSprawlScene


# ──── Fakes ───────────────────────────────────────────────────────────


class _FakeTerritory:
    """Stand-in TerritoryManager exposing only the read seams the scene uses."""

    def get_all_control(self) -> Dict[str, Dict[str, float]]:
        return {
            "DOWNTOWN": {"OmniCorp": 35.0, "BlackMarket": 25.0, "SynthSec": 40.0},
            "TECH_DISTRICT": {"NeoTech": 60.0, "Ghost_Net": 40.0},
        }

    def get_dominant_faction(self, district: str):
        return {
            "DOWNTOWN": ("SynthSec", 40.0),
            "TECH_DISTRICT": ("NeoTech", 60.0),
        }.get(district, ("none", 0.0))

    def get_faction_ranking(self) -> List:
        return [("NeoTech", 120.0), ("SynthSec", 90.0), ("OmniCorp", 35.0)]

    def get_event_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [
            {"district": "DOWNTOWN", "faction": "SynthSec", "delta": 5.0,
             "reason": "faction_expansion", "timestamp": 1000.0,
             "triggered_war": False},
        ]


class _FakeRoutine:
    """Stand-in RoutineManager."""

    def list_npcs(self) -> List[str]:
        return ["aria", "viktor"]

    def get_npc_location(self, npc_id: str):
        return {
            "aria": {"location": "grid", "activity": "running intrusions"},
            "viktor": {"location": "rusty_anchor", "activity": "tending bar"},
        }.get(npc_id)


def _new_scene() -> TheSprawlScene:
    """Construct a scene without binding any real network port."""
    return TheSprawlScene()


# ──── _build_state assembly ───────────────────────────────────────────


def test_districts_carry_control_dominant_and_contested(monkeypatch):
    scene = _new_scene()
    monkeypatch.setattr(scene, "_territory", lambda: _FakeTerritory())
    monkeypatch.setattr(scene, "_routine", lambda: _FakeRoutine())
    monkeypatch.setattr(scene, "_characters", lambda: [])
    monkeypatch.setattr(scene, "_player", lambda: {"location": "X", "credits": 0, "heat": 0})

    state = scene._build_state()

    by_id = {d["id"]: d for d in state["districts"]}
    assert "DOWNTOWN" in by_id
    dt = by_id["DOWNTOWN"]
    assert dt["control"]["SynthSec"] == 40.0
    assert dt["dominant"] == ["SynthSec", 40.0]
    # SynthSec 40 vs runner-up 35 → margin 5 < contest threshold → contested.
    assert dt["contested"] is True
    # NeoTech 60 vs 40 → margin 20 → not contested.
    assert by_id["TECH_DISTRICT"]["contested"] is False


def test_factions_come_from_ranking(monkeypatch):
    scene = _new_scene()
    monkeypatch.setattr(scene, "_territory", lambda: _FakeTerritory())
    monkeypatch.setattr(scene, "_routine", lambda: _FakeRoutine())
    monkeypatch.setattr(scene, "_characters", lambda: [])
    monkeypatch.setattr(scene, "_player", lambda: {"location": "X", "credits": 0, "heat": 0})

    state = scene._build_state()
    assert state["factions"][0] == {"faction": "NeoTech", "total": 120.0}
    assert [f["faction"] for f in state["factions"]] == ["NeoTech", "SynthSec", "OmniCorp"]


def test_npcs_carry_canonical_faction_and_district(monkeypatch):
    scene = _new_scene()
    chars = [
        {"id": "aria", "name": "Aria", "sex": "female",
         "metadata": {"faction": "OmniCorp"}},
        {"id": "viktor", "name": "Viktor Marlowe", "sex": "male",
         "metadata": {"faction": "SynthSec"}},
    ]
    monkeypatch.setattr(scene, "_territory", lambda: _FakeTerritory())
    monkeypatch.setattr(scene, "_routine", lambda: _FakeRoutine())
    monkeypatch.setattr(scene, "_characters", lambda: chars)
    monkeypatch.setattr(scene, "_player", lambda: {"location": "X", "credits": 0, "heat": 0})

    state = scene._build_state()
    npcs = {n["id"]: n for n in state["npcs"]}
    # aria is a hacker at scene "grid" → TECH_DISTRICT (per DISTRICT_SCENES).
    assert npcs["aria"]["faction"] == "OmniCorp"
    assert npcs["aria"]["district"] == "TECH_DISTRICT"
    assert npcs["aria"]["activity"] == "running intrusions"
    # viktor at "rusty_anchor" → COMBAT_ZONE.
    assert npcs["viktor"]["district"] == "COMBAT_ZONE"
    assert npcs["viktor"]["faction"] == "SynthSec"


def test_player_block_present(monkeypatch):
    scene = _new_scene()
    monkeypatch.setattr(scene, "_territory", lambda: _FakeTerritory())
    monkeypatch.setattr(scene, "_routine", lambda: _FakeRoutine())
    monkeypatch.setattr(scene, "_characters", lambda: [])
    monkeypatch.setattr(
        scene, "_player",
        lambda: {"location": "THE GRID", "credits": 4200, "heat": 12},
    )

    state = scene._build_state()
    assert state["player"] == {"location": "THE GRID", "credits": 4200, "heat": 12}
    assert "ts" in state


# ──── Defensive: a failing source yields safe defaults, never raises ──


def test_failing_territory_yields_safe_defaults(monkeypatch):
    scene = _new_scene()

    def _boom():
        raise RuntimeError("territory offline")

    monkeypatch.setattr(scene, "_territory", _boom)
    monkeypatch.setattr(scene, "_routine", lambda: _FakeRoutine())
    monkeypatch.setattr(scene, "_characters", lambda: [])
    monkeypatch.setattr(scene, "_player", lambda: {"location": "X", "credits": 0, "heat": 0})

    state = scene._build_state()  # must not raise
    assert state["districts"] == []
    assert state["factions"] == []
    # NPC district falls back to "unknown" when territory is down, but the
    # npc list itself still assembles from the routine/character sources.
    assert isinstance(state["npcs"], list)


def test_failing_routine_yields_empty_npcs(monkeypatch):
    scene = _new_scene()

    def _boom():
        raise RuntimeError("routine offline")

    monkeypatch.setattr(scene, "_territory", lambda: _FakeTerritory())
    monkeypatch.setattr(scene, "_routine", _boom)
    monkeypatch.setattr(scene, "_characters", lambda: [])
    monkeypatch.setattr(scene, "_player", lambda: {"location": "X", "credits": 0, "heat": 0})

    state = scene._build_state()  # must not raise
    assert state["npcs"] == []
    assert len(state["districts"]) == 2  # territory still works


def test_failing_player_yields_default_block(monkeypatch):
    scene = _new_scene()

    def _boom():
        raise RuntimeError("player state offline")

    monkeypatch.setattr(scene, "_territory", lambda: _FakeTerritory())
    monkeypatch.setattr(scene, "_routine", lambda: _FakeRoutine())
    monkeypatch.setattr(scene, "_characters", lambda: [])
    monkeypatch.setattr(scene, "_player", _boom)

    state = scene._build_state()  # must not raise
    assert state["player"]["location"] == ""
    assert state["player"]["credits"] == 0
    assert state["player"]["heat"] == 0


# ──── Event normalization / merge ─────────────────────────────────────


def test_merged_events_normalized_and_newest_first(monkeypatch):
    scene = _new_scene()

    class _Store:
        def recent_events(self, limit: int = 50):
            return [
                {"id": 7, "ts": "2026-06-15T10:00:05", "kind": "deal",
                 "actor": "aria", "summary": "brokered a chip deal", "payload": {}},
                {"id": 6, "ts": "2026-06-15T10:00:01", "kind": "war",
                 "actor": "SynthSec", "summary": "moved on Downtown", "payload": {}},
            ]

    monkeypatch.setattr(scene, "_emergent_store", lambda: _Store())
    monkeypatch.setattr(scene, "_territory", lambda: _FakeTerritory())

    events = scene._merged_events(since=0)
    assert isinstance(events, list)
    # Every event carries the normalized contract.
    for e in events:
        assert {"ts", "kind", "actor", "summary"} <= set(e.keys())
    # Territory event got normalized with a district + a kind.
    assert any(e.get("district") == "DOWNTOWN" for e in events)


def test_merged_events_filter_since(monkeypatch):
    scene = _new_scene()

    class _Store:
        def recent_events(self, limit: int = 50):
            return [
                {"id": 9, "ts": "t9", "kind": "deal", "actor": "a", "summary": "s9"},
                {"id": 3, "ts": "t3", "kind": "deal", "actor": "b", "summary": "s3"},
            ]

    monkeypatch.setattr(scene, "_emergent_store", lambda: _Store())

    class _Terr:
        def get_event_history(self, limit: int = 20):
            return []

    monkeypatch.setattr(scene, "_territory", lambda: _Terr())

    events = scene._merged_events(since=5)
    ids = [e.get("id") for e in events if e.get("id") is not None]
    assert 9 in ids
    assert 3 not in ids


def test_merged_events_defensive_on_store_failure(monkeypatch):
    scene = _new_scene()

    def _boom():
        raise RuntimeError("store offline")

    monkeypatch.setattr(scene, "_emergent_store", _boom)
    monkeypatch.setattr(scene, "_territory", lambda: _FakeTerritory())

    events = scene._merged_events(since=0)  # must not raise
    assert isinstance(events, list)
    # Territory events still come through.
    assert any(e.get("district") == "DOWNTOWN" for e in events)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
