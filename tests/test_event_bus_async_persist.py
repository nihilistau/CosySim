"""Tests for non-blocking Nexus persistence in engine/events/event_bus.py.

Covers the v1.63.0 fix that decouples ``publish()`` latency from Nexus by
moving ``_persist_to_nexus`` onto a bounded background worker thread, plus the
``event_bus`` write-permission allowlist fix in the governance layer.

All tests patch / mock the Nexus sink so no real HTTP calls are made.
"""
from __future__ import annotations

import threading
import time
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from engine.events.event_bus import EventBus, EventTypes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_nexus():
    """Patch get_nexus_client for every test so no real HTTP is attempted."""
    with patch("engine.events.event_bus.get_nexus_client") as mock_factory:
        mock_client = MagicMock()
        mock_factory.return_value = mock_client
        yield mock_factory, mock_client


def _make_bus(persist_async: bool) -> EventBus:
    """Construct an EventBus with persistence mode forced regardless of config."""
    return EventBus(persist_async=persist_async)


# ---------------------------------------------------------------------------
# Subscriber delivery must remain synchronous + ordered (unchanged behaviour)
# ---------------------------------------------------------------------------

class TestSubscriberDeliveryUnchanged:
    @pytest.mark.parametrize("persist_async", [True, False])
    def test_subscribers_receive_synchronously(self, persist_async: bool):
        """Handlers run in-thread before publish() returns, both modes."""
        bus = _make_bus(persist_async)
        try:
            received: List[dict] = []
            bus.subscribe(EventTypes.WORLD_TICK, received.append, "sub")
            bus.publish(EventTypes.WORLD_TICK, {"tick": 1})
            # Synchronous: already delivered the instant publish() returns.
            assert len(received) == 1
            assert received[0]["payload"] == {"tick": 1}
        finally:
            bus.shutdown()

    @pytest.mark.parametrize("persist_async", [True, False])
    def test_subscribers_receive_in_order(self, persist_async: bool):
        """Multiple subscribers fire in subscription order, both modes."""
        bus = _make_bus(persist_async)
        try:
            order: List[str] = []
            bus.subscribe(EventTypes.WORLD_TICK, lambda e: order.append("a"), "a")
            bus.subscribe(EventTypes.WORLD_TICK, lambda e: order.append("b"), "b")
            bus.subscribe(EventTypes.WORLD_TICK, lambda e: order.append("c"), "c")
            bus.publish(EventTypes.WORLD_TICK, {})
            assert order == ["a", "b", "c"]
        finally:
            bus.shutdown()


# ---------------------------------------------------------------------------
# Persistence is invoked without blocking publish
# ---------------------------------------------------------------------------

class TestPersistenceInvoked:
    def test_async_persist_invokes_sink(self, _patch_nexus):
        """In async mode the Nexus sink is eventually called once per event."""
        _, mock_client = _patch_nexus
        bus = _make_bus(persist_async=True)
        try:
            bus.publish(EventTypes.ECONOMY_TRANSACTION, {"delta": 5}, scene="casino")
            bus.flush(timeout=5.0)
            mock_client.add_entry.assert_called_once()
            kwargs = mock_client.add_entry.call_args.kwargs
            assert kwargs.get("content_type") == "history"
            assert kwargs.get("category") == "events"
            assert kwargs.get("created_by") == "event_bus"
        finally:
            bus.shutdown()

    def test_sync_persist_invokes_sink(self, _patch_nexus):
        """In sync mode the sink is called inline during publish()."""
        _, mock_client = _patch_nexus
        bus = _make_bus(persist_async=False)
        try:
            bus.publish(EventTypes.ECONOMY_TRANSACTION, {"delta": 5})
            mock_client.add_entry.assert_called_once()
        finally:
            bus.shutdown()

    def test_async_publish_does_not_block_on_slow_sink(self, _patch_nexus):
        """A slow Nexus sink must not delay publish() in async mode."""
        _, mock_client = _patch_nexus

        def _slow_add_entry(*args, **kwargs):
            time.sleep(2.0)

        mock_client.add_entry.side_effect = _slow_add_entry
        bus = _make_bus(persist_async=True)
        try:
            t0 = time.perf_counter()
            bus.publish(EventTypes.WORLD_TICK, {"tick": 1})
            elapsed = time.perf_counter() - t0
            # publish() returns well before the 2s sink completes.
            assert elapsed < 0.5, f"publish blocked for {elapsed:.3f}s"
        finally:
            bus.shutdown()


# ---------------------------------------------------------------------------
# A failing / denied sink must never block or raise into publish
# ---------------------------------------------------------------------------

class TestFailingSinkIsolated:
    @pytest.mark.parametrize("persist_async", [True, False])
    def test_sink_exception_does_not_raise(self, _patch_nexus, persist_async: bool):
        """An exception from the sink never propagates to publish(), both modes."""
        _, mock_client = _patch_nexus
        mock_client.add_entry.side_effect = RuntimeError("nexus down")
        bus = _make_bus(persist_async)
        try:
            # Must not raise.
            bus.publish(EventTypes.WORLD_TICK, {"tick": 0})
            bus.flush(timeout=5.0)
        finally:
            bus.shutdown()

    def test_permission_error_does_not_block_publish(self, _patch_nexus):
        """A PermissionError from the sink stays off the publish path (async)."""
        _, mock_client = _patch_nexus
        mock_client.add_entry.side_effect = PermissionError(
            "Agent 'event_bus' is not permitted to perform 'write'"
        )
        bus = _make_bus(persist_async=True)
        try:
            t0 = time.perf_counter()
            bus.publish(EventTypes.NEONCITY_FACTION_SHIFT, {"x": 1})
            elapsed = time.perf_counter() - t0
            assert elapsed < 0.5
            bus.flush(timeout=5.0)
        finally:
            bus.shutdown()


# ---------------------------------------------------------------------------
# Drain ordering + clean shutdown
# ---------------------------------------------------------------------------

class TestDrainAndShutdown:
    def test_async_drains_in_order(self, _patch_nexus):
        """Queued events are persisted in publish order (FIFO)."""
        _, mock_client = _patch_nexus
        seen: List[str] = []

        def _record(*args, **kwargs):
            seen.append(kwargs.get("title", ""))

        mock_client.add_entry.side_effect = _record
        bus = _make_bus(persist_async=True)
        try:
            for i in range(20):
                bus.publish(EventTypes.WORLD_TICK, {"i": i}, scene=str(i))
            bus.flush(timeout=5.0)
            assert len(seen) == 20
            # Titles embed the event id, but scene order is FIFO-preserved via
            # the worker; verify monotonic by checking add_entry call count and
            # that the worker preserved submission order of scenes.
            scenes = [c.kwargs.get("tags") for c in mock_client.add_entry.call_args_list]
            order = [t[1] for t in scenes]  # tag[1] is the scene
            assert order == [str(i) for i in range(20)]
        finally:
            bus.shutdown()

    def test_shutdown_drains_pending(self, _patch_nexus):
        """shutdown() drains any queued events before the worker stops."""
        _, mock_client = _patch_nexus
        bus = _make_bus(persist_async=True)
        for i in range(10):
            bus.publish(EventTypes.WORLD_TICK, {"i": i})
        bus.shutdown(timeout=5.0)
        assert mock_client.add_entry.call_count == 10

    def test_shutdown_is_idempotent(self, _patch_nexus):
        """Calling shutdown() twice is safe."""
        bus = _make_bus(persist_async=True)
        bus.shutdown()
        bus.shutdown()  # must not raise

    def test_worker_thread_is_daemon(self, _patch_nexus):
        """The background persist worker is a daemon thread."""
        bus = _make_bus(persist_async=True)
        try:
            bus.publish(EventTypes.WORLD_TICK, {})
            worker = bus._persist_worker  # type: ignore[attr-defined]
            assert worker is not None
            assert isinstance(worker, threading.Thread)
            assert worker.daemon is True
        finally:
            bus.shutdown()


# ---------------------------------------------------------------------------
# Governance: event_bus actor is permitted to write
# ---------------------------------------------------------------------------

class TestEventBusWritePermission:
    def test_event_bus_actor_permitted_to_write(self):
        """The governance layer allows the 'event_bus' actor to write."""
        from engine.nexus.governance_rules import get_governance_manager

        mgr = get_governance_manager()
        # Resolve via the heuristic/registry path; event_bus must be a known
        # write-capable actor (not default-deny).
        resolved = mgr._heuristic_resolve("event_bus")
        assert resolved, "event_bus should resolve to a known agent type"
        assert "write" in resolved.get("ops", [])
        assert "read" in resolved.get("ops", [])
        # event_bus is persistence-only — it must NOT get delete/admin.
        assert "delete" not in resolved.get("ops", [])
        assert "admin" not in resolved.get("ops", [])
