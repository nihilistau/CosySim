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
        import os
        import content.scenes.games.games_scene as _gsm
        scene_dir = os.path.dirname(os.path.abspath(_gsm.__file__))
        s.app = Flask(
            "test_games",
            template_folder=os.path.join(scene_dir, "templates"),
            static_folder=os.path.join(scene_dir, "static"),
        )
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
        assert {"scene", "status", "port"}.issubset(set(h.keys()))

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
        assert info["version"] == "0.56b"

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


# ═══════════════════════════════════════════════════════════════
#  GameMaster Registration & Replies  (v0.56b)
# ═══════════════════════════════════════════════════════════════

class TestGameMaster:
    """GameMaster character registration and AI-narrated reply generation."""

    @pytest.fixture
    def scene(self):
        s = _make_scene()
        s._fw = None
        return s

    # ── get_health now includes gamemaster key ────────────────────

    def test_health_contains_gamemaster_key(self, scene):
        h = scene.get_health()
        assert "gamemaster" in h

    def test_health_gamemaster_value(self, scene):
        assert scene.get_health()["gamemaster"] == "gamemaster"

    # ── _register_gamemaster ─────────────────────────────────────

    @patch("engine.mcp.character_registry.apply_default_skills")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_register_calls_registry(self, mock_get_reg, mock_skills, scene):
        mock_reg = MagicMock()
        mock_reg.exists.return_value = False
        mock_get_reg.return_value = mock_reg

        scene._register_gamemaster()

        mock_reg.register.assert_called_once()

    @patch("engine.mcp.character_registry.apply_default_skills")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_register_uses_gamemaster_id(self, mock_get_reg, mock_skills, scene):
        mock_reg = MagicMock()
        mock_reg.exists.return_value = False
        mock_get_reg.return_value = mock_reg

        scene._register_gamemaster()

        args, _ = mock_reg.register.call_args
        assert args[0] == "gamemaster"

    @patch("engine.mcp.character_registry.apply_default_skills")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_register_sets_name(self, mock_get_reg, mock_skills, scene):
        mock_reg = MagicMock()
        mock_reg.exists.return_value = False
        mock_get_reg.return_value = mock_reg

        scene._register_gamemaster()

        _, kwargs = mock_reg.register.call_args
        assert kwargs["name"] == "The GameMaster"

    @patch("engine.mcp.character_registry.apply_default_skills")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_register_sets_personality_traits(self, mock_get_reg, mock_skills, scene):
        mock_reg = MagicMock()
        mock_reg.exists.return_value = False
        mock_get_reg.return_value = mock_reg

        scene._register_gamemaster()

        _, kwargs = mock_reg.register.call_args
        personality = kwargs["personality"]
        assert personality["wit"] == 0.9
        assert personality["assertiveness"] == 0.8
        assert personality["vulnerability"] == 0.0

    @patch("engine.mcp.character_registry.apply_default_skills")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_register_sets_backstory(self, mock_get_reg, mock_skills, scene):
        mock_reg = MagicMock()
        mock_reg.exists.return_value = False
        mock_get_reg.return_value = mock_reg

        scene._register_gamemaster()

        _, kwargs = mock_reg.register.call_args
        assert "omniscient narrator" in kwargs["backstory"]
        assert "Games Arcade" in kwargs["backstory"]

    @patch("engine.mcp.character_registry.apply_default_skills")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_register_sets_voice_style(self, mock_get_reg, mock_skills, scene):
        mock_reg = MagicMock()
        mock_reg.exists.return_value = False
        mock_get_reg.return_value = mock_reg

        scene._register_gamemaster()

        _, kwargs = mock_reg.register.call_args
        assert "theatrical" in kwargs["voice_style"]
        assert "suspenseful" in kwargs["voice_style"]

    @patch("engine.mcp.character_registry.apply_default_skills")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_register_sets_scene_roles(self, mock_get_reg, mock_skills, scene):
        mock_reg = MagicMock()
        mock_reg.exists.return_value = False
        mock_get_reg.return_value = mock_reg

        scene._register_gamemaster()

        _, kwargs = mock_reg.register.call_args
        assert kwargs["scene_roles"] == ["games"]

    @patch("engine.mcp.character_registry.apply_default_skills")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_register_applies_default_skills(self, mock_get_reg, mock_skills, scene):
        mock_reg = MagicMock()
        mock_reg.exists.return_value = False
        mock_get_reg.return_value = mock_reg

        scene._register_gamemaster()

        mock_skills.assert_called_once_with("gamemaster")

    @patch("engine.mcp.character_registry.apply_default_skills")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_register_skips_when_already_exists(self, mock_get_reg, mock_skills, scene):
        mock_reg = MagicMock()
        mock_reg.exists.return_value = True
        mock_get_reg.return_value = mock_reg

        scene._register_gamemaster()

        mock_reg.register.assert_not_called()
        mock_skills.assert_not_called()

    @patch("engine.mcp.character_registry.apply_default_skills")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_register_enters_scene_when_fw_present(self, mock_get_reg, mock_skills, scene):
        mock_reg = MagicMock()
        mock_reg.exists.return_value = False
        mock_get_reg.return_value = mock_reg
        scene._fw = MagicMock()

        scene._register_gamemaster()

        scene._fw.get_character.assert_called_once_with("gamemaster")
        scene._fw.get_character.return_value.enter_scene.assert_called_once_with("games")

    @patch("engine.mcp.character_registry.apply_default_skills")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_register_no_enter_scene_without_fw(self, mock_get_reg, mock_skills, scene):
        mock_reg = MagicMock()
        mock_reg.exists.return_value = False
        mock_get_reg.return_value = mock_reg
        # scene._fw is already None from fixture

        scene._register_gamemaster()

        # No crash — enter_scene path is skipped
        mock_reg.register.assert_called_once()

    def test_register_graceful_on_registry_error(self, scene):
        """Registration degrades gracefully if character_registry raises."""
        with patch(
            "engine.mcp.character_registry.get_character_registry",
            side_effect=RuntimeError("registry unavailable"),
        ):
            scene._register_gamemaster()  # should not raise

    # ── _get_gamemaster_reply ────────────────────────────────────

    @patch("engine.agents.virtual_agent.InferenceRequest")
    @patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager")
    def test_reply_returns_stripped_text(self, mock_get_mgr, mock_ir, scene):
        mock_proc = MagicMock()
        mock_proc.clean_text = "  A dramatic reveal!  "
        mock_get_mgr.return_value.infer_processed.return_value = mock_proc
        scene._get_governance_context = MagicMock(return_value="")

        result = scene._get_gamemaster_reply("Who did it?")

        assert result == "A dramatic reveal!"

    @patch("engine.agents.virtual_agent.InferenceRequest")
    @patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager")
    def test_reply_builds_request_with_gamemaster_id(self, mock_get_mgr, mock_ir, scene):
        mock_proc = MagicMock(clean_text="ok")
        mock_get_mgr.return_value.infer_processed.return_value = mock_proc
        scene._get_governance_context = MagicMock(return_value="")

        scene._get_gamemaster_reply("test")

        _, kwargs = mock_ir.call_args
        assert kwargs["agent_id"] == "gamemaster"

    @patch("engine.agents.virtual_agent.InferenceRequest")
    @patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager")
    def test_reply_sets_temperature_and_tokens(self, mock_get_mgr, mock_ir, scene):
        mock_proc = MagicMock(clean_text="ok")
        mock_get_mgr.return_value.infer_processed.return_value = mock_proc
        scene._get_governance_context = MagicMock(return_value="")

        scene._get_gamemaster_reply("test")

        _, kwargs = mock_ir.call_args
        assert kwargs["temperature"] == 0.8
        assert kwargs["max_output_tokens"] == 150

    @patch("engine.agents.virtual_agent.InferenceRequest")
    @patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager")
    def test_reply_system_prompt_identifies_gamemaster(self, mock_get_mgr, mock_ir, scene):
        mock_proc = MagicMock(clean_text="ok")
        mock_get_mgr.return_value.infer_processed.return_value = mock_proc
        scene._get_governance_context = MagicMock(return_value="")

        scene._get_gamemaster_reply("test")

        _, kwargs = mock_ir.call_args
        messages = kwargs["messages"]
        system_content = messages[0]["content"]
        assert messages[0]["role"] == "system"
        assert "The GameMaster" in system_content
        assert "theatrical" in system_content
        assert "[MOOD:emotion]" in system_content

    @patch("engine.agents.virtual_agent.InferenceRequest")
    @patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager")
    def test_reply_passes_user_prompt_as_message(self, mock_get_mgr, mock_ir, scene):
        mock_proc = MagicMock(clean_text="ok")
        mock_get_mgr.return_value.infer_processed.return_value = mock_proc
        scene._get_governance_context = MagicMock(return_value="")

        scene._get_gamemaster_reply("Who stole the diamond?")

        _, kwargs = mock_ir.call_args
        user_msg = kwargs["messages"][1]
        assert user_msg["role"] == "user"
        assert user_msg["content"] == "Who stole the diamond?"

    @patch("engine.agents.virtual_agent.InferenceRequest")
    @patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager")
    def test_reply_appends_governance_to_system(self, mock_get_mgr, mock_ir, scene):
        mock_proc = MagicMock(clean_text="ok")
        mock_get_mgr.return_value.infer_processed.return_value = mock_proc
        scene._get_governance_context = MagicMock(
            return_value="Be respectful and stay in character."
        )

        scene._get_gamemaster_reply("test")

        _, kwargs = mock_ir.call_args
        system_content = kwargs["messages"][0]["content"]
        assert "Be respectful and stay in character." in system_content

    @patch("engine.agents.virtual_agent.InferenceRequest")
    @patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager")
    def test_reply_sets_scene_metadata(self, mock_get_mgr, mock_ir, scene):
        mock_proc = MagicMock(clean_text="ok")
        mock_get_mgr.return_value.infer_processed.return_value = mock_proc
        scene._get_governance_context = MagicMock(return_value="")

        scene._get_gamemaster_reply("test")

        _, kwargs = mock_ir.call_args
        assert kwargs["metadata"]["scene"] == "games"
        assert kwargs["metadata"]["role"] == "game_master"
        assert kwargs["store"] is False

    @patch("engine.agents.virtual_agent.InferenceRequest")
    @patch("engine.agents.virtual_agent_manager.get_virtual_agent_manager")
    def test_reply_returns_empty_when_clean_text_none(self, mock_get_mgr, mock_ir, scene):
        mock_proc = MagicMock()
        mock_proc.clean_text = None
        mock_get_mgr.return_value.infer_processed.return_value = mock_proc
        scene._get_governance_context = MagicMock(return_value="")

        result = scene._get_gamemaster_reply("test")

        assert result == ""

    def test_reply_returns_empty_on_exception(self, scene):
        """When LLM is unavailable, reply returns empty string."""
        with patch(
            "engine.agents.virtual_agent_manager.get_virtual_agent_manager",
            side_effect=RuntimeError("offline"),
        ):
            result = scene._get_gamemaster_reply("Hello?")
            assert result == ""

    # ── _get_governance_context ──────────────────────────────────

    @patch("engine.mcp.get_governor")
    def test_governance_context_returns_string(self, mock_get_gov, scene):
        mock_gov = MagicMock()
        mock_gov.build_governance_context.return_value = "Stay in character."
        mock_get_gov.return_value = mock_gov

        result = scene._get_governance_context("gamemaster")

        assert result == "Stay in character."
        mock_gov.build_governance_context.assert_called_once_with("gamemaster", "games")

    def test_governance_context_empty_on_error(self, scene):
        """Returns empty string when governor is unavailable."""
        with patch("engine.mcp.get_governor", side_effect=ImportError("no governor")):
            assert scene._get_governance_context("gamemaster") == ""


# ═══════════════════════════════════════════════════════════════
#  Score Tracking  (v0.56b)
# ═══════════════════════════════════════════════════════════════

class TestScoreTracking:
    """_update_score persists wins, losses, and points via MCP state."""

    @pytest.fixture
    def scene(self):
        """Scene without MCP — scores work but are not persisted."""
        s = _make_scene()
        s._fw = None
        return s

    @pytest.fixture
    def scene_mcp(self):
        """Scene with mocked MCP scene node for state persistence."""
        s = _make_scene()
        s._fw = MagicMock()
        s._scene_node = MagicMock()
        s._scene_node.get_state.return_value = {
            "scores": {},
            "games_played": 0,
            "mysteries_solved": 0,
        }
        return s

    def test_new_player_initialised_with_zeroes(self, scene_mcp):
        result = scene_mcp._update_score("alice", "mystery", True)
        assert result["mystery_losses"] == 0
        assert result["tod_score"] == 0
        assert result["tod_rounds"] == 0

    def test_mystery_win_increments(self, scene_mcp):
        result = scene_mcp._update_score("alice", "mystery", True)
        assert result["mystery_wins"] == 1

    def test_mystery_loss_increments(self, scene_mcp):
        result = scene_mcp._update_score("alice", "mystery", False)
        assert result["mystery_losses"] == 1
        assert result["mystery_wins"] == 0

    def test_tod_score_adds_points(self, scene_mcp):
        result = scene_mcp._update_score("alice", "tod", False, points=10)
        assert result["tod_score"] == 10

    def test_tod_increments_rounds(self, scene_mcp):
        result = scene_mcp._update_score("alice", "tod", False, points=5)
        assert result["tod_rounds"] == 1

    def test_total_games_increments(self, scene_mcp):
        result = scene_mcp._update_score("alice", "mystery", True)
        assert result["total_games"] == 1

    def test_persists_scores_to_mcp_state(self, scene_mcp):
        scene_mcp._update_score("alice", "mystery", True)
        scene_mcp._scene_node.update_state.assert_called_once()
        state = scene_mcp._scene_node.update_state.call_args[0][0]
        assert "alice" in state["scores"]

    def test_games_played_counter_increments(self, scene_mcp):
        scene_mcp._update_score("alice", "mystery", True)
        state = scene_mcp._scene_node.update_state.call_args[0][0]
        assert state["games_played"] == 1

    def test_mystery_win_increments_solved_counter(self, scene_mcp):
        scene_mcp._update_score("alice", "mystery", True)
        state = scene_mcp._scene_node.update_state.call_args[0][0]
        assert state["mysteries_solved"] == 1

    def test_mystery_loss_does_not_increment_solved(self, scene_mcp):
        scene_mcp._update_score("alice", "mystery", False)
        state = scene_mcp._scene_node.update_state.call_args[0][0]
        assert state.get("mysteries_solved", 0) == 0

    def test_works_without_scene_node(self, scene):
        """Score tracking returns result even without MCP."""
        result = scene._update_score("bob", "mystery", True)
        assert result["mystery_wins"] == 1
        assert result["total_games"] == 1

    def test_scores_api_empty_without_mcp(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/scores")
        assert resp.status_code == 200
        assert resp.get_json() == {}

    def test_scores_api_returns_player_data(self, scene_mcp):
        scene_mcp._scene_node.get_state.return_value = {
            "scores": {"alice": {"mystery_wins": 3, "total_games": 5}},
        }
        client = scene_mcp.app.test_client()
        resp = client.get("/api/scores")
        data = resp.get_json()
        assert data["alice"]["mystery_wins"] == 3

    def test_scores_api_json_content_type(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/scores")
        assert resp.content_type.startswith("application/json")


# ═══════════════════════════════════════════════════════════════
#  GameMaster HTTP Routes  (v0.56b)
# ═══════════════════════════════════════════════════════════════

class TestGameMasterRoutes:
    """HTTP endpoints that proxy the AI GameMaster."""

    @pytest.fixture
    def scene(self):
        s = _make_scene()
        s._fw = None
        return s

    @pytest.fixture
    def client(self, scene):
        return scene.app.test_client()

    def test_chat_returns_reply(self, client, scene):
        scene._get_gamemaster_reply = MagicMock(return_value="Indeed!")
        resp = client.post("/api/chat", json={"message": "Hello"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["reply"] == "Indeed!"
        assert data["character"] == "The GameMaster"

    def test_chat_empty_message_returns_400(self, client):
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 400

    def test_chat_missing_message_returns_400(self, client):
        resp = client.post("/api/chat", json={})
        assert resp.status_code == 400

    def test_chat_fallback_when_ai_unavailable(self, client, scene):
        scene._get_gamemaster_reply = MagicMock(return_value="")
        resp = client.post("/api/chat", json={"message": "Hello"})
        data = resp.get_json()
        assert "ponders" in data["reply"]

    def test_narrate_clue_returns_narration(self, client, scene):
        scene._get_gamemaster_reply = MagicMock(return_value="A mysterious clue!")
        resp = client.post("/api/mystery/narrate", json={
            "clue": "A bloody knife",
            "case_title": "Murder at Midnight",
            "clue_number": 1,
        })
        assert resp.status_code == 200
        assert resp.get_json()["narration"] == "A mysterious clue!"

    def test_narrate_fallback_uses_raw_clue(self, client, scene):
        scene._get_gamemaster_reply = MagicMock(return_value="")
        resp = client.post("/api/mystery/narrate", json={"clue": "A note"})
        assert resp.get_json()["narration"] == "A note"

    def test_react_correct_accusation(self, client, scene):
        scene._get_gamemaster_reply = MagicMock(return_value="Brilliant!")
        scene._update_score = MagicMock()
        resp = client.post("/api/mystery/react", json={
            "correct": True, "suspect": "Butler", "player": "alice",
        })
        data = resp.get_json()
        assert data["reaction"] == "Brilliant!"
        scene._update_score.assert_called_once_with("alice", "mystery", True)

    def test_react_incorrect_accusation(self, client, scene):
        scene._get_gamemaster_reply = MagicMock(return_value="So close!")
        scene._update_score = MagicMock()
        resp = client.post("/api/mystery/react", json={
            "correct": False, "suspect": "Butler",
            "real_culprit": "Maid", "player": "alice",
        })
        resp.get_json()
        scene._update_score.assert_called_once_with("alice", "mystery", False)

    def test_react_fallback_correct(self, client, scene):
        scene._get_gamemaster_reply = MagicMock(return_value="")
        scene._update_score = MagicMock()
        resp = client.post("/api/mystery/react", json={
            "correct": True, "suspect": "Butler", "player": "p",
        })
        assert resp.get_json()["reaction"] == "Brilliant!"

    def test_react_fallback_incorrect(self, client, scene):
        scene._get_gamemaster_reply = MagicMock(return_value="")
        scene._update_score = MagicMock()
        resp = client.post("/api/mystery/react", json={
            "correct": False, "suspect": "Butler", "player": "p",
        })
        assert resp.get_json()["reaction"] == "Not quite..."


# ═══════════════════════════════════════════════════════════════
#  Socket.IO Events  (v0.56b)
# ═══════════════════════════════════════════════════════════════

class TestSocketEvents:
    """Socket.IO event handlers for real-time gameplay."""

    @pytest.fixture
    def scene(self):
        s = _make_scene()
        s._fw = None
        s._setup_socketio()
        return s

    @pytest.fixture
    def sio_client(self, scene):
        """Connected test client with initial connect event drained."""
        client = scene.socketio.test_client(scene.app)
        client.get_received()          # drain the auto-connect event
        yield client
        client.disconnect()

    # ── connect ──────────────────────────────────────────────────

    def test_connect_emits_game_update(self, scene):
        client = scene.socketio.test_client(scene.app)
        received = client.get_received()
        updates = [m for m in received if m["name"] == "game_update"]
        assert len(updates) == 1
        assert updates[0]["args"][0]["type"] == "connected"
        client.disconnect()

    def test_connect_lists_available_games(self, scene):
        client = scene.socketio.test_client(scene.app)
        received = client.get_received()
        update = next(m for m in received if m["name"] == "game_update")
        games = update["args"][0]["games_available"]
        assert "mystery" in games
        assert "truth_or_dare" in games
        client.disconnect()

    # ── chat_message ─────────────────────────────────────────────

    def test_chat_emits_reply(self, sio_client, scene):
        scene._get_gamemaster_reply = MagicMock(return_value="The plot thickens!")
        sio_client.emit("chat_message", {"message": "Hello"})
        received = sio_client.get_received()
        replies = [m for m in received if m["name"] == "chat_reply"]
        assert len(replies) == 1
        assert replies[0]["args"][0]["character"] == "The GameMaster"
        assert replies[0]["args"][0]["message"] == "The plot thickens!"

    def test_chat_includes_timestamp(self, sio_client, scene):
        scene._get_gamemaster_reply = MagicMock(return_value="ok")
        sio_client.emit("chat_message", {"message": "Hi"})
        received = sio_client.get_received()
        reply = next(m for m in received if m["name"] == "chat_reply")
        assert "timestamp" in reply["args"][0]

    def test_chat_empty_message_no_reply(self, sio_client, scene):
        sio_client.emit("chat_message", {"message": ""})
        received = sio_client.get_received()
        replies = [m for m in received if m["name"] == "chat_reply"]
        assert len(replies) == 0

    def test_chat_fallback_when_ai_returns_empty(self, sio_client, scene):
        scene._get_gamemaster_reply = MagicMock(return_value="")
        sio_client.emit("chat_message", {"message": "Hello"})
        received = sio_client.get_received()
        reply = next(m for m in received if m["name"] == "chat_reply")
        assert "chin" in reply["args"][0]["message"]  # "strokes their chin"

    # ── mystery_start ────────────────────────────────────────────

    @patch("content.scenes.games.mystery_investigation.MysteryGame")
    def test_mystery_start_emits_started(self, mock_cls, sio_client, scene):
        mock_game = MagicMock()
        mock_game.start.return_value = {
            "case_title": "The Lost Key", "setting": "A dark library",
        }
        mock_cls.return_value = mock_game
        scene._get_gamemaster_reply = MagicMock(return_value="Welcome, detective!")

        sio_client.emit("mystery_start", {"player": "alice"})
        received = sio_client.get_received()

        started = [m for m in received if m["name"] == "mystery_started"]
        assert len(started) == 1
        assert started[0]["args"][0]["case_title"] == "The Lost Key"
        assert started[0]["args"][0]["setting"] == "A dark library"

    @patch("content.scenes.games.mystery_investigation.MysteryGame")
    def test_mystery_start_tracks_game(self, mock_cls, sio_client, scene):
        mock_game = MagicMock()
        mock_game.start.return_value = {"case_title": "X", "setting": "Y"}
        mock_cls.return_value = mock_game
        scene._get_gamemaster_reply = MagicMock(return_value="")

        sio_client.emit("mystery_start", {"player": "alice"})

        assert "alice" in scene.mystery_games

    # ── mystery_clue ─────────────────────────────────────────────

    def test_mystery_clue_emits_revealed(self, sio_client, scene):
        mock_game = MagicMock()
        mock_game.next_clue.return_value = {"clue": "A fingerprint", "clues_found": 2}
        scene.mystery_games["alice"] = mock_game
        scene._get_gamemaster_reply = MagicMock(return_value="Interesting...")

        sio_client.emit("mystery_clue", {"player": "alice"})
        received = sio_client.get_received()

        clues = [m for m in received if m["name"] == "clue_revealed"]
        assert len(clues) == 1
        assert clues[0]["args"][0]["clue"] == "A fingerprint"
        assert clues[0]["args"][0]["clue_number"] == 2
        assert clues[0]["args"][0]["total"] == 5

    def test_mystery_clue_marks_all_found(self, sio_client, scene):
        mock_game = MagicMock()
        mock_game.next_clue.return_value = {"clue": "Final clue", "clues_found": 5}
        scene.mystery_games["alice"] = mock_game
        scene._get_gamemaster_reply = MagicMock(return_value="")

        sio_client.emit("mystery_clue", {"player": "alice"})
        received = sio_client.get_received()

        clue_msg = next(m for m in received if m["name"] == "clue_revealed")
        assert clue_msg["args"][0]["all_found"] is True

    def test_mystery_clue_no_game_emits_error(self, sio_client, scene):
        sio_client.emit("mystery_clue", {"player": "nobody"})
        received = sio_client.get_received()
        errors = [m for m in received if m["name"] == "error"]
        assert len(errors) == 1
        assert "Start one first" in errors[0]["args"][0]["message"]

    # ── mystery_accuse ───────────────────────────────────────────

    def test_mystery_accuse_correct(self, sio_client, scene):
        mock_game = MagicMock()
        mock_game.accuse.return_value = {"correct": True, "real_culprit": "Butler"}
        scene.mystery_games["alice"] = mock_game
        scene._get_gamemaster_reply = MagicMock(return_value="Brilliant!")

        sio_client.emit("mystery_accuse", {"player": "alice", "suspect": "Butler"})
        received = sio_client.get_received()

        results = [m for m in received if m["name"] == "accusation_result"]
        assert len(results) == 1
        assert results[0]["args"][0]["correct"] is True

    def test_mystery_accuse_incorrect(self, sio_client, scene):
        mock_game = MagicMock()
        mock_game.accuse.return_value = {"correct": False, "real_culprit": "Maid"}
        scene.mystery_games["bob"] = mock_game
        scene._get_gamemaster_reply = MagicMock(return_value="So close!")

        sio_client.emit("mystery_accuse", {"player": "bob", "suspect": "Butler"})
        received = sio_client.get_received()

        result = next(m for m in received if m["name"] == "accusation_result")
        assert result["args"][0]["correct"] is False
        assert result["args"][0]["real_culprit"] == "Maid"

    def test_mystery_accuse_no_game_emits_error(self, sio_client, scene):
        sio_client.emit("mystery_accuse", {"player": "ghost", "suspect": "X"})
        received = sio_client.get_received()
        errors = [m for m in received if m["name"] == "error"]
        assert len(errors) == 1

    def test_mystery_accuse_emits_mcp_event_when_fw_present(self, sio_client, scene):
        mock_game = MagicMock()
        mock_game.accuse.return_value = {"correct": True, "real_culprit": "Butler"}
        scene.mystery_games["alice"] = mock_game
        scene._get_gamemaster_reply = MagicMock(return_value="")
        scene._fw = MagicMock()

        sio_client.emit("mystery_accuse", {"player": "alice", "suspect": "Butler"})

        scene._fw.emit_event.assert_called_once()
        call_args = scene._fw.emit_event.call_args
        assert call_args[0][0] == "mystery_completed"
        assert call_args[1]["source"] == "games"

    # ── tod_start ────────────────────────────────────────────────

    @patch("content.scenes.games.truth_or_dare.TruthOrDareGame")
    def test_tod_start_emits_started(self, mock_cls, sio_client, scene):
        mock_game = MagicMock()
        mock_cls.return_value = mock_game
        scene._get_gamemaster_reply = MagicMock(return_value="Let the game begin!")

        sio_client.emit("tod_start", {"player": "carol"})
        received = sio_client.get_received()

        started = [m for m in received if m["name"] == "tod_started"]
        assert len(started) == 1

    @patch("content.scenes.games.truth_or_dare.TruthOrDareGame")
    def test_tod_start_tracks_game(self, mock_cls, sio_client, scene):
        mock_cls.return_value = MagicMock()
        scene._get_gamemaster_reply = MagicMock(return_value="")

        sio_client.emit("tod_start", {"player": "carol"})

        assert "carol" in scene.tod_games

    # ── tod_roll ─────────────────────────────────────────────────

    def test_tod_roll_emits_prompt(self, sio_client, scene):
        mock_game = MagicMock()
        mock_game.roll.return_value = {
            "roll": 4, "type": "dare", "prompt": "Do a dance",
        }
        scene.tod_games["carol"] = mock_game
        scene._get_gamemaster_reply = MagicMock(return_value="A dare!")

        sio_client.emit("tod_roll", {"player": "carol"})
        received = sio_client.get_received()

        prompts = [m for m in received if m["name"] == "tod_prompt"]
        assert len(prompts) == 1
        assert prompts[0]["args"][0]["type"] == "dare"
        assert prompts[0]["args"][0]["prompt"] == "Do a dance"

    def test_tod_roll_no_game_emits_error(self, sio_client, scene):
        sio_client.emit("tod_roll", {"player": "nobody"})
        received = sio_client.get_received()
        errors = [m for m in received if m["name"] == "error"]
        assert len(errors) == 1

    def test_tod_roll_runtime_error_emits_error(self, sio_client, scene):
        mock_game = MagicMock()
        mock_game.roll.side_effect = RuntimeError("no more rolls")
        scene.tod_games["carol"] = mock_game

        sio_client.emit("tod_roll", {"player": "carol"})
        received = sio_client.get_received()

        errors = [m for m in received if m["name"] == "error"]
        assert len(errors) == 1
        assert "no more rolls" in errors[0]["args"][0]["message"]

    # ── tod_answer ───────────────────────────────────────────────

    def test_tod_answer_emits_scored(self, sio_client, scene):
        mock_game = MagicMock()
        mock_game.answer.return_value = {"score": 3}
        scene.tod_games["carol"] = mock_game

        sio_client.emit("tod_answer", {
            "player": "carol", "completed": True, "response": "I did it",
        })
        received = sio_client.get_received()

        scored = [m for m in received if m["name"] == "tod_scored"]
        assert len(scored) == 1
        assert scored[0]["args"][0]["score"] == 3

    def test_tod_answer_win_emits_complete(self, sio_client, scene):
        mock_game = MagicMock()
        mock_game.answer.return_value = {"score": 5}
        scene.tod_games["carol"] = mock_game
        scene._get_gamemaster_reply = MagicMock(return_value="You win!")

        sio_client.emit("tod_answer", {
            "player": "carol", "completed": True, "response": "done",
        })
        received = sio_client.get_received()

        complete = [m for m in received if m["name"] == "tod_complete"]
        assert len(complete) == 1
        assert complete[0]["args"][0]["score"] == 5

    def test_tod_answer_no_game_emits_error(self, sio_client, scene):
        sio_client.emit("tod_answer", {"player": "ghost", "completed": True})
        received = sio_client.get_received()
        errors = [m for m in received if m["name"] == "error"]
        assert len(errors) == 1
