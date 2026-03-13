"""
UnifiedMonitor — Top-level orchestrator composing all monitoring subsystems.

Single start/stop lifecycle, unified metric fan-out, and primary public API
for the entire observability stack.

Usage::

    from engine.observability.unified_monitor import get_unified_monitor
    monitor = get_unified_monitor()
    monitor.start()

    snapshot = monitor.snapshot()        # all layers in one dict
    report   = monitor.health_report()   # composite 0-100 score
    data     = monitor.dashboard_data()  # formatted for UI

    monitor.stop()
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Guarded Subsystem Imports ───────────────────────────────────────────

_SUBSYSTEM_IMPORTS: List[Tuple[str, str, str]] = [
    ("engine.observability.metrics_collector", "get_metrics_collector", "MetricsCollector"),
    ("engine.observability.metrics_db", "get_metrics_db", "MetricsDB"),
    ("engine.observability.pack_tracker", "get_pack_tracker", "PackTracker"),
    ("engine.observability.anomaly_detector", "get_anomaly_detector", "AnomalyDetector"),
    ("engine.observability.correlation_engine", "get_correlation_engine", "CorrelationEngine"),
    ("engine.observability.trend_predictor", "get_trend_predictor", "TrendPredictor"),
    ("engine.observability.alert_router", "get_alert_router", "AlertRouter"),
    ("engine.system.process_monitor", "get_process_monitor", "ProcessMonitor"),
    ("engine.logging.monitor", "get_system_monitor", "SystemMonitor"),
    ("engine.services.activity_bus", "get_activity_bus", "ActivityBus"),
]

_getters: Dict[str, Callable] = {}
for _mod, _getter_name, _label in _SUBSYSTEM_IMPORTS:
    try:
        _module = __import__(_mod, fromlist=[_getter_name])
        _getters[_label] = getattr(_module, _getter_name)
    except (ImportError, AttributeError):
        logger.debug("%s unavailable", _label)

# ── Health Scoring Weights ──────────────────────────────────────────────

_CATEGORY_WEIGHTS: Dict[str, float] = {
    "resources": 0.30, "stability": 0.20, "alerts": 0.25,
    "trends": 0.15, "performance": 0.10,
}

# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional["UnifiedMonitor"] = None
_lock = threading.Lock()


def get_unified_monitor(**kwargs: Any) -> "UnifiedMonitor":
    """Get or create the singleton UnifiedMonitor.

    Args:
        **kwargs: Forwarded to ``UnifiedMonitor.__init__`` on first call.

    Returns:
        The singleton UnifiedMonitor instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = UnifiedMonitor(**kwargs)
    return _instance


# ── UnifiedMonitor ──────────────────────────────────────────────────────


class UnifiedMonitor:
    """Top-level orchestrator that composes all monitoring subsystems.

    Owns the lifecycle of every subsystem, wires the metric fan-out so
    that each sample reaches AlertEngine + AnomalyDetector +
    CorrelationEngine + TrendPredictor, and exposes a single query API
    for the entire observability stack.
    """

    # Internal name → attribute name mapping (matches _SUBSYSTEM_IMPORTS)
    _ATTR_NAMES: Dict[str, str] = {
        "MetricsCollector": "_metrics_collector",
        "MetricsDB": "_metrics_db",
        "PackTracker": "_pack_tracker",
        "AnomalyDetector": "_anomaly_detector",
        "CorrelationEngine": "_correlation_engine",
        "TrendPredictor": "_trend_predictor",
        "AlertRouter": "_alert_router",
        "ProcessMonitor": "_process_monitor",
        "SystemMonitor": "_system_monitor",
        "ActivityBus": "_activity_bus",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = config or {}
        self._lock = threading.Lock()
        self._running = False
        self._original_alert_feed: Optional[Callable] = None

        # Acquire each subsystem singleton; store None on failure
        for label, attr in self._ATTR_NAMES.items():
            getter = _getters.get(label)
            instance = None
            if getter is not None:
                try:
                    instance = getter()
                except Exception:
                    logger.warning("Failed to acquire %s", label, exc_info=True)
            setattr(self, attr, instance)

        logger.info("UnifiedMonitor initialised — %s", ", ".join(self._available_subsystems()))

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self) -> None:
        """Start all subsystems in dependency order.

        Order: PackTracker → MetricsCollector → TrendPredictor background →
        fan-out wiring → anomaly/alert routing callbacks.
        """
        with self._lock:
            if self._running:
                return

            self._safe_call(self._pack_tracker, "start", log="PackTracker started")
            self._safe_call(self._metrics_collector, "start", log="MetricsCollector started")

            interval = self._config.get("trend_interval", 60.0)
            if self._trend_predictor is not None:
                try:
                    self._trend_predictor.start_background(interval=interval)
                    logger.info("TrendPredictor background started (%.0fs)", interval)
                except Exception:
                    logger.warning("TrendPredictor background start failed", exc_info=True)

            self._wire_fanout()
            self._wire_anomaly_routing()
            self._running = True
            logger.info("UnifiedMonitor started")

    def stop(self) -> None:
        """Stop all subsystems in reverse order and persist state."""
        with self._lock:
            if not self._running:
                return

            self._unwire_fanout()

            if self._trend_predictor is not None:
                try:
                    self._trend_predictor.persist_trends()
                except Exception:
                    logger.debug("Trend persistence failed", exc_info=True)
                try:
                    self._trend_predictor.stop_background()
                except Exception:
                    logger.debug("TrendPredictor stop failed", exc_info=True)

            self._safe_call(self._metrics_collector, "stop", log="MetricsCollector stopped")
            self._safe_call(self._pack_tracker, "stop", log="PackTracker stopped")
            self._running = False
            logger.info("UnifiedMonitor stopped")

    def restart(self) -> None:
        """Stop then start the entire monitoring stack."""
        self.stop()
        self.start()

    def is_running(self) -> bool:
        """Whether the unified monitor is currently active."""
        return self._running

    # ── Fan-Out Wiring ──────────────────────────────────────────────

    def _feed_all(self, node: str, metric: str, value: float) -> None:
        """Fan out a single metric sample to all analytical subsystems.

        Called on every ``AlertEngine.feed`` invocation so that the same
        data reaches AnomalyDetector, CorrelationEngine, and
        TrendPredictor without each needing independent collection.

        Args:
            node: Metric source node (e.g. ``"system"``).
            metric: Metric name (e.g. ``"cpu_pct"``).
            value: Current metric value.
        """
        for subsys in (self._anomaly_detector, self._correlation_engine, self._trend_predictor):
            if subsys is not None:
                try:
                    subsys.feed(node, metric, value)
                except Exception:
                    logger.debug("%s feed error", type(subsys).__name__, exc_info=True)

        # Evaluate anomalies inline and route through AlertRouter
        if self._anomaly_detector is not None and self._alert_router is not None:
            try:
                for event in self._anomaly_detector.evaluate():
                    try:
                        self._alert_router.route_anomaly(event)
                    except Exception:
                        logger.debug("AlertRouter anomaly routing error", exc_info=True)
            except Exception:
                logger.debug("Anomaly evaluation error", exc_info=True)

    def _wire_fanout(self) -> None:
        """Wrap AlertEngine.feed to fan out to analytical subsystems.

        Intercepts every ``alert_engine.feed(node, metric, value)`` call
        inside MetricsCollector so the same samples reach all detectors
        without modifying MetricsCollector source.
        """
        if self._metrics_collector is None:
            return
        try:
            engine = self._metrics_collector.alert_engine
        except AttributeError:
            return

        original = engine.feed
        self._original_alert_feed = original

        def augmented_feed(node: str, metric: str, value: float) -> None:
            original(node, metric, value)
            self._feed_all(node, metric, value)

        engine.feed = augmented_feed  # type: ignore[method-assign]
        logger.info("Metric fan-out wired via AlertEngine.feed")

    def _unwire_fanout(self) -> None:
        """Restore original AlertEngine.feed if it was wrapped."""
        if self._original_alert_feed is None or self._metrics_collector is None:
            return
        try:
            self._metrics_collector.alert_engine.feed = self._original_alert_feed  # type: ignore[method-assign]
        except Exception:
            logger.debug("Failed to unwire fan-out", exc_info=True)
        self._original_alert_feed = None

    def _wire_anomaly_routing(self) -> None:
        """Connect AlertEngine on_alert callback to AlertRouter."""
        if self._alert_router is None or self._metrics_collector is None:
            return
        try:
            engine = self._metrics_collector.alert_engine
            original_cb = getattr(engine, "_on_alert", None)
            router = self._alert_router

            def routed_callback(alert: Any) -> None:
                if original_cb is not None:
                    try:
                        original_cb(alert)
                    except Exception:
                        pass
                try:
                    router.route_alert(alert)
                except Exception:
                    logger.debug("AlertRouter routing error", exc_info=True)

            engine._on_alert = routed_callback
        except Exception:
            logger.debug("Failed to wire alert routing", exc_info=True)

    # ── Unified Queries ─────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """Complete system snapshot combining all monitoring layers.

        Returns:
            Dict with keys: system, processes, packs, anomalies, trends,
            alerts, correlations, activity, ts.
        """
        result: Dict[str, Any] = {"ts": time.time()}
        result["system"] = self._try_call(self._system_monitor, "snapshot", {})
        # Use cached last_system_snapshot from MetricsCollector instead of
        # process_monitor.system_snapshot() which does a full psutil scan and
        # can block for 30+ seconds on Windows.
        result["processes"] = self._latest_system_metrics()

        # Pack summary — convert dataclass results if needed
        if self._pack_tracker is not None:
            try:
                raw = self._pack_tracker.pack_summary()
                result["packs"] = self._dictify_map(raw)
            except Exception:
                result["packs"] = {}
        else:
            result["packs"] = {}

        result["anomalies"] = self._try_call(self._anomaly_detector, "snapshot", {})
        result["trends"] = self._try_call(self._trend_predictor, "summary", {})
        result["alerts"] = self._get_alert_status()
        result["correlations"] = self._try_call(self._correlation_engine, "snapshot", {})
        result["activity"] = self._try_call(self._activity_bus, "snapshot", {})
        return result

    def health_report(self) -> Dict[str, Any]:
        """Overall system health with composite 0–100 score.

        Computes per-category scores and identifies worst issues.

        Returns:
            Dict with composite_score, category_scores, worst_issues, ts.
        """
        scores: Dict[str, float] = {}
        issues: List[Dict[str, Any]] = []

        # Resources — peak utilisation drives score
        sm = self._latest_system_metrics()
        cpu, ram, vram = sm.get("cpu_pct", 0.0), sm.get("ram_pct", 0.0), sm.get("gpu_vram_pct", 0.0)
        scores["resources"] = self._clamp(100.0 - max(cpu, ram, vram))
        for label, val in [("CPU", cpu), ("RAM", ram), ("GPU VRAM", vram)]:
            if val > 90:
                issues.append({"category": "resources", "detail": f"{label} at {val:.1f}%", "severity": "high"})

        # Stability — anomaly count in last hour
        anomaly_1h = 0
        if self._anomaly_detector is not None:
            try:
                counts = self._anomaly_detector.anomaly_counts(hours=1.0)
                anomaly_1h = sum(sum(sev.values()) for sev in counts.values())
            except Exception:
                pass
        scores["stability"] = self._clamp(100.0 - anomaly_1h * 10.0)
        if anomaly_1h > 5:
            issues.append({
                "category": "stability",
                "detail": f"{anomaly_1h} anomalies in last hour",
                "severity": "high" if anomaly_1h > 10 else "medium",
            })

        # Alerts — red = −30, yellow = −10
        status_map = self._get_alert_status()
        reds = sum(1 for v in status_map.values() if v == "red")
        yellows = sum(1 for v in status_map.values() if v == "yellow")
        scores["alerts"] = self._clamp(100.0 - reds * 30.0 - yellows * 10.0)
        for node, level in status_map.items():
            if level in ("red", "yellow"):
                issues.append({
                    "category": "alerts", "detail": f"{node} is {level.upper()}",
                    "severity": "critical" if level == "red" else "medium",
                })

        # Trends — degradation count penalty
        scores["trends"] = 100.0
        if self._trend_predictor is not None:
            try:
                deg = self._trend_predictor.degradation_report()
                scores["trends"] = self._clamp(
                    100.0 - deg.get("degrading_count", 0) * 15.0
                    - deg.get("volatile_count", 0) * 5.0
                )
                ws = deg.get("worst_severity")
                if ws and ws not in ("none",):
                    issues.append({"category": "trends", "detail": f"Worst severity: {ws}", "severity": ws})
            except Exception:
                pass

        # Performance — pipeline latency
        scores["performance"] = self._pipeline_perf_score(issues)

        # Composite
        composite = sum(scores.get(c, 100.0) * w for c, w in _CATEGORY_WEIGHTS.items())
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        issues.sort(key=lambda i: sev_order.get(i.get("severity", "low"), 99))

        return {
            "composite_score": round(composite, 1),
            "category_scores": {k: round(v, 1) for k, v in scores.items()},
            "worst_issues": issues[:10],
            "ts": time.time(),
        }

    # ── PackTracker Delegates ───────────────────────────────────────

    def pack_summary(self) -> Dict[str, Any]:
        """Aggregated stats per skill pack."""
        if self._pack_tracker is None:
            return {}
        try:
            return self._dictify_map(self._pack_tracker.pack_summary())
        except Exception:
            return {}

    def top_packs(self, n: int = 10) -> List[Dict[str, Any]]:
        """Top packs by CPU consumption."""
        return self._try_call_list(self._pack_tracker, "top_packs", n=n)

    def pack_processes(self, pack: str) -> List[Dict[str, Any]]:
        """PIDs associated with a given skill pack."""
        return self._try_call_list(self._pack_tracker, "pack_processes", pack=pack)

    def skill_leaderboard(self, n: int = 20) -> List[Dict[str, Any]]:
        """Top individual skills by usage."""
        return self._try_call_list(self._pack_tracker, "skill_leaderboard", top_n=n)

    def cross_reference(self) -> Dict[str, Any]:
        """Pack ↔ process category cross-reference matrix."""
        return self._try_call(self._pack_tracker, "cross_reference", {})

    # ── AnomalyDetector Delegates ───────────────────────────────────

    def recent_anomalies(self, n: int = 50) -> List[Dict[str, Any]]:
        """Recent anomaly events across all metrics."""
        return self._try_call_list(self._anomaly_detector, "recent_anomalies", n=n)

    def anomaly_counts(self) -> Dict[str, Dict[str, int]]:
        """Anomaly counts grouped by node and severity (last 24 h)."""
        return self._try_call(self._anomaly_detector, "anomaly_counts", {})

    # ── TrendPredictor Delegates ────────────────────────────────────

    def all_trends(self) -> List[Any]:
        """Current trends for all qualifying metrics."""
        return self._try_call_list(self._trend_predictor, "all_trends")

    def capacity_warnings(self, horizon_minutes: int = 60) -> List[Dict[str, Any]]:
        """Metrics predicted to breach capacity within horizon."""
        return self._try_call_list(
            self._trend_predictor, "capacity_warnings", horizon_minutes=horizon_minutes,
        )

    def degradation_report(self) -> Dict[str, Any]:
        """Metrics showing degradation trends."""
        return self._try_call(self._trend_predictor, "degradation_report", {})

    # ── CorrelationEngine Delegates ─────────────────────────────────

    def strong_correlations(self, min_r: float = 0.7) -> List[Any]:
        """All metric pairs with strong correlation (|r| ≥ min_r)."""
        return self._try_call_list(self._correlation_engine, "correlation_matrix", min_r=min_r)

    def correlation_matrix(self, min_r: float = 0.3) -> List[Any]:
        """Full correlation matrix above threshold."""
        return self._try_call_list(self._correlation_engine, "correlation_matrix", min_r=min_r)

    def discover_correlations(self, min_r: float = 0.5) -> Dict[str, Any]:
        """Discover pairwise correlations across all tracked metrics."""
        return self._try_call(self._correlation_engine, "discover_correlations", {}, min_r=min_r)

    # ── Alert Delegates ─────────────────────────────────────────────

    def alert_status(self) -> Dict[str, str]:
        """Current alert status map (node → green/yellow/red)."""
        return self._get_alert_status()

    def recent_alerts(self, n: int = 50) -> List[Dict[str, Any]]:
        """Recent routed alerts."""
        if self._alert_router is not None:
            try:
                return self._alert_router.recent_routed(n=n)
            except Exception:
                pass
        if self._metrics_db is not None:
            try:
                return self._metrics_db.get_recent_alerts(limit=n)
            except Exception:
                pass
        return []

    def routing_stats(self) -> Dict[str, Any]:
        """Alert routing statistics."""
        return self._try_call(self._alert_router, "routing_stats", {})

    def suppress_alert(self, node: str, metric: str, duration: float = 3600.0) -> None:
        """Suppress alerts for a node/metric pair for *duration* seconds."""
        if self._alert_router is None:
            logger.warning("Cannot suppress — AlertRouter unavailable")
            return
        try:
            self._alert_router.suppress(node, metric, duration)
            logger.info("Suppressed %s.%s for %.0fs", node, metric, duration)
        except Exception:
            logger.warning("suppress_alert failed", exc_info=True)

    # ── ActivityBus Delegate ────────────────────────────────────────

    def activity_snapshot(self) -> Dict[str, Any]:
        """Current activity bus state (active, history, idle)."""
        return self._try_call(self._activity_bus, "snapshot", {})

    # ── Summary & Dashboard ─────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Aggregate summaries from all subsystems into one dict."""
        result: Dict[str, Any] = {
            "running": self._running,
            "available_subsystems": self._available_subsystems(),
            "ts": time.time(),
        }
        if self._metrics_collector is not None:
            result["metrics_collector"] = {
                "running": getattr(self._metrics_collector, "running", False),
                "last_system": self._metrics_collector.last_system_snapshot,
                "last_pipeline": self._metrics_collector.last_pipeline_summary,
                "last_processes": self._metrics_collector.last_process_snapshot,
            }
        for label, attr, method in [
            ("pack_tracker", "_pack_tracker", "pack_summary"),
            ("anomaly_detector", "_anomaly_detector", "snapshot"),
            ("correlation_engine", "_correlation_engine", "snapshot"),
            ("trend_predictor", "_trend_predictor", "summary"),
            ("alert_router", "_alert_router", "summary"),
            ("activity_bus", "_activity_bus", "snapshot"),
        ]:
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    raw = getattr(obj, method)()
                    result[label] = self._dictify_map(raw) if label == "pack_tracker" else raw
                except Exception:
                    result[label] = {"error": "unavailable"}
        return result

    def dashboard_data(self) -> Dict[str, Any]:
        """Data formatted for Command Center UI consumption.

        Returns:
            Dict with current, health, trends, alerts, packs, anomalies,
            capacity, correlations, activity keys.
        """
        data: Dict[str, Any] = {"ts": time.time()}

        # Current resource values
        sm = self._latest_system_metrics()
        data["current"] = {
            "cpu_pct": sm.get("cpu_pct", 0.0),
            "ram_pct": sm.get("ram_pct", 0.0),
            "gpu_vram_pct": sm.get("gpu_vram_pct", 0.0),
            "gpu_temp_c": sm.get("gpu_temp_c", 0.0),
        }
        if self._system_monitor is not None:
            try:
                data["current"]["services"] = self._system_monitor.check_services()
            except Exception:
                data["current"]["services"] = {}

        # Health summary
        try:
            report = self.health_report()
            data["health"] = {
                "score": report["composite_score"],
                "categories": report["category_scores"],
                "issues_count": len(report["worst_issues"]),
            }
        except Exception:
            data["health"] = {"score": 0, "categories": {}, "issues_count": 0}

        # Trends (serialised for JSON)
        data["trends"] = self._serialise_trends(limit=20)

        # Alerts
        data["alerts"] = {"status_map": self._get_alert_status(), "recent": self.recent_alerts(n=10)}

        # Packs, anomalies, capacity
        data["packs"] = self.top_packs(n=10)
        data["anomalies"] = {"recent": self.recent_anomalies(n=10), "counts": self.anomaly_counts()}
        data["capacity"] = self.capacity_warnings(horizon_minutes=60)

        # Correlations
        if self._correlation_engine is not None:
            try:
                data["correlations"] = self._correlation_engine.strongest_correlations(n=5)
            except Exception:
                data["correlations"] = []
        else:
            data["correlations"] = []

        data["activity"] = self.activity_snapshot()
        return data

    # ── Internal Helpers ────────────────────────────────────────────

    def _latest_system_metrics(self) -> Dict[str, float]:
        """Get latest system metrics from collector cache or SystemMonitor."""
        if self._metrics_collector is not None:
            try:
                return dict(self._metrics_collector.last_system_snapshot)
            except Exception:
                pass
        if self._system_monitor is not None:
            try:
                snap = self._system_monitor.snapshot()
                ram = snap.get("ram", {})
                gpu = snap.get("gpu", {})
                return {
                    "cpu_pct": snap.get("cpu_percent", 0.0),
                    "ram_pct": ram.get("percent", 0.0) if isinstance(ram, dict) else 0.0,
                    "gpu_vram_pct": gpu.get("vram_percent", 0.0) if isinstance(gpu, dict) else 0.0,
                    "gpu_temp_c": gpu.get("temperature", 0.0) if isinstance(gpu, dict) else 0.0,
                }
            except Exception:
                pass
        return {"cpu_pct": 0.0, "ram_pct": 0.0, "gpu_vram_pct": 0.0, "gpu_temp_c": 0.0}

    def _get_alert_status(self) -> Dict[str, str]:
        """Get current alert status map from AlertEngine."""
        if self._metrics_collector is not None:
            try:
                return self._metrics_collector.alert_engine.get_status_map()
            except Exception:
                pass
        return {}

    def _pipeline_perf_score(self, issues: List[Dict[str, Any]]) -> float:
        """Compute performance score from pipeline latency."""
        if self._metrics_collector is None:
            return 100.0
        try:
            pipeline = self._metrics_collector.last_pipeline_summary
            lat = pipeline.get("avg_latency_ms", 0)
            if lat > 2000:
                issues.append({"category": "performance", "detail": f"Avg latency {lat:.0f}ms", "severity": "high"})
                return 20.0
            if lat > 500:
                issues.append({"category": "performance", "detail": f"Avg latency {lat:.0f}ms", "severity": "medium"})
                return 60.0
            return 100.0 if lat <= 200 else 85.0
        except Exception:
            return 100.0

    def _serialise_trends(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Serialise TrendResult objects into JSON-safe dicts."""
        if self._trend_predictor is None:
            return []
        try:
            trends = self._trend_predictor.all_trends()
            out: List[Dict[str, Any]] = []
            for t in trends[:limit]:
                out.append({
                    "metric": t.metric_key,
                    "direction": t.direction.value if hasattr(t.direction, "value") else str(t.direction),
                    "slope": round(t.slope * 60, 6),
                    "severity": t.severity.value if hasattr(t.severity, "value") else str(t.severity),
                    "predicted_1h": round(t.predicted_1h, 2) if t.predicted_1h is not None else None,
                    "current": round(t.current_value, 2),
                })
            return out
        except Exception:
            return []

    def _available_subsystems(self) -> List[str]:
        """List subsystem names that resolved successfully."""
        return [label for label, attr in self._ATTR_NAMES.items() if getattr(self, attr, None) is not None]

    @staticmethod
    def _clamp(value: float) -> float:
        """Clamp value to [0, 100]."""
        return max(0.0, min(100.0, value))

    @staticmethod
    def _safe_call(obj: Any, method: str, log: Optional[str] = None, **kwargs: Any) -> None:
        """Call method on obj if not None; log on success, warn on failure."""
        if obj is None:
            return
        try:
            getattr(obj, method)(**kwargs)
            if log:
                logger.info(log)
        except Exception:
            logger.warning("%s.%s failed", type(obj).__name__, method, exc_info=True)

    @staticmethod
    def _try_call(obj: Any, method: str, default: Any, **kwargs: Any) -> Any:
        """Call method on obj and return result, or default on failure."""
        if obj is None:
            return default
        try:
            return getattr(obj, method)(**kwargs)
        except Exception:
            return default

    @staticmethod
    def _try_call_list(obj: Any, method: str, **kwargs: Any) -> List[Any]:
        """Call method on obj and return list result, or [] on failure."""
        if obj is None:
            return []
        try:
            return getattr(obj, method)(**kwargs)
        except Exception:
            return []

    @staticmethod
    def _dictify_map(raw: Any) -> Dict[str, Any]:
        """Convert a dict of dataclass-like values to plain dicts."""
        if not isinstance(raw, dict):
            return raw
        return {k: (v.to_dict() if hasattr(v, "to_dict") else v) for k, v in raw.items()}
