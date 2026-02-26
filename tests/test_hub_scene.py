"""Tests for the Hub Scene module and Scene Creator.

Covers:
- Hub utility functions (_service_up, _port_open)
- SCENE_CATEGORIES structure and completeness
- HEALTH_SERVICES data
- init_session_state behaviour
- Scene Creator templates, scaffold logic, and code generation
"""

import sys
import json
import os
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

import pytest


# ── Helpers ─────────────────────────────────────────────────────────


class _SessionState(dict):
    """Dict subclass supporting attribute access, like Streamlit's session_state."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name)

    def __contains__(self, key):
        return super().__contains__(key)


def _columns_side_effect(n, *a, **kw):
    """Return *n* MagicMock columns so tuple-unpacking works."""
    if isinstance(n, int):
        return [MagicMock() for _ in range(n)]
    if isinstance(n, (list, tuple)):
        return [MagicMock() for _ in n]
    return [MagicMock(), MagicMock(), MagicMock()]


def _make_mock_st():
    """Build a Streamlit mock that survives module-level import."""
    mock_st = MagicMock()
    mock_st.set_page_config = MagicMock()
    mock_st.markdown = MagicMock()
    mock_st.header = MagicMock()
    mock_st.subheader = MagicMock()
    mock_st.columns = MagicMock(side_effect=_columns_side_effect)
    mock_st.tabs = MagicMock(side_effect=lambda labels: [MagicMock() for _ in labels])
    mock_st.radio = MagicMock(return_value="📊 Dashboard")
    mock_st.button = MagicMock(return_value=False)
    mock_st.sidebar = MagicMock()
    mock_st.sidebar.__enter__ = MagicMock(return_value=mock_st.sidebar)
    mock_st.sidebar.__exit__ = MagicMock(return_value=False)
    mock_st.session_state = _SessionState()
    mock_st.metric = MagicMock()
    mock_st.json = MagicMock()
    mock_st.info = MagicMock()
    mock_st.warning = MagicMock()
    mock_st.error = MagicMock()
    mock_st.success = MagicMock()
    mock_st.text_input = MagicMock(return_value="")
    mock_st.text_area = MagicMock(return_value="")
    mock_st.number_input = MagicMock(return_value=5560)
    mock_st.checkbox = MagicMock(return_value=False)
    mock_st.expander = MagicMock()
    mock_st.expander.return_value.__enter__ = MagicMock()
    mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
    mock_st.code = MagicMock()
    mock_st.caption = MagicMock()
    mock_st.rerun = MagicMock()
    mock_st.balloons = MagicMock()
    return mock_st


def _make_asset_manager_mock():
    mgr = MagicMock()
    mgr.get_stats.return_value = {
        "total_assets": 10,
        "by_type": {"character": 3, "image": 7},
        "registered_types": ["character", "image"],
        "total_tags": 5,
    }
    mgr.search.return_value = []
    return mgr


@pytest.fixture
def mock_st():
    return _make_mock_st()


@pytest.fixture
def asset_mgr():
    return _make_asset_manager_mock()


# ── Hub Scene Module Import ─────────────────────────────────────────


@pytest.fixture
def hub_module(mock_st, asset_mgr):
    """Import hub_scene with streamlit + engine deps mocked."""
    mock_requests = MagicMock()
    with patch.dict(sys.modules, {"streamlit": mock_st, "requests": mock_requests}):
        with patch("engine.assets.AssetManager", return_value=asset_mgr):
            with patch("engine.config.ConfigManager", return_value=MagicMock()):
                mod_key = "content.scenes.hub.hub_scene"
                sys.modules.pop(mod_key, None)
                import content.scenes.hub.hub_scene as hub_scene
                return hub_scene, mock_st, asset_mgr, mock_requests


@pytest.fixture
def creator_module(mock_st, asset_mgr):
    """Import scene_creator with streamlit + engine deps mocked."""
    with patch.dict(sys.modules, {"streamlit": mock_st}):
        with patch("engine.assets.AssetManager", return_value=asset_mgr):
            with patch("engine.config.ConfigManager", return_value=MagicMock()):
                mod_key = "content.scenes.hub.scene_creator"
                sys.modules.pop(mod_key, None)
                import content.scenes.hub.scene_creator as scene_creator
                return scene_creator, mock_st, asset_mgr


# ═══════════════════════════════════════════════════════════════════
# Hub Scene Tests
# ═══════════════════════════════════════════════════════════════════


class TestServiceUp:
    """Test _service_up HTTP health check."""

    def test_returns_true_on_200(self, hub_module):
        mod, _, _, mock_requests = hub_module
        resp = MagicMock()
        resp.status_code = 200
        mock_requests.get.return_value = resp
        assert mod._service_up("http://localhost:1234/v1/models") is True

    def test_returns_true_on_404(self, hub_module):
        """Non-5xx codes are considered 'up'."""
        mod, _, _, mock_requests = hub_module
        resp = MagicMock()
        resp.status_code = 404
        mock_requests.get.return_value = resp
        assert mod._service_up("http://localhost:1234/missing") is True

    def test_returns_false_on_500(self, hub_module):
        mod, _, _, mock_requests = hub_module
        resp = MagicMock()
        resp.status_code = 500
        mock_requests.get.return_value = resp
        assert mod._service_up("http://localhost:1234/error") is False

    def test_returns_false_on_connection_error(self, hub_module):
        mod, _, _, mock_requests = hub_module
        mock_requests.get.side_effect = ConnectionError("refused")
        assert mod._service_up("http://localhost:9999") is False

    def test_returns_false_on_timeout(self, hub_module):
        mod, _, _, mock_requests = hub_module
        mock_requests.get.side_effect = TimeoutError("timed out")
        assert mod._service_up("http://localhost:9999") is False


class TestPortOpen:
    """Test _port_open TCP port check."""

    @patch("socket.create_connection")
    def test_returns_true_when_port_listening(self, mock_conn, hub_module):
        mod, _, _, _ = hub_module
        mock_sock = MagicMock()
        mock_conn.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        assert mod._port_open(5555) is True

    @patch("socket.create_connection")
    def test_returns_false_when_port_closed(self, mock_conn, hub_module):
        mod, _, _, _ = hub_module
        mock_conn.side_effect = OSError("Connection refused")
        assert mod._port_open(59999) is False


class TestSceneCategories:
    """Validate SCENE_CATEGORIES data structure."""

    def test_has_three_categories(self, hub_module):
        mod, _, _, _ = hub_module
        assert set(mod.SCENE_CATEGORIES.keys()) == {"core", "showcase", "tools"}

    def test_core_has_six_scenes(self, hub_module):
        mod, _, _, _ = hub_module
        assert len(mod.SCENE_CATEGORIES["core"]["scenes"]) == 6

    def test_showcase_has_four_scenes(self, hub_module):
        mod, _, _, _ = hub_module
        assert len(mod.SCENE_CATEGORIES["showcase"]["scenes"]) == 4

    def test_tools_has_five_scenes(self, hub_module):
        mod, _, _, _ = hub_module
        assert len(mod.SCENE_CATEGORIES["tools"]["scenes"]) == 5

    def test_every_scene_has_required_keys(self, hub_module):
        mod, _, _, _ = hub_module
        required_keys = {"name", "icon", "port", "mode", "desc", "color"}
        for cat_key, cat in mod.SCENE_CATEGORIES.items():
            for scene in cat["scenes"]:
                missing = required_keys - set(scene.keys())
                assert not missing, f"Scene {scene.get('name', '?')} missing keys: {missing}"

    def test_all_ports_unique(self, hub_module):
        mod, _, _, _ = hub_module
        ports = []
        for cat in mod.SCENE_CATEGORIES.values():
            for scene in cat["scenes"]:
                ports.append(scene["port"])
        assert len(ports) == len(set(ports)), f"Duplicate ports: {ports}"

    def test_all_modes_unique(self, hub_module):
        mod, _, _, _ = hub_module
        modes = []
        for cat in mod.SCENE_CATEGORIES.values():
            for scene in cat["scenes"]:
                modes.append(scene["mode"])
        assert len(modes) == len(set(modes)), f"Duplicate modes: {modes}"

    def test_every_category_has_label(self, hub_module):
        mod, _, _, _ = hub_module
        for cat_key, cat in mod.SCENE_CATEGORIES.items():
            assert "label" in cat
            assert isinstance(cat["label"], str)
            assert len(cat["label"]) > 0


class TestHealthServices:
    """Validate HEALTH_SERVICES list."""

    def test_has_at_least_10_services(self, hub_module):
        mod, _, _, _ = hub_module
        assert len(mod.HEALTH_SERVICES) >= 10

    def test_each_entry_is_name_url_tuple(self, hub_module):
        mod, _, _, _ = hub_module
        for entry in mod.HEALTH_SERVICES:
            assert len(entry) == 2
            name, url = entry
            assert isinstance(name, str)
            assert isinstance(url, str)
            assert url.startswith("http")

    def test_service_names_unique(self, hub_module):
        mod, _, _, _ = hub_module
        names = [name for name, _ in mod.HEALTH_SERVICES]
        assert len(names) == len(set(names))


class TestHubInitSessionState:
    """Test hub's init_session_state."""

    def test_creates_asset_manager(self, hub_module):
        mod, mock_st, _, _ = hub_module
        mock_st.session_state = _SessionState()
        mod.init_session_state()
        assert "asset_manager" in mock_st.session_state

    def test_creates_config(self, hub_module):
        mod, mock_st, _, _ = hub_module
        mock_st.session_state = _SessionState()
        mod.init_session_state()
        assert "config" in mock_st.session_state


# ═══════════════════════════════════════════════════════════════════
# Scene Creator Tests
# ═══════════════════════════════════════════════════════════════════


class TestTemplates:
    """Test the _TEMPLATES data structure."""

    def test_has_four_templates(self, creator_module):
        mod, _, _ = creator_module
        assert len(mod._TEMPLATES) == 4

    def test_template_keys(self, creator_module):
        mod, _, _ = creator_module
        assert set(mod._TEMPLATES.keys()) == {"blank", "chat", "multi_agent", "dashboard"}

    def test_each_template_has_required_fields(self, creator_module):
        mod, _, _ = creator_module
        for key, tmpl in mod._TEMPLATES.items():
            assert "label" in tmpl, f"{key} missing label"
            assert "description" in tmpl, f"{key} missing description"
            assert "characters" in tmpl, f"{key} missing characters"

    def test_blank_has_zero_characters(self, creator_module):
        mod, _, _ = creator_module
        assert mod._TEMPLATES["blank"]["characters"] == 0

    def test_multi_agent_has_two_characters(self, creator_module):
        mod, _, _ = creator_module
        assert mod._TEMPLATES["multi_agent"]["characters"] == 2


class TestFlaskSceneTemplate:
    """Test _flask_scene_template code generation."""

    def test_contains_class_definition(self, creator_module):
        mod, _, _ = creator_module
        code = mod._flask_scene_template("test_scene", "TestScene", "A test", 5570, False, "blank")
        assert "class TestScene(BaseScene):" in code

    def test_contains_health_route(self, creator_module):
        mod, _, _ = creator_module
        code = mod._flask_scene_template("test_scene", "TestScene", "A test", 5570, False, "blank")
        assert "register_health_route" in code

    def test_contains_get_plugin_info(self, creator_module):
        mod, _, _ = creator_module
        code = mod._flask_scene_template("test_scene", "TestScene", "A test", 5570, False, "blank")
        assert "def get_plugin_info(self):" in code

    def test_correct_port_in_output(self, creator_module):
        mod, _, _ = creator_module
        code = mod._flask_scene_template("test_scene", "TestScene", "A test", 7777, False, "blank")
        assert "7777" in code

    def test_api_status_route(self, creator_module):
        mod, _, _ = creator_module
        code = mod._flask_scene_template("demo", "DemoScene", "desc", 5000, False, "blank")
        assert "/api/status" in code


class TestStreamlitSceneTemplate:
    """Test _streamlit_scene_template code generation."""

    def test_contains_set_page_config(self, creator_module):
        mod, _, _ = creator_module
        code = mod._streamlit_scene_template("dash", "DashScene", "Dashboard", 8501)
        assert "set_page_config" in code

    def test_contains_scene_name(self, creator_module):
        mod, _, _ = creator_module
        code = mod._streamlit_scene_template("dash", "DashScene", "My Dashboard", 8501)
        assert "dash" in code


class TestHtmlTemplate:
    """Test _html_template HTML generation."""

    def test_valid_html_structure(self, creator_module):
        mod, _, _ = creator_module
        html = mod._html_template("test", "TestScene")
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_references_css(self, creator_module):
        mod, _, _ = creator_module
        html = mod._html_template("test", "TestScene")
        assert "/static/css/test.css" in html

    def test_references_js(self, creator_module):
        mod, _, _ = creator_module
        html = mod._html_template("test", "TestScene")
        assert "/static/js/test.js" in html


class TestJsTemplate:
    """Test _js_template JavaScript generation."""

    def test_contains_dom_ready(self, creator_module):
        mod, _, _ = creator_module
        js = mod._js_template("my_scene")
        assert "DOMContentLoaded" in js

    def test_contains_health_fetch(self, creator_module):
        mod, _, _ = creator_module
        js = mod._js_template("my_scene")
        assert "/api/health" in js


class TestCssTemplate:
    """Test _css_template CSS generation."""

    def test_sets_dark_background(self, creator_module):
        mod, _, _ = creator_module
        css = mod._css_template("my_scene")
        assert "#0a0a0f" in css

    def test_contains_header_gradient(self, creator_module):
        mod, _, _ = creator_module
        css = mod._css_template("my_scene")
        assert "linear-gradient" in css


class TestScaffoldScene:
    """Test _scaffold_scene creates correct directory structure."""

    def test_creates_all_files(self, creator_module, tmp_path):
        mod, _, _ = creator_module
        # Override project_root to use tmp_path
        with patch.object(mod, "project_root", tmp_path):
            mod._scaffold_scene("test_scene", "blank", "A test scene", 5570, False)
            scene_dir = tmp_path / "content" / "scenes" / "test_scene"
            assert (scene_dir / "__init__.py").exists()
            assert (scene_dir / "test_scene_scene.py").exists()
            assert (scene_dir / "templates" / "test_scene_ui.html").exists()
            assert (scene_dir / "static" / "js" / "test_scene.js").exists()
            assert (scene_dir / "static" / "css" / "test_scene.css").exists()

    def test_init_contains_docstring(self, creator_module, tmp_path):
        mod, _, _ = creator_module
        with patch.object(mod, "project_root", tmp_path):
            mod._scaffold_scene("demo", "blank", "Demo scene", 5570, False)
            init_content = (tmp_path / "content" / "scenes" / "demo" / "__init__.py").read_text()
            assert "demo" in init_content

    def test_flask_template_for_blank(self, creator_module, tmp_path):
        mod, _, _ = creator_module
        with patch.object(mod, "project_root", tmp_path):
            mod._scaffold_scene("my_app", "blank", "Blank", 6000, False)
            scene_code = (tmp_path / "content" / "scenes" / "my_app" / "my_app_scene.py").read_text()
            assert "BaseScene" in scene_code
            assert "Flask" in scene_code

    def test_streamlit_template_for_dashboard(self, creator_module, tmp_path):
        mod, _, _ = creator_module
        with patch.object(mod, "project_root", tmp_path):
            mod._scaffold_scene("my_dash", "dashboard", "Dashboard", 8505, False)
            scene_code = (tmp_path / "content" / "scenes" / "my_dash" / "my_dash_scene.py").read_text()
            assert "streamlit" in scene_code

    def test_scaffold_idempotent_no_error(self, creator_module, tmp_path):
        """Calling scaffold twice should not raise (exist_ok=True)."""
        mod, _, _ = creator_module
        with patch.object(mod, "project_root", tmp_path):
            mod._scaffold_scene("dup", "blank", "Dup", 5570, False)
            mod._scaffold_scene("dup", "blank", "Dup", 5570, False)
            assert (tmp_path / "content" / "scenes" / "dup" / "dup_scene.py").exists()


class TestCreatorInitState:
    """Test scene_creator init_state."""

    def test_sets_default_step(self, creator_module):
        mod, mock_st, _ = creator_module
        mock_st.session_state = _SessionState()
        mod.init_state()
        assert mock_st.session_state.get("sc_step") == 0

    def test_sets_default_template(self, creator_module):
        mod, mock_st, _ = creator_module
        mock_st.session_state = _SessionState()
        mod.init_state()
        assert mock_st.session_state.get("sc_template") == "blank"

    def test_sets_default_port(self, creator_module):
        mod, mock_st, _ = creator_module
        mock_st.session_state = _SessionState()
        mod.init_state()
        assert mock_st.session_state.get("sc_port") == 5560

    def test_preserves_existing_values(self, creator_module):
        mod, mock_st, _ = creator_module
        mock_st.session_state = _SessionState({"sc_step": 3, "sc_name": "existing"})
        mod.init_state()
        assert mock_st.session_state["sc_step"] == 3
        assert mock_st.session_state["sc_name"] == "existing"
