"""Tests for scene transition animations (Track A Phase 3)."""
import re
from pathlib import Path

SHARED_STATIC = Path("content/shared/static")
SHARED_TEMPLATES = Path("content/shared/templates")

JS_PATH  = SHARED_STATIC / "js" / "cosysim-transitions.js"
CSS_PATH = SHARED_STATIC / "css" / "cosysim-animations.css"
NAV_PATH = SHARED_TEMPLATES / "navbar_v2.html"


def test_transitions_js_exists() -> None:
    """cosysim-transitions.js must exist."""
    assert JS_PATH.exists(), f"Missing: {JS_PATH}"


def test_transitions_js_has_overlay() -> None:
    """transitions.js must contain overlay fade logic."""
    content = JS_PATH.read_text(encoding="utf-8")
    assert "cs-transition-overlay" in content
    assert "navigate" in content
    assert "cs-page-exit" in content


def test_transitions_js_intercepts_data_scene_nav() -> None:
    """transitions.js must intercept [data-scene-nav] clicks."""
    content = JS_PATH.read_text(encoding="utf-8")
    assert "data-scene-nav" in content


def test_transitions_js_duration_constant() -> None:
    """transitions.js must declare a DURATION constant."""
    content = JS_PATH.read_text(encoding="utf-8")
    assert "TRANSITION_MS" in content


def test_navbar_loads_transitions_js() -> None:
    """navbar_v2.html must load cosysim-transitions.js."""
    content = NAV_PATH.read_text(encoding="utf-8")
    assert "cosysim-transitions.js" in content


def test_navbar_scene_links_have_data_scene_nav() -> None:
    """Scene nav links in navbar_v2.html must carry data-scene-nav."""
    content = NAV_PATH.read_text(encoding="utf-8")
    # At least the main nav items and more-dropdown items must have the attribute
    assert content.count("data-scene-nav") >= 3, (
        "Expected data-scene-nav on logo + nav items + more-dropdown items"
    )


def test_css_has_page_enter_class() -> None:
    """.cs-page-enter must exist in cosysim-animations.css."""
    content = CSS_PATH.read_text(encoding="utf-8")
    assert ".cs-page-enter" in content


def test_css_has_page_exit_class() -> None:
    """.cs-page-exit must exist in cosysim-animations.css."""
    content = CSS_PATH.read_text(encoding="utf-8")
    assert ".cs-page-exit" in content


def test_css_page_enter_uses_fade_in_keyframe() -> None:
    """.cs-page-enter must reference cs-fade-in keyframe."""
    content = CSS_PATH.read_text(encoding="utf-8")
    enter_block = re.search(r"\.cs-page-enter\s*\{([^}]+)\}", content)
    assert enter_block, ".cs-page-enter rule not found"
    assert "cs-fade-in" in enter_block.group(1)


def test_css_page_exit_uses_fade_out_keyframe() -> None:
    """.cs-page-exit must reference cs-fade-out keyframe."""
    content = CSS_PATH.read_text(encoding="utf-8")
    exit_block = re.search(r"\.cs-page-exit\s*\{([^}]+)\}", content)
    assert exit_block, ".cs-page-exit rule not found"
    assert "cs-fade-out" in exit_block.group(1)
