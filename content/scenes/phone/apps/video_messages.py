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
        Return video messages for a character, newest first.  Falls back to
        scanning the filesystem (simulation + content media folders) for any
        video files that are not present in the DB so offline ingest works.
        """
        try:
            cards: List[Dict] = []
            seen_filenames = set()

            # 1) DB-backed messages
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
                rows = cursor.fetchall()
                for row in rows:
                    cards.append(self._row_to_card(row))
                    fp = Path(row[1]) if row[1] else None
                    if fp:
                        seen_filenames.add(fp.name)

            # 2) Filesystem fallback (scan simulation/media/video and content/media/video)
            sim_dir = Path(__file__).parent.parent.parent.parent / "simulation" / "media" / "video"
            content_dir = Path(__file__).parent.parent.parent / "media" / "video"
            for vdir in (sim_dir, content_dir):
                if not vdir.exists():
                    continue
                for f in sorted(vdir.glob('*.mp4'), key=lambda p: p.stat().st_mtime, reverse=True):
                    if f.name in seen_filenames:
                        continue
                    cards.append({
                        'id': f.stem,
                        'filename': f.name,
                        'url': f"/api/video-message/download/{f.name}",
                        'title': f.stem.replace('_', ' '),
                        'duration': 0,
                        'mood': '',
                        'text': '',
                        'sender': 'filesystem',
                        'timestamp': __import__('datetime').datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                        'timestamp_display': _fmt_ts(__import__('datetime').datetime.fromtimestamp(f.stat().st_mtime).isoformat()),
                    })
                    seen_filenames.add(f.name)

            return cards[:limit]

        except Exception as exc:
            logger.warning("VideoMessagesApp.get_list error: %s", exc)
            return []

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
