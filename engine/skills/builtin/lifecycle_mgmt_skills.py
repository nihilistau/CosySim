"""Lifecycle Management MCP skills — schema migration and graceful shutdown.

Pack ``lifecycle_mgmt`` (10 skills) exposes the schema migration engine and
the graceful shutdown manager to MCP-connected agents.  All return values
are JSON-formatted strings for LLM consumption.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill, SkillCategory
from engine.skills.utils import to_json

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────


def _json(obj: Any) -> str:
    """Serialise *obj* to an indented JSON string."""
    return to_json(obj, indent=2)


def _error(action: str, exc: Exception) -> str:
    """Return a standard error-JSON payload."""
    return _json({"error": True, "action": action, "message": str(exc)})


# ── Schema Migration Skills (5) ──────────────────────────────────────────


@skill(
    pack="lifecycle_mgmt",
    description="Get schema migration status for one or all databases.",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "migration", "schema", "status"],
)
def get_schema_status(db_name: str = "") -> str:
    """Return migration status for a single database or all tracked databases.

    Args:
        db_name: Logical database name.  If empty, returns status for all.

    Returns:
        JSON with current version, pending count, and pending versions.
    """
    try:
        from engine.nexus.schema_migration import get_migration_engine

        engine = get_migration_engine()
        if db_name:
            status = engine.get_status(db_name)
            return _json(asdict(status))
        statuses = engine.get_all_status()
        return _json({name: asdict(s) for name, s in statuses.items()})
    except Exception as exc:
        logger.error("get_schema_status failed: %s", exc, exc_info=True)
        return _error("get_schema_status", exc)


@skill(
    pack="lifecycle_mgmt",
    description="Run all pending schema migrations for a database.",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "migration", "schema", "upgrade"],
)
def run_schema_migration(db_name: str) -> str:
    """Apply every unapplied migration for *db_name* in version order.

    Args:
        db_name: Logical database name (required).

    Returns:
        JSON with the list of applied version numbers.
    """
    try:
        from engine.nexus.schema_migration import get_migration_engine

        engine = get_migration_engine()
        applied = engine.run_pending(db_name)
        return _json({
            "db_name": db_name,
            "applied_versions": applied,
            "applied_count": len(applied),
        })
    except Exception as exc:
        logger.error("run_schema_migration failed for '%s': %s", db_name, exc, exc_info=True)
        return _error("run_schema_migration", exc)


@skill(
    pack="lifecycle_mgmt",
    description="Detect schema drift in one or all databases.",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "migration", "schema", "drift"],
)
def detect_schema_drift(db_name: str = "") -> str:
    """Compare live schema against the stored baseline snapshot.

    Args:
        db_name: Logical database name.  If empty, checks all discovered databases.

    Returns:
        JSON with detected diffs (empty list means no drift).
    """
    try:
        from engine.nexus.schema_migration import get_migration_engine

        engine = get_migration_engine()
        if db_name:
            diffs = engine.detect_drift(db_name)
            return _json({
                "db_name": db_name,
                "drift_detected": len(diffs) > 0,
                "diff_count": len(diffs),
                "diffs": [str(d) for d in diffs],
            })
        all_drift = engine.detect_all_drift()
        result: Dict[str, Any] = {}
        for name, diffs in all_drift.items():
            result[name] = {
                "drift_detected": True,
                "diff_count": len(diffs),
                "diffs": [str(d) for d in diffs],
            }
        return _json({
            "databases_with_drift": len(result),
            "details": result,
        })
    except Exception as exc:
        logger.error("detect_schema_drift failed: %s", exc, exc_info=True)
        return _error("detect_schema_drift", exc)


@skill(
    pack="lifecycle_mgmt",
    description="List all discovered SQLite databases in the project.",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "migration", "database", "discovery"],
)
def discover_databases() -> str:
    """Scan known directories for .db files and return metadata.

    Returns:
        JSON list of discovered databases with name, path, size, and table count.
    """
    try:
        from engine.nexus.schema_migration import get_migration_engine

        engine = get_migration_engine()
        databases = engine.discover_databases()
        return _json({
            "count": len(databases),
            "databases": [asdict(db) for db in databases],
        })
    except Exception as exc:
        logger.error("discover_databases failed: %s", exc, exc_info=True)
        return _error("discover_databases", exc)


@skill(
    pack="lifecycle_mgmt",
    description="Get migration history for a database.",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "migration", "schema", "history"],
)
def get_migration_history(db_name: str, limit: int = 20) -> str:
    """Return the migration history log for *db_name*, newest first.

    Args:
        db_name: Logical database name (required).
        limit: Maximum number of history entries to return.

    Returns:
        JSON list of history records with version, description, timestamp, and status.
    """
    try:
        from engine.nexus.schema_migration import get_migration_engine

        engine = get_migration_engine()
        history = engine.get_history(db_name, limit=limit)
        return _json({
            "db_name": db_name,
            "entry_count": len(history),
            "history": history,
        })
    except Exception as exc:
        logger.error("get_migration_history failed for '%s': %s", db_name, exc, exc_info=True)
        return _error("get_migration_history", exc)


# ── Shutdown Management Skills (5) ───────────────────────────────────────


@skill(
    pack="lifecycle_mgmt",
    description="Get current shutdown state and registered handler summary.",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "shutdown", "status"],
)
def get_shutdown_status() -> str:
    """Return the shutdown manager's current state, handler count, and phase breakdown.

    Returns:
        JSON with state, handler_count, phases, and signals_installed.
    """
    try:
        from engine.lifecycle.shutdown_manager import get_shutdown_manager

        mgr = get_shutdown_manager()
        return _json(mgr.get_status())
    except Exception as exc:
        logger.error("get_shutdown_status failed: %s", exc, exc_info=True)
        return _error("get_shutdown_status", exc)


@skill(
    pack="lifecycle_mgmt",
    description="List all registered shutdown handlers with phase and priority.",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "shutdown", "handlers"],
)
def list_shutdown_handlers() -> str:
    """Return metadata for every registered shutdown handler, sorted by execution order.

    Returns:
        JSON list of handlers with name, phase, priority, timeout, and critical flag.
    """
    try:
        from engine.lifecycle.shutdown_manager import get_shutdown_manager

        mgr = get_shutdown_manager()
        handlers = mgr.get_handler_list()
        return _json({
            "handler_count": len(handlers),
            "handlers": handlers,
        })
    except Exception as exc:
        logger.error("list_shutdown_handlers failed: %s", exc, exc_info=True)
        return _error("list_shutdown_handlers", exc)


@skill(
    pack="lifecycle_mgmt",
    description="Initiate orderly graceful shutdown of CosySim (DANGEROUS).",
    category=SkillCategory.SYSTEM,
    cooldown=300.0,
    tags=["lifecycle", "shutdown", "dangerous"],
)
def initiate_graceful_shutdown(reason: str) -> str:
    """Begin phased shutdown: DRAIN → FLUSH → CLOSE → CLEANUP.

    This is a destructive operation — it will stop all running services.

    Args:
        reason: Human-readable reason for initiating shutdown (required).

    Returns:
        JSON shutdown report with per-phase results and overall success flag.
    """
    try:
        from engine.lifecycle.shutdown_manager import get_shutdown_manager

        mgr = get_shutdown_manager()
        logger.warning("Agent-initiated shutdown: %s", reason)
        report = mgr.initiate_shutdown(reason=reason)
        if report is None:
            return _json({
                "status": "in_progress",
                "message": "Shutdown already in progress on another thread.",
            })
        return _json({
            "status": "completed",
            "reason": report.reason,
            "success": report.success,
            "forced": report.forced,
            "total_duration_ms": report.total_duration_ms,
            "phases": [
                {
                    "phase": pr.phase.value,
                    "total": pr.total_handlers,
                    "succeeded": pr.succeeded,
                    "failed": pr.failed,
                    "timed_out": pr.timed_out,
                    "duration_ms": pr.duration_ms,
                    "errors": pr.errors,
                }
                for pr in report.phases
            ],
        })
    except Exception as exc:
        logger.error("initiate_graceful_shutdown failed: %s", exc, exc_info=True)
        return _error("initiate_graceful_shutdown", exc)


@skill(
    pack="lifecycle_mgmt",
    description="Register a database for graceful shutdown flushing.",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "shutdown", "database", "registration"],
)
def register_db_shutdown(db_name: str) -> str:
    """Create and register a FLUSH-phase handler that commits and closes a database.

    The handler uses the schema migration engine to resolve the database path
    and creates a flush callback that safely closes the connection at shutdown.

    Args:
        db_name: Logical database name to register (required).

    Returns:
        JSON confirmation with handler name and phase.
    """
    try:
        from engine.lifecycle.shutdown_manager import (
            create_database_flush_handler,
            get_shutdown_manager,
        )
        from engine.nexus.schema_migration import get_migration_engine

        engine = get_migration_engine()
        db_path = engine._get_db_path(db_name)

        def _flush_and_close() -> None:
            """Commit and close the database connection at shutdown."""
            import sqlite3 as _sqlite3

            if not db_path or not __import__("os").path.exists(db_path):
                logger.debug("DB '%s' not found at shutdown — skipping", db_name)
                return
            try:
                conn = _sqlite3.connect(db_path)
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.close()
                logger.info("Flushed and closed database '%s'", db_name)
            except Exception as e:
                logger.warning("Error flushing '%s': %s", db_name, e)

        handler = create_database_flush_handler(db_name, _flush_and_close)
        mgr = get_shutdown_manager()
        mgr.register(handler)

        return _json({
            "registered": True,
            "handler_name": handler.name,
            "phase": handler.phase.value,
            "priority": handler.priority,
            "timeout": handler.timeout,
            "db_name": db_name,
            "db_path": db_path,
        })
    except Exception as exc:
        logger.error("register_db_shutdown failed for '%s': %s", db_name, exc, exc_info=True)
        return _error("register_db_shutdown", exc)


@skill(
    pack="lifecycle_mgmt",
    description="Combined lifecycle health: migration status + shutdown state.",
    category=SkillCategory.SYSTEM,
    tags=["lifecycle", "migration", "shutdown", "health"],
)
def get_system_lifecycle() -> str:
    """Return a unified lifecycle health snapshot.

    Combines schema migration status summary (pending counts, drift) with
    the shutdown manager's current state and handler count.

    Returns:
        JSON with migration_summary, shutdown_state, handler_count, and
        any warnings about pending migrations or drift.
    """
    result: Dict[str, Any] = {
        "migration": {},
        "shutdown": {},
        "warnings": [],
    }

    # Migration status
    try:
        from engine.nexus.schema_migration import get_migration_engine

        engine = get_migration_engine()
        all_status = engine.get_all_status()
        total_pending = sum(s.pending_count for s in all_status.values())
        dbs_with_pending = [
            name for name, s in all_status.items() if s.pending_count > 0
        ]
        result["migration"] = {
            "tracked_databases": len(all_status),
            "total_pending_migrations": total_pending,
            "databases_with_pending": dbs_with_pending,
        }
        if total_pending > 0:
            result["warnings"].append(
                f"{total_pending} pending migration(s) across "
                f"{len(dbs_with_pending)} database(s)"
            )
    except Exception as exc:
        result["migration"] = {"error": str(exc)}
        result["warnings"].append(f"Migration engine unavailable: {exc}")

    # Shutdown status
    try:
        from engine.lifecycle.shutdown_manager import get_shutdown_manager

        mgr = get_shutdown_manager()
        status = mgr.get_status()
        result["shutdown"] = {
            "state": status["state"],
            "handler_count": status["handler_count"],
            "phases": status["phases"],
            "signals_installed": status["signals_installed"],
        }
        if status["state"] != "running":
            result["warnings"].append(
                f"Shutdown state is '{status['state']}' (not running)"
            )
    except Exception as exc:
        result["shutdown"] = {"error": str(exc)}
        result["warnings"].append(f"Shutdown manager unavailable: {exc}")

    return _json(result)
