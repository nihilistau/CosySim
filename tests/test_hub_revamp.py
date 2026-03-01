"""Tests for THE TERMINAL hub scene revamp — v0.68 Dark Renaissance.

Covers: metadata, skills registration, skill logic, static asset existence.
All external services (WorldState, Economy, EventBus) are mocked.
"""
from __future__ import annotations

import importlib
import json
import socket
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Paths ────────────────────────────────────────────────────────────

_HUB_DIR = Path(__file__).parent.parent / "content" / "scenes" / "hub"


# ══════════════════════════════════════════════════════════════════════
# 1. Metadata
# ══════════════════════════════════════════════════════════════════════


class TestHubSceneMetadata:
    """Verify SCENE_METADATA matches the v0.68 spec."""

    def _get_meta(self) -> dict[str, Any]:
        from content.scenes.hub.hub_flask import HubScene
        return HubScene.SCENE_METADATA

    def test_hub_scene_metadata_name(self) -> None:
        """SCENE_METADATA['name'] must be 'hub'."""
        meta = self._get_meta()
        assert meta["name"] == "hub"

    def test_hub_scene_metadata_display_name(self) -> None:
        """display_name must be 'THE TERMINAL'."""
        meta = self._get_meta()
        assert meta["display_name"] == "THE TERMINAL"

    def test_hub_scene_metadata_port(self) -> None:
        """Port must be 8500."""
        meta = self._get_meta()
        assert meta["port"] == 8500

    def test_hub_scene_metadata_accent_color(self) -> None:
        """Accent colour must be #3b82f6 (blue)."""
        meta = self._get_meta()
        assert meta["accent_color"] == "#3b82f6"

    def test_hub_scene_metadata_accent_rgb(self) -> None:
        """accent_rgb must be '59 130 246'."""
        meta = self._get_meta()
        assert meta["accent_rgb"] == "59 130 246"

    def test_hub_scene_metadata_type(self) -> None:
        """Scene type must be 'hub'."""
        meta = self._get_meta()
        assert meta["type"] == "hub"

    def test_hub_scene_metadata_description_present(self) -> None:
        """Description must be non-empty."""
        meta = self._get_meta()
        assert meta.get("description"), "description should not be empty"


# ══════════════════════════════════════════════════════════════════════
# 2. Skill registration
# ══════════════════════════════════════════════════════════════════════


class TestHubSkillsRegistered:
    """Confirm that hub skills are discoverable in the SKILL_REGISTRY."""

    def _get_registry(self) -> list:
        from engine.skills.registry import SKILL_REGISTRY
        # Re-import skills to ensure decorators have run
        import content.scenes.hub.hub_skills  # noqa: F401
        return SKILL_REGISTRY._skills.get("hub", [])

    def test_hub_skills_registered(self) -> None:
        """Both hub skills must appear in the skill registry under pack='hub'."""
        hub_skills = self._get_registry()
        skill_names = {s.name for s in hub_skills}
        assert "get_all_scenes_status" in skill_names, (
            f"get_all_scenes_status not in hub skills: {skill_names}"
        )
        assert "get_world_status" in skill_names, (
            f"get_world_status not in hub skills: {skill_names}"
        )

    def test_hub_skills_count(self) -> None:
        """Hub pack must have at least 2 registered skills."""
        hub_skills = self._get_registry()
        assert len(hub_skills) >= 2

    def test_hub_skills_category_is_system(self) -> None:
        """Hub skills must have category='system'."""
        hub_skills = self._get_registry()
        for s in hub_skills:
            assert s.category == "system", (
                f"Skill {s.name} category is '{s.category}', expected 'system'"
            )


# ══════════════════════════════════════════════════════════════════════
# 3. get_all_scenes_status skill
# ══════════════════════════════════════════════════════════════════════


class TestGetAllScenesStatusSkill:
    """Unit-test the get_all_scenes_status skill function."""

    def _call(self, all_online: bool = False) -> dict:
        from content.scenes.hub.hub_skills import get_all_scenes_status

        def _mock_port(port: int) -> bool:
            return all_online

        with patch("content.scenes.hub.hub_skills._port_open", side_effect=_mock_port):
            result_str = get_all_scenes_status()

        return json.loads(result_str)

    def test_get_all_scenes_status_returns_json_string(self) -> None:
        """Skill must return a valid JSON string."""
        from content.scenes.hub.hub_skills import get_all_scenes_status
        with patch("content.scenes.hub.hub_skills._port_open", return_value=False):
            result = get_all_scenes_status()
        assert isinstance(result, str)
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_get_all_scenes_status_all_offline(self) -> None:
        """All scenes offline → online count = 0."""
        data = self._call(all_online=False)
        assert data["online"] == 0
        assert data["total"] > 0
        assert all(s["status"] == "offline" for s in data["scenes"])

    def test_get_all_scenes_status_all_online(self) -> None:
        """All scenes online → online == total."""
        data = self._call(all_online=True)
        assert data["online"] == data["total"]
        assert all(s["status"] == "online" for s in data["scenes"])

    def test_get_all_scenes_status_summary_field(self) -> None:
        """Result must include a human-readable summary string."""
        data = self._call(all_online=False)
        assert "summary" in data
        assert "/" in data["summary"]  # e.g. "0/15 scenes online"

    def test_get_all_scenes_status_scene_fields(self) -> None:
        """Each scene entry must have id, label, port, status."""
        data = self._call()
        for scene in data["scenes"]:
            assert "id"     in scene
            assert "label"  in scene
            assert "port"   in scene
            assert "status" in scene


# ══════════════════════════════════════════════════════════════════════
# 4. get_world_status skill
# ══════════════════════════════════════════════════════════════════════


class TestGetWorldStatusSkill:
    """Unit-test the get_world_status skill function."""

    def _mock_world_summary(self) -> dict:
        return {
            "time": {"hour": 22, "minute": 15, "day": 7, "day_name": "Thursday"},
            "active_events": [{"name": "Blackout Protocol"}],
            "weather": {"neoncity": "rain"},
            "npc_availability": {"aria": True, "jack": False},
        }

    def test_get_world_status_returns_json_string(self) -> None:
        """Skill must return a valid JSON string."""
        from content.scenes.hub.hub_skills import get_world_status

        mock_ws = MagicMock()
        mock_ws.get_world_summary.return_value = self._mock_world_summary()

        with patch("engine.world.world_state.get_world_state", return_value=mock_ws):
            result = get_world_status()

        assert isinstance(result, str)
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_get_world_status_night_cycle(self) -> None:
        """Hour 22 → 'NIGHT CYCLE' in time string."""
        from content.scenes.hub.hub_skills import get_world_status

        mock_ws = MagicMock()
        mock_ws.get_world_summary.return_value = self._mock_world_summary()

        with patch("engine.world.world_state.get_world_state", return_value=mock_ws):
            data = json.loads(get_world_status())

        assert "NIGHT CYCLE" in data["time"]

    def test_get_world_status_events_listed(self) -> None:
        """Active events must appear in the result."""
        from content.scenes.hub.hub_skills import get_world_status

        mock_ws = MagicMock()
        mock_ws.get_world_summary.return_value = self._mock_world_summary()

        with patch("engine.world.world_state.get_world_state", return_value=mock_ws):
            data = json.loads(get_world_status())

        assert "Blackout Protocol" in data["active_events"]

    def test_get_world_status_graceful_fallback(self) -> None:
        """If WorldState raises, skill must return JSON with 'error' key."""
        from content.scenes.hub.hub_skills import get_world_status

        with patch(
            "engine.world.world_state.get_world_state",
            side_effect=RuntimeError("no world"),
        ):
            result = get_world_status()

        data = json.loads(result)
        assert "error" in data
        assert data["time"] == "UNKNOWN"


# ══════════════════════════════════════════════════════════════════════
# 5. Static asset existence
# ══════════════════════════════════════════════════════════════════════


class TestHubStaticAssets:
    """Confirm all required hub static / template files exist on disk."""

    def test_hub_html_exists(self) -> None:
        """hub.html template must exist."""
        path = _HUB_DIR / "templates" / "hub.html"
        assert path.is_file(), f"Missing template: {path}"

    def test_hub_css_exists(self) -> None:
        """hub.css must exist in static/."""
        path = _HUB_DIR / "static" / "hub.css"
        assert path.is_file(), f"Missing stylesheet: {path}"

    def test_hub_js_exists(self) -> None:
        """hub.js must exist in static/."""
        path = _HUB_DIR / "static" / "hub.js"
        assert path.is_file(), f"Missing script: {path}"

    def test_hub_html_contains_scene_grid_neon_world(self) -> None:
        """hub.html must define the neon_world scene grid container."""
        html = (_HUB_DIR / "templates" / "hub.html").read_text(encoding="utf-8")
        assert "scene-grid-neon_world" in html

    def test_hub_html_contains_scene_grid_action(self) -> None:
        """hub.html must define the action scene grid container."""
        html = (_HUB_DIR / "templates" / "hub.html").read_text(encoding="utf-8")
        assert "scene-grid-action" in html

    def test_hub_html_contains_world_state_panel(self) -> None:
        """hub.html must include the world-state panel."""
        html = (_HUB_DIR / "templates" / "hub.html").read_text(encoding="utf-8")
        assert "world-state-panel" in html

    def test_hub_html_contains_economy_summary(self) -> None:
        """hub.html must include the economy-summary panel."""
        html = (_HUB_DIR / "templates" / "hub.html").read_text(encoding="utf-8")
        assert "economy-summary" in html

    def test_hub_html_has_data_scene_hub(self) -> None:
        """body tag must carry data-scene='hub'."""
        html = (_HUB_DIR / "templates" / "hub.html").read_text(encoding="utf-8")
        assert 'data-scene="hub"' in html

    def test_hub_css_contains_scene_card(self) -> None:
        """hub.css must define .scene-card styles."""
        css = (_HUB_DIR / "static" / "hub.css").read_text(encoding="utf-8")
        assert ".scene-card" in css

    def test_hub_css_contains_status_dot(self) -> None:
        """hub.css must define .status-dot styles."""
        css = (_HUB_DIR / "static" / "hub.css").read_text(encoding="utf-8")
        assert ".status-dot" in css

    def test_hub_css_contains_scene_accent_var(self) -> None:
        """hub.css must use --scene-accent CSS variable."""
        css = (_HUB_DIR / "static" / "hub.css").read_text(encoding="utf-8")
        assert "--scene-accent" in css

    def test_hub_js_contains_class(self) -> None:
        """hub.js must define TheTerminalHub class."""
        js = (_HUB_DIR / "static" / "hub.js").read_text(encoding="utf-8")
        assert "class TheTerminalHub" in js

    def test_hub_js_contains_load_scenes(self) -> None:
        """hub.js TheTerminalHub must implement loadScenes."""
        js = (_HUB_DIR / "static" / "hub.js").read_text(encoding="utf-8")
        assert "loadScenes" in js

    def test_hub_js_contains_load_world_state(self) -> None:
        """hub.js TheTerminalHub must implement loadWorldState."""
        js = (_HUB_DIR / "static" / "hub.js").read_text(encoding="utf-8")
        assert "loadWorldState" in js

    def test_hub_js_contains_data_stream(self) -> None:
        """hub.js must initialise the data-stream particle canvas."""
        js = (_HUB_DIR / "static" / "hub.js").read_text(encoding="utf-8")
        assert "_initDataStream" in js or "data-stream" in js


# ══════════════════════════════════════════════════════════════════════
# 6. Flask routes (light integration, no server required)
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def hub_client():
    """Create a test Flask client for HubScene without starting the server."""
    with (
        patch("content.scenes.hub.hub_flask.register_shared_assets"),
        patch.object(
            __import__(
                "engine.scenes.base_scene", fromlist=["BaseScene"]
            ).BaseScene,
            "register_health_route",
        ),
    ):
        from content.scenes.hub.hub_flask import HubScene
        scene = HubScene.__new__(HubScene)
        scene.scene_name = "hub"
        scene.host = "0.0.0.0"
        scene.port = 8500

        from flask import Flask
        import jinja2 as _jinja2

        _scene_dir = Path(__file__).parent.parent / "content" / "scenes" / "hub"
        scene.app = Flask(
            "hub_test",
            template_folder=str(_scene_dir / "templates"),
            static_folder=str(_scene_dir / "static"),
        )
        _shared = _scene_dir.parent.parent / "shared" / "templates"
        scene.app.jinja_loader = _jinja2.ChoiceLoader([
            _jinja2.FileSystemLoader(str(_scene_dir / "templates")),
            _jinja2.FileSystemLoader(str(_shared)),
        ])
        scene.app.config["TESTING"] = True

        # Wire routes manually
        scene._setup_routes()

        with scene.app.test_client() as client:
            yield client


class TestHubFlaskRoutes:
    """Light integration tests for Flask route responses."""

    def test_api_scenes_returns_200(self, hub_client) -> None:
        """GET /api/scenes → 200 JSON."""
        with patch("content.scenes.hub.hub_flask._port_open", return_value=False):
            res = hub_client.get("/api/scenes")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_api_scenes_contains_status_field(self, hub_client) -> None:
        """Each scene in /api/scenes must carry a 'status' field."""
        with patch("content.scenes.hub.hub_flask._port_open", return_value=False):
            res = hub_client.get("/api/scenes")
        for scene in json.loads(res.data):
            assert "status" in scene

    def test_api_world_state_fallback(self, hub_client) -> None:
        """/api/world_state must return JSON even when WorldState is unavailable."""
        with patch(
            "content.scenes.hub.hub_flask.render_template", return_value=""
        ):
            res = hub_client.get("/api/world_state")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "time" in data or "ok" in data

    def test_api_economy_fallback(self, hub_client) -> None:
        """/api/economy must return JSON with 'balance' even on error."""
        res = hub_client.get("/api/economy")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "balance" in data

    def test_get_plugin_info_version(self, hub_client) -> None:
        """get_plugin_info must report version '0.68'."""
        # Reconstruct scene just to call get_plugin_info
        with (
            patch("content.scenes.hub.hub_flask.register_shared_assets"),
            patch.object(
                __import__(
                    "engine.scenes.base_scene", fromlist=["BaseScene"]
                ).BaseScene,
                "register_health_route",
                lambda *a, **kw: None,
            ),
        ):
            from content.scenes.hub.hub_flask import HubScene
            scene = HubScene.__new__(HubScene)
            scene.scene_name = "hub"
            scene.port = 8500
            scene.host = "0.0.0.0"
            scene.app = MagicMock()
            scene.app.jinja_loader = None
            info = scene.get_plugin_info()
        assert info["version"] == "0.68"
        assert "hub" in info["skill_packs"]
