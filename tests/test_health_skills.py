"""Tests for engine/skills/builtin/health_skills.py.

Covers all 10 health skills:
1.  get_system_health
2.  check_service_health
3.  get_health_history
4.  get_health_alerts
5.  register_service
6.  discover_services
7.  deregister_service
8.  heartbeat_service
9.  export_prometheus_metrics
10. get_service_capabilities

All HealthChecker and ServiceRegistry interactions are mocked.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.observability.health_checker import HealthStatus, ServiceHealth, SystemHealthReport
from engine.observability.service_registry import (
    DiscoveryResult,
    ServiceRecord,
    ServiceType,
)
from engine.skills.builtin.health_skills import (
    check_service_health,
    deregister_service,
    discover_services,
    export_prometheus_metrics,
    get_health_alerts,
    get_health_history,
    get_service_capabilities,
    get_system_health,
    heartbeat_service,
    register_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service_health(
    name: str = "test",
    status: HealthStatus = HealthStatus.HEALTHY,
    latency: float = 5.0,
    message: str = "ok",
    details: dict | None = None,
) -> ServiceHealth:
    return ServiceHealth(
        service_name=name,
        status=status,
        latency_ms=latency,
        message=message,
        checked_at=datetime.now(),
        details=details or {},
    )


def _make_report(
    overall: HealthStatus = HealthStatus.HEALTHY,
    score: float = 1.0,
    services: dict | None = None,
    alerts: list | None = None,
) -> SystemHealthReport:
    return SystemHealthReport(
        timestamp=datetime.now(),
        overall=overall,
        services=services or {"svc": _make_service_health()},
        score=score,
        alerts=alerts or [],
    )


def _make_service_record(
    service_id: str = "svc-001",
    name: str = "test_service",
    service_type: ServiceType = ServiceType.TOOL,
    host: str = "localhost",
    port: int = 9000,
    capabilities: list | None = None,
    tags: list | None = None,
    status: str = "active",
) -> ServiceRecord:
    now = datetime.now()
    return ServiceRecord(
        service_id=service_id,
        name=name,
        service_type=service_type,
        host=host,
        port=port,
        health_url="",
        metadata={},
        registered_at=now,
        last_seen=now,
        status=status,
        tags=tags or [],
        capabilities=capabilities or [],
    )


# ---------------------------------------------------------------------------
# 1. get_system_health
# ---------------------------------------------------------------------------


def test_get_system_health_returns_string() -> None:
    mock_checker = MagicMock()
    mock_checker.check_all.return_value = _make_report()
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = get_system_health()
    assert isinstance(result, str)


def test_get_system_health_contains_score() -> None:
    mock_checker = MagicMock()
    mock_checker.check_all.return_value = _make_report(score=0.85)
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = get_system_health()
    assert "0.85" in result


def test_get_system_health_contains_overall_status() -> None:
    mock_checker = MagicMock()
    mock_checker.check_all.return_value = _make_report(overall=HealthStatus.DEGRADED, score=0.7)
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = get_system_health()
    assert "DEGRADED" in result


def test_get_system_health_shows_alerts() -> None:
    mock_checker = MagicMock()
    report = _make_report(
        overall=HealthStatus.UNHEALTHY,
        score=0.2,
        alerts=["UNHEALTHY: nexus — connection refused"],
    )
    mock_checker.check_all.return_value = report
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = get_system_health()
    assert "nexus" in result
    assert "Alerts" in result or "UNHEALTHY" in result


def test_get_system_health_shows_per_service() -> None:
    mock_checker = MagicMock()
    services = {
        "lmstudio": _make_service_health("lmstudio", HealthStatus.HEALTHY),
        "nexus": _make_service_health("nexus", HealthStatus.DEGRADED),
    }
    report = _make_report(score=0.75, services=services)
    mock_checker.check_all.return_value = report
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = get_system_health()
    assert "lmstudio" in result
    assert "nexus" in result


# ---------------------------------------------------------------------------
# 2. check_service_health
# ---------------------------------------------------------------------------


def test_check_service_health_healthy(tmp_path: Path) -> None:
    mock_checker = MagicMock()
    mock_checker.check_service.return_value = _make_service_health(
        "lmstudio", HealthStatus.HEALTHY, message="2 models loaded"
    )
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = check_service_health("lmstudio")
    assert "lmstudio" in result
    assert "HEALTHY" in result


def test_check_service_health_unhealthy() -> None:
    mock_checker = MagicMock()
    mock_checker.check_service.return_value = _make_service_health(
        "nexus", HealthStatus.UNHEALTHY, message="connection refused"
    )
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = check_service_health("nexus")
    assert "UNHEALTHY" in result


def test_check_service_health_unknown_service() -> None:
    mock_checker = MagicMock()
    mock_checker.check_service.side_effect = KeyError("no_such_service")
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = check_service_health("no_such_service")
    assert "Unknown" in result or "no_such_service" in result


def test_check_service_health_includes_latency() -> None:
    mock_checker = MagicMock()
    mock_checker.check_service.return_value = _make_service_health(latency=42.5)
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = check_service_health("test")
    assert "42" in result


def test_check_service_health_includes_details() -> None:
    mock_checker = MagicMock()
    mock_checker.check_service.return_value = _make_service_health(
        details={"model_count": 3}
    )
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = check_service_health("test")
    assert "model_count" in result or "3" in result


# ---------------------------------------------------------------------------
# 3. get_health_history
# ---------------------------------------------------------------------------


def test_get_health_history_no_data() -> None:
    mock_checker = MagicMock()
    mock_checker.get_history.return_value = []
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = get_health_history(hours=24)
    assert "No health history" in result


def test_get_health_history_with_data() -> None:
    mock_checker = MagicMock()
    mock_checker.get_history.return_value = [
        {
            "timestamp": "2026-01-01T12:00:00",
            "overall_status": "healthy",
            "score": 1.0,
            "services": {},
            "alerts": [],
        }
    ]
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = get_health_history(hours=24)
    assert "healthy" in result.lower()
    assert "1 record" in result or "records" in result


def test_get_health_history_passes_hours_param() -> None:
    mock_checker = MagicMock()
    mock_checker.get_history.return_value = []
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        get_health_history(hours=48)
    mock_checker.get_history.assert_called_once_with(hours=48)


def test_get_health_history_shows_scores() -> None:
    mock_checker = MagicMock()
    mock_checker.get_history.return_value = [
        {
            "timestamp": "2026-01-01T12:00:00",
            "overall_status": "degraded",
            "score": 0.72,
            "services": {},
            "alerts": [],
        }
    ]
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = get_health_history()
    assert "0.72" in result


# ---------------------------------------------------------------------------
# 4. get_health_alerts
# ---------------------------------------------------------------------------


def test_get_health_alerts_none() -> None:
    mock_checker = MagicMock()
    mock_checker.get_alerts.return_value = []
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = get_health_alerts(hours=1)
    assert "No health alerts" in result


def test_get_health_alerts_with_alerts() -> None:
    mock_checker = MagicMock()
    mock_checker.get_alerts.return_value = [
        {
            "timestamp": "2026-01-01T12:00:00",
            "overall_status": "unhealthy",
            "score": 0.1,
            "alerts": ["UNHEALTHY: nexus — timeout"],
        }
    ]
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        result = get_health_alerts(hours=1)
    assert "nexus" in result or "UNHEALTHY" in result


def test_get_health_alerts_passes_hours() -> None:
    mock_checker = MagicMock()
    mock_checker.get_alerts.return_value = []
    with patch("engine.observability.health_checker.get_health_checker", return_value=mock_checker):
        get_health_alerts(hours=6)
    mock_checker.get_alerts.assert_called_once_with(hours=6)


# ---------------------------------------------------------------------------
# 5. register_service
# ---------------------------------------------------------------------------


def test_register_service_success() -> None:
    mock_registry = MagicMock()
    mock_registry.register.return_value = "user-svc-abc123"
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = register_service(
            name="my_api",
            service_type="tool",
            host="localhost",
            port=8080,
            capabilities_json='["read", "write"]',
        )
    assert "my_api" in result
    assert "Registered" in result or "✅" in result


def test_register_service_invalid_type() -> None:
    result = register_service(
        name="svc", service_type="invalid_type", host="localhost", port=8080
    )
    assert "Invalid" in result or "invalid_type" in result


def test_register_service_invalid_capabilities_json() -> None:
    result = register_service(
        name="svc",
        service_type="tool",
        host="localhost",
        port=8080,
        capabilities_json="not-json",
    )
    assert "Invalid" in result or "capabilities" in result


def test_register_service_calls_registry(tmp_path: Path) -> None:
    mock_registry = MagicMock()
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        register_service("my_svc", "llm", "localhost", 1234, '["inference"]')
    assert mock_registry.register.called
    record = mock_registry.register.call_args[0][0]
    assert record.name == "my_svc"
    assert record.service_type == ServiceType.LLM
    assert "inference" in record.capabilities


def test_register_service_default_capabilities() -> None:
    mock_registry = MagicMock()
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = register_service("empty_svc", "agent", "localhost", 0)
    assert "Registered" in result or "✅" in result
    record = mock_registry.register.call_args[0][0]
    assert record.capabilities == []


# ---------------------------------------------------------------------------
# 6. discover_services
# ---------------------------------------------------------------------------


def test_discover_services_no_filter() -> None:
    mock_registry = MagicMock()
    mock_registry.discover.return_value = DiscoveryResult(
        services=[_make_service_record()],
        total=1,
        filtered_by={},
    )
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = discover_services()
    assert "1 service" in result or "Discovered" in result


def test_discover_services_empty_result() -> None:
    mock_registry = MagicMock()
    mock_registry.discover.return_value = DiscoveryResult(services=[], total=0, filtered_by={})
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = discover_services()
    assert "No services" in result


def test_discover_services_by_type() -> None:
    mock_registry = MagicMock()
    mock_registry.discover.return_value = DiscoveryResult(
        services=[_make_service_record(service_type=ServiceType.LLM)],
        total=1,
        filtered_by={"service_type": "llm"},
    )
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = discover_services(service_type="llm")
    assert "llm" in result.lower()


def test_discover_services_invalid_type() -> None:
    result = discover_services(service_type="invalid_xyz")
    assert "Invalid" in result or "invalid_xyz" in result


def test_discover_services_by_capability() -> None:
    mock_registry = MagicMock()
    mock_registry.discover.return_value = DiscoveryResult(
        services=[_make_service_record(capabilities=["vision"])],
        total=1,
        filtered_by={"capabilities": ["vision"]},
    )
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = discover_services(capability="vision")
    assert "vision" in result


# ---------------------------------------------------------------------------
# 7. deregister_service
# ---------------------------------------------------------------------------


def test_deregister_service_success() -> None:
    mock_registry = MagicMock()
    mock_registry.deregister.return_value = True
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = deregister_service("svc-001")
    assert "✅" in result or "Deregistered" in result


def test_deregister_service_not_found() -> None:
    mock_registry = MagicMock()
    mock_registry.deregister.return_value = False
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = deregister_service("ghost-svc")
    assert "not found" in result.lower() or "❌" in result


def test_deregister_service_calls_registry() -> None:
    mock_registry = MagicMock()
    mock_registry.deregister.return_value = True
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        deregister_service("target-id")
    mock_registry.deregister.assert_called_once_with("target-id")


# ---------------------------------------------------------------------------
# 8. heartbeat_service
# ---------------------------------------------------------------------------


def test_heartbeat_service_success() -> None:
    mock_registry = MagicMock()
    mock_registry.heartbeat.return_value = True
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = heartbeat_service("svc-001")
    assert "💓" in result or "Heartbeat" in result


def test_heartbeat_service_not_found() -> None:
    mock_registry = MagicMock()
    mock_registry.heartbeat.return_value = False
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = heartbeat_service("ghost")
    assert "not found" in result.lower() or "❌" in result


def test_heartbeat_service_calls_registry() -> None:
    mock_registry = MagicMock()
    mock_registry.heartbeat.return_value = True
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        heartbeat_service("my-id")
    mock_registry.heartbeat.assert_called_once_with("my-id")


# ---------------------------------------------------------------------------
# 9. export_prometheus_metrics
# ---------------------------------------------------------------------------


def test_export_prometheus_metrics_returns_string() -> None:
    mock_checker = MagicMock()
    mock_checker.get_last_report.return_value = _make_report()
    mock_checker.export_prometheus.return_value = "cosysim_health_score 1.0\n"
    with patch(
        "engine.observability.health_checker.get_health_checker", return_value=mock_checker
    ):
        result = export_prometheus_metrics()
    assert isinstance(result, str)
    assert "cosysim" in result


def test_export_prometheus_metrics_triggers_check_all_if_no_report() -> None:
    mock_checker = MagicMock()
    mock_checker.get_last_report.return_value = None
    mock_checker.export_prometheus.return_value = "# metrics\n"
    with patch(
        "engine.observability.health_checker.get_health_checker", return_value=mock_checker
    ):
        export_prometheus_metrics()
    mock_checker.check_all.assert_called_once()


def test_export_prometheus_metrics_no_check_all_if_report_exists() -> None:
    mock_checker = MagicMock()
    mock_checker.get_last_report.return_value = _make_report()
    mock_checker.export_prometheus.return_value = "# metrics\n"
    with patch(
        "engine.observability.health_checker.get_health_checker", return_value=mock_checker
    ):
        export_prometheus_metrics()
    mock_checker.check_all.assert_not_called()


# ---------------------------------------------------------------------------
# 10. get_service_capabilities
# ---------------------------------------------------------------------------


def test_get_service_capabilities_found() -> None:
    mock_registry = MagicMock()
    mock_registry.get.return_value = _make_service_record(
        service_id="cap-001",
        capabilities=["render", "stream"],
        tags=["gpu"],
    )
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = get_service_capabilities("cap-001")
    assert "render" in result
    assert "stream" in result


def test_get_service_capabilities_not_found() -> None:
    mock_registry = MagicMock()
    mock_registry.get.return_value = None
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = get_service_capabilities("ghost-id")
    assert "not found" in result.lower() or "❌" in result


def test_get_service_capabilities_shows_host_port() -> None:
    mock_registry = MagicMock()
    mock_registry.get.return_value = _make_service_record(host="10.0.0.1", port=8765)
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = get_service_capabilities("any-id")
    assert "10.0.0.1" in result
    assert "8765" in result


def test_get_service_capabilities_shows_status() -> None:
    mock_registry = MagicMock()
    mock_registry.get.return_value = _make_service_record(status="unknown")
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        result = get_service_capabilities("any-id")
    assert "unknown" in result.lower()


def test_get_service_capabilities_calls_registry_get() -> None:
    mock_registry = MagicMock()
    mock_registry.get.return_value = None
    with patch(
        "engine.observability.service_registry.get_service_registry",
        return_value=mock_registry,
    ):
        get_service_capabilities("lookup-id")
    mock_registry.get.assert_called_once_with("lookup-id")
