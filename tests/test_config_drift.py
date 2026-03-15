"""Tests for engine.nexus.config_drift — drift detection and remediation."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.config_drift import (
    CRITICAL_KEYS,
    ConfigChange,
    ConfigDriftMonitor,
    DriftResult,
    DriftSeverity,
    get_drift_monitor,
    install_config_hooks,
    register_drift_tasks,
)


# ──── Helpers ─────────────────────────────────────────────────────────────────

def _make_monitor(tmp_path):
    """Create a ConfigDriftMonitor backed by a temp SQLite database."""
    db = str(tmp_path / "drift_test.db")
    with patch("engine.nexus.config_drift._get_current_config", return_value={}):
        return ConfigDriftMonitor(db_path=db)


def _make_monitor_with_config(tmp_path, config):
    """Create a monitor while _get_current_config returns *config*."""
    db = str(tmp_path / "drift_test.db")
    with patch("engine.nexus.config_drift._get_current_config", return_value=config):
        return ConfigDriftMonitor(db_path=db)


# ──── TestDriftSeverity ───────────────────────────────────────────────────────


class TestDriftSeverity:
    def test_enum_values_exist(self):
        assert DriftSeverity.INFO is not None
        assert DriftSeverity.WARNING is not None
        assert DriftSeverity.CRITICAL is not None

    def test_string_values_match(self):
        assert DriftSeverity.INFO.value == "info"
        assert DriftSeverity.WARNING.value == "warning"
        assert DriftSeverity.CRITICAL.value == "critical"


# ──── TestConfigChange ────────────────────────────────────────────────────────


class TestConfigChange:
    def test_creation_with_all_fields(self):
        change = ConfigChange(
            key="lmstudio.port",
            old_value=1234,
            new_value=5678,
            change_type="modified",
            severity=DriftSeverity.CRITICAL,
            timestamp=1000.0,
            source="disk",
        )
        assert change.key == "lmstudio.port"
        assert change.old_value == 1234
        assert change.new_value == 5678
        assert change.change_type == "modified"
        assert change.severity == DriftSeverity.CRITICAL
        assert change.auto_remediated is False

    def test_to_dict_serialises_severity(self):
        change = ConfigChange(
            key="a.b",
            old_value="x",
            new_value="y",
            change_type="modified",
            severity=DriftSeverity.WARNING,
            timestamp=1.0,
            source="disk",
        )
        d = change.to_dict()
        assert d["severity"] == "warning"
        assert d["key"] == "a.b"
        assert isinstance(d, dict)

    def test_auto_remediated_flag(self):
        change = ConfigChange(
            key="k",
            old_value=1,
            new_value=2,
            change_type="modified",
            severity=DriftSeverity.INFO,
            timestamp=1.0,
            source="disk",
            auto_remediated=True,
        )
        assert change.auto_remediated is True
        assert change.to_dict()["auto_remediated"] is True

    def test_severity_assignment_levels(self):
        for sev in DriftSeverity:
            change = ConfigChange(
                key="x", old_value=0, new_value=1,
                change_type="modified", severity=sev,
                timestamp=0, source="test",
            )
            assert change.severity is sev


# ──── TestDriftResult ─────────────────────────────────────────────────────────


class TestDriftResult:
    def test_empty_result_no_drift(self):
        result = DriftResult(check_time=1.0, total_changes=0)
        assert result.has_drift is False
        assert result.total_changes == 0
        assert result.drifted_keys == []
        assert result.added_keys == []
        assert result.removed_keys == []
        assert result.type_changes == []

    def test_result_with_changes(self):
        change = ConfigChange(
            key="a", old_value=1, new_value=2,
            change_type="modified", severity=DriftSeverity.INFO,
            timestamp=1.0, source="disk",
        )
        result = DriftResult(
            check_time=1.0,
            total_changes=1,
            drifted_keys=[change],
            has_drift=True,
            severity_summary={"info": 1, "warning": 0, "critical": 0},
        )
        assert result.has_drift is True
        assert result.total_changes == 1
        assert len(result.drifted_keys) == 1

    def test_to_dict_serialisation(self):
        change = ConfigChange(
            key="b", old_value="x", new_value="y",
            change_type="modified", severity=DriftSeverity.WARNING,
            timestamp=2.0, source="disk",
        )
        result = DriftResult(
            check_time=2.0,
            total_changes=1,
            drifted_keys=[change],
            has_drift=True,
            severity_summary={"info": 0, "warning": 1, "critical": 0},
            baseline_hash="abc",
            current_hash="def",
        )
        d = result.to_dict()
        assert d["has_drift"] is True
        assert d["total_changes"] == 1
        assert d["baseline_hash"] == "abc"
        assert len(d["drifted_keys"]) == 1
        assert d["drifted_keys"][0]["severity"] == "warning"

    def test_summary_no_drift(self):
        result = DriftResult(check_time=1.0, total_changes=0, has_drift=False)
        assert result.summary() == "No configuration drift detected."

    def test_summary_with_drift(self):
        change = ConfigChange(
            key="port", old_value=80, new_value=8080,
            change_type="modified", severity=DriftSeverity.CRITICAL,
            timestamp=1.0, source="disk",
        )
        result = DriftResult(
            check_time=1.0,
            total_changes=1,
            drifted_keys=[change],
            has_drift=True,
            severity_summary={"critical": 1, "warning": 0, "info": 0},
        )
        s = result.summary()
        assert "1 change(s)" in s
        assert "CRITICAL: 1" in s
        assert "port" in s

    def test_severity_summary_counts(self):
        result = DriftResult(
            check_time=1.0,
            total_changes=3,
            has_drift=True,
            severity_summary={"critical": 1, "warning": 1, "info": 1},
        )
        assert result.severity_summary["critical"] == 1
        assert result.severity_summary["warning"] == 1
        assert result.severity_summary["info"] == 1


# ──── TestConfigDriftMonitor ──────────────────────────────────────────────────


class TestConfigDriftMonitor:
    def test_init_creates_tables(self, tmp_path):
        monitor = _make_monitor(tmp_path)
        conn = monitor._get_conn()
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "config_baselines" in tables
        assert "config_changes" in tables
        assert "drift_checks" in tables
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_store_baseline_returns_id(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"a": 1, "b": 2}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        bid = monitor.store_baseline(label="test_label")
        assert isinstance(bid, str)
        assert len(bid) == 36  # UUID
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_store_baseline_stores_snapshot(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"server": {"port": 1234}}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        bid = monitor.store_baseline()
        baseline = monitor.get_baseline(bid)
        assert baseline == {"server": {"port": 1234}}
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_get_baseline_latest(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"v": 1}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline(label="first")
        mock_cfg.return_value = {"v": 2}
        monitor.store_baseline(label="second")
        latest = monitor.get_baseline()
        assert latest == {"v": 2}
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_get_baseline_specific_id(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"v": 1}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        bid = monitor.store_baseline(label="specific")
        mock_cfg.return_value = {"v": 999}
        monitor.store_baseline(label="later")
        result = monitor.get_baseline(bid)
        assert result == {"v": 1}
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_check_drift_no_drift(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"a": 1}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        result = monitor.check_drift()
        assert result.has_drift is False
        assert result.total_changes == 0
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_check_drift_detects_modified(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"x": 10}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        mock_cfg.return_value = {"x": 99}
        result = monitor.check_drift()
        assert result.has_drift is True
        assert len(result.drifted_keys) == 1
        assert result.drifted_keys[0].key == "x"
        assert result.drifted_keys[0].old_value == 10
        assert result.drifted_keys[0].new_value == 99
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_check_drift_detects_added(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"a": 1}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        mock_cfg.return_value = {"a": 1, "b": 2}
        result = monitor.check_drift()
        assert result.has_drift is True
        assert len(result.added_keys) == 1
        assert result.added_keys[0].key == "b"
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_check_drift_detects_removed(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"a": 1, "b": 2}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        mock_cfg.return_value = {"a": 1}
        result = monitor.check_drift()
        assert result.has_drift is True
        assert len(result.removed_keys) == 1
        assert result.removed_keys[0].key == "b"
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_check_drift_detects_type_change(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"port": 1234}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        mock_cfg.return_value = {"port": "1234"}
        result = monitor.check_drift()
        assert result.has_drift is True
        assert len(result.type_changes) == 1
        assert result.type_changes[0].change_type == "type_changed"
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_check_drift_critical_severity_for_critical_keys(
        self, mock_cfg, mock_nexus, tmp_path
    ):
        critical_key = next(iter(CRITICAL_KEYS))
        mock_cfg.return_value = {critical_key: "old"}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        # Store baseline with flat key (flatten won't recurse a non-dict)
        monitor.store_baseline()
        mock_cfg.return_value = {critical_key: "new"}
        result = monitor.check_drift()
        assert result.has_drift is True
        all_changes = (
            result.drifted_keys + result.added_keys
            + result.removed_keys + result.type_changes
        )
        critical_changes = [c for c in all_changes if c.severity == DriftSeverity.CRITICAL]
        assert len(critical_changes) >= 1

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_check_drift_info_severity_for_noncritical(
        self, mock_cfg, mock_nexus, tmp_path
    ):
        mock_cfg.return_value = {"my_custom_setting": "a"}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        mock_cfg.return_value = {"my_custom_setting": "b"}
        result = monitor.check_drift()
        assert result.has_drift is True
        assert result.drifted_keys[0].severity == DriftSeverity.INFO

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_get_drift_history(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"k": 1}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        monitor.check_drift()
        mock_cfg.return_value = {"k": 2}
        monitor.check_drift()
        history = monitor.get_drift_history(limit=10)
        assert len(history) >= 2
        assert "total_changes" in history[0]
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_get_change_log_returns_changes(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"k": 1}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        mock_cfg.return_value = {"k": 2}
        monitor.check_drift()
        log = monitor.get_change_log()
        assert len(log) >= 1
        assert log[0]["key"] == "k"
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_get_change_log_filters_by_key(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"a": 1, "b": 2}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        mock_cfg.return_value = {"a": 10, "b": 20}
        monitor.check_drift()
        log_a = monitor.get_change_log(key="a")
        log_b = monitor.get_change_log(key="b")
        assert all(entry["key"] == "a" for entry in log_a)
        assert all(entry["key"] == "b" for entry in log_b)
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    @patch("engine.nexus.config_drift._get_config_manager")
    def test_rollback_key_reverts_value(
        self, mock_mgr, mock_cfg, mock_nexus, tmp_path
    ):
        cfg_mock = MagicMock()
        cfg_mock.get.return_value = "drifted_val"
        mock_mgr.return_value = cfg_mock

        mock_cfg.return_value = {"port": 1234}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()

        ok = monitor.rollback_key("port")
        assert ok is True
        cfg_mock.set.assert_called_once_with("port", 1234)
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    @patch("engine.nexus.config_drift._get_config_manager")
    def test_rollback_all_reverts_drifted(
        self, mock_mgr, mock_cfg, mock_nexus, tmp_path
    ):
        cfg_mock = MagicMock()
        cfg_mock.get.return_value = "old"
        mock_mgr.return_value = cfg_mock

        mock_cfg.return_value = {"a": 1, "b": 2}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        mock_cfg.return_value = {"a": 99, "b": 88}
        count = monitor.rollback_all()
        assert count == 2
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_record_change_stores_event(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.record_change("test.key", "old", "new", source="runtime_set")
        log = monitor.get_change_log(key="test.key")
        assert len(log) == 1
        assert log[0]["change_type"] == "modified"
        assert log[0]["source"] == "runtime_set"
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_get_health_returns_status(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"x": 1}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        health = monitor.get_health()
        assert "status" in health
        assert health["status"] in ("healthy", "drifted", "critical")
        assert "db_path" in health
        monitor.close()

    def test_flatten_dict_nested(self):
        d = {"a": {"b": {"c": 1}}, "d": 2}
        flat = ConfigDriftMonitor._flatten_dict(d)
        assert flat == {"a.b.c": 1, "d": 2}

    def test_compute_hash_consistent(self):
        config = {"z": 1, "a": 2}
        h1 = ConfigDriftMonitor._compute_hash(config)
        h2 = ConfigDriftMonitor._compute_hash(config)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_compute_hash_differs_for_different_configs(self):
        h1 = ConfigDriftMonitor._compute_hash({"a": 1})
        h2 = ConfigDriftMonitor._compute_hash({"a": 2})
        assert h1 != h2

    def test_classify_severity_critical_key(self, tmp_path):
        monitor = _make_monitor(tmp_path)
        sev = monitor._classify_severity("lmstudio.port", "modified")
        assert sev == DriftSeverity.CRITICAL
        monitor.close()

    def test_classify_severity_type_changed(self, tmp_path):
        monitor = _make_monitor(tmp_path)
        sev = monitor._classify_severity("my_random_key", "type_changed")
        assert sev == DriftSeverity.WARNING
        monitor.close()

    def test_classify_severity_removed(self, tmp_path):
        monitor = _make_monitor(tmp_path)
        sev = monitor._classify_severity("my_random_key", "removed")
        assert sev == DriftSeverity.WARNING
        monitor.close()

    def test_classify_severity_warning_prefix(self, tmp_path):
        monitor = _make_monitor(tmp_path)
        sev = monitor._classify_severity("comms.some_key", "modified")
        assert sev == DriftSeverity.WARNING
        monitor.close()

    def test_classify_severity_info_default(self, tmp_path):
        monitor = _make_monitor(tmp_path)
        sev = monitor._classify_severity("unrelated.key", "modified")
        assert sev == DriftSeverity.INFO
        monitor.close()


# ──── TestInstallConfigHooks ──────────────────────────────────────────────────


class TestInstallConfigHooks:
    @patch("engine.nexus.config_drift._get_config_manager")
    @patch("engine.nexus.config_drift.get_drift_monitor")
    def test_wraps_config_set(self, mock_get_mon, mock_mgr):
        cfg_mock = MagicMock()
        cfg_mock.set._drift_hooked = False
        mock_mgr.return_value = cfg_mock
        monitor = MagicMock()
        mock_get_mon.return_value = monitor
        install_config_hooks(monitor=monitor)
        assert cfg_mock.set._drift_hooked is True

    @patch("engine.nexus.config_drift._get_config_manager")
    @patch("engine.nexus.config_drift.get_drift_monitor")
    def test_original_set_still_called(self, mock_get_mon, mock_mgr):
        cfg_mock = MagicMock()
        cfg_mock.set._drift_hooked = False
        original_set = cfg_mock.set
        mock_mgr.return_value = cfg_mock
        monitor = MagicMock()
        mock_get_mon.return_value = monitor

        install_config_hooks(monitor=monitor)
        # The new set should be a wrapper
        wrapped = cfg_mock.set
        cfg_mock.get.return_value = "old"
        wrapped("test.path", "new_val")
        original_set.assert_called_once_with("test.path", "new_val")

    @patch("engine.nexus.config_drift._get_config_manager")
    @patch("engine.nexus.config_drift.get_drift_monitor")
    def test_changes_recorded_via_monitor(self, mock_get_mon, mock_mgr):
        cfg_mock = MagicMock()
        cfg_mock.set._drift_hooked = False
        cfg_mock.get.return_value = "old_value"
        mock_mgr.return_value = cfg_mock
        monitor = MagicMock()
        mock_get_mon.return_value = monitor

        install_config_hooks(monitor=monitor)
        wrapped = cfg_mock.set
        wrapped("my.key", "new_value")
        monitor.record_change.assert_called_once_with(
            "my.key", "old_value", "new_value", source="runtime_set"
        )


# ──── TestRegisterDriftTasks ──────────────────────────────────────────────────


class TestRegisterDriftTasks:
    @patch("engine.nexus.config_drift.get_drift_monitor")
    def test_registers_two_tasks(self, mock_get_mon):
        monitor = MagicMock()
        mock_get_mon.return_value = monitor

        mock_daemon = MagicMock()
        with patch(
            "engine.nexus.scheduler_daemon.TaskSchedulerDaemon",
            return_value=mock_daemon,
        ):
            register_drift_tasks(monitor=monitor)
        assert mock_daemon.register.call_count == 2
        task_ids = [call.kwargs["task_id"] for call in mock_daemon.register.call_args_list]
        assert "config_drift_check" in task_ids
        assert "config_baseline_refresh" in task_ids

    def test_handles_scheduler_unavailable(self):
        """register_drift_tasks should not raise when scheduler is absent."""
        monitor = MagicMock()
        with patch(
            "engine.nexus.config_drift.get_drift_monitor",
            return_value=monitor,
        ):
            with patch.dict(
                "sys.modules",
                {"engine.nexus.scheduler_daemon": None},
            ):
                # Should not raise
                register_drift_tasks(monitor=monitor)

    @patch("engine.nexus.config_drift.get_drift_monitor")
    def test_uses_default_monitor_when_none(self, mock_get_mon):
        monitor = MagicMock()
        mock_get_mon.return_value = monitor
        mock_daemon = MagicMock()
        with patch(
            "engine.nexus.scheduler_daemon.TaskSchedulerDaemon",
            return_value=mock_daemon,
        ):
            register_drift_tasks(monitor=None)
        mock_get_mon.assert_called_once()


# ──── TestSingleton ───────────────────────────────────────────────────────────


class TestSingleton:
    @patch("engine.nexus.config_drift._get_current_config", return_value={})
    def test_get_drift_monitor_returns_same_instance(self, _mock_cfg, tmp_path):
        import engine.nexus.config_drift as mod

        mod._monitor = None  # Reset singleton
        db = str(tmp_path / "singleton.db")
        m1 = get_drift_monitor(db_path=db)
        m2 = get_drift_monitor(db_path=db)
        assert m1 is m2
        m1.close()
        mod._monitor = None  # Cleanup

    @patch("engine.nexus.config_drift._get_current_config", return_value={})
    def test_thread_safe_creation(self, _mock_cfg, tmp_path):
        import engine.nexus.config_drift as mod

        mod._monitor = None
        db = str(tmp_path / "threaded.db")
        results = []

        def get():
            results.append(get_drift_monitor(db_path=db))

        threads = [threading.Thread(target=get) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r is results[0] for r in results)
        results[0].close()
        mod._monitor = None


# ──── TestEdgeCases ───────────────────────────────────────────────────────────


class TestEdgeCases:
    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_empty_config(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        bid = monitor.store_baseline()
        assert isinstance(bid, str)
        result = monitor.check_drift()
        assert result.has_drift is False
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_deeply_nested_config(self, mock_cfg, mock_nexus, tmp_path):
        deep = {"l1": {"l2": {"l3": {"l4": {"l5": {"leaf": "val"}}}}}}
        mock_cfg.return_value = deep
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        flat = monitor._flatten_dict(deep)
        assert "l1.l2.l3.l4.l5.leaf" in flat
        assert flat["l1.l2.l3.l4.l5.leaf"] == "val"
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_config_with_lists(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"items": [1, 2, 3]}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        mock_cfg.return_value = {"items": [1, 2, 3, 4]}
        result = monitor.check_drift()
        assert result.has_drift is True
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_none_values(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"key": None}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        monitor.store_baseline()
        mock_cfg.return_value = {"key": "value"}
        result = monitor.check_drift()
        assert result.has_drift is True
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    def test_unicode_values(self, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {"greeting": "こんにちは", "emoji": "🚀"}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        bid = monitor.store_baseline()
        baseline = monitor.get_baseline(bid)
        assert baseline["greeting"] == "こんにちは"
        assert baseline["emoji"] == "🚀"
        monitor.close()

    @patch("engine.nexus.config_drift._nexus_store")
    @patch("engine.nexus.config_drift._get_current_config")
    @patch("engine.nexus.config_drift._get_config_manager")
    def test_rollback_when_no_baseline(self, mock_mgr, mock_cfg, mock_nexus, tmp_path):
        mock_cfg.return_value = {}
        monitor = ConfigDriftMonitor(db_path=str(tmp_path / "t.db"))
        ok = monitor.rollback_key("nonexistent.key")
        assert ok is False
        monitor.close()
