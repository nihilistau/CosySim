"""
CosySim System Monitor — process tracking, git operation monitoring,
and resource cross-referencing.

Usage::

    from engine.system import get_process_monitor
    mon = get_process_monitor()
    snap = mon.system_snapshot()       # Full system + process snapshot
    git_ops = mon.git_operations()     # Active git operations
    tree = mon.process_tree(1234)      # Process tree for PID
"""
from __future__ import annotations

from engine.system.process_monitor import (
    get_process_monitor,
    ProcessInfo,
    GitOperation,
    TrackedOperation,
    ProcessMonitor,
    ProcessCategory,
)

__all__ = [
    "get_process_monitor",
    "ProcessInfo",
    "GitOperation",
    "TrackedOperation",
    "ProcessMonitor",
    "ProcessCategory",
]
