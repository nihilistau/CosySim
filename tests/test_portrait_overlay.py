"""Tests for the portrait overlay component (HTML + CSS + JS)."""

import re
from pathlib import Path

TEMPLATE_PATH = Path("content/shared/templates/portrait_overlay.html")
CSS_PATH      = Path("content/shared/static/css/portrait.css")
JS_PATH       = Path("content/shared/static/js/portrait.js")


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── HTML tests ────────────────────────────────────────────────────────────────

def test_html_file_exists():
    assert TEMPLATE_PATH.exists(), f"Missing: {TEMPLATE_PATH}"


def test_html_has_root_id():
    html = _read(TEMPLATE_PATH)
    assert "id=\"cs-portrait-overlay\"" in html


def test_html_root_has_cs_portrait_class():
    html = _read(TEMPLATE_PATH)
    assert "class=\"cs-portrait\"" in html


def test_html_root_data_state_hidden():
    html = _read(TEMPLATE_PATH)
    assert 'data-state="hidden"' in html


def test_html_has_panel_div():
    html = _read(TEMPLATE_PATH)
    assert "cs-portrait__panel" in html


def test_html_has_image_area():
    html = _read(TEMPLATE_PATH)
    assert "cs-portrait__image-area" in html


def test_html_image_area_has_id():
    html = _read(TEMPLATE_PATH)
    assert 'id="cs-portrait-img-area"' in html


def test_html_has_img_tag():
    html = _read(TEMPLATE_PATH)
    assert "<img" in html
    assert 'id="cs-portrait-img"' in html


def test_html_has_placeholder():
    html = _read(TEMPLATE_PATH)
    assert "cs-portrait__placeholder" in html


def test_html_has_name_element():
    html = _read(TEMPLATE_PATH)
    assert "cs-portrait__name" in html
    assert 'id="cs-portrait-name"' in html


def test_html_has_mood_badge():
    html = _read(TEMPLATE_PATH)
    assert "cs-portrait__mood-badge" in html


def test_html_has_mood_badge_id():
    html = _read(TEMPLATE_PATH)
    assert 'id="cs-portrait-mood"' in html


# ── CSS tests ─────────────────────────────────────────────────────────────────

def test_css_file_exists():
    assert CSS_PATH.exists(), f"Missing: {CSS_PATH}"


def test_css_has_cs_portrait_selector():
    css = _read(CSS_PATH)
    assert ".cs-portrait" in css


def test_css_position_fixed():
    css = _read(CSS_PATH)
    assert "position: fixed" in css or "position:fixed" in css


def test_css_z_index_900():
    css = _read(CSS_PATH)
    assert "z-index: 900" in css or "z-index:900" in css


def test_css_all_mood_vars():
    css = _read(CSS_PATH)
    mood_vars = [
        "--mood-happy",
        "--mood-sad",
        "--mood-angry",
        "--mood-aroused",
        "--mood-neutral",
        "--mood-anxious",
        "--mood-excited",
    ]
    for var in mood_vars:
        assert var in css, f"Missing CSS variable: {var}"


def test_css_data_state_hidden_opacity_zero():
    css = _read(CSS_PATH)
    assert 'data-state="hidden"' in css
    # Match .cs-portrait[data-state="hidden"] { ... }
    hidden_block = re.search(
        r'\[data-state=["\']hidden["\']\][^{]*\{([^}]+)\}', css, re.DOTALL
    )
    assert hidden_block, "No [data-state='hidden'] CSS rule found"
    assert "opacity: 0" in hidden_block.group(1) or "opacity:0" in hidden_block.group(1)


def test_css_data_state_visible_opacity_one():
    css = _read(CSS_PATH)
    assert 'data-state="visible"' in css
    # Match .cs-portrait[data-state="visible"] { ... }
    visible_block = re.search(
        r'\[data-state=["\']visible["\']\][^{]*\{([^}]+)\}', css, re.DOTALL
    )
    assert visible_block, "No [data-state='visible'] CSS rule found"
    assert "opacity: 1" in visible_block.group(1) or "opacity:1" in visible_block.group(1)


def test_css_keyframes_portrait_pulse():
    css = _read(CSS_PATH)
    assert "@keyframes portrait-pulse" in css


def test_css_image_area_dimensions():
    css = _read(CSS_PATH)
    assert "120px" in css


def test_css_translate_x_hidden():
    css = _read(CSS_PATH)
    assert "translateX(120%)" in css


# ── JS tests ──────────────────────────────────────────────────────────────────

def test_js_file_exists():
    assert JS_PATH.exists(), f"Missing: {JS_PATH}"


def test_js_has_window_portrait_manager():
    js = _read(JS_PATH)
    assert "window.portraitManager" in js


def test_js_has_init_method():
    js = _read(JS_PATH)
    assert "init(" in js or "init (" in js


def test_js_has_show_method():
    js = _read(JS_PATH)
    assert "show(" in js


def test_js_has_hide_method():
    js = _read(JS_PATH)
    assert "hide(" in js


def test_js_has_update_mood_method():
    js = _read(JS_PATH)
    assert "updateMood(" in js


def test_js_has_parse_mood_method():
    js = _read(JS_PATH)
    assert "parseMood(" in js


def test_js_has_mood_map():
    js = _read(JS_PATH)
    assert "MOOD_MAP" in js


def test_js_mood_map_all_seven_moods():
    js = _read(JS_PATH)
    moods = ["happy", "sad", "angry", "aroused", "neutral", "anxious", "excited"]
    for mood in moods:
        assert mood in js, f"Mood missing from MOOD_MAP: {mood}"


def test_js_listens_to_message_event():
    js = _read(JS_PATH)
    assert "socket.on('message'" in js or 'socket.on("message"' in js


def test_js_listens_to_character_entered_event():
    js = _read(JS_PATH)
    assert "socket.on('character_entered'" in js or 'socket.on("character_entered"' in js


def test_js_listens_to_character_exited_event():
    js = _read(JS_PATH)
    assert "socket.on('character_exited'" in js or 'socket.on("character_exited"' in js


def test_js_calls_parse_mood():
    js = _read(JS_PATH)
    assert "parseMood(" in js
    # parseMood must be called somewhere other than its own definition
    calls = re.findall(r"parseMood\s*\(", js)
    assert len(calls) >= 2, "parseMood should be defined AND called"


def test_js_mood_tag_regex_format():
    js = _read(JS_PATH)
    assert r"[MOOD:" in js or r"\[MOOD:" in js


def test_js_dom_content_loaded_auto_init():
    js = _read(JS_PATH)
    assert "DOMContentLoaded" in js
    assert "init()" in js