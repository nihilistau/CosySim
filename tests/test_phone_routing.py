"""Tests for Phone scene v2 — PhoneDB logic, game sessions, message system."""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from content.scenes.phone.phone_db import PhoneDB
from content.scenes.phone.phone_rules_v2 import get_truth, get_dare, SCENE_ID


# ══════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def phone_db(tmp_path):
    """Create a PhoneDB backed by a temp file."""
    db_path = tmp_path / "phone_test.db"
    with patch("content.scenes.phone.phone_db._DB_PATH", db_path):
        return PhoneDB(db_path=db_path)


# ══════════════════════════════════════════════════════════════════════
#  Thread management
# ══════════════════════════════════════════════════════════════════════

class TestThreadManagement:
    def test_create_dm_thread(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        assert isinstance(tid, str)
        assert len(tid) > 0

    def test_get_or_create_dm_idempotent(self, phone_db):
        t1 = phone_db.get_or_create_dm("bob")
        t2 = phone_db.get_or_create_dm("bob")
        assert t1 == t2

    def test_different_chars_different_threads(self, phone_db):
        t1 = phone_db.get_or_create_dm("alice")
        t2 = phone_db.get_or_create_dm("bob")
        assert t1 != t2

    def test_create_group_thread(self, phone_db):
        tid = phone_db.create_group("Party", ["alice", "bob"])
        assert isinstance(tid, str)

    def test_group_thread_members(self, phone_db):
        tid = phone_db.create_group("Team", ["alice", "bob"])
        members = phone_db.get_thread_members(tid)
        assert "user" in members
        assert "alice" in members
        assert "bob" in members

    def test_dm_thread_members(self, phone_db):
        tid = phone_db.get_or_create_dm("charlie")
        members = phone_db.get_thread_members(tid)
        assert "user" in members
        assert "charlie" in members

    def test_list_threads_empty(self, phone_db):
        threads = phone_db.list_threads()
        assert threads == []

    def test_list_threads_after_dm(self, phone_db):
        phone_db.get_or_create_dm("alice")
        threads = phone_db.list_threads()
        assert len(threads) == 1
        assert threads[0]["type"] == "dm"

    def test_get_thread(self, phone_db):
        tid = phone_db.get_or_create_dm("eve")
        t = phone_db.get_thread(tid)
        assert t is not None
        assert t["id"] == tid
        assert t["type"] == "dm"

    def test_get_thread_nonexistent(self, phone_db):
        t = phone_db.get_thread("nonexistent-id")
        assert t is None


# ══════════════════════════════════════════════════════════════════════
#  Message send / receive
# ══════════════════════════════════════════════════════════════════════

class TestMessages:
    def test_save_message(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        msg = phone_db.save_message(tid, "user", "Hello!")
        assert msg["thread_id"] == tid
        assert msg["sender_id"] == "user"
        assert msg["content"] == "Hello!"
        assert msg["msg_type"] == "text"
        assert msg["status"] == "sent"
        assert "id" in msg

    def test_get_messages_returns_saved(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        phone_db.save_message(tid, "user", "Hi Alice")
        phone_db.save_message(tid, "alice", "Hi there!")
        msgs = phone_db.get_messages(tid)
        assert len(msgs) == 2
        assert msgs[0]["content"] == "Hi Alice"
        assert msgs[1]["content"] == "Hi there!"

    def test_get_messages_limit(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        for i in range(10):
            phone_db.save_message(tid, "user", f"msg {i}")
        msgs = phone_db.get_messages(tid, limit=3)
        assert len(msgs) == 3

    def test_get_messages_before_pagination(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        for i in range(5):
            phone_db.save_message(tid, "user", f"msg {i}")
        all_msgs = phone_db.get_messages(tid, limit=50)
        # Get messages before the 3rd message's timestamp
        before_ts = all_msgs[2]["created_at"]
        older = phone_db.get_messages(tid, limit=50, before=before_ts)
        assert len(older) == 2  # msg 0, msg 1

    def test_message_with_metadata(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        meta = {"mood": "happy", "custom": True}
        msg = phone_db.save_message(tid, "alice", "I'm happy!", metadata=meta)
        assert msg["metadata"] == meta
        msgs = phone_db.get_messages(tid)
        assert msgs[0]["metadata"]["mood"] == "happy"

    def test_message_types(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        for mtype in ("text", "photo", "voice", "system", "game"):
            msg = phone_db.save_message(tid, "user", f"{mtype} content", msg_type=mtype)
            assert msg["msg_type"] == mtype

    def test_message_with_response_id(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        phone_db.save_message(tid, "alice", "reply", response_id="resp-123",
                              conversation_id="conv-1")
        last_rid = phone_db.get_last_response_id(tid)
        assert last_rid == "resp-123"

    def test_last_response_id_none_when_empty(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        phone_db.save_message(tid, "user", "hi")  # no response_id
        assert phone_db.get_last_response_id(tid) is None


# ══════════════════════════════════════════════════════════════════════
#  Read receipts / unread tracking
# ══════════════════════════════════════════════════════════════════════

class TestReadReceipts:
    def test_thread_unread_all(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        phone_db.save_message(tid, "alice", "m1")
        phone_db.save_message(tid, "alice", "m2")
        assert phone_db.thread_unread(tid) == 2

    def test_thread_unread_after_mark_read(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        phone_db.save_message(tid, "alice", "m1")
        phone_db.mark_read(tid)
        assert phone_db.thread_unread(tid) == 0

    def test_unread_after_new_message(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        phone_db.save_message(tid, "alice", "m1")
        phone_db.mark_read(tid)
        phone_db.save_message(tid, "alice", "m2")
        assert phone_db.thread_unread(tid) == 1

    def test_user_messages_not_counted_as_unread(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        phone_db.save_message(tid, "user", "hi")
        assert phone_db.thread_unread(tid) == 0

    def test_total_unread(self, phone_db):
        t1 = phone_db.get_or_create_dm("alice")
        t2 = phone_db.get_or_create_dm("bob")
        phone_db.save_message(t1, "alice", "a")
        phone_db.save_message(t2, "bob", "b")
        assert phone_db.total_unread() >= 2


# ══════════════════════════════════════════════════════════════════════
#  Game sessions (truth or dare)
# ══════════════════════════════════════════════════════════════════════

class TestGameSessions:
    def test_create_game_session(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        gid = phone_db.create_game_session(tid, "alice")
        assert isinstance(gid, str)

    def test_get_game_session(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        gid = phone_db.create_game_session(tid, "alice")
        session = phone_db.get_game_session(tid)
        assert session is not None
        assert session["id"] == gid
        assert session["character_id"] == "alice"
        assert session["active"] == 1

    def test_game_session_initial_state(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        phone_db.create_game_session(tid, "alice")
        session = phone_db.get_game_session(tid)
        state = session["state"]
        assert state["round"] == 0
        assert state["score"] == 0

    def test_update_game_state(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        gid = phone_db.create_game_session(tid, "alice")
        new_state = {"round": 3, "score": 10, "history": ["a", "b", "c"]}
        phone_db.update_game_state(gid, new_state)
        session = phone_db.get_game_session(tid)
        assert session["state"]["round"] == 3
        assert session["state"]["score"] == 10

    def test_end_game_session(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        gid = phone_db.create_game_session(tid, "alice")
        phone_db.end_game_session(gid)
        session = phone_db.get_game_session(tid)
        assert session is None  # no active session

    def test_new_session_deactivates_old(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        gid1 = phone_db.create_game_session(tid, "alice")
        gid2 = phone_db.create_game_session(tid, "alice")
        session = phone_db.get_game_session(tid)
        assert session["id"] == gid2  # latest one

    def test_no_active_session(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        assert phone_db.get_game_session(tid) is None


# ══════════════════════════════════════════════════════════════════════
#  Truth or Dare helpers
# ══════════════════════════════════════════════════════════════════════

class TestTruthOrDare:
    def test_get_truth_returns_string(self):
        truth = get_truth()
        assert isinstance(truth, str)
        assert len(truth) > 0

    def test_get_dare_returns_string(self):
        dare = get_dare()
        assert isinstance(dare, str)
        assert len(dare) > 0

    def test_truths_vary(self):
        """get_truth is random — over many calls we should see variation."""
        results = {get_truth() for _ in range(50)}
        assert len(results) > 1

    def test_dares_vary(self):
        results = {get_dare() for _ in range(50)}
        assert len(results) > 1


# ══════════════════════════════════════════════════════════════════════
#  Wipe messages
# ══════════════════════════════════════════════════════════════════════

class TestWipe:
    def test_wipe_messages(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        phone_db.save_message(tid, "user", "hello")
        phone_db.save_message(tid, "alice", "hi")
        count = phone_db.wipe_messages()
        assert count == 2
        msgs = phone_db.get_messages(tid)
        assert len(msgs) == 0


# ══════════════════════════════════════════════════════════════════════
#  Edge cases
# ══════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_scene_id(self):
        assert SCENE_ID == "phone"

    def test_empty_content_message(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        msg = phone_db.save_message(tid, "user", "")
        assert msg["content"] == ""

    def test_special_characters_in_message(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        content = "Hello 🎮 <script>alert('xss')</script> \"quotes\" 'single'"
        msg = phone_db.save_message(tid, "user", content)
        msgs = phone_db.get_messages(tid)
        assert msgs[0]["content"] == content

    def test_metadata_json_roundtrip(self, phone_db):
        tid = phone_db.get_or_create_dm("alice")
        meta = {"nested": {"key": [1, 2, 3]}, "flag": True}
        phone_db.save_message(tid, "user", "test", metadata=meta)
        msgs = phone_db.get_messages(tid)
        assert msgs[0]["metadata"]["nested"]["key"] == [1, 2, 3]

    def test_multiple_groups(self, phone_db):
        t1 = phone_db.create_group("G1", ["alice"])
        t2 = phone_db.create_group("G2", ["bob"])
        assert t1 != t2
        threads = phone_db.list_threads()
        assert len(threads) == 2
