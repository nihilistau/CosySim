"""Tests for scene transition system."""
from pathlib import Path


SHARED_JS = Path("content/shared/static/js")
SHARED_CSS = Path("content/shared/static/css")
SHARED_TEMPLATES = Path("content/shared/templates")
SCENE_NAMES = ["bedroom", "phone", "lounge", "tavern", "casino", "gallery", "arena", "realm", "neoncity", "hub"]


def test_transitions_js_exists():
    assert (SHARED_JS / "cosysim-transitions.js").exists()


def test_transitions_js_has_core_logic():
    js = (SHARED_JS / "cosysim-transitions.js").read_text(encoding="utf-8")
    assert "data-scene-nav" in js
    assert "cs-page-exit" in js
    assert "cs-page-enter" in js
    assert "TRANSITION_DURATION" in js


def test_transitions_js_prevents_default():
    js = (SHARED_JS / "cosysim-transitions.js").read_text(encoding="utf-8")
    assert "preventDefault" in js


def test_transitions_js_navigates_after_delay():
    js = (SHARED_JS / "cosysim-transitions.js").read_text(encoding="utf-8")
    assert "setTimeout" in js
    assert "window.location" in js or "location.href" in js


def test_animations_css_has_page_fade_keyframes():
    css = (SHARED_CSS / "cosysim-animations.css").read_text(encoding="utf-8")
    assert "page-fade-out" in css
    assert "page-fade-in" in css


def test_animations_css_has_transition_classes():
    css = (SHARED_CSS / "cosysim-animations.css").read_text(encoding="utf-8")
    assert ".cs-page-exit" in css
    assert ".cs-page-enter" in css


def test_animations_css_has_reduced_motion():
    css = (SHARED_CSS / "cosysim-animations.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css


def test_navbar_has_scene_nav_attrs():
    navbar = (SHARED_TEMPLATES / "navbar_v2.html").read_text(encoding="utf-8")
    assert "data-scene-nav" in navbar


def test_navbar_has_multiple_scene_nav_attrs():
    navbar = (SHARED_TEMPLATES / "navbar_v2.html").read_text(encoding="utf-8")
    count = navbar.count("data-scene-nav")
    assert count >= 5, f"Expected at least 5 data-scene-nav attrs, found {count}"


def test_navbar_includes_transitions_script():
    navbar = (SHARED_TEMPLATES / "navbar_v2.html").read_text(encoding="utf-8")
    assert "cosysim-transitions.js" in navbar
