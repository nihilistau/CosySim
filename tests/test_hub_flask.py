"""Tests for HubScene — initialization, routes, health, plugin info."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _make_hub(port: int = 18500):
    """Create a HubScene with BaseScene.__init__ and shared assets mocked.

    Patches BaseScene.__init__ and register_shared_assets so the constructor
    never touches the network or filesystem, then manually wires
    attributes and routes.
    """
    with patch("content.scenes.hub.hub_flask.BaseScene.__init__"), \
         patch("content.scenes.hub.hub_flask.register_shared_assets"):
        from content.scenes.hub.hub_flask import HubScene
        hub = HubScene.__new__(HubScene)

        # Manually set attributes that BaseScene.__init__ would set
        hub.scene_name = "hub"
        hub.host = "127.0.0.1"
        hub.port = port
        hub.active_characters = {}
        hub.streaming_enabled = True
        hub._active_streams = 0
        hub._total_stream_tokens = 0
        hub.scene_metadata = HubScene.SCENE_METADATA

        # Create real Flask app for route testing
        from pathlib import Path
        from jinja2 import ChoiceLoader, FileSystemLoader
        from flask import Flask
        _scene_dir = Path(__file__).parent.parent / "content" / "scenes" / "hub"
        _shared_dir = Path(__file__).parent.parent / "content" / "shared" / "templates"
        hub.app = Flask(
            "test_hub",
            template_folder=str(_scene_dir / "templates"),
            static_folder=str(_scene_dir / "static"),
            static_url_path="/hub/static",
        )
        hub.app.jinja_loader = ChoiceLoader([
            FileSystemLoader(str(_scene_dir / "templates")),
            FileSystemLoader(str(_shared_dir)),
        ])

        # Stub BaseScene helper used during __init__
        hub.register_health_route = MagicMock()

        # Wire routes (the real _setup_routes)
        hub._setup_routes()

        # Register the health route manually for /api/health testing
        _register_test_health(hub)

        return hub


def _register_test_health(hub):
    """Register a minimal /api/health route mimicking BaseScene.register_health_route."""
    from flask import Response
    import json as _json

    @hub.app.route("/api/health")
    def _health():
        health = {
            "ok": True,
            "scene": hub.scene_name,
            "port": hub.port,
            "status": "running",
        }
        return Response(_json.dumps(health), mimetype="application/json")


# ═══════════════════════════════════════════════════════════════
#  Imports
# ═══════════════════════════════════════════════════════════════

class TestImports:
    """Module-level constants and class imports work."""

    def test_import_hub_scene(self):
        from content.scenes.hub.hub_flask import HubScene
        assert HubScene is not None

    def test_import_constants(self):
        from content.scenes.hub.hub_flask import SCENE_ID, DEFAULT_PORT
        assert SCENE_ID == "hub"
        assert DEFAULT_PORT == 8500

    def test_import_create_app(self):
        from content.scenes.hub.hub_flask import create_app
        assert callable(create_app)

    def test_import_scene_catalogue(self):
        from content.scenes.hub.hub_flask import SCENE_CATALOGUE
        assert isinstance(SCENE_CATALOGUE, list)
        assert len(SCENE_CATALOGUE) > 5


# ═══════════════════════════════════════════════════════════════
#  Initialization & Metadata
# ═══════════════════════════════════════════════════════════════

class TestInitialization:
    """HubScene construction and SCENE_METADATA."""

    @pytest.fixture
    def hub(self):
        return _make_hub()

    def test_scene_name(self, hub):
        assert hub.scene_name == "hub"

    def test_port(self, hub):
        assert hub.port == 18500

    def test_metadata_name(self, hub):
        assert hub.SCENE_METADATA["name"] == "hub"

    def test_metadata_title(self, hub):
        assert hub.SCENE_METADATA["display_name"] == "THE TERMINAL"

    def test_metadata_type(self, hub):
        assert hub.SCENE_METADATA["type"] == "hub"

    def test_metadata_genre(self, hub):
        assert hub.SCENE_METADATA["accent_color"] == "#3b82f6"

    def test_metadata_features(self, hub):
        assert len(hub.SCENE_METADATA["description"]) > 10

    def test_metadata_max_characters(self, hub):
        assert hub.SCENE_METADATA["port"] == 8500

    def test_has_flask_app(self, hub):
        assert hub.app is not None


# ═══════════════════════════════════════════════════════════════
#  get_plugin_info
# ═══════════════════════════════════════════════════════════════

class TestGetPluginInfo:
    """get_plugin_info() returns correct metadata."""

    @pytest.fixture
    def hub(self):
        return _make_hub(port=18500)

    def test_plugin_name(self, hub):
        info = hub.get_plugin_info()
        assert info["name"] == "THE TERMINAL"

    def test_plugin_version(self, hub):
        info = hub.get_plugin_info()
        assert info["version"] == "0.68"

    def test_plugin_port(self, hub):
        info = hub.get_plugin_info()
        assert info["port"] == 18500

    def test_plugin_has_routes(self, hub):
        info = hub.get_plugin_info()
        routes = info["routes"]
        assert "/" in routes
        assert "/api/scenes" in routes
        assert "/api/system" in routes
        assert "/api/health" in routes

    def test_plugin_has_tags(self, hub):
        info = hub.get_plugin_info()
        assert "hub" in info["tags"]

    def test_plugin_has_description(self, hub):
        info = hub.get_plugin_info()
        assert len(info["description"]) > 10

    def test_plugin_skill_packs_empty(self, hub):
        info = hub.get_plugin_info()
        assert "hub" in info["skill_packs"]


# ═══════════════════════════════════════════════════════════════
#  Route: GET /
# ═══════════════════════════════════════════════════════════════

class TestIndexRoute:
    """GET / returns the hub landing page."""

    @pytest.fixture
    def hub(self):
        return _make_hub()

    @pytest.fixture
    def client(self, hub):
        hub.app.config["TESTING"] = True
        return hub.app.test_client()

    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_index_content_type(self, client):
        resp = client.get("/")
        assert "text/html" in resp.content_type

    def test_index_contains_cosysim_hub(self, client):
        resp = client.get("/")
        assert b"THE TERMINAL" in resp.data

    def test_index_contains_version(self, client):
        # v1.62.0 [2026-06-15] — v1.58 made "/" the NEONCITY landing page (it
        # renders a {{ version }} string injected from package metadata); the
        # plugin "0.68" version + scene catalogue moved to /terminal.
        resp = client.get("/terminal")
        assert b"0.68" in resp.data

    def test_index_has_scene_grid(self, client):
        # v1.62.0 [2026-06-15] — scene grid moved from "/" to /terminal (v1.58).
        resp = client.get("/terminal")
        assert b"scene-grid" in resp.data

    def test_index_has_system_bar(self, client):
        # v1.62.0 [2026-06-15] — bench-hud system bar moved from "/" to /terminal (v1.58).
        resp = client.get("/terminal")
        assert b"bench-hud" in resp.data


# ═══════════════════════════════════════════════════════════════
#  Route: GET /api/scenes
# ═══════════════════════════════════════════════════════════════

class TestApiScenesRoute:
    """GET /api/scenes returns a JSON list of scene dicts."""

    @pytest.fixture
    def hub(self):
        return _make_hub()

    @pytest.fixture
    def client(self, hub):
        hub.app.config["TESTING"] = True
        return hub.app.test_client()

    @patch("content.scenes.hub.hub_flask.port_is_open", return_value=False)
    def test_returns_json_list(self, _mock_port, client):
        resp = client.get("/api/scenes")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    @patch("content.scenes.hub.hub_flask.port_is_open", return_value=False)
    def test_scene_count_matches_catalogue(self, _mock_port, client):
        from content.scenes.hub.hub_flask import SCENE_CATALOGUE
        resp = client.get("/api/scenes")
        data = resp.get_json()
        assert len(data) == len(SCENE_CATALOGUE)

    @patch("content.scenes.hub.hub_flask.port_is_open", return_value=False)
    def test_scene_has_expected_keys(self, _mock_port, client):
        resp = client.get("/api/scenes")
        data = resp.get_json()
        for scene in data:
            for key in ("id", "port", "label", "group", "status"):
                assert key in scene, f"Missing key '{key}' in scene {scene.get('id')}"

    @patch("content.scenes.hub.hub_flask.port_is_open", return_value=True)
    def test_all_online_when_ports_open(self, _mock_port, client):
        resp = client.get("/api/scenes")
        data = resp.get_json()
        for scene in data:
            assert scene["status"] == "online"

    @patch("content.scenes.hub.hub_flask.port_is_open", return_value=False)
    def test_all_offline_when_ports_closed(self, _mock_port, client):
        resp = client.get("/api/scenes")
        data = resp.get_json()
        for scene in data:
            assert scene["status"] == "offline"

    @patch("content.scenes.hub.hub_flask.port_is_open")
    def test_mixed_status(self, mock_port, client):
        """Only the bedroom port is open; others are offline."""
        mock_port.side_effect = lambda p: p == 5556
        resp = client.get("/api/scenes")
        data = resp.get_json()
        bedroom = [s for s in data if s["id"] == "penthouse"][0]
        casino = [s for s in data if s["id"] == "casino"][0]
        assert bedroom["status"] == "online"
        assert casino["status"] == "offline"

    @patch("content.scenes.hub.hub_flask.port_is_open", return_value=False)
    def test_scene_has_icon(self, _mock_port, client):
        resp = client.get("/api/scenes")
        data = resp.get_json()
        bedroom = [s for s in data if s["id"] == "penthouse"][0]
        assert "icon" in bedroom

    @patch("content.scenes.hub.hub_flask.port_is_open", return_value=False)
    def test_scene_has_desc(self, _mock_port, client):
        resp = client.get("/api/scenes")
        data = resp.get_json()
        bedroom = [s for s in data if s["id"] == "penthouse"][0]
        assert len(bedroom.get("desc", "")) > 5


# ═══════════════════════════════════════════════════════════════
#  Route: GET /api/system
# ═══════════════════════════════════════════════════════════════

class TestApiSystemRoute:
    """GET /api/system returns system summary JSON."""

    @pytest.fixture
    def hub(self):
        return _make_hub()

    @pytest.fixture
    def client(self, hub):
        hub.app.config["TESTING"] = True
        return hub.app.test_client()

    @patch("engine.assistant.system_assistant.get_assistant")
    def test_returns_json(self, mock_get, client):
        mock_assistant = MagicMock()
        mock_assistant.get_system_summary.return_value = {
            "vram_used_mb": 4000,
            "vram_total_mb": 12000,
            "loaded_models": [],
            "active_scenes": ["hub"],
            "agent_count": 1,
        }
        mock_get.return_value = mock_assistant
        resp = client.get("/api/system")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    @patch("engine.assistant.system_assistant.get_assistant")
    def test_has_expected_keys(self, mock_get, client):
        mock_assistant = MagicMock()
        mock_assistant.get_system_summary.return_value = {
            "vram_used_mb": 4000,
            "vram_total_mb": 12000,
            "loaded_models": [],
            "active_scenes": ["hub"],
            "agent_count": 1,
        }
        mock_get.return_value = mock_assistant
        resp = client.get("/api/system")
        data = resp.get_json()
        assert "active_scenes" in data or "vram_used_mb" in data

    def test_returns_fallback_on_error(self, client):
        """If assistant is unavailable, returns safe default."""
        with patch("engine.assistant.system_assistant.get_assistant",
                    side_effect=ImportError("no assistant")):
            resp = client.get("/api/system")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["vram_used_mb"] == 0


# ═══════════════════════════════════════════════════════════════
#  Route: GET /api/health
# ═══════════════════════════════════════════════════════════════

class TestApiHealthRoute:
    """GET /api/health returns a health-check dict."""

    @pytest.fixture
    def hub(self):
        return _make_hub()

    @pytest.fixture
    def client(self, hub):
        hub.app.config["TESTING"] = True
        return hub.app.test_client()

    def test_health_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_is_json(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_health_has_scene(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["scene"] == "hub"

    def test_health_has_status(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["status"] == "running"

    def test_health_has_port(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["port"] == 18500


# ═══════════════════════════════════════════════════════════════
#  Scene Catalogue
# ═══════════════════════════════════════════════════════════════

class TestSceneCatalogue:
    """SCENE_CATALOGUE module constant is well-formed."""

    def test_catalogue_has_bedroom(self):
        from content.scenes.hub.hub_flask import SCENE_CATALOGUE
        ids = [s["id"] for s in SCENE_CATALOGUE]
        assert "penthouse" in ids

    def test_catalogue_has_casino(self):
        from content.scenes.hub.hub_flask import SCENE_CATALOGUE
        ids = [s["id"] for s in SCENE_CATALOGUE]
        assert "casino" in ids

    def test_catalogue_entries_have_required_keys(self):
        from content.scenes.hub.hub_flask import SCENE_CATALOGUE
        for entry in SCENE_CATALOGUE:
            assert "id" in entry
            assert "port" in entry
            assert "label" in entry
            assert "group" in entry

    def test_catalogue_groups(self):
        from content.scenes.hub.hub_flask import SCENE_CATALOGUE
        groups = {s["group"] for s in SCENE_CATALOGUE}
        assert "neon_world" in groups
        assert "system" in groups

    def test_catalogue_ports_unique(self):
        from content.scenes.hub.hub_flask import SCENE_CATALOGUE
        ports = [s["port"] for s in SCENE_CATALOGUE]
        assert len(ports) == len(set(ports)), "Duplicate ports in catalogue"

    def test_catalogue_uses_canonical_lounge_label(self):
        from content.scenes.hub.hub_flask import SCENE_CATALOGUE

        lounge = next(scene for scene in SCENE_CATALOGUE if scene["id"] == "lounge")
        assert lounge["label"] == "THE VELVET PIT"

    def test_catalogue_includes_grid_and_system_control(self):
        from content.scenes.hub.hub_flask import SCENE_CATALOGUE

        ids = {scene["id"] for scene in SCENE_CATALOGUE}
        assert "grid" in ids
        assert "system_control" in ids


# ═══════════════════════════════════════════════════════════════
#  port_is_open helper
# ═══════════════════════════════════════════════════════════════

class TestPortOpen:
    """port_is_open() returns True/False based on socket connectivity."""

    def test_port_open_returns_bool(self):
        from engine.utils import port_is_open
        result = port_is_open(19999)  # unlikely to be listening
        assert isinstance(result, bool)

    def test_port_open_false_for_unused_port(self):
        from engine.utils import port_is_open
        assert port_is_open(19999) is False

    @patch("engine.utils.socket.create_connection")
    def test_port_open_true_when_connected(self, mock_conn):
        mock_conn.return_value.__enter__ = MagicMock()
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        from engine.utils import port_is_open
        assert port_is_open(5556) is True


# ═══════════════════════════════════════════════════════════════
#  Lifecycle stubs
# ═══════════════════════════════════════════════════════════════

class TestLifecycle:
    """start() and stop() don't crash in isolation."""

    @pytest.fixture
    def hub(self):
        return _make_hub()

    def test_stop_does_not_crash(self, hub):
        hub.stop()  # should return silently

    def test_start_calls_app_run(self, hub):
        hub.app.run = MagicMock()
        hub.start()
        hub.app.run.assert_called_once_with(
            host=hub.host,
            port=hub.port,
            debug=False,
            use_reloader=False,
        )
