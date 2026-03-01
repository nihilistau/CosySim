"""
Tests for THE OBSCURA — Gallery Scene v0.68 "Dark Renaissance" revamp.

Covers:
  - SCENE_METADATA reflects THE OBSCURA rebrand (display_name, port, accent)
  - All static assets exist (gallery.html, gallery.css, gallery.js)
  - gallery.js contains ObscuraScene class
  - gallery.html carries data-scene="gallery" and Socket.IO
  - gallery_skills.py defines all 4 Obscura skill functions
  - browse_gallery() and view_artwork() return well-formed strings
  - OBSCURA_PIECES constant is exported and well-structured
  - __init__.py re-exports THE OBSCURA metadata
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Path constants ─────────────────────────────────────────────────────────────

GALLERY_ROOT  = Path(__file__).parent.parent / "content" / "scenes" / "gallery"
STATIC_ROOT   = GALLERY_ROOT / "static"
TEMPLATE_ROOT = GALLERY_ROOT / "templates"


# ── Import helpers ─────────────────────────────────────────────────────────────

def _import_gallery_scene():
    """
    Load gallery_scene module with all heavy external deps mocked out.
    Returns the module object so tests can inspect its attributes.

    Uses real stub classes (not MagicMock instances) for the three base classes so
    that Python's class machinery doesn't hit a metaclass conflict when creating
    GalleryScene(BaseScene, MCPSceneMixin, NexusSceneMixin, mcp_scene_id=...).
    Module is pre-registered in sys.modules so @dataclass can resolve cls.__module__.
    """
    import sys as _sys

    # ── Stub base classes (regular Python classes, no metaclass conflicts) ──
    class _FakeBaseScene:
        def __init__(self, scene_name="", host="0.0.0.0", port=5560, **kw):
            pass
        def register_health_route(self, app): pass
        def register_bench_route(self, app, sio=None): pass
        def register_tts_route(self, app): pass
        def inject_navbar_context(self): return {}
        def get_health(self): return {"ok": True, "scene": "gallery"}

    class _FakeMCPSceneMixin:
        """Absorbs mcp_scene_id keyword in __init_subclass__."""
        def __init_subclass__(cls, mcp_scene_id=None, **kw):
            super().__init_subclass__(**kw)
        def _mcp_init(self): pass

    class _FakeNexusMixin:
        def nexus_init(self, name): pass
        def nexus_flush(self): pass

    fake_base = MagicMock()
    fake_base.BaseScene = _FakeBaseScene
    fake_base.get_active_scene = MagicMock(return_value=None)

    fake_mcp = MagicMock()
    fake_mcp.MCPSceneMixin = _FakeMCPSceneMixin
    fake_mcp.get_framework = MagicMock(return_value=MagicMock())

    fake_nexus = MagicMock()
    fake_nexus.NexusSceneMixin = _FakeNexusMixin

    mocks = {
        "flask":                                  MagicMock(),
        "flask_socketio":                         MagicMock(),
        "flask_cors":                             MagicMock(),
        "engine.paths":                           MagicMock(ROOT=Path(".")),
        "engine.scenes.base_scene":               fake_base,
        "engine.scenes.nexus_mixin":              fake_nexus,
        "engine.mcp.framework":                   fake_mcp,
        "engine.mcp.scene_state":                 MagicMock(),
        "engine.mcp.tag_registry":                MagicMock(),
        "engine.overlay":                         MagicMock(),
        "content.simulation.database.db":         MagicMock(),
        "content.shared":                         MagicMock(),
        "content.scenes.gallery.gallery_rules":   MagicMock(),
    }
    with patch.dict("sys.modules", mocks):
        spec = importlib.util.spec_from_file_location(
            "gallery_scene_test", GALLERY_ROOT / "gallery_scene.py"
        )
        mod = importlib.util.module_from_spec(spec)
        # Pre-register so @dataclass can resolve sys.modules[cls.__module__]
        _sys.modules[spec.name] = mod
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        finally:
            _sys.modules.pop(spec.name, None)
        return mod


def _import_gallery_skills(scene_mod=None):
    """
    Load gallery_skills module with engine deps mocked.
    If scene_mod is provided it is injected as content.scenes.gallery.gallery_scene
    so that `from content.scenes.gallery.gallery_scene import OBSCURA_PIECES` resolves.

    The @skill decorator mock is configured as a pass-through so the actual skill
    functions remain callable and return their real string results.
    """
    import sys as _sys

    def _passthrough_skill(*args, **kwargs):
        """Return the wrapped function unchanged (identity decorator)."""
        def decorator(fn):
            return fn
        return decorator

    skill_module_mock = MagicMock()
    skill_module_mock.skill = _passthrough_skill
    # SkillCategory can stay as MagicMock — only used as annotation value

    extra: dict = {}
    if scene_mod is not None:
        extra["content.scenes.gallery.gallery_scene"] = scene_mod
    mocks = {
        "engine.skills.skill":      skill_module_mock,
        "engine.scenes.base_scene": MagicMock(),
        **extra,
    }
    with patch.dict("sys.modules", mocks):
        spec = importlib.util.spec_from_file_location(
            "gallery_skills_test", GALLERY_ROOT / "gallery_skills.py"
        )
        mod = importlib.util.module_from_spec(spec)
        _sys.modules[spec.name] = mod
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        finally:
            _sys.modules.pop(spec.name, None)
        return mod


# ══════════════════════════════════════════════════════════════════════════════
#  1. SCENE METADATA
# ══════════════════════════════════════════════════════════════════════════════

class TestGallerySceneMetadata:
    """SCENE_METADATA in gallery_scene.py reflects the THE OBSCURA rebrand."""

    def _src(self) -> str:
        return (GALLERY_ROOT / "gallery_scene.py").read_text(encoding="utf-8")

    def test_gallery_scene_metadata(self):
        """SCENE_METADATA must declare display_name, port, accent_color."""
        src = self._src()
        assert '"display_name": "THE OBSCURA"' in src or "'display_name': 'THE OBSCURA'" in src, \
            "SCENE_METADATA display_name must be 'THE OBSCURA'"
        assert '"port": 5560' in src or "'port': 5560" in src, \
            "SCENE_METADATA port must be 5560"
        assert '"accent_color": "#7c3aed"' in src or "'accent_color': '#7c3aed'" in src, \
            "SCENE_METADATA accent_color must be #7c3aed"

    def test_gallery_metadata_port_5560(self):
        """Gallery scene must declare port 5560 in SCENE_METADATA."""
        src = self._src()
        assert '"port": 5560' in src or "'port': 5560" in src, \
            "Port 5560 not found in SCENE_METADATA"

    def test_gallery_metadata_accent_rgb(self):
        """Violet accent_rgb '124 58 237' must be present in gallery_scene.py."""
        src = self._src()
        assert "124 58 237" in src, \
            "accent_rgb '124 58 237' not found in gallery_scene.py"

    def test_gallery_display_name_in_init(self):
        """__init__.py must reference THE OBSCURA for registry discoverability."""
        init_src = (GALLERY_ROOT / "__init__.py").read_text(encoding="utf-8")
        assert "THE OBSCURA" in init_src, \
            "__init__.py must contain 'THE OBSCURA' in SCENE_METADATA"

    def test_init_exports_scene_metadata(self):
        """__init__.py must export SCENE_METADATA symbol."""
        init_src = (GALLERY_ROOT / "__init__.py").read_text(encoding="utf-8")
        assert "SCENE_METADATA" in init_src, \
            "SCENE_METADATA not found in __init__.py"


# ══════════════════════════════════════════════════════════════════════════════
#  2. STATIC ASSETS
# ══════════════════════════════════════════════════════════════════════════════

class TestStaticAssets:
    """All THE OBSCURA static files exist at the expected paths."""

    def test_gallery_html_exists(self):
        """templates/gallery.html must be present."""
        assert (TEMPLATE_ROOT / "gallery.html").is_file(), \
            "gallery.html not found at templates/gallery.html"

    def test_gallery_css_exists(self):
        """static/gallery.css must be present."""
        assert (STATIC_ROOT / "gallery.css").is_file(), \
            "gallery.css not found at static/gallery.css"

    def test_gallery_js_exists(self):
        """static/gallery.js must be present."""
        assert (STATIC_ROOT / "gallery.js").is_file(), \
            "gallery.js not found at static/gallery.js"

    def test_gallery_js_obscura_class(self):
        """gallery.js must define class ObscuraScene."""
        src = (STATIC_ROOT / "gallery.js").read_text(encoding="utf-8")
        assert "class ObscuraScene" in src, \
            "ObscuraScene class not found in gallery.js"

    def test_gallery_js_required_methods(self):
        """gallery.js must expose key public methods."""
        src = (STATIC_ROOT / "gallery.js").read_text(encoding="utf-8")
        for method in ("init", "loadGallery", "viewPiece", "requestPrivateViewing",
                       "commissionWork", "_renderPieces", "_openDetailPanel", "sendMessage"):
            assert method in src, f"Method '{method}' not found in gallery.js"

    def test_gallery_html_data_scene(self):
        """gallery.html must carry data-scene='gallery'."""
        src = (TEMPLATE_ROOT / "gallery.html").read_text(encoding="utf-8")
        assert 'data-scene="gallery"' in src, \
            "data-scene='gallery' not found in gallery.html"

    def test_gallery_html_socketio_cdn(self):
        """gallery.html must load the Socket.IO CDN script."""
        src = (TEMPLATE_ROOT / "gallery.html").read_text(encoding="utf-8")
        assert "socket.io" in src, \
            "Socket.IO CDN script not found in gallery.html"

    def test_gallery_html_navbar_include(self):
        """gallery.html must include navbar_v2.html."""
        src = (TEMPLATE_ROOT / "gallery.html").read_text(encoding="utf-8")
        assert "navbar_v2.html" in src, \
            "navbar_v2.html include not found in gallery.html"

    def test_gallery_css_violet_accent(self):
        """gallery.css must declare violet accent variable."""
        src = (STATIC_ROOT / "gallery.css").read_text(encoding="utf-8")
        assert "#7c3aed" in src, \
            "Violet accent #7c3aed not found in gallery.css"

    def test_gallery_css_required_selectors(self):
        """gallery.css must define all required selectors."""
        src = (STATIC_ROOT / "gallery.css").read_text(encoding="utf-8")
        for selector in (
            ".gallery-floor",
            ".artwork-frame",
            ".spotlight",
            ".artwork-title",
            ".intensity-badge",
            ".detail-panel",
            ".private-viewing-blur",
            ".commission-form",
        ):
            assert selector in src, f"CSS selector '{selector}' not found in gallery.css"


# ══════════════════════════════════════════════════════════════════════════════
#  3. GALLERY SKILLS
# ══════════════════════════════════════════════════════════════════════════════

class TestGallerySkills:
    """THE OBSCURA gallery skills are defined and callable."""

    def _skills_src(self) -> str:
        return (GALLERY_ROOT / "gallery_skills.py").read_text(encoding="utf-8")

    def test_gallery_skills_registered(self):
        """All 4 Obscura skill function signatures must exist in gallery_skills.py."""
        src = self._skills_src()
        for fn in ("browse_gallery", "view_artwork", "commission_artwork",
                   "request_private_viewing"):
            assert f"def {fn}" in src, \
                f"Skill function '{fn}' not found in gallery_skills.py"

    def test_browse_gallery_skill(self):
        """browse_gallery() returns a non-empty string containing collection info."""
        scene_mod = _import_gallery_scene()
        skills_mod = _import_gallery_skills(scene_mod)
        result = skills_mod.browse_gallery()
        assert isinstance(result, str), "browse_gallery() must return a string"
        assert len(result) > 20, "browse_gallery() returned unexpectedly short output"

    def test_view_artwork_skill_valid(self):
        """view_artwork('ob_001') returns a string with title and commentary."""
        scene_mod = _import_gallery_scene()
        skills_mod = _import_gallery_skills(scene_mod)
        result = skills_mod.view_artwork("ob_001")
        assert isinstance(result, str), "view_artwork() must return a string"
        # Should mention the piece (title or at least curator note)
        assert len(result) > 30, "view_artwork() returned unexpectedly short output"

    def test_view_artwork_skill_invalid(self):
        """view_artwork() on an unknown ID returns a helpful error message."""
        scene_mod = _import_gallery_scene()
        skills_mod = _import_gallery_skills(scene_mod)
        result = skills_mod.view_artwork("ob_999_nonexistent")
        assert isinstance(result, str)
        lower = result.lower()
        assert "not found" in lower or "available" in lower, \
            f"Expected 'not found'/'available' in error message, got: {result!r}"

    def test_commission_artwork_skill(self):
        """commission_artwork() returns a string acknowledgement."""
        scene_mod = _import_gallery_scene()
        skills_mod = _import_gallery_skills(scene_mod)
        result = skills_mod.commission_artwork("A figure dissolving into shadow", 2)
        assert isinstance(result, str)
        assert "commission" in result.lower() or "obscura" in result.lower(), \
            "commission_artwork() response should mention commission or Obscura"

    def test_request_private_viewing_skill_missing_piece(self):
        """request_private_viewing() on unknown piece_id returns error."""
        scene_mod = _import_gallery_scene()
        skills_mod = _import_gallery_skills(scene_mod)
        result = skills_mod.request_private_viewing("ob_FAKE")
        assert isinstance(result, str)
        assert "not found" in result.lower() or "permanent collection" in result.lower(), \
            f"Expected not-found error for unknown piece, got: {result!r}"

    def test_request_private_viewing_non_adult_piece(self):
        """request_private_viewing() on a non-adult piece returns early gracefully."""
        scene_mod = _import_gallery_scene()
        skills_mod = _import_gallery_skills(scene_mod)
        # ob_002 is non-adult
        result = skills_mod.request_private_viewing("ob_002")
        assert isinstance(result, str)
        assert "private viewing" in result.lower() or "not require" in result.lower()


# ══════════════════════════════════════════════════════════════════════════════
#  4. OBSCURA_PIECES constant
# ══════════════════════════════════════════════════════════════════════════════

class TestObscuraPieces:
    """OBSCURA_PIECES is defined, exported, and structurally valid."""

    def test_obscura_pieces_in_source(self):
        """gallery_scene.py must define OBSCURA_PIECES."""
        src = (GALLERY_ROOT / "gallery_scene.py").read_text(encoding="utf-8")
        assert "OBSCURA_PIECES" in src, \
            "OBSCURA_PIECES not found in gallery_scene.py"

    def test_obscura_pieces_count(self):
        """OBSCURA_PIECES must contain at least 6 pieces."""
        mod = _import_gallery_scene()
        pieces = getattr(mod, "OBSCURA_PIECES", None)
        assert pieces is not None, "OBSCURA_PIECES not exported from gallery_scene"
        assert len(pieces) >= 6, \
            f"Expected ≥ 6 OBSCURA_PIECES, got {len(pieces)}"

    def test_obscura_pieces_required_keys(self):
        """Every piece must have: id, title, adult, tags, intensity, description."""
        mod = _import_gallery_scene()
        required = {"id", "title", "adult", "tags", "intensity", "description"}
        for piece in mod.OBSCURA_PIECES:
            missing = required - piece.keys()
            assert not missing, \
                f"Piece '{piece.get('id', '?')}' missing required keys: {missing}"

    def test_obscura_pieces_ids_unique(self):
        """Every piece must have a unique id."""
        mod = _import_gallery_scene()
        ids = [p["id"] for p in mod.OBSCURA_PIECES]
        assert len(ids) == len(set(ids)), \
            f"Duplicate piece IDs found: {[i for i in ids if ids.count(i) > 1]}"

    def test_obscura_pieces_adult_flag_type(self):
        """Every piece 'adult' field must be a bool."""
        mod = _import_gallery_scene()
        for piece in mod.OBSCURA_PIECES:
            assert isinstance(piece["adult"], bool), \
                f"Piece '{piece['id']}' adult field must be bool, got {type(piece['adult'])}"

    def test_obscura_pieces_intensity_range(self):
        """Every piece intensity must be 1–3."""
        mod = _import_gallery_scene()
        for piece in mod.OBSCURA_PIECES:
            assert 1 <= piece["intensity"] <= 3, \
                f"Piece '{piece['id']}' intensity {piece['intensity']} out of 1–3 range"
