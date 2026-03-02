from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from engine.mcp.decorators import mcp_tool, ToolExecutionError


@mcp_tool
def nlm_notebook_list_impl() -> Dict[str, Any]:
    """List all managed NLM notebooks with health: source counts, ages,
    last seeded/asked dates, and overall slot health."""
    try:
        from engine.nexus.nlm_notebook_manager import get_notebook_manager

        return get_notebook_manager().health()
    except Exception as e:
        raise ToolExecutionError(str(e))


@mcp_tool
def nlm_notebook_seed_impl(
    slot_name: str = "cosysim-architecture", source_type: str = "docs"
) -> Dict[str, Any]:
    """Seed an NLM notebook from project files. source_type: 'docs' for
    documentation, 'code' for engine source files."""
    try:
        from engine.nexus.nlm_notebook_manager import get_notebook_manager

        mgr = get_notebook_manager()
        if source_type == "code":
            return mgr.seed_from_code(slot_name)
        return mgr.seed_from_docs(slot_name)
    except Exception as e:
        raise ToolExecutionError(str(e))


@mcp_tool
def nlm_notebook_rotate_impl(slot_name: str) -> Dict[str, Any]:
    """Rotate (delete & recreate) an NLM notebook to refresh stale content."""
    try:
        from engine.nexus.nlm_notebook_manager import get_notebook_manager

        return get_notebook_manager().rotate_notebook(slot_name)
    except Exception as e:
        raise ToolExecutionError(str(e))
