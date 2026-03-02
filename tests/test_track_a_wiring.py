"""Tests verifying Track A Phase 2 asset wiring across all 9 game scene templates."""

from pathlib import Path

import pytest

SCENES = [
    "bedroom",
    "phone",
    "lounge",
    "tavern",
    "casino",
    "gallery",
    "arena",
    "realm",
    "neoncity",
]

TEMPLATES_ROOT = Path(__file__).parent.parent / "content" / "scenes"


def _load(scene: str) -> str:
    path = TEMPLATES_ROOT / scene / "templates" / f"{scene}.html"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("scene", SCENES)
def test_template_has_data_scene_attribute(scene: str) -> None:
    """Every template must declare a data-scene attribute."""
    assert 'data-scene=' in _load(scene), f"{scene}: missing data-scene attribute"


@pytest.mark.parametrize("scene", SCENES)
def test_template_loads_cosysim_particles_js(scene: str) -> None:
    """Every template must load the unified particle engine."""
    assert "cosysim-particles.js" in _load(scene), f"{scene}: missing cosysim-particles.js"


@pytest.mark.parametrize("scene", SCENES)
def test_template_loads_cosysim_scene_fx_css(scene: str) -> None:
    """Every template must load the ambient scene-FX stylesheet."""
    assert "cosysim-scene-fx" in _load(scene), f"{scene}: missing cosysim-scene-fx.css"


@pytest.mark.parametrize("scene", SCENES)
def test_template_has_cs_particles_canvas(scene: str) -> None:
    """Every template must include the cs-particles canvas element."""
    assert 'id="cs-particles"' in _load(scene), f"{scene}: missing <canvas id='cs-particles'>"


@pytest.mark.parametrize("scene", SCENES)
def test_template_loads_design_tokens_css(scene: str) -> None:
    """Every template must load the design tokens stylesheet."""
    assert "design_tokens" in _load(scene), f"{scene}: missing design_tokens.css"
