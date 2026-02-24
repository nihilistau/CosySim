"""Tests for engine.observability.metrics_db."""

import os
import tempfile
from pathlib import Path

import pytest

from engine.observability.metrics_db import MetricsDB


@pytest.fixture
def db(tmp_path):
    """Create a fresh MetricsDB in a temp directory."""
    return MetricsDB(tmp_path / "test_metrics.db")


class TestSystemMetrics:
    def test_record_and_get(self, db):
        db.record_system(cpu_pct=65.0, ram_pct=42.0, gpu_vram_pct=80.0, gpu_temp_c=72.0)
        history = db.get_system_history(seconds=10)
        assert len(history) == 1
        assert history[0]["cpu_pct"] == 65.0
        assert history[0]["gpu_temp_c"] == 72.0

    def test_multiple_records(self, db):
        for i in range(5):
            db.record_system(cpu_pct=float(i * 10))
        history = db.get_system_history(seconds=10)
        assert len(history) >= 1  # timestamps may collide

    def test_prune(self, db):
        db.record_system(cpu_pct=50.0)
        pruned = db.prune_system_metrics(max_age_hours=0)  # prune everything
        assert pruned >= 1
        assert len(db.get_system_history(seconds=3600)) == 0


class TestPipelineMetrics:
    def test_record_and_get(self, db):
        db.record_pipeline(
            agent_id="lola",
            scene_id="bedroom",
            tier="gpu",
            model="qwen3-8b",
            latency_ms=350.0,
            ttft_ms=45.0,
            tokens_in=50,
            tokens_out=120,
            tps=24.0,
        )
        history = db.get_pipeline_history(seconds=10)
        assert len(history) == 1
        assert history[0]["agent_id"] == "lola"
        assert history[0]["latency_ms"] == 350.0

    def test_filter_by_agent(self, db):
        db.record_pipeline(agent_id="lola", tier="gpu")
        db.record_pipeline(agent_id="viktor", tier="cpu")
        lola = db.get_pipeline_history(seconds=10, agent_id="lola")
        assert len(lola) == 1
        assert lola[0]["agent_id"] == "lola"

    def test_filter_by_tier(self, db):
        db.record_pipeline(agent_id="a", tier="gpu")
        db.record_pipeline(agent_id="b", tier="cpu")
        gpu = db.get_pipeline_history(seconds=10, tier="gpu")
        assert len(gpu) == 1

    def test_summary(self, db):
        db.record_pipeline(latency_ms=100, tps=20, tokens_in=30, tokens_out=60, kill_fired=0, pre_warm_hit=1)
        db.record_pipeline(latency_ms=200, tps=25, tokens_in=40, tokens_out=80, kill_fired=1, pre_warm_hit=0)
        summary = db.get_pipeline_summary(seconds=10)
        assert summary["total"] == 2
        assert summary["avg_latency"] == 150.0
        assert summary["total_kills"] == 1
        assert summary["total_pre_warms"] == 1

    def test_ignores_unknown_cols(self, db):
        db.record_pipeline(agent_id="x", unknown_field="ignored")
        history = db.get_pipeline_history(seconds=10)
        assert len(history) == 1


class TestAlerts:
    def test_record_and_get(self, db):
        db.record_alert("gpu_primary", "yellow", "VRAM at 82%", "green")
        alerts = db.get_recent_alerts()
        assert len(alerts) == 1
        assert alerts[0]["node"] == "gpu_primary"
        assert alerts[0]["level"] == "yellow"
        assert alerts[0]["prev_level"] == "green"

    def test_multiple_alerts_order(self, db):
        db.record_alert("a", "green")
        db.record_alert("b", "red", "critical")
        alerts = db.get_recent_alerts()
        assert alerts[0]["node"] == "b"  # most recent first
        assert alerts[1]["node"] == "a"


class TestTrainingCandidates:
    def test_store_and_get(self, db):
        rid = db.store_training_candidate(
            source="pipeline",
            dataset="tag_extraction",
            input_text="She smiled [MOOD:happy]",
            output_text='{"mood":"happy"}',
            quality_score=0.9,
        )
        assert rid > 0
        candidates = db.get_training_candidates(dataset="tag_extraction")
        assert len(candidates) == 1
        assert candidates[0]["quality_score"] == 0.9

    def test_count(self, db):
        db.store_training_candidate("p", "tags", "in1", "out1", 0.8)
        db.store_training_candidate("p", "tags", "in2", "out2", 0.3)
        db.store_training_candidate("p", "tools", "in3", "out3", 0.9)
        assert db.count_training_candidates(dataset="tags") == 2
        assert db.count_training_candidates(dataset="tags", min_quality=0.5) == 1
        assert db.count_training_candidates() == 3

    def test_mark_exported(self, db):
        id1 = db.store_training_candidate("p", "d", "i", "o")
        id2 = db.store_training_candidate("p", "d", "i", "o")
        db.mark_exported([id1])
        pending = db.get_training_candidates(exported=False)
        assert len(pending) == 1
        assert pending[0]["id"] == id2

    def test_update_quality(self, db):
        rid = db.store_training_candidate("p", "d", "i", "o", 0.5)
        db.update_quality(rid, 0.95, "excellent example")
        candidates = db.get_training_candidates()
        assert candidates[0]["quality_score"] == 0.95
        assert candidates[0]["notes"] == "excellent example"

    def test_training_stats(self, db):
        db.store_training_candidate("p", "tags", "i", "o", 0.8)
        db.store_training_candidate("p", "tags", "i", "o", 0.6)
        db.store_training_candidate("p", "tools", "i", "o", 0.9)
        stats = db.get_training_stats()
        assert "tags" in stats
        assert stats["tags"]["total"] == 2
        assert stats["tools"]["total"] == 1

    def test_mark_exported_empty(self, db):
        assert db.mark_exported([]) == 0
