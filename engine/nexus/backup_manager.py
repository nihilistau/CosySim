"""Backup Manager — automated backup of all CosySim SQLite databases.

Performs incremental and full backups of:
  - Nexus KMS database (Nexus/data/nexus.db)
  - Session store (~/.copilot/session-store.db or session-store/store.sqlite)
  - Training flywheel database (data/training_flywheel.db)
  - Any other SQLite databases discovered under data/

Backups are compressed (.db.gz) and stored under data/backups/ with
timestamped filenames.  Retention policy removes backups older than N days.

Schedule::

    Scheduler: backup-databases (daily at 03:00)

MCP tools::

    backup_run()        — run a full backup cycle now
    backup_list()       — list all backups with sizes and ages
    backup_restore(path, target) — restore a backup to target path

CLI::

    python -m engine.nexus.backup_manager          # run backup
    python -m engine.nexus.backup_manager --list   # list backups
    python -m engine.nexus.backup_manager --restore <path> <target>
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_BACKUP_DIR_DEFAULT = Path("data") / "backups"
_DEFAULT_RETENTION_DAYS = 14
_DEFAULT_FULL_BACKUP_DAYS = 7  # Full backup every N days; else incremental

# Known database targets (relative paths from project root or absolute)
_KNOWN_DBS: Dict[str, str] = {
    "nexus": "C:/Files/Nexus/data/nexus.db",
    "session_store": "~/.copilot/session-store/store.sqlite",
    "training_flywheel": "data/training_flywheel.db",
    "task_scheduler": "data/task_scheduler.db",
}


# ──── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class BackupEntry:
    """Metadata for a single backup file."""

    name: str               # Source database name
    timestamp: str          # ISO-8601 UTC
    path: str               # Absolute path to .db.gz
    size_kb: float          # Compressed size
    backup_type: str        # "full" or "incremental"
    success: bool = True
    error: str = ""


@dataclass
class BackupResult:
    """Result of a full backup cycle."""

    started_at: str = ""
    finished_at: str = ""
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    total_size_kb: float = 0.0
    entries: List[BackupEntry] = field(default_factory=list)
    pruned: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "total_size_kb": round(self.total_size_kb, 1),
            "pruned": self.pruned,
        }


# ──── BackupManager ───────────────────────────────────────────────────────────


class BackupManager:
    """Manages incremental and full backups of all CosySim SQLite databases.

    Args:
        backup_dir: Directory to store backups.
        retention_days: Delete backups older than this many days.
        full_backup_days: Run a full backup every N days; else incremental.
    """

    def __init__(
        self,
        backup_dir: Optional[Path] = None,
        retention_days: int = _DEFAULT_RETENTION_DAYS,
        full_backup_days: int = _DEFAULT_FULL_BACKUP_DAYS,
    ) -> None:
        cfg = get_config()
        self._backup_dir = Path(
            backup_dir
            or cfg.get("nexus.backup_dir", str(_BACKUP_DIR_DEFAULT))
        )
        self._retention_days = retention_days
        self._full_backup_days = full_backup_days
        self._last_result: Optional[BackupResult] = None
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def run_backup(self) -> BackupResult:
        """Run a full backup cycle for all known databases.

        Returns:
            BackupResult with per-database status and summary statistics.
        """
        result = BackupResult(started_at=_now())
        targets = self._discover_databases()

        for name, path in targets.items():
            src = Path(os.path.expanduser(str(path)))
            if not src.exists():
                logger.debug("Skipping %s — not found at %s", name, src)
                result.skipped += 1
                continue
            entry = self._backup_one(name, src)
            result.entries.append(entry)
            if entry.success:
                result.succeeded += 1
                result.total_size_kb += entry.size_kb
            else:
                result.failed += 1

        result.pruned = self._prune_old()
        result.finished_at = _now()
        self._last_result = result
        self._save_manifest(result)

        logger.info(
            "Backup complete: %d ok, %d failed, %d skipped, %d pruned (%.1f KB total)",
            result.succeeded, result.failed, result.skipped,
            result.pruned, result.total_size_kb,
        )
        return result

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all backup files with metadata.

        Returns:
            List of dicts with name, path, size_kb, age_days, timestamp.
        """
        entries = []
        now = datetime.now(timezone.utc)
        for gz in sorted(self._backup_dir.glob("*.db.gz")):
            stat = gz.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            age_days = (now - mtime).total_seconds() / 86400
            entries.append({
                "filename": gz.name,
                "path": str(gz),
                "size_kb": round(stat.st_size / 1024, 1),
                "age_days": round(age_days, 1),
                "modified": mtime.isoformat(timespec="seconds"),
            })
        return entries

    def restore_backup(self, backup_path: str, target_path: str) -> Dict[str, Any]:
        """Restore a compressed backup to a target path.

        Args:
            backup_path: Path to the .db.gz file.
            target_path: Destination path for the restored .db file.

        Returns:
            Dict with success, restored_path, size_kb.
        """
        src = Path(backup_path)
        dst = Path(os.path.expanduser(target_path))
        if not src.exists():
            return {"success": False, "error": f"Backup not found: {src}"}
        if not src.name.endswith(".db.gz"):
            return {"success": False, "error": "Expected .db.gz file"}
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temp file first for atomicity
            tmp = dst.with_suffix(".tmp")
            with gzip.open(src, "rb") as f_in, open(tmp, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            tmp.rename(dst)
            size_kb = round(dst.stat().st_size / 1024, 1)
            logger.info("Restored %s → %s (%.1f KB)", src.name, dst, size_kb)
            return {"success": True, "restored_path": str(dst), "size_kb": size_kb}
        except Exception as exc:
            logger.error("Restore failed: %s", exc)
            return {"success": False, "error": str(exc)}

    def get_last_result(self) -> Optional[Dict[str, Any]]:
        """Return the last backup result as a dict, or None."""
        if self._last_result is None:
            self._last_result = self._load_last_manifest()
        return self._last_result.to_dict() if self._last_result else None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _discover_databases(self) -> Dict[str, Path]:
        """Collect all database paths: known + any .db files under data/."""
        targets: Dict[str, Path] = {}
        for name, path_str in _KNOWN_DBS.items():
            targets[name] = Path(os.path.expanduser(path_str))
        # Discover additional SQLite DBs under data/
        data_dir = Path("data")
        if data_dir.exists():
            for db_file in data_dir.glob("*.db"):
                slug = db_file.stem
                if slug not in targets:
                    targets[slug] = db_file
        return targets

    def _backup_one(self, name: str, src: Path) -> BackupEntry:
        """Backup a single database file to a compressed archive.

        Uses sqlite3's backup API for a consistent snapshot (handles WAL mode).

        Args:
            name: Logical name (e.g. "nexus").
            src: Absolute path to the source .db file.

        Returns:
            BackupEntry with success/failure details.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_type = self._get_backup_type(name)
        filename = f"{name}_{timestamp}_{backup_type}.db.gz"
        dst = self._backup_dir / filename
        entry = BackupEntry(
            name=name,
            timestamp=_now(),
            path=str(dst),
            size_kb=0.0,
            backup_type=backup_type,
        )
        try:
            # sqlite3 online backup into an in-memory buffer, then compress
            src_conn = sqlite3.connect(str(src), timeout=30.0)
            mem_conn = sqlite3.connect(":memory:")
            try:
                src_conn.backup(mem_conn)
                mem_conn.execute("VACUUM")  # Compact before write
            finally:
                src_conn.close()

            # Dump to temp .db file then compress
            tmp_db = dst.with_suffix(".tmp.db")
            disk_conn = sqlite3.connect(str(tmp_db))
            try:
                mem_conn.backup(disk_conn)
            finally:
                disk_conn.close()
                mem_conn.close()

            # Compress
            with open(tmp_db, "rb") as f_in, gzip.open(dst, "wb", compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)
            tmp_db.unlink()

            entry.size_kb = round(dst.stat().st_size / 1024, 1)
            logger.info("Backed up %s → %s (%.1f KB)", name, filename, entry.size_kb)

        except Exception as exc:
            entry.success = False
            entry.error = str(exc)
            logger.error("Backup failed for %s: %s", name, exc)
            if dst.exists():
                dst.unlink(missing_ok=True)

        return entry

    def _get_backup_type(self, name: str) -> str:
        """Determine if this should be a full or incremental backup."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._full_backup_days)
        existing = sorted(self._backup_dir.glob(f"{name}_*_full.db.gz"))
        if not existing:
            return "full"
        latest = existing[-1]
        mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
        return "full" if mtime < cutoff else "incremental"

    def _prune_old(self) -> int:
        """Delete backup files older than retention_days.

        Always keeps the most recent full backup for each database.

        Returns:
            Number of files deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        pruned = 0
        # Group by db name
        by_name: Dict[str, List[Path]] = {}
        for gz in self._backup_dir.glob("*.db.gz"):
            parts = gz.stem.rsplit("_", 2)
            if len(parts) >= 1:
                db_name = parts[0]
                by_name.setdefault(db_name, []).append(gz)

        for db_name, files in by_name.items():
            files.sort(key=lambda p: p.stat().st_mtime)
            full_backups = [f for f in files if "_full" in f.name]
            keep_latest_full = full_backups[-1] if full_backups else None
            for f in files:
                if f == keep_latest_full:
                    continue  # Always keep latest full
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    f.unlink()
                    pruned += 1
                    logger.debug("Pruned old backup: %s", f.name)

        return pruned

    def _save_manifest(self, result: BackupResult) -> None:
        """Save last backup result to manifest JSON for status queries."""
        manifest_path = self._backup_dir / "last_backup.json"
        try:
            data = result.to_dict()
            data["entries"] = [asdict(e) for e in result.entries]
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.warning("Failed to save backup manifest: %s", exc)

    def _load_last_manifest(self) -> Optional[BackupResult]:
        """Load the last backup result from manifest JSON."""
        manifest_path = self._backup_dir / "last_backup.json"
        if not manifest_path.exists():
            return None
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            r = BackupResult()
            for k, v in data.items():
                if k != "entries" and hasattr(r, k):
                    setattr(r, k, v)
            return r
        except Exception as exc:
            logger.warning("Failed to load backup manifest: %s", exc)
            return None


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ──── Singleton ───────────────────────────────────────────────────────────────

_backup_instance: Optional[BackupManager] = None
_backup_lock = threading.Lock()


def get_backup_manager() -> BackupManager:
    """Get the singleton BackupManager instance."""
    global _backup_instance
    if _backup_instance is None:
        with _backup_lock:
            if _backup_instance is None:
                _backup_instance = BackupManager()
    return _backup_instance


def run_backup() -> Dict[str, Any]:
    """Convenience function for scheduler callback.

    Returns:
        BackupResult as a dict.
    """
    result = get_backup_manager().run_backup()
    return result.to_dict()


# ──── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="CosySim database backup manager")
    parser.add_argument("--list", action="store_true", help="List all backups")
    parser.add_argument("--restore", nargs=2, metavar=("BACKUP_PATH", "TARGET_PATH"),
                        help="Restore a backup")
    parser.add_argument("--retention-days", type=int, default=_DEFAULT_RETENTION_DAYS)
    args = parser.parse_args()

    mgr = BackupManager(retention_days=args.retention_days)

    if args.list:
        backups = mgr.list_backups()
        if not backups:
            print("No backups found.")
        for b in backups:
            print(f"  {b['filename']:<50}  {b['size_kb']:>8.1f} KB  {b['age_days']:.1f}d old")
        sys.exit(0)

    if args.restore:
        result = mgr.restore_backup(args.restore[0], args.restore[1])
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["success"] else 1)

    # Default: run backup
    result = mgr.run_backup()
    print(json.dumps(result.to_dict(), indent=2))
    sys.exit(0 if result.failed == 0 else 1)
