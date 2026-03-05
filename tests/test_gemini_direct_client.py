"""Tests for GeminiDirectClient — ARGUS SDK gap methods (17 GEMINI_RPCIDS)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.integrations.gemini_direct_client import GeminiDirectClient


# ──── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def client() -> GeminiDirectClient:
    """GeminiDirectClient with empty cookies."""
    return GeminiDirectClient(cookies={}, locale="en-AU")


# ──── get_feature_flags (ozz5Z) ────────────────────────────────────────────────


def test_get_feature_flags_default_ids(client: GeminiDirectClient) -> None:
    """Uses default flag IDs when none provided."""
    with patch.object(client, "_call", return_value=[[True, False, True, False, True, None]]) as mock:
        flags = client.get_feature_flags()
    assert mock.call_args[0][0] == "ozz5Z"
    assert len(flags) == 6
    assert flags[447] is True
    assert flags[448] is False


def test_get_feature_flags_custom_ids(client: GeminiDirectClient) -> None:
    """Passes custom flag IDs as payload."""
    with patch.object(client, "_call", return_value=[[True, True]]) as mock:
        flags = client.get_feature_flags(flag_ids=[100, 200])
    called_payload = mock.call_args[0][1]
    assert "100" in called_payload
    assert "200" in called_payload
    assert flags[100] is True
    assert flags[200] is True


def test_get_feature_flags_empty_on_error(client: GeminiDirectClient) -> None:
    """Returns empty dict on bad response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.get_feature_flags() == {}


# ──── get_locale_preferences (DYBcR) ──────────────────────────────────────────


def test_get_locale_preferences_calls_rpcid(client: GeminiDirectClient) -> None:
    """Calls DYBcR rpcid with locale."""
    with patch.object(client, "_call", return_value=[{"locale": "en-AU"}]) as mock:
        result = client.get_locale_preferences()
    assert mock.call_args[0][0] == "DYBcR"
    assert result == {"locale": "en-AU"}


def test_get_locale_preferences_fallback(client: GeminiDirectClient) -> None:
    """Falls back to client locale on empty response."""
    with patch.object(client, "_call", return_value=[]):
        result = client.get_locale_preferences()
    assert result["locale"] == "en-AU"


# ──── proxy_unary_call (boaYGb) ────────────────────────────────────────────────


def test_proxy_unary_call_returns_thought_signature(client: GeminiDirectClient) -> None:
    """Returns thought_signature and response from result."""
    with patch.object(client, "_call", return_value=[["sig-abc", {"data": 1}]]) as mock:
        result = client.proxy_unary_call("MyService", "MyMethod", {"key": "val"})
    assert mock.call_args[0][0] == "boaYGb"
    assert result["thought_signature"] == "sig-abc"
    assert result["response"] == {"data": 1}


def test_proxy_unary_call_returns_empty_on_error(client: GeminiDirectClient) -> None:
    """Returns empty dict on bad response."""
    with patch.object(client, "_call", return_value=[]):
        result = client.proxy_unary_call("S", "M", {})
    assert result == {}


# ──── generate_content (jKHnxe) ────────────────────────────────────────────────


def test_generate_content_calls_rpcid(client: GeminiDirectClient) -> None:
    """Calls jKHnxe with prompt, model, system_instruction, temp."""
    with patch.object(client, "_call", return_value=[["Hello world"]]) as mock:
        result = client.generate_content("Say hi", model="gemini-2.0-flash")
    assert mock.call_args[0][0] == "jKHnxe"
    assert result == "Hello world"


def test_generate_content_returns_empty_on_error(client: GeminiDirectClient) -> None:
    """Returns empty string on bad response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.generate_content("hi") == ""


def test_generate_content_with_system_instruction(client: GeminiDirectClient) -> None:
    """Payload includes system instruction when provided."""
    with patch.object(client, "_call", return_value=[["Response"]]) as mock:
        client.generate_content("prompt", system_instruction="You are helpful.")
    import json
    payload = json.loads(mock.call_args[0][1])
    assert payload[2] == "You are helpful."


# ──── stream_generate_content (r7Bvze) ────────────────────────────────────────


def test_stream_generate_content_joins_chunks(client: GeminiDirectClient) -> None:
    """Joins multiple streamed chunks into single string."""
    with patch.object(client, "_call", return_value=[["Hello "], ["world"]]) as mock:
        result = client.stream_generate_content("prompt")
    assert mock.call_args[0][0] == "r7Bvze"
    assert "Hello" in result


def test_stream_generate_content_returns_empty_on_error(client: GeminiDirectClient) -> None:
    """Returns empty string on bad response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.stream_generate_content("hi") == ""


# ──── count_tokens (mMEAEd) ────────────────────────────────────────────────────


def test_count_tokens_returns_integer(client: GeminiDirectClient) -> None:
    """Returns token count as integer."""
    with patch.object(client, "_call", return_value=[[42]]) as mock:
        count = client.count_tokens("Hello world")
    assert mock.call_args[0][0] == "mMEAEd"
    assert count == 42


def test_count_tokens_returns_zero_on_error(client: GeminiDirectClient) -> None:
    """Returns 0 on bad response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.count_tokens("hi") == 0


# ──── list_models (k9yDXd) ────────────────────────────────────────────────────


def test_list_models_calls_rpcid(client: GeminiDirectClient) -> None:
    """Calls k9yDXd with empty payload."""
    with patch.object(client, "_call", return_value=[[["flash", "Gemini 2.0 Flash", "other"]]]) as mock:
        models = client.list_models()
    assert mock.call_args[0][0] == "k9yDXd"
    assert models[0]["id"] == "flash"
    assert models[0]["display_name"] == "Gemini 2.0 Flash"


def test_list_models_returns_empty_on_error(client: GeminiDirectClient) -> None:
    """Returns empty list on bad response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.list_models() == []


# ──── get_model (XqsOBb) ──────────────────────────────────────────────────────


def test_get_model_returns_dict(client: GeminiDirectClient) -> None:
    """Returns model metadata dict."""
    with patch.object(client, "_call", return_value=[[{"id": "flash", "version": "2.0"}]]) as mock:
        result = client.get_model("flash")
    assert mock.call_args[0][0] == "XqsOBb"
    assert result["id"] == "flash"


def test_get_model_wraps_list(client: GeminiDirectClient) -> None:
    """Wraps list result with model id."""
    with patch.object(client, "_call", return_value=[["flash", "v2.0"]]):
        result = client.get_model("flash")
    assert result["id"] == "flash"


def test_get_model_returns_id_on_empty(client: GeminiDirectClient) -> None:
    """Returns minimal dict on empty response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.get_model("flash") == {"id": "flash"}


# ──── create_file (BgXnQc) ────────────────────────────────────────────────────


def test_create_file_encodes_bytes(client: GeminiDirectClient) -> None:
    """Encodes file_data as base64 in payload."""
    with patch.object(client, "_call", return_value=[["fid-1", "uri://file"]]) as mock:
        result = client.create_file(b"hello", "text/plain", "test.txt")
    assert mock.call_args[0][0] == "BgXnQc"
    import json, base64
    payload = json.loads(mock.call_args[0][1])
    assert base64.b64decode(payload[0]) == b"hello"
    assert result["file_id"] == "fid-1"
    assert result["uri"] == "uri://file"


def test_create_file_returns_empty_on_error(client: GeminiDirectClient) -> None:
    """Returns empty dict on bad response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.create_file(b"x", "text/plain") == {}


# ──── list_files (mfvMVb) ─────────────────────────────────────────────────────


def test_list_files_calls_rpcid(client: GeminiDirectClient) -> None:
    """Calls mfvMVb with empty payload."""
    with patch.object(client, "_call", return_value=[[["fid-1", "uri://1", "test.txt", "text/plain", "ACTIVE"]]]) as mock:
        files = client.list_files()
    assert mock.call_args[0][0] == "mfvMVb"
    assert files[0]["id"] == "fid-1"
    assert files[0]["mime_type"] == "text/plain"


def test_list_files_returns_empty_on_error(client: GeminiDirectClient) -> None:
    """Returns empty list on bad response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.list_files() == []


# ──── delete_file (qVSQ5c) ────────────────────────────────────────────────────


def test_delete_file_calls_correct_rpcid(client: GeminiDirectClient) -> None:
    """Calls qVSQ5c with [file_id]."""
    with patch.object(client, "_call", return_value=[[]]) as mock:
        result = client.delete_file("fid-1")
    assert mock.call_args[0][0] == "qVSQ5c"
    assert result is True


# ──── get_file (ozVbQb) ────────────────────────────────────────────────────────


def test_get_file_returns_dict(client: GeminiDirectClient) -> None:
    """Returns file metadata dict."""
    with patch.object(client, "_call", return_value=[[{"id": "fid-1"}]]) as mock:
        result = client.get_file("fid-1")
    assert mock.call_args[0][0] == "ozVbQb"
    assert result["id"] == "fid-1"


def test_get_file_returns_id_on_empty(client: GeminiDirectClient) -> None:
    """Returns minimal dict on empty response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.get_file("fid-1") == {"id": "fid-1"}


# ──── create_cached_content (VUBhEd) ─────────────────────────────────────────


def test_create_cached_content_calls_rpcid(client: GeminiDirectClient) -> None:
    """Calls VUBhEd with content, model, ttl, name."""
    with patch.object(client, "_call", return_value=[["cache-1", 3600]]) as mock:
        result = client.create_cached_content("big context", display_name="my cache")
    assert mock.call_args[0][0] == "VUBhEd"
    assert result["cache_id"] == "cache-1"


def test_create_cached_content_returns_empty_on_error(client: GeminiDirectClient) -> None:
    """Returns empty dict on bad response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.create_cached_content("x") == {}


# ──── list_cached_contents (dXH9nb) ──────────────────────────────────────────


def test_list_cached_contents_calls_rpcid(client: GeminiDirectClient) -> None:
    """Calls dXH9nb with empty payload."""
    with patch.object(client, "_call", return_value=[[["c-1", "my cache", "gemini-2.0-flash", 9999]]]) as mock:
        caches = client.list_cached_contents()
    assert mock.call_args[0][0] == "dXH9nb"
    assert caches[0]["cache_id"] == "c-1"
    assert caches[0]["model"] == "gemini-2.0-flash"


def test_list_cached_contents_returns_empty_on_error(client: GeminiDirectClient) -> None:
    """Returns empty list on bad response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.list_cached_contents() == []


# ──── delete_cached_content (sPOurf) ─────────────────────────────────────────


def test_delete_cached_content_calls_rpcid(client: GeminiDirectClient) -> None:
    """Calls sPOurf with [cache_id]."""
    with patch.object(client, "_call", return_value=[[]]) as mock:
        result = client.delete_cached_content("c-1")
    assert mock.call_args[0][0] == "sPOurf"
    assert result is True


# ──── get_cached_content (jPv1oc) ────────────────────────────────────────────


def test_get_cached_content_returns_dict(client: GeminiDirectClient) -> None:
    """Returns cache metadata dict."""
    with patch.object(client, "_call", return_value=[[{"cache_id": "c-1"}]]) as mock:
        result = client.get_cached_content("c-1")
    assert mock.call_args[0][0] == "jPv1oc"
    assert result["cache_id"] == "c-1"


def test_get_cached_content_wraps_list(client: GeminiDirectClient) -> None:
    """Parses list result into named fields."""
    with patch.object(client, "_call", return_value=[["gemini-2.0-flash", 512, 1735000000]]):
        result = client.get_cached_content("c-1")
    assert result["cache_id"] == "c-1"
    assert result["model"] == "gemini-2.0-flash"
    assert result["token_count"] == 512


def test_get_cached_content_returns_id_on_empty(client: GeminiDirectClient) -> None:
    """Returns minimal dict on empty response."""
    with patch.object(client, "_call", return_value=[]):
        assert client.get_cached_content("c-1") == {"cache_id": "c-1"}
