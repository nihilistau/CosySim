"""Tests for engine.nexus.har_extractor — HAR extraction module."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.har_extractor import (
    HARExtractor,
    IngestResult,
    NotebookData,
    _dedup,
    _extract_strings,
    _get_response_text,
    _parse_batchexecute,
)


# ──── Fixtures ────

@pytest.fixture
def extractor():
    """Fresh HARExtractor instance."""
    return HARExtractor()


@pytest.fixture
def sample_har(tmp_path):
    """Create a minimal valid HAR file for testing."""
    har_data = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://notebooklm.google.com/notebook/04168cf3-04a0-46bb-ba58-fec66458aab9",
                        "cookies": [
                            {"name": "SID", "value": "abc123def456ghi789"},
                            {"name": "__Secure-1PSID", "value": "long_cookie_value_here_12345"},
                        ],
                        "headers": [],
                    },
                    "response": {
                        "content": {"text": "page content", "mimeType": "text/html"},
                    },
                },
                {
                    "request": {
                        "url": "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute?rpcids=wXbhsf",
                        "cookies": [],
                        "headers": [],
                    },
                    "response": {
                        "content": {
                            "text": ")]}'\n\n[[\"wrb.fr\",\"wXbhsf\",\"[[[\\\"My Test Notebook\\\",[[[[\\\"src-uuid-1\\\"],\\\"Source Title\\\",null,[null,5000,null,null,null,null,2,[\\\"https://example.com\\\"]]]]]]]]\",null,null,null,\"generic\"]]",
                            "mimeType": "application/x-protobuf",
                        },
                    },
                },
            ]
        }
    }
    har_path = tmp_path / "test.har"
    har_path.write_text(json.dumps(har_data), encoding="utf-8")
    return str(har_path)


@pytest.fixture
def notebook_data():
    """Sample NotebookData for testing."""
    return NotebookData(
        notebook_id="04168cf3-04a0-46bb-ba58-fec66458aab9",
        notebook_name="Test Notebook",
        summary="A test notebook summary that is long enough to count",
        sources=[
            {"id": "src-1", "title": "Source One", "url": "https://example.com", "word_count": 5000},
            {"id": "src-2", "title": "Source Two", "url": "", "word_count": 3000},
        ],
        documents=["This is a document that is long enough to be included in the extraction results for testing purposes."],
        notes=["This is a note that is long enough to be included in the extraction results for testing purposes."],
        conversations=["This is a conversation that is long enough to be included in the extraction results for testing."],
    )


# ──── NotebookData Tests ────

def test_notebook_data_stats(notebook_data):
    """Stats correctly count all content types."""
    stats = notebook_data.stats
    assert stats["sources"] == 2
    assert stats["documents"] == 1
    assert stats["notes"] == 1
    assert stats["conversations"] == 1
    assert stats["total_chars"] > 0


def test_notebook_data_to_dict(notebook_data):
    """to_dict serializes all fields correctly."""
    d = notebook_data.to_dict()
    assert d["notebook_id"] == "04168cf3-04a0-46bb-ba58-fec66458aab9"
    assert d["notebook_name"] == "Test Notebook"
    assert "content" in d
    assert "stats" in d
    assert d["stats"]["sources"] == 2


def test_notebook_data_empty():
    """Empty NotebookData has zero stats."""
    nb = NotebookData()
    assert nb.stats["sources"] == 0
    assert nb.stats["total_chars"] == 0


# ──── Decode Function Tests ────

def test_get_response_text_plain():
    """Decode plain text response."""
    entry = {"response": {"content": {"text": "hello world"}}}
    assert _get_response_text(entry) == "hello world"


def test_get_response_text_base64():
    """Decode base64-encoded response."""
    import base64
    encoded = base64.b64encode(b"decoded content").decode()
    entry = {"response": {"content": {"text": encoded, "encoding": "base64"}}}
    assert _get_response_text(entry) == "decoded content"


def test_get_response_text_empty():
    """Handle missing content gracefully."""
    assert _get_response_text({}) == ""
    assert _get_response_text({"response": {}}) == ""


def test_parse_batchexecute_valid():
    """Parse valid batchexecute response."""
    raw = ')]}\'\\n\\n[["wrb.fr","testRpc","[\\"hello\\"]",null,null,null,"generic"]]'
    # The format has XSSI prefix
    raw2 = ")]}'\n\n[[\"wrb.fr\",\"testRpc\",\"[\\\"hello\\\"]\",null,null,null,\"generic\"]]"
    rpc_id, data = _parse_batchexecute(raw2)
    assert rpc_id == "testRpc"
    assert data == ["hello"]


def test_parse_batchexecute_invalid():
    """Return None for invalid responses."""
    rpc_id, data = _parse_batchexecute("not a valid response")
    assert rpc_id is None
    assert data is None


def test_parse_batchexecute_empty():
    """Handle empty string."""
    rpc_id, data = _parse_batchexecute("")
    assert rpc_id is None


# ──── String Extraction Tests ────

def test_extract_strings_basic():
    """Extract strings from nested structure."""
    data = ["short", "x" * 100, ["nested " * 20, 42], {"key": "value " * 30}]
    result = _extract_strings(data, min_len=80)
    assert len(result) >= 2
    assert all(len(s) >= 80 for s in result)


def test_extract_strings_filters_uuids():
    """Pure hex-dash UUIDs are filtered out."""
    # Pure UUID is filtered
    data = ["04168cf304a046bbba58fec66458aab9abcdef"]
    result = _extract_strings(data, min_len=10)
    assert len(result) == 0

    # String with non-hex chars is kept
    data2 = ["04168cf3-04a0-46bb-ba58-fec66458aab9-extra-chars"]
    result2 = _extract_strings(data2, min_len=10)
    assert len(result2) == 1


def test_extract_strings_empty():
    """Handle empty input."""
    assert _extract_strings(None) == []
    assert _extract_strings([]) == []
    assert _extract_strings("") == []


def test_dedup():
    """Deduplicate by prefix."""
    texts = [
        "This is the first text that is long enough " * 3,
        "This is the first text that is long enough " * 3,  # duplicate
        "This is a different text that should remain " * 3,
    ]
    result = _dedup(texts)
    assert len(result) == 2


def test_dedup_preserves_order():
    """Dedup preserves original order."""
    texts = ["bbb" * 50, "aaa" * 50, "bbb" * 50]
    result = _dedup(texts)
    assert result[0].startswith("bbb")
    assert result[1].startswith("aaa")


# ──── HARExtractor Tests ────

def test_extract_file_not_found(extractor):
    """Raise FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        extractor.extract("nonexistent.har")


def test_extract_cookies_file_not_found(extractor):
    """Raise FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        extractor.extract_cookies("nonexistent.har")


def test_preview_file_not_found(extractor):
    """Raise FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        extractor.preview("nonexistent.har")


def test_extract_empty_har(extractor, tmp_path):
    """Handle HAR with no entries."""
    har_path = tmp_path / "empty.har"
    har_path.write_text('{"log": {"entries": []}}', encoding="utf-8")
    result = extractor.extract(str(har_path))
    assert result == []


def test_extract_finds_notebook_id(extractor, sample_har):
    """Extract notebook ID from page URL."""
    notebooks = extractor.extract(sample_har)
    assert len(notebooks) >= 1
    assert notebooks[0].notebook_id == "04168cf3-04a0-46bb-ba58-fec66458aab9"


def test_extract_cookies(extractor, sample_har):
    """Extract auth cookies from HAR entries."""
    cookies = extractor.extract_cookies(sample_har)
    assert "SID" in cookies
    assert "__Secure-1PSID" in cookies


def test_preview(extractor, sample_har):
    """Preview returns summary info."""
    info = extractor.preview(sample_har)
    assert "har_file" in info
    assert "total_entries" in info
    assert "notebook_ids" in info
    assert "04168cf3-04a0-46bb-ba58-fec66458aab9" in info["notebook_ids"]
    assert info["has_auth_cookies"] is True
    assert info["can_extract"] is True


def test_save_notebook(extractor, notebook_data, tmp_path):
    """Save notebook to JSON file."""
    path = extractor.save_notebook(notebook_data, str(tmp_path))
    assert Path(path).exists()
    with open(path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["notebook_name"] == "Test Notebook"
    assert loaded["stats"]["sources"] == 2


def test_save_notebook_creates_dir(extractor, notebook_data, tmp_path):
    """Save creates output directory if needed."""
    out_dir = tmp_path / "sub" / "dir"
    path = extractor.save_notebook(notebook_data, str(out_dir))
    assert Path(path).exists()


# ──── Ingest Tests ────

def test_ingest_to_nexus(extractor, notebook_data):
    """Ingest stores entries via NexusClient."""
    mock_client = MagicMock()
    mock_client.add_entry.return_value = "entry-123"

    result = extractor.ingest_to_nexus(notebook_data, mock_client)

    assert isinstance(result, IngestResult)
    assert result.entries_created > 0
    assert len(result.errors) == 0
    assert mock_client.add_entry.called


def test_ingest_selective(extractor, notebook_data):
    """Ingest only selected item types."""
    mock_client = MagicMock()
    mock_client.add_entry.return_value = "entry-456"

    result = extractor.ingest_to_nexus(notebook_data, mock_client, items=["sources"])

    # Should only create 1 entry (sources index)
    assert result.entries_created == 1


def test_ingest_handles_errors(extractor, notebook_data):
    """Ingest captures errors without crashing."""
    mock_client = MagicMock()
    mock_client.add_entry.side_effect = Exception("API error")

    result = extractor.ingest_to_nexus(notebook_data, mock_client)

    assert len(result.errors) > 0
    assert "API error" in result.errors[0]
