"""Tests for engine/world/world_state.py — CosySim v0.68 "Dark Renaissance".

All tests use isolated WorldState instances (not the singleton) constructed
with a mock Nexus client so no real HTTP calls are made.

Singleton tests temporarily replace the module-level ``_WORLD_STATE`` to
verify singleton identity without polluting the process-wide state.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, call, patch

import pytest

import engine.world.world_state as _ws_mod
from engine.world.world_state import (
    Weather,
    WorldEvent,
    WorldState,
    WorldTime,
    _classify_time_of_day,
    _SECONDS_PER_GAME_HOUR,
    get_world_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_nexus():
    """Mock NexusClient that always returns an empty search result set."""
    client = MagicMock()
    client.search.return_value = []
    client.add_entry.return_value = "entry-001"
    client.update_entry.return_value = True
    return client


@pytest.fixture()
def world(mock_nexus) -> WorldState:
    """Fresh, isolated WorldState per test (not the process singleton)."""
    return WorldState(nexus_client=mock_nexus)


def _at_hour(ws: WorldState, hour: int) -> None:
    """Shift WorldState._start_time so that get_time() reports *hour*."""
    ws._start_time = time.time() - hour * _SECONDS_PER_GAME_HOUR


def _make_event(
    event_id: str = "evt-1",
    name: str = "Test Event",
    scene: str = "global",
    event_type: str = "gang_war",
    duration: float = 3600.0,
    active: bool = True,
) -> WorldEvent:
    now = time.time()
    return WorldEvent(
        id=event_id,
        name=name,
        description="A test world event.",
        scene=scene,
        event_type=event_type,
        started_at=now,
        expires_at=now + duration,
        active=active,
    )


# ---------------------------------------------------------------------------
# WorldTime calculation
# ---------------------------------------------------------------------------


class TestWorldTimeCalculation:
    def test_game_hour_zero_at_start(self, world: WorldState) -> None:
        """Game hour is 0 immediately after world start."""
        world._start_time = time.time()
        wt = world.get_time()
        assert wt.game_hour == 0

    def test_game_hour_advances_with_real_seconds(self, world: WorldState) -> None:
        """Each 60 real seconds advances game time by one hour."""
        _at_hour(world, 9)
        wt = world.get_time()
        assert wt.game_hour == 9

    def test_game_day_increments_after_24_hours(self, world: WorldState) -> None:
        """game_day becomes 1 after 24 in-game hours (24 real minutes)."""
        _at_hour(world, 25)
        wt = world.get_time()
        assert wt.game_day == 1
        assert wt.game_hour == 1

    def test_game_day_name_cycles_through_week(self, world: WorldState) -> None:
        """Day names cycle Monday–Sunday then repeat."""
        # Day 0 → Monday, Day 7 → Monday again.
        _at_hour(world, 0)
        wt0 = world.get_time()
        assert wt0.game_day_name == "Monday"

        _at_hour(world, 24 * 7)  # 7 in-game days later
        wt7 = world.get_time()
        assert wt7.game_day_name == "Monday"

    def test_to_display_format(self, world: WorldState) -> None:
        """to_display returns the expected formatted string."""
        _at_hour(world, 9)
        wt = world.get_time()
        display = wt.to_display()
        assert "09:00" in display
        assert "Morning" in display

    def test_to_display_late_night(self, world: WorldState) -> None:
        """to_display correctly labels late_night as 'Late Night'."""
        _at_hour(world, 3)
        wt = world.get_time()
        assert "Late Night" in wt.to_display()


# ---------------------------------------------------------------------------
# Time-of-day classification
# ---------------------------------------------------------------------------


class TestTimeOfDayClassification:
    """Exhaustive coverage of every boundary in _classify_time_of_day."""

    @pytest.mark.parametrize("hour,expected", [
        (5, "dawn"),
        (6, "dawn"),
        (7, "dawn"),
        (8, "morning"),
        (10, "morning"),
        (11, "morning"),
        (12, "afternoon"),
        (15, "afternoon"),
        (17, "afternoon"),
        (18, "evening"),
        (20, "evening"),
        (21, "evening"),
        (22, "night"),
        (23, "night"),
        (0, "night"),
        (1, "night"),
        (2, "late_night"),
        (3, "late_night"),
        (4, "late_night"),
    ])
    def test_classification(self, hour: int, expected: str) -> None:
        assert _classify_time_of_day(hour) == expected

    def test_worldtime_tod_via_worldstate(self, world: WorldState) -> None:
        """WorldState.get_time() propagates time_of_day correctly."""
        _at_hour(world, 18)
        assert world.get_time().time_of_day == "evening"


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------


class TestWeather:
    def test_default_weather_is_clear(self, world: WorldState) -> None:
        """Global weather defaults to CLEAR on a fresh WorldState."""
        assert world.get_weather() == Weather.CLEAR
        assert world.get_weather("global") == Weather.CLEAR

    def test_get_unknown_scene_falls_back_to_global(self, world: WorldState) -> None:
        """Requesting weather for an unknown scene returns the global value."""
        world._weather["global"] = Weather.OVERCAST
        assert world.get_weather("unknown_scene") == Weather.OVERCAST

    def test_set_and_get_weather(self, world: WorldState) -> None:
        """set_weather stores the value; get_weather retrieves it."""
        world.set_weather("neon_district", Weather.NEON_RAIN)
        assert world.get_weather("neon_district") == Weather.NEON_RAIN

    def test_set_weather_overrides_global(self, world: WorldState) -> None:
        """Per-scene weather takes priority over global fallback."""
        world.set_weather("global", Weather.STORM)
        world.set_weather("casino_floor", Weather.CLEAR)
        assert world.get_weather("casino_floor") == Weather.CLEAR
        assert world.get_weather("alley") == Weather.STORM  # falls back to global

    def test_set_weather_persists_to_nexus(self, world: WorldState, mock_nexus) -> None:
        """set_weather triggers a Nexus write."""
        mock_nexus.search.return_value = []
        world.set_weather("global", Weather.FOG)
        mock_nexus.add_entry.assert_called()

    def test_weather_particle_presets(self) -> None:
        """Each Weather member exposes a non-empty particle_preset string."""
        for member in Weather:
            assert isinstance(member.particle_preset, str)
            assert len(member.particle_preset) > 0

    def test_neon_rain_preset(self) -> None:
        assert Weather.NEON_RAIN.particle_preset == "neon_rain"

    def test_fog_preset_is_smoke(self) -> None:
        assert Weather.FOG.particle_preset == "smoke"


# ---------------------------------------------------------------------------
# World events
# ---------------------------------------------------------------------------


class TestWorldEvents:
    def test_no_events_by_default(self, world: WorldState) -> None:
        assert world.get_active_events() == []

    def test_add_and_get_world_events(self, world: WorldState) -> None:
        """An added event is immediately returned by get_active_events."""
        ev = _make_event("ev-1")
        world.add_event(ev)
        active = world.get_active_events()
        assert len(active) == 1
        assert active[0].id == "ev-1"

    def test_get_active_events_filters_by_scene(self, world: WorldState) -> None:
        """get_active_events(scene) returns matching + global events only."""
        ev_global = _make_event("eg", scene="global")
        ev_casino = _make_event("ec", scene="casino")
        ev_arena = _make_event("ea", scene="arena")
        for ev in (ev_global, ev_casino, ev_arena):
            world.add_event(ev)

        casino_events = world.get_active_events("casino")
        ids = {ev.id for ev in casino_events}
        assert "ec" in ids   # scene match
        assert "eg" in ids   # global match
        assert "ea" not in ids  # wrong scene

    def test_expire_event(self, world: WorldState) -> None:
        """expire_event immediately deactivates the event."""
        ev = _make_event("ev-expire")
        world.add_event(ev)
        assert len(world.get_active_events()) == 1

        world.expire_event("ev-expire")
        assert world.get_active_events() == []

    def test_expire_unknown_event_is_noop(self, world: WorldState) -> None:
        """expire_event on a non-existent ID does not raise."""
        world.expire_event("does-not-exist")  # should not raise

    def test_expired_event_auto_pruned_on_read(self, world: WorldState) -> None:
        """Events whose expires_at is in the past are pruned during read."""
        ev = WorldEvent(
            id="ev-old",
            name="Old Event",
            description="Already past.",
            scene="global",
            event_type="festival",
            started_at=time.time() - 200,
            expires_at=time.time() - 100,  # already expired
            active=True,
        )
        world._events.append(ev)
        assert world.get_active_events() == []

    def test_event_with_zero_expires_at_never_expires(self, world: WorldState) -> None:
        """expires_at=0 means the event never auto-expires."""
        ev = WorldEvent(
            id="ev-perm",
            name="Permanent",
            description="Never expires.",
            scene="global",
            event_type="festival",
            started_at=time.time(),
            expires_at=0,
            active=True,
        )
        world.add_event(ev)
        assert len(world.get_active_events()) == 1

    def test_add_event_persists_to_nexus(self, world: WorldState, mock_nexus) -> None:
        """add_event triggers a Nexus write."""
        mock_nexus.search.return_value = []
        world.add_event(_make_event("ev-persist"))
        mock_nexus.add_entry.assert_called()


# ---------------------------------------------------------------------------
# NPC availability
# ---------------------------------------------------------------------------


class TestNpcAvailability:
    def test_default_schedule_active_at_evening(self, world: WorldState) -> None:
        """Without a custom schedule, NPCs are available in the evening."""
        _at_hour(world, 19)  # evening
        assert world.get_npc_availability("razor") is True

    def test_default_schedule_away_at_dawn(self, world: WorldState) -> None:
        """Without a custom schedule, NPCs are away at dawn."""
        _at_hour(world, 6)  # dawn
        assert world.get_npc_availability("razor") is False

    def test_default_schedule_away_at_morning(self, world: WorldState) -> None:
        _at_hour(world, 9)  # morning
        assert world.get_npc_availability("razor") is False

    def test_custom_schedule_respected(self, world: WorldState) -> None:
        """A custom schedule overrides the default."""
        world.set_npc_schedule("detective", ["dawn", "morning"])
        _at_hour(world, 6)  # dawn
        assert world.get_npc_availability("detective") is True

        _at_hour(world, 20)  # evening — not in custom schedule
        assert world.get_npc_availability("detective") is False

    def test_npc_availability_by_time_parametrized(self, world: WorldState) -> None:
        """Parametrized spot-check across all six time periods."""
        world.set_npc_schedule("npc_x", ["morning", "afternoon"])
        checks = [
            (5, False),   # dawn
            (9, True),    # morning
            (14, True),   # afternoon
            (20, False),  # evening
            (23, False),  # night
            (3, False),   # late_night
        ]
        for hour, expected in checks:
            _at_hour(world, hour)
            result = world.get_npc_availability("npc_x")
            assert result is expected, f"Hour {hour}: expected {expected}"


# ---------------------------------------------------------------------------
# World summary
# ---------------------------------------------------------------------------


class TestWorldSummary:
    def test_world_summary_has_required_keys(self, world: WorldState) -> None:
        """get_world_summary returns a dict with all required top-level keys."""
        summary = world.get_world_summary()
        for key in ("time", "weather", "active_events", "npcs_available"):
            assert key in summary

    def test_time_section_has_all_fields(self, world: WorldState) -> None:
        summary = world.get_world_summary()
        time_data = summary["time"]
        for field in ("game_hour", "game_day", "game_day_name", "time_of_day", "display"):
            assert field in time_data

    def test_active_events_in_summary(self, world: WorldState) -> None:
        """Active events appear in the summary with slim dicts."""
        world.add_event(_make_event("ev-s1"))
        summary = world.get_world_summary()
        assert len(summary["active_events"]) == 1
        ev_data = summary["active_events"][0]
        for key in ("id", "name", "scene", "event_type", "description"):
            assert key in ev_data

    def test_npcs_available_reflects_schedules(self, world: WorldState) -> None:
        """NPCs on a daytime schedule appear in npcs_available during the day."""
        world.set_npc_schedule("doc", ["morning", "afternoon"])
        _at_hour(world, 10)  # morning
        summary = world.get_world_summary()
        assert "doc" in summary["npcs_available"]

    def test_weather_in_summary_shows_scene_values(self, world: WorldState) -> None:
        world.set_weather("test_scene", Weather.STORM)
        summary = world.get_world_summary()
        assert summary["weather"]["test_scene"] == "storm"


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


class TestTick:
    def test_tick_returns_summary_shape(self, world: WorldState) -> None:
        """tick() returns a dict with the same shape as get_world_summary."""
        with patch("engine.world.world_state.get_event_bus") as mock_bus_factory:
            mock_bus_factory.return_value = MagicMock()
            result = world.tick()

        for key in ("time", "weather", "active_events", "npcs_available"):
            assert key in result

    def test_tick_publishes_world_tick_event(self, world: WorldState) -> None:
        """tick() publishes EventTypes.WORLD_TICK to the event bus."""
        mock_bus = MagicMock()
        with patch("engine.world.world_state.get_event_bus", return_value=mock_bus):
            world.tick()

        mock_bus.publish.assert_called_once()
        event_type_arg = mock_bus.publish.call_args[0][0]
        assert event_type_arg == "world.tick"

    def test_tick_payload_matches_summary(self, world: WorldState) -> None:
        """Payload published by tick() matches get_world_summary()."""
        mock_bus = MagicMock()
        with patch("engine.world.world_state.get_event_bus", return_value=mock_bus):
            result = world.tick()

        published_payload = mock_bus.publish.call_args[0][1]
        assert published_payload["time"] == result["time"]

    def test_tick_prunes_expired_events(self, world: WorldState) -> None:
        """Expired events are removed from active_events after a tick."""
        ev = WorldEvent(
            id="ev-exp",
            name="Expired",
            description="Past event.",
            scene="global",
            event_type="festival",
            started_at=time.time() - 200,
            expires_at=time.time() - 100,
            active=True,
        )
        world._events.append(ev)

        with patch("engine.world.world_state.get_event_bus") as mock_bus_f:
            mock_bus_f.return_value = MagicMock()
            result = world.tick()

        assert result["active_events"] == []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_singleton_returns_same_instance(self) -> None:
        """get_world_state() returns the same object on repeated calls."""
        saved = _ws_mod._WORLD_STATE
        _ws_mod._WORLD_STATE = None
        try:
            with patch("engine.world.world_state.get_nexus_client") as mock_nx:
                mock_nx.return_value = MagicMock(search=MagicMock(return_value=[]))
                s1 = get_world_state()
                s2 = get_world_state()
                assert s1 is s2
        finally:
            _ws_mod._WORLD_STATE = saved

    def test_singleton_is_world_state_type(self) -> None:
        """get_world_state() returns a WorldState instance."""
        saved = _ws_mod._WORLD_STATE
        _ws_mod._WORLD_STATE = None
        try:
            with patch("engine.world.world_state.get_nexus_client") as mock_nx:
                mock_nx.return_value = MagicMock(search=MagicMock(return_value=[]))
                instance = get_world_state()
                assert isinstance(instance, WorldState)
        finally:
            _ws_mod._WORLD_STATE = saved


# ---------------------------------------------------------------------------
# Nexus persistence
# ---------------------------------------------------------------------------


class TestPersistenceToNexus:
    def test_add_entry_called_on_first_persist(
        self, world: WorldState, mock_nexus
    ) -> None:
        """_persist_state calls add_entry when no existing Nexus entry exists."""
        mock_nexus.search.return_value = []
        world._persist_state()
        mock_nexus.add_entry.assert_called()

    def test_add_entry_title_is_world_state(
        self, world: WorldState, mock_nexus
    ) -> None:
        """The Nexus entry is created with title 'world:state'."""
        mock_nexus.search.return_value = []
        world._persist_state()
        _, kwargs = mock_nexus.add_entry.call_args
        assert kwargs.get("title") == "world:state"

    def test_add_entry_content_type_is_memory(
        self, world: WorldState, mock_nexus
    ) -> None:
        """The Nexus entry uses content_type='memory' and category='world_state'."""
        mock_nexus.search.return_value = []
        world._persist_state()
        _, kwargs = mock_nexus.add_entry.call_args
        assert kwargs.get("content_type") == "memory"
        assert kwargs.get("category") == "world_state"

    def test_update_entry_called_when_existing_entry_found(
        self, world: WorldState, mock_nexus
    ) -> None:
        """_persist_state calls update_entry when an existing entry is found."""
        mock_nexus.search.return_value = [
            {"id": "entry-existing", "title": "world:state", "content": "{}"}
        ]
        world._persist_state()
        mock_nexus.update_entry.assert_called_once()
        args, kwargs = mock_nexus.update_entry.call_args
        assert args[0] == "entry-existing"
        assert "content" in kwargs

    def test_load_state_restores_weather(self, mock_nexus) -> None:
        """_load_state restores persisted weather values."""
        import json

        state_json = json.dumps({
            "start_time": time.time() - 500,
            "weather": {"global": "neon_rain", "casino": "fog"},
            "events": [],
            "npc_schedules": {},
        })
        mock_nexus.search.return_value = [
            {"id": "e1", "title": "world:state", "content": state_json}
        ]
        ws = WorldState(nexus_client=mock_nexus)
        assert ws.get_weather("global") == Weather.NEON_RAIN
        assert ws.get_weather("casino") == Weather.FOG

    def test_load_state_restores_events(self, mock_nexus) -> None:
        """_load_state reconstructs WorldEvent objects from stored JSON."""
        import json

        now = time.time()
        state_json = json.dumps({
            "start_time": now - 100,
            "weather": {"global": "clear"},
            "events": [
                {
                    "id": "ev-loaded",
                    "name": "Loaded Event",
                    "description": "From Nexus.",
                    "scene": "global",
                    "event_type": "festival",
                    "started_at": now - 50,
                    "expires_at": now + 3600,
                    "active": True,
                    "payload": {},
                }
            ],
            "npc_schedules": {},
        })
        mock_nexus.search.return_value = [
            {"id": "e1", "title": "world:state", "content": state_json}
        ]
        ws = WorldState(nexus_client=mock_nexus)
        active = ws.get_active_events()
        assert len(active) == 1
        assert active[0].id == "ev-loaded"

    def test_load_state_restores_npc_schedules(self, mock_nexus) -> None:
        """_load_state restores NPC schedule mappings."""
        import json

        state_json = json.dumps({
            "start_time": time.time(),
            "weather": {"global": "clear"},
            "events": [],
            "npc_schedules": {"razor": ["evening", "night"]},
        })
        mock_nexus.search.return_value = [
            {"id": "e1", "title": "world:state", "content": state_json}
        ]
        ws = WorldState(nexus_client=mock_nexus)
        assert ws._npc_schedules.get("razor") == ["evening", "night"]

    def test_persist_tolerates_nexus_error(self, world: WorldState, mock_nexus) -> None:
        """_persist_state does not raise when Nexus throws an exception."""
        mock_nexus.search.side_effect = ConnectionError("Nexus down")
        world._persist_state()  # should not raise

    def test_load_tolerates_nexus_error(self, mock_nexus) -> None:
        """_load_state does not raise when Nexus throws an exception."""
        mock_nexus.search.side_effect = ConnectionError("Nexus down")
        ws = WorldState(nexus_client=mock_nexus)  # should not raise
        assert ws.get_weather() == Weather.CLEAR  # defaults intact
