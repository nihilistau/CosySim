"""Unit tests for the FactionRegistry faction model (Task A2).

Drives the v1.63 Emergent Engine faction layer: seeding the six canonical
NeonCity factions, distributing the canonical districts as starting territory,
power/treasury arithmetic with clamping/flooring, territory flips (with the
matching world event and power nudges), symmetric relations, and the recovery
tick that keeps the world from flat-lining. Every test uses an explicit temp
``EmergentStore(path=...)`` so the real emergent database is never touched.

Version: v1.63.0 [2026-06-15]

Change Log:
    v1.63.0 [2026-06-15] — Initial tests for the faction model (A2): seed,
                            idempotency, power/treasury bounds, territory flip,
                            relations, recovery tick.
"""
from __future__ import annotations

import pytest

from engine.world.emergent.factions import (
    DISTRICTS,
    FACTION_IDS,
    FactionRegistry,
)
from engine.world.emergent.store import EmergentStore


@pytest.fixture
def registry(tmp_path) -> FactionRegistry:
    """Return a FactionRegistry backed by an isolated temp database."""
    return FactionRegistry(store=EmergentStore(path=tmp_path / "emergent.db"))


# ── identity constants ────────────────────────────────────────────────


def test_faction_ids_match_player_state() -> None:
    assert FACTION_IDS == [
        "OmniCorp",
        "NeoTech",
        "BlackMarket",
        "Ghost_Net",
        "SynthSec",
        "DeepState",
    ]


# ── seeding ───────────────────────────────────────────────────────────


def test_seed_creates_exactly_six_factions(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    factions = registry.store.all_factions()
    assert len(factions) == 6
    assert {f["faction_id"] for f in factions} == set(FACTION_IDS)


def test_seed_sets_start_power_and_treasury(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    for fid in FACTION_IDS:
        assert registry.power_of(fid) == 50.0
        assert registry.treasury_of(fid) == 1000


def test_seed_distributes_every_district_exactly_once(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    # Every district owned by exactly one faction, none orphaned.
    owners = {t["district_id"]: t["faction_id"] for t in registry.store.all_territory()}
    assert set(owners.keys()) == set(DISTRICTS)
    # Union of all factions' territory sets == all districts, no overlaps.
    seen: list[str] = []
    for fid in FACTION_IDS:
        seen.extend(registry.territory_of(fid))
    assert sorted(seen) == sorted(DISTRICTS)
    assert len(seen) == len(set(seen))  # no district owned by two factions


def test_seed_starts_relations_neutral(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    assert registry.relation("OmniCorp", "NeoTech") == "neutral"


def test_seed_is_idempotent(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    registry.shift_power("OmniCorp", -20)  # mutate
    registry.seed_if_empty()  # second call must NOT reset
    assert len(registry.store.all_factions()) == 6
    assert registry.power_of("OmniCorp") == 30.0


# ── power ──────────────────────────────────────────────────────────────


def test_shift_power_clamps_at_zero(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    new = registry.shift_power("OmniCorp", -999)
    assert new == 0.0
    assert registry.power_of("OmniCorp") == 0.0


def test_shift_power_clamps_at_hundred(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    new = registry.shift_power("OmniCorp", 999)
    assert new == 100.0
    assert registry.power_of("OmniCorp") == 100.0


def test_shift_power_persists(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    registry.shift_power("NeoTech", 10)
    # Re-read through a fresh registry on the same store.
    fresh = FactionRegistry(store=registry.store)
    assert fresh.power_of("NeoTech") == 60.0


# ── treasury ───────────────────────────────────────────────────────────


def test_adjust_treasury_floors_at_zero(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    new = registry.adjust_treasury("OmniCorp", -999999)
    assert new == 0
    assert registry.treasury_of("OmniCorp") == 0


def test_adjust_treasury_adds(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    new = registry.adjust_treasury("OmniCorp", 250)
    assert new == 1250


# ── territory flip ─────────────────────────────────────────────────────


def test_flip_territory_reassigns_and_updates_sets(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    # Pick a district and its current owner.
    district = DISTRICTS[0]
    loser = registry.store.get_territory(district)["faction_id"]
    winner = next(fid for fid in FACTION_IDS if fid != loser)

    ok = registry.flip_territory(district, winner, by="test")
    assert ok is True

    # Territory table reassigned.
    assert registry.store.get_territory(district)["faction_id"] == winner
    # Winner gained the district, loser lost it.
    assert district in registry.territory_of(winner)
    assert district not in registry.territory_of(loser)


def test_flip_territory_emits_persistent_event(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    district = DISTRICTS[1]
    loser = registry.store.get_territory(district)["faction_id"]
    winner = next(fid for fid in FACTION_IDS if fid != loser)

    registry.flip_territory(district, winner, by="raid")
    ev = registry.store.recent_events(1)[0]
    assert ev["kind"] == "faction_territory"
    assert ev["persistent"] is True
    assert ev["actor"] == "raid"


def test_flip_territory_moves_power(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    district = DISTRICTS[2]
    loser = registry.store.get_territory(district)["faction_id"]
    winner = next(fid for fid in FACTION_IDS if fid != loser)
    loser_before = registry.power_of(loser)
    winner_before = registry.power_of(winner)

    registry.flip_territory(district, winner)

    assert registry.power_of(loser) < loser_before  # loser down
    assert registry.power_of(winner) > winner_before  # winner up


def test_flip_territory_noop_when_already_owned(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    district = DISTRICTS[3]
    owner = registry.store.get_territory(district)["faction_id"]
    power_before = registry.power_of(owner)
    # Flipping to the current owner should not double-count power.
    registry.flip_territory(district, owner)
    assert registry.power_of(owner) == power_before
    assert district in registry.territory_of(owner)


# ── relations ──────────────────────────────────────────────────────────


def test_set_relation_is_symmetric(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    registry.set_relation("OmniCorp", "NeoTech", "ally")
    assert registry.relation("OmniCorp", "NeoTech") == "ally"
    assert registry.relation("NeoTech", "OmniCorp") == "ally"


def test_declare_war_sets_war_both_ways(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    registry.declare_war("BlackMarket", "SynthSec")
    assert registry.relation("BlackMarket", "SynthSec") == "war"
    assert registry.relation("SynthSec", "BlackMarket") == "war"


def test_form_alliance_sets_ally_both_ways(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    registry.form_alliance("Ghost_Net", "DeepState")
    assert registry.relation("Ghost_Net", "DeepState") == "ally"
    assert registry.relation("DeepState", "Ghost_Net") == "ally"


def test_relation_unknown_pair_is_neutral(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    assert registry.relation("OmniCorp", "DeepState") == "neutral"


# ── recovery tick ──────────────────────────────────────────────────────


def test_recovery_tick_lifts_weak_faction(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    registry.shift_power("OmniCorp", -50)  # power -> 0, below floor
    assert registry.power_of("OmniCorp") == 0.0
    registry.recovery_tick()
    assert registry.power_of("OmniCorp") == 2.0  # nudged up by recovery_rate


def test_recovery_tick_leaves_healthy_faction(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    registry.shift_power("NeoTech", 30)  # power -> 80, healthy
    assert registry.power_of("NeoTech") == 80.0
    registry.recovery_tick()
    assert registry.power_of("NeoTech") == 80.0  # unchanged


def test_recovery_tick_does_not_undo_territory_flip(registry: FactionRegistry) -> None:
    registry.seed_if_empty()
    district = DISTRICTS[0]
    loser = registry.store.get_territory(district)["faction_id"]
    winner = next(fid for fid in FACTION_IDS if fid != loser)
    registry.flip_territory(district, winner)
    registry.recovery_tick()
    # Territory ownership untouched by recovery.
    assert registry.store.get_territory(district)["faction_id"] == winner
    assert district in registry.territory_of(winner)
