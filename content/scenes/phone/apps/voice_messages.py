"""
VoiceMessagesApp — Gallery view for voice messages (phone scene)

Queries the `media` table for ``type = 'voice'`` records and returns
card-ready dicts for the phone UI.  Accessed via the phone scene route
``GET /api/voice-messages/list``.
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


def _fmt_duration(seconds: int) -> str:
    """Convert integer seconds to 'M:SS' display string."""
    if seconds <= 0:
        return "0:00"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


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


class VoiceMessagesApp:
    """
    Backend for the Voice Messages gallery screen.

    Provides a list of all voice messages stored in the media table,
    formatted as card dicts ready for the phone UI to render. Each card
    includes:
      - ``id``             — media row PK
      - ``filename``       — bare filename of the audio file (.wav / .mp3)
      - ``url``            — stream URL  (``/api/voice/download/<filename>``)
      - ``title``          — agent-generated title stored in metadata, or excerpt
      - ``duration``       — length in seconds (int)
      - ``duration_display`` — formatted "M:SS" string
      - ``mood``           — mood tag e.g. "happy", "shy"
      - ``text``           — transcript / original text
      - ``sender``         — "character" | "user"
      - ``timestamp``      — raw ISO string from DB
      - ``timestamp_display`` — formatted human-readable string
    """

    def __init__(self, db: 'Database') -> None:
        self.db = db

    # ──────────────────────────────────────────────────────── public API ──

    def get_list(self, character_id: str, limit: int = 50) -> List[Dict]:
        """
        Return voice messages for a character, newest first.

        Args:
            character_id: Active character's DB id.
            limit: Maximum rows to return.

        Returns:
            List of card dicts (empty list on any error).
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, filepath, metadata, timestamp
                    FROM   media
                    WHERE  character_id = ? AND type = 'voice'
                    ORDER  BY timestamp DESC
                    LIMIT  ?
                    """,
                    (character_id, limit),
                )
                return [self._row_to_card(row) for row in cursor.fetchall()]
        except Exception as exc:
            logger.warning("VoiceMessagesApp.get_list error: %s", exc)
            return []

    def get_item(self, media_id: str) -> Optional[Dict]:
        """
        Return a single voice message card by its media.id.

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
            logger.warning("VoiceMessagesApp.get_item error: %s", exc)
        return None

    # ─────────────────────────────────────────────────────────── helpers ──

    def _row_to_card(self, row) -> Dict:
        media_id, filepath, meta_raw, ts = row
        meta = _parse_meta(meta_raw)

        fp = Path(filepath) if filepath else None
        filename = fp.name if fp else ""

        # Title: prefer agent-generated title stored in meta, else transcript excerpt
        title = (
            meta.get("title")
            or (meta.get("text") or "")[:60].strip()
            or "Voice Message"
        )

        duration = int(meta.get("duration") or 0)

        return {
            "id":               media_id,
            "filename":         filename,
            "url":              f"/api/voice/download/{filename}" if filename else "",
            "title":            title,
            "duration":         duration,
            "duration_display": _fmt_duration(duration),
            "mood":             meta.get("mood", ""),
            "text":             meta.get("text", ""),
            "sender":           meta.get("sender", "character"),
            "timestamp":        ts or "",
            "timestamp_display": _fmt_ts(ts),
        }
