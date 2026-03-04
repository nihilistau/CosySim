"""MCP tool domain: copilot.

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

# ──── COPILOT TOOLS ──────────────────────────────────────────────────────


@mcp_tool
def copilot_store_snippet(title: str, code: str, language: str = "python",
                          tags: str = "") -> str:
    """Store a reusable code snippet in Nexus for future sessions."""
    try:
        from engine.nexus.copilot_helpers import store_snippet
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        result = store_snippet(title, code, language, tag_list)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def copilot_store_discovery(title: str, finding: str,
                            category: str = "debugging") -> str:
    """Store a discovery, workaround, or gotcha in Nexus."""
    try:
        from engine.nexus.copilot_helpers import store_discovery
        result = store_discovery(title, finding, category)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def copilot_log_progress(task: str, status: str = "completed", details: str = "",
                         tests_passed: int = 0, commit_sha: str = "") -> str:
    """Log work progress to Nexus for tracking across sessions."""
    try:
        from engine.nexus.copilot_helpers import log_work_progress
        result = log_work_progress(task, status, details, tests_passed=tests_passed,
                                   commit_sha=commit_sha)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def copilot_context_primer(project: str = "CosySim") -> str:
    """Generate a context primer from Nexus knowledge for new sessions."""
    try:
        from engine.nexus.copilot_helpers import generate_context_primer
        return generate_context_primer(project)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def copilot_local_model_guide(task_type: str = "general") -> str:
    """Get guidance text for local LMStudio models to safely use Nexus."""
    try:
        from engine.nexus.copilot_helpers import generate_local_model_guidance
        return generate_local_model_guidance(task_type)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def copilot_sync_config() -> str:
    """Sync all Copilot instruction files, agent definitions, and hooks to Nexus."""
    try:
        from engine.nexus.copilot_self_config import get_copilot_config
        return json.dumps(get_copilot_config().sync_all_to_nexus(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def copilot_config_status() -> str:
    """Get Copilot configuration status — counts of instructions, agents, hooks."""
    try:
        from engine.nexus.copilot_self_config import get_copilot_config
        return json.dumps(get_copilot_config().status(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def copilot_list_instructions() -> str:
    """List all Copilot instruction files with names and sizes."""
    try:
        from engine.nexus.copilot_self_config import get_copilot_config
        return json.dumps(get_copilot_config().list_instructions(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def copilot_list_agents() -> str:
    """List all Copilot agent definition files."""
    try:
        from engine.nexus.copilot_self_config import get_copilot_config
        return json.dumps(get_copilot_config().list_agents(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
