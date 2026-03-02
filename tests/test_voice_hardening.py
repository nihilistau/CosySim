"""TTS/voice hardening tests — Track D.

Covers:
    - BaseScene.register_tts_route exists and is callable
    - Each of the 9 active scenes has register_tts_route wired in its source
    - register_tts_route mounts /api/tts/speak, /api/tts/voices, /api/tts/audio/<id>
    - /api/tts/speak returns 503 gracefully when TTS backend is unavailable
    - VoiceManager JS uses cosysim_tts_enabled key (default true)
    - VoiceManager JS uses cosysim_stt_enabled key (default false)
    - VoiceManager JS includes enableSTT/disableSTT methods
    - Admin overlay HTML contains the [SYSTEM] tab and voice toggles
    - All 9 scene HTML templates include cosysim-voice.js
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

# ── Paths ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
SCENES_DIR = ROOT / "content" / "scenes"
SHARED_JS = ROOT / "content" / "shared" / "static" / "js"
SHARED_TMPL = ROOT / "content" / "shared" / "templates"


# ══════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════

def _scene_source(scene_name: str) -> str:
    """Return concatenated source of all .py files in a scene directory."""
    scene_dir = SCENES_DIR / scene_name
    parts = []
    for py_file in scene_dir.rglob("*.py"):
        try:
            parts.append(py_file.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            pass
    return "\n".join(parts)


def _primary_template(scene_name: str) -> str:
    """Return content of the primary (main-route) HTML template for a scene."""
    tmpl_dir = SCENES_DIR / scene_name / "templates"
    # Prefer the plain {name}.html (main route) over _ui variants
    candidates = [
        tmpl_dir / f"{scene_name}.html",
        tmpl_dir / f"phone_ui_v2.html",      # phone special case
        tmpl_dir / f"{scene_name}_ui_v2.html",
        tmpl_dir / f"{scene_name}_ui.html",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
    # fallback: read all templates and concatenate
    all_html = []
    for f in tmpl_dir.glob("*.html"):
        all_html.append(f.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(all_html)


# ══════════════════════════════════════════════════════════════════════
#  BaseScene — register_tts_route contract
# ══════════════════════════════════════════════════════════════════════

class TestBaseSceneRegisterTTSRoute:
    """register_tts_route must exist on BaseScene and mount the 3 endpoints."""

    def test_method_exists(self):
        """BaseScene must have a register_tts_route attribute."""
        from engine.scenes.base_scene import BaseScene
        assert hasattr(BaseScene, "register_tts_route")

    def test_method_is_callable(self):
        """register_tts_route must be callable."""
        from engine.scenes.base_scene import BaseScene
        assert callable(BaseScene.register_tts_route)

    @pytest.fixture
    def tts_app(self):
        """Minimal Flask app with TTS routes wired via BaseScene."""
        from engine.scenes.base_scene import BaseScene

        class _ConcreteScene(BaseScene):
            def start(self) -> None:
                pass
            def stop(self) -> None:
                pass
            def get_plugin_info(self):
                return {}

        app = Flask(__name__)
        app.config["TESTING"] = True

        with (
            patch("engine.scenes.base_scene.BaseScene._mcp_register_scene"),
            patch("engine.assets.AssetManager.__init__", return_value=None),
        ):
            scene = _ConcreteScene.__new__(_ConcreteScene)
            scene.scene_name = "test"
            scene.host = "0.0.0.0"
            scene.port = 9999
            scene.active_characters = {}
            scene.scene_config = {"name": "test", "created_at": "", "characters": [], "settings": {}}
            scene.scene_asset_id = None
            scene.streaming_enabled = True
            scene._active_streams = 0
            scene._total_stream_tokens = 0
            scene.scene_metadata = {}
            scene.asset_manager = MagicMock()
            scene.register_tts_route(app)

        return app.test_client()

    def test_speak_route_exists(self, tts_app):
        """POST /api/tts/speak must be registered."""
        resp = tts_app.post(
            "/api/tts/speak",
            json={},
            content_type="application/json",
        )
        # 400 (no text) proves the route exists
        assert resp.status_code in (400, 503)

    def test_speak_requires_text(self, tts_app):
        """POST /api/tts/speak returns 400 when text field is absent."""
        resp = tts_app.post("/api/tts/speak", json={})
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert "error" in body

    def test_voices_route_exists(self, tts_app):
        """GET /api/tts/voices must be registered and return JSON."""
        with patch("engine.tts.tts_manager.get_tts_manager") as mock_mgr:
            mock_mgr.return_value.list_backends.return_value = ["piper", "orpheus"]
            resp = tts_app.get("/api/tts/voices")
        assert resp.status_code == 200
        body = json.loads(resp.data)
        assert "voices" in body

    def test_audio_route_returns_404_for_missing(self, tts_app):
        """/api/tts/audio/<id> returns 404 for a non-existent file."""
        resp = tts_app.get("/api/tts/audio/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_speak_503_when_tts_unavailable(self, tts_app):
        """POST /api/tts/speak returns 503 when TTSManager raises."""
        with patch("engine.tts.tts_manager.get_tts_manager", side_effect=RuntimeError("no TTS")):
            resp = tts_app.post("/api/tts/speak", json={"text": "hello"})
        assert resp.status_code == 503
        body = json.loads(resp.data)
        assert "error" in body


# ══════════════════════════════════════════════════════════════════════
#  Per-scene: register_tts_route must be wired in source code
# ══════════════════════════════════════════════════════════════════════

_NINE_SCENES = [
    "bedroom", "phone", "lounge", "tavern",
    "casino", "gallery", "arena", "realm", "neoncity",
]


class TestScenesTTSWired:
    """Every active scene must call register_tts_route somewhere in its source."""

    @pytest.mark.parametrize("scene_name", _NINE_SCENES)
    def test_register_tts_route_in_source(self, scene_name: str):
        """register_tts_route must appear in the scene's Python source."""
        src = _scene_source(scene_name)
        assert "register_tts_route" in src, (
            f"Scene '{scene_name}' never calls register_tts_route. "
            f"Add `self.register_tts_route(self.app)` in start() or __init__()."
        )


# ══════════════════════════════════════════════════════════════════════
#  Per-scene: cosysim-voice.js must be in the primary template
# ══════════════════════════════════════════════════════════════════════

class TestSceneVoiceJSIncluded:
    """Every active scene's HTML template must load cosysim-voice.js."""

    @pytest.mark.parametrize("scene_name", _NINE_SCENES)
    def test_voice_js_in_template(self, scene_name: str):
        """Primary HTML template must contain a cosysim-voice.js script tag."""
        tmpl = _primary_template(scene_name)
        assert "cosysim-voice.js" in tmpl, (
            f"Scene '{scene_name}' template is missing "
            f"<script src=\"/shared/js/cosysim-voice.js\"></script>."
        )


# ══════════════════════════════════════════════════════════════════════
#  VoiceManager JS — localStorage keys and STT defaults
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def voice_js_content() -> str:
    """Raw text of cosysim-voice.js."""
    return (SHARED_JS / "cosysim-voice.js").read_text(encoding="utf-8")


class TestVoiceManagerLocalStorageKeys:
    """VoiceManager must use the canonical cosysim_* localStorage keys."""

    def test_tts_key_is_cosysim_tts_enabled(self, voice_js_content: str):
        """Constructor must read cosysim_tts_enabled (not the legacy cs_voice_enabled)."""
        assert "cosysim_tts_enabled" in voice_js_content

    def test_stt_key_is_cosysim_stt_enabled(self, voice_js_content: str):
        """Constructor must read cosysim_stt_enabled."""
        assert "cosysim_stt_enabled" in voice_js_content

    def test_tts_default_true(self, voice_js_content: str):
        """TTS enabled flag defaults to true (key !== 'false')."""
        assert "cosysim_tts_enabled') !== 'false'" in voice_js_content

    def test_stt_default_false(self, voice_js_content: str):
        """STT enabled flag defaults to false (key === 'true')."""
        assert "cosysim_stt_enabled') === 'true'" in voice_js_content

    def test_enable_method_writes_cosysim_key(self, voice_js_content: str):
        """enable() must persist using cosysim_tts_enabled."""
        assert "localStorage.setItem('cosysim_tts_enabled'" in voice_js_content

    def test_disable_method_writes_cosysim_key(self, voice_js_content: str):
        """disable() must persist using cosysim_tts_enabled."""
        assert "localStorage.setItem('cosysim_tts_enabled'" in voice_js_content

    def test_enable_stt_method_exists(self, voice_js_content: str):
        """enableSTT() method must be defined."""
        assert "enableSTT()" in voice_js_content

    def test_disable_stt_method_exists(self, voice_js_content: str):
        """disableSTT() method must be defined."""
        assert "disableSTT()" in voice_js_content

    def test_listen_guards_stt_enabled(self, voice_js_content: str):
        """listen() must check this._sttEnabled before starting recognition."""
        assert "_sttEnabled" in voice_js_content
        # Verify the guard appears before the SpeechRecognition construction
        guard_pos = voice_js_content.find("if (!this._sttEnabled)")
        speech_pos = voice_js_content.find("SpeechRecognition")
        assert 0 < guard_pos < speech_pos, (
            "listen() must check _sttEnabled before SpeechRecognition is accessed."
        )


# ══════════════════════════════════════════════════════════════════════
#  Admin overlay — System tab and voice toggles
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def admin_overlay_html() -> str:
    return (SHARED_TMPL / "admin_overlay.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def admin_overlay_js() -> str:
    return (SHARED_JS / "admin_overlay.js").read_text(encoding="utf-8")


class TestAdminOverlaySystemTab:
    """Admin overlay must expose a System tab with TTS/STT toggles."""

    def test_system_tab_button_exists(self, admin_overlay_html: str):
        """A tab button with data-tab='system' must be present."""
        assert 'data-tab="system"' in admin_overlay_html

    def test_system_tab_panel_exists(self, admin_overlay_html: str):
        """A panel div with data-tab='system' must be present."""
        assert 'id="cs-admin-panel-system"' in admin_overlay_html

    def test_tts_toggle_checkbox_exists(self, admin_overlay_html: str):
        """A checkbox with id='cs-tts-toggle' must be in the System panel."""
        assert 'id="cs-tts-toggle"' in admin_overlay_html

    def test_stt_toggle_checkbox_exists(self, admin_overlay_html: str):
        """A checkbox with id='cs-stt-toggle' must be in the System panel."""
        assert 'id="cs-stt-toggle"' in admin_overlay_html

    def test_system_case_in_switch(self, admin_overlay_js: str):
        """_loadActiveTab switch must have a 'system' case."""
        assert "case 'system'" in admin_overlay_js

    def test_load_system_method_exists(self, admin_overlay_js: str):
        """_loadSystem() method must be defined."""
        assert "_loadSystem()" in admin_overlay_js

    def test_load_system_reads_tts_key(self, admin_overlay_js: str):
        """_loadSystem must read cosysim_tts_enabled from localStorage."""
        assert "cosysim_tts_enabled" in admin_overlay_js

    def test_load_system_reads_stt_key(self, admin_overlay_js: str):
        """_loadSystem must read cosysim_stt_enabled from localStorage."""
        assert "cosysim_stt_enabled" in admin_overlay_js
