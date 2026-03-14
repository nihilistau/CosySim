"""Tests for engine.skills.builtin.process_skills — 14 PM2 process management skills.

Verifies each skill calls PM2Manager correctly, returns valid JSON,
and handles errors gracefully with an ``error`` key in the response.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ──── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_pm2_manager() -> MagicMock:
    """Mock PM2Manager instance with sensible defaults for every method."""
    mgr = MagicMock()
    mgr.list_processes.return_value = [
        {"name": "cosysim-launcher", "status": "online", "pid": 1234, "cpu": 2.5, "memory_mb": 100},
        {"name": "cosysim-scheduler", "status": "online", "pid": 1235, "cpu": 5.0, "memory_mb": 200},
    ]
    mgr.start.return_value = {"status": "online", "name": "cosysim-launcher"}
    mgr.stop.return_value = {"status": "stopped", "name": "cosysim-launcher"}
    mgr.restart.return_value = {"status": "online", "name": "cosysim-launcher"}
    mgr.reload.return_value = {"status": "online", "name": "cosysim-launcher"}
    mgr.delete.return_value = {"status": "deleted", "name": "cosysim-launcher"}
    mgr.logs.return_value = (
        "2024-01-01 12:00:00: Server started on port 8500\n"
        "2024-01-01 12:00:01: Ready"
    )
    mgr.metrics.return_value = {
        "processes": [
            {"name": "cosysim-launcher", "cpu": 2.5, "memory_mb": 100},
        ],
        "total_cpu": 2.5,
        "total_memory_mb": 100,
    }
    mgr.health_report.return_value = {
        "healthy": ["cosysim-launcher"],
        "unhealthy": [],
        "stopped": [],
        "summary": "All processes healthy",
        "total": 1,
        "online": 1,
        "errored": 0,
        "stopped_count": 0,
        "health_score": 1.0,
        "recommendations": [],
    }
    mgr.is_healthy.return_value = True
    mgr.save.return_value = {"saved": True, "process_count": 2}
    mgr.resurrect.return_value = {"resurrected": True}
    mgr.start_ecosystem.return_value = {"started": 5}
    mgr.stop_all.return_value = {"stopped": 5}
    mgr.ecosystem_diff.return_value = {
        "defined": ["cosysim-launcher", "cosysim-scheduler"],
        "running": ["cosysim-launcher", "cosysim-scheduler"],
        "missing": [],
        "extra": [],
    }
    mgr.event_history.return_value = [
        {
            "timestamp": "2024-01-01T12:00:00",
            "process_name": "cosysim-launcher",
            "event_type": "start",
            "details": "",
        },
    ]
    return mgr


# ──── Skill Registration ──────────────────────────────────────────────


def test_all_skills_have_pack_process():
    """All process skills are in the 'process' pack."""
    from engine.skills.registry import SKILL_REGISTRY

    import engine.skills.builtin.process_skills  # ensure registration

    process_skills = SKILL_REGISTRY.get_pack_metas("process")
    assert len(process_skills) > 0, "No skills registered with pack='process'"
    for s in process_skills:
        assert s.pack == "process"


def test_skill_count():
    """Verify expected number of process skills (14)."""
    from engine.skills.registry import SKILL_REGISTRY

    import engine.skills.builtin.process_skills  # noqa: F401

    process_skills = SKILL_REGISTRY.get_pack_metas("process")
    assert len(process_skills) == 14


# ──── Process List ────────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_list_returns_json(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_list returns a JSON list of processes."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_list

    result = process_list()
    data = json.loads(result)

    assert data["ok"] is True
    assert data["count"] == 2
    assert len(data["processes"]) == 2
    assert data["processes"][0]["name"] == "cosysim-launcher"
    assert data["processes"][0]["status"] == "online"


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_list_empty(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_list returns empty list when no processes exist."""
    mock_pm2_manager.list_processes.return_value = []
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_list

    result = process_list()
    data = json.loads(result)

    assert data["ok"] is True
    assert data["count"] == 0
    assert data["processes"] == []


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_list_error(mock_get: MagicMock) -> None:
    """process_list returns JSON with error key on failure."""
    mock_get.return_value.list_processes.side_effect = RuntimeError("pm2 not found")
    from engine.skills.builtin.process_skills import process_list

    result = process_list()
    data = json.loads(result)

    assert "error" in data
    assert "pm2 not found" in data["error"]


# ──── Process Start ───────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_start(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_start returns JSON with status and name."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_start

    result = process_start("cosysim-launcher")
    data = json.loads(result)

    assert data["status"] == "online"
    assert data["name"] == "cosysim-launcher"
    mock_pm2_manager.start.assert_called_once_with("cosysim-launcher")


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_start_with_prefix(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_start works with prefixed process names."""
    mock_pm2_manager.start.return_value = {"status": "online", "name": "cosysim-tts-server"}
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_start

    result = process_start("cosysim-tts-server")
    data = json.loads(result)

    assert data["name"] == "cosysim-tts-server"
    mock_pm2_manager.start.assert_called_once_with("cosysim-tts-server")


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_start_error(mock_get: MagicMock) -> None:
    """process_start returns error JSON on failure."""
    mock_get.return_value.start.side_effect = RuntimeError("process not found")
    from engine.skills.builtin.process_skills import process_start

    result = process_start("nonexistent")
    data = json.loads(result)

    assert "error" in data
    assert "process not found" in data["error"]


# ──── Process Stop ────────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_stop(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_stop returns JSON with stopped status."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_stop

    result = process_stop("cosysim-launcher")
    data = json.loads(result)

    assert data["status"] == "stopped"
    assert data["name"] == "cosysim-launcher"
    mock_pm2_manager.stop.assert_called_once_with("cosysim-launcher")


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_stop_nonexistent(mock_get: MagicMock) -> None:
    """process_stop returns error when process does not exist."""
    mock_get.return_value.stop.side_effect = RuntimeError("process [ghost] not found")
    from engine.skills.builtin.process_skills import process_stop

    result = process_stop("ghost")
    data = json.loads(result)

    assert "error" in data
    assert "ghost" in data["error"]


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_stop_error(mock_get: MagicMock) -> None:
    """process_stop returns error JSON on unexpected failure."""
    mock_get.return_value.stop.side_effect = OSError("connection refused")
    from engine.skills.builtin.process_skills import process_stop

    result = process_stop("cosysim-launcher")
    data = json.loads(result)

    assert "error" in data
    assert "connection refused" in data["error"]


# ──── Process Restart ─────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_restart(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_restart returns JSON with online status."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_restart

    result = process_restart("cosysim-launcher")
    data = json.loads(result)

    assert data["status"] == "online"
    assert data["name"] == "cosysim-launcher"
    mock_pm2_manager.restart.assert_called_once_with("cosysim-launcher")


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_restart_error(mock_get: MagicMock) -> None:
    """process_restart returns error JSON on failure."""
    mock_get.return_value.restart.side_effect = RuntimeError("restart failed")
    from engine.skills.builtin.process_skills import process_restart

    result = process_restart("cosysim-launcher")
    data = json.loads(result)

    assert "error" in data
    assert "restart failed" in data["error"]


# ──── Process Reload ──────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_reload(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_reload returns JSON with online status."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_reload

    result = process_reload("cosysim-launcher")
    data = json.loads(result)

    assert data["status"] == "online"
    assert data["name"] == "cosysim-launcher"
    mock_pm2_manager.reload.assert_called_once_with("cosysim-launcher")


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_reload_error(mock_get: MagicMock) -> None:
    """process_reload returns error JSON on failure."""
    mock_get.return_value.reload.side_effect = RuntimeError("reload failed")
    from engine.skills.builtin.process_skills import process_reload

    result = process_reload("cosysim-launcher")
    data = json.loads(result)

    assert "error" in data
    assert "reload failed" in data["error"]


# ──── Health Report ───────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_health_report(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_health_report returns a full health report JSON."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_health_report

    result = process_health_report()
    data = json.loads(result)

    assert data["summary"] == "All processes healthy"
    assert data["health_score"] == 1.0
    assert data["online"] == 1
    assert data["errored"] == 0
    assert isinstance(data["healthy"], list)
    assert isinstance(data["unhealthy"], list)
    assert isinstance(data["recommendations"], list)


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_health_report_with_issues(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_health_report surfaces unhealthy processes and recommendations."""
    mock_pm2_manager.health_report.return_value = {
        "healthy": ["cosysim-launcher"],
        "unhealthy": ["cosysim-scheduler"],
        "stopped": ["cosysim-tts"],
        "summary": "Issues detected",
        "total": 3,
        "online": 1,
        "errored": 1,
        "stopped_count": 1,
        "health_score": 0.33,
        "recommendations": [
            "Restart errored processes: cosysim-scheduler",
            "Consider starting stopped processes: cosysim-tts",
        ],
    }
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_health_report

    result = process_health_report()
    data = json.loads(result)

    assert data["summary"] == "Issues detected"
    assert data["health_score"] == 0.33
    assert "cosysim-scheduler" in data["unhealthy"]
    assert "cosysim-tts" in data["stopped"]
    assert len(data["recommendations"]) == 2


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_health_report_error(mock_get: MagicMock) -> None:
    """process_health_report returns error JSON on failure."""
    mock_get.return_value.health_report.side_effect = RuntimeError("pm2 unavailable")
    from engine.skills.builtin.process_skills import process_health_report

    result = process_health_report()
    data = json.loads(result)

    assert "error" in data
    assert "pm2 unavailable" in data["error"]


# ──── Metrics ─────────────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_metrics(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_metrics returns CPU/memory metrics JSON."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_metrics

    result = process_metrics()
    data = json.loads(result)

    assert "processes" in data
    assert data["total_cpu"] == 2.5
    assert data["total_memory_mb"] == 100
    assert len(data["processes"]) == 1
    assert data["processes"][0]["name"] == "cosysim-launcher"


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_metrics_error(mock_get: MagicMock) -> None:
    """process_metrics returns error JSON on failure."""
    mock_get.return_value.metrics.side_effect = RuntimeError("metrics collection failed")
    from engine.skills.builtin.process_skills import process_metrics

    result = process_metrics()
    data = json.loads(result)

    assert "error" in data
    assert "metrics collection failed" in data["error"]


# ──── Logs ────────────────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_logs(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_logs returns log output wrapped in JSON."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_logs

    result = process_logs("cosysim-launcher")
    data = json.loads(result)

    assert data["name"] == "cosysim-launcher"
    assert data["lines"] == 50
    assert "Server started" in data["output"]
    mock_pm2_manager.logs.assert_called_once_with("cosysim-launcher", lines=50)


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_logs_custom_lines(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_logs respects the lines parameter."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_logs

    result = process_logs("cosysim-launcher", lines=100)
    data = json.loads(result)

    assert data["lines"] == 100
    mock_pm2_manager.logs.assert_called_once_with("cosysim-launcher", lines=100)


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_logs_error(mock_get: MagicMock) -> None:
    """process_logs returns error JSON on failure."""
    mock_get.return_value.logs.side_effect = FileNotFoundError("log file missing")
    from engine.skills.builtin.process_skills import process_logs

    result = process_logs("cosysim-launcher")
    data = json.loads(result)

    assert "error" in data
    assert "log file missing" in data["error"]


# ──── Is Healthy ──────────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_is_healthy_true(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_is_healthy returns healthy=True for online processes."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_is_healthy

    result = process_is_healthy("cosysim-launcher")
    data = json.loads(result)

    assert data["healthy"] is True
    assert "online" in data["details"].lower()


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_is_healthy_false(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_is_healthy returns healthy=False for stopped/errored processes."""
    mock_pm2_manager.is_healthy.return_value = False
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_is_healthy

    result = process_is_healthy("cosysim-dead")
    data = json.loads(result)

    assert data["healthy"] is False
    assert "not online" in data["details"].lower()


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_is_healthy_error(mock_get: MagicMock) -> None:
    """process_is_healthy returns error JSON on failure."""
    mock_get.return_value.is_healthy.side_effect = RuntimeError("check failed")
    from engine.skills.builtin.process_skills import process_is_healthy

    result = process_is_healthy("cosysim-launcher")
    data = json.loads(result)

    assert "error" in data
    assert "check failed" in data["error"]


# ──── Save State ──────────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_save_state(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_save_state returns saved=True with process count."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_save_state

    result = process_save_state()
    data = json.loads(result)

    assert data["saved"] is True
    assert data["process_count"] == 2
    mock_pm2_manager.save.assert_called_once()


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_save_state_error(mock_get: MagicMock) -> None:
    """process_save_state returns error JSON on failure."""
    mock_get.return_value.save.side_effect = PermissionError("dump file write denied")
    from engine.skills.builtin.process_skills import process_save_state

    result = process_save_state()
    data = json.loads(result)

    assert "error" in data
    assert "dump file write denied" in data["error"]


# ──── Start Ecosystem ─────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_start_ecosystem(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_start_ecosystem returns count of started processes."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_start_ecosystem

    result = process_start_ecosystem()
    data = json.loads(result)

    assert data["started"] == 5
    mock_pm2_manager.start_ecosystem.assert_called_once()


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_start_ecosystem_error(mock_get: MagicMock) -> None:
    """process_start_ecosystem returns error JSON on failure."""
    mock_get.return_value.start_ecosystem.side_effect = FileNotFoundError(
        "ecosystem.config.js not found"
    )
    from engine.skills.builtin.process_skills import process_start_ecosystem

    result = process_start_ecosystem()
    data = json.loads(result)

    assert "error" in data
    assert "ecosystem.config.js" in data["error"]


# ──── Stop All ────────────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_stop_all(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_stop_all returns count of stopped processes."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_stop_all

    result = process_stop_all()
    data = json.loads(result)

    assert data["stopped"] == 5
    mock_pm2_manager.stop_all.assert_called_once()


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_stop_all_error(mock_get: MagicMock) -> None:
    """process_stop_all returns error JSON on failure."""
    mock_get.return_value.stop_all.side_effect = RuntimeError("pm2 daemon crashed")
    from engine.skills.builtin.process_skills import process_stop_all

    result = process_stop_all()
    data = json.loads(result)

    assert "error" in data
    assert "pm2 daemon crashed" in data["error"]


# ──── Ecosystem Diff ──────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_ecosystem_diff(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_ecosystem_diff returns diff with no drift."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_ecosystem_diff

    result = process_ecosystem_diff()
    data = json.loads(result)

    assert isinstance(data["defined"], list)
    assert isinstance(data["running"], list)
    assert data["missing"] == []
    assert data["extra"] == []


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_ecosystem_diff_with_drift(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_ecosystem_diff reports missing and extra processes."""
    mock_pm2_manager.ecosystem_diff.return_value = {
        "defined": ["cosysim-launcher", "cosysim-scheduler", "cosysim-tts"],
        "running": ["cosysim-launcher", "cosysim-rogue"],
        "missing": ["cosysim-scheduler", "cosysim-tts"],
        "extra": ["cosysim-rogue"],
    }
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_ecosystem_diff

    result = process_ecosystem_diff()
    data = json.loads(result)

    assert "cosysim-scheduler" in data["missing"]
    assert "cosysim-tts" in data["missing"]
    assert "cosysim-rogue" in data["extra"]
    assert len(data["missing"]) == 2
    assert len(data["extra"]) == 1


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_ecosystem_diff_error(mock_get: MagicMock) -> None:
    """process_ecosystem_diff returns error JSON on failure."""
    mock_get.return_value.ecosystem_diff.side_effect = RuntimeError("config parse error")
    from engine.skills.builtin.process_skills import process_ecosystem_diff

    result = process_ecosystem_diff()
    data = json.loads(result)

    assert "error" in data
    assert "config parse error" in data["error"]


# ──── Event History ───────────────────────────────────────────────────


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_event_history(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_event_history returns list of events."""
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_event_history

    result = process_event_history()
    data = json.loads(result)

    assert data["ok"] is True
    assert data["count"] == 1
    assert len(data["events"]) == 1
    assert data["events"][0]["event_type"] == "start"
    assert data["events"][0]["process_name"] == "cosysim-launcher"
    mock_pm2_manager.event_history.assert_called_once_with(name="", limit=20)


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_event_history_filtered(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """process_event_history passes name and limit filters through."""
    mock_pm2_manager.event_history.return_value = [
        {
            "timestamp": "2024-01-01T13:00:00",
            "process_name": "cosysim-scheduler",
            "event_type": "restart",
            "details": "auto-restart after crash",
        },
    ]
    mock_get.return_value = mock_pm2_manager
    from engine.skills.builtin.process_skills import process_event_history

    result = process_event_history(name="cosysim-scheduler", limit=5)
    data = json.loads(result)

    assert data["ok"] is True
    assert data["count"] == 1
    assert data["events"][0]["process_name"] == "cosysim-scheduler"
    mock_pm2_manager.event_history.assert_called_once_with(name="cosysim-scheduler", limit=5)


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_process_event_history_error(mock_get: MagicMock) -> None:
    """process_event_history returns error JSON on failure."""
    mock_get.return_value.event_history.side_effect = RuntimeError("bus read error")
    from engine.skills.builtin.process_skills import process_event_history

    result = process_event_history()
    data = json.loads(result)

    assert "error" in data
    assert "bus read error" in data["error"]


# ──── JSON Output Invariants ──────────────────────────────────────────


_SKILL_NAMES = [
    "process_list",
    "process_start",
    "process_stop",
    "process_restart",
    "process_reload",
    "process_health_report",
    "process_metrics",
    "process_logs",
    "process_is_healthy",
    "process_save_state",
    "process_start_ecosystem",
    "process_stop_all",
    "process_ecosystem_diff",
    "process_event_history",
]

_SKILLS_WITH_NAME_ARG = [
    "process_start",
    "process_stop",
    "process_restart",
    "process_reload",
    "process_logs",
    "process_is_healthy",
]

_SKILLS_NO_ARGS = [
    "process_list",
    "process_health_report",
    "process_metrics",
    "process_save_state",
    "process_start_ecosystem",
    "process_stop_all",
    "process_ecosystem_diff",
    "process_event_history",
]


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_all_skills_return_valid_json(mock_get: MagicMock, mock_pm2_manager: MagicMock) -> None:
    """Every process skill returns a parseable JSON string."""
    mock_get.return_value = mock_pm2_manager
    import engine.skills.builtin.process_skills as mod

    for name in _SKILL_NAMES:
        fn = getattr(mod, name)
        if name in _SKILLS_WITH_NAME_ARG:
            result = fn("cosysim-launcher")
        else:
            result = fn()
        assert isinstance(result, str), f"{name} did not return str"
        parsed = json.loads(result)
        assert parsed is not None, f"{name} returned null JSON"


@patch("engine.system.pm2_manager.get_pm2_manager")
def test_error_responses_contain_error_key(mock_get: MagicMock) -> None:
    """Every skill returns {\"error\": ...} when the PM2Manager call raises."""
    mgr = MagicMock()
    # Make every attribute raise
    mgr.list_processes.side_effect = RuntimeError("boom")
    mgr.start.side_effect = RuntimeError("boom")
    mgr.stop.side_effect = RuntimeError("boom")
    mgr.restart.side_effect = RuntimeError("boom")
    mgr.reload.side_effect = RuntimeError("boom")
    mgr.health_report.side_effect = RuntimeError("boom")
    mgr.metrics.side_effect = RuntimeError("boom")
    mgr.logs.side_effect = RuntimeError("boom")
    mgr.is_healthy.side_effect = RuntimeError("boom")
    mgr.save.side_effect = RuntimeError("boom")
    mgr.start_ecosystem.side_effect = RuntimeError("boom")
    mgr.stop_all.side_effect = RuntimeError("boom")
    mgr.ecosystem_diff.side_effect = RuntimeError("boom")
    mgr.event_history.side_effect = RuntimeError("boom")
    mock_get.return_value = mgr

    import engine.skills.builtin.process_skills as mod

    for name in _SKILL_NAMES:
        fn = getattr(mod, name)
        if name in _SKILLS_WITH_NAME_ARG:
            result = fn("test")
        else:
            result = fn()
        data = json.loads(result)
        assert "error" in data, f"{name} missing 'error' key on exception"
        assert "boom" in data["error"], f"{name} error message should contain 'boom'"
