"""
Tests for engine/events/event_bus.py — CosySim v0.68 "Dark Renaissance".

All tests patch the Nexus client so no real HTTP calls are made.
"""
from __future__ import annotations

from typing import List
from unittest.mock import MagicMock, patch

import pytest

from engine.events.event_bus import EventBus, EventTypes, get_event_bus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_nexus():
    """Patch get_nexus_client for every test in this module."""
    with patch("engine.events.event_bus.get_nexus_client") as mock_factory:
        mock_client = MagicMock()
        mock_factory.return_value = mock_client
        yield mock_factory, mock_client


@pytest.fixture()
def bus(_patch_nexus):
    """Fresh EventBus instance (not the singleton) per test."""
    b = EventBus()
    yield b
    b.clear_handlers()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPublishAndSubscribe:
    def test_publish_and_subscribe(self, bus: EventBus):
        """Handler is called with a well-formed event dict when published."""
        received: List[dict] = []

        sub_id = bus.subscribe(EventTypes.WORLD_TICK, received.append, "test_subscriber")

        assert isinstance(sub_id, str) and sub_id  # non-empty string

        bus.publish(EventTypes.WORLD_TICK, {"tick": 1}, scene="world")

        assert len(received) == 1
        evt = received[0]
        assert evt["event_type"] == EventTypes.WORLD_TICK
        assert evt["payload"] == {"tick": 1}
        assert evt["scene"] == "world"
        assert "id" in evt
        assert "timestamp" in evt
        assert "subscribers_notified" in evt

    def test_handler_receives_subscriber_id_in_notified(self, bus: EventBus):
        """subscribers_notified list reflects the subscriber_id label."""
        received: List[dict] = []
        bus.subscribe(EventTypes.WORLD_TICK, received.append, "my_label")
        bus.publish(EventTypes.WORLD_TICK, {})

        evt = received[0]
        assert "my_label" in evt["subscribers_notified"]

    def test_scene_defaults_to_empty_string(self, bus: EventBus):
        """scene field is empty string when not provided."""
        received: List[dict] = []
        bus.subscribe(EventTypes.WORLD_EVENT, received.append)
        bus.publish(EventTypes.WORLD_EVENT, {})
        assert received[0]["scene"] == ""

    def test_subscribe_returns_unique_ids(self, bus: EventBus):
        """Each subscribe call returns a distinct subscription ID."""
        id1 = bus.subscribe(EventTypes.WORLD_TICK, lambda e: None)
        id2 = bus.subscribe(EventTypes.WORLD_TICK, lambda e: None)
        assert id1 != id2

    def test_subscribe_raises_on_empty_event_type(self, bus: EventBus):
        with pytest.raises(ValueError, match="event_type"):
            bus.subscribe("", lambda e: None)

    def test_subscribe_raises_on_non_callable_handler(self, bus: EventBus):
        with pytest.raises(ValueError, match="callable"):
            bus.subscribe(EventTypes.WORLD_TICK, "not_a_callable")  # type: ignore[arg-type]

    def test_publish_ignores_empty_event_type(self, bus: EventBus, caplog):
        """publish() with empty event_type logs a warning and is a no-op."""
        import logging
        with caplog.at_level(logging.WARNING, logger="engine.events.event_bus"):
            bus.publish("", {})
        assert any("empty event_type" in r.message for r in caplog.records)


class TestUnsubscribe:
    def test_unsubscribe(self, bus: EventBus):
        """Handler is NOT called after unsubscription."""
        received: List[dict] = []
        sub_id = bus.subscribe(EventTypes.ARENA_BET_WON, received.append)

        removed = bus.unsubscribe(sub_id)

        assert removed is True
        bus.publish(EventTypes.ARENA_BET_WON, {"amount": 100})
        assert received == []

    def test_unsubscribe_unknown_id_returns_false(self, bus: EventBus):
        result = bus.unsubscribe("non-existent-id-xyz")
        assert result is False

    def test_unsubscribe_twice_returns_false_second_time(self, bus: EventBus):
        sub_id = bus.subscribe(EventTypes.ARENA_BET_LOST, lambda e: None)
        assert bus.unsubscribe(sub_id) is True
        assert bus.unsubscribe(sub_id) is False


class TestEventHistory:
    def test_event_history_stored(self, bus: EventBus):
        """Published events appear in get_history()."""
        bus.publish(EventTypes.ECONOMY_TRANSACTION, {"delta": -50}, scene="casino")
        history = bus.get_history(EventTypes.ECONOMY_TRANSACTION)
        assert len(history) == 1
        assert history[0]["payload"] == {"delta": -50}

    def test_event_history_limit(self, bus: EventBus):
        """get_history limit parameter is respected."""
        for i in range(10):
            bus.publish(EventTypes.WORLD_TICK, {"tick": i})
        result = bus.get_history(EventTypes.WORLD_TICK, limit=3)
        assert len(result) == 3
        # Should be the 3 most-recent ticks
        assert result[-1]["payload"] == {"tick": 9}
        assert result[0]["payload"] == {"tick": 7}

    def test_event_history_no_filter(self, bus: EventBus):
        """get_history() with empty event_type returns all event types."""
        bus.publish(EventTypes.WORLD_TICK, {})
        bus.publish(EventTypes.ECONOMY_TRANSACTION, {})
        all_events = bus.get_history(limit=50)
        types = {e["event_type"] for e in all_events}
        assert EventTypes.WORLD_TICK in types
        assert EventTypes.ECONOMY_TRANSACTION in types

    def test_event_history_filter_by_type(self, bus: EventBus):
        """get_history filters to only the requested event type."""
        bus.publish(EventTypes.WORLD_TICK, {})
        bus.publish(EventTypes.WORLD_EVENT, {})
        result = bus.get_history(EventTypes.WORLD_TICK)
        assert all(e["event_type"] == EventTypes.WORLD_TICK for e in result)

    def test_history_ring_capped_at_max(self, bus: EventBus):
        """History ring does not grow beyond _MAX_HISTORY."""
        cap = EventBus._MAX_HISTORY
        for i in range(cap + 10):
            bus.publish(EventTypes.WORLD_TICK, {"i": i})
        assert len(bus._history) == cap

    def test_history_newest_last(self, bus: EventBus):
        """History list is ordered oldest → newest."""
        for i in range(5):
            bus.publish(EventTypes.WORLD_TICK, {"i": i})
        hist = bus.get_history(EventTypes.WORLD_TICK)
        payloads = [e["payload"]["i"] for e in hist]
        assert payloads == sorted(payloads)


class TestMultipleSubscribers:
    def test_multiple_subscribers_all_notified(self, bus: EventBus):
        """All subscribers for the same event type receive the event."""
        log_a: List[dict] = []
        log_b: List[dict] = []

        bus.subscribe(EventTypes.ARENA_MATCH_START, log_a.append, "scene_a")
        bus.subscribe(EventTypes.ARENA_MATCH_START, log_b.append, "scene_b")

        bus.publish(EventTypes.ARENA_MATCH_START, {"fighters": ["A", "B"]})

        assert len(log_a) == 1
        assert len(log_b) == 1
        assert log_a[0]["id"] == log_b[0]["id"]  # Same event

    def test_subscriber_only_receives_its_event_type(self, bus: EventBus):
        """A subscriber for event A does not receive events of type B."""
        received: List[dict] = []
        bus.subscribe(EventTypes.CASINO_MAJOR_WIN, received.append)
        bus.publish(EventTypes.CASINO_DEBT_CREATED, {"amount": 1000})
        assert received == []


class TestWildcardNoneWhenUnsubscribed:
    """Mirrors the ticket's test_wildcard_none_when_unsubscribed requirement."""

    def test_no_handlers_called_after_unsubscribe(self, bus: EventBus):
        """After unsubscribing, zero handlers are notified."""
        received: List[dict] = []
        sub_id = bus.subscribe(EventTypes.HEIST_JOB_COMPLETE, received.append)
        bus.unsubscribe(sub_id)
        bus.publish(EventTypes.HEIST_JOB_COMPLETE, {"crew": ["Mira", "Zax"]})
        assert received == []

    def test_subscribers_notified_empty_with_no_subscribers(self, bus: EventBus):
        """subscribers_notified is an empty list when no handlers are registered."""
        bus.publish(EventTypes.HEIST_CREW_COMPROMISED, {})
        history = bus.get_history(EventTypes.HEIST_CREW_COMPROMISED)
        assert history[0]["subscribers_notified"] == []


class TestSingleton:
    def test_singleton(self):
        """get_event_bus() always returns the same instance."""
        bus_a = get_event_bus()
        bus_b = get_event_bus()
        assert bus_a is bus_b

    def test_singleton_is_event_bus_instance(self):
        assert isinstance(get_event_bus(), EventBus)


class TestEventTypesConstants:
    def test_event_types_constants(self):
        """All known event type constants are non-empty strings."""
        constants = [
            EventTypes.ARENA_BET_WON,
            EventTypes.ARENA_BET_LOST,
            EventTypes.ARENA_MATCH_START,
            EventTypes.ARENA_MATCH_END,
            EventTypes.CASINO_MAJOR_WIN,
            EventTypes.CASINO_DEBT_CREATED,
            EventTypes.HEIST_JOB_COMPLETE,
            EventTypes.HEIST_CREW_COMPROMISED,
            EventTypes.PHONE_HACKER_MESSAGE,
            EventTypes.PHONE_JOB_ACCEPTED,
            EventTypes.ECONOMY_LOW_BALANCE,
            EventTypes.ECONOMY_DEBT_OVERDUE,
            EventTypes.ECONOMY_TRANSACTION,
            EventTypes.NEONCITY_FACTION_SHIFT,
            EventTypes.NEONCITY_WORLD_EVENT,
            EventTypes.DIRECTOR_BEAT_FIRED,
            EventTypes.WORLD_TICK,
            EventTypes.WORLD_EVENT,
        ]
        for c in constants:
            assert isinstance(c, str) and c, f"Constant is empty or not a string: {c!r}"

    def test_event_type_values_are_dot_namespaced(self):
        """All constant values follow the 'namespace.event' dot-notation."""
        constants = [v for k, v in vars(EventTypes).items() if not k.startswith("_")]
        for c in constants:
            assert "." in c, f"EventTypes constant {c!r} missing dot namespace"

    def test_event_type_values_are_unique(self):
        """No two EventTypes constants share the same string value."""
        values = [v for k, v in vars(EventTypes).items() if not k.startswith("_")]
        assert len(values) == len(set(values)), "Duplicate EventTypes values detected"


class TestClearHandlers:
    def test_clear_handlers(self, bus: EventBus):
        """clear_handlers() prevents further handler invocations."""
        received: List[dict] = []
        bus.subscribe(EventTypes.WORLD_TICK, received.append)
        bus.subscribe(EventTypes.WORLD_EVENT, received.append)

        bus.clear_handlers()

        bus.publish(EventTypes.WORLD_TICK, {})
        bus.publish(EventTypes.WORLD_EVENT, {})

        assert received == []

    def test_clear_handlers_does_not_clear_history(self, bus: EventBus):
        """clear_handlers() does not wipe the history ring."""
        bus.subscribe(EventTypes.WORLD_TICK, lambda e: None)
        bus.publish(EventTypes.WORLD_TICK, {"pre": True})
        bus.clear_handlers()
        # History still intact
        assert len(bus.get_history(EventTypes.WORLD_TICK)) == 1

    def test_resubscribe_after_clear(self, bus: EventBus):
        """New subscriptions work normally after clear_handlers()."""
        received: List[dict] = []
        bus.subscribe(EventTypes.WORLD_TICK, lambda e: None)
        bus.clear_handlers()
        bus.subscribe(EventTypes.WORLD_TICK, received.append)
        bus.publish(EventTypes.WORLD_TICK, {"after_clear": True})
        assert len(received) == 1


class TestNexusPersistence:
    def test_nexus_add_entry_called_on_publish(self, bus: EventBus, _patch_nexus):
        """Nexus add_entry is invoked once per published event."""
        _, mock_client = _patch_nexus
        bus.publish(EventTypes.ECONOMY_TRANSACTION, {"delta": 100}, scene="casino")
        mock_client.add_entry.assert_called_once()

    def test_nexus_add_entry_uses_history_content_type(self, bus: EventBus, _patch_nexus):
        """add_entry is called with content_type='history' and category='events'."""
        _, mock_client = _patch_nexus
        bus.publish(EventTypes.CASINO_MAJOR_WIN, {"winnings": 9999}, scene="casino")
        call_kwargs = mock_client.add_entry.call_args
        assert call_kwargs.kwargs.get("content_type") == "history"
        assert call_kwargs.kwargs.get("category") == "events"

    def test_nexus_failure_does_not_raise(self, bus: EventBus, _patch_nexus):
        """A Nexus exception must never propagate to the caller."""
        _, mock_client = _patch_nexus
        mock_client.add_entry.side_effect = RuntimeError("nexus down")
        # Should not raise
        bus.publish(EventTypes.WORLD_TICK, {"tick": 0})
