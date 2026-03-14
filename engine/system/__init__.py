"""
CosySim System Monitor — process tracking, git operation monitoring,
PM2 process management, and resource cross-referencing.

Usage::

    from engine.system import get_process_monitor
    mon = get_process_monitor()
    snap = mon.system_snapshot()       # Full system + process snapshot
    git_ops = mon.git_operations()     # Active git operations
    tree = mon.process_tree(1234)      # Process tree for PID

    from engine.system import get_pm2_manager
    mgr = get_pm2_manager()
    procs = mgr.list_processes()       # All PM2 processes
    report = mgr.health_report()       # Health report with scoring
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

from engine.system.pm2_manager import (
    get_pm2_manager,
    PM2Manager,
    PM2Error,
)

__all__ = [
    "get_process_monitor",
    "ProcessInfo",
    "GitOperation",
    "TrackedOperation",
    "ProcessMonitor",
    "ProcessCategory",
    "get_pm2_manager",
    "PM2Manager",
    "PM2Error",
]
