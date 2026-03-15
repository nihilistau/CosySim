"""Tests for engine.nexus.task_pipeline.

Covers validation, execution with all failure modes, data-flow through
transforms and conditions, StepResult / PipelineResult properties,
PipelineExecutor persistence, and built-in templates.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import engine.nexus.lms_task_bridge as _lms_bridge_mod

import pytest

from engine.nexus.task_pipeline import (
    PIPELINE_TEMPLATES,
    FailureMode,
    PipelineExecutor,
    PipelineResult,
    PipelineStep,
    StepResult,
    TaskPipeline,
    get_pipeline_executor,
    get_template,
    list_templates,
)
from engine.nexus.task_spec import TaskSpec


# ──── Mock Helpers ────


@dataclass
class MockTaskResult:
    """Minimal stand-in for the real TaskResult returned by LMSTaskBridge."""

    ok: bool = True
    output: str = "mock output"
    error: str = ""
    status: str = "completed"
    tokens_generated: int = 50
    latency_ms: float = 100.0
    model: str = "test-model"


def _make_bridge(result: MockTaskResult | None = None) -> MagicMock:
    """Return a MagicMock bridge whose run_task returns *result*."""
    bridge = MagicMock()
    bridge.run_task.return_value = result or MockTaskResult()
    return bridge


def _simple_spec(task_type: str = "summarize", prompt: str = "do it") -> TaskSpec:
    """Build a minimal valid TaskSpec."""
    return TaskSpec(task_type=task_type, prompt=prompt)


def _one_step_pipeline(
    name: str = "test_pipe",
    step_name: str = "step1",
    **step_kw: Any,
) -> TaskPipeline:
    """Build a single-step pipeline with optional overrides."""
    spec = step_kw.pop("spec", _simple_spec())
    return TaskPipeline(
        name=name,
        steps=[PipelineStep(name=step_name, spec=spec, **step_kw)],
    )


# ──── Pipeline Validation ────


class TestPipelineValidation:
    """Pipeline.validate() correctness."""

    def test_valid_pipeline_passes(self) -> None:
        """Pipeline with valid steps passes validation."""
        pipe = _one_step_pipeline()
        vr = pipe.validate()
        assert vr.valid is True
        assert vr.errors == []

    def test_empty_name_fails(self) -> None:
        """Pipeline with empty name fails."""
        pipe = TaskPipeline(
            name="",
            steps=[PipelineStep(name="s", spec=_simple_spec())],
        )
        vr = pipe.validate()
        assert vr.valid is False
        assert any("name" in e.lower() for e in vr.errors)

    def test_no_steps_fails(self) -> None:
        """Pipeline with zero steps fails."""
        pipe = TaskPipeline(name="empty", steps=[])
        vr = pipe.validate()
        assert vr.valid is False
        assert any("at least one step" in e.lower() for e in vr.errors)

    def test_duplicate_step_names_fail(self) -> None:
        """Two steps with the same name fail validation."""
        pipe = TaskPipeline(
            name="dup",
            steps=[
                PipelineStep(name="same", spec=_simple_spec()),
                PipelineStep(name="same", spec=_simple_spec()),
            ],
        )
        vr = pipe.validate()
        assert vr.valid is False
        assert any("duplicate" in e.lower() for e in vr.errors)

    def test_empty_prompt_with_input_transform_warns(self) -> None:
        """Empty prompt accepted when input_transform is set (warning only)."""
        pipe = TaskPipeline(
            name="xform",
            steps=[
                PipelineStep(
                    name="s",
                    spec=TaskSpec(task_type="summarize", prompt=""),
                    input_transform=lambda prev, ctx: "built prompt",
                ),
            ],
        )
        vr = pipe.validate()
        assert vr.valid is True
        assert any("input_transform" in w for w in vr.warnings)

    def test_fallback_mode_no_model_warns(self) -> None:
        """FALLBACK mode without fallback_model produces warning."""
        pipe = TaskPipeline(
            name="fb",
            steps=[
                PipelineStep(
                    name="s",
                    spec=_simple_spec(),
                    on_failure=FailureMode.FALLBACK,
                    fallback_model="",
                ),
            ],
        )
        vr = pipe.validate()
        assert vr.valid is True
        assert any("fallback" in w.lower() for w in vr.warnings)


# ──── Pipeline Execution ────


class TestPipelineExecution:
    """TaskPipeline.execute() behaviour with mocked bridge."""

    def test_single_step_success(self) -> None:
        """Single-step pipeline executes and returns completed."""
        bridge = _make_bridge()
        pipe = _one_step_pipeline()

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute(initial_input="hello")

        assert result.ok is True
        assert result.status == "completed"
        assert len(result.steps) == 1
        assert result.steps[0].ok is True
        assert result.final_output == "mock output"
        bridge.run_task.assert_called_once()

    def test_two_step_data_flow(self) -> None:
        """Step 1 output feeds into step 2."""
        bridge = MagicMock()
        bridge.run_task.side_effect = [
            MockTaskResult(output="step1 out"),
            MockTaskResult(output="step2 out"),
        ]

        pipe = TaskPipeline(
            name="flow",
            steps=[
                PipelineStep(name="a", spec=_simple_spec()),
                PipelineStep(name="b", spec=TaskSpec(task_type="classify", prompt="")),
            ],
        )

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute(initial_input="seed")

        assert result.ok is True
        assert result.final_output == "step2 out"
        # Step 2 should have received step1's output as prompt (prompt empty
        # falls through to prev_output).
        call_args = bridge.run_task.call_args_list
        assert call_args[1].kwargs.get("prompt") == "step1 out" or \
               call_args[1][1].get("prompt", call_args[1].kwargs.get("prompt")) == "step1 out"

    def test_input_transform_applied(self) -> None:
        """input_transform replaces the prompt."""
        bridge = _make_bridge()

        pipe = _one_step_pipeline(
            input_transform=lambda prev, ctx: f"transformed: {prev}",
            spec=TaskSpec(task_type="summarize", prompt="ignored"),
        )

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            pipe.execute(initial_input="raw")

        used_prompt = bridge.run_task.call_args.kwargs["prompt"]
        assert used_prompt == "transformed: raw"

    def test_output_transform_applied(self) -> None:
        """output_transform modifies the output before passing downstream."""
        bridge = _make_bridge(MockTaskResult(output="raw_out"))

        pipe = _one_step_pipeline(
            output_transform=lambda o: o.upper(),
        )

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute()

        assert result.final_output == "RAW_OUT"
        assert result.steps[0].output == "RAW_OUT"

    def test_store_as_populates_context(self) -> None:
        """store_as puts step output into context dict."""
        bridge = _make_bridge(MockTaskResult(output="stored_value"))
        pipe = _one_step_pipeline(store_as="my_key")

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute()

        assert result.context["my_key"] == "stored_value"

    def test_condition_false_skips_step(self) -> None:
        """Step with condition returning False is skipped."""
        bridge = _make_bridge()

        pipe = TaskPipeline(
            name="cond",
            steps=[
                PipelineStep(
                    name="skipped",
                    spec=_simple_spec(),
                    condition=lambda ctx: False,
                ),
                PipelineStep(name="runs", spec=_simple_spec()),
            ],
        )

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute(initial_input="data")

        assert result.ok is True
        assert result.steps[0].status == "skipped"
        assert result.steps[1].ok is True
        # Bridge called only once (skipped step doesn't call it)
        assert bridge.run_task.call_count == 1

    def test_failure_mode_stop(self) -> None:
        """STOP failure mode halts the pipeline on error."""
        bridge = _make_bridge(MockTaskResult(ok=False, error="boom", status="failed"))

        pipe = TaskPipeline(
            name="stopme",
            steps=[
                PipelineStep(
                    name="fails",
                    spec=_simple_spec(),
                    on_failure=FailureMode.STOP,
                ),
                PipelineStep(name="never_runs", spec=_simple_spec()),
            ],
        )

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute()

        assert result.ok is False
        assert result.status in ("failed", "partial")
        assert len(result.steps) == 1  # second step never added
        assert "stopped" in result.error.lower() or "boom" in result.error.lower()

    def test_failure_mode_skip(self) -> None:
        """SKIP failure mode skips the failed step and continues."""
        bridge = MagicMock()
        bridge.run_task.side_effect = [
            MockTaskResult(ok=False, error="skip me", status="failed"),
            MockTaskResult(output="second ok"),
        ]

        pipe = TaskPipeline(
            name="skipfail",
            steps=[
                PipelineStep(
                    name="flaky",
                    spec=_simple_spec(),
                    on_failure=FailureMode.SKIP,
                ),
                PipelineStep(name="solid", spec=_simple_spec()),
            ],
        )

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute(initial_input="seed")

        assert result.ok is True
        assert result.steps[0].status == "failed"
        assert result.steps[1].ok is True
        assert result.final_output == "second ok"

    def test_failure_mode_retry(self) -> None:
        """RETRY mode retries the step up to max_retries."""
        bridge = MagicMock()
        # Fail twice, then succeed on third attempt
        bridge.run_task.side_effect = [
            MockTaskResult(ok=False, error="fail1", status="failed"),
            MockTaskResult(ok=False, error="fail2", status="failed"),
            MockTaskResult(output="finally ok"),
        ]

        pipe = _one_step_pipeline(
            on_failure=FailureMode.RETRY,
            spec=TaskSpec(task_type="summarize", prompt="try", max_retries=3),
        )

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute()

        assert result.ok is True
        assert result.steps[0].status == "retried"
        assert result.steps[0].retries == 2
        assert bridge.run_task.call_count == 3

    def test_initial_input_in_context(self) -> None:
        """_initial_input is available in context dict."""
        bridge = _make_bridge()
        pipe = _one_step_pipeline()

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute(initial_input="my input text")

        assert result.context["_initial_input"] == "my input text"


# ──── StepResult / PipelineResult Properties ────


class TestStepResult:
    """StepResult dataclass behaviour."""

    def test_step_result_ok_completed(self) -> None:
        """ok is True for completed status."""
        sr = StepResult(step_name="s", step_index=0, status="completed", output="x")
        assert sr.ok is True

    def test_step_result_ok_retried(self) -> None:
        """ok is True for retried status."""
        sr = StepResult(step_name="s", step_index=0, status="retried", output="x")
        assert sr.ok is True

    def test_step_result_not_ok_failed(self) -> None:
        """ok is False for failed status."""
        sr = StepResult(step_name="s", step_index=0, status="failed", output="")
        assert sr.ok is False

    def test_step_result_to_dict(self) -> None:
        """to_dict includes all required fields."""
        sr = StepResult(
            step_name="s",
            step_index=1,
            status="completed",
            output="out",
            error="",
            latency_ms=42.0,
            tokens_generated=10,
            retries=0,
            model_used="m",
        )
        d = sr.to_dict()
        assert d["step_name"] == "s"
        assert d["step_index"] == 1
        assert d["status"] == "completed"
        assert d["ok"] is True
        assert d["latency_ms"] == 42.0
        assert d["tokens_generated"] == 10
        assert d["model_used"] == "m"


class TestPipelineResult:
    """PipelineResult dataclass behaviour."""

    @staticmethod
    def _make(
        steps: list[StepResult] | None = None,
        status: str = "completed",
    ) -> PipelineResult:
        steps = steps or []
        return PipelineResult(
            pipeline_id="p-1",
            pipeline_name="test",
            status=status,
            steps=steps,
            final_output="out",
            context={},
            total_latency_ms=100.0,
            total_tokens=50,
            started_at=0.0,
            completed_at=1.0,
        )

    def test_pipeline_result_ok(self) -> None:
        """ok is True when status is completed."""
        pr = self._make(status="completed")
        assert pr.ok is True

    def test_pipeline_result_not_ok(self) -> None:
        """ok is False when status is not completed."""
        pr = self._make(status="failed")
        assert pr.ok is False

    def test_pipeline_result_success_rate(self) -> None:
        """success_rate calculates correctly."""
        steps = [
            StepResult(step_name="a", step_index=0, status="completed", output=""),
            StepResult(step_name="b", step_index=1, status="failed", output=""),
            StepResult(step_name="c", step_index=2, status="completed", output=""),
            StepResult(step_name="d", step_index=3, status="skipped", output=""),
        ]
        pr = self._make(steps=steps, status="partial")
        assert pr.success_rate == pytest.approx(0.5)

    def test_pipeline_result_success_rate_empty(self) -> None:
        """success_rate is 0.0 when no steps."""
        pr = self._make(steps=[])
        assert pr.success_rate == 0.0

    def test_pipeline_result_to_dict(self) -> None:
        """to_dict includes all required fields."""
        pr = self._make(
            steps=[StepResult(step_name="s", step_index=0, status="completed", output="x")],
        )
        d = pr.to_dict()
        assert d["pipeline_id"] == "p-1"
        assert d["pipeline_name"] == "test"
        assert d["status"] == "completed"
        assert d["ok"] is True
        assert "success_rate" in d
        assert isinstance(d["steps"], list)
        assert d["steps"][0]["step_name"] == "s"
        assert d["total_latency_ms"] == 100.0
        assert d["total_tokens"] == 50


# ──── PipelineExecutor ────


class TestPipelineExecutor:
    """PipelineExecutor SQLite persistence and query methods."""

    @staticmethod
    def _make_executor(tmp_path: Path) -> PipelineExecutor:
        return PipelineExecutor(db_path=tmp_path / "test.db")

    def test_executor_validates_before_executing(self, tmp_path: Path) -> None:
        """Executor rejects invalid pipelines."""
        exe = self._make_executor(tmp_path)
        bad = TaskPipeline(name="", steps=[])
        result = exe.execute(bad)
        assert result.ok is False
        assert "validation" in result.error.lower()

    def test_executor_persists_result(self, tmp_path: Path) -> None:
        """Executor stores result in SQLite."""
        exe = self._make_executor(tmp_path)
        bridge = _make_bridge()
        pipe = _one_step_pipeline()

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = exe.execute(pipe, initial_input="data")

        assert result.ok is True
        # Verify we can retrieve from DB
        run = exe.get_run(result.pipeline_id)
        assert run is not None
        assert run["name"] == "test_pipe"
        assert run["status"] == "completed"

    def test_executor_get_history(self, tmp_path: Path) -> None:
        """get_history returns persisted runs."""
        exe = self._make_executor(tmp_path)
        bridge = _make_bridge()

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            exe.execute(_one_step_pipeline(name="p1"), initial_input="a")
            exe.execute(_one_step_pipeline(name="p2"), initial_input="b")

        history = exe.get_history()
        assert len(history) == 2
        names = {h["name"] for h in history}
        assert names == {"p1", "p2"}

    def test_executor_get_history_by_name(self, tmp_path: Path) -> None:
        """get_history filters by pipeline name."""
        exe = self._make_executor(tmp_path)
        bridge = _make_bridge()

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            exe.execute(_one_step_pipeline(name="target"), initial_input="a")
            exe.execute(_one_step_pipeline(name="other"), initial_input="b")

        history = exe.get_history(name="target")
        assert len(history) == 1
        assert history[0]["name"] == "target"

    def test_executor_get_run(self, tmp_path: Path) -> None:
        """get_run returns single run with steps."""
        exe = self._make_executor(tmp_path)
        bridge = _make_bridge()

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = exe.execute(_one_step_pipeline(), initial_input="x")

        run = exe.get_run(result.pipeline_id)
        assert run is not None
        assert len(run["steps"]) == 1
        assert run["steps"][0]["step_name"] == "step1"

    def test_executor_get_run_not_found(self, tmp_path: Path) -> None:
        """get_run returns None for unknown id."""
        exe = self._make_executor(tmp_path)
        assert exe.get_run("nonexistent-id") is None

    def test_executor_get_stats(self, tmp_path: Path) -> None:
        """get_stats returns aggregate statistics."""
        exe = self._make_executor(tmp_path)
        bridge = _make_bridge(MockTaskResult(tokens_generated=25))

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            exe.execute(_one_step_pipeline(name="pipe"), initial_input="a")
            exe.execute(_one_step_pipeline(name="pipe"), initial_input="b")

        stats = exe.get_stats()
        assert stats["total_runs"] == 2
        assert stats["success_rate"] == pytest.approx(1.0)
        assert stats["total_tokens"] == 50  # 25 * 2
        assert len(stats["popular_pipelines"]) >= 1
        assert stats["popular_pipelines"][0]["name"] == "pipe"

    def test_executor_get_stats_empty(self, tmp_path: Path) -> None:
        """get_stats on empty DB returns zeroes."""
        exe = self._make_executor(tmp_path)
        stats = exe.get_stats()
        assert stats["total_runs"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["total_tokens"] == 0


# ──── Singleton ────


class TestSingleton:
    """get_pipeline_executor singleton behaviour."""

    def test_singleton_returns_executor(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_pipeline_executor returns a PipelineExecutor and reuses it."""
        import engine.nexus.task_pipeline as mod

        monkeypatch.setattr(mod, "_executor_instance", None)
        exe = get_pipeline_executor(db_path=tmp_path / "singleton.db")
        assert isinstance(exe, PipelineExecutor)

        exe2 = get_pipeline_executor()
        assert exe2 is exe
        # Reset so other tests are unaffected
        monkeypatch.setattr(mod, "_executor_instance", None)


# ──── Templates ────


class TestTemplates:
    """Built-in pipeline template factories."""

    def test_review_and_fix_template(self) -> None:
        """review_and_fix creates 2-step pipeline."""
        factory = get_template("review_and_fix")
        assert factory is not None
        pipe = factory("def foo(): pass", language="python")
        assert pipe.name == "review_and_fix"
        assert len(pipe.steps) == 2
        step_names = [s.name for s in pipe.steps]
        assert "code_review" in step_names
        assert "refactor" in step_names

    def test_summarize_and_classify_template(self) -> None:
        """summarize_and_classify creates 2-step pipeline."""
        factory = get_template("summarize_and_classify")
        assert factory is not None
        pipe = factory("some long text")
        assert pipe.name == "summarize_and_classify"
        assert len(pipe.steps) == 2
        step_names = [s.name for s in pipe.steps]
        assert "summarize" in step_names
        assert "classify" in step_names

    def test_get_template_known(self) -> None:
        """get_template returns factory for known name."""
        for name in ("review_and_fix", "summarize_and_classify",
                      "security_audit", "doc_and_test"):
            assert get_template(name) is not None

    def test_get_template_unknown(self) -> None:
        """get_template returns None for unknown name."""
        assert get_template("nonexistent_template") is None

    def test_list_templates(self) -> None:
        """list_templates returns all 4 templates."""
        templates = list_templates()
        names = {t["name"] for t in templates}
        assert len(templates) >= 4
        assert {"review_and_fix", "summarize_and_classify",
                "security_audit", "doc_and_test"} <= names
        for t in templates:
            assert "name" in t
            assert "description" in t
            assert t["description"]  # non-empty description


# ──── TaskPipeline.to_dict ────


class TestPipelineToDict:
    """TaskPipeline.to_dict() serialisation."""

    def test_pipeline_to_dict(self) -> None:
        """to_dict serializes pipeline definition."""
        pipe = _one_step_pipeline(name="serial")
        d = pipe.to_dict()
        assert d["name"] == "serial"
        assert "pipeline_id" in d
        assert isinstance(d["steps"], list)
        assert len(d["steps"]) == 1
        assert d["steps"][0]["name"] == "step1"
        assert d["steps"][0]["task_type"] == "summarize"
        assert d["steps"][0]["on_failure"] == "stop"

    def test_pipeline_to_dict_with_transforms(self) -> None:
        """to_dict shows has_input_transform/has_output_transform flags."""
        pipe = _one_step_pipeline(
            input_transform=lambda prev, ctx: prev,
            output_transform=lambda o: o,
        )
        d = pipe.to_dict()
        step = d["steps"][0]
        assert step["has_input_transform"] is True
        assert step["has_output_transform"] is True

    def test_pipeline_to_dict_no_transforms(self) -> None:
        """to_dict shows False for transform flags when absent."""
        pipe = _one_step_pipeline()
        d = pipe.to_dict()
        step = d["steps"][0]
        assert step["has_input_transform"] is False
        assert step["has_output_transform"] is False


# ──── Edge Cases ────


class TestEdgeCases:
    """Additional edge-case and integration scenarios."""

    def test_metadata_passed_to_context(self) -> None:
        """Pipeline metadata is available in execution context."""
        bridge = _make_bridge()
        pipe = TaskPipeline(
            name="meta",
            steps=[PipelineStep(name="s", spec=_simple_spec())],
            metadata={"env": "test"},
        )

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute()

        assert result.context["env"] == "test"

    def test_context_merge_with_initial(self) -> None:
        """Caller-supplied context merges with pipeline metadata."""
        bridge = _make_bridge()
        pipe = TaskPipeline(
            name="merge",
            steps=[PipelineStep(name="s", spec=_simple_spec())],
            metadata={"a": 1},
        )

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute(context={"b": 2})

        assert result.context["a"] == 1
        assert result.context["b"] == 2

    def test_fallback_mode_switches_model(self) -> None:
        """FALLBACK mode switches to fallback_model on retry."""
        bridge = MagicMock()
        bridge.run_task.side_effect = [
            MockTaskResult(ok=False, error="fail", status="failed"),
            MockTaskResult(output="ok via fallback", model="fallback-m"),
        ]

        pipe = _one_step_pipeline(
            on_failure=FailureMode.FALLBACK,
            fallback_model="fallback-m",
            spec=TaskSpec(task_type="summarize", prompt="p", max_retries=2),
        )

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute()

        assert result.ok is True
        # Second call should use fallback model
        second_call = bridge.run_task.call_args_list[1]
        assert second_call.kwargs.get("model") == "fallback-m"

    def test_bridge_exception_counts_as_failure(self) -> None:
        """An exception from bridge.run_task is treated as a step failure."""
        bridge = MagicMock()
        bridge.run_task.side_effect = RuntimeError("connection lost")

        pipe = _one_step_pipeline(on_failure=FailureMode.STOP)

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute()

        assert result.ok is False
        assert result.steps[0].status == "failed"
        assert "connection lost" in result.steps[0].error

    def test_pipeline_result_total_tokens(self) -> None:
        """total_tokens sums across all steps."""
        bridge = MagicMock()
        bridge.run_task.side_effect = [
            MockTaskResult(output="a", tokens_generated=30),
            MockTaskResult(output="b", tokens_generated=70),
        ]

        pipe = TaskPipeline(
            name="tokens",
            steps=[
                PipelineStep(name="s1", spec=_simple_spec()),
                PipelineStep(name="s2", spec=_simple_spec()),
            ],
        )

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute()

        assert result.total_tokens == 100

    def test_condition_exception_skips_step(self) -> None:
        """A condition that raises is treated as False (step skipped)."""
        bridge = _make_bridge()

        def bad_condition(ctx: Dict[str, Any]) -> bool:
            raise ValueError("condition exploded")

        pipe = _one_step_pipeline(condition=bad_condition)

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute()

        assert result.ok is True
        assert result.steps[0].status == "skipped"
        bridge.run_task.assert_not_called()

    def test_output_transform_exception_uses_raw(self) -> None:
        """If output_transform raises, raw output is used."""
        bridge = _make_bridge(MockTaskResult(output="raw"))

        def bad_transform(output: str) -> str:
            raise RuntimeError("transform boom")

        pipe = _one_step_pipeline(output_transform=bad_transform)

        with patch.object(_lms_bridge_mod, "get_task_bridge", create=True, return_value=bridge):
            result = pipe.execute()

        assert result.ok is True
        assert result.final_output == "raw"
