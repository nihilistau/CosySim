"""
nexus_session_logger.py — Logs Copilot CLI session events to Nexus.

Called by .github/hooks/session-logger/hooks.json on session lifecycle events.
Falls back to local logging if Nexus is unavailable.

Captures:
  - Git context (branch, recent commits, modified files)
  - Full conversation history from Copilot session store
  - Checkpoint summaries (auto-detected on each prompt)
  - Compaction snapshots (decisions, plans, git state)
  - Files created/edited during the session

On session end, exports complete history to Nexus and runs the knowledge
distiller to extract reusable facts and Q&A from the conversation.

On each prompt, auto-detects new checkpoints and exports them to Nexus.
On compaction, captures a full snapshot (checkpoints, decisions, plan, git).

Usage:
    python engine/nexus/nexus_session_logger.py start
    python engine/nexus/nexus_session_logger.py end
    python engine/nexus/nexus_session_logger.py prompt
    python engine/nexus/nexus_session_logger.py checkpoint
    python engine/nexus/nexus_session_logger.py compact
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

NEXUS_URL = os.environ.get("NEXUS_URL", "http://localhost:8700")
LOG_DIR = Path(__file__).resolve().parent.parent.parent / ".github" / "hooks" / "logs"
SESSION_FILE = LOG_DIR / "current_session.json"
SESSION_STORE_DB = Path.home() / ".copilot" / "session-store" / "store.sqlite"


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
            logger.debug("Suppressed exception", exc_info=True)
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


def _find_session_id() -> str | None:
    """Find current Copilot session ID from the session state directory."""
    state_dir = Path.home() / ".copilot" / "session-state"
    if not state_dir.exists():
        return None
    # Find most recently modified session directory
    sessions = [d for d in state_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if not sessions:
        return None
    return max(sessions, key=lambda d: d.stat().st_mtime).name


def _get_session_history(session_id: str) -> dict:
    """Extract full conversation history from Copilot session store.

    Returns dict with turns, checkpoints, files, refs.
    """
    result: dict = {"turns": [], "checkpoints": [], "files": [], "refs": []}

    # Try session store DB
    if SESSION_STORE_DB.exists():
        try:
            conn = sqlite3.connect(f"file:{SESSION_STORE_DB}?mode=ro", uri=True)
            try:
                conn.row_factory = sqlite3.Row

                # Get turns
                turns = conn.execute(
                    "SELECT turn_index, user_message, assistant_response, timestamp "
                    "FROM turns WHERE session_id = ? ORDER BY turn_index",
                    (session_id,),
                ).fetchall()
                result["turns"] = [
                    {
                        "turn": r["turn_index"],
                        "user": (r["user_message"] or "")[:2000],
                        "assistant": (r["assistant_response"] or "")[:3000],
                        "timestamp": r["timestamp"],
                    }
                    for r in turns
                ]

                # Get checkpoints
                cps = conn.execute(
                    "SELECT checkpoint_number, title, overview, work_done "
                    "FROM checkpoints WHERE session_id = ? ORDER BY checkpoint_number",
                    (session_id,),
                ).fetchall()
                result["checkpoints"] = [
                    {
                        "number": r["checkpoint_number"],
                        "title": r["title"],
                        "overview": (r["overview"] or "")[:1000],
                        "work_done": (r["work_done"] or "")[:1000],
                    }
                    for r in cps
                ]

                # Get files
                files = conn.execute(
                    "SELECT file_path, tool_name FROM session_files "
                    "WHERE session_id = ? ORDER BY first_seen_at",
                    (session_id,),
                ).fetchall()
                result["files"] = [
                    {"path": r["file_path"], "action": r["tool_name"]}
                    for r in files
                ]

                # Get refs
                refs = conn.execute(
                    "SELECT ref_type, ref_value FROM session_refs WHERE session_id = ?",
                    (session_id,),
                ).fetchall()
                result["refs"] = [
                    {"type": r["ref_type"], "value": r["ref_value"]}
                    for r in refs
                ]
            finally:
                conn.close()
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

    # Also try plan.md from session state
    plan_path = (
        Path.home() / ".copilot" / "session-state" / session_id / "plan.md"
    )
    if plan_path.exists():
        try:
            result["plan"] = plan_path.read_text(encoding="utf-8")[:5000]
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

    return result


def _build_history_entry(session: dict, git_ctx: dict, history: dict) -> str:
    """Build a comprehensive history entry from session data."""
    lines = []
    lines.append(f"Session: {session.get('started_at', '?')} to {session.get('ended_at', '?')}")
    lines.append(f"Branch: {git_ctx.get('branch', '?')}")
    lines.append(f"Prompts: {session.get('prompts', '?')}")
    lines.append(f"CWD: {session.get('cwd', '?')}")
    lines.append("")

    if git_ctx.get("last_commit"):
        lines.append(f"Last commit: {git_ctx['last_commit']}")
    if git_ctx.get("recent_commits"):
        lines.append("Recent commits:")
        for c in git_ctx["recent_commits"][:5]:
            lines.append(f"  - {c}")
        lines.append("")

    if history.get("files"):
        lines.append("Files touched:")
        for f in history["files"]:
            lines.append(f"  - [{f['action']}] {f['path']}")
        lines.append("")

    if history.get("refs"):
        lines.append("References:")
        for r in history["refs"]:
            lines.append(f"  - {r['type']}: {r['value']}")
        lines.append("")

    if history.get("checkpoints"):
        lines.append("Checkpoints:")
        for cp in history["checkpoints"]:
            lines.append(f"  {cp['number']}. {cp.get('title', 'Untitled')}")
            if cp.get("overview"):
                lines.append(f"     {cp['overview'][:200]}")
        lines.append("")

    return "\n".join(lines)


def _build_conversation_log(history: dict) -> str:
    """Build a formatted conversation log from turns."""
    lines = []
    for t in history.get("turns", []):
        user = t.get("user", "").strip()
        assistant = t.get("assistant", "").strip()
        if user:
            lines.append(f"[Turn {t['turn']}] USER: {user[:500]}")
        if assistant:
            lines.append(f"[Turn {t['turn']}] ASSISTANT: {assistant[:1000]}")
        lines.append("")
    return "\n".join(lines)


def _extract_key_decisions(history: dict) -> list[str]:
    """Extract key decisions and learnings from assistant responses."""
    decisions = []
    for t in history.get("turns", []):
        resp = t.get("assistant", "")
        # Look for decision markers
        for marker in ["Decision:", "Fixed:", "Created:", "Added:", "Updated:",
                        "Commit:", "Result:", "Architecture:"]:
            if marker in resp:
                idx = resp.index(marker)
                snippet = resp[idx:idx + 200].split("\n")[0]
                decisions.append(snippet)
    return decisions[:20]


def handle_start():
    """Called on session start — create session record with git context."""
    git_ctx = _get_git_context()
    session_id = _find_session_id()
    session = {
        "started_at": _now(),
        "prompts": 0,
        "cwd": os.getcwd(),
        "git": git_ctx,
        "session_id": session_id,
    }
    _save_session(session)
    _log_local("SESSION_START", session)

    branch_info = f" on branch '{git_ctx.get('branch', '?')}'" if git_ctx.get("branch") else ""
    content = (
        f"Copilot CLI session started in {os.getcwd()}{branch_info}.\n"
        f"Last commit: {git_ctx.get('last_commit', 'N/A')}\n"
        f"Session ID: {session_id or 'unknown'}"
    )
    _post("/api/entries", {
        "title": f"Copilot session started — {_now()}",
        "content": content,
        "content_type": "history",
        "category": "sessions",
        "tags": ["session", "copilot", "start", git_ctx.get("branch", "")],
    })


def handle_end():
    """Called on session end — export full history to Nexus."""
    session = _load_session()
    session["ended_at"] = _now()

    # Capture end-of-session git context
    end_git = _get_git_context()
    start_git = session.get("git", {})
    session_id = session.get("session_id") or _find_session_id()

    # Get full conversation history from session store
    history: dict = {}
    if session_id:
        history = _get_session_history(session_id)

    # Compute files changed during session
    start_files = set(start_git.get("modified_files", []))
    end_files = set(end_git.get("modified_files", []))
    new_changes = sorted(end_files - start_files) if end_files else []

    # 1. Store session summary entry
    summary = _build_history_entry(session, end_git, history)
    if new_changes:
        summary += f"\nFiles changed during session: {', '.join(new_changes[:20])}"

    _post("/api/entries", {
        "title": f"Copilot session ended — {_now()}",
        "content": summary,
        "content_type": "history",
        "category": "sessions",
        "tags": ["session", "copilot", "end", "summary",
                 end_git.get("branch", "")],
    })

    # 2. Store full conversation log (if we have turns)
    if history.get("turns"):
        conv_log = _build_conversation_log(history)
        if len(conv_log) > 100:
            # Truncate very long conversations to fit Nexus storage
            if len(conv_log) > 50000:
                conv_log = conv_log[:50000] + "\n\n[TRUNCATED — full log exceeded 50k chars]"
            _post("/api/entries", {
                "title": f"Conversation log — {_now()} ({len(history['turns'])} turns)",
                "content": conv_log,
                "content_type": "history",
                "category": "sessions",
                "tags": ["session", "copilot", "conversation-log",
                         end_git.get("branch", ""),
                         f"turns:{len(history['turns'])}"],
            })

    # 3. Store plan if it exists
    if history.get("plan"):
        _post("/api/entries", {
            "title": f"Session plan — {_now()}",
            "content": history["plan"],
            "content_type": "document",
            "category": "sessions",
            "tags": ["session", "copilot", "plan", end_git.get("branch", "")],
        })

    # 4. Extract and store key decisions as Q&A
    decisions = _extract_key_decisions(history)
    for dec in decisions[:5]:
        _post("/api/qa", {
            "question": f"What was decided about: {dec[:80]}?",
            "answer": dec,
            "category": "decisions",
            "tags": ["copilot", "decision", "auto-extracted"],
        })

    # 5. Store checkpoint summaries as knowledge
    for cp in history.get("checkpoints", []):
        if cp.get("work_done"):
            _post("/api/entries", {
                "title": f"Checkpoint {cp['number']}: {cp.get('title', 'Untitled')}",
                "content": (
                    f"Overview: {cp.get('overview', 'N/A')}\n\n"
                    f"Work done: {cp.get('work_done', 'N/A')}"
                ),
                "content_type": "history",
                "category": "sessions",
                "tags": ["session", "copilot", "checkpoint",
                         end_git.get("branch", "")],
            })

    _log_local("SESSION_END", {
        "prompts": session.get("prompts", 0),
        "turns": len(history.get("turns", [])),
        "files": len(history.get("files", [])),
        "checkpoints": len(history.get("checkpoints", [])),
    })

    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def handle_prompt():
    """Called on user prompt submission — increment counter and check for new checkpoints."""
    session = _load_session()
    session["prompts"] = session.get("prompts", 0) + 1
    session["last_prompt_at"] = _now()
    _save_session(session)
    _log_local("PROMPT", {"count": session["prompts"]})

    # Auto-detect and export new checkpoints
    _auto_export_checkpoints(session)


def _auto_export_checkpoints(session: dict):
    """Detect new checkpoints in session-state and export to Nexus."""
    session_id = session.get("session_id") or _find_session_id()
    if not session_id:
        return

    checkpoints_dir = (
        Path.home() / ".copilot" / "session-state" / session_id / "checkpoints"
    )
    if not checkpoints_dir.exists():
        return

    # Track which checkpoints we've already exported
    exported = set(session.get("exported_checkpoints", []))
    cp_files = sorted(checkpoints_dir.glob("*.md"))

    new_count = 0
    for cp_file in cp_files:
        if cp_file.name == "index.md" or cp_file.name in exported:
            continue

        try:
            content = cp_file.read_text(encoding="utf-8")[:8000]
        except Exception:
            continue

        # Extract title from first heading or filename
        title = cp_file.stem.replace("-", " ").title()
        for line in content.splitlines()[:5]:
            if line.startswith("# "):
                title = line[2:].strip()
                break

        result = _post("/api/entries", {
            "title": f"Checkpoint: {title}",
            "content": content,
            "content_type": "history",
            "category": "sessions",
            "tags": ["copilot", "checkpoint", "auto-export",
                     session.get("git", {}).get("branch", "")],
        })

        if result and result.get("ok"):
            exported.add(cp_file.name)
            new_count += 1
            _log_local("CHECKPOINT_EXPORTED", {"file": cp_file.name, "title": title})

    if new_count > 0:
        session["exported_checkpoints"] = sorted(exported)
        _save_session(session)


def handle_checkpoint():
    """Explicitly export all new checkpoints to Nexus.

    Called manually or by Copilot CLI on checkpoint/compaction events.
    """
    session = _load_session()
    session_id = session.get("session_id") or _find_session_id()
    if session_id:
        session["session_id"] = session_id
    _auto_export_checkpoints(session)
    _log_local("CHECKPOINT_MANUAL")


def handle_compaction():
    """Called on context compaction — export current state to Nexus.

    Compaction means the context window is being summarised. We capture
    the current checkpoint, conversation summary, and git state before
    the older context is lost.
    """
    session = _load_session()
    session_id = session.get("session_id") or _find_session_id()
    git_ctx = _get_git_context()

    # Export any new checkpoints first
    if session_id:
        session["session_id"] = session_id
    _auto_export_checkpoints(session)

    # Build compaction snapshot
    history: dict = {}
    if session_id:
        history = _get_session_history(session_id)

    snapshot_parts = [
        f"Compaction at {_now()}",
        f"Branch: {git_ctx.get('branch', '?')}",
        f"Prompts so far: {session.get('prompts', '?')}",
        f"Session started: {session.get('started_at', '?')}",
    ]

    if git_ctx.get("last_commit"):
        snapshot_parts.append(f"Last commit: {git_ctx['last_commit']}")

    if history.get("checkpoints"):
        snapshot_parts.append(f"\nCheckpoints ({len(history['checkpoints'])}):")
        for cp in history["checkpoints"]:
            snapshot_parts.append(f"  {cp['number']}. {cp.get('title', 'Untitled')}")
            if cp.get("overview"):
                snapshot_parts.append(f"     {cp['overview'][:300]}")

    if history.get("plan"):
        snapshot_parts.append(f"\nPlan (truncated):\n{history['plan'][:2000]}")

    # Extract decisions from recent turns
    decisions = _extract_key_decisions(history)
    if decisions:
        snapshot_parts.append(f"\nKey decisions ({len(decisions)}):")
        for d in decisions[:10]:
            snapshot_parts.append(f"  - {d}")

    snapshot = "\n".join(snapshot_parts)

    _post("/api/entries", {
        "title": f"Compaction snapshot — {_now()}",
        "content": snapshot,
        "content_type": "history",
        "category": "sessions",
        "tags": ["copilot", "compaction", "snapshot",
                 git_ctx.get("branch", "")],
    })

    _log_local("COMPACTION", {
        "prompts": session.get("prompts", 0),
        "checkpoints": len(history.get("checkpoints", [])),
        "decisions": len(decisions),
    })


def main():
    if len(sys.argv) < 2:
        print("Usage: nexus_session_logger.py [start|end|prompt|checkpoint|compact]")
        sys.exit(1)

    action = sys.argv[1].lower()
    handlers = {
        "start": handle_start,
        "end": handle_end,
        "prompt": handle_prompt,
        "checkpoint": handle_checkpoint,
        "compact": handle_compaction,
    }
    handler = handlers.get(action)
    if handler:
        handler()
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
