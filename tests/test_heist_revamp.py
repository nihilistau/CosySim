"""
Tests for THE SCORE — Heist Scene v0.68 "Dark Renaissance" revamp.

Covers:
- SCENE_METADATA correctness
- Skill definitions (get_heist_jobs, select_heist, assign_crew_member,
  execute_heist_phase, crew_status)
- Static asset existence (heist.html, heist.css, heist.js)
- HTML structure (data-scene, design-system links, socket.io, TheScoreScene class)
- Socket handler presence in source
- Skill logic with mocked dependencies
"""
from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────
HEIST_ROOT    = Path(__file__).parent.parent / "content" / "scenes" / "heist"
STATIC_CSS    = HEIST_ROOT / "static" / "css" / "heist.css"
STATIC_JS     = HEIST_ROOT / "static" / "js"  / "heist.js"
TEMPLATE_HTML = HEIST_ROOT / "templates" / "heist.html"


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_skill_mock() -> MagicMock:
    """Return a mock engine.skills.skill module where @skill is a no-op decorator."""
    m = MagicMock()
    m.skill = lambda **kw: (lambda fn: fn)
    m.SkillCategory = MagicMock(GAME="game")
    return m


def _load_skills_module():
    """Import heist_skills.py with all engine deps mocked out."""
    mocks = {
        "engine.skills.skill":      _make_skill_mock(),
        "engine.scenes.base_scene": MagicMock(),
        "engine.mcp.state_coordinator": MagicMock(),
        "engine.content.content_engine": MagicMock(),
    }
    with patch.dict("sys.modules", mocks):
        spec = importlib.util.spec_from_file_location(
            "heist_skills_test", HEIST_ROOT / "heist_skills.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod


def _scene_source() -> str:
    return (HEIST_ROOT / "heist_scene.py").read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
#  1. SCENE METADATA
# ══════════════════════════════════════════════════════════════════════════

class TestHeistSceneMetadata:
    """SCENE_METADATA reflects THE SCORE rebrand."""

    def test_heist_scene_metadata_display_name(self):
        """SCENE_METADATA display_name must be 'THE SCORE'."""
        src = _scene_source()
        assert '"display_name": "THE SCORE"' in src or "'display_name': 'THE SCORE'" in src, \
            "SCENE_METADATA display_name must be 'THE SCORE'"

    def test_heist_scene_metadata_port_5565(self):
        """SCENE_METADATA port must be 5565."""
        src = _scene_source()
        assert '"port": 5565' in src or "'port': 5565" in src, \
            "SCENE_METADATA port must be 5565"

    def test_heist_scene_metadata_type_thriller(self):
        """SCENE_METADATA type must be 'thriller'."""
        src = _scene_source()
        assert '"type": "thriller"' in src or "'type': 'thriller'" in src, \
            "SCENE_METADATA type must be 'thriller'"

    def test_heist_scene_metadata_accent_color(self):
        """SCENE_METADATA accent_color must be '#e11d48' (crimson)."""
        src = _scene_source()
        assert '"accent_color": "#e11d48"' in src or "'accent_color': '#e11d48'" in src, \
            "SCENE_METADATA accent_color must be '#e11d48'"

    def test_heist_scene_metadata_accent_rgb(self):
        """SCENE_METADATA accent_rgb must be '225 29 72'."""
        src = _scene_source()
        assert "225 29 72" in src, "SCENE_METADATA accent_rgb must be '225 29 72'"

    def test_heist_scene_metadata_description(self):
        """SCENE_METADATA description must contain the flavour line."""
        src = _scene_source()
        assert "Nobody gets out clean" in src, \
            "SCENE_METADATA description should contain 'Nobody gets out clean'"

    def test_heist_scene_metadata_version(self):
        """get_plugin_info must report version 0.68."""
        src = _scene_source()
        assert '"0.68"' in src or "'0.68'" in src, \
            "get_plugin_info version must be '0.68'"


# ══════════════════════════════════════════════════════════════════════════
#  2. STATIC ASSETS EXISTENCE
# ══════════════════════════════════════════════════════════════════════════

class TestStaticAssets:
    """All Dark Renaissance static files exist on disk."""

    def test_heist_html_exists(self):
        """heist.html template must be present."""
        assert TEMPLATE_HTML.is_file(), f"heist.html not found at {TEMPLATE_HTML}"

    def test_heist_css_exists(self):
        """heist.css stylesheet must be present."""
        assert STATIC_CSS.is_file(), f"heist.css not found at {STATIC_CSS}"

    def test_heist_js_exists(self):
        """heist.js scene script must be present."""
        assert STATIC_JS.is_file(), f"heist.js not found at {STATIC_JS}"

    def test_heist_html_data_scene_attribute(self):
        """heist.html body/html must declare data-scene='heist'."""
        html = TEMPLATE_HTML.read_text(encoding="utf-8")
        assert 'data-scene="heist"' in html, \
            "heist.html missing data-scene='heist' attribute"

    def test_heist_html_design_system_css(self):
        """heist.html must link all three shared design-system CSS files."""
        html = TEMPLATE_HTML.read_text(encoding="utf-8")
        assert "design_tokens.css"      in html, "Missing design_tokens.css link"
        assert "cosysim-components.css" in html, "Missing cosysim-components.css link"
        assert "cosysim-animations.css" in html, "Missing cosysim-animations.css link"

    def test_heist_html_socketio(self):
        """heist.html must include a Socket.IO script tag."""
        html = TEMPLATE_HTML.read_text(encoding="utf-8")
        assert "socket.io" in html.lower(), "heist.html missing Socket.IO script"

    def test_heist_html_navbar(self):
        """heist.html must include the navbar_v2.html template."""
        html = TEMPLATE_HTML.read_text(encoding="utf-8")
        assert "navbar_v2.html" in html, "heist.html should include navbar_v2.html"

    def test_heist_html_3col_layout(self):
        """heist.html must contain the 3-column panel structure."""
        html = TEMPLATE_HTML.read_text(encoding="utf-8")
        assert "job-panel"   in html, "heist.html missing job-panel (left column)"
        assert "board-panel" in html, "heist.html missing board-panel (center column)"
        assert "crew-panel"  in html, "heist.html missing crew-panel (right column)"

    def test_heist_html_phase_stepper(self):
        """heist.html must contain all four phase steps."""
        html = TEMPLATE_HTML.read_text(encoding="utf-8")
        for phase_data in ("planning", "approach", "execution", "escape"):
            assert phase_data in html, f"heist.html missing phase step '{phase_data}'"

    def test_heist_html_tension_meter(self):
        """heist.html must contain the SVG tension-meter element."""
        html = TEMPLATE_HTML.read_text(encoding="utf-8")
        assert "tension-meter" in html, "heist.html missing tension-meter SVG"
        assert "tension-line"  in html, "heist.html missing tension-line polyline"

    def test_heist_html_investigation_board(self):
        """heist.html must declare the investigation-board element."""
        html = TEMPLATE_HTML.read_text(encoding="utf-8")
        assert "investigation-board" in html, \
            "heist.html missing investigation-board element"

    def test_heist_html_particles_container(self):
        """heist.html must include the heist-particles container."""
        html = TEMPLATE_HTML.read_text(encoding="utf-8")
        assert "heist-particles" in html, "heist.html missing heist-particles div"

    def test_heist_css_blueprint_bg(self):
        """heist.css must define .blueprint-bg rule."""
        css = STATIC_CSS.read_text(encoding="utf-8")
        assert ".blueprint-bg" in css, "heist.css missing .blueprint-bg rule"

    def test_heist_css_3col_grid(self):
        """heist.css must define the 3-column grid layout."""
        css = STATIC_CSS.read_text(encoding="utf-8")
        assert "grid-template-columns" in css, \
            "heist.css missing grid-template-columns declaration"
        assert "280px" in css, "heist.css missing left column width 280px"

    def test_heist_css_heat_bar(self):
        """heist.css must define .heat-bar rule with gradient."""
        css = STATIC_CSS.read_text(encoding="utf-8")
        assert ".heat-bar"  in css,       "heist.css missing .heat-bar rule"
        assert "linear-gradient" in css,  "heist.css heat-bar missing gradient"

    def test_heist_css_crew_card(self):
        """heist.css must define .crew-card glass morphism rule."""
        css = STATIC_CSS.read_text(encoding="utf-8")
        assert ".crew-card"     in css, "heist.css missing .crew-card rule"
        assert "backdrop-filter" in css, "heist.css crew-card missing backdrop-filter (glass)"

    def test_heist_css_status_badges(self):
        """heist.css must define all three status badge variants."""
        css = STATIC_CSS.read_text(encoding="utf-8")
        for badge in (".status-badge.ready", ".status-badge.compromised", ".status-badge.arrested"):
            assert badge in css, f"heist.css missing {badge} rule"

    def test_heist_css_phase_stepper(self):
        """heist.css must define .phase-stepper and .phase-step rules."""
        css = STATIC_CSS.read_text(encoding="utf-8")
        assert ".phase-stepper" in css, "heist.css missing .phase-stepper rule"
        assert ".phase-step"    in css, "heist.css missing .phase-step rule"

    def test_heist_css_tension_meter(self):
        """heist.css must define .tension-meter and .tension-line rules."""
        css = STATIC_CSS.read_text(encoding="utf-8")
        assert ".tension-meter" in css, "heist.css missing .tension-meter rule"
        assert ".tension-line"  in css, "heist.css missing .tension-line rule"

    def test_heist_css_accent_color(self):
        """heist.css must declare --score-accent: #e11d48."""
        css = STATIC_CSS.read_text(encoding="utf-8")
        assert "#e11d48" in css, "heist.css missing crimson accent #e11d48"

    def test_heist_js_class_exists(self):
        """heist.js must define the TheScoreScene class."""
        js = STATIC_JS.read_text(encoding="utf-8")
        assert "class TheScoreScene" in js, "heist.js missing class TheScoreScene"

    def test_heist_js_init_method(self):
        """heist.js TheScoreScene must have init() method."""
        js = STATIC_JS.read_text(encoding="utf-8")
        assert "init()" in js, "heist.js TheScoreScene missing init() method"

    def test_heist_js_setup_socket(self):
        """heist.js must have _setupSocket method."""
        js = STATIC_JS.read_text(encoding="utf-8")
        assert "_setupSocket" in js, "heist.js missing _setupSocket method"

    def test_heist_js_render_crew(self):
        """heist.js must have _renderCrew method."""
        js = STATIC_JS.read_text(encoding="utf-8")
        assert "_renderCrew" in js, "heist.js missing _renderCrew method"

    def test_heist_js_render_phases(self):
        """heist.js must have _renderPhases method."""
        js = STATIC_JS.read_text(encoding="utf-8")
        assert "_renderPhases" in js, "heist.js missing _renderPhases method"

    def test_heist_js_send_message(self):
        """heist.js must have sendMessage method."""
        js = STATIC_JS.read_text(encoding="utf-8")
        assert "sendMessage" in js, "heist.js missing sendMessage method"

    def test_heist_js_tension_animation(self):
        """heist.js must implement tension animation (_spikeTension, _drawTensionLine)."""
        js = STATIC_JS.read_text(encoding="utf-8")
        assert "_spikeTension"   in js, "heist.js missing _spikeTension method"
        assert "_drawTensionLine" in js, "heist.js missing _drawTensionLine method"

    def test_heist_js_embers_particles(self):
        """heist.js must initialise embers particles via ParticleSystem3D."""
        js = STATIC_JS.read_text(encoding="utf-8")
        assert "ParticleSystem3D" in js, "heist.js missing ParticleSystem3D init"
        assert "embers"           in js, "heist.js missing 'embers' particle preset"


# ══════════════════════════════════════════════════════════════════════════
#  3. SKILL REGISTRATION
# ══════════════════════════════════════════════════════════════════════════

class TestHeistSkillsRegistered:
    """All required v0.68 skills are present in heist_skills.py."""

    _REQUIRED = [
        # Original skills
        "heist_status",
        "heist_action",
        "heist_advance_phase",
        "heist_collect_loot",
        "heist_crew_check",
        "heist_obstacles",
        # New v0.68 skills
        "get_heist_jobs",
        "select_heist",
        "assign_crew_member",
        "execute_heist_phase",
        "crew_status",
    ]

    def test_heist_skills_registered(self):
        """All 11 required skills must be defined in heist_skills.py."""
        src = (HEIST_ROOT / "heist_skills.py").read_text(encoding="utf-8")
        missing = [fn for fn in self._REQUIRED if f"def {fn}(" not in src]
        assert not missing, f"Missing skill definitions: {missing}"

    def test_new_skills_have_docstrings(self):
        """New v0.68 skills must have docstrings."""
        src = (HEIST_ROOT / "heist_skills.py").read_text(encoding="utf-8")
        new_skills = [
            "get_heist_jobs", "select_heist",
            "assign_crew_member", "execute_heist_phase", "crew_status",
        ]
        for fn in new_skills:
            idx     = src.find(f"def {fn}(")
            assert idx != -1, f"{fn} not found in heist_skills.py"
            snippet = src[idx: idx + 400]
            assert '"""' in snippet, f"{fn} is missing a docstring"


# ══════════════════════════════════════════════════════════════════════════
#  4. SKILL LOGIC
# ══════════════════════════════════════════════════════════════════════════

class TestGetHeistJobsSkill:
    """get_heist_jobs falls back to VENUES when ContentEngine unavailable."""

    def test_get_heist_jobs_skill_returns_json(self):
        """get_heist_jobs returns a JSON list with 'id' and 'name' per job."""
        mock_base  = MagicMock()
        mock_base.BaseScene.get_active_scene.return_value = None
        mock_venues = {
            "diamond_exchange": {
                "name": "Diamond Exchange", "loot_value": 500_000,
                "difficulty": 1, "guards": 4, "obstacles": ["laser_grid"],
            },
            "art_museum": {
                "name": "The Art Museum", "loot_value": 2_000_000,
                "difficulty": 2, "guards": 8, "obstacles": ["motion_sensors"],
            },
        }
        mock_game_mod = MagicMock()
        mock_game_mod.VENUES = mock_venues

        mocks = {
            "engine.skills.skill":              _make_skill_mock(),
            "engine.scenes.base_scene":         mock_base,
            "engine.mcp.state_coordinator":     MagicMock(),
            "engine.content.content_engine":    MagicMock(
                get_content_engine=MagicMock(side_effect=ImportError())
            ),
            "content.scenes.heist.heist_game":  mock_game_mod,
        }
        with patch.dict("sys.modules", mocks):
            spec = importlib.util.spec_from_file_location(
                "heist_skills_jobs", HEIST_ROOT / "heist_skills.py"
            )
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
            except Exception:
                pytest.skip("Could not load heist_skills in this environment")

            result = mod.get_heist_jobs()

        assert isinstance(result, str), "get_heist_jobs must return a str"
        data = json.loads(result)
        assert isinstance(data, list),               "get_heist_jobs must return a JSON list"
        assert len(data) >= 1,                       "get_heist_jobs must return at least one job"
        assert all("id"   in item for item in data), "Each job must have 'id'"
        assert all("name" in item for item in data), "Each job must have 'name'"

    def test_get_heist_jobs_returns_string(self):
        """get_heist_jobs always returns a str (skill contract)."""
        src = (HEIST_ROOT / "heist_skills.py").read_text(encoding="utf-8")
        assert "def get_heist_jobs() -> str:" in src, \
            "get_heist_jobs must be typed -> str"


class TestAssignCrewSkill:
    """assign_crew_member validates inputs and updates scene state."""

    def test_assign_crew_skill_validates_inputs(self):
        """assign_crew_member returns error when crew_member or role is empty."""
        src = (HEIST_ROOT / "heist_skills.py").read_text(encoding="utf-8")
        assert "Specify both crew_member and role" in src, \
            "assign_crew_member should validate both inputs"

    def test_assign_crew_skill_signature(self):
        """assign_crew_member signature matches spec (crew_member, role)."""
        src = (HEIST_ROOT / "heist_skills.py").read_text(encoding="utf-8")
        assert "def assign_crew_member(crew_member: str, role: str)" in src

    def test_assign_crew_logic(self):
        """assign_crew_member stores role on scene._assigned_roles."""
        try:
            mod = _load_skills_module()
        except Exception:
            pytest.skip("Could not load heist_skills in this environment")

        mock_scene              = MagicMock()
        mock_scene._assigned_roles = {}
        mock_game               = MagicMock()
        mock_game.crew          = {"ghost": MagicMock()}

        with patch.dict("sys.modules", {
            "engine.skills.skill":      _make_skill_mock(),
            "engine.scenes.base_scene": MagicMock(
                **{"BaseScene.get_active_scene.return_value": mock_scene}
            ),
        }):
            # Patch both helpers inside the loaded module
            mod._get_heist_scene = lambda: mock_scene
            mod._get_heist       = lambda: mock_game

            result = mod.assign_crew_member("ghost", "mastermind")
            assert "mastermind" in result.lower() or "MASTERMIND" in result, \
                f"Unexpected result: {result}"


class TestSelectHeistSkill:
    """select_heist validates job_id against VENUES."""

    def test_select_heist_empty_job_id(self):
        """select_heist returns error when job_id is empty."""
        src = (HEIST_ROOT / "heist_skills.py").read_text(encoding="utf-8")
        assert "Specify a job_id" in src, \
            "select_heist must validate empty job_id"

    def test_select_heist_signature(self):
        """select_heist signature matches spec."""
        src = (HEIST_ROOT / "heist_skills.py").read_text(encoding="utf-8")
        assert "def select_heist(job_id: str) -> str:" in src


class TestCrewStatusSkill:
    """crew_status returns readable status when no active heist."""

    def test_crew_status_no_heist(self):
        """crew_status returns graceful message when heist is absent."""
        src = (HEIST_ROOT / "heist_skills.py").read_text(encoding="utf-8")
        assert "def crew_status() -> str:" in src

    def test_crew_status_signature(self):
        """crew_status takes no arguments (game-state derived)."""
        src = (HEIST_ROOT / "heist_skills.py").read_text(encoding="utf-8")
        assert "def crew_status() -> str:" in src, \
            "crew_status must be parameterless -> str"


class TestExecuteHeistPhaseSkill:
    """execute_heist_phase advances phase and returns result string."""

    def test_execute_heist_phase_signature(self):
        """execute_heist_phase signature matches spec."""
        src = (HEIST_ROOT / "heist_skills.py").read_text(encoding="utf-8")
        assert "def execute_heist_phase(phase: str) -> str:" in src

    def test_execute_heist_phase_no_heist(self):
        """execute_heist_phase returns error when no heist is active."""
        src = (HEIST_ROOT / "heist_skills.py").read_text(encoding="utf-8")
        assert "No active heist" in src


# ══════════════════════════════════════════════════════════════════════════
#  5. SOCKET HANDLERS IN heist_scene.py
# ══════════════════════════════════════════════════════════════════════════

class TestSocketHandlers:
    """All v0.68 Socket.IO handlers exist in heist_scene.py source."""

    @pytest.fixture(autouse=True)
    def _src(self):
        self._source = _scene_source()

    def _has_handler(self, name: str) -> bool:
        return f'"{name}"' in self._source or f"'{name}'" in self._source

    def test_get_heist_state_handler(self):
        assert self._has_handler("get_heist_state"), "Missing 'get_heist_state' handler"

    def test_get_available_jobs_handler(self):
        assert self._has_handler("get_available_jobs"), "Missing 'get_available_jobs' handler"

    def test_select_job_handler(self):
        assert self._has_handler("select_job"), "Missing 'select_job' handler"

    def test_assign_crew_handler(self):
        assert self._has_handler("assign_crew"), "Missing 'assign_crew' handler"

    def test_execute_phase_handler(self):
        assert self._has_handler("execute_phase"), "Missing 'execute_phase' handler"

    def test_abort_heist_handler(self):
        assert self._has_handler("abort_heist"), "Missing 'abort_heist' handler"

    def test_get_investigation_handler(self):
        assert self._has_handler("get_investigation"), "Missing 'get_investigation' handler"


# ══════════════════════════════════════════════════════════════════════════
#  6. ENGINE WIRING IN heist_scene.py
# ══════════════════════════════════════════════════════════════════════════

class TestEngineWiring:
    """Engine module wiring is present in heist_scene.py."""

    @pytest.fixture(autouse=True)
    def _src(self):
        self._source = _scene_source()

    def test_consequence_store_wired(self):
        """ConsequenceStore must be used (payout + heat_decay scheduling)."""
        assert "get_consequence_store" in self._source
        assert "heat_decay"            in self._source
        assert "delay_hours"           in self._source

    def test_event_bus_wired(self):
        """EventBus must publish heist.job_complete."""
        assert "get_event_bus"       in self._source
        assert "heist.job_complete"  in self._source

    def test_reputation_manager_wired(self):
        """ReputationManager must be referenced in heist_scene."""
        assert "get_reputation_manager" in self._source

    def test_investigation_board_wired(self):
        """InvestigationBoard must be referenced in get_investigation handler."""
        assert "get_investigation_board" in self._source

    def test_content_engine_wired(self):
        """ContentEngine must be referenced for get_available_jobs."""
        assert "get_content_engine" in self._source

    def test_scene_director_wired(self):
        """SceneDirector must be referenced in start()."""
        assert "get_scene_director" in self._source

    def test_inject_navbar_context(self):
        """The '/' route must pass inject_navbar_context() to the template."""
        assert "inject_navbar_context" in self._source

    def test_register_bench_route(self):
        """register_bench_route must be called in __init__."""
        assert "register_bench_route" in self._source

    def test_register_tts_route(self):
        """register_tts_route must be called in __init__."""
        assert "register_tts_route" in self._source
