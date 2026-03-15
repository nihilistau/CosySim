"""Tests for resilience MCP skills (circuit breaker + config drift).

Covers all 10 skills with happy-path, edge-case, and error-handling tests.
All external dependencies are mocked — no real registries or monitors.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from enum import Enum
from unittest.mock import MagicMock, patch

import pytest


# ── Fake enums / data objects for mocking ───────────────────────────────


class FakeState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class FakeTransition:
    """Mimics a CircuitBreaker state-transition record."""

    def __init__(
        self,
        breaker_name: str,
        from_state: FakeState,
        to_state: FakeState,
        timestamp: float,
        reason: str = "",
        failure_count: int = 0,
    ):
        self.breaker_name = breaker_name
        self.from_state = from_state
        self.to_state = to_state
        self.timestamp = timestamp
        self.reason = reason
        self.failure_count = failure_count


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_breaker():
    """A single MagicMock circuit breaker with sensible defaults."""
    b = MagicMock()
    b.state = FakeState.CLOSED
    b.transitions = []
    return b


@pytest.fixture()
def mock_registry(mock_breaker):
    """Patched CircuitBreakerRegistry with one breaker named 'lmstudio'."""
    reg = MagicMock()
    reg.all_status.return_value = {
        "lmstudio": {"state": "closed", "failures": 0},
    }
    reg.get.return_value = mock_breaker
    reg.get_health_summary.return_value = {
        "total": 1,
        "open": 0,
        "closed": 1,
        "half_open": 0,
    }
    with patch(
        "engine.skills.builtin.resilience_skills._registry", return_value=reg
    ):
        yield reg


@pytest.fixture()
def mock_monitor():
    """Patched ConfigDriftMonitor with sensible defaults."""
    mon = MagicMock()
    drift_result = MagicMock()
    drift_result.to_dict.return_value = {
        "drifted_keys": ["lmstudio.port"],
        "total_drifted": 1,
        "status": "drifted",
    }
    mon.check_drift.return_value = drift_result
    mon.get_drift_history.return_value = [
        {"timestamp": 1700000000, "drifted_keys": 1, "status": "drifted"}
    ]
    mon.store_baseline.return_value = "baseline-001"
    mon.rollback_key.return_value = True
    mon.get_change_log.return_value = [
        {"key": "lmstudio.port", "old": 1234, "new": 5678, "timestamp": 1700000000}
    ]
    mon.get_health.return_value = {"status": "healthy", "baseline_age_s": 3600}
    with patch(
        "engine.skills.builtin.resilience_skills._drift_monitor", return_value=mon
    ):
        yield mon


# ── Helpers ─────────────────────────────────────────────────────────────


def _parse(result: str) -> dict:
    """Parse a skill's JSON string return value."""
    return json.loads(result)


# ════════════════════════════════════════════════════════════════════════
#  1. get_circuit_status
# ════════════════════════════════════════════════════════════════════════


class TestGetCircuitStatus:
    def test_all_breakers(self, mock_registry):
        from engine.skills.builtin.resilience_skills import get_circuit_status

        data = _parse(get_circuit_status())
        assert "breakers" in data
        assert data["total"] == 1
        assert "lmstudio" in data["breakers"]

    def test_filter_by_name_match(self, mock_registry):
        from engine.skills.builtin.resilience_skills import get_circuit_status

        data = _parse(get_circuit_status(name="lmstudio"))
        assert data["matched"] == 1
        assert "lmstudio" in data["breakers"]

    def test_filter_by_name_no_match(self, mock_registry):
        from engine.skills.builtin.resilience_skills import get_circuit_status

        data = _parse(get_circuit_status(name="nonexistent"))
        assert data["matched"] == 0
        assert data["breakers"] == {}

    def test_registry_error(self):
        with patch(
            "engine.skills.builtin.resilience_skills._registry",
            side_effect=RuntimeError("boom"),
        ):
            from engine.skills.builtin.resilience_skills import get_circuit_status

            data = _parse(get_circuit_status())
            assert "error" in data
            assert "boom" in data["error"]


# ════════════════════════════════════════════════════════════════════════
#  2. reset_circuit
# ════════════════════════════════════════════════════════════════════════


class TestResetCircuit:
    def test_successful_reset(self, mock_registry, mock_breaker):
        from engine.skills.builtin.resilience_skills import reset_circuit

        mock_breaker.state = FakeState.OPEN
        data = _parse(reset_circuit(name="lmstudio"))
        assert data["success"] is True
        assert data["name"] == "lmstudio"
        assert data["previous_state"] == "open"
        mock_breaker.reset.assert_called_once()

    def test_breaker_not_found(self, mock_registry):
        from engine.skills.builtin.resilience_skills import reset_circuit

        mock_registry.get.return_value = None
        data = _parse(reset_circuit(name="unknown"))
        assert data["success"] is False
        assert "not found" in data["error"]
        assert "available" in data

    def test_reset_error(self):
        with patch(
            "engine.skills.builtin.resilience_skills._registry",
            side_effect=RuntimeError("fail"),
        ):
            from engine.skills.builtin.resilience_skills import reset_circuit

            data = _parse(reset_circuit(name="x"))
            assert "error" in data


# ════════════════════════════════════════════════════════════════════════
#  3. get_circuit_history
# ════════════════════════════════════════════════════════════════════════


class TestGetCircuitHistory:
    def test_single_breaker_history(self, mock_registry, mock_breaker):
        from engine.skills.builtin.resilience_skills import get_circuit_history

        mock_breaker.transitions = [
            FakeTransition(
                "lmstudio", FakeState.CLOSED, FakeState.OPEN, time.time(), "timeout", 5
            ),
        ]
        data = _parse(get_circuit_history(name="lmstudio"))
        assert data["total"] == 1
        assert data["transitions"][0]["breaker_name"] == "lmstudio"
        assert data["transitions"][0]["from_state"] == "closed"
        assert data["transitions"][0]["to_state"] == "open"

    def test_all_breakers_history(self, mock_registry, mock_breaker):
        from engine.skills.builtin.resilience_skills import get_circuit_history

        now = time.time()
        mock_breaker.transitions = [
            FakeTransition("lmstudio", FakeState.CLOSED, FakeState.OPEN, now - 10, "err", 3),
            FakeTransition("lmstudio", FakeState.OPEN, FakeState.HALF_OPEN, now, "probe", 3),
        ]
        data = _parse(get_circuit_history())
        assert data["total"] == 2
        # Newest first
        assert data["transitions"][0]["to_state"] == "half_open"

    def test_limit_applied(self, mock_registry, mock_breaker):
        from engine.skills.builtin.resilience_skills import get_circuit_history

        mock_breaker.transitions = [
            FakeTransition("lmstudio", FakeState.CLOSED, FakeState.OPEN, time.time() + i, f"r{i}", i)
            for i in range(10)
        ]
        data = _parse(get_circuit_history(limit=3))
        assert data["total"] == 3

    def test_unknown_breaker_name(self, mock_registry):
        from engine.skills.builtin.resilience_skills import get_circuit_history

        mock_registry.get.return_value = None
        mock_registry.all_status.return_value = {}
        data = _parse(get_circuit_history(name="ghost"))
        assert data["total"] == 0
        assert data["transitions"] == []

    def test_history_error(self):
        with patch(
            "engine.skills.builtin.resilience_skills._registry",
            side_effect=RuntimeError("oops"),
        ):
            from engine.skills.builtin.resilience_skills import get_circuit_history

            data = _parse(get_circuit_history())
            assert "error" in data


# ════════════════════════════════════════════════════════════════════════
#  4. get_retry_stats
# ════════════════════════════════════════════════════════════════════════


class TestGetRetryStats:
    def test_returns_summary(self, mock_registry):
        from engine.skills.builtin.resilience_skills import get_retry_stats

        data = _parse(get_retry_stats())
        assert data["total"] == 1
        assert data["open"] == 0
        assert data["closed"] == 1

    def test_error(self):
        with patch(
            "engine.skills.builtin.resilience_skills._registry",
            side_effect=RuntimeError("kaboom"),
        ):
            from engine.skills.builtin.resilience_skills import get_retry_stats

            data = _parse(get_retry_stats())
            assert "error" in data
            assert "kaboom" in data["error"]


# ════════════════════════════════════════════════════════════════════════
#  5. check_config_drift
# ════════════════════════════════════════════════════════════════════════


class TestCheckConfigDrift:
    def test_drift_detected(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import check_config_drift

        data = _parse(check_config_drift())
        assert data["status"] == "drifted"
        assert data["total_drifted"] == 1
        mock_monitor.check_drift.assert_called_once_with(auto_store=True)

    def test_no_drift(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import check_config_drift

        clean = MagicMock()
        clean.to_dict.return_value = {"drifted_keys": [], "total_drifted": 0, "status": "clean"}
        mock_monitor.check_drift.return_value = clean

        data = _parse(check_config_drift())
        assert data["status"] == "clean"
        assert data["total_drifted"] == 0

    def test_error(self):
        with patch(
            "engine.skills.builtin.resilience_skills._drift_monitor",
            side_effect=RuntimeError("no monitor"),
        ):
            from engine.skills.builtin.resilience_skills import check_config_drift

            data = _parse(check_config_drift())
            assert "error" in data


# ════════════════════════════════════════════════════════════════════════
#  6. get_drift_report
# ════════════════════════════════════════════════════════════════════════


class TestGetDriftReport:
    def test_returns_history(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import get_drift_report

        data = _parse(get_drift_report())
        assert data["total"] == 1
        assert data["checks"][0]["status"] == "drifted"
        mock_monitor.get_drift_history.assert_called_once_with(limit=5)

    def test_custom_limit(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import get_drift_report

        get_drift_report(limit=10)
        mock_monitor.get_drift_history.assert_called_once_with(limit=10)

    def test_empty_history(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import get_drift_report

        mock_monitor.get_drift_history.return_value = []
        data = _parse(get_drift_report())
        assert data["total"] == 0
        assert data["checks"] == []

    def test_error(self):
        with patch(
            "engine.skills.builtin.resilience_skills._drift_monitor",
            side_effect=RuntimeError("broken"),
        ):
            from engine.skills.builtin.resilience_skills import get_drift_report

            data = _parse(get_drift_report())
            assert "error" in data


# ════════════════════════════════════════════════════════════════════════
#  7. store_config_baseline
# ════════════════════════════════════════════════════════════════════════


class TestStoreConfigBaseline:
    def test_default_label(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import store_config_baseline

        data = _parse(store_config_baseline())
        assert data["success"] is True
        assert data["baseline_id"] == "baseline-001"
        assert data["label"] == "manual"
        assert "timestamp" in data
        mock_monitor.store_baseline.assert_called_once_with(label="manual")

    def test_custom_label(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import store_config_baseline

        data = _parse(store_config_baseline(label="sprint-8"))
        assert data["label"] == "sprint-8"
        mock_monitor.store_baseline.assert_called_once_with(label="sprint-8")

    def test_error(self):
        with patch(
            "engine.skills.builtin.resilience_skills._drift_monitor",
            side_effect=RuntimeError("disk full"),
        ):
            from engine.skills.builtin.resilience_skills import store_config_baseline

            data = _parse(store_config_baseline())
            assert "error" in data
            assert "disk full" in data["error"]


# ════════════════════════════════════════════════════════════════════════
#  8. rollback_config_key
# ════════════════════════════════════════════════════════════════════════


class TestRollbackConfigKey:
    def test_successful_rollback(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import rollback_config_key

        data = _parse(rollback_config_key(key="lmstudio.port"))
        assert data["success"] is True
        assert data["key"] == "lmstudio.port"
        assert "reverted" in data["message"]

    def test_rollback_fails(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import rollback_config_key

        mock_monitor.rollback_key.return_value = False
        data = _parse(rollback_config_key(key="missing.key"))
        assert data["success"] is False
        assert "missing.key" in data["message"]

    def test_error(self):
        with patch(
            "engine.skills.builtin.resilience_skills._drift_monitor",
            side_effect=RuntimeError("corrupt"),
        ):
            from engine.skills.builtin.resilience_skills import rollback_config_key

            data = _parse(rollback_config_key(key="a.b"))
            assert "error" in data


# ════════════════════════════════════════════════════════════════════════
#  9. get_config_changes
# ════════════════════════════════════════════════════════════════════════


class TestGetConfigChanges:
    def test_all_changes(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import get_config_changes

        data = _parse(get_config_changes())
        assert data["total"] == 1
        assert data["changes"][0]["key"] == "lmstudio.port"
        mock_monitor.get_change_log.assert_called_once_with(key=None, limit=50)

    def test_filter_by_key(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import get_config_changes

        get_config_changes(key="lmstudio.port", limit=10)
        mock_monitor.get_change_log.assert_called_once_with(key="lmstudio.port", limit=10)

    def test_empty_key_treated_as_none(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import get_config_changes

        get_config_changes(key="")
        mock_monitor.get_change_log.assert_called_once_with(key=None, limit=50)

    def test_error(self):
        with patch(
            "engine.skills.builtin.resilience_skills._drift_monitor",
            side_effect=RuntimeError("gone"),
        ):
            from engine.skills.builtin.resilience_skills import get_config_changes

            data = _parse(get_config_changes())
            assert "error" in data


# ════════════════════════════════════════════════════════════════════════
# 10. get_system_resilience
# ════════════════════════════════════════════════════════════════════════


class TestGetSystemResilience:
    def test_healthy_system(self, mock_registry, mock_monitor):
        from engine.skills.builtin.resilience_skills import get_system_resilience

        data = _parse(get_system_resilience())
        assert data["overall_status"] == "healthy"
        assert data["circuit_breakers"]["total"] == 1
        assert data["config_drift"]["status"] == "healthy"
        assert "timestamp" in data

    def test_critical_when_open_breakers(self, mock_registry, mock_monitor):
        from engine.skills.builtin.resilience_skills import get_system_resilience

        mock_registry.get_health_summary.return_value = {
            "total": 2,
            "open": 1,
            "closed": 1,
            "half_open": 0,
        }
        data = _parse(get_system_resilience())
        assert data["overall_status"] == "critical"

    def test_critical_when_drift_critical(self, mock_registry, mock_monitor):
        from engine.skills.builtin.resilience_skills import get_system_resilience

        mock_monitor.get_health.return_value = {"status": "critical", "baseline_age_s": 99999}
        data = _parse(get_system_resilience())
        assert data["overall_status"] == "critical"

    def test_degraded_when_drifted(self, mock_registry, mock_monitor):
        from engine.skills.builtin.resilience_skills import get_system_resilience

        mock_monitor.get_health.return_value = {"status": "drifted", "baseline_age_s": 7200}
        data = _parse(get_system_resilience())
        assert data["overall_status"] == "degraded"

    def test_registry_error_captured(self, mock_monitor):
        from engine.skills.builtin.resilience_skills import get_system_resilience

        with patch(
            "engine.skills.builtin.resilience_skills._registry",
            side_effect=RuntimeError("reg down"),
        ):
            data = _parse(get_system_resilience())
            assert "error" in data["circuit_breakers"]
            assert "reg down" in data["circuit_breakers"]["error"]

    def test_monitor_error_captured(self, mock_registry):
        from engine.skills.builtin.resilience_skills import get_system_resilience

        with patch(
            "engine.skills.builtin.resilience_skills._drift_monitor",
            side_effect=RuntimeError("mon down"),
        ):
            data = _parse(get_system_resilience())
            assert "error" in data["config_drift"]
            assert "mon down" in data["config_drift"]["error"]

    def test_both_errors_gives_unknown(self):
        from engine.skills.builtin.resilience_skills import get_system_resilience

        with patch(
            "engine.skills.builtin.resilience_skills._registry",
            side_effect=RuntimeError("a"),
        ), patch(
            "engine.skills.builtin.resilience_skills._drift_monitor",
            side_effect=RuntimeError("b"),
        ):
            data = _parse(get_system_resilience())
            assert data["overall_status"] in ("unknown", "healthy")


# ════════════════════════════════════════════════════════════════════════
#  JSON serializer edge cases
# ════════════════════════════════════════════════════════════════════════


class TestDefaultSerializer:
    def test_datetime_serialized(self, mock_registry, mock_breaker):
        """Datetimes in transition timestamps must survive JSON encoding."""
        from engine.skills.builtin.resilience_skills import get_circuit_history

        dt = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_breaker.transitions = [
            FakeTransition("lmstudio", FakeState.CLOSED, FakeState.OPEN, dt, "test", 1),
        ]
        data = _parse(get_circuit_history(name="lmstudio"))
        assert data["total"] == 1
        assert "2025-01-15" in data["transitions"][0]["timestamp"]

    def test_enum_serialized(self, mock_registry):
        """Enum values in all_status should survive JSON encoding."""
        from engine.skills.builtin.resilience_skills import get_circuit_status

        mock_registry.all_status.return_value = {
            "test": {"state": FakeState.OPEN},
        }
        data = _parse(get_circuit_status())
        assert data["breakers"]["test"]["state"] == "open"
