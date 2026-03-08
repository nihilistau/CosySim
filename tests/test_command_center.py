"""Tests for Command Center scene and training data preparation."""

import json
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ═══════════════════════════════════════════════════════════════
# Command Center Scene Tests
# ═══════════════════════════════════════════════════════════════


class TestCommandCenterImport:
    """Package imports work correctly."""

    def test_import_scene_class(self):
        from content.scenes.command_center import CommandCenterScene
        assert CommandCenterScene is not None

    def test_import_constants(self):
        from content.scenes.command_center import SCENE_ID, DEFAULT_PORT
        assert SCENE_ID == "command_center"
        assert isinstance(DEFAULT_PORT, int)


class TestCommandCenterScene:
    """Scene initialization and structure."""

    @pytest.fixture
    def scene(self):
        with patch("content.scenes.command_center.command_center_scene.BaseScene.__init__"):
            with patch("content.scenes.command_center.command_center_scene.MCPSceneMixin.__init_subclass__", lambda **kw: None):
                from content.scenes.command_center.command_center_scene import CommandCenterScene
                s = CommandCenterScene.__new__(CommandCenterScene)
                scene_dir = Path(__file__).parent.parent / "content" / "scenes" / "command_center"
                from flask import Flask
                from flask_cors import CORS
                from flask_socketio import SocketIO
                s.app = Flask(
                    "test_cc",
                    template_folder=str(scene_dir / "templates"),
                    static_folder=str(scene_dir / "static"),
                )
                import jinja2
                _shared_tmpl = str(scene_dir.parent.parent / "shared" / "templates")
                s.app.jinja_loader = jinja2.ChoiceLoader([
                    s.app.jinja_loader,
                    jinja2.FileSystemLoader(_shared_tmpl),
                ])
                CORS(s.app)
                s.socketio = SocketIO(s.app, async_mode="threading")
                s._collector = None
                s._metrics_db = None
                s._activity_bus = None
                s._ticker_thread = None
                s._running = False
                s._tick_interval = 1.0
                s.host = "127.0.0.1"
                s.port = 5563
                s.name = "command_center"
                s._register_routes()
                s._register_socketio()
                return s

    def test_has_flask_app(self, scene):
        assert scene.app is not None

    def test_has_socketio(self, scene):
        assert scene.socketio is not None

    def test_plugin_info(self, scene):
        info = scene.get_plugin_info()
        assert info["name"] == "Command Center"
        assert info["port"] == 5563
        assert "dashboard" in info["tags"]

    def test_index_route_exists(self, scene):
        client = scene.app.test_client()
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"COSYSIM COMMAND CENTER" in resp.data

    def test_api_dashboard(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "system" in data
        assert "pipeline" in data
        assert "alerts" in data
        assert "activity" in data
        assert "timestamp" in data

    def test_api_system(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/system")
        assert resp.status_code == 200

    def test_api_pipeline(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/pipeline")
        assert resp.status_code == 200

    def test_api_alerts(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/alerts")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "status" in data
        assert "history" in data

    def test_api_activity(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/activity")
        assert resp.status_code == 200

    def test_api_benchmarks(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/benchmarks")
        assert resp.status_code == 200

    def test_api_training(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/training")
        assert resp.status_code == 200

    def test_api_training_candidates(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/training/candidates")
        assert resp.status_code == 200

    def test_api_pipeline_history(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/pipeline/history?seconds=30&limit=10")
        assert resp.status_code == 200

    def test_api_system_history(self, scene):
        client = scene.app.test_client()
        resp = client.get("/api/system/history?seconds=30")
        assert resp.status_code == 200


class TestCommandCenterDataHelpers:
    """Data retrieval helpers with mocked backends."""

    @pytest.fixture
    def scene(self):
        with patch("content.scenes.command_center.command_center_scene.BaseScene.__init__"):
            with patch("content.scenes.command_center.command_center_scene.MCPSceneMixin.__init_subclass__", lambda **kw: None):
                from content.scenes.command_center.command_center_scene import CommandCenterScene
                s = CommandCenterScene.__new__(CommandCenterScene)
                scene_dir = Path(__file__).parent.parent / "content" / "scenes" / "command_center"
                from flask import Flask
                from flask_cors import CORS
                from flask_socketio import SocketIO
                s.app = Flask(
                    "test_cc2",
                    template_folder=str(scene_dir / "templates"),
                    static_folder=str(scene_dir / "static"),
                )
                CORS(s.app)
                s.socketio = SocketIO(s.app, async_mode="threading")
                s._collector = None
                s._metrics_db = None
                s._activity_bus = None
                s._ticker_thread = None
                s._running = False
                s._tick_interval = 1.0
                s.host = "127.0.0.1"
                s.port = 5563
                s.name = "command_center"
                s._register_routes()
                s._register_socketio()
                return s

    def test_system_snapshot_from_collector(self, scene):
        mock_collector = MagicMock()
        mock_collector.last_system_snapshot = {"cpu_pct": 42.0, "ram_pct": 60.0}
        scene._collector = mock_collector
        snap = scene._system_snapshot()
        assert snap["cpu_pct"] == 42.0

    def test_system_snapshot_fallback_monitor(self, scene):
        scene._collector = None
        mock_mon = MagicMock()
        mock_mon.snapshot.return_value = {"cpu": 50, "ram": {"percent": 70}}
        with patch("engine.logging.monitor.get_system_monitor", return_value=mock_mon):
            snap = scene._system_snapshot()
            assert snap["cpu"] == 50

    def test_pipeline_snapshot(self, scene):
        mock_collector = MagicMock()
        mock_collector.last_pipeline_summary = {"avg_latency_ms": 200, "avg_tps": 25}
        scene._collector = mock_collector
        snap = scene._pipeline_snapshot()
        assert snap["avg_latency_ms"] == 200

    def test_alert_status(self, scene):
        mock_collector = MagicMock()
        mock_engine = MagicMock()
        mock_engine.get_status_map.return_value = {"gpu": "green", "pipeline": "yellow"}
        mock_collector.alert_engine = mock_engine
        scene._collector = mock_collector
        status = scene._alert_status()
        assert status["gpu"] == "green"
        assert status["pipeline"] == "yellow"

    def test_activity_snapshot(self, scene):
        mock_bus = MagicMock()
        mock_bus.snapshot.return_value = {"current": [{"kind": "thinking"}], "history": []}
        scene._activity_bus = mock_bus
        snap = scene._activity_snapshot()
        assert len(snap["current"]) == 1

    def test_full_dashboard(self, scene):
        mock_collector = MagicMock()
        mock_collector.last_system_snapshot = {"cpu_pct": 50}
        mock_collector.last_pipeline_summary = {"avg_tps": 20}
        mock_collector.alert_engine = MagicMock()
        mock_collector.alert_engine.get_status_map.return_value = {}
        scene._collector = mock_collector

        dashboard = scene._full_dashboard()
        assert "system" in dashboard
        assert "pipeline" in dashboard
        assert "alerts" in dashboard
        assert "timestamp" in dashboard

    def test_recent_alerts(self, scene):
        mock_db = MagicMock()
        mock_db.get_recent_alerts.return_value = [{"node": "gpu", "level": "red", "message": "VRAM high"}]
        scene._metrics_db = mock_db
        alerts = scene._recent_alerts(limit=5)
        assert len(alerts) == 1
        assert alerts[0]["level"] == "red"


class TestCommandCenterTicker:
    """Background ticker functionality."""

    def test_start_stop_ticker(self):
        with patch("content.scenes.command_center.command_center_scene.BaseScene.__init__"):
            with patch("content.scenes.command_center.command_center_scene.MCPSceneMixin.__init_subclass__", lambda **kw: None):
                from content.scenes.command_center.command_center_scene import CommandCenterScene
                s = CommandCenterScene.__new__(CommandCenterScene)
                scene_dir = Path(__file__).parent.parent / "content" / "scenes" / "command_center"
                from flask import Flask
                from flask_cors import CORS
                from flask_socketio import SocketIO
                s.app = Flask("test_cc3",
                    template_folder=str(scene_dir / "templates"),
                    static_folder=str(scene_dir / "static"),
                )
                CORS(s.app)
                s.socketio = SocketIO(s.app, async_mode="threading")
                s._collector = None
                s._metrics_db = None
                s._activity_bus = None
                s._ticker_thread = None
                s._running = False
                s._tick_interval = 0.05  # fast for testing
                s.host = "127.0.0.1"
                s.port = 5563
                s.name = "command_center"
                s._register_routes()
                s._register_socketio()

                s._start_ticker()
                assert s._running
                assert s._ticker_thread is not None
                assert s._ticker_thread.is_alive()

                time.sleep(0.15)  # let it tick a few times
                s._stop_ticker()
                assert not s._running


# ═══════════════════════════════════════════════════════════════
# Training Data Preparation Tests
# ═══════════════════════════════════════════════════════════════


class TestPrepareFromLive:
    """Training data preparation module."""

    def test_import(self):
        from training.prepare_from_live import prepare_dataset, merge_datasets, get_dataset_stats
        assert callable(prepare_dataset)
        assert callable(merge_datasets)
        assert callable(get_dataset_stats)

    def test_format_for_gemma(self):
        from training.prepare_from_live import _format_for_gemma
        result = _format_for_gemma("What is 2+2?", "4")
        assert result["instruction"] == "What is 2+2?"
        assert result["output"] == "4"

    def test_get_dataset_stats(self, tmp_path):
        """Stats reads existing JSONL files."""
        from training.prepare_from_live import get_dataset_stats
        stats = get_dataset_stats()
        assert "tag_extraction" in stats
        assert "tool_routing" in stats
        # Should have train/val keys
        for ds in stats.values():
            assert "train" in ds
            assert "val" in ds

    def test_prepare_dataset_no_db(self):
        """Gracefully handles missing DB."""
        from training.prepare_from_live import prepare_dataset
        with patch("training.prepare_from_live._get_metrics_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.get_training_candidates.return_value = []
            mock_get_db.return_value = mock_db
            count = prepare_dataset(dataset_name="tag_extraction")
            assert count == 0

    def test_prepare_dataset_with_candidates(self, tmp_path):
        """Exports candidates to JSONL."""
        from training.prepare_from_live import prepare_dataset, DATASETS_DIR

        candidates = [
            {"id": 1, "input_text": "Hello [MOOD:happy]", "output_text": '{"mood":"happy"}', "quality_score": 0.9},
            {"id": 2, "input_text": "Hi [ACTION:wave]", "output_text": '{"action":"wave"}', "quality_score": 0.8},
        ]

        with patch("training.prepare_from_live._get_metrics_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.get_training_candidates.return_value = candidates
            mock_get_db.return_value = mock_db

            # Clean up any pre-existing live file
            live_path = DATASETS_DIR / "tag_extraction_live.jsonl"
            if live_path.exists():
                live_path.unlink()

            count = prepare_dataset(dataset_name="tag_extraction", min_quality=0.7)
            assert count == 2

            # Verify file was created
            assert live_path.exists()
            with open(live_path) as f:
                lines = [json.loads(line) for line in f if line.strip()]
            assert len(lines) == 2
            assert lines[0]["instruction"] == "Hello [MOOD:happy]"

            # Cleanup
            live_path.unlink()

    def test_merge_datasets(self, tmp_path):
        """Merge synthetic + live into combined."""
        from training.prepare_from_live import DATASETS_DIR

        # Create temporary test files
        train_path = DATASETS_DIR / "test_merge_train.jsonl"
        live_path = DATASETS_DIR / "test_merge_live.jsonl"
        combined_path = DATASETS_DIR / "test_merge_combined.jsonl"

        try:
            train_path.write_text('{"instruction":"a","output":"1"}\n{"instruction":"b","output":"2"}\n')
            live_path.write_text('{"instruction":"c","output":"3"}\n')

            from training.prepare_from_live import merge_datasets
            total = merge_datasets("test_merge")
            assert total == 3

            with open(combined_path) as f:
                lines = [json.loads(l) for l in f if l.strip()]
            assert len(lines) == 3
        finally:
            for p in [train_path, live_path, combined_path]:
                if p.exists():
                    p.unlink()


class TestPrepareFromLiveEdgeCases:
    """Edge cases for training data preparation."""

    def test_skip_empty_candidates(self):
        """Candidates with empty input/output are skipped."""
        from training.prepare_from_live import prepare_dataset, DATASETS_DIR

        candidates = [
            {"id": 1, "input_text": "", "output_text": "something"},
            {"id": 2, "input_text": "valid", "output_text": ""},
            {"id": 3, "input_text": "good", "output_text": "result"},
        ]

        with patch("training.prepare_from_live._get_metrics_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.get_training_candidates.return_value = candidates
            mock_get_db.return_value = mock_db

            live_path = DATASETS_DIR / "tag_extraction_live.jsonl"
            if live_path.exists():
                live_path.unlink()

            count = prepare_dataset(dataset_name="tag_extraction")
            assert count == 1  # only the valid one

            if live_path.exists():
                live_path.unlink()

    def test_prepare_all_datasets(self):
        """When no dataset specified, iterates all 5."""
        from training.prepare_from_live import prepare_dataset

        with patch("training.prepare_from_live._get_metrics_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.get_training_candidates.return_value = []
            mock_get_db.return_value = mock_db

            count = prepare_dataset()
            assert count == 0
            # Should have been called for all 5 datasets
            assert mock_db.get_training_candidates.call_count == 5
