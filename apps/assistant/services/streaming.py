"""
Assistant Platform — Streaming Helpers
========================================

Converts content generators to SocketIO events or SSE format.

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Dual streaming: SocketIO + SSE
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Generator


# ──── SocketIO Streaming ─────────────────────────────────────────────

def stream_to_socketio(
    socketio: Any,
    conversation_id: str,
    generator: Generator[str, None, None],
    model: str,
) -> str:
    """Consume a content generator and emit SocketIO events.

    Emits:
        chat_delta: {content, conversation_id, done: false}
        chat_complete: {conversation_id, model, full_content, done: true}

    Returns:
        The full accumulated response text.
    """
    full_content = ""

    for chunk in generator:
        if chunk:
            full_content += chunk
            socketio.emit("chat_delta", {
                "content": chunk,
                "conversation_id": conversation_id,
                "done": False,
            })

    socketio.emit("chat_complete", {
        "conversation_id": conversation_id,
        "model": model,
        "full_content": full_content,
        "done": True,
    })

    return full_content


# ──── SSE Streaming (OpenAI-compatible) ──────────────────────────────

def stream_to_sse(
    generator: Generator[str, None, None],
    model: str,
    completion_id: str = "",
) -> Generator[str, None, None]:
    """Consume a content generator and yield SSE-formatted chunks.

    Matches the exact OpenAI streaming format:
        data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[...]}
        data: [DONE]
    """
    if not completion_id:
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    for chunk in generator:
        if chunk:
            data = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": chunk},
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(data)}\n\n"

    # Final chunk — finish_reason: stop
    done_data = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(done_data)}\n\n"
    yield "data: [DONE]\n\n"


# ──── Non-Streaming Response Builder ─────────────────────────────────

def build_completion_response(
    content: str,
    model: str,
    prompt_tokens: int = 0,
) -> Dict[str, Any]:
    """Build a standard OpenAI chat.completion response."""
    completion_tokens = len(content) // 4
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
