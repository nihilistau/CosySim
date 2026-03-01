"""Tests for engine.mechanics.consequences — F6 Consequence Engine."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, call, patch

import pytest

import engine.mechanics.consequences as cons_module
from engine.mechanics.consequences import (
    Consequence,
    ConsequenceStore,
    ConsequenceType,
    get_consequence_store,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton between tests."""
    original = cons_module._store_instance
    cons_module._store_instance = None
    yield
    cons_module._store_instance = original


@pytest.fixture()
def mock_nexus():
    """Patch get_nexus_client used inside consequences.py."""
    with patch("engine.mechanics.consequences.get_nexus_client") as mock_factory:
        client = MagicMock()
        client.search.return_value = []
        client.add_entry.return_value = "nexus-cid-001"
        client.update_entry.return_value = True
        client.delete_entry.return_value = True
        client.list_by_type.return_value = []
        mock_factory.return_value = client
        yield client


@pytest.fixture()
def store(mock_nexus):
    """Return a fresh ConsequenceStore backed by a mock Nexus."""
    return ConsequenceStore(nexus_client=mock_nexus)


def _make_consequence(
    fired: bool = False,
    fired_at: float | None = None,
    scheduled_at: float | None = None,
    target_scene: str = "lounge",
    player_id: str = "player",
) -> Consequence:
    """Build a test Consequence with controllable timing."""
    import uuid
    now = time.time()
    return Consequence(
        id=str(uuid.uuid4()),
        consequence_type=ConsequenceType.CONTACT,
        source_scene="casino",
        target_scene=target_scene,
        player_id=player_id,
        description="Test consequence",
        payload={"amount": 1000},
        scheduled_at=scheduled_at if scheduled_at is not None else now - 10,
        fired=fired,
        fired_at=fired_at,
        created_at=now - 100,
    )


# ---------------------------------------------------------------------------
# Consequence dataclass
# ---------------------------------------------------------------------------


def test_schedule_creates_consequence(store, mock_nexus):
    """schedule() creates a Consequence and persists it to Nexus."""
    c = store.schedule(
        consequence_type=ConsequenceType.CONTACT,
        source_scene="casino",
        target_scene="lounge",
        description="Mira calls",
        payload={"creditor": "mira"},
        delay_hours=24.0,
    )
    assert c.id
    assert c.consequence_type == ConsequenceType.CONTACT
    assert c.source_scene == "casino"
    assert c.target_scene == "lounge"
    assert not c.fired
    mock_nexus.add_entry.assert_called_once()


def test_is_due_when_past_schedule():
    """is_due() returns True when scheduled_at is in the past."""
    c = _make_consequence(scheduled_at=time.time() - 60)
    assert c.is_due() is True


def test_is_not_due_when_future():
    """is_due() returns False when scheduled_at is in the future."""
    c = _make_consequence(scheduled_at=time.time() + 3600)
    assert c.is_due() is False


def test_is_not_due_when_fired():
    """is_due() returns False even if past schedule when already fired."""
    c = _make_consequence(scheduled_at=time.time() - 60, fired=True)
    assert c.is_due() is False


# ---------------------------------------------------------------------------
# poll
# ---------------------------------------------------------------------------


def _serialised(*consequences) -> list:
    """Return a list of fake Nexus raw entries from Consequence objects."""
    import json
    return [
        {"id": f"nid-{c.id}", "title": f"consequence:{c.id}", "content": json.dumps(c.to_dict())}
        for c in consequences
    ]


def test_poll_returns_due_only(store, mock_nexus):
    """poll() returns only due consequences for the given player and scene."""
    due_c = _make_consequence(scheduled_at=time.time() - 10, target_scene="lounge")
    future_c = _make_consequence(scheduled_at=time.time() + 3600, target_scene="lounge")
    mock_nexus.list_by_type.return_value = _serialised(due_c, future_c)

    results = store.poll(scene="lounge")
    assert len(results) == 1
    assert results[0].id == due_c.id


def test_poll_excludes_fired(store, mock_nexus):
    """poll() never returns already-fired consequences."""
    fired_c = _make_consequence(
        scheduled_at=time.time() - 10, fired=True, fired_at=time.time() - 5
    )
    due_c = _make_consequence(scheduled_at=time.time() - 10)
    mock_nexus.list_by_type.return_value = _serialised(fired_c, due_c)

    results = store.poll()
    ids = [c.id for c in results]
    assert fired_c.id not in ids
    assert due_c.id in ids


def test_poll_filters_by_scene(store, mock_nexus):
    """poll() excludes consequences targeting a different scene."""
    lounge_c = _make_consequence(target_scene="lounge", scheduled_at=time.time() - 10)
    arena_c = _make_consequence(target_scene="arena", scheduled_at=time.time() - 10)
    mock_nexus.list_by_type.return_value = _serialised(lounge_c, arena_c)

    results = store.poll(scene="lounge")
    assert len(results) == 1
    assert results[0].id == lounge_c.id


def test_poll_filters_by_player(store, mock_nexus):
    """poll() excludes consequences belonging to a different player."""
    my_c = _make_consequence(player_id="player", scheduled_at=time.time() - 10)
    other_c = _make_consequence(player_id="other_player", scheduled_at=time.time() - 10)
    mock_nexus.list_by_type.return_value = _serialised(my_c, other_c)

    results = store.poll(player_id="player")
    assert len(results) == 1
    assert results[0].id == my_c.id


# ---------------------------------------------------------------------------
# mark_fired
# ---------------------------------------------------------------------------


def test_mark_fired(store, mock_nexus):
    """mark_fired updates the Nexus entry with fired=True."""
    import json
    c = _make_consequence()
    mock_nexus.search.return_value = [
        {"id": "nid-001", "title": f"consequence:{c.id}", "content": json.dumps(c.to_dict())}
    ]
    store.mark_fired(c.id)
    mock_nexus.update_entry.assert_called_once()
    updated_content = json.loads(mock_nexus.update_entry.call_args[1]["content"])
    assert updated_content["fired"] is True
    assert updated_content["fired_at"] is not None


def test_mark_fired_no_nexus_entry_is_safe(store, mock_nexus):
    """mark_fired does not raise if the Nexus entry is missing."""
    mock_nexus.search.return_value = []
    store.mark_fired("nonexistent-id")  # should not raise


# ---------------------------------------------------------------------------
# get_pending
# ---------------------------------------------------------------------------


def test_get_pending(store, mock_nexus):
    """get_pending() returns scheduled but not yet due consequences."""
    future_c = _make_consequence(scheduled_at=time.time() + 7200)
    past_due_c = _make_consequence(scheduled_at=time.time() - 10)
    fired_c = _make_consequence(
        scheduled_at=time.time() + 3600, fired=True, fired_at=time.time() - 5
    )
    mock_nexus.list_by_type.return_value = _serialised(future_c, past_due_c, fired_c)

    results = store.get_pending()
    ids = [c.id for c in results]
    assert future_c.id in ids
    assert past_due_c.id not in ids   # already due, not "pending"
    assert fired_c.id not in ids      # already fired


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------


def test_cancel(store, mock_nexus):
    """cancel() deletes the Nexus entry and returns True."""
    import json
    c = _make_consequence()
    mock_nexus.search.return_value = [
        {"id": "nid-del", "title": f"consequence:{c.id}", "content": json.dumps(c.to_dict())}
    ]
    result = store.cancel(c.id)
    assert result is True
    mock_nexus.delete_entry.assert_called_once_with("nid-del")


def test_cancel_missing_returns_false(store, mock_nexus):
    """cancel() returns False when no Nexus entry is found."""
    mock_nexus.search.return_value = []
    result = store.cancel("ghost-id")
    assert result is False


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------


def test_build_debt_consequence(store, mock_nexus):
    """build_debt_consequence creates a CONTACT consequence for 24 h."""
    c = store.build_debt_consequence(
        scene="casino", amount=5000, debtor="player", creditor_char="mira"
    )
    assert c.consequence_type == ConsequenceType.CONTACT
    assert c.source_scene == "casino"
    assert c.target_scene == "lounge"
    assert c.payload["creditor"] == "mira"
    assert c.payload["amount"] == 5000
    # Should be ~24 h in the future
    assert c.scheduled_at > time.time() + 3600 * 23


def test_build_heist_payout(store, mock_nexus):
    """build_heist_payout creates an ECONOMY_TRANSACTION for 8 h."""
    c = store.build_heist_payout(scene="heist", amount=20000)
    assert c.consequence_type == ConsequenceType.ECONOMY_TRANSACTION
    assert c.source_scene == "heist"
    assert c.payload["amount"] == 20000
    # Should be ~8 h in the future
    assert c.scheduled_at > time.time() + 3600 * 7
    assert c.scheduled_at < time.time() + 3600 * 9


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


def test_get_history(store, mock_nexus):
    """get_history returns fired consequences newest first."""
    import json
    early_fired = _make_consequence(fired=True, fired_at=time.time() - 200)
    late_fired = _make_consequence(fired=True, fired_at=time.time() - 10)
    unfired = _make_consequence()
    mock_nexus.list_by_type.return_value = _serialised(early_fired, late_fired, unfired)

    history = store.get_history()
    assert len(history) == 2
    # newest first
    assert history[0].id == late_fired.id
    assert history[1].id == early_fired.id


def test_get_history_limit(store, mock_nexus):
    """get_history respects the limit parameter."""
    fired_items = [
        _make_consequence(fired=True, fired_at=time.time() - i * 10)
        for i in range(10)
    ]
    mock_nexus.list_by_type.return_value = _serialised(*fired_items)
    history = store.get_history(limit=3)
    assert len(history) == 3


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------


def test_consequence_to_dict_from_dict_roundtrip():
    """Consequence survives a to_dict/from_dict round-trip intact."""
    c = _make_consequence()
    restored = Consequence.from_dict(c.to_dict())
    assert restored.id == c.id
    assert restored.consequence_type == c.consequence_type
    assert restored.source_scene == c.source_scene
    assert restored.fired == c.fired
    assert restored.payload == c.payload


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_singleton(mock_nexus):
    """get_consequence_store always returns the same instance."""
    with patch("engine.mechanics.consequences.get_nexus_client", return_value=mock_nexus):
        s1 = get_consequence_store()
        s2 = get_consequence_store()
        assert s1 is s2
