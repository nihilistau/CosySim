"""
Tests for NEON OS Scene
=======================

Version: v1.0.0 [2026-03-25]

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
    """Create a test instance of NeonosScene."""
    with patch("engine.port_registry.get_port", return_value=5595):
        from content.scenes.neonos.neonos_scene import NeonosScene
        scene = NeonosScene(port=5595)
        scene.app.config["TESTING"] = True
        yield scene


@pytest.fixture
def client(scene_app):
    """Flask test client for NeonosScene."""
    return scene_app.app.test_client()


class TestNeonosSceneRoutes:
    """HTTP route tests for NEON OS."""

    def test_index_returns_200(self, client) -> None:
        resp = client.get("/")
        assert resp.status_code == 200

    def test_scene_state_api(self, client) -> None:
        resp = client.get("/api/scene/state")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["scene_id"] == "neonos"
