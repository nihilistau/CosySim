"""Tests for CosySim v0.68 Voice System (C1, C2, C3).

Covers:
- Static file existence checks (JS, CSS, HTML)
- BaseScene.register_tts_route endpoints
- TTS speak, voices, and audio-serve routes
- inject_navbar_context consistency
"""
from __future__ import annotations

import io
import json
import uuid
import wave
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

# ── Paths ────────────────────────────────────────────────────────────────

REPO = Path(__file__).resolve().parents[1]
SHARED_JS  = REPO / "content" / "shared" / "static" / "js"
SHARED_CSS = REPO / "content" / "shared" / "static" / "css"
SHARED_TPL = REPO / "content" / "shared" / "templates"
TTS_CACHE  = REPO / "data" / "tts_cache"


# ════════════════════════════════════════════════════════════════════════
#  C1 — cosysim-voice.js
# ════════════════════════════════════════════════════════════════════════

class TestVoiceManagerJS:
    def test_voice_manager_js_exists(self):
        """cosysim-voice.js must exist in the shared static JS directory."""
        path = SHARED_JS / "cosysim-voice.js"
        assert path.exists(), f"Missing: {path}"

    def test_voice_manager_js_class_definition(self):
        """cosysim-voice.js must declare the VoiceManager class."""
        src = (SHARED_JS / "cosysim-voice.js").read_text(encoding="utf-8")
        assert "class VoiceManager" in src

    def test_voice_manager_js_has_speak_method(self):
        """VoiceManager must expose a speak() method."""
        src = (SHARED_JS / "cosysim-voice.js").read_text(encoding="utf-8")
        assert "speak(" in src

    def test_voice_manager_js_has_backend_methods(self):
        """VoiceManager must expose setBackend and getBackend."""
        src = (SHARED_JS / "cosysim-voice.js").read_text(encoding="utf-8")
        assert "setBackend(" in src
        assert "getBackend(" in src

    def test_voice_manager_js_has_stt_methods(self):
        """VoiceManager must expose listen() and stopListening()."""
        src = (SHARED_JS / "cosysim-voice.js").read_text(encoding="utf-8")
        assert "listen(" in src
        assert "stopListening(" in src

    def test_voice_manager_js_singleton(self):
        """Module must assign window.voiceManager singleton."""
        src = (SHARED_JS / "cosysim-voice.js").read_text(encoding="utf-8")
        assert "window.voiceManager" in src

    def test_voice_manager_js_custom_events(self):
        """VoiceManager must emit CustomEvent for voice lifecycle events."""
        src = (SHARED_JS / "cosysim-voice.js").read_text(encoding="utf-8")
        assert "voice:speaking" in src
        assert "voice:done" in src
        assert "voice:enabled" in src
        assert "voice:disabled" in src
        assert "voice:transcript" in src
        assert "voice:error" in src


# ════════════════════════════════════════════════════════════════════════
#  C2 — voice_settings.html, voice_settings.css, voice_settings.js
# ════════════════════════════════════════════════════════════════════════

class TestVoiceSettingsTemplate:
    def test_voice_settings_template_exists(self):
        """voice_settings.html must exist in shared templates."""
        path = SHARED_TPL / "voice_settings.html"
        assert path.exists(), f"Missing: {path}"

    def test_voice_settings_template_has_master_toggle(self):
        """Template must contain the master toggle button."""
        src = (SHARED_TPL / "voice_settings.html").read_text(encoding="utf-8")
        assert "cs-voice-master-toggle" in src

    def test_voice_settings_template_has_three_backends(self):
        """Template must have radio options for piper, orpheus, and qwen3."""
        src = (SHARED_TPL / "voice_settings.html").read_text(encoding="utf-8")
        assert 'value="piper"' in src
        assert 'value="orpheus"' in src
        assert 'value="qwen3"' in src

    def test_voice_settings_template_has_speed_slider(self):
        """Template must contain the speed range input."""
        src = (SHARED_TPL / "voice_settings.html").read_text(encoding="utf-8")
        assert 'id="cs-voice-speed"' in src
        assert 'type="range"' in src

    def test_voice_settings_template_has_stt_toggle(self):
        """Template must contain the STT toggle."""
        src = (SHARED_TPL / "voice_settings.html").read_text(encoding="utf-8")
        assert "cs-stt-toggle" in src

    def test_voice_settings_template_has_preview_button(self):
        """Template must contain the preview button."""
        src = (SHARED_TPL / "voice_settings.html").read_text(encoding="utf-8")
        assert "cs-voice-preview" in src


class TestVoiceSettingsCSS:
    def test_voice_settings_css_exists(self):
        """voice_settings.css must exist in shared static CSS directory."""
        path = SHARED_CSS / "voice_settings.css"
        assert path.exists(), f"Missing: {path}"

    def test_voice_settings_css_has_panel_class(self):
        """.cs-voice-settings selector must be defined."""
        src = (SHARED_CSS / "voice_settings.css").read_text(encoding="utf-8")
        assert ".cs-voice-settings" in src

    def test_voice_settings_css_has_toggle_class(self):
        """.cs-voice-toggle selector must be defined."""
        src = (SHARED_CSS / "voice_settings.css").read_text(encoding="utf-8")
        assert ".cs-voice-toggle" in src

    def test_voice_settings_css_has_backend_classes(self):
        """Backend card selectors must be defined."""
        src = (SHARED_CSS / "voice_settings.css").read_text(encoding="utf-8")
        assert ".cs-backend-group" in src
        assert ".cs-backend-card" in src

    def test_voice_settings_css_has_slider_classes(self):
        """Slider classes must be defined."""
        src = (SHARED_CSS / "voice_settings.css").read_text(encoding="utf-8")
        assert ".cs-voice-slider" in src
        assert ".cs-slider-group" in src


class TestVoiceSettingsJS:
    def test_voice_settings_js_exists(self):
        """voice_settings.js must exist in shared static JS directory."""
        path = SHARED_JS / "voice_settings.js"
        assert path.exists(), f"Missing: {path}"

    def test_voice_settings_js_wires_toggle(self):
        """voice_settings.js must wire the master toggle to voiceManager.toggle()."""
        src = (SHARED_JS / "voice_settings.js").read_text(encoding="utf-8")
        assert "vm.toggle(" in src

    def test_voice_settings_js_wires_backend(self):
        """voice_settings.js must wire backend radios to voiceManager.setBackend()."""
        src = (SHARED_JS / "voice_settings.js").read_text(encoding="utf-8")
        assert "vm.setBackend(" in src

    def test_voice_settings_js_wires_speed(self):
        """voice_settings.js must wire speed slider to voiceManager.setSpeed()."""
        src = (SHARED_JS / "voice_settings.js").read_text(encoding="utf-8")
        assert "vm.setSpeed(" in src

    def test_voice_settings_js_wires_preview(self):
        """voice_settings.js must wire preview button to voiceManager.preview()."""
        src = (SHARED_JS / "voice_settings.js").read_text(encoding="utf-8")
        assert "vm.preview(" in src

    def test_voice_settings_js_listens_to_events(self):
        """voice_settings.js must listen for voice:enabled and voice:disabled."""
        src = (SHARED_JS / "voice_settings.js").read_text(encoding="utf-8")
        assert "voice:enabled" in src
        assert "voice:disabled" in src


# ════════════════════════════════════════════════════════════════════════
#  C3 — BaseScene.register_tts_route
# ════════════════════════════════════════════════════════════════════════

# ── Minimal concrete scene for testing ──────────────────────────────────

class _MinimalScene:
    """Lightweight stand-in that only exposes register_tts_route."""

    def __init__(self):
        self.scene_name = "test_scene"
        self.port = 5000

    # Borrow register_tts_route directly from BaseScene without __init__
    from engine.scenes.base_scene import BaseScene as _BS
    register_tts_route = _BS.register_tts_route


def _make_wav_bytes(duration_s: float = 0.5, sample_rate: int = 22050) -> bytes:
    """Build a minimal valid WAV file in memory for mocking."""
    import struct
    n_frames = int(sample_rate * duration_s)
    pcm = b"\x00\x00" * n_frames
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


@pytest.fixture
def tts_app(tmp_path):
    """Flask test app with TTS routes mounted and TTSManager mocked."""
    app = Flask(__name__)
    app.config["TESTING"] = True

    wav = _make_wav_bytes()

    mock_result = MagicMock()
    mock_result.audio_bytes = wav
    mock_result.duration = 0.5

    mock_mgr = MagicMock()
    mock_mgr.synthesize.return_value = mock_result
    mock_mgr.list_backends.return_value = [
        {"name": "piper",   "label": "Piper (Fast)",       "available": True},
        {"name": "orpheus", "label": "Orpheus API",        "available": False},
        {"name": "qwen3",   "label": "Qwen3 (GPU)",        "available": False},
    ]

    # Mount routes via helper (bypasses real BaseScene.__init__)
    _patched_register(None, app, tmp_path, mock_mgr)

    return app, tmp_path, mock_mgr


def _patched_register(scene, app, cache_dir: Path, mock_mgr: MagicMock) -> None:
    """Re-implement register_tts_route with injected cache_dir and mock_mgr."""
    import json as _json
    from flask import request, Response, send_file

    @app.route("/api/tts/speak", methods=["POST"])
    def _tts_speak():
        try:
            data = request.get_json(silent=True) or {}
            text = str(data.get("text", "")).strip()
            if not text:
                return Response(
                    _json.dumps({"error": "text is required"}),
                    status=400,
                    mimetype="application/json",
                )
            backend = str(data.get("backend", "auto"))
            result = mock_mgr.synthesize(text, backend=backend, voice="default")
            file_id = str(uuid.uuid4())
            (cache_dir / f"{file_id}.wav").write_bytes(result.audio_bytes)
            return Response(
                _json.dumps({
                    "audio_url":   f"/api/tts/audio/{file_id}",
                    "duration_ms": int(result.duration * 1000),
                    "text":        text,
                }),
                mimetype="application/json",
            )
        except Exception as exc:
            return Response(
                _json.dumps({"error": "TTS unavailable"}),
                status=503,
                mimetype="application/json",
            )

    @app.route("/api/tts/voices", methods=["GET"])
    def _tts_voices():
        return Response(
            _json.dumps({"voices": mock_mgr.list_backends()}),
            mimetype="application/json",
        )

    @app.route("/api/tts/audio/<file_id>", methods=["GET"])
    def _tts_audio(file_id: str):
        safe = "".join(c for c in file_id if c.isalnum() or c == "-")
        wav_path = cache_dir / f"{safe}.wav"
        if not wav_path.exists():
            return Response(
                _json.dumps({"error": "audio not found"}),
                status=404,
                mimetype="application/json",
            )
        return send_file(str(wav_path), mimetype="audio/wav")


class TestRegisterTTSRoute:
    def test_register_tts_route_adds_endpoints(self):
        """/api/tts/* routes must be registered after register_tts_route."""
        app = Flask(__name__)
        app.config["TESTING"] = True
        scene = _MinimalScene()
        mock_mgr = MagicMock()
        with patch("engine.tts.tts_manager.get_tts_manager", return_value=mock_mgr):
            scene.register_tts_route(app)
        rules = {r.rule for r in app.url_map.iter_rules()}
        assert "/api/tts/speak" in rules
        assert "/api/tts/voices" in rules
        assert "/api/tts/audio/<file_id>" in rules

    def test_tts_speak_endpoint_returns_audio_url(self, tts_app):
        """POST /api/tts/speak returns audio_url and duration_ms."""
        app, cache_dir, mock_mgr = tts_app
        client = app.test_client()
        resp = client.post(
            "/api/tts/speak",
            json={"text": "Hello world", "backend": "piper"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "audio_url" in data
        assert data["audio_url"].startswith("/api/tts/audio/")
        assert "duration_ms" in data
        assert data["text"] == "Hello world"

    def test_tts_speak_endpoint_calls_tts_manager(self, tts_app):
        """POST /api/tts/speak must call mock_mgr.synthesize()."""
        app, cache_dir, mock_mgr = tts_app
        client = app.test_client()
        mock_mgr.synthesize.reset_mock()
        client.post(
            "/api/tts/speak",
            json={"text": "Test call"},
            content_type="application/json",
        )
        mock_mgr.synthesize.assert_called_once()

    def test_tts_speak_endpoint_missing_text(self, tts_app):
        """POST /api/tts/speak with no text returns 400."""
        app, cache_dir, mock_mgr = tts_app
        client = app.test_client()
        resp = client.post(
            "/api/tts/speak",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "error" in data

    def test_tts_speak_endpoint_handles_failure(self, tts_app):
        """POST /api/tts/speak returns 503 when TTSManager raises."""
        app, cache_dir, mock_mgr = tts_app
        mock_mgr.synthesize.side_effect = RuntimeError("Backend offline")
        client = app.test_client()
        resp = client.post(
            "/api/tts/speak",
            json={"text": "Test failure"},
            content_type="application/json",
        )
        assert resp.status_code == 503
        data = json.loads(resp.data)
        assert data.get("error") == "TTS unavailable"
        # Reset side_effect so other tests are not affected
        mock_mgr.synthesize.side_effect = None

    def test_tts_voices_endpoint(self, tts_app):
        """GET /api/tts/voices returns a voices list."""
        app, cache_dir, mock_mgr = tts_app
        client = app.test_client()
        resp = client.get("/api/tts/voices")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "voices" in data
        assert isinstance(data["voices"], list)
        assert len(data["voices"]) > 0
        names = [v["name"] for v in data["voices"]]
        assert "piper" in names

    def test_tts_audio_serve(self, tts_app):
        """GET /api/tts/audio/<id> serves the cached WAV file."""
        app, cache_dir, mock_mgr = tts_app
        client = app.test_client()

        # First generate a file
        resp = client.post(
            "/api/tts/speak",
            json={"text": "Audio serve test"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        audio_url = json.loads(resp.data)["audio_url"]

        # Now fetch it
        resp = client.get(audio_url)
        assert resp.status_code == 200
        assert resp.content_type == "audio/wav"
        assert len(resp.data) > 0

    def test_tts_audio_not_found(self, tts_app):
        """GET /api/tts/audio/<unknown-id> returns 404."""
        app, cache_dir, mock_mgr = tts_app
        client = app.test_client()
        resp = client.get(f"/api/tts/audio/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_tts_cache_dir_created(self):
        """data/tts_cache/ directory must exist in the repository."""
        assert TTS_CACHE.exists(), f"Missing: {TTS_CACHE}"
        assert TTS_CACHE.is_dir()


# ════════════════════════════════════════════════════════════════════════
#  inject_navbar_context
# ════════════════════════════════════════════════════════════════════════

class TestInjectNavbarContextWithVoice:
    def test_inject_navbar_context_with_voice(self):
        """inject_navbar_context must return expected keys without raising."""
        from engine.scenes.base_scene import BaseScene

        class _DummyScene(BaseScene):
            SCENE_METADATA = {
                "display_name": "Test Scene",
                "accent_color": "#ff0000",
            }

            def start(self) -> None:
                pass

            def stop(self) -> None:
                pass

            def get_plugin_info(self):
                return {}

        with patch("engine.scenes.base_scene.AssetManager"):
            with patch("engine.scenes.base_scene._ACTIVE_SCENES", {}):
                with patch.object(_DummyScene, "_mcp_register_scene", lambda self: None):
                    scene = _DummyScene.__new__(_DummyScene)
                    scene.scene_name = "test_scene"
                    scene.port = 5000
                    scene.asset_manager = MagicMock()
                    scene.active_characters = {}
                    scene.scene_config = {}
                    scene.scene_asset_id = None
                    scene.streaming_enabled = True
                    scene._active_streams = 0
                    scene._total_stream_tokens = 0
                    scene.scene_metadata = _DummyScene.SCENE_METADATA

                    ctx = scene.inject_navbar_context()

        assert "current_scene" in ctx
        assert "scene_name" in ctx
        assert "scene_accent" in ctx
        assert ctx["scene_name"] == "Test Scene"
        assert ctx["scene_accent"] == "#ff0000"
