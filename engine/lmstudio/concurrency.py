"""
ConcurrentExecutor — Fan N LMStudio requests out in parallel

LMStudio supports running multiple simultaneous inference requests against a
single loaded model (configurable under Server → Advanced → concurrent slots).
This module gives CosySim an easy way to exploit that.

Three usage patterns:

1. **Scatter/gather** — send the same prompt to multiple models and collect all
   results (useful for A/B comparisons, speculative voting, etc.)::

       from engine.lmstudio.concurrency import scatter

       results = scatter(
           messages=[{"role":"user","content":"Summarise this..."}],
           models=["model-a", "model-b", "model-c"],
       )
       for r in results:
           print(r.model, r.content[:80])

2. **Parallel tasks** — send different prompts to the same model at once
   (useful when the agent loop drives multiple characters simultaneously)::

       from engine.lmstudio.concurrency import parallel_tasks

       tasks = [
           {"messages": build_prompt(char), "model": "qwen-7b"}
           for char in characters
       ]
       results = parallel_tasks(tasks, max_workers=4)

3. **ConcurrentExecutor** — reusable executor with a fixed thread pool::

       from engine.lmstudio.concurrency import ConcurrentExecutor

       executor = ConcurrentExecutor(max_workers=4)
       futures  = [executor.submit(messages, model=m) for m in models]
       results  = executor.gather(futures)
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Result container ────────────────────────────────────────────────────

@dataclass
class ConcurrentResult:
    """Result (or error) from one concurrent LLM call."""
    task_id:       int
    content:       str       = ""
    model:         str       = ""
    input_tokens:  int       = 0
    output_tokens: int       = 0
    latency_ms:    float     = 0.0
    error:         Optional[str] = None
    metadata:      Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def tokens_per_second(self) -> float:
        if self.latency_ms > 0 and self.output_tokens > 0:
            return self.output_tokens / (self.latency_ms / 1000.0)
        return 0.0

    def __repr__(self) -> str:
        if self.ok:
            return (
                f"<ConcurrentResult #{self.task_id} model={self.model!r} "
                f"tokens_out={self.output_tokens} tps={self.tokens_per_second:.1f}>"
            )
        return f"<ConcurrentResult #{self.task_id} ERROR={self.error!r}>"


# ── Executor ────────────────────────────────────────────────────────────

class ConcurrentExecutor:
    """
    Thread-pooled LMStudio request executor.

    Parameters
    ----------
    max_workers : int
        Maximum parallel HTTP threads.  Set this to match LMStudio's
        "Max concurrent requests" value (Server → Advanced).
    client : LMStudioClient, optional
        REST client to use.  Defaults to the global singleton.
    """

    def __init__(
        self,
        max_workers: int = 4,
        client=None,
    ) -> None:
        self.max_workers = max_workers
        if client is None:
            from engine.lmstudio.lms_client import get_lms_client
            client = get_lms_client()
        self._client = client
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="lms-concurrent")

    # ── Submit / gather ─────────────────────────────────────────────────

    def submit(
        self,
        messages: List[Dict],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        integrations: Optional[List[Dict]] = None,
        task_id: int = 0,
        metadata: Optional[Dict] = None,
    ) -> Future:
        """
        Submit one chat request to the thread pool.

        Returns a ``Future`` whose result is a ``ConcurrentResult``.
        """
        return self._pool.submit(
            self._run_one,
            task_id, messages, model, temperature, max_tokens, integrations,
            metadata or {},
        )

    def gather(
        self,
        futures: List[Future],
        *,
        timeout: Optional[float] = None,
    ) -> List[ConcurrentResult]:
        """
        Wait for all futures and return results in submission order.

        Errors are captured inside ``ConcurrentResult.error`` rather than
        re-raised, so partial results are always returned.
        """
        results: Dict[int, ConcurrentResult] = {}
        for future in as_completed(futures, timeout=timeout):
            try:
                result: ConcurrentResult = future.result()
            except Exception as exc:
                result = ConcurrentResult(task_id=-1, error=str(exc))
            results[result.task_id] = result

        return [results[i] for i in sorted(results)]

    def run_all(
        self,
        tasks: List[Dict],
        *,
        timeout: Optional[float] = None,
    ) -> List[ConcurrentResult]:
        """
        Submit and gather a list of task dicts in one call.

        Each task dict maps to keyword args for ``submit()``::

            tasks = [
                {"messages": msgs_a, "model": "model-a", "task_id": 0},
                {"messages": msgs_b, "model": "model-b", "task_id": 1},
            ]
            results = executor.run_all(tasks)
        """
        futures = []
        for i, task in enumerate(tasks):
            task = dict(task)
            task.setdefault("task_id", i)
            futures.append(self.submit(**task))
        return self.gather(futures, timeout=timeout)

    def stream_results(
        self,
        futures: List[Future],
        *,
        timeout: Optional[float] = None,
    ) -> Iterator[ConcurrentResult]:
        """
        Yield ``ConcurrentResult`` objects as they complete (first-done order).

        Useful for dashboards / real-time displays.
        """
        for future in as_completed(futures, timeout=timeout):
            try:
                yield future.result()
            except Exception as exc:
                yield ConcurrentResult(task_id=-1, error=str(exc))

    # ── Convenience: scatter (same prompt → many models) ────────────────

    def scatter(
        self,
        messages: List[Dict],
        models: List[str],
        **kwargs,
    ) -> List[ConcurrentResult]:
        """
        Send the same messages to multiple models in parallel.

        Returns results in the same order as *models*.
        """
        tasks = [
            {"messages": messages, "model": m, "task_id": i, **kwargs}
            for i, m in enumerate(models)
        ]
        return self.run_all(tasks)

    # ── Internal ────────────────────────────────────────────────────────

    def _run_one(
        self,
        task_id: int,
        messages: List[Dict],
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        integrations: Optional[List[Dict]],
        metadata: Dict,
    ) -> ConcurrentResult:
        t0 = time.perf_counter()
        try:
            resp = self._client.chat(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                integrations=integrations,
            )
            return ConcurrentResult(
                task_id=task_id,
                content=resp.content,
                model=resp.model,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                latency_ms=resp.latency_ms,
                metadata=metadata,
            )
        except Exception as exc:
            latency = (time.perf_counter() - t0) * 1000
            logger.warning("Concurrent task %d failed after %.0fms: %s", task_id, latency, exc)
            return ConcurrentResult(
                task_id=task_id,
                error=str(exc),
                latency_ms=latency,
                metadata=metadata,
            )

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.shutdown()

    def __repr__(self) -> str:
        return f"<ConcurrentExecutor workers={self.max_workers}>"


# ── Module-level convenience functions ──────────────────────────────────

def scatter(
    messages: List[Dict],
    models: List[str],
    *,
    max_workers: int = 4,
    **kwargs,
) -> List[ConcurrentResult]:
    """Send the same messages to multiple models in parallel. One-shot helper."""
    with ConcurrentExecutor(max_workers=max_workers) as ex:
        return ex.scatter(messages, models, **kwargs)


def parallel_tasks(
    tasks: List[Dict],
    *,
    max_workers: int = 4,
    timeout: Optional[float] = None,
) -> List[ConcurrentResult]:
    """Run a list of independent chat tasks in parallel. One-shot helper."""
    with ConcurrentExecutor(max_workers=max_workers) as ex:
        return ex.run_all(tasks, timeout=timeout)


# ── Singleton executor ────────────────────────────────────────────────

_executor: Optional[ConcurrentExecutor] = None


def get_executor(max_workers: Optional[int] = None) -> ConcurrentExecutor:
    """Return the shared ConcurrentExecutor singleton."""
    global _executor
    if _executor is None:
        try:
            from engine.config import get_config
            cfg = get_config()
            workers = max_workers or int(cfg.get("lmstudio.concurrent_slots", 4))
        except Exception:
            workers = max_workers or 4
        _executor = ConcurrentExecutor(max_workers=workers)
    return _executor
