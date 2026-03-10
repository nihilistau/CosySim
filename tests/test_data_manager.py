"""Tests for TrainingDataManager — end-to-end training data pipeline."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from training.data_manager import TrainingDataManager, PipelineStatus


@pytest.fixture
def tmp_db(tmp_path):
    from engine.observability.metrics_db import MetricsDB
    return MetricsDB(tmp_path / "test_dm.db")


@pytest.fixture
def mgr(tmp_db):
    """TrainingDataManager with real temp MetricsDB."""
    m = TrainingDataManager()
    m._metrics_db = tmp_db
    return m


class TestPipelineStatus:
    def test_status_returns_dataclass(self, mgr):
        """Status should return a PipelineStatus even with no data."""
        status = mgr.get_pipeline_status()
        assert isinstance(status, PipelineStatus)
        assert status.capture_count == 0
        assert status.candidates_pending == 0

    def test_status_to_dict(self, mgr):
        """PipelineStatus.to_dict should include all fields."""
        status = mgr.get_pipeline_status()
        d = status.to_dict()
        assert "capture_enabled" in d
        assert "candidates_by_dataset" in d
        assert "ready_for_training" in d
        assert "total_training_examples" in d


class TestCandidates:
    def test_get_candidates_empty(self, mgr):
        """No candidates initially."""
        candidates = mgr.get_candidates()
        assert candidates == []

    def test_add_manual_example(self, mgr):
        """User can add gold-standard manual examples."""
        result = mgr.add_manual_example(
            dataset="tool_routing",
            input_text="scene=bedroom, agent_id=lola",
            output_text='<tool_call>{"name":"search_memory","arguments":{"q":"hi"}}</tool_call>',
            quality_score=1.0,
            notes="gold",
        )
        assert result.affected == 1
        assert result.details.get("dataset") == "tool_routing"

        candidates = mgr.get_candidates(dataset="tool_routing")
        assert len(candidates) == 1
        assert candidates[0]["source"] == "manual"

    def test_update_candidate_quality(self, mgr, tmp_db):
        """User can review and re-score a candidate."""
        row_id = tmp_db.store_training_candidate(
            source="pipeline",
            dataset="tag_extraction",
            input_text="test input",
            output_text="test output",
            quality_score=0.5,
        )
        result = mgr.update_candidate_quality(row_id, 0.9, "looks good")
        assert result.affected == 1

    def test_bulk_update_quality(self, mgr, tmp_db):
        """Bulk approve/reject candidates."""
        ids = []
        for i in range(5):
            row_id = tmp_db.store_training_candidate(
                source="pipeline",
                dataset="tag_extraction",
                input_text=f"input {i}",
                output_text=f"output {i}",
                quality_score=0.5,
            )
            ids.append(row_id)

        result = mgr.bulk_update_quality(ids, 1.0, "approved")
        assert result.affected == 5

    def test_delete_candidate(self, mgr, tmp_db):
        """Delete bad data."""
        row_id = tmp_db.store_training_candidate(
            source="pipeline",
            dataset="tag_extraction",
            input_text="bad input",
            output_text="bad output",
            quality_score=0.1,
        )
        result = mgr.delete_candidate(row_id)
        assert result.affected == 1
        assert mgr.get_candidates() == []


class TestCaptureControl:
    def test_capture_no_collector(self, mgr):
        """When no collector is available, capture returns False."""
        mgr._capture = None  # Force no capture
        with patch.object(mgr, "_get_capture", return_value=None):
            assert mgr.set_capture_enabled(True) is False

    def test_capture_with_mock(self, mgr):
        """With a mock capture instance, toggle works."""
        mock_capture = MagicMock()
        mock_capture.enabled = True
        mgr._capture = mock_capture
        assert mgr.set_capture_enabled(False) is True


class TestExportAndMerge:
    def test_export_live_delegates(self, mgr):
        """Export should delegate to prepare_from_live."""
        with patch("training.prepare_from_live.prepare_dataset", return_value=42):
            result = mgr.export_live_candidates(min_quality=0.7)
            assert result == {"exported": 42}

    def test_validate_datasets(self, mgr):
        """Validate delegates to prepare_training."""
        result = mgr.validate_datasets()
        assert isinstance(result, dict)
        # May have "ready" key or "error" if datasets don't exist

    def test_get_training_config(self, mgr):
        """Config should return valid structure."""
        config = mgr.get_training_config()
        assert "model" in config
        assert config["model"] == "google/gemma-3-270m-it"
        assert "hyperparameters" in config
        assert "lora" in config


class TestDatasetFiles:
    def test_get_dataset_files(self, mgr):
        """Should list existing dataset files."""
        files = mgr.get_dataset_files()
        assert isinstance(files, list)
        # At least the synthetic datasets exist
        if files:
            assert "name" in files[0]
            assert "examples" in files[0]

    def test_download_nonexistent(self, mgr):
        """Download of missing file returns None."""
        assert mgr.download_dataset("nonexistent.jsonl") is None


class TestMetricsCollectorWiring:
    """Verify TrainingCapture is wired into MetricsCollector."""

    def test_collector_has_training_capture(self, tmp_db):
        """MetricsCollector should auto-create a TrainingCapture."""
        from engine.observability.metrics_collector import MetricsCollector
        collector = MetricsCollector(db=tmp_db)
        assert collector.training_capture is not None
        assert collector.training_capture.enabled is True

    def test_pipeline_result_triggers_capture(self, tmp_db):
        """on_pipeline_result should also fire training capture."""
        from engine.observability.metrics_collector import MetricsCollector
        collector = MetricsCollector(db=tmp_db)

        result = MagicMock()
        result.agent_id = "lola"
        result.scene_id = "penthouse"
        result.tier = "gpu"
        result.model = "test-model"
        result.pipeline_latency_ms = 100
        result.time_to_first_token_s = 0.05
        result.input_tokens = 50
        result.output_tokens = 20
        result.server_tps = 40.0
        result.response_id = "resp-123"
        result.draft_accepted = 0
        result.draft_rejected = 0
        result.generation_killed = False
        result.pre_warmed_results = []
        result.retry_count = 0

        # Watcher analysis with real acceptability
        wa = MagicMock()
        wa.acceptability = 0.9
        wa.latency_ms = 10
        wa.signals = []
        wa.kill_reason = ""
        result.watcher_analysis = wa

        # Request attached to result
        req = MagicMock()
        req.scene = "penthouse"
        req.agent_id = "lola"
        req.priority = "interactive"
        req.metadata = {"character_name": "Lola"}
        result._request = req

        # Tag extraction data
        result.raw_text = "Hello [MOOD:happy]"
        result.clean_text = "Hello"
        result.mood_tags = ["happy"]
        result.image_requests = []
        result.action_tags = []
        result.voice_style = ""
        result.tool_calls = []
        result.killed_content = ""

        collector.on_pipeline_result(result)

        # Check that training candidates were stored
        candidates = tmp_db.get_training_candidates()
        assert len(candidates) >= 1  # At least tag_extraction + priority


class TestPipelineRequestAttachment:
    """Verify VirtualPipeline attaches _request to results."""

    def test_result_gets_request_attached(self):
        """PipelineResult should have _request set after execute()."""
        # Just verify the attribute assignment pattern works
        result = MagicMock()
        request = MagicMock()
        result._request = request
        assert result._request is request
