"""Tests for engine.nexus.history_miner."""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch
import pytest

from engine.nexus.history_miner import (
    HistoryMiner,
    QAPair,
    SourceDocument,
    THEMES,
    get_history_miner,
)


class TestThemes:
    def test_all_ten_themes_exist(self):
        assert len(THEMES) == 10

    def test_theme_keys(self):
        expected = {
            "nlm-integration",
            "architecture",
            "training-pipeline",
            "tts-system",
            "nexus-core",
            "scene-system",
            "testing-patterns",
            "config-system",
            "governance",
            "tools-and-skills",
        }
        assert set(THEMES.keys()) == expected

    def test_each_theme_has_keywords(self):
        for theme, keywords in THEMES.items():
            assert isinstance(keywords, list), f"Theme {theme} keywords not a list"
            assert len(keywords) >= 2, f"Theme {theme} has too few keywords"


class TestHistoryMinerInit:
    def test_default_db_path_exists(self):
        miner = HistoryMiner()
        assert miner._store_path is not None

    def test_custom_db_path(self):
        miner = HistoryMiner(store_path="C:/custom/path.db")
        assert "custom" in str(miner._store_path)

    def test_singleton_returns_same_instance(self):
        m1 = get_history_miner()
        m2 = get_history_miner()
        assert m1 is m2


class TestMineCheckpoints:
    """mine_checkpoints() returns a SourceDocument from checkpoint rows."""

    def _make_rows(self):
        return [
            # session_id, number, title, overview, history, work_done, tech, next
            ("sess1", 1, "Title A", "nlm overview" * 10, "history", "work done", "tech details" * 5, "next"),
            ("sess1", 2, "Title B", "notebooklm content" * 10, "hist2", "work2", "tech2" * 5, "next2"),
        ]

    def test_returns_source_document(self):
        miner = HistoryMiner()
        with patch.object(miner, "_fetch_checkpoints", return_value=self._make_rows()):
            doc = miner.mine_checkpoints("nlm-integration")
        assert isinstance(doc, SourceDocument)

    def test_document_title_contains_theme(self):
        miner = HistoryMiner()
        with patch.object(miner, "_fetch_checkpoints", return_value=self._make_rows()):
            doc = miner.mine_checkpoints("nlm-integration")
        assert "nlm" in doc.title.lower() or "integration" in doc.title.lower()

    def test_document_content_non_empty(self):
        miner = HistoryMiner()
        with patch.object(miner, "_fetch_checkpoints", return_value=self._make_rows()):
            doc = miner.mine_checkpoints("nlm-integration")
        assert len(doc.content) > 0

    def test_missing_theme_raises_value_error(self):
        miner = HistoryMiner()
        with pytest.raises(ValueError):
            miner.mine_checkpoints("nonexistent-theme-xyz")


class TestMineAllThemes:
    def test_returns_list_of_source_documents(self):
        miner = HistoryMiner()
        mock_doc = SourceDocument(title="T", content="C" * 50, theme="nlm-integration", checkpoint_count=1)
        with patch.object(miner, "mine_checkpoints", return_value=mock_doc):
            docs = miner.mine_all_themes()
        assert isinstance(docs, list)
        assert all(isinstance(d, SourceDocument) for d in docs)

    def test_returns_one_doc_per_theme(self):
        miner = HistoryMiner()
        mock_doc = SourceDocument(title="T", content="C" * 50, theme="nlm-integration", checkpoint_count=1)
        with patch.object(miner, "mine_checkpoints", return_value=mock_doc):
            docs = miner.mine_all_themes()
        assert len(docs) == len(THEMES)


class TestMineTurns:
    def _turn_rows(self):
        return [
            # session_id, turn_index, user_message, assistant_response
            ("sess1", 0, "what is copilot?", "Copilot is an AI assistant " + "x" * 450),
            ("sess1", 1, "short?", "short answer"),
        ]

    def test_returns_list_of_qa_pairs(self):
        miner = HistoryMiner()
        with patch.object(miner, "_fetch_turns", return_value=self._turn_rows()):
            pairs = miner.mine_turns(min_answer_len=400)
        assert isinstance(pairs, list)

    def test_filters_by_min_answer_len(self):
        miner = HistoryMiner()
        with patch.object(miner, "_fetch_turns", return_value=self._turn_rows()):
            pairs = miner.mine_turns(min_answer_len=400)
        for pair in pairs:
            assert isinstance(pair, QAPair)
            assert len(pair.answer) >= 400

    def test_empty_returns_empty_list(self):
        miner = HistoryMiner()
        with patch.object(miner, "_fetch_turns", return_value=[]):
            pairs = miner.mine_turns()
        assert pairs == []


class TestMineFullDump:
    def _checkpoint_rows(self):
        return [
            ("sess1", 1, "Title A", "overview A" * 10, "hist A", "work A" * 5, "tech A" * 5, "next A"),
            ("sess1", 2, "Title B", "overview B" * 10, "hist B", "work B" * 5, "tech B" * 5, "next B"),
        ]

    def test_returns_string(self):
        miner = HistoryMiner()
        with patch.object(miner, "_fetch_checkpoints", return_value=self._checkpoint_rows()):
            dump = miner.mine_full_dump()
        assert isinstance(dump, str)

    def test_includes_all_rows(self):
        miner = HistoryMiner()
        with patch.object(miner, "_fetch_checkpoints", return_value=self._checkpoint_rows()):
            dump = miner.mine_full_dump()
        # Header mentions the count
        assert "2" in dump or "Title" in dump


class TestGetStats:
    def test_returns_error_when_file_missing(self):
        miner = HistoryMiner(store_path="nonexistent_definitely_not_there.db")
        stats = miner.get_stats()
        assert "error" in stats

    def test_returns_expected_keys_when_available(self, tmp_path):
        # Create a minimal sqlite db so the file exists
        import sqlite3 as _sqlite3
        db_path = tmp_path / "test.db"
        conn = _sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE sessions (id TEXT)")
        conn.execute("CREATE TABLE checkpoints (id TEXT)")
        conn.execute("CREATE TABLE turns (id TEXT)")
        conn.commit()
        conn.close()

        miner = HistoryMiner(store_path=db_path)
        with patch.object(miner, "_connect") as mock_conn_fn:
            mock_conn = MagicMock()
            mock_conn.__enter__ = lambda s: mock_conn
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchone.return_value = (5,)
            mock_conn_fn.return_value = mock_conn
            stats = miner.get_stats()

        assert isinstance(stats, dict)
        for key in ("session_count", "checkpoint_count", "turn_count", "store_path"):
            assert key in stats, f"Missing key: {key}"
