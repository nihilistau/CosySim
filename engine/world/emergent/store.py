"""EmergentStore — the persistent sim store for the v1.63 Emergent Engine.

This module is the foundation for the whole emergent engine: a single SQLite
database that persists the living-world state across restarts. It holds four
slices of state, each in its own table:

* ``faction_state`` — per-faction power, treasury, and a JSON ``data`` blob
  (territory set, relations, goals, …),
* ``territory``     — which faction controls each district and whether it is
  contested,
* ``npc_goal``      — durable, prioritised NPC goals (replaced atomically per
  NPC),
* ``world_event``   — an append-only, timestamped feed of things that happened
  in the world (wars, deals, betrayals, …).

Design notes
------------
* Storage path is resolved from
  ``get_config().get("emergent.store.db_path", "data/emergent.db")`` relative
  to ``engine.paths.ROOT`` — never a hardcoded absolute path. A config error
  falls back to the default.
* WAL mode + a single process-level :class:`threading.Lock` make concurrent
  writes safe: the faction AI, NPC scheduler, and event cascade will all write
  from different threads.
* A store failure must NEVER break a caller. Every DB operation is wrapped:
  errors are surfaced via ``logger.error`` in the Oracle log format
  (``[emergent] ... (operation=...)``) but do not propagate — each op returns a
  safe value instead.
* Imports are kept minimal (stdlib + ``engine.config`` + ``engine.paths``, both
  imported lazily) so this module is safe to import in environments without
  Flask.

Usage::

    from engine.world.emergent.store import get_emergent_store

    s = get_emergent_store()
    s.upsert_faction("arasaka", power=10.0, treasury=500)
    s.set_territory("watson", "arasaka", contested=True)
    eid = s.log_event("war", "arasaka", "Arasaka moves on Watson")
    feed = s.recent_events(20)

Version: v1.63.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-15] — Initial persistent sim store (A1): SQLite WAL,
                            singleton accessor, faction/territory/goal/event
                            CRUD, concurrency-safe writes, reset() for tests.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════

_DEFAULT_DB_REL = "data/emergent.db"   # relative to project root (config default)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS faction_state (
    faction_id TEXT PRIMARY KEY,
    power      REAL,
    treasury   INTEGER,
    data       TEXT
);
CREATE TABLE IF NOT EXISTS territory (
    district_id TEXT PRIMARY KEY,
    faction_id  TEXT,
    contested   INTEGER DEFAULT 0,
    data        TEXT
);
CREATE TABLE IF NOT EXISTS npc_goal (
    npc_id    TEXT,
    goal_type TEXT,
    target    TEXT,
    priority  REAL,
    progress  REAL,
    data      TEXT,
    PRIMARY KEY (npc_id, goal_type, target)
);
CREATE TABLE IF NOT EXISTS world_event (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT,
    kind       TEXT,
    actor      TEXT,
    summary    TEXT,
    payload    TEXT,
    persistent INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_world_event_ts ON world_event(ts);
"""

_FACTION_COLUMNS = ("faction_id", "power", "treasury", "data")
_TERRITORY_COLUMNS = ("district_id", "faction_id", "contested", "data")
_GOAL_COLUMNS = ("npc_id", "goal_type", "target", "priority", "progress", "data")
_EVENT_COLUMNS = ("id", "ts", "kind", "actor", "summary", "payload", "persistent")


# ══════════════════════════════════════════════════════════════════════
#  EMERGENT STORE
# ══════════════════════════════════════════════════════════════════════


class EmergentStore:
    """Persistent SQLite store for the emergent world simulation.

    Holds faction, territory, NPC-goal, and world-event state. Writes are
    thread-safe (WAL + a process-level lock); every DB error is logged in
    Oracle format and swallowed so a store failure can never break a caller.

    Attributes:
        path: Absolute filesystem path to the SQLite database.
    """

    def __init__(self, path: Optional[str | Path] = None) -> None:
        """Initialize the store, creating the schema if needed.

        Args:
            path: Explicit database path. When ``None`` the path is resolved
                from ``get_config().get("emergent.store.db_path", ...)`` relative
                to the project root. Tests should pass an explicit path so they
                never touch real data.
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
            rel = get_config().get("emergent.store.db_path", _DEFAULT_DB_REL)
        except Exception as exc:  # config optional in minimal builds
            logger.error(
                "[emergent] config lookup failed, using default db_path (operation=resolve_path): %s",
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
            logger.error("[emergent] PRAGMA setup failed (operation=connect): %s", exc)
        return conn

    def _init_db(self) -> None:
        """Create the database file, directory, and schema if absent."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self._connect() as conn:
                conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            logger.error("[emergent] schema init failed (operation=init_db): %s", exc)

    # ── factions ──────────────────────────────────────────────────────

    def upsert_faction(
        self,
        faction_id: str,
        *,
        power: Optional[float] = None,
        treasury: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Insert or partially update a faction's state.

        Only the fields explicitly provided (non-``None``) are overwritten on
        an existing row; omitted fields are preserved. For a brand-new faction,
        omitted fields default to ``None`` (``data`` to ``{}``).

        Args:
            faction_id: Unique faction identifier (primary key).
            power: Optional power score to set.
            treasury: Optional treasury (credits) to set.
            data: Optional JSON-serializable dict (territory set, relations,
                goals, …) to set.

        Returns:
            ``True`` on success, ``False`` on failure (never raises).
        """
        try:
            with self._lock, self._connect() as conn:
                existing = conn.execute(
                    "SELECT power, treasury, data FROM faction_state WHERE faction_id = ?",
                    (faction_id,),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        "INSERT INTO faction_state (faction_id, power, treasury, data) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            faction_id,
                            power,
                            treasury,
                            json.dumps(data if data is not None else {}),
                        ),
                    )
                else:
                    new_power = existing["power"] if power is None else power
                    new_treasury = (
                        existing["treasury"] if treasury is None else treasury
                    )
                    new_data = (
                        existing["data"] if data is None else json.dumps(data)
                    )
                    conn.execute(
                        "UPDATE faction_state SET power = ?, treasury = ?, data = ? "
                        "WHERE faction_id = ?",
                        (new_power, new_treasury, new_data, faction_id),
                    )
                return True
        except sqlite3.Error as exc:
            logger.error(
                "[emergent] faction upsert failed (operation=upsert_faction, faction=%s): %s",
                faction_id, exc,
            )
            return False

    def get_faction(self, faction_id: str) -> Optional[Dict[str, Any]]:
        """Return a single faction's state, or ``None`` if unknown.

        Args:
            faction_id: The faction identifier.

        Returns:
            A dict with ``faction_id``, ``power``, ``treasury``, and the
            deserialized ``data`` dict; ``None`` if not found or on failure.
        """
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM faction_state WHERE faction_id = ?",
                    (faction_id,),
                ).fetchone()
                return self._faction_row(row) if row is not None else None
        except sqlite3.Error as exc:
            logger.error(
                "[emergent] get_faction failed (operation=get_faction, faction=%s): %s",
                faction_id, exc,
            )
            return None

    def all_factions(self) -> List[Dict[str, Any]]:
        """Return every faction's state.

        Returns:
            A list of faction dicts; empty on failure.
        """
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute("SELECT * FROM faction_state").fetchall()
                return [self._faction_row(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error("[emergent] all_factions failed (operation=all_factions): %s", exc)
            return []

    # ── territory ─────────────────────────────────────────────────────

    def set_territory(
        self,
        district_id: str,
        faction_id: str,
        *,
        contested: bool = False,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Set (insert or replace) which faction controls a district.

        Args:
            district_id: District identifier (primary key).
            faction_id: Controlling faction identifier.
            contested: Whether control is currently contested.
            data: Optional JSON-serializable dict of extra district state.

        Returns:
            ``True`` on success, ``False`` on failure (never raises).
        """
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO territory "
                    "(district_id, faction_id, contested, data) VALUES (?, ?, ?, ?)",
                    (
                        district_id,
                        faction_id,
                        1 if contested else 0,
                        json.dumps(data if data is not None else {}),
                    ),
                )
                return True
        except sqlite3.Error as exc:
            logger.error(
                "[emergent] set_territory failed (operation=set_territory, district=%s): %s",
                district_id, exc,
            )
            return False

    def get_territory(self, district_id: str) -> Optional[Dict[str, Any]]:
        """Return a single district's control state, or ``None`` if unknown.

        Args:
            district_id: The district identifier.

        Returns:
            A dict with ``district_id``, ``faction_id``, ``contested`` (bool),
            and the deserialized ``data`` dict; ``None`` if not found or on
            failure.
        """
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM territory WHERE district_id = ?",
                    (district_id,),
                ).fetchone()
                return self._territory_row(row) if row is not None else None
        except sqlite3.Error as exc:
            logger.error(
                "[emergent] get_territory failed (operation=get_territory, district=%s): %s",
                district_id, exc,
            )
            return None

    def all_territory(self) -> List[Dict[str, Any]]:
        """Return control state for every district.

        Returns:
            A list of territory dicts; empty on failure.
        """
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute("SELECT * FROM territory").fetchall()
                return [self._territory_row(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error("[emergent] all_territory failed (operation=all_territory): %s", exc)
            return []

    # ── goals ─────────────────────────────────────────────────────────

    def set_goals(self, npc_id: str, goals: List[Dict[str, Any]]) -> bool:
        """Replace ALL goals for an NPC atomically.

        Every prior goal for ``npc_id`` is deleted and the supplied goals are
        inserted in a single transaction (so a concurrent reader sees either
        the old set or the new set, never a partial mix).

        Args:
            npc_id: The NPC identifier.
            goals: List of goal dicts. Each may contain ``goal_type``,
                ``target``, ``priority``, ``progress``, and a JSON-serializable
                ``data`` dict; missing keys default sensibly.

        Returns:
            ``True`` on success, ``False`` on failure (never raises).
        """
        try:
            with self._lock, self._connect() as conn:
                conn.execute("DELETE FROM npc_goal WHERE npc_id = ?", (npc_id,))
                for g in goals:
                    conn.execute(
                        "INSERT OR REPLACE INTO npc_goal "
                        "(npc_id, goal_type, target, priority, progress, data) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            npc_id,
                            g.get("goal_type", ""),
                            g.get("target", ""),
                            g.get("priority"),
                            g.get("progress"),
                            json.dumps(g.get("data") if g.get("data") is not None else {}),
                        ),
                    )
                return True
        except sqlite3.Error as exc:
            logger.error(
                "[emergent] set_goals failed (operation=set_goals, npc=%s): %s",
                npc_id, exc,
            )
            return False

    def get_goals(self, npc_id: str) -> List[Dict[str, Any]]:
        """Return every goal for an NPC, ordered by descending priority.

        Args:
            npc_id: The NPC identifier.

        Returns:
            A list of goal dicts (deserialized ``data``); empty if none or on
            failure.
        """
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM npc_goal WHERE npc_id = ? "
                    "ORDER BY priority DESC, goal_type ASC, target ASC",
                    (npc_id,),
                ).fetchall()
                return [self._goal_row(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error(
                "[emergent] get_goals failed (operation=get_goals, npc=%s): %s",
                npc_id, exc,
            )
            return []

    # ── world events ──────────────────────────────────────────────────

    def log_event(
        self,
        kind: str,
        actor: str,
        summary: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        persistent: bool = True,
        ts: Optional[str] = None,
    ) -> int:
        """Append one world event to the feed.

        Args:
            kind: Event kind, e.g. ``'war'``, ``'deal'``, ``'betrayal'``.
            actor: Identifier of the acting faction/NPC.
            summary: Human-readable one-line description.
            payload: Optional JSON-serializable dict of structured detail.
            persistent: Whether the event is durable (vs. a transient blip).
            ts: ISO-8601 timestamp. When ``None``, ``datetime.now().isoformat()``
                is used.

        Returns:
            The new row id, or ``-1`` if the write failed (never raises).
        """
        ts = ts or datetime.now().isoformat()
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO world_event "
                    "(ts, kind, actor, summary, payload, persistent) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        ts,
                        kind,
                        actor,
                        summary,
                        json.dumps(payload if payload is not None else {}),
                        1 if persistent else 0,
                    ),
                )
                return int(cur.lastrowid)
        except sqlite3.Error as exc:
            logger.error(
                "[emergent] log_event failed (operation=log_event, kind=%s, actor=%s): %s",
                kind, actor, exc,
            )
            return -1

    def recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent world events, newest-first.

        Args:
            limit: Maximum number of events to return.

        Returns:
            A list of event dicts (deserialized ``payload``); empty on failure.
        """
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM world_event ORDER BY id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
                return [self._event_row(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error(
                "[emergent] recent_events failed (operation=recent_events): %s", exc
            )
            return []

    def count_events(self) -> int:
        """Return the total number of world events.

        Returns:
            The row count, or ``0`` on failure.
        """
        try:
            with self._lock, self._connect() as conn:
                return int(
                    conn.execute("SELECT COUNT(*) FROM world_event").fetchone()[0]
                )
        except sqlite3.Error as exc:
            logger.error("[emergent] count_events failed (operation=count_events): %s", exc)
            return 0

    # ── maintenance ───────────────────────────────────────────────────

    def reset(self) -> bool:
        """Wipe all tables (factions, territory, goals, events).

        Intended for tests and full-world resets. Idempotent.

        Returns:
            ``True`` on success, ``False`` on failure (never raises).
        """
        try:
            with self._lock, self._connect() as conn:
                conn.execute("DELETE FROM faction_state")
                conn.execute("DELETE FROM territory")
                conn.execute("DELETE FROM npc_goal")
                conn.execute("DELETE FROM world_event")
                return True
        except sqlite3.Error as exc:
            logger.error("[emergent] reset failed (operation=reset): %s", exc)
            return False

    # ── row deserializers ─────────────────────────────────────────────

    @staticmethod
    def _faction_row(row: sqlite3.Row) -> Dict[str, Any]:
        """Deserialize a ``faction_state`` row into a plain dict.

        Args:
            row: A :class:`sqlite3.Row` from ``faction_state``.

        Returns:
            A dict with the ``data`` field parsed from JSON.
        """
        d = {k: row[k] for k in _FACTION_COLUMNS}
        d["data"] = _json_loads(d.get("data"), default={})
        return d

    @staticmethod
    def _territory_row(row: sqlite3.Row) -> Dict[str, Any]:
        """Deserialize a ``territory`` row into a plain dict.

        Args:
            row: A :class:`sqlite3.Row` from ``territory``.

        Returns:
            A dict with ``contested`` as a bool and ``data`` parsed from JSON.
        """
        d = {k: row[k] for k in _TERRITORY_COLUMNS}
        d["contested"] = bool(d.get("contested"))
        d["data"] = _json_loads(d.get("data"), default={})
        return d

    @staticmethod
    def _goal_row(row: sqlite3.Row) -> Dict[str, Any]:
        """Deserialize an ``npc_goal`` row into a plain dict.

        Args:
            row: A :class:`sqlite3.Row` from ``npc_goal``.

        Returns:
            A dict with the ``data`` field parsed from JSON.
        """
        d = {k: row[k] for k in _GOAL_COLUMNS}
        d["data"] = _json_loads(d.get("data"), default={})
        return d

    @staticmethod
    def _event_row(row: sqlite3.Row) -> Dict[str, Any]:
        """Deserialize a ``world_event`` row into a plain dict.

        Args:
            row: A :class:`sqlite3.Row` from ``world_event``.

        Returns:
            A dict with ``persistent`` as a bool and ``payload`` parsed from
            JSON.
        """
        d = {k: row[k] for k in _EVENT_COLUMNS}
        d["persistent"] = bool(d.get("persistent"))
        d["payload"] = _json_loads(d.get("payload"), default={})
        return d


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

_store: Optional[EmergentStore] = None
_singleton_lock = threading.Lock()


def get_emergent_store() -> EmergentStore:
    """Return the process-wide :class:`EmergentStore` singleton.

    The singleton uses the config/default database path. Tests that need
    isolation should construct ``EmergentStore(path=...)`` directly instead.

    Returns:
        The shared :class:`EmergentStore` instance.
    """
    global _store
    if _store is None:
        with _singleton_lock:
            if _store is None:
                _store = EmergentStore()
    return _store
