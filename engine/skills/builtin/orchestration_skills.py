"""
Orchestration MCP skills — agent task management, multi-step pipelines, and
model evaluation gates for CosySim agents.

10 skills (pack="orchestration") exposing three subsystems:
  - Task management via LMSTaskBridge + TaskSpec validation
  - Multi-step pipeline execution via PipelineExecutor
  - Model evaluation gates via EvaluationGate
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────


def _safe_json(obj: Any, indent: int = 2) -> str:
    """JSON-serialize with fallback to str() for non-serializable objects."""
    try:
        return json.dumps(obj, indent=indent, default=str)
    except (TypeError, ValueError):
        return str(obj)


def _ts(epoch: Optional[float]) -> str:
    """Format an epoch timestamp as a readable string, or 'n/a'."""
    if not epoch:
        return "n/a"
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def _duration_ms(ms: Optional[float]) -> str:
    """Format milliseconds as a human-readable duration string."""
    if ms is None:
        return "n/a"
    if ms < 1000:
        return f"{ms:.0f}ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    return f"{ms / 60_000:.1f}m"


# ── 1. Submit Task ────────────────────────────────────────────


@skill(
    pack="orchestration",
    description="Submit a validated task to the LMStudio task bridge with "
                "pre-flight spec validation, priority routing, and timeout control",
    category=SkillCategory.SYSTEM,
    tags=["orchestration", "task"],
)
def submit_task(
    task_type: str,
    prompt: str,
    model: str = "",
    priority: str = "normal",
    timeout_s: int = 120,
) -> str:
    """Submit a validated task to LMSTaskBridge.

    Validates the task specification before submission. Returns a task_id on
    success or a structured error report on validation failure.

    Args:
        task_type: Task type (e.g. "evaluate", "summarize", "generate").
        prompt: The user-facing prompt text.
        model: Target LMStudio model identifier (empty for auto-select).
        priority: Priority level ("critical", "high", "normal", "low",
            "background").
        timeout_s: Maximum execution time in seconds.

    Returns:
        A formatted string with the task_id or validation errors.
    """
    try:
        from engine.nexus.task_spec import TaskSpec, validate_spec
        from engine.nexus.lms_task_bridge import LMSTaskBridge

        spec = TaskSpec(
            task_type=task_type,
            prompt=prompt,
            model=model,
            priority=priority,
            timeout_s=float(timeout_s),
        )

        validation = validate_spec(spec)
        if not validation.ok:
            lines = ["=== Task Validation Failed ==="]
            for err in validation.errors:
                lines.append(f"  ERROR: {err}")
            for warn in validation.warnings:
                lines.append(f"  WARN: {warn}")
            return "\n".join(lines)

        kwargs = spec.to_submit_kwargs()
        bridge = LMSTaskBridge()
        task_id = bridge.submit(**kwargs)

        lines = [
            "=== Task Submitted ===",
            f"Task ID: {task_id}",
            f"Type: {task_type}",
            f"Priority: {priority}",
            f"Model: {model or 'auto'}",
            f"Timeout: {timeout_s}s",
        ]
        if validation.warnings:
            lines.append("")
            lines.append("Warnings:")
            for warn in validation.warnings:
                lines.append(f"  - {warn}")

        return "\n".join(lines)

    except Exception as exc:
        logger.error("submit_task failed: %s", exc)
        return f"Task submission failed: {exc}"


# ── 2. Get Task Result ────────────────────────────────────────


@skill(
    pack="orchestration",
    description="Retrieve a task result by ID with output validation status "
                "and quality scoring",
    category=SkillCategory.SYSTEM,
    tags=["orchestration", "task"],
)
def get_task_result(task_id: str) -> str:
    """Get task result with validation status and quality score.

    Retrieves the result from LMSTaskBridge. If the task has completed,
    validates the output against its type schema and computes a quality score.

    Args:
        task_id: The task identifier returned by submit_task.

    Returns:
        A formatted string with the result, validation status, and quality.
    """
    try:
        from engine.nexus.lms_task_bridge import LMSTaskBridge
        from engine.nexus.task_spec import validate_result

        bridge = LMSTaskBridge()
        result = bridge.get_result(task_id, timeout=0.1)

        if result is None:
            return f"No result found for task_id={task_id} (still pending or unknown)"

        lines = [
            "=== Task Result ===",
            f"Task ID: {result.task_id}",
            f"Status: {result.status}",
            f"Model: {result.model}",
            f"Latency: {_duration_ms(result.latency_ms)}",
            f"Tokens: {result.tokens_generated}",
            f"TPS: {result.tps:.1f}",
        ]

        if result.error:
            lines.append(f"Error: {result.error}")

        if result.status == "completed" and result.output:
            task_type = result.metadata.get("task_type", "")
            if task_type:
                validated = validate_result(result.output, task_type)
                lines.append("")
                lines.append("--- Validation ---")
                lines.append(f"Schema match: {validated.schema_match}")
                lines.append(f"Quality score: {validated.quality_score:.2f}")
                if validated.validation_errors:
                    lines.append("Validation errors:")
                    for err in validated.validation_errors:
                        lines.append(f"  - {err}")

            output_preview = result.output[:500]
            if len(result.output) > 500:
                output_preview += f"\n... ({len(result.output)} chars total)"
            lines.append("")
            lines.append("--- Output ---")
            lines.append(output_preview)

        return "\n".join(lines)

    except Exception as exc:
        logger.error("get_task_result failed: %s", exc)
        return f"Failed to get task result: {exc}"


# ── 3. List Task Types ────────────────────────────────────────


@skill(
    pack="orchestration",
    description="List all available task types with their validation schemas "
                "and expected output patterns",
    category=SkillCategory.SYSTEM,
    tags=["orchestration", "task"],
)
def list_task_types() -> str:
    """List available task types and their schema descriptions.

    Returns all valid task types from the TaskSpec module along with their
    built-in schema definitions including length limits, required patterns,
    and quality rubric weights.

    Returns:
        A formatted listing of all task types and their schemas.
    """
    try:
        from engine.nexus.task_spec import VALID_TASK_TYPES, BUILTIN_SCHEMAS, get_schema

        lines = ["=== Available Task Types ===", ""]

        for task_type in sorted(VALID_TASK_TYPES):
            schema = get_schema(task_type)
            lines.append(f"• {task_type}")
            if schema:
                lines.append(f"    Min length: {schema.min_length} chars")
                lines.append(f"    Max length: {schema.max_length} chars")
                if schema.required_patterns:
                    lines.append(f"    Required patterns: {len(schema.required_patterns)}")
                if schema.expected_sections:
                    lines.append(
                        f"    Expected sections: {', '.join(schema.expected_sections)}"
                    )
                if schema.quality_rubric:
                    criteria = ", ".join(
                        f"{k}({v:.0%})" for k, v in schema.quality_rubric.items()
                    )
                    lines.append(f"    Quality rubric: {criteria}")
            else:
                lines.append("    Schema: baseline scoring only")
            lines.append("")

        lines.append(f"Total: {len(VALID_TASK_TYPES)} task types")
        return "\n".join(lines)

    except Exception as exc:
        logger.error("list_task_types failed: %s", exc)
        return f"Failed to list task types: {exc}"


# ── 4. Get Task Metrics ──────────────────────────────────────


@skill(
    pack="orchestration",
    description="Get task execution metrics including success rates, "
                "average latency, and per-model breakdowns",
    category=SkillCategory.SYSTEM,
    tags=["orchestration", "metrics"],
)
def get_task_metrics(hours: int = 24) -> str:
    """Get task execution metrics from the LMSTaskBridge.

    Retrieves queue statistics, worker status, success rates, and per-model
    performance breakdowns from the task bridge.

    Args:
        hours: Time window in hours for metrics (used for context label).

    Returns:
        A formatted metrics report with success rates, latency, and counts.
    """
    try:
        from engine.nexus.lms_task_bridge import LMSTaskBridge

        bridge = LMSTaskBridge()
        stats = bridge.queue_stats()

        lines = [
            f"=== Task Metrics (last {hours}h window) ===",
            "",
            "--- Queue ---",
        ]

        q_stats = stats.get("queue", {})
        lines.append(f"  Depth: {q_stats.get('size', 0)}")
        lines.append(f"  Total enqueued: {q_stats.get('total_enqueued', 0)}")
        lines.append(f"  Total dequeued: {q_stats.get('total_dequeued', 0)}")
        lines.append(
            f"  Workers: {stats.get('workers_running', 0)}"
            f"/{stats.get('workers', 0)} running"
        )
        lines.append("")

        lines.append("--- Aggregate ---")
        lines.append(f"  Total tasks: {stats.get('total_tasks', 0)}")
        lines.append(f"  Success rate: {stats.get('success_rate', 0):.1%}")
        avg_lat = stats.get("avg_latency_ms", 0)
        lines.append(f"  Avg latency: {_duration_ms(avg_lat)}")
        lines.append("")

        per_model = stats.get("per_model", {})
        if per_model:
            lines.append("--- Per-Model ---")
            for model_name, m_stats in sorted(per_model.items()):
                total = m_stats.get("total", 0)
                successes = m_stats.get("successes", 0)
                rate = successes / total if total else 0
                m_lat = m_stats.get("avg_latency_ms", 0)
                lines.append(
                    f"  {model_name}: {total} tasks, "
                    f"{rate:.0%} success, {_duration_ms(m_lat)} avg"
                )
        else:
            lines.append("No per-model metrics available yet.")

        return "\n".join(lines)

    except Exception as exc:
        logger.error("get_task_metrics failed: %s", exc)
        return f"Failed to get task metrics: {exc}"


# ── 5. Submit Pipeline ────────────────────────────────────────


@skill(
    pack="orchestration",
    description="Submit a multi-step pipeline from a registered template with "
                "chained task execution and context accumulation",
    category=SkillCategory.SYSTEM,
    tags=["orchestration", "pipeline"],
    cooldown=10.0,
)
def submit_pipeline(
    template_name: str,
    initial_input: str,
    model: str = "",
) -> str:
    """Submit a multi-step pipeline for execution.

    Looks up a registered pipeline template by name, instantiates it with the
    given input, and executes all steps sequentially via the PipelineExecutor.

    Args:
        template_name: Name of the registered pipeline template.
        initial_input: Text input fed into the first pipeline step.
        model: Optional model override for all steps (empty for auto-select).

    Returns:
        A formatted pipeline result summary with per-step status.
    """
    try:
        from engine.nexus.task_pipeline import (
            get_pipeline_executor,
            get_template,
            PIPELINE_TEMPLATES,
        )

        factory = get_template(template_name)
        if factory is None:
            available = ", ".join(sorted(PIPELINE_TEMPLATES.keys()))
            return (
                f"Unknown template: '{template_name}'\n"
                f"Available templates: {available or 'none registered'}"
            )

        pipeline = factory(initial_input)
        executor = get_pipeline_executor()
        result = executor.execute(pipeline, initial_input=initial_input)

        lines = [
            "=== Pipeline Result ===",
            f"Pipeline: {result.pipeline_name} ({result.pipeline_id})",
            f"Status: {result.status}",
            f"Total latency: {_duration_ms(result.total_latency_ms)}",
            f"Total tokens: {result.total_tokens}",
            f"Success rate: {result.success_rate:.0%}",
        ]

        if result.error:
            lines.append(f"Error: {result.error}")

        lines.append("")
        lines.append("--- Steps ---")
        for step in result.steps:
            status_icon = "✓" if step.ok else "✗"
            lines.append(
                f"  {status_icon} {step.step_name} — {step.status} "
                f"({_duration_ms(step.latency_ms)}, {step.tokens_generated} tokens)"
            )
            if step.error:
                lines.append(f"      Error: {step.error}")

        if result.final_output:
            preview = result.final_output[:300]
            if len(result.final_output) > 300:
                preview += f"\n... ({len(result.final_output)} chars total)"
            lines.append("")
            lines.append("--- Final Output ---")
            lines.append(preview)

        return "\n".join(lines)

    except Exception as exc:
        logger.error("submit_pipeline failed: %s", exc)
        return f"Pipeline execution failed: {exc}"


# ── 6. Get Pipeline Templates ────────────────────────────────


@skill(
    pack="orchestration",
    description="List all registered pipeline templates with their names and "
                "descriptions",
    category=SkillCategory.SYSTEM,
    tags=["orchestration", "pipeline"],
)
def get_pipeline_templates() -> str:
    """List available pipeline templates.

    Returns the names and docstring descriptions of all registered pipeline
    template factories.

    Returns:
        A formatted listing of all pipeline templates.
    """
    try:
        from engine.nexus.task_pipeline import list_templates

        templates = list_templates()

        if not templates:
            return "No pipeline templates registered."

        lines = ["=== Pipeline Templates ===", ""]
        for tmpl in templates:
            lines.append(f"• {tmpl['name']}")
            if tmpl.get("description"):
                lines.append(f"    {tmpl['description']}")
            lines.append("")

        lines.append(f"Total: {len(templates)} templates")
        return "\n".join(lines)

    except Exception as exc:
        logger.error("get_pipeline_templates failed: %s", exc)
        return f"Failed to list pipeline templates: {exc}"


# ── 7. Get Pipeline History ──────────────────────────────────


@skill(
    pack="orchestration",
    description="Retrieve recent pipeline execution history with status, "
                "latency, and token usage summaries",
    category=SkillCategory.SYSTEM,
    tags=["orchestration", "pipeline"],
)
def get_pipeline_history(limit: int = 10) -> str:
    """Get recent pipeline execution history.

    Retrieves the most recent pipeline runs from the executor's SQLite
    database, showing status, latency, and token counts.

    Args:
        limit: Maximum number of pipeline runs to return.

    Returns:
        A formatted history of recent pipeline executions.
    """
    try:
        from engine.nexus.task_pipeline import get_pipeline_executor

        executor = get_pipeline_executor()
        history = executor.get_history(limit=limit)

        if not history:
            return "No pipeline runs recorded yet."

        lines = ["=== Pipeline History ===", ""]
        for run in history:
            status = run.get("status", "unknown")
            status_icon = "✓" if status == "completed" else "✗"
            name = run.get("name", "unknown")
            latency = _duration_ms(run.get("total_latency_ms"))
            tokens = run.get("total_tokens", 0)
            completed = run.get("completed_at")
            ts_str = _ts(completed) if completed else "n/a"

            lines.append(
                f"  {status_icon} {name} — {status} | "
                f"{latency} | {tokens} tokens | {ts_str}"
            )
            if run.get("error"):
                lines.append(f"      Error: {run['error']}")

        lines.append("")
        lines.append(f"Showing {len(history)} of last {limit} runs")
        return "\n".join(lines)

    except Exception as exc:
        logger.error("get_pipeline_history failed: %s", exc)
        return f"Failed to get pipeline history: {exc}"


# ── 8. Run Evaluation Gate ────────────────────────────────────


@skill(
    pack="orchestration",
    description="Run a model evaluation gate to benchmark a candidate model "
                "against baseline and determine promotion eligibility",
    category=SkillCategory.SYSTEM,
    tags=["orchestration", "evaluation"],
    cooldown=30.0,
)
def run_evaluation_gate(
    model_id: str,
    benchmark_name: str = "general",
) -> str:
    """Trigger a model evaluation gate.

    Runs benchmarks on the specified model and compares results against the
    stored baseline using the NO_REGRESSION policy. Determines whether the
    model passes or fails the quality gate.

    Args:
        model_id: Identifier of the candidate model to evaluate.
        benchmark_name: Benchmark category to use ("general", "router",
            "tag_extraction", "response_validate").

    Returns:
        A formatted gate result with pass/fail, scores, and recommendation.
    """
    try:
        from training.evaluation_gate import (
            get_evaluation_gate,
            BenchmarkSpec,
            GatePolicy,
            DEFAULT_BENCHMARK_PROMPTS,
        )

        gate = get_evaluation_gate()

        prompts = list(DEFAULT_BENCHMARK_PROMPTS.get(
            benchmark_name,
            DEFAULT_BENCHMARK_PROMPTS.get("general", []),
        ))

        spec = BenchmarkSpec(
            model_type=benchmark_name,
            test_prompts=prompts,
        )

        result = gate.run_gate(
            model_id=model_id,
            model_type=benchmark_name,
            policy=GatePolicy.NO_REGRESSION,
            benchmark_spec=spec,
        )

        passed_str = "PASSED ✓" if result.passed else "FAILED ✗"
        lines = [
            "=== Evaluation Gate Result ===",
            f"Model: {result.model_id}",
            f"Type: {result.model_type}",
            f"Policy: {result.policy}",
            f"Outcome: {passed_str}",
            f"Recommendation: {result.recommendation}",
            f"Reason: {result.reason}",
            "",
            "--- Scores (before → after) ---",
        ]

        all_metrics = sorted(set(result.scores_before) | set(result.scores_after))
        for metric in all_metrics:
            before = result.scores_before.get(metric, 0.0)
            after = result.scores_after.get(metric, 0.0)
            d = result.delta.get(metric, 0.0)
            d_pct = result.delta_pct.get(metric, 0.0)
            direction = "↑" if d > 0 else "↓" if d < 0 else "="
            lines.append(
                f"  {metric}: {before:.3f} → {after:.3f} "
                f"({direction} {d_pct:+.1f}%)"
            )

        overall_delta = result.delta.get("overall_score", 0.0)
        overall_pct = result.delta_pct.get("overall_score", 0.0)
        lines.append("")
        lines.append(
            f"Overall: {overall_delta:+.4f} ({overall_pct:+.1f}%)"
        )

        return "\n".join(lines)

    except Exception as exc:
        logger.error("run_evaluation_gate failed: %s", exc)
        return f"Evaluation gate failed: {exc}"


# ── 9. Get Gate Results ──────────────────────────────────────


@skill(
    pack="orchestration",
    description="Retrieve recent evaluation gate results filtered by model "
                "type with pass/fail summaries",
    category=SkillCategory.SYSTEM,
    tags=["orchestration", "evaluation"],
)
def get_gate_results(
    model_id: str = "",
    limit: int = 10,
) -> str:
    """Get recent evaluation gate results.

    Retrieves gate history from the EvaluationGate database, optionally
    filtered by model type. Shows pass/fail outcomes, recommendations,
    and score summaries.

    Args:
        model_id: Optional model type filter (e.g. "router", "general").
            When empty, returns results for all model types.
        limit: Maximum number of results to return.

    Returns:
        A formatted listing of recent gate results.
    """
    try:
        from training.evaluation_gate import get_evaluation_gate

        gate = get_evaluation_gate()
        history = gate.get_gate_history(
            model_type=model_id if model_id else None,
            limit=limit,
        )

        if not history:
            filter_msg = f" for model_type='{model_id}'" if model_id else ""
            return f"No gate results found{filter_msg}."

        lines = ["=== Evaluation Gate History ===", ""]
        passed_count = 0
        failed_count = 0

        for entry in history:
            passed = entry.get("passed", False)
            if passed:
                passed_count += 1
            else:
                failed_count += 1

            icon = "✓" if passed else "✗"
            m_id = entry.get("model_id", "unknown")
            m_type = entry.get("model_type", "unknown")
            policy = entry.get("policy", "unknown")
            rec = entry.get("recommendation", "")
            ts = _ts(entry.get("timestamp"))

            lines.append(f"  {icon} {m_id} ({m_type}) — {policy}")
            lines.append(f"      {rec} | {ts}")

        lines.append("")
        total = passed_count + failed_count
        lines.append(
            f"Summary: {passed_count}/{total} passed, "
            f"{failed_count}/{total} failed"
        )
        return "\n".join(lines)

    except Exception as exc:
        logger.error("get_gate_results failed: %s", exc)
        return f"Failed to get gate results: {exc}"


# ── 10. Get Model Health ─────────────────────────────────────


@skill(
    pack="orchestration",
    description="Get model performance health summary with trends from "
                "evaluation gate and benchmark history",
    category=SkillCategory.SYSTEM,
    tags=["orchestration", "evaluation", "health"],
)
def get_model_health(model_id: str = "") -> str:
    """Get model performance health and trends.

    Aggregates evaluation gate results and benchmark history to produce a
    health summary showing pass rates, score trends, and latency patterns.

    Args:
        model_id: Optional model type to filter. When empty, shows health
            for all evaluated model types.

    Returns:
        A formatted health summary with trends and recommendations.
    """
    try:
        from training.evaluation_gate import get_evaluation_gate

        gate = get_evaluation_gate()
        gate_history = gate.get_gate_history(
            model_type=model_id if model_id else None,
            limit=50,
        )
        bench_history = gate.get_benchmark_history(
            model_type=model_id if model_id else None,
            limit=50,
        )

        lines = [
            "=== Model Health Summary ===",
            f"Filter: {model_id or 'all models'}",
            "",
        ]

        # Gate pass rate
        if gate_history:
            passed = sum(1 for g in gate_history if g.get("passed"))
            total = len(gate_history)
            rate = passed / total if total else 0
            lines.append("--- Gate Pass Rate ---")
            lines.append(f"  {passed}/{total} passed ({rate:.0%})")

            # Recent trend (last 5 vs previous 5)
            if total >= 10:
                recent_5 = sum(
                    1 for g in gate_history[:5] if g.get("passed")
                )
                prev_5 = sum(
                    1 for g in gate_history[5:10] if g.get("passed")
                )
                trend = recent_5 - prev_5
                trend_str = "↑ improving" if trend > 0 else (
                    "↓ declining" if trend < 0 else "= stable"
                )
                lines.append(f"  Trend: {trend_str} (recent {recent_5}/5 vs prior {prev_5}/5)")
            lines.append("")
        else:
            lines.append("No gate history available.")
            lines.append("")

        # Benchmark trends
        if bench_history:
            lines.append("--- Benchmark Trends ---")

            # Group by model type
            by_type: Dict[str, List[Dict[str, Any]]] = {}
            for b in bench_history:
                m_type = b.get("model_type", "unknown")
                by_type.setdefault(m_type, []).append(b)

            for m_type, entries in sorted(by_type.items()):
                lines.append(f"  {m_type} ({len(entries)} benchmarks):")

                # Extract overall scores where available
                scores = []
                for e in entries:
                    raw_scores = e.get("scores")
                    if isinstance(raw_scores, str):
                        try:
                            raw_scores = json.loads(raw_scores)
                        except (json.JSONDecodeError, TypeError):
                            raw_scores = {}
                    if isinstance(raw_scores, dict):
                        overall = raw_scores.get("accuracy", raw_scores.get("overall", None))
                        if overall is not None:
                            scores.append(float(overall))

                if scores:
                    latest = scores[0]
                    best = max(scores)
                    worst = min(scores)
                    lines.append(f"    Latest: {latest:.3f}")
                    lines.append(f"    Best: {best:.3f} | Worst: {worst:.3f}")
                    if len(scores) >= 2:
                        delta = scores[0] - scores[1]
                        d_icon = "↑" if delta > 0 else "↓" if delta < 0 else "="
                        lines.append(f"    Trend: {d_icon} {delta:+.4f} vs previous")
                else:
                    lines.append("    No score data available")
                lines.append("")

            # Latency summary from most recent benchmark
            latest_bench = bench_history[0]
            lat_stats = latest_bench.get("latency_stats")
            if isinstance(lat_stats, str):
                try:
                    lat_stats = json.loads(lat_stats)
                except (json.JSONDecodeError, TypeError):
                    lat_stats = {}
            if isinstance(lat_stats, dict) and lat_stats:
                lines.append("--- Latest Latency ---")
                mean_lat = lat_stats.get("mean", 0)
                p95_lat = lat_stats.get("p95", lat_stats.get("max", 0))
                lines.append(f"  Mean: {mean_lat:.1f}s | P95: {p95_lat:.1f}s")
        else:
            lines.append("No benchmark history available.")

        return "\n".join(lines)

    except Exception as exc:
        logger.error("get_model_health failed: %s", exc)
        return f"Failed to get model health: {exc}"
