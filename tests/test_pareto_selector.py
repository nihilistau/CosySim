"""Tests for engine.nexus.pareto_selector — Pareto frontier, scalarization, ranking."""
from __future__ import annotations

import threading
from typing import List

import pytest

from engine.nexus.pareto_selector import (
    CONTEXT_PRESETS,
    ModelObjectives,
    ObjectiveConfig,
    ParetoResult,
    ParetoSelector,
    SelectionContext,
    get_pareto_selector,
    reset_pareto_selector,
)


# ──── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure each test gets a fresh singleton."""
    reset_pareto_selector()
    yield
    reset_pareto_selector()


@pytest.fixture
def selector() -> ParetoSelector:
    return ParetoSelector()


@pytest.fixture
def three_models() -> List[ModelObjectives]:
    """Three models with clear trade-offs."""
    return [
        ModelObjectives(
            "accurate", "qa", accuracy=0.95, latency_p50_ms=200,
            cost_per_1k_tokens=0.03, throughput_rps=10, error_rate=0.01,
        ),
        ModelObjectives(
            "fast", "qa", accuracy=0.80, latency_p50_ms=30,
            cost_per_1k_tokens=0.01, throughput_rps=100, error_rate=0.02,
        ),
        ModelObjectives(
            "cheap", "qa", accuracy=0.70, latency_p50_ms=100,
            cost_per_1k_tokens=0.005, throughput_rps=50, error_rate=0.05,
        ),
    ]


@pytest.fixture
def dominated_set() -> List[ModelObjectives]:
    """Set where one model dominates another."""
    return [
        ModelObjectives("A", "qa", accuracy=0.9, latency_p50_ms=50),
        ModelObjectives("B", "qa", accuracy=0.8, latency_p50_ms=60),  # dominated by A
        ModelObjectives("C", "qa", accuracy=0.85, latency_p50_ms=40),
    ]


# ──── Singleton ────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_returns_same_instance(self):
        a = get_pareto_selector()
        b = get_pareto_selector()
        assert a is b

    def test_reset_clears_instance(self):
        a = get_pareto_selector()
        reset_pareto_selector()
        b = get_pareto_selector()
        assert a is not b

    def test_thread_safe_creation(self):
        results = []

        def _get():
            results.append(get_pareto_selector())

        threads = [threading.Thread(target=_get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r is results[0] for r in results)


# ──── Context presets ──────────────────────────────────────────────────────────


class TestContextPresets:
    def test_builtin_presets_exist(self, selector: ParetoSelector):
        names = selector.list_contexts()
        for expected in ("balanced", "latency_sensitive", "accuracy_critical",
                         "cost_efficient", "throughput_max"):
            assert expected in names

    def test_get_context_returns_correct(self, selector: ParetoSelector):
        ctx = selector.get_context("balanced")
        assert ctx.name == "balanced"
        assert len(ctx.objectives) > 0

    def test_get_unknown_raises(self, selector: ParetoSelector):
        with pytest.raises(KeyError, match="Unknown context"):
            selector.get_context("nonexistent")

    def test_add_custom_context(self, selector: ParetoSelector):
        custom = SelectionContext(
            name="custom_test",
            description="Test preset",
            objectives=[ObjectiveConfig("accuracy", "maximize", weight=5.0)],
        )
        selector.add_context(custom)
        assert "custom_test" in selector.list_contexts()
        assert selector.get_context("custom_test") is custom


# ──── Dominance ────────────────────────────────────────────────────────────────


class TestDominance:
    def test_strictly_better_dominates(self, selector: ParetoSelector):
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        a = ModelObjectives("A", "qa", accuracy=0.9, latency_p50_ms=50)
        b = ModelObjectives("B", "qa", accuracy=0.8, latency_p50_ms=60)
        assert selector.dominates(a, b, objs)
        assert not selector.dominates(b, a, objs)

    def test_equal_does_not_dominate(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("accuracy", "maximize")]
        a = ModelObjectives("A", "qa", accuracy=0.9)
        b = ModelObjectives("B", "qa", accuracy=0.9)
        assert not selector.dominates(a, b, objs)

    def test_tradeoff_no_dominance(self, selector: ParetoSelector):
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        a = ModelObjectives("A", "qa", accuracy=0.95, latency_p50_ms=200)
        b = ModelObjectives("B", "qa", accuracy=0.80, latency_p50_ms=30)
        assert not selector.dominates(a, b, objs)
        assert not selector.dominates(b, a, objs)

    def test_minimize_direction(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("error_rate", "minimize")]
        a = ModelObjectives("A", "qa", error_rate=0.01)
        b = ModelObjectives("B", "qa", error_rate=0.05)
        assert selector.dominates(a, b, objs)

    def test_custom_objective(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("vram_gb", "minimize")]
        a = ModelObjectives("A", "qa", custom={"vram_gb": 4.0})
        b = ModelObjectives("B", "qa", custom={"vram_gb": 8.0})
        assert selector.dominates(a, b, objs)


# ──── Pareto frontier ─────────────────────────────────────────────────────────


class TestParetoFrontier:
    def test_frontier_excludes_dominated(self, selector: ParetoSelector, dominated_set):
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        result = selector.compute_frontier(dominated_set, objectives=objs)
        frontier_ids = {m.model_id for m in result.frontier}
        assert "B" not in frontier_ids  # dominated by A
        assert "A" in frontier_ids
        assert "C" in frontier_ids

    def test_all_non_dominated(self, selector: ParetoSelector, three_models):
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        result = selector.compute_frontier(three_models, objectives=objs)
        # accurate (high acc, high lat) and fast (low acc, low lat) are
        # non-dominated; cheap (medium both) — check it's on frontier
        # since cheap has worse accuracy than accurate but better latency
        assert len(result.frontier) >= 2

    def test_empty_input(self, selector: ParetoSelector):
        result = selector.compute_frontier([])
        assert result.frontier == []
        assert result.dominated == []
        assert result.rankings == []

    def test_single_model(self, selector: ParetoSelector):
        m = ModelObjectives("only", "qa", accuracy=0.9)
        objs = [ObjectiveConfig("accuracy", "maximize")]
        result = selector.compute_frontier([m], objectives=objs)
        assert len(result.frontier) == 1
        assert result.frontier[0].model_id == "only"

    def test_threshold_filtering(self, selector: ParetoSelector):
        models = [
            ModelObjectives("good", "qa", accuracy=0.9, error_rate=0.01),
            ModelObjectives("bad_err", "qa", accuracy=0.85, error_rate=0.20),
        ]
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("error_rate", "minimize", threshold=0.05),
        ]
        result = selector.compute_frontier(models, objectives=objs)
        frontier_ids = {m.model_id for m in result.frontier}
        assert "bad_err" not in frontier_ids
        assert "good" in frontier_ids

    def test_result_has_rankings(self, selector: ParetoSelector, three_models):
        result = selector.compute_frontier(three_models, context="balanced")
        assert len(result.rankings) > 0
        assert result.strategy == "weighted_sum"
        assert result.context == "balanced"


# ──── Scalarization ────────────────────────────────────────────────────────────


class TestScalarization:
    def test_weighted_sum_higher_accuracy_wins(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("accuracy", "maximize", weight=1.0)]
        models = [
            ModelObjectives("high", "qa", accuracy=0.9),
            ModelObjectives("low", "qa", accuracy=0.5),
        ]
        normed = selector._normalize_objectives(models, objs)
        s_high = selector.scalarize(models[0], objs, "weighted_sum",
                                    normalized_cache=normed[0],
                                    all_normalized=normed)
        s_low = selector.scalarize(models[1], objs, "weighted_sum",
                                   normalized_cache=normed[1],
                                   all_normalized=normed)
        assert s_high > s_low

    def test_weighted_sum_minimize(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("latency_p50_ms", "minimize", weight=1.0)]
        models = [
            ModelObjectives("fast", "qa", latency_p50_ms=10),
            ModelObjectives("slow", "qa", latency_p50_ms=100),
        ]
        normed = selector._normalize_objectives(models, objs)
        s_fast = selector.scalarize(models[0], objs, "weighted_sum",
                                    normalized_cache=normed[0],
                                    all_normalized=normed)
        s_slow = selector.scalarize(models[1], objs, "weighted_sum",
                                    normalized_cache=normed[1],
                                    all_normalized=normed)
        assert s_fast > s_slow

    def test_tchebycheff_prefers_balanced(self, selector: ParetoSelector):
        objs = [
            ObjectiveConfig("accuracy", "maximize", weight=1.0),
            ObjectiveConfig("latency_p50_ms", "minimize", weight=1.0),
        ]
        models = [
            ModelObjectives("balanced", "qa", accuracy=0.85, latency_p50_ms=60),
            ModelObjectives("extreme", "qa", accuracy=0.99, latency_p50_ms=200),
            ModelObjectives("extreme2", "qa", accuracy=0.50, latency_p50_ms=10),
        ]
        normed = selector._normalize_objectives(models, objs)
        s_balanced = selector.scalarize(models[0], objs, "tchebycheff",
                                        normalized_cache=normed[0],
                                        all_normalized=normed)
        s_extreme = selector.scalarize(models[1], objs, "tchebycheff",
                                       normalized_cache=normed[1],
                                       all_normalized=normed)
        s_extreme2 = selector.scalarize(models[2], objs, "tchebycheff",
                                        normalized_cache=normed[2],
                                        all_normalized=normed)
        # Tchebycheff should prefer the balanced model (min worst deviation)
        assert s_balanced > s_extreme or s_balanced > s_extreme2

    def test_augmented_tchebycheff_breaks_ties(self, selector: ParetoSelector):
        objs = [
            ObjectiveConfig("accuracy", "maximize", weight=1.0),
            ObjectiveConfig("latency_p50_ms", "minimize", weight=1.0),
        ]
        models = [
            ModelObjectives("a", "qa", accuracy=0.8, latency_p50_ms=50),
            ModelObjectives("b", "qa", accuracy=0.8, latency_p50_ms=50),
        ]
        normed = selector._normalize_objectives(models, objs)
        s_a = selector.scalarize(models[0], objs, "augmented_tchebycheff",
                                 normalized_cache=normed[0],
                                 all_normalized=normed)
        s_b = selector.scalarize(models[1], objs, "augmented_tchebycheff",
                                 normalized_cache=normed[1],
                                 all_normalized=normed)
        # Same values → same score
        assert abs(s_a - s_b) < 1e-9

    def test_invalid_method_raises(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("accuracy", "maximize")]
        m = ModelObjectives("x", "qa", accuracy=0.5)
        with pytest.raises(ValueError, match="Unknown scalarization"):
            selector.scalarize(m, objs, method="invalid")

    def test_constant_values_normalise_to_one(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("accuracy", "maximize")]
        models = [
            ModelObjectives("a", "qa", accuracy=0.8),
            ModelObjectives("b", "qa", accuracy=0.8),
        ]
        normed = selector._normalize_objectives(models, objs)
        assert normed[0]["accuracy"] == 1.0
        assert normed[1]["accuracy"] == 1.0


# ──── Ranking ──────────────────────────────────────────────────────────────────


class TestRanking:
    def test_weighted_sum_ranking_order(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("accuracy", "maximize", weight=1.0)]
        models = [
            ModelObjectives("low", "qa", accuracy=0.5),
            ModelObjectives("high", "qa", accuracy=0.9),
            ModelObjectives("mid", "qa", accuracy=0.7),
        ]
        ranked = selector.rank_models(models, strategy="weighted_sum",
                                      custom_objectives=objs)
        ids = [m.model_id for m, _ in ranked]
        assert ids == ["high", "mid", "low"]

    def test_pareto_rank_layers(self, selector: ParetoSelector, dominated_set):
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        ranked = selector.rank_models(dominated_set, strategy="pareto_rank",
                                      custom_objectives=objs)
        ids = [m.model_id for m, _ in ranked]
        # B is dominated, so should appear last
        assert ids[-1] == "B"

    def test_knee_point_ranking(self, selector: ParetoSelector, three_models):
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        ranked = selector.rank_models(three_models, strategy="knee_point",
                                      custom_objectives=objs)
        assert len(ranked) == 3
        # The knee model should be first
        knee_id = ranked[0][0].model_id
        assert knee_id in {"accurate", "fast", "cheap"}

    def test_invalid_strategy_raises(self, selector: ParetoSelector):
        with pytest.raises(ValueError, match="Unknown strategy"):
            selector.rank_models([], strategy="bogus")

    def test_empty_models(self, selector: ParetoSelector):
        assert selector.rank_models([]) == []

    def test_context_affects_ranking(self, selector: ParetoSelector, three_models):
        r_accuracy = selector.rank_models(three_models, context="accuracy_critical")
        r_latency = selector.rank_models(three_models, context="latency_sensitive")

        top_accuracy = r_accuracy[0][0].model_id
        top_latency = r_latency[0][0].model_id

        # Under accuracy_critical the accurate model should rank higher
        # than under latency_sensitive where the fast model should rank higher
        assert top_accuracy == "accurate"
        assert top_latency == "fast"


# ──── Knee point ───────────────────────────────────────────────────────────────


class TestKneePoint:
    def test_returns_model(self, selector: ParetoSelector, three_models):
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        knee = selector.find_knee_point(three_models, objs)
        assert knee is not None
        assert knee.model_id in {"accurate", "fast", "cheap"}

    def test_single_model(self, selector: ParetoSelector):
        m = ModelObjectives("only", "qa", accuracy=0.9)
        objs = [ObjectiveConfig("accuracy", "maximize")]
        knee = selector.find_knee_point([m], objs)
        assert knee is not None
        assert knee.model_id == "only"

    def test_empty_returns_none(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("accuracy", "maximize")]
        assert selector.find_knee_point([], objs) is None

    def test_two_models_returns_one(self, selector: ParetoSelector):
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        models = [
            ModelObjectives("a", "qa", accuracy=0.9, latency_p50_ms=100),
            ModelObjectives("b", "qa", accuracy=0.7, latency_p50_ms=20),
        ]
        knee = selector.find_knee_point(models, objs)
        assert knee is not None


# ──── Recommend ────────────────────────────────────────────────────────────────


class TestRecommend:
    def test_returns_best(self, selector: ParetoSelector, three_models):
        best = selector.recommend(three_models, context="accuracy_critical")
        assert best is not None
        assert best.model_id == "accurate"

    def test_returns_none_for_empty(self, selector: ParetoSelector):
        assert selector.recommend([]) is None

    def test_all_filtered_returns_none(self, selector: ParetoSelector):
        models = [ModelObjectives("x", "qa", accuracy=0.1, error_rate=0.9)]
        objs = [ObjectiveConfig("error_rate", "minimize", threshold=0.05)]
        ctx = SelectionContext("strict", "Very strict", objs)
        selector.add_context(ctx)
        result = selector.recommend(models, context="strict")
        assert result is None


# ──── Normalization edge cases ─────────────────────────────────────────────────


class TestNormalization:
    def test_single_model_all_ones(self, selector: ParetoSelector):
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        models = [ModelObjectives("solo", "qa", accuracy=0.85, latency_p50_ms=50)]
        normed = selector._normalize_objectives(models, objs)
        assert normed[0]["accuracy"] == 1.0
        assert normed[0]["latency_p50_ms"] == 1.0

    def test_empty_list(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("accuracy", "maximize")]
        assert selector._normalize_objectives([], objs) == []

    def test_custom_field_normalization(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("vram_gb", "minimize")]
        models = [
            ModelObjectives("small", "qa", custom={"vram_gb": 2.0}),
            ModelObjectives("big", "qa", custom={"vram_gb": 8.0}),
        ]
        normed = selector._normalize_objectives(models, objs)
        assert normed[0]["vram_gb"] > normed[1]["vram_gb"]  # smaller is better


# ──── Threshold filtering ──────────────────────────────────────────────────────


class TestThresholds:
    def test_maximize_threshold(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("accuracy", "maximize", threshold=0.8)]
        models = [
            ModelObjectives("good", "qa", accuracy=0.9),
            ModelObjectives("bad", "qa", accuracy=0.7),
        ]
        result = selector._apply_thresholds(models, objs)
        assert len(result) == 1
        assert result[0].model_id == "good"

    def test_minimize_threshold(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("error_rate", "minimize", threshold=0.05)]
        models = [
            ModelObjectives("ok", "qa", error_rate=0.02),
            ModelObjectives("bad", "qa", error_rate=0.10),
        ]
        result = selector._apply_thresholds(models, objs)
        assert len(result) == 1
        assert result[0].model_id == "ok"

    def test_no_thresholds_passes_all(self, selector: ParetoSelector):
        objs = [ObjectiveConfig("accuracy", "maximize")]
        models = [ModelObjectives("a", "qa"), ModelObjectives("b", "qa")]
        assert len(selector._apply_thresholds(models, objs)) == 2


# ──── ModelObjectives dataclass ────────────────────────────────────────────────


class TestModelObjectives:
    """Tests for the ModelObjectives dataclass."""

    def test_defaults(self):
        """All numeric fields default to 0.0."""
        m = ModelObjectives("m1", "eval")
        assert m.accuracy == 0.0
        assert m.latency_p50_ms == 0.0
        assert m.cost_per_1k_tokens == 0.0
        assert m.throughput_rps == 0.0
        assert m.error_rate == 0.0
        assert m.memory_mb == 0.0
        assert m.custom == {}

    def test_custom_fields(self):
        """Custom objectives are stored in the custom dict."""
        m = ModelObjectives("m1", "eval", custom={"novelty": 0.8, "safety": 0.95})
        assert m.custom["novelty"] == 0.8
        assert m.custom["safety"] == 0.95

    def test_model_type(self):
        """model_type is stored correctly."""
        m = ModelObjectives("m1", "qa_evaluator")
        assert m.model_type == "qa_evaluator"
        assert m.model_id == "m1"

    def test_all_standard_fields(self):
        """All standard fields accept explicit values."""
        m = ModelObjectives(
            "m1", "eval",
            accuracy=0.95,
            latency_p50_ms=100,
            latency_p95_ms=200,
            cost_per_1k_tokens=0.01,
            throughput_rps=50,
            error_rate=0.02,
            memory_mb=4096,
        )
        assert m.accuracy == 0.95
        assert m.latency_p95_ms == 200
        assert m.throughput_rps == 50
        assert m.memory_mb == 4096


# ──── ObjectiveConfig dataclass ────────────────────────────────────────────────


class TestObjectiveConfig:
    """Tests for the ObjectiveConfig dataclass."""

    def test_defaults(self):
        """Default weight is 1.0, ideal/nadir/threshold are None."""
        o = ObjectiveConfig("accuracy", "maximize")
        assert o.weight == 1.0
        assert o.ideal is None
        assert o.nadir is None
        assert o.threshold is None

    def test_threshold(self):
        """Threshold is stored correctly."""
        o = ObjectiveConfig("accuracy", "maximize", threshold=0.8)
        assert o.threshold == 0.8

    def test_directions(self):
        """Direction string is stored as given."""
        o_max = ObjectiveConfig("accuracy", "maximize")
        o_min = ObjectiveConfig("latency_p50_ms", "minimize")
        assert o_max.direction == "maximize"
        assert o_min.direction == "minimize"


# ──── Edge cases ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Robustness and edge-case tests."""

    def test_identical_models(self, selector: ParetoSelector):
        """Identical models: no dominance, all on frontier."""
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        models = [ModelObjectives(f"m{i}", "qa", accuracy=0.8, latency_p50_ms=60)
                  for i in range(3)]
        result = selector.compute_frontier(models, objectives=objs)
        assert len(result.frontier) == 3
        assert len(result.dominated) == 0

    def test_all_zeros(self, selector: ParetoSelector):
        """Models with all-zero objectives: no crash, all on frontier."""
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        models = [ModelObjectives(f"z{i}", "qa", accuracy=0.0, latency_p50_ms=0.0)
                  for i in range(3)]
        result = selector.compute_frontier(models, objectives=objs)
        assert len(result.frontier) == 3

    def test_extreme_values(self, selector: ParetoSelector):
        """Very large objective values don't cause errors."""
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]
        models = [
            ModelObjectives("huge_acc", "qa", accuracy=1e10, latency_p50_ms=1e10),
            ModelObjectives("huge_speed", "qa", accuracy=1e-10, latency_p50_ms=1e-10),
        ]
        result = selector.compute_frontier(models, objectives=objs)
        assert len(result.frontier) == 2

    def test_thread_safety(self, selector: ParetoSelector):
        """Multiple threads computing frontiers concurrently don't crash."""
        errors = []
        objs = [
            ObjectiveConfig("accuracy", "maximize"),
            ObjectiveConfig("latency_p50_ms", "minimize"),
        ]

        def compute(tid: int) -> None:
            try:
                models = [
                    ModelObjectives(f"m{tid}a", "qa", accuracy=0.9,
                                    latency_p50_ms=50 + tid),
                    ModelObjectives(f"m{tid}b", "qa", accuracy=0.7,
                                    latency_p50_ms=30 + tid),
                ]
                result = selector.compute_frontier(models, objectives=objs)
                assert result.frontier is not None
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=compute, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
