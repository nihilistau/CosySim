"""
Assistant Platform — Internal API
===================================

REST endpoints + SocketIO events for the web UI.

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Full CRUD + streaming chat
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from flask import Blueprint, jsonify, request
from flask_socketio import SocketIO

from apps.assistant import models
from apps.assistant.config import resolve_model
from apps.assistant.services import router, file_handler
from apps.assistant.services.streaming import stream_to_socketio

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


# ──── Conversations ──────────────────────────────────────────────────

@api_bp.route("/conversations", methods=["GET"])
def list_conversations():
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    return jsonify(models.get_conversations(limit, offset))


@api_bp.route("/conversations", methods=["POST"])
def create_conversation():
    data = request.get_json(silent=True) or {}
    conv = models.create_conversation(
        title=data.get("title", "New Chat"),
        model=data.get("model", "gpt-5.4"),
        system_prompt=data.get("system_prompt", ""),
    )
    return jsonify(conv), 201


@api_bp.route("/conversations/<conv_id>", methods=["GET"])
def get_conversation(conv_id: str):
    conv = models.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "not_found"}), 404
    return jsonify(conv)


@api_bp.route("/conversations/<conv_id>", methods=["PATCH"])
def update_conversation(conv_id: str):
    data = request.get_json(silent=True) or {}
    models.update_conversation(conv_id, **data)
    return jsonify({"ok": True})


@api_bp.route("/conversations/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id: str):
    if models.delete_conversation(conv_id):
        return jsonify({"ok": True})
    return jsonify({"error": "not_found"}), 404


# ──── Chat (non-streaming, for simple requests) ─────────────────────

@api_bp.route("/chat", methods=["POST"])
def chat():
    """Non-streaming chat endpoint. For streaming, use SocketIO."""
    data = request.get_json(silent=True) or {}
    conv_id = data.get("conversation_id")
    message = data.get("message", "")
    model_raw = data.get("model", "gpt-5.4")

    if not message:
        return jsonify({"error": "message required"}), 400

    # Create conversation if needed
    if not conv_id:
        conv = models.create_conversation(model=resolve_model(model_raw))
        conv_id = conv["id"]

    # Save user message
    models.add_message(conv_id, "user", message)

    # Build messages array from conversation history
    history = models.get_messages(conv_id)
    messages = [{"role": m["role"], "content": m["content"]} for m in history]

    # Get settings
    settings = models.get_all_settings()

    # Dispatch
    resolved = resolve_model(model_raw)
    response_text, provider = router.dispatch(
        messages,
        resolved,
        temperature=settings.get("temperature", 0.7),
        max_tokens=settings.get("max_tokens", 4096),
        system_prompt=settings.get("system_prompt", ""),
    )

    # Save assistant message
    msg = models.add_message(conv_id, "assistant", response_text, model=resolved, provider=provider)

    # Auto-title from first message
    conv = models.get_conversation(conv_id)
    if conv and conv.get("title") == "New Chat" and message:
        title = message[:60] + ("..." if len(message) > 60 else "")
        models.update_conversation(conv_id, title=title)

    return jsonify({
        "conversation_id": conv_id,
        "message": msg,
        "model": resolved,
        "provider": provider,
    })


# ──── Models & Providers ─────────────────────────────────────────────

@api_bp.route("/models", methods=["GET"])
def list_models():
    return jsonify({"models": router.get_available_models()})


@api_bp.route("/providers", methods=["GET"])
def list_providers():
    return jsonify(router.check_backend_status())


# ──── File Upload ────────────────────────────────────────────────────

@api_bp.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "no file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "empty filename"}), 400
    result = file_handler.handle_upload(f)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


# ──── Settings ───────────────────────────────────────────────────────

@api_bp.route("/settings", methods=["GET"])
def get_settings():
    return jsonify(models.get_all_settings())


@api_bp.route("/settings", methods=["PUT"])
def update_settings():
    data = request.get_json(silent=True) or {}
    models.update_settings(data)
    return jsonify({"ok": True})


# ──── SocketIO Events ────────────────────────────────────────────────

def register_socketio_events(socketio: SocketIO) -> None:
    """Register SocketIO event handlers for streaming chat."""

    @socketio.on("send_message")
    def handle_send_message(data: dict) -> None:
        conv_id = data.get("conversation_id")
        content = data.get("content", "")
        model_raw = data.get("model", "gpt-5.4")

        if not content:
            socketio.emit("chat_error", {"error": "empty message"})
            return

        # Create conversation if needed
        if not conv_id:
            conv = models.create_conversation(model=resolve_model(model_raw))
            conv_id = conv["id"]
            socketio.emit("conversation_created", conv)

        # Save user message
        user_msg = models.add_message(conv_id, "user", content)
        socketio.emit("message_saved", user_msg)

        # Build messages from history
        history = models.get_messages(conv_id)
        messages = [{"role": m["role"], "content": m["content"]} for m in history]

        settings = models.get_all_settings()
        resolved = resolve_model(model_raw)

        # Stream response in background thread
        def _generate():
            try:
                gen = router.dispatch_stream(
                    messages,
                    resolved,
                    temperature=settings.get("temperature", 0.7),
                    max_tokens=settings.get("max_tokens", 4096),
                    system_prompt=settings.get("system_prompt", ""),
                )
                full_text = stream_to_socketio(socketio, conv_id, gen, resolved)

                # Detect provider from model
                provider = router._detect_backend(resolved)

                # Save assistant message
                models.add_message(conv_id, "assistant", full_text, model=resolved, provider=provider)

                # Auto-title
                conv = models.get_conversation(conv_id)
                if conv and conv.get("title") == "New Chat" and content:
                    title = content[:60] + ("..." if len(content) > 60 else "")
                    models.update_conversation(conv_id, title=title)

            except Exception as e:
                logger.error("[API] Streaming failed (operation=chat): %s", e)
                socketio.emit("chat_error", {
                    "conversation_id": conv_id,
                    "error": str(e),
                })

        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()

    @socketio.on("stop_generation")
    def handle_stop(_data: Any = None) -> None:
        # Future: implement cancellation token
        pass
