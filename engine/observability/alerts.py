"""
AlertEngine — Configurable green/yellow/red threshold alerting.

Evaluates metrics against configurable rules and emits state changes.
Uses rolling averages over a configurable window.

Node status is tracked as a traffic-light: green → yellow → red.
Only state *changes* generate alert records (not continuous red).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Data types ──────────────────────────────────────────────────────────

LEVELS = ("green", "yellow", "red")


@dataclass
class AlertRule:
    """A threshold rule for a single metric on a single node."""
    node: str                  # e.g. 'gpu_primary', 'pipeline', 'system_ram'
    metric: str                # e.g. 'latency_ms', 'vram_pct', 'queue_depth'
    yellow: float              # threshold for yellow
    red: float                 # threshold for red
    window: int = 10           # seconds to average over
    invert: bool = False       # if True, lower values are worse (e.g. TPS)


@dataclass
class Alert:
    """A single alert state change."""
    node: str
    level: str
    prev_level: str
    metric: str
    value: float
    threshold: float
    message: str
    ts: float = field(default_factory=time.time)


# ── AlertEngine ─────────────────────────────────────────────────────────

class AlertEngine:
    """
    Evaluates metric samples against rules, tracks node status,
    and emits alerts on state changes.

    Usage::

        engine = AlertEngine(rules=[
            AlertRule(node="gpu_primary", metric="vram_pct", yellow=80, red=95),
            AlertRule(node="pipeline", metric="latency_ms", yellow=500, red=2000),
        ])

        # Feed metrics every tick
        engine.feed("gpu_primary", "vram_pct", 87.3)
        engine.feed("pipeline", "latency_ms", 420.0)

        # Evaluate all rules — returns list of new alerts (state changes only)
        new_alerts = engine.evaluate()
        # {'gpu_primary': 'yellow', 'pipeline': 'green'}
        status_map = engine.get_status_map()
    """

    def __init__(
        self,
        rules: Optional[List[AlertRule]] = None,
        on_alert: Optional[Callable[[Alert], None]] = None,
        metrics_db: Any = None,
    ):
        self._rules = rules or []
        self._on_alert = on_alert
        self._db = metrics_db

        # Metric sample buffers: (node, metric) → deque of (ts, value)
        self._samples: Dict[tuple, deque] = {}

        # Current node status: node → level
        self._status: Dict[str, str] = {}
        for rule in self._rules:
            self._status.setdefault(rule.node, "green")
            key = (rule.node, rule.metric)
            self._samples.setdefault(key, deque(maxlen=1000))

    @property
    def rules(self) -> List[AlertRule]:
        return list(self._rules)

    def add_rule(self, rule: AlertRule) -> None:
        """Add a new alert rule."""
        self._rules.append(rule)
        self._status.setdefault(rule.node, "green")
        key = (rule.node, rule.metric)
        self._samples.setdefault(key, deque(maxlen=1000))

    def feed(self, node: str, metric: str, value: float) -> None:
        """Feed a metric sample."""
        key = (node, metric)
        if key not in self._samples:
            self._samples[key] = deque(maxlen=1000)
        self._samples[key].append((time.time(), value))

    def evaluate(self) -> List[Alert]:
        """
        Evaluate all rules against rolling averages.

        Returns list of new alerts (state changes only).
        """
        alerts: List[Alert] = []
        now = time.time()

        # Evaluate each rule
        for rule in self._rules:
            key = (rule.node, rule.metric)
            samples = self._samples.get(key)
            if not samples:
                continue

            # Compute rolling average over window
            cutoff = now - rule.window
            window_values = [v for ts, v in samples if ts >= cutoff]
            if not window_values:
                continue

            avg = sum(window_values) / len(window_values)

            # Determine level
            if rule.invert:
                # Lower is worse (e.g., TPS — we want high TPS)
                if avg <= rule.red:
                    new_level = "red"
                elif avg <= rule.yellow:
                    new_level = "yellow"
                else:
                    new_level = "green"
            else:
                # Higher is worse (e.g., latency, VRAM%)
                if avg >= rule.red:
                    new_level = "red"
                elif avg >= rule.yellow:
                    new_level = "yellow"
                else:
                    new_level = "green"

            prev_level = self._status.get(rule.node, "green")

            # Only emit alert on state change
            if new_level != prev_level:
                self._status[rule.node] = new_level
                message = (
                    f"{rule.node}.{rule.metric}: {avg:.1f} "
                    f"({'>' if not rule.invert else '<'} "
                    f"{rule.yellow if new_level == 'yellow' else rule.red})"
                )
                alert = Alert(
                    node=rule.node,
                    level=new_level,
                    prev_level=prev_level,
                    metric=rule.metric,
                    value=avg,
                    threshold=rule.yellow if new_level == "yellow" else rule.red,
                    message=message,
                )
                alerts.append(alert)

                # Persist to DB if available
                if self._db:
                    try:
                        self._db.record_alert(
                            node=alert.node,
                            level=alert.level,
                            message=alert.message,
                            prev_level=alert.prev_level,
                        )
                    except Exception as exc:
                        logger.debug("Failed to persist alert: %s", exc)

                # Fire callback
                if self._on_alert:
                    try:
                        self._on_alert(alert)
                    except Exception:
                        pass

                logger.info(
                    "Alert: %s %s → %s (%s)",
                    rule.node, prev_level, new_level, message,
                )

        return alerts

    def get_status_map(self) -> Dict[str, str]:
        """Return current status for all nodes: {node: 'green'|'yellow'|'red'}."""
        return dict(self._status)

    def get_node_status(self, node: str) -> str:
        """Get current status for a specific node."""
        return self._status.get(node, "green")

    def get_worst_level(self) -> str:
        """Get the worst alert level across all nodes."""
        if not self._status:
            return "green"
        if any(v == "red" for v in self._status.values()):
            return "red"
        if any(v == "yellow" for v in self._status.values()):
            return "yellow"
        return "green"

    def reset_node(self, node: str) -> None:
        """Manually reset a node to green."""
        self._status[node] = "green"

    def clear_samples(self) -> None:
        """Clear all metric samples."""
        for d in self._samples.values():
            d.clear()

    @classmethod
    def from_config(cls, config: Dict[str, Any], **kwargs) -> "AlertEngine":
        """
        Create from config dict (e.g. from default.yaml observability.alerts).

        Config format::

            alerts:
              gpu_vram_pct: {yellow: 80, red: 95}
              queue_depth: {yellow: 5, red: 15}
              avg_latency_ms: {yellow: 500, red: 2000}
        """
        rules = []
        for metric, thresholds in config.items():
            if isinstance(thresholds, dict):
                # Infer node from metric name
                node = _infer_node(metric)
                rules.append(AlertRule(
                    node=node,
                    metric=metric,
                    yellow=thresholds.get("yellow", 0),
                    red=thresholds.get("red", 0),
                    window=thresholds.get("window", 10),
                    invert=thresholds.get("invert", False),
                ))
        return cls(rules=rules, **kwargs)


def _infer_node(metric: str) -> str:
    """Infer node name from metric name."""
    if "gpu" in metric:
        return "gpu_primary"
    if "cpu" in metric:
        return "system"
    if "ram" in metric:
        return "system"
    if "queue" in metric:
        return "pipeline"
    if "latency" in metric:
        return "pipeline"
    if "kill" in metric:
        return "pipeline"
    if "error" in metric:
        return "system"
    return "system"
