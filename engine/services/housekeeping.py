"""
Housekeeping Service — media ingest, health checks, integrity verification

Responsibilities:
  1. Media Ingest: Scan drop folders for new files, register in gallery DB + EventChain
  2. Health Checks: Verify all services (LMStudio, ComfyUI, TTS, MCP) are reachable
  3. DB Integrity: Find orphan DB records (missing files) and orphan files (no DB record)
  4. Cleanup: Remove stale temp files, compact job queues

Usage:
  python -m engine.services.housekeeping           # run once
  python -m engine.services.housekeeping --watch    # continuous (every 60s)
  python launcher.py --housekeep                    # via launcher
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from engine.paths import (ROOT as _PROJECT_ROOT, IMAGES_DIR, VIDEO_DIR,
                         VOICE_DIR, MEDIA_ALT_DIR)

# Directories to watch for new media files
MEDIA_DIRS = {
    "images": IMAGES_DIR,
    "video": VIDEO_DIR,
    "voice": VOICE_DIR,
    # Also scan the top-level content/media tree
    "images2": MEDIA_ALT_DIR / "images",
    "video2": MEDIA_ALT_DIR / "video",
    "voice2": MEDIA_ALT_DIR / "voice",
}

SUPPORTED_EXTENSIONS = {
    "images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"},
    "video": {".mp4", ".webm", ".avi", ".mov", ".mkv"},
    "voice": {".wav", ".mp3", ".ogg", ".flac", ".m4a"},
    "images2": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"},
    "video2": {".mp4", ".webm", ".avi", ".mov", ".mkv"},
    "voice2": {".wav", ".mp3", ".ogg", ".flac", ".m4a"},
}

# Map folder type → DB media type
FOLDER_TO_TYPE = {
    "images": "image", "video": "video", "voice": "voice",
    "images2": "image", "video2": "video", "voice2": "voice",
}


class HousekeepingService:
    """Runs health checks, media ingest, and DB integrity verification."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._load_config()
        self._results: Dict[str, any] = {}

    @staticmethod
    def _load_config() -> Dict:
        try:
            from engine.config import get_config
            return get_config()
        except Exception:
            logger.debug("Config unavailable, using defaults")
            return {}

    # ── Media Ingest ──────────────────────────────────────────────────

    def ingest_new_media(self, character_id: str = "default") -> List[Dict]:
        """
        Scan media folders for files not in the gallery DB.
        Register new files and return list of ingested items.
        """
        ingested = []
        try:
            from content.simulation.database.db import Database
            db = Database()
        except Exception as e:
            logger.error("Cannot connect to DB for ingest: %s", e)
            return ingested

        # Resolve character_id — must exist in characters table (FK constraint)
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                # Try to find the requested character first
                cursor.execute("SELECT id FROM characters WHERE id = ? OR name = ?",
                               (character_id, character_id))
                row = cursor.fetchone()
                if row:
                    character_id = row[0]
                else:
                    # Fallback: use first character in DB
                    cursor.execute("SELECT id FROM characters LIMIT 1")
                    row = cursor.fetchone()
                    if row:
                        character_id = row[0]
                    else:
                        # No characters — create a system character
                        import uuid as _uuid
                        character_id = str(_uuid.uuid4())
                        cursor.execute(
                            "INSERT INTO characters (id, name, personality_id, created_at) "
                            "VALUES (?, 'System', NULL, ?)",
                            (character_id, datetime.now().isoformat()))
                        conn.commit()
        except Exception as e:
            logger.warning("Could not resolve character_id: %s", e)

        # Get all known filepaths from DB
        known_paths = set()
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT filepath FROM media")
                known_paths = {row[0] for row in cursor.fetchall()}
        except Exception:
            logger.warning("Could not read known media paths from DB")

        for folder_key, folder_path in MEDIA_DIRS.items():
            if not folder_path.exists():
                folder_path.mkdir(parents=True, exist_ok=True)
                continue

            valid_exts = SUPPORTED_EXTENSIONS.get(folder_key, set())
            media_type = FOLDER_TO_TYPE.get(folder_key, "image")

            for fp in folder_path.iterdir():
                if not fp.is_file():
                    continue
                if fp.suffix.lower() not in valid_exts:
                    continue

                # Check if already registered (by absolute or relative path)
                fp_str = str(fp)
                fp_rel = str(fp.relative_to(_PROJECT_ROOT))
                if fp_str in known_paths or fp_rel in known_paths:
                    continue

                # Register new file
                media_id = str(uuid.uuid4())
                timestamp = datetime.now().isoformat()
                try:
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        import json as _json
                        metadata = _json.dumps({"source": "ingest", "original_name": fp.name})
                        cursor.execute("""
                            INSERT INTO media (id, character_id, type, filepath, metadata, created_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (media_id, character_id, media_type, fp_str,
                              metadata,
                              timestamp))
                        conn.commit()

                    ingested.append({
                        "id": media_id,
                        "type": media_type,
                        "filepath": fp_str,
                        "name": fp.name,
                    })
                    logger.info("Ingested: %s → %s (%s)", fp.name, media_id, media_type)
                except Exception as e:
                    logger.warning("Failed to ingest %s: %s", fp.name, e)

        # Log to EventChain
        if ingested:
            try:
                from content.simulation.database.events import EventChain
                ec = EventChain()
                ec.log(
                    "media_ingested",
                    actor="housekeeping",
                    payload={"count": len(ingested), "types": [i["type"] for i in ingested]},
                    summary=f"Ingested {len(ingested)} new media files",
                )
            except Exception:
                logger.debug("EventChain log for ingest failed")

        return ingested

    # ── Health Checks ─────────────────────────────────────────────────

    def check_services(self) -> Dict[str, Dict]:
        """Check health of all external services."""
        import requests

        services = {
            "lmstudio": {"url": "http://localhost:1234/api/v1/models", "status": "unknown"},
            "comfyui": {"url": "http://127.0.0.1:8188/system_stats", "status": "unknown"},
            "tts": {"url": "http://localhost:8600/health", "status": "unknown"},
            "mcp_bridge": {"url": "http://localhost:8601/health", "status": "unknown"},
        }

        for name, info in services.items():
            try:
                r = requests.get(info["url"], timeout=3)
                if r.status_code == 200:
                    info["status"] = "healthy"
                    info["response_ms"] = r.elapsed.total_seconds() * 1000
                else:
                    info["status"] = f"error ({r.status_code})"
            except requests.ConnectionError:
                info["status"] = "offline"
            except Exception as e:
                info["status"] = f"error: {e}"

        self._results["services"] = services
        return services

    # ── DB Integrity ──────────────────────────────────────────────────

    def check_integrity(self) -> Dict:
        """Find orphan records and orphan files."""
        result = {"orphan_records": [], "orphan_files": [], "total_records": 0, "total_files": 0}

        try:
            from content.simulation.database.db import Database
            db = Database()
        except Exception as e:
            result["error"] = str(e)
            return result

        # Get all DB records
        records = []
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, filepath, type FROM media")
                records = cursor.fetchall()
        except Exception:
            logger.warning("Could not query media records for integrity check")

        result["total_records"] = len(records)

        # Check each record has a file
        for rec_id, filepath, media_type in records:
            if filepath and not Path(filepath).exists():
                result["orphan_records"].append({
                    "id": rec_id, "filepath": filepath, "type": media_type
                })

        # Check for files not in DB
        known_paths = {r[1] for r in records}
        file_count = 0
        for folder_key, folder_path in MEDIA_DIRS.items():
            if not folder_path.exists():
                continue
            for fp in folder_path.iterdir():
                if not fp.is_file():
                    continue
                file_count += 1
                fp_str = str(fp)
                if fp_str not in known_paths:
                    result["orphan_files"].append({
                        "filepath": fp_str,
                        "name": fp.name,
                        "folder": folder_key,
                    })

        result["total_files"] = file_count
        self._results["integrity"] = result
        return result

    # ── Cleanup ───────────────────────────────────────────────────────

    def cleanup_temp_files(self, max_age_hours: int = 24) -> int:
        """Remove temp/stale files older than max_age_hours."""
        removed = 0
        cutoff = time.time() - (max_age_hours * 3600)

        # Clean __pycache__ dirs
        for cache_dir in _PROJECT_ROOT.rglob("__pycache__"):
            for f in cache_dir.iterdir():
                if f.stat().st_mtime < cutoff:
                    try:
                        f.unlink()
                        removed += 1
                    except Exception:
                        pass

        return removed

    # ── Full Run ──────────────────────────────────────────────────────

    def run_all(self, character_id: str = "default") -> Dict:
        """Run all housekeeping tasks and return report."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "services": {},
            "integrity": {},
            "ingested": [],
            "cleaned": 0,
        }

        print("🏠 CosySim Housekeeping")
        print("=" * 50)

        # 1. Service health
        print("\n🔍 Checking services...")
        report["services"] = self.check_services()
        for name, info in report["services"].items():
            icon = "✅" if info["status"] == "healthy" else "❌"
            ms = f" ({info.get('response_ms', 0):.0f}ms)" if "response_ms" in info else ""
            print(f"  {icon} {name}: {info['status']}{ms}")

        # 2. DB integrity
        print("\n🗄️  Checking database integrity...")
        report["integrity"] = self.check_integrity()
        integrity = report["integrity"]
        print(f"  Records: {integrity['total_records']} | Files: {integrity['total_files']}")
        if integrity["orphan_records"]:
            print(f"  ⚠️  {len(integrity['orphan_records'])} orphan records (file missing)")
        if integrity["orphan_files"]:
            print(f"  ⚠️  {len(integrity['orphan_files'])} unregistered files")
        if not integrity["orphan_records"] and not integrity["orphan_files"]:
            print("  ✅ All clean")

        # 3. Media ingest
        print("\n📥 Scanning for new media...")
        report["ingested"] = self.ingest_new_media(character_id)
        if report["ingested"]:
            print(f"  ✅ Ingested {len(report['ingested'])} new files")
            for item in report["ingested"]:
                print(f"     {item['type']}: {item['name']}")
        else:
            print("  No new files found")

        # 4. Cleanup
        print("\n🧹 Cleanup...")
        report["cleaned"] = self.cleanup_temp_files()
        print(f"  Removed {report['cleaned']} stale cache files")

        print(f"\n{'=' * 50}")
        print("✅ Housekeeping complete")

        return report

    def watch(self, interval: int = 60, character_id: str = "default"):
        """Run housekeeping in a loop."""
        print(f"👀 Watching every {interval}s (Ctrl+C to stop)")
        try:
            while True:
                self.run_all(character_id)
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n🛑 Housekeeping stopped")


# ── CLI entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="CosySim Housekeeping")
    parser.add_argument("--watch", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=60, help="Watch interval (seconds)")
    parser.add_argument("--character", default="default", help="Character ID for media ingest")
    args = parser.parse_args()

    hk = HousekeepingService()
    if args.watch:
        hk.watch(args.interval, args.character)
    else:
        hk.run_all(args.character)
