"""Tests for engine.observability.alert_router."""
from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from engine.observability.alert_router import (
    AlertChannel,
    AlertRouter,
    RoutedAlert,
    RoutingRule,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def router(tmp_path):
    """Fresh in-memory AlertRouter with default rules."""
    import engine.observability.alert_router as mod
    mod._instance = None
    r = AlertRouter(db_path=str(tmp_path / "test.db"))
    yield r
    mod._instance = None


@dataclass
class FakeAlert:
    node: str = "gpu"
    level: str = "red"
    prev_level: str = "yellow"
    metric: str = "temperature"
    value: float = 92.0
    threshold: float = 85.0
    message: str = "GPU temp critical"
    ts: float = 0.0

    def __post_init__(self):
        if self.ts == 0.0:
            self.ts = time.time()


@dataclass
class FakeAnomalyEvent:
    node: str = "cpu"
    metric: str = "usage"
    value: float = 98.5
    expected_mean: float = 45.0
    deviation: float = 4.2
    severity: MagicMock = None
    message: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.severity is None:
            sev = MagicMock()
            sev.value = "high"
            self.severity = sev
        if self.timestamp == 0.0:
            self.timestamp = time.time()


# ── Singleton ───────────────────────────────────────────────────────────


def test_singleton_returns_same_instance(tmp_path):
    """get_alert_router returns the same singleton each time."""
    import engine.observability.alert_router as mod
    mod._instance = None
    try:
        from engine.observability.alert_router import get_alert_router
        r1 = get_alert_router(db_path=str(tmp_path / "s.db"))
        r2 = get_alert_router()
        assert r1 is r2
    finally:
        mod._instance = None


# ── route_alert ─────────────────────────────────────────────────────────


def test_route_alert_returns_routed_alert(router):
    """route_alert converts a FakeAlert into a RoutedAlert."""
    alert = FakeAlert()
    result = router.route_alert(alert)
    assert isinstance(result, RoutedAlert)
    assert result.source_type == "alert"
    assert result.node == "gpu"
    assert result.metric == "temperature"
    assert result.level == "red"
    assert result.severity == "HIGH"
    assert not result.suppressed


def test_route_alert_persists_to_db(router):
    """Routed alerts are written to the DB."""
    router.route_alert(FakeAlert())
    rows = router.recent_routed(10)
    assert len(rows) == 1
    assert rows[0]["node"] == "gpu"
    assert rows[0]["severity"] == "HIGH"


def test_route_alert_yellow_severity(router):
    """Yellow-level alerts map to MEDIUM severity."""
    result = router.route_alert(FakeAlert(level="yellow"))
    assert result.severity == "MEDIUM"


def test_route_alert_green_severity(router):
    """Green-level alerts map to LOW severity."""
    result = router.route_alert(FakeAlert(level="green"))
    assert result.severity == "LOW"


# ── route_anomaly ───────────────────────────────────────────────────────


def test_route_anomaly_returns_routed_alert(router):
    """route_anomaly converts a FakeAnomalyEvent into a RoutedAlert."""
    event = FakeAnomalyEvent()
    result = router.route_anomaly(event)
    assert isinstance(result, RoutedAlert)
    assert result.source_type == "anomaly"
    assert result.node == "cpu"
    assert result.severity == "HIGH"


def test_route_anomaly_generates_message(router):
    """Anomaly without message gets an auto-generated one."""
    event = FakeAnomalyEvent()
    result = router.route_anomaly(event)
    assert "Anomaly on cpu.usage" in result.message


# ── Rule management ─────────────────────────────────────────────────────


def test_add_rule_replaces_existing(router):
    """Adding a rule with the same name replaces the old one."""
    initial_count = len(router._rules)
    rule = RoutingRule(name="log_all_alerts", channel=AlertChannel.LOG, min_level="green")
    router.add_rule(rule)
    assert len(router._rules) == initial_count
    found = [r for r in router._rules if r.name == "log_all_alerts"]
    assert found[0].min_level == "green"


def test_remove_rule(router):
    """remove_rule removes a rule by name and returns True."""
    assert router.remove_rule("log_all_alerts")
    assert not any(r.name == "log_all_alerts" for r in router._rules)


def test_remove_nonexistent_rule_returns_false(router):
    """remove_rule returns False when no rule with that name exists."""
    assert not router.remove_rule("does_not_exist")


# ── Suppression ─────────────────────────────────────────────────────────


def test_suppress_blocks_alerts(router):
    """Suppressed node/metric combos are marked suppressed."""
    router.suppress("gpu", "temperature", duration_seconds=300)
    result = router.route_alert(FakeAlert())
    assert result.suppressed
    assert result.channels_routed == []


def test_unsuppress_re_enables(router):
    """unsuppress removes the suppression."""
    router.suppress("gpu", "temperature", 300)
    router.unsuppress("gpu", "temperature")
    result = router.route_alert(FakeAlert())
    assert not result.suppressed


def test_wildcard_suppression(router):
    """Wildcard *::metric suppresses all nodes for that metric."""
    router.suppress("*", "temperature", 300)
    result = router.route_alert(FakeAlert(node="gpu"))
    assert result.suppressed
    result2 = router.route_alert(FakeAlert(node="cpu"))
    assert result2.suppressed


# ── Custom handlers ─────────────────────────────────────────────────────


def test_custom_handler_invoked(router):
    """Registered custom handlers are called during dispatch."""
    handler = MagicMock()
    router.add_handler("test_handler", handler, min_severity="LOW")
    router.route_alert(FakeAlert(level="yellow"))
    handler.assert_called_once()
    arg = handler.call_args[0][0]
    assert isinstance(arg, RoutedAlert)


def test_custom_handler_min_severity(router):
    """Custom handler is skipped when severity is below its threshold."""
    handler = MagicMock()
    router.add_handler("strict", handler, min_severity="CRITICAL")
    router.route_alert(FakeAlert(level="yellow"))
    handler.assert_not_called()


def test_remove_handler(router):
    """remove_handler removes a handler and returns True."""
    handler = MagicMock()
    router.add_handler("removable", handler)
    assert router.remove_handler("removable")
    assert not router.remove_handler("removable")


def test_custom_handler_exception_does_not_crash(router):
    """Failing custom handlers are caught and don't crash routing."""
    router.add_handler("bad", lambda _: 1 / 0, min_severity="LOW")
    result = router.route_alert(FakeAlert(level="yellow"))
    assert isinstance(result, RoutedAlert)


# ── Cooldown ────────────────────────────────────────────────────────────


def test_cooldown_prevents_duplicate_routing(router):
    """Same rule+node+metric within cooldown window is skipped."""
    router._rules = [
        RoutingRule(name="fast", channel=AlertChannel.LOG, min_level="yellow",
                    min_severity="LOW", cooldown_seconds=9999),
    ]
    r1 = router.route_alert(FakeAlert(level="yellow"))
    r2 = router.route_alert(FakeAlert(level="yellow"))
    assert "log" in r1.channels_routed
    assert "log" not in r2.channels_routed


# ── Query API ───────────────────────────────────────────────────────────


def test_recent_routed(router):
    """recent_routed returns inserted records newest first."""
    router.route_alert(FakeAlert(metric="a"))
    router.route_alert(FakeAlert(metric="b"))
    rows = router.recent_routed(10)
    assert len(rows) >= 2
    assert rows[0]["metric"] == "b"


def test_routing_stats(router):
    """routing_stats returns valid aggregate data."""
    router.route_alert(FakeAlert())
    stats = router.routing_stats()
    assert stats["total_routed"] >= 1
    assert "per_severity" in stats


def test_acknowledge(router):
    """acknowledge marks a routing log entry."""
    router.route_alert(FakeAlert())
    rows = router.recent_routed(1)
    assert router.acknowledge(rows[0]["id"])
    refreshed = router.recent_routed(1)
    assert refreshed[0]["acknowledged"]


def test_acknowledge_nonexistent_returns_false(router):
    """acknowledge returns False for non-existent ID."""
    assert not router.acknowledge(99999)


def test_summary_structure(router):
    """summary returns expected keys."""
    s = router.summary()
    assert "rule_count" in s
    assert "custom_handlers" in s
    assert "active_suppressions" in s
    assert "stats" in s


# ── RoutedAlert serialization ───────────────────────────────────────────


def test_routed_alert_to_dict():
    """to_dict excludes the original field."""
    ra = RoutedAlert(
        source_type="alert", node="n", metric="m",
        level="red", severity="HIGH", message="msg",
        channels_routed=["log"], original=object(),
    )
    d = ra.to_dict()
    assert "original" not in d
    assert d["channels_routed"] == ["log"]


# ── Channel handlers (with mocks) ──────────────────────────────────────


def test_nexus_handler_called(router):
    """_handle_nexus calls Nexus client.add_entry."""
    ra = RoutedAlert(source_type="alert", node="n", metric="m",
                     level="red", severity="HIGH", message="msg")
    with patch("engine.observability.alert_router.get_alert_router") as _:
        mock_client = MagicMock()
        with patch(
            "engine.nexus.client.get_nexus_client", return_value=mock_client,
        ):
            result = router._handle_nexus(ra)
            assert result
            mock_client.add_entry.assert_called_once()


def test_operator_inbox_handler_called(router):
    """_handle_operator_inbox calls inbox.submit_item."""
    ra = RoutedAlert(source_type="alert", node="n", metric="m",
                     level="red", severity="HIGH", message="msg")
    mock_inbox = MagicMock()
    with patch(
        "engine.nexus.operator_inbox.get_operator_inbox",
        return_value=mock_inbox,
    ):
        result = router._handle_operator_inbox(ra)
        assert result
        mock_inbox.submit_item.assert_called_once()


# ── Escalation check ───────────────────────────────────────────────────


def test_escalation_check_finds_old_unacked(router):
    """Unacknowledged red alerts older than 5 min appear in escalation_check."""
    conn = router._get_db()
    old_ts = time.time() - 600
    conn.execute(
        "INSERT INTO alert_routing_log "
        "(source_type, node, metric, level, severity, message, channels, suppressed, acknowledged, ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("alert", "gpu", "temp", "red", "CRITICAL", "hot", "[]", 0, 0, old_ts),
    )
    conn.commit()
    escalated = router.escalation_check()
    assert len(escalated) >= 1
    assert escalated[0]["node"] == "gpu"
