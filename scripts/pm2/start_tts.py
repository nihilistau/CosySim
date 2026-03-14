"""PM2 wrapper: start CosySim TTS server.

Replaces the inline `python -c "import uvicorn; ..."` pattern that
PM2 on Windows cannot handle (script: '-c' is treated as a filename).
"""
from __future__ import annotations

import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import uvicorn
from engine.tts.qwen3_server import create_tts_app

if __name__ == "__main__":
    app = create_tts_app()
    uvicorn.run(app, host="0.0.0.0", port=8600, log_level="warning")
