"""Track A scene polish tests — template wiring and shared assets."""
import re
from pathlib import Path

SCENES_DIR = Path("content/scenes")
SHARED_CSS = Path("content/shared/static/css")
SHARED_JS = Path("content/shared/static/js")
SHARED_TEMPLATES = Path("content/shared/templates")
NEON_BASE = Path("content/shared/templates/neon_base.html")

GAME_SCENES = ["penthouse", "phone", "lounge", "tavern", "casino", "gallery", "arena", "realm", "neoncity"]


def _effective_content(raw: str) -> str:
    """If template extends neon_base.html, include base content for assertion checks."""
    if "extends 'neon_base.html'" in raw or 'extends "neon_base.html"' in raw:
        base = NEON_BASE.read_text(encoding="utf-8") if NEON_BASE.exists() else ""
        combined = raw + "\n" + base
        m = re.search(r"{%\s*set\s+scene_key\s*=\s*['\"](\w+)['\"]", raw)
        if m:
            combined = combined.replace("{{ scene_key }}", m.group(1))
        return combined
    return raw


def _get_template(scene: str) -> str:
    """Find and return template content for a scene."""
    results = list((SCENES_DIR / scene).rglob("*.html"))
    for f in results:
        content = f.read_text(encoding="utf-8")
        if "<body" in content or "{% extends" in content:
            return _effective_content(content)
    return ""


def test_shared_assets_exist():
    assert (SHARED_JS / "cosysim-particles.js").exists()
    assert (SHARED_CSS / "cosysim-scene-fx.css").exists()
    assert (SHARED_CSS / "design_tokens.css").exists()
    assert (SHARED_TEMPLATES / "portrait_overlay.html").exists()
    assert (SHARED_CSS / "portrait.css").exists()
    assert (SHARED_JS / "portrait.js").exists()


def test_all_templates_have_data_scene():
    for scene in GAME_SCENES:
        html = _get_template(scene)
        assert html, f"No main template found for {scene}"
        assert f'data-scene="{scene}"' in html, f"{scene}: missing data-scene attribute"


def test_all_templates_link_scene_fx_css():
    for scene in GAME_SCENES:
        html = _get_template(scene)
        assert "cosysim-scene-fx.css" in html, f"{scene}: missing cosysim-scene-fx.css link"


def test_all_templates_have_particle_canvas():
    for scene in GAME_SCENES:
        html = _get_template(scene)
        assert 'id="cs-particles"' in html, f"{scene}: missing particle canvas"


def test_all_templates_link_particles_js():
    for scene in GAME_SCENES:
        html = _get_template(scene)
        assert "cosysim-particles.js" in html, f"{scene}: missing cosysim-particles.js script"


def test_all_templates_have_particle_config():
    for scene in GAME_SCENES:
        html = _get_template(scene)
        assert "SCENE_PARTICLE_CONFIG" in html, f"{scene}: missing SCENE_PARTICLE_CONFIG"


def test_particle_canvas_styles():
    """Particle canvas JS sets position:fixed and z-index:0."""
    particles_js = (SHARED_JS / "cosysim-particles.js").read_text(encoding="utf-8")
    assert "position" in particles_js
    assert "fixed" in particles_js
    assert "pointerEvents" in particles_js


def test_scene_fx_css_has_all_scenes():
    css = (SHARED_CSS / "cosysim-scene-fx.css").read_text(encoding="utf-8")
    for scene in GAME_SCENES:
        assert f'data-scene="{scene}"' in css, f"scene-fx.css missing {scene} selector"


def test_portrait_overlay_structure():
    html = (SHARED_TEMPLATES / "portrait_overlay.html").read_text(encoding="utf-8")
    assert "cs-portrait" in html
    assert "cs-portrait__image-area" in html
    assert "cs-portrait__name" in html
    assert "cs-portrait__mood-badge" in html


def test_portrait_js_exposes_manager():
    js = (SHARED_JS / "portrait.js").read_text(encoding="utf-8")
    assert "portraitManager" in js
    assert "show" in js
    assert "hide" in js
    assert "updateMood" in js
