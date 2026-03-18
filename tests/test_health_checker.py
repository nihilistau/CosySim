"""Tests for engine/observability/health_checker.py.

Covers:
- All 10 built-in service probes (HTTP, subprocess, import-based)
- check_all() concurrent execution
- Score calculation and status thresholds
- Optional service floor-clamping
- watch() background thread lifecycle
- stop_watch() termination
- get_history() SQLite query
- get_alerts() filtering
- register_probe() custom probes
- export_prometheus() format
- score_to_status() thresholds
- Singleton get_health_checker()
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from engine.observability.health_checker import (
    HealthChecker,
    HealthStatus,
    ServiceHealth,
    SystemHealthReport,
    get_health_checker,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def checker(tmp_path: Path) -> HealthChecker:
    """Fresh HealthChecker backed by a temp SQLite DB."""
    return HealthChecker(db_path=str(tmp_path / "health.db"))


def _make_health(name: str, status: HealthStatus, latency: float = 10.0) -> ServiceHealth:
    return ServiceHealth(
        service_name=name,
        status=status,
        latency_ms=latency,
        message=f"{name} is {status.value}",
        checked_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# HealthStatus enum
# ---------------------------------------------------------------------------


def test_health_status_values() -> None:
    assert HealthStatus.HEALTHY.value == "healthy"
    assert HealthStatus.DEGRADED.value == "degraded"
    assert HealthStatus.UNHEALTHY.value == "unhealthy"
    assert HealthStatus.UNKNOWN.value == "unknown"


# ---------------------------------------------------------------------------
# score_to_status
# ---------------------------------------------------------------------------


def test_score_to_status_healthy(checker: HealthChecker) -> None:
    assert checker.score_to_status(1.0) == HealthStatus.HEALTHY
    assert checker.score_to_status(0.9) == HealthStatus.HEALTHY


def test_score_to_status_degraded(checker: HealthChecker) -> None:
    assert checker.score_to_status(0.89) == HealthStatus.DEGRADED
    assert checker.score_to_status(0.6) == HealthStatus.DEGRADED


def test_score_to_status_unhealthy(checker: HealthChecker) -> None:
    assert checker.score_to_status(0.59) == HealthStatus.UNHEALTHY
    assert checker.score_to_status(0.0) == HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# _calculate_score
# ---------------------------------------------------------------------------


def test_calculate_score_all_healthy(checker: HealthChecker) -> None:
    services = {n: _make_health(n, HealthStatus.HEALTHY) for n in ["a", "b", "c"]}
    assert checker._calculate_score(services) == pytest.approx(1.0)


def test_calculate_score_all_unhealthy(checker: HealthChecker) -> None:
    services = {n: _make_health(n, HealthStatus.UNHEALTHY) for n in ["a", "b"]}
    assert checker._calculate_score(services) == pytest.approx(0.0)


def test_calculate_score_mixed(checker: HealthChecker) -> None:
    services = {
        "a": _make_health("a", HealthStatus.HEALTHY),   # 1.0
        "b": _make_health("b", HealthStatus.DEGRADED),  # 0.5
    }
    assert checker._calculate_score(services) == pytest.approx(0.75)


def test_calculate_score_empty(checker: HealthChecker) -> None:
    assert checker._calculate_score({}) == pytest.approx(1.0)


def test_calculate_score_optional_service_floor(checker: HealthChecker) -> None:
    """Optional services (comfyui, tts) should not reduce score below 0.5."""
    services = {
        "lmstudio": _make_health("lmstudio", HealthStatus.HEALTHY),      # 1.0
        "comfyui": _make_health("comfyui", HealthStatus.UNHEALTHY),      # clamped 0.5
        "tts": _make_health("tts", HealthStatus.UNHEALTHY),              # clamped 0.5
    }
    score = checker._calculate_score(services)
    assert score == pytest.approx((1.0 + 0.5 + 0.5) / 3)


def test_calculate_score_optional_unknown(checker: HealthChecker) -> None:
    """Optional services at UNKNOWN (0.3) are also clamped to 0.5."""
    services = {
        "nexus": _make_health("nexus", HealthStatus.HEALTHY),           # 1.0
        "comfyui": _make_health("comfyui", HealthStatus.UNKNOWN),       # clamped 0.5
    }
    score = checker._calculate_score(services)
    assert score == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# _build_alerts
# ---------------------------------------------------------------------------


def test_build_alerts_includes_unhealthy(checker: HealthChecker) -> None:
    services = {"bad": _make_health("bad", HealthStatus.UNHEALTHY)}
    alerts = checker._build_alerts(services)
    assert any("UNHEALTHY" in a and "bad" in a for a in alerts)


def test_build_alerts_includes_degraded(checker: HealthChecker) -> None:
    services = {"slow": _make_health("slow", HealthStatus.DEGRADED)}
    alerts = checker._build_alerts(services)
    assert any("DEGRADED" in a and "slow" in a for a in alerts)


def test_build_alerts_no_alert_for_healthy(checker: HealthChecker) -> None:
    services = {"ok": _make_health("ok", HealthStatus.HEALTHY)}
    assert checker._build_alerts(services) == []


# ---------------------------------------------------------------------------
# Probe: _check_lmstudio
# ---------------------------------------------------------------------------


def test_check_lmstudio_healthy(checker: HealthChecker) -> None:
    payload = json.dumps({"data": [{"id": "mistral"}, {"id": "llama"}]}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = payload
    with patch("urllib.request.urlopen", return_value=mock_resp):
        health = checker._check_lmstudio()
    assert health.status == HealthStatus.HEALTHY
    assert health.details["model_count"] == 2


def test_check_lmstudio_no_models(checker: HealthChecker) -> None:
    payload = json.dumps({"data": []}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = payload
    with patch("urllib.request.urlopen", return_value=mock_resp):
        health = checker._check_lmstudio()
    assert health.status == HealthStatus.DEGRADED


def test_check_lmstudio_connection_error(checker: HealthChecker) -> None:
    with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("refused")):
        health = checker._check_lmstudio()
    assert health.status == HealthStatus.UNHEALTHY
    assert health.service_name == "lmstudio"


# ---------------------------------------------------------------------------
# Probe: _check_nexus
# ---------------------------------------------------------------------------


def test_check_nexus_healthy(checker: HealthChecker) -> None:
    mock_client = MagicMock()
    mock_client.search.return_value = [{"id": 1}, {"id": 2}]
    with patch(
        "engine.observability.health_checker.HealthChecker._check_nexus",
        wraps=checker._check_nexus,
    ):
        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            health = checker._check_nexus()
    assert health.status == HealthStatus.HEALTHY
    assert health.details["result_count"] == 2


def test_check_nexus_import_error(checker: HealthChecker) -> None:
    with patch(
        "builtins.__import__",
        side_effect=lambda name, *a, **k: (_ for _ in ()).throw(ImportError("no module"))
        if "nexus" in name
        else __import__(name, *a, **k),
    ):
        health = checker._check_nexus()
    assert health.status == HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# Probe: _check_pm2
# ---------------------------------------------------------------------------


def test_check_pm2_healthy(checker: HealthChecker) -> None:
    processes = [
        {"pm2_env": {"status": "online"}},
        {"pm2_env": {"status": "online"}},
    ]
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps(processes)
    with patch("subprocess.run", return_value=mock_result):
        health = checker._check_pm2()
    assert health.status == HealthStatus.HEALTHY
    assert health.details["online"] == 2
    assert health.details["errored"] == 0


def test_check_pm2_errored_process(checker: HealthChecker) -> None:
    processes = [
        {"pm2_env": {"status": "online"}},
        {"pm2_env": {"status": "errored"}},
    ]
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps(processes)
    with patch("subprocess.run", return_value=mock_result):
        health = checker._check_pm2()
    assert health.status == HealthStatus.DEGRADED
    assert health.details["errored"] == 1


def test_check_pm2_not_found(checker: HealthChecker) -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("pm2 not found")):
        health = checker._check_pm2()
    assert health.status == HealthStatus.UNKNOWN
    assert "not found" in health.message


def test_check_pm2_nonzero_returncode(checker: HealthChecker) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "error"
    with patch("subprocess.run", return_value=mock_result):
        health = checker._check_pm2()
    assert health.status == HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# Probe: _check_comfyui (optional)
# ---------------------------------------------------------------------------


def test_check_comfyui_reachable(checker: HealthChecker) -> None:
    payload = json.dumps({"cuda": True}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = payload
    with patch("urllib.request.urlopen", return_value=mock_resp):
        health = checker._check_comfyui()
    assert health.status == HealthStatus.HEALTHY


def test_check_comfyui_unreachable(checker: HealthChecker) -> None:
    with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        health = checker._check_comfyui()
    assert health.status == HealthStatus.UNKNOWN
    assert "optional" in health.message.lower()


# ---------------------------------------------------------------------------
# Probe: _check_tts (optional)
# ---------------------------------------------------------------------------


def test_check_tts_reachable(checker: HealthChecker) -> None:
    payload = json.dumps({"status": "ok"}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = payload
    with patch("urllib.request.urlopen", return_value=mock_resp):
        health = checker._check_tts()
    assert health.status == HealthStatus.HEALTHY


def test_check_tts_unreachable(checker: HealthChecker) -> None:
    with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        health = checker._check_tts()
    assert health.status == HealthStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Probe: _check_secret_manager
# ---------------------------------------------------------------------------


def test_check_secret_manager_healthy(checker: HealthChecker) -> None:
    mock_sm = MagicMock()
    mock_sm.export_safe_report.return_value = {"secrets": 3}
    with patch(
        "engine.security.secret_manager.get_secret_manager", return_value=mock_sm
    ):
        health = checker._check_secret_manager()
    assert health.status == HealthStatus.HEALTHY
    assert health.details == {"secrets": 3}


def test_check_secret_manager_error(checker: HealthChecker) -> None:
    with patch(
        "engine.security.secret_manager.get_secret_manager",
        side_effect=RuntimeError("vault locked"),
    ):
        health = checker._check_secret_manager()
    assert health.status == HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# Probe: _check_rate_limiter
# ---------------------------------------------------------------------------


def test_check_rate_limiter_healthy(checker: HealthChecker) -> None:
    mock_rl = MagicMock()
    mock_rl.get_metrics.return_value = {"global": {"requests": 100}}
    with patch(
        "engine.security.rate_limiter.get_rate_limiter", return_value=mock_rl
    ):
        health = checker._check_rate_limiter()
    assert health.status == HealthStatus.HEALTHY


def test_check_rate_limiter_error(checker: HealthChecker) -> None:
    with patch(
        "engine.security.rate_limiter.get_rate_limiter",
        side_effect=RuntimeError("db error"),
    ):
        health = checker._check_rate_limiter()
    assert health.status == HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# Probe: _check_structured_logger
# ---------------------------------------------------------------------------


def test_check_structured_logger_healthy(checker: HealthChecker) -> None:
    mock_sl = MagicMock()
    mock_sl.get_error_summary.return_value = {"total_errors": 0}
    with patch(
        "engine.observability.structured_logger.get_structured_logger",
        return_value=mock_sl,
    ):
        health = checker._check_structured_logger()
    assert health.status == HealthStatus.HEALTHY
    mock_sl.get_error_summary.assert_called_once_with(hours=1)


def test_check_structured_logger_error(checker: HealthChecker) -> None:
    with patch(
        "engine.observability.structured_logger.get_structured_logger",
        side_effect=RuntimeError("db missing"),
    ):
        health = checker._check_structured_logger()
    assert health.status == HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# Probe: _check_integration_runner
# ---------------------------------------------------------------------------


def test_check_integration_runner_lmstudio_up(checker: HealthChecker) -> None:
    mock_ir = MagicMock()
    mock_ir.probe_service.return_value = True
    with patch(
        "engine.testing.integration_runner.get_integration_runner", return_value=mock_ir
    ):
        health = checker._check_integration_runner()
    assert health.status == HealthStatus.HEALTHY
    assert health.details["lmstudio_probe"] is True


def test_check_integration_runner_lmstudio_down(checker: HealthChecker) -> None:
    mock_ir = MagicMock()
    mock_ir.probe_service.return_value = False
    with patch(
        "engine.testing.integration_runner.get_integration_runner", return_value=mock_ir
    ):
        health = checker._check_integration_runner()
    assert health.status == HealthStatus.DEGRADED
    assert health.details["lmstudio_probe"] is False


def test_check_integration_runner_error(checker: HealthChecker) -> None:
    with patch(
        "engine.testing.integration_runner.get_integration_runner",
        side_effect=RuntimeError("runner unavailable"),
    ):
        health = checker._check_integration_runner()
    assert health.status == HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# Probe: _check_disk_space
# ---------------------------------------------------------------------------


def test_check_disk_space_healthy(checker: HealthChecker) -> None:
    mock_usage = MagicMock()
    mock_usage.free = 10 * 1024 ** 3  # 10 GB
    mock_usage.total = 100 * 1024 ** 3
    mock_usage.used = 90 * 1024 ** 3
    with patch("shutil.disk_usage", return_value=mock_usage):
        health = checker._check_disk_space()
    assert health.status == HealthStatus.HEALTHY
    assert "GB free" in health.message


def test_check_disk_space_degraded(checker: HealthChecker) -> None:
    mock_usage = MagicMock()
    mock_usage.free = 500 * 1024 ** 2  # 500 MB
    mock_usage.total = 10 * 1024 ** 3
    mock_usage.used = 10 * 1024 ** 3 - 500 * 1024 ** 2
    with patch("shutil.disk_usage", return_value=mock_usage):
        health = checker._check_disk_space()
    assert health.status == HealthStatus.DEGRADED
    assert "Warning" in health.message


def test_check_disk_space_critical(checker: HealthChecker) -> None:
    mock_usage = MagicMock()
    mock_usage.free = 50 * 1024 ** 2  # 50 MB
    mock_usage.total = 10 * 1024 ** 3
    mock_usage.used = 10 * 1024 ** 3 - 50 * 1024 ** 2
    with patch("shutil.disk_usage", return_value=mock_usage):
        health = checker._check_disk_space()
    assert health.status == HealthStatus.UNHEALTHY
    assert "Critical" in health.message


# ---------------------------------------------------------------------------
# check_all()
# ---------------------------------------------------------------------------


def test_check_all_returns_report(checker: HealthChecker) -> None:
    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "svc_a": lambda: _make_health("svc_a", HealthStatus.HEALTHY),
            "svc_b": lambda: _make_health("svc_b", HealthStatus.HEALTHY),
        }
        report = checker.check_all()
    assert isinstance(report, SystemHealthReport)
    assert "svc_a" in report.services
    assert "svc_b" in report.services
    assert report.score == pytest.approx(1.0)
    assert report.overall == HealthStatus.HEALTHY


def test_check_all_sequential(checker: HealthChecker) -> None:
    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "x": lambda: _make_health("x", HealthStatus.DEGRADED),
        }
        report = checker.check_all(parallel=False)
    assert report.services["x"].status == HealthStatus.DEGRADED


def test_check_all_caches_last_report(checker: HealthChecker) -> None:
    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "svc": lambda: _make_health("svc", HealthStatus.HEALTHY),
        }
        report = checker.check_all()
    assert checker.get_last_report() is report


def test_check_all_handles_probe_exception(checker: HealthChecker) -> None:
    def _bad_probe() -> ServiceHealth:
        raise RuntimeError("boom")

    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {"bad": _bad_probe}
        report = checker.check_all()
    assert report.services["bad"].status == HealthStatus.UNKNOWN


def test_check_all_concurrent_execution(checker: HealthChecker) -> None:
    """All probes should run concurrently within the timeout window."""
    order: list = []

    def slow_probe() -> ServiceHealth:
        order.append("start")
        time.sleep(0.05)
        order.append("end")
        return _make_health("slow", HealthStatus.HEALTHY)

    probes = {f"svc_{i}": slow_probe for i in range(5)}
    with patch.object(checker, "_all_probes", return_value=probes):
        t0 = time.monotonic()
        checker.check_all(parallel=True)
        elapsed = time.monotonic() - t0
    # 5 x 50ms sequentially = 250ms; concurrently should be ~50ms
    assert elapsed < 0.25, f"Probes ran too slowly: {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# check_service()
# ---------------------------------------------------------------------------


def test_check_service_known(checker: HealthChecker) -> None:
    with patch.object(
        checker, "_check_disk_space", return_value=_make_health("disk_space", HealthStatus.HEALTHY)
    ):
        health = checker.check_service("disk_space")
    assert health.service_name == "disk_space"


def test_check_service_unknown_raises(checker: HealthChecker) -> None:
    with pytest.raises(KeyError, match="no_such_service"):
        checker.check_service("no_such_service")


# ---------------------------------------------------------------------------
# register_probe()
# ---------------------------------------------------------------------------


def test_register_custom_probe(checker: HealthChecker) -> None:
    custom = _make_health("custom_svc", HealthStatus.HEALTHY)
    checker.register_probe("custom_svc", lambda: custom)
    assert "custom_svc" in checker._all_probes()


def test_register_probe_appears_in_check_all(checker: HealthChecker) -> None:
    custom = _make_health("my_custom", HealthStatus.DEGRADED)
    checker.register_probe("my_custom", lambda: custom)
    with patch.object(checker, "_check_lmstudio", return_value=_make_health("lmstudio", HealthStatus.HEALTHY)):
        with patch.object(checker, "_check_nexus", return_value=_make_health("nexus", HealthStatus.HEALTHY)):
            with patch.object(checker, "_check_pm2", return_value=_make_health("pm2", HealthStatus.HEALTHY)):
                with patch.object(checker, "_check_comfyui", return_value=_make_health("comfyui", HealthStatus.HEALTHY)):
                    with patch.object(checker, "_check_tts", return_value=_make_health("tts", HealthStatus.HEALTHY)):
                        with patch.object(checker, "_check_secret_manager", return_value=_make_health("secret_manager", HealthStatus.HEALTHY)):
                            with patch.object(checker, "_check_rate_limiter", return_value=_make_health("rate_limiter", HealthStatus.HEALTHY)):
                                with patch.object(checker, "_check_structured_logger", return_value=_make_health("structured_logger", HealthStatus.HEALTHY)):
                                    with patch.object(checker, "_check_integration_runner", return_value=_make_health("integration_runner", HealthStatus.HEALTHY)):
                                        with patch.object(checker, "_check_disk_space", return_value=_make_health("disk_space", HealthStatus.HEALTHY)):
                                            report = checker.check_all()
    assert "my_custom" in report.services


# ---------------------------------------------------------------------------
# watch() / stop_watch()
# ---------------------------------------------------------------------------


def test_watch_starts_background_thread(checker: HealthChecker) -> None:
    reports: list = []

    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "svc": lambda: _make_health("svc", HealthStatus.HEALTHY)
        }
        checker.watch(interval_seconds=0.05, callback=reports.append)
        time.sleep(0.2)
        checker.stop_watch()

    assert len(reports) >= 1
    assert isinstance(reports[0], SystemHealthReport)


def test_watch_is_idempotent(checker: HealthChecker) -> None:
    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "svc": lambda: _make_health("svc", HealthStatus.HEALTHY)
        }
        checker.watch(interval_seconds=60)
        thread1 = checker._watcher_thread
        checker.watch(interval_seconds=60)  # second call should be no-op
        thread2 = checker._watcher_thread
    assert thread1 is thread2
    checker.stop_watch()


def test_stop_watch_terminates_thread(checker: HealthChecker) -> None:
    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "svc": lambda: _make_health("svc", HealthStatus.HEALTHY)
        }
        checker.watch(interval_seconds=60)
        assert checker._watcher_thread is not None
        assert checker._watcher_thread.is_alive()
        checker.stop_watch()
        time.sleep(0.1)
        assert not checker._watcher_thread.is_alive()


# ---------------------------------------------------------------------------
# SQLite persistence: get_history() / get_alerts()
# ---------------------------------------------------------------------------


def test_get_history_empty(checker: HealthChecker) -> None:
    assert checker.get_history(hours=1) == []


def test_get_history_returns_persisted_reports(checker: HealthChecker) -> None:
    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "svc": lambda: _make_health("svc", HealthStatus.HEALTHY)
        }
        checker.check_all()
        checker.check_all()

    history = checker.get_history(hours=24)
    assert len(history) == 2
    for entry in history:
        assert "timestamp" in entry
        assert "overall_status" in entry
        assert "score" in entry
        assert "services" in entry
        assert "alerts" in entry


def test_get_history_respects_hours_filter(checker: HealthChecker, tmp_path: Path) -> None:
    db_path = str(tmp_path / "health.db")
    c = HealthChecker(db_path=db_path)
    # Manually insert an old record
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO health_reports (timestamp, overall_status, score, services_json, alerts_json) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2000-01-01T00:00:00", "healthy", 1.0, "{}", "[]"),
        )
        conn.commit()
    history = c.get_history(hours=1)
    # The 2000 entry should not appear
    for entry in history:
        assert entry["timestamp"] > "2000-01-01T01:00:00"


def test_get_alerts_empty(checker: HealthChecker) -> None:
    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "svc": lambda: _make_health("svc", HealthStatus.HEALTHY)
        }
        checker.check_all()
    assert checker.get_alerts(hours=1) == []


def test_get_alerts_returns_unhealthy_entries(checker: HealthChecker) -> None:
    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "svc": lambda: _make_health("svc", HealthStatus.UNHEALTHY)
        }
        checker.check_all()

    alerts = checker.get_alerts(hours=1)
    assert len(alerts) >= 1
    assert alerts[0]["alerts"]


# ---------------------------------------------------------------------------
# export_prometheus()
# ---------------------------------------------------------------------------


def test_export_prometheus_no_report(checker: HealthChecker) -> None:
    text = checker.export_prometheus()
    assert "# No health data" in text


def test_export_prometheus_format(checker: HealthChecker) -> None:
    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "lmstudio": lambda: _make_health("lmstudio", HealthStatus.HEALTHY),
            "nexus": lambda: _make_health("nexus", HealthStatus.DEGRADED),
        }
        checker.check_all()

    text = checker.export_prometheus()
    assert "cosysim_health_score" in text
    assert "cosysim_service_healthy" in text
    assert "cosysim_service_latency_ms" in text
    assert "cosysim_alerts_total" in text
    assert 'service="lmstudio"' in text
    assert 'service="nexus"' in text


def test_export_prometheus_healthy_score_1(checker: HealthChecker) -> None:
    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "svc": lambda: _make_health("svc", HealthStatus.HEALTHY)
        }
        checker.check_all()
    text = checker.export_prometheus()
    assert "cosysim_health_score 1.0000" in text


def test_export_prometheus_unhealthy_score_0(checker: HealthChecker) -> None:
    with patch.object(checker, "_all_probes") as mock_probes:
        mock_probes.return_value = {
            "svc": lambda: _make_health("svc", HealthStatus.UNHEALTHY)
        }
        checker.check_all()
    text = checker.export_prometheus()
    assert "cosysim_health_score 0.0000" in text


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_get_health_checker_singleton() -> None:
    import importlib
    import engine.observability.health_checker as mod

    orig = mod._checker_instance
    mod._checker_instance = None
    try:
        c1 = get_health_checker()
        c2 = get_health_checker()
        assert c1 is c2
    finally:
        mod._checker_instance = orig


def test_get_health_checker_returns_health_checker() -> None:
    import engine.observability.health_checker as mod

    orig = mod._checker_instance
    mod._checker_instance = None
    try:
        checker = get_health_checker()
        assert isinstance(checker, HealthChecker)
    finally:
        mod._checker_instance = orig
