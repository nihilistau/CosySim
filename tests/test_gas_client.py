"""Tests for engine.integrations.gas_client — Google Apps Script SDK."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

from engine.integrations.gas_client import (
    GASClient,
    GASDeployment,
    GASFile,
    GASProject,
    GASTrigger,
    GAS_BATCH_URL,
    GAS_BASE_URL,
    GAS_RPCIDS,
    _safe_str,
    get_gas_client,
)
from engine.integrations.google_account_pool import GoogleAccount


# ──── Fixtures ────────────────────────────────────────────────────────────────

def _make_account(
    name: str = "test_account",
    sapisid: str = "test_sapisid_value",
) -> GoogleAccount:
    """Build a test GoogleAccount with minimal cookie set."""
    return GoogleAccount(
        name=name,
        cookies={
            "__Secure-1PAPISID": sapisid,
            "SID": "test-sid-value",
            "SAPISID": sapisid,
        },
        authuser=0,
        services=["gas"],
    )


@pytest.fixture
def account():
    """Minimal GoogleAccount for GASClient construction."""
    return _make_account()


@pytest.fixture
def mock_pool():
    """Mock GoogleAccountPool returned by get_account_pool()."""
    pool = MagicMock()
    pool.get_cookie_header.return_value = "SID=test-sid-value; SAPISID=test_sapisid_value"
    return pool


@pytest.fixture
def gas_client(account, mock_pool):
    """GASClient with network calls patched out."""
    with patch(
        "engine.integrations.gas_client.get_account_pool", return_value=mock_pool
    ):
        with patch.object(requests.Session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                text='<html>"bl":"test_bl_label" "FdrFJe":"test_fsid"</html>',
                raise_for_status=MagicMock(),
            )
            client = GASClient(account)
    return client, mock_pool


# ──── Dataclass tests ─────────────────────────────────────────────────────────

class TestDataclasses:
    """Tests for GAS dataclasses."""

    def test_gas_project_has_required_fields(self):
        """GASProject stores script_id, title, and owner."""
        proj = GASProject(script_id="script-abc", title="My Project", owner="user@gmail.com")
        assert proj.script_id == "script-abc"
        assert proj.title == "My Project"
        assert proj.owner == "user@gmail.com"

    def test_gas_project_optional_fields_default_to_empty_string(self):
        """GASProject optional fields (created_time, updated_time) default to ''."""
        proj = GASProject(script_id="s", title="T")
        assert proj.created_time == ""
        assert proj.updated_time == ""

    def test_gas_file_has_required_fields(self):
        """GASFile stores name, file_type, and source."""
        f = GASFile(name="Code", file_type="SERVER_JS", source="function foo() {}")
        assert f.name == "Code"
        assert f.file_type == "SERVER_JS"
        assert f.source == "function foo() {}"

    def test_gas_file_defaults(self):
        """GASFile source and last_modified_user default to empty string."""
        f = GASFile(name="Index", file_type="HTML")
        assert f.source == ""
        assert f.last_modified_user == ""

    def test_gas_deployment_has_required_fields(self):
        """GASDeployment stores deployment_id and deployment_type."""
        dep = GASDeployment(
            deployment_id="dep-123",
            deployment_type="WEB_APP",
            url="https://script.google.com/macros/s/dep-123/exec",
        )
        assert dep.deployment_id == "dep-123"
        assert dep.deployment_type == "WEB_APP"
        assert "dep-123" in dep.url

    def test_gas_trigger_has_required_fields(self):
        """GASTrigger stores trigger_id, handler_function, and event_type."""
        trig = GASTrigger(
            trigger_id="trig-abc",
            handler_function="onEdit",
            event_type="ON_EDIT",
        )
        assert trig.trigger_id == "trig-abc"
        assert trig.handler_function == "onEdit"
        assert trig.event_type == "ON_EDIT"

    def test_gas_rpcids_registry_contains_expected_keys(self):
        """GAS_RPCIDS registry maps all documented rpcids."""
        expected_rpcids = {"OOPYjd", "OQOG2e", "AJ6bre", "pEig0e", "toGAmc", "ivJzse", "NFMk7c", "kGFage", "KhxE6", "AvwHP"}
        assert expected_rpcids.issubset(set(GAS_RPCIDS.keys()))


# ──── Auth / headers tests ────────────────────────────────────────────────────

class TestAuth:
    """Tests for SAPISIDHASH authentication."""

    def test_sapisidhash_returns_correct_format(self, gas_client, account):
        """_sapisidhash() returns 'SAPISIDHASH {ts}_{sha1hex}' format."""
        client, _ = gas_client
        result = client._sapisidhash("my_sapisid")
        assert result.startswith("SAPISIDHASH ")
        parts = result.split(" ", 1)[1].split("_", 1)
        assert len(parts) == 2
        ts_str, sha1_hex = parts
        assert ts_str.isdigit()
        assert len(sha1_hex) == 40  # SHA-1 hex digest is 40 chars

    def test_sapisidhash_digest_matches_expected(self, gas_client):
        """_sapisidhash() digest is sha1('{ts} {sapisid} {base_url}')."""
        client, _ = gas_client
        sapisid = "known_sapisid"
        before = int(time.time())
        result = client._sapisidhash(sapisid)
        after = int(time.time())

        ts_str = result.split(" ", 1)[1].split("_", 1)[0]
        ts = int(ts_str)
        assert before <= ts <= after + 1

        expected_digest = hashlib.sha1(
            f"{ts} {sapisid} {GAS_BASE_URL}".encode()
        ).hexdigest()
        actual_digest = result.split("_", 1)[1]
        assert actual_digest == expected_digest

    def test_headers_include_required_keys(self, gas_client, account, mock_pool):
        """_headers() includes Authorization, Content-Type, and X-Same-Domain."""
        client, pool = gas_client
        with patch("engine.integrations.gas_client.get_account_pool", return_value=pool):
            headers = client._headers()
        assert "Authorization" in headers
        assert "Content-Type" in headers
        assert headers["X-Same-Domain"] == "1"
        assert headers["Content-Type"] == "application/x-www-form-urlencoded;charset=UTF-8"

    def test_headers_authorization_starts_with_sapisidhash(self, gas_client, mock_pool):
        """_headers() Authorization value starts with 'SAPISIDHASH'."""
        client, pool = gas_client
        with patch("engine.integrations.gas_client.get_account_pool", return_value=pool):
            headers = client._headers()
        assert headers.get("Authorization", "").startswith("SAPISIDHASH")


# ──── _rpc_call() tests ───────────────────────────────────────────────────────

class TestRpcCall:
    """Tests for the core _rpc_call() method."""

    def test_rpc_call_posts_to_batch_url(self, gas_client, mock_pool):
        """_rpc_call() POSTs to GAS_BATCH_URL."""
        client, pool = gas_client
        mock_response = MagicMock()
        mock_response.text = ")]}'\n[[\"wrb.fr\",\"AvwHP\",\"[]\",null,null,null,\"generic\"]]"
        mock_response.raise_for_status = MagicMock()

        with patch("engine.integrations.gas_client.get_account_pool", return_value=pool):
            with patch.object(client._session, "post", return_value=mock_response) as mock_post:
                client._rpc_call("AvwHP", [None, None, None, None, None, 1])

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args.args[0] == GAS_BATCH_URL

    def test_rpc_call_includes_rpcid_in_params(self, gas_client, mock_pool):
        """_rpc_call() passes rpcids param equal to the given rpcid."""
        client, pool = gas_client
        mock_response = MagicMock()
        mock_response.text = ")]}'\n[[\"wrb.fr\",\"AvwHP\",\"[]\",null,null,null,\"generic\"]]"
        mock_response.raise_for_status = MagicMock()

        with patch("engine.integrations.gas_client.get_account_pool", return_value=pool):
            with patch.object(client._session, "post", return_value=mock_response) as mock_post:
                client._rpc_call("AvwHP", [])

        params = mock_post.call_args.kwargs.get("params", {})
        assert params.get("rpcids") == "AvwHP"

    def test_rpc_call_returns_none_on_http_error(self, gas_client, mock_pool):
        """_rpc_call() returns None when requests.HTTPError is raised."""
        client, pool = gas_client
        with patch("engine.integrations.gas_client.get_account_pool", return_value=pool):
            with patch.object(client._session, "post") as mock_post:
                mock_post.return_value.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
                result = client._rpc_call("AvwHP", [])
        assert result is None

    def test_rpc_call_encodes_payload_in_f_req(self, gas_client, mock_pool):
        """_rpc_call() URL-encodes payload in f.req body param."""
        client, pool = gas_client
        mock_response = MagicMock()
        mock_response.text = ")]}'\n[[\"wrb.fr\",\"toGAmc\",\"[]\",null,null,null,\"generic\"]]"
        mock_response.raise_for_status = MagicMock()

        with patch("engine.integrations.gas_client.get_account_pool", return_value=pool):
            with patch.object(client._session, "post", return_value=mock_response) as mock_post:
                client._rpc_call("toGAmc", ["script-id", [["Code", "SERVER_JS", "function f(){}"]]])

        body = mock_post.call_args.kwargs.get("data", "")
        assert "f.req=" in body
        # Decode and verify the rpcid is embedded
        decoded = urllib.parse.unquote(body)
        assert "toGAmc" in decoded


# ──── Project management tests ────────────────────────────────────────────────

class TestListProjects:
    """Tests for list_projects()."""

    def test_list_projects_returns_gas_project_list(self, gas_client, mock_pool):
        """list_projects() returns a list of GASProject objects."""
        client, pool = gas_client
        raw_response = [
            ["script-id-1", "Project Alpha", "owner@gmail.com", None, "2024-01-01", "2024-06-01"],
            ["script-id-2", "Project Beta", "other@gmail.com", None, "2024-02-01", "2024-07-01"],
        ]
        with patch("engine.integrations.gas_client.get_account_pool", return_value=pool):
            with patch.object(client, "_rpc_call", return_value=[raw_response]):
                projects = client.list_projects()

        assert len(projects) == 2
        assert all(isinstance(p, GASProject) for p in projects)
        assert projects[0].script_id == "script-id-1"
        assert projects[0].title == "Project Alpha"
        assert projects[1].title == "Project Beta"

    def test_list_projects_returns_empty_on_null_response(self, gas_client, mock_pool):
        """list_projects() returns empty list when _rpc_call returns None."""
        client, pool = gas_client
        with patch.object(client, "_rpc_call", return_value=None):
            projects = client.list_projects()
        assert projects == []

    def test_list_projects_uses_kgfage_rpcid(self, gas_client):
        """list_projects() calls _rpc_call with rpcid 'kGFage' (PAYLOAD_CONFIRMED)."""
        client, _ = gas_client
        with patch.object(client, "_rpc_call", return_value=None) as mock_rpc:
            client.list_projects()
        mock_rpc.assert_called_once()
        assert mock_rpc.call_args.args[0] == "kGFage"


class TestCreateProject:
    """Tests for create_project()."""

    def test_create_project_returns_gas_project(self, gas_client):
        """create_project() returns a GASProject with the new script_id."""
        client, _ = gas_client
        rpc_result = ["new-script-id", "New Project", "owner@gmail.com", None, "2024-01-01", "2024-01-01"]
        with patch.object(client, "_rpc_call", return_value=rpc_result):
            project = client.create_project("New Project")

        assert isinstance(project, GASProject)
        assert project.script_id == "new-script-id"
        assert project.title == "New Project"

    def test_create_project_uses_nfmk7c_rpcid(self, gas_client):
        """create_project() calls _rpc_call with rpcid 'NFMk7c'."""
        client, _ = gas_client
        with patch.object(client, "_rpc_call", return_value=None) as mock_rpc:
            client.create_project("Test")
        assert mock_rpc.call_args.args[0] == "NFMk7c"

    def test_create_project_returns_none_on_failure(self, gas_client):
        """create_project() returns None when _rpc_call returns None."""
        client, _ = gas_client
        with patch.object(client, "_rpc_call", return_value=None):
            result = client.create_project("Will Fail")
        assert result is None


# ──── Script file management tests ────────────────────────────────────────────

class TestGetFiles:
    """Tests for get_files()."""

    def test_get_files_returns_gas_file_list(self, gas_client):
        """get_files() returns a list of GASFile objects."""
        client, _ = gas_client
        raw_files = [
            ["Code", "SERVER_JS", "function doGet(e) { return ContentService.createTextOutput('ok'); }", None, None, "editor@gmail.com"],
            ["index", "HTML", "<html>Hello</html>", None, None, ""],
        ]
        with patch.object(client, "_rpc_call", return_value=[raw_files]):
            files = client.get_files("script-id-123")

        assert len(files) == 2
        assert all(isinstance(f, GASFile) for f in files)
        assert files[0].name == "Code"
        assert files[0].file_type == "SERVER_JS"
        assert files[1].file_type == "HTML"

    def test_get_files_uses_oqog2e_rpcid(self, gas_client):
        """get_files() calls _rpc_call with rpcid 'OQOG2e'."""
        client, _ = gas_client
        with patch.object(client, "_rpc_call", return_value=None) as mock_rpc:
            client.get_files("script-id")
        assert mock_rpc.call_args.args[0] == "OQOG2e"

    def test_get_files_returns_empty_on_null_response(self, gas_client):
        """get_files() returns empty list when _rpc_call returns None."""
        client, _ = gas_client
        with patch.object(client, "_rpc_call", return_value=None):
            files = client.get_files("script-id")
        assert files == []


class TestSaveScript:
    """Tests for save_script()."""

    def test_save_script_uses_togamc_rpcid(self, gas_client):
        """save_script() calls _rpc_call with rpcid 'toGAmc'."""
        client, _ = gas_client
        files = [GASFile(name="Code", file_type="SERVER_JS", source="function f() {}")]
        with patch.object(client, "_rpc_call", return_value=["ok"]) as mock_rpc:
            client.save_script("script-id", files)
        assert mock_rpc.call_args.args[0] == "toGAmc"

    def test_save_script_returns_true_on_success(self, gas_client):
        """save_script() returns True when _rpc_call returns a non-None result."""
        client, _ = gas_client
        files = [GASFile(name="Code", file_type="SERVER_JS", source="function f() {}")]
        with patch.object(client, "_rpc_call", return_value=["confirmed"]):
            result = client.save_script("script-id", files)
        assert result is True

    def test_save_script_returns_false_on_null_response(self, gas_client):
        """save_script() returns False when _rpc_call returns None."""
        client, _ = gas_client
        with patch.object(client, "_rpc_call", return_value=None):
            result = client.save_script("script-id", [])
        assert result is False


# ──── Execution tests ─────────────────────────────────────────────────────────

class TestRunFunction:
    """Tests for run_function()."""

    def test_run_function_uses_peig0e_rpcid(self, gas_client):
        """run_function() calls _rpc_call with rpcid 'pEig0e'."""
        client, _ = gas_client
        with patch.object(client, "_rpc_call", return_value=None) as mock_rpc:
            client.run_function("script-id", "myFunc", [1, 2])
        assert mock_rpc.call_args.args[0] == "pEig0e"

    def test_run_function_passes_function_name_and_args(self, gas_client):
        """run_function() includes function_name and args in the payload."""
        client, _ = gas_client
        with patch.object(client, "_rpc_call", return_value=None) as mock_rpc:
            client.run_function("script-id", "myFunc", [1, 2])
        payload = mock_rpc.call_args.args[1]
        assert payload[1] == "myFunc"
        assert payload[2] == [1, 2]

    def test_run_function_returns_none_when_rpc_fails(self, gas_client):
        """run_function() returns None when _rpc_call returns None."""
        client, _ = gas_client
        with patch.object(client, "_rpc_call", return_value=None):
            result = client.run_function("script-id", "failFunc", [])
        assert result is None


# ──── Deployment tests ────────────────────────────────────────────────────────

class TestCreateWebAppDeployment:
    """Tests for create_web_app_deployment()."""

    def test_create_web_app_deployment_calls_aj6bre(self, gas_client):
        """create_web_app_deployment() calls _rpc_call with rpcid 'AJ6bre'."""
        client, _ = gas_client
        with patch.object(client, "create_version", return_value=1):
            with patch.object(client, "_rpc_call", return_value=[["dep-id", "WEB_APP", 1, "https://script.google.com/exec"]]) as mock_rpc:
                client.create_web_app_deployment("script-id")
        assert mock_rpc.called
        assert mock_rpc.call_args.args[0] == "AJ6bre"

    def test_create_web_app_deployment_returns_deployment(self, gas_client):
        """create_web_app_deployment() returns a GASDeployment instance."""
        client, _ = gas_client
        with patch.object(client, "create_version", return_value=2):
            with patch.object(client, "_rpc_call", return_value=[["dep-xyz", "WEB_APP", 2, "https://script.google.com/exec/xyz"]]):
                dep = client.create_web_app_deployment("script-id", description="test")
        assert isinstance(dep, GASDeployment)
        assert dep.deployment_type == "WEB_APP"


# ──── Trigger tests ───────────────────────────────────────────────────────────

class TestListTriggers:
    """Tests for list_triggers()."""

    def test_list_triggers_uses_ivjzse_rpcid(self, gas_client):
        """list_triggers() calls _rpc_call with rpcid 'ivJzse' (ARGUS heap-confirmed ListTriggers)."""
        client, _ = gas_client
        with patch.object(client, "_rpc_call", return_value=None) as mock_rpc:
            client.list_triggers("script-id")
        assert mock_rpc.call_args.args[0] == "ivJzse"

    def test_list_triggers_returns_gas_trigger_list(self, gas_client):
        """list_triggers() parses response into list of GASTrigger objects."""
        client, _ = gas_client
        raw_triggers = [
            ["trig-001", "onOpen", "ON_OPEN", "SPREADSHEET"],
            ["trig-002", "syncData", "CLOCK", "CLOCK"],
        ]
        with patch.object(client, "_rpc_call", return_value=[raw_triggers]):
            triggers = client.list_triggers("script-id")

        assert len(triggers) == 2
        assert all(isinstance(t, GASTrigger) for t in triggers)
        assert triggers[0].trigger_id == "trig-001"
        assert triggers[0].handler_function == "onOpen"
        assert triggers[1].event_type == "CLOCK"

    def test_list_triggers_returns_empty_on_null(self, gas_client):
        """list_triggers() returns empty list on null RPC response."""
        client, _ = gas_client
        with patch.object(client, "_rpc_call", return_value=None):
            triggers = client.list_triggers("script-id")
        assert triggers == []


# ──── High-level helpers ──────────────────────────────────────────────────────

class TestCreateCosySimBridge:
    """Tests for create_cosysim_bridge()."""

    def test_create_cosysim_bridge_calls_create_webhook_script(self, gas_client):
        """create_cosysim_bridge() delegates to create_webhook_script()."""
        client, _ = gas_client
        mock_dep = GASDeployment(deployment_id="d-bridge", deployment_type="WEB_APP", url="https://exec.url")
        with patch.object(client, "create_webhook_script", return_value=mock_dep) as mock_create:
            result = client.create_cosysim_bridge("http://localhost:8700")

        mock_create.assert_called_once()
        # title should be 'CosySim Bridge'
        assert mock_create.call_args.args[0] == "CosySim Bridge"

    def test_create_cosysim_bridge_embeds_cosysim_url_in_code(self, gas_client):
        """create_cosysim_bridge() embeds the CosySim URL in the generated code."""
        client, _ = gas_client
        captured_code: list = []

        def capture_create(title: str, handler_code: str):
            captured_code.append(handler_code)
            return None

        with patch.object(client, "create_webhook_script", side_effect=capture_create):
            client.create_cosysim_bridge("http://my-cosysim:9000")

        assert len(captured_code) == 1
        assert "http://my-cosysim:9000" in captured_code[0]
        assert "/api/gas/webhook" in captured_code[0]


# ──── Factory tests ───────────────────────────────────────────────────────────

class TestGetGasClient:
    """Tests for get_gas_client() factory."""

    @patch("engine.integrations.gas_client.get_account_pool")
    def test_get_gas_client_returns_gas_client_when_account_available(self, mock_get_pool):
        """get_gas_client() returns a GASClient when an account is found."""
        mock_pool = MagicMock()
        mock_account = _make_account()
        mock_pool.get_by_name.return_value = mock_account
        mock_pool.get_account.return_value = mock_account
        mock_pool.get_cookie_header.return_value = "SID=x"
        mock_get_pool.return_value = mock_pool

        with patch.object(requests.Session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, text="<html></html>", raise_for_status=MagicMock()
            )
            client = get_gas_client("test_account")

        assert isinstance(client, GASClient)

    @patch("engine.integrations.gas_client.get_account_pool")
    def test_get_gas_client_returns_none_when_no_account(self, mock_get_pool):
        """get_gas_client() returns None when no suitable account is in the pool."""
        mock_pool = MagicMock()
        mock_pool.get_by_name.return_value = None
        mock_pool.get_account.return_value = None
        mock_get_pool.return_value = mock_pool

        result = get_gas_client("nonexistent_account")
        assert result is None


# ──── Helper function tests ───────────────────────────────────────────────────

class TestSafeStr:
    """Tests for the _safe_str() helper."""

    def test_safe_str_returns_string_at_index(self):
        """_safe_str() returns stringified value at given index."""
        assert _safe_str(["alpha", "beta", "gamma"], 1) == "beta"

    def test_safe_str_returns_empty_string_on_out_of_bounds(self):
        """_safe_str() returns '' for out-of-range indices."""
        assert _safe_str(["only"], 5) == ""

    def test_safe_str_returns_empty_string_for_none_value(self):
        """_safe_str() returns '' when list element is None."""
        assert _safe_str([None, "val"], 0) == ""

    def test_safe_str_coerces_numbers_to_string(self):
        """_safe_str() converts numeric values to their string representation."""
        assert _safe_str([42, "hello"], 0) == "42"
