"""Tests for InferenceOrchestrator — unified model lifecycle + routing."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from engine.lmstudio.orchestrator import (
    InferenceOrchestrator,
    AgentProfile,
    TierPerformance,
    get_orchestrator,
    reset_orchestrator,
)


# ── TierPerformance ────────────────────────────────────────────


class TestTierPerformance:
    def test_empty_stats(self):
        tp = TierPerformance()
        assert tp.avg_latency_ms == 0.0
        assert tp.avg_tps == 0.0
        assert tp.error_rate == 0.0

    def test_record_success(self):
        tp = TierPerformance()
        tp.record(100.0, 25.0)
        tp.record(200.0, 30.0)
        assert tp.successes == 2
        assert tp.avg_latency_ms == 150.0
        assert tp.avg_tps == 27.5

    def test_record_error(self):
        tp = TierPerformance()
        tp.record(100.0, 25.0)
        tp.record_error()
        assert tp.error_rate == 0.5

    def test_to_dict(self):
        tp = TierPerformance()
        tp.record(50.0, 10.0)
        d = tp.to_dict()
        assert "avg_latency_ms" in d
        assert "avg_tps" in d
        assert "error_rate" in d
        assert "samples" in d
        assert d["samples"] == 1

    def test_rolling_window(self):
        tp = TierPerformance()
        for i in range(60):
            tp.record(float(i), float(i))
        # Window is 50, so avg should be of last 50
        assert tp.successes == 60
        assert len(tp.latency_ms) == 50


# ── AgentProfile ───────────────────────────────────────────────


class TestAgentProfile:
    def test_defaults(self):
        p = AgentProfile(agent_id="test")
        assert p.preferred_tier == "auto"
        assert p.preferred_model == ""
        assert p.max_tokens == 2048
        assert p.context_budget == 8192
        assert p.temperature == 0.7

    def test_custom(self):
        p = AgentProfile(
            agent_id="aria",
            preferred_tier="gpu_primary",
            preferred_model="qwen-32b",
            max_tokens=4096,
        )
        assert p.agent_id == "aria"
        assert p.preferred_model == "qwen-32b"
        assert p.max_tokens == 4096


# ── InferenceOrchestrator ──────────────────────────────────────


class TestOrchestrator:
    @pytest.fixture
    def orch(self):
        reset_orchestrator()
        mock_config = MagicMock()
        mock_config.get.return_value = "concurrent"
        o = InferenceOrchestrator(config=mock_config)
        return o

    def test_init(self, orch):
        assert orch._total_requests == 0
        assert orch._total_errors == 0
        assert len(orch._profiles) == 0

    def test_register_agent(self, orch):
        p = AgentProfile(agent_id="aria", preferred_tier="gpu_primary")
        orch.register_agent(p)
        assert "aria" in orch._profiles
        assert orch._profiles["aria"].preferred_tier == "gpu_primary"

    def test_unregister_agent(self, orch):
        p = AgentProfile(agent_id="test")
        orch.register_agent(p)
        orch.unregister_agent("test")
        assert "test" not in orch._profiles

    def test_configure_chaining(self, orch):
        result = orch.configure(client=MagicMock())
        assert result is orch

    def test_tier_selection_classify(self, orch):
        profile = AgentProfile(agent_id="test")
        tier = orch._select_tier("classify", "interactive", profile, False)
        assert tier == "cpu_router"

    def test_tier_selection_tools(self, orch):
        profile = AgentProfile(agent_id="test")
        tier = orch._select_tier("chat", "interactive", profile, True)
        assert tier == "gpu_primary"

    def test_tier_selection_act(self, orch):
        profile = AgentProfile(agent_id="test")
        tier = orch._select_tier("act", "interactive", profile, False)
        assert tier == "gpu_primary"

    def test_tier_selection_background(self, orch):
        profile = AgentProfile(agent_id="test")
        tier = orch._select_tier("chat", "background", profile, False)
        # Without utility perf data, should default to gpu_primary
        assert tier == "gpu_primary"

    def test_tier_selection_background_with_utility(self, orch):
        # Record good utility performance
        orch._perf["cpu_utility"].record(50.0, 20.0)
        profile = AgentProfile(agent_id="test")
        tier = orch._select_tier("chat", "background", profile, False)
        assert tier == "cpu_utility"

    def test_tier_selection_explicit_profile(self, orch):
        profile = AgentProfile(agent_id="test", preferred_tier="cpu_utility")
        tier = orch._select_tier("chat", "interactive", profile, False)
        assert tier == "cpu_utility"

    def test_tier_to_role(self):
        assert InferenceOrchestrator._tier_to_role("gpu_primary") == "big"
        assert InferenceOrchestrator._tier_to_role("cpu_utility") == "small"
        assert InferenceOrchestrator._tier_to_role("cpu_router") == "router"
        assert InferenceOrchestrator._tier_to_role("unknown") == "big"

    def test_get_status(self, orch):
        status = orch.get_status()
        assert "orchestrator" in status
        assert "performance_by_tier" in status
        assert "agent_profiles" in status
        assert status["orchestrator"]["total_requests"] == 0

    def test_get_performance_empty(self, orch):
        perf = orch.get_performance()
        assert perf == {}

    def test_get_performance_with_data(self, orch):
        orch._perf["gpu_primary"].record(100.0, 30.0)
        perf = orch.get_performance("gpu_primary")
        assert "gpu_primary" in perf
        assert perf["gpu_primary"]["avg_latency_ms"] == 100.0

    def test_get_performance_missing_tier(self, orch):
        perf = orch.get_performance("nonexistent")
        assert perf == {}

    def test_infer_sync(self, orch):
        mock_resp = MagicMock()
        mock_resp.content = "Hello!"
        mock_resp.usage = MagicMock(completion_tokens=10)
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_resp
        mock_rm = MagicMock()
        mock_rm.acquire.return_value = "test-model"
        orch.configure(client=mock_client, resource_manager=mock_rm)

        resp = orch.infer(
            agent_id="test",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert resp.content == "Hello!"
        assert orch._total_requests == 1

    def test_infer_quick(self, orch):
        mock_resp = MagicMock()
        mock_resp.content = "World"
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_resp
        mock_rm = MagicMock()
        mock_rm.acquire.return_value = "m"
        orch.configure(client=mock_client, resource_manager=mock_rm)

        result = orch.infer_quick("Hello", agent_id="a")
        assert result == "World"


# ── Singleton ──────────────────────────────────────────────────


class TestSingleton:
    def test_get_orchestrator(self):
        reset_orchestrator()
        o1 = get_orchestrator()
        o2 = get_orchestrator()
        assert o1 is o2
        reset_orchestrator()

    def test_reset_orchestrator(self):
        reset_orchestrator()
        o1 = get_orchestrator()
        reset_orchestrator()
        o2 = get_orchestrator()
        assert o1 is not o2
        reset_orchestrator()
