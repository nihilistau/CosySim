"""Tests for engine.monitoring.metrics_collector — v0.72 in-process metrics."""
from __future__ import annotations

import threading
import time

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fresh_collector():
    """Return a brand-new MetricsCollector (not the singleton)."""
    from engine.monitoring.metrics_collector import MetricsCollector
    return MetricsCollector()


# ── Instantiation ──────────────────────────────────────────────────────────────

def test_instantiation():
    from engine.monitoring.metrics_collector import MetricsCollector
    mc = MetricsCollector()
    assert mc is not None
    assert len(mc._samples) == 0


def test_singleton_returns_same_instance():
    from engine.monitoring.metrics_collector import get_metrics_collector
    a = get_metrics_collector()
    b = get_metrics_collector()
    assert a is b


# ── record() ──────────────────────────────────────────────────────────────────

def test_record_adds_to_samples():
    mc = _fresh_collector()
    mc.record("test_component", "llm_call", 42.0)
    assert len(mc._samples) == 1


def test_record_sample_fields():
    mc = _fresh_collector()
    mc.record("mycomp", "error", 1.0, {"key": "val"})
    s = mc._samples[0]
    assert s.component == "mycomp"
    assert s.event_type == "error"
    assert s.value == 1.0
    assert s.metadata["key"] == "val"


def test_record_default_metadata_is_empty_dict():
    mc = _fresh_collector()
    mc.record("c", "e", 0.0)
    assert mc._samples[0].metadata == {}


# ── record_llm_call() ─────────────────────────────────────────────────────────

def test_record_llm_call_adds_sample():
    mc = _fresh_collector()
    mc.record_llm_call("big", 120.5, 100, 200)
    assert len(mc._samples) == 1
    s = mc._samples[0]
    assert s.event_type == "llm_call"
    assert s.component == "lmstudio"
    assert s.value == 120.5
    assert s.metadata["model_profile"] == "big"
    assert s.metadata["tokens_prompt"] == 100
    assert s.metadata["tokens_completion"] == 200
    assert s.metadata["total_tokens"] == 300
    assert s.metadata["success"] is True


def test_record_llm_call_failed():
    mc = _fresh_collector()
    mc.record_llm_call("small", 50.0, 0, 0, success=False)
    assert mc._samples[0].metadata["success"] is False


# ── record_error() ────────────────────────────────────────────────────────────

def test_record_error_increments():
    mc = _fresh_collector()
    mc.record_error("lmstudio", "ConnectionError")
    mc.record_error("lmstudio", "TimeoutError")
    errors = [s for s in mc._samples if s.event_type == "error"]
    assert len(errors) == 2


def test_record_error_metadata():
    mc = _fresh_collector()
    mc.record_error("nexus", "HTTPError")
    s = mc._samples[0]
    assert s.metadata["error_type"] == "HTTPError"
    assert s.component == "nexus"


# ── record_scene_request() ────────────────────────────────────────────────────

def test_record_scene_request_adds_sample():
    mc = _fresh_collector()
    mc.record_scene_request("penthouse", "/api/chat", 35.0)
    s = mc._samples[0]
    assert s.event_type == "scene_request"
    assert s.metadata["scene"] == "penthouse"
    assert s.metadata["endpoint"] == "/api/chat"
    assert s.value == 35.0


# ── get_summary() — empty state ───────────────────────────────────────────────

def test_summary_empty_returns_zeros():
    mc = _fresh_collector()
    summary = mc.get_summary()
    assert summary["llm"]["total_calls"] == 0
    assert summary["llm"]["error_rate"] == 0.0
    assert summary["llm"]["avg_latency_ms"] == 0.0
    assert summary["llm"]["p50_latency_ms"] == 0.0
    assert summary["llm"]["p90_latency_ms"] == 0.0
    assert summary["llm"]["total_tokens"] == 0
    assert summary["llm"]["by_model"] == {}
    assert summary["scenes"] == {}
    assert summary["errors"] == {}


def test_summary_window_seconds_in_output():
    mc = _fresh_collector()
    summary = mc.get_summary(window_seconds=600)
    assert summary["window_seconds"] == 600


# ── get_summary() — with data ─────────────────────────────────────────────────

def test_summary_total_calls():
    mc = _fresh_collector()
    mc.record_llm_call("big", 100.0, 50, 50)
    mc.record_llm_call("big", 200.0, 60, 60)
    summary = mc.get_summary()
    assert summary["llm"]["total_calls"] == 2


def test_summary_avg_latency():
    mc = _fresh_collector()
    mc.record_llm_call("big", 100.0, 10, 10)
    mc.record_llm_call("big", 300.0, 10, 10)
    summary = mc.get_summary()
    assert abs(summary["llm"]["avg_latency_ms"] - 200.0) < 0.01


def test_summary_p50_latency():
    mc = _fresh_collector()
    for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
        mc.record_llm_call("m", v, 0, 0)
    summary = mc.get_summary()
    # p50 of [10,20,30,40,50] → 30
    assert abs(summary["llm"]["p50_latency_ms"] - 30.0) < 0.01


def test_summary_p90_latency():
    mc = _fresh_collector()
    for v in [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]:
        mc.record_llm_call("m", v, 0, 0)
    summary = mc.get_summary()
    # p90 of 10 evenly-spaced values should be ≥ 85
    assert summary["llm"]["p90_latency_ms"] >= 85.0


def test_summary_error_rate():
    mc = _fresh_collector()
    mc.record_llm_call("big", 100.0, 10, 10, success=True)
    mc.record_error("lmstudio", "SomeError")
    summary = mc.get_summary()
    # 1 error / (1 call + 1 error) = 0.5
    assert abs(summary["llm"]["error_rate"] - 0.5) < 0.01


def test_summary_by_model_breakdown():
    mc = _fresh_collector()
    mc.record_llm_call("big", 200.0, 100, 100)
    mc.record_llm_call("big", 400.0, 100, 100)
    mc.record_llm_call("small", 50.0, 10, 10)
    summary = mc.get_summary()
    by_model = summary["llm"]["by_model"]
    assert "big" in by_model
    assert "small" in by_model
    assert by_model["big"]["calls"] == 2
    assert abs(by_model["big"]["avg_latency"] - 300.0) < 0.01
    assert by_model["big"]["tokens"] == 400
    assert by_model["small"]["calls"] == 1


def test_summary_scene_breakdown():
    mc = _fresh_collector()
    mc.record_scene_request("penthouse", "/chat", 40.0)
    mc.record_scene_request("penthouse", "/state", 20.0)
    mc.record_scene_request("casino", "/bet", 10.0)
    summary = mc.get_summary()
    scenes = summary["scenes"]
    assert "penthouse" in scenes
    assert scenes["penthouse"]["requests"] == 2
    assert abs(scenes["penthouse"]["avg_latency_ms"] - 30.0) < 0.01
    assert "casino" in scenes


def test_summary_total_tokens():
    mc = _fresh_collector()
    mc.record_llm_call("big", 100.0, 50, 75)
    mc.record_llm_call("big", 100.0, 25, 25)
    summary = mc.get_summary()
    assert summary["llm"]["total_tokens"] == 175


def test_summary_window_filters_old_samples():
    """Samples older than window_seconds should be excluded."""
    from engine.monitoring.metrics_collector import MetricsSample
    mc = _fresh_collector()
    # Inject an old sample directly
    old = MetricsSample(
        timestamp=time.monotonic() - 7200,  # 2 hours ago
        component="lmstudio",
        event_type="llm_call",
        value=500.0,
        metadata={"model_profile": "big", "tokens_prompt": 10,
                  "tokens_completion": 10, "total_tokens": 20, "success": True},
    )
    mc._samples.append(old)
    mc.record_llm_call("big", 100.0, 5, 5)  # recent

    summary = mc.get_summary(window_seconds=3600)
    assert summary["llm"]["total_calls"] == 1
    assert abs(summary["llm"]["avg_latency_ms"] - 100.0) < 0.01


def test_summary_collector_section():
    mc = _fresh_collector()
    mc.record("c", "e", 1.0)
    summary = mc.get_summary()
    assert "collector" in summary
    assert summary["collector"]["sample_count"] == 1
    assert summary["collector"]["oldest_sample_age_s"] >= 0.0


# ── reset() ───────────────────────────────────────────────────────────────────

def test_reset_clears_samples():
    mc = _fresh_collector()
    mc.record_llm_call("big", 100.0, 10, 10)
    mc.record_llm_call("big", 200.0, 20, 20)
    assert len(mc._samples) == 2
    mc.reset()
    assert len(mc._samples) == 0


def test_reset_then_summary_zeros():
    mc = _fresh_collector()
    mc.record_llm_call("big", 100.0, 10, 10)
    mc.reset()
    summary = mc.get_summary()
    assert summary["llm"]["total_calls"] == 0


# ── Thread-safety ─────────────────────────────────────────────────────────────

def test_thread_safe_concurrent_records():
    """Multiple threads recording simultaneously should not lose samples or raise."""
    mc = _fresh_collector()
    errors: list = []

    def _worker():
        try:
            for _ in range(50):
                mc.record_llm_call("big", 10.0, 1, 1)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread errors: {errors}"
    # 10 threads × 50 records = 500, deque capped at 10000 so all fit
    assert len(mc._samples) == 500


# ── export_prometheus() ───────────────────────────────────────────────────────

def test_export_prometheus_returns_string():
    mc = _fresh_collector()
    mc.record_llm_call("big", 100.0, 10, 10)
    output = mc.export_prometheus()
    assert isinstance(output, str)
    assert len(output) > 0


def test_export_prometheus_contains_key_metrics():
    mc = _fresh_collector()
    mc.record_llm_call("big", 100.0, 10, 10)
    output = mc.export_prometheus()
    assert "cosysim_llm_total_calls" in output
    assert "cosysim_llm_avg_latency_ms" in output
    assert "cosysim_llm_p50_latency_ms" in output
    assert "cosysim_llm_p90_latency_ms" in output


def test_export_prometheus_ends_with_newline():
    mc = _fresh_collector()
    output = mc.export_prometheus()
    assert output.endswith("\n")


# ── /api/metrics route ────────────────────────────────────────────────────────

def test_api_metrics_route_returns_200():
    """The /api/metrics route should return 200 with the expected JSON keys."""
    from flask import Flask
    from content.shared import register_shared_assets

    app = Flask(__name__)
    register_shared_assets(app)

    with app.test_client() as client:
        resp = client.get("/api/perf/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "llm" in data
        assert "scenes" in data
        assert "errors" in data
        assert "collector" in data
        assert "window_seconds" in data


def test_api_metrics_window_param():
    """The window query parameter should be forwarded to get_summary."""
    from flask import Flask
    from content.shared import register_shared_assets

    app = Flask(__name__)
    register_shared_assets(app)

    with app.test_client() as client:
        resp = client.get("/api/perf/metrics?window=600")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["window_seconds"] == 600


def test_api_metrics_reset_route():
    """POST /api/metrics/reset should return {reset: true}."""
    from flask import Flask
    from content.shared import register_shared_assets

    app = Flask(__name__)
    register_shared_assets(app)

    with app.test_client() as client:
        resp = client.post("/api/perf/metrics/reset")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["reset"] is True
