"""
ToolFactory — Ephemeral and one-shot OpenAI function-calling tools

Converts plain Python callables into OpenAI-compatible function specs and
handles the full tool-call loop (generate → call → feed results → generate)
against the LMStudio REST v1 API.

Unlike ``@skill`` (which registers tools permanently in the registry) or
``@mcp.tool()`` (which runs in a separate server process), tools created here
are:
  - **Ephemeral** — created for one request, then discarded
  - **In-process** — executed directly in Python, no network hop
  - **Type-inferred** — schema is auto-built from Python type hints + docstring

This is useful for one-off agent tools, dynamic workflow steps, or wrapping
any callable (lambda, partial, method) without changing the registry.

Usage::

    from engine.lmstudio.tool_factory import tool, run_with_tools

    # 1. Wrap any callable as a tool
    @tool
    def get_weather(city: str) -> str:
        \"\"\"Return current weather for a city.\"\"\"
        return f"Sunny, 22°C in {city}"

    # 2. Run a chat request that can use the tool
    reply = run_with_tools(
        messages=[{"role": "user", "content": "What's the weather in Paris?"}],
        tools=[get_weather],
    )
    print(reply)  # "The current weather in Paris is Sunny, 22°C."

    # 3. Ephemeral: create and discard inline
    from engine.lmstudio.tool_factory import from_callable

    spec = from_callable(lambda x: x * 2, name="double", description="Double a number")
    reply = run_with_tools(messages, tools=[spec])
"""
from __future__ import annotations

import inspect
import json
import logging
import typing
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, get_type_hints

logger = logging.getLogger(__name__)

# Python → JSON Schema type mapping
_PY_TO_JSON: Dict[Any, str] = {
    str:   "string",
    int:   "integer",
    float: "number",
    bool:  "boolean",
    list:  "array",
    dict:  "object",
}


# ── Tool spec container ─────────────────────────────────────────────────

@dataclass
class ToolSpec:
    """An OpenAI-compatible function tool spec with its backing callable."""
    name:        str
    description: str
    parameters:  Dict   # JSON Schema object
    fn:          Callable

    def to_openai_dict(self) -> Dict:
        """Build the dict that goes into the ``tools`` field of the request."""
        return {
            "type": "function",
            "function": {
                "name":        self.name,
                "description": self.description,
                "parameters":  self.parameters,
            },
        }

    def call(self, **kwargs) -> str:
        """Execute the tool and return a string result."""
        try:
            result = self.fn(**kwargs)
            return str(result)
        except Exception as exc:
            return f"Tool error: {exc}"

    def __repr__(self) -> str:
        params = list(self.parameters.get("properties", {}).keys())
        return f"<ToolSpec {self.name!r} params={params}>"


# ── Schema builder ──────────────────────────────────────────────────────

def _build_schema(fn: Callable) -> Dict:
    """
    Build a JSON Schema ``object`` from a function's type annotations.

    Rules:
      - Parameters with defaults are marked optional.
      - Only positional/keyword parameters are included (no *args/**kwargs).
      - Annotated types are mapped to JSON Schema primitives.
      - Unannotated parameters default to ``{"type": "string"}``.
    """
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:
        hints = {}

    properties: Dict[str, Dict] = {}
    required: List[str] = []

    for param_name, param in sig.parameters.items():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        python_type = hints.get(param_name)
        # Unwrap Optional[X] → X
        origin = getattr(python_type, "__origin__", None)
        if origin is typing.Union:
            args = [a for a in python_type.__args__ if a is not type(None)]
            python_type = args[0] if args else str

        json_type = _PY_TO_JSON.get(python_type, "string")
        prop: Dict[str, Any] = {"type": json_type}

        # Use param docstring-style inline description if available
        # (falls through to empty string — callers can enrich it)
        properties[param_name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


# ── from_callable / @tool decorator ────────────────────────────────────

def from_callable(
    fn: Callable,
    *,
    name:        Optional[str] = None,
    description: Optional[str] = None,
) -> ToolSpec:
    """
    Convert any Python callable to a ``ToolSpec``.

    Args:
        fn:          The callable to wrap.
        name:        Override the tool name (default: ``fn.__name__``).
        description: Override the description (default: first docstring line).

    Returns:
        ``ToolSpec`` ready to use in ``run_with_tools()``.
    """
    tool_name = name or getattr(fn, "__name__", "tool")
    doc = description or (inspect.getdoc(fn) or "").split("\n")[0].strip()
    schema = _build_schema(fn)
    return ToolSpec(name=tool_name, description=doc, parameters=schema, fn=fn)


def tool(fn: Optional[Callable] = None, *, name=None, description=None):
    """
    Decorator that wraps a function as a ``ToolSpec``.

    Can be used with or without arguments::

        @tool
        def my_func(x: int) -> str: ...

        @tool(name="custom_name", description="Does X")
        def my_func(x: int) -> str: ...
    """
    def _wrap(f: Callable) -> ToolSpec:
        return from_callable(f, name=name, description=description)

    if fn is not None:
        return _wrap(fn)
    return _wrap


# ── Tool execution helper ───────────────────────────────────────────────

def execute_tool_calls(
    tool_calls: List[Dict],
    available: List[ToolSpec],
) -> List[Dict]:
    """
    Execute tool call requests from an LLM response.

    Args:
        tool_calls: The ``message.tool_calls`` list from the API response.
        available:  List of ``ToolSpec`` objects whose names may be called.

    Returns:
        A list of ``{"role": "tool", "content": ..., "tool_call_id": ...}``
        messages to append to the conversation and continue generation.
    """
    tool_map = {spec.name: spec for spec in available}
    result_messages = []

    for call in tool_calls:
        call_id   = call.get("id", "")
        func_info = call.get("function", {})
        func_name = func_info.get("name", "")
        args_str  = func_info.get("arguments", "{}")

        spec = tool_map.get(func_name)
        if spec is None:
            content = f"Unknown tool: {func_name!r}"
            logger.warning("LLM called unknown tool %r", func_name)
        else:
            try:
                kwargs = json.loads(args_str)
            except json.JSONDecodeError:
                kwargs = {}
            logger.debug("Executing tool %r with %s", func_name, kwargs)
            content = spec.call(**kwargs)

        result_messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": content,
        })

    return result_messages


# ── Full tool-call loop ─────────────────────────────────────────────────

def run_with_tools(
    messages: List[Dict],
    tools: List[Any],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    max_rounds: int = 6,
    integrations: Optional[List[Dict]] = None,
    client=None,
) -> str:
    """
    Run a multi-turn chat with tool-calling support against LMStudio REST v1.

    Handles the full loop:
      1. Send request with tool specs attached
      2. If model asks to call a tool → execute it, append result, repeat
      3. When model produces a final text response → return it

    Args:
        messages:      Initial message list (system + user).
        tools:         ``ToolSpec`` objects (or plain callables that will be
                       auto-wrapped via ``from_callable``).
        model:         Model to use (auto-resolved if None).
        temperature:   Sampling temperature.
        max_tokens:    Max tokens per generation step.
        max_rounds:    Max tool-call rounds to prevent loops (default 6).
        integrations:  Additional MCP integrations (combined with tools).
        client:        ``LMStudioClient`` to use (default: global singleton).

    Returns:
        Final text reply from the model, or empty string on failure.
    """
    if client is None:
        from engine.lmstudio.client_v2 import get_lmstudio_client
        client = get_lmstudio_client()

    # Normalise: wrap plain callables into ToolSpec
    tool_specs: List[ToolSpec] = []
    for t in tools:
        if isinstance(t, ToolSpec):
            tool_specs.append(t)
        elif callable(t):
            tool_specs.append(from_callable(t))
        else:
            logger.warning("run_with_tools: skipping non-callable tool %r", t)

    openai_tools = [spec.to_openai_dict() for spec in tool_specs]
    thread_messages = list(messages)

    for round_num in range(max_rounds):
        try:
            resp = client.chat(
                thread_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=openai_tools if openai_tools else None,
                integrations=integrations,
            )
        except Exception as exc:
            logger.error("run_with_tools chat failed on round %d: %s", round_num, exc)
            return ""

        finish = resp.finish_reason

        # Terminal: model gave a text answer
        if finish in ("stop", "length", "") or not finish:
            return resp.content.strip()

        # Model wants to call tools
        if finish == "tool_calls":
            # We need the raw response to get tool_calls — re-request raw
            raw = _raw_chat(client, thread_messages, openai_tools, model, temperature, max_tokens, integrations)
            if raw is None:
                return resp.content.strip()

            tool_calls_payload = (
                raw.get("choices", [{}])[0]
                .get("message", {})
                .get("tool_calls", [])
            )
            if not tool_calls_payload:
                return resp.content.strip()

            # Append assistant message with tool_calls
            thread_messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls_payload,
            })

            # Execute and append tool results
            result_msgs = execute_tool_calls(tool_calls_payload, tool_specs)
            thread_messages.extend(result_msgs)
            logger.debug("round %d: executed %d tool calls", round_num, len(tool_calls_payload))
            continue

        # Unexpected finish reason — return whatever content we have
        logger.debug("Unexpected finish_reason %r on round %d", finish, round_num)
        return resp.content.strip()

    logger.warning("run_with_tools hit max_rounds=%d without a final answer", max_rounds)
    return ""


def _raw_chat(client, messages, tools, model, temperature, max_tokens, integrations) -> Optional[Dict]:
    """
    Issue a raw HTTP request and return the full parsed JSON body.
    Needed to extract ``tool_calls`` which ``ChatResponse`` doesn't carry.
    """
    import httpx
    payload = client._build_payload(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        integrations=integrations,
        stream=False,
    )
    try:
        r = client._client.post(
            f"{client.base_url}/v1/chat/completions",
            json=payload,
            timeout=client.timeout,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("_raw_chat failed: %s", exc)
        return None
