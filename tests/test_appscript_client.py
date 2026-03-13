"""Tests for the Apps Script batchexecute client.

Covers:
- Client import and construction
- SAPISIDHASH auth header generation
- batchexecute protocol (request building, response parsing)
- All 14 public methods with mocked HTTP
- Factory function (get_appscript_client)
- Error handling (HTTP errors, malformed responses)
"""
from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import requests


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_account() -> MagicMock:
    """GoogleAccount with standard test cookies."""
    from engine.integrations.google_account_pool import GoogleAccount

    return GoogleAccount(
        name="test_appscript",
        cookies={
            "SID": "test_sid",
            "HSID": "test_hsid",
            "SSID": "test_ssid",
            "APISID": "test_apisid",
            "SAPISID": "test_sapisid",
            "__Secure-1PAPISID": "test_1papisid",
            "__Secure-3PAPISID": "test_3papisid",
        },
        authuser=0,
        services=["appscript"],
    )


@pytest.fixture
def client(mock_account):
    """AppsScriptClient with mocked account and pool."""
    from engine.integrations.appscript_client import AppsScriptClient

    with patch("engine.integrations.appscript_client.get_account_pool") as mock_pool_fn:
        pool = MagicMock()
        pool.get_cookie_header.return_value = "SID=test_sid; SAPISID=test_sapisid"
        mock_pool_fn.return_value = pool
        c = AppsScriptClient(mock_account)
        # Also patch the pool call inside _get_headers
        c._pool_patcher = patch(
            "engine.integrations.google_account_pool.get_account_pool",
            return_value=pool,
        )
        c._pool_patcher.start()
    return c


@pytest.fixture(autouse=True)
def _cleanup_pool_patcher(client):
    """Stop pool patcher after each test."""
    yield
    if hasattr(client, "_pool_patcher"):
        client._pool_patcher.stop()


def _wrap_batchexecute_response(inner: Any) -> str:
    """Build a batchexecute response body with XSSI prefix and wrb.fr wrapper."""
    inner_json = json.dumps(inner)
    outer = json.dumps([["wrb.fr", "rpcid", inner_json]])
    return ")]}'\n" + outer


def _mock_post_response(inner: Any, status_code: int = 200) -> MagicMock:
    """Create a mock requests.Response for a batchexecute call."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = _wrap_batchexecute_response(inner)
    resp.raise_for_status.return_value = None
    return resp


# ──── Import Tests ────────────────────────────────────────────────────────────


def test_import_client_and_factory(client):
    """Module exports AppsScriptClient and get_appscript_client."""
    from engine.integrations.appscript_client import AppsScriptClient, get_appscript_client

    assert AppsScriptClient is not None
    assert get_appscript_client is not None


def test_client_construction(client):
    """Client initialises with a GoogleAccount and creates a requests.Session."""
    assert client is not None
    assert client._account.name == "test_appscript"
    assert client._session is not None


# ──── Auth Header Tests ───────────────────────────────────────────────────────


def test_get_headers_contains_auth(client):
    """_get_headers builds SAPISIDHASH Authorization header."""
    headers = client._get_headers()

    assert "Authorization" in headers
    assert "SAPISIDHASH " in headers["Authorization"]
    assert "SAPISID1PHASH " in headers["Authorization"]
    assert "SAPISID3PHASH " in headers["Authorization"]


def test_get_headers_contains_cookie(client):
    """_get_headers includes the Cookie header from the pool."""
    headers = client._get_headers()

    assert headers["Cookie"] == "SID=test_sid; SAPISID=test_sapisid"


def test_get_headers_sets_content_type(client):
    """_get_headers sets form-urlencoded Content-Type."""
    headers = client._get_headers()

    assert "application/x-www-form-urlencoded" in headers["Content-Type"]


def test_get_headers_merges_extra(client):
    """_get_headers merges extra headers when provided."""
    headers = client._get_headers(extra={"X-Custom": "value"})

    assert headers["X-Custom"] == "value"


def test_get_headers_sets_authuser(client):
    """_get_headers includes x-goog-authuser from account."""
    headers = client._get_headers()

    assert headers["X-Goog-Authuser"] == "0"


# ──── batchexecute Protocol Tests ─────────────────────────────────────────────


def test_batchexecute_builds_url_with_project_id(client):
    """_batchexecute uses /macros/d/{project_id}/data/batchexecute when project_id given."""
    mock_resp = _mock_post_response(["ok"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client._batchexecute("TestRPC", ["payload"], project_id="proj-123")

    call_args = mock_post.call_args
    assert "/macros/d/proj-123/data/batchexecute" in call_args[0][0]


def test_batchexecute_builds_url_without_project_id(client):
    """_batchexecute uses /data/batchexecute when no project_id given."""
    mock_resp = _mock_post_response(["ok"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client._batchexecute("TestRPC", ["payload"])

    call_args = mock_post.call_args
    url = call_args[0][0]
    assert url.endswith("/data/batchexecute")
    assert "/macros/d/" not in url


def test_batchexecute_sends_rpcid_in_params(client):
    """_batchexecute includes the rpcid in query params."""
    mock_resp = _mock_post_response(["ok"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client._batchexecute("OOPYjd", ["payload"])

    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["params"]["rpcids"] == "OOPYjd"


def test_batchexecute_sends_envelope_in_body(client):
    """_batchexecute sends f.req form data with the JSON envelope."""
    mock_resp = _mock_post_response(["ok"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client._batchexecute("TestRPC", [42, "hello"])

    call_kwargs = mock_post.call_args[1]
    freq_data = call_kwargs["data"]["f.req"]
    parsed = json.loads(freq_data)
    assert parsed[0][0] == "TestRPC"
    inner_payload = json.loads(parsed[0][1])
    assert inner_payload == [42, "hello"]


def test_batchexecute_raises_on_http_error(client):
    """_batchexecute propagates HTTP errors."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")

    with patch.object(client._session, "post", return_value=mock_resp):
        with pytest.raises(requests.HTTPError):
            client._batchexecute("TestRPC", [])


# ──── Response Parsing Tests ──────────────────────────────────────────────────


def test_parse_batchexecute_strips_xssi_prefix(client):
    """_parse_batchexecute strips the )]}' anti-XSSI prefix."""
    inner = ["result_data"]
    raw = _wrap_batchexecute_response(inner)

    result = client._parse_batchexecute(raw)

    assert result == inner


def test_parse_batchexecute_handles_missing_xssi_prefix(client):
    """_parse_batchexecute works when response lacks the XSSI prefix."""
    inner = ["result_data"]
    inner_json = json.dumps(inner)
    raw = json.dumps([["wrb.fr", "rpcid", inner_json]])

    result = client._parse_batchexecute(raw)

    assert result == inner


def test_parse_batchexecute_returns_none_on_invalid_json(client):
    """_parse_batchexecute returns None for unparseable responses."""
    result = client._parse_batchexecute("not valid json at all {{{{")

    assert result is None


def test_parse_batchexecute_returns_string_if_inner_not_json(client):
    """_parse_batchexecute returns raw string when inner payload is not JSON."""
    raw = json.dumps([["wrb.fr", "rpcid", "just a plain string"]])

    result = client._parse_batchexecute(raw)

    assert result == "just a plain string"


def test_parse_batchexecute_returns_outer_when_no_wrbfr(client):
    """_parse_batchexecute returns outer array when no wrb.fr wrapper found."""
    outer = [["other_tag", None, "data"]]
    raw = json.dumps(outer)

    result = client._parse_batchexecute(raw)

    assert result == outer


# ──── list_executions ─────────────────────────────────────────────────────────


def test_list_executions_returns_parsed_entries(client):
    """list_executions parses execution entries from response."""
    inner = [[
        ["exec-1", "myFunction", 1, "2025-01-01T00:00:00Z", 1234],
        ["exec-2", "otherFn", 2, "2025-01-02T00:00:00Z", 5678],
    ]]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.list_executions("proj-123")

    assert len(result) == 2
    assert result[0]["execution_id"] == "exec-1"
    assert result[0]["function"] == "myFunction"
    assert result[0]["status"] == 1
    assert result[0]["duration_ms"] == 1234
    assert result[1]["execution_id"] == "exec-2"


def test_list_executions_with_status_filters(client):
    """list_executions passes status_filters in the payload."""
    inner = [[]]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.list_executions("proj-123", status_filters=[1, 2])

    call_kwargs = mock_post.call_args[1]
    freq = json.loads(call_kwargs["data"]["f.req"])
    payload = json.loads(freq[0][1])
    assert payload[0][6] == [1, 2]


def test_list_executions_handles_non_list_response(client):
    """list_executions returns empty list on non-list response."""
    mock_resp = _mock_post_response("unexpected string")

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.list_executions("proj-123")

    assert result == []


def test_list_executions_handles_empty_response(client):
    """list_executions returns empty list on empty array."""
    mock_resp = _mock_post_response([])

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.list_executions("proj-123")

    assert result == []


# ──── run_function ────────────────────────────────────────────────────────────


def test_run_function_returns_execution_id(client):
    """run_function extracts execution_id from response."""
    inner = ["exec-abc", "result_value", None]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.run_function("proj-123", "doStuff")

    assert result["execution_id"] == "exec-abc"
    assert result["result"] == "result_value"
    assert "error" not in result  # None is not stored


def test_run_function_captures_error(client):
    """run_function extracts error from response when present."""
    inner = ["exec-err", None, "Script error: ReferenceError"]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.run_function("proj-err", "badFn")

    assert result["execution_id"] == "exec-err"
    assert result["error"] == "Script error: ReferenceError"


def test_run_function_sends_correct_rpcid(client):
    """run_function uses _RPCID_RUN_FUNCTION ('pEig0e')."""
    mock_resp = _mock_post_response(["exec-id"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.run_function("proj-123", "myFunc")

    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["params"]["rpcids"] == "pEig0e"


def test_run_function_sends_project_and_function_in_payload(client):
    """run_function embeds project_id and function_name in payload."""
    mock_resp = _mock_post_response(["exec-id"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.run_function("proj-XYZ", "myFunction")

    call_kwargs = mock_post.call_args[1]
    freq = json.loads(call_kwargs["data"]["f.req"])
    payload = json.loads(freq[0][1])
    assert payload[6] == ["proj-XYZ", "myFunction"]


# ──── get_project_files ───────────────────────────────────────────────────────


def test_get_project_files_returns_file_list(client):
    """get_project_files parses file entries from response."""
    inner = [[
        ["file-1", "Code.gs", "server_js", "function main() {}"],
        ["file-2", "Utils.gs", "server_js", "function helper() {}"],
    ]]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.get_project_files("proj-123")

    assert len(result) == 2
    assert result[0]["file_id"] == "file-1"
    assert result[0]["name"] == "Code.gs"
    assert result[0]["type"] == "server_js"
    assert result[0]["source"] == "function main() {}"
    assert result[1]["file_id"] == "file-2"


def test_get_project_files_handles_non_list_response(client):
    """get_project_files returns empty list on non-list response."""
    mock_resp = _mock_post_response(None)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.get_project_files("proj-123")

    assert result == []


def test_get_project_files_uses_correct_rpcid(client):
    """get_project_files uses _RPCID_GET_PROJECT_FILES ('OQOG2e')."""
    mock_resp = _mock_post_response([[]])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.get_project_files("proj-123")

    assert mock_post.call_args[1]["params"]["rpcids"] == "OQOG2e"


# ──── save_code ───────────────────────────────────────────────────────────────


def test_save_code_sends_encoded_content(client):
    """save_code sends encoded content string in payload."""
    mock_resp = _mock_post_response(["saved"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        result = client.save_code("encoded-file-data-here", project_id="proj-123")

    call_kwargs = mock_post.call_args[1]
    freq = json.loads(call_kwargs["data"]["f.req"])
    payload = json.loads(freq[0][1])
    assert payload == ["encoded-file-data-here"]
    assert result == ["saved"]


def test_save_code_uses_correct_rpcid(client):
    """save_code uses _RPCID_SAVE_CODE ('toGAmc')."""
    mock_resp = _mock_post_response(["ok"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.save_code("data")

    assert mock_post.call_args[1]["params"]["rpcids"] == "toGAmc"


def test_save_code_without_project_id(client):
    """save_code works without a project_id, using default URL."""
    mock_resp = _mock_post_response(["ok"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.save_code("data")

    url = mock_post.call_args[0][0]
    assert "/macros/d/" not in url


# ──── get_project_info ────────────────────────────────────────────────────────


def test_get_project_info_returns_metadata(client):
    """get_project_info parses title, owner, timestamps."""
    inner = ["My Project", "user@gmail.com", "2025-01-01", "2025-06-15"]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.get_project_info("proj-123")

    assert result["project_id"] == "proj-123"
    assert result["title"] == "My Project"
    assert result["owner"] == "user@gmail.com"
    assert result["create_time"] == "2025-01-01"
    assert result["update_time"] == "2025-06-15"


def test_get_project_info_uses_correct_rpcid(client):
    """get_project_info uses _RPCID_GET_PROJECT_INFO ('NFMk7c')."""
    mock_resp = _mock_post_response([])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.get_project_info("proj-123")

    assert mock_post.call_args[1]["params"]["rpcids"] == "NFMk7c"


def test_get_project_info_handles_non_list(client):
    """get_project_info returns base dict when response is not a list."""
    mock_resp = _mock_post_response("unexpected")

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.get_project_info("proj-123")

    assert result["project_id"] == "proj-123"
    assert "title" not in result


# ──── get_project_metadata ────────────────────────────────────────────────────


def test_get_project_metadata_returns_extended_info(client):
    """get_project_metadata parses container and deployment info."""
    inner = ["Title", "sheets", "container-id", "parent-id", {"deploy": True}]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.get_project_metadata("proj-123")

    assert result["project_id"] == "proj-123"
    assert result["title"] == "Title"
    assert result["container_type"] == "sheets"
    assert result["container_id"] == "container-id"
    assert result["parent_id"] == "parent-id"
    assert result["deployment_info"] == {"deploy": True}


def test_get_project_metadata_uses_correct_rpcid(client):
    """get_project_metadata uses _RPCID_GET_PROJECT_METADATA ('AvwHP')."""
    mock_resp = _mock_post_response([])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.get_project_metadata("proj-123")

    assert mock_post.call_args[1]["params"]["rpcids"] == "AvwHP"


# ──── save_project ────────────────────────────────────────────────────────────


def test_save_project_sends_files_and_title(client):
    """save_project encodes files and title in payload."""
    mock_resp = _mock_post_response(["saved"])
    files = [
        {"id": "f1", "name": "Code.gs", "type": "server_js", "source": "// code"},
        {"name": "Page.html", "type": "html", "source": "<html>"},
    ]

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        result = client.save_project("proj-123", "My Project", files)

    call_kwargs = mock_post.call_args[1]
    freq = json.loads(call_kwargs["data"]["f.req"])
    payload = json.loads(freq[0][1])
    assert payload[0] == "proj-123"
    assert payload[1] == "My Project"
    assert len(payload[2]) == 2
    assert payload[2][0] == ["f1", "Code.gs", "server_js", "// code"]
    assert payload[2][1] == [None, "Page.html", "html", "<html>"]
    assert result == ["saved"]


def test_save_project_with_settings(client):
    """save_project includes settings when provided."""
    mock_resp = _mock_post_response(["saved"])
    settings = {"timezone": "UTC", "runtime_version": "V8", "dependencies": []}

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.save_project("proj-123", "Title", [], settings=settings)

    call_kwargs = mock_post.call_args[1]
    freq = json.loads(call_kwargs["data"]["f.req"])
    payload = json.loads(freq[0][1])
    assert payload[3] == ["UTC", "V8", []]


def test_save_project_without_settings(client):
    """save_project sends None settings when not provided."""
    mock_resp = _mock_post_response(["saved"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.save_project("proj-123", "Title", [])

    call_kwargs = mock_post.call_args[1]
    freq = json.loads(call_kwargs["data"]["f.req"])
    payload = json.loads(freq[0][1])
    assert payload[3] is None


def test_save_project_uses_correct_rpcid(client):
    """save_project uses _RPCID_SAVE_PROJECT ('GXx9jd')."""
    mock_resp = _mock_post_response(["ok"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.save_project("p", "t", [])

    assert mock_post.call_args[1]["params"]["rpcids"] == "GXx9jd"


# ──── get_project_settings ────────────────────────────────────────────────────


def test_get_project_settings_returns_settings(client):
    """get_project_settings parses timezone, runtime, dependencies."""
    inner = ["America/New_York", "V8", ["OAuth2"], "STACKDRIVER"]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.get_project_settings("proj-123")

    assert result["project_id"] == "proj-123"
    assert result["timezone"] == "America/New_York"
    assert result["runtime_version"] == "V8"
    assert result["dependencies"] == ["OAuth2"]
    assert result["exception_logging"] == "STACKDRIVER"


def test_get_project_settings_uses_correct_rpcid(client):
    """get_project_settings uses _RPCID_GET_PROJECT_SETTINGS ('UvGaob')."""
    mock_resp = _mock_post_response([])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.get_project_settings("proj-123")

    assert mock_post.call_args[1]["params"]["rpcids"] == "UvGaob"


# ──── get_editor_state ────────────────────────────────────────────────────────


def test_get_editor_state_returns_state(client):
    """get_editor_state parses active_file, open_files, cursor."""
    inner = ["Code.gs", ["Code.gs", "Utils.gs"], {"line": 10, "col": 5}]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.get_editor_state(project_id="proj-123")

    assert result["active_file"] == "Code.gs"
    assert result["open_files"] == ["Code.gs", "Utils.gs"]
    assert result["cursor_position"] == {"line": 10, "col": 5}


def test_get_editor_state_uses_correct_rpcid(client):
    """get_editor_state uses _RPCID_GET_EDITOR_STATE ('LuHlxe')."""
    mock_resp = _mock_post_response([])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.get_editor_state()

    assert mock_post.call_args[1]["params"]["rpcids"] == "LuHlxe"


def test_get_editor_state_sends_s_payload(client):
    """get_editor_state sends ['s'] as the payload."""
    mock_resp = _mock_post_response([])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.get_editor_state()

    call_kwargs = mock_post.call_args[1]
    freq = json.loads(call_kwargs["data"]["f.req"])
    payload = json.loads(freq[0][1])
    assert payload == ["s"]


# ──── update_cursor ───────────────────────────────────────────────────────────


def test_update_cursor_sends_position(client):
    """update_cursor sends start, end, and viewport width in payload."""
    mock_resp = _mock_post_response(["ack"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        result = client.update_cursor(10, 25, viewport_width=120, project_id="proj-123")

    call_kwargs = mock_post.call_args[1]
    freq = json.loads(call_kwargs["data"]["f.req"])
    payload = json.loads(freq[0][1])
    assert payload == [10, 25, None, 120]
    assert result == ["ack"]


def test_update_cursor_default_viewport(client):
    """update_cursor defaults viewport_width to 80."""
    mock_resp = _mock_post_response(["ack"])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.update_cursor(0, 0)

    call_kwargs = mock_post.call_args[1]
    freq = json.loads(call_kwargs["data"]["f.req"])
    payload = json.loads(freq[0][1])
    assert payload[3] == 80


def test_update_cursor_uses_correct_rpcid(client):
    """update_cursor uses _RPCID_UPDATE_CURSOR ('ivJzse')."""
    mock_resp = _mock_post_response([])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.update_cursor(0, 0)

    assert mock_post.call_args[1]["params"]["rpcids"] == "ivJzse"


# ──── page_init ───────────────────────────────────────────────────────────────


def test_page_init_returns_init_data(client):
    """page_init returns parsed initialisation payload."""
    inner = {"config": "value", "features": ["edit", "run"]}
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.page_init(project_id="proj-123")

    assert result == inner


def test_page_init_sends_empty_payload(client):
    """page_init sends an empty list as payload."""
    mock_resp = _mock_post_response([])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.page_init()

    call_kwargs = mock_post.call_args[1]
    freq = json.loads(call_kwargs["data"]["f.req"])
    payload = json.loads(freq[0][1])
    assert payload == []


def test_page_init_uses_correct_rpcid(client):
    """page_init uses _RPCID_PAGE_INIT ('AJ6bre')."""
    mock_resp = _mock_post_response([])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.page_init()

    assert mock_post.call_args[1]["params"]["rpcids"] == "AJ6bre"


# ──── list_triggers ───────────────────────────────────────────────────────────


def test_list_triggers_returns_trigger_entries(client):
    """list_triggers parses trigger entries from response."""
    inner = [[
        ["trig-1", "onEdit", "EDIT", "spreadsheet"],
        ["trig-2", "onOpen", "OPEN", "document"],
    ]]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.list_triggers("proj-123")

    assert len(result) == 2
    assert result[0]["trigger_id"] == "trig-1"
    assert result[0]["function"] == "onEdit"
    assert result[0]["event_type"] == "EDIT"
    assert result[0]["source"] == "spreadsheet"
    assert result[1]["trigger_id"] == "trig-2"


def test_list_triggers_handles_non_list(client):
    """list_triggers returns empty list on non-list response."""
    mock_resp = _mock_post_response("unexpected")

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.list_triggers("proj-123")

    assert result == []


def test_list_triggers_uses_correct_rpcid(client):
    """list_triggers uses _RPCID_LIST_TRIGGERS ('KKLVD')."""
    mock_resp = _mock_post_response([[]])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.list_triggers("proj-123")

    assert mock_post.call_args[1]["params"]["rpcids"] == "KKLVD"


# ──── list_versions ───────────────────────────────────────────────────────────


def test_list_versions_returns_version_entries(client):
    """list_versions parses version entries from response."""
    inner = [[
        [1, "Initial version", "2025-01-01"],
        [2, "Bug fix", "2025-02-15"],
        [3, "Feature add", "2025-06-01"],
    ]]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.list_versions("proj-123")

    assert len(result) == 3
    assert result[0]["version_number"] == 1
    assert result[0]["description"] == "Initial version"
    assert result[0]["create_time"] == "2025-01-01"
    assert result[2]["version_number"] == 3


def test_list_versions_handles_non_list(client):
    """list_versions returns empty list on non-list response."""
    mock_resp = _mock_post_response(42)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.list_versions("proj-123")

    assert result == []


def test_list_versions_uses_correct_rpcid(client):
    """list_versions uses _RPCID_LIST_VERSIONS ('zzomTc')."""
    mock_resp = _mock_post_response([[]])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.list_versions("proj-123")

    assert mock_post.call_args[1]["params"]["rpcids"] == "zzomTc"


# ──── get_project_history ─────────────────────────────────────────────────────


def test_get_project_history_returns_history_entries(client):
    """get_project_history parses revision entries from response."""
    inner = [[
        ["rev-1", "alice@gmail.com", "2025-01-01T12:00:00Z", "edit"],
        ["rev-2", "bob@gmail.com", "2025-01-02T14:30:00Z", "create"],
    ]]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.get_project_history("proj-123")

    assert len(result) == 2
    assert result[0]["revision_id"] == "rev-1"
    assert result[0]["author"] == "alice@gmail.com"
    assert result[0]["timestamp"] == "2025-01-01T12:00:00Z"
    assert result[0]["change_type"] == "edit"
    assert result[1]["revision_id"] == "rev-2"


def test_get_project_history_handles_non_list(client):
    """get_project_history returns empty list on non-list response."""
    mock_resp = _mock_post_response("not a list")

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.get_project_history("proj-123")

    assert result == []


def test_get_project_history_uses_correct_rpcid(client):
    """get_project_history uses _RPCID_GET_PROJECT_HISTORY ('yFXSbd')."""
    mock_resp = _mock_post_response([[]])

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.get_project_history("proj-123")

    assert mock_post.call_args[1]["params"]["rpcids"] == "yFXSbd"


# ──── Factory Function Tests ─────────────────────────────────────────────────


def test_get_appscript_client_returns_client_when_account_available():
    """get_appscript_client returns an AppsScriptClient when pool has an account."""
    from engine.integrations.google_account_pool import GoogleAccount

    account = GoogleAccount(
        name="factory_test",
        cookies={"SAPISID": "sapisid"},
        services=["appscript"],
    )

    with patch("engine.integrations.appscript_client.get_account_pool") as mock_pool_fn:
        pool = MagicMock()
        pool.get_account.return_value = account
        mock_pool_fn.return_value = pool

        from engine.integrations.appscript_client import get_appscript_client
        result = get_appscript_client()

    assert result is not None
    assert result._account.name == "factory_test"


def test_get_appscript_client_returns_none_when_no_account():
    """get_appscript_client returns None when no appscript account in pool."""
    with patch("engine.integrations.appscript_client.get_account_pool") as mock_pool_fn:
        pool = MagicMock()
        pool.get_account.return_value = None
        mock_pool_fn.return_value = pool

        from engine.integrations.appscript_client import get_appscript_client
        result = get_appscript_client()

    assert result is None


def test_get_appscript_client_with_specific_account_name():
    """get_appscript_client uses get_by_name when account_name is given."""
    from engine.integrations.google_account_pool import GoogleAccount

    account = GoogleAccount(
        name="specific_user",
        cookies={"SAPISID": "sapisid"},
        services=["appscript"],
    )

    with patch("engine.integrations.appscript_client.get_account_pool") as mock_pool_fn:
        pool = MagicMock()
        pool.get_by_name.return_value = account
        mock_pool_fn.return_value = pool

        from engine.integrations.appscript_client import get_appscript_client
        result = get_appscript_client(account_name="specific_user")

    pool.get_by_name.assert_called_once_with("specific_user")
    assert result._account.name == "specific_user"


def test_get_appscript_client_named_account_not_found():
    """get_appscript_client returns None when named account doesn't exist."""
    with patch("engine.integrations.appscript_client.get_account_pool") as mock_pool_fn:
        pool = MagicMock()
        pool.get_by_name.return_value = None
        mock_pool_fn.return_value = pool

        from engine.integrations.appscript_client import get_appscript_client
        result = get_appscript_client(account_name="ghost")

    assert result is None


# ──── Error Handling Tests ────────────────────────────────────────────────────


def test_http_error_propagates_through_public_methods(client):
    """HTTP errors from batchexecute bubble up through public methods."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")

    with patch.object(client._session, "post", return_value=mock_resp):
        with pytest.raises(requests.HTTPError, match="403"):
            client.list_executions("proj-123")


def test_connection_error_propagates(client):
    """Connection errors bubble up from session.post."""
    with patch.object(
        client._session, "post",
        side_effect=requests.ConnectionError("DNS resolution failed"),
    ):
        with pytest.raises(requests.ConnectionError):
            client.get_project_info("proj-123")


def test_timeout_error_propagates(client):
    """Timeout errors bubble up from session.post."""
    with patch.object(
        client._session, "post",
        side_effect=requests.Timeout("Read timed out"),
    ):
        with pytest.raises(requests.Timeout):
            client.page_init()


def test_malformed_response_returns_none(client):
    """Completely invalid response body is handled gracefully."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.text = "this is not json at all"
    mock_resp.raise_for_status.return_value = None

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.page_init()

    assert result is None


def test_empty_response_body_returns_none(client):
    """Empty response body is handled gracefully."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_resp.raise_for_status.return_value = None

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.page_init()

    assert result is None


# ──── Edge Cases ──────────────────────────────────────────────────────────────


def test_list_methods_skip_non_list_items(client):
    """List-returning methods skip non-list items in the response array."""
    inner = [[["valid-id", "name", "type"], "not-a-list", 42, None]]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.get_project_files("proj-123")

    assert len(result) == 1
    assert result[0]["file_id"] == "valid-id"


def test_partial_list_items_parsed_safely(client):
    """List-returning methods handle items with fewer fields than expected."""
    inner = [[["only-id"]]]
    mock_resp = _mock_post_response(inner)

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.get_project_files("proj-123")

    assert len(result) == 1
    assert result[0]["file_id"] == "only-id"
    assert "name" not in result[0]
    assert "type" not in result[0]
    assert "source" not in result[0]


def test_run_function_handles_non_list_response(client):
    """run_function gracefully handles non-list data."""
    mock_resp = _mock_post_response("scalar response")

    with patch.object(client._session, "post", return_value=mock_resp):
        result = client.run_function("proj-123", "fn")

    assert result["raw"] == "scalar response"
    assert "execution_id" not in result
