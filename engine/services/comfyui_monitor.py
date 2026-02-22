"""ComfyUI Output Folder Monitor — watches for new assets and routes them.

File-name identifier convention
================================
Files in the ComfyUI output folder are expected to follow the naming pattern::

    <TAG>_<optional-detail>_<timestamp>.<ext>

Recognised tags
---------------
* ``PHOTO``   → ``content/simulation/media/photo/``
* ``SELFIE``  → ``content/simulation/media/photo/``
* ``GALLERY`` → ``content/simulation/media/photo/``
* ``VIDEO``   → ``content/simulation/media/video/``
* ``VOICE``   → ``content/simulation/media/voice/``
* ``AVATAR``  → ``content/simulation/media/photo/avatars/``

If no recognised tag is found the file is moved to ``content/simulation/media/unknown/``.

The monitor also registers each ingested asset in the simulation database
(``asset_registry.db``) so it is discoverable from scenes.

Usage::

    from engine.services.comfyui_monitor import ComfyUIMonitor
    monitor = ComfyUIMonitor()
    monitor.start()   # non-blocking background thread
    monitor.stop()
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from threading import Thread, Event
from typing import Dict, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

# Tag → destination sub-path (relative to content/simulation/media/)
TAG_ROUTES: Dict[str, str] = {
    "PHOTO":   "photo",
    "SELFIE":  "photo",
    "GALLERY": "photo",
    "VIDEO":   "video",
    "VOICE":   "voice",
    "AVATAR":  "photo/avatars",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".avi"}
AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac"}
ALL_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS


def _extract_tag(filename: str) -> Optional[str]:
    """Return the recognised tag prefix or None."""
    upper = filename.upper()
    for tag in TAG_ROUTES:
        if upper.startswith(tag + "_"):
            return tag
    return None


def _guess_type(ext: str) -> str:
    ext = ext.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return "unknown"


class ComfyUIMonitor:
    """Watches the ComfyUI output folder for new files and ingests them."""

    def __init__(
        self,
        watch_dir: Optional[str] = None,
        media_root: Optional[str] = None,
        poll_interval: float = 2.0,
    ):
        cfg = get_config()
        self.watch_dir = Path(
            watch_dir or cfg.get("comfyui.output_dir", "C:/ComfyUI/output")
        )
        self.media_root = Path(
            media_root
            or str(Path(__file__).parent.parent.parent / "content" / "simulation" / "media")
        )
        self.poll_interval = poll_interval
        self._stop = Event()
        self._thread: Optional[Thread] = None
        self._seen: set = set()
        self._db_path = Path(__file__).parent.parent.parent / "asset_registry.db"

    # ── public API ────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the background watcher thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, daemon=True, name="comfyui-monitor")
        self._thread.start()
        logger.info("ComfyUI monitor started — watching %s", self.watch_dir)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("ComfyUI monitor stopped")

    # ── background loop ───────────────────────────────────────────────

    def _run(self) -> None:
        # Initialise _seen with existing files so we only process NEW ones
        if self.watch_dir.exists():
            self._seen = {p.name for p in self.watch_dir.iterdir() if p.is_file()}
        while not self._stop.is_set():
            try:
                self._poll()
            except Exception as exc:
                logger.error("ComfyUI monitor poll error: %s", exc)
            self._stop.wait(self.poll_interval)

    def _poll(self) -> None:
        if not self.watch_dir.exists():
            return
        for path in self.watch_dir.iterdir():
            if not path.is_file():
                continue
            if path.name in self._seen:
                continue
            if path.suffix.lower() not in ALL_EXTS:
                self._seen.add(path.name)
                continue
            # Skip files still being written (size hasn't stabilised)
            try:
                size1 = path.stat().st_size
                time.sleep(0.3)
                size2 = path.stat().st_size
                if size1 != size2:
                    continue  # still writing
            except OSError:
                continue
            self._seen.add(path.name)
            self._ingest(path)

    # ── ingest logic ──────────────────────────────────────────────────

    def _ingest(self, src: Path) -> None:
        tag = _extract_tag(src.name)
        sub = TAG_ROUTES.get(tag, "unknown") if tag else "unknown"
        dest_dir = self.media_root / sub
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / src.name
        if dest.exists():
            stem = src.stem + f"_{int(time.time())}"
            dest = dest_dir / (stem + src.suffix)

        try:
            shutil.move(str(src), str(dest))
        except Exception as exc:
            logger.error("ComfyUI monitor: move failed %s → %s: %s", src, dest, exc)
            return

        asset_type = _guess_type(src.suffix)
        asset_id = str(uuid.uuid4())
        logger.info(
            "ComfyUI monitor: ingested %s → %s (type=%s, tag=%s, id=%s)",
            src.name, dest, asset_type, tag or "none", asset_id,
        )

        # Register in asset_registry DB
        try:
            self._register_asset(asset_id, src.name, asset_type, tag, str(dest))
        except Exception as exc:
            logger.debug("Asset registration failed: %s", exc)

    def _register_asset(
        self, asset_id: str, original_name: str, asset_type: str,
        tag: Optional[str], dest_path: str,
    ) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monitored_assets (
                    id TEXT PRIMARY KEY,
                    original_name TEXT,
                    asset_type TEXT,
                    tag TEXT,
                    dest_path TEXT,
                    created_at TEXT
                )
            """)
            conn.execute(
                "INSERT INTO monitored_assets (id, original_name, asset_type, tag, dest_path, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (asset_id, original_name, asset_type, tag, dest_path,
                 datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()


# ── Singleton access ──────────────────────────────────────────────────

_monitor: Optional[ComfyUIMonitor] = None


def get_comfyui_monitor() -> ComfyUIMonitor:
    global _monitor
    if _monitor is None:
        _monitor = ComfyUIMonitor()
    return _monitor
