"""MetricsCollector — in-process observability for LLM calls, scene health, and system performance.

Tracks:
- LLM call latency (p50, p90, p99 per model_profile)
- Error rate (per component)
- Token usage (prompt + completion per model)
- Scene request counts
- Active connections per scene
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MetricsSample:
    """Single recorded metrics event."""

    timestamp: float
    component: str
    event_type: str  # "llm_call", "error", "scene_request", "connection"
    value: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class MetricsCollector:
    """Rolling-window in-process metrics collector.

    All methods are thread-safe.  The internal deque is bounded to
    ``_MAX_SAMPLES`` entries so memory usage stays constant.
    """

    _MAX_SAMPLES = 10_000

    def __init__(self) -> None:
        self._samples: deque[MetricsSample] = deque(maxlen=self._MAX_SAMPLES)
        self._lock = threading.Lock()

    # ── Recording helpers ─────────────────────────────────────────────

    def record(
        self,
        component: str,
        event_type: str,
        value: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a generic metrics sample.

        Args:
            component:  Source component name (e.g. ``"lmstudio"``).
            event_type: Event category (``"llm_call"``, ``"error"``, etc.).
            value:      Numeric measurement (latency ms, count, etc.).
            metadata:   Optional dict of additional context.
        """
        sample = MetricsSample(
            timestamp=time.monotonic(),
            component=component,
            event_type=event_type,
            value=value,
            metadata=metadata or {},
        )
        with self._lock:
            self._samples.append(sample)

    def record_llm_call(
        self,
        model_profile: str,
        latency_ms: float,
        tokens_prompt: int,
        tokens_completion: int,
        success: bool = True,
    ) -> None:
        """Record a completed LLM inference call.

        Args:
            model_profile:     Model identifier / profile name.
            latency_ms:        End-to-end latency in milliseconds.
            tokens_prompt:     Number of prompt (input) tokens.
            tokens_completion: Number of completion (output) tokens.
            success:           False if the call raised an exception.
        """
        self.record(
            component="lmstudio",
            event_type="llm_call",
            value=latency_ms,
            metadata={
                "model_profile": model_profile,
                "tokens_prompt": tokens_prompt,
                "tokens_completion": tokens_completion,
                "success": success,
                "total_tokens": tokens_prompt + tokens_completion,
            },
        )

    def record_error(self, component: str, error_type: str) -> None:
        """Record an error event for a component.

        Args:
            component:  Source component (e.g. ``"lmstudio"``).
            error_type: Exception class name or short description.
        """
        self.record(
            component=component,
            event_type="error",
            value=1.0,
            metadata={"error_type": error_type},
        )

    def record_scene_request(
        self,
        scene_name: str,
        endpoint: str,
        latency_ms: float,
    ) -> None:
        """Record an HTTP request handled by a scene.

        Args:
            scene_name:  Scene slug (e.g. ``"bedroom"``).
            endpoint:    Request path or route name.
            latency_ms:  Handler latency in milliseconds.
        """
        self.record(
            component=f"scene.{scene_name}",
            event_type="scene_request",
            value=latency_ms,
            metadata={"scene": scene_name, "endpoint": endpoint},
        )

    # ── Summary ───────────────────────────────────────────────────────

    def get_summary(self, window_seconds: int = 3600) -> Dict[str, Any]:
        """Return an aggregated metrics summary for the recent window.

        Args:
            window_seconds: How far back (in monotonic seconds) to include.

        Returns:
            Nested dict with llm, scenes, errors, and collector sections.
        """
        cutoff = time.monotonic() - window_seconds
        with self._lock:
            samples = list(self._samples)

        window_samples = [s for s in samples if s.timestamp >= cutoff]

        # ── LLM metrics ───────────────────────────────────────────────
        llm_calls = [
            s for s in window_samples
            if s.event_type == "llm_call" and s.component == "lmstudio"
        ]
        llm_errors = [
            s for s in window_samples
            if s.event_type == "error" and s.component == "lmstudio"
        ]

        total_llm_calls = len(llm_calls)
        total_llm_errors = len(llm_errors)

        latencies: List[float] = [s.value for s in llm_calls]
        total_tokens = sum(
            s.metadata.get("total_tokens", 0) for s in llm_calls
        )

        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        p50_latency = _percentile(latencies, 50)
        p90_latency = _percentile(latencies, 90)

        error_rate = (
            total_llm_errors / (total_llm_calls + total_llm_errors)
            if (total_llm_calls + total_llm_errors) > 0
            else 0.0
        )

        # Per-model breakdown
        by_model: Dict[str, Dict[str, Any]] = {}
        for s in llm_calls:
            profile = s.metadata.get("model_profile", "unknown")
            entry = by_model.setdefault(
                profile, {"calls": 0, "avg_latency": 0.0, "tokens": 0, "_lat_sum": 0.0}
            )
            entry["calls"] += 1
            entry["_lat_sum"] += s.value
            entry["tokens"] += s.metadata.get("total_tokens", 0)
        for entry in by_model.values():
            calls = entry["calls"]
            entry["avg_latency"] = entry["_lat_sum"] / calls if calls else 0.0
            del entry["_lat_sum"]

        # ── Scene metrics ─────────────────────────────────────────────
        scene_samples = [s for s in window_samples if s.event_type == "scene_request"]
        scenes: Dict[str, Dict[str, Any]] = {}
        for s in scene_samples:
            name = s.metadata.get("scene", s.component)
            entry = scenes.setdefault(name, {"requests": 0, "_lat_sum": 0.0})
            entry["requests"] += 1
            entry["_lat_sum"] += s.value
        for entry in scenes.values():
            reqs = entry["requests"]
            entry["avg_latency_ms"] = entry["_lat_sum"] / reqs if reqs else 0.0
            del entry["_lat_sum"]

        # ── Error metrics (all components) ────────────────────────────
        error_samples = [s for s in window_samples if s.event_type == "error"]
        errors: Dict[str, Dict[str, Any]] = {}
        total_all_calls = len([s for s in window_samples if s.event_type in ("llm_call", "scene_request")])
        for s in error_samples:
            comp = s.component
            entry = errors.setdefault(comp, {"count": 0})
            entry["count"] += 1
        for entry in errors.values():
            entry["rate"] = (
                entry["count"] / (total_all_calls + entry["count"])
                if (total_all_calls + entry["count"]) > 0
                else 0.0
            )

        # ── Collector health ──────────────────────────────────────────
        oldest_age = 0.0
        if samples:
            oldest_age = time.monotonic() - samples[0].timestamp

        return {
            "window_seconds": window_seconds,
            "llm": {
                "total_calls": total_llm_calls,
                "error_rate": error_rate,
                "avg_latency_ms": avg_latency,
                "p50_latency_ms": p50_latency,
                "p90_latency_ms": p90_latency,
                "total_tokens": total_tokens,
                "by_model": by_model,
            },
            "scenes": scenes,
            "errors": errors,
            "collector": {
                "sample_count": len(samples),
                "oldest_sample_age_s": oldest_age,
            },
        }

    def reset(self) -> None:
        """Clear all recorded samples."""
        with self._lock:
            self._samples.clear()

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text exposition format.

        Returns:
            Prometheus-compatible plain-text string.
        """
        summary = self.get_summary()
        llm = summary["llm"]
        lines: List[str] = []

        def _g(name: str, value: float, help_text: str = "", labels: str = "") -> None:
            if help_text:
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} gauge")
            label_str = f"{{{labels}}}" if labels else ""
            lines.append(f"{name}{label_str} {value}")

        _g("cosysim_llm_total_calls", llm["total_calls"], "Total LLM calls in window")
        _g("cosysim_llm_error_rate", llm["error_rate"], "LLM error rate (0-1)")
        _g("cosysim_llm_avg_latency_ms", llm["avg_latency_ms"], "LLM average latency ms")
        _g("cosysim_llm_p50_latency_ms", llm["p50_latency_ms"], "LLM p50 latency ms")
        _g("cosysim_llm_p90_latency_ms", llm["p90_latency_ms"], "LLM p90 latency ms")
        _g("cosysim_llm_total_tokens", llm["total_tokens"], "Total LLM tokens in window")

        for profile, data in llm["by_model"].items():
            safe = profile.replace("-", "_").replace(".", "_")
            _g(f'cosysim_llm_calls_by_model{{model="{profile}"}}', data["calls"])
            _g(f'cosysim_llm_tokens_by_model{{model="{profile}"}}', data["tokens"])

        for scene, data in summary["scenes"].items():
            safe = scene.replace("-", "_")
            _g(f'cosysim_scene_requests{{scene="{scene}"}}', data["requests"])
            _g(f'cosysim_scene_avg_latency_ms{{scene="{scene}"}}', data["avg_latency_ms"])

        _g("cosysim_collector_sample_count", summary["collector"]["sample_count"],
           "Total samples in rolling window")

        return "\n".join(lines) + "\n"


# ── Percentile helper ──────────────────────────────────────────────────────────

def _percentile(values: List[float], pct: int) -> float:
    """Return the p-th percentile of a list of floats.

    Args:
        values: List of numeric values.
        pct:    Percentile to compute (0-100).

    Returns:
        Percentile value, or 0.0 for an empty list.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct / 100
    lower = int(k)
    upper = min(lower + 1, len(sorted_vals) - 1)
    frac = k - lower
    return sorted_vals[lower] + frac * (sorted_vals[upper] - sorted_vals[lower])


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: Optional[MetricsCollector] = None
_instance_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Return the global MetricsCollector singleton.

    Thread-safe; creates the instance on first call.

    Returns:
        The shared MetricsCollector instance.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MetricsCollector()
    return _instance
