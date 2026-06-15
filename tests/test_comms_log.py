"""Unit tests for the GlobalCommsLog backbone (CB-T1).

Covers append/read semantics, all query filters, thread ordering, the
``about`` matcher, observation marking, prune capping, and concurrent-write
safety. Uses an explicit temp db path so no real data is touched.

Version: v1.62.0 [2026-06-15]
"""
from __future__ import annotations

import threading

import pytest

from engine.world.comms_log import GlobalCommsLog, get_comms_log


@pytest.fixture
def log(tmp_path) -> GlobalCommsLog:
    """Return a GlobalCommsLog backed by an isolated temp database."""
    return GlobalCommsLog(path=tmp_path / "comms_log.db")


# ── log() + persistence ───────────────────────────────────────────────


def test_log_returns_increasing_ids_and_persists(log: GlobalCommsLog) -> None:
    id1 = log.log("phone_dm", "char-aria", ["player"], "first")
    id2 = log.log("phone_dm", "char-aria", ["player"], "second")
    assert id1 > 0
    assert id2 > id1
    rows = log.recent(10)
    assert len(rows) == 2
    contents = {r["content"] for r in rows}
    assert contents == {"first", "second"}
    # json fields deserialized
    assert rows[0]["recipient_ids"] == ["player"]
    assert rows[0]["observed_by"] == []
    assert isinstance(rows[0]["metadata"], dict)


def test_log_stores_metadata_and_mood(log: GlobalCommsLog) -> None:
    rid = log.log(
        "npc_dm", "char-bex", ["char-aria"], "psst",
        kind="autotext", mood="sly", metadata={"intercepted": True},
    )
    row = log.recent(1)[0]
    assert row["id"] == rid
    assert row["kind"] == "autotext"
    assert row["mood"] == "sly"
    assert row["metadata"] == {"intercepted": True}


# ── query() filters ───────────────────────────────────────────────────


def test_query_filter_by_channel(log: GlobalCommsLog) -> None:
    log.log("phone_dm", "a", ["b"], "dm")
    log.log("system", "system", [], "boot")
    res = log.query(channel="system")
    assert len(res) == 1
    assert res[0]["content"] == "boot"


def test_query_filter_by_participants_sender_or_recipient(log: GlobalCommsLog) -> None:
    log.log("phone_dm", "alice", ["bob"], "to bob")
    log.log("phone_dm", "carol", ["alice"], "to alice")
    log.log("phone_dm", "carol", ["dave"], "unrelated")
    res = log.query(participants=["alice"])
    bodies = {r["content"] for r in res}
    assert bodies == {"to bob", "to alice"}


def test_query_filter_by_thread_and_since(log: GlobalCommsLog) -> None:
    log.log("phone_dm", "a", ["b"], "old", thread_id="t1", ts="2026-06-15T10:00:00")
    log.log("phone_dm", "a", ["b"], "new", thread_id="t1", ts="2026-06-15T12:00:00")
    log.log("phone_dm", "a", ["b"], "other", thread_id="t2", ts="2026-06-15T12:00:00")
    by_thread = log.query(thread_id="t1")
    assert {r["content"] for r in by_thread} == {"old", "new"}
    since = log.query(since="2026-06-15T11:00:00")
    assert {r["content"] for r in since} == {"new", "other"}


def test_query_newest_first(log: GlobalCommsLog) -> None:
    log.log("phone_dm", "a", ["b"], "1", ts="2026-06-15T01:00:00")
    log.log("phone_dm", "a", ["b"], "2", ts="2026-06-15T02:00:00")
    res = log.query()
    assert [r["content"] for r in res] == ["2", "1"]


# ── thread() ──────────────────────────────────────────────────────────


def test_thread_chronological(log: GlobalCommsLog) -> None:
    log.log("phone_group", "a", ["b"], "third", thread_id="g", ts="2026-06-15T03:00:00")
    log.log("phone_group", "a", ["b"], "first", thread_id="g", ts="2026-06-15T01:00:00")
    log.log("phone_group", "a", ["b"], "second", thread_id="g", ts="2026-06-15T02:00:00")
    convo = log.thread("g")
    assert [r["content"] for r in convo] == ["first", "second", "third"]


# ── about() ───────────────────────────────────────────────────────────


def test_about_matches_sender_recipient_and_content(log: GlobalCommsLog) -> None:
    log.log("phone_dm", "char-zed", ["b"], "as sender")          # sender
    log.log("phone_dm", "a", ["char-zed"], "as recipient")       # recipient
    log.log("phone_dm", "a", ["b"], "talking about char-zed")    # content mention
    log.log("phone_dm", "a", ["b"], "unrelated chatter")         # no match
    res = log.about("char-zed")
    bodies = {r["content"] for r in res}
    assert bodies == {"as sender", "as recipient", "talking about char-zed"}


# ── mark_observed() ───────────────────────────────────────────────────


def test_mark_observed_appends_once(log: GlobalCommsLog) -> None:
    rid = log.log("npc_dm", "a", ["b"], "secret")
    assert log.mark_observed(rid, "oracle") is True
    assert log.mark_observed(rid, "hacker") is True
    assert log.mark_observed(rid, "oracle") is True  # idempotent
    row = log.recent(1)[0]
    assert sorted(row["observed_by"]) == ["hacker", "oracle"]


def test_mark_observed_unknown_id(log: GlobalCommsLog) -> None:
    assert log.mark_observed(99999, "oracle") is False


# ── count() / prune() ─────────────────────────────────────────────────


def test_count(log: GlobalCommsLog) -> None:
    assert log.count() == 0
    for i in range(5):
        log.log("system", "system", [], f"msg{i}")
    assert log.count() == 5


def test_prune_caps_rows_keeping_newest(log: GlobalCommsLog) -> None:
    ids = [log.log("system", "system", [], f"msg{i}") for i in range(20)]
    deleted = log.prune(max_rows=5)
    assert deleted == 15
    assert log.count() == 5
    remaining = {r["id"] for r in log.recent(50)}
    # newest 5 ids retained
    assert remaining == set(ids[-5:])


def test_prune_noop_when_under_cap(log: GlobalCommsLog) -> None:
    for i in range(3):
        log.log("system", "system", [], f"msg{i}")
    assert log.prune(max_rows=10) == 0
    assert log.count() == 3


# ── concurrency ───────────────────────────────────────────────────────


def test_concurrent_writes_do_not_corrupt(log: GlobalCommsLog) -> None:
    threads_n = 8
    per_thread = 50

    def writer(tid: int) -> None:
        for i in range(per_thread):
            log.log("phone_dm", f"t{tid}", ["player"], f"{tid}-{i}")

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert log.count() == threads_n * per_thread
    rows = log.recent(threads_n * per_thread)
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids)  # all ids unique → no corruption


# ── singleton ─────────────────────────────────────────────────────────


def test_singleton_identity() -> None:
    a = get_comms_log()
    b = get_comms_log()
    assert a is b
    assert isinstance(a.count(), int)
