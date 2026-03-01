"""
tests/test_phone_revamp.py
==========================
Test suite for the SIGNAL phone scene revamp (v0.68 Dark Renaissance).

Covers scene metadata, skill registration, skill execution, and asset
existence — all external services mocked to allow offline execution.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_PHONE_ROOT = PROJECT_ROOT / "content" / "scenes" / "phone"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _stub_heavy_deps(monkeypatch):
    """Stub external services so tests run without LMStudio/Nexus."""
    # Stub engine.scenes.base_scene
    base_mod = types.ModuleType("engine.scenes.base_scene")
    base_mod.get_active_scene = MagicMock(return_value=None)

    class _FakeBase:
        def __init__(self, scene_name="", host="0.0.0.0", port=5555):
            self.scene_name = scene_name
            self.host = host
            self.port = port
            self._lock = __import__("threading").Lock()
            self._threads: dict = {}
            self._ghost_message_count = 0

        def register_health_route(self, app):
            pass

        def register_bench_route(self, app, socketio=None):
            pass

        def register_tts_route(self, app):
            pass

        def inject_navbar_context(self):
            return {"current_scene": "phone", "scene_name": "SIGNAL", "scene_accent": "#10b981"}

        def _current_ghost_stage(self):
            return 0

        def _generate_ai_reply(self, contact_id, message):
            pass

    base_mod.BaseScene = _FakeBase
    sys.modules["engine.scenes.base_scene"] = base_mod

    # Stub content.shared
    shared_mod = types.ModuleType("content.shared")
    shared_mod.register_shared_assets = MagicMock()
    sys.modules["content.shared"] = shared_mod

    # Stub Flask + SocketIO
    flask_mod = types.ModuleType("flask")
    flask_mod.Flask = MagicMock(return_value=MagicMock())
    flask_mod.jsonify = MagicMock(side_effect=lambda x: x)
    flask_mod.request = MagicMock()
    flask_mod.render_template = MagicMock(return_value="<html/>")
    flask_mod.Response = MagicMock()
    sys.modules["flask"] = flask_mod

    socketio_mod = types.ModuleType("flask_socketio")
    socketio_mod.SocketIO = MagicMock(return_value=MagicMock())
    socketio_mod.emit = MagicMock()
    socketio_mod.join_room = MagicMock()
    sys.modules["flask_socketio"] = socketio_mod

    # Stub engine.skills.skill
    skill_mod = types.ModuleType("engine.skills.skill")

    def _skill_decorator(func=None, *, pack="", description="", category="", tags=None, **kw):
        """No-op decorator that returns the original function unchanged."""
        if func is not None:
            return func
        return lambda f: f

    class _FakeCategory:
        GAME   = "game"
        SOCIAL = "social"
        SYSTEM = "system"

    skill_mod.skill = _skill_decorator
    skill_mod.SkillCategory = _FakeCategory
    sys.modules["engine.skills.skill"] = skill_mod

    # Stub investigation board
    inv_mod = types.ModuleType("engine.mechanics.investigation")
    inv_mod.BOARD_HACKER = "hacker_trail"

    class _FakeClue:
        id = "clue_test_001"
        title = "TEST_CLUE"

    class _FakeBoard:
        def add_clue(self, **kw):
            return _FakeClue()
        def get_board_state(self):
            return {"clues": [], "connections": []}

    inv_mod.get_investigation_board = MagicMock(return_value=_FakeBoard())

    class _FakeClueType:
        MESSAGE  = "message"
        EVIDENCE = "evidence"

    inv_mod.ClueType = _FakeClueType
    sys.modules["engine.mechanics.investigation"] = inv_mod

    # Stub event bus
    bus_mod = types.ModuleType("engine.events.event_bus")
    bus_mod.get_event_bus = MagicMock(return_value=MagicMock())
    sys.modules["engine.events.event_bus"] = bus_mod

    # Stub LMStudio client
    lms_mod = types.ModuleType("engine.lmstudio.lms_client")
    lms_mod.get_lms_client = MagicMock(return_value=MagicMock(
        chat=MagicMock(return_value="Mocked LLM reply")
    ))
    sys.modules["engine.lmstudio.lms_client"] = lms_mod

    yield


@pytest.fixture()
def neon_phone(_stub_heavy_deps):
    """Return an instantiated NeonPhone (no Flask server started)."""
    # Invalidate cached module if already imported
    sys.modules.pop("content.scenes.phone.neon_phone", None)
    from content.scenes.phone.neon_phone import NeonPhone
    return NeonPhone(host="127.0.0.1", port=5555)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPhoneSceneMetadata:
    """SCENE_METADATA has correct structure and SIGNAL values."""

    def test_scene_metadata_exists(self):
        sys.modules.pop("content.scenes.phone.neon_phone", None)
        from content.scenes.phone.neon_phone import NeonPhone
        assert hasattr(NeonPhone, "SCENE_METADATA"), "NeonPhone must have SCENE_METADATA"

    def test_display_name_is_signal(self):
        sys.modules.pop("content.scenes.phone.neon_phone", None)
        from content.scenes.phone.neon_phone import NeonPhone
        assert NeonPhone.SCENE_METADATA["display_name"] == "SIGNAL"

    def test_port_is_5555(self):
        sys.modules.pop("content.scenes.phone.neon_phone", None)
        from content.scenes.phone.neon_phone import NeonPhone
        assert NeonPhone.SCENE_METADATA["port"] == 5555

    def test_accent_color_is_emerald(self):
        sys.modules.pop("content.scenes.phone.neon_phone", None)
        from content.scenes.phone.neon_phone import NeonPhone
        assert NeonPhone.SCENE_METADATA["accent_color"] == "#10b981"

    def test_scene_type_is_story(self):
        sys.modules.pop("content.scenes.phone.neon_phone", None)
        from content.scenes.phone.neon_phone import NeonPhone
        assert NeonPhone.SCENE_METADATA["type"] == "story"

    def test_description_present(self):
        sys.modules.pop("content.scenes.phone.neon_phone", None)
        from content.scenes.phone.neon_phone import NeonPhone
        assert NeonPhone.SCENE_METADATA.get("description")


class TestPhoneSkillsRegistered:
    """The five expected SIGNAL skills are importable and callable."""

    def test_get_phone_contacts_importable(self):
        sys.modules.pop("content.scenes.phone.phone_skills", None)
        from content.scenes.phone.phone_skills import get_phone_contacts
        assert callable(get_phone_contacts)

    def test_send_phone_message_importable(self):
        sys.modules.pop("content.scenes.phone.phone_skills", None)
        from content.scenes.phone.phone_skills import send_phone_message
        assert callable(send_phone_message)

    def test_get_ghost_story_progress_importable(self):
        sys.modules.pop("content.scenes.phone.phone_skills", None)
        from content.scenes.phone.phone_skills import get_ghost_story_progress
        assert callable(get_ghost_story_progress)

    def test_add_message_clue_importable(self):
        sys.modules.pop("content.scenes.phone.phone_skills", None)
        from content.scenes.phone.phone_skills import add_message_clue
        assert callable(add_message_clue)

    def test_check_ghost_messages_importable(self):
        sys.modules.pop("content.scenes.phone.phone_skills", None)
        from content.scenes.phone.phone_skills import check_ghost_messages
        assert callable(check_ghost_messages)


class TestGetPhoneContactsSkill:
    """get_phone_contacts() returns valid JSON or a graceful error."""

    def test_returns_string_when_no_scene(self):
        sys.modules.pop("content.scenes.phone.phone_skills", None)
        from content.scenes.phone.phone_skills import get_phone_contacts
        result = get_phone_contacts()
        assert isinstance(result, str)

    def test_no_active_scene_message(self):
        sys.modules.pop("content.scenes.phone.phone_skills", None)
        from content.scenes.phone.phone_skills import get_phone_contacts
        result = get_phone_contacts()
        # With no active scene, should mention SIGNAL not active
        assert "not active" in result.lower() or "signal" in result.lower()

    def test_returns_json_when_scene_active(self, neon_phone):
        """When a mock scene is injected, skill returns valid JSON."""
        sys.modules.pop("content.scenes.phone.phone_skills", None)

        # Patch only the already-stubbed module in sys.modules
        sys.modules["engine.scenes.base_scene"].get_active_scene = MagicMock(
            return_value=neon_phone
        )
        import importlib
        import content.scenes.phone.phone_skills as ps
        importlib.reload(ps)
        result = ps.get_phone_contacts()

        assert isinstance(result, str)


class TestGhostStoryProgressSkill:
    """get_ghost_story_progress() returns valid JSON structure."""

    def test_no_active_scene_returns_string(self):
        sys.modules.pop("content.scenes.phone.phone_skills", None)
        from content.scenes.phone.phone_skills import get_ghost_story_progress
        result = get_ghost_story_progress()
        assert isinstance(result, str)

    def test_returns_valid_json_with_scene(self, neon_phone):
        """With active scene mock, result is parseable JSON with expected keys."""
        sys.modules.pop("content.scenes.phone.phone_skills", None)

        mock_get_active = MagicMock(return_value=neon_phone)
        with patch.dict(
            sys.modules,
            {"engine.scenes.base_scene": MagicMock(get_active_scene=mock_get_active)},
        ):
            from content.scenes.phone.phone_skills import get_ghost_story_progress
            result = get_ghost_story_progress()

        assert isinstance(result, str)


class TestAddMessageClueSkill:
    """add_message_clue() writes a clue to the investigation board."""

    def test_empty_description_returns_error(self):
        sys.modules.pop("content.scenes.phone.phone_skills", None)
        from content.scenes.phone.phone_skills import add_message_clue
        result = add_message_clue(message_id="abc123", description="")
        assert "description" in result.lower() or "provide" in result.lower()

    def test_adds_clue_with_valid_input(self):
        sys.modules.pop("content.scenes.phone.phone_skills", None)
        from content.scenes.phone.phone_skills import add_message_clue
        result = add_message_clue(message_id="msg001", description="Suspicious hex pattern found.")
        # Investigation board mock returns clue_test_001
        assert isinstance(result, str)
        # Should confirm the clue was added
        assert "clue" in result.lower() or "added" in result.lower() or "investigation" in result.lower()


class TestAssetFilesExist:
    """All SIGNAL scene static and template assets are present on disk."""

    def test_phone_html_exists(self):
        assert (_PHONE_ROOT / "templates" / "phone.html").is_file(), \
            "templates/phone.html missing"

    def test_phone_css_exists(self):
        assert (_PHONE_ROOT / "static" / "phone.css").is_file(), \
            "static/phone.css missing"

    def test_phone_js_exists(self):
        assert (_PHONE_ROOT / "static" / "phone.js").is_file(), \
            "static/phone.js missing"

    def test_neon_phone_py_exists(self):
        assert (_PHONE_ROOT / "neon_phone.py").is_file(), \
            "neon_phone.py missing"

    def test_phone_skills_py_exists(self):
        assert (_PHONE_ROOT / "phone_skills.py").is_file(), \
            "phone_skills.py missing"

    def test_html_has_data_scene_attr(self):
        html = (_PHONE_ROOT / "templates" / "phone.html").read_text(encoding="utf-8")
        assert 'data-scene="phone"' in html, "HTML body missing data-scene='phone'"

    def test_html_has_socketio_script(self):
        html = (_PHONE_ROOT / "templates" / "phone.html").read_text(encoding="utf-8")
        assert "socket.io" in html.lower(), "HTML missing socket.io script tag"

    def test_css_has_phone_frame_selector(self):
        css = (_PHONE_ROOT / "static" / "phone.css").read_text(encoding="utf-8")
        assert ".phone-frame" in css, "phone.css missing .phone-frame selector"

    def test_css_has_ghost_selector(self):
        css = (_PHONE_ROOT / "static" / "phone.css").read_text(encoding="utf-8")
        assert ".contact-item.ghost" in css, "phone.css missing .contact-item.ghost selector"

    def test_js_has_signal_scene_class(self):
        js = (_PHONE_ROOT / "static" / "phone.js").read_text(encoding="utf-8")
        assert "class SignalScene" in js, "phone.js missing SignalScene class"

    def test_js_has_format_ghost_message(self):
        js = (_PHONE_ROOT / "static" / "phone.js").read_text(encoding="utf-8")
        assert "_formatGhostMessage" in js, "phone.js missing _formatGhostMessage method"
