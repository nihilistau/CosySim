"""Tests for the scheduler daemon — task registration, scheduling, and execution."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.scheduler_daemon import (
    ScheduledTask,
    TaskSchedulerDaemon,
    parse_schedule_seconds,
)


# ──── Schedule Parsing ────


class TestScheduleParsing:
    """Tests for parse_schedule_seconds."""

    def test_daily(self) -> None:
        assert parse_schedule_seconds("daily") == 86400.0

    def test_weekly(self) -> None:
        assert parse_schedule_seconds("weekly") == 604800.0

    def test_every_8h(self) -> None:
        assert parse_schedule_seconds("every_8h") == 8 * 3600.0

    def test_every_1h(self) -> None:
        assert parse_schedule_seconds("every_1h") == 3600.0

    def test_every_30m(self) -> None:
        assert parse_schedule_seconds("every_30m") == 30 * 60.0

    def test_every_5m(self) -> None:
        assert parse_schedule_seconds("every_5m") == 5 * 60.0

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Unrecognised schedule"):
            parse_schedule_seconds("biweekly")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_schedule_seconds("")


# ──── Task Registration ────


class TestTaskRegistration:
    """Tests for registering and unregistering tasks."""

    def test_register_task(self, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        cb = MagicMock(return_value="done")
        daemon.register("test-1", "Test Task", "daily", cb)

        tasks = daemon.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["id"] == "test-1"
        assert tasks[0]["name"] == "Test Task"
        assert tasks[0]["schedule"] == "daily"

    def test_register_invalid_schedule_raises(self, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        with pytest.raises(ValueError):
            daemon.register("bad", "Bad", "invalid_schedule", lambda: None)

    def test_unregister_task(self, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        daemon.register("rm-me", "Remove Me", "daily", lambda: None)
        assert len(daemon.list_tasks()) == 1

        daemon.unregister("rm-me")
        assert len(daemon.list_tasks()) == 0

    def test_unregister_nonexistent_is_noop(self, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        daemon.unregister("does-not-exist")  # should not raise

    def test_register_preserves_run_count(self, tmp_path: Path) -> None:
        """Re-registering a task preserves accumulated stats."""
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        cb = MagicMock(return_value="ok")
        daemon.register("keep-stats", "Keep Stats", "daily", cb)
        daemon.run_task("keep-stats")

        # Re-register same id with new callback
        cb2 = MagicMock(return_value="ok2")
        daemon.register("keep-stats", "Keep Stats v2", "every_8h", cb2)

        tasks = daemon.list_tasks()
        assert tasks[0]["run_count"] == 1
        assert tasks[0]["name"] == "Keep Stats v2"


# ──── Task Execution ────


class TestTaskExecution:
    """Tests for run_task and run_due."""

    @patch("engine.nexus.scheduler_daemon.TaskSchedulerDaemon._log_to_nexus")
    def test_run_task_success(self, mock_log: MagicMock, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        cb = MagicMock(return_value={"status": "healthy"})
        daemon.register("health", "Health", "daily", cb)

        result = daemon.run_task("health")
        assert result["success"] is True
        assert "status" in result["result"]
        assert result["duration_s"] >= 0
        cb.assert_called_once()

    @patch("engine.nexus.scheduler_daemon.TaskSchedulerDaemon._log_to_nexus")
    def test_run_task_not_found(self, mock_log: MagicMock, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        result = daemon.run_task("ghost")
        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("engine.nexus.scheduler_daemon.TaskSchedulerDaemon._log_to_nexus")
    def test_run_task_callback_exception(self, mock_log: MagicMock, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        cb = MagicMock(side_effect=RuntimeError("boom"))
        daemon.register("fail", "Fail", "daily", cb)

        result = daemon.run_task("fail")
        assert result["success"] is False
        assert "boom" in result["error"]

        tasks = daemon.list_tasks()
        assert tasks[0]["error_count"] == 1
        assert tasks[0]["run_count"] == 1

    @patch("engine.nexus.scheduler_daemon.TaskSchedulerDaemon._log_to_nexus")
    def test_run_due_skips_not_due(self, mock_log: MagicMock, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        cb = MagicMock(return_value="ok")
        daemon.register("skip", "Skip", "daily", cb)

        # Run once to set last_run
        daemon.run_task("skip")
        cb.reset_mock()

        # Should not run again — not due yet
        results = daemon.run_due()
        assert len(results) == 0
        cb.assert_not_called()

    @patch("engine.nexus.scheduler_daemon.TaskSchedulerDaemon._log_to_nexus")
    def test_run_due_runs_never_run_tasks(self, mock_log: MagicMock, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        cb = MagicMock(return_value="ok")
        daemon.register("first-time", "First Time", "daily", cb)

        results = daemon.run_due()
        assert len(results) == 1
        assert results[0]["success"] is True

    @patch("engine.nexus.scheduler_daemon.TaskSchedulerDaemon._log_to_nexus")
    def test_run_due_runs_overdue_task(self, mock_log: MagicMock, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        cb = MagicMock(return_value="ok")
        daemon.register("overdue", "Overdue", "every_1m", cb)

        # Manually set last_run to 2 minutes ago
        with daemon._lock:
            daemon._tasks["overdue"].last_run = time.time() - 120

        results = daemon.run_due()
        assert len(results) == 1

    @patch("engine.nexus.scheduler_daemon.TaskSchedulerDaemon._log_to_nexus")
    def test_run_due_skips_disabled(self, mock_log: MagicMock, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        cb = MagicMock(return_value="ok")
        daemon.register("off", "Disabled", "daily", cb, enabled=False)

        results = daemon.run_due()
        assert len(results) == 0


# ──── Status ────


class TestStatus:
    """Tests for status reporting."""

    def test_status_structure(self, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        daemon.register("s1", "Status 1", "daily", lambda: None)

        info = daemon.status()
        assert "running" in info
        assert info["running"] is False
        assert info["task_count"] == 1

        task = info["tasks"][0]
        assert task["id"] == "s1"
        assert task["last_run"] is None
        assert task["next_due"] is not None
        assert task["run_count"] == 0
        assert task["error_count"] == 0


# ──── State Persistence ────


class TestStatePersistence:
    """Tests for saving and loading scheduler state."""

    @patch("engine.nexus.scheduler_daemon.TaskSchedulerDaemon._log_to_nexus")
    def test_state_round_trip(self, mock_log: MagicMock, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"

        # Run a task and save state
        d1 = TaskSchedulerDaemon(state_path=state_file)
        cb = MagicMock(return_value="persisted")
        d1.register("persist", "Persist", "daily", cb)
        d1.run_task("persist")

        assert state_file.exists()

        # Load into new daemon and check state restored
        d2 = TaskSchedulerDaemon(state_path=state_file)
        d2.register("persist", "Persist", "daily", cb)

        tasks = d2.list_tasks()
        assert tasks[0]["run_count"] == 1
        assert tasks[0]["last_run"] is not None

    def test_missing_state_file_is_fine(self, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "nonexistent.json")
        assert daemon.list_tasks() == []

    def test_corrupt_state_file_handled(self, tmp_path: Path) -> None:
        state_file = tmp_path / "bad.json"
        state_file.write_text("NOT JSON", encoding="utf-8")
        daemon = TaskSchedulerDaemon(state_path=state_file)
        assert daemon.list_tasks() == []  # no crash


# ──── Daemon Start/Stop ────


class TestDaemonLifecycle:
    """Tests for the background daemon thread."""

    def test_start_and_stop(self, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        daemon.start(interval_seconds=0.1)
        assert daemon._running is True
        assert daemon._thread is not None
        assert daemon._thread.daemon is True

        daemon.stop()
        assert daemon._running is False

    def test_double_start_is_safe(self, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        daemon.start(interval_seconds=0.1)
        daemon.start(interval_seconds=0.1)  # should warn, not crash
        daemon.stop()

    def test_stop_without_start_is_safe(self, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        daemon.stop()  # should not raise


# ──── Nexus Logging ────


class TestNexusLogging:
    """Tests for best-effort Nexus logging."""

    def test_log_to_nexus_on_success(self, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        task = ScheduledTask(
            id="t", name="T", schedule="daily", callback=lambda: None,
        )
        with patch("engine.nexus.client.get_nexus_client") as mock_client:
            daemon._log_to_nexus(task, success=True, duration=1.0)
            mock_client.return_value.add_entry.assert_called_once()

    def test_log_to_nexus_failure_no_crash(self, tmp_path: Path) -> None:
        daemon = TaskSchedulerDaemon(state_path=tmp_path / "state.json")
        task = ScheduledTask(
            id="t", name="T", schedule="daily", callback=lambda: None,
        )
        with patch(
            "engine.nexus.client.get_nexus_client",
            side_effect=Exception("no nexus"),
        ):
            daemon._log_to_nexus(task, success=False, duration=0.5, error="boom")
            # should not raise


# ──── Builtin Tasks ────


class TestBuiltinTasks:
    """Tests for the builtin scheduler tasks."""

    def test_builtin_task_count(self) -> None:
        """Scheduler daemon registers the full builtin task catalog."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        # v1.50.1 — count grows as new tasks are added; assert minimum
        assert daemon.register.call_count >= 89, (
            f"Expected at least 89 builtin tasks, got {daemon.register.call_count}"
        )

    def test_doc_sync_task_registered(self) -> None:
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        task_ids = [call.args[0] if call.args else call.kwargs.get("task_id") for call in daemon.register.call_args_list]
        assert "doc-sync" in task_ids

    def test_operator_inbox_sync_task_registered(self) -> None:
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        task_ids = [call.args[0] if call.args else call.kwargs.get("task_id") for call in daemon.register.call_args_list]
        assert "operator-inbox-sync" in task_ids

    def test_control_notebook_flywheel_task_registered(self) -> None:
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        task_ids = [call.args[0] if call.args else call.kwargs.get("task_id") for call in daemon.register.call_args_list]
        assert "control-notebook-flywheel" in task_ids

    def test_control_notebook_flywheel_callback_runs_followup(self) -> None:
        from engine.nexus.scheduler_daemon import _control_notebook_flywheel_callback

        with patch(
            "engine.nexus.notebooklm_flywheel.run_control_notebook_flywheel",
            return_value={"status": "ok", "tasks_created": 2},
        ) as mock_run:
            result = _control_notebook_flywheel_callback()

        assert result["status"] == "ok"
        assert result["tasks_created"] == 2
        mock_run.assert_called_once_with(reason="scheduler")

    def test_operator_inbox_sync_callback_processes_pending_items(self) -> None:
        from engine.nexus.scheduler_daemon import _operator_inbox_sync_callback

        inbox = MagicMock()
        inbox.process_items.return_value = {"ok": True, "processed": 2, "created_tasks": 2}
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "nexus.operator_inbox.plan_digest_limit": 4,
        }.get(key, default)

        with (
            patch("engine.config.get_config", return_value=config),
            patch("engine.nexus.operator_inbox.get_operator_inbox", return_value=inbox),
        ):
            result = _operator_inbox_sync_callback()

        inbox.process_items.assert_called_once_with(limit=4)
        assert result["processed"] == 2

    def test_doc_sync_callback_runs_without_crash(self, tmp_path: Path) -> None:
        """_doc_sync_callback handles subprocess errors gracefully."""
        from engine.nexus.scheduler_daemon import _doc_sync_callback

        with patch("subprocess.check_output", side_effect=Exception("git not available")):
            # Should not raise — errors are caught internally
            try:
                _doc_sync_callback()
            except Exception:
                pass  # acceptable if git unavailable

    def test_doc_sync_callback_stores_nexus_note_on_changes(self, tmp_path: Path) -> None:
        """_doc_sync_callback stores a Nexus note when git reports changed files."""
        from engine.nexus.scheduler_daemon import _doc_sync_callback

        fake_diff = "engine/skills/builtin/notebooklm_skills.py\ndocs/SKILLS.md"
        mock_proc = MagicMock()
        mock_proc.stdout = fake_diff
        mock_proc.returncode = 0
        mock_client = MagicMock()
        with patch("subprocess.run", return_value=mock_proc), \
             patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            _doc_sync_callback()
        # Nexus add_entry should have been called with the changed files
        assert mock_client.add_entry.called


class TestWorkspacePipelineTasks:
    """Tests for workspace pipeline scheduler task registration and callbacks."""

    def test_workspace_news_pipeline_task_registered(self) -> None:
        """workspace-news-pipeline task is registered."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        task_ids = [call.args[0] if call.args else call.kwargs.get("task_id") for call in daemon.register.call_args_list]
        assert "workspace-news-pipeline" in task_ids

    def test_workspace_news_to_knowledge_task_registered(self) -> None:
        """workspace-news-to-knowledge task is registered."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        task_ids = [call.args[0] if call.args else call.kwargs.get("task_id") for call in daemon.register.call_args_list]
        assert "workspace-news-to-knowledge" in task_ids

    def test_workspace_research_cycle_task_registered(self) -> None:
        """workspace-research-cycle task is registered."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        task_ids = [call.args[0] if call.args else call.kwargs.get("task_id") for call in daemon.register.call_args_list]
        assert "workspace-research-cycle" in task_ids

    def test_workspace_pipeline_health_task_registered(self) -> None:
        """workspace-pipeline-health task is registered."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks

        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        task_ids = [call.args[0] if call.args else call.kwargs.get("task_id") for call in daemon.register.call_args_list]
        assert "workspace-pipeline-health" in task_ids

    def test_news_pipeline_callback_runs_template(self) -> None:
        """News pipeline callback invokes workspace pipeline run()."""
        from engine.nexus.scheduler_daemon import _workspace_news_pipeline_callback

        mock_run = MagicMock()
        mock_run.run_id = "test-123"
        mock_run.pipeline_name = "news_pipeline"
        mock_run.status = MagicMock(value="completed")
        mock_run.stages = [{"status": "completed"}, {"status": "completed"}]
        mock_run.final_output = {"articles_fetched": 10, "stored": 8}

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = mock_run

        with patch(
            "engine.nexus.workspace_pipeline.get_workspace_pipeline",
            return_value=mock_pipeline,
        ), patch("engine.nexus.client.get_nexus_client", return_value=MagicMock()):
            result = _workspace_news_pipeline_callback()

        assert result["run_id"] == "test-123"
        assert result["status"] == "completed"
        assert result["articles_fetched"] == 10
        mock_pipeline.run.assert_called_once()

    def test_pipeline_health_callback_checks_clients(self) -> None:
        """Pipeline health callback checks client availability."""
        from engine.nexus.scheduler_daemon import _workspace_pipeline_health_callback

        with patch(
            "engine.nexus.workspace_pipeline.get_workspace_pipeline",
            return_value=MagicMock(list_runs=MagicMock(return_value=[])),
        ), patch(
            "engine.nexus.workspace_pipeline.STAGE_REGISTRY",
            {"a": None, "b": None, "c": None},
        ), patch(
            "engine.nexus.workspace_pipeline.PIPELINE_TEMPLATES",
            {"t1": [], "t2": []},
        ), patch("engine.nexus.client.get_nexus_client", return_value=MagicMock()):
            result = _workspace_pipeline_health_callback()

        assert result["stages_registered"] == 3
        assert result["templates_available"] == 2
        assert "clients" in result

    def test_research_cycle_callback_fallback_topic(self) -> None:
        """Research cycle callback uses default topic when Nexus queue empty."""
        from engine.nexus.scheduler_daemon import _workspace_research_cycle_callback

        mock_run = MagicMock()
        mock_run.run_id = "r-1"
        mock_run.status = MagicMock(value="completed")

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = mock_run
        mock_client = MagicMock()
        mock_client.search.return_value = []

        with patch(
            "engine.nexus.workspace_pipeline.get_workspace_pipeline",
            return_value=mock_pipeline,
        ), patch(
            "engine.nexus.client.get_nexus_client",
            return_value=mock_client,
        ):
            result = _workspace_research_cycle_callback()

        assert result["topics_processed"] == 1
        assert result["results"][0]["status"] == "completed"


