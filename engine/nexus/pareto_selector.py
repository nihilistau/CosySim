"""
Pareto Selector — Multi-objective model selection for CosySim.

Computes Pareto frontiers, applies scalarization methods, and ranks models
across multiple objective dimensions (accuracy, latency, cost, throughput,
etc.).  Supports context-aware presets so different deployment scenarios
(interactive, batch, cost-sensitive) produce different rankings without
manual weight tuning.

Pure Python — no numpy, scipy, or external math libraries.

Usage:
    from engine.nexus.pareto_selector import get_pareto_selector, ModelObjectives

    selector = get_pareto_selector()

    models = [
        ModelObjectives("gpt4", "qa_evaluator", accuracy=0.95, latency_p50_ms=120),
        ModelObjectives("llama3", "qa_evaluator", accuracy=0.88, latency_p50_ms=45),
        ModelObjectives("qwen3", "qa_evaluator", accuracy=0.91, latency_p50_ms=60),
    ]

    # Quick recommendation
    best = selector.recommend(models, context="latency_sensitive")

    # Full Pareto analysis
    result = selector.compute_frontier(models, context="balanced")
    for m, score in result.rankings:
        print(f"{m.model_id}: {score:.4f}")

    # Custom ranking strategy
    ranked = selector.rank_models(models, strategy="knee_point", context="balanced")
"""
from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class ModelObjectives:
    """Typed benchmark metrics for a model.

    Attributes:
        model_id:  Unique identifier for the model.
        model_type:  Logical role, e.g. ``"qa_evaluator"``, ``"router_v2"``.
        accuracy:  Fraction correct, 0-1 (maximize).
        latency_p50_ms:  Median latency in milliseconds (minimize).
        latency_p95_ms:  95th-percentile latency in milliseconds (minimize).
        cost_per_1k_tokens:  Cost per 1 000 tokens (minimize).
        throughput_rps:  Requests per second (maximize).
        error_rate:  Fraction of failed requests, 0-1 (minimize).
        memory_mb:  Peak memory footprint in megabytes (minimize).
        custom:  Extensible bag for objectives not in the standard set.
    """

    model_id: str
    model_type: str
    accuracy: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    cost_per_1k_tokens: float = 0.0
    throughput_rps: float = 0.0
    error_rate: float = 0.0
    memory_mb: float = 0.0
    custom: Dict[str, float] = field(default_factory=dict)


@dataclass
class ObjectiveConfig:
    """Configuration for a single objective dimension.

    Attributes:
        name:  Field name in :class:`ModelObjectives` (or a key in ``custom``).
        direction:  ``"maximize"`` or ``"minimize"``.
        weight:  Relative importance for scalarization (default 1.0).
        ideal:  Utopia point for Tchebycheff methods.
        nadir:  Worst acceptable point for Tchebycheff methods.
        threshold:  Hard constraint — models violating it are excluded.
    """

    name: str
    direction: str
    weight: float = 1.0
    ideal: Optional[float] = None
    nadir: Optional[float] = None
    threshold: Optional[float] = None


@dataclass
class SelectionContext:
    """Named preset that bundles objective configs for a deployment scenario.

    Attributes:
        name:  Preset identifier (e.g. ``"balanced"``).
        description:  Human-readable explanation.
        objectives:  Ordered list of objective configurations.
    """

    name: str
    description: str
    objectives: List[ObjectiveConfig]


@dataclass
class ParetoResult:
    """Result of a Pareto frontier computation.

    Attributes:
        frontier:  Non-dominated models.
        dominated:  Dominated models.
        rankings:  All surviving models ranked by score (highest first).
        strategy:  Scalarization / ranking strategy used.
        context:  Name of the context preset applied.
    """

    frontier: List[ModelObjectives]
    dominated: List[ModelObjectives]
    rankings: List[Tuple[ModelObjectives, float]]
    strategy: str
    context: str


# ──── Default Directions ───────────────────────────────────────────────────────

_DEFAULT_DIRECTIONS: Dict[str, str] = {
    "accuracy": "maximize",
    "latency_p50_ms": "minimize",
    "latency_p95_ms": "minimize",
    "cost_per_1k_tokens": "minimize",
    "throughput_rps": "maximize",
    "error_rate": "minimize",
    "memory_mb": "minimize",
}

# Small epsilon used by augmented Tchebycheff to break ties.
_AUGMENTED_EPSILON: float = 1e-4


# ──── Built-in Context Presets ─────────────────────────────────────────────────

CONTEXT_PRESETS: Dict[str, SelectionContext] = {
    "balanced": SelectionContext(
        name="balanced",
        description="Equal weight to all objectives",
        objectives=[
            ObjectiveConfig(name=k, direction=v)
            for k, v in _DEFAULT_DIRECTIONS.items()
        ],
    ),
    "latency_sensitive": SelectionContext(
        name="latency_sensitive",
        description="Prioritize low latency (mobile, interactive)",
        objectives=[
            ObjectiveConfig("accuracy", "maximize", weight=0.3),
            ObjectiveConfig("latency_p50_ms", "minimize", weight=2.0),
            ObjectiveConfig("latency_p95_ms", "minimize", weight=2.0),
            ObjectiveConfig("cost_per_1k_tokens", "minimize", weight=0.5),
            ObjectiveConfig("throughput_rps", "maximize", weight=1.5),
            ObjectiveConfig("error_rate", "minimize", weight=1.0),
        ],
    ),
    "accuracy_critical": SelectionContext(
        name="accuracy_critical",
        description="Prioritize accuracy (critical tasks, research)",
        objectives=[
            ObjectiveConfig("accuracy", "maximize", weight=3.0),
            ObjectiveConfig("latency_p50_ms", "minimize", weight=0.3),
            ObjectiveConfig("latency_p95_ms", "minimize", weight=0.3),
            ObjectiveConfig("cost_per_1k_tokens", "minimize", weight=0.5),
            ObjectiveConfig("error_rate", "minimize", weight=2.0),
        ],
    ),
    "cost_efficient": SelectionContext(
        name="cost_efficient",
        description="Minimize cost (batch processing, background)",
        objectives=[
            ObjectiveConfig("accuracy", "maximize", weight=0.5),
            ObjectiveConfig("cost_per_1k_tokens", "minimize", weight=3.0),
            ObjectiveConfig("memory_mb", "minimize", weight=2.0),
            ObjectiveConfig("throughput_rps", "maximize", weight=1.5),
        ],
    ),
    "throughput_max": SelectionContext(
        name="throughput_max",
        description="Maximize throughput (high-volume serving)",
        objectives=[
            ObjectiveConfig("accuracy", "maximize", weight=0.5),
            ObjectiveConfig("throughput_rps", "maximize", weight=3.0),
            ObjectiveConfig("latency_p50_ms", "minimize", weight=1.0),
            ObjectiveConfig("memory_mb", "minimize", weight=1.0),
        ],
    ),
}


# ──── ParetoSelector ───────────────────────────────────────────────────────────


class ParetoSelector:
    """Multi-objective model selector with Pareto frontier computation.

    Thread-safe.  Use the :func:`get_pareto_selector` singleton accessor
    rather than instantiating directly.

    Supports four ranking strategies:

    * **weighted_sum** — classic linear scalarization.
    * **tchebycheff** — min-max deviation from ideal point.
    * **pareto_rank** — non-dominated sorting layers (NSGA-II style).
    * **knee_point** — identifies the frontier model at maximum curvature.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._contexts: Dict[str, SelectionContext] = dict(CONTEXT_PRESETS)
        logger.debug("ParetoSelector initialised with %d presets", len(self._contexts))

    # ── Context management ────────────────────────────────────────────────

    def get_context(self, name: str) -> SelectionContext:
        """Return a registered context preset by name.

        Args:
            name: Preset identifier.

        Returns:
            The matching :class:`SelectionContext`.

        Raises:
            KeyError: If no preset with *name* is registered.
        """
        with self._lock:
            if name not in self._contexts:
                available = ", ".join(sorted(self._contexts))
                raise KeyError(
                    f"Unknown context '{name}'. Available: {available}"
                )
            return self._contexts[name]

    def list_contexts(self) -> List[str]:
        """Return sorted list of registered context preset names."""
        with self._lock:
            return sorted(self._contexts.keys())

    def add_context(self, context: SelectionContext) -> None:
        """Register (or replace) a custom context preset.

        Args:
            context: The preset to register.
        """
        with self._lock:
            self._contexts[context.name] = context
            logger.info("Registered context preset '%s'", context.name)

    # ── Objective helpers (private) ───────────────────────────────────────

    def _get_objective_value(self, model: ModelObjectives, obj_name: str) -> float:
        """Extract a single objective value from *model*.

        Looks up standard fields first, then falls back to ``model.custom``.

        Args:
            model: The model record.
            obj_name: Field name or custom key.

        Returns:
            The numeric value, or ``0.0`` if the key is absent.
        """
        if hasattr(model, obj_name) and obj_name != "custom":
            return float(getattr(model, obj_name))
        return float(model.custom.get(obj_name, 0.0))

    def _apply_thresholds(
        self,
        models: List[ModelObjectives],
        objectives: List[ObjectiveConfig],
    ) -> List[ModelObjectives]:
        """Remove models that violate any hard threshold.

        For *maximize* objectives the value must be ``>= threshold``.
        For *minimize* objectives the value must be ``<= threshold``.

        Args:
            models: Candidate models.
            objectives: Objective configs (only those with a threshold set).

        Returns:
            Filtered list of models that satisfy all thresholds.
        """
        constrained = [obj for obj in objectives if obj.threshold is not None]
        if not constrained:
            return list(models)

        surviving: List[ModelObjectives] = []
        for model in models:
            passes = True
            for obj in constrained:
                val = self._get_objective_value(model, obj.name)
                if obj.direction == "maximize" and val < obj.threshold:  # type: ignore[operator]
                    logger.debug(
                        "Model '%s' excluded: %s=%.4f < threshold %.4f",
                        model.model_id, obj.name, val, obj.threshold,
                    )
                    passes = False
                    break
                if obj.direction == "minimize" and val > obj.threshold:  # type: ignore[operator]
                    logger.debug(
                        "Model '%s' excluded: %s=%.4f > threshold %.4f",
                        model.model_id, obj.name, val, obj.threshold,
                    )
                    passes = False
                    break
            if passes:
                surviving.append(model)

        if len(surviving) < len(models):
            logger.info(
                "Threshold filtering: %d → %d models",
                len(models), len(surviving),
            )
        return surviving

    def _normalize_objectives(
        self,
        models: List[ModelObjectives],
        objectives: List[ObjectiveConfig],
    ) -> List[Dict[str, float]]:
        """Normalize all objective values to 0-1 where higher is always better.

        For *maximize* objectives: ``norm = (val - min) / (max - min)``.
        For *minimize* objectives: ``norm = (max - val) / (max - min)``.
        Constant dimensions (zero range) map to ``1.0`` for all models.

        Args:
            models: Models to normalize.
            objectives: Which objectives to include.

        Returns:
            One dict per model, keyed by objective name, values in [0, 1].
        """
        if not models:
            return []

        # Collect raw values per objective
        raw: Dict[str, List[float]] = {}
        for obj in objectives:
            raw[obj.name] = [
                self._get_objective_value(m, obj.name) for m in models
            ]

        # Compute per-objective min/max
        ranges: Dict[str, Tuple[float, float]] = {}
        for obj in objectives:
            vals = raw[obj.name]
            lo = min(vals)
            hi = max(vals)
            ranges[obj.name] = (lo, hi)

        # Build normalized dicts
        result: List[Dict[str, float]] = []
        for i in range(len(models)):
            normed: Dict[str, float] = {}
            for obj in objectives:
                lo, hi = ranges[obj.name]
                val = raw[obj.name][i]
                span = hi - lo
                if span < 1e-12:
                    # All models have the same value — treat as ideal.
                    normed[obj.name] = 1.0
                elif obj.direction == "maximize":
                    normed[obj.name] = (val - lo) / span
                else:
                    normed[obj.name] = (hi - val) / span
            result.append(normed)
        return result

    # ── Dominance ─────────────────────────────────────────────────────────

    def dominates(
        self,
        a: ModelObjectives,
        b: ModelObjectives,
        objectives: List[ObjectiveConfig],
    ) -> bool:
        """Test whether model *a* Pareto-dominates model *b*.

        *a* dominates *b* iff *a* is at least as good as *b* in every
        objective and strictly better in at least one.

        Args:
            a: Candidate dominator.
            b: Candidate dominated.
            objectives: Objective dimensions to consider.

        Returns:
            ``True`` if *a* dominates *b*.
        """
        at_least_as_good = True
        strictly_better = False

        for obj in objectives:
            val_a = self._get_objective_value(a, obj.name)
            val_b = self._get_objective_value(b, obj.name)

            if obj.direction == "maximize":
                if val_a < val_b:
                    at_least_as_good = False
                    break
                if val_a > val_b:
                    strictly_better = True
            else:  # minimize
                if val_a > val_b:
                    at_least_as_good = False
                    break
                if val_a < val_b:
                    strictly_better = True

        return at_least_as_good and strictly_better

    # ── Pareto frontier ───────────────────────────────────────────────────

    def compute_frontier(
        self,
        models: List[ModelObjectives],
        objectives: Optional[List[ObjectiveConfig]] = None,
        context: str = "balanced",
    ) -> ParetoResult:
        """Compute the Pareto-optimal frontier from *models*.

        Steps:
        1. Resolve objectives from *context* if not explicitly supplied.
        2. Apply hard thresholds (exclude violators).
        3. O(n²) pairwise dominance check to extract the non-dominated set.
        4. Rank all surviving models via weighted-sum scalarization.

        Args:
            models: Candidate models.
            objectives: Explicit objective configs (overrides context).
            context: Name of a registered :class:`SelectionContext` preset.

        Returns:
            A :class:`ParetoResult` with frontier, dominated, and rankings.
        """
        if not models:
            return ParetoResult(
                frontier=[], dominated=[], rankings=[],
                strategy="weighted_sum", context=context,
            )

        ctx = self.get_context(context)
        objs = objectives if objectives is not None else ctx.objectives

        # Threshold filtering
        surviving = self._apply_thresholds(models, objs)
        if not surviving:
            logger.warning(
                "All %d models eliminated by threshold constraints", len(models),
            )
            return ParetoResult(
                frontier=[], dominated=[], rankings=[],
                strategy="weighted_sum", context=context,
            )

        # Non-dominated sorting (first layer only)
        dominated_set: set[int] = set()
        n = len(surviving)
        for i in range(n):
            if i in dominated_set:
                continue
            for j in range(n):
                if i == j or j in dominated_set:
                    continue
                if self.dominates(surviving[j], surviving[i], objs):
                    dominated_set.add(i)
                    break

        frontier = [surviving[i] for i in range(n) if i not in dominated_set]
        dominated = [surviving[i] for i in range(n) if i in dominated_set]

        logger.info(
            "Pareto frontier: %d non-dominated / %d dominated (of %d surviving)",
            len(frontier), len(dominated), n,
        )

        # Rank all surviving models
        rankings = self.rank_models(
            surviving, strategy="weighted_sum", context=context,
            custom_objectives=objs,
        )

        return ParetoResult(
            frontier=frontier,
            dominated=dominated,
            rankings=rankings,
            strategy="weighted_sum",
            context=context,
        )

    # ── Scalarization ─────────────────────────────────────────────────────

    def scalarize(
        self,
        model: ModelObjectives,
        objectives: List[ObjectiveConfig],
        method: str = "weighted_sum",
        normalized_cache: Optional[Dict[str, float]] = None,
        all_normalized: Optional[List[Dict[str, float]]] = None,
        model_index: Optional[int] = None,
    ) -> float:
        """Scalarize multi-objective values into a single score.

        Three methods are supported:

        * **weighted_sum** — ``Σ(w_i × norm_i)``, higher is better.
        * **tchebycheff** — ``-max(w_i × |norm_i - ideal_i|)``, negated so
          that higher is better (smaller deviation → higher score).
        * **augmented_tchebycheff** — Tchebycheff + ε·Σ(w_i × |norm_i -
          ideal_i|) to break ties.  Also negated.

        When called from :meth:`rank_models`, pre-computed normalized values
        are passed via *normalized_cache* to avoid redundant work.  When
        called standalone the method normalizes a single-element list (the
        model maps to a constant 1.0 on every dimension, which is only
        useful for the weighted-sum case — for Tchebycheff, prefer calling
        :meth:`rank_models` instead).

        Args:
            model: Target model.
            objectives: Objective configurations.
            method: ``"weighted_sum"``, ``"tchebycheff"``, or
                ``"augmented_tchebycheff"``.
            normalized_cache: Pre-computed normalized values for *model*.
            all_normalized: Pre-computed normalized values for all models
                (only used to derive ideal/nadir when not specified).
            model_index: Index of *model* in *all_normalized*.

        Returns:
            Scalar score (higher is better regardless of method).

        Raises:
            ValueError: If *method* is not recognised.
        """
        valid_methods = ("weighted_sum", "tchebycheff", "augmented_tchebycheff")
        if method not in valid_methods:
            raise ValueError(
                f"Unknown scalarization method '{method}'. "
                f"Valid: {', '.join(valid_methods)}"
            )

        # Resolve normalized values
        if normalized_cache is not None:
            normed = normalized_cache
        else:
            # Standalone call — normalize in isolation (best-effort).
            single = self._normalize_objectives([model], objectives)
            normed = single[0] if single else {}

        total_weight = sum(obj.weight for obj in objectives) or 1.0

        if method == "weighted_sum":
            score = 0.0
            for obj in objectives:
                w = obj.weight / total_weight
                score += w * normed.get(obj.name, 0.0)
            return score

        # ── Tchebycheff family ────────────────────────────────────────────
        # Ideal point: best normalised value per objective across the set.
        # If ObjectiveConfig provides explicit ideal/nadir we project those
        # into normalised space; otherwise we take the set extremes.
        ideals: Dict[str, float] = {}
        for obj in objectives:
            if obj.ideal is not None and all_normalized is not None:
                # Project the raw ideal into [0,1] using the same scale that
                # produced all_normalized.  Since we don't carry the raw
                # range here we approximate: ideal ≈ 1.0 (best possible).
                ideals[obj.name] = 1.0
            elif all_normalized:
                ideals[obj.name] = max(
                    n.get(obj.name, 0.0) for n in all_normalized
                )
            else:
                ideals[obj.name] = 1.0

        max_dev = -1.0
        sum_dev = 0.0
        for obj in objectives:
            w = obj.weight / total_weight
            ideal = ideals.get(obj.name, 1.0)
            deviation = abs(normed.get(obj.name, 0.0) - ideal)
            weighted_dev = w * deviation
            if weighted_dev > max_dev:
                max_dev = weighted_dev
            sum_dev += weighted_dev

        if method == "tchebycheff":
            # Negate so higher = better.
            return -max_dev

        # augmented_tchebycheff
        return -(max_dev + _AUGMENTED_EPSILON * sum_dev)

    # ── Ranking ───────────────────────────────────────────────────────────

    def rank_models(
        self,
        models: List[ModelObjectives],
        strategy: str = "weighted_sum",
        context: str = "balanced",
        custom_objectives: Optional[List[ObjectiveConfig]] = None,
    ) -> List[Tuple[ModelObjectives, float]]:
        """Rank *models* using *strategy* within *context*.

        Strategies:

        * **weighted_sum** / **tchebycheff** — scalarize then sort.
        * **pareto_rank** — assign rank by non-dominated sorting layer
          (frontier = rank 0, next layer = rank 1, …).  Score is ``-rank``
          (so rank 0 → score 0, rank 1 → score -1).
        * **knee_point** — identify the knee of the frontier, then
          sort by Euclidean distance to that knee in normalised space
          (closer → higher score).

        Args:
            models: Candidate models.
            strategy: Ranking strategy name.
            context: Registered context preset name.
            custom_objectives: Override objectives (instead of context's).

        Returns:
            List of ``(model, score)`` tuples sorted descending by score.

        Raises:
            ValueError: If *strategy* is unknown.
        """
        valid_strategies = (
            "weighted_sum", "tchebycheff", "augmented_tchebycheff",
            "pareto_rank", "knee_point",
        )
        if strategy not in valid_strategies:
            raise ValueError(
                f"Unknown strategy '{strategy}'. "
                f"Valid: {', '.join(valid_strategies)}"
            )

        if not models:
            return []

        ctx = self.get_context(context)
        objs = custom_objectives if custom_objectives is not None else ctx.objectives

        surviving = self._apply_thresholds(models, objs)
        if not surviving:
            return []

        all_normed = self._normalize_objectives(surviving, objs)

        # ── Scalarization strategies ──────────────────────────────────────
        if strategy in ("weighted_sum", "tchebycheff", "augmented_tchebycheff"):
            scored: List[Tuple[ModelObjectives, float]] = []
            for idx, model in enumerate(surviving):
                s = self.scalarize(
                    model, objs, method=strategy,
                    normalized_cache=all_normed[idx],
                    all_normalized=all_normed,
                    model_index=idx,
                )
                scored.append((model, s))
            scored.sort(key=lambda t: t[1], reverse=True)
            return scored

        # ── Pareto rank (non-dominated sorting layers) ────────────────────
        if strategy == "pareto_rank":
            return self._pareto_rank(surviving, objs)

        # ── Knee point ────────────────────────────────────────────────────
        return self._knee_point_rank(surviving, objs, all_normed)

    def _pareto_rank(
        self,
        models: List[ModelObjectives],
        objectives: List[ObjectiveConfig],
    ) -> List[Tuple[ModelObjectives, float]]:
        """Assign ranks via iterative non-dominated sorting.

        Layer 0 = Pareto frontier of the full set.  Remove layer 0, repeat
        to find layer 1, etc.  Score = ``-layer`` (so layer 0 is best).
        Within the same layer, models are sub-sorted by weighted-sum.

        Args:
            models: Pre-filtered candidate models.
            objectives: Objective configs.

        Returns:
            Ranked list of ``(model, score)`` tuples.
        """
        remaining_indices: List[int] = list(range(len(models)))
        rank_map: Dict[int, int] = {}
        current_rank = 0

        while remaining_indices:
            # Find non-dominated subset of the remaining pool
            dominated_in_layer: set[int] = set()
            for i in remaining_indices:
                if i in dominated_in_layer:
                    continue
                for j in remaining_indices:
                    if i == j or j in dominated_in_layer:
                        continue
                    if self.dominates(models[j], models[i], objectives):
                        dominated_in_layer.add(i)
                        break

            layer = [i for i in remaining_indices if i not in dominated_in_layer]
            for i in layer:
                rank_map[i] = current_rank

            remaining_indices = [i for i in remaining_indices if i in dominated_in_layer]
            current_rank += 1

        # Sub-sort within each rank using weighted_sum for determinism
        all_normed = self._normalize_objectives(models, objectives)
        total_weight = sum(obj.weight for obj in objectives) or 1.0

        def _ws_score(idx: int) -> float:
            score = 0.0
            for obj in objectives:
                w = obj.weight / total_weight
                score += w * all_normed[idx].get(obj.name, 0.0)
            return score

        scored: List[Tuple[ModelObjectives, float]] = []
        for idx in range(len(models)):
            rank = rank_map[idx]
            # Primary key: rank (lower is better → negated).
            # Secondary key: weighted-sum score within the rank (0-1).
            # Combined so that rank 0 always beats rank 1.
            combined = -float(rank) + _ws_score(idx) * 0.01
            scored.append((models[idx], combined))

        scored.sort(key=lambda t: t[1], reverse=True)
        return scored

    def _knee_point_rank(
        self,
        models: List[ModelObjectives],
        objectives: List[ObjectiveConfig],
        all_normed: List[Dict[str, float]],
    ) -> List[Tuple[ModelObjectives, float]]:
        """Rank by proximity to the knee point of the Pareto frontier.

        1. Extract frontier.
        2. Find the knee model via :meth:`find_knee_point`.
        3. Score all models by negative Euclidean distance to the knee in
           normalised space (closer → higher score).

        Args:
            models: Pre-filtered candidate models.
            objectives: Objective configs.
            all_normed: Pre-computed normalised values.

        Returns:
            Ranked list of ``(model, score)`` tuples.
        """
        knee = self.find_knee_point(models, objectives)
        if knee is None:
            # Fallback to weighted_sum if no knee can be identified.
            return self.rank_models(
                models, strategy="weighted_sum",
                custom_objectives=objectives,
            )

        # Find the normalised vector for the knee model.
        knee_idx: Optional[int] = None
        for idx, m in enumerate(models):
            if m is knee:
                knee_idx = idx
                break
        if knee_idx is None:
            # Shouldn't happen, but safeguard.
            knee_idx = 0

        knee_normed = all_normed[knee_idx]

        scored: List[Tuple[ModelObjectives, float]] = []
        for idx, m in enumerate(models):
            dist = self._euclidean_normed(all_normed[idx], knee_normed, objectives)
            scored.append((m, -dist))  # closer → higher score

        scored.sort(key=lambda t: t[1], reverse=True)
        return scored

    # ── Knee point ────────────────────────────────────────────────────────

    def find_knee_point(
        self,
        models: List[ModelObjectives],
        objectives: List[ObjectiveConfig],
    ) -> Optional[ModelObjectives]:
        """Identify the knee point of the Pareto frontier.

        The knee is the frontier model with the greatest perpendicular
        distance from the line (2-D) or hyperplane (n-D) connecting the
        extreme points of the frontier in normalised objective space.

        Args:
            models: Candidate models (frontier extraction is done internally).
            objectives: Objective configs.

        Returns:
            The knee model, or ``None`` if the frontier has fewer than 2
            models.
        """
        if len(models) < 2:
            return models[0] if models else None

        # Extract frontier
        frontier_result = self._extract_frontier(models, objectives)
        frontier = frontier_result
        if len(frontier) < 2:
            return frontier[0] if frontier else None

        all_normed = self._normalize_objectives(frontier, objectives)
        obj_names = [obj.name for obj in objectives]

        # Find extreme points: for each objective, the model with max
        # normalised value.  Collect unique extreme indices.
        extreme_indices: List[int] = []
        seen: set[int] = set()
        for name in obj_names:
            best_idx = 0
            best_val = -1.0
            for idx, normed in enumerate(all_normed):
                v = normed.get(name, 0.0)
                if v > best_val:
                    best_val = v
                    best_idx = idx
            if best_idx not in seen:
                extreme_indices.append(best_idx)
                seen.add(best_idx)

        if len(extreme_indices) < 2:
            # Degenerate — return the single best model.
            return frontier[extreme_indices[0]] if extreme_indices else frontier[0]

        # For 2-D: perpendicular distance from line between two extremes.
        if len(obj_names) <= 2 or len(extreme_indices) == 2:
            return self._knee_2d(frontier, all_normed, obj_names, extreme_indices)

        # For n-D: distance from the hyperplane spanned by extreme points.
        return self._knee_nd(frontier, all_normed, obj_names, extreme_indices)

    def _extract_frontier(
        self,
        models: List[ModelObjectives],
        objectives: List[ObjectiveConfig],
    ) -> List[ModelObjectives]:
        """Return only the non-dominated models from *models*."""
        dominated_set: set[int] = set()
        n = len(models)
        for i in range(n):
            if i in dominated_set:
                continue
            for j in range(n):
                if i == j or j in dominated_set:
                    continue
                if self.dominates(models[j], models[i], objectives):
                    dominated_set.add(i)
                    break
        return [models[i] for i in range(n) if i not in dominated_set]

    def _knee_2d(
        self,
        frontier: List[ModelObjectives],
        all_normed: List[Dict[str, float]],
        obj_names: List[str],
        extreme_indices: List[int],
    ) -> ModelObjectives:
        """Find knee via max perpendicular distance from line (2-D case).

        Also used when there are only 2 extreme points regardless of the
        actual objective dimensionality.
        """
        idx_a, idx_b = extreme_indices[0], extreme_indices[1]

        # Build n-D vectors for the two extremes
        a = [all_normed[idx_a].get(n, 0.0) for n in obj_names]
        b = [all_normed[idx_b].get(n, 0.0) for n in obj_names]

        # Direction vector of the line a→b
        d = [b[k] - a[k] for k in range(len(obj_names))]
        d_len_sq = sum(v * v for v in d)

        best_dist = -1.0
        best_idx = 0

        for idx in range(len(frontier)):
            p = [all_normed[idx].get(n, 0.0) for n in obj_names]
            # Vector a→p
            ap = [p[k] - a[k] for k in range(len(obj_names))]

            if d_len_sq < 1e-12:
                # Extremes coincide — use distance from point a.
                dist = math.sqrt(sum(v * v for v in ap))
            else:
                # Project ap onto d, then compute rejection length.
                t = sum(ap[k] * d[k] for k in range(len(obj_names))) / d_len_sq
                proj = [a[k] + t * d[k] for k in range(len(obj_names))]
                diff = [p[k] - proj[k] for k in range(len(obj_names))]
                dist = math.sqrt(sum(v * v for v in diff))

            if dist > best_dist:
                best_dist = dist
                best_idx = idx

        return frontier[best_idx]

    def _knee_nd(
        self,
        frontier: List[ModelObjectives],
        all_normed: List[Dict[str, float]],
        obj_names: List[str],
        extreme_indices: List[int],
    ) -> ModelObjectives:
        """Find knee as the point furthest from the hyperplane defined by
        the extreme points (n-D case, ≥ 3 extreme points).

        We compute the hyperplane via the centroid + normal approach:
        1. Compute centroid of extreme points.
        2. For each frontier point, compute distance to centroid.
        3. Subtract the projection onto the subspace spanned by the
           vectors from centroid to each extreme.
        4. The point with maximum residual distance is the knee.

        This is a simplified method that avoids full SVD / QR.
        """
        dim = len(obj_names)

        # Centroid of extreme points
        centroid = [0.0] * dim
        for ei in extreme_indices:
            for k, name in enumerate(obj_names):
                centroid[k] += all_normed[ei].get(name, 0.0)
        n_ext = len(extreme_indices)
        centroid = [c / n_ext for c in centroid]

        # Basis vectors: centroid → each extreme (not orthogonalised but
        # sufficient for distance approximation at our scale).
        basis: List[List[float]] = []
        for ei in extreme_indices:
            vec = [
                all_normed[ei].get(obj_names[k], 0.0) - centroid[k]
                for k in range(dim)
            ]
            length = math.sqrt(sum(v * v for v in vec))
            if length > 1e-12:
                basis.append([v / length for v in vec])

        if not basis:
            # Degenerate — return first extreme.
            return frontier[extreme_indices[0]]

        # Gram–Schmidt orthogonalisation of basis vectors.
        ortho: List[List[float]] = []
        for vec in basis:
            v = list(vec)
            for u in ortho:
                dot = sum(v[k] * u[k] for k in range(dim))
                v = [v[k] - dot * u[k] for k in range(dim)]
            length = math.sqrt(sum(x * x for x in v))
            if length > 1e-12:
                ortho.append([x / length for x in v])

        best_dist = -1.0
        best_idx = 0

        for idx in range(len(frontier)):
            p = [all_normed[idx].get(obj_names[k], 0.0) - centroid[k] for k in range(dim)]
            # Remove projection onto each orthonormal basis vector
            residual = list(p)
            for u in ortho:
                dot = sum(residual[k] * u[k] for k in range(dim))
                residual = [residual[k] - dot * u[k] for k in range(dim)]
            dist = math.sqrt(sum(r * r for r in residual))
            if dist > best_dist:
                best_dist = dist
                best_idx = idx

        return frontier[best_idx]

    # ── Euclidean distance helper ─────────────────────────────────────────

    def _euclidean_normed(
        self,
        a: Dict[str, float],
        b: Dict[str, float],
        objectives: List[ObjectiveConfig],
    ) -> float:
        """Weighted Euclidean distance between two normalised vectors.

        Args:
            a: Normalised objectives for model A.
            b: Normalised objectives for model B.
            objectives: Used for weight information.

        Returns:
            Weighted Euclidean distance.
        """
        total_weight = sum(obj.weight for obj in objectives) or 1.0
        sq_sum = 0.0
        for obj in objectives:
            w = obj.weight / total_weight
            diff = a.get(obj.name, 0.0) - b.get(obj.name, 0.0)
            sq_sum += w * diff * diff
        return math.sqrt(sq_sum)

    # ── Convenience ───────────────────────────────────────────────────────

    def recommend(
        self,
        models: List[ModelObjectives],
        context: str = "balanced",
    ) -> Optional[ModelObjectives]:
        """Shortcut: compute frontier, rank, return the single best model.

        Args:
            models: Candidate models.
            context: Preset name.

        Returns:
            The top-ranked model, or ``None`` if no models survive filtering.
        """
        if not models:
            return None

        result = self.compute_frontier(models, context=context)
        if result.rankings:
            best_model, best_score = result.rankings[0]
            logger.info(
                "Recommended model '%s' (score=%.4f, context='%s')",
                best_model.model_id, best_score, context,
            )
            return best_model

        logger.warning("No model could be recommended for context '%s'", context)
        return None


# ──── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[ParetoSelector] = None
_lock = threading.Lock()


def get_pareto_selector() -> ParetoSelector:
    """Get or create the singleton :class:`ParetoSelector` instance."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ParetoSelector()
    return _instance


def reset_pareto_selector() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    with _lock:
        _instance = None
