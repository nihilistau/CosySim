"""
CosySim Unified Hook Runner
=============================

Single entry point for all Claude Code hooks. Routes to the right check
based on the hook event and tool context. Fast (<2s for most checks),
async, and never blocks the session.

Hooks provided:
  1. Oracle health check — service health + error aggregation (on prompt + post-test)
  2. Python syntax guard — catch syntax errors immediately after .py edits
  3. Git context — branch + uncommitted count on every prompt
  4. Test result capture — extract pass/fail after pytest runs
  5. Session activity log — track edited files for easy commit messages

Version: v1.49.4 [2026-03-22]
Author:  CosySim Team

CONNECTS: Oracle, git, Python AST, pytest output
CALLED BY: Claude Code hooks (UserPromptSubmit, PostToolUse, SessionStart)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
os.chdir(str(_ROOT))
sys.path.insert(0, str(_ROOT))

# Session activity log (append-only, survives across hook invocations)
_ACTIVITY_LOG = Path(__file__).parent / "logs" / "session_activity.jsonl"


def main() -> None:
    """Route to the appropriate hook handler based on stdin context."""
    # Parse hook context
    event = os.environ.get("CLAUDE_HOOK_EVENT", "")
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass

    data = {}
    if raw.strip():
        try:
            data = json.loads(raw)
        except Exception:
            pass

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}
    tool_response = data.get("tool_response", {}) or {}

    lines = []

    # ── Route by context ──────────────────────────────────────────

    if not tool_name:
        # UserPromptSubmit or SessionStart — give Claude the full picture
        lines.extend(_git_context())
        lines.extend(_oracle_quick())

    elif tool_name in ("Edit", "Write"):
        # After file edits — syntax check Python files
        file_path = (
            tool_input.get("file_path", "")
            or tool_response.get("filePath", "")
            or ""
        )
        if file_path:
            _log_activity("edit", file_path)
            if file_path.endswith(".py"):
                lines.extend(_python_syntax_check(file_path))

    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        # After pytest — capture test results
        if any(k in cmd for k in ["pytest", "smart_test", "browser_test"]):
            lines.extend(_test_result_capture(tool_response))
            lines.extend(_oracle_quick())
        # After git commands — update context
        elif any(k in cmd for k in ["git commit", "git push", "git checkout", "git merge"]):
            lines.extend(_git_context())
        # After launcher — check health
        elif any(k in cmd for k in ["launcher.py", "tui.py"]):
            lines.extend(_oracle_quick())

    # Output (only if we have something useful to say)
    if lines:
        output = "\n".join(lines)
        # Return as hook JSON with additionalContext
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse" if tool_name else "UserPromptSubmit",
                "additionalContext": output,
            }
        }
        print(json.dumps(result))


# ──── Git Context ─────────────────────────────────────────────────────────

def _git_context() -> list[str]:
    """Return current branch + uncommitted file count."""
    lines = []
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=3, cwd=str(_ROOT),
        ).stdout.strip()

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=3, cwd=str(_ROOT),
        ).stdout.strip()

        file_count = len([l for l in status.split("\n") if l.strip()]) if status else 0

        if file_count > 0:
            lines.append(f"[Git] Branch: {branch} | {file_count} uncommitted file(s)")
        else:
            lines.append(f"[Git] Branch: {branch} | Clean working tree")
    except Exception:
        pass
    return lines


# ──── Oracle Quick Health ─────────────────────────────────────────────────

def _oracle_quick() -> list[str]:
    """Run a minimal Oracle health + error check."""
    lines = []
    try:
        from engine.observability.oracle import ensure_initialized
        ensure_initialized()

        from engine.logging.monitor import get_system_monitor
        mon = get_system_monitor()
        services = mon.check_services()
        down = [n for n, i in services.items() if isinstance(i, dict) and not i.get("up")]
        if down:
            lines.append(f"[Oracle] Services DOWN: {', '.join(down)}")

        from engine.observability.error_aggregator import get_error_aggregator
        agg = get_error_aggregator()
        snap = agg.snapshot()
        if snap["total_count"] > 0:
            rate = snap["error_rate"]["rate_per_min"]
            lines.append(f"[Oracle] {snap['total_unique']} error type(s), {rate}/min")
            for err in snap["top_errors"][:2]:
                mod = err["module"].split(".")[-1]
                lines.append(f"  [{err['count']}x] {mod}: {err['sample_message'][:50]}")
    except Exception:
        pass
    return lines


# ──── Python Syntax Guard ─────────────────────────────────────────────────

def _python_syntax_check(file_path: str) -> list[str]:
    """Quick AST parse to catch syntax errors immediately after edit."""
    lines = []
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open(r'{file_path}', encoding='utf-8').read())"],
            capture_output=True, text=True, timeout=5, cwd=str(_ROOT),
        )
        if result.returncode != 0:
            err = result.stderr.strip().split("\n")[-1] if result.stderr else "Unknown error"
            short_path = str(Path(file_path).relative_to(_ROOT)) if file_path.startswith(str(_ROOT)) else file_path
            lines.append(f"[SyntaxGuard] SYNTAX ERROR in {short_path}: {err}")
    except Exception:
        pass
    return lines


# ──── Test Result Capture ─────────────────────────────────────────────────

def _test_result_capture(tool_response: dict) -> list[str]:
    """Extract pass/fail counts from pytest output."""
    lines = []
    try:
        output = ""
        if isinstance(tool_response, dict):
            output = tool_response.get("stdout", "") or tool_response.get("output", "") or str(tool_response)

        # Look for pytest summary line: "X passed, Y failed, Z warnings in N.NNs"
        import re
        match = re.search(r"(\d+)\s+passed", output)
        failed_match = re.search(r"(\d+)\s+failed", output)
        error_match = re.search(r"(\d+)\s+error", output)

        parts = []
        if match:
            parts.append(f"{match.group(1)} passed")
        if failed_match:
            parts.append(f"{failed_match.group(1)} FAILED")
        if error_match:
            parts.append(f"{error_match.group(1)} errors")

        if parts:
            summary = " | ".join(parts)
            if failed_match or error_match:
                lines.append(f"[Tests] {summary} -- CHECK FAILURES")
            else:
                lines.append(f"[Tests] {summary}")
    except Exception:
        pass
    return lines


# ──── Session Activity Log ────────────────────────────────────────────────

def _log_activity(action: str, file_path: str) -> None:
    """Append to session activity log for easy commit message generation."""
    try:
        _ACTIVITY_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.strftime("%H:%M:%S"),
            "action": action,
            "file": str(Path(file_path).relative_to(_ROOT)) if file_path.startswith(str(_ROOT)) else file_path,
        }
        with open(_ACTIVITY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
