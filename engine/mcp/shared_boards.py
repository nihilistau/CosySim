"""
SharedBoardManager — System-wide highscore tables and message boards.
====================================================================

SQLite-backed shared data accessible from any scene or agent:

* **Highscore boards** — Submit / query ranked scores for any game.
* **Message boards**   — Cross-scene group chat for agents and players.

Access patterns:

1. Python API:  ``get_shared_boards().submit_score(...)``
2. MCP skills:  ``view_highscores``, ``post_to_board``, etc.
3. REST API:    ``/overlay/api/boards/...`` (mounted via overlay Blueprint)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "shared_boards.db"


class SharedBoardManager:
    """Singleton managing shared boards backed by SQLite."""

    _instance: Optional[SharedBoardManager] = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> SharedBoardManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._write_lock = threading.Lock()
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS boards (
                board_id     TEXT PRIMARY KEY,
                board_type   TEXT NOT NULL CHECK(board_type IN ('highscore','messageboard')),
                display_name TEXT NOT NULL,
                metadata     TEXT DEFAULT '{}',
                created_at   REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS highscores (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id    TEXT NOT NULL REFERENCES boards(board_id),
                player_name TEXT NOT NULL,
                score       INTEGER NOT NULL,
                metadata    TEXT DEFAULT '{}',
                created_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS board_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id    TEXT NOT NULL REFERENCES boards(board_id),
                author_id   TEXT NOT NULL,
                author_name TEXT NOT NULL DEFAULT 'Anonymous',
                content     TEXT NOT NULL,
                metadata    TEXT DEFAULT '{}',
                created_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_hs_score  ON highscores(board_id, score DESC);
            CREATE INDEX IF NOT EXISTS idx_msg_time  ON board_messages(board_id, created_at DESC);
        """)
        # Ensure default global chat board exists
        self.ensure_board("cosysim_global", "messageboard", "CosySim Global Chat")

    # ── Board management ─────────────────────────────────────────────

    def ensure_board(self, board_id: str, board_type: str,
                     display_name: str | None = None) -> Dict[str, Any]:
        with self._write_lock:
            row = self._conn.execute(
                "SELECT * FROM boards WHERE board_id = ?", (board_id,)
            ).fetchone()
            if row:
                return dict(row)
            self._conn.execute(
                "INSERT INTO boards (board_id, board_type, display_name, created_at) "
                "VALUES (?,?,?,?)",
                (board_id, board_type, display_name or board_id, time.time()),
            )
            self._conn.commit()
        return {
            "board_id": board_id,
            "board_type": board_type,
            "display_name": display_name or board_id,
        }

    def list_boards(self, board_type: str | None = None) -> List[Dict[str, Any]]:
        if board_type:
            rows = self._conn.execute(
                "SELECT * FROM boards WHERE board_type = ?", (board_type,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM boards").fetchall()
        return [dict(r) for r in rows]

    # ── Highscores ───────────────────────────────────────────────────

    def submit_score(self, board_id: str, player_name: str, score: int,
                     metadata: Dict | None = None) -> Dict[str, Any]:
        self.ensure_board(board_id, "highscore")
        with self._write_lock:
            self._conn.execute(
                "INSERT INTO highscores (board_id, player_name, score, metadata, created_at) "
                "VALUES (?,?,?,?,?)",
                (board_id, player_name, score, json.dumps(metadata or {}), time.time()),
            )
            self._conn.commit()
        rank = self._conn.execute(
            "SELECT COUNT(*) FROM highscores WHERE board_id = ? AND score > ?",
            (board_id, score),
        ).fetchone()[0] + 1
        return {"player_name": player_name, "score": score, "rank": rank}

    def get_highscores(self, board_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT player_name, score, metadata, created_at "
            "FROM highscores WHERE board_id = ? ORDER BY score DESC LIMIT ?",
            (board_id, limit),
        ).fetchall()
        return [
            {
                "rank": i + 1,
                "player_name": r["player_name"],
                "score": r["score"],
                "metadata": json.loads(r["metadata"] or "{}"),
                "created_at": r["created_at"],
            }
            for i, r in enumerate(rows)
        ]

    # ── Message board ────────────────────────────────────────────────

    def post_message(self, board_id: str, author_id: str, content: str,
                     author_name: str | None = None,
                     metadata: Dict | None = None) -> Dict[str, Any]:
        self.ensure_board(board_id, "messageboard")
        ts = time.time()
        with self._write_lock:
            cur = self._conn.execute(
                "INSERT INTO board_messages "
                "(board_id, author_id, author_name, content, metadata, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (board_id, author_id, author_name or author_id, content,
                 json.dumps(metadata or {}), ts),
            )
            self._conn.commit()
            msg_id = cur.lastrowid
        return {"id": msg_id, "author_id": author_id, "content": content,
                "created_at": ts}

    def get_messages(self, board_id: str, limit: int = 50,
                     since_id: int | None = None) -> List[Dict[str, Any]]:
        if since_id:
            rows = self._conn.execute(
                "SELECT id, author_id, author_name, content, metadata, created_at "
                "FROM board_messages WHERE board_id = ? AND id > ? "
                "ORDER BY created_at DESC LIMIT ?",
                (board_id, since_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, author_id, author_name, content, metadata, created_at "
                "FROM board_messages WHERE board_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (board_id, limit),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "author_id": r["author_id"],
                "author_name": r["author_name"],
                "content": r["content"],
                "metadata": json.loads(r["metadata"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]


def get_shared_boards() -> SharedBoardManager:
    """Get the singleton SharedBoardManager."""
    return SharedBoardManager.instance()
