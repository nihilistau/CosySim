"""Tests for engine.observability.anomaly_trigger.

Covers TriggerPattern matching, TriggerRule lifecycle, anomaly event
processing with cooldown/severity filtering, firing history, status
reporting, detector wiring, scheduler task registration, and the
module-level singleton.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from engine.observability.anomaly_trigger import (
    AnomalyTrigger,
    TriggerFiring,
    TriggerPattern,
    TriggerRule,
    register_anomaly_trigger_tasks,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_event(
    node: str = "system.cpu",
    metric: str = "cpu_pct",
    severity: str = "high",
) -> SimpleNamespace:
    """Build a minimal anomaly-event-like object."""
    return SimpleNamespace(
        node=node,
        metric=metric,
        severity=severity,
        to_dict=lambda: {"node": node, "metric": metric, "severity": severity},
    )


@pytest.fixture()
def trigger(tmp_path: Path) -> AnomalyTrigger:
    """Create an AnomalyTrigger backed by a temp database."""
    db = tmp_path / "test_triggers.db"
    with patch("engine.observability.anomaly_trigger._instance", None):
        t = AnomalyTrigger(db_path=db)
    return t


@pytest.fixture()
def bare_trigger(tmp_path: Path) -> AnomalyTrigger:
    """AnomalyTrigger with built-in triggers removed for isolated tests."""
    db = tmp_path / "bare_triggers.db"
    with patch("engine.observability.anomaly_trigger._instance", None):
        t = AnomalyTrigger(db_path=db)
    for rule_id in list(t._rules):
        t.remove_trigger(rule_id)
    return t


# ── Initialization ──────────────────────────────────────────────────────


class TestInitialization:
    """Database and schema bootstrap behaviour."""

    def test_creates_database(self, tmp_path: Path) -> None:
        """Database file is created on disk when AnomalyTrigger initialises."""
        db = tmp_path / "init.db"
        with patch("engine.observability.anomaly_trigger._instance", None):
            AnomalyTrigger(db_path=db)
        assert db.exists()

    def test_wal_mode(self, trigger: AnomalyTrigger) -> None:
        """SQLite connection uses WAL journal mode for concurrency."""
        conn = trigger._get_conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_tables_created(self, trigger: AnomalyTrigger) -> None:
        """Both trigger_rules and trigger_firings tables exist."""
        conn = trigger._get_conn()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "trigger_rules" in tables
        assert "trigger_firings" in tables

    def test_builtin_triggers_registered(self, trigger: AnomalyTrigger) -> None:
        """Eight built-in trigger rules are registered on init."""
        builtin_names = {r.name for r in trigger._rules.values()}
        expected = {
            "cpu-spike-snapshot",
            "memory-leak-backup",
            "accuracy-drop-investigate",
            "nexus-failure-repair",
            "skill-error-audit",
            "gpu-overload-alert",
            "accuracy-drop-investigate-quality",
            "skill-error-audit-failure",
        }
        assert expected.issubset(builtin_names)
        assert len(builtin_names) >= 8


# ── TriggerPattern ──────────────────────────────────────────────────────


class TestTriggerPattern:
    """Pattern matching logic for anomaly events."""

    def test_pattern_matches_exact_node(self) -> None:
        """Exact node match succeeds when event.node equals pattern.node."""
        pattern = TriggerPattern(node="gpu_primary")
        assert pattern.matches(_make_event(node="gpu_primary"))
        assert not pattern.matches(_make_event(node="gpu_secondary"))

    def test_pattern_matches_exact_metric(self) -> None:
        """Exact metric match succeeds when event.metric equals pattern.metric."""
        pattern = TriggerPattern(metric="cpu_pct")
        assert pattern.matches(_make_event(metric="cpu_pct"))
        assert not pattern.matches(_make_event(metric="ram_pct"))

    def test_pattern_matches_node_prefix(self) -> None:
        """Prefix match succeeds when event.node starts with pattern.node_prefix."""
        pattern = TriggerPattern(node_prefix="gpu")
        assert pattern.matches(_make_event(node="gpu_primary"))
        assert pattern.matches(_make_event(node="gpu"))
        assert not pattern.matches(_make_event(node="system.cpu"))

    def test_pattern_matches_metric_contains(self) -> None:
        """Substring match succeeds when pattern.metric_contains is in event.metric."""
        pattern = TriggerPattern(metric_contains="cpu")
        assert pattern.matches(_make_event(metric="cpu_pct"))
        assert pattern.matches(_make_event(metric="total_cpu_usage"))
        assert not pattern.matches(_make_event(metric="ram_pct"))

    def test_pattern_no_match(self) -> None:
        """Pattern with multiple constraints fails when any constraint misses."""
        pattern = TriggerPattern(node="system.cpu", metric_contains="ram")
        event = _make_event(node="system.cpu", metric="cpu_pct")
        assert not pattern.matches(event)

    def test_pattern_to_dict_from_dict(self) -> None:
        """Round-trip through to_dict/from_dict preserves all fields."""
        original = TriggerPattern(
            node="gpu_primary",
            metric="vram_pct",
            node_prefix="gpu",
            metric_contains="vram",
        )
        rebuilt = TriggerPattern.from_dict(original.to_dict())
        assert rebuilt.node == original.node
        assert rebuilt.metric == original.metric
        assert rebuilt.node_prefix == original.node_prefix
        assert rebuilt.metric_contains == original.metric_contains


# ── Rule Management ─────────────────────────────────────────────────────


class TestRuleManagement:
    """CRUD operations for trigger rules."""

    def test_register_trigger_creates_rule(
        self, bare_trigger: AnomalyTrigger
    ) -> None:
        """register_trigger returns a TriggerRule and persists it."""
        rule = bare_trigger.register_trigger(
            name="test-rule",
            pattern=TriggerPattern(node="x"),
            task_id="task-1",
            cooldown_seconds=60,
            min_severity="low",
        )
        assert isinstance(rule, TriggerRule)
        assert rule.rule_id.startswith("trig-")
        assert rule.name == "test-rule"
        assert rule.task_id == "task-1"
        assert rule.enabled is True
        assert rule.rule_id in bare_trigger._rules

    def test_remove_trigger_success(self, bare_trigger: AnomalyTrigger) -> None:
        """remove_trigger returns True and evicts the rule from the cache."""
        rule = bare_trigger.register_trigger(
            name="removable",
            pattern=TriggerPattern(),
            task_id="t",
        )
        assert bare_trigger.remove_trigger(rule.rule_id) is True
        assert rule.rule_id not in bare_trigger._rules

    def test_remove_trigger_nonexistent(
        self, bare_trigger: AnomalyTrigger
    ) -> None:
        """remove_trigger returns False for an unknown rule_id."""
        assert bare_trigger.remove_trigger("trig-nonexistent") is False

    def test_enable_disable_trigger(
        self, bare_trigger: AnomalyTrigger
    ) -> None:
        """enable/disable toggle the rule's enabled flag and persist it."""
        rule = bare_trigger.register_trigger(
            name="toggle",
            pattern=TriggerPattern(),
            task_id="t",
        )
        assert bare_trigger.disable_trigger(rule.rule_id) is True
        assert bare_trigger._rules[rule.rule_id].enabled is False

        assert bare_trigger.enable_trigger(rule.rule_id) is True
        assert bare_trigger._rules[rule.rule_id].enabled is True

    def test_list_triggers_all_vs_enabled(
        self, bare_trigger: AnomalyTrigger
    ) -> None:
        """list_triggers respects the enabled_only filter."""
        r1 = bare_trigger.register_trigger(
            name="enabled-rule",
            pattern=TriggerPattern(),
            task_id="t",
            enabled=True,
        )
        r2 = bare_trigger.register_trigger(
            name="disabled-rule",
            pattern=TriggerPattern(),
            task_id="t",
            enabled=True,
        )
        bare_trigger.disable_trigger(r2.rule_id)

        all_rules = bare_trigger.list_triggers(enabled_only=False)
        enabled_rules = bare_trigger.list_triggers(enabled_only=True)

        assert len(all_rules) == 2
        assert len(enabled_rules) == 1
        assert enabled_rules[0]["rule_id"] == r1.rule_id


# ── Event Processing ────────────────────────────────────────────────────


class TestEventProcessing:
    """on_anomaly firing logic including severity and cooldown."""

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_on_anomaly_fires_matching_rule(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """A matching rule fires the scheduler task and returns a TriggerFiring."""
        daemon = MagicMock()
        daemon._tasks = {"task-1": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        bare_trigger.register_trigger(
            name="fire-me",
            pattern=TriggerPattern(node="system.cpu"),
            task_id="task-1",
            cooldown_seconds=0,
            min_severity="low",
        )
        event = _make_event(node="system.cpu", severity="high")
        firings = bare_trigger.on_anomaly(event)

        assert len(firings) == 1
        assert firings[0].success is True
        assert firings[0].task_id == "task-1"
        daemon.run_task.assert_called_once_with("task-1")

    def test_on_anomaly_no_match(self, bare_trigger: AnomalyTrigger) -> None:
        """No firings when no rules match the event."""
        bare_trigger.register_trigger(
            name="nomatch",
            pattern=TriggerPattern(node="does.not.exist"),
            task_id="t",
        )
        event = _make_event(node="other.node")
        firings = bare_trigger.on_anomaly(event)
        assert firings == []

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_on_anomaly_cooldown_blocks(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """A rule within its cooldown window does not fire again."""
        daemon = MagicMock()
        daemon._tasks = {"t": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        rule = bare_trigger.register_trigger(
            name="cooldown-test",
            pattern=TriggerPattern(),
            task_id="t",
            cooldown_seconds=9999,
            min_severity="low",
        )
        event = _make_event(severity="high")

        first = bare_trigger.on_anomaly(event)
        assert len(first) == 1

        second = bare_trigger.on_anomaly(event)
        assert len(second) == 0

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_on_anomaly_cooldown_expired(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """A rule fires again after its cooldown window expires."""
        daemon = MagicMock()
        daemon._tasks = {"t": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        rule = bare_trigger.register_trigger(
            name="cooldown-expire",
            pattern=TriggerPattern(),
            task_id="t",
            cooldown_seconds=1,
            min_severity="low",
        )
        event = _make_event(severity="high")

        bare_trigger.on_anomaly(event)
        # Manually expire cooldown
        rule.last_fired = time.time() - 10
        bare_trigger._persist_rule(rule)

        second = bare_trigger.on_anomaly(event)
        assert len(second) == 1

    def test_on_anomaly_disabled_rule_skipped(
        self, bare_trigger: AnomalyTrigger
    ) -> None:
        """Disabled rules are excluded from event processing."""
        rule = bare_trigger.register_trigger(
            name="disabled",
            pattern=TriggerPattern(),
            task_id="t",
            min_severity="low",
        )
        bare_trigger.disable_trigger(rule.rule_id)
        event = _make_event(severity="high")
        firings = bare_trigger.on_anomaly(event)
        assert firings == []

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_on_anomaly_multiple_rules_match(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """Multiple matching rules each produce a firing."""
        daemon = MagicMock()
        daemon._tasks = {"t1": True, "t2": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        bare_trigger.register_trigger(
            name="r1",
            pattern=TriggerPattern(node_prefix="sys"),
            task_id="t1",
            cooldown_seconds=0,
            min_severity="low",
        )
        bare_trigger.register_trigger(
            name="r2",
            pattern=TriggerPattern(metric_contains="cpu"),
            task_id="t2",
            cooldown_seconds=0,
            min_severity="low",
        )
        event = _make_event(node="system", metric="cpu_pct", severity="high")
        firings = bare_trigger.on_anomaly(event)
        assert len(firings) == 2
        task_ids = {f.task_id for f in firings}
        assert task_ids == {"t1", "t2"}

    def test_on_anomaly_min_severity_filter(
        self, bare_trigger: AnomalyTrigger
    ) -> None:
        """Events below the rule's min_severity are ignored."""
        bare_trigger.register_trigger(
            name="high-only",
            pattern=TriggerPattern(),
            task_id="t",
            cooldown_seconds=0,
            min_severity="critical",
        )
        low_event = _make_event(severity="low")
        medium_event = _make_event(severity="medium")
        high_event = _make_event(severity="high")

        assert bare_trigger.on_anomaly(low_event) == []
        assert bare_trigger.on_anomaly(medium_event) == []
        assert bare_trigger.on_anomaly(high_event) == []


# ── Firing History ──────────────────────────────────────────────────────


class TestFiringHistory:
    """Querying persisted trigger_firings records."""

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_trigger_history_records_firings(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """Firings are persisted and retrievable via trigger_history."""
        daemon = MagicMock()
        daemon._tasks = {"t": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        bare_trigger.register_trigger(
            name="hist",
            pattern=TriggerPattern(),
            task_id="t",
            cooldown_seconds=0,
            min_severity="low",
        )
        bare_trigger.on_anomaly(_make_event(severity="high"))

        history = bare_trigger.trigger_history(hours=1)
        assert len(history) >= 1
        assert history[0]["task_id"] == "t"
        assert history[0]["success"] is True

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_trigger_history_by_rule_id(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """trigger_history filters by rule_id when provided."""
        daemon = MagicMock()
        daemon._tasks = {"t1": True, "t2": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        r1 = bare_trigger.register_trigger(
            name="h1",
            pattern=TriggerPattern(node="a"),
            task_id="t1",
            cooldown_seconds=0,
            min_severity="low",
        )
        r2 = bare_trigger.register_trigger(
            name="h2",
            pattern=TriggerPattern(node="b"),
            task_id="t2",
            cooldown_seconds=0,
            min_severity="low",
        )

        bare_trigger.on_anomaly(_make_event(node="a", severity="high"))
        bare_trigger.on_anomaly(_make_event(node="b", severity="high"))

        filtered = bare_trigger.trigger_history(rule_id=r1.rule_id, hours=1)
        assert all(f["rule_id"] == r1.rule_id for f in filtered)

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_trigger_history_time_filter(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """trigger_history respects the hours lookback window."""
        daemon = MagicMock()
        daemon._tasks = {"t": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        bare_trigger.register_trigger(
            name="time-filter",
            pattern=TriggerPattern(),
            task_id="t",
            cooldown_seconds=0,
            min_severity="low",
        )
        bare_trigger.on_anomaly(_make_event(severity="high"))

        # Insert an artificially old firing directly in the DB
        conn = bare_trigger._get_conn()
        old_ts = time.time() - 7200  # 2 hours ago
        conn.execute(
            "INSERT INTO trigger_firings "
            "(firing_id, rule_id, anomaly_event, task_id, fired_at, success) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("fire-old", "trig-fake", "{}", "t", old_ts, 1),
        )
        conn.commit()

        recent = bare_trigger.trigger_history(hours=1)
        old_ids = [r["firing_id"] for r in recent if r["firing_id"] == "fire-old"]
        assert old_ids == [], "Old firing should be excluded by the 1-hour window"


# ── Status ──────────────────────────────────────────────────────────────


class TestTriggerStatus:
    """trigger_status summary reporting."""

    def test_trigger_status_overview(self, trigger: AnomalyTrigger) -> None:
        """trigger_status returns correct counts for built-in rules."""
        status = trigger.trigger_status()
        assert "total_rules" in status
        assert "enabled" in status
        assert "disabled" in status
        assert "total_firings_24h" in status
        assert "rules" in status
        assert status["total_rules"] >= 8
        assert status["enabled"] >= 8

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_trigger_status_with_firings(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """total_firings_24h reflects recent firings."""
        daemon = MagicMock()
        daemon._tasks = {"t": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        bare_trigger.register_trigger(
            name="status-fire",
            pattern=TriggerPattern(),
            task_id="t",
            cooldown_seconds=0,
            min_severity="low",
        )
        bare_trigger.on_anomaly(_make_event(severity="high"))

        status = bare_trigger.trigger_status()
        assert status["total_firings_24h"] >= 1


# ── Integration ─────────────────────────────────────────────────────────


class TestIntegration:
    """Module-level helpers: scheduler registration, singleton, wiring."""

    def test_register_anomaly_trigger_tasks(self) -> None:
        """register_anomaly_trigger_tasks calls daemon.register with correct args."""
        daemon = MagicMock()
        register_anomaly_trigger_tasks(daemon)

        daemon.register.assert_called_once()
        call_kwargs = daemon.register.call_args
        # Works with both positional and keyword args
        if call_kwargs.kwargs:
            assert call_kwargs.kwargs["task_id"] == "anomaly-trigger-check"
            assert call_kwargs.kwargs["schedule"] == "every_5m"
            assert call_kwargs.kwargs["enabled"] is True
        else:
            assert call_kwargs[1]["task_id"] == "anomaly-trigger-check"

    def test_singleton_pattern(self, tmp_path: Path) -> None:
        """get_anomaly_trigger returns the same instance on repeated calls."""
        import engine.observability.anomaly_trigger as mod

        db = tmp_path / "singleton.db"
        original = mod._instance
        try:
            mod._instance = None
            first = mod.get_anomaly_trigger(db_path=db)
            second = mod.get_anomaly_trigger(db_path=db)
            assert first is second
        finally:
            mod._instance = original

    @patch("engine.observability.anomaly_detector.get_anomaly_detector")
    def test_wire_detector(
        self, mock_detector_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """wire_detector sets the detector's _on_anomaly callback."""
        detector = MagicMock()
        detector._on_anomaly = None
        mock_detector_fn.return_value = detector

        bare_trigger.wire_detector()

        assert detector._on_anomaly is not None
        assert callable(detector._on_anomaly)


# ── Edge Cases ──────────────────────────────────────────────────────────


class TestEdgeCases:
    """Boundary conditions and concurrency."""

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_concurrent_anomalies(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """on_anomaly is thread-safe under concurrent calls."""
        daemon = MagicMock()
        daemon._tasks = {"t": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        bare_trigger.register_trigger(
            name="concurrent",
            pattern=TriggerPattern(),
            task_id="t",
            cooldown_seconds=0,
            min_severity="low",
        )

        results: List[List[TriggerFiring]] = []
        errors: List[Exception] = []

        def fire() -> None:
            try:
                r = bare_trigger.on_anomaly(_make_event(severity="high"))
                results.append(r)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=fire) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Threads raised errors: {errors}"
        # At least the first thread should fire; others may be blocked by
        # the cooldown that _fire_rule sets.
        total_firings = sum(len(r) for r in results)
        assert total_firings >= 1

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_rapid_fire_cooldown(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """Rapid sequential on_anomaly calls respect cooldown after the first fire."""
        daemon = MagicMock()
        daemon._tasks = {"t": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        bare_trigger.register_trigger(
            name="rapid",
            pattern=TriggerPattern(),
            task_id="t",
            cooldown_seconds=600,
            min_severity="low",
        )

        fired_count = 0
        for _ in range(10):
            firings = bare_trigger.on_anomaly(_make_event(severity="high"))
            fired_count += len(firings)

        assert fired_count == 1, "Only the first call should fire; rest are within cooldown"

    def test_empty_pattern_matches_all(self) -> None:
        """A TriggerPattern with all None fields matches any event."""
        pattern = TriggerPattern()
        assert pattern.matches(_make_event(node="anything", metric="whatever"))
        assert pattern.matches(_make_event(node="x", metric="y"))


# ── Additional Coverage ─────────────────────────────────────────────────


class TestSeverityHandling:
    """Severity comparison and enum/string coercion."""

    def test_severity_enum_accepted(
        self, bare_trigger: AnomalyTrigger
    ) -> None:
        """register_trigger accepts an enum-like object for min_severity."""
        severity_enum = SimpleNamespace(value="high")
        rule = bare_trigger.register_trigger(
            name="enum-sev",
            pattern=TriggerPattern(),
            task_id="t",
            min_severity=severity_enum,
        )
        assert rule.min_severity == "high"

    def test_severity_string_normalised(
        self, bare_trigger: AnomalyTrigger
    ) -> None:
        """register_trigger lower-cases string severity inputs."""
        rule = bare_trigger.register_trigger(
            name="str-sev",
            pattern=TriggerPattern(),
            task_id="t",
            min_severity="HIGH",
        )
        assert rule.min_severity == "high"

    def test_severity_none_defaults_medium(
        self, bare_trigger: AnomalyTrigger
    ) -> None:
        """register_trigger defaults to 'medium' when min_severity is None."""
        rule = bare_trigger.register_trigger(
            name="def-sev",
            pattern=TriggerPattern(),
            task_id="t",
        )
        assert rule.min_severity == "medium"


class TestPersistence:
    """Database round-trip correctness."""

    def test_rule_survives_reload(self, tmp_path: Path) -> None:
        """A registered rule persists in the DB and loads into a new instance."""
        db = tmp_path / "persist.db"
        with patch("engine.observability.anomaly_trigger._instance", None):
            t1 = AnomalyTrigger(db_path=db)
        rule = t1.register_trigger(
            name="persist-me",
            pattern=TriggerPattern(node="x", metric_contains="y"),
            task_id="task-persist",
            cooldown_seconds=42,
            min_severity="high",
            metadata={"key": "val"},
        )

        # Create a fresh instance pointing at the same DB
        with patch("engine.observability.anomaly_trigger._instance", None):
            t2 = AnomalyTrigger(db_path=db)

        reloaded_names = {r.name for r in t2._rules.values()}
        assert "persist-me" in reloaded_names

        reloaded = next(r for r in t2._rules.values() if r.name == "persist-me")
        assert reloaded.pattern.node == "x"
        assert reloaded.pattern.metric_contains == "y"
        assert reloaded.cooldown_seconds == 42
        assert reloaded.min_severity == "high"
        assert reloaded.metadata == {"key": "val"}

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_firing_persisted_in_db(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """TriggerFiring records are written to the trigger_firings table."""
        daemon = MagicMock()
        daemon._tasks = {"t": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        bare_trigger.register_trigger(
            name="persist-firing",
            pattern=TriggerPattern(),
            task_id="t",
            cooldown_seconds=0,
            min_severity="low",
        )
        bare_trigger.on_anomaly(_make_event(severity="high"))

        conn = bare_trigger._get_conn()
        rows = conn.execute("SELECT * FROM trigger_firings").fetchall()
        assert len(rows) >= 1
        assert rows[0]["task_id"] == "t"
        assert bool(rows[0]["success"]) is True


class TestWireDetectorChaining:
    """Detector callback chaining behaviour."""

    @patch("engine.observability.anomaly_detector.get_anomaly_detector")
    def test_wire_detector_chains_existing_callback(
        self, mock_detector_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """wire_detector preserves an existing _on_anomaly callback."""
        detector = MagicMock()
        existing_calls: list = []
        detector._on_anomaly = lambda evt: existing_calls.append(evt)
        mock_detector_fn.return_value = detector

        bare_trigger.wire_detector()

        # Invoke the chained callback
        test_event = _make_event()
        detector._on_anomaly(test_event)

        assert len(existing_calls) == 1
        assert existing_calls[0] is test_event

    @patch("engine.observability.anomaly_detector.get_anomaly_detector")
    def test_wire_detector_import_error_handled(
        self, mock_detector_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """wire_detector handles ImportError without raising."""
        mock_detector_fn.side_effect = ImportError("no module")
        # Should not raise
        bare_trigger.wire_detector()


class TestFireRuleErrors:
    """Error paths inside _fire_rule."""

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_fire_rule_task_not_registered(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """Firing records an error when the task_id is not in the daemon."""
        daemon = MagicMock()
        daemon._tasks = {}  # No tasks registered
        mock_daemon_fn.return_value = daemon

        bare_trigger.register_trigger(
            name="missing-task",
            pattern=TriggerPattern(),
            task_id="nonexistent-task",
            cooldown_seconds=0,
            min_severity="low",
        )
        firings = bare_trigger.on_anomaly(_make_event(severity="high"))

        assert len(firings) == 1
        assert firings[0].success is False
        assert "not registered" in (firings[0].error or "")

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_fire_rule_daemon_exception(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """Firing captures exceptions from daemon.run_task."""
        daemon = MagicMock()
        daemon._tasks = {"t": True}
        daemon.run_task.side_effect = RuntimeError("boom")
        mock_daemon_fn.return_value = daemon

        bare_trigger.register_trigger(
            name="boom-rule",
            pattern=TriggerPattern(),
            task_id="t",
            cooldown_seconds=0,
            min_severity="low",
        )
        firings = bare_trigger.on_anomaly(_make_event(severity="high"))

        assert len(firings) == 1
        assert firings[0].success is False
        assert "RuntimeError" in (firings[0].error or "")

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_fire_count_increments(
        self, mock_daemon_fn: MagicMock, bare_trigger: AnomalyTrigger
    ) -> None:
        """Each firing increments the rule's fire_count."""
        daemon = MagicMock()
        daemon._tasks = {"t": True}
        daemon.run_task.return_value = {"success": True}
        mock_daemon_fn.return_value = daemon

        rule = bare_trigger.register_trigger(
            name="counter",
            pattern=TriggerPattern(),
            task_id="t",
            cooldown_seconds=0,
            min_severity="low",
        )
        assert rule.fire_count == 0

        bare_trigger.on_anomaly(_make_event(severity="high"))
        assert bare_trigger._rules[rule.rule_id].fire_count == 1
