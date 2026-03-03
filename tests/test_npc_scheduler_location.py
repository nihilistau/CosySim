"""Tests — NPCScheduler cross-scene location tracking via CityMap."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _isolate():
    """Reset NPCScheduler singleton between tests."""
    from engine.agents import npc_scheduler as _mod
    old = _mod._scheduler
    yield
    _mod._scheduler = old


def _make_scheduler():
    """Return a fresh NPCScheduler with all heavy deps mocked."""
    from engine.agents.npc_scheduler import NPCScheduler
    sched = NPCScheduler.__new__(NPCScheduler)
    sched._socketio = MagicMock()
    sched._running = False
    sched._interval = 30
    return sched


def test_track_npc_in_city_map_calls_set_location():
    """_track_npc_in_city_map should call city_map.set_npc_location with char_id and location."""
    sched = _make_scheduler()
    mock_map = MagicMock()
    mock_map.get_npc_location.return_value = None  # no prior location

    with patch("engine.world.city_map.get_city_map", return_value=mock_map):
        sched._track_npc_in_city_map("lola", "the_penthouse")

    mock_map.set_npc_location.assert_called_once_with("lola", "the_penthouse")


def test_track_npc_emits_socket_event_on_location_change():
    """Should emit 'npc_location' socket event when location changes."""
    sched = _make_scheduler()
    mock_map = MagicMock()
    mock_map.get_npc_location.return_value = "club_noir"  # was somewhere else
    mock_fw = MagicMock()

    with (
        patch("engine.world.city_map.get_city_map", return_value=mock_map),
        patch("engine.mcp.get_framework", return_value=mock_fw),
    ):
        sched._track_npc_in_city_map("viktor", "the_grid")

    mock_fw.emit.assert_called_once()
    call_args = mock_fw.emit.call_args
    assert call_args[0][0] == "npc_location"
    payload = call_args[0][1]
    assert payload["character_id"] == "viktor"
    assert payload["location"] == "the_grid"


def test_track_npc_no_emit_when_location_unchanged():
    """Should NOT emit socket event when location is already the same."""
    sched = _make_scheduler()
    mock_map = MagicMock()
    mock_map.get_npc_location.return_value = "the_penthouse"  # same as new
    mock_fw = MagicMock()

    with (
        patch("engine.world.city_map.get_city_map", return_value=mock_map),
        patch("engine.mcp.get_framework", return_value=mock_fw),
    ):
        sched._track_npc_in_city_map("lola", "the_penthouse")

    mock_fw.emit.assert_not_called()


def test_track_npc_no_location_skipped():
    """Empty/None location should be silently skipped."""
    sched = _make_scheduler()
    mock_map = MagicMock()

    with patch("engine.world.city_map.get_city_map", return_value=mock_map):
        sched._track_npc_in_city_map("aria", "")
        sched._track_npc_in_city_map("aria", None)

    mock_map.set_npc_location.assert_not_called()
    sched._socketio.emit.assert_not_called()


def test_track_npc_city_map_error_does_not_raise():
    """city_map errors should be swallowed so NPC processing continues."""
    sched = _make_scheduler()
    mock_map = MagicMock()
    mock_map.get_npc_location.side_effect = RuntimeError("db locked")

    with patch("engine.world.city_map.get_city_map", return_value=mock_map):
        # Should not raise
        sched._track_npc_in_city_map("frankie", "club_noir")


def test_track_npc_no_socketio():
    """If _socketio is None, location still updated without crash."""
    sched = _make_scheduler()
    sched._socketio = None
    mock_map = MagicMock()
    mock_map.get_npc_location.return_value = "old_location"

    with patch("engine.world.city_map.get_city_map", return_value=mock_map):
        sched._track_npc_in_city_map("mira", "neon_city")

    mock_map.set_npc_location.assert_called_once_with("mira", "neon_city")
