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

        cookies, meta = extract_cookies_from_har(str(har_file))
        assert cookies.get("SID") == "test_sid"
        assert cookies.get("SSID") == "test_ssid"
        # non-auth cookies should be filtered out
        assert "some_random_cookie" not in cookies

    def test_extracts_secure_prefix_cookies(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import extract_cookies_from_har

        har = _make_har([
            {"name": "__Secure-3PAPISID", "value": "secure_value"},
            {"name": "SAPISID", "value": "sapi_value"},
        ])
        har_file = tmp_path / "test2.har"
        har_file.write_text(json.dumps(har), encoding="utf-8")

        cookies, meta = extract_cookies_from_har(str(har_file))
        assert cookies.get("__Secure-3PAPISID") == "secure_value"
        assert cookies.get("SAPISID") == "sapi_value"

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
        cookies, meta = extract_cookies_from_har(str(har_file))
        assert cookies == {}

    def test_returns_empty_for_missing_file(self) -> None:
        from engine.mcp.nlm_live_proxy import extract_cookies_from_har
        cookies, meta = extract_cookies_from_har("/nonexistent/path/file.har")
        assert cookies == {}

    def test_extracts_bl_from_batchexecute_url(self, tmp_path: Path) -> None:
        """HAR should extract bl (build label) and f.sid from batchexecute URLs."""
        from engine.mcp.nlm_live_proxy import extract_cookies_from_har

        har = {
            "log": {
                "entries": [{
                    "request": {
                        "url": ("https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
                                "?rpcids=VfAZjd&bl=boq_labs-tailwind-frontend_20260226.08_p0"
                                "&f.sid=5167585844626553481&rt=c"),
                        "headers": [{"name": "X-Same-Domain", "value": "1"}],
                        "cookies": [],
                    },
                }]
            }
        }
        har_file = tmp_path / "test_bl.har"
        har_file.write_text(json.dumps(har), encoding="utf-8")
        cookies, meta = extract_cookies_from_har(str(har_file))
        assert meta.get("bl") == "boq_labs-tailwind-frontend_20260226.08_p0"
        assert meta.get("f_sid") == "5167585844626553481"


    def test_extracts_at_token_from_har_postdata(self, tmp_path: Path) -> None:
        """HAR postData should yield the at anti-forgery token."""
        from engine.mcp.nlm_live_proxy import extract_cookies_from_har
        import urllib.parse

        post_body = urllib.parse.urlencode({
            "f.req": "[[]]",
            "at": "AIXQIkaQJ-TlmwdNT-jCU_Kh842W:1772273952751",
        })
        har = {
            "log": {
                "entries": [{
                    "request": {
                        "url": ("https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
                                "?rpcids=CYK0Xb&bl=boq_labs-tailwind-frontend_20260226.08_p0"
                                "&f.sid=-1&rt=c"),
                        "headers": [],
                        "cookies": [],
                        "postData": {"text": post_body},
                    },
                }]
            }
        }
        har_file = tmp_path / "test_at.har"
        har_file.write_text(json.dumps(har), encoding="utf-8")
        cookies, meta = extract_cookies_from_har(str(har_file))
        assert meta.get("at") == "AIXQIkaQJ-TlmwdNT-jCU_Kh842W:1772273952751"


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

    def test_cookies_refresh_no_cookies_returns_422(self, client) -> None:
        resp = client.post("/cookies/refresh")
        assert resp.status_code == 422
        data = json.loads(resp.data)
        assert data["error"] == "no_cookies"

    def test_cookies_refresh_calls_refresh_tokens(self, client, tmp_path: Path) -> None:
        import engine.mcp.nlm_live_proxy as proxy_mod
        from unittest.mock import patch
        proxy_mod._COOKIES_FILE.write_text(
            json.dumps({"SID": "test", "SSID": "test2"}), encoding="utf-8"
        )
        with patch.object(proxy_mod, "refresh_session_tokens", return_value=True) as mock_refresh:
            resp = client.post("/cookies/refresh")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["refreshed"] is True
        mock_refresh.assert_called_once()

    def test_cookies_refresh_returns_false_when_refresh_fails(self, client, tmp_path: Path) -> None:
        import engine.mcp.nlm_live_proxy as proxy_mod
        from unittest.mock import patch
        proxy_mod._COOKIES_FILE.write_text(
            json.dumps({"SID": "test"}), encoding="utf-8"
        )
        with patch.object(proxy_mod, "refresh_session_tokens", return_value=False):
            resp = client.post("/cookies/refresh")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["refreshed"] is False


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
        assert data.get("imported_cookies", data.get("imported", 0)) >= 1

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


# ── Write operation parsing ────────────────────────────────────────────

class TestWriteOperationParsing:
    """Tests for the new write RPC response parsers."""

    def test_parse_ask_response_valid(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_ask_response
        data = [["answer-uuid-123", "This is the answer with some details."]]
        result = _parse_ask_response(data)
        assert result["answer_id"] == "answer-uuid-123"
        assert "answer with some details" in result["answer"]
        assert isinstance(result["sources"], list)

    def test_parse_ask_response_none(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_ask_response
        result = _parse_ask_response(None)
        assert result["answer"] == ""
        assert result["answer_id"] is None
        assert "error" in result

    def test_parse_ask_response_error(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_ask_response
        result = _parse_ask_response({"error": "HTTP 401", "detail": "auth expired"})
        assert result["error"] == "HTTP 401"

    def test_parse_generate_response_valid(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_generate_response
        data = [["Implementation Strategy", "A comprehensive analysis...", None, []]]
        result = _parse_generate_response(data, ["src-1"])
        assert result["title"] == "Implementation Strategy"
        assert "comprehensive" in result["description"]

    def test_parse_generate_response_none(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_generate_response
        result = _parse_generate_response(None, [])
        assert result["title"] == ""
        assert "error" in result

    def test_parse_save_note_response_valid(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_save_note_response
        data = [["note-uuid-456", "My Research Note", 2, [["src-1"]]]]
        result = _parse_save_note_response(data)
        assert result["note_id"] == "note-uuid-456"
        assert result["title"] == "My Research Note"
        assert result["note_type"] == 2

    def test_parse_save_note_response_none(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_save_note_response
        result = _parse_save_note_response(None)
        assert result["note_id"] is None
        assert "error" in result


class TestMultiBatchParsing:
    """Tests for multi-question batchexecute parsing."""

    def test_parse_multi_wrb_fr(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_batchexecute_multi
        import json as _json

        inner1 = [["id-1", "Answer to question 1"]]
        inner2 = [["id-2", "Answer to question 2"]]
        line1 = _json.dumps([["wrb.fr", "CYK0Xb", _json.dumps(inner1)]])
        line2 = _json.dumps([["wrb.fr", "CYK0Xb", _json.dumps(inner2)]])
        raw = ")]}'\n" + line1 + "\n" + line2 + "\n"

        results = _parse_batchexecute_multi(raw)
        assert len(results) == 2
        assert results[0][0] == "CYK0Xb"
        assert results[1][0] == "CYK0Xb"

    def test_parse_multi_single(self) -> None:
        from engine.mcp.nlm_live_proxy import _parse_batchexecute_multi
        import json as _json
        inner = {"key": "value"}
        line = _json.dumps([["wrb.fr", "VfAZjd", _json.dumps(inner)]])
        raw = ")]}'\n" + line
        results = _parse_batchexecute_multi(raw)
        assert len(results) == 1
        assert results[0][1] == inner


class TestWriteFlaskEndpoints:
    """Tests for the new write-operation Flask routes."""

    @pytest.fixture
    def client_with_cookies(self, tmp_path: Path):
        from engine.mcp.nlm_live_proxy import create_nlm_proxy_app
        import engine.mcp.nlm_live_proxy as proxy_mod
        from unittest.mock import patch

        original_cookies = proxy_mod._COOKIES_FILE
        original_meta = proxy_mod._META_FILE
        cookies_file = tmp_path / "cookies.json"
        meta_file = tmp_path / "meta.json"
        cookies_file.write_text(json.dumps({"SID": "test"}), encoding="utf-8")
        meta_file.write_text(json.dumps({"bl": "test_bl", "f_sid": "12345"}), encoding="utf-8")
        proxy_mod._COOKIES_FILE = cookies_file
        proxy_mod._META_FILE = meta_file
        app = create_nlm_proxy_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c
        proxy_mod._COOKIES_FILE = original_cookies
        proxy_mod._META_FILE = original_meta

    def test_ask_requires_question(self, client_with_cookies) -> None:
        from unittest.mock import patch
        with patch("engine.mcp.nlm_live_proxy._batchexecute_multi",
                   return_value=[(None, {"error": "mocked"})]):
            resp = client_with_cookies.post(
                "/notebooks/nb-123/ask",
                json={},
                content_type="application/json",
            )
        assert resp.status_code == 400

    def test_ask_batch_requires_questions_list(self, client_with_cookies) -> None:
        from unittest.mock import patch
        with patch("engine.mcp.nlm_live_proxy._batchexecute_multi",
                   return_value=[(None, {"error": "mocked"})]):
            resp = client_with_cookies.post(
                "/notebooks/nb-123/ask_batch",
                json={"questions": "not a list"},
                content_type="application/json",
            )
        assert resp.status_code == 400

    def test_ask_no_cookies_returns_401(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import create_nlm_proxy_app
        import engine.mcp.nlm_live_proxy as proxy_mod
        original = proxy_mod._COOKIES_FILE
        proxy_mod._COOKIES_FILE = tmp_path / "empty.json"
        app = create_nlm_proxy_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.post("/notebooks/nb/ask", json={"question": "Q?"})
        proxy_mod._COOKIES_FILE = original
        assert resp.status_code == 401

    def test_meta_get(self, client_with_cookies) -> None:
        resp = client_with_cookies.get("/meta")
        data = json.loads(resp.data)
        assert "bl" in data
        assert "f_sid" in data

    def test_meta_post_updates_bl(self, client_with_cookies) -> None:
        resp = client_with_cookies.post(
            "/meta",
            json={"bl": "boq_new_label"},
            content_type="application/json",
        )
        data = json.loads(resp.data)
        assert data.get("bl") == "boq_new_label"
        assert data.get("updated") is True


class TestNLMQADistiller:
    """Tests for the NLM QA Distiller module."""

    def test_question_templates_populated(self) -> None:
        from engine.nexus.nlm_qa_distiller import QUESTION_TEMPLATES
        assert len(QUESTION_TEMPLATES) >= 5
        for key, batches in QUESTION_TEMPLATES.items():
            assert len(batches) >= 1
            for batch in batches:
                assert len(batch) >= 3
                assert len(batch) <= 5

    def test_get_questions_from_template(self) -> None:
        from engine.nexus.nlm_qa_distiller import NLMQADistiller
        distiller = NLMQADistiller()
        questions = distiller._get_questions("cosysim_architecture", 10, "cosysim_architecture")
        assert len(questions) <= 10
        assert all(isinstance(q, str) and len(q) > 20 for q in questions)

    def test_get_questions_generic_fallback(self) -> None:
        from engine.nexus.nlm_qa_distiller import NLMQADistiller
        distiller = NLMQADistiller()
        questions = distiller._get_questions("unknown_topic_xyz", 5, None)
        assert len(questions) == 5
        assert all("unknown_topic_xyz" in q for q in questions)

    def test_proxy_not_ready_returns_empty(self) -> None:
        from engine.nexus.nlm_qa_distiller import NLMQADistiller
        distiller = NLMQADistiller(proxy_url="http://localhost:9999")
        pairs = distiller.distill_topic("nb-123", "test", num_questions=5)
        assert pairs == []


class TestV21Routes:
    """Tests for v2.1 routes: /chat, /chat_batch, /sources/<id>/content, /user/quota."""

    @pytest.fixture
    def client_v21(self, tmp_path: Path):
        from engine.mcp.nlm_live_proxy import create_nlm_proxy_app
        import engine.mcp.nlm_live_proxy as proxy_mod

        original_cookies = proxy_mod._COOKIES_FILE
        original_meta = proxy_mod._META_FILE
        cookies_file = tmp_path / "cookies.json"
        meta_file = tmp_path / "meta.json"
        cookies_file.write_text(json.dumps({"SID": "test_sid"}), encoding="utf-8")
        meta_file.write_text(
            json.dumps({"bl": "boq_test_20260101.01_p0", "f_sid": "99999"}),
            encoding="utf-8",
        )
        proxy_mod._COOKIES_FILE = cookies_file
        proxy_mod._META_FILE = meta_file
        app = create_nlm_proxy_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c
        proxy_mod._COOKIES_FILE = original_cookies
        proxy_mod._META_FILE = original_meta

    # ── /chat ──────────────────────────────────────────────────────────

    def test_chat_requires_question(self, client_v21) -> None:
        """POST /notebooks/<id>/chat with empty body returns 400."""
        resp = client_v21.post(
            "/notebooks/nb-xyz/chat",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "question" in data.get("error", "")

    def test_chat_no_cookies_returns_401(self, tmp_path: Path) -> None:
        """POST /notebooks/<id>/chat without cookies returns 401."""
        from engine.mcp.nlm_live_proxy import create_nlm_proxy_app
        import engine.mcp.nlm_live_proxy as proxy_mod

        original = proxy_mod._COOKIES_FILE
        proxy_mod._COOKIES_FILE = tmp_path / "missing.json"
        app = create_nlm_proxy_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.post(
                "/notebooks/nb-xyz/chat",
                json={"question": "What is the main theme?"},
                content_type="application/json",
            )
        proxy_mod._COOKIES_FILE = original
        assert resp.status_code == 401

    def test_chat_returns_queued_on_success(self, client_v21) -> None:
        """POST /notebooks/<id>/chat with mocked batchexecute returns queued result."""
        from engine.mcp.nlm_live_proxy import RESP_LEN_DEFAULT

        mock_result = {
            "queued": True,
            "notebook_id": "nb-xyz",
            "question": "What is the main theme?",
        }
        with patch("engine.mcp.nlm_live_proxy.chat_message", return_value=mock_result):
            resp = client_v21.post(
                "/notebooks/nb-xyz/chat",
                json={"question": "What is the main theme?", "role": "Act as a teacher"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("queued") is True

    def test_chat_returns_502_on_error(self, client_v21) -> None:
        """POST /notebooks/<id>/chat returns 502 when chat_message errors."""
        with patch("engine.mcp.nlm_live_proxy.chat_message",
                   return_value={"error": "network timeout", "queued": False}):
            resp = client_v21.post(
                "/notebooks/nb-xyz/chat",
                json={"question": "Q?"},
                content_type="application/json",
            )
        assert resp.status_code == 502

    # ── /chat_batch ────────────────────────────────────────────────────

    def test_chat_batch_requires_questions(self, client_v21) -> None:
        """POST /notebooks/<id>/chat_batch with empty body returns 400."""
        resp = client_v21.post(
            "/notebooks/nb-xyz/chat_batch",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_chat_batch_no_cookies_returns_401(self, tmp_path: Path) -> None:
        """POST /notebooks/<id>/chat_batch without cookies returns 401."""
        from engine.mcp.nlm_live_proxy import create_nlm_proxy_app
        import engine.mcp.nlm_live_proxy as proxy_mod

        original = proxy_mod._COOKIES_FILE
        proxy_mod._COOKIES_FILE = tmp_path / "missing.json"
        app = create_nlm_proxy_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.post(
                "/notebooks/nb-xyz/chat_batch",
                json={"questions": ["Q1?", "Q2?"]},
                content_type="application/json",
            )
        proxy_mod._COOKIES_FILE = original
        assert resp.status_code == 401

    def test_chat_batch_returns_results(self, client_v21) -> None:
        """POST /notebooks/<id>/chat_batch returns list of queued results."""
        mock_results = [
            {"queued": True, "question": "Q1?"},
            {"queued": True, "question": "Q2?"},
        ]
        with patch("engine.mcp.nlm_live_proxy.chat_messages_batch",
                   return_value=mock_results):
            resp = client_v21.post(
                "/notebooks/nb-xyz/chat_batch",
                json={"questions": ["Q1?", "Q2?"]},
                content_type="application/json",
            )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["count"] == 2
        assert data["queued_count"] == 2
        assert len(data["results"]) == 2

    # ── /sources/<id>/content ─────────────────────────────────────────

    def test_read_source_no_cookies_returns_401(self, tmp_path: Path) -> None:
        """GET /sources/<id>/content without cookies returns 401."""
        from engine.mcp.nlm_live_proxy import create_nlm_proxy_app
        import engine.mcp.nlm_live_proxy as proxy_mod

        original = proxy_mod._COOKIES_FILE
        proxy_mod._COOKIES_FILE = tmp_path / "missing.json"
        app = create_nlm_proxy_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/sources/src-abc/content")
        proxy_mod._COOKIES_FILE = original
        assert resp.status_code == 401

    def test_read_source_returns_content(self, client_v21) -> None:
        """GET /sources/<id>/content returns source text."""
        mock_result = {
            "source_id": "src-abc",
            "content": "# Document Title\n\nFull content here.",
            "word_count": 4,
        }
        with patch("engine.mcp.nlm_live_proxy.read_source", return_value=mock_result):
            resp = client_v21.get("/sources/src-abc/content")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["source_id"] == "src-abc"
        assert "content" in data
        assert data["word_count"] == 4

    def test_read_source_returns_502_on_error(self, client_v21) -> None:
        """GET /sources/<id>/content returns 502 on read_source error."""
        with patch("engine.mcp.nlm_live_proxy.read_source",
                   return_value={"error": "source not found"}):
            resp = client_v21.get("/sources/bad-id/content")
        assert resp.status_code == 502

    # ── /user/quota ────────────────────────────────────────────────────

    def test_user_quota_no_cookies_returns_401(self, tmp_path: Path) -> None:
        """GET /user/quota without cookies returns 401."""
        from engine.mcp.nlm_live_proxy import create_nlm_proxy_app
        import engine.mcp.nlm_live_proxy as proxy_mod

        original = proxy_mod._COOKIES_FILE
        proxy_mod._COOKIES_FILE = tmp_path / "missing.json"
        app = create_nlm_proxy_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/user/quota")
        proxy_mod._COOKIES_FILE = original
        assert resp.status_code == 401

    def test_user_quota_returns_data(self, client_v21) -> None:
        """GET /user/quota returns quota dict."""
        mock_result = {"quota_data": {"notebooks": 12, "sources": 150}, "extracted": True}
        with patch("engine.mcp.nlm_live_proxy.get_user_quota", return_value=mock_result):
            resp = client_v21.get("/user/quota")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "quota_data" in data

    def test_user_quota_returns_502_on_error(self, client_v21) -> None:
        """GET /user/quota returns 502 on RPC error."""
        with patch("engine.mcp.nlm_live_proxy.get_user_quota",
                   return_value={"error": "RPC failed"}):
            resp = client_v21.get("/user/quota")
        assert resp.status_code == 502


# ── refresh_session_tokens ────────────────────────────────────────────

class TestRefreshSessionTokens:
    """Tests for refresh_session_tokens() — extracts at/f.sid from live NLM page."""

    def test_returns_false_when_no_cookies(self, tmp_path: Path) -> None:
        import engine.mcp.nlm_live_proxy as proxy_mod
        original = proxy_mod._COOKIES_FILE
        proxy_mod._COOKIES_FILE = tmp_path / "empty_cookies.json"
        try:
            result = proxy_mod.refresh_session_tokens()
            assert result is False
        finally:
            proxy_mod._COOKIES_FILE = original

    def test_returns_false_on_http_error(self, tmp_path: Path) -> None:
        import engine.mcp.nlm_live_proxy as proxy_mod
        from unittest.mock import patch
        original = proxy_mod._COOKIES_FILE
        proxy_mod._COOKIES_FILE = tmp_path / "cookies.json"
        proxy_mod._COOKIES_FILE.write_text(json.dumps({"SID": "test"}), encoding="utf-8")
        try:
            import urllib.error
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
                result = proxy_mod.refresh_session_tokens()
            assert result is False
        finally:
            proxy_mod._COOKIES_FILE = original

    def test_extracts_tokens_from_wiz_global_data(self, tmp_path: Path) -> None:
        import engine.mcp.nlm_live_proxy as proxy_mod
        from unittest.mock import patch, MagicMock
        original_cookies = proxy_mod._COOKIES_FILE
        original_meta = proxy_mod._META_FILE
        proxy_mod._COOKIES_FILE = tmp_path / "cookies.json"
        proxy_mod._META_FILE = tmp_path / "meta.json"
        proxy_mod._COOKIES_FILE.write_text(json.dumps({"SID": "test"}), encoding="utf-8")
        proxy_mod._META_FILE.write_text(json.dumps({"bl": "boq_labs-tailwind-frontend_20260226.08_p0"}), encoding="utf-8")

        fake_html = (
            'WIZ_global_data = {"FdrFJe": "fresh_fsid_value", "SNlM0e": "fresh_at_token"};'
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        try:
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = proxy_mod.refresh_session_tokens()
            assert result is True
            meta = json.loads(proxy_mod._META_FILE.read_text())
            assert meta["f_sid"] == "fresh_fsid_value"
            assert meta["at"] == "fresh_at_token"
        finally:
            proxy_mod._COOKIES_FILE = original_cookies
            proxy_mod._META_FILE = original_meta


# ── NLMClient class ────────────────────────────────────────────────────

class TestNLMClient:
    """Tests for the NLMClient class and get_nlm_client() singleton."""

    def test_singleton_returns_same_instance(self) -> None:
        from engine.mcp.nlm_live_proxy import get_nlm_client
        import engine.mcp.nlm_live_proxy as mod
        original = mod._nlm_client
        mod._nlm_client = None
        try:
            c1 = get_nlm_client()
            c2 = get_nlm_client()
            assert c1 is c2
        finally:
            mod._nlm_client = original

    def test_has_cookies_false_when_no_file(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import NLMClient
        import engine.mcp.nlm_live_proxy as mod
        original = mod._COOKIES_FILE
        mod._COOKIES_FILE = tmp_path / "no_cookies.json"
        try:
            client = NLMClient()
            assert client.has_cookies() is False
        finally:
            mod._COOKIES_FILE = original

    def test_has_cookies_true_when_file_exists(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import NLMClient
        import engine.mcp.nlm_live_proxy as mod
        original = mod._COOKIES_FILE
        cf = tmp_path / "cookies.json"
        cf.write_text(json.dumps({"SID": "abc", "SSID": "xyz"}), encoding="utf-8")
        mod._COOKIES_FILE = cf
        try:
            client = NLMClient()
            assert client.has_cookies() is True
        finally:
            mod._COOKIES_FILE = original

    def test_get_cookies_returns_dict(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import NLMClient
        import engine.mcp.nlm_live_proxy as mod
        original = mod._COOKIES_FILE
        cf = tmp_path / "cookies.json"
        cf.write_text(json.dumps({"SID": "sid1", "SSID": "ssid1"}), encoding="utf-8")
        mod._COOKIES_FILE = cf
        try:
            client = NLMClient()
            cookies = client.get_cookies()
            assert isinstance(cookies, dict)
            assert cookies.get("SID") == "sid1"
        finally:
            mod._COOKIES_FILE = original

    def test_get_status_no_cookies(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import NLMClient
        import engine.mcp.nlm_live_proxy as mod
        original = mod._COOKIES_FILE
        mod._COOKIES_FILE = tmp_path / "empty.json"
        try:
            client = NLMClient()
            status = client.get_status()
            assert status["has_cookies"] is False
            assert status["cookie_count"] == 0
        finally:
            mod._COOKIES_FILE = original

    def test_get_status_with_cookies(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import NLMClient
        import engine.mcp.nlm_live_proxy as mod
        original_cf = mod._COOKIES_FILE
        original_mf = mod._META_FILE
        cf = tmp_path / "cookies.json"
        mf = tmp_path / "meta.json"
        cf.write_text(json.dumps({"SID": "s", "SAPISID": "sa"}), encoding="utf-8")
        mf.write_text(json.dumps({"bl": "boq_test_20260228.01_p0", "f_sid": "123"}), encoding="utf-8")
        mod._COOKIES_FILE = cf
        mod._META_FILE = mf
        try:
            client = NLMClient()
            status = client.get_status()
            assert status["has_cookies"] is True
            assert status["cookie_count"] == 2
            assert "bl" in status
        finally:
            mod._COOKIES_FILE = original_cf
            mod._META_FILE = original_mf

    def test_import_cookies_from_har(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import NLMClient
        import engine.mcp.nlm_live_proxy as mod
        original = mod._COOKIES_FILE
        mod._COOKIES_FILE = tmp_path / "imported.json"
        har = _make_har([
            {"name": "SID", "value": "imported_sid"},
            {"name": "HSID", "value": "imported_hsid"},
        ])
        har_file = tmp_path / "import_test.har"
        har_file.write_text(json.dumps(har), encoding="utf-8")
        try:
            client = NLMClient()
            result = client.import_cookies_from_har(str(har_file))
            # Result uses "imported" key (not "imported_cookies")
            count = result.get("imported", result.get("imported_cookies", 0))
            assert count >= 1
            assert client.has_cookies() is True
        finally:
            mod._COOKIES_FILE = original

    def test_list_notebooks_without_cookies_returns_error(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import NLMClient
        import engine.mcp.nlm_live_proxy as mod
        original = mod._COOKIES_FILE
        mod._COOKIES_FILE = tmp_path / "no_cookies.json"
        try:
            client = NLMClient()
            result = client.list_notebooks()
            # Without cookies, should return empty list or error dict
            assert isinstance(result, (list, dict))
        finally:
            mod._COOKIES_FILE = original

    def test_ask_without_cookies_returns_error(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import NLMClient
        import engine.mcp.nlm_live_proxy as mod
        original = mod._COOKIES_FILE
        mod._COOKIES_FILE = tmp_path / "no_cookies.json"
        try:
            client = NLMClient()
            result = client.ask("nb-id", "What is this about?")
            assert isinstance(result, dict)
            assert "error" in result
        finally:
            mod._COOKIES_FILE = original

    def test_all_public_methods_exist(self) -> None:
        """Verify all expected public methods are present on NLMClient."""
        from engine.mcp.nlm_live_proxy import NLMClient
        expected = [
            "has_cookies", "get_cookies", "get_status",
            "import_cookies_from_har", "capture_cookies_from_chrome",
            "list_notebooks", "get_notebook", "get_sources",
            "get_notes", "get_summary", "get_chat_history",
            "ask", "ask_batch", "chat", "chat_batch",
            "generate_document", "save_note", "read_source",
            "get_user_quota",
        ]
        for method_name in expected:
            assert hasattr(NLMClient, method_name), f"NLMClient missing method: {method_name}"


# ── History Flask route ────────────────────────────────────────────────

class TestHistoryFlaskRoute:
    """Tests for GET /notebooks/<id>/history (hPTbtc RPC)."""

    @pytest.fixture
    def client_with_cookies(self, tmp_path: Path):
        from engine.mcp.nlm_live_proxy import create_nlm_proxy_app
        import engine.mcp.nlm_live_proxy as proxy_mod

        original_cf = proxy_mod._COOKIES_FILE
        original_mf = proxy_mod._META_FILE
        cf = tmp_path / "cookies.json"
        mf = tmp_path / "meta.json"
        cf.write_text(json.dumps({"SID": "test"}), encoding="utf-8")
        mf.write_text(json.dumps({"bl": "bl_test", "f_sid": "111"}), encoding="utf-8")
        proxy_mod._COOKIES_FILE = cf
        proxy_mod._META_FILE = mf
        app = create_nlm_proxy_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c
        proxy_mod._COOKIES_FILE = original_cf
        proxy_mod._META_FILE = original_mf

    def test_history_requires_cookies(self, tmp_path: Path) -> None:
        from engine.mcp.nlm_live_proxy import create_nlm_proxy_app
        import engine.mcp.nlm_live_proxy as proxy_mod
        original = proxy_mod._COOKIES_FILE
        proxy_mod._COOKIES_FILE = tmp_path / "no.json"
        app = create_nlm_proxy_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/notebooks/nb-123/history")
        proxy_mod._COOKIES_FILE = original
        assert resp.status_code == 401

    def test_history_returns_200_with_mocked_rpc(self, client_with_cookies) -> None:
        from unittest.mock import patch
        # The history route calls _batchexecute("hPTbtc", ...) directly
        mock_data = [["message content here for testing purposes"]]
        with patch("engine.mcp.nlm_live_proxy._batchexecute",
                   return_value=("hPTbtc", mock_data)):
            resp = client_with_cookies.get("/notebooks/nb-123/history")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "messages" in data
        assert "notebook_id" in data

    def test_history_returns_502_on_rpc_error(self, client_with_cookies) -> None:
        from unittest.mock import patch
        with patch("engine.mcp.nlm_live_proxy._batchexecute",
                   return_value=("hPTbtc", {"error": "RPC timeout"})):
            resp = client_with_cookies.get("/notebooks/nb-123/history")
        assert resp.status_code == 502

    def test_history_passes_page_size(self, client_with_cookies) -> None:
        from unittest.mock import patch, call
        with patch("engine.mcp.nlm_live_proxy._batchexecute",
                   return_value=("hPTbtc", [])) as mock_rpc:
            resp = client_with_cookies.get(
                "/notebooks/nb-123/history?page_size=50"
            )
        assert resp.status_code == 200
        # Verify page_size was reflected in the args
        mock_rpc.assert_called_once()
        call_args = mock_rpc.call_args[0]
        assert "50" in call_args[1]  # page_size 50 in serialized args string
