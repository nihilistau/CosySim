"""
Session End Hook — Log Claude Code session to NEXUS KMS
========================================================

Parses the session transcript, extracts tool usage stats,
file changes, and a session summary. Stores in NEXUS for
training data collection and session continuity.

Version: v1.44.0 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.44.0 [2026-03-21] — Initial hook implementation

CONNECTS: NEXUS KMS (engine/nexus/client.py), git
CALLED BY: .claude/hooks/session-end.sh (Claude Code SessionEnd)
EMITS: NEXUS entry (content_type=history, category=session)
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("session-end-hook")


# ──── Transcript Parsing ─────────────────────────────────────────────

def parse_transcript(transcript_path: str) -> Dict[str, Any]:
    """Parse a Claude Code transcript JSONL file.

    Returns:
        Dict with tool_counts, message_count, files_edited, duration_estimate.
    """
    result: Dict[str, Any] = {
        "tool_counts": {},
        "message_count": 0,
        "user_messages": 0,
        "assistant_messages": 0,
        "files_edited": set(),
        "files_created": set(),
        "errors": 0,
    }

    if not transcript_path or not Path(transcript_path).exists():
        return result

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                result["message_count"] += 1
                msg_type = entry.get("type", "")

                if msg_type == "user" or entry.get("role") == "human":
                    result["user_messages"] += 1
                elif msg_type == "assistant" or entry.get("role") == "assistant":
                    result["assistant_messages"] += 1

                # Track tool usage
                if msg_type == "tool_use" or "tool_use" in str(entry.get("type", "")):
                    tool_name = entry.get("name", entry.get("tool", "unknown"))
                    result["tool_counts"][tool_name] = (
                        result["tool_counts"].get(tool_name, 0) + 1
                    )

                    # Track file edits
                    tool_input = entry.get("input", {})
                    if isinstance(tool_input, dict):
                        file_path = tool_input.get("file_path", "")
                        if file_path:
                            if tool_name in ("Write",):
                                result["files_created"].add(file_path)
                            elif tool_name in ("Edit",):
                                result["files_edited"].add(file_path)

                # Track errors
                if entry.get("is_error") or "error" in str(entry.get("type", "")).lower():
                    result["errors"] += 1

    except Exception as exc:
        logger.warning("Transcript parse failed: %s", exc)

    # Convert sets to lists for JSON serialization
    result["files_edited"] = sorted(result["files_edited"])
    result["files_created"] = sorted(result["files_created"])
    return result


# ──── Git Context ────────────────────────────────────────────────────

def get_git_context(cwd: str) -> Dict[str, Any]:
    """Gather git context: branch, recent commits, changed files."""
    context: Dict[str, Any] = {}
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            cwd=cwd, timeout=5, stderr=subprocess.DEVNULL,
        ).decode().strip()
        context["branch"] = branch

        # Recent commits (last 5)
        log = subprocess.check_output(
            ["git", "log", "--oneline", "-5"],
            cwd=cwd, timeout=5, stderr=subprocess.DEVNULL,
        ).decode().strip()
        context["recent_commits"] = log.splitlines()

        # Changed files count
        status = subprocess.check_output(
            ["git", "diff", "--stat", "--shortstat"],
            cwd=cwd, timeout=5, stderr=subprocess.DEVNULL,
        ).decode().strip()
        context["diff_summary"] = status.splitlines()[-1] if status else "No changes"

    except Exception as exc:
        logger.debug("Git context failed: %s", exc)
        context["error"] = str(exc)

    return context


# ──── NEXUS Storage ──────────────────────────────────────────────────

def store_to_nexus(
    session_id: str,
    reason: str,
    transcript_data: Dict[str, Any],
    git_context: Dict[str, Any],
    cwd: str,
) -> Optional[str]:
    """Store session summary in NEXUS KMS.

    CONNECTS: engine/nexus/client.py → NexusClient.add_entry()
    """
    try:
        # Add project root to path for engine imports
        sys.path.insert(0, cwd)
        from engine.nexus.client import get_nexus_client

        client = get_nexus_client()

        # Build session summary
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        tool_summary = ", ".join(
            f"{name}({count})"
            for name, count in sorted(
                transcript_data.get("tool_counts", {}).items(),
                key=lambda x: -x[1],
            )[:10]
        )

        files_edited = transcript_data.get("files_edited", [])
        files_created = transcript_data.get("files_created", [])
        branch = git_context.get("branch", "unknown")
        recent_commits = git_context.get("recent_commits", [])
        diff_summary = git_context.get("diff_summary", "")

        content_lines = [
            f"# Claude Code Session — {timestamp}",
            f"",
            f"**Session ID:** {session_id}",
            f"**End Reason:** {reason}",
            f"**Branch:** {branch}",
            f"**Messages:** {transcript_data.get('message_count', 0)} "
            f"({transcript_data.get('user_messages', 0)} user, "
            f"{transcript_data.get('assistant_messages', 0)} assistant)",
            f"**Errors:** {transcript_data.get('errors', 0)}",
            f"",
            f"## Tool Usage",
            f"{tool_summary or 'No tools used'}",
            f"",
        ]

        if files_edited:
            content_lines.append("## Files Edited")
            for fp in files_edited[:20]:
                content_lines.append(f"- `{fp}`")
            content_lines.append("")

        if files_created:
            content_lines.append("## Files Created")
            for fp in files_created[:10]:
                content_lines.append(f"- `{fp}`")
            content_lines.append("")

        if recent_commits:
            content_lines.append("## Recent Commits")
            for c in recent_commits:
                content_lines.append(f"- {c}")
            content_lines.append("")

        if diff_summary:
            content_lines.append(f"## Diff Summary")
            content_lines.append(f"{diff_summary}")

        content = "\n".join(content_lines)

        # Store in NEXUS
        entry_id = client.add_entry(
            title=f"Claude Code Session — {timestamp} ({reason})",
            content=content,
            content_type="history",
            category="session",
            tags=[
                "claude-code",
                "session",
                "auto-generated",
                f"branch:{branch}",
                f"reason:{reason}",
            ],
            created_by="claude-code-hook",
        )

        if entry_id:
            logger.info("Session logged to NEXUS: %s", entry_id)
        return entry_id

    except ImportError:
        logger.debug("NEXUS client not available — skipping session log")
    except Exception as exc:
        logger.warning("NEXUS session log failed: %s", exc)
    return None


# ──── Main ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code session end hook")
    parser.add_argument("--session-id", default="unknown")
    parser.add_argument("--transcript", default="")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--reason", default="unknown")
    # v1.44.0 — Windows-compatible: read hook JSON from stdin directly
    parser.add_argument("--from-stdin", action="store_true",
                        help="Read hook input JSON from stdin (Claude Code hook mode)")
    args = parser.parse_args()

    session_id = args.session_id
    transcript = args.transcript
    cwd = args.cwd
    reason = args.reason

    # When called as a Claude Code hook, read JSON from stdin
    if args.from_stdin:
        try:
            hook_input = json.loads(sys.stdin.read())
            session_id = hook_input.get("session_id", session_id)
            transcript = hook_input.get("transcript_path", transcript)
            cwd = hook_input.get("cwd", cwd)
            reason = hook_input.get("reason", reason)
        except Exception:
            pass  # Fall through with defaults

    # Parse transcript
    transcript_data = parse_transcript(transcript)

    # Gather git context
    git_context = get_git_context(cwd)

    # Store to NEXUS
    store_to_nexus(
        session_id=session_id,
        reason=reason,
        transcript_data=transcript_data,
        git_context=git_context,
        cwd=cwd,
    )


if __name__ == "__main__":
    main()
