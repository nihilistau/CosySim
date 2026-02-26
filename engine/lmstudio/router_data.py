"""
RouterDataCollector — Captures inference routing decisions for fine-tuning.

Every call through InferenceOrchestrator logs:
- Input features (task_type, priority, prompt length, has_tools, agent_id)
- Routing decision (tier selected, model used)
- Outcome metrics (latency_ms, tokens, tps, success)
- Optional quality score (user feedback, 0-5)

Data stored in SQLite for later export to training pipeline.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Schema ──────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS router_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    task_type TEXT NOT NULL,
    priority TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    has_tools INTEGER DEFAULT 0,
    has_system_prompt INTEGER DEFAULT 0,
    tier_selected TEXT NOT NULL,
    model_used TEXT NOT NULL DEFAULT '',
    latency_ms REAL DEFAULT 0,
    tokens_generated INTEGER DEFAULT 0,
    tokens_per_sec REAL DEFAULT 0,
    success INTEGER DEFAULT 1,
    error TEXT DEFAULT '',
    quality_score INTEGER DEFAULT -1,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_router_timestamp ON router_decisions(timestamp);
CREATE INDEX IF NOT EXISTS idx_router_task ON router_decisions(task_type, priority);
"""


@dataclass
class RouterRecord:
    """Single routing decision record."""

    agent_id: str = ""
    task_type: str = "chat"
    priority: str = "interactive"
    prompt_tokens: int = 0
    has_tools: bool = False
    has_system_prompt: bool = False
    tier_selected: str = ""
    model_used: str = ""
    latency_ms: float = 0.0
    tokens_generated: int = 0
    tokens_per_sec: float = 0.0
    success: bool = True
    error: str = ""
    quality_score: int = -1
    metadata: Dict[str, Any] = field(default_factory=dict)


class RouterDataCollector:
    """Collects inference routing decisions for router model fine-tuning."""

    _instance: Optional["RouterDataCollector"] = None

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            from engine.config import get_config
            cfg = get_config()
            data_dir = Path(cfg.get("training.datasets.base_dir", "data"))
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "router_training.db")

        self._db_path = db_path
        self._lock = threading.Lock()
        self._buffer: List[RouterRecord] = []
        self._buffer_size = 50  # flush every N records
        self._init_db()
        logger.info("RouterDataCollector initialized: %s", db_path)

    def _init_db(self) -> None:
        """Create tables if needed."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def record(self, rec: RouterRecord) -> None:
        """Buffer a routing decision. Auto-flushes when buffer is full."""
        with self._lock:
            self._buffer.append(rec)
            if len(self._buffer) >= self._buffer_size:
                self._flush_locked()

    def _flush_locked(self) -> None:
        """Write buffered records to SQLite. Must hold self._lock."""
        if not self._buffer:
            return
        records = list(self._buffer)
        self._buffer.clear()

        try:
            conn = sqlite3.connect(self._db_path)
            try:
                for rec in records:
                    conn.execute(
                        """INSERT INTO router_decisions
                        (timestamp, agent_id, task_type, priority, prompt_tokens,
                         has_tools, has_system_prompt, tier_selected, model_used,
                         latency_ms, tokens_generated, tokens_per_sec, success,
                         error, quality_score, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            time.time(), rec.agent_id, rec.task_type, rec.priority,
                            rec.prompt_tokens, int(rec.has_tools), int(rec.has_system_prompt),
                            rec.tier_selected, rec.model_used,
                            round(rec.latency_ms, 1), rec.tokens_generated,
                            round(rec.tokens_per_sec, 1), int(rec.success),
                            rec.error[:500] if rec.error else "",
                            rec.quality_score,
                            json.dumps(rec.metadata) if rec.metadata else "{}",
                        ),
                    )
                conn.commit()
                logger.debug("Flushed %d router records", len(records))
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to flush router data: %s", exc)

    def flush(self) -> int:
        """Force-flush the buffer. Returns number of records flushed."""
        with self._lock:
            count = len(self._buffer)
            self._flush_locked()
            return count

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate stats about collected data."""
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM router_decisions"
                ).fetchone()
                total = row[0] if row else 0

                by_task = dict(conn.execute(
                    "SELECT task_type, COUNT(*) FROM router_decisions GROUP BY task_type"
                ).fetchall()) if total > 0 else {}

                by_tier = dict(conn.execute(
                    "SELECT tier_selected, COUNT(*) FROM router_decisions GROUP BY tier_selected"
                ).fetchall()) if total > 0 else {}

                success_rate = 0.0
                if total > 0:
                    successes = conn.execute(
                        "SELECT COUNT(*) FROM router_decisions WHERE success = 1"
                    ).fetchone()[0]
                    success_rate = successes / total

                return {
                    "total_records": total,
                    "first_record": row[1] if row and row[1] else None,
                    "last_record": row[2] if row and row[2] else None,
                    "by_task_type": by_task,
                    "by_tier": by_tier,
                    "success_rate": round(success_rate, 3),
                    "buffer_pending": len(self._buffer),
                    "db_path": self._db_path,
                }
            finally:
                conn.close()
        except Exception as exc:
            return {"error": str(exc)}

    def export_jsonl(self, output_path: str, *, limit: int = 0) -> int:
        """Export records as JSONL for training. Returns count exported."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            query = "SELECT * FROM router_decisions ORDER BY timestamp"
            if limit > 0:
                query += f" LIMIT {limit}"
            rows = conn.execute(query).fetchall()

            with open(output_path, "w", encoding="utf-8") as f:
                for row in rows:
                    record = dict(row)
                    record["has_tools"] = bool(record["has_tools"])
                    record["has_system_prompt"] = bool(record["has_system_prompt"])
                    record["success"] = bool(record["success"])
                    f.write(json.dumps(record) + "\n")

            logger.info("Exported %d router records to %s", len(rows), output_path)
            return len(rows)
        finally:
            conn.close()

    def rate_last(self, quality_score: int) -> bool:
        """Rate the most recent decision (user feedback, 0-5)."""
        score = max(0, min(5, quality_score))
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "UPDATE router_decisions SET quality_score = ? "
                    "WHERE id = (SELECT MAX(id) FROM router_decisions)",
                    (score,),
                )
                conn.commit()
                return True
            finally:
                conn.close()
        except Exception:
            return False

    def cleanup(self, keep_days: int = 90) -> int:
        """Remove records older than keep_days. Returns count deleted."""
        cutoff = time.time() - (keep_days * 86400)
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                cursor = conn.execute(
                    "DELETE FROM router_decisions WHERE timestamp < ?", (cutoff,)
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()
        except Exception:
            return 0


def get_router_data_collector() -> RouterDataCollector:
    """Get or create the singleton RouterDataCollector."""
    if RouterDataCollector._instance is None:
        RouterDataCollector._instance = RouterDataCollector()
    return RouterDataCollector._instance
