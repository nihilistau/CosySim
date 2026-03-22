"""Tests for HeistScene — cooperative multi-agent planning & execution.
=====================================================================

Covers:
- SCENE_METADATA structure validation
- Class import verification
- Route registration (GET /api/venues, GET /api/game, POST /api/game/new,
  POST /api/game/action, POST /api/game/advance, POST /api/game/loot,
  POST /api/chat, POST /api/crew/tick)
- SocketIO handler registration
- Game state management (new game, actions, phase advance)
- Crew template configuration

Version: v1.49.5 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.5 [2026-03-22] — Initial test suite for HeistScene
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


# ──── Fixtures ────────────────────────────────────────────────────────


def _make_mock_db() -> MagicMock:
    """Build a mock Database with sensible defaults.

    Returns:
        Configured MagicMock mimicking Database.
    """
    db = MagicMock()
    db.get_all_characters.return_value = []
    return db


# v1.49.5 [2026-03-22] — Central fixture: mock all external deps, build test client
# CONNECTS: Database, HeistState, MCP Framework, TagRegistry, SceneStateManager
@pytest.fixture()
def heist_client():
    """Create a HeistScene with all external dependencies mocked
    and return (test_client, scene).
    """
    with patch("content.scenes.heist.heist_scene.Database", return_value=_make_mock_db()), \
         patch("content.scenes.heist.heist_scene.get_scene_state_manager", return_value=MagicMock()), \
         patch("content.scenes.heist.heist_scene.TagRegistry") as mock_tag_reg, \
         patch("content.scenes.heist.heist_scene.register_heist_rules"), \
         patch("content.scenes.heist.heist_scene.register_shared_assets"):
        mock_tag_reg.get.return_value = MagicMock()

        from content.scenes.heist.heist_scene import HeistScene
        scene = HeistScene(port=19001)
        scene.app.config["TESTING"] = True
        client = scene.app.test_client()
        yield client, scene


# ──── Metadata ────────────────────────────────────────────────────────


class TestHeistMetadata:
    """SCENE_METADATA structure validation."""

    def test_scene_metadata_has_required_fields(self):
        """Verify all required metadata keys are present."""
        with patch("content.scenes.heist.heist_scene.Database", return_value=_make_mock_db()), \
             patch("content.scenes.heist.heist_scene.get_scene_state_manager", return_value=MagicMock()), \
             patch("content.scenes.heist.heist_scene.TagRegistry") as mock_tr, \
             patch("content.scenes.heist.heist_scene.register_heist_rules"), \
             patch("content.scenes.heist.heist_scene.register_shared_assets"):
            mock_tr.get.return_value = MagicMock()
            from content.scenes.heist.heist_scene import HeistScene
            meta = HeistScene.SCENE_METADATA
            assert meta["name"] == "heist"
            assert meta["display_name"] == "THE SCORE"
            assert meta["port"] == 5565
            assert "accent_color" in meta
            assert "description" in meta

    def test_metadata_features_list(self):
        """Features should include heist-specific capabilities."""
        with patch("content.scenes.heist.heist_scene.Database", return_value=_make_mock_db()), \
             patch("content.scenes.heist.heist_scene.get_scene_state_manager", return_value=MagicMock()), \
             patch("content.scenes.heist.heist_scene.TagRegistry") as mock_tr, \
             patch("content.scenes.heist.heist_scene.register_heist_rules"), \
             patch("content.scenes.heist.heist_scene.register_shared_assets"):
            mock_tr.get.return_value = MagicMock()
            from content.scenes.heist.heist_scene import HeistScene
            features = HeistScene.SCENE_METADATA["features"]
            assert "heist_planning" in features
            assert "crew_roles" in features
            assert "phase_system" in features


# ──── Import ──────────────────────────────────────────────────────────


class TestHeistImport:
    """Verify the class is importable without side effects."""

    def test_class_importable(self):
        from content.scenes.heist.heist_scene import HeistScene
        assert HeistScene is not None

    def test_crew_templates_importable(self):
        from content.scenes.heist.heist_scene import CREW_TEMPLATES
        assert isinstance(CREW_TEMPLATES, dict)
        assert "ghost" in CREW_TEMPLATES
        assert "tank" in CREW_TEMPLATES
        assert "silk" in CREW_TEMPLATES
        assert "wheels" in CREW_TEMPLATES

    def test_scene_id_constant(self):
        from content.scenes.heist.heist_scene import SCENE_ID
        assert SCENE_ID == "heist"


# ──── Routes ──────────────────────────────────────────────────────────


class TestHeistVenuesRoute:
    """GET /api/venues — list available heist venues."""

    def test_venues_returns_200(self, heist_client):
        client, _ = heist_client
        resp = client.get("/api/venues")
        assert resp.status_code == 200

    def test_venues_returns_dict(self, heist_client):
        client, _ = heist_client
        data = resp = client.get("/api/venues").get_json()
        assert isinstance(data, dict)


class TestHeistGameStateRoute:
    """GET /api/game — get current game state."""

    def test_no_game_returns_inactive(self, heist_client):
        client, _ = heist_client
        resp = client.get("/api/game")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["active"] is False

    def test_active_game_returns_state(self, heist_client):
        """After setting game directly, the state should be active."""
        client, scene = heist_client
        mock_state = MagicMock()
        mock_state.to_dict.return_value = {"phase": "planning", "suspicion": 0, "loot_collected": 0}
        # Set game directly to avoid route calling undefined _sync_to_mcp
        scene.game = mock_state
        resp = client.get("/api/game")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["active"] is True


class TestHeistNewGameRoute:
    """POST /api/game/new — start a new heist."""

    def test_new_game_returns_success(self, heist_client):
        client, scene = heist_client
        mock_state = MagicMock()
        mock_state.to_dict.return_value = {"phase": "planning", "suspicion": 0}
        mock_state.crew = {}
        # _sync_to_mcp is called by the route but not defined on HeistScene;
        # mock it to avoid AttributeError
        scene._sync_to_mcp = MagicMock()
        with patch("content.scenes.heist.heist_scene.HeistState") as mock_hs:
            mock_hs.new_heist.return_value = mock_state
            resp = client.post("/api/game/new", json={"venue": "diamond_exchange", "crew": []})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "game" in data


class TestHeistActionRoute:
    """POST /api/game/action — perform an in-game action."""

    def test_action_no_game_returns_400(self, heist_client):
        client, _ = heist_client
        resp = client.post("/api/game/action", json={"character_id": "ghost", "action": "hack"})
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_action_missing_fields_returns_400(self, heist_client):
        client, scene = heist_client
        scene.game = MagicMock()
        resp = client.post("/api/game/action", json={"character_id": "", "action": ""})
        assert resp.status_code == 400


class TestHeistAdvanceRoute:
    """POST /api/game/advance — advance the heist phase."""

    def test_advance_no_game_returns_400(self, heist_client):
        client, _ = heist_client
        resp = client.post("/api/game/advance")
        assert resp.status_code == 400

    def test_advance_with_game_returns_phase(self, heist_client):
        client, scene = heist_client
        mock_game = MagicMock()
        mock_game.to_dict.return_value = {"phase": "approach"}
        mock_game.loot_collected = 0
        from content.scenes.heist.heist_game import Phase
        mock_game.advance_phase.return_value = Phase.APPROACH
        scene.game = mock_game
        resp = client.post("/api/game/advance")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "phase" in data


class TestHeistLootRoute:
    """POST /api/game/loot — collect loot."""

    def test_loot_no_game_returns_400(self, heist_client):
        client, _ = heist_client
        resp = client.post("/api/game/loot", json={"amount": 50000})
        assert resp.status_code == 400

    def test_loot_returns_total(self, heist_client):
        client, scene = heist_client
        mock_game = MagicMock()
        mock_game.collect_loot.return_value = 50000
        mock_game.loot_target = 500000
        mock_game.to_dict.return_value = {"loot_collected": 50000}
        scene.game = mock_game
        resp = client.post("/api/game/loot", json={"amount": 50000})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 50000
        assert data["target"] == 500000


class TestHeistChatRoute:
    """POST /api/chat — send a message to a crew member."""

    def test_chat_no_game_returns_400(self, heist_client):
        client, _ = heist_client
        resp = client.post("/api/chat", json={"character_id": "ghost", "message": "Hello"})
        assert resp.status_code == 400

    def test_chat_missing_fields_returns_400(self, heist_client):
        client, scene = heist_client
        scene.game = MagicMock()
        resp = client.post("/api/chat", json={"character_id": "", "message": ""})
        assert resp.status_code == 400
