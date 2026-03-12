"""Tests for engine.nexus.nlm_notebook_manager."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──── Helpers ────

def _make_manager(tmp_path, notebooks=None):
    """Build a NLMNotebookManager with patched dependencies and temp storage."""
    meta_path = tmp_path / "nlm_notebooks.json"
    if notebooks:
        meta_path.write_text(json.dumps(notebooks), encoding="utf-8")

    with patch("engine.nexus.nlm_notebook_manager.get_config") as mock_cfg, \
         patch("engine.nexus.nlm_notebook_manager.get_nlm_engine") as mock_eng_fn:
        cfg = MagicMock()
        cfg.get = MagicMock(return_value=str(meta_path))
        mock_cfg.return_value = cfg

        engine = MagicMock()
        engine.delete_notebook.return_value = {"ok": True}
        engine.add_source.return_value = {"ok": True}
        mock_eng_fn.return_value = engine

        from engine.nexus.nlm_notebook_manager import NLMNotebookManager
        mgr = NLMNotebookManager(metadata_path=str(meta_path))

    # Factory mock: get_or_create returns a notebook ID string
    factory = MagicMock()
    factory.get_or_create.return_value = "nb-123"

    return mgr, engine, meta_path, factory


# ──── Tests ────

class TestEnsureNotebook:
    """Tests for ensure_notebook."""

    def test_creates_when_missing(self, tmp_path):
        """ensure_notebook creates a new notebook if slot doesn't exist."""
        mgr, engine, meta_path, factory = _make_manager(tmp_path)

        with patch("engine.nexus.nlm_notebook_factory.get_notebook_factory", return_value=factory):
            result = mgr.ensure_notebook("cosysim-architecture")

        assert result["slot_name"] == "cosysim-architecture"
        assert result["notebook_id"] == "nb-123"
        assert result["source_count"] == 0
        factory.get_or_create.assert_called_once()

    def test_returns_existing(self, tmp_path):
        """ensure_notebook returns existing entry without calling factory."""
        existing = {
            "cosysim-architecture": {
                "slot_name": "cosysim-architecture",
                "notebook_id": "nb-existing",
                "created_at": "2024-01-01T00:00:00+00:00",
                "source_count": 5,
                "last_seeded": None,
                "last_asked": None,
            }
        }
        mgr, engine, _, factory = _make_manager(tmp_path, notebooks=existing)

        result = mgr.ensure_notebook("cosysim-architecture")

        assert result["notebook_id"] == "nb-existing"
        factory.get_or_create.assert_not_called()

    def test_returns_error_on_create_failure(self, tmp_path):
        """ensure_notebook returns error dict when factory fails to create."""
        mgr, engine, _, factory = _make_manager(tmp_path)
        factory.get_or_create.return_value = None

        with patch("engine.nexus.nlm_notebook_factory.get_notebook_factory", return_value=factory):
            result = mgr.ensure_notebook("bad-slot")

        assert "error" in result

    def test_persists_metadata(self, tmp_path):
        """ensure_notebook saves metadata to disk."""
        mgr, engine, meta_path, factory = _make_manager(tmp_path)

        with patch("engine.nexus.nlm_notebook_factory.get_notebook_factory", return_value=factory):
            mgr.ensure_notebook("cosysim-codebase")

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "cosysim-codebase" in data
        assert data["cosysim-codebase"]["notebook_id"] == "nb-123"


class TestSeedNotebook:
    """Tests for seed_notebook and seed_from_docs."""

    def test_seed_notebook_adds_sources(self, tmp_path):
        """seed_notebook reads files and adds them as text sources."""
        src_file = tmp_path / "test_source.md"
        src_file.write_text("# Hello", encoding="utf-8")

        mgr, engine, _, factory = _make_manager(tmp_path)

        with patch("engine.nexus.nlm_notebook_factory.get_notebook_factory", return_value=factory), \
             patch("engine.nexus.nlm_notebook_manager.get_nlm_engine", return_value=engine):
            mgr.ensure_notebook("test-slot")
            result = mgr.seed_notebook("test-slot", [str(src_file)])

        assert result["added"] == 1
        assert result["errors"] == []
        engine.add_source.assert_called_once()
        call_args = engine.add_source.call_args
        assert call_args[0][0] == "nb-123"  # notebook_id
        assert call_args[0][1] == "text"     # source_type

    def test_seed_notebook_handles_missing_file(self, tmp_path):
        """seed_notebook reports errors for files that don't exist."""
        mgr, engine, _, factory = _make_manager(tmp_path)

        with patch("engine.nexus.nlm_notebook_factory.get_notebook_factory", return_value=factory), \
             patch("engine.nexus.nlm_notebook_manager.get_nlm_engine", return_value=engine):
            mgr.ensure_notebook("test-slot")
            result = mgr.seed_notebook("test-slot", ["/nonexistent/file.md"])

        assert result["added"] == 0
        assert len(result["errors"]) == 1

    def test_seed_from_docs(self, tmp_path):
        """seed_from_docs discovers .md files in docs/ and seeds them."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "ARCHITECTURE.md").write_text("# Arch", encoding="utf-8")
        (docs_dir / "SKILLS.md").write_text("# Skills", encoding="utf-8")

        mgr, engine, _, factory = _make_manager(tmp_path)

        with patch("engine.nexus.nlm_notebook_factory.get_notebook_factory", return_value=factory), \
             patch("engine.nexus.nlm_notebook_manager.get_nlm_engine", return_value=engine), \
             patch("engine.nexus.nlm_notebook_manager._PROJECT_ROOT", tmp_path):
            mgr.ensure_notebook("cosysim-architecture")
            result = mgr.seed_from_docs()

        assert result["added"] == 2
        assert result["errors"] == []

    def test_seed_from_docs_missing_dir(self, tmp_path):
        """seed_from_docs returns error when docs/ doesn't exist."""
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        mgr, engine, _, factory = _make_manager(tmp_path)

        with patch("engine.nexus.nlm_notebook_manager._PROJECT_ROOT", empty_root):
            result = mgr.seed_from_docs()

        assert "error" in result


class TestSeedFromCode:
    """Tests for seed_from_code."""

    def test_seed_from_code_with_explicit_paths(self, tmp_path):
        """seed_from_code seeds the given file paths."""
        code_file = tmp_path / "engine" / "config.py"
        code_file.parent.mkdir(parents=True)
        code_file.write_text("# config", encoding="utf-8")

        mgr, engine, _, factory = _make_manager(tmp_path)

        with patch("engine.nexus.nlm_notebook_factory.get_notebook_factory", return_value=factory), \
             patch("engine.nexus.nlm_notebook_manager.get_nlm_engine", return_value=engine), \
             patch("engine.nexus.nlm_notebook_manager._PROJECT_ROOT", tmp_path):
            mgr.ensure_notebook("cosysim-codebase")
            result = mgr.seed_from_code(paths=["engine/config.py"])

        assert result["added"] == 1


class TestResearch:
    """Tests for get_or_create_research."""

    def test_creates_research_notebook(self, tmp_path):
        """get_or_create_research creates a research-{topic} slot."""
        mgr, engine, meta_path, factory = _make_manager(tmp_path)

        with patch("engine.nexus.nlm_notebook_factory.get_notebook_factory", return_value=factory):
            result = mgr.get_or_create_research("mcp-state")

        assert result["slot_name"] == "research-mcp-state"
        assert result["notebook_id"] == "nb-123"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "research-mcp-state" in data


class TestRotation:
    """Tests for rotate_notebook."""

    def test_rotate_deletes_and_recreates(self, tmp_path):
        """rotate_notebook deletes old notebook and creates a fresh one."""
        existing = {
            "cosysim-architecture": {
                "slot_name": "cosysim-architecture",
                "notebook_id": "nb-old",
                "created_at": "2024-01-01T00:00:00+00:00",
                "source_count": 10,
                "last_seeded": None,
                "last_asked": None,
            }
        }
        mgr, engine, _, factory = _make_manager(tmp_path, notebooks=existing)

        with patch("engine.nexus.nlm_notebook_manager.get_nlm_engine", return_value=engine), \
             patch("engine.nexus.nlm_notebook_factory.get_notebook_factory", return_value=factory):
            result = mgr.rotate_notebook("cosysim-architecture")

        engine.delete_notebook.assert_called_once_with("nb-old")
        factory.get_or_create.assert_called_once()
        assert result["notebook_id"] == "nb-123"
        assert result["source_count"] == 0

    def test_rotate_nonexistent_creates_new(self, tmp_path):
        """rotate_notebook on a missing slot just creates it."""
        mgr, engine, _, factory = _make_manager(tmp_path)

        with patch("engine.nexus.nlm_notebook_manager.get_nlm_engine", return_value=engine), \
             patch("engine.nexus.nlm_notebook_factory.get_notebook_factory", return_value=factory):
            result = mgr.rotate_notebook("new-slot")

        engine.delete_notebook.assert_not_called()
        assert result["notebook_id"] == "nb-123"


class TestHealth:
    """Tests for health report."""

    def test_health_report_structure(self, tmp_path):
        """health() returns a dict with total_slots and per-slot info."""
        existing = {
            "cosysim-architecture": {
                "slot_name": "cosysim-architecture",
                "notebook_id": "nb-1",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_count": 5,
                "last_seeded": "2024-06-01T00:00:00+00:00",
                "last_asked": None,
            }
        }
        mgr, _, _, _ = _make_manager(tmp_path, notebooks=existing)

        report = mgr.health()

        assert report["total_slots"] == 1
        assert len(report["slots"]) == 1
        slot = report["slots"][0]
        assert slot["slot_name"] == "cosysim-architecture"
        assert slot["source_count"] == 5
        assert isinstance(slot["age_days"], float)

    def test_health_empty(self, tmp_path):
        """health() works with no managed notebooks."""
        mgr, _, _, _ = _make_manager(tmp_path)
        report = mgr.health()
        assert report["total_slots"] == 0
        assert report["slots"] == []


class TestCleanupStale:
    """Tests for cleanup_stale."""

    def test_cleanup_removes_old_research(self, tmp_path):
        """cleanup_stale deletes research notebooks older than max_age_days."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        existing = {
            "research-old-topic": {
                "slot_name": "research-old-topic",
                "notebook_id": "nb-stale",
                "created_at": old_date,
                "source_count": 3,
                "last_seeded": None,
                "last_asked": None,
            },
            "cosysim-architecture": {
                "slot_name": "cosysim-architecture",
                "notebook_id": "nb-keep",
                "created_at": old_date,
                "source_count": 5,
                "last_seeded": None,
                "last_asked": None,
            },
        }
        mgr, engine, meta_path, _ = _make_manager(tmp_path, notebooks=existing)

        with patch("engine.nexus.nlm_notebook_manager.get_nlm_engine", return_value=engine):
            removed = mgr.cleanup_stale(max_age_days=30)

        assert "research-old-topic" in removed
        assert "cosysim-architecture" not in removed
        engine.delete_notebook.assert_called_once_with("nb-stale")

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "research-old-topic" not in data
        assert "cosysim-architecture" in data

    def test_cleanup_keeps_recent_research(self, tmp_path):
        """cleanup_stale keeps research notebooks that are still fresh."""
        recent_date = datetime.now(timezone.utc).isoformat()
        existing = {
            "research-fresh": {
                "slot_name": "research-fresh",
                "notebook_id": "nb-fresh",
                "created_at": recent_date,
                "source_count": 1,
                "last_seeded": None,
                "last_asked": None,
            }
        }
        mgr, engine, _, _ = _make_manager(tmp_path, notebooks=existing)

        with patch("engine.nexus.nlm_notebook_manager.get_nlm_engine", return_value=engine):
            removed = mgr.cleanup_stale(max_age_days=30)

        assert removed == []
        engine.delete_notebook.assert_not_called()


class TestListManaged:
    """Tests for list_managed."""

    def test_list_managed_returns_copies(self, tmp_path):
        """list_managed returns independent copies of metadata."""
        existing = {
            "slot-a": {
                "slot_name": "slot-a",
                "notebook_id": "nb-a",
                "created_at": "2024-01-01T00:00:00+00:00",
                "source_count": 1,
                "last_seeded": None,
                "last_asked": None,
            }
        }
        mgr, _, _, _ = _make_manager(tmp_path, notebooks=existing)

        managed = mgr.list_managed()
        assert len(managed) == 1
        assert managed[0]["slot_name"] == "slot-a"

        # Mutating returned dict should not affect internal state
        managed[0]["slot_name"] = "mutated"
        assert mgr.list_managed()[0]["slot_name"] == "slot-a"


class TestThreadSafety:
    """Basic thread-safety tests."""

    def test_concurrent_ensure_notebook(self, tmp_path):
        """Multiple threads calling ensure_notebook don't corrupt state."""
        mgr, engine, meta_path, factory = _make_manager(tmp_path)
        results: list = []
        errors: list = []

        def worker(slot: str) -> None:
            try:
                r = mgr.ensure_notebook(slot)
                results.append(r)
            except Exception as exc:
                errors.append(exc)

        with patch("engine.nexus.nlm_notebook_factory.get_notebook_factory", return_value=factory):
            threads = [threading.Thread(target=worker, args=(f"slot-{i}",)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        assert not errors
        assert len(results) == 10

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(data) == 10


class TestMetadataPersistence:
    """Tests for metadata load/save round-trip."""

    def test_load_corrupted_json(self, tmp_path):
        """Manager handles corrupted metadata file gracefully."""
        meta_path = tmp_path / "nlm_notebooks.json"
        meta_path.write_text("{invalid json", encoding="utf-8")

        with patch("engine.nexus.nlm_notebook_manager.get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.get = MagicMock(return_value=str(meta_path))
            mock_cfg.return_value = cfg

            from engine.nexus.nlm_notebook_manager import NLMNotebookManager
            mgr = NLMNotebookManager(metadata_path=str(meta_path))

        assert mgr.list_managed() == []

    def test_load_missing_file(self, tmp_path):
        """Manager starts empty when metadata file doesn't exist."""
        meta_path = tmp_path / "nonexistent.json"

        with patch("engine.nexus.nlm_notebook_manager.get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.get = MagicMock(return_value=str(meta_path))
            mock_cfg.return_value = cfg

            from engine.nexus.nlm_notebook_manager import NLMNotebookManager
            mgr = NLMNotebookManager(metadata_path=str(meta_path))

        assert mgr.list_managed() == []
