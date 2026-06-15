"""GlobalCommsLog — single source of truth for ALL communication in CosySim.

This module provides a queryable, append-only log of every communication that
flows through the simulation: phone DMs and group chats, NPC-to-NPC messages,
autotexts, left-messages, and system notices. It is the backbone that later
features consume:

* the Executive Suite Mail app (reads/queries threads),
* sub-project 3 — phone hacking (reads intercepted comms, marks them observed),
* sub-project 4 — the Oracle "sees all" (full visibility over every entry).

Design notes
------------
* Storage is a single SQLite table (``comms_log``) at a path resolved from
  ``get_config().get("comms.log.db_path", ...)`` under the project ``data/``
  directory — never a hardcoded absolute path.
* WAL mode + a thread lock make concurrent writes safe: the phone ticker, NPC
  scheduler, and interceptors will all write from different threads.
* A comms-log failure must NEVER break a message send. All DB operations are
  wrapped: errors are surfaced via ``logger.error`` in the Oracle log format
  (``[comms_log] ... (operation=...)``) but do not propagate to callers.
* Imports are kept minimal (stdlib + ``engine.config`` + ``engine.paths``) so
  this module is safe to import in environments without Flask.

Usage::

    from engine.world.comms_log import get_comms_log

    cl = get_comms_log()
    rid = cl.log("phone_dm", "char-aria", ["player"], "Hey, you up?")
    recent = cl.recent(20)
    convo = cl.thread("thread-abc")

Version: v1.62.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.62.0 [2026-06-15] — Initial GlobalCommsLog backbone (CB-T1): SQLite
                            append-only log, singleton accessor, query/thread/
                            about/mark_observed/recent/count/prune API.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════

_DEFAULT_DB_REL = "data/comms_log.db"   # relative to project root (config default)
_DEFAULT_MAX_ROWS = 50000               # fallback prune cap if config missing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comms_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,
    channel       TEXT,
    thread_id     TEXT,
    sender_id     TEXT,
    recipient_ids TEXT,
    content       TEXT,
    kind          TEXT,
    mood          TEXT,
    metadata      TEXT,
    observed_by   TEXT    DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_comms_ts        ON comms_log(ts);
CREATE INDEX IF NOT EXISTS idx_comms_thread    ON comms_log(thread_id);
CREATE INDEX IF NOT EXISTS idx_comms_sender    ON comms_log(sender_id);
"""

_COLUMNS = (
    "id", "ts", "channel", "thread_id", "sender_id", "recipient_ids",
    "content", "kind", "mood", "metadata", "observed_by",
)


# ══════════════════════════════════════════════════════════════════════
#  GLOBAL COMMS LOG
# ══════════════════════════════════════════════════════════════════════


class GlobalCommsLog:
    """Append-only, queryable SQLite log of every communication in CosySim.

    The log is the single source of truth consumed by the Mail app, phone
    hacking, and the Oracle. Writes are thread-safe (WAL + a process-level
    lock); DB errors are logged in Oracle format and swallowed so a logging
    failure can never break a message send.

    Attributes:
        path: Absolute filesystem path to the SQLite database.
    """

    def __init__(self, path: Optional[str | Path] = None) -> None:
        """Initialize the log, creating the schema if needed.

        Args:
            path: Explicit database path. When ``None`` the path is resolved
                from ``get_config().get("comms.log.db_path", ...)`` relative to
                the project ``data/`` directory. Tests should pass an explicit
                path so they never touch real data.
        """
        self.path: Path = self._resolve_path(path)
        self._lock = threading.Lock()
        self._init_db()

    # ── path / connection helpers ─────────────────────────────────────

    @staticmethod
    def _resolve_path(path: Optional[str | Path]) -> Path:
        """Resolve the database path from an explicit value or config.

        Args:
            path: Explicit path, or ``None`` to use config/default.

        Returns:
            Absolute :class:`~pathlib.Path` to the SQLite database.
        """
        if path is not None:
            return Path(path)
        from engine.paths import ROOT
        rel = _DEFAULT_DB_REL
        try:
            from engine.config import get_config
            rel = get_config().get("comms.log.db_path", _DEFAULT_DB_REL)
        except Exception as exc:  # config optional in minimal builds
            logger.error(
                "[comms_log] config lookup failed, using default db_path (operation=resolve_path): %s",
                exc,
            )
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        return candidate

    def _connect(self) -> sqlite3.Connection:
        """Open a WAL-enabled connection with row access by name.

        Returns:
            A configured :class:`sqlite3.Connection`.
        """
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error as exc:
            logger.error("[comms_log] PRAGMA setup failed (operation=connect): %s", exc)
        return conn

    def _init_db(self) -> None:
        """Create the database file, directory, and schema if absent."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self._connect() as conn:
                conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            logger.error("[comms_log] schema init failed (operation=init_db): %s", exc)

    @staticmethod
    def _max_rows_default() -> int:
        """Return the configured prune cap, falling back to a constant.

        Returns:
            The ``comms.log.max_rows`` config value or the module default.
        """
        try:
            from engine.config import get_config
            return int(get_config().get("comms.log.max_rows", _DEFAULT_MAX_ROWS))
        except Exception:
            return _DEFAULT_MAX_ROWS

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Deserialize a DB row into a plain dict with parsed JSON fields.

        Args:
            row: A :class:`sqlite3.Row` from the ``comms_log`` table.

        Returns:
            A dict with ``recipient_ids``/``observed_by`` as lists and
            ``metadata`` as a dict.
        """
        d = {k: row[k] for k in _COLUMNS}
        d["recipient_ids"] = _json_loads(d.get("recipient_ids"), default=[])
        d["observed_by"] = _json_loads(d.get("observed_by"), default=[])
        d["metadata"] = _json_loads(d.get("metadata"), default={})
        return d

    # ── write API ─────────────────────────────────────────────────────

    def log(
        self,
        channel: str,
        sender_id: str,
        recipient_ids: Sequence[str],
        content: str,
        *,
        thread_id: Optional[str] = None,
        kind: str = "message",
        mood: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ts: Optional[str] = None,
    ) -> int:
        """Append one communication entry to the log.

        Args:
            channel: Logical channel, e.g. ``'phone_dm'``, ``'phone_group'``,
                ``'npc_dm'``, ``'npc_group'``, ``'system'``.
            sender_id: Identifier of the sender.
            recipient_ids: Recipient identifiers (serialized as a JSON list).
            content: The message body.
            thread_id: Optional conversation/thread identifier.
            kind: Entry kind, e.g. ``'message'``, ``'autotext'``,
                ``'left_message'``, ``'system'``.
            mood: Optional mood tag associated with the message.
            metadata: Optional arbitrary metadata (serialized as JSON).
            ts: ISO-8601 timestamp. When ``None``, ``datetime.now().isoformat()``
                is used (see module note on the time approach).

        Returns:
            The new row id, or ``-1`` if the write failed (never raises).
        """
        ts = ts or datetime.now().isoformat()
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO comms_log "
                    "(ts, channel, thread_id, sender_id, recipient_ids, content, "
                    " kind, mood, metadata, observed_by) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ts,
                        channel,
                        thread_id,
                        sender_id,
                        json.dumps(list(recipient_ids)),
                        content,
                        kind,
                        mood,
                        json.dumps(metadata or {}),
                        json.dumps([]),
                    ),
                )
                return int(cur.lastrowid)
        except sqlite3.Error as exc:
            logger.error(
                "[comms_log] write failed (operation=log, channel=%s, sender=%s, thread=%s): %s",
                channel, sender_id, thread_id, exc,
            )
            return -1

    def mark_observed(self, entry_id: int, observer_id: str) -> bool:
        """Record that ``observer_id`` has seen entry ``entry_id``.

        Used later by phone hacking and the Oracle. Idempotent: an observer is
        only appended once.

        Args:
            entry_id: The ``comms_log`` row id.
            observer_id: Identifier of the observer to append.

        Returns:
            ``True`` if the row was updated (or the observer was already
            present), ``False`` on failure or unknown id.
        """
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT observed_by FROM comms_log WHERE id = ?", (entry_id,)
                ).fetchone()
                if row is None:
                    logger.error(
                        "[comms_log] mark_observed: unknown id (operation=mark_observed, id=%s)",
                        entry_id,
                    )
                    return False
                observers = _json_loads(row["observed_by"], default=[])
                if observer_id in observers:
                    return True
                observers.append(observer_id)
                conn.execute(
                    "UPDATE comms_log SET observed_by = ? WHERE id = ?",
                    (json.dumps(observers), entry_id),
                )
                return True
        except sqlite3.Error as exc:
            logger.error(
                "[comms_log] mark_observed failed (operation=mark_observed, id=%s, observer=%s): %s",
                entry_id, observer_id, exc,
            )
            return False

    def prune(self, max_rows: Optional[int] = None) -> int:
        """Cap table growth by deleting the oldest rows beyond ``max_rows``.

        Args:
            max_rows: Maximum rows to retain. When ``None``, uses
                ``comms.log.max_rows`` from config (default 50000).

        Returns:
            The number of rows deleted (0 on no-op or failure).
        """
        cap = max_rows if max_rows is not None else self._max_rows_default()
        try:
            with self._lock, self._connect() as conn:
                total = conn.execute("SELECT COUNT(*) FROM comms_log").fetchone()[0]
                if total <= cap:
                    return 0
                # Keep the newest `cap` rows (highest ids); delete the rest.
                cur = conn.execute(
                    "DELETE FROM comms_log WHERE id NOT IN "
                    "(SELECT id FROM comms_log ORDER BY id DESC LIMIT ?)",
                    (cap,),
                )
                deleted = cur.rowcount
                logger.info(
                    "[comms_log] pruned rows (operation=prune, deleted=%s, cap=%s)",
                    deleted, cap,
                )
                return int(deleted)
        except sqlite3.Error as exc:
            logger.error("[comms_log] prune failed (operation=prune, cap=%s): %s", cap, exc)
            return 0

    # ── read API ──────────────────────────────────────────────────────

    def query(
        self,
        *,
        since: Optional[str] = None,
        channel: Optional[str] = None,
        participants: Optional[Sequence[str]] = None,
        sender_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query the log with optional filters, newest-first.

        Args:
            since: Only return entries with ``ts >= since`` (ISO-8601).
            channel: Restrict to a single channel.
            participants: Match entries where any of these ids is the sender
                OR appears in ``recipient_ids``.
            sender_id: Restrict to a single sender.
            thread_id: Restrict to a single thread.
            limit: Maximum number of rows to return.

        Returns:
            A list of deserialized entry dicts ordered newest-first.
        """
        clauses: List[str] = []
        params: List[Any] = []
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since)
        if channel is not None:
            clauses.append("channel = ?")
            params.append(channel)
        if sender_id is not None:
            clauses.append("sender_id = ?")
            params.append(sender_id)
        if thread_id is not None:
            clauses.append("thread_id = ?")
            params.append(thread_id)
        if participants:
            sub: List[str] = []
            for pid in participants:
                # sender match OR id present in the JSON recipient list
                sub.append("sender_id = ?")
                params.append(pid)
                sub.append("recipient_ids LIKE ?")
                params.append(f'%"{pid}"%')
            clauses.append("(" + " OR ".join(sub) + ")")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM comms_log{where} ORDER BY ts DESC, id DESC LIMIT ?"
        params.append(int(limit))
        return self._fetch(sql, params, operation="query")

    def thread(self, thread_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        """Return all entries in a thread in chronological order.

        Args:
            thread_id: The thread identifier.
            limit: Maximum number of rows to return.

        Returns:
            A list of deserialized entry dicts ordered oldest-first.
        """
        sql = (
            "SELECT * FROM comms_log WHERE thread_id = ? "
            "ORDER BY ts ASC, id ASC LIMIT ?"
        )
        return self._fetch(sql, [thread_id, int(limit)], operation="thread")

    def about(self, character_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Return entries involving or mentioning a character, newest-first.

        Matches when the character is the sender, is among the recipients, or
        its id appears in the message ``content``.

        Args:
            character_id: The character identifier to search for.
            limit: Maximum number of rows to return.

        Returns:
            A list of deserialized entry dicts ordered newest-first.
        """
        sql = (
            "SELECT * FROM comms_log WHERE "
            "sender_id = ? OR recipient_ids LIKE ? OR content LIKE ? "
            "ORDER BY ts DESC, id DESC LIMIT ?"
        )
        params = [
            character_id,
            f'%"{character_id}"%',
            f"%{character_id}%",
            int(limit),
        ]
        return self._fetch(sql, params, operation="about")

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent entries, newest-first.

        Args:
            limit: Maximum number of rows to return.

        Returns:
            A list of deserialized entry dicts ordered newest-first.
        """
        sql = "SELECT * FROM comms_log ORDER BY id DESC LIMIT ?"
        return self._fetch(sql, [int(limit)], operation="recent")

    def count(self) -> int:
        """Return the total number of entries in the log.

        Returns:
            The row count, or ``0`` on failure.
        """
        try:
            with self._lock, self._connect() as conn:
                return int(conn.execute("SELECT COUNT(*) FROM comms_log").fetchone()[0])
        except sqlite3.Error as exc:
            logger.error("[comms_log] count failed (operation=count): %s", exc)
            return 0

    # ── internal fetch ────────────────────────────────────────────────

    def _fetch(
        self, sql: str, params: Sequence[Any], *, operation: str
    ) -> List[Dict[str, Any]]:
        """Execute a SELECT and deserialize the rows, logging errors.

        Args:
            sql: The SELECT statement.
            params: Bound parameters.
            operation: Operation name for Oracle-format error logs.

        Returns:
            A list of deserialized rows; empty on failure.
        """
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(sql, tuple(params)).fetchall()
                return [self._row_to_dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error("[comms_log] read failed (operation=%s): %s", operation, exc)
            return []


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════


def _json_loads(value: Any, *, default: Any) -> Any:
    """Best-effort JSON decode, returning ``default`` on any failure.

    Args:
        value: The raw value (str or already-decoded).
        default: Value to return when decoding fails or input is empty.

    Returns:
        The decoded object or ``default``.
    """
    if value is None or value == "":
        return default
    if not isinstance(value, (str, bytes, bytearray)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


# ══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL SINGLETON
# ══════════════════════════════════════════════════════════════════════

_comms_log: Optional[GlobalCommsLog] = None
_singleton_lock = threading.Lock()


def get_comms_log() -> GlobalCommsLog:
    """Return the process-wide :class:`GlobalCommsLog` singleton.

    The singleton uses the config/default database path. Tests that need
    isolation should construct ``GlobalCommsLog(path=...)`` directly instead.

    Returns:
        The shared :class:`GlobalCommsLog` instance.
    """
    global _comms_log
    if _comms_log is None:
        with _singleton_lock:
            if _comms_log is None:
                _comms_log = GlobalCommsLog()
    return _comms_log
