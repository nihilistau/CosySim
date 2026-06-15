"""Unit tests for the leave-a-message flow (CB-T4).

Covers the data layer (``PhoneDB.add_left_message`` /
``mark_message_delivered`` / ``clear_left_unread`` / ``get_pending_left_messages``),
the minimal :class:`~engine.world.presence.PresenceTracker`, and the
GlobalCommsLog ``kind='left_message'`` write-through performed by the
:class:`~engine.world.npc_comms.NPCCommsScheduler` when a recipient is offline.

All state is isolated: PhoneDB uses a temp sqlite path, the comms log uses an
explicit temp db, and presence is checked with monkeypatched co-presence so no
real city map / LMStudio is touched.

Version: v1.62.0 [2026-06-15]
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from content.scenes.phone.phone_db import PhoneDB
from engine.world.comms_log import GlobalCommsLog
from engine.world.npc_comms import NPCCommsScheduler
from engine.world.presence import PresenceTracker


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def phone_db(tmp_path) -> PhoneDB:
    """Return a PhoneDB backed by an isolated temp database."""
    return PhoneDB(db_path=tmp_path / "phone.db")


@pytest.fixture
def comms_log(tmp_path) -> GlobalCommsLog:
    """Return a GlobalCommsLog backed by an isolated temp database."""
    return GlobalCommsLog(path=tmp_path / "comms_log.db")


# ── data layer: persistence + flags ─────────────────────────────────────


def test_add_left_message_persists_flags(phone_db: PhoneDB) -> None:
    tid = phone_db.get_or_create_dm("aria")
    msg = phone_db.add_left_message(tid, "aria", "you up? left this for later")
    # Returned dict carries the flags.
    assert msg["metadata"]["left_unread"] is True
    assert msg["metadata"]["delivered"] is False
    # And they persist on read-back.
    stored = phone_db.get_messages(tid)
    assert len(stored) == 1
    assert stored[0]["metadata"]["left_unread"] is True
    assert stored[0]["metadata"]["delivered"] is False


def test_add_left_message_merges_extra_metadata(phone_db: PhoneDB) -> None:
    tid = phone_db.get_or_create_dm("viktor")
    msg = phone_db.add_left_message(tid, "viktor", "hey", metadata={"mood": "tense"})
    assert msg["metadata"]["mood"] == "tense"
    assert msg["metadata"]["left_unread"] is True
    assert msg["metadata"]["delivered"] is False


def test_mark_delivered_flips_delivered_keeps_left_unread(phone_db: PhoneDB) -> None:
    tid = phone_db.get_or_create_dm("aria")
    msg = phone_db.add_left_message(tid, "aria", "left for you")
    assert phone_db.mark_message_delivered(msg["id"]) is True
    stored = phone_db.get_messages(tid)[0]
    assert stored["metadata"]["delivered"] is True
    # left_unread is retained so the UI can still show "left you a message".
    assert stored["metadata"]["left_unread"] is True


def test_mark_delivered_unknown_id_returns_false(phone_db: PhoneDB) -> None:
    assert phone_db.mark_message_delivered("does-not-exist") is False


def test_clear_left_unread(phone_db: PhoneDB) -> None:
    tid = phone_db.get_or_create_dm("aria")
    msg = phone_db.add_left_message(tid, "aria", "left for you")
    assert phone_db.clear_left_unread(msg["id"]) is True
    stored = phone_db.get_messages(tid)[0]
    assert stored["metadata"]["left_unread"] is False


# ── data layer: pending query ───────────────────────────────────────────


def test_get_pending_left_messages_for_player(phone_db: PhoneDB) -> None:
    tid = phone_db.get_or_create_dm("aria")
    left = phone_db.add_left_message(tid, "aria", "left while you were away")
    # A normal (live) message must NOT be pending.
    phone_db.save_message(tid, "aria", "live message")
    pending = phone_db.get_pending_left_messages(recipient_id="user")
    assert [m["id"] for m in pending] == [left["id"]]


def test_pending_excludes_delivered(phone_db: PhoneDB) -> None:
    tid = phone_db.get_or_create_dm("aria")
    left = phone_db.add_left_message(tid, "aria", "left for you")
    phone_db.mark_message_delivered(left["id"])
    assert phone_db.get_pending_left_messages(recipient_id="user") == []


def test_pending_excludes_own_messages(phone_db: PhoneDB) -> None:
    # A message the PLAYER left (sender_id='user') is not pending FOR the player.
    tid = phone_db.get_or_create_dm("aria")
    phone_db.add_left_message(tid, "user", "I left this for aria")
    assert phone_db.get_pending_left_messages(recipient_id="user") == []
    # ...but it IS pending for aria (filtered by thread).
    pending_for_aria = phone_db.get_pending_left_messages(
        recipient_id="aria", thread_id=tid
    )
    assert len(pending_for_aria) == 1


def test_list_threads_surfaces_left_unread(phone_db: PhoneDB) -> None:
    tid = phone_db.get_or_create_dm("aria")
    phone_db.add_left_message(tid, "aria", "left you a message")
    threads = {t["id"]: t for t in phone_db.list_threads()}
    assert threads[tid]["left_unread"] == 1


# ── presence tracker ────────────────────────────────────────────────────


def test_presence_player_offline_when_no_clients() -> None:
    pres = PresenceTracker()
    # No clients connected → offline (default config).
    assert pres.is_player_online() is False
    pres.connect("sid-1")
    assert pres.is_player_online() is True
    pres.disconnect("sid-1")
    assert pres.is_player_online() is False


def test_presence_npc_co_presence(monkeypatch) -> None:
    pres = PresenceTracker()

    class _CM:
        def __init__(self, npc_loc: Optional[str]) -> None:
            self._npc_loc = npc_loc

        def get_npc_location(self, npc_id: str) -> Optional[str]:
            return self._npc_loc

    class _PS:
        active_location = "THE GRID"

    import engine.world.city_map as cm_mod

    # Co-present → online.
    monkeypatch.setattr(cm_mod, "get_city_map", lambda: _CM("THE GRID"))
    monkeypatch.setattr(cm_mod, "get_player_state", lambda: _PS())
    assert pres.is_npc_online("aria") is True

    # Elsewhere → offline.
    monkeypatch.setattr(cm_mod, "get_city_map", lambda: _CM("NEON ALLEY"))
    assert pres.is_npc_online("aria") is False


def test_presence_fails_open_on_unknown_location(monkeypatch) -> None:
    pres = PresenceTracker()

    class _CM:
        def get_npc_location(self, npc_id: str) -> Optional[str]:
            return None

    class _PS:
        active_location = None

    import engine.world.city_map as cm_mod
    monkeypatch.setattr(cm_mod, "get_city_map", lambda: _CM())
    monkeypatch.setattr(cm_mod, "get_player_state", lambda: _PS())
    # Unknown locations → treat as reachable (online).
    assert pres.is_npc_online("aria") is True


# ── npc scheduler: left_message write-through ────────────────────────────


class _FakePhoneDB:
    """Minimal PhoneDB stand-in recording left vs live messages."""

    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []
        self.left_messages: List[Dict[str, Any]] = []
        self.phones: set = set()
        self.threads: Dict[str, Any] = {}

    @staticmethod
    def npc_pair_thread_id(a: str, b: str) -> str:
        lo, hi = sorted((a, b))
        return f"npc_dm:{lo}:{hi}"

    def get_or_create_npc_dm(self, a: str, b: str) -> str:
        tid = self.npc_pair_thread_id(a, b)
        self.threads[tid] = {"members": sorted((a, b))}
        return tid

    def mark_npc_phone(self, char_id: str, enabled: bool = True) -> None:
        self.phones.add(char_id)

    def save_message(self, thread_id: str, sender_id: str, content: str,
                     metadata: Optional[Dict] = None, **_kw) -> Dict[str, Any]:
        m = {"thread_id": thread_id, "sender_id": sender_id,
             "content": content, "metadata": metadata or {}}
        self.messages.append(m)
        return m

    def add_left_message(self, thread_id: str, sender_id: str, content: str,
                         metadata: Optional[Dict] = None, **_kw) -> Dict[str, Any]:
        meta = dict(metadata or {})
        meta["left_unread"] = True
        meta["delivered"] = False
        m = {"thread_id": thread_id, "sender_id": sender_id,
             "content": content, "metadata": meta}
        self.left_messages.append(m)
        return m


class _FakeDB:
    def get_all_characters(self) -> List[Dict[str, str]]:
        return [{"id": "lola"}, {"id": "viktor"}]

    def get_relationship(self, a: str, b: str) -> Dict[str, Any]:
        return {"relationship_level": 0.2}

    def get_character(self, cid: str) -> Dict[str, str]:
        return {"id": cid, "name": cid.capitalize(), "personality": "tough"}


def _scheduler(comms_log: GlobalCommsLog, phone_db: _FakePhoneDB) -> NPCCommsScheduler:
    return NPCCommsScheduler(
        phone_db=phone_db, db=_FakeDB(), comms_log=comms_log,
        emit=lambda evt, payload: None,
    )


def test_npc_exchange_offline_recipient_is_left_message(comms_log, monkeypatch) -> None:
    fake = _FakePhoneDB()
    sched = _scheduler(comms_log, fake)
    # Recipient offline → left message.
    monkeypatch.setattr(sched, "_recipient_online", lambda a, b: False)
    result = sched.run_exchange("lola", "viktor")

    assert result["left_message"] is True
    # Stored as a left message (not a live save).
    assert len(fake.left_messages) == 1
    assert fake.left_messages[0]["metadata"]["left_unread"] is True
    assert fake.left_messages[0]["metadata"]["delivered"] is False
    assert fake.messages == []

    # GlobalCommsLog gets a kind='left_message' entry with left_unread metadata.
    entries = comms_log.query(channel="npc_dm", limit=10)
    assert len(entries) == 1
    assert entries[0]["kind"] == "left_message"
    assert entries[0]["metadata"]["left_unread"] is True


def test_npc_exchange_online_recipient_is_live(comms_log, monkeypatch) -> None:
    fake = _FakePhoneDB()
    sched = _scheduler(comms_log, fake)
    monkeypatch.setattr(sched, "_recipient_online", lambda a, b: True)
    result = sched.run_exchange("lola", "viktor")

    assert result["left_message"] is False
    assert len(fake.messages) == 1
    assert fake.left_messages == []
    entries = comms_log.query(channel="npc_dm", limit=10)
    assert entries[0]["kind"] == "message"
    assert "left_unread" not in entries[0]["metadata"]
