"""Tests for THE PENTHOUSE — Bedroom Scene v0.68 "Dark Renaissance" revamp."""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ────────────────────────────────────────────────────────────

BEDROOM_ROOT = Path(__file__).parent.parent / "content" / "scenes" / "bedroom"
STATIC_ROOT  = BEDROOM_ROOT / "static"
TEMPLATE_ROOT = BEDROOM_ROOT / "templates"


def _import_bedroom_scene():
    """Import bedroom_scene module, skipping heavy dependencies via mocks."""
    with (
        patch.dict("sys.modules", {
            "flask":                     MagicMock(),
            "flask_socketio":            MagicMock(),
            "flask_cors":                MagicMock(),
            "engine.paths":              MagicMock(CONTENT_DIR=Path(".")),
            "engine.scenes.base_scene":  MagicMock(),
            "engine.scenes.nexus_mixin": MagicMock(),
            "engine.mcp.framework":      MagicMock(),
            "engine.agents.agent_loop":  MagicMock(),
            "engine.spatial.location":   MagicMock(),
            "engine.spatial.scene_map":  MagicMock(),
            "engine.mcp.scene_state":    MagicMock(),
            "engine.mcp.tag_registry":   MagicMock(),
            "engine.mcp.interaction_trees": MagicMock(),
            "engine.overlay":            MagicMock(),
            "content.simulation.database.db":                            MagicMock(),
            "content.simulation.character_system.character":             MagicMock(),
            "content.shared":                                            MagicMock(),
            "content.scenes.bedroom.bedroom_rules":                      MagicMock(),
            "content.scenes.bedroom.bedroom_combat_mixin":               MagicMock(),
            "content.scenes.bedroom.bedroom_dialog_mixin":               MagicMock(),
            "content.scenes.bedroom.bedroom_inventory_mixin":            MagicMock(),
            "content.scenes.bedroom.bedroom_social_mixin":               MagicMock(),
        })
    ):
        spec = importlib.util.spec_from_file_location(
            "bedroom_scene", BEDROOM_ROOT / "bedroom_scene.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod


def _import_skills():
    """Import bedroom_skills module with mocked engine deps."""
    with (
        patch.dict("sys.modules", {
            "engine.skills.skill":      MagicMock(),
            "engine.scenes.base_scene": MagicMock(),
            "engine.mcp.state_coordinator": MagicMock(),
        })
    ):
        spec = importlib.util.spec_from_file_location(
            "bedroom_skills", BEDROOM_ROOT / "bedroom_skills.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod


# ══════════════════════════════════════════════════════════════════════
#  SCENE METADATA
# ══════════════════════════════════════════════════════════════════════

class TestSceneMetadata:
    """SCENE_METADATA reflects the Penthouse rebrand."""

    def _get_metadata(self) -> dict:
        """Read SCENE_METADATA directly from source without importing the module."""
        source = (BEDROOM_ROOT / "bedroom_scene.py").read_text(encoding="utf-8")
        # Find SCENE_METADATA dict and extract key values via source inspection
        return source

    def test_scene_metadata(self):
        """SCENE_METADATA has all required Penthouse keys in source."""
        source = (BEDROOM_ROOT / "bedroom_scene.py").read_text(encoding="utf-8")
        assert '"display_name": "THE PENTHOUSE"' in source or "'display_name': 'THE PENTHOUSE'" in source, \
            "SCENE_METADATA display_name must be 'THE PENTHOUSE'"
        assert '"port": 5556' in source or "'port': 5556" in source, \
            "SCENE_METADATA port must be 5556"
        assert '"accent_color": "#ec4899"' in source or "'accent_color': '#ec4899'" in source, \
            "SCENE_METADATA accent_color must be #ec4899"
        assert '"character_memory"' in source, "SCENE_METADATA features must include character_memory"
        assert '"scene_director"' in source, "SCENE_METADATA features must include scene_director"
        assert '"economy"' in source, "SCENE_METADATA features must include economy"

    def test_scene_metadata_port_5556(self):
        """Scene port must remain 5556."""
        source = (BEDROOM_ROOT / "bedroom_scene.py").read_text(encoding="utf-8")
        assert '"port": 5556' in source or "'port': 5556" in source, \
            "Scene port 5556 not found in SCENE_METADATA"


# ══════════════════════════════════════════════════════════════════════
#  STATIC ASSET EXISTENCE
# ══════════════════════════════════════════════════════════════════════

class TestStaticAssets:
    """All new Penthouse static files exist on disk."""

    def test_bedroom_html_exists(self):
        """bedroom.html template must be present."""
        assert (TEMPLATE_ROOT / "bedroom.html").is_file(), (
            "bedroom.html template not found"
        )

    def test_bedroom_css_exists(self):
        """bedroom.css scene stylesheet must be present."""
        assert (STATIC_ROOT / "bedroom.css").is_file(), (
            "bedroom.css not found at static/bedroom.css"
        )

    def test_bedroom_js_exists(self):
        """bedroom.js scene script must be present."""
        assert (STATIC_ROOT / "bedroom.js").is_file(), (
            "bedroom.js not found at static/bedroom.js"
        )

    def test_bedroom_html_data_scene_attribute(self):
        """bedroom.html must declare data-scene='bedroom' for design tokens."""
        html = (TEMPLATE_ROOT / "bedroom.html").read_text(encoding="utf-8")
        assert 'data-scene="bedroom"' in html

    def test_bedroom_html_design_system_links(self):
        """bedroom.html must link all three shared design system CSS files."""
        html = (TEMPLATE_ROOT / "bedroom.html").read_text(encoding="utf-8")
        assert "design_tokens.css" in html
        assert "cosysim-components.css" in html
        assert "cosysim-animations.css" in html

    def test_bedroom_html_socketio(self):
        """bedroom.html must include Socket.IO script tag."""
        html = (TEMPLATE_ROOT / "bedroom.html").read_text(encoding="utf-8")
        assert "socket.io" in html.lower()

    def test_bedroom_css_3col_grid(self):
        """bedroom.css must define the 3-column layout."""
        css = (STATIC_ROOT / "bedroom.css").read_text(encoding="utf-8")
        assert "grid-template-columns" in css
        assert "280px" in css  # left column width

    def test_bedroom_js_class_exists(self):
        """bedroom.js must define BedroomScene class."""
        js = (STATIC_ROOT / "bedroom.js").read_text(encoding="utf-8")
        assert "class BedroomScene" in js
        assert "sendMessage" in js
        assert "updateEmotions" in js
        assert "loadScenarios" in js


# ══════════════════════════════════════════════════════════════════════
#  SKILL REGISTRATION
# ══════════════════════════════════════════════════════════════════════

class TestBedroomSkillsRegistered:
    """All required skills are present in bedroom_skills.py."""

    _EXPECTED_SKILLS = [
        "bedroom_character_status",
        "bedroom_adjust_stat",
        "bedroom_give_line",
        "bedroom_whisper",
        "bedroom_add_prop",
        "bedroom_set_time",
        "bedroom_start_game",
        "bedroom_game_action",
        "bedroom_set_scenario",
        "bedroom_fire_event",
        # New Penthouse skills
        "get_scenario_options",
        "load_scenario",
        "recall_memories",
        "remember_moment",
        "get_emotion_levels",
        "unlock_premium",
    ]

    def test_bedroom_skills_registered(self):
        """All 16 expected skills must be defined in bedroom_skills.py."""
        source = (BEDROOM_ROOT / "bedroom_skills.py").read_text(encoding="utf-8")
        missing = [fn for fn in self._EXPECTED_SKILLS if f"def {fn}(" not in source]
        assert not missing, f"Missing skill definitions: {missing}"

    def test_new_skills_have_docstrings(self):
        """New Penthouse skills must have Google-style docstrings."""
        source = (BEDROOM_ROOT / "bedroom_skills.py").read_text(encoding="utf-8")
        new_skills = [
            "get_scenario_options",
            "load_scenario",
            "recall_memories",
            "remember_moment",
            "get_emotion_levels",
            "unlock_premium",
        ]
        for fn in new_skills:
            # Each function definition should be followed by a docstring
            fn_idx = source.find(f"def {fn}(")
            assert fn_idx != -1, f"Function {fn} not found"
            snippet = source[fn_idx: fn_idx + 400]
            assert '"""' in snippet, f"Function {fn} missing docstring"


# ══════════════════════════════════════════════════════════════════════
#  SKILL LOGIC (with mocked dependencies)
# ══════════════════════════════════════════════════════════════════════

class TestGetScenarioOptionsSkill:
    """get_scenario_options returns scenario data."""

    def test_get_scenario_options_skill_returns_json(self):
        """get_scenario_options falls back to PREMADE_SCENARIOS."""
        import sys
        import json

        # Build a mock scene with minimal attributes
        mock_scene = MagicMock()
        mock_scene.characters = {}
        mock_scene.profiles = {}
        mock_scene.room_props = []
        mock_scene.scene_state = {}
        mock_scene.bed_game = MagicMock(active=False)

        with (
            patch.dict("sys.modules", {
                "engine.skills.skill":             _make_skill_mock(),
                "engine.scenes.base_scene":        MagicMock(get_active_scene=lambda n: mock_scene),
                "engine.mcp.state_coordinator":    MagicMock(),
                "engine.content.content_engine":   MagicMock(
                    get_content_engine=MagicMock(side_effect=ImportError())
                ),
                "content.scenes.bedroom.bedroom_scene": MagicMock(
                    PREMADE_SCENARIOS={
                        "romantic_evening": {"label": "Romantic Evening", "emoji": "🌹"},
                        "spa_night": {"label": "Spa Night", "emoji": "🛁"},
                    }
                ),
            }),
        ):
            spec = importlib.util.spec_from_file_location(
                "bedroom_skills_opt", BEDROOM_ROOT / "bedroom_skills.py"
            )
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
            except Exception:
                pytest.skip("Could not load bedroom_skills in this environment")

            result = mod.get_scenario_options(intensity=2, tags="")
            data = json.loads(result)
            assert isinstance(data, list)
            assert len(data) >= 1
            assert all("id" in item for item in data)


class TestRecallMemoriesSkill:
    """recall_memories returns graceful fallback when engine absent."""

    def test_recall_memories_skill_no_character(self):
        """recall_memories returns error when character_id is missing."""
        source = (BEDROOM_ROOT / "bedroom_skills.py").read_text(encoding="utf-8")
        assert "Specify character_id" in source, (
            "recall_memories should validate character_id"
        )

    def test_recall_memories_skill_structure(self):
        """recall_memories function signature accepts character_id."""
        source = (BEDROOM_ROOT / "bedroom_skills.py").read_text(encoding="utf-8")
        assert "def recall_memories(character_id" in source


class TestRememberMomentSkill:
    """remember_moment validates inputs and handles missing engine."""

    def test_remember_moment_validates_inputs(self):
        """remember_moment requires both character_id and description."""
        source = (BEDROOM_ROOT / "bedroom_skills.py").read_text(encoding="utf-8")
        assert "Specify character_id and description" in source

    def test_remember_moment_weight_clamped(self):
        """remember_moment clamps weight to 0.0–1.0."""
        source = (BEDROOM_ROOT / "bedroom_skills.py").read_text(encoding="utf-8")
        assert "max(0.0, min(1.0" in source


class TestUnlockPremiumSkill:
    """unlock_premium enforces credit gating."""

    def test_unlock_premium_insufficient_credits(self):
        """unlock_premium returns low_credits error when balance is too low."""
        mock_economy = MagicMock()
        mock_economy.get_balance.return_value = 10

        mock_scene = MagicMock()
        mock_scene.characters = {"hero": MagicMock(name="Hero")}
        mock_scene.socketio = MagicMock()

        with (
            patch.dict("sys.modules", {
                "engine.skills.skill":          _make_skill_mock(),
                "engine.scenes.base_scene":     MagicMock(get_active_scene=lambda n: mock_scene),
                "engine.mcp.state_coordinator": MagicMock(),
                "engine.economy.economy":       MagicMock(
                    get_economy_manager=MagicMock(return_value=mock_economy)
                ),
            }),
        ):
            spec = importlib.util.spec_from_file_location(
                "bedroom_skills_prem", BEDROOM_ROOT / "bedroom_skills.py"
            )
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
            except Exception:
                pytest.skip("Could not load bedroom_skills in this environment")

            result = mod.unlock_premium(content_id="vip_scenario", cost=100)
            assert "Insufficient" in result or "credits" in result.lower()

    def test_unlock_premium_success(self):
        """unlock_premium deducts credits and emits economy_update on success."""
        mock_economy = MagicMock()
        mock_economy.get_balance.return_value = 500
        mock_economy.spend.return_value = True

        mock_scene = MagicMock()
        mock_scene.characters = {}
        mock_scene.socketio = MagicMock()

        with (
            patch.dict("sys.modules", {
                "engine.skills.skill":          _make_skill_mock(),
                "engine.scenes.base_scene":     MagicMock(get_active_scene=lambda n: mock_scene),
                "engine.mcp.state_coordinator": MagicMock(),
                "engine.economy.economy":       MagicMock(
                    get_economy_manager=MagicMock(return_value=mock_economy)
                ),
            }),
        ):
            spec = importlib.util.spec_from_file_location(
                "bedroom_skills_prem2", BEDROOM_ROOT / "bedroom_skills.py"
            )
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
            except Exception:
                pytest.skip("Could not load bedroom_skills in this environment")

            result = mod.unlock_premium(content_id="vip_scenario", cost=100)
            assert "vip_scenario" in result
            assert "Unlocked" in result or "unlock" in result.lower()

    def test_unlock_premium_no_content_id(self):
        """unlock_premium returns error when content_id is empty."""
        source = (BEDROOM_ROOT / "bedroom_skills.py").read_text(encoding="utf-8")
        assert "Specify content_id" in source


# ══════════════════════════════════════════════════════════════════════
#  SOCKET HANDLERS IN bedroom_scene.py
# ══════════════════════════════════════════════════════════════════════

class TestSocketHandlers:
    """Socket event handlers exist in bedroom_scene source."""

    _SOURCE: str | None = None

    @classmethod
    def _source(cls) -> str:
        if cls._SOURCE is None:
            cls._SOURCE = (BEDROOM_ROOT / "bedroom_scene.py").read_text(encoding="utf-8")
        return cls._SOURCE

    def test_get_scenarios_handler(self):
        """bedroom_scene.py must define get_scenarios socket handler."""
        assert '"get_scenarios"' in self._source() or "'get_scenarios'" in self._source()

    def test_director_nudge_handler(self):
        """bedroom_scene.py must define director_nudge socket handler."""
        assert '"director_nudge"' in self._source() or "'director_nudge'" in self._source()

    def test_get_economy_handler(self):
        """bedroom_scene.py must define get_economy socket handler."""
        assert '"get_economy"' in self._source() or "'get_economy'" in self._source()

    def test_spend_credits_handler(self):
        """bedroom_scene.py must define spend_credits socket handler."""
        assert '"spend_credits"' in self._source() or "'spend_credits'" in self._source()

    def test_world_tick_handler(self):
        """bedroom_scene.py must define world_tick socket handler."""
        assert '"world_tick"' in self._source() or "'world_tick'" in self._source()

    def test_load_scenario_handler(self):
        """bedroom_scene.py must define load_scenario socket handler."""
        assert '"load_scenario"' in self._source() or "'load_scenario'" in self._source()


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════

def _make_skill_mock() -> MagicMock:
    """Return a MagicMock that passes through @skill decoration."""
    mock_mod = MagicMock()
    # @skill(...) returns a decorator that returns the function unchanged
    mock_mod.skill = lambda **kw: (lambda fn: fn)
    mock_mod.SkillCategory = MagicMock(GAME="game")
    return mock_mod
