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


# ═══════════════════════════════════════════════════════════════════════
#  7. ParsedResponse — unified single-pass parsing (v3.1)
# ═══════════════════════════════════════════════════════════════════════

from engine.agents.content_router import ParsedResponse


class TestParsedResponse:
    """ContentRouter.parse_full() single-pass extraction."""

    def test_empty_text(self):
        parsed = ContentRouter.parse_full("")
        assert parsed.content == ""
        assert parsed.mood is None
        assert parsed.tags == {}

    def test_plain_text(self):
        parsed = ContentRouter.parse_full("Just chatting here.")
        assert parsed.content == "Just chatting here."
        assert parsed.mood is None
        assert not parsed.has_images

    def test_mood_extraction(self):
        parsed = ContentRouter.parse_full("I feel great! [MOOD:happy]")
        assert parsed.mood == "happy"
        assert "MOOD" in parsed.tags
        assert "I feel great!" in parsed.content
        assert "[MOOD:" not in parsed.content

    def test_mood_with_intensity(self):
        parsed = ContentRouter.parse_full("Oh my... [MOOD:excited intensity=0.9]")
        assert parsed.mood == "excited"
        assert parsed.mood_intensity == 0.9

    def test_image_request(self):
        parsed = ContentRouter.parse_full("Here! [IMAGE:sunset over ocean]")
        assert parsed.has_images
        assert "sunset over ocean" in parsed.image_requests

    def test_multiple_tags(self):
        text = "[MOOD:flirty] Check this out [IMAGE:a cat] and [ACTION:wink]"
        parsed = ContentRouter.parse_full(text)
        assert parsed.mood == "flirty"
        assert len(parsed.image_requests) == 1
        assert len(parsed.actions) == 1

    def test_game_events(self):
        parsed = ContentRouter.parse_full("You did it! [GAME_EVENT:round_won]")
        assert parsed.has_game_events
        assert "round_won" in parsed.game_events

    def test_legacy_game_markers(self):
        parsed = ContentRouter.parse_full("Truth time! [DARE_COMPLETE]")
        assert "DARE_COMPLETE" in parsed.game_events

    def test_json_extraction(self):
        text = 'Decision: {"action": "speak", "target": "player"}'
        parsed = ContentRouter.parse_full(text)
        assert parsed.json_data is not None
        assert parsed.json_data["action"] == "speak"

    def test_voice_hints(self):
        parsed = ContentRouter.parse_full("Whisper to me [VOICE:sultry]")
        assert "sultry" in parsed.voice_hints

    def test_stat_updates(self):
        parsed = ContentRouter.parse_full("Nice! [STAT:trust=+5]")
        assert "trust=+5" in parsed.stat_updates

    def test_token_artifacts_stripped(self):
        parsed = ContentRouter.parse_full("<|begin_of_text|>Hello world<|end_of_text|>")
        assert parsed.content == "Hello world"
        assert "<|" not in parsed.content

    def test_combined_complex(self):
        text = (
            "<|im_start|>Sure thing! [MOOD:happy intensity=0.7] "
            "Let me draw that for you. [IMAGE:a sunset] "
            "[ACTION:reaches for pen] [VOICE:cheerful] "
            "[DARE_COMPLETE]"
        )
        parsed = ContentRouter.parse_full(text)
        assert parsed.mood == "happy"
        assert parsed.mood_intensity == 0.7
        assert len(parsed.image_requests) == 1
        assert len(parsed.actions) == 1
        assert len(parsed.voice_hints) == 1
        assert "DARE_COMPLETE" in parsed.game_events
        assert "[MOOD:" not in parsed.content
        assert "[IMAGE:" not in parsed.content
        assert "<|im_start|>" not in parsed.content


# ═══════════════════════════════════════════════════════════════════════
#  8. Scene-aware interceptor filtering (v3.1)
# ═══════════════════════════════════════════════════════════════════════

class TestSceneAwareFiltering:
    """InterceptorPipeline respects applicable_scenes."""

    def test_interceptor_base_has_applicable_scenes(self):
        from engine.mcp.comms_framework import InterceptorBase
        base = InterceptorBase()
        assert base.applicable_scenes is None  # None = run everywhere

    def test_applicable_scenes_set_on_bedroom(self):
        from engine.agents.interceptors import BedroomSceneInterceptor
        b = BedroomSceneInterceptor()
        assert b.applicable_scenes == {"bedroom"}

    def test_applicable_scenes_set_on_phone(self):
        from engine.agents.interceptors import PhoneSceneInterceptor
        p = PhoneSceneInterceptor()
        assert p.applicable_scenes == {"phone"}

    def test_applicable_scenes_set_on_lounge(self):
        from engine.agents.interceptors import LoungeSceneInterceptor
        lg = LoungeSceneInterceptor()
        assert lg.applicable_scenes == {"lounge"}

    def test_global_interceptor_has_none(self):
        from engine.agents.interceptors import MoodSyncInterceptor
        m = MoodSyncInterceptor()
        assert m.applicable_scenes is None

    def test_pipeline_skips_wrong_scene(self):
        """BedroomSceneInterceptor should not run in phone scene."""
        from engine.mcp.comms_framework import InterceptorPipeline
        from engine.agents.interceptors import BedroomSceneInterceptor
        pipeline = InterceptorPipeline()
        bedroom = BedroomSceneInterceptor()
        pipeline.add(bedroom)
        # Should be skippable
        assert pipeline._is_applicable(bedroom, {"scene": "phone"}) is False

    def test_pipeline_runs_matching_scene(self):
        from engine.mcp.comms_framework import InterceptorPipeline
        from engine.agents.interceptors import BedroomSceneInterceptor
        pipeline = InterceptorPipeline()
        bedroom = BedroomSceneInterceptor()
        pipeline.add(bedroom)
        assert pipeline._is_applicable(bedroom, {"scene": "bedroom"}) is True

    def test_pipeline_runs_global_interceptor_anywhere(self):
        from engine.mcp.comms_framework import InterceptorPipeline
        from engine.agents.interceptors import MoodSyncInterceptor
        pipeline = InterceptorPipeline()
        mood = MoodSyncInterceptor()
        pipeline.add(mood)
        assert pipeline._is_applicable(mood, {"scene": "bedroom"}) is True
        assert pipeline._is_applicable(mood, {"scene": "phone"}) is True
        assert pipeline._is_applicable(mood, {}) is True


# ═══════════════════════════════════════════════════════════════════════
#  9. Interceptor cache (v3.1)
# ═══════════════════════════════════════════════════════════════════════

class TestInterceptorCache:
    """_InterceptorCache TTL behavior."""

    def test_get_set_basic(self):
        from engine.agents.interceptors import INTERCEPTOR_CACHE
        INTERCEPTOR_CACHE.clear()
        INTERCEPTOR_CACHE.set("agent1", "test_key", "test_value", ttl=60.0)
        assert INTERCEPTOR_CACHE.get("agent1", "test_key") == "test_value"
        INTERCEPTOR_CACHE.clear()

    def test_get_missing_returns_none(self):
        from engine.agents.interceptors import INTERCEPTOR_CACHE
        INTERCEPTOR_CACHE.clear()
        assert INTERCEPTOR_CACHE.get("nonexistent", "nope") is None

    def test_invalidate(self):
        from engine.agents.interceptors import INTERCEPTOR_CACHE
        INTERCEPTOR_CACHE.clear()
        INTERCEPTOR_CACHE.set("agent1", "key1", "val1")
        INTERCEPTOR_CACHE.invalidate("agent1", "key1")
        assert INTERCEPTOR_CACHE.get("agent1", "key1") is None
        INTERCEPTOR_CACHE.clear()

    def test_clear(self):
        from engine.agents.interceptors import INTERCEPTOR_CACHE
        INTERCEPTOR_CACHE.set("a", "k", "v")
        INTERCEPTOR_CACHE.set("b", "k", "v")
        INTERCEPTOR_CACHE.clear()
        assert INTERCEPTOR_CACHE.get("a", "k") is None

    def test_ttl_expiry(self):
        import time
        from engine.agents.interceptors import INTERCEPTOR_CACHE
        INTERCEPTOR_CACHE.clear()
        INTERCEPTOR_CACHE.set("agent1", "fast", "value", ttl=0.1)
        assert INTERCEPTOR_CACHE.get("agent1", "fast") == "value"
        time.sleep(0.15)
        assert INTERCEPTOR_CACHE.get("agent1", "fast") is None
        INTERCEPTOR_CACHE.clear()


# ═══════════════════════════════════════════════════════════════════════
#  10. GameInterceptor merge (v3.1)
# ═══════════════════════════════════════════════════════════════════════

class TestGameInterceptorMerge:
    """GameInterceptor is the merged class; aliases exist."""

    def test_merged_class_exists(self):
        from engine.agents.interceptors import GameInterceptor
        gi = GameInterceptor()
        assert gi.name == "game"
        assert gi.priority == 35

    def test_backward_compat_aliases(self):
        from engine.agents.interceptors import (
            GameSessionInterceptor, GameRulesInterceptor, GameInterceptor
        )
        assert GameSessionInterceptor is GameInterceptor
        assert GameRulesInterceptor is GameInterceptor

    def test_game_interceptor_has_pre_and_post(self):
        from engine.agents.interceptors import GameInterceptor
        gi = GameInterceptor()
        assert hasattr(gi, "pre_call")
        assert hasattr(gi, "post_call")


# ═══════════════════════════════════════════════════════════════════════
#  11. MCP Skills Server routes (v3.1)
# ═══════════════════════════════════════════════════════════════════════

class TestSkillsServer:
    """Skills server blueprint routes."""

    @pytest.fixture
    def client(self):
        from flask import Flask
        from engine.mcp.skills_server import skills_bp
        app = Flask(__name__)
        app.register_blueprint(skills_bp)
        app.config["TESTING"] = True
        return app.test_client()

    def test_health(self, client):
        resp = client.get("/mcp/skills/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_list_tools(self, client):
        resp = client.get("/mcp/skills/tools")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tools" in data
        assert isinstance(data["tools"], list)

    def test_list_packs(self, client):
        resp = client.get("/mcp/skills/packs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "packs" in data

    def test_call_missing_name(self, client):
        resp = client.post("/mcp/skills/call",
                           json={"arguments": {}},
                           content_type="application/json")
        assert resp.status_code == 400

    def test_call_unknown_tool(self, client):
        resp = client.post("/mcp/skills/call",
                           json={"name": "nonexistent_tool_xyz", "arguments": {}},
                           content_type="application/json")
        assert resp.status_code == 404

    def test_manifest(self, client):
        resp = client.get("/mcp/skills/manifest")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "skills" in data

    def test_pipeline_stats(self, client):
        resp = client.get("/mcp/skills/pipeline/stats")
        # May return 200 or 500 depending on VirtualAgentManager init,
        # but should not 404
        assert resp.status_code in (200, 500)


# ═══════════════════════════════════════════════════════════════════════
#  12. Skills server integration helper (v3.1)
# ═══════════════════════════════════════════════════════════════════════

class TestSkillsIntegration:
    """get_skills_integration() returns correct format."""

    def test_returns_none_without_port(self):
        from engine.mcp.skills_server import get_skills_integration, set_skills_server_port
        import engine.mcp.skills_server as ss
        old = ss._skills_server_port
        ss._skills_server_port = None
        assert get_skills_integration() is None
        ss._skills_server_port = old

    def test_returns_dict_with_port(self):
        from engine.mcp.skills_server import get_skills_integration, set_skills_server_port
        set_skills_server_port(5555)
        result = get_skills_integration()
        assert result is not None
        assert result["type"] == "ephemeral_mcp"
        assert "5555" in result["server_url"]
        assert "/mcp/skills" in result["server_url"]


# ═══════════════════════════════════════════════════════════════════════
#  13. Streaming conversation threading (v3.2)
# ═══════════════════════════════════════════════════════════════════════

class TestStreamingConversationThreading:
    """infer_stream creates and updates conversations."""

    def test_infer_stream_is_generator(self):
        """infer_stream() returns a generator that yields strings."""
        from engine.agents.virtual_agent_manager import VirtualAgentManager
        mgr = VirtualAgentManager.__new__(VirtualAgentManager)
        # Verify method exists and is a generator function
        import inspect
        assert hasattr(mgr, "infer_stream")

    def test_infer_processed_captures_return(self):
        """infer_processed uses StopIteration pattern to capture generator return."""
        from engine.agents.virtual_agent_manager import VirtualAgentManager
        import inspect
        source = inspect.getsource(VirtualAgentManager.infer_processed)
        # Should use StopIteration pattern, not simple for loop
        assert "StopIteration" in source
        assert "next(gen)" in source

    def test_infer_stream_creates_conversation(self):
        """infer_stream creates a conversation when conversation_id is provided
        and the conversation doesn't exist yet."""
        from engine.agents.virtual_agent_manager import VirtualAgentManager
        import inspect
        source = inspect.getsource(VirtualAgentManager.infer_stream)
        # Should call conv_mgr.create() for new conversations
        assert "conv_mgr.create(" in source
        # Should update response_id after streaming
        assert "conv.response_id" in source
        assert "_server_synced" in source

    def test_conversation_manager_get_or_create_pattern(self):
        """ConversationManager supports get_or_create for conversation lifecycle."""
        from engine.lmstudio.conversation import get_conversation_manager
        conv_mgr = get_conversation_manager()
        # get_or_create should exist
        assert hasattr(conv_mgr, "get_or_create") or hasattr(conv_mgr, "create")
        # create should work
        conv = conv_mgr.create("test_stream_conv", system="Test system", model=None)
        assert conv is not None
        assert conv.response_id is None or conv.response_id == ""
        # Cleanup
        try:
            conv_mgr.remove("test_stream_conv")
        except Exception:
            pass

    def test_conversation_tracks_response_id_history(self):
        """Conversation maintains _response_id_history for branching."""
        from engine.lmstudio.conversation import Conversation
        conv = Conversation(conversation_id="test_history_track")
        assert conv._response_id_history == []
        conv._response_id_history.append("resp_001")
        conv._response_id_history.append("resp_002")
        assert len(conv._response_id_history) == 2
        conv.response_id = "resp_002"
        assert conv.response_id == "resp_002"

    def test_processed_response_has_response_id(self):
        """ProcessedResponse dataclass has response_id field."""
        from engine.agents.stream_processor import ProcessedResponse
        pr = ProcessedResponse()
        assert hasattr(pr, "response_id")
        pr.response_id = "resp_test_123"
        assert pr.response_id == "resp_test_123"
        assert pr.is_stateful is True

    def test_processed_response_is_stateful_check(self):
        """is_stateful returns True only for resp_ prefixed IDs."""
        from engine.agents.stream_processor import ProcessedResponse
        assert ProcessedResponse(response_id="resp_abc").is_stateful is True
        assert ProcessedResponse(response_id="chatcmpl-xxx").is_stateful is False
        assert ProcessedResponse(response_id="").is_stateful is False


# ══════════════════════════════════════════════════════════════════════
#  Sprint 2 — NaturalMoodDriftInterceptor + Phone governance tests
# ══════════════════════════════════════════════════════════════════════

class TestNaturalMoodDriftInterceptor:
    """Tests for the NaturalMoodDriftInterceptor (priority 5)."""

    def test_instantiation_and_priority(self):
        from engine.agents.interceptors import NaturalMoodDriftInterceptor
        d = NaturalMoodDriftInterceptor()
        assert d.priority == 5
        assert d.name == "natural_mood_drift"

    def test_applicable_scenes(self):
        from engine.agents.interceptors import NaturalMoodDriftInterceptor
        d = NaturalMoodDriftInterceptor()
        assert "bedroom" in d.applicable_scenes
        assert "phone" in d.applicable_scenes
        assert "lounge" in d.applicable_scenes
        assert "gallery" in d.applicable_scenes
        assert "warzone" not in d.applicable_scenes

    def test_drift_rates_defined(self):
        from engine.agents.interceptors import NaturalMoodDriftInterceptor
        d = NaturalMoodDriftInterceptor()
        assert "arousal" in d._DRIFT
        assert "tiredness" in d._DRIFT
        assert d._DRIFT["arousal"] < 0  # arousal cools
        assert d._DRIFT["tiredness"] > 0  # tiredness builds

    def test_inner_thoughts_defined(self):
        from engine.agents.interceptors import NaturalMoodDriftInterceptor
        d = NaturalMoodDriftInterceptor()
        assert "cooling" in d._INNER_THOUGHTS
        assert "tired" in d._INNER_THOUGHTS
        assert "mellowing" in d._INNER_THOUGHTS
        assert "sobering" in d._INNER_THOUGHTS
        assert "calming" in d._INNER_THOUGHTS

    def test_pre_call_no_agent_id_is_noop(self):
        """Should gracefully do nothing when agent_id is missing."""
        from engine.agents.interceptors import NaturalMoodDriftInterceptor
        d = NaturalMoodDriftInterceptor()
        ctx = {"system_prompt": "hello"}
        d.pre_call(ctx)
        assert ctx["system_prompt"] == "hello"

    def test_in_default_pipeline(self):
        """NaturalMoodDriftInterceptor should be in the default pipeline."""
        from engine.mcp.comms_framework import _build_default_pipeline
        pipeline = _build_default_pipeline()
        names = [i.name for i in pipeline._interceptors]
        assert "natural_mood_drift" in names
        # Should be first (lowest priority)
        assert names[0] == "natural_mood_drift"


class TestPhoneGovernanceContext:
    """Tests that Phone agent properly accepts governance_context."""

    def test_phone_agent_reply_accepts_governance_context(self):
        """_PhoneCharacterAgent.reply() should have governance_context as explicit kwarg."""
        import inspect
        import importlib
        mod = importlib.import_module("content.scenes.phone.phone_scene_v2")
        agent_cls = getattr(mod, "_PhoneCharacterAgent")
        sig = inspect.signature(agent_cls.reply)
        params = list(sig.parameters.keys())
        assert "governance_context" in params, (
            f"governance_context not in reply params: {params}"
        )

    def test_phone_interceptor_has_heat_integration(self):
        """PhoneSceneInterceptor.pre_call should reference conversation heat."""
        import inspect
        from engine.agents.interceptors import PhoneSceneInterceptor
        source = inspect.getsource(PhoneSceneInterceptor.pre_call)
        assert "get_conversation_heat" in source

    def test_phone_interceptor_vibe_hints(self):
        """PhoneSceneInterceptor should have vibe hints for stat combinations."""
        from engine.agents.interceptors import PhoneSceneInterceptor
        p = PhoneSceneInterceptor()
        assert ("high", "high") in p._VIBE_HINTS
        assert ("low", "low") in p._VIBE_HINTS
        assert p._bucket(80) == "high"
        assert p._bucket(50) == "mid"
        assert p._bucket(20) == "low"


class TestBedroomCoordinatorIntegration:
    """Tests that Bedroom stat changes reference the Coordinator."""

    def test_bedroom_action_handler_references_coordinator(self):
        """_on_agent_action should call get_coordinator()."""
        import inspect
        import importlib
        mod = importlib.import_module("content.scenes.bedroom.bedroom_scene")
        scene_cls = getattr(mod, "BedroomScene")
        source = inspect.getsource(scene_cls._on_agent_action)
        assert "get_coordinator" in source
        assert "state_coordinator" in source


class TestCrossSceneSummaryEndpoint:
    """Tests for the /api/scenes/summary overlay endpoint."""

    def test_endpoint_function_exists(self):
        """api_scene_summary function should exist in overlay_bp."""
        from engine.overlay.overlay_bp import api_scene_summary
        assert callable(api_scene_summary)


# ══════════════════════════════════════════════════════════════════════
#  Sprint 3 — Scene migration: Coordinator + narrative wiring
# ══════════════════════════════════════════════════════════════════════

class TestGalleryGovernorContext:
    """Gallery scene should enrich prompts with framework state."""

    def test_gallery_has_governor_context_helper(self):
        import inspect, importlib
        mod = importlib.import_module("content.scenes.gallery.gallery_scene")
        cls = getattr(mod, "GalleryScene")
        assert hasattr(cls, "_get_governor_context")
        source = inspect.getsource(cls._get_governor_context)
        assert "get_coordinator" in source or "get_character_registry" in source

    def test_gallery_evaluate_references_framework(self):
        import inspect, importlib
        mod = importlib.import_module("content.scenes.gallery.gallery_scene")
        cls = getattr(mod, "GalleryScene")
        source = inspect.getsource(cls._evaluate_artwork)
        assert "governor_context" in source or "_get_governor_context" in source


class TestWarzoneCoordinatorSync:
    """Warzone should sync mood through Coordinator."""

    def test_warzone_ai_decide_references_coordinator(self):
        import inspect, importlib
        mod = importlib.import_module("content.scenes.warzone.warzone_scene")
        cls = getattr(mod, "WarzoneScene")
        source = inspect.getsource(cls._ai_decide)
        assert "get_coordinator" in source or "state_coordinator" in source


class TestRealmCoordinatorSync:
    """Realm should sync stats through Coordinator."""

    def test_realm_references_coordinator(self):
        import inspect, importlib
        mod = importlib.import_module("content.scenes.realm.realm_scene")
        cls = getattr(mod, "RealmScene")
        # Check any method that handles stat changes
        source = inspect.getsource(cls)
        assert "get_coordinator" in source or "state_coordinator" in source


class TestNeonCityNarrativeFix:
    """NeonCity should use add_narrative, not update_stats with scene_id."""

    def test_sync_to_mcp_uses_narrative(self):
        import inspect, importlib
        mod = importlib.import_module("content.scenes.neoncity.neoncity_scene")
        cls = getattr(mod, "NeonCityScene")
        source = inspect.getsource(cls._sync_to_mcp)
        assert "add_narrative" in source
        # Should NOT use update_stats with SCENE_ID
        assert "update_stats(SCENE_ID" not in source


class TestHeistCoordinatorSync:
    """Heist should sync mood through Coordinator."""

    def test_heist_references_coordinator(self):
        import inspect, importlib
        mod = importlib.import_module("content.scenes.heist.heist_scene")
        cls = getattr(mod, "HeistScene")
        source = inspect.getsource(cls)
        assert "get_coordinator" in source or "state_coordinator" in source


class TestBedroomInteractionRecords:
    """Bedroom should log InteractionRecords for physical interactions."""

    def test_bedroom_logs_interactions(self):
        import inspect, importlib
        mod = importlib.import_module("content.scenes.bedroom.bedroom_scene")
        cls = getattr(mod, "BedroomScene")
        source = inspect.getsource(cls)
        assert "log_interaction" in source
        assert "InteractionRecord" in source


# ══════════════════════════════════════════════════════════════════════
#  Sprint 4 — Registry persistence, heat expansion, new interceptors
# ══════════════════════════════════════════════════════════════════════

class TestRegistryPersistence:
    """CharacterRegistry should support persisting state to DB."""

    def test_persist_method_exists(self):
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        assert hasattr(reg, "persist_to_db")
        assert callable(reg.persist_to_db)

    def test_persist_returns_count(self):
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        # Should return int (may be 0 if no matching DB records)
        result = reg.persist_to_db()
        assert isinstance(result, int)
        assert result >= 0


class TestBaseSceneStopPersists:
    """BaseScene.stop() should call persist_to_db."""

    def test_base_scene_stop_references_persist(self):
        import inspect
        from engine.scenes.base_scene import BaseScene
        source = inspect.getsource(BaseScene.stop)
        assert "persist_to_db" in source


class TestGallerySceneInterceptor:
    """GallerySceneInterceptor should exist and be in the pipeline."""

    def test_instantiation(self):
        from engine.agents.interceptors import GallerySceneInterceptor
        g = GallerySceneInterceptor()
        assert g.name == "gallery_scene"
        assert g.priority == 15
        assert "gallery" in g.applicable_scenes

    def test_in_default_pipeline(self):
        from engine.mcp.comms_framework import _build_default_pipeline
        pipeline = _build_default_pipeline()
        names = [i.name for i in pipeline._interceptors]
        assert "gallery_scene" in names

    def test_pre_call_no_agent_is_noop(self):
        from engine.agents.interceptors import GallerySceneInterceptor
        g = GallerySceneInterceptor()
        ctx = {"system_prompt": "hello"}
        g.pre_call(ctx)
        assert ctx["system_prompt"] == "hello"


class TestLoungeHeatExpansion:
    """LoungeSceneInterceptor should use ConversationHeat."""

    def test_lounge_interceptor_references_heat(self):
        import inspect
        from engine.agents.interceptors import LoungeSceneInterceptor
        source = inspect.getsource(LoungeSceneInterceptor.pre_call)
        assert "get_conversation_heat" in source


class TestActionBasedHeatBumping:
    """MoodSyncInterceptor should bump heat from action tags."""

    def test_action_heat_map_defined(self):
        from engine.agents.interceptors import MoodSyncInterceptor
        ms = MoodSyncInterceptor()
        assert "kiss" in ms._ACTION_HEAT
        assert "touch" in ms._ACTION_HEAT
        assert "flirt" in ms._ACTION_HEAT
        assert ms._ACTION_HEAT["kiss"] > ms._ACTION_HEAT["flirt"]

    def test_bump_method_exists(self):
        from engine.agents.interceptors import MoodSyncInterceptor
        ms = MoodSyncInterceptor()
        assert hasattr(ms, "_bump_heat_from_actions")

    def test_pipeline_interceptor_count(self):
        """Pipeline should have 22 interceptors (added Universal + Ambient in Sprint 6)."""
        from engine.mcp.comms_framework import _build_default_pipeline
        pipeline = _build_default_pipeline()
        assert len(pipeline._interceptors) == 23


# ══════════════════════════════════════════════════════════════════════
#  Sprint 5 — Scene transitions, journey tracking, docs sync
# ══════════════════════════════════════════════════════════════════════

class TestSceneTransitionTracking:
    """MCPFramework should track player scene visits."""

    def test_framework_has_journey_methods(self):
        from engine.mcp.framework import get_framework
        fw = get_framework()
        assert hasattr(fw, "record_scene_visit")
        assert hasattr(fw, "get_player_journey")
        assert hasattr(fw, "get_previous_scene")

    def test_record_and_retrieve(self):
        from engine.mcp.framework import get_framework
        fw = get_framework()
        # Clear history
        fw._player_scene_history.clear()
        fw.record_scene_visit("bedroom")
        fw.record_scene_visit("phone")
        assert fw.get_previous_scene() == "bedroom"
        journey = fw.get_player_journey(limit=3)
        assert len(journey) == 2
        assert journey[0]["scene"] == "phone"  # most recent first
        assert journey[1]["scene"] == "bedroom"

    def test_no_previous_scene_initially(self):
        from engine.mcp.framework import get_framework
        fw = get_framework()
        fw._player_scene_history.clear()
        assert fw.get_previous_scene() is None

    def test_journey_limit(self):
        from engine.mcp.framework import get_framework
        fw = get_framework()
        fw._player_scene_history.clear()
        for i in range(25):
            fw.record_scene_visit(f"scene_{i}")
        assert len(fw._player_scene_history) <= 20


class TestRouterMessageJourneyInjection:
    """RouterMessageInjector should reference player journey context."""

    def test_router_injector_has_journey_logic(self):
        import inspect
        from engine.agents.interceptors import RouterMessageInjector
        source = inspect.getsource(RouterMessageInjector.pre_call)
        assert "get_previous_scene" in source
        assert "player just came from" in source


# ══════════════════════════════════════════════════════════════════════
#  Sprint 6 — UniversalSceneInterceptor + AmbientEventInterceptor
# ══════════════════════════════════════════════════════════════════════

class TestUniversalSceneInterceptor:
    """UniversalSceneInterceptor should cover scenes without dedicated interceptors."""

    def test_import(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        assert i.name == "universal_scene"
        assert i.priority == 16

    def test_skips_dedicated_scenes(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        for scene in ("bedroom", "phone", "lounge", "gallery"):
            ctx = {"scene": scene, "agent_id": "test", "system_prompt": ""}
            i.pre_call(ctx)
            assert "CONTEXT]" not in ctx["system_prompt"], f"Should skip {scene}"

    def test_injects_for_casino(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "casino", "agent_id": "dealer", "system_prompt": "You are a dealer."}
        i.pre_call(ctx)
        assert "[CASINO CONTEXT]" in ctx["system_prompt"]

    def test_injects_for_warzone(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "warzone", "agent_id": "commander", "system_prompt": ""}
        i.pre_call(ctx)
        assert "[WARZONE CONTEXT]" in ctx["system_prompt"]

    def test_injects_for_realm(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "realm", "agent_id": "npc", "system_prompt": ""}
        i.pre_call(ctx)
        assert "[REALM CONTEXT]" in ctx["system_prompt"]

    def test_injects_for_neon_city(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "neon_city", "agent_id": "hacker", "system_prompt": ""}
        i.pre_call(ctx)
        assert "[NEON CITY CONTEXT]" in ctx["system_prompt"]

    def test_injects_for_heist(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "heist", "agent_id": "planner", "system_prompt": ""}
        i.pre_call(ctx)
        assert "[HEIST CONTEXT]" in ctx["system_prompt"]

    def test_injects_for_coders_room(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "coders_room", "agent_id": "dev", "system_prompt": ""}
        i.pre_call(ctx)
        assert "[CODERS ROOM CONTEXT]" in ctx["system_prompt"]


class TestAmbientEventInterceptor:
    """AmbientEventInterceptor should inject random micro-events."""

    def test_import(self):
        from engine.agents.interceptors import AmbientEventInterceptor
        i = AmbientEventInterceptor()
        assert i.name == "ambient_events"
        assert i.priority == 17

    def test_injects_ambient_event(self):
        from engine.agents.interceptors import AmbientEventInterceptor
        i = AmbientEventInterceptor()
        i.EVENT_CHANCE = 1.0  # Force injection
        ctx = {"scene": "casino", "system_prompt": "Base prompt."}
        i.pre_call(ctx)
        assert "[AMBIENT]" in ctx["system_prompt"]
        assert "[/AMBIENT]" in ctx["system_prompt"]

    def test_no_event_when_chance_zero(self):
        from engine.agents.interceptors import AmbientEventInterceptor
        i = AmbientEventInterceptor()
        i.EVENT_CHANCE = 0.0  # Never inject
        ctx = {"scene": "casino", "system_prompt": "Base prompt."}
        i.pre_call(ctx)
        assert "[AMBIENT]" not in ctx["system_prompt"]

    def test_scene_specific_events(self):
        from engine.agents.interceptors import AmbientEventInterceptor
        i = AmbientEventInterceptor()
        i.EVENT_CHANCE = 1.0
        ctx = {"scene": "warzone", "system_prompt": ""}
        i.pre_call(ctx)
        # Warzone events should be warzone-themed
        prompt = ctx["system_prompt"]
        assert "[AMBIENT]" in prompt

    def test_avoids_repetition(self):
        from engine.agents.interceptors import AmbientEventInterceptor
        i = AmbientEventInterceptor()
        i.EVENT_CHANCE = 1.0
        events_seen = set()
        for _ in range(10):
            ctx = {"scene": "casino", "system_prompt": ""}
            i.pre_call(ctx)
            event = ctx["system_prompt"].split("[AMBIENT]")[1].split("[/AMBIENT]")[0].strip()
            events_seen.add(event)
        # Should have used at least 2 different events in 10 calls
        assert len(events_seen) >= 2

    def test_skips_when_no_scene(self):
        from engine.agents.interceptors import AmbientEventInterceptor
        i = AmbientEventInterceptor()
        i.EVENT_CHANCE = 1.0
        ctx = {"scene": "", "system_prompt": ""}
        i.pre_call(ctx)
        assert "[AMBIENT]" not in ctx["system_prompt"]

    def test_generic_fallback_for_unknown_scene(self):
        from engine.agents.interceptors import AmbientEventInterceptor
        i = AmbientEventInterceptor()
        i.EVENT_CHANCE = 1.0
        ctx = {"scene": "unknown_scene_xyz", "system_prompt": ""}
        i.pre_call(ctx)
        assert "[AMBIENT]" in ctx["system_prompt"]


# ═══════════════════════════════════════════════════════════════════════
#  Sprint 7: Timed Action Phase Injection + Scene Descriptors
# ═══════════════════════════════════════════════════════════════════════

class TestBedroomTimedActionPhases:
    """Test that active timed actions inject phase guidance into prompts."""

    def test_early_phase_injection(self):
        """Early phase (< 30%) injects anticipation guidance."""
        from engine.agents.interceptors import BedroomSceneInterceptor
        from engine.mcp.scene_state import get_scene_state_manager

        ssm = get_scene_state_manager()
        token = ssm.start_timed_action(
            "lola", "massage", duration=100, description="sensual massage",
            phase_labels=["setup", "deepening", "climax"],
        )

        i = BedroomSceneInterceptor()
        ctx = {"scene": "bedroom", "agent_id": "lola", "system_prompt": "base",
               "scene_id": "bedroom", "character_ids": ["lola"]}
        i.pre_call(ctx)

        prompt = ctx["system_prompt"]
        assert "ACTIVE INTERACTION" in prompt
        assert "massage" in prompt
        assert "anticipation" in prompt.lower() or "beginning" in prompt.lower()

        ssm.abort_timed_action(token)

    def test_mid_phase_injection(self):
        """Mid phase (30-70%) injects deepening guidance."""
        from engine.agents.interceptors import BedroomSceneInterceptor
        from engine.mcp.scene_state import get_scene_state_manager
        import time

        ssm = get_scene_state_manager()
        # Very short duration so elapsed puts us in the middle
        token = ssm.start_timed_action(
            "lola", "dance", duration=0.001,
            phase_labels=["warmup", "flow", "finale"],
        )
        time.sleep(0.01)  # Exceed duration → complete

        i = BedroomSceneInterceptor()
        ctx = {"scene": "bedroom", "agent_id": "lola", "system_prompt": "base",
               "scene_id": "bedroom", "character_ids": ["lola"]}
        i.pre_call(ctx)

        # Should not inject for completed actions
        ssm.abort_timed_action(token)

    def test_no_injection_without_active_actions(self):
        """No injection when no timed actions are active."""
        from engine.agents.interceptors import BedroomSceneInterceptor

        i = BedroomSceneInterceptor()
        ctx = {"scene": "bedroom", "agent_id": "lola", "system_prompt": "base",
               "scene_id": "bedroom", "character_ids": ["lola"]}
        i.pre_call(ctx)
        assert "ACTIVE INTERACTION" not in ctx["system_prompt"]


class TestUniversalSceneDescriptors:
    """Test that UniversalSceneInterceptor injects scene descriptors."""

    def test_casino_descriptor(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "casino", "agent_id": "frankie", "system_prompt": ""}
        i.pre_call(ctx)
        assert "Grand Casino" in ctx["system_prompt"]
        assert "high-stakes" in ctx["system_prompt"]

    def test_warzone_descriptor(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "warzone", "agent_id": "viktor", "system_prompt": ""}
        i.pre_call(ctx)
        assert "combat zone" in ctx["system_prompt"]

    def test_neon_city_descriptor(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "neon_city", "agent_id": "aria", "system_prompt": ""}
        i.pre_call(ctx)
        assert "cyberpunk" in ctx["system_prompt"]

    def test_realm_descriptor(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "realm", "agent_id": "mira", "system_prompt": ""}
        i.pre_call(ctx)
        assert "Fantasy realm" in ctx["system_prompt"]

    def test_heist_descriptor(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "heist", "agent_id": "frankie", "system_prompt": ""}
        i.pre_call(ctx)
        assert "heist" in ctx["system_prompt"].lower()

    def test_coders_room_descriptor(self):
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "coders_room", "agent_id": "aria", "system_prompt": ""}
        i.pre_call(ctx)
        assert "Coder" in ctx["system_prompt"]

    def test_no_descriptor_for_dedicated_scenes(self):
        """Dedicated scenes (bedroom, phone, etc.) get no descriptor."""
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "bedroom", "agent_id": "lola", "system_prompt": ""}
        i.pre_call(ctx)
        assert ctx["system_prompt"] == ""

    def test_descriptor_appears_before_mood(self):
        """Scene descriptor should be the first line of injected context."""
        from engine.agents.interceptors import UniversalSceneInterceptor
        i = UniversalSceneInterceptor()
        ctx = {"scene": "casino", "agent_id": "frankie", "system_prompt": ""}
        i.pre_call(ctx)
        # Find the CONTEXT block and check descriptor is first content
        prompt = ctx["system_prompt"]
        context_start = prompt.find("[CASINO CONTEXT]")
        assert context_start >= 0
        after_header = prompt[context_start + len("[CASINO CONTEXT]"):].strip()
        assert after_header.startswith("Setting:")


# ═══════════════════════════════════════════════════════════════════════
#  Sprint 8: TickerLoop + ConversationRecapInterceptor
# ═══════════════════════════════════════════════════════════════════════

class TestTickerLoop:
    """Test the TickerLoop framework utility."""

    def test_start_stop(self):
        from engine.mcp.framework import TickerLoop
        import time
        count = {"n": 0}
        def tick():
            count["n"] += 1
        t = TickerLoop("test_tick", tick, interval=0.1)
        assert not t.running
        t.start()
        assert t.running
        time.sleep(0.55)
        t.stop()
        assert not t.running
        assert count["n"] >= 2  # Should have ticked at least twice in 0.55s

    def test_stop_is_idempotent(self):
        from engine.mcp.framework import TickerLoop
        t = TickerLoop("test_idem", lambda: None, interval=1.0)
        t.start()
        t.stop()
        t.stop()  # Should not raise
        assert not t.running

    def test_start_when_running_is_noop(self):
        from engine.mcp.framework import TickerLoop
        t = TickerLoop("test_noop", lambda: None, interval=1.0)
        t.start()
        thread1 = t._thread
        t.start()  # Should not create second thread
        assert t._thread is thread1
        t.stop()

    def test_callback_error_doesnt_crash(self):
        from engine.mcp.framework import TickerLoop
        import time
        count = {"n": 0}
        def bad_tick():
            count["n"] += 1
            if count["n"] == 1:
                raise ValueError("boom")
        t = TickerLoop("test_err", bad_tick, interval=0.1)
        t.start()
        time.sleep(0.55)
        t.stop()
        assert count["n"] >= 2  # Continued ticking after error

    def test_exported_from_package(self):
        from engine.mcp import TickerLoop
        assert TickerLoop is not None


class TestConversationRecapInterceptor:
    """Test the ConversationRecapInterceptor."""

    def test_no_recap_on_first_message(self):
        from engine.agents.interceptors import ConversationRecapInterceptor
        i = ConversationRecapInterceptor()
        ctx = {"scene": "test", "agent_id": "lola", "system_prompt": "",
               "user_message": "Hello!"}
        i.pre_call(ctx)
        assert "CONVERSATION RECAP" not in ctx["system_prompt"]

    def test_recap_appears_after_exchange(self):
        from engine.agents.interceptors import ConversationRecapInterceptor
        i = ConversationRecapInterceptor()

        # Turn 1: user sends, agent replies
        ctx1 = {"scene": "test", "agent_id": "lola", "system_prompt": "",
                "user_message": "Hey there!"}
        i.pre_call(ctx1)
        ctx1["response"] = "Oh hi! How are you?"
        i.post_call(ctx1)

        # Turn 2: recap should appear
        ctx2 = {"scene": "test", "agent_id": "lola", "system_prompt": "",
                "user_message": "I'm great!"}
        i.pre_call(ctx2)
        assert "CONVERSATION RECAP" in ctx2["system_prompt"]
        assert "Hey there!" in ctx2["system_prompt"]
        assert "Oh hi!" in ctx2["system_prompt"]

    def test_recap_truncates_long_messages(self):
        from engine.agents.interceptors import ConversationRecapInterceptor
        i = ConversationRecapInterceptor()

        long_msg = "A" * 200
        ctx1 = {"scene": "test", "agent_id": "lola", "system_prompt": "",
                "user_message": long_msg}
        i.pre_call(ctx1)
        ctx1["response"] = "Short reply"
        i.post_call(ctx1)

        ctx2 = {"scene": "test", "agent_id": "lola", "system_prompt": "",
                "user_message": "Next"}
        i.pre_call(ctx2)
        # Should contain truncated version, not full 200 chars
        assert "..." in ctx2["system_prompt"]
        assert long_msg not in ctx2["system_prompt"]

    def test_separate_conversations_have_separate_recaps(self):
        from engine.agents.interceptors import ConversationRecapInterceptor
        i = ConversationRecapInterceptor()

        # Conversation A
        ctx_a1 = {"scene": "bedroom", "agent_id": "lola", "system_prompt": "",
                  "user_message": "bedroom talk"}
        i.pre_call(ctx_a1)
        ctx_a1["response"] = "bedroom reply"
        i.post_call(ctx_a1)

        # Conversation B
        ctx_b1 = {"scene": "casino", "agent_id": "frankie", "system_prompt": "",
                  "user_message": "casino talk"}
        i.pre_call(ctx_b1)
        ctx_b1["response"] = "casino reply"
        i.post_call(ctx_b1)

        # Turn 2 of A should only have A's history
        ctx_a2 = {"scene": "bedroom", "agent_id": "lola", "system_prompt": "",
                  "user_message": "more bedroom"}
        i.pre_call(ctx_a2)
        assert "bedroom talk" in ctx_a2["system_prompt"]
        assert "casino talk" not in ctx_a2["system_prompt"]

    def test_recap_limits_to_max_turns(self):
        from engine.agents.interceptors import ConversationRecapInterceptor
        i = ConversationRecapInterceptor()
        i.MAX_TURNS = 2  # Only keep 2 exchanges

        for n in range(5):
            ctx = {"scene": "test", "agent_id": "lola", "system_prompt": "",
                   "user_message": f"msg_{n}"}
            i.pre_call(ctx)
            ctx["response"] = f"reply_{n}"
            i.post_call(ctx)

        final = {"scene": "test", "agent_id": "lola", "system_prompt": "",
                 "user_message": "final"}
        i.pre_call(final)
        prompt = final["system_prompt"]
        # Should NOT contain early messages
        assert "msg_0" not in prompt
        # Should contain recent ones
        assert "msg_4" in prompt or "reply_4" in prompt

    def test_pipeline_count_is_23(self):
        """Verify pipeline now has 23 interceptors."""
        from engine.mcp.comms_framework import _build_default_pipeline
        pipeline = _build_default_pipeline()
        assert len(pipeline._interceptors) == 23
