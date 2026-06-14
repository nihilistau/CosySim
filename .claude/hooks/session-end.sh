#!/bin/bash
# ============================================================
# session-end.sh — Claude Code SessionEnd hook
# ============================================================
#
# Runs when a Claude Code session ends. Logs session summary,
# tool usage, and file changes to NEXUS KMS for training data
# and continuity across sessions.
#
# Version: v1.44.0 [2026-03-21]
# Author:  CosySim Team
#
# CONNECTS: NEXUS KMS (:8700), git, Claude Code hooks system
# CALLED BY: Claude Code SessionEnd hook event
# EMITS: Session entry in NEXUS (content_type=history, category=session)
# ============================================================

set -euo pipefail

# Read hook input from stdin
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id','unknown'))" 2>/dev/null || echo "unknown")
TRANSCRIPT_PATH=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null || echo "")
CWD=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd','.'))" 2>/dev/null || echo ".")
REASON=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reason','unknown'))" 2>/dev/null || echo "unknown")

cd "$CWD" 2>/dev/null || true

# Run the Python session logger
python3 "$CWD/.claude/hooks/session-end.py" \
    --session-id "$SESSION_ID" \
    --transcript "$TRANSCRIPT_PATH" \
    --cwd "$CWD" \
    --reason "$REASON" \
    2>/dev/null || true

exit 0
