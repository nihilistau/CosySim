"""Tests for engine.nexus.auto_loop — autonomous improvement loop.

Covers initialisation, task registration, cycle lifecycle, all five scheduler
callbacks (experiment, eval-sweep, training, impact, full-cycle), loop status,
and cycle metrics.  Every external service is mocked; no real HTTP calls or
Nexus/LMStudio connections.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton before and after each test."""
    import engine.nexus.auto_loop as mod
    mod._auto_loop = None
    yield
    mod._auto_loop = None


@pytest.fixture
def auto_loop(tmp_path: Path):
    """Return a fresh AutoLoop backed by a temp database."""
    from engine.nexus.auto_loop import AutoLoop
    return AutoLoop(db_path=str(tmp_path / "test_auto_loop.db"))


@pytest.fixture
def db_conn(auto_loop):
    """Open a read connection to the AutoLoop's backing database."""
    conn = sqlite3.connect(str(auto_loop._db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_cycle(
    auto_loop,
    cycle_type: str = "experiment_execution",
    status: str = "completed",
    offset_h: float = 0,
    result: dict | None = None,
    error: str | None = None,
) -> str:
    """Insert a cycle record directly into the DB and return its cycle_id."""
    import uuid

    cid = f"cycle-{uuid.uuid4().hex[:8]}"
    now = time.time() - offset_h * 3600
    with auto_loop._connect() as conn:
        conn.execute(
            "INSERT INTO cycle_records "
            "(cycle_id, cycle_type, started_at, completed_at, status, result, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                cid,
                cycle_type,
                now - 10,
                now if status != "running" else None,
                status,
                json.dumps(result or {}),
                error,
            ),
        )
        conn.commit()
    return cid


# ===================================================================
# Initialisation
# ===================================================================

class TestInitialisation:
    """AutoLoop constructor, singleton, and database bootstrap."""

    def test_auto_loop_singleton(self, tmp_path: Path):
        from engine.nexus.auto_loop import get_auto_loop
        import engine.nexus.auto_loop as mod
        mod._auto_loop = None

        db = str(tmp_path / "singleton.db")
        a = get_auto_loop(db_path=db)
        b = get_auto_loop(db_path=db)
        assert a is b

    def test_auto_loop_creates_db(self, tmp_path: Path):
        from engine.nexus.auto_loop import AutoLoop
        db = tmp_path / "new.db"
        AutoLoop(db_path=str(db))
        assert db.exists()

    def test_auto_loop_db_tables(self, auto_loop, db_conn):
        tables = {
            r[0]
            for r in db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "cycle_records" in tables
        assert "cycle_metrics" in tables

    def test_auto_loop_thread_safety(self, tmp_path: Path):
        from engine.nexus.auto_loop import get_auto_loop
        import engine.nexus.auto_loop as mod
        mod._auto_loop = None

        db = str(tmp_path / "thread_safe.db")
        instances: list = []

        def _get():
            instances.append(get_auto_loop(db_path=db))

        threads = [threading.Thread(target=_get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(inst is instances[0] for inst in instances)

    def test_auto_loop_custom_db_path(self, tmp_path: Path):
        from engine.nexus.auto_loop import AutoLoop
        custom = tmp_path / "sub" / "custom.db"
        loop = AutoLoop(db_path=str(custom))
        assert Path(loop._db_path).exists()


# ===================================================================
# Task Registration
# ===================================================================

class TestTaskRegistration:
    """register_tasks() and its interaction with the scheduler daemon."""

    def test_register_tasks_count(self, auto_loop):
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as mock_sd:
            mock_sd.return_value = MagicMock()
            assert auto_loop.register_tasks() == 5

    def test_register_tasks_idempotent(self, auto_loop):
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as mock_sd:
            daemon = MagicMock()
            mock_sd.return_value = daemon
            auto_loop.register_tasks()
            auto_loop.register_tasks()
            # Second call also registers 5, but _tasks_registered stays True
            assert daemon.register.call_count == 10  # 5 + 5

    def test_register_tasks_uses_scheduler(self, auto_loop):
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as mock_sd:
            daemon = MagicMock()
            mock_sd.return_value = daemon
            auto_loop.register_tasks()
            assert daemon.register.call_count == 5

    def test_task_ids(self, auto_loop):
        expected_ids = {
            "auto-loop-experiment",
            "auto-loop-eval-sweep",
            "auto-loop-training",
            "auto-loop-impact",
            "auto-loop-full-cycle",
        }
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as mock_sd:
            daemon = MagicMock()
            mock_sd.return_value = daemon
            auto_loop.register_tasks()
            registered = {
                c.kwargs["task_id"] for c in daemon.register.call_args_list
            }
            assert registered == expected_ids

    def test_task_schedules(self, auto_loop):
        expected = {
            "auto-loop-experiment": "every_2h",
            "auto-loop-eval-sweep": "every_30m",
            "auto-loop-training": "every_4h",
            "auto-loop-impact": "every_6h",
            "auto-loop-full-cycle": "daily",
        }
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as mock_sd:
            daemon = MagicMock()
            mock_sd.return_value = daemon
            auto_loop.register_tasks()
            for call in daemon.register.call_args_list:
                tid = call.kwargs["task_id"]
                assert call.kwargs["schedule"] == expected[tid]

    def test_task_callbacks_callable(self, auto_loop):
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as mock_sd:
            daemon = MagicMock()
            mock_sd.return_value = daemon
            auto_loop.register_tasks()
            for call in daemon.register.call_args_list:
                assert callable(call.kwargs["callback"])


# ===================================================================
# Cycle Management
# ===================================================================

class TestCycleManagement:
    """_start_cycle, _complete_cycle, _fail_cycle, and history queries."""

    def test_start_cycle(self, auto_loop, db_conn):
        cycle = auto_loop._start_cycle("test_type")
        assert cycle.status == "running"
        assert cycle.cycle_type == "test_type"
        row = db_conn.execute(
            "SELECT * FROM cycle_records WHERE cycle_id = ?",
            (cycle.cycle_id,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "running"

    def test_complete_cycle(self, auto_loop, db_conn):
        cycle = auto_loop._start_cycle("test_type")
        auto_loop._complete_cycle(cycle, {"key": "value"})
        assert cycle.status == "completed"
        assert cycle.completed_at is not None
        row = db_conn.execute(
            "SELECT * FROM cycle_records WHERE cycle_id = ?",
            (cycle.cycle_id,),
        ).fetchone()
        assert row["status"] == "completed"
        assert json.loads(row["result"]) == {"key": "value"}

    def test_fail_cycle(self, auto_loop, db_conn):
        cycle = auto_loop._start_cycle("test_type")
        auto_loop._fail_cycle(cycle, "boom")
        assert cycle.status == "failed"
        assert cycle.error == "boom"
        row = db_conn.execute(
            "SELECT * FROM cycle_records WHERE cycle_id = ?",
            (cycle.cycle_id,),
        ).fetchone()
        assert row["status"] == "failed"
        assert row["error"] == "boom"

    def test_cycle_id_format(self, auto_loop):
        cycle = auto_loop._start_cycle("x")
        assert cycle.cycle_id.startswith("cycle-")
        assert len(cycle.cycle_id.split("-", 1)[1]) == 8

    def test_cycle_persisted_to_db(self, auto_loop, db_conn):
        auto_loop._start_cycle("alpha")
        auto_loop._start_cycle("beta")
        count = db_conn.execute(
            "SELECT COUNT(*) AS cnt FROM cycle_records"
        ).fetchone()["cnt"]
        assert count == 2

    def test_get_cycle_history(self, auto_loop):
        _insert_cycle(auto_loop, "experiment_execution", "completed", offset_h=1)
        _insert_cycle(auto_loop, "eval_sweep", "completed", offset_h=2)
        history = auto_loop.get_cycle_history()
        assert len(history) == 2

    def test_get_cycle_history_filter_type(self, auto_loop):
        _insert_cycle(auto_loop, "experiment_execution", "completed")
        _insert_cycle(auto_loop, "eval_sweep", "completed")
        history = auto_loop.get_cycle_history(cycle_type="eval_sweep")
        assert len(history) == 1
        assert history[0]["cycle_type"] == "eval_sweep"

    def test_get_cycle_history_limit(self, auto_loop):
        for i in range(10):
            _insert_cycle(auto_loop, "test", "completed", offset_h=i)
        history = auto_loop.get_cycle_history(limit=3)
        assert len(history) == 3


# ===================================================================
# Experiment Execution Callback
# ===================================================================

class TestExperimentCallback:
    """_experiment_execution_callback with mocked executor and tracker."""

    def _patch_both(self):
        """Return a combined context manager patching executor + tracker."""
        return (
            patch("engine.nexus.experiment_executor.get_experiment_executor"),
            patch("engine.nexus.experiment_executor.ExperimentStatus"),
            patch("engine.nexus.impact_tracker.get_impact_tracker"),
            patch("engine.nexus.impact_tracker.ChangeType"),
        )

    def test_experiment_callback_no_pending(self, auto_loop):
        p_exec, p_status, p_track, p_ct = self._patch_both()
        with p_exec as m_exec, p_status as m_status, p_track, p_ct:
            m_status.PENDING = "PENDING"
            m_exec.return_value.list_runs.return_value = []
            result = auto_loop._experiment_execution_callback()
        assert result["action"] == "skipped"

    def test_experiment_callback_executes(self, auto_loop):
        p_exec, p_status, p_track, p_ct = self._patch_both()
        with p_exec as m_exec, p_status as m_status, p_track as m_track, p_ct as m_ct:
            m_status.PENDING = "PENDING"
            m_ct.EXPERIMENT_RESULT = "EXPERIMENT_RESULT"
            m_exec.return_value.list_runs.return_value = [
                {"run_id": "r1", "proposal_id": "p1", "experiment_name": "exp1"}
            ]
            m_exec.return_value.execute_experiment.return_value = {
                "status": "COMPLETED",
                "recommendation": "PROMOTE",
            }
            change_mock = MagicMock()
            change_mock.change_id = "c1"
            m_track.return_value.record_change.return_value = change_mock

            result = auto_loop._experiment_execution_callback()
        assert result["action"] == "executed"
        assert result["run_id"] == "r1"
        m_exec.return_value.execute_experiment.assert_called_once_with("p1")

    def test_experiment_callback_records_impact(self, auto_loop):
        p_exec, p_status, p_track, p_ct = self._patch_both()
        with p_exec as m_exec, p_status as m_status, p_track as m_track, p_ct as m_ct:
            m_status.PENDING = "PENDING"
            m_ct.EXPERIMENT_RESULT = "EXPERIMENT_RESULT"
            m_exec.return_value.list_runs.return_value = [
                {"run_id": "r1", "proposal_id": "p1", "experiment_name": "exp1"}
            ]
            m_exec.return_value.execute_experiment.return_value = {
                "status": "COMPLETED",
                "recommendation": "PROMOTE",
            }
            change_mock = MagicMock()
            change_mock.change_id = "c1"
            m_track.return_value.record_change.return_value = change_mock

            auto_loop._experiment_execution_callback()
        m_track.return_value.record_change.assert_called_once()
        m_track.return_value.finalize_change.assert_called_once_with("c1")

    def test_experiment_callback_handles_failure(self, auto_loop):
        p_exec, p_status, p_track, p_ct = self._patch_both()
        with p_exec as m_exec, p_status as m_status, p_track, p_ct:
            m_status.PENDING = "PENDING"
            m_exec.return_value.list_runs.return_value = [
                {"run_id": "r1", "proposal_id": "p1", "experiment_name": "exp1"}
            ]
            m_exec.return_value.execute_experiment.side_effect = RuntimeError("kaboom")
            result = auto_loop._experiment_execution_callback()
        assert result["action"] == "failed"
        assert "kaboom" in result["error"]

    def test_experiment_callback_records_cycle(self, auto_loop, db_conn):
        p_exec, p_status, p_track, p_ct = self._patch_both()
        with p_exec as m_exec, p_status as m_status, p_track as m_track, p_ct as m_ct:
            m_status.PENDING = "PENDING"
            m_ct.EXPERIMENT_RESULT = "EXPERIMENT_RESULT"
            m_exec.return_value.list_runs.return_value = [
                {"run_id": "r1", "proposal_id": "p1", "experiment_name": "exp1"}
            ]
            m_exec.return_value.execute_experiment.return_value = {
                "status": "COMPLETED",
                "recommendation": "keep",
            }
            change_mock = MagicMock()
            change_mock.change_id = "c1"
            m_track.return_value.record_change.return_value = change_mock

            auto_loop._experiment_execution_callback()
        row = db_conn.execute(
            "SELECT * FROM cycle_records WHERE cycle_type = 'experiment_execution'"
        ).fetchone()
        assert row is not None

    def test_experiment_callback_one_at_time(self, auto_loop):
        p_exec, p_status, p_track, p_ct = self._patch_both()
        with p_exec as m_exec, p_status as m_status, p_track as m_track, p_ct as m_ct:
            m_status.PENDING = "PENDING"
            m_ct.EXPERIMENT_RESULT = "EXPERIMENT_RESULT"
            m_exec.return_value.list_runs.return_value = [
                {"run_id": "r1", "proposal_id": "p1", "experiment_name": "e1"},
                {"run_id": "r2", "proposal_id": "p2", "experiment_name": "e2"},
            ]
            m_exec.return_value.execute_experiment.return_value = {
                "status": "COMPLETED",
                "recommendation": "keep",
            }
            change_mock = MagicMock()
            change_mock.change_id = "cx"
            m_track.return_value.record_change.return_value = change_mock

            auto_loop._experiment_execution_callback()
        m_exec.return_value.execute_experiment.assert_called_once_with("p1")

    def test_experiment_callback_completed_status(self, auto_loop, db_conn):
        p_exec, p_status, p_track, p_ct = self._patch_both()
        with p_exec as m_exec, p_status as m_status, p_track as m_track, p_ct as m_ct:
            m_status.PENDING = "PENDING"
            m_ct.EXPERIMENT_RESULT = "EXPERIMENT_RESULT"
            m_exec.return_value.list_runs.return_value = [
                {"run_id": "r1", "proposal_id": "p1", "experiment_name": "exp1"}
            ]
            m_exec.return_value.execute_experiment.return_value = {
                "status": "COMPLETED",
                "recommendation": "keep",
            }
            change_mock = MagicMock()
            change_mock.change_id = "c1"
            m_track.return_value.record_change.return_value = change_mock

            auto_loop._experiment_execution_callback()
        row = db_conn.execute(
            "SELECT status FROM cycle_records WHERE cycle_type = 'experiment_execution'"
        ).fetchone()
        assert row["status"] == "completed"

    def test_experiment_callback_failed_status(self, auto_loop, db_conn):
        p_exec, p_status, p_track, p_ct = self._patch_both()
        with p_exec as m_exec, p_status as m_status, p_track, p_ct:
            m_status.PENDING = "PENDING"
            m_exec.return_value.list_runs.return_value = [
                {"run_id": "r1", "proposal_id": "p1", "experiment_name": "exp1"}
            ]
            m_exec.return_value.execute_experiment.side_effect = RuntimeError("err")
            auto_loop._experiment_execution_callback()
        row = db_conn.execute(
            "SELECT status FROM cycle_records WHERE cycle_type = 'experiment_execution'"
        ).fetchone()
        assert row["status"] == "failed"


# ===================================================================
# Eval Sweep Callback
# ===================================================================

class TestEvalSweepCallback:
    """_eval_sweep_callback with mocked evaluator and tracker."""

    def test_eval_sweep_calls_auto_check(self, auto_loop):
        with (
            patch("engine.nexus.online_evaluator.get_online_evaluator") as m_eval,
            patch("engine.nexus.impact_tracker.get_impact_tracker") as m_track,
            patch("engine.nexus.impact_tracker.ChangeType") as m_ct,
        ):
            m_ct.MODEL_PROMOTION = "MODEL_PROMOTION"
            m_eval.return_value.auto_check.return_value = []
            auto_loop._eval_sweep_callback()
        m_eval.return_value.auto_check.assert_called_once()

    def test_eval_sweep_counts_promotions(self, auto_loop):
        with (
            patch("engine.nexus.online_evaluator.get_online_evaluator") as m_eval,
            patch("engine.nexus.impact_tracker.get_impact_tracker") as m_track,
            patch("engine.nexus.impact_tracker.ChangeType") as m_ct,
        ):
            m_ct.MODEL_PROMOTION = "MODEL_PROMOTION"
            change_mock = MagicMock()
            change_mock.change_id = "c1"
            m_track.return_value.record_change.return_value = change_mock
            m_eval.return_value.auto_check.return_value = [
                {"session_id": "s1", "decision": "PROMOTE", "metrics_summary": {}},
                {"session_id": "s2", "decision": "PROMOTE", "metrics_summary": {}},
                {"session_id": "s3", "decision": "continue", "metrics_summary": {}},
            ]
            result = auto_loop._eval_sweep_callback()
        assert result["promotions"] == 2

    def test_eval_sweep_counts_rollbacks(self, auto_loop):
        with (
            patch("engine.nexus.online_evaluator.get_online_evaluator") as m_eval,
            patch("engine.nexus.impact_tracker.get_impact_tracker") as m_track,
            patch("engine.nexus.impact_tracker.ChangeType") as m_ct,
        ):
            m_ct.MODEL_PROMOTION = "MODEL_PROMOTION"
            change_mock = MagicMock()
            change_mock.change_id = "cx"
            m_track.return_value.record_change.return_value = change_mock
            m_eval.return_value.auto_check.return_value = [
                {"session_id": "s1", "decision": "ROLLBACK", "metrics_summary": {}},
            ]
            result = auto_loop._eval_sweep_callback()
        assert result["rollbacks"] == 1

    def test_eval_sweep_records_impact(self, auto_loop):
        with (
            patch("engine.nexus.online_evaluator.get_online_evaluator") as m_eval,
            patch("engine.nexus.impact_tracker.get_impact_tracker") as m_track,
            patch("engine.nexus.impact_tracker.ChangeType") as m_ct,
        ):
            m_ct.MODEL_PROMOTION = "MODEL_PROMOTION"
            change_mock = MagicMock()
            change_mock.change_id = "cx"
            m_track.return_value.record_change.return_value = change_mock
            m_eval.return_value.auto_check.return_value = [
                {"session_id": "s1", "decision": "PROMOTE", "metrics_summary": {}},
            ]
            auto_loop._eval_sweep_callback()
        m_track.return_value.record_change.assert_called_once()
        m_track.return_value.finalize_change.assert_called_once_with("cx")

    def test_eval_sweep_no_sessions(self, auto_loop):
        with (
            patch("engine.nexus.online_evaluator.get_online_evaluator") as m_eval,
            patch("engine.nexus.impact_tracker.get_impact_tracker"),
            patch("engine.nexus.impact_tracker.ChangeType"),
        ):
            m_eval.return_value.auto_check.return_value = []
            result = auto_loop._eval_sweep_callback()
        assert result["sessions_checked"] == 0
        assert result["promotions"] == 0
        assert result["rollbacks"] == 0

    def test_eval_sweep_handles_error(self, auto_loop):
        with (
            patch("engine.nexus.online_evaluator.get_online_evaluator") as m_eval,
            patch("engine.nexus.impact_tracker.get_impact_tracker"),
            patch("engine.nexus.impact_tracker.ChangeType"),
        ):
            m_eval.return_value.auto_check.side_effect = RuntimeError("eval boom")
            result = auto_loop._eval_sweep_callback()
        assert result["action"] == "failed"
        assert "eval boom" in result["error"]

    def test_eval_sweep_records_cycle(self, auto_loop, db_conn):
        with (
            patch("engine.nexus.online_evaluator.get_online_evaluator") as m_eval,
            patch("engine.nexus.impact_tracker.get_impact_tracker"),
            patch("engine.nexus.impact_tracker.ChangeType"),
        ):
            m_eval.return_value.auto_check.return_value = []
            auto_loop._eval_sweep_callback()
        row = db_conn.execute(
            "SELECT * FROM cycle_records WHERE cycle_type = 'eval_sweep'"
        ).fetchone()
        assert row is not None
        assert row["status"] == "completed"


# ===================================================================
# Training Check Callback
# ===================================================================

class TestTrainingCheckCallback:
    """_training_check_callback with mocked auto_train module."""

    def test_training_callback_calls_zoo(self, auto_loop):
        with (
            patch("engine.nexus.impact_tracker.get_impact_tracker"),
            patch("engine.nexus.impact_tracker.ChangeType"),
            patch.dict("sys.modules", {"training": MagicMock(), "training.auto_train": MagicMock()}),
        ):
            import sys
            mod = sys.modules["training.auto_train"]
            mod.get_status.return_value = {"candidate_counts": {}}
            mod.check_and_train_all_zoo.return_value = {}

            auto_loop._training_check_callback()
        mod.check_and_train_all_zoo.assert_called_once()

    def test_training_callback_trained(self, auto_loop):
        with (
            patch("engine.nexus.impact_tracker.get_impact_tracker") as m_track,
            patch("engine.nexus.impact_tracker.ChangeType") as m_ct,
            patch.dict("sys.modules", {"training": MagicMock(), "training.auto_train": MagicMock()}),
        ):
            import sys
            mod = sys.modules["training.auto_train"]
            mod.get_status.return_value = {"candidate_counts": {"chat": 100}}
            mod.check_and_train_all_zoo.return_value = {
                "chat": {"action": "trained", "count": 100, "loss": 0.5},
            }
            m_ct.MODEL_PROMOTION = "MODEL_PROMOTION"
            change_mock = MagicMock()
            change_mock.change_id = "c1"
            m_track.return_value.record_change.return_value = change_mock

            result = auto_loop._training_check_callback()
        assert "chat" in result["trained"]

    def test_training_callback_skipped(self, auto_loop):
        with (
            patch("engine.nexus.impact_tracker.get_impact_tracker"),
            patch("engine.nexus.impact_tracker.ChangeType"),
            patch.dict("sys.modules", {"training": MagicMock(), "training.auto_train": MagicMock()}),
        ):
            import sys
            mod = sys.modules["training.auto_train"]
            mod.get_status.return_value = {"candidate_counts": {}}
            mod.check_and_train_all_zoo.return_value = {
                "chat": {"action": "no_dataset"},
            }
            result = auto_loop._training_check_callback()
        assert "chat" in result["skipped"]

    def test_training_callback_records_impact(self, auto_loop):
        with (
            patch("engine.nexus.impact_tracker.get_impact_tracker") as m_track,
            patch("engine.nexus.impact_tracker.ChangeType") as m_ct,
            patch.dict("sys.modules", {"training": MagicMock(), "training.auto_train": MagicMock()}),
        ):
            import sys
            mod = sys.modules["training.auto_train"]
            mod.get_status.return_value = {"candidate_counts": {}}
            mod.check_and_train_all_zoo.return_value = {
                "ds1": {"action": "trained", "count": 50, "loss": 0.3},
                "ds2": {"action": "trained", "count": 80, "loss": 0.2},
            }
            m_ct.MODEL_PROMOTION = "MODEL_PROMOTION"
            change_mock = MagicMock()
            change_mock.change_id = "cx"
            m_track.return_value.record_change.return_value = change_mock

            auto_loop._training_check_callback()
        assert m_track.return_value.record_change.call_count == 2

    def test_training_callback_handles_import_error(self, auto_loop):
        with (
            patch("engine.nexus.impact_tracker.get_impact_tracker"),
            patch("engine.nexus.impact_tracker.ChangeType"),
            patch.dict("sys.modules", {"training": None, "training.auto_train": None}),
        ):
            result = auto_loop._training_check_callback()
        assert result["action"] == "failed"

    def test_training_callback_handles_error(self, auto_loop):
        with (
            patch("engine.nexus.impact_tracker.get_impact_tracker"),
            patch("engine.nexus.impact_tracker.ChangeType"),
            patch.dict("sys.modules", {"training": MagicMock(), "training.auto_train": MagicMock()}),
        ):
            import sys
            mod = sys.modules["training.auto_train"]
            mod.get_status.side_effect = RuntimeError("train err")
            result = auto_loop._training_check_callback()
        assert result["action"] == "failed"
        assert "train err" in result["error"]


# ===================================================================
# Impact Assessment Callback
# ===================================================================

class TestImpactAssessmentCallback:
    """_impact_assessment_callback with mocked impact_tracker."""

    def test_impact_callback_finalizes_pending(self, auto_loop):
        with patch("engine.nexus.impact_tracker.get_impact_tracker") as m_track:
            tracker = m_track.return_value
            tracker.list_changes.return_value = [
                {"change_id": "c1", "impact_computed": False},
                {"change_id": "c2", "impact_computed": False},
                {"change_id": "c3", "impact_computed": True},
            ]
            tracker.get_impact.return_value = []
            result = auto_loop._impact_assessment_callback()
        assert result["pending_finalized"] == 2
        assert tracker.finalize_change.call_count == 2

    def test_impact_callback_counts(self, auto_loop):
        with patch("engine.nexus.impact_tracker.get_impact_tracker") as m_track:
            tracker = m_track.return_value
            tracker.list_changes.return_value = [
                {"change_id": "c1", "impact_computed": False},
            ]
            tracker.get_impact.return_value = []
            result = auto_loop._impact_assessment_callback()
        assert result["pending_finalized"] == 1
        assert result["total_changes_reviewed"] == 1

    def test_impact_callback_severity_distribution(self, auto_loop):
        with patch("engine.nexus.impact_tracker.get_impact_tracker") as m_track:
            tracker = m_track.return_value
            tracker.list_changes.return_value = [
                {"change_id": "c1", "impact_computed": True},
            ]
            tracker.get_impact.return_value = [
                {"severity": "HIGH"},
                {"severity": "LOW"},
                {"severity": "HIGH"},
            ]
            result = auto_loop._impact_assessment_callback()
        dist = result["severity_distribution"]
        assert dist["HIGH"] == 2
        assert dist["LOW"] == 1

    def test_impact_callback_stores_summary(self, auto_loop):
        with (
            patch("engine.nexus.impact_tracker.get_impact_tracker") as m_track,
            patch("engine.nexus.client.get_nexus_client") as m_nexus,
        ):
            tracker = m_track.return_value
            tracker.list_changes.return_value = [
                {"change_id": "c1", "impact_computed": False},
            ]
            tracker.get_impact.return_value = []
            auto_loop._impact_assessment_callback()
        m_nexus.return_value.add_entry.assert_called_once()

    def test_impact_callback_handles_error(self, auto_loop):
        with patch("engine.nexus.impact_tracker.get_impact_tracker") as m_track:
            m_track.return_value.list_changes.side_effect = RuntimeError("impact err")
            result = auto_loop._impact_assessment_callback()
        assert result["action"] == "failed"
        assert "impact err" in result["error"]


# ===================================================================
# Full Cycle Callback
# ===================================================================

class TestFullCycleCallback:
    """_full_cycle_callback — runs all four sub-cycles and aggregates."""

    def _patch_all_callbacks(self, auto_loop):
        """Patch all four sub-callback methods on the instance."""
        auto_loop._experiment_execution_callback = MagicMock(
            return_value={"action": "skipped", "reason": "no_pending_experiments"}
        )
        auto_loop._eval_sweep_callback = MagicMock(
            return_value={"sessions_checked": 0, "promotions": 0, "rollbacks": 0, "continues": 0}
        )
        auto_loop._training_check_callback = MagicMock(
            return_value={"candidates": {}, "trained": [], "skipped": []}
        )
        auto_loop._impact_assessment_callback = MagicMock(
            return_value={"pending_finalized": 0, "total_changes_reviewed": 0, "severity_distribution": {}}
        )

    def test_full_cycle_runs_all_four(self, auto_loop):
        self._patch_all_callbacks(auto_loop)
        with patch("engine.nexus.client.get_nexus_client"):
            auto_loop._full_cycle_callback()
        auto_loop._experiment_execution_callback.assert_called_once()
        auto_loop._eval_sweep_callback.assert_called_once()
        auto_loop._training_check_callback.assert_called_once()
        auto_loop._impact_assessment_callback.assert_called_once()

    def test_full_cycle_collects_results(self, auto_loop):
        self._patch_all_callbacks(auto_loop)
        with patch("engine.nexus.client.get_nexus_client"):
            report = auto_loop._full_cycle_callback()
        assert "experiments" in report["sub_results"]
        assert "eval_sweep" in report["sub_results"]
        assert "training" in report["sub_results"]
        assert "impact" in report["sub_results"]

    def test_full_cycle_stores_report(self, auto_loop):
        self._patch_all_callbacks(auto_loop)
        with patch("engine.nexus.client.get_nexus_client") as m_nexus:
            auto_loop._full_cycle_callback()
        m_nexus.return_value.add_entry.assert_called_once()

    def test_full_cycle_records_cycle(self, auto_loop, db_conn):
        self._patch_all_callbacks(auto_loop)
        with patch("engine.nexus.client.get_nexus_client"):
            auto_loop._full_cycle_callback()
        row = db_conn.execute(
            "SELECT * FROM cycle_records WHERE cycle_type = 'full_cycle'"
        ).fetchone()
        assert row is not None
        assert row["status"] == "completed"

    def test_full_cycle_partial_failure(self, auto_loop, db_conn):
        self._patch_all_callbacks(auto_loop)
        auto_loop._experiment_execution_callback.side_effect = RuntimeError("exp fail")
        with patch("engine.nexus.client.get_nexus_client"):
            report = auto_loop._full_cycle_callback()
        # Remaining three sub-cycles should still have been called
        auto_loop._eval_sweep_callback.assert_called_once()
        auto_loop._training_check_callback.assert_called_once()
        auto_loop._impact_assessment_callback.assert_called_once()
        assert "experiments" in report["errors"]
        row = db_conn.execute(
            "SELECT * FROM cycle_records WHERE cycle_type = 'full_cycle'"
        ).fetchone()
        # Still completes — partial failures are recorded
        assert row["status"] == "completed"


# ===================================================================
# Loop Status
# ===================================================================

class TestLoopStatus:
    """get_loop_status() health derivation and structure."""

    def test_get_loop_status_structure(self, auto_loop):
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as m_sd:
            m_sd.return_value.list_tasks.return_value = []
            status = auto_loop.get_loop_status()
        expected_keys = {
            "loop_registered", "tasks", "recent_cycles",
            "last_experiment", "last_eval_sweep", "last_training",
            "last_impact", "last_full_cycle", "health",
        }
        assert expected_keys.issubset(status.keys())

    def test_loop_status_healthy(self, auto_loop):
        _insert_cycle(auto_loop, "experiment_execution", "completed", offset_h=1)
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as m_sd:
            m_sd.return_value.list_tasks.return_value = []
            status = auto_loop.get_loop_status()
        assert status["health"] == "healthy"

    def test_loop_status_degraded(self, auto_loop):
        _insert_cycle(auto_loop, "experiment_execution", "completed", offset_h=1)
        _insert_cycle(auto_loop, "eval_sweep", "failed", offset_h=0.5)
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as m_sd:
            m_sd.return_value.list_tasks.return_value = []
            status = auto_loop.get_loop_status()
        assert status["health"] == "degraded"

    def test_loop_status_stalled(self, auto_loop):
        # No cycles at all
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as m_sd:
            m_sd.return_value.list_tasks.return_value = []
            status = auto_loop.get_loop_status()
        assert status["health"] == "stalled"

    def test_loop_status_includes_tasks(self, auto_loop):
        auto_loop._tasks_registered = True
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as m_sd:
            m_sd.return_value.list_tasks.return_value = [
                {"id": "auto-loop-experiment", "schedule": "every_2h"},
            ]
            status = auto_loop.get_loop_status()
        assert status["loop_registered"] is True
        assert len(status["tasks"]) == 1


# ===================================================================
# Cycle Metrics
# ===================================================================

class TestCycleMetrics:
    """record_cycle_metric() and get_cycle_metrics()."""

    def test_record_and_get_metrics(self, auto_loop):
        cycle = auto_loop._start_cycle("metrics_test")
        auto_loop.record_cycle_metric(cycle.cycle_id, "duration", 12.5)
        auto_loop.record_cycle_metric(cycle.cycle_id, "items", 42.0)
        metrics = auto_loop.get_cycle_metrics(cycle.cycle_id)
        assert len(metrics) == 2
        names = {m["metric_name"] for m in metrics}
        assert names == {"duration", "items"}

    def test_get_cycle_metrics_empty(self, auto_loop):
        metrics = auto_loop.get_cycle_metrics("nonexistent")
        assert metrics == []

    def test_metric_values(self, auto_loop):
        cycle = auto_loop._start_cycle("mv")
        auto_loop.record_cycle_metric(cycle.cycle_id, "score", 99.9)
        metrics = auto_loop.get_cycle_metrics(cycle.cycle_id)
        assert metrics[0]["metric_value"] == 99.9
        assert metrics[0]["recorded_at"] > 0
