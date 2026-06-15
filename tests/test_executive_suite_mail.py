"""Unit tests for Executive Suite Mail reading the unified GlobalCommsLog (L1).

Covers the comms-log-backed Mail logic added in v1.62.1:
* the inbox is built from the player's conversations, grouped by thread
  (newest entry per thread), excluding hacked/planted entries;
* the INTERCEPTS folder surfaces comms the player obtained by hacking — entries
  the player ``observed_by`` on NPC↔NPC channels (comms they weren't a party to)
  plus messages the player planted (``metadata.planted by user``);
* breach notifications are surfaced via the Intel route, not the inbox;
* the ``_is_intercept`` classifier itself.

An isolated temp ``GlobalCommsLog`` is injected via ``_comms_log`` so no real
data is touched and PhoneDB is stubbed out for unread/read-receipt lookups.

Version: v1.62.1 [2026-06-15]
"""
from __future__ import annotations

import pytest

from engine.world.comms_log import GlobalCommsLog


@pytest.fixture
def comms(tmp_path) -> GlobalCommsLog:
    """An isolated comms log backed by a temp database."""
    return GlobalCommsLog(path=tmp_path / "comms_log.db")


@pytest.fixture
def scene(comms, monkeypatch):
    """An ExecutiveSuiteScene wired to the isolated comms log + stub PhoneDB.

    The scene constructor only registers routes (it does not start a server),
    so it is safe to instantiate in-process. We pin its comms-log accessor to
    the temp instance and stub PhoneDB so unread/read-receipt lookups never hit
    real data or require a phone DB.
    """
    from content.scenes.executive_suite.executive_suite_scene import ExecutiveSuiteScene

    sc = ExecutiveSuiteScene()
    monkeypatch.setattr(sc, "_comms_log", lambda: comms)

    class _StubPhoneDB:
        def thread_unread(self, _tid):
            return 0

        def mark_read(self, _tid):
            return None

        def get_thread(self, _tid):
            return None

    monkeypatch.setattr(sc, "_phone_db", lambda: _StubPhoneDB())
    # Display names: identity (avoids touching the character DB).
    monkeypatch.setattr(sc, "_char_name", lambda cid, cache: cid)
    return sc


# ── _is_intercept classifier ───────────────────────────────────────────


def test_is_intercept_planted_by_user(scene):
    entry = {"channel": "phone_dm", "sender_id": "viktor",
             "recipient_ids": ["user"], "observed_by": [],
             "metadata": {"planted": True, "by": "user"}}
    assert scene._is_intercept(entry) is True


def test_is_intercept_hacked_npc_dm(scene):
    # NPC↔NPC the player was never a party to, but observed via a hack.
    entry = {"channel": "npc_dm", "sender_id": "bex",
             "recipient_ids": ["aria"], "observed_by": ["user"],
             "metadata": {}}
    assert scene._is_intercept(entry) is True


def test_is_intercept_rejects_own_conversation(scene):
    # Player-facing phone DM the player observed — NOT a hack intercept.
    entry = {"channel": "phone_dm", "sender_id": "aria",
             "recipient_ids": ["user"], "observed_by": ["user"],
             "metadata": {}}
    assert scene._is_intercept(entry) is False


def test_is_intercept_rejects_oracle_only_observer(scene):
    # Observed only by the oracle (not the player) → not a player intercept.
    entry = {"channel": "npc_dm", "sender_id": "bex",
             "recipient_ids": ["aria"], "observed_by": ["oracle"],
             "metadata": {}}
    assert scene._is_intercept(entry) is False


# ── inbox (player conversations, grouped by thread) ─────────────────────


def test_inbox_groups_by_thread_newest_first(scene, comms):
    comms.log("phone_dm", "aria", ["user"], "hey", thread_id="t1",
              ts="2026-06-15T10:00:00")
    comms.log("phone_dm", "user", ["aria"], "hi back", thread_id="t1",
              ts="2026-06-15T11:00:00")
    comms.log("phone_dm", "bex", ["user"], "yo", thread_id="t2",
              ts="2026-06-15T12:00:00")

    out = scene._mail_threads()
    threads = out["threads"]
    # One row per thread, newest thread first.
    assert [t["id"] for t in threads] == ["t2", "t1"]
    # Newest entry per thread provides the preview.
    t1 = next(t for t in threads if t["id"] == "t1")
    assert t1["preview"] == "hi back"
    assert out["empty"] is False


def test_inbox_excludes_intercepts(scene, comms):
    comms.log("phone_dm", "aria", ["user"], "real msg", thread_id="t1")
    # An NPC↔NPC entry the player hacked must NOT appear in the inbox.
    rid = comms.log("npc_dm", "bex", ["aria"], "secret", thread_id="npc1")
    comms.mark_observed(rid, "user")

    out = scene._mail_threads()
    ids = [t["id"] for t in out["threads"]]
    assert "t1" in ids
    assert "npc1" not in ids


def test_inbox_empty_when_no_comms(scene):
    out = scene._mail_threads()
    assert out["threads"] == []
    assert out["empty"] is True


# ── intercepts folder ───────────────────────────────────────────────────


def test_intercepts_surfaces_hacked_and_planted(scene, comms):
    # A normal player conversation (should NOT be in intercepts).
    comms.log("phone_dm", "aria", ["user"], "hello", thread_id="t1")
    # A hacked NPC↔NPC entry.
    rid = comms.log("npc_dm", "bex", ["aria"], "we meet at dawn", thread_id="npc1")
    comms.mark_observed(rid, "user")
    # A message the player planted.
    comms.log("phone_dm", "user", ["viktor"], "fake evidence",
              thread_id="t2", metadata={"planted": True, "by": "user"})

    out = scene._mail_intercepts()
    items = out["intercepts"]
    assert out["count"] == 2
    labels = {i["label"] for i in items}
    assert labels == {"intercepted", "planted"}
    contents = {i["content"] for i in items}
    assert "we meet at dawn" in contents
    assert "fake evidence" in contents
    assert "hello" not in contents


def test_intercepts_empty_state(scene, comms):
    comms.log("phone_dm", "aria", ["user"], "hello", thread_id="t1")
    out = scene._mail_intercepts()
    assert out["intercepts"] == []
    assert out["empty"] is True


# ── intel breaches (surfaced separately from mail) ──────────────────────


def test_intel_breaches_reads_phone_hacked_notifications(scene, comms):
    comms.log("system", "viktor", ["user"], "Your phone was breached.",
              kind="notification",
              metadata={"notification": "phone_hacked", "attacker": "viktor",
                        "blocked": False, "success": True})
    # An unrelated system entry must be ignored.
    comms.log("system", "system", ["user"], "boot", kind="system")

    out = scene._intel_breaches()
    assert out["count"] == 1
    assert out["breaches"][0]["attacker"] == "viktor"
    assert out["breaches"][0]["blocked"] is False


def test_intel_breaches_since_filter(scene, comms):
    first = comms.log("system", "viktor", ["user"], "breach 1",
                      kind="notification",
                      metadata={"notification": "phone_hacked", "attacker": "viktor"})
    comms.log("system", "bex", ["user"], "breach 2",
              kind="notification",
              metadata={"notification": "phone_hacked", "attacker": "bex"})

    out = scene._intel_breaches(since=str(first))
    assert out["count"] == 1
    assert out["breaches"][0]["attacker"] == "bex"
