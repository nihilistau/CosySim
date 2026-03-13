"""
Process monitoring MCP skills for CosySim agents.

Provides real-time process tracking, git operation monitoring,
stall detection, and system resource snapshots — all accessible
to LLM agents via the MCP skill framework.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _monitor():
    from engine.system.process_monitor import get_process_monitor
    return get_process_monitor()


# ── Process Listing ──────────────────────────────────────────────────


@skill(
    pack="system",
    description=(
        "List system processes, optionally filtered by category "
        "(git, python, lmstudio, node, chrome, comfyui). "
        "Returns top N processes sorted by CPU time."
    ),
    tags=["system", "process", "monitoring"],
    category=SkillCategory.SYSTEM,
)
def process_list(category: str = "", top_n: int = 15, sort_by: str = "cpu_seconds") -> str:
    """List processes, optionally filtered by category.

    Args:
        category: Filter by category (git/python/lmstudio/node/chrome/comfyui).
                  Empty string returns all categories.
        top_n: Maximum number of processes to return.
        sort_by: Sort field — cpu_seconds, cpu_percent, memory_mb, memory_percent.
    """
    mon = _monitor()

    if category:
        from engine.system.process_monitor import ProcessCategory
        try:
            cat = ProcessCategory(category.lower())
        except ValueError:
            return json.dumps({
                "ok": False,
                "error": f"Unknown category '{category}'. "
                         f"Valid: git, python, lmstudio, node, chrome, comfyui, system, other",
            })
        procs = mon.scan_category(cat)
        key_map = {
            "cpu_seconds": lambda p: p.cpu_seconds,
            "cpu_percent": lambda p: p.cpu_percent,
            "memory_mb": lambda p: p.memory_mb,
            "memory_percent": lambda p: p.memory_percent,
        }
        procs.sort(key=key_map.get(sort_by, key_map["cpu_seconds"]), reverse=True)
        procs = procs[:top_n]
        return json.dumps({
            "ok": True,
            "category": category,
            "count": len(procs),
            "processes": [p.to_dict() for p in procs],
        })
    else:
        top = mon.top_consumers(top_n, sort_by=sort_by)
        return json.dumps({
            "ok": True,
            "count": len(top),
            "sort_by": sort_by,
            "processes": [p.to_dict() for p in top],
        })


# ── Git Operations ───────────────────────────────────────────────────


@skill(
    pack="system",
    description=(
        "Show all active git operations with phase detection "
        "(packing, uploading, receiving, etc.), PID trees, "
        "CPU/memory usage, and elapsed time."
    ),
    tags=["system", "git", "monitoring"],
    category=SkillCategory.SYSTEM,
)
def git_operation_status() -> str:
    """Detect and report all active git operations with detailed status."""
    mon = _monitor()
    ops = mon.git_operations()

    if not ops:
        return json.dumps({
            "ok": True,
            "count": 0,
            "operations": [],
            "message": "No active git operations detected.",
        })

    return json.dumps({
        "ok": True,
        "count": len(ops),
        "operations": [op.to_dict() for op in ops],
    })


# ── Process Tree ─────────────────────────────────────────────────────


@skill(
    pack="system",
    description=(
        "Show the process tree for a specific PID — parent, children, "
        "and their resource usage. Cross-references with tracked operations."
    ),
    tags=["system", "process", "tree"],
    category=SkillCategory.SYSTEM,
)
def process_tree(pid: int) -> str:
    """Build and return the process tree rooted at the given PID.

    Args:
        pid: The process ID to inspect.
    """
    mon = _monitor()
    tree = mon.process_tree(pid)
    return json.dumps({"ok": True, "tree": tree}, default=str)


# ── Full System Snapshot ─────────────────────────────────────────────


@skill(
    pack="system",
    description=(
        "Full system resource snapshot: CPU, RAM, GPU, disk, plus "
        "categorized processes, git operations, tracked operations, "
        "and top consumers. The comprehensive system health view."
    ),
    tags=["system", "snapshot", "health", "monitoring"],
    category=SkillCategory.SYSTEM,
)
def system_resource_snapshot() -> str:
    """Return a comprehensive system snapshot with all process and resource data."""
    mon = _monitor()
    snap = mon.system_snapshot()
    return json.dumps({"ok": True, "snapshot": snap}, default=str)


# ── Operation Tracking ───────────────────────────────────────────────


@skill(
    pack="system",
    description=(
        "Track a named operation by PID for cross-referencing. "
        "Example: track_operation('git-push', 53472, metadata='{\"commits\": 388}'). "
        "Tracked operations appear in snapshots and git operation reports."
    ),
    tags=["system", "tracking", "monitoring"],
    category=SkillCategory.SYSTEM,
)
def track_operation(
    name: str,
    pid: int,
    category: str = "user",
    metadata: str = "{}",
) -> str:
    """Register a named operation for cross-referencing.

    Args:
        name: Human-readable operation name.
        pid: Root PID of the operation.
        category: Classification (git, build, test, user).
        metadata: JSON string with extra context (e.g. '{"commits": 388}').
    """
    mon = _monitor()
    try:
        meta = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError:
        meta = {"raw": metadata}

    op = mon.track_operation(name, pid, category=category, metadata=meta)
    return json.dumps({"ok": True, "operation": op.to_dict()})


@skill(
    pack="system",
    description="Stop tracking a named operation.",
    tags=["system", "tracking"],
    category=SkillCategory.SYSTEM,
)
def untrack_operation(name: str) -> str:
    """Remove a tracked operation by name.

    Args:
        name: The operation name to stop tracking.
    """
    mon = _monitor()
    op = mon.untrack_operation(name)
    if op:
        return json.dumps({"ok": True, "operation": op.to_dict()})
    return json.dumps({"ok": False, "error": f"Operation '{name}' not found"})


@skill(
    pack="system",
    description="List all currently tracked operations.",
    tags=["system", "tracking", "monitoring"],
    category=SkillCategory.SYSTEM,
)
def list_tracked_operations() -> str:
    """Return all currently tracked operations with their status."""
    mon = _monitor()
    tracked = mon.tracked_operations()
    return json.dumps({
        "ok": True,
        "count": len(tracked),
        "operations": [op.to_dict() for op in tracked],
    })


# ── Stall Detection ─────────────────────────────────────────────────


@skill(
    pack="system",
    description=(
        "Check if processes are stalled by measuring CPU time delta "
        "over a short interval. Reports verdict: active, slow, stalled, or exited. "
        "If no PIDs specified, checks all tracked operations."
    ),
    tags=["system", "stall", "monitoring", "diagnostic"],
    category=SkillCategory.SYSTEM,
)
def stall_check(pids: str = "", check_interval: float = 3.0) -> str:
    """Check processes for stalls.

    Args:
        pids: Comma-separated PIDs to check. Empty = check tracked operations.
        check_interval: Seconds between measurements (default 3.0).
    """
    mon = _monitor()

    pid_list = None
    if pids:
        try:
            pid_list = [int(p.strip()) for p in pids.split(",") if p.strip()]
        except ValueError:
            return json.dumps({"ok": False, "error": f"Invalid PID list: {pids}"})

    stalls = mon.stall_detection(pids=pid_list, check_interval=check_interval)
    return json.dumps({
        "ok": True,
        "count": len(stalls),
        "check_interval_s": check_interval,
        "results": [s.to_dict() for s in stalls],
    })


# ── LMStudio & Python Processes ──────────────────────────────────────


@skill(
    pack="system",
    description="Show all LMStudio-related processes with resource usage.",
    tags=["system", "lmstudio", "monitoring"],
    category=SkillCategory.SYSTEM,
)
def lmstudio_processes() -> str:
    """List all LMStudio processes."""
    mon = _monitor()
    procs = mon.lmstudio_processes()
    return json.dumps({
        "ok": True,
        "count": len(procs),
        "processes": [p.to_dict() for p in procs],
    })


@skill(
    pack="system",
    description="Show all Python worker processes (excluding current process).",
    tags=["system", "python", "monitoring"],
    category=SkillCategory.SYSTEM,
)
def python_workers() -> str:
    """List all Python worker processes."""
    mon = _monitor()
    procs = mon.python_workers()
    return json.dumps({
        "ok": True,
        "count": len(procs),
        "processes": [p.to_dict() for p in procs],
    })
