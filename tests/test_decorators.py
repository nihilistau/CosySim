"""Tests for engine.mcp.decorators — @mcp_tool wrapper."""
import json
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from engine.mcp.decorators import ToolExecutionError, mcp_tool


# ──── Happy-path serialisation ────────────────────────────────────────────


def test_dict_result_is_json():
    @mcp_tool
    def fn():
        return {"status": "ok", "count": 3}

    result = fn()
    data = json.loads(result)
    assert data == {"status": "ok", "count": 3}


def test_list_result_is_json():
    @mcp_tool
    def fn():
        return [1, 2, 3]

    result = fn()
    assert json.loads(result) == [1, 2, 3]


def test_string_result_passthrough():
    @mcp_tool
    def fn():
        return "hello"

    assert fn() == "hello"


def test_none_result_becomes_string():
    @mcp_tool
    def fn():
        return None

    assert fn() == "None"


def test_pydantic_model_serialised():
    class Item(BaseModel):
        name: str
        value: int

    @mcp_tool
    def fn():
        return Item(name="widget", value=42)

    result = fn()
    data = json.loads(result)
    assert data["name"] == "widget"
    assert data["value"] == 42


def test_dict_with_non_serialisable_type():
    """datetime and other non-JSON types should be stringified via default=str."""
    from datetime import datetime

    @mcp_tool
    def fn():
        return {"ts": datetime(2024, 1, 1)}

    result = json.loads(fn())
    assert "2024" in result["ts"]


# ──── Error handling ──────────────────────────────────────────────────────


def test_tool_execution_error_returns_ok_false():
    @mcp_tool
    def fn():
        raise ToolExecutionError("item not found")

    result = json.loads(fn())
    assert result["ok"] is False
    assert "item not found" in result["error"]


def test_tool_execution_error_does_not_raise():
    @mcp_tool
    def fn():
        raise ToolExecutionError("boom")

    # Should not raise — must return JSON string
    out = fn()
    assert isinstance(out, str)


def test_bare_exception_returns_error_json():
    @mcp_tool
    def fn():
        raise ValueError("unexpected crash")

    result = json.loads(fn())
    assert "error" in result
    assert "unexpected crash" in result["error"]


def test_bare_exception_does_not_raise():
    @mcp_tool
    def fn():
        raise RuntimeError("oops")

    out = fn()
    assert isinstance(out, str)


# ──── Decorator transparency ──────────────────────────────────────────────


def test_wraps_preserves_function_name():
    @mcp_tool
    def my_special_tool():
        return "x"

    assert my_special_tool.__name__ == "my_special_tool"


def test_args_and_kwargs_forwarded():
    @mcp_tool
    def fn(a: str, b: int = 0) -> str:
        return f"{a}-{b}"

    assert fn("hello", b=7) == "hello-7"
