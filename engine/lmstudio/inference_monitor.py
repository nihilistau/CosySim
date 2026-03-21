"""
InferenceMonitor — Live transaction monitoring for LMStudio inference.

Hooks into the InferenceOrchestrator to track every inference call.
Records queue depth, latency, TPS, error rate, and model utilization.
Stores periodic snapshots to Nexus.

Usage::

    from engine.lmstudio.inference_monitor import InferenceMonitor

    monitor = InferenceMonitor()
    monitor.start()
    # ... inference happens via orchestrator ...
    status = monitor.get_status()
    monitor.snapshot()  # store current metrics to Nexus
    monitor.stop()
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

import requests

from engine.config import get_config
from engine.utils import get_lmstudio_headers

logger = logging.getLogger(__name__)

_WINDOW_SIZE = 100  # rolling window for metrics


@dataclass
class InferenceTransaction:
    """Record of a single inference call."""

    timestamp: float
    agent_id: str
    model: str
    tier: str
    task_type: str
    latency_ms: float
    tokens: int
    tps: float
    success: bool
    error: str = ""


@dataclass
class ModelMetrics:
    """Rolling metrics for a specific model."""

    model: str
    latencies: Deque[float] = field(default_factory=lambda: deque(maxlen=_WINDOW_SIZE))
    tps_values: Deque[float] = field(default_factory=lambda: deque(maxlen=_WINDOW_SIZE))
    request_count: int = 0
    error_count: int = 0
    total_tokens: int = 0
    last_used: float = 0.0

    def record(self, tx: InferenceTransaction) -> None:
        """Record a transaction."""
        self.request_count += 1
        self.last_used = tx.timestamp
        if tx.success:
            self.latencies.append(tx.latency_ms)
            self.tps_values.append(tx.tps)
            self.total_tokens += tx.tokens
        else:
            self.error_count += 1

    @property
    def avg_latency(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0.0

    @property
    def avg_tps(self) -> float:
        return sum(self.tps_values) / len(self.tps_values) if self.tps_values else 0.0

    @property
    def error_rate(self) -> float:
        return self.error_count / self.request_count if self.request_count > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "requests": self.request_count,
            "errors": self.error_count,
            "error_rate": round(self.error_rate, 3),
            "avg_latency_ms": round(self.avg_latency, 1),
            "avg_tps": round(self.avg_tps, 1),
            "total_tokens": self.total_tokens,
            "last_used": self.last_used,
        }


class InferenceMonitor:
    """Live monitoring of all inference transactions."""

    def __init__(self, config: Optional[Any] = None) -> None:
        self._config = config or get_config()
        self._nexus_url = self._config.get("nexus.url", "http://localhost:8700/api")

        # Per-model metrics
        self._model_metrics: Dict[str, ModelMetrics] = defaultdict(
            lambda: ModelMetrics(model="unknown")
        )

        # Per-tier metrics
        self._tier_metrics: Dict[str, ModelMetrics] = defaultdict(
            lambda: ModelMetrics(model="tier")
        )

        # Recent transactions (circular buffer)
        self._recent: Deque[InferenceTransaction] = deque(maxlen=500)

        # Queue tracking
        self._queue_depth: Deque[int] = deque(maxlen=_WINDOW_SIZE)
        self._current_queue: int = 0

        # Global counters
        self._total_requests: int = 0
        self._total_errors: int = 0
        self._start_time: float = time.monotonic()

        # Snapshot timer
        self._snapshot_thread: Optional[threading.Thread] = None
        self._running = False
        self._snapshot_interval = self._config.get(
            "lmstudio.monitor.snapshot_interval", 300
        )

        self._lock = threading.Lock()

    # ── Recording ───────────────────────────────────────────────────

    def record(
        self,
        agent_id: str,
        model: str,
        tier: str,
        task_type: str,
        latency_ms: float,
        tokens: int,
        tps: float,
        success: bool = True,
        error: str = "",
    ) -> None:
        """Record an inference transaction."""
        tx = InferenceTransaction(
            timestamp=time.time(),
            agent_id=agent_id,
            model=model,
            tier=tier,
            task_type=task_type,
            latency_ms=latency_ms,
            tokens=tokens,
            tps=tps,
            success=success,
            error=error,
        )

        with self._lock:
            self._recent.append(tx)
            self._total_requests += 1
            if not success:
                self._total_errors += 1

            # Update model metrics
            if model not in self._model_metrics:
                self._model_metrics[model] = ModelMetrics(model=model)
            self._model_metrics[model].record(tx)

            # Update tier metrics
            if tier not in self._tier_metrics:
                self._tier_metrics[tier] = ModelMetrics(model=tier)
            self._tier_metrics[tier].record(tx)

    def update_queue_depth(self, depth: int) -> None:
        """Record current queue depth."""
        with self._lock:
            self._current_queue = depth
            self._queue_depth.append(depth)

    # ── Status ──────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Get current monitoring status."""
        uptime = time.monotonic() - self._start_time

        with self._lock:
            return {
                "uptime_seconds": round(uptime, 0),
                "total_requests": self._total_requests,
                "total_errors": self._total_errors,
                "error_rate": round(
                    self._total_errors / max(self._total_requests, 1), 3
                ),
                "current_queue_depth": self._current_queue,
                "avg_queue_depth": round(
                    sum(self._queue_depth) / max(len(self._queue_depth), 1), 1
                ),
                "requests_per_minute": round(
                    self._total_requests / max(uptime / 60, 0.1), 1
                ),
                "models": {
                    name: m.to_dict()
                    for name, m in self._model_metrics.items()
                },
                "tiers": {
                    name: m.to_dict()
                    for name, m in self._tier_metrics.items()
                },
            }

    def get_bottlenecks(self) -> List[Dict[str, str]]:
        """Identify current performance bottlenecks."""
        bottlenecks: List[Dict[str, str]] = []

        with self._lock:
            # High queue depth
            if self._current_queue > 5:
                bottlenecks.append({
                    "type": "queue_buildup",
                    "severity": "high" if self._current_queue > 10 else "medium",
                    "detail": f"Queue depth: {self._current_queue}",
                    "suggestion": "Increase concurrency or add CPU overflow model",
                })

            # High error rate per model
            for name, metrics in self._model_metrics.items():
                if metrics.error_rate > 0.1 and metrics.request_count > 5:
                    bottlenecks.append({
                        "type": "high_error_rate",
                        "severity": "high",
                        "detail": f"{name}: {metrics.error_rate:.0%} error rate",
                        "suggestion": "Check model health, reduce load, or switch model",
                    })

                if metrics.avg_latency > 10000 and metrics.request_count > 3:
                    bottlenecks.append({
                        "type": "slow_model",
                        "severity": "medium",
                        "detail": f"{name}: avg {metrics.avg_latency:.0f}ms",
                        "suggestion": "Use smaller model or reduce context length",
                    })

        return bottlenecks

    # ── Snapshot to Nexus ───────────────────────────────────────────

    def snapshot(self) -> Optional[str]:
        """Store current metrics snapshot to Nexus."""
        status = self.get_status()
        bottlenecks = self.get_bottlenecks()

        lines = [
            "## Inference Monitor Snapshot",
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Uptime: {status['uptime_seconds']:.0f}s",
            "",
            "### Summary",
            f"- Requests: {status['total_requests']}",
            f"- Errors: {status['total_errors']} ({status['error_rate']:.1%})",
            f"- Queue: {status['current_queue_depth']} (avg {status['avg_queue_depth']})",
            f"- RPM: {status['requests_per_minute']}",
            "",
        ]

        if status["models"]:
            lines.extend([
                "### Model Performance",
                "| Model | Requests | Avg Latency | Avg TPS | Error Rate |",
                "|-------|----------|-------------|---------|------------|",
            ])
            for name, m in status["models"].items():
                lines.append(
                    f"| {name} | {m['requests']} | {m['avg_latency_ms']}ms | "
                    f"{m['avg_tps']} | {m['error_rate']:.1%} |"
                )
            lines.append("")

        if bottlenecks:
            lines.extend([
                "### Bottlenecks Detected",
                "| Type | Severity | Detail | Suggestion |",
                "|------|----------|--------|------------|",
            ])
            for b in bottlenecks:
                lines.append(
                    f"| {b['type']} | {b['severity']} | "
                    f"{b['detail']} | {b['suggestion']} |"
                )

        content = "\n".join(lines)

        try:
            resp = requests.post(
                f"{self._nexus_url}/entries",
                json={
                    "title": f"Monitor Snapshot — {time.strftime('%Y-%m-%d %H:%M')}",
                    "content": content,
                    "content_type": "audit",
                    "category": "performance",
                    "tags": ["monitor", "snapshot", "auto-generated"],
                },
                headers=get_lmstudio_headers(),
                timeout=10,
            )
            if resp.ok:
                entry_id = resp.json().get("id", "?")
                logger.debug("Monitor snapshot stored: %s", entry_id)
                return entry_id
        except Exception as e:
            logger.warning("Cannot store snapshot: %s", e)
        return None

    # ── Background snapshot thread ──────────────────────────────────

    def start(self) -> None:
        """Start periodic snapshot thread."""
        if self._running:
            return
        self._running = True
        self._snapshot_thread = threading.Thread(
            target=self._snapshot_loop,
            daemon=True,
            name="inference-monitor",
        )
        self._snapshot_thread.start()
        logger.info("InferenceMonitor started (interval=%ds)", self._snapshot_interval)

    def stop(self) -> None:
        """Stop periodic snapshots."""
        self._running = False
        if self._snapshot_thread:
            self._snapshot_thread.join(timeout=5)
            self._snapshot_thread = None
        logger.info("InferenceMonitor stopped")

    def _snapshot_loop(self) -> None:
        """Background loop for periodic snapshots."""
        while self._running:
            time.sleep(self._snapshot_interval)
            if self._running and self._total_requests > 0:
                self.snapshot()


# ── Singleton ───────────────────────────────────────────────────────────

_monitor: Optional[InferenceMonitor] = None
_monitor_lock = threading.Lock()


def get_inference_monitor() -> InferenceMonitor:
    """Get or create the singleton InferenceMonitor."""
    global _monitor
    if _monitor is None:
        with _monitor_lock:
            if _monitor is None:
                _monitor = InferenceMonitor()
    return _monitor
