"""PM2 process management skills for CosySim agents.

Provides 14 MCP skills for process lifecycle control, health monitoring,
metrics collection, log retrieval, state persistence, and ecosystem
analysis — all backed by the PM2Manager singleton.

Skills are auto-discovered by the skill registry. Every function returns
a JSON string with an ``ok`` field for uniform LLM consumption.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _mgr() -> Any:
    """Lazy-import the PM2Manager singleton.

    Returns:
        PM2Manager instance.
    """
    from engine.system.pm2_manager import get_pm2_manager
    return get_pm2_manager()


# ──── Process Lifecycle ────────────────────────────────────────────


@skill(pack="process",
       description="List all PM2 managed processes with status, CPU, memory, and PID",
       tags=["pm2", "process", "list"], category=SkillCategory.SYSTEM,
       cooldown=5.0, cost=1.0)
def process_list() -> str:
    """List every PM2 process with name, status, pid, cpu, and memory_mb."""
    try:
        procs = _mgr().list_processes()
        return json.dumps({"ok": True, "count": len(procs), "processes": procs},
                          indent=2, default=str)
    except Exception as e:
        logger.error("process_list failed: %s", e)
        return json.dumps({"ok": False, "error": str(e)})


@skill(pack="process",
       description="Start a PM2 process by name so it begins running",
       tags=["pm2", "process", "start"], category=SkillCategory.SYSTEM,
       cooldown=5.0, cost=1.0)
def process_start(name: str) -> str:
    """Start a specific PM2 managed process.

    Args:
        name: PM2 process name (e.g. ``cosysim-launcher``).
    """
    try:
        result = _mgr().start(name)
        return json.dumps({"ok": True, **result}, indent=2, default=str)
    except Exception as e:
        logger.error("process_start failed for '%s': %s", name, e)
        return json.dumps({"ok": False, "name": name, "error": str(e)})


@skill(pack="process",
       description="Stop a running PM2 process by name",
       tags=["pm2", "process", "stop"], category=SkillCategory.SYSTEM,
       cooldown=5.0, cost=1.0)
def process_stop(name: str) -> str:
    """Stop a running PM2 process.

    Args:
        name: PM2 process name.
    """
    try:
        result = _mgr().stop(name)
        return json.dumps({"ok": True, **result}, indent=2, default=str)
    except Exception as e:
        logger.error("process_stop failed for '%s': %s", name, e)
        return json.dumps({"ok": False, "name": name, "error": str(e)})


@skill(pack="process",
       description="Restart a PM2 process by name (full stop then start)",
       tags=["pm2", "process", "restart"], category=SkillCategory.SYSTEM,
       cooldown=5.0, cost=1.0)
def process_restart(name: str) -> str:
    """Restart a PM2 process with a full stop-then-start cycle.

    Args:
        name: PM2 process name.
    """
    try:
        result = _mgr().restart(name)
        return json.dumps({"ok": True, **result}, indent=2, default=str)
    except Exception as e:
        logger.error("process_restart failed for '%s': %s", name, e)
        return json.dumps({"ok": False, "name": name, "error": str(e)})


@skill(pack="process",
       description="Gracefully reload a PM2 process with zero downtime",
       tags=["pm2", "process", "reload", "zero-downtime"],
       category=SkillCategory.SYSTEM, cooldown=5.0, cost=1.0)
def process_reload(name: str) -> str:
    """Gracefully reload a process for zero-downtime restarts.

    Args:
        name: PM2 process name.
    """
    try:
        result = _mgr().reload(name)
        return json.dumps({"ok": True, **result}, indent=2, default=str)
    except Exception as e:
        logger.error("process_reload failed for '%s': %s", name, e)
        return json.dumps({"ok": False, "name": name, "error": str(e)})


# ──── Monitoring & Diagnostics ─────────────────────────────────────


@skill(pack="process",
       description="Generate a full PM2 health report with scores and recommendations",
       tags=["pm2", "health", "report", "diagnostics"],
       category=SkillCategory.SYSTEM, cooldown=10.0, cost=1.0)
def process_health_report() -> str:
    """Comprehensive health report covering all managed processes.

    Returns:
        JSON with healthy/unhealthy lists, health_score (0-1),
        summary string, and actionable recommendations.
    """
    try:
        report = _mgr().health_report()
        return json.dumps({"ok": True, **report}, indent=2, default=str)
    except Exception as e:
        logger.error("process_health_report failed: %s", e)
        return json.dumps({"ok": False, "error": str(e)})


@skill(pack="process",
       description="Get CPU and memory metrics for all PM2 processes",
       tags=["pm2", "metrics", "cpu", "memory"],
       category=SkillCategory.SYSTEM, cooldown=5.0, cost=1.0)
def process_metrics() -> str:
    """Retrieve CPU and memory usage for every managed process.

    Returns:
        JSON with per-process metrics, total_cpu, and total_memory_mb.
    """
    try:
        metrics = _mgr().metrics()
        return json.dumps({"ok": True, **metrics}, indent=2, default=str)
    except Exception as e:
        logger.error("process_metrics failed: %s", e)
        return json.dumps({"ok": False, "error": str(e)})


@skill(pack="process",
       description="Get recent log output for a specific PM2 process",
       tags=["pm2", "logs", "output", "debugging"],
       category=SkillCategory.SYSTEM, cooldown=5.0, cost=1.0)
def process_logs(name: str, lines: int = 50) -> str:
    """Retrieve recent stdout/stderr lines from a process.

    Args:
        name: PM2 process name.
        lines: Number of recent log lines to return.
    """
    try:
        output = _mgr().logs(name, lines=lines)
        return json.dumps({"ok": True, "name": name, "lines": lines,
                           "output": output}, indent=2, default=str)
    except Exception as e:
        logger.error("process_logs failed for '%s': %s", name, e)
        return json.dumps({"ok": False, "name": name, "error": str(e)})


@skill(pack="process",
       description="Quick boolean health check — is a specific PM2 process online?",
       tags=["pm2", "health", "check"], category=SkillCategory.SYSTEM,
       cooldown=3.0, cost=0.5)
def process_is_healthy(name: str) -> str:
    """Check whether a named process is online and healthy.

    Args:
        name: PM2 process name.

    Returns:
        JSON with ``healthy`` (bool) and ``details`` string.
    """
    try:
        healthy = _mgr().is_healthy(name)
        details = "online" if healthy else "not online or not found"
        return json.dumps({"ok": True, "name": name, "healthy": healthy,
                           "details": details}, indent=2, default=str)
    except Exception as e:
        logger.error("process_is_healthy failed for '%s': %s", name, e)
        return json.dumps({"ok": False, "name": name, "healthy": False,
                           "error": str(e)})


# ──── State Management ─────────────────────────────────────────────


@skill(pack="process",
       description="Save PM2 process list for persistence and auto-resurrection on reboot",
       tags=["pm2", "save", "persistence"], category=SkillCategory.SYSTEM,
       cooldown=10.0, cost=1.0)
def process_save_state() -> str:
    """Persist the current PM2 process list so it survives system reboots."""
    try:
        result = _mgr().save()
        return json.dumps({"ok": True, **result}, indent=2, default=str)
    except Exception as e:
        logger.error("process_save_state failed: %s", e)
        return json.dumps({"ok": False, "error": str(e)})


@skill(pack="process",
       description="Start all processes from ecosystem.config.js",
       tags=["pm2", "ecosystem", "start"], category=SkillCategory.SYSTEM,
       cooldown=10.0, cost=2.0)
def process_start_ecosystem() -> str:
    """Launch every process defined in the ecosystem configuration file."""
    try:
        result = _mgr().start_ecosystem()
        return json.dumps({"ok": True, **result}, indent=2, default=str)
    except Exception as e:
        logger.error("process_start_ecosystem failed: %s", e)
        return json.dumps({"ok": False, "error": str(e)})


@skill(pack="process",
       description="Stop all running PM2 processes at once",
       tags=["pm2", "stop", "all"], category=SkillCategory.SYSTEM,
       cooldown=10.0, cost=2.0)
def process_stop_all() -> str:
    """Stop every PM2 managed process."""
    try:
        result = _mgr().stop_all()
        return json.dumps({"ok": True, **result}, indent=2, default=str)
    except Exception as e:
        logger.error("process_stop_all failed: %s", e)
        return json.dumps({"ok": False, "error": str(e)})


# ──── Analysis ─────────────────────────────────────────────────────


@skill(pack="process",
       description="Compare running processes against ecosystem.config.js definition",
       tags=["pm2", "ecosystem", "diff", "audit"],
       category=SkillCategory.SYSTEM, cooldown=10.0, cost=1.0)
def process_ecosystem_diff() -> str:
    """Show which ecosystem-defined processes are missing or unexpected.

    Returns:
        JSON with defined, running, missing, and extra process name lists,
        plus an ``in_sync`` boolean.
    """
    try:
        diff = _mgr().ecosystem_diff()
        in_sync = not diff.get("missing") and not diff.get("extra")
        return json.dumps({"ok": True, "in_sync": in_sync, **diff},
                          indent=2, default=str)
    except Exception as e:
        logger.error("process_ecosystem_diff failed: %s", e)
        return json.dumps({"ok": False, "error": str(e)})


@skill(pack="process",
       description="Get recent process lifecycle events from PM2 event history",
       tags=["pm2", "events", "history", "audit"],
       category=SkillCategory.SYSTEM, cooldown=5.0, cost=1.0)
def process_event_history(name: str = "", limit: int = 20) -> str:
    """Retrieve recent PM2 lifecycle events (start, stop, restart, crash).

    Args:
        name: Filter to a specific process. Empty string returns all.
        limit: Maximum number of events to return.
    """
    try:
        events = _mgr().event_history(name=name, limit=limit)
        return json.dumps({"ok": True, "count": len(events),
                           "events": events}, indent=2, default=str)
    except Exception as e:
        logger.error("process_event_history failed: %s", e)
        return json.dumps({"ok": False, "error": str(e)})
