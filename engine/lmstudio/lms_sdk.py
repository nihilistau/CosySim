"""
LMS SDK Wrapper — High-level Python SDK interface for LMStudio

Wraps the ``lmstudio`` Python SDK for features not available via REST:

* ``respond()`` — Chat with progress callbacks
* ``act()`` — Multi-round tool calling with automatic loop
* ``complete()`` — Raw text completion (useful for terminal simulation)
* Model info & context length queries
* Load/unload with full ``LoadConfig``
* Cancellation support

The SDK uses WebSocket internally and is best for:
- Complex multi-round tool calling (``act()``)
- Streaming with fine-grained progress callbacks
- Speculative decoding configuration
- Operations that need the full SDK feature set

For simple chat/streaming, prefer ``LMSClient`` (REST) as it's lighter.

Usage::

    from engine.lmstudio.lms_sdk import get_lms_sdk

    sdk = get_lms_sdk()
    reply = sdk.respond("Hello!")
    reply = sdk.act("Search for information", tools=[my_tool])
    reply = sdk.complete("Once upon a time")
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from engine.lmstudio.inference_config import InferenceConfig, LoadConfig

logger = logging.getLogger(__name__)


class LMSSDKWrapper:
    """
    Wrapper around the ``lmstudio`` Python SDK.

    Lazy-imports the SDK so the rest of the codebase doesn't fail if
    the ``lmstudio`` package is not installed.
    """

    def __init__(self, config=None) -> None:
        if config is None:
            try:
                from engine.config import get_config
                config = get_config()
            except Exception:
                config = None

        self._config = config
        self._default_model = (config.get("llm.model", "") if config else "")
        self._sdk = None
        self._lock = threading.Lock()

    @property
    def sdk_available(self) -> bool:
        """Check if the lmstudio SDK is installed."""
        try:
            import lmstudio
            return True
        except ImportError:
            return False

    def _get_llm(self, model: Optional[str] = None):
        """Get an LLM handle from the SDK."""
        import lmstudio as lms
        target = model or self._default_model
        if target:
            return lms.llm(target)
        return lms.llm()

    # ── Chat / Respond ──────────────────────────────────────────────

    def respond(
        self,
        messages_or_text: Any,
        *,
        model: Optional[str] = None,
        config: Optional[InferenceConfig] = None,
        on_fragment: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Chat using SDK's respond(). Returns complete text.

        Args:
            messages_or_text: Either a string (converted to user message)
                or a list of message dicts.
            model: Model identifier.
            config: Inference parameters.
            on_fragment: Called with each text fragment for streaming display.
        """
        try:
            llm = self._get_llm(model)

            # Build config dict for SDK
            sdk_config = self._build_sdk_config(config)

            if isinstance(messages_or_text, str):
                messages_or_text = [{"role": "user", "content": messages_or_text}]

            result = llm.respond(
                messages_or_text,
                config=sdk_config if sdk_config else None,
                on_fragment=on_fragment,
            )
            return str(result)
        except ImportError:
            logger.error("lmstudio SDK not installed — pip install lmstudio")
            raise
        except Exception as exc:
            logger.error("SDK respond failed: %s", exc)
            raise

    # ── Act (multi-round tool calling) ──────────────────────────────

    def act(
        self,
        instruction: str,
        tools: List[Any],
        *,
        model: Optional[str] = None,
        config: Optional[InferenceConfig] = None,
        on_message: Optional[Callable] = None,
        on_tool_call: Optional[Callable] = None,
        max_rounds: int = 10,
    ) -> str:
        """
        Multi-round tool calling via SDK's act().

        The SDK handles the full loop: generate → tool call → result → generate.

        Args:
            instruction: The initial instruction/prompt.
            tools: List of tool callables or ToolSpec objects.
            model: Model identifier.
            config: Inference parameters.
            on_message: Callback for each message in the conversation.
            on_tool_call: Callback when a tool is called.
            max_rounds: Maximum conversation rounds.
        """
        try:
            llm = self._get_llm(model)

            # Convert ToolSpec to plain callables if needed
            tool_fns = []
            for t in tools:
                if hasattr(t, 'fn'):  # ToolSpec
                    tool_fns.append(t.fn)
                elif callable(t):
                    tool_fns.append(t)

            result = llm.act(
                instruction,
                tools=tool_fns,
                on_message=on_message,
                max_round_trips=max_rounds,
            )
            return str(result)
        except ImportError:
            logger.error("lmstudio SDK not installed — pip install lmstudio")
            raise
        except Exception as exc:
            logger.error("SDK act failed: %s", exc)
            raise

    # ── Complete (raw completion) ───────────────────────────────────

    def complete(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        config: Optional[InferenceConfig] = None,
        on_fragment: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Raw text completion (no chat template).

        Useful for:
        - Terminal simulation
        - Code completion
        - Fill-in-the-middle tasks
        """
        try:
            llm = self._get_llm(model)
            sdk_config = self._build_sdk_config(config)

            result = llm.complete(
                prompt,
                config=sdk_config if sdk_config else None,
                on_fragment=on_fragment,
            )
            return str(result)
        except ImportError:
            logger.error("lmstudio SDK not installed — pip install lmstudio")
            raise
        except Exception as exc:
            logger.error("SDK complete failed: %s", exc)
            raise

    # ── Model info ──────────────────────────────────────────────────

    def get_context_length(self, model: Optional[str] = None) -> int:
        """Get the context length of a loaded model."""
        try:
            llm = self._get_llm(model)
            return llm.get_context_length()
        except Exception:
            return 4096

    def get_model_info(self, model: Optional[str] = None) -> Dict[str, Any]:
        """Get model metadata."""
        try:
            llm = self._get_llm(model)
            info = llm.get_model_info()
            return {
                "identifier": getattr(info, "identifier", ""),
                "architecture": getattr(info, "architecture", ""),
                "parameters": getattr(info, "parameters", ""),
                "context_length": self.get_context_length(model),
            }
        except Exception as exc:
            logger.debug("get_model_info failed: %s", exc)
            return {}

    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """Count tokens for text."""
        try:
            llm = self._get_llm(model)
            return llm.count_tokens(text)
        except Exception:
            return max(1, len(text) // 4)

    # ── Model lifecycle ─────────────────────────────────────────────

    def load_model(
        self,
        model_id: str,
        *,
        config: Optional[LoadConfig] = None,
    ) -> bool:
        """Load a model via SDK."""
        try:
            import lmstudio as lms
            load_opts = {}
            if config:
                if config.context_length:
                    load_opts["context_length"] = config.context_length
                if config.gpu_offload is not None:
                    load_opts["gpu_offload"] = config.gpu_offload
            lms.load_new_instance(model_id, **load_opts)
            logger.info("Model loaded via SDK: %s", model_id)
            return True
        except Exception as exc:
            logger.error("SDK load failed: %s", exc)
            return False

    def unload_model(self, model_id: str) -> bool:
        """Unload a model via SDK."""
        try:
            import lmstudio as lms
            handle = lms.llm(model_id)
            handle.unload()
            logger.info("Model unloaded via SDK: %s", model_id)
            return True
        except Exception as exc:
            logger.error("SDK unload failed: %s", exc)
            return False

    # ── Internal helpers ────────────────────────────────────────────

    def _build_sdk_config(self, config: Optional[InferenceConfig] = None) -> Optional[Dict]:
        """Build SDK config dict from InferenceConfig."""
        if config is None:
            return None

        d: Dict[str, Any] = {}
        if config.temperature is not None:
            d["temperature"] = config.temperature
        if config.top_p is not None:
            d["top_p"] = config.top_p
        if config.top_k is not None:
            d["top_k"] = config.top_k
        if config.min_p is not None:
            d["min_p"] = config.min_p
        if config.repeat_penalty is not None:
            d["repeat_penalty"] = config.repeat_penalty
        if config.max_output_tokens is not None:
            d["max_tokens"] = config.max_output_tokens
        if config.stop_strings:
            d["stop"] = config.stop_strings
        if config.response_format:
            d["response_format"] = config.response_format
        if config.draft_model:
            d["draft_model"] = config.draft_model

        return d if d else None


# ── Singleton ───────────────────────────────────────────────────────────

_sdk_instance: Optional[LMSSDKWrapper] = None


def get_lms_sdk(**kwargs) -> LMSSDKWrapper:
    """Return the global LMSSDKWrapper singleton."""
    global _sdk_instance
    if _sdk_instance is None:
        _sdk_instance = LMSSDKWrapper(**kwargs)
    return _sdk_instance
