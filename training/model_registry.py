"""Model Registry — tracks all fine-tuned models, their benchmark scores, and active status.

Usage::
    from training.model_registry import get_model_registry
    registry = get_model_registry()
    registry.register("qa_evaluator", adapter_path="training/models/qa_eval_abc123/adapter")
    registry.promote("qa_evaluator", "abc123")
    best = registry.get_active("qa_evaluator")
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
