"""Tests for LabBreakScene — 3D interactive escape simulation.
================================================================

Covers:
- SCENE_METADATA structure validation
- Class import verification
- Route registration (GET /api/state, POST /api/speak, POST /api/drop_item,
  POST /api/door, POST /api/speaker, GET /api/metrics, POST /api/reset,
  GET /api/history, GET /api/items, GET /api/character)
- Data models (VitalStats, EmotionalState, PersuasionMetrics, LabItem)
- Game state management (door, items, emotions, vitals)
- Fallback reply system
- Item reaction generation

Version: v1.49.5 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.5 [2026-03-22] — Initial test suite for LabBreakScene
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


# ──── Fixtures ────────────────────────────────────────────────────────


# v1.49.5 [2026-03-22] — Central fixture: mock LMStudio, build test client
# CONNECTS: FlaskScene, LMStudio chat, MCP Framework
@pytest.fixture()
def lab_client():
    """Create a LabBreakScene with all external dependencies mocked
    and return (test_client, scene).
    """
    with patch("content.scenes.lab_break.lab_break_scene.FlaskScene.__init__", return_value=None):
        from content.scenes.lab_break.lab_break_scene import LabBreakScene

        scene = LabBreakScene.__new__(LabBreakScene)
        # Manually set up required attributes that __init__ would set
        from flask import Flask
        from flask_socketio import SocketIO
        import threading

        scene.app = Flask(
            __name__,
            template_folder="C:/Files/Models/CosySim/content/scenes/lab_break/templates",
        )
        scene.app.config["TESTING"] = True
        scene.app.config["SECRET_KEY"] = "test-lab-break"
        scene.socketio = SocketIO(scene.app, logger=False, engineio_logger=False)
        scene.port = 19006
        scene.scene_name = "lab_break"
        scene._stop_event = threading.Event()

        # Initialize game state
        from content.scenes.lab_break.lab_break_scene import (
            VitalStats, EmotionalState, PersuasionMetrics,
        )
        scene.config = {}
        scene.vitals = VitalStats()
        scene.emotions = EmotionalState()
        scene.metrics = PersuasionMetrics()
        scene.lab_items = []
        scene.door_open = False
        scene.speaker_on = True
        scene.conversation_history = []
        scene.agent_actions = []
        scene.game_active = True
        scene.game_start_time = 1000000.0
        scene._vitals_thread = None
        scene._current_character_id = "subject-alpha"
        scene._character_name = "Subject Alpha"
        scene._character_backstory = "Test backstory."

        # Register routes
        scene._register_routes()
        scene._setup_socketio_handlers()

        client = scene.app.test_client()
        yield client, scene


# ──── Metadata ────────────────────────────────────────────────────────


class TestLabBreakMetadata:
    """SCENE_METADATA structure validation."""

    def test_scene_metadata_has_required_fields(self):
        from content.scenes.lab_break.lab_break_scene import LabBreakScene
        meta = LabBreakScene.SCENE_METADATA
        assert meta["name"] == "lab_break"
        assert meta["display_name"] == "LAB BREAK"
        assert meta["port"] == 5571
        assert "accent_color" in meta
        assert "description" in meta

    def test_metadata_type_is_game(self):
        from content.scenes.lab_break.lab_break_scene import LabBreakScene
        assert LabBreakScene.SCENE_METADATA["type"] == "game"

    def test_metadata_has_version(self):
        from content.scenes.lab_break.lab_break_scene import LabBreakScene
        assert "version" in LabBreakScene.SCENE_METADATA


# ──── Import ──────────────────────────────────────────────────────────


class TestLabBreakImport:
    """Verify the class and data models are importable."""

    def test_class_importable(self):
        from content.scenes.lab_break.lab_break_scene import LabBreakScene
        assert LabBreakScene is not None

    def test_scene_id_constant(self):
        from content.scenes.lab_break.lab_break_scene import SCENE_ID
        assert SCENE_ID == "lab_break"

    def test_vital_stats_importable(self):
        from content.scenes.lab_break.lab_break_scene import VitalStats
        assert VitalStats is not None

    def test_emotional_state_importable(self):
        from content.scenes.lab_break.lab_break_scene import EmotionalState
        assert EmotionalState is not None

    def test_item_catalog_exists(self):
        from content.scenes.lab_break.lab_break_scene import LabBreakScene
        catalog = LabBreakScene.ITEM_CATALOG
        assert isinstance(catalog, list)
        assert len(catalog) > 20


# ──── Data Models ─────────────────────────────────────────────────────


class TestVitalStats:
    """Test VitalStats dataclass behavior."""

    def test_default_values(self):
        from content.scenes.lab_break.lab_break_scene import VitalStats
        v = VitalStats()
        assert v.health == 100.0
        assert v.hunger == 0.0
        assert v.energy == 80.0
        assert v.stress == 30.0

    def test_tick_increases_hunger(self):
        from content.scenes.lab_break.lab_break_scene import VitalStats
        v = VitalStats()
        v.tick(100.0)
        assert v.hunger > 0.0

    def test_tick_decreases_energy(self):
        from content.scenes.lab_break.lab_break_scene import VitalStats
        v = VitalStats()
        initial_energy = v.energy
        v.tick(100.0)
        assert v.energy < initial_energy

    def test_eat_reduces_hunger(self):
        from content.scenes.lab_break.lab_break_scene import VitalStats
        v = VitalStats(hunger=50.0)
        v.eat(30.0)
        assert v.hunger == 20.0

    def test_rest_increases_energy_and_reduces_stress(self):
        from content.scenes.lab_break.lab_break_scene import VitalStats
        v = VitalStats(energy=50.0, stress=50.0)
        v.rest()
        assert v.energy == 65.0
        assert v.stress == 40.0

    def test_to_dict(self):
        from content.scenes.lab_break.lab_break_scene import VitalStats
        v = VitalStats()
        d = v.to_dict()
        assert "health" in d
        assert "hunger" in d
        assert "energy" in d
        assert "stress" in d

    def test_high_hunger_damages_health(self):
        """When hunger exceeds 70, health should degrade over time."""
        from content.scenes.lab_break.lab_break_scene import VitalStats
        v = VitalStats(hunger=80.0, health=100.0)
        v.tick(100.0)
        assert v.health < 100.0


class TestEmotionalState:
    """Test EmotionalState dataclass behavior."""

    def test_default_values(self):
        from content.scenes.lab_break.lab_break_scene import EmotionalState
        e = EmotionalState()
        assert e.fear == 60.0
        assert e.confusion == 70.0

    def test_react_to_kindness(self):
        from content.scenes.lab_break.lab_break_scene import EmotionalState
        e = EmotionalState()
        initial_trust = e.trust
        initial_hope = e.hope
        e.react_to_kindness()
        assert e.trust > initial_trust
        assert e.hope > initial_hope

    def test_react_to_cruelty(self):
        from content.scenes.lab_break.lab_break_scene import EmotionalState
        e = EmotionalState()
        initial_anger = e.anger
        e.react_to_cruelty()
        assert e.anger > initial_anger
        assert e.trust < 10.0  # trust should decrease

    def test_react_to_silence(self):
        from content.scenes.lab_break.lab_break_scene import EmotionalState
        e = EmotionalState()
        initial_desperation = e.desperation
        e.react_to_silence()
        assert e.desperation > initial_desperation

    def test_dominant_emotion(self):
        from content.scenes.lab_break.lab_break_scene import EmotionalState
        e = EmotionalState(fear=0, anger=0, hope=0, trust=0, desperation=0, confusion=100)
        assert e.dominant_emotion == "confusion"

    def test_to_dict_includes_dominant(self):
        from content.scenes.lab_break.lab_break_scene import EmotionalState
        e = EmotionalState()
        d = e.to_dict()
        assert "dominant_emotion" in d


class TestPersuasionMetrics:
    """Test PersuasionMetrics dataclass behavior."""

    def test_default_score_is_zero(self):
        from content.scenes.lab_break.lab_break_scene import PersuasionMetrics
        m = PersuasionMetrics()
        assert m.persuasion_score == 0.0
        assert m.game_won is False

    def test_update_score_with_kindness(self):
        from content.scenes.lab_break.lab_break_scene import PersuasionMetrics
        m = PersuasionMetrics(kindness_received=10, items_received=5)
        m.update_score()
        assert m.persuasion_score > 0.0

    def test_score_clamped_to_100(self):
        from content.scenes.lab_break.lab_break_scene import PersuasionMetrics
        m = PersuasionMetrics(kindness_received=100, items_received=100, user_responses=100)
        m.update_score()
        assert m.persuasion_score <= 100.0

    def test_cruelty_reduces_score(self):
        from content.scenes.lab_break.lab_break_scene import PersuasionMetrics
        m = PersuasionMetrics(cruelty_received=20)
        m.update_score()
        assert m.persuasion_score == 0.0  # clamped to 0


# ──── API Routes ──────────────────────────────────────────────────────


class TestLabBreakStateRoute:
    """GET /api/state — scene state snapshot."""

    def test_state_returns_200(self, lab_client):
        client, _ = lab_client
        resp = client.get("/api/state")
        assert resp.status_code == 200

    def test_state_contains_required_fields(self, lab_client):
        client, _ = lab_client
        data = client.get("/api/state").get_json()
        assert "game_active" in data
        assert "door_open" in data
        assert "speaker_on" in data
        assert "vitals" in data
        assert "emotions" in data
        assert "metrics" in data


class TestLabBreakSpeakRoute:
    """POST /api/speak — user speaks through the speaker."""

    def test_speak_empty_message_returns_400(self, lab_client):
        client, _ = lab_client
        resp = client.post("/api/speak", json={"message": ""})
        assert resp.status_code == 400

    def test_speak_with_message_returns_reply(self, lab_client):
        client, scene = lab_client
        with patch.object(scene, "_generate_agent_reply", return_value="Please help me!"):
            resp = client.post("/api/speak", json={"message": "Are you okay?"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "reply" in data
        assert "emotion" in data
        assert "vitals" in data

    def test_speak_kindness_increases_trust(self, lab_client):
        client, scene = lab_client
        initial_trust = scene.emotions.trust
        with patch.object(scene, "_generate_agent_reply", return_value="Thank you."):
            client.post("/api/speak", json={"message": "I believe you are real. I want to help you."})
        assert scene.emotions.trust > initial_trust


class TestLabBreakDropItemRoute:
    """POST /api/drop_item — drop an item into the lab."""

    def test_drop_valid_item(self, lab_client):
        client, _ = lab_client
        resp = client.post("/api/drop_item", json={"item_id": "bread"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "item" in data
        assert "reaction" in data

    def test_drop_unknown_item_returns_error(self, lab_client):
        client, _ = lab_client
        resp = client.post("/api/drop_item", json={"item_id": "nonexistent_item"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "error" in data

    def test_drop_food_feeds_subject(self, lab_client):
        """Dropping food should reduce hunger."""
        client, scene = lab_client
        scene.vitals.hunger = 60.0
        client.post("/api/drop_item", json={"item_id": "bread"})
        assert scene.vitals.hunger < 60.0


class TestLabBreakDoorRoute:
    """POST /api/door — open/close/toggle the door."""

    def test_door_open_triggers_game_over(self, lab_client):
        client, scene = lab_client
        resp = client.post("/api/door", json={"action": "open"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["door_open"] is True
        assert data["game_over"] is True
        assert data["won"] is True
        assert scene.game_active is False

    def test_door_close(self, lab_client):
        client, scene = lab_client
        scene.game_active = False  # Already ended
        resp = client.post("/api/door", json={"action": "close"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["door_open"] is False

    def test_door_toggle(self, lab_client):
        client, scene = lab_client
        scene.game_active = False
        scene.door_open = False
        resp = client.post("/api/door", json={"action": "toggle"})
        data = resp.get_json()
        assert data["door_open"] is True


class TestLabBreakSpeakerRoute:
    """POST /api/speaker — toggle speaker on/off."""

    def test_toggle_speaker(self, lab_client):
        client, scene = lab_client
        assert scene.speaker_on is True
        resp = client.post("/api/speaker")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["speaker_on"] is False
        assert scene.speaker_on is False


class TestLabBreakMetricsRoute:
    """GET /api/metrics — persuasion metrics."""

    def test_metrics_returns_200(self, lab_client):
        client, _ = lab_client
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "persuasion_score" in data
        assert "door_opened" in data


class TestLabBreakResetRoute:
    """POST /api/reset — reset the game."""

    def test_reset_returns_status(self, lab_client):
        client, scene = lab_client
        scene.game_active = False
        resp = client.post("/api/reset")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "reset"
        assert scene.game_active is True


class TestLabBreakHistoryRoute:
    """GET /api/history — conversation history."""

    def test_history_returns_empty_list(self, lab_client):
        client, _ = lab_client
        resp = client.get("/api/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


class TestLabBreakItemsRoute:
    """GET /api/items — lab items and catalog."""

    def test_items_returns_catalog(self, lab_client):
        client, _ = lab_client
        resp = client.get("/api/items")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "lab_items" in data
        assert "catalog" in data
        assert len(data["catalog"]) > 20


class TestLabBreakCharacterRoute:
    """GET /api/character — character info."""

    def test_character_returns_info(self, lab_client):
        client, _ = lab_client
        resp = client.get("/api/character")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == "subject-alpha"
        assert data["name"] == "Subject Alpha"
        assert "vitals" in data
        assert "emotions" in data


# ──── Fallback Reply ──────────────────────────────────────────────────


class TestLabBreakFallbackReply:
    """Test _fallback_reply produces emotionally appropriate responses."""

    def test_fallback_fear_response(self, lab_client):
        _, scene = lab_client
        scene.emotions.fear = 100
        scene.emotions.anger = 0
        scene.emotions.hope = 0
        scene.emotions.trust = 0
        scene.emotions.desperation = 0
        scene.emotions.confusion = 0
        reply = scene._fallback_reply("test")
        assert isinstance(reply, str)
        assert len(reply) > 10

    def test_fallback_anger_response(self, lab_client):
        _, scene = lab_client
        scene.emotions.fear = 0
        scene.emotions.anger = 100
        scene.emotions.hope = 0
        scene.emotions.trust = 0
        scene.emotions.desperation = 0
        scene.emotions.confusion = 0
        reply = scene._fallback_reply("test")
        assert isinstance(reply, str)
        assert len(reply) > 10
