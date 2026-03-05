"""Tests for engine.integrations.gsheets_client.

Covers client initialisation, header generation (SAPISIDHASH format),
sheet creation, read/write operations, CSV export, composite helpers,
the factory function, and HTTP error handling.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from engine.integrations.google_account_pool import GoogleAccount
from engine.integrations.gsheets_client import (
    GoogleSheetsClient,
    _DRIVE_BASE,
    _SHEETS_API,
    _SHEETS_ORIGIN,
    get_sheets_client,
)


# ──── Helpers ─────────────────────────────────────────────────────────────────

def _make_account(sapisid: str = "test_sapisid") -> GoogleAccount:
    """Build a minimal GoogleAccount with standard test cookies."""
    return GoogleAccount(
        name="test_account",
        cookies={
            "SAPISID": sapisid,
            "__Secure-1PAPISID": "test_1papisid",
            "__Secure-3PAPISID": "test_3papisid",
        },
        authuser=0,
        services=["sheets"],
    )


def _mock_pool_for(account: GoogleAccount) -> MagicMock:
    """Return a pool mock whose get_cookie_header returns a plausible string."""
    pool = MagicMock()
    pool.get_cookie_header.return_value = "SID=test_sid; SAPISID=test_sapisid"
    return pool


def _resp(
    status_code: int = 200,
    json_data: Any = None,
    text: str = "",
) -> MagicMock:
    """Build a minimal requests.Response mock."""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {}
    r.text = text
    r.raise_for_status.return_value = None
    return r


# ──── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def account() -> GoogleAccount:
    """Provide a reusable test GoogleAccount."""
    return _make_account()


@pytest.fixture
def mock_pool(account: GoogleAccount) -> MagicMock:
    """Mock GoogleAccountPool for header-generation tests."""
    return _mock_pool_for(account)


@pytest.fixture
def client(account: GoogleAccount, mock_pool: MagicMock) -> GoogleSheetsClient:
    """GoogleSheetsClient wired to a mock pool (no real network calls)."""
    with patch(
        "engine.integrations.gsheets_client.get_account_pool",
        return_value=mock_pool,
    ):
        return GoogleSheetsClient(account)


# ──── Tests: __init__ ─────────────────────────────────────────────────────────

class TestGoogleSheetsClientInit:
    """Tests for GoogleSheetsClient.__init__."""

    def test_stores_account_reference(self, account: GoogleAccount) -> None:
        """Constructor should keep a reference to the supplied GoogleAccount."""
        with patch("engine.integrations.gsheets_client.get_account_pool"):
            c = GoogleSheetsClient(account)
        assert c._account is account

    def test_creates_requests_session(self, account: GoogleAccount) -> None:
        """Constructor should create a real requests.Session on _session."""
        with patch("engine.integrations.gsheets_client.get_account_pool"):
            c = GoogleSheetsClient(account)
        assert isinstance(c._session, requests.Session)

    def test_sets_user_agent(self, account: GoogleAccount) -> None:
        """Session User-Agent should include the expected browser string."""
        with patch("engine.integrations.gsheets_client.get_account_pool"):
            c = GoogleSheetsClient(account)
        assert "Mozilla" in c._session.headers.get("User-Agent", "")


# ──── Tests: _get_headers ─────────────────────────────────────────────────────

class TestGetHeaders:
    """Tests for GoogleSheetsClient._get_headers (auth & header construction)."""

    def test_authorization_header_present(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """Authorization header should be present when SAPISID cookie is set."""
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            headers = client._get_headers()
        assert "Authorization" in headers

    def test_authorization_starts_with_sapisidhash(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """Authorization value should begin with the SAPISIDHASH prefix."""
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            headers = client._get_headers()
        assert headers["Authorization"].startswith("SAPISIDHASH")

    def test_sapisidhash_value_format(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """SAPISIDHASH token should follow '{prefix} {timestamp}_{sha1hex}' format."""
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            headers = client._get_headers()
        # Authorization is space-joined: "SAPISIDHASH ts_hex SAPISID1PHASH ts_hex …"
        parts = headers["Authorization"].split()
        # parts[0] == "SAPISIDHASH", parts[1] == "ts_hex"
        assert parts[0] == "SAPISIDHASH"
        ts, hexdig = parts[1].split("_", 1)
        assert ts.isdigit()
        assert len(hexdig) == 40  # SHA-1 produces a 40-char hex digest

    def test_x_same_domain_header(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """X-Same-Domain header must be '1' for same-origin CORS bypass."""
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            headers = client._get_headers()
        assert headers.get("X-Same-Domain") == "1"

    def test_origin_is_docs_google(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """Origin header should point to the Google Docs domain."""
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            headers = client._get_headers()
        assert headers.get("Origin") == _SHEETS_ORIGIN

    def test_extra_headers_are_merged(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """Additional headers passed as the extra argument should appear in the result."""
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            headers = client._get_headers({"Content-Type": "application/json"})
        assert headers.get("Content-Type") == "application/json"

    def test_authuser_header_matches_account(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """X-Goog-Authuser should reflect the account's authuser index."""
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            headers = client._get_headers()
        assert headers.get("X-Goog-Authuser") == "0"


# ──── Tests: create_sheet ─────────────────────────────────────────────────────

class TestCreateSheet:
    """Tests for GoogleSheetsClient.create_sheet."""

    def test_returns_dict_with_id_and_url(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """create_sheet should return a dict containing id, name, mimeType, and url."""
        fake = _resp(json_data={"id": "sheet123", "name": "T", "mimeType": ""})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "post", return_value=fake):
            result = client.create_sheet("T")

        assert result["id"] == "sheet123"
        assert "docs.google.com" in result["url"]
        assert "sheet123" in result["url"]

    def test_posts_to_drive_files_endpoint(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """create_sheet should POST to the Drive v3 /files endpoint."""
        fake = _resp(json_data={"id": "abc", "name": "T", "mimeType": ""})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "post", return_value=fake) as mock_post:
            client.create_sheet("T")
        call_url: str = mock_post.call_args[0][0]
        assert _DRIVE_BASE in call_url
        assert "/files" in call_url

    def test_folder_id_added_to_parents(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """When folder_id is provided, it should appear in 'parents' of the body."""
        fake = _resp(json_data={"id": "abc", "name": "T", "mimeType": ""})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "post", return_value=fake) as mock_post:
            client.create_sheet("T", folder_id="folder999")
        body = mock_post.call_args[1]["json"]
        assert body.get("parents") == ["folder999"]

    def test_http_error_raises(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """HTTP 4xx errors from the Drive API should propagate as requests.HTTPError."""
        err = MagicMock()
        err.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "post", return_value=err):
            with pytest.raises(requests.HTTPError):
                client.create_sheet("Bad")

    def test_url_contains_edit_suffix(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """The generated spreadsheet URL should include /edit for direct opening."""
        fake = _resp(json_data={"id": "sid99", "name": "T", "mimeType": ""})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "post", return_value=fake):
            result = client.create_sheet("T")
        assert "/edit" in result["url"]


# ──── Tests: read_raw / read_rows ─────────────────────────────────────────────

class TestReadRows:
    """Tests for GoogleSheetsClient.read_raw and read_rows."""

    def test_read_raw_returns_list_of_lists(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """read_raw should return the 'values' list from the Sheets v4 API response."""
        fake = _resp(json_data={"values": [["A", "B"], ["1", "2"], ["3", "4"]]})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=fake):
            rows = client.read_raw("sid", "Sheet1")
        assert rows == [["A", "B"], ["1", "2"], ["3", "4"]]

    def test_read_raw_empty_returns_empty_list(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """read_raw should return [] when the API response has no 'values' key."""
        fake = _resp(json_data={})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=fake):
            rows = client.read_raw("sid", "Sheet1")
        assert rows == []

    def test_read_rows_with_headers_returns_dicts(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """read_rows(include_headers=True) should zip header row with data rows."""
        fake = _resp(
            json_data={"values": [["name", "score"], ["Alice", "95"], ["Bob", "80"]]}
        )
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=fake):
            rows = client.read_rows("sid")
        assert rows == [
            {"name": "Alice", "score": "95"},
            {"name": "Bob", "score": "80"},
        ]

    def test_read_rows_without_headers_returns_raw(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """read_rows(include_headers=False) should return raw list-of-lists."""
        raw_data = [["name", "score"], ["Alice", "95"]]
        fake = _resp(json_data={"values": raw_data})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=fake):
            rows = client.read_rows("sid", include_headers=False)
        assert rows == raw_data

    def test_read_rows_pads_short_rows(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """Rows shorter than the header should be padded with empty strings."""
        fake = _resp(json_data={"values": [["a", "b", "c"], ["x"]]})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=fake):
            rows = client.read_rows("sid")
        assert rows[0] == {"a": "x", "b": "", "c": ""}

    def test_read_rows_empty_sheet_returns_empty_list(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """read_rows on an empty sheet should return [] without error."""
        fake = _resp(json_data={})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=fake):
            rows = client.read_rows("sid")
        assert rows == []


# ──── Tests: append_rows ─────────────────────────────────────────────────────

class TestAppendRows:
    """Tests for GoogleSheetsClient.append_rows."""

    def test_empty_rows_short_circuits(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """Passing an empty list should return {updatedRows: 0} with no HTTP call."""
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            result = client.append_rows("sid", [])
        assert result["updatedRows"] == 0

    def test_prepends_column_headers_when_sheet_empty(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """When the sheet has no data, column headers should be written first."""
        empty_get = _resp(json_data={})
        append_post = _resp(json_data={"updates": {"updatedRows": 3}})
        rows = [{"name": "Alice", "score": "95"}, {"name": "Bob", "score": "80"}]

        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=empty_get), \
           patch.object(client._session, "post", return_value=append_post) as mock_post:
            client.append_rows("sid", rows)

        body = mock_post.call_args[1]["json"]
        assert body["values"][0] == ["name", "score"]

    def test_omits_headers_when_sheet_has_data(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """When the sheet already has rows, column headers should NOT be prepended."""
        existing_get = _resp(json_data={"values": [["name", "score"]]})
        append_post = _resp(json_data={"updates": {"updatedRows": 1}})
        rows = [{"name": "Carol", "score": "90"}]

        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=existing_get), \
           patch.object(client._session, "post", return_value=append_post) as mock_post:
            client.append_rows("sid", rows)

        body = mock_post.call_args[1]["json"]
        # Only one data row — no header prepended
        assert body["values"] == [["Carol", "90"]]

    def test_posts_to_append_endpoint(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """append_rows should POST to the Sheets v4 :append endpoint."""
        empty_get = _resp(json_data={})
        append_post = _resp(json_data={"updates": {"updatedRows": 1}})

        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=empty_get), \
           patch.object(client._session, "post", return_value=append_post) as mock_post:
            client.append_rows("sid", [{"k": "v"}])

        call_url: str = mock_post.call_args[0][0]
        assert ":append" in call_url


# ──── Tests: write_rows ───────────────────────────────────────────────────────

class TestWriteRows:
    """Tests for GoogleSheetsClient.write_rows."""

    def test_empty_rows_short_circuits(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """Empty input should return {updatedRows: 0} with no HTTP call."""
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            result = client.write_rows("sid", [])
        assert result["updatedRows"] == 0

    def test_writes_headers_then_data_rows(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """write_rows should PUT headers as the first row, then all data rows."""
        put_resp = _resp(json_data={"updatedRows": 3})
        rows = [{"x": "1", "y": "2"}, {"x": "3", "y": "4"}]

        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "put", return_value=put_resp) as mock_put:
            client.write_rows("sid", rows)

        body = mock_put.call_args[1]["json"]
        assert body["values"][0] == ["x", "y"]   # header
        assert body["values"][1] == ["1", "2"]   # first data row
        assert body["values"][2] == ["3", "4"]   # second data row

    def test_start_row_appears_in_range_notation(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """write_rows should embed start_row in the A1-notation URL."""
        put_resp = _resp(json_data={"updatedRows": 1})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "put", return_value=put_resp) as mock_put:
            client.write_rows("sid", [{"k": "v"}], "Data", start_row=7)

        call_url: str = mock_put.call_args[0][0]
        assert "A7" in call_url

    def test_uses_put_not_post(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """write_rows must use PUT (overwrite), not POST (append)."""
        put_resp = _resp(json_data={"updatedRows": 1})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "put", return_value=put_resp) as mock_put, \
           patch.object(client._session, "post") as mock_post:
            client.write_rows("sid", [{"k": "v"}])
        mock_put.assert_called_once()
        mock_post.assert_not_called()


# ──── Tests: get_shareable_url ────────────────────────────────────────────────

class TestShareableUrl:
    """Tests for GoogleSheetsClient.get_shareable_url."""

    def test_returns_docs_google_com_url(self, client: GoogleSheetsClient) -> None:
        """get_shareable_url should return a docs.google.com spreadsheet URL."""
        url = client.get_shareable_url("sheet_abc")
        assert url.startswith("https://docs.google.com/spreadsheets/d/sheet_abc")

    def test_url_contains_sheet_id(self, client: GoogleSheetsClient) -> None:
        """The sheet ID should be embedded in the shareable URL."""
        url = client.get_shareable_url("my_sheet_id")
        assert "my_sheet_id" in url

    def test_url_includes_usp_sharing_param(self, client: GoogleSheetsClient) -> None:
        """Shareable URL should include the usp=sharing query parameter."""
        url = client.get_shareable_url("sid")
        assert "usp=sharing" in url


# ──── Tests: export_as_csv ────────────────────────────────────────────────────

class TestExportAsCsv:
    """Tests for GoogleSheetsClient.export_as_csv."""

    def test_returns_response_text(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """export_as_csv should return the raw CSV text from the response."""
        csv_body = "name,score\nAlice,95\nBob,80\n"
        fake = _resp(text=csv_body)
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=fake):
            result = client.export_as_csv("sid", "Sheet1")
        assert result == csv_body

    def test_sends_format_csv_param(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """Request params should include format=csv."""
        fake = _resp(text="a,b\n1,2\n")
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=fake) as mock_get:
            client.export_as_csv("sid", "Sheet1")
        params = mock_get.call_args[1]["params"]
        assert params.get("format") == "csv"

    def test_passes_sheet_name_in_params(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """Request params should pass the sheet tab name."""
        fake = _resp(text="x\n1\n")
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "get", return_value=fake) as mock_get:
            client.export_as_csv("sid", "MyTab")
        params = mock_get.call_args[1]["params"]
        assert params.get("sheet") == "MyTab"


# ──── Tests: create_from_data ─────────────────────────────────────────────────

class TestCreateFromData:
    """Tests for GoogleSheetsClient.create_from_data."""

    def test_returns_id_url_and_rows_written(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """create_from_data should return a dict with id, url, and rows_written."""
        create_post = _resp(
            json_data={"id": "newsheet", "name": "DS", "mimeType": ""}
        )
        empty_get = _resp(json_data={})  # sheet is empty → headers prepended
        append_post = _resp(json_data={"updates": {"updatedRows": 3}})

        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(
            client._session, "post", side_effect=[create_post, append_post]
        ), patch.object(client._session, "get", return_value=empty_get):
            result = client.create_from_data(
                "DS",
                [{"col": "v1"}, {"col": "v2"}],
            )

        assert result["id"] == "newsheet"
        assert "docs.google.com" in result["url"]
        assert "rows_written" in result

    def test_calls_create_sheet_first(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """create_from_data should call create_sheet before appending rows."""
        create_post = _resp(json_data={"id": "s1", "name": "X", "mimeType": ""})
        empty_get = _resp(json_data={})
        append_post = _resp(json_data={"updates": {"updatedRows": 1}})

        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(
            client._session, "post", side_effect=[create_post, append_post]
        ) as mock_post, patch.object(client._session, "get", return_value=empty_get):
            client.create_from_data("X", [{"k": "v"}])

        # First POST = create_sheet to /files; second POST = append
        first_url: str = mock_post.call_args_list[0][0][0]
        assert "/files" in first_url


# ──── Tests: clear_sheet ──────────────────────────────────────────────────────

class TestClearSheet:
    """Tests for GoogleSheetsClient.clear_sheet."""

    def test_returns_true_on_success(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """clear_sheet should return True when the API responds with 200."""
        fake = _resp(json_data={"clearedRange": "Sheet1!A1:Z1000"})
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "post", return_value=fake):
            assert client.clear_sheet("sid", "Sheet1") is True

    def test_returns_false_on_http_error(
        self, client: GoogleSheetsClient, mock_pool: MagicMock
    ) -> None:
        """clear_sheet should return False (not raise) when the API returns an error."""
        err = MagicMock()
        err.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ), patch.object(client._session, "post", return_value=err):
            assert client.clear_sheet("sid", "Sheet1") is False


# ──── Tests: get_sheets_client factory ───────────────────────────────────────

class TestGetSheetsClient:
    """Tests for the get_sheets_client module-level factory function."""

    def test_returns_client_when_account_available(self) -> None:
        """get_sheets_client should return a GoogleSheetsClient when the pool has an account."""
        account = _make_account()
        mock_pool = MagicMock()
        mock_pool.get_account.return_value = account
        mock_pool.get_by_name.return_value = None
        mock_pool.get_cookie_header.return_value = "SID=x"

        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            c = get_sheets_client()

        assert isinstance(c, GoogleSheetsClient)

    def test_returns_none_when_no_account_available(self) -> None:
        """get_sheets_client should return None when no account is in the pool."""
        mock_pool = MagicMock()
        mock_pool.get_account.return_value = None
        mock_pool.get_by_name.return_value = None

        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            c = get_sheets_client()

        assert c is None

    def test_uses_named_account_via_get_by_name(self) -> None:
        """When account_name is given, the pool's get_by_name method should be called."""
        account = _make_account()
        mock_pool = MagicMock()
        mock_pool.get_by_name.return_value = account
        mock_pool.get_cookie_header.return_value = "SID=x"

        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            c = get_sheets_client("my_account")

        mock_pool.get_by_name.assert_called_once_with("my_account")
        assert isinstance(c, GoogleSheetsClient)

    def test_returns_none_when_named_account_missing(self) -> None:
        """get_sheets_client should return None when the named account is not found."""
        mock_pool = MagicMock()
        mock_pool.get_by_name.return_value = None

        with patch(
            "engine.integrations.gsheets_client.get_account_pool",
            return_value=mock_pool,
        ):
            c = get_sheets_client("ghost_account")

        assert c is None
