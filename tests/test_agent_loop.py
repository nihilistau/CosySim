"""Tests for engine.agents.agent_loop — AgentLoop tick cycle."""
import pytest
from unittest.mock import MagicMock, patch
from engine.spatial.location import Location
from engine.spatial.scene_map import SceneMap
from engine.agents.agent_loop import AgentLoop


def _make_char(cid, name, mood="neutral"):
    """Create a mock Character with required attributes."""
    c = MagicMock()
    c.id = cid
    c.name = name
    c.mood = mood
    c.arousal = 0.0
    c.energy = 1.0
    c.relationship_level = 0.5
    return c


def _make_scene():
    """Build a small SceneMap with 2 locations."""
    sm = SceneMap()
    sm.add_location(Location(id="bed", name="Bed", capacity=2,
                             properties={"privacy": 0.9, "spiciness": 5}))
    sm.add_location(Location(id="bar", name="Bar", capacity=2,
                             properties={"privacy": 0.3, "spiciness": 2}))
    return sm


class TestAgentLoopInit:
    def test_valid_actions_exist(self):
        assert "speak" in AgentLoop.VALID_ACTIONS
        assert "move" in AgentLoop.VALID_ACTIONS
        assert "intimate" in AgentLoop.VALID_ACTIONS

    def test_not_running_initially(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm)
        assert loop.is_running is False

    def test_tick_count_starts_zero(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm)
        assert loop._tick_count == 0


class TestRegistration:
    def test_register_character(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm)
        char = _make_char("c1", "Luna")
        loop.register_character(char)
        assert "c1" in loop._characters
        assert loop._names["c1"] == "Luna"

    def test_unregister_character(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm)
        char = _make_char("c1", "Luna")
        loop.register_character(char)
        sm.place_character("c1", "bed")
        loop.unregister_character("c1")
        assert "c1" not in loop._characters
        assert sm.get_character_location("c1") is None

    def test_register_with_agent(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm)
        char = _make_char("c1", "Luna")
        agent = MagicMock()
        loop.register_character(char, agent=agent)
        assert loop._agents["c1"] is agent


class TestActionCallback:
    def test_callback_set(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm)
        fn = MagicMock()
        loop.set_action_callback(fn)
        assert loop._on_action is fn


class TestTick:
    """Test the tick cycle without real LLM (falls back to random actions)."""

    def test_tick_returns_actions(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm, llm_url="http://fake:9999/v1")
        c1 = _make_char("c1", "Luna")
        c2 = _make_char("c2", "Maya")
        loop.register_character(c1)
        loop.register_character(c2)
        sm.place_character("c1", "bed")
        sm.place_character("c2", "bar")

        actions = loop.tick()
        assert isinstance(actions, list)
        assert len(actions) == 2

    def test_tick_increments_count(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm, llm_url="http://fake:9999/v1")
        c1 = _make_char("c1", "Luna")
        loop.register_character(c1)
        sm.place_character("c1", "bed")

        loop.tick()
        assert loop._tick_count == 1
        loop.tick()
        assert loop._tick_count == 2

    def test_tick_actions_have_character_id(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm, llm_url="http://fake:9999/v1")
        c1 = _make_char("c1", "Luna")
        loop.register_character(c1)
        sm.place_character("c1", "bed")

        actions = loop.tick()
        assert actions[0]["character_id"] == "c1"

    def test_tick_fires_callback(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm, llm_url="http://fake:9999/v1")
        c1 = _make_char("c1", "Luna")
        loop.register_character(c1)
        sm.place_character("c1", "bed")

        cb = MagicMock()
        loop.set_action_callback(cb)
        loop.tick()
        assert cb.called

    def test_tick_with_socketio_emits(self):
        sm = _make_scene()
        sio = MagicMock()
        loop = AgentLoop(scene_map=sm, socketio=sio, llm_url="http://fake:9999/v1")
        c1 = _make_char("c1", "Luna")
        loop.register_character(c1)
        sm.place_character("c1", "bed")

        loop.tick()
        sio.emit.assert_called()


class TestSharedLog:
    def test_log_starts_empty(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm)
        assert loop.shared_log == []

    def test_external_append(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm)
        loop.shared_log.append({"name": "You", "text": "Hello", "type": "speech"})
        assert len(loop.shared_log) == 1


class TestStartStop:
    def test_start_sets_running(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm, llm_url="http://fake:9999/v1")
        c1 = _make_char("c1", "Luna")
        loop.register_character(c1)
        sm.place_character("c1", "bed")

        loop.start(interval=999)  # very long interval, won't actually tick
        assert loop.is_running is True
        loop.stop()
        assert loop.is_running is False

    def test_double_start_no_error(self):
        sm = _make_scene()
        loop = AgentLoop(scene_map=sm)
        c1 = _make_char("c1", "Luna")
        loop.register_character(c1)
        sm.place_character("c1", "bed")

        loop.start(interval=999)
        loop.start(interval=999)  # should be no-op
        loop.stop()
