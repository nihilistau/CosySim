"""
Resilience — retry decorator and circuit breaker for external service calls.

Usage::

    from engine.services.resilience import retry, CircuitBreaker

    @retry(max_attempts=3, delay=1.0)
    def call_lmstudio(prompt):
        ...

    cb = CircuitBreaker("comfyui", failure_threshold=5, recovery_timeout=60)
    if cb.allow_request():
        try:
            result = call_comfyui()
            cb.record_success()
        except Exception:
            cb.record_failure()
"""
from __future__ import annotations

import enum
import functools
import logging
import threading
import time
from typing import Any, Callable, Optional, Type, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
#  Service Status
# ═══════════════════════════════════════════════════════════════════════════
class ServiceStatus(enum.Enum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"


# ═══════════════════════════════════════════════════════════════════════════
#  Retry Decorator
# ═══════════════════════════════════════════════════════════════════════════
def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator that retries a function on failure.

    Args:
        max_attempts: Total attempts (including first).
        delay: Initial delay between retries (seconds).
        backoff: Multiplier applied to delay after each retry.
        exceptions: Tuple of exception types to catch and retry.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts:
                        logger.warning(
                            "%s attempt %d/%d failed: %s — retrying in %.1fs",
                            fn.__qualname__, attempt, max_attempts, e, current_delay,
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            fn.__qualname__, max_attempts, e,
                        )
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════════════
#  Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════════
class CircuitBreaker:
    """Simple circuit breaker — blocks requests after repeated failures.

    States:
        CLOSED  — normal operation, requests allowed
        OPEN    — too many failures, requests blocked
        HALF_OPEN — recovery window, one test request allowed

    Args:
        name: Service identifier (for logging).
        failure_threshold: Failures before opening circuit.
        recovery_timeout: Seconds to wait before trying again (half-open).
    """

    def __init__(
        self,
        name: str = "service",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._lock = threading.Lock()
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._state = "closed"  # closed | open | half_open

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == "open":
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = "half_open"
            return self._state

    @property
    def status(self) -> ServiceStatus:
        s = self.state
        if s == "closed":
            return ServiceStatus.UP
        elif s == "half_open":
            return ServiceStatus.DEGRADED
        return ServiceStatus.DOWN

    def allow_request(self) -> bool:
        """Check if a request should be allowed."""
        s = self.state
        return s in ("closed", "half_open")

    def record_success(self) -> None:
        """Record a successful request — resets failure count."""
        with self._lock:
            self._failure_count = 0
            if self._state in ("open", "half_open"):
                logger.info("Circuit breaker '%s' closed (service recovered)", self.name)
            self._state = "closed"

    def record_failure(self) -> None:
        """Record a failed request — may open the circuit."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold and self._state == "closed":
                self._state = "open"
                logger.warning(
                    "Circuit breaker '%s' OPEN after %d failures — blocking for %.0fs",
                    self.name, self._failure_count, self.recovery_timeout,
                )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        with self._lock:
            self._failure_count = 0
            self._state = "closed"
