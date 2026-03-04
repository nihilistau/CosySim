"""MCP tool domain: cache_pipeline.

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

# ──── CACHE_PIPELINE TOOLS ───────────────────────────────────────────────


@mcp_tool
def cache_pipeline_run(stages: str = "") -> str:
    """Run the NLM-driven QA cache generation pipeline (Gemini 3.0 full cycle).

    Mines session history, uploads to NLM notebooks, generates Q&A pairs via
    quota-free Studio tiles, evaluates with Gemini 3.0, and stores approved
    pairs in Nexus. Expected output: +500-1000 net new pairs per cycle.

    Args:
        stages: Optional JSON array of stage letters to run (e.g. '["A","B","C"]').
            Defaults to full cycle (all stages A-J).
    """
    try:
        from engine.nexus.cache_pipeline import get_cache_pipeline
        pipeline = get_cache_pipeline()
        result = pipeline.run_full_cycle()
        return json.dumps({
            "stored": result.stored,
            "direct_seeded": result.direct_seeded,
            "essential": result.essential,
            "useful": result.useful,
            "skipped": result.skipped,
            "gaps": result.gaps[:10],
            "review_sheet_path": result.review_sheet_path,
            "duration_s": round(result.duration_s, 1),
            "errors": result.errors[:5],
            "timestamp": result.timestamp,
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def cache_pipeline_status() -> str:
    """Get the status of the last QA cache pipeline run — pair counts, gaps, timing."""
    try:
        from engine.nexus.cache_pipeline import get_cache_pipeline
        pipeline = get_cache_pipeline()
        return json.dumps(pipeline.get_status(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
