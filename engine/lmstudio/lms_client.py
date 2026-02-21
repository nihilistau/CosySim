"""
LMSClient — Native LMStudio v1 REST API client

Primary inference client for CosySim.  Uses the **native** ``/api/v1/*``
endpoints (not the OpenAI-compatible ``/v1/chat/completions``).  Benefits:

* **Stateful chats** — server stores context; send ``previous_response_id``
  instead of full history.  Dramatically reduces token usage.
* **Ephemeral MCP** — per-request ``integrations`` for MCP tools
* **Full param control** — top_k, min_p, repeat_penalty, reasoning mode
* **Typed streaming events** — model_load, prompt_processing, tool_call, etc.
* **Structured output** — JSON schema enforcement
* **Image input** — VLM support via content parts
* **Speculative decoding** — draft model for 2-3x throughput

Falls back to OpenAI-compat ``/v1/chat/completions`` (via client_v2) when
the native API is unavailable or when custom ``tools`` field is needed.

Usage::

    from engine.lmstudio.lms_client import get_lms_client

    client = get_lms_client()
    resp = client.chat(messages)
    resp = client.chat(messages, config=InferenceConfig(temperature=0.3))
    resp = client.chat_stateful("Hello!", previous_response_id=prev_id)

    # Load/unload via REST
    client.load_model("model-id", config=LoadConfig(context_length=8192))
    client.unload_model("model-id")
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
    response_id: str = ""          # for stateful chats
    reasoning_content: str = ""    # thinking model CoT
    tool_calls: List[Dict] = field(default_factory=list)

    @property
    def tokens_per_second(self) -> float:
        if self.latency_ms > 0 and self.output_tokens > 0:
            return self.output_tokens / (self.latency_ms / 1000.0)
        return 0.0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class LMSStreamEvent:
    """A single event from the native v1 SSE stream."""
    event_type: str = ""   # model_load, prompt_processing, content, tool_call, done, error
    content: str = ""
    tool_call: Optional[Dict] = None
    stats: Optional[Dict] = None
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
    Native LMStudio v1 REST API client.

    Endpoints used:
    - ``/api/v1/chat``          — Inference (native protocol)
    - ``/api/v1/models``        — List loaded models
    - ``/api/v1/models/load``   — Load a model
    - ``/api/v1/models/unload`` — Unload a model
    - ``/v1/chat/completions``  — Fallback (OpenAI compat)
    - ``/v1/models``            — Model listing (OpenAI compat)
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

        # Track whether native v1 API is available
        self._native_available: Optional[bool] = None

    def close(self) -> None:
        self._client.close()

    # ── Health & Model Info ─────────────────────────────────────────

    def is_available(self) -> bool:
        """Check if LMStudio is responding."""
        try:
            r = self._client.get(f"{self.base_url}/v1/models", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def is_native_available(self) -> bool:
        """Check if native /api/v1 endpoints are available."""
        if self._native_available is not None:
            return self._native_available
        try:
            r = self._client.get(f"{self.base_url}/api/v1/models", timeout=3.0)
            self._native_available = (r.status_code == 200)
        except Exception:
            self._native_available = False
        return self._native_available

    def get_models(self) -> List[Dict[str, Any]]:
        """List loaded models."""
        try:
            r = self._client.get(f"{self.base_url}/v1/models", timeout=5.0)
            r.raise_for_status()
            return r.json().get("data", [])
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
        self._native_available = None

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
        tools: Optional[List[Dict]] = None,
    ) -> LMSResponse:
        """
        Send a chat completion request.

        Uses native ``/api/v1/chat`` when available and no custom ``tools`` field
        is needed.  Falls back to ``/v1/chat/completions`` otherwise.
        """
        # Build effective config
        effective = self._build_config(config, temperature=temperature,
                                        max_tokens=max_tokens,
                                        integrations=integrations,
                                        response_format=response_format,
                                        model=model)

        request_id = str(uuid.uuid4())[:8]
        t0 = time.perf_counter()

        # Route: custom tools → OpenAI compat (native v1 doesn't support tools field)
        if tools:
            resp = self._chat_openai_compat(messages, effective, tools=tools)
        elif self.is_native_available():
            resp = self._chat_native(messages, effective)
        else:
            resp = self._chat_openai_compat(messages, effective)

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
        """
        messages = []
        if system and not previous_response_id:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_message})

        effective = self._build_config(config, model=model)
        if previous_response_id:
            effective.previous_response_id = previous_response_id

        if self.is_native_available():
            return self._chat_native(messages, effective)
        return self._chat_openai_compat(messages, effective)

    # ── Chat (streaming) ────────────────────────────────────────────

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        config: Optional[InferenceConfig] = None,
        model: Optional[str] = None,
        on_event: Optional[Callable[[LMSStreamEvent], None]] = None,
    ) -> Generator[str, None, LMSResponse]:
        """
        Stream a chat response.  Yields content strings.

        Optional ``on_event`` callback receives typed events (model_load,
        prompt_processing, tool_call, etc.) for UI integration.

        The generator's return value is an LMSResponse with full stats.
        """
        effective = self._build_config(config, model=model)
        resolved_model = self.resolve_model(effective.model)

        if self.is_native_available():
            return self._stream_native(messages, effective, resolved_model, on_event)
        return self._stream_openai_compat(messages, effective, resolved_model)

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
        """Chat with image input for vision-language models."""
        content_parts: List[Dict] = [{"type": "text", "text": text}]
        for url in image_urls:
            content_parts.append({"type": "image_url", "image_url": {"url": url}})

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": content_parts},
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
            logger.info("Model unloaded via REST: %s", model_id)
            return True
        except Exception as exc:
            logger.error("REST unload failed: %s", exc)
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

    def _chat_native(self, messages: List[Dict], config: InferenceConfig) -> LMSResponse:
        """Call ``POST /api/v1/chat`` (native protocol)."""
        resolved = self.resolve_model(config.model)
        payload: Dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "stream": False,
        }
        payload.update(config.to_native_v1())

        try:
            r = self._client.post(
                f"{self.base_url}/api/v1/chat",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as exc:
            # If native fails, fallback to OpenAI compat
            logger.warning("Native v1 returned %d, falling back to OpenAI compat", exc.response.status_code)
            return self._chat_openai_compat(messages, config)
        except httpx.ConnectError:
            raise ConnectionError(f"Cannot connect to LMStudio at {self.base_url}")

        return self._parse_native_response(data, resolved)

    def _chat_openai_compat(
        self,
        messages: List[Dict],
        config: InferenceConfig,
        *,
        tools: Optional[List[Dict]] = None,
    ) -> LMSResponse:
        """Fallback: call ``/v1/chat/completions`` (OpenAI compat)."""
        resolved = self.resolve_model(config.model)
        payload: Dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "stream": False,
        }
        payload.update(config.to_openai_compat())
        if tools:
            payload["tools"] = tools

        try:
            r = self._client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as exc:
            logger.error("OpenAI compat HTTP %d: %s", exc.response.status_code, exc.response.text[:200])
            raise
        except httpx.ConnectError:
            raise ConnectionError(f"Cannot connect to LMStudio at {self.base_url}")

        return self._parse_openai_response(data, resolved)

    def _stream_native(
        self,
        messages: List[Dict],
        config: InferenceConfig,
        model: str,
        on_event: Optional[Callable] = None,
    ) -> Generator[str, None, LMSResponse]:
        """Stream via ``POST /api/v1/chat`` with typed events."""
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        payload.update(config.to_native_v1())

        result = LMSResponse(model=model)
        t0 = time.perf_counter()

        with self._client.stream(
            "POST",
            f"{self.base_url}/api/v1/chat",
            json=payload,
            timeout=None,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event = self._parse_stream_event(data)
                if on_event:
                    on_event(event)

                if event.content:
                    result.content += event.content
                    result.output_tokens += 1
                    yield event.content

                if event.is_done:
                    break

        result.latency_ms = (time.perf_counter() - t0) * 1000
        return result

    def _stream_openai_compat(
        self,
        messages: List[Dict],
        config: InferenceConfig,
        model: str,
    ) -> Generator[str, None, LMSResponse]:
        """Fallback streaming via ``/v1/chat/completions``."""
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        payload.update(config.to_openai_compat())

        result = LMSResponse(model=model)
        t0 = time.perf_counter()

        with self._client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=None,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choice = data.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                content = delta.get("content", "")

                if content:
                    result.content += content
                    result.output_tokens += 1
                    yield content

                if choice.get("finish_reason"):
                    result.finish_reason = choice["finish_reason"]
                    break

        result.latency_ms = (time.perf_counter() - t0) * 1000
        return result

    # ── Response parsing ────────────────────────────────────────────

    def _parse_native_response(self, data: Dict, model: str) -> LMSResponse:
        """Parse a native ``/api/v1/chat`` response."""
        # Native v1 may use different response shapes depending on version
        # Attempt standard shape first, then OpenAI compat shape
        choices = data.get("choices", [])
        if choices:
            return self._parse_openai_response(data, model)

        # Native shape: {content, response_id, stats, ...}
        content = data.get("content", "")
        reasoning = data.get("reasoning_content", "")
        response_id = data.get("response_id", data.get("id", ""))
        stats = data.get("stats", data.get("usage", {}))

        tool_calls = data.get("tool_calls", [])

        return LMSResponse(
            content=content or reasoning,
            reasoning_content=reasoning,
            model=data.get("model", model),
            finish_reason=data.get("finish_reason", "stop"),
            input_tokens=stats.get("prompt_tokens", stats.get("input_tokens", 0)),
            output_tokens=stats.get("completion_tokens", stats.get("output_tokens", 0)),
            total_tokens=stats.get("total_tokens", 0),
            response_id=response_id,
            tool_calls=tool_calls,
        )

    def _parse_openai_response(self, data: Dict, model: str) -> LMSResponse:
        """Parse an OpenAI-compat ``/v1/chat/completions`` response."""
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

    def _parse_stream_event(self, data: Dict) -> LMSStreamEvent:
        """Parse a single SSE event from native v1 streaming."""
        event = LMSStreamEvent()

        # Detect event type from various possible shapes
        if "type" in data:
            event.event_type = data["type"]
        elif "choices" in data:
            event.event_type = "content"

        # Extract content
        choices = data.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            event.content = delta.get("content", "")
            if choices[0].get("finish_reason"):
                event.is_done = True

        if data.get("content"):
            event.content = data["content"]

        # Tool calls in stream
        if data.get("tool_calls"):
            event.event_type = "tool_call"
            event.tool_call = data["tool_calls"]

        if data.get("done") or data.get("type") == "done":
            event.is_done = True
            event.stats = data.get("stats")

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
                    "latency_ms": resp.latency_ms,
                    "request_id": resp.request_id,
                    "response_id": resp.response_id,
                    "tps": round(resp.tokens_per_second, 1),
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

    def __repr__(self) -> str:
        native = "native" if self._native_available else "compat"
        return f"<LMSClient url={self.base_url} api={native} mcp={self._mcp_enabled}>"

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
