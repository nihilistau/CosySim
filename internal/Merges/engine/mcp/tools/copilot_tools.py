from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from engine.mcp.decorators import mcp_tool, ToolExecutionError

@mcp_tool
def copilot_store_snippet_impl(title: str, code: str, language: str = 'python', tags: str = '') -> Any:
    """Store a reusable code snippet in Nexus for future sessions."""
    from engine.nexus.copilot_helpers import store_snippet
    tag_list = [t.strip() for t in tags.split(',') if t.strip()] if tags else []
    result = store_snippet(title, code, language, tag_list)
    return result


@mcp_tool
def copilot_store_discovery_impl(title: str, finding: str, category: str = 'debugging') -> Any:
    """Store a discovery, workaround, or gotcha in Nexus."""
    from engine.nexus.copilot_helpers import store_discovery
    result = store_discovery(title, finding, category)
    return result


@mcp_tool
def copilot_log_progress_impl(task: str, status: str = 'completed', details: str = '', tests_passed: int = 0, commit_sha: str = '') -> Any:
    """Log work progress to Nexus for tracking across sessions."""
    from engine.nexus.copilot_helpers import log_work_progress
    result = log_work_progress(task, status, details, tests_passed=tests_passed, commit_sha=commit_sha)
    return result


@mcp_tool
def copilot_context_primer_impl(project: str = 'CosySim') -> Any:
    """Generate a context primer from Nexus knowledge for new sessions."""
    from engine.nexus.copilot_helpers import generate_context_primer
    return generate_context_primer(project)


@mcp_tool
def copilot_local_model_guide_impl(task_type: str = 'general') -> Any:
    """Get guidance text for local LMStudio models to safely use Nexus."""
    from engine.nexus.copilot_helpers import generate_local_model_guidance
    return generate_local_model_guidance(task_type)


@mcp_tool
def copilot_sync_config_impl() -> Any:
    """Sync all Copilot instruction files, agent definitions, and hooks to Nexus."""
    from engine.nexus.copilot_self_config import get_copilot_config
    return get_copilot_config(.sync_all_to_nexus(), default=str)


@mcp_tool
def copilot_config_status_impl() -> Any:
    """Get Copilot configuration status — counts of instructions, agents, hooks."""
    from engine.nexus.copilot_self_config import get_copilot_config
    return get_copilot_config(.status(), default=str)


@mcp_tool
def copilot_list_instructions_impl() -> Any:
    """List all Copilot instruction files with names and sizes."""
    from engine.nexus.copilot_self_config import get_copilot_config
    return get_copilot_config(.list_instructions(), default=str)


@mcp_tool
def copilot_list_agents_impl() -> Any:
    """List all Copilot agent definition files."""
    from engine.nexus.copilot_self_config import get_copilot_config
    return get_copilot_config(.list_agents(), default=str)
