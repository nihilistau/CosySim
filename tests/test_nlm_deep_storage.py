"""Tests for NLM Deep Storage — notebook archival into Nexus."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def deep_storage(tmp_path):
    """Create a NLMDeepStorage with temp archive directory."""
    with patch("engine.nexus.nlm_deep_storage.get_config") as mock_cfg:
        mock_cfg.return_value.get.return_value = str(tmp_path / "archives")
        from engine.nexus.nlm_deep_storage import NLMDeepStorage
        ds = NLMDeepStorage(archive_dir=str(tmp_path / "archives"))
    return ds


@pytest.fixture()
def mock_nlm_engine():
    """Mock NLM engine with notebook data."""
    engine = MagicMock()
    engine.list_notebooks.return_value = [
        {"id": "nb-001", "name": "Architecture Research"},
        {"id": "nb-002", "name": "MCP Deep Dive"},
    ]
    engine.get_notebook.return_value = {
        "id": "nb-001",
        "name": "Architecture Research",
        "sources": [
            {"title": "ARCHITECTURE.md", "source_type": "text", "word_count": 500},
            {"title": "MCP docs", "source_type": "url", "url": "https://example.com"},
        ],
        "conversations": [
            "Q: How does MCP work?\nA: MCP is a framework for...",
            "Q: What about state?\nA: State is managed via...",
        ],
        "notes": ["Key insight: interceptors are chainable"],
    }
    return engine


@pytest.fixture()
def mock_nexus_client():
    """Mock Nexus client that tracks add_entry calls."""
    client = MagicMock()
    call_counter = {"n": 0}

    def mock_add_entry(**kwargs):
        call_counter["n"] += 1
        return f"entry-{call_counter['n']}"

    client.add_entry.side_effect = mock_add_entry
    client.search.return_value = []
    return client


# ── NLMDeepStorage Unit Tests ───────────────────────────────────────


class TestDeepStorageInit:
    """Test initialization and index management."""

    def test_creates_archive_dir(self, tmp_path):
        """Archive directory is created on init."""
        with patch("engine.nexus.nlm_deep_storage.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = str(tmp_path / "new_archives")
            from engine.nexus.nlm_deep_storage import NLMDeepStorage
            ds = NLMDeepStorage(archive_dir=str(tmp_path / "new_archives"))
        assert (tmp_path / "new_archives").exists()

    def test_empty_index_on_fresh_init(self, deep_storage):
        """Fresh instance has empty archive index."""
        assert deep_storage.list_archives() == []

    def test_stats_on_empty(self, deep_storage):
        """Stats returns zeros on empty storage."""
        stats = deep_storage.stats()
        assert stats["total_archives"] == 0
        assert stats["total_entries_stored"] == 0

    def test_index_persists(self, tmp_path):
        """Archive index persists across instances."""
        archive_dir = str(tmp_path / "persist_test")
        with patch("engine.nexus.nlm_deep_storage.get_config") as mock_cfg:
            mock_cfg.return_value.get.return_value = archive_dir
            from engine.nexus.nlm_deep_storage import NLMDeepStorage

            ds1 = NLMDeepStorage(archive_dir=archive_dir)
            ds1._index["nb-test"] = {
                "archive_id": "archive-test",
                "notebook_name": "Test",
                "chain_id": "chain-abc",
                "archived_at": "2025-01-01T00:00:00",
                "master_entry_id": "entry-1",
                "stats": {"entries": 1},
            }
            ds1._save_index()

            ds2 = NLMDeepStorage(archive_dir=archive_dir)
            assert "nb-test" in ds2._index
            assert ds2._index["nb-test"]["notebook_name"] == "Test"


class TestArchiveNotebook:
    """Test single notebook archival."""

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.nexus.nlm_engine.get_nlm_engine")
    def test_archive_stores_metadata(self, mock_engine_fn, mock_client_fn,
                                     deep_storage, mock_nlm_engine, mock_nexus_client):
        """Archiving stores notebook metadata in Nexus."""
        mock_engine_fn.return_value = mock_nlm_engine
        mock_client_fn.return_value = mock_nexus_client

        result = deep_storage.archive_notebook("nb-001")
        assert result["entries_stored"] >= 1
        assert result["notebook_id"] == "nb-001"
        assert "archive_id" in result
        assert "chain_id" in result

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.nexus.nlm_engine.get_nlm_engine")
    def test_archive_stores_sources(self, mock_engine_fn, mock_client_fn,
                                    deep_storage, mock_nlm_engine, mock_nexus_client):
        """Archiving stores each source as a separate entry."""
        mock_engine_fn.return_value = mock_nlm_engine
        mock_client_fn.return_value = mock_nexus_client

        result = deep_storage.archive_notebook("nb-001")
        assert result["sources_stored"] == 2

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.nexus.nlm_engine.get_nlm_engine")
    def test_archive_stores_conversations(self, mock_engine_fn, mock_client_fn,
                                          deep_storage, mock_nlm_engine, mock_nexus_client):
        """Archiving stores each conversation with chain IDs."""
        mock_engine_fn.return_value = mock_nlm_engine
        mock_client_fn.return_value = mock_nexus_client

        result = deep_storage.archive_notebook("nb-001")
        assert result["conversations_stored"] == 2

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.nexus.nlm_engine.get_nlm_engine")
    def test_archive_stores_notes(self, mock_engine_fn, mock_client_fn,
                                  deep_storage, mock_nlm_engine, mock_nexus_client):
        """Archiving stores notes."""
        mock_engine_fn.return_value = mock_nlm_engine
        mock_client_fn.return_value = mock_nexus_client

        result = deep_storage.archive_notebook("nb-001")
        assert result["notes_stored"] == 1

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.nexus.nlm_engine.get_nlm_engine")
    def test_archive_updates_local_index(self, mock_engine_fn, mock_client_fn,
                                         deep_storage, mock_nlm_engine, mock_nexus_client):
        """Archiving updates the local archive index."""
        mock_engine_fn.return_value = mock_nlm_engine
        mock_client_fn.return_value = mock_nexus_client

        deep_storage.archive_notebook("nb-001")
        archives = deep_storage.list_archives()
        assert len(archives) == 1
        assert archives[0]["notebook_id"] == "nb-001"
        assert archives[0]["notebook_name"] == "Architecture Research"

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.nexus.nlm_engine.get_nlm_engine")
    def test_archive_handles_failed_notebook_fetch(self, mock_engine_fn, mock_client_fn,
                                                    deep_storage):
        """Archiving handles notebook fetch failures gracefully."""
        engine = MagicMock()
        engine.get_notebook.return_value = {"error": "not found"}
        mock_engine_fn.return_value = engine

        result = deep_storage.archive_notebook("nb-missing")
        assert len(result["errors"]) > 0

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.nexus.nlm_engine.get_nlm_engine")
    def test_archive_records_duration(self, mock_engine_fn, mock_client_fn,
                                      deep_storage, mock_nlm_engine, mock_nexus_client):
        """Archiving records operation duration."""
        mock_engine_fn.return_value = mock_nlm_engine
        mock_client_fn.return_value = mock_nexus_client

        result = deep_storage.archive_notebook("nb-001")
        assert "duration_seconds" in result
        assert result["duration_seconds"] >= 0


class TestArchiveAll:
    """Test batch archival of all notebooks."""

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.nexus.nlm_engine.get_nlm_engine")
    def test_archive_all_processes_all_notebooks(self, mock_engine_fn, mock_client_fn,
                                                  deep_storage, mock_nlm_engine, mock_nexus_client):
        """archive_all processes every notebook from the engine."""
        mock_engine_fn.return_value = mock_nlm_engine
        mock_client_fn.return_value = mock_nexus_client

        result = deep_storage.archive_all()
        assert result["total_notebooks"] == 2
        assert result["successful"] == 2
        assert len(result["notebooks"]) == 2

    @patch("engine.nexus.client.get_nexus_client")
    @patch("engine.nexus.nlm_engine.get_nlm_engine")
    def test_archive_all_handles_failures(self, mock_engine_fn, mock_client_fn,
                                           deep_storage):
        """archive_all counts failures without crashing."""
        engine = MagicMock()
        engine.list_notebooks.return_value = [
            {"id": "nb-good", "name": "Good"},
            {"id": "nb-bad", "name": "Bad"},
        ]
        engine.get_notebook.side_effect = [
            {"id": "nb-good", "name": "Good", "sources": [], "conversations": [], "notes": []},
            Exception("NLM unavailable"),
        ]
        mock_engine_fn.return_value = engine

        client = MagicMock()
        client.add_entry.return_value = "entry-1"
        mock_client_fn.return_value = client

        result = deep_storage.archive_all()
        assert result["successful"] >= 1
        assert result["failed"] >= 1


class TestStoreConversation:
    """Test conversation storage with chain IDs."""

    @patch("engine.nexus.client.get_nexus_client")
    def test_store_generates_chain_id(self, mock_client_fn, deep_storage):
        """Storing a conversation generates a unique chain ID."""
        client = MagicMock()
        client.add_entry.return_value = "entry-conv-1"
        mock_client_fn.return_value = client

        messages = [
            {"role": "user", "content": "How does MCP work?"},
            {"role": "assistant", "content": "MCP is a state tree framework..."},
        ]
        result = deep_storage.store_conversation("nb-001", messages, topic="mcp")
        assert result["chain_id"].startswith("chain-")
        assert result["message_count"] == 2
        assert result["entry_id"] == "entry-conv-1"

    @patch("engine.nexus.client.get_nexus_client")
    def test_store_with_parent_chain(self, mock_client_fn, deep_storage):
        """Conversation can be linked to a parent chain."""
        client = MagicMock()
        client.add_entry.return_value = "entry-conv-2"
        mock_client_fn.return_value = client

        messages = [{"role": "user", "content": "Follow up"}]
        result = deep_storage.store_conversation(
            "nb-001", messages, parent_chain_id="chain-parent-123",
        )
        assert result["parent_chain_id"] == "chain-parent-123"

    @patch("engine.nexus.client.get_nexus_client")
    def test_store_formats_messages(self, mock_client_fn, deep_storage):
        """Conversation content is formatted with role labels."""
        client = MagicMock()
        client.add_entry.return_value = "entry-1"
        mock_client_fn.return_value = client

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        deep_storage.store_conversation("nb-001", messages)

        call_kwargs = client.add_entry.call_args
        content = call_kwargs.kwargs.get("content", "") or call_kwargs[1].get("content", "")
        assert "**USER:**" in content
        assert "**ASSISTANT:**" in content


class TestRetrieve:
    """Test archive retrieval."""

    @patch("engine.nexus.client.get_nexus_client")
    def test_retrieve_unknown_notebook(self, mock_client_fn, deep_storage):
        """Retrieving unknown notebook returns error."""
        result = deep_storage.retrieve("nb-unknown")
        assert "error" in result

    @patch("engine.nexus.client.get_nexus_client")
    def test_retrieve_categorizes_entries(self, mock_client_fn, deep_storage):
        """Retrieved entries are categorized by type."""
        from engine.nexus.nlm_deep_storage import (
            CONTENT_TYPE_ARCHIVE, CONTENT_TYPE_CONVERSATION, CONTENT_TYPE_SOURCE,
        )

        deep_storage._index["nb-001"] = {
            "archive_id": "archive-test",
            "chain_id": "chain-test",
            "notebook_name": "Test",
        }

        client = MagicMock()
        client.search.return_value = [
            {"content_type": CONTENT_TYPE_ARCHIVE, "title": "meta"},
            {"content_type": CONTENT_TYPE_SOURCE, "title": "src"},
            {"content_type": CONTENT_TYPE_CONVERSATION, "title": "conv"},
            {"content_type": "note", "title": "[Note] Test #1"},
        ]
        mock_client_fn.return_value = client

        result = deep_storage.retrieve("nb-001")
        assert len(result["metadata"]) == 1
        assert len(result["sources"]) == 1
        assert len(result["conversations"]) == 1
        assert len(result["notes"]) == 1


class TestSearchAndChain:
    """Test search and chain retrieval."""

    @patch("engine.nexus.client.get_nexus_client")
    def test_search_conversations_filters_by_type(self, mock_client_fn, deep_storage):
        """search_conversations only returns conversation entries."""
        from engine.nexus.nlm_deep_storage import CONTENT_TYPE_CONVERSATION

        client = MagicMock()
        client.search.return_value = [
            {"content_type": CONTENT_TYPE_CONVERSATION, "title": "conv1"},
            {"content_type": "note", "title": "unrelated note"},
            {"content_type": CONTENT_TYPE_CONVERSATION, "title": "conv2"},
        ]
        mock_client_fn.return_value = client

        results = deep_storage.search_conversations("MCP")
        assert len(results) == 2

    @patch("engine.nexus.client.get_nexus_client")
    def test_get_chain_returns_ordered(self, mock_client_fn, deep_storage):
        """get_chain returns entries sorted by creation time."""
        client = MagicMock()
        client.search.return_value = [
            {"tags": ["chain-abc"], "created_at": "2025-01-02"},
            {"tags": ["chain-abc"], "created_at": "2025-01-01"},
            {"tags": ["other"], "created_at": "2025-01-03"},
        ]
        mock_client_fn.return_value = client

        chain = deep_storage.get_chain("chain-abc")
        assert len(chain) == 2
        assert chain[0]["created_at"] < chain[1]["created_at"]


class TestDeleteArchive:
    """Test archive deletion."""

    def test_delete_existing_archive(self, deep_storage):
        """Deleting an existing archive removes it from index."""
        deep_storage._index["nb-001"] = {
            "archive_id": "archive-test",
            "notebook_name": "Test",
        }
        result = deep_storage.delete_archive("nb-001")
        assert result["deleted"] is True
        assert "nb-001" not in deep_storage._index

    def test_delete_nonexistent_archive(self, deep_storage):
        """Deleting a non-existent archive returns not found."""
        result = deep_storage.delete_archive("nb-missing")
        assert result["deleted"] is False


class TestSingleton:
    """Test singleton access."""

    def test_singleton_returns_same_instance(self):
        """get_deep_storage returns same instance."""
        import engine.nexus.nlm_deep_storage as mod
        old = mod._instance
        mod._instance = None
        try:
            with patch.object(mod, "get_config") as mock_cfg:
                mock_cfg.return_value.get.return_value = "data/nlm_archives"
                ds1 = mod.get_deep_storage()
                ds2 = mod.get_deep_storage()
                assert ds1 is ds2
        finally:
            mod._instance = old


# ── Deep Storage Skills Tests ────────────────────────────────────────


class TestDeepStorageSkills:
    """Test autonomy skills for deep storage."""

    def test_skills_importable(self):
        """Deep storage skills can be imported."""
        from engine.skills.builtin.autonomy_skills import (
            deep_storage_archive,
            deep_storage_archive_all,
            deep_storage_list,
            deep_storage_retrieve,
            deep_storage_search_conversations,
            deep_storage_get_chain,
            deep_storage_store_conversation,
            deep_storage_stats,
            deep_storage_from_har,
        )
        assert callable(deep_storage_archive)
        assert callable(deep_storage_archive_all)
        assert callable(deep_storage_list)

    @patch("engine.nexus.nlm_deep_storage.get_deep_storage")
    def test_deep_storage_stats_skill(self, mock_ds):
        """Stats skill returns JSON."""
        from engine.skills.builtin.autonomy_skills import deep_storage_stats
        mock_ds.return_value.stats.return_value = {"total_archives": 3}
        result = json.loads(deep_storage_stats())
        assert result["total_archives"] == 3

    @patch("engine.nexus.nlm_deep_storage.get_deep_storage")
    def test_deep_storage_list_skill(self, mock_ds):
        """List skill returns JSON array."""
        from engine.skills.builtin.autonomy_skills import deep_storage_list
        mock_ds.return_value.list_archives.return_value = [
            {"notebook_id": "nb-1", "notebook_name": "Test"}
        ]
        result = json.loads(deep_storage_list())
        assert len(result) == 1


# ── MCP Tools Tests ──────────────────────────────────────────────────


class TestDeepStorageMCPTools:
    """Test deep storage MCP tools in devtools_server."""

    def test_mcp_tools_registered(self):
        """Deep storage MCP tools exist in devtools_server."""
        import engine.mcp.devtools_server as ds
        source = open(ds.__file__, encoding="utf-8").read()
        tools = [
            "deep_storage_archive",
            "deep_storage_archive_all",
            "deep_storage_from_har",
            "deep_storage_retrieve",
            "deep_storage_list",
            "deep_storage_search",
            "deep_storage_chain",
            "deep_storage_stats",
        ]
        for tool in tools:
            assert f"def {tool}" in source, f"MCP tool {tool} not found"
