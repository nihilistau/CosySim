"""
Post-Tool Hook — Track Claude Code tool usage
================================================

Appends tool usage records to a JSONL log file for
training data collection and session analytics.

Version: v1.44.0 [2026-03-21]
Author:  CosySim Team

CONNECTS: .claude/hooks/logs/tool_usage.jsonl
CALLED BY: Claude Code PostToolUse hook event (stdin JSON)
"""
import json
import sys
from datetime import datetime
from pathlib import Path


def main() -> None:
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "tool_usage.jsonl"

    try:
        data = json.loads(sys.stdin.read())
        tool_input = data.get("tool_input", {})
        record = {
            "ts": datetime.now().isoformat(),
            "session": data.get("session_id", ""),
            "tool": data.get("tool_name", ""),
            "input_keys": list(tool_input.keys()) if isinstance(tool_input, dict) else [],
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass  # Never block the session


if __name__ == "__main__":
    main()
