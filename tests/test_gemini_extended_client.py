"""Tests for engine.integrations.gemini_extended_client.

All HTTP calls are mocked — no real network calls are made.

Coverage (25+ tests):
  - Auth loading (nlm_meta.json, account pool)
  - _get_headers: Cookie, Origin, X-Same-Domain
  - _batchexecute: correct URL construction, f.req body, at_token
  - _parse_batchexecute_response: wrb.fr parsing, XSSI strip
  - list_storybooks (HcT8bb): payload template, locale, page_size
  - get_storybook (XqA3Ic): payload with storybook_id
  - list_saved_info (ZKcapf): page_size in payload
  - list_my_content (jGArJ): filter array construction
  - get_subscription_tiers (sJBwce): payload [[1,2]]
  - stream_response: StreamGenerate endpoint, chunk iteration
  - Registry rpcid lookup (not hardcoded strings)
  - Singleton helpers (get/reset)
  - Error handling (HTTP errors, malformed responses)
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
import requests


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_batchexecute_response(rpcid: str, inner: Any) -> str:
    """Build a minimal batchexecute wrb.fr HTTP response string."""
    inner_json = json.dumps(inner, separators=(",", ":"))
    chunk = json.dumps([["wrb.fr", rpcid, inner_json]], separators=(",", ":"))
    return f")]}'\n{chunk}\n"


def _make_client(
    cookies: str = "SID=gemini_test",
    at_token: str = "gemini_at",
) -> Any:
    """Create a GeminiExtendedClient with auth pre-loaded."""
    from engine.integrations.gemini_extended_client import GeminiExtendedClient
    with patch.object(GeminiExtendedClient, "_load_auth"):
        client = GeminiExtendedClient()
    client._cookies = cookies
    client._at_token = at_token
    return client


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    """GeminiExtendedClient with mocked auth."""
    return _make_client()


# ──── Auth loading ────────────────────────────────────────────────────────────


class TestGeminiExtendedAuth:
    """Auth loading from nlm_meta.json and account pool."""

    def test_load_auth_reads_nlm_meta(self, tmp_path, monkeypatch) -> None:
        """_load_auth reads at_token from nlm_meta.json."""
        meta = {"at": "meta_at", "cookies": "SID=meta"}
        meta_file = tmp_path / "nlm_meta.json"
        meta_file.write_text(json.dumps(meta))

        from engine.integrations import gemini_extended_client as gec
        monkeypatch.setattr(gec, "_NLM_META_PATH", meta_file)

        from engine.integrations.gemini_extended_client import GeminiExtendedClient
        with patch(
            "engine.integrations.google_account_pool.get_account_pool"
        ) as mock_pool:
            mock_pool.return_value.get_best_account.return_value = None
            c = GeminiExtendedClient()

        assert c._at_token == "meta_at"
        assert c._cookies == "SID=meta"

    def test_load_auth_falls_back_to_account_pool(self, tmp_path, monkeypatch) -> None:
        """_load_auth falls back to account pool when nlm_meta has no cookies."""
        meta_file = tmp_path / "no_cookies_meta.json"
        meta_file.write_text(json.dumps({"at": "at1"}))

        from engine.integrations import gemini_extended_client as gec
        monkeypatch.setattr(gec, "_NLM_META_PATH", meta_file)

        mock_account = MagicMock()
        mock_account.at_token = "pool_at"
        mock_pool = MagicMock()
        mock_pool.get_best_account.return_value = mock_account
        mock_pool.get_cookie_header.return_value = "SID=pool"

        from engine.integrations.gemini_extended_client import GeminiExtendedClient
        with patch(
            "engine.integrations.google_account_pool.get_account_pool",
            return_value=mock_pool,
        ):
            c = GeminiExtendedClient()

        assert c._cookies == "SID=pool"


# ──── _get_headers ────────────────────────────────────────────────────────────


class TestGeminiExtendedGetHeaders:
    """Header construction."""

    def test_get_headers_includes_cookie(self, client) -> None:
        """Cookie header is set when cookies are loaded."""
        headers = client._get_headers()
        assert headers["Cookie"] == "SID=gemini_test"

    def test_get_headers_origin(self, client) -> None:
        """Origin is set to gemini.google.com."""
        headers = client._get_headers()
        assert headers["Origin"] == "https://gemini.google.com"

    def test_get_headers_xsamedomain(self, client) -> None:
        """X-Same-Domain header is '1'."""
        headers = client._get_headers()
        assert headers["X-Same-Domain"] == "1"

    def test_get_headers_no_cookie_when_empty(self) -> None:
        """Cookie header is omitted when cookies string is empty."""
        c = _make_client(cookies="")
        headers = c._get_headers()
        assert "Cookie" not in headers


# ──── _parse_batchexecute_response ────────────────────────────────────────────


class TestGeminiExtendedParsing:
    """_parse_batchexecute_response."""

    def test_parse_extracts_inner_payload(self, client) -> None:
        """Parser extracts inner JSON for matching rpcid."""
        raw = _make_batchexecute_response("HcT8bb", [["sb1"], ["sb2"]])
        result = client._parse_batchexecute_response(raw, "HcT8bb")
        assert result == [["sb1"], ["sb2"]]

    def test_parse_strips_xssi(self, client) -> None:
        """Parser strips the )]}' prefix."""
        inner = {"key": "val"}
        inner_json = json.dumps(inner)
        chunk = json.dumps([["wrb.fr", "ZKcapf", inner_json]])
        raw = f")]}'\n{chunk}"
        result = client._parse_batchexecute_response(raw, "ZKcapf")
        assert result == inner

    def test_parse_returns_none_wrong_rpcid(self, client) -> None:
        """Parser returns None for wrong rpcid."""
        raw = _make_batchexecute_response("HcT8bb", [])
        result = client._parse_batchexecute_response(raw, "OTHER")
        assert result is None

    def test_parse_returns_none_for_empty(self, client) -> None:
        """Parser returns None for empty response."""
        result = client._parse_batchexecute_response("", "HcT8bb")
        assert result is None


# ──── _batchexecute ───────────────────────────────────────────────────────────


class TestGeminiExtendedBatchexecute:
    """_batchexecute HTTP construction."""

    def test_batchexecute_posts_to_gemini_url(self, client) -> None:
        """_batchexecute POSTs to gemini.google.com batchexecute."""
        raw = _make_batchexecute_response("HcT8bb", [])
        mock_resp = MagicMock()
        mock_resp.text = raw
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            client._batchexecute("HcT8bb", [])
        url = mock_post.call_args[0][0]
        assert "gemini.google.com" in url
        assert "HcT8bb" in url

    def test_batchexecute_includes_at_token(self, client) -> None:
        """_batchexecute includes 'at' token in POST body."""
        raw = _make_batchexecute_response("HcT8bb", [])
        mock_resp = MagicMock()
        mock_resp.text = raw
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            client._batchexecute("HcT8bb", ["payload"])
        body = mock_post.call_args[1]["data"]
        parsed = dict(urllib.parse.parse_qsl(body))
        assert parsed.get("at") == "gemini_at"

    def test_batchexecute_raises_on_http_error(self, client) -> None:
        """_batchexecute propagates HTTPError."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("401")
        with patch.object(client._session, "post", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                client._batchexecute("HcT8bb", [])

    def test_batchexecute_omits_at_token_when_none(self) -> None:
        """_batchexecute skips 'at' param when at_token is None."""
        c = _make_client(at_token="")
        c._at_token = None
        raw = _make_batchexecute_response("HcT8bb", [])
        mock_resp = MagicMock()
        mock_resp.text = raw
        mock_resp.raise_for_status = MagicMock()
        with patch.object(c._session, "post", return_value=mock_resp) as mock_post:
            c._batchexecute("HcT8bb", [])
        body = mock_post.call_args[1]["data"]
        parsed = dict(urllib.parse.parse_qsl(body))
        assert "at" not in parsed


# ──── list_storybooks (HcT8bb) ───────────────────────────────────────────────


class TestGeminiListStorybooks:
    """list_storybooks using rpcid HcT8bb."""

    def test_list_storybooks_uses_correct_rpcid(self, client) -> None:
        """list_storybooks passes HcT8bb to _batchexecute."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.list_storybooks()
        assert mock_exec.call_args[0][0] == "HcT8bb"

    def test_list_storybooks_payload_template(self, client) -> None:
        """list_storybooks sends correct payload template."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.list_storybooks(page_size=10, locale="en-US")
        payload = mock_exec.call_args[0][1]
        assert payload[0] == "storybook"
        assert "en-US" in payload[1]

    def test_list_storybooks_returns_empty_on_none(self, client) -> None:
        """list_storybooks returns [] when batchexecute returns None."""
        with patch.object(client, "_batchexecute", return_value=None):
            result = client.list_storybooks()
        assert result == []

    def test_list_storybooks_flattens_nested_lists(self, client) -> None:
        """list_storybooks flattens nested list responses."""
        with patch.object(
            client,
            "_batchexecute",
            return_value=[[{"id": "sb1"}, {"id": "sb2"}]],
        ):
            result = client.list_storybooks(page_size=5)
        assert len(result) >= 1


# ──── get_storybook (XqA3Ic) ─────────────────────────────────────────────────


class TestGeminiGetStorybook:
    """get_storybook using rpcid XqA3Ic."""

    def test_get_storybook_uses_correct_rpcid(self, client) -> None:
        """get_storybook passes XqA3Ic to _batchexecute."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.get_storybook("sb123")
        assert mock_exec.call_args[0][0] == "XqA3Ic"

    def test_get_storybook_passes_id_in_payload(self, client) -> None:
        """get_storybook includes storybook_id in payload."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.get_storybook("mybook")
        payload = mock_exec.call_args[0][1]
        assert payload[0] == "mybook"

    def test_get_storybook_returns_dict_response(self, client) -> None:
        """get_storybook returns dict when batchexecute returns dict."""
        with patch.object(
            client, "_batchexecute", return_value={"title": "My Storybook"}
        ):
            result = client.get_storybook("sb1")
        assert result["title"] == "My Storybook"

    def test_get_storybook_wraps_list_response(self, client) -> None:
        """get_storybook wraps list response in id+data dict."""
        with patch.object(client, "_batchexecute", return_value=["data1", "data2"]):
            result = client.get_storybook("sb2")
        assert result["id"] == "sb2"
        assert result["data"] == ["data1", "data2"]


# ──── list_saved_info (ZKcapf) ───────────────────────────────────────────────


class TestGeminiListSavedInfo:
    """list_saved_info using rpcid ZKcapf."""

    def test_list_saved_info_uses_correct_rpcid(self, client) -> None:
        """list_saved_info passes ZKcapf to _batchexecute."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.list_saved_info()
        assert mock_exec.call_args[0][0] == "ZKcapf"

    def test_list_saved_info_page_size_in_payload(self, client) -> None:
        """list_saved_info includes page_size as first payload element."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.list_saved_info(page_size=50)
        payload = mock_exec.call_args[0][1]
        assert payload[0] == 50

    def test_list_saved_info_includes_category(self, client) -> None:
        """list_saved_info appends category to payload when provided."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.list_saved_info(category="recipes")
        payload = mock_exec.call_args[0][1]
        assert "recipes" in payload

    def test_list_saved_info_returns_empty_on_none(self, client) -> None:
        """list_saved_info returns [] when batchexecute returns None."""
        with patch.object(client, "_batchexecute", return_value=None):
            assert client.list_saved_info() == []


# ──── list_my_content (jGArJ) ────────────────────────────────────────────────


class TestGeminiListMyContent:
    """list_my_content using rpcid jGArJ."""

    def test_list_my_content_uses_correct_rpcid(self, client) -> None:
        """list_my_content passes jGArJ to _batchexecute."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.list_my_content()
        assert mock_exec.call_args[0][0] == "jGArJ"

    def test_list_my_content_default_filter_array(self, client) -> None:
        """list_my_content sends 7-element filter array."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.list_my_content()
        payload = mock_exec.call_args[0][1]
        assert isinstance(payload[0], list)
        assert len(payload[0]) == 7

    def test_list_my_content_content_type_filter(self, client) -> None:
        """list_my_content builds correct filter for content_type='conversations'."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.list_my_content(content_type="conversations")
        payload = mock_exec.call_args[0][1]
        filters = payload[0]
        # conversations is index 4
        assert filters[4] == 1
        assert sum(filters) == 1  # only one flag set

    def test_list_my_content_returns_empty_on_none(self, client) -> None:
        """list_my_content returns [] when batchexecute returns None."""
        with patch.object(client, "_batchexecute", return_value=None):
            assert client.list_my_content() == []


# ──── get_subscription_tiers (sJBwce) ────────────────────────────────────────


class TestGeminiGetSubscriptionTiers:
    """get_subscription_tiers using rpcid sJBwce."""

    def test_get_subscription_tiers_uses_correct_rpcid(self, client) -> None:
        """get_subscription_tiers passes sJBwce to _batchexecute."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.get_subscription_tiers()
        assert mock_exec.call_args[0][0] == "sJBwce"

    def test_get_subscription_tiers_payload_template(self, client) -> None:
        """get_subscription_tiers sends [[1, 2]] payload."""
        with patch.object(client, "_batchexecute", return_value=None) as mock_exec:
            client.get_subscription_tiers()
        payload = mock_exec.call_args[0][1]
        assert payload == [[1, 2]]

    def test_get_subscription_tiers_extracts_tier(self, client) -> None:
        """get_subscription_tiers extracts current_tier from response list."""
        with patch.object(client, "_batchexecute", return_value=["pro", ["free", "pro"]]):
            result = client.get_subscription_tiers()
        assert result["current_tier"] == "pro"
        assert "free" in result["available_tiers"]

    def test_get_subscription_tiers_handles_none(self, client) -> None:
        """get_subscription_tiers returns safe defaults when response is None."""
        with patch.object(client, "_batchexecute", return_value=None):
            result = client.get_subscription_tiers()
        assert result["current_tier"] is None
        assert result["available_tiers"] == []


# ──── stream_response ─────────────────────────────────────────────────────────


class TestGeminiStreamResponse:
    """stream_response via BardFrontendService/StreamGenerate."""

    def test_stream_response_posts_to_stream_endpoint(self, client) -> None:
        """stream_response POSTs to BardFrontendService/StreamGenerate."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content.return_value = iter([])
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            list(client.stream_response("hello"))
        url = mock_post.call_args[0][0]
        assert "BardFrontendService" in url
        assert "StreamGenerate" in url

    def test_stream_response_yields_chunks(self, client) -> None:
        """stream_response yields extracted text chunks."""
        chunk_text = "streaming response"
        inner = [[chunk_text]]
        inner_json = json.dumps(inner)
        line = json.dumps([["wrb.fr", "sr", inner_json]])
        raw_chunk = f")]}'\n{line}\n"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content.return_value = iter([raw_chunk])
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch.object(client._session, "post", return_value=mock_resp):
            chunks = list(client.stream_response("prompt"))
        assert chunk_text in chunks

    def test_stream_response_raises_on_http_error(self, client) -> None:
        """stream_response propagates HTTP errors."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("403")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch.object(client._session, "post", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                list(client.stream_response("prompt"))


# ──── Registry rpcid lookup ───────────────────────────────────────────────────


class TestGeminiRegistryLookup:
    """Registry is used for rpcid lookup, not hardcoded strings."""

    def test_resolve_rpcid_uses_registry_data(self, client) -> None:
        """_resolve_rpcid returns correct rpcid from registry data."""
        mock_registry = MagicMock()
        mock_registry._data = {
            "gemini": {"rpcids": {"HcT8bb": {"description": "storybook"}}}
        }
        client._registry = mock_registry
        rpcid = client._resolve_rpcid("HcT8bb", "FALLBACK")
        assert rpcid == "HcT8bb"

    def test_resolve_rpcid_returns_fallback_when_registry_none(self, client) -> None:
        """_resolve_rpcid uses fallback when registry is None."""
        client._registry = None
        rpcid = client._resolve_rpcid("HcT8bb", "FALLBACK")
        assert rpcid == "FALLBACK"


# ──── Singleton helpers ────────────────────────────────────────────────────────


class TestGeminiExtendedSingleton:
    """get_gemini_extended_client / reset_gemini_extended_client helpers."""

    def test_singleton_returns_instance(self) -> None:
        """get_gemini_extended_client returns GeminiExtendedClient."""
        from engine.integrations.gemini_extended_client import (
            GeminiExtendedClient,
            get_gemini_extended_client,
            reset_gemini_extended_client,
        )
        reset_gemini_extended_client()
        with patch.object(GeminiExtendedClient, "_load_auth"):
            inst = get_gemini_extended_client()
        assert isinstance(inst, GeminiExtendedClient)
        reset_gemini_extended_client()

    def test_singleton_is_same_instance(self) -> None:
        """get_gemini_extended_client returns the same instance."""
        from engine.integrations.gemini_extended_client import (
            GeminiExtendedClient,
            get_gemini_extended_client,
            reset_gemini_extended_client,
        )
        reset_gemini_extended_client()
        with patch.object(GeminiExtendedClient, "_load_auth"):
            a = get_gemini_extended_client()
            b = get_gemini_extended_client()
        assert a is b
        reset_gemini_extended_client()

    def test_reset_creates_new_instance(self) -> None:
        """reset_gemini_extended_client forces a new instance."""
        from engine.integrations.gemini_extended_client import (
            GeminiExtendedClient,
            get_gemini_extended_client,
            reset_gemini_extended_client,
        )
        reset_gemini_extended_client()
        with patch.object(GeminiExtendedClient, "_load_auth"):
            a = get_gemini_extended_client()
        reset_gemini_extended_client()
        with patch.object(GeminiExtendedClient, "_load_auth"):
            b = get_gemini_extended_client()
        assert a is not b
        reset_gemini_extended_client()
