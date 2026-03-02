"""Tests for Intel Hub Mission Control panel — v72-e2."""
from __future__ import annotations

from collections import deque
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def hub_app():
    """Intel Hub Flask test client with mission-control routes."""
    from flask import Flask

    mock_metrics_summary: Dict[str, Any] = {
        "window_seconds": 3600,
        "llm": {
            "total_calls": 42,
            "error_rate": 0.02,
            "avg_latency_ms": 350.0,
            "p50_latency_ms": 320.0,
            "p90_latency_ms": 500.0,
            "total_tokens": 12000,
            "by_model": {},
        },
        "scenes": {"bedroom": {"requests": 10, "avg_latency_ms": 20.0}},
        "errors": {},
        "collector": {"sample_count": 50, "oldest_sample_age_s": 100.0},
    }

    mock_router_status: Dict[str, Any] = {
        "available": True,
        "loaded": True,
        "model_path": "/models/router.gguf",
        "load_error": None,
        "predict_count": 99,
        "error_count": 1,
        "last_predict_ms": 5.5,
    }

    mock_metrics_collector = MagicMock()
    mock_metrics_collector.get_summary.return_value = mock_metrics_summary

    mock_router_v3 = MagicMock()
    mock_router_v3.get_status.return_value = mock_router_status

    mock_world_sim = MagicMock()
    mock_world_sim.get_all_events.return_value = [{"id": "e1", "title": "Test event"}]

    mock_npc = MagicMock()
    mock_npc.list_all.return_value = [MagicMock(), MagicMock(), MagicMock()]  # 3 NPCs

    app = Flask(__name__)
    app.config["TESTING"] = True

    with (
        patch("engine.config.get_config", return_value=MagicMock(get=lambda k, d=None: d)),
        patch("content.scenes.intel_hub.intel_hub_scene.register_shared_assets"),
        patch("content.scenes.intel_hub.intel_hub_scene.SocketIO", None),
        patch("engine.scenes.base_scene.BaseScene.__init__", lambda s, **kw: None),
        patch("engine.scenes.base_scene.BaseScene.register_health_route"),
        patch("engine.monitoring.metrics_collector.get_metrics_collector",
              return_value=mock_metrics_collector),
        patch("engine.lmstudio.router_v3_client.get_router_v3_client",
              return_value=mock_router_v3),
        patch("engine.world.world_sim.get_world_sim", return_value=mock_world_sim),
        patch("engine.world.npc_state.get_npc_state", return_value=mock_npc),
    ):
        from content.scenes.intel_hub.intel_hub_scene import IntelHubScene
        scene = IntelHubScene.__new__(IntelHubScene)
        scene._app = app
        scene._host = "0.0.0.0"
        scene._port = 5580
        scene._activity = deque(maxlen=200)
        scene._stop_event = MagicMock()
        scene._register_routes()
        yield app.test_client(), mock_metrics_collector, mock_router_v3, mock_npc


# ──── /api/intel/metrics ──────────────────────────────────────────────────────


def test_intel_metrics_returns_200(hub_app):
    client, *_ = hub_app
    resp = client.get("/api/intel/metrics")
    assert resp.status_code == 200


def test_intel_metrics_returns_json(hub_app):
    client, *_ = hub_app
    resp = client.get("/api/intel/metrics")
    data = resp.get_json()
    assert data is not None


def test_intel_metrics_has_metrics_key(hub_app):
    client, *_ = hub_app
    data = client.get("/api/intel/metrics").get_json()
    assert "metrics" in data


def test_intel_metrics_has_router_key(hub_app):
    client, *_ = hub_app
    data = client.get("/api/intel/metrics").get_json()
    assert "router" in data


def test_intel_metrics_llm_subkey_present(hub_app):
    client, *_ = hub_app
    data = client.get("/api/intel/metrics").get_json()
    assert "llm" in data["metrics"]


def test_intel_metrics_scenes_subkey_present(hub_app):
    client, *_ = hub_app
    data = client.get("/api/intel/metrics").get_json()
    assert "scenes" in data["metrics"]


def test_intel_metrics_errors_subkey_present(hub_app):
    client, *_ = hub_app
    data = client.get("/api/intel/metrics").get_json()
    assert "errors" in data["metrics"]


def test_intel_metrics_router_available_key(hub_app):
    client, *_ = hub_app
    data = client.get("/api/intel/metrics").get_json()
    assert "available" in data["router"]


def test_intel_metrics_router_predict_count_key(hub_app):
    client, *_ = hub_app
    data = client.get("/api/intel/metrics").get_json()
    assert "predict_count" in data["router"]


def test_intel_metrics_llm_total_calls_value(hub_app):
    client, *_ = hub_app
    data = client.get("/api/intel/metrics").get_json()
    assert data["metrics"]["llm"]["total_calls"] == 42


def test_intel_metrics_router_predict_count_value(hub_app):
    client, *_ = hub_app
    data = client.get("/api/intel/metrics").get_json()
    assert data["router"]["predict_count"] == 99


def test_intel_metrics_router_available_true(hub_app):
    client, *_ = hub_app
    data = client.get("/api/intel/metrics").get_json()
    assert data["router"]["available"] is True


def test_intel_metrics_calls_get_summary(hub_app):
    client, mock_mc, *_ = hub_app
    client.get("/api/intel/metrics")
    mock_mc.get_summary.assert_called_once_with(window_seconds=3600)


def test_intel_metrics_calls_router_get_status(hub_app):
    client, _, mock_router, *_ = hub_app
    client.get("/api/intel/metrics")
    mock_router.get_status.assert_called()


# ──── /api/world/events (enhanced) ────────────────────────────────────────────


def test_world_events_returns_200(hub_app):
    client, *_ = hub_app
    resp = client.get("/api/world/events")
    assert resp.status_code == 200


def test_world_events_has_npc_count(hub_app):
    client, *_ = hub_app
    data = client.get("/api/world/events").get_json()
    assert "npc_count" in data


def test_world_events_npc_count_value(hub_app):
    client, *_ = hub_app
    data = client.get("/api/world/events").get_json()
    assert data["npc_count"] == 3


def test_world_events_has_events_key(hub_app):
    client, *_ = hub_app
    data = client.get("/api/world/events").get_json()
    assert "events" in data


def test_world_events_has_count_key(hub_app):
    client, *_ = hub_app
    data = client.get("/api/world/events").get_json()
    assert "count" in data


# ──── Template verification ────────────────────────────────────────────────────


def test_template_contains_mission_control():
    html = open(
        "content/scenes/intel_hub/templates/intel_hub.html",
        encoding="utf-8",
    ).read()
    assert "MISSION CONTROL" in html


def test_template_contains_setinterval():
    html = open(
        "content/scenes/intel_hub/templates/intel_hub.html",
        encoding="utf-8",
    ).read()
    assert "setInterval" in html


def test_template_contains_scene_health_grid():
    html = open(
        "content/scenes/intel_hub/templates/intel_hub.html",
        encoding="utf-8",
    ).read()
    assert "mc-scene-cards" in html


def test_template_contains_npc_counter():
    html = open(
        "content/scenes/intel_hub/templates/intel_hub.html",
        encoding="utf-8",
    ).read()
    assert "mc-npc-count" in html


def test_template_contains_auto_refresh_30s():
    html = open(
        "content/scenes/intel_hub/templates/intel_hub.html",
        encoding="utf-8",
    ).read()
    assert "30000" in html


def test_template_panel_mission_control_id():
    html = open(
        "content/scenes/intel_hub/templates/intel_hub.html",
        encoding="utf-8",
    ).read()
    assert 'id="panel-mission-control"' in html


def test_template_contains_system_metrics_label():
    html = open(
        "content/scenes/intel_hub/templates/intel_hub.html",
        encoding="utf-8",
    ).read()
    assert "SYSTEM METRICS" in html


def test_template_contains_router_stats_label():
    html = open(
        "content/scenes/intel_hub/templates/intel_hub.html",
        encoding="utf-8",
    ).read()
    assert "ROUTER STATS" in html


# ──── Graceful degradation ────────────────────────────────────────────────────


def test_intel_metrics_graceful_on_collector_error():
    """Route must return 200 even when MetricsCollector raises."""
    from flask import Flask
    from collections import deque

    app = Flask(__name__)
    app.config["TESTING"] = True

    failing_mc = MagicMock()
    failing_mc.get_summary.side_effect = RuntimeError("boom")
    mock_router = MagicMock()
    mock_router.get_status.return_value = {"available": False, "predict_count": 0}

    with (
        patch("engine.config.get_config", return_value=MagicMock(get=lambda k, d=None: d)),
        patch("content.scenes.intel_hub.intel_hub_scene.register_shared_assets"),
        patch("content.scenes.intel_hub.intel_hub_scene.SocketIO", None),
        patch("engine.scenes.base_scene.BaseScene.__init__", lambda s, **kw: None),
        patch("engine.scenes.base_scene.BaseScene.register_health_route"),
        patch("engine.monitoring.metrics_collector.get_metrics_collector", return_value=failing_mc),
        patch("engine.lmstudio.router_v3_client.get_router_v3_client", return_value=mock_router),
        patch("engine.world.world_sim.get_world_sim", side_effect=ImportError),
        patch("engine.world.npc_state.get_npc_state", side_effect=ImportError),
    ):
        from content.scenes.intel_hub.intel_hub_scene import IntelHubScene
        scene = IntelHubScene.__new__(IntelHubScene)
        scene._app = app
        scene._host = "0.0.0.0"
        scene._port = 5580
        scene._activity = deque(maxlen=200)
        scene._stop_event = MagicMock()
        scene._register_routes()
        client = app.test_client()
        resp = client.get("/api/intel/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "metrics" in data
        assert "router" in data


def test_world_events_graceful_on_npc_error():
    """npc_count defaults to 0 when NPCState raises."""
    from flask import Flask
    from collections import deque

    app = Flask(__name__)
    app.config["TESTING"] = True

    mock_sim = MagicMock()
    mock_sim.get_all_events.return_value = []

    with (
        patch("engine.config.get_config", return_value=MagicMock(get=lambda k, d=None: d)),
        patch("content.scenes.intel_hub.intel_hub_scene.register_shared_assets"),
        patch("content.scenes.intel_hub.intel_hub_scene.SocketIO", None),
        patch("engine.scenes.base_scene.BaseScene.__init__", lambda s, **kw: None),
        patch("engine.scenes.base_scene.BaseScene.register_health_route"),
        patch("engine.monitoring.metrics_collector.get_metrics_collector", return_value=MagicMock()),
        patch("engine.lmstudio.router_v3_client.get_router_v3_client", return_value=MagicMock()),
        patch("engine.world.world_sim.get_world_sim", return_value=mock_sim),
        patch("engine.world.npc_state.get_npc_state", side_effect=RuntimeError("no npc")),
    ):
        from content.scenes.intel_hub.intel_hub_scene import IntelHubScene
        scene = IntelHubScene.__new__(IntelHubScene)
        scene._app = app
        scene._host = "0.0.0.0"
        scene._port = 5580
        scene._activity = deque(maxlen=200)
        scene._stop_event = MagicMock()
        scene._register_routes()
        client = app.test_client()
        resp = client.get("/api/world/events")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["npc_count"] == 0
