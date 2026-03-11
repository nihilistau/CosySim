"""Tests for the metrics dashboard blueprint.

Verifies all API endpoints return valid JSON, the dashboard page returns
HTML, and edge cases (LMStudio offline, missing reports) are handled.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.metrics_dashboard import (
    _METRICS_DB,
    _TEST_REPORTS_DIR,
    _TEST_TIMING_FILE,
    create_dashboard_blueprint,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture()
def app():
    """Create a minimal Flask app with the metrics blueprint registered."""
    from flask import Flask

    test_app = Flask(__name__)
    test_app.config["TESTING"] = True
    bp = create_dashboard_blueprint()
    assert bp is not None, "Blueprint factory returned None"
    test_app.register_blueprint(bp, url_prefix="/metrics")
    return test_app


@pytest.fixture()
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture()
def sample_metrics_db(tmp_path: Path) -> Path:
    """Create a temporary metrics.db with sample data."""
    db_path = tmp_path / "metrics.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE system_metrics "
        "(ts REAL, cpu_pct REAL, ram_pct REAL, gpu_vram_pct REAL, "
        "gpu_temp_c REAL, lmstudio_ok INTEGER)"
    )
    conn.execute(
        "INSERT INTO system_metrics VALUES (?, 45.2, 62.1, 78.0, 65.0, 1)",
        (time.time(),),
    )
    conn.execute(
        "CREATE TABLE pipeline_metrics "
        "(id INTEGER PRIMARY KEY, ts REAL, request_id TEXT, agent_id TEXT, "
        "scene_id TEXT, tier TEXT, model TEXT, latency_ms REAL, ttft_ms REAL, "
        "tokens_in INTEGER, tokens_out INTEGER, tps REAL, "
        "watcher_latency_ms REAL, watcher_signal TEXT, kill_fired INTEGER, "
        "retry_count INTEGER, pre_warm_hit INTEGER, response_id TEXT, "
        "draft_accepted INTEGER, draft_rejected INTEGER)"
    )
    conn.execute(
        "INSERT INTO pipeline_metrics "
        "(ts, model, latency_ms, tps, tokens_in, tokens_out) "
        "VALUES (?, 'test-model', 350.0, 42.5, 100, 200)",
        (time.time(),),
    )
    conn.execute(
        "CREATE TABLE alerts "
        "(id INTEGER PRIMARY KEY, ts REAL, node TEXT, level TEXT, "
        "prev_level TEXT, message TEXT)"
    )
    conn.execute(
        "CREATE TABLE training_candidates "
        "(id INTEGER PRIMARY KEY, ts REAL, source TEXT, dataset TEXT, "
        "input_text TEXT, output_text TEXT, quality_score REAL, "
        "exported INTEGER, notes TEXT)"
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def sample_test_report(tmp_path: Path) -> Path:
    """Create a sample test report JSON file."""
    reports_dir = tmp_path / "test_reports"
    reports_dir.mkdir()
    report = {
        "timestamp": "2026-03-11T00:40:53+00:00",
        "tier": 1,
        "total": 130,
        "passed": 128,
        "failed": 2,
        "skipped": 0,
        "errors": 0,
        "duration_seconds": 14.27,
        "test_files": ["test_config.py", "test_hub.py"],
        "slowest_tests": [
            {"test": "tests/test_slow.py::test_big", "duration": 3.26},
        ],
        "return_code": 1,
        "status": "FAILED",
    }
    fp = reports_dir / "test_report_20260311_114053_tier1.json"
    fp.write_text(json.dumps(report), encoding="utf-8")
    return reports_dir


@pytest.fixture()
def sample_timing(tmp_path: Path) -> Path:
    """Create a sample test timing JSON file."""
    fp = tmp_path / "test_timing.json"
    fp.write_text(
        json.dumps({"tests/test_a.py": 2.5, "tests/test_b.py": 8.1}),
        encoding="utf-8",
    )
    return fp


# ── Endpoint tests ────────────────────────────────────────────────────

class TestSystemMetrics:
    """Tests for /api/metrics/system."""

    def test_returns_json(self, client: Any) -> None:
        """Endpoint returns valid JSON with expected top-level keys."""
        with patch(
            "engine.nexus.metrics_dashboard._check_http",
            return_value={"ok": True, "latency_ms": 12, "status_code": 200, "data": None},
        ), patch(
            "engine.nexus.metrics_dashboard._query_metrics_db",
            return_value=[{"cpu_pct": 30, "ram_pct": 50}],
        ):
            resp = client.get("/metrics/api/metrics/system")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "services" in data
            assert "timestamp" in data

    def test_handles_lmstudio_offline(self, client: Any) -> None:
        """System metrics handles LMStudio being unreachable."""
        with patch(
            "engine.nexus.metrics_dashboard._check_http",
            return_value={"ok": False, "latency_ms": -1, "error": "Connection refused"},
        ), patch(
            "engine.nexus.metrics_dashboard._query_metrics_db",
            return_value=[],
        ):
            resp = client.get("/metrics/api/metrics/system")
            assert resp.status_code == 200
            data = resp.get_json()
            assert isinstance(data["services"], dict)


class TestTestMetrics:
    """Tests for /api/metrics/tests."""

    def test_returns_json(self, client: Any, sample_test_report: Path, sample_timing: Path) -> None:
        """Returns valid JSON with latest report and history."""
        with patch.object(
            __import__("engine.nexus.metrics_dashboard", fromlist=["_TEST_REPORTS_DIR"]),
            "_TEST_REPORTS_DIR",
            sample_test_report,
        ), patch.object(
            __import__("engine.nexus.metrics_dashboard", fromlist=["_TEST_TIMING_FILE"]),
            "_TEST_TIMING_FILE",
            sample_timing,
        ):
            resp = client.get("/metrics/api/metrics/tests")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "latest" in data
            assert "history" in data
            assert "slowest_by_file" in data

    def test_no_reports_directory(self, client: Any, tmp_path: Path) -> None:
        """Handles missing test_reports directory gracefully."""
        missing = tmp_path / "nonexistent"
        import engine.nexus.metrics_dashboard as mod

        with patch.object(mod, "_TEST_REPORTS_DIR", missing), \
             patch.object(mod, "_TEST_TIMING_FILE", tmp_path / "nope.json"):
            resp = client.get("/metrics/api/metrics/tests")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["report_count"] == 0
            assert data["latest"] == {}


class TestTaskMetrics:
    """Tests for /api/metrics/tasks."""

    def test_returns_json(self, client: Any) -> None:
        """Returns valid JSON with task counts."""
        mock_task = MagicMock()
        mock_task.status = "completed"
        mock_task.title = "Test task"
        mock_task.created_at = "2026-01-01T00:00:00"
        mock_task.claimed_at = None
        mock_task.completed_at = None

        mock_sched_cls = MagicMock()
        mock_sched_cls.return_value.list_tasks.return_value = [mock_task]

        with patch.dict(
            "sys.modules",
            {"engine.nexus.task_scheduler": MagicMock(TaskScheduler=mock_sched_cls)},
        ):
            resp = client.get("/metrics/api/metrics/tasks")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "counts" in data
            assert "recent" in data

    def test_scheduler_unavailable(self, client: Any) -> None:
        """Handles missing TaskScheduler gracefully."""
        with patch.dict(
            "sys.modules",
            {"engine.nexus.task_scheduler": None},
        ):
            resp = client.get("/metrics/api/metrics/tasks")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["total"] == 0


class TestNexusMetrics:
    """Tests for /api/metrics/nexus."""

    def test_returns_json(self, client: Any) -> None:
        """Returns valid JSON with Nexus stats."""
        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"category": "architecture", "content_type": "note", "created_at": "2026-01-01T00:00:00"},
            {"category": "debugging", "content_type": "code", "created_at": "2026-01-02T00:00:00"},
        ]
        mock_client_mod = MagicMock()
        mock_client_mod.get_nexus_client.return_value = mock_client

        with patch.dict(
            "sys.modules",
            {
                "engine.nexus.client": mock_client_mod,
                "engine.nexus.query_router": None,
            },
        ):
            resp = client.get("/metrics/api/metrics/nexus")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["total_entries"] == 2
            assert "architecture" in data["categories"]


class TestModelMetrics:
    """Tests for /api/metrics/models."""

    def test_returns_json(self, client: Any) -> None:
        """Returns valid JSON with model info."""
        with patch(
            "engine.nexus.metrics_dashboard._check_http",
            return_value={
                "ok": True,
                "latency_ms": 15,
                "status_code": 200,
                "data": {"data": [{"id": "qwen3-8b", "type": "model", "owned_by": "local"}]},
            },
        ), patch(
            "engine.nexus.metrics_dashboard._query_metrics_db",
            return_value=[{"model": "qwen3-8b", "avg_latency": 320, "avg_tps": 45, "call_count": 10}],
        ):
            resp = client.get("/metrics/api/metrics/models")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["lmstudio_online"] is True
            assert data["model_count"] == 1

    def test_lmstudio_offline(self, client: Any) -> None:
        """Returns graceful response when LMStudio is down."""
        with patch(
            "engine.nexus.metrics_dashboard._check_http",
            return_value={"ok": False, "latency_ms": -1, "error": "refused"},
        ), patch(
            "engine.nexus.metrics_dashboard._query_metrics_db",
            return_value=[],
        ):
            resp = client.get("/metrics/api/metrics/models")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["lmstudio_online"] is False
            assert data["model_count"] == 0


class TestOverview:
    """Tests for /api/metrics/overview."""

    def test_aggregates_all_metrics(self, client: Any) -> None:
        """Overview endpoint aggregates all five metric categories."""
        with patch(
            "engine.nexus.metrics_dashboard._collect_system_metrics",
            return_value={"services": {}, "timestamp": 1},
        ), patch(
            "engine.nexus.metrics_dashboard._collect_test_metrics",
            return_value={"latest": {}, "history": [], "report_count": 0, "slowest_by_file": []},
        ), patch(
            "engine.nexus.metrics_dashboard._collect_task_metrics",
            return_value={"counts": {}, "total": 0, "avg_latency_s": 0, "recent": []},
        ), patch(
            "engine.nexus.metrics_dashboard._collect_nexus_metrics",
            return_value={"total_entries": 0},
        ), patch(
            "engine.nexus.metrics_dashboard._collect_model_metrics",
            return_value={"loaded_models": [], "model_count": 0},
        ):
            resp = client.get("/metrics/api/metrics/overview")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "system" in data
            assert "tests" in data
            assert "tasks" in data
            assert "nexus" in data
            assert "models" in data

    def test_partial_failure(self, client: Any) -> None:
        """Overview still returns partial data when one collector fails."""
        with patch(
            "engine.nexus.metrics_dashboard._collect_system_metrics",
            side_effect=RuntimeError("boom"),
        ), patch(
            "engine.nexus.metrics_dashboard._collect_test_metrics",
            return_value={"latest": {}},
        ), patch(
            "engine.nexus.metrics_dashboard._collect_task_metrics",
            return_value={"counts": {}},
        ), patch(
            "engine.nexus.metrics_dashboard._collect_nexus_metrics",
            return_value={"total_entries": 0},
        ), patch(
            "engine.nexus.metrics_dashboard._collect_model_metrics",
            return_value={"loaded_models": []},
        ):
            resp = client.get("/metrics/api/metrics/overview")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "error" in data["system"]
            assert "latest" in data["tests"]


class TestDashboardPage:
    """Tests for /dashboard."""

    def test_returns_html(self, client: Any) -> None:
        """Dashboard page returns HTML content."""
        resp = client.get("/metrics/dashboard")
        assert resp.status_code == 200
        assert b"CosySim System Dashboard" in resp.data
        assert b"text/html" in resp.content_type.encode()

    def test_contains_key_elements(self, client: Any) -> None:
        """Dashboard HTML includes metric cards and panels."""
        resp = client.get("/metrics/dashboard")
        html = resp.data.decode("utf-8")
        assert "card-services" in html
        assert "card-tests" in html
        assert "card-nexus" in html
        assert "card-queue" in html
        assert "refreshDashboard" in html


class TestBlueprintFactory:
    """Tests for create_dashboard_blueprint()."""

    def test_returns_blueprint(self) -> None:
        """Factory returns a Flask Blueprint instance."""
        bp = create_dashboard_blueprint()
        assert bp is not None
        assert bp.name == "metrics_dashboard"

    def test_returns_none_without_flask(self) -> None:
        """Factory returns None when Flask is not importable."""
        import sys
        flask_mod = sys.modules.get("flask")
        try:
            sys.modules["flask"] = None  # type: ignore[assignment]
            bp = create_dashboard_blueprint()
            assert bp is None
        finally:
            if flask_mod is not None:
                sys.modules["flask"] = flask_mod
            else:
                sys.modules.pop("flask", None)
