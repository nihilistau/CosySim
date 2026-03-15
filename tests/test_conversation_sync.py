"""Tests for engine.nexus.conversation_sync — EventChain-to-Nexus sync.

Covers initialisation, sync-state persistence, EventChain DB reading,
conversation sync, skill-usage aggregation, interaction-pattern analysis,
force_sync, sync status, and scheduler integration.  Every external service
(Nexus, TrainingFlywheel, scheduler daemon) is mocked.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton before and after each test."""
    import engine.nexus.conversation_sync as mod
    mod._conversation_sync = None
    yield
    mod._conversation_sync = None


@pytest.fixture
def csync(tmp_path: Path):
    """Return a fresh ConversationSync backed by a temp database."""
    from engine.nexus.conversation_sync import ConversationSync

    with patch.object(ConversationSync, "_resolve_path", side_effect=lambda raw: Path(raw)):
        return ConversationSync(db_path=str(tmp_path / "test_sync.db"))


@pytest.fixture
def sync_conn(csync):
    """Direct read connection to the ConversationSync DB."""
    conn = sqlite3.connect(str(csync._db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def mock_event_chain_db(tmp_path: Path):
    """Create a mock EventChain SQLite DB with realistic test data."""
    db_path = tmp_path / "event_chain.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            timestamp TEXT,
            event_type TEXT,
            actor TEXT,
            payload TEXT,
            summary TEXT,
            chain_id TEXT,
            character_id TEXT,
            scene_id TEXT
        )
    """)
    now = datetime.now()
    test_events = [
        # Chain-001: 4 events (should qualify: >= 3)
        ("evt-1", (now - timedelta(hours=2)).isoformat(), "governed_response", "Lola",
         json.dumps({"scene": "bedroom", "skills_auto": ["flirt", "tease"], "game_active": True}),
         "Hey there, how are you today?", "chain-001", "lola", "bedroom"),
        ("evt-2", (now - timedelta(hours=1, minutes=50)).isoformat(), "governed_response", "Viktor",
         json.dumps({"scene": "bedroom", "skills_auto": ["compliment"], "game_active": True}),
         "You look wonderful tonight.", "chain-001", "viktor", "bedroom"),
        ("evt-3", (now - timedelta(hours=1, minutes=40)).isoformat(), "governed_response", "Lola",
         json.dumps({"scene": "bedroom", "skills_auto": ["flirt", "whisper"], "game_active": True}),
         "Come closer, I have a secret.", "chain-001", "lola", "bedroom"),
        ("evt-4", (now - timedelta(hours=1, minutes=30)).isoformat(), "governed_response", "Viktor",
         json.dumps({"scene": "bedroom", "skills_auto": ["embrace"], "game_active": True}),
         "I am here for you.", "chain-001", "viktor", "bedroom"),
        # Chain-002: 2 events (should be skipped: < 3)
        ("evt-5", (now - timedelta(hours=1)).isoformat(), "governed_response", "Aria",
         json.dumps({"scene": "lounge", "skills_auto": ["sing"], "game_active": True}),
         "La la la...", "chain-002", "aria", "lounge"),
        ("evt-6", (now - timedelta(minutes=50)).isoformat(), "governed_response", "Frankie",
         json.dumps({"scene": "lounge", "skills_auto": ["joke"], "game_active": True}),
         "Why did the chicken cross the road?", "chain-002", "frankie", "lounge"),
        # Chain-003: 3 events (should qualify)
        ("evt-7", (now - timedelta(minutes=30)).isoformat(), "governed_response", "Mira",
         json.dumps({"scene": "garden", "skills_auto": ["meditate"], "game_active": True}),
         "Peace and tranquility.", "chain-003", "mira", "garden"),
        ("evt-8", (now - timedelta(minutes=20)).isoformat(), "governed_response", "Mira",
         json.dumps({"scene": "garden", "skills_auto": ["meditate", "breathe"], "game_active": True}),
         "Inhale... exhale...", "chain-003", "mira", "garden"),
        ("evt-9", (now - timedelta(minutes=10)).isoformat(), "governed_response", "Mira",
         json.dumps({"scene": "garden", "skills_auto": ["wisdom"], "game_active": True}),
         "The mind is like water.", "chain-003", "mira", "garden"),
        # Non-governed event (should be excluded)
        ("evt-10", (now - timedelta(minutes=5)).isoformat(), "system_event", "system",
         json.dumps({}), "System heartbeat", None, None, None),
    ]
    conn.executemany(
        "INSERT INTO events (id, timestamp, event_type, actor, payload, summary, chain_id, character_id, scene_id) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        test_events,
    )
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_ec_path(csync, db_path: Path):
    """Patch _get_event_chain_db_path to return the mock DB path."""
    return patch.object(csync, "_get_event_chain_db_path", return_value=db_path)


def _patch_nexus():
    """Patch the Nexus client lazy import inside conversation_sync."""
    return patch("engine.nexus.client.get_nexus_client")


def _patch_flywheel():
    """Patch the TrainingFlywheel lazy import."""
    return patch("engine.nexus.training_flywheel.get_training_flywheel")


# ===================================================================
# Initialisation
# ===================================================================

class TestInitialisation:
    """ConversationSync constructor, singleton, and schema bootstrap."""

    def test_conversation_sync_singleton(self, tmp_path: Path):
        from engine.nexus.conversation_sync import ConversationSync, get_conversation_sync
        import engine.nexus.conversation_sync as mod
        mod._conversation_sync = None

        db = str(tmp_path / "singleton.db")
        with patch.object(ConversationSync, "_resolve_path", side_effect=lambda raw: Path(raw)):
            a = get_conversation_sync(db_path=db)
            b = get_conversation_sync(db_path=db)
        assert a is b

    def test_creates_db(self, csync):
        assert csync._db_path.exists()

    def test_db_tables(self, csync, sync_conn):
        tables = {
            r[0]
            for r in sync_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "sync_state" in tables
        assert "sync_records" in tables

    def test_custom_db_path(self, tmp_path: Path):
        from engine.nexus.conversation_sync import ConversationSync

        custom = tmp_path / "sub" / "custom.db"
        with patch.object(ConversationSync, "_resolve_path", side_effect=lambda raw: Path(raw)):
            cs = ConversationSync(db_path=str(custom))
        assert cs._db_path.exists()


# ===================================================================
# Sync State
# ===================================================================

class TestSyncState:
    """_get_last_event_id / _set_last_event_id round-trips."""

    def test_get_last_event_id_default(self, csync):
        assert csync._get_last_event_id() == 0

    def test_set_last_event_id(self, csync):
        csync._set_last_event_id(42)
        assert csync._get_last_event_id() == 42

    def test_get_set_roundtrip(self, csync):
        csync._set_last_event_id(999)
        assert csync._get_last_event_id() == 999

    def test_state_persisted(self, tmp_path: Path):
        from engine.nexus.conversation_sync import ConversationSync

        db = str(tmp_path / "persist.db")
        with patch.object(ConversationSync, "_resolve_path", side_effect=lambda raw: Path(raw)):
            cs1 = ConversationSync(db_path=db)
            cs1._set_last_event_id(77)

            cs2 = ConversationSync(db_path=db)
            assert cs2._get_last_event_id() == 77

    def test_state_thread_safe(self, csync):
        errors: list = []

        def _writer(value: int):
            try:
                csync._set_last_event_id(value)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        final = csync._get_last_event_id()
        assert 0 <= final < 20


# ===================================================================
# Event Reading
# ===================================================================

class TestEventReading:
    """_read_events against a mock EventChain DB."""

    def test_read_events_empty(self, csync, tmp_path: Path):
        empty_db = tmp_path / "empty.db"
        conn = sqlite3.connect(str(empty_db))
        conn.execute("""
            CREATE TABLE events (
                id TEXT PRIMARY KEY, timestamp TEXT, event_type TEXT,
                actor TEXT, payload TEXT, summary TEXT,
                chain_id TEXT, character_id TEXT, scene_id TEXT
            )
        """)
        conn.commit()
        conn.close()
        with _patch_ec_path(csync, empty_db):
            events = csync._read_events(0, 100)
        assert events == []

    def test_read_events_filters_by_id(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db):
            all_events = csync._read_events(0, 100)
            after_5 = csync._read_events(5, 100)
        assert len(after_5) < len(all_events)
        for ev in after_5:
            assert ev["_rowid"] > 5

    def test_read_events_filters_by_type(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db):
            events = csync._read_events(0, 100)
        # Only governed_response events should appear
        for ev in events:
            assert ev["event_type"] == "governed_response"

    def test_read_events_respects_batch_size(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db):
            events = csync._read_events(0, 3)
        assert len(events) <= 3

    def test_read_events_ordered_by_id(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db):
            events = csync._read_events(0, 100)
        rowids = [ev["_rowid"] for ev in events]
        assert rowids == sorted(rowids)

    def test_read_events_handles_missing_db(self, csync, tmp_path: Path):
        missing = tmp_path / "does_not_exist.db"
        with _patch_ec_path(csync, missing):
            events = csync._read_events(0, 100)
        assert events == []


# ===================================================================
# Conversation Sync
# ===================================================================

class TestConversationSync:
    """sync_conversations() — grouping, filtering, Nexus storage."""

    def test_sync_conversations_empty(self, csync, tmp_path: Path):
        empty_db = tmp_path / "empty_ec.db"
        conn = sqlite3.connect(str(empty_db))
        conn.execute("""
            CREATE TABLE events (
                id TEXT, timestamp TEXT, event_type TEXT, actor TEXT,
                payload TEXT, summary TEXT, chain_id TEXT,
                character_id TEXT, scene_id TEXT
            )
        """)
        conn.commit()
        conn.close()
        with _patch_ec_path(csync, empty_db), _patch_nexus(), _patch_flywheel():
            result = csync.sync_conversations()
        assert result["events_processed"] == 0

    def test_sync_conversations_groups_by_chain(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx, _patch_flywheel():
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            result = csync.sync_conversations()
        # chain-001 (4 events) and chain-003 (3 events) qualify
        assert result["chains_processed"] == 2

    def test_sync_conversations_min_events(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx, _patch_flywheel():
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            result = csync.sync_conversations()
        # chain-002 has only 2 events → skipped
        assert result["skipped_short_chains"] == 1

    def test_sync_conversations_creates_nexus_entry(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx, _patch_flywheel():
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            csync.sync_conversations()
        assert m_nx.return_value.add_entry.call_count >= 2  # one per qualifying chain

    def test_sync_conversations_updates_last_id(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx, _patch_flywheel():
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            csync.sync_conversations()
        assert csync._get_last_event_id() > 0

    def test_sync_conversations_handles_nexus_error(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx, _patch_flywheel():
            m_nx.return_value.add_entry.side_effect = ConnectionError("nexus down")
            m_nx.return_value.add_qa.side_effect = ConnectionError("nexus down")
            result = csync.sync_conversations()
        # Should complete without raising — entries_created stays 0
        assert result["entries_created"] == 0

    def test_sync_conversations_extracts_skills(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx, _patch_flywheel():
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            csync.sync_conversations()
        # Check that add_entry was called with content mentioning skills
        for call in m_nx.return_value.add_entry.call_args_list:
            content = call.kwargs.get("content", "")
            if "chain-001" in content or "bedroom" in content.lower():
                assert "flirt" in content or "Skills used" in content

    def test_sync_conversations_batch_processing(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx, _patch_flywheel():
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            # Process only 3 events first
            result1 = csync.sync_conversations(batch_size=3)
            last_id_1 = csync._get_last_event_id()
            # Then the remainder
            result2 = csync.sync_conversations(batch_size=100)
        assert result1["events_processed"] == 3
        assert csync._get_last_event_id() >= last_id_1


# ===================================================================
# Skill Usage Sync
# ===================================================================

class TestSkillUsageSync:
    """sync_skill_usage() — aggregation and Nexus storage."""

    def test_sync_skill_usage_aggregates(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx:
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            result = csync.sync_skill_usage()
        assert result["unique_skills"] > 0
        assert result["total_events"] > 0

    def test_sync_skill_usage_stores_report(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx:
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            csync.sync_skill_usage()
        # At least a summary entry should be stored
        assert m_nx.return_value.add_entry.call_count >= 1

    def test_sync_skill_usage_empty(self, csync, tmp_path: Path):
        empty_db = tmp_path / "empty_ec2.db"
        conn = sqlite3.connect(str(empty_db))
        conn.execute("""
            CREATE TABLE events (
                id TEXT, timestamp TEXT, event_type TEXT, actor TEXT,
                payload TEXT, summary TEXT, chain_id TEXT,
                character_id TEXT, scene_id TEXT
            )
        """)
        conn.commit()
        conn.close()
        with _patch_ec_path(csync, empty_db), _patch_nexus():
            result = csync.sync_skill_usage()
        assert result["unique_skills"] == 0
        assert result["entries_created"] == 0

    def test_sync_skill_usage_stores_qa(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx:
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            csync.sync_skill_usage()
        # Should store at least the "top-5" Q&A
        assert m_nx.return_value.add_qa.call_count >= 1

    def test_sync_skill_usage_handles_error(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db):
            with patch.object(csync, "_read_events_since", side_effect=RuntimeError("db err")):
                result = csync.sync_skill_usage()
        assert "error" in result
        assert "db err" in result["error"]


# ===================================================================
# Interaction Patterns
# ===================================================================

class TestInteractionPatterns:
    """sync_interaction_patterns() — pattern detection and storage."""

    def test_sync_patterns_avg_length(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx:
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            result = csync.sync_interaction_patterns()
        assert "avg_lengths" in result
        assert isinstance(result["avg_lengths"], dict)

    def test_sync_patterns_active_characters(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx:
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            result = csync.sync_interaction_patterns()
        assert "top_characters" in result
        chars = result["top_characters"]
        assert isinstance(chars, dict)
        assert len(chars) > 0

    def test_sync_patterns_peak_hours(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx:
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            result = csync.sync_interaction_patterns()
        assert "peak_hours" in result

    def test_sync_patterns_stores_in_nexus(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db), _patch_nexus() as m_nx:
            m_nx.return_value.add_entry.return_value = "eid"
            m_nx.return_value.add_qa.return_value = "qid"
            csync.sync_interaction_patterns()
        assert m_nx.return_value.add_entry.call_count >= 1

    def test_sync_patterns_empty_data(self, csync, tmp_path: Path):
        empty_db = tmp_path / "empty_ec3.db"
        conn = sqlite3.connect(str(empty_db))
        conn.execute("""
            CREATE TABLE events (
                id TEXT, timestamp TEXT, event_type TEXT, actor TEXT,
                payload TEXT, summary TEXT, chain_id TEXT,
                character_id TEXT, scene_id TEXT
            )
        """)
        conn.commit()
        conn.close()
        with _patch_ec_path(csync, empty_db), _patch_nexus():
            result = csync.sync_interaction_patterns()
        assert result["total_events"] == 0
        assert result["patterns_found"] == 0


# ===================================================================
# Force Sync
# ===================================================================

class TestForceSync:
    """force_sync() — runs all three sync methods."""

    def test_force_sync_runs_all(self, csync):
        csync.sync_conversations = MagicMock(return_value={
            "events_processed": 5, "entries_created": 1, "chains_processed": 1, "skipped_short_chains": 0,
        })
        csync.sync_skill_usage = MagicMock(return_value={
            "total_events": 3, "unique_skills": 2, "entries_created": 1,
        })
        csync.sync_interaction_patterns = MagicMock(return_value={
            "total_events": 10, "patterns_found": 4, "entries_created": 1,
            "avg_lengths": {}, "top_characters": {}, "peak_hours": {},
            "top_sequences": {}, "training_signals": [],
        })
        csync.force_sync()
        csync.sync_conversations.assert_called_once()
        csync.sync_skill_usage.assert_called_once()
        csync.sync_interaction_patterns.assert_called_once()

    def test_force_sync_returns_combined(self, csync):
        csync.sync_conversations = MagicMock(return_value={
            "events_processed": 10, "entries_created": 2, "chains_processed": 2, "skipped_short_chains": 0,
        })
        csync.sync_skill_usage = MagicMock(return_value={
            "total_events": 5, "unique_skills": 3, "entries_created": 1,
        })
        csync.sync_interaction_patterns = MagicMock(return_value={
            "total_events": 20, "patterns_found": 5, "entries_created": 2,
            "avg_lengths": {}, "top_characters": {}, "peak_hours": {},
            "top_sequences": {}, "training_signals": [],
        })
        result = csync.force_sync()
        assert "conversations" in result
        assert "skill_usage" in result
        assert "interaction_patterns" in result
        assert result["total_events"] == 10 + 5 + 20
        assert result["total_entries"] == 2 + 1 + 2

    def test_force_sync_partial_failure(self, csync):
        csync.sync_conversations = MagicMock(side_effect=RuntimeError("conv err"))
        csync.sync_skill_usage = MagicMock(return_value={
            "total_events": 1, "unique_skills": 1, "entries_created": 0,
        })
        csync.sync_interaction_patterns = MagicMock(return_value={
            "total_events": 2, "patterns_found": 0, "entries_created": 0,
            "avg_lengths": {}, "top_characters": {}, "peak_hours": {},
            "top_sequences": {}, "training_signals": [],
        })
        # force_sync calls _sync_callback which calls all three sequentially.
        # If sync_conversations raises, _sync_callback will propagate the error.
        # But let's test the actual _sync_callback behavior:
        with pytest.raises(RuntimeError, match="conv err"):
            csync.force_sync()


# ===================================================================
# Sync Status
# ===================================================================

class TestSyncStatus:
    """get_sync_status() — structure and content."""

    def test_get_sync_status_structure(self, csync, tmp_path: Path):
        empty_db = tmp_path / "empty_ec_status.db"
        conn = sqlite3.connect(str(empty_db))
        conn.execute("""
            CREATE TABLE events (
                id TEXT, timestamp TEXT, event_type TEXT, actor TEXT,
                payload TEXT, summary TEXT, chain_id TEXT,
                character_id TEXT, scene_id TEXT
            )
        """)
        conn.commit()
        conn.close()
        with _patch_ec_path(csync, empty_db):
            status = csync.get_sync_status()
        expected_keys = {
            "last_sync_timestamp", "last_sync_iso", "last_event_id",
            "events_pending", "total_synced", "recent_syncs",
        }
        assert expected_keys.issubset(status.keys())

    def test_get_sync_status_recent_syncs(self, csync, tmp_path: Path):
        empty_db = tmp_path / "empty_ec_status2.db"
        conn = sqlite3.connect(str(empty_db))
        conn.execute("""
            CREATE TABLE events (
                id TEXT, timestamp TEXT, event_type TEXT, actor TEXT,
                payload TEXT, summary TEXT, chain_id TEXT,
                character_id TEXT, scene_id TEXT
            )
        """)
        conn.commit()
        conn.close()

        # Manually insert a sync record
        with csync._cursor() as cur:
            cur.execute(
                "INSERT INTO sync_records (sync_id, sync_type, events_processed, entries_created, started_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("sync-test1", "conversation", 10, 2, time.time(), "completed"),
            )

        with _patch_ec_path(csync, empty_db):
            status = csync.get_sync_status()
        assert len(status["recent_syncs"]) == 1
        assert status["recent_syncs"][0]["sync_id"] == "sync-test1"

    def test_get_sync_status_pending_count(self, csync, mock_event_chain_db):
        with _patch_ec_path(csync, mock_event_chain_db):
            status = csync.get_sync_status()
        # All governed_response events should be pending (last_event_id = 0)
        assert status["events_pending"] == 9  # 9 governed_response events

    def test_get_sync_status_total_synced(self, csync, tmp_path: Path):
        empty_db = tmp_path / "empty_ec_status3.db"
        conn = sqlite3.connect(str(empty_db))
        conn.execute("""
            CREATE TABLE events (
                id TEXT, timestamp TEXT, event_type TEXT, actor TEXT,
                payload TEXT, summary TEXT, chain_id TEXT,
                character_id TEXT, scene_id TEXT
            )
        """)
        conn.commit()
        conn.close()

        with csync._cursor() as cur:
            cur.execute(
                "INSERT INTO sync_records (sync_id, sync_type, events_processed, entries_created, started_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("s1", "conversation", 10, 2, time.time(), "completed"),
            )
            cur.execute(
                "INSERT INTO sync_records (sync_id, sync_type, events_processed, entries_created, started_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("s2", "skill_usage", 5, 1, time.time(), "completed"),
            )
        with _patch_ec_path(csync, empty_db):
            status = csync.get_sync_status()
        assert status["total_synced"] == 15


# ===================================================================
# Scheduler Integration
# ===================================================================

class TestSchedulerIntegration:
    """register_task() and its wiring to the scheduler daemon."""

    def test_register_task_calls_scheduler(self, csync):
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as m_sd:
            daemon = MagicMock()
            m_sd.return_value = daemon
            csync.register_task()
        daemon.register.assert_called_once()

    def test_register_task_correct_schedule(self, csync):
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as m_sd:
            daemon = MagicMock()
            m_sd.return_value = daemon
            csync.register_task()
        call_kwargs = daemon.register.call_args.kwargs
        assert call_kwargs["schedule"] == "every_2h"
        assert call_kwargs["task_id"] == "conversation-sync"

    def test_register_task_callback(self, csync):
        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon") as m_sd:
            daemon = MagicMock()
            m_sd.return_value = daemon
            csync.register_task()
        call_kwargs = daemon.register.call_args.kwargs
        assert callable(call_kwargs["callback"])
        # The callback should be bound to _sync_callback
        assert call_kwargs["callback"] == csync._sync_callback


# ===================================================================
# SyncRecord Lifecycle
# ===================================================================

class TestSyncRecordLifecycle:
    """_start_sync, _complete_sync, _fail_sync database persistence."""

    def test_start_sync_creates_record(self, csync, sync_conn):
        rec = csync._start_sync("conversation")
        assert rec.sync_id.startswith("sync-")
        assert rec.status == "running"
        row = sync_conn.execute(
            "SELECT * FROM sync_records WHERE sync_id = ?",
            (rec.sync_id,),
        ).fetchone()
        assert row is not None

    def test_complete_sync_updates(self, csync, sync_conn):
        rec = csync._start_sync("conversation")
        csync._complete_sync(rec, {"events_processed": 10, "entries_created": 3})
        assert rec.status == "completed"
        row = sync_conn.execute(
            "SELECT * FROM sync_records WHERE sync_id = ?",
            (rec.sync_id,),
        ).fetchone()
        assert row["status"] == "completed"
        assert row["events_processed"] == 10
        assert row["entries_created"] == 3

    def test_fail_sync_updates(self, csync, sync_conn):
        rec = csync._start_sync("skill_usage")
        csync._fail_sync(rec, "something broke")
        assert rec.status == "failed"
        row = sync_conn.execute(
            "SELECT * FROM sync_records WHERE sync_id = ?",
            (rec.sync_id,),
        ).fetchone()
        assert row["status"] == "failed"
        assert row["error"] == "something broke"


# ===================================================================
# Grouping Helper
# ===================================================================

class TestGroupByChain:
    """Static _group_by_chain utility."""

    def test_groups_correctly(self):
        from engine.nexus.conversation_sync import ConversationSync

        events = [
            {"chain_id": "a", "data": 1},
            {"chain_id": "b", "data": 2},
            {"chain_id": "a", "data": 3},
        ]
        groups = ConversationSync._group_by_chain(events)
        assert len(groups) == 2
        assert len(groups["a"]) == 2
        assert len(groups["b"]) == 1

    def test_skips_none_chain_id(self):
        from engine.nexus.conversation_sync import ConversationSync

        events = [
            {"chain_id": None, "data": 1},
            {"chain_id": "x", "data": 2},
        ]
        groups = ConversationSync._group_by_chain(events)
        assert "x" in groups
        assert None not in groups
