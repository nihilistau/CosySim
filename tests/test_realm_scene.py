"""Tests for RealmScene — AI-Directed LitRPG / Visual Novel.
=============================================================

Covers:
- SCENE_METADATA structure validation
- Class import verification
- Route registration (GET /api/scene/info, GET /api/game/state,
  POST /api/game/new, POST /api/game/choice, POST /api/game/desperation,
  POST /api/game/mutiny, POST /api/game/steal, POST /api/game/use_item)
- Director/Assistant agent inference mocking
- Game state management
- Parse director response fallback

Version: v1.49.5 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.5 [2026-03-22] — Initial test suite for RealmScene
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


# ──── Fixtures ────────────────────────────────────────────────────────


# v1.49.5 [2026-03-22] — Central fixture: mock all external deps, build test client
# CONNECTS: MCPFramework, SceneStateManager, TagRegistry, RealmGameState
@pytest.fixture()
def realm_client():
    """Create a RealmScene with all external dependencies mocked
    and return (test_client, scene).
    """
    with patch("content.scenes.realm.realm_scene.get_framework", return_value=MagicMock()), \
         patch("content.scenes.realm.realm_scene.get_scene_state_manager", return_value=MagicMock()), \
         patch("content.scenes.realm.realm_scene.TagRegistry") as mock_tr, \
         patch("content.scenes.realm.realm_scene.register_realm_rules"), \
         patch("content.scenes.realm.realm_scene.register_shared_assets"):
        mock_tr.get.return_value = MagicMock()

        from content.scenes.realm.realm_scene import RealmScene
        scene = RealmScene(port=19002)
        scene.app.config["TESTING"] = True
        client = scene.app.test_client()
        yield client, scene


# ──── Metadata ────────────────────────────────────────────────────────


class TestRealmMetadata:
    """SCENE_METADATA structure validation."""

    def test_scene_metadata_has_required_fields(self):
        """Verify all required metadata keys are present."""
        with patch("content.scenes.realm.realm_scene.get_framework", return_value=MagicMock()), \
             patch("content.scenes.realm.realm_scene.get_scene_state_manager", return_value=MagicMock()), \
             patch("content.scenes.realm.realm_scene.TagRegistry") as mock_tr, \
             patch("content.scenes.realm.realm_scene.register_realm_rules"), \
             patch("content.scenes.realm.realm_scene.register_shared_assets"):
            mock_tr.get.return_value = MagicMock()
            from content.scenes.realm.realm_scene import RealmScene
            meta = RealmScene.SCENE_METADATA
            assert meta["name"] == "realm"
            assert meta["display_name"] == "THE SHATTERED THRONE"
            assert meta["port"] == 5562
            assert "accent_color" in meta
            assert "description" in meta

    def test_metadata_type_is_rpg(self):
        with patch("content.scenes.realm.realm_scene.get_framework", return_value=MagicMock()), \
             patch("content.scenes.realm.realm_scene.get_scene_state_manager", return_value=MagicMock()), \
             patch("content.scenes.realm.realm_scene.TagRegistry") as mock_tr, \
             patch("content.scenes.realm.realm_scene.register_realm_rules"), \
             patch("content.scenes.realm.realm_scene.register_shared_assets"):
            mock_tr.get.return_value = MagicMock()
            from content.scenes.realm.realm_scene import RealmScene
            assert RealmScene.SCENE_METADATA["type"] == "rpg"

    def test_metadata_features_include_combat_and_quests(self):
        with patch("content.scenes.realm.realm_scene.get_framework", return_value=MagicMock()), \
             patch("content.scenes.realm.realm_scene.get_scene_state_manager", return_value=MagicMock()), \
             patch("content.scenes.realm.realm_scene.TagRegistry") as mock_tr, \
             patch("content.scenes.realm.realm_scene.register_realm_rules"), \
             patch("content.scenes.realm.realm_scene.register_shared_assets"):
            mock_tr.get.return_value = MagicMock()
            from content.scenes.realm.realm_scene import RealmScene
            features = RealmScene.SCENE_METADATA["features"]
            assert "combat" in features
            assert "quests" in features
            assert "murder_mystery" in features


# ──── Import ──────────────────────────────────────────────────────────


class TestRealmImport:
    """Verify the class is importable."""

    def test_class_importable(self):
        from content.scenes.realm.realm_scene import RealmScene
        assert RealmScene is not None

    def test_scene_id_constant(self):
        from content.scenes.realm.realm_scene import SCENE_ID
        assert SCENE_ID == "realm"

    def test_prompt_templates_importable(self):
        """Director and assistant prompt builders should be importable."""
        from content.scenes.realm.realm_scene import _director_system_prompt, _assistant_system_prompt
        assert callable(_director_system_prompt)
        assert callable(_assistant_system_prompt)


# ──── Routes ──────────────────────────────────────────────────────────


class TestRealmSceneInfoRoute:
    """GET /api/scene/info — scene plugin info."""

    def test_scene_info_returns_200(self, realm_client):
        client, _ = realm_client
        resp = client.get("/api/scene/info")
        assert resp.status_code == 200

    def test_scene_info_contains_name(self, realm_client):
        client, _ = realm_client
        data = client.get("/api/scene/info").get_json()
        assert "name" in data or "display_name" in data


class TestRealmGameStateRoute:
    """GET /api/game/state — get current game state."""

    def test_no_game_returns_inactive(self, realm_client):
        client, _ = realm_client
        resp = client.get("/api/game/state")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["active"] is False


class TestRealmNewGameRoute:
    """POST /api/game/new — start a new adventure."""

    def test_new_game_with_mocked_director(self, realm_client):
        """New game should succeed when Director inference is mocked."""
        client, scene = realm_client
        mock_result = {
            "narration": "You awaken in a dark chamber...",
            "choices": [{"id": "a", "text": "Look around"}],
            "stat_changes": {},
            "items_gained": [],
            "items_lost": [],
            "xp": 0,
            "damage": 0,
            "skill_check": None,
        }
        with patch.object(scene, "_director_infer", return_value=mock_result), \
             patch.object(scene, "_assistant_infer", return_value="*yawns* Another hero."), \
             patch.object(scene, "_sync_to_mcp"):
            resp = client.post("/api/game/new", json={"personality": "classic"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "narration" in data
        assert "choices" in data


class TestRealmChoiceRoute:
    """POST /api/game/choice — player makes a choice."""

    def test_choice_no_game_returns_400(self, realm_client):
        client, _ = realm_client
        resp = client.post("/api/game/choice", json={"choice_id": "a"})
        assert resp.status_code == 400
        assert "error" in resp.get_json()


class TestRealmDesperationRoute:
    """POST /api/game/desperation — desperation dice roll."""

    def test_desperation_no_game_returns_400(self, realm_client):
        client, _ = realm_client
        resp = client.post("/api/game/desperation")
        assert resp.status_code == 400


class TestRealmMutinyRoute:
    """POST /api/game/mutiny — trigger assistant mutiny."""

    def test_mutiny_no_game_returns_400(self, realm_client):
        client, _ = realm_client
        resp = client.post("/api/game/mutiny")
        assert resp.status_code == 400


class TestRealmStealRoute:
    """POST /api/game/steal — assistant steals an item."""

    def test_steal_no_game_returns_400(self, realm_client):
        client, _ = realm_client
        resp = client.post("/api/game/steal", json={"item_name": "Golden Apple"})
        assert resp.status_code == 400


# ──── Director Response Parsing ───────────────────────────────────────


class TestRealmDirectorParsing:
    """Test _parse_director_response fallback behavior."""

    def test_parse_valid_json_block(self, realm_client):
        _, scene = realm_client
        raw = '```json\n{"narration": "You enter.", "choices": [{"id": "a", "text": "Go"}]}\n```'
        result = scene._parse_director_response(raw)
        assert result["narration"] == "You enter."
        assert len(result["choices"]) == 1

    def test_parse_fallback_on_plain_text(self, realm_client):
        """Plain text without JSON should produce narration with default choices."""
        _, scene = realm_client
        raw = "The wind howls through the broken towers."
        result = scene._parse_director_response(raw)
        assert result["narration"] == raw
        assert len(result["choices"]) >= 2

    def test_parse_ensures_required_fields(self, realm_client):
        """All required response fields must be present."""
        _, scene = realm_client
        raw = '```json\n{"narration": "Test"}\n```'
        result = scene._parse_director_response(raw)
        assert "choices" in result
        assert "stat_changes" in result
        assert "xp" in result
        assert "damage" in result
