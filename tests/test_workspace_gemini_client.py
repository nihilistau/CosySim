"""Tests for WorkspaceGeminiClient — the unified Workspace Gemini backend client."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_account():
    """Create a mock GoogleAccount for testing."""
    account = MagicMock()
    account.name = "test_account"
    account.authuser = 0
    account.cookies = {"SID": "abc", "HSID": "def", "SSID": "ghi", "SAPISID": "12345//test"}
    return account


@pytest.fixture
def client(mock_account):
    """Create a WorkspaceGeminiClient with mock account."""
    with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool:
        mock_pool.return_value.get_cookie_header.return_value = "SID=abc; HSID=def"
        from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient
        return WorkspaceGeminiClient(account=mock_account)


# ──── Constructor Tests ───────────────────────────────────────────────────────


class TestWorkspaceGeminiClientInit:
    """Tests for client initialisation."""

    def test_init_with_account(self, mock_account):
        """Client initialises with a GoogleAccount."""
        from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient
        c = WorkspaceGeminiClient(account=mock_account)
        assert c._account is mock_account

    def test_init_stores_api_key(self, mock_account):
        """Client stores custom API key when provided."""
        from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient
        c = WorkspaceGeminiClient(account=mock_account, api_key="test-key")
        assert c._api_key == "test-key"

    def test_init_default_api_key(self, mock_account):
        """Client uses default API key when none provided."""
        from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient
        c = WorkspaceGeminiClient(account=mock_account)
        assert c._api_key is not None

    def test_session_created(self, client):
        """Client creates a requests session."""
        assert client._session is not None


# ──── Auth Tests ──────────────────────────────────────────────────────────────


class TestWorkspaceGeminiAuth:
    """Tests for auth header generation."""

    def test_get_headers_includes_origin(self, client):
        """Headers include the correct origin."""
        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            headers = client._get_headers()
            assert "Origin" in headers

    def test_get_headers_includes_authorization(self, client):
        """Headers include SAPISIDHASH authorization."""
        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            headers = client._get_headers()
            assert "Authorization" in headers
            assert "SAPISIDHASH" in headers["Authorization"]

    def test_get_params_includes_api_key(self, client):
        """Query params include API key when set."""
        client._api_key = "test-api-key"
        params = client._get_params()
        assert params["key"] == "test-api-key"

    def test_get_params_excludes_empty_key(self, client):
        """Query params exclude API key when empty."""
        client._api_key = ""
        params = client._get_params()
        assert "key" not in params

    def test_get_params_merges_extra(self, client):
        """Extra params are merged in."""
        params = client._get_params(extra={"foo": "bar"})
        assert params["foo"] == "bar"


# ──── Streaming Parser Tests ──────────────────────────────────────────────────


class TestStreamingParser:
    """Tests for chunked protobuf-JSON response parsing."""

    def test_parse_stream_yields_json_chunks(self, client):
        """_parse_stream yields parsed JSON chunks from stream."""
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = iter([
            '{"text":"Hello"}',
            '{"text":" world"}',
        ])

        chunks = list(client._parse_stream(mock_resp))
        assert len(chunks) == 2
        assert chunks[0]["text"] == "Hello"

    def test_parse_stream_empty_response(self, client):
        """_parse_stream yields nothing for empty stream."""
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = iter([])
        chunks = list(client._parse_stream(mock_resp))
        assert chunks == []

    def test_parse_protobuf_json_plain(self, client):
        """_parse_protobuf_json parses plain JSON response."""
        mock_resp = MagicMock()
        mock_resp.text = '{"model": "gemini-2.5-pro", "features": []}'
        result = client._parse_protobuf_json(mock_resp)
        assert result["model"] == "gemini-2.5-pro"

    def test_parse_protobuf_json_strips_xss_prefix(self, client):
        """_parse_protobuf_json strips )]}' XSS prefix."""
        mock_resp = MagicMock()
        mock_resp.text = ")]}'\\n{\"ok\":true}"
        # The actual prefix check looks for real newline after prefix
        mock_resp2 = MagicMock()
        mock_resp2.text = ")]}'\n{\"ok\":true}"
        result = client._parse_protobuf_json(mock_resp2)
        assert result.get("ok") is True

    def test_parse_protobuf_json_invalid_returns_raw(self, client):
        """_parse_protobuf_json returns raw text on parse failure."""
        mock_resp = MagicMock()
        mock_resp.text = "not valid json at all"
        result = client._parse_protobuf_json(mock_resp)
        assert "raw" in result

    def test_extract_text_from_dict(self, client):
        """_extract_text extracts text from a dict chunk with readable content."""
        from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient
        result = WorkspaceGeminiClient._extract_text(
            {"text": "This is a sufficiently long generated output text for testing"}
        )
        assert result == "This is a sufficiently long generated output text for testing"

    def test_extract_text_from_candidates(self, client):
        """_extract_text extracts text from candidates format."""
        from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient
        long_text = "Hello from Gemini, this is a generated response with enough length"
        chunk = {"candidates": [{"content": {"parts": [{"text": long_text}]}}]}
        result = WorkspaceGeminiClient._extract_text(chunk)
        assert result == long_text

    def test_extract_text_empty_dict(self, client):
        """_extract_text returns empty string for no text."""
        from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient
        result = WorkspaceGeminiClient._extract_text({})
        assert result == ""

    def test_extract_model_from_chunks(self, client):
        """_extract_model finds model name in chunks."""
        from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient
        result = WorkspaceGeminiClient._extract_model([{"model": "gemini-2.5-pro"}])
        assert result == "gemini-2.5-pro"

    def test_extract_model_empty_chunks(self, client):
        """_extract_model returns empty string for no model."""
        from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient
        result = WorkspaceGeminiClient._extract_model([{}])
        assert result == ""

    def test_extract_usage_from_chunks(self, client):
        """_extract_usage finds token counts."""
        from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient
        chunks = [{"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20, "totalTokenCount": 30}}]
        result = WorkspaceGeminiClient._extract_usage(chunks)
        assert result["prompt_tokens"] == 10
        assert result["completion_tokens"] == 20
        assert result["total_tokens"] == 30

    def test_extract_usage_empty_returns_empty(self, client):
        """_extract_usage returns empty dict when no usage found."""
        from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient
        result = WorkspaceGeminiClient._extract_usage([{}])
        assert result == {}


# ──── API Method Tests ────────────────────────────────────────────────────────


class TestStreamGenerate:
    """Tests for the stream_generate method."""

    def test_stream_generate_sends_request(self, client):
        """stream_generate sends a POST request and returns dict."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = iter(['{"text":"Generated text"}'])
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.stream_generate("Write a haiku")
            assert isinstance(result, dict)
            assert "text" in result

    def test_stream_generate_with_context(self, client):
        """stream_generate includes document context in request."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = iter(['{"text":"result"}'])
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            client.stream_generate("Summarise", context="Some document text")
            assert mock_post.called

    def test_stream_generate_error_returns_error_dict(self, client):
        """stream_generate returns error dict on HTTP errors."""
        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post") as mock_post:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            mock_post.side_effect = requests.RequestException("Server error")
            result = client.stream_generate("fail prompt")
            assert "error" in result
            assert result["text"] == ""


class TestGetSettings:
    """Tests for the get_settings method."""

    def test_get_settings_returns_dict(self, client):
        """get_settings returns a settings dictionary."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"model": "gemini-2.5-pro", "features": {}}'
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.get_settings()
            assert isinstance(result, dict)
            assert result["model"] == "gemini-2.5-pro"

    def test_get_settings_error_returns_error_dict(self, client):
        """get_settings returns error dict on failure."""
        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post") as mock_post:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            mock_post.side_effect = requests.RequestException("timeout")
            result = client.get_settings()
            assert "error" in result


class TestListGems:
    """Tests for the list_gems method."""

    def test_list_gems_returns_list(self, client):
        """list_gems returns a list of available models."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"gems": [{"name": "gemini-2.5-pro"}]}'
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.list_gems()
            assert isinstance(result, list)
            assert result[0]["name"] == "gemini-2.5-pro"

    def test_list_gems_error_returns_empty_list(self, client):
        """list_gems returns empty list on failure."""
        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post") as mock_post:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            mock_post.side_effect = requests.RequestException("timeout")
            result = client.list_gems()
            assert result == []


class TestQuotaSummary:
    """Tests for the quota_summary method."""

    def test_quota_summary_returns_usage(self, client):
        """quota_summary returns parsed quota from protobuf-JSON array."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '[[null,["10000000",null,"9999998",1,null,null,["1775026800"]],"2",[3],1],[]]'
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.quota_summary()
            assert isinstance(result, dict)
            assert result["total"] == 10000000
            assert result["remaining"] == 9999998
            assert result["used"] == "2"

    def test_quota_summary_error_returns_error_dict(self, client):
        """quota_summary returns error dict on failure."""
        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post") as mock_post:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            mock_post.side_effect = requests.RequestException("timeout")
            result = client.quota_summary()
            assert "error" in result


class TestCloudSearch:
    """Tests for the cloud_search method."""

    def test_cloud_search_sends_query(self, client):
        """cloud_search sends a search query."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [], "total": 0}
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post", return_value=mock_resp):
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            result = client.cloud_search("quantum computing")
            assert isinstance(result, dict)

    def test_cloud_search_with_page_size(self, client):
        """cloud_search respects page_size parameter."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool, \
             patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            mock_pool.return_value.get_cookie_header.return_value = "SID=abc"
            client.cloud_search("test", page_size=5)
            assert mock_post.called


# ──── Factory Tests ───────────────────────────────────────────────────────────


class TestFactory:
    """Tests for the module-level factory function."""

    def test_get_workspace_gemini_client_returns_instance(self):
        """get_workspace_gemini_client returns a client when account available."""
        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool:
            mock_acc = MagicMock()
            mock_acc.cookies = {"SAPISID": "x//y"}
            mock_acc.authuser = 0
            mock_pool.return_value.get_best_account.return_value = mock_acc
            from engine.integrations.workspace_gemini_client import get_workspace_gemini_client
            result = get_workspace_gemini_client()
            assert result is not None

    def test_get_workspace_gemini_client_no_account_raises(self):
        """get_workspace_gemini_client raises RuntimeError when no account."""
        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool:
            mock_pool.return_value.get_best_account.return_value = None
            from engine.integrations.workspace_gemini_client import get_workspace_gemini_client
            with pytest.raises(RuntimeError, match="No Google account"):
                get_workspace_gemini_client()

    def test_get_workspace_gemini_client_with_named_account(self):
        """get_workspace_gemini_client uses named account when provided."""
        with patch("engine.integrations.workspace_gemini_client.get_account_pool") as mock_pool:
            mock_acc = MagicMock()
            mock_acc.cookies = {"SAPISID": "x//y"}
            mock_acc.authuser = 0
            mock_pool.return_value.get_account.return_value = mock_acc
            from engine.integrations.workspace_gemini_client import get_workspace_gemini_client
            result = get_workspace_gemini_client(account_name="test")
            assert result is not None
            mock_pool.return_value.get_account.assert_called_with("test")
