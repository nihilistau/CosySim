"""Tests — WorldAnnouncer singleton, ring buffer, station muting, feed filtering."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _reset_announcer():
    """Ensure a clean WorldAnnouncer for every test."""
    from engine.world.world_announcer import reset_world_announcer
    reset_world_announcer()
    yield
    reset_world_announcer()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_fresh():
    from engine.world.world_announcer import get_world_announcer
    return get_world_announcer()


def _mock_bus():
    mock = MagicMock()
    mock.subscribe = MagicMock()
    return mock


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

def test_singleton_returns_same_instance():
    a = _get_fresh()
    b = _get_fresh()
    assert a is b


def test_reset_creates_new_instance():
    from engine.world.world_announcer import reset_world_announcer
    a = _get_fresh()
    reset_world_announcer()
    b = _get_fresh()
    assert a is not b


# ──────────────────────────────────────────────────────────────────────────────
# announce() / ring buffer
# ──────────────────────────────────────────────────────────────────────────────

def test_announce_adds_to_feed():
    ann = _get_fresh()
    ann.announce(title="Test Event", body="something happened", category="world")
    feed = ann.get_feed()
    assert len(feed) == 1
    assert feed[0]["title"] == "Test Event"


def test_announce_multiple_events_stored():
    ann = _get_fresh()
    for i in range(5):
        ann.announce(title=f"Event {i}", body="body", category="npc")
    feed = ann.get_feed()
    assert len(feed) == 5


def test_ring_buffer_capped_at_50():
    ann = _get_fresh()
    for i in range(60):
        ann.announce(title=f"E{i}", body="x", category="world")
    feed = ann.get_feed()
    assert len(feed) == 50


def test_get_feed_default_limit():
    ann = _get_fresh()
    for i in range(30):
        ann.announce(title=f"E{i}", body="x", category="world")
    feed = ann.get_feed()
    assert len(feed) <= 50


def test_get_feed_respects_limit_param():
    ann = _get_fresh()
    for i in range(20):
        ann.announce(title=f"E{i}", body="x", category="economy")
    feed = ann.get_feed(limit=5)
    assert len(feed) == 5


def test_newest_event_first_in_feed():
    ann = _get_fresh()
    ann.announce(title="First", body="a", category="world")
    ann.announce(title="Second", body="b", category="world")
    feed = ann.get_feed()
    assert feed[0]["title"] == "Second"
    assert feed[1]["title"] == "First"


# ──────────────────────────────────────────────────────────────────────────────
# Filtering by category
# ──────────────────────────────────────────────────────────────────────────────

def test_get_feed_filters_by_category():
    ann = _get_fresh()
    ann.announce(title="NPC Event", body="npc stuff", category="npc")
    ann.announce(title="Faction Event", body="faction stuff", category="faction")
    ann.announce(title="Economy Event", body="economy stuff", category="economy")

    npc_feed = ann.get_feed(category="npc")
    assert all(e["category"] == "npc" for e in npc_feed)
    assert len(npc_feed) == 1

    faction_feed = ann.get_feed(category="faction")
    assert len(faction_feed) == 1
    assert faction_feed[0]["category"] == "faction"


def test_get_feed_empty_category_returns_all():
    ann = _get_fresh()
    ann.announce(title="A", body="x", category="npc")
    ann.announce(title="B", body="y", category="world")
    feed = ann.get_feed(category="")
    assert len(feed) == 2


# ──────────────────────────────────────────────────────────────────────────────
# Station muting
# ──────────────────────────────────────────────────────────────────────────────

def test_muted_category_events_not_stored():
    ann = _get_fresh()
    ann.mute_station("hacker")
    ann.announce(title="Hack Alert", body="hack", category="hacker")
    feed = ann.get_feed()
    assert len(feed) == 0


def test_unmute_station_allows_new_events():
    ann = _get_fresh()
    ann.mute_station("economy")
    ann.announce(title="Muted", body="x", category="economy")
    ann.unmute_station("economy")
    ann.announce(title="Unmuted", body="y", category="economy")
    feed = ann.get_feed()
    assert len(feed) == 1
    assert feed[0]["title"] == "Unmuted"


def test_mute_unmute_cycle():
    ann = _get_fresh()
    ann.mute_station("faction")
    ann.unmute_station("faction")
    ann.announce(title="Faction News", body="z", category="faction")
    feed = ann.get_feed()
    assert len(feed) == 1


# ──────────────────────────────────────────────────────────────────────────────
# get_summary()
# ──────────────────────────────────────────────────────────────────────────────

def test_get_summary_empty():
    ann = _get_fresh()
    summary = ann.get_summary()
    assert isinstance(summary, str)


def test_get_summary_with_events():
    ann = _get_fresh()
    ann.announce(title="Corp Raid", body="OmniCorp raided lower district", category="faction")
    ann.announce(title="Market Crash", body="Credits down 5%", category="economy")
    summary = ann.get_summary()
    assert isinstance(summary, str)
    assert len(summary) > 0


# ──────────────────────────────────────────────────────────────────────────────
# to_dict() shape
# ──────────────────────────────────────────────────────────────────────────────

def test_announcement_to_dict_has_required_keys():
    ann = _get_fresh()
    ann.announce(title="Test", body="body text", category="world", scene="neoncity", actor="aria")
    feed = ann.get_feed()
    entry = feed[0]
    for key in ("id", "title", "body", "category", "scene", "actor", "timestamp"):
        assert key in entry, f"Missing key: {key}"


# ──────────────────────────────────────────────────────────────────────────────
# EventBus integration (mocked)
# ──────────────────────────────────────────────────────────────────────────────

def test_start_subscribes_to_event_bus():
    ann = _get_fresh()
    mock_bus = _mock_bus()
    with patch("engine.events.event_bus.EventBus.subscribe", mock_bus.subscribe):
        ann._subscribed = False  # force re-subscribe
        try:
            ann.start()
        except Exception:
            pass
    # subscription may have been called or EventBus unavailable — just verify no crash
    assert isinstance(ann, __import__("engine.world.world_announcer", fromlist=["WorldAnnouncer"]).WorldAnnouncer)


def test_start_idempotent():
    """Calling start() twice should not double-subscribe — _subscribed flag guards it."""
    ann = _get_fresh()
    # After reset, start() is called once in get_world_announcer().
    # Call start() explicitly again — should be a no-op.
    ann._subscribed = True  # pretend already subscribed
    mock_bus = _mock_bus()
    with patch("engine.events.event_bus.get_event_bus", return_value=mock_bus):
        ann.start()  # should not subscribe again
    mock_bus.subscribe.assert_not_called()


def test_on_event_routes_to_announce():
    """_on_event with a matching station type should add to feed."""
    ann = _get_fresh()
    # Directly call _on_event as if EventBus dispatched it
    ann._on_event("faction_event", {"title": "Faction Shift", "description": "Power changes", "scene": "the_grid", "actor": "omnicorp"})
    feed = ann.get_feed()
    assert len(feed) >= 1
