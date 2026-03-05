"""Tests for scripts.argus.tools.protocol_monitor_parser — CDP event parsing."""
from __future__ import annotations

import json
import tempfile
import urllib.parse
from pathlib import Path

import pytest

from scripts.argus.tools.protocol_monitor_parser import (
    BATCH_EXECUTE_HOSTS,
    GAS_RPCIDS,
    _decode_freq,
    extract_batchexecute_requests,
    extract_network_events,
    extract_response_bodies,
    find_all_rpcids_in_events,
    get_params,
    load_events,
)


# ──── Helpers ─────────────────────────────────────────────────────────────────

def _make_event(method: str, params: dict, use_result: bool = False) -> dict:
    """Build a minimal CDP event dict."""
    key = "result" if use_result else "params"
    return {"method": method, key: params}


def _make_batchexecute_event(
    url: str,
    rpcid: str,
    payload: list,
    use_result: bool = False,
) -> dict:
    """Build a Network.requestWillBeSent event with a batchexecute POST body."""
    f_req_inner = json.dumps(
        [[rpcid, json.dumps(payload, separators=(",", ":")), None, "generic"]],
        separators=(",", ":"),
    )
    post_data = urllib.parse.urlencode({"f.req": f_req_inner, "": ""})
    request = {
        "url": url,
        "method": "POST",
        "postData": post_data,
    }
    params = {"requestId": "req-001", "timestamp": 1000.0, "request": request}
    key = "result" if use_result else "params"
    return {"method": "Network.requestWillBeSent", key: params}


# ──── load_events ─────────────────────────────────────────────────────────────

class TestLoadEvents:
    def test_loads_list_format(self, tmp_path: Path) -> None:
        events = [{"method": "Network.requestWillBeSent", "params": {}}]
        path = tmp_path / "events.json"
        path.write_text(json.dumps(events), encoding="utf-8")
        result = load_events(str(path))
        assert len(result) == 1
        assert result[0]["method"] == "Network.requestWillBeSent"

    def test_loads_wrapped_format(self, tmp_path: Path) -> None:
        events = [{"method": "Debugger.scriptParsed", "params": {}}]
        data = {"events": events}
        path = tmp_path / "wrapped.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = load_events(str(path))
        assert len(result) == 1

    def test_loads_messages_format(self, tmp_path: Path) -> None:
        events = [{"method": "Runtime.consoleAPICalled", "params": {}}]
        data = {"messages": events}
        path = tmp_path / "messages.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = load_events(str(path))
        assert len(result) == 1

    def test_empty_list(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        path.write_text("[]", encoding="utf-8")
        result = load_events(str(path))
        assert result == []


# ──── get_params ──────────────────────────────────────────────────────────────

class TestGetParams:
    def test_returns_params_field(self) -> None:
        ev = {"method": "Network.foo", "params": {"url": "https://example.com"}}
        assert get_params(ev) == {"url": "https://example.com"}

    def test_falls_back_to_result_field(self) -> None:
        ev = {"method": "Network.foo", "result": {"url": "https://example.com"}}
        assert get_params(ev) == {"url": "https://example.com"}

    def test_returns_empty_dict_if_neither(self) -> None:
        ev = {"method": "Network.foo"}
        assert get_params(ev) == {}

    def test_params_takes_priority_over_result(self) -> None:
        ev = {
            "method": "Network.foo",
            "params": {"source": "params"},
            "result": {"source": "result"},
        }
        assert get_params(ev)["source"] == "params"


# ──── extract_network_events ──────────────────────────────────────────────────

class TestExtractNetworkEvents:
    def test_separates_by_method(self) -> None:
        events = [
            {"method": "Network.requestWillBeSent", "params": {}},
            {"method": "Network.responseReceived", "params": {}},
            {"method": "Debugger.scriptParsed", "params": {}},
            {"method": "Network.requestWillBeSent", "params": {}},
        ]
        categorized = extract_network_events(events)
        assert len(categorized["Network.requestWillBeSent"]) == 2
        assert len(categorized["Network.responseReceived"]) == 1
        assert "Debugger.scriptParsed" not in categorized

    def test_empty_events(self) -> None:
        assert extract_network_events([]) == {}

    def test_no_network_events(self) -> None:
        events = [{"method": "Runtime.consoleAPICalled", "params": {}}]
        assert extract_network_events(events) == {}


# ──── _decode_freq ────────────────────────────────────────────────────────────

class TestDecodeFreq:
    def test_decodes_valid_freq(self) -> None:
        payload = ["project-id", None, 1]
        inner = json.dumps(
            [["OOPYjd", json.dumps(payload, separators=(",", ":")), None, "generic"]],
            separators=(",", ":"),
        )
        post_data = urllib.parse.urlencode({"f.req": inner})
        result = _decode_freq(post_data)
        assert len(result) >= 1
        assert result[0]["rpcid"] == "OOPYjd"
        assert result[0]["payload"] == payload

    def test_decodes_without_freq_prefix(self) -> None:
        # Raw JSON without f.req= prefix — no spaces to avoid + encoding issue
        inner = json.dumps(
            [["AvwHP", json.dumps([None, 1], separators=(",", ":")), None, "generic"]],
            separators=(",", ":"),
        )
        result = _decode_freq(inner)
        assert len(result) >= 1
        assert result[0]["rpcid"] == "AvwHP"

    def test_returns_empty_on_garbage(self) -> None:
        result = _decode_freq("this is not valid json at all !!!")
        assert result == []

    def test_returns_empty_on_empty_string(self) -> None:
        assert _decode_freq("") == []

    def test_raw_payload_when_not_json(self) -> None:
        inner = json.dumps(
            [["KKLVD", "not-json-payload", None, "generic"]],
            separators=(",", ":"),
        )
        post_data = urllib.parse.urlencode({"f.req": inner})
        result = _decode_freq(post_data)
        assert result[0]["raw_payload"] == "not-json-payload"
        assert result[0]["payload"] == "not-json-payload"  # falls back to raw


# ──── extract_batchexecute_requests ───────────────────────────────────────────

class TestExtractBatchexecuteRequests:
    def test_finds_gas_batchexecute(self) -> None:
        url = "https://script.google.com/_/AppsPlatformConsoleUi/data/batchexecute?rpcids=OOPYjd"
        ev = _make_batchexecute_event(url, "OOPYjd", ["script-id", None, None, None, 1])
        results = extract_batchexecute_requests([ev])
        assert len(results) == 1
        assert results[0]["url"] == url

    def test_ignores_non_batchexecute(self) -> None:
        ev = _make_event("Network.requestWillBeSent", {
            "requestId": "r1",
            "timestamp": 0,
            "request": {"url": "https://script.google.com/home", "method": "GET", "postData": ""},
        })
        results = extract_batchexecute_requests([ev])
        assert results == []

    def test_target_host_filter(self) -> None:
        gas_url = "https://script.google.com/_/AppsPlatformConsoleUi/data/batchexecute"
        nlm_url = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
        gas_ev = _make_batchexecute_event(gas_url, "OOPYjd", [])
        nlm_ev = _make_batchexecute_event(nlm_url, "UIVaxd", [])
        # Only GAS
        results = extract_batchexecute_requests([gas_ev, nlm_ev], target_host="script.google.com")
        assert len(results) == 1
        assert "script.google.com" in results[0]["url"]

    def test_detects_rpcid_in_url_params(self) -> None:
        url = "https://script.google.com/_/AppsPlatformConsoleUi/data/batchexecute?rpcids=OOPYjd&f.sid=123"
        ev = _make_batchexecute_event(url, "OOPYjd", [])
        results = extract_batchexecute_requests([ev])
        assert "OOPYjd" in results[0]["rpcids_found"]

    def test_decodes_post_body_rpcid(self) -> None:
        url = "https://script.google.com/_/AppsPlatformConsoleUi/data/batchexecute"
        ev = _make_batchexecute_event(url, "NFMk7c", ["New Project"])
        results = extract_batchexecute_requests([ev])
        assert len(results) == 1
        decoded = results[0]["decoded_requests"]
        assert len(decoded) >= 1
        assert decoded[0]["rpcid"] == "NFMk7c"
        assert decoded[0]["payload"] == ["New Project"]

    def test_result_field_events(self) -> None:
        """Protocol Monitor uses result field instead of params for some events."""
        url = "https://script.google.com/_/AppsPlatformConsoleUi/data/batchexecute"
        ev = _make_batchexecute_event(url, "GXx9jd", ["script-id"], use_result=True)
        results = extract_batchexecute_requests([ev])
        assert len(results) == 1

    def test_empty_events(self) -> None:
        assert extract_batchexecute_requests([]) == []


# ──── extract_response_bodies ─────────────────────────────────────────────────

class TestExtractResponseBodies:
    def test_returns_data_received_lengths(self) -> None:
        events = [
            {"method": "Network.dataReceived", "params": {"requestId": "r1", "encodedDataLength": 1024}},
            {"method": "Network.dataReceived", "params": {"requestId": "r2", "encodedDataLength": 512}},
        ]
        bodies = extract_response_bodies(events)
        assert "r1" in bodies
        assert "r2" in bodies

    def test_ignores_non_data_received(self) -> None:
        events = [
            {"method": "Network.requestWillBeSent", "params": {"requestId": "r1"}},
        ]
        bodies = extract_response_bodies(events)
        assert bodies == {}

    def test_empty_events(self) -> None:
        assert extract_response_bodies([]) == {}


# ──── find_all_rpcids_in_events ───────────────────────────────────────────────

class TestFindAllRpcidsInEvents:
    def test_counts_known_rpcids(self) -> None:
        events = [
            {"method": "Network.requestWillBeSent", "params": {"url": "...rpcids=OOPYjd..."}},
            {"method": "Network.requestWillBeSent", "params": {"url": "...rpcids=OOPYjd..."}},
            {"method": "Network.requestWillBeSent", "params": {"url": "...rpcids=AvwHP..."}},
        ]
        counts = find_all_rpcids_in_events(events)
        assert counts.get("OOPYjd", 0) >= 2
        assert counts.get("AvwHP", 0) >= 1

    def test_returns_only_found_rpcids(self) -> None:
        events = [{"method": "Network.foo", "params": {"url": "https://example.com"}}]
        counts = find_all_rpcids_in_events(events)
        # No known rpcids in this content
        for rpcid in GAS_RPCIDS:
            assert rpcid not in counts

    def test_empty_events(self) -> None:
        counts = find_all_rpcids_in_events([])
        assert counts == {}


# ──── Constants ───────────────────────────────────────────────────────────────

class TestConstants:
    def test_gas_rpcids_list_nonempty(self) -> None:
        assert len(GAS_RPCIDS) > 0

    def test_batch_execute_hosts_covers_key_services(self) -> None:
        assert "script.google.com" in BATCH_EXECUTE_HOSTS
        assert "notebooklm.google.com" in BATCH_EXECUTE_HOSTS

    def test_known_rpcids_in_gas_list(self) -> None:
        for rpcid in ["OOPYjd", "OQOG2e", "AJ6bre", "AvwHP"]:
            assert rpcid in GAS_RPCIDS
