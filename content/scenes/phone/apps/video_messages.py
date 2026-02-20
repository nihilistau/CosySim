"""
VideoMessagesApp — Gallery view for video messages (phone scene)

Queries the `media` table for ``type = 'video_message'`` records and returns
card-ready dicts for the phone UI.  Accessed via the phone scene route
``GET /api/video-messages/list``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from content.simulation.database.db import Database

logger = logging.getLogger(__name__)


def _fmt_ts(ts: Optional[str]) -> str:
    """Return a human-readable timestamp string, gracefully handles None."""
    if not ts:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%b %d, %Y  %H:%M")
    except Exception:
        return str(ts)


def _parse_meta(raw) -> Dict:
    """Safely coerce DB metadata column to a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


class VideoMessagesApp:
    """
    Backend for the Video Messages gallery screen.

    Provides a list of all video messages stored in the media table,
    formatted as card dicts ready for the phone UI to render. Each card
    includes:
      - ``id``             — media row PK
      - ``filename``       — bare filename of the .mp4 file
      - ``url``            — stream URL  (``/api/video-message/download/<filename>``)
      - ``title``          — agent-generated title stored in metadata, or excerpt
      - ``duration``       — length in seconds (int)
      - ``mood``           — mood tag e.g. "happy", "shy"
      - ``text``           — script / transcript excerpt
      - ``sender``         — "character" | "user"
      - ``timestamp``      — raw ISO string from DB
      - ``timestamp_display`` — formatted human-readable string
    """

    def __init__(self, db: 'Database') -> None:
        self.db = db

    # ──────────────────────────────────────────────────────── public API ──

    def get_list(self, character_id: str, limit: int = 50) -> List[Dict]:
        """
        Return video messages for a character, newest first.

        Also scans media directories for .mp4 files not yet tracked in the DB
        (offline ingest: drop files in the folder and they appear).

        Args:
            character_id: Active character's DB id.
            limit: Maximum rows to return.

        Returns:
            List of card dicts (empty list on any error).
        """
        db_cards: List[Dict] = []
        db_filenames: set = set()
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, filepath, metadata, timestamp
                    FROM   media
                    WHERE  character_id = ? AND type = 'video_message'
                    ORDER  BY timestamp DESC
                    LIMIT  ?
                    """,
                    (character_id, limit),
                )
                db_cards = [self._row_to_card(row) for row in cursor.fetchall()]
                db_filenames = {c["filename"] for c in db_cards if c["filename"]}
        except Exception as exc:
            logger.warning("VideoMessagesApp.get_list DB error: %s", exc)

        # Filesystem scan — pick up files dropped in the media dirs
        content_root = Path(__file__).parent.parent.parent.parent
        scan_dirs = [
            content_root / "simulation" / "media" / "video",
            Path(__file__).parent.parent.parent / "media" / "video",
        ]
        fs_cards: List[Dict] = []
        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue
            for f in sorted(scan_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
                if f.name in db_filenames:
                    continue
                db_filenames.add(f.name)  # deduplicate across dirs
                fs_cards.append({
                    "id":               f.stem,
                    "filename":         f.name,
                    "url":              f"/api/video-message/download/{f.name}",
                    "title":            f.stem,
                    "duration":         0,
                    "mood":             "",
                    "text":             "",
                    "sender":           "character",
                    "timestamp":        "",
                    "timestamp_display": _fmt_ts(None),
                    "source":           "filesystem",
                })

        combined = db_cards + fs_cards
        return combined[:limit]

    def get_item(self, media_id: str) -> Optional[Dict]:
        """
        Return a single video message card by its media.id.

        Returns None if not found or on error.
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, filepath, metadata, timestamp FROM media WHERE id = ?",
                    (media_id,),
                )
                row = cursor.fetchone()
                if row:
                    return self._row_to_card(row)
        except Exception as exc:
            logger.warning("VideoMessagesApp.get_item error: %s", exc)
        return None

    # ─────────────────────────────────────────────────────────── helpers ──

    def _row_to_card(self, row) -> Dict:
        media_id, filepath, meta_raw, ts = row
        meta = _parse_meta(meta_raw)

        fp = Path(filepath) if filepath else None
        filename = fp.name if fp else ""

        # Title: prefer agent-generated title stored in meta, else truncated script
        title = (
            meta.get("title")
            or (meta.get("text") or "")[:60].strip()
            or "Video Message"
        )

        return {
            "id":                media_id,
            "filename":          filename,
            "url":               f"/api/video-message/download/{filename}" if filename else "",
            "title":             title,
            "duration":          int(meta.get("duration") or 0),
            "mood":              meta.get("mood", ""),
            "text":              meta.get("text", ""),
            "sender":            meta.get("sender", "character"),
            "timestamp":         ts or "",
            "timestamp_display": _fmt_ts(ts),
        }
