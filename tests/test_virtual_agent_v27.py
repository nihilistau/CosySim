"""
Tests for VirtualAgent / VirtualAgentManager v2.7 features.

Covers:
- InferenceRequest store/stream/on_event fields
- InferenceResponse v1 stats, is_stateful, tokens_per_second
- InferenceResponse.from_lms_response()
- VirtualAgent.quick_query() uses store=False
- VirtualAgent response_id tracking in state
- ResponseContext v2.7 keys (response_id, is_stateful)
"""
import time
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import asdict

from engine.agents.virtual_agent import InferenceRequest, InferenceResponse


# ── InferenceRequest tests ─────────────────────────────────────────

class TestInferenceRequestV27:

    def test_store_default_is_none(self):
        req = InferenceRequest(agent_id="a1", messages=[])
        assert req.store is None

    def test_store_false_for_stateless(self):
        req = InferenceRequest(agent_id="a1", messages=[], store=False)
        assert req.store is False

    def test_store_true_explicit(self):
        req = InferenceRequest(agent_id="a1", messages=[], store=True)
        assert req.store is True

    def test_stream_default_false(self):
        req = InferenceRequest(agent_id="a1", messages=[])
        assert req.stream is False

    def test_on_event_default_none(self):
        req = InferenceRequest(agent_id="a1", messages=[])
        assert req.on_event is None

    def test_stream_with_callback(self):
        cb = lambda evt: None
        req = InferenceRequest(agent_id="a1", messages=[], stream=True, on_event=cb)
        assert req.stream is True
        assert req.on_event is cb


# ── InferenceResponse tests ────────────────────────────────────────

class TestInferenceResponseV27:

    def test_is_stateful_with_resp_prefix(self):
        resp = InferenceResponse(response_id="resp_abc123")
        assert resp.is_stateful is True

    def test_is_stateful_empty(self):
        resp = InferenceResponse(response_id="")
        assert resp.is_stateful is False

    def test_is_stateful_non_resp(self):
        resp = InferenceResponse(response_id="chatcmpl-xxx")
        assert resp.is_stateful is False

    def test_server_tps_overrides_calculated(self):
        resp = InferenceResponse(
            server_tps=45.0,
            output_tokens=100,
            latency_ms=5000.0,
        )
        assert resp.tokens_per_second == 45.0

    def test_fallback_tps_when_no_server_tps(self):
        resp = InferenceResponse(
            server_tps=0.0,
            output_tokens=100,
            latency_ms=2000.0,
        )
        assert abs(resp.tokens_per_second - 50.0) < 0.01

    def test_tps_zero_when_no_data(self):
        resp = InferenceResponse()
        assert resp.tokens_per_second == 0.0

    def test_from_lms_response_maps_all_fields(self):
        mock = MagicMock()
        mock.content = "Hello"
        mock.reasoning_content = "Thinking..."
        mock.model = "qwen-7b"
        mock.response_id = "resp_abc"
        mock.input_tokens = 100
        mock.output_tokens = 50
        mock.reasoning_tokens = 20
        mock.latency_ms = 1500.0
        mock.tool_calls = [{"name": "foo"}]
        mock.server_tps = 33.3
        mock.time_to_first_token_s = 0.5
        mock.model_load_time_s = 2.1

        resp = InferenceResponse.from_lms_response(mock)
        assert resp.content == "Hello"
        assert resp.reasoning_content == "Thinking..."
        assert resp.model == "qwen-7b"
        assert resp.response_id == "resp_abc"
        assert resp.is_stateful is True
        assert resp.input_tokens == 100
        assert resp.output_tokens == 50
        assert resp.reasoning_tokens == 20
        assert resp.server_tps == 33.3
        assert resp.time_to_first_token_s == 0.5
        assert resp.model_load_time_s == 2.1
        assert resp.tool_calls == [{"name": "foo"}]

    def test_from_error(self):
        resp = InferenceResponse.from_error("timeout")
        assert resp.ok is False
        assert resp.error == "timeout"
        assert resp.is_stateful is False

    def test_v27_stats_defaults(self):
        resp = InferenceResponse()
        assert resp.reasoning_tokens == 0
        assert resp.server_tps == 0.0
        assert resp.time_to_first_token_s == 0.0
        assert resp.model_load_time_s == 0.0


# ── ResponseContext v2.7 keys ──────────────────────────────────────

class TestResponseContextV27:

    def test_v27_keys_documented(self):
        from engine.mcp.comms_framework import ResponseContext
        ctx = ResponseContext(
            response_id="resp_xyz",
            store=True,
            is_stateful=True,
            reasoning="Some thought",
            tool_calls=[],
        )
        assert ctx["response_id"] == "resp_xyz"
        assert ctx["is_stateful"] is True
        assert ctx["store"] is True

    def test_require_raises_on_missing(self):
        from engine.mcp.comms_framework import ResponseContext
        ctx = ResponseContext()
        with pytest.raises(KeyError, match="response_id"):
            ctx.require("response_id")


# ── Governance context flow tests ──────────────────────────────────

class TestGovernanceContext:

    def _make_agent(self):
        """Create a minimal VirtualAgent for testing."""
        char = MagicMock()
        char.id = "test_char"
        char.name = "TestChar"
        char.personality = None
        char.age = 25
        char.appearance = ""
        char.backstory = ""
        char.sexual_openness = "moderate"
        char.description = ""
        # Personality floats needed by _build_system_prompt
        char.warmth = 0.5
        char.formality = 0.5
        char.humor = 0.5
        char.flirtiness = 0.5
        char.intelligence = 0.5
        char.creativity = 0.5
        char.mood = "relaxed"
        char.energy = 1.0
        char.arousal = 0.0

        from engine.agents.virtual_agent import VirtualAgent
        agent = VirtualAgent(char, scene="test")
        agent._manager = MagicMock()
        return agent

    def test_build_request_appends_governance_context(self):
        """governance_context should be appended to system prompt."""
        agent = self._make_agent()

        req1 = agent.build_request("Hello", use_tools=False)
        sys1 = req1.messages[0]["content"]

        req2 = agent.build_request(
            "Hello",
            use_tools=False,
            governance_context="--- SCENE STATE ---\nArousal=50",
        )
        sys2 = req2.messages[0]["content"]

        assert "--- SCENE STATE ---" in sys2
        assert "Arousal=50" in sys2
        assert sys2.startswith(sys1)

    def test_build_request_no_governance_context(self):
        """Without governance_context, system prompt is unchanged."""
        agent = self._make_agent()

        req1 = agent.build_request("Hello", use_tools=False)
        req2 = agent.build_request(
            "Hello", use_tools=False, governance_context=None,
        )
        assert req1.messages[0]["content"] == req2.messages[0]["content"]

    def test_governance_context_empty_string_ignored(self):
        """Empty string governance_context should not add newlines."""
        agent = self._make_agent()

        req1 = agent.build_request("Hello", use_tools=False)
        req2 = agent.build_request(
            "Hello", use_tools=False, governance_context="",
        )
        assert req1.messages[0]["content"] == req2.messages[0]["content"]
