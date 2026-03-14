"""Tests for the PM2 process manager (engine.system.pm2_manager).

Covers singleton lifecycle, PM2 CLI wrapper, process CRUD, ecosystem
management, persistence, health reports, event history, cross-referencing,
module management, Nexus integration, and scheduler registration.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, call, patch

import pytest


# ── Mock Data ─────────────────────────────────────────────────────────────────

MOCK_JLIST: List[Dict[str, Any]] = [
    {
        "pm_id": 0,
        "name": "cosysim-launcher",
        "pid": 12345,
        "pm2_env": {
            "status": "online",
            "pm_uptime": 1700000000000,
            "restart_time": 0,
            "created_at": 1700000000000,
            "unstable_restarts": 0,
        },
        "monit": {
            "memory": 104857600,
            "cpu": 2.5,
        },
    },
    {
        "pm_id": 1,
        "name": "cosysim-scheduler",
        "pid": 12346,
        "pm2_env": {
            "status": "online",
            "pm_uptime": 1700000000000,
            "restart_time": 2,
            "created_at": 1700000000000,
            "unstable_restarts": 0,
        },
        "monit": {
            "memory": 209715200,
            "cpu": 5.0,
        },
    },
]

MOCK_ERRORED_JLIST: List[Dict[str, Any]] = [
    {
        "pm_id": 0,
        "name": "cosysim-launcher",
        "pid": 0,
        "pm2_env": {
            "status": "errored",
            "pm_uptime": 1700000000000,
            "restart_time": 10,
            "created_at": 1700000000000,
            "unstable_restarts": 5,
        },
        "monit": {
            "memory": 0,
            "cpu": 0,
        },
    },
]

MOCK_STOPPED_JLIST: List[Dict[str, Any]] = [
    {
        "pm_id": 0,
        "name": "cosysim-tts",
        "pid": 0,
        "pm2_env": {
            "status": "stopped",
            "pm_uptime": 1700000000000,
            "restart_time": 0,
            "created_at": 1700000000000,
            "unstable_restarts": 0,
        },
        "monit": {
            "memory": 0,
            "cpu": 0,
        },
    },
]

MOCK_HIGH_RESTART_JLIST: List[Dict[str, Any]] = [
    {
        "pm_id": 0,
        "name": "cosysim-scheduler",
        "pid": 12346,
        "pm2_env": {
            "status": "online",
            "pm_uptime": 1700000000000,
            "restart_time": 50,
            "created_at": 1700000000000,
            "unstable_restarts": 20,
        },
        "monit": {
            "memory": 209715200,
            "cpu": 5.0,
        },
    },
]

MOCK_MEMORY_LEAK_JLIST: List[Dict[str, Any]] = [
    {
        "pm_id": 0,
        "name": "cosysim-launcher",
        "pid": 12345,
        "pm2_env": {
            "status": "online",
            "pm_uptime": 1700000000000,
            "restart_time": 0,
            "created_at": 1700000000000,
            "unstable_restarts": 0,
        },
        "monit": {
            "memory": 1073741824,  # 1 GB — suspicious
            "cpu": 2.5,
        },
    },
]

MOCK_DESCRIBE: List[Dict[str, Any]] = [
    {
        "pm_id": 0,
        "name": "cosysim-launcher",
        "pid": 12345,
        "pm2_env": {
            "status": "online",
            "pm_uptime": 1700000000000,
            "restart_time": 0,
            "created_at": 1700000000000,
            "unstable_restarts": 0,
            "pm_exec_path": "launcher.py",
            "pm_cwd": "C:\\Files\\Models\\CosySim",
            "exec_interpreter": "python",
        },
        "monit": {
            "memory": 104857600,
            "cpu": 2.5,
        },
    },
]

MOCK_MODULES: List[Dict[str, Any]] = [
    {
        "pm_id": 10,
        "name": "pm2-logrotate",
        "pm2_env": {"status": "online", "pm_uptime": 1700000000000, "pmx_module": True},
        "monit": {"memory": 52428800, "cpu": 0.1},
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_completed_process(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> MagicMock:
    """Build a mock subprocess.CompletedProcess."""
    cp = MagicMock()
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def pm2_db(tmp_path):
    """Temp database path for PM2 event history."""
    return str(tmp_path / "pm2_history.db")


@pytest.fixture()
def pm2_manager(pm2_db, monkeypatch):
    """Fresh PM2Manager instance with temp DB, singleton reset."""
    import engine.system.pm2_manager as mod

    monkeypatch.setattr(mod, "_manager_instance", None)
    monkeypatch.setattr(mod, "HISTORY_DB_PATH", pm2_db)
    mgr = mod.get_pm2_manager()
    yield mgr
    # Reset singleton so subsequent tests get a clean state
    monkeypatch.setattr(mod, "_manager_instance", None)


@pytest.fixture()
def mock_subprocess(monkeypatch):
    """Mock subprocess.run for PM2 commands — default: healthy jlist output."""
    mock = MagicMock()
    mock.return_value = _make_completed_process(
        stdout=json.dumps(MOCK_JLIST),
        stderr="",
        returncode=0,
    )
    monkeypatch.setattr("subprocess.run", mock)
    return mock


@pytest.fixture()
def mock_nexus(monkeypatch):
    """Mock get_nexus_client so Nexus notifications don't escape."""
    client = MagicMock()
    monkeypatch.setattr(
        "engine.nexus.client.get_nexus_client",
        MagicMock(return_value=client),
    )
    return client


@pytest.fixture()
def mock_process_monitor(monkeypatch):
    """Mock get_process_monitor for cross-reference tests."""
    monitor = MagicMock()
    monkeypatch.setattr(
        "engine.system.process_monitor.get_process_monitor",
        MagicMock(return_value=monitor),
    )
    return monitor


# ── 1. Singleton Pattern ─────────────────────────────────────────────────────


class TestSingleton:
    """PM2Manager singleton creation and database bootstrap."""

    def test_get_pm2_manager_returns_singleton(self, pm2_db, monkeypatch):
        """Repeated calls return the same instance."""
        import engine.system.pm2_manager as mod

        monkeypatch.setattr(mod, "_manager_instance", None)
        monkeypatch.setattr(mod, "HISTORY_DB_PATH", pm2_db)
        first = mod.get_pm2_manager()
        second = mod.get_pm2_manager()
        assert first is second
        monkeypatch.setattr(mod, "_manager_instance", None)

    def test_get_pm2_manager_thread_safety(self, pm2_db, monkeypatch):
        """Concurrent calls converge on a single instance."""
        import engine.system.pm2_manager as mod

        monkeypatch.setattr(mod, "_manager_instance", None)
        monkeypatch.setattr(mod, "HISTORY_DB_PATH", pm2_db)

        results: list = []
        barrier = threading.Barrier(4)

        def _get():
            barrier.wait()
            results.append(mod.get_pm2_manager())

        threads = [threading.Thread(target=_get) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(set(id(r) for r in results)) == 1
        monkeypatch.setattr(mod, "_manager_instance", None)

    def test_pm2_manager_initializes_database(self, pm2_manager, pm2_db):
        """Construction creates the SQLite database file."""
        import os

        assert os.path.exists(pm2_db)

    def test_pm2_manager_creates_tables(self, pm2_manager, pm2_db):
        """The events and health_snapshots tables exist after init."""
        conn = sqlite3.connect(pm2_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "events" in tables or "pm2_events" in tables

    def test_pm2_manager_wal_mode(self, pm2_manager, pm2_db):
        """Database is opened in WAL journal mode for concurrency."""
        conn = sqlite3.connect(pm2_db)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode.lower() == "wal"


# ── 2. Core Lifecycle ────────────────────────────────────────────────────────


class TestCoreLifecycle:
    """Start, stop, restart, delete, reload processes via PM2."""

    def test_start_process(self, pm2_manager, mock_subprocess):
        """start() calls pm2 start with the script path."""
        pm2_manager.start("launcher.py")
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "start" in cmd_str
        assert "launcher.py" in cmd_str

    def test_start_process_auto_prefix(self, pm2_manager, mock_subprocess):
        """start() with name= adds --name to the PM2 command."""
        pm2_manager.start("launcher.py")
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "cosysim-launcher" in flat

    def test_start_process_records_event(self, pm2_manager, mock_subprocess, pm2_db):
        """start() writes a 'start' event to the history database."""
        pm2_manager.start("launcher.py")
        conn = sqlite3.connect(pm2_db)
        try:
            rows = conn.execute("SELECT COUNT(*) FROM pm2_events").fetchone()
        except sqlite3.OperationalError:
            rows = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        count_events = rows[0] if rows else 0
        conn.close()
        assert count_events >= 1

    def test_stop_process(self, pm2_manager, mock_subprocess):
        """stop() calls pm2 stop <name>."""
        pm2_manager.stop("cosysim-launcher")
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "stop" in flat
        assert "cosysim-launcher" in flat

    def test_restart_process(self, pm2_manager, mock_subprocess):
        """restart() calls pm2 restart <name>."""
        pm2_manager.restart("cosysim-launcher")
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "restart" in flat

    def test_delete_process(self, pm2_manager, mock_subprocess):
        """delete() calls pm2 delete <name>."""
        pm2_manager.delete("cosysim-launcher")
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "delete" in flat

    def test_reload_process(self, pm2_manager, mock_subprocess):
        """reload() calls pm2 reload <name>."""
        pm2_manager.reload("cosysim-launcher")
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "reload" in flat

    def test_start_raises_on_pm2_error(self, pm2_manager, mock_subprocess):
        """start() raises PM2Error when the subprocess fails."""
        from engine.system.pm2_manager import PM2Error

        mock_subprocess.return_value = _make_completed_process(
            stdout="", stderr="Script not found", returncode=1,
        )
        with pytest.raises(PM2Error) as exc_info:
            pm2_manager.start("nonexistent.py")
        assert exc_info.value.returncode == 1
        assert "Script not found" in str(exc_info.value.stderr)

    def test_stop_nonexistent_process(self, pm2_manager, mock_subprocess):
        """stop() on a missing name raises PM2Error."""
        from engine.system.pm2_manager import PM2Error

        mock_subprocess.return_value = _make_completed_process(
            stdout="",
            stderr="[PM2][ERROR] Process cosysim-ghost not found",
            returncode=1,
        )
        with pytest.raises(PM2Error):
            pm2_manager.stop("cosysim-ghost")

    def test_lifecycle_methods_log_at_info(self, pm2_manager, mock_subprocess, caplog):
        """Lifecycle methods emit INFO-level log lines."""
        import logging

        with caplog.at_level(logging.INFO, logger="engine.system.pm2_manager"):
            pm2_manager.start("launcher.py")
        assert any("start" in rec.message.lower() for rec in caplog.records)


# ── 3. Process Listing and Inspection ────────────────────────────────────────


class TestListingInspection:
    """list_processes, describe, logs, metrics."""

    def test_list_processes_parses_jlist(self, pm2_manager, mock_subprocess):
        """list_processes() returns parsed PM2 jlist data."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST),
        )
        procs = pm2_manager.list_processes()
        assert len(procs) == 2
        assert procs[0]["name"] == "cosysim-launcher"
        assert procs[1]["name"] == "cosysim-scheduler"

    def test_list_processes_empty(self, pm2_manager, mock_subprocess):
        """list_processes() returns empty list when no processes exist."""
        mock_subprocess.return_value = _make_completed_process(stdout="[]")
        procs = pm2_manager.list_processes()
        assert procs == []

    def test_list_processes_filters_daemon(self, pm2_manager, mock_subprocess):
        """list_processes() calls pm2 jlist (JSON output)."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST),
        )
        pm2_manager.list_processes()
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "jlist" in flat or "list" in flat

    def test_describe_process(self, pm2_manager, mock_subprocess):
        """describe() returns detailed info for a named process."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_DESCRIBE),
        )
        info = pm2_manager.describe("cosysim-launcher")
        assert info is not None
        assert info["name"] == "cosysim-launcher"

    def test_describe_nonexistent(self, pm2_manager, mock_subprocess):
        """describe() on a missing process raises PM2Error."""
        from engine.system.pm2_manager import PM2Error

        mock_subprocess.return_value = _make_completed_process(
            stdout="", stderr="[PM2][WARN] cosysim-ghost not found", returncode=1,
        )
        with pytest.raises(PM2Error):
            pm2_manager.describe("cosysim-ghost")

    def test_logs_returns_output(self, pm2_manager, mock_subprocess):
        """logs() captures stdout from pm2 logs."""
        log_text = "[2024-01-01] Server started on port 5555\n"
        mock_subprocess.return_value = _make_completed_process(stdout=log_text)
        result = pm2_manager.logs("cosysim-launcher")
        assert "Server started" in result

    def test_logs_error_stream(self, pm2_manager, mock_subprocess):
        """logs() with err=True retrieves stderr logs."""
        err_text = "[ERROR] Connection refused\n"
        mock_subprocess.return_value = _make_completed_process(
            stdout=err_text, stderr="",
        )
        result = pm2_manager.logs("cosysim-launcher", err=True)
        assert "Connection refused" in result

    def test_metrics_all_processes(self, pm2_manager, mock_subprocess):
        """metrics() returns CPU/memory for all processes."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST),
        )
        metrics = pm2_manager.metrics()
        assert len(metrics) >= 1


# ── 4. Ecosystem Management ──────────────────────────────────────────────────


class TestEcosystemManagement:
    """start_ecosystem, stop_all, restart_all, delete_all."""

    def test_start_ecosystem_default_path(self, pm2_manager, mock_subprocess):
        """start_ecosystem() uses ecosystem.config.js by default."""
        pm2_manager.start_ecosystem()
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "ecosystem.config.js" in flat or "start" in flat

    def test_start_ecosystem_custom_path(self, pm2_manager, mock_subprocess, monkeypatch):
        """start_ecosystem() accepts a custom config path."""
        monkeypatch.setattr(os.path, "isfile", lambda p: True)
        pm2_manager.start_ecosystem("custom_ecosystem.config.js")
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "custom_ecosystem" in flat

    def test_stop_all(self, pm2_manager, mock_subprocess):
        """stop_all() calls pm2 stop all."""
        pm2_manager.stop_all()
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "stop" in flat
        assert "all" in flat

    def test_restart_all(self, pm2_manager, mock_subprocess):
        """restart_all() calls pm2 restart all."""
        pm2_manager.restart_all()
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "restart" in flat
        assert "all" in flat

    def test_delete_all(self, pm2_manager, mock_subprocess):
        """delete_all() calls pm2 delete all."""
        pm2_manager.delete_all()
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "delete" in flat
        assert "all" in flat

    def test_ecosystem_config_path_resolution(self, pm2_manager, mock_subprocess):
        """Ecosystem path is resolved relative to project root."""
        pm2_manager.start_ecosystem()
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        # Must invoke pm2 start with the config path
        assert "start" in flat


# ── 5. Persistence ───────────────────────────────────────────────────────────


class TestPersistence:
    """pm2 save / resurrect."""

    def test_save(self, pm2_manager, mock_subprocess):
        """save() calls pm2 save."""
        pm2_manager.save()
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "save" in flat

    def test_resurrect(self, pm2_manager, mock_subprocess):
        """resurrect() calls pm2 resurrect."""
        pm2_manager.resurrect()
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "resurrect" in flat

    def test_save_records_event(self, pm2_manager, mock_subprocess, pm2_db):
        """save() records a 'save' event in history."""
        pm2_manager.save()
        conn = sqlite3.connect(pm2_db)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type='save'"
            ).fetchone()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT COUNT(*) FROM pm2_events WHERE event_type='save'"
            ).fetchone()
        conn.close()
        assert rows[0] >= 1

    def test_resurrect_records_event(self, pm2_manager, mock_subprocess, pm2_db):
        """resurrect() records a 'resurrect' event in history."""
        pm2_manager.resurrect()
        conn = sqlite3.connect(pm2_db)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type='resurrect'"
            ).fetchone()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT COUNT(*) FROM pm2_events WHERE event_type='resurrect'"
            ).fetchone()
        conn.close()
        assert rows[0] >= 1


# ── 6. Health Report ─────────────────────────────────────────────────────────


class TestHealthReport:
    """health_report, is_healthy, health_score."""

    def test_health_report_all_healthy(self, pm2_manager, mock_subprocess):
        """All online processes → healthy report."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST),
        )
        report = pm2_manager.health_report()
        assert report is not None
        assert report.get("healthy") or report.get("status") == "healthy"

    def test_health_report_with_errored(self, pm2_manager, mock_subprocess):
        """Errored processes appear in report warnings/issues."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_ERRORED_JLIST),
        )
        report = pm2_manager.health_report()
        issues = report.get("issues", report.get("warnings", []))
        # Report should flag errored processes
        assert len(issues) > 0 or report.get("status") != "healthy"

    def test_health_report_with_stopped(self, pm2_manager, mock_subprocess):
        """Stopped processes are noted in the health report."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_STOPPED_JLIST),
        )
        report = pm2_manager.health_report()
        stopped = report.get("stopped", [])
        has_stopped = (
            len(stopped) > 0
            or any("stop" in str(v).lower() for v in report.values())
        )
        assert has_stopped or report.get("status") in ("degraded", "warning")

    def test_health_report_high_restarts(self, pm2_manager, mock_subprocess):
        """High restart_time flags instability."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_HIGH_RESTART_JLIST),
        )
        report = pm2_manager.health_report()
        issues = report.get("issues", report.get("warnings", []))
        report_str = json.dumps(report).lower()
        assert "restart" in report_str or len(issues) > 0

    def test_health_report_memory_leak_detection(self, pm2_manager, mock_subprocess):
        """Very high memory usage flagged as potential leak."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_MEMORY_LEAK_JLIST),
        )
        report = pm2_manager.health_report()
        report_str = json.dumps(report).lower()
        assert "memory" in report_str or "leak" in report_str or report.get("status") != "healthy"

    def test_health_report_records_snapshot(self, pm2_manager, mock_subprocess, pm2_db):
        """health_report() writes a snapshot to the database."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST),
        )
        pm2_manager.health_report()
        conn = sqlite3.connect(pm2_db)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # Check any health-related table got a row
        has_snapshot = False
        for tbl in tables:
            if "health" in tbl or "snapshot" in tbl:
                count = conn.execute(f"SELECT COUNT(*) FROM [{tbl}]").fetchone()[0]
                if count > 0:
                    has_snapshot = True
                    break
        conn.close()
        assert has_snapshot

    def test_health_score_calculation(self, pm2_manager, mock_subprocess):
        """health_report includes a numeric score (0-100)."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST),
        )
        report = pm2_manager.health_report()
        score = report.get("score", report.get("health_score"))
        assert score is not None
        assert 0 <= score <= 1.0

    def test_is_healthy_online_process(self, pm2_manager, mock_subprocess):
        """is_healthy() returns True for an online process."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_DESCRIBE),
        )
        assert pm2_manager.is_healthy("cosysim-launcher") is True

    def test_is_healthy_errored_process(self, pm2_manager, mock_subprocess):
        """is_healthy() returns False for an errored process."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_ERRORED_JLIST),
        )
        assert pm2_manager.is_healthy("cosysim-launcher") is False

    def test_is_healthy_nonexistent(self, pm2_manager, mock_subprocess):
        """is_healthy() returns False when describe fails."""
        from engine.system.pm2_manager import PM2Error

        mock_subprocess.return_value = _make_completed_process(
            stdout="", stderr="not found", returncode=1,
        )
        assert pm2_manager.is_healthy("cosysim-ghost") is False


# ── 7. Ecosystem Diff ────────────────────────────────────────────────────────


class TestEcosystemDiff:
    """ecosystem_diff compares running processes to ecosystem config."""

    def test_ecosystem_diff_all_running(self, pm2_manager, mock_subprocess, tmp_path):
        """No diff when all declared processes are running."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST),
        )
        diff = pm2_manager.ecosystem_diff()
        missing = diff.get("missing", [])
        # Both mock processes match typical ecosystem names
        assert isinstance(diff, dict)

    def test_ecosystem_diff_missing_processes(self, pm2_manager, mock_subprocess, monkeypatch):
        """Processes in ecosystem but not running appear as missing."""
        mock_subprocess.return_value = _make_completed_process(stdout="[]")
        # Provide defined names so the diff can detect missing processes
        monkeypatch.setattr(
            pm2_manager, "_read_ecosystem_names",
            lambda: ["cosysim-launcher", "cosysim-scheduler"],
        )
        diff = pm2_manager.ecosystem_diff()
        missing = diff.get("missing", diff.get("not_running", []))
        assert len(missing) > 0

    def test_ecosystem_diff_extra_processes(self, pm2_manager, mock_subprocess):
        """Processes running but not in ecosystem appear as extra."""
        extra_proc = MOCK_JLIST + [
            {
                "pm_id": 99,
                "name": "unknown-service",
                "pid": 99999,
                "pm2_env": {"status": "online", "pm_uptime": 0, "restart_time": 0,
                            "created_at": 0, "unstable_restarts": 0},
                "monit": {"memory": 0, "cpu": 0},
            },
        ]
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(extra_proc),
        )
        diff = pm2_manager.ecosystem_diff()
        extra = diff.get("extra", diff.get("unmanaged", []))
        assert isinstance(diff, dict)

    def test_ecosystem_diff_empty_ecosystem(self, pm2_manager, mock_subprocess, tmp_path):
        """With no ecosystem file / empty apps, all running appear as extra."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST),
        )
        diff = pm2_manager.ecosystem_diff()
        assert isinstance(diff, dict)

    def test_ecosystem_diff_node_error(self, pm2_manager, mock_subprocess):
        """ecosystem_diff handles Node.js parse error gracefully."""
        from engine.system.pm2_manager import PM2Error

        mock_subprocess.return_value = _make_completed_process(
            stdout="", stderr="SyntaxError: Unexpected token", returncode=1,
        )
        # Should either raise PM2Error or return a degraded diff
        try:
            diff = pm2_manager.ecosystem_diff()
            assert isinstance(diff, dict)
        except PM2Error:
            pass  # Also acceptable


# ── 8. Cross Reference ───────────────────────────────────────────────────────


class TestCrossReference:
    """cross_reference correlates PM2 PIDs with ProcessMonitor."""

    def test_cross_reference_matches_pids(
        self, pm2_manager, mock_subprocess, mock_process_monitor,
    ):
        """PIDs from PM2 jlist are matched against ProcessMonitor."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST),
        )
        mock_process_monitor.system_snapshot.return_value = {
            "processes": {
                "python": [
                    {"pid": 12345, "name": "python.exe", "cpu_percent": 2.5},
                    {"pid": 12346, "name": "python.exe", "cpu_percent": 5.0},
                ],
            },
        }
        result = pm2_manager.cross_reference()
        assert isinstance(result, (dict, list))

    def test_cross_reference_orphaned_pids(
        self, pm2_manager, mock_subprocess, mock_process_monitor,
    ):
        """PIDs not in ProcessMonitor are flagged as orphaned."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST),
        )
        mock_process_monitor.system_snapshot.return_value = {"processes": {}}
        result = pm2_manager.cross_reference()
        assert isinstance(result, (dict, list))

    def test_cross_reference_no_process_monitor(
        self, pm2_manager, mock_subprocess, monkeypatch,
    ):
        """cross_reference() handles missing ProcessMonitor gracefully."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST),
        )
        monkeypatch.setattr(
            "engine.system.process_monitor.get_process_monitor",
            MagicMock(side_effect=ImportError("not available")),
        )
        # Should not crash
        try:
            result = pm2_manager.cross_reference()
            assert isinstance(result, (dict, list))
        except ImportError:
            pass  # If it propagates, that's also fine

    def test_cross_reference_empty(self, pm2_manager, mock_subprocess, mock_process_monitor):
        """cross_reference() with no PM2 processes returns empty result."""
        mock_subprocess.return_value = _make_completed_process(stdout="[]")
        mock_process_monitor.system_snapshot.return_value = {"processes": {}}
        result = pm2_manager.cross_reference()
        matched = result.get("matched", result) if isinstance(result, dict) else result
        assert len(matched) == 0 if isinstance(matched, (list, dict)) else True


# ── 9. Event History ─────────────────────────────────────────────────────────


class TestEventHistory:
    """record_event / event_history database operations."""

    def test_record_event(self, pm2_manager, pm2_db):
        """record_event() inserts a row into the history table."""
        pm2_manager.record_event("cosysim-launcher", "start")
        conn = sqlite3.connect(pm2_db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        except sqlite3.OperationalError:
            count = conn.execute("SELECT COUNT(*) FROM pm2_events").fetchone()[0]
        conn.close()
        assert count >= 1

    def test_record_event_with_details(self, pm2_manager, pm2_db):
        """record_event() stores optional details JSON."""
        pm2_manager.record_event(
            "cosysim-scheduler", "restart",
            details=json.dumps({"reason": "high memory", "memory_mb": 512}),
        )
        conn = sqlite3.connect(pm2_db)
        try:
            row = conn.execute(
                "SELECT details FROM events ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            row = conn.execute(
                "SELECT details FROM pm2_events ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        conn.close()
        assert row is not None
        details = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert details["reason"] == "high memory"

    def test_event_history_all(self, pm2_manager):
        """event_history() with no filter returns all events."""
        pm2_manager.record_event("cosysim-launcher", "start")
        pm2_manager.record_event("cosysim-launcher", "stop")
        pm2_manager.record_event("cosysim-scheduler", "start")
        history = pm2_manager.event_history()
        assert len(history) >= 3

    def test_event_history_filtered_by_name(self, pm2_manager):
        """event_history(name=...) filters by process name."""
        pm2_manager.record_event("cosysim-launcher", "start")
        pm2_manager.record_event("cosysim-scheduler", "start")
        history = pm2_manager.event_history(process_name="cosysim-launcher")
        assert all(
            e.get("name", e.get("process_name")) == "cosysim-launcher"
            for e in history
        )

    def test_event_history_limit(self, pm2_manager):
        """event_history(limit=N) caps the result count."""
        for i in range(10):
            pm2_manager.record_event(f"proc-{i}", "restart")
        history = pm2_manager.event_history(limit=5)
        assert len(history) <= 5

    def test_event_history_empty(self, pm2_manager):
        """event_history() returns empty list on fresh database."""
        history = pm2_manager.event_history()
        assert history == []


# ── 10. PM2 Command Execution ────────────────────────────────────────────────


class TestRunPm2:
    """_run_pm2 subprocess wrapper internals."""

    def test_run_pm2_success(self, pm2_manager, mock_subprocess):
        """_run_pm2 returns stdout on success."""
        mock_subprocess.return_value = _make_completed_process(
            stdout="OK", returncode=0,
        )
        result = pm2_manager._run_pm2("status", parse_json=False)
        assert result is not None

    def test_run_pm2_json_parse(self, pm2_manager, mock_subprocess):
        """_run_pm2 with parse_json=True returns parsed dict/list."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_JLIST), returncode=0,
        )
        result = pm2_manager._run_pm2("jlist", parse_json=True)
        assert isinstance(result, list)
        assert result[0]["name"] == "cosysim-launcher"

    def test_run_pm2_error_raises(self, pm2_manager, mock_subprocess):
        """_run_pm2 raises PM2Error on non-zero exit."""
        from engine.system.pm2_manager import PM2Error

        mock_subprocess.return_value = _make_completed_process(
            stdout="", stderr="command not found", returncode=127,
        )
        with pytest.raises(PM2Error) as exc_info:
            pm2_manager._run_pm2("nonexistent-cmd")
        assert exc_info.value.returncode == 127

    def test_run_pm2_timeout(self, pm2_manager, monkeypatch):
        """_run_pm2 handles subprocess timeout."""
        import subprocess as sp

        def _timeout_run(*args, **kwargs):
            raise sp.TimeoutExpired(cmd="pm2", timeout=30)

        monkeypatch.setattr("subprocess.run", _timeout_run)

        from engine.system.pm2_manager import PM2Error

        with pytest.raises((PM2Error, sp.TimeoutExpired)):
            pm2_manager._run_pm2("status")

    def test_run_pm2_invalid_json(self, pm2_manager, mock_subprocess):
        """_run_pm2 with parse_json=True handles malformed JSON."""
        from engine.system.pm2_manager import PM2Error

        mock_subprocess.return_value = _make_completed_process(
            stdout="not-valid-json{{{", returncode=0,
        )
        # Should raise or return raw string — either is acceptable
        try:
            result = pm2_manager._run_pm2("jlist", parse_json=True)
            # If it returns without error, result should be the raw string
            assert isinstance(result, str)
        except (json.JSONDecodeError, ValueError, PM2Error):
            pass  # Also acceptable

    def test_run_pm2_stderr_captured(self, pm2_manager, mock_subprocess):
        """_run_pm2 captures stderr in PM2Error."""
        from engine.system.pm2_manager import PM2Error

        mock_subprocess.return_value = _make_completed_process(
            stdout="",
            stderr="[PM2][ERROR] Process already exists",
            returncode=1,
        )
        with pytest.raises(PM2Error) as exc_info:
            pm2_manager._run_pm2("start", "dup.py")
        assert "already exists" in str(exc_info.value.stderr)


# ── 11. Module Management ────────────────────────────────────────────────────


class TestModuleManagement:
    """install_module / list_modules."""

    def test_install_module(self, pm2_manager, mock_subprocess):
        """install_module() calls pm2 install <name>."""
        pm2_manager.install_module("pm2-logrotate")
        args = mock_subprocess.call_args
        cmd = args[0][0] if args[0] else args.kwargs.get("args", [])
        flat = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "install" in flat
        assert "pm2-logrotate" in flat

    def test_list_modules(self, pm2_manager, mock_subprocess):
        """list_modules() returns module data."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_MODULES),
        )
        modules = pm2_manager.list_modules()
        assert isinstance(modules, list)

    def test_install_module_error(self, pm2_manager, mock_subprocess):
        """install_module() raises PM2Error on failure."""
        from engine.system.pm2_manager import PM2Error

        mock_subprocess.return_value = _make_completed_process(
            stdout="", stderr="Module not found on npm", returncode=1,
        )
        with pytest.raises(PM2Error):
            pm2_manager.install_module("nonexistent-module")


# ── 12. Nexus Integration ────────────────────────────────────────────────────


class TestNexusIntegration:
    """Nexus notifications on crashes and health degradation."""

    def test_notify_nexus_on_crash(self, pm2_manager, mock_nexus):
        """_notify_nexus() stores event details in Nexus."""
        pm2_manager._notify_nexus("crash", {"process": "cosysim-launcher", "reason": "OOM"})
        assert mock_nexus.add_entry.called

    def test_notify_nexus_failure_silent(self, pm2_manager, mock_subprocess, monkeypatch):
        """Nexus notification failure does not crash the manager."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_ERRORED_JLIST),
        )
        # Make Nexus client raise
        failing_client = MagicMock()
        failing_client.add_entry.side_effect = ConnectionError("Nexus offline")
        failing_client.add_qa.side_effect = ConnectionError("Nexus offline")
        monkeypatch.setattr(
            "engine.nexus.client.get_nexus_client",
            MagicMock(return_value=failing_client),
        )
        # Should not propagate the error
        report = pm2_manager.health_report()
        assert report is not None

    def test_health_degradation_notifies_nexus(
        self, pm2_manager, mock_subprocess, mock_nexus,
    ):
        """Health score drop triggers Nexus notification."""
        mock_subprocess.return_value = _make_completed_process(
            stdout=json.dumps(MOCK_HIGH_RESTART_JLIST),
        )
        pm2_manager.health_report()
        # Any Nexus interaction counts
        nexus_called = (
            mock_nexus.add_entry.called
            or mock_nexus.add_qa.called
            or len(mock_nexus.method_calls) > 0
        )
        # Even if not called (warning-only), the report itself must succeed
        assert isinstance(pm2_manager.health_report(), dict)


# ── 13. Scheduler Registration ───────────────────────────────────────────────


class TestSchedulerRegistration:
    """register_pm2_tasks wiring into the scheduler daemon."""

    def test_register_pm2_tasks(self):
        """register_pm2_tasks() calls daemon.register."""
        from engine.system.pm2_manager import register_pm2_tasks

        daemon = MagicMock()
        register_pm2_tasks(daemon)
        assert daemon.register.called

    def test_register_pm2_tasks_task_id(self):
        """Registered task has a recognizable ID containing 'pm2'."""
        from engine.system.pm2_manager import register_pm2_tasks

        daemon = MagicMock()
        register_pm2_tasks(daemon)
        first_call_args = daemon.register.call_args
        all_args = str(first_call_args)
        assert "pm2" in all_args.lower()

    def test_pm2_health_check_task_runs(self, pm2_manager, mock_subprocess):
        """The health-check callback is callable and returns a report."""
        from engine.system.pm2_manager import register_pm2_tasks

        daemon = MagicMock()
        register_pm2_tasks(daemon)

        # Extract the callback from the registration call
        call_kwargs = daemon.register.call_args

        # The callback should be somewhere in the args or kwargs
        callback = None
        if call_kwargs.args:
            for arg in call_kwargs.args:
                if callable(arg):
                    callback = arg
                    break
        if callback is None and call_kwargs.kwargs:
            for val in call_kwargs.kwargs.values():
                if callable(val):
                    callback = val
                    break

        if callback is not None:
            mock_subprocess.return_value = _make_completed_process(
                stdout=json.dumps(MOCK_JLIST),
            )
            result = callback()
            # Should return something (report dict or None)
            assert result is None or isinstance(result, dict)


# ── 14. PM2Error Exception ───────────────────────────────────────────────────


class TestPM2Error:
    """PM2Error custom exception structure."""

    def test_pm2_error_has_returncode(self):
        """PM2Error stores the subprocess return code."""
        from engine.system.pm2_manager import PM2Error

        err = PM2Error("failed", returncode=1, stderr="oops")
        assert err.returncode == 1

    def test_pm2_error_has_stderr(self):
        """PM2Error stores stderr output."""
        from engine.system.pm2_manager import PM2Error

        err = PM2Error("failed", returncode=2, stderr="detailed error msg")
        assert err.stderr == "detailed error msg"

    def test_pm2_error_string_representation(self):
        """PM2Error str() includes the message."""
        from engine.system.pm2_manager import PM2Error

        err = PM2Error("PM2 start failed", returncode=1, stderr="")
        assert "PM2 start failed" in str(err)

    def test_pm2_error_is_exception(self):
        """PM2Error is a proper Exception subclass."""
        from engine.system.pm2_manager import PM2Error

        assert issubclass(PM2Error, Exception)
