"""Tests for engine.skills.builtin.causal_skills — Granger causality MCP skills."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

# ──── Constants ────────────────────────────────────────────────────────

PATCH_ENGINE = "engine.skills.builtin.causal_skills._get_engine"


# ──── Factories ────────────────────────────────────────────────────────


def _granger_result(
    *,
    cause: str = "cpu",
    effect: str = "latency",
    is_causal: bool = True,
    f_stat: float = 12.34,
    p_value: float = 0.001,
    optimal_lag: int = 3,
    direction: str = "unidirectional",
    strength: str = "strong",
    sample_count: int = 100,
) -> MagicMock:
    r = MagicMock()
    r.cause_metric = cause
    r.effect_metric = effect
    r.is_causal = is_causal
    r.f_statistic = f_stat
    r.p_value = p_value
    r.optimal_lag = optimal_lag
    r.direction = direction
    r.strength = strength
    r.sample_count = sample_count
    return r


def _causal_edge(
    *,
    cause: str = "cpu",
    effect: str = "latency",
    f_stat: float = 8.5,
    p_value: float = 0.005,
    lag: int = 2,
    strength: str = "strong",
    weight: float = 0.995,
) -> MagicMock:
    e = MagicMock()
    e.cause = cause
    e.effect = effect
    e.f_statistic = f_stat
    e.p_value = p_value
    e.lag = lag
    e.strength = strength
    e.weight = weight
    return e


def _causal_dag(
    edges: list | None = None,
    nodes: set | None = None,
    roots: set | None = None,
    leaves: set | None = None,
) -> MagicMock:
    dag = MagicMock()
    dag.edges = edges or []
    dag.nodes = nodes or set()
    dag.roots.return_value = roots or set()
    dag.leaves.return_value = leaves or set()
    return dag


def _root_cause_result(
    target: str = "latency",
    root_causes: list | None = None,
) -> MagicMock:
    r = MagicMock()
    r.target_metric = target
    r.root_causes = root_causes or []
    return r


def _intervention_result(
    metric: str = "cpu",
    delta: float = 10.0,
    downstream: list | None = None,
    total_affected: int | None = None,
) -> MagicMock:
    r = MagicMock()
    r.intervention_metric = metric
    r.delta = delta
    r.downstream_effects = downstream or []
    r.total_affected = total_affected if total_affected is not None else len(r.downstream_effects)
    return r


# ──── Import skills (after factories so patch target string is valid) ──

from engine.skills.builtin.causal_skills import (
    causal_granger_test,
    causal_build_dag,
    causal_root_causes,
    causal_analyze_intervention,
    causal_summary,
    causal_find_path,
)


# ──── TestGrangerTest ──────────────────────────────────────────────────


class TestGrangerTest:
    """Tests for causal_granger_test skill."""

    @patch(PATCH_ENGINE)
    def test_causal_result(self, mock_get_engine: MagicMock) -> None:
        """Causal result includes CAUSAL verdict, F-stat, and p-value."""
        engine = MagicMock()
        engine.granger_test.return_value = _granger_result(
            is_causal=True, f_stat=15.0, p_value=0.0003,
        )
        mock_get_engine.return_value = engine

        out = causal_granger_test("cpu", "latency")

        assert "CAUSAL" in out
        assert "NOT CAUSAL" not in out
        assert "15.0000" in out
        assert "0.000300" in out

    @patch(PATCH_ENGINE)
    def test_non_causal_result(self, mock_get_engine: MagicMock) -> None:
        """Non-causal result shows NOT CAUSAL."""
        engine = MagicMock()
        engine.granger_test.return_value = _granger_result(is_causal=False)
        mock_get_engine.return_value = engine

        out = causal_granger_test("cpu", "latency")

        assert "NOT CAUSAL" in out

    @patch(PATCH_ENGINE)
    def test_none_result_insufficient_data(self, mock_get_engine: MagicMock) -> None:
        """None from engine means insufficient data."""
        engine = MagicMock()
        engine.granger_test.return_value = None
        mock_get_engine.return_value = engine

        out = causal_granger_test("cpu", "latency")

        assert "Insufficient data" in out
        assert "cpu" in out
        assert "latency" in out

    @patch(PATCH_ENGINE)
    def test_max_lag_passthrough(self, mock_get_engine: MagicMock) -> None:
        """max_lag parameter is forwarded to the engine."""
        engine = MagicMock()
        engine.granger_test.return_value = None
        mock_get_engine.return_value = engine

        causal_granger_test("a", "b", max_lag=25)

        engine.granger_test.assert_called_once_with("a", "b", max_lag=25)

    @patch(PATCH_ENGINE)
    def test_output_contains_all_fields(self, mock_get_engine: MagicMock) -> None:
        """Output includes lag, direction, strength, and sample count."""
        engine = MagicMock()
        engine.granger_test.return_value = _granger_result(
            optimal_lag=5,
            direction="bidirectional",
            strength="moderate",
            sample_count=200,
        )
        mock_get_engine.return_value = engine

        out = causal_granger_test("mem", "gc")

        assert "Optimal lag: 5" in out
        assert "bidirectional" in out
        assert "moderate" in out
        assert "200" in out
        assert "mem" in out
        assert "gc" in out


# ──── TestBuildDag ─────────────────────────────────────────────────────


class TestBuildDag:
    """Tests for causal_build_dag skill."""

    @patch(PATCH_ENGINE)
    def test_dag_with_edges(self, mock_get_engine: MagicMock) -> None:
        """DAG with edges shows node/edge counts, roots, and edge list."""
        edges = [
            _causal_edge(cause="cpu", effect="latency", p_value=0.002),
            _causal_edge(cause="mem", effect="gc", p_value=0.01),
        ]
        dag = _causal_dag(
            edges=edges,
            nodes={"cpu", "latency", "mem", "gc"},
            roots={"cpu", "mem"},
            leaves={"latency", "gc"},
        )
        engine = MagicMock()
        engine.build_causal_dag.return_value = dag
        mock_get_engine.return_value = engine

        out = causal_build_dag()

        assert "Nodes: 4" in out
        assert "Edges: 2" in out
        assert "cpu" in out
        assert "latency" in out

    @patch(PATCH_ENGINE)
    def test_dag_no_edges(self, mock_get_engine: MagicMock) -> None:
        """Empty DAG shows 'No significant causal relationships'."""
        dag = _causal_dag(edges=[], nodes=set())
        engine = MagicMock()
        engine.build_causal_dag.return_value = dag
        mock_get_engine.return_value = engine

        out = causal_build_dag()

        assert "No significant causal relationships found." in out

    @patch(PATCH_ENGINE)
    def test_parameter_passthrough(self, mock_get_engine: MagicMock) -> None:
        """min_samples and max_lag are forwarded to the engine."""
        engine = MagicMock()
        engine.build_causal_dag.return_value = _causal_dag()
        mock_get_engine.return_value = engine

        causal_build_dag(min_samples=50, max_lag=20)

        engine.build_causal_dag.assert_called_once_with(min_samples=50, max_lag=20)

    @patch(PATCH_ENGINE)
    def test_edges_sorted_by_p_value(self, mock_get_engine: MagicMock) -> None:
        """Edges appear in ascending p-value order."""
        edges = [
            _causal_edge(cause="b", effect="c", p_value=0.05),
            _causal_edge(cause="a", effect="b", p_value=0.001),
        ]
        dag = _causal_dag(edges=edges, nodes={"a", "b", "c"})
        engine = MagicMock()
        engine.build_causal_dag.return_value = dag
        mock_get_engine.return_value = engine

        out = causal_build_dag()

        pos_a = out.index("a → b")
        pos_b = out.index("b → c")
        assert pos_a < pos_b, "Lower p-value edge should appear first"


# ──── TestRootCauses ───────────────────────────────────────────────────


class TestRootCauses:
    """Tests for causal_root_causes skill."""

    @patch(PATCH_ENGINE)
    def test_root_causes_found(self, mock_get_engine: MagicMock) -> None:
        """Shows metric, depth, and causal chain when root causes exist."""
        rc = _root_cause_result(
            target="latency",
            root_causes=[
                {
                    "metric": "cpu",
                    "depth": 2,
                    "chain": ["cpu", "queue", "latency"],
                    "edge_strength": "strong",
                    "edge_p_value": 0.001,
                    "edge_f_statistic": 12.0,
                },
            ],
        )
        engine = MagicMock()
        engine.get_root_causes.return_value = rc
        mock_get_engine.return_value = engine

        out = causal_root_causes("latency")

        assert "Root Cause Analysis: latency" in out
        assert "Root causes found: 1" in out
        assert "cpu" in out
        assert "depth=2" in out
        assert "cpu → queue → latency" in out

    @patch(PATCH_ENGINE)
    def test_no_root_causes(self, mock_get_engine: MagicMock) -> None:
        """Empty root causes shows informative message."""
        engine = MagicMock()
        engine.get_root_causes.return_value = _root_cause_result(
            target="orphan", root_causes=[],
        )
        mock_get_engine.return_value = engine

        out = causal_root_causes("orphan")

        assert "No root causes found" in out

    @patch(PATCH_ENGINE)
    def test_parameter_passthrough(self, mock_get_engine: MagicMock) -> None:
        """min_samples and max_depth are forwarded to the engine."""
        engine = MagicMock()
        engine.get_root_causes.return_value = _root_cause_result()
        mock_get_engine.return_value = engine

        causal_root_causes("target", min_samples=100, max_depth=8)

        engine.get_root_causes.assert_called_once_with(
            "target", min_samples=100, max_depth=8,
        )

    @patch(PATCH_ENGINE)
    def test_chain_formatting(self, mock_get_engine: MagicMock) -> None:
        """Chain is rendered as arrow-separated path."""
        rc = _root_cause_result(
            root_causes=[
                {
                    "metric": "disk_io",
                    "depth": 3,
                    "chain": ["disk_io", "buffer", "throughput", "latency"],
                    "edge_strength": "moderate",
                    "edge_p_value": 0.03,
                    "edge_f_statistic": 6.0,
                },
            ],
        )
        engine = MagicMock()
        engine.get_root_causes.return_value = rc
        mock_get_engine.return_value = engine

        out = causal_root_causes("latency")

        assert "disk_io → buffer → throughput → latency" in out


# ──── TestAnalyzeIntervention ──────────────────────────────────────────


class TestAnalyzeIntervention:
    """Tests for causal_analyze_intervention skill."""

    @patch(PATCH_ENGINE)
    def test_with_downstream_effects(self, mock_get_engine: MagicMock) -> None:
        """Shows affected metrics, deltas, and paths when effects exist."""
        effects = [
            {
                "metric": "latency",
                "estimated_delta": 5.123,
                "via": "queue",
                "depth": 2,
                "edge_strength": "strong",
                "edge_lag": 3,
            },
        ]
        ir = _intervention_result(
            metric="cpu", delta=10.0,
            downstream=effects, total_affected=1,
        )
        engine = MagicMock()
        engine.analyze_intervention.return_value = ir
        mock_get_engine.return_value = engine

        out = causal_analyze_intervention("cpu", delta=10.0)

        assert "Intervention Analysis: cpu" in out
        assert "Δ+10.0" in out
        assert "Total affected metrics: 1" in out
        assert "latency" in out
        assert "+5.123" in out
        assert "queue" in out

    @patch(PATCH_ENGINE)
    def test_no_downstream_effects(self, mock_get_engine: MagicMock) -> None:
        """Empty downstream list shows 'No downstream effects predicted'."""
        ir = _intervention_result(downstream=[], total_affected=0)
        engine = MagicMock()
        engine.analyze_intervention.return_value = ir
        mock_get_engine.return_value = engine

        out = causal_analyze_intervention("cpu")

        assert "No downstream effects predicted." in out

    @patch(PATCH_ENGINE)
    def test_delta_formatting(self, mock_get_engine: MagicMock) -> None:
        """Positive delta renders with + sign in the header."""
        ir = _intervention_result(delta=25.0, downstream=[], total_affected=0)
        engine = MagicMock()
        engine.analyze_intervention.return_value = ir
        mock_get_engine.return_value = engine

        out = causal_analyze_intervention("mem", delta=25.0)

        assert "Δ+25.0" in out

    @patch(PATCH_ENGINE)
    def test_parameter_passthrough(self, mock_get_engine: MagicMock) -> None:
        """All parameters are forwarded to the engine."""
        engine = MagicMock()
        engine.analyze_intervention.return_value = _intervention_result(
            downstream=[], total_affected=0,
        )
        mock_get_engine.return_value = engine

        causal_analyze_intervention("x", delta=5.0, min_samples=60, max_depth=3)

        engine.analyze_intervention.assert_called_once_with(
            "x", delta=5.0, min_samples=60, max_depth=3,
        )


# ──── TestSummary ──────────────────────────────────────────────────────


class TestSummary:
    """Tests for causal_summary skill."""

    def _base_summary(self, **overrides: object) -> dict:
        base = {
            "tracked_metrics": 10,
            "total_samples": 500,
            "granger_tests_run": 45,
            "dags_built": 3,
            "significance_level": 0.05,
            "max_lag": 10,
        }
        base.update(overrides)
        return base

    @patch(PATCH_ENGINE)
    def test_basic_summary_fields(self, mock_get_engine: MagicMock) -> None:
        """Output includes all top-level summary fields."""
        engine = MagicMock()
        engine.causal_summary.return_value = self._base_summary()
        engine.strongest_causes.return_value = []
        mock_get_engine.return_value = engine

        out = causal_summary()

        assert "Tracked metrics: 10" in out
        assert "Total samples: 500" in out
        assert "Granger tests run: 45" in out
        assert "DAGs built: 3" in out
        assert "Significance level: 0.05" in out
        assert "Max lag: 10" in out

    @patch(PATCH_ENGINE)
    def test_with_current_dag(self, mock_get_engine: MagicMock) -> None:
        """Summary includes DAG section when current_dag is present."""
        dag_info = {
            "node_count": 5,
            "edge_count": 7,
            "roots": ["cpu", "mem"],
            "leaves": ["latency"],
            "build_timestamp": 1700000000.0,
        }
        engine = MagicMock()
        engine.causal_summary.return_value = self._base_summary(current_dag=dag_info)
        engine.strongest_causes.return_value = []
        mock_get_engine.return_value = engine

        out = causal_summary()

        assert "Current DAG:" in out
        assert "Nodes: 5" in out
        assert "Edges: 7" in out
        assert "cpu" in out
        assert "latency" in out

    @patch(PATCH_ENGINE)
    def test_with_strongest_causes(self, mock_get_engine: MagicMock) -> None:
        """Summary includes strongest causal relationships when available."""
        strongest = [
            {"cause": "cpu", "effect": "latency", "strength": "strong", "p_value": 0.001},
            {"cause": "mem", "effect": "gc", "strength": "moderate", "p_value": 0.03},
        ]
        engine = MagicMock()
        engine.causal_summary.return_value = self._base_summary()
        engine.strongest_causes.return_value = strongest
        mock_get_engine.return_value = engine

        out = causal_summary()

        assert "Strongest causal relationships:" in out
        assert "cpu → latency" in out
        assert "mem → gc" in out
        assert "strong" in out

    @patch(PATCH_ENGINE)
    def test_without_dag(self, mock_get_engine: MagicMock) -> None:
        """No current_dag key means DAG section is omitted."""
        engine = MagicMock()
        engine.causal_summary.return_value = self._base_summary()  # no current_dag
        engine.strongest_causes.return_value = []
        mock_get_engine.return_value = engine

        out = causal_summary()

        assert "Current DAG:" not in out
        assert "Causal Engine Summary" in out


# ──── TestFindPath ─────────────────────────────────────────────────────


class TestFindPath:
    """Tests for causal_find_path skill."""

    @patch(PATCH_ENGINE)
    def test_path_found(self, mock_get_engine: MagicMock) -> None:
        """Found path shows hop count and arrow-separated chain."""
        engine = MagicMock()
        engine.causal_path.return_value = ["cpu", "queue", "latency"]
        mock_get_engine.return_value = engine

        out = causal_find_path("cpu", "latency")

        assert "2 hops" in out
        assert "cpu → queue → latency" in out

    @patch(PATCH_ENGINE)
    def test_no_path(self, mock_get_engine: MagicMock) -> None:
        """None from engine means no causal path exists."""
        engine = MagicMock()
        engine.causal_path.return_value = None
        mock_get_engine.return_value = engine

        out = causal_find_path("a", "b")

        assert "No causal path found" in out
        assert "a" in out
        assert "b" in out

    @patch(PATCH_ENGINE)
    def test_single_hop_path(self, mock_get_engine: MagicMock) -> None:
        """Direct cause→effect is 1 hop."""
        engine = MagicMock()
        engine.causal_path.return_value = ["cpu", "latency"]
        mock_get_engine.return_value = engine

        out = causal_find_path("cpu", "latency")

        assert "1 hops" in out
        assert "cpu → latency" in out

    @patch(PATCH_ENGINE)
    def test_multi_hop_path(self, mock_get_engine: MagicMock) -> None:
        """Long chain shows correct hop count."""
        engine = MagicMock()
        engine.causal_path.return_value = ["a", "b", "c", "d", "e"]
        mock_get_engine.return_value = engine

        out = causal_find_path("a", "e")

        assert "4 hops" in out
        assert "a → b → c → d → e" in out
