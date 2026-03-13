"""
MetricsCollector — Background service that hooks into all system components.

Runs as a singleton daemon thread, ticking every N seconds (default 1s).
Collects system snapshots, pipeline metrics, evaluates alerts, and
broadcasts everything via Socket.IO for the Command Center.

Usage::

    from engine.observability.metrics_collector import get_metrics_collector
    collector = get_metrics_collector()
    collector.start()
    # ... later ...
    collector.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from engine.observability.alerts import Alert, AlertEngine, AlertRule
from engine.observability.metrics_db import MetricsDB, get_metrics_db

logger = logging.getLogger(__name__)

# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional["MetricsCollector"] = None
_lock = threading.Lock()


def get_metrics_collector(**kwargs) -> "MetricsCollector":
    """Get or create the singleton MetricsCollector."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = MetricsCollector(**kwargs)
    return _instance


# ── MetricsCollector ────────────────────────────────────────────────────

class MetricsCollector:
    """
    Background metrics collection service.

    Hooks into:
    - SystemMonitor (CPU/RAM/GPU every tick)
    - ActivityBus (real-time activity events)
    - Pipeline (per-request metrics via on_metrics callback)
    - AlertEngine (threshold evaluation every tick)

    Broadcasts via optional emit_fn (Socket.IO or similar).
    """

    def __init__(
        self,
        db: Optional[MetricsDB] = None,
        tick_interval: float = 1.0,
        retention_hours: float = 24.0,
        alert_rules: Optional[List[AlertRule]] = None,
        emit_fn: Optional[Callable] = None,
    ):
        self._db = db or get_metrics_db()
        self._tick_interval = tick_interval
        self._retention_hours = retention_hours
        self._emit_fn = emit_fn

        # Alert engine
        self._alert_engine = AlertEngine(
            rules=alert_rules or self._default_rules(),
            on_alert=self._on_alert,
            metrics_db=self._db,
        )

        # Training data capture
        self._training_capture = None
        try:
            from engine.observability.training_capture import TrainingCapture
            self._training_capture = TrainingCapture(db=self._db)
            logger.info("TrainingCapture wired into MetricsCollector")
        except Exception:
            logger.debug("TrainingCapture unavailable", exc_info=True)

        # Thread control
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._prune_counter = 0

        # Snapshot cache (latest)
        self._last_system: Dict[str, Any] = {}
        self._last_pipeline_summary: Dict[str, Any] = {}
        self._last_process_snapshot: Dict[str, Any] = {}

    @property
    def running(self) -> bool:
        return self._running

    @property
    def alert_engine(self) -> AlertEngine:
        return self._alert_engine

    @property
    def training_capture(self):
        """Access the wired TrainingCapture instance (may be None)."""
        return self._training_capture

    @property
    def last_system_snapshot(self) -> Dict[str, Any]:
        return dict(self._last_system)

    @property
    def last_pipeline_summary(self) -> Dict[str, Any]:
        return dict(self._last_pipeline_summary)

    @property
    def last_process_snapshot(self) -> Dict[str, Any]:
        return dict(self._last_process_snapshot)

    def start(self) -> None:
        """Start the background collection thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._tick_loop, daemon=True, name="MetricsCollector"
        )
        self._thread.start()
        logger.info("MetricsCollector started (tick=%.1fs)", self._tick_interval)

    def stop(self) -> None:
        """Stop the background collection thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("MetricsCollector stopped")

    # ── Pipeline integration ────────────────────────────────────────

    def on_pipeline_result(self, result: Any) -> None:
        """
        Called by VirtualPipeline after each execution.

        Records per-request metrics to DB and broadcasts.
        """
        try:
            metrics = {
                "agent_id": getattr(result, "agent_id", ""),
                "scene_id": getattr(result, "scene_id", ""),
                "tier": getattr(result, "tier", ""),
                "model": getattr(result, "model", ""),
                "latency_ms": getattr(result, "pipeline_latency_ms", 0),
                "ttft_ms": getattr(result, "time_to_first_token_s", 0) * 1000,
                "tokens_in": getattr(result, "input_tokens", 0),
                "tokens_out": getattr(result, "output_tokens", 0),
                "tps": getattr(result, "server_tps", 0),
                "response_id": getattr(result, "response_id", ""),
                "draft_accepted": getattr(result, "draft_accepted", 0),
                "draft_rejected": getattr(result, "draft_rejected", 0),
            }

            # Watcher metrics
            analysis = getattr(result, "watcher_analysis", None)
            if analysis:
                metrics["watcher_latency_ms"] = getattr(analysis, "latency_ms", 0)
                signals = getattr(analysis, "signals", [])
                metrics["watcher_signal"] = signals[-1].value if signals else "none"

            # Kill switch metrics
            metrics["kill_fired"] = 1 if getattr(result, "generation_killed", False) else 0
            metrics["retry_count"] = getattr(result, "retry_count", 0)

            # Pre-warm metrics
            pre_warms = getattr(result, "pre_warmed_results", [])
            metrics["pre_warm_hit"] = sum(
                1 for pw in pre_warms if getattr(pw, "was_used", False)
            )

            self._db.record_pipeline(**metrics)

            # Feed alert engine
            if metrics.get("latency_ms"):
                self._alert_engine.feed("pipeline", "avg_latency_ms", metrics["latency_ms"])
            if metrics.get("kill_fired"):
                self._alert_engine.feed("pipeline", "kill_rate", 1.0)
            else:
                self._alert_engine.feed("pipeline", "kill_rate", 0.0)

            # Broadcast
            self._emit("metric_request", metrics)

        except Exception as exc:
            logger.debug("Failed to record pipeline metrics: %s", exc)

        # Capture training data (independent of metrics recording)
        if self._training_capture and self._training_capture.enabled:
            try:
                self._training_capture.on_pipeline_complete(
                    getattr(result, "_request", None), result
                )
            except Exception:
                logger.debug("Training capture error", exc_info=True)

    # ── Background loop ─────────────────────────────────────────────

    def _tick_loop(self) -> None:
        """Main background loop."""
        while self._running:
            try:
                self._collect_system()
                self._collect_pipeline_summary()
                self._collect_processes()
                alerts = self._alert_engine.evaluate()
                if alerts:
                    self._emit("metric_alerts", [
                        {"node": a.node, "level": a.level, "message": a.message}
                        for a in alerts
                    ])

                # Prune old data periodically (every 60 ticks)
                self._prune_counter += 1
                if self._prune_counter >= 60:
                    self._prune_counter = 0
                    self._db.prune_system_metrics(self._retention_hours)
                    self._db.prune_process_snapshots(self._retention_hours)

            except Exception as exc:
                logger.debug("MetricsCollector tick error: %s", exc)

            time.sleep(self._tick_interval)

    def _collect_system(self) -> None:
        """Collect system snapshot and persist."""
        try:
            from engine.logging.monitor import get_system_monitor
            mon = get_system_monitor()
            snap = mon.snapshot()

            cpu = snap.get("cpu_percent", 0.0)
            ram = snap.get("ram", {})
            ram_pct = ram.get("percent", 0.0) if isinstance(ram, dict) else 0.0
            gpu = snap.get("gpu", {})
            vram_pct = gpu.get("vram_percent", 0.0) if isinstance(gpu, dict) else 0.0
            gpu_temp = gpu.get("temperature", 0.0) if isinstance(gpu, dict) else 0.0

            self._db.record_system(
                cpu_pct=cpu,
                ram_pct=ram_pct,
                gpu_vram_pct=vram_pct,
                gpu_temp_c=gpu_temp,
            )

            self._last_system = {
                "cpu_pct": cpu,
                "ram_pct": ram_pct,
                "gpu_vram_pct": vram_pct,
                "gpu_temp_c": gpu_temp,
            }

            # Feed alert engine
            self._alert_engine.feed("system", "cpu_pct", cpu)
            self._alert_engine.feed("system", "ram_pct", ram_pct)
            self._alert_engine.feed("gpu_primary", "gpu_vram_pct", vram_pct)

            self._emit("metric_system", self._last_system)

        except Exception as exc:
            logger.debug("System snapshot failed: %s", exc)

    def _collect_pipeline_summary(self) -> None:
        """Collect pipeline summary stats."""
        try:
            summary = self._db.get_pipeline_summary(seconds=60)
            self._last_pipeline_summary = summary
            self._emit("metric_pipeline", summary)
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

    def _collect_processes(self) -> None:
        """Collect process monitor snapshot and persist."""
        try:
            from engine.system.process_monitor import get_process_monitor
            pm = get_process_monitor()
            snap = pm.system_snapshot()

            proc_count = snap.get("total_processes", 0)
            git_count = len(snap.get("git_operations", []))
            tracked_count = len(snap.get("tracked_operations", []))
            stalled_count = len(snap.get("stalled", []))
            cpu_seconds = snap.get("total_cpu_seconds", 0.0)
            mem_mb = snap.get("total_memory_mb", 0.0)

            import json
            self._db.record_process_snapshot(
                category="all",
                process_count=proc_count,
                total_cpu_seconds=cpu_seconds,
                total_memory_mb=mem_mb,
                git_op_count=git_count,
                tracked_op_count=tracked_count,
                stalled_count=stalled_count,
                snapshot_json=json.dumps(snap, default=str),
            )

            self._last_process_snapshot = {
                "process_count": proc_count,
                "git_op_count": git_count,
                "tracked_op_count": tracked_count,
                "stalled_count": stalled_count,
                "cpu_seconds": cpu_seconds,
                "memory_mb": mem_mb,
            }

            self._alert_engine.feed("process", "worker_count", proc_count)
            self._alert_engine.feed("process", "memory_mb", mem_mb)
            self._alert_engine.feed("process", "stalled_count", stalled_count)

            self._emit("metric_processes", self._last_process_snapshot)

        except Exception as exc:
            logger.debug("Process snapshot failed: %s", exc)

    # ── Helpers ──────────────────────────────────────────────────────

    def _on_alert(self, alert: Alert) -> None:
        """Callback when alert engine fires."""
        self._emit("metric_alert", {
            "node": alert.node,
            "level": alert.level,
            "prev_level": alert.prev_level,
            "message": alert.message,
        })

    def _emit(self, event: str, data: Any) -> None:
        """Broadcast via emit function (Socket.IO or similar)."""
        if self._emit_fn:
            try:
                self._emit_fn(event, data)
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

    @staticmethod
    def _default_rules() -> List[AlertRule]:
        """Default alert rules."""
        return [
            AlertRule(node="gpu_primary", metric="gpu_vram_pct", yellow=80, red=95),
            AlertRule(node="system", metric="cpu_pct", yellow=85, red=95),
            AlertRule(node="system", metric="ram_pct", yellow=85, red=95),
            AlertRule(node="pipeline", metric="avg_latency_ms", yellow=500, red=2000),
            AlertRule(node="pipeline", metric="kill_rate", yellow=0.1, red=0.3),
            AlertRule(node="process", metric="worker_count", yellow=50, red=100),
            AlertRule(node="process", metric="memory_mb", yellow=8000, red=11000),
            AlertRule(node="process", metric="stalled_count", yellow=1, red=3),
        ]
