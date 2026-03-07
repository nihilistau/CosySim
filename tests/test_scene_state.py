"""Focused tests for explicit scene-level state sync."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from content.scenes.casino.casino_mcp import SCENE_ID as CASINO_SCENE_ID
from content.scenes.casino.casino_scene import CasinoScene
from content.scenes.lounge.lounge_mcp import SCENE_ID as LOUNGE_SCENE_ID
from content.scenes.lounge.lounge_scene import LoungeScene
from engine.mcp.scene_state import SceneStateManager


def test_update_stats_rejects_scene_level_fields() -> None:
    """Unsupported scene keys should fail fast instead of silently drifting."""
    mgr = SceneStateManager()

    with pytest.raises(ValueError, match="set_scene_state"):
        mgr.update_stats("lounge_scene", heat_level=10)


def test_scene_state_round_trip_is_in_snapshot() -> None:
    """Explicit scene state is persisted and included in snapshots."""
    mgr = SceneStateManager()

    mgr.set_scene_state("casino", pot=120, phase="bet", player_chips=420)

    assert mgr.get_scene_state("casino") == {
        "pot": 120,
        "phase": "bet",
        "player_chips": 420,
    }
    assert mgr.get_scene_snapshot("casino")["scene_state"] == {
        "pot": 120,
        "phase": "bet",
        "player_chips": 420,
    }


def test_lounge_tick_heat_persists_scene_state() -> None:
    """Heat ticks should write real lounge scene state."""
    mgr = SceneStateManager()
    fake_scene = SimpleNamespace(
        heat_level=0,
        _heat_lock=threading.Lock(),
        _ssm=mgr,
        socketio=MagicMock(),
        _apply_rule=MagicMock(),
        _fw=MagicMock(),
    )

    with patch("engine.mcp.state_coordinator.get_coordinator", return_value=MagicMock()):
        LoungeScene._tick_heat(fake_scene, 10)

    assert mgr.get_scene_state(LOUNGE_SCENE_ID)["heat_level"] == 10


def test_casino_game_state_persists_scene_metrics() -> None:
    """Casino table metrics should be written to scene state and remain readable."""
    mgr = SceneStateManager()
    fake_scene = SimpleNamespace(
        round_number=4,
        current_phase="bet",
        game_active=True,
        player_hand=["A♠", "K♠"],
        community_cards=["2♥", "7♦", "J♣"],
        mira_hand=["Q♣", "Q♦"],
        pot=80,
        player_chips=420,
        mira_chips=380,
        player_stats={"confidence": 55.0},
        dealer_comment="The house is watching.",
        mira_comment="Bold move.",
        current_tell="fingers tap",
        hand_history=[{"winner": "player"}],
        events_log=[{"type": "bet"}],
        _state_mgr=mgr,
    )

    state = CasinoScene._get_game_state(fake_scene)

    assert state["pot"] == 80
    assert mgr.get_scene_state(CASINO_SCENE_ID) == {
        "player_chips": 420,
        "mira_chips": 380,
        "pot": 80,
        "round": 4,
        "phase": "bet",
        "game_active": True,
    }
