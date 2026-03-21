"""Fine-tuned Model LMStudio Router — routes task-specific requests to fine-tuned models.

When a task-specific micro-model is active and loaded in LMStudio, this router
redirects requests of that type to the fine-tuned model instead of the large model.
Priority: qa_evaluator first (replaces Gemini stage F), then router_v2.

Usage::
    from engine.lmstudio.finetuned_router import get_finetuned_router
    router = get_finetuned_router()
    result = router.route("qa_evaluator", "How do I start the penthouse scene?")
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TASK_INSTRUCTIONS: Dict[str, str] = {
    "qa_evaluator": (
        "Classify this Q&A pair as ESSENTIAL, USEFUL, or SKIP for the knowledge cache. "
        "Output only the label, nothing else."
    ),
    "router_v2": (
        "Route this request to the most appropriate CosySim subsystem. "
        "Output only the handler name, nothing else."
    ),
    "syntax_fixer": (
        "Fix the syntax error in the following code or text. "
        "Return only the corrected version, no explanation."
    ),
    "conversation_analyzer": (
        "Extract structured user facts from this conversation as JSON. "
        "Include only fields with clear evidence: name, age, tech_level, projects, preferences, facts."
    ),
    "knowledge_synthesizer": (
        "Synthesize a concise, factual answer from the provided context fragments. "
        "Base your answer only on the context."
    ),
}


class FinetunedRouter:
    """Routes requests to fine-tuned micro-models when available."""

    def __init__(self) -> None:
        self._active_models: Dict[str, str] = {}  # task_type → model_path/id

    # ── Public API ────────────────────────────────────────────────────────────

    def register_model(self, task_type: str, model_path: str) -> None:
        """Register a fine-tuned model for a task type.

        Args:
            task_type: Task type (qa_evaluator, router_v2, etc.).
            model_path: Path to merged model or adapter directory.
        """
        self._active_models[task_type] = model_path
        logger.info("Registered fine-tuned model for %s: %s", task_type, model_path)

    def deregister_model(self, task_type: str) -> None:
        """Remove a registered fine-tuned model."""
        self._active_models.pop(task_type, None)

    def is_available(self, task_type: str) -> bool:
        """Check if a fine-tuned model is available for this task type."""
        return task_type in self._active_models

    def route(
        self,
        task_type: str,
        input_text: str,
        context: str = "",
        max_tokens: int = 64,
        temperature: float = 0.0,
    ) -> Optional[str]:
        """Route a request to the fine-tuned model if available.

        Args:
            task_type: Which micro-model to route to.
            input_text: The input text to process.
            context: Optional additional context.
            max_tokens: Max tokens for response.
            temperature: Sampling temperature (0 = greedy).

        Returns:
            Model output string, or None if no fine-tuned model available.
        """
        if not self.is_available(task_type):
            return None

        instruction = _TASK_INSTRUCTIONS.get(task_type, "Complete the task.")
        full_input = input_text
        if context:
            full_input = f"{context}\n\n{input_text}"

        try:
            return self._call_lmstudio(
                model_path=self._active_models[task_type],
                instruction=instruction,
                input_text=full_input,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            logger.warning("Fine-tuned routing failed for %s: %s", task_type, exc)
            return None

    def route_qa_evaluation(self, question: str, answer: str) -> Optional[str]:
        """Specialized route for QA pair evaluation.

        Args:
            question: The question to evaluate.
            answer: The answer to evaluate.

        Returns:
            ESSENTIAL, USEFUL, or SKIP — or None if fine-tuned model unavailable.
        """
        input_text = f"Question: {question}\nAnswer: {answer}"
        return self.route("qa_evaluator", input_text)

    def route_request_classification(self, request: str) -> Optional[str]:
        """Classify a request to a CosySim subsystem.

        Args:
            request: User or agent request text.

        Returns:
            Handler name string, or None if fine-tuned model unavailable.
        """
        return self.route("router_v2", request)

    def get_active_models(self) -> Dict[str, str]:
        """Return currently registered fine-tuned models."""
        return dict(self._active_models)

    def load_from_registry(self) -> int:
        """Auto-load all active fine-tuned models from ModelRegistry.

        Returns:
            Number of models loaded.
        """
        try:
            from training.model_registry import get_model_registry
            from training.micro_datasets import MODELS
            registry = get_model_registry()
            loaded = 0
            for model_type in MODELS:
                active = registry.get_active(model_type)
                if active:
                    path = active.merged_path or active.adapter_path
                    if path:
                        self.register_model(model_type, path)
                        loaded += 1
            logger.info("Loaded %d fine-tuned models from registry", loaded)
            return loaded
        except Exception as exc:
            logger.warning("Registry load failed: %s", exc)
            return 0

    # ── Private ───────────────────────────────────────────────────────────────

    def _call_lmstudio(
        self,
        model_path: str,
        instruction: str,
        input_text: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Call LMStudio v1 API with a fine-tuned model."""
        from engine.config import get_config
        import urllib.request
        import json

        cfg = get_config()
        host = cfg.get("lmstudio.host", "localhost")
        port = cfg.get("lmstudio.port", 1234)

        # Format as Alpaca instruction
        prompt = (
            f"### Instruction:\n{instruction}\n\n"
            f"### Input:\n{input_text}\n\n"
            f"### Response:\n"
        )

        payload = json.dumps({
            "model": model_path,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }).encode("utf-8")

        from engine.utils import get_lmstudio_headers
        req = urllib.request.Request(
            f"http://{host}:{port}/api/v1/completions",
            data=payload,
            method="POST",
        )
        for k, v in get_lmstudio_headers().items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["text"].strip()


# ──── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[FinetunedRouter] = None


def get_finetuned_router() -> FinetunedRouter:
    """Return the shared FinetunedRouter singleton."""
    global _instance
    if _instance is None:
        _instance = FinetunedRouter()
    return _instance
