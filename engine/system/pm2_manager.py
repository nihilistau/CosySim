"""
CosySim PM2 Process Manager — wraps the PM2 CLI to manage CosySim services,
track lifecycle events in SQLite, generate health reports, detect ecosystem
drift, and cross-reference with the OS-level ProcessMonitor.

Usage::

    from engine.system.pm2_manager import get_pm2_manager

    mgr = get_pm2_manager()

    # Lifecycle
    mgr.start("cosysim-launcher")
    mgr.restart("cosysim-scheduler")
    mgr.stop("cosysim-tts")
    mgr.reload("cosysim-launcher")
    mgr.delete("cosysim-old-service")

    # Inspection
    procs = mgr.list_processes()
    info  = mgr.describe("cosysim-launcher")
    log   = mgr.logs("cosysim-launcher", lines=100, err=True)
    m     = mgr.metrics()

    # Ecosystem
    mgr.start_ecosystem()
    mgr.stop_all()
    mgr.restart_all()
    mgr.delete_all()

    # Persistence
    mgr.save()
    mgr.resurrect()

    # Health & monitoring
    report = mgr.health_report()
    ok     = mgr.is_healthy("cosysim-launcher")
    diff   = mgr.ecosystem_diff()
    xref   = mgr.cross_reference()

    # Event tracking
    mgr.record_event("cosysim-launcher", "crash", "OOM killed")
    events = mgr.event_history("cosysim-launcher", limit=20)

    # Modules
    mgr.install_module("pm2-logrotate")
    mods = mgr.list_modules()

CLI::

    python -m engine.system.pm2_manager --list
    python -m engine.system.pm2_manager --health
    python -m engine.system.pm2_manager --diff
    python -m engine.system.pm2_manager --metrics
    python -m engine.system.pm2_manager --xref
    python -m engine.system.pm2_manager --history [name]
    python -m engine.system.pm2_manager --describe <name>
    python -m engine.system.pm2_manager --start <name>
    python -m engine.system.pm2_manager --stop <name>
    python -m engine.system.pm2_manager --restart <name>
    python -m engine.system.pm2_manager --modules
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──── Constants ──────────────────────────────────────────────────────────

PM2_BINARY = "pm2"
DEFAULT_ECOSYSTEM = "ecosystem.config.js"
HISTORY_DB_PATH = "data/pm2_history.db"
PM2_COMMAND_TIMEOUT = 30
PM2_RESTART_DELAY = 2.0
PROCESS_NAME_PREFIX = "cosysim-"

_HIGH_RESTART_THRESHOLD = 10
_HIGH_MEMORY_MB = 1024
_ZERO_CPU_STALL_SECONDS = 600  # 10 minutes

_PROJECT_ROOT = str(pathlib.Path(__file__).resolve().parents[2])


# ──── Exceptions ─────────────────────────────────────────────────────────


class PM2Error(Exception):
    """Error from PM2 command execution.

    Attributes:
        returncode: Exit code from the PM2 process.
        stderr: Captured stderr text.
    """

    def __init__(self, message: str, returncode: int = -1, stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


# ──── Singleton ──────────────────────────────────────────────────────────

_manager_lock = threading.Lock()
_manager_instance: Optional[PM2Manager] = None


def get_pm2_manager() -> PM2Manager:
    """Return the singleton PM2Manager instance (thread-safe, double-checked).

    Returns:
        The global PM2Manager instance.
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = PM2Manager()
    return _manager_instance


# ──── PM2Manager ─────────────────────────────────────────────────────────


class PM2Manager:
    """Manages CosySim services via PM2 process manager.

    Wraps the PM2 CLI, tracks lifecycle events in a SQLite database, and
    integrates with the Nexus knowledge base for significant events.
    """

    def __init__(self) -> None:
        self._project_root: str = _PROJECT_ROOT
        self._db_path: str = os.path.join(self._project_root, HISTORY_DB_PATH)
        self._local = threading.local()
        self._table_lock = threading.Lock()
        self._tables_created = False
        self._ensure_db_directory()
        self._ensure_tables()
        logger.info(
            "PM2Manager initialized — project_root=%s  db=%s",
            self._project_root,
            self._db_path,
        )

    # ──── Core Lifecycle ─────────────────────────────────────────────

    def start(self, name: str, ecosystem: bool = False) -> Dict[str, Any]:
        """Start a PM2 process by name or start the ecosystem.

        Args:
            name: Process name (auto-prefixed with ``cosysim-`` if needed).
            ecosystem: If True, start via the ecosystem config file instead.

        Returns:
            Parsed PM2 response dict.

        Raises:
            PM2Error: If the PM2 command fails.
        """
        if ecosystem:
            return self.start_ecosystem()

        name = self._normalise_name(name)
        logger.info("Starting PM2 process: %s", name)
        result = self._run_pm2("start", name, parse_json=False)
        self.record_event(name, "start", "Process started")
        return {"action": "start", "process": name, "success": True, "raw": result}

    def stop(self, name: str) -> Dict[str, Any]:
        """Stop a PM2 process by name.

        Args:
            name: Process name.

        Returns:
            Parsed PM2 response dict.

        Raises:
            PM2Error: If the PM2 command fails.
        """
        name = self._normalise_name(name)
        logger.info("Stopping PM2 process: %s", name)
        result = self._run_pm2("stop", name, parse_json=False)
        self.record_event(name, "stop", "Process stopped")
        return {"action": "stop", "process": name, "success": True, "raw": result}

    def restart(self, name: str) -> Dict[str, Any]:
        """Restart a PM2 process by name.

        Args:
            name: Process name.

        Returns:
            Parsed PM2 response dict.

        Raises:
            PM2Error: If the PM2 command fails.
        """
        name = self._normalise_name(name)
        logger.info("Restarting PM2 process: %s", name)
        result = self._run_pm2("restart", name, parse_json=False)
        self.record_event(name, "restart", "Process restarted")
        return {"action": "restart", "process": name, "success": True, "raw": result}

    def delete(self, name: str) -> Dict[str, Any]:
        """Delete a PM2 process from the process list.

        Args:
            name: Process name.

        Returns:
            Parsed PM2 response dict.

        Raises:
            PM2Error: If the PM2 command fails.
        """
        name = self._normalise_name(name)
        logger.info("Deleting PM2 process: %s", name)
        result = self._run_pm2("delete", name, parse_json=False)
        self.record_event(name, "delete", "Process deleted from PM2")
        return {"action": "delete", "process": name, "success": True, "raw": result}

    def reload(self, name: str) -> Dict[str, Any]:
        """Graceful reload (0-downtime restart) for a PM2 process.

        Args:
            name: Process name.

        Returns:
            Parsed PM2 response dict.

        Raises:
            PM2Error: If the PM2 command fails.
        """
        name = self._normalise_name(name)
        logger.info("Reloading PM2 process (graceful): %s", name)
        result = self._run_pm2("reload", name, parse_json=False)
        self.record_event(name, "reload", "Graceful reload triggered")
        return {"action": "reload", "process": name, "success": True, "raw": result}

    # ──── Inspection ─────────────────────────────────────────────────

    def list_processes(self) -> List[Dict[str, Any]]:
        """List all PM2 processes with status and metrics.

        Returns:
            List of normalised process-info dicts.

        Raises:
            PM2Error: If the PM2 command fails or output cannot be parsed.
        """
        raw = self._run_pm2("jlist", parse_json=True)
        if not isinstance(raw, list):
            logger.warning("PM2 jlist returned non-list type: %s", type(raw).__name__)
            return []
        processes: List[Dict[str, Any]] = []
        for entry in raw:
            try:
                parsed = self._parse_process_info(entry)
                # Filter out PM2 internal modules from the main listing
                pm2_env = entry.get("pm2_env", {})
                if pm2_env.get("pmx_module") or pm2_env.get("pm2_module"):
                    continue
                processes.append(parsed)
            except Exception:
                logger.debug(
                    "Skipping unparseable PM2 entry: %s", entry, exc_info=True
                )
        return processes

    def describe(self, name: str) -> Dict[str, Any]:
        """Get detailed info about a specific PM2 process.

        Args:
            name: Process name.

        Returns:
            Normalised detail dict for the process.

        Raises:
            PM2Error: If the process is not found or the command fails.
        """
        name = self._normalise_name(name)
        raw = self._run_pm2("describe", name, "--json", parse_json=True)
        if isinstance(raw, list) and raw:
            return self._parse_process_info(raw[0])
        if isinstance(raw, dict):
            return self._parse_process_info(raw)
        raise PM2Error(f"Process '{name}' not found or returned empty description")

    def logs(self, name: str, lines: int = 50, err: bool = False) -> str:
        """Get recent log output for a process.

        Args:
            name: Process name.
            lines: Number of trailing lines to return.
            err: If True, return only stderr (error) logs.

        Returns:
            Log text as a string.
        """
        name = self._normalise_name(name)
        args = ["logs", name, "--lines", str(lines), "--nostream"]
        if err:
            args.append("--err")
        result = self._run_pm2(*args, parse_json=False)
        return str(result)

    def metrics(self) -> Dict[str, Any]:
        """Get CPU/memory metrics for all PM2 processes.

        Returns:
            Dict mapping process names to their cpu/memory/uptime metrics,
            plus aggregate totals.
        """
        processes = self.list_processes()
        per_process: Dict[str, Any] = {}
        total_cpu = 0.0
        total_mem = 0.0
        for proc in processes:
            name = proc.get("name", "unknown")
            cpu = proc.get("cpu", 0.0)
            mem = proc.get("memory_mb", 0.0)
            total_cpu += cpu
            total_mem += mem
            per_process[name] = {
                "cpu": cpu,
                "memory_mb": mem,
                "uptime_seconds": proc.get("uptime_seconds", 0),
                "restarts": proc.get("restarts", 0),
                "status": proc.get("status", "unknown"),
            }
        return {
            "processes": per_process,
            "total_cpu": round(total_cpu, 2),
            "total_memory_mb": round(total_mem, 2),
            "process_count": len(processes),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ──── Ecosystem Management ───────────────────────────────────────

    def start_ecosystem(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Start all processes defined in ecosystem.config.js.

        Args:
            config_path: Override path to the ecosystem file.  Defaults to
                ``ecosystem.config.js`` in the project root.

        Returns:
            Parsed PM2 response dict.

        Raises:
            PM2Error: If the config is missing or the command fails.
        """
        path = config_path or self._ecosystem_config_path()
        if not os.path.isfile(path):
            raise PM2Error(f"Ecosystem config not found: {path}")
        logger.info("Starting PM2 ecosystem from: %s", path)
        result = self._run_pm2("start", path, parse_json=False)
        self.record_event("ecosystem", "start", f"Ecosystem started from {path}")
        return {
            "action": "start_ecosystem",
            "config": path,
            "success": True,
            "raw": result,
        }

    def stop_all(self) -> Dict[str, Any]:
        """Stop all PM2 processes.

        Returns:
            Parsed PM2 response dict.
        """
        logger.info("Stopping all PM2 processes")
        result = self._run_pm2("stop", "all", parse_json=False)
        self.record_event("all", "stop", "All processes stopped")
        return {"action": "stop_all", "success": True, "raw": result}

    def restart_all(self) -> Dict[str, Any]:
        """Restart all PM2 processes.

        Returns:
            Parsed PM2 response dict.
        """
        logger.info("Restarting all PM2 processes")
        result = self._run_pm2("restart", "all", parse_json=False)
        self.record_event("all", "restart", "All processes restarted")
        return {"action": "restart_all", "success": True, "raw": result}

    def delete_all(self) -> Dict[str, Any]:
        """Delete all PM2 processes from PM2's process list.

        Returns:
            Parsed PM2 response dict.
        """
        logger.warning("Deleting ALL PM2 processes")
        result = self._run_pm2("delete", "all", parse_json=False)
        self.record_event("all", "delete", "All processes deleted")
        return {"action": "delete_all", "success": True, "raw": result}

    # ──── Persistence ────────────────────────────────────────────────

    def save(self) -> Dict[str, Any]:
        """Save current PM2 process list for resurrection.

        Returns:
            Result dict with success status.
        """
        logger.info("Saving PM2 process list (pm2 save)")
        result = self._run_pm2("save", parse_json=False)
        self.record_event("pm2", "save", "Process list saved for resurrection")
        return {"action": "save", "success": True, "raw": result}

    def resurrect(self) -> Dict[str, Any]:
        """Restore previously saved PM2 process list.

        Returns:
            Result dict with success status.
        """
        logger.info("Resurrecting PM2 process list")
        result = self._run_pm2("resurrect", parse_json=False)
        self.record_event("pm2", "resurrect", "Process list resurrected")
        return {"action": "resurrect", "success": True, "raw": result}

    # ──── Health and Monitoring ──────────────────────────────────────

    def health_report(self) -> Dict[str, Any]:
        """Generate comprehensive health report for all managed processes.

        Returns:
            Dict with keys: healthy, unhealthy, stopped, summary,
            total, online, errored, stopped_count, uptime_stats,
            memory_total_mb, cpu_total, health_score, recommendations,
            timestamp.
        """
        try:
            processes = self.list_processes()
        except PM2Error as exc:
            logger.error("Cannot generate health report — PM2 unreachable: %s", exc)
            return {
                "healthy": [],
                "unhealthy": [],
                "stopped": [],
                "summary": "PM2 unreachable",
                "total": 0,
                "online": 0,
                "errored": 0,
                "stopped_count": 0,
                "uptime_stats": {},
                "memory_total_mb": 0.0,
                "cpu_total": 0.0,
                "health_score": 0.0,
                "recommendations": [
                    "PM2 daemon appears to be down — run 'pm2 ping' to verify"
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        healthy: List[str] = []
        unhealthy: List[str] = []
        stopped_list: List[str] = []
        recommendations: List[str] = []

        online_count = 0
        errored_count = 0
        stopped_count = 0
        total_memory = 0.0
        total_cpu = 0.0
        uptimes: List[float] = []

        for proc in processes:
            name = proc.get("name", "unknown")
            status = proc.get("status", "unknown")
            cpu = proc.get("cpu", 0.0)
            mem = proc.get("memory_mb", 0.0)
            restarts = proc.get("restarts", 0)
            uptime = proc.get("uptime_seconds", 0.0)

            total_memory += mem
            total_cpu += cpu

            if status == "online":
                online_count += 1
                uptimes.append(uptime)

                issues: List[str] = []
                if restarts > _HIGH_RESTART_THRESHOLD:
                    issues.append(f"high restart count ({restarts})")
                    recommendations.append(
                        f"'{name}' has restarted {restarts} times — check logs "
                        f"with 'pm2 logs {name} --err --lines 100'"
                    )
                if mem > _HIGH_MEMORY_MB:
                    issues.append(f"high memory ({mem:.0f} MB)")
                    recommendations.append(
                        f"'{name}' using {mem:.0f} MB — possible memory leak, "
                        f"consider restart"
                    )
                if cpu == 0.0 and uptime > _ZERO_CPU_STALL_SECONDS:
                    issues.append("zero CPU for >10 min (possible stall)")
                    recommendations.append(
                        f"'{name}' shows 0% CPU for "
                        f">{_ZERO_CPU_STALL_SECONDS // 60} min — may be stalled"
                    )

                if issues:
                    unhealthy.append(name)
                else:
                    healthy.append(name)

            elif status == "errored":
                errored_count += 1
                unhealthy.append(name)
                recommendations.append(
                    f"'{name}' is in errored state — check logs and restart"
                )
            elif status == "stopped":
                stopped_count += 1
                stopped_list.append(name)
            else:
                unhealthy.append(name)
                recommendations.append(
                    f"'{name}' has unexpected status '{status}'"
                )

        total = len(processes)
        if total == 0:
            health_score = 1.0
            summary = "No PM2 processes registered"
        else:
            health_score = round(len(healthy) / total, 3)
            if health_score >= 0.9:
                summary = "healthy"
            elif health_score >= 0.7:
                summary = "degraded"
            elif health_score >= 0.4:
                summary = "unhealthy"
            else:
                summary = "critical"

        uptime_stats: Dict[str, float] = {}
        if uptimes:
            uptime_stats = {
                "min": round(min(uptimes), 1),
                "max": round(max(uptimes), 1),
                "avg": round(sum(uptimes) / len(uptimes), 1),
            }

        report: Dict[str, Any] = {
            "healthy": healthy,
            "unhealthy": unhealthy,
            "stopped": stopped_list,
            "summary": summary,
            "total": total,
            "online": online_count,
            "errored": errored_count,
            "stopped_count": stopped_count,
            "uptime_stats": uptime_stats,
            "memory_total_mb": round(total_memory, 2),
            "cpu_total": round(total_cpu, 2),
            "health_score": health_score,
            "recommendations": recommendations,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            self._record_health_snapshot(report)
        except Exception:
            logger.debug("Failed to record health snapshot", exc_info=True)

        return report

    def is_healthy(self, name: str) -> bool:
        """Check if a specific process is healthy.

        A process is considered healthy if it is online with reasonable CPU
        and memory metrics and a low restart count.

        Args:
            name: Process name.

        Returns:
            True if the process is online and has no concerning metrics.
        """
        name = self._normalise_name(name)
        try:
            info = self.describe(name)
        except PM2Error:
            return False

        if info.get("status") != "online":
            return False
        if info.get("restarts", 0) > _HIGH_RESTART_THRESHOLD:
            return False
        if info.get("memory_mb", 0) > _HIGH_MEMORY_MB:
            return False
        return True

    def ecosystem_diff(self) -> Dict[str, Any]:
        """Compare running processes against ecosystem.config.js definitions.

        Returns:
            Dict with keys: defined, running, missing, extra, drift,
            timestamp.
        """
        defined_names = self._read_ecosystem_names()
        running_procs = self.list_processes()
        running_names = {p["name"] for p in running_procs}
        running_details = {p["name"]: p for p in running_procs}

        missing = sorted(set(defined_names) - running_names)
        extra = sorted(running_names - set(defined_names))

        drift: List[Dict[str, Any]] = []
        for name in sorted(set(defined_names) & running_names):
            info = running_details.get(name, {})
            status = info.get("status", "unknown")
            if status in ("errored", "stopping"):
                drift.append({
                    "name": name,
                    "expected_status": "online",
                    "actual_status": status,
                    "restarts": info.get("restarts", 0),
                })

        result: Dict[str, Any] = {
            "defined": sorted(defined_names),
            "running": sorted(running_names),
            "missing": missing,
            "extra": extra,
            "drift": drift,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if missing:
            logger.warning("Ecosystem drift — missing processes: %s", missing)
        if extra:
            logger.info("Extra processes not in ecosystem config: %s", extra)
        if drift:
            logger.warning(
                "Drifted processes: %s", [d["name"] for d in drift]
            )

        return result

    # ──── Cross-Reference with ProcessMonitor ────────────────────────

    def cross_reference(self) -> Dict[str, Any]:
        """Cross-reference PM2 processes with OS-level process data.

        Lazy-imports ``engine.system.process_monitor`` to correlate PM2
        PIDs with live OS processes, detecting orphans and PID mismatches.

        Returns:
            Dict with matched, orphaned, mismatched, and untracked entries.
        """
        pm2_procs = self.list_processes()
        pm2_pids: Dict[int, str] = {}
        for proc in pm2_procs:
            pid = proc.get("pid", 0)
            if pid and pid > 0:
                pm2_pids[pid] = proc.get("name", "unknown")

        try:
            from engine.system.process_monitor import get_process_monitor

            monitor = get_process_monitor()
            snapshot = monitor.system_snapshot()
        except Exception:
            logger.warning(
                "ProcessMonitor unavailable — cross-reference skipped",
                exc_info=True,
            )
            return {
                "matched": [],
                "orphaned": [],
                "mismatched": [],
                "untracked": [],
                "error": "ProcessMonitor unavailable",
            }

        os_pids: Dict[int, Dict[str, Any]] = {}
        for category_procs in snapshot.get("processes", {}).values():
            if isinstance(category_procs, list):
                for p in category_procs:
                    if isinstance(p, dict):
                        pid = p.get("pid")
                        if pid:
                            os_pids[pid] = p
                    else:
                        pid = getattr(p, "pid", None)
                        if pid:
                            os_pids[pid] = {
                                "pid": pid,
                                "name": getattr(p, "name", "unknown"),
                                "cmdline": getattr(p, "cmdline", []),
                            }

        matched: List[Dict[str, Any]] = []
        orphaned: List[Dict[str, Any]] = []

        for pid, pm2_name in pm2_pids.items():
            if pid in os_pids:
                matched.append({
                    "pm2_name": pm2_name,
                    "pid": pid,
                    "os_name": os_pids[pid].get("name", "unknown"),
                })
            else:
                orphaned.append({
                    "pm2_name": pm2_name,
                    "pid": pid,
                    "note": (
                        "PM2 reports PID but OS does not — "
                        "possible zombie reference"
                    ),
                })

        untracked: List[Dict[str, Any]] = []
        for pid, os_info in os_pids.items():
            os_name = os_info.get("name", "")
            cmdline = os_info.get("cmdline", [])
            cmdline_str = (
                " ".join(cmdline) if isinstance(cmdline, list) else str(cmdline)
            )
            if (
                "cosysim" in cmdline_str.lower()
                or "launcher.py" in cmdline_str.lower()
            ):
                if pid not in pm2_pids:
                    untracked.append({
                        "pid": pid,
                        "os_name": os_name,
                        "cmdline": cmdline_str[:200],
                        "note": "CosySim-related process not managed by PM2",
                    })

        return {
            "matched": matched,
            "orphaned": orphaned,
            "mismatched": [],
            "untracked": untracked,
            "pm2_count": len(pm2_pids),
            "os_cosysim_count": len(untracked) + len(matched),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ──── Event Tracking ─────────────────────────────────────────────

    def record_event(
        self,
        process_name: str,
        event_type: str,
        details: str = "",
        pid: Optional[int] = None,
        memory_mb: Optional[float] = None,
        cpu_percent: Optional[float] = None,
        uptime_seconds: Optional[float] = None,
    ) -> None:
        """Record a process lifecycle event in the history database.

        Args:
            process_name: Name of the process.
            event_type: Event type (start, stop, restart, crash, error,
                health_check).
            details: Human-readable description.
            pid: Process ID at time of event.
            memory_mb: Memory usage in MB at time of event.
            cpu_percent: CPU usage percent at time of event.
            uptime_seconds: Uptime in seconds at time of event.
        """
        process_name = self._normalise_name(process_name)
        try:
            db = self._get_db()
            db.execute(
                """
                INSERT INTO pm2_events
                    (process_name, event_type, details, pid,
                     memory_mb, cpu_percent, uptime_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    process_name,
                    event_type,
                    details,
                    pid,
                    memory_mb,
                    cpu_percent,
                    uptime_seconds,
                ),
            )
            db.commit()
            logger.debug(
                "Recorded PM2 event: %s/%s — %s",
                process_name,
                event_type,
                details,
            )
        except Exception:
            logger.warning(
                "Failed to record PM2 event %s/%s",
                process_name,
                event_type,
                exc_info=True,
            )

    def event_history(
        self,
        process_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get process event history from the database.

        Args:
            process_name: Filter to a specific process.  None returns all.
            limit: Maximum number of events to return.

        Returns:
            List of event dicts ordered by timestamp descending.
        """
        try:
            db = self._get_db()
            if process_name:
                process_name = self._normalise_name(process_name)
                cursor = db.execute(
                    """
                    SELECT id, timestamp, process_name, event_type, details,
                           pid, memory_mb, cpu_percent, uptime_seconds
                    FROM pm2_events
                    WHERE process_name = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (process_name, limit),
                )
            else:
                cursor = db.execute(
                    """
                    SELECT id, timestamp, process_name, event_type, details,
                           pid, memory_mb, cpu_percent, uptime_seconds
                    FROM pm2_events
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception:
            logger.warning("Failed to query PM2 event history", exc_info=True)
            return []

    # ──── PM2 Module Management ──────────────────────────────────────

    def install_module(self, module_name: str) -> Dict[str, Any]:
        """Install a PM2 module (e.g., pm2-logrotate).

        Args:
            module_name: NPM package name of the PM2 module.

        Returns:
            Result dict with success status.

        Raises:
            PM2Error: If the installation fails.
        """
        logger.info("Installing PM2 module: %s", module_name)
        result = self._run_pm2("install", module_name, parse_json=False)
        self.record_event(
            "pm2-module", "install", f"Installed module: {module_name}"
        )
        return {
            "action": "install_module",
            "module": module_name,
            "success": True,
            "raw": result,
        }

    def list_modules(self) -> List[Dict[str, Any]]:
        """List installed PM2 modules.

        Returns:
            List of module info dicts with name, version, and status.
        """
        try:
            raw = self._run_pm2("jlist", parse_json=True)
        except PM2Error:
            logger.warning("Failed to list PM2 modules", exc_info=True)
            return []

        modules: List[Dict[str, Any]] = []
        if not isinstance(raw, list):
            return modules

        for entry in raw:
            pm2_env = entry.get("pm2_env", {})
            if pm2_env.get("pmx_module", False) or pm2_env.get(
                "pm2_module", False
            ):
                modules.append({
                    "name": entry.get("name", "unknown"),
                    "version": pm2_env.get("version", "unknown"),
                    "status": pm2_env.get("status", "unknown"),
                    "pid": entry.get("pid", 0),
                    "pm_id": entry.get("pm_id", -1),
                })
        return modules

    # ──── Internal Helpers ───────────────────────────────────────────

    def _run_pm2(self, *args: str, parse_json: bool = True) -> Any:
        """Execute a PM2 CLI command and return parsed result.

        Uses ``subprocess.run`` with capture, timeout, and JSON parsing.

        Args:
            *args: Arguments to pass to the ``pm2`` binary.
            parse_json: If True, parse stdout as JSON.

        Returns:
            Parsed JSON (dict/list) if ``parse_json`` is True, otherwise
            the raw stdout string.

        Raises:
            PM2Error: On non-zero exit code, timeout, or JSON parse failure.
        """
        cmd = [PM2_BINARY, *args]
        logger.debug("Running PM2 command: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=PM2_COMMAND_TIMEOUT,
                cwd=self._project_root,
            )
        except FileNotFoundError:
            raise PM2Error(
                f"PM2 binary '{PM2_BINARY}' not found — is PM2 installed "
                f"globally? (npm install -g pm2)",
                returncode=-1,
            )
        except subprocess.TimeoutExpired:
            raise PM2Error(
                f"PM2 command timed out after {PM2_COMMAND_TIMEOUT}s: "
                f"{' '.join(cmd)}",
                returncode=-1,
            )

        if result.returncode != 0:
            stderr_text = (result.stderr or "").strip()
            stdout_text = (result.stdout or "").strip()
            error_detail = stderr_text or stdout_text or "unknown error"
            logger.error(
                "PM2 command failed (rc=%d): %s — %s",
                result.returncode,
                " ".join(cmd),
                error_detail[:500],
            )
            raise PM2Error(
                f"PM2 command failed: {' '.join(cmd)} — "
                f"{error_detail[:300]}",
                returncode=result.returncode,
                stderr=stderr_text,
            )

        stdout = (result.stdout or "").strip()

        if not parse_json:
            return stdout

        if not stdout:
            return {}

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            # PM2 sometimes prepends ANSI codes or banners before JSON.
            for i, ch in enumerate(stdout):
                if ch in ("[", "{"):
                    try:
                        return json.loads(stdout[i:])
                    except json.JSONDecodeError:
                        continue
            logger.error(
                "Failed to parse PM2 JSON for '%s': %s  (first 200: %s)",
                " ".join(cmd),
                exc,
                stdout[:200],
            )
            raise PM2Error(
                f"Cannot parse PM2 JSON: {exc}",
                returncode=0,
                stderr=stdout[:300],
            )

    def _get_db(self) -> sqlite3.Connection:
        """Get a thread-local SQLite connection.

        Returns:
            An open ``sqlite3.Connection`` in WAL mode.
        """
        conn: Optional[sqlite3.Connection] = getattr(
            self._local, "conn", None
        )
        if conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def _ensure_db_directory(self) -> None:
        """Create the database directory if it does not exist."""
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    def _ensure_tables(self) -> None:
        """Create history tables if they don't exist."""
        if self._tables_created:
            return
        with self._table_lock:
            if self._tables_created:
                return
            db = self._get_db()
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS pm2_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                    process_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT DEFAULT '',
                    pid INTEGER,
                    memory_mb REAL,
                    cpu_percent REAL,
                    uptime_seconds REAL
                );
                CREATE INDEX IF NOT EXISTS idx_pm2_events_name
                    ON pm2_events(process_name);
                CREATE INDEX IF NOT EXISTS idx_pm2_events_type
                    ON pm2_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_pm2_events_ts
                    ON pm2_events(timestamp);

                CREATE TABLE IF NOT EXISTS pm2_health_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                    total_processes INTEGER,
                    online_count INTEGER,
                    errored_count INTEGER,
                    stopped_count INTEGER,
                    total_memory_mb REAL,
                    total_cpu REAL,
                    health_score REAL,
                    details TEXT
                );
                """
            )
            db.commit()
            self._tables_created = True
            logger.debug(
                "PM2 history tables verified/created at %s", self._db_path
            )

    def _parse_process_info(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise PM2 jlist output into a clean dict.

        Args:
            raw: A single process entry from ``pm2 jlist``.

        Returns:
            Normalised dict with consistent keys.
        """
        pm2_env = raw.get("pm2_env", {})
        monit = raw.get("monit", {})

        memory_bytes = monit.get("memory", 0) or 0
        memory_mb = (
            round(memory_bytes / (1024 * 1024), 2) if memory_bytes else 0.0
        )

        created_at_ms = pm2_env.get("created_at", 0) or pm2_env.get(
            "pm_uptime", 0
        )
        if created_at_ms and created_at_ms > 1e12:
            created_at_s = created_at_ms / 1000.0
        else:
            created_at_s = float(created_at_ms) if created_at_ms else 0.0

        uptime_seconds = 0.0
        if created_at_s > 0:
            uptime_seconds = round(time.time() - created_at_s, 1)
            if uptime_seconds < 0:
                uptime_seconds = 0.0

        status = pm2_env.get("status", "unknown")

        return {
            "name": raw.get("name", pm2_env.get("name", "unknown")),
            "pm_id": raw.get("pm_id", pm2_env.get("pm_id", -1)),
            "pid": raw.get("pid", 0),
            "status": status,
            "cpu": monit.get("cpu", 0.0) or 0.0,
            "memory_mb": memory_mb,
            "memory_bytes": memory_bytes,
            "uptime_seconds": uptime_seconds,
            "restarts": pm2_env.get("restart_time", 0) or 0,
            "unstable_restarts": pm2_env.get("unstable_restarts", 0) or 0,
            "created_at": (
                datetime.fromtimestamp(
                    created_at_s, tz=timezone.utc
                ).isoformat()
                if created_at_s > 0
                else None
            ),
            "script": pm2_env.get("pm_exec_path", ""),
            "interpreter": pm2_env.get("exec_interpreter", ""),
            "cwd": pm2_env.get("pm_cwd", ""),
            "args": pm2_env.get("args", []),
            "exec_mode": pm2_env.get("exec_mode", "fork"),
            "node_version": pm2_env.get("node_version", ""),
            "autorestart": pm2_env.get("autorestart", True),
            "max_restarts": pm2_env.get("max_restarts", 0),
            "watch": pm2_env.get("watch", False),
            "merge_logs": pm2_env.get("merge_logs", False),
            "error_log": pm2_env.get("pm_err_log_path", ""),
            "out_log": pm2_env.get("pm_out_log_path", ""),
        }

    def _ecosystem_config_path(self) -> str:
        """Resolve path to ecosystem.config.js.

        Returns:
            Absolute path to the ecosystem config file.
        """
        return os.path.join(self._project_root, DEFAULT_ECOSYSTEM)

    def _read_ecosystem_names(self) -> List[str]:
        """Read process names defined in ecosystem.config.js.

        Uses a Node.js subprocess to parse the JavaScript config and
        extract app names.

        Returns:
            List of process names defined in the ecosystem config.
        """
        config_path = self._ecosystem_config_path()
        if not os.path.isfile(config_path):
            logger.warning("Ecosystem config not found at %s", config_path)
            return []

        safe_path = config_path.replace("\\", "/")
        node_script = (
            f"try {{ "
            f"const c = require('{safe_path}'); "
            f"console.log(JSON.stringify((c.apps || []).map(a => a.name))); "
            f"}} catch(e) {{ console.log('[]'); }}"
        )
        try:
            result = subprocess.run(
                ["node", "-e", node_script],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self._project_root,
            )
            if result.returncode == 0 and result.stdout.strip():
                names = json.loads(result.stdout.strip())
                if isinstance(names, list):
                    return [str(n) for n in names]
        except FileNotFoundError:
            logger.warning(
                "Node.js not found — cannot parse ecosystem.config.js"
            )
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            logger.warning(
                "Failed to parse ecosystem.config.js", exc_info=True
            )
        return []

    def _normalise_name(self, name: str) -> str:
        """Ensure a process name carries the CosySim prefix.

        Args:
            name: Raw process name.

        Returns:
            Name guaranteed to start with ``cosysim-``.
        """
        if not name:
            return name
        if name in ("all", "ecosystem"):
            return name
        if not name.startswith(PROCESS_NAME_PREFIX):
            return f"{PROCESS_NAME_PREFIX}{name}"
        return name

    def _notify_nexus(
        self, event_type: str, details: Dict[str, Any]
    ) -> None:
        """Store significant events in Nexus knowledge base.

        Args:
            event_type: Category of the event (crash, health_degradation,
                etc.).
            details: Event details to store.
        """
        try:
            from engine.nexus.client import get_nexus_client

            client = get_nexus_client()
            title = f"PM2 Event: {event_type}"
            content = json.dumps(details, indent=2, default=str)
            client.add_entry(
                title=title,
                content=content,
                content_type="note",
                category="system",
            )
            logger.debug("Nexus notified: %s", title)
        except ImportError:
            logger.debug(
                "Nexus client not available — skipping notification"
            )
        except Exception:
            logger.debug(
                "Failed to notify Nexus of PM2 event", exc_info=True
            )

    def _record_health_snapshot(self, report: Dict[str, Any]) -> None:
        """Persist a health snapshot to the SQLite database.

        Args:
            report: Health report dict from ``health_report()``.
        """
        db = self._get_db()
        db.execute(
            """
            INSERT INTO pm2_health_snapshots
                (total_processes, online_count, errored_count, stopped_count,
                 total_memory_mb, total_cpu, health_score, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.get("total", 0),
                report.get("online", 0),
                report.get("errored", 0),
                report.get("stopped_count", 0),
                report.get("memory_total_mb", 0.0),
                report.get("cpu_total", 0.0),
                report.get("health_score", 0.0),
                json.dumps(
                    {
                        "healthy": report.get("healthy", []),
                        "unhealthy": report.get("unhealthy", []),
                        "stopped": report.get("stopped", []),
                        "recommendations": report.get("recommendations", []),
                    },
                    default=str,
                ),
            ),
        )
        db.commit()


# ──── Scheduler Integration ─────────────────────────────────────────────


def register_pm2_tasks(daemon: Any) -> None:
    """Register PM2 monitoring tasks with the scheduler daemon.

    Args:
        daemon: A scheduler daemon instance with a ``register()`` method
            (typically ``engine.nexus.scheduler_daemon``).
    """
    mgr = get_pm2_manager()

    def pm2_health_check() -> Dict[str, Any]:
        """Run a PM2 health check, notify Nexus on degradation."""
        report = mgr.health_report()
        score = report.get("health_score", 1.0)
        if score < 0.7:
            logger.warning(
                "PM2 health degraded (score=%.2f) — notifying Nexus", score
            )
            mgr._notify_nexus("health_degradation", report)
        else:
            logger.debug("PM2 health OK (score=%.2f)", score)
        return report

    def pm2_ecosystem_drift_check() -> Dict[str, Any]:
        """Check for ecosystem config drift."""
        diff = mgr.ecosystem_diff()
        missing = diff.get("missing", [])
        drift_items = diff.get("drift", [])
        if missing or drift_items:
            logger.warning(
                "PM2 ecosystem drift detected — missing=%s drift=%s",
                missing,
                [d["name"] for d in drift_items],
            )
            mgr._notify_nexus("ecosystem_drift", diff)
        return diff

    daemon.register(
        task_id="pm2-health-check",
        name="PM2 Health Check (5 min)",
        schedule="every_5m",
        callback=pm2_health_check,
        enabled=True,
    )
    daemon.register(
        task_id="pm2-ecosystem-drift",
        name="PM2 Ecosystem Drift Check (15 min)",
        schedule="every_15m",
        callback=pm2_ecosystem_drift_check,
        enabled=True,
    )
    logger.info("PM2 monitoring tasks registered with scheduler daemon")


# ──── CLI Entry Point ────────────────────────────────────────────────────


def _cli_main() -> None:
    """Command-line interface for the PM2 manager."""
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="CosySim PM2 Process Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--list", action="store_true", help="List all PM2 processes"
    )
    group.add_argument(
        "--health", action="store_true", help="Generate health report"
    )
    group.add_argument(
        "--diff", action="store_true", help="Show ecosystem drift"
    )
    group.add_argument(
        "--metrics", action="store_true", help="Show CPU/memory metrics"
    )
    group.add_argument(
        "--xref",
        action="store_true",
        help="Cross-reference with OS processes",
    )
    group.add_argument(
        "--history",
        nargs="?",
        const="__all__",
        metavar="NAME",
        help="Show event history",
    )
    group.add_argument(
        "--describe", metavar="NAME", help="Describe a specific process"
    )
    group.add_argument(
        "--start", metavar="NAME", help="Start a process"
    )
    group.add_argument(
        "--stop", metavar="NAME", help="Stop a process"
    )
    group.add_argument(
        "--restart", metavar="NAME", help="Restart a process"
    )
    group.add_argument(
        "--modules", action="store_true", help="List installed PM2 modules"
    )

    args = parser.parse_args()
    mgr = get_pm2_manager()

    try:
        if args.list:
            _cli_list(mgr)
        elif args.health:
            _cli_health(mgr)
        elif args.diff:
            _cli_diff(mgr)
        elif args.metrics:
            _cli_metrics(mgr)
        elif args.xref:
            _cli_xref(mgr)
        elif args.history is not None:
            name = None if args.history == "__all__" else args.history
            _cli_history(mgr, name)
        elif args.describe:
            _cli_describe(mgr, args.describe)
        elif args.start:
            result = mgr.start(args.start)
            logger.info("Started: %s", result.get("process", args.start))
        elif args.stop:
            result = mgr.stop(args.stop)
            logger.info("Stopped: %s", result.get("process", args.stop))
        elif args.restart:
            result = mgr.restart(args.restart)
            logger.info(
                "Restarted: %s", result.get("process", args.restart)
            )
        elif args.modules:
            _cli_modules(mgr)
        else:
            parser.print_help()

    except PM2Error as exc:
        logger.error("PM2 error: %s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


def _cli_list(mgr: PM2Manager) -> None:
    """Print a table of all PM2 processes."""
    procs = mgr.list_processes()
    if not procs:
        logger.info("No PM2 processes found")
        return
    header = (
        f"{'Name':<30} {'Status':<10} {'PID':<8} "
        f"{'CPU%':<7} {'Mem MB':<9} {'Restarts':<10} {'Uptime'}"
    )
    logger.info(header)
    logger.info("-" * len(header))
    for p in procs:
        uptime_s = p.get("uptime_seconds", 0)
        if uptime_s > 86400:
            uptime_str = f"{uptime_s / 86400:.1f}d"
        elif uptime_s > 3600:
            uptime_str = f"{uptime_s / 3600:.1f}h"
        elif uptime_s > 60:
            uptime_str = f"{uptime_s / 60:.1f}m"
        else:
            uptime_str = f"{uptime_s:.0f}s"
        logger.info(
            f"{p.get('name', '?'):<30} {p.get('status', '?'):<10} "
            f"{p.get('pid', 0):<8} {p.get('cpu', 0):<7.1f} "
            f"{p.get('memory_mb', 0):<9.1f} "
            f"{p.get('restarts', 0):<10} {uptime_str}"
        )


def _cli_health(mgr: PM2Manager) -> None:
    """Print the health report."""
    report = mgr.health_report()
    logger.info("=== PM2 Health Report ===")
    logger.info(
        "Summary:     %s (score: %.2f)",
        report["summary"],
        report["health_score"],
    )
    logger.info("Total:       %d processes", report["total"])
    logger.info("Online:      %d", report["online"])
    logger.info("Errored:     %d", report["errored"])
    logger.info("Stopped:     %d", report["stopped_count"])
    logger.info("Memory:      %.1f MB total", report["memory_total_mb"])
    logger.info("CPU:         %.1f%% total", report["cpu_total"])
    if report.get("uptime_stats"):
        stats = report["uptime_stats"]
        logger.info(
            "Uptime:      min=%.0fs  avg=%.0fs  max=%.0fs",
            stats.get("min", 0),
            stats.get("avg", 0),
            stats.get("max", 0),
        )
    if report["healthy"]:
        logger.info("Healthy:     %s", ", ".join(report["healthy"]))
    if report["unhealthy"]:
        logger.warning("Unhealthy:   %s", ", ".join(report["unhealthy"]))
    if report["stopped"]:
        logger.info("Stopped:     %s", ", ".join(report["stopped"]))
    if report["recommendations"]:
        logger.info("--- Recommendations ---")
        for rec in report["recommendations"]:
            logger.info("  • %s", rec)


def _cli_diff(mgr: PM2Manager) -> None:
    """Print ecosystem diff."""
    diff = mgr.ecosystem_diff()
    logger.info("=== Ecosystem Diff ===")
    logger.info("Defined:  %d processes", len(diff["defined"]))
    logger.info("Running:  %d processes", len(diff["running"]))
    if diff["missing"]:
        logger.warning("Missing:  %s", ", ".join(diff["missing"]))
    else:
        logger.info("Missing:  none")
    if diff["extra"]:
        logger.info("Extra:    %s", ", ".join(diff["extra"]))
    else:
        logger.info("Extra:    none")
    if diff["drift"]:
        logger.warning("Drift:")
        for d in diff["drift"]:
            logger.warning(
                "  %s: expected=%s actual=%s restarts=%d",
                d["name"],
                d["expected_status"],
                d["actual_status"],
                d["restarts"],
            )


def _cli_metrics(mgr: PM2Manager) -> None:
    """Print metrics for all processes."""
    m = mgr.metrics()
    logger.info("=== PM2 Metrics ===")
    logger.info(
        "Processes: %d   CPU: %.1f%%   Memory: %.1f MB",
        m["process_count"],
        m["total_cpu"],
        m["total_memory_mb"],
    )
    for name, data in m.get("processes", {}).items():
        logger.info(
            "  %-28s  cpu=%.1f%%  mem=%.1f MB  uptime=%.0fs  "
            "restarts=%d  status=%s",
            name,
            data["cpu"],
            data["memory_mb"],
            data["uptime_seconds"],
            data["restarts"],
            data["status"],
        )


def _cli_xref(mgr: PM2Manager) -> None:
    """Print cross-reference results."""
    xref = mgr.cross_reference()
    logger.info("=== Cross-Reference ===")
    logger.info("PM2 processes: %d", xref.get("pm2_count", 0))
    if xref.get("matched"):
        logger.info("Matched PIDs:")
        for m in xref["matched"]:
            logger.info(
                "  PID %d: pm2=%s  os=%s",
                m["pid"],
                m["pm2_name"],
                m["os_name"],
            )
    if xref.get("orphaned"):
        logger.warning("Orphaned (PM2 ref but no OS process):")
        for o in xref["orphaned"]:
            logger.warning(
                "  PID %d: %s — %s", o["pid"], o["pm2_name"], o["note"]
            )
    if xref.get("untracked"):
        logger.info("Untracked CosySim processes:")
        for u in xref["untracked"]:
            logger.info("  PID %d: %s", u["pid"], u["cmdline"][:100])
    if xref.get("error"):
        logger.warning("Error: %s", xref["error"])


def _cli_history(mgr: PM2Manager, name: Optional[str]) -> None:
    """Print event history."""
    events = mgr.event_history(process_name=name, limit=50)
    if not events:
        logger.info("No event history found")
        return
    logger.info("=== Event History (%s) ===", name or "all")
    for ev in events:
        logger.info(
            "  %s  %-25s  %-12s  %s",
            ev.get("timestamp", "?"),
            ev.get("process_name", "?"),
            ev.get("event_type", "?"),
            ev.get("details", ""),
        )


def _cli_describe(mgr: PM2Manager, name: str) -> None:
    """Print detailed process info."""
    info = mgr.describe(name)
    logger.info("=== %s ===", info.get("name", name))
    for key in (
        "status",
        "pid",
        "pm_id",
        "cpu",
        "memory_mb",
        "uptime_seconds",
        "restarts",
        "script",
        "interpreter",
        "cwd",
        "exec_mode",
        "autorestart",
        "error_log",
        "out_log",
        "created_at",
    ):
        logger.info("  %-18s  %s", key, info.get(key, "—"))


def _cli_modules(mgr: PM2Manager) -> None:
    """Print installed PM2 modules."""
    mods = mgr.list_modules()
    if not mods:
        logger.info("No PM2 modules installed")
        return
    for mod in mods:
        logger.info(
            "  %-30s  v%-10s  %s",
            mod["name"],
            mod["version"],
            mod["status"],
        )


if __name__ == "__main__":
    _cli_main()
