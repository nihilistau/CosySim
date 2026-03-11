"""Tests for system recovery skills pack."""
from __future__ import annotations

import json
import os
import sqlite3
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────


def _make_sqlite_db(path: Path) -> None:
    """Create a minimal valid SQLite database file."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO test VALUES (1)")
    conn.commit()
    conn.close()


def _make_log_file(path: Path, hours_ago: float = 0.5) -> None:
    """Write a fake log file with ERROR and INFO entries."""
    now = datetime.now()
    recent = now - timedelta(hours=hours_ago)
    old = now - timedelta(hours=24)
    content = textwrap.dedent(f"""\
        {recent.strftime('%Y-%m-%d %H:%M:%S')} INFO [server] Started OK
        {recent.strftime('%Y-%m-%d %H:%M:%S')} ERROR [database] Connection timeout
        {recent.strftime('%Y-%m-%d %H:%M:%S')} CRITICAL [engine] Out of memory
        {old.strftime('%Y-%m-%d %H:%M:%S')} ERROR [server] Old error should be filtered
    """)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def project_root(tmp_path):
    """Set up a mock project root with data/, logs/, backups/, config/."""
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "backups").mkdir()
    (tmp_path / "config").mkdir()

    # Create test databases
    _make_sqlite_db(tmp_path / "data" / "simulation.db")
    _make_sqlite_db(tmp_path / "data" / "nexus.db")
    _make_sqlite_db(tmp_path / "data" / "metrics.db")

    # Create a config file
    (tmp_path / "config" / "default.yaml").write_text(
        "lmstudio:\n  port: 1234\nscenes:\n  phone:\n    port: 5555\n",
        encoding="utf-8",
    )

    # Create a log file with errors
    _make_log_file(tmp_path / "logs" / "cosysim.log")

    return tmp_path


@pytest.fixture
def _patch_root(project_root):
    """Patch _PROJECT_ROOT in recovery_skills to use tmp_path."""
    with patch("engine.skills.builtin.recovery_skills._PROJECT_ROOT", project_root):
        yield project_root


@pytest.fixture
def mock_port_registry():
    """Mock port registry returning known ports."""
    registry = MagicMock()
    ports = {"hub": 8500, "nexus": 8700, "tts": 8600, "lmstudio": 1234, "comfyui": 8188}
    registry._ports = ports
    registry.get.side_effect = lambda svc, default=None: ports.get(svc, default)
    return registry


# ── backup_database ──────────────────────────────────────────────────


class TestBackupDatabase:
    def test_creates_backup_file(self, _patch_root):
        from engine.skills.builtin.recovery_skills import backup_database
        result = json.loads(backup_database("simulation"))
        assert result["ok"] is True
        assert result["db_name"] == "simulation"
        assert Path(result["backup_path"]).exists()
        assert result["size_kb"] > 0

    def test_backup_unknown_db_returns_error(self, _patch_root):
        from engine.skills.builtin.recovery_skills import backup_database
        result = json.loads(backup_database("nonexistent"))
        assert result["ok"] is False
        assert "Unknown database" in result["error"]

    def test_limits_to_10_backups(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import backup_database

        backup_dir = project_root / "backups"
        # Pre-create 12 backups
        for i in range(12):
            ts = f"20240101_{i:06d}"
            path = backup_dir / f"simulation_{ts}.db"
            path.write_bytes(b"x")

        result = json.loads(backup_database("simulation"))
        assert result["ok"] is True

        remaining = list(backup_dir.glob("simulation_*.db"))
        assert len(remaining) <= 10

    def test_backup_missing_db_returns_error(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import backup_database
        (project_root / "data" / "simulation.db").unlink()
        result = json.loads(backup_database("simulation"))
        assert result["ok"] is False
        assert "not found" in result["error"]


# ── restore_database ─────────────────────────────────────────────────


class TestRestoreDatabase:
    def test_restores_from_backup(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import restore_database

        # Create a backup file
        backup = project_root / "backups" / "test_backup.db"
        _make_sqlite_db(backup)

        result = json.loads(restore_database(str(backup), "simulation"))
        assert result["ok"] is True
        assert result["pre_restore_backup"] is not None

    def test_restore_missing_backup_returns_error(self, _patch_root):
        from engine.skills.builtin.recovery_skills import restore_database
        result = json.loads(restore_database("C:\\nonexistent.db", "simulation"))
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_restore_invalid_sqlite_returns_error(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import restore_database
        bad_file = project_root / "backups" / "corrupt.db"
        bad_file.write_text("not a database", encoding="utf-8")
        result = json.loads(restore_database(str(bad_file), "simulation"))
        assert result["ok"] is False
        assert "Invalid SQLite" in result["error"]

    def test_restore_unknown_db_returns_error(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import restore_database
        backup = project_root / "backups" / "test.db"
        _make_sqlite_db(backup)
        result = json.loads(restore_database(str(backup), "unknown_db"))
        assert result["ok"] is False
        assert "Unknown database" in result["error"]


# ── analyze_error_log ────────────────────────────────────────────────


class TestAnalyzeErrorLog:
    def test_finds_recent_errors(self, _patch_root):
        from engine.skills.builtin.recovery_skills import analyze_error_log
        result = json.loads(analyze_error_log(hours=2))
        assert result["ok"] is True
        assert result["total_errors"] >= 2
        assert result["files_scanned"] >= 1
        assert len(result["top_modules"]) > 0

    def test_handles_empty_logs_dir(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import analyze_error_log
        # Remove all log files
        for f in (project_root / "logs").iterdir():
            f.unlink()
        result = json.loads(analyze_error_log())
        assert result["ok"] is True
        assert "No log files" in result.get("summary", "")

    def test_handles_missing_logs_dir(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import analyze_error_log
        import shutil
        shutil.rmtree(project_root / "logs")
        result = json.loads(analyze_error_log())
        assert result["ok"] is True
        assert "No logs directory" in result["summary"]

    def test_filters_by_service(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import analyze_error_log
        # Create a service-specific log
        _make_log_file(project_root / "logs" / "nexus.log", hours_ago=0.25)
        result = json.loads(analyze_error_log(service="nexus", hours=1))
        assert result["ok"] is True
        assert result["files_scanned"] == 1

    def test_output_within_length_limit(self, _patch_root):
        from engine.skills.builtin.recovery_skills import analyze_error_log
        result = analyze_error_log(hours=48)
        assert len(result) <= 2000


# ── config_snapshot ──────────────────────────────────────────────────


class TestConfigSnapshot:
    def test_creates_snapshot(self, _patch_root):
        from engine.skills.builtin.recovery_skills import config_snapshot
        result = json.loads(config_snapshot())
        assert result["ok"] is True
        assert Path(result["snapshot_path"]).exists()
        assert result["size_kb"] > 0

    def test_creates_snapshot_with_label(self, _patch_root):
        from engine.skills.builtin.recovery_skills import config_snapshot
        result = json.loads(config_snapshot(label="pre_upgrade"))
        assert result["ok"] is True
        assert "pre_upgrade" in result["snapshot_path"]

    def test_prunes_old_snapshots(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import config_snapshot

        backup_dir = project_root / "backups"
        # Pre-create 7 config snapshots
        for i in range(7):
            ts = f"20240101_{i:06d}"
            path = backup_dir / f"config_{ts}.yaml"
            path.write_text("old", encoding="utf-8")

        result = json.loads(config_snapshot())
        assert result["ok"] is True

        remaining = list(backup_dir.glob("config_*.yaml"))
        assert len(remaining) <= 5

    def test_missing_config_returns_error(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import config_snapshot
        (project_root / "config" / "default.yaml").unlink()
        result = json.loads(config_snapshot())
        assert result["ok"] is False
        assert "not found" in result["error"]


# ── config_rollback ──────────────────────────────────────────────────


class TestConfigRollback:
    def test_rollback_to_latest_snapshot(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import config_rollback

        # Create a snapshot manually
        snapshot = project_root / "backups" / "config_20240601_120000.yaml"
        snapshot.write_text("restored: true\n", encoding="utf-8")

        result = json.loads(config_rollback())
        assert result["ok"] is True
        assert result["pre_rollback_backup"] is not None

        # Verify config was replaced
        config_text = (project_root / "config" / "default.yaml").read_text()
        assert "restored: true" in config_text

    def test_rollback_no_snapshots_returns_error(self, _patch_root, project_root):
        from engine.skills.builtin.recovery_skills import config_rollback
        # Remove any snapshots
        for f in (project_root / "backups").glob("config_*.yaml"):
            f.unlink()
        result = json.loads(config_rollback())
        assert result["ok"] is False
        assert "No config snapshots" in result["error"]


# ── system_diagnostics ───────────────────────────────────────────────


class TestSystemDiagnostics:
    @patch("engine.skills.builtin.recovery_skills._port_registry")
    @patch("engine.skills.builtin.recovery_skills._get_gpu_info")
    def test_returns_formatted_report(self, mock_gpu, mock_reg, _patch_root):
        from engine.skills.builtin.recovery_skills import system_diagnostics

        mock_gpu.return_value = {"available": False}
        registry = MagicMock()
        registry._ports = {"lmstudio": 1234}
        registry.get.side_effect = lambda s, d=None: {"lmstudio": 1234, "nexus": 8700, "hub": 8500, "tts": 8600, "comfyui": 8188}.get(s, d)
        mock_reg.return_value = registry

        with patch("urllib.request.urlopen", side_effect=Exception("offline")):
            result_str = system_diagnostics()

        result = json.loads(result_str)
        assert isinstance(result, dict)
        assert "lmstudio" in result
        assert "disk" in result
        assert "services" in result
        assert "gpu" in result

    @patch("engine.skills.builtin.recovery_skills._port_registry")
    @patch("engine.skills.builtin.recovery_skills._get_gpu_info")
    def test_returns_string_not_none(self, mock_gpu, mock_reg, _patch_root):
        from engine.skills.builtin.recovery_skills import system_diagnostics

        mock_gpu.return_value = {"available": False}
        registry = MagicMock()
        registry._ports = {}
        registry.get.side_effect = KeyError
        mock_reg.return_value = registry

        with patch("urllib.request.urlopen", side_effect=Exception("offline")):
            result = system_diagnostics()

        assert isinstance(result, str)
        assert len(result) > 0


# ── restart_service ──────────────────────────────────────────────────


class TestRestartService:
    @patch("engine.skills.builtin.recovery_skills._port_registry")
    @patch("subprocess.Popen")
    def test_restart_known_service(self, mock_popen, mock_reg, _patch_root):
        from engine.skills.builtin.recovery_skills import restart_service

        registry = MagicMock()
        registry.get.return_value = 8500
        mock_reg.return_value = registry

        result = json.loads(restart_service("hub"))
        assert result["ok"] is True
        assert result["service"] == "hub"
        assert result["action"] == "restart_initiated"

    @patch("engine.skills.builtin.recovery_skills._port_registry")
    def test_restart_unknown_service(self, mock_reg):
        from engine.skills.builtin.recovery_skills import restart_service

        registry = MagicMock()
        registry.get.side_effect = KeyError("nope")
        mock_reg.return_value = registry

        result = json.loads(restart_service("nonexistent"))
        assert result["ok"] is False
        assert "Unknown service" in result["error"]


# ── health_recover ───────────────────────────────────────────────────


class TestHealthRecover:
    @patch("engine.skills.builtin.recovery_skills._check_port")
    @patch("engine.skills.builtin.recovery_skills._port_registry")
    def test_reports_service_status(self, mock_reg, mock_port):
        from engine.skills.builtin.recovery_skills import health_recover

        registry = MagicMock()
        registry._ports = {"lmstudio": 1234, "nexus": 8700, "hub": 8500, "tts": 8600, "comfyui": 8188}
        registry.get.side_effect = lambda s, d=None: registry._ports.get(s, d)
        mock_reg.return_value = registry
        mock_port.return_value = True

        result = json.loads(health_recover())
        assert result["ok"] is True
        assert result["online"] == 5
        assert result["offline"] == 0

    @patch("engine.skills.builtin.recovery_skills._check_port")
    @patch("engine.skills.builtin.recovery_skills._port_registry")
    def test_single_service_check(self, mock_reg, mock_port):
        from engine.skills.builtin.recovery_skills import health_recover

        registry = MagicMock()
        registry._ports = {"nexus": 8700}
        registry.get.return_value = 8700
        mock_reg.return_value = registry
        mock_port.return_value = True

        result = json.loads(health_recover(service="nexus"))
        assert result["ok"] is True
        assert result["total"] == 1


# ── All skills return strings ────────────────────────────────────────


class TestSkillReturnTypes:
    """Every skill must return a str, never None."""

    def test_backup_database_returns_str(self, _patch_root):
        from engine.skills.builtin.recovery_skills import backup_database
        assert isinstance(backup_database("simulation"), str)

    def test_analyze_error_log_returns_str(self, _patch_root):
        from engine.skills.builtin.recovery_skills import analyze_error_log
        assert isinstance(analyze_error_log(), str)

    def test_config_snapshot_returns_str(self, _patch_root):
        from engine.skills.builtin.recovery_skills import config_snapshot
        assert isinstance(config_snapshot(), str)

    @patch("engine.skills.builtin.recovery_skills._port_registry")
    @patch("engine.skills.builtin.recovery_skills._get_gpu_info")
    def test_system_diagnostics_returns_str(self, mock_gpu, mock_reg, _patch_root):
        from engine.skills.builtin.recovery_skills import system_diagnostics
        mock_gpu.return_value = {"available": False}
        registry = MagicMock()
        registry._ports = {}
        registry.get.side_effect = KeyError
        mock_reg.return_value = registry
        with patch("urllib.request.urlopen", side_effect=Exception):
            assert isinstance(system_diagnostics(), str)
