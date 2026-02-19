"""
Web Bridge — Unified FastAPI + MCP server for CosySim scenes

This module provides a FastAPI application that:

1. **SSE Streaming Proxy** — streams LMStudio responses to the browser
2. **MCP Mount** — mounts the CosySim MCP server for LMStudio discovery
3. **File Upload** — accepts user uploads exposed as MCP resources
4. **Abort Support** — client disconnect stops LMStudio generation
5. **CORS** — allows browser-based scene UIs to call the API

Mount onto an existing Flask app::

    from engine.mcp.web_bridge import create_bridge_app
    bridge = create_bridge_app()
    # Run alongside your Flask scene

Or run standalone::

    python -m engine.mcp.web_bridge  # port 8600
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

# ── Directories ────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent
UPLOAD_DIR = _PROJECT_ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def create_bridge_app(
    lmstudio_url: Optional[str] = None,
    mount_mcp: bool = True,
) -> FastAPI:
    """
    Create a FastAPI bridge app with LMStudio proxy and MCP mount.

    Args:
        lmstudio_url: LMStudio base URL (default from config).
        mount_mcp: Whether to mount the CosySim MCP server at ``/mcp``.
    """
    if lmstudio_url is None:
        try:
            from engine.config import get_config
            config = get_config()
            host = config.get("lmstudio.host", "127.0.0.1")
            port = int(config.get("lmstudio.port", 1234))
            lmstudio_url = f"http://{host}:{port}"
        except Exception:
            lmstudio_url = "http://127.0.0.1:1234"

    app = FastAPI(title="CosySim Bridge", version="1.0.0")

    # CORS for browser access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health ──────────────────────────────────────────────────────

    @app.get("/api/health")
    async def health():
        """Bridge health check."""
        lms_ok = False
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{lmstudio_url}/v1/models", timeout=3.0)
                lms_ok = r.status_code == 200
        except Exception:
            pass
        return {
            "bridge": "ok",
            "lmstudio": "connected" if lms_ok else "disconnected",
            "lmstudio_url": lmstudio_url,
        }

    # ── File Upload ─────────────────────────────────────────────────

    @app.post("/api/upload")
    async def upload_file(file: UploadFile = File(...)):
        """Upload a file for MCP resource exposure."""
        file_id = str(uuid.uuid4())[:8]
        ext = Path(file.filename).suffix if file.filename else ".txt"
        file_path = UPLOAD_DIR / f"{file_id}{ext}"
        content = await file.read()
        file_path.write_bytes(content)
        return {
            "file_id": file_id,
            "mcp_uri": f"upload://{file_id}",
            "size_bytes": len(content),
        }

    # ── Chat Proxy (non-streaming) ──────────────────────────────────

    @app.post("/api/chat")
    async def chat_proxy(request: Request):
        """
        Proxy a chat request to LMStudio.

        Accepts the same JSON body as OpenAI chat completions
        plus the ``integrations`` field for MCP tools.
        """
        body = await request.json()
        body["stream"] = False

        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(
                    f"{lmstudio_url}/v1/chat/completions",
                    json=body,
                    timeout=120.0,
                )
                return JSONResponse(r.json(), status_code=r.status_code)
            except httpx.ConnectError:
                raise HTTPException(502, "Cannot connect to LMStudio")
            except Exception as e:
                raise HTTPException(500, f"LMStudio error: {e}")

    # ── Chat Proxy (streaming SSE) ──────────────────────────────────

    @app.post("/api/chat/stream")
    async def chat_stream_proxy(request: Request):
        """
        Streaming proxy: pipes SSE chunks from LMStudio to the browser.

        Client disconnect → stops reading → LMStudio stops generating.
        """
        body = await request.json()
        body["stream"] = True

        async def event_generator():
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST",
                        f"{lmstudio_url}/v1/chat/completions",
                        json=body,
                        timeout=None,
                    ) as response:
                        async for line in response.aiter_lines():
                            # Check if browser disconnected
                            if await request.is_disconnected():
                                logger.info("Client disconnected, stopping stream")
                                break
                            if line.startswith("data: "):
                                yield f"{line}\n\n"
                            if "[DONE]" in line:
                                yield "data: [DONE]\n\n"
                                break
            except httpx.ConnectError:
                yield f'data: {{"error": "Cannot connect to LMStudio"}}\n\n'
            except Exception as e:
                yield f'data: {{"error": "{str(e)}"}}\n\n'

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── MCP Mount ───────────────────────────────────────────────────

    if mount_mcp:
        try:
            from engine.mcp.cosysim_server import mcp as cosysim_mcp
            mcp_app = cosysim_mcp.http_app(path="/mcp")
            app.mount("/mcp", mcp_app)
            logger.info("CosySim MCP server mounted at /mcp")
        except Exception as e:
            logger.warning("Failed to mount MCP server: %s", e)

    return app


# ── Standalone entry point ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="CosySim Web Bridge")
    parser.add_argument("--port", type=int, default=8600, help="Port (default 8600)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default 0.0.0.0)")
    args = parser.parse_args()

    app = create_bridge_app()

    print(f"\n🌉 CosySim Web Bridge starting on http://{args.host}:{args.port}")
    print(f"   MCP endpoint: http://localhost:{args.port}/mcp/sse")
    print(f"   Streaming:    POST http://localhost:{args.port}/api/chat/stream")
    print(f"   Upload:       POST http://localhost:{args.port}/api/upload")
    print()

    uvicorn.run(app, host=args.host, port=args.port)
