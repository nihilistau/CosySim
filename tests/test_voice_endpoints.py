"""Tests for assistant voice endpoints — chat, TTS, STT, health, status.

Covers all routes in ``engine/assistant/assistant_bp.py`` using a Flask
test-client with the assistant blueprint mounted in isolation.
"""
from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from engine.assistant.assistant_bp import assistant_bp, mount_assistant


# ═══════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def app():
    """Create a minimal Flask app with the assistant blueprint registered."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(assistant_bp)
    return flask_app


@pytest.fixture
def client(app):
    """Flask test client with assistant routes available."""
    return app.test_client()


@pytest.fixture
def mock_assistant():
    """A MagicMock that behaves like SystemAssistant."""
    assistant = MagicMock()
    assistant.name = "Aria"
    assistant.chat.return_value = {
        "reply": "Hello there!",
        "mood": "friendly",
        "source": "assistant",
    }
    assistant.get_system_summary.return_value = {
        "scenes": 3,
        "models_loaded": 1,
        "uptime": 120.5,
    }
    return assistant


@pytest.fixture
def mock_tts_manager():
    """A MagicMock that behaves like TTSManager."""
    mgr = MagicMock()
    mgr.synthesize.return_value = SimpleNamespace(
        audio_bytes=b"RIFF" + b"\x00" * 100,
        backend="piper",
        latency_ms=42.0,
        duration=1.25,
    )
    mgr.health.return_value = {
        "status": "ok",
        "backends": {"piper": "ready", "orpheus": "ready"},
    }
    mgr.get_benchmarks.return_value = {
        "piper": {"avg_rtf": 0.05, "samples": 10},
        "orpheus": {"avg_rtf": 0.12, "samples": 5},
    }
    return mgr


# ═══════════════════════════════════════════════════════════════════════
#  Imports
# ═══════════════════════════════════════════════════════════════════════

class TestImports:
    """Module-level imports from assistant_bp work."""

    def test_import_blueprint(self):
        from engine.assistant.assistant_bp import assistant_bp as bp
        assert bp is not None
        assert bp.name == "assistant"

    def test_import_mount_assistant(self):
        from engine.assistant.assistant_bp import mount_assistant
        assert callable(mount_assistant)


# ═══════════════════════════════════════════════════════════════════════
#  POST /api/assistant/chat
# ═══════════════════════════════════════════════════════════════════════

class TestChatEndpoint:
    """Tests for the /api/assistant/chat route."""

    def test_basic_chat(self, client, mock_assistant):
        """Normal chat message returns reply JSON."""
        with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant):
            resp = client.post("/api/assistant/chat", json={"message": "Hi"})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["reply"] == "Hello there!"
        assert data["mood"] == "friendly"
        assert data["source"] == "assistant"

    def test_chat_passes_scene_id(self, client, mock_assistant):
        """scene_id is forwarded to assistant.chat()."""
        with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant):
            client.post("/api/assistant/chat", json={"message": "Hey", "scene_id": "penthouse"})

        mock_assistant.chat.assert_called_once_with("Hey", scene_id="penthouse")

    def test_chat_with_voice_flag(self, client, mock_assistant):
        """voice=True adds audio_url and _voice_text to response."""
        with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant):
            resp = client.post("/api/assistant/chat", json={"message": "Speak!", "voice": True})

        data = resp.get_json()
        assert data["audio_url"] == "/api/assistant/voice"
        assert data["_voice_text"] == "Hello there!"

    def test_chat_voice_false_no_audio_url(self, client, mock_assistant):
        """voice=False (default) does NOT add audio_url."""
        with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant):
            resp = client.post("/api/assistant/chat", json={"message": "Hi"})

        data = resp.get_json()
        assert "audio_url" not in data
        assert "_voice_text" not in data

    def test_chat_voice_true_empty_reply_no_audio_url(self, client):
        """voice=True but empty reply should not add audio_url."""
        assistant = MagicMock()
        assistant.chat.return_value = {"reply": "", "mood": "neutral", "source": "assistant"}
        with patch("engine.assistant.system_assistant.get_assistant", return_value=assistant):
            resp = client.post("/api/assistant/chat", json={"message": "Speak!", "voice": True})

        data = resp.get_json()
        assert "audio_url" not in data

    def test_chat_empty_message_returns_400(self, client):
        """Empty or whitespace message returns 400."""
        resp = client.post("/api/assistant/chat", json={"message": ""})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "No message provided"

    def test_chat_whitespace_only_message(self, client):
        """Whitespace-only message is treated as empty → 400."""
        resp = client.post("/api/assistant/chat", json={"message": "   "})
        assert resp.status_code == 400

    def test_chat_missing_message_key(self, client):
        """No 'message' key at all returns 400."""
        resp = client.post("/api/assistant/chat", json={"scene_id": "hub"})
        assert resp.status_code == 400

    def test_chat_no_json_body(self, client):
        """Request with no JSON body returns 400."""
        resp = client.post("/api/assistant/chat", content_type="application/json")
        assert resp.status_code == 400

    def test_chat_assistant_exception_returns_fallback(self, client):
        """If assistant.chat() raises, return graceful error reply."""
        assistant = MagicMock()
        assistant.chat.side_effect = RuntimeError("LMS down")
        with patch("engine.assistant.system_assistant.get_assistant", return_value=assistant):
            resp = client.post("/api/assistant/chat", json={"message": "Hi"})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["mood"] == "apologetic"
        assert data["source"] == "error"
        assert "trouble" in data["reply"].lower()

    def test_chat_get_assistant_exception_returns_fallback(self, client):
        """If get_assistant() itself throws, return graceful error reply."""
        with patch("engine.assistant.system_assistant.get_assistant", side_effect=ImportError("missing")):
            resp = client.post("/api/assistant/chat", json={"message": "Hello"})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["source"] == "error"


# ═══════════════════════════════════════════════════════════════════════
#  POST /api/assistant/voice
# ═══════════════════════════════════════════════════════════════════════

class TestVoiceEndpoint:
    """Tests for the /api/assistant/voice TTS route."""

    def test_basic_synthesis(self, client, mock_tts_manager):
        """Valid text returns audio/wav with TTS headers."""
        with patch("engine.tts.tts_manager.get_tts_manager", return_value=mock_tts_manager):
            resp = client.post("/api/assistant/voice", json={"text": "Hello world"})

        assert resp.status_code == 200
        assert resp.content_type == "audio/wav"
        assert resp.data.startswith(b"RIFF")
        assert resp.headers["X-TTS-Backend"] == "piper"
        assert resp.headers["X-TTS-Latency-Ms"] == "42"

    def test_synthesis_with_backend_selection(self, client, mock_tts_manager):
        """Backend param is forwarded to synthesize()."""
        with patch("engine.tts.tts_manager.get_tts_manager", return_value=mock_tts_manager):
            client.post("/api/assistant/voice", json={"text": "Hi", "backend": "orpheus"})

        mock_tts_manager.synthesize.assert_called_once_with("Hi", backend="orpheus", voice="default")

    def test_synthesis_with_voice_selection(self, client, mock_tts_manager):
        """Voice param is forwarded to synthesize()."""
        with patch("engine.tts.tts_manager.get_tts_manager", return_value=mock_tts_manager):
            client.post("/api/assistant/voice", json={"text": "Hi", "voice": "emily"})

        mock_tts_manager.synthesize.assert_called_once_with("Hi", backend="auto", voice="emily")

    def test_synthesis_defaults(self, client, mock_tts_manager):
        """Omitting backend and voice uses auto/default."""
        with patch("engine.tts.tts_manager.get_tts_manager", return_value=mock_tts_manager):
            client.post("/api/assistant/voice", json={"text": "Hi"})

        mock_tts_manager.synthesize.assert_called_once_with("Hi", backend="auto", voice="default")

    def test_synthesis_empty_text_returns_400(self, client):
        """Empty text returns 400."""
        resp = client.post("/api/assistant/voice", json={"text": ""})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "No text provided"

    def test_synthesis_whitespace_text_returns_400(self, client):
        """Whitespace-only text is treated as empty → 400."""
        resp = client.post("/api/assistant/voice", json={"text": "   "})
        assert resp.status_code == 400

    def test_synthesis_missing_text_key(self, client):
        """No 'text' key returns 400."""
        resp = client.post("/api/assistant/voice", json={"backend": "piper"})
        assert resp.status_code == 400

    def test_synthesis_no_json_body(self, client):
        """No body at all returns 400."""
        resp = client.post("/api/assistant/voice", content_type="application/json")
        assert resp.status_code == 400

    def test_synthesis_failure_returns_500(self, client):
        """TTS synthesize() exception returns 500 with error message."""
        mgr = MagicMock()
        mgr.synthesize.side_effect = RuntimeError("GPU OOM")
        with patch("engine.tts.tts_manager.get_tts_manager", return_value=mgr):
            resp = client.post("/api/assistant/voice", json={"text": "Try this"})

        assert resp.status_code == 500
        data = resp.get_json()
        assert "TTS synthesis failed" in data["error"]
        assert "GPU OOM" in data["error"]

    def test_synthesis_get_tts_manager_failure_returns_500(self, client):
        """If get_tts_manager() itself throws, return 500."""
        with patch("engine.tts.tts_manager.get_tts_manager", side_effect=ImportError("no tts")):
            resp = client.post("/api/assistant/voice", json={"text": "Hello"})

        assert resp.status_code == 500

    def test_response_headers_rtf_calculation(self, client):
        """X-TTS-RTF header is correctly computed from latency/duration."""
        mgr = MagicMock()
        mgr.synthesize.return_value = SimpleNamespace(
            audio_bytes=b"RIFF" + b"\x00" * 50,
            backend="qwen3",
            latency_ms=500.0,
            duration=2.0,
        )
        with patch("engine.tts.tts_manager.get_tts_manager", return_value=mgr):
            resp = client.post("/api/assistant/voice", json={"text": "Test"})

        assert resp.status_code == 200
        # RTF = latency_ms / 1000 / duration = 0.5 / 2.0 = 0.25
        assert resp.headers["X-TTS-RTF"] == "0.2500"
        assert resp.headers["X-TTS-Duration"] == "2.00"


# ═══════════════════════════════════════════════════════════════════════
#  POST /api/assistant/listen
# ═══════════════════════════════════════════════════════════════════════

class TestListenEndpoint:
    """Tests for the /api/assistant/listen STT route."""

    def _post_audio(self, client, audio_bytes=b"fake-audio-data"):
        """Helper: POST multipart audio to /api/assistant/listen."""
        data = {"audio": (io.BytesIO(audio_bytes), "recording.wav")}
        return client.post(
            "/api/assistant/listen",
            data=data,
            content_type="multipart/form-data",
        )

    @patch("engine.config.get_config")
    @patch("requests.post")
    def test_basic_transcription(self, mock_post, mock_config, client):
        """Valid audio file returns transcription JSON."""
        mock_config.return_value.get.return_value = "http://localhost:5051"
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "text": "Hello world",
                "language": "en",
                "duration": 2.5,
            }),
        )

        resp = self._post_audio(client)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["text"] == "Hello world"
        assert data["language"] == "en"
        assert data["duration"] == 2.5

    @patch("engine.config.get_config")
    @patch("requests.post")
    def test_transcription_forwards_to_whisper(self, mock_post, mock_config, client):
        """Audio is forwarded to the configured STT server URL."""
        mock_config.return_value.get.return_value = "http://custom-stt:9000"
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"text": "ok"}),
        )

        self._post_audio(client, b"wav-bytes")

        call_args = mock_post.call_args
        assert "http://custom-stt:9000/v1/audio/transcriptions" == call_args[0][0]
        assert call_args[1]["data"] == {"model": "whisper-1"}
        assert call_args[1]["timeout"] == 30

    @patch("engine.config.get_config")
    @patch("requests.post")
    def test_transcription_defaults_missing_fields(self, mock_post, mock_config, client):
        """Missing fields in STT response default to safe values."""
        mock_config.return_value.get.return_value = "http://localhost:5051"
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={}),
        )

        resp = self._post_audio(client)
        data = resp.get_json()
        assert data["text"] == ""
        assert data["language"] == "en"
        assert data["duration"] == 0.0

    def test_listen_no_audio_file_returns_400(self, client):
        """Request without 'audio' file field returns 400."""
        resp = client.post("/api/assistant/listen", content_type="multipart/form-data")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "No audio file provided"

    def test_listen_empty_audio_file_returns_400(self, client):
        """Uploading a zero-length audio file returns 400."""
        resp = self._post_audio(client, audio_bytes=b"")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Empty audio file"

    @patch("engine.config.get_config")
    @patch("requests.post")
    def test_stt_server_error_returns_502(self, mock_post, mock_config, client):
        """Non-200 from Whisper returns 502 with error detail."""
        mock_config.return_value.get.return_value = "http://localhost:5051"
        mock_post.return_value = MagicMock(status_code=503)

        resp = self._post_audio(client)

        assert resp.status_code == 502
        data = resp.get_json()
        assert "STT server error: 503" in data["error"]

    @patch("engine.config.get_config")
    @patch("requests.post")
    def test_stt_connection_error_returns_500(self, mock_post, mock_config, client):
        """Connection failure to STT server returns 500."""
        mock_config.return_value.get.return_value = "http://localhost:5051"
        mock_post.side_effect = ConnectionError("refused")

        resp = self._post_audio(client)

        assert resp.status_code == 500
        data = resp.get_json()
        assert "Transcription failed" in data["error"]

    @patch("engine.config.get_config")
    @patch("requests.post")
    def test_stt_timeout_returns_500(self, mock_post, mock_config, client):
        """Timeout to STT server returns 500."""
        import requests as real_requests
        mock_config.return_value.get.return_value = "http://localhost:5051"
        mock_post.side_effect = real_requests.exceptions.Timeout("timed out")

        resp = self._post_audio(client)

        assert resp.status_code == 500
        assert "Transcription failed" in resp.get_json()["error"]


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/assistant/tts/health
# ═══════════════════════════════════════════════════════════════════════

class TestTTSHealthEndpoint:
    """Tests for the /api/assistant/tts/health route."""

    def test_health_returns_manager_health(self, client, mock_tts_manager):
        """Health endpoint returns what mgr.health() returns."""
        with patch("engine.tts.tts_manager.get_tts_manager", return_value=mock_tts_manager):
            resp = client.get("/api/assistant/tts/health")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "piper" in data["backends"]
        assert "orpheus" in data["backends"]

    def test_health_manager_error_returns_unavailable(self, client):
        """If TTS manager fails, return unavailable status."""
        with patch("engine.tts.tts_manager.get_tts_manager", side_effect=RuntimeError("no GPU")):
            resp = client.get("/api/assistant/tts/health")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "unavailable"
        assert "no GPU" in data["error"]


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/assistant/tts/benchmarks
# ═══════════════════════════════════════════════════════════════════════

class TestTTSBenchmarksEndpoint:
    """Tests for the /api/assistant/tts/benchmarks route."""

    def test_benchmarks_returns_data(self, client, mock_tts_manager):
        """Benchmarks endpoint returns what mgr.get_benchmarks() returns."""
        with patch("engine.tts.tts_manager.get_tts_manager", return_value=mock_tts_manager):
            resp = client.get("/api/assistant/tts/benchmarks")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["piper"]["avg_rtf"] == 0.05
        assert data["orpheus"]["samples"] == 5

    def test_benchmarks_manager_error_returns_error_json(self, client):
        """If TTS manager fails, return JSON with error detail."""
        with patch("engine.tts.tts_manager.get_tts_manager", side_effect=RuntimeError("gone")):
            resp = client.get("/api/assistant/tts/benchmarks")

        assert resp.status_code == 200
        data = resp.get_json()
        assert "gone" in data["error"]


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/assistant/status
# ═══════════════════════════════════════════════════════════════════════

class TestStatusEndpoint:
    """Tests for the /api/assistant/status route."""

    def test_status_includes_name_and_system(self, client, mock_assistant, mock_tts_manager):
        """Status includes assistant name, availability, and system summary."""
        with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant), \
             patch("engine.tts.tts_manager.get_tts_manager", return_value=mock_tts_manager):
            resp = client.get("/api/assistant/status")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Aria"
        assert data["available"] is True
        assert data["system"]["scenes"] == 3

    def test_status_includes_tts_info(self, client, mock_assistant, mock_tts_manager):
        """Status includes TTS availability and backends."""
        with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant), \
             patch("engine.tts.tts_manager.get_tts_manager", return_value=mock_tts_manager):
            resp = client.get("/api/assistant/status")

        data = resp.get_json()
        assert data["tts"]["available"] is True
        assert "piper" in data["tts"]["backends"]

    def test_status_tts_unavailable_when_health_not_ok(self, client, mock_assistant):
        """If TTS health status != 'ok', tts.available is False."""
        mgr = MagicMock()
        mgr.health.return_value = {"status": "degraded", "backends": {}}
        with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant), \
             patch("engine.tts.tts_manager.get_tts_manager", return_value=mgr):
            resp = client.get("/api/assistant/status")

        data = resp.get_json()
        assert data["tts"]["available"] is False

    def test_status_tts_error_shows_unavailable(self, client, mock_assistant):
        """If get_tts_manager() throws, tts block still present as unavailable."""
        with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant), \
             patch("engine.tts.tts_manager.get_tts_manager", side_effect=ImportError("no tts")):
            resp = client.get("/api/assistant/status")

        data = resp.get_json()
        assert data["tts"]["available"] is False

    def test_status_assistant_error_returns_fallback(self, client):
        """If get_assistant() fails, return fallback status."""
        with patch("engine.assistant.system_assistant.get_assistant", side_effect=RuntimeError("boom")):
            resp = client.get("/api/assistant/status")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Aria"
        assert data["available"] is False
        assert data["tts"]["available"] is False


# ═══════════════════════════════════════════════════════════════════════
#  mount_assistant()
# ═══════════════════════════════════════════════════════════════════════

class TestMountAssistant:
    """Tests for the mount_assistant() helper function."""

    def test_mount_registers_blueprint(self):
        """mount_assistant() registers the assistant blueprint on the app."""
        app = Flask(__name__)
        mount_assistant(app)
        assert "assistant" in app.blueprints

    def test_mount_idempotent(self):
        """Calling mount_assistant() twice does not raise or double-register."""
        app = Flask(__name__)
        mount_assistant(app)
        mount_assistant(app)  # Should not raise
        assert "assistant" in app.blueprints

    def test_mount_does_not_overwrite(self):
        """Second mount_assistant() call doesn't replace the blueprint."""
        app = Flask(__name__)
        mount_assistant(app)
        bp_ref = app.blueprints["assistant"]
        mount_assistant(app)
        assert app.blueprints["assistant"] is bp_ref

    def test_mount_routes_accessible(self):
        """After mount, assistant routes are accessible via test_client."""
        app = Flask(__name__)
        app.config["TESTING"] = True
        mount_assistant(app)
        client = app.test_client()
        # /api/assistant/chat exists (even if it returns 400 for missing body)
        resp = client.post("/api/assistant/chat", json={})
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════
#  Edge Cases & Content-Type
# ═══════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Miscellaneous edge-case and integration tests."""

    def test_chat_non_json_content_type(self, client):
        """Posting non-JSON to /chat returns 400 (message empty)."""
        resp = client.post(
            "/api/assistant/chat",
            data="plain text body",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_voice_non_json_content_type(self, client):
        """Posting non-JSON to /voice returns 400 (text empty)."""
        resp = client.post(
            "/api/assistant/voice",
            data="plain text",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_chat_method_not_allowed(self, client):
        """GET to /api/assistant/chat returns 405."""
        resp = client.get("/api/assistant/chat")
        assert resp.status_code == 405

    def test_voice_method_not_allowed(self, client):
        """GET to /api/assistant/voice returns 405."""
        resp = client.get("/api/assistant/voice")
        assert resp.status_code == 405

    def test_listen_method_not_allowed(self, client):
        """GET to /api/assistant/listen returns 405."""
        resp = client.get("/api/assistant/listen")
        assert resp.status_code == 405

    def test_tts_health_post_not_allowed(self, client):
        """POST to /api/assistant/tts/health returns 405."""
        resp = client.post("/api/assistant/tts/health")
        assert resp.status_code == 405

    def test_voice_response_is_binary(self, client, mock_tts_manager):
        """Voice response body is raw bytes, not JSON."""
        with patch("engine.tts.tts_manager.get_tts_manager", return_value=mock_tts_manager):
            resp = client.post("/api/assistant/voice", json={"text": "Test"})

        assert resp.content_type == "audio/wav"
        # Should NOT be parseable as JSON
        try:
            json.loads(resp.data)
            assert False, "Voice response should not be JSON"
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass  # Expected — it's binary audio

    def test_chat_long_message(self, client, mock_assistant):
        """Long messages are accepted and forwarded."""
        long_msg = "word " * 500
        with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant):
            resp = client.post("/api/assistant/chat", json={"message": long_msg})

        assert resp.status_code == 200
        mock_assistant.chat.assert_called_once()
        actual_msg = mock_assistant.chat.call_args[0][0]
        assert len(actual_msg) > 2000
