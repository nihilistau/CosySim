"""
nexus_session_logger.py — Logs Copilot CLI session events to Nexus.

Called by .github/hooks/session-logger/hooks.json on session lifecycle events.
Falls back to local logging if Nexus is unavailable.

Captures git context (branch, recent commits, modified files) and stores
enriched session records in Nexus for project history tracking.

Usage:
    python engine/nexus/nexus_session_logger.py start
    python engine/nexus/nexus_session_logger.py end
    python engine/nexus/nexus_session_logger.py prompt
"""
from __future__ import annotations

import json
import os
import subprocess
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


def _git(cmd: str) -> str:
    """Run a git command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "--no-pager"] + cmd.split(),
            capture_output=True, text=True, timeout=5, cwd=os.getcwd(),
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _get_git_context() -> dict:
    """Gather current git context: branch, recent commits, modified files."""
    ctx: dict = {}
    branch = _git("rev-parse --abbrev-ref HEAD")
    if branch:
        ctx["branch"] = branch

    last_commit = _git("log -1 --oneline")
    if last_commit:
        ctx["last_commit"] = last_commit

    recent = _git("log -5 --oneline")
    if recent:
        ctx["recent_commits"] = recent.splitlines()

    modified = _git("diff --name-only")
    staged = _git("diff --cached --name-only")
    files = set()
    if modified:
        files.update(modified.splitlines())
    if staged:
        files.update(staged.splitlines())
    if files:
        ctx["modified_files"] = sorted(files)

    return ctx


def handle_start():
    """Called on session start — create session record with git context."""
    git_ctx = _get_git_context()
    session = {
        "started_at": _now(),
        "prompts": 0,
        "cwd": os.getcwd(),
        "git": git_ctx,
    }
    _save_session(session)
    _log_local("SESSION_START", session)

    branch_info = f" on branch '{git_ctx.get('branch', '?')}'" if git_ctx.get("branch") else ""
    content = (
        f"Copilot CLI session started in {os.getcwd()}{branch_info}.\n"
        f"Last commit: {git_ctx.get('last_commit', 'N/A')}"
    )
    _post("/api/entries", {
        "title": f"Copilot session started — {_now()}",
        "content": content,
        "content_type": "history",
        "category": "sessions",
        "tags": ["session", "copilot-cli", "start", git_ctx.get("branch", "")],
    })


def handle_end():
    """Called on session end — finalize with git diff summary."""
    session = _load_session()
    session["ended_at"] = _now()
    duration_info = ""
    if "started_at" in session:
        duration_info = f" (started: {session['started_at']})"

    # Capture end-of-session git context
    end_git = _get_git_context()
    start_git = session.get("git", {})

    # Compute files changed during session
    start_files = set(start_git.get("modified_files", []))
    end_files = set(end_git.get("modified_files", []))
    new_changes = sorted(end_files - start_files) if end_files else []

    summary_lines = [
        f"Copilot CLI session ended{duration_info}.",
        f"Prompts: {session.get('prompts', '?')}",
        f"CWD: {session.get('cwd', '?')}",
        f"Branch: {end_git.get('branch', '?')}",
    ]
    if end_git.get("last_commit"):
        summary_lines.append(f"Last commit: {end_git['last_commit']}")
    if new_changes:
        summary_lines.append(f"Files changed during session: {', '.join(new_changes[:20])}")

    summary = "\n".join(summary_lines)
    _log_local("SESSION_END", session)

    _post("/api/entries", {
        "title": f"Copilot session ended — {_now()}",
        "content": summary,
        "content_type": "history",
        "category": "sessions",
        "tags": ["session", "copilot-cli", "end", end_git.get("branch", "")],
    })

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
