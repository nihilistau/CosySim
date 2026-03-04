"""MCP tool domain: backup.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── BACKUP TOOLS ───────────────────────────────────────────────────────


@mcp_tool
async def backup_run() -> str:
    """Trigger an immediate database backup."""
    from engine.nexus.backup_manager import get_backup_manager
    mgr = get_backup_manager()
    result = mgr.run_backup()
    return json.dumps(result.to_dict() if hasattr(result, "to_dict") else {"result": str(result)}, indent=2)


@mcp_tool
async def backup_list() -> str:
    """List all available database backups."""
    from engine.nexus.backup_manager import get_backup_manager
    mgr = get_backup_manager()
    backups = mgr.list_backups()
    if not backups:
        return "No backups found."
    lines = ["=== Database Backups ==="]
    for b in backups[:20]:
        lines.append(f"  {b.get('timestamp', '?')} | {b.get('size_mb', 0):.1f}MB | {b.get('targets', [])}")
    return "\n".join(lines)


@mcp_tool
async def backup_restore(backup_path: str, target: str = "nexus") -> str:
    """Restore a specific database backup.

    Args:
        backup_path: Path to the backup file.
        target: Which database to restore (nexus | session | all).
    """
    from engine.nexus.backup_manager import get_backup_manager
    result = get_backup_manager().restore_backup(backup_path, target)
    return json.dumps(result, indent=2)
