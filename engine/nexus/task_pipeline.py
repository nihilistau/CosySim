"""Multi-step task pipeline for chaining LMStudio tasks.

Enables structured pipeline definitions where the output of one step feeds
into the next, with configurable failure handling, context accumulation,
conditional execution, and SQLite-backed history tracking.

Example usage::

    from engine.nexus.task_pipeline import (
        TaskPipeline, PipelineStep, PipelineExecutor, FailureMode,
        get_pipeline_executor, get_template,
    )
    from engine.nexus.task_spec import TaskSpec

    pipeline = TaskPipeline(
        name="my_pipeline",
        steps=[
            PipelineStep(
                name="summarize",
                spec=TaskSpec(task_type="summarize", prompt="Summarize: {input}"),
                store_as="summary",
            ),
            PipelineStep(
                name="classify",
                spec=TaskSpec(task_type="classify", prompt=""),
                input_transform=lambda prev, ctx: f"Classify: {prev}",
            ),
        ],
    )
    result = get_pipeline_executor().execute(pipeline, initial_input="long text...")

Built-in templates::

    pipe = get_template("review_and_fix")("def foo(): pass", language="python")
    result = get_pipeline_executor().execute(pipe, initial_input="def foo(): pass")
"""

from __future__ import annotations

import enum
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from engine.nexus.task_spec import TaskSpec, ValidationResult

logger = logging.getLogger(__name__)


# ──── Failure Mode ────


class FailureMode(enum.Enum):
    """How a pipeline step should handle execution failures."""

    STOP = "stop"
    SKIP = "skip"
    RETRY = "retry"
    FALLBACK = "fallback"


# ──── Pipeline Step ────


@dataclass
class PipelineStep:
    """A single step in a task pipeline.

    Attributes:
        name: Human-readable step name.
        spec: Task specification for this step.
        input_transform: Optional callable ``(prev_output, context) -> new_prompt``
            that replaces the spec prompt with a dynamically built one.
        output_transform: Optional callable ``(raw_output) -> transformed_output``
            applied to the raw LMStudio response before passing it downstream.
        on_failure: Behaviour when the step fails.
        fallback_model: Model identifier used when *on_failure* is ``FALLBACK``.
        condition: When provided, the step is skipped if this returns ``False``.
            Receives the current accumulated context dict.
        store_as: If set, the step output is stored in the context dict under
            this key so later steps (or the caller) can reference it.
    """

    name: str
    spec: TaskSpec
    input_transform: Optional[Callable[[str, Dict[str, Any]], str]] = None
    output_transform: Optional[Callable[[str], str]] = None
    on_failure: FailureMode = FailureMode.STOP
    fallback_model: str = ""
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    store_as: Optional[str] = None


# ──── Step Result ────


@dataclass
class StepResult:
    """Result from executing a single pipeline step.

    Attributes:
        step_name: Name of the step that produced this result.
        step_index: Zero-based index within the pipeline.
        status: One of ``"completed"``, ``"failed"``, ``"skipped"``, ``"retried"``.
        output: The (possibly transformed) output text.
        error: Error message if the step failed.
        latency_ms: Wall-clock time for this step in milliseconds.
        tokens_generated: Tokens produced by LMStudio.
        retries: Number of retry attempts before the final outcome.
        model_used: Model that actually served the request.
    """

    step_name: str
    step_index: int
    status: str
    output: str
    error: str = ""
    latency_ms: float = 0.0
    tokens_generated: int = 0
    retries: int = 0
    model_used: str = ""

    @property
    def ok(self) -> bool:
        """True when the step completed (possibly after retries)."""
        return self.status in ("completed", "retried")

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "step_name": self.step_name,
            "step_index": self.step_index,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "tokens_generated": self.tokens_generated,
            "retries": self.retries,
            "model_used": self.model_used,
            "ok": self.ok,
        }


# ──── Pipeline Result ────


@dataclass
class PipelineResult:
    """Result from executing a full pipeline.

    Attributes:
        pipeline_id: Unique identifier for this pipeline instance.
        pipeline_name: Human-readable name.
        status: Overall outcome — ``"completed"``, ``"failed"``, or ``"partial"``.
        steps: Ordered list of per-step results.
        final_output: Output from the last successful step.
        context: Accumulated context dict (including all ``store_as`` values).
        total_latency_ms: Wall-clock time for the entire pipeline.
        total_tokens: Sum of tokens generated across all steps.
        started_at: Monotonic timestamp when execution began.
        completed_at: Monotonic timestamp when execution ended.
        error: Error message if the pipeline did not complete.
    """

    pipeline_id: str
    pipeline_name: str
    status: str
    steps: List[StepResult]
    final_output: str
    context: Dict[str, Any]
    total_latency_ms: float
    total_tokens: int
    started_at: float
    completed_at: float
    error: str = ""

    @property
    def ok(self) -> bool:
        """True when every step completed successfully."""
        return self.status == "completed"

    @property
    def success_rate(self) -> float:
        """Fraction of steps that succeeded."""
        if not self.steps:
            return 0.0
        ok_count = sum(1 for s in self.steps if s.ok)
        return ok_count / len(self.steps)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "pipeline_id": self.pipeline_id,
            "pipeline_name": self.pipeline_name,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "final_output": self.final_output,
            "context": self.context,
            "total_latency_ms": self.total_latency_ms,
            "total_tokens": self.total_tokens,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "ok": self.ok,
            "success_rate": self.success_rate,
        }


# ──── Task Pipeline ────


class TaskPipeline:
    """Multi-step task pipeline with data flow and failure handling.

    Args:
        name: Human-readable pipeline name.
        steps: Ordered list of :class:`PipelineStep` instances.
        description: Optional longer description.
        metadata: Arbitrary key/value metadata attached to every run.
    """

    def __init__(
        self,
        name: str,
        steps: List[PipelineStep],
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.pipeline_id: str = f"pipe-{uuid.uuid4().hex[:12]}"
        self.name = name
        self.steps = list(steps)
        self.description = description
        self.metadata: Dict[str, Any] = metadata or {}

    # ── Validation ──

    def validate(self) -> ValidationResult:
        """Validate all steps before execution.

        Returns:
            A :class:`ValidationResult` aggregating per-step validation.
        """
        errors: List[str] = []
        warnings: List[str] = []

        if not self.name:
            errors.append("Pipeline name is required.")
        if not self.steps:
            errors.append("Pipeline must contain at least one step.")
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        seen_names: set[str] = set()
        for idx, step in enumerate(self.steps):
            prefix = f"Step {idx} ({step.name!r})"

            if not step.name:
                errors.append(f"Step {idx}: name is required.")
            elif step.name in seen_names:
                errors.append(f"{prefix}: duplicate step name.")
            seen_names.add(step.name)

            spec_result = step.spec.validate()
            for err in spec_result.errors:
                # An empty prompt is acceptable when an input_transform
                # will supply it at execution time.
                if "prompt" in err.lower() and step.input_transform is not None:
                    warnings.append(
                        f"{prefix}: spec prompt is empty — "
                        f"input_transform will supply it at runtime."
                    )
                else:
                    errors.append(f"{prefix}: {err}")
            for warn in spec_result.warnings:
                warnings.append(f"{prefix}: {warn}")

            if step.on_failure == FailureMode.FALLBACK and not step.fallback_model:
                warnings.append(
                    f"{prefix}: FALLBACK failure mode but no fallback_model set."
                )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ── Execution ──

    def execute(
        self,
        initial_input: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> PipelineResult:
        """Execute the pipeline step by step.

        Each step receives the output of the previous step (or *initial_input*
        for step 0).  Steps can transform inputs/outputs via their transform
        callables.  The *context* dict accumulates across steps — outputs are
        stored under each step's ``store_as`` key when set.

        Args:
            initial_input: Text fed into the first step.
            context: Initial context dict (merged with pipeline metadata).

        Returns:
            A :class:`PipelineResult` summarising the full run.
        """
        from engine.nexus.lms_task_bridge import get_task_bridge

        bridge = get_task_bridge()
        ctx: Dict[str, Any] = dict(self.metadata)
        if context:
            ctx.update(context)
        ctx["_initial_input"] = initial_input
        ctx["_pipeline_name"] = self.name
        ctx["_pipeline_id"] = self.pipeline_id

        step_results: List[StepResult] = []
        prev_output = initial_input
        final_output = initial_input
        pipeline_error = ""

        started_at = time.monotonic()

        for idx, step in enumerate(self.steps):
            # ── Condition check ──
            if step.condition is not None:
                try:
                    should_run = step.condition(ctx)
                except Exception as exc:
                    logger.warning(
                        "Step %r condition raised %s — skipping.",
                        step.name,
                        exc,
                    )
                    should_run = False

                if not should_run:
                    logger.info("Step %r skipped (condition=False).", step.name)
                    step_results.append(
                        StepResult(
                            step_name=step.name,
                            step_index=idx,
                            status="skipped",
                            output="",
                        )
                    )
                    continue

            # ── Build prompt ──
            if step.input_transform is not None:
                try:
                    prompt = step.input_transform(prev_output, ctx)
                except Exception as exc:
                    logger.error(
                        "Step %r input_transform failed: %s", step.name, exc
                    )
                    prompt = prev_output
            elif step.spec.prompt:
                prompt = step.spec.prompt
            else:
                prompt = prev_output

            # ── Execute with retries / fallback ──
            step_result = self._execute_step(
                bridge, step, idx, prompt, ctx
            )
            step_results.append(step_result)

            if step_result.ok:
                prev_output = step_result.output
                final_output = step_result.output
                if step.store_as:
                    ctx[step.store_as] = step_result.output
            else:
                # Handle failure modes
                if step.on_failure == FailureMode.STOP:
                    pipeline_error = (
                        f"Pipeline stopped at step {idx} ({step.name!r}): "
                        f"{step_result.error}"
                    )
                    logger.error(pipeline_error)
                    break

                if step.on_failure == FailureMode.SKIP:
                    logger.warning(
                        "Step %r failed — skipping (output empty).", step.name
                    )
                    if step.store_as:
                        ctx[step.store_as] = ""
                    # prev_output stays unchanged so the next step gets the
                    # last successful output (not the empty skip).
                    continue

                # RETRY and FALLBACK failures that exhausted retries already
                # fell through _execute_step; treat like STOP here.
                pipeline_error = (
                    f"Pipeline stopped at step {idx} ({step.name!r}) after "
                    f"exhausting retries: {step_result.error}"
                )
                logger.error(pipeline_error)
                break

        completed_at = time.monotonic()
        total_latency = (completed_at - started_at) * 1000.0
        total_tokens = sum(s.tokens_generated for s in step_results)

        # Determine overall status
        if pipeline_error:
            any_ok = any(s.ok for s in step_results)
            status = "partial" if any_ok else "failed"
        else:
            status = "completed"

        return PipelineResult(
            pipeline_id=self.pipeline_id,
            pipeline_name=self.name,
            status=status,
            steps=step_results,
            final_output=final_output,
            context=ctx,
            total_latency_ms=total_latency,
            total_tokens=total_tokens,
            started_at=started_at,
            completed_at=completed_at,
            error=pipeline_error,
        )

    # ── Internal helpers ──

    def _execute_step(
        self,
        bridge: Any,
        step: PipelineStep,
        idx: int,
        prompt: str,
        ctx: Dict[str, Any],
    ) -> StepResult:
        """Execute a single step with retry / fallback logic.

        Args:
            bridge: An :class:`LMSTaskBridge` instance.
            step: The pipeline step definition.
            idx: Zero-based step index.
            prompt: The resolved prompt text.
            ctx: Accumulated context dict.

        Returns:
            A :class:`StepResult`.
        """
        max_attempts = step.spec.max_retries + 1
        if step.on_failure not in (FailureMode.RETRY, FailureMode.FALLBACK):
            max_attempts = 1

        last_error = ""
        retries = 0
        model_override = step.spec.model

        for attempt in range(max_attempts):
            if attempt > 0:
                retries = attempt
                if step.on_failure == FailureMode.FALLBACK and step.fallback_model:
                    model_override = step.fallback_model
                    logger.info(
                        "Step %r attempt %d — falling back to model %r.",
                        step.name,
                        attempt + 1,
                        model_override,
                    )
                else:
                    logger.info(
                        "Step %r retry attempt %d/%d.",
                        step.name,
                        attempt + 1,
                        max_attempts,
                    )

            t0 = time.monotonic()
            try:
                task_result = bridge.run_task(
                    task_type=step.spec.task_type,
                    prompt=prompt,
                    context=ctx,
                    model=model_override,
                )
            except Exception as exc:
                elapsed = (time.monotonic() - t0) * 1000.0
                last_error = f"Exception: {exc}"
                logger.error(
                    "Step %r attempt %d raised: %s", step.name, attempt + 1, exc
                )
                if attempt == max_attempts - 1:
                    return StepResult(
                        step_name=step.name,
                        step_index=idx,
                        status="failed",
                        output="",
                        error=last_error,
                        latency_ms=elapsed,
                        retries=retries,
                        model_used=model_override,
                    )
                continue

            elapsed = (time.monotonic() - t0) * 1000.0

            if task_result.ok:
                output = task_result.output
                if step.output_transform is not None:
                    try:
                        output = step.output_transform(output)
                    except Exception as exc:
                        logger.warning(
                            "Step %r output_transform failed: %s — "
                            "using raw output.",
                            step.name,
                            exc,
                        )
                        output = task_result.output

                status = "completed" if retries == 0 else "retried"
                return StepResult(
                    step_name=step.name,
                    step_index=idx,
                    status=status,
                    output=output,
                    latency_ms=elapsed,
                    tokens_generated=task_result.tokens_generated,
                    retries=retries,
                    model_used=task_result.model or model_override,
                )

            last_error = task_result.error or f"Task status: {task_result.status}"
            logger.warning(
                "Step %r attempt %d failed: %s",
                step.name,
                attempt + 1,
                last_error,
            )

        return StepResult(
            step_name=step.name,
            step_index=idx,
            status="failed",
            output="",
            error=last_error,
            latency_ms=0.0,
            retries=retries,
            model_used=model_override,
        )

    # ── Serialisation ──

    def to_dict(self) -> Dict[str, Any]:
        """Serialise pipeline definition to a plain dict."""
        return {
            "pipeline_id": self.pipeline_id,
            "name": self.name,
            "description": self.description,
            "metadata": self.metadata,
            "steps": [
                {
                    "name": s.name,
                    "task_type": s.spec.task_type,
                    "on_failure": s.on_failure.value,
                    "fallback_model": s.fallback_model,
                    "store_as": s.store_as,
                    "has_input_transform": s.input_transform is not None,
                    "has_output_transform": s.output_transform is not None,
                    "has_condition": s.condition is not None,
                }
                for s in self.steps
            ],
        }


# ──── Pipeline Executor (History + Persistence) ────


_DEFAULT_DB_DIR = Path("data")
_OUTPUT_PREVIEW_LEN = 500

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL,
    steps_json      TEXT NOT NULL,
    final_output    TEXT NOT NULL DEFAULT '',
    context_json    TEXT NOT NULL DEFAULT '{}',
    total_latency_ms REAL NOT NULL DEFAULT 0.0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    started_at      REAL NOT NULL,
    completed_at    REAL NOT NULL,
    error           TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS step_results (
    id              TEXT PRIMARY KEY,
    pipeline_run_id TEXT NOT NULL,
    step_name       TEXT NOT NULL,
    step_index      INTEGER NOT NULL,
    status          TEXT NOT NULL,
    output_preview  TEXT NOT NULL DEFAULT '',
    error           TEXT NOT NULL DEFAULT '',
    latency_ms      REAL NOT NULL DEFAULT 0.0,
    tokens          INTEGER NOT NULL DEFAULT 0,
    retries         INTEGER NOT NULL DEFAULT 0,
    model           TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_step_results_run
    ON step_results(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_name
    ON pipeline_runs(name);
"""


class PipelineExecutor:
    """Executes pipelines and tracks history in SQLite.

    Uses WAL mode and thread-local connections for safe concurrent access.

    Args:
        db_path: Path to the SQLite database file.  Defaults to
            ``data/task_pipeline.db``.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            db_path = _DEFAULT_DB_DIR / "task_pipeline.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    # ── DB helpers ──

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection."""
        conn: Optional[sqlite3.Connection] = getattr(
            self._local, "conn", None
        )
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        """Create tables if they do not exist."""
        conn = self._get_conn()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

    # ── Public API ──

    def execute(
        self,
        pipeline: TaskPipeline,
        initial_input: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> PipelineResult:
        """Execute a pipeline and persist results to the database.

        Args:
            pipeline: The pipeline definition to run.
            initial_input: Text fed into the first step.
            context: Initial context dict.

        Returns:
            A :class:`PipelineResult` summarising the run.
        """
        validation = pipeline.validate()
        if not validation.valid:
            logger.error(
                "Pipeline %r validation failed: %s",
                pipeline.name,
                validation.errors,
            )
            now = time.monotonic()
            return PipelineResult(
                pipeline_id=pipeline.pipeline_id,
                pipeline_name=pipeline.name,
                status="failed",
                steps=[],
                final_output="",
                context=context or {},
                total_latency_ms=0.0,
                total_tokens=0,
                started_at=now,
                completed_at=now,
                error=f"Validation failed: {'; '.join(validation.errors)}",
            )

        if validation.warnings:
            for warn in validation.warnings:
                logger.warning("Pipeline %r: %s", pipeline.name, warn)

        logger.info(
            "Executing pipeline %r (%s) with %d step(s).",
            pipeline.name,
            pipeline.pipeline_id,
            len(pipeline.steps),
        )

        result = pipeline.execute(initial_input=initial_input, context=context)
        self._persist_result(result)

        logger.info(
            "Pipeline %r finished — status=%s, steps=%d, latency=%.1fms, "
            "tokens=%d, success_rate=%.0f%%.",
            result.pipeline_name,
            result.status,
            len(result.steps),
            result.total_latency_ms,
            result.total_tokens,
            result.success_rate * 100,
        )

        return result

    def get_history(
        self,
        name: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent pipeline run summaries.

        Args:
            name: If provided, filter by pipeline name.
            limit: Maximum number of records to return.

        Returns:
            List of dicts with run metadata (most recent first).
        """
        conn = self._get_conn()
        if name:
            rows = conn.execute(
                "SELECT id, name, status, total_latency_ms, total_tokens, "
                "started_at, completed_at, error "
                "FROM pipeline_runs WHERE name = ? "
                "ORDER BY completed_at DESC LIMIT ?",
                (name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, status, total_latency_ms, total_tokens, "
                "started_at, completed_at, error "
                "FROM pipeline_runs ORDER BY completed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, pipeline_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single pipeline run with its step results.

        Args:
            pipeline_id: The pipeline run identifier.

        Returns:
            Dict with run metadata and nested ``steps`` list, or ``None``.
        """
        conn = self._get_conn()
        run_row = conn.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?",
            (pipeline_id,),
        ).fetchone()
        if run_row is None:
            return None

        step_rows = conn.execute(
            "SELECT step_name, step_index, status, output_preview, error, "
            "latency_ms, tokens, retries, model "
            "FROM step_results WHERE pipeline_run_id = ? "
            "ORDER BY step_index",
            (pipeline_id,),
        ).fetchall()

        run_dict = dict(run_row)
        run_dict["steps"] = [dict(r) for r in step_rows]
        # Deserialise JSON columns
        try:
            run_dict["steps_json"] = json.loads(run_dict.get("steps_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            run_dict["context_json"] = json.loads(
                run_dict.get("context_json", "{}")
            )
        except (json.JSONDecodeError, TypeError):
            pass
        return run_dict

    def get_stats(self) -> Dict[str, Any]:
        """Pipeline execution statistics.

        Returns:
            Dict with ``total_runs``, ``success_rate``, ``avg_duration_ms``,
            ``total_tokens``, and ``popular_pipelines``.
        """
        conn = self._get_conn()

        total_row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS ok, "
            "AVG(total_latency_ms) AS avg_dur, "
            "SUM(total_tokens) AS tokens "
            "FROM pipeline_runs"
        ).fetchone()

        total = total_row["total"] or 0
        ok_count = total_row["ok"] or 0
        avg_dur = total_row["avg_dur"] or 0.0
        tokens = total_row["tokens"] or 0

        popular_rows = conn.execute(
            "SELECT name, COUNT(*) AS runs, "
            "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS ok, "
            "AVG(total_latency_ms) AS avg_dur "
            "FROM pipeline_runs GROUP BY name ORDER BY runs DESC LIMIT 10"
        ).fetchall()

        return {
            "total_runs": total,
            "success_rate": ok_count / total if total else 0.0,
            "avg_duration_ms": round(avg_dur, 1),
            "total_tokens": tokens,
            "popular_pipelines": [
                {
                    "name": r["name"],
                    "runs": r["runs"],
                    "success_rate": (
                        r["ok"] / r["runs"] if r["runs"] else 0.0
                    ),
                    "avg_duration_ms": round(r["avg_dur"] or 0.0, 1),
                }
                for r in popular_rows
            ],
        }

    # ── Persistence helpers ──

    def _persist_result(self, result: PipelineResult) -> None:
        """Write a pipeline result and its step results to the database."""
        conn = self._get_conn()

        # Serialise context — strip non-serialisable entries
        safe_context: Dict[str, Any] = {}
        for key, val in result.context.items():
            try:
                json.dumps(val)
                safe_context[key] = val
            except (TypeError, ValueError):
                safe_context[key] = str(val)

        steps_summary = [
            {
                "name": s.step_name,
                "status": s.status,
                "latency_ms": s.latency_ms,
                "tokens": s.tokens_generated,
            }
            for s in result.steps
        ]

        try:
            conn.execute(
                "INSERT INTO pipeline_runs "
                "(id, name, status, steps_json, final_output, context_json, "
                "total_latency_ms, total_tokens, started_at, completed_at, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.pipeline_id,
                    result.pipeline_name,
                    result.status,
                    json.dumps(steps_summary),
                    result.final_output,
                    json.dumps(safe_context),
                    result.total_latency_ms,
                    result.total_tokens,
                    result.started_at,
                    result.completed_at,
                    result.error,
                ),
            )

            for step in result.steps:
                conn.execute(
                    "INSERT INTO step_results "
                    "(id, pipeline_run_id, step_name, step_index, status, "
                    "output_preview, error, latency_ms, tokens, retries, model) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"sr-{uuid.uuid4().hex[:12]}",
                        result.pipeline_id,
                        step.step_name,
                        step.step_index,
                        step.status,
                        step.output[:_OUTPUT_PREVIEW_LEN],
                        step.error,
                        step.latency_ms,
                        step.tokens_generated,
                        step.retries,
                        step.model_used,
                    ),
                )

            conn.commit()
        except sqlite3.Error as exc:
            logger.error("Failed to persist pipeline result: %s", exc)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass


# ──── Singleton ────

_executor_lock = threading.Lock()
_executor_instance: Optional[PipelineExecutor] = None


def get_pipeline_executor(
    db_path: Optional[Path] = None,
) -> PipelineExecutor:
    """Return the singleton :class:`PipelineExecutor`.

    Args:
        db_path: Override the default database path.  Only honoured on the
            first call.

    Returns:
        The shared executor instance.
    """
    global _executor_instance
    if _executor_instance is None:
        with _executor_lock:
            if _executor_instance is None:
                _executor_instance = PipelineExecutor(db_path=db_path)
    return _executor_instance


# ──── Pipeline Templates ────

PIPELINE_TEMPLATES: Dict[str, Callable[..., TaskPipeline]] = {}


def register_template(name: str) -> Callable[[Callable[..., TaskPipeline]], Callable[..., TaskPipeline]]:
    """Decorator that registers a pipeline template factory.

    Args:
        name: Template name used for lookup via :func:`get_template`.

    Returns:
        The original factory function, unchanged.
    """

    def _decorator(fn: Callable[..., TaskPipeline]) -> Callable[..., TaskPipeline]:
        PIPELINE_TEMPLATES[name] = fn
        return fn

    return _decorator


@register_template("review_and_fix")
def review_and_fix_pipeline(
    code: str,
    language: str = "python",
) -> TaskPipeline:
    """Review code, then generate a refactored version addressing issues.

    Args:
        code: Source code to review.
        language: Programming language identifier.

    Returns:
        A two-step :class:`TaskPipeline`.
    """
    return TaskPipeline(
        name="review_and_fix",
        steps=[
            PipelineStep(
                name="code_review",
                spec=TaskSpec(
                    task_type="code_review",
                    prompt=(
                        f"Review the following {language} code for bugs, "
                        f"style issues, and potential improvements:\n"
                        f"```{language}\n{code}\n```"
                    ),
                ),
                store_as="review",
            ),
            PipelineStep(
                name="refactor",
                spec=TaskSpec(
                    task_type="refactor",
                    prompt="",
                ),
                input_transform=lambda prev, ctx: (
                    f"Refactor this code based on the review feedback.\n\n"
                    f"Review:\n{prev}\n\n"
                    f"Original code:\n```\n{ctx.get('_initial_input', '')}\n```\n\n"
                    f"Return only the improved code."
                ),
                on_failure=FailureMode.RETRY,
            ),
        ],
        description=(
            f"Code review followed by refactoring to fix issues found "
            f"({language})"
        ),
        metadata={"language": language},
    )


@register_template("summarize_and_classify")
def summarize_and_classify_pipeline(text: str) -> TaskPipeline:
    """Summarize text, then classify the summary.

    Args:
        text: Text to summarize and classify.

    Returns:
        A two-step :class:`TaskPipeline`.
    """
    return TaskPipeline(
        name="summarize_and_classify",
        steps=[
            PipelineStep(
                name="summarize",
                spec=TaskSpec(
                    task_type="summarize",
                    prompt=(
                        "Provide a concise summary of the following text:\n\n"
                        f"{text}"
                    ),
                    max_tokens=512,
                ),
                store_as="summary",
            ),
            PipelineStep(
                name="classify",
                spec=TaskSpec(
                    task_type="classify",
                    prompt="",
                ),
                input_transform=lambda prev, ctx: (
                    "Classify the following summary into one or more "
                    "categories (e.g. technical, business, creative, "
                    "educational, news, opinion). Return the categories "
                    "and a short justification.\n\n"
                    f"Summary:\n{prev}"
                ),
                store_as="classification",
            ),
        ],
        description="Summarize content, then classify the summary",
    )


@register_template("security_audit")
def security_audit_pipeline(code: str) -> TaskPipeline:
    """Security check, then generate tests for vulnerabilities found.

    Args:
        code: Source code to audit.

    Returns:
        A two-step :class:`TaskPipeline`.
    """
    return TaskPipeline(
        name="security_audit",
        steps=[
            PipelineStep(
                name="security_check",
                spec=TaskSpec(
                    task_type="security_check",
                    prompt=(
                        "Perform a thorough security analysis of the "
                        "following code. Identify vulnerabilities, "
                        "injection risks, authentication issues, and "
                        "data-exposure risks:\n\n"
                        f"```\n{code}\n```"
                    ),
                ),
                store_as="security_report",
            ),
            PipelineStep(
                name="generate_security_tests",
                spec=TaskSpec(
                    task_type="test_generate",
                    prompt="",
                ),
                input_transform=lambda prev, ctx: (
                    "Based on the security analysis below, generate "
                    "pytest test cases that verify each vulnerability "
                    "is addressed. Include tests for edge cases and "
                    "attack vectors mentioned.\n\n"
                    f"Security Analysis:\n{prev}\n\n"
                    f"Original Code:\n```\n{ctx.get('_initial_input', '')}\n```"
                ),
                on_failure=FailureMode.RETRY,
                store_as="security_tests",
            ),
        ],
        description="Security analysis followed by test generation for vulnerabilities",
    )


@register_template("doc_and_test")
def doc_and_test_pipeline(code: str) -> TaskPipeline:
    """Generate documentation, then generate tests.

    Args:
        code: Source code to document and test.

    Returns:
        A two-step :class:`TaskPipeline`.
    """
    return TaskPipeline(
        name="doc_and_test",
        steps=[
            PipelineStep(
                name="generate_docs",
                spec=TaskSpec(
                    task_type="doc_generate",
                    prompt=(
                        "Generate comprehensive documentation for the "
                        "following code. Include module overview, class/"
                        "function descriptions, parameter docs, return "
                        "values, and usage examples:\n\n"
                        f"```\n{code}\n```"
                    ),
                ),
                store_as="documentation",
            ),
            PipelineStep(
                name="generate_tests",
                spec=TaskSpec(
                    task_type="test_generate",
                    prompt="",
                ),
                input_transform=lambda prev, ctx: (
                    "Using the documentation below as a specification, "
                    "generate a comprehensive pytest test suite for the "
                    "original code. Cover happy paths, edge cases, and "
                    "error conditions.\n\n"
                    f"Documentation:\n{prev}\n\n"
                    f"Original Code:\n```\n{ctx.get('_initial_input', '')}\n```"
                ),
                on_failure=FailureMode.RETRY,
                store_as="tests",
            ),
        ],
        description="Generate documentation, then create tests based on the docs",
    )


def get_template(name: str) -> Optional[Callable[..., TaskPipeline]]:
    """Get a pipeline template factory by name.

    Args:
        name: Registered template name.

    Returns:
        The factory callable, or ``None`` if not found.
    """
    return PIPELINE_TEMPLATES.get(name)


def list_templates() -> List[Dict[str, str]]:
    """List all available pipeline templates with descriptions.

    Returns:
        List of dicts with ``name`` and ``description`` keys.
    """
    result: List[Dict[str, str]] = []
    for name, factory in sorted(PIPELINE_TEMPLATES.items()):
        desc = ""
        if factory.__doc__:
            desc = factory.__doc__.strip().split("\n")[0]
        result.append({"name": name, "description": desc})
    return result
