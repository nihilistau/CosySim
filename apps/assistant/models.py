"""
Assistant Platform — Database Models
=====================================

SQLite persistence for conversations, messages, and settings.

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Initial schema: conversations, messages, settings
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from apps.assistant.config import DATABASE_PATH, DEFAULT_SETTINGS


# ──── Database Setup ─────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'New Chat',
            model TEXT NOT NULL DEFAULT 'gpt-5.4',
            system_prompt TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            message_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('system', 'user', 'assistant')),
            content TEXT NOT NULL DEFAULT '',
            model TEXT DEFAULT '',
            provider TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            token_count INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '{}'
        );
    """)
    conn.commit()
    conn.close()


# ──── Conversations ──────────────────────────────────────────────────

def create_conversation(
    title: str = "New Chat",
    model: str = "gpt-5.4",
    system_prompt: str = "",
) -> Dict[str, Any]:
    """Create a new conversation and return it."""
    conv_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO conversations (id, title, model, system_prompt, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conv_id, title, model, system_prompt, now, now),
    )
    conn.commit()
    conn.close()
    return {"id": conv_id, "title": title, "model": model, "system_prompt": system_prompt,
            "created_at": now, "updated_at": now, "message_count": 0}


def get_conversations(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """List conversations, newest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    conn.close()
    return {"conversations": [dict(r) for r in rows], "total": total}


def get_conversation(conv_id: str) -> Optional[Dict[str, Any]]:
    """Get a single conversation with its messages."""
    conn = _get_conn()
    conv = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    if not conv:
        conn.close()
        return None
    messages = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
        (conv_id,),
    ).fetchall()
    conn.close()
    result = dict(conv)
    result["messages"] = [dict(m) for m in messages]
    return result


def update_conversation(conv_id: str, **kwargs: Any) -> bool:
    """Update conversation fields (title, model, system_prompt)."""
    allowed = {"title", "model", "system_prompt"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = _get_conn()
    conn.execute(
        f"UPDATE conversations SET {set_clause} WHERE id = ?",
        (*updates.values(), conv_id),
    )
    conn.commit()
    conn.close()
    return True


def delete_conversation(conv_id: str) -> bool:
    """Delete a conversation and its messages."""
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
    result = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    conn.close()
    return result.rowcount > 0


# ──── Messages ───────────────────────────────────────────────────────

def add_message(
    conversation_id: str,
    role: str,
    content: str,
    model: str = "",
    provider: str = "",
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Add a message to a conversation."""
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    token_count = len(content) // 4
    meta_json = json.dumps(metadata or {})

    conn = _get_conn()
    conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, model, provider, created_at, token_count, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (msg_id, conversation_id, role, content, model, provider, now, token_count, meta_json),
    )
    conn.execute(
        "UPDATE conversations SET updated_at = ?, message_count = message_count + 1 WHERE id = ?",
        (now, conversation_id),
    )
    conn.commit()
    conn.close()
    return {"id": msg_id, "conversation_id": conversation_id, "role": role,
            "content": content, "model": model, "provider": provider,
            "created_at": now, "token_count": token_count, "metadata": metadata or {}}


def get_messages(conversation_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Get messages for a conversation."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ──── Settings ───────────────────────────────────────────────────────

def get_setting(key: str, default: Any = None) -> Any:
    """Get a setting value."""
    conn = _get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]
    if default is not None:
        return default
    return DEFAULT_SETTINGS.get(key)


def set_setting(key: str, value: Any) -> None:
    """Set a setting value."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, json.dumps(value)),
    )
    conn.commit()
    conn.close()


def get_all_settings() -> Dict[str, Any]:
    """Get all settings merged with defaults."""
    result = dict(DEFAULT_SETTINGS)
    conn = _get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    for row in rows:
        try:
            result[row["key"]] = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            result[row["key"]] = row["value"]
    return result


def update_settings(settings: Dict[str, Any]) -> None:
    """Update multiple settings at once."""
    conn = _get_conn()
    for key, value in settings.items():
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
    conn.commit()
    conn.close()
