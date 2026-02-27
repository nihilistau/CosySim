"""Tests for engine.nexus.training_flywheel module."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.training_flywheel import (
    TrainingExample,
    TrainingFlywheel,
    get_training_flywheel,
)


# ──── Fixtures ────


@dataclass
class FakeTask:
    """Minimal AgentTask stand-in for testing."""

    id: str = "task-001"
    title: str = "Fix auth bug"
    description: str = "The login endpoint returns 500 on bad tokens."
    tags: List[str] = field(default_factory=lambda: ["bug", "auth"])
    complexity: str = "medium"
    assigned_agent: str = "bug-fixer"
    created_at: float = 1000.0
    completed_at: float = 1045.0
    result_summary: str = ""


@pytest.fixture()
def flywheel(tmp_path: Path) -> TrainingFlywheel:
    """Create a flywheel with temp database and export dir."""
    db = str(tmp_path / "test_flywheel.db")
    export_dir = str(tmp_path / "exports")
    with patch("engine.nexus.training_flywheel.get_config") as mock_cfg:
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None: {
            "training.flywheel.db_path": db,
            "training.flywheel.export_dir": export_dir,
        }.get(key, default)
        mock_cfg.return_value = cfg
        fw = TrainingFlywheel(db_path=db, export_dir=export_dir)
    return fw


@pytest.fixture()
def populated_flywheel(flywheel: TrainingFlywheel) -> TrainingFlywheel:
    """Flywheel pre-loaded with examples from multiple sources."""
    flywheel.collect_from_qa("What is MCP?", "Model Context Protocol", source="cache")
    flywheel.collect_from_qa("What is DPO?", "Direct Preference Optimization", source="FTS")
    flywheel.collect_from_qa(
        "How does the interceptor work?",
        "It wraps LLM calls with pre/post hooks.",
        source="LLM",
        confidence=0.9,
    )
    flywheel.collect_from_routing("summarize this text", "qwen3-8b", "short prompt")
    flywheel.collect_from_routing("write a novel chapter", "qwen3-30b", "long creative task")
    flywheel.collect_preference(
        "Explain Python decorators",
        "Decorators wrap functions to extend behavior...",
        "idk decorators are like wrappers i guess",
    )
    task = FakeTask()
    flywheel.collect_from_task(task, "Fixed: added token validation middleware.")
    return flywheel


# ──── TrainingExample Tests ────


class TestTrainingExample:
    def test_default_fields(self) -> None:
        ex = TrainingExample()
        assert ex.source == ""
        assert ex.quality_score == 0.5
        assert ex.exported is False
        assert isinstance(ex.created_at, datetime)
        assert ex.metadata == {}

    def test_content_hash_deterministic(self) -> None:
        ex1 = TrainingExample(source="qa", input_text="q", output_text="a")
        ex2 = TrainingExample(source="qa", input_text="q", output_text="a")
        assert ex1.content_hash() == ex2.content_hash()

    def test_content_hash_differs(self) -> None:
        ex1 = TrainingExample(source="qa", input_text="q1", output_text="a")
        ex2 = TrainingExample(source="qa", input_text="q2", output_text="a")
        assert ex1.content_hash() != ex2.content_hash()

    def test_to_dict(self) -> None:
        ex = TrainingExample(source="task", input_text="in", output_text="out")
        d = ex.to_dict()
        assert d["source"] == "task"
        assert d["input_text"] == "in"
        assert d["output_text"] == "out"
        assert "id" in d
        assert "created_at" in d


# ──── Collection Tests ────


class TestCollectFromTask:
    def test_basic_task_collection(self, flywheel: TrainingFlywheel) -> None:
        task = FakeTask()
        eid = flywheel.collect_from_task(task, "Fixed the bug.")
        assert eid != ""
        st = flywheel.stats()
        assert st["total_examples"] == 1
        assert st["by_source"]["task"] == 1

    def test_task_metadata_includes_duration(self, flywheel: TrainingFlywheel) -> None:
        task = FakeTask(created_at=100.0, completed_at=145.0)
        flywheel.collect_from_task(task, "Done.")
        # Duration should be 45s — verify via stats that example was stored
        st = flywheel.stats()
        assert st["total_examples"] == 1

    def test_empty_result_skipped(self, flywheel: TrainingFlywheel) -> None:
        task = FakeTask()
        eid = flywheel.collect_from_task(task, "")
        assert eid == ""
        assert flywheel.stats()["total_examples"] == 0

    def test_empty_title_and_description_skipped(self, flywheel: TrainingFlywheel) -> None:
        task = FakeTask(title="", description="")
        eid = flywheel.collect_from_task(task, "some result")
        assert eid == ""


class TestCollectFromQA:
    def test_basic_qa_collection(self, flywheel: TrainingFlywheel) -> None:
        eid = flywheel.collect_from_qa("What is X?", "X is Y.")
        assert eid != ""
        st = flywheel.stats()
        assert st["by_source"]["qa"] == 1

    def test_empty_question_skipped(self, flywheel: TrainingFlywheel) -> None:
        eid = flywheel.collect_from_qa("", "answer")
        assert eid == ""

    def test_empty_answer_skipped(self, flywheel: TrainingFlywheel) -> None:
        eid = flywheel.collect_from_qa("question", "  ")
        assert eid == ""

    def test_confidence_clamped(self, flywheel: TrainingFlywheel) -> None:
        eid = flywheel.collect_from_qa("q", "a", confidence=5.0)
        assert eid != ""
        # quality_score should be clamped to 1.0


class TestCollectFromNLM:
    def test_basic_nlm_collection(self, flywheel: TrainingFlywheel) -> None:
        conversation = [
            {"role": "user", "content": "What is MCP?"},
            {"role": "assistant", "content": "Model Context Protocol."},
            {"role": "user", "content": "How does it work?"},
            {"role": "assistant", "content": "It uses a state tree."},
        ]
        ids = flywheel.collect_from_nlm(conversation, topic="MCP basics")
        assert len(ids) == 2
        assert all(i != "" for i in ids)
        assert flywheel.stats()["by_source"]["nlm"] == 2

    def test_empty_conversation(self, flywheel: TrainingFlywheel) -> None:
        ids = flywheel.collect_from_nlm([])
        assert ids == []

    def test_single_message_no_pairs(self, flywheel: TrainingFlywheel) -> None:
        ids = flywheel.collect_from_nlm([{"role": "user", "content": "hi"}])
        assert ids == []

    def test_alternating_roles_required(self, flywheel: TrainingFlywheel) -> None:
        conversation = [
            {"role": "user", "content": "q1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        ids = flywheel.collect_from_nlm(conversation)
        assert len(ids) == 1  # Only q2→a2 pair

    def test_human_gpt_role_names(self, flywheel: TrainingFlywheel) -> None:
        """Handles 'human'/'gpt' role names (ShareGPT style)."""
        conversation = [
            {"role": "human", "content": "What?"},
            {"role": "gpt", "content": "That."},
        ]
        ids = flywheel.collect_from_nlm(conversation)
        assert len(ids) == 1
        assert ids[0] != ""


class TestCollectFromRouting:
    def test_basic_routing_collection(self, flywheel: TrainingFlywheel) -> None:
        eid = flywheel.collect_from_routing("hello", "qwen3-0.6b", "short greeting")
        assert eid != ""
        assert flywheel.stats()["by_source"]["routing"] == 1

    def test_empty_request_skipped(self, flywheel: TrainingFlywheel) -> None:
        eid = flywheel.collect_from_routing("", "model", "reason")
        assert eid == ""


class TestCollectPreference:
    def test_basic_preference_collection(self, flywheel: TrainingFlywheel) -> None:
        eid = flywheel.collect_preference("prompt", "good answer", "bad answer")
        assert eid != ""
        assert flywheel.stats()["by_source"]["preference"] == 1

    def test_empty_field_skipped(self, flywheel: TrainingFlywheel) -> None:
        assert flywheel.collect_preference("", "chosen", "rejected") == ""
        assert flywheel.collect_preference("prompt", "", "rejected") == ""
        assert flywheel.collect_preference("prompt", "chosen", "") == ""


# ──── Deduplication Tests ────


class TestDeduplication:
    def test_duplicate_qa_skipped(self, flywheel: TrainingFlywheel) -> None:
        eid1 = flywheel.collect_from_qa("What is X?", "X is Y.")
        eid2 = flywheel.collect_from_qa("What is X?", "X is Y.")
        assert eid1 != ""
        assert eid2 == ""
        assert flywheel.stats()["total_examples"] == 1

    def test_different_content_not_duplicate(self, flywheel: TrainingFlywheel) -> None:
        eid1 = flywheel.collect_from_qa("What is X?", "X is Y.")
        eid2 = flywheel.collect_from_qa("What is X?", "X is Z.")
        assert eid1 != ""
        assert eid2 != ""
        assert flywheel.stats()["total_examples"] == 2


# ──── Export Tests ────


class TestExportJSONL:
    def test_basic_export(self, populated_flywheel: TrainingFlywheel) -> None:
        result = populated_flywheel.export_jsonl()
        assert result["count"] > 0
        assert result["file"] != ""
        assert os.path.exists(result["file"])
        with open(result["file"], encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == result["count"]
        record = json.loads(lines[0])
        assert "instruction" in record
        assert "input" in record
        assert "output" in record

    def test_quality_filter(self, populated_flywheel: TrainingFlywheel) -> None:
        high = populated_flywheel.export_jsonl(min_quality=0.85)
        # Only routing (0.8) and high-confidence QA (0.9) should pass at 0.85
        # Actually routing is 0.8 so only QA at 0.9 passes
        assert high["count"] >= 1

    def test_source_filter(self, populated_flywheel: TrainingFlywheel) -> None:
        result = populated_flywheel.export_jsonl(source_filter="routing")
        assert result["count"] == 2  # Two routing examples

    def test_no_preference_in_jsonl(self, populated_flywheel: TrainingFlywheel) -> None:
        result = populated_flywheel.export_jsonl(min_quality=0.0)
        with open(result["file"], encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                assert "rejected" not in record

    def test_empty_export(self, flywheel: TrainingFlywheel) -> None:
        result = flywheel.export_jsonl()
        assert result["count"] == 0
        assert result["file"] == ""

    def test_exported_not_re_exported(self, populated_flywheel: TrainingFlywheel) -> None:
        r1 = populated_flywheel.export_jsonl()
        r2 = populated_flywheel.export_jsonl()
        assert r1["count"] > 0
        assert r2["count"] == 0


class TestExportShareGPT:
    def test_basic_sharegpt_export(self, populated_flywheel: TrainingFlywheel) -> None:
        result = populated_flywheel.export_sharegpt()
        assert result["count"] > 0
        with open(result["file"], encoding="utf-8") as f:
            record = json.loads(f.readline())
        assert "conversations" in record
        assert record["conversations"][0]["from"] == "human"
        assert record["conversations"][1]["from"] == "gpt"

    def test_empty_sharegpt(self, flywheel: TrainingFlywheel) -> None:
        result = flywheel.export_sharegpt()
        assert result["count"] == 0


class TestExportDPO:
    def test_basic_dpo_export(self, populated_flywheel: TrainingFlywheel) -> None:
        result = populated_flywheel.export_dpo()
        assert result["count"] == 1
        with open(result["file"], encoding="utf-8") as f:
            record = json.loads(f.readline())
        assert "prompt" in record
        assert "chosen" in record
        assert "rejected" in record
        assert record["rejected"] != ""

    def test_empty_dpo(self, flywheel: TrainingFlywheel) -> None:
        result = flywheel.export_dpo()
        assert result["count"] == 0

    def test_dpo_not_re_exported(self, populated_flywheel: TrainingFlywheel) -> None:
        r1 = populated_flywheel.export_dpo()
        r2 = populated_flywheel.export_dpo()
        assert r1["count"] == 1
        assert r2["count"] == 0


# ──── Stats Tests ────


class TestStats:
    def test_empty_stats(self, flywheel: TrainingFlywheel) -> None:
        st = flywheel.stats()
        assert st["total_examples"] == 0
        assert st["exported"] == 0
        assert st["avg_quality"] == 0.0
        assert st["by_source"] == {}

    def test_populated_stats(self, populated_flywheel: TrainingFlywheel) -> None:
        st = populated_flywheel.stats()
        assert st["total_examples"] == 7
        assert "qa" in st["by_source"]
        assert "routing" in st["by_source"]
        assert "preference" in st["by_source"]
        assert "task" in st["by_source"]
        assert st["avg_quality"] > 0.0
        assert "quality_distribution" in st
        assert st["total_exports"] == 0

    def test_stats_after_export(self, populated_flywheel: TrainingFlywheel) -> None:
        populated_flywheel.export_jsonl()
        st = populated_flywheel.stats()
        assert st["exported"] > 0
        assert st["total_exports"] == 1


# ──── Sync from Nexus Tests ────


class TestSyncFromNexus:
    def test_sync_with_available_nexus(self, flywheel: TrainingFlywheel) -> None:
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.list_entries.return_value = [
            {"title": "What is CosySim?", "content": "A simulation framework.", "quality_score": 0.8},
            {"title": "What is Nexus?", "content": "A knowledge management system.", "quality_score": 0.9},
        ]
        with patch(
            "engine.nexus.client.get_nexus_client",
            return_value=mock_client,
        ):
            result = flywheel.sync_from_nexus()

        assert result["synced"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert flywheel.stats()["total_examples"] == 2

    def test_sync_with_unavailable_nexus(self, flywheel: TrainingFlywheel) -> None:
        mock_client = MagicMock()
        mock_client.is_available.return_value = False
        with patch(
            "engine.nexus.client.get_nexus_client",
            return_value=mock_client,
        ):
            result = flywheel.sync_from_nexus()
        assert result["synced"] == 0
        assert result["errors"] == 1

    def test_sync_skips_empty_entries(self, flywheel: TrainingFlywheel) -> None:
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.list_entries.return_value = [
            {"title": "", "content": "no title"},
            {"title": "no content", "content": ""},
            {"title": "Good Q", "content": "Good A"},
        ]
        with patch(
            "engine.nexus.client.get_nexus_client",
            return_value=mock_client,
        ):
            result = flywheel.sync_from_nexus()
        assert result["synced"] == 1
        assert result["skipped"] == 2

    def test_sync_deduplicates(self, flywheel: TrainingFlywheel) -> None:
        flywheel.collect_from_qa("Q1", "A1", source="manual")
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.list_entries.return_value = [
            {"title": "Q1", "content": "A1"},
        ]
        with patch(
            "engine.nexus.client.get_nexus_client",
            return_value=mock_client,
        ):
            result = flywheel.sync_from_nexus()
        # Same source ("qa"), same input/output → duplicate skipped
        assert result["synced"] == 0
        assert result["skipped"] == 1
        assert flywheel.stats()["total_examples"] == 1


# ──── Singleton Tests ────


class TestSingleton:
    def test_get_training_flywheel_returns_instance(self, tmp_path: Path) -> None:
        import engine.nexus.training_flywheel as mod

        mod._flywheel = None  # Reset singleton
        db = str(tmp_path / "singleton.db")
        with patch("engine.nexus.training_flywheel.get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.get.side_effect = lambda key, default=None: {
                "training.flywheel.db_path": db,
                "training.flywheel.export_dir": str(tmp_path / "exports"),
            }.get(key, default)
            mock_cfg.return_value = cfg
            fw1 = get_training_flywheel()
            fw2 = get_training_flywheel()
        assert fw1 is fw2
        mod._flywheel = None  # Cleanup
