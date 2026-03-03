"""Tests for engine.lmstudio.router — InferenceRouter priority queue.

All tests use mock clients so no LMStudio server is needed.
"""
import time
import threading
from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import pytest

from engine.lmstudio.router import (
    InferenceRouter, InferenceRequest, Priority, Tier, Channel,
    TierConfig, RouterMetrics,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_router(**kwargs) -> InferenceRouter:
    """Create a router with default tier configs."""
    tiers = {
        Tier.GPU_PRIMARY: TierConfig(
            tier=Tier.GPU_PRIMARY, model_key="test-8b", max_slots=2, device="gpu",
        ),
        Tier.CPU_UTILITY: TierConfig(
            tier=Tier.CPU_UTILITY, model_key="test-3b", max_slots=1, device="cpu",
        ),
        Tier.CPU_ROUTER: TierConfig(
            tier=Tier.CPU_ROUTER, model_key="test-270m", max_slots=1, device="cpu",
        ),
    }
    return InferenceRouter(tiers=tiers, **kwargs)


def _mock_sdk_response(content="Hello!"):
    """Return a mock LMSResponse."""
    resp = MagicMock()
    resp.content = content
    resp.latency_ms = 50.0
    return resp


# ── Tests: Tier selection ────────────────────────────────────────────


class TestTierSelection:
    @pytest.fixture(autouse=True)
    def disable_v3(self, monkeypatch):
        """Patch RouterV3 so tier selection falls through to rule-based logic."""
        def _raise():
            raise RuntimeError("RouterV3 disabled in tests")
        monkeypatch.setattr(
            "engine.lmstudio.router_v3_client.get_router_v3_client",
            _raise,
        )

    def test_explicit_tier(self):
        router = _make_router()
        req = InferenceRequest(tier=Tier.CPU_UTILITY)
        assert router.select_tier(req) == Tier.CPU_UTILITY

    def test_classify_goes_to_router(self):
        router = _make_router()
        req = InferenceRequest(task_type="classify")
        assert router.select_tier(req) == Tier.CPU_ROUTER

    def test_route_goes_to_router(self):
        router = _make_router()
        req = InferenceRequest(task_type="route")
        assert router.select_tier(req) == Tier.CPU_ROUTER

    def test_act_goes_to_gpu(self):
        router = _make_router()
        req = InferenceRequest(task_type="act", tools=[lambda: None])
        assert router.select_tier(req) == Tier.GPU_PRIMARY

    def test_tools_always_gpu(self):
        router = _make_router()
        req = InferenceRequest(tools=[lambda: None])
        assert router.select_tier(req) == Tier.GPU_PRIMARY

    def test_background_goes_to_cpu(self):
        router = _make_router()
        req = InferenceRequest(priority=Priority.BACKGROUND, task_type="chat")
        assert router.select_tier(req) == Tier.CPU_UTILITY

    def test_batch_goes_to_cpu(self):
        router = _make_router()
        req = InferenceRequest(priority=Priority.BATCH)
        assert router.select_tier(req) == Tier.CPU_UTILITY

    def test_realtime_chat_goes_to_gpu(self):
        router = _make_router()
        req = InferenceRequest(priority=Priority.REALTIME, task_type="chat")
        assert router.select_tier(req) == Tier.GPU_PRIMARY

    def test_interactive_chat_goes_to_gpu(self):
        router = _make_router()
        req = InferenceRequest(priority=Priority.INTERACTIVE, task_type="chat")
        assert router.select_tier(req) == Tier.GPU_PRIMARY

    def test_disabled_router_tier_falls_back(self):
        router = _make_router()
        router._tiers[Tier.CPU_ROUTER].enabled = False
        req = InferenceRequest(task_type="classify")
        # Should fall through to GPU_PRIMARY
        assert router.select_tier(req) == Tier.GPU_PRIMARY


# ── Tests: Channel selection ─────────────────────────────────────────

class TestChannelSelection:
    def test_explicit_channel(self):
        router = _make_router()
        req = InferenceRequest(channel=Channel.REST)
        assert router.select_channel(req, Tier.GPU_PRIMARY) == Channel.REST

    def test_act_forces_sdk(self):
        router = _make_router()
        req = InferenceRequest(task_type="act", tools=[lambda: None])
        assert router.select_channel(req, Tier.GPU_PRIMARY) == Channel.SDK

    def test_stateful_chat_forces_rest(self):
        router = _make_router()
        config = MagicMock()
        config.previous_response_id = "resp_abc123"
        req = InferenceRequest(config=config)
        assert router.select_channel(req, Tier.GPU_PRIMARY) == Channel.REST

    def test_default_uses_tier_channel(self):
        router = _make_router()
        req = InferenceRequest()
        # GPU tier defaults to SDK
        assert router.select_channel(req, Tier.GPU_PRIMARY) == Channel.SDK


# ── Tests: Slot management ───────────────────────────────────────────

class TestSlotManagement:
    def test_has_available_slot(self):
        router = _make_router()
        assert router.has_available_slot(Tier.GPU_PRIMARY)

    def test_no_slot_when_full(self):
        router = _make_router()
        router._tiers[Tier.GPU_PRIMARY]._busy_slots = 2
        assert not router.has_available_slot(Tier.GPU_PRIMARY)

    def test_disabled_tier_no_slot(self):
        router = _make_router()
        router._tiers[Tier.CPU_ROUTER].enabled = False
        assert not router.has_available_slot(Tier.CPU_ROUTER)


# ── Tests: Priority queue ────────────────────────────────────────────

class TestPriorityQueue:
    def test_submit_returns_future(self):
        router = _make_router()
        req = InferenceRequest(messages="Hello")
        future = router.submit(req)
        assert isinstance(future, Future)

    def test_queue_depth_tracked(self):
        router = _make_router()
        router.submit(InferenceRequest(messages="A"))
        router.submit(InferenceRequest(messages="B"))
        assert router._metrics.queue_depth == 2

    def test_queue_full_rejects(self):
        router = _make_router(max_queue_depth=2)
        router.submit(InferenceRequest(messages="A"))
        router.submit(InferenceRequest(messages="B"))
        future = router.submit(InferenceRequest(messages="C"))
        with pytest.raises(RuntimeError, match="queue full"):
            future.result(timeout=1)

    def test_priority_ordering(self):
        """Higher priority items should be dequeued first."""
        router = _make_router()
        f_batch = router.submit(InferenceRequest(
            messages="Batch", priority=Priority.BATCH
        ))
        f_realtime = router.submit(InferenceRequest(
            messages="Realtime", priority=Priority.REALTIME
        ))

        # Verify the queue ordering
        with router._lock:
            priorities = [item[0] for item in router._queue]
            assert priorities[0] == Priority.REALTIME.value
            assert priorities[1] == Priority.BATCH.value

    def test_metrics_increment(self):
        router = _make_router()
        router.submit(InferenceRequest(messages="A", priority=Priority.REALTIME))
        assert router._metrics.total_submitted == 1
        assert router._metrics.priority_counts.get("REALTIME") == 1


# ── Tests: Execution (with mocked clients) ───────────────────────────

class TestExecution:
    def test_execute_via_sdk(self):
        router = _make_router()
        mock_sdk = MagicMock()
        mock_sdk.respond.return_value = _mock_sdk_response("SDK reply")
        router._sdk_client = mock_sdk

        req = InferenceRequest(messages="Hello", task_type="chat")
        result = router._execute_request(req, Tier.GPU_PRIMARY, Channel.SDK)
        assert result.content == "SDK reply"
        mock_sdk.respond.assert_called_once()

    def test_execute_via_rest(self):
        router = _make_router()
        mock_rest = MagicMock()
        mock_rest.chat.return_value = _mock_sdk_response("REST reply")
        router._rest_client = mock_rest

        req = InferenceRequest(messages="Hello", task_type="chat")
        result = router._execute_request(req, Tier.GPU_PRIMARY, Channel.REST)
        assert result.content == "REST reply"

    def test_execute_act_uses_sdk(self):
        router = _make_router()
        mock_sdk = MagicMock()
        mock_sdk.act.return_value = _mock_sdk_response("Act result")
        router._sdk_client = mock_sdk

        req = InferenceRequest(
            messages="Use tool", task_type="act",
            tools=[lambda: "result"],
        )
        result = router._execute_request(req, Tier.GPU_PRIMARY, Channel.SDK)
        mock_sdk.act.assert_called_once()

    def test_no_sdk_raises(self):
        router = _make_router()
        req = InferenceRequest(messages="Hello")
        with pytest.raises(RuntimeError, match="SDK client not configured"):
            router._execute_request(req, Tier.GPU_PRIMARY, Channel.SDK)


# ── Tests: Worker loop integration ───────────────────────────────────

class TestWorkerLoop:
    @pytest.fixture(autouse=True)
    def disable_v3(self, monkeypatch):
        """Patch RouterV3 so the worker loop doesn't load ML models."""
        def _raise():
            raise RuntimeError("RouterV3 disabled in tests")
        monkeypatch.setattr(
            "engine.lmstudio.router_v3_client.get_router_v3_client",
            _raise,
        )

    def test_worker_processes_queue(self):
        router = _make_router()
        mock_sdk = MagicMock()
        mock_sdk.respond.return_value = _mock_sdk_response("Worker reply")
        router._sdk_client = mock_sdk

        router.start()
        try:
            req = InferenceRequest(messages="Hello", priority=Priority.REALTIME)
            future = router.submit(req)
            result = future.result(timeout=5)
            assert result.content == "Worker reply"
            assert router._metrics.total_completed >= 1
        finally:
            router.stop()

    def test_worker_handles_errors(self):
        router = _make_router()
        mock_sdk = MagicMock()
        mock_sdk.respond.side_effect = RuntimeError("LLM crashed")
        router._sdk_client = mock_sdk

        router.start()
        try:
            req = InferenceRequest(messages="Hello")
            future = router.submit(req)
            with pytest.raises(RuntimeError, match="LLM crashed"):
                future.result(timeout=5)
            assert router._metrics.total_errors >= 1
        finally:
            router.stop()

    def test_multiple_requests_processed(self):
        router = _make_router()
        call_count = 0
        def mock_respond(msgs, **kw):
            nonlocal call_count
            call_count += 1
            return _mock_sdk_response(f"Reply {call_count}")

        mock_sdk = MagicMock()
        mock_sdk.respond.side_effect = mock_respond
        router._sdk_client = mock_sdk

        router.start()
        try:
            futures = []
            for i in range(5):
                req = InferenceRequest(messages=f"Msg {i}")
                futures.append(router.submit(req))

            for f in futures:
                result = f.result(timeout=10)
                assert "Reply" in result.content

            assert router._metrics.total_completed == 5
        finally:
            router.stop()


# ── Tests: Metrics ───────────────────────────────────────────────────

class TestMetrics:
    def test_get_metrics_structure(self):
        router = _make_router()
        metrics = router.get_metrics()
        assert "total_submitted" in metrics
        assert "total_completed" in metrics
        assert "queue_depth" in metrics
        assert "slots" in metrics
        assert "gpu_primary" in metrics["slots"]


# ── Tests: Fallback ──────────────────────────────────────────────────

class TestFallback:
    def test_gpu_full_falls_to_cpu(self):
        router = _make_router()
        req = InferenceRequest(messages="Hello", task_type="chat")
        fallback = router._find_fallback_tier(Tier.GPU_PRIMARY, req)
        assert fallback == Tier.CPU_UTILITY

    def test_no_fallback_for_tool_calls(self):
        router = _make_router()
        req = InferenceRequest(messages="Hello", tools=[lambda: None])
        fallback = router._find_fallback_tier(Tier.GPU_PRIMARY, req)
        assert fallback is None  # Can't fall back tool calls to CPU

    def test_cpu_full_falls_to_gpu(self):
        router = _make_router()
        req = InferenceRequest(messages="Hello")
        fallback = router._find_fallback_tier(Tier.CPU_UTILITY, req)
        assert fallback == Tier.GPU_PRIMARY
