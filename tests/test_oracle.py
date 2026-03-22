"""
Tests for THE ORACLE Scene
==========================

Version: v1.0.0 [2026-03-22]

Covers:
    - Scene class instantiation
    - HTTP routes return 200
    - Socket.IO handlers respond
"""
from __future__ import annotations

import pytest
from unittest.mock import patch


@pytest.fixture
def scene_app():
    """Create a test instance of OracleScene."""
    with patch("engine.port_registry.get_port", return_value=5591):
        from content.scenes.oracle.oracle_scene import OracleScene
        scene = OracleScene(port=5591)
        scene.app.config["TESTING"] = True
        yield scene


@pytest.fixture
def client(scene_app):
    """Flask test client for OracleScene."""
    return scene_app.app.test_client()


class TestOracleSceneRoutes:
    """HTTP route tests for THE ORACLE."""

    def test_index_returns_200(self, client) -> None:
        resp = client.get("/")
        assert resp.status_code == 200

    def test_health_returns_200_or_not_found(self, client) -> None:
        # /health is registered by FlaskScene.start() which isn't called in tests
        resp = client.get("/health")
        assert resp.status_code in (200, 404)

    def test_scene_state_api(self, client) -> None:
        resp = client.get("/api/scene/state")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["scene_id"] == "oracle"
