"""Tests for profile_skills — conversation analysis, user profile, and backup skills."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──── analyze_conversation ────────────────────────────────────────────────────

class TestAnalyzeConversation:
    def test_returns_json_string(self):
        from engine.skills.builtin.profile_skills import analyze_conversation
        text = "User: I code in Python on my RTX 2060.\nAssistant: Noted."
        result = analyze_conversation(text, mode="heuristic")
        data = json.loads(result)
        assert "extraction_mode" in data
        assert data["extraction_mode"] == "heuristic"

    def test_short_text_returns_error(self):
        from engine.skills.builtin.profile_skills import analyze_conversation
        result = analyze_conversation("hi", mode="heuristic")
        data = json.loads(result)
        assert data.get("error")

    def test_mode_auto_falls_back_gracefully(self):
        from engine.skills.builtin.profile_skills import analyze_conversation
        from engine.nexus.conversation_analyzer import ConversationAnalyzer
        with patch.object(ConversationAnalyzer, "_extract_nlm", return_value=None):
            with patch.object(ConversationAnalyzer, "_extract_lm", return_value=None):
                result = analyze_conversation(
                    "User: I use Python on Windows for all my projects.\nAssistant: That makes sense, Windows is great for development.",
                    mode="auto",
                )
        data = json.loads(result)
        assert data["extraction_mode"] == "heuristic"


class TestAnalyzeRecentConversation:
    def test_returns_json_on_empty_store(self):
        from engine.skills.builtin.profile_skills import analyze_recent_conversation
        from engine.nexus.conversation_analyzer import ConversationAnalyzer
        with patch.object(ConversationAnalyzer, "_fetch_recent_turns", return_value=""):
            result = analyze_recent_conversation()
        data = json.loads(result)
        assert "error" in data

    def test_calls_analyze_recent_turns(self):
        from engine.skills.builtin.profile_skills import analyze_recent_conversation
        from engine.nexus.conversation_analyzer import ConversationAnalyzer, ExtractionResult
        with patch.object(
            ConversationAnalyzer, "analyze_recent_turns",
            return_value=ExtractionResult(facts=["Test fact"], extraction_mode="heuristic"),
        ) as mock_fn:
            result = analyze_recent_conversation(turns_back=30)
        mock_fn.assert_called_once_with(turns_back=30, store_to_profile=True)
        data = json.loads(result)
        assert "Test fact" in data["facts"]


class TestConversationAnalyzerStatus:
    def test_returns_null_string_when_no_result(self):
        from engine.skills.builtin.profile_skills import conversation_analyzer_status
        from engine.nexus.conversation_analyzer import ConversationAnalyzer
        with patch.object(ConversationAnalyzer, "get_last_result", return_value=None):
            result = conversation_analyzer_status()
        assert result == "null"

    def test_returns_json_when_result_exists(self):
        from engine.skills.builtin.profile_skills import conversation_analyzer_status
        from engine.nexus.conversation_analyzer import ConversationAnalyzer
        mock_result = {"extraction_mode": "heuristic", "facts": ["RTX 2060"]}
        with patch.object(ConversationAnalyzer, "get_last_result", return_value=mock_result):
            result = conversation_analyzer_status()
        data = json.loads(result)
        assert data["extraction_mode"] == "heuristic"


# ──── user_profile_get / context / facts ────────────────────────────────────────

class TestUserProfileGet:
    def test_returns_json_with_name(self, tmp_path):
        from engine.skills.builtin.profile_skills import user_profile_get
        from engine.nexus.user_profile import UserProfileStore
        store = UserProfileStore(cache_path=tmp_path / "p.json")
        with patch("engine.skills.builtin.profile_skills._profile", return_value=store):
            result = user_profile_get()
        data = json.loads(result)
        assert data["name"] == "Knack"

    def test_returns_json_string(self, tmp_path):
        from engine.skills.builtin.profile_skills import user_profile_get
        from engine.nexus.user_profile import UserProfileStore
        store = UserProfileStore(cache_path=tmp_path / "p.json")
        with patch("engine.skills.builtin.profile_skills._profile", return_value=store):
            result = user_profile_get()
        assert isinstance(result, str)
        json.loads(result)  # must be valid JSON


class TestUserProfileContext:
    def test_returns_markdown_string(self, tmp_path):
        from engine.skills.builtin.profile_skills import user_profile_context
        from engine.nexus.user_profile import UserProfileStore
        store = UserProfileStore(cache_path=tmp_path / "p.json")
        with patch("engine.skills.builtin.profile_skills._profile", return_value=store):
            result = user_profile_context()
        assert "User Profile" in result
        assert isinstance(result, str)


class TestUserProfileFacts:
    def test_empty_facts(self, tmp_path):
        from engine.skills.builtin.profile_skills import user_profile_facts
        from engine.nexus.user_profile import UserProfileStore
        store = UserProfileStore(cache_path=tmp_path / "p.json")
        with patch("engine.skills.builtin.profile_skills._profile", return_value=store):
            result = user_profile_facts()
        assert json.loads(result) == []

    def test_facts_listed(self, tmp_path):
        from engine.skills.builtin.profile_skills import user_profile_facts
        from engine.nexus.user_profile import UserProfileStore
        store = UserProfileStore(cache_path=tmp_path / "p.json")
        store.add_fact("Has RTX 2060")
        with patch("engine.skills.builtin.profile_skills._profile", return_value=store):
            result = user_profile_facts()
        facts = json.loads(result)
        assert "Has RTX 2060" in facts


class TestUserProfileAddFact:
    def test_adds_fact(self, tmp_path):
        from engine.skills.builtin.profile_skills import user_profile_add_fact
        from engine.nexus.user_profile import UserProfileStore
        store = UserProfileStore(cache_path=tmp_path / "p.json")
        with patch("engine.skills.builtin.profile_skills._profile", return_value=store):
            result = user_profile_add_fact("Uses VS Code")
        assert "Uses VS Code" in result
        assert "Uses VS Code" in store.get_profile()["facts"]


class TestUserProfileSetPreference:
    def test_sets_preference(self, tmp_path):
        from engine.skills.builtin.profile_skills import user_profile_set_preference
        from engine.nexus.user_profile import UserProfileStore
        store = UserProfileStore(cache_path=tmp_path / "p.json")
        with patch("engine.skills.builtin.profile_skills._profile", return_value=store):
            result = user_profile_set_preference("verbosity", "concise")
        assert "verbosity" in result
        assert store.get_profile()["preferences"]["verbosity"] == "concise"


class TestUserProfileUpdate:
    def test_valid_json_updates_profile(self, tmp_path):
        from engine.skills.builtin.profile_skills import user_profile_update
        from engine.nexus.user_profile import UserProfileStore
        store = UserProfileStore(cache_path=tmp_path / "p.json")
        with patch("engine.skills.builtin.profile_skills._profile", return_value=store):
            result = user_profile_update(json.dumps({"technical_background": ["Python"]}))
        data = json.loads(result)
        assert "Python" in data["technical_background"]

    def test_invalid_json_returns_error(self, tmp_path):
        from engine.skills.builtin.profile_skills import user_profile_update
        from engine.nexus.user_profile import UserProfileStore
        store = UserProfileStore(cache_path=tmp_path / "p.json")
        with patch("engine.skills.builtin.profile_skills._profile", return_value=store):
            result = user_profile_update("not valid json{")
        data = json.loads(result)
        assert "error" in data


# ──── backup_run / backup_list / backup_restore ──────────────────────────────

class TestBackupRun:
    def test_returns_json_summary(self, tmp_path):
        from engine.skills.builtin.profile_skills import backup_run
        from engine.nexus.backup_manager import BackupManager, BackupResult
        mgr = MagicMock(spec=BackupManager)
        mgr.run_backup.return_value = BackupResult(
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:05Z",
            succeeded=2,
        )
        with patch("engine.skills.builtin.profile_skills._backup", return_value=mgr):
            result = backup_run()
        data = json.loads(result)
        assert data["succeeded"] == 2

    def test_calls_run_backup(self):
        from engine.skills.builtin.profile_skills import backup_run
        from engine.nexus.backup_manager import BackupManager, BackupResult
        mgr = MagicMock(spec=BackupManager)
        mgr.run_backup.return_value = BackupResult()
        with patch("engine.skills.builtin.profile_skills._backup", return_value=mgr):
            backup_run()
        mgr.run_backup.assert_called_once()


class TestBackupList:
    def test_returns_json_array(self):
        from engine.skills.builtin.profile_skills import backup_list
        from engine.nexus.backup_manager import BackupManager
        mgr = MagicMock(spec=BackupManager)
        mgr.list_backups.return_value = [
            {"filename": "test.db.gz", "size_kb": 12.5, "age_days": 1.0}
        ]
        with patch("engine.skills.builtin.profile_skills._backup", return_value=mgr):
            result = backup_list()
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["filename"] == "test.db.gz"

    def test_returns_empty_array_when_none(self):
        from engine.skills.builtin.profile_skills import backup_list
        from engine.nexus.backup_manager import BackupManager
        mgr = MagicMock(spec=BackupManager)
        mgr.list_backups.return_value = []
        with patch("engine.skills.builtin.profile_skills._backup", return_value=mgr):
            result = backup_list()
        assert json.loads(result) == []


class TestBackupRestore:
    def test_success_returns_json(self):
        from engine.skills.builtin.profile_skills import backup_restore
        from engine.nexus.backup_manager import BackupManager
        mgr = MagicMock(spec=BackupManager)
        mgr.restore_backup.return_value = {"success": True, "restored_path": "/tmp/out.db", "size_kb": 5.0}
        with patch("engine.skills.builtin.profile_skills._backup", return_value=mgr):
            result = backup_restore("/backups/test.db.gz", "/tmp/out.db")
        data = json.loads(result)
        assert data["success"] is True

    def test_failure_returns_error(self):
        from engine.skills.builtin.profile_skills import backup_restore
        from engine.nexus.backup_manager import BackupManager
        mgr = MagicMock(spec=BackupManager)
        mgr.restore_backup.return_value = {"success": False, "error": "Not found"}
        with patch("engine.skills.builtin.profile_skills._backup", return_value=mgr):
            result = backup_restore("/bad/path.db.gz", "/tmp/out.db")
        data = json.loads(result)
        assert data["success"] is False
        assert "error" in data
