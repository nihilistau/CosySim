"""
Oracle Pre-Session Health Check
================================

Runs at session start and after test commands to surface system health
and errors. Output goes to Claude Code's conversation context so the AI
immediately knows what's broken before starting work.

Version: v1.49.4 [2026-03-22]
Author:  CosySim Team

CONNECTS: engine/observability/oracle.py, engine/observability/error_aggregator.py
CALLED BY: Claude Code hooks (SessionStart, PostToolUse:Bash)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure project root on path
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
os.chdir(str(_ROOT))


def _quick_health() -> str:
    """Run a minimal health check and return a compact summary string.

    Designed to be fast (<3s) and ASCII-safe for hook output.
    """
    lines = []
    try:
        from engine.observability.oracle import ensure_initialized
        ensure_initialized()
    except Exception:
        return "[Oracle] Init failed — observability unavailable"

    # Service health
    try:
        from engine.logging.monitor import get_system_monitor
        mon = get_system_monitor()
        services = mon.check_services()
        up = []
        down = []
        for name, info in services.items():
            if isinstance(info, dict) and info.get("up"):
                up.append(name)
            else:
                down.append(name)
        if down:
            lines.append(f"[Oracle] Services DOWN: {', '.join(down)}")
        if up:
            lines.append(f"[Oracle] Services UP: {', '.join(up)}")
    except Exception:
        lines.append("[Oracle] Service health unavailable")

    # Error summary
    try:
        from engine.observability.error_aggregator import get_error_aggregator
        agg = get_error_aggregator()
        snap = agg.snapshot()
        if snap["total_count"] > 0:
            rate = snap["error_rate"]["rate_per_min"]
            lines.append(f"[Oracle] Errors: {snap['total_unique']} unique, {snap['total_count']} total, {rate}/min")
            for err in snap["top_errors"][:3]:
                mod = err["module"].split(".")[-1] if "." in err["module"] else err["module"]
                lines.append(f"  [{err['count']}x] {mod}: {err['sample_message'][:60]}")
        else:
            lines.append("[Oracle] No errors — system healthy")
    except Exception:
        pass

    return "\n".join(lines) if lines else "[Oracle] System check complete"


def main() -> None:
    """Hook entry point. Reads stdin JSON, decides whether to run."""
    mode = "session_start"  # default

    # Try to read hook context from stdin
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            tool_name = data.get("tool_name", "")
            tool_input = data.get("tool_input", {})

            # Only run after Bash commands that are test-related
            if tool_name == "Bash":
                cmd = tool_input.get("command", "")
                # Trigger on test runs, launcher commands, or explicit oracle calls
                is_test = any(k in cmd for k in ["pytest", "smart_test", "browser_test"])
                is_launch = any(k in cmd for k in ["launcher.py", "tui.py"])
                if not (is_test or is_launch):
                    return  # Skip non-relevant Bash commands
                mode = "post_test"
            else:
                return  # Only care about Bash tool
    except Exception:
        pass  # No stdin = session start mode

    result = _quick_health()
    if result:
        print(result)


if __name__ == "__main__":
    main()
