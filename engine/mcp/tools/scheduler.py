"""MCP tool domain: scheduler.

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

# ──── SCHEDULER TOOLS ────────────────────────────────────────────────────


@mcp_tool
def agent_create_task(title: str, description: str = "", agent: str = "copilot",
                      priority: str = "normal", tags: str = "") -> str:
    """Create a tracked agent task in Nexus. Returns task ID."""
    try:
        from engine.nexus.agent_tags import get_task_manager
        mgr = get_task_manager()
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        task_id = mgr.create_task(title, description, agent, priority, tag_list)
        return json.dumps({"task_id": task_id, "status": "created"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def agent_update_task(task_id: str, status: str) -> str:
    """Update an agent task status (pending/in_progress/done/blocked/cancelled)."""
    try:
        from engine.nexus.agent_tags import get_task_manager
        ok = get_task_manager().update_status(task_id, status)
        return json.dumps({"updated": ok})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def agent_complete_task(task_id: str, summary: str = "") -> str:
    """Mark an agent task as done with an optional completion summary."""
    try:
        from engine.nexus.agent_tags import get_task_manager
        ok = get_task_manager().complete_task(task_id, summary)
        return json.dumps({"completed": ok})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def agent_list_tasks(status: str = "", agent: str = "", limit: int = 20) -> str:
    """List agent tasks, optionally filtered by status and agent."""
    try:
        from engine.nexus.agent_tags import get_task_manager
        tasks = get_task_manager().list_tasks(
            status=status or None, agent=agent or None, limit=limit)
        return json.dumps([t.to_dict() for t in tasks], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def scheduler_status() -> str:
    """Get status of all scheduled autonomous tasks — running state,
    next-due times, run/error counts, and last results."""
    try:
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        return json.dumps(get_scheduler_daemon().status(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def scheduler_run_now(task_id: str) -> str:
    """Run a scheduled task immediately by ID. Returns success/failure
    with duration and result details."""
    try:
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        return json.dumps(get_scheduler_daemon().run_task(task_id), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def task_auto_generate(source: str = "quality") -> str:
    """Auto-generate tasks from system events. source: 'quality' (from stale
    Nexus entries), 'tests' (run and parse test failures). Returns created tasks."""
    try:
        from engine.nexus.task_scheduler import get_task_scheduler
        scheduler = get_task_scheduler()
        tasks = []
        if source == "quality":
            from engine.nexus.self_maintenance import quality_report
            report = quality_report()
            stale = [{"id": s.get("entry_id", ""), "title": s.get("title", "")}
                     for s in report.get("stale", [])[:5]]
            tasks = scheduler.generate_from_stale_knowledge(stale)
        elif source == "tests":
            import subprocess, sys
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "--tb=line", "-q",
                 "--ignore=tests/test_agent_loop.py", "--ignore=tests/live_wire_test.py"],
                capture_output=True, text=True, timeout=600
            )
            tasks = scheduler.generate_from_test_failures(result.stdout + result.stderr)
        return json.dumps(
            {"source": source, "tasks_created": len(tasks),
             "tasks": [{"id": t.id, "title": t.title} for t in tasks]},
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def task_from_template(template_name: str, title: str = "",
                       description: str = "", target_files: str = "") -> str:
    """Create a task from a template: bug-fix, feature, refactor, test,
    doc-update, skill-add, scene-polish, knowledge-refresh.
    target_files is comma-separated."""
    try:
        from engine.nexus.task_scheduler import get_task_scheduler
        files = [f.strip() for f in target_files.split(",") if f.strip()] if target_files else []
        task = get_task_scheduler().from_template(
            template_name, title=title, description=description, target_files=files
        )
        return json.dumps({"id": task.id, "title": task.title, "template": template_name})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def task_list_templates() -> str:
    """List all available task templates with priorities and descriptions."""
    try:
        from engine.nexus.task_scheduler import get_task_scheduler
        return json.dumps(get_task_scheduler().list_templates(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
async def local_agent_get_tasks(model_size: str = "worker", limit: int = 10,
                                 tags: str = "") -> str:
    """Get pending tasks for a local agent by model size.

    model_size: 'router', 'mini', 'worker', or 'expert'.
    tags: optional comma-separated tag filter.
    Returns JSON list of task dicts sorted by priority.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    tasks = get_local_agent_bridge().get_ready_tasks(model_size=model_size, limit=limit,
                                                      tags=tag_list)
    return json.dumps({"tasks": tasks, "count": len(tasks)})


@mcp_tool
async def local_agent_claim_task(task_id: str, agent_id: str) -> str:
    """Claim a task for execution by this agent.

    task_id: ID of the task to claim.
    agent_id: Unique identifier for this agent (e.g. 'worker-qwen-7b-1').
    Returns claimed task dict or error.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    result = get_local_agent_bridge().claim_task(task_id=task_id, agent_id=agent_id)
    return json.dumps(result, default=str)


@mcp_tool
async def local_agent_task_context(task_id: str) -> str:
    """Get full execution context for a claimed task.

    Includes: task metadata, relevant Nexus knowledge, coding rules, and
    step-by-step execution guide. Inject this into the agent's system prompt.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    ctx = get_local_agent_bridge().get_task_context(task_id=task_id)
    return json.dumps(ctx)


@mcp_tool
async def local_agent_complete_task(task_id: str, result: str,
                                     files_changed: str = "") -> str:
    """Mark a task as completed and store the result in Nexus.

    task_id: ID of the completed task.
    result: 1-2 sentence summary of what was accomplished.
    files_changed: optional comma-separated list of files modified.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    file_list = [f.strip() for f in files_changed.split(",") if f.strip()] if files_changed else []
    out = get_local_agent_bridge().complete_task(task_id=task_id, result=result,
                                                  files_changed=file_list)
    return json.dumps(out)


@mcp_tool
async def local_agent_fail_task(task_id: str, reason: str, retry: bool = False) -> str:
    """Mark a task as failed.

    task_id: ID of the failed task.
    reason: Explanation of why it failed.
    retry: If True, reset to 'pending' so another agent can pick it up.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    out = get_local_agent_bridge().fail_task(task_id=task_id, reason=reason, retry=retry)
    return json.dumps(out)


@mcp_tool
async def local_agent_manifest(model_size: str = "worker") -> str:
    """Get the system prompt manifest for a local agent of the specified size.

    Returns a formatted string ready to inject into an LLM system prompt.
    model_size: 'router', 'mini', 'worker', or 'expert'.
    """
    from engine.nexus.local_agent_bridge import get_local_agent_bridge
    return get_local_agent_bridge().get_agent_manifest(model_size=model_size)
