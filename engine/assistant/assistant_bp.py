"""System Assistant Blueprint — mountable chat API for the Aria assistant.

Provides ``/api/assistant/chat`` on any Flask scene that mounts it.

Usage::

    from engine.assistant.assistant_bp import assistant_bp
    app.register_blueprint(assistant_bp)
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

assistant_bp = Blueprint("assistant", __name__)


@assistant_bp.route("/api/assistant/chat", methods=["POST"])
def assistant_chat() -> Any:
    """Handle chat messages to the system assistant.

    Expects JSON: { message: str, scene_id?: str }
    Returns JSON: { reply: str, mood: str, action?: dict, source: str }
    """
    try:
        data = request.get_json(silent=True) or {}
        message = data.get("message", "").strip()
        scene_id = data.get("scene_id")

        if not message:
            return jsonify({"error": "No message provided"}), 400

        from engine.assistant.system_assistant import get_assistant
        assistant = get_assistant()
        result = assistant.chat(message, scene_id=scene_id)
        return jsonify(result)
    except Exception as exc:
        logger.warning("Assistant chat error: %s", exc, exc_info=True)
        return jsonify({
            "reply": "I'm having trouble right now. Try again in a moment.",
            "mood": "apologetic",
            "source": "error",
        })


@assistant_bp.route("/api/assistant/status")
def assistant_status() -> Any:
    """Return assistant and system status summary."""
    try:
        from engine.assistant.system_assistant import get_assistant
        assistant = get_assistant()
        summary = assistant.get_system_summary()
        return jsonify({
            "name": assistant.name,
            "available": True,
            "system": summary,
        })
    except Exception as exc:
        logger.debug("Assistant status error: %s", exc)
        return jsonify({"name": "Aria", "available": False, "system": {}})


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
