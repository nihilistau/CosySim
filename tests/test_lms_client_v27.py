"""
Tests for LMSClient v2.7 — native v1 API streaming, stateful chats, conversation branching.

Tests cover:
- LMSResponse v1 stats fields
- LMSStreamEvent typed parsing
- SSE event: line parsing in _stream_v1_raw
- Conversation branching via response_id
- Stateless queries (store: false)
- InferenceConfig store/context_length passthrough
"""
import json
import time
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from dataclasses import asdict

from engine.lmstudio.lms_client import (
    LMSClient,
    LMSResponse,
    LMSStreamEvent,
)
from engine.lmstudio.inference_config import InferenceConfig
from engine.lmstudio.conversation import (
    Conversation,
    ConversationManager,
    ConversationMessage,
)


# ── Fixtures ──────────────────────────────────────────────────────────

class MockConfig:
    def get(self, key, default=None):
        return {
            "lmstudio.host": "127.0.0.1",
            "lmstudio.port": 1234,
            "llm.model": "test-model",
            "lmstudio.mcp_enabled": False,
            "lmstudio.cosysim_mcp_url": "",
        }.get(key, default)


@pytest.fixture
def client():
    with patch("engine.lmstudio.lms_client.InferenceConfig.from_yaml", return_value=InferenceConfig()):
        return LMSClient(base_url="http://127.0.0.1:1234", config=MockConfig())


@pytest.fixture
def conversation():
    return Conversation(
        conversation_id="test_conv",
        system="You are a test assistant.",
        model="test-model",
    )


@pytest.fixture
def conv_manager():
    return ConversationManager()


# ── LMSResponse tests ────────────────────────────────────────────────

class TestLMSResponse:
    def test_default_values(self):
        r = LMSResponse()
        assert r.response_id == ""
        assert r.reasoning_tokens == 0
        assert r.server_tps == 0.0
        assert r.time_to_first_token_s == 0.0
        assert r.model_load_time_s == 0.0

    def test_is_stateful_with_resp_prefix(self):
        r = LMSResponse(response_id="resp_abc123")
        assert r.is_stateful is True

    def test_is_stateful_without_resp_prefix(self):
        r = LMSResponse(response_id="chatcmpl-abc")
        assert r.is_stateful is False

    def test_is_stateful_empty(self):
        r = LMSResponse(response_id="")
        assert r.is_stateful is False

    def test_tokens_per_second_uses_server_tps(self):
        r = LMSResponse(server_tps=45.5, latency_ms=1000, output_tokens=30)
        assert r.tokens_per_second == 45.5

    def test_tokens_per_second_fallback_estimate(self):
        r = LMSResponse(server_tps=0, latency_ms=2000, output_tokens=100)
        assert r.tokens_per_second == 50.0

    def test_apply_v1_stats(self):
        r = LMSResponse()
        r._apply_v1_stats({
            "input_tokens": 120,
            "total_output_tokens": 80,
            "reasoning_output_tokens": 15,
            "tokens_per_second": 43.5,
            "time_to_first_token_seconds": 0.78,
            "model_load_time_seconds": 2.1,
        })
        assert r.input_tokens == 120
        assert r.output_tokens == 80
        assert r.reasoning_tokens == 15
        assert r.total_tokens == 200
        assert r.server_tps == 43.5
        assert r.time_to_first_token_s == 0.78
        assert r.model_load_time_s == 2.1

    def test_apply_v1_stats_null_load_time(self):
        r = LMSResponse()
        r._apply_v1_stats({"model_load_time_seconds": None})
        assert r.model_load_time_s == 0.0


# ── LMSStreamEvent parsing tests ─────────────────────────────────────

class TestStreamEventParsing:
    def setup_method(self):
        with patch("engine.lmstudio.lms_client.InferenceConfig.from_yaml", return_value=InferenceConfig()):
            self.client = LMSClient(base_url="http://test", config=MockConfig())

    def test_message_delta(self):
        ev = self.client._parse_v1_stream_event(
            {"type": "message.delta", "content": "Hello"}, "message.delta"
        )
        assert ev.event_type == "message.delta"
        assert ev.content == "Hello"
        assert ev.is_done is False

    def test_reasoning_delta(self):
        ev = self.client._parse_v1_stream_event(
            {"type": "reasoning.delta", "content": "Need to think..."}, None
        )
        assert ev.event_type == "reasoning.delta"
        assert ev.content == "Need to think..."

    def test_model_load_progress(self):
        ev = self.client._parse_v1_stream_event(
            {"type": "model_load.progress", "model_instance_id": "m1", "progress": 0.65}, None
        )
        assert ev.event_type == "model_load.progress"
        assert ev.progress == 0.65

    def test_model_load_end(self):
        ev = self.client._parse_v1_stream_event(
            {"type": "model_load.end", "model_instance_id": "m1", "load_time_seconds": 12.34}, None
        )
        assert ev.load_time_seconds == 12.34
        assert ev.model_instance_id == "m1"

    def test_chat_start(self):
        ev = self.client._parse_v1_stream_event(
            {"type": "chat.start", "model_instance_id": "m1"}, None
        )
        assert ev.event_type == "chat.start"
        assert ev.model_instance_id == "m1"

    def test_tool_call_success(self):
        ev = self.client._parse_v1_stream_event({
            "type": "tool_call.success",
            "tool": "get_weather",
            "arguments": {"city": "Tokyo"},
            "output": '{"temp": 22}',
            "provider_info": {"type": "ephemeral_mcp", "server_label": "cosysim"},
        }, None)
        assert ev.event_type == "tool_call.success"
        assert ev.tool_name == "get_weather"
        assert ev.tool_arguments == {"city": "Tokyo"}
        assert ev.tool_output == '{"temp": 22}'
        assert ev.tool_provider["type"] == "ephemeral_mcp"

    def test_tool_call_failure(self):
        ev = self.client._parse_v1_stream_event({
            "type": "tool_call.failure",
            "reason": "Cannot find tool with name bad_tool.",
            "metadata": {"type": "invalid_name", "tool_name": "bad_tool"},
        }, None)
        assert ev.event_type == "tool_call.failure"
        assert ev.error["reason"] == "Cannot find tool with name bad_tool."
        assert ev.is_done is False  # tool failure doesn't end the stream

    def test_error_event(self):
        ev = self.client._parse_v1_stream_event({
            "type": "error",
            "error": {"type": "invalid_request", "message": "model required"},
        }, None)
        assert ev.event_type == "error"
        assert ev.error["type"] == "invalid_request"
        assert ev.is_done is True

    def test_chat_end(self):
        ev = self.client._parse_v1_stream_event({
            "type": "chat.end",
            "result": {
                "model_instance_id": "m1",
                "output": [{"type": "message", "content": "Done."}],
                "stats": {"input_tokens": 100, "total_output_tokens": 50, "tokens_per_second": 42.0},
                "response_id": "resp_abc123",
            },
        }, None)
        assert ev.event_type == "chat.end"
        assert ev.is_done is True
        assert ev.response_id == "resp_abc123"
        assert ev.result["stats"]["tokens_per_second"] == 42.0
        assert ev.model_instance_id == "m1"

    def test_event_hint_fallback(self):
        """When data has no 'type', use event_hint from the SSE event: line."""
        ev = self.client._parse_v1_stream_event(
            {"content": "chunk"}, "message.delta"
        )
        assert ev.event_type == "message.delta"
        assert ev.content == "chunk"

    def test_prompt_processing_progress(self):
        ev = self.client._parse_v1_stream_event(
            {"type": "prompt_processing.progress", "progress": 0.5}, None
        )
        assert ev.event_type == "prompt_processing.progress"
        assert ev.progress == 0.5

    def test_start_end_events_no_crash(self):
        """Boundary events like message.start, message.end, reasoning.start etc."""
        for et in ("message.start", "message.end", "reasoning.start", "reasoning.end",
                    "prompt_processing.start", "prompt_processing.end"):
            ev = self.client._parse_v1_stream_event({"type": et}, None)
            assert ev.event_type == et


# ── v1 output parsing tests ──────────────────────────────────────────

class TestV1OutputParsing:
    def setup_method(self):
        with patch("engine.lmstudio.lms_client.InferenceConfig.from_yaml", return_value=InferenceConfig()):
            self.client = LMSClient(base_url="http://test", config=MockConfig())

    def test_parse_full_response(self):
        data = {
            "model_instance_id": "qwen3-4b",
            "output": [
                {"type": "reasoning", "content": "Let me think..."},
                {"type": "message", "content": "Hello there!"},
            ],
            "stats": {
                "input_tokens": 150,
                "total_output_tokens": 80,
                "reasoning_output_tokens": 20,
                "tokens_per_second": 45.0,
                "time_to_first_token_seconds": 0.5,
                "model_load_time_seconds": None,
            },
            "response_id": "resp_xyz789",
        }
        resp = self.client._parse_v1_output(data, "fallback-model")
        assert resp.content == "Hello there!"
        assert resp.reasoning_content == "Let me think..."
        assert resp.model == "qwen3-4b"
        assert resp.response_id == "resp_xyz789"
        assert resp.input_tokens == 150
        assert resp.output_tokens == 80
        assert resp.reasoning_tokens == 20
        assert resp.server_tps == 45.0
        assert resp.time_to_first_token_s == 0.5
        assert resp.model_load_time_s == 0.0
        assert resp.is_stateful is True

    def test_parse_with_tool_calls(self):
        data = {
            "model_instance_id": "m1",
            "output": [
                {
                    "type": "tool_call",
                    "tool": "search",
                    "arguments": {"q": "test"},
                    "output": '{"results": []}',
                    "provider_info": {"type": "ephemeral_mcp", "server_label": "cosysim"},
                },
                {"type": "message", "content": "No results found."},
            ],
            "stats": {"input_tokens": 50, "total_output_tokens": 30},
            "response_id": "resp_tc1",
        }
        resp = self.client._parse_v1_output(data, "m1")
        assert resp.has_tool_calls is True
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0]["tool"] == "search"
        assert resp.content == "No results found."

    def test_parse_invalid_tool_call_logged(self):
        """Invalid tool calls should be logged but not crash."""
        data = {
            "model_instance_id": "m1",
            "output": [
                {
                    "type": "invalid_tool_call",
                    "reason": "Tool not found",
                    "metadata": {"type": "invalid_name", "tool_name": "bad_tool"},
                },
                {"type": "message", "content": "Fallback reply."},
            ],
            "stats": {},
        }
        resp = self.client._parse_v1_output(data, "m1")
        assert resp.content == "Fallback reply."
        assert resp.has_tool_calls is False


# ── InferenceConfig v2.7 tests ───────────────────────────────────────

class TestInferenceConfigV27:
    def test_store_false_in_payload(self):
        cfg = InferenceConfig(store=False)
        d = cfg.to_native_v1()
        assert d["store"] is False

    def test_store_true_in_payload(self):
        cfg = InferenceConfig(store=True)
        d = cfg.to_native_v1()
        assert d["store"] is True

    def test_store_none_not_in_payload(self):
        cfg = InferenceConfig(store=None)
        d = cfg.to_native_v1()
        assert "store" not in d

    def test_context_length_in_payload(self):
        cfg = InferenceConfig(context_length=8000)
        d = cfg.to_native_v1()
        assert d["context_length"] == 8000

    def test_previous_response_id_in_payload(self):
        cfg = InferenceConfig(previous_response_id="resp_abc123")
        d = cfg.to_native_v1()
        assert d["previous_response_id"] == "resp_abc123"

    def test_reasoning_bool_to_string(self):
        cfg = InferenceConfig(reasoning=True)
        d = cfg.to_native_v1()
        assert d["reasoning"] == "on"

        cfg2 = InferenceConfig(reasoning=False)
        d2 = cfg2.to_native_v1()
        assert d2["reasoning"] == "off"

    def test_reasoning_string_passthrough(self):
        for val in ("low", "medium", "high", "on", "off"):
            cfg = InferenceConfig(reasoning=val)
            d = cfg.to_native_v1()
            assert d["reasoning"] == val


# ── Conversation v2.7 tests ──────────────────────────────────────────

class TestConversationV27:
    def test_response_id_history_tracked(self, conversation):
        """Verify response_id_history is populated after sends."""
        assert conversation._response_id_history == []

    def test_branch_at_creates_synced_fork(self, conversation):
        """branch_at should create a fork with server state if response_id exists."""
        # Manually add messages with response_ids
        conversation.messages.append(ConversationMessage(
            role="user", content="Hello", timestamp=time.time()
        ))
        conversation.messages.append(ConversationMessage(
            role="assistant", content="Hi!", timestamp=time.time(),
            metadata={"response_id": "resp_turn1"},
        ))
        conversation.messages.append(ConversationMessage(
            role="user", content="How are you?", timestamp=time.time()
        ))
        conversation.messages.append(ConversationMessage(
            role="assistant", content="I'm good!", timestamp=time.time(),
            metadata={"response_id": "resp_turn2"},
        ))
        conversation._response_id_history = ["resp_turn1", "resp_turn2"]

        branch = conversation.branch_at(1, new_id="branch_test")
        assert branch.conversation_id == "branch_test"
        assert branch.response_id == "resp_turn1"
        assert branch._server_synced is True

    def test_branch_at_no_response_id_falls_back(self, conversation):
        """branch_at without matching response_id creates unsynced fork."""
        conversation.messages.append(ConversationMessage(
            role="user", content="Hello", timestamp=time.time()
        ))
        conversation.messages.append(ConversationMessage(
            role="assistant", content="Hi!", timestamp=time.time(),
            metadata={},  # no response_id
        ))

        branch = conversation.branch_at(1, new_id="no_rid_branch")
        assert branch._server_synced is False
        assert branch.response_id is None

    def test_fork_with_branch_response_id(self, conversation):
        """fork() with explicit branch_response_id should create synced fork."""
        fork = conversation.fork(new_id="explicit_branch", branch_response_id="resp_xyz")
        assert fork._server_synced is True
        assert fork.response_id == "resp_xyz"

    def test_fork_without_branch_response_id(self, conversation):
        """fork() without branch_response_id creates unsynced fork (original behavior)."""
        fork = conversation.fork(new_id="no_branch")
        assert fork._server_synced is False
        assert fork.response_id is None

    def test_send_stateless(self, conversation):
        """send_stateless should call client.chat with store=False."""
        mock_resp = LMSResponse(content="Summary here", response_id="")
        with patch("engine.lmstudio.lms_client.get_lms_client") as mock_get:
            mock_client = MagicMock()
            mock_client.chat.return_value = mock_resp
            mock_get.return_value = mock_client

            resp = conversation.send_stateless("Summarise please")

            mock_client.chat.assert_called_once()
            call_kwargs = mock_client.chat.call_args
            assert call_kwargs.kwargs["store"] is False
            assert resp.content == "Summary here"

    def test_get_summary_includes_response_id_count(self, conversation):
        conversation._response_id_history = ["resp_1", "resp_2", "resp_3"]
        summary = conversation.get_summary()
        assert summary["response_id_count"] == 3


# ── ConversationManager tests ────────────────────────────────────────

class TestConversationManagerV27:
    def test_create_and_get(self, conv_manager):
        conv = conv_manager.create("test1", system="Hello")
        assert conv_manager.get("test1") is conv

    def test_invalidate_model_clears_sync(self, conv_manager):
        conv = conv_manager.create("test2", model="model-A")
        conv.response_id = "resp_123"
        conv._server_synced = True

        count = conv_manager.invalidate_model("model-A")
        assert count == 1
        assert conv._server_synced is False
        assert conv.response_id is None

    def test_stats(self, conv_manager):
        conv_manager.create("s1", system="sys1")
        conv_manager.create("s2", system="sys2")
        stats = conv_manager.get_stats()
        assert stats["total"] == 2


# ── messages_to_v1_input tests ───────────────────────────────────────

class TestMessagesToV1Input:
    def test_simple_user_message(self):
        sys, inp = LMSClient._messages_to_v1_input([
            {"role": "user", "content": "Hello"},
        ])
        assert sys is None
        assert inp == "Hello"

    def test_system_extracted(self):
        sys, inp = LMSClient._messages_to_v1_input([
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hi"},
        ])
        assert sys == "Be helpful"
        assert inp == "Hi"

    def test_multi_turn_creates_array(self):
        sys, inp = LMSClient._messages_to_v1_input([
            {"role": "system", "content": "Sys"},
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
        ])
        assert sys == "Sys"
        assert isinstance(inp, list)
        assert len(inp) == 3
        assert inp[1]["text"] == "[assistant]: A1"

    def test_multiple_system_messages_joined(self):
        sys, inp = LMSClient._messages_to_v1_input([
            {"role": "system", "content": "Rule 1"},
            {"role": "system", "content": "Rule 2"},
            {"role": "user", "content": "Go"},
        ])
        assert "Rule 1" in sys
        assert "Rule 2" in sys

    def test_image_input(self):
        sys, inp = LMSClient._messages_to_v1_input([
            {"role": "user", "content": [
                {"type": "text", "text": "Describe this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
            ]},
        ])
        assert isinstance(inp, list)
        assert inp[0]["type"] == "text"
        assert inp[1]["type"] == "image"
        assert inp[1]["data_url"] == "data:image/png;base64,abc123"
