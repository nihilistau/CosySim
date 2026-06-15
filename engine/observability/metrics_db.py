"""
MetricsDB — Persistent time-series storage for CosySim observability.

SQLite tables for:
- ``system_metrics`` — periodic CPU/RAM/GPU snapshots (pruned to 24h)
- ``pipeline_metrics`` — per-request pipeline performance data
- ``alerts`` — alert state change history
- ``training_candidates`` — captured examples for Gemma fine-tuning
- ``process_snapshots`` — periodic process monitor snapshots

Thread-safe singleton — call ``get_metrics_db()`` from anywhere.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import DATA_DIR

logger = logging.getLogger(__name__)

_DEFAULT_PATH = DATA_DIR / "metrics.db"

# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional["MetricsDB"] = None
_lock = threading.Lock()


def get_metrics_db(path: Optional[Path] = None) -> "MetricsDB":
    """Get or create the singleton MetricsDB."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = MetricsDB(path or _DEFAULT_PATH)
    return _instance


# ── Schema ──────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS system_metrics (
    ts REAL PRIMARY KEY,
    cpu_pct REAL,
    ram_pct REAL,
    gpu_vram_pct REAL,
    gpu_temp_c REAL,
    lmstudio_ok INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS pipeline_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    request_id TEXT,
    agent_id TEXT,
    scene_id TEXT,
    tier TEXT,
    model TEXT,
    latency_ms REAL,
    ttft_ms REAL,
    tokens_in INTEGER,
    tokens_out INTEGER,
    tps REAL,
    watcher_latency_ms REAL,
    watcher_signal TEXT,
    kill_fired INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    pre_warm_hit INTEGER DEFAULT 0,
    response_id TEXT,
    draft_accepted INTEGER DEFAULT 0,
    draft_rejected INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pm_ts ON pipeline_metrics(ts);
CREATE INDEX IF NOT EXISTS idx_pm_agent ON pipeline_metrics(agent_id, ts);
CREATE INDEX IF NOT EXISTS idx_pm_tier ON pipeline_metrics(tier, ts);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    node TEXT NOT NULL,
    level TEXT NOT NULL,
    prev_level TEXT,
    message TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);

CREATE TABLE IF NOT EXISTS training_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    source TEXT NOT NULL,
    dataset TEXT NOT NULL,
    input_text TEXT NOT NULL,
    output_text TEXT NOT NULL,
    quality_score REAL DEFAULT 0.5,
    exported INTEGER DEFAULT 0,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_tc_dataset ON training_candidates(dataset, exported);

CREATE TABLE IF NOT EXISTS process_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    category TEXT,
    process_count INTEGER DEFAULT 0,
    total_cpu_seconds REAL DEFAULT 0.0,
    total_memory_mb REAL DEFAULT 0.0,
    git_op_count INTEGER DEFAULT 0,
    tracked_op_count INTEGER DEFAULT 0,
    stalled_count INTEGER DEFAULT 0,
    snapshot_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_ps_ts ON process_snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_ps_category ON process_snapshots(category);
"""


# ── MetricsDB ───────────────────────────────────────────────────────────

class MetricsDB:
    """Thread-safe SQLite metrics store."""

    def __init__(self, path: Path = _DEFAULT_PATH):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._path), timeout=5)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def close(self) -> None:
        # v1.62.0 [2026-06-15] — Release the thread-local SQLite handle so the
        # backing file (and WAL sidecars) can be deleted promptly. Without this,
        # the connection lingered until GC, breaking Windows tmp-dir teardown
        # (rmtree -> WinError 32) during test runs.
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    @contextmanager
    def _cursor(self):
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self):
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    # ── System metrics ──────────────────────────────────────────────

    def record_system(
        self,
        cpu_pct: float = 0.0,
        ram_pct: float = 0.0,
        gpu_vram_pct: float = 0.0,
        gpu_temp_c: float = 0.0,
        lmstudio_ok: bool = True,
    ) -> None:
        """Record a system snapshot."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO system_metrics "
                "(ts, cpu_pct, ram_pct, gpu_vram_pct, gpu_temp_c, lmstudio_ok) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), cpu_pct, ram_pct, gpu_vram_pct, gpu_temp_c, int(lmstudio_ok)),
            )

    def get_system_history(self, seconds: float = 300) -> List[Dict]:
        """Get system metrics from the last N seconds."""
        cutoff = time.time() - seconds
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM system_metrics WHERE ts > ? ORDER BY ts",
                (cutoff,),
            )
            return [dict(row) for row in cur.fetchall()]

    def prune_system_metrics(self, max_age_hours: float = 24) -> int:
        """Delete system metrics older than max_age_hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        with self._cursor() as cur:
            cur.execute("DELETE FROM system_metrics WHERE ts < ?", (cutoff,))
            return cur.rowcount

    # ── Pipeline metrics ────────────────────────────────────────────

    def record_pipeline(self, **kwargs) -> None:
        """Record a pipeline execution metric."""
        kwargs.setdefault("ts", time.time())
        cols = [k for k in kwargs if k in _PIPELINE_COLS]
        vals = [kwargs[k] for k in cols]
        placeholders = ", ".join("?" for _ in cols)
        col_str = ", ".join(cols)
        with self._cursor() as cur:
            cur.execute(
                f"INSERT INTO pipeline_metrics ({col_str}) VALUES ({placeholders})",
                vals,
            )

    def get_pipeline_history(
        self,
        seconds: float = 300,
        agent_id: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> List[Dict]:
        """Get pipeline metrics from the last N seconds."""
        cutoff = time.time() - seconds
        clauses = ["ts > ?"]
        params: list = [cutoff]
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if tier:
            clauses.append("tier = ?")
            params.append(tier)
        where = " AND ".join(clauses)
        with self._cursor() as cur:
            cur.execute(
                f"SELECT * FROM pipeline_metrics WHERE {where} ORDER BY ts",
                params,
            )
            return [dict(row) for row in cur.fetchall()]

    def get_pipeline_summary(self, seconds: float = 60) -> Dict[str, Any]:
        """Get aggregated pipeline stats over the last N seconds."""
        cutoff = time.time() - seconds
        with self._cursor() as cur:
            cur.execute(
                "SELECT "
                "  COUNT(*) as total, "
                "  AVG(latency_ms) as avg_latency, "
                "  AVG(tps) as avg_tps, "
                "  AVG(ttft_ms) as avg_ttft, "
                "  SUM(kill_fired) as total_kills, "
                "  SUM(pre_warm_hit) as total_pre_warms, "
                "  AVG(tokens_in) as avg_tokens_in, "
                "  AVG(tokens_out) as avg_tokens_out "
                "FROM pipeline_metrics WHERE ts > ?",
                (cutoff,),
            )
            row = cur.fetchone()
            return dict(row) if row else {}

    # ── Alerts ──────────────────────────────────────────────────────

    def record_alert(
        self, node: str, level: str, message: str = "", prev_level: str = ""
    ) -> None:
        """Record an alert state change."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO alerts (ts, node, level, prev_level, message) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(), node, level, prev_level, message),
            )

    def get_recent_alerts(self, limit: int = 50) -> List[Dict]:
        """Get most recent alerts."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)
            )
            return [dict(row) for row in cur.fetchall()]

    # ── Training candidates ─────────────────────────────────────────

    def store_training_candidate(
        self,
        source: str,
        dataset: str,
        input_text: str,
        output_text: str,
        quality_score: float = 0.5,
        notes: str = "",
    ) -> int:
        """Store a training data candidate. Returns row id."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO training_candidates "
                "(ts, source, dataset, input_text, output_text, quality_score, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), source, dataset, input_text, output_text, quality_score, notes),
            )
            return cur.lastrowid

    def get_training_candidates(
        self,
        dataset: Optional[str] = None,
        min_quality: float = 0.0,
        exported: Optional[bool] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Query training candidates."""
        clauses = ["1=1"]
        params: list = []
        if dataset:
            clauses.append("dataset = ?")
            params.append(dataset)
        if min_quality > 0:
            clauses.append("quality_score >= ?")
            params.append(min_quality)
        if exported is not None:
            clauses.append("exported = ?")
            params.append(int(exported))
        where = " AND ".join(clauses)
        params.append(limit)
        with self._cursor() as cur:
            cur.execute(
                f"SELECT * FROM training_candidates WHERE {where} ORDER BY ts DESC LIMIT ?",
                params,
            )
            return [dict(row) for row in cur.fetchall()]

    def count_training_candidates(
        self,
        dataset: Optional[str] = None,
        exported: Optional[bool] = None,
        min_quality: float = 0.0,
    ) -> int:
        """Count training candidates matching filters."""
        clauses = ["1=1"]
        params: list = []
        if dataset:
            clauses.append("dataset = ?")
            params.append(dataset)
        if exported is not None:
            clauses.append("exported = ?")
            params.append(int(exported))
        if min_quality > 0:
            clauses.append("quality_score >= ?")
            params.append(min_quality)
        where = " AND ".join(clauses)
        with self._cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM training_candidates WHERE {where}",
                params,
            )
            return cur.fetchone()[0]

    def mark_exported(self, ids: List[int]) -> int:
        """Mark training candidates as exported."""
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        with self._cursor() as cur:
            cur.execute(
                f"UPDATE training_candidates SET exported = 1 WHERE id IN ({placeholders})",
                ids,
            )
            return cur.rowcount

    def update_quality(self, candidate_id: int, quality_score: float, notes: str = "") -> None:
        """Update quality score for a training candidate."""
        with self._cursor() as cur:
            if notes:
                cur.execute(
                    "UPDATE training_candidates SET quality_score = ?, notes = ? WHERE id = ?",
                    (quality_score, notes, candidate_id),
                )
            else:
                cur.execute(
                    "UPDATE training_candidates SET quality_score = ? WHERE id = ?",
                    (quality_score, candidate_id),
                )

    def get_training_stats(self) -> Dict[str, Any]:
        """Get summary stats for training data."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT dataset, COUNT(*) as total, "
                "SUM(CASE WHEN exported = 0 THEN 1 ELSE 0 END) as pending, "
                "AVG(quality_score) as avg_quality "
                "FROM training_candidates GROUP BY dataset"
            )
            return {row["dataset"]: dict(row) for row in cur.fetchall()}

    # ── Process snapshots ────────────────────────────────────────────

    def record_process_snapshot(
        self,
        category: str = "all",
        process_count: int = 0,
        total_cpu_seconds: float = 0.0,
        total_memory_mb: float = 0.0,
        git_op_count: int = 0,
        tracked_op_count: int = 0,
        stalled_count: int = 0,
        snapshot_json: str = "",
    ) -> None:
        """Record a process monitor snapshot."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO process_snapshots "
                "(ts, category, process_count, total_cpu_seconds, total_memory_mb, "
                "git_op_count, tracked_op_count, stalled_count, snapshot_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    time.time(), category, process_count, total_cpu_seconds,
                    total_memory_mb, git_op_count, tracked_op_count,
                    stalled_count, snapshot_json,
                ),
            )

    def get_process_history(self, seconds: float = 300, category: str = "") -> List[Dict]:
        """Get process snapshots from the last N seconds.

        Args:
            seconds: Lookback window in seconds.
            category: Optional category filter (empty = all).

        Returns:
            List of snapshot dicts ordered by timestamp.
        """
        cutoff = time.time() - seconds
        with self._cursor() as cur:
            if category:
                cur.execute(
                    "SELECT * FROM process_snapshots WHERE ts > ? AND category = ? ORDER BY ts",
                    (cutoff, category),
                )
            else:
                cur.execute(
                    "SELECT * FROM process_snapshots WHERE ts > ? ORDER BY ts",
                    (cutoff,),
                )
            return [dict(row) for row in cur.fetchall()]

    def prune_process_snapshots(self, max_age_hours: float = 24) -> int:
        """Delete process snapshots older than max_age_hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        with self._cursor() as cur:
            cur.execute("DELETE FROM process_snapshots WHERE ts < ?", (cutoff,))
            return cur.rowcount


# Valid pipeline_metrics column names for record_pipeline()
_PIPELINE_COLS = {
    "ts", "request_id", "agent_id", "scene_id", "tier", "model",
    "latency_ms", "ttft_ms", "tokens_in", "tokens_out", "tps",
    "watcher_latency_ms", "watcher_signal", "kill_fired", "retry_count",
    "pre_warm_hit", "response_id", "draft_accepted", "draft_rejected",
}
