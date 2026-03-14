"""MCP causal analysis skills — Granger causality, DAG construction, root-cause analysis."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ──── Helpers ──────────────────────────────────────────────────────────


def _ts(epoch: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp(epoch or time.time(), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _get_engine() -> Any:
    from engine.observability.causal_engine import get_causal_engine
    return get_causal_engine()


# ──── Skills ───────────────────────────────────────────────────────────


@skill(
    pack="causal",
    description="Run a Granger causality test between two metrics to determine if one causally precedes the other.",
    category=SkillCategory.SYSTEM,
    cooldown=2.0,
    cost=1.0,
    tags=["causal", "granger", "observability"],
)
def causal_granger_test(
    cause_metric: str,
    effect_metric: str,
    max_lag: int = 10,
) -> str:
    """Test if cause_metric Granger-causes effect_metric.

    Args:
        cause_metric: Potential cause (e.g., "system.cpu_pct").
        effect_metric: Potential effect (e.g., "pipeline.latency_ms").
        max_lag: Maximum lag to test (default 10).

    Returns:
        Formatted Granger test result.
    """
    engine = _get_engine()
    result = engine.granger_test(cause_metric, effect_metric, max_lag=max_lag)

    if result is None:
        return f"Insufficient data for Granger test: {cause_metric} → {effect_metric}"

    lines = [
        f"Granger Causality Test: {cause_metric} → {effect_metric}",
        f"  Result: {'CAUSAL' if result.is_causal else 'NOT CAUSAL'}",
        f"  F-statistic: {result.f_statistic:.4f}",
        f"  P-value: {result.p_value:.6f}",
        f"  Optimal lag: {result.optimal_lag}",
        f"  Direction: {result.direction}",
        f"  Strength: {result.strength}",
        f"  Samples: {result.sample_count}",
    ]
    return "\n".join(lines)


@skill(
    pack="causal",
    description="Build a causal directed acyclic graph (DAG) from all tracked metrics using Granger causality tests.",
    category=SkillCategory.SYSTEM,
    cooldown=10.0,
    cost=3.0,
    tags=["causal", "dag", "observability"],
)
def causal_build_dag(
    min_samples: int = 30,
    max_lag: int = 10,
) -> str:
    """Build a causal DAG from pairwise Granger tests across all tracked metrics.

    Args:
        min_samples: Minimum samples per metric for inclusion.
        max_lag: Maximum lag for Granger tests.

    Returns:
        DAG summary with nodes, edges, and root causes.
    """
    engine = _get_engine()
    dag = engine.build_causal_dag(min_samples=min_samples, max_lag=max_lag)

    lines = [
        "Causal DAG",
        f"  Nodes: {len(dag.nodes)}",
        f"  Edges: {len(dag.edges)}",
        f"  Root causes: {', '.join(sorted(dag.roots())) or 'none'}",
        f"  Terminal effects: {', '.join(sorted(dag.leaves())) or 'none'}",
        "",
        "Edges (cause → effect):",
    ]

    for edge in sorted(dag.edges, key=lambda e: e.p_value):
        lines.append(
            f"  {edge.cause} → {edge.effect}"
            f"  (F={edge.f_statistic:.2f}, p={edge.p_value:.4f},"
            f" lag={edge.lag}, strength={edge.strength})"
        )

    if not dag.edges:
        lines.append("  No significant causal relationships found.")

    return "\n".join(lines)


@skill(
    pack="causal",
    description="Find root causes of a target metric's behavior by tracing backwards through the causal DAG.",
    category=SkillCategory.SYSTEM,
    cooldown=5.0,
    cost=2.0,
    tags=["causal", "root-cause", "observability"],
)
def causal_root_causes(
    target_metric: str,
    min_samples: int = 30,
    max_depth: int = 5,
) -> str:
    """Trace a metric back to its causal roots.

    Args:
        target_metric: The metric to analyze (e.g., "pipeline.latency_ms").
        min_samples: Minimum samples for DAG construction.
        max_depth: Maximum traversal depth.

    Returns:
        Root cause analysis with causal chains.
    """
    engine = _get_engine()
    result = engine.get_root_causes(
        target_metric,
        min_samples=min_samples,
        max_depth=max_depth,
    )

    lines = [
        f"Root Cause Analysis: {target_metric}",
        f"  Root causes found: {len(result.root_causes)}",
        "",
    ]

    if result.root_causes:
        for rc in result.root_causes:
            chain_str = " → ".join(rc["chain"])
            lines.append(
                f"  • {rc['metric']} (depth={rc['depth']}, "
                f"strength={rc['edge_strength']}, p={rc['edge_p_value']:.4f})"
            )
            lines.append(f"    Chain: {chain_str}")
    else:
        lines.append("  No root causes found in the causal DAG.")
        lines.append("  This metric may be a root node or have insufficient data.")

    return "\n".join(lines)


@skill(
    pack="causal",
    description="Predict downstream effects of intervening on a specific metric.",
    category=SkillCategory.SYSTEM,
    cooldown=5.0,
    cost=2.0,
    tags=["causal", "intervention", "prediction"],
)
def causal_analyze_intervention(
    metric: str,
    delta: float = 10.0,
    min_samples: int = 30,
    max_depth: int = 5,
) -> str:
    """Predict what happens downstream when a metric changes.

    Args:
        metric: The metric being changed (e.g., "system.cpu_pct").
        delta: Magnitude of the change (e.g., +10.0 means 10-unit increase).
        min_samples: Minimum samples for DAG construction.
        max_depth: Maximum cascade depth.

    Returns:
        Intervention analysis with predicted downstream effects.
    """
    engine = _get_engine()
    result = engine.analyze_intervention(
        metric,
        delta=delta,
        min_samples=min_samples,
        max_depth=max_depth,
    )

    lines = [
        f"Intervention Analysis: {metric} Δ{delta:+.1f}",
        f"  Total affected metrics: {result.total_affected}",
        "",
    ]

    if result.downstream_effects:
        lines.append("Downstream effects:")
        for effect in result.downstream_effects:
            lines.append(
                f"  • {effect['metric']} → estimated Δ{effect['estimated_delta']:+.3f}"
                f"  (via {effect['via']}, depth={effect['depth']},"
                f" strength={effect['edge_strength']}, lag={effect['edge_lag']})"
            )
    else:
        lines.append("  No downstream effects predicted.")

    return "\n".join(lines)


@skill(
    pack="causal",
    description="Get a summary of the causal analysis engine state — tracked metrics, tests run, DAG status.",
    category=SkillCategory.SYSTEM,
    cooldown=1.0,
    cost=0.5,
    tags=["causal", "summary", "status"],
)
def causal_summary() -> str:
    """Get current status of the causal analysis engine.

    Returns:
        Summary of tracked metrics, Granger tests run, and DAG status.
    """
    engine = _get_engine()
    summary = engine.causal_summary()

    lines = [
        "Causal Engine Summary",
        f"  Tracked metrics: {summary['tracked_metrics']}",
        f"  Total samples: {summary['total_samples']}",
        f"  Granger tests run: {summary['granger_tests_run']}",
        f"  DAGs built: {summary['dags_built']}",
        f"  Significance level: {summary['significance_level']}",
        f"  Max lag: {summary['max_lag']}",
    ]

    dag = summary.get("current_dag")
    if dag:
        lines.extend([
            "",
            "Current DAG:",
            f"  Nodes: {dag['node_count']}",
            f"  Edges: {dag['edge_count']}",
            f"  Roots: {', '.join(dag['roots']) or 'none'}",
            f"  Leaves: {', '.join(dag['leaves']) or 'none'}",
            f"  Built: {_ts(dag['build_timestamp'])}",
        ])

    strongest = engine.strongest_causes(limit=5)
    if strongest:
        lines.extend(["", "Strongest causal relationships:"])
        for edge in strongest:
            lines.append(
                f"  {edge['cause']} → {edge['effect']}"
                f" ({edge['strength']}, p={edge['p_value']:.4f})"
            )

    return "\n".join(lines)


@skill(
    pack="causal",
    description="Find the causal path between two metrics in the DAG, if one exists.",
    category=SkillCategory.SYSTEM,
    cooldown=2.0,
    cost=1.0,
    tags=["causal", "path", "trace"],
)
def causal_find_path(
    source: str,
    target: str,
) -> str:
    """Find shortest causal path between two metrics.

    Args:
        source: Starting metric.
        target: Destination metric.

    Returns:
        Causal path or message if no path exists.
    """
    engine = _get_engine()
    path = engine.causal_path(source, target)

    if path is None:
        return f"No causal path found from {source} to {target}."

    chain = " → ".join(path)
    return f"Causal path ({len(path) - 1} hops): {chain}"
