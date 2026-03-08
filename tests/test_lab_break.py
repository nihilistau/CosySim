"""Tests for the Lab Break scene — vitals, emotions, persuasion, items, door, game flow."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from content.scenes.lab_break.lab_break_scene import (
    EmotionalState,
    LabBreakScene,
    LabItem,
    PersuasionMetrics,
    VitalStats,
)


# ──── VitalStats ────────────────────────────────────────────────

class TestVitalStats:
    def test_initial_values(self):
        v = VitalStats()
        assert v.health == 100.0
        assert v.hunger == 0.0
        assert v.energy == 80.0
        assert v.stress == 30.0

    def test_tick_increases_hunger(self):
        v = VitalStats()
        v.tick(100.0)
        assert v.hunger > 0.0

    def test_tick_decreases_energy(self):
        v = VitalStats()
        v.tick(100.0)
        assert v.energy < 80.0

    def test_tick_high_hunger_damages_health(self):
        v = VitalStats(hunger=80.0)
        v.tick(100.0)
        assert v.health < 100.0

    def test_tick_low_energy_increases_stress(self):
        v = VitalStats(energy=10.0)
        v.tick(100.0)
        assert v.stress > 30.0

    def test_eat_reduces_hunger(self):
        v = VitalStats(hunger=60.0)
        v.eat(30.0)
        assert v.hunger == 30.0

    def test_eat_increases_energy(self):
        v = VitalStats(energy=50.0)
        v.eat(30.0)
        assert v.energy > 50.0

    def test_rest_increases_energy_and_reduces_stress(self):
        v = VitalStats(energy=30.0, stress=60.0)
        v.rest()
        assert v.energy == 45.0
        assert v.stress == 50.0

    def test_hunger_capped_at_100(self):
        v = VitalStats(hunger=99.0)
        v.tick(1000.0)
        assert v.hunger <= 100.0

    def test_health_floored_at_0(self):
        v = VitalStats(hunger=100.0, health=1.0)
        v.tick(1000.0)
        assert v.health >= 0.0

    def test_to_dict(self):
        v = VitalStats()
        d = v.to_dict()
        assert set(d.keys()) == {"health", "hunger", "energy", "stress"}


# ──── EmotionalState ──────────────────────────────────────────

class TestEmotionalState:
    def test_initial_dominant_emotion(self):
        e = EmotionalState()
        assert e.dominant_emotion == "confusion"

    def test_react_to_kindness(self):
        e = EmotionalState()
        e.react_to_kindness()
        assert e.trust > 10.0
        assert e.hope > 30.0

    def test_react_to_cruelty(self):
        e = EmotionalState()
        e.react_to_cruelty()
        assert e.anger > 20.0
        assert e.trust < 10.0

    def test_react_to_silence(self):
        e = EmotionalState()
        e.react_to_silence()
        assert e.desperation > 40.0

    def test_dominant_emotion_changes(self):
        e = EmotionalState(fear=0, anger=0, hope=0, trust=0, desperation=0, confusion=0)
        e.anger = 100.0
        assert e.dominant_emotion == "anger"

    def test_to_dict_includes_dominant(self):
        e = EmotionalState()
        d = e.to_dict()
        assert "dominant_emotion" in d
        assert d["dominant_emotion"] == e.dominant_emotion


# ──── PersuasionMetrics ───────────────────────────────────────

class TestPersuasionMetrics:
    def test_initial_score_is_zero(self):
        m = PersuasionMetrics()
        m.update_score()
        assert m.persuasion_score == 0.0

    def test_kindness_increases_score(self):
        m = PersuasionMetrics(kindness_received=5, items_received=3)
        m.update_score()
        assert m.persuasion_score > 0.0

    def test_cruelty_decreases_score(self):
        m = PersuasionMetrics(cruelty_received=10)
        m.update_score()
        assert m.persuasion_score == 0.0

    def test_score_capped_at_100(self):
        m = PersuasionMetrics(kindness_received=100, items_received=100, user_responses=100)
        m.update_score()
        assert m.persuasion_score == 100.0


# ──── LabItem ─────────────────────────────────────────────────

class TestLabItem:
    def test_to_dict(self):
        item = LabItem(
            id="apple", name="Apple", description="A red apple",
            category="food", nutrition=25.0,
        )
        d = item.to_dict()
        assert d["id"] == "apple"
        assert d["nutrition"] == 25.0


# ──── LabBreakScene ───────────────────────────────────────────

class TestLabBreakScene:
    @pytest.fixture
    def scene(self):
        s = LabBreakScene(config={})
        return s

    def test_metadata(self, scene):
        assert scene.SCENE_METADATA["name"] == "lab_break"
        assert scene.SCENE_METADATA["port"] == 5571
        assert scene.SCENE_METADATA["type"] == "game"

    def test_initial_state(self, scene):
        assert scene.game_active is True
        assert scene.door_open is False
        assert scene.speaker_on is True
        assert len(scene.lab_items) == 0
        assert len(scene.conversation_history) == 0

    def test_get_scene_state_structure(self, scene):
        scene.game_start_time = 0
        state = scene._get_scene_state()
        assert "game_active" in state
        assert "vitals" in state
        assert "emotions" in state
        assert "metrics" in state
        assert "door_open" in state
        assert "character" in state

    def test_item_catalog_not_empty(self, scene):
        assert len(scene.ITEM_CATALOG) >= 10

    def test_build_system_prompt_contains_key_phrases(self, scene):
        prompt = scene._build_system_prompt()
        assert "laboratory" in prompt.lower()
        assert "mirror" in prompt.lower()
        assert "convince" in prompt.lower()
        assert "real" in prompt.lower()

    def test_build_system_prompt_reflects_hunger(self, scene):
        scene.vitals.hunger = 80.0
        prompt = scene._build_system_prompt()
        assert "hungry" in prompt.lower()

    def test_build_system_prompt_reflects_exhaustion(self, scene):
        scene.vitals.energy = 10.0
        prompt = scene._build_system_prompt()
        assert "exhausted" in prompt.lower()

    def test_drop_item_known(self, scene):
        scene.socketio = MagicMock()
        result = scene._drop_item("apple")
        assert "item" in result
        assert result["item"]["name"] == "Apple"
        assert len(scene.lab_items) == 1
        assert scene.metrics.items_received == 1

    def test_drop_item_unknown(self, scene):
        result = scene._drop_item("nonexistent_item_xyz")
        assert "error" in result

    def test_drop_food_item_reduces_hunger(self, scene):
        scene.socketio = MagicMock()
        scene.vitals.hunger = 50.0
        scene._drop_item("apple")
        assert scene.vitals.hunger < 50.0

    def test_drop_item_triggers_kindness(self, scene):
        scene.socketio = MagicMock()
        scene._drop_item("bread")
        assert scene.emotions.trust > 10.0

    def test_handle_user_message_kind(self, scene):
        scene.socketio = MagicMock()
        result = scene._handle_user_message("I believe you are real, please trust me")
        assert "reply" in result
        assert "emotion" in result
        assert scene.metrics.kindness_received >= 1
        assert len(scene.conversation_history) >= 2

    def test_handle_user_message_cruel(self, scene):
        scene.socketio = MagicMock()
        scene._handle_user_message("You are just a fake robot AI program")
        assert scene.metrics.cruelty_received >= 1

    def test_fallback_reply_based_on_emotion(self, scene):
        scene.emotions.anger = 100.0
        scene.emotions.fear = 0.0
        scene.emotions.confusion = 0.0
        reply = scene._fallback_reply("test")
        assert isinstance(reply, str)
        assert len(reply) > 10

    def test_handle_door_open_wins_game(self, scene):
        scene.socketio = MagicMock()
        scene.game_start_time = 100.0
        result = scene._handle_door("open")
        assert result["door_open"] is True
        assert result["game_over"] is True
        assert result["won"] is True
        assert scene.metrics.game_won is True
        assert scene.game_active is False

    def test_handle_door_close(self, scene):
        scene.socketio = MagicMock()
        scene.door_open = True
        scene.game_active = False
        result = scene._handle_door("close")
        assert result["door_open"] is False

    def test_handle_door_toggle(self, scene):
        scene.socketio = MagicMock()
        scene.game_active = False
        assert scene.door_open is False
        scene._handle_door("toggle")
        assert scene.door_open is True

    def test_reset_game(self, scene):
        scene.socketio = MagicMock()
        scene.vitals.hunger = 80.0
        scene.emotions.anger = 90.0
        scene.metrics.total_attempts = 10
        scene.lab_items.append(LabItem(id="x", name="X", description="x", category="tool"))
        scene.door_open = True
        scene.game_active = False
        scene._reset_game()
        assert scene.vitals.hunger == 0.0
        assert scene.emotions.anger == 20.0
        assert scene.metrics.total_attempts == 0
        assert len(scene.lab_items) == 0
        assert scene.door_open is False
        assert scene.game_active is True

    def test_get_plugin_info(self, scene):
        info = scene.get_plugin_info()
        assert info["name"] == "lab_break"
        assert info["port"] == 5571
        assert "game_active" in info

    def test_generate_victory_message_kind_path(self, scene):
        scene.game_start_time = 0
        scene.metrics.kindness_received = 5
        scene.metrics.cruelty_received = 1
        msg = scene._generate_victory_message()
        assert "thank" in msg.lower() or "knew" in msg.lower()

    def test_generate_victory_message_cruel_path(self, scene):
        scene.game_start_time = 0
        scene.metrics.kindness_received = 0
        scene.metrics.cruelty_received = 5
        msg = scene._generate_victory_message()
        assert "don't" in msg.lower() or "free" in msg.lower()

    def test_generate_item_reaction_food(self, scene):
        item = LabItem(id="apple", name="Apple", description="apple", category="food")
        reaction = scene._generate_item_reaction(item)
        assert "apple" in reaction.lower()

    def test_generate_item_reaction_medical(self, scene):
        item = LabItem(id="bandage", name="Bandage", description="bandage", category="medical")
        reaction = scene._generate_item_reaction(item)
        assert "help" in reaction.lower() or "bandage" in reaction.lower()

    def test_generate_item_reaction_tool(self, scene):
        item = LabItem(id="pen", name="Pen", description="pen", category="tool")
        reaction = scene._generate_item_reaction(item)
        assert "pen" in reaction.lower()

    def test_generate_item_reaction_document(self, scene):
        item = LabItem(id="clip", name="Clipboard", description="notes", category="document")
        reaction = scene._generate_item_reaction(item)
        assert "clipboard" in reaction.lower() or "notes" in reaction.lower()

    def test_generate_item_reaction_random(self, scene):
        item = LabItem(id="teddy", name="Teddy Bear", description="bear", category="random")
        reaction = scene._generate_item_reaction(item)
        assert "teddy" in reaction.lower() or "bear" in reaction.lower()


# ──── LabBreakScene Flask Routes ──────────────────────────────

class TestLabBreakRoutes:
    @pytest.fixture
    def scene_with_app(self):
        scene = LabBreakScene(config={})
        scene._setup_flask()
        scene._register_routes()
        scene.game_start_time = 0
        return scene

    @pytest.fixture
    def client(self, scene_with_app):
        scene_with_app.app.config["TESTING"] = True
        return scene_with_app.app.test_client()

    def test_get_state(self, client):
        resp = client.get("/api/state")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "vitals" in data
        assert "emotions" in data

    def test_speak_empty(self, client):
        resp = client.post("/api/speak", json={"message": ""})
        assert resp.status_code == 400

    def test_speak_valid(self, client, scene_with_app):
        scene_with_app.socketio = MagicMock()
        resp = client.post("/api/speak", json={"message": "Hello, can you hear me?"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "reply" in data

    def test_drop_item_route(self, client, scene_with_app):
        scene_with_app.socketio = MagicMock()
        resp = client.post("/api/drop_item", json={"item_id": "apple"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "item" in data

    def test_drop_unknown_item_route(self, client):
        resp = client.post("/api/drop_item", json={"item_id": "unknown_xyz"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "error" in data

    def test_door_open_route(self, client, scene_with_app):
        scene_with_app.socketio = MagicMock()
        resp = client.post("/api/door", json={"action": "open"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["door_open"] is True

    def test_speaker_toggle_route(self, client, scene_with_app):
        scene_with_app.socketio = MagicMock()
        resp = client.post("/api/speaker")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "speaker_on" in data

    def test_metrics_route(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "persuasion_score" in data

    def test_items_route(self, client):
        resp = client.get("/api/items")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "catalog" in data
        assert "lab_items" in data

    def test_character_route(self, client):
        resp = client.get("/api/character")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Subject Alpha"

    def test_history_route(self, client):
        resp = client.get("/api/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_reset_route(self, client, scene_with_app):
        scene_with_app.socketio = MagicMock()
        resp = client.post("/api/reset")
        assert resp.status_code == 200

    def test_health_route(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
