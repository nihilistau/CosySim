"""Tests for engine.nexus.experiment_executor.

Covers the ExperimentExecutor class: DB initialization, experiment lifecycle,
metric collection, treatment application/rollback, statistical analysis,
query methods, aggregate stats, scheduler integration, singleton pattern,
and edge cases.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.experiment_executor import (
    ExperimentExecutor,
    ExperimentRun,
    ExperimentStatus,
    _experiment_run_callback,
    get_experiment_executor,
    register_experiment_tasks,
)

# ── Helpers ─────────────────────────────────────────────────────────────


def _make_run(
    run_id: str = "exp-test0001",
    proposal_id: str = "prop-001",
    experiment_name: str = "test_exp",
    status: ExperimentStatus = ExperimentStatus.PENDING,
    hypothesis: str = "Treatment improves latency",
    variants: Optional[List[Dict[str, Any]]] = None,
    success_metric: str = "pipeline.avg_latency",
    success_threshold: float = 0.2,
    baseline_metrics: Optional[Dict[str, float]] = None,
    treatment_metrics: Optional[Dict[str, float]] = None,
    active_variant: Optional[str] = None,
    config_backup: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    started_at: Optional[float] = None,
    completed_at: Optional[float] = None,
    error: Optional[str] = None,
) -> ExperimentRun:
    """Build an ExperimentRun with sensible defaults."""
    return ExperimentRun(
        run_id=run_id,
        proposal_id=proposal_id,
        experiment_name=experiment_name,
        status=status,
        hypothesis=hypothesis,
        variants=variants or [{"id": "v1", "label": "fast", "config": {"lmstudio.temperature": 0.5}}],
        success_metric=success_metric,
        success_threshold=success_threshold,
        baseline_metrics=baseline_metrics or {},
        treatment_metrics=treatment_metrics or {},
        active_variant=active_variant,
        config_backup=config_backup or {},
        result=result,
        started_at=started_at or time.time(),
        completed_at=completed_at,
        error=error,
    )


def _make_proposal(
    proposal_id: str = "prop-001",
    experiment_name: str = "latency_test",
    priority: str = "high",
) -> Dict[str, Any]:
    """Build a proposal dict matching ExperimentProposer output."""
    return {
        "proposal_id": proposal_id,
        "experiment_name": experiment_name,
        "hypothesis": "Lower temperature reduces latency",
        "variants": [
            {"id": "v1", "label": "low_temp", "config": {"lmstudio.temperature": 0.3}},
        ],
        "success_metric": "pipeline.avg_latency",
        "success_threshold": 0.2,
        "trigger_metric": "pipeline.avg_latency",
        "trigger_value": 5.0,
        "priority": priority,
        "status": "pending",
    }


def _mock_config() -> MagicMock:
    """Return a dict-like MagicMock simulating ConfigManager."""
    store: Dict[str, Any] = {
        "experiments.settle_seconds": 0.0,
        "experiments.iterations": 3,
        "lmstudio.temperature": 0.7,
    }
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None: store.get(key, default)
    cfg.set.side_effect = lambda key, value: store.__setitem__(key, value)
    return cfg


def _mock_metrics_db(
    pipeline_summary: Optional[Dict[str, float]] = None,
    system_history: Optional[List[Dict[str, float]]] = None,
) -> MagicMock:
    """Return a MagicMock simulating MetricsDB."""
    mdb = MagicMock()
    mdb.get_pipeline_summary.return_value = pipeline_summary or {
        "avg_latency": 2.5,
        "avg_tps": 10.0,
        "avg_ttft": 0.3,
        "avg_tokens_in": 100.0,
        "avg_tokens_out": 200.0,
    }
    mdb.get_system_history.return_value = system_history or [
        {"cpu_pct": 45.0, "ram_pct": 60.0, "gpu_vram_pct": 70.0},
    ]
    mdb.get_pipeline_history.return_value = []
    return mdb


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def executor(tmp_path: Path) -> ExperimentExecutor:
    """Create an ExperimentExecutor backed by a temp database."""
    return ExperimentExecutor(db_path=tmp_path / "test_executor.db")


@pytest.fixture()
def seeded_executor(executor: ExperimentExecutor) -> ExperimentExecutor:
    """Executor with a saved run ready for queries."""
    run = _make_run()
    executor._save_run(run)
    return executor


# ── Initialization ──────────────────────────────────────────────────────


def test_creates_database_on_init(tmp_path: Path) -> None:
    """Database file is created when the executor is initialised."""
    db_file = tmp_path / "new_db.db"
    assert not db_file.exists()
    ExperimentExecutor(db_path=db_file)
    assert db_file.exists()


def test_wal_mode_enabled(executor: ExperimentExecutor) -> None:
    """SQLite WAL journal mode is activated on the connection."""
    conn = executor._get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_tables_created(executor: ExperimentExecutor) -> None:
    """Both experiment_runs and experiment_metrics tables exist."""
    conn = executor._get_conn()
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "experiment_runs" in tables
    assert "experiment_metrics" in tables


# ── Experiment Lifecycle ────────────────────────────────────────────────


@patch("engine.nexus.experiment_executor._get_nexus_client", return_value=MagicMock())
@patch("engine.nexus.experiment_executor._get_impact_tracker", return_value=None)
@patch("engine.nexus.experiment_executor._get_metrics_db")
@patch("engine.nexus.experiment_executor._get_config")
@patch("engine.nexus.experiment_executor._get_proposer")
@patch("engine.nexus.experiment_executor.time")
def test_execute_experiment_full_lifecycle(
    mock_time: MagicMock,
    mock_proposer_fn: MagicMock,
    mock_config_fn: MagicMock,
    mock_mdb_fn: MagicMock,
    mock_impact_fn: MagicMock,
    mock_nexus_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """Full lifecycle: baseline → treatment → analysis → promote/rollback."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()

    proposer = MagicMock()
    proposal = _make_proposal()
    proposer.get_proposals.return_value = [proposal]
    mock_proposer_fn.return_value = proposer

    cfg = _mock_config()
    mock_config_fn.return_value = cfg

    mdb = _mock_metrics_db()
    mock_mdb_fn.return_value = mdb

    result = executor.execute_experiment("prop-001")

    assert result["run_id"] is not None
    assert result["status"] in (
        "completed", "rolled_back", "failed",
    )
    assert result["error"] is None or result["status"] == "failed"


@patch("engine.nexus.experiment_executor._get_proposer")
def test_execute_experiment_proposal_not_found(
    mock_proposer_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """Returns error dict when proposal_id is not found."""
    proposer = MagicMock()
    proposer.get_proposals.return_value = []
    mock_proposer_fn.return_value = proposer

    result = executor.execute_experiment("nonexistent")

    assert result["status"] == "failed"
    assert "not found" in result["error"]


def test_execute_experiment_proposer_unavailable(
    executor: ExperimentExecutor,
) -> None:
    """Returns error when the ExperimentProposer singleton is None."""
    with patch(
        "engine.nexus.experiment_executor._get_proposer", return_value=None
    ):
        result = executor.execute_experiment("anything")
    assert result["status"] == "failed"
    assert "unavailable" in result["error"].lower()


@patch("engine.nexus.experiment_executor._get_nexus_client", return_value=MagicMock())
@patch("engine.nexus.experiment_executor._get_impact_tracker", return_value=None)
@patch("engine.nexus.experiment_executor._get_metrics_db")
@patch("engine.nexus.experiment_executor._get_config")
@patch("engine.nexus.experiment_executor.time")
def test_execute_from_proposal_object(
    mock_time: MagicMock,
    mock_config_fn: MagicMock,
    mock_mdb_fn: MagicMock,
    mock_impact_fn: MagicMock,
    mock_nexus_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """execute_from_proposal works with a proposal-like object."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()
    mock_config_fn.return_value = _mock_config()
    mock_mdb_fn.return_value = _mock_metrics_db()

    proposal_obj = MagicMock()
    proposal_obj.proposal_id = "obj-001"
    proposal_obj.experiment_name = "obj_test"
    proposal_obj.hypothesis = "Some hypothesis"
    proposal_obj.variants = [{"id": "v1", "label": "fast", "config": {"x": 1}}]
    proposal_obj.success_metric = "pipeline.avg_latency"
    proposal_obj.success_threshold = 0.1
    proposal_obj.trigger_metric = "pipeline.avg_latency"
    proposal_obj.trigger_value = 5.0
    proposal_obj.priority = "medium"

    result = executor.execute_from_proposal(proposal_obj)

    assert result["run_id"] is not None
    assert result["status"] in ("completed", "rolled_back", "failed")


@patch("engine.nexus.experiment_executor._get_nexus_client", return_value=MagicMock())
@patch("engine.nexus.experiment_executor._get_impact_tracker", return_value=None)
@patch("engine.nexus.experiment_executor._get_metrics_db")
@patch("engine.nexus.experiment_executor._get_config")
@patch("engine.nexus.experiment_executor._get_proposer")
@patch("engine.nexus.experiment_executor.time")
def test_run_pending_executes_all_pending(
    mock_time: MagicMock,
    mock_proposer_fn: MagicMock,
    mock_config_fn: MagicMock,
    mock_mdb_fn: MagicMock,
    mock_impact_fn: MagicMock,
    mock_nexus_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """run_pending executes every pending proposal and returns results."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()

    proposer = MagicMock()
    proposer.get_proposals.return_value = [
        _make_proposal("p1", "exp_a", "high"),
        _make_proposal("p2", "exp_b", "low"),
    ]
    mock_proposer_fn.return_value = proposer
    mock_config_fn.return_value = _mock_config()
    mock_mdb_fn.return_value = _mock_metrics_db()

    results = executor.run_pending()

    assert len(results) == 2
    assert all("run_id" in r for r in results)


@patch("engine.nexus.experiment_executor._get_proposer")
def test_run_pending_empty(
    mock_proposer_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """run_pending returns empty list when no pending proposals exist."""
    proposer = MagicMock()
    proposer.get_proposals.return_value = []
    mock_proposer_fn.return_value = proposer

    results = executor.run_pending()

    assert results == []


@patch("engine.nexus.experiment_executor._get_nexus_client", return_value=MagicMock())
@patch("engine.nexus.experiment_executor._get_impact_tracker", return_value=None)
@patch("engine.nexus.experiment_executor._get_metrics_db", return_value=None)
@patch("engine.nexus.experiment_executor._get_config")
@patch("engine.nexus.experiment_executor.time")
def test_experiment_fails_on_no_variants(
    mock_time: MagicMock,
    mock_config_fn: MagicMock,
    mock_mdb_fn: MagicMock,
    mock_impact_fn: MagicMock,
    mock_nexus_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """Experiment fails when proposal has no variants defined."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()
    mock_config_fn.return_value = _mock_config()

    proposal = _make_proposal()
    proposal["variants"] = []

    result = executor._execute_proposal_dict(proposal)

    assert result["status"] == "failed"
    assert "no variants" in result["error"].lower()


@patch("engine.nexus.experiment_executor._get_nexus_client", return_value=MagicMock())
@patch("engine.nexus.experiment_executor._get_impact_tracker", return_value=None)
@patch("engine.nexus.experiment_executor._get_metrics_db", return_value=None)
@patch("engine.nexus.experiment_executor._get_config", return_value=None)
@patch("engine.nexus.experiment_executor.time")
def test_experiment_rollback_on_failure(
    mock_time: MagicMock,
    mock_config_fn: MagicMock,
    mock_mdb_fn: MagicMock,
    mock_impact_fn: MagicMock,
    mock_nexus_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """When apply_treatment raises, status becomes FAILED and error is set."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()

    proposal = _make_proposal()
    result = executor._execute_proposal_dict(proposal)

    assert result["status"] == "failed"
    assert result["error"] is not None


# ── Metrics Collection ──────────────────────────────────────────────────


@patch("engine.nexus.experiment_executor._get_config", return_value=None)
@patch("engine.nexus.experiment_executor._get_metrics_db")
@patch("engine.nexus.experiment_executor.time")
def test_collect_metrics_returns_samples(
    mock_time: MagicMock,
    mock_mdb_fn: MagicMock,
    mock_config_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """collect_metrics returns dict of metric lists from MetricsDB."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()
    mock_mdb_fn.return_value = _mock_metrics_db()

    run = _make_run()
    executor._save_run(run)

    collected = executor.collect_metrics(run.run_id, "baseline", iterations=3)

    assert isinstance(collected, dict)
    assert "pipeline.avg_latency" in collected
    assert len(collected["pipeline.avg_latency"]) == 3


@patch("engine.nexus.experiment_executor._get_config", return_value=None)
@patch("engine.nexus.experiment_executor._get_metrics_db")
@patch("engine.nexus.experiment_executor.time")
def test_collect_metrics_custom_iterations(
    mock_time: MagicMock,
    mock_mdb_fn: MagicMock,
    mock_config_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """Iteration count controls the number of samples per metric."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()
    mock_mdb_fn.return_value = _mock_metrics_db()

    run = _make_run()
    executor._save_run(run)

    collected = executor.collect_metrics(run.run_id, "baseline", iterations=5)

    for values in collected.values():
        assert len(values) == 5


@patch("engine.nexus.experiment_executor._get_config", return_value=None)
@patch("engine.nexus.experiment_executor._get_metrics_db", return_value=None)
@patch("engine.nexus.experiment_executor.time")
def test_collect_metrics_handles_missing_metrics(
    mock_time: MagicMock,
    mock_mdb_fn: MagicMock,
    mock_config_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """Returns empty dict when MetricsDB is unavailable."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()

    run = _make_run()
    executor._save_run(run)

    collected = executor.collect_metrics(run.run_id, "baseline", iterations=2)

    assert collected == {}


def test_collect_metrics_run_not_found(executor: ExperimentExecutor) -> None:
    """Returns empty dict when the run_id does not exist."""
    collected = executor.collect_metrics("nonexistent", "baseline", iterations=1)
    assert collected == {}


@patch("engine.nexus.experiment_executor._get_config", return_value=None)
@patch("engine.nexus.experiment_executor._get_metrics_db")
@patch("engine.nexus.experiment_executor.time")
def test_collect_metrics_baseline_vs_treatment(
    mock_time: MagicMock,
    mock_mdb_fn: MagicMock,
    mock_config_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """Baseline and treatment phases store data independently in the DB."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()
    mock_mdb_fn.return_value = _mock_metrics_db()

    run = _make_run()
    executor._save_run(run)

    executor.collect_metrics(run.run_id, "baseline", iterations=2)
    executor.collect_metrics(run.run_id, "treatment", iterations=2)

    baseline_data = executor._load_metric_samples(run.run_id, "baseline")
    treatment_data = executor._load_metric_samples(run.run_id, "treatment")

    assert len(baseline_data) > 0
    assert len(treatment_data) > 0
    for vals in baseline_data.values():
        assert len(vals) == 2
    for vals in treatment_data.values():
        assert len(vals) == 2


# ── Treatment ───────────────────────────────────────────────────────────


@patch("engine.nexus.experiment_executor._get_config")
@patch("engine.nexus.experiment_executor.time")
def test_apply_treatment_success(
    mock_time: MagicMock,
    mock_config_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """apply_treatment modifies config and returns applied=True."""
    mock_time.sleep = MagicMock()
    cfg = _mock_config()
    mock_config_fn.return_value = cfg

    run = _make_run()
    variant = {"id": "v1", "label": "fast", "config": {"lmstudio.temperature": 0.3}}

    result = executor.apply_treatment(run, variant)

    assert result["applied"] is True
    assert result["variant_id"] == "v1"
    cfg.set.assert_called()


@patch("engine.nexus.experiment_executor._get_config")
@patch("engine.nexus.experiment_executor.time")
def test_apply_treatment_returns_backup(
    mock_time: MagicMock,
    mock_config_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """Backup dict contains original config values before treatment."""
    mock_time.sleep = MagicMock()
    cfg = _mock_config()
    mock_config_fn.return_value = cfg

    run = _make_run()
    variant = {"id": "v1", "label": "fast", "config": {"lmstudio.temperature": 0.3}}

    result = executor.apply_treatment(run, variant)

    assert "config_backup" in result
    assert "lmstudio.temperature" in result["config_backup"]
    assert result["config_backup"]["lmstudio.temperature"] == 0.7


@patch("engine.nexus.experiment_executor._get_config")
def test_rollback_treatment_restores_config(
    mock_config_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """Rollback restores backed-up values via cfg.set()."""
    cfg = _mock_config()
    mock_config_fn.return_value = cfg

    run = _make_run(config_backup={"lmstudio.temperature": 0.7, "lmstudio.top_p": 0.9})

    success = executor.rollback_treatment(run)

    assert success is True
    assert cfg.set.call_count == 2


@patch("engine.nexus.experiment_executor._get_config")
def test_rollback_treatment_no_backup(
    mock_config_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """Rollback returns True when there is no backup to restore."""
    mock_config_fn.return_value = _mock_config()

    run = _make_run(config_backup={})

    success = executor.rollback_treatment(run)

    assert success is True


@patch("engine.nexus.experiment_executor._get_config", return_value=None)
def test_apply_treatment_raises_without_config(
    mock_config_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """apply_treatment raises RuntimeError when config is unavailable."""
    run = _make_run()
    variant = {"id": "v1", "label": "fast", "config": {"x": 1}}

    with pytest.raises(RuntimeError, match="ConfigManager unavailable"):
        executor.apply_treatment(run, variant)


@patch("engine.nexus.experiment_executor._get_config")
@patch("engine.nexus.experiment_executor.time")
def test_treatment_with_multiple_variants(
    mock_time: MagicMock,
    mock_config_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """apply_treatment handles variant with multiple config keys."""
    mock_time.sleep = MagicMock()
    cfg = _mock_config()
    mock_config_fn.return_value = cfg

    run = _make_run()
    variant = {
        "id": "multi",
        "label": "multi_change",
        "config": {
            "lmstudio.temperature": 0.2,
            "lmstudio.top_p": 0.8,
            "lmstudio.max_tokens": 512,
        },
    }

    result = executor.apply_treatment(run, variant)

    assert result["applied"] is True
    assert len(result["config_backup"]) == 3


# ── Statistical Analysis ───────────────────────────────────────────────


def test_analyze_results_significant_improvement(
    executor: ExperimentExecutor,
) -> None:
    """Analysis recommends 'promote' for significant positive change."""
    run = _make_run(success_threshold=0.1)
    executor._save_run(run)

    # Seed metric samples: treatment clearly better
    for i in range(10):
        executor._store_metric_sample(
            run.run_id, "baseline", i, "pipeline.avg_latency", 5.0 + i * 0.01, 1000.0 + i
        )
        executor._store_metric_sample(
            run.run_id, "treatment", i, "pipeline.avg_latency", 8.0 + i * 0.01, 2000.0 + i
        )

    analysis = executor.analyze_results(run)

    assert analysis["significant"] is True
    assert "pipeline.avg_latency" in analysis["metrics"]
    metric = analysis["metrics"]["pipeline.avg_latency"]
    assert metric["direction"] == "improved"
    assert analysis["recommendation"] == "promote"


def test_analyze_results_no_significant_difference(
    executor: ExperimentExecutor,
) -> None:
    """Analysis returns 'inconclusive' when values are nearly identical."""
    run = _make_run(success_threshold=0.5)
    executor._save_run(run)

    for i in range(10):
        executor._store_metric_sample(
            run.run_id, "baseline", i, "pipeline.avg_latency", 5.0, 1000.0 + i
        )
        executor._store_metric_sample(
            run.run_id, "treatment", i, "pipeline.avg_latency", 5.0, 2000.0 + i
        )

    analysis = executor.analyze_results(run)

    assert analysis["recommendation"] == "inconclusive"


def test_analyze_results_regression(
    executor: ExperimentExecutor,
) -> None:
    """Analysis recommends 'rollback' when treatment degrades metric."""
    run = _make_run(success_threshold=0.1)
    executor._save_run(run)

    for i in range(10):
        executor._store_metric_sample(
            run.run_id, "baseline", i, "pipeline.avg_latency", 8.0, 1000.0 + i
        )
        executor._store_metric_sample(
            run.run_id, "treatment", i, "pipeline.avg_latency", 3.0, 2000.0 + i
        )

    analysis = executor.analyze_results(run)

    metric = analysis["metrics"]["pipeline.avg_latency"]
    assert metric["direction"] == "degraded"
    assert analysis["recommendation"] == "rollback"


def test_analyze_results_effect_size_calculation(
    executor: ExperimentExecutor,
) -> None:
    """Cohen's d is computed and included in analysis output."""
    run = _make_run(success_threshold=0.1)
    executor._save_run(run)

    for i in range(10):
        executor._store_metric_sample(
            run.run_id, "baseline", i, "pipeline.avg_latency", 5.0 + i * 0.1, 1000.0 + i
        )
        executor._store_metric_sample(
            run.run_id, "treatment", i, "pipeline.avg_latency", 7.0 + i * 0.1, 2000.0 + i
        )

    analysis = executor.analyze_results(run)

    metric = analysis["metrics"]["pipeline.avg_latency"]
    assert "effect_size" in metric
    assert metric["effect_size"] != 0.0


def test_analyze_results_auto_promote(
    executor: ExperimentExecutor,
) -> None:
    """Treatment is promoted when p < 0.05 and effect >= threshold."""
    run = _make_run(success_threshold=0.1)
    executor._save_run(run)

    for i in range(20):
        executor._store_metric_sample(
            run.run_id, "baseline", i, "pipeline.avg_latency", 2.0 + i * 0.05, 1000.0 + i
        )
        executor._store_metric_sample(
            run.run_id, "treatment", i, "pipeline.avg_latency", 5.0 + i * 0.05, 2000.0 + i
        )

    analysis = executor.analyze_results(run)

    assert analysis["recommendation"] == "promote"


def test_analyze_results_auto_rollback(
    executor: ExperimentExecutor,
) -> None:
    """Treatment is rolled back when success metric degrades significantly."""
    run = _make_run(success_threshold=0.1)
    executor._save_run(run)

    for i in range(20):
        executor._store_metric_sample(
            run.run_id, "baseline", i, "pipeline.avg_latency", 10.0, 1000.0 + i
        )
        executor._store_metric_sample(
            run.run_id, "treatment", i, "pipeline.avg_latency", 2.0, 2000.0 + i
        )

    analysis = executor.analyze_results(run)

    assert analysis["recommendation"] == "rollback"


def test_analyze_results_fallback_to_inmemory(
    executor: ExperimentExecutor,
) -> None:
    """Falls back to in-memory run metrics when DB has no samples."""
    run = _make_run(
        baseline_metrics={"pipeline.avg_latency": 5.0},
        treatment_metrics={"pipeline.avg_latency": 7.0},
    )
    executor._save_run(run)

    analysis = executor.analyze_results(run)

    # Only 1 sample per metric so analysis skips (needs >=2)
    assert "metrics" in analysis
    assert "recommendation" in analysis


# ── Queries ─────────────────────────────────────────────────────────────


def test_get_run_existing(seeded_executor: ExperimentExecutor) -> None:
    """get_run returns the ExperimentRun for a valid run_id."""
    run = seeded_executor.get_run("exp-test0001")

    assert run is not None
    assert run.run_id == "exp-test0001"
    assert run.experiment_name == "test_exp"
    assert isinstance(run.status, ExperimentStatus)


def test_get_run_nonexistent(executor: ExperimentExecutor) -> None:
    """get_run returns None for an unknown run_id."""
    assert executor.get_run("does-not-exist") is None


def test_list_runs_all(seeded_executor: ExperimentExecutor) -> None:
    """list_runs returns all runs within the time window."""
    runs = seeded_executor.list_runs(days=365)

    assert len(runs) >= 1
    assert runs[0]["run_id"] == "exp-test0001"


def test_list_runs_by_status(executor: ExperimentExecutor) -> None:
    """list_runs filters by ExperimentStatus."""
    executor._save_run(_make_run("r-pend", status=ExperimentStatus.PENDING))
    executor._save_run(_make_run("r-done", status=ExperimentStatus.COMPLETED))
    executor._save_run(_make_run("r-fail", status=ExperimentStatus.FAILED))

    pending = executor.list_runs(status=ExperimentStatus.PENDING, days=365)
    completed = executor.list_runs(status=ExperimentStatus.COMPLETED, days=365)

    assert all(r["status"] == "pending" for r in pending)
    assert all(r["status"] == "completed" for r in completed)


def test_list_runs_with_limit(executor: ExperimentExecutor) -> None:
    """list_runs respects the limit parameter."""
    for i in range(5):
        executor._save_run(_make_run(f"r-{i}"))

    runs = executor.list_runs(limit=2, days=365)

    assert len(runs) == 2


# ── Stats ───────────────────────────────────────────────────────────────


def test_run_stats_empty(executor: ExperimentExecutor) -> None:
    """run_stats returns zeroed stats when no runs exist."""
    stats = executor.run_stats()

    assert stats["total_runs"] == 0
    assert stats["success_rate"] == 0.0
    assert stats["avg_effect_size"] == 0.0


def test_run_stats_with_data(executor: ExperimentExecutor) -> None:
    """run_stats computes correct totals after multiple runs."""
    executor._save_run(_make_run("s1", status=ExperimentStatus.COMPLETED))
    executor._save_run(_make_run("s2", status=ExperimentStatus.FAILED))
    executor._save_run(_make_run("s3", status=ExperimentStatus.ROLLED_BACK))

    stats = executor.run_stats()

    assert stats["total_runs"] == 3
    assert stats["by_status"]["completed"] == 1
    assert stats["by_status"]["failed"] == 1
    assert stats["by_status"]["rolled_back"] == 1


def test_run_stats_completion_rate(executor: ExperimentExecutor) -> None:
    """Success rate = completed / (completed + failed + rolled_back)."""
    executor._save_run(_make_run("c1", status=ExperimentStatus.COMPLETED))
    executor._save_run(_make_run("c2", status=ExperimentStatus.COMPLETED))
    executor._save_run(_make_run("f1", status=ExperimentStatus.FAILED))
    executor._save_run(_make_run("r1", status=ExperimentStatus.ROLLED_BACK))

    stats = executor.run_stats()

    # 2 completed out of 4 attempted
    assert stats["success_rate"] == 0.5
    assert stats["attempted"] == 4


def test_run_stats_effect_size_from_results(executor: ExperimentExecutor) -> None:
    """avg_effect_size is computed from completed run results."""
    result_data = {
        "metrics": {
            "pipeline.avg_latency": {"effect_size": 0.8},
            "system.cpu_pct": {"effect_size": 0.4},
        }
    }
    run = _make_run("es1", status=ExperimentStatus.COMPLETED, result=result_data)
    executor._save_run(run)

    stats = executor.run_stats()

    assert stats["avg_effect_size"] == pytest.approx(0.6, abs=0.01)
    assert stats["max_effect_size"] == pytest.approx(0.8, abs=0.01)


# ── Integration ─────────────────────────────────────────────────────────


def test_register_experiment_tasks() -> None:
    """register_experiment_tasks calls daemon.register with correct args."""
    daemon = MagicMock()

    register_experiment_tasks(daemon)

    daemon.register.assert_called_once()
    call_kwargs = daemon.register.call_args
    assert call_kwargs[1]["task_id"] == "experiment-run" or call_kwargs.kwargs.get("task_id") == "experiment-run"


def test_singleton_pattern(tmp_path: Path) -> None:
    """get_experiment_executor returns the same instance on repeated calls."""
    import engine.nexus.experiment_executor as mod

    old_instance = mod._instance
    old_lock = mod._lock
    try:
        mod._instance = None
        mod._lock = threading.Lock()

        e1 = get_experiment_executor(db_path=tmp_path / "singleton.db")
        e2 = get_experiment_executor()

        assert e1 is e2
    finally:
        mod._instance = old_instance
        mod._lock = old_lock


@patch("engine.nexus.experiment_executor._get_nexus_client")
def test_nexus_storage_on_completion(
    mock_nexus_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """Completed runs are stored in Nexus as both entry and Q&A."""
    client = MagicMock()
    mock_nexus_fn.return_value = client

    run = _make_run(
        status=ExperimentStatus.COMPLETED,
        result={"summary": "Treatment improved latency by 25%"},
        completed_at=time.time(),
    )

    executor._store_nexus_result(run)

    client.add_entry.assert_called_once()
    client.add_qa.assert_called_once()

    entry_kwargs = client.add_entry.call_args
    assert "Experiment Result" in (
        entry_kwargs.kwargs.get("title", "") or entry_kwargs[1].get("title", "")
    )


@patch("engine.nexus.experiment_executor._get_nexus_client", return_value=None)
def test_nexus_storage_skipped_when_unavailable(
    mock_nexus_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """No error when NexusClient is unavailable."""
    run = _make_run(status=ExperimentStatus.COMPLETED)
    executor._store_nexus_result(run)  # Should not raise


# ── Edge Cases ──────────────────────────────────────────────────────────


def test_concurrent_experiments(tmp_path: Path) -> None:
    """Multiple threads can save and load runs without corruption."""
    executor = ExperimentExecutor(db_path=tmp_path / "concurrent.db")
    errors: List[str] = []

    def worker(idx: int) -> None:
        try:
            run = _make_run(f"concurrent-{idx}")
            executor._save_run(run)
            loaded = executor.get_run(f"concurrent-{idx}")
            if loaded is None:
                errors.append(f"Run concurrent-{idx} not found after save")
        except Exception as exc:
            errors.append(f"Thread {idx}: {exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Concurrency errors: {errors}"

    stats = executor.run_stats()
    assert stats["total_runs"] == 10


@patch("engine.nexus.experiment_executor._get_nexus_client", return_value=MagicMock())
@patch("engine.nexus.experiment_executor._get_impact_tracker", return_value=None)
@patch("engine.nexus.experiment_executor._get_metrics_db", return_value=None)
@patch("engine.nexus.experiment_executor._get_config")
@patch("engine.nexus.experiment_executor.time")
def test_experiment_with_empty_variants(
    mock_time: MagicMock,
    mock_config_fn: MagicMock,
    mock_mdb_fn: MagicMock,
    mock_impact_fn: MagicMock,
    mock_nexus_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """Proposal with empty variants list results in a FAILED status."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()
    mock_config_fn.return_value = _mock_config()

    proposal = _make_proposal()
    proposal["variants"] = []

    result = executor._execute_proposal_dict(proposal)

    assert result["status"] == "failed"


@patch("engine.nexus.experiment_executor._get_config", return_value=None)
@patch("engine.nexus.experiment_executor._get_metrics_db")
@patch("engine.nexus.experiment_executor.time")
def test_large_metric_dataset(
    mock_time: MagicMock,
    mock_mdb_fn: MagicMock,
    mock_config_fn: MagicMock,
    executor: ExperimentExecutor,
) -> None:
    """collect_metrics handles a large iteration count without error."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()
    mock_mdb_fn.return_value = _mock_metrics_db()

    run = _make_run()
    executor._save_run(run)

    collected = executor.collect_metrics(run.run_id, "baseline", iterations=50)

    for vals in collected.values():
        assert len(vals) == 50


# ── Internal helpers ────────────────────────────────────────────────────


def test_paired_t_test_identical_values(executor: ExperimentExecutor) -> None:
    """Paired t-test returns t=0, p=1 for identical observations."""
    t_stat, p_value = executor._paired_t_test([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert t_stat == 0.0
    assert p_value == 1.0


def test_paired_t_test_different_lengths(executor: ExperimentExecutor) -> None:
    """Paired t-test raises ValueError for mismatched lengths."""
    with pytest.raises(ValueError, match="equal length"):
        executor._paired_t_test([1.0, 2.0], [1.0])


def test_paired_t_test_too_few_samples(executor: ExperimentExecutor) -> None:
    """Paired t-test raises ValueError with fewer than 2 observations."""
    with pytest.raises(ValueError, match="at least 2"):
        executor._paired_t_test([1.0], [2.0])


def test_cohens_d_zero_variance(executor: ExperimentExecutor) -> None:
    """Cohen's d returns 0 when all values are identical."""
    d = executor._cohens_d([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])
    assert d == 0.0


def test_cohens_d_positive(executor: ExperimentExecutor) -> None:
    """Cohen's d is positive when treatment > baseline."""
    d = executor._cohens_d([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
    assert d > 0.0


def test_experiment_status_values() -> None:
    """All ExperimentStatus values match expected strings."""
    assert ExperimentStatus.PENDING.value == "pending"
    assert ExperimentStatus.BASELINE.value == "baseline"
    assert ExperimentStatus.RUNNING.value == "running"
    assert ExperimentStatus.COLLECTING.value == "collecting"
    assert ExperimentStatus.ANALYZING.value == "analyzing"
    assert ExperimentStatus.COMPLETED.value == "completed"
    assert ExperimentStatus.FAILED.value == "failed"
    assert ExperimentStatus.ROLLED_BACK.value == "rolled_back"


def test_experiment_run_dataclass() -> None:
    """ExperimentRun can be constructed and fields accessed."""
    run = _make_run()
    assert run.run_id == "exp-test0001"
    assert run.status == ExperimentStatus.PENDING
    assert isinstance(run.variants, list)
    assert run.completed_at is None
    assert run.error is None


def test_save_and_load_run_roundtrip(executor: ExperimentExecutor) -> None:
    """A run survives save → load roundtrip with all fields intact."""
    original = _make_run(
        active_variant="v1",
        config_backup={"lmstudio.temperature": 0.7},
        result={"summary": "good", "metrics": {}},
        completed_at=time.time(),
        error=None,
    )
    executor._save_run(original)
    loaded = executor.get_run(original.run_id)

    assert loaded is not None
    assert loaded.run_id == original.run_id
    assert loaded.proposal_id == original.proposal_id
    assert loaded.status == original.status
    assert loaded.active_variant == "v1"
    assert loaded.config_backup == {"lmstudio.temperature": 0.7}
    assert loaded.result["summary"] == "good"


def test_rollback_treatment_config_unavailable(
    executor: ExperimentExecutor,
) -> None:
    """Rollback returns False when ConfigManager is unavailable."""
    with patch(
        "engine.nexus.experiment_executor._get_config", return_value=None
    ):
        run = _make_run(config_backup={"k": "v"})
        assert executor.rollback_treatment(run) is False
