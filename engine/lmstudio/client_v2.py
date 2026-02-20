"""
LMStudio REST Client v2 — Direct HTTP integration with ``integrations`` support

This client talks to LMStudio's REST API (``/v1/chat/completions``) instead of
the WebSocket-based Python SDK.  This is necessary for:

* **Per-request MCP** — the ``integrations`` field lets us attach MCP servers
  (plugins or ephemeral) to individual requests
* **SSE streaming** — server-sent events for real-time token delivery
* **Abort** — close the HTTP connection to stop generation and free VRAM
* **Token counting** — track input/output tokens per call

The original ``LMStudioManager`` (client.py) is kept for CLI model lifecycle
(load/unload/estimate VRAM).  This v2 client handles all inference calls.

Usage::

    from engine.lmstudio.client_v2 import LMStudioClient, MCP

    client = LMStudioClient()

    # Simple chat
    reply = client.chat([
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello!"},
    ])
    print(reply.content)

    # Chat with MCP tools
    reply = client.chat(messages, integrations=[
        MCP.plugin("mcp/cosysim"),
        MCP.ephemeral("http://localhost:8600/mcp/sse"),
    ])

    # Streaming
    for chunk in client.chat_stream(messages):
        print(chunk.delta, end="", flush=True)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Union

import httpx

# Model-resolution cache TTL (seconds) — avoids hitting /v1/models on every call
_MODEL_CACHE_TTL = 30.0

logger = logging.getLogger(__name__)

try:
    from engine.logging import timed
except ImportError:
    def timed(name):
        def decorator(fn): return fn
        return decorator


# ── Data classes ───────────────────────────────────────────────────────

@dataclass
class ChatResponse:
    """Result of a non-streaming chat call."""
    content: str
    model: str = ""
    finish_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    request_id: str = ""

    @property
    def tokens_per_second(self) -> float:
        if self.latency_ms > 0 and self.output_tokens > 0:
            return self.output_tokens / (self.latency_ms / 1000.0)
        return 0.0


@dataclass
class StreamChunk:
    """A single chunk from an SSE stream."""
    delta: str = ""
    finish_reason: Optional[str] = None
    model: str = ""
    is_done: bool = False


@dataclass
class StreamResult:
    """Accumulated result after a stream completes."""
    content: str = ""
    model: str = ""
    finish_reason: str = ""
    chunks: int = 0
    first_token_ms: float = 0.0
    total_ms: float = 0.0

    @property
    def tokens_per_second(self) -> float:
        if self.total_ms > 0 and self.chunks > 0:
            return self.chunks / (self.total_ms / 1000.0)
        return 0.0


# ── MCP integration helpers ───────────────────────────────────────────

class MCP:
    """Factory for MCP integration payloads."""

    @staticmethod
    def plugin(plugin_id: str) -> Dict[str, str]:
        """Reference an MCP server registered in LMStudio's mcp.json."""
        return {"type": "plugin", "id": plugin_id}

    @staticmethod
    def ephemeral(server_url: str) -> Dict[str, str]:
        """Reference an MCP server by URL (not pre-registered)."""
        return {"type": "ephemeral_mcp", "server_url": server_url}


# ── Main client ────────────────────────────────────────────────────────

class LMStudioClient:
    """
    REST client for LMStudio with MCP integration support.

    Talks to ``/v1/chat/completions`` with extended fields:
    * ``integrations`` — per-request MCP server attachments
    * ``stream`` — SSE streaming
    * Standard OpenAI-compatible fields (model, messages, temperature, etc.)

    Parameters
    ----------
    base_url : str
        LMStudio server base (default from config or ``http://127.0.0.1:1234``).
    timeout : float
        HTTP timeout in seconds for non-streaming calls (default 120).
    config : ConfigManager, optional
        Config instance.  Falls back to global ``get_config()``.
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
        self._default_model = (config.get("llm.model", "") if config else "")
        self._default_temp = float(config.get("llm.temperature", 0.7) if config else 0.7)
        self._default_max_tokens = int(config.get("llm.max_tokens", 500) if config else 500)
        self._mcp_enabled = bool(config.get("lmstudio.mcp_enabled", True) if config else True)

        # Persistent httpx client for connection pooling
        self._client = httpx.Client(timeout=timeout)

        # Resolved model cache {model_id, timestamp}
        self._resolved_model: Optional[str] = None
        self._resolved_at: float = 0.0

    def close(self):
        """Close the underlying HTTP client."""
        self._client.close()

    # ── Health & Info ──────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Check if LMStudio is responding."""
        try:
            r = self._client.get(f"{self.base_url}/v1/models", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def get_models(self) -> List[Dict[str, Any]]:
        """List loaded models from the /v1/models endpoint."""
        try:
            r = self._client.get(f"{self.base_url}/v1/models", timeout=5.0)
            r.raise_for_status()
            data = r.json()
            return data.get("data", [])
        except Exception as exc:
            logger.debug("get_models failed: %s", exc)
            return []

    def get_loaded_model_id(self) -> Optional[str]:
        """Return the ID of the first loaded model, or None."""
        models = self.get_models()
        if models:
            return models[0].get("id")
        return None

    def resolve_model(self, hint: Optional[str] = None) -> str:
        """
        Return the best model ID to use for a request.

        Priority order:
          1. ``hint`` if provided and present in the loaded models list
          2. ``hint`` as-is if provided (model may be loaded by LMStudio on demand)
          3. ``self._default_model`` from config if it matches a loaded model
          4. First loaded model from ``/v1/models``
          5. ``self._default_model`` from config as last resort
          6. Empty string (LMStudio picks whatever is loaded)

        Results are cached for ``_MODEL_CACHE_TTL`` seconds so the model
        list is not polled on every single call.
        """
        now = time.monotonic()
        # Return hint immediately if explicitly provided — caller knows what they want
        if hint:
            return hint

        # Use cached resolution if still fresh
        if self._resolved_model and (now - self._resolved_at) < _MODEL_CACHE_TTL:
            return self._resolved_model

        # Fetch currently loaded models
        try:
            models = self.get_models()
        except Exception:
            models = []

        model_ids = [m.get("id", "") for m in models if m.get("id")]

        # Prefer the configured default if it's actually loaded
        if self._default_model and self._default_model in model_ids:
            resolved = self._default_model
        elif model_ids:
            resolved = model_ids[0]
            if self._default_model:
                logger.info(
                    "Configured model %r not loaded; using %r instead",
                    self._default_model, resolved,
                )
        else:
            # Nothing loaded yet — use config default and let LMStudio decide
            resolved = self._default_model or ""
            if resolved:
                logger.debug("No model loaded; will send model=%r and hope LMStudio loads it", resolved)

        self._resolved_model = resolved
        self._resolved_at = now
        return resolved

    def invalidate_model_cache(self) -> None:
        """Force the next call to resolve_model() to re-query /v1/models."""
        self._resolved_at = 0.0
        self._resolved_model = None

    # ── Chat (non-streaming) ──────────────────────────────────────────

    @timed("lmstudio_chat")
    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        integrations: Optional[List[Dict]] = None,
        response_format: Optional[Dict] = None,
        tools: Optional[List[Dict]] = None,
    ) -> ChatResponse:
        """
        Send a chat completion request and return the full response.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            model: Model ID (defaults to config or ``"default"``).
            temperature: Sampling temperature.
            max_tokens: Max output tokens.
            integrations: MCP integrations (use ``MCP.plugin()`` / ``MCP.ephemeral()``).
            response_format: Structured output format spec.
            tools: OpenAI-format tool definitions.

        Returns:
            ChatResponse with content, token counts, and timing.
        """
        request_id = str(uuid.uuid4())[:8]
        payload = self._build_payload(
            messages, model=model, temperature=temperature,
            max_tokens=max_tokens, integrations=integrations,
            response_format=response_format, tools=tools,
            stream=False,
        )

        t0 = time.perf_counter()
        try:
            r = self._client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as exc:
            logger.error("LMStudio HTTP %d: %s", exc.response.status_code, exc.response.text[:200])
            raise
        except httpx.ConnectError:
            raise ConnectionError(f"Cannot connect to LMStudio at {self.base_url}")
        finally:
            latency = (time.perf_counter() - t0) * 1000

        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})

        resp = ChatResponse(
            content=choice.get("message", {}).get("content", ""),
            model=data.get("model", ""),
            finish_reason=choice.get("finish_reason", ""),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            latency_ms=latency,
            request_id=request_id,
        )

        # Auto-record KPI for every chat call
        try:
            from engine.logging.benchmark import record_llm_kpi
            record_llm_kpi(
                "lmstudio_chat",
                latency_ms=resp.latency_ms,
                tokens_in=resp.input_tokens,
                tokens_out=resp.output_tokens,
                model=resp.model,
            )
        except Exception:
            pass  # Never let KPI recording break inference

        return resp

    # ── Chat (streaming) ──────────────────────────────────────────────

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        integrations: Optional[List[Dict]] = None,
    ) -> Generator[StreamChunk, None, StreamResult]:
        """
        Stream a chat completion via SSE.

        Yields ``StreamChunk`` objects with delta text.  The generator's
        return value is a ``StreamResult`` with accumulated stats.

        Usage::

            gen = client.chat_stream(messages)
            try:
                for chunk in gen:
                    print(chunk.delta, end="")
            except StopIteration as e:
                result = e.value  # StreamResult
        """
        payload = self._build_payload(
            messages, model=model, temperature=temperature,
            max_tokens=max_tokens, integrations=integrations,
            stream=True,
        )

        result = StreamResult()
        t0 = time.perf_counter()
        first_token_time = None

        with self._client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=None,  # No timeout for streaming
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
                finish = choice.get("finish_reason")

                if content and first_token_time is None:
                    first_token_time = (time.perf_counter() - t0) * 1000

                result.content += content
                result.chunks += 1
                result.model = data.get("model", result.model)

                if finish:
                    result.finish_reason = finish

                chunk = StreamChunk(
                    delta=content,
                    finish_reason=finish,
                    model=data.get("model", ""),
                    is_done=(finish is not None),
                )
                yield chunk

        result.first_token_ms = first_token_time or 0.0
        result.total_ms = (time.perf_counter() - t0) * 1000
        return result

    # ── Convenience wrappers ──────────────────────────────────────────

    def quick_reply(
        self,
        user_message: str,
        *,
        system: str = "You are a helpful assistant.",
        **kwargs,
    ) -> str:
        """One-shot: system + user message → reply string."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        resp = self.chat(messages, **kwargs)
        return resp.content

    def chat_with_mcp(
        self,
        messages: List[Dict[str, str]],
        mcp_servers: List[Dict],
        **kwargs,
    ) -> ChatResponse:
        """Chat with MCP integrations explicitly listed."""
        if not self._mcp_enabled:
            logger.warning("MCP is disabled in config — ignoring integrations")
            mcp_servers = None
        return self.chat(messages, integrations=mcp_servers, **kwargs)

    # ── Token counting via SDK ────────────────────────────────────────

    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """
        Count tokens using the LMStudio SDK.

        Falls back to a rough estimate (chars / 4) if SDK unavailable or no
        model is loaded.  Uses the first loaded model when ``model`` is None
        to avoid the SDK "default model not being a thing" error.
        """
        # Resolve model via REST before touching SDK (avoids SDK "no default model" err)
        resolved = model or self._default_model or self.get_loaded_model_id()
        try:
            import lmstudio as lms
            handle = lms.llm(resolved) if resolved else lms.llm()
            return handle.count_tokens(text)
        except Exception:
            return max(1, len(text) // 4)

    def get_context_length(self, model: Optional[str] = None) -> int:
        """Get the context length of the loaded model.

        Falls back to 4096 if the SDK is unavailable or no model is loaded.
        Uses the first loaded model when ``model`` is None to avoid the SDK
        "default model not being a thing" error.
        """
        resolved = model or self._default_model or self.get_loaded_model_id()
        try:
            import lmstudio as lms
            handle = lms.llm(resolved) if resolved else lms.llm()
            return handle.get_context_length()
        except Exception:
            return 4096

    # ── Benchmarking ──────────────────────────────────────────────────

    def benchmark_model(
        self,
        messages: List[Dict[str, str]],
        *,
        n_runs: int = 10,
        models: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Run ``n_runs`` completions and return latency/throughput statistics.

        If ``models`` is a list, benchmark each model separately and include
        a per-model breakdown.  Useful for A/B comparisons.

        Args:
            messages:    Prompt to use for every run.
            n_runs:      Number of completions per model (default 10).
            models:      List of model IDs to test (default: current loaded model).
            temperature: Sampling temperature for benchmark runs.
            max_tokens:  Max tokens per run.

        Returns:
            Dict with keys ``total_runs``, ``models_tested``, ``results``
            (per-model stats: count, avg_latency_ms, p50_ms, p95_ms,
            avg_tokens_out, avg_tps, errors).
        """
        import statistics

        target_models = models or [self.resolve_model()]
        all_results: Dict[str, Any] = {}

        for mdl in target_models:
            latencies: List[float] = []
            tps_list: List[float] = []
            toks_out: List[int] = []
            errors = 0

            for i in range(n_runs):
                try:
                    resp = self.chat(
                        messages,
                        model=mdl,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    latencies.append(resp.latency_ms)
                    toks_out.append(resp.output_tokens)
                    if resp.tokens_per_second > 0:
                        tps_list.append(resp.tokens_per_second)
                    logger.debug("benchmark %s run %d/%d: %.0fms", mdl, i + 1, n_runs, resp.latency_ms)
                except Exception as exc:
                    errors += 1
                    logger.warning("benchmark run %d failed: %s", i + 1, exc)

            if latencies:
                sorted_lat = sorted(latencies)
                n = len(sorted_lat)
                all_results[mdl] = {
                    "count": n,
                    "errors": errors,
                    "avg_latency_ms": round(statistics.mean(sorted_lat), 1),
                    "p50_ms": round(sorted_lat[n // 2], 1),
                    "p95_ms": round(sorted_lat[min(int(n * 0.95), n - 1)], 1),
                    "min_ms": round(sorted_lat[0], 1),
                    "max_ms": round(sorted_lat[-1], 1),
                    "avg_tokens_out": round(statistics.mean(toks_out), 1) if toks_out else 0,
                    "avg_tps": round(statistics.mean(tps_list), 2) if tps_list else 0.0,
                    "stddev_ms": round(statistics.stdev(sorted_lat), 1) if n > 1 else 0.0,
                }
            else:
                all_results[mdl] = {"count": 0, "errors": errors}

        return {
            "total_runs": n_runs * len(target_models),
            "models_tested": target_models,
            "results": all_results,
        }

    def concurrent_chat(
        self,
        messages_list: List[List[Dict[str, str]]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_workers: Optional[int] = None,
    ) -> List[Any]:
        """
        Run multiple chat requests concurrently using ``ConcurrentExecutor``.

        Args:
            messages_list: Each element is a full messages list for one request.
            model:         Model to use for all requests.
            temperature:   Temperature for all requests.
            max_tokens:    Max tokens for all requests.
            max_workers:   Override the thread-pool size.

        Returns:
            List of ``ConcurrentResult`` objects (one per input).
        """
        from engine.lmstudio.concurrency import get_executor

        executor = get_executor()
        if max_workers:
            executor.max_workers = max_workers

        tasks = [
            {
                "messages": msgs,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            for msgs in messages_list
        ]
        return executor.parallel_tasks(tasks)

    # ── Internal ──────────────────────────────────────────────────────

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        integrations: Optional[List[Dict]] = None,
        response_format: Optional[Dict] = None,
        tools: Optional[List[Dict]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        # Auto-resolve: pick the actually-loaded model; fallback to hint/config
        resolved = self.resolve_model(model)
        payload: Dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._default_temp,
            "max_tokens": max_tokens if max_tokens is not None else self._default_max_tokens,
            "stream": stream,
        }

        if integrations and self._mcp_enabled:
            payload["integrations"] = integrations

        if response_format:
            payload["response_format"] = response_format

        if tools:
            payload["tools"] = tools

        return payload

    def __repr__(self) -> str:
        return f"<LMStudioClient url={self.base_url} mcp={self._mcp_enabled}>"

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass


# ── Module-level singleton ─────────────────────────────────────────────

_client_instance: Optional[LMStudioClient] = None


def get_lmstudio_client(**kwargs) -> LMStudioClient:
    """Return the global LMStudioClient singleton."""
    global _client_instance
    if _client_instance is None:
        _client_instance = LMStudioClient(**kwargs)
    return _client_instance
