"""MCP tool decorator — unified error handling and serialisation at the edge.

All MCP tool functions should be wrapped with @mcp_tool. This eliminates
per-function try/except boilerplate and guarantees a consistent JSON response
schema for errors.

Version: v1.49.2 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.2 [2026-03-22] — Support async tool functions (await coroutines)
    v1.49.0 [2026-03-21] — Initial decorator with sync-only support
"""
import asyncio
import inspect
import json
import logging
from functools import wraps
from typing import Callable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    """Raised for predictable, expected tool failures (bad input, not-found, etc.).

    These are logged as warnings, not exceptions. Use this when the failure
    is the caller's fault and stack traces would be noise.
    """


# ──── Result Serialisation ────────────────────────────────────────────

def _serialise_result(result: object) -> str:
    """Convert a tool return value to a JSON string."""
    # Pydantic v2 BaseModel -> compact JSON
    if isinstance(result, BaseModel):
        return result.model_dump_json(indent=2)

    # Standard containers -> JSON with str fallback for non-serialisable types
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2, default=str)

    return str(result)


# ──── Decorator ───────────────────────────────────────────────────────

def mcp_tool(func: Callable) -> Callable:
    """Unified decorator for all MCP tool functions.

    Wraps the function to:
    1. Catch exceptions and log them at the appropriate level.
    2. Auto-serialise Pydantic v2 models via ``model_dump_json()``.
    3. Auto-serialise dicts/lists via ``json.dumps(default=str)``.
    4. Return a standardised error JSON on failure.
    5. Handle both sync and async tool functions transparently.

    All tools return ``str`` — either the serialised result or an error payload.

    Usage::

        @mcp_tool
        def my_tool(query: str) -> dict:
            if not query:
                raise ToolExecutionError("query is required")
            return {"result": do_work(query)}

        @mcp_tool
        async def my_async_tool(query: str) -> dict:
            return {"result": await async_work(query)}

    Error schema on ``ToolExecutionError``:
        ``{"ok": false, "error": "<message>"}``

    Error schema on unexpected exceptions:
        ``{"error": "<message>"}``
    """

    # v1.49.2 [2026-03-22] — Async-aware wrapper: if the decorated function
    # is a coroutine function, produce an async wrapper that awaits it.
    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> str:
            try:
                result = await func(*args, **kwargs)
                return _serialise_result(result)
            except ToolExecutionError as exc:
                logger.warning("Tool %s execution failed: %s", func.__name__, exc)
                return json.dumps({"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected crash in tool %s", func.__name__)
                return json.dumps({"error": str(exc)})

        return async_wrapper

    @wraps(func)
    def wrapper(*args, **kwargs) -> str:
        try:
            result = func(*args, **kwargs)
            return _serialise_result(result)

        except ToolExecutionError as exc:
            logger.warning("Tool %s execution failed: %s", func.__name__, exc)
            return json.dumps({"ok": False, "error": str(exc)})

        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected crash in tool %s", func.__name__)
            return json.dumps({"error": str(exc)})

    return wrapper
