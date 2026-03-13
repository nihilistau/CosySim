"""
PackTracker — Map skill pack executions ↔ PIDs ↔ CPU time.

Hooks into SkillRegistry execution to track which pack triggered
which process, cumulative CPU seconds per pack, and cross-references
PIDs with ProcessMonitor categories.

Usage::

    from engine.observability.pack_tracker import get_pack_tracker
    tracker = get_pack_tracker()
    tracker.start()

    # Record a skill execution (called automatically via hook)
    tracker.record_execution("world", "describe_scene", 0.34, pid=12345)

    # Query pack activity
    tracker.pack_summary()        # All packs with CPU, memory, call counts
    tracker.pack_processes("world")  # PIDs associated with a pack
    tracker.top_packs(5)          # Top 5 by CPU time
    tracker.cross_reference()     # Pack ↔ ProcessCategory cross-ref matrix
"""
from __future__ import annotations

import logging
import os
import statistics
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional["PackTracker"] = None
_lock = threading.Lock()


def get_pack_tracker() -> "PackTracker":
    """Get or create the singleton PackTracker."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = PackTracker()
    return _instance


# ── Data Models ─────────────────────────────────────────────────────────


@dataclass
class SkillExecution:
    """Record of a single skill execution."""
    pack: str
    skill_name: str
    duration_s: float
    timestamp: float
    pid: int
    cpu_seconds_before: float = 0.0
    cpu_seconds_after: float = 0.0
    memory_mb: float = 0.0
    success: bool = True
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def cpu_delta(self) -> float:
        """CPU seconds consumed by this execution."""
        return max(0.0, self.cpu_seconds_after - self.cpu_seconds_before)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pack": self.pack,
            "skill": self.skill_name,
            "duration_s": round(self.duration_s, 4),
            "cpu_delta_s": round(self.cpu_delta, 4),
            "memory_mb": round(self.memory_mb, 1),
            "pid": self.pid,
            "success": self.success,
            "error": self.error,
            "ts": self.timestamp,
        }


@dataclass
class PackActivity:
    """Aggregated activity for a skill pack."""
    pack: str
    total_calls: int = 0
    total_duration_s: float = 0.0
    total_cpu_seconds: float = 0.0
    total_memory_mb_peak: float = 0.0
    success_count: int = 0
    error_count: int = 0
    avg_duration_s: float = 0.0
    avg_cpu_seconds: float = 0.0
    p95_duration_s: float = 0.0
    p99_duration_s: float = 0.0
    associated_pids: List[int] = field(default_factory=list)
    associated_categories: List[str] = field(default_factory=list)
    last_execution: float = 0.0
    skills_used: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pack": self.pack,
            "total_calls": self.total_calls,
            "total_duration_s": round(self.total_duration_s, 2),
            "total_cpu_seconds": round(self.total_cpu_seconds, 2),
            "memory_mb_peak": round(self.total_memory_mb_peak, 1),
            "success_rate": round(self.success_count / max(self.total_calls, 1), 3),
            "error_count": self.error_count,
            "avg_duration_s": round(self.avg_duration_s, 4),
            "avg_cpu_seconds": round(self.avg_cpu_seconds, 4),
            "p95_duration_s": round(self.p95_duration_s, 4),
            "p99_duration_s": round(self.p99_duration_s, 4),
            "pid_count": len(self.associated_pids),
            "categories": self.associated_categories,
            "last_execution": self.last_execution,
            "skills_used": self.skills_used,
        }


# ── DB Schema ───────────────────────────────────────────────────────────

_PACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS pack_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    pack TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    duration_s REAL NOT NULL,
    cpu_delta_s REAL DEFAULT 0.0,
    memory_mb REAL DEFAULT 0.0,
    pid INTEGER,
    success INTEGER DEFAULT 1,
    error TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_pe_ts ON pack_executions(ts);
CREATE INDEX IF NOT EXISTS idx_pe_pack ON pack_executions(pack, ts);
CREATE INDEX IF NOT EXISTS idx_pe_skill ON pack_executions(skill_name, ts);
CREATE INDEX IF NOT EXISTS idx_pe_pid ON pack_executions(pid, ts);

CREATE TABLE IF NOT EXISTS pack_pid_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    pack TEXT NOT NULL,
    pid INTEGER NOT NULL,
    cpu_seconds REAL DEFAULT 0.0,
    memory_mb REAL DEFAULT 0.0,
    process_category TEXT DEFAULT 'other',
    process_name TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_ppm_pack ON pack_pid_map(pack);
CREATE INDEX IF NOT EXISTS idx_ppm_pid ON pack_pid_map(pid);

CREATE TABLE IF NOT EXISTS pack_hourly_rollup (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hour_ts REAL NOT NULL,
    pack TEXT NOT NULL,
    call_count INTEGER DEFAULT 0,
    total_duration_s REAL DEFAULT 0.0,
    total_cpu_s REAL DEFAULT 0.0,
    avg_duration_s REAL DEFAULT 0.0,
    p95_duration_s REAL DEFAULT 0.0,
    error_count INTEGER DEFAULT 0,
    UNIQUE(hour_ts, pack)
);

CREATE INDEX IF NOT EXISTS idx_phr_pack ON pack_hourly_rollup(pack, hour_ts);
"""


# ── PackTracker ─────────────────────────────────────────────────────────


class PackTracker:
    """
    Tracks skill pack executions, cross-references with PIDs and
    ProcessMonitor categories, and persists to MetricsDB.

    Thread-safe singleton. Can be hooked into SkillRegistry for
    automatic tracking of all skill executions.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        max_history: int = 5000,
        rollup_interval: float = 3600.0,
    ):
        self._lock = threading.Lock()
        self._executions: List[SkillExecution] = []
        self._max_history = max_history
        self._rollup_interval = rollup_interval
        self._last_rollup: float = 0.0
        self._running = False
        self._hooked = False
        self._original_execute: Optional[Callable] = None
        self._original_mcp_call: Optional[Callable] = None

        # In-memory aggregates (fast path)
        self._pack_calls: Dict[str, int] = defaultdict(int)
        self._pack_durations: Dict[str, List[float]] = defaultdict(list)
        self._pack_cpu: Dict[str, float] = defaultdict(float)
        self._pack_pids: Dict[str, set] = defaultdict(set)
        self._pack_errors: Dict[str, int] = defaultdict(int)
        self._pack_skills: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._pack_last_exec: Dict[str, float] = {}

        # DB connection
        self._db_path = db_path
        self._db_local = threading.local()
        self._init_db()

    def _get_db(self):
        """Thread-local DB connection."""
        import sqlite3
        if not hasattr(self._db_local, "conn") or self._db_local.conn is None:
            if self._db_path:
                path = self._db_path
            else:
                from engine.paths import DATA_DIR
                path = str(DATA_DIR / "metrics.db")
            self._db_local.conn = sqlite3.connect(path, timeout=5)
            self._db_local.conn.row_factory = sqlite3.Row
            self._db_local.conn.execute("PRAGMA journal_mode=WAL")
            self._db_local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._db_local.conn

    def _init_db(self) -> None:
        """Initialize pack tracking tables."""
        try:
            conn = self._get_db()
            conn.executescript(_PACK_SCHEMA)
            conn.commit()
            logger.debug("PackTracker DB schema initialized")
        except Exception as exc:
            logger.warning("PackTracker DB init failed: %s", exc)

    # ── Core Recording ──────────────────────────────────────────────

    def record_execution(
        self,
        pack: str,
        skill_name: str,
        duration_s: float,
        pid: Optional[int] = None,
        cpu_before: float = 0.0,
        cpu_after: float = 0.0,
        memory_mb: float = 0.0,
        success: bool = True,
        error: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SkillExecution:
        """Record a skill execution with full metrics.

        Args:
            pack: Skill pack name (e.g., "world", "system", "workspace").
            skill_name: Individual skill name.
            duration_s: Wall-clock execution time in seconds.
            pid: Process ID that executed the skill.
            cpu_before: Process CPU seconds before execution.
            cpu_after: Process CPU seconds after execution.
            memory_mb: Peak memory usage during execution.
            success: Whether execution succeeded.
            error: Error message if failed.
            metadata: Additional metadata dict.

        Returns:
            The recorded SkillExecution.
        """
        if pid is None:
            pid = os.getpid()

        now = time.time()
        execution = SkillExecution(
            pack=pack,
            skill_name=skill_name,
            duration_s=duration_s,
            timestamp=now,
            pid=pid,
            cpu_seconds_before=cpu_before,
            cpu_seconds_after=cpu_after,
            memory_mb=memory_mb,
            success=success,
            error=error,
            metadata=metadata or {},
        )

        with self._lock:
            self._executions.append(execution)
            if len(self._executions) > self._max_history:
                self._executions = self._executions[-self._max_history:]

            # Update in-memory aggregates
            self._pack_calls[pack] += 1
            self._pack_durations[pack].append(duration_s)
            self._pack_cpu[pack] += execution.cpu_delta
            self._pack_pids[pack].add(pid)
            self._pack_skills[pack][skill_name] += 1
            self._pack_last_exec[pack] = now
            if not success:
                self._pack_errors[pack] += 1

            # Keep duration lists bounded
            if len(self._pack_durations[pack]) > 1000:
                self._pack_durations[pack] = self._pack_durations[pack][-1000:]

        # Persist to DB (non-blocking)
        self._persist_execution(execution)

        # Cross-reference PID with ProcessMonitor category
        self._record_pid_mapping(pack, pid)

        # Check if hourly rollup needed
        if now - self._last_rollup > self._rollup_interval:
            self._do_rollup()

        return execution

    def _persist_execution(self, ex: SkillExecution) -> None:
        """Write execution to SQLite."""
        try:
            import json
            conn = self._get_db()
            conn.execute(
                "INSERT INTO pack_executions "
                "(ts, pack, skill_name, duration_s, cpu_delta_s, memory_mb, "
                "pid, success, error, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ex.timestamp, ex.pack, ex.skill_name, ex.duration_s,
                    ex.cpu_delta, ex.memory_mb, ex.pid,
                    1 if ex.success else 0, ex.error,
                    json.dumps(ex.metadata, default=str),
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.debug("Failed to persist pack execution: %s", exc)

    def _record_pid_mapping(self, pack: str, pid: int) -> None:
        """Cross-reference PID with ProcessMonitor for category mapping."""
        try:
            from engine.system.process_monitor import get_process_monitor
            pm = get_process_monitor()
            proc_info = pm.get_process(pid)
            if proc_info:
                conn = self._get_db()
                conn.execute(
                    "INSERT INTO pack_pid_map "
                    "(ts, pack, pid, cpu_seconds, memory_mb, process_category, process_name) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        time.time(), pack, pid,
                        proc_info.cpu_seconds, proc_info.memory_mb,
                        proc_info.category.value, proc_info.name,
                    ),
                )
                conn.commit()
        except Exception:
            logger.debug("PID mapping failed for pack=%s pid=%s", pack, pid, exc_info=True)

    def _do_rollup(self) -> None:
        """Compute and store hourly rollup aggregates."""
        now = time.time()
        hour_ts = now - (now % 3600)

        with self._lock:
            self._last_rollup = now

        try:
            conn = self._get_db()
            cutoff = hour_ts - 3600
            cur = conn.execute(
                "SELECT pack, COUNT(*) as cnt, "
                "SUM(duration_s) as total_dur, "
                "SUM(cpu_delta_s) as total_cpu, "
                "AVG(duration_s) as avg_dur, "
                "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as err_cnt "
                "FROM pack_executions WHERE ts >= ? AND ts < ? "
                "GROUP BY pack",
                (cutoff, hour_ts),
            )
            rows = cur.fetchall()

            for row in rows:
                # Compute p95 from raw data
                dur_cur = conn.execute(
                    "SELECT duration_s FROM pack_executions "
                    "WHERE pack = ? AND ts >= ? AND ts < ? ORDER BY duration_s",
                    (row["pack"], cutoff, hour_ts),
                )
                durations = [r["duration_s"] for r in dur_cur.fetchall()]
                p95 = self._percentile(durations, 95) if durations else 0.0

                conn.execute(
                    "INSERT OR REPLACE INTO pack_hourly_rollup "
                    "(hour_ts, pack, call_count, total_duration_s, total_cpu_s, "
                    "avg_duration_s, p95_duration_s, error_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        hour_ts, row["pack"], row["cnt"],
                        row["total_dur"] or 0.0, row["total_cpu"] or 0.0,
                        row["avg_dur"] or 0.0, p95, row["err_cnt"] or 0,
                    ),
                )
            conn.commit()
        except Exception as exc:
            logger.debug("Hourly rollup failed: %s", exc)

    # ── Query API ───────────────────────────────────────────────────

    def pack_summary(self, hours: float = 24.0) -> Dict[str, PackActivity]:
        """Get aggregated activity for all packs over the last N hours.

        Args:
            hours: Lookback window in hours.

        Returns:
            Dict mapping pack name to PackActivity.
        """
        cutoff = time.time() - (hours * 3600)
        result: Dict[str, PackActivity] = {}

        try:
            conn = self._get_db()

            # Main aggregation
            cur = conn.execute(
                "SELECT pack, COUNT(*) as cnt, "
                "SUM(duration_s) as total_dur, "
                "SUM(cpu_delta_s) as total_cpu, "
                "AVG(duration_s) as avg_dur, "
                "MAX(memory_mb) as peak_mem, "
                "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as ok_cnt, "
                "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as err_cnt, "
                "MAX(ts) as last_ts "
                "FROM pack_executions WHERE ts >= ? "
                "GROUP BY pack ORDER BY total_cpu DESC",
                (cutoff,),
            )

            for row in cur.fetchall():
                pack = row["pack"]
                activity = PackActivity(
                    pack=pack,
                    total_calls=row["cnt"],
                    total_duration_s=row["total_dur"] or 0.0,
                    total_cpu_seconds=row["total_cpu"] or 0.0,
                    total_memory_mb_peak=row["peak_mem"] or 0.0,
                    success_count=row["ok_cnt"] or 0,
                    error_count=row["err_cnt"] or 0,
                    avg_duration_s=row["avg_dur"] or 0.0,
                    last_execution=row["last_ts"] or 0.0,
                )

                # Compute percentiles
                dur_cur = conn.execute(
                    "SELECT duration_s FROM pack_executions "
                    "WHERE pack = ? AND ts >= ? ORDER BY duration_s",
                    (pack, cutoff),
                )
                durations = [r["duration_s"] for r in dur_cur.fetchall()]
                if durations:
                    activity.p95_duration_s = self._percentile(durations, 95)
                    activity.p99_duration_s = self._percentile(durations, 99)
                    activity.avg_cpu_seconds = (
                        activity.total_cpu_seconds / max(activity.total_calls, 1)
                    )

                # Associated PIDs
                pid_cur = conn.execute(
                    "SELECT DISTINCT pid FROM pack_pid_map WHERE pack = ?", (pack,)
                )
                activity.associated_pids = [r["pid"] for r in pid_cur.fetchall()]

                # Associated categories
                cat_cur = conn.execute(
                    "SELECT DISTINCT process_category FROM pack_pid_map WHERE pack = ?",
                    (pack,),
                )
                activity.associated_categories = [r["process_category"] for r in cat_cur.fetchall()]

                # Skills breakdown
                skill_cur = conn.execute(
                    "SELECT skill_name, COUNT(*) as cnt FROM pack_executions "
                    "WHERE pack = ? AND ts >= ? GROUP BY skill_name ORDER BY cnt DESC",
                    (pack, cutoff),
                )
                activity.skills_used = {r["skill_name"]: r["cnt"] for r in skill_cur.fetchall()}

                result[pack] = activity

        except Exception as exc:
            logger.debug("Pack summary query failed: %s", exc)

        return result

    def pack_processes(self, pack: str, hours: float = 1.0) -> List[Dict[str, Any]]:
        """Get PIDs associated with a pack and their resource usage.

        Args:
            pack: Pack name to query.
            hours: Lookback window in hours.

        Returns:
            List of dicts with PID, CPU, memory, category info.
        """
        cutoff = time.time() - (hours * 3600)
        try:
            conn = self._get_db()
            cur = conn.execute(
                "SELECT pid, process_name, process_category, "
                "MAX(cpu_seconds) as cpu_s, MAX(memory_mb) as mem_mb, "
                "COUNT(*) as exec_count "
                "FROM pack_pid_map WHERE pack = ? AND ts >= ? "
                "GROUP BY pid ORDER BY cpu_s DESC",
                (pack, cutoff),
            )
            return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.debug("Pack processes query failed: %s", exc)
            return []

    def top_packs(self, n: int = 10, sort_by: str = "cpu") -> List[Dict[str, Any]]:
        """Get top N packs by CPU time, call count, or duration.

        Args:
            n: Number of top packs to return.
            sort_by: Sort field — "cpu", "calls", "duration", "errors".

        Returns:
            List of pack summary dicts.
        """
        summary = self.pack_summary(hours=24.0)
        packs = list(summary.values())

        sort_key = {
            "cpu": lambda p: p.total_cpu_seconds,
            "calls": lambda p: p.total_calls,
            "duration": lambda p: p.total_duration_s,
            "errors": lambda p: p.error_count,
        }.get(sort_by, lambda p: p.total_cpu_seconds)

        packs.sort(key=sort_key, reverse=True)
        return [p.to_dict() for p in packs[:n]]

    def cross_reference(self, hours: float = 24.0) -> Dict[str, Any]:
        """Cross-reference packs with ProcessMonitor categories.

        Returns a matrix showing which packs use which process categories,
        with CPU time and memory breakdowns.

        Args:
            hours: Lookback window in hours.

        Returns:
            Dict with matrix data: {pack: {category: {cpu_s, mem_mb, count}}}.
        """
        cutoff = time.time() - (hours * 3600)
        matrix: Dict[str, Dict[str, Dict[str, float]]] = {}

        try:
            conn = self._get_db()
            cur = conn.execute(
                "SELECT pack, process_category, "
                "SUM(cpu_seconds) as total_cpu, "
                "MAX(memory_mb) as peak_mem, "
                "COUNT(*) as mapping_count "
                "FROM pack_pid_map WHERE ts >= ? "
                "GROUP BY pack, process_category",
                (cutoff,),
            )

            for row in cur.fetchall():
                pack = row["pack"]
                cat = row["process_category"]
                if pack not in matrix:
                    matrix[pack] = {}
                matrix[pack][cat] = {
                    "cpu_seconds": round(row["total_cpu"] or 0.0, 2),
                    "memory_mb_peak": round(row["peak_mem"] or 0.0, 1),
                    "execution_count": row["mapping_count"],
                }
        except Exception as exc:
            logger.debug("Cross-reference query failed: %s", exc)

        return matrix

    def skill_leaderboard(self, hours: float = 24.0, top_n: int = 20) -> List[Dict[str, Any]]:
        """Get top N individual skills by execution count and CPU time.

        Args:
            hours: Lookback window in hours.
            top_n: Number of skills to return.

        Returns:
            List of skill performance dicts.
        """
        cutoff = time.time() - (hours * 3600)
        try:
            conn = self._get_db()
            cur = conn.execute(
                "SELECT skill_name, pack, COUNT(*) as cnt, "
                "SUM(duration_s) as total_dur, "
                "SUM(cpu_delta_s) as total_cpu, "
                "AVG(duration_s) as avg_dur, "
                "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as err_cnt "
                "FROM pack_executions WHERE ts >= ? "
                "GROUP BY skill_name, pack ORDER BY total_cpu DESC LIMIT ?",
                (cutoff, top_n),
            )
            return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.debug("Skill leaderboard query failed: %s", exc)
            return []

    def recent_executions(self, n: int = 50, pack: str = "") -> List[Dict[str, Any]]:
        """Get the N most recent skill executions.

        Args:
            n: Number of executions to return.
            pack: Optional pack filter.

        Returns:
            List of execution dicts.
        """
        try:
            conn = self._get_db()
            if pack:
                cur = conn.execute(
                    "SELECT * FROM pack_executions WHERE pack = ? "
                    "ORDER BY ts DESC LIMIT ?",
                    (pack, n),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM pack_executions ORDER BY ts DESC LIMIT ?", (n,)
                )
            return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.debug("Recent executions query failed: %s", exc)
            return []

    def hourly_trends(self, pack: str = "", hours: int = 24) -> List[Dict[str, Any]]:
        """Get hourly rollup trends for a pack or all packs.

        Args:
            pack: Optional pack filter (empty = all).
            hours: Number of hours to look back.

        Returns:
            List of hourly rollup dicts.
        """
        cutoff = time.time() - (hours * 3600)
        try:
            conn = self._get_db()
            if pack:
                cur = conn.execute(
                    "SELECT * FROM pack_hourly_rollup "
                    "WHERE pack = ? AND hour_ts >= ? ORDER BY hour_ts",
                    (pack, cutoff),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM pack_hourly_rollup "
                    "WHERE hour_ts >= ? ORDER BY hour_ts",
                    (cutoff,),
                )
            return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.debug("Hourly trends query failed: %s", exc)
            return []

    # ── Hook into SkillRegistry ─────────────────────────────────────

    def hook_skill_registry(self) -> bool:
        """Monkey-patch SkillRegistry.execute_skill to auto-track executions.

        Returns:
            True if hooked successfully, False otherwise.
        """
        if self._hooked:
            return True

        try:
            from engine.skills.registry import SKILL_REGISTRY
            import psutil

            original = SKILL_REGISTRY.execute_skill

            def tracked_execute(name: str, *args, **kwargs):
                meta = SKILL_REGISTRY.get_skill(name)
                pack_name = meta.pack if meta else "unknown"

                pid = os.getpid()
                try:
                    proc = psutil.Process(pid)
                    cpu_before = proc.cpu_times().user + proc.cpu_times().system
                    mem_before = proc.memory_info().rss / (1024 * 1024)
                except Exception:
                    cpu_before = 0.0
                    mem_before = 0.0

                start = time.time()
                success = True
                error_msg = ""
                try:
                    result = original(name, *args, **kwargs)
                    return result
                except Exception as exc:
                    success = False
                    error_msg = str(exc)
                    raise
                finally:
                    duration = time.time() - start
                    try:
                        proc = psutil.Process(pid)
                        cpu_after = proc.cpu_times().user + proc.cpu_times().system
                        mem_after = proc.memory_info().rss / (1024 * 1024)
                    except Exception:
                        cpu_after = cpu_before
                        mem_after = mem_before

                    self.record_execution(
                        pack=pack_name,
                        skill_name=name,
                        duration_s=duration,
                        pid=pid,
                        cpu_before=cpu_before,
                        cpu_after=cpu_after,
                        memory_mb=max(mem_before, mem_after),
                        success=success,
                        error=error_msg,
                    )

            SKILL_REGISTRY.execute_skill = tracked_execute
            self._original_execute = original
            self._hooked = True
            logger.info("PackTracker hooked into SkillRegistry.execute_skill")
            return True

        except Exception as exc:
            logger.warning("Failed to hook SkillRegistry: %s", exc)
            return False

    def unhook_skill_registry(self) -> None:
        """Restore original SkillRegistry.execute_skill."""
        if self._hooked and self._original_execute:
            try:
                from engine.skills.registry import SKILL_REGISTRY
                SKILL_REGISTRY.execute_skill = self._original_execute
                self._hooked = False
                self._original_execute = None
                logger.info("PackTracker unhooked from SkillRegistry")
            except Exception as exc:
                logger.warning("Failed to unhook SkillRegistry: %s", exc)

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self) -> None:
        """Start pack tracking — hooks into SkillRegistry."""
        if self._running:
            return
        self._running = True
        self.hook_skill_registry()
        logger.info("PackTracker started")

    def stop(self) -> None:
        """Stop pack tracking — unhooks from SkillRegistry."""
        self._running = False
        self.unhook_skill_registry()
        logger.info("PackTracker stopped")

    # ── Maintenance ─────────────────────────────────────────────────

    def prune(self, max_age_hours: float = 168.0) -> int:
        """Delete pack executions older than max_age_hours (default 7 days).

        Args:
            max_age_hours: Maximum age in hours.

        Returns:
            Number of rows deleted.
        """
        cutoff = time.time() - (max_age_hours * 3600)
        total = 0
        try:
            conn = self._get_db()
            cur = conn.execute("DELETE FROM pack_executions WHERE ts < ?", (cutoff,))
            total += cur.rowcount
            cur = conn.execute("DELETE FROM pack_pid_map WHERE ts < ?", (cutoff,))
            total += cur.rowcount
            cur = conn.execute("DELETE FROM pack_hourly_rollup WHERE hour_ts < ?", (cutoff,))
            total += cur.rowcount
            conn.commit()
        except Exception as exc:
            logger.debug("Pack prune failed: %s", exc)
        return total

    def snapshot(self) -> Dict[str, Any]:
        """Full pack tracker snapshot for dashboard consumption.

        Returns:
            Dict with summary, top packs, cross-reference, and recent executions.
        """
        with self._lock:
            total_calls = sum(self._pack_calls.values())
            total_cpu = sum(self._pack_cpu.values())
            active_packs = len(self._pack_calls)

        return {
            "total_calls": total_calls,
            "total_cpu_seconds": round(total_cpu, 2),
            "active_packs": active_packs,
            "hooked": self._hooked,
            "running": self._running,
            "top_packs": self.top_packs(5),
            "cross_reference": self.cross_reference(hours=1.0),
        }

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _percentile(data: List[float], pct: float) -> float:
        """Compute the p-th percentile of a sorted list."""
        if not data:
            return 0.0
        k = (len(data) - 1) * (pct / 100.0)
        f = int(k)
        c = f + 1
        if c >= len(data):
            return data[-1]
        return data[f] + (k - f) * (data[c] - data[f])
