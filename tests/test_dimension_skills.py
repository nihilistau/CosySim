"""Tests for engine.skills.builtin.dimension_skills — skill function wrappers.

All external dependencies (DimensionStore, ParetoSelector, ModelRegistry)
are mocked so these tests run fast and in isolation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ──── Lightweight dataclasses that match real types for asdict() ─────────────


@dataclass
class _FakeMetric:
    """Minimal dataclass matching DimensionalMetric fields."""
    metric_id: int = 0
    name: str = ""
    value: float = 0.0
    tags: dict = field(default_factory=dict)
    timestamp: float = 0.0


@dataclass
class _FakeAggregation:
    """Minimal dataclass matching AggregationResult fields."""
    group_key: dict = field(default_factory=dict)
    count: int = 0
    mean: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    sum_val: float = 0.0
    stddev: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0


@dataclass
class _FakeCardinality:
    """Minimal dataclass matching TagCardinality fields."""
    key: str = ""
    unique_values: int = 0
    total_uses: int = 0
    sample_values: list = field(default_factory=list)


@dataclass
class _FakeModelObjectives:
    """Minimal dataclass matching ModelObjectives fields."""
    model_id: str = ""
    model_type: str = ""
    accuracy: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    cost_per_1k_tokens: float = 0.0
    throughput_rps: float = 0.0
    error_rate: float = 0.0
    memory_mb: float = 0.0
    custom: dict = field(default_factory=dict)


# ──── Helpers ────────────────────────────────────────────────────────────────


def _mock_store():
    """Build a MagicMock matching DimensionStore's interface."""
    store = MagicMock()
    store.record.return_value = 42
    store.record_batch.return_value = [1, 2, 3]
    store.query.return_value = []
    store.get_tag_cardinality.return_value = []
    store.get_summary.return_value = {}
    store.export_for_analysis.return_value = []
    store.get_metric_names.return_value = []
    store.get_tag_values.return_value = []
    return store


def _mock_selector():
    """Build a MagicMock matching ParetoSelector's interface."""
    sel = MagicMock()
    sel.list_contexts.return_value = ["balanced", "latency_sensitive"]
    sel.recommend.return_value = None
    return sel


def _mock_registry():
    """Build a MagicMock matching ModelRegistry's interface."""
    reg = MagicMock()
    reg.promote_multi_criteria.return_value = None
    reg.list_models.return_value = []
    return reg


# ──── record_dimensional_metric ──────────────────────────────────────────────


class TestRecordDimensionalMetric:
    """Tests for the record_dimensional_metric skill."""

    @patch("engine.skills.builtin.dimension_skills._get_dimension_store")
    def test_success(self, mock_get_store):
        """Successful record returns JSON with metric_id."""
        store = _mock_store()
        store.record.return_value = 42
        mock_get_store.return_value = store

        from engine.skills.builtin.dimension_skills import record_dimensional_metric

        result = record_dimensional_metric("latency_ms", 55.0, '{"agent": "alice"}')
        parsed = json.loads(result)
        assert parsed["metric_id"] == 42
        assert parsed["status"] == "recorded"
        store.record.assert_called_once_with("latency_ms", 55.0, tags={"agent": "alice"})

    @patch("engine.skills.builtin.dimension_skills._get_dimension_store")
    def test_invalid_json_tags(self, mock_get_store):
        """Invalid JSON in tags returns an error message."""
        from engine.skills.builtin.dimension_skills import record_dimensional_metric

        result = record_dimensional_metric("m", 1.0, "not valid json{{{")
        assert "Error" in result
        mock_get_store.return_value.record.assert_not_called()


# ──── query_dimensional_metrics ──────────────────────────────────────────────


class TestQueryDimensionalMetrics:
    """Tests for the query_dimensional_metrics skill."""

    @patch("engine.skills.builtin.dimension_skills._get_dimension_store")
    def test_raw_mode(self, mock_get_store):
        """Without group_by, returns raw metric rows."""
        store = _mock_store()
        raw_metric = _FakeMetric(metric_id=1, name="m", value=10.0,
                                  tags={"env": "prod"}, timestamp=1000.0)
        store.query.return_value = [raw_metric]
        mock_get_store.return_value = store

        from engine.skills.builtin.dimension_skills import query_dimensional_metrics

        result = query_dimensional_metrics("m")
        parsed = json.loads(result)
        assert parsed["count"] == 1
        assert parsed["name"] == "m"

    @patch("engine.skills.builtin.dimension_skills._get_dimension_store")
    def test_aggregated_mode(self, mock_get_store):
        """With group_by, returns aggregated results."""
        store = _mock_store()
        agg = _FakeAggregation(
            group_key={"agent": "alice"}, count=5, mean=15.0,
            min_val=10.0, max_val=20.0, sum_val=75.0,
            stddev=3.5, p50=15.0, p95=19.0, p99=20.0,
        )
        store.query.return_value = [agg]
        mock_get_store.return_value = store

        from engine.skills.builtin.dimension_skills import query_dimensional_metrics

        result = query_dimensional_metrics("m", group_by="agent")
        parsed = json.loads(result)
        assert parsed["count"] == 1

    @patch("engine.skills.builtin.dimension_skills._get_dimension_store")
    def test_error_handling(self, mock_get_store):
        """Store exceptions are caught and returned as error strings."""
        mock_get_store.return_value.query.side_effect = RuntimeError("db locked")

        from engine.skills.builtin.dimension_skills import query_dimensional_metrics

        result = query_dimensional_metrics("m")
        assert "Error" in result
        assert "db locked" in result


# ──── get_tag_cardinality ────────────────────────────────────────────────────


class TestGetTagCardinality:
    """Tests for the get_tag_cardinality skill."""

    @patch("engine.skills.builtin.dimension_skills._get_dimension_store")
    def test_without_metric_name(self, mock_get_store):
        """Without metric_name, calls store with None."""
        store = _mock_store()
        card = _FakeCardinality(key="env", unique_values=3, total_uses=10,
                                 sample_values=["prod", "dev", "staging"])
        store.get_tag_cardinality.return_value = [card]
        mock_get_store.return_value = store

        from engine.skills.builtin.dimension_skills import get_tag_cardinality

        result = get_tag_cardinality()
        parsed = json.loads(result)
        assert "tags" in parsed
        store.get_tag_cardinality.assert_called_once_with(None)

    @patch("engine.skills.builtin.dimension_skills._get_dimension_store")
    def test_with_metric_name(self, mock_get_store):
        """With metric_name, calls store with that name."""
        store = _mock_store()
        store.get_tag_cardinality.return_value = []
        mock_get_store.return_value = store

        from engine.skills.builtin.dimension_skills import get_tag_cardinality

        result = get_tag_cardinality(metric_name="latency_ms")
        store.get_tag_cardinality.assert_called_once_with("latency_ms")


# ──── get_metric_dimensions_summary ──────────────────────────────────────────


class TestGetMetricDimensionsSummary:
    """Tests for the get_metric_dimensions_summary skill."""

    @patch("engine.skills.builtin.dimension_skills._get_dimension_store")
    def test_success(self, mock_get_store):
        """Summary returns JSON with count and mean."""
        store = _mock_store()
        store.get_summary.return_value = {"count": 10, "mean": 42.5, "p50": 40.0}
        mock_get_store.return_value = store

        from engine.skills.builtin.dimension_skills import get_metric_dimensions_summary

        result = get_metric_dimensions_summary("latency_ms")
        parsed = json.loads(result)
        assert parsed["count"] == 10
        assert parsed["mean"] == 42.5
        assert parsed["metric_name"] == "latency_ms"

    @patch("engine.skills.builtin.dimension_skills._get_dimension_store")
    def test_error(self, mock_get_store):
        """Store exception is caught and returned as error."""
        mock_get_store.return_value.get_summary.side_effect = RuntimeError("fail")

        from engine.skills.builtin.dimension_skills import get_metric_dimensions_summary

        result = get_metric_dimensions_summary("m")
        assert "Error" in result


# ──── compute_pareto_frontier ────────────────────────────────────────────────


class TestComputeParetoFrontier:
    """Tests for the compute_pareto_frontier skill."""

    @patch("engine.skills.builtin.dimension_skills._get_model_registry")
    def test_success(self, mock_get_reg):
        """Valid model_type produces frontier results JSON."""
        reg = _mock_registry()
        reg.get_pareto_frontier.return_value = {
            "frontier": [{"model_id": "gpt4"}],
            "dominated": [{"model_id": "small"}],
            "rankings": [{"model_id": "gpt4", "score": 0.95}],
        }
        mock_get_reg.return_value = reg

        from engine.skills.builtin.dimension_skills import compute_pareto_frontier

        result = compute_pareto_frontier("qa_evaluator")
        parsed = json.loads(result)
        assert "frontier" in parsed

    @patch("engine.skills.builtin.dimension_skills._get_model_registry")
    def test_error(self, mock_get_reg):
        """Registry exception produces error string."""
        mock_get_reg.return_value.get_pareto_frontier.side_effect = RuntimeError("no models")

        from engine.skills.builtin.dimension_skills import compute_pareto_frontier

        result = compute_pareto_frontier("qa_evaluator")
        assert "Error" in result


# ──── rank_models_multi_criteria ─────────────────────────────────────────────


class TestRankModelsMultiCriteria:
    """Tests for the rank_models_multi_criteria skill."""

    @patch("engine.skills.builtin.dimension_skills._get_pareto_selector")
    @patch("engine.skills.builtin.dimension_skills._get_model_registry")
    def test_success(self, mock_get_reg, mock_get_sel):
        """Valid input produces ranked output."""
        reg = _mock_registry()
        model_entry = MagicMock()
        model_entry.model_type = "qa"
        reg.list_models.return_value = [model_entry]

        obj = _FakeModelObjectives(model_id="best", model_type="qa", accuracy=0.9)
        reg._to_model_objectives.return_value = [obj]
        mock_get_reg.return_value = reg

        sel = _mock_selector()
        sel.rank_models.return_value = [(obj, 0.88)]
        mock_get_sel.return_value = sel

        from engine.skills.builtin.dimension_skills import rank_models_multi_criteria

        result = rank_models_multi_criteria("qa")
        parsed = json.loads(result)
        assert parsed["count"] == 1

    @patch("engine.skills.builtin.dimension_skills._get_pareto_selector")
    @patch("engine.skills.builtin.dimension_skills._get_model_registry")
    def test_no_models(self, mock_get_reg, mock_get_sel):
        """No models for model_type returns empty rankings."""
        reg = _mock_registry()
        reg.list_models.return_value = []
        mock_get_reg.return_value = reg

        from engine.skills.builtin.dimension_skills import rank_models_multi_criteria

        result = rank_models_multi_criteria("nonexistent")
        parsed = json.loads(result)
        assert parsed["count"] == 0
        assert parsed["rankings"] == []

    @patch("engine.skills.builtin.dimension_skills._get_model_registry")
    def test_error(self, mock_get_reg):
        """Registry exception produces error string."""
        mock_get_reg.side_effect = RuntimeError("db error")

        from engine.skills.builtin.dimension_skills import rank_models_multi_criteria

        result = rank_models_multi_criteria("qa")
        assert "Error" in result


# ──── list_selection_contexts ────────────────────────────────────────────────


class TestListSelectionContexts:
    """Tests for the list_selection_contexts skill."""

    @patch("engine.skills.builtin.dimension_skills._get_pareto_selector")
    def test_success(self, mock_get_sel):
        """Returns JSON with context objects."""
        sel = _mock_selector()
        sel.list_contexts.return_value = ["balanced", "latency_sensitive"]
        ctx_balanced = MagicMock()
        ctx_balanced.name = "balanced"
        ctx_balanced.description = "Equal weight"
        obj = MagicMock()
        obj.name = "accuracy"
        obj.direction = "maximize"
        obj.weight = 1.0
        ctx_balanced.objectives = [obj]

        ctx_latency = MagicMock()
        ctx_latency.name = "latency_sensitive"
        ctx_latency.description = "Low latency"
        ctx_latency.objectives = [obj]

        sel.get_context.side_effect = lambda n: {
            "balanced": ctx_balanced,
            "latency_sensitive": ctx_latency,
        }[n]
        mock_get_sel.return_value = sel

        from engine.skills.builtin.dimension_skills import list_selection_contexts

        result = list_selection_contexts()
        parsed = json.loads(result)
        assert parsed["count"] == 2


# ──── recommend_model ────────────────────────────────────────────────────────


class TestRecommendModel:
    """Tests for the recommend_model skill."""

    @patch("engine.skills.builtin.dimension_skills._get_pareto_selector")
    @patch("engine.skills.builtin.dimension_skills._get_model_registry")
    def test_success(self, mock_get_reg, mock_get_sel):
        """Recommendation returns model details JSON."""
        reg = _mock_registry()
        model_entry = MagicMock()
        reg.list_models.return_value = [model_entry]
        obj = _FakeModelObjectives(model_id="gpt4", model_type="qa", accuracy=0.95,
                                    latency_p50_ms=100, latency_p95_ms=200,
                                    cost_per_1k_tokens=0.01, throughput_rps=50,
                                    error_rate=0.01, memory_mb=4096)
        reg._to_model_objectives.return_value = [obj]
        mock_get_reg.return_value = reg

        sel = _mock_selector()
        sel.recommend.return_value = obj
        mock_get_sel.return_value = sel

        from engine.skills.builtin.dimension_skills import recommend_model

        result = recommend_model("qa")
        parsed = json.loads(result)
        assert parsed["recommendation"] is not None

    @patch("engine.skills.builtin.dimension_skills._get_pareto_selector")
    @patch("engine.skills.builtin.dimension_skills._get_model_registry")
    def test_no_candidates(self, mock_get_reg, mock_get_sel):
        """No candidates returns None recommendation."""
        reg = _mock_registry()
        reg.list_models.return_value = []
        mock_get_reg.return_value = reg

        from engine.skills.builtin.dimension_skills import recommend_model

        result = recommend_model("nonexistent")
        parsed = json.loads(result)
        assert parsed["recommendation"] is None


# ──── promote_model_multi_criteria ───────────────────────────────────────────


class TestPromoteModelMultiCriteria:
    """Tests for the promote_model_multi_criteria skill."""

    @patch("engine.skills.builtin.dimension_skills._get_model_registry")
    def test_success(self, mock_get_reg):
        """Successful promotion returns JSON with promoted status."""
        reg = _mock_registry()
        reg.promote_multi_criteria.return_value = {
            "promoted_model_id": "abc123",
            "promoted_score": 0.92,
            "strategy": "weighted_sum",
        }
        mock_get_reg.return_value = reg

        from engine.skills.builtin.dimension_skills import promote_model_multi_criteria

        result = promote_model_multi_criteria("qa_evaluator")
        parsed = json.loads(result)
        assert parsed["status"] == "promoted"
        assert parsed["promoted_model_id"] == "abc123"
        reg.promote_multi_criteria.assert_called_once()

    @patch("engine.skills.builtin.dimension_skills._get_model_registry")
    def test_no_candidates(self, mock_get_reg):
        """No candidates returns no_candidates status."""
        reg = _mock_registry()
        reg.promote_multi_criteria.return_value = None
        mock_get_reg.return_value = reg

        from engine.skills.builtin.dimension_skills import promote_model_multi_criteria

        result = promote_model_multi_criteria("qa_evaluator")
        parsed = json.loads(result)
        assert parsed["status"] == "no_candidates"


# ──── get_promotion_strategy_info ────────────────────────────────────────────


class TestGetPromotionStrategyInfo:
    """Tests for the get_promotion_strategy_info skill."""

    def test_weighted_sum(self):
        """weighted_sum returns description with 'Weighted Sum'."""
        from engine.skills.builtin.dimension_skills import get_promotion_strategy_info

        result = get_promotion_strategy_info("weighted_sum")
        parsed = json.loads(result)
        assert parsed["name"] == "Weighted Sum"

    def test_tchebycheff(self):
        """tchebycheff returns description with 'Tchebycheff'."""
        from engine.skills.builtin.dimension_skills import get_promotion_strategy_info

        result = get_promotion_strategy_info("tchebycheff")
        parsed = json.loads(result)
        assert "Tchebycheff" in parsed["name"]

    def test_pareto_rank(self):
        """pareto_rank returns description with 'Pareto Rank'."""
        from engine.skills.builtin.dimension_skills import get_promotion_strategy_info

        result = get_promotion_strategy_info("pareto_rank")
        parsed = json.loads(result)
        assert "Pareto Rank" in parsed["name"]

    def test_knee_point(self):
        """knee_point returns description with 'Knee Point'."""
        from engine.skills.builtin.dimension_skills import get_promotion_strategy_info

        result = get_promotion_strategy_info("knee_point")
        parsed = json.loads(result)
        assert "Knee Point" in parsed["name"]

    def test_all_strategies(self):
        """Passing 'all' returns all available strategies."""
        from engine.skills.builtin.dimension_skills import get_promotion_strategy_info

        result = get_promotion_strategy_info("all")
        parsed = json.loads(result)
        assert parsed["count"] == 4
        assert "weighted_sum" in parsed["strategies"]

    def test_unknown_strategy(self):
        """Unknown strategy returns error with available list."""
        from engine.skills.builtin.dimension_skills import get_promotion_strategy_info

        result = get_promotion_strategy_info("nonexistent")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "weighted_sum" in parsed["available"]
