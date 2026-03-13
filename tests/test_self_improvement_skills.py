"""Tests for self-improvement MCP skills (v1.29).

Covers all 20 skills across four modules:
    ExperimentExecutor  (5)  — run, batch, list, status, stats
    OnlineEvaluator     (6)  — start, check, list, promote, rollback, stats
    ImpactTracker       (5)  — record, finalize, report, top, timeline
    AnomalyTrigger      (4)  — add, list, history, overview

Each skill is tested for happy-path and at least one error/edge case.
All singletons are mocked at the source module so no real instantiation occurs.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engine.skills.builtin.self_improvement_skills import (
    run_experiment,
    run_pending_experiments,
    list_experiments,
    get_experiment_status,
    experiment_stats,
    start_model_evaluation,
    check_eval_status,
    list_evaluations,
    promote_candidate_model,
    rollback_candidate_model,
    evaluation_stats,
    record_system_change,
    finalize_impact,
    impact_report,
    top_system_improvements,
    impact_timeline_view,
    add_anomaly_trigger,
    list_anomaly_triggers,
    trigger_history_view,
    trigger_overview,
)


# ──── Helpers ──────────────────────────────────────────────────────────


def _json_ok(result: str) -> dict:
    """Assert result is a valid JSON string and return the parsed dict/list."""
    assert isinstance(result, str)
    parsed = json.loads(result)
    return parsed


def _ns(**kwargs) -> SimpleNamespace:
    """Build a SimpleNamespace with to_dict() support for skill serialisation."""
    ns = SimpleNamespace(**kwargs)
    ns.to_dict = lambda: kwargs
    return ns


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ExperimentExecutor Skills (5)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ──── run_experiment ───────────────────────────────────────────────────


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_run_experiment_happy_path(mock_getter):
    """Successful execution returns JSON with experiment result."""
    mock_getter.return_value.execute_experiment.return_value = {
        "run_id": "exp-001",
        "status": "completed",
        "metrics": {"accuracy": 0.95},
    }

    result = run_experiment("prop-42")
    data = _json_ok(result)

    mock_getter.return_value.execute_experiment.assert_called_once_with("prop-42")
    assert data["run_id"] == "exp-001"
    assert data["status"] == "completed"


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_run_experiment_error(mock_getter):
    """Exception is caught and returned as an error string."""
    mock_getter.return_value.execute_experiment.side_effect = RuntimeError("db down")

    result = run_experiment("prop-99")

    assert isinstance(result, str)
    assert "Error" in result
    assert "prop-99" in result
    assert "db down" in result


# ──── run_pending_experiments ──────────────────────────────────────────


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_run_pending_experiments_with_results(mock_getter):
    """Returns JSON list when pending experiments were executed."""
    mock_getter.return_value.run_pending.return_value = [
        {"run_id": "exp-a", "status": "completed"},
        {"run_id": "exp-b", "status": "failed"},
    ]

    result = run_pending_experiments()
    data = _json_ok(result)

    assert len(data) == 2
    mock_getter.return_value.run_pending.assert_called_once()


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_run_pending_experiments_empty(mock_getter):
    """Empty result list returns a human-readable message."""
    mock_getter.return_value.run_pending.return_value = []

    result = run_pending_experiments()

    assert "No pending experiments" in result


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_run_pending_experiments_error(mock_getter):
    """Exception is caught and returned as error string."""
    mock_getter.return_value.run_pending.side_effect = ValueError("corrupt queue")

    result = run_pending_experiments()

    assert "Error" in result
    assert "corrupt queue" in result


# ──── list_experiments ─────────────────────────────────────────────────


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_list_experiments_no_filter(mock_getter):
    """No status filter returns all runs as JSON."""
    mock_getter.return_value.list_runs.return_value = [
        {"run_id": "e1", "status": "completed"},
    ]

    result = list_experiments()
    data = _json_ok(result)

    assert len(data) == 1
    mock_getter.return_value.list_runs.assert_called_once_with(
        status=None, days=30, limit=50,
    )


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_list_experiments_with_valid_status(mock_getter):
    """Valid status filter is parsed and forwarded."""
    from engine.nexus.experiment_executor import ExperimentStatus

    mock_getter.return_value.list_runs.return_value = [
        {"run_id": "e2", "status": "completed"},
    ]

    result = list_experiments(status="completed", days=7, limit=5)
    data = _json_ok(result)

    mock_getter.return_value.list_runs.assert_called_once_with(
        status=ExperimentStatus("completed"), days=7, limit=5,
    )
    assert data[0]["status"] == "completed"


def test_list_experiments_invalid_status():
    """Invalid status returns a helpful error listing valid values."""
    result = list_experiments(status="bogus_status")

    assert isinstance(result, str)
    assert "Invalid status" in result
    assert "bogus_status" in result


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_list_experiments_empty_result(mock_getter):
    """Empty list returns a human-readable message."""
    mock_getter.return_value.list_runs.return_value = []

    result = list_experiments()

    assert "No experiment runs found" in result


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_list_experiments_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.list_runs.side_effect = OSError("disk full")

    result = list_experiments()

    assert "Error" in result
    assert "disk full" in result


# ──── get_experiment_status ────────────────────────────────────────────


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_get_experiment_status_found_to_dict(mock_getter):
    """Run with to_dict() returns serialised JSON."""
    run = _ns(run_id="exp-001", status="completed", metrics={"acc": 0.9})
    mock_getter.return_value.get_run.return_value = run

    result = get_experiment_status("exp-001")
    data = _json_ok(result)

    assert data["run_id"] == "exp-001"
    mock_getter.return_value.get_run.assert_called_once_with("exp-001")


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_get_experiment_status_not_found(mock_getter):
    """Returns 'not found' message when run doesn't exist."""
    mock_getter.return_value.get_run.return_value = None

    result = get_experiment_status("missing-id")

    assert "not found" in result
    assert "missing-id" in result


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_get_experiment_status_error(mock_getter):
    """Exception is caught and returned as error string."""
    mock_getter.return_value.get_run.side_effect = KeyError("bad")

    result = get_experiment_status("exp-x")

    assert "Error" in result


# ──── experiment_stats ─────────────────────────────────────────────────


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_experiment_stats_happy_path(mock_getter):
    """Returns aggregate stats as JSON."""
    mock_getter.return_value.run_stats.return_value = {
        "total_runs": 42,
        "success_rate": 0.85,
        "avg_duration_s": 120.5,
    }

    result = experiment_stats()
    data = _json_ok(result)

    assert data["total_runs"] == 42
    assert data["success_rate"] == 0.85


@patch("engine.nexus.experiment_executor.get_experiment_executor")
def test_experiment_stats_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.run_stats.side_effect = RuntimeError("metrics offline")

    result = experiment_stats()

    assert "Error" in result
    assert "metrics offline" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OnlineEvaluator Skills (6)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ──── start_model_evaluation ───────────────────────────────────────────


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_start_model_evaluation_shadow(mock_getter):
    """Shadow mode calls start_shadow with correct kwargs."""
    session = _ns(session_id="eval-001", mode="shadow", status="running")
    mock_getter.return_value.start_shadow.return_value = session

    result = start_model_evaluation(
        mode="shadow", candidate_model="qwen3-8b",
    )
    data = _json_ok(result)

    assert data["mode"] == "shadow"
    mock_getter.return_value.start_shadow.assert_called_once()
    call_kwargs = mock_getter.return_value.start_shadow.call_args.kwargs
    assert call_kwargs["candidate_model"] == "qwen3-8b"


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_start_model_evaluation_canary(mock_getter):
    """Canary mode calls start_canary with traffic_percentage."""
    session = _ns(session_id="eval-002", mode="canary", status="running")
    mock_getter.return_value.start_canary.return_value = session

    result = start_model_evaluation(
        mode="canary",
        candidate_model="qwen3-8b",
        traffic_percentage=0.10,
    )
    data = _json_ok(result)

    assert data["mode"] == "canary"
    call_kwargs = mock_getter.return_value.start_canary.call_args.kwargs
    assert call_kwargs["traffic_percentage"] == 0.10


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_start_model_evaluation_ab_test(mock_getter):
    """A/B test mode calls start_ab_test."""
    session = _ns(session_id="eval-003", mode="ab_test", status="running")
    mock_getter.return_value.start_ab_test.return_value = session

    result = start_model_evaluation(
        mode="ab_test",
        candidate_model="qwen3-8b",
        production_model="qwen3-4b",
        min_samples=100,
        max_duration_hours=2.0,
    )
    data = _json_ok(result)

    assert data["mode"] == "ab_test"
    call_kwargs = mock_getter.return_value.start_ab_test.call_args.kwargs
    assert call_kwargs["candidate_model"] == "qwen3-8b"
    assert call_kwargs["production_model"] == "qwen3-4b"
    assert call_kwargs["min_samples"] == 100
    assert call_kwargs["max_duration_hours"] == 2.0


def test_start_model_evaluation_invalid_mode():
    """Invalid mode returns an error string without raising."""
    result = start_model_evaluation(mode="invalid", candidate_model="m")

    assert isinstance(result, str)
    assert "Invalid mode" in result
    assert "invalid" in result


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_start_model_evaluation_error(mock_getter):
    """Exception is caught and returned as error string."""
    mock_getter.return_value.start_shadow.side_effect = ConnectionError("timeout")

    result = start_model_evaluation(mode="shadow", candidate_model="m")

    assert "Error" in result
    assert "timeout" in result


# ──── check_eval_status ────────────────────────────────────────────────


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_check_eval_status_found(mock_getter):
    """Returns JSON session data when session exists."""
    session = _ns(session_id="eval-001", status="running", sample_count=42)
    mock_getter.return_value.get_session.return_value = session

    result = check_eval_status("eval-001")
    data = _json_ok(result)

    assert data["session_id"] == "eval-001"
    assert data["sample_count"] == 42


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_check_eval_status_not_found(mock_getter):
    """Returns 'not found' message when session doesn't exist."""
    mock_getter.return_value.get_session.return_value = None

    result = check_eval_status("no-such")

    assert "not found" in result
    assert "no-such" in result


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_check_eval_status_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.get_session.side_effect = RuntimeError("boom")

    result = check_eval_status("eval-x")

    assert "Error" in result


# ──── list_evaluations ─────────────────────────────────────────────────


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_list_evaluations_no_filter(mock_getter):
    """No status filter returns all sessions."""
    mock_getter.return_value.list_sessions.return_value = [
        {"session_id": "e1", "mode": "shadow"},
    ]

    result = list_evaluations()
    data = _json_ok(result)

    assert len(data) == 1
    mock_getter.return_value.list_sessions.assert_called_once_with(
        status=None, days=30, limit=50,
    )


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_list_evaluations_with_valid_status(mock_getter):
    """Valid status filter is parsed and forwarded."""
    from engine.nexus.online_evaluator import EvalStatus

    mock_getter.return_value.list_sessions.return_value = [
        {"session_id": "e2", "status": "running"},
    ]

    result = list_evaluations(status="running", days=7, limit=5)
    data = _json_ok(result)

    mock_getter.return_value.list_sessions.assert_called_once_with(
        status=EvalStatus("running"), days=7, limit=5,
    )


def test_list_evaluations_invalid_status():
    """Invalid status returns a helpful error."""
    result = list_evaluations(status="bogus")

    assert "Invalid status" in result
    assert "bogus" in result


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_list_evaluations_empty(mock_getter):
    """Empty list returns a human-readable message."""
    mock_getter.return_value.list_sessions.return_value = []

    result = list_evaluations(status="completed")

    assert "No evaluation sessions found" in result
    assert "completed" in result


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_list_evaluations_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.list_sessions.side_effect = IOError("read fail")

    result = list_evaluations()

    assert "Error" in result


# ──── promote_candidate_model ──────────────────────────────────────────


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_promote_candidate_model_success(mock_getter):
    """Successful promotion returns JSON result."""
    mock_getter.return_value.promote_model.return_value = {
        "promoted": True,
        "old_model": "qwen3-4b",
        "new_model": "qwen3-8b",
    }

    result = promote_candidate_model("eval-001")
    data = _json_ok(result)

    assert data["promoted"] is True
    mock_getter.return_value.promote_model.assert_called_once_with("eval-001")


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_promote_candidate_model_error(mock_getter):
    """Exception is caught and returned as error string."""
    mock_getter.return_value.promote_model.side_effect = RuntimeError("not ready")

    result = promote_candidate_model("eval-x")

    assert "Error" in result
    assert "eval-x" in result


# ──── rollback_candidate_model ─────────────────────────────────────────


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_rollback_candidate_model_success(mock_getter):
    """Successful rollback returns JSON result."""
    mock_getter.return_value.rollback_model.return_value = {
        "rolled_back": True,
        "restored_model": "qwen3-4b",
    }

    result = rollback_candidate_model("eval-002")
    data = _json_ok(result)

    assert data["rolled_back"] is True
    mock_getter.return_value.rollback_model.assert_called_once_with("eval-002")


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_rollback_candidate_model_error(mock_getter):
    """Exception is caught and returned as error string."""
    mock_getter.return_value.rollback_model.side_effect = ValueError("bad session")

    result = rollback_candidate_model("eval-z")

    assert "Error" in result
    assert "eval-z" in result


# ──── evaluation_stats ─────────────────────────────────────────────────


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_evaluation_stats_happy_path(mock_getter):
    """Returns aggregate evaluation stats as JSON."""
    mock_getter.return_value.eval_stats.return_value = {
        "total_sessions": 15,
        "promotion_rate": 0.6,
        "modes": {"shadow": 10, "canary": 3, "ab_test": 2},
    }

    result = evaluation_stats()
    data = _json_ok(result)

    assert data["total_sessions"] == 15
    assert data["promotion_rate"] == 0.6


@patch("engine.nexus.online_evaluator.get_online_evaluator")
def test_evaluation_stats_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.eval_stats.side_effect = RuntimeError("unavailable")

    result = evaluation_stats()

    assert "Error" in result
    assert "unavailable" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ImpactTracker Skills (5)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ──── record_system_change ─────────────────────────────────────────────


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_record_system_change_happy_path(mock_getter):
    """Records a change and returns serialised JSON."""
    change = _ns(change_id="chg-001", change_type="config_change", title="Bump LR")
    mock_getter.return_value.record_change.return_value = change

    result = record_system_change(
        change_type="config_change",
        title="Bump LR",
        description="Increased learning rate from 1e-4 to 3e-4",
    )
    data = _json_ok(result)

    assert data["change_id"] == "chg-001"
    mock_getter.return_value.record_change.assert_called_once()


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_record_system_change_with_metadata(mock_getter):
    """Valid metadata_json is parsed and forwarded."""
    change = _ns(change_id="chg-002", change_type="code_deploy", title="Deploy v2")
    mock_getter.return_value.record_change.return_value = change

    metadata = '{"version": "2.0", "sha": "abc123"}'
    result = record_system_change(
        change_type="code_deploy",
        title="Deploy v2",
        description="Deploy version 2",
        metadata_json=metadata,
    )
    data = _json_ok(result)

    call_kwargs = mock_getter.return_value.record_change.call_args.kwargs
    assert call_kwargs["metadata"] == {"version": "2.0", "sha": "abc123"}


def test_record_system_change_invalid_type():
    """Invalid change_type returns error listing valid values."""
    result = record_system_change(
        change_type="bogus_type",
        title="X",
        description="Y",
    )

    assert "Invalid change_type" in result
    assert "bogus_type" in result
    assert "config_change" in result  # valid values listed


def test_record_system_change_bad_metadata_json():
    """Malformed metadata_json returns parse error."""
    result = record_system_change(
        change_type="config_change",
        title="X",
        description="Y",
        metadata_json="{not valid json",
    )

    assert "Invalid metadata_json" in result


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_record_system_change_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.record_change.side_effect = OSError("write fail")

    result = record_system_change(
        change_type="config_change", title="X", description="Y",
    )

    assert "Error" in result
    assert "write fail" in result


# ──── finalize_impact ──────────────────────────────────────────────────


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_finalize_impact_happy_path(mock_getter):
    """Returns impact deltas as JSON."""
    mock_getter.return_value.finalize_change.return_value = {
        "change_id": "chg-001",
        "delta": {"latency_ms": -12.5, "accuracy": +0.02},
    }

    result = finalize_impact("chg-001")
    data = _json_ok(result)

    assert data["change_id"] == "chg-001"
    assert data["delta"]["latency_ms"] == -12.5
    mock_getter.return_value.finalize_change.assert_called_once_with("chg-001")


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_finalize_impact_error(mock_getter):
    """Exception is caught and returned as error string."""
    mock_getter.return_value.finalize_change.side_effect = RuntimeError("no snapshot")

    result = finalize_impact("chg-x")

    assert "Error" in result
    assert "chg-x" in result


# ──── impact_report ────────────────────────────────────────────────────


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_impact_report_happy_path(mock_getter):
    """Returns attribution report as JSON."""
    mock_getter.return_value.attribution_report.return_value = {
        "period_days": 30,
        "changes": [{"change_id": "c1", "impact_score": 0.95}],
    }

    result = impact_report(days=30, limit=10)
    data = _json_ok(result)

    assert data["period_days"] == 30
    mock_getter.return_value.attribution_report.assert_called_once_with(
        days=30, limit=10,
    )


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_impact_report_custom_params(mock_getter):
    """Custom days and limit are forwarded."""
    mock_getter.return_value.attribution_report.return_value = {"changes": []}

    impact_report(days=7, limit=3)

    mock_getter.return_value.attribution_report.assert_called_once_with(
        days=7, limit=3,
    )


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_impact_report_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.attribution_report.side_effect = RuntimeError("nope")

    result = impact_report()

    assert "Error" in result


# ──── top_system_improvements ──────────────────────────────────────────


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_top_system_improvements_with_data(mock_getter):
    """Returns ranked improvements as JSON."""
    mock_getter.return_value.top_improvements.return_value = [
        {"change_id": "c1", "impact": 0.95, "title": "Big win"},
    ]

    result = top_system_improvements(days=14, limit=5)
    data = _json_ok(result)

    assert len(data) == 1
    assert data[0]["title"] == "Big win"


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_top_system_improvements_empty(mock_getter):
    """Empty list returns a human-readable message."""
    mock_getter.return_value.top_improvements.return_value = []

    result = top_system_improvements(days=7)

    assert "No positive-impact changes" in result
    assert "7" in result


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_top_system_improvements_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.top_improvements.side_effect = RuntimeError("fail")

    result = top_system_improvements()

    assert "Error" in result


# ──── impact_timeline_view ─────────────────────────────────────────────


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_impact_timeline_view_with_data(mock_getter):
    """Returns timeline entries as JSON."""
    mock_getter.return_value.impact_timeline.return_value = [
        {"ts": "2025-01-01T00:00:00", "change_id": "c1", "type": "config_change"},
    ]

    result = impact_timeline_view(days=14)
    data = _json_ok(result)

    assert len(data) == 1
    mock_getter.return_value.impact_timeline.assert_called_once_with(days=14)


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_impact_timeline_view_empty(mock_getter):
    """Empty timeline returns a human-readable message."""
    mock_getter.return_value.impact_timeline.return_value = []

    result = impact_timeline_view(days=3)

    assert "No changes recorded" in result
    assert "3" in result


@patch("engine.nexus.impact_tracker.get_impact_tracker")
def test_impact_timeline_view_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.impact_timeline.side_effect = RuntimeError("oops")

    result = impact_timeline_view()

    assert "Error" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AnomalyTrigger Skills (4)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ──── add_anomaly_trigger ──────────────────────────────────────────────


@patch("engine.observability.anomaly_trigger.TriggerPattern")
@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_add_anomaly_trigger_happy_path(mock_getter, mock_pattern_cls):
    """Registers a trigger rule and returns JSON."""
    rule = _ns(rule_id="trig-001", name="GPU alert", task_id="fix-gpu")
    mock_getter.return_value.register_trigger.return_value = rule
    mock_pattern_cls.return_value = MagicMock()

    result = add_anomaly_trigger(
        name="GPU alert",
        task_id="fix-gpu",
        node_prefix="gpu",
        metric_contains="temp",
        cooldown_seconds=600.0,
    )
    data = _json_ok(result)

    assert data["rule_id"] == "trig-001"
    mock_getter.return_value.register_trigger.assert_called_once()
    mock_pattern_cls.assert_called_once_with(
        node=None, metric=None, node_prefix="gpu", metric_contains="temp",
    )


@patch("engine.observability.anomaly_trigger.TriggerPattern")
@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_add_anomaly_trigger_with_metadata(mock_getter, mock_pattern_cls):
    """Valid metadata_json is parsed and forwarded."""
    rule = _ns(rule_id="trig-002", name="Test", task_id="t1")
    mock_getter.return_value.register_trigger.return_value = rule
    mock_pattern_cls.return_value = MagicMock()

    result = add_anomaly_trigger(
        name="Test",
        task_id="t1",
        metadata_json='{"severity": "critical"}',
    )
    _json_ok(result)

    call_kwargs = mock_getter.return_value.register_trigger.call_args.kwargs
    assert call_kwargs["metadata"] == {"severity": "critical"}


def test_add_anomaly_trigger_bad_metadata_json():
    """Malformed metadata_json returns parse error without raising."""
    result = add_anomaly_trigger(
        name="X",
        task_id="t1",
        metadata_json="not json{",
    )

    assert "Invalid metadata_json" in result


@patch("engine.observability.anomaly_trigger.TriggerPattern")
@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_add_anomaly_trigger_error(mock_getter, mock_pattern_cls):
    """Exception is caught and returned as error string."""
    mock_pattern_cls.return_value = MagicMock()
    mock_getter.return_value.register_trigger.side_effect = RuntimeError("full")

    result = add_anomaly_trigger(name="X", task_id="t1")

    assert "Error" in result
    assert "full" in result


# ──── list_anomaly_triggers ────────────────────────────────────────────


@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_list_anomaly_triggers_with_data(mock_getter):
    """Returns trigger list as JSON."""
    mock_getter.return_value.list_triggers.return_value = [
        {"rule_id": "r1", "name": "GPU check", "enabled": True},
    ]

    result = list_anomaly_triggers(enabled_only=True)
    data = _json_ok(result)

    assert len(data) == 1
    mock_getter.return_value.list_triggers.assert_called_once_with(enabled_only=True)


@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_list_anomaly_triggers_all(mock_getter):
    """Returns all triggers when enabled_only=False."""
    mock_getter.return_value.list_triggers.return_value = [
        {"rule_id": "r1", "enabled": True},
        {"rule_id": "r2", "enabled": False},
    ]

    result = list_anomaly_triggers(enabled_only=False)
    data = _json_ok(result)

    assert len(data) == 2
    mock_getter.return_value.list_triggers.assert_called_once_with(enabled_only=False)


@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_list_anomaly_triggers_empty(mock_getter):
    """Empty list returns a human-readable message."""
    mock_getter.return_value.list_triggers.return_value = []

    result = list_anomaly_triggers(enabled_only=True)

    assert "No" in result
    assert "anomaly triggers" in result


@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_list_anomaly_triggers_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.list_triggers.side_effect = RuntimeError("fail")

    result = list_anomaly_triggers()

    assert "Error" in result


# ──── trigger_history_view ─────────────────────────────────────────────


@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_trigger_history_view_with_data(mock_getter):
    """Returns firing history as JSON."""
    mock_getter.return_value.trigger_history.return_value = [
        {"rule_id": "r1", "fired_at": "2025-01-01T12:00:00", "task": "fix-gpu"},
    ]

    result = trigger_history_view(rule_id="r1", hours=12.0, limit=50)
    data = _json_ok(result)

    assert len(data) == 1
    mock_getter.return_value.trigger_history.assert_called_once_with(
        rule_id="r1", hours=12.0, limit=50,
    )


@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_trigger_history_view_no_rule_filter(mock_getter):
    """No rule_id filter passes None."""
    mock_getter.return_value.trigger_history.return_value = [{"rule_id": "r1"}]

    trigger_history_view()

    mock_getter.return_value.trigger_history.assert_called_once_with(
        rule_id=None, hours=24.0, limit=100,
    )


@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_trigger_history_view_empty(mock_getter):
    """Empty history returns a human-readable message."""
    mock_getter.return_value.trigger_history.return_value = []

    result = trigger_history_view(rule_id="r1", hours=1.0)

    assert "No trigger firings" in result
    assert "r1" in result


@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_trigger_history_view_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.trigger_history.side_effect = RuntimeError("bad")

    result = trigger_history_view()

    assert "Error" in result


# ──── trigger_overview ─────────────────────────────────────────────────


@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_trigger_overview_happy_path(mock_getter):
    """Returns system status as JSON."""
    mock_getter.return_value.trigger_status.return_value = {
        "total_rules": 5,
        "enabled": 3,
        "total_firings_24h": 12,
    }

    result = trigger_overview()
    data = _json_ok(result)

    assert data["total_rules"] == 5
    assert data["enabled"] == 3


@patch("engine.observability.anomaly_trigger.get_anomaly_trigger")
def test_trigger_overview_error(mock_getter):
    """Exception is caught gracefully."""
    mock_getter.return_value.trigger_status.side_effect = RuntimeError("gone")

    result = trigger_overview()

    assert "Error" in result
    assert "gone" in result
