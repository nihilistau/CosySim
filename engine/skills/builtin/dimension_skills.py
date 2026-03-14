"""Dimensional metrics and Pareto model selection MCP skills."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


# ──── Lazy Service Accessors ─────────────────────────────────────────────────


def _get_dimension_store() -> Any:
    """Lazy import to avoid circular dependencies."""
    from engine.observability.metric_dimensions import get_dimension_store
    return get_dimension_store()


def _get_pareto_selector() -> Any:
    """Lazy import to avoid circular dependencies."""
    from engine.nexus.pareto_selector import get_pareto_selector
    return get_pareto_selector()


def _get_model_registry() -> Any:
    """Lazy import to avoid circular dependencies."""
    from training.model_registry import get_model_registry
    return get_model_registry()


def _model_objectives_to_dict(obj: Any) -> Dict[str, Any]:
    """Convert a ModelObjectives dataclass to a serialisable dict."""
    return asdict(obj)


def _ranked_list_to_dicts(
    ranked: List[Tuple[Any, float]],
) -> List[Dict[str, Any]]:
    """Convert a list of (ModelObjectives, score) tuples to dicts."""
    return [
        {"model": _model_objectives_to_dict(m), "score": round(s, 6)}
        for m, s in ranked
    ]


# ──── Dimensional Metrics Skills ─────────────────────────────────────────────


@skill(
    pack="model_ops",
    description="Record a dimensional metric with optional tags",
    category="system",
    tags=["metrics", "observability"],
    cooldown=0.0,
    cost=0.5,
)
def record_dimensional_metric(
    name: str,
    value: float,
    tags: str = "{}",
) -> str:
    """Record a single metric value with optional key/value dimension tags.

    Args:
        name: Metric name (e.g. ``"inference_latency_ms"``).
        value: Numeric value to record.
        tags: JSON string of ``{"key": "value"}`` tag dimensions.

    Returns:
        Confirmation string with the stored metric_id.
    """
    try:
        tags_dict: Dict[str, str] = json.loads(tags) if tags else {}
    except (json.JSONDecodeError, TypeError) as exc:
        return f"Error: invalid tags JSON — {exc}"

    try:
        store = _get_dimension_store()
        metric_id = store.record(name, value, tags=tags_dict)
        result = {
            "status": "recorded",
            "metric_id": metric_id,
            "name": name,
            "value": value,
            "tags": tags_dict,
        }
        logger.info("Recorded metric %s=%s (id=%s)", name, value, metric_id)
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        logger.warning("record_dimensional_metric failed: %s", exc)
        return f"Error: {exc}"


@skill(
    pack="model_ops",
    description="Query dimensional metrics with filtering and grouping",
    category="system",
    tags=["metrics", "observability", "query"],
    cooldown=1.0,
    cost=1.0,
)
def query_dimensional_metrics(
    name: str,
    filters: str = "{}",
    group_by: str = "",
    window_seconds: float = 3600,
) -> str:
    """Query stored metrics by name with optional tag filters and grouping.

    Args:
        name: Metric name to query.
        filters: JSON string of tag filters (e.g. ``{"model": "qwen3"}``).
        group_by: Comma-separated tag keys to group by (empty for raw).
        window_seconds: Look-back window in seconds (default 3600).

    Returns:
        JSON with aggregated groups or raw metric rows (max 50).
    """
    try:
        filter_dict: Dict[str, str] = json.loads(filters) if filters else {}
    except (json.JSONDecodeError, TypeError) as exc:
        return f"Error: invalid filters JSON — {exc}"

    try:
        group_keys: Optional[List[str]] = (
            [k.strip() for k in group_by.split(",") if k.strip()]
            if group_by
            else None
        )
        store = _get_dimension_store()
        results = store.query(
            name,
            filters=filter_dict,
            group_by=group_keys,
            window_seconds=window_seconds,
            limit=50,
        )

        if group_keys:
            payload = [asdict(r) for r in results]
        else:
            payload = [asdict(m) for m in results[:50]]

        return json.dumps(
            {"name": name, "count": len(payload), "results": payload},
            indent=2,
            default=str,
        )
    except Exception as exc:
        logger.warning("query_dimensional_metrics failed: %s", exc)
        return f"Error: {exc}"


@skill(
    pack="model_ops",
    description="Get tag cardinality statistics for dimensional metrics",
    category="system",
    tags=["metrics", "observability", "introspection"],
    cooldown=2.0,
    cost=0.5,
)
def get_tag_cardinality(metric_name: str = "") -> str:
    """Report cardinality statistics for each tag key.

    Args:
        metric_name: Restrict to tags on this metric (empty for all).

    Returns:
        JSON with cardinality records including key, unique_values,
        total_uses, and sample_values.
    """
    try:
        store = _get_dimension_store()
        cardinality = store.get_tag_cardinality(
            metric_name if metric_name else None,
        )
        payload = [asdict(c) for c in cardinality]
        return json.dumps(
            {"metric_name": metric_name or "(all)", "tags": payload},
            indent=2,
            default=str,
        )
    except Exception as exc:
        logger.warning("get_tag_cardinality failed: %s", exc)
        return f"Error: {exc}"


@skill(
    pack="model_ops",
    description="Get aggregate summary statistics for a named metric",
    category="system",
    tags=["metrics", "observability", "summary"],
    cooldown=2.0,
    cost=0.5,
)
def get_metric_dimensions_summary(metric_name: str) -> str:
    """Compute aggregate statistics for a named metric.

    Args:
        metric_name: The metric to summarise.

    Returns:
        JSON with count, mean, min, max, stddev, and percentiles
        (p50, p95, p99).
    """
    try:
        store = _get_dimension_store()
        summary = store.get_summary(metric_name)
        if not summary:
            return json.dumps(
                {"metric_name": metric_name, "status": "no_data"},
                indent=2,
            )
        summary["metric_name"] = metric_name
        return json.dumps(summary, indent=2, default=str)
    except Exception as exc:
        logger.warning("get_metric_dimensions_summary failed: %s", exc)
        return f"Error: {exc}"


# ──── Pareto Selection Skills ────────────────────────────────────────────────


@skill(
    pack="model_ops",
    description="Compute the Pareto-optimal frontier for a model type",
    category="system",
    tags=["pareto", "model-selection"],
    cooldown=5.0,
    cost=2.0,
)
def compute_pareto_frontier(
    model_type: str,
    context: str = "balanced",
) -> str:
    """Compute the Pareto-optimal frontier for registered models.

    Args:
        model_type: Model type to analyse (e.g. ``"chat"``, ``"code"``).
        context: Selection context preset name.

    Returns:
        JSON with frontier models, dominated models, total candidates,
        and rankings.
    """
    try:
        registry = _get_model_registry()
        frontier_result = registry.get_pareto_frontier(model_type, context)
        return json.dumps(frontier_result, indent=2, default=str)
    except Exception as exc:
        logger.warning("compute_pareto_frontier failed: %s", exc)
        return f"Error: {exc}"


@skill(
    pack="model_ops",
    description="Rank models using multi-criteria strategies",
    category="system",
    tags=["pareto", "model-selection", "ranking"],
    cooldown=5.0,
    cost=2.0,
)
def rank_models_multi_criteria(
    model_type: str,
    strategy: str = "weighted_sum",
    context: str = "balanced",
) -> str:
    """Rank registered models using a multi-criteria strategy.

    Args:
        model_type: Model type to rank.
        strategy: Ranking strategy — one of ``weighted_sum``,
            ``tchebycheff``, ``pareto_rank``, ``knee_point``.
        context: Selection context preset name.

    Returns:
        JSON with ranked list of ``{model, score}`` entries sorted
        by score descending.
    """
    try:
        registry = _get_model_registry()
        selector = _get_pareto_selector()
        models = registry.list_models(model_type=model_type)
        if not models:
            return json.dumps(
                {"model_type": model_type, "count": 0, "rankings": []},
                indent=2,
            )

        objectives = registry._to_model_objectives(models)
        ranked = selector.rank_models(
            objectives, strategy=strategy, context=context,
        )
        payload = {
            "model_type": model_type,
            "strategy": strategy,
            "context": context,
            "count": len(ranked),
            "rankings": _ranked_list_to_dicts(ranked),
        }
        return json.dumps(payload, indent=2, default=str)
    except Exception as exc:
        logger.warning("rank_models_multi_criteria failed: %s", exc)
        return f"Error: {exc}"


@skill(
    pack="model_ops",
    description="List available Pareto selection context presets",
    category="system",
    tags=["pareto", "model-selection", "contexts"],
    cooldown=2.0,
    cost=0.5,
)
def list_selection_contexts() -> str:
    """List all registered selection context presets with descriptions.

    Returns:
        JSON with context objects including name, description, and
        objective summaries.
    """
    try:
        selector = _get_pareto_selector()
        context_names = selector.list_contexts()
        contexts: List[Dict[str, Any]] = []
        for ctx_name in context_names:
            ctx = selector.get_context(ctx_name)
            obj_summaries = [
                {
                    "name": o.name,
                    "direction": o.direction,
                    "weight": o.weight,
                }
                for o in ctx.objectives
            ]
            contexts.append({
                "name": ctx.name,
                "description": ctx.description,
                "objectives": obj_summaries,
            })
        return json.dumps(
            {"count": len(contexts), "contexts": contexts},
            indent=2,
            default=str,
        )
    except Exception as exc:
        logger.warning("list_selection_contexts failed: %s", exc)
        return f"Error: {exc}"


@skill(
    pack="model_ops",
    description="Recommend the single best model for a type and context",
    category="system",
    tags=["pareto", "model-selection", "recommendation"],
    cooldown=5.0,
    cost=2.0,
)
def recommend_model(
    model_type: str,
    context: str = "balanced",
) -> str:
    """Recommend the best model for a given type using Pareto analysis.

    Args:
        model_type: Model type to evaluate.
        context: Selection context preset name.

    Returns:
        JSON with the recommended model details, or a no-candidates
        message.
    """
    try:
        registry = _get_model_registry()
        selector = _get_pareto_selector()
        models = registry.list_models(model_type=model_type)
        if not models:
            return json.dumps(
                {
                    "model_type": model_type,
                    "context": context,
                    "recommendation": None,
                    "reason": "No candidates found for this model type.",
                },
                indent=2,
            )

        objectives = registry._to_model_objectives(models)
        best = selector.recommend(objectives, context=context)
        if best is None:
            return json.dumps(
                {
                    "model_type": model_type,
                    "context": context,
                    "recommendation": None,
                    "reason": (
                        "All candidates were filtered out by hard "
                        "thresholds in the selected context."
                    ),
                },
                indent=2,
            )

        return json.dumps(
            {
                "model_type": model_type,
                "context": context,
                "recommendation": _model_objectives_to_dict(best),
            },
            indent=2,
            default=str,
        )
    except Exception as exc:
        logger.warning("recommend_model failed: %s", exc)
        return f"Error: {exc}"


# ──── Multi-Criteria Promotion Skills ────────────────────────────────────────


@skill(
    pack="model_ops",
    description="Promote the best model using multi-criteria Pareto selection",
    category="system",
    tags=["pareto", "promotion", "model-ops"],
    cooldown=10.0,
    cost=3.0,
)
def promote_model_multi_criteria(
    model_type: str,
    strategy: str = "weighted_sum",
    context: str = "balanced",
) -> str:
    """Promote the best model to active status using multi-criteria selection.

    Args:
        model_type: Model type to promote (e.g. ``"chat"``).
        strategy: Ranking strategy — one of ``weighted_sum``,
            ``tchebycheff``, ``pareto_rank``, ``knee_point``.
        context: Selection context preset name.

    Returns:
        JSON with promoted model id, score, strategy, context, and
        frontier size — or a status message if no candidates exist.
    """
    try:
        registry = _get_model_registry()
        result = registry.promote_multi_criteria(
            model_type, strategy=strategy, context=context,
        )
        if result is None:
            return json.dumps(
                {
                    "model_type": model_type,
                    "strategy": strategy,
                    "context": context,
                    "status": "no_candidates",
                    "message": "No models available for promotion.",
                },
                indent=2,
            )

        result["status"] = "promoted"
        logger.info(
            "Promoted model %s (strategy=%s, context=%s, score=%.4f)",
            result.get("promoted_model_id"),
            strategy,
            context,
            result.get("promoted_score", 0),
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        logger.warning("promote_model_multi_criteria failed: %s", exc)
        return f"Error: {exc}"


@skill(
    pack="model_ops",
    description="Explain available multi-criteria ranking strategies",
    category="system",
    tags=["pareto", "promotion", "help"],
    cooldown=0.0,
    cost=0.0,
)
def get_promotion_strategy_info(strategy: str = "weighted_sum") -> str:
    """Describe available multi-criteria ranking strategies and their uses.

    Args:
        strategy: Strategy to get detailed info for.  Pass ``"all"``
            for a full overview.

    Returns:
        JSON with strategy descriptions, trade-offs, and guidance.
    """
    strategies: Dict[str, Dict[str, str]] = {
        "weighted_sum": {
            "name": "Weighted Sum",
            "description": (
                "Scalarises objectives into a single score using context "
                "weights.  Fast and intuitive — good default for most cases."
            ),
            "best_for": (
                "General-purpose ranking where objectives have clear "
                "relative importance."
            ),
            "trade_offs": (
                "Cannot discover solutions in non-convex regions of the "
                "Pareto frontier."
            ),
        },
        "tchebycheff": {
            "name": "Tchebycheff (Chebyshev)",
            "description": (
                "Minimises the worst-case weighted deviation from the "
                "ideal point.  Explores non-convex frontier regions."
            ),
            "best_for": (
                "Scenarios where no single objective should be neglected "
                "— ensures balanced trade-offs."
            ),
            "trade_offs": (
                "Requires well-defined ideal and nadir points; sensitive "
                "to objective scaling."
            ),
        },
        "pareto_rank": {
            "name": "Pareto Rank (Non-Dominated Sorting)",
            "description": (
                "Assigns rank by layer of non-dominated sorting (NSGA-II "
                "style).  Models on the first frontier get rank 1."
            ),
            "best_for": (
                "Understanding dominance structure without committing to "
                "specific weights."
            ),
            "trade_offs": (
                "Coarse ranking — many models may share the same rank on "
                "small frontiers."
            ),
        },
        "knee_point": {
            "name": "Knee Point",
            "description": (
                "Identifies the 'knee' of the Pareto frontier — the "
                "point of maximum marginal return.  Ranks by proximity "
                "to that knee."
            ),
            "best_for": (
                "Finding the sweet-spot model that balances all "
                "objectives without over-optimising any single one."
            ),
            "trade_offs": (
                "Knee detection can be ambiguous with few candidates or "
                "high-dimensional objective spaces."
            ),
        },
    }

    if strategy == "all":
        payload: Dict[str, Any] = {
            "count": len(strategies),
            "strategies": strategies,
        }
    elif strategy in strategies:
        payload = strategies[strategy]
    else:
        payload = {
            "error": f"Unknown strategy '{strategy}'.",
            "available": list(strategies.keys()),
        }

    return json.dumps(payload, indent=2, default=str)
