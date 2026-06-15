"""
StatSyncInterceptor tests
=========================

Verifies the keystone of the v1.59 "consequential world" pass: ``[STAT:]``
tags emitted by an agent are actually applied to character game state.

Version: v1.59.0 [2026-06-13]
"""
from __future__ import annotations

import pytest

from engine.agents.interceptors.stat_sync import StatSyncInterceptor


@pytest.mark.unit
def test_parse_updates_delta_set_and_ignored():
    deltas, sets, ignored = StatSyncInterceptor._parse_updates(
        ["arousal+10", "trust-5", "happiness=70", "bogusstat+3", "garbage"]
    )
    assert deltas == {"arousal": 10, "trust": -5}
    assert sets == {"happiness": 70}
    # unknown stat name + unparseable string both ignored
    assert "bogusstat+3" in ignored
    assert "garbage" in ignored


@pytest.mark.unit
def test_parse_updates_accumulates_deltas():
    deltas, sets, _ = StatSyncInterceptor._parse_updates(["arousal+5", "arousal+5"])
    assert deltas == {"arousal": 10}
    assert sets == {}


@pytest.mark.unit
def test_parse_updates_aliases_resolve():
    deltas, sets, ignored = StatSyncInterceptor._parse_updates(
        ["desire+8", "joy=50", "rage-3"]
    )
    assert deltas == {"horniness": 8, "anger": -3}
    assert sets == {"happiness": 50}
    assert ignored == []


@pytest.mark.unit
def test_set_overrides_later_delta():
    # absolute set wins; a later delta on the same stat is skipped
    deltas, sets, _ = StatSyncInterceptor._parse_updates(["arousal=40", "arousal+10"])
    assert sets == {"arousal": 40}
    assert "arousal" not in deltas


@pytest.mark.unit
def test_registered_at_priority_91():
    from engine.agents.interceptors import get_all_interceptors
    classes = get_all_interceptors()
    assert StatSyncInterceptor in classes
    inst = StatSyncInterceptor()
    assert inst.priority == 91


@pytest.mark.unit
def test_post_call_applies_to_coordinator(monkeypatch):
    """End-to-end: a reply with [STAT:] tags drives state_coordinator.update."""
    calls = []

    class _FakeCoord:
        def update(self, char_id, *, mode="delta", scene="", source="", **fields):
            calls.append((char_id, mode, dict(fields)))
            return {}

    import engine.mcp.state_coordinator as sc
    monkeypatch.setattr(sc, "get_coordinator", lambda: _FakeCoord())

    ctx = {
        "agent_id": "lola",
        "scene": "lounge",
        "reply": "I lean closer, pulse racing. [STAT:arousal+15] [STAT:trust=60]",
    }
    StatSyncInterceptor().post_call(ctx)

    # one delta call and one set call, both for lola
    modes = {mode: fields for (_cid, mode, fields) in calls}
    assert modes.get("delta") == {"arousal": 15}
    assert modes.get("set") == {"trust": 60}
    # reply was cleaned of tags
    assert "[STAT:" not in ctx["reply"]
