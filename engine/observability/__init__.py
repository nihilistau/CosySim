"""
CosySim Observability — Metrics collection, persistence, and alerting.

Provides:
- MetricsDB: persistent time-series storage for system and pipeline metrics
- MetricsCollector: background service hooking into all system components
- AlertEngine: configurable green/yellow/red thresholds
- TrainingCapture: auto-captures training data candidates from pipeline events
"""

from engine.observability.alert_router import (
    AlertChannel,
    AlertRouter,
    RoutedAlert,
    RoutingRule,
    get_alert_router,
)
from engine.observability.alerts import Alert, AlertEngine, AlertRule
from engine.observability.metrics_collector import MetricsCollector, get_metrics_collector
from engine.observability.metrics_db import MetricsDB, get_metrics_db
from engine.observability.training_capture import TrainingCapture
from engine.observability.trend_predictor import TrendPredictor, get_trend_predictor
from engine.observability.unified_dashboard import (
    DashboardWidget,
    TimeRange,
    UnifiedDashboard,
    get_unified_dashboard,
)

__all__ = [
    "Alert",
    "AlertChannel",
    "AlertEngine",
    "AlertRouter",
    "AlertRule",
    "DashboardWidget",
    "MetricsCollector",
    "MetricsDB",
    "RoutedAlert",
    "RoutingRule",
    "TimeRange",
    "TrainingCapture",
    "TrendPredictor",
    "UnifiedDashboard",
    "get_alert_router",
    "get_metrics_collector",
    "get_metrics_db",
    "get_trend_predictor",
    "get_unified_dashboard",
]
