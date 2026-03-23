"""
Assistant Platform — OpenAI-Compatible API
============================================

/v1/chat/completions and /v1/models endpoints for external tools
(aider, Continue, Cursor, Open Interpreter, etc.)

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — OpenAI-compat proxy with streaming SSE
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict

from flask import Blueprint, Response, jsonify, request

from apps.assistant.config import COPILOT_MODELS, resolve_model
from apps.assistant.services import router
from apps.assistant.services.streaming import build_completion_response, stream_to_sse

logger = logging.getLogger(__name__)

openai_bp = Blueprint("openai", __name__)


# ──── Model List ─────────────────────────────────────────────────────

@openai_bp.route("/v1/models", methods=["GET"])
def list_models():
    """OpenAI-compatible model list."""
    data = []
    for m in COPILOT_MODELS:
        data.append({
            "id": m["id"],
            "object": "model",
            "created": 1700000000,
            "owned_by": m["vendor"],
        })

    # Add local LMStudio models
    try:
        from engine.lmstudio.lms_client import get_lms_client
        client = get_lms_client()
        if client.is_available():
            for m in client.get_models(loaded_only=False):
                data.append({
                    "id": m.key,
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": "local",
                })
    except Exception:
        pass

    # NLM
    data.append({
        "id": "nlm",
        "object": "model",
        "created": 1700000000,
        "owned_by": "Google (NotebookLM)",
    })

    return jsonify({"object": "list", "data": data})


# ──── Chat Completions ───────────────────────────────────────────────

@openai_bp.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    """OpenAI-compatible chat completions — streaming and non-streaming."""
    body = request.get_json(silent=True) or {}
    messages = body.get("messages", [])
    model_raw = body.get("model", "gpt-5.4")
    stream = body.get("stream", False)
    temperature = body.get("temperature", 0.7)
    max_tokens = body.get("max_tokens", 4096)

    model = resolve_model(model_raw)

    logger.info(
        "[OpenAI] Request: model=%s (resolved=%s) messages=%d stream=%s",
        model_raw, model, len(messages), stream,
    )

    if stream:
        return _handle_streaming(messages, model, temperature, max_tokens)
    else:
        return _handle_non_streaming(messages, model, temperature, max_tokens)


def _handle_streaming(
    messages: list,
    model: str,
    temperature: float,
    max_tokens: int,
) -> Response:
    """Handle streaming chat completions — returns SSE Response."""
    try:
        gen = router.dispatch_stream(
            messages, model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        sse_gen = stream_to_sse(gen, model)
        return Response(sse_gen, content_type="text/event-stream")
    except Exception as e:
        logger.error("[OpenAI] Streaming error (operation=chat): %s", e)
        return jsonify({
            "error": {"message": str(e), "type": "backend_error"}
        }), 502


def _handle_non_streaming(
    messages: list,
    model: str,
    temperature: float,
    max_tokens: int,
) -> Dict[str, Any]:
    """Handle non-streaming chat completions."""
    t0 = time.time()

    try:
        content, provider = router.dispatch(
            messages, model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.error("[OpenAI] Backend error (operation=chat): %s", e)
        return jsonify({
            "error": {"message": str(e), "type": "backend_error"}
        }), 502

    elapsed = time.time() - t0
    logger.info("[OpenAI] Response: %d chars in %.1fs via %s", len(content), elapsed, model)

    # Clean encoding artifacts
    if isinstance(content, str):
        content = (content
                   .replace("\u00e2\u0080\u0099", "'")
                   .replace("\u00e2\u0080\u009c", '"')
                   .replace("\u00e2\u0080\u009d", '"')
                   .replace("\u00e2\u0080\u0094", "\u2014"))

    prompt_tokens = sum(len(m.get("content", "")) // 4 for m in messages)
    return jsonify(build_completion_response(content, model, prompt_tokens))
