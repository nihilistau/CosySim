"""Tests for engine.skills.builtin.lifecycle_mgmt_skills — 10 MCP lifecycle management skills."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from engine.skills.builtin import lifecycle_mgmt_skills


# ── Mock dataclasses (used where asdict() is called in skills) ────────


@dataclass
class MockMigrationStatus:
    """Mimics the schema migration status returned by the migration engine."""

    db_name: str = "test_db"
    current_version: int = 3
    pending_count: int = 0
    pending_versions: List[int] = field(default_factory=list)


@dataclass
class MockDatabaseInfo:
    """Mimics a discovered database record returned by the migration engine."""

    name: str = "test_db"
    path: str = "C:\\tmp\\test.db"
    size_bytes: int = 4096
    table_count: int = 5


# ── Patch targets ─────────────────────────────────────────────────────

_MIGRATION_ENGINE = "engine.nexus.schema_migration.get_migration_engine"
_SHUTDOWN_MANAGER = "engine.lifecycle.shutdown_manager.get_shutdown_manager"
_FLUSH_HANDLER = "engine.lifecycle.shutdown_manager.create_database_flush_handler"


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def mock_migration():
    """Provide a mocked migration engine singleton."""
    with patch(_MIGRATION_ENGINE) as mock_get:
        engine = MagicMock()
        mock_get.return_value = engine
        yield engine


@pytest.fixture()
def mock_shutdown():
    """Provide a mocked shutdown manager singleton."""
    with patch(_SHUTDOWN_MANAGER) as mock_get:
        mgr = MagicMock()
        mock_get.return_value = mgr
        yield mgr


# ── Helpers ───────────────────────────────────────────────────────────


def _parse(result: str) -> Dict[str, Any]:
    """Parse a JSON skill result string into a dict."""
    return json.loads(result)


def _make_shutdown_report(reason: str = "test", success: bool = True) -> MagicMock:
    """Build a mock shutdown report with phases."""
    phase_result = MagicMock()
    phase_result.phase.value = "DRAIN"
    phase_result.total_handlers = 2
    phase_result.succeeded = 2
    phase_result.failed = 0
    phase_result.timed_out = 0
    phase_result.duration_ms = 150
    phase_result.errors = []

    report = MagicMock()
    report.reason = reason
    report.success = success
    report.forced = False
    report.total_duration_ms = 300
    report.phases = [phase_result]
    return report


def _make_handler_mock(name: str = "db_flush_test", phase_value: str = "FLUSH") -> MagicMock:
    """Build a mock shutdown handler with standard attributes."""
    handler = MagicMock()
    handler.name = name
    handler.phase.value = phase_value
    handler.priority = 100
    handler.timeout = 30.0
    return handler


# ══════════════════════════════════════════════════════════════════════
# 1. get_schema_status
# ══════════════════════════════════════════════════════════════════════


class TestGetSchemaStatus:
    """Tests for get_schema_status skill."""

    def test_single_db_status(self, mock_migration):
        """Return status for a specific database."""
        mock_migration.get_status.return_value = MockMigrationStatus(
            db_name="nexus", current_version=5, pending_count=0, pending_versions=[]
        )

        result = _parse(lifecycle_mgmt_skills.get_schema_status("nexus"))

        mock_migration.get_status.assert_called_once_with("nexus")
        assert result["db_name"] == "nexus"
        assert result["current_version"] == 5
        assert result["pending_count"] == 0

    def test_all_db_status(self, mock_migration):
        """Return status for all tracked databases when db_name is empty."""
        mock_migration.get_all_status.return_value = {
            "nexus": MockMigrationStatus(db_name="nexus", current_version=5),
            "metrics": MockMigrationStatus(
                db_name="metrics", current_version=2, pending_count=1,
                pending_versions=[3],
            ),
        }

        result = _parse(lifecycle_mgmt_skills.get_schema_status(""))

        mock_migration.get_all_status.assert_called_once()
        assert "nexus" in result
        assert "metrics" in result
        assert result["metrics"]["pending_count"] == 1

    def test_default_param_returns_all(self, mock_migration):
        """Calling with no argument returns all databases."""
        mock_migration.get_all_status.return_value = {}

        result = _parse(lifecycle_mgmt_skills.get_schema_status())

        mock_migration.get_all_status.assert_called_once()
        assert isinstance(result, dict)

    def test_error_returns_error_json(self, mock_migration):
        """Engine failure produces an error payload."""
        mock_migration.get_status.side_effect = RuntimeError("DB locked")

        result = _parse(lifecycle_mgmt_skills.get_schema_status("broken"))

        assert result["error"] is True
        assert "DB locked" in result["message"]
        assert result["action"] == "get_schema_status"


# ══════════════════════════════════════════════════════════════════════
# 2. run_schema_migration
# ══════════════════════════════════════════════════════════════════════


class TestRunSchemaMigration:
    """Tests for run_schema_migration skill."""

    def test_applies_pending_migrations(self, mock_migration):
        """Successfully apply pending versions."""
        mock_migration.run_pending.return_value = [4, 5, 6]

        result = _parse(lifecycle_mgmt_skills.run_schema_migration("nexus"))

        mock_migration.run_pending.assert_called_once_with("nexus")
        assert result["db_name"] == "nexus"
        assert result["applied_versions"] == [4, 5, 6]
        assert result["applied_count"] == 3

    def test_no_pending_migrations(self, mock_migration):
        """When no migrations are pending, applied list is empty."""
        mock_migration.run_pending.return_value = []

        result = _parse(lifecycle_mgmt_skills.run_schema_migration("metrics"))

        assert result["applied_versions"] == []
        assert result["applied_count"] == 0

    def test_migration_failure(self, mock_migration):
        """Migration error returns error payload."""
        mock_migration.run_pending.side_effect = Exception("migration v4 failed")

        result = _parse(lifecycle_mgmt_skills.run_schema_migration("broken_db"))

        assert result["error"] is True
        assert "migration v4 failed" in result["message"]
        assert result["action"] == "run_schema_migration"


# ══════════════════════════════════════════════════════════════════════
# 3. detect_schema_drift
# ══════════════════════════════════════════════════════════════════════


class TestDetectSchemaDrift:
    """Tests for detect_schema_drift skill."""

    def test_single_db_no_drift(self, mock_migration):
        """No drift detected for a clean database."""
        mock_migration.detect_drift.return_value = []

        result = _parse(lifecycle_mgmt_skills.detect_schema_drift("nexus"))

        mock_migration.detect_drift.assert_called_once_with("nexus")
        assert result["db_name"] == "nexus"
        assert result["drift_detected"] is False
        assert result["diff_count"] == 0
        assert result["diffs"] == []

    def test_single_db_with_drift(self, mock_migration):
        """Drift detected reports diffs."""
        mock_migration.detect_drift.return_value = [
            "added column: users.email",
            "dropped table: legacy_logs",
        ]

        result = _parse(lifecycle_mgmt_skills.detect_schema_drift("nexus"))

        assert result["drift_detected"] is True
        assert result["diff_count"] == 2
        assert "added column: users.email" in result["diffs"]

    def test_all_dbs_drift(self, mock_migration):
        """Check drift across all databases."""
        mock_migration.detect_all_drift.return_value = {
            "nexus": ["missing index: idx_entries_title"],
        }

        result = _parse(lifecycle_mgmt_skills.detect_schema_drift(""))

        mock_migration.detect_all_drift.assert_called_once()
        assert result["databases_with_drift"] == 1
        assert result["details"]["nexus"]["drift_detected"] is True
        assert result["details"]["nexus"]["diff_count"] == 1

    def test_all_dbs_no_drift(self, mock_migration):
        """No drift across any database."""
        mock_migration.detect_all_drift.return_value = {}

        result = _parse(lifecycle_mgmt_skills.detect_schema_drift(""))

        assert result["databases_with_drift"] == 0
        assert result["details"] == {}

    def test_drift_error(self, mock_migration):
        """Error during drift detection."""
        mock_migration.detect_drift.side_effect = OSError("file not found")

        result = _parse(lifecycle_mgmt_skills.detect_schema_drift("missing"))

        assert result["error"] is True
        assert "file not found" in result["message"]


# ══════════════════════════════════════════════════════════════════════
# 4. discover_databases
# ══════════════════════════════════════════════════════════════════════


class TestDiscoverDatabases:
    """Tests for discover_databases skill."""

    def test_discovers_multiple_dbs(self, mock_migration):
        """Discover multiple databases with metadata."""
        mock_migration.discover_databases.return_value = [
            MockDatabaseInfo(name="nexus", path="data/nexus.db", size_bytes=8192, table_count=12),
            MockDatabaseInfo(name="metrics", path="data/metrics.db", size_bytes=2048, table_count=3),
        ]

        result = _parse(lifecycle_mgmt_skills.discover_databases())

        assert result["count"] == 2
        assert len(result["databases"]) == 2
        assert result["databases"][0]["name"] == "nexus"
        assert result["databases"][1]["table_count"] == 3

    def test_no_databases_found(self, mock_migration):
        """No databases discovered returns empty list."""
        mock_migration.discover_databases.return_value = []

        result = _parse(lifecycle_mgmt_skills.discover_databases())

        assert result["count"] == 0
        assert result["databases"] == []

    def test_discovery_error(self, mock_migration):
        """Scan failure returns error payload."""
        mock_migration.discover_databases.side_effect = PermissionError("access denied")

        result = _parse(lifecycle_mgmt_skills.discover_databases())

        assert result["error"] is True
        assert "access denied" in result["message"]


# ══════════════════════════════════════════════════════════════════════
# 5. get_migration_history
# ══════════════════════════════════════════════════════════════════════


class TestGetMigrationHistory:
    """Tests for get_migration_history skill."""

    def test_returns_history_entries(self, mock_migration):
        """Return migration history for a database."""
        mock_migration.get_history.return_value = [
            {"version": 3, "description": "add index", "timestamp": "2025-01-01T00:00:00", "status": "applied"},
            {"version": 2, "description": "add column", "timestamp": "2024-12-01T00:00:00", "status": "applied"},
        ]

        result = _parse(lifecycle_mgmt_skills.get_migration_history("nexus"))

        mock_migration.get_history.assert_called_once_with("nexus", limit=20)
        assert result["db_name"] == "nexus"
        assert result["entry_count"] == 2
        assert result["history"][0]["version"] == 3

    def test_custom_limit(self, mock_migration):
        """Limit parameter is passed through."""
        mock_migration.get_history.return_value = [{"version": 1}]

        lifecycle_mgmt_skills.get_migration_history("nexus", limit=5)

        mock_migration.get_history.assert_called_once_with("nexus", limit=5)

    def test_empty_history(self, mock_migration):
        """Database with no migration history."""
        mock_migration.get_history.return_value = []

        result = _parse(lifecycle_mgmt_skills.get_migration_history("fresh_db"))

        assert result["entry_count"] == 0
        assert result["history"] == []

    def test_history_error(self, mock_migration):
        """Error fetching history."""
        mock_migration.get_history.side_effect = ValueError("unknown db")

        result = _parse(lifecycle_mgmt_skills.get_migration_history("unknown"))

        assert result["error"] is True
        assert "unknown db" in result["message"]
        assert result["action"] == "get_migration_history"


# ══════════════════════════════════════════════════════════════════════
# 6. get_shutdown_status
# ══════════════════════════════════════════════════════════════════════


class TestGetShutdownStatus:
    """Tests for get_shutdown_status skill."""

    def test_running_status(self, mock_shutdown):
        """Return current shutdown manager state."""
        mock_shutdown.get_status.return_value = {
            "state": "running",
            "handler_count": 5,
            "phases": {"DRAIN": 1, "FLUSH": 2, "CLOSE": 1, "CLEANUP": 1},
            "signals_installed": True,
        }

        result = _parse(lifecycle_mgmt_skills.get_shutdown_status())

        assert result["state"] == "running"
        assert result["handler_count"] == 5
        assert result["signals_installed"] is True

    def test_shutting_down_status(self, mock_shutdown):
        """Status during active shutdown."""
        mock_shutdown.get_status.return_value = {
            "state": "shutting_down",
            "handler_count": 3,
            "phases": {"DRAIN": 1, "FLUSH": 2},
            "signals_installed": True,
        }

        result = _parse(lifecycle_mgmt_skills.get_shutdown_status())

        assert result["state"] == "shutting_down"

    def test_status_error(self, mock_shutdown):
        """Shutdown manager unavailable."""
        mock_shutdown.get_status.side_effect = RuntimeError("manager not initialized")

        result = _parse(lifecycle_mgmt_skills.get_shutdown_status())

        assert result["error"] is True
        assert "manager not initialized" in result["message"]


# ══════════════════════════════════════════════════════════════════════
# 7. list_shutdown_handlers
# ══════════════════════════════════════════════════════════════════════


class TestListShutdownHandlers:
    """Tests for list_shutdown_handlers skill."""

    def test_returns_handler_list(self, mock_shutdown):
        """Return all registered handlers with metadata."""
        mock_shutdown.get_handler_list.return_value = [
            {"name": "db_flush_nexus", "phase": "FLUSH", "priority": 100, "timeout": 30, "critical": True},
            {"name": "websocket_drain", "phase": "DRAIN", "priority": 50, "timeout": 10, "critical": False},
        ]

        result = _parse(lifecycle_mgmt_skills.list_shutdown_handlers())

        assert result["handler_count"] == 2
        assert result["handlers"][0]["name"] == "db_flush_nexus"
        assert result["handlers"][1]["phase"] == "DRAIN"

    def test_no_handlers(self, mock_shutdown):
        """No handlers registered."""
        mock_shutdown.get_handler_list.return_value = []

        result = _parse(lifecycle_mgmt_skills.list_shutdown_handlers())

        assert result["handler_count"] == 0
        assert result["handlers"] == []

    def test_handler_list_error(self, mock_shutdown):
        """Error listing handlers."""
        mock_shutdown.get_handler_list.side_effect = RuntimeError("internal error")

        result = _parse(lifecycle_mgmt_skills.list_shutdown_handlers())

        assert result["error"] is True
        assert "internal error" in result["message"]


# ══════════════════════════════════════════════════════════════════════
# 8. initiate_graceful_shutdown
# ══════════════════════════════════════════════════════════════════════


class TestInitiateGracefulShutdown:
    """Tests for initiate_graceful_shutdown skill."""

    def test_successful_shutdown(self, mock_shutdown):
        """Complete shutdown with phase report."""
        mock_shutdown.initiate_shutdown.return_value = _make_shutdown_report(
            reason="maintenance window", success=True
        )

        result = _parse(lifecycle_mgmt_skills.initiate_graceful_shutdown("maintenance window"))

        mock_shutdown.initiate_shutdown.assert_called_once_with(reason="maintenance window")
        assert result["status"] == "completed"
        assert result["reason"] == "maintenance window"
        assert result["success"] is True
        assert result["forced"] is False
        assert result["total_duration_ms"] == 300
        assert len(result["phases"]) == 1
        assert result["phases"][0]["phase"] == "DRAIN"
        assert result["phases"][0]["succeeded"] == 2

    def test_already_in_progress(self, mock_shutdown):
        """Concurrent shutdown returns in_progress status."""
        mock_shutdown.initiate_shutdown.return_value = None

        result = _parse(lifecycle_mgmt_skills.initiate_graceful_shutdown("duplicate"))

        assert result["status"] == "in_progress"
        assert "already in progress" in result["message"].lower()

    def test_shutdown_with_failures(self, mock_shutdown):
        """Shutdown completes with handler failures."""
        report = _make_shutdown_report(reason="forced", success=False)
        report.forced = True
        phase = report.phases[0]
        phase.failed = 1
        phase.succeeded = 1
        phase.errors = ["handler timed out: slow_flush"]
        mock_shutdown.initiate_shutdown.return_value = report

        result = _parse(lifecycle_mgmt_skills.initiate_graceful_shutdown("forced"))

        assert result["success"] is False
        assert result["forced"] is True
        assert result["phases"][0]["failed"] == 1
        assert "slow_flush" in result["phases"][0]["errors"][0]

    def test_shutdown_exception(self, mock_shutdown):
        """Shutdown manager throws an exception."""
        mock_shutdown.initiate_shutdown.side_effect = RuntimeError("signal blocked")

        result = _parse(lifecycle_mgmt_skills.initiate_graceful_shutdown("crash"))

        assert result["error"] is True
        assert "signal blocked" in result["message"]


# ══════════════════════════════════════════════════════════════════════
# 9. register_db_shutdown
# ══════════════════════════════════════════════════════════════════════


class TestRegisterDbShutdown:
    """Tests for register_db_shutdown skill."""

    @patch(_FLUSH_HANDLER)
    @patch(_SHUTDOWN_MANAGER)
    @patch(_MIGRATION_ENGINE)
    def test_successful_registration(self, mock_get_engine, mock_get_mgr, mock_create_handler):
        """Register a database for flush at shutdown."""
        engine = MagicMock()
        engine._get_db_path.return_value = "data/nexus.db"
        mock_get_engine.return_value = engine

        handler = _make_handler_mock(name="db_flush_nexus", phase_value="FLUSH")
        mock_create_handler.return_value = handler

        mgr = MagicMock()
        mock_get_mgr.return_value = mgr

        result = _parse(lifecycle_mgmt_skills.register_db_shutdown("nexus"))

        engine._get_db_path.assert_called_once_with("nexus")
        mock_create_handler.assert_called_once()
        mgr.register.assert_called_once_with(handler)
        assert result["registered"] is True
        assert result["handler_name"] == "db_flush_nexus"
        assert result["phase"] == "FLUSH"
        assert result["db_name"] == "nexus"
        assert result["db_path"] == "data/nexus.db"

    @patch(_FLUSH_HANDLER)
    @patch(_SHUTDOWN_MANAGER)
    @patch(_MIGRATION_ENGINE)
    def test_registration_with_none_path(self, mock_get_engine, mock_get_mgr, mock_create_handler):
        """Register succeeds even when db_path is None (db not yet created)."""
        engine = MagicMock()
        engine._get_db_path.return_value = None
        mock_get_engine.return_value = engine

        handler = _make_handler_mock(name="db_flush_future")
        mock_create_handler.return_value = handler

        mgr = MagicMock()
        mock_get_mgr.return_value = mgr

        result = _parse(lifecycle_mgmt_skills.register_db_shutdown("future_db"))

        assert result["registered"] is True
        assert result["db_path"] is None

    @patch(_MIGRATION_ENGINE)
    def test_registration_error(self, mock_get_engine):
        """Migration engine failure during registration."""
        mock_get_engine.side_effect = ImportError("schema_migration not found")

        result = _parse(lifecycle_mgmt_skills.register_db_shutdown("broken"))

        assert result["error"] is True
        assert "schema_migration not found" in result["message"]


# ══════════════════════════════════════════════════════════════════════
# 10. get_system_lifecycle
# ══════════════════════════════════════════════════════════════════════


class TestGetSystemLifecycle:
    """Tests for get_system_lifecycle skill."""

    @patch(_SHUTDOWN_MANAGER)
    @patch(_MIGRATION_ENGINE)
    def test_healthy_system(self, mock_get_engine, mock_get_mgr):
        """Both subsystems healthy, no warnings."""
        engine = MagicMock()
        engine.get_all_status.return_value = {
            "nexus": MockMigrationStatus(db_name="nexus", pending_count=0),
        }
        mock_get_engine.return_value = engine

        mgr = MagicMock()
        mgr.get_status.return_value = {
            "state": "running",
            "handler_count": 4,
            "phases": {"DRAIN": 1, "FLUSH": 2, "CLOSE": 1},
            "signals_installed": True,
        }
        mock_get_mgr.return_value = mgr

        result = _parse(lifecycle_mgmt_skills.get_system_lifecycle())

        assert result["migration"]["tracked_databases"] == 1
        assert result["migration"]["total_pending_migrations"] == 0
        assert result["shutdown"]["state"] == "running"
        assert result["shutdown"]["handler_count"] == 4
        assert result["warnings"] == []

    @patch(_SHUTDOWN_MANAGER)
    @patch(_MIGRATION_ENGINE)
    def test_pending_migrations_warning(self, mock_get_engine, mock_get_mgr):
        """Pending migrations produce a warning."""
        engine = MagicMock()
        engine.get_all_status.return_value = {
            "nexus": MockMigrationStatus(db_name="nexus", pending_count=2),
            "metrics": MockMigrationStatus(db_name="metrics", pending_count=1),
        }
        mock_get_engine.return_value = engine

        mgr = MagicMock()
        mgr.get_status.return_value = {
            "state": "running",
            "handler_count": 2,
            "phases": {"FLUSH": 2},
            "signals_installed": True,
        }
        mock_get_mgr.return_value = mgr

        result = _parse(lifecycle_mgmt_skills.get_system_lifecycle())

        assert result["migration"]["total_pending_migrations"] == 3
        assert result["migration"]["databases_with_pending"] == ["nexus", "metrics"]
        assert any("3 pending" in w for w in result["warnings"])

    @patch(_SHUTDOWN_MANAGER)
    @patch(_MIGRATION_ENGINE)
    def test_shutdown_not_running_warning(self, mock_get_engine, mock_get_mgr):
        """Non-running shutdown state produces a warning."""
        engine = MagicMock()
        engine.get_all_status.return_value = {}
        mock_get_engine.return_value = engine

        mgr = MagicMock()
        mgr.get_status.return_value = {
            "state": "shutting_down",
            "handler_count": 0,
            "phases": {},
            "signals_installed": False,
        }
        mock_get_mgr.return_value = mgr

        result = _parse(lifecycle_mgmt_skills.get_system_lifecycle())

        assert result["shutdown"]["state"] == "shutting_down"
        assert any("shutting_down" in w for w in result["warnings"])

    @patch(_SHUTDOWN_MANAGER)
    @patch(_MIGRATION_ENGINE)
    def test_migration_engine_unavailable(self, mock_get_engine, mock_get_mgr):
        """Migration engine failure is handled gracefully."""
        mock_get_engine.side_effect = ImportError("no module")

        mgr = MagicMock()
        mgr.get_status.return_value = {
            "state": "running",
            "handler_count": 1,
            "phases": {"CLEANUP": 1},
            "signals_installed": True,
        }
        mock_get_mgr.return_value = mgr

        result = _parse(lifecycle_mgmt_skills.get_system_lifecycle())

        assert "error" in result["migration"]
        assert result["shutdown"]["state"] == "running"
        assert any("Migration engine unavailable" in w for w in result["warnings"])

    @patch(_SHUTDOWN_MANAGER)
    @patch(_MIGRATION_ENGINE)
    def test_shutdown_manager_unavailable(self, mock_get_engine, mock_get_mgr):
        """Shutdown manager failure is handled gracefully."""
        engine = MagicMock()
        engine.get_all_status.return_value = {}
        mock_get_engine.return_value = engine

        mock_get_mgr.side_effect = RuntimeError("not initialized")

        result = _parse(lifecycle_mgmt_skills.get_system_lifecycle())

        assert result["migration"]["tracked_databases"] == 0
        assert "error" in result["shutdown"]
        assert any("Shutdown manager unavailable" in w for w in result["warnings"])

    @patch(_SHUTDOWN_MANAGER)
    @patch(_MIGRATION_ENGINE)
    def test_both_subsystems_unavailable(self, mock_get_engine, mock_get_mgr):
        """Both subsystems failing still returns structured JSON."""
        mock_get_engine.side_effect = ImportError("no migration")
        mock_get_mgr.side_effect = ImportError("no shutdown")

        result = _parse(lifecycle_mgmt_skills.get_system_lifecycle())

        assert "error" in result["migration"]
        assert "error" in result["shutdown"]
        assert len(result["warnings"]) == 2
