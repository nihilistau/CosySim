"""System Assistant Blueprint — mountable chat + voice API for the Aria assistant.

Provides ``/api/assistant/chat`` and ``/api/assistant/voice`` on any Flask scene.

Usage::

    from engine.assistant.assistant_bp import assistant_bp
    app.register_blueprint(assistant_bp)
"""
from __future__ import annotations

import io
import logging
from typing import Any

from flask import Blueprint, Response, jsonify, request

logger = logging.getLogger(__name__)

assistant_bp = Blueprint("assistant", __name__)


@assistant_bp.route("/api/assistant/chat", methods=["POST"])
def assistant_chat() -> Any:
    """Handle chat messages to the system assistant.

    Expects JSON: { message: str, scene_id?: str, voice?: bool }
    Returns JSON: { reply: str, mood: str, action?: dict, source: str, audio_url?: str }
    """
    try:
        data = request.get_json(silent=True) or {}
        message = data.get("message", "").strip()
        scene_id = data.get("scene_id")
        want_voice = data.get("voice", False)

        if not message:
            return jsonify({"error": "No message provided"}), 400

        from engine.assistant.system_assistant import get_assistant
        assistant = get_assistant()
        result = assistant.chat(message, scene_id=scene_id)

        # If voice requested, add audio URL for client to fetch
        if want_voice and result.get("reply"):
            result["audio_url"] = "/api/assistant/voice"
            result["_voice_text"] = result["reply"]

        return jsonify(result)
    except Exception as exc:
        logger.warning("Assistant chat error: %s", exc, exc_info=True)
        return jsonify({
            "reply": "I'm having trouble right now. Try again in a moment.",
            "mood": "apologetic",
            "source": "error",
        })


@assistant_bp.route("/api/assistant/voice", methods=["POST"])
def assistant_voice() -> Any:
    """Synthesize speech from text using the TTS manager.

    Expects JSON: { text: str, backend?: str, voice?: str }
    Returns: audio/wav binary response

    Backends: "auto" (default), "piper", "orpheus", "qwen3"
    """
    try:
        data = request.get_json(silent=True) or {}
        text = data.get("text", "").strip()

        if not text:
            return jsonify({"error": "No text provided"}), 400

        backend = data.get("backend", "auto")
        voice = data.get("voice", "default")

        from engine.tts.tts_manager import get_tts_manager
        mgr = get_tts_manager()
        result = mgr.synthesize(text, backend=backend, voice=voice)

        return Response(
            result.audio_bytes,
            mimetype="audio/wav",
            headers={
                "X-TTS-Backend": result.backend,
                "X-TTS-Latency-Ms": str(int(result.latency_ms)),
                "X-TTS-Duration": f"{result.duration:.2f}",
                "X-TTS-RTF": f"{result.latency_ms / 1000.0 / max(result.duration, 0.001):.4f}",
            },
        )
    except Exception as exc:
        logger.warning("TTS voice error: %s", exc, exc_info=True)
        return jsonify({"error": f"TTS synthesis failed: {exc}"}), 500


@assistant_bp.route("/api/assistant/listen", methods=["POST"])
def assistant_listen() -> Any:
    """Transcribe audio using Whisper STT.

    Expects: multipart/form-data with 'audio' file field
    Returns JSON: { text: str, language: str, duration: float }
    """
    try:
        if "audio" not in request.files:
            return jsonify({"error": "No audio file provided"}), 400

        audio_file = request.files["audio"]
        audio_bytes = audio_file.read()

        if not audio_bytes:
            return jsonify({"error": "Empty audio file"}), 400

        # Forward to Whisper STT server
        import requests as http_requests
        from engine.config import get_config

        stt_url = get_config().get(
            "stt.server_url", "http://localhost:5051"
        )
        resp = http_requests.post(
            f"{stt_url}/v1/audio/transcriptions",
            files={"file": ("audio.wav", io.BytesIO(audio_bytes), "audio/wav")},
            data={"model": "whisper-1"},
            timeout=30,
        )

        if resp.status_code == 200:
            result = resp.json()
            return jsonify({
                "text": result.get("text", ""),
                "language": result.get("language", "en"),
                "duration": result.get("duration", 0.0),
            })
        else:
            return jsonify({"error": f"STT server error: {resp.status_code}"}), 502

    except Exception as exc:
        logger.warning("STT listen error: %s", exc, exc_info=True)
        return jsonify({"error": f"Transcription failed: {exc}"}), 500


@assistant_bp.route("/api/assistant/tts/health")
def assistant_tts_health() -> Any:
    """Check TTS backend health and benchmarks."""
    try:
        from engine.tts.tts_manager import get_tts_manager
        mgr = get_tts_manager()
        return jsonify(mgr.health())
    except Exception as exc:
        logger.debug("TTS health error: %s", exc)
        return jsonify({"status": "unavailable", "error": str(exc)})


@assistant_bp.route("/api/assistant/tts/benchmarks")
def assistant_tts_benchmarks() -> Any:
    """Get TTS performance benchmarks."""
    try:
        from engine.tts.tts_manager import get_tts_manager
        mgr = get_tts_manager()
        return jsonify(mgr.get_benchmarks())
    except Exception as exc:
        return jsonify({"error": str(exc)})


@assistant_bp.route("/api/assistant/status")
def assistant_status() -> Any:
    """Return assistant and system status summary."""
    try:
        from engine.assistant.system_assistant import get_assistant
        assistant = get_assistant()
        summary = assistant.get_system_summary()

        # Add TTS status
        tts_info: dict = {"available": False}
        try:
            from engine.tts.tts_manager import get_tts_manager
            mgr = get_tts_manager()
            tts_health = mgr.health()
            tts_info = {
                "available": tts_health.get("status") == "ok",
                "backends": tts_health.get("backends", {}),
            }
        except Exception:
            pass

        return jsonify({
            "name": assistant.name,
            "available": True,
            "system": summary,
            "tts": tts_info,
        })
    except Exception as exc:
        logger.debug("Assistant status error: %s", exc)
        return jsonify({"name": "Aria", "available": False, "system": {}, "tts": {"available": False}})


def mount_assistant(app: Any) -> None:
    """Mount the assistant blueprint on a Flask app.

    Safe to call multiple times — silently skips if already registered.

    Args:
        app: Flask application instance.
    """
    if "assistant" in app.blueprints:
        return
    app.register_blueprint(assistant_bp)
    logger.debug("Assistant blueprint mounted")
