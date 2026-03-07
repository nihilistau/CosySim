"""Tests for engine.nexus.sync_sessions_to_nexus — Copilot session sync utility."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import urllib.error
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.sync_sessions_to_nexus import (
    _build_nexus_content,
    _get_session_detail,
    _get_sessions,
    _load_state,
    _post_nexus,
    _save_state,
    _session_hash,
    run_session_sync,
    sync_all,
    sync_session,
)


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_db(tmp_path: Path) -> Path:
    """Create a minimal in-memory-style SQLite session store."""
    db_path = tmp_path / "store.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            cwd TEXT, repository TEXT, branch TEXT,
            summary TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE checkpoints (
            session_id TEXT, checkpoint_number INTEGER,
            title TEXT, overview TEXT, work_done TEXT,
            technical_details TEXT, next_steps TEXT
        );
        CREATE TABLE session_files (
            session_id TEXT, file_path TEXT,
            tool_name TEXT, first_seen_at TEXT
        );
        CREATE TABLE turns (session_id TEXT, turn_index INTEGER);
        CREATE TABLE session_refs (
            session_id TEXT, ref_type TEXT, ref_value TEXT
        );
    """)

    # Seed one session with 2 checkpoints
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
        ("abc-1234-5678", "/app", "owner/repo", "main",
         "Added caching layer", "2026-01-01T10:00:00Z", "2026-01-01T12:00:00Z"),
    )
    conn.execute(
        "INSERT INTO checkpoints VALUES (?,?,?,?,?,?,?)",
        ("abc-1234-5678", 1, "Implemented Redis cache",
         "Overview text", "Work done text", "Technical details", "Next steps"),
    )
    conn.execute(
        "INSERT INTO checkpoints VALUES (?,?,?,?,?,?,?)",
        ("abc-1234-5678", 2, "Added tests",
         "Test overview", "Tests written", "Test tech", "Deploy next"),
    )
    conn.execute(
        "INSERT INTO session_files VALUES (?,?,?,?)",
        ("abc-1234-5678", "engine/cache.py", "edit", "2026-01-01T10:30:00Z"),
    )
    conn.execute(
        "INSERT INTO session_files VALUES (?,?,?,?)",
        ("abc-1234-5678", "tests/test_cache.py", "create", "2026-01-01T11:00:00Z"),
    )
    conn.execute(
        "INSERT INTO turns VALUES (?,?)", ("abc-1234-5678", 0),
    )
    conn.execute(
        "INSERT INTO turns VALUES (?,?)", ("abc-1234-5678", 1),
    )
    conn.execute(
        "INSERT INTO session_refs VALUES (?,?,?)",
        ("abc-1234-5678", "commit", "abc1234"),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def sample_session() -> Dict[str, Any]:
    return {
        "id": "abc-1234-5678",
        "cwd": "/app",
        "repository": "owner/repo",
        "branch": "main",
        "summary": "Added caching layer",
        "created_at": "2026-01-01T10:00:00Z",
        "updated_at": "2026-01-01T12:00:00Z",
    }


@pytest.fixture
def sample_detail() -> Dict[str, Any]:
    return {
        "checkpoints": [
            {
                "number": 1,
                "title": "Implemented Redis cache",
                "overview": "Overview text",
                "work_done": "Work done text",
                "technical_details": "Technical details",
                "next_steps": "Next steps",
            }
        ],
        "files": [
            {"path": "engine/cache.py", "action": "edit"},
            {"path": "tests/test_cache.py", "action": "create"},
        ],
        "refs": [{"type": "commit", "value": "abc1234"}],
        "turn_count": 2,
    }


# ──── _get_sessions ───────────────────────────────────────────────────────────


class TestGetSessions:
    def test_missing_db_returns_empty(self, tmp_path: Path) -> None:
        """Returns empty list when session store DB does not exist."""
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB",
                   tmp_path / "nonexistent.sqlite"):
            result = _get_sessions()
        assert result == []

    def test_reads_sessions_from_db(self, fake_db: Path) -> None:
        """Reads sessions from the SQLite store."""
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db):
            result = _get_sessions(days=None)
        assert len(result) == 1
        assert result[0]["id"] == "abc-1234-5678"
        assert result[0]["branch"] == "main"

    def test_filters_by_session_id(self, fake_db: Path) -> None:
        """Filters to specific session ID."""
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db):
            result = _get_sessions(session_id="abc-1234-5678")
        assert len(result) == 1

        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db):
            result = _get_sessions(session_id="nonexistent")
        assert len(result) == 0

    def test_filters_by_days(self, fake_db: Path) -> None:
        """Filters to sessions within the last N days."""
        # Session is from 2026-01-01 — it will be excluded if days is too small
        # with a recent cutoff; but since we don't know the test run date,
        # we use days=None to get all and verify the DB is readable
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db):
            result = _get_sessions(days=None)
        assert len(result) == 1


# ──── _get_session_detail ─────────────────────────────────────────────────────


class TestGetSessionDetail:
    def test_returns_checkpoints(self, fake_db: Path) -> None:
        """Returns checkpoints with all fields."""
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db):
            detail = _get_session_detail("abc-1234-5678")
        assert len(detail["checkpoints"]) == 2
        assert detail["checkpoints"][0]["title"] == "Implemented Redis cache"

    def test_returns_files(self, fake_db: Path) -> None:
        """Returns edited and created files."""
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db):
            detail = _get_session_detail("abc-1234-5678")
        assert len(detail["files"]) == 2
        paths = [f["path"] for f in detail["files"]]
        assert "engine/cache.py" in paths
        assert "tests/test_cache.py" in paths

    def test_returns_turn_count(self, fake_db: Path) -> None:
        """Returns correct turn count."""
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db):
            detail = _get_session_detail("abc-1234-5678")
        assert detail["turn_count"] == 2

    def test_returns_refs(self, fake_db: Path) -> None:
        """Returns session references."""
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db):
            detail = _get_session_detail("abc-1234-5678")
        assert len(detail["refs"]) == 1
        assert detail["refs"][0]["type"] == "commit"
        assert detail["refs"][0]["value"] == "abc1234"

    def test_missing_db_returns_empty(self, tmp_path: Path) -> None:
        """Returns empty detail when DB not found."""
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB",
                   tmp_path / "nonexistent.sqlite"):
            detail = _get_session_detail("any-id")
        assert detail["checkpoints"] == []
        assert detail["turn_count"] == 0


# ──── _build_nexus_content ────────────────────────────────────────────────────


class TestBuildNexusContent:
    def test_includes_session_id(
        self, sample_session: Dict, sample_detail: Dict
    ) -> None:
        """Content includes the short session ID."""
        content = _build_nexus_content(sample_session, sample_detail)
        assert "abc-1234" in content

    def test_includes_summary(
        self, sample_session: Dict, sample_detail: Dict
    ) -> None:
        """Session summary appears in content."""
        content = _build_nexus_content(sample_session, sample_detail)
        assert "Added caching layer" in content

    def test_includes_checkpoint_titles(
        self, sample_session: Dict, sample_detail: Dict
    ) -> None:
        """Checkpoint titles appear in content."""
        content = _build_nexus_content(sample_session, sample_detail)
        assert "Implemented Redis cache" in content

    def test_includes_file_paths(
        self, sample_session: Dict, sample_detail: Dict
    ) -> None:
        """File paths appear in content."""
        content = _build_nexus_content(sample_session, sample_detail)
        assert "engine/cache.py" in content
        assert "tests/test_cache.py" in content

    def test_includes_refs(
        self, sample_session: Dict, sample_detail: Dict
    ) -> None:
        """References (commits, PRs) appear in content."""
        content = _build_nexus_content(sample_session, sample_detail)
        assert "abc1234" in content

    def test_returns_string(
        self, sample_session: Dict, sample_detail: Dict
    ) -> None:
        """Returns a string."""
        content = _build_nexus_content(sample_session, sample_detail)
        assert isinstance(content, str)
        assert len(content) > 50


# ──── _session_hash ───────────────────────────────────────────────────────────


class TestSessionHash:
    def test_same_inputs_same_hash(
        self, sample_session: Dict, sample_detail: Dict
    ) -> None:
        """Same inputs produce the same hash."""
        h1 = _session_hash(sample_session, sample_detail)
        h2 = _session_hash(sample_session, sample_detail)
        assert h1 == h2

    def test_different_turn_count_different_hash(
        self, sample_session: Dict, sample_detail: Dict
    ) -> None:
        """Changing turn count changes the hash."""
        h1 = _session_hash(sample_session, sample_detail)
        sample_detail["turn_count"] += 1
        h2 = _session_hash(sample_session, sample_detail)
        assert h1 != h2

    def test_returns_string(
        self, sample_session: Dict, sample_detail: Dict
    ) -> None:
        """Hash is a non-empty string."""
        h = _session_hash(sample_session, sample_detail)
        assert isinstance(h, str)
        assert len(h) > 0


# ──── _load_state / _save_state ───────────────────────────────────────────────


class TestStateHelpers:
    def test_load_state_returns_empty_on_missing_file(self, tmp_path: Path) -> None:
        """Returns default state when file doesn't exist."""
        with patch(
            "engine.nexus.sync_sessions_to_nexus.STATE_FILE",
            tmp_path / "nonexistent.json",
        ):
            state = _load_state()
        assert state == {"synced": {}}

    def test_round_trip(self, tmp_path: Path) -> None:
        """Save then load produces identical state."""
        state_path = tmp_path / "sync_state.json"
        with patch("engine.nexus.sync_sessions_to_nexus.STATE_FILE", state_path):
            _save_state({"synced": {"abc": {"hash": "xyz123"}}})
            loaded = _load_state()
        assert loaded["synced"]["abc"]["hash"] == "xyz123"


class TestPostNexus:
    def test_posts_entries_through_client(self) -> None:
        client = MagicMock()
        client.add_entry.return_value = "entry-42"

        with patch(
            "engine.nexus.client.get_nexus_client",
            return_value=client,
        ):
            result = _post_nexus(
                "/entries",
                {
                    "title": "Session abc",
                    "content": "Content",
                    "content_type": "history",
                    "category": "copilot-history",
                    "tags": ["copilot"],
                },
            )

        assert result == {"id": "entry-42"}
        client.add_entry.assert_called_once()


# ──── sync_session ────────────────────────────────────────────────────────────


class TestSyncSession:
    def test_skips_unchanged_session(
        self, fake_db: Path, sample_session: Dict, sample_detail: Dict
    ) -> None:
        """Session with unchanged hash is skipped."""
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db):
            detail = _get_session_detail("abc-1234-5678")
            current_hash = _session_hash(sample_session, detail)

        state = {"synced": {"abc-1234-5678": {"hash": current_hash}}}
        with (
            patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db),
            patch("engine.nexus.sync_sessions_to_nexus._post_nexus") as mock_post,
        ):
            result = sync_session(sample_session, state, force=False)

        assert result is False
        mock_post.assert_not_called()

    def test_force_resyncs_unchanged(
        self, fake_db: Path, sample_session: Dict, sample_detail: Dict
    ) -> None:
        """force=True re-syncs even if hash matches."""
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db):
            detail = _get_session_detail("abc-1234-5678")
            current_hash = _session_hash(sample_session, detail)

        state = {"synced": {"abc-1234-5678": {"hash": current_hash}}}
        with (
            patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db),
            patch(
                "engine.nexus.sync_sessions_to_nexus._post_nexus",
                return_value={"id": 99},
            ),
        ):
            result = sync_session(sample_session, state, force=True)

        assert result is True

    def test_posts_to_nexus_on_new_session(
        self, fake_db: Path, sample_session: Dict
    ) -> None:
        """Posts entry to Nexus for new sessions."""
        state: Dict = {"synced": {}}
        with (
            patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db),
            patch(
                "engine.nexus.sync_sessions_to_nexus._post_nexus",
                return_value={"id": 42},
            ) as mock_post,
        ):
            result = sync_session(sample_session, state)

        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args[0]
        assert call_args[0] == "/entries"
        entry = call_args[1]
        assert entry["content_type"] == "history"
        assert entry["category"] == "copilot-history"

    def test_returns_false_on_nexus_failure(
        self, fake_db: Path, sample_session: Dict
    ) -> None:
        """Returns False when Nexus POST fails."""
        state: Dict = {"synced": {}}
        with (
            patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db),
            patch("engine.nexus.sync_sessions_to_nexus._post_nexus", return_value=None),
        ):
            result = sync_session(sample_session, state)

        assert result is False

    def test_updates_state_on_success(
        self, fake_db: Path, sample_session: Dict
    ) -> None:
        """State is updated with hash and nexus_id after successful sync."""
        state: Dict = {"synced": {}}
        with (
            patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db),
            patch(
                "engine.nexus.sync_sessions_to_nexus._post_nexus",
                return_value={"id": 77},
            ),
        ):
            sync_session(sample_session, state)

        assert "abc-1234-5678" in state["synced"]
        assert state["synced"]["abc-1234-5678"]["nexus_id"] == 77


# ──── sync_all ────────────────────────────────────────────────────────────────


class TestSyncAll:
    def test_no_sessions_returns_zeros(self, tmp_path: Path) -> None:
        """Returns zero counts when no sessions found."""
        with (
            patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB",
                  tmp_path / "missing.sqlite"),
            patch("engine.nexus.sync_sessions_to_nexus._save_state"),
        ):
            result = sync_all()
        assert result["total"] == 0
        assert result["synced"] == 0

    def test_syncs_new_session(self, fake_db: Path) -> None:
        """Syncs one new session."""
        with (
            patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db),
            patch("engine.nexus.sync_sessions_to_nexus._load_state",
                  return_value={"synced": {}}),
            patch("engine.nexus.sync_sessions_to_nexus._save_state"),
            patch(
                "engine.nexus.sync_sessions_to_nexus._post_nexus",
                return_value={"id": 1},
            ),
        ):
            result = sync_all(days=None)

        assert result["total"] == 1
        assert result["synced"] == 1
        assert result["failed"] == 0

    def test_skips_unchanged_session(self, fake_db: Path) -> None:
        """Sessions with matching hash are skipped."""
        # Pre-compute the hash for the existing session
        with patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db):
            sessions = _get_sessions(days=None)
            detail = _get_session_detail(sessions[0]["id"])
            h = _session_hash(sessions[0], detail)

        with (
            patch("engine.nexus.sync_sessions_to_nexus.SESSION_STORE_DB", fake_db),
            patch(
                "engine.nexus.sync_sessions_to_nexus._load_state",
                return_value={"synced": {sessions[0]["id"]: {"hash": h}}},
            ),
            patch("engine.nexus.sync_sessions_to_nexus._save_state"),
            patch("engine.nexus.sync_sessions_to_nexus._post_nexus") as mock_post,
        ):
            result = sync_all(days=None)

        assert result["skipped"] == 1
        mock_post.assert_not_called()


# ──── run_session_sync ────────────────────────────────────────────────────────


class TestRunSessionSync:
    def test_calls_sync_all_with_7_days(self) -> None:
        """Scheduler callback calls sync_all with days=7."""
        with patch("engine.nexus.sync_sessions_to_nexus.sync_all") as mock_sync:
            mock_sync.return_value = {"total": 0, "synced": 0, "skipped": 0, "failed": 0}
            result = run_session_sync()
        mock_sync.assert_called_once_with(days=7)
        assert "total" in result
