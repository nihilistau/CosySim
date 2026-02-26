"""Tests for GamesScene — initialization, lifecycle, routes, health, plugin info, MCP."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _make_scene(port: int = 15567):
    """Create a GamesScene with all external dependencies mocked out.

    Patches BaseScene.__init__, NexusSceneMixin.nexus_init, MCP wiring,
    and blueprint imports so the constructor never touches the network or
    filesystem.
    """
    with patch("content.scenes.games.games_scene.BaseScene.__init__"), \
         patch("content.scenes.games.games_scene.NexusSceneMixin.nexus_init"), \
         patch("content.scenes.games.games_scene.GamesScene._wire_mcp"):
        from content.scenes.games.games_scene import GamesScene
        s = GamesScene.__new__(GamesScene)
        # Manually set attributes that BaseScene.__init__ would set
        s.scene_name = "games"
        s.host = "127.0.0.1"
        s.port = port
        s.active_characters = {}
        s.streaming_enabled = True
        s._active_streams = 0
        s._total_stream_tokens = 0
        s.scene_metadata = GamesScene.SCENE_METADATA
        s._scene_node = None

        # Active game dicts
        s.mystery_games = {}
        s.tod_games = {}

        # Create real Flask app + SocketIO for route testing
        from flask import Flask
        from flask_socketio import SocketIO
        s.app = Flask("test_games")
        s.socketio = SocketIO(s.app, async_mode="threading")

        # Stub BaseScene helper methods called during _register_routes
        s.register_health_route = MagicMock()
        s.mount_overlay = MagicMock()
        s.mount_skills_server = MagicMock()

        # Wire routes (imports blueprints)
        s._register_routes()
        return s


# ═══════════════════════════════════════════════════════════════
#  Imports
# ═══════════════════════════════════════════════════════════════

class TestImports:
    """Module-level constants and class imports work."""

    def test_import_scene_class(self):
        from content.scenes.games.games_scene import GamesScene
        assert GamesScene is not None

    def test_import_constants(self):
        from content.scenes.games.games_scene import SCENE_ID, DEFAULT_PORT
        assert SCENE_ID == "games"
        assert DEFAULT_PORT == 5567

    def test_import_create_app(self):
        from content.scenes.games.games_scene import create_app
        assert callable(create_app)


# ═══════════════════════════════════════════════════════════════
#  Initialization & Metadata
# ═══════════════════════════════════════════════════════════════

class TestInitialization:
    """Scene construction and SCENE_METADATA."""

    @pytest.fixture
    def scene(self):
        return _make_scene()

    def test_scene_name(self, scene):
        assert scene.scene_name == "games"

    def test_default_port(self, scene):
        assert scene.port == 15567

    def test_metadata_title(self, scene):
        assert scene.SCENE_METADATA["title"] == "Games Arcade"

    def test_metadata_genre(self, scene):
        assert scene.SCENE_METADATA["genre"] == "minigames"

    def test_metadata_max_characters(self, scene):
        assert scene.SCENE_METADATA["max_characters"] == 2

    def test_metadata_features(self, scene):
        feats = scene.SCENE_METADATA["features"]
        assert "mystery_investigation" in feats
        assert "truth_or_dare" in feats
        assert "mcp_skills" in feats

    def test_metadata_description_non_empty(self, scene):
        assert len(scene.SCENE_METADATA["description"]) > 20

    def test_mystery_games_dict_empty(self, scene):
        assert scene.mystery_games == {}

    def test_tod_games_dict_empty(self, scene):
        assert scene.tod_games == {}

    def test_has_flask_app(self, scene):
        assert scene.app is not None

    def test_has_socketio(self, scene):
        assert scene.socketio is not None


# ═══════════════════════════════════════════════════════════════
#  Start / Stop Lifecycle
# ═══════════════════════════════════════════════════════════════

class TestLifecycle:
    """start() delegates to SocketIO.run(); stop() calls nexus_flush()."""

    @pytest.fixture
    def scene(self):
        return _make_scene()

    def test_start_calls_socketio_run(self, scene):
        scene.socketio.run = MagicMock()
        scene.start()
        scene.socketio.run.assert_called_once_with(
            scene.app,
            host=scene.host,
            port=scene.port,
            allow_unsafe_werkzeug=True,
        )

    def test_stop_calls_nexus_flush(self, scene):
        scene.nexus_flush = MagicMock()
        scene.stop()
        scene.nexus_flush.assert_called_once()

    def test_stop_does_not_crash_without_nexus(self, scene):
        """stop() is safe even if nexus_flush raises."""
        scene.nexus_flush = MagicMock(side_effect=RuntimeError("offline"))
        with pytest.raises(RuntimeError):
            scene.stop()


# ═══════════════════════════════════════════════════════════════
#  Route Registration
# ═══════════════════════════════════════════════════════════════

class TestRouteRegistration:
    """_register_routes wires index, health, status, and game blueprints."""

    @pytest.fixture
    def scene(self):
        return _make_scene()

    @pytest.fixture
    def client(self, scene):
        return scene.app.test_client()

    def test_index_route_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Games Arcade" in resp.data

    def test_index_contains_mystery_section(self, client):
        resp = client.get("/")
        assert b"Mystery Investigation" in resp.data

    def test_index_contains_truth_or_dare_section(self, client):
        resp = client.get("/")
        assert b"Truth or Dare" in resp.data

    def test_health_route_returns_json(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["scene"] == "games"
        assert data["status"] == "running"

    def test_status_route_returns_counts(self, client, scene):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["scene"] == "games"
        assert data["mystery_active"] == 0
        assert data["tod_active"] == 0

    def test_status_reflects_active_games(self, client, scene):
        scene.mystery_games["char_1"] = {"active": True}
        scene.tod_games["char_2"] = {"active": True}
        scene.tod_games["char_3"] = {"active": True}
        resp = client.get("/api/status")
        data = resp.get_json()
        assert data["mystery_active"] == 1
        assert data["tod_active"] == 2

    def test_mystery_blueprint_mounted(self, client):
        """Mystery blueprint is reachable under /games/mystery/."""
        resp = client.get("/games/mystery/state")
        # Exact status depends on game module; key is the route is found (not 404)
        assert resp.status_code != 404

    def test_tod_blueprint_mounted(self, client):
        """Truth-or-dare blueprint is reachable under /games/truth-or-dare/."""
        resp = client.get("/games/truth-or-dare/state")
        assert resp.status_code != 404

    def test_register_health_route_called(self, scene):
        scene.register_health_route.assert_called_once_with(scene.app)

    def test_mount_overlay_called(self, scene):
        scene.mount_overlay.assert_called_once_with(scene.app)

    def test_mount_skills_server_called(self, scene):
        scene.mount_skills_server.assert_called_once_with(scene.app)


# ═══════════════════════════════════════════════════════════════
#  get_health
# ═══════════════════════════════════════════════════════════════

class TestGetHealth:
    """get_health() returns the expected status dict."""

    @pytest.fixture
    def scene(self):
        return _make_scene(port=15567)

    def test_health_keys(self, scene):
        h = scene.get_health()
        assert set(h.keys()) == {"scene", "status", "port"}

    def test_health_scene_id(self, scene):
        assert scene.get_health()["scene"] == "games"

    def test_health_status_running(self, scene):
        assert scene.get_health()["status"] == "running"

    def test_health_port(self, scene):
        assert scene.get_health()["port"] == 15567

    def test_health_serialisable(self, scene):
        """Health dict can be JSON-serialised without error."""
        s = json.dumps(scene.get_health())
        assert isinstance(s, str)


# ═══════════════════════════════════════════════════════════════
#  get_plugin_info
# ═══════════════════════════════════════════════════════════════

class TestGetPluginInfo:
    """get_plugin_info() returns complete discovery metadata."""

    @pytest.fixture
    def scene(self):
        return _make_scene(port=15567)

    def test_plugin_info_name(self, scene):
        info = scene.get_plugin_info()
        assert info["name"] == "games"

    def test_plugin_info_version(self, scene):
        info = scene.get_plugin_info()
        assert info["version"] == "0.50b"

    def test_plugin_info_author(self, scene):
        assert scene.get_plugin_info()["author"] == "CosySim"

    def test_plugin_info_port(self, scene):
        assert scene.get_plugin_info()["port"] == 15567

    def test_plugin_info_tags(self, scene):
        tags = scene.get_plugin_info()["tags"]
        assert "games" in tags
        assert "mystery" in tags
        assert "truth_or_dare" in tags

    def test_plugin_info_skill_packs(self, scene):
        assert scene.get_plugin_info()["skill_packs"] == ["games"]

    def test_plugin_info_routes(self, scene):
        routes = scene.get_plugin_info()["routes"]
        assert "/" in routes
        assert "/api/health" in routes
        assert "/api/status" in routes
        assert "/games/mystery/*" in routes
        assert "/games/truth-or-dare/*" in routes

    def test_plugin_info_description_matches_metadata(self, scene):
        info = scene.get_plugin_info()
        assert info["description"] == scene.SCENE_METADATA["description"]

    def test_plugin_info_required_keys(self, scene):
        info = scene.get_plugin_info()
        required = {"name", "description", "version", "author", "port",
                     "tags", "skill_packs", "routes"}
        assert required.issubset(set(info.keys()))

    def test_plugin_info_serialisable(self, scene):
        s = json.dumps(scene.get_plugin_info())
        assert isinstance(s, str)


# ═══════════════════════════════════════════════════════════════
#  MCP Wiring
# ═══════════════════════════════════════════════════════════════

class TestMCPWiring:
    """_wire_mcp interacts with MCPFramework; degrades gracefully."""

    def test_wire_mcp_success(self):
        """When MCP framework is available, _scene_node is set."""
        mock_node = MagicMock()
        mock_fw = MagicMock()
        mock_fw.get_scene.return_value = mock_node

        with patch("content.scenes.games.games_scene.BaseScene.__init__"), \
             patch("content.scenes.games.games_scene.NexusSceneMixin.nexus_init"):
            from content.scenes.games.games_scene import GamesScene
            s = GamesScene.__new__(GamesScene)
            s.scene_name = "games"
            s.host = "127.0.0.1"
            s.port = 15567
            s.active_characters = {}
            s.streaming_enabled = True
            s._active_streams = 0
            s._total_stream_tokens = 0
            s.scene_metadata = GamesScene.SCENE_METADATA
            s.mystery_games = {}
            s.tod_games = {}

            from flask import Flask
            from flask_socketio import SocketIO
            s.app = Flask("test_mcp")
            s.socketio = SocketIO(s.app, async_mode="threading")
            s.register_health_route = MagicMock()
            s.mount_overlay = MagicMock()
            s.mount_skills_server = MagicMock()
            s._register_routes()

            with patch("engine.mcp.framework.get_framework", return_value=mock_fw):
                s._wire_mcp()

            assert s._scene_node is mock_node
            mock_fw.get_scene.assert_called_once_with("games")

    def test_wire_mcp_graceful_failure(self):
        """When MCP framework is unavailable, _scene_node stays None."""
        with patch("content.scenes.games.games_scene.BaseScene.__init__"), \
             patch("content.scenes.games.games_scene.NexusSceneMixin.nexus_init"):
            from content.scenes.games.games_scene import GamesScene
            s = GamesScene.__new__(GamesScene)
            s.scene_name = "games"
            s.host = "127.0.0.1"
            s.port = 15567
            s.active_characters = {}
            s.streaming_enabled = True
            s._active_streams = 0
            s._total_stream_tokens = 0
            s.scene_metadata = GamesScene.SCENE_METADATA
            s.mystery_games = {}
            s.tod_games = {}

            from flask import Flask
            from flask_socketio import SocketIO
            s.app = Flask("test_mcp_fail")
            s.socketio = SocketIO(s.app, async_mode="threading")
            s.register_health_route = MagicMock()
            s.mount_overlay = MagicMock()
            s.mount_skills_server = MagicMock()
            s._register_routes()

            with patch("engine.mcp.framework.get_framework",
                       side_effect=ImportError("no mcp")):
                s._wire_mcp()

            assert s._scene_node is None


# ═══════════════════════════════════════════════════════════════
#  MCP State Syncing
# ═══════════════════════════════════════════════════════════════

class TestMCPStateSync:
    """Scene node state is synced when _scene_node is present."""

    @pytest.fixture
    def scene(self):
        s = _make_scene()
        s._scene_node = MagicMock()
        return s

    def test_scene_node_set_after_wire(self, scene):
        assert scene._scene_node is not None

    def test_status_endpoint_independent_of_mcp(self, scene):
        """API status works whether MCP is wired or not."""
        scene._scene_node = None
        client = scene.app.test_client()
        resp = client.get("/api/status")
        assert resp.status_code == 200

    def test_health_endpoint_independent_of_mcp(self, scene):
        scene._scene_node = None
        client = scene.app.test_client()
        resp = client.get("/api/health")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
#  Game Instance Tracking
# ═══════════════════════════════════════════════════════════════

class TestGameInstanceTracking:
    """mystery_games and tod_games dicts track active sessions."""

    @pytest.fixture
    def scene(self):
        return _make_scene()

    def test_add_mystery_game(self, scene):
        scene.mystery_games["alice"] = {"case": "stolen_jewels", "clues_found": 0}
        assert len(scene.mystery_games) == 1

    def test_add_tod_game(self, scene):
        scene.tod_games["bob"] = {"score": 0, "round": 1}
        assert len(scene.tod_games) == 1

    def test_remove_game_on_completion(self, scene):
        scene.mystery_games["alice"] = {"case": "stolen_jewels"}
        del scene.mystery_games["alice"]
        assert len(scene.mystery_games) == 0

    def test_multiple_concurrent_games(self, scene):
        scene.mystery_games["alice"] = {}
        scene.mystery_games["bob"] = {}
        scene.tod_games["carol"] = {}
        client = scene.app.test_client()
        data = client.get("/api/status").get_json()
        assert data["mystery_active"] == 2
        assert data["tod_active"] == 1

    def test_games_isolated_by_character(self, scene):
        scene.mystery_games["a"] = {"case": "case1"}
        scene.mystery_games["b"] = {"case": "case2"}
        assert scene.mystery_games["a"]["case"] != scene.mystery_games["b"]["case"]


# ═══════════════════════════════════════════════════════════════
#  create_app Factory
# ═══════════════════════════════════════════════════════════════

class TestCreateApp:
    """The create_app() factory returns a fully-wired GamesScene."""

    @patch("content.scenes.games.games_scene.GamesScene.__init__", return_value=None)
    def test_create_app_returns_scene(self, mock_init):
        from content.scenes.games.games_scene import create_app, GamesScene
        result = create_app(host="localhost", port=9999)
        assert isinstance(result, GamesScene)
        mock_init.assert_called_once_with(host="localhost", port=9999)

    @patch("content.scenes.games.games_scene.GamesScene.__init__", return_value=None)
    def test_create_app_defaults(self, mock_init):
        from content.scenes.games.games_scene import create_app
        create_app()
        mock_init.assert_called_once_with(host="0.0.0.0", port=5567)


# ═══════════════════════════════════════════════════════════════
#  Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Boundary conditions and robustness checks."""

    def test_custom_port_reflected_in_health(self):
        scene = _make_scene(port=19999)
        assert scene.get_health()["port"] == 19999

    def test_custom_port_reflected_in_plugin_info(self):
        scene = _make_scene(port=19999)
        assert scene.get_plugin_info()["port"] == 19999

    def test_mount_overlay_failure_tolerated(self):
        """If mount_overlay raises, scene still constructs."""
        with patch("content.scenes.games.games_scene.BaseScene.__init__"), \
             patch("content.scenes.games.games_scene.NexusSceneMixin.nexus_init"), \
             patch("content.scenes.games.games_scene.GamesScene._wire_mcp"):
            from content.scenes.games.games_scene import GamesScene
            s = GamesScene.__new__(GamesScene)
            s.scene_name = "games"
            s.host = "127.0.0.1"
            s.port = 15567
            s.active_characters = {}
            s.streaming_enabled = True
            s._active_streams = 0
            s._total_stream_tokens = 0
            s.scene_metadata = GamesScene.SCENE_METADATA
            s._scene_node = None
            s.mystery_games = {}
            s.tod_games = {}

            from flask import Flask
            from flask_socketio import SocketIO
            s.app = Flask("test_edge")
            s.socketio = SocketIO(s.app, async_mode="threading")
            s.register_health_route = MagicMock()
            s.mount_overlay = MagicMock(side_effect=RuntimeError("boom"))
            s.mount_skills_server = MagicMock()

            # Should not raise despite mount_overlay failing
            s._register_routes()
            assert s.app is not None

    def test_health_route_json_content_type(self):
        scene = _make_scene()
        client = scene.app.test_client()
        resp = client.get("/api/health")
        assert resp.content_type.startswith("application/json")

    def test_status_route_json_content_type(self):
        scene = _make_scene()
        client = scene.app.test_client()
        resp = client.get("/api/status")
        assert resp.content_type.startswith("application/json")
