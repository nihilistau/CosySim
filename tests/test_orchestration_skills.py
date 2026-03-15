"""Tests for orchestration MCP skills.

Covers all 10 skills in engine.skills.builtin.orchestration_skills:
  submit_task, get_task_result, list_task_types, get_task_metrics,
  submit_pipeline, get_pipeline_templates, get_pipeline_history,
  run_evaluation_gate, get_gate_results, get_model_health
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────


def _make_validation(ok: bool = True, errors=None, warnings=None):
    """Build a mock validation result."""
    v = MagicMock()
    v.ok = ok
    v.errors = errors or []
    v.warnings = warnings or []
    return v


def _make_task_result(
    task_id="t-1",
    status="completed",
    model="qwen3-0.6b",
    latency_ms=120.0,
    tokens_generated=50,
    tps=12.5,
    error=None,
    output="Hello world output",
    metadata=None,
):
    r = MagicMock()
    r.task_id = task_id
    r.status = status
    r.model = model
    r.latency_ms = latency_ms
    r.tokens_generated = tokens_generated
    r.tps = tps
    r.error = error
    r.output = output
    r.metadata = metadata or {"task_type": "summarize"}
    return r


def _make_pipeline_step(step_name="step1", ok=True, status="completed",
                        latency_ms=80.0, tokens_generated=30, error=None):
    s = MagicMock()
    s.step_name = step_name
    s.ok = ok
    s.status = status
    s.latency_ms = latency_ms
    s.tokens_generated = tokens_generated
    s.error = error
    return s


def _make_pipeline_result(
    pipeline_name="eval-pipeline",
    pipeline_id="p-42",
    status="completed",
    total_latency_ms=200.0,
    total_tokens=60,
    success_rate=1.0,
    error=None,
    steps=None,
    final_output="Pipeline done",
):
    r = MagicMock()
    r.pipeline_name = pipeline_name
    r.pipeline_id = pipeline_id
    r.status = status
    r.total_latency_ms = total_latency_ms
    r.total_tokens = total_tokens
    r.success_rate = success_rate
    r.error = error
    r.steps = steps or [_make_pipeline_step()]
    r.final_output = final_output
    return r


def _make_gate_result(
    model_id="qwen3-0.6b",
    model_type="general",
    policy="NO_REGRESSION",
    passed=True,
    recommendation="promote",
    reason="All metrics improved",
    scores_before=None,
    scores_after=None,
    delta=None,
    delta_pct=None,
):
    r = MagicMock()
    r.model_id = model_id
    r.model_type = model_type
    r.policy = policy
    r.passed = passed
    r.recommendation = recommendation
    r.reason = reason
    r.scores_before = scores_before or {"accuracy": 0.8, "overall_score": 0.75}
    r.scores_after = scores_after or {"accuracy": 0.85, "overall_score": 0.80}
    r.delta = delta or {"accuracy": 0.05, "overall_score": 0.05}
    r.delta_pct = delta_pct or {"accuracy": 6.25, "overall_score": 6.67}
    return r


# ── 1. submit_task ───────────────────────────────────────────


class TestSubmitTask:
    """Tests for the submit_task skill."""

    @patch("engine.skills.builtin.orchestration_skills.LMSTaskBridge", create=True)
    def test_submit_valid_spec(self, _mock_bridge_cls):
        mock_bridge = MagicMock()
        mock_bridge.submit.return_value = "task-abc"
        _mock_bridge_cls.return_value = mock_bridge

        mock_spec = MagicMock()
        mock_spec.to_submit_kwargs.return_value = {"prompt": "hi", "task_type": "evaluate"}

        mock_validation = _make_validation(ok=True, warnings=[])

        with patch(
            "engine.nexus.task_spec.TaskSpec", return_value=mock_spec
        ), patch(
            "engine.nexus.task_spec.validate_spec", return_value=mock_validation
        ), patch(
            "engine.nexus.lms_task_bridge.LMSTaskBridge", return_value=mock_bridge
        ):
            from engine.skills.builtin.orchestration_skills import submit_task

            result = submit_task("evaluate", "Evaluate this text")

        assert "Task Submitted" in result
        assert "task-abc" in result

    @patch("engine.skills.builtin.orchestration_skills.LMSTaskBridge", create=True)
    def test_submit_validation_failure(self, _mock_bridge_cls):
        mock_validation = _make_validation(
            ok=False,
            errors=["Invalid task_type 'bogus'"],
            warnings=["Model not specified"],
        )

        with patch(
            "engine.nexus.task_spec.TaskSpec", return_value=MagicMock()
        ), patch(
            "engine.nexus.task_spec.validate_spec", return_value=mock_validation
        ), patch(
            "engine.nexus.lms_task_bridge.LMSTaskBridge", return_value=MagicMock()
        ):
            from engine.skills.builtin.orchestration_skills import submit_task

            result = submit_task("bogus", "prompt")

        assert "Validation Failed" in result
        assert "Invalid task_type" in result
        assert "WARN" in result

    def test_submit_exception_handling(self):
        with patch(
            "engine.nexus.task_spec.TaskSpec",
            side_effect=RuntimeError("spec creation broke"),
        ), patch(
            "engine.nexus.lms_task_bridge.LMSTaskBridge", return_value=MagicMock()
        ):
            from engine.skills.builtin.orchestration_skills import submit_task

            result = submit_task("evaluate", "prompt")

        assert "failed" in result.lower()
        assert "spec creation broke" in result

    def test_submit_with_warnings_on_success(self):
        mock_bridge = MagicMock()
        mock_bridge.submit.return_value = "task-w1"

        mock_spec = MagicMock()
        mock_spec.to_submit_kwargs.return_value = {"prompt": "x"}

        mock_validation = _make_validation(ok=True, warnings=["Timeout is low"])

        with patch(
            "engine.nexus.task_spec.TaskSpec", return_value=mock_spec
        ), patch(
            "engine.nexus.task_spec.validate_spec", return_value=mock_validation
        ), patch(
            "engine.nexus.lms_task_bridge.LMSTaskBridge", return_value=mock_bridge
        ):
            from engine.skills.builtin.orchestration_skills import submit_task

            result = submit_task("summarize", "text", timeout_s=5)

        assert "Task Submitted" in result
        assert "Timeout is low" in result


# ── 2. get_task_result ───────────────────────────────────────


class TestGetTaskResult:
    """Tests for the get_task_result skill."""

    def test_get_result_completed_with_validation(self):
        task_res = _make_task_result()

        mock_validated = MagicMock()
        mock_validated.schema_match = True
        mock_validated.quality_score = 0.92
        mock_validated.validation_errors = []

        with patch(
            "engine.nexus.lms_task_bridge.LMSTaskBridge",
            return_value=MagicMock(get_result=MagicMock(return_value=task_res)),
        ), patch(
            "engine.nexus.task_spec.validate_result", return_value=mock_validated
        ):
            from engine.skills.builtin.orchestration_skills import get_task_result

            result = get_task_result("t-1")

        assert "Task Result" in result
        assert "t-1" in result
        assert "0.92" in result
        assert "Hello world output" in result

    def test_get_result_not_found(self):
        with patch(
            "engine.nexus.lms_task_bridge.LMSTaskBridge",
            return_value=MagicMock(get_result=MagicMock(return_value=None)),
        ), patch(
            "engine.nexus.task_spec.validate_result", return_value=MagicMock()
        ):
            from engine.skills.builtin.orchestration_skills import get_task_result

            result = get_task_result("unknown-id")

        assert "pending or unknown" in result

    def test_get_result_with_error(self):
        task_res = _make_task_result(status="failed", error="OOM", output="")

        with patch(
            "engine.nexus.lms_task_bridge.LMSTaskBridge",
            return_value=MagicMock(get_result=MagicMock(return_value=task_res)),
        ), patch(
            "engine.nexus.task_spec.validate_result", return_value=MagicMock()
        ):
            from engine.skills.builtin.orchestration_skills import get_task_result

            result = get_task_result("t-err")

        assert "Error: OOM" in result

    def test_get_result_exception(self):
        with patch(
            "engine.nexus.lms_task_bridge.LMSTaskBridge",
            side_effect=RuntimeError("bridge down"),
        ):
            from engine.skills.builtin.orchestration_skills import get_task_result

            result = get_task_result("t-crash")

        assert "Failed to get task result" in result


# ── 3. list_task_types ───────────────────────────────────────


class TestListTaskTypes:
    """Tests for the list_task_types skill."""

    def test_list_types_with_schemas(self):
        mock_schema = MagicMock()
        mock_schema.min_length = 10
        mock_schema.max_length = 5000
        mock_schema.required_patterns = ["pattern1"]
        mock_schema.expected_sections = ["intro", "conclusion"]
        mock_schema.quality_rubric = {"accuracy": 0.4, "coherence": 0.6}

        with patch(
            "engine.nexus.task_spec.VALID_TASK_TYPES", {"evaluate", "summarize"}
        ), patch(
            "engine.nexus.task_spec.BUILTIN_SCHEMAS", {}
        ), patch(
            "engine.nexus.task_spec.get_schema", return_value=mock_schema
        ):
            from engine.skills.builtin.orchestration_skills import list_task_types

            result = list_task_types()

        assert "Available Task Types" in result
        assert "evaluate" in result
        assert "summarize" in result
        assert "Min length: 10" in result
        assert "intro" in result
        assert "Total: 2" in result

    def test_list_types_no_schema(self):
        with patch(
            "engine.nexus.task_spec.VALID_TASK_TYPES", {"custom_type"}
        ), patch(
            "engine.nexus.task_spec.BUILTIN_SCHEMAS", {}
        ), patch(
            "engine.nexus.task_spec.get_schema", return_value=None
        ):
            from engine.skills.builtin.orchestration_skills import list_task_types

            result = list_task_types()

        assert "baseline scoring only" in result

    def test_list_types_exception(self):
        with patch(
            "engine.nexus.task_spec.get_schema",
            side_effect=RuntimeError("schema lookup failed"),
        ), patch(
            "engine.nexus.task_spec.VALID_TASK_TYPES", {"evaluate"}
        ), patch(
            "engine.nexus.task_spec.BUILTIN_SCHEMAS", {}
        ):
            from engine.skills.builtin.orchestration_skills import list_task_types

            result = list_task_types()

        assert "Failed to list task types" in result


# ── 4. get_task_metrics ──────────────────────────────────────


class TestGetTaskMetrics:
    """Tests for the get_task_metrics skill."""

    def test_metrics_with_per_model(self):
        stats = {
            "queue": {"size": 3, "total_enqueued": 100, "total_dequeued": 97},
            "workers_running": 2,
            "workers": 4,
            "total_tasks": 97,
            "success_rate": 0.95,
            "avg_latency_ms": 450.0,
            "per_model": {
                "qwen3-0.6b": {
                    "total": 50,
                    "successes": 48,
                    "avg_latency_ms": 300.0,
                },
                "llama-70b": {
                    "total": 47,
                    "successes": 44,
                    "avg_latency_ms": 600.0,
                },
            },
        }
        mock_bridge = MagicMock()
        mock_bridge.queue_stats.return_value = stats

        with patch(
            "engine.nexus.lms_task_bridge.LMSTaskBridge",
            return_value=mock_bridge,
        ):
            from engine.skills.builtin.orchestration_skills import get_task_metrics

            result = get_task_metrics(hours=12)

        assert "Task Metrics (last 12h window)" in result
        assert "Depth: 3" in result
        assert "95.0%" in result
        assert "qwen3-0.6b" in result
        assert "llama-70b" in result

    def test_metrics_no_per_model(self):
        stats = {
            "queue": {"size": 0, "total_enqueued": 0, "total_dequeued": 0},
            "workers_running": 0,
            "workers": 0,
            "total_tasks": 0,
            "success_rate": 0,
            "avg_latency_ms": 0,
            "per_model": {},
        }
        mock_bridge = MagicMock()
        mock_bridge.queue_stats.return_value = stats

        with patch(
            "engine.nexus.lms_task_bridge.LMSTaskBridge",
            return_value=mock_bridge,
        ):
            from engine.skills.builtin.orchestration_skills import get_task_metrics

            result = get_task_metrics()

        assert "No per-model metrics" in result

    def test_metrics_exception(self):
        with patch(
            "engine.nexus.lms_task_bridge.LMSTaskBridge",
            side_effect=ConnectionError("server offline"),
        ):
            from engine.skills.builtin.orchestration_skills import get_task_metrics

            result = get_task_metrics()

        assert "Failed to get task metrics" in result


# ── 5. submit_pipeline ───────────────────────────────────────


class TestSubmitPipeline:
    """Tests for the submit_pipeline skill."""

    def test_submit_pipeline_success(self):
        mock_pipeline = MagicMock()
        mock_factory = MagicMock(return_value=mock_pipeline)
        mock_executor = MagicMock()
        mock_executor.execute.return_value = _make_pipeline_result()

        with patch(
            "engine.nexus.task_pipeline.get_template", return_value=mock_factory
        ), patch(
            "engine.nexus.task_pipeline.PIPELINE_TEMPLATES", {"eval": mock_factory}
        ), patch(
            "engine.nexus.task_pipeline.get_pipeline_executor",
            return_value=mock_executor,
        ):
            from engine.skills.builtin.orchestration_skills import submit_pipeline

            result = submit_pipeline("eval", "Summarize this")

        assert "Pipeline Result" in result
        assert "eval-pipeline" in result
        assert "completed" in result
        assert "Pipeline done" in result

    def test_submit_pipeline_unknown_template(self):
        with patch(
            "engine.nexus.task_pipeline.get_template", return_value=None
        ), patch(
            "engine.nexus.task_pipeline.PIPELINE_TEMPLATES",
            {"real_one": MagicMock()},
        ), patch(
            "engine.nexus.task_pipeline.get_pipeline_executor",
            return_value=MagicMock(),
        ):
            from engine.skills.builtin.orchestration_skills import submit_pipeline

            result = submit_pipeline("nonexistent", "text")

        assert "Unknown template" in result
        assert "real_one" in result

    def test_submit_pipeline_with_error_step(self):
        failed_step = _make_pipeline_step(
            step_name="step2", ok=False, status="failed",
            error="Model timeout"
        )
        pipeline_res = _make_pipeline_result(
            status="partial",
            success_rate=0.5,
            error="Step 2 failed",
            steps=[_make_pipeline_step(), failed_step],
            final_output="",
        )
        mock_factory = MagicMock(return_value=MagicMock())
        mock_executor = MagicMock()
        mock_executor.execute.return_value = pipeline_res

        with patch(
            "engine.nexus.task_pipeline.get_template", return_value=mock_factory
        ), patch(
            "engine.nexus.task_pipeline.PIPELINE_TEMPLATES", {"p": mock_factory}
        ), patch(
            "engine.nexus.task_pipeline.get_pipeline_executor",
            return_value=mock_executor,
        ):
            from engine.skills.builtin.orchestration_skills import submit_pipeline

            result = submit_pipeline("p", "input")

        assert "Step 2 failed" in result
        assert "Model timeout" in result

    def test_submit_pipeline_exception(self):
        with patch(
            "engine.nexus.task_pipeline.get_template",
            side_effect=ImportError("no pipeline module"),
        ):
            from engine.skills.builtin.orchestration_skills import submit_pipeline

            result = submit_pipeline("t", "x")

        assert "Pipeline execution failed" in result


# ── 6. get_pipeline_templates ────────────────────────────────


class TestGetPipelineTemplates:
    """Tests for the get_pipeline_templates skill."""

    def test_list_templates(self):
        templates = [
            {"name": "eval-pipeline", "description": "Evaluate and score"},
            {"name": "summarize-pipeline", "description": "Multi-stage summary"},
        ]
        with patch(
            "engine.nexus.task_pipeline.list_templates", return_value=templates
        ):
            from engine.skills.builtin.orchestration_skills import get_pipeline_templates

            result = get_pipeline_templates()

        assert "Pipeline Templates" in result
        assert "eval-pipeline" in result
        assert "summarize-pipeline" in result
        assert "Total: 2" in result

    def test_list_templates_empty(self):
        with patch(
            "engine.nexus.task_pipeline.list_templates", return_value=[]
        ):
            from engine.skills.builtin.orchestration_skills import get_pipeline_templates

            result = get_pipeline_templates()

        assert "No pipeline templates registered" in result

    def test_list_templates_exception(self):
        with patch(
            "engine.nexus.task_pipeline.list_templates",
            side_effect=RuntimeError("boom"),
        ):
            from engine.skills.builtin.orchestration_skills import get_pipeline_templates

            result = get_pipeline_templates()

        assert "Failed to list pipeline templates" in result


# ── 7. get_pipeline_history ──────────────────────────────────


class TestGetPipelineHistory:
    """Tests for the get_pipeline_history skill."""

    def test_history_with_runs(self):
        history = [
            {
                "status": "completed",
                "name": "eval-pipeline",
                "total_latency_ms": 150.0,
                "total_tokens": 75,
                "completed_at": 1700000000.0,
            },
            {
                "status": "failed",
                "name": "sum-pipeline",
                "total_latency_ms": 50.0,
                "total_tokens": 10,
                "completed_at": 1699999000.0,
                "error": "Step 3 OOM",
            },
        ]
        mock_executor = MagicMock()
        mock_executor.get_history.return_value = history

        with patch(
            "engine.nexus.task_pipeline.get_pipeline_executor",
            return_value=mock_executor,
        ):
            from engine.skills.builtin.orchestration_skills import get_pipeline_history

            result = get_pipeline_history(limit=5)

        assert "Pipeline History" in result
        assert "eval-pipeline" in result
        assert "Step 3 OOM" in result
        assert "Showing 2 of last 5 runs" in result

    def test_history_empty(self):
        mock_executor = MagicMock()
        mock_executor.get_history.return_value = []

        with patch(
            "engine.nexus.task_pipeline.get_pipeline_executor",
            return_value=mock_executor,
        ):
            from engine.skills.builtin.orchestration_skills import get_pipeline_history

            result = get_pipeline_history()

        assert "No pipeline runs recorded" in result

    def test_history_exception(self):
        with patch(
            "engine.nexus.task_pipeline.get_pipeline_executor",
            side_effect=RuntimeError("db locked"),
        ):
            from engine.skills.builtin.orchestration_skills import get_pipeline_history

            result = get_pipeline_history()

        assert "Failed to get pipeline history" in result


# ── 8. run_evaluation_gate ───────────────────────────────────


class TestRunEvaluationGate:
    """Tests for the run_evaluation_gate skill."""

    def test_gate_pass(self):
        gate_result = _make_gate_result(passed=True)
        mock_gate = MagicMock()
        mock_gate.run_gate.return_value = gate_result

        with patch("training.evaluation_gate.get_evaluation_gate", return_value=mock_gate), \
             patch("training.evaluation_gate.BenchmarkSpec", MagicMock()), \
             patch("training.evaluation_gate.GatePolicy") as mock_policy, \
             patch("training.evaluation_gate.DEFAULT_BENCHMARK_PROMPTS", {
                 "general": ["prompt1", "prompt2"],
             }):
            mock_policy.NO_REGRESSION = "NO_REGRESSION"
            from engine.skills.builtin.orchestration_skills import run_evaluation_gate

            result = run_evaluation_gate("qwen3-0.6b", "general")

        assert "PASSED" in result
        assert "promote" in result
        assert "accuracy" in result

    def test_gate_fail(self):
        gate_result = _make_gate_result(
            passed=False,
            recommendation="reject",
            reason="Accuracy regressed by 5%",
            scores_before={"accuracy": 0.90},
            scores_after={"accuracy": 0.85},
            delta={"accuracy": -0.05},
            delta_pct={"accuracy": -5.6},
        )
        mock_gate = MagicMock()
        mock_gate.run_gate.return_value = gate_result

        with patch("training.evaluation_gate.get_evaluation_gate", return_value=mock_gate), \
             patch("training.evaluation_gate.BenchmarkSpec", MagicMock()), \
             patch("training.evaluation_gate.GatePolicy") as mock_policy, \
             patch("training.evaluation_gate.DEFAULT_BENCHMARK_PROMPTS", {
                 "general": ["p1"],
             }):
            mock_policy.NO_REGRESSION = "NO_REGRESSION"
            from engine.skills.builtin.orchestration_skills import run_evaluation_gate

            result = run_evaluation_gate("bad-model", "general")

        assert "FAILED" in result
        assert "reject" in result
        assert "Accuracy regressed" in result

    def test_gate_exception(self):
        with patch(
            "training.evaluation_gate.get_evaluation_gate",
            side_effect=ImportError("no training module"),
        ):
            from engine.skills.builtin.orchestration_skills import run_evaluation_gate

            result = run_evaluation_gate("model-x")

        assert "Evaluation gate failed" in result


# ── 9. get_gate_results ──────────────────────────────────────


class TestGetGateResults:
    """Tests for the get_gate_results skill."""

    def test_get_results_found(self):
        history = [
            {
                "passed": True,
                "model_id": "qwen3-0.6b",
                "model_type": "general",
                "policy": "NO_REGRESSION",
                "recommendation": "promote",
                "timestamp": 1700000000.0,
            },
            {
                "passed": False,
                "model_id": "llama-7b",
                "model_type": "router",
                "policy": "NO_REGRESSION",
                "recommendation": "reject",
                "timestamp": 1699999000.0,
            },
        ]
        mock_gate = MagicMock()
        mock_gate.get_gate_history.return_value = history

        with patch(
            "training.evaluation_gate.get_evaluation_gate",
            return_value=mock_gate,
        ):
            from engine.skills.builtin.orchestration_skills import get_gate_results

            result = get_gate_results()

        assert "Gate History" in result
        assert "1/2 passed" in result
        assert "1/2 failed" in result

    def test_get_results_empty(self):
        mock_gate = MagicMock()
        mock_gate.get_gate_history.return_value = []

        with patch(
            "training.evaluation_gate.get_evaluation_gate",
            return_value=mock_gate,
        ):
            from engine.skills.builtin.orchestration_skills import get_gate_results

            result = get_gate_results(model_id="router")

        assert "No gate results found" in result
        assert "router" in result

    def test_get_results_exception(self):
        with patch(
            "training.evaluation_gate.get_evaluation_gate",
            side_effect=RuntimeError("db crash"),
        ):
            from engine.skills.builtin.orchestration_skills import get_gate_results

            result = get_gate_results()

        assert "Failed to get gate results" in result


# ── 10. get_model_health ─────────────────────────────────────


class TestGetModelHealth:
    """Tests for the get_model_health skill."""

    def test_health_full_data(self):
        gate_history = [
            {"passed": True} for _ in range(6)
        ] + [
            {"passed": False} for _ in range(4)
        ]

        bench_history = [
            {
                "model_type": "general",
                "scores": json.dumps({"accuracy": 0.88, "overall": 0.85}),
                "latency_stats": json.dumps({"mean": 1.2, "p95": 2.5}),
            },
            {
                "model_type": "general",
                "scores": json.dumps({"accuracy": 0.84}),
                "latency_stats": None,
            },
        ]

        mock_gate = MagicMock()
        mock_gate.get_gate_history.return_value = gate_history
        mock_gate.get_benchmark_history.return_value = bench_history

        with patch(
            "training.evaluation_gate.get_evaluation_gate",
            return_value=mock_gate,
        ):
            from engine.skills.builtin.orchestration_skills import get_model_health

            result = get_model_health()

        assert "Model Health Summary" in result
        assert "6/10 passed" in result
        assert "60%" in result
        assert "improving" in result or "stable" in result or "declining" in result
        assert "0.880" in result  # latest accuracy
        assert "Mean: 1.2" in result

    def test_health_no_gate_history(self):
        mock_gate = MagicMock()
        mock_gate.get_gate_history.return_value = []
        mock_gate.get_benchmark_history.return_value = []

        with patch(
            "training.evaluation_gate.get_evaluation_gate",
            return_value=mock_gate,
        ):
            from engine.skills.builtin.orchestration_skills import get_model_health

            result = get_model_health(model_id="router")

        assert "No gate history" in result
        assert "No benchmark history" in result

    def test_health_with_string_scores(self):
        """Scores stored as JSON strings should be parsed correctly."""
        bench_history = [
            {
                "model_type": "router",
                "scores": '{"accuracy": 0.91}',
                "latency_stats": '{"mean": 0.8, "max": 1.5}',
            },
        ]
        mock_gate = MagicMock()
        mock_gate.get_gate_history.return_value = []
        mock_gate.get_benchmark_history.return_value = bench_history

        with patch(
            "training.evaluation_gate.get_evaluation_gate",
            return_value=mock_gate,
        ):
            from engine.skills.builtin.orchestration_skills import get_model_health

            result = get_model_health()

        assert "0.910" in result

    def test_health_exception(self):
        with patch(
            "training.evaluation_gate.get_evaluation_gate",
            side_effect=RuntimeError("gate broken"),
        ):
            from engine.skills.builtin.orchestration_skills import get_model_health

            result = get_model_health()

        assert "Failed to get model health" in result

    def test_health_trend_declining(self):
        """When recent results are worse than prior, trend should show declining."""
        gate_history = (
            [{"passed": False}] * 5 + [{"passed": True}] * 5
        )
        mock_gate = MagicMock()
        mock_gate.get_gate_history.return_value = gate_history
        mock_gate.get_benchmark_history.return_value = []

        with patch(
            "training.evaluation_gate.get_evaluation_gate",
            return_value=mock_gate,
        ):
            from engine.skills.builtin.orchestration_skills import get_model_health

            result = get_model_health()

        assert "declining" in result


# ── Helpers unit tests ───────────────────────────────────────


class TestHelpers:
    """Tests for the module-level helper functions."""

    def test_safe_json_normal(self):
        from engine.skills.builtin.orchestration_skills import _safe_json

        result = _safe_json({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result

    def test_safe_json_non_serializable(self):
        from engine.skills.builtin.orchestration_skills import _safe_json

        result = _safe_json(object())
        assert isinstance(result, str)

    def test_ts_with_epoch(self):
        from engine.skills.builtin.orchestration_skills import _ts

        result = _ts(1700000000.0)
        assert "2023" in result

    def test_ts_with_none(self):
        from engine.skills.builtin.orchestration_skills import _ts

        assert _ts(None) == "n/a"
        assert _ts(0) == "n/a"

    def test_duration_ms_milliseconds(self):
        from engine.skills.builtin.orchestration_skills import _duration_ms

        assert _duration_ms(500) == "500ms"

    def test_duration_ms_seconds(self):
        from engine.skills.builtin.orchestration_skills import _duration_ms

        assert "s" in _duration_ms(5000)

    def test_duration_ms_minutes(self):
        from engine.skills.builtin.orchestration_skills import _duration_ms

        assert "m" in _duration_ms(120_000)

    def test_duration_ms_none(self):
        from engine.skills.builtin.orchestration_skills import _duration_ms

        assert _duration_ms(None) == "n/a"
