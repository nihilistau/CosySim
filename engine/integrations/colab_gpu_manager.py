"""Colab GPU tier selection and compute unit (CU) budget tracker.

Manages GPU tier selection based on task type and available compute units.
CU budget persists to data/accounts/cu_budget.json.

CU rates (approximate):
    T4:  0.5 CU/hr  → 380 hours from 190 CU
    L4:  1.2 CU/hr  → 158 hours from 190 CU
    A100: 6.0 CU/hr →  31 hours from 190 CU
    H100: 7.0 CU/hr →  27 hours from 190 CU
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── GPU Tier Definitions ────

class GPUTier(str, Enum):
    T4 = "T4"
    L4 = "L4"
    A100 = "A100"
    H100 = "H100"
    FREE = "FREE"  # CPU only


GPU_SPECS: Dict[GPUTier, Dict[str, Any]] = {
    GPUTier.T4:   {"cu_per_hour": 0.5,  "vram_gb": 16.0,  "ram_gb": 12.7,  "min_cu": 0.1},
    GPUTier.L4:   {"cu_per_hour": 1.2,  "vram_gb": 22.5,  "ram_gb": 53.0,  "min_cu": 0.3},
    GPUTier.A100: {"cu_per_hour": 6.0,  "vram_gb": 40.0,  "ram_gb": 83.5,  "min_cu": 1.5},
    GPUTier.H100: {"cu_per_hour": 7.0,  "vram_gb": 80.0,  "ram_gb": 83.5,  "min_cu": 1.75},
    GPUTier.FREE: {"cu_per_hour": 0.0,  "vram_gb": 0.0,   "ram_gb": 12.7,  "min_cu": 0.0},
}

# Model size to minimum required VRAM (GB) for inference at 4-bit
MODEL_VRAM_REQUIREMENTS: Dict[str, float] = {
    "0.6b": 1.5,  "1b": 2.0,   "1.5b": 3.0,  "3b": 4.5,   "7b": 6.5,
    "8b": 7.0,    "13b": 10.0, "14b": 11.0,  "32b": 22.0, "34b": 24.0,
    "70b": 42.0,  "72b": 42.0, "405b": 250.0,
}

TASK_GPU_MAP: Dict[str, GPUTier] = {
    "inference":        GPUTier.T4,    # small model inference
    "inference_large":  GPUTier.L4,    # large model inference
    "embedding":        GPUTier.T4,    # embedding generation
    "dataset":          GPUTier.T4,    # dataset processing
    "comfyui":          GPUTier.T4,    # image generation
    "benchmark":        GPUTier.T4,    # model benchmarking
    "finetune_mini":    GPUTier.T4,    # <3B LoRA
    "finetune_small":   GPUTier.L4,    # 3B–7B LoRA
    "finetune_medium":  GPUTier.A100,  # 7B–34B LoRA
    "finetune_large":   GPUTier.H100,  # 34B+ LoRA / full fine-tune
    "vllm_server":      GPUTier.L4,    # vLLM inference server
    "gguf_server":      GPUTier.T4,    # llama.cpp server
    "whisper":          GPUTier.T4,    # speech transcription
    "tts_training":     GPUTier.T4,    # TTS model training
    "video_generation": GPUTier.L4,    # Wan/AnimateDiff video
    "image_training":   GPUTier.A100,  # full diffusion fine-tune
}

# Ordered from cheapest to most expensive (for prefer_cheap routing)
_TIER_ORDER: List[GPUTier] = [GPUTier.FREE, GPUTier.T4, GPUTier.L4, GPUTier.A100, GPUTier.H100]

_BUDGET_PATH = Path("data/accounts/cu_budget.json")
_EMERGENCY_RESERVE_CU = 2.0
_DEFAULT_BUDGET_CU = 190.0


# ──── Manager ────

class ColabGPUManager:
    """Selects GPU tiers and tracks compute unit spend across Colab sessions."""

    def __init__(self, budget_path: Path = _BUDGET_PATH) -> None:
        """Initialise manager and load persisted budget.

        Args:
            budget_path: Path to JSON file storing budget state.
        """
        self._budget_path = budget_path
        self._budget: float = _DEFAULT_BUDGET_CU
        self._used: float = 0.0
        self._usage_log: List[Dict[str, Any]] = []
        self.load()

    # ──── GPU Selection ────

    def select_gpu(
        self,
        task_type: str,
        model_size: Optional[str] = None,
        prefer_cheap: bool = False,
    ) -> GPUTier:
        """Select the appropriate GPU tier for a task.

        Args:
            task_type: Key from TASK_GPU_MAP (e.g. "finetune_small").
            model_size: Optional model size string (e.g. "7b", "13b") to
                        override the task default based on VRAM requirements.
            prefer_cheap: When True, return the minimum viable tier.

        Returns:
            The recommended GPUTier.
        """
        if model_size:
            tier = self.gpu_for_model_size(model_size)
            if prefer_cheap:
                return tier
            # Use the higher of: model-derived vs task-derived tier
            task_tier = TASK_GPU_MAP.get(task_type, GPUTier.T4)
            task_idx = _TIER_ORDER.index(task_tier) if task_tier in _TIER_ORDER else 1
            model_idx = _TIER_ORDER.index(tier) if tier in _TIER_ORDER else 1
            return _TIER_ORDER[max(task_idx, model_idx)]

        tier = TASK_GPU_MAP.get(task_type, GPUTier.T4)

        if prefer_cheap:
            # Walk down until we find the cheapest tier that meets min_cu budget
            task_idx = _TIER_ORDER.index(tier) if tier in _TIER_ORDER else 1
            for candidate in _TIER_ORDER[1:task_idx + 1]:  # skip FREE
                if GPU_SPECS[candidate]["min_cu"] <= self.get_remaining_cu():
                    return candidate
            return GPUTier.T4

        return tier

    def gpu_for_model_size(self, model_size: str) -> GPUTier:
        """Return minimum GPU tier whose VRAM satisfies the model size.

        Args:
            model_size: Model size string such as "7b", "13b", "0.6b".

        Returns:
            Minimum GPUTier with sufficient VRAM, or T4 as fallback.
        """
        normalized = self._normalize_model_size(model_size)
        required_vram = MODEL_VRAM_REQUIREMENTS.get(normalized)

        if required_vram is None:
            logger.warning(f"Unknown model size '{model_size}'; defaulting to T4")
            return GPUTier.T4

        for tier in _TIER_ORDER[1:]:  # skip FREE
            if GPU_SPECS[tier]["vram_gb"] >= required_vram:
                return tier

        logger.warning(
            f"Model size '{model_size}' requires {required_vram} GB VRAM — "
            f"exceeds all known tiers; returning H100"
        )
        return GPUTier.H100

    # ──── Budget ────

    def check_budget(self, tier: GPUTier, estimated_hours: float) -> bool:
        """Check whether the budget covers the estimated cost.

        Args:
            tier: Target GPU tier.
            estimated_hours: Estimated session duration in hours.

        Returns:
            True if affordable and above emergency reserve, False otherwise.
        """
        cost = self.estimate_cost(tier, estimated_hours)
        remaining = self.get_remaining_cu()
        if remaining <= _EMERGENCY_RESERVE_CU:
            logger.warning(
                f"CU budget at emergency reserve ({remaining:.2f} CU remaining)"
            )
            return False
        affordable = remaining >= cost
        if not affordable:
            logger.warning(
                f"Insufficient CU: need {cost:.2f}, have {remaining:.2f}"
            )
        return affordable

    def estimate_cost(self, tier: GPUTier, hours: float) -> float:
        """Estimate compute unit cost for a given tier and duration.

        Args:
            tier: GPU tier.
            hours: Duration in hours.

        Returns:
            Estimated CU cost.
        """
        return GPU_SPECS[tier]["cu_per_hour"] * hours

    def record_usage(
        self,
        tier: GPUTier,
        actual_hours: float,
        task_description: str = "",
    ) -> None:
        """Record actual GPU usage and deduct from budget.

        Args:
            tier: GPU tier used.
            actual_hours: Actual duration in hours.
            task_description: Human-readable description for the log.
        """
        cost = self.estimate_cost(tier, actual_hours)
        self._used += cost
        entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tier": tier.value,
            "hours": actual_hours,
            "cu_cost": round(cost, 4),
            "description": task_description,
        }
        self._usage_log.append(entry)
        logger.info(
            f"Recorded {cost:.3f} CU ({tier.value}, {actual_hours:.2f}h) — "
            f"{self.get_remaining_cu():.2f} CU remaining"
        )
        self.save()

    def get_remaining_cu(self) -> float:
        """Return remaining compute units (floored at 0).

        Returns:
            Remaining CU balance.
        """
        return max(0.0, self._budget - self._used)

    def get_usage_summary(self) -> Dict[str, Any]:
        """Return a summary of budget and usage.

        Returns:
            Dict with total_budget, used, remaining, recent usage_log,
            and a per-tier breakdown.
        """
        by_tier: Dict[str, float] = {}
        for entry in self._usage_log:
            t = entry["tier"]
            by_tier[t] = round(by_tier.get(t, 0.0) + entry["cu_cost"], 4)

        return {
            "total_budget": self._budget,
            "used": round(self._used, 4),
            "remaining": round(self.get_remaining_cu(), 4),
            "usage_log": self._usage_log[-20:],
            "by_tier": by_tier,
        }

    def add_cu(self, amount: float, note: str = "") -> None:
        """Add compute units to the budget (e.g. after a top-up purchase).

        Args:
            amount: CU amount to add.
            note: Optional note recorded alongside the addition.
        """
        self._budget += amount
        logger.info(f"Added {amount:.2f} CU — new budget: {self._budget:.2f} CU. {note}")
        self.save()

    # ──── Persistence ────

    def load(self) -> None:
        """Load budget state from disk; silently initialises defaults if absent."""
        if not self._budget_path.exists():
            logger.debug(f"No budget file at {self._budget_path}; using defaults")
            return
        try:
            data = json.loads(self._budget_path.read_text(encoding="utf-8"))
            self._budget = float(data.get("budget", _DEFAULT_BUDGET_CU))
            self._used = float(data.get("used", 0.0))
            self._usage_log = data.get("usage_log", [])
            logger.debug(
                f"Loaded CU budget: {self._budget:.2f} total, "
                f"{self._used:.2f} used"
            )
        except Exception as exc:
            logger.error(f"Failed to load CU budget from {self._budget_path}: {exc}")

    def save(self) -> None:
        """Persist budget state to disk."""
        try:
            self._budget_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "budget": self._budget,
                "used": round(self._used, 6),
                "usage_log": self._usage_log,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            self._budget_path.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.error(f"Failed to save CU budget to {self._budget_path}: {exc}")

    # ──── Helpers ────

    @staticmethod
    def _normalize_model_size(model_size: str) -> str:
        """Normalise a model size string to a MODEL_VRAM_REQUIREMENTS key.

        Args:
            model_size: Raw string such as "7B", "13b", "0.6b", "1.5B".

        Returns:
            Lowercase normalised key (e.g. "7b", "0.6b").
        """
        return model_size.strip().lower()


# ──── Factory ────

_instance: Optional[ColabGPUManager] = None


def get_gpu_manager() -> ColabGPUManager:
    """Return the singleton ColabGPUManager, initialising it on first call.

    Returns:
        The shared ColabGPUManager instance.
    """
    global _instance
    if _instance is None:
        _instance = ColabGPUManager()
    return _instance
