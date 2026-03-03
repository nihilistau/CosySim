"""Tests for engine.nexus.aistudio_client."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.aistudio_client import AiStudioClient, _DEFAULT_MODEL, _TOKEN_TTL
from engine.nexus.google_account_manager import GoogleAccountManager


# ──── Helpers ────

def _make_manager(tmp_path: Path) -> GoogleAccountManager:
    """Create a GoogleAccountManager with a fake account loaded."""
    mgr = GoogleAccountManager(data_dir=tmp_path / "accounts")
    acct_dir = mgr._data_dir / "fake_account"
    acct_dir.mkdir(parents=True, exist_ok=True)
    data: Dict[str, Any] = {
        "account_id": "fake_account",
        "service": "aistudio",
        "cookies": {
            "SAPISID": "fake_sapisid_value",
            "SID": "fake_sid",
        },
        "api_keys": {"aistudio": "AIza_fake_key"},
        "imported_at": time.time(),
        "last_used": None,
        "rate_limited_until": None,
        "request_count": 0,
    }
    (acct_dir / "cookies.json").write_text(json.dumps(data), encoding="utf-8")
    return mgr


def _make_client(tmp_path: Path) -> AiStudioClient:
    """Create an AiStudioClient backed by a fake account."""
    mgr = _make_manager(tmp_path)
    return AiStudioClient(manager=mgr)


# ──── Fixtures ────

@pytest.fixture
def client(tmp_path: Path) -> AiStudioClient:
    """AiStudioClient with isolated temp manager."""
    return _make_client(tmp_path)


# ──── Tests ────

def test_generate_calls_gemini_endpoint(client: AiStudioClient) -> None:
    """generate() should POST to the Gemini API generateContent endpoint."""
    token = "ya29.fake_token"
    gemini_response = {
        "candidates": [{"content": {"parts": [{"text": "Hello from Gemini"}]}}]
    }

    with (
        patch.object(client, "generate_access_token", return_value=token),
        patch("urllib.request.urlopen") as mock_open,
    ):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(gemini_response).encode()
        mock_open.return_value = mock_resp

        result = client.generate("Say hello", account_id="fake_account")

    assert result == "Hello from Gemini"
    call_args = mock_open.call_args[0][0]
    assert "generateContent" in call_args.full_url


def test_generate_access_token_caches_result(client: AiStudioClient) -> None:
    """generate_access_token should not call RPC again while token is fresh."""
    token = "ya29.cached_token"

    with patch.object(client, "_rpc", return_value=[token]) as mock_rpc:
        t1 = client.generate_access_token(account_id="fake_account")
        t2 = client.generate_access_token(account_id="fake_account")

    assert t1 == token
    assert t2 == token
    # RPC should only be called once
    assert mock_rpc.call_count == 1


def test_list_models_parses_response(client: AiStudioClient) -> None:
    """list_models should parse the nested list into dicts."""
    raw_response = [
        [
            ["gemini-2.0-flash", None, "001", "Gemini 2.0 Flash", "Fast model", 1000000, 8192],
            ["gemini-1.5-pro", None, "002", "Gemini 1.5 Pro", "Pro model", 2000000, 8192],
        ]
    ]

    with patch.object(client, "_rpc", return_value=raw_response):
        models = client.list_models(account_id="fake_account")

    assert len(models) == 2
    assert models[0]["id"] == "gemini-2.0-flash"
    assert models[0]["name"] == "Gemini 2.0 Flash"
    assert models[0]["context_window"] == 1000000


def test_rpc_sends_correct_headers(client: AiStudioClient) -> None:
    """_rpc should include SAPISIDHASH and X-Goog-Api-Key in the request."""
    captured_headers: Dict[str, str] = {}

    def fake_urlopen(req: Any, timeout: int = 30):
        captured_headers.update(req.headers)
        raise Exception("abort after capture")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client._rpc("ListModels", [], account_id="fake_account")

    # urllib lowercases header names after the first character
    header_keys_lower = {k.lower() for k in captured_headers}
    assert "authorization" in header_keys_lower
    assert "x-goog-api-key" in header_keys_lower


def test_rate_limit_marks_account(client: AiStudioClient, tmp_path: Path) -> None:
    """A 429 HTTP error from _rpc should mark the current account as rate-limited."""
    import urllib.error

    mock_err = urllib.error.HTTPError(
        url="http://x", code=429, msg="Too Many Requests", hdrs=None, fp=None
    )
    with patch("urllib.request.urlopen", side_effect=mock_err):
        result = client._rpc("ListModels", [], account_id="fake_account")

    assert result is None
    acct = client._manager._load_account("fake_account")
    assert acct is not None
    assert acct["rate_limited_until"] is not None
    assert acct["rate_limited_until"] > time.time()


def test_headers_include_sapisidhash(client: AiStudioClient) -> None:
    """_get_headers should include an Authorization: SAPISIDHASH ... header."""
    headers = client._get_headers(account_id="fake_account")
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("SAPISIDHASH ")


def test_headers_include_api_key(client: AiStudioClient) -> None:
    """_get_headers should include X-Goog-Api-Key when the account has one."""
    headers = client._get_headers(account_id="fake_account")
    assert "X-Goog-Api-Key" in headers
    assert headers["X-Goog-Api-Key"] == "AIza_fake_key"


def test_generate_with_rotation_tries_next_on_failure(tmp_path: Path) -> None:
    """generate_with_rotation should try the second account if the first fails."""
    mgr = GoogleAccountManager(data_dir=tmp_path / "accounts")

    for aid in ("acct_a", "acct_b"):
        acct_dir = mgr._data_dir / aid
        acct_dir.mkdir(parents=True, exist_ok=True)
        data: Dict[str, Any] = {
            "account_id": aid,
            "service": "aistudio",
            "cookies": {"SAPISID": f"sapisid_{aid}"},
            "api_keys": {"aistudio": "AIza_fake"},
            "imported_at": time.time(),
            "last_used": None,
            "rate_limited_until": None,
            "request_count": 0,
        }
        (acct_dir / "cookies.json").write_text(json.dumps(data))

    client = AiStudioClient(manager=mgr)
    call_count = 0

    def fake_generate(
        prompt: str,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        account_id: Optional[str] = None,
    ) -> Optional[str]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None  # first account fails
        return "success"

    with patch.object(client, "generate", side_effect=fake_generate):
        result = client.generate_with_rotation("prompt")

    assert result == "success"
    assert call_count == 2


def test_generate_returns_none_when_no_accounts(tmp_path: Path) -> None:
    """generate returns None when the account pool is empty."""
    mgr = GoogleAccountManager(data_dir=tmp_path / "empty_accounts")
    client = AiStudioClient(manager=mgr)
    result = client.generate("prompt")
    assert result is None


def test_list_models_returns_empty_on_error(client: AiStudioClient) -> None:
    """list_models returns an empty list when _rpc returns None."""
    with patch.object(client, "_rpc", return_value=None):
        models = client.list_models(account_id="fake_account")
    assert models == []


def test_token_cache_expires_correctly(client: AiStudioClient) -> None:
    """A cached token past its TTL should trigger a fresh RPC call."""
    expired_time = time.time() - 10  # already expired
    client._token_cache["fake_account"] = ("ya29.old_token", expired_time)

    new_token = "ya29.new_token"
    with patch.object(client, "_rpc", return_value=[new_token]) as mock_rpc:
        result = client.generate_access_token(account_id="fake_account")

    assert result == new_token
    mock_rpc.assert_called_once()


def test_generate_parses_response_correctly(client: AiStudioClient) -> None:
    """generate() should correctly navigate the Gemini response structure."""
    token = "ya29.ok"
    response = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Parsed text output"}]
                }
            }
        ]
    }

    with (
        patch.object(client, "generate_access_token", return_value=token),
        patch("urllib.request.urlopen") as mock_open,
    ):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(response).encode()
        mock_open.return_value = mock_resp

        result = client.generate("Test prompt", account_id="fake_account")

    assert result == "Parsed text output"
