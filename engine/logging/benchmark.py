"""
Benchmarking — ``@timed`` decorator and in-memory timing store.

Usage::

    from engine.logging.benchmark import timed, get_benchmarks

    @timed("llm_generate")
    def generate(prompt):
        ...

    stats = get_benchmarks()
    # {"llm_generate": {"count": 42, "total_ms": 12300, "min_ms": 80, ...}}
"""
from __future__ import annotations

import functools
import logging
import threading
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_store: Dict[str, List[float]] = defaultdict(list)  # op → [durations_ms]
_MAX_SAMPLES = 5000  # per operation


def timed(operation: Optional[str] = None) -> Callable:
    """Decorator that records execution time (ms) of a function.

    Can be used with or without an explicit operation name::

        @timed("llm_call")
        def call_llm(): ...

        @timed
        def my_func(): ...          # operation = "my_func"
    """
    def _decorator(fn: Callable) -> Callable:
        op = operation if isinstance(operation, str) else fn.__qualname__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                _record(op, elapsed_ms)

        return wrapper

    # Handle @timed (no parens) vs @timed("name")
    if callable(operation):
        fn = operation
        operation = fn.__qualname__
        return _decorator(fn)
    return _decorator


def _record(operation: str, elapsed_ms: float) -> None:
    with _lock:
        samples = _store[operation]
        samples.append(elapsed_ms)
        if len(samples) > _MAX_SAMPLES:
            # Keep last half to avoid unbounded growth
            _store[operation] = samples[-(_MAX_SAMPLES // 2):]


def get_benchmarks() -> Dict[str, Dict[str, Any]]:
    """Return summary statistics for every tracked operation.

    Returns dict of ``{operation: {count, total_ms, min_ms, max_ms, avg_ms, p95_ms}}``.
    """
    with _lock:
        result = {}
        for op, samples in _store.items():
            if not samples:
                continue
            n = len(samples)
            total = sum(samples)
            sorted_s = sorted(samples)
            p95_idx = max(0, int(n * 0.95) - 1)
            result[op] = {
                "count": n,
                "total_ms": round(total, 2),
                "min_ms": round(sorted_s[0], 2),
                "max_ms": round(sorted_s[-1], 2),
                "avg_ms": round(total / n, 2),
                "p95_ms": round(sorted_s[p95_idx], 2),
            }
        return result


def get_operation_timings(operation: str) -> List[float]:
    """Return raw timing samples (ms) for one operation."""
    with _lock:
        return list(_store.get(operation, []))


def reset_benchmarks(operation: Optional[str] = None) -> None:
    """Clear benchmarks for one operation, or all if *operation* is None."""
    with _lock:
        if operation:
            _store.pop(operation, None)
        else:
            _store.clear()
