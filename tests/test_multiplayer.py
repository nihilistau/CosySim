"""Tests for Phase 6 — Multiplayer subsystem.

Covers SessionManager, PlayerSessionState, PresenceTracker,
MessageStore, Leaderboard, and Multiplayer MCP skills.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest


# ════════════════════════════════════════════════════════════════════════════
# Session Manager
# ════════════════════════════════════════════════════════════════════════════


class TestPlayerSession:
    """PlayerSession dataclass."""

    def test_to_dict(self):
        from engine.multiplayer.session_manager import PlayerSession
        s = PlayerSession(
            session_id="sid-1", player_id="p1", display_name="Alice",
        )
        d = s.to_dict()
        assert d["session_id"] == "sid-1"
        assert d["player_id"] == "p1"
        assert d["display_name"] == "Alice"
        assert d["status"] == "online"
        assert "uptime_seconds" in d

    def test_defaults(self):
        from engine.multiplayer.session_manager import PlayerSession, PlayerStatus
        s = PlayerSession(session_id="s", player_id="p", display_name="X")
        assert s.status == PlayerStatus.ONLINE
        assert s.connected_scene is None
        assert s.socket_sid is None


class TestPlayerSessionState:
    """PlayerSessionState — per-player isolated state."""

    def test_earn_credits(self):
        from engine.multiplayer.session_manager import PlayerSessionState
        st = PlayerSessionState(player_id="p1")
        assert st.earn_credits(500, "test") == 1500
        assert st.stats["total_earned"] == 500

    def test_spend_credits_success(self):
        from engine.multiplayer.session_manager import PlayerSessionState
        st = PlayerSessionState(player_id="p1", credits=1000)
        assert st.spend_credits(300, "buy") is True
        assert st.credits == 700

    def test_spend_credits_insufficient(self):
        from engine.multiplayer.session_manager import PlayerSessionState
        st = PlayerSessionState(player_id="p1", credits=100)
        assert st.spend_credits(500) is False
        assert st.credits == 100

    def test_add_remove_item(self):
        from engine.multiplayer.session_manager import PlayerSessionState
        st = PlayerSessionState(player_id="p1")
        st.add_item({"id": "sword", "name": "Plasma Sword"})
        assert len(st.inventory) == 1
        assert st.remove_item("sword") is True
        assert len(st.inventory) == 0
        assert st.remove_item("nonexistent") is False

    def test_adjust_reputation(self):
        from engine.multiplayer.session_manager import PlayerSessionState
        st = PlayerSessionState(player_id="p1")
        assert st.adjust_reputation(50) == 50
        assert st.adjust_reputation(-20) == 30

    def test_adjust_heat_clamped(self):
        from engine.multiplayer.session_manager import PlayerSessionState
        st = PlayerSessionState(player_id="p1")
        st.adjust_heat(200)
        assert st.heat == 100
        st.adjust_heat(-300)
        assert st.heat == 0

    def test_increment_stat(self):
        from engine.multiplayer.session_manager import PlayerSessionState
        st = PlayerSessionState(player_id="p1")
        assert st.increment_stat("kills", 3) == 3
        assert st.increment_stat("kills") == 4

    def test_to_dict(self):
        from engine.multiplayer.session_manager import PlayerSessionState
        st = PlayerSessionState(player_id="p1")
        d = st.to_dict()
        assert d["player_id"] == "p1"
        assert d["credits"] == 1000
        assert "stats" in d
        assert "faction_standings" in d

    def test_default_faction_standings(self):
        from engine.multiplayer.session_manager import PlayerSessionState
        st = PlayerSessionState(player_id="p1")
        assert len(st.faction_standings) == 6
        assert "OmniCorp" in st.faction_standings


class TestSessionManager:
    """SessionManager lifecycle."""

    @pytest.fixture
    def sm(self):
        from engine.multiplayer.session_manager import SessionManager
        return SessionManager(heartbeat_timeout=5.0)

    def test_create_session(self, sm):
        s = sm.create_session("p1", "Alice")
        assert s.player_id == "p1"
        assert s.display_name == "Alice"
        assert sm.session_count == 1

    def test_create_replaces_existing(self, sm):
        s1 = sm.create_session("p1", "Alice")
        s2 = sm.create_session("p1", "Alice v2")
        assert sm.session_count == 1
        assert s2.display_name == "Alice v2"
        assert sm.get_session(s1.session_id) is None

    def test_destroy_session(self, sm):
        s = sm.create_session("p1", "Alice")
        assert sm.destroy_session(s.session_id) is True
        assert sm.session_count == 0
        assert sm.destroy_session(s.session_id) is False

    def test_get_session_by_player(self, sm):
        sm.create_session("p1", "Alice")
        s = sm.get_session_by_player("p1")
        assert s is not None
        assert s.player_id == "p1"
        assert sm.get_session_by_player("nobody") is None

    def test_get_state(self, sm):
        s = sm.create_session("p1", "Alice")
        state = sm.get_state(s.session_id)
        assert state is not None
        assert state.player_id == "p1"
        assert state.credits == 1000

    def test_heartbeat(self, sm):
        s = sm.create_session("p1", "Alice")
        assert sm.heartbeat(s.session_id) is True
        assert sm.heartbeat("nonexistent") is False

    def test_set_scene(self, sm):
        s = sm.create_session("p1", "Alice")
        assert sm.set_scene(s.session_id, "bedroom") is True
        assert s.connected_scene == "bedroom"
        state = sm.get_state(s.session_id)
        assert state.active_location == "bedroom"

    def test_set_status(self, sm):
        from engine.multiplayer.session_manager import PlayerStatus
        s = sm.create_session("p1", "Alice")
        sm.set_status(s.session_id, PlayerStatus.BUSY)
        assert s.status == PlayerStatus.BUSY

    def test_cleanup_stale(self, sm):
        s = sm.create_session("p1", "Alice")
        s.last_heartbeat = time.time() - 100
        stale = sm.cleanup_stale()
        assert len(stale) == 1
        assert sm.session_count == 0

    def test_cleanup_keeps_active(self, sm):
        sm.create_session("p1", "Alice")
        sm.create_session("p2", "Bob")
        stale = sm.cleanup_stale()
        assert len(stale) == 0
        assert sm.session_count == 2

    def test_list_sessions(self, sm):
        sm.create_session("p1", "Alice")
        sm.create_session("p2", "Bob")
        sessions = sm.list_sessions()
        assert len(sessions) == 2

    def test_list_online_players(self, sm):
        from engine.multiplayer.session_manager import PlayerStatus
        s1 = sm.create_session("p1", "Alice")
        s2 = sm.create_session("p2", "Bob")
        sm.set_status(s2.session_id, PlayerStatus.OFFLINE)
        online = sm.list_online_players()
        assert len(online) == 1
        assert online[0]["player_id"] == "p1"

    def test_get_players_in_scene(self, sm):
        s1 = sm.create_session("p1", "Alice")
        s2 = sm.create_session("p2", "Bob")
        sm.set_scene(s1.session_id, "bedroom")
        sm.set_scene(s2.session_id, "bedroom")
        players = sm.get_players_in_scene("bedroom")
        assert len(players) == 2

    def test_stats(self, sm):
        sm.create_session("p1", "Alice")
        sm.set_scene(sm.get_session_by_player("p1").session_id, "bedroom")
        stats = sm.get_stats()
        assert stats["total_sessions"] == 1
        assert "bedroom" in stats["by_scene"]

    def test_reset(self, sm):
        sm.create_session("p1", "Alice")
        sm.reset()
        assert sm.session_count == 0


class TestSessionSingleton:
    """Singleton behavior."""

    def test_singleton(self):
        from engine.multiplayer.session_manager import (
            get_session_manager, reset_session_manager,
        )
        reset_session_manager()
        a = get_session_manager()
        b = get_session_manager()
        assert a is b
        reset_session_manager()


# ════════════════════════════════════════════════════════════════════════════
# Presence Tracker
# ════════════════════════════════════════════════════════════════════════════


class TestPresenceTracker:
    """PresenceTracker lifecycle and events."""

    @pytest.fixture(autouse=True)
    def setup_presence(self):
        from engine.multiplayer.session_manager import reset_session_manager
        from engine.multiplayer.presence import PresenceTracker
        reset_session_manager()
        self.pt = PresenceTracker()
        yield
        reset_session_manager()

    def test_connect(self):
        result = self.pt.player_connected("p1", "Alice")
        assert result["player_id"] == "p1"
        assert self.pt.get_online_count() == 1

    def test_disconnect(self):
        result = self.pt.player_connected("p1", "Alice")
        sid = result["session_id"]
        assert self.pt.player_disconnected(sid) is True
        assert self.pt.get_online_count() == 0

    def test_disconnect_nonexistent(self):
        assert self.pt.player_disconnected("fake") is False

    def test_join_scene(self):
        result = self.pt.player_connected("p1", "Alice")
        sid = result["session_id"]
        assert self.pt.player_joined_scene(sid, "bedroom") is True
        players = self.pt.get_scene_occupancy("bedroom")
        assert len(players) == 1

    def test_scene_transition(self):
        result = self.pt.player_connected("p1", "Alice")
        sid = result["session_id"]
        self.pt.player_joined_scene(sid, "bedroom")
        self.pt.player_joined_scene(sid, "neoncity")
        assert len(self.pt.get_scene_occupancy("bedroom")) == 0
        assert len(self.pt.get_scene_occupancy("neoncity")) == 1

    def test_leave_scene(self):
        result = self.pt.player_connected("p1", "Alice")
        sid = result["session_id"]
        self.pt.player_joined_scene(sid, "bedroom")
        assert self.pt.player_left_scene(sid) is True
        assert len(self.pt.get_scene_occupancy("bedroom")) == 0

    def test_set_status(self):
        result = self.pt.player_connected("p1", "Alice")
        sid = result["session_id"]
        assert self.pt.set_status(sid, "busy") is True
        assert self.pt.set_status(sid, "invalid") is False

    def test_get_player_scene(self):
        result = self.pt.player_connected("p1", "Alice")
        sid = result["session_id"]
        self.pt.player_joined_scene(sid, "casino")
        assert self.pt.get_player_scene("p1") == "casino"
        assert self.pt.get_player_scene("nobody") is None

    def test_get_all_presence(self):
        r1 = self.pt.player_connected("p1", "Alice")
        r2 = self.pt.player_connected("p2", "Bob")
        self.pt.player_joined_scene(r1["session_id"], "bedroom")
        self.pt.player_joined_scene(r2["session_id"], "bedroom")
        pres = self.pt.get_all_presence()
        assert "bedroom" in pres
        assert len(pres["bedroom"]) == 2

    def test_recent_events(self):
        self.pt.player_connected("p1", "Alice")
        events = self.pt.get_recent_events(limit=5)
        assert len(events) >= 1
        assert events[0]["event_type"] == "connect"

    def test_stats(self):
        self.pt.player_connected("p1", "Alice")
        stats = self.pt.get_stats()
        assert stats["online_players"] == 1


class TestPresenceEvent:
    """PresenceEvent dataclass."""

    def test_to_dict(self):
        from engine.multiplayer.presence import PresenceEvent
        e = PresenceEvent(player_id="p1", event_type="connect")
        d = e.to_dict()
        assert d["player_id"] == "p1"
        assert d["event_type"] == "connect"


# ════════════════════════════════════════════════════════════════════════════
# Messaging
# ════════════════════════════════════════════════════════════════════════════


class TestMessage:
    """Message dataclass."""

    def test_to_dict(self):
        from engine.multiplayer.messaging import Message
        m = Message(message_id="m1", sender_id="p1", receiver_id="p2",
                    content="Hello!")
        d = m.to_dict()
        assert d["sender_id"] == "p1"
        assert d["receiver_id"] == "p2"
        assert d["content"] == "Hello!"
        assert d["read"] is False

    def test_thread_id_deterministic(self):
        from engine.multiplayer.messaging import Message
        m1 = Message(message_id="x", sender_id="alice", receiver_id="bob",
                     content="hi")
        m2 = Message(message_id="y", sender_id="bob", receiver_id="alice",
                     content="hey")
        assert m1.thread_id == m2.thread_id


class TestMessageStore:
    """MessageStore send/receive/threading."""

    @pytest.fixture
    def store(self):
        from engine.multiplayer.messaging import MessageStore
        return MessageStore()

    def test_send(self, store):
        msg = store.send("p1", "p2", "Hello!")
        assert msg.sender_id == "p1"
        assert msg.receiver_id == "p2"

    def test_get_thread(self, store):
        store.send("p1", "p2", "Hello!")
        store.send("p2", "p1", "Hey!")
        thread = store.get_thread("p1", "p2")
        assert len(thread) == 2

    def test_thread_order(self, store):
        store.send("p1", "p2", "First")
        store.send("p2", "p1", "Second")
        thread = store.get_thread("p1", "p2")
        assert thread[0]["content"] == "First"
        assert thread[1]["content"] == "Second"

    def test_get_unread(self, store):
        store.send("p1", "p2", "Hello!")
        store.send("p1", "p2", "Follow up")
        unread = store.get_unread("p2")
        assert len(unread) == 2

    def test_unread_count(self, store):
        store.send("p1", "p2", "Hello!")
        store.send("p3", "p2", "Hey!")
        assert store.unread_count("p2") == 2
        assert store.unread_count("p1") == 0

    def test_mark_read_all(self, store):
        store.send("p1", "p2", "Hello!")
        store.send("p3", "p2", "Hey!")
        marked = store.mark_read("p2")
        assert marked == 2
        assert store.unread_count("p2") == 0

    def test_mark_read_specific_thread(self, store):
        store.send("p1", "p2", "Hello!")
        store.send("p3", "p2", "Hey!")
        marked = store.mark_read("p2", thread_partner="p1")
        assert marked == 1
        assert store.unread_count("p2") == 1

    def test_get_conversations(self, store):
        store.send("p1", "p2", "Hello!")
        store.send("p3", "p2", "Hey!")
        convos = store.get_conversations("p2")
        assert len(convos) == 2
        for c in convos:
            assert "partner_id" in c
            assert "unread_count" in c

    def test_delete_thread(self, store):
        store.send("p1", "p2", "Hello!")
        assert store.delete_thread("p1", "p2") is True
        assert len(store.get_thread("p1", "p2")) == 0
        assert store.delete_thread("p1", "p2") is False

    def test_thread_limit(self):
        from engine.multiplayer.messaging import MessageStore
        store = MessageStore(max_messages_per_thread=5)
        for i in range(10):
            store.send("p1", "p2", f"msg-{i}")
        thread = store.get_thread("p1", "p2")
        assert len(thread) == 5

    def test_stats(self, store):
        store.send("p1", "p2", "Hello!")
        stats = store.get_stats()
        assert stats["total_threads"] == 1
        assert stats["total_sent"] == 1

    def test_reset(self, store):
        store.send("p1", "p2", "Hello!")
        store.reset()
        assert store.get_stats()["total_threads"] == 0


class TestMessageSingleton:
    """Singleton behavior."""

    def test_singleton(self):
        from engine.multiplayer.messaging import (
            get_message_store, reset_message_store,
        )
        reset_message_store()
        a = get_message_store()
        b = get_message_store()
        assert a is b
        reset_message_store()


# ════════════════════════════════════════════════════════════════════════════
# Leaderboards
# ════════════════════════════════════════════════════════════════════════════


class TestLeaderboard:
    """Leaderboard scoring and ranking."""

    @pytest.fixture
    def lb(self):
        from engine.multiplayer.leaderboards import Leaderboard
        return Leaderboard()

    def test_update_score(self, lb):
        lb.update_score("credits", "p1", "Alice", 5000)
        top = lb.get_top("credits")
        assert len(top) == 1
        assert top[0]["score"] == 5000

    def test_ranking_order(self, lb):
        lb.update_score("credits", "p1", "Alice", 5000)
        lb.update_score("credits", "p2", "Bob", 8000)
        lb.update_score("credits", "p3", "Carol", 3000)
        top = lb.get_top("credits")
        assert top[0]["display_name"] == "Bob"
        assert top[0]["rank"] == 1
        assert top[1]["display_name"] == "Alice"
        assert top[2]["display_name"] == "Carol"

    def test_get_rank(self, lb):
        lb.update_score("credits", "p1", "Alice", 5000)
        lb.update_score("credits", "p2", "Bob", 8000)
        rank = lb.get_rank("credits", "p1")
        assert rank is not None
        assert rank["rank"] == 2

    def test_get_rank_nonexistent(self, lb):
        assert lb.get_rank("credits", "nobody") is None

    def test_unknown_category(self, lb):
        lb.update_score("fake_category", "p1", "Alice", 100)
        top = lb.get_top("fake_category")
        assert len(top) == 0

    def test_update_from_session_state(self, lb):
        state_dict = {
            "credits": 5000,
            "reputation": 200,
            "stats": {
                "kills": 10,
                "heists_completed": 5,
                "hacks_completed": 3,
            },
        }
        updated = lb.update_from_session_state("p1", "Alice", state_dict)
        assert updated >= 4
        assert lb.get_top("credits")[0]["score"] == 5000
        assert lb.get_top("kills")[0]["score"] == 10

    def test_player_scores(self, lb):
        lb.update_score("credits", "p1", "Alice", 5000)
        lb.update_score("reputation", "p1", "Alice", 200)
        scores = lb.get_player_scores("p1")
        assert scores["credits"]["score"] == 5000
        assert scores["credits"]["rank"] == 1

    def test_weekly_separate(self, lb):
        lb.update_score("credits", "p1", "Alice", 5000)
        weekly_top = lb.get_top("credits", weekly=True)
        alltime_top = lb.get_top("credits", weekly=False)
        assert len(weekly_top) == 1
        assert len(alltime_top) == 1

    def test_top_limit(self, lb):
        for i in range(20):
            lb.update_score("credits", f"p{i}", f"Player{i}", i * 100)
        top5 = lb.get_top("credits", limit=5)
        assert len(top5) == 5
        assert top5[0]["rank"] == 1

    def test_stats(self, lb):
        lb.update_score("credits", "p1", "Alice", 5000)
        stats = lb.get_stats()
        assert "credits" in stats["categories"]
        assert stats["alltime_players"]["credits"] == 1

    def test_reset(self, lb):
        lb.update_score("credits", "p1", "Alice", 5000)
        lb.reset()
        assert len(lb.get_top("credits")) == 0


class TestLeaderboardSingleton:
    """Singleton behavior."""

    def test_singleton(self):
        from engine.multiplayer.leaderboards import (
            get_leaderboard, reset_leaderboard,
        )
        reset_leaderboard()
        a = get_leaderboard()
        b = get_leaderboard()
        assert a is b
        reset_leaderboard()


# ════════════════════════════════════════════════════════════════════════════
# Multiplayer MCP Skills
# ════════════════════════════════════════════════════════════════════════════


class TestMultiplayerSkills:
    """Test multiplayer skill pack imports and basic invocations."""

    @pytest.fixture(autouse=True)
    def setup_multiplayer(self):
        from engine.multiplayer.session_manager import (
            get_session_manager, reset_session_manager,
        )
        from engine.multiplayer.messaging import reset_message_store
        from engine.multiplayer.leaderboards import reset_leaderboard
        reset_session_manager()
        reset_message_store()
        reset_leaderboard()

        sm = get_session_manager()
        s1 = sm.create_session("alice", "Alice")
        s2 = sm.create_session("bob", "Bob")
        sm.set_scene(s1.session_id, "bedroom")
        sm.set_scene(s2.session_id, "bedroom")
        yield
        reset_session_manager()
        reset_message_store()
        reset_leaderboard()

    def test_imports(self):
        from engine.skills.builtin import multiplayer_skills
        assert hasattr(multiplayer_skills, "who_is_here")
        assert hasattr(multiplayer_skills, "send_message")
        assert hasattr(multiplayer_skills, "leaderboard")

    def test_who_is_here(self):
        from engine.skills.builtin.multiplayer_skills import who_is_here
        result = who_is_here("bedroom")
        assert "Alice" in result
        assert "Bob" in result

    def test_who_is_here_empty(self):
        from engine.skills.builtin.multiplayer_skills import who_is_here
        result = who_is_here("empty_scene")
        assert "No players" in result

    def test_my_session(self):
        from engine.skills.builtin.multiplayer_skills import my_session
        result = my_session("alice")
        assert "Alice" in result
        assert "Credits" in result

    def test_my_session_not_found(self):
        from engine.skills.builtin.multiplayer_skills import my_session
        result = my_session("nobody")
        assert "no active session" in result

    def test_player_list(self):
        from engine.skills.builtin.multiplayer_skills import player_list
        result = player_list()
        assert "Alice" in result
        assert "Bob" in result

    def test_go_to_scene(self):
        from engine.skills.builtin.multiplayer_skills import go_to_scene
        result = go_to_scene("alice", "casino")
        assert "casino" in result

    def test_set_status(self):
        from engine.skills.builtin.multiplayer_skills import set_status
        result = set_status("alice", "busy")
        assert "busy" in result

    def test_send_message(self):
        from engine.skills.builtin.multiplayer_skills import send_message
        result = send_message("alice", "bob", "Hello Bob!")
        assert "sent" in result.lower()

    def test_send_message_not_connected(self):
        from engine.skills.builtin.multiplayer_skills import send_message
        result = send_message("nobody", "bob", "Hello")
        assert "not connected" in result

    def test_read_messages(self):
        from engine.multiplayer.messaging import get_message_store
        get_message_store().send("alice", "bob", "Test message")

        from engine.skills.builtin.multiplayer_skills import read_messages
        result = read_messages("bob")
        assert "Test message" in result

    def test_read_messages_empty(self):
        from engine.skills.builtin.multiplayer_skills import read_messages
        result = read_messages("alice")
        assert "No unread" in result

    def test_unread_count(self):
        from engine.multiplayer.messaging import get_message_store
        get_message_store().send("alice", "bob", "msg1")
        get_message_store().send("alice", "bob", "msg2")

        from engine.skills.builtin.multiplayer_skills import unread_count
        result = unread_count("bob")
        assert "2" in result

    def test_message_history(self):
        from engine.multiplayer.messaging import get_message_store
        get_message_store().send("alice", "bob", "Hello!")
        get_message_store().send("bob", "alice", "Hey!")

        from engine.skills.builtin.multiplayer_skills import message_history
        result = message_history("alice", "bob")
        assert "Hello!" in result
        assert "Hey!" in result

    def test_leaderboard_skill(self):
        from engine.multiplayer.leaderboards import get_leaderboard
        lb = get_leaderboard()
        lb.update_score("credits", "alice", "Alice", 5000)
        lb.update_score("credits", "bob", "Bob", 8000)

        from engine.skills.builtin.multiplayer_skills import leaderboard
        result = leaderboard("credits")
        assert "Bob" in result
        assert "Alice" in result
        assert "#1" in result

    def test_leaderboard_empty(self):
        from engine.skills.builtin.multiplayer_skills import leaderboard
        result = leaderboard("kills")
        assert "No scores" in result

    def test_my_rank(self):
        from engine.multiplayer.leaderboards import get_leaderboard
        get_leaderboard().update_score("credits", "alice", "Alice", 5000)

        from engine.skills.builtin.multiplayer_skills import my_rank
        result = my_rank("alice", "credits")
        assert "#1" in result

    def test_my_rank_not_ranked(self):
        from engine.skills.builtin.multiplayer_skills import my_rank
        result = my_rank("nobody", "credits")
        assert "Not ranked" in result

    def test_my_scores(self):
        from engine.multiplayer.leaderboards import get_leaderboard
        get_leaderboard().update_score("credits", "alice", "Alice", 5000)

        from engine.skills.builtin.multiplayer_skills import my_scores
        result = my_scores("alice")
        assert "credits" in result
