"""Unit tests for the EmergentStore persistent sim store (Task A1).

Covers faction upsert (incl. partial update) round-trips, territory set/get,
goal replacement semantics, world-event logging/ordering/deserialization,
counting, an 8-thread concurrent-write stress, and reset(). Uses an explicit
temp db path (``tmp_path``) so the real emergent database is never touched.

Version: v1.63.0 [2026-06-15]

Change Log:
    v1.63.0 [2026-06-15] — Initial tests for the emergent persistent sim store
                            (A1): factions, territory, goals, world events,
                            concurrency, reset.
"""
from __future__ import annotations

import threading

import pytest

from engine.world.emergent.store import EmergentStore, get_emergent_store


@pytest.fixture
def store(tmp_path) -> EmergentStore:
    """Return an EmergentStore backed by an isolated temp database."""
    return EmergentStore(path=tmp_path / "emergent.db")


# ── factions ──────────────────────────────────────────────────────────


def test_faction_upsert_and_read_round_trip(store: EmergentStore) -> None:
    store.upsert_faction(
        "arasaka", power=10.0, treasury=500, data={"goals": ["expand"]}
    )
    f = store.get_faction("arasaka")
    assert f is not None
    assert f["faction_id"] == "arasaka"
    assert f["power"] == 10.0
    assert f["treasury"] == 500
    assert f["data"] == {"goals": ["expand"]}


def test_get_faction_unknown_returns_none(store: EmergentStore) -> None:
    assert store.get_faction("nobody") is None


def test_faction_partial_update_only_overwrites_provided(store: EmergentStore) -> None:
    store.upsert_faction("militech", power=5.0, treasury=200, data={"k": 1})
    # Update only treasury — power and data must survive.
    store.upsert_faction("militech", treasury=350)
    f = store.get_faction("militech")
    assert f is not None
    assert f["power"] == 5.0
    assert f["treasury"] == 350
    assert f["data"] == {"k": 1}
    # Update only power.
    store.upsert_faction("militech", power=9.5)
    f = store.get_faction("militech")
    assert f["power"] == 9.5
    assert f["treasury"] == 350


def test_all_factions(store: EmergentStore) -> None:
    store.upsert_faction("a", power=1.0)
    store.upsert_faction("b", power=2.0)
    ids = {f["faction_id"] for f in store.all_factions()}
    assert ids == {"a", "b"}


# ── territory ─────────────────────────────────────────────────────────


def test_territory_set_get_and_all(store: EmergentStore) -> None:
    store.set_territory("watson", "arasaka", contested=True, data={"heat": 3})
    t = store.get_territory("watson")
    assert t is not None
    assert t["district_id"] == "watson"
    assert t["faction_id"] == "arasaka"
    assert t["contested"] is True
    assert t["data"] == {"heat": 3}

    store.set_territory("pacifica", "voodoo")
    all_t = store.all_territory()
    assert {t["district_id"] for t in all_t} == {"watson", "pacifica"}
    pac = next(t for t in all_t if t["district_id"] == "pacifica")
    assert pac["contested"] is False


def test_get_territory_unknown_returns_none(store: EmergentStore) -> None:
    assert store.get_territory("void") is None


def test_territory_set_overwrites(store: EmergentStore) -> None:
    store.set_territory("watson", "arasaka")
    store.set_territory("watson", "militech", contested=True)
    t = store.get_territory("watson")
    assert t["faction_id"] == "militech"
    assert t["contested"] is True


# ── goals ─────────────────────────────────────────────────────────────


def test_set_goals_replaces_not_appends(store: EmergentStore) -> None:
    store.set_goals(
        "npc-1",
        [
            {"goal_type": "earn", "target": "credits", "priority": 1.0, "progress": 0.0},
            {"goal_type": "evade", "target": "ncpd", "priority": 0.5, "progress": 0.2},
        ],
    )
    assert len(store.get_goals("npc-1")) == 2

    # Replace with a single new goal — must NOT append to the prior two.
    store.set_goals(
        "npc-1",
        [{"goal_type": "ally", "target": "arasaka", "priority": 0.8, "progress": 0.0}],
    )
    goals = store.get_goals("npc-1")
    assert len(goals) == 1
    assert goals[0]["goal_type"] == "ally"
    assert goals[0]["target"] == "arasaka"
    assert goals[0]["priority"] == 0.8


def test_get_goals_round_trips_data(store: EmergentStore) -> None:
    store.set_goals(
        "npc-2",
        [{"goal_type": "hunt", "target": "x", "priority": 1.0,
          "progress": 0.3, "data": {"steps": [1, 2, 3]}}],
    )
    g = store.get_goals("npc-2")[0]
    assert g["data"] == {"steps": [1, 2, 3]}
    assert g["progress"] == 0.3


def test_get_goals_unknown_returns_empty(store: EmergentStore) -> None:
    assert store.get_goals("ghost") == []


def test_set_goals_empty_clears(store: EmergentStore) -> None:
    store.set_goals("npc-3", [{"goal_type": "a", "target": "t", "priority": 1.0}])
    store.set_goals("npc-3", [])
    assert store.get_goals("npc-3") == []


# ── world events ──────────────────────────────────────────────────────


def test_log_event_increasing_ids_and_recent_newest_first(store: EmergentStore) -> None:
    id1 = store.log_event("war", "arasaka", "attack begins")
    id2 = store.log_event("deal", "militech", "truce", payload={"terms": ["x"]})
    assert id1 > 0
    assert id2 > id1
    recent = store.recent_events(10)
    assert len(recent) == 2
    # newest-first
    assert recent[0]["id"] == id2
    assert recent[1]["id"] == id1
    # payload deserialized
    assert recent[0]["payload"] == {"terms": ["x"]}
    assert recent[1]["payload"] == {}
    # ts auto-populated
    assert recent[0]["ts"]


def test_log_event_persistent_flag(store: EmergentStore) -> None:
    store.log_event("blip", "x", "transient", persistent=False)
    ev = store.recent_events(1)[0]
    assert ev["persistent"] is False


def test_count_events(store: EmergentStore) -> None:
    assert store.count_events() == 0
    store.log_event("a", "x", "one")
    store.log_event("b", "y", "two")
    assert store.count_events() == 3 - 1  # 2


# ── concurrency ───────────────────────────────────────────────────────


def test_concurrent_event_logging_no_corruption(store: EmergentStore) -> None:
    threads_n = 8
    per_thread = 50
    errors: list[Exception] = []

    def worker(tid: int) -> None:
        try:
            for i in range(per_thread):
                store.log_event("stress", f"t{tid}", f"msg-{tid}-{i}")
        except Exception as exc:  # pragma: no cover - should never happen
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert store.count_events() == threads_n * per_thread
    # All ids must be unique (no corruption / collisions).
    all_events = store.recent_events(threads_n * per_thread)
    ids = [e["id"] for e in all_events]
    assert len(ids) == len(set(ids))
    assert len(ids) == threads_n * per_thread


# ── reset ─────────────────────────────────────────────────────────────


def test_reset_empties_all_tables(store: EmergentStore) -> None:
    store.upsert_faction("a", power=1.0)
    store.set_territory("d", "a")
    store.set_goals("n", [{"goal_type": "g", "target": "t", "priority": 1.0}])
    store.log_event("e", "x", "s")

    store.reset()

    assert store.all_factions() == []
    assert store.all_territory() == []
    assert store.get_goals("n") == []
    assert store.count_events() == 0


# ── singleton ─────────────────────────────────────────────────────────


def test_singleton_returns_same_instance() -> None:
    a = get_emergent_store()
    b = get_emergent_store()
    assert a is b
