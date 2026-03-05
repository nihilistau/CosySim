"""Tests for GoogleAIMClient — Google AI Mode canvas API client."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from engine.integrations.google_aim_client import (
    AIMSession,
    GoogleAIMClient,
    _strip_jspb,
    get_aim_client,
)


# ──── Helper fixtures ──────────────────────────────────────────────────────────

SAMPLE_FOLIF_HTML = """
<div data-container-id="abc123def456"></div>
<div eid="abc123def456"></div>
<div>
  <div data-target-container-id="abc123def456">
    <div
      data-msei="AUtExfDVgpFavP3qFwELJNUCY5bSd-sample"
      data-mseni="abc123def456"
      data-mstk="AUtExfBlC1dBcRPZG9tgQQLD7uHVqa5-sample"
      style="display:none">
    </div>
  </div>
</div>
<p>Here is the AI response</p>
"""

SAMPLE_FOLIF_HTML_WITH_CANVAS = SAMPLE_FOLIF_HTML + '<div class="aim/canvas">Canvas content</div>'

SAMPLE_EXPORT_RESPONSE = (
    ")]}'\n"
    '["what else can you do in the canvas?",'
    '[[[null,"<div>Canvas HTML content</div>"],"\\n"]]]'
)

SAMPLE_LIST_THREADS_RESPONSE = (
    ")]}'\n"
    '[[["thread_ei_1","Thread title 1",1709000000,true],'
    '["thread_ei_2","Thread title 2",1709000001,false]]]'
)


@pytest.fixture
def mock_cookies() -> dict:
    return {
        "__Secure-1PSIDTS": "test-xsrf-token-12345",
        "SID": "fake-sid-value",
        "HSID": "fake-hsid-value",
    }


@pytest.fixture
def client(mock_cookies: dict) -> GoogleAIMClient:
    c = GoogleAIMClient(cookies=mock_cookies)
    return c


# ──── _strip_jspb ──────────────────────────────────────────────────────────────

class TestStripJspb:
    def test_strips_prefix(self) -> None:
        raw = ")]}'\n[\"hello\"]"
        result = _strip_jspb(raw)
        assert result == ["hello"]

    def test_no_prefix(self) -> None:
        raw = '{"key": "value"}'
        result = _strip_jspb(raw)
        assert result == {"key": "value"}

    def test_preserves_nested(self) -> None:
        raw = ")]}'\n[[null, [\"a\", \"b\"], 123]]"
        result = _strip_jspb(raw)
        assert result[0][1] == ["a", "b"]


# ──── AIMSession ───────────────────────────────────────────────────────────────

class TestAIMSession:
    def test_from_folif_html_extracts_container_id(self) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "xsrf-tok")
        assert session.thread_ei == "abc123def456"

    def test_from_folif_html_extracts_mstk(self) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "xsrf-tok")
        assert session.mstk == "AUtExfBlC1dBcRPZG9tgQQLD7uHVqa5-sample"

    def test_from_folif_html_extracts_msei(self) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "xsrf-tok")
        assert session.msei == "AUtExfDVgpFavP3qFwELJNUCY5bSd-sample"

    def test_from_folif_html_sets_xsrf(self) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "my-xsrf")
        assert session.xsrf == "my-xsrf"

    def test_is_valid_with_required_fields(self) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "xsrf-tok")
        assert session.is_valid() is True

    def test_is_valid_missing_thread_ei(self) -> None:
        session = AIMSession()
        session.xsrf = "xsrf"
        assert session.is_valid() is False

    def test_is_valid_missing_xsrf(self) -> None:
        session = AIMSession()
        session.thread_ei = "thread123"
        assert session.is_valid() is False

    def test_repr(self) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "xsrf-tok")
        r = repr(session)
        assert "abc123def456" in r
        assert "valid=True" in r


# ──── GoogleAIMClient ──────────────────────────────────────────────────────────

class TestGoogleAIMClientInit:
    def test_init_with_cookies(self, mock_cookies: dict) -> None:
        c = GoogleAIMClient(cookies=mock_cookies)
        assert c is not None

    def test_get_xsrf_from_cookie(self, client: GoogleAIMClient) -> None:
        xsrf = client._get_xsrf()
        assert xsrf == "test-xsrf-token-12345"

    def test_get_xsrf_raises_without_cookies(self) -> None:
        c = GoogleAIMClient()
        with pytest.raises(RuntimeError, match="No XSRF token"):
            c._get_xsrf()


class TestSearch:
    def test_search_returns_session_and_html(self, client: GoogleAIMClient) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_FOLIF_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "get", return_value=mock_resp):
            session, html = client.search("test query")

        assert isinstance(session, AIMSession)
        assert session.thread_ei == "abc123def456"
        assert session.xsrf == "test-xsrf-token-12345"
        assert "AI response" in html

    def test_search_sets_query(self, client: GoogleAIMClient) -> None:
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_FOLIF_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "get", return_value=mock_resp):
            session, _ = client.search("my query")

        assert session.query == "my query"


class TestFollowup:
    def test_followup_returns_updated_session(self, client: GoogleAIMClient) -> None:
        initial_session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "xsrf-tok")
        initial_session.xsrf = "test-xsrf-token-12345"

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_FOLIF_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "get", return_value=mock_resp):
            new_session, html = client.followup(initial_session, "follow up question")

        assert new_session.thread_ei == "abc123def456"
        assert new_session.query == "follow up question"

    def test_followup_detects_canvas(self, client: GoogleAIMClient) -> None:
        initial_session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "test-xsrf-token-12345")

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_FOLIF_HTML_WITH_CANVAS
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "get", return_value=mock_resp):
            _, html = client.followup(initial_session, "create a canvas")

        assert client.is_canvas_response(html) is True


class TestExportThread:
    def test_export_thread_parses_content(self, client: GoogleAIMClient) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "test-xsrf-token-12345")

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_EXPORT_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "post", return_value=mock_resp):
            result = client.export_thread(session)

        assert result["thread_id"] == "abc123def456"
        assert result["query"] == "what else can you do in the canvas?"
        assert "Canvas HTML content" in result["content"]

    def test_export_thread_raises_on_invalid_session(self, client: GoogleAIMClient) -> None:
        session = AIMSession()  # no thread_ei
        with pytest.raises(ValueError, match="Invalid session"):
            client.export_thread(session)

    def test_export_thread_uses_mstk_token(self, client: GoogleAIMClient) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "test-xsrf-token-12345")

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_EXPORT_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            client.export_thread(session)

        call_kwargs = mock_post.call_args
        body = call_kwargs[1].get("data") or (call_kwargs[0][1] if len(call_kwargs[0]) > 1 else "")
        assert "abc123def456" in str(body)


class TestIsCanvasResponse:
    def test_detects_aim_canvas(self, client: GoogleAIMClient) -> None:
        assert client.is_canvas_response('aim/canvas') is True

    def test_detects_canvas_in_thread(self, client: GoogleAIMClient) -> None:
        assert client.is_canvas_response("Canvas is used in this thread") is True

    def test_no_canvas(self, client: GoogleAIMClient) -> None:
        assert client.is_canvas_response("<div>regular response</div>") is False


class TestListThreads:
    def test_list_threads_parses_response(self, client: GoogleAIMClient) -> None:
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_LIST_THREADS_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "post", return_value=mock_resp):
            threads = client.list_threads()

        assert len(threads) == 2
        assert threads[0]["id"] == "thread_ei_1"
        assert threads[0]["title"] == "Thread title 1"
        assert threads[0]["has_canvas"] is True
        assert threads[1]["has_canvas"] is False


class TestCanvasToText:
    def test_strips_html_tags(self, client: GoogleAIMClient) -> None:
        html = "<h1>Title</h1><p>Body text here.</p>"
        text = client.canvas_to_text(html)
        assert "<" not in text
        assert "Title" in text
        assert "Body text here" in text

    def test_decodes_html_entities(self, client: GoogleAIMClient) -> None:
        html = "<p>Hello &amp; world &lt;test&gt;</p>"
        text = client.canvas_to_text(html)
        assert "&amp;" not in text
        assert "Hello & world" in text

    def test_empty_html(self, client: GoogleAIMClient) -> None:
        assert client.canvas_to_text("") == ""


class TestGetAimClientSingleton:
    def test_returns_same_instance(self, mock_cookies: dict) -> None:
        import engine.integrations.google_aim_client as mod
        mod._aim_client = None  # reset

        c1 = get_aim_client(cookies=mock_cookies)
        c2 = get_aim_client()
        assert c1 is c2
        mod._aim_client = None  # clean up


class TestFollowupRewrite:
    def test_followup_rewrite_calls_folwr_url(self, client: GoogleAIMClient) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "test-xsrf-token-12345")

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_FOLIF_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            new_session, html = client.followup_rewrite(session, "Expand section 2")

        called_url = mock_get.call_args[0][0]
        assert "folwr" in called_url

    def test_followup_rewrite_passes_query(self, client: GoogleAIMClient) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "test-xsrf-token-12345")

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_FOLIF_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.followup_rewrite(session, "Rewrite the intro")

        params = mock_get.call_args[1]["params"]
        assert params["q"] == "Rewrite the intro"
        assert params["csuir"] == "1"

    def test_followup_rewrite_raises_on_invalid_session(self, client: GoogleAIMClient) -> None:
        session = AIMSession()
        with pytest.raises(ValueError, match="Invalid session"):
            client.followup_rewrite(session, "anything")

    def test_followup_rewrite_returns_updated_session(self, client: GoogleAIMClient) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "test-xsrf-token-12345")

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_FOLIF_HTML_WITH_CANVAS
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "get", return_value=mock_resp):
            new_session, html = client.followup_rewrite(session, "add more detail")

        assert new_session.query == "add more detail"
        assert new_session.xsrf == "test-xsrf-token-12345"


class TestGetImageViewer:
    def test_get_image_viewer_calls_imgv_url(self, client: GoogleAIMClient) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "test-xsrf")

        mock_resp = MagicMock()
        mock_resp.text = "<html>image panel</html>"
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            html = client.get_image_viewer(session, tbnid="abc123", docid="doc456")

        called_url = mock_get.call_args[0][0]
        assert "imgv" in called_url

    def test_get_image_viewer_passes_tbnid_and_docid(self, client: GoogleAIMClient) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "test-xsrf")

        mock_resp = MagicMock()
        mock_resp.text = "<html>image</html>"
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.get_image_viewer(session, tbnid="thumb1", docid="doc1", query="cats")

        params = mock_get.call_args[1]["params"]
        assert params["tbnid"] == "thumb1"
        assert params["imgdii"] == "thumb1"
        assert params["docid"] == "doc1"
        assert params["q"] == "cats"
        assert params["yv"] == "3"

    def test_get_image_viewer_returns_html(self, client: GoogleAIMClient) -> None:
        session = AIMSession.from_folif_html(SAMPLE_FOLIF_HTML, "test-xsrf")

        mock_resp = MagicMock()
        mock_resp.text = "<html>image panel content</html>"
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.get_image_viewer(session, tbnid="t1", docid="d1")

        assert result == "<html>image panel content</html>"
