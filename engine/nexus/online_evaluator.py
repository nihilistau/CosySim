"""Online evaluation system for production model assessment.

Provides shadow evaluation, canary promotions, A/B testing, and production
feedback tracking.  Integrates with TrainingFlywheel (DPO preference data),
ImpactTracker (change auditing), ConfigManager (model config), NexusClient
(knowledge storage), and SchedulerDaemon (periodic sweeps).
"""

from __future__ import annotations

import enum
import json
import logging
import math
import os
import random
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──── Enums ────


class EvalMode(enum.Enum):
    """Evaluation mode determining how traffic is routed."""

    SHADOW = "shadow"
    CANARY = "canary"
    AB_TEST = "ab_test"


class EvalStatus(enum.Enum):
    """Lifecycle status of an evaluation session."""

    INACTIVE = "inactive"
    RUNNING = "running"
    PROMOTING = "promoting"
    ROLLING_BACK = "rolling_back"
    COMPLETED = "completed"
    FAILED = "failed"


class EvalDecision(enum.Enum):
    """Decision outcome for an evaluation session."""

    PROMOTE = "promote"
    ROLLBACK = "rollback"
    CONTINUE = "continue"
    INCONCLUSIVE = "inconclusive"


# ──── Data Structures ────


@dataclass
class EvalSession:
    """Represents a single evaluation session."""

    session_id: str
    mode: EvalMode
    status: EvalStatus
    production_model: str
    candidate_model: str
    traffic_percentage: float
    started_at: float
    min_samples: int
    max_duration_hours: float
    promote_threshold: float
    degradation_threshold: float
    completed_at: Optional[float] = None
    decision: Optional[EvalDecision] = None
    decision_reason: str = ""
    impact_change_id: Optional[str] = None


@dataclass
class EvalSample:
    """A single paired evaluation sample."""

    sample_id: str
    session_id: str
    request_text: str
    production_response: str
    candidate_response: str
    production_latency_ms: float
    candidate_latency_ms: float
    production_tokens: int
    candidate_tokens: int
    quality_score: Optional[float] = None
    preferred: Optional[str] = None
    timestamp: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalMetrics:
    """Aggregated metrics for an evaluation session."""

    session_id: str
    total_samples: int
    production_avg_latency: float
    candidate_avg_latency: float
    production_p95_latency: float
    candidate_p95_latency: float
    production_avg_quality: float
    candidate_avg_quality: float
    production_error_rate: float
    candidate_error_rate: float
    candidate_preference_rate: float
    latency_improvement_pct: float
    quality_improvement_pct: float


# ──── Lazy Integration Helpers ────


def _get_config() -> Any:
    """Lazy-load ConfigManager to avoid circular imports."""
    try:
        from engine.config import get_config
        return get_config()
    except Exception as exc:
        logger.debug("ConfigManager unavailable: %s", exc)
        return None


def _get_flywheel() -> Any:
    """Lazy-load TrainingFlywheel singleton."""
    try:
        from engine.nexus.training_flywheel import get_training_flywheel
        return get_training_flywheel()
    except Exception as exc:
        logger.debug("TrainingFlywheel unavailable: %s", exc)
        return None


def _get_impact_tracker() -> Any:
    """Lazy-load ImpactTracker singleton."""
    try:
        from engine.nexus.impact_tracker import get_impact_tracker
        return get_impact_tracker()
    except Exception as exc:
        logger.debug("ImpactTracker unavailable: %s", exc)
        return None


def _get_nexus_client() -> Any:
    """Lazy-load NexusClient singleton."""
    try:
        from engine.nexus.client import get_nexus_client
        return get_nexus_client()
    except Exception as exc:
        logger.debug("NexusClient unavailable: %s", exc)
        return None


def _change_type_model_promotion() -> Any:
    """Lazy-load ChangeType.MODEL_PROMOTION enum value."""
    try:
        from engine.nexus.impact_tracker import ChangeType
        return ChangeType.MODEL_PROMOTION
    except Exception:
        return "model_promotion"


# ──── OnlineEvaluator ────


class OnlineEvaluator:
    """Production model evaluation with shadow, canary, and A/B testing modes.

    Shadow mode: Run candidate model on same requests as production,
    compare outputs without affecting users.

    Canary mode: Route a small percentage of traffic to candidate model,
    measure real-world performance.

    A/B test mode: Split traffic 50/50 between production and candidate,
    statistical comparison.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            db_path = Path("data") / "online_eval.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._local = threading.local()
        self._session_cache: Dict[str, EvalSession] = {}
        self._cache_lock = threading.Lock()

        self._init_schema()
        self._reload_active_sessions()
        logger.info("OnlineEvaluator initialised (db=%s)", self._db_path)

    # ──── DB Helpers ────

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection with WAL mode."""
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        conn = self._get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS eval_sessions (
                session_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                production_model TEXT NOT NULL,
                candidate_model TEXT NOT NULL,
                traffic_percentage REAL DEFAULT 0.0,
                started_at REAL NOT NULL,
                min_samples INTEGER DEFAULT 50,
                max_duration_hours REAL DEFAULT 24.0,
                promote_threshold REAL DEFAULT 0.05,
                degradation_threshold REAL DEFAULT 0.10,
                completed_at REAL,
                decision TEXT,
                decision_reason TEXT,
                impact_change_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_es_status
                ON eval_sessions(status);

            CREATE TABLE IF NOT EXISTS eval_samples (
                sample_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                request_text TEXT,
                production_response TEXT,
                candidate_response TEXT,
                production_latency_ms REAL,
                candidate_latency_ms REAL,
                production_tokens INTEGER DEFAULT 0,
                candidate_tokens INTEGER DEFAULT 0,
                quality_score REAL,
                preferred TEXT,
                timestamp REAL NOT NULL,
                metadata TEXT,
                FOREIGN KEY (session_id)
                    REFERENCES eval_sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_samples_session
                ON eval_samples(session_id);
            CREATE INDEX IF NOT EXISTS idx_samples_ts
                ON eval_samples(timestamp);

            CREATE TABLE IF NOT EXISTS eval_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                request_id TEXT,
                quality_score REAL,
                latency_ms REAL,
                model TEXT,
                feedback_source TEXT,
                timestamp REAL NOT NULL,
                metadata TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_session
                ON eval_feedback(session_id);
            """
        )
        conn.commit()

    def _save_session(self, session: EvalSession) -> None:
        """Upsert an EvalSession to the database and cache."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO eval_sessions (
                session_id, mode, status, production_model, candidate_model,
                traffic_percentage, started_at, min_samples,
                max_duration_hours, promote_threshold, degradation_threshold,
                completed_at, decision, decision_reason, impact_change_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.mode.value,
                session.status.value,
                session.production_model,
                session.candidate_model,
                session.traffic_percentage,
                session.started_at,
                session.min_samples,
                session.max_duration_hours,
                session.promote_threshold,
                session.degradation_threshold,
                session.completed_at,
                session.decision.value if session.decision else None,
                session.decision_reason,
                session.impact_change_id,
            ),
        )
        conn.commit()

        with self._cache_lock:
            self._session_cache[session.session_id] = session

    def _load_session(self, session_id: str) -> Optional[EvalSession]:
        """Load a session from cache or database."""
        with self._cache_lock:
            cached = self._session_cache.get(session_id)
            if cached is not None:
                return cached

        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM eval_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None

        session = self._row_to_session(row)
        with self._cache_lock:
            self._session_cache[session.session_id] = session
        return session

    def _row_to_session(self, row: sqlite3.Row) -> EvalSession:
        """Convert a database row to an EvalSession."""
        decision_val = row["decision"]
        return EvalSession(
            session_id=row["session_id"],
            mode=EvalMode(row["mode"]),
            status=EvalStatus(row["status"]),
            production_model=row["production_model"],
            candidate_model=row["candidate_model"],
            traffic_percentage=row["traffic_percentage"],
            started_at=row["started_at"],
            min_samples=row["min_samples"],
            max_duration_hours=row["max_duration_hours"],
            promote_threshold=row["promote_threshold"],
            degradation_threshold=row["degradation_threshold"],
            completed_at=row["completed_at"],
            decision=EvalDecision(decision_val) if decision_val else None,
            decision_reason=row["decision_reason"] or "",
            impact_change_id=row["impact_change_id"],
        )

    def _reload_active_sessions(self) -> None:
        """Load all running sessions into the cache on startup."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM eval_sessions WHERE status = ?",
            (EvalStatus.RUNNING.value,),
        ).fetchall()
        with self._cache_lock:
            for row in rows:
                session = self._row_to_session(row)
                self._session_cache[session.session_id] = session
        if rows:
            logger.info("Reloaded %d active eval sessions from DB", len(rows))

    @staticmethod
    def _percentile(values: List[float], pct: float) -> float:
        """Calculate the given percentile from a sorted list of values.

        Args:
            values: List of numeric values (need not be sorted).
            pct: Percentile in range 0-100.

        Returns:
            The interpolated percentile value, or 0.0 for empty lists.
        """
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        if n == 1:
            return sorted_vals[0]
        k = (pct / 100.0) * (n - 1)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_vals[int(k)]
        return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])

    @staticmethod
    def _gen_session_id() -> str:
        return f"eval-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _gen_sample_id() -> str:
        return f"samp-{uuid.uuid4().hex[:8]}"

    def _current_production_model(self) -> str:
        """Read the current production model from config."""
        cfg = _get_config()
        if cfg is not None:
            return cfg.get("lmstudio.models.primary", "default-model")
        return "default-model"

    def _find_active_session(
        self, mode: Optional[EvalMode] = None
    ) -> Optional[EvalSession]:
        """Find the first active (RUNNING) session, optionally filtered by mode."""
        with self._cache_lock:
            for session in self._session_cache.values():
                if session.status != EvalStatus.RUNNING:
                    continue
                if mode is not None and session.mode != mode:
                    continue
                return session
        return None

    # ──── Session Management ────

    def start_shadow(
        self,
        candidate_model: str,
        production_model: Optional[str] = None,
        min_samples: int = 50,
        max_duration_hours: float = 24.0,
        promote_threshold: float = 0.05,
    ) -> EvalSession:
        """Start a shadow evaluation session.

        Args:
            candidate_model: Model ID to evaluate.
            production_model: Current production model (reads from config if None).
            min_samples: Minimum samples before making a decision.
            max_duration_hours: Maximum session duration.
            promote_threshold: Candidate must beat production by this fraction.

        Returns:
            Created EvalSession.
        """
        if production_model is None:
            production_model = self._current_production_model()

        session = EvalSession(
            session_id=self._gen_session_id(),
            mode=EvalMode.SHADOW,
            status=EvalStatus.RUNNING,
            production_model=production_model,
            candidate_model=candidate_model,
            traffic_percentage=0.0,
            started_at=time.time(),
            min_samples=min_samples,
            max_duration_hours=max_duration_hours,
            promote_threshold=promote_threshold,
            degradation_threshold=0.10,
        )
        self._save_session(session)
        logger.info(
            "Started SHADOW eval %s: %s vs %s (min=%d, max_h=%.1f)",
            session.session_id,
            production_model,
            candidate_model,
            min_samples,
            max_duration_hours,
        )
        return session

    def start_canary(
        self,
        candidate_model: str,
        traffic_percentage: float = 0.05,
        production_model: Optional[str] = None,
        min_samples: int = 100,
        max_duration_hours: float = 48.0,
        degradation_threshold: float = 0.10,
    ) -> EvalSession:
        """Start a canary promotion session.

        Args:
            candidate_model: Model to canary.
            traffic_percentage: Fraction of traffic to route to candidate (0.0-1.0).
            production_model: Current production model (reads from config if None).
            min_samples: Minimum samples before making a decision.
            max_duration_hours: Maximum session duration.
            degradation_threshold: Rollback if worse by this fraction.

        Returns:
            Created EvalSession.
        """
        if production_model is None:
            production_model = self._current_production_model()

        traffic_percentage = max(0.0, min(1.0, traffic_percentage))

        session = EvalSession(
            session_id=self._gen_session_id(),
            mode=EvalMode.CANARY,
            status=EvalStatus.RUNNING,
            production_model=production_model,
            candidate_model=candidate_model,
            traffic_percentage=traffic_percentage,
            started_at=time.time(),
            min_samples=min_samples,
            max_duration_hours=max_duration_hours,
            promote_threshold=0.05,
            degradation_threshold=degradation_threshold,
        )
        self._save_session(session)
        logger.info(
            "Started CANARY eval %s: %s → %s at %.1f%% traffic",
            session.session_id,
            production_model,
            candidate_model,
            traffic_percentage * 100,
        )
        return session

    def start_ab_test(
        self,
        candidate_model: str,
        production_model: Optional[str] = None,
        min_samples: int = 200,
        max_duration_hours: float = 72.0,
    ) -> EvalSession:
        """Start a 50/50 A/B test.

        Args:
            candidate_model: Model to test against production.
            production_model: Current production model (reads from config if None).
            min_samples: Minimum samples before making a decision.
            max_duration_hours: Maximum session duration.

        Returns:
            Created EvalSession.
        """
        if production_model is None:
            production_model = self._current_production_model()

        session = EvalSession(
            session_id=self._gen_session_id(),
            mode=EvalMode.AB_TEST,
            status=EvalStatus.RUNNING,
            production_model=production_model,
            candidate_model=candidate_model,
            traffic_percentage=0.5,
            started_at=time.time(),
            min_samples=min_samples,
            max_duration_hours=max_duration_hours,
            promote_threshold=0.05,
            degradation_threshold=0.10,
        )
        self._save_session(session)
        logger.info(
            "Started AB_TEST eval %s: %s vs %s (50/50)",
            session.session_id,
            production_model,
            candidate_model,
        )
        return session

    def stop_session(
        self,
        session_id: str,
        force_decision: Optional[EvalDecision] = None,
    ) -> Dict[str, Any]:
        """Stop an evaluation session and finalise results.

        Args:
            session_id: The session to stop.
            force_decision: If provided, use this decision instead of computing.

        Returns:
            Summary dict with session_id, decision, metrics, and reason.
        """
        session = self._load_session(session_id)
        if session is None:
            logger.warning("stop_session: session %s not found", session_id)
            return {"error": f"Session {session_id} not found"}

        if session.status not in (EvalStatus.RUNNING, EvalStatus.PROMOTING,
                                  EvalStatus.ROLLING_BACK):
            return {
                "session_id": session_id,
                "status": session.status.value,
                "message": "Session is not active",
            }

        try:
            metrics = self.compute_metrics(session_id)
        except Exception as exc:
            logger.error("Failed to compute metrics for %s: %s", session_id, exc)
            metrics = None

        if force_decision is not None:
            decision = force_decision
            reason = f"Forced decision: {decision.value}"
        elif metrics is not None and metrics.total_samples > 0:
            decision = self._evaluate_from_metrics(session, metrics)
            reason = self._build_decision_reason(decision, metrics, session)
        else:
            decision = EvalDecision.INCONCLUSIVE
            reason = "No samples collected"

        session.status = EvalStatus.COMPLETED
        session.completed_at = time.time()
        session.decision = decision
        session.decision_reason = reason
        self._save_session(session)

        logger.info(
            "Stopped session %s → %s (%s)",
            session_id,
            decision.value,
            reason,
        )

        metrics_summary = {}
        if metrics is not None:
            metrics_summary = {
                "total_samples": metrics.total_samples,
                "quality_improvement_pct": round(metrics.quality_improvement_pct, 4),
                "latency_improvement_pct": round(metrics.latency_improvement_pct, 4),
                "candidate_preference_rate": round(
                    metrics.candidate_preference_rate, 4
                ),
            }

        return {
            "session_id": session_id,
            "decision": decision.value,
            "reason": reason,
            "metrics": metrics_summary,
        }

    # ──── Sample Recording ────

    def shadow_evaluate(
        self,
        request_text: str,
        production_response: str,
        candidate_response: str,
        production_latency_ms: float,
        candidate_latency_ms: float,
        production_tokens: int = 0,
        candidate_tokens: int = 0,
        quality_score: Optional[float] = None,
        preferred: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[str]:
        """Record a shadow evaluation sample.

        If session_id is None, uses the first active session.  If *preferred*
        is provided (``"production"`` or ``"candidate"``), the preference pair
        is also forwarded to TrainingFlywheel for DPO training.

        Args:
            request_text: The prompt / request text.
            production_response: Response from the production model.
            candidate_response: Response from the candidate model.
            production_latency_ms: Production model latency.
            candidate_latency_ms: Candidate model latency.
            production_tokens: Token count for production response.
            candidate_tokens: Token count for candidate response.
            quality_score: Optional quality rating 0-1.
            preferred: ``"production"`` or ``"candidate"``.
            session_id: Explicit session; auto-detected if None.

        Returns:
            sample_id, or None if no active session exists.
        """
        session: Optional[EvalSession] = None
        if session_id is not None:
            session = self._load_session(session_id)
        else:
            session = self._find_active_session()

        if session is None or session.status != EvalStatus.RUNNING:
            logger.debug("shadow_evaluate: no active session available")
            return None

        sample_id = self._gen_sample_id()
        now = time.time()

        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO eval_samples (
                sample_id, session_id, request_text,
                production_response, candidate_response,
                production_latency_ms, candidate_latency_ms,
                production_tokens, candidate_tokens,
                quality_score, preferred, timestamp, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample_id,
                session.session_id,
                request_text,
                production_response,
                candidate_response,
                production_latency_ms,
                candidate_latency_ms,
                production_tokens,
                candidate_tokens,
                quality_score,
                preferred,
                now,
                "{}",
            ),
        )
        conn.commit()

        # Forward preference data to TrainingFlywheel for DPO training
        if preferred in ("production", "candidate"):
            self._forward_preference(
                request_text,
                production_response,
                candidate_response,
                preferred,
                session.candidate_model,
            )

        logger.debug(
            "Recorded sample %s for session %s (preferred=%s)",
            sample_id,
            session.session_id,
            preferred,
        )
        return sample_id

    def _forward_preference(
        self,
        request_text: str,
        production_response: str,
        candidate_response: str,
        preferred: str,
        model: str,
    ) -> None:
        """Send preference pair to TrainingFlywheel for DPO collection."""
        flywheel = _get_flywheel()
        if flywheel is None:
            return
        try:
            if preferred == "candidate":
                chosen, rejected = candidate_response, production_response
            else:
                chosen, rejected = production_response, candidate_response
            flywheel.collect_preference(
                prompt=request_text,
                chosen=chosen,
                rejected=rejected,
                model=model,
            )
        except Exception as exc:
            logger.warning("Failed to forward preference to flywheel: %s", exc)

    def record_feedback(
        self,
        request_id: str,
        quality_score: float,
        latency_ms: float,
        model: str = "",
        session_id: Optional[str] = None,
        feedback_source: str = "auto",
    ) -> None:
        """Record production feedback for a specific request.

        Args:
            request_id: Original request identifier.
            quality_score: 0.0-1.0 quality rating.
            latency_ms: Observed latency in milliseconds.
            model: Which model served this request.
            session_id: Optional evaluation session context.
            feedback_source: ``"auto"``, ``"human"``, or ``"agent"``.
        """
        quality_score = max(0.0, min(1.0, quality_score))
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO eval_feedback (
                session_id, request_id, quality_score, latency_ms,
                model, feedback_source, timestamp, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                request_id,
                quality_score,
                latency_ms,
                model,
                feedback_source,
                time.time(),
                "{}",
            ),
        )
        conn.commit()
        logger.debug(
            "Recorded feedback for request %s (score=%.2f, source=%s)",
            request_id,
            quality_score,
            feedback_source,
        )

    # ──── Metrics & Analysis ────

    def compute_metrics(self, session_id: str) -> EvalMetrics:
        """Compute aggregated metrics for an evaluation session.

        Calculates means, p95 latency, quality averages, error rates,
        preference rates, and improvement percentages.

        Args:
            session_id: The session to compute metrics for.

        Returns:
            Populated EvalMetrics dataclass.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM eval_samples WHERE session_id = ?", (session_id,)
        ).fetchall()

        total = len(rows)
        if total == 0:
            return EvalMetrics(
                session_id=session_id,
                total_samples=0,
                production_avg_latency=0.0,
                candidate_avg_latency=0.0,
                production_p95_latency=0.0,
                candidate_p95_latency=0.0,
                production_avg_quality=0.0,
                candidate_avg_quality=0.0,
                production_error_rate=0.0,
                candidate_error_rate=0.0,
                candidate_preference_rate=0.0,
                latency_improvement_pct=0.0,
                quality_improvement_pct=0.0,
            )

        prod_latencies: List[float] = []
        cand_latencies: List[float] = []
        quality_scores: List[float] = []
        prod_errors = 0
        cand_errors = 0
        candidate_preferred_count = 0
        preference_total = 0

        for row in rows:
            p_lat = row["production_latency_ms"] or 0.0
            c_lat = row["candidate_latency_ms"] or 0.0
            prod_latencies.append(p_lat)
            cand_latencies.append(c_lat)

            qs = row["quality_score"]
            if qs is not None:
                quality_scores.append(qs)

            pref = row["preferred"]
            if pref in ("production", "candidate"):
                preference_total += 1
                if pref == "candidate":
                    candidate_preferred_count += 1

            p_resp = row["production_response"] or ""
            c_resp = row["candidate_response"] or ""
            if not p_resp.strip():
                prod_errors += 1
            if not c_resp.strip():
                cand_errors += 1

        prod_avg_lat = sum(prod_latencies) / total
        cand_avg_lat = sum(cand_latencies) / total
        prod_p95 = self._percentile(prod_latencies, 95.0)
        cand_p95 = self._percentile(cand_latencies, 95.0)

        # Quality: split by preference where available, fallback to overall
        prod_quality_scores: List[float] = []
        cand_quality_scores: List[float] = []
        for row in rows:
            qs = row["quality_score"]
            if qs is None:
                continue
            pref = row["preferred"]
            if pref == "production":
                prod_quality_scores.append(qs)
            elif pref == "candidate":
                cand_quality_scores.append(qs)
            else:
                prod_quality_scores.append(qs)
                cand_quality_scores.append(qs)

        prod_avg_q = (
            sum(prod_quality_scores) / len(prod_quality_scores)
            if prod_quality_scores
            else 0.0
        )
        cand_avg_q = (
            sum(cand_quality_scores) / len(cand_quality_scores)
            if cand_quality_scores
            else 0.0
        )

        prod_err_rate = prod_errors / total
        cand_err_rate = cand_errors / total

        cand_pref_rate = (
            candidate_preferred_count / preference_total
            if preference_total > 0
            else 0.0
        )

        lat_improvement = (
            (prod_avg_lat - cand_avg_lat) / prod_avg_lat
            if prod_avg_lat > 0
            else 0.0
        )

        qual_improvement = (
            (cand_avg_q - prod_avg_q) / prod_avg_q if prod_avg_q > 0 else 0.0
        )

        return EvalMetrics(
            session_id=session_id,
            total_samples=total,
            production_avg_latency=prod_avg_lat,
            candidate_avg_latency=cand_avg_lat,
            production_p95_latency=prod_p95,
            candidate_p95_latency=cand_p95,
            production_avg_quality=prod_avg_q,
            candidate_avg_quality=cand_avg_q,
            production_error_rate=prod_err_rate,
            candidate_error_rate=cand_err_rate,
            candidate_preference_rate=cand_pref_rate,
            latency_improvement_pct=lat_improvement,
            quality_improvement_pct=qual_improvement,
        )

    def _evaluate_from_metrics(
        self, session: EvalSession, metrics: EvalMetrics
    ) -> EvalDecision:
        """Core decision logic using computed metrics.

        Rules:
            1. If total_samples < min_samples → CONTINUE
            2. If candidate_error_rate > production_error_rate * 2 → ROLLBACK
            3. If quality_improvement_pct > promote_threshold → PROMOTE
            4. If quality_improvement_pct < -degradation_threshold → ROLLBACK
            5. If duration > max_duration_hours → INCONCLUSIVE
            6. Otherwise → CONTINUE
        """
        if metrics.total_samples < session.min_samples:
            return EvalDecision.CONTINUE

        if (
            metrics.production_error_rate > 0
            and metrics.candidate_error_rate > metrics.production_error_rate * 2
        ):
            return EvalDecision.ROLLBACK

        if metrics.candidate_error_rate > 0.5 and metrics.production_error_rate < 0.1:
            return EvalDecision.ROLLBACK

        if metrics.quality_improvement_pct > session.promote_threshold:
            return EvalDecision.PROMOTE

        if metrics.quality_improvement_pct < -session.degradation_threshold:
            return EvalDecision.ROLLBACK

        elapsed_hours = (time.time() - session.started_at) / 3600.0
        if elapsed_hours > session.max_duration_hours:
            return EvalDecision.INCONCLUSIVE

        return EvalDecision.CONTINUE

    @staticmethod
    def _build_decision_reason(
        decision: EvalDecision,
        metrics: EvalMetrics,
        session: EvalSession,
    ) -> str:
        """Build a human-readable explanation for a decision."""
        parts: List[str] = [
            f"samples={metrics.total_samples}",
            f"quality_δ={metrics.quality_improvement_pct:+.2%}",
            f"latency_δ={metrics.latency_improvement_pct:+.2%}",
            f"pref_rate={metrics.candidate_preference_rate:.2%}",
            f"prod_err={metrics.production_error_rate:.2%}",
            f"cand_err={metrics.candidate_error_rate:.2%}",
        ]
        detail = ", ".join(parts)

        if decision == EvalDecision.PROMOTE:
            return (
                f"Candidate beats production by "
                f"{metrics.quality_improvement_pct:+.2%} quality "
                f"(threshold {session.promote_threshold:+.2%}). {detail}"
            )
        if decision == EvalDecision.ROLLBACK:
            return f"Candidate degradation detected. {detail}"
        if decision == EvalDecision.INCONCLUSIVE:
            return f"Session expired without clear winner. {detail}"
        return f"Insufficient data to decide. {detail}"

    def evaluate_decision(self, session_id: str) -> EvalDecision:
        """Evaluate whether to promote, rollback, or continue.

        Args:
            session_id: The session to evaluate.

        Returns:
            EvalDecision indicating the recommended action.
        """
        session = self._load_session(session_id)
        if session is None:
            logger.warning("evaluate_decision: session %s not found", session_id)
            return EvalDecision.INCONCLUSIVE

        metrics = self.compute_metrics(session_id)
        return self._evaluate_from_metrics(session, metrics)

    def auto_check(self) -> List[Dict[str, Any]]:
        """Check all active sessions and auto-promote/rollback as needed.

        For each running session:
            1. Compute current metrics.
            2. Evaluate decision.
            3. If PROMOTE: apply model promotion, record in ImpactTracker.
            4. If ROLLBACK: revert any canary config, record in ImpactTracker.
            5. If session expired (max_duration): force INCONCLUSIVE.

        Returns:
            List of ``{session_id, decision, metrics_summary}`` dicts.
        """
        results: List[Dict[str, Any]] = []

        with self._cache_lock:
            running = [
                s
                for s in self._session_cache.values()
                if s.status == EvalStatus.RUNNING
            ]

        if not running:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM eval_sessions WHERE status = ?",
                (EvalStatus.RUNNING.value,),
            ).fetchall()
            running = [self._row_to_session(row) for row in rows]
            with self._cache_lock:
                for s in running:
                    self._session_cache[s.session_id] = s

        for session in running:
            try:
                result = self._check_single_session(session)
                results.append(result)
            except Exception as exc:
                logger.error(
                    "auto_check failed for session %s: %s",
                    session.session_id,
                    exc,
                )
                results.append(
                    {
                        "session_id": session.session_id,
                        "decision": "error",
                        "error": str(exc),
                    }
                )

        if results:
            logger.info(
                "auto_check completed: %d sessions evaluated", len(results)
            )
        return results

    def _check_single_session(self, session: EvalSession) -> Dict[str, Any]:
        """Evaluate a single running session and act on the decision."""
        metrics = self.compute_metrics(session.session_id)
        decision = self._evaluate_from_metrics(session, metrics)

        metrics_summary = {
            "total_samples": metrics.total_samples,
            "quality_improvement_pct": round(metrics.quality_improvement_pct, 4),
            "latency_improvement_pct": round(metrics.latency_improvement_pct, 4),
            "candidate_preference_rate": round(metrics.candidate_preference_rate, 4),
            "production_error_rate": round(metrics.production_error_rate, 4),
            "candidate_error_rate": round(metrics.candidate_error_rate, 4),
        }

        result: Dict[str, Any] = {
            "session_id": session.session_id,
            "decision": decision.value,
            "metrics_summary": metrics_summary,
        }

        if decision == EvalDecision.PROMOTE:
            promo = self.promote_model(session.session_id)
            result["promotion"] = promo
        elif decision == EvalDecision.ROLLBACK:
            rb = self.rollback_model(session.session_id)
            result["rollback"] = rb
        elif decision == EvalDecision.INCONCLUSIVE:
            self.stop_session(session.session_id, force_decision=decision)
        # CONTINUE → do nothing, let session keep collecting data

        return result

    # ──── Model Promotion / Rollback ────

    def promote_model(self, session_id: str) -> Dict[str, Any]:
        """Promote candidate model to production.

        Steps:
            1. Update config: ``lmstudio.models.primary = candidate_model``.
            2. Record change in ImpactTracker.
            3. Update session status to COMPLETED, decision to PROMOTE.
            4. Store summary in Nexus.

        Args:
            session_id: The session whose candidate should be promoted.

        Returns:
            Dict with promoted status, model name, and impact_change_id.
        """
        session = self._load_session(session_id)
        if session is None:
            return {"promoted": False, "error": f"Session {session_id} not found"}

        session.status = EvalStatus.PROMOTING
        self._save_session(session)

        # Update config
        cfg = _get_config()
        if cfg is not None:
            try:
                cfg.set("lmstudio.models.primary", session.candidate_model)
                logger.info(
                    "Config updated: lmstudio.models.primary → %s",
                    session.candidate_model,
                )
            except Exception as exc:
                logger.error("Failed to update config: %s", exc)

        # Record in ImpactTracker
        change_id = self._record_impact_change(
            session,
            title=f"Model promotion: {session.candidate_model}",
            description=(
                f"Online evaluator promoted {session.candidate_model} "
                f"over {session.production_model} after {session.session_id} "
                f"({session.mode.value} evaluation)."
            ),
        )

        metrics = self.compute_metrics(session_id)
        reason = self._build_decision_reason(
            EvalDecision.PROMOTE, metrics, session
        )

        session.status = EvalStatus.COMPLETED
        session.completed_at = time.time()
        session.decision = EvalDecision.PROMOTE
        session.decision_reason = reason
        session.impact_change_id = change_id
        self._save_session(session)

        self._store_in_nexus(session, metrics)

        logger.info(
            "Promoted model %s → %s (session %s)",
            session.production_model,
            session.candidate_model,
            session_id,
        )
        return {
            "promoted": True,
            "model": session.candidate_model,
            "impact_change_id": change_id or "",
        }

    def rollback_model(self, session_id: str) -> Dict[str, Any]:
        """Rollback to production model (revert any canary config changes).

        Steps:
            1. Restore original model config if it was changed.
            2. Record in ImpactTracker.
            3. Update session status.

        Args:
            session_id: The session to rollback.

        Returns:
            Dict with rolled_back status and restored model name.
        """
        session = self._load_session(session_id)
        if session is None:
            return {"rolled_back": False, "error": f"Session {session_id} not found"}

        session.status = EvalStatus.ROLLING_BACK
        self._save_session(session)

        # Ensure config points to the original production model
        cfg = _get_config()
        if cfg is not None:
            try:
                current = cfg.get("lmstudio.models.primary", "")
                if current == session.candidate_model:
                    cfg.set("lmstudio.models.primary", session.production_model)
                    logger.info(
                        "Config restored: lmstudio.models.primary → %s",
                        session.production_model,
                    )
            except Exception as exc:
                logger.error("Failed to restore config: %s", exc)

        self._record_impact_change(
            session,
            title=f"Model rollback: reverted to {session.production_model}",
            description=(
                f"Online evaluator rolled back {session.candidate_model} "
                f"to {session.production_model} during {session.session_id} "
                f"({session.mode.value} evaluation)."
            ),
        )

        metrics = self.compute_metrics(session_id)
        reason = self._build_decision_reason(
            EvalDecision.ROLLBACK, metrics, session
        )

        session.status = EvalStatus.COMPLETED
        session.completed_at = time.time()
        session.decision = EvalDecision.ROLLBACK
        session.decision_reason = reason
        self._save_session(session)

        logger.info(
            "Rolled back to %s (session %s)", session.production_model, session_id
        )
        return {"rolled_back": True, "model": session.production_model}

    def _record_impact_change(
        self, session: EvalSession, title: str, description: str
    ) -> Optional[str]:
        """Record a change in ImpactTracker, returning the change_id or None."""
        tracker = _get_impact_tracker()
        if tracker is None:
            return None
        try:
            change_type = _change_type_model_promotion()
            change_id = tracker.record_change(
                change_type,
                title,
                description,
                source="online_evaluator",
            )
            tracker.finalize_change(change_id)
            return change_id
        except Exception as exc:
            logger.warning("ImpactTracker record failed: %s", exc)
            return None

    def _store_in_nexus(
        self, session: EvalSession, metrics: EvalMetrics
    ) -> None:
        """Persist evaluation outcome in Nexus for knowledge reuse."""
        client = _get_nexus_client()
        if client is None:
            return
        try:
            content = (
                f"Evaluation session {session.session_id} ({session.mode.value}) "
                f"completed with decision: {session.decision.value if session.decision else 'unknown'}.\n\n"
                f"Production model: {session.production_model}\n"
                f"Candidate model: {session.candidate_model}\n"
                f"Samples: {metrics.total_samples}\n"
                f"Quality improvement: {metrics.quality_improvement_pct:+.2%}\n"
                f"Latency improvement: {metrics.latency_improvement_pct:+.2%}\n"
                f"Candidate preference rate: {metrics.candidate_preference_rate:.2%}\n"
                f"Reason: {session.decision_reason}"
            )
            client.add_entry(
                title=f"Online Eval: {session.candidate_model} ({session.decision.value if session.decision else 'N/A'})",
                content=content,
                content_type="note",
                category="performance",
            )

            if session.decision == EvalDecision.PROMOTE:
                client.add_qa(
                    question=f"Was {session.candidate_model} promoted to production?",
                    answer=(
                        f"Yes. {session.candidate_model} was promoted over "
                        f"{session.production_model} with "
                        f"{metrics.quality_improvement_pct:+.2%} quality improvement "
                        f"and {metrics.candidate_preference_rate:.0%} preference rate "
                        f"across {metrics.total_samples} samples."
                    ),
                    category="performance",
                )
        except Exception as exc:
            logger.warning("Failed to store eval results in Nexus: %s", exc)

    # ──── Query Methods ────

    def get_session(self, session_id: str) -> Optional[EvalSession]:
        """Retrieve evaluation session by ID.

        Args:
            session_id: The session identifier.

        Returns:
            EvalSession or None if not found.
        """
        return self._load_session(session_id)

    def active_sessions(self) -> List[Dict[str, Any]]:
        """List all currently running evaluation sessions.

        Returns:
            List of session summary dicts.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM eval_sessions WHERE status = ?",
            (EvalStatus.RUNNING.value,),
        ).fetchall()
        return [self._session_row_to_dict(row) for row in rows]

    def list_sessions(
        self,
        status: Optional[EvalStatus] = None,
        days: int = 30,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List evaluation sessions with optional filters.

        Args:
            status: Filter by session status.
            days: Only return sessions started within this many days.
            limit: Maximum number of sessions to return.

        Returns:
            List of session summary dicts ordered by start time descending.
        """
        conn = self._get_conn()
        cutoff = time.time() - (days * 86400)

        if status is not None:
            rows = conn.execute(
                "SELECT * FROM eval_sessions "
                "WHERE status = ? AND started_at >= ? "
                "ORDER BY started_at DESC LIMIT ?",
                (status.value, cutoff, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM eval_sessions "
                "WHERE started_at >= ? "
                "ORDER BY started_at DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()

        return [self._session_row_to_dict(row) for row in rows]

    def session_samples(
        self, session_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get recorded samples for a session.

        Args:
            session_id: The session to query.
            limit: Maximum number of samples to return.

        Returns:
            List of sample dicts ordered by timestamp descending.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM eval_samples WHERE session_id = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            meta = d.get("metadata")
            if meta and isinstance(meta, str):
                try:
                    d["metadata"] = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    d["metadata"] = {}
            results.append(d)
        return results

    def eval_stats(self) -> Dict[str, Any]:
        """Summary statistics across all sessions.

        Returns:
            Dict with total_sessions, breakdowns by mode/status/decision,
            total_samples, avg_samples_per_session, promotion_rate,
            rollback_rate, and avg_quality_improvement.
        """
        conn = self._get_conn()

        total_sessions = conn.execute(
            "SELECT COUNT(*) FROM eval_sessions"
        ).fetchone()[0]

        by_mode: Dict[str, int] = {}
        for row in conn.execute(
            "SELECT mode, COUNT(*) as cnt FROM eval_sessions GROUP BY mode"
        ):
            by_mode[row["mode"]] = row["cnt"]

        by_status: Dict[str, int] = {}
        for row in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM eval_sessions GROUP BY status"
        ):
            by_status[row["status"]] = row["cnt"]

        by_decision: Dict[str, int] = {}
        for row in conn.execute(
            "SELECT decision, COUNT(*) as cnt FROM eval_sessions "
            "WHERE decision IS NOT NULL GROUP BY decision"
        ):
            by_decision[row["decision"] or "none"] = row["cnt"]

        total_samples = conn.execute(
            "SELECT COUNT(*) FROM eval_samples"
        ).fetchone()[0]

        avg_samples = total_samples / total_sessions if total_sessions > 0 else 0.0

        completed = by_status.get("completed", 0)
        promotions = by_decision.get("promote", 0)
        rollbacks = by_decision.get("rollback", 0)

        promotion_rate = promotions / completed if completed > 0 else 0.0
        rollback_rate = rollbacks / completed if completed > 0 else 0.0

        # Average quality improvement across completed sessions with samples
        completed_sessions = conn.execute(
            "SELECT session_id FROM eval_sessions WHERE status = ?",
            (EvalStatus.COMPLETED.value,),
        ).fetchall()

        quality_improvements: List[float] = []
        for row in completed_sessions:
            sid = row["session_id"]
            try:
                m = self.compute_metrics(sid)
                if m.total_samples > 0:
                    quality_improvements.append(m.quality_improvement_pct)
            except Exception:
                pass

        avg_quality_improvement = (
            sum(quality_improvements) / len(quality_improvements)
            if quality_improvements
            else 0.0
        )

        return {
            "total_sessions": total_sessions,
            "by_mode": by_mode,
            "by_status": by_status,
            "by_decision": by_decision,
            "total_samples": total_samples,
            "avg_samples_per_session": round(avg_samples, 1),
            "promotion_rate": round(promotion_rate, 4),
            "rollback_rate": round(rollback_rate, 4),
            "avg_quality_improvement": round(avg_quality_improvement, 4),
        }

    @staticmethod
    def _session_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a session DB row to a plain dict."""
        return {
            "session_id": row["session_id"],
            "mode": row["mode"],
            "status": row["status"],
            "production_model": row["production_model"],
            "candidate_model": row["candidate_model"],
            "traffic_percentage": row["traffic_percentage"],
            "started_at": row["started_at"],
            "min_samples": row["min_samples"],
            "max_duration_hours": row["max_duration_hours"],
            "promote_threshold": row["promote_threshold"],
            "degradation_threshold": row["degradation_threshold"],
            "completed_at": row["completed_at"],
            "decision": row["decision"],
            "decision_reason": row["decision_reason"],
            "impact_change_id": row["impact_change_id"],
        }

    # ──── Routing Helper ────

    def should_use_candidate(self, session_id: Optional[str] = None) -> bool:
        """For canary/AB mode: should this request use the candidate model?

        Uses ``traffic_percentage`` to decide probabilistically.  Only returns
        ``True`` for RUNNING sessions in canary or ab_test mode.

        Args:
            session_id: Explicit session to check; auto-detects if None.

        Returns:
            True if this request should be routed to the candidate model.
        """
        session: Optional[EvalSession] = None
        if session_id is not None:
            session = self._load_session(session_id)
        else:
            session = self._find_active_session(EvalMode.CANARY)
            if session is None:
                session = self._find_active_session(EvalMode.AB_TEST)

        if session is None:
            return False
        if session.status != EvalStatus.RUNNING:
            return False
        if session.mode not in (EvalMode.CANARY, EvalMode.AB_TEST):
            return False

        return random.random() < session.traffic_percentage


# ──── Scheduler Integration ────


def _online_eval_sweep_callback() -> Dict[str, Any]:
    """Callback for scheduler: check all active eval sessions."""
    evaluator = get_online_evaluator()
    results = evaluator.auto_check()
    return {
        "checked": len(results),
        "decisions": [
            {"session_id": r["session_id"], "decision": r.get("decision")}
            for r in results
        ],
    }


def register_online_eval_tasks(daemon: Any) -> None:
    """Register online evaluation scheduler tasks.

    Args:
        daemon: TaskSchedulerDaemon instance.
    """
    try:
        daemon.register(
            task_id="online-eval-sweep",
            name="Online Eval Sweep (Hourly)",
            schedule="every_1h",
            callback=_online_eval_sweep_callback,
            enabled=True,
        )
        logger.info("Registered online-eval-sweep scheduler task")
    except Exception as exc:
        logger.warning("Failed to register eval sweep task: %s", exc)


# ──── Singleton ────

_instance: Optional[OnlineEvaluator] = None
_lock = threading.Lock()


def get_online_evaluator(db_path: Optional[Path] = None) -> OnlineEvaluator:
    """Thread-safe singleton getter for OnlineEvaluator.

    Args:
        db_path: Optional override for the database file path.

    Returns:
        The singleton OnlineEvaluator instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = OnlineEvaluator(db_path)
    return _instance
