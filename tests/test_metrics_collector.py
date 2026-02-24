"""Tests for MetricsCollector — background metrics service."""

import time
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile

from engine.observability.alerts import AlertRule
from engine.observability.metrics_collector import MetricsCollector
from engine.observability.metrics_db import MetricsDB


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary MetricsDB."""
    return MetricsDB(tmp_path / "test_collector.db")


class TestMetricsCollector:
    def test_create(self, tmp_db):
        mc = MetricsCollector(db=tmp_db)
        assert not mc.running

    def test_start_stop(self, tmp_db):
        mc = MetricsCollector(db=tmp_db, tick_interval=0.1)
        mc.start()
        assert mc.running
        time.sleep(0.05)
        mc.stop()
        assert not mc.running

    def test_double_start(self, tmp_db):
        mc = MetricsCollector(db=tmp_db, tick_interval=0.1)
        mc.start()
        mc.start()  # Should not create second thread
        assert mc.running
        mc.stop()

    def test_alert_engine_accessible(self, tmp_db):
        mc = MetricsCollector(db=tmp_db)
        assert mc.alert_engine is not None

    def test_custom_alert_rules(self, tmp_db):
        rules = [AlertRule(node="test", metric="val", yellow=50, red=90)]
        mc = MetricsCollector(db=tmp_db, alert_rules=rules)
        assert len(mc.alert_engine.rules) == 1


class TestMetricsCollectorPipelineIntegration:
    def test_on_pipeline_result(self, tmp_db):
        mc = MetricsCollector(db=tmp_db)

        # Mock a PipelineResult
        result = MagicMock()
        result.agent_id = "lola"
        result.scene_id = "bedroom"
        result.tier = "gpu"
        result.model = "qwen3-8b"
        result.pipeline_latency_ms = 450.0
        result.time_to_first_token_s = 0.1
        result.input_tokens = 200
        result.output_tokens = 50
        result.server_tps = 25.0
        result.response_id = "resp_123"
        result.draft_accepted = 0
        result.draft_rejected = 0
        result.generation_killed = False
        result.retry_count = 0
        result.pre_warmed_results = []
        result.watcher_analysis = MagicMock()
        result.watcher_analysis.latency_ms = 12.0
        result.watcher_analysis.signals = []

        mc.on_pipeline_result(result)

        # Verify it was recorded
        history = tmp_db.get_pipeline_history(seconds=60)
        assert len(history) == 1
        assert history[0]["agent_id"] == "lola"
        assert history[0]["latency_ms"] == 450.0

    def test_on_pipeline_result_with_kill(self, tmp_db):
        mc = MetricsCollector(db=tmp_db)

        result = MagicMock()
        result.agent_id = "lola"
        result.scene_id = "bedroom"
        result.tier = "gpu"
        result.model = ""
        result.pipeline_latency_ms = 100.0
        result.time_to_first_token_s = 0
        result.input_tokens = 0
        result.output_tokens = 0
        result.server_tps = 0
        result.response_id = ""
        result.draft_accepted = 0
        result.draft_rejected = 0
        result.generation_killed = True
        result.retry_count = 1
        result.pre_warmed_results = []
        result.watcher_analysis = None

        mc.on_pipeline_result(result)

        history = tmp_db.get_pipeline_history(seconds=60)
        assert len(history) == 1
        assert history[0]["kill_fired"] == 1
        assert history[0]["retry_count"] == 1

    def test_emit_fn_called(self, tmp_db):
        emitted = []
        mc = MetricsCollector(db=tmp_db, emit_fn=lambda e, d: emitted.append((e, d)))

        result = MagicMock()
        result.agent_id = "test"
        result.scene_id = ""
        result.tier = ""
        result.model = ""
        result.pipeline_latency_ms = 100
        result.time_to_first_token_s = 0
        result.input_tokens = 0
        result.output_tokens = 0
        result.server_tps = 0
        result.response_id = ""
        result.draft_accepted = 0
        result.draft_rejected = 0
        result.generation_killed = False
        result.retry_count = 0
        result.pre_warmed_results = []
        result.watcher_analysis = None

        mc.on_pipeline_result(result)
        assert any(e == "metric_request" for e, _ in emitted)


class TestMetricsCollectorSnapshots:
    def test_last_system_snapshot(self, tmp_db):
        mc = MetricsCollector(db=tmp_db)
        assert mc.last_system_snapshot == {}

    def test_last_pipeline_summary(self, tmp_db):
        mc = MetricsCollector(db=tmp_db)
        assert mc.last_pipeline_summary == {}
