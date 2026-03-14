"""CausalEngine — Granger causality testing and causal DAG inference.

Extends the observability stack beyond correlation (CorrelationEngine) into
true causal analysis.  Uses Granger causality tests on metric time-series
to determine whether changes in one metric *precede and predict* changes
in another, and assembles those pairwise results into a directed acyclic
graph (DAG) of causal relationships.

Key capabilities:
- Granger causality testing (F-test on lagged regressions)
- Causal DAG construction from pairwise Granger results
- Root-cause analysis: trace anomaly metrics back to causal predecessors
- Intervention analysis: predict downstream impact of a metric change
- Integration with ImpactTracker for change-aware causal windows

Usage::

    from engine.observability.causal_engine import get_causal_engine
    engine = get_causal_engine()

    # Feed time-series data (same interface as CorrelationEngine)
    engine.feed("system", "cpu_pct", 45.2)
    engine.feed("pipeline", "latency_ms", 230.0)

    # Test if CPU causally precedes latency
    result = engine.granger_test("system.cpu_pct", "pipeline.latency_ms")

    # Build full causal DAG
    dag = engine.build_causal_dag(min_samples=50)

    # Find root causes of a metric anomaly
    roots = engine.get_root_causes("pipeline.latency_ms")

    # Predict downstream impact of a change
    impact = engine.analyze_intervention("system.cpu_pct", delta=+20.0)
"""
from __future__ import annotations

import logging
import math
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/causal_engine.db")

# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional["CausalEngine"] = None
_lock = threading.Lock()


def get_causal_engine(
    db_path: Optional[Path] = None,
) -> "CausalEngine":
    """Get or create the singleton CausalEngine."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = CausalEngine(db_path=db_path)
    return _instance


# ── Data Models ─────────────────────────────────────────────────────────


@dataclass
class GrangerResult:
    """Result of a pairwise Granger causality test."""

    cause_metric: str
    effect_metric: str
    f_statistic: float
    p_value: float
    optimal_lag: int
    is_causal: bool
    direction: str  # "unidirectional", "bidirectional", "none"
    strength: str  # "strong" (<0.01), "moderate" (<0.05), "weak" (<0.10), "none"
    sample_count: int
    test_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)


@dataclass
class CausalEdge:
    """A directed edge in the causal DAG."""

    cause: str
    effect: str
    f_statistic: float
    p_value: float
    lag: int
    strength: str
    weight: float  # 1 - p_value (higher = stronger causation)


@dataclass
class CausalDAG:
    """Directed acyclic graph of causal relationships."""

    edges: List[CausalEdge] = field(default_factory=list)
    nodes: Set[str] = field(default_factory=set)
    build_timestamp: float = field(default_factory=time.time)
    sample_count: int = 0

    def adjacency(self) -> Dict[str, List[str]]:
        """Return cause → [effects] adjacency list."""
        adj: Dict[str, List[str]] = defaultdict(list)
        for edge in self.edges:
            adj[edge.cause].append(edge.effect)
        return dict(adj)

    def reverse_adjacency(self) -> Dict[str, List[str]]:
        """Return effect → [causes] adjacency list."""
        rev: Dict[str, List[str]] = defaultdict(list)
        for edge in self.edges:
            rev[edge.effect].append(edge.cause)
        return dict(rev)

    def roots(self) -> Set[str]:
        """Nodes with no incoming edges (ultimate causes)."""
        effects = {e.effect for e in self.edges}
        return self.nodes - effects

    def leaves(self) -> Set[str]:
        """Nodes with no outgoing edges (terminal effects)."""
        causes = {e.cause for e in self.edges}
        return self.nodes - causes

    def get_edge(self, cause: str, effect: str) -> Optional[CausalEdge]:
        """Find a specific edge."""
        for edge in self.edges:
            if edge.cause == cause and edge.effect == effect:
                return edge
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "nodes": sorted(self.nodes),
            "edges": [asdict(e) for e in self.edges],
            "roots": sorted(self.roots()),
            "leaves": sorted(self.leaves()),
            "edge_count": len(self.edges),
            "node_count": len(self.nodes),
            "build_timestamp": self.build_timestamp,
            "sample_count": self.sample_count,
        }


@dataclass
class RootCauseResult:
    """Root-cause analysis for a target metric."""

    target_metric: str
    root_causes: List[Dict[str, Any]]
    causal_chain: List[List[str]]
    analysis_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)


@dataclass
class InterventionResult:
    """Predicted downstream effects of intervening on a metric."""

    intervention_metric: str
    delta: float
    downstream_effects: List[Dict[str, Any]]
    total_affected: int
    analysis_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)


# ── Helpers ─────────────────────────────────────────────────────────────


def _classify_strength(p_value: float) -> str:
    """Classify causal strength from p-value."""
    if p_value < 0.01:
        return "strong"
    if p_value < 0.05:
        return "moderate"
    if p_value < 0.10:
        return "weak"
    return "none"


def _ols_residuals(y: List[float], X: List[List[float]]) -> Tuple[float, List[float]]:
    """Ordinary least squares via normal equations. Returns (RSS, residuals).

    X is a list of row vectors (each row = one observation's feature vector).
    y is the response vector.
    Uses Gaussian elimination for the normal equations X^T X beta = X^T y.
    """
    n = len(y)
    k = len(X[0]) if X else 0
    if n == 0 or k == 0:
        return 0.0, []

    # Build X^T X (k x k) and X^T y (k x 1)
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k

    for i in range(n):
        for j in range(k):
            xty[j] += X[i][j] * y[i]
            for m in range(j, k):
                val = X[i][j] * X[i][m]
                xtx[j][m] += val
                if j != m:
                    xtx[m][j] += val

    # Solve via Gaussian elimination with partial pivoting
    aug = [xtx[r][:] + [xty[r]] for r in range(k)]
    for col in range(k):
        # Pivot
        max_row = col
        max_val = abs(aug[col][col])
        for row in range(col + 1, k):
            if abs(aug[row][col]) > max_val:
                max_val = abs(aug[row][col])
                max_row = row
        if max_val < 1e-12:
            return float("inf"), [0.0] * n
        aug[col], aug[max_row] = aug[max_row], aug[col]

        pivot = aug[col][col]
        for row in range(col + 1, k):
            factor = aug[row][col] / pivot
            for c in range(col, k + 1):
                aug[row][c] -= factor * aug[col][c]

    # Back-substitution
    beta = [0.0] * k
    for i in range(k - 1, -1, -1):
        s = aug[i][k]
        for j in range(i + 1, k):
            s -= aug[i][j] * beta[j]
        if abs(aug[i][i]) < 1e-12:
            beta[i] = 0.0
        else:
            beta[i] = s / aug[i][i]

    # Compute residuals and RSS
    residuals = []
    rss = 0.0
    for i in range(n):
        y_hat = sum(X[i][j] * beta[j] for j in range(k))
        r = y[i] - y_hat
        residuals.append(r)
        rss += r * r

    return rss, residuals


def _f_distribution_p_value(f_stat: float, df1: int, df2: int) -> float:
    """Approximate p-value for F-distribution using regularized incomplete beta.

    Uses the relationship: P(F > f) = I_x(df1/2, df2/2) where x = df1*f/(df1*f+df2).
    Falls back to a conservative Chi-squared approximation for edge cases.
    """
    if f_stat <= 0 or df1 <= 0 or df2 <= 0:
        return 1.0

    x = (df1 * f_stat) / (df1 * f_stat + df2)
    a = df1 / 2.0
    b = df2 / 2.0

    return 1.0 - _regularized_incomplete_beta(x, a, b)


def _regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """Compute I_x(a,b) via continued fraction expansion (Lentz's method)."""
    if x < 0.0 or x > 1.0:
        return 0.0
    if x == 0.0:
        return 0.0
    if x == 1.0:
        return 1.0

    # Use symmetry relation if x > (a+1)/(a+b+2) for better convergence
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _regularized_incomplete_beta(1.0 - x, b, a)

    # Log of the coefficient: x^a * (1-x)^b / (a * B(a,b))
    lbeta = _log_beta(a, b)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - lbeta) / a

    # Continued fraction (Lentz's method)
    tiny = 1e-30
    f = tiny
    c = tiny
    d = 1.0 - (a + b) * x / (a + 1.0)
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    f = d

    for m in range(1, 201):
        # Even step
        numerator = m * (b - m) * x / ((a + 2.0 * m - 1.0) * (a + 2.0 * m))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        f *= c * d

        # Odd step
        numerator = -(a + m) * (a + b + m) * x / ((a + 2.0 * m) * (a + 2.0 * m + 1.0))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = c * d
        f *= delta

        if abs(delta - 1.0) < 1e-10:
            break

    return front * (f - 1.0) + front  # front * f


def _log_beta(a: float, b: float) -> float:
    """Compute log(B(a,b)) = log(Gamma(a)) + log(Gamma(b)) - log(Gamma(a+b))."""
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


# ── CausalEngine ────────────────────────────────────────────────────────


class CausalEngine:
    """Granger causality testing and causal DAG inference engine.

    Maintains metric time-series in memory (ring buffers), performs pairwise
    Granger causality tests, builds causal DAGs, and provides root-cause
    analysis and intervention prediction.

    Args:
        db_path: Path to SQLite database for persistence.
        max_samples: Maximum samples per metric in ring buffer.
        default_max_lag: Default maximum lag (in samples) for Granger tests.
        significance_level: P-value threshold for causal significance.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        max_samples: int = 500,
        default_max_lag: int = 10,
        significance_level: float = 0.05,
    ) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._max_samples = max_samples
        self._default_max_lag = default_max_lag
        self._significance_level = significance_level

        # Time-series buffers: metric_key → deque of (timestamp, value)
        self._series: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=max_samples)
        )
        self._series_lock = threading.Lock()

        # Cached DAG (invalidated when new data arrives)
        self._cached_dag: Optional[CausalDAG] = None
        self._dag_build_count: int = 0

        # Result history
        self._granger_history: deque = deque(maxlen=500)
        self._dag_history: deque = deque(maxlen=50)

        # Database
        self._local = threading.local()
        self._init_db()

        logger.info(
            "CausalEngine initialised (db=%s, max_samples=%d, max_lag=%d, α=%.3f)",
            self._db_path,
            max_samples,
            default_max_lag,
            significance_level,
        )

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
                CREATE TABLE IF NOT EXISTS granger_results (
                    id TEXT PRIMARY KEY,
                    cause_metric TEXT NOT NULL,
                    effect_metric TEXT NOT NULL,
                    f_statistic REAL NOT NULL,
                    p_value REAL NOT NULL,
                    optimal_lag INTEGER NOT NULL,
                    is_causal INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    strength TEXT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    test_timestamp REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS causal_dags (
                    id TEXT PRIMARY KEY,
                    edges_json TEXT NOT NULL,
                    nodes_json TEXT NOT NULL,
                    edge_count INTEGER NOT NULL,
                    node_count INTEGER NOT NULL,
                    sample_count INTEGER NOT NULL,
                    build_timestamp REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_granger_cause
                ON granger_results(cause_metric)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_granger_effect
                ON granger_results(effect_metric)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_granger_ts
                ON granger_results(test_timestamp)
            """)

    # ── Data Ingestion ──────────────────────────────────────────────────

    def feed(
        self,
        node: str,
        metric: str,
        value: float,
        ts: Optional[float] = None,
    ) -> None:
        """Add a metric sample to the time-series buffer.

        Args:
            node: Source node (e.g., "system", "pipeline").
            metric: Metric name (e.g., "cpu_pct", "latency_ms").
            value: Metric value.
            ts: Timestamp (defaults to current time).
        """
        key = f"{node}.{metric}"
        timestamp = ts or time.time()
        with self._series_lock:
            self._series[key].append((timestamp, value))
        # Invalidate cached DAG
        self._cached_dag = None

    def feed_batch(
        self,
        samples: List[Tuple[str, str, float, Optional[float]]],
    ) -> int:
        """Feed multiple samples at once.

        Args:
            samples: List of (node, metric, value, timestamp) tuples.

        Returns:
            Number of samples ingested.
        """
        with self._series_lock:
            for node, metric, value, ts in samples:
                key = f"{node}.{metric}"
                self._series[key].append((ts or time.time(), value))
        self._cached_dag = None
        return len(samples)

    def tracked_metrics(self) -> List[str]:
        """Return all metric keys currently being tracked."""
        with self._series_lock:
            return sorted(self._series.keys())

    def sample_count(self, metric_key: str) -> int:
        """Return number of samples for a metric."""
        with self._series_lock:
            return len(self._series.get(metric_key, []))

    # ── Granger Causality Test ──────────────────────────────────────────

    def granger_test(
        self,
        cause_metric: str,
        effect_metric: str,
        max_lag: Optional[int] = None,
        significance: Optional[float] = None,
    ) -> Optional[GrangerResult]:
        """Test if cause_metric Granger-causes effect_metric.

        Performs an F-test comparing:
        - Restricted model: y_t = a0 + a1*y_{t-1} + ... + ap*y_{t-p}
        - Unrestricted model: y_t = a0 + a1*y_{t-1} + ... + ap*y_{t-p}
                                    + b1*x_{t-1} + ... + bp*x_{t-p}

        Tests multiple lags and selects the one with highest F-statistic.

        Args:
            cause_metric: Potential cause metric key.
            effect_metric: Potential effect metric key.
            max_lag: Maximum number of lags to test.
            significance: P-value threshold (default: self._significance_level).

        Returns:
            GrangerResult if sufficient data, None otherwise.
        """
        max_lag = max_lag or self._default_max_lag
        alpha = significance or self._significance_level

        # Extract aligned time-series
        x_series, y_series = self._align_series(cause_metric, effect_metric)
        n = len(x_series)

        min_required = max_lag + max_lag + 2  # Need enough for lags + regression
        if n < min_required:
            logger.debug(
                "Insufficient samples for Granger test %s→%s: %d < %d",
                cause_metric, effect_metric, n, min_required,
            )
            return None

        best_f = -1.0
        best_p = 1.0
        best_lag = 1

        for lag in range(1, max_lag + 1):
            f_stat, p_val = self._granger_f_test(x_series, y_series, lag)
            if f_stat is not None and f_stat > best_f:
                best_f = f_stat
                best_p = p_val
                best_lag = lag

        if best_f < 0:
            return None

        is_causal = best_p < alpha
        strength = _classify_strength(best_p)

        # Test reverse direction for bidirectionality
        reverse_f, reverse_p = self._granger_f_test(y_series, x_series, best_lag)
        if reverse_f is not None and reverse_p < alpha and is_causal:
            direction = "bidirectional"
        elif is_causal:
            direction = "unidirectional"
        else:
            direction = "none"

        result = GrangerResult(
            cause_metric=cause_metric,
            effect_metric=effect_metric,
            f_statistic=best_f,
            p_value=best_p,
            optimal_lag=best_lag,
            is_causal=is_causal,
            direction=direction,
            strength=strength,
            sample_count=n,
        )

        # Cache and persist
        self._granger_history.append(result)
        self._persist_granger(result)

        return result

    def _granger_f_test(
        self,
        x: List[float],
        y: List[float],
        lag: int,
    ) -> Tuple[Optional[float], float]:
        """Perform a single Granger F-test at a specific lag.

        Returns:
            (F-statistic, p-value) or (None, 1.0) if insufficient data.
        """
        n = len(y)
        if n <= 2 * lag + 1:
            return None, 1.0

        # Build lagged data
        y_target = y[lag:]
        n_obs = len(y_target)

        # Restricted model: y_t ~ intercept + y_{t-1} + ... + y_{t-lag}
        X_restricted = []
        for t in range(lag, n):
            row = [1.0]  # intercept
            for l in range(1, lag + 1):
                row.append(y[t - l])
            X_restricted.append(row)

        # Unrestricted model: y_t ~ intercept + y lags + x lags
        X_unrestricted = []
        for t in range(lag, n):
            row = [1.0]  # intercept
            for l in range(1, lag + 1):
                row.append(y[t - l])
            for l in range(1, lag + 1):
                row.append(x[t - l])
            X_unrestricted.append(row)

        rss_r, _ = _ols_residuals(y_target, X_restricted)
        rss_u, _ = _ols_residuals(y_target, X_unrestricted)

        # Degrees of freedom
        k_r = lag + 1  # intercept + lag y terms
        k_u = 2 * lag + 1  # intercept + lag y terms + lag x terms
        df1 = k_u - k_r  # = lag
        df2 = n_obs - k_u

        if df2 <= 0 or rss_u <= 0:
            return None, 1.0

        # Guard against numerically zero RSS difference
        if rss_r <= rss_u:
            return 0.0, 1.0

        f_stat = ((rss_r - rss_u) / df1) / (rss_u / df2)
        p_value = _f_distribution_p_value(f_stat, df1, df2)

        return f_stat, p_value

    def _align_series(
        self,
        metric_a: str,
        metric_b: str,
    ) -> Tuple[List[float], List[float]]:
        """Align two time-series by nearest timestamp.

        Returns two lists of the same length with paired values.
        """
        with self._series_lock:
            series_a = list(self._series.get(metric_a, []))
            series_b = list(self._series.get(metric_b, []))

        if not series_a or not series_b:
            return [], []

        # Sort by timestamp
        series_a.sort(key=lambda x: x[0])
        series_b.sort(key=lambda x: x[0])

        # Nearest-timestamp alignment
        aligned_a: List[float] = []
        aligned_b: List[float] = []
        j = 0

        for ts_a, val_a in series_a:
            # Find nearest point in series_b
            while j < len(series_b) - 1 and abs(series_b[j + 1][0] - ts_a) < abs(series_b[j][0] - ts_a):
                j += 1
            # Only pair if timestamps are within reasonable proximity
            if abs(series_b[j][0] - ts_a) < 300.0:  # 5 minute tolerance
                aligned_a.append(val_a)
                aligned_b.append(series_b[j][1])

        return aligned_a, aligned_b

    # ── Causal DAG Construction ─────────────────────────────────────────

    def build_causal_dag(
        self,
        min_samples: int = 30,
        max_lag: Optional[int] = None,
        significance: Optional[float] = None,
        metrics: Optional[List[str]] = None,
    ) -> CausalDAG:
        """Build a causal DAG from pairwise Granger tests.

        Tests all pairs of tracked metrics and constructs directed edges
        for statistically significant causal relationships. Removes cycles
        via topological pruning (weakest edge in cycle removed).

        Args:
            min_samples: Minimum samples required per metric.
            max_lag: Maximum lag for Granger tests.
            significance: P-value threshold.
            metrics: Specific metrics to include (default: all tracked).

        Returns:
            CausalDAG with nodes and directed edges.
        """
        if self._cached_dag is not None:
            return self._cached_dag

        alpha = significance or self._significance_level
        target_metrics = metrics or self.tracked_metrics()

        # Filter to metrics with sufficient data
        qualified = [m for m in target_metrics if self.sample_count(m) >= min_samples]
        if len(qualified) < 2:
            logger.debug("Not enough qualified metrics for DAG: %d", len(qualified))
            return CausalDAG(nodes=set(qualified))

        dag = CausalDAG(nodes=set(qualified))
        min_sample_count = min(self.sample_count(m) for m in qualified)
        dag.sample_count = min_sample_count

        # Test all pairs
        for i, metric_a in enumerate(qualified):
            for metric_b in qualified[i + 1:]:
                result_ab = self.granger_test(metric_a, metric_b, max_lag, alpha)
                result_ba = self.granger_test(metric_b, metric_a, max_lag, alpha)

                # Add edges for significant causal relationships
                if result_ab and result_ab.is_causal:
                    dag.edges.append(CausalEdge(
                        cause=metric_a,
                        effect=metric_b,
                        f_statistic=result_ab.f_statistic,
                        p_value=result_ab.p_value,
                        lag=result_ab.optimal_lag,
                        strength=result_ab.strength,
                        weight=1.0 - result_ab.p_value,
                    ))

                if result_ba and result_ba.is_causal:
                    # For bidirectional, only keep the stronger direction
                    if result_ab and result_ab.is_causal:
                        if result_ba.f_statistic > result_ab.f_statistic:
                            # Remove the weaker A→B edge, keep B→A
                            dag.edges = [
                                e for e in dag.edges
                                if not (e.cause == metric_a and e.effect == metric_b)
                            ]
                            dag.edges.append(CausalEdge(
                                cause=metric_b,
                                effect=metric_a,
                                f_statistic=result_ba.f_statistic,
                                p_value=result_ba.p_value,
                                lag=result_ba.optimal_lag,
                                strength=result_ba.strength,
                                weight=1.0 - result_ba.p_value,
                            ))
                    else:
                        dag.edges.append(CausalEdge(
                            cause=metric_b,
                            effect=metric_a,
                            f_statistic=result_ba.f_statistic,
                            p_value=result_ba.p_value,
                            lag=result_ba.optimal_lag,
                            strength=result_ba.strength,
                            weight=1.0 - result_ba.p_value,
                        ))

        # Remove remaining cycles
        self._break_cycles(dag)

        # Cache and persist
        self._cached_dag = dag
        self._dag_build_count += 1
        self._dag_history.append(dag)
        self._persist_dag(dag)

        logger.info(
            "Built causal DAG: %d nodes, %d edges",
            len(dag.nodes), len(dag.edges),
        )

        return dag

    def _break_cycles(self, dag: CausalDAG) -> None:
        """Remove cycles from DAG by pruning weakest edges in each cycle."""
        adj = dag.adjacency()

        while True:
            cycle = self._find_cycle(dag.nodes, adj)
            if cycle is None:
                break

            # Find weakest edge in cycle
            weakest_edge: Optional[CausalEdge] = None
            weakest_weight = float("inf")
            for i in range(len(cycle)):
                cause = cycle[i]
                effect = cycle[(i + 1) % len(cycle)]
                edge = dag.get_edge(cause, effect)
                if edge and edge.weight < weakest_weight:
                    weakest_weight = edge.weight
                    weakest_edge = edge

            if weakest_edge:
                dag.edges.remove(weakest_edge)
                # Rebuild adjacency
                adj = dag.adjacency()
                logger.debug(
                    "Broke cycle by removing %s→%s (weight=%.4f)",
                    weakest_edge.cause, weakest_edge.effect, weakest_edge.weight,
                )

    def _find_cycle(
        self,
        nodes: Set[str],
        adj: Dict[str, List[str]],
    ) -> Optional[List[str]]:
        """DFS-based cycle detection. Returns cycle path or None."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {n: WHITE for n in nodes}
        parent: Dict[str, Optional[str]] = {n: None for n in nodes}

        def dfs(node: str) -> Optional[List[str]]:
            color[node] = GRAY
            for neighbor in adj.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    # Found cycle — reconstruct
                    cycle = [neighbor]
                    current = node
                    while current != neighbor:
                        cycle.append(current)
                        current = parent.get(current, neighbor)
                    cycle.reverse()
                    return cycle
                if color[neighbor] == WHITE:
                    parent[neighbor] = node
                    result = dfs(neighbor)
                    if result:
                        return result
            color[node] = BLACK
            return None

        for node in sorted(nodes):
            if color[node] == WHITE:
                result = dfs(node)
                if result:
                    return result
        return None

    # ── Root-Cause Analysis ─────────────────────────────────────────────

    def get_root_causes(
        self,
        target_metric: str,
        min_samples: int = 30,
        max_depth: int = 5,
    ) -> RootCauseResult:
        """Trace a target metric back to its causal roots in the DAG.

        Performs breadth-first traversal backwards through the causal DAG
        to find all upstream causes and their causal chains.

        Args:
            target_metric: The metric to analyze.
            min_samples: Minimum samples for DAG construction.
            max_depth: Maximum traversal depth.

        Returns:
            RootCauseResult with root causes and causal chains.
        """
        dag = self.build_causal_dag(min_samples=min_samples)
        rev_adj = dag.reverse_adjacency()
        edge_map: Dict[Tuple[str, str], CausalEdge] = {
            (e.cause, e.effect): e for e in dag.edges
        }

        # BFS backwards from target
        root_causes: List[Dict[str, Any]] = []
        chains: List[List[str]] = []
        visited: Set[str] = set()
        queue: List[Tuple[str, List[str]]] = [(target_metric, [target_metric])]

        while queue:
            current, path = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            causes = rev_adj.get(current, [])
            if not causes and current != target_metric:
                # This is a root cause
                edge = edge_map.get((current, path[-2] if len(path) > 1 else target_metric))
                root_causes.append({
                    "metric": current,
                    "depth": len(path) - 1,
                    "chain": path[:],
                    "edge_strength": edge.strength if edge else "unknown",
                    "edge_p_value": edge.p_value if edge else 1.0,
                    "edge_f_statistic": edge.f_statistic if edge else 0.0,
                })
                chains.append(path[:])
            elif len(path) <= max_depth:
                for cause in causes:
                    if cause not in visited:
                        queue.append((cause, path + [cause]))

        # If target has direct causes but no ultimate roots, add direct causes
        direct_causes = rev_adj.get(target_metric, [])
        for cause in direct_causes:
            edge = edge_map.get((cause, target_metric))
            if cause not in {r["metric"] for r in root_causes}:
                root_causes.append({
                    "metric": cause,
                    "depth": 1,
                    "chain": [target_metric, cause],
                    "edge_strength": edge.strength if edge else "unknown",
                    "edge_p_value": edge.p_value if edge else 1.0,
                    "edge_f_statistic": edge.f_statistic if edge else 0.0,
                })
                chains.append([target_metric, cause])

        # Sort by depth (shallowest first) then by edge strength
        strength_order = {"strong": 0, "moderate": 1, "weak": 2, "none": 3, "unknown": 4}
        root_causes.sort(key=lambda r: (r["depth"], strength_order.get(r["edge_strength"], 4)))

        return RootCauseResult(
            target_metric=target_metric,
            root_causes=root_causes,
            causal_chain=chains,
        )

    # ── Intervention Analysis ───────────────────────────────────────────

    def analyze_intervention(
        self,
        metric: str,
        delta: float,
        min_samples: int = 30,
        max_depth: int = 5,
    ) -> InterventionResult:
        """Predict downstream effects of intervening on a metric.

        Traverses the causal DAG forward from the intervention metric,
        estimating cascading effects based on edge weights and historical
        correlation strengths.

        Args:
            metric: The metric being intervened on.
            delta: The magnitude of the intervention change.
            min_samples: Minimum samples for DAG construction.
            max_depth: Maximum cascade depth.

        Returns:
            InterventionResult with predicted downstream effects.
        """
        dag = self.build_causal_dag(min_samples=min_samples)
        adj = dag.adjacency()
        edge_map: Dict[Tuple[str, str], CausalEdge] = {
            (e.cause, e.effect): e for e in dag.edges
        }

        # BFS forward from intervention point
        downstream: List[Dict[str, Any]] = []
        visited: Set[str] = set()
        queue: List[Tuple[str, float, int]] = [(metric, delta, 0)]

        while queue:
            current, current_delta, depth = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            effects = adj.get(current, [])
            for effect in effects:
                edge = edge_map.get((current, effect))
                if edge is None:
                    continue

                # Estimate propagated delta: scale by edge weight and attenuate
                propagated_delta = current_delta * edge.weight * 0.7  # 30% attenuation

                downstream.append({
                    "metric": effect,
                    "estimated_delta": propagated_delta,
                    "depth": depth + 1,
                    "via": current,
                    "edge_strength": edge.strength,
                    "edge_weight": edge.weight,
                    "edge_lag": edge.lag,
                })

                if depth + 1 < max_depth and effect not in visited:
                    queue.append((effect, propagated_delta, depth + 1))

        downstream.sort(key=lambda d: abs(d["estimated_delta"]), reverse=True)

        return InterventionResult(
            intervention_metric=metric,
            delta=delta,
            downstream_effects=downstream,
            total_affected=len(downstream),
        )

    # ── Queries ─────────────────────────────────────────────────────────

    def recent_tests(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent Granger test results from history."""
        results = list(self._granger_history)[-limit:]
        return [r.to_dict() for r in reversed(results)]

    def causal_summary(self) -> Dict[str, Any]:
        """Return a summary of the causal analysis state."""
        dag = self._cached_dag
        dag_info = dag.to_dict() if dag else None

        return {
            "tracked_metrics": len(self._series),
            "metric_keys": self.tracked_metrics(),
            "total_samples": sum(len(s) for s in self._series.values()),
            "granger_tests_run": len(self._granger_history),
            "dags_built": self._dag_build_count,
            "current_dag": dag_info,
            "significance_level": self._significance_level,
            "max_lag": self._default_max_lag,
        }

    def strongest_causes(
        self,
        limit: int = 10,
        min_strength: str = "moderate",
    ) -> List[Dict[str, Any]]:
        """Return strongest causal relationships from the current DAG."""
        dag = self._cached_dag
        if dag is None:
            return []

        strength_order = {"strong": 0, "moderate": 1, "weak": 2, "none": 3}
        threshold = strength_order.get(min_strength, 1)

        filtered = [
            e for e in dag.edges
            if strength_order.get(e.strength, 3) <= threshold
        ]
        filtered.sort(key=lambda e: e.p_value)

        return [asdict(e) for e in filtered[:limit]]

    def causal_path(
        self,
        source: str,
        target: str,
    ) -> Optional[List[str]]:
        """Find shortest causal path between two metrics.

        Args:
            source: Starting metric.
            target: Destination metric.

        Returns:
            List of metrics in the causal path, or None if no path exists.
        """
        dag = self._cached_dag
        if dag is None:
            return None

        adj = dag.adjacency()
        visited: Set[str] = set()
        queue: List[Tuple[str, List[str]]] = [(source, [source])]

        while queue:
            current, path = queue.pop(0)
            if current == target:
                return path
            if current in visited:
                continue
            visited.add(current)
            for neighbor in adj.get(current, []):
                if neighbor not in visited:
                    queue.append((neighbor, path + [neighbor]))

        return None

    def snapshot(self) -> Dict[str, Any]:
        """Return engine status snapshot."""
        return {
            "tracked_metrics": len(self._series),
            "total_samples": sum(len(s) for s in self._series.values()),
            "granger_tests_run": len(self._granger_history),
            "dags_built": self._dag_build_count,
            "cached_dag_available": self._cached_dag is not None,
            "significance_level": self._significance_level,
            "max_lag": self._default_max_lag,
        }

    # ── Persistence ─────────────────────────────────────────────────────

    def _persist_granger(self, result: GrangerResult) -> None:
        """Store a Granger test result in the database."""
        try:
            with self._tx() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO granger_results
                    (id, cause_metric, effect_metric, f_statistic, p_value,
                     optimal_lag, is_causal, direction, strength,
                     sample_count, test_timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        result.cause_metric,
                        result.effect_metric,
                        result.f_statistic,
                        result.p_value,
                        result.optimal_lag,
                        1 if result.is_causal else 0,
                        result.direction,
                        result.strength,
                        result.sample_count,
                        result.test_timestamp,
                    ),
                )
        except Exception as exc:
            logger.warning("Failed to persist Granger result: %s", exc)

    def _persist_dag(self, dag: CausalDAG) -> None:
        """Store a DAG snapshot in the database."""
        try:
            import json

            edges_json = json.dumps([asdict(e) for e in dag.edges])
            nodes_json = json.dumps(sorted(dag.nodes))
            with self._tx() as conn:
                conn.execute(
                    """INSERT INTO causal_dags
                    (id, edges_json, nodes_json, edge_count, node_count,
                     sample_count, build_timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        edges_json,
                        nodes_json,
                        len(dag.edges),
                        len(dag.nodes),
                        dag.sample_count,
                        dag.build_timestamp,
                    ),
                )
        except Exception as exc:
            logger.warning("Failed to persist DAG: %s", exc)

    def load_recent_dags(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Load recent DAG snapshots from the database."""
        import json

        try:
            conn = self._get_conn()
            rows = conn.execute(
                """SELECT * FROM causal_dags
                ORDER BY build_timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "edges": json.loads(row["edges_json"]),
                    "nodes": json.loads(row["nodes_json"]),
                    "edge_count": row["edge_count"],
                    "node_count": row["node_count"],
                    "sample_count": row["sample_count"],
                    "build_timestamp": row["build_timestamp"],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("Failed to load DAGs: %s", exc)
            return []

    def load_recent_results(
        self,
        limit: int = 50,
        causal_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Load recent Granger results from the database."""
        try:
            conn = self._get_conn()
            query = "SELECT * FROM granger_results"
            if causal_only:
                query += " WHERE is_causal = 1"
            query += " ORDER BY test_timestamp DESC LIMIT ?"
            rows = conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.warning("Failed to load Granger results: %s", exc)
            return []


# ── Scheduler Integration ───────────────────────────────────────────────


def register_causal_tasks(daemon: Any) -> None:
    """Register causal analysis tasks with the scheduler daemon.

    Args:
        daemon: TaskSchedulerDaemon instance.
    """

    def _run_causal_analysis() -> Dict[str, Any]:
        """Build causal DAG and report summary."""
        engine = get_causal_engine()
        dag = engine.build_causal_dag()
        summary = engine.causal_summary()
        return {
            "status": "ok",
            "nodes": len(dag.nodes),
            "edges": len(dag.edges),
            "roots": sorted(dag.roots()),
            "strongest": engine.strongest_causes(limit=5),
            "total_granger_tests": summary["granger_tests_run"],
        }

    daemon.register(
        "causal-analysis",
        "Causal DAG Analysis",
        "every_6h",
        _run_causal_analysis,
    )
