"""Tests for engine.integrations.har_parser."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from engine.integrations.har_parser import (
    _extract_body,
    _extract_request_body,
    _headers_dict,
    analyze_har,
    extract_cookies,
    find_har_file,
    get_entries,
    get_entry,
    list_har_files,
    normalize_entry,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_har(entries: List[Dict[str, Any]]) -> Dict:
    return {"log": {"version": "1.2", "entries": entries}}


def _make_entry(
    url: str = "https://example.com/api/test",
    method: str = "POST",
    status: int = 200,
    request_headers: List[Dict] = None,
    response_body: str = '{"ok": true}',
    request_body: str = '{"input": 1}',
    request_cookies: List[Dict] = None,
    time_ms: float = 42.5,
) -> Dict:
    return {
        "request": {
            "method": method,
            "url": url,
            "headers": request_headers or [
                {"name": "Content-Type", "value": "application/json"},
                {"name": "Authorization", "value": "Bearer TOKEN"},
            ],
            "cookies": request_cookies or [
                {"name": "session_id", "value": "abc123"},
            ],
            "postData": {"text": request_body} if request_body else None,
        },
        "response": {
            "status": status,
            "content": {
                "size": len(response_body),
                "mimeType": "application/json",
                "text": response_body,
            },
            "headers": [
                {"name": "Content-Type", "value": "application/json"},
            ],
            "cookies": [],
        },
        "time": time_ms,
        "timings": {"send": 1.0, "wait": 40.0, "receive": 1.5},
    }


@pytest.fixture
def har_file(tmp_path: Path) -> Path:
    """Write a small HAR file with 5 entries and return the path."""
    entries = [
        _make_entry(url="https://api.example.com/v1/create", method="POST", status=201),
        _make_entry(url="https://api.example.com/v1/list", method="GET", status=200),
        _make_entry(url="https://notebooklm.google.com/$rpc/MaestroUiService/GenerateFreeFormStreamed", method="POST", status=200,
                    request_cookies=[{"name": "SAPISID", "value": "sapisid_value"}]),
        _make_entry(url="https://colab.clients6.google.com/$rpc/CreateAgentTask", method="POST", status=200),
        _make_entry(url="https://api.individual.githubcopilot.com/models", method="GET", status=200,
                    request_headers=[{"name": "Authorization", "value": "GitHub-Bearer tok123"}]),
    ]
    har_path = tmp_path / "test.har"
    har_path.write_text(json.dumps(_make_har(entries)), encoding="utf-8")
    return har_path


# ── normalize_entry ───────────────────────────────────────────────────────────


def test_normalize_entry_basic():
    e = _make_entry()
    result = normalize_entry(e)
    assert result["url"] == "https://example.com/api/test"
    assert result["method"] == "POST"
    assert result["status"] == 200
    assert result["time_ms"] == 42.5
    assert result["send_time_ms"] == 1.0
    assert result["wait_time_ms"] == 40.0


def test_normalize_entry_headers():
    e = _make_entry()
    result = normalize_entry(e)
    assert result["request_headers"]["Content-Type"] == "application/json"
    assert result["request_headers"]["Authorization"] == "Bearer TOKEN"
    assert result["response_headers"]["Content-Type"] == "application/json"


def test_normalize_entry_cookies():
    e = _make_entry()
    result = normalize_entry(e)
    assert result["request_cookies"] == [{"name": "session_id", "value": "abc123"}]
    assert result["response_cookies"] == []


def test_normalize_entry_bodies():
    e = _make_entry(request_body='{"x": 1}', response_body='{"y": 2}')
    result = normalize_entry(e)
    assert result["request_body"] == '{"x": 1}'
    assert result["response_body"] == '{"y": 2}'


def test_normalize_entry_empty_postdata():
    e = _make_entry()
    e["request"]["postData"] = None
    result = normalize_entry(e)
    assert result["request_body"] == ""


def test_normalize_entry_body_truncation():
    long_body = "x" * 20000
    e = _make_entry(response_body=long_body)
    result = normalize_entry(e)
    assert len(result["response_body"]) < 20000
    assert "truncated" in result["response_body"]


# ── helpers ───────────────────────────────────────────────────────────────────


def test_headers_dict_last_wins():
    headers = [
        {"name": "X-Foo", "value": "first"},
        {"name": "X-Foo", "value": "second"},
    ]
    result = _headers_dict(headers)
    assert result["X-Foo"] == "second"


def test_headers_dict_empty():
    assert _headers_dict([]) == {}
    assert _headers_dict(None) == {}


# ── get_entries ───────────────────────────────────────────────────────────────


def test_get_entries_total(har_file: Path):
    result = get_entries(str(har_file))
    assert result["total"] == 5
    assert len(result["entries"]) == 5


def test_get_entries_url_filter(har_file: Path):
    result = get_entries(str(har_file), url_search="notebooklm")
    assert result["total"] == 1
    assert "notebooklm" in result["entries"][0]["url"]


def test_get_entries_method_filter(har_file: Path):
    result = get_entries(str(har_file), method_filter="GET")
    assert result["total"] == 2
    for e in result["entries"]:
        assert e["method"] == "GET"


def test_get_entries_pagination(har_file: Path):
    result = get_entries(str(har_file), limit=2, offset=0)
    assert len(result["entries"]) == 2
    assert result["total"] == 5

    result2 = get_entries(str(har_file), limit=2, offset=2)
    assert len(result2["entries"]) == 2


def test_get_entries_empty_result(har_file: Path):
    result = get_entries(str(har_file), url_search="does_not_exist_xyz")
    assert result["total"] == 0
    assert result["entries"] == []


def test_get_entries_returns_full_entry(har_file: Path):
    result = get_entries(str(har_file))
    entry = result["entries"][0]
    assert "request_headers" in entry
    assert "response_body" in entry
    assert "request_cookies" in entry


# ── get_entry ─────────────────────────────────────────────────────────────────


def test_get_entry_valid(har_file: Path):
    entry = get_entry(str(har_file), 0)
    assert entry is not None
    assert entry["url"] == "https://api.example.com/v1/create"
    assert entry["method"] == "POST"
    assert entry["status"] == 201


def test_get_entry_out_of_range(har_file: Path):
    assert get_entry(str(har_file), 999) is None


def test_get_entry_negative(har_file: Path):
    assert get_entry(str(har_file), -1) is None


# ── extract_cookies ───────────────────────────────────────────────────────────


def test_extract_cookies_from_har(har_file: Path):
    cookies = extract_cookies(str(har_file))
    assert "session_id" in cookies
    assert cookies["session_id"] == "abc123"


def test_extract_cookies_with_domain_filter(har_file: Path):
    cookies = extract_cookies(str(har_file), domain="notebooklm")
    assert "SAPISID" in cookies
    # session_id is from example.com so should NOT be here
    assert "session_id" not in cookies


def test_extract_cookies_no_match(har_file: Path):
    cookies = extract_cookies(str(har_file), domain="nonexistent.example.com")
    assert cookies == {}


# ── analyze_har ───────────────────────────────────────────────────────────────


def test_analyze_har_basic(har_file: Path):
    result = analyze_har(str(har_file))
    assert result["total_entries"] == 5
    assert "api.example.com" in result["unique_domains"]
    assert "POST" in result["methods"]
    assert "GET" in result["methods"]


def test_analyze_har_github_auth_detected(har_file: Path):
    result = analyze_har(str(har_file))
    assert result["has_github_auth"] is True
    assert result["gh_bearer_found"] is True


def test_analyze_har_google_auth_detected(har_file: Path):
    result = analyze_har(str(har_file))
    assert result["has_google_auth"] is True
    assert result["sapisid_found"] is True


def test_analyze_har_interesting_domains(har_file: Path):
    result = analyze_har(str(har_file))
    interesting = result["interesting_domains"]
    assert any("notebooklm" in d for d in interesting)
    assert any("colab" in d or "githubcopilot" in d for d in interesting)


def test_analyze_har_status_distribution(har_file: Path):
    result = analyze_har(str(har_file))
    dist = result["status_distribution"]
    assert 200 in dist or "200" in dist


# ── find_har_file ─────────────────────────────────────────────────────────────


def test_find_har_file_returns_none_for_missing():
    result = find_har_file("does_not_exist_at_all_xyz.har")
    assert result is None


def test_find_har_file_finds_in_base_dir(tmp_path: Path):
    fake_har = tmp_path / "subdir" / "test.har"
    fake_har.parent.mkdir()
    fake_har.write_text("{}", encoding="utf-8")

    from engine.integrations import har_parser
    original_dirs = har_parser.HAR_BASE_DIRS[:]
    har_parser.HAR_BASE_DIRS = [str(tmp_path)]
    try:
        result = find_har_file("test.har")
        assert result == str(fake_har)
    finally:
        har_parser.HAR_BASE_DIRS = original_dirs


# ── list_har_files ─────────────────────────────────────────────────────────────


def test_list_har_files_returns_list(tmp_path: Path):
    (tmp_path / "a.har").write_text("{}", encoding="utf-8")
    (tmp_path / "b.har").write_text("{}", encoding="utf-8")
    (tmp_path / "c.txt").write_text("not har", encoding="utf-8")

    from engine.integrations import har_parser
    original_dirs = har_parser.HAR_BASE_DIRS[:]
    har_parser.HAR_BASE_DIRS = [str(tmp_path)]
    try:
        files = list_har_files()
        names = [f["name"] for f in files]
        assert "a.har" in names
        assert "b.har" in names
        assert "c.txt" not in names
    finally:
        har_parser.HAR_BASE_DIRS = original_dirs


def test_list_har_files_fields(tmp_path: Path):
    (tmp_path / "test.har").write_text('{"log": {"entries": []}}', encoding="utf-8")

    from engine.integrations import har_parser
    original_dirs = har_parser.HAR_BASE_DIRS[:]
    har_parser.HAR_BASE_DIRS = [str(tmp_path)]
    try:
        files = list_har_files()
        assert len(files) == 1
        f = files[0]
        assert "name" in f
        assert "path" in f
        assert "size_mb" in f
        assert isinstance(f["size_mb"], float)
    finally:
        har_parser.HAR_BASE_DIRS = original_dirs


# ── dict wrappers ─────────────────────────────────────────────────────────────


def test_get_entries_dict_file_not_found():
    from engine.integrations.har_parser import get_entries_dict
    result = get_entries_dict(filename="totally_fake_xyz.har")
    assert "error" in result
    assert result["total"] == 0


def test_get_entry_dict_file_not_found():
    from engine.integrations.har_parser import get_entry_dict
    result = get_entry_dict(filename="fake.har", idx=0)
    assert "error" in result


def test_analyze_har_dict_file_not_found():
    from engine.integrations.har_parser import analyze_har_dict
    result = analyze_har_dict(filename="fake.har")
    assert "error" in result
