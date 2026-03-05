"""Tests for ARGUS HAR scanner and SDK auditor.

Covers: ScanStats defaults, synthetic HAR scanning, batchexecute detection,
gRPC-web detection, deduplication by content hash, GAS URL classification,
payload file saving, report structure, AST method extraction, ClientAudit
coverage calculation, and missing/extra detection.

All file I/O uses tmp_path — no real HAR files are read.
"""
from __future__ import annotations

import ast
import json
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ──── Helpers ─────────────────────────────────────────────────────────────────


def _make_be_post(rpcid: str, payload_raw: str = "[]") -> str:
    """Build a URL-encoded f.req POST body for a batchexecute call."""
    freq = json.dumps([[[rpcid, payload_raw, None, "generic"]]])
    return "f.req=" + urllib.parse.quote(freq)


def _make_be_response(rpcid: str, data_raw: str = '""') -> str:
    """Build a minimal batchexecute response with one wrb.fr frame."""
    frame = [[["wrb.fr", rpcid, data_raw, None, None, None, "generic"]]]
    return ")]}'\n" + json.dumps(frame)


def _make_har(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrap HAR entries in a minimal HAR envelope."""
    return {"log": {"entries": entries}}


def _make_be_entry(
    url: str,
    rpcid: str,
    payload_raw: str = "[]",
    response_text: str = "",
    response_encoding: str = "",
) -> Dict[str, Any]:
    """Build a HAR entry for a batchexecute request."""
    content: Dict[str, Any] = {
        "text": response_text,
        "mimeType": "application/json",
    }
    if response_encoding:
        content["encoding"] = response_encoding
    return {
        "request": {
            "url": url,
            "method": "POST",
            "postData": {"text": _make_be_post(rpcid, payload_raw)},
        },
        "response": {"content": content},
    }


def _make_grpc_entry(url: str) -> Dict[str, Any]:
    """Build a HAR entry for a gRPC-web request (no body needed)."""
    return {
        "request": {
            "url": url,
            "method": "POST",
            "postData": {"text": "{}"},
        },
        "response": {
            "content": {"text": '{"result": "ok"}', "mimeType": "application/json"},
        },
    }


def _write_har(tmp_path: Path, name: str, entries: List[Dict[str, Any]]) -> Path:
    """Write a HAR file under tmp_path and return its Path."""
    har = _make_har(entries)
    p = tmp_path / name
    p.write_text(json.dumps(har), encoding="utf-8")
    return p


def _make_scanner(tmp_path: Path):
    """Create a HarScanner with isolated payloads dir and fresh registry."""
    from scripts.argus.har_scanner import HarScanner
    from scripts.argus.discovery.endpoint_registry import EndpointRegistry

    registry = EndpointRegistry(path=tmp_path / "registry.json")
    payloads_dir = tmp_path / "payloads"
    return HarScanner(payloads_dir=payloads_dir, registry=registry)


# ──── ScanStats ───────────────────────────────────────────────────────────────


class TestScanStats:
    def test_defaults_are_zero(self) -> None:
        from scripts.argus.har_scanner import ScanStats

        stats = ScanStats()
        assert stats.files_scanned == 0
        assert stats.requests_total == 0
        assert stats.batchexecute_calls == 0
        assert stats.grpc_calls == 0
        assert stats.rpcids_nlm == 0
        assert stats.rpcids_gemini == 0
        assert stats.rpcids_gas == 0
        assert stats.rpcids_unknown == 0
        assert stats.new_discoveries == 0
        assert stats.errors == 0

    def test_construction_with_values(self) -> None:
        from scripts.argus.har_scanner import ScanStats

        stats = ScanStats(files_scanned=3, batchexecute_calls=7, rpcids_nlm=2)
        assert stats.files_scanned == 3
        assert stats.batchexecute_calls == 7
        assert stats.rpcids_nlm == 2
        assert stats.errors == 0  # unprovided fields stay 0


# ──── scan_file — general ─────────────────────────────────────────────────────


class TestScanFile:
    def test_scan_file_counts_one_file(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        har_path = _write_har(tmp_path, "empty.har", [])
        stats = scanner.scan_file(har_path)
        assert stats.files_scanned == 1

    def test_scan_file_zero_entries_yields_zero_requests(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        har_path = _write_har(tmp_path, "empty.har", [])
        stats = scanner.scan_file(har_path)
        assert stats.requests_total == 0

    def test_scan_file_skips_get_requests(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        entry = {
            "request": {
                "url": "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute",
                "method": "GET",
                "postData": {},
            },
            "response": {"content": {"text": ""}},
        }
        har_path = _write_har(tmp_path, "get.har", [entry])
        stats = scanner.scan_file(har_path)
        assert stats.batchexecute_calls == 0

    def test_scan_file_records_error_on_corrupt_json(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        p = tmp_path / "bad.har"
        p.write_text("not valid json", encoding="utf-8")
        stats = scanner.scan_file(p)
        assert stats.errors >= 1
        assert stats.files_scanned == 1

    def test_scan_file_appends_path_to_files_list(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        har_path = _write_har(tmp_path, "test.har", [])
        scanner.scan_file(har_path)
        assert str(har_path) in scanner._files_scanned


# ──── Batchexecute detection & decoding ───────────────────────────────────────


class TestBatchexecuteDetection:
    def test_nlm_rpcid_detected(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
        rpcid = "wIlBFe"  # ListNotebooks — in NLM_RPCIDS baseline
        har_path = _write_har(tmp_path, "nlm.har", [_make_be_entry(url, rpcid)])
        stats = scanner.scan_file(har_path)

        assert stats.batchexecute_calls == 1
        assert stats.rpcids_nlm == 1
        assert rpcid in scanner._seen_nlm

    def test_gemini_rpcid_detected(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = "https://gemini.google.com/_/BardChatUi/data/batchexecute"
        rpcid = "jKHnxe"  # GenerateContent — in GEMINI_RPCIDS
        har_path = _write_har(tmp_path, "gemini.har", [_make_be_entry(url, rpcid)])
        stats = scanner.scan_file(har_path)

        assert stats.batchexecute_calls == 1
        assert stats.rpcids_gemini == 1
        assert rpcid in scanner._seen_gemini

    def test_multiple_entries_accumulated(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
        entries = [
            _make_be_entry(url, "wIlBFe"),
            _make_be_entry(url, "VqhFhd"),
            _make_be_entry(url, "wIlBFe"),  # duplicate — same rpcid
        ]
        har_path = _write_har(tmp_path, "multi.har", entries)
        stats = scanner.scan_file(har_path)

        assert stats.batchexecute_calls == 3
        assert stats.rpcids_nlm == 2  # unique rpcids in this file

    def test_unknown_rpcid_goes_to_unknown_bucket(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = "https://someservice.google.com/_/SomeUi/data/batchexecute"
        rpcid = "XxXxXxXx"  # not in any known baseline
        har_path = _write_har(tmp_path, "unk.har", [_make_be_entry(url, rpcid)])
        stats = scanner.scan_file(har_path)

        assert stats.rpcids_unknown == 1
        assert rpcid in scanner._seen_unknown

    def test_response_is_decoded_and_saved(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
        rpcid = "wIlBFe"
        response = _make_be_response(rpcid, '"[{\\"id\\":\\"nb1\\"}]"')
        entries = [_make_be_entry(url, rpcid, response_text=response)]
        har_path = _write_har(tmp_path, "with_resp.har", entries)
        scanner.scan_file(har_path)

        resp_file = scanner._payloads_dir / f"{rpcid}_response.json"
        assert resp_file.exists(), "Response payload file should be written"

    def test_base64_response_is_decoded(self, tmp_path: Path) -> None:
        import base64

        scanner = _make_scanner(tmp_path)
        url = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
        rpcid = "mFtdI"  # GetNotebook
        response_plain = _make_be_response(rpcid, '"data"')
        b64 = base64.b64encode(response_plain.encode()).decode()
        entries = [
            _make_be_entry(url, rpcid, response_text=b64, response_encoding="base64")
        ]
        har_path = _write_har(tmp_path, "b64.har", entries)
        stats = scanner.scan_file(har_path)

        # No error even though response was base64-encoded
        assert stats.errors == 0
        assert stats.batchexecute_calls == 1


# ──── gRPC-web detection ──────────────────────────────────────────────────────


class TestGrpcDetection:
    def test_grpc_rpc_slash_detected(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = (
            "https://alkalimakersuite-pa.clients6.google.com"
            "/$rpc/google.internal.alkali.applications.makersuite.v1"
            ".MakerSuiteService/GenerateContent"
        )
        har_path = _write_har(tmp_path, "grpc.har", [_make_grpc_entry(url)])
        stats = scanner.scan_file(har_path)

        assert stats.grpc_calls == 1
        assert stats.batchexecute_calls == 0

    def test_grpc_clients6_detected_without_rpc_slash(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = "https://webchannel-alkalimakersuite-pa.clients6.google.com/something"
        har_path = _write_har(tmp_path, "grpc2.har", [_make_grpc_entry(url)])
        stats = scanner.scan_file(har_path)

        assert stats.grpc_calls == 1

    def test_batchexecute_takes_priority_over_clients6(self, tmp_path: Path) -> None:
        """A URL containing both 'batchexecute' and 'clients6.google.com'
        should be classified as batchexecute, not gRPC."""
        scanner = _make_scanner(tmp_path)
        url = "https://some.clients6.google.com/_/Foo/data/batchexecute"
        rpcid = "testRpc"
        har_path = _write_har(tmp_path, "both.har", [_make_be_entry(url, rpcid)])
        stats = scanner.scan_file(har_path)

        assert stats.batchexecute_calls == 1
        assert stats.grpc_calls == 0


# ──── GAS classification ──────────────────────────────────────────────────────


class TestGasClassification:
    def test_script_google_com_classified_as_gas(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = (
            "https://script.google.com/_/AppsPlatformConsoleUi/data/batchexecute"
        )
        rpcid = "OOPYjd"  # GetProjectContent — in GAS_RPCIDS baseline
        har_path = _write_har(tmp_path, "gas.har", [_make_be_entry(url, rpcid)])
        stats = scanner.scan_file(har_path)

        assert stats.rpcids_gas == 1
        assert rpcid in scanner._seen_gas
        assert rpcid not in scanner._seen_nlm
        assert rpcid not in scanner._seen_gemini

    def test_gas_rpcid_not_in_baseline_is_new_discovery(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = (
            "https://script.google.com/_/AppsPlatformConsoleUi/data/batchexecute"
        )
        new_rpcid = "NewGasXxx"
        har_path = _write_har(tmp_path, "gas_new.har", [_make_be_entry(url, new_rpcid)])
        stats = scanner.scan_file(har_path)

        assert new_rpcid in scanner._new_discoveries
        assert stats.new_discoveries >= 1


# ──── Deduplication ───────────────────────────────────────────────────────────


class TestDeduplication:
    def test_identical_files_processed_once(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
        entries = [_make_be_entry(url, "wIlBFe")]

        dir_a = tmp_path / "folderA"
        dir_a.mkdir()
        dir_b = tmp_path / "folderB"
        dir_b.mkdir()

        # Write identical content to two different paths
        content = json.dumps(_make_har(entries))
        (dir_a / "nlm.har").write_text(content)
        (dir_b / "nlm.har").write_text(content)  # same bytes

        stats = scanner.scan_directory(tmp_path)

        assert stats.files_scanned == 1, (
            "Duplicate file (same content hash) should be processed only once"
        )

    def test_different_content_both_processed(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"

        dir_a = tmp_path / "a"
        dir_a.mkdir()
        dir_b = tmp_path / "b"
        dir_b.mkdir()

        (dir_a / "f1.har").write_text(
            json.dumps(_make_har([_make_be_entry(url, "wIlBFe")]))
        )
        (dir_b / "f2.har").write_text(
            json.dumps(_make_har([_make_be_entry(url, "VqhFhd")]))
        )

        stats = scanner.scan_directory(tmp_path)
        assert stats.files_scanned == 2


# ──── Payload saving ──────────────────────────────────────────────────────────


class TestPayloadSaving:
    def test_request_payload_file_created(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
        rpcid = "wIlBFe"
        har_path = _write_har(tmp_path, "nlm.har", [_make_be_entry(url, rpcid)])
        scanner.scan_file(har_path)

        req_file = scanner._payloads_dir / f"{rpcid}_request.json"
        assert req_file.exists()
        data = json.loads(req_file.read_text())
        assert data["rpcid"] == rpcid

    def test_first_seen_payload_only_saved_once(self, tmp_path: Path) -> None:
        """Scanning the same rpcid twice should not overwrite the payload."""
        scanner = _make_scanner(tmp_path)
        url = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
        rpcid = "wIlBFe"
        entries = [
            _make_be_entry(url, rpcid, payload_raw='["first"]'),
            _make_be_entry(url, rpcid, payload_raw='["second"]'),
        ]
        har_path = _write_har(tmp_path, "multi.har", entries)
        scanner.scan_file(har_path)

        req_file = scanner._payloads_dir / f"{rpcid}_request.json"
        data = json.loads(req_file.read_text())
        assert data["payload_raw"] == '["first"]', "Second payload must not overwrite first"


# ──── get_report structure ────────────────────────────────────────────────────


class TestGetReport:
    def test_report_has_required_keys(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        report = scanner.get_report()

        required = {
            "generated_at", "files_scanned", "files", "requests_total",
            "batchexecute_calls", "grpc_calls", "rpcids_by_service",
            "rpcid_counts", "new_discoveries", "new_discovery_count",
            "rpcid_details", "errors", "payloads_dir",
        }
        assert required <= set(report.keys())

    def test_report_rpcids_by_service_has_all_buckets(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        report = scanner.get_report()
        assert set(report["rpcids_by_service"].keys()) == {"nlm", "gemini", "gas", "unknown"}

    def test_report_reflects_scan_results(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        url = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
        entries = [_make_be_entry(url, "wIlBFe"), _make_be_entry(url, "VqhFhd")]
        scanner.scan_directory(_write_har(tmp_path, "nlm.har", entries).parent)

        report = scanner.get_report()
        assert report["rpcid_counts"]["nlm"] == 2
        assert "wIlBFe" in report["rpcids_by_service"]["nlm"]
        assert "VqhFhd" in report["rpcids_by_service"]["nlm"]

    def test_save_report_writes_json(self, tmp_path: Path) -> None:
        scanner = _make_scanner(tmp_path)
        out_path = tmp_path / "report.json"
        scanner.save_report(out_path)

        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert "generated_at" in data


# ──── SDKAuditor — AST extraction ────────────────────────────────────────────


STUB_CLIENT = '''\
"""Stub client for testing."""
from __future__ import annotations


class MyClient:
    """A simple stub client."""

    def __init__(self) -> None:
        pass

    def list_notebooks(self) -> list:
        """List notebooks."""
        return []

    def create_notebook(self, title: str) -> dict:
        """Create a notebook."""
        return {}

    def delete_notebook(self, notebook_id: str) -> None:
        """Delete a notebook."""

    def _private_helper(self) -> None:
        """Should NOT appear in extracted methods."""

    def __repr__(self) -> str:
        return "MyClient()"


def module_level_function() -> str:
    """Top-level — should appear."""
    return "ok"


def _private_module_func() -> None:
    """Private — should NOT appear."""
'''


class TestAstExtraction:
    def test_public_methods_extracted(self, tmp_path: Path) -> None:
        from scripts.argus.sdk_auditor import SDKAuditor

        stub = tmp_path / "stub_client.py"
        stub.write_text(STUB_CLIENT, encoding="utf-8")
        auditor = SDKAuditor(payloads_dir=tmp_path / "payloads")
        methods = auditor._extract_methods(stub)

        assert "list_notebooks" in methods
        assert "create_notebook" in methods
        assert "delete_notebook" in methods
        assert "module_level_function" in methods

    def test_private_methods_excluded(self, tmp_path: Path) -> None:
        from scripts.argus.sdk_auditor import SDKAuditor

        stub = tmp_path / "stub_client.py"
        stub.write_text(STUB_CLIENT, encoding="utf-8")
        auditor = SDKAuditor(payloads_dir=tmp_path / "payloads")
        methods = auditor._extract_methods(stub)

        assert "_private_helper" not in methods
        assert "_private_module_func" not in methods
        assert "__init__" not in methods
        assert "__repr__" not in methods

    def test_invalid_file_returns_empty(self, tmp_path: Path) -> None:
        from scripts.argus.sdk_auditor import SDKAuditor

        bad = tmp_path / "bad.py"
        bad.write_text("def broken(\n", encoding="utf-8")
        auditor = SDKAuditor(payloads_dir=tmp_path / "payloads")
        assert auditor._extract_methods(bad) == []

    def test_no_duplicates_in_result(self, tmp_path: Path) -> None:
        from scripts.argus.sdk_auditor import SDKAuditor

        stub = tmp_path / "stub_client.py"
        stub.write_text(STUB_CLIENT, encoding="utf-8")
        auditor = SDKAuditor(payloads_dir=tmp_path / "payloads")
        methods = auditor._extract_methods(stub)

        assert len(methods) == len(set(methods)), "No duplicate method names"


# ──── ClientAudit coverage calculation ───────────────────────────────────────


class TestClientAuditCoverage:
    def _auditor(self, tmp_path: Path):
        from scripts.argus.sdk_auditor import SDKAuditor
        return SDKAuditor(payloads_dir=tmp_path / "payloads")

    def test_full_coverage(self, tmp_path: Path) -> None:
        stub = tmp_path / "client.py"
        stub.write_text(
            "class C:\n"
            "    def list_notebooks(self): pass\n"
            "    def create_notebook(self): pass\n",
            encoding="utf-8",
        )
        auditor = self._auditor(tmp_path)
        audit = auditor.audit_client(
            stub,
            {"r1": "ListNotebooks", "r2": "CreateNotebook"},
        )
        assert audit.coverage_pct == 100.0
        assert audit.missing == []

    def test_partial_coverage(self, tmp_path: Path) -> None:
        stub = tmp_path / "client.py"
        stub.write_text(
            "class C:\n"
            "    def list_notebooks(self): pass\n",
            encoding="utf-8",
        )
        auditor = self._auditor(tmp_path)
        audit = auditor.audit_client(
            stub,
            {"r1": "ListNotebooks", "r2": "CreateNotebook", "r3": "AddSource"},
        )
        assert audit.coverage_pct == pytest.approx(100 / 3, abs=0.5)
        assert "create_notebook" in audit.missing
        assert "add_source" in audit.missing

    def test_zero_coverage(self, tmp_path: Path) -> None:
        stub = tmp_path / "client.py"
        stub.write_text("class C:\n    def helper(self): pass\n", encoding="utf-8")
        auditor = self._auditor(tmp_path)
        audit = auditor.audit_client(
            stub,
            {"r1": "ListNotebooks", "r2": "CreateNotebook"},
        )
        assert audit.coverage_pct == 0.0
        assert len(audit.missing) == 2

    def test_empty_known_api_gives_100_pct(self, tmp_path: Path) -> None:
        stub = tmp_path / "client.py"
        stub.write_text("class C:\n    def something(self): pass\n", encoding="utf-8")
        auditor = self._auditor(tmp_path)
        audit = auditor.audit_client(stub, {})
        assert audit.coverage_pct == 100.0


# ──── Missing / extra detection ───────────────────────────────────────────────


class TestMissingExtra:
    def _auditor(self, tmp_path: Path):
        from scripts.argus.sdk_auditor import SDKAuditor
        return SDKAuditor(payloads_dir=tmp_path / "payloads")

    def test_extra_methods_detected(self, tmp_path: Path) -> None:
        stub = tmp_path / "client.py"
        stub.write_text(
            "class C:\n"
            "    def list_notebooks(self): pass\n"
            "    def helper_utility(self): pass\n"  # not in known API
            "    def another_extra(self): pass\n",
            encoding="utf-8",
        )
        auditor = self._auditor(tmp_path)
        audit = auditor.audit_client(stub, {"r1": "ListNotebooks"})
        assert "helper_utility" in audit.extra
        assert "another_extra" in audit.extra

    def test_missing_uses_snake_case(self, tmp_path: Path) -> None:
        stub = tmp_path / "client.py"
        stub.write_text("class C: pass\n", encoding="utf-8")
        auditor = self._auditor(tmp_path)
        audit = auditor.audit_client(stub, {"r1": "GetChatHistory"})
        # Missing should be in snake_case
        assert "get_chat_history" in audit.missing

    def test_known_api_items_preserved_as_originals(self, tmp_path: Path) -> None:
        stub = tmp_path / "client.py"
        stub.write_text("class C: pass\n", encoding="utf-8")
        auditor = self._auditor(tmp_path)
        audit = auditor.audit_client(
            stub, {"r1": "GenerateContent", "r2": "StreamGenerateContent"}
        )
        assert "GenerateContent" in audit.known_api_items
        assert "StreamGenerateContent" in audit.known_api_items


# ──── Pascal-to-snake utility ─────────────────────────────────────────────────


class TestPascalToSnake:
    def test_simple_pascal(self) -> None:
        from scripts.argus.sdk_auditor import _pascal_to_snake

        assert _pascal_to_snake("ListNotebooks") == "list_notebooks"
        assert _pascal_to_snake("CreateNotebook") == "create_notebook"

    def test_multi_word(self) -> None:
        from scripts.argus.sdk_auditor import _pascal_to_snake

        assert _pascal_to_snake("GetAudioOverview") == "get_audio_overview"
        assert _pascal_to_snake("StreamGenerateContent") == "stream_generate_content"

    def test_already_snake(self) -> None:
        from scripts.argus.sdk_auditor import _pascal_to_snake

        # snake_case input should stay snake_case (lowercased)
        assert _pascal_to_snake("list_notebooks") == "list_notebooks"
