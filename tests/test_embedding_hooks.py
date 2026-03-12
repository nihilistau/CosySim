"""Tests for engine.nexus.embedding_hooks."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Patch paths — lazy imports inside try blocks need source-module patches
_VS_PATCH = "engine.nexus.vector_store.get_vector_store"
_NC_PATCH = "engine.nexus.client.get_nexus_client"


# ──── Content-Type Mapping ────


class TestContentTypeMapping:
    """Tests for content_type_to_collection()."""

    def test_note_maps_to_knowledge(self):
        from engine.nexus.embedding_hooks import content_type_to_collection
        assert content_type_to_collection("note") == "knowledge"

    def test_code_maps_to_code(self):
        from engine.nexus.embedding_hooks import content_type_to_collection
        assert content_type_to_collection("code") == "code"

    def test_prompt_maps_to_prompt(self):
        from engine.nexus.embedding_hooks import content_type_to_collection
        assert content_type_to_collection("prompt") == "prompt"

    def test_document_maps_to_document(self):
        from engine.nexus.embedding_hooks import content_type_to_collection
        assert content_type_to_collection("document") == "document"

    def test_memory_maps_to_memory(self):
        from engine.nexus.embedding_hooks import content_type_to_collection
        assert content_type_to_collection("memory") == "memory"

    def test_research_maps_to_research(self):
        from engine.nexus.embedding_hooks import content_type_to_collection
        assert content_type_to_collection("research") == "research"

    def test_news_maps_to_news(self):
        from engine.nexus.embedding_hooks import content_type_to_collection
        assert content_type_to_collection("news") == "news"

    def test_history_maps_to_document(self):
        from engine.nexus.embedding_hooks import content_type_to_collection
        assert content_type_to_collection("history") == "document"

    def test_plan_maps_to_document(self):
        from engine.nexus.embedding_hooks import content_type_to_collection
        assert content_type_to_collection("plan") == "document"

    def test_transcript_maps_to_knowledge(self):
        from engine.nexus.embedding_hooks import content_type_to_collection
        assert content_type_to_collection("transcript") == "knowledge"

    def test_unknown_defaults_to_knowledge(self):
        from engine.nexus.embedding_hooks import content_type_to_collection
        assert content_type_to_collection("alien_type") == "knowledge"


# ──── Auto-Embed Entry ────


class TestAutoEmbedEntry:
    """Tests for auto_embed_entry()."""

    @patch(_VS_PATCH)
    def test_embeds_entry_into_correct_collection(self, mock_get_store):
        from engine.nexus.embedding_hooks import auto_embed_entry

        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        result = auto_embed_entry(
            entry_id="ent-1",
            text="Architecture decision about MCP",
            content_type="note",
            category="architecture",
            tags=["mcp", "decision"],
        )

        assert result is True
        mock_store.add.assert_called_once()
        call_kwargs = mock_store.add.call_args
        assert call_kwargs[1]["entry_id"] == "ent-1"
        assert call_kwargs[1]["collection"] == "knowledge"
        assert call_kwargs[1]["metadata"]["category"] == "architecture"
        assert call_kwargs[1]["metadata"]["tags"] == "mcp,decision"

    @patch(_VS_PATCH)
    def test_code_type_uses_code_collection(self, mock_get_store):
        from engine.nexus.embedding_hooks import auto_embed_entry

        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        auto_embed_entry("ent-2", "def hello(): pass", content_type="code")

        call_kwargs = mock_store.add.call_args[1]
        assert call_kwargs["collection"] == "code"

    def test_returns_false_for_empty_id(self):
        from engine.nexus.embedding_hooks import auto_embed_entry
        assert auto_embed_entry("", "some text") is False

    def test_returns_false_for_empty_text(self):
        from engine.nexus.embedding_hooks import auto_embed_entry
        assert auto_embed_entry("ent-3", "") is False

    @patch(_VS_PATCH)
    def test_returns_false_on_exception(self, mock_get_store):
        from engine.nexus.embedding_hooks import auto_embed_entry

        mock_get_store.side_effect = RuntimeError("ChromaDB down")

        result = auto_embed_entry("ent-4", "text")
        assert result is False

    @patch(_VS_PATCH)
    def test_handles_no_tags(self, mock_get_store):
        from engine.nexus.embedding_hooks import auto_embed_entry

        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        auto_embed_entry("ent-5", "content", tags=None)

        metadata = mock_store.add.call_args[1]["metadata"]
        assert "tags" not in metadata


# ──── Auto-Embed QA ────


class TestAutoEmbedQA:
    """Tests for auto_embed_qa()."""

    @patch(_VS_PATCH)
    def test_embeds_qa_into_qa_collection(self, mock_get_store):
        from engine.nexus.embedding_hooks import auto_embed_qa

        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        result = auto_embed_qa(
            qa_id="qa-1",
            question="How does MCP work?",
            answer="MCP is a framework for state management.",
            category="architecture",
        )

        assert result is True
        mock_store.add.assert_called_once()
        call_kwargs = mock_store.add.call_args[1]
        assert call_kwargs["entry_id"] == "qa-1"
        assert call_kwargs["collection"] == "qa"
        assert "Q: How does MCP work?" in call_kwargs["text"]
        assert "A: MCP is a framework" in call_kwargs["text"]

    @patch(_VS_PATCH)
    def test_handles_empty_answer(self, mock_get_store):
        from engine.nexus.embedding_hooks import auto_embed_qa

        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        auto_embed_qa("qa-2", "What is X?", "")

        text = mock_store.add.call_args[1]["text"]
        assert text == "What is X?"

    def test_returns_false_for_empty_id(self):
        from engine.nexus.embedding_hooks import auto_embed_qa
        assert auto_embed_qa("", "question", "answer") is False

    def test_returns_false_for_empty_question(self):
        from engine.nexus.embedding_hooks import auto_embed_qa
        assert auto_embed_qa("qa-3", "", "answer") is False

    @patch(_VS_PATCH)
    def test_returns_false_on_exception(self, mock_get_store):
        from engine.nexus.embedding_hooks import auto_embed_qa

        mock_get_store.side_effect = RuntimeError("DB error")
        assert auto_embed_qa("qa-4", "question", "answer") is False


# ──── Batch Embedding ────


class TestBatchEmbed:
    """Tests for batch_embed_nexus_entries()."""

    @patch(_VS_PATCH)
    @patch(_NC_PATCH)
    def test_batch_embeds_new_entries(self, mock_get_client, mock_get_store):
        from engine.nexus.embedding_hooks import batch_embed_nexus_entries

        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"id": "e1", "content": "Entry 1", "content_type": "note", "category": "arch"},
            {"id": "e2", "content": "Entry 2", "content_type": "code", "category": "dev"},
        ]
        mock_get_client.return_value = mock_client

        mock_store = MagicMock()
        mock_store.has.return_value = False
        mock_store.add_batch.return_value = 2
        mock_get_store.return_value = mock_store

        result = batch_embed_nexus_entries(limit=100)

        assert result["total"] == 2
        assert result["embedded"] >= 2
        assert result["skipped"] == 0

    @patch(_VS_PATCH)
    @patch(_NC_PATCH)
    def test_batch_skips_already_embedded(self, mock_get_client, mock_get_store):
        from engine.nexus.embedding_hooks import batch_embed_nexus_entries

        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"id": "e1", "content": "Already embedded", "content_type": "note"},
        ]
        mock_get_client.return_value = mock_client

        mock_store = MagicMock()
        mock_store.has.return_value = True
        mock_get_store.return_value = mock_store

        result = batch_embed_nexus_entries()

        assert result["skipped"] == 1
        assert result["embedded"] == 0
        mock_store.add_batch.assert_not_called()

    @patch(_VS_PATCH)
    @patch(_NC_PATCH)
    def test_batch_handles_empty_content(self, mock_get_client, mock_get_store):
        from engine.nexus.embedding_hooks import batch_embed_nexus_entries

        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"id": "e1", "content": "", "content_type": "note", "title": ""},
        ]
        mock_get_client.return_value = mock_client

        mock_store = MagicMock()
        mock_store.has.return_value = False
        mock_get_store.return_value = mock_store

        result = batch_embed_nexus_entries()

        assert result["skipped"] == 1

    @patch(_NC_PATCH)
    def test_batch_handles_client_failure(self, mock_get_client):
        from engine.nexus.embedding_hooks import batch_embed_nexus_entries

        mock_get_client.side_effect = RuntimeError("Nexus offline")

        result = batch_embed_nexus_entries()
        assert "error" in result


class TestBatchEmbedQA:
    """Tests for batch_embed_qa_entries()."""

    @patch(_VS_PATCH)
    @patch(_NC_PATCH)
    def test_batch_embeds_qa_pairs(self, mock_get_client, mock_get_store):
        from engine.nexus.embedding_hooks import batch_embed_qa_entries

        mock_client = MagicMock()
        mock_client.list_qa.return_value = [
            {"id": "qa1", "question": "What is X?", "answer": "X is Y.", "category": "dev"},
            {"id": "qa2", "question": "How does Z?", "answer": "Z does W.", "category": "arch"},
        ]
        mock_get_client.return_value = mock_client

        mock_store = MagicMock()
        mock_store.has.return_value = False
        mock_store.add_batch.return_value = 2
        mock_get_store.return_value = mock_store

        result = batch_embed_qa_entries(limit=100)

        assert result["total"] == 2
        assert result["embedded"] == 2
        mock_store.add_batch.assert_called_once()

    @patch(_VS_PATCH)
    @patch(_NC_PATCH)
    def test_batch_qa_skips_existing(self, mock_get_client, mock_get_store):
        from engine.nexus.embedding_hooks import batch_embed_qa_entries

        mock_client = MagicMock()
        mock_client.list_qa.return_value = [
            {"id": "qa1", "question": "Exists?", "answer": "Yes."},
        ]
        mock_get_client.return_value = mock_client

        mock_store = MagicMock()
        mock_store.has.return_value = True
        mock_get_store.return_value = mock_store

        result = batch_embed_qa_entries()

        assert result["skipped"] == 1
        assert result["embedded"] == 0


# ──── Scheduler Callback ────


class TestSchedulerCallback:
    """Tests for the auto-embedding scheduler callback."""

    @patch("engine.nexus.embedding_hooks.batch_embed_qa_entries")
    @patch("engine.nexus.embedding_hooks.batch_embed_nexus_entries")
    def test_auto_embedding_callback(self, mock_batch_entries, mock_batch_qa):
        from engine.nexus.scheduler_daemon import _auto_embedding_callback

        mock_batch_entries.return_value = {"embedded": 10, "skipped": 5}
        mock_batch_qa.return_value = {"embedded": 3, "skipped": 2}

        result = _auto_embedding_callback()

        assert result["entries_embedded"] == 10
        assert result["entries_skipped"] == 5
        assert result["qa_embedded"] == 3
        assert result["qa_skipped"] == 2

    def test_scheduler_task_registered(self):
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        daemon = get_scheduler_daemon()
        task_ids = {t["id"] for t in daemon.list_tasks()}
        assert "auto-embedding" in task_ids

    def test_scheduler_task_count_is_57(self):
        """Guard total task count — update when adding new tasks."""
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        daemon = get_scheduler_daemon()
        assert len(daemon.list_tasks()) == 57
