"""MCP tool decorator — unified error handling and serialisation at the edge.

All MCP tool functions should be wrapped with @mcp_tool. This eliminates
per-function try/except boilerplate and guarantees a consistent JSON response
schema for errors.
"""
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


def mcp_tool(func: Callable) -> Callable:
    """Unified decorator for all MCP tool functions.

    Wraps the function to:
    1. Catch exceptions and log them at the appropriate level.
    2. Auto-serialise Pydantic v2 models via ``model_dump_json()``.
    3. Auto-serialise dicts/lists via ``json.dumps(default=str)``.
    4. Return a standardised error JSON on failure.

    All tools return ``str`` — either the serialised result or an error payload.

    Usage::

        @mcp_tool
        def my_tool(query: str) -> dict:
            if not query:
                raise ToolExecutionError("query is required")
            return {"result": do_work(query)}

    Error schema on ``ToolExecutionError``:
        ``{"ok": false, "error": "<message>"}``

    Error schema on unexpected exceptions:
        ``{"error": "<message>"}``
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> str:
        try:
            result = func(*args, **kwargs)

            # Pydantic v2 BaseModel → compact JSON
            if isinstance(result, BaseModel):
                return result.model_dump_json(indent=2)

            # Standard containers → JSON with str fallback for non-serialisable types
            if isinstance(result, (dict, list)):
                return json.dumps(result, indent=2, default=str)

            return str(result)

        except ToolExecutionError as exc:
            logger.warning("Tool %s execution failed: %s", func.__name__, exc)
            return json.dumps({"ok": False, "error": str(exc)})

        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected crash in tool %s", func.__name__)
            return json.dumps({"error": str(exc)})

    return wrapper
