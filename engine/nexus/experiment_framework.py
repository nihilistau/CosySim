"""
Experiment Framework — A/B testing and prompt evaluation via Nexus.

Provides a structured way for agents and users to:
- Create experiments (prompt variations, config changes, parameter tuning)
- Run experiments against scenes or agents
- Log results and metrics to Nexus
- Compare variants and promote winners

Usage:
    from engine.nexus.experiment_framework import ExperimentRunner
    runner = ExperimentRunner()
    exp = runner.create("prompt_warmth", variants=[
        {"id": "warm", "system_prompt": "Be warm and friendly..."},
        {"id": "neutral", "system_prompt": "Be helpful..."},
    ])
    runner.record_result(exp["id"], "warm", {"engagement": 0.8, "quality": 0.9})
    runner.record_result(exp["id"], "neutral", {"engagement": 0.5, "quality": 0.85})
    winner = runner.evaluate(exp["id"])
"""
from __future__ import annotations

import json
import logging
import statistics
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExperimentVariant:
    """A single variant in an A/B experiment."""
    id: str
    label: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    results: List[Dict[str, float]] = field(default_factory=list)

    @property
    def mean_scores(self) -> Dict[str, float]:
        if not self.results:
            return {}
        keys = self.results[0].keys()
        return {k: statistics.mean(r.get(k, 0) for r in self.results) for k in keys}

    @property
    def sample_count(self) -> int:
        return len(self.results)


@dataclass
class Experiment:
    """An A/B experiment with multiple variants and tracked results."""
    id: str
    name: str
    description: str = ""
    hypothesis: str = ""
    metric_keys: List[str] = field(default_factory=list)
    variants: List[ExperimentVariant] = field(default_factory=list)
    status: str = "created"  # created, running, completed, archived
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    winner_id: Optional[str] = None
    conclusion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "hypothesis": self.hypothesis,
            "metric_keys": self.metric_keys,
            "variants": [asdict(v) for v in self.variants],
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "winner_id": self.winner_id,
            "conclusion": self.conclusion,
        }


class ExperimentRunner:
    """Manages A/B experiments with Nexus integration."""

    def __init__(self, nexus_url: str = ""):
        if not nexus_url:
            from engine.port_registry import get_service_url
            nexus_url = get_service_url("nexus")
        self.nexus_url = nexus_url
        self._experiments: Dict[str, Experiment] = {}

    def create(
        self,
        name: str,
        variants: List[Dict[str, Any]],
        description: str = "",
        hypothesis: str = "",
        metric_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new experiment."""
        exp_id = f"exp_{name}_{uuid.uuid4().hex[:8]}"
        exp_variants = []
        for v in variants:
            vid = v.get("id", f"v{len(exp_variants)}")
            exp_variants.append(ExperimentVariant(
                id=vid,
                label=v.get("label", vid),
                config=v.get("config", v),
            ))

        exp = Experiment(
            id=exp_id,
            name=name,
            description=description,
            hypothesis=hypothesis,
            metric_keys=metric_keys or ["quality", "engagement"],
            variants=exp_variants,
            status="running",
        )
        self._experiments[exp_id] = exp
        self._log_to_nexus(exp, "created")
        logger.info("Experiment created: %s with %d variants", exp_id, len(exp_variants))
        return exp.to_dict()

    def record_result(
        self,
        experiment_id: str,
        variant_id: str,
        metrics: Dict[str, float],
    ) -> Dict[str, Any]:
        """Record a result for a variant."""
        exp = self._experiments.get(experiment_id)
        if not exp:
            return {"error": f"Experiment {experiment_id} not found"}
        variant = next((v for v in exp.variants if v.id == variant_id), None)
        if not variant:
            return {"error": f"Variant {variant_id} not found"}
        variant.results.append(metrics)
        return {
            "experiment_id": experiment_id,
            "variant_id": variant_id,
            "sample_count": variant.sample_count,
            "mean_scores": variant.mean_scores,
        }

    def evaluate(
        self,
        experiment_id: str,
        primary_metric: Optional[str] = None,
        min_samples: int = 3,
    ) -> Dict[str, Any]:
        """Evaluate experiment results and pick a winner."""
        exp = self._experiments.get(experiment_id)
        if not exp:
            return {"error": f"Experiment {experiment_id} not found"}

        primary = primary_metric or (exp.metric_keys[0] if exp.metric_keys else "quality")

        # Check sample counts
        for v in exp.variants:
            if v.sample_count < min_samples:
                return {
                    "status": "insufficient_data",
                    "message": f"Variant '{v.id}' has {v.sample_count}/{min_samples} samples",
                }

        # Compare means
        results = []
        for v in exp.variants:
            means = v.mean_scores
            results.append({
                "variant_id": v.id,
                "label": v.label,
                "samples": v.sample_count,
                "mean_scores": means,
                "primary_score": means.get(primary, 0),
            })

        results.sort(key=lambda r: r["primary_score"], reverse=True)
        winner = results[0]

        # Calculate improvement
        if len(results) > 1:
            baseline = results[-1]["primary_score"]
            improvement = ((winner["primary_score"] - baseline) / max(0.01, baseline)) * 100
        else:
            improvement = 0

        exp.status = "completed"
        exp.completed_at = time.time()
        exp.winner_id = winner["variant_id"]
        exp.conclusion = (
            f"Winner: {winner['label']} ({primary}={winner['primary_score']:.3f}, "
            f"+{improvement:.1f}% vs worst)"
        )

        self._log_to_nexus(exp, "completed")
        return {
            "winner": winner,
            "all_results": results,
            "improvement_pct": improvement,
            "conclusion": exp.conclusion,
        }

    def list_experiments(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all experiments, optionally filtered by status."""
        exps = self._experiments.values()
        if status:
            exps = [e for e in exps if e.status == status]
        return [e.to_dict() for e in exps]

    def get_experiment(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        """Get a single experiment by ID."""
        exp = self._experiments.get(experiment_id)
        return exp.to_dict() if exp else None

    def _log_to_nexus(self, exp: Experiment, event: str) -> None:
        """Log experiment event to Nexus (best-effort)."""
        try:
            import urllib.request
            data = json.dumps({
                "content": json.dumps(exp.to_dict()),
                "content_type": "experiment",
                "tags": ["experiment", exp.name, event],
                "metadata": {"event": event, "experiment_id": exp.id},
                "quality_score": 0.8,
            }).encode()
            req = urllib.request.Request(
                f"{self.nexus_url}/api/knowledge",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            logger.debug("Best-effort logging", exc_info=True)


# Module-level singleton
_runner: Optional[ExperimentRunner] = None


def get_experiment_runner() -> ExperimentRunner:
    """Get or create the global ExperimentRunner."""
    global _runner
    if _runner is None:
        _runner = ExperimentRunner()
    return _runner
