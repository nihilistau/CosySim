"""RouterV3Client — production client for the fine-tuned Qwen2.5-0.5B router.

Loads the active router_v3 model from ModelRegistry and provides
ML-based routing decisions that replace the rule-based tier selector.

Usage::
    from engine.lmstudio.router_v3_client import get_router_v3_client
    client = get_router_v3_client()
    tier = client.predict_tier("chat", "interactive", has_tools=False)

The client lazy-loads the model on first predict call. Falls back to
rule-based routing if the model is unavailable or inference fails.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Output label → Tier mapping ──────────────────────────────────────────────

_LABEL_TO_TIER: Dict[str, str] = {
    "gpu_primary":  "gpu_primary",
    "cpu_utility":  "cpu_utility",
    "cpu_router":   "cpu_router",
    # Common aliases the model may produce
    "t1":           "gpu_primary",
    "t2":           "cpu_utility",
    "t3":           "cpu_router",
    "gpu":          "gpu_primary",
    "cpu":          "cpu_utility",
    "router":       "cpu_router",
    "primary":      "gpu_primary",
    "utility":      "cpu_utility",
}

# Rule-based fallback table (mirrors InferenceRouter.select_tier)
_RULE_FALLBACK: Dict[str, str] = {
    "classify":    "cpu_router",
    "route":       "cpu_router",
    "validate":    "cpu_router",
    "tag_extract": "cpu_router",
    "act":         "gpu_primary",
}

# Alpaca instruction used during training
_ROUTING_INSTRUCTION = (
    "Route this CosySim inference request to the optimal model tier. "
    "Output only the tier name: gpu_primary, cpu_utility, or cpu_router."
)


class RouterV3Client:
    """ML-based routing using the fine-tuned Qwen2.5-0.5B router model.

    Thread-safe. Lazy-loads the model on first call.
    """

    def __init__(self, model_path: Optional[str] = None) -> None:
        self._model_path = model_path  # resolved later if None
        self._model: Any = None        # transformers pipeline
        self._tokenizer: Any = None
        self._lock = threading.Lock()
        self._loaded = False
        self._available = False
        self._load_error: Optional[str] = None
        self._predict_count = 0
        self._error_count = 0
        self._last_predict_ms = 0.0

    # ── Model registry ───────────────────────────────────────────────────────

    @staticmethod
    def _find_active_model() -> Optional[str]:
        """Read ModelRegistry and return the merged path of the active router_v3."""
        registry_path = Path("training") / "model_registry.json"
        if not registry_path.exists():
            return None
        try:
            with open(registry_path, encoding="utf-8") as f:
                data = json.load(f)
            for entry in data.get("models", []):
                if entry.get("model_type") == "router_v3" and entry.get("active"):
                    merged = entry.get("merged_path")
                    adapter = entry.get("adapter_path")
                    # Prefer merged (faster inference) over adapter
                    for candidate in [merged, adapter]:
                        if candidate and Path(candidate).exists():
                            return str(candidate)
        except Exception as exc:
            logger.warning("ModelRegistry read failed: %s", exc)
        return None

    # ── Load ─────────────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> bool:
        """Lazy-load the model. Thread-safe. Returns True if available."""
        if self._loaded:
            return self._available
        with self._lock:
            if self._loaded:
                return self._available
            path = self._model_path or self._find_active_model()
            if path is None:
                logger.info("RouterV3: no active model in registry — using rule fallback")
                self._load_error = "no_model"
                self._loaded = True
                self._available = False
                return False
            self._load_from(path)
        return self._available

    def _load_from(self, path: str) -> None:
        """Load model from path using transformers pipeline."""
        try:
            from transformers import pipeline as hf_pipeline
            logger.info("RouterV3: loading model from %s …", path)
            t0 = time.monotonic()
            self._pipeline = hf_pipeline(
                "text-generation",
                model=path,
                device_map="auto",
                max_new_tokens=16,
                do_sample=False,
                temperature=1.0,
                pad_token_id=0,
            )
            elapsed = (time.monotonic() - t0) * 1000
            logger.info("RouterV3: model loaded in %.0f ms", elapsed)
            self._loaded = True
            self._available = True
        except ImportError:
            logger.warning("RouterV3: transformers not available — using rule fallback")
            self._load_error = "no_transformers"
            self._loaded = True
            self._available = False
        except Exception as exc:
            logger.warning("RouterV3: load failed (%s) — using rule fallback", exc)
            self._load_error = str(exc)
            self._loaded = True
            self._available = False

    # ── Predict ──────────────────────────────────────────────────────────────

    def predict_tier(
        self,
        task_type: str,
        priority: str,
        *,
        has_tools: bool = False,
        has_system_prompt: bool = False,
        prompt_tokens: int = 0,
    ) -> str:
        """Predict routing tier for the given request features.

        Args:
            task_type: e.g. "chat", "act", "classify", "complete"
            priority: "realtime", "interactive", "background", "batch"
            has_tools: whether the request includes tool schemas
            has_system_prompt: whether a system prompt is present
            prompt_tokens: approximate prompt token count

        Returns:
            One of "gpu_primary", "cpu_utility", "cpu_router".
            Falls back to rule-based result on any error.
        """
        rule_result = self._rule_predict(task_type, priority, has_tools=has_tools)

        if not self._ensure_loaded():
            return rule_result

        input_text = (
            f"task_type={task_type} priority={priority} "
            f"has_tools={has_tools} has_system_prompt={has_system_prompt} "
            f"prompt_tokens={prompt_tokens}"
        )
        prompt = (
            f"### Instruction:\n{_ROUTING_INSTRUCTION}\n\n"
            f"### Input:\n{input_text}\n\n"
            f"### Response:\n"
        )

        try:
            t0 = time.monotonic()
            outputs = self._pipeline(prompt, max_new_tokens=8, do_sample=False)
            self._last_predict_ms = (time.monotonic() - t0) * 1000
            self._predict_count += 1

            generated: str = outputs[0]["generated_text"][len(prompt):]
            tier = self._parse_label(generated.strip())
            logger.debug(
                "RouterV3: %s → %s (%.1f ms)", input_text[:60], tier, self._last_predict_ms
            )
            return tier

        except Exception as exc:
            self._error_count += 1
            logger.warning("RouterV3: predict failed (%s) — using rule fallback", exc)
            return rule_result

    def _parse_label(self, raw: str) -> str:
        """Parse model output to a known tier name, with fallback."""
        clean = raw.lower().strip().strip(".,;:").split()[0] if raw.strip() else ""
        return _LABEL_TO_TIER.get(clean, "gpu_primary")

    @staticmethod
    def _rule_predict(task_type: str, priority: str, *, has_tools: bool = False) -> str:
        """Rule-based tier prediction (mirrors InferenceRouter.select_tier)."""
        if task_type in _RULE_FALLBACK:
            return _RULE_FALLBACK[task_type]
        if has_tools or task_type == "act":
            return "gpu_primary"
        if priority in ("background", "batch"):
            return "cpu_utility"
        return "gpu_primary"

    # ── Status / diagnostics ─────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return status dict for monitoring / admin UI."""
        return {
            "available": self._available,
            "loaded": self._loaded,
            "model_path": self._model_path or self._find_active_model(),
            "load_error": self._load_error,
            "predict_count": self._predict_count,
            "error_count": self._error_count,
            "last_predict_ms": self._last_predict_ms,
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[RouterV3Client] = None
_instance_lock = threading.Lock()


def get_router_v3_client() -> RouterV3Client:
    """Return the global RouterV3Client singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = RouterV3Client()
    return _instance
