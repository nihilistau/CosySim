"""
Experiment Skills — MCP skill functions for A/B testing and evaluation.

Allows agents and users to create experiments, record results,
and evaluate which approach works best — all tracked via Nexus.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


@skill(
    pack="system",
    tags=["experiment", "testing", "nexus"],
    category=SkillCategory.SYSTEM,
    description="Create a new A/B experiment with named variants.",
    cooldown=10,
)
def experiment_create(
    name: str,
    variant_a: str = "control",
    variant_b: str = "test",
    hypothesis: str = "",
    description: str = "",
) -> str:
    """Create a new experiment to compare two approaches."""
    from engine.nexus.experiment_framework import get_experiment_runner
    runner = get_experiment_runner()
    variants = [
        {"id": "a", "label": variant_a, "config": {"variant": variant_a}},
        {"id": "b", "label": variant_b, "config": {"variant": variant_b}},
    ]
    exp = runner.create(name, variants, description=description, hypothesis=hypothesis)
    return (
        f"🧪 Experiment created: {exp['name']}\n"
        f"ID: {exp['id']}\n"
        f"Variants: {variant_a} (A) vs {variant_b} (B)\n"
        f"Hypothesis: {hypothesis or 'None specified'}"
    )


@skill(
    pack="system",
    tags=["experiment", "testing"],
    category=SkillCategory.SYSTEM,
    description="Record a result for an experiment variant. Provide metric scores.",
    cooldown=3,
)
def experiment_record(
    experiment_id: str,
    variant_id: str = "a",
    quality: float = 0.5,
    engagement: float = 0.5,
) -> str:
    """Record metrics for a variant. Quality and engagement on 0-1 scale."""
    from engine.nexus.experiment_framework import get_experiment_runner
    runner = get_experiment_runner()
    result = runner.record_result(
        experiment_id, variant_id,
        {"quality": quality, "engagement": engagement},
    )
    if "error" in result:
        return f"⚠️ {result['error']}"
    means = result.get("mean_scores", {})
    return (
        f"📊 Recorded for {variant_id}: quality={quality:.2f}, engagement={engagement:.2f}\n"
        f"Samples: {result.get('sample_count', 0)} | "
        f"Means: quality={means.get('quality', 0):.3f}, engagement={means.get('engagement', 0):.3f}"
    )


@skill(
    pack="system",
    tags=["experiment", "testing", "evaluation"],
    category=SkillCategory.SYSTEM,
    description="Evaluate an experiment and determine the winning variant.",
    cooldown=5,
)
def experiment_evaluate(
    experiment_id: str,
    primary_metric: str = "quality",
) -> str:
    """Evaluate experiment results. Needs ≥3 samples per variant."""
    from engine.nexus.experiment_framework import get_experiment_runner
    runner = get_experiment_runner()
    result = runner.evaluate(experiment_id, primary_metric=primary_metric)
    if "error" in result:
        return f"⚠️ {result['error']}"
    if result.get("status") == "insufficient_data":
        return f"⏳ {result['message']}"
    winner = result["winner"]
    return (
        f"🏆 WINNER: {winner['label']} (variant {winner['variant_id']})\n"
        f"Score: {winner['primary_score']:.3f} ({primary_metric})\n"
        f"Improvement: +{result.get('improvement_pct', 0):.1f}% vs worst\n"
        f"{result.get('conclusion', '')}"
    )


@skill(
    pack="system",
    tags=["experiment", "testing"],
    category=SkillCategory.SYSTEM,
    description="List all experiments and their status.",
)
def experiment_list(status: str = "") -> str:
    """List experiments. Optional filter: created, running, completed."""
    from engine.nexus.experiment_framework import get_experiment_runner
    runner = get_experiment_runner()
    exps = runner.list_experiments(status=status or None)
    if not exps:
        return "No experiments found."
    lines = [f"🧪 Experiments ({len(exps)}):"]
    for e in exps:
        variants = len(e.get("variants", []))
        winner = e.get("winner_id", "—")
        lines.append(f"  [{e['status']}] {e['name']} ({e['id']}) — {variants} variants, winner: {winner}")
    return "\n".join(lines)
