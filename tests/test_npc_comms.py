"""Unit tests for the NPC↔NPC hybrid messaging scheduler (CB-T3).

Covers pair selection (distinct, no immediate repeats), hybrid routing
(ambient→template with NO agent call; important→agent requested), comms-log
write-through on channel ``npc_dm`` with the right thread id, and stable
npc_dm thread get-or-create per pair.

Uses an isolated temp ``GlobalCommsLog`` and a fake PhoneDB so no real data is
touched and no LMStudio call is made unless explicitly mocked.

Version: v1.62.0 [2026-06-15]
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from engine.world.comms_log import GlobalCommsLog
from engine.world.npc_comms import NPCCommsScheduler, TEMPLATE_POOL


# ── fakes ───────────────────────────────────────────────────────────────


class _FakePhoneDB:
    """Minimal PhoneDB stand-in recording npc_dm thread + message calls."""

    def __init__(self) -> None:
        self.threads: Dict[str, Dict[str, Any]] = {}
        self.messages: List[Dict[str, Any]] = []
        self.phones: set = set()

    @staticmethod
    def npc_pair_thread_id(a: str, b: str) -> str:
        lo, hi = sorted((a, b))
        return f"npc_dm:{lo}:{hi}"

    def get_or_create_npc_dm(self, a: str, b: str) -> str:
        tid = self.npc_pair_thread_id(a, b)
        if tid not in self.threads:
            self.threads[tid] = {"type": "npc_dm", "members": sorted((a, b))}
        return tid

    def mark_npc_phone(self, char_id: str, enabled: bool = True) -> None:
        self.phones.add(char_id)

    def save_message(self, thread_id: str, sender_id: str, content: str,
                     metadata: Optional[Dict] = None, **_kw) -> Dict[str, Any]:
        m = {"thread_id": thread_id, "sender_id": sender_id,
             "content": content, "metadata": metadata or {}}
        self.messages.append(m)
        return m


class _FakeDB:
    """Main-DB stand-in with controllable per-pair affinity."""

    def __init__(self, affinity: float = 0.5,
                 chars: Optional[List[str]] = None) -> None:
        self._affinity = affinity
        self._chars = chars or ["lola", "viktor", "aria", "frankie"]

    def get_all_characters(self) -> List[Dict[str, str]]:
        return [{"id": c} for c in self._chars]

    def get_relationship(self, a: str, b: str) -> Dict[str, Any]:
        return {"relationship_level": self._affinity}

    def get_character(self, cid: str) -> Dict[str, str]:
        return {"id": cid, "name": cid.capitalize(), "personality": "tough"}


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def comms_log(tmp_path) -> GlobalCommsLog:
    return GlobalCommsLog(path=tmp_path / "comms_log.db")


def _make_scheduler(comms_log: GlobalCommsLog, *, affinity: float = 0.5,
                    chars: Optional[List[str]] = None) -> NPCCommsScheduler:
    return NPCCommsScheduler(
        phone_db=_FakePhoneDB(),
        db=_FakeDB(affinity=affinity, chars=chars),
        comms_log=comms_log,
        emit=lambda evt, payload: None,
    )


# ── pair selection ──────────────────────────────────────────────────────


def test_select_pairs_returns_distinct_valid_pairs(comms_log) -> None:
    sched = _make_scheduler(comms_log)
    npcs = ["lola", "viktor", "aria", "frankie"]
    pairs = sched.select_pairs(npcs, 3)
    assert 1 <= len(pairs) <= 3
    seen = set()
    for a, b in pairs:
        assert a != b                      # no self-pairs
        assert a in npcs and b in npcs     # valid members
        key = tuple(sorted((a, b)))
        assert key not in seen             # distinct within the tick
        seen.add(key)


def test_select_pairs_avoids_immediate_repeats(comms_log) -> None:
    sched = _make_scheduler(comms_log)
    npcs = ["lola", "viktor", "aria", "frankie"]
    # Run a couple of exchanges to populate the recent-pair memory.
    first = sched.select_pairs(npcs, 1)[0]
    sched._remember_pair(*first)
    # With other options available, the heavily-penalised recent pair should
    # rarely be chosen again immediately. Verify across repeated draws.
    recent_key = tuple(sorted(first))
    repeats = 0
    for _ in range(40):
        a, b = sched.select_pairs(npcs, 1)[0]
        if tuple(sorted((a, b))) == recent_key:
            repeats += 1
    # The penalty (0.2x) plus alternatives should keep repeats a small minority.
    assert repeats < 20


# ── hybrid routing ──────────────────────────────────────────────────────


def test_ambient_exchange_uses_template_and_no_agent(comms_log, monkeypatch) -> None:
    # Low affinity → not important → ambient → template, never the LLM path.
    sched = _make_scheduler(comms_log, affinity=0.2)
    called = {"llm": False}

    def _spy_llm(a, b):
        called["llm"] = True
        return "SHOULD NOT BE USED"

    monkeypatch.setattr(sched, "_llm_line", _spy_llm)
    result = sched.run_exchange("lola", "viktor")

    assert result["generated"] == "template"
    assert called["llm"] is False
    all_templates = [t for pool in TEMPLATE_POOL.values() for t in pool]
    assert result["content"] in all_templates


def test_important_exchange_requests_agent(comms_log, monkeypatch) -> None:
    # High affinity → important; force the llm_chance roll to fire.
    sched = _make_scheduler(comms_log, affinity=0.9)
    sched._llm_chance = 1.0
    called = {"llm": 0}

    def _spy_llm(a, b):
        called["llm"] += 1
        return "live generated line"

    monkeypatch.setattr(sched, "_llm_line", _spy_llm)
    result = sched.run_exchange("lola", "viktor")

    assert called["llm"] == 1
    assert result["generated"] == "llm"
    assert result["content"] == "live generated line"


def test_llm_failure_falls_back_to_template(comms_log, monkeypatch) -> None:
    sched = _make_scheduler(comms_log, affinity=0.9)
    sched._llm_chance = 1.0
    monkeypatch.setattr(sched, "_llm_line", lambda a, b: None)  # simulate LMStudio down
    result = sched.run_exchange("lola", "viktor")
    assert result["generated"] == "template"
    all_templates = [t for pool in TEMPLATE_POOL.values() for t in pool]
    assert result["content"] in all_templates


# ── comms-log write-through ─────────────────────────────────────────────


def test_exchange_writes_comms_log_entry(comms_log) -> None:
    sched = _make_scheduler(comms_log, affinity=0.2)
    result = sched.run_exchange("aria", "frankie")
    expected_thread = _FakePhoneDB.npc_pair_thread_id("aria", "frankie")

    entries = comms_log.query(channel="npc_dm", limit=10)
    assert len(entries) == 1
    e = entries[0]
    assert e["channel"] == "npc_dm"
    assert e["sender_id"] == "aria"
    assert e["recipient_ids"] == ["frankie"]
    assert e["thread_id"] == expected_thread == result["thread_id"]
    assert e["metadata"]["generated"] == "template"


def test_exchange_persists_into_npc_dm_phone_thread(comms_log) -> None:
    fake_phone = _FakePhoneDB()
    sched = NPCCommsScheduler(
        phone_db=fake_phone, db=_FakeDB(affinity=0.2),
        comms_log=comms_log, emit=lambda e, p: None,
    )
    sched.run_exchange("lola", "aria")
    tid = _FakePhoneDB.npc_pair_thread_id("lola", "aria")
    assert tid in fake_phone.threads
    assert len(fake_phone.messages) == 1
    assert fake_phone.messages[0]["thread_id"] == tid
    assert fake_phone.messages[0]["sender_id"] == "lola"
    # both NPCs marked phone-enabled
    assert "lola" in fake_phone.phones and "aria" in fake_phone.phones


# ── stable thread id ────────────────────────────────────────────────────


def test_npc_dm_thread_id_is_stable_per_pair(comms_log) -> None:
    sched = _make_scheduler(comms_log)
    pdb = sched._get_phone_db()
    t1 = pdb.npc_pair_thread_id("lola", "viktor")
    t2 = pdb.npc_pair_thread_id("viktor", "lola")  # reversed order
    assert t1 == t2  # order-independent
    g1 = pdb.get_or_create_npc_dm("lola", "viktor")
    g2 = pdb.get_or_create_npc_dm("viktor", "lola")
    assert g1 == g2 == t1


def test_tick_writes_exchanges(comms_log) -> None:
    sched = _make_scheduler(comms_log, affinity=0.2)
    written = sched.tick()
    assert written >= 1
    assert comms_log.count() == written
