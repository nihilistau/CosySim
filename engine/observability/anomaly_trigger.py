"""
AnomalyTrigger — Bridge AnomalyDetector events to SchedulerDaemon corrective tasks.

When the AnomalyDetector fires an anomaly event, AnomalyTrigger evaluates it
against registered trigger rules.  Each matching rule can fire a scheduler task,
subject to severity thresholds and cooldown windows.

Two integration modes:

1. **Callback mode** (preferred) — call ``wire_detector()`` so every anomaly
   event flows through ``on_anomaly()`` in real-time.
2. **Polling mode** — the ``anomaly-trigger-check`` scheduler task periodically
   reads ``recent_anomalies()`` from the detector and feeds them.

Usage::

    from engine.observability.anomaly_trigger import get_anomaly_trigger

    trigger = get_anomaly_trigger()
    trigger.wire_detector()

    # Register a custom trigger
    from engine.observability.anomaly_trigger import TriggerPattern
    from engine.observability.anomaly_detector import AnomalySeverity

    trigger.register_trigger(
        name="latency-spike-collect",
        pattern=TriggerPattern(node_prefix="pipeline", metric_contains="latency"),
        task_id="metrics-collect",
        cooldown_seconds=120,
        min_severity=AnomalySeverity.HIGH,
    )
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Data Models ─────────────────────────────────────────────────────────


@dataclass
class TriggerPattern:
    """Pattern for matching anomaly events.

    All non-None fields must match for the pattern to trigger.  A pattern
    with all fields set to None matches every event.

    Attributes:
        node: Exact-match on AnomalyEvent.node (None = any).
        metric: Exact-match on AnomalyEvent.metric (None = any).
        node_prefix: Prefix match on node (e.g. ``"gpu"`` matches ``"gpu_primary"``).
        metric_contains: Substring match on metric (e.g. ``"cpu"`` matches ``"cpu_pct"``).
    """

    node: Optional[str] = None
    metric: Optional[str] = None
    node_prefix: Optional[str] = None
    metric_contains: Optional[str] = None

    def matches(self, event: Any) -> bool:
        """Check whether *event* satisfies every non-None constraint.

        Args:
            event: An ``AnomalyEvent`` (or any object with ``.node`` and ``.metric``).

        Returns:
            ``True`` if all specified constraints match.
        """
        if self.node is not None and event.node != self.node:
            return False
        if self.metric is not None and event.metric != self.metric:
            return False
        if self.node_prefix is not None and not event.node.startswith(self.node_prefix):
            return False
        if self.metric_contains is not None and self.metric_contains not in event.metric:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "node": self.node,
            "metric": self.metric,
            "node_prefix": self.node_prefix,
            "metric_contains": self.metric_contains,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TriggerPattern:
        """Deserialize from a dict.

        Args:
            data: Dict produced by ``to_dict()``.

        Returns:
            Reconstructed ``TriggerPattern``.
        """
        return cls(
            node=data.get("node"),
            metric=data.get("metric"),
            node_prefix=data.get("node_prefix"),
            metric_contains=data.get("metric_contains"),
        )


@dataclass
class TriggerRule:
    """A rule binding an anomaly pattern to a scheduler task.

    Attributes:
        rule_id: Unique identifier (``"trig-<uuid[:8]>"``).
        name: Human-readable name.
        pattern: ``TriggerPattern`` controlling which anomalies match.
        task_id: Scheduler task to fire on match.
        cooldown_seconds: Minimum seconds between successive firings.
        min_severity: Minimum ``AnomalySeverity`` to trigger.
        enabled: Whether the rule is active.
        created_at: Unix timestamp of creation.
        last_fired: Unix timestamp of last successful firing.
        fire_count: Cumulative number of firings.
        metadata: Arbitrary extra data.
    """

    rule_id: str
    name: str
    pattern: TriggerPattern
    task_id: str
    cooldown_seconds: float = 300.0
    min_severity: str = "medium"
    enabled: bool = True
    created_at: float = 0.0
    last_fired: Optional[float] = None
    fire_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TriggerFiring:
    """Record of a trigger rule being fired.

    Attributes:
        firing_id: Unique identifier (``"fire-<uuid[:8]>"``).
        rule_id: ID of the trigger rule that fired.
        anomaly_event: Serialized ``AnomalyEvent``.
        task_id: Scheduler task that was invoked.
        task_result: Result dict returned by ``daemon.run_task()``.
        fired_at: Unix timestamp.
        success: Whether the task completed successfully.
        error: Error message if task failed.
    """

    firing_id: str
    rule_id: str
    anomaly_event: Dict[str, Any]
    task_id: str
    task_result: Optional[Dict[str, Any]]
    fired_at: float
    success: bool
    error: Optional[str] = None


# ── Severity Ordering ───────────────────────────────────────────────────

_SEVERITY_ORDER: Dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


def _severity_value(severity: Any) -> int:
    """Return a numeric severity rank for comparison.

    Args:
        severity: An ``AnomalySeverity`` enum member or a string.

    Returns:
        Integer rank (0-3).
    """
    if hasattr(severity, "value"):
        return _SEVERITY_ORDER.get(severity.value, 0)
    return _SEVERITY_ORDER.get(str(severity).lower(), 0)


# ── SQLite Schema ───────────────────────────────────────────────────────

_TRIGGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS trigger_rules (
    rule_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    pattern TEXT NOT NULL,
    task_id TEXT NOT NULL,
    cooldown_seconds REAL DEFAULT 300,
    min_severity TEXT DEFAULT 'medium',
    enabled INTEGER DEFAULT 1,
    created_at REAL,
    last_fired REAL,
    fire_count INTEGER DEFAULT 0,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS trigger_firings (
    firing_id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    anomaly_event TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task_result TEXT,
    fired_at REAL NOT NULL,
    success INTEGER DEFAULT 1,
    error TEXT,
    FOREIGN KEY (rule_id) REFERENCES trigger_rules(rule_id)
);

CREATE INDEX IF NOT EXISTS idx_tf_rule ON trigger_firings(rule_id);
CREATE INDEX IF NOT EXISTS idx_tf_ts ON trigger_firings(fired_at);
"""


# ── AnomalyTrigger ─────────────────────────────────────────────────────


class AnomalyTrigger:
    """Bridge AnomalyDetector events to SchedulerDaemon corrective actions.

    When an anomaly is detected, matching trigger rules fire the associated
    scheduler task, respecting cooldown periods and severity thresholds.

    Thread-safe via a ``threading.Lock`` on all state mutations and
    ``threading.local`` for SQLite connections.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._lock = threading.Lock()
        self._db_path = db_path
        self._db_local = threading.local()
        self._rules: Dict[str, TriggerRule] = {}
        self._dedup: Dict[str, float] = {}

        self._init_schema()
        self._load_rules_from_db()
        self._register_builtin_triggers()

    # ── DB Helpers ──────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection.

        Returns:
            A ``sqlite3.Connection`` with WAL mode and row-factory enabled.
        """
        if not hasattr(self._db_local, "conn") or self._db_local.conn is None:
            path = self._resolve_db_path()
            self._db_local.conn = sqlite3.connect(path, timeout=5)
            self._db_local.conn.row_factory = sqlite3.Row
            self._db_local.conn.execute("PRAGMA journal_mode=WAL")
            self._db_local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._db_local.conn

    def _resolve_db_path(self) -> str:
        """Determine the database file path.

        Returns:
            Absolute path string to the metrics database.
        """
        if self._db_path:
            return str(self._db_path)
        try:
            from engine.paths import DATA_DIR
            return str(DATA_DIR / "metrics.db")
        except Exception:
            return "data/metrics.db"

    def _init_schema(self) -> None:
        """Create trigger tables if they do not already exist."""
        try:
            conn = self._get_conn()
            conn.executescript(_TRIGGER_SCHEMA)
            conn.commit()
        except Exception as exc:
            logger.warning("AnomalyTrigger schema init failed: %s", exc)

    def _load_rules_from_db(self) -> None:
        """Load all persisted trigger rules into the in-memory cache."""
        try:
            conn = self._get_conn()
            rows = conn.execute("SELECT * FROM trigger_rules").fetchall()
            for row in rows:
                rule = self._row_to_rule(row)
                self._rules[rule.rule_id] = rule
            logger.debug("Loaded %d trigger rules from DB", len(rows))
        except Exception as exc:
            logger.warning("Failed to load trigger rules: %s", exc)

    @staticmethod
    def _row_to_rule(row: sqlite3.Row) -> TriggerRule:
        """Convert a DB row to a ``TriggerRule``.

        Args:
            row: A ``sqlite3.Row`` from the ``trigger_rules`` table.

        Returns:
            Reconstructed ``TriggerRule``.
        """
        pattern_data = json.loads(row["pattern"]) if row["pattern"] else {}
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        return TriggerRule(
            rule_id=row["rule_id"],
            name=row["name"],
            pattern=TriggerPattern.from_dict(pattern_data),
            task_id=row["task_id"],
            cooldown_seconds=float(row["cooldown_seconds"]),
            min_severity=row["min_severity"],
            enabled=bool(row["enabled"]),
            created_at=float(row["created_at"] or 0),
            last_fired=float(row["last_fired"]) if row["last_fired"] is not None else None,
            fire_count=int(row["fire_count"]),
            metadata=metadata,
        )

    def _persist_rule(self, rule: TriggerRule) -> None:
        """Insert or replace a trigger rule in the database.

        Args:
            rule: The ``TriggerRule`` to persist.
        """
        try:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO trigger_rules
                   (rule_id, name, pattern, task_id, cooldown_seconds,
                    min_severity, enabled, created_at, last_fired,
                    fire_count, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rule.rule_id,
                    rule.name,
                    json.dumps(rule.pattern.to_dict()),
                    rule.task_id,
                    rule.cooldown_seconds,
                    rule.min_severity,
                    int(rule.enabled),
                    rule.created_at,
                    rule.last_fired,
                    rule.fire_count,
                    json.dumps(rule.metadata) if rule.metadata else None,
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("Failed to persist trigger rule %s: %s", rule.rule_id, exc)

    def _persist_firing(self, firing: TriggerFiring) -> None:
        """Record a trigger firing in the database.

        Args:
            firing: The ``TriggerFiring`` to persist.
        """
        try:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO trigger_firings
                   (firing_id, rule_id, anomaly_event, task_id,
                    task_result, fired_at, success, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    firing.firing_id,
                    firing.rule_id,
                    json.dumps(firing.anomaly_event),
                    firing.task_id,
                    json.dumps(firing.task_result) if firing.task_result else None,
                    firing.fired_at,
                    int(firing.success),
                    firing.error,
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("Failed to persist firing %s: %s", firing.firing_id, exc)

    # ── Rule Management ─────────────────────────────────────────────

    def register_trigger(
        self,
        name: str,
        pattern: TriggerPattern,
        task_id: str,
        cooldown_seconds: float = 300.0,
        min_severity: Any = None,
        enabled: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TriggerRule:
        """Register a new trigger rule.

        Args:
            name: Human-readable trigger name.
            pattern: ``TriggerPattern`` defining which anomalies to match.
            task_id: Scheduler task ID to fire when triggered.
            cooldown_seconds: Minimum seconds between firings.
            min_severity: Minimum ``AnomalySeverity`` to trigger.  Accepts an
                enum member or a string like ``"high"``.
            enabled: Whether the trigger is active.
            metadata: Additional metadata dict.

        Returns:
            The newly created ``TriggerRule``.
        """
        if min_severity is None:
            severity_str = "medium"
        elif hasattr(min_severity, "value"):
            severity_str = min_severity.value
        else:
            severity_str = str(min_severity).lower()

        rule_id = f"trig-{uuid.uuid4().hex[:8]}"
        rule = TriggerRule(
            rule_id=rule_id,
            name=name,
            pattern=pattern,
            task_id=task_id,
            cooldown_seconds=cooldown_seconds,
            min_severity=severity_str,
            enabled=enabled,
            created_at=time.time(),
            metadata=metadata or {},
        )
        with self._lock:
            self._rules[rule_id] = rule
        self._persist_rule(rule)
        logger.info("Registered trigger rule %s (%s → %s)", rule_id, name, task_id)
        return rule

    def remove_trigger(self, rule_id: str) -> bool:
        """Remove a trigger rule by ID.

        Args:
            rule_id: The rule to remove.

        Returns:
            ``True`` if the rule was found and removed.
        """
        with self._lock:
            removed = self._rules.pop(rule_id, None)
        if removed is None:
            return False
        try:
            conn = self._get_conn()
            conn.execute("DELETE FROM trigger_rules WHERE rule_id = ?", (rule_id,))
            conn.commit()
        except Exception as exc:
            logger.warning("Failed to delete rule %s from DB: %s", rule_id, exc)
        logger.info("Removed trigger rule %s (%s)", rule_id, removed.name)
        return True

    def enable_trigger(self, rule_id: str) -> bool:
        """Enable a disabled trigger.

        Args:
            rule_id: The rule to enable.

        Returns:
            ``True`` if the rule was found and enabled.
        """
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule is None:
                return False
            rule.enabled = True
        self._persist_rule(rule)
        logger.info("Enabled trigger rule %s", rule_id)
        return True

    def disable_trigger(self, rule_id: str) -> bool:
        """Disable a trigger without removing it.

        Args:
            rule_id: The rule to disable.

        Returns:
            ``True`` if the rule was found and disabled.
        """
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule is None:
                return False
            rule.enabled = False
        self._persist_rule(rule)
        logger.info("Disabled trigger rule %s", rule_id)
        return True

    # ── Core Event Processing ───────────────────────────────────────

    def on_anomaly(self, event: Any) -> List[TriggerFiring]:
        """Process an anomaly event against all registered trigger rules.

        For each matching, enabled rule:

        1. Verify event severity >= ``min_severity``.
        2. Verify cooldown has elapsed since ``last_fired``.
        3. Fire the scheduler task via ``daemon.run_task(task_id)``.
        4. Record the firing in the ``trigger_firings`` table.
        5. Update the rule's ``last_fired`` and ``fire_count``.

        Args:
            event: An ``AnomalyEvent`` from the anomaly detector.

        Returns:
            List of ``TriggerFiring`` records for all fired triggers.
        """
        now = time.time()
        firings: List[TriggerFiring] = []

        event_severity = _severity_value(event.severity)
        event_dict = event.to_dict() if hasattr(event, "to_dict") else {"node": event.node, "metric": event.metric}

        with self._lock:
            candidates = [r for r in self._rules.values() if r.enabled]

        for rule in candidates:
            if not rule.pattern.matches(event):
                continue

            rule_severity = _severity_value(rule.min_severity)
            if event_severity < rule_severity:
                continue

            if rule.last_fired is not None and (now - rule.last_fired) < rule.cooldown_seconds:
                logger.debug(
                    "Trigger %s (%s) skipped — cooldown active (%.0fs remaining)",
                    rule.rule_id,
                    rule.name,
                    rule.cooldown_seconds - (now - rule.last_fired),
                )
                continue

            firing = self._fire_rule(rule, event_dict, now)
            firings.append(firing)

        return firings

    def _fire_rule(
        self, rule: TriggerRule, event_dict: Dict[str, Any], now: float
    ) -> TriggerFiring:
        """Execute a single trigger rule by firing its scheduler task.

        Args:
            rule: The matched rule.
            event_dict: Serialized anomaly event.
            now: Current unix timestamp.

        Returns:
            A ``TriggerFiring`` recording the outcome.
        """
        firing_id = f"fire-{uuid.uuid4().hex[:8]}"
        task_result: Optional[Dict[str, Any]] = None
        success = False
        error: Optional[str] = None

        try:
            from engine.nexus.scheduler_daemon import get_scheduler_daemon
            daemon = get_scheduler_daemon()

            if not hasattr(daemon, "_tasks") or rule.task_id not in daemon._tasks:
                error = f"Task {rule.task_id!r} not registered in scheduler"
                logger.warning(
                    "Trigger %s (%s) cannot fire — %s",
                    rule.rule_id, rule.name, error,
                )
            else:
                logger.info(
                    "Trigger %s (%s) firing task %s for anomaly: %s.%s severity=%s",
                    rule.rule_id,
                    rule.name,
                    rule.task_id,
                    event_dict.get("node", "?"),
                    event_dict.get("metric", "?"),
                    event_dict.get("severity", "?"),
                )
                task_result = daemon.run_task(rule.task_id)
                success = task_result.get("success", False)
                if not success:
                    error = task_result.get("error", "Unknown task error")

        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.error("Trigger %s task execution failed: %s", rule.rule_id, error)

        with self._lock:
            rule.last_fired = now
            rule.fire_count += 1

        self._persist_rule(rule)

        firing = TriggerFiring(
            firing_id=firing_id,
            rule_id=rule.rule_id,
            anomaly_event=event_dict,
            task_id=rule.task_id,
            task_result=task_result,
            fired_at=now,
            success=success,
            error=error,
        )
        self._persist_firing(firing)
        self._record_impact(rule, firing, event_dict)

        return firing

    def _record_impact(
        self,
        rule: TriggerRule,
        firing: TriggerFiring,
        event_dict: Dict[str, Any],
    ) -> None:
        """Record the triggered action in ImpactTracker if available.

        Args:
            rule: The rule that fired.
            firing: The firing record.
            event_dict: Serialized anomaly event.
        """
        try:
            from engine.nexus.impact_tracker import get_impact_tracker, ChangeType
            tracker = get_impact_tracker()
            status = "succeeded" if firing.success else "failed"
            tracker.record_change(
                ChangeType.SCHEDULER_CHANGE,
                f"Anomaly trigger {rule.name} → {rule.task_id} ({status})",
                (
                    f"Rule {rule.rule_id} fired task {rule.task_id} "
                    f"in response to anomaly on {event_dict.get('node', '?')}."
                    f"{event_dict.get('metric', '?')} "
                    f"(severity={event_dict.get('severity', '?')}). "
                    f"Fire count: {rule.fire_count}."
                ),
                source="anomaly_trigger",
            )
        except ImportError:
            logger.debug("ImpactTracker not available — skipping impact record")
        except Exception as exc:
            logger.debug("ImpactTracker recording failed: %s", exc)

    # ── Detector Wiring ─────────────────────────────────────────────

    def wire_detector(self) -> None:
        """Wire this trigger as the ``on_anomaly`` callback for AnomalyDetector.

        If the detector already has a callback, both callbacks are chained
        so existing behaviour is preserved.
        """
        try:
            from engine.observability.anomaly_detector import get_anomaly_detector
            detector = get_anomaly_detector()

            existing = getattr(detector, "_on_anomaly", None)
            trigger_ref = self

            def _chained_callback(event: Any) -> None:
                if existing is not None:
                    try:
                        existing(event)
                    except Exception:
                        logger.debug("Existing anomaly callback error", exc_info=True)
                trigger_ref.on_anomaly(event)

            detector._on_anomaly = _chained_callback
            logger.info("AnomalyTrigger wired to AnomalyDetector (chained=%s)", existing is not None)

        except ImportError:
            logger.warning("AnomalyDetector not available — wire_detector skipped")
        except Exception as exc:
            logger.warning("Failed to wire AnomalyDetector: %s", exc)

    # ── Query API ───────────────────────────────────────────────────

    def list_triggers(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """List all registered trigger rules.

        Args:
            enabled_only: If ``True``, return only enabled rules.

        Returns:
            List of rule dicts.
        """
        with self._lock:
            rules = list(self._rules.values())

        result: List[Dict[str, Any]] = []
        for rule in rules:
            if enabled_only and not rule.enabled:
                continue
            result.append({
                "rule_id": rule.rule_id,
                "name": rule.name,
                "pattern": rule.pattern.to_dict(),
                "task_id": rule.task_id,
                "cooldown_seconds": rule.cooldown_seconds,
                "min_severity": rule.min_severity,
                "enabled": rule.enabled,
                "created_at": rule.created_at,
                "last_fired": rule.last_fired,
                "fire_count": rule.fire_count,
                "metadata": rule.metadata,
            })
        return result

    def trigger_history(
        self,
        rule_id: Optional[str] = None,
        hours: float = 24.0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get trigger firing history.

        Args:
            rule_id: If provided, filter to this rule only.
            hours: Look-back window in hours.
            limit: Maximum number of records to return.

        Returns:
            List of firing record dicts, newest first.
        """
        try:
            conn = self._get_conn()
            cutoff = time.time() - (hours * 3600)
            conditions = ["fired_at >= ?"]
            params: List[Any] = [cutoff]

            if rule_id:
                conditions.append("rule_id = ?")
                params.append(rule_id)

            query = (
                f"SELECT * FROM trigger_firings "
                f"WHERE {' AND '.join(conditions)} "
                f"ORDER BY fired_at DESC LIMIT ?"
            )
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            results: List[Dict[str, Any]] = []
            for row in rows:
                results.append({
                    "firing_id": row["firing_id"],
                    "rule_id": row["rule_id"],
                    "anomaly_event": json.loads(row["anomaly_event"]) if row["anomaly_event"] else {},
                    "task_id": row["task_id"],
                    "task_result": json.loads(row["task_result"]) if row["task_result"] else None,
                    "fired_at": row["fired_at"],
                    "success": bool(row["success"]),
                    "error": row["error"],
                })
            return results

        except Exception as exc:
            logger.warning("Failed to query trigger history: %s", exc)
            return []

    def trigger_status(self) -> Dict[str, Any]:
        """Summary status of all triggers and recent activity.

        Returns:
            Dict with keys: ``total_rules``, ``enabled``, ``disabled``,
            ``total_firings_24h``, and ``rules`` list.
        """
        with self._lock:
            all_rules = list(self._rules.values())

        enabled_count = sum(1 for r in all_rules if r.enabled)
        disabled_count = len(all_rules) - enabled_count

        firings_24h = 0
        try:
            conn = self._get_conn()
            cutoff = time.time() - 86400
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM trigger_firings WHERE fired_at >= ?",
                (cutoff,),
            ).fetchone()
            firings_24h = row["cnt"] if row else 0
        except Exception as exc:
            logger.debug("Failed to count 24h firings: %s", exc)

        rules_summary: List[Dict[str, Any]] = []
        for rule in all_rules:
            rules_summary.append({
                "rule_id": rule.rule_id,
                "name": rule.name,
                "task_id": rule.task_id,
                "fire_count": rule.fire_count,
                "last_fired": rule.last_fired,
                "enabled": rule.enabled,
            })

        return {
            "total_rules": len(all_rules),
            "enabled": enabled_count,
            "disabled": disabled_count,
            "total_firings_24h": firings_24h,
            "rules": rules_summary,
        }

    # ── Built-in Triggers ───────────────────────────────────────────

    def _register_builtin_triggers(self) -> None:
        """Register built-in trigger rules.

        Six default rules are registered on first initialization.  If a rule
        with the same name already exists in the in-memory cache (loaded from
        DB), it is skipped to avoid duplicates.
        """
        existing_names = {r.name for r in self._rules.values()}

        builtins: List[Dict[str, Any]] = [
            {
                "name": "cpu-spike-snapshot",
                "pattern": TriggerPattern(node_prefix="system", metric_contains="cpu"),
                "task_id": "metrics-collect",
                "cooldown_seconds": 120.0,
                "min_severity": "high",
                "metadata": {"builtin": True, "description": "Collect metrics snapshot on CPU spike"},
            },
            {
                "name": "memory-leak-backup",
                "pattern": TriggerPattern(node_prefix="system", metric_contains="ram"),
                "task_id": "backup-databases",
                "cooldown_seconds": 600.0,
                "min_severity": "high",
                "metadata": {"builtin": True, "description": "Backup databases on RAM anomaly"},
            },
            {
                "name": "accuracy-drop-investigate",
                "pattern": TriggerPattern(metric_contains="accuracy"),
                "task_id": "knowledge-quality",
                "cooldown_seconds": 3600.0,
                "min_severity": "medium",
                "metadata": {"builtin": True, "description": "Run knowledge quality check on accuracy drop"},
            },
            {
                "name": "nexus-failure-repair",
                "pattern": TriggerPattern(node_prefix="nexus", metric_contains="error"),
                "task_id": "nexus-dedup",
                "cooldown_seconds": 1800.0,
                "min_severity": "high",
                "metadata": {"builtin": True, "description": "Run Nexus dedup on error anomaly"},
            },
            {
                "name": "skill-error-audit",
                "pattern": TriggerPattern(metric_contains="error_rate"),
                "task_id": "system-reflection",
                "cooldown_seconds": 3600.0,
                "min_severity": "high",
                "metadata": {"builtin": True, "description": "System reflection on skill error spike"},
            },
            {
                "name": "gpu-overload-alert",
                "pattern": TriggerPattern(node_prefix="gpu", metric_contains="vram"),
                "task_id": "metrics-collect",
                "cooldown_seconds": 60.0,
                "min_severity": "critical",
                "metadata": {"builtin": True, "description": "Immediate metrics collect on GPU VRAM overload"},
            },
        ]

        # Supplementary patterns for rules with OR semantics.
        # "accuracy-drop-investigate" also matches "quality".
        # "skill-error-audit" also matches "failure".
        # We register a second rule for the alternative pattern.
        or_variants: List[Dict[str, Any]] = [
            {
                "name": "accuracy-drop-investigate-quality",
                "pattern": TriggerPattern(metric_contains="quality"),
                "task_id": "knowledge-quality",
                "cooldown_seconds": 3600.0,
                "min_severity": "medium",
                "metadata": {
                    "builtin": True,
                    "description": "Run knowledge quality check on quality metric drop",
                    "variant_of": "accuracy-drop-investigate",
                },
            },
            {
                "name": "skill-error-audit-failure",
                "pattern": TriggerPattern(metric_contains="failure"),
                "task_id": "system-reflection",
                "cooldown_seconds": 3600.0,
                "min_severity": "high",
                "metadata": {
                    "builtin": True,
                    "description": "System reflection on skill failure spike",
                    "variant_of": "skill-error-audit",
                },
            },
        ]

        all_builtins = builtins + or_variants
        registered = 0

        for spec in all_builtins:
            if spec["name"] in existing_names:
                continue
            self.register_trigger(
                name=spec["name"],
                pattern=spec["pattern"],
                task_id=spec["task_id"],
                cooldown_seconds=spec["cooldown_seconds"],
                min_severity=spec["min_severity"],
                enabled=True,
                metadata=spec.get("metadata"),
            )
            registered += 1

        if registered:
            logger.info("Registered %d built-in trigger rules", registered)


# ── Scheduler Task Callback (Polling Mode) ──────────────────────────────


def _anomaly_trigger_check_callback() -> Dict[str, Any]:
    """Poll for recent anomalies and feed them through trigger rules.

    This is a backup integration path for cases where the callback-based
    wiring (``wire_detector()``) is not active.  It reads the last 20
    anomalies from the detector and processes any that occurred within the
    last 5 minutes.

    Returns:
        Dict with ``checked`` and ``fired`` counts, or ``error`` on failure.
    """
    trigger = get_anomaly_trigger()
    try:
        from engine.observability.anomaly_detector import (
            AnomalyDetector,
            AnomalyEvent,
            AnomalyMethod,
            AnomalySeverity,
            get_anomaly_detector,
        )

        detector = get_anomaly_detector()
        recent = detector.recent_anomalies(n=20)

        now = time.time()
        fired_total = 0
        checked = 0

        for anomaly_dict in recent:
            ts = anomaly_dict.get("ts", anomaly_dict.get("timestamp", 0))
            if now - ts > 300:
                continue
            checked += 1

            event = _reconstruct_event(anomaly_dict)
            if event is None:
                continue

            firings = trigger.on_anomaly(event)
            fired_total += len(firings)

        return {"checked": checked, "fired": fired_total}

    except ImportError:
        return {"error": "AnomalyDetector not available"}
    except Exception as exc:
        logger.warning("Anomaly trigger check failed: %s", exc)
        return {"error": str(exc)}


def _reconstruct_event(data: Dict[str, Any]) -> Any:
    """Reconstruct an ``AnomalyEvent`` from a dict returned by ``recent_anomalies()``.

    The detector's ``recent_anomalies()`` returns dicts with keys that differ
    slightly from the dataclass fields (e.g. ``ts`` vs ``timestamp``,
    ``method``/``severity`` as strings vs enums).

    Args:
        data: Dict from ``AnomalyDetector.recent_anomalies()``.

    Returns:
        An ``AnomalyEvent`` instance, or ``None`` on failure.
    """
    try:
        from engine.observability.anomaly_detector import (
            AnomalyEvent,
            AnomalyMethod,
            AnomalySeverity,
        )

        method_str = data.get("method", "zscore")
        try:
            method = AnomalyMethod(method_str)
        except (ValueError, KeyError):
            method = AnomalyMethod.ZSCORE

        severity_str = data.get("severity", "medium")
        try:
            severity = AnomalySeverity(severity_str)
        except (ValueError, KeyError):
            severity = AnomalySeverity.MEDIUM

        return AnomalyEvent(
            node=data.get("node", "unknown"),
            metric=data.get("metric", "unknown"),
            value=float(data.get("value", 0)),
            expected_mean=float(data.get("expected_mean", 0)),
            deviation=float(data.get("deviation", 0)),
            method=method,
            severity=severity,
            timestamp=float(data.get("ts", data.get("timestamp", 0))),
            z_score=float(data.get("z_score", 0)),
            iqr_factor=float(data.get("iqr_factor", 0)),
            mad_score=float(data.get("mad_score", 0)),
            baseline_window=int(data.get("baseline_window", 0)),
            message=data.get("message", ""),
        )
    except Exception as exc:
        logger.debug("Failed to reconstruct AnomalyEvent: %s", exc)
        return None


def register_anomaly_trigger_tasks(daemon: Any) -> None:
    """Register the anomaly trigger polling task with a scheduler daemon.

    Args:
        daemon: A ``TaskSchedulerDaemon`` instance.
    """
    daemon.register(
        task_id="anomaly-trigger-check",
        name="Anomaly Trigger Check (5m)",
        schedule="every_5m",
        callback=_anomaly_trigger_check_callback,
        enabled=True,
    )
    logger.info("Registered anomaly-trigger-check polling task")


# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional[AnomalyTrigger] = None
_lock = threading.Lock()


def get_anomaly_trigger(db_path: Optional[Path] = None) -> AnomalyTrigger:
    """Get or create the singleton ``AnomalyTrigger``.

    Args:
        db_path: Optional custom database path.  Only used on first creation.

    Returns:
        The singleton ``AnomalyTrigger`` instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AnomalyTrigger(db_path)
    return _instance
