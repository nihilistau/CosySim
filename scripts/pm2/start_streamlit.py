"""PM2 wrapper: start a Streamlit app.

Replaces the `python -m streamlit run ...` pattern that PM2 on Windows
cannot handle (script: '-m' is treated as a filename).

Usage:
    python scripts/pm2/start_streamlit.py <script_path> [--server.port=PORT] [...]
"""
from __future__ import annotations

import subprocess
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/pm2/start_streamlit.py <script.py> [streamlit args...]")
        sys.exit(1)

    cmd = [sys.executable, "-m", "streamlit", "run"] + sys.argv[1:]

    kwargs: dict = {
        "cwd": PROJECT_ROOT,
        "env": {**os.environ, "PYTHONPATH": PROJECT_ROOT, "PYTHONUNBUFFERED": "1"},
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    sys.exit(subprocess.call(cmd, **kwargs))
