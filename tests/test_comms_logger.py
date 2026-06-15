"""Unit tests for the CommsLoggerInterceptor (CB-T2).

Verifies that the post-call interceptor maps a ResponseContext onto a single
GlobalCommsLog entry with the correct sender/recipients/content/channel/thread,
honors published comms context, derives a channel from the scene when no context
is published, and is defensive — a comms-log failure must never propagate.

A temp-path :class:`GlobalCommsLog` is injected via monkeypatching
``engine.world.comms_log.get_comms_log`` so the real database is never touched.

Version: v1.62.0 [2026-06-15]
"""
from __future__ import annotations

import pytest

from engine.agents.interceptors.comms_logger import (
    CommsLoggerInterceptor,
    comms_context,
)
from engine.mcp.comms_framework import ResponseContext
from engine.world.comms_log import GlobalCommsLog


@pytest.fixture
def temp_log(tmp_path, monkeypatch) -> GlobalCommsLog:
    """Install a temp-path GlobalCommsLog as the singleton for the test."""
    log = GlobalCommsLog(path=tmp_path / "comms_log.db")
    monkeypatch.setattr(
        "engine.world.comms_log.get_comms_log", lambda: log, raising=True
    )
    return log


def _ctx(**over) -> ResponseContext:
    """Build a minimal ResponseContext mirroring the governor's real fields."""
    base = dict(
        scene="phone",
        agent_id="char-aria",
        agent_name="Aria",
        user_message="hey",
        reply="hey you, what's up 😏",
        response_id="resp_123",
        mood_tags=["flirty"],
    )
    base.update(over)
    return ResponseContext(base)


# ── mapping ────────────────────────────────────────────────────────────


def test_logs_agent_reply_with_published_context(temp_log: GlobalCommsLog) -> None:
    interceptor = CommsLoggerInterceptor()
    with comms_context(
        channel="phone_dm", thread_id="thread-abc", recipient_ids=["user"]
    ):
        interceptor.post_call(_ctx())

    rows = temp_log.recent(10)
    assert len(rows) == 1
    row = rows[0]
    assert row["sender_id"] == "char-aria"
    assert row["recipient_ids"] == ["user"]
    assert row["content"] == "hey you, what's up 😏"
    assert row["channel"] == "phone_dm"
    assert row["thread_id"] == "thread-abc"
    assert row["kind"] == "message"
    assert row["mood"] == "flirty"
    assert row["metadata"]["scene"] == "phone"
    assert row["metadata"]["response_id"] == "resp_123"


def test_thread_lookup_aligns_with_published_thread(temp_log: GlobalCommsLog) -> None:
    interceptor = CommsLoggerInterceptor()
    with comms_context(channel="phone_dm", thread_id="thread-xyz"):
        interceptor.post_call(_ctx(reply="aligned"))
    convo = temp_log.thread("thread-xyz")
    assert [r["content"] for r in convo] == ["aligned"]


def test_recipients_fall_back_to_user_without_context(temp_log: GlobalCommsLog) -> None:
    interceptor = CommsLoggerInterceptor()
    interceptor.post_call(_ctx())  # no comms_context published
    row = temp_log.recent(1)[0]
    assert row["recipient_ids"] == ["user"]


def test_channel_derived_from_scene_without_context(temp_log: GlobalCommsLog) -> None:
    interceptor = CommsLoggerInterceptor()
    interceptor.post_call(_ctx(scene="penthouse"))
    row = temp_log.recent(1)[0]
    assert row["channel"] == "scene:penthouse"


def test_group_recipients_from_context(temp_log: GlobalCommsLog) -> None:
    interceptor = CommsLoggerInterceptor()
    with comms_context(
        channel="phone_group",
        thread_id="grp-1",
        recipient_ids=["user", "char-bex"],
    ):
        interceptor.post_call(_ctx(reply="hi all"))
    row = temp_log.recent(1)[0]
    assert row["channel"] == "phone_group"
    assert row["recipient_ids"] == ["user", "char-bex"]


def test_published_sender_id_overrides_unknown_agent_id(
    temp_log: GlobalCommsLog,
) -> None:
    """The governor yields agent_id='unknown' for dict-backed phone agents;
    a published sender_id must win so the real char id is logged."""
    interceptor = CommsLoggerInterceptor()
    with comms_context(
        channel="phone_dm", thread_id="t1", recipient_ids=["user"],
        sender_id="aria",
    ):
        interceptor.post_call(_ctx(agent_id="unknown"))
    row = temp_log.recent(1)[0]
    assert row["sender_id"] == "aria"


def test_ctx_agent_id_used_when_no_published_sender(temp_log: GlobalCommsLog) -> None:
    interceptor = CommsLoggerInterceptor()
    interceptor.post_call(_ctx(agent_id="char-real"))
    row = temp_log.recent(1)[0]
    assert row["sender_id"] == "char-real"


# ── skip conditions ─────────────────────────────────────────────────────


def test_skips_empty_reply(temp_log: GlobalCommsLog) -> None:
    interceptor = CommsLoggerInterceptor()
    interceptor.post_call(_ctx(reply="   "))
    assert temp_log.count() == 0


def test_skips_missing_agent_id(temp_log: GlobalCommsLog) -> None:
    interceptor = CommsLoggerInterceptor()
    interceptor.post_call(_ctx(agent_id=""))
    assert temp_log.count() == 0


def test_mood_falls_back_to_mood_key(temp_log: GlobalCommsLog) -> None:
    interceptor = CommsLoggerInterceptor()
    interceptor.post_call(_ctx(mood_tags=[], mood="calm"))
    row = temp_log.recent(1)[0]
    assert row["mood"] == "calm"


# ── defensiveness ───────────────────────────────────────────────────────


def test_log_failure_never_propagates(monkeypatch) -> None:
    """A raising comms-log must not break the interceptor."""
    class _Boom:
        def log(self, *a, **k):
            raise RuntimeError("db exploded")

    monkeypatch.setattr(
        "engine.world.comms_log.get_comms_log", lambda: _Boom(), raising=True
    )
    interceptor = CommsLoggerInterceptor()
    # Must return normally despite the underlying failure.
    interceptor.post_call(_ctx())
