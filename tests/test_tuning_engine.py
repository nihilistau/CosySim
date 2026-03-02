"""Tests for TuningEngine — profiles, benchmark variant generation, metrics DB."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine(tmp_path):
    """Return a fresh TuningEngine backed by a temp DB."""
    from unittest.mock import MagicMock, patch as _patch

    import engine.asset_studio.tuning_engine as te_mod
    te_mod._engine_instance = None

    mock_cfg = MagicMock()
    db_file = str(tmp_path / "tuning.db")
    mock_cfg.get.side_effect = lambda key, default=None: {
        "asset_studio.tuning_db": db_file,
        "art.output_dir": str(tmp_path / "output"),
    }.get(key, default)

    from engine.asset_studio.tuning_engine import TuningEngine
    TuningEngine._instance = None

    with _patch("engine.asset_studio.tuning_engine.get_config", return_value=mock_cfg):
        inst = TuningEngine()
        yield inst

    TuningEngine._instance = None
    te_mod._engine_instance = None


# ──── Proven profiles ─────────────────────────────────────────────────────────


def test_proven_profiles_exist():
    from engine.asset_studio.tuning_engine import PROVEN_PROFILES
    assert "proven_portrait_fast" in PROVEN_PROFILES
    assert "proven_portrait_refiner" in PROVEN_PROFILES
    assert "proven_video_wan_t2v" in PROVEN_PROFILES


def test_proven_portrait_fast_params():
    from engine.asset_studio.tuning_engine import PROVEN_PROFILES
    p = PROVEN_PROFILES["proven_portrait_fast"]["params"]
    assert p["sampler_name"] == "lcm"
    assert p["scheduler"] == "exponential"
    assert p["cfg"] == 1.5
    assert p["steps"] == 20


def test_proven_video_params():
    from engine.asset_studio.tuning_engine import PROVEN_PROFILES
    p = PROVEN_PROFILES["proven_video_wan_t2v"]["params"]
    assert p["sampler_name"] == "euler"
    assert p["scheduler"] == "simple"
    assert p["cfg"] == 1.0
    assert p["steps"] == 6


def test_all_profiles_have_builtin_flag():
    from engine.asset_studio.tuning_engine import PROVEN_PROFILES
    for pid, p in PROVEN_PROFILES.items():
        assert p.get("builtin") is True, f"{pid} missing builtin=True"
        assert "params" in p
        assert "workflow" in p


# ──── Profile CRUD ────────────────────────────────────────────────────────────


def test_get_profiles_includes_builtin(engine):
    profiles = engine.get_profiles()
    ids = [p.get("profile_id") or p.get("workflow") for p in profiles]
    # Builtin profiles appear
    assert any("portrait_fast" in (i or "") for i in ids)


def test_save_and_get_custom_profile(engine):
    saved = engine.save_profile(
        profile_id="custom_test",
        label="Custom Test",
        workflow_id="portrait_fast",
        description="Test profile",
        params={"steps": 15, "cfg": 2.0},
    )
    assert saved["profile_id"] == "custom_test"

    fetched = engine.get_profile("custom_test")
    assert fetched is not None
    assert fetched["params"]["steps"] == 15
    assert fetched["params"]["cfg"] == 2.0


def test_delete_custom_profile(engine):
    engine.save_profile("to_delete", "Del", "portrait_fast", "", {"steps": 10})
    result = engine.delete_profile("to_delete")
    assert result is True
    assert engine.get_profile("to_delete") is None


def test_cannot_delete_builtin_profile(engine):
    result = engine.delete_profile("proven_portrait_fast")
    assert result is False


# ──── Variant building ────────────────────────────────────────────────────────


def test_build_variants_no_sweep():
    from engine.asset_studio.tuning_engine import TuningEngine
    base = {"steps": 20, "cfg": 1.5}
    variants = TuningEngine.build_variants(base, {})
    assert len(variants) == 1
    assert variants[0] == base


def test_build_variants_single_sweep():
    from engine.asset_studio.tuning_engine import TuningEngine
    variants = TuningEngine.build_variants({"steps": 20}, {"cfg": [1.0, 1.5, 2.0]})
    assert len(variants) == 3
    cfgs = [v["cfg"] for v in variants]
    assert 1.0 in cfgs and 1.5 in cfgs and 2.0 in cfgs
    # Base param preserved
    assert all(v["steps"] == 20 for v in variants)


def test_build_variants_grid_sweep():
    from engine.asset_studio.tuning_engine import TuningEngine
    variants = TuningEngine.build_variants(
        {"steps": 20},
        {"cfg": [1.0, 1.5], "sampler_name": ["lcm", "euler"]},
    )
    assert len(variants) == 4
    combos = {(v["cfg"], v["sampler_name"]) for v in variants}
    assert (1.0, "lcm") in combos
    assert (1.5, "euler") in combos


def test_build_variants_base_not_mutated():
    from engine.asset_studio.tuning_engine import TuningEngine
    base = {"steps": 20, "cfg": 1.5}
    TuningEngine.build_variants(base, {"cfg": [1.0, 2.0]})
    assert base["cfg"] == 1.5  # original untouched


# ──── Job lifecycle ───────────────────────────────────────────────────────────


def test_submit_benchmark_returns_job_id(engine):
    mock_wm = MagicMock()
    mock_wm.generate.return_value = {"path": "/tmp/test.png"}
    mock_wm.check_image_quality.return_value = {"score": 7.5, "issues": [], "strengths": ["sharp"], "suggestion": ""}

    with patch("engine.asset_studio.workflow_manager.get_workflow_manager", return_value=mock_wm), \
         patch("engine.asset_studio.tuning_engine.get_config") as mc:
        mc.return_value.get.side_effect = lambda k, d=None: {"art.output_dir": "/tmp"}.get(k, d)

        job_id = engine.submit_benchmark(
            workflow_id="portrait_fast",
            prompt="test",
            base_params={"steps": 20, "cfg": 1.5},
            sweep={},
            use_vl_qc=False,
        )
    assert job_id is not None
    assert len(job_id) > 0


def test_cancel_job(engine):
    from engine.asset_studio.tuning_engine import BenchmarkJob, BenchmarkVariant
    job = BenchmarkJob(
        job_id="test",
        workflow_id="portrait_fast",
        prompt="test",
        variants=[],
        status="running",
    )
    engine._current_job = job
    result = engine.cancel_job()
    assert result is True
    assert engine._current_job.status == "cancelled"


def test_cancel_no_job(engine):
    engine._current_job = None
    result = engine.cancel_job()
    assert result is False


def test_get_job_status_none(engine):
    engine._current_job = None
    assert engine.get_job_status() is None


# ──── Metrics persistence ─────────────────────────────────────────────────────


def test_metrics_empty_db(engine):
    result = engine.get_metrics()
    assert result["total"] == 0
    assert result["runs"] == []
    assert result["sparkline"] == []


def test_persist_and_query_variant(engine):
    from engine.asset_studio.tuning_engine import BenchmarkJob, BenchmarkVariant
    job = BenchmarkJob(
        job_id="j001",
        workflow_id="portrait_fast",
        prompt="test",
        variants=[],
    )
    v = BenchmarkVariant(
        variant_id="v000",
        params={"steps": 20, "cfg": 1.5, "sampler_name": "lcm"},
        prompt="test",
        workflow_id="portrait_fast",
        status="done",
        gen_time_ms=12500,
        vl_score=8.1,
        vl_strengths=["sharp", "detailed"],
        vl_issues=["slight noise"],
        vl_suggestion="Reduce steps slightly",
    )
    engine._persist_variant(job, v)

    metrics = engine.get_metrics(workflow_id="portrait_fast")
    assert metrics["total"] == 1
    assert len(metrics["runs"]) == 1
    run = metrics["runs"][0]
    assert run["vl_score"] == pytest.approx(8.1, abs=0.01)
    assert run["gen_time_ms"] == 12500
    assert isinstance(run["params"], dict)
    assert run["params"]["sampler_name"] == "lcm"


def test_sparkline_populated(engine):
    from engine.asset_studio.tuning_engine import BenchmarkJob, BenchmarkVariant
    job = BenchmarkJob(job_id="j002", workflow_id="portrait_fast", prompt="test", variants=[])
    for i, score in enumerate([6.0, 7.0, 8.5, 7.5, 9.0]):
        v = BenchmarkVariant(
            variant_id=f"v{i:03d}",
            params={"steps": 20},
            prompt="test",
            workflow_id="portrait_fast",
            status="done",
            gen_time_ms=10000,
            vl_score=score,
        )
        engine._persist_variant(job, v)

    metrics = engine.get_metrics(workflow_id="portrait_fast")
    assert len(metrics["sparkline"]) == 5
    assert 9.0 in metrics["sparkline"]


def test_get_best_settings(engine):
    from engine.asset_studio.tuning_engine import BenchmarkJob, BenchmarkVariant
    job = BenchmarkJob(job_id="j003", workflow_id="portrait_fast", prompt="test", variants=[])
    scores = [9.2, 6.0, 8.5, 7.1, 5.5]
    for i, s in enumerate(scores):
        engine._persist_variant(job, BenchmarkVariant(
            variant_id=f"v{i:03d}",
            params={"steps": 20, "cfg": 1.0 + i * 0.5},
            prompt="test",
            workflow_id="portrait_fast",
            status="done",
            gen_time_ms=10000,
            vl_score=s,
        ))
    best = engine.get_best_settings("portrait_fast", top_n=3)
    assert len(best) == 3
    assert best[0]["vl_score"] == pytest.approx(9.2, abs=0.01)
    assert best[1]["vl_score"] == pytest.approx(8.5, abs=0.01)


def test_metrics_filter_by_min_score(engine):
    from engine.asset_studio.tuning_engine import BenchmarkJob, BenchmarkVariant
    job = BenchmarkJob(job_id="j004", workflow_id="portrait_fast", prompt="test", variants=[])
    for i, s in enumerate([4.0, 7.0, 9.0]):
        engine._persist_variant(job, BenchmarkVariant(
            variant_id=f"v{i:03d}", params={}, prompt="test",
            workflow_id="portrait_fast", status="done", gen_time_ms=1000, vl_score=s,
        ))
    result = engine.get_metrics(min_score=7.0)
    assert result["total"] == 2
    for r in result["runs"]:
        assert r["vl_score"] >= 7.0


# ──── BenchmarkJob helpers ────────────────────────────────────────────────────


def test_elapsed_ms_zero_when_not_started():
    from engine.asset_studio.tuning_engine import BenchmarkJob
    job = BenchmarkJob(job_id="x", workflow_id="wf", prompt="", variants=[])
    assert job.elapsed_ms == 0


def test_eta_ms_zero_no_progress():
    from engine.asset_studio.tuning_engine import BenchmarkJob
    job = BenchmarkJob(job_id="x", workflow_id="wf", prompt="", variants=[], total_variants=5)
    job.started_at = time.time()
    assert job.eta_ms == 0  # current_variant=0


def test_job_to_dict_complete():
    from engine.asset_studio.tuning_engine import BenchmarkJob
    job = BenchmarkJob(
        job_id="abc",
        workflow_id="portrait_fast",
        prompt="test",
        variants=[],
        status="done",
        total_variants=3,
        current_variant=3,
    )
    d = job.to_dict()
    assert d["job_id"] == "abc"
    assert d["status"] == "done"
    assert d["total_variants"] == 3
    assert "variants" in d
