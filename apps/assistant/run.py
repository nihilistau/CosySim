"""
Assistant Platform — Launcher
==============================

Start the Advanced Assistant with: python apps/assistant/run.py

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Initial launcher
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# ── Path setup (allow imports from project root) ─────────────────────
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from apps.assistant.config import APP_NAME, APP_PORT, APP_HOST


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} — Advanced AI Chat Interface")
    parser.add_argument("--port", type=int, default=APP_PORT, help=f"Server port (default: {APP_PORT})")
    parser.add_argument("--host", default=APP_HOST, help=f"Bind host (default: {APP_HOST})")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    from apps.assistant.app import create_app
    app, socketio = create_app()

    print(f"\n{'=' * 60}")
    print(f"  {APP_NAME} v1.0.0")
    print(f"  http://localhost:{args.port}")
    print(f"{'=' * 60}")
    print(f"\n  Web UI:     http://localhost:{args.port}")
    print(f"  OpenAI API: http://localhost:{args.port}/v1")
    print(f"  Health:     http://localhost:{args.port}/health")
    print(f"\n  Connect external tools (aider, Continue, Cursor):")
    print(f"    Base URL:  http://localhost:{args.port}/v1")
    print(f"    API Key:   anything (not checked)")
    print()

    socketio.run(
        app,
        host=args.host,
        port=args.port,
        debug=args.debug,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()
