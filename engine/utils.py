"""Shared utility functions for CosySim engine."""
from __future__ import annotations

import functools
import logging
import socket
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# v1.44.0 [2026-03-21] — DEPRECATED: Use get_lms_client() for inference
#   or get_config().get("lmstudio.api_token") for auth tokens.
def get_lmstudio_headers() -> dict:
    """Return HTTP headers for LMStudio API calls.

    .. deprecated:: v1.44.0
        Use ``engine.lmstudio.chat`` functions or ``get_lms_client()``
        instead.  This function remains for legacy callers outside the
        LMStudio subsystem.
    """
    import warnings
    warnings.warn(
        "get_lmstudio_headers() is deprecated — use get_lms_client() for inference "
        "or get_config().get('lmstudio.api_token') for auth tokens.",
        DeprecationWarning,
        stacklevel=2,
    )
    headers: dict = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        from engine.config import get_config
        token = get_config().get("lmstudio.api_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    except Exception:
        pass
    return headers


def port_is_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


# v1.58.0 [2026-06-11] — Atomic JSON persistence shared by all registry caches
# CONNECTS: nlm_rpc_mapper, rpcid_updater, nlm_automation
def atomic_write_json(path: "Path | str", data: Any, indent: int = 2) -> None:
    """Write *data* as JSON to *path* atomically (tmp file + os.replace).

    Multiple CosySim processes read these registry files concurrently; a
    plain ``open(path, "w")`` exposes readers to truncated/interleaved JSON
    ("Extra data" parse errors). ``os.replace`` is atomic on Windows + POSIX.

    Args:
        path: Destination file path.
        data: JSON-serialisable object.
        indent: JSON indentation level.
    """
    import json
    import os
    from pathlib import Path as _Path

    target = _Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)


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
