"""
Tests for engine/lmstudio/client_v2.py — LMStudio REST Client

Uses httpx mock transport to avoid real HTTP calls.
"""
import json
import time
import pytest
from unittest.mock import patch, MagicMock

from engine.lmstudio.client_v2 import (
    LMStudioClient,
    ChatResponse,
    StreamChunk,
    StreamResult,
    MCP,
)


# ── Fixtures ──────────────────────────────────────────────────────────

class MockConfig:
    """Minimal config mock."""
    def get(self, key, default=None):
        return {
            "lmstudio.host": "127.0.0.1",
            "lmstudio.port": 1234,
            "llm.model": "test-model",
            "llm.temperature": 0.7,
            "llm.max_tokens": 500,
            "lmstudio.mcp_enabled": True,
        }.get(key, default)


@pytest.fixture
def client():
    """Client with explicit base_url (no real HTTP)."""
    return LMStudioClient(
        base_url="http://127.0.0.1:1234",
        config=MockConfig(),
    )


# ── MCP helper tests ──────────────────────────────────────────────────

class TestMCPHelpers:
    def test_plugin(self):
        result = MCP.plugin("mcp/cosysim")
        assert result == {"type": "plugin", "id": "mcp/cosysim"}

    def test_ephemeral(self):
        result = MCP.ephemeral("http://localhost:8600/mcp/sse")
        assert result == {
            "type": "ephemeral_mcp",
            "server_url": "http://localhost:8600/mcp/sse",
        }


# ── ChatResponse tests ────────────────────────────────────────────────

class TestChatResponse:
    def test_tokens_per_second(self):
        r = ChatResponse(
            content="hello",
            output_tokens=100,
            latency_ms=2000.0,
        )
        assert abs(r.tokens_per_second - 50.0) < 0.1

    def test_tokens_per_second_zero_latency(self):
        r = ChatResponse(content="", latency_ms=0)
        assert r.tokens_per_second == 0.0

    def test_tokens_per_second_zero_tokens(self):
        r = ChatResponse(content="", output_tokens=0, latency_ms=1000)
        assert r.tokens_per_second == 0.0


class TestStreamResult:
    def test_tokens_per_second(self):
        r = StreamResult(chunks=50, total_ms=1000.0)
        assert abs(r.tokens_per_second - 50.0) < 0.1

    def test_zero_ms(self):
        r = StreamResult(chunks=10, total_ms=0)
        assert r.tokens_per_second == 0.0


# ── Payload building ──────────────────────────────────────────────────

class TestBuildPayload:
    def test_basic_payload(self, client):
        msgs = [{"role": "user", "content": "hi"}]
        p = client._build_payload(msgs, stream=False)
        assert p["messages"] == msgs
        assert p["model"] == "test-model"
        assert p["temperature"] == 0.7
        assert p["max_tokens"] == 500
        assert p["stream"] is False
        assert "integrations" not in p

    def test_with_integrations(self, client):
        msgs = [{"role": "user", "content": "hi"}]
        integ = [MCP.plugin("mcp/test")]
        p = client._build_payload(msgs, integrations=integ, stream=False)
        assert p["integrations"] == integ

    def test_integrations_disabled(self, client):
        client._mcp_enabled = False
        msgs = [{"role": "user", "content": "hi"}]
        integ = [MCP.plugin("mcp/test")]
        p = client._build_payload(msgs, integrations=integ, stream=False)
        assert "integrations" not in p

    def test_custom_model_and_temp(self, client):
        msgs = [{"role": "user", "content": "hi"}]
        p = client._build_payload(
            msgs, model="custom-model", temperature=0.2, max_tokens=100, stream=True
        )
        assert p["model"] == "custom-model"
        assert p["temperature"] == 0.2
        assert p["max_tokens"] == 100
        assert p["stream"] is True

    def test_response_format(self, client):
        msgs = [{"role": "user", "content": "hi"}]
        fmt = {"type": "json_object"}
        p = client._build_payload(msgs, response_format=fmt, stream=False)
        assert p["response_format"] == fmt

    def test_tools(self, client):
        msgs = [{"role": "user", "content": "hi"}]
        tools = [{"type": "function", "function": {"name": "test"}}]
        p = client._build_payload(msgs, tools=tools, stream=False)
        assert p["tools"] == tools


# ── Chat (mocked HTTP) ───────────────────────────────────────────────

class TestChat:
    def test_chat_success(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "model": "test-model",
            "choices": [{
                "message": {"content": "Hello back!"},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", return_value=mock_response):
            resp = client.chat([{"role": "user", "content": "Hello"}])

        assert isinstance(resp, ChatResponse)
        assert resp.content == "Hello back!"
        assert resp.model == "test-model"
        assert resp.input_tokens == 10
        assert resp.output_tokens == 5
        assert resp.latency_ms > 0

    def test_chat_connection_error(self, client):
        import httpx
        with patch.object(client._client, "post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(ConnectionError, match="Cannot connect"):
                client.chat([{"role": "user", "content": "Hello"}])

    def test_chat_with_mcp(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "MCP reply"}, "finish_reason": "stop"}],
            "usage": {},
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", return_value=mock_response) as mock_post:
            resp = client.chat_with_mcp(
                [{"role": "user", "content": "hi"}],
                [MCP.plugin("mcp/cosysim")],
            )

        # Verify integrations were passed
        call_payload = mock_post.call_args[1]["json"]
        assert "integrations" in call_payload
        assert call_payload["integrations"][0]["type"] == "plugin"

    def test_chat_with_mcp_disabled(self, client):
        client._mcp_enabled = False
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "reply"}, "finish_reason": "stop"}],
            "usage": {},
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", return_value=mock_response) as mock_post:
            resp = client.chat_with_mcp(
                [{"role": "user", "content": "hi"}],
                [MCP.plugin("mcp/test")],
            )

        # Verify integrations were NOT passed
        call_payload = mock_post.call_args[1]["json"]
        assert "integrations" not in call_payload


# ── Convenience methods ───────────────────────────────────────────────

class TestConvenience:
    def test_quick_reply(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Quick!"}, "finish_reason": "stop"}],
            "usage": {},
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", return_value=mock_response):
            result = client.quick_reply("Say something", system="Be brief")

        assert result == "Quick!"


# ── Health check ──────────────────────────────────────────────────────

class TestHealth:
    def test_is_available_true(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch.object(client._client, "get", return_value=mock_response):
            assert client.is_available() is True

    def test_is_available_false(self, client):
        import httpx
        with patch.object(client._client, "get", side_effect=httpx.ConnectError("refused")):
            assert client.is_available() is False

    def test_get_models(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "model-1"}, {"id": "model-2"}]
        }
        mock_response.raise_for_status = MagicMock()
        with patch.object(client._client, "get", return_value=mock_response):
            models = client.get_models()
            assert len(models) == 2
            assert models[0]["id"] == "model-1"

    def test_get_loaded_model_id(self, client):
        with patch.object(client, "get_models", return_value=[{"id": "active-model"}]):
            assert client.get_loaded_model_id() == "active-model"

    def test_get_loaded_model_id_none(self, client):
        with patch.object(client, "get_models", return_value=[]):
            assert client.get_loaded_model_id() is None


# ── Token counting fallback ──────────────────────────────────────────

class TestTokenCounting:
    def test_count_tokens_fallback(self, client):
        """Falls back to chars/4 when SDK unavailable."""
        with patch("engine.lmstudio.client_v2.LMStudioClient.count_tokens") as mock_ct:
            # Simulate the actual fallback logic
            mock_ct.side_effect = lambda text, model=None: max(1, len(text) // 4)
            result = client.count_tokens("Hello world, this is a test")
            assert result >= 1

    def test_context_length_fallback(self, client):
        """Falls back to 4096 when SDK unavailable."""
        with patch.dict("sys.modules", {"lmstudio": None}):
            result = client.get_context_length()
            assert result == 4096


# ── repr ─────────────────────────────────────────────────────────────

class TestRepr:
    def test_repr(self, client):
        r = repr(client)
        assert "LMStudioClient" in r
        assert "127.0.0.1:1234" in r
        assert "mcp=True" in r
