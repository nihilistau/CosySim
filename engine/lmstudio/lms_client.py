"""
LMSClient v2.7 — Native LMStudio v1 REST API client (v1-only)

**CosySim Framework v2.7** — all inference through ``/api/v1/chat``.

Features:

* **Stateful chats** — ``previous_response_id`` / ``response_id`` for
  server-managed context; conversation branching by reusing any historical
  response_id.
* **Store / no-store** — ``store: false`` for stateless one-off requests;
  ``store: true`` (default) returns a ``response_id`` for continuations.
* **Typed SSE streaming** — proper event parsing for chat.start,
  model_load.*, prompt_processing.*, reasoning.*, tool_call.*,
  message.*, error, chat.end (full aggregated result).
* **Ephemeral MCP** — per-request ``integrations`` for tool calling.
* **Full param control** — top_k, min_p, repeat_penalty, reasoning mode,
  context_length override per request.
* **Structured output** — JSON schema enforcement at logit level.
* **Image input** — VLM support via ``{type: "image", data_url: "..."}``.
* **Speculative decoding** — draft model for 2-3x throughput.

Usage::

    from engine.lmstudio.lms_client import get_lms_client

    client = get_lms_client()
    resp = client.chat(messages)
    resp = client.chat_stateful("Hello!", previous_response_id=prev_id)

    # Streaming with typed events
    for chunk in client.chat_stream(messages, on_event=my_handler):
        print(chunk, end="")

    # Stateless one-shot (no server-side storage)
    resp = client.chat(messages, store=False)

    # Conversation branching
    resp2 = client.chat_stateful("Branch here", previous_response_id=old_resp_id)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional

import httpx

from engine.lmstudio.inference_config import InferenceConfig, LoadConfig

logger = logging.getLogger(__name__)

# Cache TTL for model resolution
_MODEL_CACHE_TTL = 30.0


# ── Response dataclasses ────────────────────────────────────────────────

@dataclass
class LMSResponse:
    """Result of a native v1 chat call."""
    content: str = ""
    model: str = ""
    finish_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    request_id: str = ""
    response_id: str = ""          # for stateful chats (starts with "resp_")
    reasoning_content: str = ""    # thinking model CoT
    reasoning_tokens: int = 0      # tokens spent on reasoning
    tool_calls: List[Dict] = field(default_factory=list)
    # Native v1 stats (from chat.end or non-streaming response)
    server_tps: float = 0.0               # tokens_per_second from server
    time_to_first_token_s: float = 0.0    # time_to_first_token_seconds
    model_load_time_s: float = 0.0        # model_load_time_seconds (0 if already loaded)

    @property
    def tokens_per_second(self) -> float:
        """Use server-reported TPS if available, else estimate from latency."""
        if self.server_tps > 0:
            return self.server_tps
        if self.latency_ms > 0 and self.output_tokens > 0:
            return self.output_tokens / (self.latency_ms / 1000.0)
        return 0.0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def is_stateful(self) -> bool:
        """Whether this response has a response_id for continuations."""
        return bool(self.response_id and self.response_id.startswith("resp_"))

    def _apply_v1_stats(self, stats: Dict) -> None:
        """Apply native v1 stats dict to this response."""
        self.input_tokens = stats.get("input_tokens", self.input_tokens)
        self.output_tokens = stats.get("total_output_tokens", self.output_tokens)
        self.reasoning_tokens = stats.get("reasoning_output_tokens", self.reasoning_tokens)
        self.total_tokens = self.input_tokens + self.output_tokens
        self.server_tps = stats.get("tokens_per_second", 0.0)
        self.time_to_first_token_s = stats.get("time_to_first_token_seconds", 0.0)
        self.model_load_time_s = stats.get("model_load_time_seconds", 0.0) or 0.0


@dataclass
class LMSStreamEvent:
    """A single typed event from the native v1 SSE stream.

    LMStudio v1 streaming sends ``event: <type>\\ndata: <json>`` pairs.
    Event types (in order they may appear):

    - chat.start, chat.end
    - model_load.start, model_load.progress, model_load.end
    - prompt_processing.start, prompt_processing.progress, prompt_processing.end
    - reasoning.start, reasoning.delta, reasoning.end
    - tool_call.start, tool_call.arguments, tool_call.success, tool_call.failure
    - message.start, message.delta, message.end
    - error
    """
    event_type: str = ""
    # Content deltas (message.delta, reasoning.delta)
    content: str = ""
    # Progress (model_load.progress, prompt_processing.progress) — 0.0 to 1.0
    progress: float = 0.0
    # Model info (chat.start, model_load.*)
    model_instance_id: str = ""
    load_time_seconds: float = 0.0  # model_load.end
    # Tool call fields
    tool_name: str = ""
    tool_arguments: Optional[Dict] = None
    tool_output: str = ""
    tool_provider: Optional[Dict] = None
    # Error fields
    error: Optional[Dict] = None
    # chat.end aggregated result
    stats: Optional[Dict] = None
    result: Optional[Dict] = None
    response_id: str = ""
    # Terminal flag
    is_done: bool = False


@dataclass
class LMSModelInfo:
    """Information about a loaded model."""
    model_id: str = ""
    architecture: str = ""
    parameters: str = ""
    context_length: int = 0
    supports_vision: bool = False
    supports_tool_use: bool = False
    quantization: str = ""


# ── Main client ─────────────────────────────────────────────────────────

class LMSClient:
    """
    Native LMStudio v1 REST API client (v2 framework — v1-only).

    Endpoints used:
    - ``/api/v1/chat``          — All inference (stateful + stateless)
    - ``/api/v1/models``        — List loaded models
    - ``/api/v1/models/load``   — Load a model
    - ``/api/v1/models/unload`` — Unload a model

    Tools are accessed via ephemeral MCP ``integrations``, not the
    ``tools`` field.  Set ``lmstudio.cosysim_mcp_url`` in config.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = 120.0,
        config=None,
    ) -> None:
        if config is None:
            try:
                from engine.config import get_config
                config = get_config()
            except Exception:
                config = None

        if base_url is None:
            if config:
                host = config.get("lmstudio.host", "127.0.0.1")
                port = int(config.get("lmstudio.port", 1234))
                base_url = f"http://{host}:{port}"
            else:
                base_url = "http://127.0.0.1:1234"

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._config = config

        # Defaults from config
        self._default_model = (config.get("llm.model", "") if config else "")
        self._mcp_enabled = bool(config.get("lmstudio.mcp_enabled", True) if config else True)
        self._cosysim_mcp_url = (config.get("lmstudio.cosysim_mcp_url", "") if config else "")

        # Inference defaults from config
        self._inference_defaults = InferenceConfig.from_yaml() if config else InferenceConfig()

        # HTTP client with connection pooling
        self._client = httpx.Client(timeout=timeout)

        # Model cache
        self._resolved_model: Optional[str] = None
        self._resolved_at: float = 0.0

    def close(self) -> None:
        self._client.close()

    # ── Health & Model Info ─────────────────────────────────────────

    def is_available(self) -> bool:
        """Check if LMStudio is responding on the native v1 API."""
        try:
            r = self._client.get(f"{self.base_url}/api/v1/models", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def get_models(self, loaded_only: bool = True) -> List[Dict[str, Any]]:
        """List models via native v1 API.

        Args:
            loaded_only: If True (default), return only currently loaded models.
                         If False, return all downloaded models.

        Returns list of dicts. For loaded models, ``id`` is taken from the
        first ``loaded_instances[].id`` so it can be passed to ``/api/v1/chat``.
        """
        try:
            r = self._client.get(f"{self.base_url}/api/v1/models", timeout=5.0)
            r.raise_for_status()
            data = r.json()

            # v1 returns {"models": [...]} with rich metadata
            raw_models = data.get("models", data.get("data", data if isinstance(data, list) else []))

            results: List[Dict[str, Any]] = []
            for m in raw_models:
                instances = m.get("loaded_instances", [])
                is_loaded = len(instances) > 0

                if loaded_only and not is_loaded:
                    continue

                entry: Dict[str, Any] = {
                    "key": m.get("key", ""),
                    "display_name": m.get("display_name", m.get("key", "")),
                    "type": m.get("type", "llm"),
                    "architecture": m.get("architecture", ""),
                    "params": m.get("params_string", ""),
                    "loaded": is_loaded,
                }
                # Use instance id for loaded models (this is what /api/v1/chat wants)
                if instances:
                    entry["id"] = instances[0].get("id", m.get("key", ""))
                    entry["config"] = instances[0].get("config", {})
                    entry["context_length"] = instances[0].get("config", {}).get("context_length", 0)
                else:
                    entry["id"] = m.get("key", "")

                results.append(entry)

            return results
        except Exception as exc:
            logger.debug("get_models failed: %s", exc)
            return []

    def get_model_info(self, model_id: Optional[str] = None) -> LMSModelInfo:
        """Get detailed info about a model via SDK."""
        info = LMSModelInfo(model_id=model_id or self.resolve_model())
        try:
            import lmstudio as lms
            handle = lms.llm(info.model_id) if info.model_id else lms.llm()
            mi = handle.get_model_info()
            info.architecture = getattr(mi, "architecture", "")
            info.parameters = getattr(mi, "parameters", "")
            info.context_length = handle.get_context_length()
            info.supports_vision = getattr(mi, "vision", False)
            info.supports_tool_use = getattr(mi, "tool_use", False)
        except Exception as exc:
            logger.debug("get_model_info failed: %s", exc)
            # Fallback context length
            if not info.context_length:
                info.context_length = int(
                    self._config.get("lmstudio.default_load_opts.context_length", 4096)
                    if self._config else 4096
                )
        return info

    def resolve_model(self, hint: Optional[str] = None) -> str:
        """Resolve best model ID to use."""
        if hint:
            return hint
        now = time.monotonic()
        if self._resolved_model and (now - self._resolved_at) < _MODEL_CACHE_TTL:
            return self._resolved_model

        models = self.get_models()
        model_ids = [m.get("id", "") for m in models if m.get("id")]

        if self._default_model and self._default_model in model_ids:
            resolved = self._default_model
        elif model_ids:
            resolved = model_ids[0]
        else:
            resolved = self._default_model or ""

        self._resolved_model = resolved
        self._resolved_at = now
        return resolved

    def invalidate_model_cache(self) -> None:
        self._resolved_at = 0.0
        self._resolved_model = None

    # ── Chat (non-streaming) ────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        config: Optional[InferenceConfig] = None,
        model: Optional[str] = None,
        # Convenience overrides (merged into config)
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        integrations: Optional[List[Dict]] = None,
        response_format: Optional[Dict] = None,
        store: Optional[bool] = None,
    ) -> LMSResponse:
        """
        Send a chat completion via native ``/api/v1/chat``.

        All inference goes through the v1 API.  For tool calling, attach
        MCP servers via ``integrations`` (ephemeral or plugin).

        Args:
            store: If False, server won't store the conversation (no response_id
                   returned).  Default None means server default (True).
        """
        # Build effective config
        effective = self._build_config(config, temperature=temperature,
                                        max_tokens=max_tokens,
                                        integrations=integrations,
                                        response_format=response_format,
                                        model=model)
        if store is not None:
            effective.store = store

        request_id = str(uuid.uuid4())[:8]
        t0 = time.perf_counter()

        resp = self._chat_native(messages, effective)

        resp.latency_ms = (time.perf_counter() - t0) * 1000
        resp.request_id = request_id

        self._publish_inference_event(resp)
        return resp

    def chat_stateful(
        self,
        user_message: str,
        *,
        previous_response_id: Optional[str] = None,
        system: Optional[str] = None,
        config: Optional[InferenceConfig] = None,
        model: Optional[str] = None,
    ) -> LMSResponse:
        """
        Stateful chat: server keeps context, you just send the new message.

        First call: omit ``previous_response_id`` → server creates new thread.
        Subsequent: pass the ``response_id`` from the previous response.

        Uses native v1 format: ``input`` + ``system_prompt`` + ``store: true``.
        """
        effective = self._build_config(config, model=model)
        if previous_response_id:
            effective.previous_response_id = previous_response_id

        resolved = self.resolve_model(effective.model)

        payload: Dict[str, Any] = {
            "model": resolved,
            "input": user_message,
            "stream": False,
            "store": True,
        }
        if system and not previous_response_id:
            payload["system_prompt"] = system
        payload.update(effective.to_native_v1())

        try:
            r = self._client.post(
                f"{self.base_url}/api/v1/chat",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except httpx.ConnectError:
            raise ConnectionError(f"Cannot connect to LMStudio at {self.base_url}")
        except httpx.HTTPStatusError as exc:
            logger.error("Native v1 HTTP %d: %s", exc.response.status_code, exc.response.text[:200])
            raise

        return self._parse_native_response(data, resolved)

    # ── Chat (streaming) ────────────────────────────────────────────

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        config: Optional[InferenceConfig] = None,
        model: Optional[str] = None,
        on_event: Optional[Callable[[LMSStreamEvent], None]] = None,
        store: Optional[bool] = None,
    ) -> Generator[str, None, LMSResponse]:
        """
        Stream a chat response via native ``/api/v1/chat`` with typed SSE events.

        Yields content strings (message deltas).  Optional ``on_event``
        callback receives **every** typed event (model_load, prompt_processing,
        reasoning, tool_call, message, error, etc.).

        The generator's return value is an LMSResponse with full stats
        extracted from the ``chat.end`` event.
        """
        effective = self._build_config(config, model=model)
        if store is not None:
            effective.store = store
        resolved_model = self.resolve_model(effective.model)
        return self._stream_native(messages, effective, resolved_model, on_event)

    def chat_stream_stateful(
        self,
        user_message: str,
        *,
        previous_response_id: Optional[str] = None,
        system: Optional[str] = None,
        config: Optional[InferenceConfig] = None,
        model: Optional[str] = None,
        on_event: Optional[Callable[[LMSStreamEvent], None]] = None,
    ) -> Generator[str, None, LMSResponse]:
        """
        Stream a stateful chat — server keeps context, you just send new message.

        Combines ``chat_stateful()`` semantics with ``chat_stream()`` streaming.
        Always stores (``store: true``) so a ``response_id`` is returned.
        """
        effective = self._build_config(config, model=model)
        if previous_response_id:
            effective.previous_response_id = previous_response_id
        effective.store = True

        resolved = self.resolve_model(effective.model)

        payload: Dict[str, Any] = {
            "model": resolved,
            "input": user_message,
            "stream": True,
            "store": True,
        }
        if system and not previous_response_id:
            payload["system_prompt"] = system
        payload.update(effective.to_native_v1())

        return self._stream_v1_raw(payload, resolved, on_event)

    # ── Convenience wrappers ────────────────────────────────────────

    def quick_reply(
        self,
        user_message: str,
        *,
        system: str = "You are a helpful assistant.",
        **kwargs,
    ) -> str:
        """One-shot: system + user → reply string."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        return self.chat(messages, **kwargs).content

    def chat_with_mcp(
        self,
        messages: List[Dict[str, Any]],
        mcp_servers: Optional[List[Dict]] = None,
        **kwargs,
    ) -> LMSResponse:
        """Chat with MCP integrations."""
        if mcp_servers is None and self._cosysim_mcp_url:
            mcp_servers = [{"type": "ephemeral_mcp", "server_url": self._cosysim_mcp_url}]
        return self.chat(messages, integrations=mcp_servers, **kwargs)

    def chat_structured(
        self,
        messages: List[Dict[str, Any]],
        schema: Dict[str, Any],
        *,
        schema_name: str = "response",
        **kwargs,
    ) -> LMSResponse:
        """Chat with JSON schema enforcement for structured output."""
        from engine.lmstudio.inference_config import json_schema_format
        fmt = json_schema_format(schema, name=schema_name)
        return self.chat(messages, response_format=fmt, **kwargs)

    def chat_with_images(
        self,
        text: str,
        image_urls: List[str],
        *,
        system: str = "You are a helpful assistant with vision capabilities.",
        **kwargs,
    ) -> LMSResponse:
        """Chat with image input for vision-language models.

        Uses native v1 input format with ``{type: "image", data_url: "..."}`` items.
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": text},
                *[{"type": "image_url", "image_url": {"url": url}} for url in image_urls],
            ]},
        ]
        return self.chat(messages, **kwargs)

    # ── Model lifecycle (REST) ──────────────────────────────────────

    def load_model(
        self,
        model_id: str,
        *,
        config: Optional[LoadConfig] = None,
    ) -> bool:
        """Load a model via ``POST /api/v1/models/load``."""
        body: Dict[str, Any] = {"model": model_id}
        if config:
            body.update(config.to_rest_body())

        try:
            r = self._client.post(
                f"{self.base_url}/api/v1/models/load",
                json=body,
                timeout=300.0,
            )
            r.raise_for_status()
            self.invalidate_model_cache()
            logger.info("Model loaded via REST: %s", model_id)
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("REST load failed (%d): %s", exc.response.status_code, exc.response.text[:200])
            return False
        except Exception as exc:
            logger.error("REST load failed: %s", exc)
            return False

    # ── Token counting ──────────────────────────────────────────────

    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """Count tokens using SDK (fallback: chars/4)."""
        resolved = model or self._default_model or self.resolve_model()
        try:
            import lmstudio as lms
            handle = lms.llm(resolved) if resolved else lms.llm()
            return handle.count_tokens(text)
        except Exception:
            return max(1, len(text) // 4)

    def get_context_length(self, model: Optional[str] = None) -> int:
        """Get context length of loaded model."""
        resolved = model or self._default_model or self.resolve_model()
        try:
            import lmstudio as lms
            handle = lms.llm(resolved) if resolved else lms.llm()
            return handle.get_context_length()
        except Exception:
            return int(
                self._config.get("lmstudio.default_load_opts.context_length", 4096)
                if self._config else 4096
            )

    # ── Internal: native v1 ─────────────────────────────────────────

    @staticmethod
    def _messages_to_v1_input(messages: List[Dict]) -> tuple:
        """Convert OpenAI-style messages to v1 native ``input`` + ``system_prompt``.

        LMStudio native v1 ``/api/v1/chat`` uses:
        - ``system_prompt``: string (extracted from system messages)
        - ``input``: string | array of ``{type: "text", content: "..."}``

        Returns ``(system_prompt_or_None, input_value)``.
        """
        system_parts: List[str] = []
        input_items: List[Dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
                continue

            # For user/assistant messages → input items
            if isinstance(content, list):
                # Multi-part content (text + images for VLMs)
                for part in content:
                    if part.get("type") == "text":
                        input_items.append({"type": "text", "content": part["text"]})
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        input_items.append({"type": "image", "data_url": url})
            else:
                # Prefix assistant messages so the model understands the turn
                if role == "assistant":
                    input_items.append({
                        "type": "text",
                        "content": f"[assistant]: {content}",
                    })
                else:
                    input_items.append({"type": "text", "content": content})

        system_prompt = "\n\n".join(system_parts) if system_parts else None

        # Simplify: single text item → plain string
        if len(input_items) == 1 and input_items[0].get("type") == "text":
            return system_prompt, input_items[0]["content"]
        if not input_items:
            return system_prompt, ""

        return system_prompt, input_items

    def _chat_native(self, messages: List[Dict], config: InferenceConfig) -> LMSResponse:
        """Call ``POST /api/v1/chat`` (native protocol, the only path)."""
        resolved = self.resolve_model(config.model)
        system_prompt, v1_input = self._messages_to_v1_input(messages)

        payload: Dict[str, Any] = {
            "model": resolved,
            "input": v1_input,
            "stream": False,
        }
        if system_prompt:
            payload["system_prompt"] = system_prompt
        payload.update(config.to_native_v1())

        try:
            r = self._client.post(
                f"{self.base_url}/api/v1/chat",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except httpx.ConnectError:
            raise ConnectionError(f"Cannot connect to LMStudio at {self.base_url}")
        except httpx.HTTPStatusError as exc:
            logger.error("Native v1 HTTP %d: %s", exc.response.status_code, exc.response.text[:200])
            raise

        resp = self._parse_native_response(data, resolved)

        # Notify ConversationManager on model unload events
        if resp.finish_reason == "model_unloaded":
            self._on_model_unloaded(resolved)

        return resp

    def _stream_native(
        self,
        messages: List[Dict],
        config: InferenceConfig,
        model: str,
        on_event: Optional[Callable] = None,
    ) -> Generator[str, None, LMSResponse]:
        """Stream via ``POST /api/v1/chat`` with typed SSE events.

        LMStudio v1 streaming uses Server-Sent Events with the format::

            event: message.delta
            data: {"type": "message.delta", "content": "Hello"}

        Events arrive in order: chat.start → model_load.* →
        prompt_processing.* → reasoning.* → tool_call.* → message.* →
        chat.end.  The ``chat.end`` event contains the full aggregated
        response (stats, response_id, output array).
        """
        system_prompt, v1_input = self._messages_to_v1_input(messages)

        payload: Dict[str, Any] = {
            "model": model,
            "input": v1_input,
            "stream": True,
        }
        if system_prompt:
            payload["system_prompt"] = system_prompt
        payload.update(config.to_native_v1())

        return self._stream_v1_raw(payload, model, on_event)

    def _stream_v1_raw(
        self,
        payload: Dict[str, Any],
        model: str,
        on_event: Optional[Callable] = None,
    ) -> Generator[str, None, LMSResponse]:
        """Low-level v1 SSE stream consumer.

        Parses the ``event:`` / ``data:`` SSE pairs emitted by
        ``POST /api/v1/chat`` with ``stream: true``.

        Yields message content deltas.  Accumulates reasoning content,
        tool call results, and stats internally.  The generator's return
        value is the fully-populated LMSResponse.
        """
        result = LMSResponse(model=model)
        t0 = time.perf_counter()
        current_event_type: Optional[str] = None

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/api/v1/chat",
                json=payload,
                timeout=None,
            ) as response:
                response.raise_for_status()

                for line in response.iter_lines():
                    if not line:
                        # Blank line = end of event block, reset
                        current_event_type = None
                        continue

                    # SSE "event:" line — sets the type for the next data line
                    if line.startswith("event: "):
                        current_event_type = line[7:].strip()
                        continue

                    # SSE "data:" line — contains the JSON payload
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event = self._parse_v1_stream_event(data, current_event_type)
                    if on_event:
                        try:
                            on_event(event)
                        except Exception:
                            pass

                    # Yield message content deltas to the caller
                    if event.event_type == "message.delta" and event.content:
                        result.content += event.content
                        yield event.content

                    # Accumulate reasoning content
                    elif event.event_type == "reasoning.delta" and event.content:
                        result.reasoning_content += event.content

                    # Track completed tool calls
                    elif event.event_type == "tool_call.success":
                        result.tool_calls.append({
                            "tool": event.tool_name,
                            "arguments": event.tool_arguments,
                            "output": event.tool_output,
                            "provider_info": event.tool_provider,
                        })

                    # Log tool call failures
                    elif event.event_type == "tool_call.failure":
                        logger.warning("Stream tool_call.failure: %s", event.error)

                    # Log errors (stream continues — chat.end still arrives)
                    elif event.event_type == "error":
                        logger.warning("Stream error: %s", event.error)

                    # Extract final stats + response_id from chat.end
                    elif event.event_type == "chat.end" and event.result:
                        result.response_id = event.result.get("response_id", "")
                        result.model = event.result.get("model_instance_id", model)
                        result.finish_reason = "stop"
                        stats = event.result.get("stats", {})
                        result._apply_v1_stats(stats)
                        break

        except httpx.ConnectError:
            raise ConnectionError(f"Cannot connect to LMStudio at {self.base_url}")
        except httpx.HTTPStatusError as exc:
            logger.error("Stream HTTP %d: %s", exc.response.status_code, exc.response.text[:200])
            raise

        result.latency_ms = (time.perf_counter() - t0) * 1000
        if not result.total_tokens:
            result.total_tokens = result.input_tokens + result.output_tokens
        return result

    # ── Response parsing ────────────────────────────────────────────

    def _parse_native_response(self, data: Dict, model: str) -> LMSResponse:
        """Parse a native ``/api/v1/chat`` response.

        LMStudio native v1 returns::

            {
              "model_instance_id": "...",
              "output": [
                {"type": "text", "text": "..."},
                {"type": "reasoning", "content": "..."},
                {"type": "tool_call", "tool": "...", "arguments": {...}, "output": "..."}
              ],
              "stats": {
                "input_tokens": 100,
                "total_output_tokens": 50,
                "reasoning_output_tokens": 0,
                "tokens_per_second": 42.5,
                "time_to_first_token_seconds": 0.3,
                "model_load_time_seconds": null
              },
              "response_id": "resp_..."
            }
        """
        # Try native v1 format first (output array)
        output_items = data.get("output")
        if output_items is not None:
            return self._parse_v1_output(data, model)

        # Legacy fallback: choices-based shape (OpenAI compat)
        choices = data.get("choices", [])
        if choices:
            return self._parse_choices_response(data, model)

        # Flat shape fallback: {content, response_id, stats, ...}
        content = data.get("content", "")
        reasoning = data.get("reasoning_content", "")
        response_id = data.get("response_id", data.get("id", ""))
        stats = data.get("stats", data.get("usage", {}))
        tool_calls = data.get("tool_calls", [])

        return LMSResponse(
            content=content or reasoning,
            reasoning_content=reasoning,
            model=data.get("model", data.get("model_instance_id", model)),
            finish_reason=data.get("finish_reason", "stop"),
            input_tokens=stats.get("input_tokens", stats.get("prompt_tokens", 0)),
            output_tokens=stats.get("total_output_tokens", stats.get("completion_tokens", 0)),
            total_tokens=stats.get("input_tokens", 0) + stats.get("total_output_tokens", 0),
            response_id=response_id,
            tool_calls=tool_calls,
        )

    def _parse_v1_output(self, data: Dict, model: str) -> LMSResponse:
        """Parse the native v1 ``output`` array response format."""
        output_items = data.get("output", [])
        stats = data.get("stats", {})
        response_id = data.get("response_id", "")

        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        tool_calls: List[Dict] = []

        for item in output_items:
            item_type = item.get("type", "")
            if item_type == "message":
                content_parts.append(item.get("content", ""))
            elif item_type == "reasoning":
                reasoning_parts.append(item.get("content", ""))
            elif item_type == "tool_call":
                tool_calls.append({
                    "tool": item.get("tool", ""),
                    "arguments": item.get("arguments", {}),
                    "output": item.get("output", ""),
                    "provider_info": item.get("provider_info"),
                })
            elif item_type == "invalid_tool_call":
                logger.warning("Invalid tool call: %s — %s",
                               item.get("metadata", {}).get("tool_name", "?"),
                               item.get("reason", "unknown"))

        resp = LMSResponse(
            content="\n".join(content_parts),
            reasoning_content="\n".join(reasoning_parts),
            model=data.get("model_instance_id", model),
            finish_reason="stop",
            response_id=response_id,
            tool_calls=tool_calls,
        )
        resp._apply_v1_stats(stats)
        return resp

    def _parse_choices_response(self, data: Dict, model: str) -> LMSResponse:
        """Parse a choices-based response (legacy/compat fallback)."""
        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})
        msg = choice.get("message", {})

        raw_content = msg.get("content") or ""
        raw_reasoning = msg.get("reasoning_content") or ""
        tool_calls = msg.get("tool_calls", [])

        return LMSResponse(
            content=raw_content,
            reasoning_content=raw_reasoning,
            model=data.get("model", model),
            finish_reason=choice.get("finish_reason", ""),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            response_id=data.get("id", ""),
            tool_calls=tool_calls,
        )

    def _parse_v1_stream_event(
        self, data: Dict, event_hint: Optional[str] = None,
    ) -> LMSStreamEvent:
        """Parse a single typed SSE event from native v1 streaming.

        The event type comes from either the ``type`` field in the JSON data
        or the ``event:`` SSE line (passed as *event_hint*).
        """
        event = LMSStreamEvent()
        event.event_type = data.get("type", event_hint or "")

        et = event.event_type

        # ── Content deltas ──────────────────────────────────────
        if et in ("message.delta", "reasoning.delta"):
            event.content = data.get("content", "")

        # ── Progress events ─────────────────────────────────────
        elif et in ("model_load.progress", "prompt_processing.progress"):
            event.progress = data.get("progress", 0.0)

        # ── Model events ────────────────────────────────────────
        elif et in ("chat.start", "model_load.start", "model_load.end"):
            event.model_instance_id = data.get("model_instance_id", "")
            if et == "model_load.end":
                event.load_time_seconds = data.get("load_time_seconds", 0.0)

        # ── Tool call events ────────────────────────────────────
        elif et.startswith("tool_call."):
            event.tool_name = data.get("tool", "")
            event.tool_arguments = data.get("arguments")
            event.tool_output = data.get("output", "")
            event.tool_provider = data.get("provider_info")
            if et == "tool_call.failure":
                event.error = {
                    "reason": data.get("reason", ""),
                    "metadata": data.get("metadata", {}),
                }

        # ── Error event ─────────────────────────────────────────
        elif et == "error":
            event.error = data.get("error", data)

        # ── Final aggregated result ─────────────────────────────
        elif et == "chat.end":
            event.result = data.get("result", {})
            event.stats = event.result.get("stats")
            event.response_id = event.result.get("response_id", "")
            event.model_instance_id = event.result.get("model_instance_id", "")
            event.is_done = True

        # Terminal states
        if et in ("chat.end", "error"):
            event.is_done = True

        return event

    # ── Config building ─────────────────────────────────────────────

    def _build_config(
        self,
        config: Optional[InferenceConfig] = None,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        integrations: Optional[List[Dict]] = None,
        response_format: Optional[Dict] = None,
        model: Optional[str] = None,
    ) -> InferenceConfig:
        """Merge defaults + explicit config + convenience overrides."""
        base = self._inference_defaults
        if config:
            base = InferenceConfig.merge(base, config)

        # Apply convenience overrides
        if temperature is not None:
            base.temperature = temperature
        if max_tokens is not None:
            base.max_output_tokens = max_tokens
        if integrations is not None:
            base.integrations = integrations
        if response_format is not None:
            base.response_format = response_format
        if model is not None:
            base.model = model

        return base

    # ── Event publishing ────────────────────────────────────────────

    def _publish_inference_event(self, resp: LMSResponse) -> None:
        """Publish inference stats to ActivityBus."""
        try:
            from engine.services.activity_bus import get_activity_bus
            get_activity_bus().publish(
                activity_type="llm_inference",
                description=f"LMS chat: {resp.output_tokens}tok {resp.latency_ms:.0f}ms",
                agent_id="lms_client",
                scene="system",
                data={
                    "model": resp.model,
                    "input_tokens": resp.input_tokens,
                    "output_tokens": resp.output_tokens,
                    "reasoning_tokens": resp.reasoning_tokens,
                    "latency_ms": resp.latency_ms,
                    "request_id": resp.request_id,
                    "response_id": resp.response_id,
                    "tps": round(resp.tokens_per_second, 1),
                    "ttft_s": round(resp.time_to_first_token_s, 3),
                    "stateful": resp.is_stateful,
                },
            )
        except Exception:
            pass

        try:
            from engine.logging.benchmark import record_llm_kpi
            record_llm_kpi(
                "lms_chat",
                latency_ms=resp.latency_ms,
                tokens_in=resp.input_tokens,
                tokens_out=resp.output_tokens,
                model=resp.model,
            )
        except Exception:
            pass

    # ── Conversation state management ──────────────────────────────────

    def _on_model_unloaded(self, model_id: str) -> None:
        """Called when server indicates model was unloaded — invalidate conversations."""
        try:
            from engine.lmstudio.conversation import get_conversation_manager
            get_conversation_manager().invalidate_model(model_id)
        except Exception:
            pass
        self.invalidate_model_cache()

    def unload_model(self, model_id: str) -> bool:
        """Unload a model via ``POST /api/v1/models/unload``."""
        try:
            r = self._client.post(
                f"{self.base_url}/api/v1/models/unload",
                json={"model": model_id},
                timeout=30.0,
            )
            r.raise_for_status()
            self.invalidate_model_cache()
            # Invalidate all conversations using this model
            self._on_model_unloaded(model_id)
            logger.info("Model unloaded via REST: %s", model_id)
            return True
        except Exception as exc:
            logger.error("REST unload failed: %s", exc)
            return False

    def __repr__(self) -> str:
        return f"<LMSClient url={self.base_url} api=native_v1 mcp={self._mcp_enabled}>"

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass


# ── Module-level singleton ──────────────────────────────────────────────

_lms_instance: Optional[LMSClient] = None


def get_lms_client(**kwargs) -> LMSClient:
    """Return the global LMSClient singleton."""
    global _lms_instance
    if _lms_instance is None:
        _lms_instance = LMSClient(**kwargs)
    return _lms_instance
