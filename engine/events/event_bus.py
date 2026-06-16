"""
Cross-scene event bus for CosySim v0.68 "Dark Renaissance".

Provides a thread-safe, in-process publish/subscribe system that lets scenes,
skills, and engine components broadcast structured events without tight
coupling.  All published events are persisted to Nexus as ``history`` entries
so they are available for post-session analysis and NLM queries.

Usage::

    from engine.events.event_bus import get_event_bus, EventTypes

    bus = get_event_bus()

    # Subscribe
    sub_id = bus.subscribe(EventTypes.ARENA_BET_WON, my_handler, "my_module")

    # Publish
    bus.publish(EventTypes.ARENA_BET_WON, {"amount": 500, "fighter": "Kira"}, scene="arena")

    # Unsubscribe
    bus.unsubscribe(sub_id)

    # Inspect recent history
    recent = bus.get_history(EventTypes.ECONOMY_TRANSACTION, limit=10)
"""
from __future__ import annotations

import logging
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)

# v1.63.0 [2026-06-17] — Sentinel pushed onto the persist queue to signal the
# background worker to drain remaining items and exit cleanly.
_SHUTDOWN_SENTINEL: object = object()


# ---------------------------------------------------------------------------
# Known event-type constants
# ---------------------------------------------------------------------------

class EventTypes:
    """Namespace of well-known CosySim event-type strings.

    Scenes and skills **should** use these constants rather than raw strings to
    avoid typos and allow IDE auto-completion.

    Example::

        bus.publish(EventTypes.WORLD_TICK, {"tick": 42})
    """

    ARENA_BET_WON: str = "arena.bet_won"
    ARENA_BET_LOST: str = "arena.bet_lost"
    ARENA_MATCH_START: str = "arena.match_start"
    ARENA_MATCH_END: str = "arena.match_end"

    CASINO_MAJOR_WIN: str = "casino.major_win"
    CASINO_DEBT_CREATED: str = "casino.debt_created"

    HEIST_JOB_COMPLETE: str = "heist.job_complete"
    HEIST_CREW_COMPROMISED: str = "heist.crew_compromised"

    PHONE_HACKER_MESSAGE: str = "phone.hacker_message"
    PHONE_JOB_ACCEPTED: str = "phone.job_accepted"

    ECONOMY_LOW_BALANCE: str = "economy.low_balance"
    ECONOMY_DEBT_OVERDUE: str = "economy.debt_overdue"
    ECONOMY_TRANSACTION: str = "economy.transaction"

    NEONCITY_FACTION_SHIFT: str = "neoncity.faction_shift"
    NEONCITY_WORLD_EVENT: str = "neoncity.world_event"

    DIRECTOR_BEAT_FIRED: str = "director.beat_fired"

    WORLD_TICK: str = "world.tick"
    WORLD_EVENT: str = "world.event"


# ---------------------------------------------------------------------------
# Internal subscription record
# ---------------------------------------------------------------------------

class _Subscription:
    """Internal record linking a subscription ID to its handler.

    Attributes:
        subscription_id: Unique identifier returned to the caller.
        event_type: The event type string this subscription is listening for.
        handler: Callable invoked with the full event dict on each publish.
        subscriber_id: Optional human-readable label (module name, scene, etc.)
    """

    __slots__ = ("subscription_id", "event_type", "handler", "subscriber_id")

    def __init__(
        self,
        subscription_id: str,
        event_type: str,
        handler: Callable[[dict], None],
        subscriber_id: str,
    ) -> None:
        self.subscription_id = subscription_id
        self.event_type = event_type
        self.handler = handler
        self.subscriber_id = subscriber_id

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<_Subscription id={self.subscription_id!r} "
            f"event={self.event_type!r} subscriber={self.subscriber_id!r}>"
        )


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------

class EventBus:
    """Thread-safe in-process publish/subscribe event bus.

    All public methods are safe to call from any thread.  Handlers are
    dispatched synchronously in the publishing thread (in subscription order)
    while the internal lock is **not** held, so handlers may themselves call
    ``publish`` or ``subscribe`` without deadlocking.

    Every published event is:

    * Kept in a capped in-memory ring-buffer for fast ``get_history`` queries.
    * Persisted to Nexus best-effort.  When ``events.persist_async`` is enabled
      (the default), persistence is enqueued to a single daemon worker thread so
      ``publish()`` returns immediately regardless of Nexus speed/availability.
      The worker drains in FIFO order; failures are logged (never raised into
      the caller).  When disabled, persistence runs synchronously inline (legacy
      behaviour).

    Subscriber dispatch is **always** synchronous and in subscription order —
    only Nexus persistence moves off the publish path.

    v1.63.0 [2026-06-17] — Non-blocking Nexus persistence: decouple publish
    latency from Nexus via a bounded background queue + daemon worker.

    Attributes:
        _MAX_HISTORY: Maximum number of events kept in the in-memory ring.
        _PERSIST_QUEUE_MAXSIZE: Bounded capacity of the async persist queue.
    """

    _MAX_HISTORY: int = 500
    _PERSIST_QUEUE_MAXSIZE: int = 1000

    def __init__(self, persist_async: Optional[bool] = None) -> None:
        """Initialise the event bus.

        Args:
            persist_async: Force the persistence mode regardless of config.
                ``True`` enables the background worker, ``False`` forces inline
                synchronous persistence.  ``None`` (default) reads
                ``events.persist_async`` from config (default ``True``).
        """
        self._lock: threading.Lock = threading.Lock()
        # event_type -> {subscription_id -> _Subscription}
        self._handlers: Dict[str, Dict[str, _Subscription]] = {}
        # Ring buffer of full event dicts, newest last
        self._history: List[dict] = []

        # --- Async persistence machinery (v1.63.0) ---
        self._persist_async: bool = (
            self._resolve_persist_async() if persist_async is None else persist_async
        )
        self._persist_queue: "queue.Queue[object]" = queue.Queue(
            maxsize=self._PERSIST_QUEUE_MAXSIZE
        )
        self._persist_worker: Optional[threading.Thread] = None
        self._worker_lock: threading.Lock = threading.Lock()
        self._shutdown: bool = False

    @staticmethod
    def _resolve_persist_async() -> bool:
        """Read the ``events.persist_async`` toggle from config (default True).

        Returns:
            ``True`` if persistence should run on the background worker.
        """
        try:
            from engine.config import get_config

            return bool(get_config().get("events.persist_async", True))
        except Exception:
            # Config unavailable (e.g. minimal test harness) — default to async.
            return True

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def publish(
        self,
        event_type: str,
        payload: dict,
        scene: str = "",
    ) -> None:
        """Publish an event to all current subscribers for *event_type*.

        Constructs a fully-formed event record, dispatches it to every
        registered handler, appends it to the in-memory history ring, and
        queues a best-effort Nexus persistence write.

        Args:
            event_type: The event-type string (use :class:`EventTypes`
                constants where possible).
            payload: Arbitrary JSON-serialisable dict carrying event data.
            scene: Optional scene identifier that originated the event.

        Returns:
            None

        Example::

            bus.publish(EventTypes.ECONOMY_TRANSACTION, {"delta": -200}, scene="casino")
        """
        if not event_type:
            logger.warning("publish() called with empty event_type; ignoring.")
            return

        event_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        # Snapshot handlers under lock so dispatch happens lock-free.
        with self._lock:
            subscriptions: List[_Subscription] = list(
                self._handlers.get(event_type, {}).values()
            )

        # Build the subscribers_notified list up-front from the snapshot so
        # that every handler receives the complete event dict on invocation.
        notified: List[str] = [
            sub.subscriber_id or sub.subscription_id for sub in subscriptions
        ]

        event: dict = {
            "id": event_id,
            "event_type": event_type,
            "payload": payload,
            "scene": scene,
            "timestamp": timestamp,
            "subscribers_notified": notified,
        }

        for sub in subscriptions:
            try:
                sub.handler(event)
            except Exception:
                logger.exception(
                    "Handler %r raised while handling event %r (sub_id=%r)",
                    sub.handler,
                    event_type,
                    sub.subscription_id,
                )

        with self._lock:
            self._history.append(event)
            if len(self._history) > self._MAX_HISTORY:
                self._history = self._history[-self._MAX_HISTORY :]

        logger.debug(
            "Published event %r (id=%s) to %d subscriber(s).",
            event_type,
            event_id,
            len(notified),
        )

        # v1.63.0 [2026-06-17] — Persistence is decoupled from the publish path.
        # Enqueue to the background worker (default) so publish() returns
        # immediately; fall back to inline persistence only when async is off.
        self._dispatch_persist(event)

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[dict], None],
        subscriber_id: str = "",
    ) -> str:
        """Register *handler* to be called whenever *event_type* is published.

        Args:
            event_type: The event-type string to listen for.
            handler: A callable that accepts a single ``dict`` argument (the
                full event record).  Must not block for extended periods as it
                runs in the publisher's thread.
            subscriber_id: Optional human-readable label for debugging (e.g.
                ``"arena_scene"``).  Defaults to an empty string.

        Returns:
            A unique ``subscription_id`` string that can be passed to
            :meth:`unsubscribe` to remove this registration.

        Raises:
            ValueError: If *event_type* is empty or *handler* is not callable.

        Example::

            sub_id = bus.subscribe(EventTypes.WORLD_TICK, on_tick, "my_scene")
        """
        if not event_type:
            raise ValueError("event_type must not be empty.")
        if not callable(handler):
            raise ValueError("handler must be callable.")

        subscription_id = str(uuid.uuid4())
        sub = _Subscription(
            subscription_id=subscription_id,
            event_type=event_type,
            handler=handler,
            subscriber_id=subscriber_id,
        )

        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = {}
            self._handlers[event_type][subscription_id] = sub

        logger.debug(
            "Subscribed %r to event %r (sub_id=%s).",
            subscriber_id or handler,
            event_type,
            subscription_id,
        )
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a previously registered subscription.

        Args:
            subscription_id: The ID returned by :meth:`subscribe`.

        Returns:
            ``True`` if the subscription was found and removed, ``False`` if
            the *subscription_id* was not recognised (already removed or never
            registered).

        Example::

            removed = bus.unsubscribe(sub_id)
        """
        with self._lock:
            for event_type, subs in self._handlers.items():
                if subscription_id in subs:
                    del subs[subscription_id]
                    logger.debug(
                        "Unsubscribed sub_id=%s from event %r.",
                        subscription_id,
                        event_type,
                    )
                    return True
        logger.debug("unsubscribe() called with unknown sub_id=%s.", subscription_id)
        return False

    def get_history(
        self,
        event_type: str = "",
        limit: int = 50,
    ) -> List[dict]:
        """Return recent events from the in-memory ring buffer.

        Args:
            event_type: If non-empty, only events matching this type are
                returned.  Pass an empty string (default) to retrieve events
                of all types.
            limit: Maximum number of events to return, taken from the most
                recent end of the ring.  Capped at :attr:`_MAX_HISTORY`.

        Returns:
            A list of event dicts (newest last), each with the shape::

                {
                    "id":                   str,
                    "event_type":           str,
                    "payload":              dict,
                    "scene":                str,
                    "timestamp":            str,   # ISO-8601 UTC
                    "subscribers_notified": list[str],
                }

        Example::

            last_10_bets = bus.get_history(EventTypes.ARENA_BET_WON, limit=10)
        """
        effective_limit = max(1, min(limit, self._MAX_HISTORY))

        with self._lock:
            snapshot = list(self._history)

        if event_type:
            snapshot = [e for e in snapshot if e["event_type"] == event_type]

        return snapshot[-effective_limit:]

    def clear_handlers(self) -> None:
        """Remove all subscriptions.

        Intended for use in test teardown to prevent handler leakage between
        test cases.  Does **not** clear the history ring or affect Nexus.

        Example::

            def teardown_method(self):
                get_event_bus().clear_handlers()
        """
        with self._lock:
            self._handlers.clear()
        logger.debug("All event handlers cleared.")

    def shutdown(self, timeout: float = 5.0) -> None:
        """Drain pending persistence and stop the background worker cleanly.

        Idempotent and safe to call multiple times.  In synchronous mode this
        is effectively a no-op.  In async mode it signals the worker to finish
        draining the queue and joins it (best-effort within *timeout*).

        Args:
            timeout: Maximum seconds to wait for the worker to drain and exit.
        """
        with self._worker_lock:
            if self._shutdown:
                return
            self._shutdown = True
            worker = self._persist_worker

        if worker is not None and worker.is_alive():
            try:
                self._persist_queue.put_nowait(_SHUTDOWN_SENTINEL)
            except queue.Full:
                # Queue saturated — block briefly so the sentinel is delivered.
                self._persist_queue.put(_SHUTDOWN_SENTINEL)
            worker.join(timeout=timeout)

    def flush(self, timeout: float = 5.0) -> bool:
        """Block until the async persist queue is fully drained.

        Intended for tests and clean checkpoints.  No-op (returns ``True``) in
        synchronous mode.

        Args:
            timeout: Maximum seconds to wait for the queue to empty.

        Returns:
            ``True`` if the queue drained within *timeout*, else ``False``.
        """
        if not self._persist_async:
            return True
        import time as _time

        deadline = _time.monotonic() + timeout
        while True:
            if self._persist_queue.unfinished_tasks == 0:
                return True
            if _time.monotonic() >= deadline:
                return False
            _time.sleep(0.01)

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _dispatch_persist(self, event: dict) -> None:
        """Route *event* to async queue or inline persistence.

        Best-effort: never raises into :meth:`publish`.  In async mode the
        event is enqueued to the bounded worker queue (dropping the event with a
        warning if the queue is saturated); in sync mode it is persisted inline.

        Args:
            event: The full event dict that was just published.
        """
        if not self._persist_async:
            self._persist_to_nexus(event)
            return

        self._ensure_worker_started()
        try:
            self._persist_queue.put_nowait(event)
        except queue.Full:
            # Defensive: never block publish — drop and log (Oracle format).
            logger.warning(
                "[EventBus] Persist queue full (operation=enqueue_persist, "
                "event_type=%s, id=%s); dropping event.",
                event.get("event_type"),
                event.get("id"),
            )

    def _ensure_worker_started(self) -> None:
        """Lazily start the daemon persistence worker (thread-safe, once)."""
        if self._persist_worker is not None and self._persist_worker.is_alive():
            return
        with self._worker_lock:
            if self._shutdown:
                return
            if self._persist_worker is not None and self._persist_worker.is_alive():
                return
            self._persist_worker = threading.Thread(
                target=self._persist_worker_loop,
                name="eventbus-persist",
                daemon=True,
            )
            self._persist_worker.start()
            logger.debug("[EventBus] Persistence worker started.")

    def _persist_worker_loop(self) -> None:
        """Background loop: drain the persist queue in FIFO order until shutdown.

        Each item is persisted best-effort; any exception is swallowed and
        logged so a single bad event never kills the worker.
        """
        while True:
            item = self._persist_queue.get()
            try:
                if item is _SHUTDOWN_SENTINEL:
                    return
                self._persist_to_nexus(item)  # type: ignore[arg-type]
            except Exception:
                logger.debug(
                    "[EventBus] Persist worker swallowed unexpected error "
                    "(operation=persist_worker).",
                    exc_info=True,
                )
            finally:
                self._persist_queue.task_done()

    def _persist_to_nexus(self, event: dict) -> None:
        """Persist *event* to Nexus as a ``history`` entry (best-effort).

        Runs synchronously in the caller's thread.  Any exception from the
        Nexus client is caught and logged so that a Nexus outage never
        disrupts the game loop.

        Args:
            event: The full event dict that was just published.
        """
        try:
            client = get_nexus_client()
            title = f"event:{event['event_type']}:{event['id'][:8]}"
            content_lines = [
                f"event_type: {event['event_type']}",
                f"scene: {event['scene']}",
                f"timestamp: {event['timestamp']}",
                f"subscribers_notified: {event['subscribers_notified']}",
                f"payload: {event['payload']}",
            ]
            client.add_entry(
                title=title,
                content="\n".join(content_lines),
                content_type="history",
                category="events",
                tags=[event["event_type"], event["scene"]] if event["scene"] else [event["event_type"]],
                created_by="event_bus",
            )
        except Exception as exc:
            # v1.63.0 [2026-06-17] — Best-effort: a Nexus outage/denial must
            # never disrupt the game loop. Log in Oracle format at warning
            # (no traceback spam) so the failure stays visible but cheap.
            logger.warning(
                "[EventBus] Failed to persist event (operation=persist_to_nexus, "
                "event_type=%s, id=%s): %s",
                event.get("event_type"),
                event.get("id"),
                exc,
            )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_bus_lock: threading.Lock = threading.Lock()
_bus_instance: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Return the process-global :class:`EventBus` singleton.

    Thread-safe; uses double-checked locking so subsequent calls (the common
    case) pay only a single attribute lookup.

    Returns:
        The shared :class:`EventBus` instance.

    Example::

        from engine.events.event_bus import get_event_bus
        bus = get_event_bus()
    """
    global _bus_instance
    if _bus_instance is None:
        with _bus_lock:
            if _bus_instance is None:
                _bus_instance = EventBus()
                # v1.63.0 [2026-06-17] — Drain pending persistence on interpreter
                # exit so queued history events are flushed cleanly.
                import atexit

                atexit.register(_bus_instance.shutdown)
                logger.info("EventBus singleton created.")
    return _bus_instance
