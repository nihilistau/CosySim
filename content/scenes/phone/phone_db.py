"""
Phone Scene v2 — Database Layer
================================
Manages phone-specific tables: threads, messages, read receipts.
Keeps character data in the main DB; only phone-conversation state lives here.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from engine.paths import DB_PHONE as _DB_PATH


class PhoneDB:
    """Lightweight SQLite wrapper for the phone scene."""

    def __init__(self, db_path: Optional[Path] = None):
        import sqlite3
        self._path = db_path or _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._sqlite3 = sqlite3
        self._dm_lock = threading.Lock()
        self._init_tables()

    # ─── connection ──────────────────────────────────────────────────

    @contextmanager
    def conn(self):
        c = self._sqlite3.connect(str(self._path))
        c.row_factory = self._sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    # ─── schema ───────────────────────────────────────────────────────

    def _init_tables(self) -> None:
        with self.conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS phone_threads (
                    id         TEXT PRIMARY KEY,
                    type       TEXT NOT NULL DEFAULT 'dm',
                    name       TEXT,
                    pinned     INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS phone_members (
                    thread_id    TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    joined_at    TEXT NOT NULL,
                    PRIMARY KEY (thread_id, character_id),
                    FOREIGN KEY (thread_id) REFERENCES phone_threads(id)
                );

                CREATE TABLE IF NOT EXISTS phone_messages (
                    id              TEXT PRIMARY KEY,
                    thread_id       TEXT NOT NULL,
                    sender_id       TEXT NOT NULL,
                    content         TEXT NOT NULL,
                    msg_type        TEXT NOT NULL DEFAULT 'text',
                    media_path      TEXT,
                    status          TEXT NOT NULL DEFAULT 'sent',
                    created_at      TEXT NOT NULL,
                    metadata        TEXT DEFAULT '{}',
                    response_id     TEXT,
                    conversation_id TEXT,
                    FOREIGN KEY (thread_id) REFERENCES phone_threads(id)
                );

                CREATE INDEX IF NOT EXISTS idx_msgs_thread ON phone_messages(thread_id, created_at);

                CREATE TABLE IF NOT EXISTS phone_reads (
                    thread_id       TEXT NOT NULL,
                    character_id    TEXT NOT NULL,
                    last_read_id    TEXT,
                    read_at         TEXT NOT NULL,
                    PRIMARY KEY (thread_id, character_id)
                );

                CREATE TABLE IF NOT EXISTS phone_game_sessions (
                    id           TEXT PRIMARY KEY,
                    thread_id    TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    session_type TEXT NOT NULL DEFAULT 'truth_or_dare',
                    state        TEXT NOT NULL DEFAULT '{}',
                    active       INTEGER DEFAULT 1,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL
                );
            """)

        # ── Migrations: add columns to existing DBs ─────────────────────
        with self.conn() as c:
            try:
                c.execute("ALTER TABLE phone_messages ADD COLUMN response_id TEXT")
            except Exception:
                pass  # Already exists
            try:
                c.execute("ALTER TABLE phone_messages ADD COLUMN conversation_id TEXT")
            except Exception:
                pass  # Already exists

        # ── News feed tables ──────────────────────────────────────────────
        with self.conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS phone_news_items (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL,
                    summary     TEXT NOT NULL DEFAULT '',
                    url         TEXT,
                    source_id   TEXT NOT NULL DEFAULT '',
                    category    TEXT NOT NULL DEFAULT '',
                    relevance   REAL NOT NULL DEFAULT 0.0,
                    markup      TEXT NOT NULL DEFAULT '',
                    is_read     INTEGER NOT NULL DEFAULT 0,
                    is_deleted  INTEGER NOT NULL DEFAULT 0,
                    feedback    INTEGER NOT NULL DEFAULT 0,
                    created_at  TEXT NOT NULL,
                    read_at     TEXT,
                    nexus_id    TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_news_created
                    ON phone_news_items(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_news_deleted
                    ON phone_news_items(is_deleted);
            """)

    # ─── thread helpers ──────────────────────────────────────────────

    def get_or_create_dm(self, char_id: str) -> str:
        """Return thread_id for a DM with *char_id*, creating one if needed.

        Uses a global lock to prevent concurrent requests from creating
        duplicate DM threads for the same character.
        """
        with self._dm_lock:
            with self.conn() as c:
                row = c.execute(
                    """SELECT m.thread_id FROM phone_members m
                       JOIN phone_members m2 ON m.thread_id = m2.thread_id
                       JOIN phone_threads t  ON m.thread_id = t.id
                       WHERE m.character_id=? AND m2.character_id='user'
                             AND t.type='dm'
                       LIMIT 1""",
                    (char_id,),
                ).fetchone()
                if row:
                    return row["thread_id"]
                tid = str(uuid.uuid4())
                now = datetime.now(timezone.utc).isoformat()
                c.execute(
                    "INSERT INTO phone_threads(id,type,created_at,updated_at)"
                    " VALUES(?,?,?,?)",
                    (tid, "dm", now, now),
                )
                for cid in (char_id, "user"):
                    c.execute(
                        "INSERT INTO phone_members(thread_id,character_id,joined_at)"
                        " VALUES(?,?,?)",
                        (tid, cid, now),
                    )
                return tid

    def create_group(self, name: str, member_ids: List[str]) -> str:
        """Create a group thread and return its id."""
        with self.conn() as c:
            tid = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            c.execute(
                "INSERT INTO phone_threads(id,type,name,created_at,updated_at) VALUES(?,?,?,?,?)",
                (tid, "group", name, now, now),
            )
            for cid in member_ids + ["user"]:
                if cid not in member_ids:  # avoid dup if caller included 'user'
                    continue
                c.execute(
                    "INSERT OR IGNORE INTO phone_members(thread_id,character_id,joined_at) VALUES(?,?,?)",
                    (tid, cid, now),
                )
            # always add user
            c.execute(
                "INSERT OR IGNORE INTO phone_members(thread_id,character_id,joined_at) VALUES(?,?,?)",
                (tid, "user", now),
            )
            return tid

    def list_threads(self) -> List[Dict]:
        """Return all threads with last message + unread count, newest first."""
        with self.conn() as c:
            threads = c.execute(
                "SELECT * FROM phone_threads ORDER BY updated_at DESC"
            ).fetchall()
            result = []
            for t in threads:
                tid = t["id"]
                members = [r["character_id"] for r in
                           c.execute("SELECT character_id FROM phone_members WHERE thread_id=?", (tid,)).fetchall()]
                last_msg = c.execute(
                    "SELECT * FROM phone_messages WHERE thread_id=? ORDER BY created_at DESC LIMIT 1",
                    (tid,),
                ).fetchone()
                read_row = c.execute(
                    "SELECT last_read_id FROM phone_reads WHERE thread_id=? AND character_id='user'",
                    (tid,),
                ).fetchone()
                last_read = read_row["last_read_id"] if read_row else None
                unread = c.execute(
                    """SELECT COUNT(*) as n FROM phone_messages
                       WHERE thread_id=? AND sender_id!='user'
                       AND (? IS NULL OR created_at > (
                           SELECT created_at FROM phone_messages WHERE id=? LIMIT 1
                       ))""",
                    (tid, last_read, last_read),
                ).fetchone()["n"] if last_read else c.execute(
                    "SELECT COUNT(*) as n FROM phone_messages WHERE thread_id=? AND sender_id!='user'",
                    (tid,),
                ).fetchone()["n"]
                result.append({
                    "id": tid,
                    "type": t["type"],
                    "name": t["name"],
                    "pinned": bool(t["pinned"]),
                    "members": [m for m in members if m != "user"],
                    # Return last message content as plain string so the JS
                    # thread-list preview renders correctly (not [object Object]).
                    "last_message": (
                        last_msg["content"] if last_msg else None
                    ),
                    "unread": unread,
                    "updated_at": t["updated_at"],
                })
            return result

    def get_thread(self, thread_id: str) -> Optional[Dict]:
        with self.conn() as c:
            t = c.execute("SELECT * FROM phone_threads WHERE id=?", (thread_id,)).fetchone()
            if not t:
                return None
            members = [r["character_id"] for r in
                       c.execute("SELECT character_id FROM phone_members WHERE thread_id=?", (thread_id,)).fetchall()]
            return {"id": t["id"], "type": t["type"], "name": t["name"],
                    "pinned": bool(t["pinned"]), "members": members}

    # ─── message helpers ─────────────────────────────────────────────

    def save_message(
        self, thread_id: str, sender_id: str, content: str,
        msg_type: str = "text", media_path: Optional[str] = None,
        metadata: Optional[Dict] = None,
        response_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict:
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.conn() as c:
            c.execute(
                """INSERT INTO phone_messages
                   (id, thread_id, sender_id, content, msg_type, media_path,
                    status, created_at, metadata, response_id, conversation_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (msg_id, thread_id, sender_id, content, msg_type,
                 media_path, "sent", now, json.dumps(metadata or {}),
                 response_id, conversation_id),
            )
            c.execute(
                "UPDATE phone_threads SET updated_at=? WHERE id=?",
                (now, thread_id),
            )
        return {"id": msg_id, "thread_id": thread_id, "sender_id": sender_id,
                "content": content, "msg_type": msg_type, "media_path": media_path,
                "status": "sent", "created_at": now, "metadata": metadata or {},
                "response_id": response_id, "conversation_id": conversation_id}

    def get_messages(
        self, thread_id: str, limit: int = 50, before: Optional[str] = None
    ) -> List[Dict]:
        with self.conn() as c:
            if before:
                rows = c.execute(
                    """SELECT * FROM phone_messages WHERE thread_id=? AND created_at < ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (thread_id, before, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    """SELECT * FROM phone_messages WHERE thread_id=?
                       ORDER BY created_at DESC LIMIT ?""",
                    (thread_id, limit),
                ).fetchall()
        msgs = [dict(r) for r in reversed(rows)]
        for m in msgs:
            try:
                m["metadata"] = json.loads(m.get("metadata") or "{}")
            except Exception:
                m["metadata"] = {}
        return msgs

    def get_last_response_id(self, thread_id: str) -> Optional[str]:
        """Get the last response_id for a thread (for stateful conversation resumption)."""
        with self.conn() as c:
            row = c.execute(
                """SELECT response_id FROM phone_messages
                   WHERE thread_id=? AND response_id IS NOT NULL
                   ORDER BY created_at DESC LIMIT 1""",
                (thread_id,),
            ).fetchone()
        return row["response_id"] if row else None

    def mark_read(self, thread_id: str, reader_id: str = "user") -> None:
        with self.conn() as c:
            last = c.execute(
                "SELECT id FROM phone_messages WHERE thread_id=? ORDER BY created_at DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
            if not last:
                return
            now = datetime.now(timezone.utc).isoformat()
            c.execute(
                """INSERT INTO phone_reads(thread_id, character_id, last_read_id, read_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(thread_id, character_id) DO UPDATE SET last_read_id=?, read_at=?""",
                (thread_id, reader_id, last["id"], now, last["id"], now),
            )

    def total_unread(self) -> int:
        """Count all unread messages for 'user' across all threads."""
        with self.conn() as c:
            n = c.execute(
                """SELECT COUNT(*) as n FROM phone_messages pm
                   WHERE pm.sender_id != 'user'
                   AND NOT EXISTS (
                     SELECT 1 FROM phone_reads pr
                     WHERE pr.thread_id = pm.thread_id AND pr.character_id = 'user'
                     AND pr.last_read_id = pm.id
                     OR (pr.last_read_id IS NOT NULL AND pm.created_at <= (
                         SELECT created_at FROM phone_messages WHERE id = pr.last_read_id LIMIT 1
                     ))
                   )""",
            ).fetchone()["n"]
        return n

    # ─── thread helpers ──────────────────────────────────────────────

    def get_thread_members(self, thread_id: str) -> List[str]:
        """Return list of character_id strings that are members of a thread."""
        with self.conn() as c:
            rows = c.execute(
                "SELECT character_id FROM phone_members WHERE thread_id=?",
                (thread_id,),
            ).fetchall()
        return [r["character_id"] for r in rows]

    def thread_unread(self, thread_id: str, reader_id: str = "user") -> int:
        """Count unread messages in a single thread for reader_id."""
        with self.conn() as c:
            row = c.execute(
                """SELECT COALESCE(last_read_id, '') as lrid FROM phone_reads
                   WHERE thread_id=? AND character_id=? LIMIT 1""",
                (thread_id, reader_id),
            ).fetchone()
            if not row:
                # Never read — all non-user messages are unread
                n = c.execute(
                    "SELECT COUNT(*) as n FROM phone_messages WHERE thread_id=? AND sender_id!=?",
                    (thread_id, reader_id),
                ).fetchone()["n"]
                return n
            lrid = row["lrid"]
            if not lrid:
                n = c.execute(
                    "SELECT COUNT(*) as n FROM phone_messages WHERE thread_id=? AND sender_id!=?",
                    (thread_id, reader_id),
                ).fetchone()["n"]
                return n
            n = c.execute(
                """SELECT COUNT(*) as n FROM phone_messages
                   WHERE thread_id=? AND sender_id!=?
                   AND created_at > (SELECT created_at FROM phone_messages WHERE id=?)""",
                (thread_id, reader_id, lrid),
            ).fetchone()["n"]
        return n

    # ─── game sessions ───────────────────────────────────────────────

    def create_game_session(self, thread_id: str, char_id: str,
                            session_type: str = "truth_or_dare") -> str:
        gid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.conn() as c:
            # Deactivate any existing session in same thread
            c.execute("UPDATE phone_game_sessions SET active=0 WHERE thread_id=?", (thread_id,))
            c.execute(
                """INSERT INTO phone_game_sessions(id,thread_id,character_id,state,active,created_at,updated_at)
                   VALUES(?,?,?,?,1,?,?)""",
                (gid, thread_id, char_id, json.dumps({"round": 0, "score": 0, "history": []}), now, now),
            )
        return gid

    def get_game_session(self, thread_id: str) -> Optional[Dict]:
        with self.conn() as c:
            row = c.execute(
                "SELECT * FROM phone_game_sessions WHERE thread_id=? AND active=1 ORDER BY created_at DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["state"] = json.loads(d["state"])
        except Exception:
            d["state"] = {}
        return d

    def update_game_state(self, session_id: str, state: Dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.conn() as c:
            c.execute(
                "UPDATE phone_game_sessions SET state=?, updated_at=? WHERE id=?",
                (json.dumps(state), now, session_id),
            )

    def end_game_session(self, session_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.conn() as c:
            c.execute(
                "UPDATE phone_game_sessions SET active=0, updated_at=? WHERE id=?",
                (now, session_id),
            )

    # ─── wipe ────────────────────────────────────────────────────────

    def wipe_messages(self) -> int:
        """Delete all phone messages and threads. Returns row count."""
        with self.conn() as c:
            n = c.execute("SELECT COUNT(*) as n FROM phone_messages").fetchone()["n"]
            c.execute("DELETE FROM phone_reads")
            c.execute("DELETE FROM phone_messages")
            c.execute("DELETE FROM phone_members")
            c.execute("DELETE FROM phone_game_sessions")
            c.execute("DELETE FROM phone_threads")
        return n

    # ─── news feed ────────────────────────────────────────────────────

    def upsert_news_item(
        self,
        item_id: str,
        title: str,
        summary: str,
        url: str,
        source_id: str,
        category: str,
        relevance: float,
        markup: str,
        nexus_id: str = "",
    ) -> bool:
        """Insert or update a news item. Returns True if new."""
        now = datetime.now(timezone.utc).isoformat()
        with self.conn() as c:
            existing = c.execute(
                "SELECT id FROM phone_news_items WHERE id=?", (item_id,)
            ).fetchone()
            if existing:
                return False
            c.execute(
                """INSERT INTO phone_news_items
                   (id, title, summary, url, source_id, category, relevance,
                    markup, created_at, nexus_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item_id, title, summary, url, source_id, category,
                 relevance, markup, now, nexus_id),
            )
        return True

    def get_news_feed(
        self,
        limit: int = 30,
        offset: int = 0,
        include_deleted: bool = False,
        unread_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get news feed items ordered by date descending."""
        with self.conn() as c:
            conditions = []
            if not include_deleted:
                conditions.append("is_deleted = 0")
            if unread_only:
                conditions.append("is_read = 0")
            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            rows = c.execute(
                f"SELECT * FROM phone_news_items {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_news_stats(self) -> Dict[str, Any]:
        """Get news feed stats."""
        with self.conn() as c:
            total = c.execute("SELECT COUNT(*) as n FROM phone_news_items WHERE is_deleted=0").fetchone()["n"]
            unread = c.execute("SELECT COUNT(*) as n FROM phone_news_items WHERE is_deleted=0 AND is_read=0").fetchone()["n"]
            liked = c.execute("SELECT COUNT(*) as n FROM phone_news_items WHERE feedback > 0").fetchone()["n"]
            disliked = c.execute("SELECT COUNT(*) as n FROM phone_news_items WHERE feedback < 0").fetchone()["n"]
        return {"total": total, "unread": unread, "liked": liked, "disliked": disliked}

    def set_news_read(self, item_id: str) -> None:
        """Mark a news item as read."""
        now = datetime.now(timezone.utc).isoformat()
        with self.conn() as c:
            c.execute(
                "UPDATE phone_news_items SET is_read=1, read_at=? WHERE id=?",
                (now, item_id),
            )

    def set_news_feedback(self, item_id: str, feedback: int) -> None:
        """Set feedback on a news item. +1 = thumbs up, -1 = thumbs down, 0 = neutral."""
        with self.conn() as c:
            c.execute(
                "UPDATE phone_news_items SET feedback=? WHERE id=?",
                (max(-1, min(1, feedback)), item_id),
            )

    def delete_news_item(self, item_id: str) -> None:
        """Soft-delete a news item."""
        with self.conn() as c:
            c.execute("UPDATE phone_news_items SET is_deleted=1 WHERE id=?", (item_id,))

    def get_feedback_summary(self) -> Dict[str, Any]:
        """Get summary of user feedback for tuning news scoring."""
        with self.conn() as c:
            # Liked sources
            liked_sources = c.execute(
                """SELECT source_id, COUNT(*) as cnt FROM phone_news_items
                   WHERE feedback > 0 GROUP BY source_id ORDER BY cnt DESC"""
            ).fetchall()
            # Disliked sources
            disliked_sources = c.execute(
                """SELECT source_id, COUNT(*) as cnt FROM phone_news_items
                   WHERE feedback < 0 GROUP BY source_id ORDER BY cnt DESC"""
            ).fetchall()
            # Liked categories
            liked_cats = c.execute(
                """SELECT category, COUNT(*) as cnt FROM phone_news_items
                   WHERE feedback > 0 GROUP BY category ORDER BY cnt DESC"""
            ).fetchall()
        return {
            "liked_sources": {r["source_id"]: r["cnt"] for r in liked_sources},
            "disliked_sources": {r["source_id"]: r["cnt"] for r in disliked_sources},
            "liked_categories": {r["category"]: r["cnt"] for r in liked_cats},
        }
