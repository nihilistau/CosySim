"""Shared utility functions for CosySim engine."""
from __future__ import annotations

import functools
import logging
import socket
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def port_is_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


def requires_service(
    service_name: str,
    fallback: Any = None,
) -> Callable:
    """Decorator: returns *fallback* value if *service_name* is unavailable.

    Catches ``ImportError``, ``ConnectionError``, and ``OSError`` so that
    callers degrade gracefully when an external service is down.

    Args:
        service_name: Human-readable service name for log messages.
        fallback: Value to return on failure.  If callable, it is invoked
            with no arguments to produce the fallback value.

    Example::

        @requires_service("Nexus KMS", fallback=[])
        def search_nexus(query: str) -> list:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning(
                    "%s unavailable for %s: %s",
                    service_name,
                    fn.__name__,
                    exc,
                )
                return fallback() if callable(fallback) else fallback
        return wrapper
    return decorator
