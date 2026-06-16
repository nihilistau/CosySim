"""Unit tests for the random character generator + world-population seeding (A7).

These tests exercise :mod:`engine.world.character_gen` against an ISOLATED temp
:class:`~content.simulation.database.db.Database` (the ``temp_db`` conftest
fixture), so the real simulation DB is never polluted. The routine-manager seam
is reset per test so registrations don't leak.

They pin the behaviour the spec requires:
    * ``generate_character`` produces a valid character — gendered name matches
      sex, traits are VARIED (not all 0.5), metadata carries ``backstory`` +
      ``generated``, and a canonical ``faction`` is stored when provided;
    * ``seed_generated_population(count=15, faction_count=10)`` creates 15 NPCs,
      10 of them factioned and distributed across the canonical factions;
    * seeding is IDEMPOTENT — a second call creates nothing;
    * ``character_faction`` returns the stored canonical id (and ``None`` when
      unaffiliated).

Version: v1.63.0 [2026-06-15]

Change Log:
    v1.63.0 [2026-06-15] — Initial tests for the random character generator (A7):
                            gendered-name/varied-traits/metadata generation,
                            canonical-faction storage, 15/10 population seeding,
                            idempotency, and the character_faction read helper.
"""
from __future__ import annotations

import random

import pytest

from engine.world import character_gen
from engine.world.character_gen import (
    CANONICAL_FACTIONS,
    FEMALE_FIRST_NAMES,
    MALE_FIRST_NAMES,
    character_faction,
    generate_character,
    seed_cast_factions,
    seed_generated_population,
)


@pytest.fixture(autouse=True)
def _reset_routines():
    """Reset the RoutineManager singleton around each test (no registration leak)."""
    from engine.world.npc_routines import reset_routine_manager

    reset_routine_manager()
    yield
    reset_routine_manager()


# ══════════════════════════════════════════════════════════════════════
#  generate_character
# ══════════════════════════════════════════════════════════════════════


def test_generate_character_female_name_matches_sex(temp_db):
    """A female NPC gets a first name from the female pool."""
    rng = random.Random(1)
    cid = generate_character(sex="female", rng=rng, db=temp_db)
    assert cid is not None

    char = temp_db.get_character(cid)
    assert char["sex"] == "female"
    first = char["name"].split()[0]
    assert first in FEMALE_FIRST_NAMES
    assert first not in MALE_FIRST_NAMES or first in FEMALE_FIRST_NAMES


def test_generate_character_male_name_matches_sex(temp_db):
    """A male NPC gets a first name from the male pool."""
    rng = random.Random(2)
    cid = generate_character(sex="male", rng=rng, db=temp_db)
    char = temp_db.get_character(cid)
    assert char["sex"] == "male"
    assert char["name"].split()[0] in MALE_FIRST_NAMES


def test_generate_character_traits_are_varied(temp_db):
    """Generated traits are random per-trait, not the default 0.5 sea."""
    rng = random.Random(7)
    cid = generate_character(rng=rng, db=temp_db)
    state = temp_db.get_character_state(cid)

    traits = [
        state["warmth"], state["formality"], state["humor"],
        state["flirtiness"], state["intelligence"], state["creativity"],
    ]
    # Not all identical, and at least one differs from the 0.5 default.
    assert len(set(traits)) > 1
    assert any(abs(t - 0.5) > 1e-6 for t in traits)


def test_generate_character_metadata_has_backstory_and_flag(temp_db):
    """Metadata carries a backstory and the generated flag."""
    cid = generate_character(rng=random.Random(3), db=temp_db)
    char = temp_db.get_character(cid)
    meta = char["metadata"]
    assert meta.get("generated") is True
    assert isinstance(meta.get("backstory"), str) and meta["backstory"]
    assert "generated" in char["tags"]


def test_generate_character_stores_canonical_faction(temp_db):
    """When a faction is supplied it lands on metadata.faction."""
    cid = generate_character(faction="NeoTech", rng=random.Random(4), db=temp_db)
    char = temp_db.get_character(cid)
    assert char["metadata"].get("faction") == "NeoTech"
    assert character_faction(cid, db=temp_db) == "NeoTech"


def test_generate_character_unaffiliated_has_no_faction(temp_db):
    """No faction supplied -> metadata has no faction, helper returns None."""
    cid = generate_character(rng=random.Random(5), db=temp_db)
    assert "faction" not in temp_db.get_character(cid)["metadata"]
    assert character_faction(cid, db=temp_db) is None


# ══════════════════════════════════════════════════════════════════════
#  seed_generated_population
# ══════════════════════════════════════════════════════════════════════


def test_seed_population_creates_15_with_10_factioned(temp_db):
    """15 NPCs created; 10 factioned and distributed across the canonical six."""
    rng = random.Random(123)
    summary = seed_generated_population(count=15, faction_count=10, rng=rng, db=temp_db)

    assert summary["created"] == 15
    assert summary["factioned"] == 10

    # The 10 factions are distributed across multiple canonical factions.
    by_faction = summary["by_faction"]
    assert sum(by_faction.values()) == 10
    assert all(f in CANONICAL_FACTIONS for f in by_faction)
    assert len(by_faction) >= 2  # genuinely distributed, not all one faction

    # The DB really holds 15 generated characters with mixed sex.
    generated = [
        c for c in temp_db.get_all_characters()
        if (c.get("metadata") or {}).get("generated")
    ]
    assert len(generated) == 15
    sexes = {c["sex"] for c in generated}
    assert "male" in sexes and "female" in sexes


def test_seed_population_is_idempotent(temp_db):
    """A second seed at the same count creates nothing more."""
    rng = random.Random(99)
    first = seed_generated_population(count=15, faction_count=10, rng=rng, db=temp_db)
    assert first["created"] == 15

    second = seed_generated_population(count=15, faction_count=10, rng=rng, db=temp_db)
    assert second["created"] == 0
    assert second["total"] == 15

    generated = [
        c for c in temp_db.get_all_characters()
        if (c.get("metadata") or {}).get("generated")
    ]
    assert len(generated) == 15


def test_seed_population_tops_up_to_count(temp_db):
    """Seeding only creates the shortfall up to the target count."""
    rng = random.Random(11)
    seed_generated_population(count=5, faction_count=2, rng=rng, db=temp_db)
    summary = seed_generated_population(count=8, faction_count=2, rng=rng, db=temp_db)
    assert summary["created"] == 3
    assert summary["total"] == 8


# ══════════════════════════════════════════════════════════════════════
#  seed_cast_factions + character_faction
# ══════════════════════════════════════════════════════════════════════


def test_seed_cast_factions_assigns_canonical_and_is_idempotent(temp_db):
    """Cast members get canonical factions once; a re-run assigns nothing new."""
    # temp_db seeds the default cast (lola/viktor/aria/frankie/mira) on init.
    assigned = seed_cast_factions(db=temp_db)
    assert assigned  # at least some cast got a faction
    for cid, faction in assigned.items():
        assert faction in CANONICAL_FACTIONS
        assert character_faction(cid, db=temp_db) == faction

    again = seed_cast_factions(db=temp_db)
    assert again == {}  # idempotent — nothing overwritten


def test_character_faction_unknown_returns_none(temp_db):
    """An unknown character id yields None, not an error."""
    assert character_faction("nonexistent-id", db=temp_db) is None
