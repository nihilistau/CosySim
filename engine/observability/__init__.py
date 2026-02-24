"""
CosySim Observability — Metrics collection, persistence, and alerting.

Provides:
- MetricsDB: persistent time-series storage for system and pipeline metrics
- MetricsCollector: background service hooking into all system components
- AlertEngine: configurable green/yellow/red thresholds
- TrainingCapture: auto-captures training data candidates from pipeline events
"""

from engine.observability.alerts import Alert, AlertEngine, AlertRule
from engine.observability.metrics_collector import MetricsCollector, get_metrics_collector
from engine.observability.metrics_db import MetricsDB, get_metrics_db
from engine.observability.training_capture import TrainingCapture

__all__ = [
    "Alert",
    "AlertEngine",
    "AlertRule",
    "MetricsCollector",
    "MetricsDB",
    "TrainingCapture",
    "get_metrics_collector",
    "get_metrics_db",
]
