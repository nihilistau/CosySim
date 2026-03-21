#!/bin/bash
# ============================================================
# post-tool.sh — Claude Code PostToolUse hook
# ============================================================
#
# Lightweight hook that appends tool usage to a JSONL log file.
# Used for training data collection and session analytics.
#
# Version: v1.44.0 [2026-03-21]
# Author:  CosySim Team
#
# CONNECTS: .claude/hooks/logs/tool_usage.jsonl
# CALLED BY: Claude Code PostToolUse hook event
# ============================================================

set -euo pipefail

INPUT=$(cat)
LOG_DIR="$(dirname "$0")/logs"
mkdir -p "$LOG_DIR"

# Append tool usage record with timestamp
echo "$INPUT" | python3 -c "
import sys, json
from datetime import datetime
try:
    data = json.load(sys.stdin)
    record = {
        'ts': datetime.now().isoformat(),
        'session': data.get('session_id', ''),
        'tool': data.get('tool_name', ''),
        'input_keys': list(data.get('tool_input', {}).keys()) if isinstance(data.get('tool_input'), dict) else [],
    }
    with open('$LOG_DIR/tool_usage.jsonl', 'a') as f:
        f.write(json.dumps(record) + '\n')
except:
    pass
" 2>/dev/null || true

exit 0
