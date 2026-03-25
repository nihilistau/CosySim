"""
System Cleanup — Centralized Maintenance Routines
==================================================

Reusable cleanup functions for the scheduler daemon, startup hooks,
and the disk_cleanup.py CLI script. Each function is self-contained
and safe to call from any context (scenes, scheduler, CLI).

Version: v1.51.0 [2026-03-24]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-24] — Initial creation for memory crisis recovery
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"


# ── Config Helper ───────────────────────────────────────────────────

def _get_cfg(key: str, default: Any) -> Any:
    """Read a config value, falling back to default if config unavailable."""
    try:
        from engine.config import get_config
        return get_config().get(key, default)
    except Exception:
        return default


# ── Chrome Profile Cache Cleanup ────────────────────────────────────
# CONNECTS: CDP auth recovery (engine/nexus/cdp_auth_recovery.py)
# NOTE: Only delete cache subdirs — CDP auth needs cookies in profile root

_CACHE_SUBDIRS = [
    "Cache", "Code Cache", "Service Worker", "GPUCache",
    "component_crx_cache", "optimization_guide_model_store",
    "Safe Browsing",
]


# v1.51.0 [2026-03-24] — Chrome cache cleanup
def cleanup_chrome_caches() -> Dict[str, Any]:
    """Clear browser cache subdirectories from all Chrome profiles.

    Preserves profile roots (cookies, session files) needed by CDP auth.

    Returns:
        Dict with freed_bytes, profiles_cleaned, dirs_deleted counts.
    """
    if not _get_cfg("maintenance.chrome_cache_cleanup", True):
        return {"skipped": True, "reason": "disabled in config"}

    freed = 0
    profiles_cleaned = 0
    dirs_deleted = 0

    for profile_dir in DATA_DIR.glob("chrome_*_profile"):
        if not profile_dir.is_dir():
            continue
        cleaned_any = False
        for subdir_name in _CACHE_SUBDIRS:
            cache_dir = profile_dir / subdir_name
            if cache_dir.exists() and cache_dir.is_dir():
                try:
                    size = sum(
                        f.stat().st_size for f in cache_dir.rglob("*") if f.is_file()
                    )
                    shutil.rmtree(str(cache_dir), ignore_errors=True)
                    freed += size
                    dirs_deleted += 1
                    cleaned_any = True
                except Exception as exc:
                    logger.warning(
                        "[maintenance] Failed to clean %s (operation=chrome_cleanup): %s",
                        cache_dir, exc,
                    )
        if cleaned_any:
            profiles_cleaned += 1

    if freed > 0:
        logger.info(
            "[maintenance] Chrome caches cleaned (operation=chrome_cleanup): "
            "freed %.1f MB from %d profiles",
            freed / (1024 * 1024), profiles_cleaned,
        )

    return {
        "freed_bytes": freed,
        "profiles_cleaned": profiles_cleaned,
        "dirs_deleted": dirs_deleted,
    }


# ── HAR File Cleanup ───────────────────────────────────────────────

_HAR_EXTENSIONS = {".har", ".heaptimeline", ".heapsnapshot"}


# v1.51.0 [2026-03-24] — HAR file cleanup
def cleanup_har_files(max_age_days: int = 0) -> Dict[str, Any]:
    """Delete HAR and heap snapshot files older than max_age_days.

    Args:
        max_age_days: Files older than this are deleted. 0 = use config.

    Returns:
        Dict with freed_bytes, files_deleted counts.
    """
    if max_age_days <= 0:
        max_age_days = _get_cfg("maintenance.har_max_age_days", 7)

    har_dirs = [DATA_DIR / "har_files", DATA_DIR / "hars"]
    cutoff = time.time() - (max_age_days * 86400)
    freed = 0
    deleted = 0

    for har_dir in har_dirs:
        if not har_dir.exists():
            continue
        for f in har_dir.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in _HAR_EXTENSIONS:
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    size = f.stat().st_size
                    f.unlink()
                    freed += size
                    deleted += 1
            except OSError:
                pass

    if freed > 0:
        logger.info(
            "[maintenance] HAR cleanup (operation=har_cleanup): "
            "deleted %d files, freed %.1f MB",
            deleted, freed / (1024 * 1024),
        )

    return {"freed_bytes": freed, "files_deleted": deleted}


# ── SQLite WAL Checkpoint ──────────────────────────────────────────

# v1.51.0 [2026-03-24] — WAL checkpoint for all databases
def checkpoint_all_wal_files() -> Dict[str, Any]:
    """Run PRAGMA wal_checkpoint(TRUNCATE) on all databases with WAL files.

    Returns:
        Dict with checkpointed, failed, freed_bytes counts.
    """
    checkpointed = 0
    failed = 0
    freed = 0

    for wal in DATA_DIR.glob("*.db-wal"):
        try:
            wal_size = wal.stat().st_size
            if wal_size == 0:
                continue  # Already clean

            db_path = wal.with_name(wal.name.replace("-wal", ""))
            if not db_path.exists():
                # Orphaned WAL — safe to remove
                wal.unlink(missing_ok=True)
                shm = wal.with_name(wal.name.replace("-wal", "-shm"))
                shm.unlink(missing_ok=True)
                freed += wal_size
                checkpointed += 1
                continue

            conn = sqlite3.connect(str(db_path), timeout=5)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                freed += wal_size
                checkpointed += 1
            finally:
                conn.close()

        except Exception as exc:
            logger.warning(
                "[maintenance] WAL checkpoint failed for %s (operation=wal_checkpoint): %s",
                wal.name, exc,
            )
            failed += 1

    if checkpointed > 0:
        logger.info(
            "[maintenance] WAL checkpoint (operation=wal_checkpoint): "
            "%d databases checkpointed, freed %.1f MB",
            checkpointed, freed / (1024 * 1024),
        )

    return {"checkpointed": checkpointed, "failed": failed, "freed_bytes": freed}


# ── Structured Log Pruning ─────────────────────────────────────────

# v1.51.0 [2026-03-24] — Structured log retention
# CONNECTS: engine/observability/structured_logger.py (flush_old_logs)
def prune_structured_logs(days: int = 0) -> Dict[str, Any]:
    """Prune structured logs older than retention window.

    Calls the existing flush_old_logs() on the StructuredLogger and
    rotates the JSONL file.

    Args:
        days: Retention days. 0 = use config.

    Returns:
        Dict with db_deleted, jsonl_rotated, freed_bytes.
    """
    if days <= 0:
        days = _get_cfg("maintenance.log_retention_days", 7)

    result: Dict[str, Any] = {"db_deleted": 0, "jsonl_rotated": False, "freed_bytes": 0}

    # 1. Prune SQLite structured logs via existing method
    try:
        from engine.observability.structured_logger import get_structured_logger
        sl = get_structured_logger()
        if hasattr(sl, "flush_old_logs"):
            deleted = sl.flush_old_logs(days=days)
            result["db_deleted"] = deleted or 0
    except Exception as exc:
        logger.warning(
            "[maintenance] Structured log prune failed (operation=log_prune): %s", exc
        )

    # 2. Rotate JSONL file if it exists and is > 100 KB
    jsonl_path = DATA_DIR / "structured_logs.jsonl"
    if jsonl_path.exists():
        try:
            size = jsonl_path.stat().st_size
            if size > 100 * 1024:  # > 100 KB
                bak = jsonl_path.with_suffix(".jsonl.bak")
                if bak.exists():
                    bak.unlink()
                jsonl_path.rename(bak)
                result["jsonl_rotated"] = True
                result["freed_bytes"] = size
        except OSError as exc:
            logger.warning(
                "[maintenance] JSONL rotation failed (operation=log_rotate): %s", exc
            )

    if result["db_deleted"] or result["jsonl_rotated"]:
        logger.info(
            "[maintenance] Log prune (operation=log_prune): "
            "deleted %d DB rows, JSONL rotated=%s",
            result["db_deleted"], result["jsonl_rotated"],
        )

    return result


# ── MetaMetrics Pruning ────────────────────────────────────────────

# v1.51.0 [2026-03-24] — MetaMetrics data retention
def prune_meta_metrics(max_age_days: int = 30) -> Dict[str, Any]:
    """Prune old metric points from meta_metrics.db.

    Returns:
        Dict with deleted count.
    """
    db_path = DATA_DIR / "meta_metrics.db"
    if not db_path.exists():
        return {"deleted": 0}

    deleted = 0
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        conn = sqlite3.connect(str(db_path), timeout=5)
        try:
            cur = conn.execute(
                "DELETE FROM metric_points WHERE timestamp < ?", (cutoff,)
            )
            deleted = cur.rowcount
            conn.commit()
            # Checkpoint after bulk delete to reclaim WAL space
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    except Exception as exc:
        # Table might not exist or have different schema — that's OK
        logger.debug(
            "[maintenance] MetaMetrics prune skipped (operation=metrics_prune): %s", exc
        )

    if deleted > 0:
        logger.info(
            "[maintenance] MetaMetrics pruned (operation=metrics_prune): "
            "deleted %d old points",
            deleted,
        )

    return {"deleted": deleted}


# ── Conversation Eviction ──────────────────────────────────────────

# v1.51.0 [2026-03-24] — Evict stale LMStudio conversations
# CONNECTS: engine/lmstudio/conversation.py (ConversationManager)
def evict_stale_conversations(max_idle_seconds: float = 0) -> int:
    """Evict idle conversations from the ConversationManager singleton.

    Args:
        max_idle_seconds: Threshold. 0 = use config.

    Returns:
        Number of conversations evicted.
    """
    if max_idle_seconds <= 0:
        max_idle_seconds = _get_cfg("maintenance.conversation_idle_seconds", 3600)

    try:
        from engine.lmstudio.conversation import get_conversation_manager
        mgr = get_conversation_manager()
        evicted = mgr.evict_stale(max_idle_seconds=max_idle_seconds)

        # Also enforce hard cap
        max_count = _get_cfg("maintenance.conversation_max_count", 200)
        capped = mgr.cap_conversations(max_count=max_count)

        return evicted + capped
    except Exception as exc:
        logger.debug(
            "[maintenance] Conversation eviction skipped (operation=conv_evict): %s", exc
        )
        return 0


# ── Full Cleanup Orchestrator ──────────────────────────────────────

# v1.51.0 [2026-03-24] — Full system cleanup orchestrator
# CALLED BY: scheduler_daemon (daily), scripts/disk_cleanup.py
# EMITS: structured log entries via Oracle logger
def run_full_cleanup() -> Dict[str, Any]:
    """Run all cleanup routines and return a combined summary.

    Safe to call from any context — each sub-routine handles its own
    errors and never raises.

    Returns:
        Dict with per-routine results and total_freed_bytes.
    """
    logger.info("[maintenance] Starting full system cleanup (operation=full_cleanup)")

    results: Dict[str, Any] = {}
    total_freed = 0

    # 1. Chrome caches
    try:
        r = cleanup_chrome_caches()
        results["chrome_caches"] = r
        total_freed += r.get("freed_bytes", 0)
    except Exception as exc:
        results["chrome_caches"] = {"error": str(exc)}

    # 2. HAR files
    try:
        r = cleanup_har_files()
        results["har_files"] = r
        total_freed += r.get("freed_bytes", 0)
    except Exception as exc:
        results["har_files"] = {"error": str(exc)}

    # 3. WAL checkpoint
    try:
        r = checkpoint_all_wal_files()
        results["wal_checkpoint"] = r
        total_freed += r.get("freed_bytes", 0)
    except Exception as exc:
        results["wal_checkpoint"] = {"error": str(exc)}

    # 4. Structured logs
    try:
        r = prune_structured_logs()
        results["structured_logs"] = r
        total_freed += r.get("freed_bytes", 0)
    except Exception as exc:
        results["structured_logs"] = {"error": str(exc)}

    # 5. MetaMetrics
    try:
        r = prune_meta_metrics()
        results["meta_metrics"] = r
    except Exception as exc:
        results["meta_metrics"] = {"error": str(exc)}

    # 6. Conversations
    try:
        evicted = evict_stale_conversations()
        results["conversations"] = {"evicted": evicted}
    except Exception as exc:
        results["conversations"] = {"error": str(exc)}

    results["total_freed_bytes"] = total_freed

    logger.info(
        "[maintenance] Full cleanup complete (operation=full_cleanup): "
        "freed %.1f MB total",
        total_freed / (1024 * 1024) if total_freed > 0 else 0,
    )

    return results
