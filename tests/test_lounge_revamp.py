"""Tests for THE VELVET PIT — v0.68 'Dark Renaissance' lounge revamp.

Validates scene metadata, skill registration, skill behaviour,
and presence of required static assets.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Constants ──────────────────────────────────────────────────────────────────

LOUNGE_DIR = Path(__file__).parent.parent / "content" / "scenes" / "lounge"


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def _mock_base_deps(monkeypatch):
    """Patch all heavy engine deps so LoungeScene can be imported without a server."""
    monkeypatch.setattr("engine.scenes.base_scene.BaseScene.__init__", lambda *a, **kw: None)

    fw = MagicMock()
    fw.start_timer.return_value = "timer_001"
    fw.tick.return_value = []
    fw.random_pick.return_value = {"picks": ["quiet"]}
    fw.get_cross_scene_inbox.return_value = []
    fw.turn = 0

    ssm = MagicMock()
    ssm.get_atmosphere.return_value = {}
    ssm.get_narrative_entries.return_value = []
    ssm.get_character_state.return_value = {}

    reg = MagicMock()
    reg.get_state.return_value = {"mood": "calm", "mood_intensity": 0.5, "energy": 75.0}
    reg_result = MagicMock()
    reg_result.profile = MagicMock()
    reg.register.return_value = reg_result

    eng = MagicMock()
    eng.apply_rule.return_value = {}
    eng.get_rules.return_value = []
    eng.get_rules_summary.return_value = ""

    monkeypatch.setattr("engine.mcp.framework.get_framework", lambda: fw)
    monkeypatch.setattr("engine.mcp.scene_state.get_scene_state_manager", lambda: ssm)
    monkeypatch.setattr("engine.mcp.tag_registry.TagRegistry.get", lambda: MagicMock())
    monkeypatch.setattr("engine.mcp.scene_rules_engine.get_rules_engine", lambda: eng)

    with patch("content.scenes.lounge.lounge_scene.register_lounge_rules"):
        with patch("content.scenes.lounge.lounge_scene.register_shared_assets"):
            with patch("flask.Flask"):
                with patch("flask_socketio.SocketIO"):
                    with patch("flask_cors.CORS"):
                        yield fw, ssm, reg, eng


# ══════════════════════════════════════════════════════════════════════════════
#  1. Metadata
# ══════════════════════════════════════════════════════════════════════════════

def test_lounge_scene_metadata():
    """SCENE_METADATA must reflect Velvet Pit v0.68 branding."""
    from content.scenes.lounge.lounge_scene import LoungeScene
    meta = LoungeScene.SCENE_METADATA
    assert meta["display_name"] == "THE VELVET PIT"
    assert meta["accent_color"] == "#f59e0b"
    assert meta["port"] == 5557
    assert meta["version"] == "0.68"
    assert meta["codename"] == "Dark Renaissance"


def test_lounge_package_metadata():
    """Package-level SCENE_METADATA must export correct values."""
    from content.scenes.lounge import SCENE_METADATA
    assert SCENE_METADATA["name"] == "lounge"
    assert SCENE_METADATA["display_name"] == "THE VELVET PIT"
    assert SCENE_METADATA["accent_color"] == "#f59e0b"
    assert SCENE_METADATA["accent_rgb"] == "245 158 11"


# ══════════════════════════════════════════════════════════════════════════════
#  2. Skill registration
# ══════════════════════════════════════════════════════════════════════════════

def test_lounge_skills_registered():
    """All Velvet Pit skills must be registered in the skill registry."""
    from engine.skills.registry import SKILL_REGISTRY
    import content.scenes.lounge.lounge_skills  # noqa — trigger registration

    skill_names = [t.__name__ for t in SKILL_REGISTRY.get_pack_tools("lounge")]

    assert "lounge_atmosphere" in skill_names
    assert "buy_drink"         in skill_names
    assert "approach_npc"      in skill_names
    assert "lounge_events"     in skill_names
    assert "heat_level"        in skill_names


# ══════════════════════════════════════════════════════════════════════════════
#  3. lounge_atmosphere skill
# ══════════════════════════════════════════════════════════════════════════════

def test_lounge_atmosphere_skill():
    """lounge_atmosphere() must return a non-empty string without an active scene."""
    from content.scenes.lounge.lounge_skills import lounge_atmosphere
    with patch("content.scenes.lounge.lounge_skills._get_lounge_scene", return_value=None):
        result = lounge_atmosphere()
    assert isinstance(result, str)
    assert len(result) > 0


def test_lounge_atmosphere_with_mock_scene():
    """lounge_atmosphere() includes heat and trust info when scene is active."""
    mock_scene = MagicMock()
    mock_scene.heat_level   = 55
    mock_scene.guest_trust  = 30
    mock_scene.current_song = {"title": "Blue Smoke"}
    mock_scene.world_time_slot = "MIDNIGHT RUSH"
    mock_scene.seating_map  = [{"occupied": True}, {"occupied": False}]

    with patch("content.scenes.lounge.lounge_skills._get_lounge_scene", return_value=mock_scene):
        from content.scenes.lounge.lounge_skills import lounge_atmosphere
        result = lounge_atmosphere()

    assert "55" in result            # heat
    assert "30" in result            # trust
    assert "Blue Smoke" in result
    assert "MIDNIGHT RUSH" in result


# ══════════════════════════════════════════════════════════════════════════════
#  4. buy_drink skill
# ══════════════════════════════════════════════════════════════════════════════

def test_buy_drink_skill():
    """buy_drink() returns error string for unknown drink, not an exception."""
    with patch("content.scenes.lounge.lounge_skills._get_lounge_scene", return_value=None):
        from content.scenes.lounge.lounge_skills import buy_drink
        result = buy_drink("unknown_drink_xyz")
    assert isinstance(result, str)
    assert "Unknown" in result or "menu" in result.lower()


def test_buy_drink_trust_gate():
    """buy_drink() blocks low-trust orders for premium pours."""
    from content.scenes.lounge.lounge_skills import buy_drink
    mock_scene = MagicMock()
    mock_scene.guest_trust = 0  # absinthe requires trust >= 55
    with patch("content.scenes.lounge.lounge_skills._get_lounge_scene", return_value=mock_scene):
        result = buy_drink("absinthe")
    assert "trust" in result.lower() or "requires" in result.lower() or "shakes" in result.lower()


# ══════════════════════════════════════════════════════════════════════════════
#  5. Asset files exist
# ══════════════════════════════════════════════════════════════════════════════

def test_lounge_html_exists():
    """lounge.html template must exist."""
    html = LOUNGE_DIR / "templates" / "lounge.html"
    assert html.exists(), f"Missing: {html}"


def test_lounge_css_exists():
    """lounge.css static file must exist."""
    css = LOUNGE_DIR / "static" / "lounge.css"
    assert css.exists(), f"Missing: {css}"


def test_lounge_js_exists():
    """lounge.js static file must exist."""
    js = LOUNGE_DIR / "static" / "lounge.js"
    assert js.exists(), f"Missing: {js}"


# ══════════════════════════════════════════════════════════════════════════════
#  6. HTML / JS / CSS content checks
# ══════════════════════════════════════════════════════════════════════════════

def test_lounge_html_branding():
    """lounge.html must contain Velvet Pit branding and data-scene attribute."""
    html = (LOUNGE_DIR / "templates" / "lounge.html").read_text(encoding="utf-8")
    assert "VELVET PIT"      in html
    assert 'data-scene="lounge"' in html
    assert "heat-meter"      in html
    assert "seating-map"     in html


def test_lounge_js_class():
    """lounge.js must define VelvetPitScene class with required methods."""
    js = (LOUNGE_DIR / "static" / "lounge.js").read_text(encoding="utf-8")
    assert "class VelvetPitScene" in js
    assert "_updateHeatMeter"     in js
    assert "_renderSeatingMap"    in js
    assert "approachTable"        in js
    assert "orderDrink"           in js
    assert "sendMessage"          in js


def test_lounge_css_amber_theme():
    """lounge.css must use amber accent colour #f59e0b."""
    css = (LOUNGE_DIR / "static" / "lounge.css").read_text(encoding="utf-8")
    assert "#f59e0b"     in css
    assert "heat-meter"  in css
    assert "seating-map" in css
    assert "table-node"  in css
    assert "lounge-bar"  in css
    assert "time-badge"  in css
    assert "drink-menu"  in css


# ── World State wiring ─────────────────────────────────────────────────────

def test_world_state_wired_lounge():
    """LoungeScene has _on_world_tick and _on_time_change methods."""
    from content.scenes.lounge.lounge_scene import LoungeScene
    assert hasattr(LoungeScene, "_on_world_tick")
    assert hasattr(LoungeScene, "_on_time_change")


def test_lounge_tick_emits_ambient_update():
    """_on_world_tick emits ambient_update socket event."""
    src = (LOUNGE_DIR / "lounge_scene.py").read_text(encoding="utf-8")
    assert "ambient_update" in src
    assert "_on_world_tick" in src
