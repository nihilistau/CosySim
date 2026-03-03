"""Tests for engine.nexus.vscode_history_extractor."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.nexus.vscode_history_extractor import VSCodeHistoryExtractor


# ──── Fixtures ────

@pytest.fixture
def extractor() -> VSCodeHistoryExtractor:
    """Fresh VSCodeHistoryExtractor instance."""
    return VSCodeHistoryExtractor()


def _write_entries(
    history_root: Path,
    folder_name: str,
    resource: str,
    entries: List[Dict[str, Any]],
    snapshots: Dict[str, str],
) -> None:
    """Write a mock History sub-directory with entries.json and snapshot files."""
    folder = history_root / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "entries.json").write_text(
        json.dumps({"resource": resource, "entries": entries}),
        encoding="utf-8",
    )
    for snapshot_id, content in snapshots.items():
        (folder / snapshot_id).write_text(content, encoding="utf-8")


# ──── Tests ────

def test_finds_history_root_on_windows(extractor: VSCodeHistoryExtractor, tmp_path: Path) -> None:
    """_find_history_root should find the directory when APPDATA is set and path exists."""
    fake_history = tmp_path / "Code" / "User" / "History"
    fake_history.mkdir(parents=True)
    with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
        result = extractor._find_history_root()
    assert result == fake_history


def test_extract_edit_pairs_returns_correct_format(
    extractor: VSCodeHistoryExtractor, tmp_path: Path
) -> None:
    """extract_edit_pairs should return dicts with all required keys."""
    history_root = tmp_path / "History"
    _write_entries(
        history_root,
        folder_name="abc123",
        resource="/workspace/engine/foo.py",
        entries=[
            {"id": "snap_before", "source": "Chat: 'add docstrings'", "timestamp": 1000},
            {"id": "snap_after", "source": "Chat Edit: 'add type hints'", "timestamp": 2000},
        ],
        snapshots={
            "snap_before": "def foo():\n    pass\n",
            "snap_after": "def foo() -> None:\n    pass\n",
        },
    )
    with (
        patch.object(extractor, "_find_history_root", return_value=history_root),
        patch.object(extractor, "_find_workspace_hash", return_value=None),
    ):
        pairs = extractor.extract_edit_pairs("/workspace")

    assert len(pairs) >= 1
    p = pairs[0]
    assert "instruction" in p
    assert "input_code" in p
    assert "output_code" in p
    assert "file_path" in p
    assert "language" in p
    assert "source_type" in p


def test_language_inferred_from_extension(extractor: VSCodeHistoryExtractor) -> None:
    """_infer_language should return the correct language for known extensions."""
    assert extractor._infer_language("foo.py") == "python"
    assert extractor._infer_language("bar.ts") == "typescript"
    assert extractor._infer_language("baz.rs") == "rust"
    assert extractor._infer_language("unknown.xyz") == "unknown"


def test_source_type_classified_correctly(extractor: VSCodeHistoryExtractor) -> None:
    """_classify_source_type should distinguish chat edits from manual edits."""
    assert extractor._classify_source_type("Chat Edit: 'add types'") == "chat_edit"
    assert extractor._classify_source_type("chat something") == "chat_edit"
    assert extractor._classify_source_type("manual save") == "manual_edit"
    assert extractor._classify_source_type("") == "manual_edit"


def test_save_to_jsonl_writes_valid_jsonl(
    extractor: VSCodeHistoryExtractor, tmp_path: Path
) -> None:
    """save_to_jsonl should produce a file where every line is valid JSON."""
    pairs = [
        {"instruction": "add types", "input_code": "def f(): pass", "output_code": "def f() -> None: pass", "language": "python"},
        {"instruction": "fix bug", "input_code": "x = 1", "output_code": "x = 2", "language": "python"},
    ]
    out_path = str(tmp_path / "out.jsonl")
    saved = extractor.save_to_jsonl(pairs, output_path=out_path)

    lines = Path(saved).read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "instruction" in obj


def test_run_returns_stats_dict_with_expected_keys(
    extractor: VSCodeHistoryExtractor, tmp_path: Path
) -> None:
    """run() should return a dict with the required stat keys."""
    with (
        patch.object(extractor, "_find_history_root", return_value=tmp_path / "nonexistent"),
        patch.object(extractor, "_find_workspace_hash", return_value=None),
    ):
        result = extractor.run("/workspace", output_path=str(tmp_path / "out.jsonl"))

    assert "pairs_extracted" in result
    assert "output_path" in result
    assert "by_language" in result
    assert "by_source_type" in result


def test_handles_missing_workspace_gracefully(extractor: VSCodeHistoryExtractor) -> None:
    """extract_edit_pairs returns empty list when history root is missing."""
    with patch.object(extractor, "_find_history_root", return_value=None):
        pairs = extractor.extract_edit_pairs("/some/workspace")
    assert pairs == []


def test_handles_malformed_entries_json_gracefully(
    extractor: VSCodeHistoryExtractor, tmp_path: Path
) -> None:
    """Malformed entries.json should be skipped without raising an exception."""
    history_root = tmp_path / "History"
    bad_dir = history_root / "bad_folder"
    bad_dir.mkdir(parents=True)
    (bad_dir / "entries.json").write_text("{invalid json!!", encoding="utf-8")

    with (
        patch.object(extractor, "_find_history_root", return_value=history_root),
        patch.object(extractor, "_find_workspace_hash", return_value=None),
    ):
        pairs = extractor.extract_edit_pairs("/workspace")

    # Should not raise; just return whatever was parseable (possibly empty)
    assert isinstance(pairs, list)


def test_pairs_have_required_keys(extractor: VSCodeHistoryExtractor, tmp_path: Path) -> None:
    """Every extracted pair must have instruction, input_code, and output_code."""
    history_root = tmp_path / "History"
    _write_entries(
        history_root,
        folder_name="folderX",
        resource="/workspace/module.py",
        entries=[
            {"id": "s1", "source": "Chat Edit: 'refactor'", "timestamp": 100},
            {"id": "s2", "source": "Chat Edit: 'add logging'", "timestamp": 200},
        ],
        snapshots={
            "s1": "import os\n",
            "s2": "import os\nimport logging\n",
        },
    )
    with (
        patch.object(extractor, "_find_history_root", return_value=history_root),
        patch.object(extractor, "_find_workspace_hash", return_value=None),
    ):
        pairs = extractor.extract_edit_pairs("/workspace")

    assert len(pairs) >= 1
    for p in pairs:
        assert "instruction" in p
        assert "input_code" in p
        assert "output_code" in p


def test_python_files_have_python_language(
    extractor: VSCodeHistoryExtractor, tmp_path: Path
) -> None:
    """Pairs from .py files should have language='python'."""
    history_root = tmp_path / "History"
    _write_entries(
        history_root,
        folder_name="pyFolder",
        resource="/workspace/engine/my_module.py",
        entries=[
            {"id": "py_before", "source": "Chat Edit: 'add docstrings'", "timestamp": 1},
            {"id": "py_after", "source": "Chat Edit: 'add docstrings done'", "timestamp": 2},
        ],
        snapshots={
            "py_before": "def hello(): pass\n",
            "py_after": "def hello():\n    '''Says hello.'''\n    pass\n",
        },
    )
    with (
        patch.object(extractor, "_find_history_root", return_value=history_root),
        patch.object(extractor, "_find_workspace_hash", return_value=None),
    ):
        pairs = extractor.extract_edit_pairs("/workspace")

    assert len(pairs) >= 1
    assert all(p["language"] == "python" for p in pairs)
