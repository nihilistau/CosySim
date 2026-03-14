"""
CosySim Observability — Unified modular monitoring system.

Provides:
- MetricsDB: persistent time-series storage for system and pipeline metrics
- MetricsCollector: background service hooking into all system components
- AlertEngine: configurable green/yellow/red thresholds with state machine
- AlertRouter: routes alerts/anomalies to handlers (log, Nexus, operator, socket)
- TrainingCapture: auto-captures training data candidates from pipeline events
- PackTracker: skill pack ↔ PID ↔ CPU cross-referencing and activity tracking
- AnomalyDetector: z-score, IQR, MAD anomaly detection with per-metric config
- CorrelationEngine: Pearson/Spearman metric correlation and discovery
- TrendPredictor: linear regression trends, capacity warnings, degradation detection
- UnifiedMonitor: top-level orchestrator composing all monitoring subsystems
- UnifiedDashboard: single API surface for all monitoring data with widgets
- DimensionStore: arbitrary tag/dimension support for multi-dimensional metric slicing
"""

from engine.observability.alert_router import (
    AlertChannel,
    AlertRouter,
    RoutedAlert,
    RoutingRule,
    get_alert_router,
)
from engine.observability.alerts import Alert, AlertEngine, AlertRule
from engine.observability.anomaly_detector import (
    AnomalyDetector,
    AnomalyEvent,
    MetricConfig,
    get_anomaly_detector,
)
from engine.observability.anomaly_trigger import (
    AnomalyTrigger,
    TriggerFiring,
    TriggerPattern,
    TriggerRule,
    get_anomaly_trigger,
    register_anomaly_trigger_tasks,
)
from engine.observability.correlation_engine import (
    CorrelationEngine,
    CorrelationResult,
    get_correlation_engine,
)
from engine.observability.metrics_collector import MetricsCollector, get_metrics_collector
from engine.observability.metrics_db import MetricsDB, get_metrics_db
from engine.observability.metric_dimensions import (
    AggregationResult,
    DimensionalMetric,
    DimensionStore,
    TagCardinality,
    get_dimension_store,
)
from engine.observability.pack_tracker import (
    PackActivity,
    PackTracker,
    SkillExecution,
    get_pack_tracker,
)
from engine.observability.training_capture import TrainingCapture
from engine.observability.trend_predictor import TrendPredictor, get_trend_predictor
from engine.observability.unified_dashboard import (
    DashboardWidget,
    TimeRange,
    UnifiedDashboard,
    get_unified_dashboard,
)
from engine.observability.unified_monitor import UnifiedMonitor, get_unified_monitor

__all__ = [
    "AggregationResult",
    "Alert",
    "AlertChannel",
    "AlertEngine",
    "AlertRouter",
    "AlertRule",
    "AnomalyDetector",
    "AnomalyEvent",
    "AnomalyTrigger",
    "CorrelationEngine",
    "CorrelationResult",
    "DashboardWidget",
    "DimensionStore",
    "DimensionalMetric",
    "MetricConfig",
    "MetricsCollector",
    "MetricsDB",
    "PackActivity",
    "PackTracker",
    "RoutedAlert",
    "RoutingRule",
    "SkillExecution",
    "TagCardinality",
    "TimeRange",
    "TrainingCapture",
    "TrendPredictor",
    "TriggerFiring",
    "TriggerPattern",
    "TriggerRule",
    "UnifiedDashboard",
    "UnifiedMonitor",
    "get_alert_router",
    "get_anomaly_detector",
    "get_anomaly_trigger",
    "get_correlation_engine",
    "get_dimension_store",
    "get_metrics_collector",
    "get_metrics_db",
    "get_pack_tracker",
    "get_trend_predictor",
    "get_unified_dashboard",
    "get_unified_monitor",
    "register_anomaly_trigger_tasks",
]
