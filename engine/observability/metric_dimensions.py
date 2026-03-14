"""Dimensional metrics store for CosySim.

Extends the fixed-column metrics system with arbitrary tag/dimension support,
enabling metrics to be sliced by any combination of dimensions (model_type,
agent_id, scene_name, request_type, etc.).

Backed by SQLite with two tables:
  - dimensional_metrics  — timestamped metric values
  - metric_tags          — key/value pairs linked to each metric row

Thread-safe via threading.Lock.  Singleton access via get_dimension_store().
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

from engine.paths import DATA_DIR

logger = logging.getLogger(__name__)

_DEFAULT_PATH: Path = DATA_DIR / "metric_dimensions.db"


# ──── Data Models ────────────────────────────────────────────────────────────


@dataclass
class DimensionalMetric:
    """A metric value with arbitrary tag dimensions.

    Attributes:
        name: Metric name (e.g. ``"latency_ms"``, ``"accuracy"``).
        value: Numeric metric value.
        tags: Arbitrary dimension key/value pairs.
        timestamp: Epoch seconds; defaults to current time.
    """

    name: str
    value: float
    tags: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AggregationResult:
    """Result of a multi-dimensional aggregation query.

    Attributes:
        group_key: Dimension values that identify this group.
        count: Number of data points in the group.
        mean: Arithmetic mean.
        min_val: Minimum observed value.
        max_val: Maximum observed value.
        sum_val: Sum of all values.
        stddev: Population standard deviation.
        p50: 50th-percentile (median).
        p95: 95th-percentile.
        p99: 99th-percentile.
    """

    group_key: Dict[str, str]
    count: int
    mean: float
    min_val: float
    max_val: float
    sum_val: float
    stddev: float
    p50: float
    p95: float
    p99: float


@dataclass
class TagCardinality:
    """Cardinality information for a tag key.

    Attributes:
        key: Tag key name.
        unique_values: Number of distinct values.
        total_uses: Total number of times this key appears.
        sample_values: Up to 10 most common values.
    """

    key: str
    unique_values: int
    total_uses: int
    sample_values: List[str]


# ──── Statistics Helpers ─────────────────────────────────────────────────────


def _percentile(sorted_values: List[float], p: float) -> float:
    """Compute interpolated percentile from pre-sorted values.

    Args:
        sorted_values: Values sorted in ascending order.  Must be non-empty.
        p: Percentile in ``[0, 100]``.

    Returns:
        Interpolated percentile value.
    """
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]

    # Rank uses 0-based indexing scaled to [0, n-1]
    rank = (p / 100.0) * (n - 1)
    lower = int(math.floor(rank))
    upper = min(lower + 1, n - 1)
    fraction = rank - lower
    return sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower])


def _stddev(values: List[float], mean: float) -> float:
    """Compute population standard deviation.

    Args:
        values: List of numeric values.
        mean: Pre-computed arithmetic mean.

    Returns:
        Population standard deviation (σ).
    """
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _compute_stats(values: List[float]) -> Dict[str, float]:
    """Compute a full statistics summary for a list of values.

    Args:
        values: Non-empty list of numeric values.

    Returns:
        Dict with keys: count, mean, min, max, sum, stddev, p50, p95, p99.
    """
    n = len(values)
    total = sum(values)
    mean = total / n
    sorted_vals = sorted(values)
    return {
        "count": n,
        "mean": mean,
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
        "sum": total,
        "stddev": _stddev(values, mean),
        "p50": _percentile(sorted_vals, 50),
        "p95": _percentile(sorted_vals, 95),
        "p99": _percentile(sorted_vals, 99),
    }


# ──── DimensionStore ─────────────────────────────────────────────────────────


class DimensionStore:
    """SQLite-backed dimensional metrics store.

    Provides recording, querying, aggregation, and pruning of metrics with
    arbitrary tag dimensions.  All public methods are thread-safe.

    Args:
        db_path: Path to the SQLite database file.  Parent directories are
            created automatically.
    """

    _SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS dimensional_metrics (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      REAL    NOT NULL,
        name    TEXT    NOT NULL,
        value   REAL    NOT NULL,
        tags_json TEXT  NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_dm_ts      ON dimensional_metrics(ts);
    CREATE INDEX IF NOT EXISTS idx_dm_name    ON dimensional_metrics(name);
    CREATE INDEX IF NOT EXISTS idx_dm_name_ts ON dimensional_metrics(name, ts);

    CREATE TABLE IF NOT EXISTS metric_tags (
        metric_id INTEGER NOT NULL,
        key       TEXT    NOT NULL,
        value     TEXT    NOT NULL,
        FOREIGN KEY (metric_id) REFERENCES dimensional_metrics(id)
    );
    CREATE INDEX IF NOT EXISTS idx_mt_key_value ON metric_tags(key, value);
    CREATE INDEX IF NOT EXISTS idx_mt_metric_id ON metric_tags(metric_id);
    """

    def __init__(self, db_path: str = "data/metric_dimensions.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_schema()
        logger.info(f"DimensionStore initialised at {self._db_path}")

    # ── Connection management ────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Return a per-thread SQLite connection with WAL mode.

        Returns:
            Thread-local ``sqlite3.Connection``.
        """
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """Context manager that yields a cursor and auto-commits / rollbacks.

        Yields:
            ``sqlite3.Cursor`` within a transaction.
        """
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._lock:
            with self._cursor() as cur:
                cur.executescript(self._SCHEMA_SQL)
            logger.debug("DimensionStore schema verified")

    # ── Recording ────────────────────────────────────────────────────────

    def record(
        self,
        name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None,
        timestamp: Optional[float] = None,
    ) -> int:
        """Store a single metric with optional tag dimensions.

        Args:
            name: Metric name.
            value: Numeric value.
            tags: Arbitrary key/value dimension pairs.
            timestamp: Epoch seconds; defaults to ``time.time()``.

        Returns:
            The ``metric_id`` of the inserted row.
        """
        ts = timestamp if timestamp is not None else time.time()
        tags = tags or {}
        tags_json = json.dumps(tags, sort_keys=True)

        with self._lock:
            with self._cursor() as cur:
                cur.execute(
                    "INSERT INTO dimensional_metrics (ts, name, value, tags_json) "
                    "VALUES (?, ?, ?, ?)",
                    (ts, name, value, tags_json),
                )
                metric_id: int = cur.lastrowid  # type: ignore[assignment]

                if tags:
                    cur.executemany(
                        "INSERT INTO metric_tags (metric_id, key, value) VALUES (?, ?, ?)",
                        [(metric_id, k, v) for k, v in tags.items()],
                    )

        logger.debug(f"Recorded metric {name}={value} id={metric_id} tags={tags}")
        return metric_id

    def record_batch(self, metrics: List[DimensionalMetric]) -> List[int]:
        """Bulk-insert multiple dimensional metrics in a single transaction.

        Args:
            metrics: List of ``DimensionalMetric`` instances.

        Returns:
            List of inserted ``metric_id`` values (same order as input).
        """
        if not metrics:
            return []

        ids: List[int] = []
        with self._lock:
            with self._cursor() as cur:
                for m in metrics:
                    tags_json = json.dumps(m.tags, sort_keys=True)
                    cur.execute(
                        "INSERT INTO dimensional_metrics (ts, name, value, tags_json) "
                        "VALUES (?, ?, ?, ?)",
                        (m.timestamp, m.name, m.value, tags_json),
                    )
                    metric_id: int = cur.lastrowid  # type: ignore[assignment]
                    ids.append(metric_id)

                    if m.tags:
                        cur.executemany(
                            "INSERT INTO metric_tags (metric_id, key, value) "
                            "VALUES (?, ?, ?)",
                            [(metric_id, k, v) for k, v in m.tags.items()],
                        )

        logger.debug(f"Batch-recorded {len(ids)} metrics")
        return ids

    # ── Querying ─────────────────────────────────────────────────────────

    def query(
        self,
        name: str,
        filters: Optional[Dict[str, str]] = None,
        group_by: Optional[List[str]] = None,
        window_seconds: Optional[float] = None,
        limit: int = 1000,
    ) -> Union[List[DimensionalMetric], List[AggregationResult]]:
        """Query dimensional metrics with optional filtering, grouping, and windowing.

        If ``group_by`` is provided, returns aggregated results grouped by
        the specified tag keys.  Otherwise returns raw ``DimensionalMetric``
        rows.

        Args:
            name: Metric name to query.
            filters: Tag key/value pairs that must match exactly.
            group_by: Tag keys to group by for aggregation.
            window_seconds: Lookback window from now (epoch seconds).
            limit: Maximum rows returned (raw mode only).

        Returns:
            A list of ``DimensionalMetric`` or ``AggregationResult`` depending
            on whether ``group_by`` is set.
        """
        filters = filters or {}

        if group_by:
            return self._query_aggregated(name, filters, group_by, window_seconds)
        return self._query_raw(name, filters, window_seconds, limit)

    def _build_filter_clauses(
        self,
        name: str,
        filters: Dict[str, str],
        window_seconds: Optional[float],
    ) -> Tuple[str, List[Any]]:
        """Build WHERE clause fragments and params for metric queries.

        Args:
            name: Metric name.
            filters: Tag filters.
            window_seconds: Optional lookback window.

        Returns:
            Tuple of (WHERE clause string, parameter list).
        """
        clauses: List[str] = ["dm.name = ?"]
        params: List[Any] = [name]

        if window_seconds is not None:
            cutoff = time.time() - window_seconds
            clauses.append("dm.ts >= ?")
            params.append(cutoff)

        for key, val in filters.items():
            clauses.append(
                "dm.id IN (SELECT metric_id FROM metric_tags WHERE key = ? AND value = ?)"
            )
            params.extend([key, val])

        where = " AND ".join(clauses)
        return where, params

    def _query_raw(
        self,
        name: str,
        filters: Dict[str, str],
        window_seconds: Optional[float],
        limit: int,
    ) -> List[DimensionalMetric]:
        """Return raw metric rows matching the criteria.

        Args:
            name: Metric name.
            filters: Tag filters.
            window_seconds: Optional lookback window.
            limit: Max rows.

        Returns:
            List of ``DimensionalMetric``.
        """
        where, params = self._build_filter_clauses(name, filters, window_seconds)
        params.append(limit)

        with self._lock:
            with self._cursor() as cur:
                cur.execute(
                    f"SELECT id, ts, name, value, tags_json "
                    f"FROM dimensional_metrics dm "
                    f"WHERE {where} "
                    f"ORDER BY dm.ts DESC LIMIT ?",
                    params,
                )
                rows = cur.fetchall()

        results: List[DimensionalMetric] = []
        for row in rows:
            tags = json.loads(row["tags_json"]) if row["tags_json"] else {}
            results.append(
                DimensionalMetric(
                    name=row["name"],
                    value=row["value"],
                    tags=tags,
                    timestamp=row["ts"],
                )
            )
        return results

    def _query_aggregated(
        self,
        name: str,
        filters: Dict[str, str],
        group_by: List[str],
        window_seconds: Optional[float],
    ) -> List[AggregationResult]:
        """Return aggregated results grouped by specified tag keys.

        Fetches matching metric IDs, then groups in Python to compute full
        statistics including percentiles.

        Args:
            name: Metric name.
            filters: Tag filters.
            group_by: Tag keys to group by.
            window_seconds: Optional lookback window.

        Returns:
            List of ``AggregationResult``.
        """
        where, params = self._build_filter_clauses(name, filters, window_seconds)

        with self._lock:
            with self._cursor() as cur:
                # Fetch all matching metrics
                cur.execute(
                    f"SELECT id, value, tags_json "
                    f"FROM dimensional_metrics dm "
                    f"WHERE {where} "
                    f"ORDER BY dm.ts",
                    params,
                )
                rows = cur.fetchall()

        # Group values by the requested tag keys
        groups: Dict[Tuple[Tuple[str, str], ...], List[float]] = {}
        for row in rows:
            tags = json.loads(row["tags_json"]) if row["tags_json"] else {}
            key_parts = tuple((k, tags.get(k, "")) for k in group_by)
            groups.setdefault(key_parts, []).append(row["value"])

        results: List[AggregationResult] = []
        for key_parts, values in groups.items():
            group_key = dict(key_parts)
            stats = _compute_stats(values)
            results.append(
                AggregationResult(
                    group_key=group_key,
                    count=int(stats["count"]),
                    mean=stats["mean"],
                    min_val=stats["min"],
                    max_val=stats["max"],
                    sum_val=stats["sum"],
                    stddev=stats["stddev"],
                    p50=stats["p50"],
                    p95=stats["p95"],
                    p99=stats["p99"],
                )
            )

        return results

    # ── Tag introspection ────────────────────────────────────────────────

    def get_tag_cardinality(self, name: Optional[str] = None) -> List[TagCardinality]:
        """Report cardinality statistics for each tag key.

        Args:
            name: If provided, restrict to tags on metrics with this name.

        Returns:
            List of ``TagCardinality`` for each distinct tag key.
        """
        with self._lock:
            with self._cursor() as cur:
                if name is not None:
                    cur.execute(
                        "SELECT mt.key, COUNT(DISTINCT mt.value) AS uniq, COUNT(*) AS total "
                        "FROM metric_tags mt "
                        "JOIN dimensional_metrics dm ON mt.metric_id = dm.id "
                        "WHERE dm.name = ? "
                        "GROUP BY mt.key ORDER BY total DESC",
                        (name,),
                    )
                else:
                    cur.execute(
                        "SELECT key, COUNT(DISTINCT value) AS uniq, COUNT(*) AS total "
                        "FROM metric_tags "
                        "GROUP BY key ORDER BY total DESC",
                    )
                key_rows = cur.fetchall()

                results: List[TagCardinality] = []
                for kr in key_rows:
                    tag_key = kr["key"]
                    # Fetch top-10 most common values for this key
                    if name is not None:
                        cur.execute(
                            "SELECT mt.value, COUNT(*) AS cnt "
                            "FROM metric_tags mt "
                            "JOIN dimensional_metrics dm ON mt.metric_id = dm.id "
                            "WHERE mt.key = ? AND dm.name = ? "
                            "GROUP BY mt.value ORDER BY cnt DESC LIMIT 10",
                            (tag_key, name),
                        )
                    else:
                        cur.execute(
                            "SELECT value, COUNT(*) AS cnt "
                            "FROM metric_tags "
                            "WHERE key = ? "
                            "GROUP BY value ORDER BY cnt DESC LIMIT 10",
                            (tag_key,),
                        )
                    sample_rows = cur.fetchall()
                    samples = [r["value"] for r in sample_rows]

                    results.append(
                        TagCardinality(
                            key=tag_key,
                            unique_values=kr["uniq"],
                            total_uses=kr["total"],
                            sample_values=samples,
                        )
                    )

        return results

    def get_tag_values(self, key: str, name: Optional[str] = None) -> List[str]:
        """Return all unique values for a given tag key.

        Args:
            key: Tag key to inspect.
            name: If provided, restrict to metrics with this name.

        Returns:
            Sorted list of unique tag values.
        """
        with self._lock:
            with self._cursor() as cur:
                if name is not None:
                    cur.execute(
                        "SELECT DISTINCT mt.value "
                        "FROM metric_tags mt "
                        "JOIN dimensional_metrics dm ON mt.metric_id = dm.id "
                        "WHERE mt.key = ? AND dm.name = ? "
                        "ORDER BY mt.value",
                        (key, name),
                    )
                else:
                    cur.execute(
                        "SELECT DISTINCT value FROM metric_tags "
                        "WHERE key = ? ORDER BY value",
                        (key,),
                    )
                return [r["value"] for r in cur.fetchall()]

    def get_metric_names(self) -> List[str]:
        """Return all unique metric names in the store.

        Returns:
            Sorted list of metric name strings.
        """
        with self._lock:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT name FROM dimensional_metrics ORDER BY name"
                )
                return [r["name"] for r in cur.fetchall()]

    # ── Summary ──────────────────────────────────────────────────────────

    def get_summary(
        self,
        name: str,
        window_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Compute aggregate statistics for a named metric.

        Args:
            name: Metric name to summarise.
            window_seconds: Optional lookback window from now.

        Returns:
            Dict with keys: count, mean, min, max, stddev, p50, p95, p99.
            Returns an empty dict if no data matches.
        """
        clauses: List[str] = ["name = ?"]
        params: List[Any] = [name]

        if window_seconds is not None:
            cutoff = time.time() - window_seconds
            clauses.append("ts >= ?")
            params.append(cutoff)

        where = " AND ".join(clauses)

        with self._lock:
            with self._cursor() as cur:
                cur.execute(
                    f"SELECT value FROM dimensional_metrics WHERE {where} ORDER BY ts",
                    params,
                )
                rows = cur.fetchall()

        if not rows:
            logger.debug(f"No data for metric '{name}'")
            return {}

        values = [r["value"] for r in rows]
        stats = _compute_stats(values)
        return {
            "count": int(stats["count"]),
            "mean": stats["mean"],
            "min": stats["min"],
            "max": stats["max"],
            "stddev": stats["stddev"],
            "p50": stats["p50"],
            "p95": stats["p95"],
            "p99": stats["p99"],
        }

    # ── Pruning ──────────────────────────────────────────────────────────

    def prune(self, older_than_seconds: float) -> int:
        """Delete metrics older than the given threshold.

        Also removes orphaned rows from the ``metric_tags`` table.

        Args:
            older_than_seconds: Age threshold in seconds from now.

        Returns:
            Number of metric rows deleted.
        """
        cutoff = time.time() - older_than_seconds

        with self._lock:
            with self._cursor() as cur:
                # Remove tag rows first (foreign-key safe)
                cur.execute(
                    "DELETE FROM metric_tags WHERE metric_id IN "
                    "(SELECT id FROM dimensional_metrics WHERE ts < ?)",
                    (cutoff,),
                )
                cur.execute(
                    "DELETE FROM dimensional_metrics WHERE ts < ?",
                    (cutoff,),
                )
                deleted: int = cur.rowcount  # type: ignore[assignment]

        if deleted:
            logger.info(f"Pruned {deleted} dimensional metrics older than {older_than_seconds}s")
        return deleted

    # ── Export ────────────────────────────────────────────────────────────

    def export_for_analysis(
        self,
        name: str,
        filters: Optional[Dict[str, str]] = None,
        window_seconds: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Export metrics as flat dicts suitable for downstream analysis.

        Each dict contains ``name``, ``value``, ``timestamp``, plus all tag
        keys flattened as top-level fields prefixed with ``tag_``.

        Args:
            name: Metric name to export.
            filters: Optional tag filters.
            window_seconds: Optional lookback window.

        Returns:
            List of flat dicts.
        """
        filters = filters or {}
        where, params = self._build_filter_clauses(name, filters, window_seconds)

        with self._lock:
            with self._cursor() as cur:
                cur.execute(
                    f"SELECT id, ts, name, value, tags_json "
                    f"FROM dimensional_metrics dm "
                    f"WHERE {where} "
                    f"ORDER BY dm.ts",
                    params,
                )
                rows = cur.fetchall()

        results: List[Dict[str, Any]] = []
        for row in rows:
            record: Dict[str, Any] = {
                "name": row["name"],
                "value": row["value"],
                "timestamp": row["ts"],
            }
            tags = json.loads(row["tags_json"]) if row["tags_json"] else {}
            for k, v in tags.items():
                record[f"tag_{k}"] = v
            results.append(record)

        logger.debug(f"Exported {len(results)} records for '{name}'")
        return results


# ──── Singleton ──────────────────────────────────────────────────────────────

_instance: Optional[DimensionStore] = None
_singleton_lock = threading.Lock()


def get_dimension_store(db_path: str = "data/metric_dimensions.db") -> DimensionStore:
    """Return the global DimensionStore singleton.

    Creates the instance on first call.  Subsequent calls return the same
    object regardless of ``db_path``.

    Args:
        db_path: Path to the SQLite database (only used on first call).

    Returns:
        The shared ``DimensionStore`` instance.
    """
    global _instance
    if _instance is None:
        with _singleton_lock:
            if _instance is None:
                _instance = DimensionStore(db_path)
    return _instance
