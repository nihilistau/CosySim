"""
End-to-end pipeline smoke test for CosySim v2.9.

Tests the full inference pipeline:
  InferenceRequest → VirtualAgentManager.infer()
    → _execute_request()  (store=False direct / stateful / retry)
    → _is_garbage_response()  (evaluator integration)
    → InferenceResponse

Also tests:
  - ContentRouter ↔ AgentLoop._parse_decision()
  - TextEvaluator ↔ quality gate
  - Conversation branching override
  - Interceptor pipeline (governor pre/post hooks)
  - Conversation repair (garbage → retry at lower temp)

All LMStudio calls are mocked. No network needed.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass

from engine.agents.virtual_agent import InferenceRequest, InferenceResponse
from engine.agents.content_router import ContentRouter, extract_json
from engine.agents.evaluator import TextEvaluator, ResponseScore


# ═══════════════════════════════════════════════════════════════════════
#  1. VirtualAgentManager full pipeline
# ═══════════════════════════════════════════════════════════════════════

class TestManagerPipeline:
    """Exercise VirtualAgentManager.infer() end-to-end."""

    def _make_mgr(self):
        from engine.agents.virtual_agent_manager import VirtualAgentManager
        return VirtualAgentManager()

    def _make_request(self, **overrides):
        defaults = dict(
            agent_id="test_agent",
            messages=[{"role": "user", "content": "Hello!"}],
            model="test-model",
            store=False,
        )
        defaults.update(overrides)
        return InferenceRequest(**defaults)

    def _fake_lms_response(self, content="Hi there!", **kw):
        resp = MagicMock()
        resp.content = content
        resp.reasoning_content = kw.get("reasoning", "")
        resp.model = kw.get("model", "test-model")
        resp.response_id = kw.get("response_id", "")
        resp.input_tokens = kw.get("input_tokens", 50)
        resp.output_tokens = kw.get("output_tokens", 20)
        resp.reasoning_tokens = kw.get("reasoning_tokens", 0)
        resp.latency_ms = kw.get("latency_ms", 100.0)
        resp.tool_calls = kw.get("tool_calls", [])
        resp.server_tps = kw.get("server_tps", 15.0)
        resp.time_to_first_token_s = kw.get("ttft", 0.5)
        resp.model_load_time_s = kw.get("load_time", 0.0)
        return resp

    @patch("engine.lmstudio.lms_client.get_lms_client")
    def test_stateless_request_skips_conversation(self, mock_get_client):
        """store=False → direct chat, no ConversationManager."""
        client = MagicMock()
        client.chat.return_value = self._fake_lms_response("Direct reply!")
        mock_get_client.return_value = client

        mgr = self._make_mgr()
        req = self._make_request(store=False)
        resp = mgr.infer(req)

        assert resp.ok
        assert resp.content == "Direct reply!"
        client.chat.assert_called_once()
        _, kwargs = client.chat.call_args
        assert kwargs.get("store") is False

    @patch("engine.lmstudio.lms_client.get_lms_client")
    def test_stateful_request_uses_conversation(self, mock_get_client):
        """conversation_id present → stateful ConversationManager path."""
        client = MagicMock()
        mock_get_client.return_value = client

        mgr = self._make_mgr()
        req = self._make_request(
            store=None,
            conversation_id="test_conv_1",
        )
        # Mock _infer_stateful
        expected = InferenceResponse(content="Stateful reply!", model="test-model")
        mgr._infer_stateful = MagicMock(return_value=expected)

        resp = mgr.infer(req)

        assert resp.ok
        assert resp.content == "Stateful reply!"
        mgr._infer_stateful.assert_called_once()

    @patch("engine.lmstudio.lms_client.get_lms_client")
    def test_garbage_response_triggers_retry(self, mock_get_client):
        """Garbage response triggers conversation repair (store=None path)."""
        client = MagicMock()
        # First call returns garbage, second returns good
        garbage_resp = self._fake_lms_response("")
        good_resp = self._fake_lms_response("A proper thoughtful reply.")
        client.chat.side_effect = [garbage_resp, good_resp]
        mock_get_client.return_value = client

        mgr = self._make_mgr()
        # store=None (not False) so it goes through the direct fallback path with retry
        req = self._make_request(store=None)
        resp = mgr.infer(req)

        assert resp.ok
        assert resp.content == "A proper thoughtful reply."
        assert client.chat.call_count == 2

    @patch("engine.lmstudio.lms_client.get_lms_client")
    def test_stats_tracking(self, mock_get_client):
        """Stats are accumulated across requests."""
        client = MagicMock()
        client.chat.return_value = self._fake_lms_response(
            "Hi!", input_tokens=100, output_tokens=25
        )
        mock_get_client.return_value = client

        mgr = self._make_mgr()
        mgr.infer(self._make_request(store=False))
        mgr.infer(self._make_request(store=False))

        assert mgr._total_requests == 2
        assert mgr._total_tokens_in == 200
        assert mgr._total_tokens_out == 50

    @patch("engine.lmstudio.lms_client.get_lms_client")
    def test_pre_post_hooks_fire(self, mock_get_client):
        """Pre and post hooks are called on every request."""
        client = MagicMock()
        client.chat.return_value = self._fake_lms_response("Hello")
        mock_get_client.return_value = client

        pre_log, post_log = [], []
        mgr = self._make_mgr()
        mgr._pre_hooks.append(lambda req: pre_log.append(req.agent_id))
        mgr._post_hooks.append(lambda req, resp: post_log.append(resp.content))

        mgr.infer(self._make_request(store=False))

        assert pre_log == ["test_agent"]
        assert post_log == ["Hello"]

    @patch("engine.lmstudio.lms_client.get_lms_client")
    def test_error_produces_error_response(self, mock_get_client):
        """LMS exception → InferenceResponse with error field."""
        client = MagicMock()
        client.chat.side_effect = ConnectionError("LMStudio unreachable")
        mock_get_client.return_value = client

        mgr = self._make_mgr()
        resp = mgr.infer(self._make_request(store=False))

        assert not resp.ok
        assert "unreachable" in resp.error.lower()
        assert mgr._total_errors == 1


# ═══════════════════════════════════════════════════════════════════════
#  2. ContentRouter + evaluator integration
# ═══════════════════════════════════════════════════════════════════════

class TestContentRouterIntegration:
    """ContentRouter JSON extraction feeds into evaluator scoring."""

    def test_parse_decision_from_wrapped_json(self):
        """ContentRouter extracts valid action from text-wrapped JSON."""
        raw = """Sure, I'll think about it.
        ```json
        {"action": "speak", "target": "user", "message": "Hey, want to play a game?"}
        ```
        """
        result = ContentRouter.parse_decision(raw, ["speak", "move", "wait"])
        assert result is not None
        assert result["action"] == "speak"
        assert "game" in result["message"]

    def test_parse_decision_with_trailing_comma(self):
        """Trailing commas in LLM JSON don't break parsing."""
        raw = '{"action": "speak", "message": "Hello!",}'
        result = ContentRouter.parse_decision(raw, ["speak"])
        assert result is not None
        assert result["action"] == "speak"

    def test_parse_decision_unknown_action_falls_back_to_idle(self):
        """Unknown action → falls back to default 'idle' action."""
        raw = '{"action": "fly", "message": "Wheee!"}'
        result = ContentRouter.parse_decision(raw, ["speak", "move", "wait"])
        assert result["action"] == "idle"

    def test_evaluator_scores_good_response_higher(self):
        """TextEvaluator gives higher score to expressive vs bland responses."""
        evaluator = TextEvaluator()
        good = "Oh wow, that's actually a really interesting question! I've been thinking about it a lot lately, and I believe the answer involves both creativity and persistence."
        bland = "ok"
        good_score = evaluator.score_heuristic(good)
        bland_score = evaluator.score_heuristic(bland)
        assert good_score.total > bland_score.total

    def test_evaluator_detects_garbage(self):
        """Empty and whitespace-only responses are garbage."""
        evaluator = TextEvaluator()
        assert evaluator.is_garbage("")
        assert evaluator.is_garbage("   \n  ")
        assert evaluator.is_garbage(".")  # too short (< 3 chars)
        assert not evaluator.is_garbage("Hello, how are you doing today?")

    def test_evaluator_detects_token_artifacts(self):
        """Token artifacts are flagged as problems (not garbage, but problematic)."""
        evaluator = TextEvaluator()
        score = evaluator.score_heuristic("<|end_of_text|> hello there")
        assert "token_artifacts" in score.problems


# ═══════════════════════════════════════════════════════════════════════
#  3. Quality gate
# ═══════════════════════════════════════════════════════════════════════

class TestQualityGate:
    """Quality gate generates multiple variants and picks the best."""

    @patch("engine.lmstudio.lms_client.get_lms_client")
    def test_quality_gate_picks_best(self, mock_get_client):
        """infer_quality_gate returns the highest-scoring variant."""
        from engine.agents.virtual_agent_manager import VirtualAgentManager

        client = MagicMock()
        # Return increasingly better responses
        responses = [
            self._fake("ok"),
            self._fake("That's a wonderful idea! Let me think about the best approach we could take together."),
        ]
        client.chat.side_effect = responses
        mock_get_client.return_value = client

        mgr = VirtualAgentManager()
        req = InferenceRequest(
            agent_id="test",
            messages=[{"role": "user", "content": "test"}],
            store=False,
        )
        resp = mgr.infer_quality_gate(req, variants=2)

        assert resp.ok
        # Should pick the longer, more expressive response
        assert len(resp.content) > 5

    def _fake(self, content):
        resp = MagicMock()
        resp.content = content
        resp.reasoning_content = ""
        resp.model = "test"
        resp.response_id = ""
        resp.input_tokens = 10
        resp.output_tokens = len(content.split())
        resp.reasoning_tokens = 0
        resp.latency_ms = 50.0
        resp.tool_calls = []
        resp.server_tps = 10.0
        resp.time_to_first_token_s = 0.2
        resp.model_load_time_s = 0.0
        return resp


# ═══════════════════════════════════════════════════════════════════════
#  4. Conversation branching override
# ═══════════════════════════════════════════════════════════════════════

class TestConversationBranching:
    """Conversation.send() respects previous_response_id_override."""

    def test_conversation_has_override_parameter(self):
        """Conversation.send() accepts previous_response_id_override."""
        from engine.lmstudio.conversation import Conversation
        import inspect
        sig = inspect.signature(Conversation.send)
        assert "previous_response_id_override" in sig.parameters

    def test_conversation_state_tracks_response_ids(self):
        """Conversation records response_id history for branching."""
        from engine.lmstudio.conversation import Conversation
        conv = Conversation(conversation_id="test_track")
        # Simulate recording response IDs (internal mechanism)
        conv._response_id_history.append("resp_001")
        conv._response_id_history.append("resp_002")
        conv._response_id_history.append("resp_003")
        conv.response_id = "resp_003"
        assert conv.response_id == "resp_003"
        assert len(conv._response_id_history) == 3
        # branch_at exists and takes turn_index
        assert hasattr(conv, "branch_at")


# ═══════════════════════════════════════════════════════════════════════
#  5. ContentRouter classification
# ═══════════════════════════════════════════════════════════════════════

class TestContentClassification:
    """ContentRouter correctly classifies response types."""

    def test_classify_json(self):
        result = ContentRouter.classify('{"action": "speak"}')
        assert result.content_type == "json"
        assert result.json_data is not None

    def test_classify_tagged_text(self):
        result = ContentRouter.classify("Hello [MOOD:happy] world!")
        assert result.content_type == "tagged_text"
        assert "MOOD" in result.tags

    def test_classify_plain(self):
        result = ContentRouter.classify("Just a regular message.")
        assert result.content_type == "plain_text"

    def test_extract_json_nested(self):
        """Nested JSON objects are extracted correctly."""
        text = 'Here is the plan: {"outer": {"inner": [1, 2, 3]}, "done": true}'
        result = extract_json(text)
        assert result is not None
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_extract_json_no_json(self):
        """Text without JSON returns None."""
        assert extract_json("No JSON here at all") is None


# ═══════════════════════════════════════════════════════════════════════
#  6. InferenceResponse dataclass
# ═══════════════════════════════════════════════════════════════════════

class TestInferenceResponse:
    """InferenceResponse properties work correctly."""

    def test_ok_property(self):
        assert InferenceResponse(content="hi").ok is True
        assert InferenceResponse(error="fail").ok is False

    def test_is_stateful_property(self):
        assert InferenceResponse(response_id="resp_abc123").is_stateful is True
        assert InferenceResponse(response_id="").is_stateful is False
        assert InferenceResponse(response_id="chatcmpl-xxx").is_stateful is False

    def test_tokens_per_second(self):
        resp = InferenceResponse(server_tps=25.0)
        assert resp.tokens_per_second == 25.0

    def test_from_lms_response(self):
        lms = MagicMock()
        lms.content = "Response text"
        lms.reasoning_content = ""
        lms.model = "qwen3-8b"
        lms.response_id = "resp_test"
        lms.input_tokens = 100
        lms.output_tokens = 30
        lms.reasoning_tokens = 0
        lms.latency_ms = 250.0
        lms.tool_calls = []
        lms.server_tps = 12.0
        lms.time_to_first_token_s = 1.2
        lms.model_load_time_s = 0.0

        resp = InferenceResponse.from_lms_response(lms)
        assert resp.content == "Response text"
        assert resp.model == "qwen3-8b"
        assert resp.input_tokens == 100
        assert resp.is_stateful is True
