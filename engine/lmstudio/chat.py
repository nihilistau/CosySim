"""
engine.lmstudio.chat — Complete public API for LMStudio inference
==================================================================

Every scene, every agent, every service calls these functions.
No more scattered HTTP calls, no more URL construction, no more
manual auth headers.  One path, one client, one way.

Functions return either ``str`` (convenience) or ``LMSResponse``
(full metadata including latency, TPS, tokens, response_id).

Version: v1.44.0 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.44.0 [2026-03-21] — Added chat_response(), chat_stateful(),
                            chat_structured(), quick_reply(); wired
                            InferenceMonitor into every call
    v1.43.1 [2026-03-21] — Initial unified chat interface

Usage::

    from engine.lmstudio.chat import chat, chat_response, is_ready

    # Simple: messages in, text out
    text = chat(messages, system="You are Aria.", temperature=0.9)

    # Full metadata: messages in, LMSResponse out
    resp = chat_response(messages, system="You are Aria.")
    print(resp.content, resp.latency_ms, resp.server_tps)

    # Stateful: server retains KV cache between calls
    resp1 = chat_stateful("Hello!", system="You are Aria.")
    resp2 = chat_stateful("What's your name?",
                          previous_response_id=resp1.response_id)

    # Structured: JSON schema enforcement
    resp = chat_structured(messages, schema={"type": "object", ...})

    # One-liner
    text = quick_reply("What is 2+2?")
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


# ── Internal: metrics recording ───────────────────────────────────────

def _record_metrics(
    resp: Any,
    *,
    agent_id: str = "chat_facade",
    tier: str = "direct",
    task_type: str = "chat",
    success: bool = True,
    error: str = "",
) -> None:
    """Feed InferenceMonitor with response metrics (best-effort)."""
    try:
        from engine.lmstudio.inference_monitor import get_inference_monitor
        monitor = get_inference_monitor()
        monitor.record(
            agent_id=agent_id,
            model=getattr(resp, "model", "") or "unknown",
            tier=tier,
            task_type=task_type,
            latency_ms=getattr(resp, "latency_ms", 0.0) or 0.0,
            tokens=getattr(resp, "output_tokens", 0) or 0,
            tps=getattr(resp, "server_tps", 0.0) or 0.0,
            success=success,
            error=error,
        )
    except Exception:
        logger.debug("InferenceMonitor record failed", exc_info=True)


# ── Core Chat (returns LMSResponse) ──────────────────────────────────

def chat_response(
    messages: List[Dict[str, Any]],
    *,
    system: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
    store: Optional[bool] = None,
    stop_strings: Optional[List[str]] = None,
    response_format: Optional[Dict] = None,
    integrations: Optional[List[Dict]] = None,
) -> Any:
    """Send messages to LMStudio, get full LMSResponse back.

    Returns the complete ``LMSResponse`` with content, latency, TPS,
    token counts, response_id, and all metadata.  On failure returns
    an ``LMSResponse`` with ``content=""`` and ``finish_reason="error"``.

    Args:
        messages: OpenAI-style message list.
        system: Convenience — prepended as a system message.
        temperature: Sampling temperature (0.0–2.0).
        max_tokens: Max output tokens.
        model: Explicit model override.
        store: Server-side conversation storage.
        stop_strings: Sequences that stop generation.
        response_format: JSON schema for structured output.
        integrations: MCP integrations for tool calling.

    Returns:
        LMSResponse object (always non-None).
    """
    from engine.lmstudio.lms_client import get_lms_client
    from engine.lmstudio.lms_models import LMSResponse

    if system:
        messages = [{"role": "system", "content": system}, *messages]

    try:
        client = get_lms_client()
        resp = client.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            store=store,
            stop_strings=stop_strings,
            response_format=response_format,
            integrations=integrations,
        )
        logger.debug(
            "chat_response() → %d chars (model=%s, %.0fms, %.1f TPS)",
            len(resp.content or ""),
            resp.model or "?",
            resp.latency_ms or 0,
            resp.server_tps or 0,
        )
        _record_metrics(resp)
        return resp

    except ConnectionError as exc:
        logger.error("chat_response() failed — LMStudio not reachable")
        _record_metrics(LMSResponse(), success=False, error=str(exc))
        return LMSResponse(content="", finish_reason="error")
    except Exception as exc:
        logger.error("chat_response() failed: %s", exc, exc_info=True)
        _record_metrics(LMSResponse(), success=False, error=str(exc))
        return LMSResponse(content="", finish_reason="error")


# ── Convenience Chat (returns str) ───────────────────────────────────

def chat(
    messages: List[Dict[str, Any]],
    *,
    system: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
    store: Optional[bool] = None,
    stop_strings: Optional[List[str]] = None,
    response_format: Optional[Dict] = None,
    integrations: Optional[List[Dict]] = None,
) -> str:
    """Send messages to LMStudio, get text back.

    Convenience wrapper around ``chat_response()`` that returns just
    the content string.  Empty string on failure (never None).
    """
    resp = chat_response(
        messages,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
        store=store,
        stop_strings=stop_strings,
        response_format=response_format,
        integrations=integrations,
    )
    return resp.content or ""


# ── Stateful Chat ────────────────────────────────────────────────────

def chat_stateful(
    user_message: str,
    *,
    previous_response_id: Optional[str] = None,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Any:
    """Stateful chat — server retains KV cache between calls.

    First call: omit ``previous_response_id`` → server creates new thread.
    Subsequent: pass the ``response_id`` from the previous response.

    Args:
        user_message: The user's message text.
        previous_response_id: response_id from previous call (for continuations).
        system: System prompt (only used on first call of a thread).
        model: Explicit model override.
        temperature: Sampling temperature.
        max_tokens: Max output tokens.

    Returns:
        LMSResponse with response_id for chaining.
    """
    from engine.lmstudio.lms_client import get_lms_client
    from engine.lmstudio.lms_models import LMSResponse
    from engine.lmstudio.inference_config import InferenceConfig

    try:
        client = get_lms_client()
        cfg = InferenceConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ) if temperature is not None or max_tokens is not None else None

        resp = client.chat_stateful(
            user_message,
            previous_response_id=previous_response_id,
            system=system,
            config=cfg,
            model=model,
        )
        _record_metrics(resp, task_type="stateful_chat")
        return resp

    except Exception as exc:
        logger.error("chat_stateful() failed: %s", exc, exc_info=True)
        _record_metrics(LMSResponse(), success=False, error=str(exc))
        return LMSResponse(content="", finish_reason="error")


# ── Structured Chat ──────────────────────────────────────────────────

def chat_structured(
    messages: List[Dict[str, Any]],
    schema: Dict[str, Any],
    *,
    system: Optional[str] = None,
    schema_name: str = "response",
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Any:
    """Chat with JSON schema enforcement for structured output.

    Args:
        messages: OpenAI-style message list.
        schema: JSON schema dict that the output must conform to.
        system: Convenience system prompt.
        schema_name: Name for the schema (default: "response").
        model: Explicit model override.
        temperature: Sampling temperature.
        max_tokens: Max output tokens.

    Returns:
        LMSResponse with JSON content conforming to the schema.
    """
    from engine.lmstudio.lms_client import get_lms_client
    from engine.lmstudio.lms_models import LMSResponse

    if system:
        messages = [{"role": "system", "content": system}, *messages]

    try:
        client = get_lms_client()
        resp = client.chat_structured(
            messages,
            schema,
            schema_name=schema_name,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        _record_metrics(resp, task_type="structured")
        return resp

    except Exception as exc:
        logger.error("chat_structured() failed: %s", exc, exc_info=True)
        _record_metrics(LMSResponse(), success=False, error=str(exc))
        return LMSResponse(content="", finish_reason="error")


# ── Quick Reply ──────────────────────────────────────────────────────

def quick_reply(
    prompt: str,
    *,
    system: str = "You are a helpful assistant.",
    **kwargs: Any,
) -> str:
    """One-shot: system + user prompt → reply string.

    Args:
        prompt: The user's message.
        system: System prompt (default: helpful assistant).
        **kwargs: Forwarded to ``chat()``.

    Returns:
        Response text string.
    """
    return chat(
        [{"role": "user", "content": prompt}],
        system=system,
        **kwargs,
    )


# ── Streaming Chat ───────────────────────────────────────────────────

def chat_stream(
    messages: List[Dict[str, Any]],
    *,
    system: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
    on_event: Optional[Callable] = None,
) -> Generator[str, None, None]:
    """Stream chat response chunks from LMStudio.

    Yields content strings (message deltas).

    Args:
        messages: OpenAI-style message list.
        system: Convenience system prompt.
        temperature: Sampling temperature.
        max_tokens: Max output tokens.
        model: Explicit model override.
        on_event: Optional callback for typed SSE events.

    Yields:
        Content string chunks.
    """
    from engine.lmstudio.lms_client import get_lms_client

    if system:
        messages = [{"role": "system", "content": system}, *messages]

    try:
        client = get_lms_client()
        gen = client.chat_stream(
            messages,
            model=model,
            on_event=on_event,
        )
        yield from gen

    except ConnectionError:
        logger.error("chat_stream() failed — LMStudio not reachable")
    except Exception as exc:
        logger.error("chat_stream() failed: %s", exc, exc_info=True)


# ── Health Check ─────────────────────────────────────────────────────

def is_ready() -> bool:
    """Check if LMStudio is online and has a model loaded.

    Use this instead of hand-rolling HTTP health checks.
    """
    from engine.lmstudio.lms_client import get_lms_client
    try:
        client = get_lms_client()
        if not client.is_available():
            return False
        model = client.resolve_model()
        return bool(model)
    except Exception:
        return False


# ── Model Listing ────────────────────────────────────────────────────

def get_models(loaded_only: bool = True) -> List[Any]:
    """List available LMStudio models.

    Returns list of LMSModel objects.  Empty list on failure.
    """
    from engine.lmstudio.lms_client import get_lms_client
    try:
        return get_lms_client().get_models(loaded_only=loaded_only)
    except Exception:
        return []
