"""Tests for Intel Hub scene."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def hub_app():
    """Intel Hub Flask test client with fully-wired routes."""
    from flask import Flask

    mock_profile = {
        "name": "User",
        "facts": ["Has RTX 2060"],
        "preferences": {"verbosity": "concise"},
        "technical_background": ["Python", "CUDA"],
        "projects": {"CosySim": {"version": "0.65"}},
        "topics_of_interest": ["AI", "fine-tuning"],
        "conversation_count": 3,
        "last_updated": "2026-03-01T00:00:00Z",
    }

    mock_store = MagicMock()
    mock_store.get_profile.return_value = mock_profile
    mock_store.get_context_summary.return_value = "## User Profile: User\n**Tech Background:** Python"
    mock_store.add_fact = MagicMock()
    mock_store.add_preference = MagicMock()

    app = Flask(__name__)
    app.config["TESTING"] = True

    with (
        patch("engine.config.get_config", return_value=MagicMock(get=lambda k, d=None: d)),
        patch("content.scenes.intel_hub.intel_hub_scene.register_shared_assets"),
        patch("content.scenes.intel_hub.intel_hub_scene.SocketIO", None),
        patch("engine.scenes.base_scene.BaseScene.__init__", lambda s, **kw: None),
        patch("engine.scenes.base_scene.BaseScene.register_health_route"),
        # Patch at the source so lazy imports in route handlers resolve correctly
        patch("engine.nexus.user_profile.get_user_profile_store", return_value=mock_store),
    ):
        from content.scenes.intel_hub.intel_hub_scene import IntelHubScene
        scene = IntelHubScene.__new__(IntelHubScene)
        scene._app = app
        scene._host = "0.0.0.0"
        scene._port = 5580
        scene._activity = []
        scene._stop_event = MagicMock()
        scene._register_routes()

        yield app.test_client(), mock_store


class TestIntelHubScene:
    def test_scene_metadata(self):
        from content.scenes.intel_hub.intel_hub_scene import IntelHubScene
        assert hasattr(IntelHubScene, "SCENE_METADATA")
        assert IntelHubScene.SCENE_METADATA.get("type") == "admin"
        assert "Intelligence Hub" in IntelHubScene.SCENE_METADATA.get("title", "")

    def test_scene_package_has_init(self):
        """Package is importable."""
        import content.scenes.intel_hub
        assert content.scenes.intel_hub is not None

    def test_skills_module_importable(self):
        from content.scenes.intel_hub import intel_hub_skills
        assert intel_hub_skills is not None

    def test_skills_have_skill_decorator(self):
        from content.scenes.intel_hub.intel_hub_skills import (
            intel_hub_status,
            intel_hub_cache_status,
        )
        assert callable(intel_hub_status)
        assert callable(intel_hub_cache_status)


class TestIntelHubConfig:
    def test_port_in_default_yaml(self):
        import yaml
        from pathlib import Path
        cfg_path = Path("config/default.yaml")
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text())
            intel_hub_cfg = cfg.get("scenes", {}).get("intel_hub", {})
            assert intel_hub_cfg.get("port") == 5580


# ──────────────────────────────────────────────────────────────────────────────
# User Profile API routes
# ──────────────────────────────────────────────────────────────────────────────


class TestUserProfileRoutes:
    """Tests for GET/POST /api/user-profile/* endpoints."""

    def test_get_profile_returns_profile_dict(self, hub_app):
        """GET /api/user-profile returns the full profile."""
        client, mock_store = hub_app
        with patch(
            "content.scenes.intel_hub.intel_hub_scene._get_user_profile",
            return_value={"name": "User", "facts": ["Has RTX 2060"]},
        ):
            resp = client.get("/api/user-profile")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "User"
        assert "facts" in data

    def test_get_profile_context_returns_markdown(self, hub_app):
        """GET /api/user-profile/context returns a markdown context block."""
        client, mock_store = hub_app
        resp = client.get("/api/user-profile/context")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "context" in data
        assert "User Profile" in data["context"]

    def test_add_fact_succeeds(self, hub_app):
        """POST /api/user-profile/fact stores a new fact."""
        client, mock_store = hub_app
        resp = client.post(
            "/api/user-profile/fact",
            json={"fact": "Runs on Windows 11"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["fact"] == "Runs on Windows 11"
        mock_store.add_fact.assert_called_once_with("Runs on Windows 11")

    def test_add_fact_missing_body_returns_400(self, hub_app):
        """POST /api/user-profile/fact with no fact returns 400."""
        client, _ = hub_app
        resp = client.post(
            "/api/user-profile/fact",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_set_preference_succeeds(self, hub_app):
        """POST /api/user-profile/preference stores a preference."""
        client, mock_store = hub_app
        resp = client.post(
            "/api/user-profile/preference",
            json={"key": "verbosity", "value": "concise"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["key"] == "verbosity"
        mock_store.add_preference.assert_called_once_with("verbosity", "concise")

    def test_set_preference_missing_key_returns_400(self, hub_app):
        """POST /api/user-profile/preference with no key returns 400."""
        client, _ = hub_app
        resp = client.post(
            "/api/user-profile/preference",
            json={"value": "concise"},
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()
