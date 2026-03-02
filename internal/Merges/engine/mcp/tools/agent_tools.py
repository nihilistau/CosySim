from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from engine.mcp.decorators import mcp_tool, ToolExecutionError

@mcp_tool
def agent_create_task_impl(title: str, description: str = '', agent: str = 'copilot', priority: str = 'normal', tags: str = '') -> Any:
    """Create a tracked agent task in Nexus. Returns task ID."""
    from engine.nexus.agent_tags import get_task_manager
    mgr = get_task_manager()
    tag_list = [t.strip() for t in tags.split(',') if t.strip()] if tags else []
    task_id = mgr.create_task(title, description, agent, priority, tag_list)
    return {'task_id': task_id, 'status': 'created'}


@mcp_tool
def agent_update_task_impl(task_id: str, status: str) -> Any:
    """Update an agent task status (pending/in_progress/done/blocked/cancelled)."""
    from engine.nexus.agent_tags import get_task_manager
    ok = get_task_manager().update_status(task_id, status)
    return {'updated': ok}


@mcp_tool
def agent_complete_task_impl(task_id: str, summary: str = '') -> Any:
    """Mark an agent task as done with an optional completion summary."""
    from engine.nexus.agent_tags import get_task_manager
    ok = get_task_manager().complete_task(task_id, summary)
    return {'completed': ok}


@mcp_tool
def agent_list_tasks_impl(status: str = '', agent: str = '', limit: int = 20) -> Any:
    """List agent tasks, optionally filtered by status and agent."""
    from engine.nexus.agent_tags import get_task_manager
    tasks = get_task_manager().list_tasks(status=status or None, agent=agent or None, limit=limit)
    return [t.to_dict( for t in tasks], indent=2)
