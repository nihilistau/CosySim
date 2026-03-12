"""Deduplication filter for news items with SQLite-backed persistence.

Fingerprints are stored in a local SQLite database so dedup state survives
process restarts.  A configurable retention window automatically prunes
fingerprints older than *retention_days* (default 30).

The public API is unchanged from the original in-memory implementation:
``filter()``, ``mark_seen()``, ``get_seen_fingerprints()``.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional, Set

from engine.nexus.news.news_models import NewsItem
from engine.paths import DATA_DIR

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = DATA_DIR / "news_dedup.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_fingerprints (
    fingerprint TEXT PRIMARY KEY,
    first_seen  REAL NOT NULL,
    category    TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_seen_ts ON seen_fingerprints(first_seen);
"""


def _fingerprint(item: NewsItem) -> str:
    """URL + normalised title hash — 16-char hex digest."""
    key = item.url + item.title.lower().strip()
    return hashlib.md5(key.encode()).hexdigest()[:16]


class DedupFilter:
    """Deduplicates news items with SQLite-backed fingerprint storage.

    On construction the filter loads all non-expired fingerprints into an
    in-memory set for O(1) lookup, then writes new fingerprints back to
    the database on every ``filter()`` call.

    Args:
        db_path: Path to the SQLite file.  Defaults to ``data/news_dedup.db``.
        retention_days: How many days to keep fingerprints before pruning.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        retention_days: int = 30,
    ) -> None:
        self._path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._seen: Set[str] = set()

        self._init_db()
        self._prune_expired()
        self._load_from_db()

    # ── SQLite helpers ──────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Create a new connection (safe for the calling thread)."""
        conn = sqlite3.connect(str(self._path), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _load_from_db(self) -> None:
        """Load all active fingerprints into the in-memory set."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT fingerprint FROM seen_fingerprints"
            ).fetchall()
            with self._lock:
                self._seen.update(row[0] for row in rows)
            logger.debug("DedupFilter: loaded %d fingerprints from DB", len(rows))
        finally:
            conn.close()

    def _prune_expired(self) -> None:
        """Remove fingerprints older than the retention window."""
        cutoff = time.time() - (self._retention_days * 86400)
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "DELETE FROM seen_fingerprints WHERE first_seen < ?",
                (cutoff,),
            )
            pruned = cur.rowcount
            conn.commit()
            if pruned:
                logger.info("DedupFilter: pruned %d expired fingerprints", pruned)
        finally:
            conn.close()

    def _persist_fingerprints(
        self,
        fingerprints: List[str],
        category: str = "",
    ) -> None:
        """Batch-insert new fingerprints into the database."""
        if not fingerprints:
            return
        now = time.time()
        conn = self._get_conn()
        try:
            conn.executemany(
                "INSERT OR IGNORE INTO seen_fingerprints "
                "(fingerprint, first_seen, category) VALUES (?, ?, ?)",
                [(fp, now, category) for fp in fingerprints],
            )
            conn.commit()
        finally:
            conn.close()

    # ── Public API (unchanged) ──────────────────────────────────────

    def filter(self, items: List[NewsItem]) -> List[NewsItem]:
        """Return only unseen items; persists new fingerprints to DB."""
        fresh: List[NewsItem] = []
        new_fps: List[str] = []
        categories: dict[str, str] = {}

        for item in items:
            fp = _fingerprint(item)
            item.fingerprint = fp
            with self._lock:
                if fp not in self._seen:
                    self._seen.add(fp)
                    fresh.append(item)
                    new_fps.append(fp)
                    categories[fp] = item.category

        if new_fps:
            self._persist_fingerprints(
                new_fps,
                category=categories.get(new_fps[0], ""),
            )

        logger.info("DedupFilter: %d/%d items are fresh", len(fresh), len(items))
        return fresh

    def mark_seen(self, fingerprints: List[str]) -> None:
        """Pre-seed seen set (e.g. from external persistence)."""
        with self._lock:
            self._seen.update(fingerprints)
        self._persist_fingerprints(fingerprints)

    def get_seen_fingerprints(self) -> List[str]:
        """Return all currently-tracked fingerprints."""
        with self._lock:
            return list(self._seen)

    def count(self) -> int:
        """Total fingerprints currently tracked (in-memory)."""
        with self._lock:
            return len(self._seen)

    def prune(self) -> int:
        """Manually trigger pruning.  Returns number of fingerprints removed."""
        cutoff = time.time() - (self._retention_days * 86400)
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "DELETE FROM seen_fingerprints WHERE first_seen < ?",
                (cutoff,),
            )
            pruned = cur.rowcount
            conn.commit()
        finally:
            conn.close()

        if pruned:
            # Reload in-memory set from DB after prune
            new_set: Set[str] = set()
            conn2 = self._get_conn()
            try:
                rows = conn2.execute(
                    "SELECT fingerprint FROM seen_fingerprints"
                ).fetchall()
                new_set.update(row[0] for row in rows)
            finally:
                conn2.close()
            with self._lock:
                self._seen = new_set
            logger.info("DedupFilter: pruned %d fingerprints", pruned)
        return pruned
