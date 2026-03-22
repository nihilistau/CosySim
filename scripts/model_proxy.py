"""Model Proxy — OpenAI-compatible API server backed by free frontier models.

Exposes /v1/chat/completions, /v1/models, and /health endpoints.
Any tool that speaks OpenAI protocol can connect: Cursor, Continue,
aider, open-interpreter, LMStudio as client, etc.

Point your tool at http://localhost:5800/v1 and select any model.

Usage:
    python scripts/model_proxy.py                    # start on :5800
    python scripts/model_proxy.py --port 8080        # custom port
    python scripts/model_proxy.py --default opus     # default model

Version: v1.50.1 [2026-03-23]
Author:  CosySim Team
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("model_proxy")

# ──── Model routing ───────────────────────────────────────────────────────────

ALIASES = {
    "opus": "claude-opus-4.6",
    "sonnet": "claude-sonnet-4.6",
    "haiku": "claude-haiku-4.5",
    "gpt5": "gpt-5.4",
    "gpt": "gpt-5.4",
    "codex": "gpt-5.3-codex",
    "gemini": "gemini-3.1-pro",
    "flash": "gemini-3-flash",
    "grok": "grok-code-fast-1",
    # OpenAI-compatible aliases that tools might send
    "gpt-4": "gpt-5.4",
    "gpt-4o": "gpt-5.4",
    "gpt-4-turbo": "gpt-5.4",
    "gpt-3.5-turbo": "gpt-5.4",
    "claude-3-opus": "claude-opus-4.6",
    "claude-3-sonnet": "claude-sonnet-4.6",
    "claude-3-haiku": "claude-haiku-4.5",
    "claude-3.5-sonnet": "claude-sonnet-4.6",
}

COPILOT_MODELS = [
    {"id": "claude-opus-4.6", "vendor": "Anthropic"},
    {"id": "claude-sonnet-4.6", "vendor": "Anthropic"},
    {"id": "claude-sonnet-4.5", "vendor": "Anthropic"},
    {"id": "claude-sonnet-4", "vendor": "Anthropic"},
    {"id": "claude-opus-4.5", "vendor": "Anthropic"},
    {"id": "claude-haiku-4.5", "vendor": "Anthropic"},
    {"id": "gpt-5.4", "vendor": "OpenAI"},
    {"id": "gpt-5.4-mini", "vendor": "OpenAI"},
    {"id": "gpt-5.3-codex", "vendor": "OpenAI"},
    {"id": "gpt-5.2-codex", "vendor": "OpenAI"},
    {"id": "gpt-5.2", "vendor": "OpenAI"},
    {"id": "gpt-5.1", "vendor": "OpenAI"},
    {"id": "gpt-5.1-codex-max", "vendor": "OpenAI"},
    {"id": "gpt-5-mini", "vendor": "OpenAI"},
    {"id": "gemini-3.1-pro", "vendor": "Google"},
    {"id": "gemini-3-pro", "vendor": "Google"},
    {"id": "gemini-3-flash", "vendor": "Google"},
    {"id": "gemini-2.5-pro", "vendor": "Google"},
    {"id": "grok-code-fast-1", "vendor": "xAI"},
    {"id": "nlm", "vendor": "Google (NotebookLM)"},
]


def resolve_model(model: str) -> str:
    """Resolve aliases and partial matches to actual model ID."""
    if model in ALIASES:
        return ALIASES[model]
    for m in COPILOT_MODELS:
        if model.lower() == m["id"].lower():
            return m["id"]
    # Partial match
    for m in COPILOT_MODELS:
        if model.lower() in m["id"].lower():
            return m["id"]
    return model


# ──── Backend calls ───────────────────────────────────────────────────────────

def call_copilot(messages: List[Dict], model: str, account: str = "nihilistcod") -> str:
    """Route to GitHub Copilot."""
    from engine.integrations.github_copilot_client import GithubCopilotClient

    client = GithubCopilotClient(account)
    thread_id = client.create_thread()

    # Combine messages into a single prompt (Copilot expects one message)
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            parts.append(f"System: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
        else:
            parts.append(content)
    prompt = "\n\n".join(parts)

    response = client.send_message(thread_id, prompt, model=model)
    if isinstance(response, tuple):
        return response[0] if response[0] else str(response)
    return str(response)


def call_nlm(messages: List[Dict], port: int = 9223) -> str:
    """Route to NotebookLM via CDP."""
    from scripts.nlm_ask import ask

    # Use the last user message as the prompt
    prompt = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            prompt = msg.get("content", "")
            break
    if not prompt:
        prompt = messages[-1].get("content", "") if messages else ""

    return asyncio.run(ask(prompt, port))


# ──── FastAPI server ──────────────────────────────────────────────────────────

def create_app(default_model: str = "gpt-5.4", account: str = "nihilistcod", cdp_port: int = 9223):
    """Create the FastAPI application."""
    from fastapi import FastAPI, Body
    from fastapi.responses import JSONResponse

    app = FastAPI(title="CosySim Model Proxy", version="1.50.1")

    @app.get("/health")
    async def health():
        return {"status": "ok", "models": len(COPILOT_MODELS), "default": default_model}

    @app.get("/v1/models")
    async def list_models():
        """OpenAI-compatible model list."""
        data = []
        for m in COPILOT_MODELS:
            data.append({
                "id": m["id"],
                "object": "model",
                "created": 1700000000,
                "owned_by": m["vendor"],
            })
        return {"object": "list", "data": data}

    @app.post("/v1/chat/completions")
    async def chat_completions(body: Dict[str, Any] = Body(...)):
        """OpenAI-compatible chat completions endpoint."""
        messages = body.get("messages", [])
        model_raw = body.get("model", default_model)
        model = resolve_model(model_raw)
        stream = body.get("stream", False)

        logger.info("Request: model=%s (resolved=%s) messages=%d stream=%s",
                     model_raw, model, len(messages), stream)

        t0 = time.time()

        try:
            if model == "nlm":
                content = call_nlm(messages, cdp_port)
            else:
                content = call_copilot(messages, model, account)
        except Exception as exc:
            logger.error("Backend error: %s", exc)
            return JSONResponse(
                status_code=502,
                content={"error": {"message": str(exc), "type": "backend_error"}},
            )

        elapsed = time.time() - t0
        logger.info("Response: %d chars in %.1fs via %s", len(content), elapsed, model)

        # Clean encoding artifacts
        if isinstance(content, str):
            content = (content
                       .replace("\u00e2\u0080\u0099", "'")
                       .replace("\u00e2\u0080\u009c", '"')
                       .replace("\u00e2\u0080\u009d", '"')
                       .replace("\u00e2\u0080\u0094", "—"))

        # Build OpenAI-compatible response
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

        if stream:
            # SSE streaming response
            from fastapi.responses import StreamingResponse

            async def generate():
                # Single chunk with the full response
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant", "content": content},
                        "finish_reason": None,
                    }],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                # Final chunk
                done_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(done_chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(generate(), media_type="text/event-stream")

        # Non-streaming response
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": sum(len(m.get("content", "")) // 4 for m in messages),
                "completion_tokens": len(content) // 4,
                "total_tokens": (sum(len(m.get("content", "")) // 4 for m in messages) + len(content) // 4),
            },
        }

    return app


# ──── Main ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Model Proxy — OpenAI-compatible API for frontier models")
    parser.add_argument("--port", type=int, default=5800, help="Server port (default: 5800)")
    parser.add_argument("--default", default="gpt-5.4", help="Default model")
    parser.add_argument("--account", default="nihilistcod", help="GitHub account for Copilot")
    parser.add_argument("--cdp-port", type=int, default=9223, help="CDP port for NLM")
    args = parser.parse_args()

    default_model = resolve_model(args.default)
    app = create_app(default_model=default_model, account=args.account, cdp_port=args.cdp_port)

    print(f"\n{'='*60}")
    print(f"  CosySim Model Proxy v1.50.1")
    print(f"  http://localhost:{args.port}/v1/chat/completions")
    print(f"  Default model: {default_model}")
    print(f"  Models: {len(COPILOT_MODELS)} (Copilot + NLM)")
    print(f"{'='*60}\n")
    print(f"  Point any OpenAI-compatible tool at:")
    print(f"    Base URL:  http://localhost:{args.port}/v1")
    print(f"    API Key:   anything (not checked)")
    print(f"    Model:     {default_model}")
    print(f"\n  Examples:")
    print(f"    curl http://localhost:{args.port}/v1/models")
    print(f"    curl -X POST http://localhost:{args.port}/v1/chat/completions \\")
    print(f"      -H 'Content-Type: application/json' \\")
    print(f"      -d '{{\"model\": \"opus\", \"messages\": [{{\"role\": \"user\", \"content\": \"hello\"}}]}}'")
    print()

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
