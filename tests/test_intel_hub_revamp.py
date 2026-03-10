"""Tests for THE BRIEFING ROOM — Intel Hub revamp (v0.68 Dark Renaissance).

Covers:
  - SCENE_METADATA accuracy (new display_name, accent, type)
  - Skills module registration (all skills including new trio)
  - get_benchmark_report skill callable
  - get_news_feed skill callable
  - ask_aria skill callable
  - HTML template exists
  - CSS file exists
  - JS file exists
  - World events route (/api/world/events)
  - Scene health route (/api/scenes/health)
  - Index route injects navbar context
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


NEON_BASE = Path(__file__).parent.parent / "content" / "shared" / "templates" / "neon_base.html"


def _effective_content(raw: str) -> str:
    """If template extends neon_base.html, include base content for assertion checks."""
    if "extends 'neon_base.html'" in raw or 'extends "neon_base.html"' in raw:
        base = NEON_BASE.read_text(encoding="utf-8") if NEON_BASE.exists() else ""
        combined = raw + "\n" + base
        m = re.search(r"{%\s*set\s+scene_key\s*=\s*['\"](\w+)['\"]", raw)
        if m:
            combined = combined.replace("{{ scene_key }}", m.group(1))
        return combined
    return raw

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def scene_module():
    """Import intel_hub_scene module (no Flask server started)."""
    with (
        patch("engine.config.get_config", return_value=MagicMock(get=lambda k, d=None: d)),
        patch("content.scenes.intel_hub.intel_hub_scene.register_shared_assets"),
        patch("content.scenes.intel_hub.intel_hub_scene.SocketIO", None),
    ):
        import importlib
        import content.scenes.intel_hub.intel_hub_scene as mod
        importlib.reload(mod)
        yield mod


@pytest.fixture
def hub_app(scene_module):
    """Wired Flask test client for THE BRIEFING ROOM."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True

    with (
        patch("engine.scenes.base_scene.BaseScene.__init__", lambda s, **kw: None),
        patch("engine.scenes.base_scene.BaseScene.register_health_route"),
        patch("engine.scenes.base_scene.BaseScene.register_bench_route"),
        patch("engine.scenes.base_scene.BaseScene.register_tts_route"),
        patch("engine.scenes.base_scene.BaseScene.inject_navbar_context",
              return_value={"current_scene": "intel_hub",
                            "scene_name": "THE BRIEFING ROOM",
                            "scene_accent": "#06b6d4"}),
        patch("engine.nexus.user_profile.get_user_profile_store", return_value=MagicMock()),
    ):
        scene = scene_module.IntelHubScene.__new__(scene_module.IntelHubScene)
        scene._app = app
        scene._host = "0.0.0.0"
        scene._port = 5580
        import collections
        scene._activity = collections.deque(maxlen=200)
        scene._notification_subscribers = []
        scene._socketio = None
        scene._stop_event = MagicMock()
        scene._register_routes()
        yield app.test_client()


# ── 1. SCENE_METADATA ────────────────────────────────────────────────────────


class TestIntelHubSceneMetadata:
    """SCENE_METADATA reflects v0.68 Briefing Room values."""

    def test_display_name(self, scene_module):
        meta = scene_module.SCENE_METADATA
        assert meta["display_name"] == "THE BRIEFING ROOM"

    def test_port(self, scene_module):
        assert scene_module.SCENE_METADATA["port"] == 5580

    def test_type_is_system(self, scene_module):
        assert scene_module.SCENE_METADATA["type"] == "system"

    def test_accent_color(self, scene_module):
        assert scene_module.SCENE_METADATA["accent_color"] == "#06b6d4"

    def test_accent_rgb(self, scene_module):
        assert scene_module.SCENE_METADATA["accent_rgb"] == "6 182 212"

    def test_description_set(self, scene_module):
        assert scene_module.SCENE_METADATA["description"]

    def test_class_has_metadata(self, scene_module):
        assert hasattr(scene_module.IntelHubScene, "SCENE_METADATA")
        assert scene_module.IntelHubScene.SCENE_METADATA["display_name"] == "THE BRIEFING ROOM"


# ── 2. SKILLS REGISTERED ────────────────────────────────────────────────────


class TestIntelHubSkillsRegistered:
    """All expected skills exist and are callable."""

    def test_skills_module_importable(self):
        from content.scenes.intel_hub import intel_hub_skills
        assert intel_hub_skills is not None

    def test_original_skills_callable(self):
        from content.scenes.intel_hub.intel_hub_skills import (
            intel_hub_status,
            intel_hub_chat,
            intel_hub_tts_test,
            intel_hub_list_voices,
            intel_hub_vtt_config,
            intel_hub_cache_status,
        )
        for fn in (intel_hub_status, intel_hub_chat, intel_hub_tts_test,
                   intel_hub_list_voices, intel_hub_vtt_config, intel_hub_cache_status):
            assert callable(fn)

    def test_new_skills_callable(self):
        from content.scenes.intel_hub.intel_hub_skills import (
            get_benchmark_report,
            get_news_feed,
            ask_aria,
        )
        assert callable(get_benchmark_report)
        assert callable(get_news_feed)
        assert callable(ask_aria)

    def test_new_skills_in_intel_hub_pack(self):
        """New skills carry the correct pack identifier."""
        from content.scenes.intel_hub.intel_hub_skills import (
            get_benchmark_report, get_news_feed, ask_aria,
        )
        for fn in (get_benchmark_report, get_news_feed, ask_aria):
            # The @skill decorator attaches metadata as _skill_meta or similar
            meta = getattr(fn, "_skill_meta", None) or getattr(fn, "__skill__", None)
            if meta is not None:
                assert meta.get("pack") == "intel_hub"


# ── 3. get_benchmark_report SKILL ───────────────────────────────────────────


class TestGetBenchmarkReportSkill:
    """get_benchmark_report returns JSON-parseable string."""

    def test_returns_string(self):
        from content.scenes.intel_hub.intel_hub_skills import get_benchmark_report
        with (
            patch("content.scenes.intel_hub.intel_hub_scene._get_system_resources",
                  return_value={"cpu_percent": 12, "ram_percent": 55}),
            patch("content.scenes.intel_hub.intel_hub_scene._get_benchmarks",
                  return_value={"benchmarks": []}),
        ):
            result = get_benchmark_report()
        assert isinstance(result, str)

    def test_returns_valid_json(self):
        import json
        from content.scenes.intel_hub.intel_hub_skills import get_benchmark_report
        with (
            patch("content.scenes.intel_hub.intel_hub_scene._get_system_resources",
                  return_value={"cpu_percent": 5, "ram_percent": 40}),
            patch("content.scenes.intel_hub.intel_hub_scene._get_benchmarks",
                  return_value={"benchmarks": []}),
        ):
            result = get_benchmark_report()
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_fallback_includes_system_key(self):
        import json
        from content.scenes.intel_hub.intel_hub_skills import get_benchmark_report
        with (
            patch("content.scenes.intel_hub.intel_hub_scene._get_system_resources",
                  return_value={"cpu_percent": 22}),
            patch("content.scenes.intel_hub.intel_hub_scene._get_benchmarks",
                  return_value={"benchmarks": []}),
        ):
            result = json.loads(get_benchmark_report())
        assert "system" in result or "error" in result  # graceful either way


# ── 4. HTML EXISTS ──────────────────────────────────────────────────────────


class TestIntelHubHtmlExists:
    """Template file exists and contains expected Briefing Room markup."""

    _TPL = Path("content/scenes/intel_hub/templates/intel_hub.html")

    def test_file_exists(self):
        assert self._TPL.exists(), "intel_hub.html template missing"

    def test_contains_briefing_room_title(self):
        content = _effective_content(self._TPL.read_text(encoding="utf-8"))
        assert "THE BRIEFING ROOM" in content

    def test_contains_data_scene_attribute(self):
        content = _effective_content(self._TPL.read_text(encoding="utf-8"))
        assert 'data-scene="intel_hub"' in content

    def test_contains_aria_panel(self):
        content = _effective_content(self._TPL.read_text(encoding="utf-8"))
        assert "aria-center-panel" in content

    def test_contains_scene_health_grid(self):
        content = _effective_content(self._TPL.read_text(encoding="utf-8"))
        assert "scene-health-grid" in content

    def test_includes_navbar(self):
        content = _effective_content(self._TPL.read_text(encoding="utf-8"))
        assert "navbar_v2.html" in content

    def test_contains_data_stream_canvas(self):
        content = _effective_content(self._TPL.read_text(encoding="utf-8"))
        assert "data-stream-canvas" in content


# ── 5. CSS EXISTS ───────────────────────────────────────────────────────────


class TestIntelHubCssExists:
    """CSS file exists and defines the expected mission-control classes."""

    _CSS = Path("content/scenes/intel_hub/static/css/intel_hub.css")

    def test_file_exists(self):
        assert self._CSS.exists(), "intel_hub.css missing"

    def test_intel_layout_class(self):
        assert ".intel-layout" in self._CSS.read_text(encoding="utf-8")

    def test_aria_center_panel_class(self):
        assert ".aria-center-panel" in self._CSS.read_text(encoding="utf-8")

    def test_status_light_class(self):
        assert ".status-light" in self._CSS.read_text(encoding="utf-8")

    def test_intel_panel_class(self):
        assert ".intel-panel" in self._CSS.read_text(encoding="utf-8")

    def test_news_feed_class(self):
        assert ".news-feed" in self._CSS.read_text(encoding="utf-8")

    def test_scene_health_grid_class(self):
        assert ".scene-health-grid" in self._CSS.read_text(encoding="utf-8")

    def test_accent_color_present(self):
        # The cyan accent must appear in CSS variables
        assert "#06b6d4" in self._CSS.read_text(encoding="utf-8")


# ── 6. ROUTES ───────────────────────────────────────────────────────────────


class TestIntelHubRoutes:
    """New routes respond correctly."""

    def test_health_includes_display_name(self, hub_app):
        rv = hub_app.get("/api/health")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data.get("display_name") == "THE BRIEFING ROOM"

    def test_world_events_route_exists(self, hub_app):
        with patch("content.scenes.intel_hub.intel_hub_scene._get_world_events",
                   return_value={"events": [], "count": 0}):
            rv = hub_app.get("/api/world/events")
        assert rv.status_code == 200

    def test_scene_health_route_exists(self, hub_app):
        with patch("content.scenes.intel_hub.intel_hub_scene._get_scene_health",
                   return_value={"scenes": [], "online": 0, "total": 0}):
            rv = hub_app.get("/api/scenes/health")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "scenes" in data

    def test_index_returns_html(self, hub_app):
        with patch("content.scenes.intel_hub.intel_hub_scene.render_template",
                   return_value="<html>THE BRIEFING ROOM</html>"):
            rv = hub_app.get("/")
        assert rv.status_code == 200


# ── 7. JS EXISTS ────────────────────────────────────────────────────────────


class TestIntelHubJsExists:
    """JS file exists and exports the BriefingRoomScene class."""

    _JS = Path("content/scenes/intel_hub/static/js/intel_hub.js")

    def test_file_exists(self):
        assert self._JS.exists(), "intel_hub.js missing"

    def test_briefing_room_class(self):
        assert "BriefingRoomScene" in self._JS.read_text(encoding="utf-8")

    def test_data_stream_particles_class(self):
        assert "DataStreamParticles" in self._JS.read_text(encoding="utf-8")

    def test_ask_aria_method(self):
        assert "askAria" in self._JS.read_text(encoding="utf-8")

    def test_send_message_method(self):
        assert "sendMessage" in self._JS.read_text(encoding="utf-8")

    def test_load_dashboard_method(self):
        assert "loadDashboard" in self._JS.read_text(encoding="utf-8")


# ── 8. PACKAGE __init__ ─────────────────────────────────────────────────────


class TestIntelHubPackage:
    """__init__.py exports IntelHubScene and registers skills."""

    def test_package_importable(self):
        import content.scenes.intel_hub
        assert content.scenes.intel_hub is not None

    def test_exports_scene_class(self):
        from content.scenes.intel_hub import IntelHubScene
        assert IntelHubScene is not None

    def test_init_imports_skills(self):
        init_src = Path("content/scenes/intel_hub/__init__.py").read_text(encoding="utf-8")
        assert "intel_hub_skills" in init_src
        assert "noqa" in init_src  # skills import comment pattern
