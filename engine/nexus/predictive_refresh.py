"""PredictiveRefresh — forecast knowledge staleness and auto-schedule refreshes.

Tracks Nexus knowledge entry access patterns, computes decay curves, and
proactively schedules refreshes *before* entries become stale.  Integrates
with TrendPredictor for time-series forecasting and NexusClient for
knowledge entry metadata.

Key capabilities:
- Track access patterns for Nexus knowledge entries
- Compute staleness scores based on age, access frequency, and decay
- Predict when entries will cross staleness thresholds
- Auto-schedule refresh tasks for entries approaching staleness
- Content-type-aware staleness thresholds (code decays faster than docs)
- Integration with scheduler daemon for periodic sweeps

Usage::

    from engine.nexus.predictive_refresh import get_predictive_refresh
    pr = get_predictive_refresh()

    # Record an access
    pr.record_access("entry-123", content_type="code", category="api")

    # Assess staleness of tracked entries
    report = pr.assess_staleness(threshold=0.7)

    # Get refresh queue (entries predicted to go stale soon)
    queue = pr.get_refresh_queue(horizon_hours=48)

    # Auto-refresh stale entries (triggers Nexus search + update)
    results = pr.refresh_stale(max_items=10)
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/predictive_refresh.db")

# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional["PredictiveRefresh"] = None
_lock = threading.Lock()


def get_predictive_refresh(
    db_path: Optional[Path] = None,
) -> "PredictiveRefresh":
    """Get or create the singleton PredictiveRefresh."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = PredictiveRefresh(db_path=db_path)
    return _instance


# ── Configuration ───────────────────────────────────────────────────────

# Staleness decay half-lives by content type (in days).
# Entries lose 50% of their freshness after this many days without access.
_HALF_LIFE_DAYS: Dict[str, float] = {
    "code": 14.0,       # Code snippets go stale quickly
    "qa": 30.0,         # Q&A pairs are more durable
    "note": 45.0,       # General notes decay slowly
    "document": 60.0,   # Documents are fairly stable
    "prompt": 21.0,     # Prompts need regular review
    "memory": 30.0,     # Agent memories
    "research": 60.0,   # Research artifacts are durable
    "transcript": 90.0, # Transcripts rarely need refresh
    "rule": 90.0,       # Rules are very stable
    "history": 180.0,   # Historical records are permanent-ish
    "plan": 7.0,        # Plans go stale very fast
    "benchmark": 14.0,  # Benchmark data needs frequent updates
}

_DEFAULT_HALF_LIFE = 30.0  # Default for unknown content types

# Staleness thresholds per content type (0.0 = fresh, 1.0 = completely stale).
# When staleness exceeds threshold, entry is flagged for refresh.
_STALENESS_THRESHOLDS: Dict[str, float] = {
    "code": 0.6,
    "qa": 0.7,
    "note": 0.7,
    "document": 0.8,
    "prompt": 0.6,
    "memory": 0.7,
    "research": 0.8,
    "transcript": 0.9,
    "rule": 0.9,
    "history": 0.95,
    "plan": 0.5,
    "benchmark": 0.6,
}

_DEFAULT_THRESHOLD = 0.7


# ── Data Models ─────────────────────────────────────────────────────────


@dataclass
class EntryFreshness:
    """Freshness assessment for a single Nexus entry."""

    entry_id: str
    title: str
    content_type: str
    category: str
    staleness_score: float  # 0.0 = perfectly fresh, 1.0 = completely stale
    freshness_score: float  # 1.0 - staleness_score
    age_days: float
    access_count: int
    last_accessed: Optional[float]  # Unix timestamp
    days_since_access: Optional[float]
    half_life_days: float
    threshold: float
    is_stale: bool
    predicted_stale_at: Optional[float]  # Unix timestamp when staleness will exceed threshold
    hours_until_stale: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)


@dataclass
class RefreshCandidate:
    """An entry queued for refresh."""

    entry_id: str
    title: str
    content_type: str
    category: str
    staleness_score: float
    urgency: str  # "critical" (>threshold+0.15), "high" (>threshold), "medium" (approaching)
    predicted_stale_at: Optional[float]
    hours_until_stale: Optional[float]
    refresh_reason: str
    last_refreshed: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)


@dataclass
class RefreshResult:
    """Result of refreshing a single entry."""

    entry_id: str
    title: str
    status: str  # "refreshed", "skipped", "failed"
    old_staleness: float
    new_staleness: float
    refresh_method: str  # "access_reset", "content_update", "manual"
    timestamp: float = field(default_factory=time.time)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)


@dataclass
class StalenessReport:
    """Aggregate staleness assessment across all tracked entries."""

    total_tracked: int
    stale_count: int
    approaching_stale: int  # Within 80% of threshold
    fresh_count: int
    avg_staleness: float
    worst_entries: List[Dict[str, Any]]
    by_content_type: Dict[str, Dict[str, Any]]
    by_category: Dict[str, Dict[str, Any]]
    refresh_queue_size: int
    report_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)


# ── Helpers ─────────────────────────────────────────────────────────────


def _compute_staleness(
    age_days: float,
    access_count: int,
    days_since_last_access: float,
    half_life: float,
) -> float:
    """Compute staleness score using exponential decay with access boost.

    The model:
    - Base decay: exponential decay with content-type-specific half-life
    - Access boost: each access reduces staleness (logarithmic diminishing returns)
    - Recency boost: recent accesses keep entries fresher

    Returns:
        Staleness score in [0.0, 1.0].
    """
    if age_days <= 0:
        return 0.0

    # Base exponential decay: s = 1 - 2^(-age/half_life)
    decay_factor = 1.0 - math.pow(2.0, -age_days / half_life)

    # Access frequency boost: more accesses = slower staleness growth
    # Uses log scale to provide diminishing returns
    access_boost = math.log1p(access_count) * 0.1  # Each doubling of accesses reduces staleness ~7%
    access_boost = min(access_boost, 0.5)  # Cap at 50% reduction

    # Recency boost: recent access reduces staleness
    if days_since_last_access is not None and days_since_last_access < half_life:
        recency_boost = 0.3 * (1.0 - days_since_last_access / half_life)
    else:
        recency_boost = 0.0

    staleness = decay_factor * (1.0 - access_boost) - recency_boost
    return max(0.0, min(1.0, staleness))


def _predict_staleness_crossing(
    current_staleness: float,
    threshold: float,
    half_life: float,
    age_days: float,
) -> Optional[float]:
    """Predict when staleness will cross the threshold.

    Uses the decay model to extrapolate forward and find when
    staleness_score > threshold (assuming no further accesses).

    Returns:
        Unix timestamp of predicted threshold crossing, or None if already stale
        or if crossing is very far in the future (>365 days).
    """
    if current_staleness >= threshold:
        return None  # Already stale

    # Solve: 1 - 2^(-(age + delta_days) / half_life) = threshold
    # => 2^(-(age + delta_days) / half_life) = 1 - threshold
    # => -(age + delta_days) / half_life = log2(1 - threshold)
    # => delta_days = -half_life * log2(1 - threshold) - age
    if threshold >= 1.0:
        return None

    target_age = -half_life * math.log2(1.0 - threshold)
    delta_days = target_age - age_days

    if delta_days <= 0:
        return None  # Already past the crossing
    if delta_days > 365:
        return None  # Too far in the future

    return time.time() + delta_days * 86400.0


# ── PredictiveRefresh ───────────────────────────────────────────────────


class PredictiveRefresh:
    """Predictive knowledge refresh engine.

    Tracks access patterns for Nexus knowledge entries, computes staleness
    scores using exponential decay models, and proactively identifies
    entries that need refreshing before they become stale.

    Args:
        db_path: Path to SQLite database for access tracking.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
    ) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._local = threading.local()
        self._refresh_history: list = []
        self._init_db()

        logger.info("PredictiveRefresh initialised (db=%s)", self._db_path)

    # ── Database ────────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Thread-local SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    @contextmanager
    def _tx(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for transactional DB access."""
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._tx() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entry_tracking (
                    entry_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'note',
                    category TEXT NOT NULL DEFAULT '',
                    first_seen REAL NOT NULL,
                    last_accessed REAL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_refreshed REAL,
                    refresh_count INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS access_log (
                    id TEXT PRIMARY KEY,
                    entry_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS refresh_log (
                    id TEXT PRIMARY KEY,
                    entry_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    old_staleness REAL NOT NULL,
                    new_staleness REAL NOT NULL,
                    method TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_access_entry
                ON access_log(entry_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_access_ts
                ON access_log(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_refresh_entry
                ON refresh_log(entry_id)
            """)

    # ── Access Tracking ─────────────────────────────────────────────────

    def record_access(
        self,
        entry_id: str,
        title: str = "",
        content_type: str = "note",
        category: str = "",
        source: str = "manual",
    ) -> None:
        """Record an access event for a Nexus entry.

        Args:
            entry_id: The Nexus entry ID.
            title: Entry title (for display).
            content_type: Entry content type.
            category: Entry category.
            source: Access source (e.g., "search", "agent", "manual").
        """
        now = time.time()
        with self._tx() as conn:
            # Upsert tracking record
            conn.execute(
                """INSERT INTO entry_tracking
                (entry_id, title, content_type, category, first_seen, last_accessed, access_count)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(entry_id) DO UPDATE SET
                    title = COALESCE(NULLIF(excluded.title, ''), entry_tracking.title),
                    content_type = COALESCE(NULLIF(excluded.content_type, 'note'), entry_tracking.content_type),
                    category = COALESCE(NULLIF(excluded.category, ''), entry_tracking.category),
                    last_accessed = excluded.last_accessed,
                    access_count = entry_tracking.access_count + 1
                """,
                (entry_id, title, content_type, category, now, now),
            )
            # Log individual access
            conn.execute(
                "INSERT INTO access_log (id, entry_id, timestamp, source) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), entry_id, now, source),
            )

    def register_entry(
        self,
        entry_id: str,
        title: str,
        content_type: str = "note",
        category: str = "",
        created_at: Optional[float] = None,
    ) -> None:
        """Register a Nexus entry for staleness tracking without recording access.

        Args:
            entry_id: The Nexus entry ID.
            title: Entry title.
            content_type: Entry content type.
            category: Entry category.
            created_at: Original creation timestamp (defaults to now).
        """
        now = created_at or time.time()
        with self._tx() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO entry_tracking
                (entry_id, title, content_type, category, first_seen, access_count)
                VALUES (?, ?, ?, ?, ?, 0)""",
                (entry_id, title, content_type, category, now),
            )

    def bulk_register(
        self,
        entries: List[Dict[str, Any]],
    ) -> int:
        """Register multiple entries at once.

        Args:
            entries: List of dicts with keys: entry_id, title, content_type, category, created_at.

        Returns:
            Number of entries registered.
        """
        count = 0
        with self._tx() as conn:
            for entry in entries:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO entry_tracking
                        (entry_id, title, content_type, category, first_seen, access_count)
                        VALUES (?, ?, ?, ?, ?, 0)""",
                        (
                            entry["entry_id"],
                            entry.get("title", ""),
                            entry.get("content_type", "note"),
                            entry.get("category", ""),
                            entry.get("created_at", time.time()),
                        ),
                    )
                    count += 1
                except Exception:
                    continue
        return count

    # ── Staleness Assessment ────────────────────────────────────────────

    def assess_entry(self, entry_id: str) -> Optional[EntryFreshness]:
        """Compute freshness/staleness for a single tracked entry.

        Args:
            entry_id: The Nexus entry ID.

        Returns:
            EntryFreshness or None if entry is not tracked.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM entry_tracking WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()

        if row is None:
            return None

        return self._compute_freshness(row)

    def assess_staleness(
        self,
        threshold: Optional[float] = None,
        content_type: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> StalenessReport:
        """Assess staleness across all tracked entries.

        Args:
            threshold: Override staleness threshold (uses per-type defaults if None).
            content_type: Filter by content type.
            category: Filter by category.
            limit: Maximum entries to analyze.

        Returns:
            StalenessReport with aggregate statistics.
        """
        conn = self._get_conn()

        query = "SELECT * FROM entry_tracking"
        params: List[Any] = []
        conditions: List[str] = []

        if content_type:
            conditions.append("content_type = ?")
            params.append(content_type)
        if category:
            conditions.append("category = ?")
            params.append(category)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += f" LIMIT {limit}"

        rows = conn.execute(query, params).fetchall()

        entries: List[EntryFreshness] = []
        for row in rows:
            ef = self._compute_freshness(row, threshold_override=threshold)
            entries.append(ef)

        # Aggregate stats
        stale = [e for e in entries if e.is_stale]
        approaching = [
            e for e in entries
            if not e.is_stale and e.staleness_score >= e.threshold * 0.8
        ]
        fresh = [e for e in entries if not e.is_stale and e.staleness_score < e.threshold * 0.8]

        avg_staleness = (
            sum(e.staleness_score for e in entries) / len(entries)
            if entries else 0.0
        )

        # By content type
        by_type: Dict[str, Dict[str, Any]] = {}
        for e in entries:
            if e.content_type not in by_type:
                by_type[e.content_type] = {
                    "count": 0, "stale": 0, "avg_staleness": 0.0, "total_staleness": 0.0
                }
            by_type[e.content_type]["count"] += 1
            by_type[e.content_type]["total_staleness"] += e.staleness_score
            if e.is_stale:
                by_type[e.content_type]["stale"] += 1
        for ct_data in by_type.values():
            if ct_data["count"] > 0:
                ct_data["avg_staleness"] = ct_data["total_staleness"] / ct_data["count"]
            del ct_data["total_staleness"]

        # By category
        by_cat: Dict[str, Dict[str, Any]] = {}
        for e in entries:
            cat = e.category or "uncategorized"
            if cat not in by_cat:
                by_cat[cat] = {
                    "count": 0, "stale": 0, "avg_staleness": 0.0, "total_staleness": 0.0
                }
            by_cat[cat]["count"] += 1
            by_cat[cat]["total_staleness"] += e.staleness_score
            if e.is_stale:
                by_cat[cat]["stale"] += 1
        for cat_data in by_cat.values():
            if cat_data["count"] > 0:
                cat_data["avg_staleness"] = cat_data["total_staleness"] / cat_data["count"]
            del cat_data["total_staleness"]

        # Worst entries (sorted by staleness descending)
        entries.sort(key=lambda e: e.staleness_score, reverse=True)
        worst = [e.to_dict() for e in entries[:10]]

        # Count items in refresh queue
        queue = self.get_refresh_queue(horizon_hours=48)

        return StalenessReport(
            total_tracked=len(entries),
            stale_count=len(stale),
            approaching_stale=len(approaching),
            fresh_count=len(fresh),
            avg_staleness=avg_staleness,
            worst_entries=worst,
            by_content_type=by_type,
            by_category=by_cat,
            refresh_queue_size=len(queue),
        )

    def _compute_freshness(
        self,
        row: sqlite3.Row,
        threshold_override: Optional[float] = None,
    ) -> EntryFreshness:
        """Compute freshness for a database row."""
        now = time.time()
        entry_id = row["entry_id"]
        content_type = row["content_type"]
        category = row["category"]
        first_seen = row["first_seen"]
        last_accessed = row["last_accessed"]
        access_count = row["access_count"]

        age_days = (now - first_seen) / 86400.0
        half_life = _HALF_LIFE_DAYS.get(content_type, _DEFAULT_HALF_LIFE)
        threshold = threshold_override or _STALENESS_THRESHOLDS.get(content_type, _DEFAULT_THRESHOLD)

        days_since_access: Optional[float] = None
        if last_accessed:
            days_since_access = (now - last_accessed) / 86400.0

        staleness = _compute_staleness(
            age_days=age_days,
            access_count=access_count,
            days_since_last_access=days_since_access if days_since_access is not None else age_days,
            half_life=half_life,
        )

        predicted_stale = _predict_staleness_crossing(
            current_staleness=staleness,
            threshold=threshold,
            half_life=half_life,
            age_days=age_days,
        )

        hours_until = None
        if predicted_stale is not None:
            hours_until = max(0.0, (predicted_stale - now) / 3600.0)

        return EntryFreshness(
            entry_id=entry_id,
            title=row["title"],
            content_type=content_type,
            category=category,
            staleness_score=staleness,
            freshness_score=1.0 - staleness,
            age_days=age_days,
            access_count=access_count,
            last_accessed=last_accessed,
            days_since_access=days_since_access,
            half_life_days=half_life,
            threshold=threshold,
            is_stale=staleness >= threshold,
            predicted_stale_at=predicted_stale,
            hours_until_stale=hours_until,
        )

    # ── Refresh Queue ───────────────────────────────────────────────────

    def get_refresh_queue(
        self,
        horizon_hours: float = 48.0,
        content_type: Optional[str] = None,
        max_items: int = 50,
    ) -> List[RefreshCandidate]:
        """Get entries that need refreshing, ordered by urgency.

        Returns entries that are either:
        1. Already stale (exceeded their threshold)
        2. Predicted to become stale within the horizon

        Args:
            horizon_hours: Look-ahead window in hours.
            content_type: Filter by content type.
            max_items: Maximum entries to return.

        Returns:
            List of RefreshCandidate ordered by urgency.
        """
        conn = self._get_conn()

        query = "SELECT * FROM entry_tracking"
        params: List[Any] = []
        if content_type:
            query += " WHERE content_type = ?"
            params.append(content_type)

        rows = conn.execute(query, params).fetchall()
        candidates: List[RefreshCandidate] = []
        now = time.time()
        horizon_ts = now + horizon_hours * 3600.0

        for row in rows:
            ef = self._compute_freshness(row)

            if ef.is_stale:
                # Already stale
                urgency = "critical" if ef.staleness_score > ef.threshold + 0.15 else "high"
                candidates.append(RefreshCandidate(
                    entry_id=ef.entry_id,
                    title=ef.title,
                    content_type=ef.content_type,
                    category=ef.category,
                    staleness_score=ef.staleness_score,
                    urgency=urgency,
                    predicted_stale_at=None,
                    hours_until_stale=0.0,
                    refresh_reason=f"Staleness {ef.staleness_score:.2f} exceeds threshold {ef.threshold:.2f}",
                    last_refreshed=row["last_refreshed"],
                ))
            elif ef.predicted_stale_at and ef.predicted_stale_at <= horizon_ts:
                # Predicted to go stale within horizon
                candidates.append(RefreshCandidate(
                    entry_id=ef.entry_id,
                    title=ef.title,
                    content_type=ef.content_type,
                    category=ef.category,
                    staleness_score=ef.staleness_score,
                    urgency="medium",
                    predicted_stale_at=ef.predicted_stale_at,
                    hours_until_stale=ef.hours_until_stale,
                    refresh_reason=f"Predicted stale in {ef.hours_until_stale:.1f}h",
                    last_refreshed=row["last_refreshed"],
                ))

        # Sort: critical first, then high, then medium; within each, by staleness descending
        urgency_order = {"critical": 0, "high": 1, "medium": 2}
        candidates.sort(key=lambda c: (urgency_order.get(c.urgency, 3), -c.staleness_score))

        return candidates[:max_items]

    # ── Refresh Execution ───────────────────────────────────────────────

    def refresh_stale(
        self,
        max_items: int = 10,
        horizon_hours: float = 48.0,
        refresh_callback: Optional[Callable[[str, str, str], Optional[str]]] = None,
    ) -> List[RefreshResult]:
        """Refresh stale entries.

        For each stale entry, either:
        1. Calls the provided refresh_callback(entry_id, title, content_type)
           which should return updated content (or None to skip)
        2. Falls back to recording a refresh event (resetting the access timer)

        Args:
            max_items: Maximum entries to refresh in this batch.
            horizon_hours: Look-ahead window for the refresh queue.
            refresh_callback: Optional callback to generate updated content.

        Returns:
            List of RefreshResult for each processed entry.
        """
        queue = self.get_refresh_queue(
            horizon_hours=horizon_hours,
            max_items=max_items,
        )

        results: List[RefreshResult] = []
        now = time.time()

        for candidate in queue:
            old_staleness = candidate.staleness_score

            try:
                if refresh_callback:
                    updated_content = refresh_callback(
                        candidate.entry_id,
                        candidate.title,
                        candidate.content_type,
                    )
                    if updated_content:
                        method = "content_update"
                    else:
                        method = "access_reset"
                else:
                    method = "access_reset"

                # Record the refresh
                self._record_refresh(candidate.entry_id, method, now)

                # Re-assess to get new staleness
                new_freshness = self.assess_entry(candidate.entry_id)
                new_staleness = new_freshness.staleness_score if new_freshness else old_staleness

                result = RefreshResult(
                    entry_id=candidate.entry_id,
                    title=candidate.title,
                    status="refreshed",
                    old_staleness=old_staleness,
                    new_staleness=new_staleness,
                    refresh_method=method,
                    timestamp=now,
                )
            except Exception as exc:
                result = RefreshResult(
                    entry_id=candidate.entry_id,
                    title=candidate.title,
                    status="failed",
                    old_staleness=old_staleness,
                    new_staleness=old_staleness,
                    refresh_method="failed",
                    timestamp=now,
                    error=str(exc),
                )

            results.append(result)
            self._persist_refresh(result)

        self._refresh_history.extend(results)
        return results

    def _record_refresh(
        self,
        entry_id: str,
        method: str,
        timestamp: float,
    ) -> None:
        """Record a refresh event in the tracking database."""
        with self._tx() as conn:
            conn.execute(
                """UPDATE entry_tracking SET
                    last_refreshed = ?,
                    last_accessed = ?,
                    refresh_count = refresh_count + 1
                WHERE entry_id = ?""",
                (timestamp, timestamp, entry_id),
            )

    def _persist_refresh(self, result: RefreshResult) -> None:
        """Persist a refresh result to the database."""
        try:
            with self._tx() as conn:
                conn.execute(
                    """INSERT INTO refresh_log
                    (id, entry_id, timestamp, old_staleness, new_staleness, method, status, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        result.entry_id,
                        result.timestamp,
                        result.old_staleness,
                        result.new_staleness,
                        result.refresh_method,
                        result.status,
                        result.error,
                    ),
                )
        except Exception as exc:
            logger.warning("Failed to persist refresh result: %s", exc)

    # ── Schedule Prediction ─────────────────────────────────────────────

    def schedule_refresh(
        self,
        entry_id: str,
        target_staleness: float = 0.5,
    ) -> Optional[Dict[str, Any]]:
        """Calculate optimal refresh schedule for an entry.

        Determines when the entry should next be refreshed to maintain
        its staleness below the target level.

        Args:
            entry_id: The Nexus entry ID.
            target_staleness: Desired maximum staleness (default 0.5).

        Returns:
            Schedule recommendation dict or None if entry not tracked.
        """
        ef = self.assess_entry(entry_id)
        if ef is None:
            return None

        # Time until staleness reaches target (in hours)
        predicted_crossing = _predict_staleness_crossing(
            current_staleness=ef.staleness_score,
            threshold=target_staleness,
            half_life=ef.half_life_days,
            age_days=ef.age_days,
        )

        if predicted_crossing is None:
            if ef.staleness_score >= target_staleness:
                return {
                    "entry_id": entry_id,
                    "title": ef.title,
                    "current_staleness": ef.staleness_score,
                    "target_staleness": target_staleness,
                    "recommendation": "refresh_now",
                    "next_refresh_at": None,
                    "hours_until_refresh": 0.0,
                }
            return {
                "entry_id": entry_id,
                "title": ef.title,
                "current_staleness": ef.staleness_score,
                "target_staleness": target_staleness,
                "recommendation": "no_refresh_needed",
                "next_refresh_at": None,
                "hours_until_refresh": None,
            }

        hours_until = max(0.0, (predicted_crossing - time.time()) / 3600.0)

        # Schedule at 80% of the predicted crossing time (proactive)
        proactive_hours = hours_until * 0.8
        proactive_ts = time.time() + proactive_hours * 3600.0

        return {
            "entry_id": entry_id,
            "title": ef.title,
            "current_staleness": ef.staleness_score,
            "target_staleness": target_staleness,
            "recommendation": "schedule_refresh",
            "next_refresh_at": proactive_ts,
            "hours_until_refresh": proactive_hours,
            "predicted_stale_at": predicted_crossing,
            "hours_until_stale": hours_until,
        }

    # ── Queries ─────────────────────────────────────────────────────────

    def tracked_count(self) -> int:
        """Return number of tracked entries."""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM entry_tracking").fetchone()
        return row[0] if row else 0

    def access_history(
        self,
        entry_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get access history for a specific entry."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM access_log WHERE entry_id = ? ORDER BY timestamp DESC LIMIT ?",
            (entry_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def refresh_history(
        self,
        entry_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get refresh history, optionally filtered by entry."""
        conn = self._get_conn()
        if entry_id:
            rows = conn.execute(
                "SELECT * FROM refresh_log WHERE entry_id = ? ORDER BY timestamp DESC LIMIT ?",
                (entry_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM refresh_log ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def snapshot(self) -> Dict[str, Any]:
        """Return engine status snapshot."""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM entry_tracking").fetchone()[0]
        total_accesses = conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
        total_refreshes = conn.execute("SELECT COUNT(*) FROM refresh_log").fetchone()[0]

        return {
            "tracked_entries": total,
            "total_accesses": total_accesses,
            "total_refreshes": total_refreshes,
            "refresh_history_size": len(self._refresh_history),
            "half_life_configs": len(_HALF_LIFE_DAYS),
            "threshold_configs": len(_STALENESS_THRESHOLDS),
        }


# ── Scheduler Integration ───────────────────────────────────────────────


def register_refresh_tasks(daemon: Any) -> None:
    """Register predictive refresh tasks with the scheduler daemon.

    Args:
        daemon: TaskSchedulerDaemon instance.
    """

    def _run_staleness_sweep() -> Dict[str, Any]:
        """Assess staleness across all tracked entries and refresh stale ones."""
        pr = get_predictive_refresh()
        report = pr.assess_staleness(limit=500)
        results = pr.refresh_stale(max_items=20)

        return {
            "status": "ok",
            "total_tracked": report.total_tracked,
            "stale_count": report.stale_count,
            "approaching_stale": report.approaching_stale,
            "avg_staleness": round(report.avg_staleness, 3),
            "refreshed": len([r for r in results if r.status == "refreshed"]),
            "failed": len([r for r in results if r.status == "failed"]),
        }

    daemon.register(
        "knowledge-staleness-sweep",
        "Knowledge Staleness Sweep",
        "every_6h",
        _run_staleness_sweep,
    )
