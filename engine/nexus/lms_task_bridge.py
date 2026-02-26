"""
LMS Task Bridge — Copilot → LMStudio task delegation.

Allows Copilot CLI to dispatch subtasks to local LMStudio models via the
InferenceOrchestrator. Subtasks run locally on GPU/CPU and return results
to the caller for integration.

Usage::

    from engine.nexus.lms_task_bridge import LMSTaskBridge

    bridge = LMSTaskBridge()

    # Single prompt
    result = bridge.run_prompt("Summarize this code", model="qwen3-0.6b")

    # Batch prompts
    results = bridge.run_batch([
        {"prompt": "Variation 1", "temperature": 0.3},
        {"prompt": "Variation 2", "temperature": 0.9},
    ])

    # Structured task
    result = bridge.run_task(
        task_type="evaluate",
        prompt="Rate this dialog for naturalness",
        context={"dialog": "..."},
        store_result=True,
    )
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Result from a delegated LMStudio task."""

    task_id: str = ""
    status: str = "pending"  # pending, running, completed, failed
    output: str = ""
    model: str = ""
    latency_ms: float = 0.0
    tokens_generated: int = 0
    tps: float = 0.0
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "completed" and not self.error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "output": self.output,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 1),
            "tokens_generated": self.tokens_generated,
            "tps": round(self.tps, 1),
            "error": self.error,
            "metadata": self.metadata,
        }


class LMSTaskBridge:
    """Bridge between Copilot CLI and local LMStudio inference.

    Delegates tasks to the InferenceOrchestrator for execution on
    locally loaded models. Results can optionally be stored in Nexus.
    """

    def __init__(self, config: Any = None) -> None:
        self._config = config
        self._orchestrator = None
        self._nexus = None
        self._task_counter = 0

    @property
    def orchestrator(self):
        if self._orchestrator is None:
            from engine.lmstudio.orchestrator import get_orchestrator
            self._orchestrator = get_orchestrator(self._config)
        return self._orchestrator

    @property
    def nexus(self):
        if self._nexus is None:
            from engine.nexus.client import get_nexus_client
            self._nexus = get_nexus_client()
        return self._nexus

    def _next_id(self) -> str:
        self._task_counter += 1
        return f"lms-{self._task_counter:04d}"

    # ── Single prompt ────────────────────────────────────────────

    def run_prompt(
        self,
        prompt: str,
        *,
        model: str = "",
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        task_type: str = "chat",
        priority: str = "background",
    ) -> TaskResult:
        """Run a single prompt through LMStudio and return the result."""
        task_id = self._next_id()
        result = TaskResult(task_id=task_id, status="running")

        messages = [{"role": "user", "content": prompt}]
        t0 = time.monotonic()

        try:
            resp = self.orchestrator.infer(
                agent_id=f"bridge-{task_id}",
                messages=messages,
                task_type=task_type,
                priority=priority,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )

            latency_ms = (time.monotonic() - t0) * 1000
            content = resp.content if hasattr(resp, "content") else str(resp)

            # Extract token count if available
            tokens = 0
            if hasattr(resp, "usage") and resp.usage:
                tokens = int(getattr(resp.usage, "completion_tokens", 0) or 0)

            tps = tokens / (latency_ms / 1000) if tokens > 0 and latency_ms > 0 else 0.0

            result.status = "completed"
            result.output = content
            result.model = model or "default"
            result.latency_ms = latency_ms
            result.tokens_generated = tokens
            result.tps = tps

        except Exception as exc:
            result.status = "failed"
            result.error = str(exc)
            result.latency_ms = (time.monotonic() - t0) * 1000
            logger.error("Task %s failed: %s", task_id, exc)

        return result

    # ── Batch execution ──────────────────────────────────────────

    def run_batch(
        self,
        prompts: List[Dict[str, Any]],
        *,
        model: str = "",
        system_prompt: str = "",
        store_results: bool = False,
    ) -> List[TaskResult]:
        """Run multiple prompts sequentially and return all results.

        Each item in prompts should have at minimum a "prompt" key.
        Optional keys: temperature, max_tokens, task_type.
        """
        results: List[TaskResult] = []
        for item in prompts:
            p = item.get("prompt", "")
            if not p:
                continue
            result = self.run_prompt(
                p,
                model=model or item.get("model", ""),
                system_prompt=system_prompt or item.get("system_prompt", ""),
                temperature=item.get("temperature", 0.7),
                max_tokens=item.get("max_tokens", 1024),
                task_type=item.get("task_type", "chat"),
            )
            results.append(result)

        if store_results:
            self._store_batch_results(results)

        return results

    # ── Structured task ──────────────────────────────────────────

    def run_task(
        self,
        task_type: str,
        prompt: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        model: str = "",
        store_result: bool = False,
    ) -> TaskResult:
        """Run a structured task with context injection.

        Task types:
            - evaluate: Rate/score content
            - summarize: Summarize text
            - generate: Generate content
            - classify: Classify input
            - compare: Compare two inputs
        """
        system_prompts = {
            "evaluate": "You are an expert evaluator. Provide a rating (1-10) and brief justification.",
            "summarize": "Summarize the following concisely. Focus on key facts and decisions.",
            "generate": "Generate high-quality content based on the requirements.",
            "classify": "Classify the input into the most appropriate category. Return the category name and confidence.",
            "compare": "Compare the inputs and highlight similarities, differences, and which is better.",
        }

        sys_prompt = system_prompts.get(task_type, "")
        full_prompt = prompt
        if context:
            ctx_str = "\n".join(f"{k}: {v}" for k, v in context.items())
            full_prompt = f"{prompt}\n\nContext:\n{ctx_str}"

        result = self.run_prompt(
            full_prompt,
            model=model,
            system_prompt=sys_prompt,
            task_type="chat",
            priority="background",
        )
        result.metadata["task_type"] = task_type

        if store_result and result.ok:
            self._store_single_result(result, task_type)

        return result

    # ── LMStudio health check ────────────────────────────────────

    def check_lmstudio(self) -> Dict[str, Any]:
        """Check LMStudio server status and loaded models."""
        import requests
        try:
            r = requests.get("http://localhost:1234/api/v1/models", timeout=5)
            data = r.json()
            models = [m.get("id", "unknown") for m in data.get("data", [])]
            return {
                "status": "online",
                "models_loaded": len(models),
                "model_ids": models,
            }
        except Exception as exc:
            return {"status": "offline", "error": str(exc)}

    # ── Nexus storage ────────────────────────────────────────────

    def _store_single_result(self, result: TaskResult, task_type: str) -> None:
        """Store a single task result in Nexus."""
        try:
            self.nexus.add_entry(
                title=f"LMS Task [{task_type}]: {result.task_id}",
                content=(
                    f"Model: {result.model}\n"
                    f"Latency: {result.latency_ms:.0f}ms\n"
                    f"TPS: {result.tps:.1f}\n"
                    f"Output:\n{result.output[:3000]}"
                ),
                content_type="note",
                category="lms_tasks",
                tags=["lms-bridge", task_type, result.model],
            )
        except Exception as exc:
            logger.warning("Failed to store task result: %s", exc)

    def _store_batch_results(self, results: List[TaskResult]) -> None:
        """Store batch results summary in Nexus."""
        completed = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]

        summary = (
            f"Batch: {len(results)} tasks\n"
            f"Completed: {len(completed)}\n"
            f"Failed: {len(failed)}\n"
        )
        if completed:
            avg_latency = sum(r.latency_ms for r in completed) / len(completed)
            avg_tps = sum(r.tps for r in completed) / len(completed)
            summary += f"Avg latency: {avg_latency:.0f}ms\nAvg TPS: {avg_tps:.1f}\n"

        try:
            self.nexus.add_entry(
                title=f"LMS Batch: {len(results)} tasks",
                content=summary,
                content_type="note",
                category="lms_tasks",
                tags=["lms-bridge", "batch"],
            )
        except Exception as exc:
            logger.warning("Failed to store batch results: %s", exc)
