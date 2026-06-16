"""Unit tests for per-NPC goal generation + persistence (Task A3).

Covers the PURE goal generator (``generate_goals`` driven entirely by a
hand-built ctx dict), the deterministic re-prioritiser (``reprioritize``), the
``Goal`` dataclass row mapping, and round-trip persistence through an isolated
``EmergentStore(path=tmp)`` so the real emergent database is never touched.

These tests are self-contained: no live managers are imported or called — the
generator takes all of its inputs via ctx, which is the whole point of keeping
it pure and unit-testable.

Version: v1.63.0 [2026-06-15]

Change Log:
    v1.63.0 [2026-06-15] — Initial tests for the emergent per-NPC goal layer
                            (A3): baseline wealth, revenge/romance from
                            relationships, faction rank+territory, lay-low
                            priority boost, determinism, reprioritize decay/
                            bump ordering, and save/load round-trip.
"""
from __future__ import annotations

import random

import pytest

from engine.world.emergent.goals import (
    LAY_LOW,
    RANK,
    REVENGE,
    ROMANCE,
    TERRITORY,
    WEALTH,
    Goal,
    generate_goals,
    load_goals,
    reprioritize,
    save_goals,
)
from engine.world.emergent.store import EmergentStore


@pytest.fixture
def store(tmp_path) -> EmergentStore:
    """Return an EmergentStore backed by an isolated temp database."""
    return EmergentStore(path=tmp_path / "emergent.db")


def _types(goals) -> list[str]:
    """Return the list of goal ``type`` strings for easy assertions."""
    return [g.type for g in goals]


# ── generation: baseline ───────────────────────────────────────────────


def test_baseline_wealth_always_present() -> None:
    goals = generate_goals("npc-1", ctx={})
    assert WEALTH in _types(goals)


# ── generation: relationships ──────────────────────────────────────────


def test_hostile_relationship_yields_revenge_goal() -> None:
    ctx = {"relationships": {"enemy": -0.8, "friend": 0.1}}
    goals = generate_goals("npc-1", ctx=ctx)
    revenge = [g for g in goals if g.type == REVENGE]
    assert len(revenge) == 1
    assert revenge[0].target == "enemy"


def test_close_relationship_yields_romance_for_strongest() -> None:
    ctx = {"relationships": {"a": 0.65, "best": 0.8, "c": 0.2}}
    goals = generate_goals("npc-1", ctx=ctx)
    romance = [g for g in goals if g.type == ROMANCE]
    assert len(romance) == 1
    assert romance[0].target == "best"


# ── generation: faction ────────────────────────────────────────────────


def test_faction_yields_rank_and_territory() -> None:
    goals = generate_goals("npc-1", ctx={"faction": "arasaka"})
    rank = [g for g in goals if g.type == RANK]
    terr = [g for g in goals if g.type == TERRITORY]
    assert len(rank) == 1 and rank[0].target == "arasaka"
    assert len(terr) == 1 and terr[0].target == "arasaka"


# ── generation: lay low ────────────────────────────────────────────────


def test_recently_hacked_makes_lay_low_top_priority() -> None:
    ctx = {
        "relationships": {"enemy": -0.9},
        "faction": "maelstrom",
        "recently_hacked": True,
    }
    goals = generate_goals("npc-1", ctx=ctx)
    assert goals[0].type == LAY_LOW
    assert goals[0].priority >= max(g.priority for g in goals)


def test_in_trouble_makes_lay_low_top_priority() -> None:
    ctx = {"faction": "maelstrom", "in_trouble": True}
    goals = generate_goals("npc-1", ctx=ctx)
    assert goals[0].type == LAY_LOW


# ── generation: ordering + determinism ─────────────────────────────────


def test_goals_sorted_priority_desc() -> None:
    ctx = {"relationships": {"e": -0.7}, "faction": "f"}
    goals = generate_goals("npc-1", ctx=ctx)
    pris = [g.priority for g in goals]
    assert pris == sorted(pris, reverse=True)


def test_generate_goals_deterministic_with_seed() -> None:
    ctx = {
        "relationships": {"e1": -0.7, "e2": -0.5, "buddy": 0.9},
        "faction": "valentinos",
        "in_trouble": True,
    }
    a = generate_goals("npc-1", ctx=ctx, rng=random.Random(42))
    b = generate_goals("npc-1", ctx=ctx, rng=random.Random(42))
    assert [g.to_row() for g in a] == [g.to_row() for g in b]


# ── reprioritize ───────────────────────────────────────────────────────


def test_reprioritize_decays_success_and_bumps_failure() -> None:
    goals = [
        Goal(type=WEALTH, target="", priority=0.5),
        Goal(type=REVENGE, target="enemy", priority=0.45),
    ]
    # WEALTH succeeded -> should decay below REVENGE; ordering flips.
    out = reprioritize(goals, {"goal_type": WEALTH, "target": "", "success": True})
    assert out[0].type == REVENGE

    # REVENGE thwarted -> bumped above WEALTH.
    goals2 = [
        Goal(type=REVENGE, target="enemy", priority=0.4),
        Goal(type=WEALTH, target="", priority=0.5),
    ]
    out2 = reprioritize(
        goals2, {"goal_type": REVENGE, "target": "enemy", "success": False}
    )
    assert out2[0].type == REVENGE


# ── Goal row mapping ───────────────────────────────────────────────────


def test_goal_to_row_and_from_row_round_trip() -> None:
    g = Goal(type=REVENGE, target="enemy", priority=0.7, progress=0.3)
    row = g.to_row()
    assert row["goal_type"] == REVENGE
    assert row["target"] == "enemy"
    assert row["priority"] == 0.7
    assert row["progress"] == 0.3
    back = Goal.from_row(row)
    assert back == g


# ── persistence round-trip ─────────────────────────────────────────────


def test_save_then_load_round_trips(store: EmergentStore) -> None:
    goals = generate_goals(
        "npc-7",
        ctx={"relationships": {"e": -0.8, "luv": 0.9}, "faction": "tyger"},
    )
    assert save_goals("npc-7", goals, store=store) is True

    loaded = load_goals("npc-7", store=store)
    assert {g.type for g in loaded} == {g.type for g in goals}
    # priorities + targets preserved (compare by (type, target) -> priority)
    orig = {(g.type, g.target): g.priority for g in goals}
    seen = {(g.type, g.target): g.priority for g in loaded}
    assert seen == orig
