"""MCP tool domain: qa.

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

# ──── QA TOOLS ───────────────────────────────────────────────────────────


@mcp_tool
async def qa_expander_run(batch_size: int = 20, dry_run: bool = False) -> str:
    """Run one batch of QA expansion — reverse-generate Q&A pairs from Nexus entries.

    For each entry, asks NLM to generate 5 questions it answers, then stores
    the pairs in Nexus for instant cache hits. Processes batch_size entries per call.

    batch_size: Number of entries to process (default 20).
    dry_run: Show what would be processed without making NLM calls.
    """
    from engine.nexus.qa_expander import QAExpander
    expander = QAExpander(dry_run=dry_run)
    result = expander.run(batch_size=batch_size)
    return json.dumps(result, indent=2, default=str)


@mcp_tool
async def qa_expander_stats() -> str:
    """Show QA expansion progress: entries expanded, pairs generated, last run."""
    from engine.nexus.qa_expander import get_qa_expander
    stats = get_qa_expander().stats()
    lines = [
        "=== QA Expander Stats ===",
        f"Entries expanded : {stats['entries_expanded']}",
        f"Pairs generated  : {stats['total_generated']}",
        f"Nexus Q&A count  : {stats['nexus_qa_count']}",
        f"Last run         : {stats['last_run']}",
        f"Total runs       : {stats['runs']}",
        f"Notebook ID      : {stats['notebook_id']}",
    ]
    return "\n".join(lines)


@mcp_tool
async def qa_expander_reset() -> str:
    """Reset QA expansion state — next run will start from the beginning.

    WARNING: This clears all progress tracking. The Q&A pairs already stored
    in Nexus are preserved, but expansion will re-process all entries.
    """
    from engine.nexus.qa_expander import QAExpander
    QAExpander().reset()
    return "QA expander state reset. Next run will process all entries from scratch."


@mcp_tool
async def qa_expander_reset() -> str:
    """Reset QA expansion state — next run will start from the beginning.    WARNING: This clears all progress tracking. The Q&A pairs already stored
    in Nexus are preserved, but expansion will re-process all entries.
    """
    from engine.nexus.qa_expander import QAExpander
    QAExpander().reset()
    return "QA expander state reset. Next run will process all entries from scratch."
