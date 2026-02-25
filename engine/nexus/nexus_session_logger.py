"""
nexus_session_logger.py — Logs Copilot CLI session events to Nexus.

Called by .github/hooks/session-logger/hooks.json on session lifecycle events.
Falls back to local logging if Nexus is unavailable.

Usage:
    python engine/nexus/nexus_session_logger.py start
    python engine/nexus/nexus_session_logger.py end
    python engine/nexus/nexus_session_logger.py prompt
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

NEXUS_URL = os.environ.get("NEXUS_URL", "http://localhost:8700")
LOG_DIR = Path(__file__).resolve().parent.parent.parent / ".github" / "hooks" / "logs"
SESSION_FILE = LOG_DIR / "current_session.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _post(path: str, data: dict, timeout: int = 5) -> dict | None:
    """Post to Nexus API. Returns response or None on failure."""
    try:
        url = f"{NEXUS_URL}{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _log_local(event: str, data: dict | None = None):
    """Append to local log file as fallback."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{_now()}] {event}"
    if data:
        line += f" | {json.dumps(data)}"
    with open(LOG_DIR / "session.log", "a") as f:
        f.write(line + "\n")


def _load_session() -> dict:
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_session(data: dict):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(data, indent=2))


def handle_start():
    """Called on session start — create session record."""
    session = {
        "started_at": _now(),
        "prompts": 0,
        "cwd": os.getcwd(),
    }
    _save_session(session)
    _log_local("SESSION_START", session)

    # Log to Nexus
    _post("/api/agent/submit", {
        "agent_id": "copilot-cli",
        "entry_type": "note",
        "title": f"Session started — {_now()}",
        "content": f"Copilot CLI session started in {os.getcwd()}",
        "tags": ["session", "copilot-cli", "start"],
        "category": "development",
    })


def handle_end():
    """Called on session end — finalize and log summary."""
    session = _load_session()
    session["ended_at"] = _now()
    duration_info = ""
    if "started_at" in session:
        duration_info = f" (started: {session['started_at']})"

    summary = (
        f"Copilot CLI session ended{duration_info}. "
        f"Prompts: {session.get('prompts', '?')}. "
        f"CWD: {session.get('cwd', '?')}"
    )
    _log_local("SESSION_END", session)

    # Log to Nexus
    _post("/api/agent/submit", {
        "agent_id": "copilot-cli",
        "entry_type": "note",
        "title": f"Session ended — {_now()}",
        "content": summary,
        "tags": ["session", "copilot-cli", "end"],
        "category": "development",
    })

    # Clean up session file
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def handle_prompt():
    """Called on user prompt submission — increment counter."""
    session = _load_session()
    session["prompts"] = session.get("prompts", 0) + 1
    session["last_prompt_at"] = _now()
    _save_session(session)
    _log_local("PROMPT", {"count": session["prompts"]})


def main():
    if len(sys.argv) < 2:
        print("Usage: nexus_session_logger.py [start|end|prompt]")
        sys.exit(1)

    action = sys.argv[1].lower()
    handlers = {"start": handle_start, "end": handle_end, "prompt": handle_prompt}
    handler = handlers.get(action)
    if handler:
        handler()
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
