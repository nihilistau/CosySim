import logging
import json
from functools import wraps
from typing import Any, Callable
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    """Base exception for predictable tool failures."""

    pass


def mcp_tool(func: Callable) -> Callable:
    """
    A unified decorator for all MCP tools.
    1. Catches exceptions and logs them properly.
    2. Automatically converts Pydantic models or dicts to JSON strings.
    3. Standardizes the error schema.
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> str:
        try:
            result = func(*args, **kwargs)

            # Auto-serialize Pydantic models
            if isinstance(result, BaseModel):
                return result.model_dump_json(indent=2)

            # Auto-serialize standard dicts/lists
            if isinstance(result, (dict, list)):
                return json.dumps(result, indent=2, default=str)

            return str(result)

        except ToolExecutionError as e:
            logger.warning(f"Tool {func.__name__} execution failed: {e}")
            return json.dumps({"ok": False, "error": str(e)})
        except Exception as e:
            # Catch-all for unexpected errors
            logger.exception(f"Unexpected crash in tool {func.__name__}")
            return json.dumps({"error": str(e)})

    return wrapper
