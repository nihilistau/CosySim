"""MCP tool domain: review.

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

# ──── REVIEW TOOLS ───────────────────────────────────────────────────────


@mcp_tool
def review_sheet_generate(output_path: str = "") -> str:
    """Generate a fresh Excel review sheet for pending Q&A cache pairs.

    Creates an xlsx file with formulas (Include? column auto-fills YES for
    ESSENTIAL/USEFUL), dropdown validation, and conditional formatting.

    Args:
        output_path: Where to save the xlsx. Defaults to
            data/qa_review_{YYYY-MM-DD}.xlsx.
    """
    try:
        from datetime import datetime
        from engine.nexus.review_sheet import get_review_sheet
        from engine.nexus.cache_pipeline import get_cache_pipeline, CandidatePair

        if not output_path:
            date_str = datetime.now().strftime("%Y-%m-%d")
            output_path = f"data/qa_review_{date_str}.xlsx"

        pipeline = get_cache_pipeline()
        pending_pairs: list = []
        try:
            import json as _json
            from pathlib import Path
            state_path = getattr(pipeline, "_state_path", None)
            if state_path and Path(state_path).exists():
                state = _json.loads(Path(state_path).read_text())
                for p in state.get("last_candidates", []):
                    pending_pairs.append(CandidatePair(
                        q=p.get("q", ""),
                        a=p.get("a", ""),
                        consumer=p.get("consumer", "developer"),
                        priority=int(p.get("priority", 3)),
                        category=p.get("category", "general"),
                    ))
        except Exception:
            pass

        rs = get_review_sheet()
        saved = rs.generate(pending_pairs, output_path)
        return json.dumps({"saved_path": saved, "row_count": len(pending_pairs)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def review_sheet_import(path: str) -> str:
    """Import a reviewed Excel Q&A review sheet back into the Nexus cache.

    Reads rows where Include? == "YES" and stores them in the Nexus Q&A cache
    with consumer, priority, and category metadata.

    Args:
        path: Path to the reviewed .xlsx file.
    """
    try:
        from engine.nexus.review_sheet import get_review_sheet
        from engine.nexus.client import get_nexus_client
        rs = get_review_sheet()
        count = rs.import_reviewed(path, get_nexus_client())
        return json.dumps({"imported": count, "path": path})
    except Exception as e:
        return json.dumps({"error": str(e)})
