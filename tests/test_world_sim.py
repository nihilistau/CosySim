"""Tests for engine/world/world_sim.py — CosySim v0.68 "Dark Renaissance".

All tests use isolated :class:`WorldSim` instances constructed with mock
dependencies so no real Nexus, EventBus, or WorldState calls are made.

Singleton tests temporarily patch the module-level ``_WORLD_SIM`` to verify
singleton identity without polluting the process-wide state.
"""
from __future__ import annotations

import threading
import time
from dataclasses import fields
from typing import List
from unittest.mock import MagicMock, call, patch

import pytest

import engine.world.world_sim as _sim_mod
from engine.world.world_sim import (
    FACTION_NAMES,
    GHOST_MESSAGES,
    NPC_ACTIONS,
    WORLD_EVENTS,
    SimEvent,
    SimEventType,
    WorldSim,
    _RING_BUFFER_MAX,
    get_world_sim,
    start_world_sim,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_nexus() -> MagicMock:
    """Return a mock NexusClient that accepts all calls."""
    client = MagicMock()
    client.add_entry.return_value = "entry-001"
    client.search.return_value = []
    return client


@pytest.fixture()
def mock_bus() -> MagicMock:
    """Return a mock EventBus."""
    bus = MagicMock()
    return bus


@pytest.fixture()
def mock_world_state() -> MagicMock:
    """Return a mock WorldState with a sensible get_time() and get_world_summary()."""
    ws = MagicMock()
    wt = MagicMock()
    wt.game_day = 3
    wt.game_hour = 14
    ws.get_time.return_value = wt
    ws.get_world_summary.return_value = {"faction_tension": {}}
    return ws


@pytest.fixture()
def sim(mock_nexus, mock_bus, mock_world_state) -> WorldSim:
    """Isolated WorldSim per test — injected with all mock dependencies."""
    return WorldSim(
        nexus_client=mock_nexus,
        world_state=mock_world_state,
        event_bus=mock_bus,
    )


# ---------------------------------------------------------------------------
# 1. SimEvent dataclass
# ---------------------------------------------------------------------------


class TestSimEventDataclass:
    """Verify :class:`SimEvent` has all required fields with correct types."""

    def test_sim_event_dataclass(self):
        """SimEvent can be constructed with required fields and has correct defaults."""
        ev = SimEvent(
            id="abc-123",
            event_type=SimEventType.NPC_ACTION,
            title="Test title",
            description="Test desc",
            scene="neoncity",
        )
        assert ev.id == "abc-123"
        assert ev.event_type == SimEventType.NPC_ACTION
        assert ev.title == "Test title"
        assert ev.description == "Test desc"
        assert ev.scene == "neoncity"
        assert ev.actor == ""
        assert ev.intensity == 1.0
        assert ev.payload == {}
        assert ev.created_at == ""
        assert ev.seen_by_player is False

    def test_sim_event_full_construction(self):
        """SimEvent accepts all optional fields."""
        ev = SimEvent(
            id="xyz",
            event_type=SimEventType.WORLD_EVENT,
            title="T",
            description="D",
            scene="arena",
            actor="Iron Vex",
            intensity=2.5,
            payload={"key": "value"},
            created_at="Day 1 12:00",
            seen_by_player=True,
        )
        assert ev.actor == "Iron Vex"
        assert ev.intensity == 2.5
        assert ev.payload == {"key": "value"}
        assert ev.seen_by_player is True

    def test_sim_event_type_enum_values(self):
        """SimEventType enum covers all expected categories."""
        expected = {
            "NPC_ACTION",
            "FACTION_SHIFT",
            "SCENE_AMBIENT",
            "HACKER_MESSAGE",
            "ARENA_MATCH",
            "WORLD_EVENT",
            "ECONOMY_TICK",
        }
        actual = {m.name for m in SimEventType}
        assert actual == expected

    def test_sim_event_payload_is_independent(self):
        """Two SimEvent instances do not share the same payload dict."""
        ev1 = SimEvent(id="1", event_type=SimEventType.NPC_ACTION, title="", description="", scene="")
        ev2 = SimEvent(id="2", event_type=SimEventType.NPC_ACTION, title="", description="", scene="")
        ev1.payload["x"] = 1
        assert "x" not in ev2.payload


# ---------------------------------------------------------------------------
# 2. Start / stop
# ---------------------------------------------------------------------------


class TestStartStop:
    """Verify lifecycle management of the daemon thread."""

    def test_start_stop(self, sim: WorldSim):
        """start() sets _running=True and launches a thread; stop() joins it."""
        assert not sim._running
        sim.start()
        assert sim._running
        assert sim._thread is not None
        sim.stop()
        assert not sim._running

    def test_double_start_is_noop(self, sim: WorldSim):
        """Calling start() twice does not spawn a second thread."""
        sim.start()
        first_thread = sim._thread
        sim.start()
        assert sim._thread is first_thread
        sim.stop()

    def test_stop_before_start_is_safe(self, sim: WorldSim):
        """stop() before start() does not raise."""
        sim.stop()  # Should not raise.

    def test_daemon_thread_flag(self, sim: WorldSim):
        """The spawned thread is marked as a daemon thread."""
        sim.start()
        assert sim._thread.daemon is True
        sim.stop()


# ---------------------------------------------------------------------------
# 3. _fire_npc_action
# ---------------------------------------------------------------------------


class TestFireNpcAction:
    """Tests for :meth:`WorldSim._fire_npc_action`."""

    def test_fire_npc_action_creates_event(self, sim: WorldSim):
        """_fire_npc_action() returns a SimEvent with NPC_ACTION type."""
        ev = sim._fire_npc_action()
        assert isinstance(ev, SimEvent)
        assert ev.event_type == SimEventType.NPC_ACTION
        assert ev.title
        assert ev.description
        assert ev.scene

    def test_fire_npc_action_fires_eventbus(self, sim: WorldSim, mock_bus: MagicMock):
        """_fire_npc_action() calls bus.publish exactly once."""
        sim._fire_npc_action()
        mock_bus.publish.assert_called_once()

    def test_fire_npc_action_logs_to_ring_buffer(self, sim: WorldSim):
        """_fire_npc_action() appends the event to the internal log."""
        sim._fire_npc_action()
        assert len(sim._event_log) == 1
        assert sim._event_log[0].event_type == SimEventType.NPC_ACTION

    def test_fire_npc_action_has_actor(self, sim: WorldSim):
        """Generated NPC_ACTION event carries a non-empty actor field."""
        ev = sim._fire_npc_action()
        assert ev.actor != ""

    def test_fire_npc_action_intensity_in_range(self, sim: WorldSim):
        """Intensity is within the documented 0–3 scale."""
        for _ in range(20):
            ev = sim._fire_npc_action()
            assert 0.0 <= ev.intensity <= 3.0


# ---------------------------------------------------------------------------
# 4. _fire_faction_shift
# ---------------------------------------------------------------------------


class TestFireFactionShift:
    """Tests for :meth:`WorldSim._fire_faction_shift`."""

    def test_fire_faction_shift_creates_event(self, sim: WorldSim):
        """_fire_faction_shift() returns a SimEvent with FACTION_SHIFT type."""
        ev = sim._fire_faction_shift()
        assert isinstance(ev, SimEvent)
        assert ev.event_type == SimEventType.FACTION_SHIFT

    def test_fire_faction_shift_scene_is_neoncity(self, sim: WorldSim):
        """Faction shifts are always anchored to the 'neoncity' scene."""
        ev = sim._fire_faction_shift()
        assert ev.scene == "neoncity"

    def test_fire_faction_shift_actor_is_faction(self, sim: WorldSim):
        """The actor field contains a known faction name."""
        ev = sim._fire_faction_shift()
        assert ev.actor in FACTION_NAMES

    def test_fire_faction_shift_fires_eventbus(self, sim: WorldSim, mock_bus: MagicMock):
        """_fire_faction_shift() publishes to the event bus."""
        sim._fire_faction_shift()
        mock_bus.publish.assert_called_once()

    def test_fire_faction_shift_updates_worldstate(
        self, sim: WorldSim, mock_world_state: MagicMock
    ):
        """_fire_faction_shift() calls WorldState.add_event() to register the shift."""
        sim._fire_faction_shift()
        mock_world_state.add_event.assert_called_once()

    def test_fire_faction_shift_payload_has_tension_delta(self, sim: WorldSim):
        """Payload contains a tension_delta of ±5."""
        ev = sim._fire_faction_shift()
        assert "tension_delta" in ev.payload
        assert abs(ev.payload["tension_delta"]) == 5


# ---------------------------------------------------------------------------
# 5. _fire_scene_ambient
# ---------------------------------------------------------------------------


class TestFireSceneAmbient:
    """Tests for :meth:`WorldSim._fire_scene_ambient`."""

    def test_fire_scene_ambient_creates_event(self, sim: WorldSim):
        """_fire_scene_ambient() returns a SimEvent with SCENE_AMBIENT type."""
        ev = sim._fire_scene_ambient()
        assert isinstance(ev, SimEvent)
        assert ev.event_type == SimEventType.SCENE_AMBIENT

    def test_fire_scene_ambient_payload_has_mood(self, sim: WorldSim):
        """Generated event carries a 'mood' key in its payload."""
        ev = sim._fire_scene_ambient()
        assert "mood" in ev.payload
        valid_moods = {"bustling", "quiet", "tense", "festive", "dangerous", "intimate"}
        assert ev.payload["mood"] in valid_moods

    def test_fire_scene_ambient_fires_eventbus(self, sim: WorldSim, mock_bus: MagicMock):
        """_fire_scene_ambient() publishes a scene_ambient_shift event."""
        sim._fire_scene_ambient()
        mock_bus.publish.assert_called_once()
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == "world.scene_ambient_shift"


# ---------------------------------------------------------------------------
# 6. _fire_hacker_event
# ---------------------------------------------------------------------------


class TestFireHackerEvent:
    """Tests for :meth:`WorldSim._fire_hacker_event`."""

    def test_fire_hacker_event_probabilistic(self, sim: WorldSim):
        """Over many trials, roughly 30% of calls return a SimEvent."""
        hits = sum(
            1
            for _ in range(300)
            if sim._fire_hacker_event() is not None
        )
        # Allow ±15% tolerance around 30%.
        assert 35 <= hits <= 115, f"Expected ~90/300 hits, got {hits}"

    def test_fire_hacker_event_returns_correct_type(self, sim: WorldSim):
        """When triggered, event type is HACKER_MESSAGE and actor is 0xGH0ST."""
        with patch("engine.world.world_sim.random.random", return_value=0.0):
            ev = sim._fire_hacker_event()
        assert ev is not None
        assert ev.event_type == SimEventType.HACKER_MESSAGE
        assert ev.actor == "0xGH0ST"
        assert ev.scene == "phone"

    def test_fire_hacker_event_stores_nexus(
        self, sim: WorldSim, mock_nexus: MagicMock
    ):
        """When triggered, _fire_hacker_event() stores a Nexus entry for the message."""
        with patch("engine.world.world_sim.random.random", return_value=0.0):
            sim._fire_hacker_event()
        # add_entry is called twice: once for the phone_messages entry, once
        # by _log_event for the world_sim ring-buffer entry.  We want the first.
        assert mock_nexus.add_entry.call_count >= 1
        first_kwargs = mock_nexus.add_entry.call_args_list[0].kwargs
        assert first_kwargs.get("category") == "phone_messages"
        assert first_kwargs.get("title", "").startswith("ghost_msg:")

    def test_fire_hacker_event_returns_none_when_not_triggered(self, sim: WorldSim):
        """Returns None when the probability check fails."""
        with patch("engine.world.world_sim.random.random", return_value=1.0):
            result = sim._fire_hacker_event()
        assert result is None

    def test_fire_hacker_event_fires_eventbus_when_triggered(
        self, sim: WorldSim, mock_bus: MagicMock
    ):
        """EventBus.publish is called when the hacker event fires."""
        with patch("engine.world.world_sim.random.random", return_value=0.0):
            sim._fire_hacker_event()
        mock_bus.publish.assert_called_once()


# ---------------------------------------------------------------------------
# 7. _fire_arena_queue
# ---------------------------------------------------------------------------


class TestFireArenaQueue:
    """Tests for :meth:`WorldSim._fire_arena_queue`."""

    def test_fire_arena_queue_creates_event(self, sim: WorldSim):
        """_fire_arena_queue() returns an ARENA_MATCH SimEvent."""
        ev = sim._fire_arena_queue()
        assert isinstance(ev, SimEvent)
        assert ev.event_type == SimEventType.ARENA_MATCH
        assert ev.scene == "arena"

    def test_fire_arena_queue_stores_nexus(
        self, sim: WorldSim, mock_nexus: MagicMock
    ):
        """_fire_arena_queue() stores the match in Nexus under 'arena_queue'."""
        sim._fire_arena_queue()
        # add_entry is called twice: once for the arena_queue entry, once by
        # _log_event for the world_sim ring-buffer entry.  We want the first.
        assert mock_nexus.add_entry.call_count >= 1
        first_kwargs = mock_nexus.add_entry.call_args_list[0].kwargs
        assert first_kwargs.get("category") == "arena_queue"
        assert first_kwargs.get("title", "").startswith("match:")

    def test_fire_arena_queue_fires_eventbus(self, sim: WorldSim, mock_bus: MagicMock):
        """_fire_arena_queue() publishes 'arena.match_queued'."""
        sim._fire_arena_queue()
        mock_bus.publish.assert_called_once()
        assert mock_bus.publish.call_args[0][0] == "arena.match_queued"

    def test_fire_arena_queue_payload_has_fighters(self, sim: WorldSim):
        """Payload contains fighter_a and fighter_b keys."""
        ev = sim._fire_arena_queue()
        assert "fighter_a" in ev.payload
        assert "fighter_b" in ev.payload
        assert ev.payload["fighter_a"] != ev.payload["fighter_b"]


# ---------------------------------------------------------------------------
# 8. _fire_world_event
# ---------------------------------------------------------------------------


class TestFireWorldEvent:
    """Tests for :meth:`WorldSim._fire_world_event`."""

    def test_fire_world_event_creates_event(self, sim: WorldSim):
        """_fire_world_event() returns a WORLD_EVENT SimEvent."""
        ev = sim._fire_world_event()
        assert isinstance(ev, SimEvent)
        assert ev.event_type == SimEventType.WORLD_EVENT

    def test_fire_world_event_adds_to_worldstate(
        self, sim: WorldSim, mock_world_state: MagicMock
    ):
        """_fire_world_event() registers a WorldEvent via WorldState.add_event()."""
        sim._fire_world_event()
        mock_world_state.add_event.assert_called_once()

    def test_fire_world_event_fires_eventbus(self, sim: WorldSim, mock_bus: MagicMock):
        """_fire_world_event() publishes 'world.major_event'."""
        sim._fire_world_event()
        mock_bus.publish.assert_called_once()
        assert mock_bus.publish.call_args[0][0] == "world.major_event"

    def test_fire_world_event_intensity_is_max(self, sim: WorldSim):
        """World events are higher-intensity (>=1.5) than NPC actions."""
        ev = sim._fire_world_event()
        assert ev.intensity >= 1.5

    def test_fire_world_event_title_from_templates(self, sim: WorldSim):
        """Generated title matches one of the WORLD_EVENTS_RICH templates."""
        from engine.world.neon_city_events import WORLD_EVENTS_RICH
        known_titles = {t["title"] for t in WORLD_EVENTS_RICH}
        ev = sim._fire_world_event()
        assert ev.title in known_titles


# ---------------------------------------------------------------------------
# 9. _log_event / ring buffer
# ---------------------------------------------------------------------------


class TestLogEvent:
    """Tests for :meth:`WorldSim._log_event` and the ring buffer."""

    def _make_event(self, scene: str = "neoncity") -> SimEvent:
        return SimEvent(
            id=str(id(object())),
            event_type=SimEventType.NPC_ACTION,
            title="t",
            description="d",
            scene=scene,
        )

    def test_log_event_stores_nexus(self, sim: WorldSim, mock_nexus: MagicMock):
        """_log_event() adds an entry to Nexus under category='world_sim'."""
        ev = self._make_event()
        sim._log_event(ev)
        mock_nexus.add_entry.assert_called_once()
        kwargs = mock_nexus.add_entry.call_args.kwargs
        assert kwargs.get("category") == "world_sim"
        assert kwargs.get("content_type") == "history"
        assert f"sim:{ev.id}" == kwargs.get("title")

    def test_log_event_ring_buffer_limit(self, sim: WorldSim):
        """Ring buffer never exceeds _RING_BUFFER_MAX entries."""
        for _ in range(_RING_BUFFER_MAX + 50):
            sim._log_event(self._make_event())
        assert len(sim._event_log) == _RING_BUFFER_MAX

    def test_log_event_ring_buffer_drops_oldest(self, sim: WorldSim):
        """When over limit, the oldest event is evicted."""
        first_id = "first-event-id"
        first_ev = SimEvent(
            id=first_id,
            event_type=SimEventType.NPC_ACTION,
            title="first",
            description="",
            scene="neoncity",
        )
        sim._log_event(first_ev)
        for _ in range(_RING_BUFFER_MAX):
            sim._log_event(self._make_event())
        ids = [ev.id for ev in sim._event_log]
        assert first_id not in ids

    def test_log_event_appends_in_order(self, sim: WorldSim):
        """Events appear in insertion order in the ring buffer."""
        ids = []
        for i in range(5):
            ev = SimEvent(
                id=f"ev-{i}",
                event_type=SimEventType.SCENE_AMBIENT,
                title="",
                description="",
                scene="lounge",
            )
            sim._log_event(ev)
            ids.append(f"ev-{i}")
        logged_ids = [ev.id for ev in sim._event_log]
        assert logged_ids == ids


# ---------------------------------------------------------------------------
# 10. get_digest
# ---------------------------------------------------------------------------


class TestGetDigest:
    """Tests for :meth:`WorldSim.get_digest`."""

    def _add_event(self, sim: WorldSim, scene: str, seen: bool = False) -> SimEvent:
        ev = SimEvent(
            id=str(uuid_counter()),
            event_type=SimEventType.NPC_ACTION,
            title="t",
            description="d",
            scene=scene,
            seen_by_player=seen,
        )
        with sim._lock:
            sim._event_log.append(ev)
        return ev

    def test_get_digest_filters_by_scene(self, sim: WorldSim):
        """get_digest() only returns events whose scene matches or is global."""
        self._add_event(sim, "lounge")
        self._add_event(sim, "casino")
        self._add_event(sim, "")  # global

        result = sim.get_digest("lounge")
        scenes = {ev.scene for ev in result}
        assert "casino" not in scenes
        assert "lounge" in scenes or "" in scenes

    def test_get_digest_marks_seen(self, sim: WorldSim):
        """All events returned by get_digest() are marked seen_by_player=True."""
        self._add_event(sim, "neoncity")
        self._add_event(sim, "neoncity")
        result = sim.get_digest("neoncity")
        assert len(result) == 2
        for ev in result:
            assert ev.seen_by_player is True

    def test_get_digest_skips_already_seen(self, sim: WorldSim):
        """Events already marked seen are not returned again."""
        self._add_event(sim, "arena", seen=True)
        self._add_event(sim, "arena", seen=False)
        result = sim.get_digest("arena")
        assert len(result) == 1

    def test_get_digest_returns_newest_first(self, sim: WorldSim):
        """Digest is ordered newest-first (reversed ring-buffer order)."""
        ev1 = self._add_event(sim, "lounge")
        ev2 = self._add_event(sim, "lounge")
        ev3 = self._add_event(sim, "lounge")
        result = sim.get_digest("lounge")
        assert result[0].id == ev3.id
        assert result[-1].id == ev1.id


# ---------------------------------------------------------------------------
# 11. get_all_events
# ---------------------------------------------------------------------------


class TestGetAllEvents:
    """Tests for :meth:`WorldSim.get_all_events`."""

    def test_get_all_events(self, sim: WorldSim):
        """Returns recent events up to the requested limit."""
        for i in range(10):
            ev = SimEvent(
                id=f"ev-{i}",
                event_type=SimEventType.FACTION_SHIFT,
                title="",
                description="",
                scene="neoncity",
            )
            sim._log_event(ev)

        result = sim.get_all_events(limit=5)
        assert len(result) == 5

    def test_get_all_events_newest_first(self, sim: WorldSim):
        """get_all_events() returns events newest-first."""
        for i in range(3):
            ev = SimEvent(
                id=f"ev-{i}",
                event_type=SimEventType.NPC_ACTION,
                title="",
                description="",
                scene="neoncity",
            )
            sim._log_event(ev)
        result = sim.get_all_events()
        assert result[0].id == "ev-2"
        assert result[-1].id == "ev-0"

    def test_get_all_events_empty(self, sim: WorldSim):
        """Returns empty list when no events have been logged."""
        assert sim.get_all_events() == []


# ---------------------------------------------------------------------------
# 12. Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """Tests for :func:`get_world_sim` double-checked locking singleton."""

    def test_singleton(self):
        """get_world_sim() always returns the same instance."""
        with patch.object(_sim_mod, "_WORLD_SIM", None):
            with patch("engine.world.world_sim.get_nexus_client", return_value=MagicMock()):
                with patch("engine.world.world_sim.get_world_state", return_value=MagicMock()):
                    a = get_world_sim()
                    b = get_world_sim()
                    assert a is b

    def test_singleton_restored_after_patch(self):
        """Module-level _WORLD_SIM is restored between test patches."""
        original = _sim_mod._WORLD_SIM
        try:
            _sim_mod._WORLD_SIM = None
            with patch("engine.world.world_sim.get_nexus_client", return_value=MagicMock()):
                with patch("engine.world.world_sim.get_world_state", return_value=MagicMock()):
                    sim = get_world_sim()
                    assert sim is not None
        finally:
            _sim_mod._WORLD_SIM = original

    def test_start_world_sim_returns_started_sim(self):
        """start_world_sim() returns the singleton and marks it running."""
        mock_sim = MagicMock(spec=WorldSim)
        with patch("engine.world.world_sim.get_world_sim", return_value=mock_sim):
            result = start_world_sim()
        assert result is mock_sim
        mock_sim.start.assert_called_once()


# ---------------------------------------------------------------------------
# 13. NPC actions cover all scenes
# ---------------------------------------------------------------------------


class TestNpcActionsCoverScenes:
    """Verify NPC_ACTIONS template breadth."""

    def test_npc_actions_cover_all_scenes(self):
        """NPC_ACTIONS includes entries for all major CosySim scenes."""
        expected_scenes = {"neoncity", "lounge", "tavern", "casino", "arena", "heist", "phone"}
        covered = {t["scene"] for t in NPC_ACTIONS}
        missing = expected_scenes - covered
        assert not missing, f"NPC_ACTIONS missing templates for: {missing}"

    def test_npc_actions_minimum_count(self):
        """NPC_ACTIONS contains at least 20 entries."""
        assert len(NPC_ACTIONS) >= 20

    def test_npc_actions_all_have_required_keys(self):
        """Every NPC_ACTIONS entry has scene, actor, title, and desc keys."""
        required = {"scene", "actor", "title", "desc"}
        for i, t in enumerate(NPC_ACTIONS):
            missing = required - set(t.keys())
            assert not missing, f"NPC_ACTIONS[{i}] missing keys: {missing}"


# ---------------------------------------------------------------------------
# 14. Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Basic thread-safety smoke tests."""

    def test_concurrent_log_event(self, sim: WorldSim, mock_nexus: MagicMock):
        """Concurrent calls to _log_event() do not corrupt the ring buffer."""
        errors: List[Exception] = []

        def worker():
            try:
                for _ in range(50):
                    ev = SimEvent(
                        id=str(uuid_counter()),
                        event_type=SimEventType.SCENE_AMBIENT,
                        title="",
                        description="",
                        scene="lounge",
                    )
                    sim._log_event(ev)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(sim._event_log) <= _RING_BUFFER_MAX

    def test_concurrent_get_digest(self, sim: WorldSim):
        """Concurrent get_digest() calls do not raise."""
        for i in range(20):
            ev = SimEvent(
                id=str(i),
                event_type=SimEventType.NPC_ACTION,
                title="",
                description="",
                scene="neoncity",
            )
            with sim._lock:
                sim._event_log.append(ev)

        errors: List[Exception] = []

        def reader():
            try:
                sim.get_digest("neoncity")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ---------------------------------------------------------------------------
# 15. EventTypes integration
# ---------------------------------------------------------------------------


class TestEventTypesIntegration:
    """Confirm WorldSim uses existing EventTypes constants."""

    def test_hacker_event_uses_phone_event_type(
        self, sim: WorldSim, mock_bus: MagicMock
    ):
        """_fire_hacker_event() uses EventTypes.PHONE_HACKER_MESSAGE."""
        from engine.events.event_bus import EventTypes

        with patch("engine.world.world_sim.random.random", return_value=0.0):
            sim._fire_hacker_event()
        called_type = mock_bus.publish.call_args[0][0]
        assert called_type == EventTypes.PHONE_HACKER_MESSAGE

    def test_faction_shift_uses_neoncity_event_type(
        self, sim: WorldSim, mock_bus: MagicMock
    ):
        """_fire_faction_shift() uses EventTypes.NEONCITY_FACTION_SHIFT."""
        from engine.events.event_bus import EventTypes

        sim._fire_faction_shift()
        called_type = mock_bus.publish.call_args[0][0]
        assert called_type == EventTypes.NEONCITY_FACTION_SHIFT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_counter = 0


def uuid_counter() -> str:
    """Simple incrementing ID generator for test fixture events."""
    global _counter
    _counter += 1
    return f"test-ev-{_counter}"
