"""Circuit breaker and resilience framework for CosySim.

Production-grade circuit breaker with exponential backoff, retry policies,
state transition history, and optional Nexus/metrics integration.

Usage::

    from engine.resilience.circuit_breaker import (
        CircuitBreaker, CircuitConfig, CircuitOpenError,
        ExponentialBackoff, RetryPolicy,
        retry_with_backoff, circuit_protected,
        get_breaker_registry,
    )

    # Standalone circuit breaker
    cb = CircuitBreaker(CircuitConfig(name="lmstudio", failure_threshold=5))
    if cb.allow_request():
        try:
            result = call_lmstudio()
            cb.record_success()
        except Exception as exc:
            cb.record_failure(exc)

    # Decorator form
    @circuit_protected(cb, fallback=lambda: {"error": "service down"})
    def call_lmstudio():
        ...

    # Retry with backoff
    @retry_with_backoff(RetryPolicy(max_attempts=5))
    def flaky_call():
        ...

    # Registry
    registry = get_breaker_registry()
    breaker = registry.get_or_create("comfyui", CircuitConfig(failure_threshold=3))
    summary = registry.get_health_summary()
"""
from __future__ import annotations

import asyncio
import enum
import functools
import inspect
import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
)

logger = logging.getLogger(__name__)


# ──── Constants ────────────────────────────────────────────────────────────

_MAX_TRANSITION_HISTORY: int = 100
_REGISTRY_LOCK = threading.Lock()
_REGISTRY_INSTANCE: Optional[CircuitBreakerRegistry] = None


# ──── Exceptions ───────────────────────────────────────────────────────────


class CircuitOpenError(Exception):
    """Raised when a request is attempted on an open circuit breaker.

    Attributes:
        breaker_name: Name of the circuit breaker.
        open_since: Epoch timestamp when the circuit opened.
        recovery_timeout: Seconds until half-open is attempted.
    """

    def __init__(
        self,
        breaker_name: str,
        open_since: float,
        recovery_timeout: float,
    ) -> None:
        self.breaker_name = breaker_name
        self.open_since = open_since
        self.recovery_timeout = recovery_timeout
        remaining = max(0.0, recovery_timeout - (time.monotonic() - open_since))
        super().__init__(
            f"Circuit '{breaker_name}' is OPEN "
            f"(since {remaining:.1f}s ago, recovery in {remaining:.1f}s)"
        )


# ──── Enums ────────────────────────────────────────────────────────────────


class CircuitState(enum.Enum):
    """States of the circuit breaker finite state machine."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ──── Data classes ─────────────────────────────────────────────────────────


@dataclass
class StateTransition:
    """Record of a single circuit breaker state change.

    Attributes:
        breaker_name: Human-readable breaker identifier.
        from_state: Previous state.
        to_state: New state.
        timestamp: Monotonic time of the transition.
        reason: Why the transition happened.
        failure_count: Running failure count at transition time.
    """

    breaker_name: str
    from_state: CircuitState
    to_state: CircuitState
    timestamp: float
    reason: str
    failure_count: int = 0


@dataclass
class CircuitConfig:
    """Configuration for a :class:`CircuitBreaker` instance.

    Attributes:
        failure_threshold: Consecutive failures before opening the circuit.
        recovery_timeout: Seconds before attempting half-open from open.
        half_open_max_calls: Maximum probe calls allowed in half-open state.
        success_threshold: Consecutive successes needed to close from half-open.
        excluded_exceptions: Exception types that are NOT counted as failures.
        window_size: Rolling window in seconds for failure-rate tracking.
        name: Human-readable identifier for the breaker.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 3
    success_threshold: int = 2
    excluded_exceptions: Tuple[Type[Exception], ...] = ()
    window_size: int = 60
    name: str = ""


# ──── Exponential Backoff ──────────────────────────────────────────────────


class ExponentialBackoff:
    """Compute exponential backoff delays with optional jitter.

    Args:
        base_delay: Starting delay in seconds.
        max_delay: Upper cap on the computed delay.
        multiplier: Factor applied per attempt.
        jitter: If ``True``, add random 0–50 % of computed delay.
    """

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        multiplier: float = 2.0,
        jitter: bool = True,
    ) -> None:
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter
        self._attempt: int = 0

    def next_delay(self, attempt: int) -> float:
        """Calculate the delay for the given *attempt* number (0-based).

        Args:
            attempt: Zero-based attempt index.

        Returns:
            Delay in seconds, capped at *max_delay*.
        """
        delay = self.base_delay * (self.multiplier ** attempt)
        delay = min(delay, self.max_delay)
        if self.jitter:
            delay += random.uniform(0.0, delay * 0.5)
        return delay

    def reset(self) -> None:
        """Reset the internal attempt counter."""
        self._attempt = 0


# ──── Retry Policy ─────────────────────────────────────────────────────────


@dataclass
class RetryPolicy:
    """Describes how retries should be attempted.

    Attributes:
        max_attempts: Total attempts (including the first call).
        backoff: Backoff strategy to use between attempts.
        retryable_exceptions: Exception types that trigger a retry.
        on_retry: Optional callback invoked before each retry with
            ``(attempt_number, exception)`` arguments.
    """

    max_attempts: int = 3
    backoff: ExponentialBackoff = field(default_factory=ExponentialBackoff)
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
    on_retry: Optional[Callable[[int, Exception], None]] = None


# ──── Circuit Breaker ──────────────────────────────────────────────────────


class CircuitBreaker:
    """Thread-safe circuit breaker with rolling failure window.

    Implements the standard three-state pattern:

    * **CLOSED** — requests pass through; failures are counted.
    * **OPEN** — all requests are blocked until *recovery_timeout* expires.
    * **HALF_OPEN** — a limited number of probe requests are allowed; if
      enough succeed the circuit closes, otherwise it reopens.

    Args:
        config: A :class:`CircuitConfig` instance.
    """

    def __init__(self, config: CircuitConfig) -> None:
        self._config = config
        self._lock = threading.Lock()

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._half_open_calls: int = 0
        self._half_open_successes: int = 0

        self._total_requests: int = 0
        self._total_successes: int = 0
        self._total_failures: int = 0

        self._last_failure_time: float = 0.0
        self._open_since: float = 0.0

        # Rolling failure window (monotonic timestamps of failures)
        self._failure_timestamps: Deque[float] = deque()

        # Transition history (bounded)
        self._transitions: Deque[StateTransition] = deque(
            maxlen=_MAX_TRANSITION_HISTORY
        )

        if config.name:
            logger.debug("CircuitBreaker '%s' initialised (CLOSED)", config.name)

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        """Return the current circuit state.

        If the circuit is OPEN and the recovery timeout has elapsed the
        state is automatically promoted to HALF_OPEN.
        """
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    @property
    def config(self) -> CircuitConfig:
        """Return the breaker configuration (read-only)."""
        return self._config

    @property
    def name(self) -> str:
        """Shortcut for ``config.name``."""
        return self._config.name

    @property
    def transitions(self) -> List[StateTransition]:
        """Return a copy of the transition history (newest last)."""
        with self._lock:
            return list(self._transitions)

    # ── Public API ─────────────────────────────────────────────────────

    def allow_request(self) -> bool:
        """Determine whether a request should be allowed.

        Returns:
            ``True`` if the request may proceed, ``False`` otherwise.
        """
        with self._lock:
            self._maybe_transition_to_half_open()

            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls < self._config.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False

            # OPEN
            return False

    def record_success(self) -> None:
        """Record a successful request.

        In HALF_OPEN state, once *success_threshold* consecutive successes
        are recorded the circuit transitions back to CLOSED.
        """
        with self._lock:
            self._total_requests += 1
            self._total_successes += 1

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self._config.success_threshold:
                    self._transition(
                        CircuitState.CLOSED,
                        reason="success_threshold",
                    )
            elif self._state == CircuitState.CLOSED:
                # Consecutive-failure counter resets on success.
                self._failure_count = 0

    def record_failure(self, error: Optional[Exception] = None) -> None:
        """Record a failed request.

        Args:
            error: The exception that caused the failure.  If its type is
                in *excluded_exceptions* the failure is **not** counted.
        """
        if error is not None and isinstance(error, self._config.excluded_exceptions):
            logger.debug(
                "CircuitBreaker '%s': excluded exception %s ignored",
                self._config.name,
                type(error).__name__,
            )
            return

        with self._lock:
            now = time.monotonic()
            self._total_requests += 1
            self._total_failures += 1
            self._last_failure_time = now
            self._failure_timestamps.append(now)
            self._prune_failure_window(now)

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open reopens the circuit immediately.
                self._transition(
                    CircuitState.OPEN,
                    reason="half_open_failure",
                )
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self._config.failure_threshold:
                    self._transition(
                        CircuitState.OPEN,
                        reason="failure_threshold",
                    )

    def reset(self) -> None:
        """Force-reset the circuit to CLOSED regardless of current state."""
        with self._lock:
            old = self._state
            if old != CircuitState.CLOSED:
                self._transition(CircuitState.CLOSED, reason="manual_reset")
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._half_open_successes = 0
            self._failure_timestamps.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Return a snapshot of the breaker's statistics.

        Returns:
            Dictionary with keys: ``name``, ``state``, ``failure_count``,
            ``success_count``, ``total_requests``, ``total_successes``,
            ``total_failures``, ``last_failure_time``, ``open_since``,
            ``failure_rate``, ``half_open_calls``, ``half_open_successes``,
            ``transition_count``.
        """
        with self._lock:
            self._maybe_transition_to_half_open()
            now = time.monotonic()
            self._prune_failure_window(now)
            return {
                "name": self._config.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "total_requests": self._total_requests,
                "total_successes": self._total_successes,
                "total_failures": self._total_failures,
                "last_failure_time": self._last_failure_time,
                "open_since": self._open_since,
                "failure_rate": self._compute_failure_rate(now),
                "half_open_calls": self._half_open_calls,
                "half_open_successes": self._half_open_successes,
                "transition_count": len(self._transitions),
            }

    def get_failure_rate(self) -> float:
        """Return failures-per-second over the rolling window.

        Returns:
            Rate as a float (failures / window_size seconds).
        """
        with self._lock:
            now = time.monotonic()
            self._prune_failure_window(now)
            return self._compute_failure_rate(now)

    # ── Internal helpers (must be called under self._lock) ─────────────

    def _maybe_transition_to_half_open(self) -> None:
        """Promote OPEN → HALF_OPEN if recovery timeout has elapsed."""
        if self._state != CircuitState.OPEN:
            return
        elapsed = time.monotonic() - self._open_since
        if elapsed >= self._config.recovery_timeout:
            self._transition(
                CircuitState.HALF_OPEN,
                reason="recovery_timeout",
            )

    def _transition(self, new_state: CircuitState, reason: str) -> None:
        """Execute a state transition and record it.

        Side-effects (best-effort):
        * Appends to ``_transitions`` history.
        * Logs to Nexus and metrics (failures are silently swallowed).
        """
        old_state = self._state
        self._state = new_state

        transition = StateTransition(
            breaker_name=self._config.name,
            from_state=old_state,
            to_state=new_state,
            timestamp=time.monotonic(),
            reason=reason,
            failure_count=self._failure_count,
        )
        self._transitions.append(transition)

        # Reset per-state counters on entering a new state.
        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._half_open_successes = 0
            self._failure_timestamps.clear()
        elif new_state == CircuitState.OPEN:
            self._open_since = time.monotonic()
            self._half_open_calls = 0
            self._half_open_successes = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._half_open_successes = 0

        logger.info(
            "CircuitBreaker '%s': %s → %s (reason=%s, failures=%d)",
            self._config.name,
            old_state.value,
            new_state.value,
            reason,
            self._failure_count,
        )

        # Best-effort Nexus logging (fire-and-forget outside lock).
        _log_transition_to_nexus(transition)
        _log_transition_to_metrics(transition, new_state)

    def _prune_failure_window(self, now: float) -> None:
        """Remove failure timestamps older than the rolling window."""
        cutoff = now - self._config.window_size
        while self._failure_timestamps and self._failure_timestamps[0] < cutoff:
            self._failure_timestamps.popleft()

    def _compute_failure_rate(self, now: float) -> float:
        """Failures per second within the rolling window."""
        count = len(self._failure_timestamps)
        if count == 0 or self._config.window_size <= 0:
            return 0.0
        return count / self._config.window_size

    # ── Dunder helpers ─────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(name={self._config.name!r}, "
            f"state={self._state.value}, "
            f"failures={self._failure_count})"
        )


# ──── Best-effort Nexus / metrics helpers ──────────────────────────────────


def _log_transition_to_nexus(transition: StateTransition) -> None:
    """Log a state transition to the Nexus knowledge system (best-effort)."""
    try:
        from engine.nexus.client import get_nexus_client

        client = get_nexus_client()
        client.add_entry(
            title=(
                f"Circuit breaker '{transition.breaker_name}' "
                f"→ {transition.to_state.value}"
            ),
            content=(
                f"Transition: {transition.from_state.value} → "
                f"{transition.to_state.value}. "
                f"Reason: {transition.reason}. "
                f"Failures: {transition.failure_count}"
            ),
            content_type="note",
            category="resilience",
            tags=["circuit_breaker", transition.breaker_name],
            created_by="resilience_framework",
        )
    except Exception:  # noqa: BLE001
        pass


def _log_transition_to_metrics(
    transition: StateTransition,
    new_state: CircuitState,
) -> None:
    """Record a circuit state change in the metrics database (best-effort)."""
    try:
        from engine.observability.metrics_db import get_metrics_db

        db = get_metrics_db()
        level = "red" if new_state == CircuitState.OPEN else "green"
        db.record_alert(
            node=f"circuit_{transition.breaker_name}",
            level=level,
            message=(
                f"Circuit {transition.breaker_name}: {new_state.value} "
                f"(reason={transition.reason})"
            ),
        )
    except Exception:  # noqa: BLE001
        pass


# ──── Registry ─────────────────────────────────────────────────────────────


class CircuitBreakerRegistry:
    """Singleton registry that tracks all circuit breakers in the system.

    Obtain the global instance via :func:`get_breaker_registry`.
    """

    def __init__(self) -> None:
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def register(self, name: str, breaker: CircuitBreaker) -> None:
        """Register a circuit breaker under *name*.

        Args:
            name: Unique identifier.
            breaker: The breaker instance.

        Raises:
            ValueError: If *name* is already registered.
        """
        with self._lock:
            if name in self._breakers:
                raise ValueError(
                    f"Circuit breaker '{name}' is already registered"
                )
            self._breakers[name] = breaker
            logger.debug("Registered circuit breaker '%s'", name)

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Return the breaker for *name*, or ``None`` if not found.

        Args:
            name: Registered breaker name.
        """
        with self._lock:
            return self._breakers.get(name)

    def get_or_create(
        self,
        name: str,
        config: Optional[CircuitConfig] = None,
    ) -> CircuitBreaker:
        """Return an existing breaker or create a new one.

        If a breaker with *name* already exists it is returned regardless of
        the supplied *config*.  Otherwise a new breaker is created, registered,
        and returned.

        Args:
            name: Unique breaker identifier.
            config: Configuration for a new breaker.  If ``None`` a default
                :class:`CircuitConfig` is used with *name* populated.

        Returns:
            The registered :class:`CircuitBreaker`.
        """
        with self._lock:
            if name in self._breakers:
                return self._breakers[name]
            if config is None:
                config = CircuitConfig(name=name)
            elif not config.name:
                config = CircuitConfig(
                    failure_threshold=config.failure_threshold,
                    recovery_timeout=config.recovery_timeout,
                    half_open_max_calls=config.half_open_max_calls,
                    success_threshold=config.success_threshold,
                    excluded_exceptions=config.excluded_exceptions,
                    window_size=config.window_size,
                    name=name,
                )
            breaker = CircuitBreaker(config)
            self._breakers[name] = breaker
            logger.debug("Created and registered circuit breaker '%s'", name)
            return breaker

    def unregister(self, name: str) -> Optional[CircuitBreaker]:
        """Remove and return a breaker, or ``None`` if not found.

        Args:
            name: Registered breaker name.
        """
        with self._lock:
            return self._breakers.pop(name, None)

    def all_status(self) -> Dict[str, Dict[str, Any]]:
        """Return ``{name: stats_dict}`` for every registered breaker."""
        with self._lock:
            names = list(self._breakers.keys())
            breakers = list(self._breakers.values())
        return {n: b.get_stats() for n, b in zip(names, breakers)}

    def reset_all(self) -> None:
        """Reset every registered breaker to CLOSED."""
        with self._lock:
            breakers = list(self._breakers.values())
        for b in breakers:
            b.reset()
        logger.info("All circuit breakers reset to CLOSED")

    def get_open_circuits(self) -> List[str]:
        """Return the names of all breakers currently in OPEN state."""
        with self._lock:
            return [
                name
                for name, b in self._breakers.items()
                if b.state == CircuitState.OPEN
            ]

    def get_health_summary(self) -> Dict[str, Any]:
        """Return an aggregate health summary of all breakers.

        Returns:
            Dictionary with keys: ``total``, ``closed``, ``open``,
            ``half_open``, ``breakers`` (list of per-breaker dicts).
        """
        status = self.all_status()
        closed = sum(1 for s in status.values() if s["state"] == "closed")
        open_count = sum(1 for s in status.values() if s["state"] == "open")
        half_open = sum(
            1 for s in status.values() if s["state"] == "half_open"
        )
        return {
            "total": len(status),
            "closed": closed,
            "open": open_count,
            "half_open": half_open,
            "breakers": [
                {
                    "name": name,
                    "state": info["state"],
                    "failure_count": info["failure_count"],
                    "failure_rate": info["failure_rate"],
                    "total_requests": info["total_requests"],
                }
                for name, info in status.items()
            ],
        }

    def __len__(self) -> int:
        with self._lock:
            return len(self._breakers)

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._breakers

    def __repr__(self) -> str:
        with self._lock:
            names = list(self._breakers.keys())
        return f"CircuitBreakerRegistry(breakers={names!r})"


def get_breaker_registry() -> CircuitBreakerRegistry:
    """Return the global :class:`CircuitBreakerRegistry` singleton."""
    global _REGISTRY_INSTANCE  # noqa: PLW0603
    if _REGISTRY_INSTANCE is None:
        with _REGISTRY_LOCK:
            if _REGISTRY_INSTANCE is None:
                _REGISTRY_INSTANCE = CircuitBreakerRegistry()
    return _REGISTRY_INSTANCE


# ──── Retry decorator ──────────────────────────────────────────────────────


def retry_with_backoff(
    policy: Optional[RetryPolicy] = None,
) -> Callable:
    """Decorator that retries a callable with exponential backoff.

    Supports both synchronous and ``async`` callables.

    Args:
        policy: Retry configuration.  If ``None``, a default
            :class:`RetryPolicy` is used.

    Returns:
        A decorator that wraps the target function.

    Example::

        @retry_with_backoff(RetryPolicy(max_attempts=5))
        def call_api():
            ...

        @retry_with_backoff()
        async def async_call():
            ...
    """
    if policy is None:
        policy = RetryPolicy()

    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                last_exc: Optional[Exception] = None
                for attempt in range(policy.max_attempts):
                    try:
                        return await func(*args, **kwargs)
                    except policy.retryable_exceptions as exc:
                        last_exc = exc
                        if attempt < policy.max_attempts - 1:
                            delay = policy.backoff.next_delay(attempt)
                            logger.warning(
                                "Retry %d/%d for %s after %.2fs: %s",
                                attempt + 1,
                                policy.max_attempts,
                                func.__qualname__,
                                delay,
                                exc,
                            )
                            if policy.on_retry is not None:
                                policy.on_retry(attempt + 1, exc)
                            await asyncio.sleep(delay)
                        else:
                            logger.error(
                                "All %d attempts exhausted for %s: %s",
                                policy.max_attempts,
                                func.__qualname__,
                                exc,
                            )
                raise last_exc  # type: ignore[misc]

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[Exception] = None
            for attempt in range(policy.max_attempts):
                try:
                    return func(*args, **kwargs)
                except policy.retryable_exceptions as exc:
                    last_exc = exc
                    if attempt < policy.max_attempts - 1:
                        delay = policy.backoff.next_delay(attempt)
                        logger.warning(
                            "Retry %d/%d for %s after %.2fs: %s",
                            attempt + 1,
                            policy.max_attempts,
                            func.__qualname__,
                            delay,
                            exc,
                        )
                        if policy.on_retry is not None:
                            policy.on_retry(attempt + 1, exc)
                        time.sleep(delay)
                    else:
                        logger.error(
                            "All %d attempts exhausted for %s: %s",
                            policy.max_attempts,
                            func.__qualname__,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return sync_wrapper

    return decorator


# ──── Circuit-protected decorator ──────────────────────────────────────────


def circuit_protected(
    breaker: CircuitBreaker,
    fallback: Optional[Callable] = None,
) -> Callable:
    """Decorator that wraps a callable with circuit breaker protection.

    When the circuit is **open** (and no recovery-timeout has elapsed):

    * If *fallback* is provided it is called with the same arguments.
    * Otherwise :class:`CircuitOpenError` is raised.

    Supports both synchronous and ``async`` callables.

    Args:
        breaker: The :class:`CircuitBreaker` governing this call.
        fallback: Optional callable invoked when the circuit is open.

    Returns:
        A decorator that wraps the target function.

    Example::

        cb = CircuitBreaker(CircuitConfig(name="lmstudio"))

        @circuit_protected(cb, fallback=lambda: "service unavailable")
        def call_lmstudio():
            ...
    """

    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if not breaker.allow_request():
                    if fallback is not None:
                        logger.debug(
                            "Circuit '%s' open — calling fallback for %s",
                            breaker.name,
                            func.__qualname__,
                        )
                        result = fallback(*args, **kwargs)
                        if inspect.isawaitable(result):
                            return await result
                        return result
                    raise CircuitOpenError(
                        breaker.name,
                        breaker._open_since,
                        breaker.config.recovery_timeout,
                    )
                try:
                    result = await func(*args, **kwargs)
                    breaker.record_success()
                    return result
                except Exception as exc:
                    breaker.record_failure(exc)
                    raise

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not breaker.allow_request():
                if fallback is not None:
                    logger.debug(
                        "Circuit '%s' open — calling fallback for %s",
                        breaker.name,
                        func.__qualname__,
                    )
                    return fallback(*args, **kwargs)
                raise CircuitOpenError(
                    breaker.name,
                    breaker._open_since,
                    breaker.config.recovery_timeout,
                )
            try:
                result = func(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception as exc:
                breaker.record_failure(exc)
                raise

        return sync_wrapper

    return decorator


# ──── Convenience factory ──────────────────────────────────────────────────


def create_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    register: bool = True,
    **kwargs: Any,
) -> CircuitBreaker:
    """Create (and optionally register) a circuit breaker in one call.

    Args:
        name: Human-readable name.
        failure_threshold: Failures before opening.
        recovery_timeout: Seconds before half-open.
        register: If ``True`` the breaker is added to the global registry.
        **kwargs: Additional :class:`CircuitConfig` fields.

    Returns:
        A configured :class:`CircuitBreaker`.
    """
    config = CircuitConfig(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        **kwargs,
    )
    breaker = CircuitBreaker(config)
    if register:
        registry = get_breaker_registry()
        try:
            registry.register(name, breaker)
        except ValueError:
            return registry.get(name)  # type: ignore[return-value]
    return breaker


# ──── Module-level exports ─────────────────────────────────────────────────

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitConfig",
    "CircuitOpenError",
    "CircuitState",
    "ExponentialBackoff",
    "RetryPolicy",
    "StateTransition",
    "circuit_protected",
    "create_breaker",
    "get_breaker_registry",
    "retry_with_backoff",
]
