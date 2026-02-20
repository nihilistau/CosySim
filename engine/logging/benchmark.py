"""
Benchmarking — ``@timed`` decorator, in-memory timing store, and KPI tracking.

Usage::

    from engine.logging.benchmark import timed, get_benchmarks, record_llm_kpi

    @timed("llm_generate")
    def generate(prompt):
        ...

    record_llm_kpi("llm_generate", tokens_in=50, tokens_out=120, model="qwen-7b")

    stats = get_benchmarks()
    # {"llm_generate": {"count": 42, "total_ms": 12300, "min_ms": 80, ...}}
"""
from __future__ import annotations

import functools
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_store: Dict[str, List[float]] = defaultdict(list)  # op → [durations_ms]
_MAX_SAMPLES = 5000  # per operation

# Extended KPI store for LLM/media calls
_kpi_store: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
_MAX_KPI_SAMPLES = 2000


@dataclass
class LLMKpi:
    """Per-call KPI for LLM inference."""
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_per_sec: float = 0.0
    first_token_ms: float = 0.0
    model: str = ""
    timestamp: float = field(default_factory=time.time)


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


def record_llm_kpi(
    operation: str,
    latency_ms: float = 0.0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    first_token_ms: float = 0.0,
    model: str = "",
) -> None:
    """Record detailed LLM KPI data for a call."""
    tps = tokens_out / (latency_ms / 1000.0) if latency_ms > 0 and tokens_out > 0 else 0.0
    kpi = {
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_per_sec": round(tps, 2),
        "first_token_ms": first_token_ms,
        "model": model,
        "timestamp": time.time(),
    }
    with _lock:
        samples = _kpi_store[operation]
        samples.append(kpi)
        if len(samples) > _MAX_KPI_SAMPLES:
            _kpi_store[operation] = samples[-(_MAX_KPI_SAMPLES // 2):]


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


def get_llm_kpis(operation: Optional[str] = None) -> Dict[str, Any]:
    """Return detailed LLM KPIs.

    If *operation* is given, returns KPIs for that operation only.
    Otherwise returns aggregated KPIs across all operations.
    """
    with _lock:
        if operation:
            samples = list(_kpi_store.get(operation, []))
        else:
            samples = []
            for s in _kpi_store.values():
                samples.extend(s)

    if not samples:
        return {"count": 0}

    total_in = sum(s["tokens_in"] for s in samples)
    total_out = sum(s["tokens_out"] for s in samples)
    latencies = [s["latency_ms"] for s in samples]
    tps_values = [s["tokens_per_sec"] for s in samples if s["tokens_per_sec"] > 0]
    ftft_values = [s["first_token_ms"] for s in samples if s["first_token_ms"] > 0]

    sorted_lat = sorted(latencies) if latencies else [0]
    sorted_tps = sorted(tps_values) if tps_values else [0]

    n = len(samples)
    return {
        "count": n,
        "total_tokens_in": total_in,
        "total_tokens_out": total_out,
        "avg_tokens_in": round(total_in / n, 1),
        "avg_tokens_out": round(total_out / n, 1),
        "avg_latency_ms": round(sum(latencies) / n, 1) if latencies else 0,
        "p95_latency_ms": round(sorted_lat[max(0, int(n * 0.95) - 1)], 1),
        "avg_tokens_per_sec": round(sum(tps_values) / len(tps_values), 1) if tps_values else 0,
        "p95_tokens_per_sec": round(sorted_tps[max(0, int(len(sorted_tps) * 0.95) - 1)], 1) if tps_values else 0,
        "avg_first_token_ms": round(sum(ftft_values) / len(ftft_values), 1) if ftft_values else 0,
        "models": list(set(s["model"] for s in samples if s["model"])),
    }


def get_kpi_timeseries(operation: Optional[str] = None, last_n: int = 100) -> List[Dict[str, Any]]:
    """Return raw KPI samples as a timeseries for charting."""
    with _lock:
        if operation:
            samples = list(_kpi_store.get(operation, []))
        else:
            samples = []
            for s in _kpi_store.values():
                samples.extend(s)
    samples.sort(key=lambda s: s["timestamp"])
    return samples[-last_n:]


def get_operation_timings(operation: str) -> List[float]:
    """Return raw timing samples (ms) for one operation."""
    with _lock:
        return list(_store.get(operation, []))


def get_all_operations() -> List[str]:
    """Return all tracked operation names."""
    with _lock:
        return sorted(set(list(_store.keys()) + list(_kpi_store.keys())))


def reset_benchmarks(operation: Optional[str] = None) -> None:
    """Clear benchmarks for one operation, or all if *operation* is None."""
    with _lock:
        if operation:
            _store.pop(operation, None)
            _kpi_store.pop(operation, None)
        else:
            _store.clear()
            _kpi_store.clear()
