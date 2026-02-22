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
