"""
Tests for the NPC Portrait Overlay static assets and template structure.

Verifies that all required files exist and contain the expected HTML elements,
CSS classes, and JavaScript API surface. These are structural / smoke tests
that do not require a running Flask server or browser.
"""
import re
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

REPO     = Path(__file__).parent.parent
TEMPLATE = REPO / "content" / "shared" / "templates" / "portrait_overlay.html"
CSS_FILE = REPO / "content" / "shared" / "static" / "css" / "portrait.css"
JS_FILE  = REPO / "content" / "shared" / "static" / "js"  / "portrait.js"


# ── File existence ────────────────────────────────────────────────────────────

class TestPortraitOverlayFilesExist:
    """All three asset files must be present on disk."""

    def test_template_exists(self):
        assert TEMPLATE.exists(), f"Missing: {TEMPLATE}"

    def test_css_exists(self):
        assert CSS_FILE.exists(), f"Missing: {CSS_FILE}"

    def test_js_exists(self):
        assert JS_FILE.exists(), f"Missing: {JS_FILE}"


# ── HTML structure ────────────────────────────────────────────────────────────

class TestPortraitOverlayHTML:
    """Template must contain all required structural elements."""

    @classmethod
    def setup_class(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_has_root_id(self):
        assert 'id="cs-portrait-overlay"' in self.html

    def test_has_data_char_attr(self):
        assert "data-char" in self.html

    def test_has_data_mood_attr(self):
        assert "data-mood" in self.html

    def test_has_portrait_initial_id(self):
        assert 'id="cs-portrait-initial"' in self.html

    def test_has_portrait_name_id(self):
        assert 'id="cs-portrait-name"' in self.html

    def test_has_portrait_mood_badge_id(self):
        assert 'id="cs-portrait-mood-badge"' in self.html

    def test_has_mood_ring_element(self):
        assert 'id="cs-portrait-mood-ring"' in self.html

    def test_has_aria_hidden(self):
        assert "aria-hidden" in self.html

    def test_has_cs_portrait_class(self):
        assert 'class="cs-portrait"' in self.html


# ── CSS structure ─────────────────────────────────────────────────────────────

class TestPortraitOverlayCSS:
    """Stylesheet must define all required rules."""

    @classmethod
    def setup_class(cls):
        cls.css = CSS_FILE.read_text(encoding="utf-8")

    def test_has_position_fixed(self):
        assert "position: fixed" in self.css

    def test_has_z_index_900(self):
        assert "z-index: 900" in self.css

    def test_has_is_visible_class(self):
        assert ".is-visible" in self.css

    def test_has_keyframes_portrait_pulse(self):
        assert "@keyframes portrait-pulse" in self.css

    def test_has_mood_ring_rule(self):
        assert ".cs-portrait__mood-ring" in self.css

    def test_has_transition_property(self):
        assert "transition:" in self.css

    def test_has_backdrop_filter(self):
        assert "backdrop-filter" in self.css

    def test_has_portrait_mood_color_var(self):
        assert "--portrait-mood-color" in self.css

    def test_has_translate_x_hidden_state(self):
        assert "translateX(140px)" in self.css


# ── JavaScript structure ──────────────────────────────────────────────────────

class TestPortraitOverlayJS:
    """Script must expose the full PortraitManager API."""

    @classmethod
    def setup_class(cls):
        cls.js = JS_FILE.read_text(encoding="utf-8")

    def test_has_portrait_manager_class(self):
        assert "class PortraitManager" in self.js

    def test_has_mood_colors_map(self):
        assert "MOOD_COLORS" in self.js

    def test_mood_colors_has_happy(self):
        assert re.search(r"['\"]?happy['\"]?\s*:", self.js)

    def test_mood_colors_has_angry(self):
        assert re.search(r"['\"]?angry['\"]?\s*:", self.js)

    def test_mood_colors_has_sad(self):
        assert re.search(r"['\"]?sad['\"]?\s*:", self.js)

    def test_mood_colors_has_aroused(self):
        assert re.search(r"['\"]?aroused['\"]?\s*:", self.js)

    def test_has_show_method(self):
        assert "show(" in self.js

    def test_has_hide_method(self):
        assert "hide()" in self.js

    def test_has_update_mood_method(self):
        assert "updateMood(" in self.js

    def test_has_parse_mood_tag_method(self):
        assert "_parseMoodTag(" in self.js

    def test_has_mood_tag_regex(self):
        assert "[MOOD:" in self.js

    def test_auto_init_on_dom_content_loaded(self):
        assert "DOMContentLoaded" in self.js

    def test_exposes_window_portrait_manager(self):
        assert "window.portraitManager" in self.js

    def test_listens_to_message_event(self):
        assert "socket.on('message'" in self.js or 'socket.on("message"' in self.js

    def test_listens_to_character_speaking_event(self):
        assert "socket.on('character_speaking'" in self.js or 'socket.on("character_speaking"' in self.js

    def test_has_auto_hide_timer(self):
        assert "hideTimer" in self.js or "hide_timer" in self.js

    def test_mood_colors_has_at_least_8_entries(self):
        # Count colour hex values as a proxy for the number of entries
        matches = re.findall(r"'#[0-9a-fA-F]{6}'", self.js)
        assert len(matches) >= 8, f"Expected ≥8 MOOD_COLORS entries, found {len(matches)}"

    def test_has_parse_char_tag_method(self):
        assert "_parseCharTag(" in self.js


# ── Injection registration ────────────────────────────────────────────────────

class TestPortraitInjectedBySharedInit:
    """portrait.css and portrait.js must be registered in shared/__init__.py."""

    @classmethod
    def setup_class(cls):
        cls.init = (REPO / "content" / "shared" / "__init__.py").read_text(encoding="utf-8")

    def test_portrait_css_injected(self):
        assert "portrait.css" in self.init

    def test_portrait_js_injected(self):
        assert "portrait.js" in self.init


# ── Mood colour CSS selectors ─────────────────────────────────────────────────

class TestPortraitCSSMoodColors:
    """portrait.css must define data-mood attribute selectors for every canonical mood."""

    MOODS = ["happy", "angry", "sad", "aroused", "neutral", "afraid", "excited"]

    @classmethod
    def setup_class(cls):
        cls.css = CSS_FILE.read_text(encoding="utf-8")

    def test_has_happy_selector(self):
        assert '[data-mood="happy"]' in self.css

    def test_has_angry_selector(self):
        assert '[data-mood="angry"]' in self.css

    def test_has_sad_selector(self):
        assert '[data-mood="sad"]' in self.css

    def test_has_aroused_selector(self):
        assert '[data-mood="aroused"]' in self.css

    def test_has_neutral_selector(self):
        assert '[data-mood="neutral"]' in self.css

    def test_has_afraid_selector(self):
        assert '[data-mood="afraid"]' in self.css

    def test_has_excited_selector(self):
        assert '[data-mood="excited"]' in self.css

    def test_all_moods_present(self):
        for mood in self.MOODS:
            assert f'[data-mood="{mood}"]' in self.css, f"Missing CSS selector for mood: {mood}"


# ── Admin portrait routes ─────────────────────────────────────────────────────

class TestAdminPortraitsRoutes:
    """/api/admin/portraits and /api/admin/portrait/generate must be wired."""

    @classmethod
    def setup_class(cls):
        cls.init = (REPO / "content" / "shared" / "__init__.py").read_text(encoding="utf-8")

    def test_admin_portraits_route_in_shared_init(self):
        assert "/api/admin/portraits" in self.init

    def test_admin_portrait_generate_route_in_shared_init(self):
        assert "/api/admin/portrait/generate" in self.init

    def test_admin_portraits_returns_portraits_key(self):
        """GET /api/admin/portraits returns JSON with a portraits list."""
        import sys
        from unittest.mock import MagicMock
        from flask import Flask

        # Ensure flask_cors won't cause an ImportError inside register_shared_assets
        if "flask_cors" not in sys.modules:
            sys.modules["flask_cors"] = MagicMock()

        app = Flask(__name__)
        app.config["TESTING"] = True

        from content.shared import register_shared_assets
        register_shared_assets(app)

        with app.test_client() as client:
            rv = client.get("/api/admin/portraits")
            assert rv.status_code == 200
            data = rv.get_json()
            assert data is not None, "Expected JSON response"
            assert "portraits" in data, f"Expected 'portraits' key, got: {list(data.keys())}"
            assert isinstance(data["portraits"], list)


# ── Injection into scene responses ────────────────────────────────────────────

class TestPortraitOverlayInjection:
    """portrait_overlay.html must be injected into scene HTML responses."""

    @classmethod
    def setup_class(cls):
        cls.init = (REPO / "content" / "shared" / "__init__.py").read_text(encoding="utf-8")

    def test_shared_init_references_portrait_overlay_html(self):
        assert "portrait_overlay.html" in self.init

    def test_portrait_overlay_div_injected_into_response(self):
        """The after_request hook must embed cs-portrait-overlay into HTML responses."""
        import sys
        from unittest.mock import MagicMock
        from flask import Flask, Response

        if "flask_cors" not in sys.modules:
            sys.modules["flask_cors"] = MagicMock()

        app = Flask(__name__)
        app.config["TESTING"] = True

        from content.shared import register_shared_assets
        register_shared_assets(app)

        @app.route("/test-portrait-inject")
        def _test_view() -> Response:
            return Response(
                "<html><body><p>hello</p></body></html>",
                content_type="text/html",
            )

        with app.test_client() as client:
            rv = client.get("/test-portrait-inject")
            html = rv.data.decode("utf-8")
            assert "cs-portrait-overlay" in html, (
                "Expected cs-portrait-overlay to be injected into HTML response"
            )
