"""Phase 2 Integration Tests — Unified Neon Base Template System.

Validates:
1. neon_base.html exists and has all required blocks/assets
2. All 17 scene templates extend neon_base.html correctly
3. neon_base.css and neon_base.js exist with required features
4. ChoiceLoader wiring in register_shared_assets()
5. Scene lifecycle compliance (route registration)
6. No duplicate asset loading in child templates
"""

import importlib
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent

# ── Asset paths ────────────────────────────────────────────────────────────

NEON_BASE_HTML = ROOT / "content" / "shared" / "templates" / "neon_base.html"
NEON_BASE_CSS = ROOT / "content" / "shared" / "static" / "css" / "neon_base.css"
NEON_BASE_JS = ROOT / "content" / "shared" / "static" / "js" / "neon_base.js"

ALL_SCENE_TEMPLATES = {
    "arena": ROOT / "content/scenes/arena/templates/arena.html",
    "penthouse": ROOT / "content/scenes/penthouse/templates/penthouse.html",
    "casino": ROOT / "content/scenes/casino/templates/casino.html",
    "coders": ROOT / "content/scenes/coders/templates/coders.html",
    "command_center": ROOT / "content/scenes/command_center/templates/command_center.html",
    "gallery": ROOT / "content/scenes/gallery/templates/gallery.html",
    "games": ROOT / "content/scenes/games/templates/games.html",
    "grid": ROOT / "content/scenes/grid/templates/grid.html",
    "heist": ROOT / "content/scenes/heist/templates/heist.html",
    "intel_hub": ROOT / "content/scenes/intel_hub/templates/intel_hub.html",
    "lab_break": ROOT / "content/scenes/lab_break/templates/lab_break.html",
    "lounge": ROOT / "content/scenes/lounge/templates/lounge.html",
    "neoncity": ROOT / "content/scenes/neoncity/templates/neoncity.html",
    "realm": ROOT / "content/scenes/realm/templates/realm.html",
    "system_control": ROOT / "content/scenes/system_control/templates/system_control_ui.html",
    "tavern": ROOT / "content/scenes/tavern/templates/tavern.html",
    "asset_studio": ROOT / "content/scenes/asset_studio/templates/asset_studio.html",
}

EXPECTED_SCENE_ACCENTS = {
    "penthouse": "#f43f5e",
    "lounge": "#f43f5e",
    "tavern": "#f97316",
    "casino": "#eab308",
    "gallery": "#a855f7",
    "arena": "#dc2626",
    "realm": "#6366f1",
    "neoncity": "#06b6d4",
    "coders": "#06b6d4",
    "heist": "#f59e0b",
    "command_center": "#14b8a6",
    "games": "#f43f5e",
    "asset_studio": "#a855f7",
    "grid": "#22d3ee",
    "lab_break": "#00ff88",
    "intel_hub": "#8b5cf6",
    "system_control": "#14b8a6",
}

SCENE_CLASSES = {
    "arena": ("content.scenes.arena", "ArenaScene"),
    "penthouse": ("content.scenes.penthouse.penthouse_scene", "PenthouseScene"),
    "casino": ("content.scenes.casino.casino_scene", "CasinoScene"),
    "coders": ("content.scenes.coders.coders_scene", "CodersScene"),
    "command_center": ("content.scenes.command_center.command_center_scene", "CommandCenterScene"),
    "gallery": ("content.scenes.gallery.gallery_scene", "GalleryScene"),
    "games": ("content.scenes.games.games_scene", "GamesScene"),
    "grid": ("content.scenes.grid.grid_scene", "GridScene"),
    "heist": ("content.scenes.heist.heist_scene", "HeistScene"),
    "intel_hub": ("content.scenes.intel_hub.intel_hub_scene", "IntelHubScene"),
    "lab_break": ("content.scenes.lab_break.lab_break_scene", "LabBreakScene"),
    "lounge": ("content.scenes.lounge.lounge_scene", "LoungeScene"),
    "neoncity": ("content.scenes.neoncity.neoncity_scene", "NeonCityScene"),
    "realm": ("content.scenes.realm.realm_scene", "RealmScene"),
    "system_control": ("content.scenes.system_control.system_control_scene", "SystemControlScene"),
    "tavern": ("content.scenes.tavern.tavern_scene", "TavernScene"),
    "asset_studio": ("content.scenes.asset_studio.asset_studio_scene", "AssetStudioScene"),
}


# ═══════════════════════════════════════════════════════════════════════════
# 1. neon_base.html — Base Template Existence & Structure
# ═══════════════════════════════════════════════════════════════════════════


class TestNeonBaseHTML:
    """Tests for the unified base template."""

    @pytest.fixture(autouse=True)
    def load_base(self):
        self.content = NEON_BASE_HTML.read_text(encoding="utf-8")

    def test_base_template_exists(self):
        assert NEON_BASE_HTML.exists()

    def test_has_doctype(self):
        assert "<!DOCTYPE html>" in self.content

    def test_has_html_lang(self):
        assert '<html lang="en"' in self.content

    def test_has_data_scene_attribute(self):
        assert 'data-scene="{{ scene_key }}"' in self.content

    # ── Required CSS assets ────────────────────────────────────────────

    def test_loads_design_tokens(self):
        assert "design_tokens.css" in self.content

    def test_loads_components_css(self):
        assert "cosysim-components.css" in self.content

    def test_loads_animations_css(self):
        assert "cosysim-animations.css" in self.content

    def test_loads_scene_fx_css(self):
        assert "cosysim-scene-fx.css" in self.content

    def test_loads_scene_css(self):
        assert "cosysim-scene.css" in self.content

    def test_loads_neon_base_css(self):
        assert "neon_base.css" in self.content

    # ── Required JS assets ─────────────────────────────────────────────

    def test_loads_socket_io(self):
        assert "socket.io.min.js" in self.content

    def test_loads_core_js(self):
        assert "cosysim-core.js" in self.content

    def test_loads_stream_js(self):
        assert "cosysim-stream.js" in self.content

    def test_loads_neon_hud_js(self):
        assert "cosysim-neon-hud.js" in self.content

    def test_loads_neon_base_js(self):
        assert "neon_base.js" in self.content

    def test_loads_particles_js(self):
        assert "cosysim-particles.js" in self.content

    # ── Required includes ──────────────────────────────────────────────

    def test_includes_navbar(self):
        assert "navbar_v2.html" in self.content

    def test_includes_aria_widget(self):
        assert "aria_widget.html" in self.content

    # ── Required blocks ────────────────────────────────────────────────

    REQUIRED_BLOCKS = [
        "head_meta", "head_css", "head_style", "head_scripts",
        "scene_header", "scene_content", "scene_sidebar",
        "scene_footer", "scene_overlays", "body_scripts",
    ]

    @pytest.mark.parametrize("block", REQUIRED_BLOCKS)
    def test_has_block(self, block):
        assert f"{{% block {block} %}}" in self.content

    # ── Visual elements ────────────────────────────────────────────────

    def test_has_scanlines_overlay(self):
        assert "neon-scanlines" in self.content

    def test_has_particle_canvas(self):
        assert "cs-particles" in self.content

    def test_has_neon_grid_bg(self):
        assert "neon-grid-bg" in self.content

    def test_has_neon_body_class(self):
        assert 'class="neon-body"' in self.content

    def test_has_neon_main(self):
        assert 'class="neon-main"' in self.content

    # ── Scene accent injection ─────────────────────────────────────────

    def test_injects_scene_accent_css_var(self):
        assert "--scene-accent:" in self.content

    def test_injects_scene_accent_rgb_css_var(self):
        assert "--scene-accent-rgb:" in self.content

    def test_injects_scene_accent_glow(self):
        assert "--scene-accent-glow:" in self.content

    # ── Default variable fallbacks ─────────────────────────────────────

    def test_default_scene_key(self):
        assert "default('neoncity')" in self.content

    def test_default_scene_accent(self):
        assert "default('#00e5ff')" in self.content

    def test_particle_opt_out(self):
        assert "hide_particles" in self.content


# ═══════════════════════════════════════════════════════════════════════════
# 2. neon_base.css — Visual System
# ═══════════════════════════════════════════════════════════════════════════


class TestNeonBaseCSS:
    """Tests for the neon visual system CSS."""

    @pytest.fixture(autouse=True)
    def load_css(self):
        self.content = NEON_BASE_CSS.read_text(encoding="utf-8")

    def test_css_exists(self):
        assert NEON_BASE_CSS.exists()

    def test_has_neon_grid_bg(self):
        assert ".neon-grid-bg" in self.content

    def test_has_scanlines(self):
        assert ".neon-scanlines" in self.content

    def test_has_neon_panel(self):
        assert ".neon-panel" in self.content

    def test_has_neon_body(self):
        assert ".neon-body" in self.content

    def test_has_neon_main(self):
        assert ".neon-main" in self.content

    def test_has_neon_btn(self):
        assert ".neon-btn" in self.content

    def test_has_chat_components(self):
        assert ".neon-chat" in self.content or ".chat-" in self.content

    def test_has_stat_bars(self):
        assert "stat-bar" in self.content or "neon-stat" in self.content

    def test_has_responsive_breakpoints(self):
        assert "@media" in self.content

    def test_has_reduced_motion_support(self):
        assert "prefers-reduced-motion" in self.content

    def test_has_keyframe_animations(self):
        assert "@keyframes" in self.content

    def test_references_scene_accent(self):
        assert "var(--scene-accent" in self.content


# ═══════════════════════════════════════════════════════════════════════════
# 3. neon_base.js — Client-Side System
# ═══════════════════════════════════════════════════════════════════════════


class TestNeonBaseJS:
    """Tests for the neon base JavaScript."""

    @pytest.fixture(autouse=True)
    def load_js(self):
        self.content = NEON_BASE_JS.read_text(encoding="utf-8")

    def test_js_exists(self):
        assert NEON_BASE_JS.exists()

    def test_has_socket_io_connect(self):
        assert "io(" in self.content or "socket" in self.content.lower()

    def test_exposes_window_neonbase(self):
        assert "window.NeonBase" in self.content or "NeonBase" in self.content

    def test_has_keyboard_shortcuts(self):
        assert "keydown" in self.content or "Escape" in self.content

    def test_has_console_branding(self):
        assert "console" in self.content


# ═══════════════════════════════════════════════════════════════════════════
# 4. Scene Template Conversion — All 17 Scenes
# ═══════════════════════════════════════════════════════════════════════════


class TestSceneTemplateConversion:
    """Verify all 17 scenes properly extend neon_base.html."""

    def test_all_17_templates_exist(self):
        missing = [n for n, p in ALL_SCENE_TEMPLATES.items() if not p.exists()]
        assert not missing, f"Missing scene templates: {missing}"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_extends_neon_base(self, scene_name):
        """Every scene template must extend neon_base.html."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert "extends 'neon_base.html'" in content or 'extends "neon_base.html"' in content, \
            f"{scene_name} template does not extend neon_base.html"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_sets_scene_key(self, scene_name):
        """Every scene template must set scene_key."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert re.search(r"{%\s*set\s+scene_key\s*=", content), \
            f"{scene_name} does not set scene_key"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_sets_scene_display_name(self, scene_name):
        """Every scene template must set scene_display_name."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert re.search(r"{%\s*set\s+scene_display_name\s*=", content), \
            f"{scene_name} does not set scene_display_name"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_sets_scene_accent(self, scene_name):
        """Every scene template must set scene_accent color."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert re.search(r"{%\s*set\s+scene_accent\s*=", content), \
            f"{scene_name} does not set scene_accent"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_sets_scene_accent_rgb(self, scene_name):
        """Every scene template must set scene_accent_rgb."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert re.search(r"{%\s*set\s+scene_accent_rgb\s*=", content), \
            f"{scene_name} does not set scene_accent_rgb"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_has_scene_content_block(self, scene_name):
        """Every scene template must define a scene_content block."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert re.search(r"{%\s*block\s+scene_content\s*%}", content), \
            f"{scene_name} does not define scene_content block"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_accent_matches_expected(self, scene_name):
        """Each scene accent must match the expected value."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        expected = EXPECTED_SCENE_ACCENTS.get(scene_name)
        if expected:
            assert expected in content, \
                f"{scene_name} accent mismatch: expected {expected}"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_no_duplicate_doctype(self, scene_name):
        """Child templates must NOT have their own <!DOCTYPE>."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert "<!DOCTYPE" not in content, \
            f"{scene_name} has duplicate <!DOCTYPE> (should come from neon_base.html)"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_no_duplicate_html_tag(self, scene_name):
        """Child templates must NOT have their own <html> tag."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert "<html" not in content, \
            f"{scene_name} has duplicate <html> tag (should come from neon_base.html)"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_no_duplicate_socket_io(self, scene_name):
        """Child templates must NOT load socket.io.min.js (base does it)."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert "socket.io.min.js" not in content, \
            f"{scene_name} loads socket.io.min.js (already in neon_base.html)"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_no_duplicate_core_js(self, scene_name):
        """Child templates must NOT load cosysim-core.js (base does it)."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert "cosysim-core.js" not in content, \
            f"{scene_name} loads cosysim-core.js (already in neon_base.html)"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_no_duplicate_design_tokens(self, scene_name):
        """Child templates must NOT load design_tokens.css (base does it)."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert "design_tokens.css" not in content, \
            f"{scene_name} loads design_tokens.css (already in neon_base.html)"

    @pytest.mark.parametrize("scene_name", ALL_SCENE_TEMPLATES.keys())
    def test_no_duplicate_navbar_include(self, scene_name):
        """Child templates must NOT include navbar_v2.html (base does it)."""
        content = ALL_SCENE_TEMPLATES[scene_name].read_text(encoding="utf-8")
        assert "navbar_v2" not in content, \
            f"{scene_name} includes navbar_v2 (already in neon_base.html)"

    def test_bedroom_has_threejs_in_head_scripts(self):
        """Bedroom must use head_scripts block for Three.js CDN."""
        content = ALL_SCENE_TEMPLATES["penthouse"].read_text(encoding="utf-8")
        assert "head_scripts" in content
        assert "three.min.js" in content or "three.js" in content


# ═══════════════════════════════════════════════════════════════════════════
# 5. ChoiceLoader Integration — Shared Templates Resolution
# ═══════════════════════════════════════════════════════════════════════════


class TestChoiceLoader:
    """Verify register_shared_assets() sets up ChoiceLoader for neon_base.html."""

    def test_shared_init_has_choice_loader_code(self):
        """content/shared/__init__.py must reference ChoiceLoader."""
        init_path = ROOT / "content" / "shared" / "__init__.py"
        content = init_path.read_text(encoding="utf-8")
        assert "ChoiceLoader" in content

    def test_shared_init_adds_templates_dir(self):
        """register_shared_assets must add the shared templates directory."""
        init_path = ROOT / "content" / "shared" / "__init__.py"
        content = init_path.read_text(encoding="utf-8")
        assert "templates" in content
        assert "FileSystemLoader" in content or "jinja2" in content

    def test_flask_app_resolves_neon_base(self):
        """A Flask app with register_shared_assets can resolve neon_base.html."""
        try:
            from flask import Flask
        except ImportError:
            pytest.skip("Flask not installed")

        app = Flask(
            __name__,
            template_folder=str(ROOT / "content" / "scenes" / "arena" / "templates"),
        )

        from content.shared import register_shared_assets
        register_shared_assets(app)

        with app.app_context():
            env = app.jinja_env
            tmpl = env.get_template("neon_base.html")
            assert tmpl is not None

    def test_flask_app_resolves_child_via_extends(self):
        """A Flask app can resolve a child template that extends neon_base.html."""
        try:
            from flask import Flask
        except ImportError:
            pytest.skip("Flask not installed")

        app = Flask(
            __name__,
            template_folder=str(ROOT / "content" / "scenes" / "arena" / "templates"),
        )

        from content.shared import register_shared_assets
        register_shared_assets(app)

        with app.app_context():
            env = app.jinja_env
            tmpl = env.get_template("arena.html")
            assert tmpl is not None


# ═══════════════════════════════════════════════════════════════════════════
# 6. Scene Lifecycle Compliance
# ═══════════════════════════════════════════════════════════════════════════


class TestSceneLifecycle:
    """Verify all scene classes register required routes."""

    SCENE_PY_FILES = {
        "arena": ROOT / "content/scenes/arena/__init__.py",
        "penthouse": ROOT / "content/scenes/penthouse/penthouse_scene.py",
        "casino": ROOT / "content/scenes/casino/casino_scene.py",
        "coders": ROOT / "content/scenes/coders/coders_scene.py",
        "command_center": ROOT / "content/scenes/command_center/command_center_scene.py",
        "gallery": ROOT / "content/scenes/gallery/gallery_scene.py",
        "games": ROOT / "content/scenes/games/games_scene.py",
        "grid": ROOT / "content/scenes/grid/grid_scene.py",
        "heist": ROOT / "content/scenes/heist/heist_scene.py",
        "intel_hub": ROOT / "content/scenes/intel_hub/intel_hub_scene.py",
        "lab_break": ROOT / "content/scenes/lab_break/lab_break_scene.py",
        "lounge": ROOT / "content/scenes/lounge/lounge_scene.py",
        "neoncity": ROOT / "content/scenes/neoncity/neoncity_scene.py",
        "realm": ROOT / "content/scenes/realm/realm_scene.py",
        "system_control": ROOT / "content/scenes/system_control/system_control_scene.py",
        "tavern": ROOT / "content/scenes/tavern/tavern_scene.py",
        "asset_studio": ROOT / "content/scenes/asset_studio/asset_studio_scene.py",
    }

    @pytest.mark.parametrize("scene_name", SCENE_PY_FILES.keys())
    def test_calls_register_shared_assets(self, scene_name):
        """Every scene must call register_shared_assets()."""
        content = self.SCENE_PY_FILES[scene_name].read_text(encoding="utf-8")
        assert "register_shared_assets" in content, \
            f"{scene_name} does not call register_shared_assets()"

    @pytest.mark.parametrize("scene_name", SCENE_PY_FILES.keys())
    def test_calls_register_health_route(self, scene_name):
        """Every scene must register the health route."""
        content = self.SCENE_PY_FILES[scene_name].read_text(encoding="utf-8")
        assert "register_health_route" in content, \
            f"{scene_name} does not register health route"

    @pytest.mark.parametrize("scene_name", SCENE_PY_FILES.keys())
    def test_calls_register_hud_route(self, scene_name):
        """Every scene must register the HUD route."""
        content = self.SCENE_PY_FILES[scene_name].read_text(encoding="utf-8")
        assert "register_hud_route" in content, \
            f"{scene_name} does not register HUD route"

    @pytest.mark.parametrize("scene_name", SCENE_PY_FILES.keys())
    def test_calls_register_announcer_route(self, scene_name):
        """Every scene must register the announcer route."""
        content = self.SCENE_PY_FILES[scene_name].read_text(encoding="utf-8")
        assert "register_announcer_route" in content, \
            f"{scene_name} does not register announcer route"

    @pytest.mark.parametrize("scene_name", SCENE_PY_FILES.keys())
    def test_inherits_base_scene(self, scene_name):
        """Every scene class must inherit from BaseScene."""
        content = self.SCENE_PY_FILES[scene_name].read_text(encoding="utf-8")
        assert "BaseScene" in content, \
            f"{scene_name} does not inherit from BaseScene"

    def test_command_center_no_redundant_registration(self):
        """CommandCenter must NOT register routes in both __init__ and start()."""
        content = self.SCENE_PY_FILES["command_center"].read_text(encoding="utf-8")
        health_count = content.count("register_health_route")
        assert health_count == 1, \
            f"CommandCenter has {health_count} register_health_route calls (should be 1)"


# ═══════════════════════════════════════════════════════════════════════════
# 7. Cross-Cutting Consistency
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossCuttingConsistency:
    """Verify consistency across the entire template system."""

    def test_all_17_scenes_covered(self):
        """We must test exactly 17 scene templates."""
        assert len(ALL_SCENE_TEMPLATES) == 17

    def test_all_accent_colors_defined(self):
        """Every scene must have an expected accent color."""
        missing = [s for s in ALL_SCENE_TEMPLATES if s not in EXPECTED_SCENE_ACCENTS]
        assert not missing, f"Scenes missing expected accents: {missing}"

    def test_scene_accents_are_valid_hex(self):
        """All expected accent colors must be valid hex."""
        for scene, color in EXPECTED_SCENE_ACCENTS.items():
            assert re.match(r"^#[0-9a-fA-F]{6}$", color), \
                f"{scene} accent {color} is not valid hex"

    def test_no_scene_loads_navbar_css_directly(self):
        """No scene template should load navbar_v2.css or navbar_v2.js directly."""
        for name, path in ALL_SCENE_TEMPLATES.items():
            content = path.read_text(encoding="utf-8")
            assert "navbar_v2.css" not in content, \
                f"{name} loads navbar_v2.css (navbar_v2.html is self-contained)"
            assert "navbar_v2.js" not in content, \
                f"{name} loads navbar_v2.js (navbar_v2.html is self-contained)"

    def test_no_scene_loads_aria_js_directly(self):
        """No scene should load aria_widget.js (use include instead)."""
        for name, path in ALL_SCENE_TEMPLATES.items():
            content = path.read_text(encoding="utf-8")
            assert "aria_widget.js" not in content, \
                f"{name} loads aria_widget.js (should use include)"

    def test_neon_base_css_references_design_tokens(self):
        """neon_base.css should reference design token CSS variables."""
        content = NEON_BASE_CSS.read_text(encoding="utf-8")
        assert "var(--cs-" in content or "var(--scene-" in content

    def test_shared_templates_dir_contains_all_includes(self):
        """Shared templates dir must contain neon_base, navbar_v2, aria_widget."""
        templates_dir = ROOT / "content" / "shared" / "templates"
        assert (templates_dir / "neon_base.html").exists()
        assert (templates_dir / "navbar_v2.html").exists()
        assert (templates_dir / "aria_widget.html").exists()
