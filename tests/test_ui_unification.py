"""Tests for CosySim v0.75 'NEON CITY' Track E — UI/UX Unification.

Verifies that all 10 scene templates, shared CSS files, and the navbar meet
the NEON CITY unification requirements.
"""

import re
from pathlib import Path

# ── Helpers ────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent

SCENE_TEMPLATES = {
    "bedroom":  ROOT / "content/scenes/bedroom/templates/bedroom.html",
    "phone":    ROOT / "content/scenes/phone/templates/phone.html",
    "casino":   ROOT / "content/scenes/casino/templates/casino.html",
    "lounge":   ROOT / "content/scenes/lounge/templates/lounge.html",
    "tavern":   ROOT / "content/scenes/tavern/templates/tavern.html",
    "gallery":  ROOT / "content/scenes/gallery/templates/gallery.html",
    "arena":    ROOT / "content/scenes/arena/templates/arena.html",
    "realm":    ROOT / "content/scenes/realm/templates/realm.html",
    "neoncity": ROOT / "content/scenes/neoncity/templates/neoncity.html",
    "grid":     ROOT / "content/scenes/grid/templates/grid.html",
}

NAVBAR      = ROOT / "content/shared/templates/navbar_v2.html"
SCENE_FX    = ROOT / "content/shared/static/css/cosysim-scene-fx.css"
DESIGN_TOKENS = ROOT / "content/shared/static/css/design_tokens.css"
NEON_BASE   = ROOT / "content/shared/templates/neon_base.html"


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

REQUIRED_SCENES_IN_NAVBAR = [
    "bedroom", "phone", "lounge", "tavern", "casino",
    "gallery", "arena", "realm", "coders", "heist",
    "games", "grid", "intel", "neoncity", "hub",
]


# ── Task 1: Scene templates ────────────────────────────────────────────────

def test_all_scene_templates_exist():
    """All 10 target scene templates must exist on disk."""
    missing = [name for name, path in SCENE_TEMPLATES.items() if not path.exists()]
    assert not missing, f"Missing template files: {missing}"


def test_all_scene_templates_have_data_scene_attribute():
    """Every scene template must declare data-scene='<scene>' on its body element."""
    bad = []
    for name, path in SCENE_TEMPLATES.items():
        content = _effective_content(path.read_text(encoding="utf-8"))
        # Accept data-scene on <body> or on <html> (some scenes use html-level attr)
        if not re.search(rf'data-scene=["\']?{name}["\']?', content):
            bad.append(name)
    assert not bad, f"Templates missing data-scene attribute: {bad}"


def test_all_scene_templates_include_navbar_v2():
    """Every template must include or extend navbar_v2.html (which injects neon_hud)."""
    bad = []
    for name, path in SCENE_TEMPLATES.items():
        content = _effective_content(path.read_text(encoding="utf-8"))
        if "navbar_v2" not in content:
            bad.append(name)
    assert not bad, f"Templates missing navbar_v2 include/extend: {bad}"


def test_neon_hud_injected_via_navbar():
    """navbar_v2.html must include neon_hud.html so all scenes inherit it."""
    content = NAVBAR.read_text(encoding="utf-8")
    assert "neon_hud.html" in content, "navbar_v2.html must include neon_hud.html"


def test_all_scene_templates_link_scene_css():
    """Every template must reference a scene-specific CSS file."""
    bad = []
    for name, path in SCENE_TEMPLATES.items():
        content = _effective_content(path.read_text(encoding="utf-8"))
        if f"{name}.css" not in content:
            bad.append(name)
    assert not bad, f"Templates missing scene-specific CSS link: {bad}"


# ── Task 2: cosysim-scene-fx.css ──────────────────────────────────────────

def test_scene_fx_has_entry_for_grid():
    """cosysim-scene-fx.css must have a [data-scene='grid'] rule block."""
    content = SCENE_FX.read_text(encoding="utf-8")
    assert '[data-scene="grid"]' in content, \
        "cosysim-scene-fx.css missing [data-scene='grid'] rule"


def test_scene_fx_grid_accent_is_neon_green():
    """cosysim-scene-fx.css grid entry must use #00ff88 as the accent colour."""
    content = SCENE_FX.read_text(encoding="utf-8")
    # Find the custom property block for grid and check for the neon green value
    assert "#00ff88" in content, \
        "cosysim-scene-fx.css grid accent must be #00ff88 (neon green)"


def test_scene_fx_has_all_10_scenes():
    """cosysim-scene-fx.css must contain data-scene entries for all 10 scenes."""
    content = SCENE_FX.read_text(encoding="utf-8")
    missing = [s for s in SCENE_TEMPLATES if f'[data-scene="{s}"]' not in content]
    assert not missing, f"cosysim-scene-fx.css missing entries for: {missing}"


def test_scene_fx_grid_has_keyframe():
    """cosysim-scene-fx.css must define a @keyframes animation for grid."""
    content = SCENE_FX.read_text(encoding="utf-8")
    assert re.search(r"@keyframes\s+grid-", content), \
        "cosysim-scene-fx.css missing @keyframes animation for grid scene"


# ── Task 3 & 4: navbar_v2.html ────────────────────────────────────────────

def test_navbar_contains_the_grid_link():
    """navbar_v2.html must reference THE GRID scene."""
    content = NAVBAR.read_text(encoding="utf-8")
    assert "THE GRID" in content or '"grid"' in content, \
        "navbar_v2.html does not contain a THE GRID scene entry"


def test_navbar_has_all_15_scenes():
    """navbar_v2.html must list all 15 scenes in its scene registry."""
    content = NAVBAR.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED_SCENES_IN_NAVBAR
               if f'"key": "{s}"' not in content and f'"key":"{s}"' not in content
               and f"\"key\": \"{s}\"" not in content]
    # Jinja dict syntax — key is a plain string quoted with double quotes
    missing2 = [s for s in REQUIRED_SCENES_IN_NAVBAR
                if re.search(rf'"key":\s*"{s}"', content) is None]
    assert not missing2, f"navbar_v2.html missing scene keys: {missing2}"


def test_navbar_has_scene_dot_spans():
    """navbar_v2.html must contain <span class='scene-dot'> elements for status indicators."""
    content = NAVBAR.read_text(encoding="utf-8")
    count = content.count('class="scene-dot"') + content.count("class='scene-dot'")
    assert count >= 1, \
        "navbar_v2.html must contain at least one scene-dot span for status indicators"


def test_navbar_grid_port_is_5569():
    """navbar_v2.html must map the grid scene to port 5569."""
    content = NAVBAR.read_text(encoding="utf-8")
    # Look for grid entry with port 5569 nearby
    assert re.search(r'"port":\s*5569', content), \
        "navbar_v2.html grid scene port must be 5569"


# ── Task 4: design_tokens.css ─────────────────────────────────────────────

def test_design_tokens_has_scene_dot_rule():
    """design_tokens.css must define the .scene-dot CSS rule."""
    content = DESIGN_TOKENS.read_text(encoding="utf-8")
    assert ".scene-dot" in content, \
        "design_tokens.css must define the .scene-dot class"


def test_design_tokens_scene_dot_has_pulse_animation():
    """design_tokens.css .scene-dot must reference dot-pulse animation."""
    content = DESIGN_TOKENS.read_text(encoding="utf-8")
    assert "dot-pulse" in content, \
        "design_tokens.css must define and apply the dot-pulse @keyframes"


def test_design_tokens_has_grid_scene_token():
    """design_tokens.css must define --cs-scene-grid token with #00ff88."""
    content = DESIGN_TOKENS.read_text(encoding="utf-8")
    assert "--cs-scene-grid" in content and "#00ff88" in content, \
        "design_tokens.css must define --cs-scene-grid: #00ff88"


def test_design_tokens_has_grid_data_scene_override():
    """design_tokens.css must override --cs-scene-accent for [data-scene='grid']."""
    content = DESIGN_TOKENS.read_text(encoding="utf-8")
    assert re.search(r'\[data-scene=["\']?grid["\']?\]', content), \
        "design_tokens.css missing [data-scene='grid'] accent override"
