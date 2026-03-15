"""Tests for engine.skills.builtin.lifecycle_skills — 12 MCP lifecycle skills."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from engine.skills.builtin import lifecycle_skills


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture()
def mock_auto_loop():
    """Provide a mocked AutoLoop singleton."""
    with patch("engine.nexus.auto_loop.get_auto_loop") as mock_get:
        loop = MagicMock()
        mock_get.return_value = loop
        yield loop


@pytest.fixture()
def mock_conversation_sync():
    """Provide a mocked ConversationSync singleton."""
    with patch("engine.nexus.conversation_sync.get_conversation_sync") as mock_get:
        sync = MagicMock()
        mock_get.return_value = sync
        yield sync


@pytest.fixture()
def mock_scheduler_daemon():
    """Provide a mocked SchedulerDaemon singleton."""
    with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as mock_get:
        daemon = MagicMock()
        mock_get.return_value = daemon
        yield daemon


# ── Skill Registration ────────────────────────────────────────


def test_lifecycle_skills_registered():
    """All 12 lifecycle skills are registered in SKILL_REGISTRY."""
    from engine.skills.registry import SKILL_REGISTRY

    lifecycle_pack = SKILL_REGISTRY.get_pack_metas("lifecycle")
    assert len(lifecycle_pack) >= 12


def test_lifecycle_skills_category():
    """All lifecycle skills have SYSTEM category."""
    from engine.skills.registry import SKILL_REGISTRY

    lifecycle = SKILL_REGISTRY.get_pack_metas("lifecycle")
    for s in lifecycle:
        assert str(s.category).endswith("SYSTEM") or s.category == "system"


# ── 1. get_loop_status ────────────────────────────────────────


def test_get_loop_status_returns_string(mock_auto_loop):
    """Happy path: returns formatted status string."""
    mock_auto_loop.get_loop_status.return_value = {
        "loop_registered": True,
        "health": "healthy",
        "tasks": [
            {
                "id": "experiment",
                "name": "Experiment Runner",
                "enabled": True,
                "run_count": 5,
                "error_count": 0,
                "last_run": time.time(),
            }
        ],
        "recent_cycles": [
            {
                "cycle_type": "experiment",
                "status": "completed",
                "started_at": time.time(),
                "duration_s": 12.5,
            }
        ],
    }
    result = lifecycle_skills.get_loop_status()
    assert isinstance(result, str)
    assert "HEALTHY" in result
    assert "Experiment Runner" in result


def test_get_loop_status_handles_import_error():
    """Import error returns a graceful fallback string."""
    with patch(
        "engine.nexus.auto_loop.get_auto_loop",
        side_effect=ImportError("no module"),
    ):
        result = lifecycle_skills.get_loop_status()
    assert isinstance(result, str)
    assert "unavailable" in result.lower()


# ── 2. trigger_experiment_cycle ───────────────────────────────


def test_trigger_experiment_cycle_executed(mock_auto_loop):
    """Experiment cycle returns executed result."""
    mock_auto_loop._experiment_execution_callback.return_value = {
        "action": "executed",
        "run_id": "run-abc",
        "result": {"status": "success", "recommendation": "promote"},
    }
    result = lifecycle_skills.trigger_experiment_cycle()
    assert isinstance(result, str)
    assert "executed" in result.lower()
    assert "run-abc" in result


def test_trigger_experiment_cycle_handles_error():
    """Exception in experiment callback returns error string."""
    with patch(
        "engine.nexus.auto_loop.get_auto_loop",
        side_effect=RuntimeError("boom"),
    ):
        result = lifecycle_skills.trigger_experiment_cycle()
    assert isinstance(result, str)
    assert "failed" in result.lower()


# ── 3. trigger_eval_sweep ─────────────────────────────────────


def test_trigger_eval_sweep_returns_results(mock_auto_loop):
    """Eval sweep returns session counts."""
    mock_auto_loop._eval_sweep_callback.return_value = {
        "sessions_checked": 10,
        "promotions": 2,
        "rollbacks": 1,
        "continues": 7,
    }
    result = lifecycle_skills.trigger_eval_sweep()
    assert isinstance(result, str)
    assert "10" in result
    assert "Promotions" in result


def test_trigger_eval_sweep_handles_error():
    """Exception in eval sweep returns error string."""
    with patch(
        "engine.nexus.auto_loop.get_auto_loop",
        side_effect=RuntimeError("eval crash"),
    ):
        result = lifecycle_skills.trigger_eval_sweep()
    assert isinstance(result, str)
    assert "failed" in result.lower()


# ── 4. trigger_training_cycle ─────────────────────────────────


def test_trigger_training_cycle_returns_results(mock_auto_loop):
    """Training cycle formats per-dataset results."""
    mock_auto_loop._training_check_callback.return_value = {
        "chat_quality": {"status": "trained", "examples": 500, "loss": 0.1234},
        "persona_voice": {"status": "skipped"},
    }
    result = lifecycle_skills.trigger_training_cycle()
    assert isinstance(result, str)
    assert "trained" in result
    assert "0.1234" in result


def test_trigger_training_cycle_handles_error():
    """Exception in training callback returns error string."""
    with patch(
        "engine.nexus.auto_loop.get_auto_loop",
        side_effect=RuntimeError("gpu oom"),
    ):
        result = lifecycle_skills.trigger_training_cycle()
    assert isinstance(result, str)
    assert "failed" in result.lower()


# ── 5. trigger_full_cycle ─────────────────────────────────────


def test_trigger_full_cycle_returns_summary(mock_auto_loop):
    """Full cycle returns summary and sub-results."""
    mock_auto_loop._full_cycle_callback.return_value = {
        "summary": {"total_phases": 3, "succeeded": 3},
        "sub_results": {
            "experiment": {"action": "executed"},
            "eval": {"action": "skipped"},
            "training": {"status": "done"},
        },
        "health": "healthy",
    }
    result = lifecycle_skills.trigger_full_cycle()
    assert isinstance(result, str)
    assert "healthy" in result.lower()
    assert "experiment" in result.lower()


def test_trigger_full_cycle_handles_error():
    """Exception in full cycle returns error string."""
    with patch(
        "engine.nexus.auto_loop.get_auto_loop",
        side_effect=RuntimeError("full cycle crash"),
    ):
        result = lifecycle_skills.trigger_full_cycle()
    assert isinstance(result, str)
    assert "failed" in result.lower()


# ── 6. get_cycle_history ──────────────────────────────────────


def test_get_cycle_history_returns_formatted(mock_auto_loop):
    """History with records is formatted correctly."""
    mock_auto_loop.get_cycle_history.return_value = [
        {
            "cycle_id": "abcdef12-3456",
            "cycle_type": "experiment",
            "status": "completed",
            "started_at": time.time() - 3600,
            "duration_s": 45.2,
            "result": {"runs": 3},
        }
    ]
    result = lifecycle_skills.get_cycle_history()
    assert isinstance(result, str)
    assert "experiment" in result
    assert "Total: 1 cycles" in result


def test_get_cycle_history_empty(mock_auto_loop):
    """Empty history returns descriptive message."""
    mock_auto_loop.get_cycle_history.return_value = []
    result = lifecycle_skills.get_cycle_history(days=3)
    assert isinstance(result, str)
    assert "No cycles recorded" in result
    assert "3 days" in result


# ── 7. get_training_queue_status ──────────────────────────────


def test_get_training_queue_status_formats_datasets():
    """Training queue formats candidate counts vs thresholds."""
    with patch("training.auto_train.get_status") as mock_status:
        mock_status.return_value = {
            "candidate_counts": {"chat": 150, "persona": 30},
            "thresholds": {"chat": 100, "persona": 50},
            "last_train": {},
            "recent_history": [],
            "last_check": time.time(),
        }
        result = lifecycle_skills.get_training_queue_status()
    assert isinstance(result, str)
    assert "READY" in result
    assert "waiting" in result


def test_get_training_queue_status_handles_missing_module():
    """Missing training module returns fallback string."""
    with patch(
        "training.auto_train.get_status",
        side_effect=ImportError("no training module"),
    ):
        result = lifecycle_skills.get_training_queue_status()
    assert isinstance(result, str)
    assert "unavailable" in result.lower()


# ── 8. force_conversation_sync ────────────────────────────────


def test_force_conversation_sync_returns_result(mock_conversation_sync):
    """Successful sync returns processed/created counts."""
    mock_conversation_sync.force_sync.return_value = {
        "nexus_knowledge": {"events_processed": 10, "entries_created": 3},
        "training_data": {"events_processed": 10, "entries_created": 5},
    }
    result = lifecycle_skills.force_conversation_sync()
    assert isinstance(result, str)
    assert "10" in result
    assert "entries created" in result.lower()


def test_force_conversation_sync_handles_error():
    """Exception in sync returns error string."""
    with patch(
        "engine.nexus.conversation_sync.get_conversation_sync",
        side_effect=RuntimeError("db locked"),
    ):
        result = lifecycle_skills.force_conversation_sync()
    assert isinstance(result, str)
    assert "failed" in result.lower()


# ── 9. get_conversation_sync_status ───────────────────────────


def test_get_conversation_sync_status_returns_string(mock_conversation_sync):
    """Sync status is formatted with timestamps and counts."""
    mock_conversation_sync.get_sync_status.return_value = {
        "last_sync_timestamp": time.time() - 600,
        "last_event_id": "evt-42",
        "events_pending": 5,
        "total_synced": 200,
        "recent_syncs": [],
    }
    result = lifecycle_skills.get_conversation_sync_status()
    assert isinstance(result, str)
    assert "evt-42" in result
    assert "200" in result


def test_get_conversation_sync_status_handles_error():
    """Exception returns unavailable string."""
    with patch(
        "engine.nexus.conversation_sync.get_conversation_sync",
        side_effect=RuntimeError("connection refused"),
    ):
        result = lifecycle_skills.get_conversation_sync_status()
    assert isinstance(result, str)
    assert "unavailable" in result.lower()


# ── 10. get_improvement_report ────────────────────────────────


def test_get_improvement_report_aggregates_sources():
    """Report aggregates experiment, eval, impact, and training data."""
    with (
        patch("engine.nexus.experiment_executor.get_experiment_executor") as mock_exec,
        patch("engine.nexus.online_evaluator.get_online_evaluator") as mock_eval,
        patch("engine.nexus.impact_tracker.get_impact_tracker") as mock_impact,
        patch("training.auto_train.get_status") as mock_train,
    ):
        executor = MagicMock()
        executor.run_stats.return_value = {
            "total_runs": 20,
            "success_rate": 0.75,
            "avg_effect_size": 0.05,
        }
        executor.list_runs.return_value = [
            {"status": "completed"},
            {"status": "completed"},
            {"status": "failed"},
        ]
        mock_exec.return_value = executor

        evaluator = MagicMock()
        evaluator.list_sessions.return_value = [
            {"started_at": time.time(), "status": "completed", "decision": "promote"},
        ]
        mock_eval.return_value = evaluator

        tracker = MagicMock()
        tracker.attribution_report.return_value = {
            "total_changes": 15,
            "computed": 10,
            "uncomputed": 5,
            "top_positive": [{"title": "Better prompts", "percentage_delta": 0.12}],
            "top_negative": [],
        }
        mock_impact.return_value = tracker

        mock_train.return_value = {
            "candidate_counts": {"chat": 100},
            "thresholds": {"chat": 100},
            "recent_history": [],
        }

        result = lifecycle_skills.get_improvement_report(days=7)

    assert isinstance(result, str)
    assert "Experiments" in result
    assert "75.0%" in result
    assert "Evaluations" in result
    assert "Impact" in result
    assert "Training" in result


def test_get_improvement_report_handles_partial_failures():
    """Report still renders sections that succeed when others fail."""
    with (
        patch(
            "engine.nexus.experiment_executor.get_experiment_executor",
            side_effect=ImportError("missing"),
        ),
        patch(
            "engine.nexus.online_evaluator.get_online_evaluator",
            side_effect=ImportError("missing"),
        ),
        patch(
            "engine.nexus.impact_tracker.get_impact_tracker",
            side_effect=ImportError("missing"),
        ),
        patch(
            "training.auto_train.get_status",
            side_effect=ImportError("missing"),
        ),
    ):
        result = lifecycle_skills.get_improvement_report(days=7)
    assert isinstance(result, str)
    assert "Subsystem Errors" in result
    assert "experiments" in result.lower()


# ── 11. get_loop_health ───────────────────────────────────────


def test_get_loop_health_all_ok():
    """All components healthy yields ALL SYSTEMS OK."""
    with (
        patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as mock_sched,
        patch("engine.nexus.auto_loop.get_auto_loop") as mock_loop,
        patch("engine.nexus.conversation_sync.get_conversation_sync") as mock_sync,
        patch("training.auto_train.get_status") as mock_train,
        patch("engine.nexus.impact_tracker.get_impact_tracker") as mock_impact,
        patch("engine.nexus.experiment_executor.get_experiment_executor") as mock_exec,
        patch("engine.nexus.online_evaluator.get_online_evaluator") as mock_eval,
    ):
        daemon = MagicMock()
        daemon.status.return_value = {"running": True, "task_count": 4}
        mock_sched.return_value = daemon

        loop = MagicMock()
        loop.get_loop_status.return_value = {
            "loop_registered": True,
            "health": "healthy",
        }
        mock_loop.return_value = loop

        sync = MagicMock()
        sync.get_sync_status.return_value = {
            "events_pending": 2,
            "total_synced": 100,
        }
        mock_sync.return_value = sync

        mock_train.return_value = {
            "candidate_counts": {"chat": 50},
        }

        tracker = MagicMock()
        tracker.attribution_report.return_value = {"total_changes": 5}
        mock_impact.return_value = tracker

        executor = MagicMock()
        executor.run_stats.return_value = {"total_runs": 10}
        mock_exec.return_value = executor

        evaluator = MagicMock()
        evaluator.list_sessions.return_value = []
        mock_eval.return_value = evaluator

        result = lifecycle_skills.get_loop_health()

    assert isinstance(result, str)
    assert "ALL SYSTEMS OK" in result


def test_get_loop_health_shows_failures():
    """Component failures are flagged as FAIL."""
    with (
        patch(
            "engine.nexus.scheduler_daemon.get_scheduler_daemon",
            side_effect=ImportError("gone"),
        ),
        patch(
            "engine.nexus.auto_loop.get_auto_loop",
            side_effect=ImportError("gone"),
        ),
        patch(
            "engine.nexus.conversation_sync.get_conversation_sync",
            side_effect=ImportError("gone"),
        ),
        patch(
            "training.auto_train.get_status",
            side_effect=ImportError("gone"),
        ),
        patch(
            "engine.nexus.impact_tracker.get_impact_tracker",
            side_effect=ImportError("gone"),
        ),
        patch(
            "engine.nexus.experiment_executor.get_experiment_executor",
            side_effect=ImportError("gone"),
        ),
        patch(
            "engine.nexus.online_evaluator.get_online_evaluator",
            side_effect=ImportError("gone"),
        ),
    ):
        result = lifecycle_skills.get_loop_health()

    assert isinstance(result, str)
    assert "FAIL" in result
    assert "FAILED" in result


# ── 12. configure_loop ────────────────────────────────────────


def test_configure_loop_enables_task(mock_scheduler_daemon):
    """Enabling an existing task returns confirmation."""
    mock_scheduler_daemon.status.return_value = {
        "tasks": [{"id": "experiment"}, {"id": "eval_sweep"}]
    }
    result = lifecycle_skills.configure_loop(task_id="experiment", enabled=True)
    assert isinstance(result, str)
    assert "enabled" in result
    mock_scheduler_daemon.enable_task.assert_called_once_with("experiment")


def test_configure_loop_disables_task(mock_scheduler_daemon):
    """Disabling an existing task returns confirmation."""
    mock_scheduler_daemon.status.return_value = {
        "tasks": [{"id": "experiment"}, {"id": "eval_sweep"}]
    }
    result = lifecycle_skills.configure_loop(task_id="eval_sweep", enabled=False)
    assert isinstance(result, str)
    assert "disabled" in result
    mock_scheduler_daemon.disable_task.assert_called_once_with("eval_sweep")


def test_configure_loop_missing_task(mock_scheduler_daemon):
    """Unknown task_id returns error listing available tasks."""
    mock_scheduler_daemon.status.return_value = {
        "tasks": [{"id": "experiment"}]
    }
    result = lifecycle_skills.configure_loop(task_id="nonexistent", enabled=True)
    assert isinstance(result, str)
    assert "not found" in result.lower()
    assert "experiment" in result


def test_configure_loop_empty_task_id():
    """Empty task_id returns usage hint."""
    result = lifecycle_skills.configure_loop(task_id="", enabled=True)
    assert isinstance(result, str)
    assert "required" in result.lower()


def test_configure_loop_handles_error():
    """Exception in scheduler daemon returns error string."""
    with patch(
        "engine.nexus.scheduler_daemon.get_scheduler_daemon",
        side_effect=RuntimeError("daemon dead"),
    ):
        result = lifecycle_skills.configure_loop(
            task_id="experiment", enabled=True,
        )
    assert isinstance(result, str)
    assert "failed" in result.lower()


# ── Helper Functions ──────────────────────────────────────────


def test_ts_helper_never():
    """_ts returns 'never' for falsy input."""
    assert lifecycle_skills._ts(None) == "never"
    assert lifecycle_skills._ts(0) == "never"


def test_ts_helper_formats_epoch():
    """_ts formats a valid epoch timestamp."""
    result = lifecycle_skills._ts(1700000000.0)
    assert isinstance(result, str)
    assert "2023" in result


def test_duration_helper_seconds():
    """_duration formats sub-minute values as seconds."""
    assert lifecycle_skills._duration(30.0) == "30.0s"


def test_duration_helper_minutes():
    """_duration formats values >=60 as minutes."""
    assert lifecycle_skills._duration(120.0) == "2.0m"


def test_duration_helper_hours():
    """_duration formats values >=3600 as hours."""
    assert lifecycle_skills._duration(7200.0) == "2.0h"


def test_duration_helper_none():
    """_duration returns 'n/a' for None."""
    assert lifecycle_skills._duration(None) == "n/a"
