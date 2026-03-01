"""
tests/test_navbar_v2.py
=======================
Tests for the CosySim Universal Navbar v2 (B1 track).

Covers:
- BaseScene.inject_navbar_context() return shape and defaults
- inject_navbar_context() reads SCENE_METADATA correctly
- Static asset existence (CSS, JS, HTML template)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent


def _shared_static(rel: str) -> Path:
    """Return absolute path for a file under content/shared/static/."""
    return _PROJECT_ROOT / "content" / "shared" / "static" / rel


def _shared_template(name: str) -> Path:
    """Return absolute path for a file under content/shared/templates/."""
    return _PROJECT_ROOT / "content" / "shared" / "templates" / name


# ---------------------------------------------------------------------------
# Static asset presence
# ---------------------------------------------------------------------------


class TestNavbarStaticAssets:
    """Ensure the three static files were created and are non-empty."""

    def test_navbar_css_exists(self):
        """navbar_v2.css must exist and contain content."""
        path = _shared_static("css/navbar_v2.css")
        assert path.is_file(), f"Missing: {path}"
        assert path.stat().st_size > 0, "navbar_v2.css is empty"

    def test_navbar_js_exists(self):
        """navbar_v2.js must exist and contain content."""
        path = _shared_static("js/navbar_v2.js")
        assert path.is_file(), f"Missing: {path}"
        assert path.stat().st_size > 0, "navbar_v2.js is empty"

    def test_navbar_template_exists(self):
        """navbar_v2.html must exist in shared templates."""
        path = _shared_template("navbar_v2.html")
        assert path.is_file(), f"Missing: {path}"
        assert path.stat().st_size > 0, "navbar_v2.html is empty"

    def test_navbar_css_has_bar_class(self):
        """navbar_v2.css must define the .cs-navbar selector."""
        css = _shared_static("css/navbar_v2.css").read_text(encoding="utf-8")
        assert ".cs-navbar {" in css or ".cs-navbar{" in css

    def test_navbar_css_has_credits_class(self):
        """navbar_v2.css must define .cs-credits-display."""
        css = _shared_static("css/navbar_v2.css").read_text(encoding="utf-8")
        assert ".cs-credits-display" in css

    def test_navbar_js_has_class_definition(self):
        """navbar_v2.js must define the CosyNavbar class."""
        js = _shared_static("js/navbar_v2.js").read_text(encoding="utf-8")
        assert "class CosyNavbar" in js

    def test_navbar_js_has_scene_ports(self):
        """navbar_v2.js must define SCENE_PORTS const."""
        js = _shared_static("js/navbar_v2.js").read_text(encoding="utf-8")
        assert "SCENE_PORTS" in js

    def test_navbar_template_has_jinja_defaults(self):
        """navbar_v2.html must include the Jinja2 variable defaults block."""
        html = _shared_template("navbar_v2.html").read_text(encoding="utf-8")
        assert "current_scene" in html
        assert "scene_name" in html
        assert "scene_accent" in html

    def test_navbar_template_has_credits_element(self):
        """navbar_v2.html must include the credits display element."""
        html = _shared_template("navbar_v2.html").read_text(encoding="utf-8")
        assert "navbar-credits" in html
        assert "cs-credits-display" in html

    def test_navbar_template_has_action_buttons(self):
        """navbar_v2.html must include all four action buttons."""
        html = _shared_template("navbar_v2.html").read_text(encoding="utf-8")
        for btn_id in (
            "navbar-phone-btn",
            "navbar-aria-btn",
            "navbar-voice-btn",
            "navbar-admin-btn",
        ):
            assert btn_id in html, f"Missing button id: {btn_id}"


# ---------------------------------------------------------------------------
# BaseScene.inject_navbar_context()
# ---------------------------------------------------------------------------


class TestInjectNavbarContext:
    """Unit tests for BaseScene.inject_navbar_context()."""

    def _make_scene(self, metadata: dict | None = None):
        """Create a minimal concrete subclass of BaseScene for testing.

        Patches heavy __init__ dependencies so the test stays fast and
        offline.
        """
        from engine.scenes.base_scene import BaseScene

        class _ConcreteScene(BaseScene):
            if metadata is not None:
                SCENE_METADATA = metadata

            def start(self) -> None:  # pragma: no cover
                pass

            def stop(self) -> None:  # pragma: no cover
                pass

            def get_plugin_info(self):  # pragma: no cover
                return {}

        with (
            patch("engine.scenes.base_scene.AssetManager"),
            patch("engine.scenes.base_scene.BaseScene._mcp_register_scene"),
        ):
            scene = _ConcreteScene.__new__(_ConcreteScene)
            # Minimal attribute initialisation (avoids full __init__)
            scene.scene_name = "test_scene"
            scene.host = "0.0.0.0"
            scene.port = 9000
            scene.active_characters = {}
            scene.scene_config = {}
            scene.streaming_enabled = True
            scene._active_streams = 0
            scene._total_stream_tokens = 0
            if metadata is not None:
                # Attach SCENE_METADATA as instance attribute for class variants
                pass
            return scene

    # ── return type ─────────────────────────────────────────────────

    def test_inject_navbar_context_returns_dict(self):
        """inject_navbar_context must return a dict."""
        scene = self._make_scene()
        result = scene.inject_navbar_context()
        assert isinstance(result, dict)

    def test_inject_navbar_context_has_required_keys(self):
        """Returned dict must contain current_scene, scene_name, scene_accent."""
        scene = self._make_scene()
        result = scene.inject_navbar_context()
        assert "current_scene" in result
        assert "scene_name" in result
        assert "scene_accent" in result

    # ── defaults (no SCENE_METADATA on class) ───────────────────────

    def test_inject_navbar_context_defaults(self):
        """Without SCENE_METADATA, scene_name defaults to 'CosySim' and accent to cyan."""
        scene = self._make_scene(metadata=None)
        result = scene.inject_navbar_context()
        assert result["current_scene"] == "test_scene"
        assert result["scene_name"] == "CosySim"
        assert result["scene_accent"] == "#00e5ff"

    # ── uses SCENE_METADATA ─────────────────────────────────────────

    def test_inject_navbar_context_uses_metadata(self):
        """When SCENE_METADATA provides display_name and accent_color, they are used."""
        meta = {
            "display_name": "THE PENTHOUSE",
            "accent_color": "#c084fc",
        }
        scene = self._make_scene(metadata=meta)
        # Force class attribute (needed for patched instantiation)
        scene.__class__.SCENE_METADATA = meta

        result = scene.inject_navbar_context()
        assert result["scene_name"] == "THE PENTHOUSE"
        assert result["scene_accent"] == "#c084fc"

    def test_inject_navbar_context_partial_metadata(self):
        """If SCENE_METADATA is missing accent_color, default cyan is used."""
        meta = {"display_name": "THE SCORE"}
        scene = self._make_scene(metadata=meta)
        scene.__class__.SCENE_METADATA = meta

        result = scene.inject_navbar_context()
        assert result["scene_name"] == "THE SCORE"
        assert result["scene_accent"] == "#00e5ff"

    def test_inject_navbar_context_uses_scene_name_attr(self):
        """current_scene must reflect scene.scene_name, not a hardcoded value."""
        scene = self._make_scene()
        scene.scene_name = "casino"
        result = scene.inject_navbar_context()
        assert result["current_scene"] == "casino"
