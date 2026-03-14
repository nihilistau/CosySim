"""Model Registry — tracks all fine-tuned models, their benchmark scores, and active status.

Supports single-score promotion (``auto_promote``) and multi-criteria Pareto-based
promotion (``promote_multi_criteria``).

Usage::
    from training.model_registry import get_model_registry
    registry = get_model_registry()
    registry.register("qa_evaluator", adapter_path="training/models/qa_eval_abc123/adapter")
    registry.promote("qa_evaluator", "abc123")
    best = registry.get_active("qa_evaluator")

    # Multi-criteria promotion
    result = registry.promote_multi_criteria("qa_evaluator", context="accuracy_critical")
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path("training/model_registry.json")
_MODELS_DIR = Path("training/models")


@dataclass
class RegisteredModel:
    """A registered fine-tuned model entry."""
    model_id: str
    model_type: str
    base_model: str
    adapter_path: str
    merged_path: Optional[str] = None
    job_id: Optional[str] = None
    benchmark_score: Optional[float] = None
    benchmark_details: Dict[str, Any] = field(default_factory=dict)
    active: bool = False
    promoted_at: Optional[str] = None
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tags: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RegisteredModel":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ModelRegistry:
    """Tracks fine-tuned models with promotion and benchmark history."""

    def __init__(self) -> None:
        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self._models: Dict[str, RegisteredModel] = {}
        self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def register(
        self,
        model_type: str,
        adapter_path: str,
        base_model: str = "unknown",
        merged_path: Optional[str] = None,
        job_id: Optional[str] = None,
        notes: str = "",
    ) -> RegisteredModel:
        """Register a new fine-tuned model.

        Args:
            model_type: Micro-model type (qa_evaluator, router_v2, etc).
            adapter_path: Path to the LoRA adapter directory.
            base_model: HuggingFace model ID of the base.
            merged_path: Path to merged 16-bit model if available.
            job_id: Source fine-tuning job ID.
            notes: Free-text notes.

        Returns:
            The registered model entry.
        """
        import uuid
        model_id = str(uuid.uuid4())[:8]
        model = RegisteredModel(
            model_id=model_id,
            model_type=model_type,
            base_model=base_model,
            adapter_path=adapter_path,
            merged_path=merged_path,
            job_id=job_id,
            notes=notes,
        )
        self._models[model_id] = model
        self._persist()
        logger.info("Registered model %s: %s (%s)", model_id, model_type, base_model)
        return model

    def register_from_job(self, job: Any) -> RegisteredModel:
        """Register a model directly from a completed FinetuneJob.

        Args:
            job: A completed FinetuneJob instance.

        Returns:
            Registered model.
        """
        return self.register(
            model_type=job.model_type,
            adapter_path=job.checkpoint_path or "",
            base_model=job.base_model,
            merged_path=job.merged_path,
            job_id=job.job_id,
        )

    def update_benchmark(
        self,
        model_id: str,
        score: float,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update benchmark score for a model.

        Args:
            model_id: Model to update.
            score: Aggregate benchmark score (0.0–1.0).
            details: Additional benchmark metrics.
        """
        if model_id not in self._models:
            raise KeyError(f"Model {model_id} not found")
        self._models[model_id].benchmark_score = score
        self._models[model_id].benchmark_details = details or {}
        self._persist()
        logger.info("Updated benchmark for %s: %.3f", model_id, score)

    def promote(self, model_type: str, model_id: str) -> None:
        """Mark a model as the active model for its type.

        Demotes any previously active model of the same type.

        Args:
            model_type: The model type to update.
            model_id: ID of the model to promote.
        """
        if model_id not in self._models:
            raise KeyError(f"Model {model_id} not found")
        # Demote current active
        for m in self._models.values():
            if m.model_type == model_type and m.active:
                m.active = False
        # Promote new
        self._models[model_id].active = True
        self._models[model_id].promoted_at = datetime.now(timezone.utc).isoformat()
        self._persist()
        logger.info("Promoted model %s as active %s", model_id, model_type)
        self._notify_lmstudio(self._models[model_id])

    def auto_promote(self, model_type: str) -> Optional[RegisteredModel]:
        """Automatically promote the best-scoring model for a type.

        Args:
            model_type: The model type to auto-promote.

        Returns:
            Promoted model, or None if no scored models exist.
        """
        candidates = [
            m for m in self._models.values()
            if m.model_type == model_type
            and m.benchmark_score is not None
        ]
        if not candidates:
            return None
        best = max(candidates, key=lambda m: m.benchmark_score or 0.0)
        current_active = self.get_active(model_type)
        if current_active and current_active.benchmark_score and \
                best.benchmark_score <= current_active.benchmark_score:
            logger.info("Auto-promote: %s already has best score (%.3f)", model_type, current_active.benchmark_score)
            return current_active
        self.promote(model_type, best.model_id)
        return best

    def promote_multi_criteria(
        self,
        model_type: str,
        strategy: str = "weighted_sum",
        context: str = "balanced",
        custom_weights: Optional[Dict[str, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Promote the best model using multi-criteria Pareto-based selection.

        Uses ParetoSelector to evaluate models across multiple objectives
        (accuracy, latency, cost, throughput, etc.) instead of a single score.

        Args:
            model_type: The model type to promote.
            strategy: Ranking strategy — weighted_sum, tchebycheff, pareto_rank, knee_point.
            context: Selection context preset — balanced, latency_sensitive,
                accuracy_critical, cost_efficient, throughput_max.
            custom_weights: Override default weights per objective.
                Keys are objective names, values are weights.

        Returns:
            Dict with promotion result including model_id, score, strategy,
            frontier_size, and all_rankings, or None if no candidates.
        """
        from engine.nexus.pareto_selector import (
            get_pareto_selector,
            ModelObjectives,
            ObjectiveConfig,
        )

        candidates = [
            m for m in self._models.values()
            if m.model_type == model_type
            and m.benchmark_score is not None
        ]
        if not candidates:
            logger.info("Multi-criteria: no scored models for %s", model_type)
            return None

        objectives_list = self._to_model_objectives(candidates)
        if not objectives_list:
            return None

        selector = get_pareto_selector()

        custom_objectives: Optional[List[ObjectiveConfig]] = None
        if custom_weights:
            ctx = selector.get_context(context)
            custom_objectives = []
            for obj in ctx.objectives:
                w = custom_weights.get(obj.name, obj.weight)
                custom_objectives.append(ObjectiveConfig(
                    name=obj.name,
                    direction=obj.direction,
                    weight=w,
                    ideal=obj.ideal,
                    nadir=obj.nadir,
                    threshold=obj.threshold,
                ))

        rankings = selector.rank_models(
            objectives_list,
            strategy=strategy,
            context=context,
            custom_objectives=custom_objectives,
        )

        if not rankings:
            return None

        best_obj, best_score = rankings[0]
        best_model = next(
            (m for m in candidates if m.model_id == best_obj.model_id), None
        )
        if not best_model:
            return None

        current_active = self.get_active(model_type)
        if current_active and current_active.model_id == best_model.model_id:
            logger.info(
                "Multi-criteria: %s already active for %s (score=%.4f, strategy=%s)",
                best_model.model_id, model_type, best_score, strategy,
            )
        else:
            self.promote(model_type, best_model.model_id)
            logger.info(
                "Multi-criteria promoted %s for %s (score=%.4f, strategy=%s, context=%s)",
                best_model.model_id, model_type, best_score, strategy, context,
            )

        frontier = selector.compute_frontier(objectives_list, context=context)
        return {
            "promoted_model_id": best_model.model_id,
            "promoted_score": round(best_score, 6),
            "strategy": strategy,
            "context": context,
            "frontier_size": len(frontier.frontier),
            "total_candidates": len(candidates),
            "all_rankings": [
                {"model_id": obj.model_id, "score": round(score, 6)}
                for obj, score in rankings
            ],
        }

    def get_pareto_frontier(
        self,
        model_type: str,
        context: str = "balanced",
    ) -> Dict[str, Any]:
        """Compute the Pareto frontier for a model type.

        Args:
            model_type: The model type to analyze.
            context: Selection context preset.

        Returns:
            Dict with frontier models, dominated models, and analysis.
        """
        from engine.nexus.pareto_selector import get_pareto_selector

        candidates = [
            m for m in self._models.values()
            if m.model_type == model_type
            and m.benchmark_score is not None
        ]
        if not candidates:
            return {"frontier": [], "dominated": [], "total": 0}

        objectives_list = self._to_model_objectives(candidates)
        selector = get_pareto_selector()
        result = selector.compute_frontier(objectives_list, context=context)

        return {
            "frontier": [
                {"model_id": m.model_id, "model_type": m.model_type}
                for m in result.frontier
            ],
            "dominated": [
                {"model_id": m.model_id, "model_type": m.model_type}
                for m in result.dominated
            ],
            "total": len(candidates),
            "strategy": result.strategy,
            "context": result.context,
        }

    def _to_model_objectives(
        self, models: List[RegisteredModel]
    ) -> List["ModelObjectives"]:
        """Convert RegisteredModels to ModelObjectives for Pareto analysis.

        Extracts typed metrics from benchmark_details, falling back to
        benchmark_score for accuracy if specific fields are missing.

        Args:
            models: List of registered models.

        Returns:
            List of ModelObjectives with populated metrics.
        """
        from engine.nexus.pareto_selector import ModelObjectives

        results: List[ModelObjectives] = []
        for m in models:
            details = m.benchmark_details or {}
            results.append(ModelObjectives(
                model_id=m.model_id,
                model_type=m.model_type,
                accuracy=details.get("accuracy", m.benchmark_score or 0.0),
                latency_p50_ms=details.get("latency_p50_ms", 0.0),
                latency_p95_ms=details.get("latency_p95_ms", 0.0),
                cost_per_1k_tokens=details.get("cost_per_1k_tokens", 0.0),
                throughput_rps=details.get("throughput_rps", 0.0),
                error_rate=details.get("error_rate", 0.0),
                memory_mb=details.get("memory_mb", 0.0),
                custom={
                    k: float(v) for k, v in details.items()
                    if k not in {
                        "accuracy", "latency_p50_ms", "latency_p95_ms",
                        "cost_per_1k_tokens", "throughput_rps", "error_rate",
                        "memory_mb",
                    }
                    and isinstance(v, (int, float))
                },
            ))
        return results

    def get_active(self, model_type: str) -> Optional[RegisteredModel]:
        """Return the currently active model for a type."""
        for m in self._models.values():
            if m.model_type == model_type and m.active:
                return m
        return None

    def list_models(
        self,
        model_type: Optional[str] = None,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List all registered models.

        Args:
            model_type: Filter by type.
            active_only: Only return active models.

        Returns:
            List of model dicts.
        """
        models = list(self._models.values())
        if model_type:
            models = [m for m in models if m.model_type == model_type]
        if active_only:
            models = [m for m in models if m.active]
        return [m.to_dict() for m in sorted(models, key=lambda m: m.registered_at, reverse=True)]

    def get_model(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific model by ID."""
        m = self._models.get(model_id)
        return m.to_dict() if m else None

    def delete(self, model_id: str) -> None:
        """Remove a model from the registry (does not delete files)."""
        if model_id not in self._models:
            raise KeyError(f"Model {model_id} not found")
        del self._models[model_id]
        self._persist()

    def summary(self) -> Dict[str, Any]:
        """Return registry summary statistics."""
        from training.micro_datasets import MODELS as model_types
        summary: Dict[str, Any] = {}
        for model_type in model_types:
            active = self.get_active(model_type)
            all_of_type = [m for m in self._models.values() if m.model_type == model_type]
            summary[model_type] = {
                "total": len(all_of_type),
                "active_id": active.model_id if active else None,
                "active_score": active.benchmark_score if active else None,
            }
        return summary

    # ── Private ───────────────────────────────────────────────────────────────

    def _notify_lmstudio(self, model: RegisteredModel) -> None:
        """Inform the finetuned router about a newly active model."""
        try:
            from engine.lmstudio.finetuned_router import get_finetuned_router
            router = get_finetuned_router()
            router.register_model(model.model_type, model.merged_path or model.adapter_path)
        except Exception as exc:
            logger.debug("LMStudio router notification skipped: %s", exc)

    def _load(self) -> None:
        if not _REGISTRY_PATH.exists():
            return
        try:
            data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
            for entry in data.get("models", []):
                m = RegisteredModel.from_dict(entry)
                self._models[m.model_id] = m
        except Exception as exc:
            logger.warning("Registry load error: %s", exc)

    def _persist(self) -> None:
        try:
            data = {"models": [m.to_dict() for m in self._models.values()]}
            _REGISTRY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Registry persist error: %s", exc)


# ──── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    """Return the shared ModelRegistry singleton."""
    global _instance
    if _instance is None:
        _instance = ModelRegistry()
    return _instance
