"""Model evaluation gate — prevents degraded model promotion.

Runs benchmark evaluation before and after training to ensure quality
hasn't regressed. Integrates with ModelRegistry, LMSTaskBridge,
ImpactTracker, and Nexus for a complete evaluation-and-record pipeline.

Gate policies:
    NO_REGRESSION   — new model must score >= threshold * baseline
    MUST_IMPROVE    — a specific metric must increase
    PARETO_DOMINANT — new model must not be dominated on any metric
    CUSTOM          — caller-supplied evaluation function
"""
from __future__ import annotations

import contextlib
import enum
import json
import logging
import sqlite3
import statistics
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/evaluation_gate.db")


# ──── Gate Policy ────────────────────────────────────────────────────

class GatePolicy(enum.Enum):
    """Policy applied when comparing baseline vs candidate model."""

    NO_REGRESSION = "no_regression"
    MUST_IMPROVE = "must_improve"
    PARETO_DOMINANT = "pareto_dominant"
    CUSTOM = "custom"


# ──── Default Benchmark Prompts ──────────────────────────────────────

DEFAULT_BENCHMARK_PROMPTS: Dict[str, List[str]] = {
    "router": [
        "Route this to the right agent: 'Tell me a joke about programming'",
        "Route this to the right agent: 'What's the weather forecast?'",
        "Route this to the right agent: 'Generate a unit test for this function'",
        "Route this to the right agent: 'Summarize the last meeting notes'",
        "Route this to the right agent: 'Check this code for security issues'",
    ],
    "tag_extraction": [
        "Extract tags from: 'The new React 19 release includes server components and improved performance'",
        "Extract tags from: 'Fixed a critical SQL injection vulnerability in the auth module'",
        "Extract tags from: 'Updated documentation for the API endpoints and added OpenAPI spec'",
        "Extract tags from: 'Deployed new model version to production with 15% latency improvement'",
        "Extract tags from: 'Added unit tests for the payment processing module'",
    ],
    "response_validate": [
        "Validate this response for helpfulness and accuracy: 'Python uses indentation to define code blocks.'",
        "Validate this response for helpfulness and accuracy: 'The speed of light is approximately 300,000 km/s.'",
        "Validate this response for helpfulness and accuracy: 'Machine learning requires labeled data in all cases.'",
        "Validate this response for helpfulness and accuracy: 'Git is a distributed version control system.'",
        "Validate this response for helpfulness and accuracy: 'SQL injection can be prevented by using parameterized queries.'",
    ],
    "general": [
        "Explain the difference between a stack and a queue in one paragraph.",
        "What are the SOLID principles in software engineering? List them briefly.",
        "Given a list of numbers [3, 1, 4, 1, 5, 9], describe how merge sort would sort them.",
        "What is the time complexity of binary search and why?",
        "Describe what a race condition is and give one example.",
    ],
}


# ──── Dataclasses ────────────────────────────────────────────────────

@dataclass
class BenchmarkSpec:
    """Specification for a benchmark evaluation run."""

    model_type: str
    test_prompts: List[str]
    metrics: List[str] = field(
        default_factory=lambda: ["accuracy", "latency", "consistency"]
    )
    num_runs: int = 3
    temperature: float = 0.3
    max_tokens: int = 512
    timeout_s: float = 60.0
    reference_answers: Optional[List[str]] = None


@dataclass
class BenchmarkResult:
    """Result from a single benchmark evaluation run."""

    model_id: str
    model_type: str
    timestamp: float
    scores: Dict[str, float]
    raw_results: List[Dict[str, Any]]
    latency_stats: Dict[str, float]
    consistency_score: float
    total_tokens: int
    total_time_s: float
    error_rate: float

    # ── Metric weights for the aggregate score ──
    _WEIGHTS: Dict[str, float] = field(
        default=None,  # type: ignore[assignment]
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "_WEIGHTS", {
            "accuracy": 0.40,
            "latency": 0.20,
            "consistency": 0.25,
            "error_rate": 0.15,
        })

    @property
    def overall_score(self) -> float:
        """Weighted aggregate score in 0.0–1.0 range."""
        total_weight = 0.0
        weighted_sum = 0.0
        for metric, weight in self._WEIGHTS.items():
            if metric == "error_rate":
                value = 1.0 - self.error_rate
            elif metric == "latency":
                # Normalise: lower latency is better, cap at 10 s.
                mean_lat = self.latency_stats.get("mean", 5.0)
                value = max(0.0, 1.0 - (mean_lat / 10.0))
            elif metric == "consistency":
                value = self.consistency_score
            elif metric in self.scores:
                value = self.scores[metric]
            else:
                continue
            weighted_sum += weight * value
            total_weight += weight
        if total_weight == 0.0:
            return 0.0
        return round(weighted_sum / total_weight, 4)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (omits private fields)."""
        return {
            "model_id": self.model_id,
            "model_type": self.model_type,
            "timestamp": self.timestamp,
            "scores": self.scores,
            "raw_results": self.raw_results,
            "latency_stats": self.latency_stats,
            "consistency_score": round(self.consistency_score, 4),
            "total_tokens": self.total_tokens,
            "total_time_s": round(self.total_time_s, 3),
            "error_rate": round(self.error_rate, 4),
            "overall_score": self.overall_score,
        }


@dataclass
class GateResult:
    """Outcome of an evaluation gate check."""

    passed: bool
    policy: str
    model_id: str
    model_type: str
    scores_before: Dict[str, float]
    scores_after: Dict[str, float]
    delta: Dict[str, float]
    delta_pct: Dict[str, float]
    recommendation: str
    reason: str
    timestamp: float
    benchmark_before: Optional[BenchmarkResult] = None
    benchmark_after: Optional[BenchmarkResult] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "passed": self.passed,
            "policy": self.policy,
            "model_id": self.model_id,
            "model_type": self.model_type,
            "scores_before": self.scores_before,
            "scores_after": self.scores_after,
            "delta": {k: round(v, 4) for k, v in self.delta.items()},
            "delta_pct": {k: round(v, 2) for k, v in self.delta_pct.items()},
            "recommendation": self.recommendation,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "benchmark_before": (
                self.benchmark_before.to_dict() if self.benchmark_before else None
            ),
            "benchmark_after": (
                self.benchmark_after.to_dict() if self.benchmark_after else None
            ),
        }


# ──── Evaluation Gate ────────────────────────────────────────────────

class EvaluationGate:
    """Evaluation gate that runs before model promotion.

    Benchmarks a candidate model against the currently active baseline
    and applies a gate policy to decide whether the candidate should
    be promoted, rejected, or flagged for manual review.

    All results are persisted in a local SQLite database and optionally
    forwarded to Nexus and the ImpactTracker.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()
        logger.info("EvaluationGate initialised (db=%s)", self._db_path)

    # ── SQLite helpers ───────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection."""
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=15)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    @contextlib.contextmanager
    def _cursor(self):
        """Yield a cursor with auto-commit / rollback."""
        conn = self._conn()
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
        CREATE TABLE IF NOT EXISTS gate_results (
            id            TEXT PRIMARY KEY,
            model_id      TEXT NOT NULL,
            model_type    TEXT NOT NULL,
            policy        TEXT NOT NULL,
            passed        INTEGER NOT NULL,
            scores_before TEXT,
            scores_after  TEXT,
            delta         TEXT,
            recommendation TEXT,
            reason        TEXT,
            timestamp     REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_gate_ts ON gate_results(timestamp);
        CREATE INDEX IF NOT EXISTS idx_gate_type ON gate_results(model_type);

        CREATE TABLE IF NOT EXISTS benchmark_history (
            id              TEXT PRIMARY KEY,
            model_id        TEXT NOT NULL,
            model_type      TEXT NOT NULL,
            scores          TEXT,
            latency_stats   TEXT,
            consistency     REAL,
            error_rate      REAL,
            overall_score   REAL,
            total_tokens    INTEGER,
            total_time_s    REAL,
            timestamp       REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bench_ts ON benchmark_history(timestamp);
        CREATE INDEX IF NOT EXISTS idx_bench_type ON benchmark_history(model_type);
        CREATE INDEX IF NOT EXISTS idx_bench_model ON benchmark_history(model_id);
        """
        with self._cursor() as cur:
            cur.executescript(ddl)

    # ── Public API ───────────────────────────────────────────────────

    def run_gate(
        self,
        model_id: str,
        model_type: str,
        policy: GatePolicy = GatePolicy.NO_REGRESSION,
        benchmark_spec: Optional[BenchmarkSpec] = None,
        threshold: float = 0.95,
        required_metric: Optional[str] = None,
        custom_fn: Optional[Callable[[BenchmarkResult, BenchmarkResult], Tuple[bool, str, str]]] = None,
    ) -> GateResult:
        """Run the evaluation gate for a candidate model.

        Steps:
            1. Retrieve or compute baseline benchmark for active model.
            2. Run benchmark on the candidate model.
            3. Compare results according to *policy*.
            4. Persist the gate result.
            5. Log to Nexus and ImpactTracker.

        Args:
            model_id: Identifier of the candidate model.
            model_type: Model category (``router``, ``tag_extraction``, …).
            policy: Comparison policy to apply.
            benchmark_spec: Optional custom benchmark specification.
            threshold: Minimum fraction of baseline score (NO_REGRESSION).
            required_metric: Metric that must improve (MUST_IMPROVE).
            custom_fn: Evaluation function (CUSTOM).  Receives
                ``(baseline, candidate)`` and returns
                ``(passed, recommendation, reason)``.

        Returns:
            A :class:`GateResult` summarising the outcome.
        """
        logger.info(
            "Running evaluation gate for %s (type=%s, policy=%s)",
            model_id, model_type, policy.value,
        )

        # 1. Baseline
        baseline = self.get_baseline(model_type)
        if baseline is None:
            logger.warning(
                "No baseline benchmark for model_type=%s — running first benchmark as baseline",
                model_type,
            )
            baseline = self._make_empty_baseline(model_type)

        # 2. Candidate benchmark
        candidate = self.run_benchmark(model_id, model_type, spec=benchmark_spec)

        # 3. Compare
        if policy == GatePolicy.NO_REGRESSION:
            passed, recommendation, reason = self._evaluate_no_regression(
                baseline, candidate, threshold,
            )
        elif policy == GatePolicy.MUST_IMPROVE:
            metric = required_metric or "accuracy"
            passed, recommendation, reason = self._evaluate_must_improve(
                baseline, candidate, metric,
            )
        elif policy == GatePolicy.PARETO_DOMINANT:
            passed, recommendation, reason = self._evaluate_pareto(
                baseline, candidate,
            )
        elif policy == GatePolicy.CUSTOM:
            if custom_fn is None:
                raise ValueError("CUSTOM policy requires a custom_fn argument")
            passed, recommendation, reason = custom_fn(baseline, candidate)
        else:
            raise ValueError(f"Unknown policy: {policy}")

        # Build deltas
        all_metrics = set(baseline.scores) | set(candidate.scores)
        delta: Dict[str, float] = {}
        delta_pct: Dict[str, float] = {}
        for m in sorted(all_metrics):
            old = baseline.scores.get(m, 0.0)
            new = candidate.scores.get(m, 0.0)
            delta[m] = round(new - old, 6)
            delta_pct[m] = round(((new - old) / old) * 100, 2) if old else 0.0

        # Also add overall_score delta
        delta["overall_score"] = round(candidate.overall_score - baseline.overall_score, 6)
        old_overall = baseline.overall_score
        delta_pct["overall_score"] = (
            round(((candidate.overall_score - old_overall) / old_overall) * 100, 2)
            if old_overall else 0.0
        )

        gate_result = GateResult(
            passed=passed,
            policy=policy.value,
            model_id=model_id,
            model_type=model_type,
            scores_before=baseline.scores,
            scores_after=candidate.scores,
            delta=delta,
            delta_pct=delta_pct,
            recommendation=recommendation,
            reason=reason,
            timestamp=time.time(),
            benchmark_before=baseline,
            benchmark_after=candidate,
        )

        # 4. Persist
        self._store_gate_result(gate_result)

        # 5. Side-effects (best-effort)
        self._log_to_nexus(gate_result)
        self._record_impact(gate_result)

        # 6. Update model registry benchmark score
        self._update_registry_score(model_id, candidate)

        logger.info(
            "Gate result for %s: passed=%s recommendation=%s reason=%s",
            model_id, passed, recommendation, reason,
        )
        return gate_result

    def run_benchmark(
        self,
        model_id: str,
        model_type: str,
        spec: Optional[BenchmarkSpec] = None,
    ) -> BenchmarkResult:
        """Run a benchmark suite on a model.

        Uses :class:`LMSTaskBridge` to send prompts to the model.
        Measures latency, consistency (SequenceMatcher similarity across
        repeated runs), and error rate.  If ``reference_answers`` are
        provided in the spec, accuracy is measured via LLM-as-judge.

        Args:
            model_id: Model identifier.
            model_type: Model category.
            spec: Benchmark specification (defaults built from model_type).

        Returns:
            A :class:`BenchmarkResult` with all collected metrics.
        """
        if spec is None:
            prompts = self.get_default_prompts(model_type)
            spec = BenchmarkSpec(model_type=model_type, test_prompts=prompts)

        from engine.nexus.lms_task_bridge import LMSTaskBridge
        try:
            bridge = LMSTaskBridge()
        except Exception as exc:
            logger.error("Failed to initialise LMSTaskBridge: %s", exc)
            return self._failed_benchmark(model_id, model_type, str(exc))

        raw_results: List[Dict[str, Any]] = []
        latencies: List[float] = []
        total_tokens = 0
        errors = 0
        all_outputs_per_prompt: List[List[str]] = []
        t_start = time.monotonic()

        for prompt_idx, prompt in enumerate(spec.test_prompts):
            run_outputs: List[str] = []
            for run_idx in range(spec.num_runs):
                t0 = time.monotonic()
                try:
                    result = bridge.run_prompt(
                        prompt,
                        temperature=spec.temperature,
                        max_tokens=spec.max_tokens,
                    )
                    elapsed = time.monotonic() - t0

                    if elapsed > spec.timeout_s:
                        logger.warning(
                            "Prompt %d run %d exceeded timeout (%.1fs > %.1fs)",
                            prompt_idx, run_idx, elapsed, spec.timeout_s,
                        )

                    if result.ok:
                        output_text = result.output or ""
                        latencies.append(result.latency_ms / 1000.0)
                        total_tokens += result.tokens_generated
                        run_outputs.append(output_text)
                        raw_results.append({
                            "prompt_idx": prompt_idx,
                            "run_idx": run_idx,
                            "output": output_text[:500],
                            "latency_s": round(result.latency_ms / 1000.0, 4),
                            "tokens": result.tokens_generated,
                            "status": "ok",
                        })
                    else:
                        errors += 1
                        run_outputs.append("")
                        raw_results.append({
                            "prompt_idx": prompt_idx,
                            "run_idx": run_idx,
                            "output": "",
                            "error": result.error[:200] if result.error else "unknown",
                            "latency_s": round(elapsed, 4),
                            "tokens": 0,
                            "status": "error",
                        })
                except Exception as exc:
                    errors += 1
                    elapsed = time.monotonic() - t0
                    run_outputs.append("")
                    raw_results.append({
                        "prompt_idx": prompt_idx,
                        "run_idx": run_idx,
                        "output": "",
                        "error": str(exc)[:200],
                        "latency_s": round(elapsed, 4),
                        "tokens": 0,
                        "status": "exception",
                    })
                    logger.warning(
                        "Benchmark prompt %d run %d failed: %s",
                        prompt_idx, run_idx, exc,
                    )

            all_outputs_per_prompt.append(run_outputs)

        total_time = time.monotonic() - t_start
        total_calls = len(spec.test_prompts) * spec.num_runs
        error_rate = errors / total_calls if total_calls > 0 else 1.0

        # Latency statistics
        latency_stats = self._compute_latency_stats(latencies)

        # Consistency: average pairwise similarity across repeated runs
        consistency = self._compute_consistency(all_outputs_per_prompt)

        # Accuracy: if reference answers exist, score via LLM-as-judge
        accuracy = 0.0
        if spec.reference_answers and len(spec.reference_answers) == len(spec.test_prompts):
            accuracy = self._compute_accuracy(
                spec.test_prompts,
                all_outputs_per_prompt,
                spec.reference_answers,
                bridge,
            )
        elif error_rate < 1.0:
            # Heuristic: non-empty response ratio as proxy accuracy
            non_empty = sum(
                1 for outputs in all_outputs_per_prompt
                for o in outputs if o.strip()
            )
            accuracy = non_empty / total_calls if total_calls > 0 else 0.0

        scores: Dict[str, float] = {
            "accuracy": round(accuracy, 4),
            "latency": round(latency_stats.get("mean", 10.0), 4),
            "consistency": round(consistency, 4),
        }

        bench = BenchmarkResult(
            model_id=model_id,
            model_type=model_type,
            timestamp=time.time(),
            scores=scores,
            raw_results=raw_results,
            latency_stats=latency_stats,
            consistency_score=consistency,
            total_tokens=total_tokens,
            total_time_s=round(total_time, 3),
            error_rate=round(error_rate, 4),
        )

        self._store_benchmark(bench)
        logger.info(
            "Benchmark complete for %s: overall=%.3f accuracy=%.3f "
            "consistency=%.3f error_rate=%.3f latency_mean=%.3fs",
            model_id, bench.overall_score, accuracy,
            consistency, error_rate, latency_stats.get("mean", -1),
        )
        return bench

    def get_baseline(self, model_type: str) -> Optional[BenchmarkResult]:
        """Get the most recent benchmark for the active model of this type.

        Looks up the current active model in the registry, then finds
        its latest stored benchmark.  Falls back to the most recent
        benchmark of *any* model of this type if the active model has
        no recorded benchmark.

        Args:
            model_type: Model category.

        Returns:
            The latest :class:`BenchmarkResult`, or ``None`` if no
            benchmarks exist for this type.
        """
        # Try the active model first
        try:
            from training.model_registry import get_model_registry
            registry = get_model_registry()
            active = registry.get_active(model_type)
            if active is not None:
                row = self._fetch_latest_benchmark(active.model_id)
                if row is not None:
                    return self._row_to_benchmark(row)
        except Exception as exc:
            logger.debug("Could not query model registry for baseline: %s", exc)

        # Fallback: latest benchmark for this model_type regardless of model
        row = self._fetch_latest_benchmark_by_type(model_type)
        if row is not None:
            return self._row_to_benchmark(row)
        return None

    def get_gate_history(
        self,
        model_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get recent gate results.

        Args:
            model_type: Optional filter by model category.
            limit: Maximum rows to return.

        Returns:
            List of gate result dicts, newest first.
        """
        with self._cursor() as cur:
            if model_type:
                cur.execute(
                    "SELECT * FROM gate_results WHERE model_type = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (model_type, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM gate_results ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            rows = cur.fetchall()
        return [self._gate_row_to_dict(r) for r in rows]

    def get_benchmark_history(
        self,
        model_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get recent benchmark results.

        Args:
            model_type: Optional filter by model category.
            limit: Maximum rows to return.

        Returns:
            List of benchmark dicts, newest first.
        """
        with self._cursor() as cur:
            if model_type:
                cur.execute(
                    "SELECT * FROM benchmark_history WHERE model_type = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (model_type, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM benchmark_history ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            rows = cur.fetchall()
        return [self._bench_row_to_dict(r) for r in rows]

    def get_default_prompts(self, model_type: str) -> List[str]:
        """Get default benchmark prompts for a model type.

        Returns prompts suited for the model's purpose:
            - ``router``: classification prompts
            - ``tag_extraction``: text + expected tags
            - ``response_validate``: sample responses to validate
            - ``general``: diverse reasoning prompts

        Falls back to ``general`` if *model_type* is not mapped.

        Args:
            model_type: Model category.

        Returns:
            List of prompt strings.
        """
        return list(DEFAULT_BENCHMARK_PROMPTS.get(
            model_type,
            DEFAULT_BENCHMARK_PROMPTS["general"],
        ))

    # ── Policy evaluators ────────────────────────────────────────────

    def _evaluate_no_regression(
        self,
        before: BenchmarkResult,
        after: BenchmarkResult,
        threshold: float,
    ) -> Tuple[bool, str, str]:
        """NO_REGRESSION policy: every metric must be >= threshold * baseline.

        Args:
            before: Baseline benchmark.
            after: Candidate benchmark.
            threshold: Minimum fraction of baseline (e.g. 0.95).

        Returns:
            ``(passed, recommendation, reason)`` tuple.
        """
        failed_metrics: List[str] = []
        for metric in before.scores:
            old = before.scores[metric]
            new = after.scores.get(metric, 0.0)
            # For latency, lower is better
            if metric == "latency":
                # New latency must not be more than (1/threshold) * old
                if old > 0 and new > old / threshold:
                    failed_metrics.append(
                        f"{metric}: {new:.4f}s > {old / threshold:.4f}s ceiling"
                    )
            else:
                if old > 0 and new < threshold * old:
                    failed_metrics.append(
                        f"{metric}: {new:.4f} < {threshold * old:.4f} minimum"
                    )

        # Also check overall score
        old_overall = before.overall_score
        new_overall = after.overall_score
        if old_overall > 0 and new_overall < threshold * old_overall:
            failed_metrics.append(
                f"overall_score: {new_overall:.4f} < {threshold * old_overall:.4f} minimum"
            )

        if not failed_metrics:
            return (
                True,
                "promote",
                f"All metrics within {threshold:.0%} of baseline (overall: {new_overall:.4f})",
            )

        reason = "Regression detected — " + "; ".join(failed_metrics)
        # If regression is marginal (within 10% of threshold), flag for review
        is_marginal = all(
            "overall_score" not in fm for fm in failed_metrics
        )
        if is_marginal and len(failed_metrics) <= 1:
            return False, "review", reason
        return False, "reject", reason

    def _evaluate_must_improve(
        self,
        before: BenchmarkResult,
        after: BenchmarkResult,
        metric: str,
    ) -> Tuple[bool, str, str]:
        """MUST_IMPROVE policy: a specific metric must increase.

        Args:
            before: Baseline benchmark.
            after: Candidate benchmark.
            metric: Name of the metric that must improve.

        Returns:
            ``(passed, recommendation, reason)`` tuple.
        """
        old = before.scores.get(metric, 0.0)
        new = after.scores.get(metric, 0.0)

        # For latency, improvement means *lower* value
        if metric == "latency":
            improved = new < old
            delta = old - new
            direction = "lower"
        else:
            improved = new > old
            delta = new - old
            direction = "higher"

        if improved:
            pct = (abs(delta) / old * 100) if old else 0.0
            return (
                True,
                "promote",
                f"{metric} improved by {delta:+.4f} ({pct:+.1f}%, {direction} is better)",
            )

        if abs(new - old) < 1e-6:
            return (
                False,
                "review",
                f"{metric} unchanged at {old:.4f} — expected improvement",
            )

        pct = (abs(delta) / old * 100) if old else 0.0
        return (
            False,
            "reject",
            f"{metric} regressed by {delta:+.4f} ({pct:+.1f}%) — required improvement",
        )

    def _evaluate_pareto(
        self,
        before: BenchmarkResult,
        after: BenchmarkResult,
    ) -> Tuple[bool, str, str]:
        """PARETO_DOMINANT policy: candidate must not be dominated.

        A candidate is Pareto-dominated if the baseline is at least as
        good on *all* metrics and strictly better on at least one.  The
        candidate passes if it is *not* dominated (i.e. it is better on
        at least one metric).

        Returns:
            ``(passed, recommendation, reason)`` tuple.
        """
        metrics = sorted(set(before.scores) & set(after.scores))
        if not metrics:
            return True, "promote", "No shared metrics to compare — passing by default"

        better_count = 0
        worse_count = 0
        details: List[str] = []

        for m in metrics:
            old = before.scores[m]
            new = after.scores[m]

            if m == "latency":
                # Lower is better
                if new < old - 1e-6:
                    better_count += 1
                    details.append(f"{m}: {new:.4f}s < {old:.4f}s ✓")
                elif new > old + 1e-6:
                    worse_count += 1
                    details.append(f"{m}: {new:.4f}s > {old:.4f}s ✗")
                else:
                    details.append(f"{m}: ~equal")
            else:
                if new > old + 1e-6:
                    better_count += 1
                    details.append(f"{m}: {new:.4f} > {old:.4f} ✓")
                elif new < old - 1e-6:
                    worse_count += 1
                    details.append(f"{m}: {new:.4f} < {old:.4f} ✗")
                else:
                    details.append(f"{m}: ~equal")

        summary = "; ".join(details)

        # Dominated: baseline is >= on all, strictly > on at least one
        if worse_count > 0 and better_count == 0:
            return False, "reject", f"Pareto-dominated by baseline — {summary}"

        if worse_count > 0 and better_count > 0:
            return True, "review", f"Trade-off detected — {summary}"

        return True, "promote", f"Pareto non-dominated — {summary}"

    # ── Benchmark computation helpers ────────────────────────────────

    @staticmethod
    def _compute_latency_stats(latencies: List[float]) -> Dict[str, float]:
        """Compute summary statistics for a list of latency values.

        Args:
            latencies: Latency samples in seconds.

        Returns:
            Dict with ``mean``, ``p50``, ``p95``, ``p99``, ``min``,
            ``max``, and ``stdev``.
        """
        if not latencies:
            return {
                "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0,
                "min": 0.0, "max": 0.0, "stdev": 0.0,
            }
        sorted_lat = sorted(latencies)
        n = len(sorted_lat)

        def _percentile(pct: float) -> float:
            idx = int(pct / 100.0 * (n - 1))
            return sorted_lat[min(idx, n - 1)]

        stdev = statistics.stdev(sorted_lat) if n >= 2 else 0.0
        return {
            "mean": round(statistics.mean(sorted_lat), 4),
            "p50": round(_percentile(50), 4),
            "p95": round(_percentile(95), 4),
            "p99": round(_percentile(99), 4),
            "min": round(sorted_lat[0], 4),
            "max": round(sorted_lat[-1], 4),
            "stdev": round(stdev, 4),
        }

    @staticmethod
    def _compute_consistency(outputs_per_prompt: List[List[str]]) -> float:
        """Compute consistency score across repeated runs.

        For each prompt, measures pairwise SequenceMatcher similarity
        between all run outputs. The overall score is the mean across
        all prompts. A score of 1.0 means all runs produced identical
        outputs.

        Args:
            outputs_per_prompt: Outer list = prompts, inner = run outputs.

        Returns:
            Consistency score in 0.0–1.0 range.
        """
        if not outputs_per_prompt:
            return 0.0

        prompt_consistencies: List[float] = []
        for outputs in outputs_per_prompt:
            non_empty = [o for o in outputs if o.strip()]
            if len(non_empty) < 2:
                # Single run or all-empty: mark as 1.0 (trivially consistent)
                # or 0.0 if all empty
                prompt_consistencies.append(1.0 if non_empty else 0.0)
                continue

            pair_sims: List[float] = []
            for i in range(len(non_empty)):
                for j in range(i + 1, len(non_empty)):
                    ratio = SequenceMatcher(
                        None, non_empty[i], non_empty[j],
                    ).ratio()
                    pair_sims.append(ratio)
            prompt_consistencies.append(
                statistics.mean(pair_sims) if pair_sims else 0.0
            )

        return statistics.mean(prompt_consistencies) if prompt_consistencies else 0.0

    def _compute_accuracy(
        self,
        prompts: List[str],
        outputs_per_prompt: List[List[str]],
        reference_answers: List[str],
        bridge: Any,
    ) -> float:
        """Score accuracy via LLM-as-judge against reference answers.

        For each prompt, takes the first non-empty run output and asks
        the bridge to judge whether it matches the reference answer.

        Args:
            prompts: Original benchmark prompts.
            outputs_per_prompt: Model outputs grouped by prompt.
            reference_answers: Gold-standard reference answers.
            bridge: A :class:`LMSTaskBridge` instance.

        Returns:
            Accuracy score in 0.0–1.0 range.
        """
        if not reference_answers:
            return 0.0

        correct = 0
        total = 0
        judge_prompt_template = (
            "You are an evaluation judge. Compare the model's answer to the "
            "reference answer and rate accuracy on a scale of 0 to 10.\n\n"
            "PROMPT: {prompt}\n"
            "REFERENCE ANSWER: {reference}\n"
            "MODEL ANSWER: {model_answer}\n\n"
            "Respond with ONLY a number from 0 to 10."
        )

        for idx, (prompt, reference) in enumerate(zip(prompts, reference_answers)):
            outputs = outputs_per_prompt[idx] if idx < len(outputs_per_prompt) else []
            model_answer = next((o for o in outputs if o.strip()), "")
            if not model_answer:
                total += 1
                continue

            judge_prompt = judge_prompt_template.format(
                prompt=prompt[:300],
                reference=reference[:300],
                model_answer=model_answer[:300],
            )

            try:
                judge_result = bridge.run_prompt(
                    judge_prompt,
                    temperature=0.0,
                    max_tokens=16,
                )
                if judge_result.ok:
                    score = self._parse_judge_score(judge_result.output)
                    if score >= 7:
                        correct += 1
                total += 1
            except Exception as exc:
                logger.debug("LLM-as-judge failed for prompt %d: %s", idx, exc)
                total += 1

        return correct / total if total > 0 else 0.0

    @staticmethod
    def _parse_judge_score(text: str) -> int:
        """Extract a numeric score from judge LLM output.

        Args:
            text: Raw LLM output (expected to be a number 0–10).

        Returns:
            Parsed integer score, or 0 on failure.
        """
        text = text.strip()
        # Try to extract the first number from the text
        for token in text.split():
            cleaned = token.strip(".,;:!?/()[]")
            try:
                val = int(cleaned)
                if 0 <= val <= 10:
                    return val
            except ValueError:
                try:
                    val = int(float(cleaned))
                    if 0 <= val <= 10:
                        return val
                except ValueError:
                    continue
        return 0

    # ── Failed / empty benchmark helpers ─────────────────────────────

    @staticmethod
    def _failed_benchmark(
        model_id: str, model_type: str, error_msg: str,
    ) -> BenchmarkResult:
        """Create a benchmark result representing total failure.

        Args:
            model_id: Model identifier.
            model_type: Model category.
            error_msg: Description of the failure.

        Returns:
            A :class:`BenchmarkResult` with ``error_rate=1.0``.
        """
        return BenchmarkResult(
            model_id=model_id,
            model_type=model_type,
            timestamp=time.time(),
            scores={"accuracy": 0.0, "latency": 10.0, "consistency": 0.0},
            raw_results=[{"error": error_msg, "status": "bridge_failure"}],
            latency_stats={
                "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0,
                "min": 0.0, "max": 0.0, "stdev": 0.0,
            },
            consistency_score=0.0,
            total_tokens=0,
            total_time_s=0.0,
            error_rate=1.0,
        )

    @staticmethod
    def _make_empty_baseline(model_type: str) -> BenchmarkResult:
        """Create a neutral baseline when no prior benchmark exists.

        All scores are zeroed so any candidate automatically passes
        a NO_REGRESSION gate.

        Args:
            model_type: Model category.

        Returns:
            A :class:`BenchmarkResult` representing a zero baseline.
        """
        return BenchmarkResult(
            model_id="__no_baseline__",
            model_type=model_type,
            timestamp=0.0,
            scores={"accuracy": 0.0, "latency": 0.0, "consistency": 0.0},
            raw_results=[],
            latency_stats={
                "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0,
                "min": 0.0, "max": 0.0, "stdev": 0.0,
            },
            consistency_score=0.0,
            total_tokens=0,
            total_time_s=0.0,
            error_rate=0.0,
        )

    # ── Persistence ──────────────────────────────────────────────────

    def _store_benchmark(self, bench: BenchmarkResult) -> None:
        """Persist a benchmark result to the history table."""
        row_id = f"bench-{uuid.uuid4().hex[:8]}"
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO benchmark_history "
                "(id, model_id, model_type, scores, latency_stats, "
                " consistency, error_rate, overall_score, total_tokens, "
                " total_time_s, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row_id,
                    bench.model_id,
                    bench.model_type,
                    json.dumps(bench.scores),
                    json.dumps(bench.latency_stats),
                    bench.consistency_score,
                    bench.error_rate,
                    bench.overall_score,
                    bench.total_tokens,
                    bench.total_time_s,
                    bench.timestamp,
                ),
            )

    def _store_gate_result(self, result: GateResult) -> None:
        """Persist a gate result to the history table."""
        row_id = f"gate-{uuid.uuid4().hex[:8]}"
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO gate_results "
                "(id, model_id, model_type, policy, passed, "
                " scores_before, scores_after, delta, "
                " recommendation, reason, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row_id,
                    result.model_id,
                    result.model_type,
                    result.policy,
                    1 if result.passed else 0,
                    json.dumps(result.scores_before),
                    json.dumps(result.scores_after),
                    json.dumps(result.delta),
                    result.recommendation,
                    result.reason,
                    result.timestamp,
                ),
            )

    def _fetch_latest_benchmark(self, model_id: str) -> Optional[sqlite3.Row]:
        """Fetch the newest benchmark row for a specific model."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM benchmark_history WHERE model_id = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (model_id,),
            )
            return cur.fetchone()

    def _fetch_latest_benchmark_by_type(
        self, model_type: str,
    ) -> Optional[sqlite3.Row]:
        """Fetch the newest benchmark row for a model type."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM benchmark_history WHERE model_type = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (model_type,),
            )
            return cur.fetchone()

    @staticmethod
    def _row_to_benchmark(row: sqlite3.Row) -> BenchmarkResult:
        """Convert a SQLite row to a BenchmarkResult."""
        scores = json.loads(row["scores"]) if row["scores"] else {}
        latency_stats = json.loads(row["latency_stats"]) if row["latency_stats"] else {}
        return BenchmarkResult(
            model_id=row["model_id"],
            model_type=row["model_type"],
            timestamp=row["timestamp"],
            scores=scores,
            raw_results=[],
            latency_stats=latency_stats,
            consistency_score=row["consistency"] or 0.0,
            total_tokens=row["total_tokens"] or 0,
            total_time_s=row["total_time_s"] or 0.0,
            error_rate=row["error_rate"] or 0.0,
        )

    @staticmethod
    def _gate_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a gate_results row to a plain dict."""
        return {
            "id": row["id"],
            "model_id": row["model_id"],
            "model_type": row["model_type"],
            "policy": row["policy"],
            "passed": bool(row["passed"]),
            "scores_before": json.loads(row["scores_before"]) if row["scores_before"] else {},
            "scores_after": json.loads(row["scores_after"]) if row["scores_after"] else {},
            "delta": json.loads(row["delta"]) if row["delta"] else {},
            "recommendation": row["recommendation"],
            "reason": row["reason"],
            "timestamp": row["timestamp"],
        }

    @staticmethod
    def _bench_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a benchmark_history row to a plain dict."""
        return {
            "id": row["id"],
            "model_id": row["model_id"],
            "model_type": row["model_type"],
            "scores": json.loads(row["scores"]) if row["scores"] else {},
            "latency_stats": json.loads(row["latency_stats"]) if row["latency_stats"] else {},
            "consistency": row["consistency"],
            "error_rate": row["error_rate"],
            "overall_score": row["overall_score"],
            "total_tokens": row["total_tokens"],
            "total_time_s": row["total_time_s"],
            "timestamp": row["timestamp"],
        }

    # ── External integrations (best-effort) ──────────────────────────

    def _update_registry_score(
        self, model_id: str, bench: BenchmarkResult,
    ) -> None:
        """Update the model registry with the benchmark score."""
        try:
            from training.model_registry import get_model_registry
            registry = get_model_registry()
            registry.update_benchmark(
                model_id,
                bench.overall_score,
                details=bench.to_dict(),
            )
        except Exception as exc:
            logger.debug("Could not update model registry score: %s", exc)

    def _log_to_nexus(self, gate_result: GateResult) -> None:
        """Log gate result to Nexus knowledge store (best-effort)."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            status = "PASSED" if gate_result.passed else "FAILED"
            title = (
                f"Evaluation Gate {status}: {gate_result.model_id} "
                f"({gate_result.model_type})"
            )
            content = (
                f"Policy: {gate_result.policy}\n"
                f"Recommendation: {gate_result.recommendation}\n"
                f"Reason: {gate_result.reason}\n"
                f"Scores before: {json.dumps(gate_result.scores_before)}\n"
                f"Scores after: {json.dumps(gate_result.scores_after)}\n"
                f"Delta: {json.dumps(gate_result.delta)}\n"
                f"Delta %: {json.dumps(gate_result.delta_pct)}"
            )
            client.add_entry(
                title=title,
                content=content,
                content_type="note",
                category="training",
            )
        except Exception as exc:
            logger.debug("Could not log gate result to Nexus: %s", exc)

    def _record_impact(self, gate_result: GateResult) -> None:
        """Record gate result in ImpactTracker (best-effort)."""
        try:
            from engine.nexus.impact_tracker import ChangeType, get_impact_tracker
            tracker = get_impact_tracker()
            status = "passed" if gate_result.passed else "failed"
            tracker.record_change(
                change_type=ChangeType.MODEL_PROMOTION,
                title=f"Evaluation gate {status}: {gate_result.model_id}",
                description=gate_result.reason,
                source="evaluation_gate",
                metadata={
                    "model_id": gate_result.model_id,
                    "model_type": gate_result.model_type,
                    "policy": gate_result.policy,
                    "passed": gate_result.passed,
                    "recommendation": gate_result.recommendation,
                    "overall_before": gate_result.benchmark_before.overall_score if gate_result.benchmark_before else None,
                    "overall_after": gate_result.benchmark_after.overall_score if gate_result.benchmark_after else None,
                },
            )
        except Exception as exc:
            logger.debug("Could not record impact: %s", exc)


# ──── Singleton ──────────────────────────────────────────────────────

_gate_instance: Optional[EvaluationGate] = None
_gate_lock = threading.Lock()


def get_evaluation_gate(db_path: Optional[Path] = None) -> EvaluationGate:
    """Get or create the EvaluationGate singleton.

    Args:
        db_path: Override database path (only used on first call).

    Returns:
        The shared :class:`EvaluationGate` instance.
    """
    global _gate_instance
    if _gate_instance is None:
        with _gate_lock:
            if _gate_instance is None:
                _gate_instance = EvaluationGate(db_path)
    return _gate_instance
