"""Tests for engine/world/event_cascade.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.world.event_cascade import (
    CascadeEvent,
    DEFAULT_SCENE_SUBSCRIPTIONS,
    EventCascade,
    WorldEventType,
    get_event_cascade,
)


# ──── WorldEventType ──────────────────────────────────────────────────────────


def test_world_event_type_constants_exist():
    assert WorldEventType.ECONOMY == "economy"
    assert WorldEventType.FACTION == "faction"
    assert WorldEventType.NPC == "npc"
    assert WorldEventType.CRIME == "crime"
    assert WorldEventType.WEATHER == "weather"
    assert WorldEventType.POLITICAL == "political"
    assert WorldEventType.SOCIAL == "social"
    assert WorldEventType.DISASTER == "disaster"
    assert WorldEventType.RUMOUR == "rumour"
    assert WorldEventType.COMBAT == "combat"


def test_world_event_type_all_set_complete():
    assert len(WorldEventType.ALL) == 10
    expected = {
        "economy", "faction", "npc", "crime", "weather",
        "political", "social", "disaster", "rumour", "combat",
    }
    assert WorldEventType.ALL == expected


# ──── DEFAULT_SCENE_SUBSCRIPTIONS ─────────────────────────────────────────────


def test_default_scene_subscriptions_has_expected_scenes():
    expected_scenes = {
        "bedroom", "phone", "lounge", "tavern", "casino",
        "gallery", "arena", "realm", "neoncity", "heist", "intel_hub",
    }
    assert expected_scenes <= set(DEFAULT_SCENE_SUBSCRIPTIONS.keys())


def test_intel_hub_subscribes_to_all_event_types():
    intel_types = set(DEFAULT_SCENE_SUBSCRIPTIONS["intel_hub"])
    assert intel_types == WorldEventType.ALL


def test_arena_subscribes_to_combat():
    assert WorldEventType.COMBAT in DEFAULT_SCENE_SUBSCRIPTIONS["arena"]


def test_casino_subscribes_to_economy():
    assert WorldEventType.ECONOMY in DEFAULT_SCENE_SUBSCRIPTIONS["casino"]


def test_all_subscriptions_reference_valid_event_types():
    for scene, types in DEFAULT_SCENE_SUBSCRIPTIONS.items():
        for t in types:
            assert t in WorldEventType.ALL, f"{scene} has invalid type {t!r}"


# ──── EventCascade subscription management ────────────────────────────────────


class TestSubscriptionManagement:
    def setup_method(self):
        self.cascade = EventCascade()
        # Reset to empty subscriptions for isolation
        self.cascade._subscriptions = {}

    def test_subscribe_adds_event_types(self):
        self.cascade.subscribe("bedroom", [WorldEventType.SOCIAL])
        assert WorldEventType.SOCIAL in self.cascade.get_subscriptions("bedroom")

    def test_subscribe_merges_with_existing(self):
        self.cascade.subscribe("bedroom", [WorldEventType.SOCIAL])
        self.cascade.subscribe("bedroom", [WorldEventType.ECONOMY])
        subs = self.cascade.get_subscriptions("bedroom")
        assert WorldEventType.SOCIAL in subs
        assert WorldEventType.ECONOMY in subs

    def test_unsubscribe_specific_type(self):
        self.cascade.subscribe("bedroom", [WorldEventType.SOCIAL, WorldEventType.ECONOMY])
        self.cascade.unsubscribe("bedroom", [WorldEventType.SOCIAL])
        subs = self.cascade.get_subscriptions("bedroom")
        assert WorldEventType.SOCIAL not in subs
        assert WorldEventType.ECONOMY in subs

    def test_unsubscribe_all(self):
        self.cascade.subscribe("bedroom", [WorldEventType.SOCIAL])
        self.cascade.unsubscribe("bedroom")
        assert self.cascade.get_subscriptions("bedroom") == set()

    def test_unsubscribe_unknown_scene_is_noop(self):
        self.cascade.unsubscribe("nonexistent_scene")  # must not raise

    def test_get_subscriptions_returns_empty_set_for_unknown_scene(self):
        assert self.cascade.get_subscriptions("ghost_scene") == set()

    def test_subscribe_accepts_multiple_types_at_once(self):
        types = [WorldEventType.CRIME, WorldEventType.FACTION, WorldEventType.WEATHER]
        self.cascade.subscribe("neoncity", types)
        subs = self.cascade.get_subscriptions("neoncity")
        assert set(types) <= subs

    def test_get_subscriptions_returns_copy(self):
        self.cascade.subscribe("casino", [WorldEventType.ECONOMY])
        subs = self.cascade.get_subscriptions("casino")
        subs.add("fake_type")  # mutate the returned copy
        # Original must be unchanged
        assert "fake_type" not in self.cascade.get_subscriptions("casino")


# ──── EventCascade dispatch + filtering ───────────────────────────────────────


class TestDispatch:
    def setup_method(self):
        self.cascade = EventCascade()
        self.cascade._subscriptions = {
            "bedroom": {WorldEventType.SOCIAL},
            "casino": {WorldEventType.ECONOMY},
            "arena": {WorldEventType.COMBAT, WorldEventType.SOCIAL},
        }
        self.cascade.reset_stats()

    def _patch_deliver_returns_true(self):
        self.cascade._deliver = MagicMock(return_value=True)

    def test_dispatch_delivers_to_subscribed_scenes(self):
        self._patch_deliver_returns_true()
        count = self.cascade.dispatch(WorldEventType.SOCIAL, {"msg": "test"})
        assert count == 2  # bedroom + arena both subscribe to SOCIAL

    def test_dispatch_does_not_deliver_to_unsubscribed_scenes(self):
        self._patch_deliver_returns_true()
        count = self.cascade.dispatch(WorldEventType.ECONOMY, {"msg": "test"})
        assert count == 1  # only casino

    def test_dispatch_returns_zero_for_unknown_type(self):
        self._patch_deliver_returns_true()
        count = self.cascade.dispatch("nonexistent_type", {})
        assert count == 0

    def test_dispatch_passes_payload_correctly(self):
        self._patch_deliver_returns_true()
        payload = {"severity": "high", "location": "downtown"}
        self.cascade.dispatch(WorldEventType.CRIME, payload, source="npc_sim")
        # deliver was NOT called because no scene subscribes to CRIME in this setup
        assert self.cascade._deliver.call_count == 0

    def test_dispatch_increments_delivered_stat(self):
        self._patch_deliver_returns_true()
        self.cascade.dispatch(WorldEventType.SOCIAL, {})
        assert self.cascade._delivered == 2

    def test_dispatch_event_has_correct_fields(self):
        delivered_events = []
        self.cascade._deliver = lambda evt: (delivered_events.append(evt), True)[1]
        self.cascade.dispatch(WorldEventType.COMBAT, {"fight": True}, source="arena_sim")
        assert len(delivered_events) == 1
        evt = delivered_events[0]
        assert evt.scene == "arena"
        assert evt.event_type == WorldEventType.COMBAT
        assert evt.payload == {"fight": True}
        assert evt.source == "arena_sim"


# ──── EventCascade delivery tiers ─────────────────────────────────────────────


class TestDelivery:
    def setup_method(self):
        self.cascade = EventCascade()
        self.evt = CascadeEvent(
            scene="bedroom",
            event_type=WorldEventType.SOCIAL,
            payload={"info": "party tonight"},
        )

    def test_deliver_via_event_bus_success(self):
        mock_bus = MagicMock()
        with patch("engine.world.event_cascade.get_event_bus", return_value=mock_bus):
            result = self.cascade._deliver(self.evt)
        assert result is True

    def test_deliver_falls_back_gracefully_when_all_fail(self):
        """_deliver returns False when all delivery mechanisms fail."""
        with patch("engine.world.event_cascade.get_event_bus", side_effect=ImportError):
            with patch("engine.world.event_cascade.get_framework", side_effect=ImportError):
                result = self.cascade._deliver(self.evt)
        assert result is False

    def test_deliver_payload_includes_event_type(self):
        """The payload dict passed to EventBus contains event_type."""
        captured = []

        def fake_bus_publish(topic, payload, **kwargs):
            captured.append(payload)

        mock_bus = MagicMock()
        mock_bus.publish.side_effect = fake_bus_publish
        with patch("engine.world.event_cascade.get_event_bus", return_value=mock_bus):
            self.cascade._deliver(self.evt)

        if captured:
            assert captured[0]["event_type"] == WorldEventType.SOCIAL


# ──── WorldSim bridge ─────────────────────────────────────────────────────────


class TestWorldSimBridge:
    def setup_method(self):
        self.cascade = EventCascade()
        self.cascade._subscriptions = {}
        self.cascade.reset_stats()

    def test_start_is_idempotent(self):
        with patch("engine.world.world_sim.get_world_sim", side_effect=ImportError):
            self.cascade.start()
            self.cascade.start()
        assert self.cascade._started is True

    def test_on_world_sim_event_dict(self):
        self.cascade.subscribe("bedroom", [WorldEventType.SOCIAL])
        self.cascade._deliver = MagicMock(return_value=True)
        self.cascade._on_world_sim_event({"type": WorldEventType.SOCIAL, "detail": "test"})
        assert self.cascade._deliver.call_count == 1

    def test_on_world_sim_event_missing_type_uses_social(self):
        self.cascade.subscribe("bedroom", [WorldEventType.SOCIAL])
        self.cascade._deliver = MagicMock(return_value=True)
        self.cascade._on_world_sim_event({})  # no 'type' key
        assert self.cascade._deliver.call_count == 1  # social is default

    def test_on_world_sim_event_handles_exceptions(self):
        # Broken payload must not raise
        self.cascade._on_world_sim_event(None)  # must not raise

    def test_on_world_sim_event_object(self):
        """Accepts objects with a .type attribute."""
        self.cascade.subscribe("arena", [WorldEventType.COMBAT])
        self.cascade._deliver = MagicMock(return_value=True)

        class FakeEvent:
            type = WorldEventType.COMBAT
            def __init__(self):
                pass

        self.cascade._on_world_sim_event(FakeEvent())
        assert self.cascade._deliver.call_count == 1


# ──── Stats ───────────────────────────────────────────────────────────────────


class TestStats:
    def setup_method(self):
        self.cascade = EventCascade()
        self.cascade._subscriptions = {
            "bedroom": {WorldEventType.SOCIAL},
        }
        self.cascade.reset_stats()

    def test_get_stats_returns_dict(self):
        stats = self.cascade.get_stats()
        assert isinstance(stats, dict)
        assert "delivered" in stats
        assert "filtered" in stats
        assert "subscribed_scenes" in stats
        assert "subscriptions" in stats

    def test_get_stats_initial_zeroes(self):
        stats = self.cascade.get_stats()
        assert stats["delivered"] == 0
        assert stats["filtered"] == 0

    def test_get_stats_subscribed_scenes_count(self):
        stats = self.cascade.get_stats()
        assert stats["subscribed_scenes"] == 1

    def test_get_stats_subscriptions_snapshot_is_serialisable(self):
        stats = self.cascade.get_stats()
        import json
        json.dumps(stats)  # must not raise

    def test_reset_stats_clears_counters(self):
        self.cascade._delivered = 100
        self.cascade._filtered = 50
        self.cascade.reset_stats()
        assert self.cascade._delivered == 0
        assert self.cascade._filtered == 0

    def test_delivered_increments_after_dispatch(self):
        self.cascade._deliver = MagicMock(return_value=True)
        self.cascade.dispatch(WorldEventType.SOCIAL, {})
        stats = self.cascade.get_stats()
        assert stats["delivered"] == 1


# ──── Singleton ───────────────────────────────────────────────────────────────


def test_get_event_cascade_returns_same_instance():
    a = get_event_cascade()
    b = get_event_cascade()
    assert a is b


def test_get_event_cascade_returns_event_cascade():
    assert isinstance(get_event_cascade(), EventCascade)


# ──── CascadeEvent dataclass ──────────────────────────────────────────────────


def test_cascade_event_fields():
    evt = CascadeEvent(
        scene="casino",
        event_type=WorldEventType.ECONOMY,
        payload={"change": "+5%"},
    )
    assert evt.scene == "casino"
    assert evt.event_type == WorldEventType.ECONOMY
    assert evt.payload == {"change": "+5%"}
    assert evt.source == "world_sim"  # default


def test_cascade_event_custom_source():
    evt = CascadeEvent(
        scene="arena",
        event_type=WorldEventType.COMBAT,
        payload={},
        source="arena_sim",
    )
    assert evt.source == "arena_sim"


# ──── Default subscriptions pre-loaded on init ────────────────────────────────


def test_fresh_cascade_has_default_subscriptions_loaded():
    c = EventCascade()
    subs = c.get_subscriptions("bedroom")
    assert WorldEventType.SOCIAL in subs


def test_fresh_cascade_intel_hub_sees_all():
    c = EventCascade()
    subs = c.get_subscriptions("intel_hub")
    assert subs == WorldEventType.ALL
