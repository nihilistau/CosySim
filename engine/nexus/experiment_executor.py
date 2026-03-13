"""
Experiment Executor — Run experiment proposals with statistical rigor.

Accepts proposals from ExperimentProposer and executes the full lifecycle:
capture baseline, apply treatment, capture treatment metrics, run statistical
analysis, auto-promote or rollback, and store results in Nexus + ImpactTracker.

Pipeline:
    1. Fetch pending proposals from ExperimentProposer
    2. Capture baseline metrics (N iterations)
    3. Apply treatment (config change, model swap, etc.)
    4. Capture treatment metrics (N iterations)
    5. Statistical comparison (paired t-test or Wilcoxon)
    6. Auto-promote if treatment wins (p < 0.05, effect > threshold)
    7. Auto-rollback if treatment loses or fails
    8. Store results in Nexus + ImpactTracker

Thread-safe singleton — call ``get_experiment_executor()``.
"""

from __future__ import annotations

import enum
import json
import logging
import math
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from engine.paths import DATA_DIR

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = DATA_DIR / "experiment_executor.db"


# ── Data Models ─────────────────────────────────────────────────────────


class ExperimentStatus(enum.Enum):
    """Lifecycle states for an experiment run."""

    PENDING = "pending"
    BASELINE = "baseline"
    RUNNING = "running"
    COLLECTING = "collecting"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class ExperimentRun:
    """A single execution of an experiment proposal.

    Attributes:
        run_id: Unique identifier ``exp-{uuid[:8]}``.
        proposal_id: Links back to the originating ExperimentProposal.
        experiment_name: Human-readable experiment name.
        status: Current lifecycle state.
        hypothesis: What the experiment aims to prove.
        variants: List of variant dicts ``[{id, label, config}]``.
        success_metric: Metric used to judge success.
        success_threshold: Minimum improvement to declare success.
        baseline_metrics: Metric values captured before treatment.
        treatment_metrics: Metric values captured after treatment.
        active_variant: Which variant is currently applied.
        config_backup: Original config values for rollback.
        result: Statistical analysis results.
        started_at: Unix timestamp when execution began.
        completed_at: Unix timestamp when execution ended.
        error: Error message if the run failed.
        impact_change_id: Links to ImpactTracker change record.
    """

    run_id: str
    proposal_id: str
    experiment_name: str
    status: ExperimentStatus
    hypothesis: str
    variants: List[Dict[str, Any]]
    success_metric: str
    success_threshold: float
    baseline_metrics: Dict[str, float]
    treatment_metrics: Dict[str, float]
    active_variant: Optional[str]
    config_backup: Dict[str, Any]
    result: Optional[Dict[str, Any]]
    started_at: float
    completed_at: Optional[float] = None
    error: Optional[str] = None
    impact_change_id: Optional[str] = None


# ── Priority ordering ───────────────────────────────────────────────────

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


# ── SQL Schema ──────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    experiment_name TEXT NOT NULL,
    status TEXT NOT NULL,
    hypothesis TEXT,
    variants TEXT,
    success_metric TEXT,
    success_threshold REAL,
    baseline_metrics TEXT,
    treatment_metrics TEXT,
    active_variant TEXT,
    config_backup TEXT,
    result TEXT,
    started_at REAL,
    completed_at REAL,
    error TEXT,
    impact_change_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_status ON experiment_runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_ts ON experiment_runs(started_at);

CREATE TABLE IF NOT EXISTS experiment_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    timestamp REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES experiment_runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_em_run ON experiment_metrics(run_id, phase);
"""


# ── Lazy dependency helpers ─────────────────────────────────────────────


def _get_proposer() -> Any:
    """Lazy import of ExperimentProposer singleton."""
    try:
        from engine.nexus.experiment_proposals import get_experiment_proposer
        return get_experiment_proposer()
    except Exception as exc:
        logger.warning("ExperimentProposer unavailable: %s", exc)
        return None


def _get_impact_tracker() -> Any:
    """Lazy import of ImpactTracker singleton."""
    try:
        from engine.nexus.impact_tracker import get_impact_tracker
        return get_impact_tracker()
    except Exception as exc:
        logger.debug("ImpactTracker unavailable: %s", exc)
        return None


def _get_nexus_client() -> Any:
    """Lazy import of NexusClient singleton."""
    try:
        from engine.nexus.client import get_nexus_client
        return get_nexus_client()
    except Exception as exc:
        logger.debug("NexusClient unavailable: %s", exc)
        return None


def _get_config() -> Any:
    """Lazy import of ConfigManager singleton."""
    try:
        from engine.config import get_config
        return get_config()
    except Exception as exc:
        logger.debug("ConfigManager unavailable: %s", exc)
        return None


def _get_metrics_db() -> Any:
    """Lazy import of MetricsDB singleton."""
    try:
        from engine.observability.metrics_db import get_metrics_db
        return get_metrics_db()
    except Exception as exc:
        logger.debug("MetricsDB unavailable: %s", exc)
        return None


# ── Statistical helpers (module-level for reuse) ────────────────────────


def _try_scipy_ttest(
    baseline: List[float], treatment: List[float]
) -> Optional[Tuple[float, float]]:
    """Attempt scipy paired t-test. Returns (t_stat, p_value) or None."""
    try:
        from scipy import stats as sp_stats
        result = sp_stats.ttest_rel(treatment, baseline)
        return (float(result.statistic), float(result.pvalue))
    except Exception:
        return None


def _try_scipy_wilcoxon(
    baseline: List[float], treatment: List[float]
) -> Optional[Tuple[float, float]]:
    """Attempt scipy Wilcoxon signed-rank test. Returns (stat, p_value) or None."""
    try:
        from scipy import stats as sp_stats
        differences = [t - b for t, b in zip(treatment, baseline)]
        if all(d == 0.0 for d in differences):
            return (0.0, 1.0)
        result = sp_stats.wilcoxon(differences)
        return (float(result.statistic), float(result.pvalue))
    except Exception:
        return None


# ── Executor ────────────────────────────────────────────────────────────


class ExperimentExecutor:
    """Executes experiment proposals with statistical rigor.

    Lifecycle:
        1. Accept proposal from ExperimentProposer
        2. Capture baseline metrics (N iterations)
        3. Apply treatment (config change, model swap, etc.)
        4. Capture treatment metrics (N iterations)
        5. Statistical comparison (paired t-test or Wilcoxon)
        6. Auto-promote if treatment wins (p < 0.05, effect > threshold)
        7. Auto-rollback if treatment loses or fails
        8. Store results in Nexus + ImpactTracker
    """

    DEFAULT_ITERATIONS: int = 10
    DEFAULT_SETTLE_SECONDS: float = 30.0
    SIGNIFICANCE_LEVEL: float = 0.05
    SAMPLE_INTERVAL: float = 3.0  # seconds between metric samples

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialize the executor with SQLite backing store.

        Args:
            db_path: Path to the SQLite database file. Defaults to
                ``data/experiment_executor.db``.
        """
        self._path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._rw_lock = threading.Lock()
        self._init_schema()
        logger.info("ExperimentExecutor initialised (db=%s)", self._path)

    # ── DB helpers ──────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create a thread-local SQLite connection.

        Returns:
            sqlite3.Connection with WAL mode and row_factory set.
        """
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._path), timeout=10)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    @contextmanager
    def _cursor(self):
        """Yield a cursor with auto-commit / rollback.

        Yields:
            sqlite3.Cursor bound to the thread-local connection.
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
        """Create tables and indices if they do not exist."""
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    def _save_run(self, run: ExperimentRun) -> None:
        """Persist an ExperimentRun to the database.

        Args:
            run: The experiment run to save.
        """
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO experiment_runs "
                "(run_id, proposal_id, experiment_name, status, hypothesis, "
                "variants, success_metric, success_threshold, baseline_metrics, "
                "treatment_metrics, active_variant, config_backup, result, "
                "started_at, completed_at, error, impact_change_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run.run_id,
                    run.proposal_id,
                    run.experiment_name,
                    run.status.value,
                    run.hypothesis,
                    json.dumps(run.variants),
                    run.success_metric,
                    run.success_threshold,
                    json.dumps(run.baseline_metrics),
                    json.dumps(run.treatment_metrics),
                    run.active_variant,
                    json.dumps(run.config_backup),
                    json.dumps(run.result) if run.result else None,
                    run.started_at,
                    run.completed_at,
                    run.error,
                    run.impact_change_id,
                ),
            )

    def _load_run(self, run_id: str) -> Optional[ExperimentRun]:
        """Load an ExperimentRun from the database.

        Args:
            run_id: Unique run identifier.

        Returns:
            ExperimentRun if found, else None.
        """
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM experiment_runs WHERE run_id = ?", (run_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_run(row)

    def _row_to_run(self, row: sqlite3.Row) -> ExperimentRun:
        """Convert a database row to an ExperimentRun dataclass.

        Args:
            row: sqlite3.Row from experiment_runs table.

        Returns:
            Fully populated ExperimentRun.
        """
        return ExperimentRun(
            run_id=row["run_id"],
            proposal_id=row["proposal_id"],
            experiment_name=row["experiment_name"],
            status=ExperimentStatus(row["status"]),
            hypothesis=row["hypothesis"] or "",
            variants=json.loads(row["variants"]) if row["variants"] else [],
            success_metric=row["success_metric"] or "",
            success_threshold=row["success_threshold"] or 0.0,
            baseline_metrics=json.loads(row["baseline_metrics"]) if row["baseline_metrics"] else {},
            treatment_metrics=json.loads(row["treatment_metrics"]) if row["treatment_metrics"] else {},
            active_variant=row["active_variant"],
            config_backup=json.loads(row["config_backup"]) if row["config_backup"] else {},
            result=json.loads(row["result"]) if row["result"] else None,
            started_at=row["started_at"] or 0.0,
            completed_at=row["completed_at"],
            error=row["error"],
            impact_change_id=row["impact_change_id"],
        )

    # ── Metric collection ───────────────────────────────────────────

    def _get_current_metric(self, metric_name: str) -> Optional[float]:
        """Get current value of a specific metric from the system.

        Checks MetricsDB pipeline summary and system history for known
        metric names, falling back to config values for config-style paths.

        Args:
            metric_name: Dot-notation metric name (e.g. ``pipeline.avg_latency``).

        Returns:
            Current metric value, or None if unavailable.
        """
        mdb = _get_metrics_db()

        # Pipeline metrics mapping
        pipeline_keys = {
            "pipeline.avg_latency": "avg_latency",
            "pipeline.avg_tps": "avg_tps",
            "pipeline.avg_ttft": "avg_ttft",
            "pipeline.total_kills": "total_kills",
            "pipeline.total_pre_warms": "total_pre_warms",
            "pipeline.avg_tokens_in": "avg_tokens_in",
            "pipeline.avg_tokens_out": "avg_tokens_out",
            "pipeline.total": "total",
        }

        # System metrics mapping
        system_keys = {
            "system.cpu_pct": "cpu_pct",
            "system.ram_pct": "ram_pct",
            "system.gpu_vram_pct": "gpu_vram_pct",
            "system.gpu_temp_c": "gpu_temp_c",
        }

        if mdb is not None:
            # Check pipeline metrics
            if metric_name in pipeline_keys:
                try:
                    summary = mdb.get_pipeline_summary(seconds=60)
                    col = pipeline_keys[metric_name]
                    val = summary.get(col)
                    if val is not None:
                        return float(val)
                except Exception as exc:
                    logger.debug("Pipeline metric read failed: %s", exc)

            # Check system metrics
            if metric_name in system_keys:
                try:
                    history = mdb.get_system_history(seconds=30)
                    if history:
                        latest = history[-1]
                        col = system_keys[metric_name]
                        val = latest.get(col)
                        if val is not None:
                            return float(val)
                except Exception as exc:
                    logger.debug("System metric read failed: %s", exc)

            # Generic: scan recent pipeline history for arbitrary column matches
            if metric_name.startswith("pipeline."):
                try:
                    col_name = metric_name.split(".", 1)[1]
                    history = mdb.get_pipeline_history(seconds=60)
                    if history:
                        vals = [
                            float(h[col_name])
                            for h in history
                            if col_name in h and h[col_name] is not None
                        ]
                        if vals:
                            return sum(vals) / len(vals)
                except Exception as exc:
                    logger.debug("Generic pipeline metric read failed: %s", exc)

        # Fallback: try config value (for metrics like lmstudio.temperature)
        cfg = _get_config()
        if cfg is not None:
            try:
                val = cfg.get(metric_name)
                if val is not None and isinstance(val, (int, float)):
                    return float(val)
            except Exception:
                pass

        return None

    def collect_metrics(
        self,
        run_id: str,
        phase: str,
        iterations: int = 10,
    ) -> Dict[str, List[float]]:
        """Collect N iterations of metric samples from the system.

        For each iteration queries pipeline summary, system snapshot,
        and the experiment's specific success metric. Each sample is
        persisted to the ``experiment_metrics`` table.

        Args:
            run_id: Experiment run to collect for.
            phase: Either ``"baseline"`` or ``"treatment"``.
            iterations: Number of sampling rounds.

        Returns:
            Dict mapping metric names to lists of sampled values.
        """
        run = self._load_run(run_id)
        if run is None:
            logger.error("collect_metrics: run %s not found", run_id)
            return {}

        collected: Dict[str, List[float]] = {}
        mdb = _get_metrics_db()

        for i in range(iterations):
            ts = time.time()
            samples: Dict[str, float] = {}

            # Pipeline summary
            if mdb is not None:
                try:
                    summary = mdb.get_pipeline_summary(seconds=30)
                    for key in ("avg_latency", "avg_tps", "avg_ttft",
                                "avg_tokens_in", "avg_tokens_out"):
                        val = summary.get(key)
                        if val is not None:
                            metric_key = f"pipeline.{key}"
                            samples[metric_key] = float(val)
                except Exception as exc:
                    logger.debug("Pipeline sample %d failed: %s", i, exc)

                # System snapshot (latest)
                try:
                    sys_hist = mdb.get_system_history(seconds=10)
                    if sys_hist:
                        latest = sys_hist[-1]
                        for key in ("cpu_pct", "ram_pct", "gpu_vram_pct"):
                            val = latest.get(key)
                            if val is not None:
                                samples[f"system.{key}"] = float(val)
                except Exception as exc:
                    logger.debug("System sample %d failed: %s", i, exc)

            # Success metric
            success_val = self._get_current_metric(run.success_metric)
            if success_val is not None:
                samples[run.success_metric] = success_val

            # Store samples
            for metric_name, value in samples.items():
                collected.setdefault(metric_name, []).append(value)
                self._store_metric_sample(run_id, phase, i, metric_name, value, ts)

            if i < iterations - 1:
                time.sleep(self.SAMPLE_INTERVAL)

        logger.info(
            "Collected %d metrics over %d iterations for %s/%s",
            sum(len(v) for v in collected.values()),
            iterations,
            run_id,
            phase,
        )
        return collected

    def _store_metric_sample(
        self,
        run_id: str,
        phase: str,
        iteration: int,
        metric: str,
        value: float,
        timestamp: float,
    ) -> None:
        """Persist a single metric sample to the database.

        Args:
            run_id: Owning experiment run.
            phase: ``"baseline"`` or ``"treatment"``.
            iteration: Sample iteration index.
            metric: Metric name.
            value: Sampled value.
            timestamp: Unix timestamp of the sample.
        """
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO experiment_metrics "
                "(run_id, phase, iteration, metric, value, timestamp) "
                "VALUES (?,?,?,?,?,?)",
                (run_id, phase, iteration, metric, value, timestamp),
            )

    def _load_metric_samples(
        self, run_id: str, phase: str
    ) -> Dict[str, List[float]]:
        """Load all metric samples for a run/phase from the database.

        Args:
            run_id: Experiment run identifier.
            phase: ``"baseline"`` or ``"treatment"``.

        Returns:
            Dict mapping metric names to ordered lists of values.
        """
        result: Dict[str, List[float]] = {}
        with self._cursor() as cur:
            cur.execute(
                "SELECT metric, value FROM experiment_metrics "
                "WHERE run_id = ? AND phase = ? ORDER BY iteration",
                (run_id, phase),
            )
            for row in cur.fetchall():
                result.setdefault(row["metric"], []).append(float(row["value"]))
        return result

    # ── Treatment application / rollback ────────────────────────────

    def apply_treatment(
        self, run: ExperimentRun, variant: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply a treatment variant by modifying system configuration.

        Backs up current config values for every key in the variant's
        ``config`` dict, applies the new values, waits for the system to
        settle, then verifies the changes took effect.

        Args:
            run: The experiment run being executed.
            variant: Variant dict with at least ``{id, label, config}``.

        Returns:
            ``{applied: True, config_backup: {...}, variant_id: "..."}``

        Raises:
            RuntimeError: If config manager is unavailable.
        """
        cfg = _get_config()
        if cfg is None:
            raise RuntimeError("ConfigManager unavailable — cannot apply treatment")

        variant_config = variant.get("config", {})
        variant_id = variant.get("id", "unknown")
        backup: Dict[str, Any] = {}

        # Backup current values
        for key in variant_config:
            backup[key] = cfg.get(key)

        # Apply new values
        for key, value in variant_config.items():
            cfg.set(key, value)
            logger.info(
                "Treatment %s: set %s = %r (was %r)",
                variant_id, key, value, backup.get(key),
            )

        # Wait for the system to settle
        settle = cfg.get(
            "experiments.settle_seconds", self.DEFAULT_SETTLE_SECONDS
        )
        logger.info("Waiting %.1fs for system to settle after treatment", settle)
        time.sleep(settle)

        # Verify changes took effect
        verified = 0
        for key, expected in variant_config.items():
            actual = cfg.get(key)
            if actual == expected:
                verified += 1
            else:
                logger.warning(
                    "Config verify mismatch: %s expected %r got %r",
                    key, expected, actual,
                )

        logger.info(
            "Treatment %s applied: %d/%d config keys verified",
            variant_id, verified, len(variant_config),
        )

        return {
            "applied": True,
            "config_backup": backup,
            "variant_id": variant_id,
        }

    def rollback_treatment(self, run: ExperimentRun) -> bool:
        """Restore original config values from the run's config backup.

        Args:
            run: The experiment run whose treatment to undo.

        Returns:
            True if all config values were restored successfully.
        """
        cfg = _get_config()
        if cfg is None:
            logger.error("ConfigManager unavailable — cannot rollback")
            return False

        if not run.config_backup:
            logger.info("No config backup to rollback for %s", run.run_id)
            return True

        restored = 0
        for key, original_value in run.config_backup.items():
            try:
                cfg.set(key, original_value)
                restored += 1
                logger.info("Rolled back %s = %r", key, original_value)
            except Exception as exc:
                logger.error("Failed to rollback %s: %s", key, exc)

        success = restored == len(run.config_backup)
        logger.info(
            "Rollback for %s: %d/%d restored (success=%s)",
            run.run_id, restored, len(run.config_backup), success,
        )
        return success

    # ── Statistical analysis ────────────────────────────────────────

    def _paired_t_test(
        self, baseline: List[float], treatment: List[float]
    ) -> Tuple[float, float]:
        """Manual paired t-test implementation (scipy fallback).

        Computes the t-statistic and approximate two-tailed p-value for
        paired observations.  When n >= 30 the normal approximation via
        ``math.erfc`` is used; for smaller samples the result is a rough
        estimate using the same approximation.

        Args:
            baseline: Baseline observation values.
            treatment: Treatment observation values.

        Returns:
            Tuple of (t_statistic, p_value).

        Raises:
            ValueError: If the two lists have different lengths or fewer
                than 2 observations.
        """
        n = len(baseline)
        if n != len(treatment):
            raise ValueError("Baseline and treatment must have equal length")
        if n < 2:
            raise ValueError("Need at least 2 paired observations")

        differences = [t - b for t, b in zip(treatment, baseline)]
        d_mean = sum(differences) / n
        d_var = sum((d - d_mean) ** 2 for d in differences) / (n - 1)
        d_std = math.sqrt(d_var) if d_var > 0 else 0.0

        if d_std == 0.0:
            return (0.0, 1.0)

        t_stat = d_mean / (d_std / math.sqrt(n))

        # Two-tailed p-value approximation via complementary error function
        # For the t-distribution with df = n-1, approximate using the normal
        # distribution — adequate for n >= 10 and conservative for smaller n.
        p_value = math.erfc(abs(t_stat) / math.sqrt(2))
        return (t_stat, p_value)

    def _cohens_d(
        self, baseline: List[float], treatment: List[float]
    ) -> float:
        """Compute Cohen's d effect size for paired samples.

        Uses the pooled standard deviation as the denominator.

        Args:
            baseline: Baseline observation values.
            treatment: Treatment observation values.

        Returns:
            Cohen's d (positive means treatment > baseline).
        """
        n_b = len(baseline)
        n_t = len(treatment)
        if n_b < 2 or n_t < 2:
            return 0.0

        mean_b = sum(baseline) / n_b
        mean_t = sum(treatment) / n_t

        var_b = sum((x - mean_b) ** 2 for x in baseline) / (n_b - 1)
        var_t = sum((x - mean_t) ** 2 for x in treatment) / (n_t - 1)

        pooled_std = math.sqrt(((n_b - 1) * var_b + (n_t - 1) * var_t) / (n_b + n_t - 2))
        if pooled_std == 0.0:
            return 0.0

        return (mean_t - mean_b) / pooled_std

    def analyze_results(self, run: ExperimentRun) -> Dict[str, Any]:
        """Perform statistical analysis of baseline vs treatment metrics.

        For each metric present in both phases the method computes means,
        standard deviations, a paired t-test (scipy preferred, manual
        fallback), and Cohen's d effect size.

        Args:
            run: The experiment run with collected metrics.

        Returns:
            Dict containing per-metric analysis, overall significance,
            a recommendation (``"promote"`` / ``"rollback"`` /
            ``"inconclusive"``), and a human-readable summary.
        """
        baseline_data = self._load_metric_samples(run.run_id, "baseline")
        treatment_data = self._load_metric_samples(run.run_id, "treatment")

        if not baseline_data and not treatment_data:
            # Fall back to in-memory dicts stored on the run
            baseline_data = {k: [v] for k, v in run.baseline_metrics.items()} if run.baseline_metrics else {}
            treatment_data = {k: [v] for k, v in run.treatment_metrics.items()} if run.treatment_metrics else {}

        metrics_analysis: Dict[str, Dict[str, Any]] = {}
        any_significant = False
        success_metric_result: Optional[Dict[str, Any]] = None

        # Analyse each metric that has data in both phases
        common_metrics = set(baseline_data.keys()) & set(treatment_data.keys())
        for metric_name in sorted(common_metrics):
            b_vals = baseline_data[metric_name]
            t_vals = treatment_data[metric_name]

            # Align to shortest length
            min_len = min(len(b_vals), len(t_vals))
            if min_len < 2:
                continue
            b_vals = b_vals[:min_len]
            t_vals = t_vals[:min_len]

            mean_b = sum(b_vals) / len(b_vals)
            mean_t = sum(t_vals) / len(t_vals)

            # Try scipy first, then manual fallback
            scipy_result = _try_scipy_ttest(b_vals, t_vals)
            if scipy_result is not None:
                t_stat, p_value = scipy_result
            else:
                t_stat, p_value = self._paired_t_test(b_vals, t_vals)

            effect_size = self._cohens_d(b_vals, t_vals)
            significant = p_value < self.SIGNIFICANCE_LEVEL

            if mean_b != 0:
                pct_change = ((mean_t - mean_b) / abs(mean_b)) * 100
            else:
                pct_change = 0.0 if mean_t == 0 else 100.0

            if pct_change > 1.0:
                direction = "improved"
            elif pct_change < -1.0:
                direction = "degraded"
            else:
                direction = "unchanged"

            entry = {
                "baseline_mean": round(mean_b, 6),
                "treatment_mean": round(mean_t, 6),
                "baseline_std": round(
                    math.sqrt(sum((x - mean_b) ** 2 for x in b_vals) / max(len(b_vals) - 1, 1)), 6
                ),
                "treatment_std": round(
                    math.sqrt(sum((x - mean_t) ** 2 for x in t_vals) / max(len(t_vals) - 1, 1)), 6
                ),
                "t_statistic": round(t_stat, 4),
                "p_value": round(p_value, 6),
                "effect_size": round(effect_size, 4),
                "significant": significant,
                "direction": direction,
                "pct_change": round(pct_change, 2),
                "n_samples": min_len,
            }
            metrics_analysis[metric_name] = entry

            if significant and direction == "improved":
                any_significant = True

            if metric_name == run.success_metric:
                success_metric_result = entry

        # Determine recommendation
        if success_metric_result is not None:
            sm = success_metric_result
            if sm["significant"] and sm["direction"] == "improved":
                if sm["effect_size"] >= run.success_threshold:
                    recommendation = "promote"
                else:
                    recommendation = "inconclusive"
            elif sm["direction"] == "degraded":
                recommendation = "rollback"
            else:
                recommendation = "inconclusive"
        elif any_significant:
            recommendation = "promote"
        else:
            recommendation = "inconclusive"

        # Build summary string
        n_improved = sum(
            1 for m in metrics_analysis.values()
            if m["significant"] and m["direction"] == "improved"
        )
        n_degraded = sum(
            1 for m in metrics_analysis.values()
            if m["significant"] and m["direction"] == "degraded"
        )
        summary = (
            f"Analysed {len(metrics_analysis)} metrics: "
            f"{n_improved} significantly improved, "
            f"{n_degraded} significantly degraded. "
            f"Recommendation: {recommendation}."
        )
        if success_metric_result:
            summary += (
                f" Success metric ({run.success_metric}): "
                f"p={success_metric_result['p_value']:.4f}, "
                f"d={success_metric_result['effect_size']:.3f}, "
                f"{success_metric_result['direction']}."
            )

        return {
            "significant": any_significant,
            "metrics": metrics_analysis,
            "recommendation": recommendation,
            "summary": summary,
        }

    # ── Core execution ──────────────────────────────────────────────

    def execute_experiment(self, proposal_id: str) -> Dict[str, Any]:
        """Execute a single experiment proposal through full lifecycle.

        Steps:
            1. Fetch proposal from ExperimentProposer
            2. Create ExperimentRun record
            3. Record change in ImpactTracker
            4. Collect baseline metrics
            5. Apply treatment variant
            6. Collect treatment metrics
            7. Run statistical test
            8. Promote or rollback based on results
            9. Finalize impact and store in Nexus

        Args:
            proposal_id: ID of the proposal to execute.

        Returns:
            Dict with ``run_id``, ``status``, ``result``, and ``impact``.
        """
        proposer = _get_proposer()
        if proposer is None:
            return {"error": "ExperimentProposer unavailable", "status": "failed"}

        # Find the proposal
        proposals = proposer.get_proposals(status="pending")
        target = None
        for p in proposals:
            if p.get("proposal_id") == proposal_id:
                target = p
                break
        if target is None:
            proposals_all = proposer.get_proposals()
            for p in proposals_all:
                if p.get("proposal_id") == proposal_id:
                    target = p
                    break
        if target is None:
            return {"error": f"Proposal {proposal_id} not found", "status": "failed"}

        # Build a lightweight ExperimentProposal-like dict for execution
        return self._execute_proposal_dict(target)

    def execute_from_proposal(self, proposal: Any) -> Dict[str, Any]:
        """Execute directly from an ExperimentProposal object.

        This is an alternative entry point that skips the proposal lookup.

        Args:
            proposal: An ``ExperimentProposal`` dataclass instance.

        Returns:
            Dict with ``run_id``, ``status``, ``result``, and ``impact``.
        """
        try:
            from dataclasses import asdict as _asdict
            proposal_dict = _asdict(proposal)
        except Exception:
            proposal_dict = {
                "proposal_id": getattr(proposal, "proposal_id", str(uuid.uuid4())[:8]),
                "experiment_name": getattr(proposal, "experiment_name", "unnamed"),
                "hypothesis": getattr(proposal, "hypothesis", ""),
                "variants": getattr(proposal, "variants", []),
                "success_metric": getattr(proposal, "success_metric", ""),
                "success_threshold": getattr(proposal, "success_threshold", 0.0),
                "trigger_metric": getattr(proposal, "trigger_metric", ""),
                "trigger_value": getattr(proposal, "trigger_value", 0.0),
                "priority": getattr(proposal, "priority", "medium"),
            }
        return self._execute_proposal_dict(proposal_dict)

    def _execute_proposal_dict(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """Internal: execute from a proposal dictionary.

        Args:
            proposal: Dict with proposal fields.

        Returns:
            Dict with ``run_id``, ``status``, ``result``, and ``impact``.
        """
        run_id = f"exp-{uuid.uuid4().hex[:8]}"
        proposal_id = proposal.get("proposal_id", "unknown")
        variants = proposal.get("variants", [])

        run = ExperimentRun(
            run_id=run_id,
            proposal_id=proposal_id,
            experiment_name=proposal.get("experiment_name", "unnamed"),
            status=ExperimentStatus.PENDING,
            hypothesis=proposal.get("hypothesis", ""),
            variants=variants,
            success_metric=proposal.get("success_metric", ""),
            success_threshold=proposal.get("success_threshold", 0.0),
            baseline_metrics={},
            treatment_metrics={},
            active_variant=None,
            config_backup={},
            result=None,
            started_at=time.time(),
        )
        self._save_run(run)

        logger.info(
            "Starting experiment %s (proposal=%s, name=%s)",
            run_id, proposal_id, run.experiment_name,
        )

        # Record change in ImpactTracker
        impact_id: Optional[str] = None
        tracker = _get_impact_tracker()
        if tracker is not None:
            try:
                from engine.nexus.impact_tracker import ChangeType
                impact_id = tracker.record_change(
                    change_type=ChangeType.EXPERIMENT_RESULT,
                    title=f"Experiment: {run.experiment_name}",
                    description=run.hypothesis,
                    source="experiment_executor",
                    metadata={
                        "run_id": run_id,
                        "proposal_id": proposal_id,
                        "variants": len(variants),
                    },
                )
                run.impact_change_id = impact_id
            except Exception as exc:
                logger.warning("ImpactTracker record_change failed: %s", exc)

        treatment_applied = False
        try:
            # Phase 1: Baseline collection
            run.status = ExperimentStatus.BASELINE
            self._save_run(run)
            logger.info("[%s] Collecting baseline metrics", run_id)

            cfg = _get_config()
            iterations = self.DEFAULT_ITERATIONS
            if cfg is not None:
                iterations = int(
                    cfg.get("experiments.iterations", self.DEFAULT_ITERATIONS)
                )

            baseline = self.collect_metrics(run_id, "baseline", iterations)
            run.baseline_metrics = {k: sum(v) / len(v) for k, v in baseline.items() if v}
            self._save_run(run)

            # Phase 2: Apply treatment
            if not variants:
                raise RuntimeError("No variants defined in proposal")

            variant = variants[0]  # Use first variant
            run.status = ExperimentStatus.RUNNING
            run.active_variant = variant.get("id", variant.get("label", "v0"))
            self._save_run(run)

            logger.info("[%s] Applying treatment variant: %s", run_id, run.active_variant)
            treatment_result = self.apply_treatment(run, variant)
            run.config_backup = treatment_result.get("config_backup", {})
            treatment_applied = True
            self._save_run(run)

            # Phase 3: Treatment metric collection
            run.status = ExperimentStatus.COLLECTING
            self._save_run(run)
            logger.info("[%s] Collecting treatment metrics", run_id)

            treatment = self.collect_metrics(run_id, "treatment", iterations)
            run.treatment_metrics = {k: sum(v) / len(v) for k, v in treatment.items() if v}
            self._save_run(run)

            # Phase 4: Statistical analysis
            run.status = ExperimentStatus.ANALYZING
            self._save_run(run)
            logger.info("[%s] Analysing results", run_id)

            analysis = self.analyze_results(run)
            run.result = analysis

            recommendation = analysis.get("recommendation", "inconclusive")

            if recommendation == "promote":
                run.status = ExperimentStatus.COMPLETED
                logger.info(
                    "[%s] Treatment PROMOTED — %s", run_id, analysis.get("summary", "")
                )
            elif recommendation == "rollback":
                logger.info("[%s] Treatment ROLLED BACK — %s", run_id, analysis.get("summary", ""))
                self.rollback_treatment(run)
                treatment_applied = False
                run.status = ExperimentStatus.ROLLED_BACK
            else:
                logger.info("[%s] INCONCLUSIVE — rolling back to be safe", run_id)
                self.rollback_treatment(run)
                treatment_applied = False
                run.status = ExperimentStatus.ROLLED_BACK

            run.completed_at = time.time()
            self._save_run(run)

        except Exception as exc:
            logger.error("[%s] Experiment failed: %s", run_id, exc, exc_info=True)
            run.status = ExperimentStatus.FAILED
            run.error = str(exc)
            run.completed_at = time.time()

            if treatment_applied:
                logger.info("[%s] Rolling back treatment after failure", run_id)
                try:
                    self.rollback_treatment(run)
                except Exception as rb_exc:
                    logger.error("[%s] Rollback also failed: %s", run_id, rb_exc)

            self._save_run(run)

        # Post-execution: finalize impact + store in Nexus
        impact_result: Optional[Dict[str, Any]] = None
        if tracker is not None and impact_id is not None:
            try:
                impact_result = tracker.finalize_change(impact_id)
            except Exception as exc:
                logger.warning("ImpactTracker finalize failed: %s", exc)

        self._store_nexus_result(run)

        return {
            "run_id": run.run_id,
            "status": run.status.value,
            "result": run.result,
            "impact": impact_result,
            "error": run.error,
        }

    # ── Batch execution ─────────────────────────────────────────────

    def run_pending(self) -> List[Dict[str, Any]]:
        """Scan for pending proposals and execute in priority order.

        Fetches proposals with ``status="pending"`` from the proposer,
        sorts by priority (high → medium → low), then executes each
        one sequentially.

        Returns:
            List of result dicts from each execution.
        """
        proposer = _get_proposer()
        if proposer is None:
            logger.warning("run_pending: ExperimentProposer unavailable")
            return []

        pending = proposer.get_proposals(status="pending")
        if not pending:
            logger.info("run_pending: no pending proposals")
            return []

        # Sort by priority
        pending.sort(
            key=lambda p: _PRIORITY_ORDER.get(p.get("priority", "low"), 2)
        )

        logger.info("run_pending: executing %d pending proposals", len(pending))
        results: List[Dict[str, Any]] = []

        for proposal in pending:
            pid = proposal.get("proposal_id", "unknown")
            logger.info("run_pending: executing proposal %s", pid)
            try:
                result = self._execute_proposal_dict(proposal)
                results.append(result)
            except Exception as exc:
                logger.error("run_pending: proposal %s failed: %s", pid, exc)
                results.append({
                    "run_id": None,
                    "status": "failed",
                    "error": str(exc),
                    "proposal_id": pid,
                })

        logger.info(
            "run_pending: completed %d experiments (%d succeeded)",
            len(results),
            sum(1 for r in results if r.get("status") in ("completed", "rolled_back")),
        )
        return results

    # ── Query methods ───────────────────────────────────────────────

    def get_run(self, run_id: str) -> Optional[ExperimentRun]:
        """Retrieve an experiment run by its ID.

        Args:
            run_id: Unique run identifier.

        Returns:
            ExperimentRun if found, else None.
        """
        return self._load_run(run_id)

    def list_runs(
        self,
        status: Optional[ExperimentStatus] = None,
        days: int = 30,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List experiment runs with optional filters.

        Args:
            status: Filter by experiment status.
            days: Only include runs from the last N days.
            limit: Maximum number of results.

        Returns:
            List of run dicts ordered by ``started_at`` descending.
        """
        cutoff = time.time() - (days * 86400)
        clauses = ["started_at > ?"]
        params: list = [cutoff]

        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)

        where = " AND ".join(clauses)
        params.append(limit)

        with self._cursor() as cur:
            cur.execute(
                f"SELECT * FROM experiment_runs WHERE {where} "
                "ORDER BY started_at DESC LIMIT ?",
                params,
            )
            rows = cur.fetchall()

        results: List[Dict[str, Any]] = []
        for row in rows:
            run = self._row_to_run(row)
            results.append({
                "run_id": run.run_id,
                "proposal_id": run.proposal_id,
                "experiment_name": run.experiment_name,
                "status": run.status.value,
                "active_variant": run.active_variant,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "error": run.error,
                "result_summary": (
                    run.result.get("summary", "") if run.result else None
                ),
            })
        return results

    def run_stats(self) -> Dict[str, Any]:
        """Compute summary statistics across all experiment runs.

        Returns:
            Dict with total count, counts by status, success rate,
            and average effect size.
        """
        with self._cursor() as cur:
            cur.execute("SELECT status, COUNT(*) as cnt FROM experiment_runs GROUP BY status")
            status_counts = {row["status"]: row["cnt"] for row in cur.fetchall()}

            cur.execute("SELECT COUNT(*) as total FROM experiment_runs")
            total = cur.fetchone()["total"]

            cur.execute("SELECT result FROM experiment_runs WHERE status = 'completed'")
            effect_sizes: List[float] = []
            for row in cur.fetchall():
                if row["result"]:
                    try:
                        res = json.loads(row["result"])
                        for m in res.get("metrics", {}).values():
                            es = m.get("effect_size")
                            if es is not None:
                                effect_sizes.append(abs(float(es)))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass

        completed = status_counts.get("completed", 0)
        rolled_back = status_counts.get("rolled_back", 0)
        failed = status_counts.get("failed", 0)
        attempted = completed + rolled_back + failed

        return {
            "total_runs": total,
            "by_status": status_counts,
            "success_rate": round(completed / attempted, 4) if attempted > 0 else 0.0,
            "attempted": attempted,
            "avg_effect_size": (
                round(sum(effect_sizes) / len(effect_sizes), 4)
                if effect_sizes else 0.0
            ),
            "max_effect_size": round(max(effect_sizes), 4) if effect_sizes else 0.0,
        }

    # ── Nexus storage ───────────────────────────────────────────────

    def _store_nexus_result(self, run: ExperimentRun) -> None:
        """Store a completed experiment summary in Nexus.

        Creates both a knowledge entry (note) and a Q&A pair so that
        future agents can find experiment outcomes.

        Args:
            run: The completed experiment run.
        """
        client = _get_nexus_client()
        if client is None:
            logger.debug("NexusClient unavailable — skipping result storage")
            return

        status_str = run.status.value
        summary = ""
        if run.result:
            summary = run.result.get("summary", "")

        content = (
            f"Experiment: {run.experiment_name}\n"
            f"Run ID: {run.run_id}\n"
            f"Proposal: {run.proposal_id}\n"
            f"Status: {status_str}\n"
            f"Hypothesis: {run.hypothesis}\n"
            f"Variant: {run.active_variant}\n"
            f"Success Metric: {run.success_metric}\n"
            f"Threshold: {run.success_threshold}\n"
        )

        if run.baseline_metrics:
            content += "\nBaseline Metrics:\n"
            for k, v in sorted(run.baseline_metrics.items()):
                content += f"  {k}: {v:.4f}\n"

        if run.treatment_metrics:
            content += "\nTreatment Metrics:\n"
            for k, v in sorted(run.treatment_metrics.items()):
                content += f"  {k}: {v:.4f}\n"

        if summary:
            content += f"\nAnalysis: {summary}\n"

        if run.error:
            content += f"\nError: {run.error}\n"

        duration = ""
        if run.completed_at and run.started_at:
            elapsed = run.completed_at - run.started_at
            duration = f" ({elapsed:.1f}s)"

        try:
            client.add_entry(
                title=f"Experiment Result: {run.experiment_name} [{status_str}]{duration}",
                content=content,
                content_type="note",
                category="experiments",
                tags=["experiment", status_str, run.experiment_name],
            )
        except Exception as exc:
            logger.warning("Nexus add_entry failed: %s", exc)

        # Store a Q&A pair for discoverability
        question = f"What was the result of the '{run.experiment_name}' experiment?"
        if summary:
            answer = summary
        else:
            answer = f"Experiment {run.run_id} finished with status '{status_str}'."
            if run.error:
                answer += f" Error: {run.error}"

        try:
            client.add_qa(
                question=question,
                answer=answer,
                category="experiments",
                tags=["experiment", run.experiment_name],
            )
        except Exception as exc:
            logger.debug("Nexus add_qa failed: %s", exc)


# ── Scheduler integration ───────────────────────────────────────────────


def _experiment_run_callback() -> Dict[str, Any]:
    """Callback for scheduler: run all pending experiments.

    Returns:
        Dict with count of executed experiments and per-run status.
    """
    executor = get_experiment_executor()
    results = executor.run_pending()
    return {
        "executed": len(results),
        "results": [
            {"run_id": r.get("run_id"), "status": r.get("status")}
            for r in results
        ],
    }


def register_experiment_tasks(daemon: Any) -> None:
    """Register experiment execution scheduler tasks.

    Called by ``scheduler_daemon._register_builtin_tasks`` to wire the
    daily experiment runner into the task scheduler.

    Args:
        daemon: A ``TaskSchedulerDaemon`` instance.
    """
    daemon.register(
        task_id="experiment-run",
        name="Experiment Runner (Daily)",
        schedule="daily",
        callback=_experiment_run_callback,
        enabled=True,
    )
    logger.info("Registered experiment-run task with scheduler")


# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional[ExperimentExecutor] = None
_lock = threading.Lock()


def get_experiment_executor(
    db_path: Optional[Path] = None,
) -> ExperimentExecutor:
    """Get or create the singleton ExperimentExecutor instance.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        The global ExperimentExecutor instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ExperimentExecutor(db_path)
    return _instance
