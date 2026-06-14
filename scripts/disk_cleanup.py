"""
Disk Cleanup — Immediate Memory Crisis Recovery
================================================

One-time (or recurring) disk cleanup script for CosySim.
Reclaims disk space from HAR files, Chrome profile caches,
stale backups, and uncheckpointed SQLite WAL files.

Usage:
    python scripts/disk_cleanup.py              # Dry run — show what would be freed
    python scripts/disk_cleanup.py --execute    # Actually delete + checkpoint WAL files
    python scripts/disk_cleanup.py --execute --keep-hars 3  # Keep 3 days of HARs

Version: v1.51.0 [2026-03-24]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-24] — Initial creation for memory crisis recovery
"""

import argparse
import logging
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

# ── Project root ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

logger = logging.getLogger("disk_cleanup")
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ── Utilities ───────────────────────────────────────────────────────

def format_bytes(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def dir_size(path: Path) -> int:
    """Total size of a directory tree in bytes."""
    total = 0
    if not path.exists():
        return 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def file_age_days(path: Path) -> float:
    """Age of file in days since last modification."""
    try:
        return (time.time() - path.stat().st_mtime) / 86400
    except OSError:
        return 0.0


# ── Cleanup Functions ───────────────────────────────────────────────

# v1.51.0 [2026-03-24] — HAR file cleanup
def scan_har_files(max_age_days: int = 7) -> Tuple[List[Path], int]:
    """Find HAR/heap files older than max_age_days.

    Returns:
        (list_of_files_to_delete, total_bytes)
    """
    har_dir = DATA_DIR / "har_files"
    if not har_dir.exists():
        return [], 0

    extensions = {".har", ".heaptimeline", ".heapsnapshot"}
    targets: List[Path] = []
    total = 0

    for f in har_dir.rglob("*"):
        if f.is_file() and (f.suffix.lower() in extensions or f.name.endswith(".har")):
            if file_age_days(f) > max_age_days:
                targets.append(f)
                total += f.stat().st_size

    return targets, total


# v1.51.0 [2026-03-24] — Chrome profile cache cleanup
# CONNECTS: CDP auth recovery (engine/nexus/cdp_auth_recovery.py) uses cookie files
# NOTE: Only delete cache subdirs, NOT the profile root
CHROME_CACHE_SUBDIRS = [
    "Cache", "Code Cache", "Service Worker", "GPUCache",
    "component_crx_cache", "optimization_guide_model_store",
    "Safe Browsing",
]


def scan_chrome_caches() -> Tuple[List[Path], int]:
    """Find Chrome profile cache directories that can be safely deleted.

    Returns:
        (list_of_dirs_to_delete, total_bytes)
    """
    targets: List[Path] = []
    total = 0

    for profile_dir in DATA_DIR.glob("chrome_*_profile"):
        if not profile_dir.is_dir():
            continue
        for subdir_name in CHROME_CACHE_SUBDIRS:
            cache_dir = profile_dir / subdir_name
            if cache_dir.exists() and cache_dir.is_dir():
                size = dir_size(cache_dir)
                if size > 0:
                    targets.append(cache_dir)
                    total += size

    return targets, total


# v1.51.0 [2026-03-24] — Backup retention (count-based)
def scan_stale_backups(max_per_db: int = 3) -> Tuple[List[Path], int]:
    """Find backup files exceeding count limit per database.

    Keeps the N most recent backups per database name (always keeps latest full).

    Returns:
        (list_of_files_to_delete, total_bytes)
    """
    backup_dir = DATA_DIR / "backups"
    if not backup_dir.exists():
        return [], 0

    # Group by database name
    by_name: Dict[str, List[Path]] = {}
    for gz in backup_dir.glob("*.db.gz"):
        # Filename format: nexus_20260323_232809_incremental.db.gz
        parts = gz.stem.rsplit("_", 2)
        db_name = parts[0] if parts else gz.stem
        by_name.setdefault(db_name, []).append(gz)

    targets: List[Path] = []
    total = 0

    for db_name, files in by_name.items():
        # Sort newest first
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        # Always keep the latest full backup
        full_backups = [f for f in files if "_full" in f.name]
        keep_latest_full = full_backups[0] if full_backups else None

        # Mark excess files for deletion
        for f in files[max_per_db:]:
            if f == keep_latest_full:
                continue
            targets.append(f)
            total += f.stat().st_size

    return targets, total


# v1.51.0 [2026-03-24] — SQLite WAL checkpoint
def scan_wal_files() -> Tuple[List[Path], int]:
    """Find SQLite WAL files that need checkpointing.

    Returns:
        (list_of_wal_files, total_bytes)
    """
    targets: List[Path] = []
    total = 0

    for wal in DATA_DIR.glob("*.db-wal"):
        try:
            size = wal.stat().st_size
            if size > 0:
                targets.append(wal)
                total += size
        except OSError:
            pass

    return targets, total


def checkpoint_wal(db_path: Path) -> bool:
    """Run PRAGMA wal_checkpoint(TRUNCATE) on a database.

    Returns True if successful.
    """
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        return True
    except Exception as exc:
        logger.warning("  Could not checkpoint %s: %s", db_path.name, exc)
        return False


# v1.51.0 [2026-03-24] — Structured log rotation
def scan_log_rotation() -> Tuple[List[Path], int]:
    """Find structured log files that should be rotated.

    Returns:
        (list_of_files, total_bytes)
    """
    targets: List[Path] = []
    total = 0

    jsonl = DATA_DIR / "structured_logs.jsonl"
    if jsonl.exists():
        size = jsonl.stat().st_size
        if size > 100 * 1024:  # Only rotate if > 100 KB
            targets.append(jsonl)
            total += size

    return targets, total


# ── Main ────────────────────────────────────────────────────────────

def run_scan(max_har_age: int = 7, max_backups: int = 3) -> Dict[str, Tuple[list, int]]:
    """Run all scans and return results by category."""
    return {
        "har_files": scan_har_files(max_har_age),
        "chrome_caches": scan_chrome_caches(),
        "stale_backups": scan_stale_backups(max_backups),
        "wal_files": scan_wal_files(),
        "log_rotation": scan_log_rotation(),
    }


def print_report(results: Dict[str, Tuple[list, int]]) -> int:
    """Print scan report and return total reclaimable bytes."""
    grand_total = 0

    print("\n" + "=" * 60)
    print("  CosySim Disk Cleanup Report")
    print("=" * 60)

    labels = {
        "har_files": "HAR Files & Heap Snapshots",
        "chrome_caches": "Chrome Profile Caches",
        "stale_backups": "Stale Nexus Backups",
        "wal_files": "SQLite WAL Files (uncheckpointed)",
        "log_rotation": "Structured Log Rotation",
    }

    for key, (files, size) in results.items():
        label = labels.get(key, key)
        print(f"\n  {label}")
        print(f"  {'-' * 40}")
        if not files:
            print(f"    (none)")
        else:
            for f in files[:10]:  # Show first 10
                try:
                    fsize = dir_size(f) if f.is_dir() else f.stat().st_size
                    print(f"    {f.name:<50} {format_bytes(fsize):>10}")
                except OSError:
                    print(f"    {f.name:<50} {'???':>10}")
            if len(files) > 10:
                print(f"    ... and {len(files) - 10} more")
            print(f"    Subtotal: {format_bytes(size)}")
            grand_total += size

    print(f"\n{'=' * 60}")
    print(f"  TOTAL RECLAIMABLE: {format_bytes(grand_total)}")
    print(f"{'=' * 60}\n")

    return grand_total


def execute_cleanup(results: Dict[str, Tuple[list, int]]) -> int:
    """Execute the cleanup. Returns total bytes freed."""
    freed = 0

    # 1. HAR files — delete individual files
    har_files, har_size = results["har_files"]
    if har_files:
        print(f"\n  Deleting {len(har_files)} HAR/heap files ({format_bytes(har_size)})...")
        for f in har_files:
            try:
                f.unlink()
                freed += f.stat().st_size if f.exists() else 0
            except OSError:
                pass
        freed += har_size
        print(f"    Done.")

    # 2. Chrome caches — delete directories
    chrome_dirs, chrome_size = results["chrome_caches"]
    if chrome_dirs:
        print(f"\n  Deleting {len(chrome_dirs)} Chrome cache directories ({format_bytes(chrome_size)})...")
        for d in chrome_dirs:
            try:
                shutil.rmtree(str(d), ignore_errors=True)
            except Exception:
                pass
        freed += chrome_size
        print(f"    Done.")

    # 3. Stale backups — delete files
    backup_files, backup_size = results["stale_backups"]
    if backup_files:
        print(f"\n  Deleting {len(backup_files)} stale backup files ({format_bytes(backup_size)})...")
        for f in backup_files:
            try:
                f.unlink()
            except OSError:
                pass
        freed += backup_size
        print(f"    Done.")

    # 4. WAL files — checkpoint databases
    wal_files, wal_size = results["wal_files"]
    if wal_files:
        print(f"\n  Checkpointing {len(wal_files)} SQLite WAL files ({format_bytes(wal_size)})...")
        for wal in wal_files:
            db_path = wal.with_suffix("").with_suffix(".db")  # foo.db-wal -> foo.db
            if db_path.exists():
                ok = checkpoint_wal(db_path)
                if ok:
                    freed += wal_size
                    print(f"    Checkpointed: {db_path.name}")
            else:
                # Orphaned WAL — safe to delete
                try:
                    wal.unlink()
                    freed += wal.stat().st_size if wal.exists() else 0
                    print(f"    Removed orphaned: {wal.name}")
                except OSError:
                    pass
        print(f"    Done.")

    # 5. Log rotation — rename JSONL
    log_files, log_size = results["log_rotation"]
    if log_files:
        print(f"\n  Rotating structured logs ({format_bytes(log_size)})...")
        for f in log_files:
            bak = f.with_suffix(".jsonl.bak")
            try:
                if bak.exists():
                    bak.unlink()
                f.rename(bak)
                freed += log_size
                print(f"    Rotated: {f.name} -> {bak.name}")
            except OSError as exc:
                print(f"    Could not rotate {f.name}: {exc}")
        print(f"    Done.")

    print(f"\n  TOTAL FREED: {format_bytes(freed)}")
    return freed


def main():
    parser = argparse.ArgumentParser(
        description="CosySim disk cleanup — reclaim space from caches, HARs, backups, and WAL files"
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually delete files (default: dry run only)"
    )
    parser.add_argument(
        "--keep-hars", type=int, default=7,
        help="Keep HAR files newer than N days (default: 7)"
    )
    parser.add_argument(
        "--keep-backups", type=int, default=3,
        help="Keep N most recent backups per database (default: 3)"
    )
    args = parser.parse_args()

    if not DATA_DIR.exists():
        print(f"Data directory not found: {DATA_DIR}")
        sys.exit(1)

    # Scan
    results = run_scan(max_har_age=args.keep_hars, max_backups=args.keep_backups)
    total = print_report(results)

    if total == 0:
        print("  Nothing to clean up!")
        return

    if not args.execute:
        print("  This was a DRY RUN. Use --execute to actually clean up.")
        print(f"  Example: python scripts/disk_cleanup.py --execute")
        return

    # Execute
    print("\n  EXECUTING CLEANUP...")
    freed = execute_cleanup(results)
    print(f"\n  Cleanup complete. Freed approximately {format_bytes(freed)}.")


if __name__ == "__main__":
    main()
