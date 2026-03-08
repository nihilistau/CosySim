"""Evaluation and metrics MCP skills.

Exposes benchmark results, training stats, data collector status, and
evaluation controls as MCP-accessible skills.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────


def _get_benchmark_runner():
    """Lazy import benchmark runner."""
    from training.benchmark_runner import get_benchmark_runner
    return get_benchmark_runner()


def _get_data_collector():
    """Lazy import data collector."""
    from training.data_collector import get_data_collector
    return get_data_collector()


def _get_training_flywheel():
    """Lazy import training flywheel."""
    from engine.nexus.training_flywheel import get_training_flywheel
    return get_training_flywheel()


def _get_nexus_client():
    """Lazy import nexus client."""
    from engine.nexus.client import get_nexus_client
    return get_nexus_client()


# ── Skills ───────────────────────────────────────────────────────────


@skill(
    pack="evaluation",
    description=(
        "Get the benchmark leaderboard showing the best score for each model "
        "type. Returns model types, scores, and promotion status."
    ),
    category="SYSTEM",
    tags=["benchmark", "leaderboard", "metrics", "training"],
    cooldown=5.0,
    cost=1.0,
)
def eval_leaderboard() -> str:
    """Get the current benchmark leaderboard.

    Returns:
        JSON-formatted leaderboard with best scores per model type.
    """
    try:
        runner = _get_benchmark_runner()
        board = runner.get_leaderboard()
        return json.dumps(board, indent=2, default=str)
    except Exception as exc:
        logger.warning("eval_leaderboard failed: %s", exc)
        return f"Leaderboard unavailable: {exc}"


@skill(
    pack="evaluation",
    description=(
        "Get benchmark history for a specific model type or all models. "
        "Shows score trends over time."
    ),
    category="SYSTEM",
    tags=["benchmark", "history", "trends", "training"],
    cooldown=5.0,
    cost=1.0,
)
def eval_history(model_type: str = "", limit: int = 10) -> str:
    """Get benchmark history.

    Args:
        model_type: Filter to a specific model type (empty = all).
        limit: Maximum number of results to return.

    Returns:
        JSON array of historical benchmark results.
    """
    try:
        runner = _get_benchmark_runner()
        history = runner.get_history(
            model_type=model_type or None,
            limit=limit,
        )
        return json.dumps(history, indent=2, default=str)
    except Exception as exc:
        logger.warning("eval_history failed: %s", exc)
        return f"History unavailable: {exc}"


@skill(
    pack="evaluation",
    description=(
        "Run benchmarks for a specific model type or all models. "
        "Auto-promotes winners if scores improve. Returns results."
    ),
    category="SYSTEM",
    tags=["benchmark", "run", "evaluate", "training"],
    cooldown=30.0,
    cost=5.0,
)
def eval_run_benchmark(model_type: str = "", auto_promote: bool = True) -> str:
    """Run benchmarks on fine-tuned models.

    Args:
        model_type: Specific model type to benchmark (empty = all).
        auto_promote: Whether to auto-promote if score improves.

    Returns:
        JSON benchmark results with scores and promotion status.
    """
    try:
        runner = _get_benchmark_runner()
        if model_type:
            result = runner.run(model_type, auto_promote=auto_promote)
            output = {
                "model_type": result.model_type,
                "accuracy": result.accuracy,
                "f1": result.f1,
                "aggregate_score": result.aggregate_score,
                "promoted": result.promoted,
                "latency_ms_avg": result.latency_ms_avg,
                "error": result.error,
            }
        else:
            results = runner.run_all(auto_promote=auto_promote)
            output = [
                {
                    "model_type": r.model_type,
                    "accuracy": r.accuracy,
                    "aggregate_score": r.aggregate_score,
                    "promoted": r.promoted,
                    "error": r.error,
                }
                for r in results
            ]
        return json.dumps(output, indent=2, default=str)
    except Exception as exc:
        logger.warning("eval_run_benchmark failed: %s", exc)
        return f"Benchmark run failed: {exc}"


@skill(
    pack="evaluation",
    description=(
        "Get current data collector stats showing how many training examples "
        "have been collected for each model type."
    ),
    category="SYSTEM",
    tags=["data", "collector", "stats", "training"],
    cooldown=2.0,
    cost=1.0,
)
def eval_collector_stats() -> str:
    """Get data collector statistics.

    Returns:
        JSON with live buffer sizes and total counts per model type.
    """
    try:
        collector = _get_data_collector()
        stats = collector.get_stats()
        return json.dumps(stats, indent=2, default=str)
    except Exception as exc:
        logger.warning("eval_collector_stats failed: %s", exc)
        return f"Collector stats unavailable: {exc}"


@skill(
    pack="evaluation",
    description=(
        "Flush collected training data from live buffers into training "
        "datasets. Optionally flush a specific model type or all types."
    ),
    category="SYSTEM",
    tags=["data", "flush", "export", "training"],
    cooldown=10.0,
    cost=2.0,
)
def eval_flush_data(model_type: str = "") -> str:
    """Flush collected data to training datasets.

    Args:
        model_type: Specific model type to flush (empty = all).

    Returns:
        JSON with flush counts per model type.
    """
    try:
        collector = _get_data_collector()
        if model_type:
            count = collector.flush(model_type)
            result = {model_type: count}
        else:
            result = collector.flush_all()
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        logger.warning("eval_flush_data failed: %s", exc)
        return f"Data flush failed: {exc}"


@skill(
    pack="evaluation",
    description=(
        "Get training flywheel statistics: total examples collected, "
        "quality distribution, source breakdown, and export status."
    ),
    category="SYSTEM",
    tags=["flywheel", "training", "stats", "quality"],
    cooldown=5.0,
    cost=1.0,
)
def eval_flywheel_stats() -> str:
    """Get training flywheel statistics.

    Returns:
        JSON with flywheel metrics: counts, quality distribution, sources.
    """
    try:
        flywheel = _get_training_flywheel()
        stats = flywheel.get_stats()
        return json.dumps(stats, indent=2, default=str)
    except Exception as exc:
        logger.warning("eval_flywheel_stats failed: %s", exc)
        return f"Flywheel stats unavailable: {exc}"


@skill(
    pack="evaluation",
    description=(
        "Store a benchmark result or evaluation metric in Nexus for "
        "historical tracking and trend analysis."
    ),
    category="SYSTEM",
    tags=["nexus", "store", "metrics", "benchmark"],
    cooldown=2.0,
    cost=1.0,
)
def eval_store_result(
    title: str,
    content: str,
    category: str = "benchmark",
) -> str:
    """Store an evaluation result in Nexus.

    Args:
        title: Title for the result entry.
        content: JSON or text content of the result.
        category: Nexus category (default: benchmark).

    Returns:
        Entry ID on success, or error message.
    """
    try:
        client = _get_nexus_client()
        entry_id = client.add_entry(
            title=title,
            content=content,
            content_type="history",
            category=category,
            tags=["benchmark", "evaluation", "metrics"],
        )
        if entry_id:
            return f"Stored in Nexus: {entry_id}"
        return "Failed to store in Nexus (no entry ID returned)"
    except Exception as exc:
        logger.warning("eval_store_result failed: %s", exc)
        return f"Nexus storage failed: {exc}"


@skill(
    pack="evaluation",
    description=(
        "Prune low-quality training examples from the data collector. "
        "Removes examples below the specified quality threshold."
    ),
    category="SYSTEM",
    tags=["data", "quality", "prune", "training"],
    cooldown=10.0,
    cost=2.0,
)
def eval_prune_low_quality(min_quality: float = 0.3) -> str:
    """Prune low-quality training data.

    Args:
        min_quality: Minimum quality threshold (0.0-1.0). Examples below
            this score are removed.

    Returns:
        Number of examples pruned.
    """
    try:
        collector = _get_data_collector()
        pruned = collector.prune_low_quality(min_quality)
        return f"Pruned {pruned} low-quality examples (threshold: {min_quality})"
    except Exception as exc:
        logger.warning("eval_prune_low_quality failed: %s", exc)
        return f"Pruning failed: {exc}"
