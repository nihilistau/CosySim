"""MCP tool domain: master_notebook.

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

# ──── MASTER_NOTEBOOK TOOLS ──────────────────────────────────────────────


@mcp_tool
async def master_notebook_build(
    sources_only: bool = False,
    generators_only: bool = False,
    notebook_id: str = "",
    dry_run: bool = False,
) -> str:
    """Build or refresh the CosySim Master Intelligence notebook.

    Bundles all engine code, docs, configs, JS, and SDK URLs into NotebookLM,
    then runs all generators (audio, video, study guide, FAQ, briefing, Q&A).

    sources_only: Only upload sources, skip generators.
    generators_only: Skip upload, only run generators.
    notebook_id: Use existing notebook ID (skips creation).
    dry_run: Print plan without making NLM calls.
    """
    from engine.nexus.master_notebook_builder import MasterNotebookBuilder
    builder = MasterNotebookBuilder(dry_run=dry_run)
    result = builder.build(
        notebook_id=notebook_id or None,
        sources_only=sources_only,
        generators_only=generators_only,
    )
    return json.dumps(result, indent=2, default=str)


@mcp_tool
async def master_notebook_status() -> str:
    """Get status of the master notebook build (what's been done, what's pending)."""
    from engine.nexus.master_notebook_builder import _load_state, DISTILLATION_QUESTIONS
    state = _load_state()
    nb_id = state.get("notebook_id", "not created yet")
    sources_done = len(state.get("sources_uploaded", []))
    gens_done = state.get("generators_done", [])
    qa_done = state.get("qa_done_index", 0)
    qa_total = len(DISTILLATION_QUESTIONS)
    lines = [
        "=== Master Notebook Status ===",
        f"Notebook ID   : {nb_id}",
        f"Last build    : {state.get('last_build', 'never')}",
        f"Sources done  : {sources_done}",
        f"Generators    : {', '.join(gens_done) or 'none yet'}",
        f"Q&A distilled : {qa_done}/{qa_total}",
    ]
    return "\n".join(lines)


@mcp_tool
async def master_notebook_reset() -> str:
    """Reset master notebook build state (forces fresh creation and full re-upload).

    WARNING: This will delete the stored notebook ID. A new notebook will be
    created on the next build. Use this when you want a completely fresh start.
    """
    from engine.nexus.master_notebook_builder import _STATE_FILE
    try:
        if _STATE_FILE.exists():
            _STATE_FILE.unlink()
        return "Master notebook state reset. Next build will create a fresh notebook."
    except Exception as exc:
        return f"Reset failed: {exc}"


@mcp_tool
async def master_notebook_list_sources() -> str:
    """List all sources that will be included in the master notebook.

    Shows all 13 code bundles + 19 SDK documentation URLs.
    """
    from engine.nexus.master_notebook_builder import SDK_URLS
    lines = ["=== Master Notebook Source Manifest ===\n", "TEXT BUNDLES (code + docs):"]
    text_bundles = [
        "CosySim Hardware & System Specification",
        "Engine Framework: Config, MCP, Scenes, Agents",
        "Engine Nexus: Knowledge Management System",
        "Engine LMStudio: LLM Inference Integration",
        "Engine MCP Servers: DevTools, NLM Hybrid, Bridges",
        "Engine Skills: @skill Decorator + All Builtin Packs",
        "Engine Services: TTS, Integrations, Assistant",
        "Scene Implementations: Top 8 Scenes",
        "Config Files, Governance Rules & Copilot Instructions",
        "Documentation: Architecture, Guides, Protocols",
        "Frontend JavaScript: All Scene + Shared JS",
        "Test Suite: Patterns and Conventions",
        "Dependencies: requirements.txt, package.json, pyproject.toml",
    ]
    for i, b in enumerate(text_bundles, 1):
        lines.append(f"  {i:2}. {b}")
    lines.append(f"\nSDK / API DOCUMENTATION URLs ({len(SDK_URLS)} sources):")
    for i, sdk in enumerate(SDK_URLS, 1):
        lines.append(f"  {i:2}. {sdk['label']} → {sdk['url']}")
    lines.append(f"\nTotal sources: {len(text_bundles) + len(SDK_URLS)}")
    return "\n".join(lines)
