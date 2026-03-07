"""Tests for the HAR-based Colab and NLM direct client stack.

import pytest
pytestmark = pytest.mark.integration

Covers:
- HAR extraction (cookies, authuser, at token)
- GoogleAccountPool (import, rotation, rate limiting, cookie header)
- ColabClient (SAPISIDHASH, AI agent flow, kernel session)
- NLMDirectClient (response parsing, request building)
- Colab skill pack
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest
import requests


# ──── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_har_data() -> Dict[str, Any]:
    """Minimal HAR structure with Google cookies and auth headers."""
    return {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "url": "https://colab.research.google.com/$rpc/test",
                        "headers": [
                            {"name": "x-goog-authuser", "value": "0"},
                            {"name": "Cookie", "value": (
                                "SID=test_sid; "
                                "__Secure-1PSID=test_1psid; "
                                "__Secure-3PSID=test_3psid; "
                                "HSID=test_hsid; "
                                "SSID=test_ssid; "
                                "APISID=test_apisid; "
                                "SAPISID=test_sapisid; "
                                "__Secure-1PAPISID=test_1papisid; "
                                "__Secure-3PAPISID=test_3papisid; "
                                "OSID=test_osid; "
                                "__Secure-OSID=test_secure_osid; "
                                "__Secure-BUCKET=test_bucket; "
                                "SIDCC=test_sidcc; "
                                "__Secure-1PSIDCC=test_1psidcc; "
                                "__Secure-3PSIDCC=test_3psidcc; "
                                "__Secure-1PSIDTS=test_1psidts; "
                                "__Secure-1PSIDRTS=test_1psidrts; "
                                "__Secure-3PSIDTS=test_3psidts; "
                                "__Secure-3PSIDRTS=test_3psidrts; "
                                "AEC=test_aec; "
                                "NID=test_nid; "
                                "LSID=test_lsid; "
                                "CONSENT=test_consent; "
                                "SEARCH_SAMESITE=test_search_samesite"
                            )},
                        ],
                        "cookies": [
                            {"name": "SID", "value": "test_sid"},
                            {"name": "__Secure-1PSID", "value": "test_1psid"},
                            {"name": "__Secure-3PSID", "value": "test_3psid"},
                            {"name": "HSID", "value": "test_hsid"},
                            {"name": "SSID", "value": "test_ssid"},
                            {"name": "APISID", "value": "test_apisid"},
                            {"name": "SAPISID", "value": "test_sapisid"},
                            {"name": "__Secure-1PAPISID", "value": "test_1papisid"},
                            {"name": "__Secure-3PAPISID", "value": "test_3papisid"},
                            {"name": "OSID", "value": "test_osid"},
                            {"name": "__Secure-OSID", "value": "test_secure_osid"},
                            {"name": "__Secure-BUCKET", "value": "test_bucket"},
                            {"name": "SIDCC", "value": "test_sidcc"},
                            {"name": "__Secure-1PSIDCC", "value": "test_1psidcc"},
                            {"name": "__Secure-3PSIDCC", "value": "test_3psidcc"},
                            {"name": "__Secure-1PSIDTS", "value": "test_1psidts"},
                            {"name": "__Secure-1PSIDRTS", "value": "test_1psidrts"},
                            {"name": "__Secure-3PSIDTS", "value": "test_3psidts"},
                            {"name": "__Secure-3PSIDRTS", "value": "test_3psidrts"},
                            {"name": "AEC", "value": "test_aec"},
                            {"name": "NID", "value": "test_nid"},
                            {"name": "LSID", "value": "test_lsid"},
                            {"name": "CONSENT", "value": "test_consent"},
                            {"name": "SEARCH_SAMESITE", "value": "test_search_samesite"},
                        ],
                        "postData": {
                            "mimeType": "application/x-www-form-urlencoded",
                            "text": "at=test_at_token&other=value",
                        },
                        "queryString": [],
                        "headersSize": -1,
                        "bodySize": 100,
                    },
                        "response": {
                            "status": 200,
                            "content": {"text": "[]", "mimeType": "application/json"},
                        },
                    },
                    {
                        "request": {
                            "method": "POST",
                            "url": (
                                "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
                                "?rpcids=wXbhsf&source-path=%2Fnotebook%2Fnb-uuid-123"
                                "&f.sid=-12345&bl=boq_labs-tailwind-frontend_20260305.05_p0"
                            ),
                            "headers": [],
                            "cookies": [],
                            "postData": {
                                "mimeType": "application/x-www-form-urlencoded",
                                "text": "f.req=%5B%5D&at=test_at_token",
                            },
                        },
                        "response": {
                            "status": 200,
                            "content": {"text": "[]", "mimeType": "application/json"},
                        },
                    }
                ]
            }
        }


@pytest.fixture
def har_file(tmp_path, sample_har_data):
    """Write sample HAR data to a temp file and return path."""
    path = tmp_path / "test.har"
    path.write_text(json.dumps(sample_har_data), encoding="utf-8")
    return str(path)


@pytest.fixture
def pool_with_account(tmp_path):
    """GoogleAccountPool with one pre-loaded account."""
    from engine.integrations.google_account_pool import GoogleAccount, GoogleAccountPool

    pool = GoogleAccountPool(pool_path=str(tmp_path / "pool.json"))
    account = GoogleAccount(
        name="testuser",
        cookies={
            "SID": "test_sid",
            "SAPISID": "test_sapisid",
            "__Secure-1PAPISID": "test_1papisid",
            "__Secure-3PAPISID": "test_3papisid",
        },
        authuser=0,
        services=["colab", "notebooklm"],
    )
    pool.add_account(account)
    return pool


# ──── HAR Extractor tests ─────────────────────────────────────────────────────

class TestHARExtractor:
    def test_har_extractor_reads_cookies(self, har_file):
        """HARExtractor.extract_cookies returns all canonical Google auth cookies."""
        from engine.integrations.har_extractor import HARExtractor, COOKIE_NAMES

        extractor = HARExtractor(har_file)
        cookies = extractor.extract_cookies("google.com")

        for name in COOKIE_NAMES:
            assert name in cookies, f"Missing cookie: {name}"
        assert cookies["SID"] == "test_sid"
        assert cookies["SAPISID"] == "test_sapisid"
        assert cookies["NID"] == "test_nid"

    def test_har_extractor_extracts_authuser(self, har_file):
        """HARExtractor.extract_authuser returns integer from x-goog-authuser."""
        from engine.integrations.har_extractor import HARExtractor

        extractor = HARExtractor(har_file)
        assert extractor.extract_authuser() == 0

    def test_har_extractor_extracts_at_token(self, har_file):
        """HARExtractor.extract_at_token finds at= in post body."""
        from engine.integrations.har_extractor import HARExtractor

        extractor = HARExtractor(har_file)
        token = extractor.extract_at_token()
        assert token == "test_at_token"

    def test_har_extractor_to_account_dict(self, har_file):
        """HARExtractor.to_account_dict returns complete dict."""
        from engine.integrations.har_extractor import HARExtractor

        extractor = HARExtractor(har_file)
        result = extractor.to_account_dict("myaccount")

        assert result["name"] == "myaccount"
        assert result["authuser"] == 0
        assert result["at_token"] == "test_at_token"
        assert result["nlm_session"]["bl"] == "boq_labs-tailwind-frontend_20260305.05_p0"
        assert result["nlm_session"]["f_sid"] == "-12345"
        assert len(result["cookies"]) >= 24

    def test_har_extractor_missing_cookies_returns_empty(self, tmp_path):
        """HARExtractor returns empty dict when no cookies found."""
        from engine.integrations.har_extractor import HARExtractor

        har_data = {
            "log": {
                "entries": [
                    {
                        "request": {
                            "method": "GET",
                            "url": "https://example.com/",
                            "headers": [],
                            "cookies": [],
                            "queryString": [],
                            "headersSize": -1,
                            "bodySize": 0,
                        },
                        "response": {"status": 200, "content": {}},
                    }
                ]
            }
        }
        path = tmp_path / "empty.har"
        path.write_text(json.dumps(har_data), encoding="utf-8")

        extractor = HARExtractor(str(path))
        cookies = extractor.extract_cookies("google.com")
        assert cookies == {}

    def test_har_extractor_detects_service_bundles(self, har_file):
        """HARExtractor surfaces service-aware bundle metadata."""
        from engine.integrations.har_extractor import HARExtractor

        extractor = HARExtractor(har_file)
        bundles = extractor.extract_service_bundles()

        assert "colab" in bundles
        assert "notebooklm" in bundles
        assert bundles["notebooklm"]["session"]["bl"] == "boq_labs-tailwind-frontend_20260305.05_p0"
        assert "batchexecute" in bundles["notebooklm"]["protocols"]
        assert bundles["colab"]["cookie_count"] >= 24


class TestGoogleServiceProfiles:
    def test_normalize_google_service_aliases(self):
        """Historical aliases normalize to canonical Google service names."""
        from engine.integrations.google_service_profiles import normalize_google_services

        assert normalize_google_services(["nlm", "google_drive", "gemini", "nlm"]) == [
            "notebooklm",
            "drive",
            "aistudio",
        ]

    def test_detect_google_services_from_har_urls(self, har_file):
        """Registered Google services are detected from HAR request URLs."""
        from engine.integrations.har_extractor import HARExtractor

        extractor = HARExtractor(har_file)
        assert extractor.detect_services() == ["notebooklm", "colab"]


# ──── GoogleAccountPool tests ─────────────────────────────────────────────────

class TestGoogleAccountPool:
    def test_account_pool_import_from_har(self, har_file, tmp_path):
        """import_from_har creates an account with correct cookies."""
        from engine.integrations.google_account_pool import GoogleAccountPool

        pool = GoogleAccountPool(pool_path=str(tmp_path / "pool.json"))
        account = pool.import_from_har(har_file, "testaccount", ["colab"])

        assert account.name == "testaccount"
        assert account.authuser == 0
        assert "colab" in account.services
        assert account.cookies.get("SID") == "test_sid"

    def test_account_pool_import_from_har_normalizes_service_and_persists_nlm_meta(self, har_file, tmp_path):
        """NotebookLM imports normalize aliases and persist session metadata."""
        from engine.integrations.google_account_pool import GoogleAccountPool

        pool_path = tmp_path / "pool.json"
        pool = GoogleAccountPool(pool_path=str(pool_path))
        account = pool.import_from_har(har_file, "testaccount", "nlm")

        assert "notebooklm" in account.services
        assert account.at_token == "test_at_token"
        assert account.nlm_session["bl"] == "boq_labs-tailwind-frontend_20260305.05_p0"
        assert account.service_sessions["notebooklm"]["f_sid"] == "-12345"

        meta_path = tmp_path / "nlm_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["bl"] == "boq_labs-tailwind-frontend_20260305.05_p0"
        assert meta["f_sid"] == "-12345"

        cookies_path = tmp_path / "nlm_cookies.json"
        exported_cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
        assert exported_cookies["SAPISID"] == "test_sapisid"
        assert exported_cookies["OSID"] == "test_osid"

    def test_account_pool_list_accounts_surfaces_service_profiles(self, har_file, tmp_path):
        """Account summaries expose service profile metadata for Nexus/UI surfaces."""
        from engine.integrations.google_account_pool import GoogleAccountPool

        pool = GoogleAccountPool(pool_path=str(tmp_path / "pool.json"))
        pool.import_from_har(har_file, "testaccount")

        accounts = pool.list_accounts()
        assert len(accounts) == 1
        assert "notebooklm" in accounts[0]["service_profiles"]
        assert accounts[0]["service_profiles"]["notebooklm"]["has_session"] is True
        assert "colab" in accounts[0]["detected_services"]

    def test_account_pool_rotation(self, tmp_path):
        """get_account rotates round-robin across eligible accounts."""
        from engine.integrations.google_account_pool import GoogleAccount, GoogleAccountPool

        pool = GoogleAccountPool(pool_path=str(tmp_path / "pool.json"))
        for i in range(3):
            pool.add_account(GoogleAccount(
                name=f"user{i}",
                cookies={"SID": f"sid{i}"},
                services=["colab"],
            ))

        names_seen = [pool.get_account("colab").name for _ in range(6)]
        # Each account should appear twice in 6 calls
        assert names_seen.count("user0") == 2
        assert names_seen.count("user1") == 2
        assert names_seen.count("user2") == 2

    def test_account_pool_rate_limit_skip(self, tmp_path):
        """Rate-limited accounts are skipped in get_account."""
        from engine.integrations.google_account_pool import GoogleAccount, GoogleAccountPool

        pool = GoogleAccountPool(pool_path=str(tmp_path / "pool.json"))
        pool.add_account(GoogleAccount(name="limited", cookies={}, services=["colab"]))
        pool.add_account(GoogleAccount(name="active", cookies={}, services=["colab"]))

        pool.mark_rate_limited("limited", "colab", duration_seconds=3600)

        for _ in range(5):
            account = pool.get_account("colab")
            assert account is not None
            assert account.name == "active"

    def test_account_pool_no_accounts_returns_none(self, tmp_path):
        """get_account returns None when no accounts are available."""
        from engine.integrations.google_account_pool import GoogleAccountPool

        pool = GoogleAccountPool(pool_path=str(tmp_path / "pool.json"))
        assert pool.get_account("colab") is None

    def test_account_pool_cookie_header(self, pool_with_account):
        """get_cookie_header builds a valid Cookie header string."""
        account = pool_with_account.get_by_name("testuser")
        header = pool_with_account.get_cookie_header(account)

        assert "SID=test_sid" in header
        assert "SAPISID=test_sapisid" in header
        parts = header.split("; ")
        for part in parts:
            assert "=" in part

    def test_account_pool_save_load(self, pool_with_account, tmp_path):
        """Pool saves and loads correctly."""
        pool_path = str(tmp_path / "pool.json")
        pool_with_account._path = pool_path
        pool_with_account.save()

        from engine.integrations.google_account_pool import GoogleAccountPool
        pool2 = GoogleAccountPool(pool_path=pool_path)
        assert pool2.get_by_name("testuser") is not None
        assert pool2.get_by_name("testuser").cookies["SID"] == "test_sid"

    def test_mark_available_clears_rate_limit(self, tmp_path):
        """mark_available removes the rate limit."""
        from engine.integrations.google_account_pool import GoogleAccount, GoogleAccountPool

        pool = GoogleAccountPool(pool_path=str(tmp_path / "pool.json"))
        account = GoogleAccount(name="user", cookies={}, services=["colab"])
        pool.add_account(account)

        pool.mark_rate_limited("user", "colab", 9999)
        assert pool.get_account("colab") is None

        pool.mark_available("user", "colab")
        assert pool.get_account("colab") is not None


# ──── ColabClient — SAPISIDHASH tests ────────────────────────────────────────

class TestColabClientAuth:
    def _make_client(self):
        from engine.integrations.google_account_pool import GoogleAccount
        from engine.integrations.colab_client import ColabClient

        account = GoogleAccount(
            name="test",
            cookies={"SAPISID": "abc123sapisid"},
            services=["colab"],
        )
        return ColabClient(account)

    def test_colab_client_sapisidhash_format(self):
        """SAPISIDHASH has format 'SAPISIDHASH {ts}_{sha1hex}'."""
        client = self._make_client()
        result = client._sapisidhash("mysapisid", "https://colab.research.google.com")

        assert result.startswith("SAPISIDHASH ")
        parts = result[len("SAPISIDHASH "):].split("_")
        assert len(parts) == 2
        ts, digest = parts
        assert ts.isdigit()
        assert len(digest) == 40  # SHA-1 hex

    def test_colab_client_sapisidhash_changes_with_time(self):
        """Two SAPISIDHASH calls at different times produce different outputs."""
        client = self._make_client()
        h1 = client._sapisidhash("mysapisid", "https://colab.research.google.com")
        time.sleep(1.1)
        h2 = client._sapisidhash("mysapisid", "https://colab.research.google.com")

        assert h1 != h2

    def test_colab_client_sapisidhash_correct_hash(self):
        """SAPISIDHASH value matches expected SHA-1 computation."""
        client = self._make_client()
        sapisid = "test_sapisid_value"
        origin = "https://colab.research.google.com"

        result = client._sapisidhash(sapisid, origin)
        ts = result.split(" ")[1].split("_")[0]
        expected_digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
        assert result.endswith(f"_{expected_digest}")


# ──── ColabClient — AI Agent tests ───────────────────────────────────────────

class TestColabClientAIAgent:
    def _make_client(self):
        from engine.integrations.google_account_pool import GoogleAccount
        from engine.integrations.colab_client import ColabClient

        account = GoogleAccount(
            name="test",
            cookies={"SAPISID": "sapisid_val", "SID": "sid_val"},
            services=["colab"],
        )
        return ColabClient(account)

    def test_colab_create_task_returns_uuid(self):
        """create_task returns the task UUID from API response."""
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = ["70bdcdb8-c279-4178-82e4-356b9a7fa05f"]
        mock_resp.raise_for_status.return_value = None

        with patch.object(client._session, "post", return_value=mock_resp):
            task_id = client.create_task()

        assert task_id == "70bdcdb8-c279-4178-82e4-356b9a7fa05f"

    def test_colab_update_task_sends_context(self):
        """update_task POSTs context in the correct JSON structure."""
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = ["70bdcdb8-c279-4178-82e4-356b9a7fa05f"]
        mock_resp.raise_for_status.return_value = None

        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            client.update_task("task-uuid", "my context")

        call_kwargs = mock_post.call_args
        body = call_kwargs[1].get("json", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None)
        # Body should start with the task_id
        assert body[0] == "task-uuid"

    def test_colab_query_task_polls_until_done(self):
        """query_task returns None while processing and text when done."""
        client = self._make_client()

        processing_resp = MagicMock()
        processing_resp.json.return_value = ["task-uuid", None, None, 2]
        processing_resp.raise_for_status.return_value = None

        done_resp = MagicMock()
        done_resp.json.return_value = [
            "task-uuid",
            None,
            [[None, None, None, None, None, None, [None, [[None, ["Hello from Gemini"]]]]]],
        ]
        done_resp.raise_for_status.return_value = None

        call_count = [0]
        def mock_post(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return processing_resp
            return done_resp

        with patch.object(client._session, "post", side_effect=mock_post):
            result1 = client.query_task("task-uuid")
            assert result1 is None

            result2 = client.query_task("task-uuid")
            assert result2 is None

            result3 = client.query_task("task-uuid")
            assert result3 is not None
            assert "Hello from Gemini" in result3

    def test_colab_ask_full_flow(self):
        """ask() orchestrates create→update→poll and returns response."""
        client = self._make_client()

        create_resp = MagicMock()
        create_resp.json.return_value = ["task-uuid-123"]
        create_resp.raise_for_status.return_value = None

        update_resp = MagicMock()
        update_resp.json.return_value = ["task-uuid-123"]
        update_resp.raise_for_status.return_value = None

        done_resp = MagicMock()
        done_resp.json.return_value = [
            "task-uuid-123",
            None,
            [[None, None, None, None, None, None, [None, [[None, ["The answer is 42"]]]]]],
        ]
        done_resp.raise_for_status.return_value = None

        responses = [create_resp, update_resp, done_resp]
        idx = [0]
        def side_effect(*args, **kwargs):
            resp = responses[min(idx[0], len(responses) - 1)]
            idx[0] += 1
            return resp

        with patch.object(client._session, "post", side_effect=side_effect):
            result = client.ask("What is the meaning of life?")

        assert "42" in result

    def test_colab_ask_timeout(self):
        """ask() raises TimeoutError when task never completes."""
        client = self._make_client()

        create_resp = MagicMock()
        create_resp.json.return_value = ["task-uuid"]
        create_resp.raise_for_status.return_value = None

        never_done = MagicMock()
        never_done.json.return_value = ["task-uuid", None, None, 2]
        never_done.raise_for_status.return_value = None

        with patch.object(client._session, "post", return_value=never_done):
            with pytest.raises(TimeoutError):
                # Very short timeout for test speed
                client.ask("test", timeout=1)


# ──── ColabClient — Kernel session tests ─────────────────────────────────────

class TestColabClientKernel:
    def _make_client(self):
        from engine.integrations.google_account_pool import GoogleAccount
        from engine.integrations.colab_client import ColabClient

        account = GoogleAccount(
            name="test",
            cookies={"SAPISID": "sapisid"},
            services=["colab"],
        )
        return ColabClient(account)

    def test_colab_create_kernel_session(self):
        """create_kernel_session returns (session_id, kernel_id)."""
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": "sess-123",
            "kernel": {"id": "kern-456", "name": "python3", "last_activity": ""},
        }
        mock_resp.raise_for_status.return_value = None

        with patch.object(client._session, "post", return_value=mock_resp):
            sess_id, kern_id = client.create_kernel_session(
                "https://8080-test.runtime.dev",
                "jwt-proxy-token",
                "test.ipynb",
            )

        assert sess_id == "sess-123"
        assert kern_id == "kern-456"

    def test_colab_execute_code_collects_output(self):
        """execute_code collects stream messages into output string."""
        client = self._make_client()

        # Mock the async execution
        async def fake_exec(*args, **kwargs):
            return {"output": "Hello, World!\n", "error": None, "status": "ok"}

        with patch.object(client, "_execute_code_async", fake_exec):
            import asyncio
            result = asyncio.run(client._execute_code_async(
                "https://rt.dev", "kern-id", "token", "print('Hello, World!')", 30
            ))

        assert result["output"] == "Hello, World!\n"
        assert result["error"] is None
        assert result["status"] == "ok"


# ──── NLM Direct Client tests ─────────────────────────────────────────────────

class TestNLMDirectClient:
    def _make_client(self):
        from engine.integrations.google_account_pool import GoogleAccount
        from engine.integrations.nlm_direct_client import NLMDirectClient

        account = GoogleAccount(
            name="test",
            cookies={
                "SID": "sid",
                "SAPISID": "sapisid",
                "__Secure-3PSID": "3psid",
            },
            services=["notebooklm"],
        )
        return NLMDirectClient(account)

    def test_nlm_parse_response_strips_xssi(self):
        """_parse_response strips the )]}' XSSI prefix and extracts text."""
        client = self._make_client()

        inner_text = "Here is the NotebookLM answer text."
        inner_json = json.dumps([[inner_text, None, ["src-1"], None, None]])
        outer = json.dumps([["wrb.fr", None, inner_json]])
        xssi = ")" + "]}" + "'"
        raw = f"{xssi}\n1234\n{outer}\n"

        result = client._parse_response(raw)
        assert result == inner_text

    def test_nlm_parse_response_last_chunk_wins(self):
        """_parse_response returns the last wrb.fr text in multi-chunk response."""
        client = self._make_client()

        def make_chunk(text: str) -> str:
            inner = json.dumps([[text, None, ["s1"], None, None]])
            return json.dumps([["wrb.fr", None, inner]])

        xssi = ")" + "]}" + "'"
        raw = f"{xssi}\n500\n{make_chunk('first answer')}\n600\n{make_chunk('second answer')}\n"
        result = client._parse_response(raw)
        assert result == "second answer"

    def test_nlm_ask_builds_correct_request(self):
        """ask() sends form-encoded body with f.req= containing source UUIDs."""
        client = self._make_client()
        client._bl = "boq_test_label"
        client._f_sid = "-12345"

        captured_body = {}

        def mock_post(url, headers=None, data=None, **kwargs):
            captured_body["data"] = data
            captured_body["url"] = url
            mock_resp = MagicMock()
            inner_text = "Test NLM answer"
            inner_json = json.dumps([[inner_text, None, [], None, None]])
            outer = json.dumps([["wrb.fr", None, inner_json]])
            mock_resp.text = (")" + "]}" + "'") + "\n100\n" + outer + "\n"
            mock_resp.raise_for_status.return_value = None
            return mock_resp

        with patch.object(client._session, "post", side_effect=mock_post):
            result = client.ask(
                notebook_id="nb-uuid-123",
                source_ids=["src-uuid-1", "src-uuid-2"],
                question="What is this about?",
            )

        assert result == "Test NLM answer"
        assert captured_body["data"].startswith("f.req=")
        assert "boq_test_label" in captured_body["url"]

        # Verify the decoded body contains source UUIDs
        import urllib.parse
        decoded = urllib.parse.unquote(captured_body["data"][len("f.req="):])
        outer = json.loads(decoded)
        inner_str = outer[1]
        inner = json.loads(inner_str)
        source_list = inner[0]
        source_ids_extracted = [item[0][0] for item in source_list]
        assert "src-uuid-1" in source_ids_extracted
        assert "src-uuid-2" in source_ids_extracted
        assert inner[2] == "What is this about?"
        assert inner[3] == "nb-uuid-123"

    def test_nlm_ask_returns_text(self):
        """ask() returns the extracted answer text."""
        client = self._make_client()
        client._bl = "boq_labs_label"
        client._f_sid = "999"

        def mock_post(*args, **kwargs):
            inner_text = "NotebookLM says: This is important."
            inner_json = json.dumps([[inner_text, None, ["src1"], None, None]])
            outer = json.dumps([["wrb.fr", None, inner_json]])
            resp = MagicMock()
            resp.text = (")" + "]}" + "'") + "\n200\n" + outer + "\n"
            resp.raise_for_status.return_value = None
            return resp

        with patch.object(client._session, "post", side_effect=mock_post):
            result = client.ask("nb-id", ["src1"], "Summarize this.")

        assert result == "NotebookLM says: This is important."


# ──── Skill tests ─────────────────────────────────────────────────────────────

class TestColabSkills:
    def test_colab_skill_ask(self):
        """colab_ask skill calls ColabClient.ask and returns result."""
        from engine.skills.builtin.colab_skills import colab_ask
        from engine.integrations.colab_client import ColabClient

        mock_client = MagicMock(spec=ColabClient)
        mock_client.ask.return_value = "Gemini response here"

        with patch("engine.integrations.colab_client.get_account_pool") as mock_pool_fn:
            mock_pool = MagicMock()
            mock_pool.get_account.return_value = MagicMock(name="test", cookies={}, authuser=0, services=["colab"])
            mock_pool.get_by_name.return_value = None
            mock_pool.get_cookie_header.return_value = "SID=x"
            mock_pool_fn.return_value = mock_pool
            with patch("engine.integrations.colab_client.ColabClient", return_value=mock_client):
                result = colab_ask("What is 2+2?", context="math context")

        assert result == "Gemini response here"

    def test_colab_skill_ask_no_account(self):
        """colab_ask returns informative message when no account available."""
        from engine.skills.builtin.colab_skills import colab_ask

        with patch("engine.integrations.colab_client.get_account_pool") as mock_pool_fn:
            mock_pool = MagicMock()
            mock_pool.get_account.return_value = None
            mock_pool.get_by_name.return_value = None
            mock_pool_fn.return_value = mock_pool
            result = colab_ask("test prompt")

        assert "No Colab account" in result

    def test_colab_skill_status(self):
        """colab_status returns JSON with hardware and account info."""
        from engine.skills.builtin.colab_skills import colab_status

        mock_client = MagicMock()
        mock_client.get_user_info.return_value = {
            "free_tiers": {1: ["T4"]},
            "pro_tiers": {1: ["H100"]},
            "compute_units": "6000",
        }
        mock_client.list_assignments.return_value = [{"runtime_id": "rt-1"}]

        with patch("engine.integrations.google_account_pool.get_account_pool") as mock_pool_fn:
            mock_pool = MagicMock()
            mock_pool.list_accounts.return_value = [
                {"name": "nihilistcod", "services": ["colab"], "cookie_count": 14}
            ]
            mock_pool.get_account.return_value = MagicMock(name="t", cookies={}, authuser=0, services=["colab"])
            mock_pool.get_by_name.return_value = None
            mock_pool.get_cookie_header.return_value = "SID=x"
            mock_pool_fn.return_value = mock_pool
            with patch("engine.integrations.colab_client.get_account_pool", return_value=mock_pool):
                with patch("engine.integrations.colab_client.ColabClient", return_value=mock_client):
                    result = colab_status()

        data = json.loads(result)
        assert "hardware" in data
        assert data["active_runtimes"] == 1

    def test_nlm_direct_skill(self):
        """nlm_direct_ask skill calls NLMDirectClient.ask with parsed source IDs."""
        from engine.skills.builtin.colab_skills import nlm_direct_ask
        from engine.integrations.nlm_direct_client import NLMDirectClient

        mock_client = MagicMock(spec=NLMDirectClient)
        mock_client.ask.return_value = "NLM answer"

        with patch("engine.integrations.nlm_direct_client.get_account_pool") as mock_pool_fn:
            mock_pool = MagicMock()
            mock_pool.get_account.return_value = MagicMock(name="t", cookies={}, authuser=0, services=["notebooklm"])
            mock_pool.get_by_name.return_value = None
            mock_pool.get_cookie_header.return_value = "SID=x"
            mock_pool_fn.return_value = mock_pool
            with patch("engine.integrations.nlm_direct_client.NLMDirectClient", return_value=mock_client):
                result = nlm_direct_ask(
                    notebook_id="nb-123",
                    source_ids="src-1, src-2, src-3",
                    question="Tell me about this.",
                )

        assert result == "NLM answer"
        mock_client.ask.assert_called_once_with(
            "nb-123", ["src-1", "src-2", "src-3"], "Tell me about this."
        )

    def test_nlm_direct_skill_no_account(self):
        """nlm_direct_ask returns informative message when no account available."""
        from engine.skills.builtin.colab_skills import nlm_direct_ask

        with patch("engine.integrations.nlm_direct_client.get_account_pool") as mock_pool_fn:
            mock_pool = MagicMock()
            mock_pool.get_account.return_value = None
            mock_pool.get_by_name.return_value = None
            mock_pool_fn.return_value = mock_pool
            result = nlm_direct_ask("nb-id", "src-1", "question?")

        assert "No NotebookLM account" in result
