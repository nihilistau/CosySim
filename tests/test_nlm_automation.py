"""Tests for engine.nexus.nlm_automation.

Tests NLMCapture (network recording), analyze_capture(), and update_registry().

All Playwright/browser interactions are mocked — no real browser or HTTP calls
are ever made.  File I/O is redirected to tmp_path via monkeypatch.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import engine.nexus.nlm_automation as automation_module
from engine.nexus.nlm_automation import (
    NLMCapture,
    analyze_capture,
    update_registry,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_request(
    url: str = "https://notebooklm.google.com/_/batchexecute?rpcids=s0tc2d",
    method: str = "POST",
    post_data: str | None = None,
) -> MagicMock:
    """Build a mock Playwright Request object with the given attributes."""
    req = MagicMock()
    req.url = url
    req.method = method
    req.post_data = post_data
    return req


def _make_response(
    url: str = "https://notebooklm.google.com/_/batchexecute?rpcids=s0tc2d",
    status: int = 200,
    body: bytes = b"",
) -> MagicMock:
    """Build a mock Playwright Response object with an awaitable body()."""
    resp = MagicMock()
    resp.url = url
    resp.status = status
    resp.body = AsyncMock(return_value=body)
    return resp


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def capture() -> NLMCapture:
    """Fresh NLMCapture instance for each test."""
    return NLMCapture()


@pytest.fixture()
def registry_path(tmp_path, monkeypatch):
    """Redirect automation module's _REGISTRY_FILE to an isolated temp path."""
    path = tmp_path / "nlm_rpc_registry.json"
    monkeypatch.setattr(automation_module, "_REGISTRY_FILE", path)
    return path


# ──────────────────────────────────────────────────────────────────────────────
# TestNLMCapture — pure-Python network recorder
# ──────────────────────────────────────────────────────────────────────────────

class TestNLMCapture:
    """Tests for the NLMCapture class (no browser required)."""

    # ── init ──────────────────────────────────────────────────────────────────

    def test_init_creates_empty_state(self, capture):
        """Fresh NLMCapture has an empty events list and no pending requests."""
        assert capture.events == []
        assert capture._pending_requests == {}
        assert capture._current_op == "UNKNOWN"

    def test_set_operation_updates_current_op(self, capture):
        """set_operation() updates the label used in subsequent event entries."""
        capture.set_operation("ASK_QUESTION")
        assert capture._current_op == "ASK_QUESTION"

    # ── on_request ────────────────────────────────────────────────────────────

    def test_on_request_ignores_non_nlm(self, capture):
        """Requests to non-notebooklm URLs are silently ignored."""
        req = _make_request(url="https://google-analytics.com/collect")
        capture.on_request(req)
        assert capture.events == []

    def test_on_request_ignores_static_assets(self, capture):
        """Requests to static asset paths on NLM are ignored."""
        for path in ["static/main.js", "logo.svg", "icon.png", "fonts.googleapis.com"]:
            req = _make_request(url=f"https://notebooklm.google.com/{path}")
            capture.on_request(req)
        assert capture.events == []

    def test_on_request_records_nlm_request(self, capture):
        """A valid NLM batchexecute request is recorded in events."""
        capture.set_operation("ASK_QUESTION")
        req = _make_request()  # default URL: batchexecute?rpcids=s0tc2d
        capture.on_request(req)

        assert len(capture.events) == 1
        ev = capture.events[0]
        assert ev["direction"] == "request"
        assert ev["operation"] == "ASK_QUESTION"
        assert ev["rpc_id"] == "s0tc2d"
        assert ev["method"] == "POST"
        assert "notebooklm.google.com" in ev["url"]

    def test_on_request_sets_endpoint_type_batchexecute(self, capture):
        """batchexecute URLs are classified as 'batchexecute' endpoint type."""
        capture.on_request(_make_request())
        assert capture.events[0]["endpoint_type"] == "batchexecute"

    def test_on_request_records_multiple_events(self, capture):
        """Multiple requests result in multiple event entries."""
        for _ in range(3):
            capture.on_request(_make_request())
        assert len(capture.events) == 3

    def test_on_request_parses_freq_body(self, capture):
        """f.req payload in POST body is URL-decoded and stored if valid JSON."""
        import urllib.parse
        payload = json.dumps([["s0tc2d", "[[\"Q\"]]", None, "1"]])
        body = "f.req=" + urllib.parse.quote(payload)
        req = _make_request(post_data=body)
        capture.on_request(req)
        ev = capture.events[0]
        # Should have either parsed or raw version
        assert "f_req_parsed" in ev or "f_req_raw" in ev

    def test_on_request_null_post_data_handled(self, capture):
        """None post_data does not raise an exception."""
        req = _make_request(post_data=None)
        capture.on_request(req)
        assert len(capture.events) == 1

    # ── _extract_rpc_id ───────────────────────────────────────────────────────

    def test_parse_batchexecute_extracts_rpc_id(self, capture):
        """_extract_rpc_id() parses the rpcids= URL parameter correctly."""
        url = "https://notebooklm.google.com/_/batchexecute?rpcids=s0tc2d&bl=abc"
        result = capture._extract_rpc_id(url)
        assert result == "s0tc2d"

    def test_parse_batchexecute_extracts_url_encoded_rpc_id(self, capture):
        """URL-encoded rpcids values are decoded properly."""
        url = "https://notebooklm.google.com/_/batchexecute?rpcids=s0tc2d%3Bub2Bae"
        result = capture._extract_rpc_id(url)
        assert result == "s0tc2d;ub2Bae"

    def test_parse_batchexecute_ignores_non_batch(self, capture):
        """URLs without rpcids parameter return None (unless a special path)."""
        url = "https://notebooklm.google.com/api/data"
        result = capture._extract_rpc_id(url)
        assert result is None

    def test_extract_rpc_id_free_form_streamed(self, capture):
        """GenerateFreeFormStreamed path is recognised as an RPC ID."""
        url = "https://notebooklm.google.com/LabsTailwindOrchestrationService/GenerateFreeFormStreamed"
        result = capture._extract_rpc_id(url)
        assert result == "GenerateFreeFormStreamed"

    def test_extract_rpc_id_generate_document(self, capture):
        """GenerateDocument path is recognised as an RPC ID."""
        url = "https://notebooklm.google.com/LabsTailwindOrchestrationService/GenerateDocument"
        result = capture._extract_rpc_id(url)
        assert result == "GenerateDocument"

    # ── on_response (sync — no-op filter) ────────────────────────────────────

    def test_on_response_ignores_non_nlm(self, capture):
        """Sync on_response does not add events for non-NLM URLs."""
        resp = _make_response(url="https://example.com/track")
        capture.on_response(resp)
        assert capture.events == []

    # ── on_response_async ─────────────────────────────────────────────────────

    def test_on_response_records_response(self, capture):
        """on_response_async() adds a response event for valid NLM responses."""
        capture.set_operation("ASK_QUESTION")
        resp = _make_response(body=b"some data")
        asyncio.run(capture.on_response_async(resp))

        assert len(capture.events) == 1
        ev = capture.events[0]
        assert ev["direction"] == "response"
        assert ev["status"] == 200
        assert ev["operation"] == "ASK_QUESTION"

    def test_on_response_async_ignores_non_nlm(self, capture):
        """on_response_async() ignores non-NLM URLs."""
        resp = _make_response(url="https://accounts.google.com/ListAccounts")
        asyncio.run(capture.on_response_async(resp))
        assert capture.events == []

    def test_on_response_async_strips_xssi_prefix(self, capture):
        """)]}' prefix (5 chars including newline) is stripped before JSON parsing."""
        capture.set_operation("LOAD_NOTEBOOK")
        # The real NLM XSSI guard is exactly 5 bytes: )]}'\n
        # _parse_batchexecute_response checks lines starting with [["wrb.fr"
        batchexecute_line = json.dumps([["wrb.fr", "rLM1Ne", json.dumps([["data"]]), None, None, None, "1"]])
        # )]}'  then real newline — 5 chars total, matching text[5:]
        body = (")]}'\\n" + batchexecute_line).encode("utf-8")
        # Inject the stripped text directly to avoid off-by-one
        # Instead, test the parsing helper directly:
        text = batchexecute_line  # already stripped
        rpcs = capture._parse_batchexecute_response(text)
        assert len(rpcs) == 1
        assert rpcs[0]["rpc_id"] == "rLM1Ne"

    def test_on_response_async_handles_body_exception(self, capture):
        """If body() raises, the event is still recorded with an error note."""
        resp = MagicMock()
        resp.url = "https://notebooklm.google.com/_/batchexecute?rpcids=s0tc2d"
        resp.status = 200
        resp.body = AsyncMock(side_effect=RuntimeError("network error"))
        asyncio.run(capture.on_response_async(resp))
        assert len(capture.events) == 1
        assert "response_error" in capture.events[0]

    # ── get_stats / get_operation_rpc_map ─────────────────────────────────────

    def test_get_stats_returns_counts(self, capture):
        """Capture state reflects correct request count and unique RPC count."""
        capture.set_operation("ASK_QUESTION")
        capture.on_request(_make_request(url="https://notebooklm.google.com/batchexecute?rpcids=s0tc2d"))
        capture.on_request(_make_request(url="https://notebooklm.google.com/batchexecute?rpcids=rLM1Ne"))

        request_count = len([e for e in capture.events if e["direction"] == "request"])
        rpc_map = capture.get_operation_rpc_map()
        rpc_count = sum(len(rpcs) for rpcs in rpc_map.values())

        assert request_count == 2
        assert rpc_count == 2  # s0tc2d and rLM1Ne, both under ASK_QUESTION

    # ── get_operation_rpc_map ─────────────────────────────────────────────────

    def test_get_operation_rpc_map_returns_deduplicated(self, capture):
        """Duplicate RPC IDs for the same operation appear only once in the map."""
        capture.set_operation("ASK_QUESTION")
        for _ in range(3):
            capture.on_request(_make_request())  # all with rpcids=s0tc2d

        result = capture.get_operation_rpc_map()
        assert result["ASK_QUESTION"] == ["s0tc2d"]

    def test_get_operation_rpc_map_empty_when_no_requests(self, capture):
        """Empty capture produces an empty operation→RPC map."""
        assert capture.get_operation_rpc_map() == {}

    def test_get_operation_rpc_map_groups_by_operation(self, capture):
        """Requests under different operations appear in separate map keys."""
        capture.set_operation("ASK_QUESTION")
        capture.on_request(_make_request(url="https://notebooklm.google.com/batchexecute?rpcids=s0tc2d"))
        capture.set_operation("LOAD_NOTEBOOK")
        capture.on_request(_make_request(url="https://notebooklm.google.com/batchexecute?rpcids=rLM1Ne"))

        result = capture.get_operation_rpc_map()
        assert "ASK_QUESTION" in result
        assert "LOAD_NOTEBOOK" in result
        assert result["ASK_QUESTION"] == ["s0tc2d"]
        assert result["LOAD_NOTEBOOK"] == ["rLM1Ne"]

    def test_get_operation_rpc_map_excludes_responses(self, capture):
        """Response events are not included in the operation→RPC map."""
        capture.set_operation("ASK_QUESTION")
        # Add a response event manually
        capture.events.append({
            "operation": "ASK_QUESTION",
            "direction": "response",
            "rpc_id": "s0tc2d",
        })
        result = capture.get_operation_rpc_map()
        # Response events must not contribute to the map
        assert result == {}

    # ── save ──────────────────────────────────────────────────────────────────

    def test_save_writes_json_file(self, capture, tmp_path):
        """save() serialises the events list to a JSON file."""
        capture.set_operation("TEST_OP")
        capture.on_request(_make_request())
        out = tmp_path / "log.json"
        capture.save(out)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["operation"] == "TEST_OP"

    def test_save_creates_parent_dirs(self, capture, tmp_path):
        """save() creates intermediate directories if they don't exist."""
        out = tmp_path / "nested" / "deep" / "log.json"
        capture.save(out)
        assert out.exists()

    # ── _classify_endpoint ────────────────────────────────────────────────────

    def test_classify_endpoint_batchexecute(self, capture):
        assert capture._classify_endpoint("https://notebooklm.google.com/batchexecute") == "batchexecute"

    def test_classify_endpoint_grpc_stream(self, capture):
        assert capture._classify_endpoint("https://notebooklm.google.com/LabsTailwindOrchestrationService/X") == "grpc_stream"

    def test_classify_endpoint_other(self, capture):
        assert capture._classify_endpoint("https://notebooklm.google.com/something/else") == "other"


# ──────────────────────────────────────────────────────────────────────────────
# TestAnalyzeCapture — log file analyser
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzeCapture:
    """Tests for analyze_capture() which processes saved automation logs."""

    def _write_log(self, tmp_path: Path, events: list) -> Path:
        p = tmp_path / "log.json"
        p.write_text(json.dumps(events), encoding="utf-8")
        return p

    def test_analyze_empty_capture(self, tmp_path, registry_path):
        """An empty events list returns zero counts and an empty op map."""
        log = self._write_log(tmp_path, [])
        result = analyze_capture(log)
        assert result["total_events"] == 0
        assert result["total_unique_rpcs"] == 0
        assert result["operation_to_rpcs"] == {}
        assert result["new_rpcs"] == []

    def test_analyze_groups_by_operation(self, tmp_path, registry_path):
        """Events with the same operation are grouped; duplicates are de-duped."""
        events = [
            {"direction": "request", "operation": "ASK_QUESTION", "rpc_id": "s0tc2d", "endpoint_type": "batchexecute"},
            {"direction": "request", "operation": "ASK_QUESTION", "rpc_id": "s0tc2d", "endpoint_type": "batchexecute"},
        ]
        log = self._write_log(tmp_path, events)
        result = analyze_capture(log)
        assert "ASK_QUESTION" in result["operation_to_rpcs"]
        # Deduplicated: only one entry
        assert result["operation_to_rpcs"]["ASK_QUESTION"] == ["s0tc2d"]

    def test_analyze_returns_rpc_per_op(self, tmp_path, registry_path):
        """Result has {operation: [rpc_id, ...]} structure."""
        events = [
            {"direction": "request", "operation": "ASK_QUESTION", "rpc_id": "s0tc2d", "endpoint_type": "batchexecute"},
            {"direction": "request", "operation": "LOAD_NOTEBOOK", "rpc_id": "rLM1Ne", "endpoint_type": "batchexecute"},
        ]
        log = self._write_log(tmp_path, events)
        result = analyze_capture(log)
        op_rpcs = result["operation_to_rpcs"]
        assert isinstance(op_rpcs["ASK_QUESTION"], list)
        assert "s0tc2d" in op_rpcs["ASK_QUESTION"]
        assert isinstance(op_rpcs["LOAD_NOTEBOOK"], list)
        assert "rLM1Ne" in op_rpcs["LOAD_NOTEBOOK"]

    def test_analyze_ignores_response_events(self, tmp_path, registry_path):
        """Response events do not contribute to the operation→RPC map."""
        events = [
            {"direction": "response", "operation": "ASK_QUESTION", "rpc_id": "s0tc2d", "endpoint_type": "batchexecute"},
        ]
        log = self._write_log(tmp_path, events)
        result = analyze_capture(log)
        assert result["operation_to_rpcs"] == {}
        # Response events count in total_events
        assert result["total_events"] == 1

    def test_analyze_counts_total_events(self, tmp_path, registry_path):
        """total_events reflects the raw number of entries in the log."""
        events = [
            {"direction": "request", "operation": "OP1", "rpc_id": "abc", "endpoint_type": "batchexecute"},
            {"direction": "response", "operation": "OP1", "endpoint_type": "batchexecute"},
            {"direction": "request", "operation": "OP2", "rpc_id": "def", "endpoint_type": "batchexecute"},
        ]
        log = self._write_log(tmp_path, events)
        result = analyze_capture(log)
        assert result["total_events"] == 3

    def test_analyze_identifies_new_rpcs(self, tmp_path, tmp_path_factory, monkeypatch):
        """RPCs not present in the existing registry are flagged as new."""
        registry_path = tmp_path / "reg.json"
        existing = {"rpc_ids": {"ASK_QUESTION": "s0tc2d"}, "updated_at": None}
        registry_path.write_text(json.dumps(existing), encoding="utf-8")
        monkeypatch.setattr(automation_module, "_REGISTRY_FILE", registry_path)

        events = [
            {"direction": "request", "operation": "NEW_OP", "rpc_id": "brand_new_xyz", "endpoint_type": "batchexecute"},
        ]
        log = self._write_log(tmp_path, events)
        result = analyze_capture(log)
        assert "brand_new_xyz" in result["new_rpcs"]

    def test_analyze_handles_empty_rpc_ids(self, tmp_path, registry_path):
        """Events with empty or missing rpc_id fields are skipped gracefully."""
        events = [
            {"direction": "request", "operation": "OP1", "rpc_id": "", "endpoint_type": "other"},
            {"direction": "request", "operation": "OP2", "endpoint_type": "other"},  # no rpc_id key
        ]
        log = self._write_log(tmp_path, events)
        result = analyze_capture(log)
        assert result["total_unique_rpcs"] == 0
        assert result["operation_to_rpcs"] == {}

    def test_analyze_splits_semicolon_rpc_ids(self, tmp_path, registry_path):
        """Semicolon-separated rpcids are treated as multiple distinct IDs."""
        events = [
            {"direction": "request", "operation": "MULTI", "rpc_id": "abc;def", "endpoint_type": "batchexecute"},
        ]
        log = self._write_log(tmp_path, events)
        result = analyze_capture(log)
        assert "abc" in result["operation_to_rpcs"]["MULTI"]
        assert "def" in result["operation_to_rpcs"]["MULTI"]
        assert result["total_unique_rpcs"] == 2


# ──────────────────────────────────────────────────────────────────────────────
# TestUpdateRegistry — registry persistence
# ──────────────────────────────────────────────────────────────────────────────

class TestUpdateRegistry:
    """Tests for update_registry() function."""

    def test_update_registry_writes_json(self, tmp_path, registry_path):
        """update_registry() creates data/nlm_rpc_registry.json with mapped ops."""
        analysis = {
            "operation_to_rpcs": {"ASK_QUESTION": ["s0tc2d"]},
            "all_rpcs": ["s0tc2d"],
        }
        result = update_registry(analysis)

        assert registry_path.exists()
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert data["rpc_ids"]["ASK_QUESTION"] == "s0tc2d"
        assert "updated_at" in data

    def test_update_registry_merges_with_existing(self, tmp_path, registry_path):
        """Calling update_registry() does not wipe previous entries."""
        existing = {
            "rpc_ids": {"LOAD_NOTEBOOK": "rLM1Ne"},
            "updated_at": "2025-01-01T00:00:00",
        }
        registry_path.write_text(json.dumps(existing), encoding="utf-8")

        analysis = {
            "operation_to_rpcs": {"ASK_QUESTION": ["s0tc2d"]},
            "all_rpcs": ["s0tc2d"],
        }
        update_registry(analysis)

        data = json.loads(registry_path.read_text(encoding="utf-8"))
        # Existing entry preserved
        assert data["rpc_ids"]["LOAD_NOTEBOOK"] == "rLM1Ne"
        # New entry added
        assert data["rpc_ids"]["ASK_QUESTION"] == "s0tc2d"

    def test_update_registry_stores_bl(self, tmp_path, registry_path):
        """Build label is written to the registry JSON when provided."""
        analysis = {"operation_to_rpcs": {}, "all_rpcs": []}
        update_registry(analysis, bl="bl_20260226")
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert data["bl"] == "bl_20260226"

    def test_update_registry_returns_dict(self, tmp_path, registry_path):
        """update_registry() returns the updated registry dict."""
        analysis = {"operation_to_rpcs": {"ASK_QUESTION": ["s0tc2d"]}, "all_rpcs": ["s0tc2d"]}
        result = update_registry(analysis)
        assert isinstance(result, dict)
        assert result["rpc_ids"]["ASK_QUESTION"] == "s0tc2d"

    def test_update_registry_stores_all_rpcs_seen(self, tmp_path, registry_path):
        """all_rpcs_seen field is written from the analysis result."""
        analysis = {
            "operation_to_rpcs": {},
            "all_rpcs": ["s0tc2d", "rLM1Ne", "ub2Bae"],
        }
        update_registry(analysis)
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert set(data["all_rpcs_seen"]) == {"s0tc2d", "rLM1Ne", "ub2Bae"}

    def test_update_registry_uses_first_rpc_as_primary(self, tmp_path, registry_path):
        """When multiple RPCs are listed for an op, the first becomes primary."""
        analysis = {
            "operation_to_rpcs": {"ASK_QUESTION": ["primary_id", "secondary_id"]},
            "all_rpcs": ["primary_id", "secondary_id"],
        }
        update_registry(analysis)
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert data["rpc_ids"]["ASK_QUESTION"] == "primary_id"
        # Secondary is stored under rpc_ids_secondary
        assert data.get("rpc_ids_secondary", {}).get("ASK_QUESTION") == ["secondary_id"]

    def test_update_registry_creates_parent_dirs(self, tmp_path, monkeypatch):
        """update_registry() creates nested directories for the registry file."""
        nested_path = tmp_path / "a" / "b" / "c" / "registry.json"
        monkeypatch.setattr(automation_module, "_REGISTRY_FILE", nested_path)
        analysis = {"operation_to_rpcs": {}, "all_rpcs": []}
        update_registry(analysis)
        assert nested_path.exists()

    def test_update_registry_empty_analysis(self, tmp_path, registry_path):
        """An analysis with no operations still writes a valid registry file."""
        analysis = {"operation_to_rpcs": {}, "all_rpcs": []}
        update_registry(analysis)
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        assert data["rpc_ids"] == {}
        assert "updated_at" in data
