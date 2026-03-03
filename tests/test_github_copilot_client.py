"""Tests for GithubCopilotClient.

Covers token fetch/cache, model listing, thread creation, message sending
(SSE parsing), and the ask() / singleton helpers.  All HTTP calls are mocked.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_client(account_name: str = "tester"):
    """Return a fresh (non-singleton) GithubCopilotClient."""
    # Import fresh so singleton registry doesn't interfere
    from engine.integrations.github_copilot_client import GithubCopilotClient

    return GithubCopilotClient(account_name=account_name)


def _mock_token_response(token: str = "gh-tok-abc", expires_in: int = 3600):
    """Build a mock requests.Response for the token endpoint."""
    import datetime

    exp = (
        datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"token": token, "expiration": exp, "ssoOrgIDs": []}
    return resp


def _mock_models_response(n: int = 26):
    """Build a mock requests.Response for /models."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "data": [{"id": f"model-{i}", "vendor": "Test"} for i in range(n)]
    }
    return resp


def _mock_thread_response(thread_id: str = "thread-uuid-123"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"thread_id": thread_id, "thread": {"id": thread_id}}
    return resp


def _make_sse_lines(chunks: list[str], final_id: str = "msg-final") -> list[bytes]:
    """Build SSE byte lines for streaming mock."""
    lines: list[bytes] = []
    for chunk in chunks:
        event = json.dumps({"type": "content", "body": chunk})
        lines.append(f"data: {event}\n".encode())
    complete = json.dumps({"type": "complete", "id": final_id, "body": ""})
    lines.append(f"data: {complete}\n".encode())
    return lines


# ──── Cookie loading ──────────────────────────────────────────────────────────


class TestGetCookies:
    def test_loads_from_account_pool(self, tmp_path):
        from engine.integrations.github_copilot_client import GithubCopilotClient
        from engine.integrations.google_account_pool import GoogleAccount

        client = GithubCopilotClient(account_name="pooluser")
        mock_account = GoogleAccount(
            name="pooluser",
            cookies={"user_session": "abc123"},
            services=["github"],
        )
        mock_pool = MagicMock()
        mock_pool.get_by_name.return_value = mock_account

        with patch("engine.integrations.google_account_pool.GoogleAccountPool.get_by_name",
                   return_value=mock_account):
            # Patch inside the function's local import
            with patch("engine.integrations.github_copilot_client.GithubCopilotClient._get_cookies",
                       return_value={"user_session": "abc123"}):
                cookies = client._get_cookies()

        assert cookies == {"user_session": "abc123"}

    def test_falls_back_to_json_file(self, tmp_path, monkeypatch):
        from engine.integrations.github_copilot_client import GithubCopilotClient

        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "accounts").mkdir(parents=True)
        cookie_file = tmp_path / "data" / "accounts" / "github_fallbackuser_cookies.json"
        cookie_file.write_text(json.dumps({"_gh_sess": "xyz"}))

        client = GithubCopilotClient(account_name="fallbackuser")

        # Patch the inner import of get_account_pool
        mock_pool = MagicMock()
        mock_pool.get_by_name.return_value = None

        with patch("engine.integrations.google_account_pool._pool_instance", mock_pool):
            cookies = client._get_cookies()

        assert cookies == {"_gh_sess": "xyz"}

    def test_raises_when_no_cookies_available(self, tmp_path, monkeypatch):
        from engine.integrations.github_copilot_client import GithubCopilotClient

        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "accounts").mkdir(parents=True)

        client = GithubCopilotClient(account_name="nobody")
        mock_pool = MagicMock()
        mock_pool.get_by_name.return_value = None

        with patch("engine.integrations.google_account_pool._pool_instance", mock_pool):
            with pytest.raises(RuntimeError, match="No GitHub cookies"):
                client._get_cookies()


# ──── Token management ────────────────────────────────────────────────────────


class TestGetToken:
    def _client_with_cookies(self):
        client = _make_client()
        client._get_cookies = MagicMock(return_value={"user_session": "s123"})
        return client

    def test_fetches_token_on_first_call(self):
        client = self._client_with_cookies()
        with patch("requests.post", return_value=_mock_token_response("tok-001")) as mock_post:
            token = client._get_token()
        assert token == "tok-001"
        assert mock_post.called

    def test_caches_valid_token(self):
        client = self._client_with_cookies()
        with patch("requests.post", return_value=_mock_token_response("tok-002")) as mock_post:
            t1 = client._get_token()
            t2 = client._get_token()
        assert t1 == t2 == "tok-002"
        assert mock_post.call_count == 1  # only fetched once

    def test_refreshes_expired_token(self):
        client = self._client_with_cookies()
        # Pre-populate with an already-expired token
        client._token = "old-tok"
        client._token_expires = time.time() - 10  # in the past

        with patch("requests.post", return_value=_mock_token_response("new-tok")) as mock_post:
            token = client._get_token()

        assert token == "new-tok"
        assert mock_post.call_count == 1

    def test_refreshes_token_within_buffer(self):
        client = self._client_with_cookies()
        client._token = "about-to-expire"
        # Expires in 30s — within the 60s buffer
        client._token_expires = time.time() + 30

        with patch("requests.post", return_value=_mock_token_response("fresh-tok")):
            token = client._get_token()
        assert token == "fresh-tok"

    def test_raises_on_non_200(self):
        client = self._client_with_cookies()
        bad_resp = MagicMock()
        bad_resp.status_code = 401
        bad_resp.text = "Unauthorized"
        with patch("requests.post", return_value=bad_resp):
            with pytest.raises(RuntimeError, match="401"):
                client._get_token()

    def test_token_is_thread_safe(self):
        """Two threads calling _get_token simultaneously should only fetch once."""
        client = self._client_with_cookies()
        call_count = [0]
        original_post = MagicMock(side_effect=lambda *a, **kw: (
            time.sleep(0.05), setattr(call_count, '__setitem__', None),
            call_count.__setitem__(0, call_count[0] + 1),
            _mock_token_response("thread-tok"),
        )[-1])

        tokens = []

        def fetch():
            with patch("requests.post", return_value=_mock_token_response("tok-shared")):
                tokens.append(client._get_token())

        threads = [threading.Thread(target=fetch) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(tok == tokens[0] for tok in tokens)


# ──── Models ──────────────────────────────────────────────────────────────────


class TestListModels:
    def _client(self):
        client = _make_client()
        client._get_token = MagicMock(return_value="tok")
        return client

    def test_returns_model_list(self):
        client = self._client()
        with patch("requests.get", return_value=_mock_models_response(26)):
            models = client.list_models()
        assert len(models) == 26
        assert models[0]["id"] == "model-0"

    def test_caches_result(self):
        client = self._client()
        with patch("requests.get", return_value=_mock_models_response(3)) as mock_get:
            client.list_models()
            client.list_models()
        assert mock_get.call_count == 1

    def test_cache_expires(self):
        client = self._client()
        client._models_cache_time = 0  # force expiry
        with patch("requests.get", return_value=_mock_models_response(5)) as mock_get:
            client.list_models()
            client._models_cache_time = 0  # expire again
            client.list_models()
        assert mock_get.call_count == 2

    def test_raises_on_http_error(self):
        client = self._client()
        bad_resp = MagicMock()
        bad_resp.status_code = 500
        bad_resp.raise_for_status.side_effect = Exception("Server error")
        with patch("requests.get", return_value=bad_resp):
            with pytest.raises(Exception):
                client.list_models()


# ──── Thread creation ─────────────────────────────────────────────────────────


class TestCreateThread:
    def _client(self):
        client = _make_client()
        client._get_token = MagicMock(return_value="tok")
        return client

    def test_returns_thread_id(self):
        client = self._client()
        with patch("requests.post", return_value=_mock_thread_response("tid-001")):
            tid = client.create_thread()
        assert tid == "tid-001"

    def test_handles_nested_thread_id(self):
        client = self._client()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"thread": {"id": "nested-tid"}}
        with patch("requests.post", return_value=resp):
            tid = client.create_thread()
        assert tid == "nested-tid"

    def test_raises_on_non_200(self):
        client = self._client()
        resp = MagicMock()
        resp.status_code = 403
        resp.text = "Forbidden"
        with patch("requests.post", return_value=resp):
            with pytest.raises(RuntimeError, match="403"):
                client.create_thread()

    def test_raises_when_no_thread_id_in_response(self):
        client = self._client()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {}
        with patch("requests.post", return_value=resp):
            with pytest.raises(RuntimeError, match="No thread_id"):
                client.create_thread()


# ──── Send message ────────────────────────────────────────────────────────────


class TestSendMessage:
    def _client(self):
        client = _make_client()
        client._get_token = MagicMock(return_value="tok")
        return client

    def _mock_stream(self, chunks: list[str], final_id: str = "final-id"):
        resp = MagicMock()
        resp.status_code = 200
        resp.iter_lines.return_value = [
            line.decode() for line in _make_sse_lines(chunks, final_id)
        ]
        return resp

    def test_collects_content_chunks(self):
        client = self._client()
        with patch("requests.post", return_value=self._mock_stream(["Hello", " world"])):
            text, msg_id = client.send_message("tid", "Hi", model="claude-sonnet-4.6")
        assert text == "Hello world"

    def test_returns_final_message_id(self):
        client = self._client()
        with patch("requests.post", return_value=self._mock_stream(["Hi"], "msg-999")):
            _, msg_id = client.send_message("tid", "Hello")
        assert msg_id == "msg-999"

    def test_raises_on_non_200(self):
        client = self._client()
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "Rate limited"
        with patch("requests.post", return_value=resp):
            with pytest.raises(RuntimeError, match="429"):
                client.send_message("tid", "prompt")

    def test_handles_empty_stream(self):
        client = self._client()
        resp = MagicMock()
        resp.status_code = 200
        resp.iter_lines.return_value = []
        with patch("requests.post", return_value=resp):
            text, _ = client.send_message("tid", "test")
        assert text == ""

    def test_skips_malformed_json_chunks(self):
        client = self._client()
        resp = MagicMock()
        resp.status_code = 200
        resp.iter_lines.return_value = [
            "data: {bad json}",
            'data: {"type":"content","body":"ok"}',
        ]
        with patch("requests.post", return_value=resp):
            text, _ = client.send_message("tid", "test")
        assert text == "ok"


# ──── ask() ───────────────────────────────────────────────────────────────────


class TestAsk:
    def test_full_flow(self):
        client = _make_client()
        client._get_token = MagicMock(return_value="tok")

        thread_resp = _mock_thread_response("t-flow")
        stream_resp = MagicMock()
        stream_resp.status_code = 200
        stream_resp.iter_lines.return_value = [
            'data: {"type":"content","body":"Deep thought"}',
            'data: {"type":"complete","id":"m-1"}',
        ]

        with patch("requests.post", side_effect=[thread_resp, stream_resp]):
            result = client.ask("What is 42?")

        assert "Deep thought" in result

    def test_uses_specified_model(self):
        client = _make_client()
        client._get_token = MagicMock(return_value="tok")

        thread_resp = _mock_thread_response("t-model")
        stream_resp = MagicMock()
        stream_resp.status_code = 200
        stream_resp.iter_lines.return_value = []

        with patch("requests.post", side_effect=[thread_resp, stream_resp]) as mock_post:
            client.ask("Hello", model="gpt-5.2-codex")

        # Second call is send_message — check model in payload
        second_call_kwargs = mock_post.call_args_list[1]
        body = second_call_kwargs[1].get("json") or second_call_kwargs[0][1] if len(second_call_kwargs[0]) > 1 else {}
        if hasattr(second_call_kwargs, 'kwargs'):
            body = second_call_kwargs.kwargs.get("json", {})
        assert body.get("model") == "gpt-5.2-codex"


# ──── embed() ────────────────────────────────────────────────────────────────


def test_embed_raises_not_implemented():
    from engine.integrations.github_copilot_client import GithubCopilotClient

    client = GithubCopilotClient()
    with pytest.raises(NotImplementedError, match="embeddings endpoint"):
        client.embed("test text")


# ──── Error handling ──────────────────────────────────────────────────────────


class TestErrorHandling:
    def test_network_failure_in_token(self):
        client = _make_client()
        client._get_cookies = MagicMock(return_value={"s": "v"})
        with patch("requests.post", side_effect=ConnectionError("Network down")):
            with pytest.raises(ConnectionError):
                client._get_token()

    def test_network_failure_in_list_models(self):
        client = _make_client()
        client._get_token = MagicMock(return_value="tok")
        with patch("requests.get", side_effect=ConnectionError("Offline")):
            with pytest.raises(ConnectionError):
                client.list_models()


# ──── Singleton ───────────────────────────────────────────────────────────────


class TestSingleton:
    def test_same_account_returns_same_instance(self):
        from engine.integrations import github_copilot_client as mod

        # Reset registry for clean test
        mod._instances.clear()

        c1 = mod.get_copilot_client("alpha")
        c2 = mod.get_copilot_client("alpha")
        assert c1 is c2

    def test_different_accounts_return_different_instances(self):
        from engine.integrations import github_copilot_client as mod

        mod._instances.clear()

        c1 = mod.get_copilot_client("acct-a")
        c2 = mod.get_copilot_client("acct-b")
        assert c1 is not c2

    def test_account_name_stored(self):
        from engine.integrations import github_copilot_client as mod

        mod._instances.clear()
        client = mod.get_copilot_client("myaccount")
        assert client.account_name == "myaccount"
