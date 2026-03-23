"""
Assistant Platform — Prompt Cache
==================================

SQLite-backed response cache to avoid redundant LLM calls.
Checks cache before dispatch, stores after successful response.

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Initial cache with TTL, hash-based lookup, stats
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from typing import Any, Dict, Optional, Tuple

from apps.assistant.config import DATABASE_PATH

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3600  # 1 hour
MAX_CACHE_ENTRIES = 10000


# ──── Cache Table Setup ──────────────────────────────────────────────

def init_cache_table() -> None:
    """Create the cache table if it doesn't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prompt_cache (
            prompt_hash TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            prompt_preview TEXT DEFAULT '',
            response TEXT NOT NULL,
            token_count INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            ttl_seconds INTEGER NOT NULL DEFAULT 3600,
            hit_count INTEGER DEFAULT 0,
            last_hit_at REAL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_cache_model ON prompt_cache(model);
        CREATE INDEX IF NOT EXISTS idx_cache_created ON prompt_cache(created_at);
    """)
    conn.commit()
    conn.close()


def _get_conn() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ──── Hash Function ──────────────────────────────────────────────────

def _hash_prompt(messages: list, model: str, temperature: float = 0.7) -> str:
    """Create a deterministic hash of the prompt for cache lookup.

    Includes messages, model, and temperature in the hash so different
    configurations don't collide.

    Note: temperature is rounded to 1 decimal to avoid float precision issues.
    """
    key = json.dumps({
        "messages": messages,
        "model": model,
        "temperature": round(temperature, 1),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(key.encode()).hexdigest()[:32]


# ──── Cache Operations ───────────────────────────────────────────────

def cache_get(
    messages: list,
    model: str,
    temperature: float = 0.7,
) -> Optional[str]:
    """Look up a cached response.

    Returns the cached response text if found and not expired, None otherwise.
    """
    prompt_hash = _hash_prompt(messages, model, temperature)
    conn = _get_conn()

    row = conn.execute(
        "SELECT response, created_at, ttl_seconds FROM prompt_cache WHERE prompt_hash = ?",
        (prompt_hash,),
    ).fetchone()

    if not row:
        conn.close()
        return None

    # Check TTL
    age = time.time() - row["created_at"]
    if age > row["ttl_seconds"]:
        # Expired — delete and return miss
        conn.execute("DELETE FROM prompt_cache WHERE prompt_hash = ?", (prompt_hash,))
        conn.commit()
        conn.close()
        return None

    # Cache hit — update stats
    conn.execute(
        "UPDATE prompt_cache SET hit_count = hit_count + 1, last_hit_at = ? WHERE prompt_hash = ?",
        (time.time(), prompt_hash),
    )
    conn.commit()
    conn.close()

    logger.debug("[Cache] HIT: %s (model=%s, age=%.0fs)", prompt_hash[:8], model, age)
    return row["response"]


def cache_set(
    messages: list,
    model: str,
    response: str,
    temperature: float = 0.7,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> None:
    """Store a response in the cache."""
    prompt_hash = _hash_prompt(messages, model, temperature)

    # Preview: first user message, truncated
    preview = ""
    for msg in messages:
        if msg.get("role") == "user":
            preview = msg.get("content", "")[:100]
            break

    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO prompt_cache
           (prompt_hash, model, prompt_preview, response, token_count, created_at, ttl_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (prompt_hash, model, preview, response, len(response) // 4, time.time(), ttl_seconds),
    )
    conn.commit()

    # Evict old entries if over limit
    count = conn.execute("SELECT COUNT(*) FROM prompt_cache").fetchone()[0]
    if count > MAX_CACHE_ENTRIES:
        conn.execute(
            "DELETE FROM prompt_cache WHERE prompt_hash IN "
            "(SELECT prompt_hash FROM prompt_cache ORDER BY last_hit_at ASC LIMIT ?)",
            (count - MAX_CACHE_ENTRIES,),
        )
        conn.commit()

    conn.close()
    logger.debug("[Cache] SET: %s (model=%s, ttl=%ds)", prompt_hash[:8], model, ttl_seconds)


def cache_clear(model: Optional[str] = None) -> int:
    """Clear cached entries. Optionally filter by model.

    Returns number of entries deleted.
    """
    conn = _get_conn()
    if model:
        result = conn.execute("DELETE FROM prompt_cache WHERE model = ?", (model,))
    else:
        result = conn.execute("DELETE FROM prompt_cache")
    conn.commit()
    deleted = result.rowcount
    conn.close()
    return deleted


def cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    conn = _get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM prompt_cache").fetchone()[0]
        total_hits = conn.execute("SELECT COALESCE(SUM(hit_count), 0) FROM prompt_cache").fetchone()[0]

        # Per-model breakdown
        models = {}
        for row in conn.execute(
            "SELECT model, COUNT(*) as cnt, SUM(hit_count) as hits "
            "FROM prompt_cache GROUP BY model"
        ).fetchall():
            models[row["model"]] = {"entries": row["cnt"], "hits": row["hits"]}

        # Oldest and newest
        oldest = conn.execute("SELECT MIN(created_at) FROM prompt_cache").fetchone()[0]
        newest = conn.execute("SELECT MAX(created_at) FROM prompt_cache").fetchone()[0]

        return {
            "total_entries": total,
            "total_hits": total_hits,
            "max_entries": MAX_CACHE_ENTRIES,
            "default_ttl_seconds": DEFAULT_TTL_SECONDS,
            "models": models,
            "oldest_entry_age_hours": round((time.time() - oldest) / 3600, 1) if oldest else 0,
            "newest_entry_age_seconds": round(time.time() - newest, 0) if newest else 0,
        }
    except Exception:
        return {"total_entries": 0, "total_hits": 0, "error": "cache table may not exist"}
    finally:
        conn.close()
