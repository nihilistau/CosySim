"""
LMSClient v0.50a — API-Complete LMStudio v1 REST API client

**CosySim Framework v0.50a** — all inference through ``/api/v1/chat``.

Implements every endpoint in the LMStudio v1 REST API:

* ``POST /api/v1/chat``                     — Inference (stateful + stateless)
* ``GET  /api/v1/models``                   — List models (rich metadata)
* ``POST /api/v1/models/load``              — Load model (with config echo)
* ``POST /api/v1/models/unload``            — Unload model
* ``POST /api/v1/models/download``          — Download model from catalog
* ``GET  /api/v1/models/download/status``   — Download progress tracking

Features:

* **Authentication** — Optional Bearer token for secured LMStudio servers.
* **Stateful chats** — ``previous_response_id`` / ``response_id`` for
  server-managed context; conversation branching by reusing any historical
  response_id.
* **Store / no-store** — ``store: false`` for stateless one-off requests;
  ``store: true`` (default) returns a ``response_id`` for continuations.
* **Typed SSE streaming** — proper event parsing for all 19 event types:
  chat.start, model_load.*, prompt_processing.*, reasoning.*,
  tool_call.*, message.*, error, chat.end.
* **Ephemeral MCP** — per-request ``integrations`` for tool calling
  with ``allowed_tools`` and ``headers`` support.
* **Full param control** — top_k, min_p, repeat_penalty, reasoning mode,
  context_length override per request.
* **Structured output** — JSON schema enforcement at logit level.
* **Image input** — VLM support via ``{type: "image", data_url: "..."}``.
* **Speculative decoding** — ``enable_speculative()`` loads main + draft
  model pair; ``draft_model`` passed through to chat payload.
* **Rich model objects** — ``LMSModel`` with full metadata (capabilities,
  quantization, format, publisher, description).
* **Model download** — Download models by catalog ID or Hugging Face URL.

Usage::

    from engine.lmstudio.lms_client import get_lms_client

    client = get_lms_client()
    resp = client.chat(messages)
    resp = client.chat_stateful("Hello!", previous_response_id=prev_id)

    # Streaming with typed events
    for chunk in client.chat_stream(messages, on_event=my_handler):
        print(chunk, end="")

    # Rich model listing
    models = client.get_models()  # List[LMSModel]
    for m in models:
        print(m.display_name, m.capabilities, m.quantization)

    # Download + load
    job = client.download_model("ibm/granite-4-micro")
    result = client.load_model("ibm/granite-4-micro", echo_load_config=True)

    # Speculative decoding
    client.enable_speculative("qwen2.5-7b-instruct", "qwen2.5-0.5b-instruct")
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
    # Extra metadata (spec decode stats, etc.)
    metadata: Dict = field(default_factory=dict)

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
    max_context_length: int = 0
    supports_vision: bool = False
    supports_tool_use: bool = False
    quantization: str = ""


@dataclass
class LMSModelInstance:
    """A loaded instance of a model (from ``loaded_instances[]``)."""
    id: str = ""
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def context_length(self) -> int:
        return self.config.get("context_length", 0)

    @property
    def eval_batch_size(self) -> Optional[int]:
        return self.config.get("eval_batch_size")

    @property
    def flash_attention(self) -> Optional[bool]:
        return self.config.get("flash_attention")

    @property
    def num_experts(self) -> Optional[int]:
        return self.config.get("num_experts")

    @property
    def offload_kv_cache_to_gpu(self) -> Optional[bool]:
        return self.config.get("offload_kv_cache_to_gpu")


@dataclass
class LMSQuantization:
    """Quantization info for a model."""
    name: Optional[str] = None
    bits_per_weight: Optional[float] = None


@dataclass
class LMSCapabilities:
    """Model capabilities."""
    vision: bool = False
    trained_for_tool_use: bool = False


@dataclass
class LMSModel:
    """Full model metadata from ``GET /api/v1/models``.

    Maps every field from the LMStudio v1 response schema.
    """
    type: str = "llm"
    publisher: str = ""
    key: str = ""
    display_name: str = ""
    architecture: Optional[str] = None
    quantization: Optional[LMSQuantization] = None
    size_bytes: int = 0
    params_string: Optional[str] = None
    loaded_instances: List[LMSModelInstance] = field(default_factory=list)
    max_context_length: int = 0
    format: Optional[str] = None
    capabilities: Optional[LMSCapabilities] = None
    description: Optional[str] = None

    @property
    def is_loaded(self) -> bool:
        return len(self.loaded_instances) > 0

    @property
    def instance_id(self) -> str:
        """The ID to use for ``/api/v1/chat`` model field."""
        if self.loaded_instances:
            return self.loaded_instances[0].id
        return self.key

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "LMSModel":
        """Parse from a single model entry in ``GET /api/v1/models`` response."""
        quant_data = data.get("quantization")
        quant = None
        if quant_data and isinstance(quant_data, dict):
            quant = LMSQuantization(
                name=quant_data.get("name"),
                bits_per_weight=quant_data.get("bits_per_weight"),
            )
        cap_data = data.get("capabilities")
        caps = None
        if cap_data and isinstance(cap_data, dict):
            caps = LMSCapabilities(
                vision=cap_data.get("vision", False),
                trained_for_tool_use=cap_data.get("trained_for_tool_use", False),
            )
        instances = [
            LMSModelInstance(id=inst.get("id", ""), config=inst.get("config", {}))
            for inst in data.get("loaded_instances", [])
        ]
        return cls(
            type=data.get("type", "llm"),
            publisher=data.get("publisher", ""),
            key=data.get("key", ""),
            display_name=data.get("display_name", data.get("key", "")),
            architecture=data.get("architecture"),
            quantization=quant,
            size_bytes=data.get("size_bytes", 0),
            params_string=data.get("params_string"),
            loaded_instances=instances,
            max_context_length=data.get("max_context_length", 0),
            format=data.get("format"),
            capabilities=caps,
            description=data.get("description"),
        )


@dataclass
class LMSLoadResult:
    """Response from ``POST /api/v1/models/load``."""
    type: str = "llm"
    instance_id: str = ""
    load_time_seconds: float = 0.0
    status: str = ""
    load_config: Optional[Dict[str, Any]] = None


@dataclass
class LMSDownloadJob:
    """Response from ``POST /api/v1/models/download``."""
    job_id: Optional[str] = None
    status: str = ""
    total_size_bytes: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class LMSDownloadStatus:
    """Response from ``GET /api/v1/models/download/status/:job_id``."""
    job_id: str = ""
    status: str = ""
    bytes_per_second: Optional[float] = None
    estimated_completion: Optional[str] = None
    completed_at: Optional[str] = None
    total_size_bytes: Optional[int] = None
    downloaded_bytes: Optional[int] = None
    started_at: Optional[str] = None

    @property
    def progress(self) -> float:
        """Download progress as 0.0–1.0."""
        if self.total_size_bytes and self.downloaded_bytes:
            return self.downloaded_bytes / self.total_size_bytes
        return 0.0 if self.status == "downloading" else 1.0


# ── Main client ─────────────────────────────────────────────────────────

class LMSClient:
    """
    API-complete LMStudio v1 REST client.

    Endpoints:
    - ``POST /api/v1/chat``                    — All inference
    - ``GET  /api/v1/models``                  — List models (rich metadata)
    - ``POST /api/v1/models/load``             — Load model
    - ``POST /api/v1/models/unload``           — Unload model
    - ``POST /api/v1/models/download``         — Download model
    - ``GET  /api/v1/models/download/status``  — Download progress

    Authentication via ``api_token`` (Bearer header) is optional.
    Tools are accessed via ephemeral MCP ``integrations``.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = 120.0,
        config=None,
        api_token: Optional[str] = None,
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

        # Authentication
        self._api_token: Optional[str] = (
            api_token
            or (config.get("lmstudio.api_token", "") if config else "")
            or None
        )

        # Defaults from config
        self._default_model = (config.get("llm.model", "") if config else "")
        self._mcp_enabled = bool(config.get("lmstudio.mcp_enabled", True) if config else True)
        self._cosysim_mcp_url = (config.get("lmstudio.cosysim_mcp_url", "") if config else "")

        # Inference defaults from config
        self._inference_defaults = InferenceConfig.from_yaml() if config else InferenceConfig()

        # HTTP client with connection pooling and auth headers
        headers: Dict[str, str] = {}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        self._client = httpx.Client(timeout=timeout, headers=headers)

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

    def get_models(
        self,
        loaded_only: bool = True,
        *,
        raw: bool = False,
    ) -> List[Any]:
        """List models via native v1 API.

        Args:
            loaded_only: If True (default), return only currently loaded models.
            raw: If True, return legacy dict format for backward compatibility.

        Returns:
            List of ``LMSModel`` objects (or dicts if ``raw=True``).
        """
        try:
            r = self._client.get(f"{self.base_url}/api/v1/models", timeout=5.0)
            r.raise_for_status()
            data = r.json()

            raw_models = data.get("models", data.get("data", data if isinstance(data, list) else []))
            models: List[LMSModel] = []

            for m in raw_models:
                model = LMSModel.from_api(m)
                if loaded_only and not model.is_loaded:
                    continue
                models.append(model)

            if raw:
                # Backward-compat dict format
                results: List[Dict[str, Any]] = []
                for model in models:
                    entry: Dict[str, Any] = {
                        "key": model.key,
                        "display_name": model.display_name,
                        "type": model.type,
                        "architecture": model.architecture or "",
                        "params": model.params_string or "",
                        "loaded": model.is_loaded,
                        "id": model.instance_id,
                    }
                    if model.loaded_instances:
                        entry["config"] = model.loaded_instances[0].config
                        entry["context_length"] = model.loaded_instances[0].context_length
                    results.append(entry)
                return results

            return models
        except Exception as exc:
            logger.debug("get_models failed: %s", exc)
            return []

    def get_model_info(self, model_id: Optional[str] = None) -> LMSModelInfo:
        """Get detailed info about a model (REST-first, SDK fallback)."""
        resolved = model_id or self.resolve_model()
        info = LMSModelInfo(model_id=resolved)

        # Try REST API first — has all fields since v1
        try:
            models = self.get_models(loaded_only=False)
            for m in models:
                if isinstance(m, LMSModel) and (m.key == resolved or m.instance_id == resolved):
                    info.architecture = m.architecture or ""
                    info.parameters = m.params_string or ""
                    info.max_context_length = m.max_context_length
                    if m.loaded_instances:
                        info.context_length = m.loaded_instances[0].context_length
                    else:
                        info.context_length = m.max_context_length
                    if m.capabilities:
                        info.supports_vision = m.capabilities.vision
                        info.supports_tool_use = m.capabilities.trained_for_tool_use
                    if m.quantization and m.quantization.name:
                        info.quantization = m.quantization.name
                    return info
        except Exception as exc:
            logger.debug("REST get_model_info failed: %s", exc)

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

        models = self.get_models(raw=True)
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
        echo_load_config: bool = False,
    ) -> LMSLoadResult:
        """Load a model via ``POST /api/v1/models/load``.

        Returns an ``LMSLoadResult`` with instance ID, load time, and
        optionally the final load config applied by LMStudio.
        """
        body: Dict[str, Any] = {"model": model_id}
        if config:
            body.update(config.to_rest_body())
        if echo_load_config:
            body["echo_load_config"] = True

        try:
            r = self._client.post(
                f"{self.base_url}/api/v1/models/load",
                json=body,
                timeout=300.0,
            )
            r.raise_for_status()
            data = r.json()
            self.invalidate_model_cache()
            logger.info("Model loaded via REST: %s", model_id)

            return LMSLoadResult(
                type=data.get("type", "llm"),
                instance_id=data.get("instance_id", model_id),
                load_time_seconds=data.get("load_time_seconds", 0.0),
                status=data.get("status", "loaded"),
                load_config=data.get("load_config"),
            )
        except httpx.HTTPStatusError as exc:
            logger.error("REST load failed (%d): %s", exc.response.status_code, exc.response.text[:200])
            return LMSLoadResult(status="error", instance_id=model_id)
        except Exception as exc:
            logger.error("REST load failed: %s", exc)
            return LMSLoadResult(status="error", instance_id=model_id)

    # ── Model download (REST) ──────────────────────────────────────

    def download_model(
        self,
        model: str,
        *,
        quantization: Optional[str] = None,
    ) -> LMSDownloadJob:
        """Download a model via ``POST /api/v1/models/download``.

        Args:
            model: Model catalog ID (e.g. ``"ibm/granite-4-micro"``)
                   or Hugging Face URL.
            quantization: Quantization level (e.g. ``"Q4_K_M"``).
                          Only supported for Hugging Face links.

        Returns ``LMSDownloadJob`` with ``job_id`` for tracking progress.
        """
        body: Dict[str, Any] = {"model": model}
        if quantization:
            body["quantization"] = quantization

        try:
            r = self._client.post(
                f"{self.base_url}/api/v1/models/download",
                json=body,
                timeout=30.0,
            )
            r.raise_for_status()
            data = r.json()
            return LMSDownloadJob(
                job_id=data.get("job_id"),
                status=data.get("status", ""),
                total_size_bytes=data.get("total_size_bytes"),
                started_at=data.get("started_at"),
                completed_at=data.get("completed_at"),
            )
        except httpx.HTTPStatusError as exc:
            logger.error("Download failed (%d): %s", exc.response.status_code, exc.response.text[:200])
            return LMSDownloadJob(status="failed")
        except Exception as exc:
            logger.error("Download failed: %s", exc)
            return LMSDownloadJob(status="failed")

    def download_status(self, job_id: str) -> LMSDownloadStatus:
        """Check download progress via ``GET /api/v1/models/download/status/:job_id``."""
        try:
            r = self._client.get(
                f"{self.base_url}/api/v1/models/download/status/{job_id}",
                timeout=10.0,
            )
            r.raise_for_status()
            data = r.json()
            return LMSDownloadStatus(
                job_id=data.get("job_id", job_id),
                status=data.get("status", ""),
                bytes_per_second=data.get("bytes_per_second"),
                estimated_completion=data.get("estimated_completion"),
                completed_at=data.get("completed_at"),
                total_size_bytes=data.get("total_size_bytes"),
                downloaded_bytes=data.get("downloaded_bytes"),
                started_at=data.get("started_at"),
            )
        except httpx.HTTPStatusError as exc:
            logger.error("Download status failed (%d): %s", exc.response.status_code, exc.response.text[:200])
            return LMSDownloadStatus(job_id=job_id, status="error")
        except Exception as exc:
            logger.error("Download status failed: %s", exc)
            return LMSDownloadStatus(job_id=job_id, status="error")

    # ── Speculative decoding ───────────────────────────────────────

    def enable_speculative(
        self,
        main_model: str,
        draft_model: str,
        *,
        main_config: Optional[LoadConfig] = None,
        draft_config: Optional[LoadConfig] = None,
    ) -> tuple:
        """Load both main and draft models for speculative decoding.

        LMStudio activates speculative decoding automatically when a
        compatible draft model is loaded alongside the main model.

        Returns ``(main_result, draft_result)`` tuple of ``LMSLoadResult``.
        """
        main_result = self.load_model(main_model, config=main_config)
        draft_result = self.load_model(draft_model, config=draft_config)
        if main_result.status == "loaded" and draft_result.status == "loaded":
            logger.info("Speculative decoding enabled: main=%s draft=%s",
                        main_model, draft_model)
        else:
            logger.warning("Speculative decoding setup incomplete: main=%s draft=%s",
                           main_result.status, draft_result.status)
        return main_result, draft_result

    def disable_speculative(self, draft_model: str) -> bool:
        """Unload the draft model to disable speculative decoding."""
        return self.unload_model(draft_model)

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
                            logger.debug("Suppressed exception", exc_info=True)

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
            logger.debug("Suppressed exception", exc_info=True)

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
            logger.debug("Suppressed exception", exc_info=True)

    # ── Conversation state management ──────────────────────────────────

    def _on_model_unloaded(self, model_id: str) -> None:
        """Called when server indicates model was unloaded — invalidate conversations."""
        try:
            from engine.lmstudio.conversation import get_conversation_manager
            get_conversation_manager().invalidate_model(model_id)
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        self.invalidate_model_cache()

    def unload_model(self, model_id: str) -> bool:
        """Unload a model via ``POST /api/v1/models/unload``.

        Per API spec, sends ``{"instance_id": ...}``.
        """
        try:
            r = self._client.post(
                f"{self.base_url}/api/v1/models/unload",
                json={"instance_id": model_id},
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
        auth = "auth" if self._api_token else "no-auth"
        return f"<LMSClient url={self.base_url} api=native_v1 mcp={self._mcp_enabled} {auth}>"

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)


# ── MCP integration helpers ─────────────────────────────────────────────

class MCP:
    """Factory for MCP integration payloads (v1 API ``integrations`` field).

    Supports ``allowed_tools`` to restrict which tools a server exposes,
    and ``headers`` for authenticated ephemeral servers.
    """

    @staticmethod
    def plugin(
        plugin_id: str,
        *,
        allowed_tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Reference an MCP server registered in LMStudio's mcp.json.

        Args:
            plugin_id: e.g. ``"mcp/playwright"``
            allowed_tools: Restrict to these tool names only.
        """
        d: Dict[str, Any] = {"type": "plugin", "id": plugin_id}
        if allowed_tools:
            d["allowed_tools"] = allowed_tools
        return d

    @staticmethod
    def ephemeral(
        server_url: str,
        *,
        server_label: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Reference an MCP server by URL (not pre-registered).

        Args:
            server_url: The SSE endpoint URL.
            server_label: Human-readable label (defaults to URL).
            allowed_tools: Restrict to these tool names only.
            headers: Custom HTTP headers for the MCP server connection.
        """
        d: Dict[str, Any] = {
            "type": "ephemeral_mcp",
            "server_label": server_label or server_url,
            "server_url": server_url,
        }
        if allowed_tools:
            d["allowed_tools"] = allowed_tools
        if headers:
            d["headers"] = headers
        return d


# ── Module-level singleton ──────────────────────────────────────────────

_lms_instance: Optional[LMSClient] = None


def get_lms_client(**kwargs) -> LMSClient:
    """Return the global LMSClient singleton."""
    global _lms_instance
    if _lms_instance is None:
        _lms_instance = LMSClient(**kwargs)
    return _lms_instance
