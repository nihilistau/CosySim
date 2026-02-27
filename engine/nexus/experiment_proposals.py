"""
Experiment Proposals — Auto-propose experiments from system metrics.

Connects MetaMetrics trend data and reflection insights to the
ExperimentRunner framework.  When metrics show degradation or
opportunities, this module proposes structured A/B experiments
with variants, success criteria, and auto-evaluation.

Pipeline:
    1. Scan MetaMetrics for actionable trends
    2. Match trends to experiment templates
    3. Create experiment via ExperimentRunner
    4. Store proposal in Nexus for audit trail
    5. (Optional) Register a scheduler task to run the experiment

Thread-safe singleton — call ``get_experiment_proposer()``.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Data Models ─────────────────────────────────────────────────────────


@dataclass
class ExperimentProposal:
    """A proposed experiment based on metric analysis."""

    proposal_id: str
    trigger_metric: str
    trigger_value: float
    hypothesis: str
    experiment_name: str
    variants: List[Dict[str, Any]]
    success_metric: str
    success_threshold: float
    priority: str  # "high", "medium", "low"
    auto_run: bool = False
    created_at: str = ""
    experiment_id: Optional[str] = None  # Set when experiment is created


# ── Templates ───────────────────────────────────────────────────────────

EXPERIMENT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "cache_hit_rate_low": {
        "trigger_metric": "llm.cache.hit_rate",
        "condition": "below",
        "threshold": 0.4,
        "hypothesis": (
            "Increasing Q&A cache TTL and expanding query matching "
            "will improve cache hit rate"
        ),
        "experiment_name": "cache-hit-optimization",
        "variants": [
            {
                "id": "baseline",
                "label": "Current settings",
                "config": {"cache_ttl": 300, "fuzzy_match": False},
            },
            {
                "id": "longer-ttl",
                "label": "Extended TTL (10min)",
                "config": {"cache_ttl": 600, "fuzzy_match": False},
            },
            {
                "id": "fuzzy-match",
                "label": "Fuzzy query matching",
                "config": {"cache_ttl": 300, "fuzzy_match": True},
            },
        ],
        "success_metric": "llm.cache.hit_rate",
        "success_threshold": 0.5,
        "priority": "high",
    },
    "inference_slow": {
        "trigger_metric": "llm.latency.avg_ms",
        "condition": "above",
        "threshold": 5000,
        "hypothesis": (
            "Reducing max context length or switching to a smaller "
            "model for simple queries will reduce latency"
        ),
        "experiment_name": "inference-latency-reduction",
        "variants": [
            {
                "id": "baseline",
                "label": "Current model config",
                "config": {"max_context": 8192, "model_tier": "big"},
            },
            {
                "id": "smaller-context",
                "label": "Reduced context (4096)",
                "config": {"max_context": 4096, "model_tier": "big"},
            },
            {
                "id": "smaller-model",
                "label": "Use small model for simple",
                "config": {"max_context": 8192, "model_tier": "small"},
            },
        ],
        "success_metric": "llm.latency.avg_ms",
        "success_threshold": 3000,
        "priority": "medium",
    },
    "task_failure_high": {
        "trigger_metric": "tasks.agent_error_rate",
        "condition": "above",
        "threshold": 0.2,
        "hypothesis": (
            "Better task decomposition or using larger models for "
            "complex tasks will reduce failure rate"
        ),
        "experiment_name": "task-reliability-improvement",
        "variants": [
            {
                "id": "baseline",
                "label": "Current task routing",
                "config": {"decompose": False, "model_escalation": False},
            },
            {
                "id": "decompose",
                "label": "Auto-decompose complex tasks",
                "config": {"decompose": True, "model_escalation": False},
            },
            {
                "id": "escalate",
                "label": "Escalate to larger model on failure",
                "config": {"decompose": False, "model_escalation": True},
            },
        ],
        "success_metric": "tasks.agent_error_rate",
        "success_threshold": 0.1,
        "priority": "high",
    },
    "knowledge_quality_low": {
        "trigger_metric": "nexus.quality.average",
        "condition": "below",
        "threshold": 0.6,
        "hypothesis": (
            "More aggressive deduplication and structured content "
            "templates will improve knowledge quality"
        ),
        "experiment_name": "knowledge-quality-improvement",
        "variants": [
            {
                "id": "baseline",
                "label": "Current quality pipeline",
                "config": {"dedup_threshold": 0.85, "require_structure": False},
            },
            {
                "id": "strict-dedup",
                "label": "Stricter deduplication (0.7)",
                "config": {"dedup_threshold": 0.7, "require_structure": False},
            },
            {
                "id": "structured",
                "label": "Require structured content",
                "config": {"dedup_threshold": 0.85, "require_structure": True},
            },
        ],
        "success_metric": "nexus.quality.average",
        "success_threshold": 0.7,
        "priority": "medium",
    },
    "gpu_utilization_low": {
        "trigger_metric": "system.gpu.utilization",
        "condition": "below",
        "threshold": 20.0,
        "hypothesis": (
            "Batch processing and speculative loading can improve "
            "GPU utilization efficiency"
        ),
        "experiment_name": "gpu-utilization-optimization",
        "variants": [
            {
                "id": "baseline",
                "label": "Current scheduling",
                "config": {"batch_size": 1, "speculative_load": False},
            },
            {
                "id": "batch",
                "label": "Batch inference (4)",
                "config": {"batch_size": 4, "speculative_load": False},
            },
            {
                "id": "speculative",
                "label": "Speculative model loading",
                "config": {"batch_size": 1, "speculative_load": True},
            },
        ],
        "success_metric": "system.gpu.utilization",
        "success_threshold": 40.0,
        "priority": "low",
    },
}


# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional[ExperimentProposer] = None
_lock = threading.Lock()


def get_experiment_proposer() -> ExperimentProposer:
    """Get or create the singleton ExperimentProposer instance."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ExperimentProposer()
    return _instance


# ── Core Class ──────────────────────────────────────────────────────────


class ExperimentProposer:
    """Proposes experiments based on metric trends.

    Scans MetaMetrics for actionable patterns and creates structured
    experiments via the ExperimentRunner framework.
    """

    def __init__(self) -> None:
        self._proposals: List[ExperimentProposal] = []
        self._templates = dict(EXPERIMENT_TEMPLATES)

    def add_template(
        self, name: str, template: Dict[str, Any]
    ) -> None:
        """Register a custom experiment template."""
        self._templates[name] = template
        logger.info("Registered experiment template: %s", name)

    def scan_and_propose(self) -> List[ExperimentProposal]:
        """Scan metrics and propose experiments for any triggered templates.

        Returns:
            List of ExperimentProposal objects for triggered experiments.
        """
        proposals: List[ExperimentProposal] = []
        metrics = self._get_current_metrics()

        for template_name, template in self._templates.items():
            trigger_metric = template["trigger_metric"]
            current_value = metrics.get(trigger_metric)

            if current_value is None:
                continue

            triggered = False
            condition = template.get("condition", "below")
            threshold = template.get("threshold", 0)

            if condition == "below" and current_value < threshold:
                triggered = True
            elif condition == "above" and current_value > threshold:
                triggered = True

            if triggered:
                proposal = ExperimentProposal(
                    proposal_id=f"prop-{uuid.uuid4().hex[:8]}",
                    trigger_metric=trigger_metric,
                    trigger_value=current_value,
                    hypothesis=template["hypothesis"],
                    experiment_name=template["experiment_name"],
                    variants=template["variants"],
                    success_metric=template["success_metric"],
                    success_threshold=template["success_threshold"],
                    priority=template.get("priority", "medium"),
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                proposals.append(proposal)
                self._proposals.append(proposal)
                logger.info(
                    "Proposed experiment '%s' — %s=%s (threshold=%s)",
                    template_name,
                    trigger_metric,
                    current_value,
                    threshold,
                )

        return proposals

    def create_experiment(
        self, proposal: ExperimentProposal
    ) -> Optional[Dict[str, Any]]:
        """Create an actual experiment from a proposal.

        Args:
            proposal: The experiment proposal to execute.

        Returns:
            Experiment dict from ExperimentRunner, or None on failure.
        """
        try:
            from engine.nexus.experiment_framework import get_experiment_runner
            runner = get_experiment_runner()

            experiment = runner.create(
                name=proposal.experiment_name,
                variants=proposal.variants,
                description=(
                    f"Auto-proposed experiment.\n"
                    f"Trigger: {proposal.trigger_metric}={proposal.trigger_value}\n"
                    f"Hypothesis: {proposal.hypothesis}\n"
                    f"Success: {proposal.success_metric} reaches "
                    f"{proposal.success_threshold}"
                ),
            )
            proposal.experiment_id = experiment.get("id")

            # Store in Nexus
            self._store_proposal(proposal)

            logger.info(
                "Created experiment %s from proposal %s",
                proposal.experiment_id,
                proposal.proposal_id,
            )
            return experiment
        except Exception as exc:
            logger.warning("Failed to create experiment: %s", exc)
            return None

    def get_proposals(
        self, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return proposal history.

        Args:
            status: Filter by status — ``"pending"`` (no experiment_id),
                    ``"active"`` (has experiment_id), or None for all.
        """
        results = []
        for p in self._proposals:
            if status == "pending" and p.experiment_id is not None:
                continue
            if status == "active" and p.experiment_id is None:
                continue
            results.append(asdict(p))
        return results

    def list_templates(self) -> List[Dict[str, Any]]:
        """Return all registered experiment templates."""
        return [
            {
                "name": name,
                "trigger_metric": t["trigger_metric"],
                "condition": t.get("condition", "below"),
                "threshold": t.get("threshold"),
                "experiment_name": t["experiment_name"],
                "priority": t.get("priority", "medium"),
                "variant_count": len(t.get("variants", [])),
            }
            for name, t in self._templates.items()
        ]

    # ── Internals ───────────────────────────────────────────────────

    def _get_current_metrics(self) -> Dict[str, float]:
        """Get latest metric values from MetaMetrics."""
        result: Dict[str, float] = {}
        try:
            from engine.nexus.meta_metrics import get_meta_metrics
            mm = get_meta_metrics()

            metric_names = set()
            for t in self._templates.values():
                metric_names.add(t["trigger_metric"])

            for name in metric_names:
                try:
                    trend = mm.trend(name, days=1)
                    if trend.get("count", 0) > 0:
                        result[name] = trend.get("latest", 0.0)
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("MetaMetrics unavailable: %s", exc)
        return result

    def _store_proposal(self, proposal: ExperimentProposal) -> None:
        """Store experiment proposal in Nexus."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()

            content = (
                f"**Proposal:** {proposal.proposal_id}\n"
                f"**Trigger:** {proposal.trigger_metric} = "
                f"{proposal.trigger_value}\n"
                f"**Hypothesis:** {proposal.hypothesis}\n"
                f"**Experiment:** {proposal.experiment_name}\n"
                f"**Variants:** {len(proposal.variants)}\n"
                f"**Success Metric:** {proposal.success_metric} >= "
                f"{proposal.success_threshold}\n"
                f"**Priority:** {proposal.priority}\n"
            )
            if proposal.experiment_id:
                content += (
                    f"**Experiment ID:** {proposal.experiment_id}\n"
                )

            client.add_entry(
                title=f"[Experiment] {proposal.experiment_name}",
                content=content,
                content_type="note",
                category="experiments",
                tags=[
                    "experiment",
                    "auto-proposed",
                    proposal.priority,
                    proposal.trigger_metric,
                ],
            )
        except Exception as exc:
            logger.debug("Failed to store proposal: %s", exc)
