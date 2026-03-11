"""
System recovery and management MCP skills for CosySim agents.

Provides database backup/restore, error log analysis, service recovery,
configuration snapshotting/rollback, and comprehensive system diagnostics.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)

# ── Project root (two levels up from this file) ─────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# ── Known database locations ────────────────────────────────────────
_DB_MAP: Dict[str, str] = {
    "simulation": "data/simulation.db",
    "nexus": "data/nexus.db",
    "metrics": "data/metrics.db",
}

# ── Known restartable services ──────────────────────────────────────
_SERVICE_ENTRY_POINTS: Dict[str, str] = {
    "hub": "launcher.py --hub",
    "tts": "start_servers.ps1",
    "nexus": "-m nexus",
}


def _port_registry():
    """Lazy import for the port registry singleton."""
    from engine.port_registry import get_port_registry
    return get_port_registry()


def _check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


def _ensure_dir(path: Path) -> None:
    """Create directory if it does not exist."""
    path.mkdir(parents=True, exist_ok=True)


# ── Service Restart ─────────────────────────────────────────────────


@skill(
    pack="system_recovery",
    description="Restart a CosySim service by name (scene, hub, tts, nexus)",
    tags=["recovery", "admin", "restart"],
    category=SkillCategory.SYSTEM,
    cooldown=10.0,
    cost=2.0,
)
def restart_service(service_name: str) -> str:
    """Restart a named CosySim service after checking its health."""
    try:
        registry = _port_registry()
        try:
            port = registry.get(service_name)
        except KeyError:
            return json.dumps({
                "ok": False,
                "service": service_name,
                "error": f"Unknown service: {service_name}",
            })

        was_up = _check_port("localhost", port)
        logger.info(
            "restart_service: %s (port %d) — pre-restart status: %s",
            service_name, port, "online" if was_up else "offline",
        )

        # Determine entry point
        entry = _SERVICE_ENTRY_POINTS.get(service_name)
        if entry is None:
            # Scene-based service
            entry = f"launcher.py --scene {service_name}"

        cmd = f"{sys.executable} {entry}"
        try:
            subprocess.Popen(
                cmd,
                shell=True,
                cwd=str(_PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except Exception as exc:
            return json.dumps({
                "ok": False,
                "service": service_name,
                "port": port,
                "error": f"Failed to start process: {exc}",
            })

        return json.dumps({
            "ok": True,
            "service": service_name,
            "port": port,
            "was_online": was_up,
            "action": "restart_initiated",
            "command": cmd,
        })
    except Exception as exc:
        logger.exception("restart_service failed for %s", service_name)
        return json.dumps({"ok": False, "service": service_name, "error": str(exc)})


# ── Database Backup ─────────────────────────────────────────────────


def _prune_backups(backup_dir: Path, prefix: str, keep: int = 10) -> List[str]:
    """Delete oldest backups exceeding *keep*, return list of removed paths."""
    pattern = f"{prefix}_*.db"
    backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    removed: List[str] = []
    while len(backups) > keep:
        oldest = backups.pop(0)
        oldest.unlink(missing_ok=True)
        removed.append(str(oldest))
        logger.info("Pruned old backup: %s", oldest)
    return removed


@skill(
    pack="system_recovery",
    description="Create a timestamped backup of a CosySim database (simulation, nexus, metrics)",
    tags=["recovery", "backup", "database"],
    category=SkillCategory.SYSTEM,
    cooldown=5.0,
    cost=1.0,
)
def backup_database(db_name: str = "simulation") -> str:
    """Create a timestamped backup of the specified database file."""
    try:
        rel_path = _DB_MAP.get(db_name)
        if rel_path is None:
            return json.dumps({
                "ok": False,
                "error": f"Unknown database: {db_name}. Valid: {', '.join(_DB_MAP)}",
            })

        src = _PROJECT_ROOT / rel_path
        if not src.exists():
            return json.dumps({
                "ok": False,
                "error": f"Database file not found: {src}",
            })

        backup_dir = _PROJECT_ROOT / "backups"
        _ensure_dir(backup_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"{db_name}_{timestamp}.db"

        shutil.copy2(str(src), str(dest))
        size_kb = dest.stat().st_size / 1024

        pruned = _prune_backups(backup_dir, db_name, keep=10)

        logger.info("Database backup created: %s (%.1f KB)", dest, size_kb)
        return json.dumps({
            "ok": True,
            "db_name": db_name,
            "backup_path": str(dest),
            "size_kb": round(size_kb, 1),
            "pruned": pruned,
        })
    except Exception as exc:
        logger.exception("backup_database failed for %s", db_name)
        return json.dumps({"ok": False, "db_name": db_name, "error": str(exc)})


# ── Database Restore ────────────────────────────────────────────────


def _is_valid_sqlite(path: Path) -> bool:
    """Return True if *path* is a readable SQLite database."""
    try:
        conn = sqlite3.connect(str(path))
        conn.execute("SELECT 1")
        conn.close()
        return True
    except Exception:
        return False


@skill(
    pack="system_recovery",
    description="Restore a CosySim database from a backup file",
    tags=["recovery", "restore", "database"],
    category=SkillCategory.SYSTEM,
    cooldown=10.0,
    cost=2.0,
)
def restore_database(backup_path: str, db_name: str = "simulation") -> str:
    """Restore a database from a backup file after validation."""
    try:
        backup = Path(backup_path)
        if not backup.exists():
            return json.dumps({"ok": False, "error": f"Backup not found: {backup_path}"})

        if not _is_valid_sqlite(backup):
            return json.dumps({"ok": False, "error": f"Invalid SQLite file: {backup_path}"})

        rel_path = _DB_MAP.get(db_name)
        if rel_path is None:
            return json.dumps({
                "ok": False,
                "error": f"Unknown database: {db_name}. Valid: {', '.join(_DB_MAP)}",
            })

        target = _PROJECT_ROOT / rel_path

        # Create a pre-restore safety backup
        pre_restore_path: Optional[str] = None
        if target.exists():
            backup_dir = _PROJECT_ROOT / "backups"
            _ensure_dir(backup_dir)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_restore = backup_dir / f"{db_name}_pre_restore_{timestamp}.db"
            shutil.copy2(str(target), str(pre_restore))
            pre_restore_path = str(pre_restore)
            logger.info("Pre-restore backup saved: %s", pre_restore)

        shutil.copy2(str(backup), str(target))
        logger.info("Database restored: %s → %s", backup_path, target)

        return json.dumps({
            "ok": True,
            "db_name": db_name,
            "restored_from": str(backup),
            "target": str(target),
            "pre_restore_backup": pre_restore_path,
        })
    except Exception as exc:
        logger.exception("restore_database failed")
        return json.dumps({"ok": False, "error": str(exc)})


# ── Error Log Analysis ──────────────────────────────────────────────


_LOG_LEVEL_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"
    r".*?\b(ERROR|CRITICAL)\b"
    r".*?(?:\[([^\]]+)\])?"
    r"\s*(.*)",
)


@skill(
    pack="system_recovery",
    description="Analyze recent error and critical log entries from the logs directory",
    tags=["recovery", "logs", "diagnostics"],
    category=SkillCategory.SYSTEM,
    cooldown=3.0,
    cost=1.0,
)
def analyze_error_log(service: str = "", hours: int = 1) -> str:
    """Read log files and summarize ERROR/CRITICAL entries from the last N hours."""
    try:
        logs_dir = _PROJECT_ROOT / "logs"
        if not logs_dir.exists():
            return json.dumps({"ok": True, "errors": [], "summary": "No logs directory found."})

        cutoff = datetime.now() - timedelta(hours=hours)
        log_files: List[Path] = []

        for f in logs_dir.iterdir():
            if not f.is_file() or f.suffix not in (".log", ".txt"):
                continue
            if service and service.lower() not in f.name.lower():
                continue
            log_files.append(f)

        if not log_files:
            return json.dumps({
                "ok": True,
                "errors": [],
                "summary": f"No log files found{' for ' + service if service else ''}.",
            })

        errors_by_module: Dict[str, List[Dict[str, Any]]] = {}
        total_errors = 0

        for log_file in log_files:
            try:
                text = log_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for line in text.splitlines():
                match = _LOG_LEVEL_RE.search(line)
                if not match:
                    continue

                ts_str, level, module, message = match.groups()
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue

                if ts < cutoff:
                    continue

                module = module or log_file.stem
                message = message.strip()[:200]
                total_errors += 1

                if module not in errors_by_module:
                    errors_by_module[module] = []
                errors_by_module[module].append({
                    "level": level,
                    "time": ts_str,
                    "message": message,
                    "file": log_file.name,
                })

        # Build summary within 2000-char limit
        summary_parts: List[str] = [
            f"Log analysis: {total_errors} error(s) in last {hours}h",
            f"Files scanned: {len(log_files)}",
        ]
        top_modules: List[Dict[str, Any]] = []
        for module, entries in sorted(
            errors_by_module.items(), key=lambda x: len(x[1]), reverse=True
        )[:10]:
            times = [e["time"] for e in entries]
            top_modules.append({
                "module": module,
                "count": len(entries),
                "first": min(times),
                "last": max(times),
                "sample": entries[0]["message"][:120],
            })

        result = json.dumps({
            "ok": True,
            "total_errors": total_errors,
            "hours": hours,
            "files_scanned": len(log_files),
            "top_modules": top_modules,
            "summary": " | ".join(summary_parts),
        })

        # Truncate to ~2000 chars for LLM consumption
        if len(result) > 2000:
            result = result[:1997] + "..."
        return result
    except Exception as exc:
        logger.exception("analyze_error_log failed")
        return json.dumps({"ok": False, "error": str(exc)})


# ── Health Recovery ─────────────────────────────────────────────────


@skill(
    pack="system_recovery",
    description="Run health checks and attempt automatic recovery for unhealthy services",
    tags=["recovery", "health", "auto-repair"],
    category=SkillCategory.SYSTEM,
    cooldown=15.0,
    cost=3.0,
)
def health_recover(service: str = "") -> str:
    """Check service health and attempt recovery for failing services."""
    try:
        registry = _port_registry()
        key_services = ["lmstudio", "nexus", "hub", "tts", "comfyui"]

        if service:
            if service in registry._ports or service in key_services:
                key_services = [service]
            else:
                return json.dumps({
                    "ok": False,
                    "error": f"Unknown service: {service}",
                })

        report: List[Dict[str, Any]] = []

        for svc in key_services:
            entry: Dict[str, Any] = {"service": svc, "action": "none"}
            try:
                port = registry.get(svc)
                entry["port"] = port
            except KeyError:
                entry["status"] = "unknown"
                entry["error"] = "Not in port registry"
                report.append(entry)
                continue

            is_up = _check_port("localhost", port)
            entry["status"] = "online" if is_up else "offline"

            if is_up:
                entry["action"] = "none_needed"
                report.append(entry)
                continue

            # Attempt recovery for known services
            if svc in _SERVICE_ENTRY_POINTS:
                cmd = f"{sys.executable} {_SERVICE_ENTRY_POINTS[svc]}"
                try:
                    subprocess.Popen(
                        cmd,
                        shell=True,
                        cwd=str(_PROJECT_ROOT),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                    )
                    entry["action"] = "restart_attempted"
                    entry["command"] = cmd
                except Exception as exc:
                    entry["action"] = "restart_failed"
                    entry["error"] = str(exc)
            elif svc in ("lmstudio", "comfyui"):
                entry["action"] = "external_service"
                entry["note"] = f"{svc} is external — manual restart required"
            else:
                # Check for port conflicts
                entry["action"] = "manual_intervention_needed"

            report.append(entry)

        online = sum(1 for r in report if r["status"] == "online")
        return json.dumps({
            "ok": True,
            "total": len(report),
            "online": online,
            "offline": len(report) - online,
            "services": report,
        })
    except Exception as exc:
        logger.exception("health_recover failed")
        return json.dumps({"ok": False, "error": str(exc)})


# ── Config Snapshot ─────────────────────────────────────────────────


@skill(
    pack="system_recovery",
    description="Save a snapshot of the current default.yaml configuration",
    tags=["recovery", "config", "backup"],
    category=SkillCategory.SYSTEM,
    cooldown=5.0,
    cost=1.0,
)
def config_snapshot(label: str = "") -> str:
    """Save config/default.yaml as a timestamped snapshot in backups/."""
    try:
        config_path = _PROJECT_ROOT / "config" / "default.yaml"
        if not config_path.exists():
            return json.dumps({"ok": False, "error": "config/default.yaml not found"})

        backup_dir = _PROJECT_ROOT / "backups"
        _ensure_dir(backup_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        label_part = f"_{label}" if label else ""
        dest = backup_dir / f"config{label_part}_{timestamp}.yaml"

        shutil.copy2(str(config_path), str(dest))
        size_kb = dest.stat().st_size / 1024

        # Prune to keep last 5 config snapshots
        snapshots = sorted(
            backup_dir.glob("config_*.yaml"),
            key=lambda p: p.stat().st_mtime,
        )
        pruned: List[str] = []
        while len(snapshots) > 5:
            oldest = snapshots.pop(0)
            oldest.unlink(missing_ok=True)
            pruned.append(str(oldest))

        logger.info("Config snapshot saved: %s", dest)
        return json.dumps({
            "ok": True,
            "snapshot_path": str(dest),
            "size_kb": round(size_kb, 1),
            "pruned": pruned,
        })
    except Exception as exc:
        logger.exception("config_snapshot failed")
        return json.dumps({"ok": False, "error": str(exc)})


# ── Config Rollback ─────────────────────────────────────────────────


@skill(
    pack="system_recovery",
    description="Rollback configuration to a previous snapshot",
    tags=["recovery", "config", "rollback"],
    category=SkillCategory.SYSTEM,
    cooldown=10.0,
    cost=2.0,
)
def config_rollback(snapshot_path: str = "") -> str:
    """Rollback config/default.yaml to a previous snapshot."""
    try:
        backup_dir = _PROJECT_ROOT / "backups"
        config_path = _PROJECT_ROOT / "config" / "default.yaml"

        # Find the snapshot to restore
        if snapshot_path:
            snapshot = Path(snapshot_path)
        else:
            snapshots = sorted(
                backup_dir.glob("config_*.yaml"),
                key=lambda p: p.stat().st_mtime,
            ) if backup_dir.exists() else []
            if not snapshots:
                return json.dumps({"ok": False, "error": "No config snapshots found"})
            snapshot = snapshots[-1]

        if not snapshot.exists():
            return json.dumps({"ok": False, "error": f"Snapshot not found: {snapshot}"})

        # Read both files to compute diff summary
        current_text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        snapshot_text = snapshot.read_text(encoding="utf-8")

        current_lines = set(current_text.splitlines())
        snapshot_lines = set(snapshot_text.splitlines())
        added = len(snapshot_lines - current_lines)
        removed = len(current_lines - snapshot_lines)

        # Backup current config before rollback
        _ensure_dir(backup_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pre_rollback = backup_dir / f"config_pre_rollback_{timestamp}.yaml"
        if config_path.exists():
            shutil.copy2(str(config_path), str(pre_rollback))

        # Perform rollback
        shutil.copy2(str(snapshot), str(config_path))

        logger.info("Config rolled back from %s", snapshot)
        return json.dumps({
            "ok": True,
            "restored_from": str(snapshot),
            "pre_rollback_backup": str(pre_rollback),
            "diff": {
                "lines_added": added,
                "lines_removed": removed,
            },
        })
    except Exception as exc:
        logger.exception("config_rollback failed")
        return json.dumps({"ok": False, "error": str(exc)})


# ── System Diagnostics ──────────────────────────────────────────────


def _get_gpu_info() -> Dict[str, Any]:
    """Query nvidia-smi for VRAM usage."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            return {
                "available": True,
                "vram_used_mb": int(parts[0]),
                "vram_total_mb": int(parts[1]),
                "vram_free_mb": int(parts[2]),
            }
    except Exception:
        pass
    return {"available": False}


def _get_db_stats(db_path: Path) -> Dict[str, Any]:
    """Get basic stats for a SQLite database."""
    stats: Dict[str, Any] = {}
    if not db_path.exists():
        return {"exists": False}

    stats["exists"] = True
    stats["size_mb"] = round(db_path.stat().st_size / (1024 * 1024), 2)

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        stats["tables"] = len(tables)

        table_sizes: Dict[str, int] = {}
        for table in tables[:20]:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
                table_sizes[table] = count
            except Exception:
                continue
        stats["row_counts"] = table_sizes
        conn.close()
    except Exception as exc:
        stats["error"] = str(exc)

    return stats


@skill(
    pack="system_recovery",
    description="Comprehensive system diagnostics: LMStudio, Nexus, databases, GPU, disk, services",
    tags=["recovery", "diagnostics", "system", "health"],
    category=SkillCategory.SYSTEM,
    cooldown=5.0,
    cost=2.0,
)
def system_diagnostics() -> str:
    """Generate a comprehensive system health and diagnostics report."""
    try:
        report: Dict[str, Any] = {}

        # LMStudio status
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:1234/api/v1/models")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                models = data.get("data", [])
                report["lmstudio"] = {
                    "status": "online",
                    "models_loaded": len(models),
                    "model_ids": [m.get("id", "?") for m in models[:5]],
                }
        except Exception:
            report["lmstudio"] = {"status": "offline"}

        # Nexus database
        nexus_db = _PROJECT_ROOT / "data" / "nexus.db"
        report["nexus"] = _get_db_stats(nexus_db)

        # Simulation database
        sim_db = _PROJECT_ROOT / "data" / "simulation.db"
        report["simulation_db"] = _get_db_stats(sim_db)

        # GPU info
        report["gpu"] = _get_gpu_info()

        # Disk space
        try:
            usage = shutil.disk_usage(str(_PROJECT_ROOT))
            report["disk"] = {
                "total_gb": round(usage.total / (1024 ** 3), 1),
                "used_gb": round(usage.used / (1024 ** 3), 1),
                "free_gb": round(usage.free / (1024 ** 3), 1),
            }
        except Exception:
            report["disk"] = {"error": "unavailable"}

        # Service port status
        registry = _port_registry()
        services_to_check = ["lmstudio", "nexus", "hub", "tts", "comfyui"]
        service_status: List[Dict[str, Any]] = []
        for svc in services_to_check:
            try:
                port = registry.get(svc)
                up = _check_port("localhost", port, timeout=0.5)
                service_status.append({
                    "service": svc,
                    "port": port,
                    "status": "online" if up else "offline",
                })
            except KeyError:
                service_status.append({"service": svc, "status": "unknown"})
        report["services"] = service_status

        return json.dumps(report)
    except Exception as exc:
        logger.exception("system_diagnostics failed")
        return json.dumps({"ok": False, "error": str(exc)})
