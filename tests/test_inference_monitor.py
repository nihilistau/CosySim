"""Tests for engine.lmstudio.inference_monitor — InferenceMonitor."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.lmstudio.inference_monitor import InferenceMonitor, ModelMetrics


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_config():
    """MagicMock config with .get() support."""
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda k, d=None: {
        "nexus.url": "http://localhost:8700/api",
        "lmstudio.monitor.snapshot_interval": 3600,
    }.get(k, d))
    return cfg


@pytest.fixture
def monitor(mock_config):
    """InferenceMonitor with mocked config."""
    return InferenceMonitor(mock_config)


# ── ModelMetrics ────────────────────────────────────────────────────────

def test_model_metrics_empty():
    """Empty ModelMetrics has zero values."""
    m = ModelMetrics(model="test")
    assert m.avg_latency == 0.0
    assert m.avg_tps == 0.0
    assert m.error_rate == 0.0
    assert m.request_count == 0


def test_model_metrics_to_dict():
    """ModelMetrics serializes correctly."""
    m = ModelMetrics(model="test")
    d = m.to_dict()
    assert d["model"] == "test"
    assert d["requests"] == 0
    assert d["errors"] == 0


# ── InferenceMonitor.record ─────────────────────────────────────────────

def test_record_single_transaction(monitor):
    """Recording a transaction updates all counters."""
    monitor.record(
        agent_id="agent-1",
        model="qwen3-8b",
        tier="big",
        task_type="roleplay",
        latency_ms=250.0,
        tokens=50,
        tps=20.0,
        success=True,
    )

    status = monitor.get_status()
    assert status["total_requests"] == 1
    assert status["total_errors"] == 0
    assert "qwen3-8b" in status["models"]
    assert status["models"]["qwen3-8b"]["requests"] == 1
    assert "big" in status["tiers"]


def test_record_multiple_transactions(monitor):
    """Multiple transactions accumulate correctly."""
    for i in range(10):
        monitor.record(
            agent_id=f"agent-{i}",
            model="qwen3-8b",
            tier="big",
            task_type="chat",
            latency_ms=100 + i * 10,
            tokens=20 + i,
            tps=15.0 + i,
            success=True,
        )

    status = monitor.get_status()
    assert status["total_requests"] == 10
    assert status["models"]["qwen3-8b"]["requests"] == 10
    assert status["models"]["qwen3-8b"]["avg_latency_ms"] > 0
    assert status["models"]["qwen3-8b"]["avg_tps"] > 0


def test_record_errors(monitor):
    """Error transactions are tracked separately."""
    monitor.record(
        agent_id="agent-1",
        model="bad-model",
        tier="small",
        task_type="chat",
        latency_ms=0,
        tokens=0,
        tps=0,
        success=False,
        error="timeout",
    )

    status = monitor.get_status()
    assert status["total_errors"] == 1
    assert status["error_rate"] == 1.0
    assert status["models"]["bad-model"]["error_rate"] == 1.0


def test_record_multiple_models(monitor):
    """Tracks per-model metrics separately."""
    monitor.record("a", "model-a", "big", "chat", 100, 10, 20, True)
    monitor.record("a", "model-b", "small", "chat", 200, 5, 10, True)
    monitor.record("a", "model-a", "big", "chat", 150, 12, 22, True)

    status = monitor.get_status()
    assert len(status["models"]) == 2
    assert status["models"]["model-a"]["requests"] == 2
    assert status["models"]["model-b"]["requests"] == 1


# ── InferenceMonitor.update_queue_depth ─────────────────────────────────

def test_update_queue_depth(monitor):
    """Queue depth is tracked and averaged."""
    for d in [1, 2, 3, 4, 5]:
        monitor.update_queue_depth(d)

    status = monitor.get_status()
    assert status["current_queue_depth"] == 5
    assert status["avg_queue_depth"] == 3.0


# ── InferenceMonitor.get_bottlenecks ────────────────────────────────────

def test_no_bottlenecks_when_healthy(monitor):
    """No bottlenecks when metrics are healthy."""
    monitor.record("a", "m", "big", "chat", 100, 10, 20, True)
    bottlenecks = monitor.get_bottlenecks()
    assert len(bottlenecks) == 0


def test_detects_queue_buildup(monitor):
    """Detects high queue depth as bottleneck."""
    monitor.update_queue_depth(12)
    bottlenecks = monitor.get_bottlenecks()
    assert any(b["type"] == "queue_buildup" for b in bottlenecks)


def test_detects_high_error_rate(monitor):
    """Detects high error rate as bottleneck."""
    for _ in range(10):
        monitor.record("a", "bad-model", "big", "chat", 0, 0, 0, False, "err")

    bottlenecks = monitor.get_bottlenecks()
    assert any(b["type"] == "high_error_rate" for b in bottlenecks)


def test_detects_slow_model(monitor):
    """Detects slow model as bottleneck."""
    for _ in range(5):
        monitor.record("a", "slow-model", "big", "chat", 15000, 10, 1.0, True)

    bottlenecks = monitor.get_bottlenecks()
    assert any(b["type"] == "slow_model" for b in bottlenecks)


# ── InferenceMonitor.snapshot ───────────────────────────────────────────

@patch("engine.lmstudio.inference_monitor.requests.post")
def test_snapshot_sends_to_nexus(mock_post, monitor):
    """Snapshot stores metrics in Nexus."""
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {"id": "snap-123"}
    mock_post.return_value = mock_response

    monitor.record("a", "m", "big", "chat", 100, 10, 20, True)
    entry_id = monitor.snapshot()

    assert entry_id == "snap-123"
    mock_post.assert_called_once()
    call_json = mock_post.call_args[1].get("json", {})
    assert call_json["content_type"] == "audit"
    assert "monitor" in call_json.get("tags", [])


@patch("engine.lmstudio.inference_monitor.requests.post")
def test_snapshot_handles_nexus_failure(mock_post, monitor):
    """Snapshot returns None when Nexus is down."""
    mock_post.side_effect = Exception("connection refused")
    monitor.record("a", "m", "big", "chat", 100, 10, 20, True)

    entry_id = monitor.snapshot()
    assert entry_id is None


# ── InferenceMonitor.start/stop ─────────────────────────────────────────

def test_start_stop_lifecycle(monitor):
    """Monitor can start and stop without errors."""
    monitor.start()
    assert monitor._running is True

    monitor.stop()
    assert monitor._running is False


def test_double_start_is_safe(monitor):
    """Starting monitor twice doesn't create duplicate threads."""
    monitor.start()
    monitor.start()
    assert monitor._running is True
    monitor.stop()


# ── get_status structure ────────────────────────────────────────────────

def test_get_status_structure(monitor):
    """get_status returns all expected fields."""
    status = monitor.get_status()
    expected_keys = {
        "uptime_seconds", "total_requests", "total_errors",
        "error_rate", "current_queue_depth", "avg_queue_depth",
        "requests_per_minute", "models", "tiers",
    }
    assert expected_keys.issubset(set(status.keys()))
