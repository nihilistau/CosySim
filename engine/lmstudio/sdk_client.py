"""
SDKClient — LMStudio Python SDK integration layer for CosySim

Provides a persistent WebSocket-based connection to LMStudio via the official
``lmstudio`` SDK (v1.5.0+).  Wraps all SDK capabilities and maps them to
CosySim's existing ``LMSResponse`` / ``LMSStreamEvent`` types so that
downstream code (scenes, agents, pipeline) needs zero changes.

Three usage modes:

1. **respond** — single-shot chat completion (blocking or streaming)
2. **act** — multi-round autonomous tool calling via ``.act()``
3. **model management** — load/unload/list via SDK instead of CLI subprocess

The SDK uses a persistent WebSocket to LMStudio (auto-discovered on LMS's
internal ports), which avoids the per-request HTTP overhead of the REST API.

Design principles:
- Singleton pattern via ``get_sdk_client()``
- Thread-safe (SDK manages its own event loop)
- Graceful degradation — if SDK connection fails, callers should fall back
  to the REST ``LMSClient``
- All results mapped to ``LMSResponse`` for seamless integration
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import (
    Any, Callable, Dict, Generator, Iterable, List, Optional, Tuple, Union,
)

logger = logging.getLogger(__name__)

# ── SDK import with graceful fallback ────────────────────────────────
try:
    import lmstudio as lms
    SDK_AVAILABLE = True
except ImportError:
    lms = None  # type: ignore[assignment]
    SDK_AVAILABLE = False
    logger.info("lmstudio SDK not installed — SDK channel disabled")


# ── Lazy imports (avoid circular deps at module level) ───────────────
def _LMSResponse():
    from .lms_client import LMSResponse
    return LMSResponse

def _LMSStreamEvent():
    from .lms_client import LMSStreamEvent
    return LMSStreamEvent

def _InferenceConfig():
    from .inference_config import InferenceConfig
    return InferenceConfig


# ── Result container for .act() calls ────────────────────────────────
@dataclass
class ActRoundInfo:
    """Metadata from a single .act() prediction round."""
    round_index: int = 0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    content: str = ""


# ── The SDK Client ───────────────────────────────────────────────────

class SDKClient:
    """
    Persistent WebSocket connection to LMStudio via the Python SDK.

    Parameters
    ----------
    api_host : str or None
        Explicit LMStudio SDK host (e.g. ``"127.0.0.1:41343"``).
        If None, the SDK auto-discovers LMStudio on its default ports.
    """

    def __init__(self, api_host: Optional[str] = None) -> None:
        if not SDK_AVAILABLE:
            raise RuntimeError("lmstudio SDK is not installed")

        self._api_host = api_host
        self._client: Optional[lms.Client] = None
        self._lock = threading.Lock()
        # Cache model handles to avoid repeated lookups
        self._model_handles: Dict[str, Any] = {}

    # ─────────────────────────────────── connection lifecycle ──

    def _ensure_connected(self) -> lms.Client:
        """Lazily create and return the SDK client."""
        if self._client is not None:
            return self._client

        with self._lock:
            if self._client is not None:
                return self._client
            try:
                self._client = lms.Client(self._api_host)
                logger.info("SDK connected to LMStudio (host=%s)", self._api_host or "auto")
            except Exception as exc:
                logger.error("SDK connection failed: %s", exc)
                raise
            return self._client

    @property
    def connected(self) -> bool:
        """Return True if the SDK client is connected."""
        return self._client is not None

    def close(self) -> None:
        """Close the SDK connection and clear cached handles."""
        with self._lock:
            self._model_handles.clear()
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None
                logger.info("SDK connection closed")

    # ──────────────────────────────────── model handle cache ──

    def get_model(self, model_key: Optional[str] = None) -> Any:
        """
        Get an LLM handle for the given model key.

        If *model_key* is None, returns a handle to any loaded model
        (equivalent to ``lms.llm()``).
        """
        cache_key = model_key or "__default__"
        if cache_key in self._model_handles:
            return self._model_handles[cache_key]

        client = self._ensure_connected()
        try:
            if model_key:
                handle = client.llm.model(model_key)
            else:
                handle = client.llm.model()
            self._model_handles[cache_key] = handle
            logger.debug("Cached model handle for %s", cache_key)
            return handle
        except Exception as exc:
            logger.error("Failed to get model handle '%s': %s", cache_key, exc)
            raise

    def load_instance(
        self,
        model_key: str,
        *,
        instance_id: Optional[str] = None,
        ttl: Optional[int] = 3600,
        context_length: Optional[int] = None,
        gpu_offload: Optional[Any] = None,
        flash_attention: Optional[bool] = None,
        eval_batch_size: Optional[int] = None,
    ) -> Any:
        """
        Load a new model instance with explicit config.

        Uses ``DownloadedLlm.load_new_instance()`` to create a separate
        model instance with its own KV cache — essential for agent identity
        isolation.

        Returns the LLM handle for the new instance.
        """
        client = self._ensure_connected()
        downloaded = client.llm.model(model_key)

        load_config: Dict[str, Any] = {}
        if context_length is not None:
            load_config["context_length"] = context_length
        if gpu_offload is not None:
            load_config["gpu"] = {"ratio": gpu_offload} if isinstance(gpu_offload, (int, float)) else gpu_offload
        if flash_attention is not None:
            load_config["flash_attention"] = flash_attention
        if eval_batch_size is not None:
            load_config["eval_batch_size"] = eval_batch_size

        try:
            handle = downloaded.load_new_instance(
                instance_identifier=instance_id,
                ttl=ttl,
                config=load_config or None,
            )
            cache_key = instance_id or model_key
            self._model_handles[cache_key] = handle
            logger.info("Loaded new instance: %s (id=%s, ttl=%s)", model_key, instance_id, ttl)
            return handle
        except Exception as exc:
            logger.error("Failed to load instance '%s': %s", model_key, exc)
            raise

    def unload_model(self, model_key: str) -> None:
        """Unload a model by its key or instance ID."""
        handle = self._model_handles.pop(model_key, None)
        if handle is None:
            handle = self.get_model(model_key)
        try:
            handle.unload()
            logger.info("Unloaded model: %s", model_key)
        except Exception as exc:
            logger.warning("Failed to unload '%s': %s", model_key, exc)

    def list_loaded(self) -> List[Dict[str, Any]]:
        """Return info about all loaded models."""
        client = self._ensure_connected()
        try:
            models = client.list_loaded_models()
            return [
                {
                    "model_key": str(m),
                    "type": getattr(m, "type", "llm"),
                }
                for m in models
            ]
        except Exception as exc:
            logger.error("list_loaded failed: %s", exc)
            return []

    def list_downloaded(self) -> List[Dict[str, Any]]:
        """Return info about all downloaded models."""
        client = self._ensure_connected()
        try:
            models = client.list_downloaded_models()
            return [{"model_key": str(m)} for m in models]
        except Exception as exc:
            logger.error("list_downloaded failed: %s", exc)
            return []

    # ────────────────────────────────── config translation ──

    @staticmethod
    def inference_config_to_sdk(config) -> Dict[str, Any]:
        """
        Translate a CosySim ``InferenceConfig`` to an SDK ``LlmPredictionConfig`` dict.

        Only includes fields that the SDK accepts.
        """
        d: Dict[str, Any] = {}
        if config.temperature is not None:
            d["temperature"] = config.temperature
        if config.top_p is not None:
            d["top_p_sampling"] = config.top_p
        if config.top_k is not None:
            d["top_k_sampling"] = config.top_k
        if config.min_p is not None:
            d["min_p_sampling"] = config.min_p
        if config.repeat_penalty is not None:
            d["repeat_penalty"] = config.repeat_penalty
        if config.max_output_tokens is not None:
            d["max_tokens"] = config.max_output_tokens
        if config.stop_strings:
            d["stop_strings"] = config.stop_strings
        if config.draft_model:
            d["draft_model"] = config.draft_model
        if config.response_format:
            d["structured"] = config.response_format
        return d

    @staticmethod
    def load_config_to_sdk(config) -> Dict[str, Any]:
        """Translate a CosySim ``LoadConfig`` to an SDK ``LlmLoadModelConfig`` dict."""
        d: Dict[str, Any] = {}
        if config.context_length is not None:
            d["context_length"] = config.context_length
        if config.gpu_offload is not None:
            if isinstance(config.gpu_offload, (int, float)):
                d["gpu"] = {"ratio": config.gpu_offload}
            elif config.gpu_offload == "max":
                d["gpu"] = {"ratio": 1.0}
            elif config.gpu_offload == "off":
                d["gpu"] = {"ratio": 0.0}
        if config.flash_attention is not None:
            d["flash_attention"] = config.flash_attention
        if config.eval_batch_size is not None:
            d["eval_batch_size"] = config.eval_batch_size
        return d

    # ──────────────────────────────────── respond (blocking) ──

    def respond(
        self,
        messages: Union[List[Dict], str],
        *,
        model_key: Optional[str] = None,
        config: Optional[Any] = None,
        on_first_token: Optional[Callable] = None,
        on_fragment: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
    ):
        """
        Blocking chat completion via SDK.

        Parameters
        ----------
        messages : list[dict] or str
            Either a list of ``{"role": "...", "content": "..."}`` dicts
            or a plain string (wrapped as a user message).
        model_key : str, optional
            Model to use.  If None, uses any loaded model.
        config : InferenceConfig, optional
            CosySim inference config (auto-translated to SDK format).
        on_first_token, on_fragment, on_progress : callable, optional
            SDK callbacks for real-time updates.

        Returns
        -------
        LMSResponse
            Compatible with the existing REST client's return type.
        """
        LMSResponse = _LMSResponse()
        t0 = time.time()

        llm = self.get_model(model_key)
        chat = self._build_chat(messages)
        sdk_config = self.inference_config_to_sdk(config) if config else None

        kwargs: Dict[str, Any] = {}
        if sdk_config:
            kwargs["config"] = sdk_config
        if on_first_token:
            kwargs["on_first_token"] = on_first_token
        if on_fragment:
            kwargs["on_prediction_fragment"] = on_fragment
        if on_progress:
            kwargs["on_prompt_processing_progress"] = on_progress

        try:
            result = llm.respond(chat, **kwargs)
            latency_ms = (time.time() - t0) * 1000

            stats = result.stats
            spec_decode_stats = {}
            if stats:
                accepted = getattr(stats, "accepted_draft_tokens_count", 0)
                rejected = getattr(stats, "rejected_draft_tokens_count", 0)
                total_draft = getattr(stats, "total_draft_tokens_count", 0)
                draft_model = getattr(stats, "used_draft_model_key", "")
                if total_draft > 0:
                    spec_decode_stats = {
                        "accepted": accepted,
                        "rejected": rejected,
                        "total_draft": total_draft,
                        "acceptance_ratio": accepted / total_draft if total_draft else 0,
                        "draft_model": draft_model,
                    }

            resp = LMSResponse(
                content=result.content,
                model=getattr(result.model_info, "display_name", model_key or ""),
                finish_reason=getattr(stats, "stop_reason", "stop") if stats else "stop",
                input_tokens=getattr(stats, "prompt_tokens_count", 0) if stats else 0,
                output_tokens=getattr(stats, "predicted_tokens_count", 0) if stats else 0,
                total_tokens=getattr(stats, "total_tokens_count", 0) if stats else 0,
                latency_ms=latency_ms,
                server_tps=getattr(stats, "tokens_per_second", 0.0) if stats else 0.0,
                time_to_first_token_s=getattr(stats, "time_to_first_token_sec", 0.0) if stats else 0.0,
                reasoning_content=getattr(result, "reasoning_content", ""),
            )
            # Attach spec decode stats as extra attribute (not in dataclass)
            if spec_decode_stats:
                resp.spec_decode_stats = spec_decode_stats
            return resp
        except Exception as exc:
            logger.error("SDK respond failed: %s", exc)
            return LMSResponse(content=f"[SDK Error] {exc}", latency_ms=(time.time() - t0) * 1000)

    # ──────────────────────────────────── respond_stream ──

    def respond_stream(
        self,
        messages: Union[List[Dict], str],
        *,
        model_key: Optional[str] = None,
        config: Optional[Any] = None,
    ) -> Generator:
        """
        Streaming chat completion via SDK.

        Yields ``LMSStreamEvent``-compatible objects so that the existing
        ``StreamProcessor`` can consume them without changes.
        """
        LMSStreamEvent = _LMSStreamEvent()

        llm = self.get_model(model_key)
        chat = self._build_chat(messages)
        sdk_config = self.inference_config_to_sdk(config) if config else None

        kwargs: Dict[str, Any] = {}
        if sdk_config:
            kwargs["config"] = sdk_config

        try:
            stream = llm.respond_stream(chat, **kwargs)

            # Emit a chat.start event
            yield LMSStreamEvent(
                event_type="chat.start",
                model_instance_id=model_key or "",
            )

            for fragment in stream:
                text = getattr(fragment, "content", str(fragment))
                if text:
                    yield LMSStreamEvent(
                        event_type="message.delta",
                        content=text,
                    )

            # Wait for the final result
            result = stream.result()
            stats = result.stats if hasattr(result, "stats") else None

            # Emit chat.end
            yield LMSStreamEvent(
                event_type="chat.end",
                is_done=True,
                stats={
                    "tokens_per_second": getattr(stats, "tokens_per_second", 0.0) if stats else 0.0,
                    "predicted_tokens_count": getattr(stats, "predicted_tokens_count", 0) if stats else 0,
                    "prompt_tokens_count": getattr(stats, "prompt_tokens_count", 0) if stats else 0,
                    "time_to_first_token_sec": getattr(stats, "time_to_first_token_sec", 0.0) if stats else 0.0,
                    "accepted_draft_tokens_count": getattr(stats, "accepted_draft_tokens_count", 0) if stats else 0,
                    "rejected_draft_tokens_count": getattr(stats, "rejected_draft_tokens_count", 0) if stats else 0,
                } if stats else None,
            )

        except Exception as exc:
            logger.error("SDK respond_stream failed: %s", exc)
            yield LMSStreamEvent(
                event_type="error",
                error={"message": str(exc)},
                is_done=True,
            )

    # ──────────────────────────────────── act (tool calling) ──

    def act(
        self,
        messages: Union[List[Dict], str],
        tools: Iterable,
        *,
        model_key: Optional[str] = None,
        config: Optional[Any] = None,
        max_rounds: Optional[int] = None,
        max_parallel_tools: int = 1,
        on_round_start: Optional[Callable] = None,
        on_round_end: Optional[Callable] = None,
        on_prediction_completed: Optional[Callable] = None,
        on_message: Optional[Callable] = None,
        on_fragment: Optional[Callable] = None,
        handle_invalid_tool: Optional[Callable] = None,
    ):
        """
        Multi-round autonomous tool calling via SDK ``.act()``.

        This is the big feature — the LLM autonomously calls tools over
        multiple rounds until it produces a final text response.  No MCP
        server round-trips needed.

        Parameters
        ----------
        tools : iterable
            Collection of tools.  Can be:
            - Plain Python callables (auto-wrapped by SDK)
            - ``lms.ToolFunctionDef`` objects
            - ``ToolSpec`` objects (from our tool_factory — unwrapped to callables)
        max_rounds : int, optional
            Maximum number of prediction rounds (default: SDK default).
        max_parallel_tools : int
            How many tools can execute in parallel per round.

        Returns
        -------
        LMSResponse
            With ``content`` = final text and ``tool_calls`` = all executed calls.
        """
        LMSResponse = _LMSResponse()
        t0 = time.time()

        llm = self.get_model(model_key)
        chat = self._build_chat(messages)
        sdk_config = self.inference_config_to_sdk(config) if config else None

        # Unwrap ToolSpec objects to their callables
        unwrapped_tools = []
        for t in tools:
            if hasattr(t, "fn"):
                unwrapped_tools.append(t.fn)
            elif hasattr(t, "implementation"):
                unwrapped_tools.append(t)
            elif callable(t):
                unwrapped_tools.append(t)
            else:
                logger.warning("Skipping non-callable tool: %s", t)

        # Build .act() kwargs
        kwargs: Dict[str, Any] = {
            "max_parallel_tool_calls": max_parallel_tools,
        }
        if sdk_config:
            kwargs["config"] = sdk_config
        if max_rounds is not None:
            kwargs["max_prediction_rounds"] = max_rounds
        if on_round_start:
            kwargs["on_round_start"] = on_round_start
        if on_round_end:
            kwargs["on_round_end"] = on_round_end
        if on_prediction_completed:
            kwargs["on_prediction_completed"] = on_prediction_completed
        if on_message:
            kwargs["on_message"] = on_message
        if on_fragment:
            kwargs["on_prediction_fragment"] = on_fragment
        if handle_invalid_tool:
            kwargs["handle_invalid_tool_request"] = handle_invalid_tool

        # Collect tool call info from callbacks
        all_tool_calls: List[Dict] = []
        round_count = 0

        def _on_round_end_internal(idx: int) -> None:
            nonlocal round_count
            round_count = idx + 1
            if on_round_end:
                on_round_end(idx)

        kwargs["on_round_end"] = _on_round_end_internal

        try:
            act_result = llm.act(chat, unwrapped_tools, **kwargs)
            latency_ms = (time.time() - t0) * 1000

            # Extract content from the last round
            content = ""
            for round_info in act_result.rounds:
                if hasattr(round_info, "content") and round_info.content:
                    content = round_info.content

            return LMSResponse(
                content=content,
                model=model_key or "",
                latency_ms=latency_ms,
                tool_calls=all_tool_calls,
            )
        except Exception as exc:
            logger.error("SDK act failed: %s", exc)
            return LMSResponse(
                content=f"[SDK Act Error] {exc}",
                latency_ms=(time.time() - t0) * 1000,
                tool_calls=all_tool_calls,
            )

    # ──────────────────────────────────── complete (raw) ──

    def complete(
        self,
        prompt: str,
        *,
        model_key: Optional[str] = None,
        config: Optional[Any] = None,
    ):
        """
        Raw text completion (no chat template applied).

        Returns
        -------
        LMSResponse
        """
        LMSResponse = _LMSResponse()
        t0 = time.time()

        llm = self.get_model(model_key)
        sdk_config = self.inference_config_to_sdk(config) if config else None

        kwargs: Dict[str, Any] = {}
        if sdk_config:
            kwargs["config"] = sdk_config

        try:
            result = llm.complete(prompt, **kwargs)
            latency_ms = (time.time() - t0) * 1000

            stats = result.stats
            return LMSResponse(
                content=result.content,
                model=model_key or "",
                latency_ms=latency_ms,
                input_tokens=getattr(stats, "prompt_tokens_count", 0) if stats else 0,
                output_tokens=getattr(stats, "predicted_tokens_count", 0) if stats else 0,
                total_tokens=getattr(stats, "total_tokens_count", 0) if stats else 0,
                server_tps=getattr(stats, "tokens_per_second", 0.0) if stats else 0.0,
            )
        except Exception as exc:
            logger.error("SDK complete failed: %s", exc)
            return LMSResponse(content=f"[SDK Error] {exc}", latency_ms=(time.time() - t0) * 1000)

    # ──────────────────────────────────── embeddings ──

    def embed(
        self,
        text: Union[str, List[str]],
        *,
        model_key: Optional[str] = None,
    ) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings using a loaded embedding model.

        Parameters
        ----------
        text : str or list[str]
            Text(s) to embed.
        model_key : str, optional
            Embedding model key.  If None, uses any loaded embedding model.

        Returns
        -------
        list[float] or list[list[float]]
        """
        client = self._ensure_connected()
        try:
            if model_key:
                emb_model = client.embedding.model(model_key)
            else:
                emb_model = client.embedding.model()

            if isinstance(text, str):
                return emb_model.embed(text)
            else:
                return [emb_model.embed(t) for t in text]
        except Exception as exc:
            logger.error("SDK embed failed: %s", exc)
            raise

    # ──────────────────────────────────── model info ──

    def get_model_info(self, model_key: Optional[str] = None) -> Dict[str, Any]:
        """Return model info dict (context length, capabilities, etc.)."""
        try:
            handle = self.get_model(model_key)
            info = handle.get_info()
            return {
                "model_key": str(info) if info else model_key,
                "context_length": handle.get_context_length() if hasattr(handle, "get_context_length") else None,
            }
        except Exception as exc:
            logger.debug("get_model_info failed: %s", exc)
            return {"model_key": model_key, "error": str(exc)}

    def count_tokens(self, text: str, *, model_key: Optional[str] = None) -> int:
        """Count tokens in text using the model's tokenizer."""
        try:
            handle = self.get_model(model_key)
            return handle.count_tokens(text)
        except Exception as exc:
            logger.debug("count_tokens failed: %s", exc)
            return -1

    # ──────────────────────────────────── internals ──

    @staticmethod
    def _build_chat(messages: Union[List[Dict], str]) -> Any:
        """
        Convert message list or string to an ``lms.Chat`` object.

        Supports:
        - Plain string → single user message
        - List of dicts with role/content → full chat history
        """
        if not SDK_AVAILABLE:
            raise RuntimeError("lmstudio SDK not available")

        if isinstance(messages, str):
            return messages  # SDK accepts plain strings

        chat = lms.Chat()
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                chat.add_system_prompt(content)
            elif role == "user":
                chat.add_user_message(content)
            elif role == "assistant":
                chat.add_assistant_response(content)
            elif role == "tool":
                # Tool results from previous .act() rounds
                chat.add_tool_result(content)
            else:
                chat.add_user_message(content)
        return chat


# ── Singleton ────────────────────────────────────────────────────────

_sdk_client: Optional[SDKClient] = None
_sdk_lock = threading.Lock()


def get_sdk_client(api_host: Optional[str] = None) -> Optional[SDKClient]:
    """
    Return the global SDKClient singleton.

    Returns None if the ``lmstudio`` package is not installed.
    """
    global _sdk_client
    if not SDK_AVAILABLE:
        return None

    if _sdk_client is not None:
        return _sdk_client

    with _sdk_lock:
        if _sdk_client is not None:
            return _sdk_client
        try:
            _sdk_client = SDKClient(api_host=api_host)
            return _sdk_client
        except Exception as exc:
            logger.error("Failed to create SDK client: %s", exc)
            return None
