"""
AlertRouter — Route alerts to handlers based on severity and category.

Implements escalation chains: log → Nexus → operator inbox → Socket.IO.
Provides deduplication, suppression windows, and configurable routing rules.

Usage::

    from engine.observability.alert_router import get_alert_router
    router = get_alert_router()

    # Route an AlertEngine alert
    router.route_alert(alert)

    # Route an anomaly event
    router.route_anomaly(anomaly_event)

    # Add custom handler
    router.add_handler("slack", my_slack_handler, min_severity="high")
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional["AlertRouter"] = None
_lock = threading.Lock()


def get_alert_router(**kwargs: Any) -> AlertRouter:
    """Get or create the singleton AlertRouter."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AlertRouter(**kwargs)
    return _instance


# ── Data Models ─────────────────────────────────────────────────────────

_LEVEL_MAP: Dict[str, int] = {"green": 0, "yellow": 1, "red": 2}
_SEVERITY_MAP: Dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class AlertChannel(Enum):
    """Available routing channels for alerts."""
    LOG = "log"
    NEXUS = "nexus"
    OPERATOR_INBOX = "operator_inbox"
    SOCKETIO = "socketio"
    CUSTOM = "custom"


@dataclass
class RoutingRule:
    """A single routing rule mapping alerts to a delivery channel."""
    name: str
    channel: AlertChannel
    min_level: str = "yellow"
    min_severity: str = "LOW"
    node_filter: Optional[str] = None
    metric_filter: Optional[str] = None
    cooldown_seconds: float = 60.0
    enabled: bool = True


@dataclass
class RoutedAlert:
    """Result of routing an alert or anomaly through the rule engine."""
    source_type: str
    node: str
    metric: str
    level: str
    severity: str
    message: str
    channels_routed: List[str] = field(default_factory=list)
    suppressed: bool = False
    ts: float = field(default_factory=time.time)
    original: Any = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "source_type": self.source_type,
            "node": self.node,
            "metric": self.metric,
            "level": self.level,
            "severity": self.severity,
            "message": self.message,
            "channels_routed": list(self.channels_routed),
            "suppressed": self.suppressed,
            "ts": self.ts,
        }


@dataclass
class _CustomHandler:
    """Internal wrapper for a registered custom handler."""
    name: str
    fn: Callable[[RoutedAlert], None]
    min_severity: str = "LOW"


# ── DB Schema ───────────────────────────────────────────────────────────

_ROUTING_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_routing_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type  TEXT    NOT NULL,
    node         TEXT    NOT NULL,
    metric       TEXT    NOT NULL,
    level        TEXT    NOT NULL,
    severity     TEXT    NOT NULL,
    message      TEXT    NOT NULL DEFAULT '',
    channels     TEXT    NOT NULL DEFAULT '[]',
    suppressed   INTEGER NOT NULL DEFAULT 0,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    ts           REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_arl_ts       ON alert_routing_log(ts);
CREATE INDEX IF NOT EXISTS idx_arl_node     ON alert_routing_log(node, metric, ts);
CREATE INDEX IF NOT EXISTS idx_arl_severity ON alert_routing_log(severity, ts);
CREATE INDEX IF NOT EXISTS idx_arl_ack      ON alert_routing_log(acknowledged, ts);
"""


# ── AlertRouter ─────────────────────────────────────────────────────────


class AlertRouter:
    """Central alert/anomaly routing engine.

    Evaluates incoming Alert and AnomalyEvent objects against a list of
    RoutingRules, dispatches to matching channels (log, Nexus, operator
    inbox, Socket.IO, custom handlers), and persists a routing log.

    Thread-safe singleton.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        default_rules: bool = True,
    ):
        self._lock = threading.Lock()
        self._db_path = db_path
        self._db_local = threading.local()
        self._init_db()

        self._rules: List[RoutingRule] = []
        self._custom_handlers: Dict[str, _CustomHandler] = {}
        self._cooldowns: Dict[str, float] = {}       # "rule::node::metric" → ts
        self._suppressions: Dict[str, float] = {}     # "node::metric" → expiry ts

        if default_rules:
            self._rules.extend(self._default_rules())
        logger.info("AlertRouter initialised (%d rules)", len(self._rules))

    # ── DB helpers ──────────────────────────────────────────────────────

    def _get_db(self) -> sqlite3.Connection:
        """Thread-local SQLite connection."""
        if not hasattr(self._db_local, "conn") or self._db_local.conn is None:
            path = self._db_path
            if not path:
                from engine.paths import DATA_DIR
                path = str(DATA_DIR / "metrics.db")
            self._db_local.conn = sqlite3.connect(path, timeout=5)
            self._db_local.conn.row_factory = sqlite3.Row
            self._db_local.conn.execute("PRAGMA journal_mode=WAL")
            self._db_local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._db_local.conn

    def _init_db(self) -> None:
        """Create the alert_routing_log table."""
        try:
            conn = self._get_db()
            conn.executescript(_ROUTING_SCHEMA)
            conn.commit()
        except Exception as exc:
            logger.warning("AlertRouter DB init failed: %s", exc)

    # ── Routing API ─────────────────────────────────────────────────────

    def route_alert(self, alert: Any) -> RoutedAlert:
        """Route an AlertEngine Alert through all matching rules."""
        level = getattr(alert, "level", "green")
        node = getattr(alert, "node", "unknown")
        metric = getattr(alert, "metric", "unknown")
        value = getattr(alert, "value", 0.0)
        threshold = getattr(alert, "threshold", 0.0)
        message = getattr(alert, "message", "") or (
            f"{node}.{metric}={value:.2f} (threshold {threshold:.2f})"
        )
        routed = RoutedAlert(
            source_type="alert",
            node=node, metric=metric,
            level=level,
            severity=self._level_to_severity_label(level),
            message=message,
            ts=getattr(alert, "ts", time.time()),
            original=alert,
        )
        self._dispatch(routed)
        return routed

    def route_anomaly(self, event: Any) -> RoutedAlert:
        """Route an AnomalyEvent through all matching rules."""
        node = getattr(event, "node", "unknown")
        metric = getattr(event, "metric", "unknown")
        value = getattr(event, "value", 0.0)
        expected = getattr(event, "expected_mean", 0.0)
        deviation = getattr(event, "deviation", 0.0)

        sev_enum = getattr(event, "severity", None)
        severity_str = (
            str(sev_enum.value).upper() if hasattr(sev_enum, "value")
            else str(sev_enum or "LOW").upper()
        )
        message = getattr(event, "message", "") or (
            f"Anomaly on {node}.{metric}: value={value:.2f}, "
            f"expected={expected:.2f}, deviation={deviation:.2f}"
        )
        routed = RoutedAlert(
            source_type="anomaly",
            node=node, metric=metric,
            level=self._severity_to_level(severity_str),
            severity=severity_str,
            message=message,
            ts=getattr(event, "timestamp", time.time()),
            original=event,
        )
        self._dispatch(routed)
        return routed

    # ── Rule management ─────────────────────────────────────────────────

    def add_rule(self, rule: RoutingRule) -> None:
        """Add a routing rule (replaces existing rule with same name)."""
        with self._lock:
            self._rules = [r for r in self._rules if r.name != rule.name]
            self._rules.append(rule)
        logger.debug("Routing rule added: %s", rule.name)

    def remove_rule(self, name: str) -> bool:
        """Remove a routing rule by name. Returns True if found."""
        with self._lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if r.name != name]
            removed = len(self._rules) < before
        if removed:
            logger.debug("Routing rule removed: %s", name)
        return removed

    # ── Handler management ──────────────────────────────────────────────

    def add_handler(
        self,
        name: str,
        handler: Callable[[RoutedAlert], None],
        min_severity: str = "LOW",
    ) -> None:
        """Register a custom handler callable."""
        with self._lock:
            self._custom_handlers[name] = _CustomHandler(
                name=name, fn=handler, min_severity=min_severity.upper(),
            )
        logger.debug("Custom handler registered: %s", name)

    def remove_handler(self, name: str) -> bool:
        """Remove a custom handler. Returns True if found."""
        with self._lock:
            removed = self._custom_handlers.pop(name, None) is not None
        if removed:
            logger.debug("Custom handler removed: %s", name)
        return removed

    # ── Suppression ─────────────────────────────────────────────────────

    def suppress(self, node: str, metric: str, duration_seconds: float = 300.0) -> None:
        """Suppress alerts for a node/metric combo for *duration_seconds*."""
        key = f"{node}::{metric}"
        with self._lock:
            self._suppressions[key] = time.time() + duration_seconds
        logger.info("Suppressing %s.%s for %.0fs", node, metric, duration_seconds)

    def unsuppress(self, node: str, metric: str) -> None:
        """Remove suppression for a node/metric combination."""
        key = f"{node}::{metric}"
        with self._lock:
            self._suppressions.pop(key, None)
        logger.info("Unsuppressed %s.%s", node, metric)

    # ── Query API ───────────────────────────────────────────────────────

    def recent_routed(self, n: int = 50) -> List[Dict[str, Any]]:
        """Recent routed alerts from DB (newest first)."""
        try:
            conn = self._get_db()
            rows = conn.execute(
                "SELECT * FROM alert_routing_log ORDER BY ts DESC LIMIT ?", (n,),
            ).fetchall()
            return [
                {
                    "id": r["id"], "source_type": r["source_type"],
                    "node": r["node"], "metric": r["metric"],
                    "level": r["level"], "severity": r["severity"],
                    "message": r["message"],
                    "channels": json.loads(r["channels"]),
                    "suppressed": bool(r["suppressed"]),
                    "acknowledged": bool(r["acknowledged"]),
                    "ts": r["ts"],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("Failed to query recent routed alerts: %s", exc)
            return []

    def routing_stats(self) -> Dict[str, Any]:
        """Aggregate stats: totals, per-channel counts, top nodes."""
        try:
            conn = self._get_db()
            total = conn.execute("SELECT COUNT(*) FROM alert_routing_log").fetchone()[0]
            suppressed = conn.execute(
                "SELECT COUNT(*) FROM alert_routing_log WHERE suppressed = 1",
            ).fetchone()[0]
            acknowledged = conn.execute(
                "SELECT COUNT(*) FROM alert_routing_log WHERE acknowledged = 1",
            ).fetchone()[0]

            sev_rows = conn.execute(
                "SELECT severity, COUNT(*) AS cnt "
                "FROM alert_routing_log GROUP BY severity",
            ).fetchall()
            per_severity = {r["severity"]: r["cnt"] for r in sev_rows}

            cutoff = time.time() - 86400
            top_rows = conn.execute(
                "SELECT node, COUNT(*) AS cnt FROM alert_routing_log "
                "WHERE ts > ? AND suppressed = 0 "
                "GROUP BY node ORDER BY cnt DESC LIMIT 10",
                (cutoff,),
            ).fetchall()
            top_nodes = {r["node"]: r["cnt"] for r in top_rows}

            per_channel: Dict[str, int] = {}
            for row in conn.execute(
                "SELECT channels FROM alert_routing_log WHERE suppressed = 0",
            ).fetchall():
                for ch in json.loads(row["channels"]):
                    per_channel[ch] = per_channel.get(ch, 0) + 1

            return {
                "total_routed": total, "total_suppressed": suppressed,
                "total_acknowledged": acknowledged,
                "per_severity": per_severity, "per_channel": per_channel,
                "top_nodes_24h": top_nodes,
            }
        except Exception as exc:
            logger.warning("Failed to compute routing stats: %s", exc)
            return {"total_routed": 0, "error": str(exc)}

    def escalation_check(self) -> List[Dict[str, Any]]:
        """Alerts at red/CRITICAL for >5 min that remain un-acknowledged."""
        cutoff = time.time() - 300
        try:
            conn = self._get_db()
            rows = conn.execute(
                "SELECT * FROM alert_routing_log "
                "WHERE acknowledged = 0 "
                "  AND (level = 'red' OR severity IN ('HIGH', 'CRITICAL')) "
                "  AND ts < ? ORDER BY ts ASC",
                (cutoff,),
            ).fetchall()
            return [
                {
                    "id": r["id"], "node": r["node"], "metric": r["metric"],
                    "level": r["level"], "severity": r["severity"],
                    "message": r["message"], "ts": r["ts"],
                    "age_seconds": round(time.time() - r["ts"], 1),
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("Escalation check failed: %s", exc)
            return []

    def acknowledge(self, alert_id: int) -> bool:
        """Mark a routed alert as acknowledged."""
        try:
            conn = self._get_db()
            cur = conn.execute(
                "UPDATE alert_routing_log SET acknowledged = 1 WHERE id = ?",
                (alert_id,),
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception as exc:
            logger.warning("Acknowledge failed for id=%s: %s", alert_id, exc)
            return False

    def summary(self) -> Dict[str, Any]:
        """Overall summary: rules, handlers, suppressions, stats."""
        with self._lock:
            now = time.time()
            active = {k: round(v - now, 1) for k, v in self._suppressions.items() if v > now}
        return {
            "rule_count": len(self._rules),
            "rules": [r.name for r in self._rules],
            "custom_handler_count": len(self._custom_handlers),
            "custom_handlers": list(self._custom_handlers.keys()),
            "active_suppressions": active,
            "pending_escalations": len(self.escalation_check()),
            "stats": self.routing_stats(),
        }

    # ── Dispatch internals ──────────────────────────────────────────────

    def _dispatch(self, routed: RoutedAlert) -> None:
        """Evaluate rules and send to matching channels."""
        with self._lock:
            suppressed = self._is_suppressed(routed.node, routed.metric)
        if suppressed:
            routed.suppressed = True
            self._persist(routed)
            logger.debug("Suppressed: %s.%s (%s)", routed.node, routed.metric, routed.severity)
            return

        channels_fired: List[str] = []
        with self._lock:
            rules_snapshot = list(self._rules)
            handlers_snapshot = dict(self._custom_handlers)

        # Evaluate routing rules
        for rule in rules_snapshot:
            if not rule.enabled or not self._rule_matches(rule, routed):
                continue
            if self._check_cooldown(rule.name, routed.node, routed.metric):
                continue

            dispatched = self._dispatch_to_channel(rule.channel, routed, handlers_snapshot)
            if dispatched:
                ch = rule.channel.value
                if ch not in channels_fired:
                    channels_fired.append(ch)
            with self._lock:
                self._cooldowns[f"{rule.name}::{routed.node}::{routed.metric}"] = time.time()

        # Fire registered custom handlers (independent of CUSTOM-channel rules)
        for h in handlers_snapshot.values():
            if self._severity_to_int(routed.severity) >= self._severity_to_int(h.min_severity):
                try:
                    h.fn(routed)
                    if "custom" not in channels_fired:
                        channels_fired.append("custom")
                except Exception as exc:
                    logger.error("Custom handler '%s' failed: %s", h.name, exc)

        routed.channels_routed = channels_fired
        self._persist(routed)

    def _dispatch_to_channel(
        self,
        channel: AlertChannel,
        routed: RoutedAlert,
        handlers: Dict[str, _CustomHandler],
    ) -> bool:
        """Send a routed alert to a specific channel."""
        dispatch_map: Dict[AlertChannel, Callable[..., bool]] = {
            AlertChannel.LOG: lambda: self._handle_log(routed),
            AlertChannel.NEXUS: lambda: self._handle_nexus(routed),
            AlertChannel.OPERATOR_INBOX: lambda: self._handle_operator_inbox(routed),
            AlertChannel.SOCKETIO: lambda: self._handle_socketio(routed),
        }
        fn = dispatch_map.get(channel)
        return fn() if fn else False

    def _rule_matches(self, rule: RoutingRule, routed: RoutedAlert) -> bool:
        """Check whether a routing rule matches the routed alert."""
        if routed.source_type == "alert":
            if self._level_to_severity(routed.level) < self._level_to_severity(rule.min_level):
                return False
        if routed.source_type == "anomaly":
            if self._severity_to_int(routed.severity) < self._severity_to_int(rule.min_severity):
                return False
        if rule.node_filter:
            try:
                if not re.search(rule.node_filter, routed.node, re.IGNORECASE):
                    return False
            except re.error:
                pass
        if rule.metric_filter:
            try:
                if not re.search(rule.metric_filter, routed.metric, re.IGNORECASE):
                    return False
            except re.error:
                pass
        return True

    # ── Channel handlers ────────────────────────────────────────────────

    def _handle_log(self, routed: RoutedAlert) -> bool:
        """Log the alert via the module logger."""
        sev = self._severity_to_int(routed.severity)
        args = (
            "[%s] %s.%s — %s (level=%s, severity=%s)",
            routed.source_type.upper(), routed.node, routed.metric,
            routed.message, routed.level, routed.severity,
        )
        if sev >= 3:
            logger.error(*args)
        elif sev >= 2:
            logger.warning(*args)
        else:
            logger.info(*args)
        return True

    def _handle_nexus(self, routed: RoutedAlert) -> bool:
        """Store the alert in Nexus via the client (graceful if unavailable)."""
        try:
            from engine.nexus.client import get_nexus_client
            get_nexus_client().add_entry(
                title=f"Alert: {routed.node}.{routed.metric} [{routed.severity}]",
                content=(
                    f"Source: {routed.source_type}\nNode: {routed.node}\n"
                    f"Metric: {routed.metric}\nLevel: {routed.level}\n"
                    f"Severity: {routed.severity}\nMessage: {routed.message}\n"
                    f"Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(routed.ts))}"
                ),
                content_type="note", category="alerts",
            )
            return True
        except Exception as exc:
            logger.debug("Nexus handler unavailable: %s", exc)
            return False

    def _handle_operator_inbox(self, routed: RoutedAlert) -> bool:
        """Send the alert to the operator inbox (graceful if unavailable)."""
        try:
            from engine.nexus.operator_inbox import get_operator_inbox
            get_operator_inbox().submit_item(
                title=f"[{routed.severity}] {routed.node}.{routed.metric}",
                content=routed.message,
                item_type="alert",
                priority="high" if self._severity_to_int(routed.severity) >= 2 else "normal",
                tags=["observability", routed.source_type, routed.severity.lower()],
                source="alert_router", author="system",
            )
            return True
        except Exception as exc:
            logger.debug("Operator inbox unavailable: %s", exc)
            return False

    def _handle_socketio(self, routed: RoutedAlert) -> bool:
        """Emit the alert via Socket.IO (graceful if unavailable)."""
        try:
            from flask import current_app
            sio = current_app.extensions.get("socketio")
            if sio is None:
                return False
            sio.emit("alert", routed.to_dict())
            return True
        except Exception as exc:
            logger.debug("Socket.IO handler unavailable: %s", exc)
            return False

    # ── Suppression / cooldown helpers ──────────────────────────────────

    def _is_suppressed(self, node: str, metric: str) -> bool:
        """Check suppression state (exact + wildcard, lazy cleanup)."""
        now = time.time()
        keys = [f"{node}::{metric}", f"*::{metric}", f"{node}::*", "*::*"]
        expired: List[str] = []
        for key in keys:
            expiry = self._suppressions.get(key)
            if expiry is not None:
                if now < expiry:
                    return True
                expired.append(key)
        for key in expired:
            self._suppressions.pop(key, None)
        return False

    def _check_cooldown(self, rule_name: str, node: str, metric: str) -> bool:
        """Return True if the rule is still in cooldown for this node/metric."""
        cd_key = f"{rule_name}::{node}::{metric}"
        last = self._cooldowns.get(cd_key)
        if last is None:
            return False
        cooldown_s = 60.0
        for rule in self._rules:
            if rule.name == rule_name:
                cooldown_s = rule.cooldown_seconds
                break
        return (time.time() - last) < cooldown_s

    # ── Severity / level mapping ────────────────────────────────────────

    @staticmethod
    def _level_to_severity(level: str) -> int:
        """Map 'green'→0, 'yellow'→1, 'red'→2."""
        return _LEVEL_MAP.get(level.lower(), 0)

    @staticmethod
    def _severity_to_int(severity: str) -> int:
        """Map LOW→0, MEDIUM→1, HIGH→2, CRITICAL→3."""
        return _SEVERITY_MAP.get(severity.lower(), 0)

    @staticmethod
    def _level_to_severity_label(level: str) -> str:
        """Convert alert level to severity label (green→LOW, yellow→MEDIUM, red→HIGH)."""
        return {"green": "LOW", "yellow": "MEDIUM", "red": "HIGH"}.get(level.lower(), "LOW")

    @staticmethod
    def _severity_to_level(severity: str) -> str:
        """Convert severity to alert level (LOW→green, MEDIUM→yellow, HIGH/CRITICAL→red)."""
        return {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "CRITICAL": "red"}.get(
            severity.upper(), "green",
        )

    # ── Persistence ─────────────────────────────────────────────────────

    def _persist(self, routed: RoutedAlert) -> None:
        """Write a routing log entry to the DB."""
        try:
            conn = self._get_db()
            conn.execute(
                "INSERT INTO alert_routing_log "
                "(source_type, node, metric, level, severity, message, channels, suppressed, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    routed.source_type, routed.node, routed.metric,
                    routed.level, routed.severity, routed.message,
                    json.dumps(routed.channels_routed),
                    1 if routed.suppressed else 0, routed.ts,
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("Failed to persist routed alert: %s", exc)

    # ── Default rules ───────────────────────────────────────────────────

    @staticmethod
    def _default_rules() -> List[RoutingRule]:
        """Six standard routing rules for log, Nexus, operator, and Socket.IO."""
        return [
            RoutingRule(
                name="log_all_alerts", channel=AlertChannel.LOG,
                min_level="yellow", min_severity="LOW", cooldown_seconds=30.0,
            ),
            RoutingRule(
                name="nexus_red_alerts", channel=AlertChannel.NEXUS,
                min_level="red", min_severity="LOW", cooldown_seconds=120.0,
            ),
            RoutingRule(
                name="nexus_high_anomalies", channel=AlertChannel.NEXUS,
                min_level="yellow", min_severity="HIGH", cooldown_seconds=120.0,
            ),
            RoutingRule(
                name="operator_critical", channel=AlertChannel.OPERATOR_INBOX,
                min_level="red", min_severity="LOW",
                node_filter=r"gpu|system", cooldown_seconds=300.0,
            ),
            RoutingRule(
                name="operator_critical_anomalies", channel=AlertChannel.OPERATOR_INBOX,
                min_level="yellow", min_severity="CRITICAL", cooldown_seconds=300.0,
            ),
            RoutingRule(
                name="socketio_all", channel=AlertChannel.SOCKETIO,
                min_level="yellow", min_severity="LOW", cooldown_seconds=10.0,
            ),
        ]
