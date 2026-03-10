"""Tests for content/shared/static/js/cosysim-particles.js

Validates the JS file structure and content by reading it as text.
No JS execution required.
"""

from pathlib import Path

import pytest

JS_PATH = Path("content/shared/static/js/cosysim-particles.js")


@pytest.fixture(scope="module")
def js_content() -> str:
    return JS_PATH.read_text(encoding="utf-8")


# ──── File existence ────

def test_particle_engine_file_exists():
    assert JS_PATH.exists(), f"Expected {JS_PATH} to exist"


def test_particle_engine_file_not_empty():
    assert JS_PATH.stat().st_size > 1000, "File appears too small to be complete"


# ──── Class definition ────

def test_particle_engine_class_defined(js_content):
    assert "class ParticleEngine" in js_content


def test_constructor_defined(js_content):
    assert "constructor(" in js_content


# ──── Required public methods ────

def test_start_method_defined(js_content):
    assert "start()" in js_content


def test_stop_method_defined(js_content):
    assert "stop()" in js_content


def test_resize_method_defined(js_content):
    assert "resize()" in js_content


def test_tick_method_defined(js_content):
    assert "_tick()" in js_content


def test_spawn_particle_method_defined(js_content):
    assert "_spawnParticle(" in js_content


def test_update_particle_method_defined(js_content):
    assert "_updateParticle(" in js_content


def test_draw_particle_method_defined(js_content):
    assert "_drawParticle(" in js_content


# ──── All 9 effects ────

@pytest.mark.parametrize("effect", [
    "float", "signal", "smoke", "ember", "glint",
    "ink", "blood", "energy", "neon_rain",
])
def test_effect_defined(js_content, effect):
    assert f"'{effect}'" in js_content or f'"{effect}"' in js_content, \
        f"Effect '{effect}' not found in particle engine"


# ──── PARTICLE_PRESETS constant ────

def test_scene_presets_constant_defined(js_content):
    assert "PARTICLE_PRESETS" in js_content


@pytest.mark.parametrize("scene", [
    "penthouse", "phone", "lounge", "tavern", "casino",
    "gallery", "arena", "realm", "neoncity",
])
def test_scene_preset_defined(js_content, scene):
    assert scene in js_content, f"Preset '{scene}' not found in PARTICLE_PRESETS"


# ──── Config schema keys ────

@pytest.mark.parametrize("key", ["count", "color", "effect", "size", "speed", "opacity"])
def test_config_schema_key_present(js_content, key):
    assert key in js_content, f"Config schema key '{key}' not found"


# ──── Auto-init ────

def test_auto_init_on_domcontentloaded(js_content):
    assert "DOMContentLoaded" in js_content


def test_cs_particles_canvas_id(js_content):
    assert "cs-particles" in js_content


def test_window_particle_engine_exposed(js_content):
    assert "window.particleEngine" in js_content


def test_window_particle_engine_class_exposed(js_content):
    """window.ParticleEngine (the class) must be assigned for external use."""
    assert "window.ParticleEngine = ParticleEngine" in js_content or \
           "window.ParticleEngine=ParticleEngine" in js_content


def test_init_method_defined(js_content):
    """init(canvas, config) method must be defined on ParticleEngine."""
    assert "init(" in js_content


def test_scene_particle_config_override(js_content):
    assert "SCENE_PARTICLE_CONFIG" in js_content


def test_body_dataset_scene(js_content):
    assert "dataset.scene" in js_content or "data-scene" in js_content or "body.dataset" in js_content


# ──── Canvas setup ────

def test_canvas_fixed_position(js_content):
    assert "fixed" in js_content


def test_canvas_pointer_events_none(js_content):
    assert "pointer-events" in js_content or "pointerEvents" in js_content


def test_canvas_z_index(js_content):
    assert "zIndex" in js_content or "z-index" in js_content


def test_resize_observer_used(js_content):
    assert "ResizeObserver" in js_content


def test_request_animation_frame_used(js_content):
    assert "requestAnimationFrame" in js_content


def test_cancel_animation_frame_used(js_content):
    assert "cancelAnimationFrame" in js_content


# ──── Colour helper ────

def test_hex_to_rgb_helper(js_content):
    assert "hexToRgb" in js_content


# ──── Preset count sanity check ────

def test_nine_presets_total(js_content):
    """Ensure exactly the 9 expected preset keys are in the PARTICLE_PRESETS block."""
    expected = {"penthouse", "phone", "lounge", "tavern", "casino", "gallery", "arena", "realm", "neoncity"}
    found = {scene for scene in expected if scene in js_content}
    assert found == expected, f"Missing presets: {expected - found}"


# ──── All 9 effects in PARTICLE_PRESETS values ────

def test_all_effect_types_used_in_presets(js_content):
    """Every effect type must appear at least once as a preset value."""
    for effect in ("float", "signal", "smoke", "ember", "glint", "ink", "blood", "energy", "neon_rain"):
        assert effect in js_content, f"Effect '{effect}' missing from presets"


# ──── Use strict ────

def test_use_strict_present(js_content):
    assert "'use strict'" in js_content or '"use strict"' in js_content


# ──── No external dependencies ────

def test_no_external_imports(js_content):
    """File must not import/require external libraries."""
    assert "import " not in js_content or "// import" in js_content
    assert "require(" not in js_content
