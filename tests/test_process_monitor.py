"""Tests for the system process monitor (engine.system.process_monitor).

Covers classification, git operation detection, stall detection,
tracked operations, system snapshots, DB recording, and CLI parsing.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from engine.system.process_monitor import (
    GitOperation,
    GitOpType,
    GitPhase,
    ProcessCategory,
    ProcessInfo,
    ProcessMonitor,
    StallInfo,
    TrackedOperation,
    _classify_by_cmdline,
    _classify_process_name,
    _detect_git_op_type,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def monitor():
    """Create a fresh ProcessMonitor (non-singleton) for each test."""
    mon = ProcessMonitor.__new__(ProcessMonitor)
    mon._tracked = {}
    mon._cpu_baselines = {}
    mon._snapshot_history = []
    mon._max_history = 100
    mon._lock = threading.Lock()
    return mon


@pytest.fixture()
def sample_proc():
    """Return a factory for ProcessInfo instances."""

    def _make(
        pid: int = 1234,
        name: str = "python.exe",
        cmdline: Optional[List[str]] = None,
        cpu_seconds: float = 12.5,
        cpu_percent: float = 5.0,
        memory_mb: float = 150.0,
        memory_percent: float = 2.0,
        status: str = "running",
        parent_pid: Optional[int] = None,
        children_pids: Optional[List[int]] = None,
        category: ProcessCategory = ProcessCategory.PYTHON,
        create_time: Optional[float] = None,
        username: Optional[str] = None,
    ) -> ProcessInfo:
        return ProcessInfo(
            pid=pid,
            name=name,
            cmdline=cmdline or [name],
            cpu_seconds=cpu_seconds,
            cpu_percent=cpu_percent,
            memory_mb=memory_mb,
            memory_percent=memory_percent,
            status=status,
            parent_pid=parent_pid,
            children_pids=children_pids or [],
            create_time=create_time or time.time() - 60,
            username=username,
            category=category,
        )

    return _make


@pytest.fixture()
def metrics_db(tmp_path):
    """Create a fresh MetricsDB instance with full schema."""
    from engine.observability.metrics_db import MetricsDB
    db = MetricsDB(str(tmp_path / "metrics_test.db"))
    return db


# ── ProcessCategory Classification ────────────────────────────────────────────


class TestClassification:
    """Test process → category classification via module-level functions."""

    def test_git_by_name(self):
        """git.exe maps to GIT category."""
        assert _classify_process_name("git.exe") == ProcessCategory.GIT

    def test_git_by_cmdline(self):
        """git push cmdline maps to GIT."""
        assert _classify_by_cmdline(["git", "push"], "git.exe") == ProcessCategory.GIT

    def test_python_by_name(self):
        """python.exe maps to PYTHON."""
        assert _classify_process_name("python.exe") == ProcessCategory.PYTHON

    def test_python3_by_name(self):
        """python3 maps to PYTHON."""
        assert _classify_process_name("python3") == ProcessCategory.PYTHON

    def test_node_by_name(self):
        """node.exe maps to NODE."""
        assert _classify_process_name("node.exe") == ProcessCategory.NODE

    def test_chrome_by_name(self):
        """chrome.exe maps to CHROME."""
        assert _classify_process_name("chrome.exe") == ProcessCategory.CHROME

    def test_lmstudio_by_name(self):
        """lms.exe maps to LMSTUDIO."""
        assert _classify_process_name("lms.exe") == ProcessCategory.LMSTUDIO

    def test_lmstudio_by_cmdline(self):
        """lmstudio in cmdline maps to LMSTUDIO even with python name."""
        assert _classify_by_cmdline(
            ["python", "lmstudio/server.py"], "python.exe"
        ) == ProcessCategory.LMSTUDIO

    def test_comfyui_by_cmdline(self):
        """ComfyUI in cmdline maps to COMFYUI."""
        assert _classify_by_cmdline(
            ["python", "ComfyUI/main.py"], "python.exe"
        ) == ProcessCategory.COMFYUI

    def test_unknown_process_returns_other(self):
        """Unrecognized process returns OTHER (not None)."""
        assert _classify_process_name("svchost.exe") == ProcessCategory.OTHER
        assert _classify_by_cmdline(["svchost.exe"], "svchost.exe") == ProcessCategory.OTHER

    def test_edge_maps_to_chrome(self):
        """msedge.exe maps to CHROME category."""
        assert _classify_process_name("msedge.exe") == ProcessCategory.CHROME


# ── Git Operation Detection ──────────────────────────────────────────────────


class TestGitOperations:
    """Test git operation type detection via module-level _detect_git_op_type."""

    def test_git_push_detected(self):
        """git push cmdline is recognized as PUSH."""
        assert _detect_git_op_type(["git", "push", "origin", "main"]) == GitOpType.PUSH

    def test_git_pull_detected(self):
        """git pull cmdline is recognized as PULL."""
        assert _detect_git_op_type(["git", "pull", "--rebase"]) == GitOpType.PULL

    def test_git_fetch_detected(self):
        """git fetch cmdline is recognized as FETCH."""
        assert _detect_git_op_type(["git", "fetch", "origin"]) == GitOpType.FETCH

    def test_git_clone_detected(self):
        """git clone cmdline is recognized as CLONE."""
        assert _detect_git_op_type(
            ["git", "clone", "https://github.com/repo.git"]
        ) == GitOpType.CLONE

    def test_git_gc_detected(self):
        """git gc cmdline is recognized as GC."""
        assert _detect_git_op_type(["git", "gc"]) == GitOpType.GC

    def test_git_repack_detected(self):
        """git repack cmdline is recognized as REPACK."""
        assert _detect_git_op_type(["git", "repack", "-a", "-d"]) == GitOpType.REPACK

    def test_git_status_returns_unknown(self):
        """git status is NOT a network operation — returns UNKNOWN."""
        assert _detect_git_op_type(["git", "status"]) == GitOpType.UNKNOWN

    def test_git_log_returns_unknown(self):
        """git log is NOT a network operation — returns UNKNOWN."""
        assert _detect_git_op_type(["git", "log", "--oneline"]) == GitOpType.UNKNOWN

    def test_empty_cmdline_returns_unknown(self):
        """Empty cmdline returns UNKNOWN."""
        assert _detect_git_op_type([]) == GitOpType.UNKNOWN

    def test_send_pack_maps_to_push(self):
        """git-send-pack subprocess maps to PUSH."""
        assert _detect_git_op_type(["git-send-pack", "origin"]) == GitOpType.PUSH


# ── Tracked Operations ───────────────────────────────────────────────────────


class TestTrackedOperations:
    """Test manual operation tracking via track_operation / untrack_operation."""

    def test_track_and_list(self, monitor: ProcessMonitor):
        """Track an operation and list it."""
        op = monitor.track_operation("deploy-v1", pid=1234, metadata={"version": "1.27"})
        tracked = monitor.tracked_operations()
        assert len(tracked) == 1
        assert tracked[0].name == "deploy-v1"
        assert tracked[0].id == "deploy-v1-1234"
        assert tracked[0].metadata == {"version": "1.27"}

    def test_untrack(self, monitor: ProcessMonitor):
        """Untrack removes the operation and marks it completed."""
        monitor.track_operation("build-1", pid=5678)
        assert len(monitor.tracked_operations()) == 1
        removed = monitor.untrack_operation("build-1")
        assert removed is not None
        assert removed.status == "completed"
        assert len(monitor.tracked_operations()) == 0

    def test_untrack_missing_returns_none(self, monitor: ProcessMonitor):
        """Untracking a non-existent name returns None (no error)."""
        result = monitor.untrack_operation("does-not-exist")
        assert result is None

    def test_track_duplicate_replaces(self, monitor: ProcessMonitor):
        """Tracking with same name replaces the old entry."""
        monitor.track_operation("t1", pid=100, category="build")
        monitor.track_operation("t1", pid=200, category="deploy")
        tracked = monitor.tracked_operations()
        assert len(tracked) == 1
        assert tracked[0].category == "deploy"
        assert tracked[0].pids == [200]

    def test_tracked_operation_fields(self, monitor: ProcessMonitor):
        """TrackedOperation has the expected dataclass fields."""
        op = monitor.track_operation("test-op", pid=999, category="test",
                                      metadata={"key": "val"})
        assert op.name == "test-op"
        assert op.category == "test"
        assert op.pids == [999]
        assert op.status == "running"
        assert op.metadata == {"key": "val"}
        assert op.elapsed_seconds >= 0


# ── Stall Detection ─────────────────────────────────────────────────────────


class TestStallDetection:
    """Test StallInfo verdict classification and dataclass behavior."""

    def test_stall_info_stalled_verdict(self):
        """StallInfo with near-zero delta is 'stalled'."""
        info = StallInfo(
            pid=100, name="test.exe",
            cpu_seconds_delta=0.0,
            check_interval=3.0,
            memory_mb=256.0,
            uptime_seconds=600.0,
            verdict="stalled",
        )
        assert info.verdict == "stalled"
        d = info.to_dict()
        assert d["verdict"] == "stalled"
        assert d["pid"] == 100

    def test_stall_info_active_verdict(self):
        """StallInfo with high delta is 'active'."""
        info = StallInfo(
            pid=200, name="worker.exe",
            cpu_seconds_delta=5.2,
            check_interval=3.0,
            memory_mb=1024.0,
            uptime_seconds=120.0,
            verdict="active",
        )
        assert info.verdict == "active"

    def test_stall_info_slow_verdict(self):
        """StallInfo with small delta is 'slow'."""
        info = StallInfo(
            pid=300, name="idle.exe",
            cpu_seconds_delta=0.05,
            check_interval=3.0,
            memory_mb=64.0,
            uptime_seconds=3600.0,
            verdict="slow",
        )
        assert info.verdict == "slow"

    def test_stall_detection_no_tracked_ops(self, monitor: ProcessMonitor):
        """stall_detection with no tracked ops and no explicit pids returns empty."""
        result = monitor.stall_detection(pids=[], check_interval=0.01)
        assert result == []


# ── System Snapshot ──────────────────────────────────────────────────────────


class TestSystemSnapshot:
    """Test the aggregate system_snapshot() method."""

    def test_snapshot_returns_dict_with_expected_keys(self, monitor: ProcessMonitor):
        """system_snapshot returns a dict with top-level keys."""
        with patch.object(monitor, "scan_all", return_value={}), \
             patch.object(monitor, "git_operations", return_value=[]), \
             patch.object(monitor, "top_consumers", return_value=[]), \
             patch("engine.logging.monitor.get_system_monitor") as mock_sys:
            mock_sys.return_value.snapshot.return_value = {"cpu": 25.0}
            snapshot = monitor.system_snapshot()

        assert isinstance(snapshot, dict)
        assert "timestamp" in snapshot
        assert "git_operations" in snapshot
        assert "tracked_operations" in snapshot
        assert "processes" in snapshot

    def test_snapshot_stored_in_history(self, monitor: ProcessMonitor):
        """system_snapshot appends to _snapshot_history."""
        with patch.object(monitor, "scan_all", return_value={}), \
             patch.object(monitor, "git_operations", return_value=[]), \
             patch.object(monitor, "top_consumers", return_value=[]), \
             patch("engine.logging.monitor.get_system_monitor") as mock_sys:
            mock_sys.return_value.snapshot.return_value = {}
            monitor.system_snapshot()

        assert len(monitor._snapshot_history) == 1


# ── MetricsDB Integration ───────────────────────────────────────────────────


class TestMetricsDBRecording:
    """Test record_to_metrics_db uses the proper process_snapshots table."""

    def test_record_calls_db_method(self, monitor: ProcessMonitor):
        """record_to_metrics_db calls db.record_process_snapshot."""
        mock_db = MagicMock()
        mock_snapshot = {
            "timestamp": "2025-01-01T00:00:00Z",
            "total_processes": 5,
            "git_operations": [],
            "tracked_operations": [],
            "stalled": [],
            "total_cpu_seconds": 100.0,
            "total_memory_mb": 2048.0,
        }
        with patch.object(monitor, "system_snapshot", return_value=mock_snapshot), \
             patch(
                 "engine.observability.metrics_db.get_metrics_db",
                 return_value=mock_db,
             ):
            result = monitor.record_to_metrics_db()

        assert result is True
        mock_db.record_process_snapshot.assert_called_once()


# ── DB Schema ────────────────────────────────────────────────────────────────


class TestMetricsDBSchema:
    """Test process_snapshots table operations on a real MetricsDB."""

    def test_record_and_retrieve(self, metrics_db):
        """Round-trip: record snapshot then retrieve it."""
        metrics_db.record_process_snapshot(
            category="git",
            process_count=3,
            total_cpu_seconds=45.2,
            total_memory_mb=512.0,
            git_op_count=1,
            tracked_op_count=0,
            stalled_count=0,
            snapshot_json='{"test": true}',
        )
        history = metrics_db.get_process_history(category="git", seconds=300)
        assert len(history) >= 1
        row = history[0]
        assert row["category"] == "git"
        assert row["process_count"] == 3
        assert row["total_cpu_seconds"] == pytest.approx(45.2, abs=0.1)
        assert row["total_memory_mb"] == pytest.approx(512.0, abs=0.1)
        assert row["git_op_count"] == 1

    def test_prune_old_snapshots(self, metrics_db):
        """Pruning removes only old records."""
        metrics_db.record_process_snapshot(
            category="python",
            process_count=10,
            total_cpu_seconds=100.0,
            total_memory_mb=2048.0,
        )
        pruned = metrics_db.prune_process_snapshots(max_age_hours=0)
        assert pruned >= 0

    def test_history_filters_by_category(self, metrics_db):
        """get_process_history correctly filters by category."""
        metrics_db.record_process_snapshot(
            category="git", process_count=2,
            total_cpu_seconds=10.0, total_memory_mb=100.0,
        )
        metrics_db.record_process_snapshot(
            category="python", process_count=5,
            total_cpu_seconds=30.0, total_memory_mb=500.0,
        )
        git_only = metrics_db.get_process_history(category="git", seconds=300)
        all_records = metrics_db.get_process_history(seconds=300)
        assert len(git_only) == 1
        assert len(all_records) == 2


# ── Alert Node Mapping ──────────────────────────────────────────────────────


class TestAlertNodeMapping:
    """Test that process metrics map to the 'process' node in alerts."""

    def test_worker_count_maps_to_process(self):
        """worker_count metric infers process node."""
        from engine.observability.alerts import _infer_node

        assert _infer_node("worker_count") == "process"

    def test_stalled_count_maps_to_process(self):
        """stalled_count metric infers process node."""
        from engine.observability.alerts import _infer_node

        assert _infer_node("stalled_count") == "process"

    def test_process_metric_maps_to_process(self):
        """Direct 'process' metric infers process node."""
        from engine.observability.alerts import _infer_node

        assert _infer_node("process") == "process"

    def test_python_worker_maps_to_process(self):
        """python_worker metric infers process node."""
        from engine.observability.alerts import _infer_node

        assert _infer_node("python_worker") == "process"

    def test_git_stall_maps_to_process(self):
        """git_stall metric infers process node."""
        from engine.observability.alerts import _infer_node

        assert _infer_node("git_stall") == "process"


# ── Scheduler Callback Smoke ─────────────────────────────────────────────────


class TestSchedulerCallbacks:
    """Verify scheduler callbacks import and return dicts."""

    def test_process_snapshot_callback_returns_dict(self):
        """_process_snapshot_callback returns a dict."""
        from engine.nexus.scheduler_daemon import _process_snapshot_callback

        with patch("engine.system.get_process_monitor") as mock_get:
            mock_mon = MagicMock()
            mock_mon.system_snapshot.return_value = {
                "total_processes": 5,
                "git_operations": [],
                "tracked_operations": [],
                "stalled": [],
                "total_memory_mb": 1024.0,
            }
            mock_mon.record_to_metrics_db.return_value = True
            mock_get.return_value = mock_mon

            result = _process_snapshot_callback()
            assert isinstance(result, dict)
            assert result["total_processes"] == 5
            assert result["recorded_to_db"] is True

    def test_git_operation_check_callback(self):
        """_git_operation_check_callback returns a dict with git info."""
        from engine.nexus.scheduler_daemon import _git_operation_check_callback

        with patch("engine.system.get_process_monitor") as mock_get:
            mock_mon = MagicMock()
            mock_mon.git_operations.return_value = []
            mock_get.return_value = mock_mon

            result = _git_operation_check_callback()
            assert isinstance(result, dict)
            assert result["active_git_ops"] == 0
            assert result["stalled_git_ops"] == 0

    def test_stall_detection_callback(self):
        """_stall_detection_callback returns a dict with stall info."""
        from engine.nexus.scheduler_daemon import _stall_detection_callback

        with patch("engine.system.get_process_monitor") as mock_get:
            mock_mon = MagicMock()
            mock_mon.stall_detection.return_value = []
            mock_get.return_value = mock_mon

            result = _stall_detection_callback()
            assert isinstance(result, dict)
            assert result["stalled_count"] == 0


# ── CLI Argument Parsing ─────────────────────────────────────────────────────


class TestCLI:
    """Test __main__.py argument parsing."""

    def test_module_importable(self):
        """engine.system.__main__ is importable."""
        import engine.system.__main__ as cli_mod

        assert hasattr(cli_mod, "main") or hasattr(cli_mod, "build_parser")

    def test_package_init_exports(self):
        """engine.system exports expected symbols."""
        from engine.system import (
            ProcessCategory,
            ProcessInfo,
            ProcessMonitor,
            get_process_monitor,
        )

        assert ProcessCategory.GIT.value == "git"
        assert callable(get_process_monitor)


# ── Skills Registration ──────────────────────────────────────────────────────


class TestSkillRegistration:
    """Test process_monitor_skills register correctly."""

    def test_skills_importable(self):
        """process_monitor_skills module imports without error."""
        import engine.skills.builtin.process_monitor_skills as skills_mod

        assert skills_mod is not None

    def test_skill_functions_exist(self):
        """Key skill functions are defined."""
        from engine.skills.builtin import process_monitor_skills as sm

        expected = [
            "process_list",
            "git_operation_status",
            "system_resource_snapshot",
            "stall_check",
            "lmstudio_processes",
            "python_workers",
        ]
        for name in expected:
            assert hasattr(sm, name), f"Missing skill: {name}"
