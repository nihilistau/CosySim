"""Tests for engine.integrations.opal_client — Opal creative content client.

All HTTP calls are mocked — no real network calls are made.

Coverage:
  - OpalClient auth loading (nlm_meta.json, account pool, config)
  - generate_content: batchexecute payload construction
  - drive_proxy_get / drive_proxy_list: correct REST URLs
  - gallery_list / gallery_get: correct endpoints
  - Auth headers included correctly in all calls
  - Response parsing for batchexecute wrb.fr format
  - Error handling (HTTP errors, malformed responses)
  - Singleton helpers (get_opal_client, reset_opal_client)
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, Mock, patch, PropertyMock

import pytest
import requests


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_batchexecute_response(rpcid: str, inner: Any) -> str:
    """Build a minimal batchexecute wrb.fr HTTP response string."""
    inner_json = json.dumps(inner, separators=(",", ":"))
    chunk = json.dumps([["wrb.fr", rpcid, inner_json]], separators=(",", ":"))
    return f")]}'\n{chunk}\n"


def _make_client(cookies: str = "SID=test", at_token: str = "test_at") -> Any:
    """Create an OpalClient with auth pre-loaded (no disk/account pool calls)."""
    from engine.integrations.opal_client import OpalClient
    with patch.object(OpalClient, "_load_auth"):
        client = OpalClient()
    client._cookies = cookies
    client._at_token = at_token
    return client


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    """OpalClient with mocked auth."""
    return _make_client()


@pytest.fixture()
def mock_session(client):
    """Patch the client's requests.Session."""
    with patch.object(client, "_session") as mock:
        yield mock


# ──── Auth loading ────────────────────────────────────────────────────────────


class TestOpalClientAuth:
    """Auth loading from various sources."""

    def test_load_auth_from_nlm_meta(self, tmp_path, monkeypatch) -> None:
        """_load_auth reads at_token and cookies from nlm_meta.json."""
        meta = {"at": "my_at_token", "cookies": "SID=abc"}
        meta_file = tmp_path / "nlm_meta.json"
        meta_file.write_text(json.dumps(meta))

        from engine.integrations import opal_client as oc_mod
        monkeypatch.setattr(oc_mod, "_NLM_META_PATH", meta_file)

        from engine.integrations.opal_client import OpalClient
        with patch("engine.integrations.opal_client.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = None
            with patch("engine.integrations.google_account_pool.get_account_pool") as mock_pool:
                mock_pool.return_value.get_best_account.return_value = None
                client = OpalClient()

        assert client._at_token == "my_at_token"
        assert client._cookies == "SID=abc"

    def test_load_auth_from_account_pool(self, tmp_path, monkeypatch) -> None:
        """_load_auth falls back to account pool when nlm_meta.json has no cookies."""
        meta_file = tmp_path / "nlm_meta.json"
        meta_file.write_text(json.dumps({"at": "at1"}))

        from engine.integrations import opal_client as oc_mod
        monkeypatch.setattr(oc_mod, "_NLM_META_PATH", meta_file)

        mock_account = MagicMock()
        mock_account.at_token = "pool_at"
        mock_pool = MagicMock()
        mock_pool.get_best_account.return_value = mock_account
        mock_pool.get_cookie_header.return_value = "SID=poolcookie"

        from engine.integrations.opal_client import OpalClient
        with patch("engine.integrations.opal_client.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = None
            with patch(
                "engine.integrations.google_account_pool.get_account_pool",
                return_value=mock_pool,
            ):
                client = OpalClient()

        assert client._cookies == "SID=poolcookie"

    def test_load_auth_from_config_fallback(self, tmp_path, monkeypatch) -> None:
        """_load_auth uses config when no cookies available."""
        meta_file = tmp_path / "missing_nlm_meta.json"

        from engine.integrations import opal_client as oc_mod
        monkeypatch.setattr(oc_mod, "_NLM_META_PATH", meta_file)

        from engine.integrations.opal_client import OpalClient
        with patch("engine.integrations.opal_client.get_config") as mock_cfg:
            mock_cfg.return_value.get.side_effect = lambda k, *a: (
                "cfg_at" if "at_token" in k else None
            )
            with patch(
                "engine.integrations.google_account_pool.get_account_pool"
            ) as mock_pool:
                mock_pool.return_value.get_best_account.return_value = None
                client = OpalClient()

        assert client._at_token == "cfg_at"

    def test_refresh_auth_clears_and_reloads(self) -> None:
        """_refresh_auth resets credentials and calls _load_auth."""
        client = _make_client(cookies="old", at_token="old_at")
        with patch.object(client, "_load_auth") as mock_load:
            client._refresh_auth()
        assert client._at_token is None
        assert client._cookies == ""
        mock_load.assert_called_once()


# ──── _get_headers ────────────────────────────────────────────────────────────


class TestOpalGetHeaders:
    """Header construction."""

    def test_get_headers_contains_cookie(self, client) -> None:
        """Cookie header included when cookies are set."""
        headers = client._get_headers()
        assert headers["Cookie"] == "SID=test"

    def test_get_headers_no_cookie_when_empty(self) -> None:
        """Cookie header omitted when cookies string is empty."""
        c = _make_client(cookies="")
        headers = c._get_headers()
        assert "Cookie" not in headers

    def test_get_headers_origin(self, client) -> None:
        """Origin is set to opal.google.com."""
        headers = client._get_headers()
        assert headers["Origin"] == "https://opal.google.com"

    def test_get_headers_xsamedomain(self, client) -> None:
        """X-Same-Domain header is set to '1'."""
        headers = client._get_headers()
        assert headers["X-Same-Domain"] == "1"

    def test_get_headers_referer_default(self, client) -> None:
        """Default referer uses the base Opal URL."""
        headers = client._get_headers()
        assert headers["Referer"].startswith("https://opal.google.com")

    def test_get_headers_referer_custom(self, client) -> None:
        """Custom referer path is appended to base URL."""
        headers = client._get_headers(referer="/gallery")
        assert headers["Referer"] == "https://opal.google.com/gallery"


# ──── _parse_batchexecute_response ────────────────────────────────────────────


class TestOpalParseBatchexecuteResponse:
    """Batchexecute response parsing."""

    def test_parse_extracts_inner_payload(self, client) -> None:
        """Parser extracts inner JSON for matching rpcid."""
        raw = _make_batchexecute_response("ug7pge", ["generated text"])
        result = client._parse_batchexecute_response(raw, "ug7pge")
        assert result == ["generated text"]

    def test_parse_returns_none_for_wrong_rpcid(self, client) -> None:
        """Parser returns None when rpcid doesn't match."""
        raw = _make_batchexecute_response("other_rpc", ["data"])
        result = client._parse_batchexecute_response(raw, "ug7pge")
        assert result is None

    def test_parse_strips_xssi_prefix(self, client) -> None:
        """Parser strips the )]}\' XSSI prefix."""
        inner = {"key": "value"}
        inner_json = json.dumps(inner, separators=(",", ":"))
        chunk = json.dumps([["wrb.fr", "ug7pge", inner_json]], separators=(",", ":"))
        raw = f")]}'\n{chunk}"
        result = client._parse_batchexecute_response(raw, "ug7pge")
        assert result == inner

    def test_parse_handles_empty_response(self, client) -> None:
        """Parser returns None for empty response body."""
        result = client._parse_batchexecute_response("", "ug7pge")
        assert result is None

    def test_parse_handles_malformed_json(self, client) -> None:
        """Parser returns None when JSON is malformed."""
        result = client._parse_batchexecute_response("not json at all", "ug7pge")
        assert result is None


# ──── generate_content ────────────────────────────────────────────────────────


class TestOpalGenerateContent:
    """generate_content (batchexecute ug7pge)."""

    def test_generate_content_calls_batchexecute(self, client) -> None:
        """generate_content calls _batchexecute with ug7pge and correct payload."""
        with patch.object(
            client, "_batchexecute", return_value=["hello world"]
        ) as mock_exec:
            result = client.generate_content("test prompt", style="creative")
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        assert call_args[0][0] == "ug7pge"
        payload = call_args[0][1]
        assert payload[0] == "test prompt"
        assert payload[1] == "creative"

    def test_generate_content_extracts_text_from_list(self, client) -> None:
        """generate_content extracts first element from list response."""
        with patch.object(client, "_batchexecute", return_value=["my content"]):
            result = client.generate_content("prompt")
        assert result["content"] == "my content"

    def test_generate_content_returns_empty_on_none(self, client) -> None:
        """generate_content returns empty content when batchexecute returns None."""
        with patch.object(client, "_batchexecute", return_value=None):
            result = client.generate_content("prompt")
        assert result["content"] == ""

    def test_generate_content_includes_rpcid(self, client) -> None:
        """generate_content result includes rpcid field."""
        with patch.object(client, "_batchexecute", return_value=["text"]):
            result = client.generate_content("prompt")
        assert "rpcid" in result
        assert result["rpcid"] == "ug7pge"

    def test_generate_content_default_style(self, client) -> None:
        """generate_content uses 'default' style when not specified."""
        with patch.object(client, "_batchexecute", return_value=[]) as mock_exec:
            client.generate_content("prompt")
        payload = mock_exec.call_args[0][1]
        assert payload[1] == "default"


# ──── drive_proxy_get ─────────────────────────────────────────────────────────


class TestOpalDriveProxyGet:
    """drive_proxy_get REST endpoint."""

    def test_drive_proxy_get_calls_correct_url(self, client) -> None:
        """drive_proxy_get uses /api/drive-proxy/drive/v3/files/{id} URL."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "file123", "name": "test.opal"}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            result = client.drive_proxy_get("file123")

        call_url = mock_get.call_args[0][0]
        assert "drive-proxy/drive/v3/files/file123" in call_url
        assert result["id"] == "file123"

    def test_drive_proxy_get_raises_on_http_error(self, client) -> None:
        """drive_proxy_get propagates HTTP errors."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                client.drive_proxy_get("missing")

    def test_drive_proxy_get_includes_auth_headers(self, client) -> None:
        """drive_proxy_get passes auth headers."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.drive_proxy_get("abc")
        headers = mock_get.call_args[1]["headers"]
        assert "Cookie" in headers
        assert headers["Cookie"] == "SID=test"


# ──── drive_proxy_list ────────────────────────────────────────────────────────


class TestOpalDriveProxyList:
    """drive_proxy_list REST endpoint."""

    def test_drive_proxy_list_returns_files(self, client) -> None:
        """drive_proxy_list returns the 'files' list from response."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"files": [{"id": "f1"}, {"id": "f2"}]}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.drive_proxy_list(page_size=10)
        assert len(result) == 2

    def test_drive_proxy_list_sends_page_size_param(self, client) -> None:
        """drive_proxy_list passes pageSize query parameter."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"files": []}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.drive_proxy_list(page_size=5)
        params = mock_get.call_args[1]["params"]
        assert params["pageSize"] == 5

    def test_drive_proxy_list_returns_empty_on_missing_key(self, client) -> None:
        """drive_proxy_list returns [] when response has no 'files' key."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.drive_proxy_list()
        assert result == []


# ──── gallery_list ────────────────────────────────────────────────────────────


class TestOpalGalleryList:
    """gallery_list REST endpoint."""

    def test_gallery_list_uses_correct_url(self, client) -> None:
        """gallery_list calls /api/gallery/list."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"items": []}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.gallery_list()
        call_url = mock_get.call_args[0][0]
        assert "/api/gallery/list" in call_url

    def test_gallery_list_sends_category_param(self, client) -> None:
        """gallery_list passes category query parameter when provided."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"items": []}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.gallery_list(category="templates", page_size=10)
        params = mock_get.call_args[1]["params"]
        assert params["category"] == "templates"
        assert params["pageSize"] == 10

    def test_gallery_list_omits_category_when_empty(self, client) -> None:
        """gallery_list does not send category param when empty."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"items": []}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.gallery_list(category="")
        params = mock_get.call_args[1]["params"]
        assert "category" not in params

    def test_gallery_list_handles_list_response(self, client) -> None:
        """gallery_list handles responses that are plain lists."""
        items = [{"id": "a"}, {"id": "b"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = items
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.gallery_list()
        assert result == items

    def test_gallery_list_returns_items_key(self, client) -> None:
        """gallery_list returns the 'items' key from dict responses."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"items": [{"id": "x"}]}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.gallery_list()
        assert result == [{"id": "x"}]


# ──── gallery_get ─────────────────────────────────────────────────────────────


class TestOpalGalleryGet:
    """gallery_get REST endpoint."""

    def test_gallery_get_uses_item_id_in_url(self, client) -> None:
        """gallery_get appends item_id to /api/gallery/list/ URL."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "item42"}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.gallery_get("item42")
        call_url = mock_get.call_args[0][0]
        assert "item42" in call_url

    def test_gallery_get_raises_on_http_error(self, client) -> None:
        """gallery_get propagates HTTP errors."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                client.gallery_get("nonexistent")


# ──── Singleton helpers ────────────────────────────────────────────────────────


class TestOpalSingleton:
    """get_opal_client / reset_opal_client helpers."""

    def test_get_opal_client_returns_instance(self) -> None:
        """get_opal_client returns an OpalClient."""
        from engine.integrations.opal_client import (
            OpalClient,
            get_opal_client,
            reset_opal_client,
        )
        reset_opal_client()
        with patch.object(OpalClient, "_load_auth"):
            inst = get_opal_client()
        assert isinstance(inst, OpalClient)
        reset_opal_client()

    def test_get_opal_client_is_singleton(self) -> None:
        """get_opal_client returns the same instance on repeated calls."""
        from engine.integrations.opal_client import (
            OpalClient,
            get_opal_client,
            reset_opal_client,
        )
        reset_opal_client()
        with patch.object(OpalClient, "_load_auth"):
            a = get_opal_client()
            b = get_opal_client()
        assert a is b
        reset_opal_client()

    def test_reset_opal_client_clears_singleton(self) -> None:
        """reset_opal_client forces a new instance to be created."""
        from engine.integrations.opal_client import (
            OpalClient,
            get_opal_client,
            reset_opal_client,
        )
        reset_opal_client()
        with patch.object(OpalClient, "_load_auth"):
            a = get_opal_client()
        reset_opal_client()
        with patch.object(OpalClient, "_load_auth"):
            b = get_opal_client()
        assert a is not b
        reset_opal_client()


# ──── _batchexecute HTTP layer ─────────────────────────────────────────────────


class TestOpalBatchexecute:
    """_batchexecute constructs correct HTTP request."""

    def test_batchexecute_posts_to_correct_url(self, client) -> None:
        """_batchexecute POSTs to the Opal batchexecute endpoint."""
        raw = _make_batchexecute_response("ug7pge", ["result"])
        mock_resp = MagicMock()
        mock_resp.text = raw
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            client._batchexecute("ug7pge", ["payload"])
        call_url = mock_post.call_args[0][0]
        assert "opal.google.com" in call_url
        assert "ug7pge" in call_url

    def test_batchexecute_includes_at_token(self, client) -> None:
        """_batchexecute includes 'at' token in POST body."""
        raw = _make_batchexecute_response("ug7pge", [])
        mock_resp = MagicMock()
        mock_resp.text = raw
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            client._batchexecute("ug7pge", [])
        body = mock_post.call_args[1]["data"]
        parsed = dict(urllib.parse.parse_qsl(body))
        assert "at" in parsed
        assert parsed["at"] == "test_at"

    def test_batchexecute_raises_on_http_error(self, client) -> None:
        """_batchexecute propagates HTTPError."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("403")
        with patch.object(client._session, "post", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                client._batchexecute("ug7pge", [])
