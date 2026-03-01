"""
Tests for THE LAB Coders Scene — v0.68 Dark Renaissance.

Covers: scene metadata, skills registration, skill logic, file existence.
All tests run without a live Flask/Socket.IO server.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
SCENE_DIR = ROOT / "content" / "scenes" / "coders"


# ── Helpers ───────────────────────────────────────────────────────────


def _make_state_mock(
    active: bool = True,
    tick: int = 10,
    total_lines: int = 300,
    total_tests: int = 15,
) -> MagicMock:
    """Return a minimal CodersRoomState-like mock."""
    agent_a = MagicMock()
    agent_a.id = "ada"
    agent_a.name = "Ada"
    agent_a.role.value = "reviewer"
    agent_a.status = "idle"
    agent_a.lines_written = 100
    agent_a.reviews_done = 5
    agent_a.tests_run = 3

    agent_b = MagicMock()
    agent_b.id = "linus"
    agent_b.name = "Linus"
    agent_b.role.value = "writer"
    agent_b.status = "coding"
    agent_b.lines_written = 200
    agent_b.reviews_done = 0
    agent_b.tests_run = 0

    state = MagicMock()
    state.active = active
    state.tick_count = tick
    state.total_lines = total_lines
    state.total_tests = total_tests
    state.agents = [agent_a, agent_b]
    state.features = []
    state.completed_features = []
    state.get_current_feature.return_value = None
    return state


def _make_scene_mock(**kwargs) -> MagicMock:
    """Return a minimal scene mock with a wired state."""
    scene = MagicMock()
    scene.state = _make_state_mock(**kwargs)
    return scene


# ══════════════════════════════════════════════════════════════════════
#  1. Scene metadata
# ══════════════════════════════════════════════════════════════════════


class TestCodersSceneMetadata:
    """SCENE_METADATA must reflect the THE LAB v0.68 identity."""

    def test_scene_metadata_name(self):
        from content.scenes.coders.coders_scene import CodersRoomScene
        assert CodersRoomScene.SCENE_METADATA["name"] == "coders"

    def test_scene_metadata_display_name(self):
        from content.scenes.coders.coders_scene import CodersRoomScene
        assert CodersRoomScene.SCENE_METADATA["display_name"] == "THE LAB"

    def test_scene_metadata_port(self):
        from content.scenes.coders.coders_scene import CodersRoomScene
        assert CodersRoomScene.SCENE_METADATA["port"] == 5564

    def test_scene_metadata_type(self):
        from content.scenes.coders.coders_scene import CodersRoomScene
        assert CodersRoomScene.SCENE_METADATA["type"] == "system"

    def test_scene_metadata_accent_color(self):
        from content.scenes.coders.coders_scene import CodersRoomScene
        assert CodersRoomScene.SCENE_METADATA["accent_color"] == "#4ade80"

    def test_scene_metadata_accent_rgb(self):
        from content.scenes.coders.coders_scene import CodersRoomScene
        assert CodersRoomScene.SCENE_METADATA["accent_rgb"] == "74 222 128"

    def test_scene_metadata_description_set(self):
        from content.scenes.coders.coders_scene import CodersRoomScene
        desc = CodersRoomScene.SCENE_METADATA["description"]
        assert isinstance(desc, str) and len(desc) > 10


# ══════════════════════════════════════════════════════════════════════
#  2. Skills registered in SKILL_REGISTRY
# ══════════════════════════════════════════════════════════════════════


class TestCodersSkillsRegistered:
    """All expected skills must be registered under the 'coders' pack."""

    @pytest.fixture(autouse=True)
    def _import_skills(self):
        """Force @skill decorators to run by importing the module."""
        import content.scenes.coders.coders_skills  # noqa: F401

    def test_core_skills_present(self):
        from engine.skills.registry import SKILL_REGISTRY
        tools = SKILL_REGISTRY.get_pack_tools("coders")
        names = {fn.__name__ for fn in tools}
        expected_core = {
            "coders_status",
            "coders_agent_info",
            "coders_add_feature",
            "coders_feature_list",
            "coders_run_code",
            "coders_tick",
        }
        missing = expected_core - names
        assert not missing, f"Core skills missing: {missing}"

    def test_v068_skills_present(self):
        from engine.skills.registry import SKILL_REGISTRY
        tools = SKILL_REGISTRY.get_pack_tools("coders")
        names = {fn.__name__ for fn in tools}
        expected_new = {"pipeline_status", "start_coding_task", "get_velocity_metrics"}
        missing = expected_new - names
        assert not missing, f"v0.68 skills missing: {missing}"


# ══════════════════════════════════════════════════════════════════════
#  3. pipeline_status skill
# ══════════════════════════════════════════════════════════════════════


class TestPipelineStatusSkill:
    """pipeline_status() must return valid JSON with expected keys."""

    def test_pipeline_status_offline(self):
        from content.scenes.coders.coders_skills import pipeline_status
        with patch("content.scenes.coders.coders_skills._get_coders_scene", return_value=None):
            result = pipeline_status()
        data = json.loads(result)
        assert data["status"] == "offline"

    def test_pipeline_status_running(self):
        from content.scenes.coders.coders_skills import pipeline_status
        mock_scene = _make_scene_mock(active=True, tick=20, total_lines=500, total_tests=25)
        with patch("content.scenes.coders.coders_skills._get_coders_scene", return_value=mock_scene):
            result = pipeline_status()
        data = json.loads(result)
        assert data["status"] == "running"
        assert data["tick"] == 20
        assert "velocity" in data
        assert data["velocity"]["total_lines"] == 500
        assert "agents" in data
        assert len(data["agents"]) == 2

    def test_pipeline_status_agents_schema(self):
        from content.scenes.coders.coders_skills import pipeline_status
        mock_scene = _make_scene_mock()
        with patch("content.scenes.coders.coders_skills._get_coders_scene", return_value=mock_scene):
            result = pipeline_status()
        data = json.loads(result)
        for agent in data["agents"]:
            assert "name"    in agent
            assert "role"    in agent
            assert "status"  in agent
            assert "lines"   in agent

    def test_pipeline_status_has_current_feature(self):
        from content.scenes.coders.coders_skills import pipeline_status
        mock_scene = _make_scene_mock()
        feat = MagicMock()
        feat.title = "Auth Refactor"
        feat.phase.value = "coding"
        mock_scene.state.get_current_feature.return_value = feat
        with patch("content.scenes.coders.coders_skills._get_coders_scene", return_value=mock_scene):
            result = pipeline_status()
        data = json.loads(result)
        assert data["pipeline"]["current"]["title"] == "Auth Refactor"
        assert data["pipeline"]["current"]["phase"] == "coding"


# ══════════════════════════════════════════════════════════════════════
#  4. start_coding_task skill
# ══════════════════════════════════════════════════════════════════════


class TestStartCodingTaskSkill:
    """start_coding_task() must validate input and queue feature."""

    def test_empty_description_rejected(self):
        from content.scenes.coders.coders_skills import start_coding_task
        result = start_coding_task("")
        assert "error" in result.lower() or "cannot" in result.lower() or "empty" in result.lower()

    def test_task_queued_successfully(self):
        from content.scenes.coders.coders_skills import start_coding_task
        mock_scene = _make_scene_mock()
        feat = MagicMock()
        feat.title = "Build auth module"
        feat.id = "feat-abc"
        feat.phase.value = "feature"
        mock_scene.state.add_feature.return_value = feat
        mock_scene.state.features = [feat]
        with patch("content.scenes.coders.coders_skills._get_coders_scene", return_value=mock_scene):
            result = start_coding_task("Build auth module")
        assert "Build auth module" in result
        assert "feat-abc" in result

    def test_scene_offline_message(self):
        from content.scenes.coders.coders_skills import start_coding_task
        with patch("content.scenes.coders.coders_skills._get_coders_scene", return_value=None):
            result = start_coding_task("Some task")
        assert "not active" in result.lower()


# ══════════════════════════════════════════════════════════════════════
#  5. get_velocity_metrics skill
# ══════════════════════════════════════════════════════════════════════


class TestGetVelocityMetricsSkill:
    """get_velocity_metrics() must return JSON with velocity and agent data."""

    def test_returns_valid_json(self):
        from content.scenes.coders.coders_skills import get_velocity_metrics
        mock_scene = _make_scene_mock(tick=50, total_lines=800, total_tests=40)
        with patch("content.scenes.coders.coders_skills._get_coders_scene", return_value=mock_scene):
            result = get_velocity_metrics()
        data = json.loads(result)
        assert "velocity" in data
        assert "totals" in data
        assert "agents" in data

    def test_velocity_values(self):
        from content.scenes.coders.coders_skills import get_velocity_metrics
        mock_scene = _make_scene_mock(tick=10, total_lines=200, total_tests=20)
        with patch("content.scenes.coders.coders_skills._get_coders_scene", return_value=mock_scene):
            result = get_velocity_metrics()
        data = json.loads(result)
        assert data["velocity"]["lines_per_tick"] == pytest.approx(20.0, abs=0.1)
        assert data["velocity"]["tests_per_tick"] == pytest.approx(2.0, abs=0.1)

    def test_pipeline_health_field(self):
        from content.scenes.coders.coders_skills import get_velocity_metrics
        mock_scene = _make_scene_mock(active=True)
        mock_scene.state.features = []
        with patch("content.scenes.coders.coders_skills._get_coders_scene", return_value=mock_scene):
            result = get_velocity_metrics()
        data = json.loads(result)
        assert data["pipeline_health"] in ("green", "yellow")

    def test_offline_returns_error(self):
        from content.scenes.coders.coders_skills import get_velocity_metrics
        with patch("content.scenes.coders.coders_skills._get_coders_scene", return_value=None):
            result = get_velocity_metrics()
        data = json.loads(result)
        assert "error" in data


# ══════════════════════════════════════════════════════════════════════
#  6. HTML template existence and content
# ══════════════════════════════════════════════════════════════════════


class TestCodersHtmlExists:
    """coders.html must exist with correct structure and v0.68 identifiers."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.path = SCENE_DIR / "templates" / "coders.html"
        self.content = self.path.read_text(encoding="utf-8")

    def test_html_file_exists(self):
        assert self.path.exists(), f"Template not found: {self.path}"

    def test_has_the_lab_title(self):
        assert "THE LAB" in self.content

    def test_has_data_scene_coders(self):
        assert 'data-scene="coders"' in self.content

    def test_has_navbar_include(self):
        assert "navbar_v2.html" in self.content

    def test_has_matrix_canvas(self):
        assert "matrix-canvas" in self.content

    def test_has_pipeline_stepper(self):
        assert "pipeline-stepper" in self.content

    def test_has_socketio_script(self):
        assert "socket.io" in self.content

    def test_links_coders_css(self):
        assert "coders.css" in self.content

    def test_links_coders_js(self):
        assert "coders.js" in self.content


# ══════════════════════════════════════════════════════════════════════
#  7. CSS file existence and content
# ══════════════════════════════════════════════════════════════════════


class TestCodersCssExists:
    """coders.css must exist with matrix-green palette and required selectors."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.path = SCENE_DIR / "static" / "coders.css"
        self.content = self.path.read_text(encoding="utf-8")

    def test_css_file_exists(self):
        assert self.path.exists(), f"CSS not found: {self.path}"

    def test_accent_color_defined(self):
        assert "#4ade80" in self.content

    def test_agent_feed_selector(self):
        assert ".agent-feed" in self.content

    def test_agent_tag_selector(self):
        assert ".agent-tag" in self.content

    def test_pipeline_stepper_selector(self):
        assert ".pipeline-stepper" in self.content

    def test_task_card_selector(self):
        assert ".task-card" in self.content

    def test_metrics_panel_selector(self):
        assert ".metrics-panel" in self.content

    def test_coders_layout_selector(self):
        assert ".coders-layout" in self.content

    def test_matrix_canvas_selector(self):
        assert "#matrix-canvas" in self.content


# ══════════════════════════════════════════════════════════════════════
#  8. JS file existence and content
# ══════════════════════════════════════════════════════════════════════


class TestCodersJsExists:
    """coders.js must exist with TheLabScene class and required methods."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.path = SCENE_DIR / "static" / "coders.js"
        self.content = self.path.read_text(encoding="utf-8")

    def test_js_file_exists(self):
        assert self.path.exists(), f"JS not found: {self.path}"

    def test_the_lab_scene_class(self):
        assert "class TheLabScene" in self.content

    def test_has_init_method(self):
        assert "init()" in self.content

    def test_has_setup_socket_method(self):
        assert "_setupSocket()" in self.content

    def test_has_load_state_method(self):
        assert "loadState()" in self.content

    def test_has_start_task_method(self):
        assert "startTask(" in self.content

    def test_has_render_agent_feed(self):
        assert "_renderAgentFeed(" in self.content

    def test_has_update_pipeline(self):
        assert "_updatePipeline(" in self.content

    def test_has_send_message(self):
        assert "sendMessage(" in self.content

    def test_has_matrix_rain_class(self):
        assert "class MatrixRain" in self.content

    def test_window_the_lab_exported(self):
        assert "window.TheLab" in self.content
