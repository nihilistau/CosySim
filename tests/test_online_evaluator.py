"""Comprehensive tests for engine.nexus.online_evaluator.

Covers initialization, shadow/canary/AB evaluations, metrics computation,
decision logic, model promotion/rollback, session management, queries,
and integration points (scheduler, singleton, training flywheel).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.online_evaluator import (
    EvalDecision,
    EvalMetrics,
    EvalMode,
    EvalSample,
    EvalSession,
    EvalStatus,
    OnlineEvaluator,
    register_online_eval_tasks,
)


# ──── Fixtures ────


@pytest.fixture()
def evaluator(tmp_path: Path) -> OnlineEvaluator:
    """Create a fresh OnlineEvaluator backed by a temporary database."""
    db = tmp_path / "test_eval.db"
    with (
        patch("engine.nexus.online_evaluator._get_config", return_value=None),
        patch("engine.nexus.online_evaluator._get_flywheel", return_value=None),
        patch("engine.nexus.online_evaluator._get_impact_tracker", return_value=None),
        patch("engine.nexus.online_evaluator._get_nexus_client", return_value=None),
    ):
        ev = OnlineEvaluator(db_path=db)
    return ev


@pytest.fixture()
def shadow_session(evaluator: OnlineEvaluator) -> EvalSession:
    """Start and return a shadow session on the evaluator."""
    return evaluator.start_shadow(
        candidate_model="candidate-7b",
        production_model="production-13b",
        min_samples=5,
        max_duration_hours=1.0,
        promote_threshold=0.05,
    )


def _add_samples(
    evaluator: OnlineEvaluator,
    session_id: str,
    count: int = 10,
    prod_latency: float = 100.0,
    cand_latency: float = 80.0,
    quality: float = 0.8,
    preferred: str = "candidate",
) -> list[str]:
    """Insert *count* shadow samples and return their sample IDs."""
    ids: list[str] = []
    for i in range(count):
        sid = evaluator.shadow_evaluate(
            request_text=f"request-{i}",
            production_response=f"prod-resp-{i}",
            candidate_response=f"cand-resp-{i}",
            production_latency_ms=prod_latency,
            candidate_latency_ms=cand_latency,
            quality_score=quality,
            preferred=preferred,
            session_id=session_id,
        )
        assert sid is not None
        ids.append(sid)
    return ids


# ──── Initialization ────


def test_creates_database(tmp_path: Path) -> None:
    """Database file is created on disk during initialization."""
    db = tmp_path / "sub" / "eval.db"
    with patch("engine.nexus.online_evaluator._get_config", return_value=None):
        OnlineEvaluator(db_path=db)
    assert db.exists()


def test_wal_mode(evaluator: OnlineEvaluator) -> None:
    """Database uses WAL journal mode for concurrent-read performance."""
    conn = evaluator._get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_tables_created(evaluator: OnlineEvaluator) -> None:
    """All three schema tables are created on init."""
    conn = evaluator._get_conn()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "eval_sessions" in names
    assert "eval_samples" in names
    assert "eval_feedback" in names


# ──── Shadow Evaluation ────


def test_start_shadow_creates_session(evaluator: OnlineEvaluator) -> None:
    """start_shadow persists a RUNNING SHADOW session in the database."""
    session = evaluator.start_shadow(
        candidate_model="cand-7b",
        production_model="prod-13b",
        min_samples=10,
    )

    assert session.mode == EvalMode.SHADOW
    assert session.status == EvalStatus.RUNNING
    assert session.candidate_model == "cand-7b"
    assert session.production_model == "prod-13b"
    assert session.traffic_percentage == 0.0
    assert session.min_samples == 10

    loaded = evaluator.get_session(session.session_id)
    assert loaded is not None
    assert loaded.session_id == session.session_id


def test_shadow_evaluate_records_sample(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """shadow_evaluate inserts a sample row for the given session."""
    sid = evaluator.shadow_evaluate(
        request_text="Hello",
        production_response="Hi from prod",
        candidate_response="Hi from cand",
        production_latency_ms=120.0,
        candidate_latency_ms=90.0,
        session_id=shadow_session.session_id,
    )

    assert sid is not None
    assert sid.startswith("samp-")

    samples = evaluator.session_samples(shadow_session.session_id)
    assert len(samples) == 1
    assert samples[0]["request_text"] == "Hello"


def test_shadow_multiple_samples(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """Multiple samples accumulate correctly for a session."""
    ids = _add_samples(evaluator, shadow_session.session_id, count=5)
    assert len(ids) == 5

    samples = evaluator.session_samples(shadow_session.session_id)
    assert len(samples) == 5


def test_shadow_auto_check_continue(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """auto_check returns CONTINUE when min_samples is not met."""
    _add_samples(evaluator, shadow_session.session_id, count=2)

    results = evaluator.auto_check()
    assert len(results) == 1
    assert results[0]["decision"] == "continue"


def test_shadow_auto_check_promote(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """auto_check promotes when quality exceeds threshold with enough samples."""
    # Production quality=0.5 (preferred="production"), candidate quality=0.8 (preferred="candidate")
    # quality_improvement = (0.8 - 0.5) / 0.5 = 0.60 > 0.05 threshold → PROMOTE
    for i in range(3):
        evaluator.shadow_evaluate(
            request_text=f"req-{i}",
            production_response=f"prod-{i}",
            candidate_response=f"cand-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=80.0,
            quality_score=0.5,
            preferred="production",
            session_id=shadow_session.session_id,
        )
    for i in range(3):
        evaluator.shadow_evaluate(
            request_text=f"req-p-{i}",
            production_response=f"prod-p-{i}",
            candidate_response=f"cand-p-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=80.0,
            quality_score=0.8,
            preferred="candidate",
            session_id=shadow_session.session_id,
        )

    with patch("engine.nexus.online_evaluator._get_config", return_value=None):
        results = evaluator.auto_check()
    assert len(results) == 1
    assert results[0]["decision"] == "promote"


def test_shadow_dpo_preference_data(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """Preferred samples forward to TrainingFlywheel for DPO collection."""
    mock_fw = MagicMock()
    with patch(
        "engine.nexus.online_evaluator._get_flywheel", return_value=mock_fw
    ):
        evaluator.shadow_evaluate(
            request_text="prompt",
            production_response="prod-answer",
            candidate_response="cand-answer",
            production_latency_ms=100.0,
            candidate_latency_ms=80.0,
            preferred="candidate",
            session_id=shadow_session.session_id,
        )

    mock_fw.collect_preference.assert_called_once_with(
        prompt="prompt",
        chosen="cand-answer",
        rejected="prod-answer",
        model="candidate-7b",
    )


# ──── Canary Evaluation ────


def test_start_canary_creates_session(evaluator: OnlineEvaluator) -> None:
    """start_canary persists a RUNNING CANARY session with traffic pct."""
    session = evaluator.start_canary(
        candidate_model="cand-7b",
        traffic_percentage=0.10,
        production_model="prod-13b",
        min_samples=20,
        degradation_threshold=0.15,
    )

    assert session.mode == EvalMode.CANARY
    assert session.status == EvalStatus.RUNNING
    assert session.traffic_percentage == 0.10
    assert session.degradation_threshold == 0.15


def test_canary_traffic_routing(evaluator: OnlineEvaluator) -> None:
    """should_use_candidate routes probabilistically for canary sessions."""
    session = evaluator.start_canary(
        candidate_model="cand-7b",
        traffic_percentage=1.0,
        production_model="prod-13b",
    )
    # traffic_percentage=1.0 → always candidate
    assert evaluator.should_use_candidate(session.session_id) is True

    session2 = evaluator.start_canary(
        candidate_model="cand-small",
        traffic_percentage=0.0,
        production_model="prod-13b",
    )
    # traffic_percentage=0.0 → never candidate
    assert evaluator.should_use_candidate(session2.session_id) is False


def test_canary_degradation_rollback(evaluator: OnlineEvaluator) -> None:
    """Canary session rolls back when quality degrades beyond threshold."""
    session = evaluator.start_canary(
        candidate_model="bad-model",
        traffic_percentage=0.05,
        production_model="prod-13b",
        min_samples=3,
        degradation_threshold=0.10,
    )
    # Production quality=0.8, candidate quality=0.3
    # quality_improvement = (0.3 - 0.8)/0.8 = -0.625 < -0.10 → ROLLBACK
    for i in range(2):
        evaluator.shadow_evaluate(
            request_text=f"req-{i}",
            production_response=f"prod-{i}",
            candidate_response=f"cand-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=200.0,
            quality_score=0.8,
            preferred="production",
            session_id=session.session_id,
        )
    for i in range(2):
        evaluator.shadow_evaluate(
            request_text=f"req-c-{i}",
            production_response=f"prod-c-{i}",
            candidate_response=f"cand-c-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=200.0,
            quality_score=0.3,
            preferred="candidate",
            session_id=session.session_id,
        )

    decision = evaluator.evaluate_decision(session.session_id)
    assert decision == EvalDecision.ROLLBACK


def test_canary_success_promote(evaluator: OnlineEvaluator) -> None:
    """Canary session promotes when candidate quality exceeds threshold."""
    session = evaluator.start_canary(
        candidate_model="great-model",
        traffic_percentage=0.10,
        production_model="prod-13b",
        min_samples=4,
    )
    # prod quality=0.5, cand quality=0.9
    # quality_improvement = (0.9 - 0.5)/0.5 = 0.80 > 0.05 → PROMOTE
    for i in range(3):
        evaluator.shadow_evaluate(
            request_text=f"r-{i}",
            production_response=f"p-{i}",
            candidate_response=f"c-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=80.0,
            quality_score=0.5,
            preferred="production",
            session_id=session.session_id,
        )
    for i in range(3):
        evaluator.shadow_evaluate(
            request_text=f"rc-{i}",
            production_response=f"pc-{i}",
            candidate_response=f"cc-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=80.0,
            quality_score=0.9,
            preferred="candidate",
            session_id=session.session_id,
        )

    decision = evaluator.evaluate_decision(session.session_id)
    assert decision == EvalDecision.PROMOTE


def test_canary_min_samples_not_met(evaluator: OnlineEvaluator) -> None:
    """Decision is CONTINUE when min_samples has not been reached."""
    session = evaluator.start_canary(
        candidate_model="cand-7b",
        traffic_percentage=0.10,
        production_model="prod-13b",
        min_samples=100,
    )
    _add_samples(evaluator, session.session_id, count=5)

    decision = evaluator.evaluate_decision(session.session_id)
    assert decision == EvalDecision.CONTINUE


# ──── AB Test ────


def test_start_ab_test_creates_session(evaluator: OnlineEvaluator) -> None:
    """start_ab_test persists a RUNNING AB_TEST session with 50% traffic."""
    session = evaluator.start_ab_test(
        candidate_model="ab-cand",
        production_model="ab-prod",
        min_samples=200,
        max_duration_hours=72.0,
    )

    assert session.mode == EvalMode.AB_TEST
    assert session.status == EvalStatus.RUNNING
    assert session.traffic_percentage == 0.5
    assert session.min_samples == 200
    assert session.max_duration_hours == 72.0


def test_ab_test_balanced_routing(evaluator: OnlineEvaluator) -> None:
    """AB test routing converges to ~50% candidate usage over many calls."""
    session = evaluator.start_ab_test(
        candidate_model="ab-cand",
        production_model="ab-prod",
    )
    candidate_count = sum(
        1 for _ in range(1000)
        if evaluator.should_use_candidate(session.session_id)
    )
    # With 50% traffic, expect ~500 ± tolerance
    assert 350 < candidate_count < 650


def test_ab_test_sufficient_samples(evaluator: OnlineEvaluator) -> None:
    """AB test with enough good-quality samples can promote."""
    session = evaluator.start_ab_test(
        candidate_model="ab-cand",
        production_model="ab-prod",
        min_samples=4,
    )
    for i in range(3):
        evaluator.shadow_evaluate(
            request_text=f"r-{i}",
            production_response=f"p-{i}",
            candidate_response=f"c-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=70.0,
            quality_score=0.4,
            preferred="production",
            session_id=session.session_id,
        )
    for i in range(3):
        evaluator.shadow_evaluate(
            request_text=f"r2-{i}",
            production_response=f"p2-{i}",
            candidate_response=f"c2-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=70.0,
            quality_score=0.9,
            preferred="candidate",
            session_id=session.session_id,
        )

    decision = evaluator.evaluate_decision(session.session_id)
    assert decision == EvalDecision.PROMOTE


def test_ab_test_inconclusive(evaluator: OnlineEvaluator) -> None:
    """AB test is INCONCLUSIVE when expired with similar quality."""
    session = evaluator.start_ab_test(
        candidate_model="ab-cand",
        production_model="ab-prod",
        min_samples=4,
        max_duration_hours=0.0,  # already expired
    )
    # Equal quality on both sides — no preferred → scores go to both pools
    for i in range(5):
        evaluator.shadow_evaluate(
            request_text=f"req-{i}",
            production_response=f"prod-{i}",
            candidate_response=f"cand-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=100.0,
            quality_score=0.7,
            preferred=None,
            session_id=session.session_id,
        )

    decision = evaluator.evaluate_decision(session.session_id)
    assert decision == EvalDecision.INCONCLUSIVE


# ──── Metrics Computation ────


def test_compute_metrics_accuracy(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """compute_metrics returns correct averages for latency and quality."""
    for i in range(4):
        evaluator.shadow_evaluate(
            request_text=f"req-{i}",
            production_response=f"prod-{i}",
            candidate_response=f"cand-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=80.0,
            quality_score=0.7,
            preferred="candidate",
            session_id=shadow_session.session_id,
        )

    metrics = evaluator.compute_metrics(shadow_session.session_id)
    assert metrics.total_samples == 4
    assert metrics.production_avg_latency == pytest.approx(100.0)
    assert metrics.candidate_avg_latency == pytest.approx(80.0)
    assert metrics.candidate_preference_rate == pytest.approx(1.0)


def test_compute_metrics_latency_percentiles(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """P95 latency percentiles are computed correctly from samples."""
    latencies = [50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0, 130.0, 500.0]
    for i, lat in enumerate(latencies):
        evaluator.shadow_evaluate(
            request_text=f"req-{i}",
            production_response=f"prod-{i}",
            candidate_response=f"cand-{i}",
            production_latency_ms=lat,
            candidate_latency_ms=lat * 0.9,
            session_id=shadow_session.session_id,
        )

    metrics = evaluator.compute_metrics(shadow_session.session_id)
    assert metrics.total_samples == 10
    # P95 should be high due to the 500ms outlier
    assert metrics.production_p95_latency > 100.0
    assert metrics.candidate_p95_latency > 90.0


def test_compute_metrics_error_rate(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """Empty responses count as errors in error rate calculation."""
    # 2 normal samples + 1 with empty candidate response
    evaluator.shadow_evaluate(
        request_text="ok-1",
        production_response="good",
        candidate_response="also good",
        production_latency_ms=100.0,
        candidate_latency_ms=80.0,
        session_id=shadow_session.session_id,
    )
    evaluator.shadow_evaluate(
        request_text="ok-2",
        production_response="fine",
        candidate_response="fine too",
        production_latency_ms=100.0,
        candidate_latency_ms=80.0,
        session_id=shadow_session.session_id,
    )
    evaluator.shadow_evaluate(
        request_text="err",
        production_response="good",
        candidate_response="",  # empty → error
        production_latency_ms=100.0,
        candidate_latency_ms=80.0,
        session_id=shadow_session.session_id,
    )

    metrics = evaluator.compute_metrics(shadow_session.session_id)
    assert metrics.production_error_rate == pytest.approx(0.0)
    assert metrics.candidate_error_rate == pytest.approx(1.0 / 3.0)


def test_compute_metrics_empty_session(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """compute_metrics returns zeroes for a session with no samples."""
    metrics = evaluator.compute_metrics(shadow_session.session_id)
    assert metrics.total_samples == 0
    assert metrics.production_avg_latency == 0.0
    assert metrics.candidate_avg_latency == 0.0
    assert metrics.quality_improvement_pct == 0.0


def test_compute_metrics_quality_scores(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """Quality scores split by preference for production/candidate averages."""
    # production-preferred score=0.3, candidate-preferred score=0.9
    evaluator.shadow_evaluate(
        request_text="q1",
        production_response="p1",
        candidate_response="c1",
        production_latency_ms=100.0,
        candidate_latency_ms=80.0,
        quality_score=0.3,
        preferred="production",
        session_id=shadow_session.session_id,
    )
    evaluator.shadow_evaluate(
        request_text="q2",
        production_response="p2",
        candidate_response="c2",
        production_latency_ms=100.0,
        candidate_latency_ms=80.0,
        quality_score=0.9,
        preferred="candidate",
        session_id=shadow_session.session_id,
    )

    metrics = evaluator.compute_metrics(shadow_session.session_id)
    assert metrics.production_avg_quality == pytest.approx(0.3)
    assert metrics.candidate_avg_quality == pytest.approx(0.9)
    # (0.9 - 0.3) / 0.3 = 2.0
    assert metrics.quality_improvement_pct == pytest.approx(2.0)


# ──── Decision Logic ────


def test_evaluate_decision_promote(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """evaluate_decision returns PROMOTE when quality exceeds threshold."""
    for i in range(3):
        evaluator.shadow_evaluate(
            request_text=f"r-{i}",
            production_response=f"p-{i}",
            candidate_response=f"c-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=80.0,
            quality_score=0.4,
            preferred="production",
            session_id=shadow_session.session_id,
        )
    for i in range(3):
        evaluator.shadow_evaluate(
            request_text=f"r2-{i}",
            production_response=f"p2-{i}",
            candidate_response=f"c2-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=80.0,
            quality_score=0.8,
            preferred="candidate",
            session_id=shadow_session.session_id,
        )

    decision = evaluator.evaluate_decision(shadow_session.session_id)
    assert decision == EvalDecision.PROMOTE


def test_evaluate_decision_rollback(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """evaluate_decision returns ROLLBACK on severe quality degradation."""
    for i in range(3):
        evaluator.shadow_evaluate(
            request_text=f"r-{i}",
            production_response=f"p-{i}",
            candidate_response=f"c-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=200.0,
            quality_score=0.9,
            preferred="production",
            session_id=shadow_session.session_id,
        )
    for i in range(3):
        evaluator.shadow_evaluate(
            request_text=f"r2-{i}",
            production_response=f"p2-{i}",
            candidate_response=f"c2-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=200.0,
            quality_score=0.3,
            preferred="candidate",
            session_id=shadow_session.session_id,
        )

    decision = evaluator.evaluate_decision(shadow_session.session_id)
    assert decision == EvalDecision.ROLLBACK


def test_evaluate_decision_continue(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """evaluate_decision returns CONTINUE when min_samples not reached."""
    _add_samples(evaluator, shadow_session.session_id, count=2)

    decision = evaluator.evaluate_decision(shadow_session.session_id)
    assert decision == EvalDecision.CONTINUE


def test_evaluate_decision_inconclusive(evaluator: OnlineEvaluator) -> None:
    """evaluate_decision returns INCONCLUSIVE when session is expired."""
    session = evaluator.start_shadow(
        candidate_model="cand-7b",
        production_model="prod-13b",
        min_samples=4,
        max_duration_hours=0.0,
    )
    # No preferred → quality goes to both pools equally → 0% improvement
    for i in range(5):
        evaluator.shadow_evaluate(
            request_text=f"r-{i}",
            production_response=f"p-{i}",
            candidate_response=f"c-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=100.0,
            quality_score=0.7,
            preferred=None,
            session_id=session.session_id,
        )

    decision = evaluator.evaluate_decision(session.session_id)
    assert decision == EvalDecision.INCONCLUSIVE


def test_evaluate_decision_expired(evaluator: OnlineEvaluator) -> None:
    """Expired session with neutral metrics yields INCONCLUSIVE."""
    session = evaluator.start_shadow(
        candidate_model="cand-7b",
        production_model="prod-13b",
        min_samples=3,
        max_duration_hours=0.0,  # already expired
    )
    # Equal quality on both sides — no promote or rollback trigger
    for i in range(4):
        evaluator.shadow_evaluate(
            request_text=f"r-{i}",
            production_response=f"p-{i}",
            candidate_response=f"c-{i}",
            production_latency_ms=100.0,
            candidate_latency_ms=100.0,
            quality_score=0.5,
            session_id=session.session_id,
        )

    decision = evaluator.evaluate_decision(session.session_id)
    assert decision == EvalDecision.INCONCLUSIVE


def test_auto_check_multiple_sessions(evaluator: OnlineEvaluator) -> None:
    """auto_check evaluates all running sessions at once."""
    s1 = evaluator.start_shadow(
        candidate_model="cand-a", production_model="prod", min_samples=3
    )
    s2 = evaluator.start_shadow(
        candidate_model="cand-b", production_model="prod", min_samples=3
    )

    _add_samples(evaluator, s1.session_id, count=2)
    _add_samples(evaluator, s2.session_id, count=2)

    results = evaluator.auto_check()
    assert len(results) == 2
    session_ids = {r["session_id"] for r in results}
    assert s1.session_id in session_ids
    assert s2.session_id in session_ids


# ──── Model Management ────


def test_promote_model_success(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """promote_model updates session to COMPLETED with PROMOTE decision."""
    _add_samples(evaluator, shadow_session.session_id, count=5)

    with (
        patch("engine.nexus.online_evaluator._get_config", return_value=None),
        patch("engine.nexus.online_evaluator._get_impact_tracker", return_value=None),
        patch("engine.nexus.online_evaluator._get_nexus_client", return_value=None),
    ):
        result = evaluator.promote_model(shadow_session.session_id)

    assert result["promoted"] is True
    assert result["model"] == "candidate-7b"

    session = evaluator.get_session(shadow_session.session_id)
    assert session is not None
    assert session.status == EvalStatus.COMPLETED
    assert session.decision == EvalDecision.PROMOTE


def test_promote_model_not_found(evaluator: OnlineEvaluator) -> None:
    """promote_model returns error for a nonexistent session."""
    result = evaluator.promote_model("nonexistent-session")
    assert result["promoted"] is False
    assert "not found" in result["error"]


def test_rollback_model_success(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """rollback_model restores production model and completes session."""
    _add_samples(evaluator, shadow_session.session_id, count=5)

    with (
        patch("engine.nexus.online_evaluator._get_config", return_value=None),
        patch("engine.nexus.online_evaluator._get_impact_tracker", return_value=None),
    ):
        result = evaluator.rollback_model(shadow_session.session_id)

    assert result["rolled_back"] is True
    assert result["model"] == "production-13b"

    session = evaluator.get_session(shadow_session.session_id)
    assert session is not None
    assert session.status == EvalStatus.COMPLETED
    assert session.decision == EvalDecision.ROLLBACK


def test_rollback_model_not_found(evaluator: OnlineEvaluator) -> None:
    """rollback_model returns error for a nonexistent session."""
    result = evaluator.rollback_model("nonexistent-session")
    assert result["rolled_back"] is False
    assert "not found" in result["error"]


# ──── Session Management ────


def test_stop_session(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """stop_session completes a running session and returns summary."""
    _add_samples(evaluator, shadow_session.session_id, count=3)

    result = evaluator.stop_session(shadow_session.session_id)
    assert result["session_id"] == shadow_session.session_id
    assert "decision" in result
    assert "reason" in result

    session = evaluator.get_session(shadow_session.session_id)
    assert session is not None
    assert session.status == EvalStatus.COMPLETED


def test_stop_session_force_decision(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """stop_session with force_decision overrides computed decision."""
    result = evaluator.stop_session(
        shadow_session.session_id, force_decision=EvalDecision.ROLLBACK
    )
    assert result["decision"] == "rollback"
    assert "Forced decision" in result["reason"]


def test_get_session_existing(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """get_session returns the session when it exists."""
    session = evaluator.get_session(shadow_session.session_id)
    assert session is not None
    assert session.session_id == shadow_session.session_id
    assert session.mode == EvalMode.SHADOW


def test_get_session_nonexistent(evaluator: OnlineEvaluator) -> None:
    """get_session returns None for unknown session IDs."""
    assert evaluator.get_session("does-not-exist") is None


def test_active_sessions_filter(evaluator: OnlineEvaluator) -> None:
    """active_sessions only returns RUNNING sessions."""
    s1 = evaluator.start_shadow(
        candidate_model="cand-a", production_model="prod"
    )
    s2 = evaluator.start_shadow(
        candidate_model="cand-b", production_model="prod"
    )
    # Stop s1
    evaluator.stop_session(s1.session_id, force_decision=EvalDecision.INCONCLUSIVE)

    active = evaluator.active_sessions()
    active_ids = {s["session_id"] for s in active}
    assert s1.session_id not in active_ids
    assert s2.session_id in active_ids


# ──── Queries ────


def test_list_sessions_all(evaluator: OnlineEvaluator) -> None:
    """list_sessions returns all sessions within the time window."""
    evaluator.start_shadow(candidate_model="a", production_model="p")
    evaluator.start_shadow(candidate_model="b", production_model="p")

    sessions = evaluator.list_sessions()
    assert len(sessions) == 2


def test_list_sessions_by_status(evaluator: OnlineEvaluator) -> None:
    """list_sessions filters correctly by status parameter."""
    s1 = evaluator.start_shadow(candidate_model="a", production_model="p")
    evaluator.start_shadow(candidate_model="b", production_model="p")
    evaluator.stop_session(s1.session_id, force_decision=EvalDecision.INCONCLUSIVE)

    running = evaluator.list_sessions(status=EvalStatus.RUNNING)
    assert len(running) == 1

    completed = evaluator.list_sessions(status=EvalStatus.COMPLETED)
    assert len(completed) == 1


def test_session_samples(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """session_samples returns sample dicts with deserialized metadata."""
    _add_samples(evaluator, shadow_session.session_id, count=3)

    samples = evaluator.session_samples(shadow_session.session_id)
    assert len(samples) == 3
    for sample in samples:
        assert "sample_id" in sample
        assert "request_text" in sample
        assert isinstance(sample["metadata"], dict)


def test_eval_stats(evaluator: OnlineEvaluator) -> None:
    """eval_stats provides aggregate statistics across all sessions."""
    s1 = evaluator.start_shadow(
        candidate_model="a", production_model="p", min_samples=2
    )
    s2 = evaluator.start_canary(
        candidate_model="b", production_model="p", min_samples=2
    )
    _add_samples(evaluator, s1.session_id, count=3)
    _add_samples(evaluator, s2.session_id, count=3)

    stats = evaluator.eval_stats()
    assert stats["total_sessions"] == 2
    assert stats["total_samples"] == 6
    assert "by_mode" in stats
    assert "by_status" in stats
    assert "promotion_rate" in stats
    assert "rollback_rate" in stats


# ──── Record Feedback ────


def test_record_feedback(evaluator: OnlineEvaluator) -> None:
    """record_feedback inserts a row into eval_feedback."""
    evaluator.record_feedback(
        request_id="req-123",
        quality_score=0.85,
        latency_ms=120.0,
        model="prod-13b",
        session_id=None,
        feedback_source="human",
    )

    conn = evaluator._get_conn()
    row = conn.execute("SELECT * FROM eval_feedback WHERE request_id = ?", ("req-123",)).fetchone()
    assert row is not None
    assert row["quality_score"] == pytest.approx(0.85)
    assert row["feedback_source"] == "human"


def test_record_feedback_clamps_quality(evaluator: OnlineEvaluator) -> None:
    """Quality scores are clamped to [0.0, 1.0]."""
    evaluator.record_feedback(
        request_id="high", quality_score=1.5, latency_ms=50.0
    )
    evaluator.record_feedback(
        request_id="low", quality_score=-0.5, latency_ms=50.0
    )

    conn = evaluator._get_conn()
    high = conn.execute(
        "SELECT quality_score FROM eval_feedback WHERE request_id = ?", ("high",)
    ).fetchone()
    low = conn.execute(
        "SELECT quality_score FROM eval_feedback WHERE request_id = ?", ("low",)
    ).fetchone()
    assert high["quality_score"] == pytest.approx(1.0)
    assert low["quality_score"] == pytest.approx(0.0)


# ──── Shadow with No Active Session ────


def test_shadow_evaluate_no_active_session(evaluator: OnlineEvaluator) -> None:
    """shadow_evaluate returns None when no running session exists."""
    result = evaluator.shadow_evaluate(
        request_text="orphan",
        production_response="p",
        candidate_response="c",
        production_latency_ms=100.0,
        candidate_latency_ms=80.0,
    )
    assert result is None


# ──── should_use_candidate Edge Cases ────


def test_should_use_candidate_no_session(evaluator: OnlineEvaluator) -> None:
    """should_use_candidate returns False when no session is active."""
    assert evaluator.should_use_candidate() is False


def test_should_use_candidate_shadow_mode(evaluator: OnlineEvaluator) -> None:
    """should_use_candidate returns False for SHADOW sessions (traffic=0)."""
    session = evaluator.start_shadow(
        candidate_model="cand-7b", production_model="prod-13b"
    )
    assert evaluator.should_use_candidate(session.session_id) is False


# ──── Integration ────


def test_register_online_eval_tasks() -> None:
    """register_online_eval_tasks registers 'online-eval-sweep' on daemon."""
    daemon = MagicMock()
    register_online_eval_tasks(daemon)

    daemon.register.assert_called_once()
    call_kwargs = daemon.register.call_args
    # Check both positional and keyword args
    if call_kwargs.kwargs:
        assert call_kwargs.kwargs.get("task_id") == "online-eval-sweep"
    else:
        assert call_kwargs[1].get("task_id") == "online-eval-sweep"


def test_singleton_pattern(tmp_path: Path) -> None:
    """get_online_evaluator returns the same instance on repeated calls."""
    import engine.nexus.online_evaluator as mod

    # Reset the singleton for this test
    original = mod._instance
    mod._instance = None
    try:
        with patch("engine.nexus.online_evaluator._get_config", return_value=None):
            a = mod.get_online_evaluator(db_path=tmp_path / "singleton.db")
            b = mod.get_online_evaluator()
        assert a is b
    finally:
        mod._instance = original


def test_training_flywheel_integration(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """Production preference forwards chosen/rejected to TrainingFlywheel."""
    mock_fw = MagicMock()
    with patch(
        "engine.nexus.online_evaluator._get_flywheel", return_value=mock_fw
    ):
        evaluator.shadow_evaluate(
            request_text="prompt-text",
            production_response="prod-resp",
            candidate_response="cand-resp",
            production_latency_ms=100.0,
            candidate_latency_ms=80.0,
            preferred="production",
            session_id=shadow_session.session_id,
        )

    # When production is preferred: chosen=prod, rejected=cand
    mock_fw.collect_preference.assert_called_once_with(
        prompt="prompt-text",
        chosen="prod-resp",
        rejected="cand-resp",
        model="candidate-7b",
    )


# ──── Promote / Rollback with Config ────


def test_promote_updates_config(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """promote_model calls config.set to update the primary model."""
    mock_cfg = MagicMock()
    _add_samples(evaluator, shadow_session.session_id, count=3)

    with (
        patch("engine.nexus.online_evaluator._get_config", return_value=mock_cfg),
        patch("engine.nexus.online_evaluator._get_impact_tracker", return_value=None),
        patch("engine.nexus.online_evaluator._get_nexus_client", return_value=None),
    ):
        evaluator.promote_model(shadow_session.session_id)

    mock_cfg.set.assert_called_once_with(
        "lmstudio.models.primary", "candidate-7b"
    )


def test_rollback_restores_config_when_changed(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """rollback_model restores config only when it matches candidate model."""
    mock_cfg = MagicMock()
    mock_cfg.get.return_value = "candidate-7b"  # current = candidate
    _add_samples(evaluator, shadow_session.session_id, count=3)

    with (
        patch("engine.nexus.online_evaluator._get_config", return_value=mock_cfg),
        patch("engine.nexus.online_evaluator._get_impact_tracker", return_value=None),
    ):
        evaluator.rollback_model(shadow_session.session_id)

    mock_cfg.set.assert_called_once_with(
        "lmstudio.models.primary", "production-13b"
    )


def test_stop_session_already_completed(
    evaluator: OnlineEvaluator, shadow_session: EvalSession
) -> None:
    """stop_session on an already-completed session returns status message."""
    evaluator.stop_session(
        shadow_session.session_id, force_decision=EvalDecision.INCONCLUSIVE
    )

    result = evaluator.stop_session(shadow_session.session_id)
    assert result["message"] == "Session is not active"


def test_stop_session_not_found(evaluator: OnlineEvaluator) -> None:
    """stop_session on unknown session ID returns error."""
    result = evaluator.stop_session("ghost-session")
    assert "error" in result
    assert "not found" in result["error"]
