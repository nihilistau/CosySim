"""Tests for the CrossSceneRelay cross-scene event routing."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch


class TestCrossSceneRelayInit:
    def test_import(self):
        from engine.events.cross_scene_relay import CrossSceneRelay, get_cross_scene_relay
        relay = CrossSceneRelay()
        assert relay is not None
        assert not relay._subscribed

    def test_singleton(self):
        from engine.events.cross_scene_relay import get_cross_scene_relay
        import engine.events.cross_scene_relay as mod
        original = mod._RELAY
        mod._RELAY = None
        try:
            r1 = get_cross_scene_relay()
            r2 = get_cross_scene_relay()
            assert r1 is r2
        finally:
            mod._RELAY = original


class TestCrossSceneRelayStart:
    def _make_mock_bus(self):
        """Return a mock bus whose subscribe() returns unique sub IDs."""
        mock_bus = MagicMock()
        mock_bus.subscribe.side_effect = lambda *a, **kw: str(uuid.uuid4())
        return mock_bus

    def test_start_subscribes(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = self._make_mock_bus()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay.start()
        assert relay._subscribed
        assert mock_bus.subscribe.call_count == 4

    def test_start_stores_sub_ids(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = self._make_mock_bus()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay.start()
        assert len(relay._sub_ids) == 4
        for sub_id in relay._sub_ids:
            assert isinstance(sub_id, str)

    def test_start_idempotent(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = self._make_mock_bus()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay.start()
            relay.start()
        assert mock_bus.subscribe.call_count == 4  # Only once

    def test_stop_unsubscribes(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = self._make_mock_bus()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay.start()
            relay.stop()
        assert not relay._subscribed
        assert mock_bus.unsubscribe.call_count == 4

    def test_stop_clears_sub_ids(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = self._make_mock_bus()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay.start()
            relay.stop()
        assert relay._sub_ids == []


class TestCrossSceneRelayRipples:
    def test_arena_match_ripples(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = MagicMock()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay._on_arena_match_end({"winner": "Kira", "faction": "Syndicate"})
        published_events = [c[0][0] for c in mock_bus.publish.call_args_list]
        assert "neoncity.faction_event" in published_events
        assert "lounge.new_rumor" in published_events

    def test_arena_match_winner_in_rumor(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = MagicMock()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay._on_arena_match_end({"winner": "Kira", "faction": "Syndicate"})
        lounge_calls = [
            c[0][1] for c in mock_bus.publish.call_args_list
            if c[0][0] == "lounge.new_rumor"
        ]
        assert any("Kira" in call["text"] for call in lounge_calls)

    def test_casino_win_ripples(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = MagicMock()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay._on_casino_major_win({"amount": 50000, "player": "Viktor"})
        published_events = [c[0][0] for c in mock_bus.publish.call_args_list]
        assert "lounge.new_rumor" in published_events
        assert "intel_hub.alert" in published_events

    def test_casino_win_amount_formatted(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = MagicMock()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay._on_casino_major_win({"amount": 50000, "player": "Viktor"})
        lounge_calls = [
            c[0][1] for c in mock_bus.publish.call_args_list
            if c[0][0] == "lounge.new_rumor"
        ]
        assert any("50,000" in call["text"] for call in lounge_calls)

    def test_heist_completed_ripples(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = MagicMock()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay._on_heist_completed({"target": "OmniCorp Vault", "crew": ["Kira", "Viktor"]})
        published_events = [c[0][0] for c in mock_bus.publish.call_args_list]
        assert "intel_hub.alert" in published_events
        assert "neoncity.faction_event" in published_events

    def test_heist_crew_count_in_alert(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = MagicMock()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay._on_heist_completed({"target": "OmniCorp Vault", "crew": ["Kira", "Viktor"]})
        alert_calls = [
            c[0][1] for c in mock_bus.publish.call_args_list
            if c[0][0] == "intel_hub.alert"
        ]
        assert any("2" in call["headline"] for call in alert_calls)

    def test_faction_shift_ripples(self):
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = MagicMock()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay._on_faction_shift({"faction": "Syndicate", "direction": "up"})
        published_events = [c[0][0] for c in mock_bus.publish.call_args_list]
        assert "tavern.new_rumor" in published_events

    def test_ripple_handler_survives_bad_payload(self):
        """Handlers must not raise even with empty payloads."""
        from engine.events.cross_scene_relay import CrossSceneRelay
        relay = CrossSceneRelay()
        mock_bus = MagicMock()
        with patch("engine.events.cross_scene_relay.get_event_bus", return_value=mock_bus):
            relay._on_arena_match_end({})
            relay._on_casino_major_win({})
            relay._on_heist_completed({})
            relay._on_faction_shift({})


class TestSceneDirectorAccessor:
    """Verify get_scene_director() returns a functional SceneDirector singleton."""

    def test_get_scene_director_returns_instance(self):
        from engine.director.scene_director import SceneDirector, get_scene_director
        director = get_scene_director()
        assert isinstance(director, SceneDirector)

    def test_get_scene_director_singleton(self):
        import engine.director.scene_director as mod
        original = mod._director_instance
        mod._director_instance = None
        try:
            from engine.director.scene_director import get_scene_director
            a = get_scene_director()
            b = get_scene_director()
            assert a is b
        finally:
            mod._director_instance = original

    def test_scene_director_tick_exists(self):
        from engine.director.scene_director import get_scene_director
        director = get_scene_director()
        assert callable(director.tick)

    def test_scene_director_tick_returns_none_on_stable_state(self):
        """tick() on a fresh director with no triggers should return None."""
        from engine.director.scene_director import SceneDirector
        from unittest.mock import MagicMock, patch
        mock_nexus = MagicMock()
        mock_nexus.search.return_value = []
        director = SceneDirector(nexus_client=mock_nexus)
        mock_bus = MagicMock()
        with patch("engine.director.scene_director._bus", return_value=mock_bus):
            with patch("engine.director.scene_director._event_types") as et:
                et.return_value.DIRECTOR_BEAT_FIRED = "director.beat_fired"
                result = director.tick("bedroom", {
                    "turn_count": 3,
                    "emotion_levels": {"arousal": 40.0},
                    "idle_seconds": 10.0,
                    "economy_balance": 500.0,
                })
        assert result is None


class TestSceneBeatConfigs:
    """Verify per-scene beat config structure."""

    def test_scene_beat_configs_imported(self):
        from engine.director.scene_director import SCENE_BEAT_CONFIGS
        assert isinstance(SCENE_BEAT_CONFIGS, dict)
        assert len(SCENE_BEAT_CONFIGS) > 0

    def test_bedroom_avoids_world_event(self):
        from engine.director.scene_director import SCENE_BEAT_CONFIGS, BeatType
        cfg = SCENE_BEAT_CONFIGS.get("bedroom", {})
        assert BeatType.WORLD_EVENT in cfg.get("avoid_beats", [])

    def test_bedroom_has_lower_escalation_threshold(self):
        from engine.director.scene_director import SCENE_BEAT_CONFIGS
        cfg = SCENE_BEAT_CONFIGS.get("bedroom", {})
        assert cfg.get("escalation_threshold", 80) < 80

    def test_all_configs_have_required_keys(self):
        from engine.director.scene_director import SCENE_BEAT_CONFIGS
        for scene, cfg in SCENE_BEAT_CONFIGS.items():
            assert "preferred_beats" in cfg, f"{scene} missing preferred_beats"
            assert "avoid_beats" in cfg, f"{scene} missing avoid_beats"
            assert "escalation_threshold" in cfg, f"{scene} missing escalation_threshold"

    def test_bedroom_escalation_threshold_fires_at_75(self):
        """bedroom escalation_threshold=70 means arousal=75 should fire ESCALATION."""
        from engine.director.scene_director import SceneDirector, BeatType
        from unittest.mock import MagicMock, patch
        mock_nexus = MagicMock()
        mock_nexus.search.return_value = []
        director = SceneDirector(nexus_client=mock_nexus)
        mock_bus = MagicMock()
        with patch("engine.director.scene_director._bus", return_value=mock_bus):
            with patch("engine.director.scene_director._event_types") as et:
                et.return_value.DIRECTOR_BEAT_FIRED = "director.beat_fired"
                beat = director.tick("bedroom", {
                    "turn_count": 3,
                    "emotion_levels": {"arousal": 75.0},
                    "idle_seconds": 0.0,
                    "economy_balance": 500.0,
                })
        assert beat is not None
        assert beat.beat_type == BeatType.ESCALATION
