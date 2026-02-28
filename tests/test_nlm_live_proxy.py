"""Tests for engine.mcp.nlm_live_proxy and the updated notebooklm_proxy."""
from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────

def _make_har(cookies: list[dict]) -> dict:
    """Build a minimal HAR dict with cookies in the request headers."""
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    return {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://notebooklm.google.com/",
                        "headers": [
                            {"name": "Cookie", "value": cookie_str},
                        ],
                        "cookies": cookies,
                    },
                },
            ]
        }
    }


# ── Cookie extraction ──────────────────────────────────────────────────

class TestCookieExtraction:
    def test_extracts_auth_cookies_from_har(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import extract_cookies_from_har

        har = _make_har([
            {"name": "SID", "value": "test_sid"},
            {"name": "SSID", "value": "test_ssid"},
            {"name": "some_random_cookie", "value": "ignored"},
        ])
        har_file = tmp_path / "test.har"
        har_file.write_text(json.dumps(har), encoding="utf-8")

        result = extract_cookies_from_har(str(har_file))
        assert result.get("SID") == "test_sid"
        assert result.get("SSID") == "test_ssid"
        # non-auth cookies should be filtered out
        assert "some_random_cookie" not in result

    def test_extracts_secure_prefix_cookies(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import extract_cookies_from_har

        har = _make_har([
            {"name": "__Secure-3PAPISID", "value": "secure_value"},
            {"name": "SAPISID", "value": "sapi_value"},
        ])
        har_file = tmp_path / "test2.har"
        har_file.write_text(json.dumps(har), encoding="utf-8")

        result = extract_cookies_from_har(str(har_file))
        assert result.get("__Secure-3PAPISID") == "secure_value"
        assert result.get("SAPISID") == "sapi_value"

    def test_returns_empty_for_non_nlm_entries(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import extract_cookies_from_har

        har = {
            "log": {
                "entries": [
                    {
                        "request": {
                            "url": "https://google.com/",
                            "headers": [{"name": "Cookie", "value": "SID=ignored"}],
                            "cookies": [],
                        },
                    }
                ]
            }
        }
        har_file = tmp_path / "test3.har"
        har_file.write_text(json.dumps(har), encoding="utf-8")
        result = extract_cookies_from_har(str(har_file))
        assert result == {}

    def test_returns_empty_for_missing_file(self) -> None:
        from engine.mcp.nlm_live_proxy import extract_cookies_from_har
        result = extract_cookies_from_har("/nonexistent/path/file.har")
        assert result == {}


# ── Cookie formatting ──────────────────────────────────────────────────

class TestCookieFormatting:
    def test_cookies_header_format(self) -> None:
        from engine.mcp.nlm_live_proxy import _cookies_header
        header = _cookies_header({"SID": "abc", "SSID": "def"})
        assert "SID=abc" in header
        assert "SSID=def" in header
        assert ";" in header

    def test_sapisid_hash_empty_without_sapisid(self) -> None:
        from engine.mcp.nlm_live_proxy import _sapisid_hash
        result = _sapisid_hash({})
        assert result == ""

    def test_sapisid_hash_format(self) -> None:
        from engine.mcp.nlm_live_proxy import _sapisid_hash
        result = _sapisid_hash({"SAPISID": "test_value"})
        assert result.startswith("SAPISIDHASH ")
        parts = result.split(" ")
        assert len(parts) == 2
        ts, digest = parts[1].split("_")
        assert ts.isdigit()
        assert len(digest) == 40  # sha1 hex


# ── batchexecute response parsing ──────────────────────────────────────

class TestBatchexecuteParsing:
    def test_parse_wrb_fr_response(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_batchexecute
        inner = {"key": "value"}
        wrapped = json.dumps([["wrb.fr", "VfAZjd", json.dumps(inner)]])
        raw = ")]}'\n" + wrapped
        rpc_id, data = _parse_batchexecute(raw)
        assert rpc_id == "VfAZjd"
        assert data == inner

    def test_parse_empty_response(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_batchexecute
        rpc_id, data = _parse_batchexecute(")]}'\n\n")
        assert rpc_id is None
        assert data is None

    def test_parse_malformed_response(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_batchexecute
        rpc_id, data = _parse_batchexecute("not valid json at all")
        assert rpc_id is None
        assert data is None


# ── String extraction helpers ──────────────────────────────────────────

class TestExtractStrings:
    def test_extracts_from_nested_list(self) -> None:
        from engine.mcp.nlm_live_proxy import _extract_strings
        long_text = "This is a real sentence with enough length to pass the filter. " * 2
        data = [["short", long_text], [{"key": "another " + "z" * 90}]]
        results = _extract_strings(data)
        assert any(len(r) >= 90 for r in results)

    def test_filters_by_min_len(self) -> None:
        from engine.mcp.nlm_live_proxy import _extract_strings
        long_text = "The quick brown fox jumps over the lazy dog. " * 3  # 135 chars
        results = _extract_strings(["hi", long_text])
        assert "hi" not in results
        assert any(len(r) > 100 for r in results)

    def test_dedup(self) -> None:
        from engine.mcp.nlm_live_proxy import _dedup
        texts = ["abc" + "x" * 150, "abc" + "x" * 150, "def" + "y" * 150]
        result = _dedup(texts)
        assert len(result) == 2


# ── Flask app endpoints ────────────────────────────────────────────────

class TestFlaskEndpoints:
    @pytest.fixture
    def client(self, tmp_path: Path):
        """Create a test Flask client with a mocked cookie store."""
        from engine.mcp.nlm_live_proxy import create_nlm_proxy_app
        import engine.mcp.nlm_live_proxy as proxy_mod

        # Redirect cookie file to tmp
        original = proxy_mod._COOKIES_FILE
        proxy_mod._COOKIES_FILE = tmp_path / "test_cookies.json"
        app = create_nlm_proxy_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c
        proxy_mod._COOKIES_FILE = original

    def test_health_no_cookies(self, client) -> None:
        resp = client.get("/health")
        data = json.loads(resp.data)
        assert resp.status_code == 503
        assert data["has_cookies"] is False

    def test_health_with_cookies(self, client, tmp_path: Path) -> None:
        import engine.mcp.nlm_live_proxy as proxy_mod
        proxy_mod._COOKIES_FILE.write_text(
            json.dumps({"SID": "test", "SSID": "test2"}), encoding="utf-8"
        )
        resp = client.get("/health")
        data = json.loads(resp.data)
        assert resp.status_code == 200
        assert data["has_cookies"] is True
        assert data["cookie_count"] == 2

    def test_cookies_list_empty(self, client) -> None:
        resp = client.get("/cookies")
        data = json.loads(resp.data)
        assert data["count"] == 0
        assert data["has_cookies"] is False

    def test_cookies_clear(self, client, tmp_path: Path) -> None:
        import engine.mcp.nlm_live_proxy as proxy_mod
        proxy_mod._COOKIES_FILE.write_text(
            json.dumps({"SID": "test"}), encoding="utf-8"
        )
        resp = client.delete("/cookies")
        assert resp.status_code == 200
        assert not proxy_mod._COOKIES_FILE.exists() or \
               json.loads(proxy_mod._COOKIES_FILE.read_text()) == {}

    def test_import_cookies_missing_file(self, client) -> None:
        resp = client.post(
            "/cookies/import",
            json={"har_path": "/nonexistent/path.har"},
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_notebooks_requires_cookies(self, client) -> None:
        resp = client.get("/notebooks")
        assert resp.status_code == 401
        data = json.loads(resp.data)
        assert data["error"] == "no_cookies"

    def test_sources_requires_cookies(self, client) -> None:
        resp = client.get("/notebooks/test-id/sources")
        assert resp.status_code == 401

    def test_notes_requires_cookies(self, client) -> None:
        resp = client.get("/notebooks/test-id/notes")
        assert resp.status_code == 401

    def test_summary_requires_cookies(self, client) -> None:
        resp = client.get("/notebooks/test-id/summary")
        assert resp.status_code == 401

    def test_conversations_requires_cookies(self, client) -> None:
        resp = client.get("/notebooks/test-id/conversations")
        assert resp.status_code == 401

    def test_rpc_passthrough_requires_cookies(self, client) -> None:
        resp = client.post("/rpc/VfAZjd", json={"args": "[]"})
        assert resp.status_code == 401

    def test_import_cookies_from_har_file(self, client, tmp_path: Path) -> None:
        import engine.mcp.nlm_live_proxy as proxy_mod
        har = _make_har([
            {"name": "SID", "value": "my_sid"},
            {"name": "SAPISID", "value": "my_sapisid"},
        ])
        har_file = tmp_path / "import.har"
        har_file.write_text(json.dumps(har), encoding="utf-8")

        resp = client.post(
            "/cookies/import",
            json={"har_path": str(har_file)},
            content_type="application/json",
        )
        data = json.loads(resp.data)
        assert resp.status_code == 200
        assert data["imported"] >= 1

        # Verify cookies persisted
        stored = json.loads(proxy_mod._COOKIES_FILE.read_text())
        assert stored.get("SID") == "my_sid"


# ── NotebookLMProxy client (updated) ──────────────────────────────────

class TestNotebookLMProxy:
    def test_proxy_not_running_without_server(self) -> None:
        from engine.mcp.notebooklm_proxy import NotebookLMProxy
        proxy = NotebookLMProxy({"base_url": "http://localhost:9999"})
        assert proxy.is_running() is False

    def test_start_returns_false_without_server(self) -> None:
        from engine.mcp.notebooklm_proxy import NotebookLMProxy
        proxy = NotebookLMProxy({"base_url": "http://localhost:9999"})
        assert proxy.start() is False

    def test_request_returns_error_when_offline(self) -> None:
        from engine.mcp.notebooklm_proxy import NotebookLMProxy
        proxy = NotebookLMProxy({"base_url": "http://localhost:9999"})
        result = proxy.list_notebooks()
        assert result == []

    def test_ask_returns_error_when_offline(self) -> None:
        from engine.mcp.notebooklm_proxy import NotebookLMProxy
        proxy = NotebookLMProxy({"base_url": "http://localhost:9999"})
        result = proxy.ask("nb-123", "question")
        assert isinstance(result, dict)
        assert "error" in result

    def test_add_source_always_returns_not_supported(self) -> None:
        from engine.mcp.notebooklm_proxy import NotebookLMProxy
        proxy = NotebookLMProxy({"base_url": "http://localhost:9999"})
        result = proxy.add_source("nb-123", "url", "https://example.com")
        assert result["error"] == "not_supported"

    def test_generate_audio_always_returns_not_supported(self) -> None:
        from engine.mcp.notebooklm_proxy import NotebookLMProxy
        proxy = NotebookLMProxy({"base_url": "http://localhost:9999"})
        result = proxy.generate_audio("nb-123")
        assert result["error"] == "not_supported"

    def test_stop_is_noop(self) -> None:
        from engine.mcp.notebooklm_proxy import NotebookLMProxy
        proxy = NotebookLMProxy({})
        proxy.stop()  # Should not raise

    def test_proxy_uses_base_url_from_config(self) -> None:
        from engine.mcp.notebooklm_proxy import NotebookLMProxy
        proxy = NotebookLMProxy({"base_url": "http://custom:9000"})
        assert proxy._base_url == "http://custom:9000"

    def test_proxy_strips_trailing_slash(self) -> None:
        from engine.mcp.notebooklm_proxy import NotebookLMProxy
        proxy = NotebookLMProxy({"base_url": "http://localhost:8800/"})
        assert proxy._base_url == "http://localhost:8800"

    def test_singleton(self) -> None:
        from engine.mcp.notebooklm_proxy import get_notebooklm_proxy
        import engine.mcp.notebooklm_proxy as mod
        # Reset singleton for test isolation
        original = mod._proxy
        mod._proxy = None
        try:
            p1 = get_notebooklm_proxy()
            p2 = get_notebooklm_proxy()
            assert p1 is p2
        finally:
            mod._proxy = original
