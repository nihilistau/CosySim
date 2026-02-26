"""Tests for the Nexus→Dataset curation pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.dataset_curator import (
    DatasetCurator,
    CurationStats,
    QualityFilter,
)


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def curator():
    return DatasetCurator(nexus_url="http://test:8700")


@pytest.fixture
def sample_qa():
    return [
        {"question": "How does the interceptor pipeline work?",
         "answer": "The interceptor pipeline processes requests through pre_call and post_call hooks.",
         "category": "architecture", "tags": ["interceptor"]},
        {"question": "What is MCP?",
         "answer": "MCP is the Model Context Protocol framework that manages state.",
         "category": "architecture", "tags": ["mcp"]},
        {"question": "Short Q", "answer": "Tiny", "category": "misc", "tags": []},
    ]


@pytest.fixture
def sample_entries():
    return [
        {"title": "Interceptor Pipeline",
         "content": "The interceptor pipeline is a chain of pre/post processing hooks. " * 5,
         "content_type": "document", "category": "architecture", "tags": ["core"]},
        {"title": "Skill Decorator",
         "content": "@skill decorator registers functions as MCP tools. " * 3,
         "content_type": "code", "category": "api", "tags": ["skills"]},
        {"title": "Tiny", "content": "Too short", "content_type": "note",
         "category": "misc", "tags": []},
    ]


# ── CurationStats ────────────────────────────────────────────────

class TestCurationStats:
    def test_to_dict(self):
        stats = CurationStats(total_fetched=100, exported=50, format="chat_ml")
        d = stats.to_dict()
        assert d["total_fetched"] == 100
        assert d["exported"] == 50
        assert d["format"] == "chat_ml"


# ── Quality Filtering ────────────────────────────────────────────

class TestQAFiltering:
    def test_filters_short_answers(self, curator, sample_qa):
        qf = QualityFilter(min_answer_length=20)
        result = curator._apply_qa_filter(sample_qa, qf)
        assert len(result) == 2  # "Tiny" filtered out

    def test_filters_short_questions(self, curator, sample_qa):
        qf = QualityFilter(min_question_length=20)
        result = curator._apply_qa_filter(sample_qa, qf)
        assert len(result) == 1  # Only the long question passes

    def test_exclude_categories(self, curator, sample_qa):
        qf = QualityFilter(exclude_categories=["misc"])
        result = curator._apply_qa_filter(sample_qa, qf)
        assert all(item["category"] != "misc" for item in result)

    def test_require_categories(self, curator, sample_qa):
        qf = QualityFilter(require_categories=["architecture"])
        result = curator._apply_qa_filter(sample_qa, qf)
        assert all(item["category"] == "architecture" for item in result)

    def test_exclude_tags(self, curator, sample_qa):
        qf = QualityFilter(exclude_tags=["mcp"])
        result = curator._apply_qa_filter(sample_qa, qf)
        questions = [item["question"] for item in result]
        assert "What is MCP?" not in questions

    def test_require_tags(self, curator, sample_qa):
        qf = QualityFilter(require_tags=["interceptor"])
        result = curator._apply_qa_filter(sample_qa, qf)
        assert len(result) == 1


class TestEntryFiltering:
    def test_filters_short_content(self, curator, sample_entries):
        qf = QualityFilter(min_content_length=50)
        result = curator._apply_entry_filter(sample_entries, qf)
        assert len(result) == 2  # "Too short" filtered out

    def test_filters_long_content(self, curator, sample_entries):
        qf = QualityFilter(max_content_length=100)
        result = curator._apply_entry_filter(sample_entries, qf)
        assert len(result) <= 2


# ── Deduplication ────────────────────────────────────────────────

class TestDeduplication:
    def test_dedup_qa(self, curator):
        items = [
            {"question": "What is MCP?", "answer": "Answer 1"},
            {"question": "what is mcp?", "answer": "Answer 2"},
            {"question": "Different Q", "answer": "Answer 3"},
        ]
        result = curator._dedup_qa(items)
        assert len(result) == 2

    def test_dedup_entries(self, curator):
        items = [
            {"title": "Interceptor Pipeline", "content": "v1"},
            {"title": "interceptor pipeline", "content": "v2"},
            {"title": "Skill System", "content": "v3"},
        ]
        result = curator._dedup_entries(items)
        assert len(result) == 2


# ── Formatting ───────────────────────────────────────────────────

class TestFormatting:
    def test_qa_instruction_format(self, curator):
        item = {"question": "What is MCP?", "answer": "A framework."}
        result = curator._format_qa(item, "instruction")
        assert "instruction" in result
        assert result["input"] == "What is MCP?"
        assert result["output"] == "A framework."

    def test_qa_chat_ml_format(self, curator):
        item = {"question": "Q", "answer": "A"}
        result = curator._format_qa(item, "chat_ml")
        assert "messages" in result
        assert len(result["messages"]) == 3
        assert result["messages"][0]["role"] == "system"
        assert result["messages"][1]["role"] == "user"
        assert result["messages"][2]["role"] == "assistant"

    def test_qa_sharegpt_format(self, curator):
        item = {"question": "Q", "answer": "A"}
        result = curator._format_qa(item, "sharegpt")
        assert "conversations" in result
        assert result["conversations"][0]["from"] == "human"
        assert result["conversations"][1]["from"] == "gpt"

    def test_qa_raw_format(self, curator):
        item = {"question": "Q", "answer": "A", "category": "test"}
        result = curator._format_qa(item, "raw")
        assert result["question"] == "Q"
        assert result["category"] == "test"

    def test_entry_instruction_format(self, curator):
        item = {"title": "Pattern X", "content": "Details here.", "content_type": "code"}
        result = curator._format_entry(item, "instruction")
        assert "Explain this code pattern" in result["instruction"]
        assert result["output"] == "Details here."

    def test_entry_chat_ml_format(self, curator):
        item = {"title": "Decision Y", "content": "We chose Z.", "content_type": "decision"}
        result = curator._format_entry(item, "chat_ml")
        assert result["messages"][1]["content"].startswith("What was decided")


# ── File I/O ─────────────────────────────────────────────────────

class TestWriteJSONL:
    def test_writes_jsonl(self, tmp_path):
        items = [{"a": 1}, {"b": 2}]
        path = str(tmp_path / "test.jsonl")
        DatasetCurator._write_jsonl(items, path)
        lines = Path(path).read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"a": 1}

    def test_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "sub" / "dir" / "test.jsonl")
        DatasetCurator._write_jsonl([{"x": 1}], path)
        assert Path(path).exists()


# ── Full Pipeline ────────────────────────────────────────────────

class TestExportQADataset:
    def test_end_to_end(self, curator, sample_qa, tmp_path):
        path = str(tmp_path / "qa.jsonl")
        with patch.object(curator, "_fetch_qa", return_value=sample_qa):
            stats = curator.export_qa_dataset(path, fmt="instruction")
        assert stats.total_fetched == 3
        assert stats.exported >= 1
        assert Path(path).exists()
        lines = Path(path).read_text().strip().split("\n")
        assert len(lines) == stats.exported

    def test_chat_ml_format(self, curator, sample_qa, tmp_path):
        path = str(tmp_path / "qa_chat.jsonl")
        with patch.object(curator, "_fetch_qa", return_value=sample_qa):
            stats = curator.export_qa_dataset(path, fmt="chat_ml")
        line = json.loads(Path(path).read_text().strip().split("\n")[0])
        assert "messages" in line


class TestExportInstructionDataset:
    def test_end_to_end(self, curator, sample_entries, tmp_path):
        path = str(tmp_path / "instruct.jsonl")
        with patch.object(curator, "_fetch_entries", return_value=sample_entries):
            stats = curator.export_instruction_dataset(path)
        assert stats.total_fetched == 3
        assert stats.exported >= 1
        assert Path(path).exists()


class TestExportCombinedDataset:
    def test_end_to_end(self, curator, sample_qa, sample_entries, tmp_path):
        path = str(tmp_path / "combined.jsonl")
        with patch.object(curator, "_fetch_qa", return_value=sample_qa):
            with patch.object(curator, "_fetch_entries", return_value=sample_entries):
                stats = curator.export_combined_dataset(path)
        assert stats.total_fetched == len(sample_qa) + len(sample_entries)
        assert stats.exported >= 2


class TestPreview:
    def test_preview_qa(self, curator, sample_qa):
        with patch.object(curator, "_fetch_qa", return_value=sample_qa):
            examples = curator.preview(source="qa", limit=2)
        assert len(examples) == 2

    def test_preview_entries(self, curator, sample_entries):
        with patch.object(curator, "_fetch_entries", return_value=sample_entries):
            examples = curator.preview(source="entries", limit=2)
        assert len(examples) == 2
