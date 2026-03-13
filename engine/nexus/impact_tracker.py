"""Impact Tracker — records system changes and measures their metric impact.

Provides a durable audit trail linking every configuration tweak, model
promotion, experiment result, or code deploy to the before/after metric
deltas it caused.  Results are stored in a local SQLite database and
optionally mirrored to Nexus for cross-session retrieval.
"""
from __future__ import annotations

import enum
import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/impact_tracker.db")

# Metrics where a *decrease* is an improvement (lower is better).
_INVERTED_METRICS = frozenset({
    "pipeline.avg_latency_ms",
    "pipeline.avg_ttft_ms",
    "pipeline.error_rate",
    "system.cpu_pct",
    "system.ram_pct",
    "system.gpu_vram_pct",
    "scheduler.failure_rate",
})


# ──── Enums ────────────────────────────────────────────────────────────────


class ChangeType(enum.Enum):
    """Categories of tracked system changes."""

    CONFIG_CHANGE = "config_change"
    MODEL_PROMOTION = "model_promotion"
    EXPERIMENT_RESULT = "experiment_result"
    CODE_DEPLOY = "code_deploy"
    KNOWLEDGE_UPDATE = "knowledge_update"
    SCHEDULER_CHANGE = "scheduler_change"
    RULE_UPDATE = "rule_update"


class ImpactSeverity(enum.Enum):
    """Bucketed severity for a metric delta.

    Thresholds (absolute percentage change):
        > +10 %  → POSITIVE_HIGH
        +1 – +10 % → POSITIVE_LOW
        -1 – +1 % → NEUTRAL
        -1 – -10 % → NEGATIVE_LOW
        < -10 %  → NEGATIVE_HIGH

    For inverted metrics (latency, error rate, CPU …) a *decrease* counts
    as a positive change.
    """

    POSITIVE_HIGH = "positive_high"
    POSITIVE_LOW = "positive_low"
    NEUTRAL = "neutral"
    NEGATIVE_LOW = "negative_low"
    NEGATIVE_HIGH = "negative_high"


# ──── Data Structures ─────────────────────────────────────────────────────


@dataclass
class SystemChange:
    """A single recorded system change."""

    change_id: str
    change_type: ChangeType
    title: str
    description: str
    timestamp: float
    source: str
    metadata: Dict[str, Any]
    baseline_snapshot_id: Optional[str] = None
    after_snapshot_id: Optional[str] = None
    impact_computed: bool = False


@dataclass
class MetricSnapshot:
    """Point-in-time metric capture linked to a change."""

    snapshot_id: str
    change_id: str
    phase: str
    timestamp: float
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class ImpactScore:
    """Computed delta for one metric between before/after snapshots."""

    change_id: str
    metric: str
    before_value: float
    after_value: float
    absolute_delta: float
    percentage_delta: float
    severity: ImpactSeverity
    confidence: float


# ──── Severity Classification ─────────────────────────────────────────────


def _classify_severity(pct_delta: float, metric: str) -> ImpactSeverity:
    """Map a percentage delta to an ``ImpactSeverity`` bucket.

    Args:
        pct_delta: Raw ``((after - before) / before) * 100``.
        metric: Metric name — used to check if the metric is inverted.

    Returns:
        The appropriate severity enum value.
    """
    effective = -pct_delta if metric in _INVERTED_METRICS else pct_delta

    if effective > 10.0:
        return ImpactSeverity.POSITIVE_HIGH
    if effective > 1.0:
        return ImpactSeverity.POSITIVE_LOW
    if effective >= -1.0:
        return ImpactSeverity.NEUTRAL
    if effective >= -10.0:
        return ImpactSeverity.NEGATIVE_LOW
    return ImpactSeverity.NEGATIVE_HIGH


# ──── ImpactTracker ───────────────────────────────────────────────────────


class ImpactTracker:
    """Records system changes and measures their impact on key metrics."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        cfg = get_config()
        resolved = db_path or Path(
            cfg.get("impact_tracker.db_path", str(_DEFAULT_DB_PATH))
        )
        self._path = Path(resolved)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()
        logger.info("ImpactTracker initialised (db=%s)", self._path)

    # ── DB helpers ────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection with WAL mode."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._path), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """Yield a cursor inside a commit/rollback transaction."""
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
        ddl = """
        CREATE TABLE IF NOT EXISTS changes (
            change_id TEXT PRIMARY KEY,
            change_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            timestamp REAL NOT NULL,
            source TEXT,
            metadata TEXT,
            baseline_snapshot_id TEXT,
            after_snapshot_id TEXT,
            impact_computed INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_changes_ts ON changes(timestamp);
        CREATE INDEX IF NOT EXISTS idx_changes_type ON changes(change_type);

        CREATE TABLE IF NOT EXISTS metric_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            timestamp REAL NOT NULL,
            metrics TEXT NOT NULL,
            FOREIGN KEY (change_id) REFERENCES changes(change_id)
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_change
            ON metric_snapshots(change_id);

        CREATE TABLE IF NOT EXISTS impact_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            change_id TEXT NOT NULL,
            metric TEXT NOT NULL,
            before_value REAL,
            after_value REAL,
            absolute_delta REAL,
            percentage_delta REAL,
            severity TEXT,
            confidence REAL,
            computed_at REAL,
            FOREIGN KEY (change_id) REFERENCES changes(change_id)
        );
        CREATE INDEX IF NOT EXISTS idx_impact_change
            ON impact_scores(change_id);
        CREATE INDEX IF NOT EXISTS idx_impact_severity
            ON impact_scores(severity);
        """
        conn = self._get_conn()
        conn.executescript(ddl)
        conn.commit()

    # ── Core API ──────────────────────────────────────────────────────

    def record_change(
        self,
        change_type: ChangeType,
        title: str,
        description: str,
        source: str = "manual",
        metadata: Optional[Dict[str, Any]] = None,
        auto_snapshot: bool = True,
    ) -> SystemChange:
        """Record a system change event.

        Args:
            change_type: Category of change.
            title: Short human-readable label.
            description: Detailed explanation.
            source: Originating subsystem or user.
            metadata: Arbitrary key/value context (config key, model, …).
            auto_snapshot: When ``True``, immediately capture baseline metrics.

        Returns:
            The persisted ``SystemChange`` dataclass.
        """
        change_id = f"chg-{uuid.uuid4().hex[:8]}"
        now = time.time()
        meta = metadata or {}

        change = SystemChange(
            change_id=change_id,
            change_type=change_type,
            title=title,
            description=description,
            timestamp=now,
            source=source,
            metadata=meta,
        )

        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO changes "
                "(change_id, change_type, title, description, timestamp, "
                " source, metadata, impact_computed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    change_id,
                    change_type.value,
                    title,
                    description,
                    now,
                    source,
                    json.dumps(meta),
                ),
            )

        logger.info(
            "Recorded change %s [%s] — %s", change_id, change_type.value, title
        )

        if auto_snapshot:
            snap = self.capture_snapshot(change_id, "before")
            change.baseline_snapshot_id = snap.snapshot_id

        return change

    def capture_snapshot(self, change_id: str, phase: str) -> MetricSnapshot:
        """Capture current system metrics as a snapshot linked to a change.

        Args:
            change_id: The change this snapshot belongs to.
            phase: ``"before"`` or ``"after"``.

        Returns:
            The persisted ``MetricSnapshot``.
        """
        snapshot_id = f"snap-{uuid.uuid4().hex[:8]}"
        now = time.time()

        metrics: Dict[str, float] = {}
        metrics.update(self._collect_system_metrics())
        metrics.update(self._collect_pipeline_metrics())
        metrics.update(self._collect_nexus_metrics())
        metrics.update(self._collect_scheduler_metrics())
        metrics.update(self._collect_training_metrics())

        snapshot = MetricSnapshot(
            snapshot_id=snapshot_id,
            change_id=change_id,
            phase=phase,
            timestamp=now,
            metrics=metrics,
        )

        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO metric_snapshots "
                "(snapshot_id, change_id, phase, timestamp, metrics) "
                "VALUES (?, ?, ?, ?, ?)",
                (snapshot_id, change_id, phase, now, json.dumps(metrics)),
            )
            col = (
                "baseline_snapshot_id" if phase == "before"
                else "after_snapshot_id"
            )
            cur.execute(
                f"UPDATE changes SET {col} = ? WHERE change_id = ?",
                (snapshot_id, change_id),
            )

        logger.debug(
            "Captured %s snapshot %s for %s (%d metrics)",
            phase, snapshot_id, change_id, len(metrics),
        )
        return snapshot

    def compute_impact(self, change_id: str) -> List[ImpactScore]:
        """Compare before/after snapshots and compute per-metric impact.

        Args:
            change_id: The change to evaluate.

        Returns:
            List of ``ImpactScore`` instances (empty if snapshots missing).
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT phase, metrics FROM metric_snapshots "
            "WHERE change_id = ? ORDER BY phase",
            (change_id,),
        ).fetchall()

        snapshots: Dict[str, Dict[str, float]] = {}
        for row in rows:
            snapshots[row["phase"]] = json.loads(row["metrics"])

        if "before" not in snapshots or "after" not in snapshots:
            logger.warning(
                "Cannot compute impact for %s — missing %s snapshot(s)",
                change_id,
                "before and/or after",
            )
            return []

        before = snapshots["before"]
        after = snapshots["after"]
        common_keys = sorted(set(before) & set(after))

        if not common_keys:
            logger.warning("No common metrics between snapshots for %s", change_id)
            return []

        # Confidence is based on the number of common metrics.
        base_confidence = min(1.0, 0.3 + 0.05 * len(common_keys))

        scores: List[ImpactScore] = []
        now = time.time()

        with self._cursor() as cur:
            for metric in common_keys:
                bv = before[metric]
                av = after[metric]
                abs_delta = av - bv
                if bv != 0.0:
                    pct_delta = ((av - bv) / abs(bv)) * 100.0
                else:
                    pct_delta = 0.0 if av == 0.0 else 100.0

                severity = _classify_severity(pct_delta, metric)

                # Adjust confidence: tiny absolute deltas on small values
                # are less trustworthy.
                confidence = base_confidence
                if abs(bv) < 1e-6 and abs(av) < 1e-6:
                    confidence = max(0.1, confidence - 0.3)

                score = ImpactScore(
                    change_id=change_id,
                    metric=metric,
                    before_value=bv,
                    after_value=av,
                    absolute_delta=round(abs_delta, 6),
                    percentage_delta=round(pct_delta, 4),
                    severity=severity,
                    confidence=round(confidence, 3),
                )
                scores.append(score)

                cur.execute(
                    "INSERT INTO impact_scores "
                    "(change_id, metric, before_value, after_value, "
                    " absolute_delta, percentage_delta, severity, "
                    " confidence, computed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        change_id,
                        metric,
                        bv,
                        av,
                        score.absolute_delta,
                        score.percentage_delta,
                        severity.value,
                        score.confidence,
                        now,
                    ),
                )

            cur.execute(
                "UPDATE changes SET impact_computed = 1 WHERE change_id = ?",
                (change_id,),
            )

        logger.info(
            "Computed impact for %s — %d metric(s) scored", change_id, len(scores)
        )
        return scores

    def finalize_change(self, change_id: str) -> Dict[str, Any]:
        """Capture after-snapshot, compute impact, and store summary in Nexus.

        Args:
            change_id: The change to finalize.

        Returns:
            Dict with ``change_id``, ``impact_scores``, and ``summary``.
        """
        self.capture_snapshot(change_id, "after")
        scores = self.compute_impact(change_id)

        change = self.get_change(change_id)
        title = change.title if change else change_id

        positives = [s for s in scores if s.severity in (
            ImpactSeverity.POSITIVE_HIGH, ImpactSeverity.POSITIVE_LOW
        )]
        negatives = [s for s in scores if s.severity in (
            ImpactSeverity.NEGATIVE_HIGH, ImpactSeverity.NEGATIVE_LOW
        )]
        neutrals = [s for s in scores if s.severity == ImpactSeverity.NEUTRAL]

        summary_parts = [f"Impact for '{title}': "]
        summary_parts.append(
            f"{len(positives)} improved, {len(negatives)} regressed, "
            f"{len(neutrals)} neutral out of {len(scores)} metrics."
        )

        if positives:
            best = max(positives, key=lambda s: abs(s.percentage_delta))
            summary_parts.append(
                f" Best: {best.metric} {best.percentage_delta:+.1f}%."
            )
        if negatives:
            worst = min(negatives, key=lambda s: s.percentage_delta)
            summary_parts.append(
                f" Worst: {worst.metric} {worst.percentage_delta:+.1f}%."
            )

        summary = "".join(summary_parts)

        # Mirror to Nexus (best-effort)
        try:
            from engine.nexus.client import get_nexus_client

            client = get_nexus_client()
            score_dicts = [
                {
                    "metric": s.metric,
                    "before": s.before_value,
                    "after": s.after_value,
                    "delta_pct": s.percentage_delta,
                    "severity": s.severity.value,
                }
                for s in scores
            ]
            content = json.dumps(
                {"change_id": change_id, "summary": summary, "scores": score_dicts},
                indent=2,
            )
            client.add_entry(
                title=f"Impact: {title}",
                content=content,
                content_type="note",
                category="impact",
                tags=["impact-tracker", "auto-generated"],
            )
        except Exception as exc:
            logger.debug("Nexus storage skipped for %s: %s", change_id, exc)

        result = {
            "change_id": change_id,
            "impact_scores": [asdict(s) for s in scores],
            "summary": summary,
        }
        # Serialise severity enums for JSON round-tripping
        for item in result["impact_scores"]:
            if isinstance(item.get("severity"), ImpactSeverity):
                item["severity"] = item["severity"].value

        logger.info("Finalized change %s — %s", change_id, summary)
        return result

    # ── Query API ─────────────────────────────────────────────────────

    def get_change(self, change_id: str) -> Optional[SystemChange]:
        """Retrieve a single change by ID.

        Args:
            change_id: The unique change identifier.

        Returns:
            ``SystemChange`` or ``None`` if not found.
        """
        row = self._get_conn().execute(
            "SELECT * FROM changes WHERE change_id = ?", (change_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_change(row)

    def list_changes(
        self,
        change_type: Optional[ChangeType] = None,
        days: int = 30,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List recent changes with optional type filter.

        Args:
            change_type: Restrict to this category (or ``None`` for all).
            days: Look-back window in days.
            limit: Maximum rows returned.

        Returns:
            List of change dicts ordered newest-first.
        """
        cutoff = time.time() - days * 86400
        params: List[Any] = [cutoff]
        query = "SELECT * FROM changes WHERE timestamp >= ?"
        if change_type is not None:
            query += " AND change_type = ?"
            params.append(change_type.value)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self._get_conn().execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_impact(self, change_id: str) -> List[ImpactScore]:
        """Get computed impact scores for a change.

        Args:
            change_id: The change identifier.

        Returns:
            List of ``ImpactScore`` instances.
        """
        rows = self._get_conn().execute(
            "SELECT * FROM impact_scores WHERE change_id = ? "
            "ORDER BY ABS(percentage_delta) DESC",
            (change_id,),
        ).fetchall()
        return [self._row_to_impact(r) for r in rows]

    def improvement_history(
        self, metric: str, days: int = 90
    ) -> List[Dict[str, Any]]:
        """Timeline of all changes that affected a specific metric.

        Args:
            metric: Dot-notation metric name (e.g. ``"pipeline.avg_latency_ms"``).
            days: Look-back window.

        Returns:
            List of dicts sorted by timestamp ascending.
        """
        cutoff = time.time() - days * 86400
        rows = self._get_conn().execute(
            "SELECT i.change_id, c.title, i.percentage_delta AS delta, "
            "       i.severity, c.timestamp "
            "FROM impact_scores i "
            "JOIN changes c ON c.change_id = i.change_id "
            "WHERE i.metric = ? AND c.timestamp >= ? "
            "ORDER BY c.timestamp ASC",
            (metric, cutoff),
        ).fetchall()
        return [
            {
                "change_id": r["change_id"],
                "title": r["title"],
                "delta": r["delta"],
                "severity": r["severity"],
                "timestamp": r["timestamp"],
            }
            for r in rows
        ]

    def top_improvements(
        self, days: int = 30, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Top changes with the largest average positive impact.

        Args:
            days: Look-back window.
            limit: Max results.

        Returns:
            List of dicts with ``change_id``, ``title``, ``avg_pct_delta``,
            ``metric_count``.
        """
        cutoff = time.time() - days * 86400
        rows = self._get_conn().execute(
            "SELECT i.change_id, c.title, "
            "       AVG(i.percentage_delta) AS avg_pct_delta, "
            "       COUNT(*) AS metric_count "
            "FROM impact_scores i "
            "JOIN changes c ON c.change_id = i.change_id "
            "WHERE c.timestamp >= ? "
            "GROUP BY i.change_id "
            "HAVING avg_pct_delta > 0 "
            "ORDER BY avg_pct_delta DESC "
            "LIMIT ?",
            (cutoff, limit),
        ).fetchall()
        return [
            {
                "change_id": r["change_id"],
                "title": r["title"],
                "avg_pct_delta": round(r["avg_pct_delta"], 4),
                "metric_count": r["metric_count"],
            }
            for r in rows
        ]

    def impact_timeline(
        self, days: int = 30
    ) -> List[Dict[str, Any]]:
        """Chronological list of all changes with their computed impact summaries.

        Args:
            days: Look-back window.

        Returns:
            List of dicts ordered oldest-first containing change info and
            aggregated impact statistics.
        """
        cutoff = time.time() - days * 86400
        changes = self._get_conn().execute(
            "SELECT * FROM changes WHERE timestamp >= ? "
            "ORDER BY timestamp ASC",
            (cutoff,),
        ).fetchall()

        timeline: List[Dict[str, Any]] = []
        for chg in changes:
            entry = self._row_to_dict(chg)
            if chg["impact_computed"]:
                scores = self._get_conn().execute(
                    "SELECT metric, percentage_delta, severity "
                    "FROM impact_scores WHERE change_id = ?",
                    (chg["change_id"],),
                ).fetchall()
                entry["impact"] = {
                    "metric_count": len(scores),
                    "avg_delta": round(
                        sum(r["percentage_delta"] for r in scores) / len(scores), 4
                    ) if scores else 0.0,
                    "severities": _severity_counts(scores),
                }
            else:
                entry["impact"] = None
            timeline.append(entry)

        return timeline

    def attribution_report(
        self, days: int = 30, limit: int = 20
    ) -> Dict[str, Any]:
        """Generate a report of which changes had the biggest impact.

        Args:
            days: Look-back window in days.
            limit: Max items in top-positive / top-negative lists.

        Returns:
            Structured report dict.
        """
        cutoff = time.time() - days * 86400
        conn = self._get_conn()

        total_changes = conn.execute(
            "SELECT COUNT(*) AS cnt FROM changes WHERE timestamp >= ?",
            (cutoff,),
        ).fetchone()["cnt"]

        uncomputed = conn.execute(
            "SELECT COUNT(*) AS cnt FROM changes "
            "WHERE timestamp >= ? AND impact_computed = 0",
            (cutoff,),
        ).fetchone()["cnt"]

        # Top positive (by avg percentage delta)
        top_pos = conn.execute(
            "SELECT i.change_id, c.title, c.change_type, c.source, "
            "       AVG(i.percentage_delta) AS avg_delta, "
            "       COUNT(*) AS metric_count "
            "FROM impact_scores i "
            "JOIN changes c ON c.change_id = i.change_id "
            "WHERE c.timestamp >= ? "
            "GROUP BY i.change_id "
            "HAVING avg_delta > 0 "
            "ORDER BY avg_delta DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()

        # Top negative
        top_neg = conn.execute(
            "SELECT i.change_id, c.title, c.change_type, c.source, "
            "       AVG(i.percentage_delta) AS avg_delta, "
            "       COUNT(*) AS metric_count "
            "FROM impact_scores i "
            "JOIN changes c ON c.change_id = i.change_id "
            "WHERE c.timestamp >= ? "
            "GROUP BY i.change_id "
            "HAVING avg_delta < 0 "
            "ORDER BY avg_delta ASC LIMIT ?",
            (cutoff, limit),
        ).fetchall()

        # Breakdown by change_type
        by_type_rows = conn.execute(
            "SELECT c.change_type, "
            "       COUNT(DISTINCT c.change_id) AS cnt, "
            "       AVG(i.percentage_delta) AS avg_impact "
            "FROM changes c "
            "LEFT JOIN impact_scores i ON i.change_id = c.change_id "
            "WHERE c.timestamp >= ? "
            "GROUP BY c.change_type",
            (cutoff,),
        ).fetchall()
        by_type = {
            r["change_type"]: {
                "count": r["cnt"],
                "avg_impact": round(r["avg_impact"], 4) if r["avg_impact"] else 0.0,
            }
            for r in by_type_rows
        }

        # Breakdown by source
        by_source_rows = conn.execute(
            "SELECT c.source, "
            "       COUNT(DISTINCT c.change_id) AS cnt, "
            "       AVG(i.percentage_delta) AS avg_impact "
            "FROM changes c "
            "LEFT JOIN impact_scores i ON i.change_id = c.change_id "
            "WHERE c.timestamp >= ? "
            "GROUP BY c.source",
            (cutoff,),
        ).fetchall()
        by_source = {
            r["source"]: {
                "count": r["cnt"],
                "avg_impact": round(r["avg_impact"], 4) if r["avg_impact"] else 0.0,
            }
            for r in by_source_rows
        }

        def _fmt_row(r: sqlite3.Row) -> Dict[str, Any]:
            return {
                "change_id": r["change_id"],
                "title": r["title"],
                "change_type": r["change_type"],
                "source": r["source"],
                "avg_pct_delta": round(r["avg_delta"], 4),
                "metric_count": r["metric_count"],
            }

        return {
            "period_days": days,
            "total_changes": total_changes,
            "top_positive": [_fmt_row(r) for r in top_pos],
            "top_negative": [_fmt_row(r) for r in top_neg],
            "by_type": by_type,
            "by_source": by_source,
            "uncomputed": uncomputed,
        }

    # ── Metric Collection Helpers ─────────────────────────────────────

    def _collect_system_metrics(self) -> Dict[str, float]:
        """Collect CPU, RAM, and GPU metrics from MetricsCollector.

        Returns:
            Dict of ``system.*`` metrics.  Empty dict if unavailable.
        """
        metrics: Dict[str, float] = {}
        try:
            from engine.observability.metrics_collector import get_metrics_collector

            collector = get_metrics_collector()
            snapshot = getattr(collector, "latest_snapshot", None)
            if snapshot and isinstance(snapshot, dict):
                for key in ("cpu_pct", "ram_pct", "gpu_vram_pct", "gpu_util_pct"):
                    if key in snapshot:
                        metrics[f"system.{key}"] = float(snapshot[key])
        except Exception as exc:
            logger.debug("System metrics unavailable: %s", exc)

        # Fallback: psutil directly if collector had nothing
        if not metrics:
            try:
                import psutil

                metrics["system.cpu_pct"] = psutil.cpu_percent(interval=0.1)
                mem = psutil.virtual_memory()
                metrics["system.ram_pct"] = mem.percent
            except Exception:
                pass

        return metrics

    def _collect_pipeline_metrics(self) -> Dict[str, float]:
        """Collect recent pipeline averages from MetricsDB.

        Returns:
            Dict of ``pipeline.*`` metrics.  Empty dict if unavailable.
        """
        metrics: Dict[str, float] = {}
        try:
            from engine.observability.metrics_db import get_metrics_db

            db = get_metrics_db()
            conn = db._get_conn() if hasattr(db, "_get_conn") else None
            if conn is None:
                return metrics

            row = conn.execute(
                "SELECT AVG(latency_ms) AS avg_lat, "
                "       AVG(tps)        AS avg_tps, "
                "       AVG(tokens_out) AS avg_tok, "
                "       AVG(ttft_ms)    AS avg_ttft, "
                "       COUNT(*)        AS cnt "
                "FROM pipeline_metrics "
                "ORDER BY ts DESC LIMIT 100"
            ).fetchone()

            if row and row["cnt"] and row["cnt"] > 0:
                if row["avg_lat"] is not None:
                    metrics["pipeline.avg_latency_ms"] = round(row["avg_lat"], 2)
                if row["avg_tps"] is not None:
                    metrics["pipeline.avg_tps"] = round(row["avg_tps"], 2)
                if row["avg_tok"] is not None:
                    metrics["pipeline.avg_tokens_out"] = round(row["avg_tok"], 2)
                if row["avg_ttft"] is not None:
                    metrics["pipeline.avg_ttft_ms"] = round(row["avg_ttft"], 2)
        except Exception as exc:
            logger.debug("Pipeline metrics unavailable: %s", exc)
        return metrics

    def _collect_nexus_metrics(self) -> Dict[str, float]:
        """Collect entry and Q&A counts from NexusClient.

        Returns:
            Dict of ``nexus.*`` metrics.  Empty dict if unavailable.
        """
        metrics: Dict[str, float] = {}
        try:
            from engine.nexus.client import get_nexus_client

            client = get_nexus_client()
            health = client.health()
            if isinstance(health, dict):
                entries = health.get("entries", health.get("total_entries"))
                if entries is not None:
                    metrics["nexus.entries.total"] = float(entries)
                qa = health.get("qa_count", health.get("qa_pairs"))
                if qa is not None:
                    metrics["nexus.qa.count"] = float(qa)
                plugins = health.get("plugins")
                if plugins is not None:
                    metrics["nexus.plugins"] = float(plugins)

            stats = client.stats()
            if isinstance(stats, dict):
                for key in ("total_entries", "total_qa", "cache_size"):
                    if key in stats:
                        metrics[f"nexus.stats.{key}"] = float(stats[key])
        except Exception as exc:
            logger.debug("Nexus metrics unavailable: %s", exc)
        return metrics

    def _collect_scheduler_metrics(self) -> Dict[str, float]:
        """Collect task execution stats from TaskSchedulerDaemon.

        Returns:
            Dict of ``scheduler.*`` metrics.  Empty dict if unavailable.
        """
        metrics: Dict[str, float] = {}
        try:
            from engine.nexus.scheduler_daemon import TaskSchedulerDaemon

            daemon = TaskSchedulerDaemon.__new__(TaskSchedulerDaemon)
            if not hasattr(daemon, "status"):
                return metrics
            # Prefer singleton if available
            import engine.nexus.scheduler_daemon as sd_mod

            instance = getattr(sd_mod, "_daemon", None) or getattr(
                sd_mod, "_instance", None
            )
            if instance is None:
                return metrics

            status = instance.status()
            if not isinstance(status, dict):
                return metrics

            tasks = status.get("tasks", {})
            if isinstance(tasks, dict):
                total = len(tasks)
                passed = sum(
                    1 for t in tasks.values()
                    if isinstance(t, dict) and t.get("last_result") == "ok"
                )
                metrics["scheduler.task_count"] = float(total)
                if total > 0:
                    metrics["scheduler.pass_rate"] = round(passed / total, 4)
                    metrics["scheduler.failure_rate"] = round(
                        1.0 - passed / total, 4
                    )
            elif isinstance(tasks, list):
                total = len(tasks)
                passed = sum(
                    1 for t in tasks
                    if isinstance(t, dict) and t.get("last_result") == "ok"
                )
                metrics["scheduler.task_count"] = float(total)
                if total > 0:
                    metrics["scheduler.pass_rate"] = round(passed / total, 4)
                    metrics["scheduler.failure_rate"] = round(
                        1.0 - passed / total, 4
                    )
        except Exception as exc:
            logger.debug("Scheduler metrics unavailable: %s", exc)
        return metrics

    def _collect_training_metrics(self) -> Dict[str, float]:
        """Collect training flywheel statistics.

        Returns:
            Dict of ``training.*`` metrics.  Empty dict if unavailable.
        """
        metrics: Dict[str, float] = {}
        try:
            from engine.nexus.training_flywheel import get_training_flywheel

            fw = get_training_flywheel()
            stats = fw.stats()
            if isinstance(stats, dict):
                total = stats.get("total_examples")
                if total is not None:
                    metrics["training.total_examples"] = float(total)
                avg_q = stats.get("avg_quality")
                if avg_q is not None:
                    metrics["training.avg_quality"] = round(float(avg_q), 4)
                exported = stats.get("exported")
                if exported is not None:
                    metrics["training.exported"] = float(exported)
        except Exception as exc:
            logger.debug("Training metrics unavailable: %s", exc)
        return metrics

    # ── Row Converters ────────────────────────────────────────────────

    @staticmethod
    def _row_to_change(row: sqlite3.Row) -> SystemChange:
        """Convert a DB row into a ``SystemChange`` dataclass."""
        return SystemChange(
            change_id=row["change_id"],
            change_type=ChangeType(row["change_type"]),
            title=row["title"],
            description=row["description"] or "",
            timestamp=row["timestamp"],
            source=row["source"] or "",
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            baseline_snapshot_id=row["baseline_snapshot_id"],
            after_snapshot_id=row["after_snapshot_id"],
            impact_computed=bool(row["impact_computed"]),
        )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a DB row into a plain dict with parsed JSON fields."""
        d = dict(row)
        if "metadata" in d and isinstance(d["metadata"], str):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
        d["impact_computed"] = bool(d.get("impact_computed", 0))
        return d

    @staticmethod
    def _row_to_impact(row: sqlite3.Row) -> ImpactScore:
        """Convert a DB row into an ``ImpactScore`` dataclass."""
        return ImpactScore(
            change_id=row["change_id"],
            metric=row["metric"],
            before_value=row["before_value"],
            after_value=row["after_value"],
            absolute_delta=row["absolute_delta"],
            percentage_delta=row["percentage_delta"],
            severity=ImpactSeverity(row["severity"]),
            confidence=row["confidence"],
        )


# ──── Module-level helpers ────────────────────────────────────────────────


def _severity_counts(rows: List[sqlite3.Row]) -> Dict[str, int]:
    """Tally severity values from a list of impact_scores rows."""
    counts: Dict[str, int] = {}
    for r in rows:
        sev = r["severity"]
        counts[sev] = counts.get(sev, 0) + 1
    return counts


# ──── Scheduler Registration ──────────────────────────────────────────────


def register_impact_tasks(daemon: Any) -> None:
    """Register recurring impact-tracking tasks with the scheduler daemon.

    Args:
        daemon: ``SchedulerDaemon`` instance.
    """
    def _weekly_summary() -> None:
        tracker = get_impact_tracker()
        report = tracker.attribution_report(days=7)
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            summary_lines = [
                f"Impact Attribution Report — {report.get('period', 'last 7 days')}",
                f"Total changes: {report.get('total_changes', 0)}",
                f"Changes with impact: {report.get('changes_with_impact', 0)}",
            ]
            for entry in report.get("top_changes", [])[:5]:
                summary_lines.append(
                    f"  • {entry.get('description', 'unknown')}: "
                    f"severity={entry.get('severity', '?')}"
                )
            client.add_entry(
                title="Weekly Impact Summary",
                content="\n".join(summary_lines),
                content_type="note",
                category="observability",
            )
        except Exception:
            logger.debug("Nexus unavailable for impact summary storage")

    daemon.register(
        task_id="impact-summary",
        name="Weekly impact attribution summary",
        schedule="weekly",
        callback=_weekly_summary,
        enabled=True,
    )


# ──── Singleton ───────────────────────────────────────────────────────────

_instance: Optional[ImpactTracker] = None
_lock = threading.Lock()


def get_impact_tracker(db_path: Optional[Path] = None) -> ImpactTracker:
    """Thread-safe singleton getter for ``ImpactTracker``.

    Args:
        db_path: Override database path (only used on first call).

    Returns:
        The shared ``ImpactTracker`` instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ImpactTracker(db_path)
    return _instance
